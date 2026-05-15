#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M8 ConversationMemory + ChatHandler 历史接续测试。

不依赖真实 MySQL：
* 默认 inmem 后端测试 base 行为；
* DB 后端测试通过 mock executeSql/executeSqlFetch 验证 SQL；
* ChatHandler 集成测试通过 mock run_chat / get_memory 验证流程。
"""

from __future__ import annotations

import json
import os
import unittest
from unittest import mock

from quantia.lib.ai.memory import (
    Conversation, Message,
    estimate_tokens, estimate_messages_tokens, truncate_to_budget,
    get_memory, reset_memory_for_tests,
)
from quantia.lib.ai.memory.inmem import InMemoryConversationMemory


class TokenAndTruncateTests(unittest.TestCase):
    def test_estimate_tokens(self):
        self.assertEqual(estimate_tokens(''), 0)
        # 5 字符 / 2.5 = 2 tokens (向下取整后 max 1)
        self.assertEqual(estimate_tokens('hello'), 2)

    def test_truncate_keeps_system_head(self):
        msgs = [
            Message('system', 'sys'),
            Message('user', 'a' * 100),
            Message('assistant', 'b' * 100),
            Message('user', 'tail'),
        ]
        # max_tokens 极小，应只保留 head system + 最后一条
        kept = truncate_to_budget(msgs, max_tokens=5)
        self.assertEqual([m.role for m in kept], ['system', 'user'])
        self.assertEqual(kept[-1].content, 'tail')

    def test_truncate_preserves_when_under_budget(self):
        msgs = [Message('user', 'hi'), Message('assistant', 'ok')]
        self.assertEqual(len(truncate_to_budget(msgs, max_tokens=1000)), 2)

    def test_truncate_empty(self):
        self.assertEqual(truncate_to_budget([], max_tokens=100), [])


class InMemoryMemoryTests(unittest.TestCase):
    def setUp(self):
        self.m = InMemoryConversationMemory()

    def test_create_append_load_roundtrip(self):
        self.m.get_or_create('c1', scene='chat', user_id='u1')
        self.m.append('c1', 'user', 'hello world', scene='chat', user_id='u1')
        self.m.append('c1', 'assistant', 'hi back')
        loaded = self.m.load('c1', max_tokens=4000)
        self.assertEqual(len(loaded), 2)
        conv = self.m.get('c1')
        self.assertEqual(conv.title, 'hello world')
        self.assertGreater(conv.total_tokens, 0)

    def test_list_filter_by_user_and_scene(self):
        self.m.get_or_create('a', scene='chat', user_id='u1')
        self.m.get_or_create('b', scene='chat', user_id='u2')
        self.m.get_or_create('c', scene='strategy_gen', user_id='u1')
        self.assertEqual(
            sorted(c.conversation_id for c in self.m.list(user_id='u1')),
            ['a', 'c'])
        self.assertEqual(
            [c.conversation_id for c in self.m.list(scene='strategy_gen')],
            ['c'])

    def test_delete_and_rename(self):
        self.m.get_or_create('x', scene='chat', user_id='u')
        self.assertTrue(self.m.rename('x', '我的会话'))
        self.assertEqual(self.m.get('x').title, '我的会话')
        self.assertTrue(self.m.delete('x'))
        self.assertIsNone(self.m.get('x'))
        self.assertFalse(self.m.delete('x'))

    def test_lru_eviction(self):
        os.environ['QUANTIA_AI_MEMORY_MAX_CONVS'] = '12'
        try:
            m = InMemoryConversationMemory()
            for i in range(20):
                m.get_or_create(f'c{i}', scene='chat')
            self.assertLessEqual(len(m.list(limit=100)), 12)
        finally:
            del os.environ['QUANTIA_AI_MEMORY_MAX_CONVS']

    def test_load_unknown_returns_empty(self):
        self.assertEqual(self.m.load('nope', max_tokens=100), [])


class FactoryTests(unittest.TestCase):
    def setUp(self):
        reset_memory_for_tests(None)
        self._snap = os.environ.get('QUANTIA_AI_MEMORY_BACKEND')

    def tearDown(self):
        reset_memory_for_tests(None)
        if self._snap is None:
            os.environ.pop('QUANTIA_AI_MEMORY_BACKEND', None)
        else:
            os.environ['QUANTIA_AI_MEMORY_BACKEND'] = self._snap

    def test_factory_inmem(self):
        os.environ['QUANTIA_AI_MEMORY_BACKEND'] = 'inmem'
        mem = get_memory()
        self.assertIsInstance(mem, InMemoryConversationMemory)
        # singleton
        self.assertIs(mem, get_memory())

    def test_factory_db_falls_back_when_unavailable(self):
        os.environ['QUANTIA_AI_MEMORY_BACKEND'] = 'db'
        # 把 DbConversationMemory 类替换成会抛错的 stub，验证回退
        with mock.patch('quantia.lib.ai.memory.db.DbConversationMemory',
                        side_effect=RuntimeError('no db')):
            mem = get_memory()
        # 应该回退到 inmem
        self.assertIsInstance(mem, InMemoryConversationMemory)


class DbBackendSqlTests(unittest.TestCase):
    """验证 DbConversationMemory 的关键 SQL 拼装与 messages_json 序列化。"""

    def setUp(self):
        from quantia.lib.ai.memory import db as dbmod
        # 强制 _table_ready=True，避免每次 _ensure_table 触发 mdb 调用
        dbmod._table_ready = True

    def test_append_inserts_messages_json(self):
        from quantia.lib.ai.memory.db import DbConversationMemory
        captured = []

        def fake_fetch(sql, params):
            # get() 走 SELECT；首次返回空列表 = 不存在
            return []

        def fake_exec(sql, params):
            captured.append((sql, params))

        with mock.patch('quantia.lib.ai.memory.db.mdb.executeSqlFetch',
                        side_effect=fake_fetch), \
             mock.patch('quantia.lib.ai.memory.db.mdb.executeSql',
                        side_effect=fake_exec):
            mem = DbConversationMemory()
            mem.append('cid-1', 'user', 'hello', scene='chat', user_id='u1')

        # 至少发生过 INSERT (get_or_create) + UPDATE messages_json
        sqls = [s for s, _ in captured]
        self.assertTrue(any('INSERT INTO cn_stock_ai_conversation' in s for s in sqls))
        self.assertTrue(any('UPDATE cn_stock_ai_conversation' in s
                            and 'messages_json=%s' in s for s in sqls))
        # messages_json 参数应是 JSON 数组字符串
        upd = next(p for s, p in captured if 'messages_json=%s' in s)
        decoded = json.loads(upd[0])
        self.assertEqual(len(decoded), 1)
        self.assertEqual(decoded[0]['role'], 'user')
        self.assertEqual(decoded[0]['content'], 'hello')

    def test_get_parses_row(self):
        from quantia.lib.ai.memory.db import DbConversationMemory
        row = (
            1, 'cid-2', 'chat', 'general_assistant', 'title-x',
            json.dumps([{'role': 'user', 'content': 'hi', 'ts': 1.0}]),
            10, 'u9', None, None,
        )
        with mock.patch('quantia.lib.ai.memory.db.mdb.executeSqlFetch',
                        return_value=[row]):
            mem = DbConversationMemory()
            conv = mem.get('cid-2')
        self.assertEqual(conv.title, 'title-x')
        self.assertEqual(len(conv.messages), 1)
        self.assertEqual(conv.messages[0].content, 'hi')
        self.assertEqual(conv.user_id, 'u9')


class HandlerHistoryWiringTests(unittest.TestCase):
    """验证 ChatHandler 在线程池路径上把 history 透传到 _call_ai_blocking。"""

    def test_call_ai_blocking_passes_history_to_run_chat(self):
        from quantia.web import aiAssistantHandler as h
        from quantia.lib.ai.providers.base import ChatMessage

        captured = {}

        def fake_run_chat(prompt, **kw):
            captured.update(kw)
            captured['prompt'] = prompt
            return 'ok'

        # load_config 也会被调；mock 简化为返回带 .model 属性的 stub
        class _Cfg:
            provider = 'openai_compat'
            model = 'fake-model'

        with mock.patch('quantia.web.aiAssistantHandler.run_chat',
                        side_effect=fake_run_chat), \
             mock.patch('quantia.lib.ai.config.load_config', return_value=_Cfg()):
            history = [ChatMessage(role='user', content='earlier')]
            content, model = h._call_ai_blocking(
                'now', None, 'chat', None, '1.2.3.4',
                {}, False, history,
            )
        self.assertEqual(content, 'ok')
        self.assertEqual(model, 'fake-model')
        self.assertEqual(captured['history'], history)
        self.assertFalse(captured['rate_limit_loop'])


class RunChatHistoryBuildTests(unittest.TestCase):
    """验证 run_chat 的 history 参数被合并到 messages 列表。"""

    def test_run_chat_prepends_history_between_system_and_prompt(self):
        from quantia.lib import ai as ai_mod
        from quantia.lib.ai.providers.base import ChatMessage, ChatResult
        os.environ['QUANTIA_AI_RATE_DISABLED'] = '1'
        try:
            captured_msgs = {}

            class _FakeProvider:
                def chat(self, messages, **kw):
                    captured_msgs['msgs'] = messages
                    return ChatResult(content='reply', total_tokens=5)

            with mock.patch.object(ai_mod, 'get_provider',
                                    return_value=_FakeProvider()):
                history = [
                    ChatMessage(role='user', content='Q1'),
                    ChatMessage(role='assistant', content='A1'),
                ]
                out = ai_mod.run_chat(
                    'Q2', system='SYS', history=history,
                    user_id='1.1.1.1', scene='chat',
                )
                self.assertEqual(out, 'reply')
                roles = [m.role for m in captured_msgs['msgs']]
                self.assertEqual(roles, ['system', 'user', 'assistant', 'user'])
                self.assertEqual(captured_msgs['msgs'][0].content, 'SYS')
                self.assertEqual(captured_msgs['msgs'][-1].content, 'Q2')
        finally:
            del os.environ['QUANTIA_AI_RATE_DISABLED']


# ──────────────────────────────────────────────────────────────────────
# audit-fix-P0/P1/P2 回归测试
# ──────────────────────────────────────────────────────────────────────
class AuditFixesTests(unittest.TestCase):
    """覆盖 audit-fix-P0-1/P0-2/P1-4/P1-5/P2-7/P2-8/P3-13。"""

    def test_p0_1_db_append_holds_per_cid_lock_serializes_writes(self):
        """两次并发 append 不应丢消息（per-cid 锁）。"""
        from quantia.lib.ai.memory import db as dbmod
        dbmod._table_ready = True

        # 模拟一个简单的 in-memory DB 通过共享 dict
        store = {'msgs': '[]'}

        def fake_fetch(sql, params):
            if 'WHERE conversation_id' in sql:
                return [(1, 'cid', 'chat', None, None, store['msgs'], 0,
                         'u1', None, None)]
            return []

        def fake_exec(sql, params):
            if 'UPDATE' in sql and 'messages_json=%s' in sql:
                store['msgs'] = params[0]

        import threading
        from quantia.lib.ai.memory.db import DbConversationMemory

        with mock.patch('quantia.lib.ai.memory.db._ensure_table'), \
             mock.patch('quantia.lib.ai.memory.db.mdb.executeSqlFetch',
                        side_effect=fake_fetch), \
             mock.patch('quantia.lib.ai.memory.db.mdb.executeSql',
                        side_effect=fake_exec):
            mem = DbConversationMemory()
            errors = []

            def writer(role, content):
                try:
                    mem.append('cid', role, content,
                               scene='chat', user_id='u1')
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=writer,
                                         args=('user', f'msg-{i}'))
                       for i in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(errors, [])
            decoded = json.loads(store['msgs'])
            # 串行化保证：8 条 append 全部落库
            self.assertEqual(len(decoded), 8)

    def test_p1_4_get_or_create_recovers_from_unique_violation(self):
        from quantia.lib.ai.memory import db as dbmod
        dbmod._table_ready = True

        # 第一次 SELECT 返回空 → INSERT 抛 1062 → 第二次 SELECT 返回行
        existing_row = (1, 'cid', 'chat', 'agent-x', None,
                        '[]', 0, 'u1', None, None)
        select_returns = [[], [existing_row]]

        def fake_fetch(sql, params):
            return select_returns.pop(0) if select_returns else [existing_row]

        def fake_exec(sql, params):
            raise Exception('(1062, "Duplicate entry for key conversation_id")')

        from quantia.lib.ai.memory.db import DbConversationMemory
        with mock.patch('quantia.lib.ai.memory.db._ensure_table'), \
             mock.patch('quantia.lib.ai.memory.db.mdb.executeSqlFetch',
                        side_effect=fake_fetch), \
             mock.patch('quantia.lib.ai.memory.db.mdb.executeSql',
                        side_effect=fake_exec):
            mem = DbConversationMemory()
            conv = mem.get_or_create('cid', scene='chat', user_id='u1')
        self.assertEqual(conv.user_id, 'u1')
        self.assertEqual(conv.agent, 'agent-x')

    def test_p1_5_5round_context_accumulation_acceptance(self):
        """spec §13 #M8：5 轮上下文累积修改，最近若干轮在 budget 内可被加载。"""
        m = InMemoryConversationMemory()
        m.get_or_create('c1', scene='chat', user_id='u1')
        for i in range(5):
            m.append('c1', 'user', f'问题{i}: ' + 'x' * 10)
            m.append('c1', 'assistant', f'回答{i}: ' + 'y' * 10)
        # 至少能一字不漏地加载最近 5 轮的最后 1 条
        loaded = m.load('c1', max_tokens=10000)
        self.assertEqual(len(loaded), 10)
        roles = [x.role for x in loaded]
        self.assertEqual(roles, ['user', 'assistant'] * 5)
        self.assertEqual(loaded[-1].content, '回答4: ' + 'y' * 10)
        # 极小预算时也至少保留最后一条（P2-7）
        loaded_small = m.load('c1', max_tokens=1)
        self.assertEqual(len(loaded_small), 1)

    def test_p2_7_truncate_keeps_last_when_single_message_exceeds_budget(self):
        from quantia.lib.ai.memory.base import (
            Message as Msg, truncate_to_budget,
        )
        msgs = [Msg('user', 'x' * 10000)]  # 单条远超
        kept = truncate_to_budget(msgs, max_tokens=10)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].content, msgs[0].content)

    def test_p2_8_inmem_caps_messages_per_conversation(self):
        os.environ['QUANTIA_AI_MEMORY_MAX_CONVS'] = '50'
        try:
            m = InMemoryConversationMemory()
            m.get_or_create('c1', scene='chat')
            for i in range(250):
                m.append('c1', 'user', f'msg{i}')
            conv = m.get('c1')
            # 上限为 _MAX_MSGS_PER_CONV=200
            self.assertLessEqual(len(conv.messages), 200)
            # 最后一条应被保留
            self.assertEqual(conv.messages[-1].content, 'msg249')
        finally:
            del os.environ['QUANTIA_AI_MEMORY_MAX_CONVS']

    def test_p3_13_role_whitelist_in_from_dict(self):
        from quantia.lib.ai.memory.base import Message as Msg
        m1 = Msg.from_dict({'role': '<script>', 'content': 'x'})
        self.assertEqual(m1.role, 'user')
        for ok in ('system', 'user', 'assistant', 'tool'):
            self.assertEqual(Msg.from_dict({'role': ok, 'content': ''}).role, ok)

    def test_audit2_p1c_inmem_append_coerces_role(self):
        """直接 append('<script>', ...) 也必须被白名单拒收（不只是 from_dict）。"""
        m = InMemoryConversationMemory()
        m.get_or_create('c-evil', scene='chat')
        m.append('c-evil', '<img onerror=x>', 'pwn')
        m.append('c-evil', 'system', 'ok')
        conv = m.get('c-evil')
        roles = [x.role for x in conv.messages]
        self.assertEqual(roles, ['user', 'system'])

    def test_audit2_p0a_cid_lock_returns_same_object_for_concurrent_callers(self):
        """WeakValueDictionary 在锁仍被持有时不应回收，并发请求拿到同一把锁。"""
        from quantia.lib.ai.memory.db import _get_cid_lock
        l1 = _get_cid_lock('cid-z')
        l2 = _get_cid_lock('cid-z')
        self.assertIs(l1, l2)
        # 释放强引用 → 可被弱引用字典回收
        del l1, l2
        import gc
        gc.collect()
        # 重新取应该是新对象（旧的已被 GC），但仍然可用
        l3 = _get_cid_lock('cid-z')
        with l3:
            pass
        self.assertIsNotNone(l3)


if __name__ == '__main__':
    unittest.main()
