#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自定义 Agent 持久化（M7）。

负责：
  * 惰性建表 cn_stock_ai_agent（首次访问时 CREATE TABLE IF NOT EXISTS）
  * CRUD：list / get / upsert / delete
  * 启动时 upsert 内置 agent（is_builtin=1，禁止删除）

设计要点：
  * 与 audit.py 一致的 lazy-DDL + threading.Lock 单例模式
  * 失败仅记 warning，不影响业务（DB 不可用时上层走 file 兜底）
  * allowed_tools 以 JSON 形式存储（list[str]），读取时反序列化
"""

import json
import logging
import threading
from typing import Any, Dict, List, Optional

import quantia.lib.database as mdb

__author__ = 'Quantia'
__date__ = '2026/05/11'

_TABLE = 'cn_stock_ai_agent'
_table_ready = False
_lock = threading.Lock()

# 字段长度限制（与 DDL 一致 + 避免 LLM 注入超大值）
_NAME_MAX = 64
_DISPLAY_MAX = 128
_PROVIDER_MAX = 32
_MODEL_MAX = 64
_PROMPT_MAX_BYTES = 1 * 1024 * 1024  # 1MB
_TEMP_MIN = 0.0
_TEMP_MAX = 2.0
_MAX_TOKENS_MIN = 1
_MAX_TOKENS_MAX = 65536


class AgentStoreError(Exception):
    """业务错误（如：禁止删除内置 / 字段不合法）。"""


_DDL = f"""
CREATE TABLE IF NOT EXISTS {_TABLE} (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(64) UNIQUE NOT NULL,
    display_name VARCHAR(128),
    description TEXT,
    system_prompt MEDIUMTEXT NOT NULL,
    default_provider VARCHAR(32),
    default_model VARCHAR(64),
    allowed_tools JSON NULL COMMENT '["sql_query","kline_fetch","web_search"]',
    temperature FLOAT DEFAULT 0.3,
    max_tokens INT DEFAULT 4096,
    is_builtin TINYINT(1) DEFAULT 0,
    enabled TINYINT(1) DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
""".strip()


def _ensure_table() -> None:
    global _table_ready
    if _table_ready:
        return
    with _lock:
        if _table_ready:
            return
        try:
            with mdb.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(_DDL)
            _table_ready = True
        except Exception as exc:
            logging.warning(f"[ai.agent_store] 建表失败: {exc}")


def _reset_for_test() -> None:
    """仅供测试用：强制下次访问重新执行 DDL。"""
    global _table_ready
    with _lock:
        _table_ready = False


# ── 校验 ──────────────────────────────────────────────────────────
def _validate(meta: Dict[str, Any], *, partial: bool = False) -> Dict[str, Any]:
    """归一化并校验入参；返回可直接落库的 dict。

    partial=True 时允许缺失字段（用于 upsert 已存在记录的部分更新）。
    """
    out: Dict[str, Any] = {}
    name = meta.get('name')
    if name is None and not partial:
        raise AgentStoreError('name 不能为空')
    if name is not None:
        if not isinstance(name, str):
            raise AgentStoreError('name 必须是字符串')
        name = name.strip()
        if not name:
            raise AgentStoreError('name 不能为空')
        if len(name) > _NAME_MAX:
            raise AgentStoreError(f'name 长度不可超过 {_NAME_MAX}')
        # 仅允许字母数字下划线，避免奇异字符（不限制大小写以兼容历史）
        for ch in name:
            if not (ch.isalnum() or ch == '_'):
                raise AgentStoreError(f'name 仅支持字母/数字/下划线，非法字符: {ch!r}')
        out['name'] = name

    if 'system_prompt' in meta or not partial:
        sp = meta.get('system_prompt') or ''
        if not isinstance(sp, str):
            raise AgentStoreError('system_prompt 必须是字符串')
        if len(sp.encode('utf-8')) > _PROMPT_MAX_BYTES:
            raise AgentStoreError(f'system_prompt 超过 {_PROMPT_MAX_BYTES} bytes')
        if not sp.strip() and not partial:
            raise AgentStoreError('system_prompt 不能为空')
        out['system_prompt'] = sp

    if 'display_name' in meta:
        v = meta.get('display_name')
        if v is not None and not isinstance(v, str):
            raise AgentStoreError('display_name 必须是字符串')
        if v and len(v) > _DISPLAY_MAX:
            raise AgentStoreError(f'display_name 超过 {_DISPLAY_MAX}')
        out['display_name'] = v

    if 'description' in meta:
        v = meta.get('description')
        if v is not None and not isinstance(v, str):
            raise AgentStoreError('description 必须是字符串')
        out['description'] = v

    if 'default_provider' in meta:
        v = meta.get('default_provider')
        if v is not None and not isinstance(v, str):
            raise AgentStoreError('default_provider 必须是字符串')
        if v and len(v) > _PROVIDER_MAX:
            raise AgentStoreError(f'default_provider 超过 {_PROVIDER_MAX}')
        out['default_provider'] = v

    if 'default_model' in meta:
        v = meta.get('default_model')
        if v is not None and not isinstance(v, str):
            raise AgentStoreError('default_model 必须是字符串')
        if v and len(v) > _MODEL_MAX:
            raise AgentStoreError(f'default_model 超过 {_MODEL_MAX}')
        out['default_model'] = v

    if 'allowed_tools' in meta:
        v = meta.get('allowed_tools')
        if v is None:
            out['allowed_tools'] = None
        elif isinstance(v, list):
            # P2（一轮审计）：校验工具名是否在 ToolRegistry 中注册。
            # 避免用户保存拼错名后调用该 agent 时遇到 unknown tool 报错。
            try:
                from quantia.lib.ai.tools import get_registry
                registered = set(get_registry().list_names())
            except Exception:
                registered = set()
            for item in v:
                if not isinstance(item, str):
                    raise AgentStoreError('allowed_tools 元素必须是字符串')
                if len(item) > 64:
                    raise AgentStoreError('allowed_tools 元素长度超限')
                if registered and item not in registered:
                    raise AgentStoreError(f'未知工具名: {item}（已注册: {sorted(registered)}）')
            out['allowed_tools'] = v
        else:
            raise AgentStoreError('allowed_tools 必须是字符串数组或 null')

    if 'temperature' in meta:
        v = meta.get('temperature')
        if v is not None:
            try:
                fv = float(v)
            except (TypeError, ValueError):
                raise AgentStoreError('temperature 必须是数字')
            if not (_TEMP_MIN <= fv <= _TEMP_MAX):
                raise AgentStoreError(f'temperature 超出范围 [{_TEMP_MIN},{_TEMP_MAX}]')
            out['temperature'] = fv

    if 'max_tokens' in meta:
        v = meta.get('max_tokens')
        if v is not None:
            try:
                iv = int(v)
            except (TypeError, ValueError):
                raise AgentStoreError('max_tokens 必须是整数')
            if not (_MAX_TOKENS_MIN <= iv <= _MAX_TOKENS_MAX):
                raise AgentStoreError(f'max_tokens 超出范围 [{_MAX_TOKENS_MIN},{_MAX_TOKENS_MAX}]')
            out['max_tokens'] = iv

    if 'enabled' in meta:
        out['enabled'] = 1 if meta.get('enabled') else 0

    return out


# ── CRUD ──────────────────────────────────────────────────────────
def _row_to_dict(row: Dict[str, Any]) -> Dict[str, Any]:
    """torndb Row → 普通 dict，并解析 allowed_tools JSON。"""
    d = dict(row)
    raw = d.get('allowed_tools')
    if raw is not None and isinstance(raw, str):
        try:
            d['allowed_tools'] = json.loads(raw)
        except (TypeError, ValueError):
            d['allowed_tools'] = None
    if 'is_builtin' in d:
        d['is_builtin'] = bool(d['is_builtin'])
    if 'enabled' in d:
        d['enabled'] = bool(d['enabled'])
    return d


def list_agents(*, enabled_only: bool = False) -> List[Dict[str, Any]]:
    """读取所有 agent。DB 不可用时返回空列表。"""
    _ensure_table()
    try:
        sql = f"SELECT * FROM {_TABLE}"
        if enabled_only:
            sql += " WHERE enabled=1"
        sql += " ORDER BY is_builtin DESC, name ASC"
        rows = mdb.executeSqlFetch(sql)
        return [_row_to_dict(r) for r in (rows or [])]
    except Exception as exc:
        logging.warning(f"[ai.agent_store] list 失败: {exc}")
        return []


def get_agent(name: str) -> Optional[Dict[str, Any]]:
    """按 name 查询单条记录。"""
    _ensure_table()
    if not isinstance(name, str) or not name.strip():
        return None
    try:
        rows = mdb.executeSqlFetch(
            f"SELECT * FROM {_TABLE} WHERE name=%s LIMIT 1", (name.strip(),))
        if not rows:
            return None
        return _row_to_dict(rows[0])
    except Exception as exc:
        logging.warning(f"[ai.agent_store] get 失败: {exc}")
        return None


def upsert_agent(meta: Dict[str, Any], *, is_builtin: bool = False) -> Dict[str, Any]:
    """新建或更新 agent。

    name 已存在则更新；不存在则插入。
    is_builtin=True 仅供启动时注入内置 agent；用户接口不应传 True。
    返回归一化后的字典（含 is_builtin/enabled bool）。
    """
    _ensure_table()
    payload = _validate(meta, partial=False)
    payload['is_builtin'] = 1 if is_builtin else 0
    if 'enabled' not in payload:
        payload['enabled'] = 1
    if 'temperature' not in payload:
        payload['temperature'] = 0.3
    if 'max_tokens' not in payload:
        payload['max_tokens'] = 4096
    allowed_json = json.dumps(payload.get('allowed_tools'), ensure_ascii=False) \
        if payload.get('allowed_tools') is not None else None

    cols = ['name', 'display_name', 'description', 'system_prompt',
            'default_provider', 'default_model', 'allowed_tools',
            'temperature', 'max_tokens', 'is_builtin', 'enabled']
    vals = [
        payload['name'],
        payload.get('display_name'),
        payload.get('description'),
        payload['system_prompt'],
        payload.get('default_provider'),
        payload.get('default_model'),
        allowed_json,
        payload.get('temperature'),
        payload.get('max_tokens'),
        payload['is_builtin'],
        payload['enabled'],
    ]
    placeholders = ','.join(['%s'] * len(cols))
    update_assigns = ','.join([f"{c}=VALUES({c})" for c in cols if c != 'name'])
    sql = (f"INSERT INTO {_TABLE} ({','.join(cols)}) VALUES ({placeholders}) "
           f"ON DUPLICATE KEY UPDATE {update_assigns}")
    mdb.executeSql(sql, tuple(vals))
    out = get_agent(payload['name']) or {}
    return out


def delete_agent(name: str) -> bool:
    """按 name 删除自定义 agent；内置 agent 拒绝删除。"""
    _ensure_table()
    existing = get_agent(name)
    if not existing:
        raise AgentStoreError(f'agent 不存在: {name}')
    if existing.get('is_builtin'):
        raise AgentStoreError(f'内置 agent 不可删除: {name}')
    mdb.executeSql(f"DELETE FROM {_TABLE} WHERE name=%s AND is_builtin=0",
                   (name,))
    return True


def upsert_builtin_agents(builtins: List[Dict[str, Any]]) -> int:
    """启动时调用：把内置 agent 写入 DB（is_builtin=1）。

    返回成功 upsert 的条数。失败的条目仅 warning，不抛。
    """
    n = 0
    for meta in builtins or []:
        try:
            upsert_agent(meta, is_builtin=True)
            n += 1
        except Exception as exc:
            logging.warning(f"[ai.agent_store] upsert builtin {meta.get('name')!r} 失败: {exc}")
    return n
