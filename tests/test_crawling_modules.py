#!/usr/bin/env python
# -*- coding:utf-8 -*-
"""
Comprehensive tests for quantia/core/crawling/ modules.
All HTTP calls are mocked — no network access required.
"""
import sys
import os
import json
import datetime
import unittest
from unittest.mock import patch, MagicMock, PropertyMock, call

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# ---------------------------------------------------------------------------
# Disable crawl delays globally so tests don't sleep
# ---------------------------------------------------------------------------
os.environ['QUANTIA_CRAWL_DELAY_ENABLED'] = '0'


# ═══════════════════════════════════════════════════════════════════════════
# 1. stock_hist_em
# ═══════════════════════════════════════════════════════════════════════════
class TestStockHistEM(unittest.TestCase):
    """Tests for quantia.core.crawling.stock_hist_em"""

    def _import(self):
        from quantia.core.crawling import stock_hist_em
        return stock_hist_em

    # -- _CodeIdMapProxy -------------------------------------------------
    def test_code_id_map_proxy_getitem_sh(self):
        mod = self._import()
        proxy = mod._CodeIdMapProxy()
        self.assertEqual(proxy['600000'], 1)  # 上交所
        self.assertEqual(proxy['510050'], 1)  # 沪ETF

    def test_code_id_map_proxy_getitem_sz(self):
        mod = self._import()
        proxy = mod._CodeIdMapProxy()
        self.assertEqual(proxy['000001'], 0)
        self.assertEqual(proxy['300001'], 0)
        self.assertEqual(proxy['159001'], 0)  # 深ETF

    def test_code_id_map_proxy_getitem_bj(self):
        mod = self._import()
        proxy = mod._CodeIdMapProxy()
        self.assertEqual(proxy['430001'], 0)
        self.assertEqual(proxy['830001'], 0)
        self.assertEqual(proxy['870001'], 0)
        self.assertEqual(proxy['880001'], 0)
        self.assertEqual(proxy['920819'], 0)

    def test_code_id_map_proxy_contains(self):
        mod = self._import()
        proxy = mod._CodeIdMapProxy()
        self.assertIn('600000', proxy)
        self.assertNotIn('ABC', proxy)
        self.assertNotIn('12345', proxy)   # only 5 digits
        self.assertNotIn(123456, proxy)     # not string

    def test_code_id_map_proxy_get_default(self):
        mod = self._import()
        proxy = mod._CodeIdMapProxy()
        self.assertEqual(proxy.get('600000'), 1)
        self.assertIsNone(proxy.get('XXXXXX'))
        self.assertEqual(proxy.get('XXXXXX', -1), -1)

    def test_code_id_map_proxy_unknown_prefix(self):
        mod = self._import()
        proxy = mod._CodeIdMapProxy()
        with self.assertRaises(KeyError):
            _ = proxy['700000']

    def test_code_id_map_em_returns_proxy(self):
        mod = self._import()
        result = mod.code_id_map_em()
        self.assertIsInstance(result, mod._CodeIdMapProxy)

    # -- stock_zh_a_hist with mock ---------------------------------------
    @patch('quantia.core.crawling.stock_hist_em.fetcher')
    def test_stock_zh_a_hist_columns(self, mock_fetcher):
        mod = self._import()
        # Simulate EastMoney kline API response
        klines = [
            "2024-01-02,10.00,10.50,10.80,9.90,100000,1050000,8.91,4.95,0.50,1.20",
            "2024-01-03,10.50,10.30,10.60,10.20,80000,840000,3.81,-1.90,-0.20,0.90",
        ]
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": {
                "klines": klines,
                "code": "000001",
                "name": "平安银行",
            }
        }
        mock_fetcher.make_request.return_value = mock_resp

        df = mod.stock_zh_a_hist(symbol="000001", period="daily",
                                 start_date="20240101", end_date="20240110")
        expected_cols = ["日期", "开盘", "收盘", "最高", "最低",
                         "成交量", "成交额", "振幅", "涨跌幅", "涨跌额", "换手率"]
        self.assertEqual(list(df.columns), expected_cols)
        self.assertEqual(len(df), 2)
        self.assertAlmostEqual(df.iloc[0]["开盘"], 10.0)

    @patch('quantia.core.crawling.stock_hist_em.fetcher')
    def test_stock_zh_a_hist_empty_klines(self, mock_fetcher):
        mod = self._import()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": {"klines": []}}
        mock_fetcher.make_request.return_value = mock_resp

        df = mod.stock_zh_a_hist(symbol="000001")
        self.assertTrue(df.empty)

    @patch('quantia.core.crawling.stock_hist_em.fetcher')
    def test_stock_zh_a_hist_none_data(self, mock_fetcher):
        mod = self._import()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": None}
        mock_fetcher.make_request.return_value = mock_resp

        df = mod.stock_zh_a_hist(symbol="000001")
        self.assertTrue(df.empty)

    # -- stock_zh_a_spot_em with mock ------------------------------------
    @patch('quantia.core.crawling.stock_hist_em.fetcher')
    def test_stock_zh_a_spot_em_columns(self, mock_fetcher):
        mod = self._import()
        row = {
            "f2": 10.5, "f3": 1.5, "f4": 0.15, "f5": 100000, "f6": 1050000,
            "f7": 3.0, "f8": 1.2, "f9": 15.0, "f10": 1.1, "f11": 0.5,
            "f12": "000001", "f14": "平安银行", "f15": 10.8, "f16": 10.2,
            "f17": 10.3, "f18": 10.35, "f20": 200000000000, "f21": 180000000000,
            "f22": 0.3, "f23": 1.0, "f24": 5.0, "f25": 8.0, "f26": "20000101",
            "f37": 20.0, "f38": 19000000000, "f39": 5000000000, "f40": 50000000000,
            "f41": 5.0, "f45": 3000000000, "f46": 6.0, "f48": 1.5, "f49": 10.0,
            "f57": 2.0, "f61": 30.0, "f100": "银行",
            "f112": 2.5, "f113": 2.0, "f114": 10.0, "f115": 9.5, "f221": "20231231",
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": {"diff": [row], "total": 1}}
        mock_fetcher.make_request.return_value = mock_resp

        df = mod.stock_zh_a_spot_em()
        self.assertIn("代码", df.columns)
        self.assertIn("名称", df.columns)
        self.assertIn("最新价", df.columns)
        self.assertIn("所处行业", df.columns)
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]["代码"], "000001")

    @patch('quantia.core.crawling.stock_hist_em.fetcher')
    def test_stock_zh_a_spot_em_empty(self, mock_fetcher):
        mod = self._import()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": {"diff": [], "total": 0}}
        mock_fetcher.make_request.return_value = mock_resp

        df = mod.stock_zh_a_spot_em()
        self.assertTrue(df.empty)


# ═══════════════════════════════════════════════════════════════════════════
# 2. stock_hist_sina
# ═══════════════════════════════════════════════════════════════════════════
class TestStockHistSina(unittest.TestCase):
    """Tests for quantia.core.crawling.stock_hist_sina"""

    def _import(self):
        from quantia.core.crawling import stock_hist_sina
        return stock_hist_sina

    def test_get_market_prefix_sh(self):
        mod = self._import()
        self.assertEqual(mod._get_market_prefix('600000'), 'sh')
        self.assertEqual(mod._get_market_prefix('510050'), 'sh')
        self.assertEqual(mod._get_market_prefix('900001'), 'sh')

    def test_get_market_prefix_sz(self):
        mod = self._import()
        self.assertEqual(mod._get_market_prefix('000001'), 'sz')
        self.assertEqual(mod._get_market_prefix('300001'), 'sz')
        self.assertEqual(mod._get_market_prefix('159001'), 'sz')

    def test_get_market_prefix_bj(self):
        mod = self._import()
        self.assertEqual(mod._get_market_prefix('430001'), 'bj')
        self.assertEqual(mod._get_market_prefix('830001'), 'bj')
        self.assertEqual(mod._get_market_prefix('870001'), 'bj')
        self.assertEqual(mod._get_market_prefix('880001'), 'bj')
        self.assertEqual(mod._get_market_prefix('920819'), 'bj')

    def test_safe_float_normal(self):
        mod = self._import()
        self.assertEqual(mod._safe_float('3.14'), 3.14)
        self.assertEqual(mod._safe_float(42), 42.0)

    def test_safe_float_edge(self):
        mod = self._import()
        self.assertEqual(mod._safe_float(None), 0.0)
        self.assertEqual(mod._safe_float(''), 0.0)
        self.assertEqual(mod._safe_float('-'), 0.0)
        self.assertEqual(mod._safe_float('abc'), 0.0)

    def test_convert_adjust_type(self):
        mod = self._import()
        self.assertEqual(mod._convert_adjust_type('hfq'), 'hfq')
        self.assertEqual(mod._convert_adjust_type('qfq'), 'qfq')
        self.assertEqual(mod._convert_adjust_type(''), '')
        self.assertEqual(mod._convert_adjust_type('other'), '')

    @patch('quantia.core.crawling.stock_hist_sina.requests.get')
    def test_stock_zh_a_hist_sina_success(self, mock_get):
        mod = self._import()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = [
            {"day": "2024-01-02", "open": "10.00", "high": "10.50",
             "low": "9.80", "close": "10.30", "volume": "5000000"},
            {"day": "2024-01-03", "open": "10.30", "high": "10.60",
             "low": "10.10", "close": "10.50", "volume": "4200000"},
        ]
        mock_get.return_value = mock_resp

        df = mod.stock_zh_a_hist_sina(
            symbol="000001", start_date="20240101", end_date="20240110")
        self.assertIsNotNone(df)
        self.assertIn('date', df.columns)
        self.assertIn('open', df.columns)
        self.assertIn('close', df.columns)
        self.assertIn('volume', df.columns)
        self.assertIn('amount', df.columns)
        self.assertIn('amplitude', df.columns)
        self.assertIn('quote_change', df.columns)
        self.assertIn('ups_downs', df.columns)
        self.assertIn('turnover', df.columns)

    @patch('quantia.core.crawling.stock_hist_sina.requests.get')
    def test_stock_zh_a_hist_sina_empty(self, mock_get):
        mod = self._import()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = []
        mock_get.return_value = mock_resp

        result = mod.stock_zh_a_hist_sina(symbol="000001")
        self.assertIsNone(result)

    @patch('quantia.core.crawling.stock_hist_sina.requests.get')
    def test_stock_zh_a_hist_sina_network_error(self, mock_get):
        mod = self._import()
        import requests as req_lib
        mock_get.side_effect = req_lib.exceptions.ConnectionError("Network error")
        result = mod.stock_zh_a_hist_sina(symbol="000001")
        self.assertIsNone(result)


