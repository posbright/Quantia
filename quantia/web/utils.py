#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Web 层公共工具函数

将被 backtestHandler.py 和 backtestDashboardHandler.py 等共用的
工具函数统一提取到此处，避免代码重复。
"""

import datetime
import numpy as np
import pandas as pd

__author__ = 'Quantia'
__date__ = '2026/03/19'


def parse_int_list(csv_text, *, default=None, min_value=1, max_value=None, max_items=20):
    """解析逗号分隔的整数列表，带范围校验和去重排序。

    Args:
        csv_text: 逗号分隔的字符串，如 "1,3,5,10"
        default: csv_text 为空时的默认列表
        min_value: 最小允许值
        max_value: 最大允许值（None 不限）
        max_items: 最大项数（None 不限）

    Returns:
        排序去重后的整数列表
    """
    if not csv_text:
        return list(default) if default is not None else []
    values = []
    for part in str(csv_text).split(','):
        part = part.strip()
        if not part:
            continue
        try:
            v = int(part)
        except Exception:
            continue
        if v < min_value:
            continue
        if max_value is not None and v > max_value:
            continue
        values.append(v)
    values = sorted(set(values))
    if max_items is not None and len(values) > max_items:
        values = values[:max_items]
    return values


def json_default(obj):
    """JSON 序列化辅助：处理 datetime、numpy、pandas 类型。"""
    if isinstance(obj, (datetime.date, datetime.datetime)):
        return obj.strftime("%Y-%m-%d")
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return round(float(obj), 4) if not np.isnan(obj) else None
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if pd.isna(obj):
        return None
    return str(obj)
