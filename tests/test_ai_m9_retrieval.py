#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M9 RAG / kb_search 测试。

所有 MySQL 调用 mock，不依赖真实数据库。
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

# 防止 retrieval/db 在 import 时尝试连 MySQL（_ensure_table 由实例化触发，不是 import）
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


class KbStoreTests(unittest.TestCase):
    def setUp(self):
        from quantia.lib.ai.retrieval import db as kbdb
        kbdb._table_ready = True

    def test_upsert_truncates_and_calls_insert(self):
        from quantia.lib.ai.retrieval.db import KbStore, _MAX_CONTENT_CHARS
        captured = {}

        def fake_exec(sql, params):
            captured['sql'] = sql
            captured['params'] = params

        with mock.patch('quantia.lib.ai.retrieval.db.mdb.executeSql',
                        side_effect=fake_exec):
            s = KbStore()
            ok = s.upsert('template', 'boll', 'T' * 500,
                           'C' * (_MAX_CONTENT_CHARS + 1000))
        self.assertTrue(ok)
        self.assertIn('ON DUPLICATE KEY UPDATE', captured['sql'])
        stype, sid, title, content = captured['params']
        self.assertEqual(stype, 'template')
        self.assertEqual(sid, 'boll')
        self.assertEqual(len(title), 255)
        self.assertEqual(len(content), _MAX_CONTENT_CHARS)

    def test_upsert_rejects_empty_source_type(self):
        from quantia.lib.ai.retrieval.db import KbStore
        with mock.patch('quantia.lib.ai.retrieval.db.mdb.executeSql'):
            s = KbStore()
            with self.assertRaises(ValueError):
                s.upsert('', 'x', 't', 'c')

    def test_search_fulltext_hit(self):
        """纯英文查询走 FULLTEXT 主路径。"""
        from quantia.lib.ai.retrieval.db import KbStore
        rows = [
            ('template', 'boll', 'BOLL Lower Band', 'BOLL lower band buy strategy ...',
             '2026-05-12 10:00:00', 1.5),
            ('template', 'dual_ma', 'Dual MA', '5-day 20-day golden cross ...',
             '2026-05-12 09:00:00', 0.7),
        ]
        with mock.patch('quantia.lib.ai.retrieval.db.mdb.executeSqlFetch',
                        return_value=rows):
            s = KbStore()
            docs = s.search('BOLL lower band', top_k=5)
        self.assertEqual(len(docs), 2)
        self.assertEqual(docs[0].source_id, 'boll')
        self.assertGreater(docs[0].score, docs[1].score)
        self.assertIn('BOLL', docs[0].snippet)

    def test_search_cjk_uses_like_as_primary(self):
        """audit-fix-1-P2: 中文查询直接走 LIKE，不发 FULLTEXT。"""
        from quantia.lib.ai.retrieval.db import KbStore
        sql_seen = []

        def fake_fetch(sql, params):
            sql_seen.append(sql)
            # LIKE 路径返回 5 列（无 score）
            return [('template', 'boll', '布林带下轨', '布林带 布林带 下轨 ...',
                     '2026-05-12 10:00:00')]

        with mock.patch('quantia.lib.ai.retrieval.db.mdb.executeSqlFetch',
                        side_effect=fake_fetch):
            s = KbStore()
            docs = s.search('布林带 下轨', top_k=3)
        self.assertEqual(len(docs), 1)
        # 只调了一次 SQL，必须是 LIKE 而不是 MATCH AGAINST
        self.assertEqual(len(sql_seen), 1)
        self.assertIn('LIKE', sql_seen[0])
        self.assertNotIn('MATCH', sql_seen[0])

    def test_search_falls_back_to_like_when_fulltext_empty(self):
        """英文查询 FULLTEXT 返回空 → LIKE 兑底。"""
        from quantia.lib.ai.retrieval.db import KbStore
        rows_like = [
            ('template', 'boll', 'BOLL Lower', 'BOLL lower lower band ...',
             '2026-05-12 10:00:00'),
        ]
        # 第 1 次（FULLTEXT）返回空；第 2 次（LIKE）返回 rows_like
        seq = [[], rows_like]

        def fake_fetch(sql, params):
            return seq.pop(0) if seq else []

        with mock.patch('quantia.lib.ai.retrieval.db.mdb.executeSqlFetch',
                        side_effect=fake_fetch):
            s = KbStore()
            docs = s.search('BOLL', top_k=3)
        self.assertEqual(len(docs), 1)
        # LIKE 模式下 score = 命中次数
        self.assertGreaterEqual(docs[0].score, 1.0)

    def test_search_filters_by_source_types(self):
        from quantia.lib.ai.retrieval.db import KbStore
        captured = {}

        def fake_fetch(sql, params):
            captured.setdefault('sqls', []).append(sql)
            captured.setdefault('params', []).append(params)
            return []

        with mock.patch('quantia.lib.ai.retrieval.db.mdb.executeSqlFetch',
                        side_effect=fake_fetch):
            s = KbStore()
            s.search('x', source_types=['template', 'doc'])
        # FULLTEXT + LIKE 两次 SQL 都应包含 source_type IN
        self.assertTrue(all('source_type IN' in q for q in captured['sqls']))
        # template/doc 应出现在 params 里（位置依实现而定，宽松匹配）
        flat = [v for tpl in captured['params'] for v in tpl]
        self.assertIn('template', flat)
        self.assertIn('doc', flat)

    def test_empty_query_returns_empty(self):
        from quantia.lib.ai.retrieval.db import KbStore
        with mock.patch('quantia.lib.ai.retrieval.db.mdb.executeSqlFetch'):
            s = KbStore()
            self.assertEqual(s.search(''), [])
            self.assertEqual(s.search('   '), [])


