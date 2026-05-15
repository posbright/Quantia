# -*- coding: utf-8 -*-
"""Phase 7: 实盘交易连接（默认关闭）。

设计要点：
- 主开关 ``QUANTIA_LIVE_TRADING_ENABLED``（默认 false）。开启后才允许把 Phase 6
  落库的 ``cn_stock_trade_command`` 中 ``status='approved'`` 的指令送入 broker。
- Broker 抽象 ``BrokerAdapter``；默认实现 ``DryRunBroker`` **永不调用真实券商**，
  仅记录日志并返回模拟结果，供测试与体检使用。
- 真实券商通过 ``QUANTIA_LIVE_BROKER`` 环境变量 + ``register_broker()`` 注入，
  与 ``quantia/trade/trade_service.py`` 解耦；Phase 7 仓库内不绑定任何券商
  client，避免误用。
- 二次风控：执行前重新校验未过期 / 操作人仍在白名单 / 单笔 + 单日金额 / 同
  signal 未被其它指令执行 / 当前在 ``QUANTIA_TRADING_HOURS``（可选）。
- 结果回写：写入 ``executed_at`` / ``execution_result`` / ``status`` ∈
  {executed, expired, failed, skipped}，并通过 Phase 1 通知 outbox 发送
  ``event_type='trade_executed'`` 给 IM。
"""
from __future__ import annotations

import dataclasses
import datetime
import hashlib
import json
import logging
import os
from typing import Any, Callable, Dict, List, Optional

from quantia.im.schema import OPERATOR_WHITELIST_TABLE, TRADE_COMMAND_TABLE, ensure_im_tables
from quantia.im import service as im_service

ENABLED_ENV = "QUANTIA_LIVE_TRADING_ENABLED"
BROKER_ENV = "QUANTIA_LIVE_BROKER"
TRADING_HOURS_ENV = "QUANTIA_TRADING_HOURS"  # e.g. "09:30-11:30,13:00-15:00"

DEFAULT_BROKER = "dry_run"


# ─────────────── Broker 抽象 ───────────────


@dataclasses.dataclass
class BrokerOrderResult:
    ok: bool
    order_id: Optional[str] = None
    filled_amount: Optional[float] = None
    filled_price: Optional[float] = None
    error: str = ""
    raw: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "order_id": self.order_id,
            "filled_amount": self.filled_amount,
            "filled_price": self.filled_price,
            "error": self.error[:500] if self.error else "",
            "raw": self.raw or {},
        }


class BrokerAdapter:
    """Broker 适配器协议。子类需实现 ``place_order``。"""

    name: str = "abstract"

    def place_order(self, command: Dict[str, Any]) -> BrokerOrderResult:
        raise NotImplementedError


class DryRunBroker(BrokerAdapter):
    """空跑 broker：永不下单，仅返回模拟结果。生产默认使用。"""

    name = "dry_run"

    def place_order(self, command: Dict[str, Any]) -> BrokerOrderResult:
        amount = command.get("amount") or 0
        price = command.get("price_limit") or 0
        order_id = "DRY-" + hashlib.sha256(
            f"{command.get('id')}|{command.get('signal_id')}|{datetime.datetime.now().isoformat()}"
            .encode("utf-8")
        ).hexdigest()[:16]
        logging.info("[live.dry_run] mock order id=%s code=%s direction=%s amount=%s price=%s",
                     order_id, command.get("code"), command.get("direction"), amount, price)
        return BrokerOrderResult(
            ok=True, order_id=order_id,
            filled_amount=float(amount) if amount else None,
            filled_price=float(price) if price else None,
            error="",
            raw={"mode": "dry_run"},
        )


_BROKER_REGISTRY: Dict[str, BrokerAdapter] = {DEFAULT_BROKER: DryRunBroker()}


def register_broker(name: str, adapter: BrokerAdapter) -> None:
    """注册 broker 实现。生产部署在启动入口手工调用即可。"""
    if not isinstance(adapter, BrokerAdapter):
        raise TypeError("adapter 必须继承 BrokerAdapter")
    _BROKER_REGISTRY[name] = adapter


def _resolve_broker() -> BrokerAdapter:
    name = (os.getenv(BROKER_ENV) or DEFAULT_BROKER).strip().lower()
    return _BROKER_REGISTRY.get(name) or _BROKER_REGISTRY[DEFAULT_BROKER]


# ─────────────── 主开关 / 工具 ───────────────


def is_enabled() -> bool:
    val = os.getenv(ENABLED_ENV, "")
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _now() -> datetime.datetime:
    return datetime.datetime.now()


