#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""基金同类平均净值基线 — FundNavPeerHandler 单元测试（F9 §9.3）。"""

import json
import os
import sys
from unittest import mock

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tornado.testing import AsyncHTTPTestCase
from tornado.web import Application

import quantia.web.fundNavHistoryHandler as nvh


def _make_peer_df():
    """三只同类基金 + 目标自身（target=001045）的净值长表。"""
    rows = []
    # 目标自身（compute 时应被排除，不计入 peer 均值）
    for d, acc in [('2026-05-27', 5.0), ('2026-05-28', 5.5), ('2026-05-29', 6.0)]:
        rows.append({'code': '001045', 'nav_date': pd.Timestamp(d), 'acc_nav': acc, 'unit_nav': acc})
    # peer A：+10% 然后 +20%
    for d, acc in [('2026-05-27', 1.0), ('2026-05-28', 1.1), ('2026-05-29', 1.2)]:
        rows.append({'code': 'AAA', 'nav_date': pd.Timestamp(d), 'acc_nav': acc, 'unit_nav': acc})
    # peer B：+0% 然后 +0%（基准 2.0）
    for d, acc in [('2026-05-27', 2.0), ('2026-05-28', 2.0), ('2026-05-29', 2.0)]:
        rows.append({'code': 'BBB', 'nav_date': pd.Timestamp(d), 'acc_nav': acc, 'unit_nav': acc})
    return pd.DataFrame(rows)


def _make_app():
    return Application([
        (r'/api/fund/nav_peer', nvh.FundNavPeerHandler),
    ])


class TestComputePeerBaseline:
    def test_excludes_target_and_normalizes_growth(self):
        df = _make_peer_df()
        points, peer_count = nvh.compute_peer_baseline(df, '001045')
        # 仅 AAA / BBB 参与
        assert peer_count == 2
        assert len(points) == 3
        # 起点均为 0%
        assert points[0]['growth'] == 0.0
        # 末日：AAA=+20%, BBB=0% → 平均 10%
        assert abs(points[-1]['growth'] - 10.0) < 1e-6

    def test_empty_df_returns_empty(self):
        points, peer_count = nvh.compute_peer_baseline(pd.DataFrame(), '001045')
        assert points == []
        assert peer_count == 0

    def test_only_target_returns_empty(self):
        df = _make_peer_df()
        df = df[df['code'] == '001045']
        points, peer_count = nvh.compute_peer_baseline(df, '001045')
        assert points == []
        assert peer_count == 0

    def test_acc_nav_preferred_unit_fallback(self):
        rows = [
            {'code': 'AAA', 'nav_date': pd.Timestamp('2026-05-27'), 'acc_nav': None, 'unit_nav': 1.0},
            {'code': 'AAA', 'nav_date': pd.Timestamp('2026-05-28'), 'acc_nav': None, 'unit_nav': 1.5},
        ]
        points, peer_count = nvh.compute_peer_baseline(pd.DataFrame(rows), 'ZZZ')
        assert peer_count == 1
        assert abs(points[-1]['growth'] - 50.0) < 1e-6


class TestFundNavPeerHandler(AsyncHTTPTestCase):
    def get_app(self):
        return _make_app()

    @mock.patch.object(nvh.pd, 'read_sql')
    @mock.patch.object(nvh.mdb, 'engine', return_value=object())
    @mock.patch.object(nvh.mdb, 'executeSqlFetch')
    @mock.patch.object(nvh.mdb, 'checkTableIsExist', return_value=True)
    def test_peer_ok(self, _exist, mock_fetch, _eng, mock_read):
        # 第一次 fetch: fund_type；第二次 fetch: peer codes
        mock_fetch.side_effect = [
            [('股票型',)],
            [('AAA',), ('BBB',)],
        ]
        mock_read.return_value = _make_peer_df()
        resp = self.fetch('/api/fund/nav_peer?code=001045&range=1y')
        self.assertEqual(resp.code, 200)
        data = json.loads(resp.body)
        self.assertEqual(data['code'], '001045')
        self.assertEqual(data['fund_type'], '股票型')
        self.assertEqual(data['peer_count'], 2)
        self.assertEqual(data['count'], 3)
        self.assertEqual(data['points'][0]['growth'], 0.0)
        self.assertAlmostEqual(data['points'][-1]['growth'], 10.0, places=4)

    def test_peer_missing_code(self):
        resp = self.fetch('/api/fund/nav_peer')
        self.assertEqual(resp.code, 400)
        self.assertIn('error', json.loads(resp.body))

    @mock.patch.object(nvh.mdb, 'checkTableIsExist', return_value=False)
    def test_peer_no_table_empty(self, _exist):
        resp = self.fetch('/api/fund/nav_peer?code=001045')
        self.assertEqual(resp.code, 200)
        data = json.loads(resp.body)
        self.assertEqual(data['peer_count'], 0)
        self.assertEqual(data['count'], 0)
        self.assertEqual(data['points'], [])

    @mock.patch.object(nvh.mdb, 'executeSqlFetch', return_value=[])
    @mock.patch.object(nvh.mdb, 'checkTableIsExist', return_value=True)
    def test_peer_unknown_fund_type_empty(self, _exist, _fetch):
        resp = self.fetch('/api/fund/nav_peer?code=999999')
        self.assertEqual(resp.code, 200)
        data = json.loads(resp.body)
        self.assertEqual(data['count'], 0)
        self.assertEqual(data['points'], [])
