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
_FUND_SCORE_TABLE = tbs.TABLE_CN_FUND_RANK_SCORE['name']
_FUND_PROFILE_TABLE = tbs.TABLE_CN_FUND_PROFILE['name']

# 基金类型桶（与 fund_em._NAV_TYPES + 货币型一致）。
_FUND_TYPES = ['股票型', '混合型', '债券型', '指数型', 'QDII', 'FOF', '货币型']

# 仅 A 股权益类桶支持「主行业」二级过滤（行业映射只覆盖 A 股，见 §3.5 F12）。
_EQUITY_TYPES = {'股票型', '混合型', '指数型'}

# 可排序周期列白名单（防 SQL 注入：仅允许真实数值列）。label 供前端下拉展示。
# 前缀 r. 列来自 cn_fund_rank；score 派生列（_SCORE_PERIOD_COLS）来自 cn_fund_rank_score。
_PERIOD_OPTIONS = [
    {'value': 'score', 'label': '综合评分'},
    {'value': 'rate_1w', 'label': '近1周'},
    {'value': 'rate_1m', 'label': '近1月'},
    {'value': 'rate_3m', 'label': '近3月'},
    {'value': 'rate_6m', 'label': '近6月'},
    {'value': 'rate_1y', 'label': '近1年'},
    {'value': 'rate_2y', 'label': '近2年'},
    {'value': 'rate_3y', 'label': '近3年'},
    {'value': 'rate_5y', 'label': '近5年'},
    {'value': 'rate_ytd', 'label': '今年来'},
    {'value': 'rate_since', 'label': '成立来'},
    {'value': 'sharpe', 'label': '夏普比率'},
    {'value': 'max_drawdown', 'label': '最大回撤'},
    {'value': 'excess_1y', 'label': '基准超额'},
    {'value': 'day_growth', 'label': '日增长率'},
    {'value': 'seven_day_annual', 'label': '7日年化(货币型)'},
]
_PERIOD_COLS = {o['value'] for o in _PERIOD_OPTIONS}

# 这些排序列存于 cn_fund_rank_score（s.），其余存于 cn_fund_rank（r.）。
# 全部 DESC 即"越好越靠前"：max_drawdown 为负数，DESC 把回撤小（接近 0）的排前。
_SCORE_PERIOD_COLS = {'score', 'sharpe', 'max_drawdown', 'excess_1y', 'rate_5y'}

_DEFAULT_PERIOD = 'score'
# 评分表缺失时，score 类排序回退到该 cn_fund_rank 列。
_DEFAULT_RATE_PERIOD = 'rate_1y'
_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200

# 返回给前端的展示列（固定顺序，避免 SELECT *）。
_DISPLAY_COLS = [
    'code', 'name', 'fund_type', 'nav_date', 'unit_nav', 'acc_nav', 'day_growth',
    'million_unit_income', 'seven_day_annual',
    'rate_1w', 'rate_1m', 'rate_3m', 'rate_6m', 'rate_1y', 'rate_2y', 'rate_3y',
    'rate_ytd', 'rate_since', 'fee',
]

# 评分表派生列（JOIN cn_fund_rank_score 带出，供净值型桶展示评分/夏普/回撤/超额/主行业）。
_SCORE_EXTRA_COLS = [
    'score', 'sharpe', 'max_drawdown', 'rate_5y', 'excess_1y', 'rank_in_type',
    'main_industry',
]

