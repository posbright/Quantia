"""
归一化函数集合（从 _compare_composite_winrate_v2.py 抽取）。

所有函数：
- 输入 pd.Series（或几个 Series 组合）
- 输出 0~100 区间的 pd.Series（NaN 用合理默认填充）
- 不修改输入
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def n_lin(s: pd.Series) -> pd.Series:
    """线性截断到 0~100。适用于 RSI/KDJ-K 等已在 0~100 的指标。"""
    return s.clip(0, 100)


def n_wr(s: pd.Series) -> pd.Series:
    """Williams %R 反向归一化：原始 -100~0 → 100~0（值越低越超卖）→ 翻成评分。"""
    return (100 + s).clip(0, 100)


def n_rank(s: pd.Series, w: int = 60) -> pd.Series:
    """滚动百分位 rank → 0~100 评分。NaN 默认填 50（中性）。"""
    return (s.rolling(w).rank(pct=True) * 100).fillna(50)


def n_supertrend(s: pd.Series) -> pd.Series:
    """SuperTrend 方向 (-1/+1) → 0/100。"""
    return ((s + 1) / 2) * 100


def n_pctb(close: pd.Series, lower: pd.Series, upper: pd.Series) -> pd.Series:
    """BOLL %B：(close - lower) / (upper - lower) × 100。"""
    return ((close - lower) / (upper - lower).replace(0, np.nan) * 100).clip(0, 100)


def n_cci(s: pd.Series) -> pd.Series:
    """CCI ±200 → 0~100。"""
    return ((s + 200) / 4).clip(0, 100)


__all__ = ["n_lin", "n_wr", "n_rank", "n_supertrend", "n_pctb", "n_cci"]
