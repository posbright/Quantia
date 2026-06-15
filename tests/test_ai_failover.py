#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI provider/model 故障转移（failover）单元测试。

不依赖真实 LLM / DB：通过 mock quantia.lib.ai.run_agent 与
list_provider_profiles 注入场景。
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quantia.lib.ai import failover as fo
from quantia.lib.ai.exceptions import (
    AIError,
    ProviderError,
    RateLimitError,
    ValidationError,
)


def _profiles(default='qwen'):
    return {
        'default': default,
        'profiles': [
            {'name': 'default', 'has_key': True, 'default_model': 'm0'},
            {'name': 'deepseek', 'has_key': True, 'default_model': 'deepseek-chat'},
            {'name': 'openai', 'has_key': True, 'default_model': 'gpt-4o-mini'},
            {'name': 'qwen', 'has_key': True, 'default_model': 'qwen-plus'},
            {'name': 'kimi', 'has_key': False, 'default_model': 'moonshot-v1-8k'},
        ],
    }


class ShouldFailoverTests(unittest.TestCase):
    def test_rate_limit_failover(self):
        self.assertTrue(fo.should_failover(RateLimitError('429')))

    def test_rate_limit_overloaded_failover(self):
        self.assertTrue(fo.should_failover(RateLimitError('busy', overloaded=True)))

    def test_provider_billing_failover(self):
        self.assertTrue(fo.should_failover(ProviderError('HTTP 402', status_code=402)))

    def test_provider_auth_failover(self):
        self.assertTrue(fo.should_failover(ProviderError('HTTP 401', status_code=401)))

    def test_provider_server_failover(self):
        self.assertTrue(fo.should_failover(ProviderError('HTTP 500', status_code=500)))

    def test_validation_error_not_failover(self):
        self.assertFalse(fo.should_failover(ValidationError('bad output')))

    def test_other_ai_error_failover(self):
        self.assertTrue(fo.should_failover(AIError('未知 provider')))

    def test_raw_exception_not_failover(self):
        # provider 层已包装所有上游/网络错误为 AIError，裸异常视为真实 bug，不转移
        self.assertFalse(fo.should_failover(KeyError('boom')))
        self.assertFalse(fo.should_failover(TypeError('bad call')))


class BuildChainTests(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.pop('QUANTIA_AI_FALLBACK_CHAIN', None)

    def tearDown(self):
        if self._saved is not None:
            os.environ['QUANTIA_AI_FALLBACK_CHAIN'] = self._saved
        else:
            os.environ.pop('QUANTIA_AI_FALLBACK_CHAIN', None)

    def test_auto_chain_excludes_default_and_keyless(self):
        with mock.patch.object(fo, 'list_provider_profiles', return_value=_profiles('qwen')):
            chain = fo.build_fallback_chain(None)
        # 第 1 个是默认（空 override）
        self.assertEqual(chain[0], {})
        names = [c.get('provider') for c in chain[1:]]
        # 排除默认 qwen 与无 key 的 kimi
        self.assertIn('deepseek', names)
        self.assertIn('openai', names)
        self.assertNotIn('qwen', names)
        self.assertNotIn('kimi', names)
        # 备用项携带各自 default_model
        ds = next(c for c in chain if c.get('provider') == 'deepseek')
        self.assertEqual(ds['model'], 'deepseek-chat')

    def test_explicit_env_chain_with_model(self):
        os.environ['QUANTIA_AI_FALLBACK_CHAIN'] = 'openai:gpt-4o, deepseek'
        with mock.patch.object(fo, 'list_provider_profiles', return_value=_profiles('qwen')):
            chain = fo.build_fallback_chain(None)
        self.assertEqual(chain[1], {'provider': 'openai', 'model': 'gpt-4o'})
        self.assertEqual(chain[2], {'provider': 'deepseek', 'model': 'deepseek-chat'})

    def test_base_provider_dedup(self):
        # 当调用方已指定 provider=deepseek，备用链不应再次包含 deepseek
        with mock.patch.object(fo, 'list_provider_profiles', return_value=_profiles('qwen')):
            chain = fo.build_fallback_chain({'provider': 'deepseek'})
        names = [c.get('provider') for c in chain[1:]]
        self.assertNotIn('deepseek', names)


class RunWithFailoverTests(unittest.TestCase):
    def _run(self, side_effects, chain=None, **kw):
        calls = []

        def fake_run_agent(*, overrides=None, **rest):
            calls.append(overrides)
            eff = side_effects[len(calls) - 1]
            if isinstance(eff, Exception):
                raise eff
            return eff

        with mock.patch('quantia.lib.ai.run_agent', side_effect=fake_run_agent):
            result = fo.run_agent_with_failover(
                fallback_chain=chain or [{}, {'provider': 'deepseek'}, {'provider': 'openai'}],
                user_message='x', scene='stock_report', agent='stock_analyst',
                **kw,
            )
        return result, calls

    def test_first_success_no_failover(self):
        result, calls = self._run(['OK'])
        self.assertEqual(result, 'OK')
        self.assertEqual(len(calls), 1)
        self.assertIsNone(calls[0])  # 空 override → None

    def test_failover_on_billing_then_success(self):
        seen = []
        result, calls = self._run(
            [ProviderError('HTTP 402', status_code=402), 'OK2'],
            on_failover=lambda a, b, e: seen.append((a, b)),
        )
        self.assertEqual(result, 'OK2')
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1], {'provider': 'deepseek'})
        self.assertEqual(len(seen), 1)

    def test_validation_error_no_failover(self):
        with self.assertRaises(ValidationError):
            self._run([ValidationError('bad'), 'OK2'])

    def test_raw_exception_no_failover(self):
        # 裸 KeyError 视为真实 bug，立即抛出，不尝试其它 provider
        with self.assertRaises(KeyError):
            self._run([KeyError('boom'), 'OK2'])

    def test_all_fail_raises_last(self):
        with self.assertRaises(ProviderError) as ctx:
            self._run([
                ProviderError('HTTP 402', status_code=402),
                RateLimitError('429'),
                ProviderError('HTTP 500', status_code=500),
            ])
        self.assertEqual(ctx.exception.status_code, 500)


if __name__ == '__main__':
    unittest.main()