# ═══════════════════════════════════════════════════════════════════════════
# 3. stock_hist_tencent
# ═══════════════════════════════════════════════════════════════════════════
class TestStockHistTencent(unittest.TestCase):
    """Tests for quantia.core.crawling.stock_hist_tencent"""

    def _import(self):
        from quantia.core.crawling import stock_hist_tencent
        return stock_hist_tencent

    def test_get_market_prefix(self):
        mod = self._import()
        self.assertEqual(mod._get_market_prefix('600000'), 'sh')
        self.assertEqual(mod._get_market_prefix('000001'), 'sz')
        self.assertEqual(mod._get_market_prefix('300001'), 'sz')
        self.assertEqual(mod._get_market_prefix('510050'), 'sh')
        self.assertEqual(mod._get_market_prefix('430001'), 'bj')
        self.assertEqual(mod._get_market_prefix('830001'), 'bj')
        self.assertEqual(mod._get_market_prefix('870001'), 'bj')
        self.assertEqual(mod._get_market_prefix('880001'), 'bj')
        self.assertEqual(mod._get_market_prefix('920819'), 'bj')

    def test_safe_float(self):
        mod = self._import()
        self.assertEqual(mod._safe_float('1.23'), 1.23)
        self.assertEqual(mod._safe_float(None), 0.0)
        self.assertEqual(mod._safe_float(''), 0.0)
        self.assertEqual(mod._safe_float('-'), 0.0)

    def test_convert_fq_type(self):
        mod = self._import()
        self.assertEqual(mod._convert_fq_type('qfq'), 'qfq')
        self.assertEqual(mod._convert_fq_type('hfq'), 'hfq')
        self.assertEqual(mod._convert_fq_type(''), '')
        self.assertEqual(mod._convert_fq_type('other'), '')

    def test_get_kline_key(self):
        mod = self._import()
        self.assertEqual(mod._get_kline_key('qfq'), 'qfqday')
        self.assertEqual(mod._get_kline_key('hfq'), 'hfqday')
        self.assertEqual(mod._get_kline_key(''), 'day')

    @patch('quantia.core.crawling.stock_hist_tencent.requests.get')
    def test_fetch_one_batch_success(self, mock_get):
        mod = self._import()
        kline_data = [
            ['2024-01-02', '10.00', '10.30', '10.50', '9.80', '4210.000'],
            ['2024-01-03', '10.30', '10.50', '10.60', '10.10', '3800.000'],
        ]
        json_body = {"code": 0, "data": {"sz000001": {"qfqday": kline_data}}}
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = f'kline_dayqfq={json.dumps(json_body)}'
        mock_get.return_value = mock_resp

        result = mod._fetch_one_batch("sz000001", "qfq", "qfqday",
                                      "2024-01-01", "2024-01-10", 300)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0][0], '2024-01-02')

    @patch('quantia.core.crawling.stock_hist_tencent.requests.get')
    def test_fetch_one_batch_failure(self, mock_get):
        mod = self._import()
        mock_get.side_effect = Exception("timeout")
        result = mod._fetch_one_batch("sz000001", "", "day",
                                      "2024-01-01", "2024-01-10", 300)
        self.assertIsNone(result)

    @patch('quantia.core.crawling.stock_hist_tencent._fetch_one_batch')
    def test_stock_zh_a_hist_tencent_columns(self, mock_fetch):
        mod = self._import()
        mock_fetch.return_value = [
            ['2024-01-02', '10.00', '10.30', '10.50', '9.80', '4210.000'],
            ['2024-01-03', '10.30', '10.50', '10.60', '10.10', '3800.000'],
        ]
        df = mod.stock_zh_a_hist_tencent(
            symbol="000001", start_date="20240101", end_date="20240110")
        self.assertIsNotNone(df)
        expected = ['date', 'open', 'close', 'high', 'low', 'volume',
                    'amount', 'amplitude', 'quote_change', 'ups_downs', 'turnover']
        self.assertEqual(list(df.columns), expected)

    @patch('quantia.core.crawling.stock_hist_tencent._fetch_one_batch')
    def test_stock_zh_a_hist_tencent_empty(self, mock_fetch):
        mod = self._import()
        mock_fetch.return_value = None
        result = mod.stock_zh_a_hist_tencent(symbol="000001")
        self.assertIsNone(result)

    @patch('quantia.core.crawling.stock_hist_tencent._fetch_one_batch')
    def test_stock_zh_a_hist_tencent_strips_dividend_cols(self, mock_fetch):
        """Rows with 7+ columns (dividend info) should be truncated to 6."""
        mod = self._import()
        mock_fetch.return_value = [
            ['2024-01-02', '10.00', '10.30', '10.50', '9.80', '4210.000',
             {'nd': '2024', 'fh_sh': '1.2'}],
        ]
        df = mod.stock_zh_a_hist_tencent(
            symbol="000001", start_date="20240101", end_date="20240110")
        self.assertIsNotNone(df)
        self.assertEqual(len(df), 1)


# ═══════════════════════════════════════════════════════════════════════════
# 4. stock_sina (spot)
# ═══════════════════════════════════════════════════════════════════════════
class TestStockSina(unittest.TestCase):
    """Tests for quantia.core.crawling.stock_sina"""

    def _import(self):
        from quantia.core.crawling import stock_sina
        return stock_sina

    def test_get_stock_codes_not_empty(self):
        mod = self._import()
        codes = mod._get_stock_codes()
        self.assertGreater(len(codes), 0)
        self.assertTrue(codes[0].startswith('sh') or codes[0].startswith('sz'))

    def test_safe_float(self):
        mod = self._import()
        self.assertEqual(mod._safe_float('10.5'), 10.5)
        self.assertEqual(mod._safe_float(None), 0.0)
        self.assertEqual(mod._safe_float('-'), 0.0)

    def test_safe_int(self):
        mod = self._import()
        self.assertEqual(mod._safe_int('12345'), 12345)
        self.assertEqual(mod._safe_int('12345.6'), 12345)
        self.assertEqual(mod._safe_int(None), 0)
        self.assertEqual(mod._safe_int('-'), 0)

    def test_parse_sina_data_valid(self):
        mod = self._import()
        # Minimal 32-field Sina line
        fields = ['浦发银行', '10.10', '10.12', '10.07', '10.15', '10.00',
                  '10.06', '10.07'] + ['100'] * 22 + ['2024-01-02', '15:00:00']
        line = f'var hq_str_sh600000="{",".join(fields)}";'
        result = mod._parse_sina_data(line)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['代码'], '600000')
        self.assertEqual(result[0]['名称'], '浦发银行')

    def test_parse_sina_data_empty_price(self):
        mod = self._import()
        fields = ['银行', '0', '0', '0.00', '0', '0', '0', '0'] + ['0'] * 22 + ['', '']
        line = f'var hq_str_sh600000="{",".join(fields)}";'
        result = mod._parse_sina_data(line)
        self.assertEqual(len(result), 0)  # skipped because price == 0.00

    def test_parse_sina_data_empty_string(self):
        mod = self._import()
        result = mod._parse_sina_data('')
        self.assertEqual(len(result), 0)

    def test_parse_sina_data_malformed(self):
        mod = self._import()
        result = mod._parse_sina_data('garbage data without hq_str')
        self.assertEqual(len(result), 0)


