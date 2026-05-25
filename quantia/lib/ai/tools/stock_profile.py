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
        SELECT code, name, new_price, change_rate, ups_downs,
               turnoverrate, volume, amplitude, high_price, low_price, open_price,
               total_market_cap, free_cap,
               pe9, pbnewmrq, basic_eps, roe_weight, sale_gpr,
               debt_asset_ratio, toi_yoy_ratio, netprofit_yoy_ratio, date
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
        SELECT macd, macds, macdh, kdjk, kdjd, kdjj,
               rsi_6, rsi_12, rsi_24, boll_ub, boll, boll_lb,
               cci, wr_6, wr_10, atr, date
        FROM cn_stock_indicators
        WHERE code = %s
        ORDER BY date DESC LIMIT 1
    """
    rows = executeSqlFetch(sql, (code,))
    if not rows:
        return {}
    keys = ['macd', 'macd_signal', 'macd_hist', 'kdj_k', 'kdj_d', 'kdj_j',
            'rsi_6', 'rsi_12', 'rsi_24', 'boll_upper', 'boll_mid', 'boll_lower',
            'cci', 'wr_6', 'wr_10', 'atr', 'date']
    return _row_to_dict(rows[0], keys)


def _query_fund_flow(code: str, days: int = 5) -> List[Dict[str, Any]]:
    """近N日资金流向。"""
    from quantia.lib.database import executeSqlFetch
    sql = """
        SELECT date, fund_amount, fund_amount_super, fund_amount_large,
               fund_amount_medium, fund_amount_small
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
    """最新K线形态信号列表（非零形态）。"""
    from quantia.lib.database import executeSqlFetch
    # 61 个形态列名（与 cn_stock_kline_pattern 表结构对应）
    _PATTERN_COLS = [
        'tow_crows', 'upside_gap_two_crows', 'three_black_crows',
        'identical_three_crows', 'three_line_strike', 'dark_cloud_cover',
        'evening_doji_star', 'doji_Star', 'hanging_man', 'hikkake_pattern',
        'modified_hikkake_pattern', 'in_neck_pattern', 'on_neck_pattern',
        'thrusting_pattern', 'shooting_star', 'stalled_pattern',
        'advance_block', 'high_wave_candle', 'engulfing_pattern',
        'abandoned_baby', 'closing_marubozu', 'doji', 'long_legged_doji',
        'rickshaw_man', 'marubozu', 'three_inside_up_down',
        'three_outside_up_down', 'three_stars_in_the_south',
        'three_white_soldiers', 'belt_hold', 'breakaway',
        'concealing_baby_swallow', 'counterattack', 'dragonfly_doji',
        'evening_star', 'gravestone_doji', 'hammer', 'harami_pattern',
        'harami_cross_pattern', 'homing_pigeon', 'inverted_hammer',
        'kicking', 'ladder_bottom', 'long_line_candle', 'matching_low',
        'mat_hold', 'morning_doji_star', 'morning_star', 'piercing_pattern',
        'rising_falling_three', 'separating_lines', 'short_line_candle',
        'spinning_top', 'stick_sandwich', 'takuri', 'tasuki_gap',
        'tristar_pattern', 'unique_3_river', 'upside_downside_gap',
    ]
    _PATTERN_CN = {
        'tow_crows': '两只乌鸦', 'upside_gap_two_crows': '向上跳空的两只乌鸦',
        'three_black_crows': '三只乌鸦', 'identical_three_crows': '三胞胎乌鸦',
        'three_line_strike': '三线打击', 'dark_cloud_cover': '乌云压顶',
        'evening_doji_star': '十字暮星', 'doji_Star': '十字星',
        'hanging_man': '上吊线', 'hikkake_pattern': '陷阱',
        'modified_hikkake_pattern': '修正陷阱', 'in_neck_pattern': '颈内线',
        'on_neck_pattern': '颈上线', 'thrusting_pattern': '插入',
        'shooting_star': '射击之星', 'stalled_pattern': '停顿形态',
        'advance_block': '大敌当前', 'high_wave_candle': '风高浪大线',
        'engulfing_pattern': '吞噬模式', 'abandoned_baby': '弃婴',
        'closing_marubozu': '收盘缺影线', 'doji': '十字',
        'long_legged_doji': '长脚十字', 'rickshaw_man': '黄包车夫',
        'marubozu': '光头光脚', 'three_inside_up_down': '三内部上涨和下跌',
        'three_outside_up_down': '三外部上涨和下跌',
        'three_stars_in_the_south': '南方三星', 'three_white_soldiers': '三个白兵',
        'belt_hold': '捉腰带线', 'breakaway': '脱离',
        'concealing_baby_swallow': '藏婴吞没', 'counterattack': '反击线',
        'dragonfly_doji': '蜻蜓十字', 'evening_star': '暮星',
        'gravestone_doji': '墓碑十字', 'hammer': '锤头',
        'harami_pattern': '母子线', 'harami_cross_pattern': '十字孕线',
        'homing_pigeon': '家鸽', 'inverted_hammer': '倒锤头',
        'kicking': '反冲形态', 'ladder_bottom': '梯底',
        'long_line_candle': '长蜡烛', 'matching_low': '相同低价',
        'mat_hold': '铺垫', 'morning_doji_star': '十字晨星',
        'morning_star': '晨星', 'piercing_pattern': '刺透形态',
        'rising_falling_three': '上升/下降三法', 'separating_lines': '分离线',
        'short_line_candle': '短蜡烛', 'spinning_top': '纺锤',
        'stick_sandwich': '条形三明治', 'takuri': '探水竿',
        'tasuki_gap': '跳空并列阴阳线', 'tristar_pattern': '三星',
        'unique_3_river': '奇特三河床', 'upside_downside_gap': '上升/下降跳空三法',
    }
    cols_sql = ', '.join(f'`{c}`' for c in _PATTERN_COLS)
    sql = f"SELECT {cols_sql} FROM cn_stock_kline_pattern WHERE code = %s ORDER BY date DESC LIMIT 1"
    rows = executeSqlFetch(sql, (code,))
    if not rows:
        return []
    signals = []
    for col_name, val in zip(_PATTERN_COLS, rows[0]):
        if val and val != 0:
            direction = '看涨' if val > 0 else '看跌'
            cn_name = _PATTERN_CN.get(col_name, col_name)
            signals.append(f'{cn_name}({direction})')
    return signals


