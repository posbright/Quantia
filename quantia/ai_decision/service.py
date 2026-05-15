# -*- coding: utf-8 -*-
"""Phase 4 顶层服务：score_trade + evaluate_ai_gate。

调用流程：
  load_config_for_source -> 若禁用 -> 返回 GATE_NOT_ENABLED
  build_input_summary + compute_input_hash
  render_messages + compute_prompt_hash
  provider.generate -> normalize_ai_payload
  应用 buy_threshold / sell_threshold 决定 gate_result
  写入 cn_stock_trade_ai_score（异常仅 warning）
"""
from __future__ import annotations

import datetime
import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from .config import (
    AIDecisionConfig, ensure_ai_decision_tables, load_config_for_source,
    SCORE_TABLE,
)
from .context_builder import build_input_summary, compute_input_hash
from .prompt_renderer import compute_prompt_hash, render_messages
from .schema import (
    AIDecisionResult, GATE_ERROR, GATE_FALLBACK, GATE_NOT_ENABLED,
    GATE_PASS, GATE_REJECT, STATUS_FAILED, STATUS_SKIPPED, STATUS_SUCCEEDED,
    STATUS_TIMEOUT, normalize_ai_payload,
)


def _make_provider(provider_name: str):
    """工厂：当前仅支持 openai_compatible；未知 provider 抛错。"""
    name = (provider_name or "openai_compatible").lower()
    if name in ("openai", "openai_compatible", "deepseek", "qwen"):
        from .providers.openai_compatible import OpenAICompatibleProvider
        return OpenAICompatibleProvider()
    raise RuntimeError(f"不支持的 provider: {provider_name}")


def _safe_json_loads(text: str) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        # 模型可能回带 ```json ... ``` 代码块；尝试剥离
        stripped = text.strip()
        if stripped.startswith("```"):
            stripped = stripped.strip("`")
            if stripped.startswith("json"):
                stripped = stripped[4:]
            try:
                return json.loads(stripped)
            except Exception:
                return None
        return None


def _apply_gate(result: AIDecisionResult, cfg: AIDecisionConfig, direction: str) -> str:
    """根据评分 / 动作与配置阈值决定 gate_result（不修改 result）。"""
    if not cfg.is_gate():
        return GATE_NOT_ENABLED
    if result.status != STATUS_SUCCEEDED or result.score is None:
        return GATE_FALLBACK if not cfg.fail_closed else GATE_REJECT
    score = float(result.score)
    direction = (direction or "").lower()
    if direction == "buy":
        return GATE_PASS if score >= float(cfg.buy_threshold or 0) else GATE_REJECT
    if direction == "sell":
        # 卖出阈值：低于阈值视为 reject（即不卖出/不减仓提醒）；
        # 默认 sell_threshold=40 → 评分较低时通过卖出/减仓动作。
        return GATE_PASS if score <= float(cfg.sell_threshold or 0) else GATE_REJECT
    return GATE_PASS


