# -*- coding: utf-8 -*-
"""Phase 6: IM 指令服务。

职责：
- ``is_enabled()``：读取 env ``QUANTIA_IM_COMMAND_ENABLED``（默认 false）。
- ``handle_dingtalk_callback()``：完整的回调处理（签名 / 白名单 / 解析 /
  风控 / 落库），**永不直接调券商**，仅写 ``cn_stock_trade_command``。
- ``list_commands()`` / ``get_command()``：管理面读接口。
- 操作人白名单 CRUD。

风控字段（环境变量，可被前端配置覆盖）：
- ``QUANTIA_IM_MAX_SINGLE_VALUE``（默认 100000 元）
- ``QUANTIA_IM_MAX_DAILY_VALUE``（默认 500000 元）
- ``QUANTIA_IM_COMMAND_TTL_SECONDS``（默认 300 秒过期）

设计要点：
- 风控失败 → status=rejected，仍然落库（可审计）。
- 已对同一 ``signal_id`` 处理过的 confirm 指令不能再次确认（status='approved' 或 'executed'）。
- 同一 (channel, message_id) 第二次回调直接复用第一次的指令记录（防重放）。
- 单笔金额优先用 ``value``，无则按 ``amount * price_limit`` 估算；都没有时记 0 不阻断。
"""
from __future__ import annotations

import datetime
import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from .schema import (
    OPERATOR_WHITELIST_TABLE, TRADE_COMMAND_TABLE, ensure_im_tables,
)
from .signature import verify_dingtalk_signature

ENABLED_ENV = "QUANTIA_IM_COMMAND_ENABLED"
SECRET_ENV = "QUANTIA_DINGTALK_CALLBACK_SECRET"
MAX_SINGLE_ENV = "QUANTIA_IM_MAX_SINGLE_VALUE"
MAX_DAILY_ENV = "QUANTIA_IM_MAX_DAILY_VALUE"
TTL_ENV = "QUANTIA_IM_COMMAND_TTL_SECONDS"

DEFAULT_MAX_SINGLE = 100000.0
DEFAULT_MAX_DAILY = 500000.0
DEFAULT_TTL_SECONDS = 300

VALID_COMMAND_TYPES = {"confirm_buy", "confirm_sell", "cancel", "adjust"}
VALID_DIRECTIONS = {"buy", "sell"}


# ─────────────── 配置读取 ───────────────


