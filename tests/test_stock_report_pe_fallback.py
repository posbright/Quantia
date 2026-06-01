#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stockReportHandler / stock_profile 市盈率回退逻辑回归测试。

背景：行情源降级到腾讯/新浪时 cn_stock_spot.pe9/roe_weight 恒为 0，
导致 AI 降级报告(StockDataFallbackHandler)、行业分位数(IndustryPercentileHandler)、
以及 stock_profile 工具的 PE/ROE 全部为 0。修复后估值字段优先取 cn_stock_selection，
PE 按 TTM(pe9) → 动态(dtsyl) 回退。
"""

import unittest

from quantia.web.stockReportHandler import _pick_pe


class TestStockReportPickPe(unittest.TestCase):
    def test_prefers_ttm(self):
        self.assertEqual(_pick_pe(15.5, 16.2), 15.5)

    def test_falls_back_to_dynamic_when_ttm_zero(self):
        self.assertEqual(_pick_pe(0.0, 107.41), 107.41)

    def test_falls_back_to_dynamic_when_ttm_none(self):
        self.assertEqual(_pick_pe(None, 24.9), 24.9)

    def test_returns_none_when_both_missing(self):
        self.assertIsNone(_pick_pe(0.0, 0.0))
        self.assertIsNone(_pick_pe(None, None))

    def test_negative_pe_is_kept(self):
        self.assertEqual(_pick_pe(0.0, -8.5), -8.5)


if __name__ == '__main__':
    unittest.main()
