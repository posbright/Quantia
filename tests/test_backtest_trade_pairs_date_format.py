#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for TradePairHandler date normalization helpers (pytest).

Focus:
- Ensure date matching works between DB dates (YYYY-MM-DD) and cache dates (YYYYMMDD).

We test helper functions and the key index selection logic used in TradePairHandler.
"""

import os
import sys


project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)


def test_to_yyyymmdd_loose_supports_multiple_formats():
    import datetime
    import quantia.web.backtestDashboardHandler as mod

    assert mod._to_yyyymmdd_loose('2026-02-03') == '20260203'
    assert mod._to_yyyymmdd_loose('20260203') == '20260203'
    assert mod._to_yyyymmdd_loose('2026/2/3') == '20260203'
    assert mod._to_yyyymmdd_loose('2026.2.3') == '20260203'
    assert mod._to_yyyymmdd_loose(datetime.date(2026, 2, 3)) == '20260203'
    assert mod._to_yyyymmdd_loose('') == ''
    assert mod._to_yyyymmdd_loose('bad') == ''


def test_to_dash_ymd_loose_outputs_yyyy_mm_dd():
    import datetime
    import quantia.web.backtestDashboardHandler as mod

    assert mod._to_dash_ymd_loose('20260203') == '2026-02-03'
    assert mod._to_dash_ymd_loose('2026-2-3') == '2026-02-03'
    assert mod._to_dash_ymd_loose('2026/02/03') == '2026-02-03'
    assert mod._to_dash_ymd_loose(datetime.date(2026, 2, 3)) == '2026-02-03'


def test_cache_date_yyyymmdd_matches_db_date_yyyy_mm_dd():
    import pandas as pd
    import quantia.web.backtestDashboardHandler as mod

    hist = pd.DataFrame({
        'date': ['20260201', '20260203', '20260210'],
        'close': [10.0, 11.0, 12.0],
    })
    hist['date_key'] = hist['date'].apply(mod._to_yyyymmdd_loose)

    buy_date_db = '2026-02-03'
    buy_key = mod._to_yyyymmdd_loose(buy_date_db)
    idxs = hist.index[hist['date_key'] == buy_key].tolist()
    assert idxs == [1], f"应匹配到索引 1，实际 {idxs}"


def test_pick_first_sell_after_compares_by_date_key():
    import quantia.web.backtestDashboardHandler as mod

    buy_key = '20260203'
    sell_dates = ['2026-02-01', 'bad', '2026-02-04', '20260205', '2026/02/06']
    picked = mod._pick_first_sell_after(buy_key, sell_dates)
    assert picked == '2026-02-04'


def test_pick_first_sell_after_returns_empty_when_no_valid_sell():
    import quantia.web.backtestDashboardHandler as mod

    assert mod._pick_first_sell_after('', ['2026-02-10']) == ''
    assert mod._pick_first_sell_after('20260203', ['bad', None, '']) == ''
    assert mod._pick_first_sell_after('20260203', ['2026-02-01', '20260203']) == ''


def test_apply_max_hold_exit_rule_enforces_hard_cap():
    import quantia.web.backtestDashboardHandler as mod

    # sell within hold => signal
    exit_type, sell_idx = mod._apply_max_hold_exit_rule(buy_idx=10, sell_idx=12, max_hold=5, hist_len=100)
    assert exit_type == 'signal'
    assert sell_idx == 12

    # sell too late => timeout at buy+max_hold
    exit_type, sell_idx = mod._apply_max_hold_exit_rule(buy_idx=10, sell_idx=30, max_hold=5, hist_len=100)
    assert exit_type == 'timeout'
    assert sell_idx == 15

    # missing sell => timeout
    exit_type, sell_idx = mod._apply_max_hold_exit_rule(buy_idx=10, sell_idx=None, max_hold=5, hist_len=100)
    assert exit_type == 'timeout'
    assert sell_idx == 15

    # clamp to end of hist
    exit_type, sell_idx = mod._apply_max_hold_exit_rule(buy_idx=98, sell_idx=None, max_hold=10, hist_len=100)
    assert exit_type == 'timeout'
    assert sell_idx == 99
