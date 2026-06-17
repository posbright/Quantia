#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Comprehensive tests for quantia/paper_trading/ modules.

Covers:
  - state_manager.serialize_portfolio / restore_portfolio
  - paper_engine._create_api / _ensure_*_table / _update_paper_error
  - paper_engine.run_paper_trading_daily / run_all_paper_trading
"""

import sys
import os
import json
import datetime
from unittest import mock
from unittest.mock import patch, MagicMock, call

import pytest
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from quantia.core.backtest.strategy_context import (
    Context, Portfolio, Position, GlobalVars, DataProxy, TradeRecord, NavRecord,
)
from quantia.paper_trading.state_manager import (
    serialize_portfolio, restore_portfolio, restore_runtime_vars,
)
from quantia.paper_trading.paper_engine import (
    _create_api,
    _update_paper_error,
    _ensure_paper_table,
    _ensure_trade_table,
    _ensure_position_table,
    _is_paper_due,
    _load_security_data,
    _net_same_bar_orders,
    _normalize_security_code,
    run_paper_trading_daily,
    run_all_paper_trading,
)
from quantia.web.paperTradingHandler import (
    _apply_nav_snapshot,
    _build_paper_update_fields,
    _compute_paper_metrics,
    _get_benchmark_name,
    _get_benchmark_return_label,
    _paper_has_started,
    _latest_nav_snapshot,
    _normalize_benchmark_code,
    _should_rebuild_benchmark_values,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_context_with_positions(cash=500000, positions_data=None):
    """Build a Context with optional positions for testing."""
    ctx = Context(initial_cash=1000000)
    ctx.portfolio.available_cash = cash
    ctx.current_dt = datetime.date(2026, 3, 18)
    ctx.benchmark = '000300'
    ctx.commission_rate = 0.0003
    ctx.stamp_tax_rate = 0.001
    ctx.slippage_rate = 0.002

    if positions_data:
        for d in positions_data:
            pos = Position(d['code'], d.get('name', ''))
            pos.amount = d.get('amount', 0)
            pos.closeable_amount = d.get('closeable_amount', 0)
            pos.avg_cost = d.get('avg_cost', 0.0)
            pos.price = d.get('price', 0.0)
            pos.value = pos.amount * pos.price
            if pos.amount > 0:
                ctx.portfolio.positions[d['code']] = pos

    ctx.portfolio._update_value()

    # Attach a minimal engine + g so serialize_portfolio can inspect g
    g = GlobalVars()
    ctx._engine = type('E', (), {
        'g': g,
        '_stock_data': {},
        '_pending_orders': [],
        '_trade_records': [],
        '_log_messages': [],
        '_custom_records': {},
    })()
    return ctx, g


# ===========================================================================
#  1. serialize_portfolio tests
# ===========================================================================

class TestSerializePortfolio:
    """Tests for state_manager.serialize_portfolio"""

    def test_empty_portfolio(self):
        """Serialize context with no positions."""
        ctx, _g = _make_context_with_positions(cash=1000000)
        result = serialize_portfolio(ctx)
        state = json.loads(result)

        assert state['available_cash'] == 1000000
        assert state['positions'] == {}
        assert state['benchmark'] == '000300'
        assert state['commission_rate'] == 0.0003
        assert state['stamp_tax_rate'] == 0.001
        assert state['slippage_rate'] == 0.002

    def test_single_position(self):
        """Serialize context with one position."""
        ctx, _g = _make_context_with_positions(
            cash=800000,
            positions_data=[
                {'code': '600519', 'name': '贵州茅台', 'amount': 100,
                 'closeable_amount': 100, 'avg_cost': 1800.0, 'price': 1900.0},
            ],
        )
        result = serialize_portfolio(ctx)
        state = json.loads(result)

        assert state['available_cash'] == 800000
        assert '600519' in state['positions']
        pos = state['positions']['600519']
        assert pos['code'] == '600519'
        assert pos['name'] == '贵州茅台'
        assert pos['amount'] == 100
        assert pos['closeable_amount'] == 100
        assert pos['avg_cost'] == 1800.0
        assert pos['price'] == 1900.0

    def test_multiple_positions(self):
        """Serialize context with multiple positions."""
        ctx, _g = _make_context_with_positions(
            cash=300000,
            positions_data=[
                {'code': '600519', 'name': '贵州茅台', 'amount': 100,
                 'closeable_amount': 100, 'avg_cost': 1800.0, 'price': 1900.0},
                {'code': '000001', 'name': '平安银行', 'amount': 500,
                 'closeable_amount': 500, 'avg_cost': 15.0, 'price': 16.0},
                {'code': '300750', 'name': '宁德时代', 'amount': 200,
                 'closeable_amount': 200, 'avg_cost': 220.0, 'price': 225.5},
            ],
        )
        result = serialize_portfolio(ctx)
        state = json.loads(result)

        assert len(state['positions']) == 3
        codes = set(state['positions'].keys())
        assert codes == {'600519', '000001', '300750'}

    def test_zero_amount_positions_excluded(self):
        """Positions with amount == 0 should not appear in the JSON."""
        ctx, _g = _make_context_with_positions(cash=1000000)
        pos = Position('999999', 'empty')
        pos.amount = 0
        ctx.portfolio.positions['999999'] = pos

        result = serialize_portfolio(ctx)
        state = json.loads(result)
        assert '999999' not in state['positions']

    def test_g_vars_serialized(self):
        """GlobalVars basic types are serialized."""
        ctx, g = _make_context_with_positions(cash=1000000)
        g.my_flag = True
        g.my_count = 42
        g.my_name = 'test_strategy'
        g.my_list = [1, 2, 3]

        result = serialize_portfolio(ctx)
        state = json.loads(result)

        assert state['g_vars']['my_flag'] is True
        assert state['g_vars']['my_count'] == 42
        assert state['g_vars']['my_name'] == 'test_strategy'
        assert state['g_vars']['my_list'] == [1, 2, 3]

    def test_g_vars_non_serializable_skipped(self):
        """Non-basic types on g should be silently skipped."""
        ctx, g = _make_context_with_positions(cash=1000000)
        g.ok_var = 'keep'
        g.bad_var = lambda x: x  # not serializable

        result = serialize_portfolio(ctx)
        state = json.loads(result)

        assert 'ok_var' in state['g_vars']
        assert 'bad_var' not in state['g_vars']

    def test_current_dt_serialized(self):
        """current_dt is converted to string."""
        ctx, _g = _make_context_with_positions(cash=1000000)
        ctx.current_dt = datetime.date(2026, 3, 18)

        result = serialize_portfolio(ctx)
        state = json.loads(result)
        assert state['current_dt'] == '2026-03-18'

    def test_output_is_valid_json(self):
        """Result is a valid JSON string."""
        ctx, _g = _make_context_with_positions(cash=1000000)
        result = serialize_portfolio(ctx)
        parsed = json.loads(result)
        assert isinstance(parsed, dict)


# ===========================================================================
#  2. restore_portfolio tests
# ===========================================================================

class TestRestorePortfolio:
    """Tests for state_manager.restore_portfolio"""

    def test_restore_empty_state(self):
        """Restore from None/empty state_json is a no-op."""
        ctx = Context(1000000)
        restore_portfolio(ctx, None)
        assert ctx.portfolio.available_cash == 1000000
        assert len(ctx.portfolio.positions) == 0

        restore_portfolio(ctx, '')
        assert ctx.portfolio.available_cash == 1000000

    def test_restore_cash(self):
        """Cash is restored correctly."""
        state = json.dumps({'available_cash': 750000, 'positions': {}})
        ctx = Context(1000000)
        restore_portfolio(ctx, state)
        assert ctx.portfolio.available_cash == 750000

    def test_restore_single_position(self):
        """Restore one position from JSON."""
        state = json.dumps({
            'available_cash': 800000,
            'positions': {
                '600519': {
                    'code': '600519', 'name': '贵州茅台',
                    'amount': 100, 'closeable_amount': 100,
                    'avg_cost': 1800.0, 'price': 1900.0,
                },
            },
        })
        ctx = Context(1000000)
        restore_portfolio(ctx, state)

        assert '600519' in ctx.portfolio.positions
        pos = ctx.portfolio.positions['600519']
        assert pos.code == '600519'
        assert pos.name == '贵州茅台'
        assert pos.amount == 100
        assert pos.closeable_amount == 100
        assert pos.avg_cost == 1800.0
        assert pos.price == 1900.0
        assert pos.value == 100 * 1900.0

    def test_restore_multiple_positions(self):
        """Restore multiple positions."""
        state = json.dumps({
            'available_cash': 300000,
            'positions': {
                '600519': {'code': '600519', 'name': 'A', 'amount': 100,
                           'closeable_amount': 100, 'avg_cost': 100, 'price': 110},
                '000001': {'code': '000001', 'name': 'B', 'amount': 200,
                           'closeable_amount': 200, 'avg_cost': 10, 'price': 12},
            },
        })
        ctx = Context(1000000)
        restore_portfolio(ctx, state)

        assert len(ctx.portfolio.positions) == 2
        assert ctx.portfolio.available_cash == 300000

    def test_restore_clears_existing_positions(self):
        """Restore should clear any pre-existing positions."""
        ctx = Context(1000000)
        ctx.portfolio.positions['OLD'] = Position('OLD', 'old_stock')
        ctx.portfolio.positions['OLD'].amount = 500

        state = json.dumps({
            'available_cash': 500000,
            'positions': {
                '600519': {'code': '600519', 'name': 'A', 'amount': 100,
                           'closeable_amount': 100, 'avg_cost': 100, 'price': 110},
            },
        })
        restore_portfolio(ctx, state)
        assert 'OLD' not in ctx.portfolio.positions
        assert '600519' in ctx.portfolio.positions

    def test_restore_g_vars(self):
        """GlobalVars are restored."""
        state = json.dumps({
            'available_cash': 1000000,
            'positions': {},
            'g_vars': {'my_flag': True, 'my_count': 42},
        })
        ctx = Context(1000000)
        g = GlobalVars()
        restore_portfolio(ctx, state, g)

        assert g.my_flag is True
        assert g.my_count == 42

    def test_restore_trade_costs(self):
        """Commission, tax, slippage are restored."""
        state = json.dumps({
            'available_cash': 1000000,
            'positions': {},
            'benchmark': '000905',
            'commission_rate': 0.001,
            'stamp_tax_rate': 0.002,
            'slippage_rate': 0.005,
        })
        ctx = Context(1000000)
        restore_portfolio(ctx, state)

        assert ctx.benchmark == '000905'
        assert ctx.commission_rate == 0.001
        assert ctx.stamp_tax_rate == 0.002
        assert ctx.slippage_rate == 0.005

    def test_restore_invalid_json(self):
        """Invalid JSON string should not raise, just warn."""
        ctx = Context(1000000)
        restore_portfolio(ctx, '{bad json}')
        # Should still have default state
        assert ctx.portfolio.available_cash == 1000000

    def test_restore_total_value_updated(self):
        """After restore, total_value = cash + market_value."""
        state = json.dumps({
            'available_cash': 500000,
            'positions': {
                '600519': {'code': '600519', 'name': 'A', 'amount': 100,
                           'closeable_amount': 100, 'avg_cost': 100, 'price': 150},
            },
        })
        ctx = Context(1000000)
        restore_portfolio(ctx, state)

        expected_market = 100 * 150
        assert ctx.portfolio.market_value == expected_market
        assert ctx.portfolio.total_value == 500000 + expected_market


# ===========================================================================
#  3. Round-trip serialize → restore tests
# ===========================================================================

class TestSerializeRestoreRoundTrip:
    """Round-trip: serialize → restore → verify equality."""

    def test_roundtrip_empty(self):
        ctx1, _g1 = _make_context_with_positions(cash=1000000)
        json_str = serialize_portfolio(ctx1)

        ctx2 = Context(1000000)
        restore_portfolio(ctx2, json_str)

        assert ctx2.portfolio.available_cash == ctx1.portfolio.available_cash
        assert len(ctx2.portfolio.positions) == 0

    def test_roundtrip_with_positions(self):
        ctx1, g1 = _make_context_with_positions(
            cash=500000,
            positions_data=[
                {'code': '600519', 'name': '贵州茅台', 'amount': 100,
                 'closeable_amount': 100, 'avg_cost': 1800.0, 'price': 1900.0},
                {'code': '000001', 'name': '平安银行', 'amount': 500,
                 'closeable_amount': 300, 'avg_cost': 15.0, 'price': 16.0},
            ],
        )
        g1.counter = 7
        g1.active = True

        json_str = serialize_portfolio(ctx1)

        ctx2 = Context(1000000)
        g2 = GlobalVars()
        restore_portfolio(ctx2, json_str, g2)

        assert ctx2.portfolio.available_cash == 500000
        assert len(ctx2.portfolio.positions) == 2

        p1 = ctx2.portfolio.positions['600519']
        assert p1.amount == 100
        assert p1.avg_cost == 1800.0
        assert p1.price == 1900.0

        p2 = ctx2.portfolio.positions['000001']
        assert p2.amount == 500
        assert p2.avg_cost == 15.0

        assert g2.counter == 7
        assert g2.active is True

    def test_roundtrip_preserves_costs(self):
        ctx1, _g1 = _make_context_with_positions(cash=1000000)
        ctx1.commission_rate = 0.0005
        ctx1.stamp_tax_rate = 0.0015
        ctx1.slippage_rate = 0.003

        json_str = serialize_portfolio(ctx1)
        ctx2 = Context(1000000)
        restore_portfolio(ctx2, json_str)

        assert ctx2.commission_rate == 0.0005
        assert ctx2.stamp_tax_rate == 0.0015
        assert ctx2.slippage_rate == 0.003


# ===========================================================================
#  4. _create_api tests
# ===========================================================================

class TestCreateApi:
    """Tests for paper_engine._create_api"""

    def test_api_namespace_keys(self):
        """API namespace contains all expected functions."""
        ctx = Context(1000000)
        ctx._engine = type('E', (), {'_stock_data': {}})()
        dp = DataProxy()
        g = GlobalVars()

        ns = _create_api(ctx, dp, g)

        expected_keys = {'history', 'get_price', 'log', 'g', 'record',
                         'set_benchmark', 'set_order_cost'}
        assert expected_keys.issubset(set(ns.keys()))

    def test_g_reference(self):
        """The namespace 'g' is the same GlobalVars object passed in."""
        ctx = Context(1000000)
        ctx._engine = type('E', (), {'_stock_data': {}})()
        g = GlobalVars()
        g.x = 99

        ns = _create_api(ctx, DataProxy(), g)
        assert ns['g'] is g
        assert ns['g'].x == 99

    def test_set_benchmark(self):
        """set_benchmark updates context.benchmark."""
        ctx = Context(1000000)
        ctx._engine = type('E', (), {'_stock_data': {}})()
        ns = _create_api(ctx, DataProxy(), GlobalVars())

        ns['set_benchmark']('000905')
        assert ctx.benchmark == '000905'

    def test_set_order_cost(self):
        """set_order_cost updates context cost attributes."""
        ctx = Context(1000000)
        ctx._engine = type('E', (), {'_stock_data': {}})()
        ns = _create_api(ctx, DataProxy(), GlobalVars())

        ns['set_order_cost'](commission=0.001, tax=0.002, slippage=0.005)
        assert ctx.commission_rate == 0.001
        assert ctx.stamp_tax_rate == 0.002
        assert ctx.slippage_rate == 0.005

    def test_record_is_callable(self):
        """record() should be a no-op callable."""
        ctx = Context(1000000)
        ctx._engine = type('E', (), {'_stock_data': {}})()
        ns = _create_api(ctx, DataProxy(), GlobalVars())

        # Should not raise
        ns['record'](value=1.0, nav=1.05)

    def test_log_has_methods(self):
        """log object has info/warn/error/debug."""
        ctx = Context(1000000)
        ctx._engine = type('E', (), {'_stock_data': {}})()
        ns = _create_api(ctx, DataProxy(), GlobalVars())

        log = ns['log']
        assert callable(getattr(log, 'info', None))
        assert callable(getattr(log, 'warn', None))
        assert callable(getattr(log, 'error', None))
        assert callable(getattr(log, 'debug', None))

    def test_history_returns_series(self, monkeypatch):
        """history() returns an empty Series when dynamic loading has no data."""
        import pandas as pd

        monkeypatch.setattr(
            'quantia.paper_trading.paper_engine._load_security_data',
            lambda code, start_date=None, end_date=None: (code, None),
        )

        ctx = Context(1000000)
        ctx._engine = type('E', (), {'_stock_data': {}})()
        ctx.current_dt = datetime.date(2026, 3, 18)
        ns = _create_api(ctx, DataProxy(), GlobalVars())

        result = ns['history']('600519', 10)
        assert isinstance(result, pd.Series)
        assert len(result) == 0

    def test_history_with_data(self):
        """history() returns correct trailing data."""
        import pandas as pd

        ctx = Context(1000000)
        dates = pd.date_range('2026-03-01', periods=10, freq='B')
        df = pd.DataFrame({
            'date': dates,
            'close': range(100, 110),
            'open': range(99, 109),
            'high': range(101, 111),
            'low': range(98, 108),
            'volume': [1000] * 10,
        })
        ctx._engine = type('E', (), {'_stock_data': {'600519': df}})()
        ctx.current_dt = dates[-1]

        ns = _create_api(ctx, DataProxy(), GlobalVars())
        result = ns['history']('600519', 5)
        assert len(result) == 5
        assert result.iloc[-1] == 109  # last close

    def test_get_price_returns_dataframe(self):
        """get_price() returns a DataFrame (empty when no data)."""
        import pandas as pd

        ctx = Context(1000000)
        ctx._engine = type('E', (), {'_stock_data': {}})()
        ns = _create_api(ctx, DataProxy(), GlobalVars())

        result = ns['get_price']('600519')
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0

    def test_get_price_with_data_and_filter(self):
        """get_price() returns filtered data by date range."""
        import pandas as pd

        ctx = Context(1000000)
        dates = pd.date_range('2026-03-01', periods=10, freq='B')
        df = pd.DataFrame({
            'date': dates,
            'close': range(100, 110),
            'open': range(99, 109),
        })
        ctx._engine = type('E', (), {'_stock_data': {'600519': df}})()

        ns = _create_api(ctx, DataProxy(), GlobalVars())
        result = ns['get_price']('600519', start_date='2026-03-05', end_date='2026-03-10')
        assert len(result) > 0
        # All dates should be within range
        for d in result['date']:
            assert pd.Timestamp('2026-03-05') <= d <= pd.Timestamp('2026-03-10')


# ===========================================================================
#  5. _ensure_*_table tests
# ===========================================================================

class TestEnsureTables:
    """Tests for _ensure_paper_table, _ensure_trade_table, _ensure_position_table."""

    @pytest.fixture(autouse=True)
    def _reset_paper_table_flag(self):
        # _ensure_paper_table 现为进程内一次性建表（_paper_table_ensured 标记）。
        # 每个用例显式重置，避免一次性标记跨用例泄漏导致后续用例被短路跳过。
        import quantia.paper_trading.paper_engine as pe
        pe._paper_table_ensured = False
        yield
        pe._paper_table_ensured = False

    @patch('quantia.lib.database.executeSqlFetch', return_value=[(4,)])
    @patch('quantia.lib.database.checkTableIsExist', return_value=True)
    @patch('quantia.lib.database.executeSql')
    def test_ensure_paper_table_exists(self, mock_exec, mock_check, _mock_fetch):
        """If table exists and migration columns exist, no ALTER/CREATE TABLE issued."""
        _ensure_paper_table()
        mock_check.assert_called_once_with('cn_stock_paper_trading')
        mock_exec.assert_not_called()

    @patch('quantia.lib.database.checkTableIsExist', return_value=False)
    @patch('quantia.lib.database.executeSql')
    def test_ensure_paper_table_creates(self, mock_exec, mock_check):
        """If table doesn't exist, CREATE TABLE is issued."""
        _ensure_paper_table()
        mock_exec.assert_called_once()
        sql = mock_exec.call_args[0][0]
        assert 'CREATE TABLE' in sql
        assert 'cn_stock_paper_trading' in sql
        assert 'strategy_id' in sql
        assert 'backtest_id' in sql
        assert 'run_frequency' in sql
        assert 'start_at' in sql
        assert 'last_run_at' in sql
        assert 'initial_cash' in sql
        assert 'state_json' in sql

    @patch('quantia.lib.database.executeSqlFetch', return_value=[(0,)])
    @patch('quantia.lib.database.checkTableIsExist', return_value=True)
    @patch('quantia.lib.database.executeSql')
    def test_ensure_paper_table_migrates_existing_table(self, mock_exec, _mock_check, _mock_fetch):
        """Existing paper table is migrated with newly introduced scheduling columns."""
        _ensure_paper_table()
        assert mock_exec.call_count == 4
        sqls = [c.args[0] for c in mock_exec.call_args_list]
        assert any('backtest_id' in sql for sql in sqls)
        assert any('run_frequency' in sql for sql in sqls)
        assert any('start_at' in sql for sql in sqls)
        assert any('last_run_at' in sql for sql in sqls)


