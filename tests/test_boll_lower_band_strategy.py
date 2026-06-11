#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


def _make_market_df(start='2024-01-02', periods=320, base=20.0):
    dates = pd.bdate_range(start=start, periods=periods)
    down_len = max(20, int(periods * 0.40))
    flat_len = max(15, int(periods * 0.30))
    up_len = max(1, periods - down_len - flat_len)
    down = np.linspace(base, base * 0.45, down_len)
    flat = np.linspace(base * 0.45, base * 0.50, flat_len)
    up = np.linspace(base * 0.50, base * 0.70, up_len)
    close = np.concatenate([down, flat, up])
    open_price = close * 0.995
    high = close * 1.02
    low = close * 0.98
    volume = np.linspace(200000, 260000, periods).astype(int)
    return pd.DataFrame({
        'date': dates,
        'open': open_price,
        'high': high,
        'low': low,
        'close': close,
        'volume': volume,
        'amount': volume * close * 100,
    })


def _make_boll_entry_df(start='2022-01-03', periods=820, base=20.0):
    dates = pd.bdate_range(start=start, periods=periods)
    stable_len = 430
    down_len = 120
    bottom_len = 55
    rebound_len = 70
    rest_len = max(1, periods - stable_len - down_len - bottom_len - rebound_len)
    stable = base + np.sin(np.linspace(0, 12, stable_len)) * base * 0.02
    down = np.linspace(base * 0.98, base * 0.48, down_len)
    bottom = base * 0.48 + np.sin(np.linspace(0, 6, bottom_len)) * base * 0.01
    rebound = np.linspace(base * 0.49, base * 0.68, rebound_len)
    rest = np.linspace(base * 0.68, base * 0.78, rest_len)
    close = np.concatenate([stable, down, bottom, rebound, rest])[:periods]
    open_price = close * 0.995
    high = close * 1.02
    low = close * 0.98
    volume = np.linspace(220000, 320000, periods).astype(int)
    return pd.DataFrame({
        'date': dates,
        'open': open_price,
        'high': high,
        'low': low,
        'close': close,
        'volume': volume,
        'amount': volume * close * 100,
    })


def _make_benchmark_df(start='2022-01-03', periods=820, base=4000.0):
    dates = pd.bdate_range(start=start, periods=periods)
    close = np.linspace(base, base * 1.08, periods)
    open_price = close * 0.998
    high = close * 1.01
    low = close * 0.99
    volume = np.linspace(1000000, 1200000, periods).astype(int)
    return pd.DataFrame({
        'date': dates,
        'open': open_price,
        'high': high,
        'low': low,
        'close': close,
        'volume': volume,
        'amount': volume * close * 100,
    })


def _write_stock_cache(code, df):
    from quantia.core.backtest.data_feed import _CACHE_DIR
    os.makedirs(_CACHE_DIR, exist_ok=True)
    path = os.path.join(_CACHE_DIR, f'{code}.gzip.pickle')
    df.to_pickle(path)
    return path


def _write_index_cache(code, df):
    from quantia.core.backtest.data_feed import _CACHE_DIR
    index_dir = os.path.join(_CACHE_DIR, 'index')
    os.makedirs(index_dir, exist_ok=True)
    path = os.path.join(index_dir, f'{code}.gzip.pickle')
    df.to_pickle(path)
    return path


def test_boll_strategy_template_is_registered_and_valid():
    from quantia.core.backtest.boll_lower_band_strategy import (
        BOLL_LOWER_BAND_VALUE_STRATEGY_CODE,
    )
    from quantia.core.backtest.strategy_sandbox import compile_strategy, validate_code
    from quantia.web.portfolioBacktestHandler import STRATEGY_TEMPLATES

    ok, err = validate_code(BOLL_LOWER_BAND_VALUE_STRATEGY_CODE)
    assert ok, err
    funcs = compile_strategy(BOLL_LOWER_BAND_VALUE_STRATEGY_CODE)
    assert callable(funcs['initialize'])
    assert '_aggregate_bars' in BOLL_LOWER_BAND_VALUE_STRATEGY_CODE
    assert '_macd_green_shrinking' in BOLL_LOWER_BAND_VALUE_STRATEGY_CODE
    assert '_relative_strength_ok' in BOLL_LOWER_BAND_VALUE_STRATEGY_CODE
    assert '_monthly_lower_breakout_seen' in BOLL_LOWER_BAND_VALUE_STRATEGY_CODE
    assert '_ma5_crosses_ma20_up' in BOLL_LOWER_BAND_VALUE_STRATEGY_CODE
    assert 'monthly_lower' in BOLL_LOWER_BAND_VALUE_STRATEGY_CODE
    assert 'monthly_lower_breakout_seen' in BOLL_LOWER_BAND_VALUE_STRATEGY_CODE
    assert 'daily_ma5_cross_ma20_up' in BOLL_LOWER_BAND_VALUE_STRATEGY_CODE
    assert 'weekly_middle' in BOLL_LOWER_BAND_VALUE_STRATEGY_CODE
    assert '_market_allows_entry' in BOLL_LOWER_BAND_VALUE_STRATEGY_CODE
    assert 'g.added' in BOLL_LOWER_BAND_VALUE_STRATEGY_CODE
    assert '亏损企稳加仓' in BOLL_LOWER_BAND_VALUE_STRATEGY_CODE
    assert '月线下轨后MA5上穿MA20买入' in BOLL_LOWER_BAND_VALUE_STRATEGY_CODE
    assert any(tpl['id'] == 'boll_lower_band_value' for tpl in STRATEGY_TEMPLATES)


