#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 调用审计：写入 cn_stock_ai_call_log。

此模块负责：
  * 惰性建表（首次调用时 CREATE TABLE IF NOT EXISTS）
  * 同步写入一条调用记录（失败仅记 warning，不影响业务）
"""

import json
import logging
import os
import threading
from typing import Any, Dict, Optional

import quantia.lib.database as mdb

__author__ = 'Quantia'
__date__ = '2026/05/11'

_TABLE = 'cn_stock_ai_call_log'
_table_ready = False
_lock = threading.Lock()

# A3：审计字段截断上限，避免超出 MySQL max_allowed_packet（默认 4MB）
_MAX_TEXT_BYTES = max(1024, int(os.environ.get('QUANTIA_AI_AUDIT_MAX_BYTES', str(128 * 1024))))


def _truncate_for_audit(text: Optional[str]) -> Optional[str]:
    """按字节安全截断，保留 UTF-8 边界。"""
    if text is None:
        return None
    if not isinstance(text, str):
        text = str(text)
    encoded = text.encode('utf-8')
    if len(encoded) <= _MAX_TEXT_BYTES:
        return text
    truncated = encoded[:_MAX_TEXT_BYTES].decode('utf-8', errors='ignore')
    suffix = f"\n...[TRUNCATED: original {len(encoded)} bytes]"
    return truncated + suffix

_DDL = f"""
CREATE TABLE IF NOT EXISTS {_TABLE} (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    scene VARCHAR(32) NOT NULL COMMENT 'strategy_gen / strategy_repair / im_summary / ...',
    agent VARCHAR(64) NULL,
    provider VARCHAR(32) NOT NULL,
    model VARCHAR(64) NOT NULL,
    user_id VARCHAR(64) NULL COMMENT '单部署下存 client_ip，多用户化后存真实用户 ID',
    prompt MEDIUMTEXT,
    response MEDIUMTEXT,
    tools_used JSON NULL,
    prompt_tokens INT,
    completion_tokens INT,
    total_tokens INT,
    latency_ms INT,
    ok TINYINT(1) NOT NULL,
    error VARCHAR(512) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_scene_time (scene, created_at),
    INDEX idx_user_time (user_id, created_at)
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
            logging.warning(f"[ai.audit] 建表失败: {exc}")


def record_call(
    *,
    scene: str,
    provider: str,
    model: str,
    prompt: str,
    response: str,
    ok: bool,
    agent: Optional[str] = None,
    user_id: Optional[str] = None,
    tools_used: Optional[Any] = None,
    prompt_tokens: Optional[int] = None,
    completion_tokens: Optional[int] = None,
    total_tokens: Optional[int] = None,
    latency_ms: Optional[int] = None,
    error: Optional[str] = None,
    rate_limit_loop: bool = False,
) -> Optional[int]:
    """写入一条 AI 调用记录，返回自增 id（失败返回 None，不抛异常）。

    rate_limit_loop=True 时在 tools_used JSON 中追加 `{"rate_limit_loop": true}`，
    供 rate_limiter 滑窗查询排除（spec §4.4 / §16.5）。
    """
    _ensure_table()
    # 把 rate_limit_loop 标志合并到 tools_used JSON 中（保留原 list 结构作为
    # `calls` 子键），保持向后兼容：rate_limiter SQL 查询用 JSON_EXTRACT 在
    # 顶层取 $.rate_limit_loop。
    tools_payload: Optional[Any]
    if rate_limit_loop or (tools_used is not None):
        tools_payload = {
            'rate_limit_loop': bool(rate_limit_loop),
            'calls': tools_used if tools_used is not None else [],
        }
    else:
        tools_payload = None
    try:
        with mdb.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'INSERT INTO {_TABLE} '
                    '(scene, agent, provider, model, user_id, prompt, response, tools_used, '
                    ' prompt_tokens, completion_tokens, total_tokens, latency_ms, ok, error) '
                    'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                    (
                        scene, agent, provider, model, user_id,
                        _truncate_for_audit(prompt), _truncate_for_audit(response),
                        json.dumps(tools_payload, ensure_ascii=False) if tools_payload is not None else None,
                        prompt_tokens, completion_tokens, total_tokens,
                        latency_ms, 1 if ok else 0,
                        (error or '')[:512] or None,
                    ),
                )
                cur.execute('SELECT LAST_INSERT_ID()')
                row = cur.fetchone()
                return int(row[0]) if row and row[0] is not None else None
    except Exception as exc:
        logging.warning(f"[ai.audit] 写入调用日志失败: {exc}")
        return None
