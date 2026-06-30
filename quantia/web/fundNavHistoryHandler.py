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

# 同类平均基线：参与平均的最多同类基金数（控制内存/查询量）。
_PEER_MAX_FUNDS = 40


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

            df = mdb.read_sql_ro(sql, params=tuple(params))
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


def _range_start(rng):
    """range → 起点日期字符串（None 表示全史不裁剪）。"""
    days = _RANGE_DAYS.get(rng)
    if days is None:
        return None
    start = datetime.date.today() - datetime.timedelta(days=days)
    return start.isoformat()


def compute_peer_baseline(df, target_code):
    """由同类基金净值长表计算"同类平均增长基线"。

    df 列：code, nav_date, acc_nav, unit_nav（窗口内、含/不含 target）。
    口径：每只基金优先用 acc_nav（缺失回退 unit_nav）归一化为"较窗口首个有效点
    的增长百分比"，再按日期对齐（前向填充各基金最后已知值）求跨基金均值。
    排除 target_code 自身，使后续"超额"语义干净。

    返回 (points, peer_count)：points=[{date, growth}]，按日期升序。
    """
    if df is None or df.empty:
        return [], 0
    work = df.copy()
    if target_code:
        work = work[work['code'] != target_code]
    if work.empty:
        return [], 0

    # 每行取 acc 优先、回退 unit 的净值。
    def _pick(row):
        v = _num(row.get('acc_nav'))
        if v is None:
            v = _num(row.get('unit_nav'))
        return v

    work = work.assign(_nav=work.apply(_pick, axis=1))
    work = work.dropna(subset=['_nav'])
    if work.empty:
        return [], 0

    # 日期标准化为字符串，便于对齐。
    def _dstr(d):
        if hasattr(d, 'strftime'):
            return d.strftime('%Y-%m-%d')
        return str(d)[:10]

    work['_d'] = work['nav_date'].map(_dstr)
    # 宽表：index=日期，columns=基金，values=净值。
    wide = work.pivot_table(index='_d', columns='code', values='_nav', aggfunc='last')
    wide = wide.sort_index()
    # 每只基金归一化为增长% = (v / 首个有效值 - 1)*100。
    growth = pd.DataFrame(index=wide.index)
    for c in wide.columns:
        s = wide[c]
        first_idx = s.first_valid_index()
        if first_idx is None:
            continue
        base = s.loc[first_idx]
        if base is None or base == 0:
            continue
        growth[c] = (s / base - 1.0) * 100.0
    if growth.empty or growth.shape[1] == 0:
        return [], 0
    # 前向填充各基金最后已知增长（避免某基金缺测日把均值拉偏），再跨基金求均值。
    growth = growth.ffill()
    avg = growth.mean(axis=1, skipna=True)
    peer_count = int(growth.shape[1])
    points = []
    for d, v in avg.items():
        fv = _num(v)
        if fv is None:
            continue
        points.append({'date': d, 'growth': round(fv, 4)})
    return points, peer_count


class FundNavPeerHandler(webBase.BaseHandler):
    """GET /quantia/api/fund/nav_peer?code=xxx&range=1y

    返回目标基金所属同类桶的"平均净值增长基线"（§9.3 叠加同类平均看超额）。
    {code, fund_type, range, peer_count, count, points:[{date, growth}]}。
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

            empty = {'code': code, 'fund_type': None, 'range': rng,
                     'peer_count': 0, 'count': 0, 'points': []}
            if not (mdb.checkTableIsExist(_NAV_TABLE)
                    and mdb.checkTableIsExist(_RANK_TABLE)):
                _write_json(self, empty)
                return

            # 目标基金的同类桶（最新快照日的 fund_type）。
            frows = mdb.executeSqlFetch(
                f"SELECT `fund_type` FROM `{_RANK_TABLE}` WHERE `code` = %s "
                f"ORDER BY `date` DESC LIMIT 1", (code,))
            fund_type = frows[0][0] if (frows and frows[0]) else None
            if not fund_type:
                _write_json(self, empty)
                return

            # 同类桶基金（最新快照日），限制数量；优先取有净值历史的。
            peer_rows = mdb.executeSqlFetch(
                f"SELECT DISTINCT r.`code` FROM `{_RANK_TABLE}` r "
                f"JOIN `{_NAV_TABLE}` n ON n.`code` = r.`code` "
                f"WHERE r.`date` = (SELECT MAX(`date`) FROM `{_RANK_TABLE}`) "
                f"  AND r.`fund_type` = %s "
                f"LIMIT %s", (fund_type, _PEER_MAX_FUNDS))
            peer_codes = [r[0] for r in (peer_rows or []) if r and r[0]]
            # 始终把目标自身纳入查询（用于对齐日期轴），compute 时再排除。
            if code not in peer_codes:
                peer_codes.append(code)
            if not peer_codes:
                empty['fund_type'] = fund_type
                _write_json(self, empty)
                return

            placeholders = ', '.join(['%s'] * len(peer_codes))
            params = list(peer_codes)
            sql = (
                f"SELECT `code`, `nav_date`, `acc_nav`, `unit_nav` FROM `{_NAV_TABLE}` "
                f"WHERE `code` IN ({placeholders}) ")
            start = _range_start(rng)
            if start is not None:
                sql += "AND `nav_date` >= %s "
                params.append(start)
            sql += "ORDER BY `nav_date` ASC"

            df = mdb.read_sql_ro(sql, params=tuple(params))
            points, peer_count = compute_peer_baseline(df, code)
            _write_json(self, {
                'code': code, 'fund_type': fund_type, 'range': rng,
                'peer_count': peer_count, 'count': len(points), 'points': points,
            })
        except Exception:
            logger.error("基金同类平均基线查询异常", exc_info=True)
            _write_error(self, '服务器内部错误', 500)
