# -*- coding: utf-8 -*-
"""Phase 5: AI 决策配置 CRUD（前端可调整 prompt / 阈值 / 数据包范围）。

设计要点（对齐 §3.7 / §11 Phase 5 / §14.3）：

- ``cn_stock_ai_decision_config`` 已由 Phase 4 创建。本模块仅做读写 +
  保存时 ``config_version += 1``，保证历史 ``cn_stock_trade_ai_score``
  仍可凭 ``config_id + config_version`` 解释当时使用的 prompt。
- ``api_key`` 永远只允许写入 ``api_key_ref``（环境变量名），从未在 DB / 响应中
  返回明文。GET 响应额外返回 ``api_key_is_configured`` 表示该环境变量是否
  已注入到当前进程。
- ``buy_threshold`` / ``sell_threshold`` 必须在 0–100；``temperature`` 0–2；
  ``timeout_seconds`` 1–300；``max_tokens`` 1–32000。范围外返回 400。
- ``enabled_as_gate=1`` 但 ``enabled=0`` 视作矛盾，强制 enabled=1。
"""
from __future__ import annotations

import json
import logging
import os
from abc import ABC
from typing import Any, Dict, List, Optional

from tornado import gen

import quantia.web.base as webBase
from quantia.auth import require_login, require_role
from quantia.ai_decision.config import (
    CONFIG_TABLE, DEFAULT_API_KEY_ENV, ensure_ai_decision_tables,
)


def _to_int(v, default=None):
    if v is None or v == "":
        return default
    try:
        return int(v)
    except Exception:
        return default


def _to_float(v, default=None):
    if v is None or v == "":
        return default
    try:
        return float(v)
    except Exception:
        return default


def _safe_json_loads(text, default=None):
    if not text:
        return default
    if not isinstance(text, str):
        return text
    try:
        return json.loads(text)
    except Exception:
        return default


_SELECT_COLS = (
    "id, name, enabled, source_type, source_id, strategy_id, "
    "provider, model_name, base_url, api_key_ref, "
    "system_prompt, user_prompt_template, output_schema, tool_config, "
    "temperature, max_tokens, timeout_seconds, retry_count, "
    "enabled_as_gate, fail_closed, "
    "buy_threshold, sell_threshold, config_version, modified_by, created_at, updated_at"
)


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
        import logging
        logging.debug("[aiDecisionConfig] 检查/添加 modified_by 列失败: %s", exc)


def _row_to_config(row) -> Dict[str, Any]:
    api_key_ref = row[9] or ""
    return {
        "id": int(row[0]),
        "name": row[1],
        "enabled": bool(row[2]),
        "source_type": row[3],
        "source_id": row[4],
        "strategy_id": row[5],
        "provider": row[6],
        "model_name": row[7],
        "base_url": row[8],
        "api_key_ref": api_key_ref,
        # 安全：永不返回明文。仅告知是否已注入环境变量。
        "api_key_is_configured": bool(api_key_ref and os.getenv(api_key_ref or DEFAULT_API_KEY_ENV)),
        "system_prompt": row[10],
        "user_prompt_template": row[11],
        "output_schema": _safe_json_loads(row[12], default=None),
        "tool_config": _safe_json_loads(row[13], default=None),
        "temperature": float(row[14]) if row[14] is not None else 0.2,
        "max_tokens": int(row[15]) if row[15] is not None else 2048,
        "timeout_seconds": int(row[16]) if row[16] is not None else 20,
        "retry_count": int(row[17]) if row[17] is not None else 1,
        "enabled_as_gate": bool(row[18]),
        "fail_closed": bool(row[19]),
        "buy_threshold": float(row[20]) if row[20] is not None else 70.0,
        "sell_threshold": float(row[21]) if row[21] is not None else 40.0,
        "config_version": int(row[22]) if row[22] is not None else 1,
        "modified_by": row[23] or None,
        "created_at": row[24].strftime("%Y-%m-%d %H:%M:%S") if row[24] else None,
        "updated_at": row[25].strftime("%Y-%m-%d %H:%M:%S") if row[25] else None,
    }


def list_configs(source_type: Optional[str] = None,
                 source_id: Optional[int] = None) -> List[Dict[str, Any]]:
    ensure_ai_decision_tables()
    _ensure_modified_by_column()
    import quantia.lib.database as mdb
    if not mdb.checkTableIsExist(CONFIG_TABLE):
        return []
    where = ["1=1"]
    params: List[Any] = []
    if source_type:
        where.append("source_type = %s")
        params.append(source_type)
    if source_id is not None:
        where.append("(source_id = %s OR source_id IS NULL)")
        params.append(int(source_id))
    sql = (
        f"SELECT {_SELECT_COLS} FROM `{CONFIG_TABLE}` "
        f"WHERE {' AND '.join(where)} ORDER BY id DESC"
    )
    rows = mdb.executeSqlFetch(sql, tuple(params)) or []
    return [_row_to_config(r) for r in rows]