class TestPaperRunFrequency:
    """Tests for per-paper run frequency gating."""

    def test_daily_scheduled_waits_until_after_close(self):
        due, reason = _is_paper_due(
            'daily', None, None, None, '2026-04-21',
            datetime.datetime(2026, 4, 21, 14, 30), scheduled=True)
        assert due is False
        assert '收盘后' in reason

    def test_daily_skips_same_trade_date(self):
        due, reason = _is_paper_due(
            'daily', None, datetime.date(2026, 4, 21), None, '2026-04-21',
            datetime.datetime(2026, 4, 21, 16, 30), scheduled=False)
        assert due is False
        assert '今日已运行' in reason

    def test_hourly_respects_last_run_at(self):
        due, reason = _is_paper_due(
            'hourly', None, datetime.date(2026, 4, 21),
            datetime.datetime(2026, 4, 21, 10, 0), '2026-04-21',
            datetime.datetime(2026, 4, 21, 10, 30), scheduled=True)
        assert due is False
        assert '下次运行时间' in reason

        due, reason = _is_paper_due(
            'hourly', None, datetime.date(2026, 4, 21),
            datetime.datetime(2026, 4, 21, 10, 0), '2026-04-21',
            datetime.datetime(2026, 4, 21, 11, 0), scheduled=True)
        assert due is True
        assert reason == 'ok'

    def test_start_at_blocks_before_configured_time(self):
        due, reason = _is_paper_due(
            '15m', datetime.datetime(2026, 4, 21, 10, 15), None, None,
            '2026-04-21', datetime.datetime(2026, 4, 21, 10, 0), scheduled=True)
        assert due is False
        assert '未到开始时间' in reason

    def test_hourly_skipped_before_market_open(self):
        # 09:00 still pre-open
        due, reason = _is_paper_due(
            'hourly', None, None, None, '2026-04-21',
            datetime.datetime(2026, 4, 21, 9, 0), scheduled=True)
        assert due is False
        assert '非交易时段' in reason

    def test_hourly_skipped_during_lunch_break(self):
        due, reason = _is_paper_due(
            'hourly', None, None, None, '2026-04-21',
            datetime.datetime(2026, 4, 21, 12, 0), scheduled=True)
        assert due is False
        assert '非交易时段' in reason

    def test_hourly_due_in_morning_session(self):
        due, reason = _is_paper_due(
            'hourly', None, None, None, '2026-04-21',
            datetime.datetime(2026, 4, 21, 10, 30), scheduled=True)
        assert due is True
        assert reason == 'ok'

    def test_hourly_due_after_close_for_eod_pass(self):
        # 15:30 after close — still allow last EOD run
        due, reason = _is_paper_due(
            'hourly', None, None, None, '2026-04-21',
            datetime.datetime(2026, 4, 21, 15, 30), scheduled=True)
        assert due is True
        assert reason == 'ok'

    def test_hourly_manual_run_bypasses_session_gate(self):
        # scheduled=False（手动调用）不受时段限制
        due, reason = _is_paper_due(
            'hourly', None, None, None, '2026-04-21',
            datetime.datetime(2026, 4, 21, 12, 0), scheduled=False)
        assert due is True
        assert reason == 'ok'


