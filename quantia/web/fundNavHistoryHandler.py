#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""基金净值曲线 API Handler（F9 §9.3 净值曲线）。

只读 MySQL（遵守 Fetch/Analysis/Web 分离）：直接读 cn_fund_nav_history，
返回单位净值/累计净值时间序列，供前端 ECharts 折线展示。

- 展示用 unit_nav（用户直观）；长期口径派生指标用 acc_nav（见 §2 审计修正），
  本接口两者都返回，前端默认画 acc_nav 归一化增长曲线 + unit_nav 可选。
- 区间过滤在 SQL 端按 nav_date >= 起点裁剪，避免一次拉全史 5000+ 行。

端点：
- GET /quantia/api/fund/nav_history?code=000001&range=1y
"""

import datetime
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

_NAV_TABLE = tbs.TABLE_CN_FUND_NAV_HISTORY['name']
_RANK_TABLE = tbs.TABLE_CN_FUND_RANK['name']

# range → 回看天数（None 表示全史）。
_RANGE_DAYS = {
    '1m': 31,
    '3m': 93,
    '6m': 186,
    '1y': 366,
    '3y': 1100,
    'all': None,
}
_DEFAULT_RANGE = '1y'


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


def _write_error(handler, msg, code=400):
    handler.set_status(code)
    _write_json(handler, {'error': msg})


def _num(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if not math.isfinite(f) else f


class FundNavHistoryHandler(webBase.BaseHandler):
    """GET /quantia/api/fund/nav_history?code=xxx&range=1y

    返回 {code, name, range, points:[{date, unit_nav, acc_nav}], count}。
    """

    def get(self):
        try:
            code = (self.get_argument('code', default='') or '').strip()
            rng = (self.get_argument('range', default=_DEFAULT_RANGE) or '').strip().lower()
            if not code:
                _write_error(self, '缺少 code 参数')
                return
            if rng not in _RANGE_DAYS:
                rng = _DEFAULT_RANGE

            if not mdb.checkTableIsExist(_NAV_TABLE):
                _write_json(self, {'code': code, 'name': None, 'range': rng,
                                   'count': 0, 'points': []})
                return

            name = None
            if mdb.checkTableIsExist(_RANK_TABLE):
                nrows = mdb.executeSqlFetch(
                    f"SELECT `name` FROM `{_RANK_TABLE}` WHERE `code` = %s "
                    f"ORDER BY `date` DESC LIMIT 1", (code,))
                if nrows and nrows[0]:
                    name = nrows[0][0]

            days = _RANGE_DAYS[rng]
            params = [code]
            sql = (
                f"SELECT `nav_date`, `unit_nav`, `acc_nav` FROM `{_NAV_TABLE}` "
                f"WHERE `code` = %s "
            )
            if days is not None:
                start = datetime.date.today() - datetime.timedelta(days=days)
                sql += "AND `nav_date` >= %s "
                params.append(start.isoformat())
            sql += "ORDER BY `nav_date` ASC"

            df = pd.read_sql(sql, con=mdb.engine(), params=tuple(params))
            points = []
            for _, r in df.iterrows():
                d = r['nav_date']
                if hasattr(d, 'strftime'):
                    date_str = d.strftime('%Y-%m-%d')
                else:
                    date_str = str(d)[:10]
                points.append({
                    'date': date_str,
                    'unit_nav': _num(r.get('unit_nav')),
                    'acc_nav': _num(r.get('acc_nav')),
                })

            _write_json(self, {
                'code': code, 'name': name, 'range': rng,
                'count': len(points), 'points': points,
            })
        except Exception:
            logger.error("基金净值曲线查询异常", exc_info=True)
            _write_error(self, '服务器内部错误', 500)