def _query_kline_30d(code: str) -> List[Dict[str, Any]]:
    """近30日OHLCV摘要。直接从 cache/hist/ pickle 文件读取，不触发在线获取。"""
    import os
    try:
        import pandas as pd
        # 遵守架构规则：Web pipeline 不调外部 API，仅读本地缓存
        cache_base = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))))), 'cache', 'hist')
        # 统一缓存路径优先
        unified_path = os.path.join(cache_base, code[:3], f'{code}qfq.gzip.pickle')
        legacy_path = os.path.join(cache_base, f'{code}.gzip.pickle')

        df = None
        if os.path.exists(unified_path):
            df = pd.read_pickle(unified_path, compression='gzip')
        elif os.path.exists(legacy_path):
            df = pd.read_pickle(legacy_path)

        if df is None or len(df) == 0:
            return []

        # 标准化列名
        col_map = {'Date': 'date', 'Open': 'open', 'High': 'high',
                   'Low': 'low', 'Close': 'close', 'Volume': 'volume'}
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
        if 'date' not in df.columns and df.index.name in ('date', 'Date', None):
            df = df.reset_index()
            if 'Date' in df.columns:
                df = df.rename(columns={'Date': 'date'})

        df = df.tail(30)
        result = []
        for _, row in df.iterrows():
            bar: Dict[str, Any] = {}
            for k in ('date', 'open', 'high', 'low', 'close', 'volume'):
                if k not in row:
                    continue
                v = row[k]
                # Skip None, NaT, NaN, inf
                if v is None:
                    continue
                try:
                    if pd.isna(v):
                        continue
                except (TypeError, ValueError):
                    pass
                if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                    continue
                if hasattr(v, 'isoformat'):
                    bar[k] = str(v)[:10]  # date only, no time component
                elif isinstance(v, float):
                    bar[k] = round(v, 4)
                elif hasattr(v, 'item'):
                    # numpy scalar → native Python (int64→int, float64→float)
                    bar[k] = v.item()
                else:
                    bar[k] = v
            result.append(bar)
        return result
    except Exception as exc:
        _logger.warning(f'[stock_profile] 加载 K 线失败 ({code}): {exc}', exc_info=True)
        return []