def is_enabled() -> bool:
    """IM 指令总开关，默认关闭。

    通过环境变量 ``QUANTIA_IM_COMMAND_ENABLED`` 控制，
    取值 ``1/true/yes/on``（大小写不敏感）视作启用。
    """
    val = os.getenv(ENABLED_ENV, "")
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _to_float(v: Any, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _to_int(v: Any, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _now() -> datetime.datetime:
    return datetime.datetime.now()


def _max_single_value() -> float:
    return _to_float(os.getenv(MAX_SINGLE_ENV), DEFAULT_MAX_SINGLE)


def _max_daily_value() -> float:
    return _to_float(os.getenv(MAX_DAILY_ENV), DEFAULT_MAX_DAILY)


def _ttl_seconds() -> int:
    return _to_int(os.getenv(TTL_ENV), DEFAULT_TTL_SECONDS)


# ─────────────── 白名单 ───────────────


def list_operators(channel: Optional[str] = None) -> List[Dict[str, Any]]:
    ensure_im_tables()
    _ensure_modified_by_column()
    import quantia.lib.database as mdb
    where = "1=1"
    params: Tuple[Any, ...] = ()
    if channel:
        where = "channel=%s"
        params = (channel,)
    rows = mdb.executeSqlFetch(
        f"SELECT id, channel, operator_id, operator_name, enabled, note, modified_by, "
        f"created_at, updated_at FROM `{OPERATOR_WHITELIST_TABLE}` "
        f"WHERE {where} ORDER BY id DESC",
        params,
    ) or []
    out = []
    for r in rows:
        out.append({
            "id": int(r[0]),
            "channel": r[1],
            "operator_id": r[2],
            "operator_name": r[3],
            "enabled": bool(r[4]),
            "note": r[5],
            "modified_by": r[6] or None,
            "created_at": r[7].strftime("%Y-%m-%d %H:%M:%S") if r[7] else None,
            "updated_at": r[8].strftime("%Y-%m-%d %H:%M:%S") if r[8] else None,
        })
    return out


def _ensure_modified_by_column():
    """如旧库无 modified_by 列则补齐。Phase 8 鉴权上线前默认写入 'system'。失败仅 warning。"""
    try:
        import quantia.lib.database as mdb
    except Exception:
        return
    try:
        rows = mdb.executeSqlFetch(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema=DATABASE() AND table_name=%s AND column_name='modified_by' LIMIT 1",
            (OPERATOR_WHITELIST_TABLE,),
        ) or []
        if not rows:
            mdb.executeSql(
                f"ALTER TABLE `{OPERATOR_WHITELIST_TABLE}` "
                "ADD COLUMN `modified_by` VARCHAR(64) NULL DEFAULT NULL AFTER `note`"
            )
    except Exception as exc:
        import logging
        logging.debug("[im.service] 检查/添加 modified_by 列失败: %s", exc)


def save_operator(payload: Dict[str, Any]) -> Dict[str, Any]:
    ensure_im_tables()
    _ensure_modified_by_column()
    import quantia.lib.database as mdb
    channel = (payload.get("channel") or "dingtalk").strip().lower()
    op_id = (payload.get("operator_id") or "").strip()
    op_name = (payload.get("operator_name") or "").strip() or None
    enabled = 1 if payload.get("enabled", True) else 0
    note = (payload.get("note") or "").strip() or None
    if not op_id:
        raise ValueError("operator_id 不能为空")
    if "/" in op_id or " " in op_id:
        raise ValueError("operator_id 含非法字符")
    # Phase 8 鉴权上线前，所有修改记录为 'system'。
    modified_by = (payload.get("modified_by") or "system").strip()[:64] or "system"
    cid = _to_int(payload.get("id"), 0)
    if cid:
        mdb.executeSql(
            f"UPDATE `{OPERATOR_WHITELIST_TABLE}` SET channel=%s, operator_id=%s, "
            f"operator_name=%s, enabled=%s, note=%s, modified_by=%s WHERE id=%s",
            (channel, op_id, op_name, enabled, note, modified_by, cid),
        )
    else:
        # ON DUPLICATE KEY UPDATE 处理 (channel, operator_id) 已存在的情况
        mdb.executeSql(
            f"INSERT INTO `{OPERATOR_WHITELIST_TABLE}` "
            f"(channel, operator_id, operator_name, enabled, note, modified_by) "
            f"VALUES (%s,%s,%s,%s,%s,%s) "
            f"ON DUPLICATE KEY UPDATE operator_name=VALUES(operator_name), "
            f"enabled=VALUES(enabled), note=VALUES(note), modified_by=VALUES(modified_by)",
            (channel, op_id, op_name, enabled, note, modified_by),
        )
    rows = mdb.executeSqlFetch(
        f"SELECT id, channel, operator_id, operator_name, enabled, note, modified_by, "
        f"created_at, updated_at FROM `{OPERATOR_WHITELIST_TABLE}` "
        f"WHERE channel=%s AND operator_id=%s LIMIT 1",
        (channel, op_id),
    ) or []
    if not rows:
        return {"channel": channel, "operator_id": op_id, "enabled": bool(enabled)}
    r = rows[0]
    return {
        "id": int(r[0]), "channel": r[1], "operator_id": r[2],
        "operator_name": r[3], "enabled": bool(r[4]), "note": r[5],
        "modified_by": r[6] or None,
        "created_at": r[7].strftime("%Y-%m-%d %H:%M:%S") if r[7] else None,
        "updated_at": r[8].strftime("%Y-%m-%d %H:%M:%S") if r[8] else None,
    }


def delete_operator(op_id: int) -> bool:
    ensure_im_tables()
    import quantia.lib.database as mdb
    mdb.executeSql(
        f"DELETE FROM `{OPERATOR_WHITELIST_TABLE}` WHERE id=%s", (int(op_id),),
    )
    return True


def _is_operator_allowed(channel: str, operator_id: str) -> bool:
    if not operator_id:
        return False
    import quantia.lib.database as mdb
    rows = mdb.executeSqlFetch(
        f"SELECT enabled FROM `{OPERATOR_WHITELIST_TABLE}` "
        f"WHERE channel=%s AND operator_id=%s LIMIT 1",
        (channel, operator_id),
    ) or []
    return bool(rows) and bool(rows[0][0])


# ─────────────── 风控 ───────────────


def _estimate_value(amount: Optional[float], price_limit: Optional[float],
                    explicit_value: Optional[float]) -> float:
    if explicit_value is not None and explicit_value > 0:
        return float(explicit_value)
    if amount and price_limit:
        return float(amount) * float(price_limit)
    return 0.0


def _daily_used_value(operator_id: str, channel: str) -> float:
    import quantia.lib.database as mdb
    today = datetime.date.today()
    rows = mdb.executeSqlFetch(
        f"SELECT COALESCE(SUM(`value`), 0) FROM `{TRADE_COMMAND_TABLE}` "
        f"WHERE operator_id=%s AND source_channel=%s "
        f"AND status IN ('approved','executed') "
        f"AND DATE(created_at)=%s",
        (operator_id, channel, today),
    ) or []
    if not rows:
        return 0.0
    try:
        return float(rows[0][0] or 0)
    except Exception:
        return 0.0


def _signal_already_confirmed(signal_id: int) -> bool:
    import quantia.lib.database as mdb
    rows = mdb.executeSqlFetch(
        f"SELECT id FROM `{TRADE_COMMAND_TABLE}` "
        f"WHERE signal_id=%s AND status IN ('approved','executed') LIMIT 1",
        (int(signal_id),),
    ) or []
    return bool(rows)


def _run_risk_check(channel: str, operator_id: str, command_type: str,
                    signal_id: Optional[int], value_estimate: float
                    ) -> Tuple[bool, Dict[str, Any]]:
    """返回 (passed, risk_result_dict)。"""
    result: Dict[str, Any] = {
        "checks": [],
        "passed": True,
        "value_estimate": round(value_estimate, 2),
    }
    # 1. 单笔金额
    max_single = _max_single_value()
    ok = value_estimate <= max_single
    result["checks"].append({
        "name": "max_single_value", "limit": max_single,
        "actual": round(value_estimate, 2), "passed": ok,
    })
    if not ok:
        result["passed"] = False
    # 2. 单日金额
    max_daily = _max_daily_value()
    used = _daily_used_value(operator_id, channel)
    after = used + value_estimate
    ok2 = after <= max_daily
    result["checks"].append({
        "name": "max_daily_value", "limit": max_daily,
        "used_today": round(used, 2), "after": round(after, 2), "passed": ok2,
    })
    if not ok2:
        result["passed"] = False
    # 3. 重复确认同一信号
    if command_type in {"confirm_buy", "confirm_sell"} and signal_id:
        already = _signal_already_confirmed(signal_id)
        result["checks"].append({
            "name": "signal_unique_confirm", "signal_id": signal_id,
            "already_confirmed": already, "passed": not already,
        })
        if already:
            result["passed"] = False
    return result["passed"], result


# ─────────────── 解析回调 payload ───────────────


def _parse_command_text(text: str) -> Dict[str, Any]:
    """从 IM 文本解析指令。

    支持简单格式（建议在通知卡片按钮中预填）：
        confirm_buy paper=1 signal=42 code=600519 amount=100 value=20000
        confirm_sell paper=1 signal=43 code=600519 amount=100
        cancel signal=42
    """
    out: Dict[str, Any] = {}
    if not text:
        return out
    parts = text.strip().split()
    if not parts:
        return out
    out["command_type"] = parts[0].lower()
    for token in parts[1:]:
        if "=" not in token:
            continue
        k, v = token.split("=", 1)
        out[k.strip().lower()] = v.strip()
    return out


def _parse_callback_payload(body: Dict[str, Any]) -> Dict[str, Any]:
    """归一化回调 payload → 内部 command dict。

    优先级：body 顶层显式字段 > body.text.content 解析。
    """
    parsed = dict(body or {})
    text_obj = body.get("text") if isinstance(body, dict) else None
    if isinstance(text_obj, dict):
        parsed_text = _parse_command_text(text_obj.get("content") or "")
        for k, v in parsed_text.items():
            parsed.setdefault(k, v)
    return parsed


# ─────────────── 主回调处理 ───────────────


def handle_dingtalk_callback(headers: Dict[str, str],
                             body: Dict[str, Any],
                             *,
                             secret_override: Optional[str] = None,
                             ) -> Dict[str, Any]:
    """处理钉钉回调。返回 ``{ok, status, command_id, error}``。

    ``status`` 取值：disabled / signature_failed / unauthorized /
    duplicate / expired / invalid / rejected / approved。
    """
    if not is_enabled():
        return {"ok": False, "status": "disabled",
                "error": f"IM 指令未启用（{ENABLED_ENV} != 1）"}

    ensure_im_tables()
    import quantia.lib.database as mdb

    timestamp = headers.get("timestamp") or headers.get("Timestamp") or ""
    sign = headers.get("sign") or headers.get("Sign") or ""
    secret = secret_override if secret_override is not None \
        else os.getenv(SECRET_ENV, "")
    sig_err = verify_dingtalk_signature(secret, str(timestamp), str(sign))
    if sig_err:
        return {"ok": False, "status": "signature_failed", "error": sig_err}

    parsed = _parse_callback_payload(body or {})
    channel = (parsed.get("source_channel") or "dingtalk").strip().lower()
    msg_id = str(parsed.get("source_message_id") or parsed.get("msgId")
                 or "").strip() or None
    op_id = str(parsed.get("operator_id") or parsed.get("senderStaffId")
                or "").strip()
    op_name = str(parsed.get("operator_name") or parsed.get("senderNick")
                  or "").strip() or None
    command_type = (parsed.get("command_type") or "").strip().lower()
    paper_id = _to_int(parsed.get("paper") or parsed.get("paper_id"), 0) or None
    signal_id = _to_int(parsed.get("signal") or parsed.get("signal_id"), 0) or None
    code = (parsed.get("code") or "").strip() or None
    direction = (parsed.get("direction") or "").strip().lower() or None
    if not direction:
        if command_type == "confirm_buy":
            direction = "buy"
        elif command_type == "confirm_sell":
            direction = "sell"
    amount = _to_float(parsed.get("amount"), 0.0) or None
    value = _to_float(parsed.get("value"), 0.0) or None
    price_limit = _to_float(parsed.get("price") or parsed.get("price_limit"),
                            0.0) or None

    # 防重放：(channel, msg_id) UNIQUE → 已存在则直接返回原记录
    if msg_id:
        rows = mdb.executeSqlFetch(
            f"SELECT id, status FROM `{TRADE_COMMAND_TABLE}` "
            f"WHERE source_channel=%s AND source_message_id=%s LIMIT 1",
            (channel, msg_id),
        ) or []
        if rows:
            return {"ok": True, "status": "duplicate",
                    "command_id": int(rows[0][0]),
                    "original_status": rows[0][1]}

    # 校验指令格式
    if command_type not in VALID_COMMAND_TYPES:
        return _persist_invalid(channel, msg_id, op_id, op_name, parsed,
                                f"非法 command_type: {command_type}")
    if direction and direction not in VALID_DIRECTIONS:
        return _persist_invalid(channel, msg_id, op_id, op_name, parsed,
                                f"非法 direction: {direction}")

    # 白名单
    if not _is_operator_allowed(channel, op_id):
        return _persist_invalid(channel, msg_id, op_id, op_name, parsed,
                                f"操作人 {op_id} 不在白名单",
                                status="unauthorized",
                                command_type=command_type, signal_id=signal_id,
                                paper_id=paper_id, code=code, direction=direction,
                                amount=amount, value=value, price_limit=price_limit)

    # 风控
    value_est = _estimate_value(amount, price_limit, value)
    passed, risk_result = _run_risk_check(channel, op_id, command_type,
                                          signal_id, value_est)
    expire_at = _now() + datetime.timedelta(seconds=_ttl_seconds())
    status = "approved" if passed else "rejected"
    # 持久化时统一写入估算金额，方便后续按 operator+date 累计求和
    persist_value = value if value is not None else (
        value_est if value_est > 0 else None)

    cid = _insert_command(
        channel=channel, msg_id=msg_id, op_id=op_id, op_name=op_name,
        command_type=command_type, paper_id=paper_id, signal_id=signal_id,
        code=code, direction=direction, amount=amount, value=persist_value,
        price_limit=price_limit, status=status,
        risk_check=risk_result, request_payload=parsed,
        expire_at=expire_at, approved_at=_now() if passed else None,
    )
    return {"ok": passed, "status": status, "command_id": cid,
            "risk_result": risk_result}


def _persist_invalid(channel: str, msg_id: Optional[str],
                     op_id: Optional[str], op_name: Optional[str],
                     payload: Dict[str, Any], err: str,
                     status: str = "invalid",
                     **extra) -> Dict[str, Any]:
    cid = _insert_command(
        channel=channel, msg_id=msg_id,
        op_id=op_id or None, op_name=op_name,
        command_type=extra.get("command_type") or "unknown",
        paper_id=extra.get("paper_id"), signal_id=extra.get("signal_id"),
        code=extra.get("code"), direction=extra.get("direction"),
        amount=extra.get("amount"), value=extra.get("value"),
        price_limit=extra.get("price_limit"),
        status=status,
        risk_check={"error": err},
        request_payload=payload,
        expire_at=None, approved_at=None,
    )
    return {"ok": False, "status": status, "command_id": cid, "error": err}


def _insert_command(*, channel: str, msg_id: Optional[str],
                    op_id: Optional[str], op_name: Optional[str],
                    command_type: str, paper_id: Optional[int],
                    signal_id: Optional[int], code: Optional[str],
                    direction: Optional[str], amount: Optional[float],
                    value: Optional[float], price_limit: Optional[float],
                    status: str, risk_check: Dict[str, Any],
                    request_payload: Dict[str, Any],
                    expire_at: Optional[datetime.datetime],
                    approved_at: Optional[datetime.datetime]) -> int:
    import quantia.lib.database as mdb
    risk_json = json.dumps(risk_check, ensure_ascii=False, default=str)
    payload_json = json.dumps(request_payload, ensure_ascii=False, default=str)
    try:
        with mdb.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"INSERT INTO `{TRADE_COMMAND_TABLE}` "
                    f"(source_channel, source_message_id, operator_id, operator_name, "
                    f" command_type, paper_id, signal_id, code, direction, "
                    f" amount, `value`, price_limit, status, "
                    f" risk_check_json, request_payload, expire_at, approved_at) "
                    f"VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (channel, msg_id, op_id, op_name,
                     command_type, paper_id, signal_id, code, direction,
                     amount, value, price_limit, status,
                     risk_json, payload_json, expire_at, approved_at),
                )
                cur.execute("SELECT LAST_INSERT_ID()")
                row = cur.fetchone()
                conn.commit()
                return int(row[0]) if row and row[0] is not None else 0
    except Exception as exc:
        logging.exception("[im.service] 写入指令失败: %s", exc)
        return 0


