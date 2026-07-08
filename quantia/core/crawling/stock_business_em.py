#!/usr/bin/env python
# -*- coding:utf-8 -*-
"""
东方财富网-个股-F10-经营分析（公司概况）。
https://emweb.securities.eastmoney.com/PC_HSF10/BusinessAnalysis/index?code=SZ000651

单接口 PageAjax 一次返回三段：
  - zyfw   : 经营范围（BUSINESS_SCOPE）
  - zygcfx : 主营构成明细（按行业/产品/地区拆分，多报告期）
  - jyps   : 经营评述（BUSINESS_REVIEW，最新报告期长文本）

本模块只负责抓取 + 解析为纯 Python 结构，落库由 fetch_company_profile_job 负责
（遵循 Fetch/Analysis/Web 管道分离：只有 Fetch 管道可调用外部 API）。
"""
import datetime
import logging
from collections import defaultdict

from quantia.core.eastmoney_fetcher import eastmoney_fetcher

__author__ = 'Quantia'
__date__ = '2026/06/26'

_logger = logging.getLogger(__name__)

# 创建全局实例，供所有函数使用
fetcher = eastmoney_fetcher()

_BUSINESS_URL = "https://emweb.securities.eastmoney.com/PC_HSF10/BusinessAnalysis/PageAjax"

# 经营评述长文本落库上限（TEXT 列 64KB，中文 3 字节/字；8000 字≈24KB，安全且展示够用）
_REVIEW_MAX_CHARS = 8000
_SCOPE_MAX_CHARS = 4000

# 主营构成分类维度：东方财富 MAINOP_TYPE 编码 → 中文
_MAINOP_TYPE_MAP = {'1': '行业', '2': '产品', '3': '地区'}

# 主营构成维度过期阈值（天）：某维度自身最新披露期距全局最新披露期超过此值即视为
# 已停止披露而丢弃。取 450 天（约 15 个月）——既能保留「按产品仅在半年报披露、按地区
# 在年报披露」这类正常错期（如浦发银行按产品 2025-06-30 vs 按地区 2025-12-31），
# 又能丢弃多年前的僵尸维度（如平安/紫金按行业停留在 2019-12-31）。
_MAINOP_STALE_DAYS = 450


class BusinessFetchError(Exception):
    """经营分析抓取传输层失败（网络异常 / 东方财富封禁 / 返回非 JSON 的反爬页）。

    与"响应正常但无经营分析数据"（返回 None）明确区分：上层 job 据此实现熔断——
    连续多只 BusinessFetchError 视为数据源不可用，提前中止本轮，避免空转 + 加剧封禁。
    """


def to_secid(code):
    """6 位股票代码 → 东方财富 F10 secid（带交易所字母前缀）。

    - 6xxxxx（沪市 A）/ 9xxxxx（沪市 B，如 900xxx）→ SH
    - 4xxxxx / 8xxxxx / 920xxx（北交所）→ BJ
    - 其余（0/2/3 开头，深市 A / B / 创业板）→ SZ
    """
    c = str(code).strip().zfill(6)
    # 北交所新代码段 920xxx 以 9 开头，必须先于「9→沪市 B」判断，否则会误路由到 SH
    if c.startswith('92') or c[0] in ('4', '8'):
        return 'BJ' + c
    if c[0] in ('6', '9'):
        return 'SH' + c
    return 'SZ' + c


def _report_date_str(raw):
    """'2025-12-31 00:00:00' → '2025-12-31'；解析失败返回 None。"""
    if not raw:
        return None
    s = str(raw).strip()
    if not s:
        return None
    return s[:10]


def _parse_date(s):
    """'2025-12-31' → date；失败返回 None。"""
    if not s:
        return None
    try:
        return datetime.date.fromisoformat(str(s)[:10])
    except (ValueError, TypeError):
        return None


def _to_float(v):
    if v is None or v == '':
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


