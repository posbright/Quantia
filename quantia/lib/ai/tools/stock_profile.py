#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stock_profile 工具：聚合个股综合画像（行情/指标/资金/形态/K线）。

所有数据来自 MySQL，不调用外部 API（遵守 Fetch/Analysis/Web 分离原则）。
"""

import logging
import math
from typing import Any, Dict, List, Optional

from quantia.lib.ai.tools import Tool, ToolError

__author__ = 'Quantia'
__date__ = '2026/05/23'

_logger = logging.getLogger(__name__)


def _safe_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return round(f, 4)
    except (TypeError, ValueError):
        return None


def _safe_int(v) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _row_to_dict(row, keys: List[str]) -> Dict[str, Any]:
    """将 pymysql fetchone 元组转为 dict，跳过 None/NaN。"""
    if row is None:
        return {}
    d = {}
    for i, k in enumerate(keys):
        if i >= len(row):
            break
        v = row[i]
        if v is None:
            continue
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            continue
        if hasattr(v, 'isoformat'):
            d[k] = str(v)
        elif isinstance(v, float):
            d[k] = round(v, 4)
        else:
            d[k] = v
    return d


def _query_latest_spot(code: str) -> Dict[str, Any]:
    """最新行情快照：价格/涨跌/市值/PE/PB/换手率。"""
    from quantia.lib.database import executeSqlFetch
    sql = """
        SELECT code, name, new_price, change_rate, change_amount,
               turnover, volume, amplitude, high, low, open,
               total_market_cap, current_market_cap,
               pe9, pbnewmrq, eps, roe, gross_profit_margin,
               debt_asset_ratio, revenue_growth, profit_growth, date
        FROM cn_stock_spot
        WHERE code = %s
        ORDER BY date DESC LIMIT 1
    """
    rows = executeSqlFetch(sql, (code,))
    if not rows:
        return {}
    keys = ['code', 'name', 'new_price', 'change_rate', 'change_amount',
            'turnover', 'volume', 'amplitude', 'high', 'low', 'open',
            'total_market_cap', 'current_market_cap',
            'pe', 'pb', 'eps', 'roe', 'gross_profit_margin',
            'debt_asset_ratio', 'revenue_growth', 'profit_growth', 'date']
    return _row_to_dict(rows[0], keys)


def _query_indicators(code: str) -> Dict[str, Any]:
    """最新技术指标：MACD/KDJ/RSI/BOLL。"""
    from quantia.lib.database import executeSqlFetch
    sql = """
        SELECT macd, macd_dea, macd_dif, kdj_k, kdj_d, kdj_j,
               rsi_6, rsi_12, rsi_24, boll_upper, boll_mid, boll_lower,
               cci, wr_6, wr_10, atr, date
        FROM cn_stock_indicators
        WHERE code = %s
        ORDER BY date DESC LIMIT 1
    """
    rows = executeSqlFetch(sql, (code,))
    if not rows:
        return {}
    keys = ['macd', 'macd_dea', 'macd_dif', 'kdj_k', 'kdj_d', 'kdj_j',
            'rsi_6', 'rsi_12', 'rsi_24', 'boll_upper', 'boll_mid', 'boll_lower',
            'cci', 'wr_6', 'wr_10', 'atr', 'date']
    return _row_to_dict(rows[0], keys)


def _query_fund_flow(code: str, days: int = 5) -> List[Dict[str, Any]]:
    """近N日资金流向。"""
    from quantia.lib.database import executeSqlFetch
    sql = """
        SELECT date, main_net_inflow, super_net_inflow, big_net_inflow,
               mid_net_inflow, small_net_inflow
        FROM cn_stock_fund_flow
        WHERE code = %s
        ORDER BY date DESC LIMIT %s
    """
    rows = executeSqlFetch(sql, (code, days))
    if not rows:
        return []
    keys = ['date', 'main_net_inflow', 'super_net_inflow', 'big_net_inflow',
            'mid_net_inflow', 'small_net_inflow']
    return [_row_to_dict(r, keys) for r in rows]


def _query_patterns(code: str) -> List[str]:
    """最新K线形态信号列表。"""
    from quantia.lib.database import executeSqlFetch
    sql = """
        SELECT pattern_name
        FROM cn_stock_kline_pattern
        WHERE code = %s
        ORDER BY date DESC LIMIT 10
    """
    rows = executeSqlFetch(sql, (code,))
    if not rows:
        return []
    return [r[0] for r in rows if r[0]]


def _query_kline_30d(code: str) -> List[Dict[str, Any]]:
    """近30日OHLCV摘要。"""
    from quantia.lib.database import executeSqlFetch
    sql = """
        SELECT date, open, high, low, close, volume
        FROM cn_stock_kline_data
        WHERE code = %s
        ORDER BY date DESC LIMIT 30
    """
    rows = executeSqlFetch(sql, (code,))
    if not rows:
        # fallback: try loading from cache via data_feed
        try:
            from quantia.core.backtest.data_feed import load_stock_data
            import pandas as pd
            df = load_stock_data(code)
            if df is not None and len(df) > 0:
                df = df.tail(30)
                result = []
                for _, row in df.iterrows():
                    bar = {}
                    for k in ('date', 'open', 'high', 'low', 'close', 'volume'):
                        if k in row and row[k] is not None:
                            v = row[k]
                            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                                continue
                            bar[k] = str(v) if hasattr(v, 'isoformat') else v
                    result.append(bar)
                return result
        except Exception:
            pass
        return []
    keys = ['date', 'open', 'high', 'low', 'close', 'volume']
    return [_row_to_dict(r, keys) for r in rows]


class StockProfileTool(Tool):
    name = 'stock_profile'
    description = '获取个股综合画像：最新行情+近期指标+资金流向+K线形态信号+近30日K线。'
    parameters = {
        'type': 'object',
        'required': ['code'],
        'properties': {
            'code': {
                'type': 'string',
                'description': '6位股票代码（如 600000、000001）',
            },
        },
    }

    def run(self, args: Dict[str, Any]) -> Dict[str, Any]:
        code = (args.get('code') or '').strip()
        if not code:
            raise ToolError('code 不能为空')
        if len(code) != 6 or not code.isdigit():
            raise ToolError('code 必须是6位数字股票代码')

        spot = _query_latest_spot(code)
        if not spot:
            raise ToolError(f'未找到股票 {code} 的行情数据')

        indicators = _query_indicators(code)
        fund_flow = _query_fund_flow(code, 5)
        patterns = _query_patterns(code)
        kline_30d = _query_kline_30d(code)

        return {
            'code': code,
            'name': spot.get('name', ''),
            'spot': spot,
            'indicators': indicators,
            'fund_flow': fund_flow,
            'patterns': patterns,
            'kline_30d': kline_30d,
        }
