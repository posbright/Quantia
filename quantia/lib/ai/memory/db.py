#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ConversationMemory MySQL 持久化实现（spec §3.4 / §11.3 / §M8）。

落库 cn_stock_ai_conversation，messages_json 一次性整列覆盖（小数据量下
比拆 messages 副表更简单，且支持事务）。
"""

from __future__ import annotations

import json
import logging
import threading
import time
import weakref
from datetime import datetime
from typing import Dict, List, Optional

import quantia.lib.database as mdb
from quantia.lib.ai.memory.base import (
    Conversation, ConversationMemory, Message,
    coerce_role, estimate_messages_tokens, truncate_to_budget,
)

_TABLE = 'cn_stock_ai_conversation'
_table_ready = False
_lock = threading.Lock()

# audit-fix-P0-1: per-conversation_id 锁，避免 append 读-改-写丢消息
# audit-fix-2-P0-A: 使用 WeakValueDictionary 让锁在所有持有者释放后自动从 dict 中移除，
# 不再需要 .clear() 兜底（清空可能丢弃正在被持有的锁，破坏 per-CID 串行化）。
# threading.Lock() 是 C 实现的 _thread.lock，不支持 weakref，需要包一层 Python 类。
class _RefLock:
    __slots__ = ('_lock', '__weakref__')

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def __enter__(self):
        self._lock.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._lock.release()


_cid_locks: 'weakref.WeakValueDictionary[str, _RefLock]' = weakref.WeakValueDictionary()
_cid_locks_lock = threading.Lock()

# audit-fix-P2-8: messages_json 会话消息总数上限（超出从最旧丢弃、保留 head system）
_MAX_MSGS_PER_CONV = 200


def _get_cid_lock(cid: str) -> _RefLock:
    with _cid_locks_lock:
        lk = _cid_locks.get(cid)
        if lk is None:
            lk = _RefLock()
            _cid_locks[cid] = lk
        return lk

_DDL = f"""
CREATE TABLE IF NOT EXISTS {_TABLE} (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    conversation_id VARCHAR(64) UNIQUE NOT NULL,
    scene VARCHAR(32) NOT NULL,
    agent VARCHAR(64) NULL,
    title VARCHAR(255) NULL,
    messages_json MEDIUMTEXT NOT NULL,
    total_tokens INT NOT NULL DEFAULT 0,
    user_id VARCHAR(64) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_scene_updated (scene, updated_at),
    INDEX idx_user_updated (user_id, updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
""".strip()


def _ensure_table() -> None:
    global _table_ready
    if _table_ready:
        return
    with _lock:
        if _table_ready:
            return
        # 不使用 try/except，允许异常向上报错，由 factory 决定是否回退 inmem。
        with mdb.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(_DDL)
        _table_ready = True


def _epoch(value) -> float:
    if value is None:
        return time.time()
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, datetime):
        return value.timestamp()
    return time.time()


def _row_to_conv(row) -> Conversation:
    """row 可能是 tuple 或 Row（dict-like）。"""
    def g(idx, key):
        if isinstance(row, (list, tuple)):
            return row[idx]
        if hasattr(row, 'get'):
            return row.get(key)
        return getattr(row, key, None)

    raw_msgs = g(5, 'messages_json') or '[]'
    try:
        msgs = [Message.from_dict(m) for m in (json.loads(raw_msgs) or [])]
    except Exception:
        msgs = []
    return Conversation(
        conversation_id=str(g(1, 'conversation_id')),
        scene=str(g(2, 'scene') or 'chat'),
        agent=g(3, 'agent') or None,
        title=g(4, 'title') or None,
        messages=msgs,
        total_tokens=int(g(6, 'total_tokens') or 0),
        user_id=g(7, 'user_id') or None,
        created_at=_epoch(g(8, 'created_at')),
        updated_at=_epoch(g(9, 'updated_at')),
    )


_SELECT = (
    'SELECT id, conversation_id, scene, agent, title, messages_json, '
    'total_tokens, user_id, created_at, updated_at '
    f'FROM {_TABLE}'
)


class DbConversationMemory(ConversationMemory):
    def __init__(self) -> None:
        # 启动时探测：报错会被 factory 捕获并回退 inmem。
        _ensure_table()

    def get(self, conversation_id: str) -> Optional[Conversation]:
        _ensure_table()
        try:
            rows = mdb.executeSqlFetch(
                _SELECT + ' WHERE conversation_id=%s', (conversation_id,))
        except Exception as exc:
            logging.warning(f'[ai.memory.db.get] {exc}')
            return None
        if not rows:
            return None
        return _row_to_conv(rows[0])

    def get_or_create(self, conversation_id, *, scene, user_id=None,
                      agent=None, title=None) -> Conversation:
        _ensure_table()
        with _get_cid_lock(conversation_id):
            existing = self.get(conversation_id)
            if existing is not None:
                # 补齐空字段
                updates = []
                params: list = []
                if user_id and not existing.user_id:
                    updates.append('user_id=%s'); params.append(user_id); existing.user_id = user_id
                if agent and not existing.agent:
                    updates.append('agent=%s'); params.append(agent); existing.agent = agent
                if title and not existing.title:
                    updates.append('title=%s'); params.append(title[:255]); existing.title = title[:255]
                if updates:
                    params.append(conversation_id)
                    try:
                        mdb.executeSql(
                            f'UPDATE {_TABLE} SET ' + ','.join(updates)
                            + ' WHERE conversation_id=%s', tuple(params))
                    except Exception as exc:
                        logging.warning(f'[ai.memory.db.get_or_create.update] {exc}')
                return existing
            # 新建
            conv = Conversation(
                conversation_id=conversation_id,
                scene=scene, agent=agent, user_id=user_id, title=title,
            )
            try:
                mdb.executeSql(
                    f'INSERT INTO {_TABLE} '
                    '(conversation_id, scene, agent, title, messages_json, '
                    ' total_tokens, user_id) VALUES (%s,%s,%s,%s,%s,%s,%s)',
                    (conversation_id, scene, agent, title[:255] if title else None,
                     '[]', 0, user_id),
                )
            except Exception as exc:
                # audit-fix-P1-4: 并发 INSERT 冲突 → 重取一次
                msg = str(exc).lower()
                if '1062' in msg or 'duplicate' in msg:
                    logging.info(f'[ai.memory.db.get_or_create] duplicate, re-fetching: {conversation_id}')
                    fetched = self.get(conversation_id)
                    if fetched is not None:
                        return fetched
                logging.warning(f'[ai.memory.db.get_or_create.insert] {exc}')
            return conv

    def append(self, conversation_id, role, content, *,
               scene=None, user_id=None, agent=None) -> None:
        _ensure_table()
        # audit-fix-P0-1: 锁住从 get 到 update 的读-改-写区间
        with _get_cid_lock(conversation_id):
            conv = self.get(conversation_id)
            if conv is None:
                # get_or_create 自身也要拿同一把锁（RLock 不适用于跨函数）——
                # 改为直接内联 INSERT 逻辑避免重入
                conv = Conversation(
                    conversation_id=conversation_id,
                    scene=scene or 'chat', user_id=user_id, agent=agent,
                )
                try:
                    mdb.executeSql(
                        f'INSERT INTO {_TABLE} '
                        '(conversation_id, scene, agent, title, messages_json, '
                        ' total_tokens, user_id) VALUES (%s,%s,%s,%s,%s,%s,%s)',
                        (conversation_id, conv.scene, agent, None,
                         '[]', 0, user_id),
                    )
                except Exception as exc:
                    msg = str(exc).lower()
                    if '1062' in msg or 'duplicate' in msg:
                        fetched = self.get(conversation_id)
                        if fetched is not None:
                            conv = fetched
                    else:
                        logging.warning(f'[ai.memory.db.append.insert] {exc}')
            msg_obj = Message(role=coerce_role(role), content=content)
            conv.messages.append(msg_obj)
            # audit-fix-P2-8: 消息总数超上限时，从最旧丢弃（保留 head system）
            if len(conv.messages) > _MAX_MSGS_PER_CONV:
                head = []
                if conv.messages and conv.messages[0].role == 'system':
                    head = [conv.messages[0]]
                tail = conv.messages[-(_MAX_MSGS_PER_CONV - len(head)):]
                conv.messages = head + tail
            if not conv.title and role == 'user':
                conv.title = (content[:60].strip() or None)
            conv.total_tokens = estimate_messages_tokens(conv.messages)
            try:
                mdb.executeSql(
                    f'UPDATE {_TABLE} SET messages_json=%s, total_tokens=%s, '
                    ' title=COALESCE(title, %s) WHERE conversation_id=%s',
                    (json.dumps([m.to_dict() for m in conv.messages],
                                ensure_ascii=False),
                     conv.total_tokens, conv.title, conversation_id),
                )
            except Exception as exc:
                logging.warning(f'[ai.memory.db.append] {exc}')

    def load(self, conversation_id, *, max_tokens: int = 4000) -> List[Message]:
        conv = self.get(conversation_id)
        if conv is None:
            return []
        return truncate_to_budget(list(conv.messages), max_tokens)

    def list(self, *, user_id=None, scene=None, limit: int = 50) -> List[Conversation]:
        _ensure_table()
        clauses = []
        params: list = []
        if user_id:
            clauses.append('user_id=%s'); params.append(user_id)
        if scene:
            clauses.append('scene=%s'); params.append(scene)
        where = (' WHERE ' + ' AND '.join(clauses)) if clauses else ''
        try:
            rows = mdb.executeSqlFetch(
                _SELECT + where + ' ORDER BY updated_at DESC LIMIT %s',
                tuple(params) + (int(limit),))
        except Exception as exc:
            logging.warning(f'[ai.memory.db.list] {exc}')
            return []
        return [_row_to_conv(r) for r in (rows or [])]

    def delete(self, conversation_id: str) -> bool:
        _ensure_table()
        try:
            mdb.executeSql(
                f'DELETE FROM {_TABLE} WHERE conversation_id=%s',
                (conversation_id,))
            return True
        except Exception as exc:
            logging.warning(f'[ai.memory.db.delete] {exc}')
            return False

    def rename(self, conversation_id: str, title: str) -> bool:
        _ensure_table()
        try:
            mdb.executeSql(
                f'UPDATE {_TABLE} SET title=%s WHERE conversation_id=%s',
                (title[:255], conversation_id))
            return True
        except Exception as exc:
            logging.warning(f'[ai.memory.db.rename] {exc}')
            return False
