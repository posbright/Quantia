#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M6 工具基类 + 注册表。

每个 Tool 子类必须提供：
    name: 工具名（与 LLM function-calling 的 function.name 一致）
    description: 简短描述（LLM 用来决定何时调用）
    parameters: JSON-Schema dict，描述 args
    run(args) -> dict: 同步执行，返回可 JSON 序列化的结果

约束：
- run 必须自带超时/输出截断保护（见各工具实现）。
- 抛出 ToolError 表示参数非法或执行被拒；其他异常视为内部错误。
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Iterable, List, Optional

__author__ = 'Quantia'
__date__ = '2026/05/11'


class ToolError(Exception):
    """工具调用被拒（参数非法 / 安全策略 / 超时等）。"""


class Tool(ABC):
    name: str = 'base'
    description: str = ''
    parameters: Dict[str, Any] = {'type': 'object', 'properties': {}}

    @abstractmethod
    def run(self, args: Dict[str, Any]) -> Dict[str, Any]:
        ...

    def schema(self) -> Dict[str, Any]:
        """返回 OpenAI function-calling 兼容 schema。"""
        return {
            'type': 'function',
            'function': {
                'name': self.name,
                'description': self.description,
                'parameters': self.parameters,
            },
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if not tool.name:
            raise ValueError('tool.name 不能为空')
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def list_names(self) -> List[str]:
        return sorted(self._tools.keys())

    def schemas(self, allowed: Optional[Iterable[str]] = None) -> List[Dict[str, Any]]:
        names = set(allowed) if allowed is not None else None
        out = []
        for name in self.list_names():
            if names is not None and name not in names:
                continue
            out.append(self._tools[name].schema())
        return out


_default_registry: Optional[ToolRegistry] = None


def get_registry() -> ToolRegistry:
    global _default_registry
    if _default_registry is None:
        _default_registry = ToolRegistry()
        _autoload(_default_registry)
    return _default_registry


def _autoload(reg: ToolRegistry) -> None:
    """按需注册内置工具（导入失败的工具被跳过并记 warning）。"""
    pairs = [
        ('quantia.lib.ai.tools.sql_query', 'SqlQueryTool'),
        ('quantia.lib.ai.tools.kline_fetch', 'KlineFetchTool'),
        ('quantia.lib.ai.tools.code_validate', 'CodeValidateTool'),
        ('quantia.lib.ai.tools.backtest_run', 'BacktestRunTool'),
        ('quantia.lib.ai.tools.web_search', 'WebSearchTool'),
        ('quantia.lib.ai.tools.kb_search', 'KbSearchTool'),
    ]
    for mod_path, cls_name in pairs:
        try:
            mod = __import__(mod_path, fromlist=[cls_name])
            cls = getattr(mod, cls_name)
            reg.register(cls())
        except Exception as exc:
            logging.warning(f'[ai.tools] 加载 {cls_name} 失败: {exc}')


def reset_registry() -> None:
    """测试用：清空缓存的注册表，下次 get_registry() 会重新加载。"""
    global _default_registry
    _default_registry = None
