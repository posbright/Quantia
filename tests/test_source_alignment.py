#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据源字段对齐验证脚本
验证不同数据源输出的 DataFrame 列数和语义顺序与 DB schema 一致。
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import quantia.core.tablestructure as tbs


def get_schema_columns(table_def):
    """获取 schema 列名列表（不含 date）"""
    return list(table_def['columns'].keys())[1:]  # skip 'date'


def verify_columns(source_name, df, expected_cols, category):
    """验证 DataFrame 列数和关键列的语义"""
    issues = []
    actual_cols = list(df.columns)

    if len(actual_cols) != len(expected_cols):
        issues.append(f"  列数不匹配: 期望 {len(expected_cols)}, 实际 {len(actual_cols)}")
        return issues

    # 验证最后两列（总市值/流通市值）的语义
    if category in ('etf', 'index'):
        # Schema: ..., total_market_cap(总市值), free_cap(流通市值)
        last_two = actual_cols[-2:]
        if last_two != ['总市值', '流通市值']:
            issues.append(f"  最后两列顺序错误: 期望 ['总市值', '流通市值'], 实际 {last_two}")

    if category == 'stock':
        # Schema: ..., total_market_cap(总市值), free_cap(流通市值), industry, listing_date
        mv_idx_total = None
        mv_idx_free = None
        for i, col in enumerate(actual_cols):
            if col == '总市值':
                mv_idx_total = i
            if col == '流通市值':
                mv_idx_free = i
        if mv_idx_total is not None and mv_idx_free is not None:
            if mv_idx_total > mv_idx_free:
                issues.append(f"  总市值/流通市值顺序错误: 总市值@{mv_idx_total} > 流通市值@{mv_idx_free}")

    return issues


def test_etf_sources():
    """验证 ETF 数据源列对齐"""
    expected = get_schema_columns(tbs.TABLE_CN_ETF_SPOT)
    print(f"\nETF schema: {len(expected)} 列 (不含date)")
    print(f"  最后两列: {expected[-2:]} (total_market_cap, free_cap)")

    # Tencent
    try:
        import quantia.core.crawling.etf_tencent as etc
        df = etc.fund_etf_spot_tencent()
        if df is not None and len(df) > 0:
            issues = verify_columns("ETF腾讯", df, expected, 'etf')
            print(f"  ETF腾讯: {len(df)} 条, {len(df.columns)} 列, 最后两列={list(df.columns[-2:])}")
            for iss in issues:
                print(f"    ❌ {iss}")
            if not issues:
                print(f"    ✅ 列对齐正确")
        else:
            print(f"  ETF腾讯: 获取失败(可能不在交易时段)")
    except Exception as e:
        print(f"  ETF腾讯: 异常 {e}")

    # Sina
    try:
        import quantia.core.crawling.etf_sina as esa
        df = esa.fund_etf_spot_sina()
        if df is not None and len(df) > 0:
            issues = verify_columns("ETF新浪", df, expected, 'etf')
            print(f"  ETF新浪: {len(df)} 条, {len(df.columns)} 列, 最后两列={list(df.columns[-2:])}")
            for iss in issues:
                print(f"    ❌ {iss}")
            if not issues:
                print(f"    ✅ 列对齐正确")
        else:
            print(f"  ETF新浪: 获取失败(可能不在交易时段)")
    except Exception as e:
        print(f"  ETF新浪: 异常 {e}")

    # EastMoney (may fail with 500 currently)
    try:
        import quantia.core.crawling.fund_etf_em as fee
        df = fee.fund_etf_spot_em()
        if df is not None and len(df) > 0:
            issues = verify_columns("ETF东方财富", df, expected, 'etf')
            print(f"  ETF东方财富: {len(df)} 条, {len(df.columns)} 列, 最后两列={list(df.columns[-2:])}")
            for iss in issues:
                print(f"    ❌ {iss}")
            if not issues:
                print(f"    ✅ 列对齐正确")
        else:
            print(f"  ETF东方财富: 获取失败")
    except Exception as e:
        print(f"  ETF东方财富: 异常 {e}")


def test_index_sources():
    """验证 Index 数据源列对齐"""
    expected = get_schema_columns(tbs.TABLE_CN_INDEX_SPOT)
    print(f"\nIndex schema: {len(expected)} 列 (不含date)")
    print(f"  最后两列: {expected[-2:]} (total_market_cap, free_cap)")

    # Tencent
    try:
        import quantia.core.crawling.index_tencent as itc
        df = itc.index_spot_tencent()
        if df is not None and len(df) > 0:
            issues = verify_columns("Index腾讯", df, expected, 'index')
            print(f"  Index腾讯: {len(df)} 条, {len(df.columns)} 列, 最后两列={list(df.columns[-2:])}")
            for iss in issues:
                print(f"    ❌ {iss}")
            if not issues:
                print(f"    ✅ 列对齐正确")
        else:
            print(f"  Index腾讯: 获取失败")
    except Exception as e:
        print(f"  Index腾讯: 异常 {e}")

    # Sina
    try:
        import quantia.core.crawling.index_sina as isa
        df = isa.index_spot_sina()
        if df is not None and len(df) > 0:
            issues = verify_columns("Index新浪", df, expected, 'index')
            print(f"  Index新浪: {len(df)} 条, {len(df.columns)} 列, 最后两列={list(df.columns[-2:])}")
            for iss in issues:
                print(f"    ❌ {iss}")
            if not issues:
                print(f"    ✅ 列对齐正确")
        else:
            print(f"  Index新浪: 获取失败")
    except Exception as e:
        print(f"  Index新浪: 异常 {e}")

    # EastMoney (may fail with 500)
    try:
        import quantia.core.crawling.stock_index_em as sie
        df = sie.stock_index_spot_em()
        if df is not None and len(df) > 0:
            issues = verify_columns("Index东方财富", df, expected, 'index')
            print(f"  Index东方财富: {len(df)} 条, {len(df.columns)} 列, 最后两列={list(df.columns[-2:])}")
            for iss in issues:
                print(f"    ❌ {iss}")
            if not issues:
                print(f"    ✅ 列对齐正确")
        else:
            print(f"  Index东方财富: 获取失败")
    except Exception as e:
        print(f"  Index东方财富: 异常 {e}")


def test_stock_sources():
    """验证 Stock 数据源列对齐"""
    expected = get_schema_columns(tbs.TABLE_CN_STOCK_SPOT)
    print(f"\nStock schema: {len(expected)} 列 (不含date)")

    # Just verify Tencent (fastest)
    try:
        import quantia.core.crawling.stock_tencent as stc
        df = stc.stock_zh_a_spot_tencent()
        if df is not None and len(df) > 0:
            issues = verify_columns("Stock腾讯", df, expected, 'stock')
            print(f"  Stock腾讯: {len(df)} 条, {len(df.columns)} 列")
            # Find 总市值 and 流通市值 positions
            cols = list(df.columns)
            for name in ['总市值', '流通市值']:
                idx = cols.index(name) if name in cols else -1
                print(f"    {name} @ position {idx}")
            for iss in issues:
                print(f"    ❌ {iss}")
            if not issues:
                print(f"    ✅ 列对齐正确")
    except Exception as e:
        print(f"  Stock腾讯: 异常 {e}")


if __name__ == '__main__':
    print("=" * 60)
    print("数据源字段对齐验证")
    print("=" * 60)

    test_etf_sources()
    test_index_sources()
    test_stock_sources()

    print("\n" + "=" * 60)
    print("验证完成")