class TestPaperSecurityDataRouting:
    """Tests for stock/index data source selection in paper trading."""

    def test_normalize_jq_security_suffix(self):
        assert _normalize_security_code('000300.XSHG') == '000300'
        assert _normalize_security_code('399951.XSHE') == '399951'

    @patch('quantia.paper_trading.paper_engine.load_stock_data')
    @patch('quantia.paper_trading.paper_engine.load_benchmark_data')
    def test_hs300_uses_benchmark_loader(self, mock_benchmark, mock_stock):
        df = pd.DataFrame({'date': pd.to_datetime(['2026-04-21']), 'close': [3900]})
        mock_benchmark.return_value = df

        code, result = _load_security_data('000300.XSHG', '2026-04-01', '2026-04-21')

        assert code == '000300'
        assert result is df
        mock_benchmark.assert_called_once_with('000300', '2026-04-01', '2026-04-21')
        mock_stock.assert_not_called()

    @patch('quantia.paper_trading.paper_engine.load_stock_data')
    @patch('quantia.paper_trading.paper_engine.load_benchmark_data')
    def test_common_stock_uses_stock_loader(self, mock_benchmark, mock_stock):
        df = pd.DataFrame({'date': pd.to_datetime(['2026-04-21']), 'close': [12.3]})
        mock_stock.return_value = df

        code, result = _load_security_data('000001', '2026-04-01', '2026-04-21')

        assert code == '000001'
        assert result is df
        mock_stock.assert_called_once_with('000001', '2026-04-01', '2026-04-21')
        mock_benchmark.assert_not_called()


