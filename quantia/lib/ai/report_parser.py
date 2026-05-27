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
    section = _extract_section(text, '六、') or text[:1200]
    rating_lines = [line for line in section.splitlines() if '评级' in line]
    haystacks = rating_lines if rating_lines else [section[:600]]
    for haystack in haystacks:
        if _is_rating_option_line(haystack):
            continue
        for value, keywords in _RATING_KEYWORDS:
            if any(keyword in haystack for keyword in keywords):
                return value
    return None


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
        rf'(?m)^\s*#{{1,6}}\s*{re.escape(label)}[^\n]*\n(?P<body>.*?)(?=^\s*#{{1,6}}\s*(?:短期|中期|长期|七、)|\Z)',
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
        r'(?:目标(?:价|区间|价格)|目标位)[^\n\d]{0,20}(\d+(?:\.\d+)?)\s*(?:-|~|至|到|—|－)\s*(\d+(?:\.\d+)?)\s*(?:元|块)?',
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
    match = re.search(r'(?:止损价|止损位|止损线|止损|风控价|跌破)[^\n\d]{0,20}(\d+(?:\.\d+)?)\s*(?:元|块)?', text)
    if match:
        return float(match.group(1))
    return None


def _extract_moat_score(text: str) -> Optional[int]:
    section = _extract_section(text, '四.五') or _extract_section(text, '竞争壁垒') or _extract_section(text, '护城河')
    section = f'{section}\n{text}' if section else text
    numeric = re.search(r'(?:护城河(?:强度)?评分|护城河评分|壁垒评分)[^\n\d]{0,20}(\d)\s*(?:/\s*5|分)?', section)
    if numeric:
        value = int(numeric.group(1))
        if 0 <= value <= 5:
            return value
    level_map = {'强': 5, '中': 3, '弱': 1, '无': 0, '暂缺': 0}
    level = re.search(r'(?:护城河(?:强度)?评分|护城河强度|壁垒强度)[^\n:：]*[:：]?\s*(强|中|弱|无|暂缺)', section)
    if level:
        return level_map.get(level.group(1))
    return None


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