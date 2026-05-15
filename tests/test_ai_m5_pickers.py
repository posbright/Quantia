#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M5 测试：/ai/config + /ai/agents 路由 + provider/agent 元数据。"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tornado.testing import AsyncHTTPTestCase
from tornado.web import Application

import quantia.web.aiAssistantHandler as ai_h
from quantia.lib.ai import config as ai_config
from quantia.lib.ai import prompt_loader


def _make_app() -> Application:
    return Application([
        (r"/quantia/api/ai/config", ai_h.GetAiConfigHandler),
        (r"/quantia/api/ai/agents", ai_h.ListAiAgentsHandler),
    ])


class ProviderProfileTests(unittest.TestCase):
    def setUp(self):
        # 备份并清理所有 QUANTIA_AI_* env，避免测试间互相污染
        self._saved = {k: v for k, v in os.environ.items()
                       if k.startswith('QUANTIA_AI_')}
        for k in list(self._saved.keys()):
            del os.environ[k]

    def tearDown(self):
        for k in list(os.environ.keys()):
            if k.startswith('QUANTIA_AI_') and k not in self._saved:
                del os.environ[k]
        for k, v in self._saved.items():
            os.environ[k] = v

    def test_default_profile_always_present(self):
        data = ai_config.list_provider_profiles()
        names = {p['name'] for p in data['profiles']}
        self.assertIn('default', names)
        self.assertIn('default', data)

    def test_namespaced_provider_discovered(self):
        os.environ['QUANTIA_AI_PROVIDER_DEEPSEEK_API_BASE'] = 'https://api.deepseek.com/v1'
        os.environ['QUANTIA_AI_PROVIDER_DEEPSEEK_API_KEY'] = 'sk-test'
        os.environ['QUANTIA_AI_PROVIDER_DEEPSEEK_MODELS'] = 'deepseek-chat,deepseek-coder'
        os.environ['QUANTIA_AI_PROVIDER_DEEPSEEK_DEFAULT_MODEL'] = 'deepseek-chat'
        os.environ['QUANTIA_AI_DEFAULT_PROVIDER'] = 'deepseek'
        data = ai_config.list_provider_profiles()
        ds = next(p for p in data['profiles'] if p['name'] == 'deepseek')
        self.assertEqual(ds['api_base'], 'https://api.deepseek.com/v1')
        self.assertTrue(ds['has_key'])
        self.assertIn('deepseek-chat', ds['models'])
        self.assertIn('deepseek-coder', ds['models'])
        self.assertEqual(ds['default_model'], 'deepseek-chat')
        self.assertEqual(data['default'], 'deepseek')

    def test_api_key_never_returned(self):
        os.environ['QUANTIA_AI_PROVIDER_QWEN_API_KEY'] = 'sk-secret'
        data = ai_config.list_provider_profiles()
        for p in data['profiles']:
            self.assertNotIn('api_key', p)

    def test_provider_name_with_underscore(self):
        # P0-1（六轮）：provider 名包含下划线（如 azure_openai）必须正确解析
        os.environ['QUANTIA_AI_PROVIDER_AZURE_OPENAI_API_BASE'] = 'https://az.example/v1'
        os.environ['QUANTIA_AI_PROVIDER_AZURE_OPENAI_API_KEY'] = 'sk-az'
        os.environ['QUANTIA_AI_PROVIDER_AZURE_OPENAI_DEFAULT_MODEL'] = 'gpt-4o'
        data = ai_config.list_provider_profiles()
        names = {p['name'] for p in data['profiles']}
        self.assertIn('azure_openai', names)
        prof = next(p for p in data['profiles'] if p['name'] == 'azure_openai')
        self.assertEqual(prof['api_base'], 'https://az.example/v1')
        self.assertTrue(prof['has_key'])
        self.assertEqual(prof['default_model'], 'gpt-4o')

    def test_unknown_attribute_ignored(self):
        # 未识别的 suffix（如 _FOO）不应导致解析错位
        os.environ['QUANTIA_AI_PROVIDER_DEEPSEEK_FOO'] = 'bar'
        os.environ['QUANTIA_AI_PROVIDER_DEEPSEEK_API_BASE'] = 'https://ds.example/v1'
        data = ai_config.list_provider_profiles()
        prof = next((p for p in data['profiles'] if p['name'] == 'deepseek'), None)
        self.assertIsNotNone(prof)
        self.assertEqual(prof['api_base'], 'https://ds.example/v1')

    def test_profiles_sorted_default_first(self):
        # P1-4（六轮）：返回顺序稳定 - default 置顶，其余字母序
        os.environ['QUANTIA_AI_PROVIDER_ZULU_API_BASE'] = 'z'
        os.environ['QUANTIA_AI_PROVIDER_ALPHA_API_BASE'] = 'a'
        data = ai_config.list_provider_profiles()
        names = [p['name'] for p in data['profiles']]
        self.assertEqual(names[0], 'default')
        rest = names[1:]
        self.assertEqual(rest, sorted(rest))

    def test_provider_override_loads_namespaced_credentials(self):
        # P0-10b（七轮）：overrides.provider 切换到 namespaced provider 时
        # 应该自动从该 namespace 加载 api_key/api_base，避免用 default 的密钥
        # 调用错误的 endpoint。
        os.environ['QUANTIA_AI_API_BASE'] = 'https://default.example/v1'
        os.environ['QUANTIA_AI_API_KEY'] = 'sk-default'
        os.environ['QUANTIA_AI_PROVIDER_QWEN_API_BASE'] = 'https://qwen.example/v1'
        os.environ['QUANTIA_AI_PROVIDER_QWEN_API_KEY'] = 'sk-qwen'
        os.environ['QUANTIA_AI_PROVIDER_QWEN_DEFAULT_MODEL'] = 'qwen-max'
        cfg = ai_config.load_config({'provider': 'qwen'})
        self.assertEqual(cfg.api_base, 'https://qwen.example/v1')
        self.assertEqual(cfg.api_key, 'sk-qwen')
        self.assertEqual(cfg.model, 'qwen-max')

    def test_provider_override_explicit_api_base_wins(self):
        # 显式 overrides.api_base 优先于 namespaced env
        os.environ['QUANTIA_AI_PROVIDER_QWEN_API_BASE'] = 'https://qwen.example/v1'
        os.environ['QUANTIA_AI_PROVIDER_QWEN_API_KEY'] = 'sk-qwen'
        cfg = ai_config.load_config({
            'provider': 'qwen',
            'api_base': 'https://custom.example/v1',
        })
        self.assertEqual(cfg.api_base, 'https://custom.example/v1')
        self.assertEqual(cfg.api_key, 'sk-qwen')  # 未指定 -> 仍从 namespace 拉取


