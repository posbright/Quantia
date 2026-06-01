#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票财务数据 API

为指标详情页提供：
1. 最新一期财务摘要 (latest)
2. 历史多期财务序列 (history) 供前端绘制柱状/折线图
"""

import json
import logging
from abc import ABC
from typing import Any, Dict, List

from tornado import gen

import quantia.lib.database as mdb
import quantia.web.base as webBase

__author__ = 'Quantia'
__date__ = '2026/05/27'

_logger = logging.getLogger(__name__)


def _write_json(handler, data: Any, status: int = 200):
    handler.set_status(status)
    handler.set_header('Content-Type', 'application/json; charset=utf-8')
    handler.write(json.dumps(data, ensure_ascii=False, default=str))


def _pick_pe(pe_ttm, pe_dyn, pe_static):
    """按优先级挑选可展示的市盈率：TTM(pe9) → 动态(dtsyl) → 静态(pe)。

    部分行情源（腾讯/新浪）不提供 TTM/静态市盈率，会落库为 0，
    此时回退到动态市盈率(dtsyl)，保证前端"市盈率(PE)"有可展示的数值。
    返回 None 表示三者均无有效值。
    """
    for cand in (pe_ttm, pe_dyn, pe_static):
        if cand is not None and cand != 0:
            return cand
    return None


class StockFinancialSummaryHandler(webBase.BaseHandler, ABC):
    """GET /quantia/api/stock/financial_summary

    参数:
      code  — 6位股票代码（必填）
      limit — 历史期数（默认12，最多20）

    返回:
      {
        "code": "300560",
        "latest": { ... 最新一期摘要 ... },
        "history": [ ... 历史序列（从旧到新）... ]
      }
    """

    @gen.coroutine
    def get(self):
        code = (self.get_argument('code', '') or '').strip()
        if not code or len(code) != 6 or not code.isdigit():
            _write_json(self, {'error': 'code 必须是6位数字'}, 400)
            return

        try:
            limit = min(20, max(1, int(self.get_argument('limit', '12'))))
        except (ValueError, TypeError):
            limit = 12

        result: Dict[str, Any] = {'code': code}

        # ── 从 cn_stock_financial 取历史财务数据 ──
        try:
            sql = """
                SELECT report_date, report_name, eps, bps, revenue, net_profit,
                       revenue_yoy, net_profit_yoy, roe, gross_margin, net_profit_margin,
                       asset_liability_ratio, current_ratio, quick_ratio,
                       total_asset_turnover, ocfps,
                       rd_expense, admin_expense, selling_expense, financial_expense, rd_ratio
                FROM cn_stock_financial
                WHERE code = %s AND revenue IS NOT NULL
                ORDER BY report_date DESC
                LIMIT %s
            """
            rows = mdb.executeSqlFetch(sql, (code, limit))
        except Exception as exc:
            _logger.warning(f'[financial] 查询异常: {exc}')
            rows = []

        cols = [
            'report_date', 'report_name', 'eps', 'bps', 'revenue', 'net_profit',
            'revenue_yoy', 'net_profit_yoy', 'roe', 'gross_margin', 'net_profit_margin',
            'asset_liability_ratio', 'current_ratio', 'quick_ratio',
            'total_asset_turnover', 'ocfps',
            'rd_expense', 'admin_expense', 'selling_expense', 'financial_expense', 'rd_ratio',
        ]

        history: List[Dict[str, Any]] = []
        for row in rows:
            item: Dict[str, Any] = {}
            for i, col in enumerate(cols):
                val = row[i]
                if val is None:
                    item[col] = None
                elif col == 'report_date':
                    item[col] = str(val)
                else:
                    item[col] = val
            history.append(item)

        # 从旧到新排列（方便前端绘制时间轴图表）
        history.reverse()

        if history:
            result['latest'] = history[-1]
        else:
            result['latest'] = None

        result['history'] = history

        # ── 从 cn_stock_spot 取最新估值快照 ──
        try:
            sql = """
                SELECT name, new_price, change_rate, pe9, pbnewmrq,
                       total_market_cap, turnoverrate, total_shares, free_shares,
                       dtsyl, pe
                FROM cn_stock_spot
                WHERE code = %s
                ORDER BY date DESC LIMIT 1
            """
            spot_rows = mdb.executeSqlFetch(sql, (code,))
            if spot_rows:
                r = spot_rows[0]
                # 市盈率优先级：TTM(pe9) → 动态(dtsyl) → 静态(pe)。
                pe_val = _pick_pe(r[3], r[9], r[10])
                result['valuation'] = {
                    'name': r[0],
                    'price': r[1],
                    'change_pct': r[2],
                    'pe': pe_val,
                    'pb': r[4],
                    'market_cap': r[5],        # 万元
                    'turnover_rate': r[6],
                    'total_shares': r[7],      # 万股
                    'free_shares': r[8],       # 万股
                }
        except Exception as exc:
            _logger.debug(f'[financial] spot 查询异常: {exc}')

        _write_json(self, result)
