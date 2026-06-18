#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""单股区间买卖点回测单元测试（document/backtest/single_stock_backtest_dev_plan.md）。"""

import json
import os
import sys
import unittest
from contextlib import contextmanager
from datetime import date
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from tornado.testing import AsyncHTTPTestCase
from tornado.web import Application

from quantia.web import backtestHandler as bh
import quantia.core.indicator.buy_sell_signal as bss


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
            res = bh._run_single_backtest('000001', 'unknown_strategy_name',
                                          '2026-01-01', '2026-03-01', hold_days=5)
        self.assertIn('error', res)

    def test_indicators_buy_supported(self):
        # 单股指标回测在个股自身指标序列上按配置参数重算信号（含回撤闸门）
        signal_day = self.hist['date'].iloc[5].date()
        with mock.patch.object(bh, '_get_stock_name', return_value='测试股'), \
             mock.patch.object(bh.stf, 'read_stock_hist_from_cache', return_value=self.hist), \
             mock.patch.object(bh, '_compute_single_indicator_signal_dates', return_value={signal_day}):
            res = bh._run_single_backtest('000001', 'indicators_buy',
                                          '2026-01-01', '2026-03-31', hold_days=5)
        self.assertNotIn('error', res)
        self.assertEqual(res['strategy_cn'], '指标买入信号')
        self.assertEqual(res['exit_mode'], 'fixed')
        self.assertTrue(len(res['trades']) >= 1)

    def test_indicators_sell_supported(self):
        signal_day = self.hist['date'].iloc[8].date()
        with mock.patch.object(bh, '_get_stock_name', return_value='测试股'), \
             mock.patch.object(bh.stf, 'read_stock_hist_from_cache', return_value=self.hist), \
             mock.patch.object(bh, '_compute_single_indicator_signal_dates', return_value={signal_day}):
            res = bh._run_single_backtest('000001', 'indicators_sell',
                                          '2026-01-01', '2026-03-31', hold_days=3)
        self.assertNotIn('error', res)
        self.assertEqual(res['strategy_cn'], '指标卖出信号')
        self.assertEqual(res['exit_mode'], 'fixed')
        self.assertTrue(len(res['trades']) >= 1)

    def test_indicator_recompute_applies_drawdown_gate(self):
        # 三根都极度超卖；high 恒为 100。buy_drawdown_ratio=0.90 要求现价 ≤ 10。
        # idx1 现价 9（跌 91%）过闸；idx2 现价 30（仅跌 70%）被回撤闸门过滤。
        dates = pd.bdate_range('2026-01-05', periods=3)
        ind = pd.DataFrame({
            'date': dates,
            'high': [100.0, 100.0, 100.0],
            'close': [50.0, 9.0, 30.0],
            'rsi_6': [50.0, 5.0, 5.0],
            'kdjj': [50.0, -10.0, -10.0],
            'wr_6': [-50.0, -95.0, -95.0],
            'cci': [0.0, -200.0, -200.0],
            'mfi': [50.0, 5.0, 5.0],
        })
        params = dict(bss.DEFAULT_PARAMS)
        params['buy_drawdown_ratio'] = 0.90
        with mock.patch.object(bss, 'load_params', return_value=params), \
             mock.patch.object(bh.idr, 'get_indicators', return_value=ind):
            out = bh._compute_single_indicator_signal_dates(
                'indicators_buy', ind, '2026-01-01', '2026-12-31')
        self.assertEqual(out, {dates[1].date()})

    def test_indicator_recompute_sell_drawdown_gate(self):
        # 三根都极度超买；high 恒为 100。sell_drawdown_ratio=0.80 要求现价 ≥ 80。
        dates = pd.bdate_range('2026-01-05', periods=2)
        ind = pd.DataFrame({
            'date': dates,
            'high': [100.0, 100.0],
            'close': [90.0, 50.0],   # idx0 贴峰过闸；idx1 跌始被过滤
            'rsi_6': [90.0, 90.0],
            'kdjj': [110.0, 110.0],
            'wr_6': [-5.0, -5.0],
            'cci': [200.0, 200.0],
            'mfi': [90.0, 90.0],
        })
        params = dict(bss.DEFAULT_PARAMS)
        with mock.patch.object(bss, 'load_params', return_value=params), \
             mock.patch.object(bh.idr, 'get_indicators', return_value=ind):
            out = bh._compute_single_indicator_signal_dates(
                'indicators_sell', ind, '2026-01-01', '2026-12-31')
        self.assertEqual(out, {dates[0].date()})

    def test_indicator_signal_dates_normalize_compact_date_strings(self):
        captured = {}

        def fake_execute_sql_fetch(sql, params=None):
            captured['sql'] = sql
            captured['params'] = params
            return [{'date': '2026-01-02'}]

        with mock.patch.object(bh.mdb, 'checkTableIsExist', return_value=True), \
             mock.patch.object(bh.mdb, 'executeSqlFetch', side_effect=fake_execute_sql_fetch):
            result = bh._load_single_indicator_signal_dates('indicators_buy', '000001', '20260101', '20260331')

        self.assertEqual(captured['params'], ('000001', '2026-01-01', '2026-03-31'))
        self.assertEqual(result, {date(2026, 1, 2)})

    def test_compute_signal_dates_from_own_indicator_series(self):
        """选股结果表查无该股信号时，按个股自身指标序列重算超卖买入信号日。"""
        hist = _make_hist([10.0 + i * 0.1 for i in range(10)])
        ind = hist.copy()
        # 仅第 3、7 根满足极度超卖（5 项指标同时越过阈值）
        ind['rsi_6'] = 50.0
        ind['kdjj'] = 50.0
        ind['wr_6'] = -50.0
        ind['cci'] = 0.0
        ind['mfi'] = 50.0
        for i in (3, 7):
            ind.loc[i, ['rsi_6', 'kdjj', 'wr_6', 'cci', 'mfi']] = [10.0, -5.0, -95.0, -200.0, 10.0]

        # 回撤闸门置 0（现价 ≤ 1.0×峰值恒成立），本用例专测“指标超卖”逻辑。
        _p = dict(bss.DEFAULT_PARAMS); _p['buy_drawdown_ratio'] = 0.0
        with mock.patch.object(bss, 'load_params', return_value=_p), \
             mock.patch.object(bh.mdb, 'checkTableIsExist', return_value=False), \
             mock.patch.object(bh.idr, 'get_indicators', return_value=ind):
            dates = bh._compute_single_indicator_signal_dates('indicators_buy', hist)

        expected = {hist['date'].iloc[3].date(), hist['date'].iloc[7].date()}
        self.assertEqual(dates, expected)

    def test_compute_signal_dates_respects_range_bounds(self):
        """重算信号日应裁剪到回测区间内。"""
        hist = _make_hist([10.0 + i * 0.1 for i in range(10)])
        ind = hist.copy()
        ind['rsi_6'] = 10.0
        ind['kdjj'] = -5.0
        ind['wr_6'] = -95.0
        ind['cci'] = -200.0
        ind['mfi'] = 10.0  # 全部满足超卖

        start = hist['date'].iloc[2].strftime('%Y-%m-%d')
        end = hist['date'].iloc[5].strftime('%Y-%m-%d')
        _p = dict(bss.DEFAULT_PARAMS); _p['buy_drawdown_ratio'] = 0.0  # 回撤闸门置 0，专测区间裁剪
        with mock.patch.object(bss, 'load_params', return_value=_p), \
             mock.patch.object(bh.mdb, 'checkTableIsExist', return_value=False), \
             mock.patch.object(bh.idr, 'get_indicators', return_value=ind):
            dates = bh._compute_single_indicator_signal_dates('indicators_buy', hist, start, end)

        expected = {hist['date'].iloc[i].date() for i in range(2, 6)}
        self.assertEqual(dates, expected)

    def test_load_signal_dates_uses_own_series_when_hist_available(self):
        """hist 可用时始终按个股指标序列重算，不读横截面选股结果表。"""
        hist = _make_hist([10.0 + i * 0.1 for i in range(10)])
        ind = hist.copy()
        ind['rsi_6'] = 50.0
        ind['kdjj'] = 50.0
        ind['wr_6'] = -50.0
        ind['cci'] = 0.0
        ind['mfi'] = 50.0
        ind.loc[4, ['rsi_6', 'kdjj', 'wr_6', 'cci', 'mfi']] = [10.0, -5.0, -95.0, -200.0, 10.0]

        called = {'fetch': False}

        def _fetch(*_a, **_k):
            called['fetch'] = True
            return []

        _p = dict(bss.DEFAULT_PARAMS); _p['buy_drawdown_ratio'] = 0.0  # 回撤闸门置 0，专测重算路径
        with mock.patch.object(bss, 'load_params', return_value=_p), \
             mock.patch.object(bh.mdb, 'checkTableIsExist', return_value=False), \
             mock.patch.object(bh.mdb, 'executeSqlFetch', side_effect=_fetch), \
             mock.patch.object(bh.idr, 'get_indicators', return_value=ind):
            dates = bh._load_single_indicator_signal_dates(
                'indicators_buy', '000001', '2026-01-01', '2026-03-31', hist=hist)

        self.assertEqual(dates, {hist['date'].iloc[4].date()})
        # 选股结果表不应被查询（executeSqlFetch 仅可能被 load_params 调用，这里
        # checkTableIsExist=False 使 load_params 不触发 fetch）。
        self.assertFalse(called['fetch'])

    def test_compute_signal_uses_full_indicator_series(self):
        """重算信号须取完整指标序列（threshold=None），否则仅最后一根被判定。"""
        hist = _make_hist([10.0 + i * 0.1 for i in range(10)])
        captured = {}

        def fake_get_indicators(data, end_date=None, threshold=120, calc_threshold=None):
            captured['threshold'] = threshold
            return data  # 无指标列 → 返回空集；此处仅校验 threshold 传参

        with mock.patch.object(bh.mdb, 'checkTableIsExist', return_value=False), \
             mock.patch.object(bh.idr, 'get_indicators', side_effect=fake_get_indicators):
            bh._compute_single_indicator_signal_dates('indicators_buy', hist)

        self.assertIsNone(captured['threshold'])

    def test_overlay_indicators_use_full_series(self):
        """K 线叠加指标须取完整序列（threshold=None），否则 BOLL/MACD/KDJ/RSI 仅末根有值。"""
        hist = _make_hist([10.0 + i * 0.1 for i in range(10)])
        captured = {}

        def fake_get_indicators(data, end_date=None, threshold=120, calc_threshold=None):
            captured['threshold'] = threshold
            return data

        with mock.patch.object(bh.idr, 'get_indicators', side_effect=fake_get_indicators):
            bh._build_kline_and_indicators(hist, list(bh._DEFAULT_OVERLAY), list(bh._ALL_OVERLAYS))

        self.assertIsNone(captured['threshold'])

    def test_indicators_buy_backtest_works_without_table_rows(self):
        """端到端：选股表无 000001 信号，单股回测仍按自身指标产生交易（不再全空）。"""
        hist = _make_hist([10.0 + i * 0.1 for i in range(30)])
        ind = hist.copy()
        ind['rsi_6'] = 50.0
        ind['kdjj'] = 50.0
        ind['wr_6'] = -50.0
        ind['cci'] = 0.0
        ind['mfi'] = 50.0
        ind.loc[5, ['rsi_6', 'kdjj', 'wr_6', 'cci', 'mfi']] = [10.0, -5.0, -95.0, -200.0, 10.0]

        _p = dict(bss.DEFAULT_PARAMS); _p['buy_drawdown_ratio'] = 0.0  # 回撤闸门置 0，专测端到端交易生成
        with mock.patch.object(bss, 'load_params', return_value=_p), \
             mock.patch.object(bh, '_get_stock_name', return_value='测试股'), \
             mock.patch.object(bh.stf, 'read_stock_hist_from_cache', return_value=hist), \
             mock.patch.object(bh.idr, 'get_indicators', return_value=ind), \
             mock.patch.object(bh.mdb, 'checkTableIsExist', return_value=True), \
             mock.patch.object(bh.mdb, 'executeSqlFetch', return_value=[]):
            res = bh._run_single_backtest('000001', 'indicators_buy',
                                          hist['date'].iloc[0].strftime('%Y-%m-%d'),
                                          hist['date'].iloc[-1].strftime('%Y-%m-%d'),
                                          hold_days=3)
        self.assertNotIn('error', res)
        self.assertEqual(res['strategy_cn'], '指标买入信号')
        self.assertTrue(len(res['trades']) >= 1)

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