# ─────────────── 管理面读接口 ───────────────


_COMMAND_COLS = (
    "id, source_channel, source_message_id, operator_id, operator_name, "
    "command_type, paper_id, signal_id, code, direction, "
    "amount, `value`, price_limit, status, "
    "risk_check_json, request_payload, expire_at, approved_at, executed_at, "
    "execution_result, created_at, updated_at"
)


def _row_to_command(row) -> Dict[str, Any]:
    def _dt(v):
        return v.strftime("%Y-%m-%d %H:%M:%S") if v else None

    def _safe_json(v):
        if not v:
            return None
        if not isinstance(v, str):
            return v
        try:
            return json.loads(v)
        except Exception:
            return v

    return {
        "id": int(row[0]),
        "source_channel": row[1],
        "source_message_id": row[2],
        "operator_id": row[3],
        "operator_name": row[4],
        "command_type": row[5],
        "paper_id": row[6],
        "signal_id": row[7],
        "code": row[8],
        "direction": row[9],
        "amount": float(row[10]) if row[10] is not None else None,
        "value": float(row[11]) if row[11] is not None else None,
        "price_limit": float(row[12]) if row[12] is not None else None,
        "status": row[13],
        "risk_check": _safe_json(row[14]),
        "request_payload": _safe_json(row[15]),
        "expire_at": _dt(row[16]),
        "approved_at": _dt(row[17]),
        "executed_at": _dt(row[18]),
        "execution_result": _safe_json(row[19]),
        "created_at": _dt(row[20]),
        "updated_at": _dt(row[21]),
    }


