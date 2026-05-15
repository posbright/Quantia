#!/usr/bin/env python3
"""Test backtest API with all metrics

NOTE: This test requires the web service to be running on localhost:9988.
It will be automatically skipped if the service is not available.
"""
import urllib.request, json, time, sys, unittest

strategy_code = """
def initialize(context):
    context.security = '000001'

def handle_data(context, data):
    security = context.security
    close_data = history(security, 21, 'close')
    if len(close_data) < 21:
        return
    MA5 = close_data[-5:].mean()
    MA20 = close_data.mean()
    cash = context.portfolio.available_cash
    if MA5 > MA20 and security not in context.portfolio.positions:
        order_value(security, cash * 0.95)
    elif MA5 < MA20 and security in context.portfolio.positions:
        order_target(security, 0)
"""

payload = json.dumps({
    'code': strategy_code,
    'start_date': '2024-01-01',
    'end_date': '2025-01-01',
    'initial_cash': 1000000,
    'benchmark': '000300',
}).encode()


def _check_server_available():
    """Check if the web service is reachable."""
    try:
        urllib.request.urlopen('http://localhost:9988/', timeout=3)
        return True
    except Exception:
        return False


@unittest.skipUnless(_check_server_available(), "Web service not running on localhost:9988")
class TestBacktestMetrics(unittest.TestCase):
    """Integration test for portfolio backtest API with full metrics."""

    @classmethod
    def setUpClass(cls):
        req = urllib.request.Request(
            'http://localhost:9988/quantia/api/backtest/portfolio/run',
            data=payload, headers={'Content-Type': 'application/json'}
        )
        t0 = time.time()
        resp = urllib.request.urlopen(req, timeout=120)
        cls.result = json.loads(resp.read())
        cls.elapsed = time.time() - t0
        cls.data = cls.result.get('data', {})
        cls.metrics = cls.data.get('metrics', {})

    def test_status_ok(self):
        self.assertIn(self.data.get('status'), ('success', 'completed'))

    def test_has_metrics(self):
        self.assertGreater(len(self.metrics), 0)

    def test_benchmark_return_nonzero(self):
        bm_ret = self.metrics.get('benchmark_return', 0)
        self.assertNotAlmostEqual(abs(bm_ret), 0, places=1,
                                  msg="基准收益为 0 — 基准数据加载失败!")

    def test_has_nav_data(self):
        nav = self.data.get('nav', [])
        self.assertGreater(len(nav), 0)

    def test_has_trade_records(self):
        trades = self.data.get('trades', [])
        self.assertGreater(len(trades), 0)

    def test_detail_api(self):
        bt_id = self.data.get('backtest_id')
        if not bt_id:
            self.skipTest("No backtest_id returned")
        detail_resp = urllib.request.urlopen(
            f'http://localhost:9988/quantia/api/backtest/portfolio/detail?id={bt_id}',
            timeout=30
        )
        detail = json.loads(detail_resp.read())
        dm = detail.get('data', {}).get('metrics', {})
        self.assertGreater(len(dm), 0)


if __name__ == '__main__':
    unittest.main()
