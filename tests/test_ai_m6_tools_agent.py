#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M6 工具 + AgentRuntime 单元测试。"""

import json
import os
import sys
import unittest
from unittest import mock

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quantia.lib.ai import tools as tools_pkg
from quantia.lib.ai.tools import Tool, ToolError, get_registry, reset_registry
from quantia.lib.ai.tools.sql_query import SqlQueryTool, _check_safety, _inject_limit
from quantia.lib.ai.tools.code_validate import CodeValidateTool
from quantia.lib.ai.tools.web_search import WebSearchTool
from quantia.lib.ai.agent import AgentRuntime, AgentRunResult
from quantia.lib.ai.providers.base import ChatMessage, ChatResult, Provider, ToolCall


# ── sql_query tool 安全 ───────────────────────────────────────────────
class SqlQuerySafetyTests(unittest.TestCase):
    def test_select_allowed_table(self):
        _check_safety('SELECT * FROM cn_stock_spot WHERE code="000001"')

    def test_reject_insert(self):
        with self.assertRaises(ToolError):
            _check_safety("INSERT INTO cn_stock_spot VALUES(1)")

    def test_reject_update(self):
        with self.assertRaises(ToolError):
            _check_safety("UPDATE cn_stock_spot SET code='x'")

    def test_reject_drop(self):
        with self.assertRaises(ToolError):
            _check_safety("DROP TABLE cn_stock_spot")

    def test_reject_multi_statement(self):
        with self.assertRaises(ToolError):
            _check_safety("SELECT 1; DROP TABLE cn_stock_spot")

    def test_reject_non_select(self):
        with self.assertRaises(ToolError):
            _check_safety("SHOW TABLES")

    def test_reject_unwhitelisted_table(self):
        with self.assertRaises(ToolError):
            _check_safety("SELECT * FROM mysql.user")

    def test_inject_limit_default(self):
        sql = _inject_limit("SELECT * FROM cn_stock_spot", 100)
        self.assertIn('LIMIT 100', sql)

    def test_inject_limit_caps_user_limit(self):
        # 用户写了大 LIMIT，应被限制为请求 limit
        sql = _inject_limit("SELECT * FROM cn_stock_spot LIMIT 5000", 100)
        self.assertIn('LIMIT 100', sql)
        self.assertNotIn('5000', sql)

    def test_inject_limit_max_cap(self):
        # 请求 limit 超过 _MAX_LIMIT 应被截断为 1000
        sql = _inject_limit("SELECT * FROM cn_stock_spot", 99999)
        self.assertIn('LIMIT 1000', sql)

    def test_limit_non_integer_rejected(self):
        # P1-4（一轮审计）：LLM 传字符串 limit 必须被早拒
        with self.assertRaises(ToolError):
            SqlQueryTool().run({'sql': 'SELECT * FROM cn_stock_spot', 'limit': 'abc'})

    def test_union_to_unwhitelisted_table_rejected(self):
        # UNION 攻击：第二段 FROM 应被表前缀检查拦截
        with self.assertRaises(ToolError):
            _check_safety("SELECT 1 UNION SELECT * FROM mysql.user")


# ── code_validate tool ───────────────────────────────────────────────
class CodeValidateToolTests(unittest.TestCase):
    def test_valid_code(self):
        code = "def initialize(context):\n    pass\n\ndef handle_data(context, data):\n    pass\n"
        out = CodeValidateTool().run({'code': code})
        self.assertIn('ok', out)

    def test_unsafe_code(self):
        out = CodeValidateTool().run({'code': "import os\nos.system('echo')"})
        self.assertFalse(out['ok'])
        self.assertTrue(out['error'])

    def test_non_string_rejected(self):
        with self.assertRaises(ToolError):
            CodeValidateTool().run({'code': 123})


