#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 4：AI 综合评分单元测试。

覆盖：
- 配置默认值 / is_enabled / is_gate / api_key 引用环境变量
- 输入摘要剔除未来 K 线（§14.6）
- prompt 渲染稳定 hash
- AI 输出 JSON 规整（合法 / 缺字段 / 非法 action / 字符串 / 代码块包裹）
- score_trade：禁用、启用-非 gate（仅留痕）、gate-pass、gate-reject、超时、fail_closed
- 通知模板 AI 块：缺省时不展示 / 提供时展示评分 + 证据 + 风险
- 表 DDL 函数被调用（DB 不可用时静默）
"""
import datetime
import json
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from quantia.ai_decision import (
    AIDecisionConfig, build_input_summary, compute_input_hash,
    compute_prompt_hash, render_messages,
)
from quantia.ai_decision.schema import (
    AIDecisionResult, GATE_FALLBACK, GATE_NOT_ENABLED, GATE_PASS, GATE_REJECT,
    STATUS_FAILED, STATUS_SUCCEEDED, STATUS_TIMEOUT, normalize_ai_payload,
)
from quantia.ai_decision.service import (
    _apply_gate, _safe_json_loads, score_trade,
)
from quantia.notification.templates import build_trade_markdown


# ---------- 配置 ----------

def test_config_defaults_and_helpers(monkeypatch):
    cfg = AIDecisionConfig()
    assert cfg.enabled == 0
    assert cfg.is_enabled() is False
    assert cfg.is_gate() is False
    assert cfg.provider == "openai_compatible"
    assert cfg.timeout_seconds == 20
    assert cfg.buy_threshold == 70.0

    cfg2 = AIDecisionConfig(enabled=1, enabled_as_gate=1, api_key_ref="MY_KEY")
    monkeypatch.setenv("MY_KEY", "secret-value")
    assert cfg2.is_enabled() is True
    assert cfg2.is_gate() is True
    assert cfg2.resolve_api_key() == "secret-value"
    # to_dict 不应包含解析后的密钥值
    assert "secret-value" not in json.dumps(cfg2.to_dict())


# ---------- 输入摘要 + hash ----------

def test_input_summary_drops_future_kline():
    """§14.6: 决策日期之后的 K 线不允许进入 AI 输入。"""
    summary = build_input_summary(
        code="600016", name="民生银行",
        decision_date="2026-05-07", direction="buy",
        kline_window=[
            {"date": "2026-05-05", "close": 3.70},
            {"date": "2026-05-06", "close": 3.72},
            {"date": "2026-05-07", "close": 3.74},
            {"date": "2026-05-08", "close": 3.99},  # 未来，应被剔除
            {"date": "2026-05-09", "close": 4.10},
        ],
    )
    dates = [r["date"] for r in summary["kline_window"]]
    assert "2026-05-08" not in dates
    assert "2026-05-09" not in dates
    assert summary["kline_window_size"] == 3


def test_input_hash_stable_for_equivalent_input():
    s1 = build_input_summary(code="600016", decision_date="2026-05-07", direction="buy",
                             indicators={"close": 3.74, "ma5": 3.71})
    s2 = build_input_summary(code="600016", decision_date="2026-05-07", direction="buy",
                             indicators={"ma5": 3.71, "close": 3.74})
    assert compute_input_hash(s1) == compute_input_hash(s2)


# ---------- prompt 渲染 ----------

def test_render_messages_uses_default_when_template_empty():
    summary = {"code": "600016", "name": "民生", "decision_date": "2026-05-07",
               "decision_phase": "pre_buy", "direction": "buy"}
    msgs = render_messages(system_prompt=None, user_prompt_template=None, input_summary=summary)
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    assert "600016" in msgs[1]["content"]


def test_render_messages_substitutes_placeholders_and_keeps_unknown():
    summary = {"code": "600016", "indicators": {"close": 3.74}}
    msgs = render_messages(
        system_prompt="sys", user_prompt_template="code={{ code }} ind={{ indicators }} miss={{ missing }}",
        input_summary=summary,
    )
    user = msgs[1]["content"]
    assert "code=600016" in user
    assert '"close": 3.74' in user
    assert "{{ missing }}" in user  # 未知占位符保留


def test_compute_prompt_hash_stable():
    msgs = [{"role": "system", "content": "a"}, {"role": "user", "content": "b"}]
    assert compute_prompt_hash(msgs) == compute_prompt_hash(list(msgs))


# ---------- normalize_ai_payload ----------

def test_normalize_valid_payload():
    r = normalize_ai_payload({
        "score": 82.5, "action": "buy", "confidence": 0.76,
        "reason_summary": "BOLL 下轨反弹",
        "evidence": ["close=3.74<=lower*1.02"],
        "risk_flags": ["MA60 偏弱"],
        "threshold_result": {"buy_threshold": 70, "passed": True},
    })
    assert r.status == STATUS_SUCCEEDED
    assert r.score == 82.5
    assert r.action == "buy"
    assert r.confidence == 0.76
    assert r.evidence and r.risk_flags


def test_normalize_clamps_score_and_confidence():
    r = normalize_ai_payload({"score": 150, "confidence": 5, "action": "BUY"})
    assert r.score == 100.0
    assert r.confidence == 1.0
    assert r.action == "buy"  # 大小写归一


def test_normalize_rejects_illegal_action():
    r = normalize_ai_payload({"score": 50, "action": "moon"})
    assert r.action is None


def test_normalize_non_dict_returns_failed():
    r = normalize_ai_payload("hello")
    assert r.status == STATUS_FAILED
    assert "非 JSON" in r.error_message


def test_normalize_missing_score_and_action_returns_failed():
    r = normalize_ai_payload({"reason_summary": "x"})
    assert r.status == STATUS_FAILED


def test_safe_json_loads_handles_code_fence():
    obj = _safe_json_loads('```json\n{"score": 70, "action": "buy"}\n```')
    assert obj == {"score": 70, "action": "buy"}


# ---------- gate 决策 ----------

def _result(score=None, status=STATUS_SUCCEEDED):
    return AIDecisionResult(score=score, status=status)


def test_apply_gate_disabled_returns_not_enabled():
    cfg = AIDecisionConfig(enabled=1, enabled_as_gate=0)
    assert _apply_gate(_result(score=10), cfg, "buy") == GATE_NOT_ENABLED


def test_apply_gate_buy_pass_and_reject():
    cfg = AIDecisionConfig(enabled=1, enabled_as_gate=1, buy_threshold=70)
    assert _apply_gate(_result(score=82), cfg, "buy") == GATE_PASS
    assert _apply_gate(_result(score=50), cfg, "buy") == GATE_REJECT


def test_apply_gate_sell_low_score_passes_reduce():
    cfg = AIDecisionConfig(enabled=1, enabled_as_gate=1, sell_threshold=40)
    assert _apply_gate(_result(score=30), cfg, "sell") == GATE_PASS
    assert _apply_gate(_result(score=80), cfg, "sell") == GATE_REJECT


def test_apply_gate_failed_with_fail_closed_rejects():
    cfg_open = AIDecisionConfig(enabled=1, enabled_as_gate=1, fail_closed=0)
    cfg_closed = AIDecisionConfig(enabled=1, enabled_as_gate=1, fail_closed=1)
    failed = AIDecisionResult(status=STATUS_FAILED, score=None)
    assert _apply_gate(failed, cfg_open, "buy") == GATE_FALLBACK
    assert _apply_gate(failed, cfg_closed, "buy") == GATE_REJECT


# ---------- score_trade 端到端（mock provider + 持久化） ----------

class _StubProvider:
    """可参数化的 fake provider。"""
    def __init__(self, response=None, raise_exc=None):
        self.response = response
        self.raise_exc = raise_exc
        self.calls = []

    def generate(self, **kw):
        self.calls.append(kw)
        if self.raise_exc:
            raise self.raise_exc
        return self.response, {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None}


@pytest.fixture
def _no_persist():
    """禁用 _persist_score_row，避免触发 DB。"""
    with patch("quantia.ai_decision.service._persist_score_row", return_value=None):
        yield


def test_score_trade_disabled_returns_skipped(_no_persist):
    cfg = AIDecisionConfig(enabled=0)
    out = score_trade(
        cfg=cfg, source_type="paper", source_id=1, run_id="r1",
        code="600016", decision_date="2026-05-07", direction="buy",
    )
    assert out["status"] == "skipped"
    assert out["ai_gate_result"] == GATE_NOT_ENABLED
    assert out["ai_score"] is None


def test_score_trade_enabled_no_gate_persists_only(_no_persist):
    cfg = AIDecisionConfig(enabled=1, enabled_as_gate=0,
                           model_name="m", base_url="http://x", api_key_ref="K")
    stub = _StubProvider(response=json.dumps({"score": 75, "action": "buy"}))
    with patch.dict("os.environ", {"K": "kkk"}):
        out = score_trade(
            cfg=cfg, source_type="paper", source_id=1, run_id="r1",
            code="600016", decision_date="2026-05-07", direction="buy",
            provider_factory=lambda name: stub,
        )
    assert out["status"] == STATUS_SUCCEEDED
    assert out["ai_score"] == 75.0
    assert out["ai_action"] == "buy"
    # 非 gate 模式 → not_enabled，绝不影响交易结果
    assert out["ai_gate_result"] == GATE_NOT_ENABLED
    assert len(stub.calls) == 1


def test_score_trade_gate_buy_pass(_no_persist):
    cfg = AIDecisionConfig(enabled=1, enabled_as_gate=1, buy_threshold=70,
                           model_name="m", base_url="http://x", api_key_ref="K")
    stub = _StubProvider(response=json.dumps({"score": 82, "action": "buy"}))
    with patch.dict("os.environ", {"K": "kkk"}):
        out = score_trade(
            cfg=cfg, source_type="paper", source_id=1, run_id="r1",
            code="600016", decision_date="2026-05-07", direction="buy",
            provider_factory=lambda name: stub,
        )
    assert out["ai_gate_result"] == GATE_PASS


def test_score_trade_gate_buy_reject_below_threshold(_no_persist):
    cfg = AIDecisionConfig(enabled=1, enabled_as_gate=1, buy_threshold=70,
                           model_name="m", base_url="http://x", api_key_ref="K")
    stub = _StubProvider(response=json.dumps({"score": 40, "action": "skip"}))
    with patch.dict("os.environ", {"K": "kkk"}):
        out = score_trade(
            cfg=cfg, source_type="paper", source_id=1, run_id="r1",
            code="600016", decision_date="2026-05-07", direction="buy",
            provider_factory=lambda name: stub,
        )
    assert out["ai_gate_result"] == GATE_REJECT
    # 即便 gate=reject，策略原始信号仍能被上游持久化（非本测试关心）。
    assert out["ai_score"] == 40.0


def test_score_trade_timeout_with_fail_closed_rejects(_no_persist):
    cfg = AIDecisionConfig(enabled=1, enabled_as_gate=1, fail_closed=1,
                           model_name="m", base_url="http://x", api_key_ref="K")
    stub = _StubProvider(raise_exc=TimeoutError("connection timed out"))
    with patch.dict("os.environ", {"K": "kkk"}):
        out = score_trade(
            cfg=cfg, source_type="paper", source_id=1, run_id="r1",
            code="600016", decision_date="2026-05-07", direction="buy",
            provider_factory=lambda name: stub,
        )
    assert out["status"] == STATUS_TIMEOUT
    assert out["ai_gate_result"] == GATE_REJECT


def test_score_trade_timeout_with_open_gate_falls_back(_no_persist):
    cfg = AIDecisionConfig(enabled=1, enabled_as_gate=1, fail_closed=0,
                           model_name="m", base_url="http://x", api_key_ref="K")
    stub = _StubProvider(raise_exc=TimeoutError("timed out"))
    with patch.dict("os.environ", {"K": "kkk"}):
        out = score_trade(
            cfg=cfg, source_type="paper", source_id=1, run_id="r1",
            code="600016", decision_date="2026-05-07", direction="buy",
            provider_factory=lambda name: stub,
        )
    assert out["ai_gate_result"] == GATE_FALLBACK


def test_score_trade_invalid_json_response_falls_back(_no_persist):
    cfg = AIDecisionConfig(enabled=1, enabled_as_gate=1, fail_closed=0,
                           model_name="m", base_url="http://x", api_key_ref="K")
    stub = _StubProvider(response="not-json-at-all")
    with patch.dict("os.environ", {"K": "kkk"}):
        out = score_trade(
            cfg=cfg, source_type="paper", source_id=1, run_id="r1",
            code="600016", decision_date="2026-05-07", direction="buy",
            provider_factory=lambda name: stub,
        )
    assert out["status"] == STATUS_FAILED
    assert out["ai_gate_result"] == GATE_FALLBACK


# ---------- 通知模板 AI 块 ----------

def test_template_without_ai_fields_omits_block():
    md = build_trade_markdown({
        "code": "600016", "name": "民生", "direction": "buy",
        "price": 3.74, "amount": 100, "value": 374, "paper_id": 1,
        "trade_date": "2026-05-07",
    })["markdown"]
    assert "AI 综合研判" not in md


def test_template_with_ai_fields_renders_summary():
    md = build_trade_markdown({
        "code": "600016", "name": "民生", "direction": "buy",
        "price": 3.74, "amount": 100, "value": 374, "paper_id": 1,
        "trade_date": "2026-05-07",
        "ai_score": 82.5, "ai_action": "buy", "ai_gate_result": "pass",
        "ai_confidence": 0.76, "ai_reason_summary": "BOLL 下轨附近反弹",
        "ai_evidence": ["close=3.74<=lower*1.02", "MA5 上穿 MA20"],
        "ai_risk_flags": ["MA60 仍偏弱"],
    })["markdown"]
    assert "AI 综合研判（仅供参考）" in md
    assert "评分 82.50/100" in md
    assert "建议 buy" in md
    assert "Gate 通过" in md
    assert "BOLL 下轨附近反弹" in md
    assert "close=3.74<=lower*1.02" in md
    assert "MA60 仍偏弱" in md
    # 摘要永远在详情之前（§7）
    assert md.index("摘要") < md.index("AI 综合研判")
    assert md.index("AI 综合研判") < md.index("详情")


def test_template_renders_gate_reject_label():
    md = build_trade_markdown({
        "code": "600016", "name": "民生", "direction": "buy",
        "price": 3.74, "amount": 100, "value": 374, "paper_id": 1,
        "trade_date": "2026-05-07",
        "ai_score": 35, "ai_action": "skip", "ai_gate_result": "reject",
    })["markdown"]
    assert "Gate 拒绝" in md


# ---------- DDL 调用安全性 ----------

def test_ensure_tables_silent_on_db_failure():
    from quantia.ai_decision import ensure_ai_decision_tables
    # 模拟 DB 不可用：checkTableIsExist 抛出 → 不应抛出
    with patch("quantia.lib.database.checkTableIsExist", side_effect=Exception("no db")):
        ensure_ai_decision_tables()  # should not raise


def test_load_config_no_table_returns_none():
    from quantia.ai_decision import load_config_for_source
    with patch("quantia.lib.database.checkTableIsExist", return_value=False):
        cfg = load_config_for_source("paper", 1)
    assert cfg is None
