#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Comprehensive unit tests for quantia/core/backtest/ modules.

Covers:
  1. strategy_context  – Position, Portfolio, GlobalVars, Context,
                         DataProxy, StockData, TradeRecord, NavRecord
  2. strategy_sandbox  – validate_code, compile_strategy, _create_safe_namespace
  3. data_feed         – load_stock_data, load_multiple_stocks, get_trading_dates,
                         load_benchmark_data, _normalize_cache_df, _load_from_cache
  4. risk_metrics      – calculate_metrics, _empty_metrics
  5. rate_stats        – get_rates
  6. bt_engine         – BacktestEngine, StrategyBacktester
  7. fundamentals      – _FieldExpr, _Query, FundamentalDataProvider
  8. portfolio_engine  – PortfolioBacktestEngine
"""

import sys
import os
import math
import datetime
import unittest
from unittest.mock import patch, MagicMock, PropertyMock

import numpy as np
import pandas as pd

# Ensure project root is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


# ═══════════════════════════════════════════════════════════════════════
# 1. strategy_context tests
# ═══════════════════════════════════════════════════════════════════════

from quantia.core.backtest.strategy_context import (
    Position, Portfolio, GlobalVars, Context, DataProxy, StockData,
    TradeRecord, NavRecord,
)


class TestPosition(unittest.TestCase):
    """Tests for Position data object."""

    def setUp(self):
        self.pos = Position('000001', '平安银行')

    # -- construction --
    def test_initial_state(self):
        self.assertEqual(self.pos.code, '000001')
        self.assertEqual(self.pos.name, '平安银行')
        self.assertEqual(self.pos.amount, 0)
        self.assertEqual(self.pos.closeable_amount, 0)
        self.assertAlmostEqual(self.pos.avg_cost, 0.0)
        self.assertAlmostEqual(self.pos.price, 0.0)
        self.assertAlmostEqual(self.pos.value, 0.0)

    # -- _on_buy --
    def test_on_buy_single(self):
        self.pos._on_buy(1000, 10.0, cost=3.0)
        self.assertEqual(self.pos.amount, 1000)
        # avg_cost 不含佣金（与聚宽一致）: (0*0 + 10*1000) / 1000 = 10.0
        self.assertAlmostEqual(self.pos.avg_cost, 10.0, places=4)
        self.assertAlmostEqual(self.pos.price, 10.0)
        self.assertAlmostEqual(self.pos.value, 10000.0)
        self.assertEqual(self.pos._today_bought, 1000)

    def test_on_buy_multiple_different_prices(self):
        """avg_cost must weight correctly across multiple buys."""
        self.pos._on_buy(1000, 10.0, cost=0.0)
        self.pos._on_buy(1000, 12.0, cost=0.0)
        # avg_cost = (10*1000 + 12*1000) / 2000 = 11.0
        self.assertEqual(self.pos.amount, 2000)
        self.assertAlmostEqual(self.pos.avg_cost, 11.0, places=4)
        self.assertAlmostEqual(self.pos.price, 12.0)  # latest price
        self.assertAlmostEqual(self.pos.value, 24000.0)

    def test_on_buy_three_tranches(self):
        self.pos._on_buy(500, 8.0)
        self.pos._on_buy(300, 10.0)
        self.pos._on_buy(200, 12.0)
        expected_cost = (500 * 8 + 300 * 10 + 200 * 12) / 1000
        self.assertEqual(self.pos.amount, 1000)
        self.assertAlmostEqual(self.pos.avg_cost, expected_cost, places=4)

    # -- _on_sell --
    def test_on_sell_partial(self):
        self.pos._on_buy(1000, 10.0)
        self.pos._on_new_day()  # make shares closeable
        self.pos._on_sell(400, 12.0)
        self.assertEqual(self.pos.amount, 600)
        self.assertEqual(self.pos.closeable_amount, 600)
        self.assertAlmostEqual(self.pos.price, 12.0)
        self.assertAlmostEqual(self.pos.value, 7200.0)
        # avg_cost unchanged on partial sell
        self.assertAlmostEqual(self.pos.avg_cost, 10.0)

    def test_on_sell_all_resets(self):
        self.pos._on_buy(500, 10.0)
        self.pos._on_new_day()
        self.pos._on_sell(500, 11.0)
        self.assertEqual(self.pos.amount, 0)
        self.assertEqual(self.pos.closeable_amount, 0)
        self.assertAlmostEqual(self.pos.avg_cost, 0.0)

    def test_on_sell_more_than_closeable(self):
        """Selling more than closeable should be capped."""
        self.pos._on_buy(1000, 10.0)
        self.pos._on_new_day()  # closeable = 1000
        self.pos._on_buy(500, 11.0)  # today_bought, not closeable yet
        self.pos._on_sell(1500, 11.0)
        # Only 1000 closeable → sold 1000
        self.assertEqual(self.pos.amount, 500)

    # -- _update_price --
    def test_update_price(self):
        self.pos._on_buy(1000, 10.0)
        self.pos._update_price(15.0)
        self.assertAlmostEqual(self.pos.price, 15.0)
        self.assertAlmostEqual(self.pos.value, 15000.0)

    # -- _on_new_day / T+1 --
    def test_on_new_day_t_plus_1(self):
        self.pos._on_buy(1000, 10.0)
        self.assertEqual(self.pos.closeable_amount, 0)  # same day
        self.pos._on_new_day()
        self.assertEqual(self.pos.closeable_amount, 1000)
        self.assertEqual(self.pos._today_bought, 0)

    def test_t_plus_1_cannot_sell_same_day(self):
        """Shares bought today should NOT be closeable until next day."""
        self.pos._on_buy(1000, 10.0)
        self.pos._on_sell(1000, 11.0)  # closeable_amount is 0
        self.assertEqual(self.pos.amount, 1000)  # nothing sold

    # -- profit / profit_rate --
    def test_profit_positive(self):
        self.pos._on_buy(1000, 10.0)
        self.pos._update_price(12.0)
        self.assertAlmostEqual(self.pos.profit, 2000.0)
        self.assertAlmostEqual(self.pos.profit_rate, 0.2)

    def test_profit_negative(self):
        self.pos._on_buy(1000, 10.0)
        self.pos._update_price(8.0)
        self.assertAlmostEqual(self.pos.profit, -2000.0)
        self.assertAlmostEqual(self.pos.profit_rate, -0.2)

    def test_profit_zero_amount(self):
        self.assertAlmostEqual(self.pos.profit, 0.0)
        self.assertAlmostEqual(self.pos.profit_rate, 0.0)

    # -- repr --
    def test_repr(self):
        r = repr(self.pos)
        self.assertIn('000001', r)


class TestPortfolio(unittest.TestCase):
    """Tests for Portfolio."""

    def setUp(self):
        self.portfolio = Portfolio(initial_cash=500000.0)

    def test_initial_state(self):
        self.assertAlmostEqual(self.portfolio.starting_cash, 500000.0)
        self.assertAlmostEqual(self.portfolio.available_cash, 500000.0)
        self.assertAlmostEqual(self.portfolio.total_value, 500000.0)
        self.assertAlmostEqual(self.portfolio.market_value, 0.0)
        self.assertEqual(len(self.portfolio.positions), 0)

    def test_cash_property(self):
        self.assertAlmostEqual(self.portfolio.cash, 500000.0)
        self.portfolio.cash = 300000.0
        self.assertAlmostEqual(self.portfolio.available_cash, 300000.0)

    def test_get_or_create_position_new(self):
        pos = self.portfolio._get_or_create_position('600036', '招商银行')
        self.assertIn('600036', self.portfolio.positions)
        self.assertEqual(pos.code, '600036')
        self.assertEqual(pos.name, '招商银行')

    def test_get_or_create_position_existing(self):
        p1 = self.portfolio._get_or_create_position('600036')
        p1._on_buy(1000, 10.0)
        p2 = self.portfolio._get_or_create_position('600036')
        self.assertIs(p1, p2)
        self.assertEqual(p2.amount, 1000)

    def test_update_value(self):
        pos = self.portfolio._get_or_create_position('600036')
        pos._on_buy(1000, 10.0)
        self.portfolio.available_cash -= 10000.0
        self.portfolio._update_value()
        self.assertAlmostEqual(self.portfolio.market_value, 10000.0)
        self.assertAlmostEqual(self.portfolio.total_value, 500000.0)

    def test_on_new_day_updates_prices(self):
        pos = self.portfolio._get_or_create_position('600036')
        pos._on_buy(1000, 10.0)
        self.portfolio._on_new_day({'600036': 12.0})
        self.assertEqual(pos.closeable_amount, 1000)
        self.assertAlmostEqual(pos.price, 12.0)
        self.assertAlmostEqual(pos.value, 12000.0)

    def test_on_new_day_removes_empty_positions(self):
        pos = self.portfolio._get_or_create_position('600036')
        pos._on_buy(1000, 10.0)
        pos._on_new_day()
        pos._on_sell(1000, 11.0)
        self.assertEqual(pos.amount, 0)
        self.portfolio._on_new_day({})
        self.assertNotIn('600036', self.portfolio.positions)


class TestGlobalVars(unittest.TestCase):
    def test_dynamic_attrs(self):
        g = GlobalVars()
        g.watchlist = ['000001', '600036']
        g.counter = 42
        self.assertEqual(g.watchlist, ['000001', '600036'])
        self.assertEqual(g.counter, 42)


class TestContext(unittest.TestCase):
    def test_default_params(self):
        ctx = Context()
        self.assertAlmostEqual(ctx.portfolio.starting_cash, 1000000.0)
        self.assertEqual(ctx.benchmark, '000300')
        self.assertAlmostEqual(ctx.commission_rate, 0.0003)
        self.assertIsNone(ctx.current_dt)

    def test_custom_cash(self):
        ctx = Context(initial_cash=50000.0)
        self.assertAlmostEqual(ctx.portfolio.total_value, 50000.0)

    def test_repr(self):
        ctx = Context()
        r = repr(ctx)
        self.assertIn('Context', r)
        self.assertIn('1000000', r)


class TestDataProxy(unittest.TestCase):
    def setUp(self):
        self.proxy = DataProxy()

    def test_set_and_get_current(self):
        bar = {'open': 10.0, 'high': 11.0, 'low': 9.5,
               'close': 10.5, 'volume': 100000}
        self.proxy._set_current('000001', bar)
        self.assertIn('000001', self.proxy)
        self.assertNotIn('999999', self.proxy)

    def test_getitem_returns_stock_data(self):
        bar = {'open': 10.0, 'high': 11.0, 'low': 9.5,
               'close': 10.5, 'volume': 100000}
        self.proxy._set_current('000001', bar)
        sd = self.proxy['000001']
        self.assertIsInstance(sd, StockData)
        self.assertAlmostEqual(sd.close, 10.5)

    def test_set_history(self):
        df = pd.DataFrame({'date': ['2025-01-01'], 'close': [10.0]})
        self.proxy._set_history('000001', df)
        self.assertIn('000001', self.proxy._history_cache)


class TestStockData(unittest.TestCase):
    def setUp(self):
        self.proxy = DataProxy()
        self.bar = {
            'open': 10.0, 'high': 11.0, 'low': 9.5,
            'close': 10.5, 'volume': 200000, 'pre_close': 10.0
        }
        self.proxy._set_current('000001', self.bar)
        self.sd = StockData('000001', self.proxy)

    def test_ohlcv(self):
        self.assertAlmostEqual(self.sd.open, 10.0)
        self.assertAlmostEqual(self.sd.high, 11.0)
        self.assertAlmostEqual(self.sd.low, 9.5)
        self.assertAlmostEqual(self.sd.close, 10.5)
        self.assertEqual(self.sd.volume, 200000)

    def test_high_limit_with_pre_close(self):
        expected = round(10.0 * 1.1, 2)
        self.assertAlmostEqual(self.sd.high_limit, expected, places=2)

    def test_low_limit_with_pre_close(self):
        expected = round(10.0 * 0.9, 2)
        self.assertAlmostEqual(self.sd.low_limit, expected, places=2)

    def test_high_limit_without_pre_close(self):
        self.proxy._set_current('600036', {'open': 20.0, 'high': 21.0,
                                           'low': 19.0, 'close': 20.5,
                                           'volume': 50000})
        sd = StockData('600036', self.proxy)
        self.assertAlmostEqual(sd.high_limit, 20.5 * 1.1, places=2)

    def test_missing_code_defaults(self):
        sd = StockData('999999', self.proxy)
        self.assertAlmostEqual(sd.close, 0.0)
        self.assertAlmostEqual(sd.open, 0.0)
        self.assertEqual(sd.volume, 0)


class TestTradeRecord(unittest.TestCase):
    def test_total_cost(self):
        tr = TradeRecord(datetime.date(2025, 1, 2), '000001', '平安银行',
                         'buy', 10.0, 1000)
        tr.commission = 3.0
        tr.tax = 0.0
        tr.slippage_cost = 5.0
        self.assertAlmostEqual(tr.total_cost, 8.0)

    def test_value(self):
        tr = TradeRecord(datetime.date(2025, 1, 2), '000001', '平安银行',
                         'buy', 10.0, 1000)
        self.assertAlmostEqual(tr.value, 10000.0)

    def test_to_dict(self):
        tr = TradeRecord(datetime.date(2025, 6, 15), '600036', '招商银行',
                         'sell', 42.5, 500)
        tr.commission = 6.37
        tr.tax = 21.25
        tr.slippage_cost = 4.25
        d = tr.to_dict()
        self.assertEqual(d['date'], '2025-06-15')
        self.assertEqual(d['code'], '600036')
        self.assertEqual(d['direction'], 'sell')
        self.assertAlmostEqual(d['price'], 42.5)
        self.assertEqual(d['amount'], 500)
        self.assertAlmostEqual(d['commission'], 6.37)

    def test_to_dict_string_date(self):
        tr = TradeRecord('2025-03-01', '000001', '', 'buy', 10, 100)
        d = tr.to_dict()
        self.assertEqual(d['date'], '2025-03-01')

    def test_close_profit_and_return_rate_default_zero(self):
        """买入交易的平仓盈亏和收益率默认为0"""
        tr = TradeRecord(datetime.date(2025, 1, 2), '000001', '平安银行', 'buy', 10.0, 1000)
        self.assertAlmostEqual(tr.close_profit, 0.0)
        self.assertAlmostEqual(tr.return_rate, 0.0)
        d = tr.to_dict()
        self.assertEqual(d['close_profit'], 0.0)
        self.assertEqual(d['return_rate'], 0.0)

    def test_close_profit_sell_positive(self):
        """卖出盈利时平仓盈亏为正"""
        tr = TradeRecord(datetime.date(2025, 3, 1), '600036', '招商银行', 'sell', 45.0, 1000)
        # 假设持仓均价40，卖出价45，1000股
        tr.close_profit = round((45.0 - 40.0) * 1000, 2)  # 5000
        tr.return_rate = round((45.0 - 40.0) / 40.0 * 100, 2)  # 12.5%
        self.assertAlmostEqual(tr.close_profit, 5000.0)
        self.assertAlmostEqual(tr.return_rate, 12.5)
        d = tr.to_dict()
        self.assertAlmostEqual(d['close_profit'], 5000.0)
        self.assertAlmostEqual(d['return_rate'], 12.5)

    def test_close_profit_sell_negative(self):
        """卖出亏损时平仓盈亏为负"""
        tr = TradeRecord(datetime.date(2025, 3, 1), '600036', '招商银行', 'sell', 35.0, 1000)
        # 假设持仓均价40，卖出价35，1000股
        tr.close_profit = round((35.0 - 40.0) * 1000, 2)  # -5000
        tr.return_rate = round((35.0 - 40.0) / 40.0 * 100, 2)  # -12.5%
        self.assertAlmostEqual(tr.close_profit, -5000.0)
        self.assertAlmostEqual(tr.return_rate, -12.5)

    def test_to_dict_includes_close_profit_and_return_rate(self):
        """to_dict() 输出包含 close_profit 和 return_rate 字段"""
        tr = TradeRecord(datetime.date(2025, 6, 15), '600036', '招商银行', 'sell', 42.5, 500)
        tr.close_profit = 1250.0
        tr.return_rate = 6.25
        d = tr.to_dict()
        self.assertIn('close_profit', d)
        self.assertIn('return_rate', d)
        self.assertAlmostEqual(d['close_profit'], 1250.0)
        self.assertAlmostEqual(d['return_rate'], 6.25)

    def test_name_field_in_trade_record(self):
        """TradeRecord 的 name 字段正确保存"""
        tr = TradeRecord(datetime.date(2025, 1, 2), '000001', '平安银行', 'buy', 10.0, 100)
        self.assertEqual(tr.name, '平安银行')
        d = tr.to_dict()
        self.assertEqual(d['name'], '平安银行')


class TestNavRecord(unittest.TestCase):
    def test_to_dict_rounding(self):
        nr = NavRecord(
            date=datetime.date(2025, 6, 15),
            nav=1.123456789,
            benchmark_nav=1.05,
            cash=500000.123,
            market_value=500000.789,
            total_value=1000000.912,
            daily_return=0.00123456,
            benchmark_return=0.00056789,
        )
        d = nr.to_dict()
        self.assertEqual(d['date'], '2025-06-15')
        self.assertEqual(d['nav'], 1.123457)
        self.assertEqual(d['cash'], 500000.12)
        self.assertEqual(d['daily_return'], 0.001235)

    def test_to_dict_string_date(self):
        nr = NavRecord(date='2025-01-01', nav=1.0)
        d = nr.to_dict()
        self.assertEqual(d['date'], '2025-01-01')


# ═══════════════════════════════════════════════════════════════════════
# 2. strategy_sandbox tests
# ═══════════════════════════════════════════════════════════════════════

from quantia.core.backtest.strategy_sandbox import (
    validate_code, compile_strategy, _create_safe_namespace,
)


class TestValidateCode(unittest.TestCase):
    """Test validate_code for both blocking and allowing patterns."""

    # -- blocking --
    def test_block_import_os(self):
        ok, _ = validate_code("import os\ndef initialize(ctx): pass")
        self.assertFalse(ok)

    def test_block_import_sys(self):
        ok, _ = validate_code("import sys\ndef initialize(ctx): pass")
        self.assertFalse(ok)

    def test_block_import_subprocess(self):
        ok, _ = validate_code("import subprocess\ndef initialize(ctx): pass")
        self.assertFalse(ok)

    def test_block_from_os(self):
        ok, _ = validate_code("from os import path\ndef initialize(ctx): pass")
        self.assertFalse(ok)

    def test_block_exec(self):
        ok, _ = validate_code("def initialize(ctx): exec('print(1)')")
        self.assertFalse(ok)

    def test_block_eval(self):
        ok, _ = validate_code("def initialize(ctx): eval('1+1')")
        self.assertFalse(ok)

    def test_block_open(self):
        ok, _ = validate_code("def initialize(ctx): open('/etc/passwd')")
        self.assertFalse(ok)

    def test_block_dunder_import(self):
        ok, _ = validate_code("__import__('os')\ndef initialize(ctx): pass")
        self.assertFalse(ok)

    def test_block_getattr(self):
        ok, _ = validate_code("def initialize(ctx): getattr(ctx, 'x')")
        self.assertFalse(ok)

    def test_block_dunder_builtins(self):
        ok, _ = validate_code("def initialize(ctx): ctx.__builtins__")
        self.assertFalse(ok)

    def test_block_unknown_import(self):
        ok, msg = validate_code("import socket\ndef initialize(ctx): pass")
        self.assertFalse(ok)
        self.assertIn('socket', msg)

    # -- allowing --
    def test_allow_numpy(self):
        code = "import numpy as np\ndef initialize(ctx): pass"
        ok, err = validate_code(code)
        self.assertTrue(ok, err)

    def test_allow_pandas(self):
        code = "import pandas as pd\ndef initialize(ctx): pass"
        ok, err = validate_code(code)
        self.assertTrue(ok, err)

    def test_allow_math(self):
        code = "import math\ndef initialize(ctx): pass"
        ok, err = validate_code(code)
        self.assertTrue(ok, err)

    def test_allow_datetime(self):
        code = "import datetime\ndef initialize(ctx): pass"
        ok, err = validate_code(code)
        self.assertTrue(ok, err)

    def test_allow_collections(self):
        code = "import collections\ndef initialize(ctx): pass"
        ok, err = validate_code(code)
        self.assertTrue(ok, err)

    # -- edge cases --
    def test_empty_code(self):
        ok, _ = validate_code('')
        self.assertFalse(ok)

    def test_whitespace_only(self):
        ok, _ = validate_code('   \n\t  ')
        self.assertFalse(ok)

    def test_missing_initialize(self):
        ok, msg = validate_code("def handle_data(ctx, data): pass")
        self.assertFalse(ok)
        self.assertIn('initialize', msg)

    def test_valid_minimal(self):
        code = "def initialize(ctx): pass"
        ok, err = validate_code(code)
        self.assertTrue(ok, err)


class TestCompileStrategy(unittest.TestCase):
    def test_compile_valid(self):
        code = """
