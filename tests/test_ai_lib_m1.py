#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M1 AI 基础层单元测试：config / provider / run_chat（mock requests）。"""

import sys
import os
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quantia.lib.ai import (
    AIConfig, AIError, ProviderError, RateLimitError,
    ChatMessage, get_provider, run_chat, load_config,
)
from quantia.lib.ai.providers.openai_compat import OpenAICompatProvider


class TestConfig(unittest.TestCase):
    def test_load_config_defaults(self):
        with patch('quantia.lib.ai.config._load_from_db', return_value={}), \
             patch('quantia.lib.ai.config._load_from_env', return_value={}):
            cfg = load_config()
        self.assertEqual(cfg.provider, 'openai_compat')
        self.assertEqual(cfg.model, 'gpt-4o-mini')
        self.assertEqual(cfg.temperature, 0.3)

    def test_overrides_take_precedence(self):
        with patch('quantia.lib.ai.config._load_from_db',
                   return_value={'model': 'db-model', 'api_key': 'db-key'}), \
             patch('quantia.lib.ai.config._load_from_env',
                   return_value={'model': 'env-model'}):
            cfg = load_config({'model': 'override-model'})
        self.assertEqual(cfg.model, 'override-model')
        self.assertEqual(cfg.api_key, 'db-key')

    def test_db_over_env(self):
        with patch('quantia.lib.ai.config._load_from_db', return_value={'model': 'db'}), \
             patch('quantia.lib.ai.config._load_from_env', return_value={'model': 'env'}):
            cfg = load_config()
        self.assertEqual(cfg.model, 'db')


class TestProviderRegistry(unittest.TestCase):
    def test_get_provider_default(self):
        cfg = AIConfig(provider='openai_compat', api_key='x')
        self.assertIsInstance(get_provider(cfg), OpenAICompatProvider)

    def test_unknown_provider_raises(self):
        cfg = AIConfig(provider='nonexistent', api_key='x')
        with self.assertRaises(AIError):
            get_provider(cfg)


def _mock_response(status=200, json_body=None, text='ok'):
    m = MagicMock()
    m.status_code = status
    m.text = text
    m.json.return_value = json_body or {}
    return m