# ═══════════════════════════════════════════════════════════════════════════
# 5. stock_tencent (spot)
# ═══════════════════════════════════════════════════════════════════════════
class TestStockTencent(unittest.TestCase):
    """Tests for quantia.core.crawling.stock_tencent"""

    def _import(self):
        from quantia.core.crawling import stock_tencent
        return stock_tencent

    def test_get_stock_codes(self):
        mod = self._import()
        codes = mod._get_stock_codes()
        self.assertGreater(len(codes), 0)

    def test_safe_float(self):
        mod = self._import()
        self.assertEqual(mod._safe_float('10.5'), 10.5)
        self.assertEqual(mod._safe_float(None), 0.0)

    def test_safe_int(self):
        mod = self._import()
        self.assertEqual(mod._safe_int('100'), 100)
        self.assertEqual(mod._safe_int(None), 0)

    def test_parse_tencent_data_valid(self):
        mod = self._import()
        # Build a minimal 51-field Tencent data line
        parts = [''] * 51
        parts[1] = '浦发银行'
        parts[2] = '600000'
        parts[3] = '10.07'
        parts[4] = '10.12'   # 昨收
        parts[5] = '10.10'   # 今开
        parts[31] = '-0.05'  # 涨跌额
        parts[32] = '-0.49'  # 涨跌幅
        parts[33] = '10.15'  # 最高
        parts[34] = '10.00'  # 最低
        parts[36] = '50000'  # 成交量(手)
        parts[37] = '5050.0' # 成交额(万)
        parts[38] = '1.2'    # 换手率
        parts[39] = '5.0'    # 市盈率
        parts[43] = '1.5'    # 振幅
        parts[44] = '1800.0' # 流通市值(亿→万)
        parts[45] = '2000.0' # 总市值(亿→万)
        parts[46] = '0.8'    # 市净率
        text = f"v_sh600000=\"{'~'.join(parts)}\";"
        result = mod._parse_tencent_data(text)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['代码'], '600000')

    def test_parse_tencent_data_empty(self):
        mod = self._import()
        result = mod._parse_tencent_data('')
        self.assertEqual(len(result), 0)

    def test_parse_tencent_data_no_price(self):
        mod = self._import()
        parts = [''] * 51
        parts[1] = 'TestName'
        parts[2] = '600000'
        parts[3] = '0.00'
        text = f"v_sh600000=\"{'~'.join(parts)}\";"
        result = mod._parse_tencent_data(text)
        self.assertEqual(len(result), 0)


# ═══════════════════════════════════════════════════════════════════════════
# 6. fund_etf_em
# ═══════════════════════════════════════════════════════════════════════════
class TestFundEtfEM(unittest.TestCase):
    """Tests for quantia.core.crawling.fund_etf_em"""

    def _import(self):
        from quantia.core.crawling import fund_etf_em
        return fund_etf_em

    @patch('quantia.core.crawling.fund_etf_em.fetcher')
    def test_fund_etf_spot_em_columns(self, mock_fetcher):
        mod = self._import()
        row = {
            "f12": "510050", "f14": "50ETF", "f2": 3.5, "f3": 1.2,
            "f4": 0.04, "f5": 500000, "f6": 1750000,
            "f17": 3.48, "f15": 3.55, "f16": 3.45, "f18": 3.46,
            "f8": 0.5, "f21": 100000000, "f20": 150000000,
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": {"diff": [row], "total": 1}}
        mock_fetcher.make_request.return_value = mock_resp

        df = mod.fund_etf_spot_em()
        expected_cols = ["代码", "名称", "最新价", "涨跌幅", "涨跌额", "成交量",
                         "成交额", "开盘价", "最高价", "最低价", "昨收", "换手率",
                         "总市值", "流通市值"]
        self.assertEqual(list(df.columns), expected_cols)
        self.assertEqual(df.iloc[0]["代码"], "510050")

    @patch('quantia.core.crawling.fund_etf_em.fetcher')
    def test_fund_etf_spot_em_empty(self, mock_fetcher):
        mod = self._import()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": {"diff": [], "total": 0}}
        mock_fetcher.make_request.return_value = mock_resp

        df = mod.fund_etf_spot_em()
        self.assertTrue(df.empty)

    @patch('quantia.core.crawling.fund_etf_em._fund_etf_code_id_map_em')
    @patch('quantia.core.crawling.fund_etf_em.fetcher')
    def test_fund_etf_hist_em_columns(self, mock_fetcher, mock_code_map):
        mod = self._import()
        mock_code_map.return_value = {"159707": 0}
        klines = [
            "2024-01-02,1.00,1.05,1.08,0.99,100000,105000,9.0,5.0,0.05,1.2",
        ]
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": {"klines": klines}}
        mock_fetcher.make_request.return_value = mock_resp

        df = mod.fund_etf_hist_em(symbol="159707")
        expected_cols = ["日期", "开盘", "收盘", "最高", "最低",
                         "成交量", "成交额", "振幅", "涨跌幅", "涨跌额", "换手率"]
        self.assertEqual(list(df.columns), expected_cols)

    @patch('quantia.core.crawling.fund_etf_em._fund_etf_code_id_map_em')
    @patch('quantia.core.crawling.fund_etf_em.fetcher')
    def test_fund_etf_hist_em_empty(self, mock_fetcher, mock_code_map):
        mod = self._import()
        mock_code_map.return_value = {"159707": 0}
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": None}
        mock_fetcher.make_request.return_value = mock_resp

        df = mod.fund_etf_hist_em(symbol="159707")
        self.assertTrue(df.empty)


# ═══════════════════════════════════════════════════════════════════════════
# 7. etf_sina
# ═══════════════════════════════════════════════════════════════════════════
class TestEtfSina(unittest.TestCase):
    """Tests for quantia.core.crawling.etf_sina"""

    def _import(self):
        from quantia.core.crawling import etf_sina
        return etf_sina

    def test_get_etf_codes(self):
        mod = self._import()
        codes = mod._get_etf_codes()
        self.assertGreater(len(codes), 0)
        # Should include sh510xxx and sz159xxx
        self.assertTrue(any(c.startswith('sh510') for c in codes))
        self.assertTrue(any(c.startswith('sz159') for c in codes))

    def test_safe_float(self):
        mod = self._import()
        self.assertEqual(mod._safe_float('3.5'), 3.5)
        self.assertEqual(mod._safe_float(None), 0.0)

    def test_safe_int(self):
        mod = self._import()
        self.assertEqual(mod._safe_int('100'), 100)
        self.assertEqual(mod._safe_int(None), 0)

    def test_parse_sina_etf_data_valid(self):
        mod = self._import()
        fields = ['50ETF', '3.500', '3.508', '3.502', '3.515', '3.495',
                  '3.501', '3.502'] + ['100'] * 22 + ['2024-01-02', '15:00:00']
        line = f'var hq_str_sh510050="{",".join(fields)}";'
        result = mod._parse_sina_etf_data(line)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['代码'], '510050')

    def test_parse_sina_etf_data_empty(self):
        mod = self._import()
        result = mod._parse_sina_etf_data('')
        self.assertEqual(len(result), 0)


# ═══════════════════════════════════════════════════════════════════════════
# 8. etf_tencent
# ═══════════════════════════════════════════════════════════════════════════
class TestEtfTencent(unittest.TestCase):
    """Tests for quantia.core.crawling.etf_tencent"""

    def _import(self):
        from quantia.core.crawling import etf_tencent
        return etf_tencent

    def test_get_etf_codes(self):
        mod = self._import()
        codes = mod._get_etf_codes()
        self.assertGreater(len(codes), 0)

    def test_safe_float(self):
        mod = self._import()
        self.assertEqual(mod._safe_float('3.14'), 3.14)
        self.assertEqual(mod._safe_float(None), 0.0)

    def test_safe_int(self):
        mod = self._import()
        self.assertEqual(mod._safe_int('42'), 42)
        self.assertEqual(mod._safe_int(None), 0)

    def test_parse_tencent_etf_data_valid(self):
        mod = self._import()
        parts = [''] * 51
        parts[1] = '50ETF'
        parts[2] = '510050'
        parts[3] = '3.502'
        parts[4] = '3.508'   # 昨收
        parts[5] = '3.500'   # 今开
        parts[31] = '-0.006'
        parts[32] = '-0.17'
        parts[33] = '3.515'
        parts[34] = '3.495'
        parts[36] = '10000'
        parts[37] = '3502'
        parts[38] = '0.5'
        parts[44] = '100.0'
        parts[45] = '120.0'
        text = f"v_sh510050=\"{'~'.join(parts)}\";"
        result = mod._parse_tencent_etf_data(text)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['代码'], '510050')

    def test_parse_tencent_etf_data_empty(self):
        mod = self._import()
        result = mod._parse_tencent_etf_data('')
        self.assertEqual(len(result), 0)


