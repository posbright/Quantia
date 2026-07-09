#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""基金 → 跟踪宽基指数映射（T3 估值分位择时的基准解析）。

把 ``cn_fund_profile.benchmark`` 业绩比较基准文本解析到一只**有估值覆盖**的宽基指数
代码（见 crawling.index_valuation_lg.INDEX_SYMBOLS 的 12 只）。仅命中这 12 只时才有
估值分位可用，否则返回 None（T3 维度缺失，compose 自动降维，不造信号）。

匹配口径（保守，宁缺毋滥）：
- 关键词按**长度降序**匹配，避免「中证1000」被「中证100」截断误配。
- 主动混合基金基准是文本表达式（噪声大）：只做**明确指数名**的字面命中，不做行业推断。
"""

__author__ = 'Quantia'
__date__ = '2026/07/09'

# 指数名关键词 → 纯数字代码（与 cn_index_valuation.index_code 一致）。
# 别名合并到同一代码；长关键词优先（下方按长度降序匹配）。
_BENCHMARK_KEYWORDS = {
    '沪深300': '000300',
    '中证1000': '000852',
    '中证800': '000906',
    '中证500': '000905',
    '中证100': '000903',
    '上证180': '000010',
    '上证380': '000009',
    '上证50': '000016',
    '上证红利': '000015',
    '深证红利': '399324',
    '深证100': '399330',
    '创业板50': '399673',
}

# 预排序：长关键词在前（防子串误配，如 中证1000 vs 中证100）。
_ORDERED_KEYWORDS = sorted(_BENCHMARK_KEYWORDS.items(), key=lambda kv: len(kv[0]), reverse=True)


def map_benchmark_to_index(benchmark_text):
    """基准文本 → 指数代码（命中 12 只有估值覆盖的宽基之一），无命中返回 None。

    >>> map_benchmark_to_index('沪深300指数收益率×95%＋银行活期存款利率×5%')
    '000300'
    >>> map_benchmark_to_index('中证1000指数收益率×90%')
    '000852'
    >>> map_benchmark_to_index('创业板指数收益率') is None  # 创业板指非创业板50，无估值覆盖
    True
    """
    if not benchmark_text:
        return None
    try:
        text = str(benchmark_text)
    except (TypeError, ValueError):
        return None
    if not text.strip():
        return None
    for keyword, code in _ORDERED_KEYWORDS:
        if keyword in text:
            return code
    return None
