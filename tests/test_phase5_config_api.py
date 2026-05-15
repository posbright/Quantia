#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 5 验收测试：通知配置 CRUD / 测试发送 / 重试 + AI 决策配置 CRUD。

聚焦：
- 输入校验（拒绝写入密钥明文 / 非法 channel / 范围外数值）
- 响应永不回显密钥明文（只返回 *_env / api_key_ref + is_configured 布尔）
- 保存自动 +1 ``config_version``
- 测试发送在通知未启用时返回 ``skipped``，不抛异常
- 单事件重试在事件不存在时返回 ok=False，不影响其他事件
"""
from __future__ import annotations

import datetime
import os
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import patch

import pytest

from quantia.web import notificationConfigHandler as nch
from quantia.web import aiDecisionConfigHandler as ach


# ─────────── In-memory fake DB ───────────

class _FakeMDB:
    def __init__(self):
        self.tables: Dict[str, List[Dict[str, Any]]] = {
            "cn_stock_notification_config": [],
            "cn_stock_notification_event": [],
            "cn_stock_ai_decision_config": [],
        }
        self._auto_id = {k: 0 for k in self.tables}
        self._existing = set(self.tables.keys())

    # mimic quantia.lib.database surface
    def checkTableIsExist(self, name):
        return name in self._existing

    def executeSql(self, sql, params=()):
        # Only handle the operations Phase 5 handlers issue; other DDL is ignored.
        s = sql.strip().lower()
        if s.startswith("create table"):
            return None
        if s.startswith("alter table"):
            return None
        if s.startswith("delete from `cn_stock_notification_config`"):
            cid = int(params[0])
            self.tables["cn_stock_notification_config"] = [
                r for r in self.tables["cn_stock_notification_config"] if r["id"] != cid
            ]
            return None
        if s.startswith("delete from `cn_stock_ai_decision_config`"):
            cid = int(params[0])
            self.tables["cn_stock_ai_decision_config"] = [
                r for r in self.tables["cn_stock_ai_decision_config"] if r["id"] != cid
            ]
            return None
        if s.startswith("update `cn_stock_notification_config`"):
            (paper_id, channel, event_type, enabled, webhook_env, secret_env,
             summary_config, detail_config, modified_by, cid) = params
            for r in self.tables["cn_stock_notification_config"]:
                if r["id"] == cid:
                    r.update({
                        "paper_id": paper_id, "channel": channel, "event_type": event_type,
                        "enabled": enabled, "webhook_env": webhook_env, "secret_env": secret_env,
                        "summary_config": summary_config, "detail_config": detail_config,
                        "modified_by": modified_by,
                        "config_version": (r.get("config_version") or 1) + 1,
                        "updated_at": datetime.datetime.now(),
                    })
            return None
        if s.startswith("update `cn_stock_ai_decision_config`"):
            # see column order in handler save_config UPDATE
            keys = [
                "name", "enabled", "source_type", "source_id", "strategy_id",
                "provider", "model_name", "base_url", "api_key_ref",
                "system_prompt", "user_prompt_template", "output_schema", "tool_config",
                "temperature", "max_tokens", "timeout_seconds", "retry_count",
                "enabled_as_gate", "fail_closed",
                "buy_threshold", "sell_threshold", "modified_by",
            ]
            cid = params[-1]
            kv = dict(zip(keys, params[:-1]))
            for r in self.tables["cn_stock_ai_decision_config"]:
                if r["id"] == cid:
                    r.update(kv)
                    r["config_version"] = (r.get("config_version") or 1) + 1
                    r["updated_at"] = datetime.datetime.now()
            return None
        if s.startswith("update `cn_stock_notification_event`"):
            eid = int(params[-1])
            for r in self.tables["cn_stock_notification_event"]:
                if r["id"] == eid:
                    r["status"] = "pending"
                    r["next_retry_at"] = None
            return None
        return None

    def executeSqlFetch(self, sql, params=()):
        s = sql.strip().lower()
        if "information_schema.columns" in s:
            return [(1,)]  # always claim column exists
        if s.startswith("select id, paper_id, channel, event_type, enabled,"):
            rows = self.tables["cn_stock_notification_config"]
            return [_dict_to_row_notif(r) for r in rows]
        if s.startswith("select id, name, enabled, source_type"):
            rows = self.tables["cn_stock_ai_decision_config"]
            return [_dict_to_row_ai(r) for r in rows]
        if s.startswith("select id, status, retry_count from `cn_stock_notification_event`"):
            eid = int(params[0])
            for r in self.tables["cn_stock_notification_event"]:
                if r["id"] == eid:
                    return [(r["id"], r.get("status", "pending"), r.get("retry_count", 0))]
            return []
        if s.startswith("select status, error_message from `cn_stock_notification_event`"):
            eid = int(params[0])
            for r in self.tables["cn_stock_notification_event"]:
                if r["id"] == eid:
                    return [(r.get("status", "pending"), r.get("error_message", ""))]
            return []
        if s.startswith("select id, paper_id, event_type, payload_json"):
            return []
        return []

    # context manager for get_connection
    class _Cur:
        def __init__(self, parent): self.parent = parent; self._last = None
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, sql, params=()):
            s = sql.strip().lower()
            if s.startswith("insert into `cn_stock_notification_config`"):
                self.parent._auto_id["cn_stock_notification_config"] += 1
                new_id = self.parent._auto_id["cn_stock_notification_config"]
                (paper_id, channel, event_type, enabled, webhook_env, secret_env,
                 summary_config, detail_config, modified_by) = params
                self.parent.tables["cn_stock_notification_config"].append({
                    "id": new_id, "paper_id": paper_id, "channel": channel,
                    "event_type": event_type, "enabled": enabled,
                    "webhook_env": webhook_env, "secret_env": secret_env,
                    "summary_config": summary_config, "detail_config": detail_config,
                    "config_version": 1,
                    "modified_by": modified_by,
                    "created_at": datetime.datetime.now(),
                    "updated_at": datetime.datetime.now(),
                })
                self._last = new_id
            elif s.startswith("insert into `cn_stock_ai_decision_config`"):
                self.parent._auto_id["cn_stock_ai_decision_config"] += 1
                new_id = self.parent._auto_id["cn_stock_ai_decision_config"]
                keys = [
                    "name", "enabled", "source_type", "source_id", "strategy_id",
                    "provider", "model_name", "base_url", "api_key_ref",
                    "system_prompt", "user_prompt_template", "output_schema", "tool_config",
                    "temperature", "max_tokens", "timeout_seconds", "retry_count",
                    "enabled_as_gate", "fail_closed",
                    "buy_threshold", "sell_threshold", "modified_by",
                ]
                kv = dict(zip(keys, params))
                kv["id"] = new_id
                kv["config_version"] = 1
                kv["created_at"] = datetime.datetime.now()
                kv["updated_at"] = datetime.datetime.now()
                self.parent.tables["cn_stock_ai_decision_config"].append(kv)
                self._last = new_id
            elif s.startswith("select last_insert_id"):
                pass
            return None
        def fetchone(self):
            return (self._last,) if self._last is not None else None

    class _Conn:
        def __init__(self, parent): self.parent = parent
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def cursor(self): return _FakeMDB._Cur(self.parent)
        def commit(self): pass

    def get_connection(self):
        return _FakeMDB._Conn(self)


def _dict_to_row_notif(r):
    return (
        r["id"], r.get("paper_id"), r.get("channel"), r.get("event_type"),
        r.get("enabled", 0), r.get("webhook_env"), r.get("secret_env"),
        r.get("summary_config"), r.get("detail_config"),
        r.get("config_version", 1), r.get("modified_by"),
        r.get("created_at"), r.get("updated_at"),
    )


def _dict_to_row_ai(r):
    return (
        r["id"], r.get("name"), r.get("enabled", 0), r.get("source_type"),
        r.get("source_id"), r.get("strategy_id"),
        r.get("provider"), r.get("model_name"), r.get("base_url"), r.get("api_key_ref"),
        r.get("system_prompt"), r.get("user_prompt_template"),
        r.get("output_schema"), r.get("tool_config"),
        r.get("temperature", 0.2), r.get("max_tokens", 2048),
        r.get("timeout_seconds", 20), r.get("retry_count", 1),
        r.get("enabled_as_gate", 0), r.get("fail_closed", 0),
        r.get("buy_threshold", 70.0), r.get("sell_threshold", 40.0),
        r.get("config_version", 1), r.get("modified_by"),
        r.get("created_at"), r.get("updated_at"),
    )


@pytest.fixture
def fake_db(monkeypatch):
    fake = _FakeMDB()
    import quantia.lib.database as mdb
    monkeypatch.setattr(mdb, "checkTableIsExist", fake.checkTableIsExist)
    monkeypatch.setattr(mdb, "executeSql", fake.executeSql)
    monkeypatch.setattr(mdb, "executeSqlFetch", fake.executeSqlFetch)
    monkeypatch.setattr(mdb, "get_connection", fake.get_connection)
    # Also patch the lazy-imported notification.service references
    import quantia.notification.service as nsvc
    monkeypatch.setattr(nsvc, "ensure_notification_tables", lambda: None)
    return fake


# ─────────────── Notification config tests ───────────────


def test_save_notification_config_inserts_with_version_1(fake_db):
    cfg = nch.save_config({
        "paper_id": 7, "channel": "dingtalk", "event_type": "paper_trade",
        "enabled": True,
        "webhook_env": "QUANTIA_DINGTALK_WEBHOOK",
        "secret_env": "QUANTIA_DINGTALK_SECRET",
        "summary_config": {"fields": ["direction", "code", "ai_score"]},
        "detail_config": {"max_rules": 5},
    })
    assert cfg["id"] == 1
    assert cfg["channel"] == "dingtalk"
    assert cfg["enabled"] is True
    assert cfg["config_version"] == 1
    assert cfg["webhook_env"] == "QUANTIA_DINGTALK_WEBHOOK"
    # 安全：响应不含 webhook URL / secret 明文
    assert "webhook_url" not in cfg and "webhook" not in cfg
    assert "secret" not in cfg


def test_save_notification_config_update_bumps_version(fake_db):
    cfg = nch.save_config({"channel": "dingtalk", "event_type": "paper_trade",
                           "enabled": True, "webhook_env": "FOO"})
    assert cfg["config_version"] == 1
    cfg2 = nch.save_config({"id": cfg["id"], "channel": "dingtalk",
                            "event_type": "paper_trade", "enabled": False,
                            "webhook_env": "FOO"})
    assert cfg2["config_version"] == 2
    assert cfg2["enabled"] is False


def test_save_notification_config_rejects_webhook_url_field(fake_db):
    with pytest.raises(ValueError, match="webhook_url"):
        nch.save_config({"channel": "dingtalk", "event_type": "paper_trade",
                         "enabled": True,
                         "webhook_url": "https://oapi.dingtalk.com/robot/send?xxx"})


def test_save_notification_config_rejects_secret_plaintext(fake_db):
    with pytest.raises(ValueError, match="secret"):
        nch.save_config({"channel": "dingtalk", "event_type": "paper_trade",
                         "secret": "SECxxx"})


def test_save_notification_config_rejects_url_in_env_field(fake_db):
    with pytest.raises(ValueError, match="环境变量名|URL"):
        nch.save_config({"channel": "dingtalk", "event_type": "paper_trade",
                         "webhook_env": "https://oapi.dingtalk.com/robot/send"})


def test_save_notification_config_rejects_secret_in_secret_env(fake_db):
    # secret_env 与 webhook_env 同样必须只接受环境变量名
    with pytest.raises(ValueError, match="secret_env"):
        nch.save_config({"channel": "dingtalk", "event_type": "paper_trade",
                         "secret_env": "https://example.com/?token=abc"})
    long_sec = "SEC" + "a" * 60
    with pytest.raises(ValueError, match="secret_env"):
        nch.save_config({"channel": "dingtalk", "event_type": "paper_trade",
                         "secret_env": long_sec})
    # 合法变量名应放行（包含 SEC 前缀但短）
    ok = nch.save_config({"channel": "dingtalk", "event_type": "paper_trade",
                          "enabled": True, "webhook_env": "FOO",
                          "secret_env": "SEC_REF"})
    assert ok["secret_env"] == "SEC_REF"


def test_save_notification_config_rejects_invalid_channel(fake_db):
    with pytest.raises(ValueError, match="channel"):
        nch.save_config({"channel": "wechat", "event_type": "paper_trade"})


def test_save_notification_config_rejects_invalid_event_type(fake_db):
    with pytest.raises(ValueError, match="event_type"):
        nch.save_config({"channel": "dingtalk", "event_type": "rocket_launch"})


def test_list_and_get_notification_config(fake_db):
    a = nch.save_config({"channel": "dingtalk", "event_type": "paper_trade",
                         "enabled": True, "webhook_env": "FOO"})
    nch.save_config({"channel": "dingtalk", "event_type": "run_failed",
                     "enabled": False, "webhook_env": "BAR"})
    rows = nch.list_configs(channel="dingtalk")
    assert len(rows) == 2
    detail = nch.get_config(a["id"])
    assert detail["webhook_env"] == "FOO"


def test_delete_notification_config(fake_db):
    a = nch.save_config({"channel": "dingtalk", "event_type": "paper_trade",
                         "enabled": True, "webhook_env": "FOO"})
    nch.delete_config(a["id"])
    assert nch.get_config(a["id"]) is None


def test_webhook_is_configured_reflects_env(fake_db, monkeypatch):
    monkeypatch.setenv("MY_WEBHOOK_VAR", "https://example.com/hook")
    a = nch.save_config({"channel": "dingtalk", "event_type": "paper_trade",
                         "enabled": True, "webhook_env": "MY_WEBHOOK_VAR"})
    assert a["webhook_is_configured"] is True
    monkeypatch.delenv("MY_WEBHOOK_VAR", raising=False)
    a2 = nch.get_config(a["id"])
    assert a2["webhook_is_configured"] is False


def test_test_send_skips_when_disabled(fake_db, monkeypatch):
    # No env vars set → _load_config returns enabled=False
    monkeypatch.delenv("QUANTIA_DINGTALK_WEBHOOK", raising=False)
    monkeypatch.delenv("QUANTIA_DINGTALK_SECRET", raising=False)
    result = nch.send_test_message(paper_id=7, channel="dingtalk")
    assert result["ok"] is False
    assert result["status"] == "skipped"
    assert "webhook" in result["error"].lower() or "未启用" in result["error"]


def test_test_send_unsupported_channel_returns_skipped(fake_db):
    result = nch.send_test_message(paper_id=7, channel="wecom")
    assert result["ok"] is False and result["status"] == "skipped"


def test_retry_event_returns_error_when_event_missing(fake_db):
    result = nch.retry_event(99999)
    assert result["ok"] is False
    assert "不存在" in result["error"]


# ─────────────── AI decision config tests ───────────────


def test_save_ai_config_inserts_with_version_1(fake_db):
    cfg = ach.save_config({
        "name": "默认模拟盘 Pre-Buy",
        "enabled": True,
        "source_type": "paper",
        "provider": "openai_compatible",
        "model_name": "gpt-4o-mini",
        "api_key_ref": "QUANTIA_AI_API_KEY",
        "system_prompt": "你是量化研判助手...",
        "user_prompt_template": "{{ code }} 当前情况：{{ indicators }}",
        "temperature": 0.2,
        "max_tokens": 1024,
        "timeout_seconds": 15,
        "buy_threshold": 70,
        "sell_threshold": 40,
        "enabled_as_gate": False,
    })
    assert cfg["id"] == 1
    assert cfg["config_version"] == 1
    assert cfg["api_key_ref"] == "QUANTIA_AI_API_KEY"
    # 安全：响应不返回密钥明文字段
    assert "api_key" not in cfg and "secret" not in cfg


def test_save_ai_config_update_bumps_version(fake_db):
    cfg = ach.save_config({"name": "v1", "source_type": "paper",
                           "provider": "openai_compatible"})
    assert cfg["config_version"] == 1
    cfg2 = ach.save_config({"id": cfg["id"], "name": "v1",
                            "source_type": "paper",
                            "provider": "openai_compatible",
                            "buy_threshold": 80})
    assert cfg2["config_version"] == 2
    assert cfg2["buy_threshold"] == 80


def test_save_ai_config_rejects_api_key_plaintext(fake_db):
    with pytest.raises(ValueError, match="api_key"):
        ach.save_config({"name": "x", "provider": "openai",
                         "api_key": "sk-ABCDEFG..."})


def test_save_ai_config_rejects_secret_in_ref_field(fake_db):
    with pytest.raises(ValueError, match="api_key_ref"):
        ach.save_config({"name": "x", "provider": "openai",
                         "api_key_ref": "sk-ABCDEFG..."})


def test_save_ai_config_rejects_out_of_range(fake_db):
    with pytest.raises(ValueError, match="temperature"):
        ach.save_config({"name": "x", "provider": "openai", "temperature": 5})
    with pytest.raises(ValueError, match="buy_threshold"):
        ach.save_config({"name": "x", "provider": "openai", "buy_threshold": 200})
    with pytest.raises(ValueError, match="timeout_seconds"):
        ach.save_config({"name": "x", "provider": "openai", "timeout_seconds": 9999})


def test_save_ai_config_gate_implies_enabled(fake_db):
    cfg = ach.save_config({"name": "x", "provider": "openai",
                           "enabled": False, "enabled_as_gate": True})
    # 矛盾 → enabled 自动转 True（与 §3.5 一致：gate 启用必须先启用 AI）
    assert cfg["enabled"] is True
    assert cfg["enabled_as_gate"] is True


def test_save_ai_config_rejects_invalid_provider_and_source_type(fake_db):
    with pytest.raises(ValueError, match="provider"):
        ach.save_config({"name": "x", "provider": "anthropic_native"})
    with pytest.raises(ValueError, match="source_type"):
        ach.save_config({"name": "x", "provider": "openai", "source_type": "bogus"})


def test_save_ai_config_requires_name(fake_db):
    with pytest.raises(ValueError, match="name"):
        ach.save_config({"provider": "openai"})


def test_list_and_delete_ai_config(fake_db):
    a = ach.save_config({"name": "a", "provider": "openai"})
    ach.save_config({"name": "b", "provider": "openai"})
    rows = ach.list_configs()
    assert len(rows) == 2
    ach.delete_config(a["id"])
    rows = ach.list_configs()
    assert len(rows) == 1
    assert rows[0]["name"] == "b"


def test_ai_config_api_key_is_configured_flag(fake_db, monkeypatch):
    monkeypatch.setenv("MY_AI_KEY", "sk-test")
    a = ach.save_config({"name": "x", "provider": "openai",
                         "api_key_ref": "MY_AI_KEY"})
    assert a["api_key_is_configured"] is True
    # API 响应 dict 中也不应包含明文 sk-test
    assert "sk-test" not in str(a)


def test_ai_config_response_omits_internal_db_fields_only_safe_subset(fake_db):
    cfg = ach.save_config({"name": "x", "provider": "openai",
                           "system_prompt": "secret-prompt",
                           "api_key_ref": "MY_VAR"})
    # 业务字段允许（system_prompt 不是密钥，是模板）
    assert cfg["system_prompt"] == "secret-prompt"
    # 但 api_key 明文绝不应出现
    for forbidden in ("api_key", "apiKey", "secret", "token"):
        assert forbidden not in cfg
