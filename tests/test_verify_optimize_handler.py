#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""选股验证中心 — verifyOptimizeHandler 单元测试。"""

import json
import os
import sys
from unittest import mock

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tornado.testing import AsyncHTTPTestCase
from tornado.web import Application

import quantia.web.verifyOptimizeHandler as voh


# ── 测试数据工厂 ──────────────────────────────────────────────────────

def _reset_strategy_cache():
    """重置策略映射缓存，确保测试使用最新配置。"""
    voh._STRATEGY_MAP = None

def _make_backtest_df(n=50, max_days=20):
    """生成模拟回测数据 DataFrame。"""
    np.random.seed(42)
    dates = pd.date_range('2025-01-01', periods=n, freq='B')
    data = {'date': dates, 'code': [f'60000{i % 9}' for i in range(n)], 'name': [f'股票{i}' for i in range(n)]}
    for d in range(1, max_days + 1):
        data[f'rate_{d}'] = np.random.normal(0.5, 3.0, n)
    return pd.DataFrame(data)


def _make_app():
    return Application([
        (r'/api/verify/holding_period', voh.HoldingPeriodAnalysisHandler),
        (r'/api/verify/signal_quality', voh.SignalQualityHandler),
        (r'/api/verify/sl_tp_matrix', voh.StopLossTakeProfitMatrixHandler),
        (r'/api/verify/market_regime', voh.MarketRegimeHandler),
        (r'/api/verify/signal_decay', voh.SignalDecayHandler),
        (r'/api/verify/cost_sensitivity', voh.CostSensitivityHandler),
    ])


# ── 持仓天数扫描 ──────────────────────────────────────────────────────

class TestHoldingPeriodHandler(AsyncHTTPTestCase):
    def get_app(self):
        return _make_app()

    def setUp(self):
        _reset_strategy_cache()
        super().setUp()

    def test_missing_strategy(self):
        resp = self.fetch('/api/verify/holding_period?start_date=2025-01-01&end_date=2025-06-01')
        body = json.loads(resp.body)
        self.assertIn('error', body)

    def test_missing_dates(self):
        resp = self.fetch('/api/verify/holding_period?strategy=keep_increasing')
        body = json.loads(resp.body)
        self.assertIn('error', body)

    def test_unknown_strategy(self):
        resp = self.fetch('/api/verify/holding_period?strategy=nonexist&start_date=2025-01-01&end_date=2025-06-01')
        body = json.loads(resp.body)
        self.assertIn('error', body)
        self.assertIn('未知', body['error'])

    def test_empty_data(self):
        with mock.patch.object(voh.mdb, 'checkTableIsExist', return_value=True), \
             mock.patch.object(voh.pd, 'read_sql', return_value=pd.DataFrame()):
            resp = self.fetch('/api/verify/holding_period?strategy=keep_increasing&start_date=2025-01-01&end_date=2025-06-01')
        body = json.loads(resp.body)
        self.assertEqual(body['total_signals'], 0)
        self.assertEqual(body['analysis'], [])

    def test_normal_response(self):
        df = _make_backtest_df(100, 60)
        with mock.patch.object(voh.mdb, 'checkTableIsExist', return_value=True), \
             mock.patch.object(voh.pd, 'read_sql', return_value=df):
            resp = self.fetch('/api/verify/holding_period?strategy=keep_increasing&start_date=2025-01-01&end_date=2025-06-01&holding_days=1,5,10,20')
        body = json.loads(resp.body)
        self.assertEqual(body['total_signals'], 100)
        self.assertEqual(len(body['analysis']), 4)
        for item in body['analysis']:
            self.assertIn('holding_days', item)
            self.assertIn('avg_return', item)
            self.assertIn('sharpe_approx', item)
            self.assertIn('percentile_10', item)
            self.assertIn('percentile_90', item)
        self.assertIsNotNone(body['best_holding_days'])

    def test_date_range_too_large(self):
        resp = self.fetch('/api/verify/holding_period?strategy=keep_increasing&start_date=2024-01-01&end_date=2025-12-31')
        body = json.loads(resp.body)
        self.assertIn('error', body)
        self.assertIn('366', body['error'])


# ── 信号质量诊断 ──────────────────────────────────────────────────────

class TestSignalQualityHandler(AsyncHTTPTestCase):
    def get_app(self):
        return _make_app()

    def setUp(self):
        _reset_strategy_cache()
        super().setUp()

    def test_invalid_indicator(self):
        resp = self.fetch('/api/verify/signal_quality?strategy=keep_increasing&start_date=2025-01-01&end_date=2025-06-01&indicator=invalid_xxx')
        body = json.loads(resp.body)
        self.assertIn('error', body)
        self.assertIn('不支持', body['error'])

    def test_empty_result(self):
        with mock.patch.object(voh.mdb, 'checkTableIsExist', return_value=True), \
             mock.patch.object(voh.pd, 'read_sql', return_value=pd.DataFrame()):
            resp = self.fetch('/api/verify/signal_quality?strategy=keep_increasing&start_date=2025-01-01&end_date=2025-06-01&indicator=rsi_6')
        body = json.loads(resp.body)
        self.assertEqual(body['buckets'], [])

    def test_normal_response(self):
        np.random.seed(123)
        n = 200
        df = pd.DataFrame({
            'date': pd.date_range('2025-01-01', periods=n, freq='B'),
            'code': [f'60000{i % 9}' for i in range(n)],
            'rate': np.random.normal(1.5, 4.0, n),
            'ind_val': np.random.uniform(10, 90, n),
        })
        with mock.patch.object(voh.mdb, 'checkTableIsExist', return_value=True), \
             mock.patch.object(voh.pd, 'read_sql', return_value=df):
            resp = self.fetch('/api/verify/signal_quality?strategy=keep_increasing&start_date=2025-01-01&end_date=2025-06-01&indicator=rsi_6&holding_days=5')
        body = json.loads(resp.body)
        self.assertIn('buckets', body)
        self.assertGreater(len(body['buckets']), 0)
        for b in body['buckets']:
            self.assertIn('quality', b)
            self.assertIn(b['quality'], ('golden', 'good', 'neutral', 'filter'))


