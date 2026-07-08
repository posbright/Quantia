# -*- coding: utf-8 -*-
"""公司概况（F10 经营分析）抓取解析 + handler 解析单元测试。

覆盖：
- to_secid 交易所前缀路由
- stock_business_composition 解析 zyfw/zygcfx/jyps，最新报告期筛选、主营构成分组排序
- StockBusinessHandler._parse_mainop JSON 字符串解析容错

全部 mock，不打外部 API / 不连 DB。
"""
from unittest import mock

import quantia.core.crawling.stock_business_em as sbe
import quantia.web.stockProfileHandler as sph


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _sample_payload():
    return {
        'zyfw': [{'SECUCODE': '000651.SZ', 'BUSINESS_SCOPE': '制冷、空调设备制造;家用电器销售'}],
        'jyps': [{'SECUCODE': '000651.SZ', 'REPORT_DATE': '2025-12-31 00:00:00',
                  'BUSINESS_REVIEW': '公司是一家多元化科技型全球工业集团。'}],
        'zygcfx': [
            # 最新报告期
            {'REPORT_DATE': '2025-12-31 00:00:00', 'MAINOP_TYPE': '2', 'ITEM_NAME': '消费电器',
             'MAIN_BUSINESS_INCOME': 133055208627.13, 'MBI_RATIO': 0.780625,
             'GROSS_RPOFIT_RATIO': 0.352806, 'RANK': 1},
            {'REPORT_DATE': '2025-12-31 00:00:00', 'MAINOP_TYPE': '1', 'ITEM_NAME': '制造业',
             'MAIN_BUSINESS_INCOME': 153781972343.46, 'MBI_RATIO': 0.902227,
             'GROSS_RPOFIT_RATIO': 0.327466, 'RANK': 1},
            {'REPORT_DATE': '2025-12-31 00:00:00', 'MAINOP_TYPE': '3', 'ITEM_NAME': '内销',
             'MAIN_BUSINESS_INCOME': 126407077425.42, 'MBI_RATIO': 0.741621,
             'GROSS_RPOFIT_RATIO': 0.345242, 'RANK': 1},
            # 旧报告期（应被过滤）
            {'REPORT_DATE': '2016-12-31 00:00:00', 'MAINOP_TYPE': '1', 'ITEM_NAME': '空调',
             'MAIN_BUSINESS_INCOME': 88000000000.0, 'MBI_RATIO': 0.8,
             'GROSS_RPOFIT_RATIO': 0.3, 'RANK': 1},
        ],
    }


def test_to_secid_routing():
    assert sbe.to_secid('600519') == 'SH600519'
    assert sbe.to_secid('000651') == 'SZ000651'
    assert sbe.to_secid('300750') == 'SZ300750'
    assert sbe.to_secid('831832') == 'BJ831832'  # 北交所 8 开头
    assert sbe.to_secid('430047') == 'BJ430047'  # 北交所 4 开头
    assert sbe.to_secid('920819') == 'BJ920819'  # 北交所新代码段 920（须先于 9→SH 判断）
    assert sbe.to_secid('900957') == 'SH900957'  # 沪市 B 股 900
    assert sbe.to_secid('651') == 'SZ000651'     # 补零


def test_stock_business_composition_parsing():
    with mock.patch.object(sbe.fetcher, 'make_request', return_value=_FakeResp(_sample_payload())):
        out = sbe.stock_business_composition('000651')
    assert out is not None
    assert out['report_date'] == '2025-12-31'
    assert out['business_scope'].startswith('制冷')
    assert out['business_review'].startswith('公司是一家')
    # 只保留最新报告期（2016 的“空调”应被过滤）
    items = out['mainop']
    assert all(it['item'] != '空调' for it in items)
    assert len(items) == 3
    # 分组排序：行业 → 产品 → 地区
    types_in_order = [it['type'] for it in items]
    assert types_in_order == ['行业', '产品', '地区']
    manufacturing = next(it for it in items if it['item'] == '制造业')
    assert manufacturing['income'] == 153781972343.46
    assert abs(manufacturing['income_ratio'] - 0.902227) < 1e-6
    assert abs(manufacturing['gross_profit_ratio'] - 0.327466) < 1e-6
    # 每个明细项携带其维度自身报告期
    assert all(it['report_date'] == '2025-12-31' for it in items)