class KbSearchToolTests(unittest.TestCase):
    def setUp(self):
        from quantia.lib.ai.retrieval import db as kbdb
        kbdb._table_ready = True

    def test_tool_schema_exposes_kb_search(self):
        from quantia.lib.ai.tools import get_registry, reset_registry
        reset_registry()
        reg = get_registry()
        self.assertIn('kb_search', reg.list_names())
        schema = reg.get('kb_search').schema()
        self.assertEqual(schema['function']['name'], 'kb_search')
        params = schema['function']['parameters']
        self.assertIn('query', params['properties'])
        self.assertIn('source_types', params['properties'])

    def test_tool_run_returns_results(self):
        from quantia.lib.ai.tools.kb_search import KbSearchTool
        # CJK 查询走 LIKE 主路径，5 列无 score
        with mock.patch('quantia.lib.ai.retrieval.db.mdb.executeSqlFetch',
                        return_value=[
                            ('template', 'boll', '布林带', '布林带下轨买入',
                             '2026-05-12 10:00:00'),
                        ]):
            out = KbSearchTool().run({'query': '布林带', 'top_k': 3})
        self.assertIn('results', out)
        self.assertEqual(out['results'][0]['source_id'], 'boll')

    def test_tool_rejects_empty_query(self):
        from quantia.lib.ai.tools import ToolError
        from quantia.lib.ai.tools.kb_search import KbSearchTool
        with self.assertRaises(ToolError):
            KbSearchTool().run({'query': ''})

    def test_tool_rejects_invalid_source_types(self):
        from quantia.lib.ai.tools import ToolError
        from quantia.lib.ai.tools.kb_search import KbSearchTool
        with self.assertRaises(ToolError):
            KbSearchTool().run({'query': 'x', 'source_types': ['evil']})

    def test_tool_caps_top_k(self):
        from quantia.lib.ai.tools.kb_search import KbSearchTool
        with mock.patch('quantia.lib.ai.retrieval.db.mdb.executeSqlFetch',
                        return_value=[]) as p:
            KbSearchTool().run({'query': 'x', 'top_k': 999})
        # 实际传给 SQL 的 LIMIT 必须 ≤ 10
        last_params = p.call_args_list[0][0][1]
        # FULLTEXT 调用：(q, q, top_k)
        self.assertLessEqual(last_params[-1], 10)