def stock_business_composition(code):
    """抓取单只个股的公司概况（经营范围 / 主营构成 / 经营评述）。

    :param code: 6 位股票代码，例如 '000651'
    :raises BusinessFetchError: 传输层失败（网络异常 / 东方财富封禁 / 返回非 JSON）
    :return: dict 或 None（响应正常但无任何有效字段时返回 None）
        {
          'report_date': '2025-12-31' | None,
          'business_scope': str | None,
          'business_review': str | None,
          'mainop': [
             {'type': '行业'|'产品'|'地区', 'item': str, 'income': float|None,
              'income_ratio': float|None, 'gross_profit_ratio': float|None,
              'rank': int|None, 'report_date': 'YYYY-MM-DD'},
             ...
          ]  # 各维度取自身最新披露期（可能不同），已剔除多年未披露的僵尸维度
        }
    """
    secid = to_secid(code)
    try:
        r = fetcher.make_request(_BUSINESS_URL, params={"code": secid})
        data_json = r.json()
    except Exception as exc:  # 传输层失败（make_request 用尽重试 / 返回非 JSON 的封禁反爬页）
        # 抛出显式异常而非降级 None：让上层 job 能区分"封禁/网络故障"与"无数据"，据此熔断。
        raise BusinessFetchError(f'{code}({secid}) 抓取失败: {exc}') from exc

    if not isinstance(data_json, dict):
        # 响应可解析但结构异常，视为无数据（非封禁信号），返回 None。
        return None

    # 1) 经营范围
    business_scope = None
    zyfw = data_json.get('zyfw') or []
    if zyfw and isinstance(zyfw[0], dict):
        scope = zyfw[0].get('BUSINESS_SCOPE')
        if scope:
            business_scope = str(scope).strip()[:_SCOPE_MAX_CHARS]

    # 2) 经营评述 + 报告期
    business_review = None
    review_report_date = None
    jyps = data_json.get('jyps') or []
    if jyps and isinstance(jyps[0], dict):
        review = jyps[0].get('BUSINESS_REVIEW')
        if review:
            business_review = str(review).strip()[:_REVIEW_MAX_CHARS]
        review_report_date = _report_date_str(jyps[0].get('REPORT_DATE'))

    # 3) 主营构成明细（多报告期，多维度）
    #    关键：不同维度（按行业/产品/地区）的最新披露期可能不同——银行常按产品披露到半年报、
    #    按地区披露到年报；部分公司某维度多年未再披露（如平安/紫金按行业停在 2019）。
    #    因此对每个维度取其"自身最新披露期"，但丢弃距全局最新披露期过久（>_MAINOP_STALE_DAYS）
    #    的僵尸维度，避免既丢失有效近期维度、又混入多年前的陈旧口径。
    mainop = []
    mainop_report_date = None
    zygcfx = data_json.get('zygcfx') or []
    rows = [row for row in zygcfx if isinstance(row, dict)]

    type_dates = defaultdict(set)
    for row in rows:
        d = _report_date_str(row.get('REPORT_DATE'))
        if d:
            type_dates[str(row.get('MAINOP_TYPE'))].add(d)

    all_dates = set()
    for ds in type_dates.values():
        all_dates |= ds
    if all_dates:
        global_max = max(all_dates)          # 全局最新披露期（用作整表 report_date）
        mainop_report_date = global_max
        gm_date = _parse_date(global_max)
        # 每个维度取自身最新披露期，过期维度剔除
        keep_type_date = {}
        for t, ds in type_dates.items():
            d_latest = max(ds)
            dd = _parse_date(d_latest)
            if gm_date and dd and (gm_date - dd).days > _MAINOP_STALE_DAYS:
                continue
            keep_type_date[t] = d_latest

        for row in rows:
            t = str(row.get('MAINOP_TYPE'))
            d = _report_date_str(row.get('REPORT_DATE'))
            if t not in keep_type_date or d != keep_type_date[t]:
                continue
            item_name = row.get('ITEM_NAME')
            if not item_name:
                continue
            rank = row.get('RANK')
            try:
                rank = int(rank) if rank is not None else None
            except (TypeError, ValueError):
                rank = None
            mainop.append({
                'type': _MAINOP_TYPE_MAP.get(t, '其他'),
                'item': str(item_name).strip(),
                'income': _to_float(row.get('MAIN_BUSINESS_INCOME')),
                'income_ratio': _to_float(row.get('MBI_RATIO')),
                'gross_profit_ratio': _to_float(row.get('GROSS_RPOFIT_RATIO')),
                'rank': rank,
                'report_date': d,  # 该维度自身报告期（可能与整表 report_date 不同）
            })
        # 稳定排序：先按维度（行业→产品→地区→其他），再按 rank
        _type_order = {'行业': 0, '产品': 1, '地区': 2, '其他': 3}
        mainop.sort(key=lambda x: (_type_order.get(x['type'], 9),
                                   x['rank'] if x['rank'] is not None else 999))

    # 报告期优先取主营构成（更能代表财务口径），退化到经营评述
    report_date = mainop_report_date or review_report_date

    if not business_scope and not business_review and not mainop:
        return None

    return {
        'report_date': report_date,
        'business_scope': business_scope,
        'business_review': business_review,
        'mainop': mainop,
    }