class TestEnsureTradeAndPositionTables:
    """Tests for _ensure_trade_table and _ensure_position_table."""

    @patch('quantia.lib.database.checkTableIsExist', return_value=True)
    @patch('quantia.lib.database.executeSqlFetch', return_value=[('executed_at',)])
    @patch('quantia.lib.database.executeSql')
    def test_ensure_trade_table_exists(self, mock_exec, mock_fetch, mock_check):
        """\u8868\u5b58\u5728\u4e14 executed_at \u5217\u5df2\u5b58\u5728\uff1a\u4e0d\u5e94 ALTER\u3002"""
        _ensure_trade_table()
        mock_check.assert_called_once_with('cn_stock_backtest_trade')
        mock_exec.assert_not_called()

    @patch('quantia.lib.database.checkTableIsExist', return_value=True)
    @patch('quantia.lib.database.executeSqlFetch', return_value=[])
    @patch('quantia.lib.database.executeSql')
    def test_ensure_trade_table_migrates_executed_at(self, mock_exec, mock_fetch, mock_check):
        """\u8868\u5b58\u5728\u4f46\u7f3a executed_at \u5217\uff1a\u5e94 ALTER \u8865\u4e0a\u3002"""
        _ensure_trade_table()
        mock_exec.assert_called_once()
        sql = mock_exec.call_args[0][0]
        assert 'ALTER TABLE cn_stock_backtest_trade' in sql
        assert 'executed_at' in sql

    @patch('quantia.lib.database.checkTableIsExist', return_value=False)
    @patch('quantia.lib.database.executeSql')
    def test_ensure_trade_table_creates(self, mock_exec, mock_check):
        _ensure_trade_table()
        mock_exec.assert_called_once()
        sql = mock_exec.call_args[0][0]
        assert 'CREATE TABLE' in sql
        assert 'cn_stock_backtest_trade' in sql
        assert 'direction' in sql
        assert 'paper_id' in sql

    @patch('quantia.lib.database.checkTableIsExist', return_value=True)
    @patch('quantia.lib.database.executeSqlFetch', return_value=[('uq_paper_position',)])
    @patch('quantia.lib.database.executeSql')
    def test_ensure_position_table_exists(self, mock_exec, mock_fetch, mock_check):
        _ensure_position_table()
        mock_check.assert_called_once_with('cn_stock_backtest_position')
        mock_exec.assert_not_called()

    @patch('quantia.lib.database.checkTableIsExist', return_value=True)
    @patch('quantia.lib.database.executeSqlFetch', return_value=[])
    @patch('quantia.lib.database.executeSql')
    def test_ensure_position_table_migrates_unique_index(self, mock_exec, mock_fetch, mock_check):
        _ensure_position_table()
        mock_exec.assert_called_once()
        sql = mock_exec.call_args[0][0]
        assert 'ALTER TABLE cn_stock_backtest_position' in sql
        assert 'uq_paper_position' in sql

    @patch('quantia.lib.database.checkTableIsExist', return_value=False)
    @patch('quantia.lib.database.executeSql')
    def test_ensure_position_table_creates(self, mock_exec, mock_check):
        _ensure_position_table()
        mock_exec.assert_called_once()
        sql = mock_exec.call_args[0][0]
        assert 'CREATE TABLE' in sql
        assert 'cn_stock_backtest_position' in sql
        assert 'avg_cost' in sql
        assert 'weight' in sql
        assert 'uq_paper_position' in sql

    @patch('quantia.lib.database.checkTableIsExist', return_value=False)
    @patch('quantia.lib.database.executeSql')
    def test_ensure_intraday_nav_table_creates(self, mock_exec, mock_check):
        from quantia.paper_trading.paper_engine import _ensure_intraday_nav_table
        _ensure_intraday_nav_table()
        mock_check.assert_called_once_with('cn_stock_paper_nav_intraday')
        mock_exec.assert_called_once()
        sql = mock_exec.call_args[0][0]
        assert 'CREATE TABLE' in sql
        assert 'cn_stock_paper_nav_intraday' in sql
        assert '`datetime`' in sql
        assert 'uq_paper_dt' in sql

    @patch('quantia.lib.database.checkTableIsExist', return_value=True)
    @patch('quantia.lib.database.executeSql')
    def test_ensure_intraday_nav_table_exists(self, mock_exec, mock_check):
        from quantia.paper_trading.paper_engine import _ensure_intraday_nav_table
        _ensure_intraday_nav_table()
        mock_check.assert_called_once_with('cn_stock_paper_nav_intraday')
        mock_exec.assert_not_called()


# ===========================================================================
#  6. paperTradingHandler NAV metric tests
# ===========================================================================

class TestPaperTradingNavMetrics:
    """Regression tests for paper detail historical return curves."""

    def test_latest_nav_snapshot_uses_newest_nav_row(self):
        nav_rows = [
            (datetime.date(2026, 4, 29), 100000.00, 90000.00, 10000.00),
            (datetime.date(2026, 4, 30), 98707.13, 88000.00, 10707.13),
        ]

        snapshot = _latest_nav_snapshot(nav_rows)

        assert snapshot == {
            'date': '2026-04-30',
            'total_value': 98707.13,
            'cash': 88000.00,
            'position_value': 10707.13,
        }

    def test_apply_nav_snapshot_overrides_stale_current_value(self):
        info = {
            'initial_cash': 100000,
            'current_value': 100000,
            'current_cash': 100000,
            'position_value': 0,
            'profit_rate': 0,
        }
        snapshot = {
            'date': '2026-04-30',
            'total_value': 98707.13,
            'cash': 88000.00,
            'position_value': 10707.13,
        }

        _apply_nav_snapshot(info, snapshot)

        assert info['current_value'] == 98707.13
        assert info['current_cash'] == 88000.00
        assert info['position_value'] == 10707.13
        assert info['current_value_date'] == '2026-04-30'
        assert info['profit_rate'] == -1.29

    def test_apply_nav_snapshot_ignores_missing_snapshot(self):
        info = {'initial_cash': 100000, 'current_value': 100000}

        result = _apply_nav_snapshot(info, None)

        assert result == {'initial_cash': 100000, 'current_value': 100000}

    def test_metrics_use_initial_cash_not_first_nav(self):
        nav_rows = [
            (datetime.date(2026, 4, 29), 99771.13, 99771.13, 0, 1.0),
            (datetime.date(2026, 4, 30), 98710.00, 98710.00, 0, 1.0),
        ]

        metrics = _compute_paper_metrics(nav_rows, [], initial_cash=100000)

        assert metrics['total_return'] == -1.29

    def test_benchmark_return_uses_normalized_benchmark_value(self):
        nav_rows = [
            (datetime.date(2026, 4, 29), 99771.13, 99771.13, 0, 1.01),
            (datetime.date(2026, 4, 30), 98710.00, 98710.00, 0, 1.03),
        ]

        metrics = _compute_paper_metrics(nav_rows, [], initial_cash=100000)

        assert metrics['benchmark_return'] == 3.0
        assert metrics['excess_return'] == -4.29

    def test_rebuilds_only_default_benchmark_series(self):
        assert _should_rebuild_benchmark_values([1, 1.0, None]) is True
        assert _should_rebuild_benchmark_values([1.0, 1.002]) is False

    def test_benchmark_display_name_normalizes_common_codes(self):
        assert _normalize_benchmark_code('000300.XSHG') == '000300'
        assert _get_benchmark_name('000300.XSHG') == '沪深300'
        assert _get_benchmark_name('000016') == '上证50'
        assert _get_benchmark_return_label('000905') == '基准收益（中证500）'


class TestPaperTradingSettingsUpdate:
    """Regression tests for editable paper trading settings."""

    def test_paper_has_started_detects_nav_or_trade_rows(self):
        assert _paper_has_started(None, 0, 0) is False
        assert _paper_has_started(datetime.date(2026, 4, 30), 0, 0) is True
        assert _paper_has_started(None, 1, 0) is True
        assert _paper_has_started(None, 0, 1) is True

    def test_build_update_fields_allows_initial_cash_before_started(self):
        fields, params, error = _build_paper_update_fields({
            'name': '新模拟盘',
            'run_frequency': 'hourly',
            'start_at': '2026-05-06 09:30:00',
            'initial_cash': 200000,
        }, can_update_initial_cash=True)

        assert error is None
        assert fields == [
            'name=%s', 'run_frequency=%s', 'start_at=%s',
            'initial_cash=%s', 'current_cash=%s', 'current_value=%s',
        ]
        assert params[0] == '新模拟盘'
        assert params[1] == 'hourly'
        assert params[2] == datetime.datetime(2026, 5, 6, 9, 30, 0)
        assert params[3:] == [200000.0, 200000.0, 200000.0]

    def test_build_update_fields_blocks_initial_cash_after_started(self):
        fields, params, error = _build_paper_update_fields({
            'name': '可改名称',
            'run_frequency': '15m',
            'initial_cash': 200000,
        }, can_update_initial_cash=False)

        assert fields is None
        assert params is None
        assert error == '模拟盘已开始运行，不能修改初始资金'

    def test_build_update_fields_validates_frequency_and_start_time(self):
        assert _build_paper_update_fields({'run_frequency': 'weekly'}, True)[2] == '运行频率参数错误'
        assert _build_paper_update_fields({'start_at': 'not-a-date'}, True)[2] == '开始时间格式错误'
        assert _build_paper_update_fields({'name': '   '}, True)[2] == '模拟盘名称不能为空'

    def test_build_update_fields_rejects_low_initial_cash(self):
        fields, params, error = _build_paper_update_fields(
            {'initial_cash': 5000}, can_update_initial_cash=True)
        assert fields is None
        assert params is None
        assert error == '初始资金不能低于 10000'

    def test_build_update_fields_rejects_empty_payload(self):
        fields, params, error = _build_paper_update_fields({}, can_update_initial_cash=True)
        assert fields is None
        assert params is None
        assert error == '没有可更新的字段'

    def test_parse_optional_int_round_trips_numeric_values(self):
        # Regression: _parse_optional_int previously fell into dead code after a
        # refactor and returned None for any non-empty value, which broke
        # CreatePaperTradingHandler / _resolve_backtest_id. Make sure it still
        # parses numeric inputs correctly.
        from quantia.web.paperTradingHandler import _parse_optional_int

        assert _parse_optional_int(None) is None
        assert _parse_optional_int('') is None
        assert _parse_optional_int('123') == 123
        assert _parse_optional_int(456) == 456
        assert _parse_optional_int('not-a-number') is None


