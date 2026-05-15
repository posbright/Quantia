#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cn_stock_ai_kb 表存储与检索（spec §3.4 / §11.2 / §M9）。

设计：
- MySQL FULLTEXT 主路径；ngram parser 不一定可用，配 LIKE 兜底（中文短查询）。
- upsert 走 UNIQUE (source_type, source_id)，indexer 重复执行幂等。
- 单条 content 截断到 _MAX_CONTENT_BYTES，避免 MEDIUMTEXT 失控。
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

import quantia.lib.database as mdb

_TABLE = 'cn_stock_ai_kb'
_table_ready = False
_lock = threading.Lock()

_MAX_TITLE_CHARS = 255
_MAX_CONTENT_CHARS = 16_000  # 约 32KB UTF-8，远小于 MEDIUMTEXT 上限
_MIN_QUERY_CHARS = 1
_MAX_QUERY_CHARS = 256
_DEFAULT_TOP_K = 5
_MAX_TOP_K = 20
_MAX_SNIPPET_CHARS = 600

_DDL = f"""
CREATE TABLE IF NOT EXISTS {_TABLE} (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    source_type VARCHAR(32) NOT NULL,
    source_id VARCHAR(64) NULL,
    title VARCHAR(255),
    content MEDIUMTEXT,
    embedding BLOB NULL,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_source (source_type, source_id),
    FULLTEXT KEY ftx_content (title, content) WITH PARSER ngram
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
""".strip()

# audit-fix-1-P2: 部分 MySQL 构建未启 ngram parser，则回退不带 parser 的 DDL，
# Chinese 查询会走 LIKE 主路径（见 _is_cjk_query）。
# audit-fix-2-P3: 用 regex 去掉 WITH PARSER ngram 子句，对 DDL 重排版更鲁棒。
_DDL_NO_NGRAM = re.sub(r'\s+WITH\s+PARSER\s+ngram', '', _DDL)


@dataclass
class KbDoc:
    source_type: str
    source_id: Optional[str]
    title: str
    content: str
    score: float = 0.0
    snippet: str = ''
    updated_at: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            'source_type': self.source_type,
            'source_id': self.source_id,
            'title': self.title,
            'snippet': self.snippet or self.content[:_MAX_SNIPPET_CHARS],
            'score': round(float(self.score), 4),
            'updated_at': self.updated_at,
        }


def _ensure_table() -> None:
    global _table_ready
    if _table_ready:
        return
    with _lock:
        if _table_ready:
            return
        with mdb.get_connection() as conn:
            try:
                with conn.cursor() as cur:
                    cur.execute(_DDL)
            except Exception as exc:
                # ngram parser 不可用 → 回退不带 parser
                # audit-fix-2-P0/P1: 开新 cursor，避免某些驱动在 execute 报错后 cursor 状态不可用
                logging.info(f'[ai.retrieval] ngram parser 不可用，回退普通 FULLTEXT: {exc}')
                with conn.cursor() as cur:
                    cur.execute(_DDL_NO_NGRAM)
        _table_ready = True


def _is_cjk_query(s: str) -> bool:
    """audit-fix-1-P2: 含 CJK 字符（中/日/韩）的查询，
    跳过 FULLTEXT（默认 parser 不能切中文，ngram 可能未启），
    直接走 LIKE 主路径，避免 FULLTEXT 返回不相关低分结果遮蔽 LIKE 。"""
    for ch in s or '':
        cp = ord(ch)
        if (0x4E00 <= cp <= 0x9FFF or       # CJK Unified Ideographs
                0x3040 <= cp <= 0x30FF or  # ひらがな + カタカナ
                0xAC00 <= cp <= 0xD7AF):    # Hangul Syllables
            return True
    return False


def _truncate(s: Optional[str], n: int) -> str:
    if not s:
        return ''
    s = str(s)
    return s if len(s) <= n else s[:n]


def _make_snippet(content: str, query_terms: Sequence[str]) -> str:
    """围绕第一个命中 term 截 ±200 字；找不到就直接 head。"""
    if not content:
        return ''
    body = content
    for term in query_terms:
        if not term:
            continue
        idx = body.find(term)
        if idx >= 0:
            start = max(0, idx - 200)
            end = min(len(body), idx + 400)
            prefix = '…' if start > 0 else ''
            suffix = '…' if end < len(body) else ''
            return prefix + body[start:end] + suffix
    return _truncate(body, _MAX_SNIPPET_CHARS)


