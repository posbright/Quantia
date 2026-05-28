#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""web_search 工具：搜索互联网获取实时信息。

优先级：
1. 若配置了 QUANTIA_AI_WEB_SEARCH_URL → 调用自建搜索代理（SearXNG 等）
2. 若配置了 QUANTIA_AI_BOCHA_API_KEY → 使用博查 (Bocha) AI 搜索（首选，国内专用）
3. 否则使用 Bing CN 搜索作为零配置 fallback
4. 全部失败时优雅降级，返回空结果 + warning

博查 API（推荐）：
  - 专为 AI 设计的搜索引擎，结构化 JSON + summary 摘要
  - 支持 freshness 时间过滤、语义排序
  - 国内 ICP 备案，稳定可达
  - 注册获取 Key：https://open.bochaai.com/dashboard

自建代理 endpoint 协议（极简）：
  GET <URL>?q=<query>&n=<top_n>
  返回 JSON: {"results": [{"title": ..., "url": ..., "snippet": ...}, ...]}
"""

import json
import logging
import os
import re
from html import unescape as html_unescape
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

_COMMON_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/125.0.0.0 Safari/537.36'
    ),
    'Accept': 'text/html,application/xhtml+xml',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
}

# ── 博查 (Bocha) AI 搜索 ────────────────────────────────────────────────────
_BOCHA_API_URL = 'https://api.bochaai.com/v1/web-search'


def _search_bocha(query: str, top_n: int) -> List[Dict[str, str]]:
    """博查 AI 搜索（国内首选，结构化 JSON + 语义排序 + 摘要）。"""
    api_key = os.environ.get('QUANTIA_AI_BOCHA_API_KEY', '').strip()
    if not api_key:
        raise ToolError('QUANTIA_AI_BOCHA_API_KEY 未配置')

    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }
    payload = {
        'query': query,
        'count': top_n,
        'freshness': 'oneMonth',  # 近一个月（适合"近期事件"场景）
        'summary': True,
    }
    try:
        resp = requests.post(
            _BOCHA_API_URL,
            json=payload,
            headers=headers,
            timeout=_TIMEOUT_SEC,
        )
    except requests.RequestException as exc:
        raise ToolError(f'web_search(Bocha) 网络错误: {exc}') from exc

    if resp.status_code == 401:
        raise ToolError('web_search(Bocha) API Key 无效或已过期')
    if resp.status_code >= 400:
        raise ToolError(f'web_search(Bocha) HTTP {resp.status_code}: {resp.text[:200]}')

    try:
        data = resp.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise ToolError(f'web_search(Bocha) 非 JSON 响应: {resp.text[:200]}') from exc

    # 博查响应格式: {"code":200, "data": {"_type":"SearchResponse", "webPages": {"value": [...]}}}
    inner = data.get('data') or data  # 兼容两种格式
    web_pages = inner.get('webPages') or {}
    values = web_pages.get('value') or []
    if not isinstance(values, list):
        return []

    results: List[Dict[str, str]] = []
    for item in values[:top_n]:
        if not isinstance(item, dict):
            continue
        title = str(item.get('name') or '').strip()
        url = str(item.get('url') or '').strip()
        # 优先用 summary（AI 摘要），否则用 snippet
        snippet = str(item.get('summary') or item.get('snippet') or '').strip()
        if title or snippet:
            results.append({
                'title': title[:300],
                'url': url[:500],
                'snippet': snippet[:1000],
            })

    return results


# ── Bing CN ──────────────────────────────────────────────────────────────────
_BING_URL = 'https://www.bing.com/search'


def _search_bing_cn(query: str, top_n: int) -> List[Dict[str, str]]:
    """Bing 搜索（国内外均可访问，优先返回中文结果）。"""
    try:
        resp = requests.get(
            _BING_URL,
            params={'q': query, 'count': top_n},
            headers=_COMMON_HEADERS,
            timeout=_TIMEOUT_SEC,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise ToolError(f'web_search(Bing CN) 网络错误: {exc}') from exc

    html = resp.text
    results: List[Dict[str, str]] = []

    # Bing 搜索结果块: <li class="b_algo">
    #   <h2><a href="URL">Title</a></h2>
    #   <div class="b_caption"><p>Snippet</p></div>
    blocks = re.findall(
        r'<li\s+class="b_algo"[^>]*>(.*?)</li>',
        html, re.DOTALL
    )
    for block in blocks[:top_n]:
        # 提取标题和链接
        title_match = re.search(
            r'<h2[^>]*>\s*<a[^>]+href="([^"]*)"[^>]*>(.*?)</a>',
            block, re.DOTALL
        )
        if not title_match:
            continue
        url = html_unescape(title_match.group(1))
        title = re.sub(r'<[^>]+>', '', title_match.group(2)).strip()
        title = html_unescape(title)

        # 尝试从 <cite> 提取原始 URL（比 bing.com/ck/a 跳转链接更有意义）
        cite_match = re.search(r'<cite[^>]*>(.*?)</cite>', block, re.DOTALL)
        if cite_match:
            cite_url = re.sub(r'<[^>]+>', '', cite_match.group(1)).strip()
            cite_url = html_unescape(cite_url)
            # cite 通常是 "example.com › path" 格式，转换为 URL
            if cite_url and not cite_url.startswith('http'):
                cite_url = 'https://' + cite_url.replace(' › ', '/').replace('›', '/')
            if cite_url:
                url = cite_url

        # 提取摘要 — Bing 有多种 snippet 容器
        snippet = ''
        snippet_match = re.search(
            r'<div\s+class="b_caption"[^>]*>.*?<p[^>]*>(.*?)</p>',
            block, re.DOTALL
        )
        if snippet_match:
            snippet = re.sub(r'<[^>]+>', '', snippet_match.group(1)).strip()
        else:
            # 备选: <span class="b_algoSlug">
            slug_match = re.search(
                r'<span[^>]*class="[^"]*algoSlug[^"]*"[^>]*>(.*?)</span>',
                block, re.DOTALL
            )
            if slug_match:
                snippet = re.sub(r'<[^>]+>', '', slug_match.group(1)).strip()
        snippet = html_unescape(snippet)

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
        '支持博查AI搜索（推荐）、Bing CN 或自建搜索代理。'
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
        # 安全校验在 try 外面：配置错误（如 http:// 不允许）应立即报错
        if url:
            self._validate_proxy_url(url)
        try:
            if url:
                out = self._search_via_proxy(url, query, top_n)
            else:
                out = self._search_with_fallback(query, top_n)
        except ToolError as exc:
            # 网络不可达 / 超时 / 被屏蔽时优雅降级：返回空结果 + 提示，
            # 让 Agent 继续生成报告（"近期事件"一节标注暂无数据即可），
            # 而非中断整个工具链。
            _logger.warning(f'[web_search] 搜索失败（降级为空结果）: {exc}')
            return {
                'query': query,
                'result_count': 0,
                'results': [],
                'warning': f'搜索服务暂不可用: {exc}',
            }

        # 整体截断
        encoded = json.dumps(out, ensure_ascii=False).encode('utf-8')
        if len(encoded) > _MAX_RESPONSE_BYTES:
            while len(json.dumps(out, ensure_ascii=False).encode('utf-8')) > _MAX_RESPONSE_BYTES and out:
                out.pop()
        return {'query': query, 'result_count': len(out), 'results': out}

    @staticmethod
    def _validate_proxy_url(url: str) -> None:
        """校验代理 URL 协议安全性（配置错误应立即报错，不降级）。"""
        allow_http = os.environ.get('QUANTIA_AI_WEB_SEARCH_ALLOW_HTTP', '0').lower() in ('1', 'true', 'yes')
        if allow_http:
            if not (url.startswith('https://') or url.startswith('http://')):
                raise ToolError('QUANTIA_AI_WEB_SEARCH_URL 必须是 http(s) 协议')
        else:
            if not url.startswith('https://'):
                raise ToolError('QUANTIA_AI_WEB_SEARCH_URL 必须是 https（设 QUANTIA_AI_WEB_SEARCH_ALLOW_HTTP=1 放行 http）')

    @staticmethod
    def _search_with_fallback(query: str, top_n: int) -> List[Dict[str, str]]:
        """内置搜索 fallback 链：博查 (Bocha) → Bing CN。

        优先用博查 AI 搜索（需 QUANTIA_AI_BOCHA_API_KEY）；
        未配置或失败时降级到 Bing CN（零配置即可用）。
        """
        # 第一梯队：博查 AI 搜索（国内首选，结构化 + 语义排序）
        bocha_key = os.environ.get('QUANTIA_AI_BOCHA_API_KEY', '').strip()
        if bocha_key:
            try:
                results = _search_bocha(query, top_n)
                if results:
                    return results
                _logger.info('[web_search] Bocha 返回空结果，尝试 Bing CN fallback')
            except ToolError as exc:
                _logger.info(f'[web_search] Bocha 失败 ({exc})，尝试 Bing CN fallback')

        # 第二梯队：Bing CN（零配置，国内可达）
        return _search_bing_cn(query, top_n)

    def _search_via_proxy(self, url: str, query: str, top_n: int) -> List[Dict[str, str]]:
        """通过自建搜索代理获取结果。"""

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
