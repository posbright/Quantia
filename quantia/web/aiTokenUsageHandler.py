#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI Token 用量统计 + 功能开关管理 Handler。

路由（web_service.py 中注册）::

    GET  /quantia/api/ai/token/summary         → 今日/本月/小时配额汇总
    GET  /quantia/api/ai/token/by_model        → 按模型分组统计
    GET  /quantia/api/ai/token/by_scene        → 按场景分组统计
    GET  /quantia/api/ai/token/daily_trend     → 每日趋势（近 N 天）
    GET  /quantia/api/ai/token/feature_status  → 各功能开关 + 日预算余量
    GET  /quantia/api/ai/token/recent_calls    → 最近调用记录
    POST /quantia/api/ai/token/update_feature  → 更新功能开关/预算
"""
from __future__ import annotations

import json
import logging
from abc import ABC
from typing import Any, Dict

from tornado import gen

import quantia.lib.database as mdb
import quantia.web.base as webBase
from quantia.lib.ai import rate_limiter
from quantia.lib.ai.feature_switch import (
    _FEATURE_SCENE_PREFIX, load_all_switches, update_feature,
    _query_today_tokens_by_prefix, _ensure_table,
)

__author__ = 'Quantia'
__date__ = '2026/05/23'

_AUDIT_TABLE = 'cn_stock_ai_call_log'


def _to_int(val, default: int) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _write_json(handler, data: Dict[str, Any], status: int = 200):
    handler.set_status(status)
    handler.set_header("Content-Type", "application/json; charset=UTF-8")
    handler.write(json.dumps(data, ensure_ascii=False, default=str))


class TokenSummaryHandler(webBase.BaseHandler, ABC):
    """GET /quantia/api/ai/token/summary"""

    @gen.coroutine
    def get(self):
        try:
            # 今日 token
            rows = mdb.executeSqlFetch(
                f"SELECT COALESCE(SUM(total_tokens),0), COUNT(*) "
                f"FROM `{_AUDIT_TABLE}` WHERE DATE(created_at) = CURDATE()", ())
            today_tokens = int(rows[0][0]) if rows else 0
            today_calls = int(rows[0][1]) if rows else 0

            # 本月 token
            rows = mdb.executeSqlFetch(
                f"SELECT COALESCE(SUM(total_tokens),0) "
                f"FROM `{_AUDIT_TABLE}` "
                f"WHERE created_at >= DATE_FORMAT(CURDATE(), '%%Y-%%m-01')", ())
            month_tokens = int(rows[0][0]) if rows else 0

            # 小时滑窗（排除 rate_limit_loop）
            rows = mdb.executeSqlFetch(
                f"SELECT COUNT(*), COALESCE(SUM(total_tokens),0) "
                f"FROM `{_AUDIT_TABLE}` "
                f"WHERE created_at >= NOW() - INTERVAL 1 HOUR "
                f"  AND (tools_used IS NULL "
                f"       OR JSON_EXTRACT(tools_used, '$.rate_limit_loop') IS NULL "
                f"       OR JSON_EXTRACT(tools_used, '$.rate_limit_loop') = false)", ())
            hour_calls = int(rows[0][0]) if rows else 0
            hour_tokens = int(rows[0][1]) if rows else 0

            _write_json(self, {
                "ok": True,
                "data": {
                    "today_tokens": today_tokens,
                    "today_calls": today_calls,
                    "month_tokens": month_tokens,
                    "hour_calls": hour_calls,
                    "hour_tokens": hour_tokens,
                    "hour_limit_calls": rate_limiter.calls_per_hour(),
                    "hour_limit_tokens": rate_limiter.tokens_per_hour(),
                }
            })
        except Exception as exc:
            logging.exception("[ai.token] summary 失败")
            _write_json(self, {"ok": False, "error": str(exc)}, 500)


class TokenByModelHandler(webBase.BaseHandler, ABC):
    """GET /quantia/api/ai/token/by_model?days=30"""

    @gen.coroutine
    def get(self):
        try:
            days = _to_int(self.get_argument("days", "30"), 30)
            days = max(1, min(365, days))
            rows = mdb.executeSqlFetch(
                f"SELECT model, COALESCE(SUM(total_tokens),0) AS total_tokens, "
                f"       COUNT(*) AS call_count "
                f"FROM `{_AUDIT_TABLE}` "
                f"WHERE created_at >= CURDATE() - INTERVAL %s DAY "
                f"GROUP BY model ORDER BY total_tokens DESC",
                (days,))
            data = []
            for r in (rows or []):
                if isinstance(r, (list, tuple)):
                    total = int(r[1])
                    count = int(r[2])
                    data.append({"model": r[0], "total_tokens": total,
                                 "call_count": count,
                                 "avg_tokens_per_call": round(total / count) if count else 0})
                else:
                    total = int(r.get("total_tokens", 0))
                    count = int(r.get("call_count", 0))
                    data.append({"model": r.get("model"), "total_tokens": total,
                                 "call_count": count,
                                 "avg_tokens_per_call": round(total / count) if count else 0})
            _write_json(self, {"ok": True, "data": data})
        except Exception as exc:
            logging.exception("[ai.token] by_model 失败")
            _write_json(self, {"ok": False, "error": str(exc)}, 500)


class TokenBySceneHandler(webBase.BaseHandler, ABC):
    """GET /quantia/api/ai/token/by_scene?days=30"""

    @gen.coroutine
    def get(self):
        try:
            days = _to_int(self.get_argument("days", "30"), 30)
            days = max(1, min(365, days))
            rows = mdb.executeSqlFetch(
                f"SELECT scene, COALESCE(SUM(total_tokens),0) AS total_tokens, "
                f"       COUNT(*) AS call_count "
                f"FROM `{_AUDIT_TABLE}` "
                f"WHERE created_at >= CURDATE() - INTERVAL %s DAY "
                f"GROUP BY scene ORDER BY total_tokens DESC",
                (days,))
            data = []
            for r in (rows or []):
                if isinstance(r, (list, tuple)):
                    data.append({"scene": r[0], "total_tokens": int(r[1]),
                                 "call_count": int(r[2])})
                else:
                    data.append({"scene": r.get("scene"), "total_tokens": int(r.get("total_tokens", 0)),
                                 "call_count": int(r.get("call_count", 0))})
            _write_json(self, {"ok": True, "data": data})
        except Exception as exc:
            logging.exception("[ai.token] by_scene 失败")
            _write_json(self, {"ok": False, "error": str(exc)}, 500)


class TokenDailyTrendHandler(webBase.BaseHandler, ABC):
    """GET /quantia/api/ai/token/daily_trend?days=30"""

    @gen.coroutine
    def get(self):
        try:
            days = _to_int(self.get_argument("days", "30"), 30)
            days = max(1, min(365, days))
            rows = mdb.executeSqlFetch(
                f"SELECT DATE(created_at) AS dt, "
                f"       COALESCE(SUM(prompt_tokens),0), "
                f"       COALESCE(SUM(completion_tokens),0), "
                f"       COALESCE(SUM(total_tokens),0), "
                f"       COUNT(*) "
                f"FROM `{_AUDIT_TABLE}` "
                f"WHERE created_at >= CURDATE() - INTERVAL %s DAY "
                f"GROUP BY dt ORDER BY dt",
                (days,))
            data = []
            for r in (rows or []):
                if isinstance(r, (list, tuple)):
                    data.append({
                        "date": str(r[0]),
                        "prompt_tokens": int(r[1]),
                        "completion_tokens": int(r[2]),
                        "total_tokens": int(r[3]),
                        "call_count": int(r[4]),
                    })
                else:
                    data.append({
                        "date": str(r.get("dt", "")),
                        "prompt_tokens": int(r.get("COALESCE(SUM(prompt_tokens),0)", 0)),
                        "completion_tokens": int(r.get("COALESCE(SUM(completion_tokens),0)", 0)),
                        "total_tokens": int(r.get("COALESCE(SUM(total_tokens),0)", 0)),
                        "call_count": int(r.get("COUNT(*)", 0)),
                    })
            _write_json(self, {"ok": True, "data": data})
        except Exception as exc:
            logging.exception("[ai.token] daily_trend 失败")
            _write_json(self, {"ok": False, "error": str(exc)}, 500)


class TokenFeatureStatusHandler(webBase.BaseHandler, ABC):
    """GET /quantia/api/ai/token/feature_status"""

    @gen.coroutine
    def get(self):
        try:
            _ensure_table()
            switches = load_all_switches()
            data = []
            for s in switches:
                feature = s['feature']
                prefix = _FEATURE_SCENE_PREFIX.get(feature, feature)
                used = _query_today_tokens_by_prefix(prefix)
                budget = s.get('daily_token_budget')
                data.append({
                    "feature": feature,
                    "enabled": s['enabled'],
                    "daily_budget": budget,
                    "used_today": used,
                    "remaining": max(0, budget - used) if budget else None,
                    "modified_by": s.get('modified_by'),
                    "updated_at": s.get('updated_at'),
                })
            _write_json(self, {"ok": True, "data": data})
        except Exception as exc:
            logging.exception("[ai.token] feature_status 失败")
            _write_json(self, {"ok": False, "error": str(exc)}, 500)


class TokenRecentCallsHandler(webBase.BaseHandler, ABC):
    """GET /quantia/api/ai/token/recent_calls?limit=50"""

    @gen.coroutine
    def get(self):
        try:
            limit = _to_int(self.get_argument("limit", "50"), 50)
            limit = max(1, min(200, limit))
            rows = mdb.executeSqlFetch(
                f"SELECT id, scene, model, provider, total_tokens, "
                f"       latency_ms, ok, created_at "
                f"FROM `{_AUDIT_TABLE}` "
                f"ORDER BY created_at DESC LIMIT %s",
                (limit,))
            data = []
            for r in (rows or []):
                if isinstance(r, (list, tuple)):
                    data.append({
                        "id": r[0], "scene": r[1], "model": r[2],
                        "provider": r[3], "total_tokens": r[4],
                        "latency_ms": r[5], "ok": bool(r[6]),
                        "created_at": str(r[7]),
                    })
                else:
                    data.append({
                        "id": r.get("id"), "scene": r.get("scene"),
                        "model": r.get("model"), "provider": r.get("provider"),
                        "total_tokens": r.get("total_tokens"),
                        "latency_ms": r.get("latency_ms"),
                        "ok": bool(r.get("ok")),
                        "created_at": str(r.get("created_at", "")),
                    })
            _write_json(self, {"ok": True, "data": data})
        except Exception as exc:
            logging.exception("[ai.token] recent_calls 失败")
            _write_json(self, {"ok": False, "error": str(exc)}, 500)


class TokenUpdateFeatureHandler(webBase.BaseHandler, ABC):
    """POST /quantia/api/ai/token/update_feature"""

    @gen.coroutine
    def post(self):
        try:
            body = json.loads(self.request.body or '{}')
            feature = (body.get('feature') or '').strip()
            if not feature:
                _write_json(self, {"ok": False, "error": "缺少 feature 参数"}, 400)
                return
            enabled = body.get('enabled')
            budget = body.get('daily_token_budget')
            if enabled is None and budget is None:
                _write_json(self, {"ok": False, "error": "至少提供 enabled 或 daily_token_budget"}, 400)
                return
            # 获取调用者身份（简化：取 IP）
            modified_by = self.request.remote_ip or 'unknown'
            ok = update_feature(
                feature,
                enabled=bool(enabled) if enabled is not None else None,
                daily_token_budget=_to_int(budget, 0) if budget is not None else None,
                modified_by=modified_by,
            )
            if ok:
                _write_json(self, {"ok": True})
            else:
                _write_json(self, {"ok": False, "error": "更新失败，功能可能不存在"}, 404)
        except Exception as exc:
            logging.exception("[ai.token] update_feature 失败")
            _write_json(self, {"ok": False, "error": str(exc)}, 500)
