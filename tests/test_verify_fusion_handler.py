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


# ── Stage 3: 真 Shapley / AB / Overlap 单元测试 ────────────────────────

class TestShapleyABOverlap:
    """直接测试 Stage 3 模块级函数（不走 HTTP 层）。"""

    def _make_spec(self, mode='weighted_score', weights=None, holding=5):
        weights = weights or {'tech': 50, 'fund': 30, 'flow': 20}
        dims = {}
        for k, w in weights.items():
            dims[k] = {'enabled': True, 'weight': w, 'items': ['x']}
        return {
            'mode': mode,
            'start_date': pd.Timestamp('2025-01-01').date(),
            'end_date': pd.Timestamp('2025-02-01').date(),
            'holding_days': holding,
            'min_score': 0.0,
            'vote_threshold': 1,
            'dimensions': dims,
        }

    def test_fuse_subset_signals_single_dim(self):
        dates = pd.date_range('2025-01-02', periods=3, freq='B')
        sig = _make_signal_df(['A', 'B'], dates)
        spec = self._make_spec(weights={'tech': 50, 'fund': 50})
        fused = vfh._fuse_subset_signals({'tech': sig}, spec)
        assert len(fused) == 6  # 3 days × 2 codes

    def test_fuse_subset_signals_renormalizes_weights(self):
        dates = pd.date_range('2025-01-02', periods=3, freq='B')
        tech = _make_signal_df(['A', 'B'], dates)
        fund = _make_signal_df(['B', 'C'], dates)
        # spec weights: tech=50/fund=30/flow=20。子集 tech+fund 重新归一化 -> tech=62.5, fund=37.5
        spec = self._make_spec(weights={'tech': 50, 'fund': 30, 'flow': 20})
        spec['min_score'] = 0.5
        fused = vfh._fuse_subset_signals({'tech': tech, 'fund': fund}, spec)
        # 重归一化后 tech 62.5%, fund 37.5%; B 同时命中 = 1.0 ≥ 0.5 ✓
        # A 仅 tech = 0.625 ≥ 0.5 ✓
        # C 仅 fund = 0.375 < 0.5 ✗
        codes = set(fused['code'].unique())
        assert 'A' in codes and 'B' in codes
        assert 'C' not in codes

    def test_shapley_real_two_dims(self):
        dates = pd.date_range('2025-01-02', periods=4, freq='B')
        tech = _make_signal_df(['A', 'B'], dates)
        fund = _make_signal_df(['B', 'C'], dates)
        rate = _make_rate_df(['A', 'B', 'C'], dates, rate_value=1.0)
        dim_signals = {'tech': tech, 'fund': fund}
        spec = self._make_spec(weights={'tech': 50, 'fund': 50})
        spec['min_score'] = 0.0
        items, used_fb, diag = vfh._shapley_real(dim_signals, spec, rate, time_budget_s=8.0)
        assert used_fb is False
        assert len(items) == 2
        # 子集枚举数 = 2^2 - 1 = 3（不含空集）
        assert diag['n_subsets_evaluated'] == 3
        assert diag['total_subsets'] == 4
        # 排序：贡献大的在前；rank 字段连续 1..n
        ranks = [i['rank'] for i in items]
        assert ranks == [1, 2]
        # 每个 item 必有 dim/contrib/contribution/sharpe_delta
        for it in items:
            assert 'dim' in it and 'contrib' in it and 'sharpe_delta' in it

    def test_shapley_real_three_dims_sums_to_fusion_minus_empty(self):
        """Shapley 性质：Σ phi_k = v(N) - v(∅) = v(N)（因 v(∅)=0）。"""
        dates = pd.date_range('2025-01-02', periods=4, freq='B')
        a = _make_signal_df(['X', 'Y'], dates)
        b = _make_signal_df(['Y', 'Z'], dates)
        c = _make_signal_df(['Z', 'W'], dates)
        rate = _make_rate_df(['X', 'Y', 'Z', 'W'], dates, rate_value=1.0)
        dim_signals = {'tech': a, 'fund': b, 'flow': c}
        spec = self._make_spec(weights={'tech': 40, 'fund': 30, 'flow': 30})
        spec['min_score'] = 0.0
        items, _, _ = vfh._shapley_real(dim_signals, spec, rate, time_budget_s=8.0)
        # v(N) = fusion sharpe over all 3 dims
        full = vfh._fuse_subset_signals(dim_signals, spec)
        m, _ds = vfh._evaluate(full, rate, spec['holding_days'])
        v_full = float(m.get('sharpe') or 0.0)
        s = sum(it['contrib'] or 0.0 for it in items)
        # Shapley sum = v(N)（容差 1e-6）
        assert abs(s - v_full) < 1e-6

    def test_shapley_real_timeout_returns_none(self):
        """超时预算 0 秒应立即返回 used_fallback=True。"""
        dates = pd.date_range('2025-01-02', periods=2, freq='B')
        sig = _make_signal_df(['A'], dates)
        rate = _make_rate_df(['A'], dates, rate_value=1.0)
        spec = self._make_spec(weights={'tech': 50, 'fund': 50})
        items, used_fb, diag = vfh._shapley_real(
            {'tech': sig, 'fund': sig}, spec, rate, time_budget_s=0.0)
        assert used_fb is True
        assert items is None
        assert diag.get('reason') == 'timeout'

    def test_shapley_real_less_than_two_dims_empty(self):
        """单维度时不计算 Shapley。"""
        dates = pd.date_range('2025-01-02', periods=2, freq='B')
        sig = _make_signal_df(['A'], dates)
        rate = _make_rate_df(['A'], dates, rate_value=1.0)
        spec = self._make_spec(weights={'tech': 100})
        items, used_fb, diag = vfh._shapley_real({'tech': sig}, spec, rate)
        assert items == []
        assert used_fb is False
        assert diag.get('reason') == 'less_than_2_dims'

    def test_ab_steps_follows_shapley_order(self):
        """AB 步进按 Shapley 排序顺序累加。"""
        dates = pd.date_range('2025-01-02', periods=4, freq='B')
        tech = _make_signal_df(['A', 'B'], dates)
        fund = _make_signal_df(['B', 'C'], dates)
        rate = _make_rate_df(['A', 'B', 'C'], dates, rate_value=1.0)
        dim_signals = {'tech': tech, 'fund': fund}
        spec = self._make_spec(weights={'tech': 50, 'fund': 50})
        spec['min_score'] = 0.0
        shapley_items = [
            {'dim': 'fund', 'cn': '基本面', 'contrib': 0.5, 'rank': 1},
            {'dim': 'tech', 'cn': '技术信号', 'contrib': 0.3, 'rank': 2},
        ]
        steps = vfh._ab_steps(dim_signals, shapley_items, spec, rate)
        assert len(steps) == 2
        assert steps[0]['dims'] == ['fund']
        assert steps[1]['dims'] == ['fund', 'tech']
        assert steps[0]['step'] == 1 and steps[1]['step'] == 2
        # signal_count 单调（fund=2*4=8；fund∪tech 也是 3*4=12 for weighted mode 0 threshold）
        assert steps[1]['signal_count'] >= 1

    def test_overlap_jaccard_symmetric(self):
        """Jaccard 矩阵对角=1，对称。"""
        dates = pd.date_range('2025-01-02', periods=3, freq='B')
        a = _make_signal_df(['X', 'Y'], dates)
        b = _make_signal_df(['Y', 'Z'], dates)
        out = vfh._overlap({'tech': a, 'fund': b})
        pairs = {(p['a'], p['b']): p['jaccard'] for p in out['co_occurrence']}
        # 对角 = 1.0
        assert pairs[('tech', 'tech')] == 1.0
        assert pairs[('fund', 'fund')] == 1.0
        # 对称
        assert pairs[('tech', 'fund')] == pairs[('fund', 'tech')]
        # 交=Y×3 dates=3, 并 = |tech ∪ fund| = 6+6-3 = 9 → jaccard=3/9≈0.3333
        assert abs(pairs[('tech', 'fund')] - 1.0 / 3) < 1e-3

    def test_overlap_calendar_aggregates(self):
        """日历按 date 聚合 distinct code 总数 + dims_hit。"""
        dates = ['2025-01-02', '2025-01-03']
        a = pd.DataFrame([{'date': '2025-01-02', 'code': 'X'}, {'date': '2025-01-03', 'code': 'Y'}])
        b = pd.DataFrame([{'date': '2025-01-02', 'code': 'X'}, {'date': '2025-01-02', 'code': 'Z'}])
        out = vfh._overlap({'tech': a, 'fund': b})
        cal = {row['date']: row for row in out['calendar']}
        assert cal['2025-01-02']['signal_count'] == 2  # X, Z
        assert cal['2025-01-02']['dims_hit'] == 2     # 两维都有 2025-01-02
        assert cal['2025-01-03']['signal_count'] == 1  # Y
        assert cal['2025-01-03']['dims_hit'] == 1     # 只 tech 有 2025-01-03

    def test_overlap_empty(self):
        out = vfh._overlap({})
        assert out == {'calendar': [], 'co_occurrence': []}


