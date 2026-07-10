#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每日精选榜 API Handler（P5，只读 MySQL，遵守 Fetch/Analysis/Web 分离规则1）。

读 cn_fund_daily_pick 最新运行日，按 fund_type 分桶返回每桶 Top10。榜单由
analysis_fund_pick_job.py 预生成；本 Handler 只做读取 + 分组，不算 timing、不落库、
不调外部 API。

择时档位为**弱标签**（V1 口径 C：质量主排序 + 择时提示，非买卖建议）。货币型不做
点位择时（timing_applicable=false）；债券型多无净值历史故 timing 多为空，前端按
has_timing 决定是否展示徽章。返回 labels.RISK_DISCLAIMER。

端点：GET /quantia/api/fund/daily_pick
"""

import json
import logging
import math

import quantia.core.tablestructure as tbs
import quantia.lib.database as mdb
import quantia.web.base as webBase
from quantia.core.fund import labels

__author__ = 'Quantia'
__date__ = '2026/07/09'

logger = logging.getLogger(__name__)

_PICK_TABLE = tbs.TABLE_CN_FUND_DAILY_PICK['name']
_RANK_TABLE = tbs.TABLE_CN_FUND_RANK['name']
_MONEY_TYPE = '货币型'
# 桶展示顺序（其余类型按字典序追加）
_TYPE_ORDER = ['股票型', '混合型', '指数型', 'QDII', 'FOF', '债券型', '货币型']


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


def _round(v, nd=1):
    n = _num(v)
    return None if n is None else round(n, nd)


def _to_iso(v):
    if v is None:
        return None
    if hasattr(v, 'isoformat'):
        return v.isoformat()
    return str(v)[:10]


def _fetch_seven_day_annual(codes):
    """读货币型基金最新 7 日年化（cn_fund_rank.seven_day_annual）。

    只读 MySQL（规则1），SELECT 显式列（规则7）。取每只基金 cn_fund_rank 中
    最新 date 的 seven_day_annual，返回 {code: float}。
    """
    codes = [c for c in (codes or []) if c]
    if not codes or not mdb.checkTableIsExist(_RANK_TABLE):
        return {}
    placeholders = ', '.join(['%s'] * len(codes))
    rows = mdb.executeSqlFetch(
        f"SELECT r.`code`, r.`seven_day_annual` FROM `{_RANK_TABLE}` r "
        f"JOIN (SELECT `code`, MAX(`date`) AS d FROM `{_RANK_TABLE}` "
        f"WHERE `code` IN ({placeholders}) GROUP BY `code`) m "
        f"ON r.`code` = m.`code` AND r.`date` = m.d",
        tuple(codes)) or []
    out = {}
    for code, sda in rows:
        v = _num(sda)
        if v is not None:
            out[code] = v
    return out


class FundDailyPickHandler(webBase.BaseHandler):
    """GET /quantia/api/fund/daily_pick

    返回 {date, score_as_of, buckets:[{fund_type, timing_applicable, has_timing,
          picks:[{rank_in_type, code, name, quality_score, timing_score,
                  timing_tier, final_score, max_drawdown, rate_1y,
                  seven_day_annual, nav_as_of, data_lag_days}]}], disclaimer}。
    """

    def get(self):
        try:
            base = {
                'date': None, 'score_as_of': None, 'buckets': [],
                'disclaimer': labels.RISK_DISCLAIMER,
            }
            if not mdb.checkTableIsExist(_PICK_TABLE):
                _write_json(self, base)
                return

            drow = mdb.executeSqlFetch(
                f"SELECT MAX(`date`) FROM `{_PICK_TABLE}`")
            pick_date = drow[0][0] if drow and drow[0] else None
            if pick_date is None:
                _write_json(self, base)
                return
            base['date'] = _to_iso(pick_date)

            rows = mdb.executeSqlFetch(
                f"SELECT `fund_type`, `rank_in_type`, `code`, `name`, "
                f"`quality_score`, `timing_score`, `timing_tier`, `final_score`, "
                f"`max_drawdown`, `rate_1y`, `score_as_of`, `nav_as_of`, "
                f"`data_lag_days` FROM `{_PICK_TABLE}` WHERE `date` = %s "
                f"ORDER BY `fund_type`, `rank_in_type`", (pick_date,))

            groups = {}
            for r in (rows or ()):
                (ftype, rank, code, name, quality, tscore, tier, final,
                 mdd, rate_1y, score_as_of, nav_as_of, lag) = r
                if base['score_as_of'] is None and score_as_of is not None:
                    base['score_as_of'] = _to_iso(score_as_of)
                groups.setdefault(ftype, []).append({
                    'rank_in_type': int(rank) if rank is not None else None,
                    'code': code,
                    'name': name,
                    'quality_score': _round(quality),
                    'timing_score': _round(tscore),
                    'timing_tier': tier,
                    'final_score': _round(final),
                    'max_drawdown': _round(mdd, 4),
                    'rate_1y': _round(rate_1y, 2),
                    'seven_day_annual': None,
                    'nav_as_of': _to_iso(nav_as_of),
                    'data_lag_days': int(lag) if lag is not None else None,
                })

            # 货币型桶：补 7 日年化（cn_fund_rank），对齐原型「收益稳定性」展示
            money_codes = [p['code'] for p in groups.get(_MONEY_TYPE, [])
                           if p.get('code')]
            if money_codes:
                sda_map = _fetch_seven_day_annual(money_codes)
                for p in groups.get(_MONEY_TYPE, []):
                    p['seven_day_annual'] = _round(sda_map.get(p.get('code')), 3)

            ordered = [t for t in _TYPE_ORDER if t in groups]
            ordered += sorted(t for t in groups if t not in _TYPE_ORDER)
            buckets = []
            for ftype in ordered:
                picks = groups[ftype]
                has_timing = any(p['timing_tier'] is not None for p in picks)
                buckets.append({
                    'fund_type': ftype,
                    'timing_applicable': ftype != _MONEY_TYPE,
                    'has_timing': has_timing,
                    'picks': picks,
                })
            base['buckets'] = buckets

            _write_json(self, base)
        except Exception:
            logger.error("基金每日精选榜查询异常", exc_info=True)
            _write_error(self, '服务器内部错误', 500)
