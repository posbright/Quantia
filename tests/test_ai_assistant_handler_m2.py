#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M2 aiAssistantHandler 集成测试。"""

import json
import sys
import os
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tornado.testing import AsyncHTTPTestCase
from tornado.web import Application

import quantia.web.aiAssistantHandler as ai_h


def _make_app() -> Application:
    return Application([
        (r"/quantia/api/ai/strategy/generate", ai_h.GenerateStrategyHandler),
        (r"/quantia/api/ai/strategy/refine", ai_h.RefineStrategyHandler),
        (r"/quantia/api/ai/strategy/repair", ai_h.RepairStrategyHandler),
        (r"/quantia/api/ai/chat", ai_h.ChatHandler),
    ])


_VALID_CODE = '''def initialize(context):
    context.security = '000001'

def handle_data(context, data):
    pass
'''


class GenerateHandlerTests(AsyncHTTPTestCase):
    def get_app(self):
        return _make_app()

    def test_empty_prompt_returns_error(self):
        resp = self.fetch('/quantia/api/ai/strategy/generate', method='POST',
                          body=json.dumps({'prompt': ''}))
        self.assertEqual(resp.code, 200)
        body = json.loads(resp.body)
        self.assertEqual(body['code'], -1)
        self.assertIn('prompt', body['msg'])

    def test_generate_success(self):
        with mock.patch('quantia.web.aiAssistantHandler._call_ai_blocking',
                        return_value=(_VALID_CODE, 'gpt-4o-mini')):
            resp = self.fetch('/quantia/api/ai/strategy/generate', method='POST',
                              body=json.dumps({'prompt': '生成一个简单策略'}))
        self.assertEqual(resp.code, 200)
        body = json.loads(resp.body)
        self.assertEqual(body['code'], 0, body)
        self.assertTrue(body['data']['validated'])
        self.assertIn('def initialize', body['data']['code'])
        self.assertEqual(body['data']['model'], 'gpt-4o-mini')

    def test_generate_strips_code_fence(self):
        fenced = f"```python\n{_VALID_CODE}```"
        with mock.patch('quantia.web.aiAssistantHandler._call_ai_blocking',
                        return_value=(fenced, 'm1')):
            resp = self.fetch('/quantia/api/ai/strategy/generate', method='POST',
                              body=json.dumps({'prompt': 'x'}))
        body = json.loads(resp.body)
        self.assertEqual(body['code'], 0, body)
        self.assertNotIn('```', body['data']['code'])

    def test_generate_unsafe_code_fails_validation(self):
        unsafe = "import os\n" + _VALID_CODE
        with mock.patch('quantia.web.aiAssistantHandler._call_ai_blocking',
                        return_value=(unsafe, 'm1')):
            resp = self.fetch('/quantia/api/ai/strategy/generate', method='POST',
                              body=json.dumps({'prompt': 'x'}))
        body = json.loads(resp.body)
        self.assertEqual(body['code'], -2)
        self.assertFalse(body['data']['validated'])

    def test_generate_rate_limit(self):
        from quantia.lib.ai import RateLimitError
        with mock.patch('quantia.web.aiAssistantHandler._call_ai_blocking',
                        side_effect=RateLimitError('429')):
            resp = self.fetch('/quantia/api/ai/strategy/generate', method='POST',
                              body=json.dumps({'prompt': 'x'}))
        self.assertEqual(resp.code, 429)
        body = json.loads(resp.body)
        self.assertEqual(body['code'], 429)


class RefineHandlerTests(AsyncHTTPTestCase):
    def get_app(self):
        return _make_app()

    def test_refine_requires_both_fields(self):
        resp = self.fetch('/quantia/api/ai/strategy/refine', method='POST',
                          body=json.dumps({'prompt': 'x'}))
        body = json.loads(resp.body)
        self.assertEqual(body['code'], -1)

    def test_refine_success(self):
        with mock.patch('quantia.web.aiAssistantHandler._call_ai_blocking',
                        return_value=(_VALID_CODE, 'm1')) as m:
            resp = self.fetch('/quantia/api/ai/strategy/refine', method='POST',
                              body=json.dumps({
                                  'prompt': '改成持仓 10 只',
                                  'code': _VALID_CODE,
                              }))
        body = json.loads(resp.body)
        self.assertEqual(body['code'], 0, body)
        # composed prompt should embed original code
        composed_arg = m.call_args.args[0]
        self.assertIn('改成持仓 10 只', composed_arg)
        self.assertIn("context.security = '000001'", composed_arg)


