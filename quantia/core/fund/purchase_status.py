#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""基金申购状态归一化纯函数。"""

import datetime

AVAILABLE = 'available'
LIMITED = 'limited'
UNAVAILABLE = 'unavailable'
UNKNOWN = 'unknown'

_UNAVAILABLE_MARKERS = ('暂停申购', '停止申购', '封闭', '不可申购')
_LIMITED_MARKERS = ('限大额', '限购', '限制申购')


def classify(status, fetched_at=None, as_of=None, max_age_days=2):
    """映射原始申购状态；缺失、未知或过期一律返回 unknown。"""
    if _is_stale(fetched_at, as_of, max_age_days):
        return UNKNOWN
    text = str(status or '').strip()
    if not text:
        return UNKNOWN
    if any(marker in text for marker in _UNAVAILABLE_MARKERS):
        return UNAVAILABLE
    if any(marker in text for marker in _LIMITED_MARKERS):
        return LIMITED
    if text == '开放申购':
        return AVAILABLE
    return UNKNOWN


def _is_stale(fetched_at, as_of, max_age_days):
    if fetched_at is None:
        return True
    fetched_date = fetched_at.date() if isinstance(fetched_at, datetime.datetime) else fetched_at
    if not isinstance(fetched_date, datetime.date):
        try:
            fetched_date = datetime.date.fromisoformat(str(fetched_at)[:10])
        except (TypeError, ValueError):
            return True
    current = as_of or datetime.date.today()
    if isinstance(current, datetime.datetime):
        current = current.date()
    return (current - fetched_date).days > max_age_days