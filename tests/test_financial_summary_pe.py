#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""StockFinancialSummaryHandler 市盈率回退逻辑回归测试。

背景：腾讯/新浪行情源不提供 TTM/静态市盈率（落库为 0），仅有动态市盈率(dtsyl)。
此前指标详情"市盈率(PE)"直接取 pe9 → 全市场显示为空。修复后按
TTM → 动态 → 静态 优先级回退。
"""

import unittest

from quantia.web.stockFinancialHandler import _pick_pe


class TestPickPe(unittest.TestCase):
    def test_prefers_ttm_when_available(self):
        self.assertEqual(_pick_pe(15.5, 16.2, 14.0), 15.5)

    def test_falls_back_to_dynamic_when_ttm_zero(self):
        # 腾讯/新浪场景：pe9=0, pe=0, 仅 dtsyl 有效
        self.assertEqual(_pick_pe(0.0, 107.41, 0.0), 107.41)

    def test_falls_back_to_dynamic_when_ttm_none(self):
        self.assertEqual(_pick_pe(None, 24.9, None), 24.9)

    def test_falls_back_to_static_when_ttm_and_dynamic_missing(self):
        self.assertEqual(_pick_pe(0.0, 0.0, 12.3), 12.3)

    def test_returns_none_when_all_missing(self):
        self.assertIsNone(_pick_pe(0.0, 0.0, 0.0))
        self.assertIsNone(_pick_pe(None, None, None))

    def test_negative_pe_is_kept(self):
        # 亏损股动态市盈率为负，属于有效信息，应保留展示
        self.assertEqual(_pick_pe(0.0, -8.5, 0.0), -8.5)


if __name__ == '__main__':
    unittest.main()