def _mixed_period_payload():
    """模拟真实场景：不同维度最新披露期不同。
    - 按行业(type1) 最新停在 2019-12-31（多年未再披露，应被剔除）
    - 按产品(type2) 最新为 2025-06-30（半年报，距全局最新 <450 天，应保留）
    - 按地区(type3) 最新为 2025-12-31（年报，全局最新）
    """
    return {
        'zyfw': [{'BUSINESS_SCOPE': '银行业务'}],
        'jyps': [{'REPORT_DATE': '2025-12-31 00:00:00', 'BUSINESS_REVIEW': '经营评述。'}],
        'zygcfx': [
            {'REPORT_DATE': '2025-12-31 00:00:00', 'MAINOP_TYPE': '3', 'ITEM_NAME': '华东地区',
             'MAIN_BUSINESS_INCOME': 5e10, 'MBI_RATIO': 0.5, 'GROSS_RPOFIT_RATIO': 0.4, 'RANK': 1},
            {'REPORT_DATE': '2025-06-30 00:00:00', 'MAINOP_TYPE': '2', 'ITEM_NAME': '对公业务',
             'MAIN_BUSINESS_INCOME': 6e10, 'MBI_RATIO': 0.6, 'GROSS_RPOFIT_RATIO': 0.45, 'RANK': 1},
            {'REPORT_DATE': '2025-06-30 00:00:00', 'MAINOP_TYPE': '2', 'ITEM_NAME': '零售业务',
             'MAIN_BUSINESS_INCOME': 4e10, 'MBI_RATIO': 0.4, 'GROSS_RPOFIT_RATIO': 0.35, 'RANK': 2},
            # 陈旧行业维度（2019），应被整体剔除
            {'REPORT_DATE': '2019-12-31 00:00:00', 'MAINOP_TYPE': '1', 'ITEM_NAME': '金融业',
             'MAIN_BUSINESS_INCOME': 3e10, 'MBI_RATIO': 1.0, 'GROSS_RPOFIT_RATIO': 0.3, 'RANK': 1},
        ],
    }


def test_stock_business_composition_per_dimension_latest_period():
    """回归：不同维度取各自最新期，保留近期错期维度、剔除多年僵尸维度。"""
    with mock.patch.object(sbe.fetcher, 'make_request',
                           return_value=_FakeResp(_mixed_period_payload())):
        out = sbe.stock_business_composition('600000')
    assert out is not None
    # 整表报告期 = 全局最新 2025-12-31
    assert out['report_date'] == '2025-12-31'
    items = out['mainop']
    types = {it['type'] for it in items}
    # 陈旧的“按行业”(2019) 被剔除
    assert '行业' not in types
    assert all(it['item'] != '金融业' for it in items)
    # “按产品”(2025-06-30, 半年报) 被保留，且携带其自身报告期
    product_items = [it for it in items if it['type'] == '产品']
    assert len(product_items) == 2
    assert all(it['report_date'] == '2025-06-30' for it in product_items)
    # “按地区”(2025-12-31) 保留
    region_items = [it for it in items if it['type'] == '地区']
    assert len(region_items) == 1
    assert region_items[0]['report_date'] == '2025-12-31'
    # 排序：产品在地区之前
    assert [it['type'] for it in items] == ['产品', '产品', '地区']


def test_stock_business_composition_empty_returns_none():
    empty = {'zyfw': [], 'jyps': [], 'zygcfx': []}
    with mock.patch.object(sbe.fetcher, 'make_request', return_value=_FakeResp(empty)):
        assert sbe.stock_business_composition('000651') is None


def test_stock_business_composition_request_failure_returns_none():
    with mock.patch.object(sbe.fetcher, 'make_request', side_effect=RuntimeError('boom')):
        assert sbe.stock_business_composition('000651') is None


def test_handler_parse_mainop():
    assert sph._parse_mainop(None) == []
    assert sph._parse_mainop('') == []
    assert sph._parse_mainop('not-json') == []
    assert sph._parse_mainop('[{"item":"x"}]') == [{'item': 'x'}]
    # 已是 list 时原样返回
    assert sph._parse_mainop([{'item': 'y'}]) == [{'item': 'y'}]
    # JSON 对象（非 list）应归一为空 list
    assert sph._parse_mainop('{"a":1}') == []
