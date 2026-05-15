# -*- coding: utf-8 -*-
"""Phase 5: 通知配置 CRUD + 测试发送 + 重试 API。

设计要点（对齐 §3.7 / §11 Phase 5 / §14.3）：

- 仅读写 ``cn_stock_notification_config`` 中的 **引用与开关**；webhook URL、
  secret 明文不在该表存储，仅通过环境变量名 (``webhook_env`` / ``secret_env``)
  引用。POST 接口拒绝写入任何 webhook 完整 URL 字段。
- 所有响应都不会回显环境变量明文，只回显引用名 + 是否已配置（is_configured）。
- 配置保存自动 +1 ``config_version``（如表已有该列）；运行时仍读取最新行，
  历史 ``cn_stock_notification_event`` 记录已是不可变快照。
- 测试发送写入一条专门的 dedupe_key（带时间戳），不复用真实 trade dedupe，
  发送结果落 ``cn_stock_notification_event`` 便于审计。
- 重试 API 仅触发已存在事件的发送（基于 ``process_pending_notifications``
  或单事件强制重置状态）。
"""
from __future__ import annotations

import datetime
import hashlib
import json
import logging
import os
from abc import ABC
from typing import Any, Dict, List, Optional

from tornado import gen

import quantia.web.base as webBase
from quantia import auth as _auth
from quantia.auth import require_login, require_role

CONFIG_TABLE = "cn_stock_notification_config"
EVENT_TABLE = "cn_stock_notification_event"

_VALID_CHANNELS = {"dingtalk", "wecom", "qq", "serverchan", "pushplus"}
_VALID_EVENT_TYPES = {"paper_trade", "run_failed", "run_summary", "risk_alert", "*"}


def _to_int(v, default=None):
    if v is None or v == "":
        return default
    try:
        return int(v)
    except Exception:
        return default


def _safe_json_loads(text: Any, default=None):
    if not text:
        return default
    if not isinstance(text, str):
        return text
    try:
        return json.loads(text)
    except Exception:
        return default


def _ensure_config_version_column():
    """如旧库无 config_version 列则补齐。失败仅 warning。"""
    try:
        import quantia.lib.database as mdb
    except Exception:
        return
    try:
        rows = mdb.executeSqlFetch(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema=DATABASE() AND table_name=%s AND column_name='config_version' LIMIT 1",
            (CONFIG_TABLE,),
        ) or []
        if not rows:
            mdb.executeSql(
                f"ALTER TABLE `{CONFIG_TABLE}` "
                "ADD COLUMN `config_version` INT NOT NULL DEFAULT 1 AFTER `detail_config`"
            )
    except Exception as exc:
        logging.debug("[notificationConfig] 检查/添加 config_version 列失败: %s", exc)


def _ensure_modified_by_column():
    """如旧库无 modified_by 列则补齐。Phase 8 鉴权体系上线前默认写入 'system'。失败仅 warning。"""
    try:
        import quantia.lib.database as mdb
    except Exception:
        return
    try:
        rows = mdb.executeSqlFetch(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema=DATABASE() AND table_name=%s AND column_name='modified_by' LIMIT 1",
            (CONFIG_TABLE,),
        ) or []
        if not rows:
            mdb.executeSql(
                f"ALTER TABLE `{CONFIG_TABLE}` "
                "ADD COLUMN `modified_by` VARCHAR(64) NULL DEFAULT NULL AFTER `config_version`"
            )
    except Exception as exc:
        logging.debug("[notificationConfig] 检查/添加 modified_by 列失败: %s", exc)


def _row_to_config(row) -> Dict[str, Any]:
    """SELECT 列序：id, paper_id, channel, event_type, enabled, webhook_env,
    secret_env, summary_config, detail_config, config_version, modified_by, created_at, updated_at."""
    webhook_env = row[5] or ""
    secret_env = row[6] or ""
    return {
        "id": int(row[0]),
        "paper_id": row[1],
        "channel": row[2],
        "event_type": row[3],
        "enabled": bool(row[4]),
        "webhook_env": webhook_env,
        "secret_env": secret_env,
        # 关键安全策略：只回显引用名 + 是否已注入环境变量；从不返回明文。
        "webhook_is_configured": bool(webhook_env and os.getenv(webhook_env)),
        "secret_is_configured": bool(secret_env and os.getenv(secret_env)),
        "summary_config": _safe_json_loads(row[7], default={}),
        "detail_config": _safe_json_loads(row[8], default={}),
        "config_version": int(row[9]) if row[9] is not None else 1,
        "modified_by": row[10] or None,
        "created_at": row[11].strftime("%Y-%m-%d %H:%M:%S") if row[11] else None,
        "updated_at": row[12].strftime("%Y-%m-%d %H:%M:%S") if row[12] else None,
    }