# ===========================================================================
#  7. _update_paper_error tests
# ===========================================================================

class TestUpdatePaperError:
    """Tests for paper_engine._update_paper_error"""

    @patch('quantia.lib.database.executeSql')
    def test_updates_status_to_stopped(self, mock_exec):
        _update_paper_error(42, 'compile failed')
        mock_exec.assert_called_once()
        sql = mock_exec.call_args[0][0]
        params = mock_exec.call_args[0][1]
        assert 'UPDATE' in sql
        assert 'cn_stock_paper_trading' in sql
        assert 'stopped' in params
        assert 42 in params

    @patch('quantia.lib.database.executeSql', side_effect=Exception('db down'))
    def test_db_error_suppressed(self, mock_exec):
        """DB errors in _update_paper_error are silently suppressed."""
        # Should not raise
        _update_paper_error(99, 'some error')


# ===========================================================================
#  8. run_paper_trading_daily tests
# ===========================================================================

class TestRunPaperTradingDaily:
    """Tests for paper_engine.run_paper_trading_daily"""

    @patch('quantia.lib.database.checkTableIsExist', return_value=True)
    @patch('quantia.lib.database.executeSql')
    @patch('quantia.lib.database.executeSqlFetch')
    @patch('quantia.lib.trade_time.get_trade_date_last')
    @patch('quantia.lib.trade_time.is_trade_date', return_value=False)
    def test_non_trade_day_skipped(self, mock_is_td, mock_get_td, mock_fetch,
                                   mock_exec, mock_check):
        """Non-trade day returns 'skipped'."""
        mock_get_td.return_value = (datetime.date(2026, 3, 14), datetime.date(2026, 3, 14))
        result = run_paper_trading_daily(1)
        assert result['status'] == 'skipped'
        assert '非交易日' in result['message']

    @patch('quantia.lib.database.checkTableIsExist', return_value=True)
    @patch('quantia.lib.database.executeSql')
    @patch('quantia.lib.database.executeSqlFetch', return_value=[])
    @patch('quantia.lib.trade_time.get_trade_date_last')
    @patch('quantia.lib.trade_time.is_trade_date', return_value=True)
    def test_paper_not_found(self, mock_is_td, mock_get_td, mock_fetch,
                             mock_exec, mock_check):
        """Paper ID not in DB returns error."""
        mock_get_td.return_value = (datetime.date(2026, 3, 18), datetime.date(2026, 3, 18))
        result = run_paper_trading_daily(999)
        assert result['status'] == 'error'
        assert '不存在' in result['message']

    @patch('quantia.lib.database.checkTableIsExist', return_value=True)
    @patch('quantia.lib.database.executeSql')
    @patch('quantia.lib.database.executeSqlFetch')
    @patch('quantia.lib.trade_time.get_trade_date_last')
    @patch('quantia.lib.trade_time.is_trade_date', return_value=True)
    def test_paper_paused_skipped(self, mock_is_td, mock_get_td, mock_fetch,
                                  mock_exec, mock_check):
        """Paused paper returns 'skipped'."""
        mock_get_td.return_value = (datetime.date(2026, 3, 18), datetime.date(2026, 3, 18))
        # row: id, strategy_id, initial_cash, status, last_run_date, state_json, strategy_code
        mock_fetch.return_value = [(1, 10, 1000000, 'paused', None, None, 'pass')]
        result = run_paper_trading_daily(1)
        assert result['status'] == 'skipped'
        assert 'paused' in result['message']

    @patch('quantia.lib.database.checkTableIsExist', return_value=True)
    @patch('quantia.lib.database.executeSql')
    @patch('quantia.lib.database.executeSqlFetch')
    @patch('quantia.lib.trade_time.get_trade_date_last')
    @patch('quantia.lib.trade_time.is_trade_date', return_value=True)
    def test_already_run_today_skipped(self, mock_is_td, mock_get_td, mock_fetch,
                                       mock_exec, mock_check):
        """Paper that already ran today returns 'skipped'."""
        mock_get_td.return_value = (datetime.date(2026, 3, 18), datetime.date(2026, 3, 18))
        mock_fetch.return_value = [(1, 10, 1000000, 'running', '2026-03-18', None, 'pass')]
        result = run_paper_trading_daily(1)
        assert result['status'] == 'skipped'
        assert '已运行' in result['message']

    @patch('quantia.lib.database.checkTableIsExist', return_value=True)
    @patch('quantia.lib.database.executeSql')
    @patch('quantia.lib.database.executeSqlFetch')
    @patch('quantia.lib.trade_time.get_trade_date_last')
    @patch('quantia.lib.trade_time.is_trade_date', return_value=True)
    @patch('quantia.paper_trading.paper_engine.compile_strategy', side_effect=SyntaxError('bad code'))
    def test_compile_error(self, mock_compile, mock_is_td, mock_get_td,
                           mock_fetch, mock_exec, mock_check):
        """Strategy compile failure returns error and updates DB."""
        mock_get_td.return_value = (datetime.date(2026, 3, 18), datetime.date(2026, 3, 18))
        mock_fetch.return_value = [(1, 10, 1000000, 'running', None, None, 'invalid code')]
        result = run_paper_trading_daily(1)
        assert result['status'] == 'error'
        assert '编译失败' in result['message']

    @patch('quantia.lib.database.checkTableIsExist', return_value=True)
    @patch('quantia.lib.database.executeSql')
    @patch('quantia.lib.database.executeSqlFetch')
    @patch('quantia.lib.trade_time.get_trade_date_last')
    @patch('quantia.lib.trade_time.is_trade_date', return_value=True)
    @patch('quantia.paper_trading.paper_engine.compile_strategy')
    @patch('quantia.paper_trading.paper_engine.load_stock_data', return_value=None)
    def test_successful_run_no_trades(self, mock_load, mock_compile, mock_is_td,
                                      mock_get_td, mock_fetch, mock_exec, mock_check):
        """Successful run with empty strategy (no orders)."""
        mock_get_td.return_value = (datetime.date(2026, 3, 18), datetime.date(2026, 3, 18))

        # First call: load paper info. Subsequent: other queries
        state_json = json.dumps({
            'available_cash': 1000000,
            'positions': {},
            'g_vars': {},
            'benchmark': '000300',
            'commission_rate': 0.0003,
            'stamp_tax_rate': 0.001,
            'slippage_rate': 0.002,
        })
        mock_fetch.return_value = [(1, 10, 1000000, 'running', '2026-03-17',
                                    state_json, 'def handle_data(context, data): pass')]

        # compile returns dict with handle_data
        def _noop_handle(ctx, data):
            pass
        mock_compile.return_value = {
            'initialize': lambda ctx: None,
            'handle_data': _noop_handle,
            'before_trading_start': None,
            'after_trading_end': None,
        }

        result = run_paper_trading_daily(1)
        assert result['status'] == 'ok'
        assert result['trades'] == 0

    @patch('quantia.lib.database.checkTableIsExist', return_value=True)
    @patch('quantia.lib.database.executeSql')
    @patch('quantia.lib.database.executeSqlFetch')
    @patch('quantia.lib.trade_time.get_trade_date_last')
    @patch('quantia.lib.trade_time.is_trade_date', return_value=True)
    @patch('quantia.paper_trading.paper_engine.compile_strategy')
    @patch('quantia.paper_trading.paper_engine.load_stock_data', return_value=None)
    def test_first_run_calls_initialize(self, mock_load, mock_compile, mock_is_td,
                                        mock_get_td, mock_fetch, mock_exec, mock_check):
        """First run (no state_json) should call initialize."""
        mock_get_td.return_value = (datetime.date(2026, 3, 18), datetime.date(2026, 3, 18))
        mock_fetch.return_value = [(1, 10, 1000000, 'running', None, None,
                                    'def initialize(ctx): pass')]

        init_called = {'count': 0}

        def _init(ctx):
            init_called['count'] += 1

        def _handle(ctx, data):
            pass

        mock_compile.return_value = {
            'initialize': _init,
            'handle_data': _handle,
            'before_trading_start': None,
            'after_trading_end': None,
        }

        result = run_paper_trading_daily(1)
        assert result['status'] == 'ok'
        assert init_called['count'] == 1

    @patch('quantia.lib.database.checkTableIsExist', return_value=True)
    @patch('quantia.lib.database.executeSql')
    @patch('quantia.lib.database.executeSqlFetch')
    @patch('quantia.lib.trade_time.get_trade_date_last')
    @patch('quantia.lib.trade_time.is_trade_date', return_value=True)
    @patch('quantia.paper_trading.paper_engine.compile_strategy')
    @patch('quantia.paper_trading.paper_engine.load_stock_data', return_value=None)
    def test_initialize_exception_returns_error(self, mock_load, mock_compile,
                                                 mock_is_td, mock_get_td,
                                                 mock_fetch, mock_exec, mock_check):
        """initialize() exception returns error status."""
        mock_get_td.return_value = (datetime.date(2026, 3, 18), datetime.date(2026, 3, 18))
        mock_fetch.return_value = [(1, 10, 1000000, 'running', None, None,
                                    'def initialize(ctx): raise ValueError("bad")')]

        def _bad_init(ctx):
            raise ValueError('bad init')

        mock_compile.return_value = {
            'initialize': _bad_init,
            'handle_data': lambda ctx, data: None,
            'before_trading_start': None,
            'after_trading_end': None,
        }

        result = run_paper_trading_daily(1)
        assert result['status'] == 'error'
        assert 'initialize' in result['message']

    @patch('quantia.lib.database.checkTableIsExist', return_value=True)
    @patch('quantia.lib.database.executeSql')
    @patch('quantia.lib.database.executeSqlFetch')
    @patch('quantia.lib.trade_time.get_trade_date_last')
    @patch('quantia.lib.trade_time.is_trade_date', return_value=True)
    @patch('quantia.paper_trading.paper_engine.compile_strategy')
    @patch('quantia.paper_trading.paper_engine.load_stock_data', return_value=None)
    @patch('quantia.lib.database.get_connection')
    def test_initialize_exception_after_restore_does_not_persist_state(
            self, mock_get_conn, mock_load, mock_compile, mock_is_td,
            mock_get_td, mock_fetch, mock_exec, mock_check):
        """Restored paper state must not continue/save if initialize() fails."""
        mock_get_td.return_value = (datetime.date(2026, 3, 18), datetime.date(2026, 3, 18))
        state_json = json.dumps({
            'available_cash': 1000000, 'positions': {}, 'g_vars': {},
            'benchmark': '000300', 'commission_rate': 0.0003,
            'stamp_tax_rate': 0.001, 'slippage_rate': 0.002,
        })
        mock_fetch.return_value = [(1, 10, 1000000, 'running', '2026-03-17',
                                    state_json, 'def initialize(ctx): pass')]

        def _bad_init(ctx):
            raise ValueError('restore init failed')

        mock_compile.return_value = {
            'initialize': _bad_init,
            'handle_data': lambda ctx, data: None,
            'before_trading_start': None,
            'after_trading_end': None,
        }

        result = run_paper_trading_daily(1)

        assert result['status'] == 'error'
        assert 'initialize' in result['message']
        mock_get_conn.assert_not_called()

    @patch('quantia.lib.database.checkTableIsExist', return_value=True)
    @patch('quantia.lib.database.executeSql')
    @patch('quantia.lib.database.executeSqlFetch')
    @patch('quantia.lib.trade_time.get_trade_date_last')
    @patch('quantia.lib.trade_time.is_trade_date', return_value=True)
    @patch('quantia.paper_trading.paper_engine.compile_strategy')
    @patch('quantia.paper_trading.paper_engine.load_stock_data', return_value=None)
    @patch('quantia.lib.database.get_connection')
    def test_state_saved_after_run(self, mock_get_conn, mock_load, mock_compile, mock_is_td,
                                   mock_get_td, mock_fetch, mock_exec, mock_check):
        """After successful run, state is saved via get_connection transaction."""
        mock_get_td.return_value = (datetime.date(2026, 3, 18), datetime.date(2026, 3, 18))
        state_json = json.dumps({
            'available_cash': 1000000, 'positions': {},
            'g_vars': {}, 'benchmark': '000300',
            'commission_rate': 0.0003, 'stamp_tax_rate': 0.001, 'slippage_rate': 0.002,
        })
        mock_fetch.return_value = [(1, 10, 1000000, 'running', '2026-03-17',
                                    state_json, 'def handle_data(c,d): pass')]
        mock_compile.return_value = {
            'initialize': lambda c: None,
            'handle_data': lambda c, d: None,
            'before_trading_start': None,
            'after_trading_end': None,
        }

        # Mock get_connection context manager and cursor
        mock_cur = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_conn)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_get_conn.return_value = mock_ctx

        run_paper_trading_daily(1)

        # Check UPDATE was called via cursor.execute
        update_calls = [c for c in mock_cur.execute.call_args_list
                        if 'UPDATE cn_stock_paper_trading' in str(c)]
        assert len(update_calls) >= 1

    @patch('quantia.lib.database.checkTableIsExist', return_value=True)
    @patch('quantia.lib.database.executeSql')
    @patch('quantia.lib.database.executeSqlFetch')
    @patch('quantia.lib.trade_time.get_trade_date_last')
    @patch('quantia.lib.trade_time.is_trade_date', return_value=True)
    @patch('quantia.paper_trading.paper_engine.compile_strategy')
    @patch('quantia.paper_trading.paper_engine.load_stock_data')
    @patch('quantia.lib.database.get_connection')
    def test_run_with_existing_position_and_prices(self, mock_get_conn, mock_load, mock_compile,
                                                    mock_is_td, mock_get_td,
                                                    mock_fetch, mock_exec, mock_check):
        """Run with an existing position; prices are loaded and portfolio updated."""
        import pandas as pd

        mock_get_td.return_value = (datetime.date(2026, 3, 18), datetime.date(2026, 3, 18))

        state_json = json.dumps({
            'available_cash': 800000,
            'positions': {
                '600519': {
                    'code': '600519', 'name': '贵州茅台',
                    'amount': 100, 'closeable_amount': 100,
                    'avg_cost': 1800.0, 'price': 1850.0,
                },
            },
            'g_vars': {},
            'benchmark': '000300',
            'commission_rate': 0.0003,
            'stamp_tax_rate': 0.001,
            'slippage_rate': 0.002,
        })
        mock_fetch.return_value = [(1, 10, 1000000, 'running', '2026-03-17',
                                    state_json, 'def handle_data(c,d): pass')]

        # Provide price data for 600519
        dates = pd.date_range('2026-03-01', '2026-03-18', freq='B')
        df = pd.DataFrame({
            'date': dates,
            'close': [1900.0] * len(dates),
            'open': [1890.0] * len(dates),
            'high': [1910.0] * len(dates),
            'low': [1880.0] * len(dates),
            'volume': [10000] * len(dates),
            'pre_close': [1895.0] * len(dates),
        })
        mock_load.return_value = df

        mock_compile.return_value = {
            'initialize': lambda c: None,
            'handle_data': lambda c, d: None,
            'before_trading_start': None,
            'after_trading_end': None,
        }

        # Mock get_connection context manager and cursor
        mock_cur = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_conn)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_get_conn.return_value = mock_ctx

        result = run_paper_trading_daily(1)
        assert result['status'] == 'ok'

    @patch('quantia.lib.database.checkTableIsExist', return_value=True)
    @patch('quantia.lib.database.executeSql')
    @patch('quantia.lib.database.executeSqlFetch')
    @patch('quantia.lib.trade_time.get_trade_date_last')
    @patch('quantia.lib.trade_time.is_trade_date', return_value=True)
    @patch('quantia.paper_trading.paper_engine.compile_strategy')
    @patch('quantia.paper_trading.paper_engine.load_stock_data')
    @patch('quantia.lib.database.get_connection')
    def test_intraday_rerun_preserves_t_plus_one(self, mock_get_conn, mock_load,
                                                  mock_compile, mock_is_td, mock_get_td,
                                                  mock_fetch, mock_exec, mock_check):
        """同日 hourly 重入：日频策略逻辑(handle_data)只在每个交易日执行一次。

        修复后语义：同一交易日的后续运行跳过 handle_data（不再重复调仓），
        既保留 T+1（closeable_amount 不被重置），又从根上消除“同日买入又卖出”。
        """
        import pandas as pd

        mock_get_td.return_value = (datetime.date(2026, 3, 18), datetime.date(2026, 3, 18))

        # 持仓 amount=200 但 closeable_amount=0 (今天买入，明天才能卖)
        state_json = json.dumps({
            'available_cash': 600000,
            'positions': {
                '600519': {
                    'code': '600519', 'name': '贵州茅台',
                    'amount': 200, 'closeable_amount': 0,
                    'avg_cost': 1800.0, 'price': 1850.0,
                },
            },
            'g_vars': {}, 'benchmark': '000300',
            'commission_rate': 0.0003, 'stamp_tax_rate': 0.001, 'slippage_rate': 0.002,
        })
        # 同日重入：last_run_date 已经是今天 2026-03-18, run_frequency=hourly
        mock_fetch.return_value = [(1, 10, 1000000, 'running',
                                    datetime.date(2026, 3, 18), state_json,
                                    'def handle_data(c,d): pass',
                                    'hourly', None,
                                    datetime.datetime(2026, 3, 18, 10, 0))]

        dates = pd.date_range('2026-03-01', '2026-03-18', freq='B')
        df = pd.DataFrame({
            'date': dates,
            'close': [1900.0] * len(dates),
            'open': [1890.0] * len(dates),
            'high': [1910.0] * len(dates),
            'low': [1880.0] * len(dates),
            'volume': [10000] * len(dates),
            'pre_close': [1895.0] * len(dates),
        })
        mock_load.return_value = df

        captured = {}

        def _handle(ctx, data):
            pos = ctx.portfolio.positions.get('600519')
            if pos is not None:
                captured['amount'] = pos.amount
                captured['closeable_amount'] = pos.closeable_amount

        mock_compile.return_value = {
            'initialize': lambda c: None,
            'handle_data': _handle,
            'before_trading_start': None,
            'after_trading_end': None,
        }

        mock_cur = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_conn)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_get_conn.return_value = mock_ctx

        result = run_paper_trading_daily(
            1, scheduled=True,
            now=datetime.datetime(2026, 3, 18, 11, 0))
        assert result['status'] == 'ok'
        # 关键断言：同一交易日重入跳过 handle_data（日频逻辑每日仅执行一次），
        # 因此不会重复调仓、不会把 closeable_amount 拉回 amount。
        assert 'amount' not in captured

    @patch('quantia.lib.database.checkTableIsExist', return_value=True)
    @patch('quantia.lib.database.executeSql')
    @patch('quantia.lib.database.executeSqlFetch')
    @patch('quantia.lib.trade_time.get_trade_date_last')
    @patch('quantia.lib.trade_time.is_trade_date', return_value=True)
    @patch('quantia.paper_trading.paper_engine.compile_strategy')
    @patch('quantia.paper_trading.paper_engine.load_stock_data')
    @patch('quantia.lib.database.get_connection')
    def test_cross_day_run_resets_t_plus_one(self, mock_get_conn, mock_load,
                                              mock_compile, mock_is_td, mock_get_td,
                                              mock_fetch, mock_exec, mock_check):
        """跨日: 上一交易日 closeable_amount=0 应被重置为 amount."""
        import pandas as pd

        mock_get_td.return_value = (datetime.date(2026, 3, 18), datetime.date(2026, 3, 18))

        state_json = json.dumps({
            'available_cash': 600000,
            'positions': {
                '600519': {
                    'code': '600519', 'name': '贵州茅台',
                    'amount': 200, 'closeable_amount': 0,
                    'avg_cost': 1800.0, 'price': 1850.0,
                },
            },
            'g_vars': {}, 'benchmark': '000300',
            'commission_rate': 0.0003, 'stamp_tax_rate': 0.001, 'slippage_rate': 0.002,
        })
        mock_fetch.return_value = [(1, 10, 1000000, 'running',
                                    datetime.date(2026, 3, 17), state_json,
                                    'def handle_data(c,d): pass')]

        dates = pd.date_range('2026-03-01', '2026-03-18', freq='B')
        df = pd.DataFrame({
            'date': dates,
            'close': [1900.0] * len(dates),
            'open': [1890.0] * len(dates),
            'high': [1910.0] * len(dates),
            'low': [1880.0] * len(dates),
            'volume': [10000] * len(dates),
            'pre_close': [1895.0] * len(dates),
        })
        mock_load.return_value = df

        captured = {}

        def _handle(ctx, data):
            pos = ctx.portfolio.positions.get('600519')
            if pos is not None:
                captured['closeable_amount'] = pos.closeable_amount

        mock_compile.return_value = {
            'initialize': lambda c: None,
            'handle_data': _handle,
            'before_trading_start': None,
            'after_trading_end': None,
        }

        mock_cur = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_conn)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_get_conn.return_value = mock_ctx

        result = run_paper_trading_daily(1)
        assert result['status'] == 'ok'
        # 跨日: closeable_amount 应被 _on_new_day 重置为 amount
        assert captured['closeable_amount'] == 200

    @patch('quantia.lib.database.checkTableIsExist', return_value=True)
    @patch('quantia.lib.database.executeSql')
    @patch('quantia.lib.database.executeSqlFetch')
    @patch('quantia.lib.trade_time.get_trade_date_last')
    @patch('quantia.lib.trade_time.is_trade_date', return_value=True)
    def test_unexpected_exception_returns_error(self, mock_is_td, mock_get_td,
                                                 mock_fetch, mock_exec, mock_check):
        """Unexpected exception in run_paper_trading_daily returns error dict."""
        mock_get_td.return_value = (datetime.date(2026, 3, 18), datetime.date(2026, 3, 18))
        mock_fetch.side_effect = RuntimeError('db exploded')

        result = run_paper_trading_daily(1)
        assert result['status'] == 'error'
        assert 'db exploded' in result['message']


