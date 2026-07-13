#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""K 线预测 provider、响应归一化与 Handler 契约测试。"""

import json
import os
from unittest import mock

from tornado.testing import AsyncHTTPTestCase
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
             mock.patch.object(kh, '_do_provider_request', return_value=_prediction_payload()) as request:
            response = self._post({'code': '300308', 'days': 3})

        body = json.loads(response.body)
        self.assertEqual(response.code, 200)
        self.assertEqual(body['data']['provider'], 'local')
        self.assertEqual(request.call_args.args[0], env['QUANTIA_KPRED_LOCAL_URL'])
        self.assertEqual(request.call_args.args[1], '')

    def test_invalid_provider_response_returns_502_and_is_not_cached(self):
        env = {'QUANTIA_KPRED_PROVIDER': 'local'}
        with mock.patch.dict(os.environ, env, clear=False), \
             mock.patch.object(kh, '_do_provider_request', return_value={'code': 0, 'data': {}}):
            response = self._post({'code': '300308', 'days': 5})

        body = json.loads(response.body)
        self.assertEqual(response.code, 502)
        self.assertIn('predictions', body['msg'])
        self.assertEqual(kh._pred_cache, {})


if __name__ == '__main__':
    import unittest
    unittest.main()