class EventStrategyExitTests(unittest.TestCase):
    """修复 A：事件型策略入场/退出解耦——默认走规则退出（止损/止盈/最大持仓）。"""

    def _patch(self, hist, hit_dates):
        def fake_strategy(stock, h, date=None, **kw):
            ts = pd.Timestamp(date)
            idx = hist.index[hist['date'] == ts]
            if len(idx) == 0:
                return False
            return int(idx[0]) in hit_dates

        @contextmanager
        def _ctx():
            with mock.patch.object(bh, '_resolve_single_strategy',
                                   return_value=(fake_strategy, '事件策略')), \
                 mock.patch.object(bh, '_get_stock_name', return_value='测试股'), \
                 mock.patch.object(bh.stf, 'read_stock_hist_from_cache', return_value=hist), \
                 mock.patch.object(bh.idr, 'get_indicators', return_value=hist):
                yield
        return _ctx()

    def test_event_strategy_uses_rule_exit_mode(self):
        # 事件型策略不指定 hold_days → exit_mode 应为 rule_exit（而非 strategy_signal）
        hist = _make_hist([10.0] * 40)
        with self._patch(hist, {5}):
            res = bh._run_single_backtest('000001', 'cn_stock_strategy_enter',
                                          '2026-01-01', '2026-12-30', hold_days=None)
        self.assertNotIn('error', res)
        self.assertEqual(res['exit_mode'], 'rule_exit')

    def test_event_strategy_take_profit(self):
        # 买入价 10，涨过 +15% → 止盈离场
        prices = [10.0] * 7 + [11.6] * 33  # idx7 收盘 11.6 ≥ 11.5
        hist = _make_hist(prices)
        with self._patch(hist, {5}):  # 信号 idx5 → 买入 idx6 开盘=10.0
            res = bh._run_single_backtest('000001', 'cn_stock_strategy_enter',
                                          '2026-01-01', '2026-12-30', hold_days=None)
        self.assertEqual(len(res['trades']), 1)
        t = res['trades'][0]
        self.assertEqual(t['exit_reason'], 'take_profit')
        self.assertEqual(t['status'], 'closed')
        self.assertEqual(t['sell_date'], hist['date'].iloc[7].strftime('%Y-%m-%d'))

    def test_event_strategy_stop_loss(self):
        # 买入价 10，跌破 -8% → 止损离场
        prices = [10.0] * 7 + [9.0] * 33  # idx7 收盘 9.0 ≤ 9.2
        hist = _make_hist(prices)
        with self._patch(hist, {5}):
            res = bh._run_single_backtest('000001', 'cn_stock_strategy_enter',
                                          '2026-01-01', '2026-12-30', hold_days=None)
        self.assertEqual(len(res['trades']), 1)
        t = res['trades'][0]
        self.assertEqual(t['exit_reason'], 'stop_loss')
        self.assertEqual(t['status'], 'closed')
        self.assertLess(t['rate'], 0)

    def test_event_strategy_max_hold(self):
        # 价格平稳不触发止损/止盈 → 持满 20 交易日离场
        hist = _make_hist([10.0] * 40)
        with self._patch(hist, {5}):  # 买入 idx6，max_hold 卖点 idx 26
            res = bh._run_single_backtest('000001', 'cn_stock_strategy_enter',
                                          '2026-01-01', '2026-12-30', hold_days=None)
        self.assertEqual(len(res['trades']), 1)
        t = res['trades'][0]
        self.assertEqual(t['exit_reason'], 'max_hold')
        self.assertEqual(t['hold_days'], bh._EVENT_EXIT_MAX_HOLD)
        self.assertEqual(t['sell_date'], hist['date'].iloc[26].strftime('%Y-%m-%d'))

    def test_event_strategy_not_one_day_trap(self):
        # 回归核心 bug：事件型策略不再退化成"买入次日即卖"的一日交易。
        # 平稳行情下应持满 max_hold，而非 hold_days==1。
        hist = _make_hist([10.0] * 40)
        with self._patch(hist, {5}):
            res = bh._run_single_backtest('000001', 'cn_stock_strategy_enter',
                                          '2026-01-01', '2026-12-30', hold_days=None)
        t = res['trades'][0]
        self.assertGreater(t['hold_days'], 1)


