#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""场外开放式基金排名 API Handler（F6 方案 A，第一期 MVP）。

只读 MySQL（遵守 Fetch/Analysis/Web 分离原则）：直接读 cn_fund_rank，
按 fund_type 分桶后按指定周期收益率排序，零计算成本。

端点：
- GET /quantia/api/fund/rank/meta         返回可选基金类型 + 排序周期元数据
- GET /quantia/api/fund/rank?...          按类型+周期返回排名列表
"""

import json
import logging
import math

import pandas as pd

import quantia.core.tablestructure as tbs
import quantia.lib.database as mdb
import quantia.web.base as webBase

__author__ = 'Quantia'
__date__ = '2026/06/01'

logger = logging.getLogger(__name__)

_FUND_RANK_TABLE = tbs.TABLE_CN_FUND_RANK['name']

# 基金类型桶（与 fund_em._NAV_TYPES + 货币型一致）。
_FUND_TYPES = ['股票型', '混合型', '债券型', '指数型', 'QDII', 'FOF', '货币型']

# 可排序周期列白名单（防 SQL 注入：仅允许 cn_fund_rank 真实数值列）。
# label 供前端下拉展示；value 即列名。
_PERIOD_OPTIONS = [
    {'value': 'rate_1w', 'label': '近1周'},
    {'value': 'rate_1m', 'label': '近1月'},
    {'value': 'rate_3m', 'label': '近3月'},
    {'value': 'rate_6m', 'label': '近6月'},
    {'value': 'rate_1y', 'label': '近1年'},
    {'value': 'rate_2y', 'label': '近2年'},
    {'value': 'rate_3y', 'label': '近3年'},
    {'value': 'rate_ytd', 'label': '今年来'},
    {'value': 'rate_since', 'label': '成立来'},
    {'value': 'day_growth', 'label': '日增长率'},
    {'value': 'seven_day_annual', 'label': '7日年化(货币型)'},
]
_PERIOD_COLS = {o['value'] for o in _PERIOD_OPTIONS}

_DEFAULT_PERIOD = 'rate_1y'
_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200

# 返回给前端的展示列（固定顺序，避免 SELECT *）。
_DISPLAY_COLS = [
    'code', 'name', 'fund_type', 'nav_date', 'unit_nav', 'acc_nav', 'day_growth',
    'million_unit_income', 'seven_day_annual',
    'rate_1w', 'rate_1m', 'rate_3m', 'rate_6m', 'rate_1y', 'rate_2y', 'rate_3y',
    'rate_ytd', 'rate_since', 'fee',
]


def _json_default(o):
    """JSON 序列化兜底：NaN/Inf/日期/numpy 标量 → 可序列化值。"""
    if isinstance(o, float):
        return None if not math.isfinite(o) else o
    if hasattr(o, 'isoformat'):
        return o.isoformat()
    if hasattr(o, 'item'):
        return o.item()
    return str(o)


def _write_json(handler, data):
    handler.set_header('Content-Type', 'application/json;charset=UTF-8')
    handler.write(json.dumps(data, ensure_ascii=False, default=_json_default))


def _write_error(handler, msg, code=400):
    handler.set_status(code)
    _write_json(handler, {'error': msg})


def _clean_row(row):
    """逐值清洗：NaN/Inf → None，使 JSON 合法。"""
    out = {}
    for k, v in row.items():
        if isinstance(v, float) and not math.isfinite(v):
            out[k] = None
        elif v is None or (isinstance(v, float) and v != v):
            out[k] = None
        else:
            out[k] = v
    return out


class FundRankMetaHandler(webBase.BaseHandler):
    """GET /quantia/api/fund/rank/meta

    返回可选基金类型、排序周期、最新净值快照日，供前端构建筛选器。
    """

    def get(self):
        try:
            latest_date = None
            if mdb.checkTableIsExist(_FUND_RANK_TABLE):
                rows = mdb.executeSqlFetch(
                    f"SELECT MAX(`date`) AS d FROM `{_FUND_RANK_TABLE}`")
                if rows and rows[0] and rows[0][0] is not None:
                    d = rows[0][0]
                    latest_date = d.isoformat() if hasattr(d, 'isoformat') else str(d)
            _write_json(self, {
                'fund_types': _FUND_TYPES,
                'periods': _PERIOD_OPTIONS,
                'default_period': _DEFAULT_PERIOD,
                'default_limit': _DEFAULT_LIMIT,
                'latest_date': latest_date,
            })
        except Exception:
            logger.error("基金排名元数据异常", exc_info=True)
            _write_error(self, '服务器内部错误', 500)


class FundRankHandler(webBase.BaseHandler):
    """GET /quantia/api/fund/rank?fund_type=股票型&period=rate_1y&limit=50

    读 cn_fund_rank 最新快照日，按 fund_type 过滤后按 period 列降序排序，
    NULL 收益率排末尾。零计算，纯排序展示。
    """

    def get(self):
        try:
            fund_type = self.get_argument('fund_type', default=_FUND_TYPES[0])
            period = self.get_argument('period', default=_DEFAULT_PERIOD)
            limit_raw = self.get_argument('limit', default=str(_DEFAULT_LIMIT))

            if fund_type not in _FUND_TYPES:
                _write_error(self, f'不支持的基金类型: {fund_type}')
                return
            if period not in _PERIOD_COLS:
                _write_error(self, f'不支持的排序周期: {period}')
                return
            try:
                limit = int(limit_raw)
            except (TypeError, ValueError):
                limit = _DEFAULT_LIMIT
            limit = max(1, min(limit, _MAX_LIMIT))

            if not mdb.checkTableIsExist(_FUND_RANK_TABLE):
                _write_json(self, {'date': None, 'fund_type': fund_type,
                                   'period': period, 'count': 0, 'items': []})
                return

            cols_sql = ', '.join(f'`{c}`' for c in _DISPLAY_COLS)
            # period 已过白名单校验，安全拼入 ORDER BY；其余参数化。
            # NULL 收益率排末尾：`col IS NULL` 升序使非空在前。
            sql = (
                f"SELECT {cols_sql} FROM `{_FUND_RANK_TABLE}` "
                f"WHERE `date` = (SELECT MAX(`date`) FROM `{_FUND_RANK_TABLE}`) "
                f"AND `fund_type` = %s "
                f"ORDER BY (`{period}` IS NULL), `{period}` DESC "
                f"LIMIT %s"
            )
            df = pd.read_sql(sql, con=mdb.engine(), params=(fund_type, limit))

            snapshot_date = None
            date_rows = mdb.executeSqlFetch(
                f"SELECT MAX(`date`) FROM `{_FUND_RANK_TABLE}`")
            if date_rows and date_rows[0] and date_rows[0][0] is not None:
                d = date_rows[0][0]
                snapshot_date = d.isoformat() if hasattr(d, 'isoformat') else str(d)

            items = [_clean_row(r) for r in df.to_dict(orient='records')]
            _write_json(self, {
                'date': snapshot_date,
                'fund_type': fund_type,
                'period': period,
                'count': len(items),
                'items': items,
            })
        except Exception:
            logger.error("基金排名查询异常", exc_info=True)
            _write_error(self, '服务器内部错误', 500)
