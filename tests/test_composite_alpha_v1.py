#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""composite_alpha_v1 截面打分模块单元测试（纯计算，无 DB）。"""

import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from quantia.core.strategy.composite_alpha_v1 import (
    compute_composite_scores,
    select_candidates,
    DEFAULT_WEIGHTS,
    DIMENSION_FACTORS,
)


def _make_cross_section(n=30, seed=1, with_chip=True, with_flow=True, with_tech=True):
    rng = np.random.RandomState(seed)
    data = {
        'code': [f'{600000 + i:06d}' for i in range(n)],
        'roe_weight': rng.uniform(2, 30, n),
        'sale_gpr': rng.uniform(10, 60, n),
        'sale_npr': rng.uniform(2, 30, n),
        'netprofit_growthrate_3y': rng.uniform(-20, 40, n),
        'income_growthrate_3y': rng.uniform(-10, 35, n),
        'debt_asset_ratio': rng.uniform(20, 80, n),
    }
    if with_tech:
        data['atr_pct'] = rng.uniform(1, 12, n)
        data['ma20_slope'] = rng.uniform(-5, 8, n)
        data['mom_20'] = rng.uniform(-15, 25, n)
    if with_chip:
        data['winner_rate'] = rng.uniform(10, 95, n)
        data['concentration_90'] = rng.uniform(5, 40, n)
    if with_flow:
        data['main_net_inflow'] = rng.uniform(-5e7, 5e7, n)
        data['low_funds_inflow'] = rng.randint(0, 2, n).astype(float)
    return pd.DataFrame(data)