class CacheFallbackTests(unittest.TestCase):
    """修复 C：缓存缺失或过薄时从 cn_stock_spot 补全（仅读 MySQL，不发外部 API）。"""

    def test_cache_covers_range_true_when_recent(self):
        hist = _make_hist([10.0] * 80, start='2026-01-01')
        end = hist['date'].iloc[-1].strftime('%Y-%m-%d')
        self.assertTrue(bh._cache_covers_range(hist, '2026-01-01', end))

    def test_cache_covers_range_false_when_stale(self):
        hist = _make_hist([10.0] * 5, start='2026-01-01')  # 截止 ~2026-01-07
        self.assertFalse(bh._cache_covers_range(hist, '2026-01-01', '2026-05-30'))

    def test_cache_covers_range_false_when_empty(self):
        self.assertFalse(bh._cache_covers_range(None, '2026-01-01', '2026-05-30'))
        self.assertFalse(bh._cache_covers_range(pd.DataFrame(), '2026-01-01', '2026-05-30'))

    def test_thin_cache_augmented_from_spot(self):
        # 缓存只有 5 行（截止 2026-01-07），spot 提供完整 80 行覆盖区间末。
        thin = _make_hist([10.0] * 5, start='2026-01-01')
        full = _make_hist([10.0 + i * 0.1 for i in range(80)], start='2026-01-01')
        end = full['date'].iloc[-1].strftime('%Y-%m-%d')

        def fake_strategy(stock, h, date=None, **kw):
            return pd.Timestamp(date) == full['date'].iloc[5]

        with mock.patch.object(bh, '_resolve_single_strategy',
                               return_value=(fake_strategy, '测试策略')), \
             mock.patch.object(bh, '_get_stock_name', return_value='测试股'), \
             mock.patch.object(bh.stf, 'read_stock_hist_from_cache', return_value=thin), \
             mock.patch.object(bh.stf, '_fallback_kline_from_spot', return_value=full) as m_spot, \
             mock.patch.object(bh.idr, 'get_indicators', return_value=full):
            res = bh._run_single_backtest('000001', 'cn_stock_strategy_keep_increasing',
                                          '2026-01-01', end, hold_days=5)
        # 触发了 spot 补全，且 K 线扩展到完整 80 根（薄缓存不会再静默产出空结果）
        m_spot.assert_called_once()
        self.assertNotIn('error', res)
        self.assertEqual(len(res['kline']), 80)
        self.assertTrue(len(res['trades']) >= 1)

    def test_full_cache_not_augmented(self):
        # 缓存已覆盖区间末 → 不应调用 spot 补全
        full = _make_hist([10.0 + i * 0.1 for i in range(80)], start='2026-01-01')
        end = full['date'].iloc[-1].strftime('%Y-%m-%d')

        def fake_strategy(stock, h, date=None, **kw):
            return pd.Timestamp(date) == full['date'].iloc[5]

        with mock.patch.object(bh, '_resolve_single_strategy',
                               return_value=(fake_strategy, '测试策略')), \
             mock.patch.object(bh, '_get_stock_name', return_value='测试股'), \
             mock.patch.object(bh.stf, 'read_stock_hist_from_cache', return_value=full), \
             mock.patch.object(bh.stf, '_fallback_kline_from_spot', return_value=None) as m_spot, \
             mock.patch.object(bh.idr, 'get_indicators', return_value=full):
            res = bh._run_single_backtest('000001', 'cn_stock_strategy_keep_increasing',
                                          '2026-01-01', end, hold_days=5)
        m_spot.assert_not_called()
        self.assertNotIn('error', res)

    def test_no_cache_uses_spot_only(self):
        # 缓存完全缺失 → 全量使用 spot 数据
        full = _make_hist([10.0 + i * 0.1 for i in range(80)], start='2026-01-01')
        end = full['date'].iloc[-1].strftime('%Y-%m-%d')

        def fake_strategy(stock, h, date=None, **kw):
            return pd.Timestamp(date) == full['date'].iloc[5]

        with mock.patch.object(bh, '_resolve_single_strategy',
                               return_value=(fake_strategy, '测试策略')), \
             mock.patch.object(bh, '_get_stock_name', return_value='测试股'), \
             mock.patch.object(bh.stf, 'read_stock_hist_from_cache', return_value=None), \
             mock.patch.object(bh.stf, '_fallback_kline_from_spot', return_value=full), \
             mock.patch.object(bh.idr, 'get_indicators', return_value=full):
            res = bh._run_single_backtest('000001', 'cn_stock_strategy_keep_increasing',
                                          '2026-01-01', end, hold_days=5)
        self.assertNotIn('error', res)
        self.assertEqual(len(res['kline']), 80)