# ===========================================================================
#  9. run_all_paper_trading tests
# ===========================================================================

class TestRunAllPaperTrading:
    """Tests for paper_engine.run_all_paper_trading"""

    @patch('quantia.lib.database.checkTableIsExist', return_value=True)
    @patch('quantia.lib.database.executeSql')
    @patch('quantia.lib.database.executeSqlFetch', return_value=[])
    def test_no_running_papers(self, mock_fetch, mock_exec, mock_check):
        """No running papers → returns None."""
        result = run_all_paper_trading()
        assert result is None

    @patch('quantia.paper_trading.paper_engine.run_paper_trading_daily')
    @patch('quantia.lib.database.checkTableIsExist', return_value=True)
    @patch('quantia.lib.database.executeSql')
    @patch('quantia.lib.database.executeSqlFetch', return_value=[(1,), (2,), (3,)])
    def test_runs_each_paper(self, mock_fetch, mock_exec, mock_check, mock_run):
        """Calls run_paper_trading_daily for each active paper."""
        mock_run.return_value = {'status': 'ok', 'message': 'done', 'trades': 0}

        results = run_all_paper_trading()

        assert len(results) == 3
        mock_run.assert_any_call(1, scheduled=False)
        mock_run.assert_any_call(2, scheduled=False)
        mock_run.assert_any_call(3, scheduled=False)

    @patch('quantia.paper_trading.paper_engine.run_paper_trading_daily')
    @patch('quantia.lib.database.checkTableIsExist', return_value=True)
    @patch('quantia.lib.database.executeSql')
    @patch('quantia.lib.database.executeSqlFetch', return_value=[(10,)])
    def test_result_includes_id(self, mock_fetch, mock_exec, mock_check, mock_run):
        """Each result dict includes the paper id."""
        mock_run.return_value = {'status': 'ok', 'message': 'done', 'trades': 2}

        results = run_all_paper_trading()
        assert results[0]['id'] == 10
        assert results[0]['status'] == 'ok'

    @patch('quantia.paper_trading.paper_engine.run_paper_trading_daily')
    @patch('quantia.lib.database.checkTableIsExist', return_value=True)
    @patch('quantia.lib.database.executeSql')
    @patch('quantia.lib.database.executeSqlFetch', return_value=[(1,), (2,)])
    def test_mixed_results(self, mock_fetch, mock_exec, mock_check, mock_run):
        """Handles mix of success/error results."""
        mock_run.side_effect = [
            {'status': 'ok', 'message': 'done', 'trades': 1},
            {'status': 'error', 'message': 'failed'},
        ]

        results = run_all_paper_trading()
        assert results[0]['status'] == 'ok'
        assert results[1]['status'] == 'error'