def _select_columns() -> str:
    return (
        "id, paper_id, channel, event_type, enabled, webhook_env, secret_env, "
        "summary_config, detail_config, config_version, modified_by, created_at, updated_at"
    )


def list_configs(paper_id: Optional[int] = None,
                 channel: Optional[str] = None) -> List[Dict[str, Any]]:
    from quantia.notification.service import ensure_notification_tables
    ensure_notification_tables()
    _ensure_config_version_column()
    _ensure_modified_by_column()
    import quantia.lib.database as mdb
    where = ["1=1"]
    params: List[Any] = []
    if paper_id is not None:
        where.append("(paper_id = %s OR paper_id IS NULL)")
        params.append(int(paper_id))
    if channel:
        where.append("channel = %s")
        params.append(channel)
    sql = (
        f"SELECT {_select_columns()} FROM `{CONFIG_TABLE}` "
        f"WHERE {' AND '.join(where)} ORDER BY id DESC"
    )
    rows = mdb.executeSqlFetch(sql, tuple(params)) or []
    return [_row_to_config(r) for r in rows]


def get_config(config_id: int) -> Optional[Dict[str, Any]]:
    from quantia.notification.service import ensure_notification_tables
    ensure_notification_tables()
    _ensure_config_version_column()
    _ensure_modified_by_column()
    import quantia.lib.database as mdb
    rows = mdb.executeSqlFetch(
        f"SELECT {_select_columns()} FROM `{CONFIG_TABLE}` WHERE id=%s LIMIT 1",
        (int(config_id),),
    ) or []
    return _row_to_config(rows[0]) if rows else None


def _validate_payload(p: Dict[str, Any]) -> Optional[str]:
    channel = (p.get("channel") or "dingtalk").strip().lower()
    if channel not in _VALID_CHANNELS:
        return f"非法 channel: {channel}"
    et = (p.get("event_type") or "paper_trade").strip()
    if et not in _VALID_EVENT_TYPES:
        return f"非法 event_type: {et}"
    # 安全：禁止前端写入 webhook URL / secret 明文
    for forbidden in ("webhook_url", "webhook", "secret", "secret_value", "api_key", "token"):
        if forbidden in p:
            return f"前端不允许直接写入敏感字段 {forbidden}（请使用环境变量并仅保存 *_env 引用）"
    for field in ("webhook_env", "secret_env"):
        v = p.get(field)
        if v is None:
            continue
        if not isinstance(v, str):
            return f"{field} 必须为字符串环境变量名"
        if not v:
            continue
        # 环境变量名不会含有 URL 字符或空格
        if "/" in v or "http" in v.lower() or " " in v:
            return f"{field} 看起来像 URL 或包含空格，请只填写环境变量名"
        # 常见密钥前缀
        if v.startswith("sk-") or v.startswith("Bearer "):
            return f"{field} 看起来像密钥本身，请只填写环境变量名"
        # 钉钉 secret 通常以 SEC 开头且长度 ≥ 64；环境变量名 SEC* 一般较短
        if v.startswith("SEC") and len(v) >= 40:
            return f"{field} 看起来像钉钉 secret 本身，请只填写环境变量名"
    return None


def save_config(payload: Dict[str, Any]) -> Dict[str, Any]:
    """新增或更新配置。返回保存后的完整记录（包含递增后的 config_version）。"""
    err = _validate_payload(payload)
    if err:
        raise ValueError(err)
    from quantia.notification.service import ensure_notification_tables
    ensure_notification_tables()
    _ensure_config_version_column()
    _ensure_modified_by_column()
    import quantia.lib.database as mdb

    cid = _to_int(payload.get("id"))
    paper_id = _to_int(payload.get("paper_id"))
    channel = (payload.get("channel") or "dingtalk").strip().lower()
    event_type = (payload.get("event_type") or "paper_trade").strip()
    enabled = 1 if payload.get("enabled") else 0
    webhook_env = (payload.get("webhook_env") or "").strip() or None
    secret_env = (payload.get("secret_env") or "").strip() or None
    summary_config = json.dumps(payload.get("summary_config") or {}, ensure_ascii=False)
    detail_config = json.dumps(payload.get("detail_config") or {}, ensure_ascii=False)
    # Phase 8 鉴权上线前，所有修改记录为 'system'；上线后由 handler 从 session 注入 username。
    modified_by = (payload.get("modified_by") or "system").strip()[:64] or "system"

    if cid:
        # UPDATE + version+1
        mdb.executeSql(
            f"UPDATE `{CONFIG_TABLE}` SET paper_id=%s, channel=%s, event_type=%s, "
            f"enabled=%s, webhook_env=%s, secret_env=%s, summary_config=%s, detail_config=%s, "
            f"modified_by=%s, config_version=COALESCE(config_version,1)+1 WHERE id=%s",
            (paper_id, channel, event_type, enabled, webhook_env, secret_env,
             summary_config, detail_config, modified_by, cid),
        )
        out = get_config(cid)
        if out is None:
            raise ValueError("配置不存在")
        return out
    else:
        with mdb.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"INSERT INTO `{CONFIG_TABLE}` "
                    f"(paper_id, channel, event_type, enabled, webhook_env, secret_env, "
                    f" summary_config, detail_config, config_version, modified_by) "
                    f"VALUES (%s,%s,%s,%s,%s,%s,%s,%s,1,%s)",
                    (paper_id, channel, event_type, enabled, webhook_env, secret_env,
                     summary_config, detail_config, modified_by),
                )
                cur.execute("SELECT LAST_INSERT_ID()")
                row = cur.fetchone()
                conn.commit()
                new_id = int(row[0]) if row and row[0] is not None else 0
        return get_config(new_id) or {"id": new_id}