class TestStage3Integration(AsyncHTTPTestCase):
    """v2 接口端到端：返回非空 shapley/ab_steps/overlap。"""

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

    def test_v2_two_dims_returns_shapley_ab_overlap(self):
        dates = pd.date_range('2025-01-02', periods=5, freq='B')
        tech = _make_signal_df(['A', 'B'], dates)
        fund = _make_signal_df(['B', 'C'], dates)
        rate = _make_rate_df(['A', 'B', 'C'], dates, rate_value=1.0)

        def load_side(key, items, s, e):
            return {'tech': (tech, []), 'fund': (fund, [])}.get(key, (pd.DataFrame(columns=['date', 'code']), []))

        with mock.patch.object(vfh, '_load_dim_signals', side_effect=load_side), \
             mock.patch.object(vfh, '_load_rate_df', return_value=rate):
            code, data = self._post({
                'version': 2, 'mode': 'weighted_score', 'min_score': 0.0,
                'start_date': '2025-01-01', 'end_date': '2025-02-01', 'holding_days': 5,
                'dimensions': {
                    'tech': {'enabled': True, 'weight': 50, 'items': ['x']},
                    'fund': {'enabled': True, 'weight': 50, 'items': ['pe9_lt_30']},
                },
            })
        assert code == 200, data
        # Shapley 非空，包含 contrib + rank
        assert len(data['shapley']) == 2
        for it in data['shapley']:
            assert 'dim' in it and 'contrib' in it and 'rank' in it
        # AB 步进 = 2 步
        assert len(data['ab_steps']) == 2
        assert data['ab_steps'][0]['step'] == 1
        # Overlap calendar 非空（5 个日期）+ co_occurrence 4 对（2x2）
        assert len(data['overlap']['calendar']) == 5
        assert len(data['overlap']['co_occurrence']) == 4

    def test_v2_single_dim_no_shapley(self):
        """单维度时 shapley/ab 仍可返回（≥1 维），但 shapley 走 naive 路径。"""
        dates = pd.date_range('2025-01-02', periods=3, freq='B')
        sig = _make_signal_df(['A'], dates)
        rate = _make_rate_df(['A'], dates, rate_value=1.0)

        with mock.patch.object(vfh, '_load_dim_signals', return_value=(sig, [])), \
             mock.patch.object(vfh, '_load_rate_df', return_value=rate):
            code, data = self._post({
                'version': 2, 'mode': 'weighted_score', 'min_score': 0.0,
                'start_date': '2025-01-01', 'end_date': '2025-02-01', 'holding_days': 5,
                'dimensions': {'tech': {'enabled': True, 'weight': 100, 'items': ['x']}},
            })
        assert code == 200, data
        # 单维 overlap 仍有 1x1 对
        assert len(data['overlap']['co_occurrence']) == 1
        assert data['overlap']['co_occurrence'][0]['jaccard'] == 1.0


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