def get_config(config_id: int) -> Optional[Dict[str, Any]]:
    ensure_ai_decision_tables()
    _ensure_modified_by_column()
    import quantia.lib.database as mdb
    rows = mdb.executeSqlFetch(
        f"SELECT {_SELECT_COLS} FROM `{CONFIG_TABLE}` WHERE id=%s LIMIT 1",
        (int(config_id),),
    ) or []
    return _row_to_config(rows[0]) if rows else None


_VALID_SOURCE_TYPES = {"paper", "backtest", "live", "all"}
_VALID_PROVIDERS = {"openai_compatible", "openai", "deepseek", "qwen", "local"}


def _validate(p: Dict[str, Any]) -> Optional[str]:
    name = (p.get("name") or "").strip()
    if not name:
        return "name 不能为空"
    src = (p.get("source_type") or "paper").strip().lower()
    if src not in _VALID_SOURCE_TYPES:
        return f"非法 source_type: {src}"
    provider = (p.get("provider") or "openai_compatible").strip().lower()
    if provider not in _VALID_PROVIDERS:
        return f"非法 provider: {provider}"
    # 安全：禁止前端写入 api_key 明文字段
    for forbidden in ("api_key", "apiKey", "secret", "token", "password"):
        if forbidden in p:
            return f"前端不允许直接写入 {forbidden}（请仅保存 api_key_ref 环境变量名）"
    ref = p.get("api_key_ref")
    if ref is not None and not isinstance(ref, str):
        return "api_key_ref 必须为字符串环境变量名"
    if ref and ("/" in ref or " " in ref or ref.startswith("sk-") or ref.startswith("Bearer ")):
        return "api_key_ref 看起来像密钥本身，请只填写环境变量名"
    # 数值范围
    t = _to_float(p.get("temperature"), default=0.2)
    if t is None or t < 0 or t > 2:
        return "temperature 必须在 0-2"
    mt = _to_int(p.get("max_tokens"), default=2048)
    if mt is None or mt < 1 or mt > 32000:
        return "max_tokens 必须在 1-32000"
    ts = _to_int(p.get("timeout_seconds"), default=20)
    if ts is None or ts < 1 or ts > 300:
        return "timeout_seconds 必须在 1-300"
    rc = _to_int(p.get("retry_count"), default=1)
    if rc is None or rc < 0 or rc > 5:
        return "retry_count 必须在 0-5"
    bt = _to_float(p.get("buy_threshold"), default=70.0)
    if bt is None or bt < 0 or bt > 100:
        return "buy_threshold 必须在 0-100"
    st = _to_float(p.get("sell_threshold"), default=40.0)
    if st is None or st < 0 or st > 100:
        return "sell_threshold 必须在 0-100"
    return None


