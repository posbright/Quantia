#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""行业 → IPC 保底估算单元测试。"""
from quantia.core.patent_industry_ipc import estimate_ipc_distribution


def test_unmatched_industry_returns_none():
    assert estimate_ipc_distribution('不存在的行业xyz', 100) is None
    assert estimate_ipc_distribution('', 100) is None
    assert estimate_ipc_distribution(None, 100) is None


def test_battery_industry_primary_is_h01():
    est = estimate_ipc_distribution('电源设备', 43354)
    assert est is not None
    assert est['ipc_primary'] == 'H01'
    assert est['estimated'] is True
    assert est['ipc_source'] == 'industry'
    assert est['ipc_primary_desc']  # 有中文描述
    assert est['tech_domain']


def test_distribution_sums_to_100():
    for ind in ('半导体', '消费电子设备', '汽车', '生物医药', '化学制品',
                '通用设备', '互联网金融', '铁路设备', '白色家电', '食品'):
        est = estimate_ipc_distribution(ind, 1000)
        assert est is not None, ind
        dist = est['ipc_distribution']
        assert sum(dist.values()) == 100, (ind, dist)
        assert all(v >= 0 for v in dist.values())
        # 主分类应是占比最高项
        assert est['ipc_primary'] == max(dist, key=dist.get)


def test_keyword_substring_match():
    # cn_stock_selection 中的真实变体名都应命中
    assert estimate_ipc_distribution('消费电子设备', 100)['ipc_primary'] == 'H01'
    assert estimate_ipc_distribution('电子设备制造', 100) is not None
    assert estimate_ipc_distribution('光电子器件', 100) is not None
    assert estimate_ipc_distribution('互联网金融', 100)['ipc_primary'] == 'G06'


def test_specific_before_generic():
    # 半导体 应走半导体画像(H01 0.45)，而非被泛"电子"覆盖
    semi = estimate_ipc_distribution('半导体', 100)
    assert semi['ipc_distribution']['H01'] == 45