def test_builtin_template_sync_updates_stale_db_code(monkeypatch):
    import quantia.web.portfolioBacktestHandler as handler

    template = {
        'name': 'BOLL带下轨价值低位策略',
        'code': 'new code with _aggregate_bars',
        'description': 'new description',
        'category': 'stock',
    }
    executed = []

    monkeypatch.setattr(handler, '_ensure_strategy_table', lambda: None)
    monkeypatch.setattr(handler.mdb, 'executeSqlFetch', lambda sql, params=(): [(
        90, 'old code', 'old description', 'stock', 'oldhash', 0
    )])
    monkeypatch.setattr(handler.mdb, 'executeSql', lambda sql, params=(): executed.append((sql, params)))

    result = handler.sync_strategy_templates_to_db([template])

    assert result == {'updated': 1, 'inserted': 0, 'unchanged': 0, 'skipped_user_modified': 0}
    assert len(executed) == 1
    assert executed[0][1][0].startswith('new code with _aggregate_bars')
    assert '[Quantia Template Param Self-Heal v1]' in executed[0][1][0]
    assert executed[0][1][1:4] == ('new description', 'stock', 'BOLL带下轨价值低位策略')
    assert executed[0][1][-2:] == (0, 90)


def test_builtin_template_sync_updates_code_missing_self_heal(monkeypatch):
    import quantia.web.portfolioBacktestHandler as handler

    template = {
        'name': 'BOLL带下轨价值低位策略',
        'code': 'same code',
        'description': 'same description',
        'category': 'stock',
        'id': 'boll_lower_band_value',
    }
    executed = []

    monkeypatch.setattr(handler, '_ensure_strategy_table', lambda: None)
    monkeypatch.setattr(handler.mdb, 'executeSqlFetch', lambda sql, params=(): [{
        'id': 90,
        'code': 'same code',
        'description': 'same description',
        'category': 'stock',
        'template_hash': handler._template_hash('same code'),
        'user_modified': 0,
    }])
    monkeypatch.setattr(handler.mdb, 'executeSql', lambda sql, params=(): executed.append((sql, params)))

    result = handler.sync_strategy_templates_to_db([template])

    # Existing code without self-heal snippet is treated as stale and will be upgraded.
    assert result == {'updated': 1, 'inserted': 0, 'unchanged': 0, 'skipped_user_modified': 0}
    assert len(executed) == 1
    assert '[Quantia Template Param Self-Heal v1]' in executed[0][1][0]


def test_builtin_template_sync_skips_user_modified_template(monkeypatch):
    import quantia.web.portfolioBacktestHandler as handler

    template = {
        'id': 'boll_lower_band_value',
        'name': 'BOLL带下轨价值低位策略',
        'code': 'official template code',
        'description': 'official description',
        'category': 'stock',
    }
    executed = []

    monkeypatch.setattr(handler, '_ensure_strategy_table', lambda: None)
    monkeypatch.setattr(handler.mdb, 'executeSqlFetch', lambda sql, params=(): [{
        'id': 90,
        'code': 'user changed code',
        'description': 'user description',
        'category': 'stock',
        'template_hash': handler._template_hash('old official code'),
        'user_modified': 1,
    }])
    monkeypatch.setattr(handler.mdb, 'executeSql', lambda sql, params=(): executed.append((sql, params)))

    result = handler.sync_strategy_templates_to_db([template])

    assert result == {'updated': 0, 'inserted': 0, 'unchanged': 0, 'skipped_user_modified': 1}
    assert executed == []


