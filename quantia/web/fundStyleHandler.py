#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""持仓风格暴露 + 前向兼容漂移 API Handler（P4 选基增量，风控辅助展示，非硬因子）。

只读（遵守 Fetch/Analysis/Web 分离，规则 1）：读 `cn_fund_holding` 基金各季前十大重仓股
（`industry`/`hold_ratio`），算最新季**行业暴露/集中度**；若库中已累积 ≥2 季报，再算相邻两季
**风格漂移**（当前生产库每基金仅 1 季 → drift_available=false，历史累积后自动点亮）。

严格定位（蓝图 §9.2 / §F12）：**仅详情页风控辅助展示（条形/雷达）**，不做硬拦截、
**不进入 TimingScore**，不影响无覆盖基金；`未分类`（科创板 688 断层）仅透明化占比、
不计入集中度/漂移口径。

端点：GET /quantia/api/fund/style?code=000001
"""

import json
import logging
import math

import quantia.core.tablestructure as tbs
import quantia.lib.database as mdb
import quantia.web.base as webBase
from quantia.core.fund import labels, style_drift

__author__ = 'Quantia'
__date__ = '2026/07/09'

logger = logging.getLogger(__name__)

_HOLDING_TABLE = tbs.TABLE_CN_FUND_HOLDING['name']
_RANK_TABLE = tbs.TABLE_CN_FUND_RANK['name']

_TOP_INDUSTRIES = 8   # 前端条形最多展示的行业数


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


class FundStyleHandler(webBase.BaseHandler):
    """GET /quantia/api/fund/style?code=xxx

    返回 {code, name, fund_type, quarter, data_available,
          industries:[{industry, weight, share}], unclassified_weight,
          disclosed_ratio, unclassified_ratio, hhi, concentration_label,
          top3_share, n_industries,
          drift_available, drift:{drift_score, drift_label, top_changes}|None,
          prev_quarter, disclaimer, note}。
    """

    def get(self):
        try:
            code = (self.get_argument('code', default='') or '').strip()
            if not code:
                _write_error(self, '缺少 code 参数')
                return

            base = {
                'code': code, 'name': None, 'fund_type': None, 'quarter': None,
                'data_available': False,
                'industries': [], 'unclassified_weight': 0.0,
                'disclosed_ratio': 0.0, 'unclassified_ratio': None,
                'hhi': None, 'concentration_label': None,
                'top3_share': None, 'n_industries': 0,
                'drift_available': False, 'drift': None, 'prev_quarter': None,
                'disclaimer': labels.RISK_DISCLAIMER,
                'note': '基于季报前十大重仓股的行业暴露估算，穿透不完整（前十大常仅占净值 '
                        '40–60%）、季报滞后约一季度；仅作风控辅助展示、非买卖/申赎建议。'
                        '「未分类」含科创板等未回填行业个股，仅透明化占比、不计入集中度。',
            }

            self._fill_meta(code, base)

            if not mdb.checkTableIsExist(_HOLDING_TABLE):
                _write_json(self, base)
                return

            # 取最近两个季度（若只有一季，则仅最新季）
            qrows = mdb.executeSqlFetch(
                f"SELECT DISTINCT `quarter` FROM `{_HOLDING_TABLE}` "
                f"WHERE `code` = %s ORDER BY `quarter` DESC LIMIT 2", (code,))
            if not qrows:
                _write_json(self, base)
                return

            latest_q = qrows[0][0]
            prev_q = qrows[1][0] if len(qrows) > 1 else None

            latest_holdings = self._load_quarter(code, latest_q)
            exp = style_drift.industry_exposure(latest_holdings)

            base['quarter'] = latest_q
            base['industries'] = exp['industries'][:_TOP_INDUSTRIES]
            base['unclassified_weight'] = exp['unclassified_weight']
            base['disclosed_ratio'] = exp['disclosed_ratio']
            base['unclassified_ratio'] = exp['unclassified_ratio']
            base['hhi'] = exp['hhi']
            base['concentration_label'] = style_drift.concentration_label(exp['hhi'])
            base['top3_share'] = exp['top3_share']
            base['n_industries'] = exp['n_industries']
            # 有已分类行业才算"有暴露可展示"
            base['data_available'] = exp['n_industries'] > 0

            # 前向兼容漂移：库中已有上一季 → 算相邻两季漂移
            if prev_q is not None:
                prev_holdings = self._load_quarter(code, prev_q)
                prev_exp = style_drift.industry_exposure(prev_holdings)
                drift = style_drift.style_drift(prev_exp, exp)
                if drift is not None:
                    base['drift_available'] = True
                    base['drift'] = drift
                    base['prev_quarter'] = prev_q

            _write_json(self, base)
        except Exception:
            logger.error("持仓风格暴露查询异常", exc_info=True)
            _write_error(self, '服务器内部错误', 500)

    def _load_quarter(self, code, quarter):
        """读某一季全部持仓行（industry + hold_ratio）。"""
        rows = mdb.executeSqlFetch(
            f"SELECT `industry`, `hold_ratio` FROM `{_HOLDING_TABLE}` "
            f"WHERE `code` = %s AND `quarter` = %s", (code, quarter))
        return [{'industry': r[0], 'hold_ratio': r[1]} for r in (rows or [])]

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
