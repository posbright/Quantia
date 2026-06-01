#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PR-3 单元测试：F8 净值历史 / F10 规模画像 / F12 持仓股（mock akshare + DB，禁真实网络/DB）。

覆盖：
- fund_em 净值历史合并（unit+acc）、规模解析、画像透视、持仓比例解析/最新季度/列映射
- F8 job 增量过滤 + Top-N 选码 + 编排
- F10 job 画像 upsert + 列对齐
- F12 job 行业回填 + 删旧重写 + 含权益桶选码
"""
import datetime
import sys
import types
import unittest
from unittest import mock

import pandas as pd

import quantia.core.tablestructure as tbs
from quantia.core.crawling import fund_em as fem


# ── F8/F10/F12 crawler 纯函数 ───────────────────────────────────────
class TestFundEmNavHistory(unittest.TestCase):

    def test_map_nav_history_merges_unit_and_acc(self):
        unit = pd.DataFrame({
            '净值日期': ['2026-05-28', '2026-05-29'],
            '单位净值': ['1.10', '1.12'],
            '日增长率': ['0.5', '1.8'],
        })
        acc = pd.DataFrame({
            '净值日期': ['2026-05-28', '2026-05-29'],
            '累计净值': ['2.10', '2.12'],
        })
        out = fem._map_nav_history(unit, acc, '000001')
        self.assertEqual(list(out.columns),
                         ['code', 'nav_date', 'unit_nav', 'acc_nav', 'day_growth'])
        self.assertEqual(out['code'].iloc[0], '000001')
        self.assertAlmostEqual(out['unit_nav'].iloc[1], 1.12)
        self.assertAlmostEqual(out['acc_nav'].iloc[1], 2.12)
        self.assertEqual(out['nav_date'].iloc[0], datetime.date(2026, 5, 28))

    def test_map_nav_history_without_acc_fills_na(self):
        unit = pd.DataFrame({'净值日期': ['2026-05-29'], '单位净值': ['1.5'], '日增长率': ['0.1']})
        out = fem._map_nav_history(unit, None, '110011')
        self.assertTrue(out['acc_nav'].isna().all())
        self.assertAlmostEqual(out['unit_nav'].iloc[0], 1.5)

    def test_map_nav_history_empty_returns_none(self):
        self.assertIsNone(fem._map_nav_history(pd.DataFrame(), None, 'x'))
        self.assertIsNone(fem._map_nav_history(None, None, 'x'))

    def test_map_nav_history_drops_bad_dates(self):
        unit = pd.DataFrame({'净值日期': ['bad', '2026-05-29'], '单位净值': ['1', '2'],
                             '日增长率': ['0', '0']})
        out = fem._map_nav_history(unit, None, '1')
        self.assertEqual(len(out.index), 1)


class TestFundEmProfile(unittest.TestCase):

    def test_parse_scale_yi(self):
        self.assertAlmostEqual(fem._parse_scale_yi('26.44亿'), 26.44)
        self.assertAlmostEqual(fem._parse_scale_yi('5000万'), 0.5)
        self.assertIsNone(fem._parse_scale_yi('暂无数据'))
        self.assertIsNone(fem._parse_scale_yi(None))
        self.assertIsNone(fem._parse_scale_yi(''))

    def test_pivot_profile(self):
        info = pd.DataFrame({
            'item': ['基金名称', '基金全称', '成立时间', '最新规模', '基金公司',
                     '基金经理', '基金类型', '基金评级', '业绩比较基准'],
            'value': ['华夏成长', '华夏成长混合', '2001-12-18', '26.44亿', '华夏基金',
                      '张三', '混合型-偏股', '5星', '沪深300×80%+中证综合债×20%'],
        })
        row = fem._pivot_profile(info, '000001')
        self.assertEqual(row['code'], '000001')
        self.assertEqual(row['name'], '华夏成长')
        self.assertAlmostEqual(row['scale_yi'], 26.44)
        self.assertEqual(row['setup_date'], datetime.date(2001, 12, 18))
        self.assertEqual(row['company'], '华夏基金')
        self.assertEqual(row['rating'], '5星')
        self.assertIn('沪深300', row['benchmark'])

    def test_pivot_profile_missing_items_none(self):
        info = pd.DataFrame({'item': ['基金名称'], 'value': ['只有名字']})
        row = fem._pivot_profile(info, '1')
        self.assertEqual(row['name'], '只有名字')
        self.assertIsNone(row['scale_yi'])
        self.assertIsNone(row['benchmark'])

    def test_pivot_profile_bad_input(self):
        self.assertIsNone(fem._pivot_profile(None, '1'))
        self.assertIsNone(fem._pivot_profile(pd.DataFrame({'a': [1]}), '1'))


class TestFundEmHolding(unittest.TestCase):

    def test_parse_ratio(self):
        self.assertAlmostEqual(fem._parse_ratio('5.21%'), 5.21)
        self.assertAlmostEqual(fem._parse_ratio('3.1'), 3.1)
        self.assertIsNone(fem._parse_ratio('---'))

    def test_pick_latest_quarter(self):
        df = pd.DataFrame({
            '股票代码': ['600000', '000001', '600519'],
            '季度': ['2024年4季度', '2025年1季度', '2024年4季度'],
        })
        out = fem._pick_latest_quarter(df)
        self.assertEqual(len(out.index), 1)
        self.assertEqual(out['季度'].iloc[0], '2025年1季度')

    def test_map_holding_columns(self):
        df = pd.DataFrame({
            '序号': [1, 2],
            '股票代码': ['600000', '1'],
            '股票名称': ['浦发银行', '平安银行'],
            '占净值比例': ['5.21%', '3.10%'],
            '持股数': ['1000', '2000'],
            '持仓市值': ['5000', '6000'],
            '季度': ['2025年1季度', '2025年1季度'],
        })
        out = fem._map_holding_columns(df, '000001')
        self.assertEqual(out['code'].iloc[0], '000001')
        self.assertEqual(out['stock_code'].iloc[1], '000001')  # zfill(6)
        self.assertAlmostEqual(out['hold_ratio'].iloc[0], 5.21)
        self.assertAlmostEqual(out['hold_value'].iloc[0], 5000.0)

    def test_map_holding_empty(self):
        self.assertIsNone(fem._map_holding_columns(None, '1'))
        self.assertIsNone(fem._map_holding_columns(pd.DataFrame(), '1'))


# ── F8 job ──────────────────────────────────────────────────────────
class TestNavHistoryJob(unittest.TestCase):

    def setUp(self):
        import quantia.job.fetch_fund_nav_history_job as job
        self.job = job
        self._sleep = mock.patch.object(job.time, 'sleep', lambda *a, **k: None)
        self._sleep.start()

    def tearDown(self):
        self._sleep.stop()

    def test_save_filters_increment(self):
        hist = pd.DataFrame({
            'code': ['000001', '000001'],
            'nav_date': [datetime.date(2026, 5, 28), datetime.date(2026, 5, 29)],
            'unit_nav': [1.1, 1.2], 'acc_nav': [2.1, 2.2], 'day_growth': [0.1, 0.2],
        })
        captured = {}

        def fake_insert(data, table, cols_type, wi, pk):
            captured['rows'] = len(data.index)

        with mock.patch.object(self.job.fem, 'fund_nav_history', return_value=hist), \
             mock.patch.object(self.job.mdb, 'checkTableIsExist', return_value=True), \
             mock.patch.object(self.job, '_existing_max_navdate',
                               return_value=datetime.date(2026, 5, 28)), \
             mock.patch.object(self.job.mdb, 'insert_db_from_df', side_effect=fake_insert):
            n = self.job.save_fund_nav_history('000001')
        self.assertEqual(n, 1)            # 仅 5-29 增量行
        self.assertEqual(captured['rows'], 1)

    def test_save_no_increment_skips_insert(self):
        hist = pd.DataFrame({
            'code': ['000001'], 'nav_date': [datetime.date(2026, 5, 28)],
            'unit_nav': [1.1], 'acc_nav': [2.1], 'day_growth': [0.1],
        })
        with mock.patch.object(self.job.fem, 'fund_nav_history', return_value=hist), \
             mock.patch.object(self.job.mdb, 'checkTableIsExist', return_value=True), \
             mock.patch.object(self.job, '_existing_max_navdate',
                               return_value=datetime.date(2026, 5, 28)), \
             mock.patch.object(self.job.mdb, 'insert_db_from_df') as ins:
            n = self.job.save_fund_nav_history('000001')
        self.assertEqual(n, 0)
        ins.assert_not_called()

    def test_run_orchestrates_codes(self):
        with mock.patch.object(self.job, 'save_fund_nav_history', return_value=3) as sv, \
             mock.patch.object(self.job, 'record_task_start', return_value=0.0), \
             mock.patch.object(self.job, 'record_task_end'):
            total = self.job.run(codes=['000001', '110011'])
        self.assertEqual(total, 6)
        self.assertEqual(sv.call_count, 2)


# ── F10 job ─────────────────────────────────────────────────────────
class TestProfileJob(unittest.TestCase):

    def setUp(self):
        import quantia.job.fetch_fund_profile_job as job
        self.job = job
        self._sleep = mock.patch.object(job.time, 'sleep', lambda *a, **k: None)
        self._sleep.start()

    def tearDown(self):
        self._sleep.stop()

    def test_save_profile_aligns_columns(self):
        row = {'code': '000001', 'name': '华夏成长', 'scale_yi': 26.44, 'company': '华夏基金'}
        captured = {}

        def fake_insert(data, table, cols_type, wi, pk):
            captured['cols'] = list(data.columns)
            captured['code'] = data['code'].iloc[0]

        with mock.patch.object(self.job.fem, 'fund_profile', return_value=row), \
             mock.patch.object(self.job.mdb, 'checkTableIsExist', return_value=True), \
             mock.patch.object(self.job.mdb, 'insert_db_from_df', side_effect=fake_insert):
            n = self.job.save_fund_profile('000001', datetime.date(2026, 6, 1))
        self.assertEqual(n, 1)
        self.assertEqual(captured['cols'], list(tbs.TABLE_CN_FUND_PROFILE['columns']))
        self.assertEqual(captured['code'], '000001')

    def test_save_profile_no_data(self):
        with mock.patch.object(self.job.fem, 'fund_profile', return_value=None), \
             mock.patch.object(self.job.mdb, 'insert_db_from_df') as ins:
            n = self.job.save_fund_profile('x', datetime.date(2026, 6, 1))
        self.assertEqual(n, 0)
        ins.assert_not_called()


# ── F12 job ─────────────────────────────────────────────────────────
class TestHoldingJob(unittest.TestCase):

    def setUp(self):
        import quantia.job.fetch_fund_holding_job as job
        self.job = job
        self._sleep = mock.patch.object(job.time, 'sleep', lambda *a, **k: None)
        self._sleep.start()

    def tearDown(self):
        self._sleep.stop()

    def test_join_industry(self):
        df = pd.DataFrame({'stock_code': ['600000', '999999']})
        out = self.job._join_industry(df, {'600000': '银行'})
        self.assertEqual(out['industry'].iloc[0], '银行')
        self.assertEqual(out['industry'].iloc[1], self.job._UNKNOWN_INDUSTRY)

    def test_save_holding_deletes_old_then_writes(self):
        held = pd.DataFrame({
            'code': ['000001'], 'stock_code': ['600000'], 'stock_name': ['浦发银行'],
            'hold_ratio': [5.21], 'hold_shares': [1000.0], 'hold_value': [5000.0],
            'quarter': ['2025年1季度'],
        })
        captured = {}

        def fake_insert(data, table, cols_type, wi, pk):
            captured['cols'] = list(data.columns)
            captured['industry'] = data['industry'].iloc[0]

        with mock.patch.object(self.job.fem, 'fund_holding_latest', return_value=held), \
             mock.patch.object(self.job.mdb, 'checkTableIsExist', return_value=True), \
             mock.patch.object(self.job.mdb, 'executeSql') as dele, \
             mock.patch.object(self.job.mdb, 'insert_db_from_df', side_effect=fake_insert):
            n = self.job.save_fund_holding('000001', 2026, {'600000': '银行'},
                                           datetime.date(2026, 6, 1))
        self.assertEqual(n, 1)
        dele.assert_called_once()          # 删旧
        self.assertEqual(captured['cols'], list(tbs.TABLE_CN_FUND_HOLDING['columns']))
        self.assertEqual(captured['industry'], '银行')

    def test_run_uses_equity_types(self):
        with mock.patch.object(self.job, '_select_target_codes', return_value=['000001']) as sel, \
             mock.patch.object(self.job, '_load_industry_map', return_value={}), \
             mock.patch.object(self.job, 'save_fund_holding', return_value=10), \
             mock.patch.object(self.job, 'record_task_start', return_value=0.0), \
             mock.patch.object(self.job, 'record_task_end'):
            total = self.job.run()
        self.assertEqual(total, 10)
        sel.assert_called_once()


if __name__ == '__main__':
    unittest.main()
