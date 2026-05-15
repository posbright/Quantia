#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import datetime
import hashlib
import json
import logging
import os
from typing import Any, Dict, Iterable, Optional

from .channels.dingtalk import DingTalkChannel
from .templates import build_trade_markdown

CONFIG_TABLE = "cn_stock_notification_config"
EVENT_TABLE = "cn_stock_notification_event"
DEFAULT_WEBHOOK_ENV = "QUANTIA_DINGTALK_WEBHOOK"
DEFAULT_SECRET_ENV = "QUANTIA_DINGTALK_SECRET"


def ensure_notification_tables():
    import quantia.lib.database as mdb

    if not mdb.checkTableIsExist(CONFIG_TABLE):
        mdb.executeSql(f'''
            CREATE TABLE IF NOT EXISTS `{CONFIG_TABLE}` (
                `id` INT AUTO_INCREMENT PRIMARY KEY,
                `paper_id` INT DEFAULT NULL,
                `channel` VARCHAR(32) NOT NULL DEFAULT 'dingtalk',
                `event_type` VARCHAR(64) NOT NULL DEFAULT 'paper_trade',
                `enabled` TINYINT(1) NOT NULL DEFAULT 0,
                `webhook_env` VARCHAR(128) DEFAULT '{DEFAULT_WEBHOOK_ENV}',
                `secret_env` VARCHAR(128) DEFAULT '{DEFAULT_SECRET_ENV}',
                `summary_config` LONGTEXT,
                `detail_config` LONGTEXT,
                `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
                `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX `idx_paper_event` (`paper_id`, `event_type`),
                INDEX `idx_channel_enabled` (`channel`, `enabled`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        ''')

    if not mdb.checkTableIsExist(EVENT_TABLE):
        mdb.executeSql(f'''
            CREATE TABLE IF NOT EXISTS `{EVENT_TABLE}` (
                `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
                `dedupe_key` VARCHAR(128) NOT NULL,
                `paper_id` INT DEFAULT NULL,
                `event_type` VARCHAR(64) NOT NULL,
                `channel` VARCHAR(32) NOT NULL,
                `trade_date` DATE DEFAULT NULL,
                `code` VARCHAR(16) DEFAULT NULL,
                `direction` VARCHAR(16) DEFAULT NULL,
                `status` VARCHAR(20) NOT NULL DEFAULT 'pending',
                `retry_count` INT NOT NULL DEFAULT 0,
                `max_retries` INT NOT NULL DEFAULT 3,
                `next_retry_at` DATETIME DEFAULT NULL,
                `payload_json` LONGTEXT,
                `response_json` LONGTEXT,
                `error_message` VARCHAR(1000) DEFAULT NULL,
                `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
                `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                `sent_at` DATETIME DEFAULT NULL,
                UNIQUE KEY `uq_dedupe_key` (`dedupe_key`),
                INDEX `idx_status_retry` (`status`, `next_retry_at`),
                INDEX `idx_paper_trade` (`paper_id`, `trade_date`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        ''')


def build_trade_dedupe_key(paper_id: int, trade: Any, trade_date: Any, channel: str = "dingtalk") -> str:
    raw = "|".join([
        "paper_trade",
        str(channel),
        str(paper_id),
        str(trade_date),
        str(getattr(trade, "code", "")),
        str(getattr(trade, "direction", "")),
        str(getattr(trade, "amount", "")),
        str(getattr(trade, "price", "")),
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:64]


def _json_default(value):
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat(sep=" ") if isinstance(value, datetime.datetime) else value.isoformat()
    return str(value)


def _load_config(paper_id: int, event_type: str, channel: str = "dingtalk") -> Dict[str, Any]:
    import quantia.lib.database as mdb

    rows = None
    try:
        rows = mdb.executeSqlFetch(
            f"SELECT enabled, webhook_env, secret_env, summary_config, detail_config "
            f"FROM `{CONFIG_TABLE}` WHERE channel=%s AND event_type IN (%s, '*') "
            f"AND (paper_id=%s OR paper_id IS NULL) "
            f"ORDER BY CASE WHEN paper_id=%s THEN 0 ELSE 1 END, id DESC LIMIT 1",
            (channel, event_type, paper_id, paper_id),
        )
    except Exception as exc:
        logging.warning(f"[通知] 读取通知配置失败，使用环境变量默认配置: {exc}")

    if rows:
        row = rows[0]
        webhook_env = row[1] or DEFAULT_WEBHOOK_ENV
        secret_env = row[2] or DEFAULT_SECRET_ENV
        return {
            "enabled": bool(row[0]),
            "webhook": os.getenv(webhook_env, ""),
            "secret": os.getenv(secret_env, ""),
            "webhook_env": webhook_env,
            "secret_env": secret_env,
        }

    webhook = os.getenv(DEFAULT_WEBHOOK_ENV, "")
    return {
        "enabled": bool(webhook),
        "webhook": webhook,
        "secret": os.getenv(DEFAULT_SECRET_ENV, ""),
        "webhook_env": DEFAULT_WEBHOOK_ENV,
        "secret_env": DEFAULT_SECRET_ENV,
    }


def _insert_event(event: Dict[str, Any]) -> Optional[int]:
    import quantia.lib.database as mdb

    with mdb.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"INSERT IGNORE INTO `{EVENT_TABLE}` "
                "(dedupe_key, paper_id, event_type, channel, trade_date, code, direction, status, payload_json, error_message) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    event["dedupe_key"], event.get("paper_id"), event.get("event_type"), event.get("channel"),
                    event.get("trade_date"), event.get("code"), event.get("direction"), event.get("status", "pending"),
                    json.dumps(event.get("payload"), ensure_ascii=False, default=_json_default),
                    event.get("error_message"),
                ),
            )
            if cur.rowcount == 0:
                return None
            cur.execute("SELECT LAST_INSERT_ID()")
            row = cur.fetchone()
            return int(row[0]) if row and row[0] is not None else None