class PromptLoaderAgentsTests(unittest.TestCase):
    def test_list_agents_contains_builtins(self):
        agents = prompt_loader.list_agents()
        names = {a['name'] for a in agents}
        self.assertIn('strategy_coder', names)
        self.assertIn('strategy_repairer', names)
        for a in agents:
            self.assertTrue(a['is_builtin'])
            self.assertIn('system_prompt', a)


class GetAiConfigHandlerTests(AsyncHTTPTestCase):
    def get_app(self):
        return _make_app()

    def test_get_config_shape(self):
        resp = self.fetch('/quantia/api/ai/config')
        self.assertEqual(resp.code, 200)
        body = json.loads(resp.body)
        self.assertEqual(body['code'], 0, body)
        data = body['data']
        self.assertIn('profiles', data)
        self.assertIn('agents', data)
        self.assertIn('default', data)
        # api_key / system_prompt 不外露
        for p in data['profiles']:
            self.assertNotIn('api_key', p)
        for a in data['agents']:
            self.assertNotIn('system_prompt', a)


class ListAiAgentsHandlerTests(AsyncHTTPTestCase):
    def get_app(self):
        return _make_app()

    def test_list_default_no_prompt(self):
        resp = self.fetch('/quantia/api/ai/agents')
        body = json.loads(resp.body)
        self.assertEqual(body['code'], 0)
        for a in body['data']['agents']:
            self.assertNotIn('system_prompt', a)

    def test_list_include_prompt(self):
        resp = self.fetch('/quantia/api/ai/agents?include_prompt=1')
        body = json.loads(resp.body)
        self.assertEqual(body['code'], 0)
        agents = body['data']['agents']
        self.assertTrue(all('system_prompt' in a for a in agents))


if __name__ == '__main__':
    unittest.main()
