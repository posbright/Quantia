#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""选股验证中心 — verifyFusionHandler 单元测试。"""

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

import quantia.web.verifyFusionHandler as vfh
import quantia.web.verifyOptimizeHandler as voh
import quantia.lib.database as mdb


# ── 测试数据工厂 ──────────────────────────────────────────────────────

def _reset_strategy_cache():
    voh._STRATEGY_MAP = None


def _make_backtest_df(n=50, strategy_seed=42):
    np.random.seed(strategy_seed)
    dates = pd.date_range('2025-01-01', periods=n, freq='B')
    data = {
        'date': dates,
        'code': [f'60000{i % 9}' for i in range(n)],
        'rate': np.random.normal(0.5, 3.0, n),
    }
    return pd.DataFrame(data)


def _make_app():
    return Application([
        (r'/api/verify/fusion', vfh.StrategyFusionHandler),
        (r'/api/verify/optimize_suggest', vfh.OptimizeSuggestHandler),
    ])


# ── StrategyFusionHandler 测试 ────────────────────────────────────────

class TestStrategyFusionHandler(AsyncHTTPTestCase):

    def setUp(self):
        super().setUp()
        _reset_strategy_cache()

    def get_app(self):
        return _make_app()

    def _post(self, body):
        resp = self.fetch('/api/verify/fusion', method='POST',
                         body=json.dumps(body),
                         headers={'Content-Type': 'application/json'})
        return resp.code, json.loads(resp.body)

    def test_missing_strategies(self):
        code, data = self._post({'strategy_names': ['放量上涨'], 'mode': 'intersection',
                                  'start_date': '2025-01-01', 'end_date': '2025-03-01'})
        assert code == 400
        assert '至少' in data.get('error', '')

    def test_invalid_mode(self):
        code, data = self._post({'strategy_names': ['放量上涨', '均线多头'], 'mode': 'invalid',
                                  'start_date': '2025-01-01', 'end_date': '2025-03-01'})
        assert code == 400
        assert 'mode' in data.get('error', '')

    def test_missing_dates(self):
        code, data = self._post({'strategy_names': ['放量上涨', '均线多头'], 'mode': 'intersection'})
        assert code == 400

    @mock.patch.object(mdb, 'checkTableIsExist', return_value=True)
    @mock.patch('quantia.web.verifyFusionHandler.pd.read_sql')
    def test_intersection_mode(self, mock_sql, mock_table):
        # Both strategies share same (date, code) pairs
        df = _make_backtest_df(30, strategy_seed=42)
        mock_sql.return_value = df

        code, data = self._post({
            'strategy_names': ['放量上涨', '均线多头'],
            'mode': 'intersection',
            'start_date': '2025-01-01',
            'end_date': '2025-03-01',
            'holding_days': 5,
        })
        assert code == 200
        assert data['fusion_mode'] == 'intersection'
        assert 'fusion_result' in data
        assert data['fusion_result']['signal_count'] >= 0

    @mock.patch.object(mdb, 'checkTableIsExist', return_value=True)
    @mock.patch('quantia.web.verifyFusionHandler.pd.read_sql')
    def test_union_mode(self, mock_sql, mock_table):
        df = _make_backtest_df(30, strategy_seed=42)
        mock_sql.return_value = df

        code, data = self._post({
            'strategy_names': ['放量上涨', '均线多头'],
            'mode': 'union',
            'start_date': '2025-01-01',
            'end_date': '2025-03-01',
        })
        assert code == 200
        assert data['fusion_mode'] == 'union'
        assert data['fusion_result']['signal_count'] > 0

    @mock.patch.object(mdb, 'checkTableIsExist', return_value=True)
    @mock.patch('quantia.web.verifyFusionHandler.pd.read_sql')
    def test_vote_mode(self, mock_sql, mock_table):
        df = _make_backtest_df(30, strategy_seed=42)
        mock_sql.return_value = df

        code, data = self._post({
            'strategy_names': ['放量上涨', '均线多头', '停机坪'],
            'mode': 'vote',
            'vote_threshold': 2,
            'start_date': '2025-01-01',
            'end_date': '2025-03-01',
        })
        assert code == 200
        assert data['fusion_mode'] == 'vote'
        assert data['vote_threshold'] == 2

    @mock.patch.object(mdb, 'checkTableIsExist', return_value=True)
    @mock.patch('quantia.web.verifyFusionHandler.pd.read_sql')
    def test_rotation_mode(self, mock_sql, mock_table):
        df = _make_backtest_df(60, strategy_seed=42)
        mock_sql.return_value = df

        code, data = self._post({
            'strategy_names': ['放量上涨', '均线多头'],
            'mode': 'rotation',
            'start_date': '2025-01-01',
            'end_date': '2025-06-01',
        })
        assert code == 200
        assert data['fusion_mode'] == 'rotation'

    @mock.patch.object(mdb, 'checkTableIsExist', return_value=True)
    @mock.patch('quantia.web.verifyFusionHandler.pd.read_sql')
    def test_filters_parameter(self, mock_sql, mock_table):
        df = _make_backtest_df(30, strategy_seed=42)
        # For indicators query, return a df with the indicator column
        ind_df = df[['date', 'code']].copy()
        ind_df['rsi_6'] = np.random.uniform(20, 80, len(ind_df))

        def side_effect(sql, **kwargs):
            if 'cn_stock_indicators' in sql:
                return ind_df
            return df

        mock_sql.side_effect = side_effect

        code, data = self._post({
            'strategy_names': ['放量上涨', '均线多头'],
            'mode': 'union',
            'start_date': '2025-01-01',
            'end_date': '2025-03-01',
            'filters': {'rsi_6_max': 70, 'rsi_6_min': 30},
        })
        assert code == 200

    def test_too_many_strategies(self):
        code, data = self._post({
            'strategy_names': ['放量上涨'] * 7,
            'mode': 'intersection',
            'start_date': '2025-01-01',
            'end_date': '2025-03-01',
        })
        assert code == 400
        assert '最多' in data.get('error', '')

    def test_date_range_too_large(self):
        code, data = self._post({
            'strategy_names': ['放量上涨', '均线多头'],
            'mode': 'intersection',
            'start_date': '2023-01-01',
            'end_date': '2025-03-01',
        })
        assert code == 400
        assert '366' in data.get('error', '')


# ── OptimizeSuggestHandler 测试 ───────────────────────────────────────

class TestOptimizeSuggestHandler(AsyncHTTPTestCase):

    def setUp(self):
        super().setUp()
        _reset_strategy_cache()

    def get_app(self):
        return _make_app()

    @mock.patch.object(mdb, 'checkTableIsExist', return_value=True)
    @mock.patch('quantia.web.verifyFusionHandler.pd.read_sql')
    def test_basic_suggest(self, mock_sql, mock_table):
        np.random.seed(42)
        n = 100
        dates = pd.date_range('2025-01-01', periods=n, freq='B')
        data = {'date': dates, 'code': [f'60000{i % 9}' for i in range(n)]}
        for d in [1, 3, 5, 7, 10, 15, 20, 30]:
            data[f'rate_{d}'] = np.random.normal(0.5, 3.0, n)
        mock_sql.return_value = pd.DataFrame(data)

        resp = self.fetch('/api/verify/optimize_suggest?strategy=放量上涨&start_date=2025-01-01&end_date=2025-06-01')
        assert resp.code == 200
        body = json.loads(resp.body)
        assert 'suggestions' in body
        assert len(body['suggestions']) > 0

    def test_missing_params(self):
        resp = self.fetch('/api/verify/optimize_suggest?strategy=放量上涨')
        assert resp.code == 400