def _update_event_status(event_id: int, status: str, response: Optional[Dict[str, Any]] = None, error: str = ""):
    import quantia.lib.database as mdb

    sent_at = datetime.datetime.now() if status == "sent" else None
    next_retry_at = datetime.datetime.now() + datetime.timedelta(minutes=5) if status == "failed" else None
    mdb.executeSql(
        f"UPDATE `{EVENT_TABLE}` SET status=%s, response_json=%s, error_message=%s, next_retry_at=%s, "
        "retry_count=CASE WHEN %s='failed' THEN retry_count + 1 ELSE retry_count END, sent_at=%s "
        "WHERE id=%s",
        (status, json.dumps(response or {}, ensure_ascii=False, default=_json_default), error[:1000], next_retry_at, status, sent_at, event_id),
    )


def _send_payload_for_event(event_id: int, paper_id: int, event_type: str, payload: Dict[str, Any]) -> bool:
    config = _load_config(paper_id, event_type, "dingtalk")
    if not config.get("enabled") or not config.get("webhook"):
        _update_event_status(event_id, "skipped", {}, "DingTalk notification disabled or webhook missing")
        return False
    result = DingTalkChannel(config["webhook"], config.get("secret", "")).send(payload)
    _update_event_status(event_id, "sent" if result.ok else "failed", result.response, result.error)
    return result.ok


def process_pending_notifications(limit: int = 20) -> Dict[str, int]:
    ensure_notification_tables()
    import quantia.lib.database as mdb

    rows = mdb.executeSqlFetch(
        f"SELECT id, paper_id, event_type, payload_json FROM `{EVENT_TABLE}` "
        "WHERE status IN ('pending', 'failed') "
        "AND retry_count < max_retries "
        "AND (next_retry_at IS NULL OR next_retry_at <= NOW()) "
        "ORDER BY created_at ASC LIMIT %s",
        (int(limit),),
    ) or []
    stats = {"processed": 0, "sent": 0, "failed": 0, "skipped": 0}
    for row in rows:
        event_id, paper_id, event_type, payload_json = row
        stats["processed"] += 1
        try:
            payload = json.loads(payload_json or "{}")
            if _send_payload_for_event(int(event_id), int(paper_id or 0), event_type, payload):
                stats["sent"] += 1
            else:
                refreshed = mdb.executeSqlFetch(
                    f"SELECT status FROM `{EVENT_TABLE}` WHERE id=%s", (event_id,)) or []
                current_status = refreshed[0][0] if refreshed else "failed"
                if current_status == "skipped":
                    stats["skipped"] += 1
                else:
                    stats["failed"] += 1
        except Exception as exc:
            stats["failed"] += 1
            _update_event_status(int(event_id), "failed", {}, str(exc))
    return stats


