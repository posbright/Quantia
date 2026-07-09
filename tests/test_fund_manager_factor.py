# -*- coding: utf-8 -*-
"""manager_factor.py 纯函数单测（基金经理经验弱因子）。"""

import pytest

from quantia.core.fund import manager_factor as mf


def _m(manager, tenure_days, total_aum=100.0, best_return=50.0, fund_count=3, company='华夏基金'):
    return {'manager': manager, 'company': company, 'tenure_days': tenure_days,
            'total_aum': total_aum, 'best_return': best_return, 'fund_count': fund_count}


class TestExperienceLabel:
    def test_senior(self):
        assert mf.experience_label(8.0) == '资深'
        assert mf.experience_label(12.5) == '资深'

    def test_mature(self):
        assert mf.experience_label(4.0) == '成熟'
        assert mf.experience_label(7.99) == '成熟'

    def test_junior(self):
        assert mf.experience_label(2.0) == '新锐'
        assert mf.experience_label(3.9) == '新锐'

    def test_novice(self):
        assert mf.experience_label(1.9) == '新手'
        assert mf.experience_label(0.1) == '新手'

    def test_none(self):
        assert mf.experience_label(None) is None
        assert mf.experience_label('abc') is None


class TestManagerExperience:
    def test_single_manager(self):
        # 4636 天 ≈ 12.7 年 → 资深
        res = mf.manager_experience([_m('王斌', 4636, total_aum=71.94, best_return=364.14, fund_count=5)])
        assert res['manager_count'] == 1
        assert res['names'] == ['王斌']
        assert res['company'] == '华夏基金'
        assert res['max_tenure_years'] == round(4636 / 365.0, 2)
        assert res['avg_tenure_years'] == res['max_tenure_years']
        assert res['experience_label'] == '资深'
        assert res['best_return'] == 364.14
        assert res['max_fund_count'] == 5
        assert res['over_extended'] is False

    def test_multi_manager_team(self):
        res = mf.manager_experience([
            _m('黎海威', 4636, best_return=234.33, fund_count=8),
            _m('徐喻军', 4464, best_return=185.26, fund_count=4),
        ])
        assert res['manager_count'] == 2
        # 团队最大从业年限取 max
        assert res['max_tenure_years'] == round(4636 / 365.0, 2)
        # 平均
        assert res['avg_tenure_years'] == round((4636 / 365.0 + 4464 / 365.0) / 2, 2)
        # 最佳回报取团队最大
        assert res['best_return'] == 234.33
        assert res['max_fund_count'] == 8

    def test_over_extended_flag(self):
        res = mf.manager_experience([_m('张三', 3000, fund_count=20)])
        assert res['over_extended'] is True
        assert res['max_fund_count'] == 20

    def test_not_over_extended_at_threshold_minus_one(self):
        res = mf.manager_experience([_m('李四', 3000, fund_count=14)])
        assert res['over_extended'] is False

    def test_over_extended_at_threshold(self):
        res = mf.manager_experience([_m('王五', 3000, fund_count=15)])
        assert res['over_extended'] is True

    def test_skips_invalid_tenure(self):
        res = mf.manager_experience([
            _m('有效', 3000),
            _m('无从业', None),
            _m('零从业', 0),
            _m('负从业', -5),
        ])
        assert res['manager_count'] == 1
        assert res['names'] == ['有效']

    def test_dedup_same_name(self):
        res = mf.manager_experience([_m('重复', 3000), _m('重复', 3000)])
        assert res['manager_count'] == 1

    def test_empty_returns_none(self):
        assert mf.manager_experience([]) is None
        assert mf.manager_experience(None) is None

    def test_all_invalid_returns_none(self):
        res = mf.manager_experience([_m('a', None), _m('b', 0)])
        assert res is None

    def test_best_return_none_when_all_missing(self):
        res = mf.manager_experience([_m('x', 3000, best_return=None)])
        assert res['best_return'] is None

    def test_fund_count_none_when_all_missing(self):
        res = mf.manager_experience([_m('x', 3000, fund_count=None)])
        assert res['max_fund_count'] is None
        assert res['over_extended'] is False

    def test_ignores_non_dict_items(self):
        res = mf.manager_experience(['not a dict', None, _m('valid', 3000)])
        assert res['manager_count'] == 1
        assert res['names'] == ['valid']

    def test_company_from_first_valid(self):
        res = mf.manager_experience([
            {'manager': '甲', 'tenure_days': 3000, 'company': '嘉实基金'},
            {'manager': '乙', 'tenure_days': 2000, 'company': '易方达基金'},
        ])
        assert res['company'] == '嘉实基金'