class RepairHandlerTests(AsyncHTTPTestCase):
    def get_app(self):
        return _make_app()

    def test_repair_requires_strategy_id(self):
        resp = self.fetch('/quantia/api/ai/strategy/repair', method='POST',
                          body=json.dumps({}))
        self.assertEqual(json.loads(resp.body)['code'], -1)

    def test_repair_no_failure_record(self):
        # 无 DB 失败记录 + 静态校验通过 + 显式关闭 auto_backtest → 走"无失败可修复"分支
        with mock.patch('quantia.core.backtest.task_recorder.fetch_last_failure',
                        return_value=None), \
             mock.patch('quantia.core.backtest.task_recorder.fetch_recent_failures',
                        return_value=[]):
            resp = self.fetch('/quantia/api/ai/strategy/repair', method='POST',
                              body=json.dumps({
                                  'strategy_id': 999,
                                  'code': _VALID_CODE,
                                  'auto_backtest': False,
                              }))
        body = json.loads(resp.body)
        self.assertEqual(body['code'], -1)
        self.assertIn('未找到', body['msg'])
        # 提示文案应明确告诉用户"静态校验已通过"避免误以为 bug
        self.assertIn('静态校验', body['msg'])

    def test_repair_preflight_static_check_picks_up_syntax_error(self):
        """无失败记录但代码沙箱校验失败 → 把校验错误当作失败喂给 AI 修复。"""
        bad_code = 'def initialize(context):\n    import os\n    pass\n'
        with mock.patch('quantia.core.backtest.task_recorder.fetch_last_failure',
                        return_value=None), \
             mock.patch('quantia.core.backtest.task_recorder.fetch_recent_failures',
                        return_value=[]), \
             mock.patch('quantia.web.aiAssistantHandler._call_ai_blocking',
                        return_value=(_VALID_CODE, 'm1')) as m:
            resp = self.fetch('/quantia/api/ai/strategy/repair', method='POST',
                              body=json.dumps({
                                  'strategy_id': 999,
                                  'code': bad_code,
                                  'auto_backtest': False,
                              }))
        body = json.loads(resp.body)
        self.assertEqual(body['code'], 0, body)
        # 修复 prompt 中必须带上静态校验失败信息
        composed = m.call_args.args[0]
        self.assertIn('静态校验失败', composed)
        # 响应 failure.source 标记为 static
        self.assertEqual(body['data']['failure'].get('source'), 'static')

    def test_repair_preflight_backtest_records_runtime_failure(self):
        """auto_backtest=True 时预演回测抛错 → 记录并喂给 AI 修复。"""
        with mock.patch('quantia.core.backtest.task_recorder.fetch_last_failure',
                        return_value=None), \
             mock.patch('quantia.core.backtest.task_recorder.fetch_recent_failures',
                        return_value=[]), \
             mock.patch('quantia.core.backtest.task_recorder.record_failed',
                        return_value=42), \
             mock.patch('quantia.core.backtest.portfolio_engine.PortfolioBacktestEngine'
                        ) as _MockEng, \
             mock.patch('quantia.web.aiAssistantHandler._call_ai_blocking',
                        return_value=(_VALID_CODE, 'm1')) as m:
            # 预演回测抛 RuntimeError
            inst = _MockEng.return_value
            inst.run.side_effect = RuntimeError('preflight boom: ZeroDivisionError')
            resp = self.fetch('/quantia/api/ai/strategy/repair', method='POST',
                              body=json.dumps({
                                  'strategy_id': 999,
                                  'code': _VALID_CODE,
                                  'auto_backtest': True,
                                  'start_date': '2026-03-01',
                                  'end_date': '2026-05-01',
                                  'initial_cash': 1000000,
                              }))
        body = json.loads(resp.body)
        self.assertEqual(body['code'], 0, body)
        composed = m.call_args.args[0]
        self.assertIn('preflight boom', composed)
        self.assertEqual(body['data']['failure'].get('source'), 'backtest')

    def test_repair_success(self):
        last = {'id': 7, 'started_at': '2026-05-11', 'completed_at': '2026-05-11',
                'error_message': 'ZeroDivisionError'}
        with mock.patch('quantia.core.backtest.task_recorder.fetch_last_failure',
                        return_value=last), \
             mock.patch('quantia.web.aiAssistantHandler._call_ai_blocking',
                        return_value=(_VALID_CODE, 'm1')) as m:
            resp = self.fetch('/quantia/api/ai/strategy/repair', method='POST',
                              body=json.dumps({'strategy_id': 7, 'code': _VALID_CODE}))
        body = json.loads(resp.body)
        self.assertEqual(body['code'], 0, body)
        self.assertEqual(body['data']['failure']['error_message'], 'ZeroDivisionError')
        composed = m.call_args.args[0]
        self.assertIn('ZeroDivisionError', composed)