def list_commands(status: Optional[str] = None,
                  paper_id: Optional[int] = None,
                  limit: int = 50,
                  offset: int = 0) -> List[Dict[str, Any]]:
    ensure_im_tables()
    import quantia.lib.database as mdb
    where = ["1=1"]
    params: List[Any] = []
    if status:
        where.append("status=%s")
        params.append(status)
    if paper_id is not None:
        where.append("paper_id=%s")
        params.append(int(paper_id))
    sql = (
        f"SELECT {_COMMAND_COLS} FROM `{TRADE_COMMAND_TABLE}` "
        f"WHERE {' AND '.join(where)} ORDER BY id DESC LIMIT %s OFFSET %s"
    )
    params.extend([int(max(1, min(limit, 200))), int(max(0, offset))])
    rows = mdb.executeSqlFetch(sql, tuple(params)) or []
    return [_row_to_command(r) for r in rows]


def get_command(command_id: int) -> Optional[Dict[str, Any]]:
    ensure_im_tables()
    import quantia.lib.database as mdb
    rows = mdb.executeSqlFetch(
        f"SELECT {_COMMAND_COLS} FROM `{TRADE_COMMAND_TABLE}` WHERE id=%s LIMIT 1",
        (int(command_id),),
    ) or []
    return _row_to_command(rows[0]) if rows else None