# ═══════════════════════════════════════════════════════════════════════════
# 9. stock_index_em
# ═══════════════════════════════════════════════════════════════════════════
class TestStockIndexEM(unittest.TestCase):
    """Tests for quantia.core.crawling.stock_index_em"""

    def _import(self):
        from quantia.core.crawling import stock_index_em
        return stock_index_em

    def test_get_index_market_id(self):
        mod = self._import()
        self.assertEqual(mod._get_index_market_id('000300'), 1)
        self.assertEqual(mod._get_index_market_id('000001'), 1)
        self.assertEqual(mod._get_index_market_id('399001'), 0)
        self.assertEqual(mod._get_index_market_id('399006'), 0)

    @patch('quantia.core.crawling.stock_index_em.fetcher')
    def test_stock_index_spot_em_columns(self, mock_fetcher):
        mod = self._import()
        row = {
            "f12": "000300", "f14": "沪深300", "f2": 3800.0, "f3": 0.5,
            "f4": 19.0, "f5": 200000000, "f6": 400000000000,
            "f17": 3790.0, "f15": 3820.0, "f16": 3780.0, "f18": 3781.0,
            "f8": 0.8, "f21": 30000000000000, "f20": 50000000000000,
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": {"diff": [row], "total": 1}}
        mock_fetcher.make_request.return_value = mock_resp

        df = mod.stock_index_spot_em()
        self.assertIn("代码", df.columns)
        self.assertIn("名称", df.columns)
        self.assertEqual(len(df), 1)

    @patch('quantia.core.crawling.stock_index_em.fetcher')
    def test_stock_index_spot_em_empty(self, mock_fetcher):
        mod = self._import()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": None}
        mock_fetcher.make_request.return_value = mock_resp

        df = mod.stock_index_spot_em()
        self.assertTrue(df.empty)

    @patch('quantia.core.crawling.stock_index_em.fetcher')
    def test_stock_index_hist_em_columns(self, mock_fetcher):
        mod = self._import()
        klines = [
            "2024-01-02,3790.00,3800.00,3820.00,3780.00,200000000,400000000000,1.05,0.50,19.00,0.80",
        ]
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": {"klines": klines}}
        mock_fetcher.make_request.return_value = mock_resp

        df = mod.stock_index_hist_em(symbol="000300")
        expected_cols = ["日期", "开盘", "收盘", "最高", "最低",
                         "成交量", "成交额", "振幅", "涨跌幅", "涨跌额", "换手率"]
        self.assertEqual(list(df.columns), expected_cols)

    @patch('quantia.core.crawling.stock_index_em.fetcher')
    def test_stock_index_hist_em_empty(self, mock_fetcher):
        mod = self._import()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": None}
        mock_fetcher.make_request.return_value = mock_resp

        df = mod.stock_index_hist_em(symbol="000300")
        self.assertTrue(df.empty)


# ═══════════════════════════════════════════════════════════════════════════
# 10. index_sina
# ═══════════════════════════════════════════════════════════════════════════
class TestIndexSina(unittest.TestCase):
    """Tests for quantia.core.crawling.index_sina"""

    def _import(self):
        from quantia.core.crawling import index_sina
        return index_sina

    def test_code_to_sina(self):
        mod = self._import()
        self.assertEqual(mod._code_to_sina('000001'), 'sh000001')
        self.assertEqual(mod._code_to_sina('000300'), 'sh000300')
        self.assertEqual(mod._code_to_sina('399001'), 'sz399001')

    def test_safe_float(self):
        mod = self._import()
        self.assertEqual(mod._safe_float('3260.5'), 3260.5)
        self.assertEqual(mod._safe_float(None), 0.0)

    def test_safe_int_from_float(self):
        mod = self._import()
        self.assertEqual(mod._safe_int_from_float('12345.6'), 12345)
        self.assertEqual(mod._safe_int_from_float(None), 0)

    def test_parse_sina_index_data(self):
        mod = self._import()
        fields = ['上证指数', '3260.00', '3250.00', '3265.50', '3270.00',
                  '3245.00', '0', '0', '200000', '30000000000']
        line = f'var hq_str_sh000001="{",".join(fields)}";\n'
        result = mod._parse_sina_index_data(line, ['000001'])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['代码'], '000001')
        self.assertEqual(result[0]['名称'], '上证指数')
        self.assertAlmostEqual(result[0]['最新价'], 3265.5)

    def test_parse_sina_index_data_empty(self):
        mod = self._import()
        result = mod._parse_sina_index_data('', [])
        self.assertEqual(len(result), 0)


# ═══════════════════════════════════════════════════════════════════════════
# 11. index_tencent
# ═══════════════════════════════════════════════════════════════════════════
class TestIndexTencent(unittest.TestCase):
    """Tests for quantia.core.crawling.index_tencent"""

    def _import(self):
        from quantia.core.crawling import index_tencent
        return index_tencent

    def test_code_to_tencent(self):
        mod = self._import()
        self.assertEqual(mod._code_to_tencent('000001'), 'sh000001')
        self.assertEqual(mod._code_to_tencent('399001'), 'sz399001')

    def test_safe_float(self):
        mod = self._import()
        self.assertEqual(mod._safe_float('100.5'), 100.5)
        self.assertEqual(mod._safe_float(None), 0.0)

    def test_safe_int_from_float(self):
        mod = self._import()
        self.assertEqual(mod._safe_int_from_float('100.9'), 100)
        self.assertEqual(mod._safe_int_from_float(None), 0)

    def test_parse_tencent_index_data_valid(self):
        mod = self._import()
        parts = [''] * 51
        parts[1] = '上证指数'
        parts[2] = '000001'
        parts[3] = '3265.50'
        parts[4] = '3250.00'
        parts[5] = '3260.00'
        parts[31] = '15.50'
        parts[32] = '0.48'
        parts[33] = '3270.00'
        parts[34] = '3245.00'
        parts[36] = '200000'
        parts[37] = '3000000'
        parts[38] = '0.0'
        parts[44] = '350000.0'
        parts[45] = '500000.0'
        text = f"v_sh000001=\"{'~'.join(parts)}\";"
        result = mod._parse_tencent_index_data(text)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['代码'], '000001')

    def test_parse_tencent_index_data_empty(self):
        mod = self._import()
        result = mod._parse_tencent_index_data('')
        self.assertEqual(len(result), 0)

    def test_parse_tencent_index_data_skip_invalid(self):
        mod = self._import()
        parts = [''] * 51
        parts[1] = ''       # empty name
        parts[2] = '000001'
        parts[3] = '0'      # zero price
        text = f"v_sh000001=\"{'~'.join(parts)}\";"
        result = mod._parse_tencent_index_data(text)
        self.assertEqual(len(result), 0)


# ═══════════════════════════════════════════════════════════════════════════
# 12. stock_fund_em
# ═══════════════════════════════════════════════════════════════════════════
class TestStockFundEM(unittest.TestCase):
    """Tests for quantia.core.crawling.stock_fund_em"""

    def _import(self):
        from quantia.core.crawling import stock_fund_em
        return stock_fund_em

    @patch('quantia.core.crawling.stock_fund_em._individual_fund_flow_fetch_page')
    def test_stock_individual_fund_flow_rank_today(self, mock_fetch):
        mod = self._import()
        # fields: f12,f14,f2,f3,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87,f204,f205,f124 = 17 fields
        # But the code assigns 18 column names — the API actually returns an extra field.
        # Provide 18 values to match.
        row = {
            "f2": 10.5, "f3": 1.5, "f12": "000001", "f14": "平安银行",
            "f62": 5000000, "f184": 2.5, "f66": 3000000, "f69": 1.5,
            "f72": 1000000, "f75": 0.5, "f78": -500000, "f81": -0.25,
            "f84": -2000000, "f87": -1.0, "f204": "foo", "f205": "bar",
            "f124": "x", "f64": 0,
        }
        mock_fetch.return_value = {"data": {"diff": [row], "total": 1}}

        df = mod.stock_individual_fund_flow_rank(indicator="今日")
        self.assertIn("代码", df.columns)
        self.assertIn("今日主力净流入-净额", df.columns)
        self.assertEqual(len(df), 1)

    @patch('quantia.core.crawling.stock_fund_em._individual_fund_flow_fetch_page')
    def test_stock_individual_fund_flow_rank_empty(self, mock_fetch):
        mod = self._import()
        mock_fetch.return_value = None
        df = mod.stock_individual_fund_flow_rank(indicator="今日")
        self.assertTrue(df.empty)

    @patch('quantia.core.crawling.stock_fund_em._sector_fund_flow_fetch_page')
    def test_stock_sector_fund_flow_rank_today(self, mock_fetch):
        mod = self._import()
        # fields: f12,f14,f2,f3,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87,f204,f205,f124 = 17
        # Code assigns 18 col names — add extra field
        row = {
            "f2": 1.5, "f3": 0.8, "f14": "银行",
            "f62": 8000000, "f184": 3.0,
            "f66": 5000000, "f69": 2.0,
            "f72": 2000000, "f75": 0.8,
            "f78": -1000000, "f81": -0.4,
            "f84": -3000000, "f87": -1.2,
            "f204": "平安银行", "f205": "000001",
            "f124": "y", "f12": "BK001",
            "f64": 1,
        }
        mock_fetch.return_value = {"data": {"diff": [row], "total": 1}}

        df = mod.stock_sector_fund_flow_rank(indicator="今日", sector_type="行业资金流")
        self.assertIn("名称", df.columns)
        self.assertIn("今日主力净流入-净额", df.columns)

    @patch('quantia.core.crawling.stock_fund_em._sector_fund_flow_fetch_page')
    def test_stock_sector_fund_flow_rank_empty(self, mock_fetch):
        mod = self._import()
        mock_fetch.return_value = None
        df = mod.stock_sector_fund_flow_rank(indicator="今日")
        self.assertTrue(df.empty)


