#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for quantia.core.indicator.buy_sell_signal (超卖深跌抄底 / 超买见顶派发)。

纯单元测试：mock 数据库与 K 线缓存，无任何网络/真实 DB 访问。
"""
import datetime
import unittest
from unittest.mock import patch

import pandas as pd

import quantia.core.indicator.buy_sell_signal as bss

TEST_DATE = datetime.datetime(2026, 3, 18)
TEST_DATE_STR = '2026-03-18'
RATIO = 0.80


def _hist(peak_high, last_close, last_date=TEST_DATE_STR):
    """构造一个最小 K 线历史：历史最高 = peak_high，最后一根收盘 = last_close。"""
    return pd.DataFrame({
        'date': ['2024-01-02', '2024-06-03', last_date],
        'high': [peak_high * 0.5, peak_high, last_close * 1.01],
        'close': [peak_high * 0.4, peak_high * 0.9, last_close],
    })


class TestPeakDrawdownGate(unittest.TestCase):
    def test_buy_deep_drawdown_passes(self):
        # 历史最高 100，现价 15 → 跌掉 85% ≥ 80% → 通过
        with patch.object(bss.stf, 'read_stock_hist_from_cache', return_value=_hist(100.0, 15.0)):
            self.assertTrue(bss._peak_drawdown_ok('000001', TEST_DATE_STR, 'buy', RATIO))

    def test_buy_shallow_drawdown_rejected(self):
        # 历史最高 100，现价 25 → 仅跌 75% < 80% → 拒绝
        with patch.object(bss.stf, 'read_stock_hist_from_cache', return_value=_hist(100.0, 25.0)):
            self.assertFalse(bss._peak_drawdown_ok('000001', TEST_DATE_STR, 'buy', RATIO))

    def test_buy_relaxed_ratio_passes(self):
        # 放宽回撤到 0.50：现价 40（跌 60%）→ 通过
        with patch.object(bss.stf, 'read_stock_hist_from_cache', return_value=_hist(100.0, 40.0)):
            self.assertTrue(bss._peak_drawdown_ok('000001', TEST_DATE_STR, 'buy', 0.50))

    def test_sell_near_peak_passes(self):
        # 历史最高 100，现价 85 → ≥ 80% 峰值 → 通过
        with patch.object(bss.stf, 'read_stock_hist_from_cache', return_value=_hist(100.0, 85.0)):
            self.assertTrue(bss._peak_drawdown_ok('000001', TEST_DATE_STR, 'sell', RATIO))

    def test_sell_far_from_peak_rejected(self):
        with patch.object(bss.stf, 'read_stock_hist_from_cache', return_value=_hist(100.0, 70.0)):
            self.assertFalse(bss._peak_drawdown_ok('000001', TEST_DATE_STR, 'sell', RATIO))

    def test_no_cache_returns_false(self):
        with patch.object(bss.stf, 'read_stock_hist_from_cache', return_value=None):
            self.assertFalse(bss._peak_drawdown_ok('000001', TEST_DATE_STR, 'buy', RATIO))

    def test_no_future_leak(self):
        # 历史最高出现在 target 之后（未来），不应被用于回撤判定。
        # 截至 target 的峰值=100，现价=90（仅跌 10%）→ 不满足深跌 → False。
        # 若错误地用到未来高点 1000，则 90 <= 0.2*1000=200 会被误判为 True。
        hist = pd.DataFrame({
            'date': ['2024-01-02', TEST_DATE_STR, '2026-12-31'],
            'high': [100.0, 100.0, 1000.0],
            'close': [90.0, 90.0, 900.0],
        })
        with patch.object(bss.stf, 'read_stock_hist_from_cache', return_value=hist):
            self.assertFalse(bss._peak_drawdown_ok('000001', TEST_DATE_STR, 'buy', RATIO))

    def test_no_bars_before_target_returns_false(self):
        # target 早于所有 K 线 → 截面为空 → False（保守，不发信号）
        hist = pd.DataFrame({
            'date': ['2027-01-02', '2027-06-03'],
            'high': [100.0, 120.0],
            'close': [10.0, 12.0],
        })
        with patch.object(bss.stf, 'read_stock_hist_from_cache', return_value=hist):
            self.assertFalse(bss._peak_drawdown_ok('000001', TEST_DATE_STR, 'buy', RATIO))

    def test_unsorted_cache_uses_latest_date_not_last_row(self):
        # 缓存非升序排列：最后一行不是日期最大的行。现价应取日期最大（target 当日）那行。
        # target 当日收盘=15（跌 85% ≥ 80% → 通过）；若错误用 iloc[-1] 的收盘 90 → 会被误判为 False。
        hist = pd.DataFrame({
            'date': [TEST_DATE_STR, '2024-01-02', '2024-06-03'],
            'high': [16.0, 50.0, 100.0],
            'close': [15.0, 40.0, 90.0],
        })
        with patch.object(bss.stf, 'read_stock_hist_from_cache', return_value=hist):
            self.assertTrue(bss._peak_drawdown_ok('000001', TEST_DATE_STR, 'buy', RATIO))


class TestLoadParams(unittest.TestCase):
    def test_no_table_returns_defaults(self):
        with patch.object(bss.mdb, 'checkTableIsExist', return_value=False):
            p = bss.load_params()
        self.assertEqual(p['buy_rsi_6'], bss.DEFAULT_PARAMS['buy_rsi_6'])
        self.assertEqual(p['fund_filter_enabled'], 0)

    def test_saved_values_override_defaults(self):
        rows = [('buy_rsi_6', '10'), ('buy_drawdown_ratio', '0.5'), ('unknown_key', '1')]
        with patch.object(bss.mdb, 'checkTableIsExist', return_value=True), \
             patch.object(bss.mdb, 'executeSqlFetch', return_value=rows):
            p = bss.load_params()
        self.assertEqual(p['buy_rsi_6'], 10)
        self.assertEqual(p['buy_drawdown_ratio'], 0.5)
        self.assertNotIn('unknown_key', p)  # 未知键被忽略

    def test_read_failure_falls_back(self):
        with patch.object(bss.mdb, 'checkTableIsExist', return_value=True), \
             patch.object(bss.mdb, 'executeSqlFetch', side_effect=RuntimeError('db down')):
            p = bss.load_params()
        self.assertEqual(p, dict(bss.DEFAULT_PARAMS))


class TestSqlBuilders(unittest.TestCase):
    def test_oversold_uses_params(self):
        p = dict(bss.DEFAULT_PARAMS, buy_rsi_6=12, buy_cci=-200)
        clause = bss._build_oversold(p)
        self.assertIn('rsi_6` < 12', clause)
        self.assertIn('cci` < -200', clause)

    def test_overbought_uses_params(self):
        p = dict(bss.DEFAULT_PARAMS, sell_rsi_6=90)
        clause = bss._build_overbought(p)
        self.assertIn('rsi_6` > 90', clause)

    def test_name_exclude_toggles(self):
        plist = []
        clause = bss._name_exclude_clause(dict(bss.DEFAULT_PARAMS, exclude_st=1, exclude_delist=0), plist)
        self.assertEqual(plist, [bss._ST_LIKE])
        self.assertIn('NOT LIKE', clause)
        plist2 = []
        clause2 = bss._name_exclude_clause(dict(bss.DEFAULT_PARAMS, exclude_st=0, exclude_delist=0), plist2)
        self.assertEqual(plist2, [])
        self.assertEqual(clause2, '')


class TestSelectBuySignals(unittest.TestCase):
    def test_missing_indicators_table_returns_none(self):
        with patch.object(bss.mdb, 'checkTableIsExist', return_value=False):
            self.assertIsNone(bss.select_buy_signals(TEST_DATE, dict(bss.DEFAULT_PARAMS)))

    def test_buy_applies_drawdown_gate(self):
        df = pd.DataFrame({'date': [TEST_DATE_STR, TEST_DATE_STR],
                           'code': ['000001', '000002'], 'name': ['A', 'B']})
        with patch.object(bss.mdb, 'checkTableIsExist', return_value=True), \
             patch.object(bss.mdb, 'engine'), \
             patch('pandas.read_sql', return_value=df), \
             patch.object(bss, '_peak_drawdown_ok', side_effect=lambda c, d, m, r: c == '000001'):
            out = bss.select_buy_signals(TEST_DATE, dict(bss.DEFAULT_PARAMS))
        self.assertIsNotNone(out)
        self.assertEqual(list(out['code']), ['000001'])

    def test_buy_gate_filters_all_returns_none(self):
        df = pd.DataFrame({'date': [TEST_DATE_STR], 'code': ['000001'], 'name': ['A']})
        with patch.object(bss.mdb, 'checkTableIsExist', return_value=True), \
             patch.object(bss.mdb, 'engine'), \
             patch('pandas.read_sql', return_value=df), \
             patch.object(bss, '_peak_drawdown_ok', return_value=False):
            self.assertIsNone(bss.select_buy_signals(TEST_DATE, dict(bss.DEFAULT_PARAMS)))

    def test_buy_fundamental_filter_adds_join(self):
        df = pd.DataFrame({'date': [TEST_DATE_STR], 'code': ['000001'], 'name': ['A']})
        captured = {}

        def _capture(sql=None, con=None, params=None):
            captured['sql'] = sql
            return df

        p = dict(bss.DEFAULT_PARAMS, fund_filter_enabled=1)
        with patch.object(bss.mdb, 'checkTableIsExist', return_value=True), \
             patch.object(bss.mdb, 'engine'), \
             patch('pandas.read_sql', side_effect=_capture), \
             patch.object(bss, '_peak_drawdown_ok', return_value=True):
            bss.select_buy_signals(TEST_DATE, p)
        self.assertIn('JOIN `cn_stock_spot`', captured['sql'])
        self.assertIn('roe_weight', captured['sql'])


class TestSelectSellSignals(unittest.TestCase):
    def test_sell_no_fundamental_dependency(self):
        df = pd.DataFrame({'date': [TEST_DATE_STR], 'code': ['000003'], 'name': ['C']})
        with patch.object(bss.mdb, 'checkTableIsExist',
                          side_effect=lambda t: t == bss.tbs.TABLE_CN_STOCK_INDICATORS['name']), \
             patch.object(bss.mdb, 'engine'), \
             patch('pandas.read_sql', return_value=df), \
             patch.object(bss, '_peak_drawdown_ok', return_value=True):
            out = bss.select_sell_signals(TEST_DATE, dict(bss.DEFAULT_PARAMS))
        self.assertIsNotNone(out)
        self.assertEqual(list(out['code']), ['000003'])

    def test_sell_missing_indicators_returns_none(self):
        with patch.object(bss.mdb, 'checkTableIsExist', return_value=False):
            self.assertIsNone(bss.select_sell_signals(TEST_DATE, dict(bss.DEFAULT_PARAMS)))


class TestRecompute(unittest.TestCase):
    def test_recompute_stores_and_counts(self):
        buy_df = pd.DataFrame({'date': [TEST_DATE_STR], 'code': ['000001'], 'name': ['A']})
        with patch.object(bss, 'load_params', return_value=dict(bss.DEFAULT_PARAMS)), \
             patch.object(bss, 'select_buy_signals', return_value=buy_df), \
             patch.object(bss, 'select_sell_signals', return_value=None), \
             patch.object(bss, '_store_signals') as mock_store, \
             patch.object(bss, '_delete_day') as mock_del:
            res = bss.recompute(TEST_DATE)
        self.assertEqual(res, {'buy': 1, 'sell': 0})
        mock_store.assert_called_once()       # 买入写库
        mock_del.assert_called_once()          # 卖出无信号 → 清当日


if __name__ == '__main__':
    unittest.main()
