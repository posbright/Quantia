#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kb_search 工具（spec §11.2 / §M9）。

让 LLM 在生成策略前能拉到相关 template / doc / strategy / failure 做 in-context
few-shot，避免把全部模板塞进 system prompt。

输入：query (str), top_k (int, 默认 5), source_types (list[str], 可选)
返回：{ "results": [ {source_type, source_id, title, snippet, score, updated_at}, ... ] }
"""

from typing import Any, Dict

from quantia.lib.ai.tools import Tool, ToolError

__author__ = 'Quantia'
__date__ = '2026/05/12'

_ALLOWED_TYPES = ('template', 'doc', 'strategy', 'backtest_failure')
_DEFAULT_TOP_K = 5
_MAX_TOP_K = 10
_MAX_QUERY_CHARS = 256


class KbSearchTool(Tool):
    name = 'kb_search'
    description = (
        '从内部知识库（策略模板 / 文档 / 历史策略 / 回测失败用例）检索与 query '
        '相关的片段，返回 title + snippet。生成新策略前应先调用以拉取相似模板。'
    )
    parameters = {
        'type': 'object',
        'required': ['query'],
        'properties': {
            'query': {
                'type': 'string',
                'description': '检索关键词（中文/英文，≤256 字符）',
            },
            'top_k': {
                'type': 'integer',
                'description': f'返回条数（默认 {_DEFAULT_TOP_K}，最大 {_MAX_TOP_K}）',
                'minimum': 1,
                'maximum': _MAX_TOP_K,
            },
            'source_types': {
                'type': 'array',
                'items': {
                    'type': 'string',
                    'enum': list(_ALLOWED_TYPES),
                },
                'description': '可选：限定来源类型',
            },
        },
    }

    def run(self, args: Dict[str, Any]) -> Dict[str, Any]:
        query = (args.get('query') or '').strip()
        if not query:
            raise ToolError('query 不能为空')
        if len(query) > _MAX_QUERY_CHARS:
            raise ToolError(f'query 超过 {_MAX_QUERY_CHARS} 字符上限')
        try:
            top_k = max(1, min(_MAX_TOP_K, int(args.get('top_k') or _DEFAULT_TOP_K)))
        except (TypeError, ValueError):
            raise ToolError('top_k 必须是整数')

        source_types = args.get('source_types') or None
        if source_types is not None:
            if not isinstance(source_types, list):
                raise ToolError('source_types 必须是数组')
            bad = [t for t in source_types if t not in _ALLOWED_TYPES]
            if bad:
                raise ToolError(
                    f'source_types 含非法值: {bad}，可选: {list(_ALLOWED_TYPES)}')

        # 延迟导入：MySQL 不可用时仍允许 registry 加载这个 tool
        from quantia.lib.ai.retrieval import KbStore
        try:
            store = KbStore()
            docs = store.search(query, top_k=top_k, source_types=source_types)
        except Exception as exc:
            raise ToolError(f'kb_search 检索失败: {exc}') from exc
        return {'results': [d.to_dict() for d in docs]}
