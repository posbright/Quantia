#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ConversationMemory 工厂入口（spec §11.3 / §M8）。

QUANTIA_AI_MEMORY_BACKEND=db|inmem  （默认 db；DB 不可用时落地 inmem fallback）
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Optional

from quantia.lib.ai.memory.base import (
    Conversation, ConversationMemory, Message,
    estimate_tokens, estimate_messages_tokens, truncate_to_budget,
)
from quantia.lib.ai.memory.inmem import InMemoryConversationMemory

__all__ = [
    'ConversationMemory', 'Conversation', 'Message',
    'estimate_tokens', 'estimate_messages_tokens', 'truncate_to_budget',
    'get_memory', 'reset_memory_for_tests',
]

_lock = threading.Lock()
_singleton: Optional[ConversationMemory] = None


def _backend_choice() -> str:
    raw = (os.environ.get('QUANTIA_AI_MEMORY_BACKEND') or 'db').strip().lower()
    return raw if raw in ('db', 'inmem') else 'db'


def get_memory() -> ConversationMemory:
    global _singleton
    if _singleton is not None:
        return _singleton
    with _lock:
        if _singleton is not None:
            return _singleton
        if _backend_choice() == 'inmem':
            _singleton = InMemoryConversationMemory()
        else:
            try:
                from quantia.lib.ai.memory.db import DbConversationMemory
                _singleton = DbConversationMemory()
            except Exception as exc:
                logging.warning(
                    f'[ai.memory] 加载 DbConversationMemory 失败，回退 inmem: {exc}')
                _singleton = InMemoryConversationMemory()
        return _singleton


def reset_memory_for_tests(impl: Optional[ConversationMemory] = None) -> None:
    """测试钩子：替换或清空全局 memory 单例。"""
    global _singleton
    with _lock:
        _singleton = impl
