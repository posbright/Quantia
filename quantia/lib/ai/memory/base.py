#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ConversationMemory 抽象与公共数据结构（spec §11.3 / §M8）。

调用方模式：
    mem = get_memory()                                   # 工厂选择 inmem/db
    conv = mem.get_or_create('uuid-x', scene='chat',
                              user_id='1.2.3.4', agent='general_assistant')
    history = mem.load('uuid-x', max_tokens=4000)        # 自动截断/摘要
    mem.append('uuid-x', 'user', user_text)
    mem.append('uuid-x', 'assistant', reply_text)

Token 估算策略 (spec §11.3)：`len(text)//2.5`，避免新增 tiktoken 依赖。
"""

from __future__ import annotations

import abc
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


_ALLOWED_ROLES = ('system', 'user', 'assistant', 'tool')


def coerce_role(role: Optional[str]) -> str:
    """audit-fix-2-P1-C: 任何写入 Message.role 的入口都要走这个白名单，
    避免直接 Message(role=user_input,...) 绕过 from_dict 的校验。"""
    r = str(role or 'user')
    return r if r in _ALLOWED_ROLES else 'user'


@dataclass
class Message:
    role: str               # 'system' | 'user' | 'assistant' | 'tool'
    content: str
    ts: float = field(default_factory=lambda: time.time())

    def to_dict(self) -> Dict[str, Any]:
        return {'role': self.role, 'content': self.content, 'ts': self.ts}

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> 'Message':
        # audit-fix-P3-13: 白名单 role，避免脑变型 XSS 从 DB 走到前端
        return cls(role=coerce_role(raw.get('role')),
                   content=str(raw.get('content') or ''),
                   ts=float(raw.get('ts') or time.time()))


@dataclass
class Conversation:
    conversation_id: str
    scene: str
    agent: Optional[str] = None
    title: Optional[str] = None
    user_id: Optional[str] = None
    messages: List[Message] = field(default_factory=list)
    total_tokens: int = 0
    created_at: float = field(default_factory=lambda: time.time())
    updated_at: float = field(default_factory=lambda: time.time())

    def to_summary(self) -> Dict[str, Any]:
        return {
            'conversation_id': self.conversation_id,
            'scene': self.scene,
            'agent': self.agent,
            'title': self.title,
            'user_id': self.user_id,
            'message_count': len(self.messages),
            'total_tokens': self.total_tokens,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }

    def to_dict(self) -> Dict[str, Any]:
        d = self.to_summary()
        d['messages'] = [m.to_dict() for m in self.messages]
        return d


def estimate_tokens(text: str) -> int:
    """spec §11.3 简易 token 估算：`len(text)//2.5`，min=1。"""
    if not text:
        return 0
    return max(1, int(len(text) / 2.5))


def estimate_messages_tokens(messages: List[Message]) -> int:
    return sum(estimate_tokens(m.content) for m in messages)


class ConversationMemory(abc.ABC):
    """会话记忆抽象。所有方法对未知 conversation_id 安全（返回 None / []）。"""

    @abc.abstractmethod
    def get_or_create(self, conversation_id: str, *, scene: str,
                      user_id: Optional[str] = None,
                      agent: Optional[str] = None,
                      title: Optional[str] = None) -> Conversation: ...

    @abc.abstractmethod
    def get(self, conversation_id: str) -> Optional[Conversation]: ...

    @abc.abstractmethod
    def append(self, conversation_id: str, role: str, content: str,
               *, scene: Optional[str] = None,
               user_id: Optional[str] = None,
               agent: Optional[str] = None) -> None: ...

    @abc.abstractmethod
    def load(self, conversation_id: str, *, max_tokens: int = 4000) -> List[Message]:
        """返回截断到 max_tokens 内的历史消息（含可能的摘要 system 消息）。"""

    @abc.abstractmethod
    def list(self, *, user_id: Optional[str] = None,
             scene: Optional[str] = None, limit: int = 50) -> List[Conversation]: ...

    @abc.abstractmethod
    def delete(self, conversation_id: str) -> bool: ...

    @abc.abstractmethod
    def rename(self, conversation_id: str, title: str) -> bool: ...


def truncate_to_budget(messages: List[Message], max_tokens: int) -> List[Message]:
    """从最旧消息开始丢弃直到总 token 估算 <= max_tokens。

    保留首条 system 消息（若有），并保证至少返回最后一条消息。
    spec §11.3 提到 "达到 80% 时调廉价模型摘要"——MVP 阶段先用纯截断，
    自动摘要由 `summarize_if_needed` 在调用方按需触发。
    """
    if not messages:
        return []
    head_system: List[Message] = []
    body = messages
    if messages and messages[0].role == 'system':
        head_system = [messages[0]]
        body = messages[1:]
    head_tokens = estimate_messages_tokens(head_system)
    budget = max(0, max_tokens - head_tokens)
    # 从尾部往前累加
    kept_rev: List[Message] = []
    used = 0
    for m in reversed(body):
        t = estimate_tokens(m.content)
        if used + t > budget and kept_rev:
            break
        kept_rev.append(m)
        used += t
    # audit-fix-P2-7: 单条超预算时 — 以上循环会跳过所有消息。
    # 避免返回空，至少保留最后一条。
    if not kept_rev and body:
        kept_rev.append(body[-1])
    kept = list(reversed(kept_rev))
    return head_system + kept
