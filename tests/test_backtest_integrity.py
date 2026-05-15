#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回测系统完整性测试

验证回测系统的六大核心规则：
1. 数据准备：复权处理、幸存者偏差意识
2. 策略逻辑：信号日 vs 执行日
3. 模拟规则：未来函数检测、交易成本、涨跌停过滤
4. 绩效评估：收益率计算正确性
5. 稳健性：参数敏感性
6. 工具集成：各模块一致性
"""

import datetime
import os
import sys
import unittest
import numpy as np
import pandas as pd

# 确保项目路径在 sys.path 中
cpath = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
sys.path.insert(0, cpath)


def _make_hist(days=20, start_price=10.0, daily_return=0.01, start_date='2026-01-05'):
    """生成模拟历史数据（含 open/high/low/close/volume/date）"""
    dates = pd.bdate_range(start=start_date, periods=days)
    rows = []
    price = start_price
    for i, d in enumerate(dates):
        open_p = price * (1 + np.random.uniform(-0.005, 0.005))
        close_p = price * (1 + daily_return)
        high_p = max(open_p, close_p) * (1 + np.random.uniform(0.001, 0.01))
        low_p = min(open_p, close_p) * (1 - np.random.uniform(0.001, 0.01))
        rows.append({
            'date': d.strftime('%Y-%m-%d'),
            'open': round(open_p, 2),
            'close': round(close_p, 2),
            'high': round(high_p, 2),
            'low': round(low_p, 2),
            'volume': 1000000 + i * 10000,
        })
        price = close_p
    return pd.DataFrame(rows)


def _make_hist_deterministic(closes, opens=None, start_date='2026-01-05'):
    """根据精确价格序列生成历史数据"""
    n = len(closes)
    dates = pd.bdate_range(start=start_date, periods=n)
    if opens is None:
        opens = [c * 0.995 for c in closes]  # 默认 open = close * 0.995
    rows = []
    for i in range(n):
        rows.append({
            'date': dates[i].strftime('%Y-%m-%d'),
            'open': round(opens[i], 4),
            'close': round(closes[i], 4),
            'high': round(max(opens[i], closes[i]) * 1.005, 4),
            'low': round(min(opens[i], closes[i]) * 0.995, 4),
            'volume': 1000000,
        })
    return pd.DataFrame(rows)


class TestRateStatsLookAheadBias(unittest.TestCase):
    """验证 rate_stats.get_rates() 修正后不存在未来函数"""

    def setUp(self):
        from quantia.core.backtest.rate_stats import get_rates, ROUND_TRIP_COST_PCT
        self.get_rates = get_rates
        self.cost = ROUND_TRIP_COST_PCT

    def test_buy_price_uses_t_plus_1_open(self):
        """买入价应为T+1开盘价，而非T日收盘价"""
        # T=Day0 close=10, T+1=Day1 open=10.5, close=11
        closes = [10.0, 11.0, 12.0, 13.0, 14.0]
        opens  = [9.5, 10.5, 11.5, 12.5, 13.5]
        hist = _make_hist_deterministic(closes, opens)

        signal_date = hist.iloc[0]['date']  # Day0 = 信号日
        columns = ['date', 'code', 'rate_1', 'rate_2', 'rate_3']
        # threshold = len(columns) - 1 以匹配真实调用方式
        result = self.get_rates((signal_date, '000001'), hist, columns, threshold=len(columns) - 1)

        self.assertIsNotNone(result)
        # rate_1: (close[T+1] - open[T+1]) / open[T+1] * 100 - cost
        # = (11.0 - 10.5) / 10.5 * 100 - cost = 4.76 - 0.20 = 4.56
        expected_rate_1 = round(100 * (11.0 - 10.5) / 10.5 - self.cost, 2)
        self.assertAlmostEqual(result['rate_1'], expected_rate_1, places=1)

    def test_rate_1_is_not_overnight_return(self):
        """rate_1 不应等于隔夜收益（T收盘→T+1收盘），而是日内收益"""
        closes = [10.0, 11.0]
        opens  = [10.0, 10.8]  # T+1 open gap up
        hist = _make_hist_deterministic(closes, opens)

        signal_date = hist.iloc[0]['date']
        columns = ['date', 'code', 'rate_1']
        result = self.get_rates((signal_date, '000001'), hist, columns, threshold=len(columns) - 1)

        # 旧版本（bug）: rate_1 = (11-10)/10*100 = 10%
        # 修正版本:       rate_1 = (11-10.8)/10.8*100 - cost ≈ 1.65%
        wrong_value = round(100 * (11.0 - 10.0) / 10.0 - self.cost, 2)
        correct_value = round(100 * (11.0 - 10.8) / 10.8 - self.cost, 2)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result['rate_1'], correct_value, places=1)
        self.assertNotAlmostEqual(result['rate_1'], wrong_value, places=0)

    def test_limit_up_filtered(self):
        """T+1开盘涨停（>=9.5%）时应返回None（无法买入）"""
        closes = [10.0, 11.0, 12.0]
        opens  = [10.0, 11.0, 12.0]  # T+1 open = 11.0, gap = 10% >= 9.5%
        hist = _make_hist_deterministic(closes, opens)

        signal_date = hist.iloc[0]['date']
        columns = ['date', 'code', 'rate_1', 'rate_2']
        result = self.get_rates((signal_date, '000001'), hist, columns, threshold=len(columns) - 1)

        # T+1 open = 11.0, T close = 10.0, gap = 10% → 涨停，返回 None
        self.assertIsNone(result)

    def test_just_below_limit_up_not_filtered(self):
        """T+1开盘涨幅<9.5%时不应被过滤"""
        closes = [10.0, 10.8, 11.0]
        opens  = [10.0, 10.9, 10.8]  # T+1 open=10.9, gap=9% < 9.5%
        hist = _make_hist_deterministic(closes, opens)

        signal_date = hist.iloc[0]['date']
        columns = ['date', 'code', 'rate_1', 'rate_2']
        result = self.get_rates((signal_date, '000001'), hist, columns, threshold=len(columns) - 1)

        self.assertIsNotNone(result)


class TestTransactionCosts(unittest.TestCase):
    """验证交易成本扣除逻辑"""

    def test_cost_constants_reasonable(self):
        """交易成本参数在合理范围内"""
        from quantia.core.backtest.rate_stats import (
            COMMISSION_RATE, STAMP_TAX_RATE, SLIPPAGE_RATE, ROUND_TRIP_COST_PCT
        )
        # 佣金: 0.01% ~ 0.1%
        self.assertGreater(COMMISSION_RATE, 0.0001)
        self.assertLess(COMMISSION_RATE, 0.001)
        # 印花税: 0.05% (A股现行)
        self.assertAlmostEqual(STAMP_TAX_RATE, 0.0005, places=4)
        # 滑点: 0 ~ 0.5%
        self.assertGreater(SLIPPAGE_RATE, 0)
        self.assertLess(SLIPPAGE_RATE, 0.005)
        # 总成本: 0.1% ~ 0.5% 
        self.assertGreater(ROUND_TRIP_COST_PCT, 0.1)
        self.assertLess(ROUND_TRIP_COST_PCT, 0.5)

    def test_net_return_less_than_raw(self):
        """扣费后收益率严格低于原始收益率"""
        from quantia.core.backtest.rate_stats import get_rates, ROUND_TRIP_COST_PCT

        closes = [10.0, 10.5, 11.0, 11.5, 12.0]
        opens  = [10.0, 10.2, 10.6, 11.1, 11.6]
        hist = _make_hist_deterministic(closes, opens)

        signal_date = hist.iloc[0]['date']
        columns = ['date', 'code', 'rate_1', 'rate_2', 'rate_3']
        result = get_rates((signal_date, '000001'), hist, columns, threshold=len(columns) - 1)

        self.assertIsNotNone(result)
        # 原始 rate_1 (不扣费) = (10.5 - 10.2) / 10.2 * 100 ≈ 2.94%
        raw_rate_1 = round(100 * (10.5 - 10.2) / 10.2, 2)
        # 扣费后 = raw - cost
        self.assertAlmostEqual(result['rate_1'], round(raw_rate_1 - ROUND_TRIP_COST_PCT, 2), places=1)

    def test_zero_return_becomes_negative_after_costs(self):
        """0收益扣费后应为负（交易成本是真实摩擦）"""
        from quantia.core.backtest.rate_stats import get_rates, ROUND_TRIP_COST_PCT

        # T+1 open = close → 0% raw return becomes -cost%
        closes = [10.0, 10.2, 10.2]
        opens  = [10.0, 10.2, 10.2]  # T+1 open = 10.2, T+1 close = 10.2
        hist = _make_hist_deterministic(closes, opens)

        signal_date = hist.iloc[0]['date']
        columns = ['date', 'code', 'rate_1']
        result = get_rates((signal_date, '000001'), hist, columns, threshold=len(columns) - 1)
        # gap = (10.2-10)/10 = 2% < 9.5%, 不涨停
        self.assertIsNotNone(result)
        # rate_1 = (10.2-10.2)/10.2*100 - cost = 0 - 0.20 = -0.20
        self.assertAlmostEqual(result['rate_1'], round(-ROUND_TRIP_COST_PCT, 2), places=1)


class TestCalculateSimpleReturns(unittest.TestCase):
    """验证 bt_engine.calculate_simple_returns 与 rate_stats 一致"""

    def test_uses_t_plus_1_open(self):
        """calculate_simple_returns 也应使用T+1开盘价"""
        from quantia.core.backtest.bt_engine import calculate_simple_returns

        closes = [10.0, 10.5, 11.0, 11.5, 12.0, 12.5, 13.0]
        opens  = [10.0, 10.2, 10.6, 11.1, 11.6, 12.1, 12.6]
        hist = _make_hist_deterministic(closes, opens)

        signal_date = hist.iloc[0]['date']
        result = calculate_simple_returns(hist, signal_date, days=[1, 3, 5])

        # buy_price = T+1 open = 10.2
        # rate_1 = (close[T+1] - 10.2) / 10.2 * 100 - cost = (10.5-10.2)/10.2*100 - cost
        from quantia.core.backtest.rate_stats import ROUND_TRIP_COST_PCT
        expected_1 = round((10.5 - 10.2) / 10.2 * 100 - ROUND_TRIP_COST_PCT, 2)
        self.assertIsNotNone(result[1])
        self.assertAlmostEqual(result[1], expected_1, places=1)


class TestNoFutureFunction(unittest.TestCase):
    """验证不存在未来函数问题"""

    def test_signal_day_data_not_used_as_buy_price(self):
        """信号日(T)的收盘价不应作为买入基准"""
        from quantia.core.backtest.rate_stats import get_rates

        # 极端情况：T close = 10, T+1 open = 15（巨大缺口）
        # 如果使用T close作为基准，rate会虚高
        closes = [10.0, 16.0, 17.0]
        opens  = [10.0, 15.0, 16.0]  # T+1 开盘大幅跳空但<9.5% limit (15/10=50%...)
        hist = _make_hist_deterministic(closes, opens)

        signal_date = hist.iloc[0]['date']
        columns = ['date', 'code', 'rate_1']
        # 50% gap → 涨停过滤
        result = get_rates((signal_date, '000001'), hist, columns, threshold=len(columns) - 1)
        # 因为 gap = 50% >> 9.5%, 会被涨停过滤
        self.assertIsNone(result)

    def test_small_gap_uses_open_not_close(self):
        """小缺口时应用T+1 open而非T close"""
        from quantia.core.backtest.rate_stats import get_rates, ROUND_TRIP_COST_PCT

        closes = [10.0, 10.5, 11.0]
        opens  = [10.0, 10.3, 10.6]  # gap = 3%
        hist = _make_hist_deterministic(closes, opens)

        signal_date = hist.iloc[0]['date']
        columns = ['date', 'code', 'rate_1']
        result = get_rates((signal_date, '000001'), hist, columns, threshold=len(columns) - 1)

        self.assertIsNotNone(result)
        # rate_1 基于 open[T+1]=10.3, 不是 close[T]=10.0
        expected = round(100 * (10.5 - 10.3) / 10.3 - ROUND_TRIP_COST_PCT, 2)
        self.assertAlmostEqual(result['rate_1'], expected, places=1)


class TestEdgeCases(unittest.TestCase):
    """边界情况测试"""

    def test_only_two_data_points(self):
        """仅有信号日+T+1两天数据时应正常返回rate_1"""
        from quantia.core.backtest.rate_stats import get_rates

        closes = [10.0, 10.5]
        opens  = [10.0, 10.2]
        hist = _make_hist_deterministic(closes, opens)

        signal_date = hist.iloc[0]['date']
        columns = ['date', 'code', 'rate_1']
        result = get_rates((signal_date, '000001'), hist, columns, threshold=len(columns) - 1)
        self.assertIsNotNone(result)

    def test_only_signal_day_returns_none(self):
        """仅有信号日1天数据时应返回None"""
        from quantia.core.backtest.rate_stats import get_rates

        closes = [10.0]
        opens  = [10.0]
        hist = _make_hist_deterministic(closes, opens)

        signal_date = hist.iloc[0]['date']
        columns = ['date', 'code', 'rate_1']
        result = get_rates((signal_date, '000001'), hist, columns, threshold=len(columns) - 1)
        self.assertIsNone(result)

    def test_none_data_returns_none(self):
        from quantia.core.backtest.rate_stats import get_rates
        result = get_rates(('2026-01-01', '000001'), None, ['date', 'code', 'rate_1'], len(['date', 'code', 'rate_1']) - 1)
        self.assertIsNone(result)

    def test_negative_return_stock(self):
        """下跌股票应产生负收益"""
        from quantia.core.backtest.rate_stats import get_rates, ROUND_TRIP_COST_PCT

        closes = [10.0, 9.5, 9.0, 8.5]
        opens  = [10.0, 9.8, 9.3, 8.8]  # gap = -2%
        hist = _make_hist_deterministic(closes, opens)

        signal_date = hist.iloc[0]['date']
        columns = ['date', 'code', 'rate_1', 'rate_2']
        result = get_rates((signal_date, '000001'), hist, columns, threshold=len(columns) - 1)

        self.assertIsNotNone(result)
        # rate_1 = (9.5 - 9.8) / 9.8 * 100 - cost ≈ -3.06 - 0.20 = -3.26
        expected = round(100 * (9.5 - 9.8) / 9.8 - ROUND_TRIP_COST_PCT, 2)
        self.assertAlmostEqual(result['rate_1'], expected, places=1)
        self.assertLess(result['rate_1'], 0)

    def test_no_open_column_degrades_gracefully(self):
        """缓存数据无open列时应降级使用close（不crash）"""
        from quantia.core.backtest.rate_stats import get_rates

        hist = pd.DataFrame({
            'date': ['2026-01-05', '2026-01-06', '2026-01-07'],
            'close': [10.0, 10.5, 11.0],
            'high': [10.5, 11.0, 11.5],
            'low': [9.5, 10.0, 10.5],
            'volume': [1000000, 1000000, 1000000],
        })

        columns = ['date', 'code', 'rate_1', 'rate_2']
        result = get_rates(('2026-01-05', '000001'), hist, columns, threshold=len(columns) - 1)
        # 降级时使用 close[0]=10.0 作为基准
        self.assertIsNotNone(result)


class TestReturnColumnConsistency(unittest.TestCase):
    """验证 rate_1..rate_N 的列数和填充逻辑"""

    def test_rates_count_matches_columns(self):
        """rate_N 的数量应与输入列匹配"""
        from quantia.core.backtest.rate_stats import get_rates

        closes = [10.0, 10.5, 11.0, 11.5, 12.0]
        opens  = [10.0, 10.2, 10.6, 11.1, 11.6]
        hist = _make_hist_deterministic(closes, opens)

        columns = ['date', 'code'] + [f'rate_{i}' for i in range(1, 11)]
        # threshold = len(columns) - 1 = 11, 表示最多使用11行数据
        result = get_rates((hist.iloc[0]['date'], '000001'), hist, columns, threshold=len(columns) - 1)

        self.assertIsNotNone(result)
        self.assertEqual(len(result), len(columns))
        # 5行数据, T+1到T+4: 能算 rate_1 到 rate_3 (T+1=rate_1, ..., T+3=rate_3)
        # wait: 5 data rows with threshold=11 → head(11)=5 rows
        # future_closes = close[1:] = 4 values → rate_1 to rate_4
        for i in range(1, 5):
            self.assertIsNotNone(result[f'rate_{i}'])
        for i in range(5, 11):
            self.assertIsNone(result[f'rate_{i}'])

    def test_rate_semantics(self):
        """rate_N 的含义：持有N天后的收益（相对于T+1开盘价）"""
        from quantia.core.backtest.rate_stats import get_rates, ROUND_TRIP_COST_PCT

        # 精确控制价格：每天涨1元
        closes = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0]
        opens  = [10.0, 10.5, 11.5, 12.5, 13.5, 14.5]
        hist = _make_hist_deterministic(closes, opens)

        columns = ['date', 'code', 'rate_1', 'rate_2', 'rate_3', 'rate_4', 'rate_5']
        # threshold = len(columns)-1 = 6, 正好使用全部6行
        result = get_rates((hist.iloc[0]['date'], '000001'), hist, columns, threshold=len(columns) - 1)

        self.assertIsNotNone(result)
        buy_price = 10.5  # T+1 open
        # rate_1: (close[T+1] - buy) / buy = (11.0 - 10.5) / 10.5 = 4.76% - cost
        # rate_2: (close[T+2] - buy) / buy = (12.0 - 10.5) / 10.5 = 14.29% - cost
        # rate_3: (close[T+3] - buy) / buy = (13.0 - 10.5) / 10.5 = 23.81% - cost
        for n, expected_close in [(1, 11.0), (2, 12.0), (3, 13.0), (4, 14.0), (5, 15.0)]:
            expected = round(100 * (expected_close - buy_price) / buy_price - ROUND_TRIP_COST_PCT, 2)
            self.assertAlmostEqual(result[f'rate_{n}'], expected, places=1,
                                   msg=f"rate_{n} should be ~{expected}%")


class TestBacktestHandlerConsistency(unittest.TestCase):
    """验证 backtestHandler 中的函数签名正确性"""

    def test_imports_cost_constant(self):
        """backtestHandler 应正确引入交易成本常量"""
        from quantia.web.backtestHandler import ROUND_TRIP_COST_PCT
        from quantia.core.backtest.rate_stats import ROUND_TRIP_COST_PCT as expected
        self.assertEqual(ROUND_TRIP_COST_PCT, expected)

    def test_dashboard_imports_cost_constant(self):
        """backtestDashboardHandler 应正确引入交易成本常量"""
        from quantia.web.backtestDashboardHandler import ROUND_TRIP_COST_PCT
        from quantia.core.backtest.rate_stats import ROUND_TRIP_COST_PCT as expected
        self.assertEqual(ROUND_TRIP_COST_PCT, expected)


class TestSurvivorshipBiasAwareness(unittest.TestCase):
    """幸存者偏差相关检测（文档化而非代码修复）"""

    def test_backtest_job_uses_cached_data(self):
        """回测作业应能处理缓存中存在但当前已退市的股票"""
        # 这是一个设计层面的测试：验证 backtest_data_daily_job.process()
        # 读取策略表中的 (date, code) 并从缓存获取历史数据，
        # 而不是从当前 cn_stock_spot 表获取代码列表。
        # 关键：策略表中记录了信号产生时的 code（可能后来退市），
        # 只要缓存文件存在就能回测。
        import quantia.job.backtest_data_daily_job as bdj
        # process 函数签名检查
        import inspect
        sig = inspect.signature(bdj.process)
        params = list(sig.parameters.keys())
        self.assertIn('table', params)
        # 确认 process 从策略表读取 code，而非从 cn_stock_spot
        source = inspect.getsource(bdj.process)
        self.assertNotIn('cn_stock_spot', source)
        self.assertIn('SELECT * FROM', source)


class TestQfqAdjustment(unittest.TestCase):
    """验证前复权数据正确使用"""

    def test_cache_uses_qfq(self):
        """缓存文件路径应包含 qfq 标识"""
        from quantia.core.stockfetch import _get_cache_file_path
        path = _get_cache_file_path('000001', 'qfq')
        self.assertIn('qfq', path)

    def test_fetch_stock_hist_uses_qfq(self):
        """fetch_stock_hist 默认使用前复权"""
        import inspect
        from quantia.core.stockfetch import fetch_stock_hist
        source = inspect.getsource(fetch_stock_hist)
        self.assertIn("'qfq'", source)


if __name__ == '__main__':
    unittest.main()
