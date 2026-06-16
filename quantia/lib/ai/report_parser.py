#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Parse structured fields from AI stock report Markdown."""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

_RATING_KEYWORDS = (
    ('avoid', ('🔴回避', '回避', '卖出', '减持', '看空')),
    ('buy', ('🟢买入', '买入', '增持', '看多', '积极')),
    ('hold', ('🟡观望', '观望', '持有', '中性')),
)

_FACTOR_KEYWORDS = {
    'patents': ('专利', '知识产权', '发明专利', 'IPC', 'PCT'),
    'brand': ('品牌', '客户粘性', '口碑'),
    'scale': ('规模', '市占率', '市场份额', '成本优势'),
    'tech': ('技术壁垒', '研发', '核心技术', '算法', '工艺'),
    'network': ('网络效应', '生态', '平台效应', '转换成本'),
}


def extract_structured_fields(report_md: str) -> Dict[str, Any]:
    """Extract Phase 2 structured fields from a Markdown report.

    The parser is intentionally conservative: values that cannot be recognized
    with reasonable confidence are returned as None instead of guessed.
    """
    text = report_md or ''
    target_low, target_high = _extract_target_range(text)
    return {
        'rating': _extract_rating(text),
        'rating_score': _extract_rating_score(text),
        'short_term_advice': _extract_advice(text, '短期'),
        'mid_term_advice': _extract_advice(text, '中期'),
        'long_term_advice': _extract_advice(text, '长期'),
        'target_price_low': target_low,
        'target_price_high': target_high,
        'stop_loss_price': _extract_stop_loss(text),
        'moat_score': _extract_moat_score(text),
        'moat_factors': _extract_moat_factors(text),
    }


def _extract_rating(text: str) -> Optional[str]:
    # 结论/评级往往位于"综合评级 / 综合判断 / 投资评级"小节，且小节序号不固定
    # （五、六、七…），可能带 emoji 前缀（"## 🏆 六、"），最终结论行也可能是一个
    # 独立的 ### 子标题（"### 综合评级：强烈看空"）。因此从结论小节标题处起向后取
    # 全部正文（不在子标题处截断），再优先匹配形如"评级：xxx"的结论行。
    section = _conclusion_tail(text)
    lines = section.splitlines()
    # 结论行优先：形如 "**评级**：观望" / "综合评级：看多"
    verdict_lines = [line for line in lines if re.search(r'(?:综合)?评级\s*[:：]', line)]
    other_rating_lines = [
        line for line in lines if '评级' in line and line not in verdict_lines
    ]
    haystacks = verdict_lines or other_rating_lines or [section]
    for haystack in haystacks:
        if _is_rating_option_line(haystack):
            continue
        for value, keywords in _RATING_KEYWORDS:
            if any(keyword in haystack for keyword in keywords):
                return value
    return None


def _conclusion_tail(text: str) -> str:
    """定位结论小节并返回从其标题处到文末的正文。

    结论小节标题按语义（综合评级/综合判断…）匹配，序号无关；找不到时回退到旧的
    "六、"序号标题，再回退到全文。不在子标题处截断，确保独立成行的结论标题
    （如 "### 综合评级：强烈看空"）也被纳入扫描范围。
    """
    hint_pattern = re.compile(
        r'(?m)^\s*#{1,6}\s*[^\n]*'
        r'(?:综合评级|综合判断|投资评级|综合结论|综合评价|评级与操作|评级与建议)'
        r'[^\n]*$'
    )
    match = hint_pattern.search(text)
    if match:
        return text[match.start():]
    legacy = re.search(r'(?m)^\s*#{1,6}\s*[^\n]*六、[^\n]*$', text)
    if legacy:
        return text[legacy.start():]
    return text


def _is_rating_option_line(text: str) -> bool:
    has_buy = any(keyword in text for keyword in ('🟢买入', '买入', '增持', '看多'))
    has_hold = any(keyword in text for keyword in ('🟡观望', '观望', '持有', '中性'))
    has_avoid = any(keyword in text for keyword in ('🔴回避', '回避', '卖出', '减持', '看空'))
    return sum((has_buy, has_hold, has_avoid)) >= 2 and bool(re.search(r'[/／|]', text))


