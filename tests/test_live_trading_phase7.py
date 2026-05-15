#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 7 验收测试：实盘交易连接（默认关闭、二次风控、状态回写、IM 通知）。

策略：
- 内存 fake DB 隔离 ``cn_stock_trade_command`` / ``cn_stock_im_operator_whitelist``
  / ``cn_stock_notification_event``。
- ``DryRunBroker`` 默认覆盖；自定义 ``RecordingBroker`` 验证调用次数与参数；
  另外引入会抛异常的 ``ExplodingBroker`` 验证 try/except。
- monkeypatch ``QUANTIA_LIVE_TRADING_ENABLED`` 控制总开关；不写入真实 DB。
"""
from __future__ import annotations

import datetime
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from quantia.live import executor as live_executor
from quantia.live.executor import (
    BrokerAdapter, BrokerOrderResult, DryRunBroker, _second_stage_risk,
    execute_pending_commands, is_enabled, register_broker,
)
from quantia.im import service as im_service
from quantia.im import schema as im_schema


# ─────────── In-memory fake DB ───────────

class _FakeMDB:
    def __init__(self):
        self.commands: List[Dict[str, Any]] = []
        self.operators: List[Dict[str, Any]] = []
        self.events: List[Dict[str, Any]] = []
        self._cmd_id = 0
        self._op_id = 0
        self._evt_id = 0
        self._existing = {
            im_schema.TRADE_COMMAND_TABLE,
            im_schema.OPERATOR_WHITELIST_TABLE,
            "cn_stock_notification_config",
            "cn_stock_notification_event",
        }

    def checkTableIsExist(self, name):
        return name in self._existing

    def executeSql(self, sql, params=()):
        s = sql.strip().lower()
        if s.startswith("create table") or s.startswith("alter table"):
            return None
        # Update command status from executor
        if s.startswith(f"update `{im_schema.TRADE_COMMAND_TABLE}` set status="):
            status, executed_at, exec_result, cid = params
            for r in self.commands:
                if r["id"] == int(cid):
                    r["status"] = status
                    r["executed_at"] = executed_at
                    r["execution_result"] = exec_result
            return None
        # Operator whitelist mutations (reuse Phase 6 logic)
        if s.startswith(f"insert into `{im_schema.OPERATOR_WHITELIST_TABLE}`"):
            channel, op_id, op_name, enabled, note = params
            for r in self.operators:
                if r["channel"] == channel and r["operator_id"] == op_id:
                    r.update(operator_name=op_name, enabled=enabled, note=note,
                             updated_at=datetime.datetime.now())
                    return None
            self._op_id += 1
            self.operators.append({
                "id": self._op_id, "channel": channel, "operator_id": op_id,
                "operator_name": op_name, "enabled": enabled, "note": note,
                "created_at": datetime.datetime.now(),
                "updated_at": datetime.datetime.now(),
            })
            return None
        return None

    def executeSqlFetch(self, sql, params=()):
        s = sql.strip().lower()
        # operator allowed
        if s.startswith(f"select enabled from `{im_schema.OPERATOR_WHITELIST_TABLE}`"):
            channel, op_id = params
            for r in self.operators:
                if r["channel"] == channel and r["operator_id"] == op_id:
                    return [(r["enabled"],)]
            return []
        # daily used value
        if "coalesce(sum(`value`), 0)" in s:
            op_id, channel, today = params
            total = 0.0
            for r in self.commands:
                if (r["operator_id"] == op_id and r["source_channel"] == channel
                        and r["status"] in ("approved", "executed")
                        and r["created_at"].date() == today):
                    total += float(r.get("value") or 0)
            return [(total,)]
        # signal already executed (executor.second_stage uses status='executed')
        if "and status='executed' and id<>" in s:
            sig_id, self_id = params
            for r in self.commands:
                if (r.get("signal_id") == int(sig_id) and r["status"] == "executed"
                        and r["id"] != int(self_id)):
                    return [(r["id"],)]
            return []
        # signal already approved/executed (Phase 6 risk)
        if s.startswith(f"select id from `{im_schema.TRADE_COMMAND_TABLE}` "
                        f"where signal_id=%s and status in ('approved','executed')"):
            (sig_id,) = params
            for r in self.commands:
                if r.get("signal_id") == int(sig_id) and r["status"] in ("approved", "executed"):
                    return [(r["id"],)]
            return []
        # executor scan
        if "from `cn_stock_trade_command`" in s and "where status='approved'" in s:
            (limit,) = params
            out = [r for r in self.commands if r["status"] == "approved"][:int(limit)]
            return [_cmd_row_for_executor(r) for r in out]
        return []

    class _Cur:
        def __init__(self, parent): self.parent = parent; self._last = None
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, sql, params=()):
            s = sql.strip().lower()
            if s.startswith("insert into `cn_stock_notification_event`") or \
               s.startswith("insert ignore into `cn_stock_notification_event`"):
                self.parent._evt_id += 1
                new_id = self.parent._evt_id
                (dedupe, paper_id, event_type, channel, trade_date, code,
                 direction, status, payload_json, error_message) = params
                # dedupe enforcement
                if any(e["dedupe_key"] == dedupe for e in self.parent.events):
                    self._last = None
                    return None
                self.parent.events.append({
                    "id": new_id, "dedupe_key": dedupe, "paper_id": paper_id,
                    "event_type": event_type, "channel": channel,
                    "trade_date": trade_date, "code": code, "direction": direction,
                    "status": status, "payload_json": payload_json,
                    "error_message": error_message,
                })
                self._last = new_id
            elif s.startswith("select last_insert_id"):
                pass
            return None
        def fetchone(self):
            return (self._last,) if self._last is not None else None
        @property
        def rowcount(self):
            return 0 if self._last is None else 1

    class _Conn:
        def __init__(self, parent): self.parent = parent
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def cursor(self): return _FakeMDB._Cur(self.parent)
        def commit(self): pass

    def get_connection(self):
        return _FakeMDB._Conn(self)


def _cmd_row_for_executor(r):
    return (r["id"], r["source_channel"], r["source_message_id"],
            r["operator_id"], r.get("operator_name"),
            r.get("command_type"), r.get("paper_id"), r.get("signal_id"),
            r.get("code"), r.get("direction"),
            r.get("amount"), r.get("value"), r.get("price_limit"),
            r["status"], r.get("expire_at"), r.get("approved_at"))


@pytest.fixture
def fake_db():
    fake = _FakeMDB()
    with patch("quantia.lib.database.checkTableIsExist", side_effect=fake.checkTableIsExist), \
         patch("quantia.lib.database.executeSql", side_effect=fake.executeSql), \
         patch("quantia.lib.database.executeSqlFetch", side_effect=fake.executeSqlFetch), \
         patch("quantia.lib.database.get_connection", side_effect=fake.get_connection), \
         patch("quantia.notification.service.ensure_notification_tables",
               side_effect=lambda: None):
        yield fake


# ─────────── helpers ───────────


def _seed_command(fake, **overrides):
    fake._cmd_id += 1
    cmd = {
        "id": fake._cmd_id,
        "source_channel": "dingtalk", "source_message_id": f"m-{fake._cmd_id}",
        "operator_id": "u1", "operator_name": "Alice",
        "command_type": "confirm_buy", "paper_id": 1, "signal_id": 100 + fake._cmd_id,
        "code": "600519", "direction": "buy",
        "amount": 100.0, "value": 20000.0, "price_limit": 200.0,
        "status": "approved",
        "expire_at": datetime.datetime.now() + datetime.timedelta(seconds=300),
        "approved_at": datetime.datetime.now(),
        "executed_at": None, "execution_result": None,
        "created_at": datetime.datetime.now(),
        "updated_at": datetime.datetime.now(),
    }
    cmd.update(overrides)
    fake.commands.append(cmd)
    return cmd


def _whitelist(fake, op_id="u1", enabled=1):
    fake._op_id += 1
    fake.operators.append({
        "id": fake._op_id, "channel": "dingtalk", "operator_id": op_id,
        "operator_name": op_id, "enabled": enabled, "note": "",
        "created_at": datetime.datetime.now(),
        "updated_at": datetime.datetime.now(),
    })


# ─────────── 1. 总开关默认关闭 ───────────


def test_is_enabled_default_off(monkeypatch):
    monkeypatch.delenv(live_executor.ENABLED_ENV, raising=False)
    assert is_enabled() is False


def test_execute_pending_disabled_returns_no_db_touch(fake_db, monkeypatch):
    monkeypatch.delenv(live_executor.ENABLED_ENV, raising=False)
    _whitelist(fake_db)
    _seed_command(fake_db)
    res = execute_pending_commands()
    assert res["status"] == "disabled"
    # 命令状态保持 approved
    assert fake_db.commands[0]["status"] == "approved"
    # 通知 outbox 未写入
    assert fake_db.events == []


# ─────────── 2. DryRunBroker happy path ───────────


def test_execute_pending_dry_run_executes_and_notifies(fake_db, monkeypatch):
    monkeypatch.setenv(live_executor.ENABLED_ENV, "1")
    monkeypatch.delenv(live_executor.BROKER_ENV, raising=False)
    monkeypatch.delenv(live_executor.TRADING_HOURS_ENV, raising=False)
    _whitelist(fake_db)
    cmd = _seed_command(fake_db)
    res = execute_pending_commands()
    assert res["status"] == "ok"
    assert res["broker"] == "dry_run"
    assert res["executed"] == 1
    assert res["failed"] == 0
    # 状态回写
    assert fake_db.commands[0]["status"] == "executed"
    assert fake_db.commands[0]["executed_at"] is not None
    er = fake_db.commands[0]["execution_result"]
    assert er and "DRY-" in er  # JSON 字符串包含 dry_run order id
    # 通知事件
    assert len(fake_db.events) == 1
    evt = fake_db.events[0]
    assert evt["event_type"] == "trade_executed"
    assert evt["code"] == cmd["code"]


# ─────────── 3. 已过期 → expired ───────────


def test_execute_pending_marks_expired(fake_db, monkeypatch):
    monkeypatch.setenv(live_executor.ENABLED_ENV, "1")
    _whitelist(fake_db)
    _seed_command(fake_db,
                  expire_at=datetime.datetime.now() - datetime.timedelta(seconds=10))
    res = execute_pending_commands()
    assert res["expired"] == 1
    assert res["executed"] == 0
    assert fake_db.commands[0]["status"] == "expired"


# ─────────── 4. 操作人被移出白名单 → rejected ───────────


def test_execute_pending_rejects_when_operator_removed(fake_db, monkeypatch):
    monkeypatch.setenv(live_executor.ENABLED_ENV, "1")
    # 白名单为空，操作人不再有效
    _seed_command(fake_db)
    res = execute_pending_commands()
    assert res["rejected"] == 1
    assert fake_db.commands[0]["status"] == "rejected"
    er = fake_db.commands[0]["execution_result"]
    assert er and "operator_still_whitelisted" in er


# ─────────── 5. 单笔金额超限 → rejected ───────────


def test_execute_pending_rejects_when_single_value_over(fake_db, monkeypatch):
    monkeypatch.setenv(live_executor.ENABLED_ENV, "1")
    monkeypatch.setenv(im_service.MAX_SINGLE_ENV, "10000")
    _whitelist(fake_db)
    _seed_command(fake_db, value=20000.0)  # > 10000
    res = execute_pending_commands()
    assert res["rejected"] == 1
    assert fake_db.commands[0]["status"] == "rejected"


# ─────────── 6. 交易时段限制 ───────────


def test_within_trading_hours_default_open(monkeypatch):
    monkeypatch.delenv(live_executor.TRADING_HOURS_ENV, raising=False)
    assert live_executor._within_trading_hours() is True


def test_within_trading_hours_outside_window(monkeypatch):
    # 设置一个一定不包含当前时间的窗口（00:00-00:01）
    monkeypatch.setenv(live_executor.TRADING_HOURS_ENV, "00:00-00:01")
    # 直接构造一个明显在窗口外的时间
    fake_now = datetime.datetime.combine(datetime.date.today(),
                                         datetime.time(12, 0))
    assert live_executor._within_trading_hours(fake_now) is False


def test_execute_pending_rejects_outside_trading_hours(fake_db, monkeypatch):
    monkeypatch.setenv(live_executor.ENABLED_ENV, "1")
    monkeypatch.setenv(live_executor.TRADING_HOURS_ENV, "00:00-00:01")
    _whitelist(fake_db)
    _seed_command(fake_db)
    # patch _now used by _within_trading_hours indirectly via parse + time check
    # Easier: patch _within_trading_hours to False
    with patch.object(live_executor, "_within_trading_hours", return_value=False):
        res = execute_pending_commands()
    assert res["rejected"] == 1
    assert fake_db.commands[0]["status"] == "rejected"


# ─────────── 7. 自定义 broker 注入 ───────────


class _RecordingBroker(BrokerAdapter):
    name = "recording"

    def __init__(self):
        self.calls: List[Dict[str, Any]] = []

    def place_order(self, command):
        self.calls.append(dict(command))
        return BrokerOrderResult(ok=True, order_id="REC-1",
                                 filled_amount=command.get("amount"),
                                 filled_price=command.get("price_limit"),
                                 raw={"mode": "recording"})


def test_register_and_use_custom_broker(fake_db, monkeypatch):
    monkeypatch.setenv(live_executor.ENABLED_ENV, "1")
    monkeypatch.setenv(live_executor.BROKER_ENV, "recording")
    rec = _RecordingBroker()
    register_broker("recording", rec)
    _whitelist(fake_db)
    cmd = _seed_command(fake_db)
    res = execute_pending_commands()
    assert res["broker"] == "recording"
    assert res["executed"] == 1
    assert len(rec.calls) == 1
    assert rec.calls[0]["id"] == cmd["id"]
    assert rec.calls[0]["code"] == cmd["code"]


def test_register_broker_rejects_non_adapter():
    with pytest.raises(TypeError):
        register_broker("bad", object())


# ─────────── 8. broker 抛异常不影响其他指令 ───────────


class _ExplodingBroker(BrokerAdapter):
    name = "exploding"

    def place_order(self, command):
        raise RuntimeError("simulated broker failure")


def test_broker_exception_marks_failed_and_continues(fake_db, monkeypatch):
    monkeypatch.setenv(live_executor.ENABLED_ENV, "1")
    monkeypatch.setenv(live_executor.BROKER_ENV, "exploding")
    register_broker("exploding", _ExplodingBroker())
    _whitelist(fake_db)
    a = _seed_command(fake_db, code="600519")
    b = _seed_command(fake_db, code="000001")
    res = execute_pending_commands()
    assert res["failed"] == 2
    assert res["executed"] == 0
    assert all(c["status"] == "failed" for c in fake_db.commands)
    # 每条都有 IM 通知事件
    assert len(fake_db.events) == 2


# ─────────── 9. 同一 signal 不会被重复执行 ───────────


def test_same_signal_blocked_after_executed(fake_db, monkeypatch):
    monkeypatch.setenv(live_executor.ENABLED_ENV, "1")
    _whitelist(fake_db)
    # 先模拟一条已 executed 的指令
    _seed_command(fake_db, status="executed", signal_id=999, value=10000.0)
    # 再来一条 approved 的指向同 signal
    _seed_command(fake_db, status="approved", signal_id=999, value=10000.0)
    res = execute_pending_commands()
    assert res["rejected"] == 1
    # 第二条被拒
    assert fake_db.commands[1]["status"] == "rejected"


# ─────────── 10. 不会重复处理已执行的指令（只扫 approved） ───────────


def test_executor_skips_non_approved(fake_db, monkeypatch):
    monkeypatch.setenv(live_executor.ENABLED_ENV, "1")
    _whitelist(fake_db)
    _seed_command(fake_db, status="executed")
    _seed_command(fake_db, status="rejected")
    _seed_command(fake_db, status="failed")
    res = execute_pending_commands()
    assert res["processed"] == 0
    assert res["executed"] == 0
    assert fake_db.events == []


# ─────────── 11. trading_hours 解析 ───────────


def test_parse_trading_hours_basic():
    out = live_executor._parse_trading_hours("09:30-11:30,13:00-15:00")
    assert len(out) == 2
    assert out[0] == (datetime.time(9, 30), datetime.time(11, 30))
    assert out[1] == (datetime.time(13, 0), datetime.time(15, 0))


def test_parse_trading_hours_invalid_skipped():
    assert live_executor._parse_trading_hours("") == []
    assert live_executor._parse_trading_hours("garbage") == []
    assert live_executor._parse_trading_hours("09:30") == []


# ─────────── 12. DryRunBroker 仍返回 ok 即便 amount/price 为 0 ───────────


def test_dry_run_broker_returns_order_id_even_when_zero():
    res = DryRunBroker().place_order({"id": 1, "code": "600519",
                                      "direction": "buy",
                                      "amount": 0, "price_limit": 0})
    assert res.ok is True
    assert res.order_id and res.order_id.startswith("DRY-")
