#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M9 知识库索引器（spec §11.2 / §16.8）。

来源：
- template: quantia.web.portfolioBacktestHandler.STRATEGY_TEMPLATES
- doc:      document/*.md（顶层、限制大小）
- strategy: cn_stock_strategy_code（用户保存策略，可选）
- failure:  cn_stock_backtest_portfolio status='failed' 的 error_message（可选）

幂等：按 (source_type, source_id) UNIQUE upsert。
入口：python -m quantia.lib.ai.retrieval.indexer
     或者 cron/cron.workdayly/refresh_ai_kb 调用 run_indexer()
"""

from __future__ import annotations

import logging
import os
from typing import Dict, List, Tuple

from quantia.lib.ai.retrieval.db import KbStore

_DOC_DIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', '..', '..', '..', 'document'))
# audit-fix-2-P2: 这里是“读取后的字符上限”（text mode read 返回 chars）；
# 文件字节上限另外用 os.path.getsize() 预检，避免读超大文件。
_DOC_MAX_CHARS = 200_000
_STRATEGY_LIMIT = 200      # 最近 N 条用户策略
_FAILURE_LIMIT = 100       # 最近 N 条失败回测


def _index_templates(store: KbStore) -> int:
    try:
        from quantia.web.portfolioBacktestHandler import STRATEGY_TEMPLATES
    except Exception as exc:
        logging.warning(f'[ai.retrieval.indexer.templates] import 失败: {exc}')
        return 0
    # audit-fix-2-P2: 空源不应抹掎旧表 —— 防重构后 STRATEGY_TEMPLATES 意外为空导致清库
    if not STRATEGY_TEMPLATES:
        logging.info('[ai.retrieval.indexer.templates] STRATEGY_TEMPLATES 为空，跳过。')
        return 0
    # audit-fix-1-P2: 模板源是闭集（代码里写死的 STRATEGY_TEMPLATES），
    # 重建前清掉旧 template 行，避免删除 / 改名后旧条目残留。
    try:
        store.delete_by_type('template')
    except Exception as exc:
        logging.warning(f'[ai.retrieval.indexer.templates.prune] {exc}')
    n = 0
    for tpl in STRATEGY_TEMPLATES or []:
        if not isinstance(tpl, dict):
            continue
        sid = str(tpl.get('id') or '').strip()
        if not sid:
            continue
        title = str(tpl.get('name') or sid)
        desc = str(tpl.get('description') or '')
        code = str(tpl.get('code') or '')
        content = (
            f'{title}\n\n'
            f'描述：{desc}\n\n'
            f'代码：\n{code}'
        )
        if store.upsert('template', sid, title, content):
            n += 1
    return n


def _index_docs(store: KbStore) -> int:
    if not os.path.isdir(_DOC_DIR):
        logging.info(f'[ai.retrieval.indexer.docs] 跳过：{_DOC_DIR} 不存在')
        return 0
    n = 0
    # audit-fix-1-P3: 递归扫 document/ 下所有 .md（包括子目录）
    for root, dirs, files in os.walk(_DOC_DIR):
        # audit-fix-2-P3: 原地排序 dirs/files，使递归顺序在各平台上一致
        dirs.sort()
        for fname in sorted(files):
            if not fname.lower().endswith('.md'):
                continue
            fpath = os.path.join(root, fname)
            try:
                # audit-fix-1-P2: size + read 放同一 try 里，避免中间文件被改后读取异常裸露
                if os.path.getsize(fpath) > _DOC_MAX_CHARS:
                    # 按字节预检（UTF-8 中文 1 字 ≈ 3 字节，实际允许的文件还会更大）
                    continue
                with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                    body = f.read(_DOC_MAX_CHARS + 1)
                if len(body) > _DOC_MAX_CHARS:
                    body = body[:_DOC_MAX_CHARS]
            except OSError as exc:
                logging.warning(f'[ai.retrieval.indexer.docs] {fname}: {exc}')
                continue
            # source_id 用相对 _DOC_DIR 的 POSIX 路径，避免同名冲突
            rel = os.path.relpath(fpath, _DOC_DIR).replace(os.sep, '/')
            title = rel[:-3]   # 去 .md
            if store.upsert('doc', rel, title, body):
                n += 1
    return n


def _index_strategies(store: KbStore) -> int:
    try:
        import quantia.lib.database as mdb
        rows = mdb.executeSqlFetch(
            'SELECT id, name, description, code FROM cn_stock_strategy_code '
            'ORDER BY id DESC LIMIT %s', (_STRATEGY_LIMIT,))
    except Exception as exc:
        logging.info(f'[ai.retrieval.indexer.strategies] 跳过: {exc}')
        return 0
    n = 0
    for r in rows or []:
        if isinstance(r, (list, tuple)):
            rid, name, desc, code = r[0], r[1], r[2], r[3]
        else:
            rid = r.get('id'); name = r.get('name')
            desc = r.get('description'); code = r.get('code')
        sid = f's{rid}'
        title = str(name or sid)
        content = f'{title}\n\n描述：{desc or ""}\n\n代码：\n{code or ""}'
        if store.upsert('strategy', sid, title, content):
            n += 1
    return n


def _index_failures(store: KbStore) -> int:
    try:
        import quantia.lib.database as mdb
        # audit-fix-1-P0: 表列名是 strategy_name，不是 task_name
        rows = mdb.executeSqlFetch(
            'SELECT id, strategy_name, error_message FROM cn_stock_backtest_portfolio '
            "WHERE status='failed' AND error_message IS NOT NULL "
            'ORDER BY id DESC LIMIT %s', (_FAILURE_LIMIT,))
    except Exception as exc:
        logging.info(f'[ai.retrieval.indexer.failures] 跳过: {exc}')
        return 0
    n = 0
    for r in rows or []:
        if isinstance(r, (list, tuple)):
            rid, name, err = r[0], r[1], r[2]
        else:
            rid = r.get('id'); name = r.get('strategy_name'); err = r.get('error_message')
        if not err:
            continue
        sid = f'f{rid}'
        title = str(name or sid)[:255]
        content = f'失败用例：{title}\n\n错误：\n{err}'
        if store.upsert('backtest_failure', sid, title, content):
            n += 1
    return n


def run_indexer(*, sources: List[str] = None) -> Dict[str, int]:
    """跑全部或指定来源的索引，返回 {source: count}。"""
    sources = sources or ['template', 'doc', 'strategy', 'backtest_failure']
    store = KbStore()
    runners: List[Tuple[str, callable]] = [
        ('template', _index_templates),
        ('doc', _index_docs),
        ('strategy', _index_strategies),
        ('backtest_failure', _index_failures),
    ]
    out: Dict[str, int] = {}
    for name, fn in runners:
        if name not in sources:
            continue
        try:
            out[name] = fn(store)
        except Exception as exc:
            logging.exception(f'[ai.retrieval.indexer] {name} 异常: {exc}')
            out[name] = 0
    return out


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s')
    res = run_indexer()
    total = sum(res.values())
    print(f'[ai.kb.indexer] done: {res} (total={total})')
