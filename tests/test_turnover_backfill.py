#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stockfetch.backfill_turnover_from_spot 单元测试（DB 层被 mock，零真实连接）。"""

import unittest
from unittest import mock

import pandas as pd

import quantia.core.stockfetch as stf


def _hist(n=60, turnover=None):
    dates = pd.date_range('2026-01-01', periods=n, freq='D')
    data = {
        'date': dates,
        'open': [10.0] * n,
        'high': [10.5] * n,
        'low': [9.5] * n,
        'close': [10.0] * n,
    }
    if turnover is not None:
        data['turnover'] = list(turnover)
    return pd.DataFrame(data)


class TestBackfillTurnover(unittest.TestCase):

    def test_gate_skips_db_when_cache_sufficient(self):
        # 近窗口有 >= min_bars(20) 个正换手率 → 不应查库
        h = _hist(60, turnover=[3.0] * 60)
        with mock.patch.object(stf, '_load_turnover_map',
                               side_effect=AssertionError('DB 不应被查询')) as m:
            out = stf.backfill_turnover_from_spot('000001', h)
        m.assert_not_called()
        self.assertIs(out, h)  # 原对象返回

    def test_fills_when_turnover_column_missing(self):
        h = _hist(60)  # 无 turnover 列
        # 构造 {YYYY-MM-DD: 换手率} 映射覆盖全部日期
        tmap = {d.strftime('%Y-%m-%d'): 2.5 for d in h['date']}
        with mock.patch.object(stf, '_load_turnover_map', return_value=tmap):
            out = stf.backfill_turnover_from_spot('000001', h)
        self.assertIn('turnover', out.columns)
        self.assertEqual(int((out['turnover'] > 0).sum()), 60)
        self.assertAlmostEqual(out['turnover'].iloc[0], 2.5)

    def test_fills_only_zero_rows_preserving_existing(self):
        # 前 30 行有有效换手率，后 30 行为 0 → 只补后半，且不足以触发 gate 跳过
        turn = [1.5] * 10 + [0.0] * 50
        h = _hist(60, turnover=turn)
        tmap = {d.strftime('%Y-%m-%d'): 4.0 for d in h['date']}
        with mock.patch.object(stf, '_load_turnover_map', return_value=tmap):
            out = stf.backfill_turnover_from_spot('000001', h)
        # 已有 >0 的值保留
        self.assertAlmostEqual(out['turnover'].iloc[0], 1.5)
        # 原本为 0 的位置被 DB 值补齐
        self.assertAlmostEqual(out['turnover'].iloc[-1], 4.0)

    def test_returns_unchanged_when_db_empty(self):
        h = _hist(60)
        with mock.patch.object(stf, '_load_turnover_map', return_value={}):
            out = stf.backfill_turnover_from_spot('000001', h)
        # 补不到 → 原样返回（无 turnover 列）
        self.assertNotIn('turnover', out.columns)

    def test_falls_back_to_etf_spot(self):
        h = _hist(60)
        tmap = {d.strftime('%Y-%m-%d'): 1.0 for d in h['date']}

        def _side(table, code, start):
            return {} if table == 'cn_stock_spot' else tmap

        with mock.patch.object(stf, '_load_turnover_map', side_effect=_side):
            out = stf.backfill_turnover_from_spot('510300', h)
        self.assertEqual(int((out['turnover'] > 0).sum()), 60)

    def test_none_or_empty_input_safe(self):
        self.assertIsNone(stf.backfill_turnover_from_spot('000001', None))
        empty = pd.DataFrame()
        self.assertTrue(stf.backfill_turnover_from_spot('000001', empty).empty)


if __name__ == '__main__':
    unittest.main()
