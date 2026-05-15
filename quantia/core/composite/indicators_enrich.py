"""
原始技术指标计算 + 归一化丰富列。

设计原则：
- 输入：原始 OHLCV DataFrame（columns: date, open, high, low, close, volume）
- 输出：原 DataFrame 的拷贝 + 多列 `n_*` 归一化评分（0~100）
- 与 _compare_composite_winrate_v2.enrich 数值完全一致（可对比 V6 实证结果）
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from quantia.core.composite.normalizers import (
    n_lin, n_wr, n_rank, n_supertrend, n_pctb, n_cci,
)


# ============================ 原始指标 ========================================
def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    diff = close.diff()
    gain = diff.clip(lower=0)
    loss = -diff.clip(upper=0)
    ag = gain.ewm(alpha=1 / n, adjust=False).mean()
    al = loss.ewm(alpha=1 / n, adjust=False).mean()
    rs = ag / al.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def kdj(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 9):
    ll = low.rolling(n).min()
    hh = high.rolling(n).max()
    rsv = ((close - ll) / (hh - ll).replace(0, np.nan) * 100).fillna(50)
    k = rsv.ewm(com=2, adjust=False).mean()
    d = k.ewm(com=2, adjust=False).mean()
    j = 3 * k - 2 * d
    return k, d, j


def wr(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    hh = high.rolling(n).max()
    ll = low.rolling(n).min()
    return (-100 * (hh - close) / (hh - ll).replace(0, np.nan)).fillna(-50)


def macd_hist(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.Series:
    ema_f = close.ewm(span=fast, adjust=False).mean()
    ema_s = close.ewm(span=slow, adjust=False).mean()
    dif = ema_f - ema_s
    dea = dif.ewm(span=signal, adjust=False).mean()
    return (dif - dea) * 2


def boll(close: pd.Series, n: int = 20, k: float = 2.0):
    mid = close.rolling(n).mean()
    sd = close.rolling(n).std()
    return mid - k * sd, mid, mid + k * sd


def supertrend_dir(high: pd.Series, low: pd.Series, close: pd.Series,
                   period: int = 10, mult: float = 3.0) -> pd.Series:
    tr = pd.concat([high - low,
                    (high - close.shift()).abs(),
                    (low - close.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    hl2 = (high + low) / 2
    upper = hl2 + mult * atr
    lower = hl2 - mult * atr
    arr = np.ones(len(close), dtype=int)
    c = close.to_numpy(); u = upper.to_numpy(); lo = lower.to_numpy()
    for i in range(1, len(close)):
        if c[i] > u[i - 1]:
            arr[i] = 1
        elif c[i] < lo[i - 1]:
            arr[i] = -1
        else:
            arr[i] = arr[i - 1]
    return pd.Series(arr, index=close.index)


def adx(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    up = high.diff()
    dn = -low.diff()
    plus_dm = ((up > dn) & (up > 0)).astype(float) * up
    minus_dm = ((dn > up) & (dn > 0)).astype(float) * dn
    tr = pd.concat([high - low,
                    (high - close.shift()).abs(),
                    (low - close.shift()).abs()], axis=1).max(axis=1)
    atr_ = tr.ewm(alpha=1 / n, adjust=False).mean().replace(0, np.nan)
    plus_di = 100 * plus_dm.ewm(alpha=1 / n, adjust=False).mean() / atr_
    minus_di = 100 * minus_dm.ewm(alpha=1 / n, adjust=False).mean() / atr_
    dx = (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan) * 100
    return dx.ewm(alpha=1 / n, adjust=False).mean().fillna(0)


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    sign = np.sign(close.diff().fillna(0))
    return (sign * volume).cumsum()


def cci(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 20) -> pd.Series:
    tp = (high + low + close) / 3
    ma = tp.rolling(n).mean()
    md = (tp - ma).abs().rolling(n).mean().replace(0, np.nan)
    return ((tp - ma) / (0.015 * md)).fillna(0)


# ============================ enrich =========================================
def enrich(df: pd.DataFrame) -> pd.DataFrame:
    """
    给 OHLCV DataFrame 增加完整的指标列 + 归一化 n_* 列。

    新增的关键列（部分摘抄）：
        ma5/ma10/ma20/ma60/ma120, rsi14, rsi6, kdj_k/d/j, wr14, macd_hist,
        boll_lower/mid/upper/pct_b/width, trend_st, adx14, obv, obv_slope10,
        vol_ma5, vol_ratio_5, cci20, atr14_pct,
        n_rsi14, n_rsi6, n_kdj_k, n_kdj_j, n_wr14, n_macd_hist_rank,
        n_trend_st, n_vol_ratio_rank, n_boll_pct_b, n_ma_uptrend,
        n_long_uptrend, n_atr_pct_inv_rank, n_obv_slope_rank, n_adx_rank,
        n_cci_inv
    """
    d = df.copy()
    d["ma5"] = d["close"].rolling(5).mean()
    d["ma10"] = d["close"].rolling(10).mean()
    d["ma20"] = d["close"].rolling(20).mean()
    d["ma60"] = d["close"].rolling(60).mean()
    d["ma120"] = d["close"].rolling(120).mean()
    d["rsi14"] = rsi(d["close"], 14)
    d["rsi6"] = rsi(d["close"], 6)
    k, dd, j = kdj(d["high"], d["low"], d["close"], 9)
    d["kdj_k"], d["kdj_d"], d["kdj_j"] = k, dd, j
    d["wr14"] = wr(d["high"], d["low"], d["close"], 14)
    d["macd_hist"] = macd_hist(d["close"])
    bl, bm, bu = boll(d["close"], 20, 2)
    d["boll_lower"], d["boll_mid"], d["boll_upper"] = bl, bm, bu
    d["boll_pct_b"] = n_pctb(d["close"], bl, bu)
    d["boll_width"] = (bu - bl) / bm.replace(0, np.nan)
    d["trend_st"] = supertrend_dir(d["high"], d["low"], d["close"])
    d["adx14"] = adx(d["high"], d["low"], d["close"], 14)
    d["obv"] = obv(d["close"], d["volume"])
    d["obv_slope10"] = d["obv"].diff(10) / d["obv"].abs().rolling(60).mean().replace(0, np.nan)
    d["vol_ma5"] = d["volume"].rolling(5).mean()
    d["vol_ratio_5"] = d["volume"] / d["vol_ma5"].replace(0, np.nan)
    d["cci20"] = cci(d["high"], d["low"], d["close"], 20)
    d["atr14_pct"] = (
        pd.concat([d["high"] - d["low"],
                   (d["high"] - d["close"].shift()).abs(),
                   (d["low"] - d["close"].shift()).abs()], axis=1).max(axis=1)
        .rolling(14).mean() / d["close"]
    )

    # 归一化 n_* 列
    d["n_rsi14"] = n_lin(d["rsi14"])
    d["n_rsi6"] = n_lin(d["rsi6"])
    d["n_kdj_k"] = n_lin(d["kdj_k"])
    d["n_kdj_j"] = n_lin(d["kdj_j"].clip(-50, 150) + 50) / 2 * 2
    d["n_wr14"] = n_wr(d["wr14"])
    d["n_macd_hist_rank"] = n_rank(d["macd_hist"], 60)
    d["n_trend_st"] = n_supertrend(d["trend_st"])
    d["n_vol_ratio_rank"] = n_rank(d["vol_ratio_5"], 60)
    d["n_boll_pct_b"] = n_lin(d["boll_pct_b"])
    d["n_ma_uptrend"] = ((d["ma20"] > d["ma60"]).astype(int) * 100)
    d["n_long_uptrend"] = ((d["ma60"] > d["ma120"]).astype(int) * 100)
    d["n_atr_pct_inv_rank"] = n_rank(-d["atr14_pct"], 60)
    d["n_obv_slope_rank"] = n_rank(d["obv_slope10"], 60)
    d["n_adx_rank"] = n_rank(d["adx14"], 60)
    d["n_cci_inv"] = (100 - n_cci(d["cci20"])).clip(0, 100)

    return d


__all__ = [
    "rsi", "kdj", "wr", "macd_hist", "boll",
    "supertrend_dir", "adx", "obv", "cci", "enrich",
]
