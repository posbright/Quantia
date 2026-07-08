#!/usr/bin/env python
# -*- coding:utf-8 -*-
"""同花顺 F10 主营介绍——公司概况备用源（东方财富封禁/不可用时降级）。

经 akshare `stock_zyjs_ths` 抓取，走同花顺独立基础设施（IP 信誉体系与东方财富
不同），故可对冲东财针对 F10 的封禁。**注意其为降级源**：

  - 提供：经营范围（BUSINESS_SCOPE）、主营业务/产品类型定性描述。
  - 不提供：定量主营构成（收入占比 / 毛利率 / 分行业·产品·地区）——该定量数据为
    东方财富独有，同花顺该接口不含占比，故 mainop 返回空（**绝不编造占比**），
    待东财恢复后下一轮采集补齐。

属 fetch 管道（只有 Fetch 管道可调用外部 API）。返回结构与
`stock_business_em.stock_business_composition` 归一，供 fetch job 无缝落库。
"""
import logging

from quantia.core.crawling.stock_business_em import (
    BusinessFetchError,
    _REVIEW_MAX_CHARS,
    _SCOPE_MAX_CHARS,
)

__author__ = 'Quantia'
__date__ = '2026/07/08'

_logger = logging.getLogger(__name__)


def stock_business_composition_ths(code):
    """同花顺主营介绍（降级源）。

    :param code: 6 位股票代码，例如 '000651'
    :raises BusinessFetchError: 传输层失败（网络异常 / 同花顺反爬 / akshare 抛错）
    :return: dict 或 None（无任何有效字段时返回 None）
        {
          'report_date': None,            # 同花顺主营介绍无报告期
          'business_scope': str | None,   # 经营范围
          'business_review': str | None,  # 主营业务 + 主要产品（定性合成）
          'mainop': [],                   # 同花顺无定量占比，恒为空（不编造）
          'source': 'ths',
        }
    """
    code6 = str(code).strip().zfill(6)
    try:
        import akshare as ak
        df = ak.stock_zyjs_ths(symbol=code6)
    except Exception as exc:  # akshare 抛出异常类型繁杂，统一视为传输层失败
        raise BusinessFetchError(f'{code6} 同花顺主营介绍抓取失败: {exc}') from exc

    if df is None or getattr(df, 'empty', True):
        return None

    row = df.iloc[0].to_dict()

    def _clean(v):
        if v is None:
            return None
        s = str(v).strip()
        if not s or s.lower() == 'nan':
            return None
        return s

    scope = _clean(row.get('经营范围'))
    if scope:
        scope = scope[:_SCOPE_MAX_CHARS]

    main_biz = _clean(row.get('主营业务'))
    prod = _clean(row.get('产品类型'))
    parts = []
    if main_biz:
        parts.append(main_biz)
    if prod:
        parts.append('主要产品：' + prod)
    review = '；'.join(parts)[:_REVIEW_MAX_CHARS] if parts else None

    if not scope and not review:
        return None

    return {
        'report_date': None,
        'business_scope': scope,
        'business_review': review,
        'mainop': [],  # 同花顺无定量主营构成占比，留空，绝不编造
        'source': 'ths',
    }
