#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M4 验收单测：GetPortfolioBacktestDetailHandler 暴露 error_message。"""

import json
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tornado.testing import AsyncHTTPTestCase
from tornado.web import Application

from quantia.web import portfolioBacktestHandler as pbh


def _build_row(status='failed', error_message=''):
    return [(
        7, 42, '布林带下轨抄底',
        '2024-01-01', '2024-12-31',
        100000.0,
        status,
        0, 0, 0, 0, 0, 0, 0, 0,
        None,
        json.dumps({'metrics': {}, 'nav': [], 'trades': [], 'positions': [],
                    'logs': [], 'params': {}}),
        '000300',
        error_message,
    )]


def _make_app():
    return Application([
        (r'/api/backtest/portfolio/detail', pbh.GetPortfolioBacktestDetailHandler),
    ])


class M4DetailErrorMessageTests(AsyncHTTPTestCase):
    def get_app(self):
        return _make_app()

    def test_failed_backtest_returns_error_message(self):
        rows = _build_row(status='failed',
                          error_message='ZeroDivisionError: division by zero')
        with mock.patch.object(pbh, '_ensure_backtest_table', lambda: None), \
             mock.patch.object(pbh.mdb, 'executeSqlFetch', return_value=rows):
            resp = self.fetch('/api/backtest/portfolio/detail?id=7')
        body = json.loads(resp.body)
        self.assertEqual(body['code'], 0, body)
        self.assertEqual(body['data']['status'], 'failed')
        self.assertEqual(body['data']['error_message'],
                         'ZeroDivisionError: division by zero')

    def test_completed_backtest_error_message_empty(self):
        rows = _build_row(status='completed', error_message=None)
        with mock.patch.object(pbh, '_ensure_backtest_table', lambda: None), \
             mock.patch.object(pbh.mdb, 'executeSqlFetch', return_value=rows):
            resp = self.fetch('/api/backtest/portfolio/detail?id=7')
        body = json.loads(resp.body)
        self.assertEqual(body['code'], 0)
        self.assertEqual(body['data']['error_message'], '')


if __name__ == '__main__':
    import unittest
    unittest.main()

