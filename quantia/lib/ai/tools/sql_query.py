#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sql_query 工具：受白名单限制的只读 SQL。

安全约束（per spec §4.5）：
- 只允许 SELECT；INSERT/UPDATE/DELETE/REPLACE/DDL 一律拒绝。
- 仅允许查询项目自有表前缀：cn_stock_* / cn_etf_* / QUANTIA_* / cn_stock_ai_*。
- LIMIT 强制注入：默认 100，最大 1000。
- 单条 SQL，不允许分号串联。
- 输出按字节截断 32 KB。
- **列验证**：执行前对 SELECT 中引用的列名做真实 schema 校验，拒绝不存在的列。
"""

import logging
import re
from typing import Any, Dict, List, Optional, Set

import quantia.lib.database as mdb

from quantia.lib.ai.tools import Tool, ToolError

__author__ = 'Quantia'
__date__ = '2026/05/27'

_logger = logging.getLogger(__name__)

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

# ── 列名验证：执行前校验 SQL 中引用的列是否真实存在 ──────────────────
# 缓存 table_name -> set(column_names)，进程生命周期内有效
_SCHEMA_CACHE: Dict[str, Set[str]] = {}


def _get_table_columns(table_name: str) -> Optional[Set[str]]:
    """获取表的真实列名集合（从 MySQL INFORMATION_SCHEMA 查询，带缓存）。"""
    if table_name in _SCHEMA_CACHE:
        return _SCHEMA_CACHE[table_name]
    try:
        rows = mdb.executeSqlFetch(
            "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s",
            (table_name,)
        )
        if not rows:
            # 表可能不存在，返回 None 表示无法验证
            return None
        cols = set()
        for r in rows:
            if isinstance(r, dict):
                cols.add(r.get('COLUMN_NAME', '').lower())
            elif isinstance(r, (list, tuple)):
                cols.add(str(r[0]).lower())
        _SCHEMA_CACHE[table_name] = cols
        return cols
    except Exception as exc:
        _logger.debug(f"获取表 {table_name} schema 失败: {exc}")
        return None


# 提取 SQL 中 SELECT 列表和 WHERE/ORDER BY/GROUP BY 中引用的标识符
_SELECT_COLS_RE = re.compile(
    r'(?:SELECT\s+)(.*?)(?:\s+FROM\b)',
    re.IGNORECASE | re.DOTALL,
)
_IDENTIFIER_RE = re.compile(r'(?<![.\w])([`"]?)([a-zA-Z_][a-zA-Z0-9_]*)\1(?!\s*\()', re.IGNORECASE)
# 排除 SQL 关键字和聚合函数
_SQL_KEYWORDS = frozenset({
    'select', 'from', 'where', 'and', 'or', 'not', 'in', 'is', 'null',
    'like', 'between', 'as', 'on', 'join', 'left', 'right', 'inner', 'outer',
    'cross', 'order', 'by', 'group', 'having', 'limit', 'offset', 'union',
    'all', 'distinct', 'case', 'when', 'then', 'else', 'end', 'asc', 'desc',
    'exists', 'true', 'false', 'with', 'recursive', 'count', 'sum', 'avg',
    'min', 'max', 'if', 'ifnull', 'coalesce', 'cast', 'convert',
    'date', 'now', 'curdate', 'year', 'month', 'day', 'concat', 'substring',
    'length', 'replace', 'trim', 'upper', 'lower', 'round', 'abs', 'floor',
    'ceil', 'over', 'partition', 'row_number', 'rank', 'dense_rank',
})


def _extract_referenced_columns(sql: str, tables: List[str]) -> Dict[str, List[str]]:
    """从 SQL 中提取可能是列名的标识符，按表分组。

    返回 {table_name: [columns_that_dont_exist]}，仅包含验证失败的列。
    """
    # 先剥离字符串字面量（单引号/双引号包裹的内容），避免误提取
    cleaned_sql = re.sub(r"'[^']*'", "''", sql)
    cleaned_sql = re.sub(r'"[^"]*"', '""', cleaned_sql)
    # 剥离数字字面量
    cleaned_sql = re.sub(r'\b\d+(\.\d+)?\b', '0', cleaned_sql)

    # 提取所有非关键字、非函数的标识符
    table_set = {t.lower() for t in tables}
    identifiers: Set[str] = set()
    for m in _IDENTIFIER_RE.finditer(cleaned_sql):
        ident = m.group(2).lower()
        if ident not in _SQL_KEYWORDS and ident not in table_set:
            identifiers.add(ident)

    # 对每个表校验列
    invalid: Dict[str, List[str]] = {}
    for table in tables:
        schema = _get_table_columns(table)
        if schema is None:
            continue  # 无法获取 schema，跳过验证（表可能不存在，执行时会报错）
        bad_cols = [col for col in identifiers if col not in schema
                    and not col.startswith('col')  # 别名前缀排除
                    and len(col) > 1]  # 排除单字符别名
        if bad_cols:
            invalid[table] = bad_cols
    return invalid


def _validate_columns(sql: str, tables: List[str]) -> None:
    """执行前校验 SQL 引用的列名是否在目标表的真实 schema 中。

    若发现不存在的列，直接报错并提示可用列名，避免无效执行。
    """
    invalid = _extract_referenced_columns(sql, tables)
    if not invalid:
        return
    # 构建有用的错误信息
    parts = []
    for table, bad_cols in invalid.items():
        schema = _get_table_columns(table)
        # 只展示前 20 个可用列作为参考
        available = sorted(schema)[:20] if schema else []
        parts.append(
            f"表 `{table}` 中不存在列: {', '.join(sorted(bad_cols))}。"
            f"可用列（部分）: {', '.join(available)}"
        )
    raise ToolError('列验证失败——' + '；'.join(parts))


def _normalize_sql(sql: str) -> str:
    sql = (sql or '').strip()
    if sql.endswith(';'):
        sql = sql[:-1].rstrip()
    return sql


def _check_safety(sql: str) -> List[str]:
    """安全检查：仅允许 SELECT，白名单表前缀。返回目标表名列表。"""
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
    return tables


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
        tables = _check_safety(sql)
        # ── 列验证：执行前确认引用列在真实 schema 中存在 ──
        _validate_columns(sql, tables)
        # P1-4（一轮审计）：LLM 可能传不合法的 limit 类型，需提前报错避免
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