# ═══════════════════════════════════════════════════════════════════════════
# 13. stock_fund_sina
# ═══════════════════════════════════════════════════════════════════════════
class TestStockFundSina(unittest.TestCase):
    """Tests for quantia.core.crawling.stock_fund_sina"""

    def _import(self):
        from quantia.core.crawling import stock_fund_sina
        return stock_fund_sina

    def test_safe_float(self):
        mod = self._import()
        self.assertEqual(mod._safe_float('1.5'), 1.5)
        self.assertEqual(mod._safe_float(None), 0.0)

    def test_safe_int(self):
        mod = self._import()
        self.assertEqual(mod._safe_int('100'), 100)
        self.assertEqual(mod._safe_int(None), 0)

    @patch('quantia.core.crawling.stock_fund_sina.proxys')
    @patch('quantia.core.crawling.stock_fund_sina.requests.get')
    def test_individual_fund_flow_rank_sina_success(self, mock_get, mock_proxys):
        mod = self._import()
        mock_proxy_inst = MagicMock()
        mock_proxy_inst.get_proxies.return_value = {}
        mock_proxys.return_value = mock_proxy_inst

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = json.dumps([
            {"symbol": "sh600000", "name": "浦发银行", "trade": "10.50",
             "changeratio": "0.015", "netamount": "5000000",
             "ratioamount": "0.025"},
        ])
        mock_get.return_value = mock_resp

        df = mod.stock_individual_fund_flow_rank_sina(indicator="今日")
        self.assertIn("代码", df.columns)
        self.assertIn("主力净流入", df.columns)
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]["代码"], "600000")

    @patch('quantia.core.crawling.stock_fund_sina.proxys')
    @patch('quantia.core.crawling.stock_fund_sina.requests.get')
    def test_individual_fund_flow_rank_sina_empty(self, mock_get, mock_proxys):
        mod = self._import()
        mock_proxy_inst = MagicMock()
        mock_proxy_inst.get_proxies.return_value = {}
        mock_proxys.return_value = mock_proxy_inst

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = 'null'
        mock_get.return_value = mock_resp

        df = mod.stock_individual_fund_flow_rank_sina()
        self.assertTrue(df.empty)

    @patch('quantia.core.crawling.stock_fund_sina.proxys')
    @patch('quantia.core.crawling.stock_fund_sina.requests.get')
    def test_sector_fund_flow_rank_sina_success(self, mock_get, mock_proxys):
        mod = self._import()
        mock_proxy_inst = MagicMock()
        mock_proxy_inst.get_proxies.return_value = {}
        mock_proxys.return_value = mock_proxy_inst

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = json.dumps([
            {"name": "银行", "avg_changeratio": "0.012",
             "netamount": "8000000", "ratioamount": "0.03",
             "ts_name": "平安银行"},
        ])
        mock_get.return_value = mock_resp

        df = mod.stock_sector_fund_flow_rank_sina(indicator="今日")
        self.assertIn("名称", df.columns)
        self.assertIn("主力净流入-净额", df.columns)
        self.assertEqual(len(df), 1)


# ═══════════════════════════════════════════════════════════════════════════
# 14. stock_dzjy_em
# ═══════════════════════════════════════════════════════════════════════════
class TestStockDzjyEM(unittest.TestCase):
    """Tests for quantia.core.crawling.stock_dzjy_em"""

    def _import(self):
        from quantia.core.crawling import stock_dzjy_em
        return stock_dzjy_em

    @patch('quantia.core.crawling.stock_dzjy_em.fetcher')
    def test_stock_dzjy_sctj_columns(self, mock_fetcher):
        mod = self._import()
        row = {
            "TRADE_DATE": "2024-01-02T00:00:00.000",
            "SZ_INDEX": 2980.0, "SZ_CHANGE_RATE": 0.5,
            "BLOCKTRADE_DEAL_AMT": 5000000000,
            "PREMIUM_DEAL_AMT": 2000000000, "PREMIUM_RATIO": 40.0,
            "DISCOUNT_DEAL_AMT": 3000000000, "DISCOUNT_RATIO": 60.0,
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"result": {"pages": 1, "data": [row]}}
        mock_fetcher.make_request.return_value = mock_resp

        df = mod.stock_dzjy_sctj()
        self.assertIn("交易日期", df.columns)
        self.assertIn("大宗交易成交总额", df.columns)
        self.assertEqual(len(df), 1)

    @patch('quantia.core.crawling.stock_dzjy_em.fetcher')
    def test_stock_dzjy_mrmx_empty(self, mock_fetcher):
        mod = self._import()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"result": {"data": []}}
        mock_fetcher.make_request.return_value = mock_resp

        df = mod.stock_dzjy_mrmx(symbol='A股', start_date='20240101', end_date='20240101')
        self.assertTrue(df.empty)

    @patch('quantia.core.crawling.stock_dzjy_em.fetcher')
    def test_stock_dzjy_mrtj_columns(self, mock_fetcher):
        mod = self._import()
        row = {
            "TRADE_DATE": "2024-01-05T00:00:00.000",
            "SECURITY_CODE": "000001", "SECUCODE": "000001.SZ",
            "SECURITY_NAME_ABBR": "平安银行",
            "CHANGE_RATE": 1.5, "CLOSE_PRICE": 10.5,
            "AVERAGE_PRICE": 10.3, "PREMIUM_RATIO": -1.9,
            "DEAL_NUM": 3, "VOLUME": 500000,
            "DEAL_AMT": 5150000, "TURNOVERRATE": 0.03,
            "D1_CLOSE_ADJCHRATE": 0.5, "D5_CLOSE_ADJCHRATE": 1.0,
            "D10_CLOSE_ADJCHRATE": 1.5, "D20_CLOSE_ADJCHRATE": 2.0,
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"result": {"data": [row]}}
        mock_fetcher.make_request.return_value = mock_resp

        df = mod.stock_dzjy_mrtj(start_date='20240105', end_date='20240105')
        self.assertIn("证券代码", df.columns)
        self.assertIn("成交总额", df.columns)


# ═══════════════════════════════════════════════════════════════════════════
# 15. stock_lhb_em
# ═══════════════════════════════════════════════════════════════════════════
class TestStockLhbEM(unittest.TestCase):
    """Tests for quantia.core.crawling.stock_lhb_em"""

    def _import(self):
        from quantia.core.crawling import stock_lhb_em
        return stock_lhb_em

    @patch('quantia.core.crawling.stock_lhb_em.fetcher')
    def test_stock_lhb_detail_em_columns(self, mock_fetcher):
        mod = self._import()
        row = {
            "SECURITY_CODE": "000001", "SECUCODE": "000001.SZ",
            "SECURITY_NAME_ABBR": "平安银行",
            "TRADE_DATE": "2024-01-02T00:00:00.000",
            "EXPLAIN": "买入", "CLOSE_PRICE": 10.5,
            "CHANGE_RATE": 2.0,
            "BILLBOARD_NET_AMT": 5000000,
            "BILLBOARD_BUY_AMT": 8000000,
            "BILLBOARD_SELL_AMT": 3000000,
            "BILLBOARD_DEAL_AMT": 11000000,
            "ACCUM_AMOUNT": 500000000,
            "DEAL_NET_RATIO": 1.0,
            "DEAL_AMOUNT_RATIO": 2.2,
            "TURNOVERRATE": 1.5,
            "FREE_MARKET_CAP": 180000000000,
            "EXPLANATION": "日涨幅偏离值达7%",
            "D1_CLOSE_ADJCHRATE": 0.5,
            "D2_CLOSE_ADJCHRATE": 1.0,
            "D5_CLOSE_ADJCHRATE": 2.0,
            "D10_CLOSE_ADJCHRATE": 3.0,
            "SECURITY_TYPE_CODE": "001",
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"result": {"pages": 1, "data": [row]}}
        mock_fetcher.make_request.return_value = mock_resp

        df = mod.stock_lhb_detail_em(start_date="20240102", end_date="20240102")
        self.assertIn("代码", df.columns)
        self.assertIn("龙虎榜净买额", df.columns)
        self.assertIn("上榜原因", df.columns)

    @patch('quantia.core.crawling.stock_lhb_em.fetcher')
    def test_stock_lhb_detail_em_single_page_no_data(self, mock_fetcher):
        """When the API returns pages=1 with a single empty row, verify graceful handling."""
        mod = self._import()
        # Return valid row but set pages=1 so only one request is made
        row = {
            "SECURITY_CODE": "999999", "SECUCODE": "999999.SZ",
            "SECURITY_NAME_ABBR": "TestEmpty",
            "TRADE_DATE": "2024-01-02T00:00:00.000",
            "EXPLAIN": "", "CLOSE_PRICE": 0,
            "CHANGE_RATE": 0,
            "BILLBOARD_NET_AMT": 0,
            "BILLBOARD_BUY_AMT": 0,
            "BILLBOARD_SELL_AMT": 0,
            "BILLBOARD_DEAL_AMT": 0,
            "ACCUM_AMOUNT": 0,
            "DEAL_NET_RATIO": 0,
            "DEAL_AMOUNT_RATIO": 0,
            "TURNOVERRATE": 0,
            "FREE_MARKET_CAP": 0,
            "EXPLANATION": "",
            "D1_CLOSE_ADJCHRATE": None,
            "D2_CLOSE_ADJCHRATE": None,
            "D5_CLOSE_ADJCHRATE": None,
            "D10_CLOSE_ADJCHRATE": None,
            "SECURITY_TYPE_CODE": "001",
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"result": {"pages": 1, "data": [row]}}
        mock_fetcher.make_request.return_value = mock_resp

        df = mod.stock_lhb_detail_em(start_date="20240102", end_date="20240102")
        self.assertIn("代码", df.columns)
        self.assertEqual(len(df), 1)


