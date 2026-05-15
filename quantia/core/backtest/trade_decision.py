# -*- coding: utf-8 -*-
"""Phase 2 — 交易决策结构标准化与兜底说明。

策略下单时可显式传入 ``reason / decision / indicators / selection`` 解释下单意图，
本模块把这些原始输入归一为可入库与渲染的形态，并在策略未提供时生成可识别的兜底说明。

设计原则（参考开发计划 §3.1 / §6.3）：

- 策略提供的真实原因永远优先，``reason_source = 'strategy'``。
- 兜底说明必须可识别，``reason_source = 'generated'``，渲染时需要明确标注。
- 不试图“补完”策略未提供的指标值，避免事后伪造。
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, List, Optional

REASON_SOURCE_STRATEGY = "strategy"
REASON_SOURCE_DERIVED = "derived"
REASON_SOURCE_GENERATED = "generated"

_GENERATED_BUY_TEMPLATE = (
    "策略触发买入信号，按模拟盘撮合规则成交；该理由由系统根据成交结果生成，非策略显式说明。"
)
_GENERATED_SELL_TEMPLATE = (
    "策略触发卖出/调仓/风控信号，按模拟盘撮合规则成交；该理由由系统根据成交结果生成，非策略显式说明。"
)


def _ensure_str(value, max_len: int = 2000) -> str:
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    return text[:max_len]


def _ensure_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _ensure_list_of_dict(value: Any) -> List[Dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def normalize_rule(rule: Dict[str, Any], sort_order: int = 0) -> Dict[str, Any]:
    """单条规则归一化。仅保留约定字段，避免无关字段污染入库。"""
    return {
        "rule_group": _ensure_str(rule.get("rule_group") or rule.get("group"), 64) or None,
        "rule_name": _ensure_str(rule.get("rule_name") or rule.get("name"), 128) or "rule",
        "indicator_key": _ensure_str(rule.get("indicator_key") or rule.get("indicator"), 64) or None,
        "threshold_expr": _ensure_str(rule.get("threshold_expr") or rule.get("threshold"), 255) or None,
        "threshold_value": rule.get("threshold_value") if rule.get("threshold_value") is not None else rule.get("threshold"),
        "actual_value": rule.get("actual_value") if rule.get("actual_value") is not None else rule.get("actual"),
        "passed": _coerce_passed(rule.get("passed")),
        "weight": _coerce_float(rule.get("weight")),
        "score": _coerce_float(rule.get("score")),
        "note": _ensure_str(rule.get("note"), 500) or None,
        "sort_order": int(sort_order),
    }


def _coerce_passed(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (int, float)):
        return 1 if value else 0
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("1", "true", "pass", "passed", "yes", "y"):
            return 1
        if v in ("0", "false", "fail", "failed", "no", "n"):
            return 0
    return None


def _coerce_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_decision_payload(decision: Any, *, indicators: Any = None, selection: Any = None) -> Dict[str, Any]:
    """归一化策略原始 decision/indicators/selection 输入。

    返回结构：
        {
            'rules': [normalized_rule, ...],
            'indicators': {...},          # 原样，渲染层负责裁剪展示
            'selection': [normalized_stage, ...],
        }
    """
    decision = _ensure_dict(decision)
    raw_rules = _ensure_list_of_dict(decision.get("rules"))
    rules = [normalize_rule(rule, sort_order=idx) for idx, rule in enumerate(raw_rules)]

    raw_indicators = _ensure_dict(indicators if indicators is not None else decision.get("indicators"))
    raw_selection = _ensure_list_of_dict(selection if selection is not None else decision.get("selection"))
    selection_norm = [
        {
            "stage": _ensure_str(item.get("stage"), 64) or "stage",
            "candidate_count_before": _coerce_int(item.get("candidate_count_before")),
            "candidate_count_after": _coerce_int(item.get("candidate_count_after")),
            "rank_value": _coerce_float(item.get("rank_value")),
            "rank_position": _coerce_int(item.get("rank_position")),
            "filter_expr": _ensure_str(item.get("filter_expr"), 255) or None,
            "actual_value": item.get("actual_value"),
            "passed": _coerce_passed(item.get("passed")),
            "note": _ensure_str(item.get("note"), 500) or None,
        }
        for item in raw_selection
    ]

    return {
        "rules": rules,
        "indicators": raw_indicators,
        "selection": selection_norm,
    }


def _coerce_int(value: Any) -> Optional[int]:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def build_generated_reason(direction: str) -> str:
    """旧策略未提供 reason 时的可识别兜底说明。"""
    if direction == "buy":
        return _GENERATED_BUY_TEMPLATE
    if direction == "sell":
        return _GENERATED_SELL_TEMPLATE
    return f"策略触发交易信号({direction})，按模拟盘撮合规则成交；该理由由系统生成，非策略显式说明。"


def resolve_reason(direction: str, raw_reason: Any, *, derived_reason: Any = None) -> Dict[str, str]:
    """返回 ``{'reason': str, 'reason_source': 'strategy'|'derived'|'generated'}``。

    - ``raw_reason`` 由策略显式提供时优先使用，标记 ``strategy``。
    - 否则若 ``derived_reason`` 提供（系统从策略 log/order 参数派生的真实决策上下文），
      使用并标记 ``derived`` —— 文案不再含 "非策略显式说明" 的兜底措辞。
    - 两者都缺失才回落到固定模板，标记 ``generated``。
    """
    text = _ensure_str(raw_reason, 4000).strip()
    if text:
        return {"reason": text, "reason_source": REASON_SOURCE_STRATEGY}
    derived = _ensure_str(derived_reason, 4000).strip()
    if derived:
        return {"reason": derived, "reason_source": REASON_SOURCE_DERIVED}
    return {"reason": build_generated_reason(direction), "reason_source": REASON_SOURCE_GENERATED}


def compute_signal_hash(
    *,
    source_type: str,
    source_id: Any,
    run_id: Any,
    code: str,
    direction: str,
    signal_date: Any,
    requested_amount: Any = None,
    requested_value: Any = None,
) -> str:
    parts = [
        str(source_type or ""),
        str(source_id or ""),
        str(run_id or ""),
        str(code or ""),
        str(direction or ""),
        str(signal_date or ""),
        str(requested_amount if requested_amount is not None else ""),
        str(requested_value if requested_value is not None else ""),
    ]
    raw = "|".join(parts).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def serialize_for_db(value: Any) -> Optional[str]:
    """把 dict/list 序列化为 JSON 字符串供 MySQL JSON 列存储。None 直接返回 None。"""
    if value is None:
        return None
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return json.dumps(str(value), ensure_ascii=False)