def delete_config(config_id: int) -> bool:
    from quantia.notification.service import ensure_notification_tables
    ensure_notification_tables()
    import quantia.lib.database as mdb
    mdb.executeSql(
        f"DELETE FROM `{CONFIG_TABLE}` WHERE id=%s",
        (int(config_id),),
    )
    return True


def send_test_message(paper_id: Optional[int] = None,
                      channel: str = "dingtalk") -> Dict[str, Any]:
    """触发一条测试钉钉消息，返回 sent/skipped/failed 状态 + event_id。

    - 不复用交易 dedupe；用 ``test_dingtalk-<paper_id>-<timestamp>`` 作为 dedupe。
    - 失败仅记录，不抛异常（避免前端 500）。
    """
    if channel != "dingtalk":
        return {"ok": False, "status": "skipped", "error": f"暂不支持 channel={channel}"}
    try:
        from quantia.notification.service import (
            CONFIG_TABLE as _CT, EVENT_TABLE as _ET, _load_config, _insert_event,
            _update_event_status,
        )
        from quantia.notification.channels.dingtalk import DingTalkChannel
        from quantia.notification.service import ensure_notification_tables
        ensure_notification_tables()
    except Exception as exc:
        return {"ok": False, "status": "skipped", "error": f"通知模块加载失败: {exc}"}
    cfg = _load_config(paper_id or 0, "paper_trade", channel)
    if not cfg.get("enabled") or not cfg.get("webhook"):
        return {"ok": False, "status": "skipped",
                "error": "通知未启用或 webhook 环境变量为空（请检查 webhook_env 指向的环境变量是否已注入）"}
    ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    dedupe = hashlib.sha256(f"test|{channel}|{paper_id or 0}|{ts}".encode("utf-8")).hexdigest()[:64]
    title = "Phase5 通知测试"
    body = (
        f"## {title}\n\n"
        f"- 时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"- paper_id：{paper_id or '-'}\n"
        f"- 渠道：{channel}\n"
        f"- 说明：这是一条由 `/quantia/api/notification/config/test_send` 触发的测试消息，"
        f"不影响真实交易事件。\n"
    )
    payload = DingTalkChannel.build_markdown_payload(title, body)
    event_id = _insert_event({
        "dedupe_key": dedupe,
        "paper_id": paper_id,
        "event_type": "test_send",
        "channel": channel,
        "trade_date": datetime.date.today(),
        "code": None,
        "direction": None,
        "status": "pending",
        "payload": payload,
        "error_message": "",
    })
    if event_id is None:
        return {"ok": False, "status": "skipped",
                "error": "测试消息已存在（dedupe 命中），未重复发送"}
    try:
        result = DingTalkChannel(cfg["webhook"], cfg.get("secret", "")).send(payload)
        _update_event_status(event_id, "sent" if result.ok else "failed",
                             result.response, result.error)
        return {"ok": result.ok,
                "status": "sent" if result.ok else "failed",
                "event_id": event_id,
                "error": result.error or ""}
    except Exception as exc:
        _update_event_status(event_id, "failed", {}, str(exc))
        return {"ok": False, "status": "failed",
                "event_id": event_id, "error": str(exc)[:500]}


def retry_event(event_id: int) -> Dict[str, Any]:
    """强制重置单事件为 pending 并触发一次发送。"""
    from quantia.notification.service import (
        ensure_notification_tables, process_pending_notifications,
    )
    ensure_notification_tables()
    import quantia.lib.database as mdb
    rows = mdb.executeSqlFetch(
        f"SELECT id, status, retry_count FROM `{EVENT_TABLE}` WHERE id=%s",
        (int(event_id),),
    ) or []
    if not rows:
        return {"ok": False, "error": f"事件 {event_id} 不存在"}
    mdb.executeSql(
        f"UPDATE `{EVENT_TABLE}` SET status='pending', next_retry_at=NULL WHERE id=%s",
        (int(event_id),),
    )
    stats = process_pending_notifications(limit=20)
    rows = mdb.executeSqlFetch(
        f"SELECT status, error_message FROM `{EVENT_TABLE}` WHERE id=%s",
        (int(event_id),),
    ) or []
    if rows:
        return {"ok": rows[0][0] == "sent", "status": rows[0][0],
                "error": rows[0][1] or "", "process_stats": stats}
    return {"ok": False, "error": "事件状态查询失败", "process_stats": stats}


