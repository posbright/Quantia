#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 6 验收测试：IM 指令回调（签名 / 白名单 / 风控 / 防重放 / 默认关闭）。

使用内存 fake DB 隔离，不连真实 MySQL；同时 monkeypatch 环境变量启用
``QUANTIA_IM_COMMAND_ENABLED`` 以便走完整流程。
"""
from __future__ import annotations

import datetime
import json
import time
from typing import Any, Dict, List, Tuple
from unittest.mock import patch

import pytest

from quantia.im import service as im_service
from quantia.im import signature as im_sig


# ─────────── In-memory fake DB ───────────

class _FakeMDB:
    def __init__(self):
        self.commands: List[Dict[str, Any]] = []
        self.operators: List[Dict[str, Any]] = []
        self._cmd_id = 0
        self._op_id = 0
        self._existing = {
            im_service.TRADE_COMMAND_TABLE,
            im_service.OPERATOR_WHITELIST_TABLE,
        }

    def checkTableIsExist(self, name):
        return name in self._existing

    def executeSql(self, sql, params=()):
        s = sql.strip().lower()
        if s.startswith("create table"):
            return None
        if s.startswith("delete from `cn_stock_im_operator_whitelist`"):
            cid = int(params[0])
            self.operators = [r for r in self.operators if r["id"] != cid]
            return None
        if s.startswith("update `cn_stock_im_operator_whitelist`"):
            channel, op_id, op_name, enabled, note, modified_by, cid = params
            for r in self.operators:
                if r["id"] == int(cid):
                    r.update(channel=channel, operator_id=op_id,
                             operator_name=op_name, enabled=enabled, note=note,
                             modified_by=modified_by,
                             updated_at=datetime.datetime.now())
            return None
        if s.startswith("insert into `cn_stock_im_operator_whitelist`"):
            channel, op_id, op_name, enabled, note, modified_by = params
            # Simulate ON DUPLICATE KEY UPDATE on (channel, operator_id)
            for r in self.operators:
                if r["channel"] == channel and r["operator_id"] == op_id:
                    r.update(operator_name=op_name, enabled=enabled, note=note,
                             modified_by=modified_by,
                             updated_at=datetime.datetime.now())
                    return None
            self._op_id += 1
            self.operators.append({
                "id": self._op_id, "channel": channel, "operator_id": op_id,
                "operator_name": op_name, "enabled": enabled, "note": note,
                "modified_by": modified_by,
                "created_at": datetime.datetime.now(),
                "updated_at": datetime.datetime.now(),
            })
            return None
        return None

    def executeSqlFetch(self, sql, params=()):
        s = sql.strip().lower()
        # Operator list
        if s.startswith("select id, channel, operator_id, operator_name, enabled, note,"):
            rows = self.operators
            if "where channel=%s" in s and "operator_id" not in s.split("where", 1)[1]:
                rows = [r for r in rows if r["channel"] == params[0]]
            return [_op_row(r) for r in rows]
        # Operator allowed check
        if s.startswith("select enabled from `cn_stock_im_operator_whitelist`"):
            channel, op_id = params
            for r in self.operators:
                if r["channel"] == channel and r["operator_id"] == op_id:
                    return [(r["enabled"],)]
            return []
        # Single op fetch by (channel, operator_id) for save_operator return
        if "where channel=%s and operator_id=%s limit 1" in s and "from `cn_stock_im_operator_whitelist`" in s:
            channel, op_id = params
            for r in self.operators:
                if r["channel"] == channel and r["operator_id"] == op_id:
                    return [_op_row(r)]
            return []
        # Replay check
        if s.startswith("select id, status from `cn_stock_trade_command`"):
            channel, msg_id = params
            for r in self.commands:
                if r["source_channel"] == channel and r["source_message_id"] == msg_id:
                    return [(r["id"], r["status"])]
            return []
        # Daily used value
        if "coalesce(sum(`value`), 0)" in s:
            op_id, channel, today = params
            total = 0.0
            for r in self.commands:
                if (r["operator_id"] == op_id and r["source_channel"] == channel
                        and r["status"] in ("approved", "executed")
                        and r["created_at"].date() == today):
                    total += float(r.get("value") or 0)
            return [(total,)]
        # Already-confirmed signal check
        if s.startswith("select id from `cn_stock_trade_command`"):
            (signal_id,) = params
            for r in self.commands:
                if r.get("signal_id") == int(signal_id) and r["status"] in ("approved", "executed"):
                    return [(r["id"],)]
            return []
        # list / detail
        if s.startswith("select id, source_channel, source_message_id"):
            rows = list(self.commands)
            # crude WHERE clause handling
            return [_cmd_row(r) for r in rows[-10:]]
        return []

    class _Cur:
        def __init__(self, parent): self.parent = parent; self._last = None
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, sql, params=()):
            s = sql.strip().lower()
            if s.startswith("insert into `cn_stock_trade_command`"):
                self.parent._cmd_id += 1
                new_id = self.parent._cmd_id
                (channel, msg_id, op_id, op_name, command_type, paper_id,
                 signal_id, code, direction, amount, value, price_limit,
                 status, risk_json, payload_json, expire_at, approved_at) = params
                self.parent.commands.append({
                    "id": new_id, "source_channel": channel, "source_message_id": msg_id,
                    "operator_id": op_id, "operator_name": op_name,
                    "command_type": command_type, "paper_id": paper_id,
                    "signal_id": signal_id, "code": code, "direction": direction,
                    "amount": amount, "value": value, "price_limit": price_limit,
                    "status": status, "risk_check_json": risk_json,
                    "request_payload": payload_json, "expire_at": expire_at,
                    "approved_at": approved_at, "executed_at": None,
                    "execution_result": None,
                    "created_at": datetime.datetime.now(),
                    "updated_at": datetime.datetime.now(),
                })
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


def _op_row(r):
    return (r["id"], r["channel"], r["operator_id"], r.get("operator_name"),
            r.get("enabled", 1), r.get("note"), r.get("modified_by"),
            r.get("created_at"), r.get("updated_at"))


def _cmd_row(r):
    return (r["id"], r["source_channel"], r["source_message_id"],
            r.get("operator_id"), r.get("operator_name"),
            r.get("command_type"), r.get("paper_id"), r.get("signal_id"),
            r.get("code"), r.get("direction"),
            r.get("amount"), r.get("value"), r.get("price_limit"),
            r.get("status"), r.get("risk_check_json"), r.get("request_payload"),
            r.get("expire_at"), r.get("approved_at"), r.get("executed_at"),
            r.get("execution_result"), r.get("created_at"), r.get("updated_at"))


@pytest.fixture
def fake_db():
    fake = _FakeMDB()
    with patch("quantia.lib.database.checkTableIsExist", side_effect=fake.checkTableIsExist), \
         patch("quantia.lib.database.executeSql", side_effect=fake.executeSql), \
         patch("quantia.lib.database.executeSqlFetch", side_effect=fake.executeSqlFetch), \
         patch("quantia.lib.database.get_connection", side_effect=fake.get_connection):
        yield fake


# ─────────── 工具：构造合法签名 + 启用 ───────────

CALLBACK_SECRET = "TEST_CALLBACK_SECRET_for_unit_tests"


def _build_signed_headers(secret: str = CALLBACK_SECRET, *,
                          ts_offset_ms: int = 0) -> Dict[str, str]:
    ts = str(int(time.time() * 1000) + ts_offset_ms)
    sign = im_sig.compute_sign(secret, ts)
    return {"timestamp": ts, "sign": sign}


def _enable():
    return patch.dict("os.environ", {
        im_service.ENABLED_ENV: "1",
        im_service.SECRET_ENV: CALLBACK_SECRET,
    })


# ─────────── 1. 默认关闭 ───────────


def test_is_enabled_default_off(monkeypatch):
    monkeypatch.delenv(im_service.ENABLED_ENV, raising=False)
    assert im_service.is_enabled() is False


def test_is_enabled_truthy_values(monkeypatch):
    for v in ("1", "true", "Yes", "ON"):
        monkeypatch.setenv(im_service.ENABLED_ENV, v)
        assert im_service.is_enabled() is True
    for v in ("0", "false", "no", ""):
        monkeypatch.setenv(im_service.ENABLED_ENV, v)
        assert im_service.is_enabled() is False


def test_callback_returns_disabled_when_flag_off(fake_db, monkeypatch):
    monkeypatch.delenv(im_service.ENABLED_ENV, raising=False)
    headers = _build_signed_headers()
    result = im_service.handle_dingtalk_callback(
        headers, {"command_type": "confirm_buy"})
    assert result["ok"] is False
    assert result["status"] == "disabled"
    # 不应写入任何指令
    assert fake_db.commands == []


# ─────────── 2. 签名校验 ───────────


def test_signature_missing_components():
    err = im_sig.verify_dingtalk_signature("secret", "", "abc")
    assert err and "缺少" in err
    err = im_sig.verify_dingtalk_signature("", "1700000000000", "abc")
    assert err and "secret" in err
    err = im_sig.verify_dingtalk_signature("secret", "not-a-number", "abc")
    assert err and "timestamp" in err


def test_signature_out_of_time_window():
    secret = "s"
    ts_old = str(int(time.time() * 1000) - 10 * 60 * 1000)  # 10 分钟前
    sign = im_sig.compute_sign(secret, ts_old)
    err = im_sig.verify_dingtalk_signature(secret, ts_old, sign)
    assert err and "时间窗" in err


def test_signature_valid_round_trip():
    secret = "s"
    ts = str(int(time.time() * 1000))
    sign = im_sig.compute_sign(secret, ts)
    assert im_sig.verify_dingtalk_signature(secret, ts, sign) is None


def test_signature_mismatch():
    secret = "s"
    ts = str(int(time.time() * 1000))
    bad_sign = im_sig.compute_sign("other_secret", ts)
    err = im_sig.verify_dingtalk_signature(secret, ts, bad_sign)
    assert err and "不匹配" in err


def test_callback_signature_failed_does_not_touch_db(fake_db, monkeypatch):
    monkeypatch.setenv(im_service.ENABLED_ENV, "1")
    monkeypatch.setenv(im_service.SECRET_ENV, CALLBACK_SECRET)
    bad_headers = {"timestamp": str(int(time.time() * 1000)), "sign": "bad"}
    result = im_service.handle_dingtalk_callback(
        bad_headers, {"command_type": "confirm_buy", "operator_id": "u1"})
    assert result["ok"] is False
    assert result["status"] == "signature_failed"
    assert fake_db.commands == []


# ─────────── 3. 白名单 ───────────


def test_operator_whitelist_crud(fake_db):
    saved = im_service.save_operator({"channel": "dingtalk",
                                      "operator_id": "u1",
                                      "operator_name": "Alice"})
    assert saved["operator_id"] == "u1"
    assert saved["enabled"] is True
    rows = im_service.list_operators("dingtalk")
    assert len(rows) == 1
    # idempotent: same (channel, operator_id) updates instead of duplicating
    saved2 = im_service.save_operator({"channel": "dingtalk",
                                       "operator_id": "u1",
                                       "operator_name": "Alice2"})
    assert saved2["operator_name"] == "Alice2"
    assert len(im_service.list_operators("dingtalk")) == 1
    im_service.delete_operator(saved["id"])
    assert im_service.list_operators("dingtalk") == []


def test_save_operator_rejects_empty_id(fake_db):
    with pytest.raises(ValueError, match="operator_id"):
        im_service.save_operator({"channel": "dingtalk", "operator_id": ""})


def test_save_operator_rejects_invalid_chars(fake_db):
    with pytest.raises(ValueError, match="非法"):
        im_service.save_operator({"channel": "dingtalk",
                                  "operator_id": "u/1"})


def test_callback_unauthorized_when_operator_not_whitelisted(fake_db, monkeypatch):
    monkeypatch.setenv(im_service.ENABLED_ENV, "1")
    monkeypatch.setenv(im_service.SECRET_ENV, CALLBACK_SECRET)
    headers = _build_signed_headers()
    result = im_service.handle_dingtalk_callback(headers, {
        "command_type": "confirm_buy", "operator_id": "ghost",
        "signal_id": 1, "code": "600519", "amount": 10, "price": 100,
        "source_message_id": "m-unauth-1",
    })
    assert result["status"] == "unauthorized"
    # 仍然落库以便审计
    assert len(fake_db.commands) == 1
    assert fake_db.commands[0]["status"] == "unauthorized"


# ─────────── 4. 风控 ───────────


def test_callback_rejects_when_single_value_exceeds_limit(fake_db, monkeypatch):
    monkeypatch.setenv(im_service.ENABLED_ENV, "1")
    monkeypatch.setenv(im_service.SECRET_ENV, CALLBACK_SECRET)
    monkeypatch.setenv(im_service.MAX_SINGLE_ENV, "10000")
    im_service.save_operator({"channel": "dingtalk", "operator_id": "u1"})
    headers = _build_signed_headers()
    result = im_service.handle_dingtalk_callback(headers, {
        "command_type": "confirm_buy", "operator_id": "u1",
        "signal_id": 100, "code": "600519",
        "amount": 100, "price": 200,  # value=20000 > 10000
        "source_message_id": "m-single-over",
    })
    assert result["status"] == "rejected"
    risk = result["risk_result"]
    fail = [c for c in risk["checks"] if c["name"] == "max_single_value"]
    assert fail and fail[0]["passed"] is False


def test_callback_rejects_when_daily_value_exceeds_limit(fake_db, monkeypatch):
    monkeypatch.setenv(im_service.ENABLED_ENV, "1")
    monkeypatch.setenv(im_service.SECRET_ENV, CALLBACK_SECRET)
    monkeypatch.setenv(im_service.MAX_SINGLE_ENV, "100000")
    monkeypatch.setenv(im_service.MAX_DAILY_ENV, "30000")
    im_service.save_operator({"channel": "dingtalk", "operator_id": "u1"})
    # 第一笔 20000 通过
    r1 = im_service.handle_dingtalk_callback(_build_signed_headers(), {
        "command_type": "confirm_buy", "operator_id": "u1",
        "signal_id": 1, "code": "600519",
        "amount": 100, "price": 200,
        "source_message_id": "m-day-1",
    })
    assert r1["status"] == "approved"
    # 第二笔 20000，今日累计 40000 > 30000 → 拒绝
    r2 = im_service.handle_dingtalk_callback(_build_signed_headers(), {
        "command_type": "confirm_buy", "operator_id": "u1",
        "signal_id": 2, "code": "600519",
        "amount": 100, "price": 200,
        "source_message_id": "m-day-2",
    })
    assert r2["status"] == "rejected"
    fail = [c for c in r2["risk_result"]["checks"] if c["name"] == "max_daily_value"]
    assert fail and fail[0]["passed"] is False


def test_callback_rejects_duplicate_signal_confirmation(fake_db, monkeypatch):
    monkeypatch.setenv(im_service.ENABLED_ENV, "1")
    monkeypatch.setenv(im_service.SECRET_ENV, CALLBACK_SECRET)
    im_service.save_operator({"channel": "dingtalk", "operator_id": "u1"})
    r1 = im_service.handle_dingtalk_callback(_build_signed_headers(), {
        "command_type": "confirm_buy", "operator_id": "u1",
        "signal_id": 7, "code": "600519",
        "amount": 10, "price": 100,
        "source_message_id": "m-sig-1",
    })
    assert r1["status"] == "approved"
    # 同一 signal_id 不同 message_id，第二次应被风控拒绝
    r2 = im_service.handle_dingtalk_callback(_build_signed_headers(), {
        "command_type": "confirm_buy", "operator_id": "u1",
        "signal_id": 7, "code": "600519",
        "amount": 10, "price": 100,
        "source_message_id": "m-sig-2",
    })
    assert r2["status"] == "rejected"
    fail = [c for c in r2["risk_result"]["checks"] if c["name"] == "signal_unique_confirm"]
    assert fail and fail[0]["passed"] is False


# ─────────── 5. 防重放 ───────────


def test_callback_replay_returns_duplicate(fake_db, monkeypatch):
    monkeypatch.setenv(im_service.ENABLED_ENV, "1")
    monkeypatch.setenv(im_service.SECRET_ENV, CALLBACK_SECRET)
    im_service.save_operator({"channel": "dingtalk", "operator_id": "u1"})
    payload = {
        "command_type": "confirm_buy", "operator_id": "u1",
        "signal_id": 11, "code": "600519",
        "amount": 1, "price": 1,
        "source_message_id": "m-replay-1",
    }
    r1 = im_service.handle_dingtalk_callback(_build_signed_headers(), payload)
    assert r1["status"] == "approved"
    cid_first = r1["command_id"]
    # 第二次同 message_id
    r2 = im_service.handle_dingtalk_callback(_build_signed_headers(), payload)
    assert r2["status"] == "duplicate"
    assert r2["command_id"] == cid_first
    # DB 中只应有一条
    assert len([c for c in fake_db.commands
                if c["source_message_id"] == "m-replay-1"]) == 1


# ─────────── 6. 非法指令 / 缺字段 ───────────


def test_callback_invalid_command_type(fake_db, monkeypatch):
    monkeypatch.setenv(im_service.ENABLED_ENV, "1")
    monkeypatch.setenv(im_service.SECRET_ENV, CALLBACK_SECRET)
    result = im_service.handle_dingtalk_callback(_build_signed_headers(), {
        "command_type": "rocket_launch", "operator_id": "u1",
        "source_message_id": "m-bad-cmd",
    })
    assert result["status"] == "invalid"
    # 落库（审计）
    assert len(fake_db.commands) == 1
    assert fake_db.commands[0]["status"] == "invalid"


def test_callback_invalid_direction(fake_db, monkeypatch):
    monkeypatch.setenv(im_service.ENABLED_ENV, "1")
    monkeypatch.setenv(im_service.SECRET_ENV, CALLBACK_SECRET)
    result = im_service.handle_dingtalk_callback(_build_signed_headers(), {
        "command_type": "confirm_buy", "direction": "short",
        "operator_id": "u1", "source_message_id": "m-bad-dir",
    })
    assert result["status"] == "invalid"


# ─────────── 7. 指令文本解析 ───────────


def test_parse_command_text():
    out = im_service._parse_command_text(
        "confirm_buy paper=1 signal=42 code=600519 amount=100 value=20000")
    assert out == {
        "command_type": "confirm_buy",
        "paper": "1", "signal": "42", "code": "600519",
        "amount": "100", "value": "20000",
    }


def test_parse_callback_payload_merges_text_field():
    body = {
        "operator_id": "u1",
        "source_message_id": "m1",
        "text": {"content": "confirm_buy signal=42 code=600519 amount=10"},
    }
    out = im_service._parse_callback_payload(body)
    assert out["command_type"] == "confirm_buy"
    assert out["signal"] == "42"
    assert out["code"] == "600519"
    # 顶层字段不被覆盖
    assert out["operator_id"] == "u1"


# ─────────── 8. happy path 落库字段完整 ───────────


def test_callback_happy_path_persists_full_command(fake_db, monkeypatch):
    monkeypatch.setenv(im_service.ENABLED_ENV, "1")
    monkeypatch.setenv(im_service.SECRET_ENV, CALLBACK_SECRET)
    im_service.save_operator({"channel": "dingtalk", "operator_id": "u1",
                              "operator_name": "Alice"})
    headers = _build_signed_headers()
    result = im_service.handle_dingtalk_callback(headers, {
        "command_type": "confirm_buy", "operator_id": "u1",
        "operator_name": "Alice",
        "paper": 1, "signal": 42, "code": "600519",
        "amount": 100, "price": 200,
        "source_message_id": "m-happy-1",
    })
    assert result["ok"] is True
    assert result["status"] == "approved"
    cid = result["command_id"]
    # 落库验证
    rec = next(c for c in fake_db.commands if c["id"] == cid)
    assert rec["operator_id"] == "u1"
    assert rec["operator_name"] == "Alice"
    assert rec["command_type"] == "confirm_buy"
    assert rec["paper_id"] == 1
    assert rec["signal_id"] == 42
    assert rec["code"] == "600519"
    assert rec["direction"] == "buy"
    assert float(rec["amount"]) == 100.0
    assert rec["status"] == "approved"
    assert rec["expire_at"] is not None
    assert rec["approved_at"] is not None
    # request_payload 是 JSON 字符串，可解析回来
    payload = json.loads(rec["request_payload"])
    assert payload["operator_id"] == "u1"


# ─────────── 9. 默认 max_*/ttl 读取 ───────────


def test_default_risk_limits(monkeypatch):
    monkeypatch.delenv(im_service.MAX_SINGLE_ENV, raising=False)
    monkeypatch.delenv(im_service.MAX_DAILY_ENV, raising=False)
    monkeypatch.delenv(im_service.TTL_ENV, raising=False)
    assert im_service._max_single_value() == im_service.DEFAULT_MAX_SINGLE
    assert im_service._max_daily_value() == im_service.DEFAULT_MAX_DAILY
    assert im_service._ttl_seconds() == im_service.DEFAULT_TTL_SECONDS