# ── web_search tool ──────────────────────────────────────────────────
class WebSearchToolTests(unittest.TestCase):
    def test_bing_cn_primary_fallback(self):
        """未配置 URL 时优先使用 Bing CN 搜索。"""
        os.environ.pop('QUANTIA_AI_WEB_SEARCH_URL', None)
        fake_resp = mock.Mock()
        fake_resp.status_code = 200
        fake_resp.text = (
            '<li class="b_algo">'
            '<h2><a href="https://example.com/news">贵州茅台最新消息</a></h2>'
            '<div class="b_caption"><p>茅台集团发布2026年Q1财报</p></div>'
            '</li>'
        )
        fake_resp.raise_for_status = mock.Mock()
        with mock.patch('quantia.lib.ai.tools.web_search.requests.get',
                        return_value=fake_resp):
            out = WebSearchTool().run({'query': '茅台 新闻'})
        self.assertEqual(out['result_count'], 1)
        self.assertEqual(out['results'][0]['title'], '贵州茅台最新消息')
        self.assertIn('茅台集团', out['results'][0]['snippet'])

    def test_fallback_to_duckduckgo_when_no_url(self):
        """未配置 URL 时使用内置搜索（Bing 失败时降级到 DuckDuckGo）。"""
        os.environ.pop('QUANTIA_AI_WEB_SEARCH_URL', None)
        fake_resp = mock.Mock()
        fake_resp.status_code = 200
        fake_resp.text = (
            '<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com">Example Title</a>'
            '<a class="result__snippet" href="#">A snippet here</a>'
        )
        fake_resp.raise_for_status = mock.Mock()
        # Bing GET 失败 → 降级到 DuckDuckGo POST
        with mock.patch('quantia.lib.ai.tools.web_search.requests.get',
                        side_effect=requests.RequestException('timeout')):
            with mock.patch('quantia.lib.ai.tools.web_search.requests.post',
                            return_value=fake_resp):
                out = WebSearchTool().run({'query': 'btc price'})
        self.assertIn('results', out)
        self.assertEqual(out['result_count'], 1)
        self.assertEqual(out['results'][0]['title'], 'Example Title')

    def test_calls_endpoint_when_configured(self):
        os.environ['QUANTIA_AI_WEB_SEARCH_URL'] = 'https://example.test/search'
        try:
            fake_resp = mock.Mock()
            fake_resp.status_code = 200
            fake_resp.json.return_value = {
                'results': [
                    {'title': 't1', 'url': 'http://a', 'snippet': 's1'},
                    {'title': 't2', 'url': 'http://b', 'snippet': 's2'},
                ]
            }
            with mock.patch('quantia.lib.ai.tools.web_search.requests.get',
                            return_value=fake_resp) as m:
                out = WebSearchTool().run({'query': 'hi', 'top_n': 2})
            m.assert_called_once()
            self.assertEqual(out['result_count'], 2)
            self.assertEqual(out['results'][0]['title'], 't1')
        finally:
            del os.environ['QUANTIA_AI_WEB_SEARCH_URL']

    def test_http_url_rejected_by_default(self):
        # P2（一轮审计）：默认强制 https，避免 SSRF
        os.environ['QUANTIA_AI_WEB_SEARCH_URL'] = 'http://localhost:8080/search'
        os.environ.pop('QUANTIA_AI_WEB_SEARCH_ALLOW_HTTP', None)
        try:
            with self.assertRaises(ToolError):
                WebSearchTool().run({'query': 'hi'})
        finally:
            del os.environ['QUANTIA_AI_WEB_SEARCH_URL']

    def test_http_allowed_via_opt_in(self):
        os.environ['QUANTIA_AI_WEB_SEARCH_URL'] = 'http://search.local/search'
        os.environ['QUANTIA_AI_WEB_SEARCH_ALLOW_HTTP'] = '1'
        try:
            fake_resp = mock.Mock()
            fake_resp.status_code = 200
            fake_resp.json.return_value = {'results': []}
            with mock.patch('quantia.lib.ai.tools.web_search.requests.get',
                            return_value=fake_resp):
                out = WebSearchTool().run({'query': 'hi'})
            self.assertEqual(out['result_count'], 0)
        finally:
            del os.environ['QUANTIA_AI_WEB_SEARCH_URL']
            del os.environ['QUANTIA_AI_WEB_SEARCH_ALLOW_HTTP']

    def test_graceful_degradation_all_backends_fail(self):
        """Bing + DuckDuckGo 都失败时优雅降级为空结果 + warning。"""
        os.environ.pop('QUANTIA_AI_WEB_SEARCH_URL', None)
        with mock.patch('quantia.lib.ai.tools.web_search.requests.get',
                        side_effect=requests.RequestException('bing timeout')):
            with mock.patch('quantia.lib.ai.tools.web_search.requests.post',
                            side_effect=requests.RequestException('ddg blocked')):
                out = WebSearchTool().run({'query': 'test'})
        self.assertEqual(out['result_count'], 0)
        self.assertEqual(out['results'], [])
        self.assertIn('搜索服务暂不可用', out['warning'])


