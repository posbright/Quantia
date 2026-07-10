#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T3 估值分位查询单一事实源单测：benchmark 映射 + 缓存 + 空值容忍。

只用 mock 打 mdb / benchmark_map，不打真实 DB（对齐 tests 约定）。
同时验证 analysis_fund_pick_job._compute_timing 已纳入 T3（与 Handler 口径一致）。
"""
import datetime
import unittest
from unittest import mock

from quantia.core.fund import valuation_lookup as vl


class TestIndexCodeForFund(unittest.TestCase):
    def test_no_table(self):
        with mock.patch.object(vl.mdb, 'checkTableIsExist', return_value=False):
            self.assertIsNone(vl.index_code_for_fund('000001'))

    def test_empty_code(self):
        self.assertIsNone(vl.index_code_for_fund(''))
        self.assertIsNone(vl.index_code_for_fund(None))

    def test_no_profile_row(self):
        with mock.patch.object(vl.mdb, 'checkTableIsExist', return_value=True), \
                mock.patch.object(vl.mdb, 'executeSqlFetch', return_value=()):
            self.assertIsNone(vl.index_code_for_fund('000001'))

    def test_null_benchmark(self):
        with mock.patch.object(vl.mdb, 'checkTableIsExist', return_value=True), \
                mock.patch.object(vl.mdb, 'executeSqlFetch', return_value=((None,),)):
            self.assertIsNone(vl.index_code_for_fund('000001'))

    def test_maps_benchmark(self):
        with mock.patch.object(vl.mdb, 'checkTableIsExist', return_value=True), \
                mock.patch.object(vl.mdb, 'executeSqlFetch',
                                  return_value=(('沪深300指数收益率*95%',),)), \
                mock.patch.object(vl.benchmark_map, 'map_benchmark_to_index',
                                  return_value='000300') as m:
            self.assertEqual(vl.index_code_for_fund('000001'), '000300')
            m.assert_called_once()

    def test_unmappable_benchmark(self):
        with mock.patch.object(vl.mdb, 'checkTableIsExist', return_value=True), \
                mock.patch.object(vl.mdb, 'executeSqlFetch',
                                  return_value=(('某自定义基准',),)), \
                mock.patch.object(vl.benchmark_map, 'map_benchmark_to_index',
                                  return_value=None):
            self.assertIsNone(vl.index_code_for_fund('000001'))


class TestValuationScoreForIndex(unittest.TestCase):
    def test_no_index(self):
        self.assertIsNone(vl.valuation_score_for_index(None))

    def test_no_table(self):
        with mock.patch.object(vl.mdb, 'checkTableIsExist', return_value=False):
            self.assertIsNone(vl.valuation_score_for_index('000300'))

    def test_no_rows(self):
        with mock.patch.object(vl.mdb, 'checkTableIsExist', return_value=True), \
                mock.patch.object(vl.mdb, 'executeSqlFetch', return_value=()):
            self.assertIsNone(vl.valuation_score_for_index('000300'))

    def test_too_few_samples(self):
        with mock.patch.object(vl.mdb, 'checkTableIsExist', return_value=True), \
                mock.patch.object(vl.mdb, 'executeSqlFetch', return_value=((12.0,),)):
            self.assertIsNone(vl.valuation_score_for_index('000300'))

    def test_filters_nonpositive_pe(self):
        # 负/零/None PE 被剔除，剩余不足 2 个 → None
        with mock.patch.object(vl.mdb, 'checkTableIsExist', return_value=True), \
                mock.patch.object(vl.mdb, 'executeSqlFetch',
                                  return_value=((0.0,), (-3.0,), (None,), (15.0,))):
            self.assertIsNone(vl.valuation_score_for_index('000300'))

    def test_low_pe_high_score(self):
        # 当前 PE 处历史低位 → 分位分高（低估→高分）
        rows = tuple((float(v),) for v in [30, 28, 26, 24, 22, 20, 18, 16, 14, 12, 10])
        with mock.patch.object(vl.mdb, 'checkTableIsExist', return_value=True), \
                mock.patch.object(vl.mdb, 'executeSqlFetch', return_value=rows):
            score = vl.valuation_score_for_index('000300')
        self.assertIsNotNone(score)
        self.assertGreater(score, 50.0)


class TestValuationScoreForFund(unittest.TestCase):
    def test_no_index_mapping(self):
        with mock.patch.object(vl, 'index_code_for_fund', return_value=None):
            idx, score = vl.valuation_score_for_fund('000001')
            self.assertIsNone(idx)
            self.assertIsNone(score)

    def test_cache_hit_avoids_second_query(self):
        cache = {'000300': 77.0}
        with mock.patch.object(vl, 'index_code_for_fund', return_value='000300'), \
                mock.patch.object(vl, 'valuation_score_for_index') as vfi:
            idx, score = vl.valuation_score_for_fund('000001', cache)
            self.assertEqual(idx, '000300')
            self.assertEqual(score, 77.0)
            vfi.assert_not_called()

    def test_cache_populated_on_miss(self):
        cache = {}
        with mock.patch.object(vl, 'index_code_for_fund', return_value='000905'), \
                mock.patch.object(vl, 'valuation_score_for_index', return_value=42.0):
            idx, score = vl.valuation_score_for_fund('000002', cache)
            self.assertEqual(idx, '000905')
            self.assertEqual(score, 42.0)
            self.assertEqual(cache, {'000905': 42.0})

    def test_index_returned_even_without_valuation(self):
        # 命中映射但无估值数据 → 仍返回 index_code（供前端透明展示）
        cache = {}
        with mock.patch.object(vl, 'index_code_for_fund', return_value='000300'), \
                mock.patch.object(vl, 'valuation_score_for_index', return_value=None):
            idx, score = vl.valuation_score_for_fund('000003', cache)
            self.assertEqual(idx, '000300')
            self.assertIsNone(score)


class TestPickJobIncludesT3(unittest.TestCase):
    """回归：pick_job._compute_timing 必须把 T3 估值分位喂给 compose（与 Handler 一致）。"""

    def _nav_rows(self, pick_date, n=30):
        rows = []
        base = pick_date - datetime.timedelta(days=n)
        v = 1.0
        for i in range(n):
            v += 0.01
            rows.append((base + datetime.timedelta(days=i), v, v))
        return rows

    def test_t3_passed_to_compose(self):
        from quantia.job import analysis_fund_pick_job as job
        pick_date = datetime.date(2026, 7, 8)
        nav_rows = self._nav_rows(pick_date)
        val_cache = {}
        with mock.patch.object(job.valuation_lookup, 'valuation_score_for_fund',
                               return_value=('000300', 88.0)) as vff:
            tscore, tier, nav_as_of, lag = job._compute_timing(
                nav_rows, '股票型', pick_date, '000001', val_cache)
            vff.assert_called_once_with('000001', val_cache)
        self.assertIsNotNone(tscore)
        self.assertIsNotNone(tier)

    def test_money_type_skips_t3(self):
        from quantia.job import analysis_fund_pick_job as job
        pick_date = datetime.date(2026, 7, 8)
        nav_rows = self._nav_rows(pick_date)
        with mock.patch.object(job.valuation_lookup, 'valuation_score_for_fund') as vff:
            tscore, tier, _, _ = job._compute_timing(
                nav_rows, '货币型', pick_date, '000001', {})
            vff.assert_not_called()
        self.assertIsNone(tscore)
        self.assertIsNone(tier)

    def test_stale_skips_t3(self):
        from quantia.job import analysis_fund_pick_job as job
        pick_date = datetime.date(2026, 7, 8)
        # nav_as_of 15 天前 → 滞后 > 7，不产出档位且不查 T3
        nav_rows = self._nav_rows(pick_date - datetime.timedelta(days=15))
        with mock.patch.object(job.valuation_lookup, 'valuation_score_for_fund') as vff:
            tscore, tier, _, lag = job._compute_timing(
                nav_rows, '股票型', pick_date, '000001', {})
            vff.assert_not_called()
        self.assertIsNone(tscore)
        self.assertIsNone(tier)
        self.assertGreater(lag, 7)


if __name__ == '__main__':
    unittest.main()
