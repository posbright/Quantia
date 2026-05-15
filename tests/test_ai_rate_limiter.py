#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""规范一致性修复：AI 滑窗限流（spec §4.2 / §16.5 / §13 验收第 9 条）。

不依赖真实 MySQL；通过 patch executeSqlFetch 模拟过去 1 小时的统计返回。
"""

import os
import unittest
from unittest import mock

from quantia.lib.ai import rate_limiter
from quantia.lib.ai.exceptions import RateLimitError


class _BaseEnv(unittest.TestCase):
    def setUp(self):
        # 默认开启限流；显式 disable 由各用例自行设置
        self._snapshot = {k: os.environ.get(k) for k in (
            'QUANTIA_AI_RATE_DISABLED',
            'QUANTIA_AI_RATE_CALLS_PER_HOUR',
            'QUANTIA_AI_RATE_TOKENS_PER_HOUR',
        )}
        for k in self._snapshot:
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self._snapshot.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class CheckQuotaTests(_BaseEnv):
    def test_disabled_via_env_skips(self):
        os.environ['QUANTIA_AI_RATE_DISABLED'] = '1'
        # 即便配额为 0 也不应抛
        os.environ['QUANTIA_AI_RATE_CALLS_PER_HOUR'] = '0'
        with mock.patch('quantia.lib.ai.rate_limiter.mdb.executeSqlFetch',
                        return_value=[(999, 999_999)]):
            rate_limiter.check_quota(user_id='1.2.3.4', scene='x')

    def test_no_user_id_skips(self):
        with mock.patch('quantia.lib.ai.rate_limiter.mdb.executeSqlFetch') as m:
            rate_limiter.check_quota(user_id=None, scene='x')
        m.assert_not_called()

    def test_rate_limit_loop_flag_skips(self):
        with mock.patch('quantia.lib.ai.rate_limiter.mdb.executeSqlFetch') as m:
            rate_limiter.check_quota(
                user_id='1.2.3.4', scene='x', rate_limit_loop=True)
        m.assert_not_called()

    def test_under_quota_passes(self):
        os.environ['QUANTIA_AI_RATE_CALLS_PER_HOUR'] = '60'
        os.environ['QUANTIA_AI_RATE_TOKENS_PER_HOUR'] = '200000'
        with mock.patch('quantia.lib.ai.rate_limiter.mdb.executeSqlFetch',
                        return_value=[(10, 5000)]):
            rate_limiter.check_quota(user_id='1.2.3.4', scene='x')

    def test_calls_quota_exceeded_raises(self):
        os.environ['QUANTIA_AI_RATE_CALLS_PER_HOUR'] = '60'
        with mock.patch('quantia.lib.ai.rate_limiter.mdb.executeSqlFetch',
                        return_value=[(60, 0)]):
            with self.assertRaises(RateLimitError) as ctx:
                rate_limiter.check_quota(user_id='1.2.3.4', scene='x')
            self.assertIn('60/60', str(ctx.exception))

    def test_tokens_quota_exceeded_raises(self):
        os.environ['QUANTIA_AI_RATE_CALLS_PER_HOUR'] = '60'
        os.environ['QUANTIA_AI_RATE_TOKENS_PER_HOUR'] = '200000'
        with mock.patch('quantia.lib.ai.rate_limiter.mdb.executeSqlFetch',
                        return_value=[(5, 200_000)]):
            with self.assertRaises(RateLimitError):
                rate_limiter.check_quota(user_id='1.2.3.4', scene='x')

    def test_db_failure_fail_open(self):
        os.environ['QUANTIA_AI_RATE_CALLS_PER_HOUR'] = '60'
        with mock.patch('quantia.lib.ai.rate_limiter.mdb.executeSqlFetch',
                        side_effect=Exception('table missing')):
            # 不应抛异常（fail-open）
            rate_limiter.check_quota(user_id='1.2.3.4', scene='x')

    def test_dict_row_compatible(self):
        # torndb 通常返回 Row（dict-like）
        os.environ['QUANTIA_AI_RATE_CALLS_PER_HOUR'] = '10'
        with mock.patch('quantia.lib.ai.rate_limiter.mdb.executeSqlFetch',
                        return_value=[{'c': 10, 't': 0}]):
            with self.assertRaises(RateLimitError):
                rate_limiter.check_quota(user_id='1.2.3.4', scene='x')

    def test_query_excludes_repair_loop_records(self):
        # 验证 SQL 查询包含 JSON_EXTRACT(rate_limit_loop) 排除条件
        captured = {}

        def fake(sql, params):
            captured['sql'] = sql
            captured['params'] = params
            return [(0, 0)]

        os.environ['QUANTIA_AI_RATE_CALLS_PER_HOUR'] = '60'
        with mock.patch('quantia.lib.ai.rate_limiter.mdb.executeSqlFetch',
                        side_effect=fake):
            rate_limiter.check_quota(user_id='ip-1', scene='strategy_gen')
        self.assertIn('rate_limit_loop', captured['sql'])
        self.assertEqual(captured['params'], ('ip-1', 'strategy_gen'))


class RunChatIntegrationTests(_BaseEnv):
    """验证 run_chat / run_agent 在调用 provider 前先走限流检查。"""

    def test_run_chat_blocks_when_over_quota(self):
        from quantia.lib import ai as ai_mod
        os.environ['QUANTIA_AI_RATE_CALLS_PER_HOUR'] = '5'
        with mock.patch('quantia.lib.ai.rate_limiter.mdb.executeSqlFetch',
                        return_value=[(5, 0)]):
            with mock.patch.object(ai_mod, 'get_provider') as gp:
                with self.assertRaises(RateLimitError):
                    ai_mod.run_chat('hi', user_id='1.1.1.1', scene='strategy_gen')
                # provider 不应被构造
                gp.assert_not_called()

    def test_run_chat_with_loop_flag_skips_check(self):
        from quantia.lib import ai as ai_mod
        os.environ['QUANTIA_AI_RATE_CALLS_PER_HOUR'] = '5'

        class _FakeProvider:
            def chat(self, messages, **kw):
                from quantia.lib.ai.providers.base import ChatResult
                return ChatResult(content='ok', total_tokens=10)

        with mock.patch('quantia.lib.ai.rate_limiter.mdb.executeSqlFetch') as m, \
             mock.patch.object(ai_mod, 'get_provider', return_value=_FakeProvider()):
            os.environ['QUANTIA_AI_RATE_DISABLED'] = '1'  # 也跳过 audit DB 写入路径
            try:
                out = ai_mod.run_chat(
                    'hi', user_id='1.1.1.1', scene='strategy_gen',
                    rate_limit_loop=True,
                )
                self.assertEqual(out, 'ok')
                # rate_limit_loop=True 时不应触发 limiter 的 SQL 查询
                # （但 load_config 本身仍会查 cn_strategy_params，故只断言
                # 没有任何调用包含 cn_stock_ai_call_log）
                for call in m.call_args_list:
                    sql = call.args[0] if call.args else ''
                    self.assertNotIn('cn_stock_ai_call_log', sql)
            finally:
                del os.environ['QUANTIA_AI_RATE_DISABLED']


if __name__ == '__main__':
    unittest.main()
