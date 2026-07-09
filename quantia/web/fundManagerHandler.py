#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""基金经理经验弱因子 API Handler（P4 选基增量，弱因子展示，非硬因子）。

只读（遵守 Fetch/Analysis/Web 分离，规则 1）：读 `cn_fund_manager`（来源
akshare.fund_manager_em，由 fetch_fund_manager_job 写入）里一只基金的在管经理行，
聚合团队从业年限/经理数/最佳回报/一拖多提示。

严格定位（蓝图 §9.2 / P4）：**仅详情页经理经验弱因子展示**，不做硬拦截、
**不进入 TimingScore**，不影响无覆盖基金；「累计从业时间」是经理全市场累计从业天数、
**非本基金任职起始日**，故只作「经验」弱信号，不宣称「本基金经理稳定/未跳槽」。

端点：GET /quantia/api/fund/manager?code=000001
"""

import json
import logging
import math

import quantia.core.tablestructure as tbs
import quantia.lib.database as mdb
import quantia.web.base as webBase
from quantia.core.fund import labels, manager_factor

__author__ = 'Quantia'
__date__ = '2026/07/09'

logger = logging.getLogger(__name__)

_MANAGER_TABLE = tbs.TABLE_CN_FUND_MANAGER['name']
_RANK_TABLE = tbs.TABLE_CN_FUND_RANK['name']


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


class FundManagerHandler(webBase.BaseHandler):
    """GET /quantia/api/fund/manager?code=xxx

    返回 {code, name, fund_type, data_available,
          manager_count, names:[..], company,
          max_tenure_years, avg_tenure_years, experience_label,
          best_return, max_fund_count, over_extended,
          managers:[{manager, company, tenure_years, total_aum, best_return, fund_count}],
          disclaimer, note}。
    """

    def get(self):
        try:
            code = (self.get_argument('code', default='') or '').strip()
            if not code:
                _write_error(self, '缺少 code 参数')
                return

            base = {
                'code': code, 'name': None, 'fund_type': None,
                'data_available': False,
                'manager_count': 0, 'names': [], 'company': None,
                'max_tenure_years': None, 'avg_tenure_years': None,
                'experience_label': None, 'best_return': None,
                'max_fund_count': None, 'over_extended': False,
                'managers': [],
                'disclaimer': labels.RISK_DISCLAIMER,
                'note': '「累计从业时间」为基金经理全市场累计从业年限，非本基金任职起始日；'
                        '经理经验仅作弱因子参考，不代表本基金业绩，非投资建议。'
                        '一拖多（单人在管基金数偏多）仅提示精力可能分散。',
            }

            self._fill_meta(code, base)

            if not mdb.checkTableIsExist(_MANAGER_TABLE):
                _write_json(self, base)
                return

            rows = mdb.executeSqlFetch(
                f"SELECT `manager`, `company`, `tenure_days`, `total_aum`, "
                f"`best_return`, `fund_count` FROM `{_MANAGER_TABLE}` "
                f"WHERE `code` = %s", (code,))
            if not rows:
                _write_json(self, base)
                return

            managers = [{
                'manager': r[0], 'company': r[1], 'tenure_days': r[2],
                'total_aum': r[3], 'best_return': r[4], 'fund_count': r[5],
            } for r in rows]

            agg = manager_factor.manager_experience(managers)
            if agg is None:
                _write_json(self, base)
                return

            base['data_available'] = True
            base['manager_count'] = agg['manager_count']
            base['names'] = agg['names']
            base['company'] = agg['company']
            base['max_tenure_years'] = agg['max_tenure_years']
            base['avg_tenure_years'] = agg['avg_tenure_years']
            base['experience_label'] = agg['experience_label']
            base['best_return'] = agg['best_return']
            base['max_fund_count'] = agg['max_fund_count']
            base['over_extended'] = agg['over_extended']
            # 逐经理明细（按从业年限降序），供前端表格/条形
            detail = []
            for r in rows:
                td = r[2]
                yrs = round(float(td) / 365.0, 2) if td not in (None, 0) else None
                detail.append({
                    'manager': r[0], 'company': r[1],
                    'tenure_years': yrs,
                    'total_aum': r[3], 'best_return': r[4], 'fund_count': r[5],
                })
            detail.sort(key=lambda d: (d['tenure_years'] is None, -(d['tenure_years'] or 0)))
            base['managers'] = detail

            _write_json(self, base)
        except Exception:
            logger.error("基金经理经验查询异常", exc_info=True)
            _write_error(self, '服务器内部错误', 500)

    def _fill_meta(self, code, base):
        """填 name / fund_type（缺失不阻断）。"""
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
