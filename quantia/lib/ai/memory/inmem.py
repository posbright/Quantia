#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""进程内 ConversationMemory（默认实现，spec §11.3）。

无 TTL，按 LRU 截断到 QUANTIA_AI_MEMORY_MAX_CONVS（默认 200）。
"""

from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict
from typing import List, Optional

from quantia.lib.ai.memory.base import (
    Conversation, ConversationMemory, Message,
    coerce_role, estimate_messages_tokens, truncate_to_budget,
)


def _max_convs() -> int:
    try:
        # audit-fix-P3-14: \u4e0a\u9650 5000 \u907f\u514d\u8bef\u914d OOM
        return min(5000, max(10, int(os.environ.get('QUANTIA_AI_MEMORY_MAX_CONVS', '200'))))
    except (TypeError, ValueError):
        return 200


# audit-fix-P2-8: \u6bcf\u4f1a\u8bdd\u6d88\u606f\u603b\u6570\u4e0a\u9650
_MAX_MSGS_PER_CONV = 200


class InMemoryConversationMemory(ConversationMemory):
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._store: 'OrderedDict[str, Conversation]' = OrderedDict()

    def _touch(self, conv: Conversation) -> None:
        conv.updated_at = time.time()
        # LRU
        self._store.move_to_end(conv.conversation_id)
        while len(self._store) > _max_convs():
            self._store.popitem(last=False)

    def get_or_create(self, conversation_id, *, scene, user_id=None,
                      agent=None, title=None) -> Conversation:
        with self._lock:
            conv = self._store.get(conversation_id)
            if conv is None:
                conv = Conversation(
                    conversation_id=conversation_id,
                    scene=scene, user_id=user_id, agent=agent, title=title,
                )
                self._store[conversation_id] = conv
            else:
                # 允许后续调用补齐字段（不覆盖已有非空值）
                if not conv.scene:
                    conv.scene = scene
                if user_id and not conv.user_id:
                    conv.user_id = user_id
                if agent and not conv.agent:
                    conv.agent = agent
                if title and not conv.title:
                    conv.title = title
            self._touch(conv)
            return conv

    def get(self, conversation_id: str) -> Optional[Conversation]:
        with self._lock:
            return self._store.get(conversation_id)

    def append(self, conversation_id, role, content, *,
               scene=None, user_id=None, agent=None) -> None:
        with self._lock:
            conv = self._store.get(conversation_id)
            if conv is None:
                conv = Conversation(
                    conversation_id=conversation_id,
                    scene=scene or 'chat', user_id=user_id, agent=agent,
                )
                self._store[conversation_id] = conv
            msg = Message(role=coerce_role(role), content=content)
            conv.messages.append(msg)
            # audit-fix-P2-8
            if len(conv.messages) > _MAX_MSGS_PER_CONV:
                head = []
                if conv.messages and conv.messages[0].role == 'system':
                    head = [conv.messages[0]]
                tail = conv.messages[-(_MAX_MSGS_PER_CONV - len(head)):]
                conv.messages = head + tail
            # 首条 user 消息作为 title
            if not conv.title and role == 'user':
                conv.title = (content[:60].strip() or None)
            conv.total_tokens = estimate_messages_tokens(conv.messages)
            self._touch(conv)

    def load(self, conversation_id, *, max_tokens: int = 4000) -> List[Message]:
        with self._lock:
            conv = self._store.get(conversation_id)
            if conv is None:
                return []
            return truncate_to_budget(list(conv.messages), max_tokens)

    def list(self, *, user_id=None, scene=None, limit: int = 50) -> List[Conversation]:
        with self._lock:
            items = list(self._store.values())
        items.sort(key=lambda c: c.updated_at, reverse=True)
        out: List[Conversation] = []
        for c in items:
            if user_id and c.user_id != user_id:
                continue
            if scene and c.scene != scene:
                continue
            out.append(c)
            if len(out) >= limit:
                break
        return out

    def delete(self, conversation_id: str) -> bool:
        with self._lock:
            return self._store.pop(conversation_id, None) is not None

    def rename(self, conversation_id: str, title: str) -> bool:
        with self._lock:
            conv = self._store.get(conversation_id)
            if conv is None:
                return False
            conv.title = title[:255]
            self._touch(conv)
            return True
