# -*- coding: utf-8 -*-
"""Phase 4: AI 综合评分模块。

模块边界（与开发计划 §3.5 / §4.1 / §14 严格对齐）：

- 默认 ``enabled=0``：不调用任何外部模型，零成本零风险。
- ``enabled=1, enabled_as_gate=0``：仅留痕 + 通知摘要展示，**不改变交易结果**。
- ``enabled=1, enabled_as_gate=1``：作为可选闸门；评分低于
  ``buy_threshold`` 时拒绝买入；卖出阈值用于触发减仓提醒。
- ``fail_closed=1``：AI 超时 / 解析失败时拒绝放行；默认 ``fail_closed=0``
  时放行，保护策略原始信号。

安全：``api_key`` 不进入数据库与日志，仅通过 ``api_key_ref`` 引用环境变量。
"""

from .schema import (
    AIDecisionResult,
    GATE_NOT_ENABLED, GATE_PASS, GATE_REJECT, GATE_FALLBACK, GATE_ERROR,
    STATUS_SUCCEEDED, STATUS_FAILED, STATUS_TIMEOUT, STATUS_SKIPPED,
)
from .config import (
    AIDecisionConfig, load_config_for_source, ensure_ai_decision_tables,
    DEFAULT_API_KEY_ENV, CONFIG_TABLE, SCORE_TABLE,
)
from .context_builder import build_input_summary, compute_input_hash
from .prompt_renderer import render_messages, compute_prompt_hash
from .service import score_trade, evaluate_ai_gate

__all__ = [
    "AIDecisionResult",
    "AIDecisionConfig", "load_config_for_source", "ensure_ai_decision_tables",
    "build_input_summary", "compute_input_hash",
    "render_messages", "compute_prompt_hash",
    "score_trade", "evaluate_ai_gate",
    "GATE_NOT_ENABLED", "GATE_PASS", "GATE_REJECT", "GATE_FALLBACK", "GATE_ERROR",
    "STATUS_SUCCEEDED", "STATUS_FAILED", "STATUS_TIMEOUT", "STATUS_SKIPPED",
    "DEFAULT_API_KEY_ENV", "CONFIG_TABLE", "SCORE_TABLE",
]
