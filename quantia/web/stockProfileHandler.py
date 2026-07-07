#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""个股公司概况 / 基本面 API。

端点：
- GET /quantia/api/stock/profile?code=XXX

数据来源：`cn_stock_selection`（综合选股表，最新交易日）。该表的
行业(industry)/地区(area)/概念(concept)/板块(style)/营业总收入(total_operate_income)
覆盖率 100%，配合总市值/PE/PB/ROE/毛利率/净利率等财务字段，用于个股详情页
「公司概况」卡片展示，替代旧「知识产权/护城河」在无专利数据时的空占位。

架构约束：
- 只读 MySQL，不调用任何外部 API（铁律 1）。
- 显式列清单 SELECT，运行时先校验表存在（铁律 7），不假设 tablestructure.py 已部署。
"""

from __future__ import annotations

import json
import logging
import math
from abc import ABC
from typing import Any, Dict, Optional

from tornado import gen

import quantia.lib.database as mdb
import quantia.web.base as webBase

__author__ = 'Quantia'
__date__ = '2026/07'

_logger = logging.getLogger(__name__)

SELECTION_TABLE = 'cn_stock_selection'

# 显式列清单（顺序即取值顺序）。均为 cn_stock_selection 真实列。
_PROFILE_COLUMNS = (
    'date', 'code', 'name',
    'industry', 'area', 'concept', 'style', 'listing_date',
    'total_operate_income', 'parent_netprofit',
    'total_market_cap', 'free_cap',
    'pe9', 'pbnewmrq', 'roe_weight',
    'sale_gpr', 'sale_npr', 'netprofit_yoy_ratio', 'zxgxl',
)

# 需要拆分为标签数组的逗号分隔文本列
_TAG_COLUMNS = {'concept', 'style'}


def _sanitize(val: Any) -> Any:
    """把 NaN/inf 归一为 None，datetime/date 归一为 isoformat 字符串。"""
    if isinstance(val, float):
        return val if math.isfinite(val) else None
    if hasattr(val, 'isoformat'):
        try:
            return val.isoformat()
        except Exception:
            return str(val)
    return val


def _split_tags(text: Any) -> list:
    """将 '概念A, 概念B' 逗号分隔文本拆为去重去空的标签列表。"""
    if not text or not isinstance(text, str):
        return []
    seen = []
    for part in text.replace('，', ',').split(','):
        item = part.strip()
        if item and item not in seen:
            seen.append(item)
    return seen


def _write_json(handler, data: Dict[str, Any], status: int = 200) -> None:
    handler.set_status(status)
    handler.set_header('Content-Type', 'application/json; charset=UTF-8')
    handler.write(json.dumps(data, ensure_ascii=False, default=str))


def _table_exists() -> bool:
    try:
        return mdb.checkTableIsExist(SELECTION_TABLE)
    except Exception:
        return False


def _fetch_profile(code: str) -> Optional[Dict[str, Any]]:
    cols = ', '.join(f'`{c}`' for c in _PROFILE_COLUMNS)
    try:
        rows = mdb.executeSqlFetch(
            f"SELECT {cols} FROM `{SELECTION_TABLE}` WHERE code=%s "
            f"ORDER BY date DESC LIMIT 1",
            (code,),
        )
    except Exception as exc:  # pragma: no cover - depends on live DB
        _logger.warning('[profile] _fetch_profile failed: %s', exc)
        return None
    if not rows:
        return None
    out: Dict[str, Any] = {}
    for col, val in zip(_PROFILE_COLUMNS, rows[0]):
        val = _sanitize(val)
        if col in _TAG_COLUMNS:
            out[col] = _split_tags(val)
        else:
            out[col] = val
    return out


class StockProfileHandler(webBase.BaseHandler, ABC):
    """GET /quantia/api/stock/profile?code=XXX — 公司概况 / 基本面。"""

    @gen.coroutine
    def get(self):
        code = (self.get_argument('code', '') or '').strip()
        if not code or len(code) != 6 or not code.isdigit():
            _write_json(self, {'error': 'code 必须是6位数字'}, 400)
            return

        if not _table_exists():
            _write_json(self, {'code': code, 'data': None, 'reason': '选股表不存在'})
            return

        data = _fetch_profile(code)
        if data is None:
            _write_json(self, {'code': code, 'data': None, 'reason': '暂无公司概况数据'})
            return

        _write_json(self, {'code': code, 'data': data})