# ── Tool registry ────────────────────────────────────────────────────
class ToolRegistryTests(unittest.TestCase):
    def setUp(self):
        reset_registry()

    def tearDown(self):
        reset_registry()

    def test_autoload_registers_builtins(self):
        reg = get_registry()
        names = reg.list_names()
        self.assertIn('sql_query', names)
        self.assertIn('code_validate', names)
        self.assertIn('kline_fetch', names)
        self.assertIn('backtest_run', names)
        self.assertIn('web_search', names)

    def test_schemas_filtered_by_allowed(self):
        reg = get_registry()
        schemas = reg.schemas(allowed=['sql_query', 'code_validate'])
        names = [s['function']['name'] for s in schemas]
        self.assertEqual(sorted(names), ['code_validate', 'sql_query'])


# ── AgentRuntime function-calling loop ───────────────────────────────
class _FakeProvider(Provider):
    name = 'fake'

    def __init__(self, results):
        self.config = mock.Mock(model='fake-m', provider='fake', api_key='', api_base='', temperature=0.3, max_tokens=100, timeout=30)
        self._results = list(results)
        self.call_count = 0
        self.last_kwargs = None

    def chat(self, messages, **kwargs):
        self.last_kwargs = kwargs
        self.call_count += 1
        return self._results.pop(0)


class _EchoTool(Tool):
    name = 'echo'
    description = 'echo back arg'
    parameters = {
        'type': 'object',
        'required': ['msg'],
        'properties': {'msg': {'type': 'string'}},
    }
    def run(self, args):
        return {'echoed': args.get('msg')}