class KbStore:
    """cn_stock_ai_kb CRUD + 检索。"""

    def __init__(self) -> None:
        _ensure_table()

    # ── 写入 ────────────────────────────────────────────
    def upsert(self, source_type: str, source_id: Optional[str],
               title: str, content: str) -> bool:
        if not source_type:
            raise ValueError('source_type 不能为空')
        title = _truncate(title, _MAX_TITLE_CHARS)
        content = _truncate(content, _MAX_CONTENT_CHARS)
        # source_id 为 None 时放空串，避免 UNIQUE NULL 多值重复
        sid = '' if source_id is None else str(source_id)
        try:
            mdb.executeSql(
                f'INSERT INTO {_TABLE} (source_type, source_id, title, content) '
                'VALUES (%s,%s,%s,%s) '
                'ON DUPLICATE KEY UPDATE title=VALUES(title), content=VALUES(content)',
                (source_type, sid, title, content),
            )
            return True
        except Exception as exc:
            logging.warning(f'[ai.retrieval.upsert] {source_type}/{sid}: {exc}')
            return False

    def delete_by_type(self, source_type: str) -> int:
        """删除某来源类型下所有记录（indexer 全量重建场景）。"""
        if not source_type:
            return 0
        try:
            mdb.executeSql(
                f'DELETE FROM {_TABLE} WHERE source_type=%s', (source_type,))
            return 1
        except Exception as exc:
            logging.warning(f'[ai.retrieval.delete_by_type] {exc}')
            return 0

    def count(self, source_type: Optional[str] = None) -> int:
        try:
            if source_type:
                rows = mdb.executeSqlFetch(
                    f'SELECT COUNT(1) FROM {_TABLE} WHERE source_type=%s',
                    (source_type,))
            else:
                rows = mdb.executeSqlFetch(
                    f'SELECT COUNT(1) FROM {_TABLE}', ())
        except Exception as exc:
            logging.warning(f'[ai.retrieval.count] {exc}')
            return 0
        if not rows:
            return 0
        first = rows[0]
        return int(first[0] if isinstance(first, (list, tuple)) else
                   list(first.values())[0])

    # ── 检索 ────────────────────────────────────────────
    def search(self, query: str, *, top_k: int = _DEFAULT_TOP_K,
               source_types: Optional[Sequence[str]] = None) -> List[KbDoc]:
        q = (query or '').strip()
        if len(q) < _MIN_QUERY_CHARS:
            return []
        if len(q) > _MAX_QUERY_CHARS:
            q = q[:_MAX_QUERY_CHARS]
        try:
            top_k = max(1, min(_MAX_TOP_K, int(top_k)))
        except (TypeError, ValueError):
            top_k = _DEFAULT_TOP_K
        terms = [t for t in q.replace('，', ' ').replace(',', ' ').split() if t]
        if not terms:
            terms = [q]

        # audit-fix-1-P2: 中文查询走 LIKE 主路径（FULLTEXT 默认 parser 无法切中文）
        if _is_cjk_query(q):
            return self._search_like(terms, top_k, source_types)

        # 路径 1: FULLTEXT (NATURAL LANGUAGE MODE)
        results = self._search_fulltext(q, terms, top_k, source_types)
        if results:
            return results
        # 路径 2: LIKE 兑底
        return self._search_like(terms, top_k, source_types)

    def _build_type_filter(self, source_types: Optional[Sequence[str]]) -> tuple:
        if not source_types:
            return '', ()
        types = [str(t) for t in source_types if t]
        if not types:
            return '', ()
        placeholders = ','.join(['%s'] * len(types))
        return f' AND source_type IN ({placeholders})', tuple(types)

    def _search_fulltext(self, q: str, terms: Sequence[str], top_k: int,
                          source_types: Optional[Sequence[str]]) -> List[KbDoc]:
        type_clause, type_params = self._build_type_filter(source_types)
        sql = (
            'SELECT source_type, source_id, title, content, updated_at, '
            'MATCH(title, content) AGAINST (%s IN NATURAL LANGUAGE MODE) AS score '
            f'FROM {_TABLE} '
            'WHERE MATCH(title, content) AGAINST (%s IN NATURAL LANGUAGE MODE)'
            + type_clause
            + ' ORDER BY score DESC LIMIT %s'
        )
        params = (q, q) + type_params + (top_k,)
        try:
            rows = mdb.executeSqlFetch(sql, params)
        except Exception as exc:
            logging.info(f'[ai.retrieval.fulltext] 跳过 FULLTEXT: {exc}')
            return []
        return self._rows_to_docs(rows or [], terms)

    def _search_like(self, terms: Sequence[str], top_k: int,
                     source_types: Optional[Sequence[str]]) -> List[KbDoc]:
        # 任一 term 命中 title/content 即可，AND 多 term 提升精度
        like_clauses = []
        like_params: list = []
        for t in terms:
            like_clauses.append('(title LIKE %s OR content LIKE %s)')
            like_params.extend([f'%{t}%', f'%{t}%'])
        type_clause, type_params = self._build_type_filter(source_types)
        sql = (
            'SELECT source_type, source_id, title, content, updated_at '
            f'FROM {_TABLE} WHERE '
            + ' AND '.join(like_clauses)
            + type_clause
            + ' ORDER BY updated_at DESC LIMIT %s'
        )
        params = tuple(like_params) + type_params + (top_k,)
        try:
            rows = mdb.executeSqlFetch(sql, params)
        except Exception as exc:
            logging.warning(f'[ai.retrieval.like] {exc}')
            return []
        docs = self._rows_to_docs(rows or [], terms)
        # LIKE 模式没有打分，按 term 命中次数粗估
        for d in docs:
            hit = sum(d.content.count(t) + d.title.count(t) for t in terms)
            d.score = float(hit)
        docs.sort(key=lambda x: x.score, reverse=True)
        return docs

    @staticmethod
    def _rows_to_docs(rows, terms: Sequence[str]) -> List[KbDoc]:
        out: List[KbDoc] = []
        for r in rows:
            if isinstance(r, (list, tuple)):
                stype, sid, title, content, updated_at = r[0], r[1], r[2], r[3], r[4]
                score = float(r[5]) if len(r) > 5 and r[5] is not None else 0.0
            else:
                stype = r.get('source_type')
                sid = r.get('source_id')
                title = r.get('title')
                content = r.get('content')
                updated_at = r.get('updated_at')
                score = float(r.get('score') or 0.0)
            content_s = str(content or '')
            doc = KbDoc(
                source_type=str(stype or ''),
                source_id=(None if sid in (None, '') else str(sid)),
                title=str(title or ''),
                content=content_s,
                score=score,
                snippet=_make_snippet(content_s, terms),
                updated_at=str(updated_at) if updated_at is not None else None,
            )
            out.append(doc)
        return out
