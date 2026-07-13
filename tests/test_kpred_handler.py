#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""K 线预测 provider、响应归一化与 Handler 契约测试。"""

import json
import os
import datetime
import asyncio
import time
from unittest import mock

from tornado.httpclient import HTTPRequest
from tornado.testing import AsyncHTTPTestCase, gen_test
from tornado.web import Application

import quantia.web.kpredHandler as kh


def _prediction_payload():
    return {
        'symbol': '300308',
        'name': '测试股票',
        'last_close': 10.0,
        'last_date': '2026-07-10',
        'predictions': [
            {'date': '2026-07-13', 'open': 10.0, 'high': 10.3,
             'low': 9.9, 'close': 10.2, 'volume': 100000},
        ],
        'pro': {
            'composite_score': 0.23,
            'rating': '偏多',
            'confidence': '中',
            'conflict_level': '低',
            'adj_return_pct': 1.85,
            'sigma_daily_pct': 2.1,
            'factors': [
                {'key': 'kronos', 'label': 'Kronos技术', 'score': 0.6,
                 'weight': 0.1, 'contribution': 0.06},
            ],
        },
    }


class TestKpredHandler(AsyncHTTPTestCase):
    def get_app(self):
        return Application([(r'/quantia/api/kpred', kh.GetKpredHandler)])

    def setUp(self):
        super().setUp()
        kh._pred_cache.clear()
        kh._pred_cache_date = ''
        kh._singleflight_tasks.clear()

    def _post(self, body):
        return self.fetch(
            '/quantia/api/kpred', method='POST',
            headers={'Content-Type': 'application/json'},
            body=json.dumps(body),
        )

    def test_agentpit_direct_payload_keeps_pro_visible(self):
        payload = _prediction_payload()
        payload['code'] = '300308'
        env = {'QUANTIA_KPRED_PROVIDER': 'agentpit', 'QUANTIA_AGENTPIT_API_KEY': 'test-key'}
        with mock.patch.dict(os.environ, env, clear=False), \
             mock.patch.object(kh, '_do_provider_request', return_value=payload):
            response = self._post({'code': '300308', 'days': 5})

        body = json.loads(response.body)
        self.assertEqual(response.code, 200)
        self.assertEqual(body['data']['provider'], 'agentpit')
        self.assertEqual(body['data']['code'], '300308')
        self.assertEqual(body['data']['pro']['factors'][0]['label'], 'Kronos技术')

    def test_agentpit_wrapped_payload_is_unwrapped_once(self):
        wrapped = {'code': 0, 'data': _prediction_payload()}
        env = {'QUANTIA_KPRED_PROVIDER': 'agentpit', 'QUANTIA_AGENTPIT_API_KEY': 'test-key'}
        with mock.patch.dict(os.environ, env, clear=False), \
             mock.patch.object(kh, '_do_provider_request', return_value=wrapped):
            response = self._post({'code': '300308', 'days': 5})

        body = json.loads(response.body)
        self.assertIn('predictions', body['data'])
        self.assertIn('pro', body['data'])
        self.assertNotIn('data', body['data'])

    def test_local_provider_needs_no_agentpit_key(self):
        env = {
            'QUANTIA_KPRED_PROVIDER': 'local',
            'QUANTIA_KPRED_LOCAL_URL': 'http://127.0.0.1:18081/v1/open-api/kpred',
            'QUANTIA_AGENTPIT_API_KEY': '',
        }
        with mock.patch.dict(os.environ, env, clear=False), \
             mock.patch.object(kh, '_prepare_local_payload', return_value={
                 'code': '300308', 'days': 3, 'history': [], 'future_timestamps': [],
             }), \
             mock.patch.object(kh, '_do_provider_request', return_value=_prediction_payload()) as request:
            response = self._post({'code': '300308', 'days': 3})

        body = json.loads(response.body)
        self.assertEqual(response.code, 200)
        self.assertEqual(body['data']['provider'], 'local')
        self.assertEqual(request.call_args.args[0], env['QUANTIA_KPRED_LOCAL_URL'])
        self.assertEqual(request.call_args.args[1], '')
        self.assertEqual(request.call_args.args[5]['code'], '300308')

    def test_prepare_local_payload_reads_cache_without_network(self):
        import pandas as pd

        frame = pd.DataFrame({
            'date': pd.bdate_range('2026-01-01', periods=90),
            'open': 10.0,
            'high': 10.3,
            'low': 9.8,
            'close': 10.1,
            'volume': 1000,
            'amount': 10100,
        })
        now = datetime.datetime(2026, 5, 7, 12, 0)
        cutoff = frame['date'].iloc[-1].date()
        with mock.patch.dict(os.environ, {'KRONOS_LOOKBACK': '90'}, clear=False), \
                mock.patch('quantia.core.backtest.data_feed.load_stock_data',
                           return_value=frame) as load, \
                mock.patch.object(kh, '_completed_daily_cutoff', return_value=cutoff), \
                mock.patch('quantia.lib.trade_time.get_next_trade_date',
                           side_effect=lambda value: value + datetime.timedelta(days=1)):
            payload = kh._prepare_local_payload('300308', 3, now=now)

        load.assert_called_once_with(
            '300308', end_date=cutoff, cache_only=True
        )
        self.assertEqual(len(payload['history']), 90)
        self.assertEqual(len(payload['future_timestamps']), 3)
        self.assertEqual(
            payload['prediction_start_date'],
            (cutoff + datetime.timedelta(days=1)).isoformat(),
        )

    def test_noon_prediction_starts_today_from_previous_complete_bar(self):
        now = datetime.datetime(2026, 7, 13, 12, 0)
        with mock.patch('quantia.lib.trade_time.is_trade_date', return_value=True), \
             mock.patch('quantia.lib.trade_time.is_post_settlement', return_value=False), \
             mock.patch('quantia.lib.trade_time.get_previous_trade_date',
                        return_value=datetime.date(2026, 7, 10)):
            cutoff = kh._completed_daily_cutoff(now)

        self.assertEqual(cutoff, datetime.date(2026, 7, 10))

    def test_post_settlement_prediction_uses_today_as_complete_bar(self):
        now = datetime.datetime(2026, 7, 13, 18, 30)
        with mock.patch('quantia.lib.trade_time.is_trade_date', return_value=True), \
             mock.patch('quantia.lib.trade_time.is_post_settlement', return_value=True):
            cutoff = kh._completed_daily_cutoff(now)

        self.assertEqual(cutoff, datetime.date(2026, 7, 13))

    def test_stale_history_is_rejected_by_default(self):
        import pandas as pd

        frame = pd.DataFrame({
            'date': pd.bdate_range('2026-01-01', periods=90),
            'open': 10.0, 'high': 10.3, 'low': 9.8, 'close': 10.1,
            'volume': 1000, 'amount': 10100,
        })
        with mock.patch.dict(os.environ, {
            'KRONOS_LOOKBACK': '90',
            'KRONOS_REJECT_STALE_HISTORY': '1',
        }, clear=False), \
                mock.patch('quantia.core.backtest.data_feed.load_stock_data',
                           return_value=frame), \
                mock.patch.object(kh, '_completed_daily_cutoff',
                                  return_value=datetime.date(2026, 7, 10)):
            with self.assertRaisesRegex(ValueError, '本地历史已过期'):
                kh._prepare_local_payload('300308', 3)

    def test_unsupported_prediction_horizon_is_rejected(self):
        env = {
            'QUANTIA_KPRED_PROVIDER': 'local',
            'QUANTIA_KPRED_MAX_DAYS': '30',
            'QUANTIA_KPRED_HORIZONS': '1,3,5,10,15,30',
        }
        with mock.patch.dict(os.environ, env, clear=False), \
             mock.patch.object(kh, '_prepare_local_payload') as prepare:
            response = self._post({'code': '300308', 'days': 20})

        self.assertEqual(response.code, 400)
        self.assertEqual(json.loads(response.body)['supported_horizons'], [1, 3, 5, 10, 15, 30])
        prepare.assert_not_called()

    def test_invalid_provider_response_returns_502_and_is_not_cached(self):
        env = {'QUANTIA_KPRED_PROVIDER': 'local'}
        with mock.patch.dict(os.environ, env, clear=False), \
             mock.patch.object(kh, '_prepare_local_payload', return_value={
                 'code': '300308', 'days': 5, 'history': [], 'future_timestamps': [],
             }), \
             mock.patch.object(kh, '_do_provider_request', return_value={'code': 0, 'data': {}}):
            response = self._post({'code': '300308', 'days': 5})

        body = json.loads(response.body)
        self.assertEqual(response.code, 502)
        self.assertIn('predictions', body['msg'])
        self.assertEqual(kh._pred_cache, {})

    def test_local_cache_context_changes_when_history_is_corrected(self):
        payload = {
            'history': [{'date': '2026-07-10', 'close': 10.0}],
            'future_timestamps': ['2026-07-13'],
        }
        with mock.patch.dict(os.environ, {'KRONOS_LOOKBACK': '256'}, clear=False):
            first = kh._cache_context('local', payload)
            payload['history'][0]['close'] = 10.1
            corrected = kh._cache_context('local', payload)
            os.environ['KRONOS_LOOKBACK'] = '90'
            changed_lookback = kh._cache_context('local', payload)

        self.assertNotEqual(first, corrected)
        self.assertNotEqual(corrected, changed_lookback)

    @gen_test
    async def test_concurrent_identical_requests_use_singleflight(self):
        env = {'QUANTIA_KPRED_PROVIDER': 'local'}
        payload = {
            'code': '300308', 'days': 3,
            'history': [{'date': '2026-07-10', 'close': 10.0}],
            'future_timestamps': ['2026-07-13', '2026-07-14', '2026-07-15'],
        }

        def slow_request(*args):
            time.sleep(0.05)
            return _prediction_payload()

        request = HTTPRequest(
            self.get_url('/quantia/api/kpred'), method='POST',
            headers={'Content-Type': 'application/json'},
            body=json.dumps({'code': '300308', 'days': 3}),
        )
        with mock.patch.dict(os.environ, env, clear=False), \
             mock.patch.object(kh, '_prepare_local_payload', return_value=payload), \
             mock.patch.object(kh, '_do_provider_request', side_effect=slow_request) as upstream:
            responses = await asyncio.gather(*[
                self.http_client.fetch(request) for _ in range(5)
            ])

        self.assertTrue(all(response.code == 200 for response in responses))
        self.assertEqual(upstream.call_count, 1)
        self.assertEqual(
            sum(bool(json.loads(response.body).get('_singleflight')) for response in responses),
            4,
        )


if __name__ == '__main__':
    import unittest
    unittest.main()