# ===========================================================================
#  10. Context / Portfolio / Position integration edge-case tests
# ===========================================================================

class TestContextPositionEdgeCases:
    """Edge-case tests ensuring serialize/restore handle boundary conditions."""

    def test_position_profit_and_profit_rate(self):
        """Position.profit and profit_rate computed correctly after restore."""
        state = json.dumps({
            'available_cash': 500000,
            'positions': {
                '600519': {'code': '600519', 'name': 'A', 'amount': 100,
                           'closeable_amount': 100, 'avg_cost': 100.0, 'price': 120.0},
            },
        })
        ctx = Context(1000000)
        restore_portfolio(ctx, state)

        pos = ctx.portfolio.positions['600519']
        assert pos.profit == (120.0 - 100.0) * 100
        assert abs(pos.profit_rate - 0.20) < 1e-9

    def test_zero_cost_position_profit_rate(self):
        """profit_rate is 0 when avg_cost is 0."""
        pos = Position('000001')
        pos.amount = 100
        pos.avg_cost = 0.0
        pos.price = 10.0
        assert pos.profit_rate == 0.0

    def test_empty_position_profit(self):
        """profit is 0 when amount is 0."""
        pos = Position('000001')
        pos.amount = 0
        pos.avg_cost = 50.0
        pos.price = 60.0
        assert pos.profit == 0.0

    def test_roundtrip_large_portfolio(self):
        """Round-trip with many positions."""
        positions_data = [
            {'code': f'{600000 + i:06d}', 'name': f'Stock{i}', 'amount': 100 * (i + 1),
             'closeable_amount': 100 * (i + 1), 'avg_cost': 10.0 + i,
             'price': 11.0 + i}
            for i in range(20)
        ]
        ctx1, g1 = _make_context_with_positions(cash=100000, positions_data=positions_data)
        g1.iteration = 99

        json_str = serialize_portfolio(ctx1)
        ctx2 = Context(1000000)
        g2 = GlobalVars()
        restore_portfolio(ctx2, json_str, g2)

        assert len(ctx2.portfolio.positions) == 20
        assert g2.iteration == 99
        assert ctx2.portfolio.available_cash == 100000

    def test_restore_defaults_when_keys_missing(self):
        """Missing keys in JSON should fall back to defaults."""
        state = json.dumps({'available_cash': 999999})
        ctx = Context(1000000)
        restore_portfolio(ctx, state)

        assert ctx.portfolio.available_cash == 999999
        assert len(ctx.portfolio.positions) == 0
        # Defaults should be the standard values
        assert ctx.benchmark == '000300'
        assert ctx.commission_rate == 0.0003

    def test_portfolio_update_value(self):
        """_update_value correctly sums market_value + cash."""
        ctx, _g = _make_context_with_positions(
            cash=400000,
            positions_data=[
                {'code': '600519', 'name': 'A', 'amount': 100,
                 'closeable_amount': 100, 'avg_cost': 100, 'price': 200},
                {'code': '000001', 'name': 'B', 'amount': 200,
                 'closeable_amount': 200, 'avg_cost': 50, 'price': 60},
            ],
        )
        assert ctx.portfolio.market_value == 100 * 200 + 200 * 60
        assert ctx.portfolio.total_value == 400000 + 100 * 200 + 200 * 60