def _persist_score_row(
    cfg: AIDecisionConfig, *,
    source_type: str, source_id: int, run_id: Optional[str],
    code: str, name: Optional[str], decision_date, decision_phase: str,
    input_hash: str, prompt_hash: Optional[str],
    input_summary: Dict[str, Any], prompt_messages: List[Dict[str, str]],
    result: AIDecisionResult, model_name: Optional[str],
) -> Optional[int]:
    """写入 ``cn_stock_trade_ai_score``，返回 ai_score_id。

    异常仅 warning，返回 None。
    """
    try:
        ensure_ai_decision_tables()
        import quantia.lib.database as mdb
    except Exception as exc:
        logging.debug("[ai_decision] 跳过持久化: %s", exc)
        return None
    try:
        with mdb.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"INSERT INTO `{SCORE_TABLE}` "
                    "(config_id, config_version, source_type, source_id, run_id, "
                    " strategy_id, strategy_name, code, name, decision_date, decision_phase, "
                    " input_hash, prompt_hash, prompt_version, model_name, "
                    " input_summary, prompt_messages, raw_response, "
                    " score, action, confidence, reason_summary, evidence, risk_flags, "
                    " threshold_result, gate_result, status, latency_ms, error_message) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON DUPLICATE KEY UPDATE "
                    " score=VALUES(score), action=VALUES(action), confidence=VALUES(confidence), "
                    " reason_summary=VALUES(reason_summary), evidence=VALUES(evidence), "
                    " risk_flags=VALUES(risk_flags), threshold_result=VALUES(threshold_result), "
                    " gate_result=VALUES(gate_result), status=VALUES(status), "
                    " latency_ms=VALUES(latency_ms), error_message=VALUES(error_message), "
                    " raw_response=VALUES(raw_response)",
                    (
                        cfg.id, cfg.config_version,
                        source_type, int(source_id or 0), run_id,
                        cfg.strategy_id, None,
                        code, name, decision_date, decision_phase,
                        input_hash, prompt_hash, str(cfg.config_version or ""), model_name,
                        json.dumps(input_summary, ensure_ascii=False, default=str),
                        json.dumps(prompt_messages, ensure_ascii=False, default=str),
                        (result.raw_response or "")[:65000] if result.raw_response else None,
                        result.score, result.action, result.confidence, result.reason_summary,
                        json.dumps(result.evidence, ensure_ascii=False, default=str),
                        json.dumps(result.risk_flags, ensure_ascii=False, default=str),
                        json.dumps(result.threshold_result, ensure_ascii=False, default=str),
                        result.gate_result, result.status, result.latency_ms,
                        (result.error_message or "")[:1000] if result.error_message else None,
                    ),
                )
                cur.execute(
                    f"SELECT id FROM `{SCORE_TABLE}` "
                    "WHERE source_type=%s AND source_id=%s AND run_id<=>%s "
                    "  AND code=%s AND decision_phase=%s AND input_hash=%s LIMIT 1",
                    (source_type, int(source_id or 0), run_id, code, decision_phase, input_hash),
                )
                row = cur.fetchone()
                conn.commit()
                return int(row[0]) if row else None
    except Exception as exc:
        logging.warning("[ai_decision] 持久化评分失败 code=%s: %s", code, exc)
        return None


