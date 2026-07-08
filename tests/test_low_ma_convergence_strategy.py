#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from quantia.core.strategy import low_ma_convergence


def _make_data(close):
    close = np.array(close, dtype=float)
    dates = pd.bdate_range(end="2026-07-03", periods=len(close))
    p_change = np.zeros(len(close))
    p_change[1:] = (close[1:] - close[:-1]) / close[:-1] * 100
    return pd.DataFrame({
        "date": dates,
        "open": close,
        "high": close * 1.01,
        "low": close * 0.99,
        "close": close,
        "volume": 1_000_000,
        "p_change": p_change,
    })


def test_low_ma_convergence_accepts_low_converged_ma():
    early_drop = np.linspace(30, 10.2, 190)
    low_base = 10 + np.sin(np.linspace(0, 6, 70)) * 0.08
    data = _make_data(np.r_[early_drop, low_base])

    result = low_ma_convergence.check(("2026-07-03", "600000"), data)

    assert result
    assert result["low_position"] <= 25
    assert result["ma_convergence"] <= 5
    assert result["hit_count"] >= 1
    assert all(key in result for key in ("ma5", "ma10", "ma20", "ma30", "ma60"))


def test_low_ma_convergence_rejects_high_position():
    prices = np.linspace(10, 30, 260)
    data = _make_data(prices)

    result = low_ma_convergence.check(("2026-07-03", "600000"), data)

    assert result is False


def test_low_ma_convergence_rejects_diverged_ma():
    early_drop = np.linspace(30, 10.2, 220)
    rebound = np.linspace(10.1, 14, 40)
    data = _make_data(np.r_[early_drop, rebound])

    result = low_ma_convergence.check(
        ("2026-07-03", "600000"),
        data,
        low_position_pct=100,
        max_close_ma60_dev=100,
    )

    assert result is False


def test_low_ma_convergence_rejects_still_falling_ma_trend():
    prices = np.linspace(30, 10, 260)
    data = _make_data(prices)

    result = low_ma_convergence.check(
        ("2026-07-03", "002558"),
        data,
        low_position_pct=100,
        convergence_pct=20,
        max_close_ma60_dev=100,
    )

    assert result is False


def test_low_ma_convergence_can_disable_trend_filter_for_legacy_scan():
    prices = np.linspace(30, 10, 260)
    data = _make_data(prices)

    result = low_ma_convergence.check(
        ("2026-07-03", "002558"),
        data,
        low_position_pct=100,
        convergence_pct=20,
        max_close_ma60_dev=100,
        enable_trend_filter=0,
    )

    assert result
    assert result["ma60_slope"] < 0