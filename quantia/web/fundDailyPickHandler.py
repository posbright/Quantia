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
_RANK_SCORE_TABLE = tbs.TABLE_CN_FUND_RANK_SCORE['name']
_NAV_HIST_TABLE = tbs.TABLE_CN_FUND_NAV_HISTORY['name']
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


def _fetch_rank_fields(codes):
    """读基金最新净值/收益字段（cn_fund_rank）。

    只读 MySQL（规则1），SELECT 显式列（规则7）。取每只基金 cn_fund_rank 中
    最新 date 行的 unit_nav / acc_nav / seven_day_annual，返回
    {code: {'unit_nav': float|None, 'acc_nav': float|None,
            'seven_day_annual': float|None}}。
    """
    codes = [c for c in (codes or []) if c]
    if not codes or not mdb.checkTableIsExist(_RANK_TABLE):
        return {}
    placeholders = ', '.join(['%s'] * len(codes))
    rows = mdb.executeSqlFetch(
        f"SELECT r.`code`, r.`unit_nav`, r.`acc_nav`, r.`seven_day_annual` "
        f"FROM `{_RANK_TABLE}` r "
        f"JOIN (SELECT `code`, MAX(`date`) AS d FROM `{_RANK_TABLE}` "
        f"WHERE `code` IN ({placeholders}) GROUP BY `code`) m "
        f"ON r.`code` = m.`code` AND r.`date` = m.d",
        tuple(codes)) or []
    out = {}
    for code, unit_nav, acc_nav, sda in rows:
        out[code] = {
            'unit_nav': _num(unit_nav),
            'acc_nav': _num(acc_nav),
            'seven_day_annual': _num(sda),
        }
    return out


def _fetch_main_industry(codes):
    """读各基金主行业（cn_fund_rank_score.main_industry，由前十大重仓股加权得出）。

    只读 MySQL（规则1），SELECT 显式列（规则7）。取每只基金评分表最新 date 行的
    main_industry，返回 {code: str}。仅权益/指数类有覆盖，债券/货币/QDII/FOF 及无
    持仓基金无值（前端如实留白）。「未分类」视为无有效行业，不返回。
    """
    codes = [c for c in (codes or []) if c]
    if not codes or not mdb.checkTableIsExist(_RANK_SCORE_TABLE):
        return {}
    placeholders = ', '.join(['%s'] * len(codes))
    rows = mdb.executeSqlFetch(
        f"SELECT s.`code`, s.`main_industry` FROM `{_RANK_SCORE_TABLE}` s "
        f"JOIN (SELECT `code`, MAX(`date`) AS d FROM `{_RANK_SCORE_TABLE}` "
        f"WHERE `code` IN ({placeholders}) GROUP BY `code`) m "
        f"ON s.`code` = m.`code` AND s.`date` = m.d",
        tuple(codes)) or []
    out = {}
    for code, industry in rows:
        ind = (industry or '').strip()
        if ind and ind != '未分类':
            out[code] = ind
    return out


def _fetch_current_drawdown(codes):
    """读各基金「目前回撤」（距历史高点，蓝图 T1 drawdown-from-high）。

    current_dd = 最新累计净值 / 历史峰值累计净值 - 1（≤0），口径与
    scoring.compute_max_drawdown 的回撤序列末值一致（cummax 末点=全序峰值）。
    只读 MySQL（规则1），SELECT 显式列（规则7），一条 JOIN 查询取峰值与最新值，
    不整段拉净值序列。返回 {code: float}。仅有净值历史者有值（货币/债券多无）。
    """
    codes = [c for c in (codes or []) if c]
    if not codes or not mdb.checkTableIsExist(_NAV_HIST_TABLE):
        return {}
    placeholders = ', '.join(['%s'] * len(codes))
    rows = mdb.executeSqlFetch(
        f"SELECT h.`code`, m.`peak`, h.`acc_nav` FROM `{_NAV_HIST_TABLE}` h "
        f"JOIN (SELECT `code`, MAX(`nav_date`) AS d, MAX(`acc_nav`) AS peak "
        f"FROM `{_NAV_HIST_TABLE}` WHERE `code` IN ({placeholders}) "
        f"GROUP BY `code`) m "
        f"ON h.`code` = m.`code` AND h.`nav_date` = m.d",
        tuple(codes)) or []
    out = {}
    for code, peak, latest in rows:
        pk = _num(peak)
        lt = _num(latest)
        if pk is None or lt is None or pk <= 0:
            continue
        dd = lt / pk - 1.0
        if math.isfinite(dd):
            out[code] = min(dd, 0.0)
    return out