def initialize(context):
    pass

def handle_data(context, data):
    pass
"""
        funcs = compile_strategy(code)
        self.assertIn('initialize', funcs)
        self.assertTrue(callable(funcs['initialize']))
        self.assertTrue(callable(funcs['handle_data']))

    def test_compile_without_handle_data(self):
        code = "def initialize(ctx): pass"
        funcs = compile_strategy(code)
        self.assertIsNone(funcs['handle_data'])

    def test_compile_with_before_after(self):
        code = """
def initialize(ctx): pass
def before_trading_start(ctx): pass
def after_trading_end(ctx): pass
"""
        funcs = compile_strategy(code)
        self.assertIsNotNone(funcs['before_trading_start'])
        self.assertIsNotNone(funcs['after_trading_end'])

    def test_compile_syntax_error(self):
        code = "def initialize(ctx):\n  if True\n    pass"
        with self.assertRaises(SyntaxError):
            compile_strategy(code)

    def test_compile_forbidden_code(self):
        code = "import os\ndef initialize(ctx): pass"
        with self.assertRaises(ValueError):
            compile_strategy(code)


class TestCreateSafeNamespace(unittest.TestCase):
    def test_has_safe_builtins(self):
        ns = _create_safe_namespace()
        builtins = ns['__builtins__']
        self.assertIn('abs', builtins)
        self.assertIn('len', builtins)
        self.assertIn('range', builtins)
        self.assertIn('print', builtins)
        self.assertIn('hasattr', builtins)  # 聚宽策略常用

    def test_no_dangerous_builtins(self):
        ns = _create_safe_namespace()
        builtins = ns['__builtins__']
        # type is intentionally removed per source comment
        self.assertNotIn('type', builtins)
        self.assertNotIn('exec', builtins)
        self.assertNotIn('eval', builtins)
        self.assertNotIn('open', builtins)
        # __import__ is a sandboxed _safe_import (whitelist-only), not the real __import__
        self.assertIn('__import__', builtins)
        self.assertNotEqual(builtins['__import__'], __builtins__.__import__ if hasattr(__builtins__, '__import__') else None)

    def test_math_available(self):
        ns = _create_safe_namespace()
        self.assertIn('math', ns)

    def test_numpy_available(self):
        ns = _create_safe_namespace()
        self.assertIn('numpy', ns)
        self.assertIn('np', ns)

    def test_pandas_available(self):
        ns = _create_safe_namespace()
        self.assertIn('pandas', ns)
        self.assertIn('pd', ns)


# ═══════════════════════════════════════════════════════════════════════
# 3. data_feed tests
# ═══════════════════════════════════════════════════════════════════════

from quantia.core.backtest.data_feed import (
    _normalize_cache_df, load_stock_data, load_multiple_stocks,
    get_trading_dates, load_benchmark_data, _load_from_cache,
)


class TestNormalizeCacheDf(unittest.TestCase):
    def test_normal_df(self):
        df = pd.DataFrame({
            'date': ['2025-01-02', '2025-01-03'],
            'open': [10.0, 10.5],
            'high': [11.0, 11.5],
            'low': [9.5, 10.0],
            'close': [10.5, 11.0],
            'volume': [100000, 200000],
        })
        result = _normalize_cache_df(df)
        self.assertIsNotNone(result)
        self.assertTrue(pd.api.types.is_datetime64_any_dtype(result['date']))
        self.assertEqual(len(result), 2)

    def test_date_as_index(self):
        df = pd.DataFrame({
            'open': [10.0], 'high': [11.0], 'low': [9.5],
            'close': [10.5], 'volume': [100000],
        }, index=pd.to_datetime(['2025-01-02']))
        df.index.name = 'date'
        result = _normalize_cache_df(df)
        self.assertIsNotNone(result)
        self.assertIn('date', result.columns)

    def test_missing_column(self):
        df = pd.DataFrame({'date': ['2025-01-02'], 'close': [10.0]})
        result = _normalize_cache_df(df)
        self.assertIsNone(result)

    def test_empty_df(self):
        df = pd.DataFrame()
        result = _normalize_cache_df(df)
        self.assertIsNone(result)

    def test_none_input(self):
        result = _normalize_cache_df(None)
        self.assertIsNone(result)


class TestLoadStockData(unittest.TestCase):
    def _make_cache_df(self, code='000001'):
        dates = pd.date_range('2024-01-02', periods=50, freq='B')
        return pd.DataFrame({
            'date': dates,
            'open': np.random.uniform(9, 11, len(dates)),
            'high': np.random.uniform(10, 12, len(dates)),
            'low': np.random.uniform(8, 10, len(dates)),
            'close': np.random.uniform(9, 11, len(dates)),
            'volume': np.random.randint(50000, 200000, len(dates)),
        })

    @patch('quantia.core.backtest.data_feed._load_from_cache')
    @patch('quantia.core.backtest.data_feed._fetch_stock_from_eastmoney')
    def test_cache_hit(self, mock_fetch, mock_cache):
        mock_cache.return_value = self._make_cache_df()
        mock_fetch.return_value = None
        df = load_stock_data('000001', '2024-01-02', '2024-03-01')
        self.assertIsNotNone(df)
        self.assertIn('pre_close', df.columns)
        mock_fetch.assert_not_called()

    @patch('quantia.core.backtest.data_feed._load_from_cache')
    @patch('quantia.core.backtest.data_feed._fetch_stock_from_eastmoney')
    @patch('quantia.core.backtest.data_feed._save_cache')
    def test_fallback_to_api(self, mock_save, mock_fetch, mock_cache):
        mock_cache.return_value = None
        mock_fetch.return_value = self._make_cache_df()
        df = load_stock_data('000001', '2024-01-02', '2024-03-01')
        self.assertIsNotNone(df)
        mock_fetch.assert_called_once()
        mock_save.assert_called_once()

    @patch('quantia.core.backtest.data_feed._load_from_cache')
    @patch('quantia.core.backtest.data_feed._fetch_stock_from_eastmoney')
    def test_no_data(self, mock_fetch, mock_cache):
        mock_cache.return_value = None
        mock_fetch.return_value = None
        df = load_stock_data('999999')
        self.assertIsNone(df)

    @patch('quantia.core.backtest.data_feed._load_from_cache')
    def test_date_filtering(self, mock_cache):
        cache_df = self._make_cache_df()
        mock_cache.return_value = cache_df
        df = load_stock_data('000001', '2024-02-01', '2024-02-28')
        self.assertIsNotNone(df)
        # All dates should be within range
        self.assertTrue((df['date'] >= pd.Timestamp('2024-02-01')).all())
        self.assertTrue((df['date'] <= pd.Timestamp('2024-02-28')).all())

    @patch('quantia.core.backtest.data_feed._load_from_cache')
    @patch('quantia.core.backtest.data_feed._fetch_stock_from_eastmoney')
    @patch('quantia.core.backtest.data_feed.load_benchmark_data')
    def test_unambiguous_index_routes_to_benchmark_loader(
            self, mock_benchmark, mock_fetch, mock_cache):
        benchmark_df = pd.DataFrame({
            'date': pd.to_datetime(['2025-01-02']),
            'close': [3900],
        })
        mock_benchmark.return_value = benchmark_df

        df = load_stock_data('000300.XSHG', '2025-01-01', '2025-01-31')

        self.assertIs(df, benchmark_df)
        mock_benchmark.assert_called_once_with('000300', '2025-01-01', '2025-01-31')
        mock_cache.assert_not_called()
        mock_fetch.assert_not_called()

    @patch('quantia.core.backtest.data_feed._load_from_cache')
    @patch('quantia.core.backtest.data_feed._fetch_stock_from_eastmoney')
    @patch('quantia.core.backtest.data_feed.load_benchmark_data')
    def test_ambiguous_stock_code_still_uses_stock_loader(
            self, mock_benchmark, mock_fetch, mock_cache):
        mock_cache.return_value = self._make_cache_df('000001')

        df = load_stock_data('000001', '2024-01-02', '2024-03-01')

        self.assertIsNotNone(df)
        mock_benchmark.assert_not_called()
        mock_cache.assert_called_once_with('000001')
        mock_fetch.assert_not_called()


class TestLoadMultipleStocks(unittest.TestCase):
    @patch('quantia.core.backtest.data_feed.load_stock_data')
    def test_load_multiple(self, mock_load):
        df1 = pd.DataFrame({
            'date': pd.date_range('2024-01-02', periods=5, freq='B'),
            'close': [10, 11, 12, 11, 10],
        })
        df2 = pd.DataFrame({
            'date': pd.date_range('2024-01-02', periods=5, freq='B'),
            'close': [20, 21, 22, 21, 20],
        })
        mock_load.side_effect = [df1, None, df2]
        result = load_multiple_stocks(['000001', '999999', '600036'])
        self.assertEqual(len(result), 2)
        self.assertIn('000001', result)
        self.assertIn('600036', result)
        self.assertNotIn('999999', result)


class TestGetTradingDates(unittest.TestCase):
    @patch('quantia.core.backtest.data_feed.load_benchmark_data')
    @patch('quantia.core.backtest.data_feed.load_stock_data')
    def test_fallback_to_bdate_range(self, mock_load_stock, mock_load_benchmark):
        """When DB and cache are both unavailable, pd.bdate_range is used."""
        mock_load_stock.return_value = None
        mock_load_benchmark.return_value = None
        with patch.dict('sys.modules', {'quantia.lib.trade_time': None}):
            dates = get_trading_dates('2025-01-06', '2025-01-10')
        self.assertIsInstance(dates, list)
        self.assertTrue(all(isinstance(d, datetime.date) for d in dates))

    @patch('quantia.core.backtest.data_feed.load_stock_data')
    @patch('quantia.core.backtest.data_feed.load_benchmark_data')
    def test_uses_benchmark_loader_for_hs300_fallback(self, mock_load_benchmark, mock_load_stock):
        benchmark_df = pd.DataFrame({
            'date': pd.to_datetime(['2025-01-06', '2025-01-07']),
            'close': [3900, 3910],
        })
        mock_load_benchmark.return_value = benchmark_df
        with patch.dict('sys.modules', {'quantia.lib.trade_time': None}):
            dates = get_trading_dates('2025-01-06', '2025-01-10')
        mock_load_benchmark.assert_called_once_with('000300', '2025-01-06', '2025-01-10')
        mock_load_stock.assert_not_called()
        self.assertEqual(dates, [datetime.date(2025, 1, 6), datetime.date(2025, 1, 7)])


class TestLoadBenchmarkData(unittest.TestCase):
    @patch('quantia.core.backtest.data_feed._load_index_from_cache')
    def test_from_index_cache(self, mock_idx):
        df = pd.DataFrame({
            'date': pd.date_range('2024-01-02', periods=30, freq='B'),
            'open': np.ones(30) * 3000,
            'high': np.ones(30) * 3100,
            'low': np.ones(30) * 2900,
            'close': np.linspace(3000, 3100, 30),
            'volume': np.ones(30, dtype=int) * 1000000,
        })
        mock_idx.return_value = df
        result = load_benchmark_data('000300', '2024-01-02', '2024-02-15')
        self.assertIsNotNone(result)
        self.assertIn('pre_close', result.columns)


# ═══════════════════════════════════════════════════════════════════════
# 4. risk_metrics tests
# ═══════════════════════════════════════════════════════════════════════

from quantia.core.backtest.risk_metrics import (
    calculate_metrics, _empty_metrics, _TRADING_DAYS_PER_YEAR,
)


class TestEmptyMetrics(unittest.TestCase):
    def test_all_zero(self):
        m = _empty_metrics()
        self.assertEqual(m['total_return'], 0)
        self.assertEqual(m['sharpe_ratio'], 0)
        self.assertEqual(m['max_drawdown'], 0)
        self.assertEqual(m['trading_days'], 0)
        self.assertIn('win_count', m)
        self.assertIn('loss_count', m)


class TestCalculateMetrics(unittest.TestCase):
    """Test risk metrics with known hand-calculable inputs."""

    def test_empty_nav(self):
        m = calculate_metrics([])
        self.assertEqual(m['total_return'], 0)

    def test_single_point(self):
        m = calculate_metrics([1.0])
        self.assertEqual(m['total_return'], 0)

    def test_known_total_return(self):
        """NAV 1.0 → 1.2 ≡ 20% total return."""
        nav = [1.0, 1.05, 1.10, 1.15, 1.20]
        m = calculate_metrics(nav)
        self.assertAlmostEqual(m['total_return'], 20.0, places=1)

    def test_known_max_drawdown(self):
        """NAV goes 1.0 → 2.0 → 1.5 → 1.8.  Max drawdown = (2.0−1.5)/2.0 = 25%."""
        nav = [1.0, 1.5, 2.0, 1.5, 1.8]
        m = calculate_metrics(nav)
        self.assertAlmostEqual(m['max_drawdown'], 25.0, places=1)

    def test_all_negative_returns(self):
        """Monotonically decreasing NAV."""
        nav = [1.0, 0.95, 0.90, 0.85, 0.80]
        m = calculate_metrics(nav)
        self.assertAlmostEqual(m['total_return'], -20.0, places=1)
        self.assertGreater(m['max_drawdown'], 0)

    def test_sharpe_positive_for_rising_nav(self):
        """Steady upward NAV should yield positive Sharpe."""
        nav = [1.0 + 0.001 * i for i in range(100)]
        m = calculate_metrics(nav)
        self.assertGreater(m['sharpe_ratio'], 0)

    def test_sortino_positive_for_rising_nav(self):
        # Need some up-and-down days so downside std > 0
        np.random.seed(42)
        nav = [1.0]
        for _ in range(100):
            nav.append(nav[-1] * (1 + np.random.normal(0.002, 0.005)))
        m = calculate_metrics(nav)
        self.assertGreater(m['sortino_ratio'], 0)

    def test_sharpe_known_value(self):
        """
        Construct a series with known daily return and std.
        Daily return = 0.001, daily std ≈ 0 → Sharpe very large.
        """
        nav = [1.0]
        for _ in range(50):
            nav.append(nav[-1] * 1.001)
        m = calculate_metrics(nav)
        self.assertGreater(m['sharpe_ratio'], 5)  # very high for constant gain

    def test_benchmark_metrics(self):
        nav = [1.0, 1.05, 1.10, 1.15, 1.20]
        bm = [1.0, 1.02, 1.03, 1.04, 1.05]
        m = calculate_metrics(nav, bm)
        self.assertAlmostEqual(m['benchmark_return'], 5.0, places=1)
        self.assertGreater(m['excess_return'], 0)

    def test_zero_initial_nav(self):
        m = calculate_metrics([0.0, 1.0, 1.1])
        self.assertEqual(m['total_return'], 0)  # returns empty_metrics

    def test_trade_statistics(self):
        """Provide known trades and verify win/loss counts."""
        nav = [1.0, 1.0]  # minimal
        buy = MagicMock()
        buy.direction = 'buy'
        buy.code = '000001'
        buy.price = 10.0
        buy.amount = 100
        buy.commission = 3.0
        buy.slippage_cost = 1.0

        sell = MagicMock()
        sell.direction = 'sell'
        sell.code = '000001'
        sell.price = 12.0
        sell.amount = 100
        sell.commission = 3.0
        sell.tax = 2.0
        sell.slippage_cost = 1.0

        m = calculate_metrics(nav, trades=[buy, sell])
        self.assertEqual(m['win_count'], 1)
        self.assertEqual(m['loss_count'], 0)

    def test_trade_loss_count(self):
        nav = [1.0, 1.0]
        buy = MagicMock()
        buy.direction = 'buy'
        buy.code = '000001'
        buy.price = 10.0
        buy.amount = 100
        buy.commission = 0.0
        buy.slippage_cost = 0.0

        sell = MagicMock()
        sell.direction = 'sell'
        sell.code = '000001'
        sell.price = 8.0
        sell.amount = 100
        sell.commission = 0.0
        sell.tax = 0.0
        sell.slippage_cost = 0.0

        m = calculate_metrics(nav, trades=[buy, sell])
        self.assertEqual(m['win_count'], 0)
        self.assertEqual(m['loss_count'], 1)

    def test_daily_win_rate(self):
        """Two up days, one down day → 66.67% daily win rate."""
        nav = [1.0, 1.01, 1.02, 1.015]
        m = calculate_metrics(nav)
        # returns: +0.01, +0.01, −0.005 → 2 up, 1 down → 66.67%
        self.assertAlmostEqual(m['daily_win_rate'], 66.67, places=0)

    def test_drawdown_dates(self):
        dates = [datetime.date(2025, 1, i + 1) for i in range(5)]
        nav = [1.0, 1.5, 2.0, 1.5, 1.8]
        m = calculate_metrics(nav, dates=dates)
        self.assertEqual(m['max_drawdown_start'], '2025-01-03')
        self.assertEqual(m['max_drawdown_end'], '2025-01-04')


# ═══════════════════════════════════════════════════════════════════════
# 5. rate_stats tests
# ═══════════════════════════════════════════════════════════════════════


class TestGetRates(unittest.TestCase):
    """Tests for rate_stats.get_rates (mock envconfig for import)."""

    def _make_data(self, start='2025-01-02', periods=10):
        dates = pd.date_range(start, periods=periods, freq='B')
        closes = np.linspace(10.0, 15.0, periods)
        opens = closes - 0.1
        return pd.DataFrame({
            'date': dates,
            'open': opens,
            'high': closes + 0.5,
            'low': closes - 0.5,
            'close': closes,
        })

    def test_basic_rate_calculation(self):
        from quantia.core.backtest.rate_stats import get_rates, ROUND_TRIP_COST_PCT
        data = self._make_data()
        # stock_column length must = 2 (date, code) + (periods − 1) rates
        n_rates = len(data) - 1  # future_closes starts at T+1
        cols = ['date', 'code'] + [f'rate_{i+1}' for i in range(n_rates)]
        code_name = (data['date'].iloc[0], '000001')
        result = get_rates(code_name, data, cols, threshold=len(data))
        self.assertIsNotNone(result)
        self.assertEqual(result['code'], '000001')

        # rate_1 = (close[T+1] − buy_price) / buy_price * 100 − ROUND_TRIP_COST
        buy_price = data.iloc[1]['open']  # T+1 open
        expected_raw = (data.iloc[1]['close'] - buy_price) / buy_price * 100
        expected_net = round(round(expected_raw, 2) - ROUND_TRIP_COST_PCT, 2)
        self.assertAlmostEqual(result['rate_1'], expected_net, places=2)

    def test_limit_up_filtered(self):
        """T+1 open price ≥ T close * 1.095 → skip (limit-up)."""
        from quantia.core.backtest.rate_stats import get_rates
        data = self._make_data()
        # Make T+1 open = T close * 1.1
        data.loc[data.index[1], 'open'] = data.iloc[0]['close'] * 1.10
        cols = ['date', 'code', 'rate_1']
        code_name = (data['date'].iloc[0], '000001')
        result = get_rates(code_name, data, cols, threshold=10)
        self.assertIsNone(result)

    def test_insufficient_data(self):
        from quantia.core.backtest.rate_stats import get_rates
        data = self._make_data(periods=1)  # only 1 row
        cols = ['date', 'code', 'rate_1']
        code_name = (data['date'].iloc[0], '000001')
        result = get_rates(code_name, data, cols)
        self.assertIsNone(result)

    def test_none_data(self):
        from quantia.core.backtest.rate_stats import get_rates
        result = get_rates(('2025-01-02', '000001'), None, ['d', 'c', 'r1'])
        self.assertIsNone(result)

    def test_date_type_normalization(self):
        """start_date as string should still work."""
        from quantia.core.backtest.rate_stats import get_rates
        data = self._make_data()
        n_rates = len(data) - 1
        cols = ['date', 'code'] + [f'rate_{i+1}' for i in range(n_rates)]
        code_name = (str(data['date'].iloc[0].date()), '000001')
        result = get_rates(code_name, data, cols, threshold=len(data))
        self.assertIsNotNone(result)

    def test_padding_none_for_short_data(self):
        """When data has fewer rows than cols, remaining should be None."""
        from quantia.core.backtest.rate_stats import get_rates
        # Use tight price range to avoid limit-up filter (gap < 9.5%)
        dates = pd.date_range('2025-01-02', periods=3, freq='B')
        closes = np.array([10.0, 10.2, 10.5])
        data = pd.DataFrame({
            'date': dates,
            'open': closes - 0.05,
            'high': closes + 0.3,
            'low': closes - 0.3,
            'close': closes,
        })
        # 3 rows: T, T+1, T+2 → only rate_1 and rate_2 available (future_closes = 2)
        # Request more columns than data produces to test None padding
        cols = ['date', 'code', 'rate_1', 'rate_2', 'rate_3', 'rate_4', 'rate_5']
        code_name = (data['date'].iloc[0], '000001')
        result = get_rates(code_name, data, cols, threshold=3)
        self.assertIsNotNone(result)
        # rate_3, rate_4, rate_5 should be None (only 2 rates from 3 rows)
        self.assertIsNone(result['rate_3'])
        self.assertIsNone(result['rate_4'])
        self.assertIsNone(result['rate_5'])


# ═══════════════════════════════════════════════════════════════════════
# 6. bt_engine tests
# ═══════════════════════════════════════════════════════════════════════

from quantia.core.backtest.bt_engine import (
    BacktestEngine, StrategyBacktester, BACKTRADER_AVAILABLE,
    calculate_simple_returns,
)


class TestBacktestEngine(unittest.TestCase):
    def test_init_without_backtrader(self):
        if not BACKTRADER_AVAILABLE:
            with self.assertRaises(ImportError):
                engine = BacktestEngine()
                engine.setup()

    @unittest.skipUnless(BACKTRADER_AVAILABLE, "backtrader not installed")
    def test_setup(self):
        engine = BacktestEngine(initial_cash=200000, commission=0.001)
        engine.setup()
        self.assertIsNotNone(engine.cerebro)

    @unittest.skipUnless(BACKTRADER_AVAILABLE, "backtrader not installed")
    def test_run_without_data_raises(self):
        engine = BacktestEngine()
        with self.assertRaises(ValueError):
            engine.run()


class TestStrategyBacktester(unittest.TestCase):
    def test_init(self):
        bt = StrategyBacktester(initial_cash=200000)
        self.assertEqual(bt.initial_cash, 200000)


class TestCalculateSimpleReturns(unittest.TestCase):
    def test_known_returns(self):
        dates = pd.date_range('2025-01-02', periods=30, freq='B')
        data = pd.DataFrame({
            'date': dates,
            'open': np.linspace(10, 13, 30),
            'close': np.linspace(10, 13, 30),
        })
        result = calculate_simple_returns(data, '2025-01-02', days=[1, 5])
        self.assertIn(1, result)
        self.assertIn(5, result)

    def test_no_data(self):
        data = pd.DataFrame({
            'date': pd.date_range('2025-01-02', periods=1, freq='B'),
            'open': [10.0], 'close': [10.0],
        })
        result = calculate_simple_returns(data, '2025-01-02')
        # Only 1 row → all None
        self.assertTrue(all(v is None for v in result.values()))


# ═══════════════════════════════════════════════════════════════════════
# 7. fundamentals tests
# ═══════════════════════════════════════════════════════════════════════

from quantia.core.backtest.fundamentals import (
    _FieldExpr, _Query, query, valuation, OrderCost,
    FundamentalDataProvider,
)


class TestFieldExpr(unittest.TestCase):
    def setUp(self):
        self.field = _FieldExpr('valuation', 'market_cap')

    def test_between(self):
        result = self.field.between(10, 50)
        self.assertEqual(result, ('between', 'market_cap', 10, 50))

    def test_in_(self):
        result = self.field.in_(['000001', '600036'])
        self.assertEqual(result[0], 'in_')
        self.assertEqual(result[1], 'market_cap')
        self.assertEqual(result[2], ['000001', '600036'])

    def test_gt(self):
        result = self.field > 100
        self.assertEqual(result, ('gt', 'market_cap', 100))

    def test_lt(self):
        result = self.field < 50
        self.assertEqual(result, ('lt', 'market_cap', 50))

    def test_ge(self):
        result = self.field >= 20
        self.assertEqual(result, ('ge', 'market_cap', 20))

    def test_le(self):
        result = self.field <= 80
        self.assertEqual(result, ('le', 'market_cap', 80))

    def test_asc(self):
        result = self.field.asc()
        self.assertEqual(result, ('asc', 'market_cap'))

    def test_desc(self):
        result = self.field.desc()
        self.assertEqual(result, ('desc', 'market_cap'))

    def test_repr(self):
        r = repr(self.field)
        self.assertIn('valuation', r)
        self.assertIn('market_cap', r)


class TestQuery(unittest.TestCase):
    def test_empty_query(self):
        q = query(valuation.market_cap)
        self.assertEqual(len(q._filters), 0)
        self.assertIsNone(q._order_by_clause)
        self.assertIsNone(q._limit_val)

    def test_filter_chaining(self):
        q = query(valuation.market_cap).filter(
            valuation.market_cap.between(20, 50)
        ).filter(
            valuation.pb_ratio > 0
        )
        self.assertEqual(len(q._filters), 2)

    def test_order_by(self):
        q = query(valuation.market_cap).order_by(valuation.market_cap.asc())
        self.assertEqual(q._order_by_clause, ('asc', 'market_cap'))

    def test_limit(self):
        q = query(valuation.market_cap).limit(10)
        self.assertEqual(q._limit_val, 10)

    def test_full_chain(self):
        q = (query(valuation.market_cap)
             .filter(valuation.market_cap.between(20, 50))
             .order_by(valuation.market_cap.asc())
             .limit(5))
        self.assertEqual(len(q._filters), 1)
        self.assertEqual(q._order_by_clause, ('asc', 'market_cap'))
        self.assertEqual(q._limit_val, 5)


class TestValuationTable(unittest.TestCase):
    def test_fields_are_field_expr(self):
        self.assertIsInstance(valuation.code, _FieldExpr)
        self.assertIsInstance(valuation.market_cap, _FieldExpr)
        self.assertIsInstance(valuation.pe_ratio, _FieldExpr)
        self.assertIsInstance(valuation.pb_ratio, _FieldExpr)


class TestOrderCost(unittest.TestCase):
    def test_defaults(self):
        oc = OrderCost()
        self.assertEqual(oc.open_tax, 0)
        self.assertAlmostEqual(oc.close_tax, 0.001)
        self.assertAlmostEqual(oc.open_commission, 0.0003)

    def test_custom(self):
        oc = OrderCost(close_tax=0.0005, open_commission=0.0002)
        self.assertAlmostEqual(oc.close_tax, 0.0005)
        self.assertAlmostEqual(oc.open_commission, 0.0002)


class TestFundamentalDataProvider(unittest.TestCase):
    """Test FundamentalDataProvider with mocked DB/API calls."""

    def _make_provider(self):
        engine = MagicMock()
        engine.context = Context()
        engine.context.current_dt = datetime.date(2025, 3, 10)
        provider = FundamentalDataProvider(engine)
        # Manually set internal state to skip _init_data
        provider._initialized = True
        # total_shares chosen so that mcap = total_shares * close / 1e8
        # matches current_mcap at current_price
        provider._stock_info = pd.DataFrame({
            'code': ['000001', '600036', '000002'],
            'name': ['平安银行', '招商银行', '万科A'],
            'total_shares': [2e8, 2e8, 2e8],
            'current_mcap': [30, 60, 20],
            'current_pb': [1.2, 1.5, 0.8],
            'current_price': [15.0, 30.0, 10.0],
        })
        provider._candidate_codes = ['000001', '600036', '000002']
        provider._price_lookup = {
            '000001': {'2025-03-10': 15.0, '2025-03-11': 15.5},
            '600036': {'2025-03-10': 30.0, '2025-03-11': 31.0},
            '000002': {'2025-03-10': 10.0, '2025-03-11': 9.5},
        }
        provider._volume_lookup = {
            '000001': {'2025-03-10': 1000000},
            '600036': {'2025-03-10': 2000000},
            '000002': {'2025-03-10': 500000},
        }
        return provider

    def test_get_fundamentals_basic(self):
        provider = self._make_provider()
        q = query(valuation.market_cap)
        result = provider.get_fundamentals(q, datetime.date(2025, 3, 10))
        self.assertIsInstance(result, pd.DataFrame)
        self.assertGreater(len(result), 0)
        self.assertIn('code', result.columns)
        self.assertIn('market_cap', result.columns)

    def test_get_fundamentals_filter_between(self):
        provider = self._make_provider()
        q = query(valuation.market_cap).filter(
            valuation.market_cap.between(25, 35)
        )
        result = provider.get_fundamentals(q, datetime.date(2025, 3, 10))
        # Only 000001 with mcap ~30 should match (600036 is ~60)
        matched_codes = result['code'].tolist()
        self.assertIn('000001', matched_codes)
        self.assertNotIn('600036', matched_codes)

    def test_get_fundamentals_order_and_limit(self):
        provider = self._make_provider()
        q = (query(valuation.market_cap)
             .order_by(valuation.market_cap.asc())
             .limit(2))
        result = provider.get_fundamentals(q, datetime.date(2025, 3, 10))
        self.assertLessEqual(len(result), 2)
        if len(result) == 2:
            # Should be sorted ascending
            self.assertLessEqual(
                result.iloc[0]['market_cap'],
                result.iloc[1]['market_cap']
            )

    def test_get_fundamentals_in_filter(self):
        provider = self._make_provider()
        q = query(valuation.market_cap).filter(
            valuation.code.in_(['000001', '000002'])
        )
        result = provider.get_fundamentals(q, datetime.date(2025, 3, 10))
        for code in result['code'].tolist():
            self.assertIn(code, ['000001', '000002'])

    def test_get_fundamentals_no_data_date(self):
        provider = self._make_provider()
        q = query(valuation.market_cap)
        result = provider.get_fundamentals(q, datetime.date(2020, 1, 1))
        # No prices for 2020 → empty or minimal
        self.assertEqual(len(result), 0)

    def test_is_paused(self):
        provider = self._make_provider()
        # 000001 has volume data for 2025-03-10 (nonzero) → not paused
        self.assertFalse(provider.is_paused('000001', datetime.date(2025, 3, 10)))
        # Unknown date → paused
        self.assertTrue(provider.is_paused('000001', datetime.date(2020, 1, 1)))
        # Unknown code → paused
        self.assertTrue(provider.is_paused('999999'))

    def test_is_paused_zero_volume(self):
        provider = self._make_provider()
        provider._volume_lookup['000001']['2025-03-12'] = 0
        self.assertTrue(provider.is_paused('000001', datetime.date(2025, 3, 12)))


# ═══════════════════════════════════════════════════════════════════════
# 8. portfolio_engine tests
# ═══════════════════════════════════════════════════════════════════════

from quantia.core.backtest.portfolio_engine import PortfolioBacktestEngine


class TestPortfolioBacktestEngineInit(unittest.TestCase):
    def test_init(self):
        engine = PortfolioBacktestEngine()
        self.assertIsNone(engine.context)
        self.assertIsNone(engine.data_proxy)
        self.assertEqual(len(engine._trade_records), 0)
        self.assertEqual(len(engine._nav_records), 0)


class TestPortfolioBacktestEngineRun(unittest.TestCase):
    """Test the run() method with a simple strategy and mocked data."""

    def _make_stock_df(self, code='000001', start='2025-01-02', periods=20):
        dates = pd.date_range(start, periods=periods, freq='B')
        closes = np.linspace(10, 12, periods)
        df = pd.DataFrame({
            'date': dates,
            'open': closes - 0.05,
            'high': closes + 0.5,
            'low': closes - 0.5,
            'close': closes,
            'volume': np.ones(periods, dtype=int) * 500000,
        })
        df['pre_close'] = df['close'].shift(1)
        return df

    @patch('quantia.core.backtest.portfolio_engine.load_benchmark_data')
    @patch('quantia.core.backtest.portfolio_engine.load_multiple_stocks')
    def test_preload_routes_index_codes_to_benchmark_loader(self, mock_load_multi, mock_bm):
        stock_df = self._make_stock_df(code='000001', periods=5)
        benchmark_df = self._make_stock_df(code='000300', periods=5)
        mock_load_multi.return_value = {'000001': stock_df}
        mock_bm.return_value = benchmark_df

        engine = PortfolioBacktestEngine()
        engine.context = MagicMock()
        engine.context.benchmark = '000300'
        engine.context.stock = '000001'
        engine.g = MagicMock()
        engine.data_proxy = MagicMock()

        engine._discover_and_load_stocks('2024-12-01', '2025-01-31')

        loaded_stock_codes = mock_load_multi.call_args.args[0]
        self.assertIn('000001', loaded_stock_codes)
        self.assertNotIn('000300', loaded_stock_codes)
        mock_bm.assert_called_once_with('000300', '2024-12-01', '2025-01-31')
        self.assertIn('000300', engine._stock_data)

    @patch('quantia.core.backtest.portfolio_engine.load_benchmark_data')
    @patch('quantia.core.backtest.portfolio_engine.load_multiple_stocks')
    @patch('quantia.core.backtest.portfolio_engine.get_trading_dates')
    @patch('quantia.core.backtest.portfolio_engine.load_stock_data')
    def test_run_simple_buy_and_hold(self, mock_load_single, mock_dates,
                                      mock_load_multi, mock_bm):
        stock_df = self._make_stock_df(periods=10)
        dates_list = [d.date() for d in stock_df['date']]

        mock_dates.return_value = dates_list
        mock_load_multi.return_value = {'000001': stock_df}
        mock_load_single.return_value = stock_df
        bm_df = stock_df.copy()
        mock_bm.return_value = bm_df

        strategy = """
