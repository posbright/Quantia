#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""composite_alpha_data_job 纯核心 select_composite 单元测试（无 DB / 无 K线 IO）。"""

import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
JOB = os.path.join(ROOT, "quantia", "job")
if JOB not in sys.path:
    sys.path.insert(0, JOB)

import composite_alpha_data_job as caj


def _make_selection(n=60, seed=1):
    rng = np.random.RandomState(seed)
    return pd.DataFrame({
        'date': ['2026-06-30'] * n,
        'code': [f'{600000 + i:06d}' for i in range(n)],
        'name': [f'股票{i}' for i in range(n)],
        'new_price': rng.uniform(5, 50, n),
        'roe_weight': rng.uniform(2, 30, n),
        'sale_gpr': rng.uniform(10, 60, n),
        'sale_npr': rng.uniform(2, 30, n),
        'netprofit_growthrate_3y': rng.uniform(-20, 40, n),
        'income_growthrate_3y': rng.uniform(-10, 35, n),
        'debt_asset_ratio': rng.uniform(20, 80, n),
        'pe9': rng.uniform(5, 90, n),
        'pbnewmrq': rng.uniform(0.5, 8, n),
    })


class TestSelectComposite:
    def test_basic_selection(self):
        df = _make_selection()
        picked = caj.select_composite(df, quality_gate=40, trade_gate=40, top_positions=10)
        assert len(picked) <= 10
        if not picked.empty:
            assert 'composite_score' in picked.columns
            assert picked['composite_score'].is_monotonic_decreasing

    def test_excludes_st_and_delist(self):
        df = _make_selection(n=20, seed=3)
        df.loc[0, 'name'] = 'ST某某'
        df.loc[1, 'name'] = '某某退'
        picked = caj.select_composite(df, quality_gate=0, trade_gate=0, top_positions=20)
        codes = set(picked['code']) if not picked.empty else set()
        assert df.loc[0, 'code'] not in codes
        assert df.loc[1, 'code'] not in codes

    def test_high_gate_empty(self):
        """极高门槛允许当日空仓。"""
        df = _make_selection(n=30, seed=5)
        picked = caj.select_composite(df, quality_gate=100, trade_gate=100, top_positions=10)
        assert picked.empty

    def test_tech_map_enables_tech_dim(self):
        """提供技术因子后 tech 维度参与打分（tech_score 非全空）。"""
        df = _make_selection(n=40, seed=7)
        rng = np.random.RandomState(7)
        tech_map = {c: (float(rng.uniform(1, 10)), float(rng.uniform(-5, 8)),
                        float(rng.uniform(-15, 25))) for c in df['code']}
        picked = caj.select_composite(df, tech_map=tech_map, quality_gate=30,
                                      trade_gate=30, top_positions=15)
        if not picked.empty:
            assert picked['tech_score'].notna().any()

    def test_new_price_filter(self):
        """停牌/无价（new_price<=0）应被过滤。"""
        df = _make_selection(n=15, seed=9)
        df.loc[0, 'new_price'] = 0
        picked = caj.select_composite(df, quality_gate=0, trade_gate=0, top_positions=15)
        codes = set(picked['code']) if not picked.empty else set()
        assert df.loc[0, 'code'] not in codes

    def test_value_score_and_close_propagate(self):
        """value_score 与 close 应随入选结果一并输出（回归：曾漏传 value_score/close）。"""
        df = _make_selection(n=40, seed=13)
        picked = caj.select_composite(df, quality_gate=30, trade_gate=30, top_positions=10)
        assert not picked.empty
        assert 'value_score' in picked.columns and picked['value_score'].notna().any()
        assert 'close' in picked.columns and picked['close'].notna().any()