class ChatHandlerTests(AsyncHTTPTestCase):
    def get_app(self):
        return _make_app()

    def test_chat_returns_raw_content(self):
        with mock.patch('quantia.web.aiAssistantHandler._call_ai_blocking',
                        return_value=('hello world', 'm1')):
            resp = self.fetch('/quantia/api/ai/chat', method='POST',
                              body=json.dumps({'prompt': 'hi'}))
        body = json.loads(resp.body)
        self.assertEqual(body['code'], 0)
        self.assertEqual(body['data']['content'], 'hello world')

    def test_chat_rate_limit_status_429(self):
        from quantia.lib.ai import RateLimitError
        with mock.patch('quantia.web.aiAssistantHandler._call_ai_blocking',
                        side_effect=RateLimitError('429')):
            resp = self.fetch('/quantia/api/ai/chat', method='POST',
                              body=json.dumps({'prompt': 'hi'}))
        self.assertEqual(resp.code, 429)
        self.assertEqual(json.loads(resp.body)['code'], 429)


class StripFenceTests(unittest.TestCase):
    def test_python_fence(self):
        self.assertEqual(
            ai_h._strip_code_fence('```python\nprint(1)\n```'),
            'print(1)',
        )

    def test_no_fence(self):
        self.assertEqual(ai_h._strip_code_fence('x=1\n'), 'x=1')

    def test_empty(self):
        self.assertEqual(ai_h._strip_code_fence(''), '')


# ─── B1：SSE 流式生成 ──────────────────────────────────────────
def _sse_app() -> Application:
    return Application([
        (r"/quantia/api/ai/strategy/generate/stream",
         ai_h.GenerateStrategyStreamHandler),
    ])


def _parse_sse(body: bytes):
    """把 SSE 响应体按 data: 拆为事件 dict 列表。"""
    out = []
    for chunk in body.split(b'\n\n'):
        s = chunk.strip()
        if not s.startswith(b'data:'):
            continue
        try:
            out.append(json.loads(s[5:].strip()))
        except Exception:
            continue
    return out


class GenerateStreamHandlerTests(AsyncHTTPTestCase):
    def get_app(self):
        return _sse_app()

    def test_stream_empty_prompt(self):
        resp = self.fetch('/quantia/api/ai/strategy/generate/stream',
                          method='POST', body=json.dumps({'prompt': ''}))
        # _write_error 路径走普通 JSON
        body = json.loads(resp.body)
        self.assertEqual(body['code'], -1)

    def test_stream_yields_chunks_then_done(self):
        chunks = ['def initi', 'alize(context):\n    ', "context.security = '000001'\n",
                  '\ndef handle_data(context, data):\n    pass\n']

        def _fake(*args, **kwargs):
            yield from chunks

        with mock.patch('quantia.web.aiAssistantHandler.stream_chat',
                        side_effect=_fake):
            resp = self.fetch('/quantia/api/ai/strategy/generate/stream',
                              method='POST', body=json.dumps({'prompt': 'x'}))
        self.assertEqual(resp.code, 200)
        events = _parse_sse(resp.body)
        types = [e.get('type') for e in events]
        self.assertEqual(types.count('chunk'), len(chunks))
        self.assertEqual(types[-1], 'done')
        done = events[-1]
        self.assertTrue(done['validated'], done)
        self.assertIn('def initialize', done['code'])
        self.assertIn('model', done)

    def test_stream_rate_limit_emits_error(self):
        from quantia.lib.ai import RateLimitError

        def _boom(*args, **kwargs):
            raise RateLimitError('429')
            yield  # pragma: no cover

        with mock.patch('quantia.web.aiAssistantHandler.stream_chat',
                        side_effect=_boom):
            resp = self.fetch('/quantia/api/ai/strategy/generate/stream',
                              method='POST', body=json.dumps({'prompt': 'x'}))
        events = _parse_sse(resp.body)
        self.assertTrue(any(e.get('type') == 'error' and e.get('code') == 429
                            for e in events), events)

    def test_stream_truncation_emits_done_with_flag(self):
        """L2：超过上限应正常发出 done + truncated=true，而非致命 error。"""
        import quantia.web.aiAssistantHandler as ai_h
        big_chunk = 'x' * 1024  # 1KB per chunk

        def _fake(*args, **kwargs):
            for _ in range(50):
                yield big_chunk

        original = ai_h._MAX_GENERATED_CHARS
        ai_h._MAX_GENERATED_CHARS = 4 * 1024  # 4KB → 截断
        try:
            with mock.patch('quantia.web.aiAssistantHandler.stream_chat',
                            side_effect=_fake):
                resp = self.fetch('/quantia/api/ai/strategy/generate/stream',
                                  method='POST', body=json.dumps({'prompt': 'x'}))
        finally:
            ai_h._MAX_GENERATED_CHARS = original
        events = _parse_sse(resp.body)
        types = [e.get('type') for e in events]
        # 应以 done 收尾且 truncated=True
        self.assertEqual(types[-1], 'done')
        self.assertTrue(events[-1].get('truncated'), events[-1])
        # 不应当出现致命 error
        self.assertFalse(any(e.get('type') == 'error' for e in events), events)

    def test_stream_sentinel_when_queue_full(self):
        """K2：生产端被快速塞满后，sentinel 仍能被消费端接收（不会卡死）。"""
        many_pieces = [f'p{i}' for i in range(200)]

        def _fake(*args, **kwargs):
            for p in many_pieces:
                yield p

        with mock.patch('quantia.web.aiAssistantHandler.stream_chat',
                        side_effect=_fake):
            resp = self.fetch('/quantia/api/ai/strategy/generate/stream',
                              method='POST', body=json.dumps({'prompt': 'x'}))
        # 关键：响应正常返回（未死锁），且最后一个事件为 done
        self.assertEqual(resp.code, 200)
        events = _parse_sse(resp.body)
        self.assertEqual(events[-1].get('type'), 'done')


