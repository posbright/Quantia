#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""F7 多因子评分 / F11 同类评比 / F13 综合分析 单元测试（纯函数 + handler mock DB）。

禁真实网络/DB：纯计算直接断言；handler 用 mock.patch 打 mdb + pandas.read_sql。
"""
import datetime
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

import quantia.core.fund.scoring as scoring
import quantia.core.fund.labels as labels
import quantia.web.fundPeerCompareHandler as peer
import quantia.web.fundCompositeAnalysisHandler as cah


# ──────────────────────────────────────────────────────────
# F7 scoring 纯函数
# ──────────────────────────────────────────────────────────
class TestScoringMetrics:

    def _ascending_nav(self, n=120, step=0.001):
        # 单调上升 acc_nav：无回撤、正夏普
        return [1.0 + i * step for i in range(n)]

    def test_sharpe_positive_for_uptrend(self):
        s = scoring.compute_sharpe(self._ascending_nav())
        assert s is not None and s > 0

    def test_sharpe_none_when_too_few_samples(self):
        assert scoring.compute_sharpe([1.0, 1.01, 1.02]) is None

    def test_sharpe_none_when_zero_vol(self):
        assert scoring.compute_sharpe([1.0] * 120) is None

    def test_max_drawdown_negative(self):
        nav = [1.0, 1.2, 0.9, 1.1]  # 峰值1.2→0.9 回撤 -0.25
        dd = scoring.compute_max_drawdown(nav)
        assert dd is not None
        assert abs(dd - (-0.25)) < 1e-9

    def test_max_drawdown_zero_for_monotonic(self):
        dd = scoring.compute_max_drawdown([1.0, 1.1, 1.2, 1.3])
        assert dd == 0.0

    def test_calmar_none_without_drawdown(self):
        # 单调上升无回撤 → Calmar None
        assert scoring.compute_calmar(self._ascending_nav()) is None

    def test_rate_5y_none_when_history_short(self):
        dates = pd.date_range('2024-01-01', periods=100, freq='D')
        assert scoring.compute_rate_5y(dates, [1.0 + i * 0.001 for i in range(100)]) is None

    def test_rate_5y_computed_when_5y_history(self):
        dates = pd.date_range('2019-01-01', periods=2000, freq='D')
        nav = [1.0 + i * 0.0005 for i in range(2000)]
        r = scoring.compute_rate_5y(dates, nav)
        assert r is not None and r > 0

    def test_scale_inverted_u_peaks_at_median(self):
        s = pd.Series([0.1, 1.0, 10.0, 100.0, 1000.0])
        out = scoring.scale_inverted_u(s)
        # 倒U：两端（最小0.1 / 最大1000）得分最低，中段得分最高
        assert out.iloc[2] >= out.iloc[0]
        assert out.iloc[2] >= out.iloc[4]
        assert out.idxmin() in (0, 4)

    def test_cross_sectional_rank_range(self):
        r = scoring.cross_sectional_pct_rank(pd.Series([1.0, 2.0, 3.0, 4.0]))
        assert r.min() > 0 and r.max() == 100.0

    def test_main_industry_weighted(self):
        df = pd.DataFrame([
            {'code': '001', 'industry': '银行', 'hold_ratio': 5.0},
            {'code': '001', 'industry': '医药', 'hold_ratio': 3.0},
            {'code': '001', 'industry': '银行', 'hold_ratio': 4.0},  # 银行合计9 > 医药3
            {'code': '002', 'industry': '半导体', 'hold_ratio': 8.0},
        ])
        m = scoring.compute_main_industry(df)
        assert m['001'] == '银行'
        assert m['002'] == '半导体'

    def test_main_industry_ignores_unknown(self):
        # 大量未分类(数据缺口)不应压过真实行业倾向：半导体 13.7% > 未分类 45% 也应判半导体
        df = pd.DataFrame([
            {'code': '020470', 'industry': '未分类', 'hold_ratio': 45.71},
            {'code': '020470', 'industry': '半导体', 'hold_ratio': 13.70},
            {'code': '020470', 'industry': '汽车', 'hold_ratio': 5.94},
        ])
        m = scoring.compute_main_industry(df)
        assert m['020470'] == '半导体'

    def test_main_industry_all_unknown_omitted(self):
        # 全部未分类 → 无已知行业 → 不返回该基金（前端保持空，诚实）
        df = pd.DataFrame([
            {'code': '111', 'industry': '未分类', 'hold_ratio': 60.0},
            {'code': '111', 'industry': None, 'hold_ratio': 10.0},
        ])
        m = scoring.compute_main_industry(df)
        assert '111' not in m


class TestComputeScores:

    def _bucket(self):
        rows = []
        for i in range(6):
            rows.append({
                'code': f'10000{i}', 'fund_type': '股票型',
                'rate_3m': i, 'rate_6m': i * 2, 'rate_1y': i * 3,
                'rate_3y': i * 5, 'rate_ytd': i, 'fee': 0.5 - i * 0.05,
                'scale_yi': 1.0 + i, 'sharpe': i * 0.2, 'calmar': i * 0.1,
                'max_drawdown': -0.1 - i * 0.02, 'rate_5y': i * 8,
                'main_industry': '银行',
            })
        return pd.DataFrame(rows)

    def test_scores_within_bucket_and_ranked(self):
        df = self._bucket()
        out = scoring.compute_scores(df, score_date='2026-06-01')
        assert len(out.index) == 6
        # 最高 rate/sharpe 的 i=5 应 rank_in_type==1
        top = out.sort_values('score', ascending=False).iloc[0]
        assert top['code'] == '100005'
        assert int(out[out['code'] == '100005']['rank_in_type'].iloc[0]) == 1
        # 列齐全 + date 注入
        assert (out['date'] == '2026-06-01').all()
        assert 'excess_1y' in out.columns

    def test_b1_fallback_when_no_risk_metrics(self):
        df = self._bucket().drop(columns=['sharpe', 'calmar'])
        out = scoring.compute_scores(df, score_date='2026-06-01')
        # 无夏普/calmar 仍能打分（B1 兜底），sharpe_score 为 NaN
        assert out['sharpe_score'].isna().all()
        assert out['score'].notna().all()

    def test_money_bucket_no_sharpe(self):
        rows = [{'code': f'20000{i}', 'fund_type': '货币型',
                 'seven_day_annual': 1.5 + i * 0.1, 'million_unit_income': 0.5 + i * 0.05,
                 'fee': 0.1, 'rate_1y': 2.0 + i, 'rate_3y': 6.0}
                for i in range(4)]
        out = scoring.compute_scores(pd.DataFrame(rows), score_date='2026-06-01')
        assert out['sharpe'].isna().all()
        assert out['max_drawdown'].isna().all()
        assert out['score'].notna().all()

    def test_empty_df_returns_schema(self):
        out = scoring.compute_scores(pd.DataFrame(), score_date='2026-06-01')
        assert out.empty
        assert 'score' in out.columns and 'rank_in_type' in out.columns


# ──────────────────────────────────────────────────────────
# labels 共享阈值
# ──────────────────────────────────────────────────────────
class TestLabels:

    def test_tier_label_bands(self):
        assert labels.tier_label(95) == '领先'
        assert labels.tier_label(75) == '较优'
        assert labels.tier_label(50) == '中等'
        assert labels.tier_label(25) == '偏弱'
        assert labels.tier_label(5) == '靠后'
        assert labels.tier_label(None) is None
        assert labels.tier_label(float('nan')) is None

    def test_value_labels_leading(self):
        tags = labels.value_labels({'return': 95, 'drawdown': 90, 'sharpe': 85,
                                    'fee': 80, 'scale': 75})
        assert '同类收益前10%' in tags
        assert any('回撤控制优于同类' in t for t in tags)
        assert '费率低于同类中位' in tags

    def test_concentration_levels(self):
        assert labels.concentration_label(30)[0] == 'dispersed'
        assert labels.concentration_label(50)[0] == 'moderate'
        assert labels.concentration_label(75)[0] == 'concentrated'
        assert labels.concentration_label(None) == (None, None)

    def test_risk_level_money_is_low(self):
        assert labels.risk_level(fund_type='货币型') == '低'

    def test_risk_level_high_for_deep_drawdown(self):
        assert labels.risk_level(max_drawdown=-0.45, concentration=70,
                                 fund_type='股票型') == '高'

    def test_risk_level_equity_without_dd_is_midhigh(self):
        # 权益类无回撤数据 → 至少中高
        assert labels.risk_level(max_drawdown=None, concentration=None,
                                 fund_type='股票型') in ('中高', '高')


# ──────────────────────────────────────────────────────────
# F11 peer compute_peer_dims 纯函数
# ──────────────────────────────────────────────────────────
class TestPeerDims:

    def _bucket(self):
        return pd.DataFrame([
            {'code': '001', 'rate_1y': 30.0, 'fee': 0.1, 'sharpe': 1.5,
             'max_drawdown': -0.1, 'scale_yi': 10.0},
            {'code': '002', 'rate_1y': 20.0, 'fee': 0.3, 'sharpe': 1.0,
             'max_drawdown': -0.2, 'scale_yi': 5.0},
            {'code': '003', 'rate_1y': 10.0, 'fee': 0.5, 'sharpe': 0.5,
             'max_drawdown': -0.4, 'scale_yi': 1.0},
        ])

    def test_top_fund_high_percentiles(self):
        res = peer.compute_peer_dims(self._bucket(), '001')
        p = res['percentiles']
        assert p['return'] == 100.0     # 最高收益
        assert p['sharpe'] == 100.0     # 最高夏普
        assert p['drawdown'] == 100.0   # 回撤最小（-0.1 最优）
        assert p['fee'] > 50            # 费率最低 → 成本分高
        assert res['peer_count'] == 3

    def test_missing_code_returns_none_dims(self):
        res = peer.compute_peer_dims(self._bucket(), '999')
        assert all(d['value'] is None for d in res['dims'])


# ──────────────────────────────────────────────────────────
# F13 build_composite_analysis 纯函数
# ──────────────────────────────────────────────────────────
class TestCompositeAnalysis:

    def _ctx(self):
        return {
            'code': '001', 'name': '基金A', 'fund_type': '股票型',
            'data_date': '2026-05-29',
            'rank': {'rate_1y': 25.0, 'rate_3y': 60.0},
            'score': {'score': 92.0, 'sharpe': 1.6, 'max_drawdown': -0.18,
                      'rate_5y': 110.0, 'excess_1y': 6.0, 'main_industry': '半导体'},
            'profile': {'fund_type_detail': '股票型-普通', 'scale_yi': 12.0,
                        'setup_date': '2018-01-01'},
            'holdings': [
                {'industry': '半导体', 'hold_ratio': 25.0},
                {'industry': '电子', 'hold_ratio': 20.0},
                {'industry': '半导体', 'hold_ratio': 10.0},
            ],
            'peer_percentiles': {'sharpe': 90.0, 'drawdown': 80.0},
        }

    def test_structure_and_no_buysell_words(self):
        out = cah.build_composite_analysis(self._ctx())
        assert out['fund_type'] == '股票型'
        assert out['performance']['sharpe'] == 1.6
        assert out['concentration']['top10_sum'] == 55.0
        assert out['concentration']['level'] == 'moderate'
        # 行业加权：半导体 35 > 电子 20 → 主行业半导体
        assert out['industry']['main_industry'] == '半导体'
        assert out['risk_level'] in ('低', '中', '中高', '高')
        blob = json.dumps(out, ensure_ascii=False)
        for forbidden in ('买入', '卖出', '加仓', '减仓', '建议买'):
            assert forbidden not in blob
        assert out['disclaimer'] == labels.RISK_DISCLAIMER

    def test_performance_texts_include_excess(self):
        out = cah.build_composite_analysis(self._ctx())
        assert any('跑赢对照基线' in t for t in out['performance']['texts'])
        assert any('夏普' in t for t in out['performance']['texts'])

    def test_handles_empty_context(self):
        out = cah.build_composite_analysis({'code': 'x', 'fund_type': '股票型'})
        assert out['concentration']['top10_sum'] is None
        assert out['summary']  # 不报错，给兜底文案


# ──────────────────────────────────────────────────────────
# Handler 端到端（mock DB + read_sql）
# ──────────────────────────────────────────────────────────
def _peer_bucket_df():
    return pd.DataFrame([
        {'code': '001', 'rate_1y': 30.0, 'fee': 0.1, 'sharpe': 1.5,
         'max_drawdown': -0.1, 'scale_yi': 10.0},
        {'code': '002', 'rate_1y': 20.0, 'fee': 0.3, 'sharpe': 1.0,
         'max_drawdown': -0.2, 'scale_yi': 5.0},
    ])


class TestPeerHandler(AsyncHTTPTestCase):
    def get_app(self):
        return Application([(r'/api/fund/peer_compare', peer.FundPeerCompareHandler)])

    def test_peer_compare_ok(self):
        with mock.patch.object(peer.mdb, 'checkTableIsExist', return_value=True), \
             mock.patch.object(peer.mdb, 'executeSqlFetch',
                               return_value=[('基金A', '股票型')]), \
             mock.patch.object(peer.mdb, 'engine', return_value=None), \
             mock.patch.object(peer.pd, 'read_sql', return_value=_peer_bucket_df()):
            resp = self.fetch('/api/fund/peer_compare?code=001')
        assert resp.code == 200
        data = json.loads(resp.body)
        assert data['fund_type'] == '股票型'
        assert len(data['dims']) == 5
        assert data['disclaimer']

    def test_peer_compare_missing_code(self):
        resp = self.fetch('/api/fund/peer_compare')
        assert resp.code == 400


class TestCompositeHandler(AsyncHTTPTestCase):
    def get_app(self):
        return Application([(r'/api/fund/composite_analysis',
                             cah.FundCompositeAnalysisHandler)])

    def test_composite_ok(self):
        def _fetch_side(sql, params=None):
            if 'cn_fund_rank_score' in sql.lower() and 'select `score`' in sql.lower():
                return [(92.0, 1.6, -0.18, 60.0, 110.0, 6.0, '半导体', 1)]
            if 'cn_fund_profile' in sql.lower():
                return [('股票型-普通', 12.0, '2018-01-01', '某公司', '张三',
                         '5星', '价值成长', '长期超额', '沪深300')]
            if 'cn_fund_holding' in sql.lower():
                return [('中芯国际', '688981', '半导体', 25.0, '2026Q1'),
                        ('立讯精密', '002475', '电子', 20.0, '2026Q1')]
            # rank meta
            return [('基金A', '股票型', '2026-05-29', 25.0, 60.0)]

        with mock.patch.object(cah.mdb, 'checkTableIsExist', return_value=True), \
             mock.patch.object(cah.mdb, 'executeSqlFetch', side_effect=_fetch_side), \
             mock.patch.object(cah.mdb, 'engine', return_value=None), \
             mock.patch.object(cah.pd, 'read_sql', return_value=_peer_bucket_df()):
            resp = self.fetch('/api/fund/composite_analysis?code=001')
        assert resp.code == 200
        data = json.loads(resp.body)
        assert data['code'] == '001'
        assert data['risk_level'] in ('低', '中', '中高', '高')
        assert 'performance' in data and 'concentration' in data
        # F9 扩展：基金画像 + 前十大重仓股明细
        assert data['profile']['company'] == '某公司'
        assert data['profile']['benchmark'] == '沪深300'
        assert data['holdings']['quarter'] == '2026Q1'
        assert len(data['holdings']['top']) == 2
        assert data['holdings']['top'][0]['name'] == '中芯国际'
        assert data['holdings']['top'][0]['stock_code'] == '688981'

    def test_composite_missing_code(self):
        resp = self.fetch('/api/fund/composite_analysis')
        assert resp.code == 400


# ──────────────────────────────────────────────────────────
# F7 job 装配编排（build_score_df，mock DB 读）
# ──────────────────────────────────────────────────────────
import quantia.job.analysis_fund_score_job as job


class TestBuildScoreDf:

    def _rank_df(self):
        rows = []
        for i in range(4):
            rows.append({'code': f'00100{i}', 'fund_type': '股票型',
                         'rate_3m': i, 'rate_6m': i * 2, 'rate_1y': i * 3,
                         'rate_3y': i * 5, 'rate_ytd': i, 'fee': 0.5 - i * 0.05,
                         'seven_day_annual': None, 'million_unit_income': None})
        return pd.DataFrame(rows), '2026-05-29'

    def test_assembles_and_aligns_columns(self):
        rank_df, snap = self._rank_df()
        risk_df = pd.DataFrame([
            {'code': '001000', 'sharpe': 1.2, 'calmar': 0.8,
             'max_drawdown': -0.15, 'rate_5y': 80.0},
            {'code': '001001', 'sharpe': 0.9, 'calmar': 0.5,
             'max_drawdown': -0.25, 'rate_5y': 60.0},
        ])
        with mock.patch.object(job, '_load_rank_snapshot', return_value=(rank_df, snap)), \
             mock.patch.object(job, '_load_scale_map',
                               return_value={'001000': 5.0, '001001': 50.0}), \
             mock.patch.object(job, '_load_main_industry_map',
                               return_value={'001000': '半导体'}), \
             mock.patch.object(job, '_build_risk_metrics', return_value=risk_df):
            scored, eff = job.build_score_df()
        # 列序与表结构严格一致
        assert list(scored.columns) == job._SCORE_COLS
        assert eff == datetime.date(2026, 5, 29)
        assert len(scored.index) == 4
        # 有夏普的基金 sharpe 落库
        row = scored[scored['code'] == '001000'].iloc[0]
        assert abs(float(row['sharpe']) - 1.2) < 1e-9
        assert row['main_industry'] == '半导体'
        # 无夏普的基金（002/003）sharpe 为空但 score 有效
        miss = scored[scored['code'] == '001003'].iloc[0]
        assert pd.isna(miss['sharpe'])
        assert pd.notna(miss['score'])
        # 无 inf
        import numpy as _np
        numeric = scored.select_dtypes(include=[_np.number])
        assert not _np.isinf(numeric.to_numpy(dtype='float64', na_value=_np.nan)).any()

    def test_empty_rank_returns_schema(self):
        with mock.patch.object(job, '_load_rank_snapshot',
                               return_value=(pd.DataFrame(), None)):
            scored, eff = job.build_score_df()
        assert list(scored.columns) == job._SCORE_COLS
        assert scored.empty

    def test_no_risk_metrics_falls_back_to_b1(self):
        rank_df, snap = self._rank_df()
        with mock.patch.object(job, '_load_rank_snapshot', return_value=(rank_df, snap)), \
             mock.patch.object(job, '_load_scale_map', return_value={}), \
             mock.patch.object(job, '_load_main_industry_map', return_value={}), \
             mock.patch.object(job, '_build_risk_metrics',
                               return_value=pd.DataFrame(
                                   columns=['code', 'sharpe', 'calmar',
                                            'max_drawdown', 'rate_5y'])):
            scored, eff = job.build_score_df()
        assert scored['sharpe'].isna().all()
        assert scored['score'].notna().all()
        assert list(scored.columns) == job._SCORE_COLS


if __name__ == '__main__':
    pytest.main([__file__, '-q'])