# 画像表派生列（JOIN cn_fund_profile 带出规模与评级）。
_PROFILE_EXTRA_COLS = ['scale_yi', 'rating']


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
            industry = (self.get_argument('industry', default='') or '').strip()

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

            # 行业过滤仅对 A 股权益类桶 + 评分表存在时生效；其它情况忽略该参数。
            has_score = mdb.checkTableIsExist(_FUND_SCORE_TABLE)
            has_profile = mdb.checkTableIsExist(_FUND_PROFILE_TABLE)
            apply_industry = (bool(industry) and fund_type in _EQUITY_TYPES
                              and has_score)

            if not mdb.checkTableIsExist(_FUND_RANK_TABLE):
                _write_json(self, {'date': None, 'fund_type': fund_type,
                                   'period': period, 'industry': industry or None,
                                   'count': 0, 'items': []})
                return

            # 排序目标：score 派生列走 s.（需评分表），否则走 r.。
            # 评分表缺失时 score 类排序回退到 cn_fund_rank 列，避免空排序。
            score_sort = period in _SCORE_PERIOD_COLS
            if score_sort and not has_score:
                effective_period = _DEFAULT_RATE_PERIOD
                score_sort = False
            else:
                effective_period = period
            sort_alias = 's' if score_sort else 'r'

            select_parts = [f'r.`{c}`' for c in _DISPLAY_COLS]
            joins = ''
            if has_score:
                select_parts += [f's.`{c}` AS `{c}`' for c in _SCORE_EXTRA_COLS]
                joins += (
                    f" LEFT JOIN `{_FUND_SCORE_TABLE}` s "
                    f"  ON s.`code` = r.`code` "
                    f"  AND s.`date` = (SELECT MAX(`date`) FROM `{_FUND_SCORE_TABLE}`)")
            if has_profile:
                select_parts += [f'p.`{c}` AS `{c}`' for c in _PROFILE_EXTRA_COLS]
                joins += (
                    f" LEFT JOIN `{_FUND_PROFILE_TABLE}` p ON p.`code` = r.`code`")

            params = [fund_type]
            where = (
                f"WHERE r.`date` = (SELECT MAX(`date`) FROM `{_FUND_RANK_TABLE}`) "
                f"  AND r.`fund_type` = %s ")
            if apply_industry:
                where += "AND s.`main_industry` = %s "
                params.append(industry)
            order = (f"ORDER BY ({sort_alias}.`{effective_period}` IS NULL), "
                     f"{sort_alias}.`{effective_period}` DESC")
            sql = (f"SELECT {', '.join(select_parts)} "
                   f"FROM `{_FUND_RANK_TABLE}` r{joins} {where}{order} LIMIT %s")
            params.append(limit)
            df = pd.read_sql(sql, con=mdb.engine_ro(), params=tuple(params))

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
                'industry': industry or None,
                'count': len(items),
                'items': items,
            })
        except Exception:
            logger.error("基金排名查询异常", exc_info=True)
            _write_error(self, '服务器内部错误', 500)


class FundIndustriesHandler(webBase.BaseHandler):
    """GET /quantia/api/fund/rank/industries?fund_type=股票型

    返回该 A 股权益类桶内出现的主行业列表（供排行榜二级过滤下拉）。
    非权益类桶（QDII/债券/货币/FOF）返回空列表 + supported=False。
    """

    def get(self):
        try:
            fund_type = self.get_argument('fund_type', default=_FUND_TYPES[0])
            if fund_type not in _FUND_TYPES:
                _write_error(self, f'不支持的基金类型: {fund_type}')
                return
            supported = fund_type in _EQUITY_TYPES
            industries = []
            if (supported and mdb.checkTableIsExist(_FUND_RANK_TABLE)
                    and mdb.checkTableIsExist(_FUND_SCORE_TABLE)):
                rows = mdb.executeSqlFetch(
                    f"SELECT DISTINCT s.`main_industry` "
                    f"FROM `{_FUND_RANK_TABLE}` r "
                    f"JOIN `{_FUND_SCORE_TABLE}` s "
                    f"  ON s.`code` = r.`code` "
                    f"  AND s.`date` = (SELECT MAX(`date`) FROM `{_FUND_SCORE_TABLE}`) "
                    f"WHERE r.`date` = (SELECT MAX(`date`) FROM `{_FUND_RANK_TABLE}`) "
                    f"  AND r.`fund_type` = %s "
                    f"  AND s.`main_industry` IS NOT NULL AND s.`main_industry` <> '' "
                    f"ORDER BY s.`main_industry`",
                    (fund_type,))
                industries = [r[0] for r in (rows or []) if r and r[0]]
            _write_json(self, {
                'fund_type': fund_type,
                'supported': supported,
                'industries': industries,
            })
        except Exception:
            logger.error("基金行业列表查询异常", exc_info=True)
            _write_error(self, '服务器内部错误', 500)