class TestOpenAICompatProvider(unittest.TestCase):
    def setUp(self):
        self.cfg = AIConfig(api_key='sk-test', model='test-model')
        self.provider = OpenAICompatProvider(self.cfg)

    def test_chat_success(self):
        body = {
            'choices': [{'message': {'content': 'hello world'}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 5, 'completion_tokens': 7, 'total_tokens': 12},
        }
        with patch('quantia.lib.ai.providers.openai_compat.requests.post',
                   return_value=_mock_response(200, body)) as mock_post:
            result = self.provider.chat([ChatMessage(role='user', content='hi')])
        self.assertEqual(result.content, 'hello world')
        self.assertEqual(result.total_tokens, 12)
        self.assertEqual(result.finish_reason, 'stop')
        # Verify URL composed correctly
        call_args = mock_post.call_args
        self.assertTrue(call_args[0][0].endswith('/chat/completions'))
        sent_payload = call_args[1]['json']
        self.assertEqual(sent_payload['model'], 'test-model')
        self.assertEqual(sent_payload['messages'][0]['role'], 'user')

    def test_rate_limit(self):
        with patch('quantia.lib.ai.providers.openai_compat.requests.post',
                   return_value=_mock_response(429, {}, 'rate limited')):
            with self.assertRaises(RateLimitError):
                self.provider.chat([ChatMessage(role='user', content='hi')])

    def test_http_error(self):
        with patch('quantia.lib.ai.providers.openai_compat.requests.post',
                   return_value=_mock_response(500, {}, 'server error')):
            with self.assertRaises(ProviderError) as ctx:
                self.provider.chat([ChatMessage(role='user', content='hi')])
        self.assertEqual(ctx.exception.status_code, 500)

    def test_malformed_response(self):
        with patch('quantia.lib.ai.providers.openai_compat.requests.post',
                   return_value=_mock_response(200, {'no': 'choices'})):
            with self.assertRaises(ProviderError):
                self.provider.chat([ChatMessage(role='user', content='hi')])


class TestRunChat(unittest.TestCase):
    def test_run_chat_records_audit(self):
        body = {
            'choices': [{'message': {'content': 'pong'}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2},
        }
        with patch('quantia.lib.ai.config._load_from_db', return_value={'api_key': 'sk-x'}), \
             patch('quantia.lib.ai.config._load_from_env', return_value={}), \
             patch('quantia.lib.ai.providers.openai_compat.requests.post',
                   return_value=_mock_response(200, body)), \
             patch('quantia.lib.ai.audit.record_call') as mock_audit:
            text = run_chat('ping', scene='unit_test')
        self.assertEqual(text, 'pong')
        mock_audit.assert_called_once()
        kwargs = mock_audit.call_args.kwargs
        self.assertEqual(kwargs['scene'], 'unit_test')
        self.assertTrue(kwargs['ok'])
        self.assertEqual(kwargs['total_tokens'], 2)
        self.assertEqual(kwargs['response'], 'pong')

    def test_run_chat_audits_on_failure(self):
        with patch('quantia.lib.ai.config._load_from_db', return_value={'api_key': 'sk-x'}), \
             patch('quantia.lib.ai.config._load_from_env', return_value={}), \
             patch('quantia.lib.ai.providers.openai_compat.requests.post',
                   return_value=_mock_response(429, {}, 'rl')), \
             patch('quantia.lib.ai.audit.record_call') as mock_audit:
            with self.assertRaises(RateLimitError):
                run_chat('ping', scene='unit_test')
        mock_audit.assert_called_once()
        kwargs = mock_audit.call_args.kwargs
        self.assertFalse(kwargs['ok'])
        self.assertIn('429', kwargs['error'])


class TestAuditTruncation(unittest.TestCase):
    """A3：审计写入前对 prompt/response 做按字节截断。"""

    def test_truncate_long_text(self):
        from quantia.lib.ai import audit as _audit
        original_max = _audit._MAX_TEXT_BYTES
        _audit._MAX_TEXT_BYTES = 100
        try:
            big = 'a' * 10_000
            out = _audit._truncate_for_audit(big)
            # 包含 TRUNCATED 标记，且总长度小于 raw（保留首部）
            self.assertIn('TRUNCATED', out)
            self.assertLess(len(out), len(big))
            self.assertTrue(out.startswith('a' * 50))
        finally:
            _audit._MAX_TEXT_BYTES = original_max

    def test_short_text_passthrough(self):
        from quantia.lib.ai import audit as _audit
        self.assertEqual(_audit._truncate_for_audit('hi'), 'hi')
        self.assertIsNone(_audit._truncate_for_audit(None))


class TestProviderSecretScrub(unittest.TestCase):
    """C2：异常消息中含 Bearer token / sk-xxx / api_key 应脱敏。"""

    def test_scrub_bearer(self):
        from quantia.lib.ai.providers.openai_compat import _scrub
        s = "401 Unauthorized: Bearer sk-abcdef1234567890 invalid"
        out = _scrub(s)
        self.assertNotIn('sk-abcdef', out)
        self.assertIn('[REDACTED]', out)

    def test_scrub_api_key_field(self):
        from quantia.lib.ai.providers.openai_compat import _scrub
        s = '{"error":"api_key=sk-1234567890abcdef invalid"}'
        out = _scrub(s)
        self.assertNotIn('1234567890abcdef', out)

    def test_scrub_url_query_param(self):
        from quantia.lib.ai.providers.openai_compat import _scrub
        s = "https://api.example.com/v1/chat?key=abcdef1234567890 timeout"
        out = _scrub(s)
        self.assertNotIn('abcdef1234567890', out)

    def test_scrub_x_api_key_header(self):
        from quantia.lib.ai.providers.openai_compat import _scrub
        s = "request failed: x-api-key: secrettoken12345 invalid"
        out = _scrub(s)
        self.assertNotIn('secrettoken12345', out)


class TestStreamErrorScrub(unittest.TestCase):
    """P0-E2：流式迭代异常需脱敏后再外抛。"""

    @patch('quantia.lib.ai.config._load_from_env', return_value={'api_key': 'k', 'api_base': 'http://x'})
    @patch('quantia.lib.ai.config._load_from_db', return_value={})
    def test_iter_lines_exception_is_scrubbed(self, *_):
        import requests as _req
        from quantia.lib.ai.providers.openai_compat import OpenAICompatProvider
        from quantia.lib.ai import AIConfig, ProviderError, ChatMessage

        cfg = AIConfig(provider='openai_compat', model='m', api_key='k', api_base='http://x')
        provider = OpenAICompatProvider(cfg)

        fake_resp = MagicMock()
        fake_resp.status_code = 200

        def _raise(*a, **kw):
            raise _req.ConnectionError('Connection refused: Bearer sk-leaktoken1234567890')

        fake_resp.iter_lines = _raise
        fake_resp.close = lambda: None

        with patch('quantia.lib.ai.providers.openai_compat.requests.post',
                   return_value=fake_resp):
            with self.assertRaises(ProviderError) as ctx:
                list(provider.stream([ChatMessage(role='user', content='hi')]))
        self.assertNotIn('sk-leaktoken1234567890', str(ctx.exception))
        self.assertIn('[REDACTED]', str(ctx.exception))


class TestRunChatAuditFailure(unittest.TestCase):
    """J1：DB 不可达时 run_chat 仍应正常返回内容。"""

    @patch('quantia.lib.ai.config._load_from_env', return_value={'api_key': 'k', 'api_base': 'http://x'})
    @patch('quantia.lib.ai.config._load_from_db', return_value={})
    def test_audit_failure_does_not_break_run_chat(self, *_):
        body = {'choices': [{'message': {'content': 'hi'}, 'finish_reason': 'stop'}],
                'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}}

        def _fake_post(*args, **kwargs):
            r = MagicMock()
            r.status_code = 200
            r.json = lambda: body
            return r

        with patch('quantia.lib.ai.providers.openai_compat.requests.post',
                   side_effect=_fake_post), \
             patch('quantia.lib.ai.audit.record_call', side_effect=Exception('DB down')):
            result = run_chat('ping', scene='unit_test')
        self.assertEqual(result, 'hi')


if __name__ == '__main__':
    unittest.main()
