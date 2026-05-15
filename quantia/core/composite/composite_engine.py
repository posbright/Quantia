"""
Composite 加权评分引擎（从 _compare_composite_winrate_v2.Composite 抽取）。

设计：
- 加权评分 = Σ(weights[col] * df[col]) / Σ(weights)
- 可选 EMA 平滑（smooth_ema）
- 触发模式 direction:
    "low"  → 评分由 ≥ buy_th 跌穿到 < buy_th（抄底/超卖确认）
    "high" → 评分由 ≤ buy_th 升穿到 > buy_th（突破/反弹确认）
- 可选额外硬过滤 (extra_filter callable)
- 可选 require_uptrend (trend_st == 1)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

import pandas as pd


@dataclass
class Composite:
    name: str
    weights: dict[str, float]
    smooth_ema: int = 0
    buy_th: float = 30.0
    require_uptrend: bool = False
    direction: str = "low"   # "low" or "high"
    extra_filter: Optional[Callable[[pd.DataFrame], pd.Series]] = None

    def __post_init__(self) -> None:
        if not self.weights:
            raise ValueError("weights must not be empty")
        if self.direction not in ("low", "high"):
            raise ValueError(f"direction must be 'low' or 'high', got {self.direction!r}")
        wsum = sum(self.weights.values())
        if wsum <= 0:
            raise ValueError(f"weights must sum to > 0, got {wsum}")

    def value(self, d: pd.DataFrame) -> pd.Series:
        """计算复合评分（0~100）。"""
        missing = [k for k in self.weights if k not in d.columns]
        if missing:
            raise KeyError(f"DataFrame missing required columns: {missing}")
        wsum = sum(self.weights.values())
        out = sum(d[k] * w for k, w in self.weights.items()) / wsum
        if self.smooth_ema > 0:
            out = out.ewm(span=self.smooth_ema, adjust=False).mean()
        return out

    def signal(self, d: pd.DataFrame) -> pd.Series:
        """触发布尔信号 (T+0 触发位)。"""
        v = self.value(d)
        if self.direction == "low":
            sig = (v.shift(1) >= self.buy_th) & (v < self.buy_th)
        else:
            sig = (v.shift(1) <= self.buy_th) & (v > self.buy_th)
        if self.require_uptrend:
            if "trend_st" not in d.columns:
                raise KeyError("require_uptrend=True 但 DataFrame 无 trend_st 列")
            sig &= d["trend_st"] == 1
        if self.extra_filter is not None:
            sig &= self.extra_filter(d)
        return sig.fillna(False)


__all__ = ["Composite"]
