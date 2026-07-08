#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""筹码分布计算模块单元测试（纯函数，零 DB、零网络）。"""

import math
import unittest

import numpy as np
import pandas as pd

import quantia.core.kline.chip_distribution as cyqd


def _make_hist(n=60, base=10.0, drift=0.0, turnover=3.0, seed=42):
    """构造升序 K 线 DataFrame（含 open/high/low/close/turnover）。"""
    rng = np.random.RandomState(seed)
    closes = []
    price = base
    for i in range(n):
        price = max(0.5, price + drift + rng.uniform(-0.15, 0.15))
        closes.append(price)
    closes = np.array(closes)
    highs = closes * (1 + rng.uniform(0.0, 0.03, n))
    lows = closes * (1 - rng.uniform(0.0, 0.03, n))
    opens = (highs + lows) / 2.0
    dates = pd.date_range('2026-01-01', periods=n, freq='D')
    return pd.DataFrame({
        'date': dates,
        'open': opens,
        'high': highs,
        'low': lows,
        'close': closes,
        'turnover': [turnover] * n,
    })


class TestChipDistribution(unittest.TestCase):

    def test_basic_metrics_ranges(self):
        m = cyqd.compute_chip_metrics(_make_hist())
        self.assertIsNotNone(m)
        self.assertGreaterEqual(m['winner_rate'], 0.0)
        self.assertLessEqual(m['winner_rate'], 100.0)
        self.assertGreater(m['avg_cost'], 0.0)
        self.assertLessEqual(m['cost_90_low'], m['cost_90_high'])
        self.assertLessEqual(m['cost_70_low'], m['cost_70_high'])
        # 70% 区间应落在 90% 区间之内（或相等）
        self.assertGreaterEqual(m['cost_70_low'], m['cost_90_low'] - 1e-6)
        self.assertLessEqual(m['cost_70_high'], m['cost_90_high'] + 1e-6)

    def test_all_profit_when_price_above_all_cost(self):
        hist = _make_hist(base=10.0, turnover=5.0)
        m = cyqd.compute_chip_metrics(hist, close_override=1000.0)
        self.assertIsNotNone(m)
        self.assertAlmostEqual(m['winner_rate'], 100.0, delta=0.5)

    def test_all_loss_when_price_below_all_cost(self):
        hist = _make_hist(base=10.0, turnover=5.0)
        m = cyqd.compute_chip_metrics(hist, close_override=0.01)
        self.assertIsNotNone(m)
        self.assertAlmostEqual(m['winner_rate'], 0.0, delta=0.5)

    def test_zero_turnover_returns_none(self):
        hist = _make_hist(turnover=0.0)
        self.assertIsNone(cyqd.compute_chip_metrics(hist))

    def test_insufficient_bars_returns_none(self):
        hist = _make_hist(n=5)
        self.assertIsNone(cyqd.compute_chip_metrics(hist, min_bars=20))

    def test_missing_turnover_column_returns_none(self):
        hist = _make_hist().drop(columns=['turnover'])
        self.assertIsNone(cyqd.compute_chip_metrics(hist))

    def test_no_nan_inf_in_output(self):
        m = cyqd.compute_chip_metrics(_make_hist())
        self.assertIsNotNone(m)
        for k, v in m.items():
            self.assertIsNotNone(v, f"{k} is None")
            self.assertTrue(math.isfinite(v), f"{k}={v} not finite")

    def test_one_word_board(self):
        """一字板：high==low==open==close，不应崩溃。"""
        n = 30
        dates = pd.date_range('2026-01-01', periods=n, freq='D')
        price = np.array([10.0] * n)
        hist = pd.DataFrame({
            'date': dates,
            'open': price, 'high': price, 'low': price, 'close': price,
            'turnover': [2.0] * n,
        })
        m = cyqd.compute_chip_metrics(hist)
        self.assertIsNotNone(m)
        self.assertTrue(math.isfinite(m['winner_rate']))
        self.assertAlmostEqual(m['avg_cost'], 10.0, delta=0.5)

    def test_concentration_in_unit_range(self):
        m = cyqd.compute_chip_metrics(_make_hist())
        self.assertIsNotNone(m)
        for key in ('concentration_90', 'concentration_70'):
            self.assertGreaterEqual(m[key], 0.0)
            self.assertLessEqual(m[key], 1.0)

    def test_empty_or_none_input(self):
        self.assertIsNone(cyqd.compute_chip_metrics(None))
        self.assertIsNone(cyqd.compute_chip_metrics(pd.DataFrame()))


class TestChipDistributionHistogram(unittest.TestCase):
    """compute_chip_distribution：直方图 + 标量。"""

    def test_returns_prices_chips_and_metrics(self):
        d = cyqd.compute_chip_distribution(_make_hist())
        self.assertIsNotNone(d)
        self.assertIn('prices', d)
        self.assertIn('chips', d)
        self.assertIn('metrics', d)
        self.assertIn('close', d)
        # prices/chips 等长
        self.assertEqual(len(d['prices']), len(d['chips']))
        self.assertGreater(len(d['prices']), 0)

    def test_prices_ascending(self):
        d = cyqd.compute_chip_distribution(_make_hist())
        prices = d['prices']
        for i in range(1, len(prices)):
            self.assertGreaterEqual(prices[i], prices[i - 1])

    def test_chips_sum_to_100(self):
        d = cyqd.compute_chip_distribution(_make_hist())
        total = sum(d['chips'])
        self.assertAlmostEqual(total, 100.0, delta=0.5)

    def test_chips_all_finite_nonneg(self):
        d = cyqd.compute_chip_distribution(_make_hist())
        for c in d['chips']:
            self.assertTrue(math.isfinite(c))
            self.assertGreaterEqual(c, 0.0)
        for p in d['prices']:
            self.assertTrue(math.isfinite(p))

    def test_metrics_match_compute_chip_metrics(self):
        hist = _make_hist()
        d = cyqd.compute_chip_distribution(hist)
        m = cyqd.compute_chip_metrics(hist)
        self.assertIsNotNone(d)
        self.assertIsNotNone(m)
        for k in ('winner_rate', 'avg_cost', 'cost_90_low', 'cost_90_high',
                  'concentration_90', 'cost_70_low', 'cost_70_high', 'concentration_70'):
            self.assertAlmostEqual(d['metrics'][k], m[k], delta=1e-6, msg=k)

    def test_missing_turnover_returns_none(self):
        hist = _make_hist().drop(columns=['turnover'])
        self.assertIsNone(cyqd.compute_chip_distribution(hist))

    def test_zero_turnover_returns_none(self):
        self.assertIsNone(cyqd.compute_chip_distribution(_make_hist(turnover=0.0)))

    def test_insufficient_bars_returns_none(self):
        self.assertIsNone(cyqd.compute_chip_distribution(_make_hist(n=5), min_bars=20))

    def test_empty_or_none_input(self):
        self.assertIsNone(cyqd.compute_chip_distribution(None))
        self.assertIsNone(cyqd.compute_chip_distribution(pd.DataFrame()))


if __name__ == '__main__':
    unittest.main()
