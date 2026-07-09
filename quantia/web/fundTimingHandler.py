#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""基金入场择时 API Handler（P1：T1 回撤 + T2 趋势，纯净值）。

只读 MySQL（遵守 Fetch/Analysis/Web 分离，规则 1）：读 cn_fund_nav_history 的
acc_nav（缺失回退 unit_nav，防线3）逐基金实时算 TimingScore，读 cn_fund_rank_score
求 quality_pass。**不新增任何外部 API 调用**。

防御（见 document/fund/fund_pick_timing_impl_plan.md §1）：
- 防线1：净值滞后 > 7 天 → 不产出档位（stale=true, tier=None）。
- 防线3：acc_nav 全缺 → unit_nav 兜底，acc_null=true。
- 覆盖缺失：无净值历史/样本不足 → data_available=false，不造信号。
- 货币型不做点位择时 → timing_applicable=false。
- F13：禁买卖措辞，返回 labels.RISK_DISCLAIMER。

端点：GET /quantia/api/fund/timing?code=000001
"""

import datetime
import json
import logging
import math

import quantia.core.tablestructure as tbs
import quantia.lib.database as mdb
import quantia.web.base as webBase
from quantia.core.fund import labels, timing

__author__ = 'Quantia'
__date__ = '2026/07/09'

logger = logging.getLogger(__name__)

_NAV_TABLE = tbs.TABLE_CN_FUND_NAV_HISTORY['name']
_RANK_TABLE = tbs.TABLE_CN_FUND_RANK['name']
_SCORE_TABLE = tbs.TABLE_CN_FUND_RANK_SCORE['name']

_STALE_DAYS = 7          # 净值滞后阈值（防线1）
_QUALITY_PASS = 70.0     # quality_pass 门槛（桶内百分位分）
_MIN_SAMPLES = 2         # 最少净值样本
_MONEY_TYPE = '货币型'


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
    return None if v is None else round(float(v), nd)


class FundTimingHandler(webBase.BaseHandler):
    """GET /quantia/api/fund/timing?code=xxx

    返回 {code, name, fund_type, as_of, data_available, timing_applicable,
          stale, acc_null, timing_score, tier, components:{dd,trend,val},
          dims_used, quality_pass, quality_score, disclaimer}。
    """

    def get(self):
        try:
            code = (self.get_argument('code', default='') or '').strip()
            if not code:
                _write_error(self, '缺少 code 参数')
                return

            base = {
                'code': code, 'name': None, 'fund_type': None, 'as_of': None,
                'data_available': False, 'timing_applicable': True,
                'stale': False, 'acc_null': False,
                'timing_score': None, 'tier': None,
                'components': {'dd': None, 'trend': None, 'val': None},
                'dims_used': [], 'quality_pass': None, 'quality_score': None,
                'disclaimer': labels.RISK_DISCLAIMER,
            }

            if not mdb.checkTableIsExist(_NAV_TABLE):
                _write_json(self, base)
                return

            # 名称 + 类型 + 质量分（best-effort，缺失不阻断）
            self._fill_meta(code, base)

            if base['fund_type'] == _MONEY_TYPE:
                base['timing_applicable'] = False
                _write_json(self, base)
                return

            # 读净值序列（acc 优先，缺则 unit 兜底）
            rows = mdb.read_sql_ro(
                f"SELECT `nav_date`, `unit_nav`, `acc_nav` FROM `{_NAV_TABLE}` "
                f"WHERE `code` = %s ORDER BY `nav_date` ASC", params=(code,))
            if rows is None or rows.empty or len(rows) < _MIN_SAMPLES:
                _write_json(self, base)
                return

            acc = [_num(v) for v in rows['acc_nav'].tolist()]
            unit = [_num(v) for v in rows['unit_nav'].tolist()]
            series = [v for v in acc if v is not None]
            if len(series) >= _MIN_SAMPLES:
                nav_series = acc
            else:
                # acc 全缺 → 单位净值兜底（防线3）
                nav_series = unit
                base['acc_null'] = True
            nav_series = [v for v in nav_series if v is not None]
            if len(nav_series) < _MIN_SAMPLES:
                _write_json(self, base)
                return

            base['data_available'] = True

            # 净值滞后判定（防线1）
            last_date = rows['nav_date'].iloc[-1]
            as_of = last_date.strftime('%Y-%m-%d') if hasattr(last_date, 'strftime') \
                else str(last_date)[:10]
            base['as_of'] = as_of
            try:
                gap = (datetime.date.today()
                       - datetime.date.fromisoformat(as_of)).days
            except (ValueError, TypeError):
                gap = 0
            if gap > _STALE_DAYS:
                base['stale'] = True
                # 滞后：产出分量供透明展示，但不产出档位与综合分（防线1）
                dd = timing.drawdown_from_high(nav_series)
                trend = timing.nav_trend_score(nav_series)
                base['components'] = {'dd': _round(dd), 'trend': _round(trend), 'val': None}
                _write_json(self, base)
                return

            # T1 + T2（P1 val=None，自动降为二维）
            dd = timing.drawdown_from_high(nav_series)
            trend = timing.nav_trend_score(nav_series)
            res = timing.compose_timing_score(dd, trend, None)
            base['timing_score'] = _round(res['score'])
            base['tier'] = res['tier']
            base['components'] = {
                'dd': _round(res['components']['dd']),
                'trend': _round(res['components']['trend']),
                'val': None,
            }
            base['dims_used'] = res['dims_used']

            _write_json(self, base)
        except Exception:
            logger.error("基金入场择时查询异常", exc_info=True)
            _write_error(self, '服务器内部错误', 500)

    def _fill_meta(self, code, base):
        """填 name / fund_type / quality_score / quality_pass（缺失不阻断）。"""
        try:
            if mdb.checkTableIsExist(_RANK_TABLE):
                nrows = mdb.executeSqlFetch(
                    f"SELECT `name`, `fund_type` FROM `{_RANK_TABLE}` "
                    f"WHERE `code` = %s ORDER BY `date` DESC LIMIT 1", (code,))
                if nrows and nrows[0]:
                    base['name'] = nrows[0][0]
                    base['fund_type'] = nrows[0][1]
        except Exception:
            logger.warning("读取基金名称/类型失败 code=%s", code, exc_info=True)
        try:
            if mdb.checkTableIsExist(_SCORE_TABLE):
                srows = mdb.executeSqlFetch(
                    f"SELECT `score`, `fund_type` FROM `{_SCORE_TABLE}` "
                    f"WHERE `code` = %s ORDER BY `date` DESC LIMIT 1", (code,))
                if srows and srows[0]:
                    q = _num(srows[0][0])
                    base['quality_score'] = _round(q)
                    base['quality_pass'] = (q >= _QUALITY_PASS) if q is not None else None
                    if not base.get('fund_type') and srows[0][1]:
                        base['fund_type'] = srows[0][1]
        except Exception:
            logger.warning("读取基金质量分失败 code=%s", code, exc_info=True)
