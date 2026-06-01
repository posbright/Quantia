#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""场外基金排名 — fundRankHandler 单元测试（F6 方案 A）。"""

import json
import os
import sys
from unittest import mock

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tornado.testing import AsyncHTTPTestCase
from tornado.web import Application

import quantia.web.fundRankHandler as frh


def _make_rank_df():
    return pd.DataFrame([
        {'code': '001045', 'name': '基金A', 'fund_type': '股票型', 'nav_date': '2026-05-29',
         'unit_nav': 2.1, 'acc_nav': 3.0, 'day_growth': 1.2, 'million_unit_income': None,
         'seven_day_annual': None, 'rate_1w': 0.5, 'rate_1m': 1.0, 'rate_3m': 2.0,
         'rate_6m': 3.0, 'rate_1y': 15.0, 'rate_2y': 20.0, 'rate_3y': 30.0,
         'rate_ytd': 8.0, 'rate_since': 110.0, 'fee': 0.15},
        {'code': '012887', 'name': '基金B', 'fund_type': '股票型', 'nav_date': '2026-05-29',
         'unit_nav': 1.5, 'acc_nav': 1.8, 'day_growth': -0.3, 'million_unit_income': None,
         'seven_day_annual': None, 'rate_1w': 0.2, 'rate_1m': 0.5, 'rate_3m': 1.0,
         'rate_6m': 2.0, 'rate_1y': 12.0, 'rate_2y': 18.0, 'rate_3y': 25.0,
         'rate_ytd': 6.0, 'rate_since': 80.0, 'fee': 0.1},
    ])


def _make_app():
    return Application([
        (r'/api/fund/rank/meta', frh.FundRankMetaHandler),
        (r'/api/fund/rank', frh.FundRankHandler),
    ])


class TestFundRankMetaHandler(AsyncHTTPTestCase):
    def get_app(self):
        return _make_app()

    @mock.patch.object(frh.mdb, 'executeSqlFetch', return_value=[('2026-05-29',)])
    @mock.patch.object(frh.mdb, 'checkTableIsExist', return_value=True)
    def test_meta_returns_types_and_periods(self, _exist, _fetch):
        resp = self.fetch('/api/fund/rank/meta')
        self.assertEqual(resp.code, 200)
        data = json.loads(resp.body)
        self.assertIn('股票型', data['fund_types'])
        self.assertIn('货币型', data['fund_types'])
        period_vals = [p['value'] for p in data['periods']]
        self.assertIn('rate_1y', period_vals)
        self.assertEqual(data['default_period'], 'rate_1y')
        self.assertEqual(data['latest_date'], '2026-05-29')

    @mock.patch.object(frh.mdb, 'checkTableIsExist', return_value=False)
    def test_meta_no_table_returns_null_date(self, _exist):
        resp = self.fetch('/api/fund/rank/meta')
        self.assertEqual(resp.code, 200)
        data = json.loads(resp.body)
        self.assertIsNone(data['latest_date'])


class TestFundRankHandler(AsyncHTTPTestCase):
    def get_app(self):
        return _make_app()

    @mock.patch.object(frh.pd, 'read_sql')
    @mock.patch.object(frh.mdb, 'executeSqlFetch', return_value=[('2026-05-29',)])
    @mock.patch.object(frh.mdb, 'engine', return_value=object())
    @mock.patch.object(frh.mdb, 'checkTableIsExist', return_value=True)
    def test_rank_returns_sorted_items(self, _exist, _eng, _fetch, mock_read):
        mock_read.return_value = _make_rank_df()
        resp = self.fetch('/api/fund/rank?fund_type=股票型&period=rate_1y&limit=10')
        self.assertEqual(resp.code, 200)
        data = json.loads(resp.body)
        self.assertEqual(data['fund_type'], '股票型')
        self.assertEqual(data['period'], 'rate_1y')
        self.assertEqual(data['count'], 2)
        self.assertEqual(data['date'], '2026-05-29')
        self.assertEqual(data['items'][0]['code'], '001045')

    @mock.patch.object(frh.mdb, 'checkTableIsExist', return_value=True)
    def test_rank_rejects_bad_fund_type(self, _exist):
        resp = self.fetch('/api/fund/rank?fund_type=非法类型&period=rate_1y')
        self.assertEqual(resp.code, 400)
        self.assertIn('error', json.loads(resp.body))

    @mock.patch.object(frh.mdb, 'checkTableIsExist', return_value=True)
    def test_rank_rejects_bad_period(self, _exist):
        resp = self.fetch('/api/fund/rank?fund_type=股票型&period=rate_99y')
        self.assertEqual(resp.code, 400)
        self.assertIn('error', json.loads(resp.body))

    @mock.patch.object(frh.mdb, 'checkTableIsExist', return_value=False)
    def test_rank_no_table_returns_empty(self, _exist):
        resp = self.fetch('/api/fund/rank?fund_type=股票型&period=rate_1y')
        self.assertEqual(resp.code, 200)
        data = json.loads(resp.body)
        self.assertEqual(data['count'], 0)
        self.assertEqual(data['items'], [])

    @mock.patch.object(frh.pd, 'read_sql')
    @mock.patch.object(frh.mdb, 'executeSqlFetch', return_value=[('2026-05-29',)])
    @mock.patch.object(frh.mdb, 'engine', return_value=object())
    @mock.patch.object(frh.mdb, 'checkTableIsExist', return_value=True)
    def test_rank_clamps_limit(self, _exist, _eng, _fetch, mock_read):
        mock_read.return_value = _make_rank_df()
        self.fetch('/api/fund/rank?fund_type=股票型&period=rate_1y&limit=99999')
        # 校验传入 read_sql 的 LIMIT 参数被钳制到 _MAX_LIMIT
        _, kwargs = mock_read.call_args
        params = kwargs.get('params')
        self.assertEqual(params[1], frh._MAX_LIMIT)
