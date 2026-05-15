"""
单股交易模拟器（从 _compare_composite_winrate_v3_fundamentals.simulate 抽取）。

支持：
- T+1 进场（买信号当日的下一根 bar 开盘）
- 止损 / 止盈 / 持有期满 三路退出，止损优先
- 单股同时仅一仓
- 双边交易成本扣除
- 可选：基本面恶化提前止盈（fundamentals_check_fn 可调用）
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np
import pandas as pd


# 与 V2/V3 一致：佣金 0.06% + 印花税 0.10% (卖) + 滑点 0.20% = 0.36% 双边
ROUND_TRIP_COST = 0.0006 + 0.001 + 0.002


@dataclass
class Trade:
    code: str
    entry_bar: int
    entry_date: pd.Timestamp
    entry_price: float
    exit_bar: int
    exit_date: pd.Timestamp
    exit_price: float
    reason: str             # "stop-loss" | "win-target" | "time-exit" | "fundamentals-exit"
    gross_ret: float
    net_ret: float
    hold_days: int


def simulate(
    code: str,
    df_enriched: pd.DataFrame,
    sig: pd.Series,
    stop_loss: float = 0.05,
    take_profit: float = 0.10,
    max_hold: int = 20,
    cost: float = ROUND_TRIP_COST,
    fundamentals_check_fn: Optional[Callable[[str, pd.Timestamp], bool]] = None,
) -> list[Trade]:
    """
    walk-forward 模拟：信号触发 → 下一 bar 开盘进场 → 止损/止盈/到期/基本面退出
    取首发条件（同一 bar 同时触及止损与止盈，止损优先）。

    fundamentals_check_fn(code, date) -> True 表示当日基本面恶化，需立即平仓。
    """
    n = len(df_enriched)
    if n == 0:
        return []
    opn = df_enriched["open"].values
    hi  = df_enriched["high"].values
    lo  = df_enriched["low"].values
    cls = df_enriched["close"].values
    dts = df_enriched["date"].values
    sig_arr = sig.values

    trades: list[Trade] = []
    i = 0
    while i < n - 2:
        if not bool(sig_arr[i]):
            i += 1
            continue
        eb = i + 1
        if eb >= n:
            break
        entry = opn[eb]
        if not np.isfinite(entry) or entry <= 0:
            i = eb + 1
            continue
        target = entry * (1 + take_profit)
        stop = entry * (1 - stop_loss)
        out_bar, out_price, reason = None, None, None
        for j in range(eb, min(eb + max_hold + 1, n)):
            # 基本面退出最优先（开盘前可知）
            if fundamentals_check_fn is not None and j > eb:
                try:
                    if fundamentals_check_fn(code, pd.Timestamp(dts[j])):
                        out_bar, out_price, reason = j, float(opn[j]), "fundamentals-exit"
                        break
                except Exception:
                    pass  # 基本面查询失败，继续技术止损路径
            # 止损优先（保守）
            if lo[j] <= stop and j > eb:
                out_bar, out_price, reason = j, stop, "stop-loss"
                break
            if hi[j] >= target and j > eb:
                out_bar, out_price, reason = j, target, "win-target"
                break
        if out_bar is None:
            out_bar = min(eb + max_hold, n - 1)
            out_price = cls[out_bar]
            reason = "time-exit"
        gross = (out_price - entry) / entry
        net = gross - cost
        trades.append(Trade(
            code=code, entry_bar=eb, entry_date=pd.Timestamp(dts[eb]),
            entry_price=float(entry),
            exit_bar=out_bar, exit_date=pd.Timestamp(dts[out_bar]),
            exit_price=float(out_price), reason=reason,
            gross_ret=float(gross), net_ret=float(net),
            hold_days=int(out_bar - eb),
        ))
        i = out_bar + 1
    return trades


def summarize_trades(trades: list[Trade], name: str = "") -> dict:
    """汇总交易统计（与 V3 StrategyResult.summary 一致）。"""
    if not trades:
        return {"strategy": name, "trades": 0}
    rets = np.array([t.net_ret for t in trades])
    wins = rets[rets > 0]
    losses = rets[rets < 0]
    reasons = pd.Series([t.reason for t in trades]).value_counts().to_dict()
    avg_w = wins.mean() if len(wins) else 0.0
    avg_l = losses.mean() if len(losses) else 0.0
    wr = float((rets > 0).mean())
    exp_ = wr * avg_w + (1 - wr) * avg_l
    return {
        "strategy": name,
        "trades": len(rets),
        "win%": round(wr * 100, 2),
        "avg%": round(float(rets.mean()) * 100, 3),
        "med%": round(float(np.median(rets)) * 100, 3),
        "expectancy%": round(float(exp_) * 100, 3),
        "PF": round(float(wins.sum() / -losses.sum()), 2) if losses.sum() < 0 else None,
        "avg_hold": round(float(np.mean([t.hold_days for t in trades])), 1),
        "stop%": round(reasons.get("stop-loss", 0) / len(rets) * 100, 1),
        "tp%":   round(reasons.get("win-target", 0) / len(rets) * 100, 1),
        "time%": round(reasons.get("time-exit", 0) / len(rets) * 100, 1),
        "fund%": round(reasons.get("fundamentals-exit", 0) / len(rets) * 100, 1),
    }


__all__ = ["Trade", "ROUND_TRIP_COST", "simulate", "summarize_trades"]
