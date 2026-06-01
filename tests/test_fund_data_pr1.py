#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PR-1 单元测试：场外基金数据薄封装 + stockfetch 调度（mock akshare，禁真实网络）。

覆盖：
- fund_em 列映射（净值型/货币型）、费率 strip%、数值 coerce、容错跳过
- stockfetch.fetch_funds 字段对齐 TABLE_CN_FUND_RANK、去重、date 注入
- tablestructure 五表定义健全性
"""
import datetime
import sys
import types
import unittest
from unittest import mock

import pandas as pd

import quantia.core.tablestructure as tbs


def _fake_akshare():
    """构造一个假的 akshare 模块，供 fund_em 内部 `import akshare as ak` 使用。"""
    ak = types.ModuleType('akshare')

    def fund_open_fund_rank_em(symbol):
        return pd.DataFrame({
            '序号': [1, 2],
            '基金代码': ['000001', '110011'],
            '基金简称': ['华夏成长', '易方达中小盘'],
            '日期': ['2026-05-29', '2026-05-29'],
            '单位净值': ['1.234', '5.678'],
            '累计净值': ['3.456', '7.890'],
            '日增长率': ['0.51', '-0.32'],
            '近1周': ['1.1', '2.2'],
            '近1月': ['3.3', '4.4'],
            '近3月': ['5.5', '6.6'],
            '近6月': ['7.7', '8.8'],
            '近1年': ['9.9', '10.1'],
            '近2年': ['11.1', '12.2'],
            '近3年': ['13.3', '14.4'],
            '今年来': ['15.5', '16.6'],
            '成立来': ['100.1', '200.2'],
            '自定义': ['x', 'y'],
            '手续费': ['0.15%', '---'],
        })

    def fund_money_rank_em():
        return pd.DataFrame({
            '序号': [1],
            '基金代码': ['000198'],
            '基金简称': ['天弘余额宝'],
            '日期': ['2026-05-29'],
            '万份收益': ['0.6543'],
            '年化收益率7日': ['1.85'],
            '年化收益率14日': ['1.83'],
            '年化收益率28日': ['1.80'],
            '近1月': ['0.15'],
            '近3月': ['0.45'],
            '近6月': ['0.90'],
            '近1年': ['1.80'],
            '近2年': ['3.60'],
            '近3年': ['5.40'],
            '近5年': ['9.00'],
            '今年来': ['0.75'],
            '成立来': ['20.0'],
            '手续费': ['0'],
        })

    ak.fund_open_fund_rank_em = fund_open_fund_rank_em
    ak.fund_money_rank_em = fund_money_rank_em
    return ak


class TestFundEmMapping(unittest.TestCase):

    def setUp(self):
        # 注入假 akshare，并把 sleep 置空避免限速拖慢测试
        self._ak_patch = mock.patch.dict(sys.modules, {'akshare': _fake_akshare()})
        self._ak_patch.start()
        self._sleep_patch = mock.patch('quantia.core.crawling.fund_em.time.sleep', lambda *a, **k: None)
        self._sleep_patch.start()

    def tearDown(self):
        self._sleep_patch.stop()
        self._ak_patch.stop()

    def test_parse_fee(self):
        from quantia.core.crawling import fund_em as fem
        self.assertEqual(fem._parse_fee('0.15%'), 0.15)
        self.assertEqual(fem._parse_fee('0'), 0.0)
        self.assertIsNone(fem._parse_fee('---'))
        self.assertIsNone(fem._parse_fee(''))
        self.assertIsNone(fem._parse_fee(None))

    def test_map_nav_columns(self):
        from quantia.core.crawling import fund_em as fem
        ak = sys.modules['akshare']
        out = fem._map_nav_columns(ak.fund_open_fund_rank_em('股票型'))
        # 序号/自定义 丢弃
        self.assertNotIn('序号', out.columns)
        self.assertNotIn('自定义', out.columns)
        # 列映射
        self.assertIn('unit_nav', out.columns)
        self.assertIn('acc_nav', out.columns)
        self.assertIn('rate_1y', out.columns)
        # 数值 coerce
        self.assertAlmostEqual(out.iloc[0]['unit_nav'], 1.234)
        self.assertAlmostEqual(out.iloc[0]['rate_1y'], 9.9)
        # 费率解析：'0.15%'→0.15，'---'→None
        self.assertAlmostEqual(out.iloc[0]['fee'], 0.15)
        self.assertTrue(pd.isna(out.iloc[1]['fee']))

    def test_map_money_columns(self):
        from quantia.core.crawling import fund_em as fem
        ak = sys.modules['akshare']
        out = fem._map_money_columns(ak.fund_money_rank_em())
        self.assertIn('million_unit_income', out.columns)
        self.assertIn('seven_day_annual', out.columns)
        self.assertNotIn('unit_nav', out.columns)  # 货币型无单位净值
        self.assertAlmostEqual(out.iloc[0]['million_unit_income'], 0.6543)
        self.assertAlmostEqual(out.iloc[0]['seven_day_annual'], 1.85)
        self.assertEqual(out.iloc[0]['fee'], 0.0)

    def test_fund_rank_all_concat(self):
        from quantia.core.crawling import fund_em as fem
        df = fem.fund_rank_all()
        self.assertIsNotNone(df)
        # 6 个净值型类型各 2 行 + 货币型 1 行 = 13
        self.assertEqual(len(df), 6 * 2 + 1)
        self.assertIn('fund_type', df.columns)
        types_present = set(df['fund_type'].unique())
        self.assertEqual(types_present, set(fem._NAV_TYPES) | {'货币型'})
        # 互斥列：货币型行 million_unit_income 有值、unit_nav NaN
        money = df[df['fund_type'] == '货币型'].iloc[0]
        self.assertAlmostEqual(money['million_unit_income'], 0.6543)
        self.assertTrue(pd.isna(money['unit_nav']))

    def test_fund_rank_all_partial_failure(self):
        """某净值型抛错时跳过、不影响其他类型与货币型。"""
        from quantia.core.crawling import fund_em as fem
        ak = sys.modules['akshare']
        orig = ak.fund_open_fund_rank_em

        def flaky(symbol):
            if symbol == '债券型':
                raise RuntimeError('akshare 限流')
            return orig(symbol)

        with mock.patch.object(ak, 'fund_open_fund_rank_em', flaky):
            df = fem.fund_rank_all()
        self.assertIsNotNone(df)
        self.assertNotIn('债券型', set(df['fund_type'].unique()))
        self.assertIn('股票型', set(df['fund_type'].unique()))
        self.assertIn('货币型', set(df['fund_type'].unique()))

    def test_fund_rank_all_total_failure(self):
        from quantia.core.crawling import fund_em as fem
        ak = sys.modules['akshare']

        def boom(*a, **k):
            raise RuntimeError('down')

        with mock.patch.object(ak, 'fund_open_fund_rank_em', boom), \
                mock.patch.object(ak, 'fund_money_rank_em', boom):
            df = fem.fund_rank_all()
        self.assertIsNone(df)


class TestFetchFunds(unittest.TestCase):

    def setUp(self):
        self._ak_patch = mock.patch.dict(sys.modules, {'akshare': _fake_akshare()})
        self._ak_patch.start()
        self._sleep_patch = mock.patch('quantia.core.crawling.fund_em.time.sleep', lambda *a, **k: None)
        self._sleep_patch.start()

    def tearDown(self):
        self._sleep_patch.stop()
        self._ak_patch.stop()

    def test_fetch_funds_aligns_table_columns(self):
        import quantia.core.stockfetch as stf
        data = stf.fetch_funds(datetime.date(2026, 5, 30))
        self.assertIsNotNone(data)
        # 列与表定义完全一致且有序
        self.assertEqual(list(data.columns), list(tbs.TABLE_CN_FUND_RANK['columns']))
        # date 注入为运行日
        self.assertTrue((data['date'] == '2026-05-30').all())
        # nav_date 保留 akshare 披露日
        self.assertIn('2026-05-29', set(data['nav_date'].astype(str)))

    def test_fetch_funds_dedup_by_code(self):
        import quantia.core.stockfetch as stf
        data = stf.fetch_funds(None)
        self.assertEqual(data['code'].is_unique, True)

    def test_fetch_funds_none_when_source_fails(self):
        import quantia.core.stockfetch as stf
        with mock.patch('quantia.core.crawling.fund_em.fund_rank_all', return_value=None):
            self.assertIsNone(stf.fetch_funds(None))


class TestFundTableStructures(unittest.TestCase):

    def test_five_tables_defined(self):
        for attr in ('TABLE_CN_FUND_RANK', 'TABLE_CN_FUND_NAV_HISTORY',
                     'TABLE_CN_FUND_PROFILE', 'TABLE_CN_FUND_HOLDING',
                     'TABLE_CN_FUND_RANK_SCORE', 'TABLE_CN_FUND_AI_ANALYSIS'):
            t = getattr(tbs, attr)
            self.assertIn('name', t)
            self.assertIn('columns', t)
            self.assertTrue(len(t['columns']) > 0)
            # get_field_types 可用
            ft = tbs.get_field_types(t['columns'])
            self.assertEqual(set(ft), set(t['columns']))

    def test_rank_has_both_nav_and_money_columns(self):
        cols = tbs.TABLE_CN_FUND_RANK['columns']
        for c in ('unit_nav', 'acc_nav', 'million_unit_income', 'seven_day_annual',
                  'nav_date', 'fund_type', 'fee'):
            self.assertIn(c, cols)

    def test_nav_history_has_acc_nav(self):
        # 长期口径必须有 acc_nav
        self.assertIn('acc_nav', tbs.TABLE_CN_FUND_NAV_HISTORY['columns'])


if __name__ == '__main__':
    unittest.main()
