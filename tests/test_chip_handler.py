#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""筹码分布 API（/quantia/api/chip）黑盒测试。

用 AsyncHTTPTestCase 起真实 Tornado app，mock 数据层（DB + 缓存 + 现算），
覆盖 DB 命中 / 现算 / 过期降级 / 空态 / 缺参 各分支，零真实 DB、零网络。
"""

import json
from unittest import mock

import pandas as pd
from tornado.testing import AsyncHTTPTestCase
from tornado.web import Application

import quantia.web.klineHandler as kh


def _make_app():
    return Application([
        (r'/quantia/api/chip', kh.GetChipDistributionHandler),
    ])


def _fake_hist(last_date='2026-07-08', with_turnover=True):
    cols = {
        'date': pd.to_datetime([last_date]),
        'open': [10.0], 'high': [10.5], 'low': [9.8], 'close': [10.2],
        'volume': [100000],
    }
    if with_turnover:
        cols['turnover'] = [3.0]
    return pd.DataFrame(cols)


_DB_ROW = {
    'date': '2026-07-08', 'name': '格力电器', 'close': 10.2,
    'winner_rate': 62.5, 'avg_cost': 9.9,
    'cost_90_low': 9.0, 'cost_90_high': 11.0, 'concentration_90': 0.10,
    'cost_70_low': 9.4, 'cost_70_high': 10.6, 'concentration_70': 0.06,
}


class TestChipHandler(AsyncHTTPTestCase):
    def get_app(self):
        return _make_app()

    def test_missing_code_400(self):
        resp = self.fetch('/quantia/api/chip')
        self.assertEqual(resp.code, 400)
        self.assertIn('error', json.loads(resp.body))

    def test_db_fresh_no_histogram(self):
        # DB 行与缓存最新日相同 → 不过期；缓存无 turnover → 无直方图
        with mock.patch.object(kh, '_query_chip_db', return_value=dict(_DB_ROW)), \
             mock.patch.object(kh.stf, 'read_hist_from_cache',
                               return_value=_fake_hist('2026-07-08', with_turnover=False)):
            resp = self.fetch('/quantia/api/chip?code=000651')
        body = json.loads(resp.body)
        self.assertTrue(body['has_chip'])
        self.assertEqual(body['metrics_source'], 'db')
        self.assertEqual(body['metrics_as_of'], '2026-07-08')
        self.assertIsNone(body['distribution'])
        self.assertAlmostEqual(body['metrics']['winner_rate'], 62.5)

    def test_compute_provides_histogram(self):
        computed = {
            'close': 10.2,
            'prices': [9.0, 9.5, 10.0, 10.5],
            'chips': [10.0, 40.0, 30.0, 20.0],
            'metrics': {k: _DB_ROW[k] for k in (
                'winner_rate', 'avg_cost', 'cost_90_low', 'cost_90_high',
                'concentration_90', 'cost_70_low', 'cost_70_high', 'concentration_70')},
        }
        # DB miss，缓存含 turnover → 现算命中，含直方图
        with mock.patch.object(kh, '_query_chip_db', return_value=None), \
             mock.patch.object(kh.stf, 'read_hist_from_cache',
                               return_value=_fake_hist('2026-07-08', with_turnover=True)), \
             mock.patch.object(kh.cyqd, 'compute_chip_distribution', return_value=computed):
            resp = self.fetch('/quantia/api/chip?code=000651')
        body = json.loads(resp.body)
        self.assertTrue(body['has_chip'])
        self.assertEqual(body['metrics_source'], 'compute')
        self.assertIsNotNone(body['distribution'])
        self.assertEqual(len(body['distribution']['prices']), 4)
        self.assertEqual(body['distribution']['as_of'], '2026-07-08')

    def test_db_stale_no_turnover_degrades(self):
        # DB 行早于缓存最新日 → 过期；缓存无 turnover → 无法现算 → 退回 db_stale
        stale = dict(_DB_ROW, date='2025-12-31')
        with mock.patch.object(kh, '_query_chip_db', return_value=stale), \
             mock.patch.object(kh.stf, 'read_hist_from_cache',
                               return_value=_fake_hist('2026-07-08', with_turnover=False)):
            resp = self.fetch('/quantia/api/chip?code=000651')
        body = json.loads(resp.body)
        self.assertTrue(body['has_chip'])
        self.assertEqual(body['metrics_source'], 'db_stale')
        self.assertEqual(body['metrics_as_of'], '2025-12-31')
        self.assertIsNone(body['distribution'])
        self.assertTrue(body['message'])

    def test_no_data_empty_state(self):
        # DB miss + 无缓存 → 空态
        with mock.patch.object(kh, '_query_chip_db', return_value=None), \
             mock.patch.object(kh.stf, 'read_hist_from_cache', return_value=None):
            resp = self.fetch('/quantia/api/chip?code=603917')
        body = json.loads(resp.body)
        self.assertFalse(body['has_chip'])
        self.assertIsNone(body['metrics'])
        self.assertIsNone(body['distribution'])
        self.assertTrue(body['message'])


if __name__ == '__main__':
    import unittest
    unittest.main()
