"""Composite 引擎单元测试。"""
import numpy as np
import pandas as pd
import pytest

from quantia.core.composite.composite_engine import Composite


def _make_df(n: int = 50) -> pd.DataFrame:
    np.random.seed(42)
    return pd.DataFrame({
        "n_a": np.linspace(80, 20, n),  # 单调下降，会穿过 30
        "n_b": np.linspace(80, 20, n),
        "trend_st": [1] * n,
    })


def test_validates_empty_weights():
    with pytest.raises(ValueError, match="weights"):
        Composite(name="x", weights={})


def test_validates_direction():
    with pytest.raises(ValueError, match="direction"):
        Composite(name="x", weights={"a": 1.0}, direction="middle")


def test_validates_weight_sum_positive():
    with pytest.raises(ValueError, match="sum"):
        Composite(name="x", weights={"a": 0.0, "b": 0.0})


def test_value_raises_on_missing_column():
    c = Composite(name="x", weights={"missing_col": 1.0})
    df = _make_df()
    with pytest.raises(KeyError, match="missing"):
        c.value(df)


def test_value_weighted_average():
    c = Composite(name="x", weights={"n_a": 1.0, "n_b": 3.0})
    df = pd.DataFrame({"n_a": [100.0], "n_b": [0.0]})
    # (100*1 + 0*3) / 4 = 25
    assert c.value(df).iloc[0] == 25.0


def test_signal_low_direction_triggers_on_cross_down():
    c = Composite(name="x", weights={"n_a": 1.0}, buy_th=30, direction="low")
    df = _make_df()
    sig = c.signal(df)
    # 评分从 80 单调降到 20，必有一次 30 穿越
    assert sig.sum() == 1


def test_signal_high_direction_triggers_on_cross_up():
    c = Composite(name="x", weights={"n_a": 1.0}, buy_th=50, direction="high")
    # 单调上升的列
    df = pd.DataFrame({"n_a": np.linspace(20, 80, 30)})
    sig = c.signal(df)
    assert sig.sum() == 1


def test_signal_require_uptrend_filters():
    c = Composite(name="x", weights={"n_a": 1.0}, buy_th=30,
                  direction="low", require_uptrend=True)
    df = _make_df()
    df["trend_st"] = -1  # 全部下跌
    assert c.signal(df).sum() == 0


def test_signal_extra_filter():
    c = Composite(name="x", weights={"n_a": 1.0}, buy_th=30, direction="low",
                  extra_filter=lambda d: pd.Series([False] * len(d)))
    assert c.signal(_make_df()).sum() == 0


def test_smooth_ema_smooths_value():
    c = Composite(name="x", weights={"n_a": 1.0}, smooth_ema=3)
    df = pd.DataFrame({"n_a": [0.0, 100.0, 100.0, 100.0]})
    v = c.value(df)
    # EMA 平滑后第二个不会立即跳到 100
    assert v.iloc[1] < 100
