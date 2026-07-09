# -*- coding: utf-8 -*-
"""style_drift.py 纯函数单测（风格暴露 + 前向兼容漂移）。"""

import math

import pytest

from quantia.core.fund import style_drift as sd


def _h(industry, ratio):
    return {'industry': industry, 'hold_ratio': ratio}


class TestIndustryExposure:
    def test_basic_aggregation_and_sort(self):
        holdings = [
            _h('电子', 5.0), _h('电子', 3.0),
            _h('医药', 4.0), _h('食品饮料', 2.0),
        ]
        exp = sd.industry_exposure(holdings)
        assert exp['disclosed_ratio'] == 14.0
        assert exp['classified_ratio'] == 14.0
        assert exp['unclassified_weight'] == 0.0
        # 电子 8, 医药 4, 食品饮料 2 → 降序
        inds = exp['industries']
        assert inds[0]['industry'] == '电子'
        assert inds[0]['weight'] == 8.0
        assert inds[1]['industry'] == '医药'
        assert exp['n_industries'] == 3
        # HHI = (8/14)^2+(4/14)^2+(2/14)^2
        hhi = (8 / 14) ** 2 + (4 / 14) ** 2 + (2 / 14) ** 2
        assert abs(exp['hhi'] - round(hhi, 4)) < 1e-6
        assert abs(exp['top3_share'] - 1.0) < 1e-6

    def test_unclassified_bucketed_and_excluded_from_hhi(self):
        holdings = [
            _h('电子', 6.0), _h('医药', 4.0),
            _h('未分类', 5.0), _h(None, 3.0), _h('', 2.0),
        ]
        exp = sd.industry_exposure(holdings)
        # 未分类 = 5+3+2 = 10
        assert exp['unclassified_weight'] == 10.0
        assert exp['disclosed_ratio'] == 20.0
        assert exp['classified_ratio'] == 10.0
        assert abs(exp['unclassified_ratio'] - 0.5) < 1e-6
        # 未分类 不进 industries 列表
        assert all(it['industry'] != sd.UNCLASSIFIED for it in exp['industries'])
        # HHI 仅对已分类：(6/10)^2+(4/10)^2 = 0.52
        assert abs(exp['hhi'] - 0.52) < 1e-6
        assert exp['n_industries'] == 2

    def test_empty_holdings(self):
        exp = sd.industry_exposure([])
        assert exp['industries'] == []
        assert exp['hhi'] is None
        assert exp['top3_share'] is None
        assert exp['disclosed_ratio'] == 0.0
        assert exp['unclassified_ratio'] is None
        assert exp['n_industries'] == 0

    def test_only_unclassified(self):
        exp = sd.industry_exposure([_h('未分类', 8.0), _h(None, 2.0)])
        assert exp['unclassified_weight'] == 10.0
        assert exp['classified_ratio'] == 0.0
        assert exp['hhi'] is None
        assert exp['industries'] == []
        assert exp['unclassified_ratio'] == 1.0

    def test_invalid_ratios_skipped(self):
        holdings = [
            _h('电子', 5.0), _h('医药', None), _h('食品', 'x'),
            _h('军工', -1.0), _h('电力', float('nan')), _h('计算机', 0.0),
        ]
        exp = sd.industry_exposure(holdings)
        assert exp['disclosed_ratio'] == 5.0
        assert exp['n_industries'] == 1
        assert exp['industries'][0]['industry'] == '电子'

    def test_top3_share_with_more_than_three(self):
        holdings = [_h(f'行业{i}', 10.0 - i) for i in range(5)]  # 10,9,8,7,6
        exp = sd.industry_exposure(holdings)
        total = 10 + 9 + 8 + 7 + 6
        assert abs(exp['top3_share'] - (10 + 9 + 8) / total) < 1e-6


class TestConcentrationLabel:
    def test_high(self):
        assert sd.concentration_label(0.6) == '高度集中'
        assert sd.concentration_label(0.5) == '高度集中'

    def test_mid(self):
        assert sd.concentration_label(0.4) == '适度集中'
        assert sd.concentration_label(0.3) == '适度集中'

    def test_low(self):
        assert sd.concentration_label(0.2) == '行业分散'

    def test_none(self):
        assert sd.concentration_label(None) is None
        assert sd.concentration_label(float('nan')) is None


class TestStyleDrift:
    def test_no_drift_identical(self):
        holdings = [_h('电子', 6.0), _h('医药', 4.0)]
        e1 = sd.industry_exposure(holdings)
        e2 = sd.industry_exposure(holdings)
        d = sd.style_drift(e1, e2)
        assert d is not None
        assert d['drift_score'] == 0.0
        assert d['drift_label'] == '风格稳定'

    def test_full_rotation(self):
        e1 = sd.industry_exposure([_h('电子', 10.0)])
        e2 = sd.industry_exposure([_h('医药', 10.0)])
        d = sd.style_drift(e1, e2)
        # 电子 1→0, 医药 0→1 → L1=2 → /2*100 = 100
        assert d['drift_score'] == 100.0
        assert d['drift_label'] == '显著漂移'
        # top change magnitude 1.0
        assert abs(abs(d['top_changes'][0]['delta']) - 1.0) < 1e-6

    def test_partial_rotation(self):
        # prev: 电子0.5 医药0.5 ; curr: 电子0.25 医药0.75
        e1 = sd.industry_exposure([_h('电子', 5.0), _h('医药', 5.0)])
        e2 = sd.industry_exposure([_h('电子', 2.5), _h('医药', 7.5)])
        d = sd.style_drift(e1, e2)
        # L1 = |0.25-0.5|+|0.75-0.5| = 0.5 → /2*100 = 25
        assert abs(d['drift_score'] - 25.0) < 1e-6
        assert d['drift_label'] == '中等换仓'

    def test_none_when_no_classified(self):
        e1 = sd.industry_exposure([_h('未分类', 10.0)])
        e2 = sd.industry_exposure([_h('电子', 10.0)])
        assert sd.style_drift(e1, e2) is None
        assert sd.style_drift(e2, e1) is None

    def test_top_changes_sorted_by_magnitude(self):
        e1 = sd.industry_exposure([_h('电子', 5.0), _h('医药', 3.0), _h('食品', 2.0)])
        e2 = sd.industry_exposure([_h('电子', 2.0), _h('医药', 3.0), _h('食品', 5.0)])
        d = sd.style_drift(e1, e2)
        deltas = [abs(c['delta']) for c in d['top_changes']]
        assert deltas == sorted(deltas, reverse=True)


class TestDriftLabel:
    def test_bands(self):
        assert sd.drift_label(60) == '显著漂移'
        assert sd.drift_label(50) == '显著漂移'
        assert sd.drift_label(30) == '中等换仓'
        assert sd.drift_label(25) == '中等换仓'
        assert sd.drift_label(10) == '风格稳定'

    def test_none(self):
        assert sd.drift_label(None) is None
        assert sd.drift_label(float('inf')) is None
