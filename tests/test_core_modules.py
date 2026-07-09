#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Comprehensive unit tests for quantia/core/ top-level modules.

Covers:
  - tablestructure: TABLE_CN_* constants, get_field_cn, get_field_cns,
                    get_field_types, get_field_type_name
  - web_module_data: instantiation, attributes, url generation
  - stockfetch: is_a_stock, is_not_st, is_open, is_open_with_line,
                _filter_ohlc_outliers, source health tracking,
                _retry_sleep, stock_hist_cache_incremental,
                read_hist_from_cache, _to_date_str, _to_dash_date,
                _to_dash_date_safe
  - singleton_stock: stock_data, stock_hist_data singleton behavior
  - singleton_trade_date: stock_trade_date singleton & refresh
  - singleton_stock_web_module_data: stock_web_module_data registration
  - singleton_proxy: proxys pool management (mocked)
  - eastmoney_fetcher: make_request / session / cookie (mocked)

All tests are self-contained — no database, network, or file I/O required.
"""

import os
import sys
import time
import datetime
import threading
import unittest
from unittest.mock import patch, MagicMock, PropertyMock, mock_open, call
import json

import numpy as np
import pandas as pd

# Ensure project root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Pre-import in dependency order to break circular import seen when
# TestSingletonTradeDate runs in isolation (singleton_trade_date <-> stockfetch <-> trade_time).
import quantia.core.stockfetch  # noqa: E402,F401
import quantia.core.singleton_trade_date  # noqa: E402,F401


# ============================================================
# 1. tablestructure
# ============================================================
class TestTableStructureConstants(unittest.TestCase):
    """Tests for TABLE_CN_* dictionary constants."""

    def setUp(self):
        import quantia.core.tablestructure as tbs
        self.tbs = tbs

    def test_table_cn_stock_attention_has_required_keys(self):
        t = self.tbs.TABLE_CN_STOCK_ATTENTION
        self.assertIn('name', t)
        self.assertIn('cn', t)
        self.assertIn('columns', t)
        self.assertEqual(t['name'], 'cn_stock_attention')
        self.assertEqual(t['cn'], '我的关注')

    def test_table_cn_stock_attention_columns(self):
        cols = self.tbs.TABLE_CN_STOCK_ATTENTION['columns']
        self.assertIn('datetime', cols)
        self.assertIn('code', cols)
        self.assertIn('cn', cols['code'])
        self.assertEqual(cols['code']['cn'], '代码')

    def test_table_cn_stock_spot_has_many_columns(self):
        cols = self.tbs.TABLE_CN_STOCK_SPOT['columns']
        self.assertGreater(len(cols), 30)
        self.assertIn('code', cols)
        self.assertIn('name', cols)
        self.assertIn('new_price', cols)
        self.assertIn('change_rate', cols)
        self.assertIn('industry', cols)

    def test_table_cn_etf_spot_structure(self):
        t = self.tbs.TABLE_CN_ETF_SPOT
        self.assertEqual(t['name'], 'cn_etf_spot')
        self.assertEqual(t['cn'], '每日ETF数据')
        cols = t['columns']
        self.assertIn('date', cols)
        self.assertIn('code', cols)
        self.assertIn('volume', cols)

    def test_table_cn_index_spot_structure(self):
        t = self.tbs.TABLE_CN_INDEX_SPOT
        self.assertEqual(t['name'], 'cn_index_spot')
        cols = t['columns']
        self.assertIn('code', cols)
        # Index code can be up to 12 chars
        self.assertIn('name', cols)

    def test_table_cn_stock_backtest_structure(self):
        t = self.tbs.TABLE_CN_STOCK_BACKTEST
        self.assertEqual(t['name'], 'cn_stock_backtest')
        cols = t['columns']
        self.assertIn('date', cols)
        self.assertIn('strategy_name', cols)
        self.assertIn('success_rate', cols)
        # Check avg_rate horizons exist
        for h in (1, 3, 5, 10, 20, 30, 60, 90, 120):
            self.assertIn(f'avg_rate_{h}', cols)

    def test_table_cn_stock_spot_buy_copies_stock_spot(self):
        buy_cols = self.tbs.TABLE_CN_STOCK_SPOT_BUY['columns']
        spot_cols = self.tbs.TABLE_CN_STOCK_SPOT['columns']
        self.assertEqual(set(buy_cols.keys()), set(spot_cols.keys()))

    def test_cn_stock_hist_data_has_ohlcv(self):
        cols = self.tbs.CN_STOCK_HIST_DATA['columns']
        for field in ('date', 'open', 'close', 'high', 'low', 'volume', 'amount'):
            self.assertIn(field, cols)

    def test_table_cn_stock_fund_flow_merges_all_flows(self):
        t = self.tbs.TABLE_CN_STOCK_FUND_FLOW
        cols = t['columns']
        self.assertIn('date', cols)
        self.assertIn('code', cols)
        self.assertIn('fund_amount', cols)
        self.assertIn('fund_amount_3', cols)

    def test_table_cn_stock_foreign_key_has_date_code_name(self):
        t = self.tbs.TABLE_CN_STOCK_FOREIGN_KEY
        cols = t['columns']
        self.assertEqual(set(cols.keys()), {'date', 'code', 'name'})

    def test_table_cn_stock_backtest_data_has_rate_fields(self):
        t = self.tbs.TABLE_CN_STOCK_BACKTEST_DATA
        cols = t['columns']
        self.assertEqual(len(cols), self.tbs.RATE_FIELDS_COUNT)
        self.assertIn('rate_1', cols)
        self.assertIn('rate_100', cols)

    def test_stock_stats_data_indicator_columns(self):
        cols = self.tbs.STOCK_STATS_DATA['columns']
        for indicator in ('macd', 'kdjk', 'rsi_6', 'boll', 'cci', 'atr', 'obv', 'sar'):
            self.assertIn(indicator, cols)

    def test_table_cn_stock_bonus_columns(self):
        t = self.tbs.TABLE_CN_STOCK_BONUS
        cols = t['columns']
        self.assertIn('bonusaward_yield', cols)
        self.assertIn('ex_dividend_date', cols)


class TestTableStructureFunctions(unittest.TestCase):
    """Tests for get_field_cn, get_field_cns, get_field_types, get_field_type_name."""

    def setUp(self):
        import quantia.core.tablestructure as tbs
        self.tbs = tbs

    # -- get_field_cn --
    def test_get_field_cn_returns_chinese_name(self):
        result = self.tbs.get_field_cn('code', self.tbs.TABLE_CN_STOCK_SPOT)
        self.assertEqual(result, '代码')

    def test_get_field_cn_returns_key_when_not_found(self):
        result = self.tbs.get_field_cn('nonexistent_col', self.tbs.TABLE_CN_STOCK_SPOT)
        self.assertEqual(result, 'nonexistent_col')

    def test_get_field_cn_for_date_column(self):
        result = self.tbs.get_field_cn('date', self.tbs.TABLE_CN_STOCK_SPOT)
        self.assertEqual(result, '日期')

    def test_get_field_cn_for_change_rate(self):
        result = self.tbs.get_field_cn('change_rate', self.tbs.TABLE_CN_STOCK_SPOT)
        self.assertEqual(result, '涨跌幅')

    # -- get_field_cns --
    def test_get_field_cns_returns_list_of_dicts(self):
        cols = self.tbs.TABLE_CN_STOCK_FOREIGN_KEY['columns']
        result = self.tbs.get_field_cns(cols)
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 3)  # date, code, name
        for entry in result:
            self.assertIn('value', entry)
            self.assertIn('caption', entry)
            self.assertIn('width', entry)
            self.assertIn('dataType', entry)

    def test_get_field_cns_data_types(self):
        cols = self.tbs.TABLE_CN_STOCK_FOREIGN_KEY['columns']
        result = self.tbs.get_field_cns(cols)
        by_value = {e['value']: e for e in result}
        self.assertEqual(by_value['date']['dataType'], 'datetime')
        self.assertEqual(by_value['code']['dataType'], 'string')

    def test_get_field_cns_code_has_style_key(self):
        cols = self.tbs.TABLE_CN_STOCK_SPOT['columns']
        result = self.tbs.get_field_cns(cols)
        by_value = {e['value']: e for e in result}
        self.assertIn('style', by_value['code'])

    def test_get_field_cns_change_rate_has_conditional_formats(self):
        cols = self.tbs.TABLE_CN_STOCK_SPOT['columns']
        result = self.tbs.get_field_cns(cols)
        by_value = {e['value']: e for e in result}
        self.assertIn('conditionalFormats', by_value['change_rate'])
        self.assertEqual(len(by_value['change_rate']['conditionalFormats']), 2)

    def test_get_field_cns_bigint_data_type(self):
        cols = self.tbs.TABLE_CN_STOCK_SPOT['columns']
        result = self.tbs.get_field_cns(cols)
        by_value = {e['value']: e for e in result}
        # volume is BIGINT → should be 'bigint' data type
        self.assertEqual(by_value['volume']['dataType'], 'bigint')

    # -- get_field_types --
    def test_get_field_types_returns_dict(self):
        cols = self.tbs.TABLE_CN_STOCK_FOREIGN_KEY['columns']
        result = self.tbs.get_field_types(cols)
        self.assertIsInstance(result, dict)
        self.assertEqual(len(result), 3)

    def test_get_field_types_values_are_sqlalchemy_types(self):
        from sqlalchemy import DATE, FLOAT, VARCHAR
        cols = self.tbs.TABLE_CN_STOCK_FOREIGN_KEY['columns']
        result = self.tbs.get_field_types(cols)
        self.assertEqual(result['date'], DATE)

    # -- get_field_type_name --
    def test_get_field_type_name_date(self):
        from sqlalchemy import DATE
        self.assertEqual(self.tbs.get_field_type_name(DATE), 'datetime')

    def test_get_field_type_name_float(self):
        from sqlalchemy import FLOAT
        self.assertEqual(self.tbs.get_field_type_name(FLOAT), 'numeric')

    def test_get_field_type_name_bigint(self):
        from sqlalchemy import BIGINT
        self.assertEqual(self.tbs.get_field_type_name(BIGINT), 'numeric')

    def test_get_field_type_name_smallint(self):
        from sqlalchemy import SmallInteger
        self.assertEqual(self.tbs.get_field_type_name(SmallInteger), 'numeric')

    def test_get_field_type_name_varchar(self):
        from sqlalchemy import VARCHAR
        self.assertEqual(self.tbs.get_field_type_name(VARCHAR(20)), 'string')

    def test_get_field_type_name_bit(self):
        from sqlalchemy.dialects.mysql import BIT
        self.assertEqual(self.tbs.get_field_type_name(BIT), 'numeric')


# ============================================================
# 2. web_module_data
# ============================================================
class TestWebModuleData(unittest.TestCase):
    """Tests for web_module_data class."""

    def test_basic_instantiation(self):
        from quantia.core.web_module_data import web_module_data
        wmd = web_module_data(
            mode="query",
            type="test_type",
            ico="fa fa-star",
            name="测试模块",
            table_name="test_table",
            columns=("col1", "col2"),
            column_names=[{"value": "col1"}],
            primary_key=["id"],
            is_realtime=True,
        )
        self.assertEqual(wmd.mode, "query")
        self.assertEqual(wmd.type, "test_type")
        self.assertEqual(wmd.ico, "fa fa-star")
        self.assertEqual(wmd.name, "测试模块")
        self.assertEqual(wmd.table_name, "test_table")
        self.assertEqual(wmd.columns, ("col1", "col2"))
        self.assertEqual(wmd.primary_key, ["id"])
        self.assertTrue(wmd.is_realtime)

    def test_url_generation(self):
        from quantia.core.web_module_data import web_module_data
        wmd = web_module_data(
            mode="query", type="t", ico="fa", name="n",
            table_name="my_table", columns=(), column_names=[],
            primary_key=[], is_realtime=False,
        )
        self.assertEqual(wmd.url, "/quantia/data?table_name=my_table")

    def test_optional_order_params(self):
        from quantia.core.web_module_data import web_module_data
        wmd = web_module_data(
            mode="editor", type="t", ico="fa", name="n",
            table_name="tbl", columns=(), column_names=[],
            primary_key=[], is_realtime=False,
            order_columns="col1 ASC",
            order_by=" col1 DESC",
        )
        self.assertEqual(wmd.order_columns, "col1 ASC")
        self.assertEqual(wmd.order_by, " col1 DESC")
        self.assertEqual(wmd.mode, "editor")

    def test_defaults_for_order_params(self):
        from quantia.core.web_module_data import web_module_data
        wmd = web_module_data(
            mode="query", type="t", ico="fa", name="n",
            table_name="tbl", columns=(), column_names=[],
            primary_key=[], is_realtime=False,
        )
        self.assertIsNone(wmd.order_columns)
        self.assertIsNone(wmd.order_by)


# ============================================================
# 3. stockfetch — pure / utility functions
# ============================================================
class TestIsAStock(unittest.TestCase):
    """Tests for is_a_stock() — A-share code pattern matching."""

    def setUp(self):
        from quantia.core.stockfetch import is_a_stock
        self.is_a_stock = is_a_stock

    # SH A-stock codes
    def test_sh_600_is_a_stock(self):
        self.assertTrue(self.is_a_stock('600000'))

    def test_sh_601_is_a_stock(self):
        self.assertTrue(self.is_a_stock('601318'))

    def test_sh_603_is_a_stock(self):
        self.assertTrue(self.is_a_stock('603288'))

    def test_sh_605_is_a_stock(self):
        self.assertTrue(self.is_a_stock('605001'))

    def test_star_market_688_is_a_stock(self):
        self.assertTrue(self.is_a_stock('688001'))

    # SZ A-stock codes
    def test_sz_000_is_a_stock(self):
        self.assertTrue(self.is_a_stock('000001'))

    def test_sz_001_is_a_stock(self):
        self.assertTrue(self.is_a_stock('001001'))

    def test_sz_002_is_a_stock(self):
        self.assertTrue(self.is_a_stock('002230'))

    def test_sz_003_is_a_stock(self):
        self.assertTrue(self.is_a_stock('003001'))

    # ChiNext (创业板)
    def test_sz_300_is_a_stock(self):
        self.assertTrue(self.is_a_stock('300750'))

    def test_sz_301_is_a_stock(self):
        self.assertTrue(self.is_a_stock('301001'))

    # Non-A-share codes → False
    def test_b_share_200_not_a_stock(self):
        self.assertFalse(self.is_a_stock('200001'))

    def test_b_share_900_not_a_stock(self):
        self.assertFalse(self.is_a_stock('900001'))

    def test_neeq_430_not_a_stock(self):
        self.assertFalse(self.is_a_stock('430001'))

    def test_neeq_830_not_a_stock(self):
        self.assertFalse(self.is_a_stock('830001'))

    def test_empty_string(self):
        self.assertFalse(self.is_a_stock(''))


class TestFetchStocksMarketCoverage(unittest.TestCase):
    """Tests for daily spot market coverage filtering."""

    @patch('quantia.core.stockfetch.she.stock_zh_a_spot_em')
    def test_fetch_stocks_keeps_star_market_and_chinext(self, mock_spot_em):
        from quantia.core import stockfetch
        from quantia.core import tablestructure as tbs

        source_columns = list(tbs.TABLE_CN_STOCK_SPOT['columns'])[1:]

        def make_row(code, name, price=10.0):
            row = {column: 0 for column in source_columns}
            row['code'] = code
            row['name'] = name
            row['new_price'] = price
            return row

        mock_spot_em.return_value = pd.DataFrame([
            make_row('688001', '华兴源创'),
            make_row('300750', '宁德时代'),
            make_row('301001', '凯淳股份'),
            make_row('430001', '北交示例'),
            make_row('900901', 'B股示例'),
        ], columns=source_columns)

        result = stockfetch.fetch_stocks(datetime.date(2026, 7, 9))

        self.assertEqual(set(result['code']), {'688001', '300750', '301001'})


class TestIsNotST(unittest.TestCase):
    """Tests for is_not_st() — ST stock filtering."""

    def setUp(self):
        from quantia.core.stockfetch import is_not_st
        self.is_not_st = is_not_st

    def test_normal_stock(self):
        self.assertTrue(self.is_not_st('贵州茅台'))

    def test_st_stock(self):
        self.assertFalse(self.is_not_st('ST华仪'))

    def test_star_st_stock(self):
        self.assertFalse(self.is_not_st('*ST信威'))

    def test_empty_string_is_not_st(self):
        self.assertTrue(self.is_not_st(''))


class TestIsOpen(unittest.TestCase):
    """Tests for is_open() — NaN price detection."""

    def setUp(self):
        from quantia.core.stockfetch import is_open
        self.is_open = is_open

    def test_valid_price(self):
        self.assertTrue(self.is_open(10.5))

    def test_zero_price_is_open(self):
        self.assertTrue(self.is_open(0.0))

    def test_nan_price(self):
        self.assertFalse(self.is_open(np.nan))

    def test_float_nan(self):
        self.assertFalse(self.is_open(float('nan')))


class TestIsOpenWithLine(unittest.TestCase):
    """Tests for is_open_with_line() — dash-price detection."""

    def setUp(self):
        from quantia.core.stockfetch import is_open_with_line
        self.is_open_with_line = is_open_with_line

    def test_dash_means_closed(self):
        self.assertFalse(self.is_open_with_line('-'))

    def test_valid_price_string(self):
        self.assertTrue(self.is_open_with_line('10.5'))

    def test_numeric_price(self):
        self.assertTrue(self.is_open_with_line(10.5))

    def test_zero_is_open(self):
        self.assertTrue(self.is_open_with_line(0))


class TestToDateStr(unittest.TestCase):
    """Tests for _to_date_str, _to_dash_date, _to_dash_date_safe."""

    def setUp(self):
        from quantia.core.stockfetch import _to_date_str, _to_dash_date, _to_dash_date_safe
        self.to_date_str = _to_date_str
        self.to_dash_date = _to_dash_date
        self.to_dash_date_safe = _to_dash_date_safe

    def test_to_date_str_from_dash_string(self):
        self.assertEqual(self.to_date_str('2025-03-15'), '20250315')

    def test_to_date_str_from_datetime(self):
        d = datetime.datetime(2025, 3, 15)
        self.assertEqual(self.to_date_str(d), '20250315')

    def test_to_date_str_from_date(self):
        d = datetime.date(2025, 3, 15)
        self.assertEqual(self.to_date_str(d), '20250315')

    def test_to_dash_date(self):
        self.assertEqual(self.to_dash_date('20250315'), '2025-03-15')

    def test_to_dash_date_safe_from_string_with_dash(self):
        self.assertEqual(self.to_dash_date_safe('2025-03-15'), '2025-03-15')

    def test_to_dash_date_safe_from_string_no_dash(self):
        self.assertEqual(self.to_dash_date_safe('20250315'), '2025-03-15')

    def test_to_dash_date_safe_from_timestamp(self):
        ts = pd.Timestamp('2025-03-15')
        self.assertEqual(self.to_dash_date_safe(ts), '2025-03-15')

    def test_to_dash_date_safe_from_datetime(self):
        dt = datetime.datetime(2025, 3, 15)
        self.assertEqual(self.to_dash_date_safe(dt), '2025-03-15')


# ============================================================
# 3b. stockfetch — _filter_ohlc_outliers
# ============================================================
class TestFilterOhlcOutliers(unittest.TestCase):
    """Tests for _filter_ohlc_outliers() — anomaly detection on synthetic DataFrames."""

    def setUp(self):
        from quantia.core.stockfetch import _filter_ohlc_outliers
        self.filter_fn = _filter_ohlc_outliers

    def _make_normal_df(self, n=50, base_price=10.0, base_volume=10000):
        """Create a synthetic 'normal' OHLCV DataFrame."""
        dates = pd.date_range('2025-01-01', periods=n, freq='B')
        np.random.seed(42)
        close = base_price + np.random.normal(0, 0.2, n).cumsum()
        close = np.maximum(close, 1.0)  # keep positive
        df = pd.DataFrame({
            'date': dates,
            'open': close * 0.99,
            'high': close * 1.02,
            'low': close * 0.98,
            'close': close,
            'volume': np.random.randint(base_volume // 2, base_volume * 2, n).astype(float),
            'amount': np.random.randint(100000, 500000, n).astype(float),
        })
        return df

    def test_no_outliers_returns_same_data(self):
        df = self._make_normal_df()
        result, n_removed = self.filter_fn(df, '000001')
        self.assertEqual(n_removed, 0)
        self.assertEqual(len(result), len(df))

    def test_none_input(self):
        result, n = self.filter_fn(None, '000001')
        self.assertIsNone(result)
        self.assertEqual(n, 0)

    def test_too_short_data(self):
        df = self._make_normal_df(n=5)
        result, n = self.filter_fn(df, '000001')
        self.assertEqual(n, 0)
        self.assertEqual(len(result), 5)

    def test_extreme_price_spike_removed(self):
        """A single row with price > 2.5x neighbors should be removed."""
        df = self._make_normal_df(n=30, base_price=10.0)
        # Inject outlier at row 15: close = 100 (10x normal)
        df.loc[15, 'close'] = 100.0
        df.loc[15, 'open'] = 100.0
        df.loc[15, 'high'] = 105.0
        df.loc[15, 'low'] = 95.0
        result, n_removed = self.filter_fn(df.copy(), '000001')
        self.assertGreaterEqual(n_removed, 1)
        self.assertLess(len(result), len(df))

    def test_extreme_price_drop_removed(self):
        """A single row with price < 0.4x neighbors (extreme drop) should be removed."""
        df = self._make_normal_df(n=30, base_price=10.0)
        # Inject outlier: price drops to 1.0 while neighbors are ~10
        df.loc[15, 'close'] = 1.0
        df.loc[15, 'open'] = 1.0
        df.loc[15, 'high'] = 1.2
        df.loc[15, 'low'] = 0.8
        result, n_removed = self.filter_fn(df.copy(), '000001')
        self.assertGreaterEqual(n_removed, 1)

    def test_joint_detection_price_and_volume(self):
        """Price deviated >25% AND volume >3x neighbor median should be removed."""
        df = self._make_normal_df(n=30, base_price=10.0, base_volume=10000)
        # Inject joint anomaly: close = 14 (40% above ~10), volume = 50000 (5x)
        df.loc[15, 'close'] = 14.0
        df.loc[15, 'volume'] = 50000.0
        result, n_removed = self.filter_fn(df.copy(), '000001')
        self.assertGreaterEqual(n_removed, 1)

    def test_invalid_price_zero_removed(self):
        """Row with close <= 0 should be flagged if neighbors are positive."""
        df = self._make_normal_df(n=30, base_price=10.0)
        df.loc[15, 'close'] = 0.0
        result, n_removed = self.filter_fn(df.copy(), '000001')
        self.assertGreaterEqual(n_removed, 1)

    def test_negative_price_removed(self):
        """Row with close < 0 should be flagged if neighbors are positive."""
        df = self._make_normal_df(n=30, base_price=10.0)
        df.loc[15, 'close'] = -5.0
        result, n_removed = self.filter_fn(df.copy(), '000001')
        self.assertGreaterEqual(n_removed, 1)

    def test_safety_valve_too_many_outliers(self):
        """If >15% of rows are flagged, none should be removed (safety valve)."""
        df = self._make_normal_df(n=20, base_price=10.0)
        # Make 5 out of 20 rows (25%) show extreme prices → exceeds 15%
        for idx in [5, 8, 11, 14, 17]:
            df.loc[idx, 'close'] = 100.0
        result, n_removed = self.filter_fn(df.copy(), '000001')
        self.assertEqual(n_removed, 0)
        self.assertEqual(len(result), 20)

    def test_moderate_price_change_not_removed(self):
        """A 10% price change between neighbors should NOT be an outlier."""
        df = self._make_normal_df(n=30, base_price=10.0)
        # ~10% change is within the 25% threshold
        df.loc[15, 'close'] = df.loc[14, 'close'] * 1.10
        result, n_removed = self.filter_fn(df.copy(), '000001')
        self.assertEqual(n_removed, 0)

    def test_missing_volume_column_still_works(self):
        """If no volume column, joint detection is skipped but price detection works."""
        df = self._make_normal_df(n=30, base_price=10.0)
        df = df.drop(columns=['volume'])
        df.loc[15, 'close'] = 100.0  # extreme price spike
        result, n_removed = self.filter_fn(df.copy(), '000001')
        # Should still detect via extreme price deviation
        self.assertGreaterEqual(n_removed, 1)


# ============================================================
# 3c. stockfetch — source health tracking
# ============================================================
class TestSourceHealthTracking(unittest.TestCase):
    """Tests for _report_source_failure, _report_source_success,
    _is_source_degraded, _sort_sources_by_health."""

    def setUp(self):
        """Reset global health tracking state before each test."""
        import quantia.core.stockfetch as stf
        self.stf = stf
        # Save and reset global state
        with stf._source_health_lock:
            stf._source_fail_counts.clear()
            stf._source_cooldown_until.clear()
            stf._source_degrade_count.clear()
            stf._source_is_degraded.clear()

    def test_initial_state_not_degraded(self):
        self.assertFalse(self.stf._is_source_degraded('TestSource'))

    def test_failures_below_threshold_not_degraded(self):
        for _ in range(self.stf.SOURCE_FAIL_THRESHOLD - 1):
            self.stf._report_source_failure('TestSource')
        self.assertFalse(self.stf._is_source_degraded('TestSource'))

    def test_failures_at_threshold_triggers_degradation(self):
        for _ in range(self.stf.SOURCE_FAIL_THRESHOLD):
            self.stf._report_source_failure('TestSource')
        self.assertTrue(self.stf._is_source_degraded('TestSource'))

    def test_success_resets_failure_count(self):
        for _ in range(self.stf.SOURCE_FAIL_THRESHOLD):
            self.stf._report_source_failure('TestSource')
        self.assertTrue(self.stf._is_source_degraded('TestSource'))
        self.stf._report_source_success('TestSource')
        self.assertFalse(self.stf._is_source_degraded('TestSource'))

    def test_success_resets_degrade_count(self):
        for _ in range(self.stf.SOURCE_FAIL_THRESHOLD):
            self.stf._report_source_failure('TestSource')
        self.stf._report_source_success('TestSource')
        with self.stf._source_health_lock:
            self.assertEqual(self.stf._source_degrade_count.get('TestSource', 0), 0)

    def test_cooldown_expiry_restores_source(self):
        """After cooldown, source should no longer be degraded."""
        for _ in range(self.stf.SOURCE_FAIL_THRESHOLD):
            self.stf._report_source_failure('TestSource')
        # Manually expire cooldown
        with self.stf._source_health_lock:
            self.stf._source_cooldown_until['TestSource'] = time.time() - 1
        self.assertFalse(self.stf._is_source_degraded('TestSource'))

    def test_sort_sources_degraded_last(self):
        # Degrade source A
        for _ in range(self.stf.SOURCE_FAIL_THRESHOLD):
            self.stf._report_source_failure('A')
        sources = [('A', lambda: None), ('B', lambda: None), ('C', lambda: None)]
        sorted_sources = self.stf._sort_sources_by_health(sources)
        names = [s[0] for s in sorted_sources]
        self.assertEqual(names[-1], 'A')
        self.assertIn('B', names[:2])
        self.assertIn('C', names[:2])

    def test_sort_sources_no_degraded(self):
        sources = [('A', lambda: None), ('B', lambda: None)]
        sorted_sources = self.stf._sort_sources_by_health(sources)
        self.assertEqual(len(sorted_sources), 2)

    def test_progressive_cooldown(self):
        """Repeated degradation should increase cooldown exponentially."""
        # First degradation
        for _ in range(self.stf.SOURCE_FAIL_THRESHOLD):
            self.stf._report_source_failure('TestSource')
        with self.stf._source_health_lock:
            degrade1 = self.stf._source_degrade_count.get('TestSource', 0)
        self.assertEqual(degrade1, 1)

        # Expire and trigger second degradation
        with self.stf._source_health_lock:
            self.stf._source_cooldown_until['TestSource'] = time.time() - 1
        # _is_source_degraded will auto-recover
        self.stf._is_source_degraded('TestSource')
        for _ in range(self.stf.SOURCE_FAIL_THRESHOLD):
            self.stf._report_source_failure('TestSource')
        with self.stf._source_health_lock:
            degrade2 = self.stf._source_degrade_count.get('TestSource', 0)
        self.assertEqual(degrade2, 2)

    def test_fail_count_accumulates(self):
        self.stf._report_source_failure('X')
        self.stf._report_source_failure('X')
        self.stf._report_source_failure('X')
        with self.stf._source_health_lock:
            self.assertEqual(self.stf._source_fail_counts['X'], 3)

    def test_multiple_sources_independent(self):
        for _ in range(self.stf.SOURCE_FAIL_THRESHOLD):
            self.stf._report_source_failure('A')
        self.assertTrue(self.stf._is_source_degraded('A'))
        self.assertFalse(self.stf._is_source_degraded('B'))


# ============================================================
# 3d. stockfetch — _retry_sleep
# ============================================================
class TestRetrySleep(unittest.TestCase):
    """Tests for _retry_sleep() — exponential backoff."""

    @patch('quantia.core.stockfetch.time.sleep')
    @patch('quantia.core.stockfetch.random.uniform')
    def test_first_retry_base_delay(self, mock_uniform, mock_sleep):
        from quantia.core.stockfetch import _retry_sleep
        mock_uniform.return_value = 10.0  # fixed jitter
        _retry_sleep(0, base_interval=90)
        # base_delay = 90 * 2^0 = 90, jitter = 10, total = 100
        mock_sleep.assert_called_once()
        actual_delay = mock_sleep.call_args[0][0]
        self.assertEqual(actual_delay, 100.0)

    @patch('quantia.core.stockfetch.time.sleep')
    @patch('quantia.core.stockfetch.random.uniform')
    def test_second_retry_doubles_delay(self, mock_uniform, mock_sleep):
        from quantia.core.stockfetch import _retry_sleep
        mock_uniform.return_value = 20.0
        _retry_sleep(1, base_interval=90)
        # base_delay = 90 * 2^1 = 180, jitter = 20, total = 200
        actual_delay = mock_sleep.call_args[0][0]
        self.assertEqual(actual_delay, 200.0)

    @patch('quantia.core.stockfetch.time.sleep')
    @patch('quantia.core.stockfetch.random.uniform')
    def test_jitter_range(self, mock_uniform, mock_sleep):
        from quantia.core.stockfetch import _retry_sleep
        mock_uniform.return_value = 15.0
        _retry_sleep(0, base_interval=100)
        # Check uniform was called with 10% to 30% of base_delay (100)
        mock_uniform.assert_called_once_with(10.0, 30.0)


# ============================================================
# 3e. stockfetch — stock_hist_cache_incremental (mocked)
# ============================================================
class TestStockHistCacheIncremental(unittest.TestCase):
    """Tests for stock_hist_cache_incremental with mocked I/O."""

    def _make_cached_df(self, dates, base_price=10.0):
        """Create a cached-style DataFrame."""
        n = len(dates)
        return pd.DataFrame({
            'date': dates,
            'open': [base_price] * n,
            'close': [base_price] * n,
            'high': [base_price * 1.02] * n,
            'low': [base_price * 0.98] * n,
            'volume': [10000.0] * n,
            'amount': [100000.0] * n,
            'amplitude': [2.0] * n,
            'quote_change': [0.5] * n,
            'ups_downs': [0.05] * n,
            'turnover': [1.0] * n,
        })

    @patch('quantia.core.stockfetch._fetch_from_sources')
    @patch('quantia.core.stockfetch._write_cache_meta')
    @patch('quantia.core.stockfetch._read_cache_meta', return_value={'filtered_version': 2})
    @patch('quantia.core.stockfetch.os.replace')
    @patch('quantia.core.stockfetch.os.path.isfile', return_value=False)
    def test_no_cache_full_fetch(self, mock_isfile, mock_replace, mock_read_meta,
                                  mock_write_meta, mock_fetch):
        """When no cache exists, full fetch should be triggered."""
        from quantia.core.stockfetch import stock_hist_cache_incremental
        new_data = self._make_cached_df(['2025-01-02', '2025-01-03'])
        mock_fetch.return_value = new_data

        result = stock_hist_cache_incremental('000001', '20250102', '20250103', is_cache=True)
        mock_fetch.assert_called_once_with('000001', '20250102', '20250103', '')
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 2)

    @patch('quantia.core.stockfetch._filter_ohlc_outliers', side_effect=lambda d, c='': (d, 0))
    @patch('quantia.core.stockfetch._fetch_from_sources')
    @patch('quantia.core.stockfetch._write_cache_meta')
    @patch('quantia.core.stockfetch._read_cache_meta', return_value=None)
    @patch('quantia.core.stockfetch.pd.read_pickle')
    @patch('quantia.core.stockfetch.os.path.isfile', return_value=True)
    def test_tail_append_scenario(self, mock_isfile, mock_pickle, mock_read_meta,
                                   mock_write_meta, mock_fetch, mock_filter):
        """When cache has older data and date_end is newer, tail-append should happen."""
        from quantia.core.stockfetch import stock_hist_cache_incremental
        cached = self._make_cached_df(['2025-01-02', '2025-01-03'])
        mock_pickle.return_value = cached
        new_data = self._make_cached_df(['2025-01-06'])
        mock_fetch.return_value = new_data

        result = stock_hist_cache_incremental('000001', '20250102', '20250106', is_cache=True)
        # Should fetch only the new range (2025-01-04 to 2025-01-06)
        mock_fetch.assert_called_once()
        call_args = mock_fetch.call_args[0]
        self.assertEqual(call_args[0], '000001')
        self.assertEqual(call_args[1], '20250104')  # next day after cache_last
        self.assertEqual(call_args[2], '20250106')

    @patch('quantia.core.stockfetch._filter_ohlc_outliers', side_effect=lambda d, c='': (d, 0))
    @patch('quantia.core.stockfetch._fetch_from_sources', return_value=None)
    @patch('quantia.core.stockfetch._write_cache_meta')
    @patch('quantia.core.stockfetch._read_cache_meta', return_value={'filtered_version': 2})
    @patch('quantia.core.stockfetch.pd.read_pickle')
    @patch('quantia.core.stockfetch.os.path.isfile', return_value=True)
    def test_cache_fully_covers_date_range(self, mock_isfile, mock_pickle, mock_read_meta,
                                            mock_write_meta, mock_fetch, mock_filter):
        """When cache fully covers requested range, no fetch should happen."""
        from quantia.core.stockfetch import stock_hist_cache_incremental
        cached = self._make_cached_df(['2025-01-02', '2025-01-03', '2025-01-06'])
        mock_pickle.return_value = cached

        result = stock_hist_cache_incremental('000001', '20250102', '20250106', is_cache=True)
        mock_fetch.assert_not_called()
        self.assertIsNotNone(result)


# ============================================================
# 3f. stockfetch — read_hist_from_cache (mocked)
# ============================================================
class TestReadHistFromCache(unittest.TestCase):
    """Tests for read_hist_from_cache with mocked file read."""

    @patch('quantia.core.stockfetch.read_stock_hist_from_cache', return_value=None)
    @patch('quantia.lib.trade_time.get_trade_hist_interval', return_value=('20200101', True))
    def test_returns_none_when_no_cache(self, mock_interval, mock_read):
        from quantia.core.stockfetch import read_hist_from_cache
        result = read_hist_from_cache(('2025-03-15', '000001'))
        self.assertIsNone(result)
        mock_read.assert_called_once()

    @patch('quantia.core.stockfetch.read_stock_hist_from_cache')
    @patch('quantia.lib.trade_time.get_trade_hist_interval', return_value=('20200101', True))
    def test_returns_data_when_cache_exists(self, mock_interval, mock_read):
        from quantia.core.stockfetch import read_hist_from_cache
        df = pd.DataFrame({'date': ['2025-01-02'], 'close': [10.0]})
        mock_read.return_value = df
        result = read_hist_from_cache(('2025-03-15', '000001'))
        self.assertIsNotNone(result)

    @patch('quantia.core.stockfetch.read_stock_hist_from_cache', return_value=None)
    @patch('quantia.lib.trade_time.get_trade_hist_interval', return_value=('20200101', True))
    def test_passes_correct_code_to_cache(self, mock_interval, mock_read):
        from quantia.core.stockfetch import read_hist_from_cache
        read_hist_from_cache(('2025-03-15', '600519'))
        call_args = mock_read.call_args[0]
        self.assertEqual(call_args[0], '600519')


# ============================================================
# 4. singleton_stock — mocked singletons
# ============================================================
class TestSingletonStock(unittest.TestCase):
    """Tests for stock_data and stock_hist_data singleton behavior."""

    def _clear_singleton(self, cls):
        from quantia.lib.singleton_type import singleton_type
        with singleton_type.single_lock:
            if hasattr(cls, '_instance'):
                del cls._instance

    def tearDown(self):
        from quantia.core.singleton_stock import stock_data, stock_hist_data
        self._clear_singleton(stock_data)
        self._clear_singleton(stock_hist_data)

    @patch('quantia.core.singleton_stock.stf.fetch_stocks')
    def test_stock_data_returns_data(self, mock_fetch):
        from quantia.core.singleton_stock import stock_data
        mock_fetch.return_value = pd.DataFrame({'code': ['000001'], 'name': ['平安银行']})
        sd = stock_data('2025-03-15')
        self.assertIsNotNone(sd.get_data())
        self.assertEqual(len(sd.get_data()), 1)

    @patch('quantia.core.singleton_stock.stf.fetch_stocks')
    def test_stock_data_handles_exception(self, mock_fetch):
        from quantia.core.singleton_stock import stock_data
        mock_fetch.side_effect = Exception("API error")
        sd = stock_data('2025-03-15')
        self.assertIsNone(sd.get_data())

    @patch('quantia.core.singleton_stock.stf.fetch_stocks', return_value=None)
    def test_stock_data_returns_none_when_fetch_fails(self, mock_fetch):
        from quantia.core.singleton_stock import stock_data
        sd = stock_data('2025-03-15')
        self.assertIsNone(sd.get_data())


# ============================================================
# 5. singleton_trade_date — mocked singleton
# ============================================================
class TestSingletonTradeDate(unittest.TestCase):
    """Tests for stock_trade_date singleton, refresh, and cross-midnight detection."""

    def _clear_singleton(self, cls):
        from quantia.lib.singleton_type import singleton_type
        with singleton_type.single_lock:
            if hasattr(cls, '_instance'):
                del cls._instance

    def tearDown(self):
        from quantia.core.singleton_trade_date import stock_trade_date
        self._clear_singleton(stock_trade_date)

    @patch('quantia.core.singleton_trade_date.stf.fetch_stocks_trade_date')
    def test_trade_date_loads_data(self, mock_fetch):
        from quantia.core.singleton_trade_date import stock_trade_date
        self._clear_singleton(stock_trade_date)
        # Need > 30 entries to pass the check
        many_dates = {datetime.date(2020, 1, i + 1) for i in range(31)}
        mock_fetch.return_value = many_dates
        td = stock_trade_date()
        self.assertIsNotNone(td.get_data())
        self.assertGreater(len(td.get_data()), 30)

    @patch('quantia.core.singleton_trade_date.stf.fetch_stocks_trade_date', return_value=None)
    def test_trade_date_handles_none(self, mock_fetch):
        from quantia.core.singleton_trade_date import stock_trade_date
        self._clear_singleton(stock_trade_date)
        td = stock_trade_date()
        self.assertIsNone(td.get_data())

    @patch('quantia.core.singleton_trade_date.stf.fetch_stocks_trade_date')
    def test_trade_date_rejects_too_few_results(self, mock_fetch):
        from quantia.core.singleton_trade_date import stock_trade_date
        self._clear_singleton(stock_trade_date)
        mock_fetch.return_value = {datetime.date(2025, 1, 2)}  # only 1 date
        td = stock_trade_date()
        # Should keep data as None since result has <= 30 items
        self.assertIsNone(td.get_data())


# ============================================================
# 6. singleton_stock_web_module_data
# ============================================================
class TestSingletonStockWebModuleData(unittest.TestCase):
    """Tests for stock_web_module_data registration."""

    def test_has_data_list(self):
        from quantia.core.singleton_stock_web_module_data import stock_web_module_data
        swmd = stock_web_module_data()
        data_list = swmd.get_data_list()
        self.assertIsInstance(data_list, list)
        self.assertGreater(len(data_list), 10)

    def test_data_list_entries_are_web_module_data(self):
        from quantia.core.singleton_stock_web_module_data import stock_web_module_data
        from quantia.core.web_module_data import web_module_data
        swmd = stock_web_module_data()
        for entry in swmd.get_data_list():
            self.assertIsInstance(entry, web_module_data)

    def test_get_data_by_table_name(self):
        from quantia.core.singleton_stock_web_module_data import stock_web_module_data
        swmd = stock_web_module_data()
        result = swmd.get_data('cn_stock_spot')
        self.assertIsNotNone(result)
        self.assertEqual(result.table_name, 'cn_stock_spot')

    def test_get_data_returns_none_for_unknown_table(self):
        from quantia.core.singleton_stock_web_module_data import stock_web_module_data
        swmd = stock_web_module_data()
        result = swmd.get_data('nonexistent_table')
        self.assertIsNone(result)

    def test_get_data_returns_none_for_none(self):
        from quantia.core.singleton_stock_web_module_data import stock_web_module_data
        swmd = stock_web_module_data()
        result = swmd.get_data(None)
        self.assertIsNone(result)

    def test_backtest_table_registered(self):
        from quantia.core.singleton_stock_web_module_data import stock_web_module_data
        swmd = stock_web_module_data()
        result = swmd.get_data('cn_stock_backtest')
        self.assertIsNotNone(result)
        self.assertEqual(result.name, '回测验证')

    def test_etf_spot_registered(self):
        from quantia.core.singleton_stock_web_module_data import stock_web_module_data
        swmd = stock_web_module_data()
        result = swmd.get_data('cn_etf_spot')
        self.assertIsNotNone(result)

    def test_index_spot_registered(self):
        from quantia.core.singleton_stock_web_module_data import stock_web_module_data
        swmd = stock_web_module_data()
        result = swmd.get_data('cn_index_spot')
        self.assertIsNotNone(result)

    def test_each_entry_has_url(self):
        from quantia.core.singleton_stock_web_module_data import stock_web_module_data
        swmd = stock_web_module_data()
        for entry in swmd.get_data_list():
            self.assertIn('/quantia/data?table_name=', entry.url)


# ============================================================
# 7. singleton_proxy — mocked proxy pool
# ============================================================
class TestSingletonProxy(unittest.TestCase):
    """Tests for proxys class with mocked HTTP/file IO."""

    def _make_proxy_instance(self):
        """Create a proxys instance with mocked init (no real network/file)."""
        from quantia.core.singleton_proxy import proxys
        with patch.object(proxys, '__init__', lambda self: None):
            p = proxys.__new__(proxys)
            p._lock = threading.RLock()
            p._pool = {}
            p._manual_proxies = []
            p._running = False
            p._initialized = True
            return p

    def test_empty_pool_returns_none(self):
        p = self._make_proxy_instance()
        # Empty pool + no emergency refresh
        p._trigger_emergency_refresh = MagicMock()
        result = p.get_proxies()
        self.assertIsNone(result)

    def test_report_failure_increments_count(self):
        p = self._make_proxy_instance()
        proxy_url = 'http://1.2.3.4:8080'
        p._pool[proxy_url] = {"fail_count": 0, "last_verified": time.time(), "manual": False}
        p.report_failure(proxy_url)
        self.assertEqual(p._pool[proxy_url]["fail_count"], 1)

    def test_report_failure_removes_after_threshold(self):
        from quantia.core.singleton_proxy import PROXY_MAX_FAIL_COUNT
        p = self._make_proxy_instance()
        proxy_url = 'http://1.2.3.4:8080'
        p._pool[proxy_url] = {"fail_count": PROXY_MAX_FAIL_COUNT - 1,
                               "last_verified": time.time(), "manual": False}
        p.report_failure(proxy_url)
        self.assertNotIn(proxy_url, p._pool)

    def test_report_failure_does_not_remove_manual_proxy(self):
        from quantia.core.singleton_proxy import PROXY_MAX_FAIL_COUNT
        p = self._make_proxy_instance()
        proxy_url = 'http://manual.proxy:8080'
        p._pool[proxy_url] = {"fail_count": PROXY_MAX_FAIL_COUNT - 1,
                               "last_verified": time.time(), "manual": True}
        p.report_failure(proxy_url)
        # Manual proxies should not be removed, just increment count
        self.assertIn(proxy_url, p._pool)

    def test_report_success_resets_fail_count(self):
        p = self._make_proxy_instance()
        proxy_url = 'http://1.2.3.4:8080'
        p._pool[proxy_url] = {"fail_count": 2, "last_verified": time.time() - 100}
        p.report_success(proxy_url)
        self.assertEqual(p._pool[proxy_url]["fail_count"], 0)
        # last_verified should be updated
        self.assertAlmostEqual(p._pool[proxy_url]["last_verified"], time.time(), delta=2)

    def test_report_failure_none_proxy_is_noop(self):
        p = self._make_proxy_instance()
        p.report_failure(None)  # should not raise

    def test_report_success_none_proxy_is_noop(self):
        p = self._make_proxy_instance()
        p.report_success(None)  # should not raise

    def test_pool_size_counts_available(self):
        from quantia.core.singleton_proxy import PROXY_MAX_FAIL_COUNT
        p = self._make_proxy_instance()
        p._pool = {
            'http://a:80': {"fail_count": 0, "last_verified": time.time()},
            'http://b:80': {"fail_count": PROXY_MAX_FAIL_COUNT, "last_verified": time.time()},
            'http://c:80': {"fail_count": 1, "last_verified": time.time()},
        }
        self.assertEqual(p.pool_size(), 2)  # a and c are available

    @patch('random.random', return_value=0.99)  # force proxy selection (not direct)
    def test_get_proxies_returns_proxy_from_pool(self, mock_random):
        p = self._make_proxy_instance()
        now = time.time()
        p._pool = {
            'http://a:80': {"fail_count": 0, "last_verified": now, "https_ok": False},
        }
        p._trigger_emergency_refresh = MagicMock()
        result = p.get_proxies()
        # Should return a dict with 'http' key
        self.assertIsNotNone(result)
        self.assertIn('http', result)

    @patch('random.random', return_value=0.01)  # force direct connection
    def test_get_proxies_returns_none_for_direct(self, mock_random):
        p = self._make_proxy_instance()
        now = time.time()
        p._pool = {
            'http://a:80': {"fail_count": 0, "last_verified": now, "https_ok": False},
        }
        result = p.get_proxies()
        self.assertIsNone(result)

    def test_report_success_unknown_proxy_is_noop(self):
        p = self._make_proxy_instance()
        p.report_success('http://unknown:80')  # should not raise


# ============================================================
# 8. eastmoney_fetcher — mocked HTTP
# ============================================================
class TestEastmoneyFetcher(unittest.TestCase):
    """Tests for eastmoney_fetcher with mocked HTTP responses."""

    def _make_fetcher(self):
        from quantia.core.eastmoney_fetcher import eastmoney_fetcher
        fetcher = eastmoney_fetcher()
        return fetcher

    @patch('quantia.core.singleton_proxy.proxys')
    def test_make_request_success(self, mock_proxys_cls):
        fetcher = self._make_fetcher()
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_response
        fetcher._thread_local.session = mock_session

        mock_proxy_inst = MagicMock()
        mock_proxy_inst.get_proxies.return_value = None
        mock_proxys_cls.return_value = mock_proxy_inst

        result = fetcher.make_request('http://example.com/api', retry=1)
        self.assertEqual(result, mock_response)
        mock_session.get.assert_called_once()

    @patch('quantia.core.singleton_proxy.proxys')
    def test_make_request_retries_on_failure(self, mock_proxys_cls):
        import requests
        fetcher = self._make_fetcher()
        mock_session = MagicMock()
        # First call fails, second succeeds
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_session.get.side_effect = [
            requests.exceptions.ConnectionError("Connection refused"),
            mock_response
        ]
        fetcher._thread_local.session = mock_session

        mock_proxy_inst = MagicMock()
        mock_proxy_inst.get_proxies.return_value = None
        mock_proxys_cls.return_value = mock_proxy_inst

        result = fetcher.make_request('http://example.com/api', retry=2, timeout=5)
        self.assertEqual(result, mock_response)
        self.assertEqual(mock_session.get.call_count, 2)

    @patch('quantia.core.singleton_proxy.proxys')
    def test_make_request_raises_after_all_retries(self, mock_proxys_cls):
        import requests
        fetcher = self._make_fetcher()
        mock_session = MagicMock()
        mock_session.get.side_effect = requests.exceptions.ConnectionError("fail")
        fetcher._thread_local.session = mock_session

        mock_proxy_inst = MagicMock()
        mock_proxy_inst.get_proxies.return_value = None
        mock_proxys_cls.return_value = mock_proxy_inst

        with self.assertRaises(requests.exceptions.ConnectionError):
            fetcher.make_request('http://example.com/api', retry=1, timeout=5)

    def test_get_cookie_from_env(self):
        fetcher = self._make_fetcher()
        with patch.dict(os.environ, {'EAST_MONEY_COOKIE': 'test_cookie_value'}):
            cookie = fetcher._get_cookie()
            self.assertEqual(cookie, 'test_cookie_value')

    def test_get_cookie_default_empty(self):
        fetcher = self._make_fetcher()
        with patch.dict(os.environ, {}, clear=True):
            # Also mock the file not existing
            with patch('builtins.open', side_effect=FileNotFoundError):
                with patch('pathlib.Path.exists', return_value=False):
                    cookie = fetcher._get_cookie()
                    self.assertEqual(cookie, '')

    def test_create_session_has_user_agent(self):
        fetcher = self._make_fetcher()
        session = fetcher._create_session()
        self.assertIn('User-Agent', session.headers)
        self.assertIn('Mozilla', session.headers['User-Agent'])

    def test_create_session_has_referer(self):
        fetcher = self._make_fetcher()
        session = fetcher._create_session()
        self.assertIn('Referer', session.headers)
        self.assertIn('eastmoney', session.headers['Referer'])

    def test_thread_local_session_isolation(self):
        """Each thread should get its own session."""
        fetcher = self._make_fetcher()
        sessions = []
        barrier = threading.Barrier(2)

        def get_session():
            s = fetcher._get_thread_session()
            barrier.wait()  # ensure both threads hold their session simultaneously
            sessions.append(s)

        t1 = threading.Thread(target=get_session)
        t2 = threading.Thread(target=get_session)
        t1.start(); t2.start()
        t1.join(); t2.join()

        # Two threads should get different session objects
        self.assertEqual(len(sessions), 2)
        self.assertIsNot(sessions[0], sessions[1])

    def test_update_cookie(self):
        fetcher = self._make_fetcher()
        fetcher.update_cookie('new_cookie_123')
        self.assertIn('Cookie', fetcher.session.cookies)


# ============================================================
# Run
# ============================================================
if __name__ == '__main__':
    unittest.main()
