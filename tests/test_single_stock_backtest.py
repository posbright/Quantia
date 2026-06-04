#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""单股区间买卖点回测单元测试（document/backtest/single_stock_backtest_dev_plan.md）。"""

import json
import os
import sys
import unittest
from contextlib import contextmanager
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from tornado.testing import AsyncHTTPTestCase
from tornado.web import Application

from quantia.web import backtestHandler as bh


def _make_hist(prices, start='2026-01-01'):
    """构造连续交易日的 K 线 DataFrame。prices 为收盘价序列。"""
    dates = pd.bdate_range(start=start, periods=len(prices))
    closes = np.array(prices, dtype='float64')
    return pd.DataFrame({
        'date': dates,
        'open': closes,        # 简化：开盘=收盘，便于按收益预测
        'close': closes,
        'low': closes * 0.99,
        'high': closes * 1.01,
        'volume': np.full(len(prices), 10000.0),
        'p_change': np.zeros(len(prices)),
    })


class RunSingleBacktestTests(unittest.TestCase):
    def setUp(self):
        # 一段单调上涨的价格，便于固定持仓产生确定收益
        self.prices = [10.0 + i * 0.1 for i in range(80)]
        self.hist = _make_hist(self.prices)

    def _patch(self, hit_dates):
        """hit_dates: 命中买入信号的日期索引集合。返回单一上下文管理器。"""
        def fake_strategy(stock, hist, date=None, **kw):
            ts = pd.Timestamp(date)
            idx = self.hist.index[self.hist['date'] == ts]
            if len(idx) == 0:
                return False
            return int(idx[0]) in hit_dates

        @contextmanager
        def _ctx():
            with mock.patch.object(bh, '_resolve_single_strategy',
                                   return_value=(fake_strategy, '测试策略')), \
                 mock.patch.object(bh, '_get_stock_name', return_value='测试股'), \
                 mock.patch.object(bh.stf, 'read_stock_hist_from_cache', return_value=self.hist), \
                 mock.patch.object(bh.idr, 'get_indicators', return_value=self.hist):
                yield
        return _ctx()

    def test_index_code_rejected(self):
        res = bh._run_single_backtest('399001', 'cn_stock_strategy_keep_increasing',
                                      '2026-01-01', '2026-03-01', hold_days=5)
        self.assertIn('error', res)
        self.assertIn('指数', res['error'])

    def test_unknown_strategy_rejected(self):
        with mock.patch.object(bh.stf, 'read_stock_hist_from_cache', return_value=self.hist):
            res = bh._run_single_backtest('000001', 'indicators_buy',
                                          '2026-01-01', '2026-03-01', hold_days=5)
        self.assertIn('error', res)

    def test_fixed_hold_produces_closed_trades(self):
        with self._patch({5, 30}):
            res = bh._run_single_backtest('000001', 'cn_stock_strategy_keep_increasing',
                                          '2026-01-01', '2026-05-30', hold_days=5)
        self.assertNotIn('error', res)
        self.assertEqual(res['exit_mode'], 'fixed')
        self.assertEqual(res['hold_days'], 5)
        self.assertTrue(len(res['trades']) >= 1)
        t = res['trades'][0]
        self.assertEqual(t['status'], 'closed')
        self.assertEqual(t['hold_days'], 5)
        # 上涨行情：扣费后仍盈利
        self.assertGreater(t['rate'], 0)
        self.assertEqual(t['exit_reason'], 'hold_expired')

    def test_hold_days_one(self):
        with self._patch({10}):
            res = bh._run_single_backtest('000001', 'cn_stock_strategy_keep_increasing',
                                          '2026-01-01', '2026-05-30', hold_days=1)
        self.assertNotIn('error', res)
        self.assertEqual(res['trades'][0]['hold_days'], 1)

    def test_winrate_excludes_open_trade(self):
        # 让最后一个信号靠近区间末，固定持仓无法到期 → open
        last_idx = len(self.prices) - 2  # 倒数第二根，T+1 是最后一根，hold 5 无法到期
        with self._patch({5, 30, last_idx}):
            res = bh._run_single_backtest('000001', 'cn_stock_strategy_keep_increasing',
                                          '2026-01-01', '2026-12-30', hold_days=5)
        s = res['summary']
        self.assertEqual(s['trade_count'], s['closed_count'] + s['open_count'])
        self.assertEqual(s['win_count'] + s['lose_count'], s['closed_count'])
        if s['open_count'] > 0:
            # 胜率分母为已平仓
            self.assertEqual(s['win_rate'], round(100.0 * s['win_count'] / s['closed_count'], 2))

    def test_no_lookahead_past_end_date_fixed(self):
        # 区间末 = 第 40 根；信号在第 38 根，hold_days=10 → 到期日(idx 49)越过区间末。
        # 缓存数据延伸到第 80 根，但不得据此在区间外平仓，应标记持仓中并按区间末收盘定价。
        end_ts = self.hist['date'].iloc[40]
        end_str = end_ts.strftime('%Y-%m-%d')
        with self._patch({38}):
            res = bh._run_single_backtest('000001', 'cn_stock_strategy_keep_increasing',
                                          '2026-01-01', end_str, hold_days=10)
        self.assertNotIn('error', res)
        self.assertEqual(len(res['trades']), 1)
        t = res['trades'][0]
        self.assertEqual(t['status'], 'open')
        self.assertEqual(t['exit_reason'], 'interval_end')
        self.assertIsNone(t['sell_date'])
        # 持仓中收益须按区间末(idx 40)收盘价，而非未来(idx 49/80)价格
        buy_price = float(self.hist['open'].iloc[39])
        end_close = float(self.hist['close'].iloc[40])
        expected = round(round(100.0 * (end_close - buy_price) / buy_price, 2) - bh.ROUND_TRIP_COST_PCT, 2)
        self.assertEqual(t['rate'], expected)
        # K线不得包含区间末之后的未来蜡烛
        last_k = res['kline'][-1]
        last_k_date = last_k[0] if isinstance(last_k, (list, tuple)) else (last_k.get('date') or last_k.get('time'))
        self.assertEqual(str(last_k_date), end_str)

    def test_no_lookahead_past_end_date_signal(self):
        # 策略信号出场模式：买入后策略持续命中至缓存末，但区间末前未触发卖点 → 持仓中，不得越界平仓。
        end_ts = self.hist['date'].iloc[40]
        end_str = end_ts.strftime('%Y-%m-%d')
        hits = set(range(38, 80))  # 38 起一直命中，含区间末之后
        with self._patch(hits):
            res = bh._run_single_backtest('000001', 'cn_stock_strategy_keep_increasing',
                                          '2026-01-01', end_str, hold_days=None)
        self.assertNotIn('error', res)
        self.assertEqual(len(res['trades']), 1)
        t = res['trades'][0]
        self.assertEqual(t['status'], 'open')
        self.assertIsNone(t['sell_date'])

    def test_limit_up_skip(self):
        # 构造 T+1 开盘涨停（相对 T 收盘 +10%）
        prices = [10.0] * 10
        hist = _make_hist(prices)
        # 信号在 idx=3，T+1(idx=4) 开盘拉到涨停
        hist.loc[4, 'open'] = hist.loc[3, 'close'] * 1.10
        with mock.patch.object(bh.stf, 'read_stock_hist_from_cache', return_value=hist), \
             mock.patch.object(bh.idr, 'get_indicators', return_value=hist), \
             mock.patch.object(bh, '_get_stock_name', return_value='测试股'), \
             mock.patch.object(bh, '_resolve_single_strategy',
                               return_value=(lambda s, h, date=None, **k: pd.Timestamp(date) == hist.loc[3, 'date'], 'x')):
            res = bh._run_single_backtest('000001', 'cn_stock_strategy_keep_increasing',
                                          '2026-01-01', '2026-02-28', hold_days=2)
        # 涨停被跳过 → 无成交
        self.assertEqual(res['summary']['trade_count'], 0)

    def test_strategy_signal_exit(self):
        # 命中 idx 5..10 连续为买点，11 起不再命中 → 卖点在 idx 11
        hits = {5, 6, 7, 8, 9, 10}
        with self._patch(hits):
            res = bh._run_single_backtest('000001', 'cn_stock_strategy_keep_increasing',
                                          '2026-01-01', '2026-05-30', hold_days=None)
        self.assertEqual(res['exit_mode'], 'strategy_signal')
        self.assertIsNone(res['hold_days'])
        self.assertTrue(len(res['trades']) >= 1)
        t = res['trades'][0]
        # 买入 T+1 = idx 6；条件在 idx 11 破 → 卖点
        self.assertEqual(t['exit_reason'], 'sell_signal')

    def test_sharpe_null_when_insufficient(self):
        self.assertIsNone(bh._compute_single_sharpe([]))
        self.assertIsNone(bh._compute_single_sharpe([{'rate': 5.0, 'hold_days': 5}]))

    def test_sharpe_finite_multi(self):
        trades = [{'rate': 5.0, 'hold_days': 5}, {'rate': -2.0, 'hold_days': 5},
                  {'rate': 3.0, 'hold_days': 5}, {'rate': 1.0, 'hold_days': 5}]
        s = bh._compute_single_sharpe(trades)
        self.assertIsNotNone(s)
        self.assertTrue(np.isfinite(s))

    def test_cum_return_compound(self):
        with self._patch({5, 30}):
            res = bh._run_single_backtest('000001', 'cn_stock_strategy_keep_increasing',
                                          '2026-01-01', '2026-05-30', hold_days=5)
        closed = [t for t in res['trades'] if t['status'] == 'closed']
        comp = 1.0
        for t in closed:
            comp *= (1.0 + t['rate'] / 100.0)
        self.assertAlmostEqual(res['summary']['cum_return'], round((comp - 1.0) * 100.0, 2), places=2)

    def test_price_limit_ratio(self):
        self.assertEqual(bh._price_limit_ratio('000001', '平安银行'), 0.10)
        self.assertEqual(bh._price_limit_ratio('300750', '宁德时代'), 0.20)
        self.assertEqual(bh._price_limit_ratio('688981', '中芯国际'), 0.20)
        self.assertEqual(bh._price_limit_ratio('000001', 'ST中天'), 0.05)
        self.assertEqual(bh._price_limit_ratio('830799', '艾融软件'), 0.30)

    def test_indicators_aligned_to_kline(self):
        with self._patch({5}):
            res = bh._run_single_backtest('000001', 'cn_stock_strategy_keep_increasing',
                                          '2026-01-01', '2026-05-30', hold_days=5)
        n = len(res['kline'])
        ind = res['indicators']
        self.assertEqual(len(ind['ma']['5']), n)
        self.assertEqual(len(ind['ma']['250']), n)
        # 前 4 根 MA5 应为 None（不足周期）
        self.assertIsNone(ind['ma']['5'][0])
        self.assertIsNotNone(ind['ma']['5'][4])
        # 推荐指标按策略映射
        self.assertEqual(ind['recommended'], bh.STRATEGY_OVERLAY_MAP['cn_stock_strategy_keep_increasing'])