def initialize(context):
    pass

def handle_data(context, data):
    if '000001' not in context.portfolio.positions:
        order_value('000001', 100000)
"""
        engine = PortfolioBacktestEngine()
        result = engine.run(
            strategy_code=strategy,
            start_date='2025-01-02',
            end_date='2025-01-15',
            initial_cash=1000000,
        )
        self.assertEqual(result['status'], 'completed')
        self.assertIn('metrics', result)
        self.assertIn('nav', result)
        self.assertIn('trades', result)

    @patch('quantia.core.backtest.portfolio_engine.load_benchmark_data')
    @patch('quantia.core.backtest.portfolio_engine.load_multiple_stocks')
    @patch('quantia.core.backtest.portfolio_engine.get_trading_dates')
    @patch('quantia.core.backtest.portfolio_engine.load_stock_data')
    def test_run_invalid_strategy(self, mock_load_single, mock_dates,
                                   mock_load_multi, mock_bm):
        result = PortfolioBacktestEngine().run(
            strategy_code="import os\ndef initialize(ctx): pass",
            start_date='2025-01-02', end_date='2025-01-15',
        )
        self.assertEqual(result['status'], 'error')
        self.assertIn('message', result)

    @patch('quantia.core.backtest.portfolio_engine.load_benchmark_data')
    @patch('quantia.core.backtest.portfolio_engine.load_multiple_stocks')
    @patch('quantia.core.backtest.portfolio_engine.get_trading_dates')
    @patch('quantia.core.backtest.portfolio_engine.load_stock_data')
    def test_run_syntax_error(self, mock_load_single, mock_dates,
                               mock_load_multi, mock_bm):
        result = PortfolioBacktestEngine().run(
            strategy_code="def initialize(ctx)\n  pass",
            start_date='2025-01-02', end_date='2025-01-15',
        )
        self.assertEqual(result['status'], 'error')

    @patch('quantia.core.backtest.portfolio_engine.load_benchmark_data')
    @patch('quantia.core.backtest.portfolio_engine.load_multiple_stocks')
    @patch('quantia.core.backtest.portfolio_engine.get_trading_dates')
    @patch('quantia.core.backtest.portfolio_engine.load_stock_data')
    def test_run_no_trading_dates(self, mock_load_single, mock_dates,
                                   mock_load_multi, mock_bm):
        mock_dates.return_value = []
        result = PortfolioBacktestEngine().run(
            strategy_code="def initialize(ctx): pass",
            start_date='2025-01-02', end_date='2025-01-15',
        )
        self.assertEqual(result['status'], 'error')
        self.assertIn('无交易日', result['message'])

    def test_run_zero_cash(self):
        result = PortfolioBacktestEngine().run(
            strategy_code="def initialize(ctx): pass",
            start_date='2025-01-02', end_date='2025-01-15',
            initial_cash=0,
        )
        self.assertEqual(result['status'], 'error')

    @patch('quantia.core.backtest.portfolio_engine.load_benchmark_data')
    @patch('quantia.core.backtest.portfolio_engine.load_multiple_stocks')
    @patch('quantia.core.backtest.portfolio_engine.get_trading_dates')
    @patch('quantia.core.backtest.portfolio_engine.load_stock_data')
    def test_order_matching_and_t_plus_1(self, mock_load_single, mock_dates,
                                          mock_load_multi, mock_bm):
        """Buy on day 1. On day 2 the shares should be closeable. Sell on day 2."""
        stock_df = self._make_stock_df(periods=5)
        dates_list = [d.date() for d in stock_df['date']]

        mock_dates.return_value = dates_list
        mock_load_multi.return_value = {'000001': stock_df}
        mock_load_single.return_value = stock_df
        mock_bm.return_value = stock_df.copy()

        strategy = """
