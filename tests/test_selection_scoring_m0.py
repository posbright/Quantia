#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M0 单测：综合选股纯计算核心（selection_scoring）。

全部使用合成 DataFrame / Series，不触碰 DB / 网络。验证标准化原语、绝对质量分、
以及有效性验证原语（IC / 分层 / 单调性）的正确性。
"""
import unittest

import numpy as np
import pandas as pd

from quantia.core import selection_scoring as sc


class TestPrimitives(unittest.TestCase):

    def test_directionalize_low_negates(self):
        s = pd.Series([1.0, 2.0, 3.0])
        pd.testing.assert_series_equal(sc.directionalize(s, 'low'), -s)
        pd.testing.assert_series_equal(sc.directionalize(s, 'high'), s)

    def test_winsorize_clips_extremes(self):
        s = pd.Series([1, 2, 3, 4, 1000.0])
        out = sc.winsorize(s, 0.0, 0.8)
        self.assertLess(out.max(), 1000.0)
        self.assertLessEqual(out.max(), s.quantile(0.8))

    def test_winsorize_too_few_values(self):
        s = pd.Series([5.0, np.nan])
        out = sc.winsorize(s)
        self.assertTrue(np.isnan(out.iloc[1]))
        self.assertEqual(out.iloc[0], 5.0)

    def test_robust_z_median_centered(self):
        s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        z = sc.robust_z(s)
        # 中位数处 z=0
        self.assertAlmostEqual(z.iloc[2], 0.0, places=6)
        # 单调递增
        self.assertTrue((z.diff().dropna() > 0).all())

    def test_robust_z_constant_column(self):
        s = pd.Series([7.0, 7.0, 7.0, np.nan])
        z = sc.robust_z(s)
        self.assertEqual(z.iloc[0], 0.0)
        self.assertTrue(np.isnan(z.iloc[3]))

    def test_logistic_range_and_monotonic(self):
        z = pd.Series([-100.0, -1.0, 0.0, 1.0, 100.0])
        out = sc.logistic(z)
        self.assertTrue(((out > 0) & (out < 1)).all())
        self.assertAlmostEqual(out.iloc[2], 0.5, places=6)
        self.assertTrue((out.diff().dropna() > 0).all())

    def test_percentile_rank(self):
        s = pd.Series([10.0, 20.0, 30.0, 40.0])
        out = sc.percentile_rank(s)
        self.assertAlmostEqual(out.iloc[-1], 1.0, places=6)
        self.assertTrue((out.diff().dropna() > 0).all())


class TestQualityScore(unittest.TestCase):

    def _make_df(self, n=200, seed=0):
        rng = np.random.default_rng(seed)
        return pd.DataFrame({
            'roe_weight': rng.normal(10, 5, n),
            'jroa': rng.normal(5, 2, n),
            'netprofit_yoy_ratio': rng.normal(15, 20, n),
            'toi_yoy_ratio': rng.normal(10, 15, n),
            'pe9': np.abs(rng.normal(30, 15, n)) + 1,
            'pbnewmrq': np.abs(rng.normal(3, 1.5, n)) + 0.1,
            'debt_asset_ratio': rng.uniform(10, 80, n),
            'current_ratio': rng.uniform(0.5, 3, n),
            'allcorp_ratio': rng.uniform(0, 60, n),
            'volume_ratio': rng.uniform(0.5, 3, n),
        })

    def test_dimension_q_in_unit_range(self):
        df = self._make_df()
        for dim in ('profitability', 'growth', 'valuation', 'health'):
            q = sc.compute_dimension_q(df, dim)
            self.assertIsNotNone(q)
            self.assertTrue(((q >= 0) & (q <= 1)).all())

    def test_dimension_q_missing_returns_none(self):
        df = pd.DataFrame({'unrelated': [1.0, 2.0, 3.0]})
        self.assertIsNone(sc.compute_dimension_q(df, 'profitability'))
        self.assertIsNone(sc.compute_dimension_q(df, 'technical'))

    def test_quality_score_range_and_reweight(self):
        df = self._make_df()
        q, dims = sc.compute_quality_score(df)
        self.assertTrue(((q >= 0) & (q <= 100)).all())
        # 技术面/情绪部分缺失 → 仅在现有维度上重归一，不应抛错
        self.assertIn('profitability', dims)
        self.assertNotIn('technical', dims)

    def test_quality_score_all_missing(self):
        df = pd.DataFrame({'foo': [1.0, 2.0]})
        q, dims = sc.compute_quality_score(df)
        self.assertTrue(q.isna().all())
        self.assertEqual(dims, {})

    def test_resolve_weight_template_m1(self):
        weights = sc.resolve_weight_template('m1_selection_pool')
        self.assertAlmostEqual(sum(weights.values()), 1.0, places=6)
        self.assertGreater(weights['profitability'], sc.DEFAULT_WEIGHTS['profitability'])
        self.assertLess(weights['technical'], sc.DEFAULT_WEIGHTS['technical'])


class TestValidationPrimitives(unittest.TestCase):

    def test_spearman_ic_perfect_positive(self):
        f = pd.Series([1, 2, 3, 4, 5, 6.0])
        r = pd.Series([2, 4, 6, 8, 10, 12.0])
        self.assertAlmostEqual(sc.spearman_ic(f, r), 1.0, places=6)

    def test_spearman_ic_perfect_negative(self):
        f = pd.Series([1, 2, 3, 4, 5, 6.0])
        r = pd.Series([6, 5, 4, 3, 2, 1.0])
        self.assertAlmostEqual(sc.spearman_ic(f, r), -1.0, places=6)

    def test_spearman_ic_too_few(self):
        self.assertTrue(np.isnan(sc.spearman_ic(pd.Series([1, 2.0]), pd.Series([1, 2.0]))))

    def test_spearman_ic_constant(self):
        f = pd.Series([1, 1, 1, 1, 1, 1.0])
        r = pd.Series([1, 2, 3, 4, 5, 6.0])
        self.assertTrue(np.isnan(sc.spearman_ic(f, r)))

    def test_ic_summary(self):
        out = sc.ic_summary([0.1, 0.2, -0.05, 0.15, 0.1])
        self.assertEqual(out['n'], 5)
        self.assertAlmostEqual(out['ic_mean'], 0.1, places=6)
        self.assertGreater(out['ic_win_rate'], 0.5)
        self.assertTrue(np.isfinite(out['ir']))

    def test_ic_summary_empty(self):
        out = sc.ic_summary([np.nan, np.nan])
        self.assertEqual(out['n'], 0)
        self.assertTrue(np.isnan(out['ic_mean']))

    def test_quantile_groups(self):
        s = pd.Series(np.arange(100.0))
        g = sc.quantile_groups(s, 5)
        self.assertEqual(set(g.dropna().unique()), {0.0, 1.0, 2.0, 3.0, 4.0})
        # 最大值落最高组
        self.assertEqual(g.iloc[-1], 4.0)
        self.assertEqual(g.iloc[0], 0.0)

    def test_quantile_groups_insufficient(self):
        g = sc.quantile_groups(pd.Series([1.0, 2.0]), 5)
        self.assertTrue(g.isna().all())

    def test_layered_returns_monotonic(self):
        # 分数越高未来收益越高
        scores = pd.Series(np.arange(100.0))
        rets = pd.Series(np.arange(100.0) * 0.001)
        layer = sc.layered_returns(scores, rets, 5)
        self.assertEqual(len(layer), 5)
        self.assertGreater(layer[4], layer[0])

    def test_monotonicity_perfect(self):
        self.assertAlmostEqual(sc.monotonicity({0: 0.0, 1: 0.1, 2: 0.2, 3: 0.3, 4: 0.4}), 1.0, places=6)

    def test_monotonicity_reversed(self):
        self.assertAlmostEqual(sc.monotonicity({0: 0.4, 1: 0.3, 2: 0.2, 3: 0.1, 4: 0.0}), -1.0, places=6)

    def test_monotonicity_degenerate(self):
        self.assertTrue(np.isnan(sc.monotonicity({0: 0.1})))
        self.assertTrue(np.isnan(sc.monotonicity({0: 0.1, 1: 0.1})))


class TestM2DailyBuilder(unittest.TestCase):

    def test_build_daily_selection_scores_basic(self):
        df = pd.DataFrame({
            'date': pd.to_datetime(['2026-06-01', '2026-06-01', '2026-06-01']),
            'code': ['000001', '000002', '000003'],
            'name': ['A', 'B', 'C'],
            'industry': ['银行', '银行', '电池'],
            'roe_weight': [10.0, 5.0, 15.0],
            'jroa': [2.0, 1.0, 3.0],
            'netprofit_yoy_ratio': [8.0, 1.0, 12.0],
            'toi_yoy_ratio': [6.0, 2.0, 10.0],
            'pe9': [8.0, 20.0, 25.0],
            'pbnewmrq': [1.2, 2.0, 3.0],
            'debt_asset_ratio': [70.0, 85.0, 45.0],
            'current_ratio': [1.2, 0.8, 2.1],
            'allcorp_ratio': [20.0, 8.0, 30.0],
            'volume_ratio': [1.1, 0.9, 1.5],
        })

        out = sc.build_daily_selection_scores(df)
        self.assertEqual(len(out), 3)
        self.assertTrue({'total_score', 'quality_score', 'industry_score', 'rating'}.issubset(out.columns))
        self.assertTrue(((out['total_score'] >= 0) & (out['total_score'] <= 100)).all())
        self.assertTrue(((out['quality_score'] >= 0) & (out['quality_score'] <= 100)).all())
        self.assertTrue(((out['industry_rank'] >= 1) & (out['industry_rank'] <= out['industry_total'])).all())

    def test_build_daily_selection_scores_uses_latest_date(self):
        df = pd.DataFrame({
            'date': pd.to_datetime(['2026-05-31', '2026-06-01']),
            'code': ['000001', '000001'],
            'industry': ['银行', '银行'],
            'roe_weight': [1.0, 2.0],
            'jroa': [1.0, 2.0],
        })
        out = sc.build_daily_selection_scores(df)
        self.assertEqual(len(out), 1)
        self.assertEqual(str(out.iloc[0]['date']), '2026-06-01')

    def test_build_daily_selection_scores_requires_columns(self):
        with self.assertRaises(ValueError):
            sc.build_daily_selection_scores(pd.DataFrame({'code': ['000001']}))
        with self.assertRaises(ValueError):
            sc.build_daily_selection_scores(pd.DataFrame({'date': ['2026-06-01']}))

    def test_apply_ema_and_rank_change(self):
        cur = pd.DataFrame({
            'date': [pd.to_datetime('2026-06-02').date(), pd.to_datetime('2026-06-02').date()],
            'code': ['000001', '000002'],
            'industry': ['银行', '银行'],
            'total_score_raw': [0.0, 100.0],
            'total_score': [0.0, 100.0],
            'industry_rank': [2, 1],
            'industry_total': [2, 2],
        })
        prev = pd.DataFrame({
            'code': ['000001', '000002'],
            'industry': ['银行', '银行'],
            'total_score': [90.0, 50.0],
            'industry_rank': [1, 2],
        })

        out = sc.apply_ema_and_rank_change(cur, prev_scores=prev, ema_span=5)
        # alpha=2/(5+1)=1/3, code1: 1/3*0+2/3*90=60
        self.assertAlmostEqual(float(out.loc[out['code'] == '000001', 'total_score'].iloc[0]), 60.0, places=6)
        # code2: 1/3*100+2/3*50=66.6667
        self.assertAlmostEqual(float(out.loc[out['code'] == '000002', 'total_score'].iloc[0]), 66.6666667, places=5)

        # 平滑后 code2 反超：code1 排名 2，code2 排名 1。
        # rank_change=prev-current: code1=1-2=-1, code2=2-1=+1
        r1 = int(out.loc[out['code'] == '000001', 'rank_change_1d'].iloc[0])
        r2 = int(out.loc[out['code'] == '000002', 'rank_change_1d'].iloc[0])
        self.assertEqual(r1, -1)
        self.assertEqual(r2, 1)

    def test_apply_ema_rank_change_no_prev_defaults_zero(self):
        cur = pd.DataFrame({
            'date': [pd.to_datetime('2026-06-02').date()],
            'code': ['000001'],
            'industry': ['银行'],
            'total_score_raw': [66.0],
            'total_score': [66.0],
            'industry_rank': [1],
            'industry_total': [1],
        })
        out = sc.apply_ema_and_rank_change(cur, prev_scores=pd.DataFrame(), ema_span=5)
        self.assertAlmostEqual(float(out['total_score'].iloc[0]), 66.0, places=6)
        self.assertEqual(int(out['rank_change_1d'].iloc[0]), 0)


if __name__ == '__main__':
    unittest.main()