# ─── B3：refine / repair 也应返回 HTTP 429 ──────────────────────
class RateLimitStatusTests(AsyncHTTPTestCase):
    def get_app(self):
        return _make_app()

    def test_refine_rate_limit_status_429(self):
        from quantia.lib.ai import RateLimitError
        with mock.patch('quantia.web.aiAssistantHandler._call_ai_blocking',
                        side_effect=RateLimitError('429')):
            resp = self.fetch('/quantia/api/ai/strategy/refine', method='POST',
                              body=json.dumps({'prompt': 'x', 'code': _VALID_CODE}))
        self.assertEqual(resp.code, 429)

    def test_repair_rate_limit_status_429(self):
        from quantia.lib.ai import RateLimitError
        last = {'id': 1, 'started_at': '2026-05-11', 'error_message': 'boom'}
        with mock.patch('quantia.core.backtest.task_recorder.fetch_last_failure',
                        return_value=last), \
             mock.patch('quantia.web.aiAssistantHandler._call_ai_blocking',
                        side_effect=RateLimitError('429')):
            resp = self.fetch('/quantia/api/ai/strategy/repair', method='POST',
                              body=json.dumps({'strategy_id': 1, 'code': _VALID_CODE}))
        self.assertEqual(resp.code, 429)


# ─── M3：strict 校验失败自动重试 ≤3 轮 ──────────────────────────
_UNSAFE_CODE = "import os\n" + _VALID_CODE
_UNSAFE_CODE_2 = "import sys\n" + _VALID_CODE
_UNSAFE_CODE_3 = "import subprocess\n" + _VALID_CODE


