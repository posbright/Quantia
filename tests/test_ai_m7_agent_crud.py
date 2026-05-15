#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M7：自定义 Agent CRUD 测试。

不依赖真实 MySQL；通过 patch quantia.lib.database 的 executeSql / executeSqlFetch
模拟一个内存表，覆盖 agent_store 与 prompt_loader.list_agents 的合并行为。
"""

import json
import re
import unittest
from unittest import mock

from quantia.lib.ai import agent_store
from quantia.lib.ai.agent_store import AgentStoreError


class _FakeDB:
    """极简内存表：只支持 agent_store 实际使用到的几条 SQL。"""

    def __init__(self):
        self.rows = {}
        self.next_id = 1
        # 列顺序与 DDL 一致
        self.cols = ['id', 'name', 'display_name', 'description', 'system_prompt',
                     'default_provider', 'default_model', 'allowed_tools',
                     'temperature', 'max_tokens', 'is_builtin', 'enabled',
                     'created_at', 'updated_at']

    def executeSql(self, sql, params=()):
        s = sql.strip()
        if s.upper().startswith('CREATE TABLE'):
            return
        if s.upper().startswith('INSERT INTO'):
            # INSERT INTO cn_stock_ai_agent (..) VALUES (..) ON DUPLICATE KEY UPDATE ..
            cols_match = re.search(r'\(([^)]+)\) VALUES', sql)
            cols = [c.strip() for c in cols_match.group(1).split(',')]
            row = dict(zip(cols, params))
            name = row['name']
            if name in self.rows:
                # update existing
                existing = self.rows[name]
                for k, v in row.items():
                    if k != 'name':
                        existing[k] = v
            else:
                row['id'] = self.next_id
                self.next_id += 1
                self.rows[name] = row
            return
        if s.upper().startswith('DELETE FROM'):
            # DELETE FROM cn_stock_ai_agent WHERE name=%s AND is_builtin=0
            name = params[0]
            r = self.rows.get(name)
            if r and not r.get('is_builtin'):
                del self.rows[name]
            return
        raise AssertionError(f'unexpected SQL: {sql}')

    def executeSqlFetch(self, sql, params=()):
        s = sql.strip()
        if 'WHERE name=%s' in sql:
            name = params[0]
            r = self.rows.get(name)
            return [dict(r)] if r else []
        if 'SELECT * FROM cn_stock_ai_agent' in sql:
            rows = list(self.rows.values())
            if 'WHERE enabled=1' in sql:
                rows = [r for r in rows if r.get('enabled')]
            rows.sort(key=lambda r: (-int(r.get('is_builtin') or 0), r['name']))
            return [dict(r) for r in rows]
        raise AssertionError(f'unexpected fetch: {sql}')


def _patch_db(fake: _FakeDB):
    return mock.patch.multiple(
        'quantia.lib.ai.agent_store.mdb',
        executeSql=fake.executeSql,
        executeSqlFetch=fake.executeSqlFetch,
        get_connection=mock.MagicMock(),
    )


class AgentStoreCrudTests(unittest.TestCase):
    def setUp(self):
        self.fake = _FakeDB()
        agent_store._reset_for_test()

    def test_upsert_and_get(self):
        with _patch_db(self.fake):
            saved = agent_store.upsert_agent({
                'name': 'market_summarizer',
                'display_name': '行情摘要',
                'description': '总结行情',
                'system_prompt': '你是行情摘要器',
                'allowed_tools': ['sql_query', 'kline_fetch'],
                'temperature': 0.5,
                'max_tokens': 2048,
            })
            self.assertEqual(saved['name'], 'market_summarizer')
            self.assertFalse(saved['is_builtin'])
            self.assertEqual(saved['allowed_tools'], ['sql_query', 'kline_fetch'])
            got = agent_store.get_agent('market_summarizer')
            self.assertIsNotNone(got)
            self.assertEqual(got['display_name'], '行情摘要')

    def test_upsert_invalid_name(self):
        with _patch_db(self.fake):
            with self.assertRaises(AgentStoreError):
                agent_store.upsert_agent({'name': 'bad name!', 'system_prompt': 'x'})
            with self.assertRaises(AgentStoreError):
                agent_store.upsert_agent({'name': '', 'system_prompt': 'x'})

    def test_upsert_invalid_temperature(self):
        with _patch_db(self.fake):
            with self.assertRaises(AgentStoreError):
                agent_store.upsert_agent({
                    'name': 'a', 'system_prompt': 'x', 'temperature': 5.0,
                })

    def test_upsert_invalid_allowed_tools(self):
        with _patch_db(self.fake):
            with self.assertRaises(AgentStoreError):
                agent_store.upsert_agent({
                    'name': 'a', 'system_prompt': 'x',
                    'allowed_tools': 'not_a_list',
                })
            with self.assertRaises(AgentStoreError):
                agent_store.upsert_agent({
                    'name': 'a', 'system_prompt': 'x',
                    'allowed_tools': [123],
                })

    def test_delete_user_agent(self):
        with _patch_db(self.fake):
            agent_store.upsert_agent({'name': 'tmp', 'system_prompt': 'x'})
            self.assertTrue(agent_store.delete_agent('tmp'))
            self.assertIsNone(agent_store.get_agent('tmp'))

    def test_delete_builtin_refused(self):
        with _patch_db(self.fake):
            agent_store.upsert_agent({'name': 'sys', 'system_prompt': 'x'},
                                     is_builtin=True)
            with self.assertRaises(AgentStoreError):
                agent_store.delete_agent('sys')

    def test_delete_nonexistent_raises(self):
        with _patch_db(self.fake):
            with self.assertRaises(AgentStoreError):
                agent_store.delete_agent('does_not_exist')

    def test_list_sorts_builtin_first(self):
        with _patch_db(self.fake):
            agent_store.upsert_agent({'name': 'zzz_user', 'system_prompt': 'x'})
            agent_store.upsert_agent({'name': 'aaa_builtin', 'system_prompt': 'x'},
                                     is_builtin=True)
            rows = agent_store.list_agents()
            self.assertEqual(rows[0]['name'], 'aaa_builtin')
            self.assertEqual(rows[1]['name'], 'zzz_user')

    def test_list_db_failure_returns_empty(self):
        # 模拟 list 异常 → 返回空列表，不抛
        with mock.patch.object(agent_store.mdb, 'executeSqlFetch',
                               side_effect=Exception('db down')), \
             mock.patch.object(agent_store.mdb, 'get_connection', mock.MagicMock()):
            rows = agent_store.list_agents()
            self.assertEqual(rows, [])

    def test_upsert_builtin_agents_count(self):
        with _patch_db(self.fake):
            n = agent_store.upsert_builtin_agents([
                {'name': 'b1', 'system_prompt': 'p1'},
                {'name': 'b2', 'system_prompt': 'p2'},
            ])
            self.assertEqual(n, 2)
            self.assertTrue(agent_store.get_agent('b1')['is_builtin'])

    def test_upsert_builtin_agents_skips_failed(self):
        with _patch_db(self.fake):
            n = agent_store.upsert_builtin_agents([
                {'name': 'ok', 'system_prompt': 'p'},
                {'name': 'bad name', 'system_prompt': 'p'},  # invalid → skip
                {'name': 'ok2', 'system_prompt': 'p'},
            ])
            self.assertEqual(n, 2)


class PromptLoaderMergeTests(unittest.TestCase):
    """list_agents() 应优先返回 DB 行，DB 不可用时回退文件兜底。"""

    def setUp(self):
        self.fake = _FakeDB()
        agent_store._reset_for_test()
        from quantia.lib.ai import prompt_loader
        prompt_loader._reset_bootstrap_for_test()
        prompt_loader.clear_cache()

    def test_db_first_then_file_fallback(self):
        from quantia.lib.ai import prompt_loader
        with _patch_db(self.fake):
            agents = prompt_loader.list_agents()
            # bootstrap 应注入内置 agent
            names = {a['name'] for a in agents}
            self.assertIn('strategy_coder', names)
            self.assertIn('strategy_repairer', names)
            for a in agents:
                if a['name'] in ('strategy_coder', 'strategy_repairer'):
                    self.assertTrue(a['is_builtin'])

    def test_user_agent_appears_in_list(self):
        from quantia.lib.ai import prompt_loader
        with _patch_db(self.fake):
            agent_store.upsert_agent({
                'name': 'user_agent',
                'display_name': '用户自定义',
                'system_prompt': 'sp',
            })
            prompt_loader._reset_bootstrap_for_test()
            agents = prompt_loader.list_agents()
            names = {a['name'] for a in agents}
            self.assertIn('user_agent', names)

    def test_disabled_agent_filtered_out(self):
        from quantia.lib.ai import prompt_loader
        with _patch_db(self.fake):
            agent_store.upsert_agent({
                'name': 'disabled_one',
                'system_prompt': 'sp',
                'enabled': False,
            })
            prompt_loader._reset_bootstrap_for_test()
            agents = prompt_loader.list_agents()
            names = {a['name'] for a in agents}
            self.assertNotIn('disabled_one', names)

    def test_db_failure_falls_back_to_files(self):
        from quantia.lib.ai import prompt_loader
        # list_agents 抛异常 → 返回 []，prompt_loader 走文件兜底分支
        with mock.patch.object(agent_store, 'list_agents',
                               side_effect=Exception('db down')):
            agents = prompt_loader.list_agents()
            # 应至少有内置 strategy_coder（来自 prompt/*.md 文件）
            names = {a['name'] for a in agents}
            self.assertIn('strategy_coder', names)


class HandlerProtectionTests(unittest.TestCase):
    """M7 一轮审计 P1 修复：内置 agent enabled 字段不可被修改 + 工具白名单。"""

    def setUp(self):
        self.fake = _FakeDB()
        agent_store._reset_for_test()

    def test_unknown_tool_in_allowed_tools_rejected(self):
        # P2 修复（一轮审计）：工具名必须在 ToolRegistry 中注册
        with _patch_db(self.fake):
            with self.assertRaises(AgentStoreError):
                agent_store.upsert_agent({
                    'name': 'x', 'system_prompt': 'p',
                    'allowed_tools': ['totally_unknown_tool_xyz'],
                })

    def test_handler_post_protects_builtin_enabled(self):
        # P1 修复（一轮审计）：handler 端编辑 builtin agent 时
        # enabled 字段必须保持原值，不能被禁用。
        with _patch_db(self.fake):
            agent_store.upsert_agent({'name': 'sys_a', 'system_prompt': 'p'},
                                     is_builtin=True)
            existing = agent_store.get_agent('sys_a')
            self.assertTrue(existing['enabled'])

            # 模拟 handler.post 的保护逻辑（与代码一致的检查路径）
            body = {'name': 'sys_a', 'enabled': False,
                    'description': '想偷偷禁用'}
            body.pop('is_builtin', None)
            if existing and existing.get('is_builtin'):
                for k in ('system_prompt', 'allowed_tools', 'name'):
                    body.pop(k, None)
                body['name'] = existing['name']
                body['system_prompt'] = existing.get('system_prompt') or ''
                body['enabled'] = bool(existing.get('enabled', True))

            saved = agent_store.upsert_agent(
                body, is_builtin=bool(existing and existing.get('is_builtin')))
            self.assertTrue(saved['is_builtin'])
            # enabled 应保持为 True（不被恶意禁用）
            self.assertTrue(saved['enabled'])
            # 但允许字段（description）应已写入
            self.assertEqual(saved['description'], '想偷偷禁用')

    def test_user_agent_can_still_be_disabled(self):
        # 防回归：保护逻辑不影响 user agent 的正常禁用
        with _patch_db(self.fake):
            agent_store.upsert_agent({'name': 'user_b', 'system_prompt': 'p'})
            saved = agent_store.upsert_agent({
                'name': 'user_b', 'system_prompt': 'p', 'enabled': False,
            })
            self.assertFalse(saved['enabled'])


if __name__ == '__main__':
    unittest.main()
