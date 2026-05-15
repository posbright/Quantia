#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试策略名称映射完整性和 _resolve_strategy 容错性"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import quantia.core.tablestructure as tbs
from quantia.web.backtestDashboardHandler import _get_strategy_map, _resolve_strategy


class TestStrategyMap:
    """策略映射完整性测试"""

    def test_all_strategy_tables_have_entries(self):
        """每个 TABLE_CN_STOCK_STRATEGIES 的表名都在 map 中"""
        m = _get_strategy_map()
        for s in tbs.TABLE_CN_STOCK_STRATEGIES:
            assert s['name'] in m, f"表名 {s['name']} 不在 strategy_map 中"

    def test_all_strategy_chinese_names_have_entries(self):
        """每个策略的中文名都在 map 中"""
        m = _get_strategy_map()
        for s in tbs.TABLE_CN_STOCK_STRATEGIES:
            cn = s['cn']
            if cn:
                assert cn in m, f"中文名 '{cn}' 不在 strategy_map 中"

    def test_indicator_buy_entries(self):
        """指标买入信号的 3 种 key 都存在"""
        m = _get_strategy_map()
        table = tbs.TABLE_CN_STOCK_INDICATORS_BUY['name']
        assert table in m
        assert 'indicators_buy' in m
        assert '指标买入信号' in m
        # 且指向同一条目
        assert m[table]['table'] == table
        assert m['indicators_buy']['table'] == table
        assert m['指标买入信号']['table'] == table

    def test_indicator_sell_entries(self):
        """指标卖出信号的 3 种 key 都存在"""
        m = _get_strategy_map()
        table = tbs.TABLE_CN_STOCK_INDICATORS_SELL['name']
        assert table in m
        assert 'indicators_sell' in m
        assert '指标卖出信号' in m
        assert m[table]['table'] == table
        assert m['indicators_sell']['table'] == table

    def test_gpt_strategy_entries(self):
        """GPT综合选股的表名和中文名都在 map 中"""
        m = _get_strategy_map()
        table = tbs.TABLE_CN_STOCK_STRATEGY_GPT_VALUE['name']
        cn = tbs.TABLE_CN_STOCK_STRATEGY_GPT_VALUE['cn']
        assert table in m
        assert cn in m
        assert m[table]['table'] == table

    def test_total_key_count(self):
        """确保映射条目数 >= 34（13策略*2 + 3买入 + 3卖出 + 2GPT）"""
        m = _get_strategy_map()
        assert len(m) >= 34, f"映射条目仅 {len(m)} 个，期望 >= 34"

    def test_strategy_map_entry_has_required_fields(self):
        """每个映射条目都包含 table, cn, type 字段"""
        m = _get_strategy_map()
        for key, entry in m.items():
            assert 'table' in entry, f"key='{key}' 缺少 'table'"
            assert 'cn' in entry, f"key='{key}' 缺少 'cn'"
            assert 'type' in entry, f"key='{key}' 缺少 'type'"
            assert entry['type'] in ('strategy', 'indicator'), f"key='{key}' type='{entry['type']}' 非法"

    def test_summarize_backtest_writes_valid_strategy_names(self):
        """summarize_backtest 写入的所有 strategy_name 值都能被 strategy_map 找到"""
        m = _get_strategy_map()
        tables = [tbs.TABLE_CN_STOCK_INDICATORS_BUY, tbs.TABLE_CN_STOCK_INDICATORS_SELL]
        tables.extend(tbs.TABLE_CN_STOCK_STRATEGIES)
        tables.append(tbs.TABLE_CN_STOCK_STRATEGY_GPT_VALUE)
        for t in tables:
            table_name = t['name']
            assert table_name in m, f"summarize_backtest写入的 strategy_name='{table_name}' 不在 map 中"


class TestResolveStrategy:
    """_resolve_strategy 容错性测试"""

    def test_resolve_valid_table_name(self):
        """有效表名能成功解析"""
        meta, err = _resolve_strategy('cn_stock_strategy_enter')
        assert err is None
        assert meta is not None
        assert meta['table'] == 'cn_stock_strategy_enter'

    def test_resolve_valid_chinese_name(self):
        """有效中文名能成功解析"""
        meta, err = _resolve_strategy('放量上涨')
        assert err is None
        assert meta is not None
        assert meta['table'] == 'cn_stock_strategy_enter'

    def test_resolve_indicator_alias(self):
        """指标别名能成功解析"""
        meta, err = _resolve_strategy('indicators_buy')
        assert err is None
        assert meta is not None
        assert meta['table'] == tbs.TABLE_CN_STOCK_INDICATORS_BUY['name']

    def test_resolve_empty_string_returns_error(self):
        """空字符串返回错误"""
        meta, err = _resolve_strategy('')
        assert meta is None
        assert err is not None
        assert '缺少 strategy 参数' in err

    def test_resolve_none_returns_error(self):
        """None 返回错误"""
        meta, err = _resolve_strategy(None)
        assert meta is None
        assert err is not None

    def test_resolve_invalid_returns_diagnostic(self):
        """无效策略名返回诊断信息（包含实际值和可用列表）"""
        meta, err = _resolve_strategy('invalid_strategy')
        assert meta is None
        assert err is not None
        assert 'invalid_strategy' in err
        assert '可用策略' in err

    def test_resolve_whitespace_tolerance(self):
        """包含前后空格的策略名可以被正确解析"""
        meta, err = _resolve_strategy('  cn_stock_strategy_enter  ')
        assert err is None
        assert meta is not None
        assert meta['table'] == 'cn_stock_strategy_enter'

    def test_resolve_all_strategies_roundtrip(self):
        """模拟完整 DB→overview→frontend→detail 流程"""
        m = _get_strategy_map()
        # summarize_backtest 写入的值
        tables = [tbs.TABLE_CN_STOCK_INDICATORS_BUY, tbs.TABLE_CN_STOCK_INDICATORS_SELL]
        tables.extend(tbs.TABLE_CN_STOCK_STRATEGIES)
        tables.append(tbs.TABLE_CN_STOCK_STRATEGY_GPT_VALUE)

        for t in tables:
            db_value = t['name']  # summarize_backtest 写入 DB 的值
            # overview 从 DB 读出并返回给前端
            overview_meta = m.get(db_value)
            assert overview_meta is not None, f"overview 查找失败: '{db_value}'"
            # 前端再把 strategy_name 发回给 detail/dist/tradePairs
            detail_meta, err = _resolve_strategy(db_value)
            assert err is None, f"detail 解析失败: '{db_value}' => {err}"
            assert detail_meta['table'] == db_value

    def test_resolve_old_chinese_names_roundtrip(self):
        """旧版 DB 中存储中文名的兼容性"""
        tables = list(tbs.TABLE_CN_STOCK_STRATEGIES)
        for t in tables:
            cn = t['cn']
            meta, err = _resolve_strategy(cn)
            assert err is None, f"中文名解析失败: '{cn}' => {err}"
            assert meta['table'] == t['name']