def _parse_trading_hours(spec: str) -> List[tuple]:
    """``"09:30-11:30,13:00-15:00"`` → ``[(time(9,30), time(11,30)), ...]``"""
    out: List[tuple] = []
    if not spec:
        return out
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if "-" not in chunk:
            continue
        a, b = chunk.split("-", 1)
        try:
            ah, am = a.strip().split(":")
            bh, bm = b.strip().split(":")
            out.append((datetime.time(int(ah), int(am)),
                        datetime.time(int(bh), int(bm))))
        except Exception:
            continue
    return out


def _within_trading_hours(now: Optional[datetime.datetime] = None) -> bool:
    spec = os.getenv(TRADING_HOURS_ENV) or ""
    windows = _parse_trading_hours(spec)
    if not windows:
        return True  # 未配置即不限制（与现有 paper_trading 行为一致）
    cur = (now or _now()).time()
    for start, end in windows:
        if start <= cur <= end:
            return True
    return False


# ─────────────── 二次风控 ───────────────


def _second_stage_risk(command: Dict[str, Any]) -> Dict[str, Any]:
    """对一条 approved 指令做执行前最终校验。

    返回 ``{"passed": bool, "checks": [...], "error": str|None}``。
    """
    checks: List[Dict[str, Any]] = []
    passed = True
    err = None

    # 1. 未过期
    expire_at = command.get("expire_at")
    if isinstance(expire_at, str):
        try:
            expire_at = datetime.datetime.strptime(expire_at, "%Y-%m-%d %H:%M:%S")
        except Exception:
            expire_at = None
    not_expired = bool(expire_at and expire_at > _now())
    checks.append({"name": "not_expired", "expire_at": str(expire_at), "passed": not_expired})
    if not not_expired:
        passed = False
        err = err or "指令已过期"

    # 2. 操作人仍在白名单
    op_ok = im_service._is_operator_allowed(
        command.get("source_channel") or "dingtalk",
        command.get("operator_id") or "",
    )
    checks.append({"name": "operator_still_whitelisted", "passed": op_ok})
    if not op_ok:
        passed = False
        err = err or "操作人已被移出白名单"

    # 3. 单笔金额（再次读取最新 env）
    value = float(command.get("value") or 0)
    max_single = im_service._max_single_value()
    ok_single = value == 0 or value <= max_single
    checks.append({"name": "max_single_value", "limit": max_single, "actual": value, "passed": ok_single})
    if not ok_single:
        passed = False
        err = err or "单笔金额超限"

    # 4. 单日金额（不计本身指令本身的 value，避免双计）
    used_today = im_service._daily_used_value(
        command.get("operator_id") or "",
        command.get("source_channel") or "dingtalk",
    )
    max_daily = im_service._max_daily_value()
    after = used_today  # 本指令已经在 _daily_used_value 中计入（status='approved'）
    ok_daily = after <= max_daily
    checks.append({"name": "max_daily_value", "limit": max_daily, "used_today": after, "passed": ok_daily})
    if not ok_daily:
        passed = False
        err = err or "当日累计金额超限"

    # 5. 同 signal 未被其它指令 executed
    sig_id = command.get("signal_id")
    if sig_id:
        try:
            import quantia.lib.database as mdb
            rows = mdb.executeSqlFetch(
                f"SELECT id FROM `{TRADE_COMMAND_TABLE}` "
                f"WHERE signal_id=%s AND status='executed' AND id<>%s LIMIT 1",
                (int(sig_id), int(command.get("id") or 0)),
            ) or []
        except Exception:
            rows = []
        ok_sig = not rows
        checks.append({"name": "signal_not_yet_executed", "signal_id": sig_id, "passed": ok_sig})
        if not ok_sig:
            passed = False
            err = err or "该信号已有其他指令执行完成"

    # 6. 交易时段
    in_hours = _within_trading_hours()
    checks.append({"name": "within_trading_hours", "passed": in_hours,
                   "windows": os.getenv(TRADING_HOURS_ENV) or ""})
    if not in_hours:
        passed = False
        err = err or "当前不在配置的交易时段内"

    return {"passed": passed, "checks": checks, "error": err}


# ─────────────── 状态写回 + 通知 ───────────────


def _update_command_status(command_id: int, status: str,
                           execution_result: Dict[str, Any]) -> None:
    import quantia.lib.database as mdb
    executed_at = _now() if status == "executed" else None
    mdb.executeSql(
        f"UPDATE `{TRADE_COMMAND_TABLE}` SET status=%s, executed_at=%s, "
        f"execution_result=%s WHERE id=%s",
        (status, executed_at,
         json.dumps(execution_result, ensure_ascii=False, default=str),
         int(command_id)),
    )


