#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import inspect
import unittest
from unittest.mock import MagicMock, patch

import pandas as pd


class TestIndexRoutingGuards(unittest.TestCase):
    def test_kline_handler_index_branch_does_not_fallback_to_stock_cache(self):
        from quantia.web import klineHandler

        source = inspect.getsource(klineHandler.GetKlineDataHandler.get)
        start = source.index("if data_type == 'index':")
        end = source.index("else:", start)
        idx_block = source[start:end]

        self.assertIn('read_index_hist_from_cache', idx_block)
        self.assertNotIn('read_hist_from_cache', idx_block)

    def test_data_indicators_handler_routes_index_by_strategy(self):
        from quantia.web import dataIndicatorsHandler

        source = inspect.getsource(dataIndicatorsHandler.GetDataIndicatorsHandler.get)
        idx_pos = source.index("if 'index' in (strategy or '').lower():")
        idx_block = source[idx_pos:idx_pos + 600]

        self.assertIn('read_index_hist_from_cache', idx_block)
        self.assertIn('index_hist_cache_incremental', idx_block)


class TestSpotBackfillOhlcValidation(unittest.TestCase):
    @patch('quantia.lib.database.engine')
    @patch('quantia.lib.database.checkTableIsExist')
    @patch('quantia.core.stockfetch.pd.read_sql')
    def test_backfill_from_spot_skips_invalid_ohlc_row(self, mock_read_sql, mock_exists, mock_engine):
        from quantia.core.stockfetch import _backfill_from_spot

        mock_exists.return_value = True
        mock_engine.return_value = MagicMock()
        mock_read_sql.return_value = pd.DataFrame([
            {
                'date': '2026-06-12',
                'close': 2.76,
                'open': 0.0,
                'high': 0.0,
                'low': 0.0,
                'volume': 0.0,
                'amount': 0.0,
                'amplitude': 0.0,
                'quote_change': 0.0,
                'ups_downs': 0.0,
                'turnover': 0.0,
            }
        ])

        result = _backfill_from_spot('000004', '20260612')
        self.assertIsNone(result)

    @patch('quantia.lib.database.engine')
    @patch('quantia.lib.database.checkTableIsExist')
    @patch('quantia.core.stockfetch.pd.read_sql')
    def test_fallback_from_spot_keeps_only_valid_rows(self, mock_read_sql, mock_exists, mock_engine):
        from quantia.core.stockfetch import _fallback_kline_from_spot

        mock_exists.return_value = True
        mock_engine.return_value = MagicMock()
        mock_read_sql.return_value = pd.DataFrame([
            {
                'date': '2026-06-11',
                'close': 2.76,
                'open': 0.0,
                'high': 0.0,
                'low': 0.0,
                'volume': 0.0,
                'amount': 0.0,
                'amplitude': 0.0,
                'quote_change': 0.0,
                'ups_downs': 0.0,
                'turnover': 0.0,
            },
            {
                'date': '2026-06-12',
                'close': 3859.0,
                'open': 3883.62,
                'high': 3916.06,
                'low': 3850.24,
                'volume': 460174620.0,
                'amount': 0.0,
                'amplitude': 1.71,
                'quote_change': 0.72,
                'ups_downs': 27.63,
                'turnover': 0.0,
            },
        ])

        result = _fallback_kline_from_spot('000004', '20260601', '20260612')
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(float(result.iloc[0]['close']), 3859.0)


if __name__ == '__main__':
    unittest.main()
