#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""StockDataFallbackHandler 财务字段逐字段回退逻辑回归测试。

背景：最新报告期（如季报）核心指标(营收/ROE/毛利率)可能因上游尚未披露而为 NULL，
原逻辑仅取最新一行并剔除 NULL，导致前端"报告期最新但营收等全空白"。
修复后 _coalesce_financials 对每个字段回退到最近非空值，并用 value_periods
记录回退值实际所属报告期，供前端标注"截至xxxx"。
"""

import unittest

from quantia.web.stockReportHandler import _coalesce_financials


class TestCoalesceFinancials(unittest.TestCase):
    KEYS = ['report_date', 'revenue', 'roe', 'gross_margin']

    def test_empty_rows_returns_none(self):
        self.assertIsNone(_coalesce_financials([], self.KEYS))

    def test_latest_row_complete_no_fallback(self):
        """最新期各字段齐全时，直接取最新期且不产生 value_periods。"""
        rows = [
            ('2026-03-31', 100.0, 5.0, 30.0),
            ('2025-12-31', 90.0, 4.5, 29.0),
        ]
        out = _coalesce_financials(rows, self.KEYS)
        self.assertEqual(out['report_date'], '2026-03-31')
        self.assertEqual(out['revenue'], 100.0)
        self.assertEqual(out['roe'], 5.0)
        self.assertNotIn('value_periods', out)

    def test_per_field_fallback_to_earlier_period(self):
        """最新期核心字段 NULL 时回退上一期，并在 value_periods 标注来源期。"""
        rows = [
            ('2026-03-31', None, None, None),   # 季报：仅建行，核心指标未披露
            ('2025-12-31', 12000.0, None, 46.0),
            ('2024-12-31', 11000.0, 3.0, 45.0),
        ]
        out = _coalesce_financials(rows, self.KEYS)
        # 锚点仍是最新期（数据新鲜度）
        self.assertEqual(out['report_date'], '2026-03-31')
        # 营收回退到 2025-12-31
        self.assertEqual(out['revenue'], 12000.0)
        # roe 2025 也为 NULL，继续回退到 2024-12-31
        self.assertEqual(out['roe'], 3.0)
        self.assertEqual(out['gross_margin'], 46.0)
        # value_periods 标注每个回退值的实际报告期
        self.assertEqual(out['value_periods']['revenue'], '2025-12-31')
        self.assertEqual(out['value_periods']['roe'], '2024-12-31')
        self.assertEqual(out['value_periods']['gross_margin'], '2025-12-31')

    def test_all_metrics_null_returns_none(self):
        """所有期所有指标均为 NULL 时返回 None（不下发空壳）。"""
        rows = [
            ('2026-03-31', None, None, None),
            ('2025-12-31', None, None, None),
        ]
        self.assertIsNone(_coalesce_financials(rows, self.KEYS))


if __name__ == '__main__':
    unittest.main()
