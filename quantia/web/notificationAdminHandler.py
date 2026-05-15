# -*- coding: utf-8 -*-
"""Phase 3 扩展：通知事件后台查看 API。

提供给后台/运维使用，用于查看历史发送到钉钉等渠道的消息内容、
发送状态、payload、错误信息和原始响应，以便排查发送失败、确认
通知摘要/详情是否符合预期、对账实际投递结果。

接口仅返回元数据 + 原始 payload/response/error；webhook URL 与
secret 等敏感字段不会进入 ``cn_stock_notification_event``，因此
本接口不会泄露密钥（密钥仅存在于环境变量与运行内存中）。

路由：
- GET /quantia/api/notification/event/list
    可选过滤：paper_id, status, channel, event_type, code, since (YYYY-MM-DD), limit (<=500)
- GET /quantia/api/notification/event/detail?event_id=
    返回 payload_json/response_json/error/状态等完整字段。
"""
from __future__ import annotations

import datetime
import json
import logging
from abc import ABC
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from tornado import gen

import quantia.web.base as webBase

EVENT_TABLE = "cn_stock_notification_event"

# 列表场景下默认裁剪 payload/response 长度，避免一次返回过大；
# 详情接口才返回完整内容。
_PAYLOAD_PREVIEW_LEN = 600