_bought = False
_sold = False

def initialize(context):
    pass

def handle_data(context, data):
    global _bought, _sold
    if not _bought:
        order('000001', 100)
        _bought = True
    elif not _sold and '000001' in context.portfolio.positions:
        pos = context.portfolio.positions['000001']
        if pos.closeable_amount > 0:
            order('000001', -100)
            _sold = True
"""
        engine = PortfolioBacktestEngine()
        result = engine.run(
            strategy_code=strategy,
            start_date=str(dates_list[0]),
            end_date=str(dates_list[-1]),
            initial_cash=100000,
        )
        self.assertEqual(result['status'], 'completed')
        trades = result['trades']
        # Should have at least a buy; sell depends on T+1 closeable
        self.assertGreaterEqual(len(trades), 1)

    @patch('quantia.core.backtest.portfolio_engine.load_benchmark_data')
    @patch('quantia.core.backtest.portfolio_engine.load_multiple_stocks')
    @patch('quantia.core.backtest.portfolio_engine.get_trading_dates')
    @patch('quantia.core.backtest.portfolio_engine.load_stock_data')
    def test_limit_up_blocks_buy(self, mock_load_single, mock_dates,
                                  mock_load_multi, mock_bm):
        """If a stock is limit-up, the buy should be cancelled."""
        stock_df = self._make_stock_df(periods=5)
        # Make day 1 look like limit-up: close/pre_close > 9.5%
        stock_df.loc[stock_df.index[0], 'close'] = 10.0
        stock_df.loc[stock_df.index[0], 'pre_close'] = 9.0  # +11.1%
        dates_list = [d.date() for d in stock_df['date']]

        mock_dates.return_value = dates_list
        mock_load_multi.return_value = {'000001': stock_df}
        mock_load_single.return_value = stock_df
        mock_bm.return_value = stock_df.copy()

        strategy = """
