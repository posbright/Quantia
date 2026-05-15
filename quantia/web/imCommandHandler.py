# -*- coding: utf-8 -*-
"""Phase 6: IM 指令回调 + 后台管理 handlers。

路由：
- POST ``/quantia/api/im/dingtalk/callback``：钉钉机器人回调入口（默认关闭）。
- GET  ``/quantia/api/im/command/list``：指令列表（含 status/paper_id 过滤）。
- GET  ``/quantia/api/im/command/detail``：指令详情。
- GET  ``/quantia/api/im/operator/list``：白名单列表。
- POST ``/quantia/api/im/operator/save``：白名单新增/更新。
- POST ``/quantia/api/im/operator/delete``：白名单删除。
- GET  ``/quantia/api/im/status``：返回总开关状态（前端展示用）。
"""
from __future__ import annotations

import json
import logging
from abc import ABC
from typing import Any

from tornado import gen

import quantia.web.base as webBase
from quantia.im import service as im_service
from quantia.lib import ratelimit as _ratelimit
from quantia import auth as _auth
from quantia.auth import require_login, require_role


def _to_int(v, default=None):
    if v is None or v == "":
        return default
    try:
        return int(v)
    except Exception:
        return default


class _BaseIMHandler(webBase.BaseHandler, ABC):
    def _write_json(self, data: Any, status: int = 200):
        self.set_status(status)
        self.set_header("Content-Type", "application/json; charset=utf-8")
        self.write(json.dumps(data, ensure_ascii=False, default=str))


class IMStatusHandler(_BaseIMHandler, ABC):
    @gen.coroutine
    def get(self):
        self._write_json({
            "ok": True,
            "data": {
                "enabled": im_service.is_enabled(),
                "max_single_value": im_service._max_single_value(),
                "max_daily_value": im_service._max_daily_value(),
                "ttl_seconds": im_service._ttl_seconds(),
                "enabled_env": im_service.ENABLED_ENV,
            },
        })


class DingtalkCallbackHandler(_BaseIMHandler, ABC):
    @gen.coroutine
    def post(self):
        try:
            try:
                body = json.loads(self.request.body or b"{}")
            except Exception:
                self._write_json({"ok": False, "status": "invalid",
                                  "error": "请求体非 JSON"}, status=400)
                return
            # Phase 8 Must 5: IP 白名单（默认未配置 → 不强制）。
            client_ip = (
                self.request.headers.get("X-Forwarded-For", "")
                .split(",")[0].strip()
                or self.request.remote_ip or ""
            )
            if not _auth.is_ip_allowed(client_ip):
                self._write_json({
                    "ok": False, "status": "ip_forbidden",
                    "error": f"IP {client_ip} 不在白名单",
                }, status=403)
                return
            # Phase 8: 按 operator_id 速率限制（默认禁用）。
            # 默认 QUANTIA_DINGTALK_CALLBACK_RPM 未设置 → no-op。
            rpm = _ratelimit.dingtalk_callback_rpm()
            if rpm > 0:
                op_id = (
                    body.get("operator_id")
                    or body.get("senderStaffId")
                    or (body.get("text") or {}).get("senderStaffId")
                    or "unknown"
                )
                allowed = _ratelimit.check(
                    "dingtalk_callback", str(op_id),
                    capacity=float(rpm), refill_per_sec=float(rpm) / 60.0,
                )
                if not allowed:
                    self._write_json({
                        "ok": False, "status": "rate_limited",
                        "error": f"超过限速 {rpm}/min",
                    }, status=429)
                    return
            headers = {
                "timestamp": self.request.headers.get("timestamp")
                             or self.request.headers.get("Timestamp") or "",
                "sign": self.request.headers.get("sign")
                        or self.request.headers.get("Sign") or "",
            }
            result = im_service.handle_dingtalk_callback(headers, body)
            status_map = {
                "disabled": 503, "signature_failed": 401,
                "unauthorized": 403, "invalid": 400,
            }
            http_status = status_map.get(result.get("status"), 200)
            self._write_json({"ok": bool(result.get("ok")), "data": result},
                             status=http_status)
        except Exception as exc:
            logging.exception("[imCommand] 回调失败")
            self._write_json({"ok": False, "error": str(exc)}, status=500)


class ListTradeCommandsHandler(_BaseIMHandler, ABC):
    @gen.coroutine
    def get(self):
        try:
            status = self.get_argument("status", None)
            paper_id = _to_int(self.get_argument("paper_id", None))
            limit = _to_int(self.get_argument("limit", "50"), 50)
            offset = _to_int(self.get_argument("offset", "0"), 0)
            data = im_service.list_commands(status=status, paper_id=paper_id,
                                            limit=limit or 50, offset=offset or 0)
            self._write_json({"ok": True, "data": data})
        except Exception as exc:
            logging.exception("[imCommand] list 失败")
            self._write_json({"ok": False, "error": str(exc)}, status=500)


class GetTradeCommandDetailHandler(_BaseIMHandler, ABC):
    @gen.coroutine
    def get(self):
        try:
            cid = _to_int(self.get_argument("id", None))
            if not cid:
                self._write_json({"ok": False, "error": "缺少 id"}, status=400)
                return
            data = im_service.get_command(cid)
            if data is None:
                self._write_json({"ok": False, "error": "未找到"}, status=404)
                return
            self._write_json({"ok": True, "data": data})
        except Exception as exc:
            logging.exception("[imCommand] detail 失败")
            self._write_json({"ok": False, "error": str(exc)}, status=500)


class ListOperatorsHandler(_BaseIMHandler, ABC):
    @gen.coroutine
    def get(self):
        try:
            channel = self.get_argument("channel", None)
            self._write_json({"ok": True,
                              "data": im_service.list_operators(channel=channel)})
        except Exception as exc:
            logging.exception("[imCommand] operator list 失败")
            self._write_json({"ok": False, "error": str(exc)}, status=500)


class SaveOperatorHandler(_BaseIMHandler, ABC):
    @require_role("admin")
    @gen.coroutine
    def post(self):
        try:
            try:
                body = json.loads(self.request.body or b"{}")
            except Exception:
                self._write_json({"ok": False, "error": "请求体非 JSON"}, status=400)
                return
            # Phase 8：启用鉴权后由 session 注入 modified_by。
            if getattr(self, "current_username", None):
                body["modified_by"] = self.current_username
            try:
                data = im_service.save_operator(body)
            except ValueError as ve:
                self._write_json({"ok": False, "error": str(ve)}, status=400)
                return
            self._write_json({"ok": True, "data": data})
        except Exception as exc:
            logging.exception("[imCommand] operator save 失败")
            self._write_json({"ok": False, "error": str(exc)}, status=500)


class DeleteOperatorHandler(_BaseIMHandler, ABC):
    @require_role("admin")
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
            im_service.delete_operator(cid)
            self._write_json({"ok": True})
        except Exception as exc:
            logging.exception("[imCommand] operator delete 失败")
            self._write_json({"ok": False, "error": str(exc)}, status=500)
