# -*- coding: utf-8 -*-
"""P4 T6 穿透式持仓位置纯函数单测（lookthrough）。纯序列，无 DB/网络。"""

import numpy as np

from quantia.core.fund import lookthrough as lt


class TestDrawdownPosition:
    def test_at_high_low_score(self):
        # 单调上涨，收在最高点 → 距高点回撤 0 → 位置分 0（高位）
        close = list(np.linspace(1.0, 2.0, 300))
        assert lt.drawdown_position(close) == 0.0

    def test_deep_drawdown_high_score(self):
        # 先涨到 2 再腰斩到 1（-50%）→ 达 cap → 位置分 100（低位）
        close = list(np.linspace(1.0, 2.0, 200)) + list(np.linspace(2.0, 1.0, 100))
        assert lt.drawdown_position(close) == 100.0

    def test_short_series_none(self):
        assert lt.drawdown_position([1.0]) is None


class TestMaPosition:
    def test_below_ma_high_score(self):
        # 长期在均线上方后急跌到均线下方 → 位置分 > 50
        close = list(np.linspace(1.0, 2.0, 120)) + list(np.linspace(2.0, 1.2, 40))
        v = lt.ma_position(close, ma_window=60)
        assert v is not None and v > 50

    def test_above_ma_low_score(self):
        # 收盘远在均线上方 → 位置分 < 50（高位）
        close = list(np.linspace(1.0, 3.0, 200))
        v = lt.ma_position(close, ma_window=60)
        assert v is not None and v < 50

    def test_short_series_none(self):
        assert lt.ma_position([1.0, 1.1, 1.2], ma_window=60) is None


class TestRsiPosition:
    def test_oversold_high_score(self):
        # 单调下跌 → RSI≈0 → 位置分≈100（超卖=低位）
        close = list(np.linspace(2.0, 1.0, 60))
        v = lt.rsi_position(close, n=14)
        assert v is not None and v > 90

    def test_overbought_low_score(self):
        # 单调上涨 → RSI≈100 → 位置分≈0（超买=高位）
        close = list(np.linspace(1.0, 2.0, 60))
        v = lt.rsi_position(close, n=14)
        assert v is not None and v < 10

    def test_short_series_none(self):
        assert lt.rsi_position([1.0, 1.1], n=14) is None


class TestStockPosition:
    def test_all_dims_present(self):
        close = list(np.linspace(1.0, 2.0, 200)) + list(np.linspace(2.0, 1.3, 80))
        res = lt.stock_position(close)
        assert res['score'] is not None
        assert res['dd'] is not None and res['ma'] is not None and res['rsi'] is not None
        assert 0.0 <= res['score'] <= 100.0

    def test_short_series_dd_ma_none_rsi_maybe(self):
        # 仅 5 个点：dd 有值（≥2），ma/rsi 缺 → score 仅由 dd 决定
        res = lt.stock_position([1.0, 1.1, 1.2, 1.15, 1.05])
        assert res['ma'] is None and res['rsi'] is None
        assert res['dd'] is not None
        assert res['score'] == res['dd']

    def test_empty_all_none(self):
        res = lt.stock_position([])
        assert res['score'] is None and res['dd'] is None


class TestAggregate:
    def test_weighted_by_hold_ratio(self):
        items = [
            {'hold_ratio': 8.0, 'score': 90.0},
            {'hold_ratio': 2.0, 'score': 40.0},
        ]
        res = lt.aggregate_positions(items)
        # (90*8 + 40*2)/10 = 80
        assert res['position_score'] == 80.0
        assert res['covered_ratio'] == 10.0
        assert res['n'] == 2

    def test_skips_none_and_nonpositive_weight(self):
        items = [
            {'hold_ratio': 5.0, 'score': 60.0},
            {'hold_ratio': None, 'score': 90.0},   # 无权重 → 跳过
            {'hold_ratio': 3.0, 'score': None},    # 无分 → 跳过
            {'hold_ratio': 0.0, 'score': 50.0},    # 权重 0 → 跳过
        ]
        res = lt.aggregate_positions(items)
        assert res['position_score'] == 60.0
        assert res['covered_ratio'] == 5.0
        assert res['n'] == 1

    def test_empty(self):
        res = lt.aggregate_positions([])
        assert res['position_score'] is None
        assert res['covered_ratio'] == 0.0
        assert res['n'] == 0


class TestLabel:
    def test_labels(self):
        assert lt.position_label(80.0) == '多数处于低位'
        assert lt.position_label(55.0) == '中性偏均衡'
        assert lt.position_label(20.0) == '多数处于高位'
        assert lt.position_label(None) is None
        assert lt.position_label(float('nan')) is None
