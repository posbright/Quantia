# -*- coding: utf-8 -*-
"""Phase 7: 实盘交易管理接口。

- GET  ``/quantia/api/live/status``：读取主开关与 broker 名称。
- POST ``/quantia/api/live/execute_pending``：管理员触发一次扫描执行（默认关闭时返回 503）。
"""
from __future__ import annotations

import json
import logging
import os
from abc import ABC
from typing import Any

from tornado import gen

import quantia.web.base as webBase
from quantia.live import executor as live_executor
from quantia.lib import ratelimit as _ratelimit
from quantia.auth import require_login, require_role


def _to_int(v, default=None):
    if v is None or v == "":
        return default
    try:
        return int(v)
    except Exception:
        return default


class _BaseLiveHandler(webBase.BaseHandler, ABC):
    def _write_json(self, data: Any, status: int = 200):
        self.set_status(status)
        self.set_header("Content-Type", "application/json; charset=utf-8")
        self.write(json.dumps(data, ensure_ascii=False, default=str))


class LiveStatusHandler(_BaseLiveHandler, ABC):
    @gen.coroutine
    def get(self):
        broker = live_executor._resolve_broker()
        self._write_json({
            "ok": True,
            "data": {
                "enabled": live_executor.is_enabled(),
                "enabled_env": live_executor.ENABLED_ENV,
                "broker": broker.name,
                "broker_env": live_executor.BROKER_ENV,
                "trading_hours": os.getenv(live_executor.TRADING_HOURS_ENV, ""),
            },
        })


class ExecutePendingCommandsHandler(_BaseLiveHandler, ABC):
    @require_role("admin")
    @gen.coroutine
    def post(self):
        try:
            # Phase 8: 按客户端 IP 速率限制（默认禁用）。
            # 默认 QUANTIA_LIVE_EXECUTE_RPS 未设置 → no-op。
            rps = _ratelimit.live_execute_rps()
            if rps > 0:
                client_ip = (
                    self.request.headers.get("X-Forwarded-For", "")
                    .split(",")[0].strip()
                    or self.request.remote_ip or "unknown"
                )
                allowed = _ratelimit.check(
                    "live_execute_pending", client_ip,
                    capacity=float(rps), refill_per_sec=float(rps),
                )
                if not allowed:
                    self._write_json({
                        "ok": False, "status": "rate_limited",
                        "error": f"超过限速 {rps}/s",
                    }, status=429)
                    return
            try:
                body = json.loads(self.request.body or b"{}")
            except Exception:
                body = {}
            limit = _to_int(body.get("limit") or self.get_argument("limit", "20"), 20)
            stats = live_executor.execute_pending_commands(limit=limit or 20)
            http = 503 if stats.get("status") == "disabled" else 200
            self._write_json({"ok": stats.get("status") != "disabled",
                              "data": stats}, status=http)
        except Exception as exc:
            logging.exception("[live] execute_pending 失败")
            self._write_json({"ok": False, "error": str(exc)}, status=500)