# ═══════════════════════════════════════════════════════════════════════════
# 16. stock_lhb_sina
# ═══════════════════════════════════════════════════════════════════════════
class TestStockLhbSina(unittest.TestCase):
    """Tests for quantia.core.crawling.stock_lhb_sina"""

    def _import(self):
        from quantia.core.crawling import stock_lhb_sina
        return stock_lhb_sina

    @patch('quantia.core.crawling.stock_lhb_sina._sina_request')
    def test_stock_lhb_detail_daily_empty(self, mock_req):
        mod = self._import()
        mock_resp = MagicMock()
        mock_resp.text = '<html><body></body></html>'
        mock_req.return_value = mock_resp

        df = mod.stock_lhb_detail_daily_sina(date="20240102")
        self.assertTrue(df.empty)

    @patch('quantia.core.crawling.stock_lhb_sina._sina_request')
    def test_stock_lhb_detail_daily_network_error(self, mock_req):
        mod = self._import()
        mock_req.side_effect = Exception("Network error")

        df = mod.stock_lhb_detail_daily_sina(date="20240102")
        self.assertTrue(df.empty)


# ═══════════════════════════════════════════════════════════════════════════
# 17. stock_fhps_em
# ═══════════════════════════════════════════════════════════════════════════
class TestStockFhpsEM(unittest.TestCase):
    """Tests for quantia.core.crawling.stock_fhps_em"""

    def _import(self):
        from quantia.core.crawling import stock_fhps_em
        return stock_fhps_em

    @patch('quantia.core.crawling.stock_fhps_em.fetcher')
    def test_stock_fhps_em_columns(self, mock_fetcher):
        mod = self._import()
        row = {
            "c0": "_",  "SECURITY_NAME_ABBR": "平安银行",
            "c2": "_",  "c3": "_",
            "SECURITY_CODE": "000001",
            "BONUS_IT_RATIO": 10.0,
            "IT_RATIO": 5.0,
            "TRANSFER_RATIO": 5.0,
            "PRETAX_BONUS_RMB": 3.0,
            "PLAN_NOTICE_DATE": "2024-04-01T00:00:00.000",
            "EQUITY_RECORD_DATE": "2024-05-01T00:00:00.000",
            "EX_DIVIDEND_DATE": "2024-05-02T00:00:00.000",
            "c11": "_",
            "IMPL_PLAN_PROFILE": "实施",
            "c13": "_",
            "UPDATE_DATE": "2024-03-15T00:00:00.000",
            "c15": "_", "c16": "_", "c17": "_",
            "BASIC_EPS": 2.5,
            "BVPS": 15.0,
            "PER_CAPITAL_RESERVE": 5.0,
            "PER_UNASSIGN_PROFIT": 8.0,
            "NET_PROFIT_GROWTH_RATE": 10.0,
            "TOTAL_SHARES": 19000000000,
            "c23": "_",
            "DIVIDEND_YIELD_RATIO": 2.5,
            "d1": "-", "d2": "-", "d3": "-",
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"result": {"pages": 1, "data": [row]}}
        mock_fetcher.make_request.return_value = mock_resp

        df = mod.stock_fhps_em(date="20231231")
        self.assertIn("代码", df.columns)
        self.assertIn("名称", df.columns)
        self.assertIn("现金分红-股息率", df.columns)
        self.assertIn("方案进度", df.columns)
        self.assertEqual(len(df), 1)


# ═══════════════════════════════════════════════════════════════════════════
# 18. stock_chip_race
# ═══════════════════════════════════════════════════════════════════════════
class TestStockChipRace(unittest.TestCase):
    """Tests for quantia.core.crawling.stock_chip_race"""

    def _import(self):
        from quantia.core.crawling import stock_chip_race
        return stock_chip_race

    @patch('quantia.core.crawling.stock_chip_race.proxys')
    @patch('quantia.core.crawling.stock_chip_race.requests.post')
    def test_stock_chip_race_open_columns(self, mock_post, mock_proxys):
        mod = self._import()
        mock_proxy_inst = MagicMock()
        mock_proxy_inst.get_proxies.return_value = {}
        mock_proxys.return_value = mock_proxy_inst

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "datas": [
                ["000001", "平安银行", 105000, 105500, 5000000,
                 0.005, 1000000, 800000, 10.55, 0, 3, 1]
            ]
        }
        mock_post.return_value = mock_resp

        df = mod.stock_chip_race_open()
        self.assertIn("代码", df.columns)
        self.assertIn("抢筹幅度", df.columns)
        self.assertIn("涨跌幅", df.columns)
        self.assertIn("抢筹占比", df.columns)

    @patch('quantia.core.crawling.stock_chip_race.proxys')
    @patch('quantia.core.crawling.stock_chip_race.requests.post')
    def test_stock_chip_race_open_empty(self, mock_post, mock_proxys):
        mod = self._import()
        mock_proxy_inst = MagicMock()
        mock_proxy_inst.get_proxies.return_value = {}
        mock_proxys.return_value = mock_proxy_inst

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"datas": None}
        mock_post.return_value = mock_resp

        df = mod.stock_chip_race_open()
        self.assertTrue(df.empty)

    @patch('quantia.core.crawling.stock_chip_race.proxys')
    @patch('quantia.core.crawling.stock_chip_race.requests.post')
    def test_stock_chip_race_end_columns(self, mock_post, mock_proxys):
        mod = self._import()
        mock_proxy_inst = MagicMock()
        mock_proxy_inst.get_proxies.return_value = {}
        mock_proxys.return_value = mock_proxy_inst

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "datas": [
                ["000001", "平安银行", 105000, 105500, 8000000,
                 0.003, 500000, 400000, 10.58, 0, 3, 1]
            ]
        }
        mock_post.return_value = mock_resp

        df = mod.stock_chip_race_end()
        self.assertIn("代码", df.columns)
        self.assertIn("收盘金额", df.columns)
        self.assertIn("涨跌幅", df.columns)

    @patch('quantia.core.crawling.stock_chip_race.proxys')
    @patch('quantia.core.crawling.stock_chip_race.requests.post')
    def test_stock_chip_race_open_http_error(self, mock_post, mock_proxys):
        mod = self._import()
        mock_proxy_inst = MagicMock()
        mock_proxy_inst.get_proxies.return_value = {}
        mock_proxys.return_value = mock_proxy_inst

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_post.return_value = mock_resp

        df = mod.stock_chip_race_open()
        self.assertTrue(df.empty)

    @patch('quantia.core.crawling.stock_chip_race.proxys')
    @patch('quantia.core.crawling.stock_chip_race.requests.post')
    def test_stock_chip_race_open_json_error(self, mock_post, mock_proxys):
        mod = self._import()
        mock_proxy_inst = MagicMock()
        mock_proxy_inst.get_proxies.return_value = {}
        mock_proxys.return_value = mock_proxy_inst

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = ValueError("No JSON")
        mock_resp.text = "not json"
        mock_post.return_value = mock_resp

        df = mod.stock_chip_race_open()
        self.assertTrue(df.empty)

    @patch('quantia.core.crawling.stock_chip_race.proxys')
    @patch('quantia.core.crawling.stock_chip_race.requests.post')
    def test_stock_chip_race_network_error(self, mock_post, mock_proxys):
        mod = self._import()
        mock_proxy_inst = MagicMock()
        mock_proxy_inst.get_proxies.return_value = {}
        mock_proxys.return_value = mock_proxy_inst

        mock_post.side_effect = Exception("Connection refused")

        df = mod.stock_chip_race_open()
        self.assertTrue(df.empty)


# ═══════════════════════════════════════════════════════════════════════════
# 19. stock_cpbd
# ═══════════════════════════════════════════════════════════════════════════
class TestStockCpbd(unittest.TestCase):
    """Tests for quantia.core.crawling.stock_cpbd"""

    def _import(self):
        from quantia.core.crawling import stock_cpbd
        return stock_cpbd

    @patch('quantia.core.crawling.stock_cpbd.fetcher')
    def test_stock_cpbd_em_market_prefix_sh(self, mock_fetcher):
        """Verify SH prefix is added for 6xx codes."""
        mod = self._import()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "zxzb": [{"EPS": 2.5, "BPS": 15.0}],
            "zxzbOther": [],
            "ssbk": [{"BOARD_NAME": "银行"}],
            "gdrs": [],
            "lhbd": [],
            "dzjy": [],
            "rzrq": [],
        }
        mock_fetcher.make_request.return_value = mock_resp

        mod.stock_cpbd_em(symbol="600000")
        call_args = mock_fetcher.make_request.call_args
        params = call_args[1].get('params') or call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get('params')
        self.assertIn("SH600000", str(params))

    @patch('quantia.core.crawling.stock_cpbd.fetcher')
    def test_stock_cpbd_em_market_prefix_sz(self, mock_fetcher):
        """Verify SZ prefix is added for 0xx/3xx codes."""
        mod = self._import()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "zxzb": [{"EPS": 1.0}],
            "zxzbOther": [],
            "ssbk": [],
            "gdrs": [],
            "lhbd": [],
            "dzjy": [],
            "rzrq": [],
        }
        mock_fetcher.make_request.return_value = mock_resp

        mod.stock_cpbd_em(symbol="000001")
        call_args = mock_fetcher.make_request.call_args
        params = call_args[1].get('params') or call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get('params')
        self.assertIn("SZ000001", str(params))

    @patch('quantia.core.crawling.stock_cpbd.fetcher')
    def test_stock_cpbd_em_empty_zxzb(self, mock_fetcher):
        mod = self._import()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "zxzb": [],
            "zxzbOther": [],
            "ssbk": [],
            "gdrs": [],
            "lhbd": [],
            "dzjy": [],
            "rzrq": [],
        }
        mock_fetcher.make_request.return_value = mock_resp

        result = mod.stock_cpbd_em(symbol="000001")
        self.assertIsNone(result)


