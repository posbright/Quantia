#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Provider 抽象基类。"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional

__author__ = 'Quantia'
__date__ = '2026/05/11'


@dataclass
class ChatMessage:
    role: str  # system / user / assistant / tool
    content: str
    name: Optional[str] = None
    tool_call_id: Optional[str] = None
    # M6：assistant 回复中携带的 tool_calls（用于将上一轮调用回放给 LLM）
    tool_calls: Optional[List[Dict[str, Any]]] = None


@dataclass
class ToolCall:
    """M6：function-calling 响应中的单个工具调用。"""
    id: str
    name: str
    arguments: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatResult:
    content: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    finish_reason: str = ''
    raw: Dict[str, Any] = field(default_factory=dict)
    tool_calls: List['ToolCall'] = field(default_factory=list)


class Provider(ABC):
    """LLM 提供商抽象。所有实现必须支持同步 chat。"""

    name: str = 'base'

    def __init__(self, config):
        self.config = config

    @abstractmethod
    def chat(self, messages: List[ChatMessage], **kwargs) -> ChatResult:
        """同步聊天补全。"""

    def stream(self, messages: List[ChatMessage], **kwargs) -> Iterator[str]:
        """可选：流式输出（默认 fallback 到 chat 一次性返回）。"""
        result = self.chat(messages, **kwargs)
        yield result.content
