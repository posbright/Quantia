#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""综合选股评分列表 API（M2.3）。

端点：
- GET /quantia/api/selection/score/list

本阶段目标：在列表结果中透出 rank_change 是否可比，
当 risk_flags 包含 "rank_change_not_comparable" 时返回 rank_change_comparable=false。
"""

from __future__ import annotations

import json
import logging
import math

import pandas as pd

import quantia.core.selection_scoring as scoring
import quantia.lib.database as mdb
import quantia.web.base as webBase

__author__ = 'Quantia'
__date__ = '2026/06/02'

logger = logging.getLogger(__name__)


def _json_default(o):
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


def _parse_flag_list(risk_flags) -> list[str]:
    if isinstance(risk_flags, list):
        return [str(x) for x in risk_flags if x is not None]
    if not isinstance(risk_flags, str):
        return []
    text = risk_flags.strip()
    if not text:
        return []
    try:
        arr = json.loads(text)
    except Exception:
        return []
    if not isinstance(arr, list):
        return []
    return [str(x) for x in arr if x is not None]


def _rank_change_comparable_from_flags(risk_flags) -> bool:
    flags = _parse_flag_list(risk_flags)
    return 'rank_change_not_comparable' not in flags


class SelectionScoreListHandler(webBase.BaseHandler):
    """GET /quantia/api/selection/score/list

    Query:
    - date: 可选，默认最新日期
    - industry: 可选
    - rating: 可选（S/A/B/C/D）
    - min_quality: 可选
    - page/page_size: 分页
    - sort: total_score|quality_score|industry_rank（默认 total_score）
    """

    _SORT_MAP = {
        'total_score': '`total_score` DESC',
        'quality_score': '`quality_score` DESC',
        'industry_rank': '`industry_rank` ASC',
    }

    def get(self):
        try:
            if not mdb.checkTableIsExist(scoring.SELECTION_SCORE_TABLE):
                _write_json(self, {
                    'date': None,
                    'total': 0,
                    'items': [],
                    'warning': 'cn_stock_selection_score 表尚未创建，请先执行 selection_score_job',
                })
                return

            date_arg = self.get_argument('date', default='').strip()
            industry = self.get_argument('industry', default='').strip()
            rating = self.get_argument('rating', default='').strip().upper()
            min_quality_raw = self.get_argument('min_quality', default='').strip()
            sort = self.get_argument('sort', default='total_score').strip()
            page = max(1, int(self.get_argument('page', default='1')))
            page_size = min(200, max(1, int(self.get_argument('page_size', default='50'))))
            offset = (page - 1) * page_size

            where = []
            params = []

            if date_arg:
                where.append('`date` = %s')
                params.append(date_arg)
            else:
                where.append(f"`date` = (SELECT MAX(`date`) FROM `{scoring.SELECTION_SCORE_TABLE}`)")

            if industry:
                where.append('`industry` = %s')
                params.append(industry)

            if rating in {'S', 'A', 'B', 'C', 'D'}:
                where.append('`rating` = %s')
                params.append(rating)

            if min_quality_raw:
                try:
                    min_quality = float(min_quality_raw)
                    where.append('`quality_score` >= %s')
                    params.append(min_quality)
                except ValueError:
                    pass

            where_sql = (' WHERE ' + ' AND '.join(where)) if where else ''
            order_sql = self._SORT_MAP.get(sort, self._SORT_MAP['total_score'])

            count_sql = f"SELECT COUNT(*) AS cnt FROM `{scoring.SELECTION_SCORE_TABLE}`{where_sql}"
            data_sql = (
                f"SELECT `date`,`code`,`name`,`industry`,`total_score`,`total_score_raw`,`quality_score`,`industry_score`,"
                f"`rating`,`industry_rank`,`industry_total`,`rank_change_1d`,`data_completeness`,`risk_flags`,`tags` "
                f"FROM `{scoring.SELECTION_SCORE_TABLE}`{where_sql} "
                f"ORDER BY {order_sql} LIMIT %s OFFSET %s"
            )

            total_df = pd.read_sql(count_sql, con=mdb.engine(), params=tuple(params))
            total = int(total_df.iloc[0]['cnt']) if not total_df.empty else 0

            data_params = list(params) + [page_size, offset]
            df = pd.read_sql(data_sql, con=mdb.engine(), params=tuple(data_params))

            items = []
            for row in df.to_dict(orient='records'):
                row['rank_change_comparable'] = _rank_change_comparable_from_flags(row.get('risk_flags'))
                items.append(row)

            date_rows = mdb.executeSqlFetch(
                f"SELECT MAX(`date`) FROM `{scoring.SELECTION_SCORE_TABLE}`"
            )
            latest_date = None
            if date_rows and date_rows[0] and date_rows[0][0] is not None:
                d = date_rows[0][0]
                latest_date = d.isoformat() if hasattr(d, 'isoformat') else str(d)

            _write_json(self, {
                'date': latest_date,
                'page': page,
                'page_size': page_size,
                'total': total,
                'items': items,
            })
        except Exception:
            logger.error('SelectionScoreListHandler 查询异常', exc_info=True)
            self.set_status(500)
            _write_json(self, {'error': '服务器内部错误'})