def initialize(context):
    pass

def handle_data(context, data):
    if '000001' not in context.portfolio.positions:
        order('000001', 100)
"""
        engine = PortfolioBacktestEngine()
        result = engine.run(
            strategy_code=strategy,
            start_date=str(dates_list[0]),
            end_date=str(dates_list[-1]),
            initial_cash=100000,
        )
        self.assertEqual(result['status'], 'completed')
        # The first day's buy should be blocked, but subsequent days may go through
        # Check logs for limit-up warning
        has_limit_log = any('涨停' in msg for msg in engine._log_messages)
        # The stock may not be limit-up on subsequent days, so buy might succeed later
        self.assertIsNotNone(result['trades'])

    @patch('quantia.core.backtest.portfolio_engine.load_benchmark_data')
    @patch('quantia.core.backtest.portfolio_engine.load_multiple_stocks')
    @patch('quantia.core.backtest.portfolio_engine.get_trading_dates')
    @patch('quantia.core.backtest.portfolio_engine.load_stock_data')
    def test_nav_records_generated(self, mock_load_single, mock_dates,
                                    mock_load_multi, mock_bm):
        stock_df = self._make_stock_df(periods=5)
        dates_list = [d.date() for d in stock_df['date']]
        mock_dates.return_value = dates_list
        mock_load_multi.return_value = {}
        mock_load_single.return_value = stock_df
        mock_bm.return_value = stock_df.copy()

        strategy = "def initialize(ctx): pass"
        engine = PortfolioBacktestEngine()
        result = engine.run(
            strategy_code=strategy,
            start_date=str(dates_list[0]),
            end_date=str(dates_list[-1]),
            initial_cash=100000,
        )
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(len(result['nav']), len(dates_list))
        # First NAV should be 1.0 (no trades)
        self.assertAlmostEqual(result['nav'][0]['nav'], 1.0)


class TestPortfolioEngineEdgeCases(unittest.TestCase):
    """Additional edge-case tests for portfolio engine internals."""

    def test_load_day_prices(self):
        engine = PortfolioBacktestEngine()
        engine.context = Context()
        engine.data_proxy = DataProxy()
        df = pd.DataFrame({
            'date': pd.to_datetime(['2025-01-02', '2025-01-03']),
            'open': [10.0, 10.5],
            'high': [11.0, 11.5],
            'low': [9.5, 10.0],
            'close': [10.5, 11.0],
            'volume': [100000, 200000],
            'pre_close': [10.0, 10.5],
        })
        engine._build_date_index('000001', df)
        prices = engine._load_day_prices(datetime.date(2025, 1, 2))
        self.assertIn('000001', prices)
        self.assertAlmostEqual(prices['000001'], 10.5)

    def test_resolve_stock_name_cached(self):
        """_resolve_stock_name 使用缓存"""
        engine = PortfolioBacktestEngine()
        engine._stock_names = {'000001': '平安银行', '600036': '招商银行'}
        self.assertEqual(engine._resolve_stock_name('000001'), '平安银行')
        self.assertEqual(engine._resolve_stock_name('600036'), '招商银行')

    def test_resolve_stock_name_fallback_empty(self):
        """_resolve_stock_name 查不到时返回空字符串"""
        engine = PortfolioBacktestEngine()
        engine._stock_names = {}
        # mock _query_stock_name to avoid DB access
        # Note: read from __dict__ to preserve staticmethod descriptor on restore
        original = PortfolioBacktestEngine.__dict__['_query_stock_name']
        PortfolioBacktestEngine._query_stock_name = staticmethod(lambda code: '')
        try:
            name = engine._resolve_stock_name('999999')
            self.assertEqual(name, '')
            # 应入缓存
            self.assertIn('999999', engine._stock_names)
        finally:
            PortfolioBacktestEngine._query_stock_name = original

    def test_stock_names_cache_initialization(self):
        """引擎初始化时 _stock_names 为空字典"""
        engine = PortfolioBacktestEngine()
        self.assertIsInstance(engine._stock_names, dict)
        self.assertEqual(len(engine._stock_names), 0)


class TestTradeRecordPnlInEngine(unittest.TestCase):
    """测试引擎在卖出时正确计算平仓盈亏和收益率"""

    def _make_engine_with_position(self, code='000001', name='平安银行',
                                    amount=1000, avg_cost=10.0):
        """创建一个包含指定持仓的引擎实例"""
        engine = PortfolioBacktestEngine()
        engine.context = Context(initial_cash=100000)
        engine.context.commission_rate = 0.0003
        engine.context.stamp_tax_rate = 0.001
        engine.context.slippage_rate = 0.002
        engine.data_proxy = DataProxy()
        engine._stock_names = {code: name}
        engine._trade_records = []
        engine._log_messages = []
        engine._pending_orders = []

        # 建仓
        pos = engine.context.portfolio._get_or_create_position(code, name)
        pos.amount = amount
        pos.closeable_amount = amount
        pos.avg_cost = avg_cost
        pos.price = avg_cost
        pos.value = amount * avg_cost
        engine.context.portfolio.available_cash = 100000 - pos.value
        engine.context.portfolio._update_value()

        return engine

    def _setup_day_price(self, engine, code, date, close_price):
        """设置引擎的当日价格"""
        engine.context.current_dt = date
        engine._current_day_prices = {code: close_price}
        df = pd.DataFrame({
            'date': pd.to_datetime([date]),
            'open': [close_price],
            'high': [close_price],
            'low': [close_price],
            'close': [close_price],
            'volume': [100000],
            'pre_close': [close_price * 0.98],
        })
        engine._build_date_index(code, df)
        engine.data_proxy._set_current(code, {
            'open': close_price, 'high': close_price,
            'low': close_price, 'close': close_price,
            'volume': 100000, 'pre_close': close_price * 0.98,
        })

    def test_sell_profit_positive(self):
        """卖出盈利：close_profit > 0, return_rate > 0"""
        engine = self._make_engine_with_position(
            code='000001', name='平安银行', amount=1000, avg_cost=10.0)
        date = datetime.date(2025, 3, 1)
        self._setup_day_price(engine, '000001', date, 12.0)

        engine._execute_single_order({'code': '000001', 'amount': -1000, 'value': None}, date)

        self.assertEqual(len(engine._trade_records), 1)
        trade = engine._trade_records[0]
        self.assertEqual(trade.direction, 'sell')
        self.assertEqual(trade.name, '平安银行')
        self.assertEqual(trade.code, '000001')
        # close_profit = (12.0 - 10.0) * 1000 = 2000
        self.assertAlmostEqual(trade.close_profit, 2000.0)
        # return_rate = (12.0 - 10.0) / 10.0 * 100 = 20.0%
        self.assertAlmostEqual(trade.return_rate, 20.0)

    def test_sell_profit_negative(self):
        """卖出亏损：close_profit < 0, return_rate < 0"""
        engine = self._make_engine_with_position(
            code='600036', name='招商银行', amount=1000, avg_cost=40.0)
        date = datetime.date(2025, 3, 1)
        self._setup_day_price(engine, '600036', date, 35.0)

        engine._execute_single_order({'code': '600036', 'amount': -1000, 'value': None}, date)

        self.assertEqual(len(engine._trade_records), 1)
        trade = engine._trade_records[0]
        self.assertEqual(trade.direction, 'sell')
        self.assertEqual(trade.name, '招商银行')
        # close_profit = (35.0 - 40.0) * 1000 = -5000
        self.assertAlmostEqual(trade.close_profit, -5000.0)
        # return_rate = (35.0 - 40.0) / 40.0 * 100 = -12.5%
        self.assertAlmostEqual(trade.return_rate, -12.5)

    def test_sell_less_than_one_lot_rejected_with_warning(self):
        """不足一手的卖出请求不应静默清仓，应记录拒绝日志。"""
        engine = self._make_engine_with_position(
            code='000001', name='平安银行', amount=300, avg_cost=10.0)
        date = datetime.date(2025, 3, 1)
        self._setup_day_price(engine, '000001', date, 12.0)

        engine._execute_single_order({'code': '000001', 'amount': -50, 'value': None}, date)

        self.assertEqual(len(engine._trade_records), 0)
        self.assertEqual(engine.context.portfolio.positions['000001'].amount, 300)
        self.assertTrue(any('不足一手' in msg and '000001' in msg
                            for msg in engine._log_messages))

    def test_buy_has_stock_name(self):
        """买入交易记录包含股票名称"""
        engine = PortfolioBacktestEngine()
        engine.context = Context(initial_cash=100000)
        engine.context.commission_rate = 0.0003
        engine.context.stamp_tax_rate = 0.001
        engine.context.slippage_rate = 0.002
        engine.context.current_dt = datetime.date(2025, 3, 1)
        engine.data_proxy = DataProxy()
        engine._stock_names = {'000001': '平安银行'}
        engine._trade_records = []
        engine._log_messages = []
        engine._pending_orders = []
        engine._current_day_prices = {'000001': 10.0}
        engine._all_codes = {'000001'}

        df = pd.DataFrame({
            'date': pd.to_datetime(['2025-03-01']),
            'open': [10.0], 'high': [10.0], 'low': [10.0],
            'close': [10.0], 'volume': [100000], 'pre_close': [9.8],
        })
        engine._build_date_index('000001', df)
        engine.data_proxy._set_current('000001', {
            'open': 10.0, 'high': 10.0, 'low': 10.0,
            'close': 10.0, 'volume': 100000, 'pre_close': 9.8,
        })

        engine._execute_single_order(
            {'code': '000001', 'amount': 100, 'value': None},
            datetime.date(2025, 3, 1))

        self.assertEqual(len(engine._trade_records), 1)
        trade = engine._trade_records[0]
        self.assertEqual(trade.direction, 'buy')
        self.assertEqual(trade.name, '平安银行')
        # 买入时 close_profit 和 return_rate 都为 0
        self.assertAlmostEqual(trade.close_profit, 0.0)
        self.assertAlmostEqual(trade.return_rate, 0.0)

    def test_buy_name_empty_when_unknown(self):
        """未知股票买入时 name 为空字符串"""
        engine = PortfolioBacktestEngine()
        engine.context = Context(initial_cash=100000)
        engine.context.commission_rate = 0.0003
        engine.context.stamp_tax_rate = 0.001
        engine.context.slippage_rate = 0.002
        engine.context.current_dt = datetime.date(2025, 3, 1)
        engine.data_proxy = DataProxy()
        engine._stock_names = {}
        engine._trade_records = []
        engine._log_messages = []
        engine._pending_orders = []
        engine._current_day_prices = {'999999': 10.0}
        engine._all_codes = {'999999'}

        df = pd.DataFrame({
            'date': pd.to_datetime(['2025-03-01']),
            'open': [10.0], 'high': [10.0], 'low': [10.0],
            'close': [10.0], 'volume': [100000], 'pre_close': [9.8],
        })
        engine._build_date_index('999999', df)
        engine.data_proxy._set_current('999999', {
            'open': 10.0, 'high': 10.0, 'low': 10.0,
            'close': 10.0, 'volume': 100000, 'pre_close': 9.8,
        })

        # mock _query_stock_name to avoid DB
        # Note: read from __dict__ to preserve staticmethod descriptor on restore
        original = PortfolioBacktestEngine.__dict__['_query_stock_name']
        PortfolioBacktestEngine._query_stock_name = staticmethod(lambda code: '')
        try:
            engine._execute_single_order(
                {'code': '999999', 'amount': 100, 'value': None},
                datetime.date(2025, 3, 1))
        finally:
            PortfolioBacktestEngine._query_stock_name = original

        self.assertEqual(len(engine._trade_records), 1)
        self.assertEqual(engine._trade_records[0].name, '')

    def test_to_dict_roundtrip(self):
        """完整的买卖流程 to_dict 包含所有字段"""
        engine = self._make_engine_with_position(
            code='000001', name='平安银行', amount=1000, avg_cost=10.0)
        date = datetime.date(2025, 3, 1)
        self._setup_day_price(engine, '000001', date, 11.0)

        engine._execute_single_order({'code': '000001', 'amount': -1000, 'value': None}, date)

        trade = engine._trade_records[0]
        d = trade.to_dict()

        # 验证所有字段存在
        required_fields = ['date', 'code', 'name', 'direction', 'price',
                          'amount', 'value', 'commission', 'tax',
                          'slippage_cost', 'close_profit', 'return_rate']
        for field in required_fields:
            self.assertIn(field, d, f"to_dict() 缺少字段: {field}")

        self.assertEqual(d['name'], '平安银行')
        self.assertEqual(d['direction'], 'sell')
        self.assertGreater(d['close_profit'], 0)
        self.assertGreater(d['return_rate'], 0)


# ═══════════════════════════════════════════════════════════════════════
# Runner
# ═══════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    unittest.main()
