#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试新浪降级时用历史股本回算总市值/流通市值/换手率。"""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import quantia.core.stockfetch as stf


def _make_df(rows):
    """构造与 TABLE_CN_STOCK_SPOT 对齐（仅含回算用到的列）的 DataFrame。"""
    return pd.DataFrame(rows)


def _base_row(code, new_price, volume):
    return {
        'code': code,
        'new_price': new_price,
        'volume': volume,
        'turnoverrate': 0,
        'total_shares': 0,
        'free_shares': 0,
        'total_market_cap': 0,
        'free_cap': 0,
    }


def test_backfill_computes_cap_and_turnover():
    data = _make_df([_base_row('600000', 10.0, 1_000_000)])
    shares_map = {'600000': (5_000_000, 2_000_000)}  # 总股本500万, 流通200万
    filled = stf._backfill_shares_derived_columns(data, shares_map)

    assert filled == 1
    row = data.iloc[0]
    assert row['total_market_cap'] == 50_000_000     # 10 * 500万
    assert row['free_cap'] == 20_000_000             # 10 * 200万
    # 换手率 = 成交量 / 流通股本 * 100 = 1,000,000 / 2,000,000 * 100 = 50
    assert abs(row['turnoverrate'] - 50.0) < 1e-6
    # 股本列也被补回
    assert row['total_shares'] == 5_000_000
    assert row['free_shares'] == 2_000_000


def test_backfill_skips_when_no_history_shares():
    data = _make_df([_base_row('301999', 20.0, 500_000)])
    shares_map = {'600000': (5_000_000, 2_000_000)}  # 无 301999
    filled = stf._backfill_shares_derived_columns(data, shares_map)

    assert filled == 0
    row = data.iloc[0]
    assert row['total_market_cap'] == 0
    assert row['free_cap'] == 0
    assert row['turnoverrate'] == 0


def test_backfill_does_not_overwrite_existing_nonzero():
    row = _base_row('600000', 10.0, 1_000_000)
    row['total_market_cap'] = 99_999_999   # 已有非零值（如东财数据），不应被覆盖
    row['turnoverrate'] = 3.21
    data = _make_df([row])
    shares_map = {'600000': (5_000_000, 2_000_000)}
    stf._backfill_shares_derived_columns(data, shares_map)

    out = data.iloc[0]
    assert out['total_market_cap'] == 99_999_999
    assert abs(out['turnoverrate'] - 3.21) < 1e-6


def test_backfill_empty_map_returns_zero():
    data = _make_df([_base_row('600000', 10.0, 1_000_000)])
    assert stf._backfill_shares_derived_columns(data, {}) == 0
    assert data.iloc[0]['total_market_cap'] == 0


def test_backfill_empty_dataframe():
    data = _make_df([]).reindex(columns=[
        'code', 'new_price', 'volume', 'turnoverrate',
        'total_shares', 'free_shares', 'total_market_cap', 'free_cap',
    ])
    assert stf._backfill_shares_derived_columns(data, {'600000': (1, 1)}) == 0


def test_backfill_zero_free_shares_skips_turnover_but_caps_total():
    data = _make_df([_base_row('600000', 10.0, 1_000_000)])
    shares_map = {'600000': (5_000_000, 0)}  # 流通股本未知
    filled = stf._backfill_shares_derived_columns(data, shares_map)

    assert filled == 1
    row = data.iloc[0]
    assert row['total_market_cap'] == 50_000_000   # 总市值可算
    assert row['free_cap'] == 0                    # 流通市值无法算
    assert row['turnoverrate'] == 0                # 换手率无法算


def test_backfill_partial_rows():
    data = _make_df([
        _base_row('600000', 10.0, 1_000_000),
        _base_row('000001', 5.0, 400_000),
    ])
    shares_map = {'600000': (5_000_000, 2_000_000)}  # 仅第一只有股本
    filled = stf._backfill_shares_derived_columns(data, shares_map)

    assert filled == 1
    assert data.iloc[0]['total_market_cap'] == 50_000_000
    assert data.iloc[1]['total_market_cap'] == 0


def test_backfill_fractional_turnover_into_int_column():
    # 回归：换手率列初始为 int(0)，回算出小数（如 0.5153）不应触发 pandas dtype 错误
    data = _make_df([_base_row('000001', 10.0, 100_000_000)])
    # 大流通股本 → 换手率为小数
    shares_map = {'000001': (19_405_918_198, 19_405_600_653)}
    filled = stf._backfill_shares_derived_columns(data, shares_map)

    assert filled == 1
    row = data.iloc[0]
    # 换手率 = 1e8 / 1.94056e10 * 100 ≈ 0.5153
    assert abs(row['turnoverrate'] - round(100_000_000 / 19_405_600_653 * 100, 4)) < 1e-6
    assert row['total_market_cap'] == round(10.0 * 19_405_918_198)

