#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""web_search 工具：通过用户配置的搜索 endpoint 拉取结果。

设计：零新增依赖（仅 requests），由 QUANTIA_AI_WEB_SEARCH_URL 控制是否启用。
未配置 URL 时调用直接拒绝（避免 LLM 误以为可用）。

约定的搜索 endpoint 协议（极简）：
  GET <URL>?q=<query>&n=<top_n>
  返回 JSON: {"results": [{"title": ..., "url": ..., "snippet": ...}, ...]}

兼容 SearXNG / brave search wrapper / 自建代理等。
"""

import json
import os
from typing import Any, Dict, List

import requests

from quantia.lib.ai.tools import Tool, ToolError

__author__ = 'Quantia'
__date__ = '2026/05/11'

_TIMEOUT_SEC = 10
_MAX_RESULTS = 10
_MAX_RESPONSE_BYTES = 16 * 1024
_MAX_QUERY_LEN = 256


class WebSearchTool(Tool):
    name = 'web_search'
    description = (
        '通过用户配置的 web search 代理拉取搜索结果（标题/URL/摘要）。'
        '需运维设置 QUANTIA_AI_WEB_SEARCH_URL；未设置时此工具不可用。'
    )
    parameters = {
        'type': 'object',
        'required': ['query'],
        'properties': {
            'query': {
                'type': 'string',
                'description': '搜索关键词（≤256 字符）',
            },
            'top_n': {
                'type': 'integer',
                'description': f'返回结果数（默认 5，最大 {_MAX_RESULTS}）',
                'minimum': 1,
                'maximum': _MAX_RESULTS,
            },
        },
    }

    def run(self, args: Dict[str, Any]) -> Dict[str, Any]:
        url = (os.environ.get('QUANTIA_AI_WEB_SEARCH_URL') or '').strip()
        if not url:
            raise ToolError('未配置 QUANTIA_AI_WEB_SEARCH_URL，web_search 不可用')
        # P2（一轮审计）：SSRF 防护 - 强制 https 协议，避免 file:// 或
        # http:// 指向内网服务。调试下可以设 QUANTIA_AI_WEB_SEARCH_ALLOW_HTTP=1 放行。
        allow_http = os.environ.get('QUANTIA_AI_WEB_SEARCH_ALLOW_HTTP', '0').lower() in ('1', 'true', 'yes')
        if allow_http:
            if not (url.startswith('https://') or url.startswith('http://')):
                raise ToolError('QUANTIA_AI_WEB_SEARCH_URL 必须是 http(s) 协议')
        else:
            if not url.startswith('https://'):
                raise ToolError('QUANTIA_AI_WEB_SEARCH_URL 必须是 https（设 QUANTIA_AI_WEB_SEARCH_ALLOW_HTTP=1 放行 http）')
        query = (args.get('query') or '').strip()
        if not query:
            raise ToolError('query 不能为空')
        if len(query) > _MAX_QUERY_LEN:
            raise ToolError(f'query 超过 {_MAX_QUERY_LEN} 字符上限')
        try:
            top_n = max(1, min(_MAX_RESULTS, int(args.get('top_n') or 5)))
        except (TypeError, ValueError):
            raise ToolError('top_n 必须是整数')

        api_key = os.environ.get('QUANTIA_AI_WEB_SEARCH_KEY') or ''
        headers = {'Accept': 'application/json'}
        if api_key:
            headers['Authorization'] = f'Bearer {api_key}'
        try:
            resp = requests.get(
                url,
                params={'q': query, 'n': top_n},
                headers=headers,
                timeout=_TIMEOUT_SEC,
            )
        except requests.RequestException as exc:
            raise ToolError(f'web_search 网络错误: {exc}') from exc
        if resp.status_code >= 400:
            raise ToolError(f'web_search HTTP {resp.status_code}: {resp.text[:200]}')
        try:
            data = resp.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise ToolError(f'web_search 非 JSON 响应: {resp.text[:200]}') from exc
        results = data.get('results') if isinstance(data, dict) else data
        if not isinstance(results, list):
            raise ToolError('web_search 响应缺少 results 数组')

        out: List[Dict[str, Any]] = []
        for r in results[:top_n]:
            if not isinstance(r, dict):
                continue
            out.append({
                'title': str(r.get('title') or '')[:300],
                'url': str(r.get('url') or '')[:500],
                'snippet': str(r.get('snippet') or '')[:1000],
            })
        # 整体截断
        encoded = json.dumps(out, ensure_ascii=False).encode('utf-8')
        if len(encoded) > _MAX_RESPONSE_BYTES:
            while len(json.dumps(out, ensure_ascii=False).encode('utf-8')) > _MAX_RESPONSE_BYTES and out:
                out.pop()
        return {'query': query, 'result_count': len(out), 'results': out}