def save_config(payload: Dict[str, Any]) -> Dict[str, Any]:
    """新增或更新 AI 配置；保存成功后 config_version+1（首次写入为 1）。"""
    err = _validate(payload)
    if err:
        raise ValueError(err)
    ensure_ai_decision_tables()
    _ensure_modified_by_column()
    import quantia.lib.database as mdb

    cid = _to_int(payload.get("id"))
    name = (payload.get("name") or "").strip()
    enabled = 1 if payload.get("enabled") else 0
    enabled_as_gate = 1 if payload.get("enabled_as_gate") else 0
    fail_closed = 1 if payload.get("fail_closed") else 0
    if enabled_as_gate and not enabled:
        # 矛盾时按文档 §3.5：gate 启用必须先启用 AI
        enabled = 1
    source_type = (payload.get("source_type") or "paper").strip().lower()
    source_id = _to_int(payload.get("source_id"))
    strategy_id = _to_int(payload.get("strategy_id"))
    provider = (payload.get("provider") or "openai_compatible").strip().lower()
    model_name = payload.get("model_name") or None
    base_url = payload.get("base_url") or None
    api_key_ref = (payload.get("api_key_ref") or "").strip() or None
    system_prompt = payload.get("system_prompt") or None
    user_prompt_template = payload.get("user_prompt_template") or None
    output_schema = json.dumps(payload.get("output_schema") or {}, ensure_ascii=False) \
        if payload.get("output_schema") is not None else None
    tool_config = json.dumps(payload.get("tool_config") or {}, ensure_ascii=False) \
        if payload.get("tool_config") is not None else None
    temperature = _to_float(payload.get("temperature"), 0.2)
    max_tokens = _to_int(payload.get("max_tokens"), 2048)
    timeout_seconds = _to_int(payload.get("timeout_seconds"), 20)
    retry_count = _to_int(payload.get("retry_count"), 1)
    buy_threshold = _to_float(payload.get("buy_threshold"), 70.0)
    sell_threshold = _to_float(payload.get("sell_threshold"), 40.0)
    # Phase 8 鉴权上线前，所有修改记录为 'system'；上线后由 handler 从 session 注入 username。
    modified_by = (payload.get("modified_by") or "system").strip()[:64] or "system"

    if cid:
        mdb.executeSql(
            f"UPDATE `{CONFIG_TABLE}` SET "
            "name=%s, enabled=%s, source_type=%s, source_id=%s, strategy_id=%s, "
            "provider=%s, model_name=%s, base_url=%s, api_key_ref=%s, "
            "system_prompt=%s, user_prompt_template=%s, output_schema=%s, tool_config=%s, "
            "temperature=%s, max_tokens=%s, timeout_seconds=%s, retry_count=%s, "
            "enabled_as_gate=%s, fail_closed=%s, "
            "buy_threshold=%s, sell_threshold=%s, modified_by=%s, "
            "config_version=COALESCE(config_version,1)+1 "
            "WHERE id=%s",
            (name, enabled, source_type, source_id, strategy_id,
             provider, model_name, base_url, api_key_ref,
             system_prompt, user_prompt_template, output_schema, tool_config,
             temperature, max_tokens, timeout_seconds, retry_count,
             enabled_as_gate, fail_closed,
             buy_threshold, sell_threshold, modified_by, cid),
        )
        out = get_config(cid)
        if out is None:
            raise ValueError("配置不存在")
        return out
    with mdb.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO `{CONFIG_TABLE}` "
                f"(name, enabled, source_type, source_id, strategy_id, "
                f" provider, model_name, base_url, api_key_ref, "
                f" system_prompt, user_prompt_template, output_schema, tool_config, "
                f" temperature, max_tokens, timeout_seconds, retry_count, "
                f" enabled_as_gate, fail_closed, "
                f" buy_threshold, sell_threshold, config_version, modified_by) "
                f"VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s)",
                (name, enabled, source_type, source_id, strategy_id,
                 provider, model_name, base_url, api_key_ref,
                 system_prompt, user_prompt_template, output_schema, tool_config,
                 temperature, max_tokens, timeout_seconds, retry_count,
                 enabled_as_gate, fail_closed,
                 buy_threshold, sell_threshold, modified_by),
            )
            cur.execute("SELECT LAST_INSERT_ID()")
            row = cur.fetchone()
            conn.commit()
            new_id = int(row[0]) if row and row[0] is not None else 0
    return get_config(new_id) or {"id": new_id}


def delete_config(config_id: int) -> bool:
    ensure_ai_decision_tables()
    import quantia.lib.database as mdb
    mdb.executeSql(
        f"DELETE FROM `{CONFIG_TABLE}` WHERE id=%s", (int(config_id),),
    )
    return True


# ─────────────── Tornado handlers ───────────────


class _BaseAIHandler(webBase.BaseHandler, ABC):
    def _write_json(self, data: Any, status: int = 200):
        self.set_status(status)
        self.set_header("Content-Type", "application/json; charset=utf-8")
        self.write(json.dumps(data, ensure_ascii=False, default=str))


class GetAIDecisionConfigListHandler(_BaseAIHandler, ABC):
    @gen.coroutine
    def get(self):
        try:
            src = self.get_argument("source_type", None)
            sid = _to_int(self.get_argument("source_id", None))
            data = list_configs(source_type=src, source_id=sid)
            self._write_json({"ok": True, "data": data})
        except Exception as exc:
            logging.exception("[aiDecisionConfig] list 失败")
            self._write_json({"ok": False, "error": str(exc)}, status=500)


class GetAIDecisionConfigDetailHandler(_BaseAIHandler, ABC):
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
            logging.exception("[aiDecisionConfig] detail 失败")
            self._write_json({"ok": False, "error": str(exc)}, status=500)


class SaveAIDecisionConfigHandler(_BaseAIHandler, ABC):
    @require_role("admin", "operator")
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
                cfg = save_config(body)
            except ValueError as ve:
                self._write_json({"ok": False, "error": str(ve)}, status=400)
                return
            self._write_json({"ok": True, "data": cfg})
        except Exception as exc:
            logging.exception("[aiDecisionConfig] save 失败")
            self._write_json({"ok": False, "error": str(exc)}, status=500)


class DeleteAIDecisionConfigHandler(_BaseAIHandler, ABC):
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
            logging.exception("[aiDecisionConfig] delete 失败")
            self._write_json({"ok": False, "error": str(exc)}, status=500)
