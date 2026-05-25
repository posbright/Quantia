#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""web_search 工具：搜索互联网获取实时信息。

优先级：
1. 若配置了 QUANTIA_AI_WEB_SEARCH_URL → 调用自建搜索代理（SearXNG 等）
2. 否则使用内置 DuckDuckGo HTML 搜索作为 fallback（零配置可用）

约定的搜索 endpoint 协议（极简）：
  GET <URL>?q=<query>&n=<top_n>
  返回 JSON: {"results": [{"title": ..., "url": ..., "snippet": ...}, ...]}

兼容 SearXNG / brave search wrapper / 自建代理等。
"""

import json
import logging
import os
import re
from typing import Any, Dict, List

import requests

from quantia.lib.ai.tools import Tool, ToolError

__author__ = 'Quantia'
__date__ = '2026/05/25'

_logger = logging.getLogger(__name__)

_TIMEOUT_SEC = 10
_MAX_RESULTS = 10
_MAX_RESPONSE_BYTES = 16 * 1024
_MAX_QUERY_LEN = 256

# DuckDuckGo HTML endpoint（lite 版，轻量易解析）
_DDG_URL = 'https://html.duckduckgo.com/html/'
_DDG_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/125.0.0.0 Safari/537.36'
    ),
    'Accept': 'text/html,application/xhtml+xml',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
}


def _search_duckduckgo(query: str, top_n: int) -> List[Dict[str, str]]:
    """内置 DuckDuckGo HTML 搜索，返回 [{title, url, snippet}, ...]。"""
    try:
        resp = requests.post(
            _DDG_URL,
            data={'q': query, 'b': '', 'kl': 'cn-zh'},
            headers=_DDG_HEADERS,
            timeout=_TIMEOUT_SEC,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise ToolError(f'web_search(DuckDuckGo) 网络错误: {exc}') from exc

    html = resp.text
    results: List[Dict[str, str]] = []

    # 解析 DuckDuckGo HTML lite 结果
    # 每个结果块: <a rel="nofollow" class="result__a" href="...">title</a>
    #             <a class="result__snippet" ...>snippet</a>
    result_blocks = re.findall(
        r'<a[^>]+class="result__a"[^>]+href="([^"]*)"[^>]*>(.*?)</a>.*?'
        r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
        html, re.DOTALL
    )
    for href, title_html, snippet_html in result_blocks[:top_n]:
        # 提取真实 URL（DuckDuckGo 会包装为 //duckduckgo.com/l/?uddg=<encoded>）
        url = href
        uddg_match = re.search(r'uddg=([^&]+)', href)
        if uddg_match:
            from urllib.parse import unquote
            url = unquote(uddg_match.group(1))

        # 清理 HTML 标签
        title = re.sub(r'<[^>]+>', '', title_html).strip()
        snippet = re.sub(r'<[^>]+>', '', snippet_html).strip()

        if title or snippet:
            results.append({
                'title': title[:300],
                'url': url[:500],
                'snippet': snippet[:1000],
            })

    return results


class WebSearchTool(Tool):
    name = 'web_search'
    description = (
        '搜索互联网获取实时新闻、公告、行业动态等信息。'
        '支持自建搜索代理或内置 DuckDuckGo 搜索。'
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
        query = (args.get('query') or '').strip()
        if not query:
            raise ToolError('query 不能为空')
        if len(query) > _MAX_QUERY_LEN:
            raise ToolError(f'query 超过 {_MAX_QUERY_LEN} 字符上限')
        try:
            top_n = max(1, min(_MAX_RESULTS, int(args.get('top_n') or 5)))
        except (TypeError, ValueError):
            raise ToolError('top_n 必须是整数')

        url = (os.environ.get('QUANTIA_AI_WEB_SEARCH_URL') or '').strip()
        if url:
            # 使用自建搜索代理
            out = self._search_via_proxy(url, query, top_n)
        else:
            # 内置 DuckDuckGo 搜索 fallback
            out = _search_duckduckgo(query, top_n)

        # 整体截断
        encoded = json.dumps(out, ensure_ascii=False).encode('utf-8')
        if len(encoded) > _MAX_RESPONSE_BYTES:
            while len(json.dumps(out, ensure_ascii=False).encode('utf-8')) > _MAX_RESPONSE_BYTES and out:
                out.pop()
        return {'query': query, 'result_count': len(out), 'results': out}

    def _search_via_proxy(self, url: str, query: str, top_n: int) -> List[Dict[str, str]]:
        """通过自建搜索代理获取结果。"""
        allow_http = os.environ.get('QUANTIA_AI_WEB_SEARCH_ALLOW_HTTP', '0').lower() in ('1', 'true', 'yes')
        if allow_http:
            if not (url.startswith('https://') or url.startswith('http://')):
                raise ToolError('QUANTIA_AI_WEB_SEARCH_URL 必须是 http(s) 协议')
        else:
            if not url.startswith('https://'):
                raise ToolError('QUANTIA_AI_WEB_SEARCH_URL 必须是 https（设 QUANTIA_AI_WEB_SEARCH_ALLOW_HTTP=1 放行 http）')

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

        out: List[Dict[str, str]] = []
        for r in results[:top_n]:
            if not isinstance(r, dict):
                continue
            out.append({
                'title': str(r.get('title') or '')[:300],
                'url': str(r.get('url') or '')[:500],
                'snippet': str(r.get('snippet') or '')[:1000],
            })
        return out
