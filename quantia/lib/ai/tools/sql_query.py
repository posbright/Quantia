#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sql_query 工具：受白名单限制的只读 SQL。

安全约束（per spec §4.5）：
- 只允许 SELECT；INSERT/UPDATE/DELETE/REPLACE/DDL 一律拒绝。
- 仅允许查询项目自有表前缀：cn_stock_* / cn_etf_* / QUANTIA_* / cn_stock_ai_*。
- LIMIT 强制注入：默认 100，最大 1000。
- 单条 SQL，不允许分号串联。
- 输出按字节截断 32 KB。
"""

import re
from typing import Any, Dict, List

import quantia.lib.database as mdb

from quantia.lib.ai.tools import Tool, ToolError

__author__ = 'Quantia'
__date__ = '2026/05/11'

_ALLOWED_PREFIXES = ('cn_stock_', 'cn_etf_', 'QUANTIA_')
_FORBIDDEN_RE = re.compile(
    r'\b(insert|update|delete|replace|drop|alter|create|truncate|grant|revoke|'
    r'rename|lock|unlock|call|use|set|do|handler|optimize|repair|analyze|'
    r'load|outfile|dumpfile|into\s+outfile)\b',
    re.IGNORECASE,
)
_TABLE_RE = re.compile(r'\b(?:from|join)\s+([`"]?)([A-Za-z_][A-Za-z0-9_]*)\1', re.IGNORECASE)
_LIMIT_RE = re.compile(r'\blimit\s+(\d+)(?:\s*,\s*\d+)?\s*$', re.IGNORECASE)
_DEFAULT_LIMIT = 100
_MAX_LIMIT = 1000
_MAX_OUTPUT_BYTES = 32 * 1024


def _strip_concept_column(sql: str) -> str:
    """Best-effort rewrite to drop missing concept column from SELECT list."""
    s = sql
    # concept, xxx
    s = re.sub(r'(?i)\bconcept\b\s*,\s*', '', s)
    # xxx, concept
    s = re.sub(r'(?i),\s*\bconcept\b(\s|$)', r'\1', s)
    return s


def _normalize_sql(sql: str) -> str:
    sql = (sql or '').strip()
    if sql.endswith(';'):
        sql = sql[:-1].rstrip()
    return sql


def _check_safety(sql: str) -> None:
    if not sql:
        raise ToolError('SQL 不能为空')
    if ';' in sql:
        raise ToolError('禁止多语句串联')
    lower = sql.lstrip().lower()
    if not (lower.startswith('select') or lower.startswith('with')):
        raise ToolError('仅允许 SELECT / WITH 查询')
    if _FORBIDDEN_RE.search(sql):
        raise ToolError('SQL 包含被禁用的关键字')
    tables = [m.group(2).lower() for m in _TABLE_RE.finditer(sql)]
    if not tables:
        raise ToolError('未识别到 FROM/JOIN 表名，无法做白名单校验')
    for t in tables:
        if not any(t.startswith(p) for p in _ALLOWED_PREFIXES):
            raise ToolError(f'表 {t} 不在白名单（允许前缀 {_ALLOWED_PREFIXES}）')


def _inject_limit(sql: str, requested_limit: int) -> str:
    eff_limit = max(1, min(_MAX_LIMIT, int(requested_limit or _DEFAULT_LIMIT)))
    if _LIMIT_RE.search(sql):
        # 用户已指定 LIMIT；以请求 limit 与用户值取小者为最终值
        m = _LIMIT_RE.search(sql)
        user_limit = int(m.group(1))
        final_limit = min(user_limit, eff_limit)
        return _LIMIT_RE.sub(f'LIMIT {final_limit}', sql)
    return f'{sql} LIMIT {eff_limit}'


def _truncate_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """整体输出按字节截断。返回完整行列表（截断时附 _truncated 标记行）。"""
    import json as _json
    encoded = _json.dumps(rows, ensure_ascii=False, default=str).encode('utf-8')
    if len(encoded) <= _MAX_OUTPUT_BYTES:
        return rows
    # 折半丢弃直到 <= 阈值
    keep = len(rows)
    while keep > 0:
        keep = max(1, keep // 2)
        candidate = rows[:keep]
        if len(_json.dumps(candidate, ensure_ascii=False, default=str).encode('utf-8')) <= _MAX_OUTPUT_BYTES:
            return candidate + [{'_truncated': True, 'kept': keep, 'total': len(rows)}]
        if keep == 1:
            return [{'_truncated': True, 'note': '单行超过输出上限'}]
    return []


class SqlQueryTool(Tool):
    name = 'sql_query'
    description = (
        '执行只读 SELECT 查询，受表前缀白名单与 LIMIT 限制。'
        '可用于查询 cn_stock_* / cn_etf_* / QUANTIA_* 系列业务表。'
    )
    parameters = {
        'type': 'object',
        'required': ['sql'],
        'properties': {
            'sql': {
                'type': 'string',
                'description': '单条 SELECT/WITH 查询，禁止分号串联与写操作',
            },
            'limit': {
                'type': 'integer',
                'description': f'返回行数上限（默认 {_DEFAULT_LIMIT}，最大 {_MAX_LIMIT}）',
                'minimum': 1,
                'maximum': _MAX_LIMIT,
            },
        },
    }

    def run(self, args: Dict[str, Any]) -> Dict[str, Any]:
        sql_in = args.get('sql', '')
        if not isinstance(sql_in, str):
            raise ToolError('sql 必须是字符串')
        sql = _normalize_sql(sql_in)
        _check_safety(sql)
        # P1-4（一轮审计）：LLM 可能传不合法的 limit 类型，需提前报错避免
        # _inject_limit 内部 int(...) 报未捕获异常。
        raw_limit = args.get('limit')
        if raw_limit in (None, ''):
            limit_val = _DEFAULT_LIMIT
        else:
            try:
                limit_val = int(raw_limit)
            except (TypeError, ValueError):
                raise ToolError(f'limit 必须是整数，收到: {raw_limit!r}')
        sql = _inject_limit(sql, limit_val)
        try:
            rows = mdb.executeSqlFetch(sql)
        except Exception as exc:
            msg = str(exc)
            # Some deployments do not have cn_stock_spot.concept; retry once without this column.
            if "Unknown column 'concept'" in msg and 'cn_stock_spot' in sql.lower():
                patched_sql = _strip_concept_column(sql)
                if patched_sql != sql:
                    try:
                        rows = mdb.executeSqlFetch(patched_sql)
                        sql = patched_sql
                    except Exception as exc2:
                        raise ToolError(f'SQL 执行失败: {exc2}') from exc2
                else:
                    raise ToolError(f'SQL 执行失败: {exc}') from exc
            else:
                raise ToolError(f'SQL 执行失败: {exc}') from exc
        # 标准化为 list[dict]
        out_rows: List[Dict[str, Any]] = []
        for r in rows or []:
            if isinstance(r, dict):
                out_rows.append(r)
            elif isinstance(r, (list, tuple)):
                out_rows.append({f'col{i}': v for i, v in enumerate(r)})
            else:
                out_rows.append({'value': r})
        return {
            'sql': sql,
            'row_count': len(out_rows),
            'rows': _truncate_rows(out_rows),
        }
