"""归一化函数单元测试。"""
import numpy as np
import pandas as pd
import pytest

from quantia.core.composite.normalizers import (
    n_lin, n_wr, n_rank, n_supertrend, n_pctb, n_cci,
)


def test_n_lin_clips():
    s = pd.Series([-10, 0, 50, 100, 150])
    out = n_lin(s)
    assert out.tolist() == [0, 0, 50, 100, 100]


def test_n_lin_preserves_nan():
    s = pd.Series([np.nan, 50.0])
    out = n_lin(s)
    assert pd.isna(out.iloc[0])
    assert out.iloc[1] == 50.0


def test_n_wr_inverts_williams_r():
    s = pd.Series([-100, -80, -50, -20, 0])
    out = n_wr(s)
    assert out.tolist() == [0, 20, 50, 80, 100]


def test_n_rank_returns_0_100():
    s = pd.Series(np.arange(100, dtype=float))
    out = n_rank(s, w=60)
    assert out.between(0, 100).all()
    # 末尾必为最高 rank ≈ 100
    assert out.iloc[-1] > 95


def test_n_rank_fills_nan_with_50():
    s = pd.Series([1.0, 2.0, 3.0])
    out = n_rank(s, w=60)
    # 不足窗口 → 全 NaN → 填 50
    assert (out == 50).all()


def test_n_supertrend_maps_to_0_100():
    s = pd.Series([-1, 1, -1, 1])
    out = n_supertrend(s)
    assert out.tolist() == [0, 100, 0, 100]


def test_n_pctb_normal():
    close = pd.Series([10.0, 11.0, 12.0])
    lower = pd.Series([8.0, 8.0, 8.0])
    upper = pd.Series([12.0, 12.0, 12.0])
    out = n_pctb(close, lower, upper)
    assert out.tolist() == [50.0, 75.0, 100.0]


def test_n_pctb_handles_zero_band():
    close = pd.Series([10.0])
    lower = pd.Series([10.0])
    upper = pd.Series([10.0])  # upper == lower → 防 zero-div
    out = n_pctb(close, lower, upper)
    assert pd.isna(out.iloc[0])


def test_n_pctb_clips_outside_band():
    close = pd.Series([5.0, 20.0])
    lower = pd.Series([8.0, 8.0])
    upper = pd.Series([12.0, 12.0])
    out = n_pctb(close, lower, upper)
    assert out.tolist() == [0.0, 100.0]


def test_n_cci_normal():
    s = pd.Series([-200.0, 0.0, 200.0])
    out = n_cci(s)
    assert out.tolist() == [0.0, 50.0, 100.0]


def test_n_cci_clips():
    s = pd.Series([-500.0, 500.0])
    out = n_cci(s)
    assert out.tolist() == [0.0, 100.0]


def test_normalizers_dont_mutate_input():
    s = pd.Series([1.0, 2.0, 3.0])
    original = s.copy()
    _ = n_lin(s)
    _ = n_rank(s)
    pd.testing.assert_series_equal(s, original)