class IndexerTests(unittest.TestCase):
    def setUp(self):
        from quantia.lib.ai.retrieval import db as kbdb
        kbdb._table_ready = True

    def test_run_indexer_template_path(self):
        from quantia.lib.ai.retrieval import indexer

        upserts = []

        class FakeStore:
            def upsert(self, source_type, source_id, title, content):
                upserts.append((source_type, source_id, title, len(content)))
                return True

        # 只跑 template，跳过 doc/strategy/failure
        with mock.patch('quantia.lib.ai.retrieval.indexer.KbStore',
                        return_value=FakeStore()):
            res = indexer.run_indexer(sources=['template'])
        self.assertIn('template', res)
        self.assertGreater(res['template'], 0)
        self.assertTrue(all(t == 'template' for t, *_ in upserts))

    def test_indexer_skips_missing_doc_dir(self):
        from quantia.lib.ai.retrieval import indexer
        with mock.patch.object(indexer, '_DOC_DIR', '/no/such/dir'):
            with mock.patch('quantia.lib.ai.retrieval.indexer.KbStore'):
                res = indexer.run_indexer(sources=['doc'])
        self.assertEqual(res.get('doc', 0), 0)

    def test_indexer_swallows_strategy_db_errors(self):
        from quantia.lib.ai.retrieval import indexer
        with mock.patch('quantia.lib.ai.retrieval.indexer.KbStore'):
            with mock.patch('quantia.lib.database.executeSqlFetch',
                            side_effect=Exception('no mysql')):
                res = indexer.run_indexer(
                    sources=['strategy', 'backtest_failure'])
        self.assertEqual(res.get('strategy', 0), 0)
        self.assertEqual(res.get('backtest_failure', 0), 0)

    def test_audit1_p0_failures_query_uses_strategy_name_column(self):
        """audit-fix-1-P0: 列名应为 strategy_name 而非 task_name。"""
        from quantia.lib.ai.retrieval import indexer
        captured = {}

        def fake_fetch(sql, params):
            captured['sql'] = sql
            return []

        with mock.patch('quantia.lib.ai.retrieval.indexer.KbStore'):
            with mock.patch('quantia.lib.database.executeSqlFetch',
                            side_effect=fake_fetch):
                indexer.run_indexer(sources=['backtest_failure'])
        self.assertIn('strategy_name', captured.get('sql', ''))
        self.assertNotIn('task_name', captured.get('sql', ''))

    def test_audit1_p2_template_indexer_prunes_stale_entries(self):
        """audit-fix-1-P2: 模板索引前应清掉旧 template 行；
        audit-fix-2-P3: delete 必须发生在 upsert 之前。"""
        from quantia.lib.ai.retrieval import indexer

        calls = []

        class FakeStore:
            def delete_by_type(self, t):
                calls.append(('delete', t))
                return 1

            def upsert(self, *a, **kw):
                calls.append(('upsert', a[0] if a else None))
                return True

        with mock.patch('quantia.lib.ai.retrieval.indexer.KbStore',
                        return_value=FakeStore()):
            indexer.run_indexer(sources=['template'])
        # 至少有 1 次 delete + ≥1 次 upsert，且 delete 必须先于所有 upsert
        kinds = [c[0] for c in calls]
        self.assertIn('delete', kinds)
        self.assertIn('upsert', kinds)
        self.assertEqual(kinds[0], 'delete')
        self.assertTrue(all(k == 'upsert' for k in kinds[1:]))

    def test_audit2_p2_empty_templates_skips_prune(self):
        """audit-fix-2-P2: STRATEGY_TEMPLATES 为空时不能调 delete_by_type
        （否则会抹平整张表）。"""
        from quantia.lib.ai.retrieval import indexer

        calls = []

        class FakeStore:
            def delete_by_type(self, t):
                calls.append(('delete', t))
                return 1

            def upsert(self, *a, **kw):
                calls.append(('upsert', a[0] if a else None))
                return True

        with mock.patch.object(
                __import__('quantia.web.portfolioBacktestHandler',
                            fromlist=['STRATEGY_TEMPLATES']),
                'STRATEGY_TEMPLATES', []):
            with mock.patch('quantia.lib.ai.retrieval.indexer.KbStore',
                            return_value=FakeStore()):
                res = indexer.run_indexer(sources=['template'])
        self.assertEqual(res.get('template'), 0)
        self.assertEqual(calls, [])  # 既不 delete 也不 upsert


if __name__ == '__main__':
    unittest.main()