def _fetch_data_health(pick_date, score_as_of):
    """构建数据健康三防线（蓝图 §9），全部基于真实库计数，不臆造。

    - 防线1 净值披露及时性：cn_fund_rank 全库各基金最新快照，nav_date 距运行日
      ≤5 自然日者视为「及时」，返回 fresh/total/pct。
    - 防线2 持仓行业可用性：cn_fund_rank_score.main_industry 全库覆盖计数（由前十大
      重仓股加权得出），返回 covered/total/pct；仅权益/指数类有覆盖。
    - 防线3 质量评分覆盖：以榜单 score_as_of 是否就绪判定 full/partial。
    只读 MySQL（规则1），SELECT 显式列（规则7）。
    """
    health = {
        'timeliness': None,
        'holdings': {'available': False},
        'quality_coverage': {
            'status': 'full' if score_as_of else 'unknown',
            'score_as_of': score_as_of,
        },
    }
    try:
        if pick_date is not None and mdb.checkTableIsExist(_RANK_TABLE):
            row = mdb.executeSqlFetch(
                f"SELECT SUM(CASE WHEN r.`nav_date` >= "
                f"DATE_SUB(%s, INTERVAL 5 DAY) THEN 1 ELSE 0 END), COUNT(*) "
                f"FROM (SELECT `code`, MAX(`date`) AS d FROM `{_RANK_TABLE}` "
                f"GROUP BY `code`) m "
                f"JOIN `{_RANK_TABLE}` r ON r.`code` = m.`code` "
                f"AND r.`date` = m.d", (pick_date,))
            if row and row[0]:
                fresh = int(row[0][0] or 0)
                total = int(row[0][1] or 0)
                pct = round(fresh * 100.0 / total, 1) if total else None
                health['timeliness'] = {
                    'fresh': fresh, 'total': total, 'pct': pct}
    except Exception:
        logger.warning("数据健康防线1（净值及时性）统计失败", exc_info=True)
    try:
        if mdb.checkTableIsExist(_RANK_SCORE_TABLE):
            row = mdb.executeSqlFetch(
                f"SELECT SUM(CASE WHEN s.`main_industry` IS NOT NULL "
                f"AND s.`main_industry` <> '' AND s.`main_industry` <> '未分类' "
                f"THEN 1 ELSE 0 END), COUNT(*) FROM `{_RANK_SCORE_TABLE}` s "
                f"JOIN (SELECT MAX(`date`) AS d FROM `{_RANK_SCORE_TABLE}`) x "
                f"ON s.`date` = x.d")
            if row and row[0]:
                covered = int(row[0][0] or 0)
                total = int(row[0][1] or 0)
                pct = round(covered * 100.0 / total, 1) if total else None
                health['holdings'] = {
                    'available': covered > 0,
                    'covered': covered, 'total': total, 'pct': pct}
    except Exception:
        logger.warning("数据健康防线2（持仓行业覆盖）统计失败", exc_info=True)
    return health


class FundDailyPickHandler(webBase.BaseHandler):
    """GET /quantia/api/fund/daily_pick

    返回 {date, score_as_of, data_health, buckets:[{fund_type,
          timing_applicable, has_timing, picks:[{rank_in_type, code, name,
          quality_score, timing_score, timing_tier, final_score, max_drawdown,
          current_drawdown, main_industry, rate_1y, unit_nav, acc_nav,
          seven_day_annual, nav_as_of, data_lag_days}]}], disclaimer}。
    current_drawdown 为距历史高点回撤（cn_fund_nav_history 现算），main_industry
    为持仓加权主行业（cn_fund_rank_score），二者仅有覆盖者有值、否则 None。
    data_health 为三条数据防线（timeliness/holdings/quality_coverage），全部
    基于真实库计数。
    """

    def get(self):
        try:
            base = {
                'date': None, 'score_as_of': None, 'data_health': None,
                'buckets': [], 'disclaimer': labels.RISK_DISCLAIMER,
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
                    'current_drawdown': None,
                    'main_industry': None,
                    'rate_1y': _round(rate_1y, 2),
                    'unit_nav': None,
                    'acc_nav': None,
                    'seven_day_annual': None,
                    'nav_as_of': _to_iso(nav_as_of),
                    'data_lag_days': int(lag) if lag is not None else None,
                })

            # 全桶补最新净值（unit_nav/acc_nav）+ 货币型 7 日年化（cn_fund_rank），
            # 对齐原型「净值/累计」列与「收益稳定性」展示。
            all_codes = [p['code'] for picks in groups.values()
                         for p in picks if p.get('code')]
            if all_codes:
                rmap = _fetch_rank_fields(all_codes)
                for picks in groups.values():
                    for p in picks:
                        rf = rmap.get(p.get('code'))
                        if not rf:
                            continue
                        p['unit_nav'] = _round(rf.get('unit_nav'), 4)
                        p['acc_nav'] = _round(rf.get('acc_nav'), 4)
                        p['seven_day_annual'] = _round(
                            rf.get('seven_day_annual'), 3)

                # 主行业（cn_fund_rank_score.main_industry）+ 目前回撤
                # （cn_fund_nav_history 距高点），对齐原型「风格/目前回撤」列。
                # 无持仓/无净值历史的基金保持 None，前端如实留白。
                imap = _fetch_main_industry(all_codes)
                ddmap = _fetch_current_drawdown(all_codes)
                for picks in groups.values():
                    for p in picks:
                        code = p.get('code')
                        if code in imap:
                            p['main_industry'] = imap[code]
                        if code in ddmap:
                            p['current_drawdown'] = _round(ddmap[code], 4)

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
            base['data_health'] = _fetch_data_health(
                pick_date, base['score_as_of'])

            _write_json(self, base)
        except Exception:
            logger.error("基金每日精选榜查询异常", exc_info=True)
            _write_error(self, '服务器内部错误', 500)
