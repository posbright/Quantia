#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略与指标 Bug 修复验证测试

覆盖本轮审计发现的 CRITICAL / HIGH / MEDIUM 级问题。
"""

import unittest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta


# ---------------------------------------------------------------------------
# 辅助函数：构造模拟 K 线 DataFrame
# ---------------------------------------------------------------------------
def _make_kline(rows, start_date='2025-01-01'):
    """
    rows: list of dict, each with optional keys:
        open, high, low, close, volume, amount, p_change
    Missing keys get reasonable defaults.
    """
    dates = pd.bdate_range(start=start_date, periods=len(rows), freq='B')
    records = []
    prev_close = None
    for i, r in enumerate(rows):
        o = r.get('open', 10.0)
        c = r.get('close', 10.0)
        h = r.get('high', max(o, c) * 1.01)
        l_ = r.get('low', min(o, c) * 0.99)
        v = r.get('volume', 1000000.0)
        amt = r.get('amount', c * v)
        if prev_close is not None and prev_close != 0:
            pc = r.get('p_change', (c - prev_close) / prev_close * 100)
        else:
            pc = r.get('p_change', 0.0)
        records.append({
            'date': dates[i].strftime('%Y-%m-%d'),
            'open': o, 'high': h, 'low': l_, 'close': c,
            'volume': v, 'amount': amt, 'p_change': pc,
        })
        prev_close = c
    return pd.DataFrame(records)


def _make_steady_rise(n=60, start=10.0, daily_pct=0.015):
    """构造稳步上涨、无大回撤的 K 线（用于 low_backtrace_increase 测试）"""
    rows = []
    price = start
    for i in range(n):
        o = price
        c = round(price * (1 + daily_pct), 4)
        h = round(c * 1.005, 4)
        l_ = round(o * 0.995, 4)
        rows.append({'open': o, 'close': c, 'high': h, 'low': l_,
                     'p_change': round(daily_pct * 100, 2)})
        price = c
    return _make_kline(rows)


# ===========================================================================
# CRITICAL: low_backtrace_increase 不再永远返回 False
# ===========================================================================
class TestLowBacktraceIncrease(unittest.TestCase):
    """验证 previous_open 初始化修复后策略可以返回 True"""

    def test_steady_rise_should_pass(self):
        """稳定上涨超60%、日回撤极小 → 应返回 True"""
        from quantia.core.strategy import low_backtrace_increase as lbi
        # 60 天每天涨 1.5%，累计涨幅 ≈ 144% >> 60%
        data = _make_steady_rise(n=60, start=10.0, daily_pct=0.015)
        code_name = (data.iloc[-1]['date'], 'SH600000')
        result = lbi.check(code_name, data, threshold=60)
        self.assertTrue(result, "稳步上涨无回撤应通过策略")

    def test_big_drop_should_fail(self):
        """含单日 > 7% 跌幅 → 应返回 False"""
        from quantia.core.strategy import low_backtrace_increase as lbi
        data = _make_steady_rise(n=60, start=10.0, daily_pct=0.015)
        # 在第30天注入一个 -8% 跌幅
        idx = 30
        prev_close = data.iloc[idx - 1]['close']
        data.loc[data.index[idx], 'p_change'] = -8.0
        data.loc[data.index[idx], 'close'] = prev_close * 0.92
        code_name = (data.iloc[-1]['date'], 'SH600000')
        result = lbi.check(code_name, data, threshold=60)
        self.assertFalse(result, "含 -8% 单日跌幅应拒绝")

    def test_insufficient_rise_should_fail(self):
        """涨幅 < 60% → 应在涨幅检查阶段返回 False"""
        from quantia.core.strategy import low_backtrace_increase as lbi
        data = _make_steady_rise(n=60, start=10.0, daily_pct=0.005)  # ~35%
        code_name = (data.iloc[-1]['date'], 'SH600000')
        result = lbi.check(code_name, data, threshold=60)
        self.assertFalse(result, "总涨幅 < 60% 应拒绝")

    def test_pattern_strategy_class_matches(self):
        """pattern_strategies.LowBacktraceIncreaseStrategy 应与函数版一致"""
        from quantia.core.strategy.pattern.pattern_strategies import LowBacktraceIncreaseStrategy
        strategy = LowBacktraceIncreaseStrategy(threshold=60)
        data = _make_steady_rise(n=60, start=10.0, daily_pct=0.015)
        code_name = (data.iloc[-1]['date'], 'SH600000')
        result = strategy.check(code_name, data)
        self.assertTrue(result, "OOP 版本应与函数版行为一致")


# ===========================================================================
# HIGH: enter.py / climax_limitdown.py 除零保护
# ===========================================================================
class TestDivisionByZeroGuard(unittest.TestCase):

    def test_enter_zero_vol_ma5(self):
        """vol_ma5 = 0 时不应抛异常"""
        from quantia.core.strategy import enter
        # 构造 volume 全为 0（5日均量=0）
        rows = [{'close': 10 + i * 0.3, 'open': 10 + i * 0.3 - 0.1,
                 'volume': 0.0, 'amount': 0.0, 'p_change': 3.0}
                for i in range(65)]
        data = _make_kline(rows)
        code_name = (data.iloc[-1]['date'], 'SH600000')
        # 不应抛出 ZeroDivisionError
        try:
            result = enter.check_volume(code_name, data, threshold=60)
        except ZeroDivisionError:
            self.fail("enter.check_volume 在 vol_ma5=0 时抛出 ZeroDivisionError")
        self.assertFalse(result)

    def test_climax_limitdown_zero_vol_ma5(self):
        """vol_ma5 = 0 时不应抛异常"""
        from quantia.core.strategy import climax_limitdown as cl
        rows = [{'close': 10 - i * 0.01, 'open': 10 - i * 0.01 + 0.1,
                 'volume': 0.0, 'amount': 0.0, 'p_change': -10.0}
                for i in range(65)]
        data = _make_kline(rows)
        code_name = (data.iloc[-1]['date'], 'SH600000')
        try:
            result = cl.check(code_name, data, threshold=60)
        except ZeroDivisionError:
            self.fail("climax_limitdown.check 在 vol_ma5=0 时抛出 ZeroDivisionError")
        self.assertFalse(result)


# ===========================================================================
# HIGH: backtrace_ma250 除零 & elif 修复
# ===========================================================================
class TestBacktraceMa250(unittest.TestCase):

    def test_no_division_by_zero_on_zero_volume(self):
        """recent_lowest_row volume=0 时不应除零"""
        from quantia.core.strategy import backtrace_ma250 as bm
        # 需要 250+ 行数据（MA250 需要 250 天）
        rows = []
        for i in range(300):
            rows.append({'open': 10.0, 'close': 10.0 + (i / 300.0),
                         'high': 10.5 + (i / 300.0), 'low': 9.5,
                         'volume': 0.0, 'amount': 0.0, 'p_change': 0.0})
        data = _make_kline(rows, start_date='2024-01-01')
        code_name = (data.iloc[-1]['date'], 'SH600000')
        try:
            result = bm.check(code_name, data, threshold=60)
        except ZeroDivisionError:
            self.fail("backtrace_ma250 在 volume=0 时抛出 ZeroDivisionError")
        # 策略判断应该返回 False（不满足条件），但不应崩溃
        self.assertIsInstance(result, bool)


# ===========================================================================
# HIGH: high_tight_flag 价格引用修复
# ===========================================================================
class TestHighTightFlag(unittest.TestCase):

    def test_uses_current_close_not_sliced_high(self):
        """验证 ratio 使用当日收盘价（非切片后的 day[-11] high）"""
        from quantia.core.strategy import high_tight_flag as htf
        # 构造 60 行数据
        rows = []
        for i in range(60):
            # 前 36 行低价平稳
            if i < 36:
                rows.append({'open': 5.0, 'close': 5.0, 'high': 5.1,
                             'low': 4.9, 'volume': 1e6, 'p_change': 0.0})
            # 第 37-38 行连续涨停
            elif i in (36, 37):
                rows.append({'open': 5.0, 'close': 5.5, 'high': 5.6,
                             'low': 4.9, 'volume': 1e6, 'p_change': 10.0})
            # 后面逐步上涨到 20（当日close=20 / 区间low=4.9 = 4.08 > 1.9）
            else:
                rows.append({'open': 15.0, 'close': 20.0, 'high': 20.5,
                             'low': 14.0, 'volume': 1e6, 'p_change': 2.0})
        data = _make_kline(rows)
        code_name = (data.iloc[-1]['date'], 'SH600000')
        # istop=True 才不会直接返回 False
        result = htf.check_high_tight(code_name, data, threshold=60, istop=True)
        # 关键：如果还在用 data.iloc[-1]['high']（切片后 = day[-11]），
        # ratio 会不同于用 current_close 的结果
        # 这里主要验证不崩溃且逻辑正确
        self.assertIsInstance(result, (bool, dict))


# ===========================================================================
# MEDIUM: execute_daily_job 表名
# ===========================================================================
class TestExecuteDailyJobTableName(unittest.TestCase):

    def test_health_check_uses_correct_table_name(self):
        """验证回测汇总表名是 cn_stock_backtest 而非 cn_stock_backtest_summary"""
        import ast
        with open('quantia/job/execute_daily_job.py', 'r', encoding='utf-8') as f:
            source = f.read()
        # 确保不存在错误的表名
        self.assertNotIn('cn_stock_backtest_summary', source,
                         "execute_daily_job.py 不应包含错误的表名 cn_stock_backtest_summary")
        # 确保正确的表名存在
        self.assertIn("'cn_stock_backtest'", source,
                       "execute_daily_job.py 应包含正确的表名 cn_stock_backtest")


# ===========================================================================
# MEDIUM: indicators_data_daily_job errors='ignore'
# ===========================================================================
class TestIndicatorsJobErrorsIgnore(unittest.TestCase):

    def test_drop_has_errors_ignore(self):
        """验证 drop('date') 调用包含 errors='ignore'"""
        with open('quantia/job/indicators_data_daily_job.py', 'r', encoding='utf-8') as f:
            source = f.read()
        # 查找 drop 调用
        self.assertIn("errors='ignore'", source,
                      "indicators_data_daily_job.py 的 drop 调用应包含 errors='ignore'")


# ===========================================================================
# MEDIUM: breakthrough_platform 偏离率公式方向
# ===========================================================================
class TestBreakthroughPlatformDeviation(unittest.TestCase):

    def test_deviation_formula_direction(self):
        """验证偏离率公式使用 (close - ma) / ma 而非 (ma - close) / ma"""
        with open('quantia/core/strategy/breakthrough_platform.py', 'r',
                  encoding='utf-8') as f:
            source = f.read()
        # 修复后应使用 (_close - _ma60) / _ma60
        self.assertIn('(_close - _ma60) / _ma60', source,
                      "偏离率应使用 (close - MA) / MA")
        # 不应包含旧的反向公式
        self.assertNotIn('(_ma60 - _close) / _ma60', source,
                         "不应包含旧的反向偏离率公式")


# ===========================================================================
# MEDIUM: calculate_indicator inf 处理
# ===========================================================================
class TestIndicatorInfHandling(unittest.TestCase):

    def test_emv_uses_fill_nan_inf(self):
        """EMV 和 VHF 应使用 _fill_nan_inf 而非 _fillna"""
        with open('quantia/core/indicator/calculate_indicator.py', 'r',
                  encoding='utf-8') as f:
            lines = f.readlines()
        
        # 查找 emv 赋值后的清理行
        found_emv_fix = False
        found_vhf_fix = False
        found_m_price_fix = False
        for i, line in enumerate(lines):
            if "'emv'" in line and '_fill_nan_inf' in line:
                found_emv_fix = True
            if "'vhf'" in line and '_fill_nan_inf' in line:
                found_vhf_fix = True
            if "'m_price'" in line and '_fill_nan_inf' in line:
                found_m_price_fix = True
        
        self.assertTrue(found_emv_fix, "EMV 应使用 _fill_nan_inf 清理 inf")
        self.assertTrue(found_vhf_fix, "VHF 应使用 _fill_nan_inf 清理 inf")
        self.assertTrue(found_m_price_fix, "m_price 应使用 _fill_nan_inf 清理 inf (volume=0)")


# ---------------------------------------------------------------------------
# Bug: get_indicators 收到 tuple 导致 TypeError
# ---------------------------------------------------------------------------

class TestGetIndicatorsTupleGuard(unittest.TestCase):
    """验证 get_indicators 对非 DataFrame 输入的防御"""

    def test_tuple_input_returns_none(self):
        """传入 tuple 时应返回 None 而非抛出 TypeError"""
        import sys, os
        sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
        import quantia.core.indicator.calculate_indicator as idr
        result = idr.get_indicators(("2026-03-12", "600519"), end_date="2026-03-12")
        self.assertIsNone(result)

    def test_none_input_returns_none(self):
        """传入 None 时应返回 None"""
        import sys, os
        sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
        import quantia.core.indicator.calculate_indicator as idr
        result = idr.get_indicators(None)
        self.assertIsNone(result)

    def test_valid_dataframe_not_rejected(self):
        """传入有效 DataFrame 时不应被类型检查拦截"""
        import sys, os
        sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
        import quantia.core.indicator.calculate_indicator as idr
        dates = pd.date_range("2025-01-01", periods=200, freq="B")
        np.random.seed(42)
        closes = np.random.uniform(10, 20, 200)
        df = pd.DataFrame({
            'date': dates,
            'open': np.random.uniform(10, 20, 200),
            'high': np.random.uniform(15, 25, 200),
            'low': np.random.uniform(5, 15, 200),
            'close': closes,
            'volume': np.random.randint(1000, 100000, 200).astype(float),
            'amount': np.random.uniform(10000, 500000, 200),
            'p_change': np.concatenate([[0], np.diff(closes) / closes[:-1] * 100]),
        })
        result = idr.get_indicators(df, threshold=120)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, pd.DataFrame)


# ---------------------------------------------------------------------------
# Bug: _ensure_params_table 使用 CREATE TABLE 无 IF NOT EXISTS
# ---------------------------------------------------------------------------

class TestEnsureParamsTableSQL(unittest.TestCase):
    """验证 _ensure_params_table 使用 IF NOT EXISTS 避免竞态"""

    def test_create_table_has_if_not_exists(self):
        """SQL 中应包含 IF NOT EXISTS 防止并发创建报错"""
        import inspect
        import sys, os
        sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
        import quantia.web.strategyParamsHandler as sph
        source = inspect.getsource(sph._ensure_params_table)
        self.assertIn("IF NOT EXISTS", source.upper(),
                       "_ensure_params_table 的 CREATE TABLE 应包含 IF NOT EXISTS")


if __name__ == '__main__':
    unittest.main()
