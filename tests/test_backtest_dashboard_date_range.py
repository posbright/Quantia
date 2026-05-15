#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Backtest Dashboard date-range unit tests (pytest).

Purpose:
- Validate start_date/end_date parsing and precedence logic introduced in
    quantia.web.backtestDashboardHandler._resolve_date_range.

Notes:
- Tests are DB-free: we monkeypatch helper functions that would otherwise hit MySQL.
"""

import os
import sys


project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)


class FakeHandler:
    def __init__(self, args):
        self._args = dict(args or {})

    def get_argument(self, name, default='', strip=True):
        if name in self._args and self._args[name] is not None:
            val = self._args[name]
        else:
            val = default
        if strip and isinstance(val, str):
            return val.strip()
        return val


def test_explicit_start_date_autofill_end_date(monkeypatch):
    import quantia.web.backtestDashboardHandler as mod

    calls = []

    def fake_cnt(table, s, e):
        calls.append((table, s, e))
        return 7

    monkeypatch.setattr(mod, '_get_table_trade_date_count', fake_cnt)
    monkeypatch.setattr(mod, '_get_recent_date_range', lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('不应走 days 分支')))

    h = FakeHandler({'start_date': '2026-2-3'})
    dr, err = mod._resolve_date_range(h, 't', 60)
    assert err is None
    assert dr['start'] == '2026-02-03'
    assert dr['end'] == '2026-02-03'
    assert dr['count'] == 7
    assert calls == [('t', '2026-02-03', '2026-02-03')]


def test_explicit_end_date_autofill_start_date(monkeypatch):
    import quantia.web.backtestDashboardHandler as mod

    def fake_cnt(_table, s, e):
        assert s == e == '2026-02-03'
        return 1

    monkeypatch.setattr(mod, '_get_table_trade_date_count', fake_cnt)
    monkeypatch.setattr(mod, '_get_recent_date_range', lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('不应走 days 分支')))

    h = FakeHandler({'end_date': '20260203'})
    dr, err = mod._resolve_date_range(h, 't', 60)
    assert err is None
    assert dr['start'] == '2026-02-03'
    assert dr['end'] == '2026-02-03'
    assert dr['count'] == 1


def test_explicit_range_swap_when_start_gt_end(monkeypatch):
    import quantia.web.backtestDashboardHandler as mod

    def fake_cnt(_table, s, e):
        assert s == '2026-02-01'
        assert e == '2026-02-10'
        return 2

    monkeypatch.setattr(mod, '_get_table_trade_date_count', fake_cnt)
    monkeypatch.setattr(mod, '_get_recent_date_range', lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('不应走 days 分支')))

    h = FakeHandler({'start_date': '20260210', 'end_date': '2026-02-01', 'days': '10'})
    dr, err = mod._resolve_date_range(h, 't', 60)
    assert err is None
    assert dr['start'] == '2026-02-01'
    assert dr['end'] == '2026-02-10'
    assert dr['count'] == 2


def test_explicit_range_invalid_date_returns_error(monkeypatch):
    import quantia.web.backtestDashboardHandler as mod

    monkeypatch.setattr(mod, '_get_table_trade_date_count', lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('不应计算 count')))
    monkeypatch.setattr(mod, '_get_recent_date_range', lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('不应走 days 分支')))

    h = FakeHandler({'start_date': '2026-13-01', 'end_date': '2026-02-01'})
    dr, err = mod._resolve_date_range(h, 't', 60)
    assert dr is None
    assert err and '格式' in err


def test_explicit_range_too_large_returns_error(monkeypatch):
    import quantia.web.backtestDashboardHandler as mod

    monkeypatch.setattr(mod, '_get_table_trade_date_count', lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('不应计算 count')))
    monkeypatch.setattr(mod, '_get_recent_date_range', lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('不应走 days 分支')))

    h = FakeHandler({'start_date': '2024-01-01', 'end_date': '2026-02-01'})
    dr, err = mod._resolve_date_range(h, 't', 60)
    assert dr is None
    assert err and ('366' in err or '过大' in err)


def test_days_branch_used_when_no_explicit_range(monkeypatch):
    import quantia.web.backtestDashboardHandler as mod

    def fake_recent(table, days):
        assert table == 't'
        assert days == 10
        return {'start': '2026-02-01', 'end': '2026-02-27', 'count': 10}

    monkeypatch.setattr(mod, '_get_table_trade_date_count', lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('不应计算 count')))
    monkeypatch.setattr(mod, '_get_recent_date_range', fake_recent)

    h = FakeHandler({'days': '10'})
    dr, err = mod._resolve_date_range(h, 't', 60)
    assert err is None
    assert dr['start'] == '2026-02-01'
    assert dr['end'] == '2026-02-27'
    assert dr['count'] == 10
