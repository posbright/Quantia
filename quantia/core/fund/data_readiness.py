#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""基金评分截面完整度门控纯函数。"""

import statistics


def evaluate(snapshot_date, expected_snapshot, latest_count, previous_counts,
             fresh_count, core_count, size_threshold=0.9, freshness_threshold=0.9):
    """评估日期、规模、新鲜度三门槛，返回可审计结构。"""
    previous = [int(value) for value in (previous_counts or []) if value is not None and int(value) > 0]
    median_count = statistics.median(previous) if previous else None
    size_ratio = (float(latest_count) / median_count) if median_count else None
    freshness_ratio = (float(fresh_count) / int(core_count)) if core_count else None
    reasons = []
    if snapshot_date is None or expected_snapshot is None:
        reasons.append('缺少快照日或交易日历')
    elif snapshot_date != expected_snapshot:
        reasons.append(f'最新基金快照 {snapshot_date}，期望 {expected_snapshot}')
    if size_ratio is None:
        reasons.append('缺少历史快照规模基线')
    elif size_ratio < size_threshold:
        reasons.append(f'快照规模完整度 {size_ratio:.1%} < {size_threshold:.0%}')
    if freshness_ratio is None:
        reasons.append('核心类型无可统计基金')
    elif freshness_ratio < freshness_threshold:
        reasons.append(f'核心类型净值新鲜度 {freshness_ratio:.1%} < {freshness_threshold:.0%}')
    return {
        'ready': not reasons,
        'snapshot_date': snapshot_date,
        'expected_snapshot': expected_snapshot,
        'latest_count': int(latest_count or 0),
        'previous_median': median_count,
        'size_ratio': size_ratio,
        'fresh_count': int(fresh_count or 0),
        'core_count': int(core_count or 0),
        'freshness_ratio': freshness_ratio,
        'reasons': reasons,
    }