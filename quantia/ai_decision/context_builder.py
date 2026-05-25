# -*- coding: utf-8 -*-
"""AI 输入数据包构造：仅包含决策时点可见的数据。

按开发计划 §3.5 / §14.6：
- 不允许把交易日之后的 K 线、财务数据、指数数据带入。
- 输入摘要存哈希 + 关键切片，避免数据库体积爆炸。
"""
from __future__ import annotations

import datetime
import hashlib
import json
from typing import Any, Dict, Optional


def _trim_kline_window(kline_window: Any, decision_date: Any, max_rows: int = 30) -> list:
    """K 线窗口仅保留 ``decision_date`` 当日及之前的最近 ``max_rows`` 行。

    输入应为 list[dict]（每行至少含 ``date``）。无法解析时返回 [] 而不抛错。
    """
    if not kline_window or not isinstance(kline_window, list):
        return []
    boundary = _to_date(decision_date)
    cleaned = []
    for row in kline_window:
        if not isinstance(row, dict):
            continue
        d = _to_date(row.get("date"))
        if boundary is not None and d is not None and d > boundary:
            continue  # 屏蔽未来数据
        cleaned.append({k: row.get(k) for k in ("date", "open", "high", "low", "close", "volume", "amount") if k in row})
    return cleaned[-max_rows:]


def _to_date(v):
    if v is None:
        return None
    if isinstance(v, datetime.datetime):
        return v.date()
    if isinstance(v, datetime.date):
        return v
    if isinstance(v, str):
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.datetime.strptime(v[:len(fmt) - 2], fmt).date() if False else datetime.datetime.strptime(v[:10], "%Y-%m-%d").date()
            except Exception:
                continue
    return None


def build_input_summary(
    *,
    code: str,
    name: Optional[str] = None,
    decision_date: Any,
    decision_phase: str = "pre_buy",
    direction: str = "buy",
    indicators: Optional[Dict[str, Any]] = None,
    selection: Optional[list] = None,
    kline_window: Optional[list] = None,
    portfolio_snapshot: Optional[Dict[str, Any]] = None,
    market_context: Optional[Dict[str, Any]] = None,
    event_context: Optional[Dict[str, Any]] = None,
    extra: Optional[Dict[str, Any]] = None,
    kline_max_rows: int = 30,
) -> Dict[str, Any]:
    """构造可序列化输入摘要。仅保留决策时点可见数据。"""
    summary: Dict[str, Any] = {
        "code": code,
        "name": name,
        "decision_date": str(decision_date) if decision_date is not None else None,
        "decision_phase": decision_phase,
        "direction": direction,
    }
    if indicators:
        summary["indicators"] = indicators
    if selection:
        summary["selection"] = selection
    if kline_window:
        summary["kline_window"] = _trim_kline_window(kline_window, decision_date, kline_max_rows)
        summary["kline_window_size"] = len(summary["kline_window"])
    if portfolio_snapshot:
        # 不放置 API key、券商账号等敏感字段；上游传入时不要附带。
        summary["portfolio"] = {
            k: portfolio_snapshot.get(k)
            for k in ("available_cash", "total_value", "current_position",
                      "target_percent", "max_position", "max_daily_trades",
                      "drawdown")
            if k in (portfolio_snapshot or {})
        }
    if market_context:
        summary["market"] = market_context
    if event_context:
        summary["event_context"] = event_context
    if extra:
        summary["extra"] = extra
    return summary


def compute_input_hash(input_summary: Dict[str, Any]) -> str:
    """对 input_summary 计算稳定哈希，用于唯一键 + 复现。"""
    raw = json.dumps(input_summary, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
