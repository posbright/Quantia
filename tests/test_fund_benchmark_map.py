#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P3 基金基准 → 宽基指数映射单测（benchmark_map）。纯字符串，无 DB/网络。"""

from quantia.core.fund import benchmark_map as bm


class TestMapBenchmarkToIndex:
    def test_hs300(self):
        assert bm.map_benchmark_to_index('沪深300指数收益率×95%＋银行活期存款利率（税后）×5%') == '000300'

    def test_zz1000_not_shadowed_by_zz100(self):
        # 关键：中证1000 不能被子串「中证100」截断误配
        assert bm.map_benchmark_to_index('中证1000指数收益率×90%＋活期×10%') == '000852'

    def test_zz100(self):
        assert bm.map_benchmark_to_index('中证100指数收益率') == '000903'

    def test_zz500(self):
        assert bm.map_benchmark_to_index('中证500指数收益率*80%') == '000905'

    def test_zz800(self):
        assert bm.map_benchmark_to_index('中证800指数') == '000906'

    def test_sz50(self):
        assert bm.map_benchmark_to_index('上证50指数收益率') == '000016'

    def test_cyb50(self):
        assert bm.map_benchmark_to_index('创业板50指数收益率') == '399673'

    def test_chuangyeban_zhi_not_mapped(self):
        # 创业板指（399006）不在有估值覆盖的 12 只内 → 不映射
        assert bm.map_benchmark_to_index('创业板指数收益率×95%') is None

    def test_unknown_returns_none(self):
        assert bm.map_benchmark_to_index('某某主题指数收益率') is None

    def test_empty_and_none(self):
        assert bm.map_benchmark_to_index(None) is None
        assert bm.map_benchmark_to_index('') is None
        assert bm.map_benchmark_to_index('   ') is None

    # ── 风格/行业子指数不得错套宽基估值（边界校验，生产实测 10 例）──
    def test_hs300_style_growth_not_mapped(self):
        # 沪深300成长 是风格子指数，无宽基估值覆盖 → None（不得错套 000300）
        assert bm.map_benchmark_to_index('沪深300成长指数收益率×90%+中债×10%') is None

    def test_zz800_growth_not_mapped(self):
        assert bm.map_benchmark_to_index('中证800成长指数收益率×85%+中债-总全价指数收益率×15%') is None

    def test_zz500_sector_not_mapped(self):
        assert bm.map_benchmark_to_index('中证500信息技术指数收益率×95%+银行活期×5%') is None

    def test_hs300_innovation_not_mapped(self):
        assert bm.map_benchmark_to_index('沪深300创新驱动指数收益率×70%+中证港股通综合指数×15%') is None

    def test_zz800_growth_midstring_not_mapped(self):
        # 子指数出现在串中部，仍应拒绝
        assert bm.map_benchmark_to_index('中债-新综合财富指数收益率×80%+中证800成长指数收益率×15%') is None

    def test_zz1000_style_not_shadowed_to_zz100(self):
        # 中证1000成长：既不是 中证1000 本身，也不能被子串 中证100 误配 → None
        assert bm.map_benchmark_to_index('中证1000成长指数收益率×90%') is None

    def test_standalone_broad_still_maps_with_income_suffix(self):
        # 关键词后紧跟“收益率”（无“指数”二字）仍应命中宽基本身
        assert bm.map_benchmark_to_index('沪深300收益率×95%') == '000300'

    def test_standalone_broad_with_nonchinese_suffix(self):
        # 关键词后接非汉字（ETF/标点）→ 命中宽基本身
        assert bm.map_benchmark_to_index('沪深300ETF联接') == '000300'