def _json_default(value):
    if isinstance(value, datetime.datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, datetime.date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def _safe_str(s: Any, max_len: int = 256) -> str:
    if s is None:
        return ""
    text = str(s)
    return text if len(text) <= max_len else text[:max_len]


def _try_parse_json(text: Any) -> Any:
    if not text:
        return None
    if not isinstance(text, str):
        return text
    try:
        return json.loads(text)
    except Exception:
        return text  # 原文字符串（解析失败时仍返回供肉眼排查）


def _query_events(filters: Dict[str, Any], limit: int) -> List[Tuple]:
    import quantia.lib.database as mdb

    where = ["1=1"]
    params: List[Any] = []
    if filters.get("paper_id") is not None:
        where.append("paper_id = %s")
        params.append(int(filters["paper_id"]))
    if filters.get("status"):
        where.append("status = %s")
        params.append(filters["status"])
    if filters.get("channel"):
        where.append("channel = %s")
        params.append(filters["channel"])
    if filters.get("event_type"):
        where.append("event_type = %s")
        params.append(filters["event_type"])
    if filters.get("code"):
        where.append("code = %s")
        params.append(filters["code"])
    if filters.get("since"):
        where.append("created_at >= %s")
        params.append(filters["since"])
    sql = (
        f"SELECT id, dedupe_key, paper_id, event_type, channel, trade_date, "
        f"code, direction, status, retry_count, max_retries, next_retry_at, "
        f"error_message, created_at, updated_at, sent_at, "
        f"payload_json, response_json "
        f"FROM `{EVENT_TABLE}` WHERE {' AND '.join(where)} "
        f"ORDER BY id DESC LIMIT %s"
    )
    params.append(int(limit))
    return mdb.executeSqlFetch(sql, tuple(params)) or []


def _row_to_summary(row: Tuple, include_full_payload: bool = False) -> Dict[str, Any]:
    payload_text = row[16]
    response_text = row[17]
    summary: Dict[str, Any] = {
        "event_id": int(row[0]) if row[0] is not None else None,
        "dedupe_key": row[1],
        "paper_id": row[2],
        "event_type": row[3],
        "channel": row[4],
        "trade_date": row[5],
        "code": row[6],
        "direction": row[7],
        "status": row[8],
        "retry_count": row[9],
        "max_retries": row[10],
        "next_retry_at": row[11],
        "error_message": _safe_str(row[12], 1000),
        "created_at": row[13],
        "updated_at": row[14],
        "sent_at": row[15],
    }
    if include_full_payload:
        summary["payload"] = _try_parse_json(payload_text)
        summary["response"] = _try_parse_json(response_text)
    else:
        summary["payload_preview"] = _safe_str(payload_text, _PAYLOAD_PREVIEW_LEN)
        summary["response_preview"] = _safe_str(response_text, _PAYLOAD_PREVIEW_LEN)
    return summary


class GetNotificationEventListHandler(webBase.BaseHandler, ABC):
    """GET /quantia/api/notification/event/list

    后台查看通知事件列表（钉钉等渠道发送记录）。
    """

    @gen.coroutine
    def get(self):
        try:
            filters: Dict[str, Any] = {}
            paper_id_arg = (self.get_argument("paper_id", "") or "").strip()
            if paper_id_arg:
                try:
                    filters["paper_id"] = int(paper_id_arg)
                except Exception:
                    self.write(json.dumps({"code": -1, "msg": "paper_id 必须为整数"}, ensure_ascii=False))
                    return
            status = (self.get_argument("status", "") or "").strip()
            if status:
                if status not in ("pending", "sending", "sent", "failed", "skipped"):
                    self.write(json.dumps({"code": -1, "msg": "非法 status"}, ensure_ascii=False))
                    return
                filters["status"] = status
            channel = (self.get_argument("channel", "") or "").strip()
            if channel:
                # 渠道白名单，避免任意字符串注入查询
                if channel not in ("dingtalk", "wecom", "qq", "serverchan", "pushplus"):
                    self.write(json.dumps({"code": -1, "msg": "非法 channel"}, ensure_ascii=False))
                    return
                filters["channel"] = channel
            event_type = (self.get_argument("event_type", "") or "").strip()
            if event_type:
                filters["event_type"] = event_type
            code = (self.get_argument("code", "") or "").strip()
            if code:
                filters["code"] = code
            since = (self.get_argument("since", "") or "").strip()
            if since:
                try:
                    datetime.datetime.strptime(since, "%Y-%m-%d")
                    filters["since"] = since
                except Exception:
                    self.write(json.dumps({"code": -1, "msg": "since 必须为 YYYY-MM-DD"}, ensure_ascii=False))
                    return
            try:
                limit = int(self.get_argument("limit", "100") or 100)
            except Exception:
                limit = 100
            limit = max(1, min(limit, 500))

            rows = _query_events(filters, limit)
            data = [_row_to_summary(r, include_full_payload=False) for r in rows]
            self.write(json.dumps({"code": 0, "data": data, "count": len(data)},
                                  ensure_ascii=False, default=_json_default))
        except Exception as e:
            logging.error("GetNotificationEventList异常", exc_info=True)
            self.write(json.dumps({"code": -1, "msg": str(e)}, ensure_ascii=False))


class GetNotificationEventDetailHandler(webBase.BaseHandler, ABC):
    """GET /quantia/api/notification/event/detail?event_id=

    返回单条通知事件完整内容（payload/response/error）。
    """

    @gen.coroutine
    def get(self):
        try:
            try:
                event_id = int(self.get_argument("event_id", "0") or 0)
            except Exception:
                event_id = 0
            if event_id <= 0:
                self.write(json.dumps({"code": -1, "msg": "缺少 event_id"}, ensure_ascii=False))
                return
            import quantia.lib.database as mdb
            rows = mdb.executeSqlFetch(
                f"SELECT id, dedupe_key, paper_id, event_type, channel, trade_date, "
                f"code, direction, status, retry_count, max_retries, next_retry_at, "
                f"error_message, created_at, updated_at, sent_at, "
                f"payload_json, response_json "
                f"FROM `{EVENT_TABLE}` WHERE id=%s LIMIT 1",
                (event_id,),
            ) or []
            if not rows:
                self.write(json.dumps({"code": -1, "msg": "通知事件不存在"}, ensure_ascii=False))
                return
            data = _row_to_summary(rows[0], include_full_payload=True)
            self.write(json.dumps({"code": 0, "data": data},
                                  ensure_ascii=False, default=_json_default))
        except Exception as e:
            logging.error("GetNotificationEventDetail异常", exc_info=True)
            self.write(json.dumps({"code": -1, "msg": str(e)}, ensure_ascii=False))
