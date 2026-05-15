# -*- coding: utf-8 -*-
"""AI 决策结果 schema：常量 + 校验/规整工具。

按开发计划 §3.5 / §5.6 要求，AI 输出必须结构化保存：score/action/
confidence/reason_summary/evidence/risk_flags/threshold_result。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# Gate 结果常量
GATE_NOT_ENABLED = "not_enabled"
GATE_PASS = "pass"
GATE_REJECT = "reject"
GATE_FALLBACK = "fallback"
GATE_ERROR = "error"

# 评分行 status 常量
STATUS_PENDING = "pending"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"
STATUS_TIMEOUT = "timeout"

# 合法 action 集合（与文档 §3.5 与表 5.1 ai_action 注释一致）
_VALID_ACTIONS = {"buy", "sell", "hold", "skip", "reduce", "watch"}


class AIDecisionResult:
    """规整后的 AI 评分结果。

    所有字段允许为 None，方便上游在调用失败时仍构造一行带错误信息的结果。
    """

    __slots__ = (
        "score", "action", "confidence", "reason_summary", "evidence",
        "risk_flags", "threshold_result", "raw_response", "status",
        "error_message", "latency_ms", "gate_result",
    )

    def __init__(
        self,
        *,
        score: Optional[float] = None,
        action: Optional[str] = None,
        confidence: Optional[float] = None,
        reason_summary: Optional[str] = None,
        evidence: Optional[List[Any]] = None,
        risk_flags: Optional[List[Any]] = None,
        threshold_result: Optional[Dict[str, Any]] = None,
        raw_response: Optional[str] = None,
        status: str = STATUS_PENDING,
        error_message: Optional[str] = None,
        latency_ms: Optional[int] = None,
        gate_result: str = GATE_NOT_ENABLED,
    ):
        self.score = score
        self.action = action
        self.confidence = confidence
        self.reason_summary = reason_summary
        self.evidence = evidence or []
        self.risk_flags = risk_flags or []
        self.threshold_result = threshold_result or {}
        self.raw_response = raw_response
        self.status = status
        self.error_message = error_message
        self.latency_ms = latency_ms
        self.gate_result = gate_result

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": self.score,
            "action": self.action,
            "confidence": self.confidence,
            "reason_summary": self.reason_summary,
            "evidence": list(self.evidence or []),
            "risk_flags": list(self.risk_flags or []),
            "threshold_result": dict(self.threshold_result or {}),
            "status": self.status,
            "error_message": self.error_message,
            "latency_ms": self.latency_ms,
            "gate_result": self.gate_result,
        }


def _coerce_float(v: Any, lo: Optional[float] = None, hi: Optional[float] = None) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
    except Exception:
        return None
    if lo is not None and f < lo:
        f = lo
    if hi is not None and f > hi:
        f = hi
    return f


def normalize_ai_payload(payload: Any) -> AIDecisionResult:
    """将模型返回的 dict 规整为 ``AIDecisionResult``。

    宽松解析：缺字段或类型不符不抛错，仅保留可用字段；非法 action 落为 None。
    """
    if not isinstance(payload, dict):
        return AIDecisionResult(
            status=STATUS_FAILED,
            error_message="AI 返回非 JSON 对象",
            raw_response=str(payload)[:4000] if payload is not None else None,
        )
    score = _coerce_float(payload.get("score"), 0.0, 100.0)
    action = payload.get("action")
    if isinstance(action, str):
        action = action.strip().lower()
        if action not in _VALID_ACTIONS:
            action = None
    else:
        action = None
    confidence = _coerce_float(payload.get("confidence"), 0.0, 1.0)
    reason_summary = payload.get("reason_summary")
    if isinstance(reason_summary, str):
        reason_summary = reason_summary.strip()[:1000]
    else:
        reason_summary = None

    def _as_list(v):
        if v is None:
            return []
        if isinstance(v, list):
            return v
        return [v]

    evidence = _as_list(payload.get("evidence"))
    risk_flags = _as_list(payload.get("risk_flags"))
    threshold_result = payload.get("threshold_result") if isinstance(payload.get("threshold_result"), dict) else {}

    if score is None and action is None:
        return AIDecisionResult(
            status=STATUS_FAILED,
            error_message="AI 输出缺少 score / action 字段",
            evidence=evidence, risk_flags=risk_flags,
            threshold_result=threshold_result,
            raw_response=None,
        )
    return AIDecisionResult(
        score=score, action=action, confidence=confidence,
        reason_summary=reason_summary, evidence=evidence,
        risk_flags=risk_flags, threshold_result=threshold_result,
        status=STATUS_SUCCEEDED,
    )
