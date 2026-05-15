#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 调用层滑窗限流（spec §4.2 / §16.5）。

设计要点：
  * 基于 cn_stock_ai_call_log 表的滑窗 SQL 查询，不引入缓存或 Redis；
    重启不影响计数（与 spec "直接 SQL 查 cn_stock_ai_call_log" 一致）。
  * 双桶：调用数 + token 总量，任一超额即抛 RateLimitError。
  * `rate_limit_loop=True` 的内部修复重试（spec §4.4）从计数中扣除，
    避免 max_attempts=3 把用户 60 calls/h 配额吃光。
  * 失败模式 fail-open：DB 不可用 / 表未初始化时不阻断业务，仅 warning。
  * 测试可通过 QUANTIA_AI_RATE_DISABLED=1 跳过整个限流（CI 默认）。
  * 限流粒度按 (user_id, scene)；user_id 在单部署下落 client_ip。
    与 audit 表 idx_user_time(user_id, created_at) 索引对齐，O(扫窗口数).
"""

import logging
import os
from typing import Optional

import quantia.lib.database as mdb
from quantia.lib.ai.exceptions import RateLimitError

__author__ = 'Quantia'
__date__ = '2026/05/12'

# 与文档 §4.2 / §8 / §16.5 一致的环境变量名
_ENV_CALLS = 'QUANTIA_AI_RATE_CALLS_PER_HOUR'
_ENV_TOKENS = 'QUANTIA_AI_RATE_TOKENS_PER_HOUR'
_ENV_DISABLED = 'QUANTIA_AI_RATE_DISABLED'

_DEFAULT_CALLS_PER_HOUR = 60
_DEFAULT_TOKENS_PER_HOUR = 200_000


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == '':
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _is_disabled() -> bool:
    raw = (os.environ.get(_ENV_DISABLED) or '').strip().lower()
    return raw in ('1', 'true', 'yes', 'on')


def calls_per_hour() -> int:
    return _env_int(_ENV_CALLS, _DEFAULT_CALLS_PER_HOUR)


def tokens_per_hour() -> int:
    return _env_int(_ENV_TOKENS, _DEFAULT_TOKENS_PER_HOUR)


def _query_window(user_id: str, scene: str) -> tuple:
    """查询过去 1 小时内 (user_id, scene) 的调用数与 token 总量。

    排除 tools_used JSON 中 rate_limit_loop=true 的内部修复重试记录。
    返回 (calls, tokens)。DB 异常时返回 (0, 0)。
    """
    sql = (
        "SELECT COUNT(*) AS c, COALESCE(SUM(total_tokens),0) AS t "
        "FROM cn_stock_ai_call_log "
        "WHERE user_id=%s AND scene=%s "
        "  AND created_at >= NOW() - INTERVAL 1 HOUR "
        "  AND (tools_used IS NULL "
        "       OR JSON_EXTRACT(tools_used, '$.rate_limit_loop') IS NULL "
        "       OR JSON_EXTRACT(tools_used, '$.rate_limit_loop') = false)"
    )
    try:
        rows = mdb.executeSqlFetch(sql, (user_id, scene))
        if not rows:
            return 0, 0
        row = rows[0]
        if isinstance(row, (list, tuple)):
            return int(row[0] or 0), int(row[1] or 0)
        return int(row.get('c') or 0), int(row.get('t') or 0)
    except Exception as exc:
        # fail-open：表未建 / DB 不可用都允许通过，仅 warning
        logging.warning(f'[ai.rate_limiter] 查询滑窗失败（fail-open）: {exc}')
        return 0, 0


def check_quota(*, user_id: Optional[str], scene: str,
                rate_limit_loop: bool = False) -> None:
    """限流入口。超额抛 RateLimitError；正常返回 None。

    rate_limit_loop=True 表示当前调用是修复闭环的内部重试，自身不计入
    配额（仅在审计写入时落 tools_used.rate_limit_loop=true 即可），但
    本次调用前的"前置检查"仍按用户主请求维度执行：因为修复重试本身
    不该再触发 429（它已经在原始 429 时主动 break 出循环了）。
    所以本函数当 rate_limit_loop=True 时直接放行。
    """
    if _is_disabled():
        return
    if not user_id:
        # 没有可识别的主体（CLI / 后台任务），不限流
        return
    if rate_limit_loop:
        return
    cap_calls = calls_per_hour()
    cap_tokens = tokens_per_hour()
    if cap_calls <= 0 and cap_tokens <= 0:
        return
    calls, tokens = _query_window(user_id, scene)
    if cap_calls > 0 and calls >= cap_calls:
        raise RateLimitError(
            f'触发限流: 1 小时内调用数 {calls}/{cap_calls}（user_id={user_id} scene={scene}）')
    if cap_tokens > 0 and tokens >= cap_tokens:
        raise RateLimitError(
            f'触发限流: 1 小时内 token {tokens}/{cap_tokens}（user_id={user_id} scene={scene}）')
