#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M9 RAG / 知识库检索模块。

公开 API：
- KbStore: cn_stock_ai_kb 上的 upsert / search（FULLTEXT + LIKE 兜底）
- run_indexer: 扫描 STRATEGY_TEMPLATES + document/*.md + cn_stock_strategy_code +
  失败用例，切片入表（idempotent，按 (source_type, source_id) upsert）
"""

from quantia.lib.ai.retrieval.db import KbStore, KbDoc  # noqa: F401


def __getattr__(name):
    """延迟导入 indexer，避免 python -m 执行时触发 RuntimeWarning。"""
    if name == 'run_indexer':
        from quantia.lib.ai.retrieval.indexer import run_indexer
        return run_indexer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ['KbStore', 'KbDoc', 'run_indexer']