def _query_financials(code: str) -> Dict[str, Any]:
    """最新一期财务数据：费用明细 + 关键增长率。"""
    from quantia.lib.database import executeSqlFetch
    # 先尝试带费用列的查询，若列不存在则降级
    sql_full = """
        SELECT report_date, revenue, net_profit, revenue_yoy, net_profit_yoy,
               roe, roa, gross_margin, net_profit_margin, asset_liability_ratio,
               rd_expense, admin_expense, selling_expense, financial_expense, rd_ratio
        FROM cn_stock_financial
        WHERE code = %s
        ORDER BY report_date DESC LIMIT 1
    """
    sql_basic = """
        SELECT report_date, revenue, net_profit, revenue_yoy, net_profit_yoy,
               roe, roa, gross_margin, net_profit_margin, asset_liability_ratio
        FROM cn_stock_financial
        WHERE code = %s
        ORDER BY report_date DESC LIMIT 1
    """
    keys_full = ['report_date', 'revenue', 'net_profit', 'revenue_yoy', 'net_profit_yoy',
                 'roe', 'roa', 'gross_margin', 'net_profit_margin', 'asset_liability_ratio',
                 'rd_expense', 'admin_expense', 'selling_expense', 'financial_expense', 'rd_ratio']
    keys_basic = ['report_date', 'revenue', 'net_profit', 'revenue_yoy', 'net_profit_yoy',
                  'roe', 'roa', 'gross_margin', 'net_profit_margin', 'asset_liability_ratio']

    # 字段中文别名（供 LLM 在报告中使用）
    _FIELD_CN = {
        'report_date': '报告期',
        'revenue': '营业收入',
        'net_profit': '净利润',
        'revenue_yoy': '营收同比增长率',
        'net_profit_yoy': '净利润同比增长率',
        'roe': '净资产收益率(ROE)',
        'roa': '总资产收益率(ROA)',
        'gross_margin': '毛利率',
        'net_profit_margin': '净利率',
        'asset_liability_ratio': '资产负债率',
        'rd_expense': '研发费用',
        'admin_expense': '管理费用',
        'selling_expense': '销售费用',
        'financial_expense': '财务费用',
        'rd_ratio': '研发费用率',
    }

    rows = executeSqlFetch(sql_full, (code,))
    if rows:
        d = _row_to_dict(rows[0], keys_full)
        d['_字段说明'] = {k: v for k, v in _FIELD_CN.items() if k in d}
        return d
    # 降级：可能是列不存在（1054错误）或无数据
    rows = executeSqlFetch(sql_basic, (code,))
    if rows:
        d = _row_to_dict(rows[0], keys_basic)
        d['_字段说明'] = {k: v for k, v in _FIELD_CN.items() if k in d}
        return d
    return {}


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
        financials = _query_financials(code)

        return {
            'code': code,
            'name': spot.get('name', ''),
            'spot': spot,
            'indicators': indicators,
            'fund_flow': fund_flow,
            'patterns': patterns,
            'kline_30d': kline_30d,
            'financials': financials,
        }