# ─────────────── Tornado handlers ───────────────


class _BaseConfigHandler(webBase.BaseHandler, ABC):
    def _write_json(self, data: Any, status: int = 200):
        self.set_status(status)
        self.set_header("Content-Type", "application/json; charset=utf-8")
        self.write(json.dumps(data, ensure_ascii=False, default=str))


class GetNotificationConfigListHandler(_BaseConfigHandler, ABC):
    @gen.coroutine
    def get(self):
        try:
            paper_id = _to_int(self.get_argument("paper_id", None))
            channel = self.get_argument("channel", None)
            data = list_configs(paper_id=paper_id, channel=channel)
            self._write_json({"ok": True, "data": data})
        except Exception as exc:
            logging.exception("[notificationConfig] list 失败")
            self._write_json({"ok": False, "error": str(exc)}, status=500)


class GetNotificationConfigDetailHandler(_BaseConfigHandler, ABC):
    @gen.coroutine
    def get(self):
        try:
            cid = _to_int(self.get_argument("id", None))
            if not cid:
                self._write_json({"ok": False, "error": "缺少 id"}, status=400)
                return
            cfg = get_config(cid)
            if cfg is None:
                self._write_json({"ok": False, "error": "未找到"}, status=404)
                return
            self._write_json({"ok": True, "data": cfg})
        except Exception as exc:
            logging.exception("[notificationConfig] detail 失败")
            self._write_json({"ok": False, "error": str(exc)}, status=500)


class SaveNotificationConfigHandler(_BaseConfigHandler, ABC):
    @require_role("admin", "operator")
    @gen.coroutine
    def post(self):
        try:
            try:
                body = json.loads(self.request.body or b"{}")
            except Exception:
                self._write_json({"ok": False, "error": "请求体非 JSON"}, status=400)
                return
            # Phase 8：启用鉴权后由 session 注入 modified_by；未启用时 require_login 设为 'system'。
            if getattr(self, "current_username", None):
                body["modified_by"] = self.current_username
            try:
                cfg = save_config(body)
            except ValueError as ve:
                self._write_json({"ok": False, "error": str(ve)}, status=400)
                return
            self._write_json({"ok": True, "data": cfg})
        except Exception as exc:
            logging.exception("[notificationConfig] save 失败")
            self._write_json({"ok": False, "error": str(exc)}, status=500)


class DeleteNotificationConfigHandler(_BaseConfigHandler, ABC):
    @require_role("admin", "operator")
    @gen.coroutine
    def post(self):
        try:
            try:
                body = json.loads(self.request.body or b"{}")
            except Exception:
                body = {}
            cid = _to_int(body.get("id") or self.get_argument("id", None))
            if not cid:
                self._write_json({"ok": False, "error": "缺少 id"}, status=400)
                return
            delete_config(cid)
            self._write_json({"ok": True})
        except Exception as exc:
            logging.exception("[notificationConfig] delete 失败")
            self._write_json({"ok": False, "error": str(exc)}, status=500)


class TestSendNotificationHandler(_BaseConfigHandler, ABC):
    @require_role("admin", "operator")
    @gen.coroutine
    def post(self):
        try:
            try:
                body = json.loads(self.request.body or b"{}")
            except Exception:
                body = {}
            paper_id = _to_int(body.get("paper_id"))
            channel = (body.get("channel") or "dingtalk").lower()
            result = send_test_message(paper_id=paper_id, channel=channel)
            self._write_json({"ok": bool(result.get("ok")), "data": result})
        except Exception as exc:
            logging.exception("[notificationConfig] test_send 失败")
            self._write_json({"ok": False, "error": str(exc)}, status=500)


class RetryNotificationEventHandler(_BaseConfigHandler, ABC):
    @require_role("admin", "operator")
    @gen.coroutine
    def post(self):
        try:
            try:
                body = json.loads(self.request.body or b"{}")
            except Exception:
                body = {}
            eid = _to_int(body.get("event_id") or self.get_argument("event_id", None))
            if not eid:
                self._write_json({"ok": False, "error": "缺少 event_id"}, status=400)
                return
            result = retry_event(eid)
            self._write_json({"ok": bool(result.get("ok")), "data": result})
        except Exception as exc:
            logging.exception("[notificationConfig] retry 失败")
            self._write_json({"ok": False, "error": str(exc)}, status=500)