# ── 止盈止损矩阵 ──────────────────────────────────────────────────────

class TestSlTpMatrixHandler(AsyncHTTPTestCase):
    def get_app(self):
        return _make_app()

    def setUp(self):
        _reset_strategy_cache()
        super().setUp()

    def test_normal_response(self):
        df = _make_backtest_df(80, 20)
        with mock.patch.object(voh.mdb, 'checkTableIsExist', return_value=True), \
             mock.patch.object(voh.pd, 'read_sql', return_value=df):
            resp = self.fetch('/api/verify/sl_tp_matrix?strategy=keep_increasing&start_date=2025-01-01&end_date=2025-06-01&sl_range=-3,-5,-8&tp_range=3,5,8&max_hold_days=10')
        body = json.loads(resp.body)
        self.assertIn('matrix', body)
        # 3 SL × 3 TP = 9 组合
        self.assertEqual(len(body['matrix']), 9)
        for item in body['matrix']:
            self.assertIn('stop_loss', item)
            self.assertIn('take_profit', item)
            self.assertIn('sharpe', item)
            self.assertIn('trades_hit_sl', item)
            self.assertIn('trades_hit_tp', item)
        self.assertIsNotNone(body['best_combo'])

    def test_empty_data(self):
        with mock.patch.object(voh.mdb, 'checkTableIsExist', return_value=True), \
             mock.patch.object(voh.pd, 'read_sql', return_value=pd.DataFrame()):
            resp = self.fetch('/api/verify/sl_tp_matrix?strategy=keep_increasing&start_date=2025-01-01&end_date=2025-06-01')
        body = json.loads(resp.body)
        self.assertEqual(body['matrix'], [])


# ── 信号衰减分析 ──────────────────────────────────────────────────────

class TestSignalDecayHandler(AsyncHTTPTestCase):
    def get_app(self):
        return _make_app()

    def setUp(self):
        _reset_strategy_cache()
        super().setUp()

    def test_normal_response(self):
        df = _make_backtest_df(200, 10)
        with mock.patch.object(voh.mdb, 'checkTableIsExist', return_value=True), \
             mock.patch.object(voh.pd, 'read_sql', return_value=df):
            resp = self.fetch('/api/verify/signal_decay?strategy=keep_increasing&start_date=2025-01-01&end_date=2025-12-01&holding_days=5')
        body = json.loads(resp.body)
        self.assertIn('monthly', body)
        self.assertGreater(len(body['monthly']), 0)
        for m in body['monthly']:
            self.assertIn('month', m)
            self.assertIn('avg_return', m)
            self.assertIn('win_rate', m)


# ── 交易成本敏感性 ────────────────────────────────────────────────────

class TestCostSensitivityHandler(AsyncHTTPTestCase):
    def get_app(self):
        return _make_app()

    def setUp(self):
        _reset_strategy_cache()
        super().setUp()

    def test_normal_response(self):
        df = _make_backtest_df(100, 10)
        with mock.patch.object(voh.mdb, 'checkTableIsExist', return_value=True), \
             mock.patch.object(voh.pd, 'read_sql', return_value=df):
            resp = self.fetch('/api/verify/cost_sensitivity?strategy=keep_increasing&start_date=2025-01-01&end_date=2025-06-01&holding_days=5')
        body = json.loads(resp.body)
        self.assertIn('scenarios', body)
        self.assertEqual(len(body['scenarios']), 8)
        # 确认有一个 is_current=True
        current = [s for s in body['scenarios'] if s['is_current']]
        self.assertEqual(len(current), 1)


# ── 市场环境分类 ──────────────────────────────────────────────────────

class TestMarketRegimeHandler(AsyncHTTPTestCase):
    def get_app(self):
        return _make_app()

    def setUp(self):
        _reset_strategy_cache()
        super().setUp()

    def test_normal_response(self):
        df = _make_backtest_df(100, 10)
        # 构造基准数据
        np.random.seed(99)
        n = 200
        bench_df = pd.DataFrame({
            'date': pd.date_range('2024-10-01', periods=n, freq='B'),
            'close': np.cumsum(np.random.normal(0, 1, n)) + 3500,
            'high': np.cumsum(np.random.normal(0, 1, n)) + 3510,
            'low': np.cumsum(np.random.normal(0, 1, n)) + 3490,
        })
        with mock.patch.object(voh.mdb, 'checkTableIsExist', return_value=True), \
             mock.patch.object(voh.pd, 'read_sql', return_value=df), \
             mock.patch('quantia.core.backtest.data_feed.load_benchmark_data', return_value=bench_df):
            resp = self.fetch('/api/verify/market_regime?strategy=keep_increasing&start_date=2025-01-01&end_date=2025-06-01&benchmark=000300')
        body = json.loads(resp.body)
        self.assertIn('regimes', body)
        self.assertIn('strategy_by_regime', body)
        # 至少应有一种环境
        self.assertGreater(len(body['regimes']), 0)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