# ===========================================================================
#  RC1: context_vars 持久化 + restore_runtime_vars（修复调仓计数器每轮被重置）
# ===========================================================================

class TestContextVarsPersistence:
    """context 标量状态（如 hold_days）必须跨运行持久化，否则 hourly 下调仓门被击穿。"""

    def test_context_vars_serialized(self):
        ctx, _g = _make_context_with_positions(cash=1000000)
        ctx.hold_days = 7
        ctx.stocks = ['600519', '000001']
        ctx.pool_size = 80

        state = json.loads(serialize_portfolio(ctx))
        assert 'context_vars' in state
        assert state['context_vars']['hold_days'] == 7
        assert state['context_vars']['stocks'] == ['600519', '000001']
        assert state['context_vars']['pool_size'] == 80

    def test_context_vars_excludes_reserved_and_objects(self):
        ctx, _g = _make_context_with_positions(cash=1000000)
        ctx.hold_days = 3
        state = json.loads(serialize_portfolio(ctx))
        cv = state['context_vars']
        # 引擎管理 / 顶层已序列化的字段不应混入 context_vars
        for k in ('portfolio', 'benchmark', 'commission_rate', 'current_dt',
                  'slippage_rate', 'stamp_tax_rate'):
            assert k not in cv

    def test_restore_runtime_vars_reapplies_counter(self):
        """模拟 initialize 把 hold_days 重置为 0 后，restore_runtime_vars 回填真实值。"""
        ctx, g = _make_context_with_positions(cash=1000000)
        ctx.hold_days = 19
        g.days = 19
        state_json = serialize_portfolio(ctx)

        # 模拟下一轮：initialize 重置计数器
        ctx.hold_days = 0
        g.days = 0
        restore_runtime_vars(ctx, state_json, g)
        assert ctx.hold_days == 19
        assert g.days == 19

    def test_restore_runtime_vars_noop_on_empty(self):
        ctx, g = _make_context_with_positions(cash=1000000)
        ctx.hold_days = 5
        restore_runtime_vars(ctx, None, g)
        restore_runtime_vars(ctx, '', g)
        assert ctx.hold_days == 5

    def test_rebalance_gate_holds_across_runs(self):
        """端到端语义：counter 持久化后，hold_days%20 只在第 1、21 天满足。"""
        ctx, g = _make_context_with_positions(cash=1000000)
        rebalance_days = []
        state_json = None
        for day in range(1, 42):
            # 每个新交易日：initialize 重置 -> 回填 -> handle_data +1
            ctx.hold_days = 0
            if state_json:
                restore_runtime_vars(ctx, state_json, g)
            ctx.hold_days += 1
            if ctx.hold_days % 20 == 1:
                rebalance_days.append(day)
            state_json = serialize_portfolio(ctx)
        assert rebalance_days == [1, 21, 41]


# ===========================================================================
#  RC2: 同 bar 对冲单净额合并（消除“卖光又买回”的同日换手）
# ===========================================================================

class TestNetSameBarOrders:
    """_net_same_bar_orders 把同一标的的对冲单在价值空间合并为净额。"""

    @staticmethod
    def _ctx_with_pos(code, amount, price):
        ctx = Context(1000000)
        pos = Position(code, '')
        pos.amount = amount
        pos.closeable_amount = amount
        pos.avg_cost = price
        pos.price = price
        pos.value = amount * price
        ctx.portfolio.positions[code] = pos
        ctx.portfolio.available_cash = 1000000
        ctx.portfolio._update_value()
        return ctx

    def test_sell_then_rebuy_same_target_collapses_to_hold(self):
        """order_target(0) + order_target_value(=当前市值) -> 净额≈0（持有，不换手）。"""
        code = '603066'
        price = 10.75
        ctx = self._ctx_with_pos(code, 2700, price)
        cur_val = 2700 * price
        orders = [
            # 卖出循环：order_target(code, 0) -> amount = 0 - 2700
            {'code': code, 'amount': -2700, 'value': None,
             'order_api': 'order_target', 'target_amount': 0, 'reason': 'sell'},
            # 买入循环：order_target_value(code, cur_val) -> value = cur_val - cur_val = 0
            {'code': code, 'amount': None, 'value': 0.0,
             'order_api': 'order_target_value', 'reason': 'buy'},
        ]
        netted = _net_same_bar_orders(orders, ctx, {code: price})
        assert len(netted) == 1
        # 净额价值≈0 -> 撮合时折算成 0 手 -> 不成交
        net_amt = int((netted[0]['value'] or 0) / price / 100) * 100
        assert net_amt == 0

    def test_sell_then_rebuy_to_higher_target_nets_buy(self):
        """卖光后买回到更高目标 -> 净额为正（小幅买入），而非先卖光再全额买。"""
        code = '600036'
        price = 37.70
        ctx = self._ctx_with_pos(code, 800, price)
        cur_val = 800 * price
        target_val = cur_val + 10000  # 想加仓 1 万
        orders = [
            {'code': code, 'amount': -800, 'value': None,
             'order_api': 'order_target', 'target_amount': 0, 'reason': 'sell'},
            {'code': code, 'amount': None, 'value': target_val - cur_val,
             'order_api': 'order_target_value', 'reason': 'buy'},
        ]
        netted = _net_same_bar_orders(orders, ctx, {code: price})
        assert len(netted) == 1
        assert abs(netted[0]['value'] - 10000) < 1e-6  # 净额 = 目标 - 起始 = +1万

    def test_single_order_untouched(self):
        code = '000001'
        ctx = self._ctx_with_pos(code, 500, 15.0)
        orders = [{'code': code, 'amount': 100, 'value': None,
                   'order_api': 'order', 'reason': 'add'}]
        netted = _net_same_bar_orders(orders, ctx, {code: 15.0})
        assert netted == orders

    def test_distinct_codes_untouched(self):
        ctx = Context(1000000)
        orders = [
            {'code': 'A', 'amount': 100, 'value': None, 'order_api': 'order'},
            {'code': 'B', 'amount': -200, 'value': None, 'order_api': 'order'},
        ]
        netted = _net_same_bar_orders(orders, ctx, {'A': 10.0, 'B': 20.0})
        assert len(netted) == 2

    def test_no_price_keeps_original(self):
        code = 'C'
        ctx = self._ctx_with_pos(code, 100, 5.0)
        orders = [
            {'code': code, 'amount': -100, 'value': None, 'order_api': 'order_target', 'target_amount': 0},
            {'code': code, 'amount': None, 'value': 500.0, 'order_api': 'order_target_value'},
        ]
        netted = _net_same_bar_orders(orders, ctx, {})  # 无当日价
        assert len(netted) == 2  # 保持原样，不强行合并

