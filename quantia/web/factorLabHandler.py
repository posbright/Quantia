#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""因子实验室 API Handler (Phase 6)

提供多维因子组合回测、因子贡献分析、预设模板等接口。
支持策略信号 + 技术指标 + 基本面 + 资金流向的混合因子组合。

数据来源: MySQL（遵守 Fetch/Analysis/Web 分离原则）
"""

import datetime
import json
import logging
import math

import numpy as np
import pandas as pd

import quantia.core.tablestructure as tbs
import quantia.lib.database as mdb
import quantia.web.base as webBase
from quantia.web.verifyOptimizeHandler import (
    _calc_annualized_sharpe, _json_default, _safe_float,
    RATE_FIELDS_COUNT,
)

__author__ = 'Quantia'
__date__ = '2026/05/18'

logger = logging.getLogger(__name__)

# ── 因子目录 ──────────────────────────────────────────────────────────

_INDICATORS_TABLE = tbs.TABLE_CN_STOCK_INDICATORS['name']
_SELECTION_TABLE = tbs.TABLE_CN_STOCK_SELECTION['name']
_FUND_FLOW_TABLE = tbs.TABLE_CN_STOCK_FUND_FLOW['name']

# 策略信号因子列表（从 tablestructure 自动构建）
_STRATEGY_FACTORS = []
for _s in tbs.TABLE_CN_STOCK_STRATEGIES:
    _short = _s['name'].replace('cn_stock_strategy_', '')
    _STRATEGY_FACTORS.append({
        'id': _short,
        'name': _s['cn'],
        'category': 'tech_signal',
        'type': 'signal',
        'table': _s['name'],
        'column': None,
        'icon': _s['cn'][0] if _s['cn'] else _short[0].upper(),
        'description': f"数据: {_s['name']} | 规则: 当日被选入 = 信号触发",
    })
# GPT 策略
_gpt = tbs.TABLE_CN_STOCK_STRATEGY_GPT_VALUE
_STRATEGY_FACTORS.append({
    'id': 'gpt_value',
    'name': _gpt['cn'],
    'category': 'tech_signal',
    'type': 'signal',
    'table': _gpt['name'],
    'column': None,
    'icon': 'G',
    'description': f"数据: {_gpt['name']}",
})

# 技术指标因子
_INDICATOR_FACTORS = [
    {'id': 'rsi_6', 'name': 'RSI(6)', 'category': 'tech_indicator', 'type': 'continuous',
     'table': _INDICATORS_TABLE, 'column': 'rsi_6', 'direction': 'desc', 'icon': 'R',
     'default_operator': '<', 'default_value': 70,
     'presets': [
         {'label': '< 30 超卖', 'operator': '<', 'value': 30},
         {'label': '< 50 中性偏低', 'operator': '<', 'value': 50},
         {'label': '< 70 过滤超买', 'operator': '<', 'value': 70},
         {'label': '30~70 中性', 'operator': 'between', 'value': [30, 70]},
     ]},
    {'id': 'rsi_12', 'name': 'RSI(12)', 'category': 'tech_indicator', 'type': 'continuous',
     'table': _INDICATORS_TABLE, 'column': 'rsi_12', 'direction': 'desc', 'icon': 'R',
     'default_operator': '<', 'default_value': 70,
     'presets': [{'label': '< 30 超卖', 'operator': '<', 'value': 30},
                 {'label': '< 70 过滤超买', 'operator': '<', 'value': 70}]},
    {'id': 'macd', 'name': 'MACD(DIF)', 'category': 'tech_indicator', 'type': 'continuous',
     'table': _INDICATORS_TABLE, 'column': 'macd', 'direction': 'asc', 'icon': 'M',
     'default_operator': '>', 'default_value': 0,
     'presets': [{'label': '> 0 多头', 'operator': '>', 'value': 0}]},
    {'id': 'macdh', 'name': 'MACD柱', 'category': 'tech_indicator', 'type': 'continuous',
     'table': _INDICATORS_TABLE, 'column': 'macdh', 'direction': 'asc', 'icon': 'M',
     'default_operator': '>', 'default_value': 0,
     'presets': [{'label': '> 0 红柱', 'operator': '>', 'value': 0}]},
    {'id': 'kdjk', 'name': 'KDJ-K', 'category': 'tech_indicator', 'type': 'continuous',
     'table': _INDICATORS_TABLE, 'column': 'kdjk', 'direction': 'desc', 'icon': 'K',
     'default_operator': '<', 'default_value': 80,
     'presets': [{'label': '< 20 超卖', 'operator': '<', 'value': 20},
                 {'label': '< 80 过滤超买', 'operator': '<', 'value': 80},
                 {'label': '20~80 中性', 'operator': 'between', 'value': [20, 80]}]},
    {'id': 'kdjd', 'name': 'KDJ-D', 'category': 'tech_indicator', 'type': 'continuous',
     'table': _INDICATORS_TABLE, 'column': 'kdjd', 'direction': 'desc', 'icon': 'K',
     'default_operator': '<', 'default_value': 80, 'presets': []},
    {'id': 'cci', 'name': 'CCI', 'category': 'tech_indicator', 'type': 'continuous',
     'table': _INDICATORS_TABLE, 'column': 'cci', 'direction': 'asc', 'icon': 'C',
     'default_operator': '>', 'default_value': -100,
     'presets': [{'label': '> 100 强势', 'operator': '>', 'value': 100},
                 {'label': '> 0 偏强', 'operator': '>', 'value': 0},
                 {'label': '-100~100 中性', 'operator': 'between', 'value': [-100, 100]}]},
    {'id': 'adx', 'name': 'ADX', 'category': 'tech_indicator', 'type': 'continuous',
     'table': _INDICATORS_TABLE, 'column': 'adx', 'direction': 'asc', 'icon': 'A',
     'default_operator': '>', 'default_value': 25,
     'presets': [{'label': '> 25 趋势明显', 'operator': '>', 'value': 25},
                 {'label': '> 40 强趋势', 'operator': '>', 'value': 40}]},
    {'id': 'wr_6', 'name': 'WR(6)', 'category': 'tech_indicator', 'type': 'continuous',
     'table': _INDICATORS_TABLE, 'column': 'wr_6', 'direction': 'asc', 'icon': 'W',
     'default_operator': '<', 'default_value': -20,
     'presets': [{'label': '< -80 超卖', 'operator': '<', 'value': -80},
                 {'label': '< -50 偏弱', 'operator': '<', 'value': -50}]},
    {'id': 'bias', 'name': 'BIAS乖离率', 'category': 'tech_indicator', 'type': 'continuous',
     'table': _INDICATORS_TABLE, 'column': 'bias', 'direction': 'desc', 'icon': 'B',
     'default_operator': '<', 'default_value': 5,
     'presets': [{'label': '< 3 偏低', 'operator': '<', 'value': 3},
                 {'label': '-5~5 中性', 'operator': 'between', 'value': [-5, 5]}]},
    {'id': 'mfi', 'name': 'MFI资金流量', 'category': 'tech_indicator', 'type': 'continuous',
     'table': _INDICATORS_TABLE, 'column': 'mfi', 'direction': 'desc', 'icon': 'F',
     'default_operator': '<', 'default_value': 80,
     'presets': [{'label': '< 20 超卖', 'operator': '<', 'value': 20},
                 {'label': '< 80 过滤超买', 'operator': '<', 'value': 80}]},
    {'id': 'obv', 'name': 'OBV能量潮', 'category': 'tech_indicator', 'type': 'continuous',
     'table': _INDICATORS_TABLE, 'column': 'obv', 'direction': 'asc', 'icon': 'O',
     'default_operator': '>', 'default_value': 0, 'presets': []},
]

# 基本面因子
_FUNDAMENTAL_FACTORS = [
    {'id': 'pe9', 'name': '市盈率TTM', 'category': 'fundamental', 'type': 'range',
     'table': _SELECTION_TABLE, 'column': 'pe9', 'direction': 'desc', 'icon': 'P',
     'default_operator': 'between', 'default_value': [0, 30],
     'presets': [
         {'label': '0~15 深度价值', 'operator': 'between', 'value': [0, 15]},
         {'label': '0~30 合理估值', 'operator': 'between', 'value': [0, 30]},
         {'label': '0~50 宽松', 'operator': 'between', 'value': [0, 50]},
     ]},
    {'id': 'pbnewmrq', 'name': '市净率MRQ', 'category': 'fundamental', 'type': 'range',
     'table': _SELECTION_TABLE, 'column': 'pbnewmrq', 'direction': 'desc', 'icon': 'P',
     'default_operator': 'between', 'default_value': [0, 5],
     'presets': [{'label': '0~1 破净', 'operator': 'between', 'value': [0, 1]},
                 {'label': '0~3 合理', 'operator': 'between', 'value': [0, 3]},
                 {'label': '0~5 宽松', 'operator': 'between', 'value': [0, 5]}]},
    {'id': 'roe_weight', 'name': 'ROE加权', 'category': 'fundamental', 'type': 'continuous',
     'table': _SELECTION_TABLE, 'column': 'roe_weight', 'direction': 'asc', 'icon': 'R',
     'default_operator': '>=', 'default_value': 10,
     'presets': [{'label': '>= 10% 良好', 'operator': '>=', 'value': 10},
                 {'label': '>= 15% 优秀', 'operator': '>=', 'value': 15},
                 {'label': '>= 20% 卓越', 'operator': '>=', 'value': 20}]},
    {'id': 'jroa', 'name': 'ROA', 'category': 'fundamental', 'type': 'continuous',
     'table': _SELECTION_TABLE, 'column': 'jroa', 'direction': 'asc', 'icon': 'R',
     'default_operator': '>=', 'default_value': 5,
     'presets': [{'label': '>= 5% 良好', 'operator': '>=', 'value': 5}]},
    {'id': 'sale_gpr', 'name': '毛利率', 'category': 'fundamental', 'type': 'continuous',
     'table': _SELECTION_TABLE, 'column': 'sale_gpr', 'direction': 'asc', 'icon': '毛',
     'default_operator': '>=', 'default_value': 30,
     'presets': [{'label': '>= 20%', 'operator': '>=', 'value': 20},
                 {'label': '>= 30% 较高', 'operator': '>=', 'value': 30},
                 {'label': '>= 50% 高毛利', 'operator': '>=', 'value': 50}]},
    {'id': 'sale_npr', 'name': '净利率', 'category': 'fundamental', 'type': 'continuous',
     'table': _SELECTION_TABLE, 'column': 'sale_npr', 'direction': 'asc', 'icon': '净',
     'default_operator': '>=', 'default_value': 10,
     'presets': [{'label': '>= 5%', 'operator': '>=', 'value': 5},
                 {'label': '>= 10% 较高', 'operator': '>=', 'value': 10}]},
    {'id': 'debt_asset_ratio', 'name': '资产负债率', 'category': 'fundamental', 'type': 'continuous',
     'table': _SELECTION_TABLE, 'column': 'debt_asset_ratio', 'direction': 'desc', 'icon': '负',
     'default_operator': '<', 'default_value': 60,
     'presets': [{'label': '< 40% 低负债', 'operator': '<', 'value': 40},
                 {'label': '< 60% 适中', 'operator': '<', 'value': 60}]},
    {'id': 'netprofit_yoy_ratio', 'name': '净利润增长率', 'category': 'fundamental', 'type': 'continuous',
     'table': _SELECTION_TABLE, 'column': 'netprofit_yoy_ratio', 'direction': 'asc', 'icon': '增',
     'default_operator': '>', 'default_value': 0,
     'presets': [{'label': '> 0 正增长', 'operator': '>', 'value': 0},
                 {'label': '> 20% 高增长', 'operator': '>', 'value': 20},
                 {'label': '> 50% 超高增长', 'operator': '>', 'value': 50}]},
    {'id': 'toi_yoy_ratio', 'name': '营收增长率', 'category': 'fundamental', 'type': 'continuous',
     'table': _SELECTION_TABLE, 'column': 'toi_yoy_ratio', 'direction': 'asc', 'icon': '营',
     'default_operator': '>', 'default_value': 0,
     'presets': [{'label': '> 0 正增长', 'operator': '>', 'value': 0},
                 {'label': '> 20% 高增长', 'operator': '>', 'value': 20}]},
    {'id': 'basic_eps', 'name': '每股收益', 'category': 'fundamental', 'type': 'continuous',
     'table': _SELECTION_TABLE, 'column': 'basic_eps', 'direction': 'asc', 'icon': 'E',
     'default_operator': '>', 'default_value': 0,
     'presets': [{'label': '> 0 盈利', 'operator': '>', 'value': 0},
                 {'label': '> 0.5 较好', 'operator': '>', 'value': 0.5}]},
    {'id': 'zxgxl', 'name': '股息率', 'category': 'fundamental', 'type': 'continuous',
     'table': _SELECTION_TABLE, 'column': 'zxgxl', 'direction': 'asc', 'icon': '股',
     'default_operator': '>=', 'default_value': 2,
     'presets': [{'label': '>= 2% 适中', 'operator': '>=', 'value': 2},
                 {'label': '>= 4% 高股息', 'operator': '>=', 'value': 4}]},
]

# 资金流向因子
_FUND_FLOW_FACTORS = [
    {'id': 'fund_amount', 'name': '当日主力净流入', 'category': 'fund_flow', 'type': 'continuous',
     'table': _FUND_FLOW_TABLE, 'column': 'fund_amount', 'direction': 'asc', 'icon': '主',
     'default_operator': '>', 'default_value': 0,
     'presets': [{'label': '> 0 净流入', 'operator': '>', 'value': 0},
                 {'label': '> 5000万', 'operator': '>', 'value': 50000000}]},
    {'id': 'fund_amount_3', 'name': '3日主力净流入', 'category': 'fund_flow', 'type': 'continuous',
     'table': _FUND_FLOW_TABLE, 'column': 'fund_amount_3', 'direction': 'asc', 'icon': '3',
     'default_operator': '>', 'default_value': 0,
     'presets': [{'label': '> 0 净流入', 'operator': '>', 'value': 0}]},
    {'id': 'fund_amount_5', 'name': '5日主力净流入', 'category': 'fund_flow', 'type': 'continuous',
     'table': _FUND_FLOW_TABLE, 'column': 'fund_amount_5', 'direction': 'asc', 'icon': '5',
     'default_operator': '>', 'default_value': 0,
     'presets': [{'label': '> 0 净流入', 'operator': '>', 'value': 0}]},
    {'id': 'fund_amount_10', 'name': '10日主力净流入', 'category': 'fund_flow', 'type': 'continuous',
     'table': _FUND_FLOW_TABLE, 'column': 'fund_amount_10', 'direction': 'asc', 'icon': '⑩',
     'default_operator': '>', 'default_value': 0,
     'presets': [{'label': '> 0 净流入', 'operator': '>', 'value': 0}]},
    {'id': 'fund_rate', 'name': '当日主力净流入占比', 'category': 'fund_flow', 'type': 'continuous',
     'table': _FUND_FLOW_TABLE, 'column': 'fund_rate', 'direction': 'asc', 'icon': '%',
     'default_operator': '>', 'default_value': 0,
     'presets': [{'label': '> 0 正净流入', 'operator': '>', 'value': 0},
                 {'label': '> 5% 大幅流入', 'operator': '>', 'value': 5}]},
]

# 合并所有因子
FACTOR_CATALOG = _STRATEGY_FACTORS + _INDICATOR_FACTORS + _FUNDAMENTAL_FACTORS + _FUND_FLOW_FACTORS

# id -> factor meta 映射
_FACTOR_MAP = {f['id']: f for f in FACTOR_CATALOG}

# 允许的运算符
_VALID_OPS = {'<', '<=', '>', '>=', 'between'}

# 预设模板
PRESET_TEMPLATES = [
    {'id': 'blank', 'name': '空白', 'factors': [], 'fusion_mode': 'and'},
    {'id': 'tech_fund', 'name': '技术+基本面(推荐)', 'fusion_mode': 'score', 'factors': [
        {'id': 'keep_increasing', 'weight': 30, 'enabled': True},
        {'id': 'breakout_confirm', 'weight': 25, 'enabled': True},
        {'id': 'trend_pullback', 'weight': 20, 'enabled': True},
        {'id': 'rsi_6', 'operator': '<', 'value': 70, 'weight': 15, 'enabled': True},
        {'id': 'pe9', 'operator': 'between', 'value': [0, 30], 'weight': 12, 'enabled': True},
        {'id': 'roe_weight', 'operator': '>=', 'value': 10, 'weight': 15, 'enabled': True},
        {'id': 'fund_amount', 'operator': '>', 'value': 0, 'weight': 10, 'enabled': True},
        {'id': 'fund_amount_3', 'operator': '>', 'value': 0, 'weight': 8, 'enabled': True},
    ]},
    {'id': 'pure_tech', 'name': '纯技术多因子', 'fusion_mode': 'and', 'factors': [
        {'id': 'keep_increasing', 'weight': 20, 'enabled': True},
        {'id': 'breakout_confirm', 'weight': 20, 'enabled': True},
        {'id': 'turtle_trade', 'weight': 20, 'enabled': True},
        {'id': 'rsi_6', 'operator': '<', 'value': 50, 'weight': 15, 'enabled': True},
        {'id': 'macd', 'operator': '>', 'value': 0, 'weight': 15, 'enabled': True},
    ]},
    {'id': 'value_invest', 'name': '价值投资', 'fusion_mode': 'and', 'factors': [
        {'id': 'pe9', 'operator': 'between', 'value': [0, 20], 'weight': 20, 'enabled': True},
        {'id': 'pbnewmrq', 'operator': 'between', 'value': [0, 3], 'weight': 15, 'enabled': True},
        {'id': 'roe_weight', 'operator': '>=', 'value': 15, 'weight': 20, 'enabled': True},
        {'id': 'sale_gpr', 'operator': '>=', 'value': 30, 'weight': 15, 'enabled': True},
        {'id': 'debt_asset_ratio', 'operator': '<', 'value': 50, 'weight': 15, 'enabled': True},
        {'id': 'zxgxl', 'operator': '>=', 'value': 2, 'weight': 15, 'enabled': True},
    ]},
    {'id': 'money_driven', 'name': '资金驱动', 'fusion_mode': 'vote', 'vote_threshold': 3, 'factors': [
        {'id': 'fund_amount', 'operator': '>', 'value': 0, 'weight': 20, 'enabled': True},
        {'id': 'fund_amount_3', 'operator': '>', 'value': 0, 'weight': 20, 'enabled': True},
        {'id': 'fund_amount_5', 'operator': '>', 'value': 0, 'weight': 20, 'enabled': True},
        {'id': 'fund_amount_10', 'operator': '>', 'value': 0, 'weight': 20, 'enabled': True},
        {'id': 'fund_rate', 'operator': '>', 'value': 0, 'weight': 20, 'enabled': True},
    ]},
    {'id': 'full_dimension', 'name': '全维度融合', 'fusion_mode': 'score', 'factors': [
        {'id': 'keep_increasing', 'weight': 20, 'enabled': True},
        {'id': 'rsi_6', 'operator': '<', 'value': 70, 'weight': 15, 'enabled': True},
        {'id': 'pe9', 'operator': 'between', 'value': [0, 30], 'weight': 15, 'enabled': True},
        {'id': 'roe_weight', 'operator': '>=', 'value': 10, 'weight': 20, 'enabled': True},
        {'id': 'fund_amount', 'operator': '>', 'value': 0, 'weight': 15, 'enabled': True},
        {'id': 'debt_asset_ratio', 'operator': '<', 'value': 60, 'weight': 15, 'enabled': True},
    ]},
]


# ── 工具函数 ──────────────────────────────────────────────────────────

def _write_json(handler, data):
    handler.set_header('Content-Type', 'application/json;charset=UTF-8')
    handler.write(json.dumps(data, ensure_ascii=False, default=_json_default))


def _write_error(handler, msg, code=400):
    handler.set_status(code)
    _write_json(handler, {'error': msg})


def _parse_date(s):
    if not s:
        return None
    s = str(s).strip().replace('/', '-')
    for fmt in ('%Y-%m-%d', '%Y%m%d'):
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _apply_condition(series, operator, value):
    """对 pandas Series 应用条件运算符，返回布尔 Series。"""
    if operator == '<':
        return series < float(value)
    elif operator == '<=':
        return series <= float(value)
    elif operator == '>':
        return series > float(value)
    elif operator == '>=':
        return series >= float(value)
    elif operator == 'between':
        if isinstance(value, (list, tuple)) and len(value) == 2:
            return (series >= float(value[0])) & (series <= float(value[1]))
        return pd.Series(True, index=series.index)
    return pd.Series(True, index=series.index)


def _load_filter_data(table_name, columns, start_date, end_date):
    """从指标/基本面/资金流表加载过滤数据。"""
    if not mdb.checkTableIsExist(table_name):
        return None
    cols_sql = ', '.join(['`date`', '`code`'] + [f'`{c}`' for c in columns])
    sql = f"SELECT {cols_sql} FROM `{table_name}` WHERE `date` >= %s AND `date` <= %s"
    try:
        df = pd.read_sql(sql, con=mdb.engine(), params=(str(start_date), str(end_date)))
    except Exception as e:
        logger.error(f"加载 {table_name} 失败: {e}", exc_info=True)
        return None
    return df if df is not None and len(df) > 0 else None


def _compute_daily_series(rates_by_date):
    """从日级平均收益计算累计收益曲线与回撤。

    rates_by_date: Series(index=date, value=avg_rate_pct)
    """
    if rates_by_date is None or len(rates_by_date) == 0:
        return []
    cumulative = (1 + rates_by_date / 100).cumprod() * 100
    running_max = cumulative.cummax()
    drawdown = (cumulative - running_max) / running_max * 100
    result = []
    for dt in cumulative.index:
        result.append({
            'date': dt.strftime('%Y-%m-%d') if hasattr(dt, 'strftime') else str(dt),
            'cumulative': _safe_float(round(float(cumulative.loc[dt]), 2)),
            'drawdown': _safe_float(round(float(drawdown.loc[dt]), 2)),
        })
    return result


def _compute_kpi(rates, holding_days, total_dates=0):
    """从收益率数组计算 KPI 指标。"""
    if rates is None or len(rates) == 0:
        return {
            'sharpe': None, 'win_rate': None, 'avg_return': None,
            'max_drawdown': None, 'calmar': None,
            'daily_signal_avg': 0, 'signal_count': 0, 'filter_rate': None,
        }
    rates = np.asarray(rates, dtype=float)
    rates = rates[np.isfinite(rates)]
    if len(rates) == 0:
        return {
            'sharpe': None, 'win_rate': None, 'avg_return': None,
            'max_drawdown': None, 'calmar': None,
            'daily_signal_avg': 0, 'signal_count': 0, 'filter_rate': None,
        }
    sharpe = _calc_annualized_sharpe(rates, holding_days)
    avg_ret = float(rates.mean())
    win_rate = float((rates > 0).mean() * 100)

    # 最大回撤（从日均收益推算）
    daily_cum = (1 + rates / 100).cumprod()
    running_max = np.maximum.accumulate(daily_cum)
    dd = (daily_cum - running_max) / running_max * 100
    max_dd = float(dd.min()) if len(dd) > 0 else 0.0

    # Calmar
    annualized_return = avg_ret * 252 / holding_days
    calmar = None
    if max_dd != 0:
        calmar = _safe_float(abs(annualized_return / max_dd))

    daily_avg = len(rates) / max(total_dates, 1) if total_dates > 0 else 0.0

    return {
        'sharpe': _safe_float(sharpe),
        'win_rate': _safe_float(round(win_rate, 1)),
        'avg_return': _safe_float(round(avg_ret, 2)),
        'max_drawdown': _safe_float(round(max_dd, 1)),
        'calmar': calmar,
        'daily_signal_avg': _safe_float(round(daily_avg, 1)),
        'signal_count': int(len(rates)),
        'filter_rate': None,
    }


# ── Handler: 因子目录 ─────────────────────────────────────────────────

class FactorCatalogHandler(webBase.BaseHandler):
    """GET /quantia/api/factor_lab/factors

    返回可用因子目录，按类别分组。
    """

    def get(self):
        try:
            categories = [
                {'key': 'tech_signal', 'name': '技术策略信号', 'icon': '📊',
                 'factors': [f for f in FACTOR_CATALOG if f['category'] == 'tech_signal']},
                {'key': 'tech_indicator', 'name': '技术指标', 'icon': '📈',
                 'factors': [f for f in FACTOR_CATALOG if f['category'] == 'tech_indicator']},
                {'key': 'fundamental', 'name': '基本面', 'icon': '📋',
                 'factors': [f for f in FACTOR_CATALOG if f['category'] == 'fundamental']},
                {'key': 'fund_flow', 'name': '资金流向', 'icon': '💰',
                 'factors': [f for f in FACTOR_CATALOG if f['category'] == 'fund_flow']},
            ]
            _write_json(self, {'categories': categories})
        except Exception:
            logger.error("因子目录异常", exc_info=True)
            _write_error(self, '服务器内部错误', 500)


# ── Handler: 运行因子组合回测 ──────────────────────────────────────────

class FactorLabRunHandler(webBase.BaseHandler):
    """POST /quantia/api/factor_lab/run

    运行因子组合回测，返回 KPI + 日级走势 + 因子贡献。
    """

    def post(self):
        try:
            self._handle()
        except Exception:
            logger.error("因子实验室运行异常", exc_info=True)
            _write_error(self, '服务器内部错误', 500)

    def _handle(self):
        try:
            body = json.loads(self.request.body)
        except (json.JSONDecodeError, TypeError):
            _write_error(self, '请求体必须为 JSON')
            return

        factors_raw = body.get('factors', [])
        if not isinstance(factors_raw, list) or len(factors_raw) == 0:
            _write_error(self, '至少需要 1 个因子')
            return
        if len(factors_raw) > 15:
            _write_error(self, '最多支持 15 个因子')
            return

        fusion_mode = body.get('fusion_mode', 'and')
        if fusion_mode not in ('and', 'vote', 'score'):
            _write_error(self, "fusion_mode 必须为 and / vote / score")
            return

        vote_threshold = int(body.get('vote_threshold', 2))
        holding_days = max(1, min(int(body.get('holding_days', 10)), RATE_FIELDS_COUNT))

        start_date = _parse_date(body.get('start_date', ''))
        end_date = _parse_date(body.get('end_date', ''))
        if not start_date or not end_date:
            _write_error(self, 'start_date 和 end_date 必填，格式 YYYY-MM-DD')
            return
        if start_date > end_date:
            start_date, end_date = end_date, start_date
        if (end_date - start_date).days > 366:
            _write_error(self, '日期区间不超过 366 天')
            return

        rate_col = f'rate_{holding_days}'

        # 解析并验证因子配置
        parsed_factors = []
        for fc in factors_raw:
            fid = fc.get('id', '')
            if not fc.get('enabled', True):
                continue
            meta = _FACTOR_MAP.get(fid)
            if meta is None:
                _write_error(self, f"未知因子 id: '{fid}'")
                return
            pf = {
                'id': fid,
                'meta': meta,
                'weight': max(0, min(100, int(fc.get('weight', 10)))),
                'operator': fc.get('operator', meta.get('default_operator', '>')),
                'value': fc.get('value', meta.get('default_value', 0)),
            }
            if meta['type'] != 'signal' and pf['operator'] not in _VALID_OPS:
                _write_error(self, f"因子 {fid} 的运算符无效: {pf['operator']}")
                return
            parsed_factors.append(pf)

        if not parsed_factors:
            _write_error(self, '没有启用的因子')
            return

        # 分离策略因子与过滤因子
        signal_factors = [f for f in parsed_factors if f['meta']['type'] == 'signal']
        filter_factors = [f for f in parsed_factors if f['meta']['type'] != 'signal']

        if not signal_factors:
            _write_error(self, '至少需要 1 个策略信号因子（提供收益率数据）')
            return

        # 加载策略信号数据
        strategy_dfs = {}
        for sf in signal_factors:
            table = sf['meta']['table']
            if table in strategy_dfs:
                continue
            if not mdb.checkTableIsExist(table):
                _write_error(self, f"策略表 {table} 不存在")
                return
            sql = f"""
                SELECT `date`, `code`, `{rate_col}` AS rate
                FROM `{table}`
                WHERE `date` >= %s AND `date` <= %s
                  AND `{rate_col}` IS NOT NULL
            """
            try:
                df = pd.read_sql(sql, con=mdb.engine(),
                                 params=(str(start_date), str(end_date)))
            except Exception as e:
                logger.error(f"加载 {table}: {e}", exc_info=True)
                _write_error(self, f'加载策略 {sf["meta"]["name"]} 失败', 500)
                return
            strategy_dfs[table] = df if df is not None and len(df) > 0 \
                else pd.DataFrame(columns=['date', 'code', 'rate'])

        # 策略信号融合（得到基础信号池）
        base_df = self._fuse_strategy_signals(
            strategy_dfs, signal_factors, fusion_mode, vote_threshold)

        if base_df is None or len(base_df) == 0:
            _write_json(self, {
                'kpi': _compute_kpi(np.array([]), holding_days),
                'baseline': _compute_kpi(np.array([]), holding_days),
                'daily_series': [], 'factor_contributions': [],
                'signal_sparse_warning': True,
            })
            return

        # 记录过滤前基线指标
        baseline_rates = base_df['rate'].dropna().values
        total_dates = base_df['date'].nunique()
        baseline_kpi = _compute_kpi(baseline_rates, holding_days, total_dates)

        # 应用过滤因子
        filtered_df = base_df.copy()
        if filter_factors:
            filtered_df = self._apply_filter_factors(
                filtered_df, filter_factors, start_date, end_date)

        # 计算最终 KPI
        final_rates = filtered_df['rate'].dropna().values if filtered_df is not None and len(filtered_df) > 0 else np.array([])
        final_kpi = _compute_kpi(final_rates, holding_days, total_dates)

        # 筛选率
        if baseline_kpi['signal_count'] > 0 and final_kpi['signal_count'] > 0:
            final_kpi['filter_rate'] = _safe_float(
                round(final_kpi['signal_count'] / baseline_kpi['signal_count'] * 100, 1))

        # 日级累计走势
        daily_series = []
        if filtered_df is not None and len(filtered_df) > 0:
            fdf = filtered_df.copy()
            fdf['date'] = pd.to_datetime(fdf['date'])
            daily_avg = fdf.groupby('date')['rate'].mean().sort_index()
            daily_series = _compute_daily_series(daily_avg)

        # 因子贡献分析（每个因子的边际夏普贡献）
        factor_contributions = self._compute_contributions(
            strategy_dfs, signal_factors, filter_factors,
            parsed_factors, fusion_mode, vote_threshold,
            start_date, end_date, holding_days, final_kpi)

        # 信号稀疏警告
        signal_sparse = (final_kpi['daily_signal_avg'] or 0) < 3

        _write_json(self, {
            'kpi': final_kpi,
            'baseline': baseline_kpi,
            'daily_series': daily_series,
            'factor_contributions': factor_contributions,
            'signal_sparse_warning': signal_sparse,
            'holding_days': holding_days,
            'period': f'{start_date} ~ {end_date}',
            'fusion_mode': fusion_mode,
        })

    @staticmethod
    def _fuse_strategy_signals(strategy_dfs, signal_factors, fusion_mode, vote_threshold):
        """融合多策略信号，返回 DataFrame(date, code, rate)。"""
        if len(signal_factors) == 1:
            table = signal_factors[0]['meta']['table']
            return strategy_dfs.get(table, pd.DataFrame(columns=['date', 'code', 'rate']))

        # 合并所有策略
        dfs = []
        tables = []
        for sf in signal_factors:
            table = sf['meta']['table']
            if table in tables:
                continue
            tables.append(table)
            df = strategy_dfs.get(table)
            if df is not None and len(df) > 0:
                dfs.append(df[['date', 'code', 'rate']].copy())
        if not dfs:
            return pd.DataFrame(columns=['date', 'code', 'rate'])

        combined = pd.concat(dfs, ignore_index=True)

        if fusion_mode == 'and':
            counts = combined.groupby(['date', 'code']).size().reset_index(name='cnt')
            valid = counts[counts['cnt'] >= len(tables)][['date', 'code']]
            avg_rate = combined.groupby(['date', 'code'])['rate'].mean().reset_index()
            return valid.merge(avg_rate, on=['date', 'code'], how='inner')

        elif fusion_mode == 'vote':
            threshold = max(2, min(vote_threshold, len(tables)))
            counts = combined.groupby(['date', 'code']).size().reset_index(name='cnt')
            valid = counts[counts['cnt'] >= threshold][['date', 'code']]
            avg_rate = combined.groupby(['date', 'code'])['rate'].mean().reset_index()
            return valid.merge(avg_rate, on=['date', 'code'], how='inner')

        else:  # score — 取并集，用加权平均
            return combined.groupby(['date', 'code'])['rate'].mean().reset_index()

    def _apply_filter_factors(self, base_df, filter_factors, start_date, end_date):
        """对基础信号池应用非策略因子过滤。"""
        if base_df is None or len(base_df) == 0:
            return base_df

        # 按来源表分组，一次性加载
        table_cols = {}
        for ff in filter_factors:
            table = ff['meta']['table']
            col = ff['meta']['column']
            if table not in table_cols:
                table_cols[table] = set()
            table_cols[table].add(col)

        # 加载各表数据
        table_data = {}
        for table, cols in table_cols.items():
            df = _load_filter_data(table, list(cols), start_date, end_date)
            if df is not None:
                table_data[table] = df

        result = base_df.copy()
        for ff in filter_factors:
            table = ff['meta']['table']
            col = ff['meta']['column']
            if table not in table_data:
                continue
            filt_df = table_data[table]
            if col not in filt_df.columns:
                continue

            # 合并过滤数据到结果集
            merged = result.merge(
                filt_df[['date', 'code', col]], on=['date', 'code'], how='inner')
            mask = _apply_condition(merged[col], ff['operator'], ff['value'])
            result = merged.loc[mask, ['date', 'code', 'rate']].reset_index(drop=True)

        return result

    def _compute_contributions(self, strategy_dfs, signal_factors, filter_factors,
                               all_factors, fusion_mode, vote_threshold,
                               start_date, end_date, holding_days, full_kpi):
        """计算每个因子的边际贡献 = 全集夏普 - 剔除该因子后的夏普。"""
        if full_kpi.get('sharpe') is None or len(all_factors) <= 1:
            return []

        full_sharpe = full_kpi['sharpe']
        contributions = []

        for i, factor in enumerate(all_factors):
            remaining = [f for j, f in enumerate(all_factors) if j != i]
            remaining_signals = [f for f in remaining if f['meta']['type'] == 'signal']
            remaining_filters = [f for f in remaining if f['meta']['type'] != 'signal']

            if not remaining_signals:
                # 剔除后无策略信号，该因子是唯一策略因子，贡献=全部夏普
                contributions.append({
                    'id': factor['id'],
                    'name': factor['meta']['name'],
                    'category': factor['meta']['category'],
                    'impact': full_sharpe,
                })
                continue

            # 用剩余因子重算
            without_df = self._fuse_strategy_signals(
                strategy_dfs, remaining_signals, fusion_mode, vote_threshold)

            if remaining_filters and without_df is not None and len(without_df) > 0:
                without_df = self._apply_filter_factors(
                    without_df, remaining_filters, start_date, end_date)

            without_rates = without_df['rate'].dropna().values if without_df is not None and len(without_df) > 0 else np.array([])
            without_sharpe = _calc_annualized_sharpe(without_rates, holding_days) if len(without_rates) > 1 else 0.0
            if without_sharpe is None:
                without_sharpe = 0.0

            impact = round(full_sharpe - without_sharpe, 2)
            contributions.append({
                'id': factor['id'],
                'name': factor['meta']['name'],
                'category': factor['meta']['category'],
                'impact': _safe_float(impact),
            })

        # 按贡献从大到小排序
        contributions.sort(key=lambda c: (c.get('impact') or 0), reverse=True)
        return contributions


# ── Handler: 单因子边际贡献 ───────────────────────────────────────────

class FactorImpactHandler(webBase.BaseHandler):
    """POST /quantia/api/factor_lab/factor_impact

    计算添加/移除指定因子的边际贡献。
    """

    def post(self):
        try:
            self._handle()
        except Exception:
            logger.error("因子贡献分析异常", exc_info=True)
            _write_error(self, '服务器内部错误', 500)

    def _handle(self):
        try:
            body = json.loads(self.request.body)
        except (json.JSONDecodeError, TypeError):
            _write_error(self, '请求体必须为 JSON')
            return

        target_factor_id = body.get('target_factor_id', '')
        if not target_factor_id or target_factor_id not in _FACTOR_MAP:
            _write_error(self, f"未知 target_factor_id: '{target_factor_id}'")
            return

        _write_json(self, {
            'target_factor_id': target_factor_id,
            'message': '请使用 /factor_lab/run 接口的 factor_contributions 字段获取因子贡献',
        })


# ── Handler: 预设模板 ─────────────────────────────────────────────────

class FactorPresetsHandler(webBase.BaseHandler):
    """GET /quantia/api/factor_lab/presets

    返回预设因子组合模板列表。
    """

    def get(self):
        try:
            # 为每个预设丰富因子元数据
            result = []
            for preset in PRESET_TEMPLATES:
                enriched_factors = []
                for pf in preset.get('factors', []):
                    meta = _FACTOR_MAP.get(pf['id'])
                    if meta:
                        enriched = {**pf, 'name': meta['name'], 'category': meta['category'],
                                    'type': meta['type'], 'icon': meta.get('icon', '')}
                        enriched_factors.append(enriched)
                result.append({
                    'id': preset['id'],
                    'name': preset['name'],
                    'fusion_mode': preset.get('fusion_mode', 'and'),
                    'vote_threshold': preset.get('vote_threshold'),
                    'factors': enriched_factors,
                })
            _write_json(self, {'presets': result})
        except Exception:
            logger.error("预设模板异常", exc_info=True)
            _write_error(self, '服务器内部错误', 500)