def score_trade(
    *,
    cfg: AIDecisionConfig,
    source_type: str,
    source_id: int,
    run_id: Optional[str],
    code: str,
    name: Optional[str] = None,
    decision_date,
    decision_phase: str = "pre_buy",
    direction: str = "buy",
    indicators: Optional[Dict[str, Any]] = None,
    selection: Optional[List[Dict[str, Any]]] = None,
    kline_window: Optional[List[Dict[str, Any]]] = None,
    portfolio_snapshot: Optional[Dict[str, Any]] = None,
    market_context: Optional[Dict[str, Any]] = None,
    extra: Optional[Dict[str, Any]] = None,
    provider_factory: Optional[Callable[[str], Any]] = None,
    persist: bool = True,
) -> Dict[str, Any]:
    """主入口：执行 AI 评分并返回 dict。

    返回值键：``ai_score_id``, ``ai_score``, ``ai_action``, ``ai_gate_result``,
    ``status``, ``error_message``, ``reason_summary``, ``evidence``,
    ``risk_flags``, ``input_hash``, ``prompt_hash``。

    任何子步骤异常都会被吞掉，最坏情况下返回 fallback 结果。
    """
    if cfg is None or not cfg.is_enabled():
        return {
            "ai_score_id": None, "ai_score": None, "ai_action": None,
            "ai_gate_result": GATE_NOT_ENABLED, "status": STATUS_SKIPPED,
        }

    # 1) 输入摘要 + hash
    input_summary = build_input_summary(
        code=code, name=name, decision_date=decision_date,
        decision_phase=decision_phase, direction=direction,
        indicators=indicators, selection=selection,
        kline_window=kline_window, portfolio_snapshot=portfolio_snapshot,
        market_context=market_context, extra=extra,
    )
    input_hash = compute_input_hash(input_summary)

    # 2) prompt 渲染 + hash
    messages = render_messages(
        system_prompt=cfg.system_prompt,
        user_prompt_template=cfg.user_prompt_template,
        input_summary=input_summary,
    )
    prompt_hash = compute_prompt_hash(messages)

    # 3) 调用 provider
    factory = provider_factory or _make_provider
    started = time.monotonic()
    result: AIDecisionResult
    try:
        provider = factory(cfg.provider or "openai_compatible")
        raw = provider.generate(
            messages=messages, model_name=cfg.model_name,
            base_url=cfg.base_url, api_key=cfg.resolve_api_key(),
            temperature=float(cfg.temperature or 0.2),
            max_tokens=int(cfg.max_tokens or 2048),
            timeout_seconds=int(cfg.timeout_seconds or 20),
        )
        latency_ms = int((time.monotonic() - started) * 1000)
        parsed = _safe_json_loads(raw)
        if parsed is None:
            result = AIDecisionResult(
                status=STATUS_FAILED, error_message="AI 返回非合法 JSON",
                raw_response=str(raw)[:4000], latency_ms=latency_ms,
            )
        else:
            result = normalize_ai_payload(parsed)
            result.raw_response = str(raw)[:4000]
            result.latency_ms = latency_ms
    except Exception as exc:
        latency_ms = int((time.monotonic() - started) * 1000)
        msg = str(exc)
        is_timeout = "timeout" in msg.lower() or "timed out" in msg.lower()
        result = AIDecisionResult(
            status=STATUS_TIMEOUT if is_timeout else STATUS_FAILED,
            error_message=msg[:1000], latency_ms=latency_ms,
        )

    # 4) 应用 gate
    result.gate_result = _apply_gate(result, cfg, direction)

    # 5) 持久化（持久化失败不影响调用方拿到结果）
    ai_score_id: Optional[int] = None
    if persist:
        ai_score_id = _persist_score_row(
            cfg,
            source_type=source_type, source_id=source_id, run_id=run_id,
            code=code, name=name, decision_date=decision_date,
            decision_phase=decision_phase,
            input_hash=input_hash, prompt_hash=prompt_hash,
            input_summary=input_summary, prompt_messages=messages,
            result=result, model_name=cfg.model_name,
        )

    return {
        "ai_score_id": ai_score_id,
        "ai_score": result.score,
        "ai_action": result.action,
        "ai_gate_result": result.gate_result,
        "status": result.status,
        "error_message": result.error_message,
        "reason_summary": result.reason_summary,
        "evidence": result.evidence,
        "risk_flags": result.risk_flags,
        "confidence": result.confidence,
        "input_hash": input_hash,
        "prompt_hash": prompt_hash,
    }


def evaluate_ai_gate(
    *,
    source_type: str,
    source_id: int,
    direction: str,
    code: str,
    decision_date,
    indicators: Optional[Dict[str, Any]] = None,
    selection: Optional[List[Dict[str, Any]]] = None,
    portfolio_snapshot: Optional[Dict[str, Any]] = None,
    run_id: Optional[str] = None,
    decision_phase: Optional[str] = None,
    name: Optional[str] = None,
    cfg: Optional[AIDecisionConfig] = None,
    provider_factory: Optional[Callable[[str], Any]] = None,
) -> Dict[str, Any]:
    """便捷封装：用于在策略下单点进行 gate 决策。

    cfg 未传入时按 (source_type, source_id) 自动加载；未启用时返回
    not_enabled / 不持久化（与禁用语义一致）。
    """
    cfg = cfg or load_config_for_source(source_type, source_id)
    if cfg is None or not cfg.is_enabled():
        return {
            "ai_score_id": None, "ai_score": None, "ai_action": None,
            "ai_gate_result": GATE_NOT_ENABLED, "status": STATUS_SKIPPED,
        }
    phase = decision_phase or ("pre_buy" if direction == "buy" else "pre_sell")
    return score_trade(
        cfg=cfg, source_type=source_type, source_id=source_id, run_id=run_id,
        code=code, name=name, decision_date=decision_date,
        decision_phase=phase, direction=direction,
        indicators=indicators, selection=selection,
        portfolio_snapshot=portfolio_snapshot,
        provider_factory=provider_factory,
    )
