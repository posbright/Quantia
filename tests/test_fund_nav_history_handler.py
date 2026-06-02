#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""基金净值曲线 — fundNavHistoryHandler 单元测试（F9 §9.3）。"""

import json
import os
import sys
from unittest import mock

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tornado.testing import AsyncHTTPTestCase
from tornado.web import Application

import quantia.web.fundNavHistoryHandler as nvh


def _make_nav_df():
    return pd.DataFrame([
        {'nav_date': pd.Timestamp('2026-05-27'), 'unit_nav': 2.0, 'acc_nav': 3.0},
        {'nav_date': pd.Timestamp('2026-05-28'), 'unit_nav': 2.1, 'acc_nav': 3.1},
        {'nav_date': pd.Timestamp('2026-05-29'), 'unit_nav': 2.2, 'acc_nav': 3.2},
    ])


def _make_app():
    return Application([
        (r'/api/fund/nav_history', nvh.FundNavHistoryHandler),
    ])


class TestFundNavHistoryHandler(AsyncHTTPTestCase):
    def get_app(self):
        return _make_app()

    @mock.patch.object(nvh.pd, 'read_sql')
    @mock.patch.object(nvh.mdb, 'executeSqlFetch', return_value=[('基金A',)])
    @mock.patch.object(nvh.mdb, 'engine', return_value=object())
    @mock.patch.object(nvh.mdb, 'checkTableIsExist', return_value=True)
    def test_nav_history_ok(self, _exist, _eng, _fetch, mock_read):
        mock_read.return_value = _make_nav_df()
        resp = self.fetch('/api/fund/nav_history?code=001045&range=1y')
        self.assertEqual(resp.code, 200)
        data = json.loads(resp.body)
        self.assertEqual(data['code'], '001045')
        self.assertEqual(data['name'], '基金A')
        self.assertEqual(data['range'], '1y')
        self.assertEqual(data['count'], 3)
        self.assertEqual(data['points'][0]['date'], '2026-05-27')
        self.assertEqual(data['points'][0]['acc_nav'], 3.0)

    @mock.patch.object(nvh.pd, 'read_sql')
    @mock.patch.object(nvh.mdb, 'executeSqlFetch', return_value=[('基金A',)])
    @mock.patch.object(nvh.mdb, 'engine', return_value=object())
    @mock.patch.object(nvh.mdb, 'checkTableIsExist', return_value=True)
    def test_nav_history_all_range_no_date_filter(self, _exist, _eng, _fetch, mock_read):
        mock_read.return_value = _make_nav_df()
        self.fetch('/api/fund/nav_history?code=001045&range=all')
        sql, kwargs = mock_read.call_args
        # all 区间不应注入 nav_date >= 起点过滤
        self.assertNotIn('nav_date` >= ', sql[0])
        self.assertEqual(kwargs.get('params'), ('001045',))

    @mock.patch.object(nvh.pd, 'read_sql')
    @mock.patch.object(nvh.mdb, 'executeSqlFetch', return_value=[('基金A',)])
    @mock.patch.object(nvh.mdb, 'engine', return_value=object())
    @mock.patch.object(nvh.mdb, 'checkTableIsExist', return_value=True)
    def test_nav_history_bad_range_falls_back(self, _exist, _eng, _fetch, mock_read):
        mock_read.return_value = _make_nav_df()
        resp = self.fetch('/api/fund/nav_history?code=001045&range=xyz')
        data = json.loads(resp.body)
        self.assertEqual(data['range'], '1y')

    def test_nav_history_missing_code(self):
        resp = self.fetch('/api/fund/nav_history')
        self.assertEqual(resp.code, 400)
        self.assertIn('error', json.loads(resp.body))

    @mock.patch.object(nvh.mdb, 'checkTableIsExist', return_value=False)
    def test_nav_history_no_table_empty(self, _exist):
        resp = self.fetch('/api/fund/nav_history?code=001045')
        self.assertEqual(resp.code, 200)
        data = json.loads(resp.body)
        self.assertEqual(data['count'], 0)
        self.assertEqual(data['points'], [])
