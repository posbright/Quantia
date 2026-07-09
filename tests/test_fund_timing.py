# -*- coding: utf-8 -*-
"""基金入场择时纯函数单测（quantia/core/fund/timing.py）。

覆盖：绝对时序刻度不变性、回撤/趋势映射、缺维重归一化、档位阈值。
纯合成数据，无 DB/网络依赖。
"""

import numpy as np

from quantia.core.fund import timing


class TestDrawdownFromHigh:
    def test_monotonic_up_no_drawdown_low_score(self):
        nav = list(np.linspace(1.0, 2.0, 100))  # 一路上涨，当前即峰值
        assert timing.drawdown_from_high(nav) == 0.0

    def test_deep_drawdown_caps_at_100(self):
        # 峰值 2.0 → 当前 1.3（跌 35% > cap 30%）→ 封顶 100
        nav = [1.0, 1.5, 2.0, 1.7, 1.3]
        assert timing.drawdown_from_high(nav) == 100.0

    def test_partial_drawdown_linear(self):
        # 峰值 2.0 → 当前 1.7（跌 15% = cap/2）→ 50
        nav = [1.0, 2.0, 1.7]
        assert abs(timing.drawdown_from_high(nav) - 50.0) < 1e-6

    def test_too_few_samples_none(self):
        assert timing.drawdown_from_high([1.0]) is None
        assert timing.drawdown_from_high([]) is None

    def test_scale_invariance(self):
        # 绝对时序口径：整体缩放常数倍，回撤分不变（证明非截面）
        nav = [1.0, 2.0, 1.6]
        a = timing.drawdown_from_high(nav)
        b = timing.drawdown_from_high([x * 37.0 for x in nav])
        assert abs(a - b) < 1e-9


class TestNavTrendScore:
    def test_above_ma_uptrend_gt_50(self):
        nav = list(np.linspace(1.0, 2.0, 80))  # 持续上行，站上均线 + 斜率正
        s = timing.nav_trend_score(nav, ma_window=60)
        assert s is not None and s > 50.0

    def test_below_ma_downtrend_lt_50(self):
        up = list(np.linspace(1.0, 2.0, 60))
        down = list(np.linspace(2.0, 1.2, 40))  # 后段大幅下行，跌破均线
        s = timing.nav_trend_score(up + down, ma_window=60)
        assert s is not None and s < 50.0

    def test_insufficient_samples_none(self):
        assert timing.nav_trend_score(list(np.linspace(1, 2, 30)), ma_window=60) is None

    def test_scale_invariance(self):
        nav = list(np.linspace(1.0, 1.8, 90))
        a = timing.nav_trend_score(nav, ma_window=60)
        b = timing.nav_trend_score([x * 12.5 for x in nav], ma_window=60)
        assert a is not None and b is not None
        assert abs(a - b) < 1e-6


class TestValuationPercentileScore:
    def test_p1_none_passthrough(self):
        assert timing.valuation_percentile_score(None) is None

    def test_cheap_low_percentile_high_score(self):
        # 当前值是历史最低 → 分位≈1/n 很低 → 分数高
        series = [30, 28, 25, 22, 15]
        s = timing.valuation_percentile_score(series)
        assert s is not None and s >= 80.0

    def test_expensive_high_percentile_low_score(self):
        series = [15, 22, 25, 28, 30]  # 当前最高 → 分数低
        s = timing.valuation_percentile_score(series)
        assert s is not None and s <= 20.0


class TestComposeTimingScore:
    def test_all_dims_weighted(self):
        r = timing.compose_timing_score(80, 60, 40)
        # 0.5*80 + 0.3*60 + 0.2*40 = 40+18+8 = 66
        assert abs(r['score'] - 66.0) < 1e-6
        assert r['tier'] == '定投'
        assert r['dims_used'] == ['dd', 'trend', 'val']

    def test_val_missing_renormalizes(self):
        # 缺 val：权重 dd 0.5/trend 0.3 → 归一 0.625/0.375
        r = timing.compose_timing_score(80, 60, None)
        expected = (0.5 * 80 + 0.3 * 60) / (0.5 + 0.3)
        assert abs(r['score'] - expected) < 1e-6
        assert r['dims_used'] == ['dd', 'trend']
        assert r['components']['val'] is None

    def test_all_missing_none(self):
        r = timing.compose_timing_score(None, None, None)
        assert r['score'] is None and r['tier'] is None and r['dims_used'] == []

    def test_score_clipped_0_100(self):
        r = timing.compose_timing_score(100, 100, 100)
        assert 0.0 <= r['score'] <= 100.0


class TestTierOf:
    def test_thresholds(self):
        assert timing.tier_of(79) == '低吸'
        assert timing.tier_of(75) == '低吸'
        assert timing.tier_of(60) == '定投'
        assert timing.tier_of(50) == '定投'
        assert timing.tier_of(40) == '观望'
        assert timing.tier_of(30) == '观望'
        assert timing.tier_of(20) == '高估勿追'
        assert timing.tier_of(0) == '高估勿追'

    def test_none_and_nan(self):
        assert timing.tier_of(None) is None
        assert timing.tier_of(float('nan')) is None
