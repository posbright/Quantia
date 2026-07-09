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

# 关键词后紧跟这些串 → 判定为“对该宽基本身的引用”（如 沪深300指数收益率）。
_STANDALONE_SUFFIXES = ('指数', '收益')


def _is_cjk(ch):
    return '\u4e00' <= ch <= '\u9fff'


def _valid_boundary(text, end_idx):
    """关键词右边界校验：区分「宽基本身」与「以宽基名开头的子指数/风格指数」。

    - 关键词在串尾，或后接**非汉字非数字**（如 指/×/%/空格/字母标点）→ 视为对宽基本身的引用。
    - 后接数字 → 说明关键词其实是更长数字代码的前缀（中证100 之于 中证1000），拒绝。
    - 后接汉字 → 仅当紧跟“指数/收益”才接受；否则是子指数名（沪深300**成长**、中证500**信息**技术）→ 拒绝，
      降级为 None（宁缺毋滥，避免对风格/行业子指数错套宽基估值）。
    """
    rest = text[end_idx:]
    if not rest:
        return True
    nxt = rest[0]
    if nxt.isdigit():
        return False
    if not _is_cjk(nxt):
        return True
    return any(rest.startswith(s) for s in _STANDALONE_SUFFIXES)


def map_benchmark_to_index(benchmark_text):
    """基准文本 → 指数代码（命中 12 只有估值覆盖的宽基之一），无命中返回 None。

    仅当关键词是对**宽基本身**的引用才命中；以宽基名开头的风格/行业子指数
    （如「沪深300成长指数」「中证500信息技术指数」）判定为无覆盖 → None，避免错套宽基估值。

    >>> map_benchmark_to_index('沪深300指数收益率×95%＋银行活期存款利率×5%')
    '000300'
    >>> map_benchmark_to_index('中证1000指数收益率×90%')
    '000852'
    >>> map_benchmark_to_index('沪深300成长指数收益率×90%') is None  # 风格子指数，无宽基估值覆盖
    True
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
        start = 0
        while True:
            i = text.find(keyword, start)
            if i < 0:
                break
            if _valid_boundary(text, i + len(keyword)):
                return code
            start = i + 1
    return None