# ═══════════════════════════════════════════════════════════════════════════
# 20. stock_limitup_reason
# ═══════════════════════════════════════════════════════════════════════════
class TestStockLimitupReason(unittest.TestCase):
    """Tests for quantia.core.crawling.stock_limitup_reason"""

    def _import(self):
        from quantia.core.crawling import stock_limitup_reason as mod
        return mod

    @patch('quantia.core.crawling.stock_limitup_reason.stock_limitup_detail',
           new=lambda row: "详细原因")
    @patch('quantia.core.crawling.stock_limitup_reason.proxys')
    @patch('quantia.core.crawling.stock_limitup_reason.requests.get')
    def test_stock_limitup_reason_columns(self, mock_get, mock_proxys):
        mod = self._import()
        mock_proxy_inst = MagicMock()
        mock_proxy_inst.get_proxies.return_value = {}
        mock_proxys.return_value = mock_proxy_inst

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": [
                [12345, "平安银行", "000001", "资金流入", "2024-01-02",
                 10.5, 0.5, 5.0, 1.2, 50000000, 100000, 3.5, "_"]
            ]
        }
        mock_get.return_value = mock_resp

        df = mod.stock_limitup_reason(date="2024-01-02")
        self.assertIn("代码", df.columns)
        self.assertIn("原因", df.columns)
        self.assertIn("日期", df.columns)
        self.assertEqual(len(df), 1)

    @patch('quantia.core.crawling.stock_limitup_reason.proxys')
    @patch('quantia.core.crawling.stock_limitup_reason.requests.get')
    def test_stock_limitup_reason_empty(self, mock_get, mock_proxys):
        mod = self._import()
        mock_proxy_inst = MagicMock()
        mock_proxy_inst.get_proxies.return_value = {}
        mock_proxys.return_value = mock_proxy_inst

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": []}
        mock_get.return_value = mock_resp

        df = mod.stock_limitup_reason(date="2024-01-02")
        self.assertTrue(df.empty)

    @patch('quantia.core.crawling.stock_limitup_reason.proxys')
    @patch('quantia.core.crawling.stock_limitup_reason.requests.get')
    def test_stock_limitup_reason_network_error(self, mock_get, mock_proxys):
        mod = self._import()
        mock_proxy_inst = MagicMock()
        mock_proxy_inst.get_proxies.return_value = {}
        mock_proxys.return_value = mock_proxy_inst

        mock_get.side_effect = Exception("timeout")

        df = mod.stock_limitup_reason(date="2024-01-02")
        self.assertTrue(df.empty)

    @patch('quantia.core.crawling.stock_limitup_reason.proxys')
    @patch('quantia.core.crawling.stock_limitup_reason.requests.get')
    def test_stock_limitup_detail(self, mock_get, mock_proxys):
        mod = self._import()
        mock_proxy_inst = MagicMock()
        mock_proxy_inst.get_proxies.return_value = {}
        mock_proxys.return_value = mock_proxy_inst

        mock_resp = MagicMock()
        mock_resp.text = "var title = '涨停原因'; var data = 'Some detail text';"
        mock_get.return_value = mock_resp

        row = pd.Series({"ID": 12345})
        result = mod.stock_limitup_detail(row)
        self.assertEqual(result, "Some detail text")

    @patch('quantia.core.crawling.stock_limitup_reason.proxys')
    @patch('quantia.core.crawling.stock_limitup_reason.requests.get')
    def test_stock_limitup_detail_network_error(self, mock_get, mock_proxys):
        mod = self._import()
        mock_proxy_inst = MagicMock()
        mock_proxy_inst.get_proxies.return_value = {}
        mock_proxys.return_value = mock_proxy_inst

        mock_get.side_effect = Exception("timeout")

        row = pd.Series({"ID": 12345})
        result = mod.stock_limitup_detail(row)
        self.assertEqual(result, "")


# ═══════════════════════════════════════════════════════════════════════════
# 21. stock_selection
# ═══════════════════════════════════════════════════════════════════════════
class TestStockSelection(unittest.TestCase):
    """Tests for quantia.core.crawling.stock_selection"""

    def _import(self):
        from quantia.core.crawling import stock_selection
        return stock_selection

    @patch('quantia.core.crawling.stock_selection.fetcher')
    def test_stock_selection_empty(self, mock_fetcher):
        mod = self._import()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"result": {"data": [], "count": 0}}
        mock_fetcher.make_request.return_value = mock_resp

        df = mod.stock_selection()
        self.assertTrue(df.empty)

    @patch('quantia.core.crawling.stock_selection.fetcher')
    def test_stock_selection_first_page_failure(self, mock_fetcher):
        mod = self._import()
        mock_fetcher.make_request.side_effect = Exception("Network error")

        df = mod.stock_selection()
        self.assertTrue(df.empty)


# ═══════════════════════════════════════════════════════════════════════════
# 22. trade_date_hist
# ═══════════════════════════════════════════════════════════════════════════
class TestTradeDateHist(unittest.TestCase):
    """Tests for quantia.core.crawling.trade_date_hist"""

    def _import(self):
        from quantia.core.crawling import trade_date_hist
        return trade_date_hist

    # -- _request_with_ssl_retry ----------------------------------------
    @patch('quantia.core.crawling.trade_date_hist.requests.get')
    def test_request_with_ssl_retry_success_first_try(self, mock_get):
        mod = self._import()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = mod._request_with_ssl_retry("https://example.com")
        self.assertEqual(result, mock_resp)
        self.assertEqual(mock_get.call_count, 1)

    @patch('quantia.core.crawling.trade_date_hist.requests.get')
    def test_request_with_ssl_retry_ssl_then_success(self, mock_get):
        mod = self._import()
        import requests as req_lib
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()

        # First two calls (proxy+verify) fail with SSL, third (direct+verify) succeeds
        mock_get.side_effect = [
            req_lib.exceptions.SSLError("SSL handshake failed"),
            req_lib.exceptions.SSLError("SSL handshake failed"),
            mock_resp,
        ]

        result = mod._request_with_ssl_retry("https://example.com",
                                              proxies={"http": "http://proxy:8080"})
        self.assertEqual(result, mock_resp)

    @patch('quantia.core.crawling.trade_date_hist.requests.get')
    def test_request_with_ssl_retry_all_fail(self, mock_get):
        mod = self._import()
        import requests as req_lib
        mock_get.side_effect = req_lib.exceptions.SSLError("SSL error")

        with self.assertRaises(req_lib.exceptions.SSLError):
            mod._request_with_ssl_retry("https://example.com", max_retries=1)

    @patch('quantia.core.crawling.trade_date_hist.requests.get')
    def test_request_with_ssl_retry_timeout_skips(self, mock_get):
        """Timeout errors should immediately skip to next attempt combo."""
        mod = self._import()
        import requests as req_lib
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()

        # Timeout with proxy, then direct succeeds
        mock_get.side_effect = [
            req_lib.exceptions.ConnectTimeout("Timed out"),
            mock_resp,
        ]

        result = mod._request_with_ssl_retry(
            "https://example.com",
            proxies={"http": "http://proxy:8080"},
            max_retries=2
        )
        self.assertEqual(result, mock_resp)

    @patch('quantia.core.crawling.trade_date_hist.requests.get')
    def test_request_with_ssl_retry_connection_error_retries(self, mock_get):
        mod = self._import()
        import requests as req_lib
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()

        # First ConnectionError, then success on retry
        mock_get.side_effect = [
            req_lib.exceptions.ConnectionError("refused"),
            mock_resp,
        ]

        result = mod._request_with_ssl_retry("https://example.com", max_retries=2)
        self.assertEqual(result, mock_resp)

    @patch('quantia.core.crawling.trade_date_hist.MiniRacer')
    @patch('quantia.core.crawling.trade_date_hist._request_with_ssl_retry')
    @patch('quantia.core.crawling.trade_date_hist.proxys')
    def test_tool_trade_date_hist_sina(self, mock_proxys, mock_request, mock_mini):
        mod = self._import()
        mock_proxy_inst = MagicMock()
        mock_proxy_inst.get_proxies.return_value = {}
        mock_proxys.return_value = mock_proxy_inst

        mock_resp = MagicMock()
        mock_resp.text = 'var data="ENCODED_DATA";'
        mock_request.return_value = mock_resp

        # MiniRacer decode returns list of dicts with 'day' key
        mock_js = MagicMock()
        mock_mini.return_value = mock_js
        mock_js.call.return_value = [
            {"day": datetime.datetime(2024, 1, 2)},
            {"day": datetime.datetime(2024, 1, 3)},
        ]

        df = mod.tool_trade_date_hist_sina()
        self.assertIn("trade_date", df.columns)
        # Should include the injected 1992-05-04 date
        self.assertGreater(len(df), 2)

    @patch('quantia.core.crawling.trade_date_hist._request_with_ssl_retry')
    @patch('quantia.core.crawling.trade_date_hist.proxys')
    def test_tool_trade_date_hist_sina_network_error_with_cache(self, mock_proxys, mock_request):
        """API失败时，若存在本地缓存则降级返回缓存数据。"""
        mod = self._import()
        mock_proxy_inst = MagicMock()
        mock_proxy_inst.get_proxies.return_value = {}
        mock_proxys.return_value = mock_proxy_inst
        mock_request.side_effect = Exception("All retries failed")

        import json, tempfile, os
        cache_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(mod.__file__))),
            'cache'
        )
        cache_file = os.path.join(cache_dir, 'trade_date_cache.json')
        os.makedirs(cache_dir, exist_ok=True)
        # 写入临时缓存
        backup = None
        if os.path.isfile(cache_file):
            with open(cache_file, 'r') as f:
                backup = f.read()
        try:
            with open(cache_file, 'w') as f:
                json.dump(['2024-01-02', '2024-01-03', '2024-01-04'], f)
            df = mod.tool_trade_date_hist_sina()
            self.assertEqual(len(df), 3)
            self.assertIn('trade_date', df.columns)
        finally:
            if backup is not None:
                with open(cache_file, 'w') as f:
                    f.write(backup)
            elif os.path.isfile(cache_file):
                os.remove(cache_file)

    @patch('quantia.core.crawling.trade_date_hist._request_with_ssl_retry')
    @patch('quantia.core.crawling.trade_date_hist.proxys')
    def test_tool_trade_date_hist_sina_network_error_no_cache(self, mock_proxys, mock_request):
        """API失败且无本地缓存时应抛出异常。"""
        mod = self._import()
        mock_proxy_inst = MagicMock()
        mock_proxy_inst.get_proxies.return_value = {}
        mock_proxys.return_value = mock_proxy_inst
        mock_request.side_effect = Exception("All retries failed")

        import os
        cache_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(mod.__file__))),
            'cache', 'trade_date_cache.json'
        )
        # 确保缓存文件不存在
        backup = None
        if os.path.isfile(cache_file):
            with open(cache_file, 'r') as f:
                backup = f.read()
            os.remove(cache_file)
        try:
            with self.assertRaises(Exception):
                mod.tool_trade_date_hist_sina()
        finally:
            if backup is not None:
                with open(cache_file, 'w') as f:
                    f.write(backup)


