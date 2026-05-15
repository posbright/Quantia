#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试所有策略文件的 datetime.date vs str 日期类型兼容性。

核心场景：当 data['date'] 列包含 datetime.date 对象时，
所有策略的 mask 比较操作不应抛出 TypeError。
"""

import datetime
import numpy as np
import pandas as pd
import pytest

# ============================================================
# 构造包含 datetime.date 类型日期列的测试数据
# ============================================================
def make_test_data(n=300, use_date_objects=True):
    """构造测试用 DataFrame，date列使用 datetime.date 对象模拟 _backfill_from_spot 输出"""
    base = datetime.date(2024, 1, 2)
    dates = [base + datetime.timedelta(days=i) for i in range(n)]
    np.random.seed(42)
    closes = 10 + np.cumsum(np.random.randn(n) * 0.3)
    closes = np.maximum(closes, 1.0)
    opens = closes * (1 + np.random.randn(n) * 0.01)
    highs = np.maximum(closes, opens) * (1 + np.abs(np.random.randn(n) * 0.01))
    lows = np.minimum(closes, opens) * (1 - np.abs(np.random.randn(n) * 0.01))
    volumes = np.random.randint(100000, 10000000, size=n).astype(float)
    p_changes = np.zeros(n)
    p_changes[1:] = (closes[1:] - closes[:-1]) / closes[:-1] * 100

    data = pd.DataFrame({
        'date': dates if use_date_objects else [d.strftime('%Y-%m-%d') for d in dates],
        'open': opens,
        'close': closes,
        'high': highs,
        'low': lows,
        'volume': volumes,
        'p_change': p_changes,
    })
    return data


CODE_NAME = ('2024-08-01', '测试股票', '000001')


# ============================================================
# 测试旧版独立策略文件
# ============================================================
class TestOldStrategies:
    """测试 quantia/core/strategy/ 下的旧版独立策略文件"""

    def test_turtle_trade(self):
        from quantia.core.strategy.turtle_trade import check_enter
        data = make_test_data()
        # 不应抛出 TypeError
        result = check_enter(CODE_NAME, data)
        assert isinstance(result, (bool, dict))

    def test_climax_limitdown(self):
        from quantia.core.strategy.climax_limitdown import check
        data = make_test_data()
        result = check(CODE_NAME, data)
        assert isinstance(result, bool)

    def test_enter(self):
        from quantia.core.strategy.enter import check_volume
        data = make_test_data()
        result = check_volume(CODE_NAME, data)
        assert isinstance(result, bool)

    def test_high_tight_flag(self):
        from quantia.core.strategy.high_tight_flag import check_high_tight
        data = make_test_data()
        result = check_high_tight(CODE_NAME, data, istop=True)
        assert isinstance(result, bool)

    def test_keep_increasing(self):
        from quantia.core.strategy.keep_increasing import check
        data = make_test_data()
        result = check(CODE_NAME, data)
        assert isinstance(result, bool)

    def test_low_atr(self):
        from quantia.core.strategy.low_atr import check_low_increase
        data = make_test_data()
        result = check_low_increase(CODE_NAME, data)
        assert isinstance(result, bool)

    def test_low_backtrace_increase(self):
        from quantia.core.strategy.low_backtrace_increase import check
        data = make_test_data()
        result = check(CODE_NAME, data)
        assert isinstance(result, (bool, dict))

    def test_backtrace_ma250(self):
        from quantia.core.strategy.backtrace_ma250 import check
        data = make_test_data()
        result = check(CODE_NAME, data)
        assert isinstance(result, (bool, dict))

    def test_breakthrough_platform(self):
        from quantia.core.strategy.breakthrough_platform import check
        data = make_test_data()
        result = check(CODE_NAME, data)
        assert isinstance(result, (bool, dict))

    def test_parking_apron(self):
        from quantia.core.strategy.parking_apron import check
        data = make_test_data()
        result = check(CODE_NAME, data)
        assert isinstance(result, (bool, dict))


# ============================================================
# 测试回测引擎
# ============================================================
class TestBacktestEngine:
    def test_calculate_simple_returns(self):
        from quantia.core.backtest.bt_engine import calculate_simple_returns
        data = make_test_data()
        result = calculate_simple_returns(data, '2024-06-01')
        assert isinstance(result, dict)


# ============================================================
# 测试核心模块（之前已修复的）
# ============================================================
class TestCoreModules:
    def test_rate_stats(self):
        from quantia.core.backtest.rate_stats import get_rates
        data = make_test_data()
        # get_rates 需要特定列，可能返回None，但不应抛TypeError
        try:
            result = get_rates(CODE_NAME, data)
        except TypeError as e:
            if ">=" in str(e) or "<=" in str(e):
                pytest.fail(f"Date comparison TypeError: {e}")

    def test_calculate_indicator(self):
        from quantia.core.indicator.calculate_indicator import get_indicators
        data = make_test_data()
        try:
            # get_indicators(data, end_date=...) — 第一参数是 DataFrame，不是 code_name
            result = get_indicators(data, end_date=CODE_NAME[0])
        except TypeError as e:
            if ">=" in str(e) or "<=" in str(e):
                pytest.fail(f"Date comparison TypeError: {e}")

    def test_pattern_recognitions(self):
        from quantia.core.pattern.pattern_recognitions import get_pattern_recognition
        data = make_test_data()
        try:
            result = get_pattern_recognition(CODE_NAME, data)
        except TypeError as e:
            if ">=" in str(e) or "<=" in str(e):
                pytest.fail(f"Date comparison TypeError: {e}")


# ============================================================
# 测试 date 为字符串时也正常（回归测试）
# ============================================================
class TestStringDates:
    """确保字符串日期（正常路径）仍然工作"""

    def test_turtle_trade_str(self):
        from quantia.core.strategy.turtle_trade import check_enter
        data = make_test_data(use_date_objects=False)
        result = check_enter(CODE_NAME, data)
        assert isinstance(result, (bool, dict))

    def test_backtrace_ma250_str(self):
        from quantia.core.strategy.backtrace_ma250 import check
        data = make_test_data(use_date_objects=False)
        result = check(CODE_NAME, data)
        assert isinstance(result, (bool, dict))

    def test_breakthrough_platform_str(self):
        from quantia.core.strategy.breakthrough_platform import check
        data = make_test_data(use_date_objects=False)
        result = check(CODE_NAME, data)
        assert isinstance(result, (bool, dict))

    def test_parking_apron_str(self):
        from quantia.core.strategy.parking_apron import check
        data = make_test_data(use_date_objects=False)
        result = check(CODE_NAME, data)
        assert isinstance(result, (bool, dict))


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