class SingleBacktestHandlerTests(AsyncHTTPTestCase):
    def get_app(self):
        return Application([
            (r'/api/backtest/single', bh.SingleStockBacktestHandler),
            (r'/api/backtest/history', bh.BacktestHistoryListHandler),
            (r'/api/backtest/history/detail', bh.BacktestHistoryDetailHandler),
            (r'/api/backtest/history/delete', bh.BacktestHistoryDeleteHandler),
        ])

    def test_missing_code_returns_error(self):
        resp = self.fetch('/api/backtest/single?strategy=cn_stock_strategy_keep_increasing'
                          '&start_date=2026-01-01&end_date=2026-03-01&hold_days=5')
        body = json.loads(resp.body)
        self.assertIn('error', body)

    def test_history_list_empty_when_no_table(self):
        with mock.patch.object(bh.mdb, 'checkTableIsExist', return_value=False):
            resp = self.fetch('/api/backtest/history?page=1&page_size=20')
        body = json.loads(resp.body)
        self.assertEqual(body['total'], 0)
        self.assertEqual(body['items'], [])

    def test_history_detail_missing_id(self):
        resp = self.fetch('/api/backtest/history/detail')
        self.assertEqual(resp.code, 400)

    def test_history_delete_missing_id(self):
        resp = self.fetch('/api/backtest/history/delete', method='DELETE')
        self.assertEqual(resp.code, 400)


if __name__ == '__main__':
    unittest.main()