class TestCompositeScores:
    def test_all_dims_available(self):
        df = _make_cross_section()
        scores = compute_composite_scores(df)
        assert 'composite_score' in scores.columns
        assert scores['composite_score'].notna().all()
        assert (scores['composite_score'] >= 0).all() and (scores['composite_score'] <= 100).all()
        # 全维度可用
        assert set(scores['available_dims'].iloc[0].split(',')) == {'fund', 'tech', 'chip', 'flow'}

    def test_degrade_when_chip_flow_missing(self):
        """筹码/资金流缺失时应降级：available_dims 不含 chip/flow，仍产出有效分。"""
        df = _make_cross_section(with_chip=False, with_flow=False)
        scores = compute_composite_scores(df)
        dims = set(scores['available_dims'].iloc[0].split(','))
        assert dims == {'fund', 'tech'}
        assert scores['composite_score'].notna().all()
        assert scores['chip_score'].isna().all()
        assert scores['flow_score'].isna().all()

    def test_weight_renormalization(self):
        """降级后权重在可用维度上重归一：只留 fund 时，composite 应等于 fund_score。"""
        df = _make_cross_section(with_tech=False, with_chip=False, with_flow=False)
        scores = compute_composite_scores(df)
        assert scores['available_dims'].iloc[0] == 'fund'
        # 只有 fund 维度 → composite == fund_score
        np.testing.assert_allclose(
            scores['composite_score'].values,
            scores['fund_score'].values,
            rtol=1e-6, atol=1e-6,
        )

    def test_scores_same_scale_0_100(self):
        """所有维度分与综合分都在 0–100 同量纲（修复量纲 Bug 的核心保证）。"""
        df = _make_cross_section()
        scores = compute_composite_scores(df)
        for col in ('fund_score', 'tech_score', 'chip_score', 'flow_score', 'composite_score'):
            s = scores[col].dropna()
            assert (s >= 0).all() and (s <= 100).all()

    def test_higher_fundamentals_rank_higher(self):
        """基本面显著更优的股票，其 fund_score 应更高（方向正确性）。"""
        df = _make_cross_section(n=20, seed=3, with_tech=False, with_chip=False, with_flow=False)
        # 人为把第0只做成基本面最优，最后一只最差
        df.loc[0, ['roe_weight', 'sale_gpr', 'sale_npr',
                   'netprofit_growthrate_3y', 'income_growthrate_3y']] = [35, 70, 35, 50, 45]
        df.loc[0, 'debt_asset_ratio'] = 15
        df.loc[df.index[-1], ['roe_weight', 'sale_gpr', 'sale_npr',
                              'netprofit_growthrate_3y', 'income_growthrate_3y']] = [1, 5, 1, -30, -20]
        df.loc[df.index[-1], 'debt_asset_ratio'] = 90
        scores = compute_composite_scores(df)
        assert scores['fund_score'].iloc[0] > scores['fund_score'].iloc[-1]

    def test_empty_all_dims_missing(self):
        """完全无可用因子列时不崩溃，composite 为 NaN。"""
        df = pd.DataFrame({'code': ['600000', '600001'], 'irrelevant': [1, 2]})
        scores = compute_composite_scores(df)
        assert scores['composite_score'].isna().all()

    def test_factor_weights_affect_score(self):
        """IC 加权：给某因子极高权重时，维度分应主要由该因子驱动。"""
        n = 25
        rng = np.random.RandomState(5)
        df = pd.DataFrame({
            'code': [f'{600000 + i:06d}' for i in range(n)],
            'roe_weight': rng.uniform(2, 30, n),
            'sale_gpr': rng.uniform(10, 60, n),
            'debt_asset_ratio': rng.uniform(20, 80, n),
        })
        dims = {'fund': [('roe_weight', 'high'), ('sale_gpr', 'high'), ('debt_asset_ratio', 'low')]}
        # 仅给 roe_weight 权重 → fund_score 排序应与 roe 排序高度一致
        fw = {'roe_weight': 1.0, 'sale_gpr': 0.0, 'debt_asset_ratio': 0.0}
        s = compute_composite_scores(df, weights={'fund': 1.0},
                                     dimension_factors=dims, factor_weights=fw)
        # roe 最大的股票 fund_score 应为最高
        top_roe_idx = df['roe_weight'].idxmax()
        assert s['fund_score'].idxmax() == top_roe_idx

    def test_value_dimension_low_pe_scores_higher(self):
        """估值维度：低 PE/PB（便宜）应得更高分（方向 low）。"""
        n = 20
        df = pd.DataFrame({
            'code': [f'{600000 + i:06d}' for i in range(n)],
            'pe_proxy': np.linspace(5, 100, n),   # 递增：越后越贵
            'pb_proxy': np.linspace(0.5, 8, n),
        })
        s = compute_composite_scores(df, weights={'value': 1.0})
        # 第0只(最便宜) value_score 应高于最后一只(最贵)
        assert s['value_score'].iloc[0] > s['value_score'].iloc[-1]


class TestSelectCandidates:
    def test_dual_gate_selection(self):
        df = _make_cross_section(n=40, seed=7)
        picked = select_candidates(df, quality_gate=45, trade_gate=45, top_n=10)
        assert len(picked) <= 10
        if not picked.empty:
            assert (picked['fund_score'] >= 45).all()
            assert (picked['composite_score'] >= 45).all()
            # 结果按综合分降序
            assert picked['composite_score'].is_monotonic_decreasing

    def test_high_gate_returns_empty(self):
        """极高门槛允许当日不出手（返回空表，不报错）。"""
        df = _make_cross_section(n=20, seed=9)
        picked = select_candidates(df, quality_gate=100.0, trade_gate=100.0, top_n=10)
        assert picked.empty

    def test_quality_gate_skipped_when_fund_missing(self):
        """基本面维度整体缺失（长周期早期降级）时，质量门槛跳过，仍可按交易门槛出手。"""
        df = _make_cross_section(n=25, seed=11)
        # 移除全部基本面列
        for col, _ in DIMENSION_FACTORS['fund']:
            if col in df.columns:
                df = df.drop(columns=[col])
        picked = select_candidates(df, quality_gate=60, trade_gate=40, top_n=5)
        # fund 缺失 → 不因质量门槛全部淘汰
        assert len(picked) >= 1