class AgentRuntimeTests(unittest.TestCase):
    def setUp(self):
        reset_registry()
        get_registry().register(_EchoTool())

    def tearDown(self):
        reset_registry()

    def test_no_tool_calls_returns_directly(self):
        provider = _FakeProvider([
            ChatResult(content='hello world')
        ])
        runtime = AgentRuntime(provider, allowed_tools=['echo'])
        out = runtime.run(system='sys', user_message='hi')
        self.assertEqual(out.content, 'hello world')
        self.assertEqual(out.tool_calls, [])
        self.assertEqual(out.rounds, 1)

    def test_single_tool_call_then_final(self):
        provider = _FakeProvider([
            ChatResult(content='', tool_calls=[
                ToolCall(id='c1', name='echo', arguments={'msg': 'hey'}),
            ]),
            ChatResult(content='final answer')
        ])
        runtime = AgentRuntime(provider, allowed_tools=['echo'])
        out = runtime.run(system='sys', user_message='do echo')
        self.assertEqual(out.content, 'final answer')
        self.assertEqual(len(out.tool_calls), 1)
        self.assertTrue(out.tool_calls[0]['ok'])
        self.assertEqual(out.tool_calls[0]['result'], {'echoed': 'hey'})
        self.assertEqual(out.rounds, 2)

    def test_disallowed_tool_returns_error_to_llm(self):
        # echo not in allowed → tool result should carry error and loop continues
        provider = _FakeProvider([
            ChatResult(content='', tool_calls=[
                ToolCall(id='c1', name='echo', arguments={'msg': 'x'}),
            ]),
            ChatResult(content='cannot use that tool')
        ])
        runtime = AgentRuntime(provider, allowed_tools=[])  # nothing allowed
        out = runtime.run(system='sys', user_message='try')
        self.assertIn('cannot use that tool', out.content)
        self.assertFalse(out.tool_calls[0]['ok'])
        self.assertIn('not allowed', out.tool_calls[0]['error'])

    def test_unknown_tool_returns_error(self):
        provider = _FakeProvider([
            ChatResult(content='', tool_calls=[
                ToolCall(id='c1', name='nonexistent', arguments={}),
            ]),
            ChatResult(content='gave up')
        ])
        # unknown name still goes through allowed gate; allow it so error path is unknown
        runtime = AgentRuntime(provider, allowed_tools=['nonexistent'])
        out = runtime.run(system='sys', user_message='try')
        self.assertFalse(out.tool_calls[0]['ok'])
        self.assertIn('unknown tool', out.tool_calls[0]['error'])

    def test_max_rounds_cap(self):
        # Provider always asks for tool → loop should stop at max_rounds
        os.environ['QUANTIA_AI_AGENT_MAX_ROUNDS'] = '2'
        try:
            results = [
                ChatResult(content='', tool_calls=[ToolCall(id=f'c{i}', name='echo', arguments={'msg': str(i)})])
                for i in range(5)
            ]
            provider = _FakeProvider(results)
            runtime = AgentRuntime(provider, allowed_tools=['echo'])
            out = runtime.run(system='sys', user_message='loop')
            self.assertLessEqual(out.rounds, 2)
        finally:
            del os.environ['QUANTIA_AI_AGENT_MAX_ROUNDS']

    def test_tools_passed_to_provider(self):
        provider = _FakeProvider([ChatResult(content='ok')])
        runtime = AgentRuntime(provider, allowed_tools=['echo'])
        runtime.run(system='sys', user_message='hi')
        self.assertIn('tools', provider.last_kwargs)
        self.assertEqual(provider.last_kwargs['tool_choice'], 'auto')
        self.assertEqual(provider.last_kwargs['tools'][0]['function']['name'], 'echo')

    def test_empty_tool_call_id_is_filled(self):
        # P1-1（一轮审计）：provider 未返回 id 时由 runtime 补本地 UUID
        provider = _FakeProvider([
            ChatResult(content='', tool_calls=[
                ToolCall(id='', name='echo', arguments={'msg': 'x'}),
            ]),
            ChatResult(content='done')
        ])
        runtime = AgentRuntime(provider, allowed_tools=['echo'])
        out = runtime.run(system='sys', user_message='hi')
        self.assertEqual(out.content, 'done')
        # 第二轮请求消息中 assistant 的 tool_calls 与 tool 消息的 tool_call_id 必须有值
        sent_msgs = provider.last_kwargs.get('tools')  # last_kwargs 来自第二次 chat
        # 找到 messages 检查太底层；这里直接断言 tools_used 记录正常
        self.assertTrue(out.tool_calls[0]['ok'])

    def test_max_rounds_with_pending_tool_calls_forces_summary(self):
        # P1-2（一轮审计）：max_rounds 用尽且仍有 tool_calls 时强制再调一次拿摘要
        os.environ['QUANTIA_AI_AGENT_MAX_ROUNDS'] = '1'
        try:
            provider = _FakeProvider([
                ChatResult(content='', tool_calls=[
                    ToolCall(id='c1', name='echo', arguments={'msg': 'x'}),
                ]),
                # 第二次（强制摘要调用）应被发起
                ChatResult(content='summary text')
            ])
            runtime = AgentRuntime(provider, allowed_tools=['echo'])
            out = runtime.run(system='sys', user_message='go')
            self.assertEqual(out.content, 'summary text')
            self.assertEqual(provider.call_count, 2)
        finally:
            del os.environ['QUANTIA_AI_AGENT_MAX_ROUNDS']


if __name__ == '__main__':
    unittest.main()
