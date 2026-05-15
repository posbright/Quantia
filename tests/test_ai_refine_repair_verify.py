#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试 RefineStrategyHandler / RepairStrategyHandler 的闭环验收升级：

升级目标（用户需求）：AI "修改当前代码" 和 "修复失败回测" 这两个 agent 在
修改完代码后, 不仅静态沙箱要通过, 还要跑一次轻量回测预演确认代码能跑起来,
否则继续把运行期错误反馈给 AI 重试修复。

覆盖：
1. _run_runtime_preflight 在引擎抛异常 / errors 非空 / 日志有 [ERROR] / 全 OK
   四种情形下的返回值；
2. _verify_strategy_code 三态：(ok, '', '') / 静态失败 ('static') / 运行期失败 ('runtime')；
3. Refine handler 闭环：第一轮通过静态但运行期失败 → 第二轮 AI 改完后通过 → repair_status='success'；
4. Repair handler 闭环：与 Refine 相同行为；
5. 多轮失败仍未修好 → repair_status='max_attempts' 且响应 validation_kind='runtime'。
"""
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tornado.testing import AsyncHTTPTestCase
from tornado.web import Application

import quantia.web.aiAssistantHandler as ai_h


_VALID_CODE = '''def initialize(context):
    context.security = '000001'

def handle_data(context, data):
    pass
'''

_VALID_CODE_FIXED = '''# fixed
def initialize(context):
    context.security = '000001'

def handle_data(context, data):
    pass
'''


def _make_app() -> Application:
    return Application([
        (r"/quantia/api/ai/strategy/refine", ai_h.RefineStrategyHandler),
        (r"/quantia/api/ai/strategy/repair", ai_h.RepairStrategyHandler),
    ])


class RuntimePreflightUnitTests(unittest.TestCase):
    """_run_runtime_preflight 与 _verify_strategy_code 单元行为。"""

    def test_preflight_returns_ok_when_engine_completes_cleanly(self):
        result = {
            'status': 'completed',
            'errors': [],
            'logs': ['[2025-01-02 09:30:00] [INFO] 启动完成'],
        }
        with mock.patch('quantia.core.backtest.portfolio_engine.PortfolioBacktestEngine'
                        ) as Eng:
            Eng.return_value.run.return_value = result
            ok, err = ai_h._run_runtime_preflight(_VALID_CODE)
        self.assertTrue(ok, err)
        self.assertEqual(err, '')

    def test_preflight_catches_engine_exception(self):
        with mock.patch('quantia.core.backtest.portfolio_engine.PortfolioBacktestEngine'
                        ) as Eng:
            Eng.return_value.run.side_effect = RuntimeError('boom1234')
            ok, err = ai_h._run_runtime_preflight(_VALID_CODE)
        self.assertFalse(ok)
        self.assertIn('RuntimeError', err)
        self.assertIn('boom1234', err)

    def test_preflight_detects_strategy_errors_list(self):
        result = {
            'status': 'completed',
            'errors': [{'type': 'NameError', 'error': "name 'ta' is not defined",
                        'traceback': 'Traceback ...\nNameError: name \'ta\' is not defined'}],
            'logs': [],
        }
        with mock.patch('quantia.core.backtest.portfolio_engine.PortfolioBacktestEngine'
                        ) as Eng:
            Eng.return_value.run.return_value = result
            ok, err = ai_h._run_runtime_preflight(_VALID_CODE)
        self.assertFalse(ok)
        self.assertIn('NameError', err)
        self.assertIn("name 'ta'", err)

    def test_preflight_detects_swallowed_error_logs(self):
        """策略 try/except 吞掉异常只 log.error 时，日志反解仍要算失败。"""
        result = {
            'status': 'completed',
            'errors': [],
            'logs': [
                '[2025-01-02 09:30] [INFO] hi',
                '[2025-01-02 10:00] [ERROR] 处理 000001 时发生错误: name \'ta\' is not defined',
                '[2025-01-02 11:00] [ERROR] 处理 000002 时发生错误: name \'ta\' is not defined',
            ],
        }
        with mock.patch('quantia.core.backtest.portfolio_engine.PortfolioBacktestEngine'
                        ) as Eng:
            Eng.return_value.run.return_value = result
            ok, err = ai_h._run_runtime_preflight(_VALID_CODE)
        self.assertFalse(ok)
        self.assertIn('[ERROR]', err)
        self.assertIn("name 'ta'", err)

    def test_preflight_returns_failure_when_engine_status_error(self):
        result = {'status': 'error', 'message': '无可用交易日'}
        with mock.patch('quantia.core.backtest.portfolio_engine.PortfolioBacktestEngine'
                        ) as Eng:
            Eng.return_value.run.return_value = result
            ok, err = ai_h._run_runtime_preflight(_VALID_CODE)
        self.assertFalse(ok)
        self.assertIn('无可用交易日', err)

    def test_verify_strategy_code_static_failure_short_circuits(self):
        os.environ['QUANTIA_AI_REPAIR_RUN_PREFLIGHT'] = '1'
        try:
            unsafe = 'import os\n' + _VALID_CODE
            # 故意让 preflight 抛异常，确保静态失败时不会调到 preflight
            with mock.patch(
                    'quantia.web.aiAssistantHandler._run_runtime_preflight',
                    side_effect=AssertionError('should not be called')):
                ok, kind, err = ai_h._verify_strategy_code(unsafe, {})
            self.assertFalse(ok)
            self.assertEqual(kind, 'static')
            self.assertTrue(err)
        finally:
            os.environ.pop('QUANTIA_AI_REPAIR_RUN_PREFLIGHT', None)

    def test_verify_strategy_code_runtime_failure_carries_kind(self):
        os.environ['QUANTIA_AI_REPAIR_RUN_PREFLIGHT'] = '1'
        try:
            with mock.patch(
                    'quantia.web.aiAssistantHandler._run_runtime_preflight',
                    return_value=(False, '回测期 NameError')):
                ok, kind, err = ai_h._verify_strategy_code(_VALID_CODE, {})
            self.assertFalse(ok)
            self.assertEqual(kind, 'runtime')
            self.assertIn('NameError', err)
        finally:
            os.environ.pop('QUANTIA_AI_REPAIR_RUN_PREFLIGHT', None)

    def test_verify_strategy_code_all_pass(self):
        os.environ['QUANTIA_AI_REPAIR_RUN_PREFLIGHT'] = '1'
        try:
            with mock.patch(
                    'quantia.web.aiAssistantHandler._run_runtime_preflight',
                    return_value=(True, '')):
                ok, kind, err = ai_h._verify_strategy_code(_VALID_CODE, {})
            self.assertTrue(ok)
            self.assertEqual(kind, '')
            self.assertEqual(err, '')
        finally:
            os.environ.pop('QUANTIA_AI_REPAIR_RUN_PREFLIGHT', None)


class RefineCloseLoopTests(AsyncHTTPTestCase):
    """修改当前代码：第一轮通过静态但运行期挂掉，AI 二轮修好。"""

    def get_app(self):
        return _make_app()

    def setUp(self):
        super().setUp()
        os.environ['QUANTIA_AI_REPAIR_RUN_PREFLIGHT'] = '1'
        os.environ['QUANTIA_AI_REPAIR_MAX_ATTEMPTS'] = '3'

    def tearDown(self):
        os.environ.pop('QUANTIA_AI_REPAIR_RUN_PREFLIGHT', None)
        os.environ.pop('QUANTIA_AI_REPAIR_MAX_ATTEMPTS', None)
        super().tearDown()

    def test_refine_runtime_failure_triggers_repair_loop(self):
        """首轮代码静态过但运行期挂 → 进入修复循环 → 二轮通过 → status=success。"""
        ai_calls = []

        def _fake_ai(prompt, *a, **kw):
            ai_calls.append(prompt)
            # 第一次返回"含 bug"的代码（静态过、preflight 挂），第二次返回"修好"的代码
            if len(ai_calls) == 1:
                return _VALID_CODE, 'm1'
            return _VALID_CODE_FIXED, 'm1'

        preflight_calls = []

        def _fake_preflight(code, **kw):
            preflight_calls.append(code)
            # 第一次（buggy 代码）失败；第二次（fixed 代码）通过
            if len(preflight_calls) == 1:
                return False, "回测运行期 NameError: name 'ta' is not defined"
            return True, ''

        with mock.patch('quantia.web.aiAssistantHandler._call_ai_blocking',
                        side_effect=_fake_ai), \
             mock.patch('quantia.web.aiAssistantHandler._run_runtime_preflight',
                        side_effect=_fake_preflight):
            resp = self.fetch('/quantia/api/ai/strategy/refine', method='POST',
                              body=json.dumps({
                                  'prompt': '请加止损 5%',
                                  'code': _VALID_CODE,
                              }))
        body = json.loads(resp.body)
        self.assertEqual(body['code'], 0, body)
        self.assertEqual(body['data']['repair_status'], 'success')
        self.assertEqual(body['data']['repair_attempts'], 1)  # 二次 AI 调用 = 一次重试
        self.assertEqual(body['data']['validation_kind'], '')
        # 第二次 AI 调用必须收到"运行期"修复提示
        runtime_prompt = ai_calls[1]
        self.assertIn('回测', runtime_prompt)
        self.assertIn('NameError', runtime_prompt)
        # 必须使用 _build_runtime_repair_prompt 路径（含沙箱不会自动注入的提示）
        self.assertIn('沙箱', runtime_prompt)
        self.assertIn('numpy', runtime_prompt)

    def test_refine_runtime_failure_exhausts_attempts(self):
        """三轮都修不好 → repair_status='max_attempts' 且 validation_kind='runtime'。"""
        os.environ['QUANTIA_AI_REPAIR_MAX_ATTEMPTS'] = '2'  # 缩短 CI 时间
        # AI 每次都返回不同但仍然 buggy 的代码（保证 no_progress 守卫不会提前退出）
        counter = {'n': 0}

        def _fake_ai(prompt, *a, **kw):
            counter['n'] += 1
            return f"# iter {counter['n']}\n" + _VALID_CODE, 'm1'

        with mock.patch('quantia.web.aiAssistantHandler._call_ai_blocking',
                        side_effect=_fake_ai), \
             mock.patch('quantia.web.aiAssistantHandler._run_runtime_preflight',
                        return_value=(False, '回测一直挂')):
            resp = self.fetch('/quantia/api/ai/strategy/refine', method='POST',
                              body=json.dumps({
                                  'prompt': '改持仓数',
                                  'code': _VALID_CODE,
                              }))
        body = json.loads(resp.body)
        self.assertEqual(body['code'], -2, body)
        self.assertFalse(body['data']['validated'])
        self.assertEqual(body['data']['validation_kind'], 'runtime')
        self.assertEqual(body['data']['repair_status'], 'max_attempts')
        self.assertEqual(body['data']['repair_attempts'], 2)
        self.assertIn('回测预演失败', body['msg'])

    def test_refine_static_failure_uses_static_prompt(self):
        """静态校验失败时必须使用 _build_repair_prompt（含'沙箱安全'文案）而不是 runtime 变体。"""
        ai_calls = []
        # 第一次返回 import os 的不安全代码（静态挂），第二次返回干净代码（通过）
        responses = [('import os\n' + _VALID_CODE, 'm1'), (_VALID_CODE, 'm1')]

        def _fake_ai(prompt, *a, **kw):
            ai_calls.append(prompt)
            return responses[len(ai_calls) - 1]

        with mock.patch('quantia.web.aiAssistantHandler._call_ai_blocking',
                        side_effect=_fake_ai), \
             mock.patch('quantia.web.aiAssistantHandler._run_runtime_preflight',
                        return_value=(True, '')):
            resp = self.fetch('/quantia/api/ai/strategy/refine', method='POST',
                              body=json.dumps({
                                  'prompt': '改一改',
                                  'code': _VALID_CODE,
                              }))
        body = json.loads(resp.body)
        self.assertEqual(body['code'], 0, body)
        self.assertEqual(body['data']['repair_status'], 'success')
        # 第二次 AI 调用应该是 static 修复 prompt（不含 runtime 特有的"回测期间"字样）
        static_repair = ai_calls[1]
        self.assertIn('沙箱安全校验', static_repair)
        self.assertNotIn('回测运行期间的错误', static_repair)


class RepairCloseLoopTests(AsyncHTTPTestCase):
    """修复失败回测：同样需要 runtime preflight 闭环。"""

    def get_app(self):
        return _make_app()

    def setUp(self):
        super().setUp()
        os.environ['QUANTIA_AI_REPAIR_RUN_PREFLIGHT'] = '1'
        os.environ['QUANTIA_AI_REPAIR_MAX_ATTEMPTS'] = '3'

    def tearDown(self):
        os.environ.pop('QUANTIA_AI_REPAIR_RUN_PREFLIGHT', None)
        os.environ.pop('QUANTIA_AI_REPAIR_MAX_ATTEMPTS', None)
        super().tearDown()

    def test_repair_runtime_failure_triggers_repair_loop(self):
        last_failure = {
            'id': 7, 'started_at': '2026-05-11', 'completed_at': '2026-05-11',
            'error_message': "NameError: name 'ta' is not defined",
            'traceback': 'Traceback...\nNameError', 'error': 'ta',
        }
        ai_calls = []

        def _fake_ai(prompt, *a, **kw):
            ai_calls.append(prompt)
            if len(ai_calls) == 1:
                return _VALID_CODE, 'm1'  # 首轮 AI 输出
            return _VALID_CODE_FIXED, 'm1'  # 二轮 AI 修复后

        preflight_calls = []

        def _fake_preflight(code, **kw):
            preflight_calls.append(code)
            if len(preflight_calls) == 1:
                return False, '回测期 ZeroDivisionError'
            return True, ''

        with mock.patch('quantia.core.backtest.task_recorder.fetch_last_failure',
                        return_value=last_failure), \
             mock.patch('quantia.core.backtest.task_recorder.fetch_recent_failures',
                        return_value=[]), \
             mock.patch('quantia.web.aiAssistantHandler._call_ai_blocking',
                        side_effect=_fake_ai), \
             mock.patch('quantia.web.aiAssistantHandler._run_runtime_preflight',
                        side_effect=_fake_preflight):
            resp = self.fetch('/quantia/api/ai/strategy/repair', method='POST',
                              body=json.dumps({
                                  'strategy_id': 7,
                                  'code': _VALID_CODE,
                                  'auto_backtest': False,
                              }))
        body = json.loads(resp.body)
        self.assertEqual(body['code'], 0, body)
        self.assertEqual(body['data']['repair_status'], 'success')
        self.assertEqual(body['data']['repair_attempts'], 1)
        self.assertEqual(body['data']['validation_kind'], '')
        # 二轮 prompt 必须包含 runtime 错误信息（ZeroDivisionError）和沙箱 import 提示
        runtime_prompt = ai_calls[1]
        self.assertIn('ZeroDivisionError', runtime_prompt)
        self.assertIn('沙箱', runtime_prompt)


if __name__ == '__main__':
    unittest.main()
