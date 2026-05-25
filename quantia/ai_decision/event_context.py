# -*- coding: utf-8 -*-
"""事件上下文构建器 — 为 AI Gate 提供风险/机会事件信息。

调用方式：
    from quantia.ai_decision.event_context import build_event_context
    ctx = build_event_context(code='600519', lookback_days=30)

返回结构：
    {
        'recent_announcements': [...],
        'risk_events': [...],
        'opportunity_events': [...],
        'news_sentiment': 'positive' | 'negative' | 'neutral',
    }
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


def build_event_context(
    code: str,
    lookback_days: int = 30,
    max_events: int = 20,
) -> Dict[str, Any]:
    """从 cn_stock_announcement 表查询近期公告，分类为风险/机会事件。

    Args:
        code: 6位股票代码
        lookback_days: 回溯天数（默认30）
        max_events: 最大返回事件数

    Returns:
        事件上下文字典，即使查询失败也返回空结构（不抛异常）
    """
    empty = {
        'recent_announcements': [],
        'risk_events': [],
        'opportunity_events': [],
        'news_sentiment': 'neutral',
    }

    try:
        import quantia.lib.database as mdb
    except Exception:
        return empty

    since = (datetime.now() - timedelta(days=lookback_days)).strftime('%Y-%m-%d')

    sql = """
        SELECT ann_date, title, ann_type, tag, url
        FROM cn_stock_announcement
        WHERE code = %s AND ann_date >= %s
        ORDER BY ann_date DESC
        LIMIT %s
    """

    try:
        rows = mdb.executeSqlFetch(sql, (code, since, max_events))
    except Exception as e:
        log.debug(f"[event_context] 查询公告失败: {e}")
        return empty

    if not rows:
        return empty

    announcements = []
    risk_events = []
    opportunity_events = []

    for row in rows:
        ann_date, title, ann_type, tag, url = row
        item = {
            'date': str(ann_date) if ann_date else '',
            'title': title or '',
            'type': ann_type or '',
            'tag': tag or 'neutral',
        }
        announcements.append(item)

        if tag == 'risk':
            risk_events.append({
                'type': _infer_risk_type(title, ann_type),
                'date': item['date'],
                'desc': title,
            })
        elif tag == 'opportunity':
            opportunity_events.append({
                'type': _infer_opportunity_type(title, ann_type),
                'date': item['date'],
                'desc': title,
            })

    # 简单情绪判断：风险事件 > 机会事件 → negative
    if len(risk_events) > len(opportunity_events) + 2:
        sentiment = 'negative'
    elif len(opportunity_events) > len(risk_events) + 2:
        sentiment = 'positive'
    else:
        sentiment = 'neutral'

    return {
        'recent_announcements': announcements[:10],
        'risk_events': risk_events,
        'opportunity_events': opportunity_events,
        'news_sentiment': sentiment,
    }


def _infer_risk_type(title: str, ann_type: str) -> str:
    """从标题推断风险子类型。"""
    text = f"{title} {ann_type}"
    if 'ST' in text or '退市' in text:
        return 'st_warning'
    if '处罚' in text or '违规' in text or '警示' in text:
        return 'regulatory_action'
    if '立案' in text or '调查' in text:
        return 'investigation'
    if '诉讼' in text or '仲裁' in text:
        return 'litigation'
    if '冻结' in text:
        return 'asset_freeze'
    if '预亏' in text or '首亏' in text or '续亏' in text:
        return 'major_loss'
    if '预减' in text:
        return 'earnings_miss'
    return 'general_risk'


def _infer_opportunity_type(title: str, ann_type: str) -> str:
    """从标题推断机会子类型。"""
    text = f"{title} {ann_type}"
    if '专利' in text or '授权' in text:
        return 'patent_grant'
    if '中标' in text or '合同' in text or '签约' in text:
        return 'contract_win'
    if '增持' in text or '回购' in text:
        return 'insider_buy'
    if '预增' in text or '扭亏' in text or '续盈' in text:
        return 'earnings_beat'
    if '补贴' in text or '政策' in text:
        return 'policy_support'
    if '战略' in text or '合作' in text:
        return 'strategic_partnership'
    return 'general_opportunity'
