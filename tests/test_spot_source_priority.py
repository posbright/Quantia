#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试实时行情数据源优先级配置（QUANTIA_SPOT_SOURCE_PRIORITY）。"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import quantia.core.stockfetch as stf


def _names(data_sources):
    return [item[0] for item in data_sources]


def _sample_sources():
    return [
        ('东方财富', lambda: None),
        ('腾讯财经', lambda: None),
        ('新浪财经', lambda: None),
    ]


def test_no_config_keeps_original_order(monkeypatch):
    monkeypatch.delenv('QUANTIA_SPOT_SOURCE_PRIORITY', raising=False)
    sources = _sample_sources()
    result = stf._apply_source_priority(sources)
    assert _names(result) == ['东方财富', '腾讯财经', '新浪财经']


def test_empty_config_keeps_original_order(monkeypatch):
    monkeypatch.setenv('QUANTIA_SPOT_SOURCE_PRIORITY', '  ,  ')
    sources = _sample_sources()
    result = stf._apply_source_priority(sources)
    assert _names(result) == ['东方财富', '腾讯财经', '新浪财经']


def test_full_reorder(monkeypatch):
    monkeypatch.setenv('QUANTIA_SPOT_SOURCE_PRIORITY', '腾讯财经,新浪财经,东方财富')
    sources = _sample_sources()
    result = stf._apply_source_priority(sources)
    assert _names(result) == ['腾讯财经', '新浪财经', '东方财富']


def test_partial_config_appends_remaining_in_original_order(monkeypatch):
    # 只指定把腾讯提到首位，其余保持原始相对顺序追加
    monkeypatch.setenv('QUANTIA_SPOT_SOURCE_PRIORITY', '腾讯财经')
    sources = _sample_sources()
    result = stf._apply_source_priority(sources)
    assert _names(result) == ['腾讯财经', '东方财富', '新浪财经']


def test_unknown_names_ignored_and_no_source_lost(monkeypatch):
    monkeypatch.setenv('QUANTIA_SPOT_SOURCE_PRIORITY', '不存在的源,新浪财经')
    sources = _sample_sources()
    result = stf._apply_source_priority(sources)
    # 未知名忽略；新浪提前；其余保持原始相对顺序
    assert _names(result) == ['新浪财经', '东方财富', '腾讯财经']
    assert len(result) == len(sources)


def test_duplicate_names_in_config_handled(monkeypatch):
    monkeypatch.setenv('QUANTIA_SPOT_SOURCE_PRIORITY', '腾讯财经,腾讯财经,东方财富')
    sources = _sample_sources()
    result = stf._apply_source_priority(sources)
    assert _names(result) == ['腾讯财经', '东方财富', '新浪财经']
    assert len(result) == len(sources)


def test_priority_preserves_fetch_callables(monkeypatch):
    monkeypatch.setenv('QUANTIA_SPOT_SOURCE_PRIORITY', '腾讯财经,东方财富,新浪财经')
    sources = _sample_sources()
    result = stf._apply_source_priority(sources)
    # 重排后每个条目仍是 (name, callable) 且 callable 未被破坏
    for name, func in result:
        assert callable(func)
