#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Comprehensive tests for kline, indicator, and pattern modules.

Covers:
  - quantia.core.kline.visualization.get_plot_kline
  - quantia.core.kline.indicator_web_dic.indicators_dic
  - quantia.core.kline.cyq.CYQCalculator
  - quantia.core.indicator.calculate_indicator (get_indicators, get_indicator, _fillna, _fill_nan_inf)
  - quantia.core.pattern.pattern_recognitions (get_pattern_recognitions, get_pattern_recognition)
"""

import sys
import os
import unittest
from unittest.mock import patch, MagicMock
import numpy as np
import pandas as pd
import talib as tl

# Ensure project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# ---------------------------------------------------------------------------
# Helper: synthetic OHLCV DataFrames
# ---------------------------------------------------------------------------

def _make_ohlcv(n=100, start_price=20.0, seed=42):
    """Return a DataFrame with n rows of realistic daily OHLCV + amount + p_change + turnover."""
    rng = np.random.RandomState(seed)
    dates = pd.bdate_range(end='2026-03-18', periods=n)
    close = np.empty(n)
    close[0] = start_price
    for i in range(1, n):
        close[i] = close[i - 1] * (1 + rng.uniform(-0.05, 0.05))
    high = close * (1 + rng.uniform(0.001, 0.03, n))
    low = close * (1 - rng.uniform(0.001, 0.03, n))
    open_ = low + (high - low) * rng.uniform(0.2, 0.8, n)
    volume = rng.randint(100000, 5000000, n).astype(float)
    amount = volume * close  # approximate
    p_change = np.insert(np.diff(close) / close[:-1] * 100, 0, 0.0)
    turnover = rng.uniform(0.5, 10.0, n)  # turnover rate percent
    quote_change = p_change.copy()

    df = pd.DataFrame({
        'date': dates.strftime('%Y-%m-%d'),
        'open': np.round(open_, 2),
        'close': np.round(close, 2),
        'high': np.round(high, 2),
        'low': np.round(low, 2),
        'volume': volume,
        'amount': np.round(amount, 2),
        'p_change': np.round(p_change, 2),
        'turnover': np.round(turnover, 2),
        'quote_change': np.round(quote_change, 2),
    })
    return df


def _make_small_ohlcv(n=30, seed=7):
    """Smaller DataFrame for CYQ tests.  Includes turnover (rate %) column."""
    return _make_ohlcv(n=n, start_price=15.0, seed=seed)


# ===========================================================================
# 1. indicator_web_dic tests
# ===========================================================================

class TestIndicatorWebDic(unittest.TestCase):
    """Tests for quantia.core.kline.indicator_web_dic.indicators_dic."""

    @classmethod
    def setUpClass(cls):
        import quantia.core.kline.indicator_web_dic as iwd
        cls.indicators_dic = iwd.indicators_dic

    def test_is_non_empty_list(self):
        self.assertIsInstance(self.indicators_dic, list)
        self.assertGreater(len(self.indicators_dic), 0)

    def test_each_entry_has_required_keys(self):
        for entry in self.indicators_dic:
            self.assertIn('title', entry, f"Missing 'title' in {entry}")
            self.assertIn('desc', entry, f"Missing 'desc' in {entry}")
            self.assertIn('dic', entry, f"Missing 'dic' in {entry}")
            # dic should be a tuple/list of column names
            self.assertIsInstance(entry['dic'], (tuple, list))
            self.assertGreater(len(entry['dic']), 0)

    def test_known_indicators_present(self):
        titles = {e['title'] for e in self.indicators_dic}
        for name in ('MACD', 'KDJ', 'BOLL', 'RSI', 'CCI', 'ATR', 'OBV', 'SAR'):
            self.assertIn(name, titles, f"{name} not found in indicators_dic titles")

    def test_macd_columns(self):
        macd_entry = [e for e in self.indicators_dic if e['title'] == 'MACD'][0]
        self.assertIn('macd', macd_entry['dic'])
        self.assertIn('macds', macd_entry['dic'])
        self.assertIn('macdh', macd_entry['dic'])

    def test_kdj_columns(self):
        kdj_entry = [e for e in self.indicators_dic if e['title'] == 'KDJ'][0]
        self.assertIn('kdjk', kdj_entry['dic'])
        self.assertIn('kdjd', kdj_entry['dic'])
        self.assertIn('kdjj', kdj_entry['dic'])

    def test_boll_columns(self):
        boll_entry = [e for e in self.indicators_dic if e['title'] == 'BOLL'][0]
        for col in ('close', 'boll_ub', 'boll', 'boll_lb'):
            self.assertIn(col, boll_entry['dic'])

    def test_desc_is_string(self):
        for entry in self.indicators_dic:
            self.assertIsInstance(entry['desc'], str)
            self.assertGreater(len(entry['desc'].strip()), 0)


# ===========================================================================
# 2. CYQCalculator tests
# ===========================================================================

class TestCYQCalculator(unittest.TestCase):
    """Tests for quantia.core.kline.cyq.CYQCalculator."""

    @classmethod
    def setUpClass(cls):
        from quantia.core.kline.cyq import CYQCalculator
        cls.CYQCalculator = CYQCalculator
        # Build a 330-row dataset (cyq_days=210 + range=120)
        cls.df = _make_ohlcv(n=330, start_price=18.0, seed=99)

    def _make_calc(self, **kwargs):
        defaults = dict(accuracy_factor=150, crange=120, cyq_days=210)
        defaults.update(kwargs)
        return self.CYQCalculator(self.df, **defaults)

    # --- basic structure ---
    def test_calc_returns_object_with_expected_attrs(self):
        calc = self._make_calc()
        result = calc.calc(index=330)  # last bar relative to range
        for attr in ('x', 'y', 'benefit_part', 'avg_cost', 'percent_chips', 'b', 'd', 't'):
            self.assertTrue(hasattr(result, attr), f"Missing attribute '{attr}'")

    def test_x_and_y_lengths_match_factor(self):
        factor = 150
        calc = self._make_calc(accuracy_factor=factor)
        result = calc.calc(index=330)
        self.assertEqual(len(result.x), factor)
        self.assertEqual(len(result.y), factor)

    # --- benefit ratio ---
    def test_benefit_part_between_0_and_1(self):
        calc = self._make_calc()
        result = calc.calc(index=330)
        self.assertGreaterEqual(result.benefit_part, 0.0)
        self.assertLessEqual(result.benefit_part, 1.0)

    # --- avg_cost ---
    def test_avg_cost_is_numeric_string(self):
        calc = self._make_calc()
        result = calc.calc(index=330)
        cost = float(result.avg_cost)
        self.assertGreater(cost, 0)

    # --- percent_chips / concentration ---
    def test_percent_chips_keys(self):
        calc = self._make_calc()
        result = calc.calc(index=330)
        self.assertIn('90', result.percent_chips)
        self.assertIn('70', result.percent_chips)

    def test_concentration_non_negative(self):
        calc = self._make_calc()
        result = calc.calc(index=330)
        for pct_key in ('90', '70'):
            conc = result.percent_chips[pct_key]['concentration']
            self.assertGreaterEqual(conc, 0.0)

    def test_price_range_has_two_elements(self):
        calc = self._make_calc()
        result = calc.calc(index=330)
        for pct_key in ('90', '70'):
            pr = result.percent_chips[pct_key]['priceRange']
            self.assertEqual(len(pr), 2)
            self.assertLessEqual(float(pr[0]), float(pr[1]))

    # --- boundary ---
    def test_boundary_within_factor(self):
        factor = 150
        calc = self._make_calc(accuracy_factor=factor)
        result = calc.calc(index=330)
        self.assertGreaterEqual(result.b, 0)
        self.assertLessEqual(result.b, factor)

    # --- edge: first valid bar ---
    def test_first_bar_index(self):
        """Calc at the earliest possible index (index == crange + cyq_days)."""
        # With crange=120 and cyq_days=210, the earliest valid index is 330
        # (start=0, end=210, kdata has 210 rows).
        # Use a smaller cyq_days so index=150 is valid with our 330-row df.
        calc = self.CYQCalculator(self.df, accuracy_factor=150, crange=120, cyq_days=30)
        result = calc.calc(index=150)
        self.assertIsNotNone(result.x)

    # --- edge: last bar ---
    def test_last_bar_index(self):
        calc = self._make_calc()
        result = calc.calc(index=330)
        self.assertIsNotNone(result.d)

    # --- trading days recorded ---
    def test_trading_days(self):
        calc = self._make_calc(cyq_days=210)
        result = calc.calc(index=330)
        self.assertEqual(result.t, 210)

    # --- y range monotonically increasing ---
    def test_y_range_increasing(self):
        calc = self._make_calc()
        result = calc.calc(index=330)
        for i in range(1, len(result.y)):
            self.assertGreaterEqual(result.y[i], result.y[i - 1])

    # --- chips sum positive ---
    def test_chips_sum_positive(self):
        calc = self._make_calc()
        result = calc.calc(index=330)
        self.assertGreater(sum(result.x), 0)

    # --- different factor sizes ---
    def test_small_factor(self):
        calc = self._make_calc(accuracy_factor=50)
        result = calc.calc(index=330)
        self.assertEqual(len(result.x), 50)

    def test_large_factor(self):
        calc = self._make_calc(accuracy_factor=500)
        result = calc.calc(index=330)
        self.assertEqual(len(result.x), 500)


# ===========================================================================
# 3. calculate_indicator tests
# ===========================================================================

class TestFillna(unittest.TestCase):
    """Tests for _fillna and _fill_nan_inf helper functions."""

    @classmethod
    def setUpClass(cls):
        from quantia.core.indicator.calculate_indicator import _fillna, _fill_nan_inf
        cls._fillna = staticmethod(_fillna)
        cls._fill_nan_inf = staticmethod(_fill_nan_inf)

    def test_fillna_replaces_nan(self):
        df = pd.DataFrame({'a': [1.0, np.nan, 3.0, np.nan]})
        self._fillna(df, 'a')
        self.assertFalse(df['a'].isna().any())
        self.assertEqual(df['a'].iloc[1], 0.0)
        self.assertEqual(df['a'].iloc[3], 0.0)

    def test_fillna_preserves_values(self):
        df = pd.DataFrame({'a': [1.0, 2.0, 3.0]})
        self._fillna(df, 'a')
        self.assertEqual(list(df['a']), [1.0, 2.0, 3.0])

    def test_fill_nan_inf_replaces_inf(self):
        df = pd.DataFrame({'b': [1.0, np.inf, -np.inf, np.nan, 5.0]})
        self._fill_nan_inf(df, 'b')
        self.assertFalse(df['b'].isna().any())
        self.assertFalse(np.isinf(df['b']).any())
        self.assertEqual(df['b'].iloc[1], 0.0)
        self.assertEqual(df['b'].iloc[2], 0.0)
        self.assertEqual(df['b'].iloc[3], 0.0)

    def test_fill_nan_inf_preserves_finite(self):
        df = pd.DataFrame({'b': [10.0, -3.5, 0.0]})
        self._fill_nan_inf(df, 'b')
        self.assertEqual(list(df['b']), [10.0, -3.5, 0.0])

    def test_fillna_all_nan(self):
        df = pd.DataFrame({'c': [np.nan, np.nan, np.nan]})
        self._fillna(df, 'c')
        self.assertTrue((df['c'] == 0.0).all())

    def test_fill_nan_inf_all_inf(self):
        df = pd.DataFrame({'c': [np.inf, -np.inf, np.inf]})
        self._fill_nan_inf(df, 'c')
        self.assertTrue((df['c'] == 0.0).all())


class TestGetIndicators(unittest.TestCase):
    """Tests for get_indicators with synthetic OHLCV data."""

    @classmethod
    def setUpClass(cls):
        from quantia.core.indicator.calculate_indicator import get_indicators
        cls.get_indicators = staticmethod(get_indicators)
        cls.df = _make_ohlcv(n=200, seed=42)

    def test_returns_dataframe(self):
        result = self.get_indicators(self.df.copy())
        self.assertIsInstance(result, pd.DataFrame)

    def test_macd_columns_present(self):
        result = self.get_indicators(self.df.copy())
        for col in ('macd', 'macds', 'macdh'):
            self.assertIn(col, result.columns)

    def test_kdj_columns_present(self):
        result = self.get_indicators(self.df.copy())
        for col in ('kdjk', 'kdjd', 'kdjj'):
            self.assertIn(col, result.columns)

    def test_rsi_columns_present(self):
        result = self.get_indicators(self.df.copy())
        for col in ('rsi', 'rsi_6', 'rsi_12', 'rsi_24'):
            self.assertIn(col, result.columns)

    def test_boll_columns_present(self):
        result = self.get_indicators(self.df.copy())
        for col in ('boll', 'boll_ub', 'boll_lb'):
            self.assertIn(col, result.columns)

    def test_ma_columns_present(self):
        result = self.get_indicators(self.df.copy())
        for col in ('ma10', 'ma20', 'ma50', 'ma200'):
            self.assertIn(col, result.columns)

    def test_volume_columns_present(self):
        result = self.get_indicators(self.df.copy())
        for col in ('vol_5', 'vol_10'):
            self.assertIn(col, result.columns)

    def test_recent_bars_not_all_nan(self):
        """Values for the last rows should be numeric, not NaN."""
        result = self.get_indicators(self.df.copy())
        last_row = result.iloc[-1]
        for col in ('macd', 'rsi', 'boll', 'kdjk', 'cci', 'atr', 'obv'):
            val = last_row[col]
            self.assertFalse(np.isnan(val), f"Last row {col} is NaN")

    def test_no_inf_in_output(self):
        result = self.get_indicators(self.df.copy())
        numeric_cols = result.select_dtypes(include=[np.number]).columns
        for col in numeric_cols:
            self.assertFalse(np.isinf(result[col]).any(), f"Inf found in column {col}")

    def test_threshold_limits_rows(self):
        result = self.get_indicators(self.df.copy(), threshold=50)
        self.assertEqual(len(result), 50)

    def test_end_date_filters(self):
        mid_date = self.df.iloc[99]['date']
        result = self.get_indicators(self.df.copy(), end_date=mid_date, threshold=None)
        # All dates should be <= mid_date
        result_dates = pd.to_datetime(result['date'])
        self.assertTrue((result_dates <= pd.Timestamp(mid_date)).all())

    def test_calc_threshold_limits_input(self):
        result = self.get_indicators(self.df.copy(), threshold=None, calc_threshold=80)
        # The output should have at most 80 rows (calc_threshold tails the input)
        self.assertLessEqual(len(result), 80)

    def test_non_dataframe_returns_none(self):
        result = self.get_indicators([1, 2, 3])
        self.assertIsNone(result)

    def test_supertrend_columns(self):
        result = self.get_indicators(self.df.copy())
        for col in ('supertrend', 'supertrend_ub', 'supertrend_lb'):
            self.assertIn(col, result.columns)

    def test_psy_columns(self):
        result = self.get_indicators(self.df.copy())
        for col in ('psy', 'psyma'):
            self.assertIn(col, result.columns)

    def test_ene_columns(self):
        result = self.get_indicators(self.df.copy())
        for col in ('ene', 'ene_ue', 'ene_le'):
            self.assertIn(col, result.columns)

    def test_dmi_columns(self):
        result = self.get_indicators(self.df.copy())
        for col in ('pdi', 'mdi', 'dx', 'adx', 'adxr'):
            self.assertIn(col, result.columns)

    def test_wr_columns(self):
        result = self.get_indicators(self.df.copy())
        for col in ('wr_6', 'wr_10', 'wr_14'):
            self.assertIn(col, result.columns)

    def test_roc_columns(self):
        result = self.get_indicators(self.df.copy())
        for col in ('roc', 'rocma', 'rocema'):
            self.assertIn(col, result.columns)

    def test_bias_columns(self):
        result = self.get_indicators(self.df.copy())
        for col in ('bias', 'bias_12', 'bias_24'):
            self.assertIn(col, result.columns)

    def test_emv_columns(self):
        result = self.get_indicators(self.df.copy())
        for col in ('emv', 'emva'):
            self.assertIn(col, result.columns)

    def test_vr_column(self):
        result = self.get_indicators(self.df.copy())
        self.assertIn('vr', result.columns)

    def test_wt_columns(self):
        result = self.get_indicators(self.df.copy())
        for col in ('wt1', 'wt2'):
            self.assertIn(col, result.columns)

    def test_fi_columns(self):
        result = self.get_indicators(self.df.copy())
        for col in ('fi', 'force_2', 'force_13'):
            self.assertIn(col, result.columns)


class TestGetIndicator(unittest.TestCase):
    """Tests for the single-stock get_indicator wrapper."""

    @classmethod
    def setUpClass(cls):
        from quantia.core.indicator.calculate_indicator import get_indicator
        cls.get_indicator = staticmethod(get_indicator)
        cls.df = _make_ohlcv(n=150, seed=55)

    def test_returns_series(self):
        code_name = ('2026-03-18', '000001')
        stock_column = ['date', 'code', 'macd', 'rsi', 'kdjk']
        result = self.get_indicator(code_name, self.df.copy(), stock_column)
        self.assertIsInstance(result, pd.Series)

    def test_empty_df_returns_zeros(self):
        code_name = ('2026-03-18', '000001')
        stock_column = ['date', 'code', 'macd', 'rsi']
        empty_df = self.df.iloc[:1].copy()
        result = self.get_indicator(code_name, empty_df, stock_column)
        self.assertIsInstance(result, pd.Series)
        # Non-date/code values should be 0
        self.assertEqual(result['macd'], 0)
        self.assertEqual(result['rsi'], 0)

    def test_result_has_correct_index(self):
        code_name = ('2026-03-18', '000001')
        stock_column = ['date', 'code', 'macd', 'rsi', 'boll']
        result = self.get_indicator(code_name, self.df.copy(), stock_column)
        self.assertEqual(list(result.index), stock_column)


# ===========================================================================
# 4. pattern_recognitions tests
# ===========================================================================

class TestPatternRecognitions(unittest.TestCase):
    """Tests for get_pattern_recognitions and get_pattern_recognition."""

    @classmethod
    def setUpClass(cls):
        from quantia.core.pattern.pattern_recognitions import get_pattern_recognitions, get_pattern_recognition
        import quantia.core.tablestructure as tbs
        cls.get_pattern_recognitions = staticmethod(get_pattern_recognitions)
        cls.get_pattern_recognition = staticmethod(get_pattern_recognition)
        cls.stock_column = tbs.STOCK_KLINE_PATTERN_DATA['columns']
        cls.df = _make_ohlcv(n=150, seed=77)

    def test_returns_dataframe(self):
        result = self.get_pattern_recognitions(self.df.copy(), self.stock_column)
        self.assertIsInstance(result, pd.DataFrame)

    def test_pattern_columns_added(self):
        result = self.get_pattern_recognitions(self.df.copy(), self.stock_column)
        for k in self.stock_column:
            self.assertIn(k, result.columns, f"Pattern column '{k}' missing from output")

    def test_pattern_values_are_integer_type(self):
        result = self.get_pattern_recognitions(self.df.copy(), self.stock_column)
        sample_col = list(self.stock_column.keys())[0]
        # talib CDL functions return integers (100, -100, 0)
        self.assertTrue(np.issubdtype(result[sample_col].dtype, np.integer))

    def test_threshold_limits_output_rows(self):
        result = self.get_pattern_recognitions(self.df.copy(), self.stock_column, threshold=30)
        self.assertEqual(len(result), 30)

    def test_end_date_filtering(self):
        mid_date = self.df.iloc[74]['date']
        result = self.get_pattern_recognitions(self.df.copy(), self.stock_column, end_date=mid_date, threshold=None)
        result_dates = pd.to_datetime(result['date'])
        self.assertTrue((result_dates <= pd.Timestamp(mid_date)).all())

    def test_calc_threshold(self):
        result = self.get_pattern_recognitions(self.df.copy(), self.stock_column, threshold=None, calc_threshold=40)
        self.assertLessEqual(len(result), 40)

    def test_known_pattern_keys(self):
        """Verify well-known pattern columns exist."""
        for key in ('doji', 'hammer', 'engulfing_pattern', 'morning_star', 'evening_star'):
            self.assertIn(key, self.stock_column, f"Expected pattern key '{key}' not in stock_column")

    def test_pattern_values_in_expected_range(self):
        """CDL values should be in {-100, 0, 100} (some have -200/200 for certain patterns)."""
        result = self.get_pattern_recognitions(self.df.copy(), self.stock_column)
        for k in self.stock_column:
            vals = result[k].unique()
            for v in vals:
                self.assertTrue(abs(v) <= 200, f"Unexpected pattern value {v} in column {k}")

    def test_get_pattern_recognition_returns_series_or_none(self):
        code_name = ('2026-03-18', '000001')
        result = self.get_pattern_recognition(code_name, self.df.copy(), self.stock_column)
        # Can return a Series (if any pattern detected) or None
        if result is not None:
            self.assertIsInstance(result, pd.Series)

    def test_get_pattern_recognition_with_date(self):
        import datetime
        dt = datetime.datetime(2026, 3, 18)
        code_name = ('2026-03-18', '000001')
        result = self.get_pattern_recognition(code_name, self.df.copy(), self.stock_column, date=dt)
        # result is Series or None
        self.assertTrue(result is None or isinstance(result, pd.Series))

    def test_get_pattern_recognition_empty_df(self):
        code_name = ('2026-03-18', '000001')
        empty_df = self.df.iloc[:1].copy()
        result = self.get_pattern_recognition(code_name, empty_df, self.stock_column)
        self.assertIsNone(result)


# ===========================================================================
# 5. visualization.get_plot_kline tests (heavily mocked)
# ===========================================================================

class TestGetPlotKline(unittest.TestCase):
    """Tests for quantia.core.kline.visualization.get_plot_kline.

    The function builds a Bokeh layout and calls components().
    We mock heavy dependencies (indicators, patterns, curdoc, database) and
    verify the function returns {'script': ..., 'div': ...} or None.
    """

    @classmethod
    def setUpClass(cls):
        cls.df = _make_ohlcv(n=400, seed=12)

    @patch('quantia.core.kline.visualization.curdoc')
    @patch('quantia.core.kline.visualization.kpr')
    @patch('quantia.core.kline.visualization.idr')
    def test_returns_dict_with_script_and_div(self, mock_idr, mock_kpr, mock_curdoc):
        from quantia.core.kline.visualization import get_plot_kline
        import quantia.core.tablestructure as tbs

        indicator_df = self.df.tail(120).copy()
        # Add minimal columns that visualization expects
        for col in ('ma10', 'ma20', 'ma50', 'ma200', 'vol_5', 'vol_10'):
            if col not in indicator_df.columns:
                indicator_df[col] = indicator_df['close']
        # Add indicator columns referenced in indicator_web_dic
        import quantia.core.kline.indicator_web_dic as iwd
        for conf in iwd.indicators_dic:
            for name in conf['dic']:
                if name not in indicator_df.columns:
                    indicator_df[name] = 0.0

        # Add pattern columns
        stock_column = tbs.STOCK_KLINE_PATTERN_DATA['columns']
        for k in stock_column:
            indicator_df[k] = 0

        mock_idr.get_indicators.return_value = indicator_df.copy()
        mock_kpr.get_pattern_recognitions.return_value = indicator_df.copy()
        mock_curdoc.return_value = MagicMock()

        result = get_plot_kline('000001', self.df.copy(), '2026-03-18', '测试股票')
        self.assertIsNotNone(result)
        self.assertIn('script', result)
        self.assertIn('div', result)
        self.assertIsInstance(result['script'], str)
        self.assertIsInstance(result['div'], str)

    @patch('quantia.core.kline.visualization.kpr')
    @patch('quantia.core.kline.visualization.idr')
    def test_returns_none_when_indicators_none(self, mock_idr, mock_kpr):
        from quantia.core.kline.visualization import get_plot_kline
        mock_idr.get_indicators.return_value = None
        result = get_plot_kline('000001', self.df.copy(), '2026-03-18', '测试股票')
        self.assertIsNone(result)

    @patch('quantia.core.kline.visualization.kpr')
    @patch('quantia.core.kline.visualization.idr')
    def test_returns_none_when_patterns_none(self, mock_idr, mock_kpr):
        from quantia.core.kline.visualization import get_plot_kline
        mock_idr.get_indicators.return_value = self.df.tail(120).copy()
        mock_kpr.get_pattern_recognitions.return_value = None
        result = get_plot_kline('000001', self.df.copy(), '2026-03-18', '测试股票')
        self.assertIsNone(result)


# ===========================================================================
# 6. Integration-style: indicators then patterns pipeline
# ===========================================================================

class TestIndicatorPatternPipeline(unittest.TestCase):
    """End-to-end: compute indicators then run pattern recognition."""

    @classmethod
    def setUpClass(cls):
        from quantia.core.indicator.calculate_indicator import get_indicators
        from quantia.core.pattern.pattern_recognitions import get_pattern_recognitions
        import quantia.core.tablestructure as tbs

        cls.get_indicators = staticmethod(get_indicators)
        cls.get_pattern_recognitions = staticmethod(get_pattern_recognitions)
        cls.stock_column = tbs.STOCK_KLINE_PATTERN_DATA['columns']
        cls.df = _make_ohlcv(n=200, seed=321)

    def test_pipeline_produces_complete_dataframe(self):
        indicator_df = self.get_indicators(self.df.copy(), threshold=120)
        self.assertIsNotNone(indicator_df)

        pattern_df = self.get_pattern_recognitions(indicator_df, self.stock_column, threshold=120)
        self.assertIsNotNone(pattern_df)
        self.assertEqual(len(pattern_df), 120)

        # Verify both indicator and pattern columns are present
        self.assertIn('macd', pattern_df.columns)
        self.assertIn('rsi', pattern_df.columns)
        self.assertIn('doji', pattern_df.columns)
        self.assertIn('hammer', pattern_df.columns)


# ===========================================================================
# Run
# ===========================================================================

if __name__ == '__main__':
    unittest.main()
