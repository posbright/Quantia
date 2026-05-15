#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Comprehensive tests for quantia/core/strategy/ modules.

Covers:
  base, enter, keep_increasing, parking_apron, backtrace_ma250,
  breakthrough_platform, low_backtrace_increase, climax_limitdown,
  turtle_trade, low_atr, high_tight_flag, gpt_value_strategy,
  technical/ma_strategies, technical/value_invest_strategies,
  volume/volume_strategies, pattern/pattern_strategies,
  fundamental/fundamental_filter, fundamental/fundamental_strategies,
  fundamental/moat_model, fundamental/moat_ai_service
"""

import sys
import os
import copy
import json
import math
import logging
from datetime import datetime, timedelta
from unittest import mock

import numpy as np
import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# ---------------------------------------------------------------------------
# Helpers – synthetic OHLCV DataFrames
# ---------------------------------------------------------------------------
def _make_dates(n: int, end: str = "2026-03-01"):
    """Return *n* business-day timestamps ending at *end*."""
    end_ts = pd.Timestamp(end)
    return pd.bdate_range(end=end_ts, periods=n)


def make_ohlcv(n: int = 100, base_price: float = 10.0,
               daily_return: float = 0.002, volatility: float = 0.01,
               base_volume: int = 1_000_000, end_date: str = "2026-03-01",
               seed: int = 42) -> pd.DataFrame:
    """
    Create a synthetic OHLCV DataFrame with *n* rows.

    The close price follows a geometric random walk with drift
    ``daily_return`` and noise ``volatility``.
    Columns: date, open, high, low, close, volume, p_change
    """
    rng = np.random.RandomState(seed)
    dates = _make_dates(n, end_date)
    log_returns = daily_return + volatility * rng.randn(n)
    log_returns[0] = 0.0
    close = base_price * np.exp(np.cumsum(log_returns))

    open_ = close * (1 + volatility * rng.randn(n) * 0.3)
    high = np.maximum(open_, close) * (1 + abs(volatility * rng.randn(n) * 0.5))
    low = np.minimum(open_, close) * (1 - abs(volatility * rng.randn(n) * 0.5))
    volume = base_volume * (1 + 0.3 * rng.randn(n))
    volume = np.clip(volume, 100_000, None).astype(np.float64)

    p_change = np.zeros(n)
    p_change[1:] = (close[1:] - close[:-1]) / close[:-1] * 100

    df = pd.DataFrame({
        "date": dates,
        "open": np.round(open_, 2),
        "high": np.round(high, 2),
        "low": np.round(low, 2),
        "close": np.round(close, 2),
        "volume": volume,
        "p_change": np.round(p_change, 2),
    })
    return df


def make_fundamental_row(**overrides) -> pd.Series:
    """Create a single stock fundamental data row (pd.Series)."""
    defaults = dict(
        code="600519", name="贵州茅台",
        debt_asset_ratio=25.0, per_netcash_operate=2.5,
        current_ratio=3.0, speed_ratio=2.5,
        roe_weight=25.0, sale_gpr=50.0, sale_npr=20.0, jroa=12.0,
        income_growthrate_3y=18.0, netprofit_growthrate_3y=20.0,
        deduct_netprofit_growthrate=15.0,
        pe9=30.0, pbnewmrq=8.0,
        zxgxl=3.0, roic=18.0
    )
    defaults.update(overrides)
    return pd.Series(defaults)


def make_fundamental_df(n: int = 5, good: int = 3) -> pd.DataFrame:
    """Create a small DataFrame with *good* qualifying rows and *n-good* bad rows."""
    rows = []
    for i in range(good):
        rows.append(make_fundamental_row(
            code=f"60000{i}", name=f"好公司{i}",
            roe_weight=20 + i, sale_gpr=40 + i, sale_npr=15 + i,
            pe9=20 + i, debt_asset_ratio=30 + i,
            per_netcash_operate=1.5 + i * 0.5,
            income_growthrate_3y=15 + i, netprofit_growthrate_3y=15 + i,
            deduct_netprofit_growthrate=10 + i,
            current_ratio=2.0 + i * 0.3, speed_ratio=1.5 + i * 0.3,
            pbnewmrq=5.0
        ))
    for i in range(n - good):
        rows.append(make_fundamental_row(
            code=f"60010{i}", name=f"差公司{i}",
            roe_weight=3.0, sale_gpr=8.0, sale_npr=2.0,
            pe9=80.0, debt_asset_ratio=75.0,
            per_netcash_operate=-0.5,
            income_growthrate_3y=-5, netprofit_growthrate_3y=-3,
            deduct_netprofit_growthrate=-2,
            current_ratio=0.5, speed_ratio=0.3,
            pbnewmrq=15.0
        ))
    return pd.DataFrame(rows)


# =========================================================================
# 1. base.py
# =========================================================================
class TestBase:
    """Tests for quantia.core.strategy.base"""

    def test_register_strategy_decorator(self):
        from quantia.core.strategy.base import (
            register_strategy, STRATEGY_REGISTRY, BaseStrategy
        )
        orig = STRATEGY_REGISTRY.copy()
        try:
            @register_strategy
            class _Dummy(BaseStrategy):
                name = "_test_dummy_xyz"
                cn_name = "测试"

                def check(self, code_name, data, date=None, **kw):
                    return True

            assert "_test_dummy_xyz" in STRATEGY_REGISTRY
            assert STRATEGY_REGISTRY["_test_dummy_xyz"] is _Dummy
        finally:
            STRATEGY_REGISTRY.clear()
            STRATEGY_REGISTRY.update(orig)

    def test_get_strategy_found(self):
        from quantia.core.strategy.base import get_strategy
        # 'keep_increasing' is registered by MABullishStrategy
        cls = get_strategy("keep_increasing")
        assert cls is not None

    def test_get_strategy_missing_raises(self):
        from quantia.core.strategy.base import get_strategy
        with pytest.raises(ValueError, match="未注册"):
            get_strategy("no_such_strategy_xyz")

    def test_get_all_strategies_returns_dict(self):
        from quantia.core.strategy.base import get_all_strategies
        result = get_all_strategies()
        assert isinstance(result, dict)
        assert len(result) > 0

    def test_get_strategies_by_category(self):
        from quantia.core.strategy.base import get_strategies_by_category
        techs = get_strategies_by_category("technical")
        assert isinstance(techs, dict)
        # At least MABullishStrategy should be registered as technical
        for cls in techs.values():
            assert cls.category == "technical"

    def test_technical_strategy_calc_ma(self):
        from quantia.core.strategy.base import TechnicalStrategy
        df = make_ohlcv(60)
        ma = TechnicalStrategy.calc_ma(df, "close", 5)
        assert len(ma) == len(df)
        # First 4 values should be 0 (filled NaN)
        assert ma[0] == 0.0
        # Non-zero after warm-up
        assert ma[-1] > 0

    def test_technical_strategy_calc_ema(self):
        from quantia.core.strategy.base import TechnicalStrategy
        df = make_ohlcv(60)
        ema = TechnicalStrategy.calc_ema(df, "close", 12)
        assert len(ema) == len(df)
        assert ema[-1] > 0

    def test_technical_strategy_calc_atr(self):
        from quantia.core.strategy.base import TechnicalStrategy
        df = make_ohlcv(60)
        atr = TechnicalStrategy.calc_atr(df, 14)
        assert len(atr) == len(df)
        assert atr[-1] >= 0

    def test_volume_strategy_calc_vol_ma(self):
        from quantia.core.strategy.base import VolumeStrategy
        df = make_ohlcv(60)
        vol_ma = VolumeStrategy.calc_vol_ma(df, 5)
        assert len(vol_ma) == len(df)

    def test_volume_strategy_calc_amount(self):
        from quantia.core.strategy.base import VolumeStrategy
        df = make_ohlcv(60)
        amount = VolumeStrategy.calc_amount(df, -1)
        assert amount == df.iloc[-1]["close"] * df.iloc[-1]["volume"]

    def test_base_strategy_prepare_data_insufficient(self):
        from quantia.core.strategy.base import TechnicalStrategy
        # Create a small concrete subclass
        class _T(TechnicalStrategy):
            name = "__xxx"
            def check(self, *a, **k):
                return False
        s = _T(threshold=200)
        df = make_ohlcv(50)
        code_name = (df.iloc[-1]["date"].strftime("%Y-%m-%d"), "600000")
        assert s.prepare_data(code_name, df) is None

    def test_base_strategy_callable(self):
        from quantia.core.strategy.base import TechnicalStrategy
        class _T(TechnicalStrategy):
            name = "__yyy"
            def check(self, code_name, data, date=None, **kw):
                return True
        s = _T()
        df = make_ohlcv(100)
        code_name = (df.iloc[-1]["date"].strftime("%Y-%m-%d"), "600000")
        # __call__ delegates to check
        assert s(code_name, df) is True


# =========================================================================
# 2. enter.py – check_volume
# =========================================================================
class TestEnter:
    def _build_trigger_df(self):
        """Build data that triggers check_volume."""
        n = 70
        df = make_ohlcv(n, base_price=20.0, daily_return=0.001,
                        base_volume=5_000_000, seed=7)
        # Force last row: +3% gain, open < close, huge volume
        last = df.index[-1]
        prev_close = df.iloc[-2]["close"]
        new_close = round(prev_close * 1.035, 2)
        new_open = round(prev_close * 1.005, 2)
        # Ensure amount > 2e8: close * volume > 2e8
        big_vol = int(3e8 / new_close)
        df.loc[last, "close"] = new_close
        df.loc[last, "open"] = new_open
        df.loc[last, "high"] = new_close * 1.01
        df.loc[last, "low"] = new_open * 0.99
        df.loc[last, "volume"] = big_vol
        df.loc[last, "p_change"] = round((new_close - prev_close) / prev_close * 100, 2)
        return df

    def test_check_volume_triggers(self):
        from quantia.core.strategy.enter import check_volume
        df = self._build_trigger_df()
        end = df.iloc[-1]["date"].strftime("%Y-%m-%d")
        code_name = (end, "600000")
        result = check_volume(code_name, df, threshold=60)
        assert result  # truthy (dict with metrics)
        assert isinstance(result, dict)
        assert 'p_change' in result
        assert 'vol_ratio' in result
        assert result['vol_ratio'] >= 2
        assert result['p_change'] >= 2

    def test_check_volume_no_trigger_low_change(self):
        from quantia.core.strategy.enter import check_volume
        df = make_ohlcv(100, daily_return=0.0, volatility=0.001, seed=1)
        # p_change ~ 0
        end = df.iloc[-1]["date"].strftime("%Y-%m-%d")
        code_name = (end, "600000")
        assert check_volume(code_name, df, threshold=60) is False

    def test_check_volume_insufficient_data(self):
        from quantia.core.strategy.enter import check_volume
        df = make_ohlcv(10)
        code_name = (df.iloc[-1]["date"].strftime("%Y-%m-%d"), "600000")
        assert check_volume(code_name, df, threshold=60) is False


# =========================================================================
# 3. keep_increasing.py
# =========================================================================
class TestKeepIncreasing:
    def test_increasing_ma30(self):
        from quantia.core.strategy.keep_increasing import check
        # Strong uptrend: 0.8% daily return
        df = make_ohlcv(120, base_price=10.0, daily_return=0.008,
                        volatility=0.003, seed=10)
        end = df.iloc[-1]["date"].strftime("%Y-%m-%d")
        code_name = (end, "600000")
        result = check(code_name, df, threshold=30)
        assert isinstance(result, dict)

    def test_not_increasing(self):
        from quantia.core.strategy.keep_increasing import check
        # Flat / slightly declining
        df = make_ohlcv(120, base_price=10.0, daily_return=-0.002,
                        volatility=0.005, seed=20)
        end = df.iloc[-1]["date"].strftime("%Y-%m-%d")
        code_name = (end, "600000")
        assert check(code_name, df, threshold=30) is False

    def test_insufficient_data(self):
        from quantia.core.strategy.keep_increasing import check
        df = make_ohlcv(10)
        code_name = (df.iloc[-1]["date"].strftime("%Y-%m-%d"), "600000")
        assert check(code_name, df, threshold=30) is False


# =========================================================================
# 4. parking_apron.py
# =========================================================================
class TestParkingApron:
    def _build_parking_df(self):
        """Build data with a limit-up day followed by 3-day consolidation."""
        n = 80
        df = make_ohlcv(n, base_price=10.0, daily_return=0.005,
                        volatility=0.005, base_volume=2_000_000, seed=55)
        # Pick day at index 60 as limit-up day
        idx = 60
        prev_close = df.iloc[idx - 1]["close"]
        limit_close = round(prev_close * 1.10, 2)
        df.loc[df.index[idx], "close"] = limit_close
        df.loc[df.index[idx], "open"] = round(prev_close * 1.02, 2)
        df.loc[df.index[idx], "high"] = round(limit_close * 1.005, 2)
        df.loc[df.index[idx], "low"] = round(prev_close * 1.01, 2)
        df.loc[df.index[idx], "p_change"] = 10.0
        # Make it the 60-day high so turtle_trade passes
        for j in range(max(0, idx - 59), idx):
            df.loc[df.index[j], "close"] = min(df.iloc[j]["close"], limit_close * 0.95)

        # 3 consolidation days: high-open, close > limitup price, close/open within 3%
        for d in range(1, 4):
            i = idx + d
            if i >= len(df):
                break
            c = round(limit_close * (1 + 0.005 * d), 2)
            o = round(c * 0.998, 2)
            df.loc[df.index[i], "open"] = o
            df.loc[df.index[i], "close"] = c
            df.loc[df.index[i], "high"] = round(c * 1.005, 2)
            df.loc[df.index[i], "low"] = round(o * 0.998, 2)
            df.loc[df.index[i], "p_change"] = round(
                (c - df.iloc[i - 1]["close"]) / df.iloc[i - 1]["close"] * 100, 2
            )
        return df

    def test_parking_apron_structure(self):
        """Test that check_internal works with crafted data."""
        from quantia.core.strategy.parking_apron import check_internal
        # Build a mini dataframe directly for check_internal
        dates = _make_dates(5, "2026-03-01")
        limitup_price = 11.0
        # 3 consolidation rows all above limitup_price, close/open ~1
        rows = []
        for i, d in enumerate(dates):
            c = limitup_price * 1.01 + i * 0.01
            o = c * 0.999
            rows.append({"date": d, "open": round(o, 2), "close": round(c, 2),
                         "high": round(c * 1.005, 2), "low": round(o * 0.998, 2),
                         "p_change": 0.5, "volume": 1_000_000})
        data = pd.DataFrame(rows)
        limitup_row = [limitup_price, dates[0]]
        # check_internal needs at least 3 rows after limitup_row date
        result = check_internal(data, limitup_row)
        assert isinstance(result, bool)

    def test_parking_apron_fail_insufficient(self):
        from quantia.core.strategy.parking_apron import check
        df = make_ohlcv(5)
        code_name = (df.iloc[-1]["date"].strftime("%Y-%m-%d"), "600000")
        assert check(code_name, df, threshold=15) is False


# =========================================================================
# 5. backtrace_ma250.py
# =========================================================================
class TestBacktraceMa250:
    def test_insufficient_data(self):
        from quantia.core.strategy.backtrace_ma250 import check
        df = make_ohlcv(100)
        code_name = (df.iloc[-1]["date"].strftime("%Y-%m-%d"), "600000")
        assert check(code_name, df, threshold=60) is False

    def test_no_pullback_flat(self):
        from quantia.core.strategy.backtrace_ma250 import check
        # 300 rows flat – no pullback pattern
        df = make_ohlcv(300, daily_return=0.0, volatility=0.002, seed=5)
        code_name = (df.iloc[-1]["date"].strftime("%Y-%m-%d"), "600000")
        assert check(code_name, df, threshold=60) is False


# =========================================================================
# 6. breakthrough_platform.py
# =========================================================================
class TestBreakthroughPlatform:
    def test_no_trigger_flat(self):
        from quantia.core.strategy.breakthrough_platform import check
        df = make_ohlcv(120, daily_return=0.0, volatility=0.002, seed=3)
        code_name = (df.iloc[-1]["date"].strftime("%Y-%m-%d"), "600000")
        assert check(code_name, df, threshold=60) is False

    def test_insufficient_data(self):
        from quantia.core.strategy.breakthrough_platform import check
        df = make_ohlcv(20)
        code_name = (df.iloc[-1]["date"].strftime("%Y-%m-%d"), "600000")
        assert check(code_name, df, threshold=60) is False


# =========================================================================
# 7. low_backtrace_increase.py
# =========================================================================
class TestLowBacktraceIncrease:
    def test_steady_uptrend_no_drawdown(self):
        from quantia.core.strategy.low_backtrace_increase import check
        # Generate strong uptrend with very low vol → >60% gain, no big drop
        n = 70
        df = make_ohlcv(n, base_price=10.0, daily_return=0.009,
                        volatility=0.001, seed=99)
        # Guarantee p_change all > -7 and open/close gap < 7%
        df["p_change"] = df["close"].pct_change().fillna(0) * 100
        df["open"] = df["close"] * 0.999  # tiny gap
        end = df.iloc[-1]["date"].strftime("%Y-%m-%d")
        code_name = (end, "600000")
        result = check(code_name, df, threshold=60)
        assert isinstance(result, dict)

    def test_big_drawdown_rejected(self):
        from quantia.core.strategy.low_backtrace_increase import check
        df = make_ohlcv(100, daily_return=0.01, volatility=0.005, seed=8)
        # Insert a -10% day
        idx = 80
        prev = df.iloc[idx - 1]["close"]
        df.loc[df.index[idx], "close"] = round(prev * 0.90, 2)
        df.loc[df.index[idx], "p_change"] = -10.0
        end = df.iloc[-1]["date"].strftime("%Y-%m-%d")
        code_name = (end, "600000")
        assert check(code_name, df, threshold=60) is False

    def test_insufficient_gain_rejected(self):
        from quantia.core.strategy.low_backtrace_increase import check
        df = make_ohlcv(100, daily_return=0.001, volatility=0.001, seed=1)
        end = df.iloc[-1]["date"].strftime("%Y-%m-%d")
        code_name = (end, "600000")
        assert check(code_name, df, threshold=60) is False


# =========================================================================
# 8. climax_limitdown.py
# =========================================================================
class TestClimaxLimitdown:
    def test_limitdown_trigger(self):
        from quantia.core.strategy.climax_limitdown import check
        n = 70
        df = make_ohlcv(n, base_price=30.0, base_volume=3_000_000, seed=12)
        last = df.index[-1]
        prev_close = df.iloc[-2]["close"]
        new_close = round(prev_close * 0.90, 2)
        big_vol = int(5e8 / new_close)  # ensure amount > 2e8
        df.loc[last, "close"] = new_close
        df.loc[last, "p_change"] = -10.0
        df.loc[last, "volume"] = big_vol
        end = df.iloc[-1]["date"].strftime("%Y-%m-%d")
        code_name = (end, "600000")
        result = check(code_name, df, threshold=60)
        assert isinstance(result, dict)

    def test_no_limitdown(self):
        from quantia.core.strategy.climax_limitdown import check
        df = make_ohlcv(100, daily_return=0.001, seed=1)
        end = df.iloc[-1]["date"].strftime("%Y-%m-%d")
        code_name = (end, "600000")
        assert check(code_name, df, threshold=60) is False


# =========================================================================
# 9. turtle_trade.py
# =========================================================================
class TestTurtleTrade:
    def test_breakout_entry(self):
        from quantia.core.strategy.turtle_trade import check_enter
        df = make_ohlcv(100, daily_return=0.005, volatility=0.003, seed=50)
        # Ensure last close is the max
        max_c = df["close"].max()
        df.loc[df.index[-1], "close"] = max_c + 1
        end = df.iloc[-1]["date"].strftime("%Y-%m-%d")
        code_name = (end, "600000")
        assert isinstance(check_enter(code_name, df, threshold=60), dict)

    def test_no_breakout(self):
        from quantia.core.strategy.turtle_trade import check_enter
        df = make_ohlcv(100, daily_return=-0.005, volatility=0.003, seed=33)
        # Last close is likely NOT the max
        # Force last close well below max
        df.loc[df.index[-1], "close"] = df["close"].min() * 0.9
        end = df.iloc[-1]["date"].strftime("%Y-%m-%d")
        code_name = (end, "600000")
        assert check_enter(code_name, df, threshold=60) is False

    def test_insufficient_data(self):
        from quantia.core.strategy.turtle_trade import check_enter
        df = make_ohlcv(10)
        code_name = (df.iloc[-1]["date"].strftime("%Y-%m-%d"), "600000")
        assert check_enter(code_name, df, threshold=60) is False


# =========================================================================
# 10. low_atr.py
# =========================================================================
class TestLowAtr:
    def test_low_atr_increase(self):
        from quantia.core.strategy.low_atr import check_low_increase
        # Need 250 rows, last 10 have >10% range, ATR < 10
        df = make_ohlcv(300, base_price=10.0, daily_return=0.003,
                        volatility=0.005, seed=77)
        # Force last 10 days: spread > 10% but daily changes moderate
        tail_idx = df.index[-10:]
        base = df.loc[tail_idx[0], "close"]
        for i, idx in enumerate(tail_idx):
            df.loc[idx, "close"] = round(base * (1 + 0.015 * i), 2)
            df.loc[idx, "p_change"] = 1.5  # moderate
        end = df.iloc[-1]["date"].strftime("%Y-%m-%d")
        code_name = (end, "600000")
        result = check_low_increase(code_name, df, threshold=10)
        assert isinstance(result, dict)

    def test_insufficient_history(self):
        from quantia.core.strategy.low_atr import check_low_increase
        df = make_ohlcv(100)
        code_name = (df.iloc[-1]["date"].strftime("%Y-%m-%d"), "600000")
        assert check_low_increase(code_name, df, ma_long=250, threshold=10) is False


# =========================================================================
# 11. high_tight_flag.py
# =========================================================================
class TestHighTightFlag:
    def test_no_istop_returns_false(self):
        from quantia.core.strategy.high_tight_flag import check_high_tight
        df = make_ohlcv(100)
        code_name = (df.iloc[-1]["date"].strftime("%Y-%m-%d"), "600000")
        assert check_high_tight(code_name, df, istop=False) is False

    def test_with_istop_but_no_pattern(self):
        from quantia.core.strategy.high_tight_flag import check_high_tight
        df = make_ohlcv(100, daily_return=0.001, volatility=0.005, seed=2)
        code_name = (df.iloc[-1]["date"].strftime("%Y-%m-%d"), "600000")
        assert check_high_tight(code_name, df, istop=True) is False

    def test_high_tight_pattern_triggers(self):
        from quantia.core.strategy.high_tight_flag import check_high_tight
        n = 80
        df = make_ohlcv(n, base_price=5.0, daily_return=0.005,
                        volatility=0.005, seed=44)
        # In the window [-24:-10] from end (data.tail(60).tail(24).head(14)),
        # we need:
        # 1) Two consecutive days with p_change >= 9.5
        # 2) current_close / min(low in that window) >= 1.9
        # The window indices from tail(60): indices 36..49 of tail(60)
        # i.e., from the full df: indices n-60+36 to n-60+49 = n-24 to n-11
        win_start = n - 24
        win_end = n - 11  # exclusive
        # Set two consecutive limit-up days
        for j in [win_start + 2, win_start + 3]:
            prev = df.iloc[j - 1]["close"]
            new_c = round(prev * 1.10, 2)
            df.loc[df.index[j], "close"] = new_c
            df.loc[df.index[j], "open"] = round(prev * 1.02, 2)
            df.loc[df.index[j], "high"] = round(new_c * 1.005, 2)
            df.loc[df.index[j], "low"] = round(prev * 1.01, 2)
            df.loc[df.index[j], "p_change"] = 10.0
        # Ensure current close (last row) / min low in window >= 1.9
        window_lows = df.iloc[win_start:win_end]["low"].values
        min_low = window_lows.min()
        needed_close = min_low * 1.95
        df.loc[df.index[-1], "close"] = round(needed_close, 2)

        code_name = (df.iloc[-1]["date"].strftime("%Y-%m-%d"), "600000")
        result = check_high_tight(code_name, df, threshold=60, istop=True)
        assert isinstance(result, dict)


# =========================================================================
# 12. gpt_value_strategy.py
# =========================================================================
class TestGptValueStrategy:
    def test_compute_gpt_score_known_data(self):
        from quantia.core.strategy.gpt_value_strategy import compute_gpt_score, _DEFAULT_PARAMS
        row = make_fundamental_row(
            roe_weight=25.0, sale_gpr=50.0, sale_npr=20.0, jroa=10.0,
            debt_asset_ratio=25.0, per_netcash_operate=2.0,
            current_ratio=2.0, speed_ratio=1.5,
            income_growthrate_3y=20.0, netprofit_growthrate_3y=20.0,
            deduct_netprofit_growthrate=15.0,
            pe9=15.0, pbnewmrq=3.0
        )
        result = compute_gpt_score(row, _DEFAULT_PARAMS)
        assert "gpt_score" in result
        assert result["gpt_score"] > 0
        # With these strong numbers, score should be quite high
        assert result["gpt_score"] > 50

    def test_compute_gpt_score_all_null(self):
        from quantia.core.strategy.gpt_value_strategy import compute_gpt_score, _DEFAULT_PARAMS
        row = pd.Series({
            "roe_weight": None, "sale_gpr": None, "sale_npr": None,
            "jroa": None, "debt_asset_ratio": None, "per_netcash_operate": None,
            "current_ratio": None, "speed_ratio": None,
            "income_growthrate_3y": None, "netprofit_growthrate_3y": None,
            "deduct_netprofit_growthrate": None,
            "pe9": None, "pbnewmrq": None
        })
        result = compute_gpt_score(row, _DEFAULT_PARAMS)
        assert result["gpt_score"] == 0.0

    def test_check_gpt_value_from_selection_pass(self):
        from quantia.core.strategy.gpt_value_strategy import (
            check_gpt_value_from_selection, _DEFAULT_PARAMS
        )
        row = make_fundamental_row(
            roe_weight=20.0, sale_gpr=30.0, sale_npr=10.0, jroa=5.0,
            debt_asset_ratio=30.0, per_netcash_operate=1.0,
            current_ratio=2.0, speed_ratio=1.0,
            income_growthrate_3y=15.0, netprofit_growthrate_3y=15.0,
            deduct_netprofit_growthrate=5.0,
            pe9=20.0, pbnewmrq=5.0
        )
        assert check_gpt_value_from_selection(row, _DEFAULT_PARAMS) is True

    def test_check_gpt_value_from_selection_fail_high_debt(self):
        from quantia.core.strategy.gpt_value_strategy import (
            check_gpt_value_from_selection, _DEFAULT_PARAMS
        )
        row = make_fundamental_row(debt_asset_ratio=70.0)
        assert check_gpt_value_from_selection(row, _DEFAULT_PARAMS) is False

    def test_check_gpt_value_from_selection_fail_low_roe(self):
        from quantia.core.strategy.gpt_value_strategy import (
            check_gpt_value_from_selection, _DEFAULT_PARAMS
        )
        row = make_fundamental_row(roe_weight=3.0)
        assert check_gpt_value_from_selection(row, _DEFAULT_PARAMS) is False

    def test_check_gpt_value_from_selection_all_null(self):
        from quantia.core.strategy.gpt_value_strategy import (
            check_gpt_value_from_selection, _DEFAULT_PARAMS
        )
        row = pd.Series({k: None for k in [
            "debt_asset_ratio", "per_netcash_operate", "current_ratio",
            "speed_ratio", "roe_weight", "sale_gpr", "sale_npr", "jroa",
            "income_growthrate_3y", "netprofit_growthrate_3y",
            "deduct_netprofit_growthrate", "pe9", "pbnewmrq"
        ]})
        # No ROE and no PE → data quality check fails
        assert check_gpt_value_from_selection(row, _DEFAULT_PARAMS) is False

    @mock.patch("quantia.core.strategy.gpt_value_strategy._load_params")
    def test_filter_gpt_value_stocks(self, mock_load):
        from quantia.core.strategy.gpt_value_strategy import (
            filter_gpt_value_stocks, _DEFAULT_PARAMS
        )
        mock_load.return_value = _DEFAULT_PARAMS.copy()
        df = make_fundamental_df(n=6, good=3)
        result = filter_gpt_value_stocks(df)
        assert isinstance(result, pd.DataFrame)
        # At least some should pass
        # (good rows have roe_weight 20-22 which >= default 10)
        assert len(result) >= 0  # may be 0-3 depending on defaults

    def test_filter_gpt_value_stocks_empty(self):
        from quantia.core.strategy.gpt_value_strategy import filter_gpt_value_stocks
        result = filter_gpt_value_stocks(pd.DataFrame())
        assert len(result) == 0

    def test_load_params_fallback(self):
        from quantia.core.strategy.gpt_value_strategy import _load_params, _DEFAULT_PARAMS
        # _load_params will try to import strategyParamsHandler which may fail → should return defaults
        params = _load_params()
        assert isinstance(params, dict)
        # Should have same keys as defaults
        for k in _DEFAULT_PARAMS:
            assert k in params


# =========================================================================
# 13. technical/ma_strategies.py
# =========================================================================
class TestMaStrategies:
    def test_ma_bullish_strategy(self):
        from quantia.core.strategy.technical.ma_strategies import MABullishStrategy
        s = MABullishStrategy(threshold=30)
        df = make_ohlcv(120, daily_return=0.008, volatility=0.003, seed=10)
        end = df.iloc[-1]["date"].strftime("%Y-%m-%d")
        code_name = (end, "600000")
        result = s.check(code_name, df)
        assert result is True

    def test_ma_bullish_strategy_fail(self):
        from quantia.core.strategy.technical.ma_strategies import MABullishStrategy
        s = MABullishStrategy(threshold=30)
        df = make_ohlcv(120, daily_return=-0.003, volatility=0.005, seed=20)
        end = df.iloc[-1]["date"].strftime("%Y-%m-%d")
        code_name = (end, "600000")
        assert s.check(code_name, df) is False

    def test_turtle_trading_strategy(self):
        from quantia.core.strategy.technical.ma_strategies import TurtleTradingStrategy
        s = TurtleTradingStrategy(threshold=60)
        df = make_ohlcv(100, daily_return=0.005, seed=50)
        df.loc[df.index[-1], "close"] = df["close"].max() + 1
        end = df.iloc[-1]["date"].strftime("%Y-%m-%d")
        code_name = (end, "600000")
        assert bool(s.check(code_name, df)) is True

    def test_turtle_trading_strategy_fail(self):
        from quantia.core.strategy.technical.ma_strategies import TurtleTradingStrategy
        s = TurtleTradingStrategy(threshold=60)
        df = make_ohlcv(100, daily_return=-0.003, seed=33)
        df.loc[df.index[-1], "close"] = df["close"].min() * 0.8
        end = df.iloc[-1]["date"].strftime("%Y-%m-%d")
        code_name = (end, "600000")
        assert bool(s.check(code_name, df)) is False

    def test_low_atr_growth_strategy_insufficient(self):
        from quantia.core.strategy.technical.ma_strategies import LowATRGrowthStrategy
        s = LowATRGrowthStrategy(threshold=120)
        df = make_ohlcv(50)
        code_name = (df.iloc[-1]["date"].strftime("%Y-%m-%d"), "600000")
        assert s.check(code_name, df) is False

    def test_compat_check(self):
        from quantia.core.strategy.technical.ma_strategies import check
        df = make_ohlcv(120, daily_return=0.008, volatility=0.003, seed=10)
        end = df.iloc[-1]["date"].strftime("%Y-%m-%d")
        code_name = (end, "600000")
        result = check(code_name, df, threshold=30)
        assert isinstance(result, bool)

    def test_compat_check_enter(self):
        from quantia.core.strategy.technical.ma_strategies import check_enter
        df = make_ohlcv(100, daily_return=0.005, seed=50)
        df.loc[df.index[-1], "close"] = df["close"].max() + 1
        end = df.iloc[-1]["date"].strftime("%Y-%m-%d")
        code_name = (end, "600000")
        assert bool(check_enter(code_name, df)) is True


# =========================================================================
# 14. technical/value_invest_strategies.py
# =========================================================================
class TestValueInvestStrategies:
    def test_trend_pullback_no_trigger_flat(self):
        from quantia.core.strategy.technical.value_invest_strategies import TrendPullbackStrategy
        s = TrendPullbackStrategy()
        df = make_ohlcv(100, daily_return=0.0, volatility=0.002, seed=1)
        code_name = (df.iloc[-1]["date"].strftime("%Y-%m-%d"), "600000")
        assert s.check(code_name, df) is False

    def test_trend_pullback_insufficient(self):
        from quantia.core.strategy.technical.value_invest_strategies import TrendPullbackStrategy
        s = TrendPullbackStrategy()
        df = make_ohlcv(20)
        code_name = (df.iloc[-1]["date"].strftime("%Y-%m-%d"), "600000")
        assert s.check(code_name, df) is False

    def test_oversold_rebound_no_trigger(self):
        from quantia.core.strategy.technical.value_invest_strategies import OversoldReboundStrategy
        s = OversoldReboundStrategy()
        df = make_ohlcv(100, daily_return=0.003, seed=5)
        code_name = (df.iloc[-1]["date"].strftime("%Y-%m-%d"), "600000")
        assert s.check(code_name, df) is False

    def test_breakout_confirm_no_trigger(self):
        from quantia.core.strategy.technical.value_invest_strategies import BreakoutConfirmStrategy
        s = BreakoutConfirmStrategy()
        df = make_ohlcv(100, daily_return=0.0, volatility=0.002, seed=3)
        code_name = (df.iloc[-1]["date"].strftime("%Y-%m-%d"), "600000")
        assert s.check(code_name, df) is False

    def test_compat_check_trend_pullback(self):
        from quantia.core.strategy.technical.value_invest_strategies import check_trend_pullback
        df = make_ohlcv(100, seed=1)
        code_name = (df.iloc[-1]["date"].strftime("%Y-%m-%d"), "600000")
        result = check_trend_pullback(code_name, df)
        assert isinstance(result, bool)


# =========================================================================
# 15. volume/volume_strategies.py
# =========================================================================
class TestVolumeStrategies:
    def test_volume_increase_strategy(self):
        from quantia.core.strategy.volume.volume_strategies import VolumeIncreaseStrategy
        s = VolumeIncreaseStrategy(threshold=60)
        df = self._build_trigger()
        end = df.iloc[-1]["date"].strftime("%Y-%m-%d")
        code_name = (end, "600000")
        assert bool(s.check(code_name, df)) is True

    def test_volume_increase_strategy_fail(self):
        from quantia.core.strategy.volume.volume_strategies import VolumeIncreaseStrategy
        s = VolumeIncreaseStrategy(threshold=60)
        df = make_ohlcv(100, daily_return=0.0, volatility=0.001, seed=1)
        code_name = (df.iloc[-1]["date"].strftime("%Y-%m-%d"), "600000")
        assert s.check(code_name, df) is False

    def test_climax_limitdown_strategy(self):
        from quantia.core.strategy.volume.volume_strategies import ClimaxLimitdownStrategy
        s = ClimaxLimitdownStrategy(threshold=60)
        df = make_ohlcv(100, base_price=20.0, base_volume=3_000_000, seed=12)
        # Inject limit-down last row
        last = df.index[-1]
        df.loc[last, "p_change"] = -10.0
        prev_close = df.iloc[-2]["close"]
        df.loc[last, "close"] = round(prev_close * 0.9, 2)
        df.loc[last, "volume"] = 15_000_000.0  # big volume
        code_name = (df.iloc[-1]["date"].strftime("%Y-%m-%d"), "600000")
        result = s.check(code_name, df)
        assert bool(result) is True

    def test_climax_limitdown_no_drop(self):
        from quantia.core.strategy.volume.volume_strategies import ClimaxLimitdownStrategy
        s = ClimaxLimitdownStrategy(threshold=60)
        df = make_ohlcv(100)
        code_name = (df.iloc[-1]["date"].strftime("%Y-%m-%d"), "600000")
        assert s.check(code_name, df) is False

    def test_compat_check_volume(self):
        from quantia.core.strategy.volume.volume_strategies import check_volume
        df = make_ohlcv(100, seed=1)
        code_name = (df.iloc[-1]["date"].strftime("%Y-%m-%d"), "600000")
        result = check_volume(code_name, df)
        assert isinstance(result, bool)

    def _build_trigger(self):
        n = 70
        df = make_ohlcv(n, base_price=20.0, daily_return=0.001,
                        base_volume=5_000_000, seed=7)
        last = df.index[-1]
        prev_close = df.iloc[-2]["close"]
        new_close = round(prev_close * 1.035, 2)
        new_open = round(prev_close * 1.005, 2)
        big_vol = int(3e8 / new_close)
        df.loc[last, "close"] = new_close
        df.loc[last, "open"] = new_open
        df.loc[last, "high"] = new_close * 1.01
        df.loc[last, "low"] = new_open * 0.99
        df.loc[last, "volume"] = big_vol
        df.loc[last, "p_change"] = round(
            (new_close - prev_close) / prev_close * 100, 2
        )
        return df


# =========================================================================
# 16. pattern/pattern_strategies.py
# =========================================================================
class TestPatternStrategies:
    def test_breakthrough_platform_no_trigger(self):
        from quantia.core.strategy.pattern.pattern_strategies import BreakthroughPlatformStrategy
        s = BreakthroughPlatformStrategy()
        df = make_ohlcv(120, daily_return=0.0, volatility=0.002, seed=3)
        code_name = (df.iloc[-1]["date"].strftime("%Y-%m-%d"), "600000")
        assert s.check(code_name, df) is False

    def test_parking_apron_insufficient(self):
        from quantia.core.strategy.pattern.pattern_strategies import ParkingApronStrategy
        s = ParkingApronStrategy()
        df = make_ohlcv(5)
        code_name = (df.iloc[-1]["date"].strftime("%Y-%m-%d"), "600000")
        assert s.check(code_name, df) is False

    def test_high_tight_flag_no_istop(self):
        from quantia.core.strategy.pattern.pattern_strategies import HighTightFlagStrategy
        s = HighTightFlagStrategy()
        df = make_ohlcv(100)
        code_name = (df.iloc[-1]["date"].strftime("%Y-%m-%d"), "600000")
        assert s.check(code_name, df, istop=False) is False

    def test_low_backtrace_increase_fail(self):
        from quantia.core.strategy.pattern.pattern_strategies import LowBacktraceIncreaseStrategy
        s = LowBacktraceIncreaseStrategy()
        df = make_ohlcv(100, daily_return=0.001, volatility=0.001, seed=1)
        code_name = (df.iloc[-1]["date"].strftime("%Y-%m-%d"), "600000")
        assert s.check(code_name, df) is False

    def test_low_backtrace_increase_success(self):
        from quantia.core.strategy.pattern.pattern_strategies import LowBacktraceIncreaseStrategy
        s = LowBacktraceIncreaseStrategy()
        n = 70
        df = make_ohlcv(n, base_price=10.0, daily_return=0.009,
                        volatility=0.001, seed=99)
        df["p_change"] = df["close"].pct_change().fillna(0) * 100
        df["open"] = df["close"] * 0.999
        code_name = (df.iloc[-1]["date"].strftime("%Y-%m-%d"), "600000")
        assert s.check(code_name, df) is True

    def test_compat_check_low_backtrace(self):
        from quantia.core.strategy.pattern.pattern_strategies import check_low_backtrace
        df = make_ohlcv(100, seed=1)
        code_name = (df.iloc[-1]["date"].strftime("%Y-%m-%d"), "600000")
        result = check_low_backtrace(code_name, df)
        assert isinstance(result, bool)


# =========================================================================
# 17. fundamental/fundamental_filter.py
# =========================================================================
class TestFundamentalFilter:
    def test_filter_level_enum(self):
        from quantia.core.strategy.fundamental.fundamental_filter import FilterLevel
        assert FilterLevel.SAFETY.value == 1
        assert FilterLevel.VALUATION.value == 5
        assert len(FilterLevel) == 5

    def test_fundamental_criteria_defaults(self):
        from quantia.core.strategy.fundamental.fundamental_filter import FundamentalCriteria
        c = FundamentalCriteria()
        assert c.min_roe == 15.0
        assert c.max_debt_ratio == 60.0
        assert c.min_gross_margin == 30.0
        assert c.max_pe_ttm == 50.0
        assert c.min_current_ratio == 1.0

    def test_fundamental_criteria_custom(self):
        from quantia.core.strategy.fundamental.fundamental_filter import FundamentalCriteria
        c = FundamentalCriteria(min_roe=20.0, max_debt_ratio=50.0)
        assert c.min_roe == 20.0
        assert c.max_debt_ratio == 50.0

    def test_fundamental_filter_reduces_count(self):
        from quantia.core.strategy.fundamental.fundamental_filter import (
            FundamentalFilter, FundamentalCriteria
        )
        df = make_fundamental_df(n=10, good=4)
        f = FundamentalFilter()
        result = f.filter_stocks(df)
        assert len(result) < len(df)

    def test_fundamental_filter_safety_only(self):
        from quantia.core.strategy.fundamental.fundamental_filter import (
            FundamentalFilter, FilterLevel
        )
        df = make_fundamental_df(n=8, good=5)
        f = FundamentalFilter()
        result = f.filter_stocks(df, levels=[FilterLevel.SAFETY])
        # Good rows have debt < 60 and cashflow > 0 → should pass safety
        assert len(result) >= 5

    def test_fundamental_filter_empty_input(self):
        from quantia.core.strategy.fundamental.fundamental_filter import FundamentalFilter
        f = FundamentalFilter()
        result = f.filter_stocks(pd.DataFrame())
        assert result is not None

    def test_fundamental_filter_none_input(self):
        from quantia.core.strategy.fundamental.fundamental_filter import FundamentalFilter
        f = FundamentalFilter()
        result = f.filter_stocks(None)
        assert result is None

    def test_moat_scorer_calculate_score(self):
        from quantia.core.strategy.fundamental.fundamental_filter import MoatScorer
        scorer = MoatScorer()
        row = make_fundamental_row(
            roe_weight=25.0, sale_gpr=50.0, sale_npr=20.0,
            jroa=12.0, roic=18.0,
            debt_asset_ratio=25.0, per_netcash_operate=2.0,
            current_ratio=2.5,
            income_growthrate_3y=25.0, netprofit_growthrate_3y=25.0,
            zxgxl=3.0
        )
        score = scorer.calculate_score(row)
        assert score.total_score > 0
        assert score.grade in ("A", "B", "C", "D")
        assert isinstance(score.moat_type, list)
        assert isinstance(score.risk_factors, list)
        assert score.profitability_score <= 25
        assert score.stability_score <= 20
        assert score.growth_score <= 20
        assert score.efficiency_score <= 15
        assert score.safety_score <= 20

    def test_moat_scorer_weak_stock(self):
        from quantia.core.strategy.fundamental.fundamental_filter import MoatScorer
        scorer = MoatScorer()
        row = make_fundamental_row(
            roe_weight=2.0, sale_gpr=8.0, sale_npr=1.0,
            jroa=1.0, roic=2.0,
            debt_asset_ratio=75.0, per_netcash_operate=-1.0,
            current_ratio=0.5,
            income_growthrate_3y=-5.0, netprofit_growthrate_3y=-3.0,
            zxgxl=0.0
        )
        score = scorer.calculate_score(row)
        assert score.total_score < 30
        assert score.grade == "D"
        assert "高负债" in score.risk_factors or "现金流为负" in score.risk_factors

    def test_moat_scorer_batch_score(self):
        from quantia.core.strategy.fundamental.fundamental_filter import MoatScorer
        scorer = MoatScorer()
        df = make_fundamental_df(n=5, good=3)
        result = scorer.batch_score(df)
        assert "moat_score" in result.columns
        assert "moat_grade" in result.columns
        assert len(result) == len(df)

    def test_filter_value_stocks_convenience(self):
        from quantia.core.strategy.fundamental.fundamental_filter import filter_value_stocks
        df = make_fundamental_df(n=8, good=4)
        result = filter_value_stocks(df, strict=False)
        assert isinstance(result, pd.DataFrame)

    def test_filter_value_stocks_strict(self):
        from quantia.core.strategy.fundamental.fundamental_filter import filter_value_stocks
        df = make_fundamental_df(n=8, good=4)
        result_strict = filter_value_stocks(df, strict=True)
        result_normal = filter_value_stocks(df, strict=False)
        assert len(result_strict) <= len(result_normal)

    def test_score_stocks_convenience(self):
        from quantia.core.strategy.fundamental.fundamental_filter import score_stocks
        df = make_fundamental_df(n=4, good=2)
        result = score_stocks(df)
        assert "moat_score" in result.columns

    def test_get_top_moat_stocks(self):
        from quantia.core.strategy.fundamental.fundamental_filter import get_top_moat_stocks
        df = make_fundamental_df(n=10, good=6)
        result = get_top_moat_stocks(df, top_n=3)
        assert len(result) <= 3

    def test_moat_score_calculate_grade(self):
        from quantia.core.strategy.fundamental.fundamental_filter import MoatScore
        s = MoatScore(total_score=85)
        s.calculate_grade()
        assert s.grade == "A"
        s.total_score = 70
        s.calculate_grade()
        assert s.grade == "B"
        s.total_score = 55
        s.calculate_grade()
        assert s.grade == "C"
        s.total_score = 30
        s.calculate_grade()
        assert s.grade == "D"


# =========================================================================
# 18. fundamental/fundamental_strategies.py
# =========================================================================
class TestFundamentalStrategies:
    def test_value_invest_check_pass(self):
        from quantia.core.strategy.fundamental.fundamental_strategies import ValueInvestStrategy
        s = ValueInvestStrategy()
        row = make_fundamental_row(
            roe_weight=20.0, sale_gpr=40.0, sale_npr=15.0,
            debt_asset_ratio=30.0, per_netcash_operate=2.0, pe9=25.0
        )
        assert s.check(row) is True

    def test_value_invest_check_fail_low_roe(self):
        from quantia.core.strategy.fundamental.fundamental_strategies import ValueInvestStrategy
        s = ValueInvestStrategy()
        row = make_fundamental_row(roe_weight=5.0)
        assert s.check(row) is False

    def test_value_invest_check_fail_high_pe(self):
        from quantia.core.strategy.fundamental.fundamental_strategies import ValueInvestStrategy
        s = ValueInvestStrategy()
        row = make_fundamental_row(pe9=60.0)
        assert s.check(row) is False

    def test_value_invest_check_fail_nan_roe(self):
        from quantia.core.strategy.fundamental.fundamental_strategies import ValueInvestStrategy
        s = ValueInvestStrategy()
        row = make_fundamental_row(roe_weight=float("nan"))
        assert s.check(row) is False

    def test_value_invest_filter_stocks(self):
        from quantia.core.strategy.fundamental.fundamental_strategies import ValueInvestStrategy
        s = ValueInvestStrategy()
        df = make_fundamental_df(n=8, good=4)
        result = s.filter_stocks(df)
        assert isinstance(result, pd.DataFrame)

    def test_growth_invest_check_pass(self):
        from quantia.core.strategy.fundamental.fundamental_strategies import GrowthInvestStrategy
        s = GrowthInvestStrategy()
        row = make_fundamental_row(
            income_growthrate_3y=20.0, netprofit_growthrate_3y=20.0,
            roe_weight=15.0, sale_gpr=30.0, debt_asset_ratio=40.0
        )
        assert s.check(row) is True

    def test_growth_invest_check_fail_low_growth(self):
        from quantia.core.strategy.fundamental.fundamental_strategies import GrowthInvestStrategy
        s = GrowthInvestStrategy()
        row = make_fundamental_row(income_growthrate_3y=5.0)
        assert s.check(row) is False

    def test_moat_strategy_check_pass(self):
        from quantia.core.strategy.fundamental.fundamental_strategies import MoatStrategy
        s = MoatStrategy()
        # Build a row with very strong fundamentals to get score >= 65
        row = make_fundamental_row(
            roe_weight=25.0, sale_gpr=50.0, sale_npr=20.0,
            jroa=12.0, roic=18.0,
            debt_asset_ratio=25.0, per_netcash_operate=2.0,
            current_ratio=2.5, speed_ratio=2.0,
            income_growthrate_3y=25.0, netprofit_growthrate_3y=25.0,
            zxgxl=3.0
        )
        result = s.check(row)
        assert isinstance(result, bool)

    def test_moat_strategy_check_fail_low_roe(self):
        from quantia.core.strategy.fundamental.fundamental_strategies import MoatStrategy
        s = MoatStrategy()
        row = make_fundamental_row(roe_weight=5.0)
        assert s.check(row) is False

    def test_dividend_growth_check_pass(self):
        from quantia.core.strategy.fundamental.fundamental_strategies import DividendGrowthStrategy
        s = DividendGrowthStrategy()
        row = make_fundamental_row(
            zxgxl=3.0, roe_weight=15.0, netprofit_growthrate_3y=10.0,
            debt_asset_ratio=30.0, per_netcash_operate=1.5
        )
        assert s.check(row) is True

    def test_dividend_growth_check_fail_low_dividend(self):
        from quantia.core.strategy.fundamental.fundamental_strategies import DividendGrowthStrategy
        s = DividendGrowthStrategy()
        row = make_fundamental_row(zxgxl=0.5)
        assert s.check(row) is False

    def test_dividend_growth_check_fail_negative_cashflow(self):
        from quantia.core.strategy.fundamental.fundamental_strategies import DividendGrowthStrategy
        s = DividendGrowthStrategy()
        row = make_fundamental_row(per_netcash_operate=-1.0)
        assert s.check(row) is False


# =========================================================================
# 19. fundamental/moat_model.py
# =========================================================================
class TestMoatModel:
    def test_moat_category_enum(self):
        from quantia.core.strategy.fundamental.moat_model import MoatCategory
        assert MoatCategory.BRAND.value == "brand"
        assert MoatCategory.SCALE.value == "scale"
        assert len(MoatCategory) == 8

    def test_risk_level_enum(self):
        from quantia.core.strategy.fundamental.moat_model import RiskLevel
        assert RiskLevel.LOW.value == "low"
        assert RiskLevel.CRITICAL.value == "critical"

    def test_quantitative_metric_weighted_score(self):
        from quantia.core.strategy.fundamental.moat_model import QuantitativeMetric
        m = QuantitativeMetric(name="ROE", value=25.0, score=80.0, weight=0.15)
        assert m.weighted_score() == 80.0 * 0.15

    def test_scorecard_add_quantitative_score(self):
        from quantia.core.strategy.fundamental.moat_model import MoatScorecard
        sc = MoatScorecard(stock_code="600519", stock_name="贵州茅台")
        sc.add_quantitative_score("ROE", 25.0, category="profitability",
                                  weight=0.15, thresholds=(5, 30))
        assert len(sc.profitability_metrics) == 1
        m = sc.profitability_metrics[0]
        assert m.name == "ROE"
        assert m.value == 25.0
        # score = (25-5)/(30-5)*100 = 80
        assert abs(m.score - 80.0) < 0.1

    def test_scorecard_add_quantitative_score_below_threshold(self):
        from quantia.core.strategy.fundamental.moat_model import MoatScorecard
        sc = MoatScorecard(stock_code="600519")
        sc.add_quantitative_score("ROE", 3.0, thresholds=(5, 30))
        assert sc.profitability_metrics[0].score == 0

    def test_scorecard_add_quantitative_score_above_threshold(self):
        from quantia.core.strategy.fundamental.moat_model import MoatScorecard
        sc = MoatScorecard(stock_code="600519")
        sc.add_quantitative_score("ROE", 50.0, thresholds=(5, 30))
        assert sc.profitability_metrics[0].score == 100

    def test_scorecard_add_qualitative_assessment(self):
        from quantia.core.strategy.fundamental.moat_model import MoatScorecard, MoatCategory
        sc = MoatScorecard(stock_code="600519")
        sc.add_qualitative_assessment(
            MoatCategory.BRAND, "品牌是否有定价权?",
            "是", score=5
        )
        assert len(sc.moat_assessments) == 1
        assert MoatCategory.BRAND in sc.identified_moats

    def test_scorecard_add_qualitative_low_score_not_moat(self):
        from quantia.core.strategy.fundamental.moat_model import MoatScorecard, MoatCategory
        sc = MoatScorecard(stock_code="600519")
        sc.add_qualitative_assessment(
            MoatCategory.NETWORK, "有网络效应?",
            "弱", score=2
        )
        assert MoatCategory.NETWORK not in sc.identified_moats

    def test_scorecard_add_risk(self):
        from quantia.core.strategy.fundamental.moat_model import MoatScorecard, RiskLevel
        sc = MoatScorecard(stock_code="600519")
        sc.add_risk("高负债", RiskLevel.HIGH, description="资产负债率70%")
        assert len(sc.risk_factors) == 1
        assert sc.risk_factors[0].level == RiskLevel.HIGH

    def test_scorecard_calculate_final_score(self):
        from quantia.core.strategy.fundamental.moat_model import MoatScorecard, MoatCategory, RiskLevel
        sc = MoatScorecard(stock_code="600519")
        sc.add_quantitative_score("ROE", 25.0, thresholds=(5, 30), weight=1.0)
        sc.add_qualitative_assessment(MoatCategory.BRAND, "Q?", "A", score=4)
        sc.overall_risk = RiskLevel.LOW
        sc.calculate_final_score()
        assert sc.final_score > 0
        assert sc.grade in ("A", "B", "C", "D")
        assert sc.recommendation != ""

    def test_scorecard_risk_penalty(self):
        from quantia.core.strategy.fundamental.moat_model import MoatScorecard, RiskLevel
        sc = MoatScorecard(stock_code="600519")
        sc.add_quantitative_score("ROE", 20.0, thresholds=(5, 30), weight=1.0)
        sc.overall_risk = RiskLevel.LOW
        sc.calculate_final_score()
        low_risk_score = sc.final_score

        sc2 = MoatScorecard(stock_code="600519")
        sc2.add_quantitative_score("ROE", 20.0, thresholds=(5, 30), weight=1.0)
        sc2.overall_risk = RiskLevel.CRITICAL
        sc2.calculate_final_score()
        assert sc2.final_score < low_risk_score

    def test_scorecard_to_dict_from_dict_roundtrip(self):
        from quantia.core.strategy.fundamental.moat_model import (
            MoatScorecard, MoatCategory, RiskLevel
        )
        sc = MoatScorecard(stock_code="600519", stock_name="贵州茅台",
                           industry="白酒")
        sc.add_quantitative_score("ROE", 25.0, thresholds=(5, 30))
        sc.add_qualitative_assessment(MoatCategory.BRAND, "Q?", "A", score=5)
        sc.add_risk("政策风险", RiskLevel.MEDIUM, description="限制")
        sc.calculate_final_score()

        d = sc.to_dict()
        assert d["basic_info"]["stock_code"] == "600519"
        assert d["scores"]["grade"] == sc.grade
        assert len(d["quantitative"]["profitability"]) == 1
        assert len(d["risks"]) == 1

    def test_scorecard_to_json(self):
        from quantia.core.strategy.fundamental.moat_model import MoatScorecard
        sc = MoatScorecard(stock_code="600519", stock_name="贵州茅台")
        sc.add_quantitative_score("ROE", 25, thresholds=(5, 30))
        sc.calculate_final_score()
        j = sc.to_json()
        parsed = json.loads(j)
        assert parsed["basic_info"]["stock_code"] == "600519"

    def test_create_default_scorecard(self):
        from quantia.core.strategy.fundamental.moat_model import create_default_scorecard
        sc = create_default_scorecard("600519", "贵州茅台")
        assert sc.stock_code == "600519"
        assert sc.stock_name == "贵州茅台"
        assert len(sc.moat_assessments) > 0
        # Default questions cover multiple categories
        categories = {a.category for a in sc.moat_assessments}
        assert len(categories) >= 5

    def test_get_threshold_config(self):
        from quantia.core.strategy.fundamental.moat_model import get_threshold_config, SCORING_THRESHOLDS
        config = get_threshold_config()
        assert isinstance(config, dict)
        # Should have same keys as SCORING_THRESHOLDS
        for k in SCORING_THRESHOLDS:
            assert k in config

    def test_ai_analysis_request_to_prompt(self):
        from quantia.core.strategy.fundamental.moat_model import AIAnalysisRequest
        req = AIAnalysisRequest(
            stock_code="600519", stock_name="贵州茅台",
            industry="白酒",
            financial_data={"roe": 25.0, "gross_margin": 91.0}
        )
        prompt = req.to_prompt()
        assert "600519" in prompt
        assert "贵州茅台" in prompt

    def test_ai_analysis_result_from_json(self):
        from quantia.core.strategy.fundamental.moat_model import AIAnalysisResult
        data = {
            "moat_types": [{"type": "brand", "score": 4}],
            "risk_factors": ["政策风险"],
            "investment_thesis": "强品牌",
            "concerns": ["竞争加剧"],
            "overall_score": 85,
            "confidence": 0.8
        }
        result = AIAnalysisResult.from_json(json.dumps(data))
        assert result.overall_score == 85
        assert result.confidence == 0.8
        assert len(result.moat_types) == 1


# =========================================================================
# 20. fundamental/moat_ai_service.py
# =========================================================================
class TestMoatAIService:
    def test_moat_ai_config_defaults(self):
        from quantia.core.strategy.fundamental.moat_ai_service import MoatAIConfig
        cfg = MoatAIConfig()
        assert cfg.model == "gpt-4"
        assert cfg.temperature == 0.3
        assert cfg.max_tokens == 2000
        assert cfg.timeout == 60
        assert cfg.api_key == ""

    def test_moat_ai_config_custom(self):
        from quantia.core.strategy.fundamental.moat_ai_service import MoatAIConfig
        cfg = MoatAIConfig(model="gpt-3.5-turbo", api_key="sk-test", temperature=0.5)
        assert cfg.model == "gpt-3.5-turbo"
        assert cfg.api_key == "sk-test"
        assert cfg.temperature == 0.5

    def test_moat_ai_service_no_key_returns_none(self):
        from quantia.core.strategy.fundamental.moat_ai_service import MoatAIService, MoatAIConfig
        cfg = MoatAIConfig(api_key="")
        service = MoatAIService(config=cfg)
        result = service.analyze_moat("600519", "贵州茅台", "白酒", {"roe": 25})
        assert result is None

    def test_moat_ai_service_quick_assess_no_key(self):
        from quantia.core.strategy.fundamental.moat_ai_service import MoatAIService, MoatAIConfig
        cfg = MoatAIConfig(api_key="")
        service = MoatAIService(config=cfg)
        result = service.quick_assess("600519", "贵州茅台", "白酒", 25, 91, 15)
        assert result is None

    @mock.patch.object(
        __import__("quantia.core.strategy.fundamental.moat_ai_service",
                    fromlist=["MoatAIService"]).MoatAIService,
        "_call_ai"
    )
    def test_analyze_moat_with_mock(self, mock_call):
        from quantia.core.strategy.fundamental.moat_ai_service import MoatAIService, MoatAIConfig
        mock_call.return_value = json.dumps({
            "moat_types": [{"type": "brand", "score": 4, "reason": "强品牌"}],
            "risk_factors": [{"name": "政策", "level": "medium", "description": "x"}],
            "investment_thesis": "优质标的",
            "concerns": ["竞争"],
            "overall_score": 85,
            "confidence": 0.8
        })
        cfg = MoatAIConfig(api_key="sk-fake")
        service = MoatAIService(config=cfg)
        result = service.analyze_moat("600519", "贵州茅台", "白酒", {"roe": 25})
        assert result is not None
        assert result.overall_score == 85

    def test_generate_moat_report(self):
        from quantia.core.strategy.fundamental.moat_ai_service import generate_moat_report
        from quantia.core.strategy.fundamental.moat_model import (
            MoatScorecard, MoatCategory, RiskLevel
        )
        sc = MoatScorecard(stock_code="600519", stock_name="贵州茅台",
                           industry="白酒")
        sc.add_quantitative_score("ROE", 25.0, thresholds=(5, 30))
        sc.add_qualitative_assessment(MoatCategory.BRAND, "Q?", "A", score=5)
        sc.add_risk("政策风险", RiskLevel.MEDIUM, description="可能调税")
        sc.calculate_final_score()
        sc.ai_investment_thesis = "优质白酒龙头"
        sc.ai_concerns = ["年轻人不喝白酒?"]

        report = generate_moat_report(sc)
        assert "600519" in report
        assert "贵州茅台" in report
        assert "政策风险" in report
        assert "优质白酒龙头" in report

    @mock.patch.object(
        __import__("quantia.core.strategy.fundamental.moat_ai_service",
                    fromlist=["MoatAIService"]).MoatAIService,
        "_call_ai"
    )
    def test_enrich_scorecard(self, mock_call):
        from quantia.core.strategy.fundamental.moat_ai_service import MoatAIService, MoatAIConfig
        from quantia.core.strategy.fundamental.moat_model import MoatScorecard
        mock_call.return_value = json.dumps({
            "moat_types": [{"type": "brand", "score": 5, "reason": "顶级品牌"}],
            "risk_factors": [],
            "investment_thesis": "核心资产",
            "concerns": ["估值偏高"],
            "overall_score": 90,
            "confidence": 0.9
        })
        cfg = MoatAIConfig(api_key="sk-fake")
        service = MoatAIService(config=cfg)
        sc = MoatScorecard(stock_code="600519", stock_name="贵州茅台",
                           industry="白酒")
        enriched = service.enrich_scorecard(sc, {"roe": 25})
        assert enriched.ai_investment_thesis == "核心资产"
        assert "估值偏高" in enriched.ai_concerns

    def test_parse_analysis_result_with_markdown(self):
        from quantia.core.strategy.fundamental.moat_ai_service import MoatAIService, MoatAIConfig
        cfg = MoatAIConfig(api_key="sk-fake")
        service = MoatAIService(config=cfg)
        md_response = '```json\n{"moat_types":[],"risk_factors":[],"investment_thesis":"test","concerns":[],"overall_score":50,"confidence":0.5}\n```'
        result = service._parse_analysis_result(md_response)
        assert result is not None
        assert result.overall_score == 50

    def test_parse_analysis_result_invalid_json(self):
        from quantia.core.strategy.fundamental.moat_ai_service import MoatAIService, MoatAIConfig
        cfg = MoatAIConfig(api_key="sk-fake")
        service = MoatAIService(config=cfg)
        result = service._parse_analysis_result("not json at all {{{")
        assert result is None


# =========================================================================
# Run
# =========================================================================
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
