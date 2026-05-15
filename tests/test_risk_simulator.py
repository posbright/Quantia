"""单股交易模拟器单元测试。"""
import numpy as np
import pandas as pd
import pytest

from quantia.core.composite.risk_simulator import (
    Trade, ROUND_TRIP_COST, simulate, summarize_trades,
)


def _make_df(closes, opens=None, highs=None, lows=None):
    n = len(closes)
    df = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=n),
        "open":  opens if opens is not None else closes,
        "high":  highs if highs is not None else [c * 1.01 for c in closes],
        "low":   lows  if lows  is not None else [c * 0.99 for c in closes],
        "close": closes,
    })
    return df


def test_no_signal_returns_empty():
    df = _make_df([10.0] * 10)
    sig = pd.Series([False] * 10)
    assert simulate("000001", df, sig) == []


def test_take_profit_exit():
    # 第 0 bar 信号 → 第 1 bar 进场 open=10
    # take_profit=0.10 → target=11；让第 3 bar 触及 11
    closes = [10, 10, 10.5, 11.5, 11.0]
    df = _make_df(closes, opens=closes)
    sig = pd.Series([True, False, False, False, False])
    trades = simulate("X", df, sig, stop_loss=0.10, take_profit=0.10, max_hold=10)
    assert len(trades) == 1
    t = trades[0]
    assert t.reason == "win-target"
    assert t.entry_price == 10.0
    assert t.exit_price == pytest.approx(11.0)


def test_stop_loss_exit():
    closes = [10, 10, 9.5, 8.5, 8.0]
    df = _make_df(closes, opens=closes,
                  highs=[c * 1.005 for c in closes],
                  lows=[c * 0.99 for c in closes])
    sig = pd.Series([True, False, False, False, False])
    trades = simulate("X", df, sig, stop_loss=0.10, take_profit=0.20, max_hold=10)
    assert len(trades) == 1
    assert trades[0].reason == "stop-loss"


def test_time_exit():
    closes = [10.0] * 10
    df = _make_df(closes, opens=closes)
    sig = pd.Series([True] + [False] * 9)
    trades = simulate("X", df, sig, stop_loss=0.05, take_profit=0.05, max_hold=3)
    assert len(trades) == 1
    assert trades[0].reason == "time-exit"
    assert trades[0].hold_days == 3


def test_t_plus_1_entry():
    closes = [10, 12, 12, 12]
    df = _make_df(closes, opens=closes)
    sig = pd.Series([True, False, False, False])
    trades = simulate("X", df, sig, stop_loss=0.5, take_profit=0.5, max_hold=10)
    # 进场是第 1 bar 的 open=12，不是第 0 bar 的 close=10
    assert trades[0].entry_price == 12.0


def test_fundamentals_check_triggers_exit():
    closes = [10, 10, 10, 10, 10]
    df = _make_df(closes, opens=closes)
    sig = pd.Series([True, False, False, False, False])
    # 第 3 bar (i=3) 基本面恶化
    def fcheck(code, date):
        return date == pd.Timestamp("2024-01-04")
    trades = simulate("X", df, sig, stop_loss=0.5, take_profit=0.5,
                      max_hold=10, fundamentals_check_fn=fcheck)
    assert len(trades) == 1
    assert trades[0].reason == "fundamentals-exit"


def test_summarize_empty():
    assert summarize_trades([], "test")["trades"] == 0


def test_summarize_basic_stats():
    trades = [
        Trade("X", 1, pd.Timestamp("2024-01-02"), 10.0,
              3, pd.Timestamp("2024-01-04"), 11.0, "win-target", 0.10, 0.097, 2),
        Trade("X", 5, pd.Timestamp("2024-01-06"), 10.0,
              7, pd.Timestamp("2024-01-08"), 9.5, "stop-loss", -0.05, -0.054, 2),
    ]
    s = summarize_trades(trades, "test")
    assert s["trades"] == 2
    assert s["win%"] == 50.0