class M3RetryTests(AsyncHTTPTestCase):
    def get_app(self):
        return _make_app()

    def test_generate_unsafe_then_repaired_by_retry(self):
        """首轮返回 import os（不安全），重试第 1 轮返回安全代码 → 验收通过。"""
        seq = [(_UNSAFE_CODE, 'm1'), (_VALID_CODE, 'm1')]
        with mock.patch('quantia.web.aiAssistantHandler._call_ai_blocking',
                        side_effect=seq):
            resp = self.fetch('/quantia/api/ai/strategy/generate', method='POST',
                              body=json.dumps({'prompt': 'x'}))
        body = json.loads(resp.body)
        self.assertEqual(body['code'], 0, body)
        self.assertTrue(body['data']['validated'])
        self.assertEqual(body['data']['repair_attempts'], 1)
        self.assertEqual(body['data']['repair_status'], 'success')
        self.assertNotIn('import os', body['data']['code'])

    def test_generate_distinct_unsafe_3_attempts_max_attempts(self):
        """3 次重试每次都返回**不同**的不安全代码 → repair_status='max_attempts', attempts=3。"""
        bad = [(_UNSAFE_CODE, 'm1'), (_UNSAFE_CODE_2, 'm1'),
               (_UNSAFE_CODE_3, 'm1'), (_UNSAFE_CODE, 'm1')]
        with mock.patch('quantia.web.aiAssistantHandler._call_ai_blocking',
                        side_effect=bad):
            resp = self.fetch('/quantia/api/ai/strategy/generate', method='POST',
                              body=json.dumps({'prompt': 'x'}))
        body = json.loads(resp.body)
        self.assertEqual(body['code'], -2)  # 校验失败统一返回 -2
        self.assertFalse(body['data']['validated'])
        self.assertEqual(body['data']['repair_attempts'], 3)
        self.assertEqual(body['data']['repair_status'], 'max_attempts')

    def test_generate_dedup_same_unsafe_returned_twice(self):
        """D1：连续两次返回完全相同的不安全代码 → 提前退出 repair_status='no_progress'。"""
        seq = [(_UNSAFE_CODE, 'm1'), (_UNSAFE_CODE, 'm1')]
        with mock.patch('quantia.web.aiAssistantHandler._call_ai_blocking',
                        side_effect=seq):
            resp = self.fetch('/quantia/api/ai/strategy/generate', method='POST',
                              body=json.dumps({'prompt': 'x'}))
        body = json.loads(resp.body)
        self.assertEqual(body['code'], -2)
        self.assertEqual(body['data']['repair_attempts'], 1)
        self.assertEqual(body['data']['repair_status'], 'no_progress')

    def test_generate_repair_rate_limited_propagates_status(self):
        """D2：重试中触发限流 → repair_status='rate_limited'，但响应仍是 200/-2 + 上次 raw。"""
        from quantia.lib.ai import RateLimitError
        seq = [(_UNSAFE_CODE, 'm1'), RateLimitError('429 in retry')]
        with mock.patch('quantia.web.aiAssistantHandler._call_ai_blocking',
                        side_effect=seq):
            resp = self.fetch('/quantia/api/ai/strategy/generate', method='POST',
                              body=json.dumps({'prompt': 'x'}))
        body = json.loads(resp.body)
        self.assertEqual(body['code'], -2)
        self.assertEqual(body['data']['repair_status'], 'rate_limited')
        self.assertEqual(body['data']['repair_attempts'], 1)

    def test_refine_repair_attempts_succeed_on_2nd(self):
        """refine 首轮失败、第 2 轮成功 → repair_attempts=2。"""
        seq = [(_UNSAFE_CODE, 'm1'), (_UNSAFE_CODE_2, 'm1'), (_VALID_CODE, 'm1')]
        with mock.patch('quantia.web.aiAssistantHandler._call_ai_blocking',
                        side_effect=seq):
            resp = self.fetch('/quantia/api/ai/strategy/refine', method='POST',
                              body=json.dumps({'prompt': 'x', 'code': _VALID_CODE}))
        body = json.loads(resp.body)
        self.assertEqual(body['code'], 0, body)
        self.assertEqual(body['data']['repair_attempts'], 2)
        self.assertEqual(body['data']['repair_status'], 'success')

    def test_max_attempts_env_override(self):
        """D4：QUANTIA_AI_REPAIR_MAX_ATTEMPTS 应在每次请求时动态生效。"""
        import os as _os
        seq = [(_UNSAFE_CODE, 'm1')] * 5
        original = _os.environ.get('QUANTIA_AI_REPAIR_MAX_ATTEMPTS')
        _os.environ['QUANTIA_AI_REPAIR_MAX_ATTEMPTS'] = '0'
        try:
            with mock.patch('quantia.web.aiAssistantHandler._call_ai_blocking',
                            side_effect=seq):
                resp = self.fetch('/quantia/api/ai/strategy/generate', method='POST',
                                  body=json.dumps({'prompt': 'x'}))
            body = json.loads(resp.body)
            self.assertEqual(body['data']['repair_attempts'], 0)
        finally:
            if original is None:
                _os.environ.pop('QUANTIA_AI_REPAIR_MAX_ATTEMPTS', None)
            else:
                _os.environ['QUANTIA_AI_REPAIR_MAX_ATTEMPTS'] = original


if __name__ == '__main__':
    unittest.main()