# ═══════════════════════════════════════════════════════════════════════════
# Cross-module: Shared helper pattern tests
# ═══════════════════════════════════════════════════════════════════════════
class TestSharedHelperPatterns(unittest.TestCase):
    """Verify that _safe_float / _safe_int are consistent across modules."""

    def test_safe_float_across_modules(self):
        """All modules' _safe_float should handle None, '', '-' identically."""
        from quantia.core.crawling import stock_hist_sina
        from quantia.core.crawling import stock_hist_tencent
        from quantia.core.crawling import stock_sina
        from quantia.core.crawling import stock_tencent

        modules = [stock_hist_sina, stock_hist_tencent, stock_sina, stock_tencent]
        for mod in modules:
            with self.subTest(module=mod.__name__):
                self.assertEqual(mod._safe_float(None), 0.0)
                self.assertEqual(mod._safe_float(''), 0.0)
                self.assertEqual(mod._safe_float('-'), 0.0)
                self.assertEqual(mod._safe_float('3.14'), 3.14)

    def test_safe_int_across_modules(self):
        from quantia.core.crawling import stock_sina
        from quantia.core.crawling import stock_tencent

        for mod in [stock_sina, stock_tencent]:
            with self.subTest(module=mod.__name__):
                self.assertEqual(mod._safe_int(None), 0)
                self.assertEqual(mod._safe_int(''), 0)
                self.assertEqual(mod._safe_int('-'), 0)
                self.assertEqual(mod._safe_int('100'), 100)


# ═══════════════════════════════════════════════════════════════════════════
# Additional edge cases and error handling
# ═══════════════════════════════════════════════════════════════════════════
class TestEdgeCases(unittest.TestCase):
    """Misc edge cases across multiple modules."""

    def test_code_id_map_proxy_empty_symbol(self):
        from quantia.core.crawling.stock_hist_em import _CodeIdMapProxy
        proxy = _CodeIdMapProxy()
        with self.assertRaises(KeyError):
            _ = proxy['']

    def test_code_id_map_proxy_none_symbol(self):
        from quantia.core.crawling.stock_hist_em import _CodeIdMapProxy
        proxy = _CodeIdMapProxy()
        self.assertIsNone(proxy.get(None))

    def test_tencent_kline_key_unknown(self):
        from quantia.core.crawling.stock_hist_tencent import _get_kline_key
        self.assertEqual(_get_kline_key('xyz'), 'day')

    def test_sina_hist_convert_adjust_unknown(self):
        from quantia.core.crawling.stock_hist_sina import _convert_adjust_type
        self.assertEqual(_convert_adjust_type('xxx'), '')

    @patch('quantia.core.crawling.stock_hist_tencent.requests.get')
    def test_fetch_one_batch_no_json(self, mock_get):
        from quantia.core.crawling.stock_hist_tencent import _fetch_one_batch
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = 'not a json response at all'
        mock_get.return_value = mock_resp
        result = _fetch_one_batch("sz000001", "", "day", "2024-01-01", "2024-01-10", 300)
        self.assertIsNone(result)

    @patch('quantia.core.crawling.stock_hist_tencent.requests.get')
    def test_fetch_one_batch_code_not_zero(self, mock_get):
        from quantia.core.crawling.stock_hist_tencent import _fetch_one_batch
        json_body = {"code": -1, "msg": "error"}
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = f'kline_day={json.dumps(json_body)}'
        mock_get.return_value = mock_resp
        result = _fetch_one_batch("sz000001", "", "day", "2024-01-01", "2024-01-10", 300)
        self.assertIsNone(result)

    def test_index_em_get_market_id_000_prefix(self):
        from quantia.core.crawling.stock_index_em import _get_index_market_id
        # 000xxx → 1 (上交所)
        self.assertEqual(_get_index_market_id('000001'), 1)
        self.assertEqual(_get_index_market_id('000300'), 1)

    def test_index_em_get_market_id_399_prefix(self):
        from quantia.core.crawling.stock_index_em import _get_index_market_id
        self.assertEqual(_get_index_market_id('399001'), 0)

    def test_index_sina_code_to_sina_various(self):
        from quantia.core.crawling.index_sina import _code_to_sina
        self.assertEqual(_code_to_sina('000016'), 'sh000016')
        self.assertEqual(_code_to_sina('399006'), 'sz399006')

    def test_index_tencent_code_to_tencent_various(self):
        from quantia.core.crawling.index_tencent import _code_to_tencent
        self.assertEqual(_code_to_tencent('000016'), 'sh000016')
        self.assertEqual(_code_to_tencent('399006'), 'sz399006')

    @patch('quantia.core.crawling.stock_chip_race.proxys')
    @patch('quantia.core.crawling.stock_chip_race.requests.post')
    def test_chip_race_end_http_error(self, mock_post, mock_proxys):
        from quantia.core.crawling.stock_chip_race import stock_chip_race_end
        mock_proxy_inst = MagicMock()
        mock_proxy_inst.get_proxies.return_value = {}
        mock_proxys.return_value = mock_proxy_inst

        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_post.return_value = mock_resp

        df = stock_chip_race_end()
        self.assertTrue(df.empty)

    def test_parse_sina_data_short_fields(self):
        """Lines with fewer than 32 fields should be skipped."""
        from quantia.core.crawling.stock_sina import _parse_sina_data
        line = 'var hq_str_sh600000="shortdata,only,few,fields";'
        result = _parse_sina_data(line)
        self.assertEqual(len(result), 0)

    def test_parse_tencent_data_short_fields(self):
        """Lines with fewer than 50 fields should be skipped."""
        from quantia.core.crawling.stock_tencent import _parse_tencent_data
        parts = ['a'] * 10
        text = f"v_sh600000=\"{'~'.join(parts)}\";"
        result = _parse_tencent_data(text)
        self.assertEqual(len(result), 0)

    def test_etf_sina_get_codes_includes_159(self):
        from quantia.core.crawling.etf_sina import _get_etf_codes
        codes = _get_etf_codes()
        sz_codes = [c for c in codes if c.startswith('sz159')]
        self.assertGreater(len(sz_codes), 0)

    def test_etf_tencent_get_codes_includes_510(self):
        from quantia.core.crawling.etf_tencent import _get_etf_codes
        codes = _get_etf_codes()
        sh_codes = [c for c in codes if c.startswith('sh510')]
        self.assertGreater(len(sh_codes), 0)


if __name__ == "__main__":
    unittest.main()