class CustomStrategyBacktestTests(unittest.TestCase):
    """自定义策略单股回测（方案 2：组合回测交易过滤法）。仅 custom_* 走新分支，内置路径零回归。"""

    def setUp(self):
        self.full = _make_hist([10.0 + i * 0.1 for i in range(80)], start='2026-01-01')
        self.end = self.full['date'].iloc[-1].strftime('%Y-%m-%d')
        self.buy_date = self.full['date'].iloc[10].strftime('%Y-%m-%d')
        self.sell_date = self.full['date'].iloc[20].strftime('%Y-%m-%d')
        self.buy_price = float(self.full['close'].iloc[10])
        self.sell_price = float(self.full['close'].iloc[20])

    # ── code 匹配 ──────────────────────────────────────────────────────────
    def test_custom_code_match_variants(self):
        self.assertTrue(bh._custom_code_match('000001', '000001'))
        self.assertTrue(bh._custom_code_match('000001.XSHE', '000001'))
        self.assertTrue(bh._custom_code_match('sz000001', '000001'))
        self.assertFalse(bh._custom_code_match('600519', '000001'))
        self.assertFalse(bh._custom_code_match('', '000001'))
        self.assertFalse(bh._custom_code_match(None, '000001'))

    # ── 路由：custom_* 走自定义分支 ──────────────────────────────────────────
    def test_custom_prefix_routes_to_custom_backtest(self):
        with mock.patch.object(bh, '_run_single_custom_backtest',
                               return_value={'exit_mode': 'custom', 'trades': []}) as m:
            res = bh._run_single_backtest('000001', 'custom_5', '2026-01-01', '2026-05-30')
        m.assert_called_once_with('000001', 'custom_5', '2026-01-01', '2026-05-30')
        self.assertEqual(res['exit_mode'], 'custom')

    def test_unknown_custom_strategy_returns_error(self):
        with mock.patch.object(bh, '_resolve_custom_strategy', return_value=(None, None)):
            res = bh._run_single_custom_backtest('000001', 'custom_999', '2026-01-01', self.end)
        self.assertIn('error', res)
        self.assertIn('不存在', res['error'])

    # ── round-trip 配对 ─────────────────────────────────────────────────────
    def _patch_custom(self, cached_result):
        """patch 自定义路径依赖：策略解析 / 历史 / 指标 / 组合回测缓存。"""
        return mock.patch.multiple(
            bh,
            _resolve_custom_strategy=mock.DEFAULT,
            _load_single_hist=mock.DEFAULT,
            _get_stock_name=mock.DEFAULT,
        ), mock.patch('quantia.web.verifyOptimizeHandler._load_cached_custom_backtest',
                      return_value=(cached_result, 'cache:1'))

    def test_custom_pairs_buy_sell_round_trip(self):
        result = {'status': 'completed', 'trades': [
            {'direction': 'buy', 'date': self.buy_date, 'code': '000001', 'price': self.buy_price},
            {'direction': 'sell', 'date': self.sell_date, 'code': '000001', 'price': self.sell_price},
            # 其它股票的交易应被过滤
            {'direction': 'buy', 'date': self.buy_date, 'code': '600519', 'price': 100.0},
        ]}
        m_multi, m_cache = self._patch_custom(result)
        with m_multi as mocks, m_cache, \
             mock.patch.object(bh.idr, 'get_indicators', return_value=self.full):
            mocks['_resolve_custom_strategy'].return_value = (5, '我的策略')
            mocks['_load_single_hist'].return_value = self.full
            mocks['_get_stock_name'].return_value = '平安银行'
            res = bh._run_single_custom_backtest('000001', 'custom_5', '2026-01-01', self.end)
        self.assertNotIn('error', res)
        self.assertEqual(res['exit_mode'], 'custom')
        self.assertEqual(res['strategy_cn'], '我的策略')
        self.assertEqual(len(res['trades']), 1)
        t = res['trades'][0]
        self.assertEqual(t['status'], 'closed')
        self.assertEqual(t['buy_date'], self.buy_date)
        self.assertEqual(t['sell_date'], self.sell_date)
        self.assertEqual(t['hold_days'], 10)
        self.assertEqual(t['exit_reason'], 'strategy_sell')
        self.assertGreater(t['rate'], 0)  # 上涨行情，扣费后仍盈利
        self.assertEqual(len(res['kline']), 80)

    def test_custom_open_position_at_interval_end(self):
        result = {'status': 'completed', 'trades': [
            {'direction': 'buy', 'date': self.buy_date, 'code': '000001', 'price': self.buy_price},
        ]}
        m_multi, m_cache = self._patch_custom(result)
        with m_multi as mocks, m_cache, \
             mock.patch.object(bh.idr, 'get_indicators', return_value=self.full):
            mocks['_resolve_custom_strategy'].return_value = (5, '我的策略')
            mocks['_load_single_hist'].return_value = self.full
            mocks['_get_stock_name'].return_value = '平安银行'
            res = bh._run_single_custom_backtest('000001', 'custom_5', '2026-01-01', self.end)
        self.assertEqual(len(res['trades']), 1)
        t = res['trades'][0]
        self.assertEqual(t['status'], 'open')
        self.assertIsNone(t['sell_date'])
        self.assertEqual(t['exit_reason'], 'interval_end')

    def test_custom_no_trades_for_stock_returns_message(self):
        result = {'status': 'completed', 'trades': [
            {'direction': 'buy', 'date': self.buy_date, 'code': '600519', 'price': 100.0},
        ]}
        m_multi, m_cache = self._patch_custom(result)
        with m_multi as mocks, m_cache, \
             mock.patch.object(bh.idr, 'get_indicators', return_value=self.full):
            mocks['_resolve_custom_strategy'].return_value = (5, '我的策略')
            mocks['_load_single_hist'].return_value = self.full
            mocks['_get_stock_name'].return_value = '平安银行'
            res = bh._run_single_custom_backtest('000001', 'custom_5', '2026-01-01', self.end)
        self.assertNotIn('error', res)
        self.assertEqual(res['trades'], [])
        self.assertIn('message', res)
        self.assertIn('未被', res['message'])
        # 即使无交易，仍返回 K 线供前端展示
        self.assertEqual(len(res['kline']), 80)

    def test_custom_auto_run_when_cache_missing(self):
        result = {'status': 'completed', 'trades': [
            {'direction': 'buy', 'date': self.buy_date, 'code': '000001', 'price': self.buy_price},
            {'direction': 'sell', 'date': self.sell_date, 'code': '000001', 'price': self.sell_price},
        ]}
        with mock.patch.object(bh, '_resolve_custom_strategy', return_value=(5, '我的策略')), \
             mock.patch.object(bh, '_load_single_hist', return_value=self.full), \
             mock.patch.object(bh, '_get_stock_name', return_value='平安银行'), \
             mock.patch.object(bh.idr, 'get_indicators', return_value=self.full), \
             mock.patch('quantia.web.verifyOptimizeHandler._load_cached_custom_backtest',
                        side_effect=[(None, None), (result, 'cache:1')]) as m_cache, \
             mock.patch('quantia.web.verifyOptimizeHandler._auto_run_custom_backtest',
                        return_value=([], None)) as m_auto:
            res = bh._run_single_custom_backtest('000001', 'custom_5', '2026-01-01', self.end)
        m_auto.assert_called_once()
        self.assertEqual(m_cache.call_count, 2)
        self.assertEqual(len(res['trades']), 1)
        self.assertEqual(res['trades'][0]['status'], 'closed')

    def test_custom_auto_run_failure_returns_error(self):
        with mock.patch.object(bh, '_resolve_custom_strategy', return_value=(5, '我的策略')), \
             mock.patch('quantia.web.verifyOptimizeHandler._load_cached_custom_backtest',
                        return_value=(None, None)), \
             mock.patch('quantia.web.verifyOptimizeHandler._auto_run_custom_backtest',
                        return_value=([], '引擎编译失败')):
            res = bh._run_single_custom_backtest('000001', 'custom_5', '2026-01-01', self.end)
        self.assertIn('error', res)
        self.assertIn('引擎编译失败', res['error'])


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