def test_saving_builtin_template_without_real_change_is_not_user_modified(monkeypatch):
    import quantia.web.portfolioBacktestHandler as handler

    official_code = 'def initialize(context):\n    pass\n'
    monkeypatch.setattr(handler, 'STRATEGY_TEMPLATES', [{
        'id': 'demo_template',
        'name': 'Demo',
        'code': official_code,
    }])
    monkeypatch.setattr(handler.mdb, 'executeSqlFetch', lambda sql, params=(): [{
        'template_id': 'demo_template',
    }])

    assert handler._resolve_user_modified_flag(1, official_code.strip()) == 0


def test_saving_builtin_template_with_code_change_is_user_modified(monkeypatch):
    import quantia.web.portfolioBacktestHandler as handler

    monkeypatch.setattr(handler, 'STRATEGY_TEMPLATES', [{
        'id': 'demo_template',
        'name': 'Demo',
        'code': 'def initialize(context):\n    pass\n',
    }])
    monkeypatch.setattr(handler.mdb, 'executeSqlFetch', lambda sql, params=(): [{
        'template_id': 'demo_template',
    }])

    assert handler._resolve_user_modified_flag(1, 'def initialize(context):\n    context.changed = True') == 1


def test_saving_builtin_template_with_self_heal_snippet_is_not_user_modified(monkeypatch):
    import quantia.web.portfolioBacktestHandler as handler

    official_code = 'def initialize(context):\n    pass\n'
    monkeypatch.setattr(handler, 'STRATEGY_TEMPLATES', [{
        'id': 'demo_template',
        'name': 'Demo',
        'code': official_code,
    }])
    monkeypatch.setattr(handler.mdb, 'executeSqlFetch', lambda sql, params=(): [{
        'template_id': 'demo_template',
    }])

    code_with_self_heal = official_code.strip() + handler._TEMPLATE_PARAM_SELF_HEAL_SNIPPET
    assert handler._resolve_user_modified_flag(1, code_with_self_heal) == 0


def test_boll_strategy_can_run_backtest_with_dynamic_selection(monkeypatch):
    from quantia.core.backtest import portfolio_engine
    from quantia.core.backtest.boll_lower_band_strategy import BOLL_LOWER_BAND_VALUE_STRATEGY_CODE

    stock_df = _make_boll_entry_df(base=20.0)
    benchmark_df = _make_benchmark_df(periods=len(stock_df), base=4000.0)
    _write_stock_cache('600519', stock_df)
    _write_index_cache('000300', benchmark_df)

    class FakeFundamentalProvider:
        def __init__(self, engine):
            self._engine = engine
            self._candidate_codes = ['600519']

        def get_fundamentals(self, q, date=None):
            return pd.DataFrame([{
                'code': '600519',
                'market_cap': 1800,
                'pe_ratio': 18,
                'pb_ratio': 1.4,
                'roe': 14,
                'inc_net_profit_year_on_year': 8,
                'gross_profit_margin': 42,
                'net_profit_margin': 18,
                'net_operate_cash_flow': 1000000000,
            }])

    monkeypatch.setattr(portfolio_engine, 'FundamentalDataProvider', FakeFundamentalProvider)

    result = portfolio_engine.run_backtest(
        BOLL_LOWER_BAND_VALUE_STRATEGY_CODE,
        '2024-02-01',
        '2025-03-01',
        initial_cash=5000000,
        benchmark='000300',
        slippage=0.0005,
    )

    assert result['status'] == 'completed'
    assert result.get('errors') in ([], None)
    assert any(trade['direction'] == 'buy' for trade in result['trades'])


def test_paper_api_attribute_history_loads_dynamic_candidate(monkeypatch):
    from quantia.core.backtest.strategy_context import Context, DataProxy, GlobalVars
    import quantia.paper_trading.paper_engine as paper_engine

    ctx = Context(100000)
    ctx.current_dt = pd.Timestamp('2024-04-30 15:00:00')
    data_proxy = DataProxy()
    g = GlobalVars()
    ctx._engine = type('E', (), {
        'g': g,
        'context': ctx,
        '_stock_data': {},
        '_pending_orders': [],
        '_trade_records': [],
        '_log_messages': [],
        '_custom_records': {},
    })()

    stock_df = _make_market_df(start='2024-01-02', periods=90, base=10.0)

    def fake_load_security_data(code, start_date, end_date):
        return code, stock_df.copy()

    monkeypatch.setattr(paper_engine, '_load_security_data', fake_load_security_data)

    api = paper_engine._create_api(ctx, data_proxy, g)
    hist = api['attribute_history']('600519', 20, '1d', ['close', 'volume'])

    assert len(hist) == 20
    assert '600519' in ctx._engine._stock_data
    assert 'close' in hist.columns
    expected_close = stock_df.loc[stock_df['date'] == pd.Timestamp('2024-04-30'), 'close'].iloc[0]
    assert data_proxy._current_bars['600519']['close'] == expected_close