def enqueue_trade_notification(
    paper_id: int,
    trade: Any,
    trade_date: Any,
    executed_at: Optional[datetime.datetime] = None,
    send_now: bool = True,
    signal_id: Optional[int] = None,
    extra_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    ensure_notification_tables()
    channel = "dingtalk"
    event_type = "paper_trade"
    dedupe_key = build_trade_dedupe_key(paper_id, trade, trade_date, channel)
    event_data = {
        "dedupe_key": dedupe_key,
        "paper_id": paper_id,
        "event_type": event_type,
        "channel": channel,
        "trade_date": str(trade_date),
        "executed_at": executed_at,
        "code": getattr(trade, "code", ""),
        "name": getattr(trade, "name", ""),
        "direction": getattr(trade, "direction", ""),
        "price": getattr(trade, "price", None),
        "amount": getattr(trade, "amount", None),
        "value": getattr(trade, "value", None),
        "commission": getattr(trade, "commission", None),
        "tax": getattr(trade, "tax", None),
        # 文档 §7 模板字段：滑点 / 平仓盈亏 / 收益率（卖出时由 TradeRecord 填充）
        "slippage_cost": getattr(trade, "slippage_cost", None),
        "close_profit": getattr(trade, "close_profit", None),
        "return_rate": getattr(trade, "return_rate", None),
        "signal_id": signal_id,
    }
    # 文档 §7：模拟盘名称 / 策略名称 / 运行 ID / 成交后仓位 由 paper_engine
    # 通过 signal_meta 透传，避免模板再回查 DB。
    if isinstance(extra_meta, dict):
        for key in ("paper_name", "strategy_name", "strategy_code",
                    "run_id", "position_after_pct"):
            if key in extra_meta and extra_meta[key] is not None:
                event_data[key] = extra_meta[key]
        # 若 trade 已带这些字段则保留，否则用 meta 兜底
        for key in ("slippage_cost", "close_profit", "return_rate"):
            if event_data.get(key) in (None, 0, 0.0) and extra_meta.get(key) is not None:
                event_data[key] = extra_meta[key]
    # Phase 2: 若提供 signal_id，加载真实策略 reason/decision 注入模板上下文。
    if signal_id:
        try:
            from quantia.core.backtest.trade_signal_store import fetch_signal_with_decision
            sig_detail = fetch_signal_with_decision(int(signal_id))
            if sig_detail:
                event_data["reason"] = sig_detail.get("reason")
                event_data["reason_source"] = sig_detail.get("reason_source")
                event_data["decision_rules"] = sig_detail.get("rules") or []
                # Phase 4: 把 signal 表 ai_* 字段透传到模板上下文（缺省时模板自动隐藏 AI 块）
                event_data["ai_score"] = sig_detail.get("ai_score")
                event_data["ai_action"] = sig_detail.get("ai_action")
                event_data["ai_gate_result"] = sig_detail.get("ai_gate_result")
                # 详细证据/风险/置信度等通过 ai_score_id 关联表查询，避免模板渲染时再次访问 DB
                ai_score_id = sig_detail.get("ai_score_id")
                if ai_score_id:
                    try:
                        from quantia.ai_decision.config import SCORE_TABLE
                        import quantia.lib.database as _mdb
                        rows = _mdb.executeSqlFetch(
                            f"SELECT confidence, reason_summary, evidence, risk_flags "
                            f"FROM `{SCORE_TABLE}` WHERE id=%s LIMIT 1",
                            (int(ai_score_id),),
                        ) or []
                        if rows:
                            r = rows[0]
                            event_data["ai_confidence"] = r[0]
                            event_data["ai_reason_summary"] = r[1]
                            try:
                                import json as _json
                                event_data["ai_evidence"] = _json.loads(r[2]) if isinstance(r[2], (str, bytes)) else r[2]
                                event_data["ai_risk_flags"] = _json.loads(r[3]) if isinstance(r[3], (str, bytes)) else r[3]
                            except Exception:
                                event_data["ai_evidence"] = []
                                event_data["ai_risk_flags"] = []
                    except Exception as _ai_err:
                        logging.debug("[通知] 加载 AI 评分详情失败: %s", _ai_err)
        except Exception as exc:
            logging.warning(f"[通知] 读取 signal_id={signal_id} 详情失败，模板使用兜底说明: {exc}")
    message = build_trade_markdown(event_data)
    config = _load_config(paper_id, event_type, channel)
    payload = DingTalkChannel.build_markdown_payload(message["title"], message["markdown"])

    event = {
        **event_data,
        "payload": payload,
        "status": "pending" if config.get("enabled") and config.get("webhook") else "skipped",
        "error_message": "" if config.get("enabled") and config.get("webhook") else "DingTalk notification disabled or webhook missing",
    }
    event_id = _insert_event(event)
    if event_id is None:
        return {"created": False, "sent": False, "dedupe_key": dedupe_key}

    if event["status"] == "skipped" or not send_now:
        return {"created": True, "sent": False, "event_id": event_id, "status": event["status"], "dedupe_key": dedupe_key}

    sent = _send_payload_for_event(event_id, paper_id, event_type, payload)
    return {
        "created": True,
        "sent": sent,
        "event_id": event_id,
        "status": "sent" if sent else "failed",
        "dedupe_key": dedupe_key,
    }


def notify_trade_records(
    paper_id: int,
    trade_records: Iterable[Any],
    trade_date: Any,
    executed_at: Optional[datetime.datetime] = None,
    signal_meta: Optional[Iterable[Dict[str, Any]]] = None,
) -> Dict[str, int]:
    stats = {"created": 0, "sent": 0, "failed": 0, "skipped": 0, "duplicates": 0}
    meta_list = list(signal_meta or [])
    for idx, trade in enumerate(trade_records or []):
        signal_id = None
        meta = meta_list[idx] if idx < len(meta_list) and isinstance(meta_list[idx], dict) else {}
        if meta:
            signal_id = meta.get("signal_id")
        try:
            result = enqueue_trade_notification(
                paper_id, trade, trade_date,
                executed_at=executed_at, send_now=True, signal_id=signal_id,
                extra_meta=meta or None)
            if not result.get("created"):
                stats["duplicates"] += 1
            elif result.get("sent"):
                stats["created"] += 1
                stats["sent"] += 1
            else:
                stats["created"] += 1
                status = result.get("status")
                if status == "skipped":
                    stats["skipped"] += 1
                elif status == "failed":
                    stats["failed"] += 1
        except Exception as exc:
            stats["failed"] += 1
            logging.warning(f"[通知] 模拟交易成交通知处理失败(不影响交易): {exc}", exc_info=True)
    return stats
