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


# ── v2 五维真融合测试 ────────────────────────────────────────────────

def _make_signal_df(codes, dates):
    """构造 (date, code) DataFrame。"""
    rows = []
    for d in dates:
        for c in codes:
            rows.append({'date': d, 'code': c})
    return pd.DataFrame(rows)


def _make_rate_df(codes, dates, rate_value=1.0):
    """构造 (date, code, rate) DataFrame。"""
    rows = []
    for d in dates:
        for c in codes:
            rows.append({'date': d, 'code': c, 'rate': rate_value})
    return pd.DataFrame(rows)


class TestStrategyFusionHandlerV2(AsyncHTTPTestCase):

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

    def test_v2_invalid_mode(self):
        code, data = self._post({
            'version': 2, 'mode': 'no_such_mode',
            'start_date': '2025-01-01', 'end_date': '2025-03-01',
            'dimensions': {'tech': {'enabled': True, 'weight': 100, 'items': ['cn_stock_strategy_keep_increasing']}},
        })
        assert code == 400
        assert 'mode' in data.get('error', '')

    def test_v2_no_dim_enabled(self):
        code, data = self._post({
            'version': 2, 'mode': 'weighted_score',
            'start_date': '2025-01-01', 'end_date': '2025-03-01',
            'dimensions': {
                'tech': {'enabled': False, 'weight': 50, 'items': []},
                'fund': {'enabled': False, 'weight': 50, 'items': []},
            },
        })
        assert code == 400
        assert '维度' in data.get('error', '')

    def test_v2_date_range_too_large(self):
        code, data = self._post({
            'version': 2, 'mode': 'weighted_score',
            'start_date': '2024-01-01', 'end_date': '2025-06-01',
            'dimensions': {'tech': {'enabled': True, 'weight': 100, 'items': ['cn_stock_strategy_keep_increasing']}},
        })
        assert code == 400
        assert '366' in data.get('error', '') or '区间' in data.get('error', '')

    def test_v2_vote_basic(self):
        """vote 模式 + 单维 tech，验证 schema 与基本指标。"""
        dates = pd.date_range('2025-01-02', periods=10, freq='B')
        sig = _make_signal_df(['600001', '600002'], dates)
        rate = _make_rate_df(['600001', '600002'], dates, rate_value=2.0)

        with mock.patch.object(vfh, '_load_dim_signals', return_value=(sig, [])), \
             mock.patch.object(vfh, '_load_rate_df', return_value=rate):
            code, data = self._post({
                'version': 2, 'mode': 'vote', 'vote_threshold': 1,
                'start_date': '2025-01-01', 'end_date': '2025-02-01', 'holding_days': 5,
                'dimensions': {
                    'tech': {'enabled': True, 'weight': 100, 'items': ['cn_stock_strategy_keep_increasing']},
                },
            })
        assert code == 200, data
        assert data['version'] == 2
        assert data['mode'] == 'vote'
        assert data['diagnostics']['enabled_dims'] == ['tech']
        assert data['fusion_result']['signal_count'] == 20  # 2 codes × 10 days
        assert data['fusion_result']['win_rate'] == 100.0   # all rate=2.0 positive
        assert len(data['daily_series']) == 10

    def test_v2_weighted_score_multi_dim(self):
        """三维 weighted_score：tech ∪ fund ∪ flow 都贡献。"""
        dates = pd.date_range('2025-01-02', periods=5, freq='B')
        # tech 命中 A,B；fund 命中 B,C；flow 命中 C
        tech_sig = _make_signal_df(['A', 'B'], dates)
        fund_sig = _make_signal_df(['B', 'C'], dates)
        flow_sig = _make_signal_df(['C'], dates)
        rate = _make_rate_df(['A', 'B', 'C'], dates, rate_value=1.0)

        def load_side(key, items, s, e):
            return {'tech': (tech_sig, []), 'fund': (fund_sig, []), 'flow': (flow_sig, [])}.get(key, (pd.DataFrame(columns=['date', 'code']), []))

        with mock.patch.object(vfh, '_load_dim_signals', side_effect=load_side), \
             mock.patch.object(vfh, '_load_rate_df', return_value=rate):
            # weight: tech=50, fund=30, flow=20。total=100
            # A: tech only → score = 50/100 = 0.5
            # B: tech+fund → score = 80/100 = 0.8
            # C: fund+flow → score = 50/100 = 0.5
            # min_score = 0.6 → 只有 B 入选
            code, data = self._post({
                'version': 2, 'mode': 'weighted_score', 'min_score': 0.6,
                'start_date': '2025-01-01', 'end_date': '2025-02-01', 'holding_days': 5,
                'dimensions': {
                    'tech': {'enabled': True, 'weight': 50, 'items': ['x']},
                    'fund': {'enabled': True, 'weight': 30, 'items': ['pe9_lt_30']},
                    'flow': {'enabled': True, 'weight': 20, 'items': ['fund_amount_gt_0']},
                },
            })
        assert code == 200, data
        assert data['diagnostics']['enabled_dims'] == ['tech', 'fund', 'flow']
        # 只 B 入选 → 5 个日期 × 1 个 code = 5 signals
        assert data['fusion_result']['signal_count'] == 5
        # individual_results 三维度都有
        assert set(data['individual_results'].keys()) == {'tech', 'fund', 'flow'}
        assert data['individual_results']['tech']['signal_count'] == 10  # A,B × 5 days
        assert data['individual_results']['fund']['signal_count'] == 10
        assert data['individual_results']['flow']['signal_count'] == 5

    def test_v2_condition_tree_intersection(self):
        """condition_tree = 多维 AND 链。"""
        dates = pd.date_range('2025-01-02', periods=3, freq='B')
        tech_sig = _make_signal_df(['A', 'B', 'C'], dates)
        fund_sig = _make_signal_df(['B', 'C', 'D'], dates)
        rate = _make_rate_df(['A', 'B', 'C', 'D'], dates, rate_value=1.5)

        def load_side(key, items, s, e):
            return {'tech': (tech_sig, []), 'fund': (fund_sig, [])}.get(key, (pd.DataFrame(columns=['date', 'code']), []))

        with mock.patch.object(vfh, '_load_dim_signals', side_effect=load_side), \
             mock.patch.object(vfh, '_load_rate_df', return_value=rate):
            code, data = self._post({
                'version': 2, 'mode': 'condition_tree',
                'start_date': '2025-01-01', 'end_date': '2025-02-01', 'holding_days': 5,
                'dimensions': {
                    'tech': {'enabled': True, 'weight': 50, 'items': ['x']},
                    'fund': {'enabled': True, 'weight': 30, 'items': ['pe9_lt_30']},
                },
            })
        assert code == 200, data
        # 交集 = B, C → 3 dates × 2 codes = 6
        assert data['fusion_result']['signal_count'] == 6

    def test_v2_rotation_warns_fallback(self):
        """rotation 模式 Stage 1 应回退 weighted_score 并发出 warning。"""
        dates = pd.date_range('2025-01-02', periods=3, freq='B')
        sig = _make_signal_df(['A'], dates)
        rate = _make_rate_df(['A'], dates, rate_value=1.0)

        with mock.patch.object(vfh, '_load_dim_signals', return_value=(sig, [])), \
             mock.patch.object(vfh, '_load_rate_df', return_value=rate):
            code, data = self._post({
                'version': 2, 'mode': 'rotation',
                'start_date': '2025-01-01', 'end_date': '2025-02-01', 'holding_days': 5,
                'dimensions': {'tech': {'enabled': True, 'weight': 100, 'items': ['x']}},
            })
        assert code == 200, data
        assert any('rotation' in w for w in data['warnings'])

    def test_v2_dim_empty_warns_and_removed(self):
        """某维度命中 0 → warnings 包含该维度 + diagnostics.enabled_dims 不含它。"""
        dates = pd.date_range('2025-01-02', periods=3, freq='B')
        tech_sig = _make_signal_df(['A'], dates)
        empty = pd.DataFrame(columns=['date', 'code'])
        rate = _make_rate_df(['A'], dates, rate_value=1.0)

        def load_side(key, items, s, e):
            if key == 'tech':
                return tech_sig, []
            return empty, []

        with mock.patch.object(vfh, '_load_dim_signals', side_effect=load_side), \
             mock.patch.object(vfh, '_load_rate_df', return_value=rate):
            code, data = self._post({
                'version': 2, 'mode': 'weighted_score', 'min_score': 0.0,
                'start_date': '2025-01-01', 'end_date': '2025-02-01', 'holding_days': 5,
                'dimensions': {
                    'tech': {'enabled': True, 'weight': 60, 'items': ['x']},
                    'fund': {'enabled': True, 'weight': 40, 'items': ['pe9_lt_30']},
                },
            })
        assert code == 200, data
        assert data['diagnostics']['enabled_dims'] == ['tech']
        assert any('基本面' in w and '0' in w for w in data['warnings'])

    def test_parse_item_expr_valid(self):
        col, op, val = vfh._parse_item_expr('pe9_lt_30', vfh._FUND_ALLOWED_COLS)
        assert (col, op, val) == ('pe9', '<', 30.0)
        col, op, val = vfh._parse_item_expr('fund_amount_3_gte_500', vfh._FLOW_ALLOWED_COLS)
        assert (col, op, val) == ('fund_amount_3', '>=', 500.0)

    def test_parse_item_expr_invalid(self):
        with pytest.raises(vfh._ValidationError):
            vfh._parse_item_expr('no_such_col_lt_5', vfh._FUND_ALLOWED_COLS)
        with pytest.raises(vfh._ValidationError):
            vfh._parse_item_expr('pe9_xx_30', vfh._FUND_ALLOWED_COLS)
        with pytest.raises(vfh._ValidationError):
            vfh._parse_item_expr('pe9_lt_notanumber', vfh._FUND_ALLOWED_COLS)

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
