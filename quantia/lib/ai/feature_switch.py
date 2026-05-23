#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 功能开关 + 每日 Token 预算控制。

每个 AI 功能（strategy_gen / chat / trade_gate 等）可独立启用/禁用，
并可设定 daily_token_budget 上限（NULL 表示不限）。

与 rate_limiter 的关系：
  * Feature Switch = 每日总量预算（粗粒度）
  * Rate Limiter   = 小时突发控制（细粒度）
  执行顺序：is_feature_enabled() → rate_limiter.check_quota() → provider call
"""

import logging
import threading
from typing import Any, Dict, List, Optional

import quantia.lib.database as mdb
from quantia.lib.ai.exceptions import AIError

__author__ = 'Quantia'
__date__ = '2026/05/23'

_TABLE = 'cn_stock_ai_feature_switch'
_AUDIT_TABLE = 'cn_stock_ai_call_log'
_table_ready = False
_lock = threading.Lock()

# feature → scene prefix 映射（LIKE 'prefix%' 查询 cn_stock_ai_call_log）
_FEATURE_SCENE_PREFIX: Dict[str, str] = {
    'strategy_gen': 'strategy_gen',
    'strategy_refine': 'strategy_refine',
    'strategy_repair': 'strategy_repair',
    'chat': 'chat',
    'trade_gate': 'trade_gate',
    'report_generate': 'report_generate',
    'report_cron_pregenerate': 'report_cron',
}


def _resolve_scene_to_feature(scene: str) -> str:
    """将实际 scene 值解析为所属的 feature 标识。

    例如 'strategy_gen_stream_repair' → 'strategy_gen'（最长前缀匹配）。
    未匹配任何 feature 时原样返回（_load_switch 会返回 None → fail-open）。
    """
    # 精确命中
    if scene in _FEATURE_SCENE_PREFIX:
        return scene
    # 最长前缀匹配：从所有 feature 中找到是 scene 前缀的最长者
    best = ''
    for feature, prefix in _FEATURE_SCENE_PREFIX.items():
        if scene.startswith(prefix) and len(prefix) > len(best):
            best = feature
    return best or scene

_DDL = f"""
CREATE TABLE IF NOT EXISTS `{_TABLE}` (
    id INT PRIMARY KEY AUTO_INCREMENT,
    feature VARCHAR(64) UNIQUE NOT NULL COMMENT '功能标识，对应 scene 前缀',
    enabled TINYINT(1) DEFAULT 1,
    daily_token_budget INT DEFAULT NULL COMMENT '该功能每日 token 上限，NULL=不限',
    modified_by VARCHAR(64) DEFAULT 'system' COMMENT '最后修改人',
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
""".strip()

_SEED_SQL = f"""
INSERT IGNORE INTO `{_TABLE}` (feature, enabled, daily_token_budget) VALUES
('strategy_gen', 1, NULL),
('strategy_refine', 1, NULL),
('strategy_repair', 1, NULL),
('chat', 1, NULL),
('trade_gate', 1, 100000),
('report_generate', 1, 150000),
('report_cron_pregenerate', 0, 200000)
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
                    cur.execute(_SEED_SQL)
            _table_ready = True
        except Exception as exc:
            logging.warning("[ai.feature_switch] 建表失败: %s", exc)


def _load_switch(feature: str) -> Optional[Dict[str, Any]]:
    """加载单个功能开关配置。"""
    _ensure_table()
    try:
        rows = mdb.executeSqlFetch(
            f"SELECT feature, enabled, daily_token_budget FROM `{_TABLE}` WHERE feature=%s LIMIT 1",
            (feature,))
        if not rows:
            return None
        r = rows[0]
        if isinstance(r, (list, tuple)):
            return {'feature': r[0], 'enabled': bool(r[1]), 'daily_token_budget': r[2]}
        return {'feature': r.get('feature'), 'enabled': bool(r.get('enabled')),
                'daily_token_budget': r.get('daily_token_budget')}
    except Exception as exc:
        logging.warning("[ai.feature_switch] 查询失败（fail-open）: %s", exc)
        return None  # fail-open: 查询失败视为允许


def load_all_switches() -> List[Dict[str, Any]]:
    """加载所有功能开关。"""
    _ensure_table()
    try:
        rows = mdb.executeSqlFetch(
            f"SELECT feature, enabled, daily_token_budget, modified_by, updated_at "
            f"FROM `{_TABLE}` ORDER BY id", ())
        result = []
        for r in (rows or []):
            if isinstance(r, (list, tuple)):
                result.append({
                    'feature': r[0], 'enabled': bool(r[1]),
                    'daily_token_budget': r[2], 'modified_by': r[3],
                    'updated_at': r[4],
                })
            else:
                result.append({
                    'feature': r.get('feature'), 'enabled': bool(r.get('enabled')),
                    'daily_token_budget': r.get('daily_token_budget'),
                    'modified_by': r.get('modified_by'),
                    'updated_at': r.get('updated_at'),
                })
        return result
    except Exception as exc:
        logging.warning("[ai.feature_switch] load_all 失败: %s", exc)
        return []


def _query_today_tokens_by_prefix(scene_prefix: str) -> int:
    """查询今日某 scene 前缀下的累计 token 消耗。"""
    try:
        rows = mdb.executeSqlFetch(
            f"SELECT COALESCE(SUM(total_tokens),0) FROM `{_AUDIT_TABLE}` "
            "WHERE scene LIKE %s AND DATE(created_at) = CURDATE()",
            (scene_prefix + '%',))
        if not rows:
            return 0
        r = rows[0]
        return int(r[0] if isinstance(r, (list, tuple)) else r.get('COALESCE(SUM(total_tokens),0)', 0)) or 0
    except Exception as exc:
        logging.warning("[ai.feature_switch] 查询日 token 失败（fail-open）: %s", exc)
        return 0


def is_feature_enabled(feature: str) -> bool:
    """检查某 AI 功能是否启用 + 日预算未超。

    Fail-open：DB 不可用时返回 True（不阻断业务）。
    """
    switch = _load_switch(feature)
    if switch is None:
        return True  # 未配置的功能默认允许
    if not switch['enabled']:
        return False
    budget = switch['daily_token_budget']
    if budget is not None and budget > 0:
        prefix = _FEATURE_SCENE_PREFIX.get(feature, feature)
        used_today = _query_today_tokens_by_prefix(prefix)
        if used_today >= budget:
            return False
    return True


def check_feature(feature_or_scene: str) -> None:
    """检查功能开关，未启用或超预算时抛 AIError。

    接受 feature 标识或实际 scene 值（自动解析为所属 feature）。
    """
    feature = _resolve_scene_to_feature(feature_or_scene)
    if not is_feature_enabled(feature):
        switch = _load_switch(feature)
        if switch and not switch['enabled']:
            raise AIError(f"AI 功能 [{feature}] 已被管理员禁用")
        raise AIError(f"AI 功能 [{feature}] 今日 token 预算已耗尽")


def update_feature(feature: str, *, enabled: Optional[bool] = None,
                   daily_token_budget: Optional[int] = None,
                   modified_by: str = 'system') -> bool:
    """更新功能开关配置。返回是否成功。"""
    _ensure_table()
    parts = []
    params: list = []
    if enabled is not None:
        parts.append("enabled=%s")
        params.append(1 if enabled else 0)
    if daily_token_budget is not None:
        parts.append("daily_token_budget=%s")
        params.append(daily_token_budget if daily_token_budget > 0 else None)
    if not parts:
        return False
    parts.append("modified_by=%s")
    params.append(modified_by)
    params.append(feature)
    try:
        with mdb.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE `{_TABLE}` SET {', '.join(parts)} WHERE feature=%s",
                    tuple(params))
            conn.commit()
        return True
    except Exception as exc:
        logging.warning("[ai.feature_switch] update 失败: %s", exc)
        return False