def _notify_execution(command: Dict[str, Any], status: str,
                      result: Dict[str, Any]) -> None:
    """复用 Phase 1 通知 outbox。失败仅 warning，不阻塞执行流程。"""
    try:
        from quantia.notification.service import (
            ensure_notification_tables, _insert_event,
        )
    except Exception as exc:
        logging.debug("[live.notify] 通知模块加载失败: %s", exc)
        return
    try:
        ensure_notification_tables()
    except Exception:
        pass
    cmd_id = int(command.get("id") or 0)
    dedupe = hashlib.sha256(
        f"trade_executed|{cmd_id}|{status}".encode("utf-8")
    ).hexdigest()[:64]
    payload = {
        "title": f"[实盘执行] {command.get('code')} {command.get('direction')} {status}",
        "command_id": cmd_id,
        "signal_id": command.get("signal_id"),
        "operator_id": command.get("operator_id"),
        "code": command.get("code"),
        "direction": command.get("direction"),
        "amount": command.get("amount"),
        "value": command.get("value"),
        "price_limit": command.get("price_limit"),
        "status": status,
        "execution_result": result,
    }
    try:
        _insert_event({
            "dedupe_key": dedupe,
            "paper_id": command.get("paper_id"),
            "event_type": "trade_executed",
            "channel": "dingtalk",
            "trade_date": datetime.date.today(),
            "code": command.get("code"),
            "direction": command.get("direction"),
            "status": "pending",
            "payload": payload,
            "error_message": "",
        })
    except Exception as exc:
        logging.warning("[live.notify] 写入通知事件失败: %s", exc)


# ─────────────── 主入口 ───────────────


def execute_pending_commands(*, limit: int = 20,
                             broker: Optional[BrokerAdapter] = None,
                             ) -> Dict[str, Any]:
    """扫描 approved 指令并尝试执行。返回执行统计。

    - 总开关关闭时返回 ``{"status": "disabled", ...}``，**不读不写 DB**。
    - 已执行过的指令（status != 'approved'）不会被重复处理（DB WHERE 过滤）。
    - 单条失败/过期不影响其它指令。
    """
    if not is_enabled():
        return {"status": "disabled", "reason": f"{ENABLED_ENV} 未启用",
                "processed": 0, "executed": 0, "expired": 0,
                "rejected": 0, "failed": 0, "details": []}
    ensure_im_tables()
    import quantia.lib.database as mdb
    limit = max(1, min(int(limit or 20), 100))
    rows = mdb.executeSqlFetch(
        f"SELECT id, source_channel, source_message_id, operator_id, operator_name, "
        f"command_type, paper_id, signal_id, code, direction, "
        f"amount, `value`, price_limit, status, expire_at, approved_at "
        f"FROM `{TRADE_COMMAND_TABLE}` "
        f"WHERE status='approved' ORDER BY id ASC LIMIT %s",
        (limit,),
    ) or []
    broker_impl = broker or _resolve_broker()
    stats = {"status": "ok", "broker": broker_impl.name, "processed": 0,
             "executed": 0, "expired": 0, "rejected": 0, "failed": 0,
             "details": []}
    for r in rows:
        cmd = {
            "id": r[0], "source_channel": r[1], "source_message_id": r[2],
            "operator_id": r[3], "operator_name": r[4],
            "command_type": r[5], "paper_id": r[6], "signal_id": r[7],
            "code": r[8], "direction": r[9],
            "amount": float(r[10]) if r[10] is not None else None,
            "value": float(r[11]) if r[11] is not None else None,
            "price_limit": float(r[12]) if r[12] is not None else None,
            "status": r[13], "expire_at": r[14], "approved_at": r[15],
        }
        stats["processed"] += 1
        risk = _second_stage_risk(cmd)
        if not risk["passed"]:
            new_status = "expired" if risk["error"] == "指令已过期" else "rejected"
            result = {"phase": "second_stage_risk", "risk": risk}
            _update_command_status(cmd["id"], new_status, result)
            _notify_execution(cmd, new_status, result)
            stats[new_status if new_status in stats else "rejected"] += 1
            stats["details"].append({"id": cmd["id"], "status": new_status,
                                     "error": risk["error"]})
            continue
        # 真实下单
        try:
            order = broker_impl.place_order(cmd)
        except Exception as exc:
            logging.exception("[live] broker 异常 cmd=%s", cmd["id"])
            order = BrokerOrderResult(ok=False, error=f"broker_exception: {exc}")
        result = {"phase": "broker_call", "broker": broker_impl.name,
                  "risk": risk, **order.to_dict()}
        new_status = "executed" if order.ok else "failed"
        _update_command_status(cmd["id"], new_status, result)
        _notify_execution(cmd, new_status, result)
        stats[new_status] += 1
        stats["details"].append({"id": cmd["id"], "status": new_status,
                                 "order_id": order.order_id,
                                 "error": order.error or ""})
    return stats