def _extract_rating_score(text: str) -> Optional[int]:
    patterns = (
        r'(?:综合评分|评级分|评分)\D{0,12}(\d{1,3})\s*(?:分|/100)?',
        r'(\d{1,3})\s*/\s*100',
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            score = int(match.group(1))
            if 0 <= score <= 100:
                return score
    rating = _extract_rating(text)
    if rating == 'buy':
        return 75
    if rating == 'hold':
        return 50
    if rating == 'avoid':
        return 25
    return None


def _extract_advice(text: str, label: str) -> Optional[str]:
    pattern = re.compile(
        rf'(?m)^\s*#{{1,6}}\s*{re.escape(label)}[^\n]*\n(?P<body>.*?)(?=^\s*#{{1,6}}\s|\Z)',
        re.DOTALL,
    )
    match = pattern.search(text)
    body = match.group('body') if match else _extract_bullet_after_label(text, label)
    return _summarize_advice(body)


def _extract_bullet_after_label(text: str, label: str) -> str:
    pattern = re.compile(rf'{re.escape(label)}[^\n]*\n(?P<body>(?:\s*[-*].*\n?){{1,4}})', re.DOTALL)
    match = pattern.search(text)
    return match.group('body') if match else ''


def _summarize_advice(body: str) -> Optional[str]:
    if not body:
        return None
    lines = []
    for raw in body.splitlines():
        line = raw.strip().strip('|').strip()
        if not line or set(line) <= {'-', ':', ' '}:
            continue
        line = re.sub(r'^[-*+\d.、\s]+', '', line)
        line = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', line)
        line = re.sub(r'[`>#]', '', line).strip()
        if line:
            lines.append(line)
        if len('；'.join(lines)) >= 120:
            break
    if not lines:
        return None
    return '；'.join(lines)[:500]


def _extract_target_range(text: str) -> tuple[Optional[float], Optional[float]]:
    patterns = (
        r'(?:目标(?:价|区间|价格)|目标位)[^\n\d]{0,20}(\d+(?:\.\d+)?)\s*(?:-|~|\u2013|\u2014|至|到|—|－)\s*(\d+(?:\.\d+)?)\s*(?:元|块)?',
        r'(?:目标(?:价|价格)|目标位)[^\n\d]{0,20}(\d+(?:\.\d+)?)\s*(?:元|块)',
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        low = float(match.group(1))
        high = float(match.group(2)) if match.lastindex and match.lastindex >= 2 else low
        if low > high:
            low, high = high, low
        return low, high
    return None, None


def _extract_stop_loss(text: str) -> Optional[float]:
    patterns = (
        r'止损(?:参考|目标)?(?:价|位|线)[^\n\d]{0,15}(\d+(?:\.\d+)?)\s*(?:元|块|¥)?',
        r'风控价[^\n\d]{0,15}(\d+(?:\.\d+)?)\s*(?:元|块|¥)?',
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        tail = text[match.end():match.end() + 2]
        if tail.startswith((':', '：')):
            continue
        value = float(match.group(1))
        if 0 < value < 100000:
            return value
    return None


def _extract_moat_score(text: str) -> Optional[int]:
    section = _extract_section(text, '四.五') or _extract_section(text, '竞争壁垒') or _extract_section(text, '护城河')
    section = f'{section}\n{text}' if section else text
    level_map = {'强': 5, '中': 3, '弱': 1, '无': 0, '暂缺': 0}
    for line in section.splitlines():
        if _is_moat_option_line(line):
            continue
        # Strip markdown bold markers for reliable matching
        clean = re.sub(r'\*{1,3}', '', line)
        numeric = re.search(r'(?:护城河(?:强度)?评分|护城河评分|壁垒评分)[^\n\d]{0,20}(\d)\s*(?:/\s*5|分)?', clean)
        if numeric:
            value = int(numeric.group(1))
            if 0 <= value <= 5:
                return value
        level = re.search(r'(?:护城河(?:强度)?评分|护城河强度|壁垒强度)[^\n:：]*[:：]?\s*(强|中|弱|无|暂缺)', clean)
        if level:
            return level_map.get(level.group(1))
    return None


def _is_moat_option_line(line: str) -> bool:
    return bool(re.search(r'强\s*[/／|]\s*中\s*[/／|]\s*弱', line))


def _extract_moat_factors(text: str) -> Dict[str, bool]:
    section = _extract_section(text, '四.五') or _extract_section(text, '竞争壁垒') or _extract_section(text, '护城河') or text
    return {
        key: any(keyword in section for keyword in keywords)
        for key, keywords in _FACTOR_KEYWORDS.items()
    }


def _extract_section(text: str, title_fragment: str) -> str:
    pattern = re.compile(
        rf'(?m)^\s*#{{1,6}}\s*[^\n]*{re.escape(title_fragment)}[^\n]*\n(?P<body>.*?)(?=^\s*#{{1,6}}\s*[^\n]+|\Z)',
        re.DOTALL,
    )
    match = pattern.search(text)
    return match.group('body') if match else ''