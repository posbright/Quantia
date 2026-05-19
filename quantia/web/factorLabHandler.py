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

# 自动补全 description：基于 category / 默认条件 / 预设档位生成统一文案，
# 让前端因子卡片 tooltip 可以始终展示"含义 + 取值"。已显式写入的 description 不覆盖。
_CATEGORY_LABEL = {
    'tech_signal': '技术策略信号', 'tech_indicator': '技术指标',
    'fundamental': '基本面指标', 'fund_flow': '资金流向指标',
}


def _auto_fill_description(f):
    if f.get('description'):
        return
    parts = []
    cat = _CATEGORY_LABEL.get(f.get('category', ''), f.get('category', ''))
    parts.append(f"{cat} · {f.get('name', f.get('id', ''))}")
    if f.get('type') == 'signal':
        parts.append('当日被该策略选中视为信号触发')
    else:
        op = f.get('default_operator')
        val = f.get('default_value')
        if op is not None and val is not None:
            vs = ('~'.join(str(x) for x in val)) if isinstance(val, (list, tuple)) else val
            parts.append(f"默认筛选: {op} {vs}")
        presets = f.get('presets') or []
        if presets:
            parts.append('常用阈值: ' + ' / '.join(p.get('label', '') for p in presets[:4]))
    f['description'] = '；'.join(p for p in parts if p)


for _f in FACTOR_CATALOG:
    _auto_fill_description(_f)

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


# ── 自定义策略动态注入 ────────────────────────────────────────────────

def _load_custom_strategy_factors():
    """从 cn_stock_strategy_code 读取活跃的自定义策略，注册为 tech_signal 因子。

    每个自定义策略对应一个 id 为 `custom_<strategy_id>` 的因子；其底层数据
    通过 verifyOptimizeHandler._build_custom_strategy_dataframe 在运行时按
    (date, code, rate_N) 形态组装，故 table/column 置 None 以示与表型策略不同。
    """
    factors = []
    if not mdb.checkTableIsExist('cn_stock_strategy_code'):
        return factors
    try:
        rows = mdb.executeSqlFetch(
            "SELECT id, name, description FROM cn_stock_strategy_code "
            "WHERE status != 'archived' ORDER BY updated_at DESC LIMIT 200")
    except Exception as e:
        logger.warning(f"加载自定义策略列表失败: {e}")
        return factors
    for r in (rows or []):
        sid = r[0]
        name = (r[1] or f'自定义策略 {sid}').strip()
        desc = (r[2] or '').strip()
        factors.append({
            'id': f'custom_{sid}',
            'name': f'{name}（自定义）',
            'category': 'tech_signal',
            'type': 'signal',
            'table': None,
            'column': None,
            'icon': name[0] if name else 'C',
            'description': (desc or f'用户自定义策略 #{sid}，来自 cn_stock_strategy_code；'
                            '运行时从组合回测交易日志 + K 线缓存逐笔补算收益'),
            'is_custom': True,
        })
    return factors


# ── Handler: 因子目录 ─────────────────────────────────────────────────

class FactorCatalogHandler(webBase.BaseHandler):
    """GET /quantia/api/factor_lab/factors

    返回可用因子目录，按类别分组。
    """

    def get(self):
        try:
            custom_factors = _load_custom_strategy_factors()
            tech_signals = [f for f in FACTOR_CATALOG if f['category'] == 'tech_signal'] + custom_factors
            categories = [
                {'key': 'tech_signal', 'name': '技术策略信号', 'icon': '📊',
                 'factors': tech_signals},
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
            if meta is None and fid.startswith('custom_'):
                # 自定义策略：动态构建 meta（cn_stock_strategy_code）
                try:
                    sid = int(fid.split('_', 1)[1])
                except (ValueError, IndexError):
                    _write_error(self, f"非法自定义策略 id: '{fid}'")
                    return
                name = f'自定义策略 #{sid}'
                if mdb.checkTableIsExist('cn_stock_strategy_code'):
                    try:
                        row = mdb.executeSqlFetch(
                            "SELECT name FROM cn_stock_strategy_code WHERE id=%s", (sid,))
                        if row and row[0] and row[0][0]:
                            name = str(row[0][0])
                    except Exception:
                        pass
                meta = {
                    'id': fid, 'name': name, 'category': 'tech_signal', 'type': 'signal',
                    'table': None, 'column': None, 'icon': name[0] if name else 'C',
                    'is_custom': True, 'strategy_id': sid,
                }
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

        # 加载策略信号数据（内置策略走表 / 自定义策略走交易日志+K线缓存）
        strategy_dfs = {}
        for sf in signal_factors:
            key = self._signal_key(sf)
            if key in strategy_dfs:
                continue
            if sf['meta'].get('is_custom'):
                df = self._load_custom_signal_df(
                    sf['meta'], start_date, end_date, holding_days)
                strategy_dfs[key] = df if df is not None and len(df) > 0 \
                    else pd.DataFrame(columns=['date', 'code', 'rate'])
                continue
            table = sf['meta']['table']
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
            strategy_dfs[key] = df if df is not None and len(df) > 0 \
                else pd.DataFrame(columns=['date', 'code', 'rate'])

        # 策略信号融合（得到基础信号池）
        base_df = self._fuse_strategy_signals(
            strategy_dfs, signal_factors, fusion_mode, vote_threshold)

        if base_df is None or len(base_df) == 0:
            # 基础池为空 — 区分"自定义策略无买入"与"内置策略表无信号"两种成因
            empty_per_strategy = {}
            for sf in signal_factors:
                key = self._signal_key(sf)
                df = strategy_dfs.get(key)
                empty_per_strategy[sf['meta']['name']] = int(0 if df is None else len(df))
            no_data_names = [n for n, c in empty_per_strategy.items() if c == 0]
            if no_data_names:
                hint = (
                    f"策略「{('、'.join(no_data_names))}」在所选区间无买入信号。"
                    "若为自定义策略，已尝试自动运行一次回测但仍无买入；"
                    "请检查策略代码、放宽时间区间或更换基准。"
                )
            else:
                hint = "所有策略信号在该区间均存在，但融合后无交集；尝试切换融合模式为「加权评分(Score)」或减少必选策略数。"
            _write_json(self, {
                'kpi': _compute_kpi(np.array([]), holding_days),
                'baseline': _compute_kpi(np.array([]), holding_days),
                'daily_series': [], 'factor_contributions': [],
                'signal_sparse_warning': True,
                'signal_sparse_reason': 'no_base_signal',
                'signal_sparse_hint': hint,
                'signal_diagnosis': {
                    'base_signal_count': 0,
                    'filtered_signal_count': 0,
                    'per_strategy_counts': empty_per_strategy,
                },
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

        # ── 信号稀疏诊断（按成因区分）──────────────────────────────
        base_cnt = int(baseline_kpi.get('signal_count') or 0)
        final_cnt = int(final_kpi.get('signal_count') or 0)
        daily_avg = float(final_kpi.get('daily_signal_avg') or 0)
        signal_sparse = daily_avg < 3
        signal_sparse_reason = None
        signal_sparse_hint = None
        if signal_sparse:
            if final_cnt == 0 and base_cnt > 0 and filter_factors:
                signal_sparse_reason = 'filtered_out'
                filter_names = '、'.join(ff['meta']['name'] for ff in filter_factors)
                signal_sparse_hint = (
                    f"基础信号池有 {base_cnt} 条，应用「{filter_names}」后归零。"
                    "建议：① 放宽过滤阈值（参考因子卡片的常用阈值预设）；"
                    "② 暂时禁用基本面因子（财报季度披露，与日级信号存在日期错位）；"
                    "③ 把起始日往后挪到 Q1 报披露完毕之后。"
                )
            elif final_cnt == 0 and base_cnt == 0:
                signal_sparse_reason = 'no_base_signal'
                signal_sparse_hint = (
                    "策略信号源在该区间无任何买入记录。若为自定义策略，"
                    "请先在「策略回测」页跑一次相同区间；或放宽日期范围。"
                )
            else:
                signal_sparse_reason = 'low_density'
                signal_sparse_hint = (
                    f"日均信号 {daily_avg:.1f} 偏低（阈值 3）。"
                    "可尝试：① 减少过滤因子数量；② 切换融合模式为「加权评分(Score)」（取并集而非交集）；"
                    "③ 检查持仓天数与日期窗口是否过短。"
                )

        _write_json(self, {
            'kpi': final_kpi,
            'baseline': baseline_kpi,
            'daily_series': daily_series,
            'factor_contributions': factor_contributions,
            'signal_sparse_warning': signal_sparse,
            'signal_sparse_reason': signal_sparse_reason,
            'signal_sparse_hint': signal_sparse_hint,
            'signal_diagnosis': {
                'base_signal_count': base_cnt,
                'filtered_signal_count': final_cnt,
                'filter_factor_count': len(filter_factors),
            },
            'holding_days': holding_days,
            'period': f'{start_date} ~ {end_date}',
            'fusion_mode': fusion_mode,
        })

    @staticmethod
    def _signal_key(sf):
        """返回 strategy_dfs 字典 key：内置走 table 名，自定义走 factor id。"""
        if sf['meta'].get('is_custom'):
            return sf['meta']['id']
        return sf['meta']['table']

    @staticmethod
    def _load_custom_signal_df(meta, start_date, end_date, holding_days):
        """自定义策略 → DataFrame[date, code, rate]。复用 verifyOptimize 的逐笔补算。"""
        from quantia.web.verifyOptimizeHandler import _build_custom_strategy_dataframe
        strategy_key = meta['id']
        # auto_run=True：区间无任何可复用回测时自动跑一次，避免直接归 0
        df, _total, _err = _build_custom_strategy_dataframe(
            strategy_key, start_date, end_date, holding_days, '000300',
            auto_run=True)
        if df is None or len(df) == 0:
            return pd.DataFrame(columns=['date', 'code', 'rate'])
        rate_col = f'rate_{holding_days}'
        if rate_col not in df.columns:
            return pd.DataFrame(columns=['date', 'code', 'rate'])
        out = df[['date', 'code', rate_col]].rename(columns={rate_col: 'rate'}).copy()
        out['date'] = pd.to_datetime(out['date']).dt.strftime('%Y-%m-%d')
        out = out.dropna(subset=['rate'])
        return out.reset_index(drop=True)

    @staticmethod
    def _fuse_strategy_signals(strategy_dfs, signal_factors, fusion_mode, vote_threshold):
        """融合多策略信号，返回 DataFrame(date, code, rate)。"""
        def _k(sf):
            return sf['meta']['id'] if sf['meta'].get('is_custom') else sf['meta']['table']
        if len(signal_factors) == 1:
            return strategy_dfs.get(_k(signal_factors[0]),
                                    pd.DataFrame(columns=['date', 'code', 'rate']))

        # 合并所有策略
        dfs = []
        keys = []
        for sf in signal_factors:
            key = _k(sf)
            if key in keys:
                continue
            keys.append(key)
            df = strategy_dfs.get(key)
            if df is not None and len(df) > 0:
                dfs.append(df[['date', 'code', 'rate']].copy())
        if not dfs:
            return pd.DataFrame(columns=['date', 'code', 'rate'])

        combined = pd.concat(dfs, ignore_index=True)

        if fusion_mode == 'and':
            counts = combined.groupby(['date', 'code']).size().reset_index(name='cnt')
            valid = counts[counts['cnt'] >= len(keys)][['date', 'code']]
            avg_rate = combined.groupby(['date', 'code'])['rate'].mean().reset_index()
            return valid.merge(avg_rate, on=['date', 'code'], how='inner')

        elif fusion_mode == 'vote':
            threshold = max(2, min(vote_threshold, len(keys)))
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


# ── Phase 7.1: 保存/加载因子配置 ──────────────────────────────────────

_config_table_ready = False


def _ensure_factor_config_table():
    """确保 cn_stock_factor_lab_config 表存在。"""
    global _config_table_ready
    if _config_table_ready:
        return
    if not mdb.checkTableIsExist("cn_stock_factor_lab_config"):
        mdb.executeSql("""
            CREATE TABLE IF NOT EXISTS `cn_stock_factor_lab_config` (
              `id` INT AUTO_INCREMENT PRIMARY KEY,
              `name` VARCHAR(200) NOT NULL COMMENT '配置名称',
              `description` VARCHAR(500) DEFAULT '' COMMENT '简要描述',
              `factors` JSON NOT NULL COMMENT '因子配置列表',
              `fusion_mode` VARCHAR(20) NOT NULL DEFAULT 'and',
              `vote_threshold` INT DEFAULT 2,
              `holding_days` INT DEFAULT 10,
              `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
              `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              INDEX `idx_name` (`name`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        logger.info("[factor_lab] 已创建表 cn_stock_factor_lab_config")
    _config_table_ready = True


class FactorLabSaveHandler(webBase.BaseHandler):
    """POST /quantia/api/factor_lab/save

    保存因子配置方案到数据库。
    Body: { name, description?, factors, fusion_mode, vote_threshold?, holding_days?, id? }
    如果传入 id，则更新；否则新建。
    """

    def post(self):
        try:
            self._handle()
        except Exception:
            logger.error("因子配置保存异常", exc_info=True)
            _write_error(self, '服务器内部错误', 500)

    def _handle(self):
        try:
            body = json.loads(self.request.body)
        except (json.JSONDecodeError, TypeError):
            _write_error(self, '请求体必须为 JSON')
            return

        name = str(body.get('name', '')).strip()
        if not name or len(name) > 200:
            _write_error(self, '名称不能为空且不超过 200 字符')
            return

        factors = body.get('factors', [])
        if not isinstance(factors, list) or len(factors) == 0:
            _write_error(self, '至少需要 1 个因子')
            return
        if len(factors) > 15:
            _write_error(self, '最多支持 15 个因子')
            return

        fusion_mode = body.get('fusion_mode', 'and')
        if fusion_mode not in ('and', 'vote', 'score'):
            _write_error(self, "fusion_mode 必须为 and / vote / score")
            return

        description = str(body.get('description', '')).strip()[:500]
        vote_threshold = max(2, min(int(body.get('vote_threshold', 2)), 15))
        holding_days = max(1, min(int(body.get('holding_days', 10)), RATE_FIELDS_COUNT))
        config_id = body.get('id')

        _ensure_factor_config_table()

        factors_json = json.dumps(factors, ensure_ascii=False)

        if config_id:
            # 更新
            config_id = int(config_id)
            mdb.executeSql("""
                UPDATE `cn_stock_factor_lab_config`
                SET `name` = %s, `description` = %s, `factors` = %s,
                    `fusion_mode` = %s, `vote_threshold` = %s, `holding_days` = %s
                WHERE `id` = %s
            """, (name, description, factors_json,
                  fusion_mode, vote_threshold, holding_days, config_id))
            _write_json(self, {'id': config_id, 'message': '已更新'})
        else:
            # 新建
            mdb.executeSql("""
                INSERT INTO `cn_stock_factor_lab_config`
                    (`name`, `description`, `factors`, `fusion_mode`, `vote_threshold`, `holding_days`)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (name, description, factors_json,
                  fusion_mode, vote_threshold, holding_days))
            # 获取新 ID
            rows = mdb.executeSqlFetch("SELECT LAST_INSERT_ID()")
            new_id = int(rows[0][0]) if rows else None
            _write_json(self, {'id': new_id, 'message': '已保存'})


class FactorLabConfigsHandler(webBase.BaseHandler):
    """GET /quantia/api/factor_lab/my_configs

    返回用户保存的因子配置列表。
    """

    def get(self):
        try:
            _ensure_factor_config_table()
            rows = mdb.executeSqlFetch("""
                SELECT `id`, `name`, `description`, `factors`, `fusion_mode`,
                       `vote_threshold`, `holding_days`, `created_at`, `updated_at`
                FROM `cn_stock_factor_lab_config`
                ORDER BY `updated_at` DESC
                LIMIT 50
            """)
            configs = []
            for row in (rows or []):
                factors_data = row[3]
                if isinstance(factors_data, str):
                    factors_data = json.loads(factors_data)
                configs.append({
                    'id': row[0],
                    'name': row[1],
                    'description': row[2] or '',
                    'factors': factors_data,
                    'fusion_mode': row[4],
                    'vote_threshold': row[5],
                    'holding_days': row[6],
                    'created_at': row[7].strftime('%Y-%m-%d %H:%M') if row[7] else '',
                    'updated_at': row[8].strftime('%Y-%m-%d %H:%M') if row[8] else '',
                })
            _write_json(self, {'configs': configs})
        except Exception:
            logger.error("加载因子配置列表异常", exc_info=True)
            _write_error(self, '服务器内部错误', 500)


class FactorLabDeleteConfigHandler(webBase.BaseHandler):
    r"""DELETE /quantia/api/factor_lab/configs/(\d+)

    删除指定 ID 的因子配置。
    """

    def delete(self, config_id):
        try:
            config_id = int(config_id)
            _ensure_factor_config_table()
            mdb.executeSql(
                "DELETE FROM `cn_stock_factor_lab_config` WHERE `id` = %s",
                (config_id,))
            _write_json(self, {'message': '已删除', 'id': config_id})
        except Exception:
            logger.error("删除因子配置异常", exc_info=True)
            _write_error(self, '服务器内部错误', 500)


# ── Phase 7.2: 导出 Python 策略代码 ──────────────────────────────────

class FactorLabExportCodeHandler(webBase.BaseHandler):
    """POST /quantia/api/factor_lab/export_code

    将因子组合导出为可运行的 Backtrader 策略代码。
    Body: { factors, fusion_mode, vote_threshold?, holding_days? }
    """

    def post(self):
        try:
            self._handle()
        except Exception:
            logger.error("因子代码导出异常", exc_info=True)
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

        fusion_mode = body.get('fusion_mode', 'and')
        holding_days = max(1, min(int(body.get('holding_days', 10)), RATE_FIELDS_COUNT))
        vote_threshold = int(body.get('vote_threshold', 2))

        # 构建因子描述
        factor_lines = []
        signal_ids = []
        filter_conditions = []

        for fc in factors_raw:
            if not fc.get('enabled', True):
                continue
            fid = fc.get('id', '')
            meta = _FACTOR_MAP.get(fid)
            if not meta:
                continue

            if meta['type'] == 'signal':
                signal_ids.append(fid)
                factor_lines.append(f"    # 策略信号: {meta['name']} (权重 {fc.get('weight', 10)}%)")
            else:
                op = fc.get('operator', meta.get('default_operator', '>'))
                val = fc.get('value', meta.get('default_value', 0))
                col = meta.get('column', fid)
                if op == 'between' and isinstance(val, (list, tuple)):
                    cond = f"{col} BETWEEN {val[0]} AND {val[1]}"
                else:
                    cond = f"{col} {op} {val}"
                filter_conditions.append((meta['name'], col, op, val))
                factor_lines.append(f"    # 过滤因子: {meta['name']} → {cond} (权重 {fc.get('weight', 10)}%)")

        # 生成 Python 代码
        code = self._generate_code(
            signal_ids, filter_conditions, fusion_mode,
            vote_threshold, holding_days, factor_lines)

        _write_json(self, {
            'code': code,
            'filename': f'factor_lab_{fusion_mode}_{holding_days}d.py',
        })

    @staticmethod
    def _generate_code(signal_ids, filter_conditions, fusion_mode,
                       vote_threshold, holding_days, factor_lines):
        """生成 Backtrader 策略 Python 代码模板。"""
        signals_str = ', '.join(f"'{s}'" for s in signal_ids)
        fusion_desc = {'and': '全部满足(AND)', 'vote': f'投票(≥{vote_threshold})',
                       'score': '加权评分(Score)'}

        # 过滤条件代码
        filter_code_lines = []
        for name, col, op, val in filter_conditions:
            if op == 'between' and isinstance(val, (list, tuple)):
                filter_code_lines.append(
                    f"            ('{col}', 'between', [{val[0]}, {val[1]}]),  # {name}")
            else:
                filter_code_lines.append(
                    f"            ('{col}', '{op}', {val}),  # {name}")

        filters_str = '\n'.join(filter_code_lines) if filter_code_lines else \
            "            # 无额外过滤条件"

        code = f'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
因子实验室导出策略
====================
融合模式: {fusion_desc.get(fusion_mode, fusion_mode)}
持仓天数: {holding_days}
策略信号: {signals_str}
生成时间: {{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}}

因子配置:
{chr(10).join(factor_lines)}
"""

import datetime
import numpy as np
import pandas as pd
import backtrader as bt


class FactorLabStrategy(bt.Strategy):
    """因子实验室多因子选股策略"""

    params = (
        ('holding_days', {holding_days}),
        ('fusion_mode', '{fusion_mode}'),
        ('vote_threshold', {vote_threshold}),
        ('signal_strategies', [{signals_str}]),
        ('filter_conditions', [
{filters_str}
        ]),
        ('max_positions', 10),
        ('position_pct', 0.1),  # 每只股票仓位占比
    )

    def __init__(self):
        self.holding_counter = {{}}  # code -> 持仓天数计数
        self.order_dict = {{}}

    def next(self):
        today = self.datas[0].datetime.date(0)

        # === 1. 获取策略信号 ===
        signals = self._get_strategy_signals(today)

        # === 2. 融合信号 ===
        candidates = self._fuse_signals(signals)

        # === 3. 应用过滤因子 ===
        filtered = self._apply_filters(candidates, today)

        # === 4. 持仓管理 ===
        self._manage_positions(filtered, today)

    def _get_strategy_signals(self, today):
        """从策略表获取当日选中的股票代码。

        TODO: 连接数据库或缓存读取策略选股结果
        """
        signals = {{}}  # strategy_id -> set(codes)
        for strategy_id in self.p.signal_strategies:
            # 实际使用时从 DB 或 cache 加载:
            # sql = f"SELECT code FROM cn_stock_strategy_{{strategy_id}} WHERE date = %s"
            signals[strategy_id] = set()
        return signals

    def _fuse_signals(self, signals):
        """根据融合模式合并多策略信号。"""
        if not signals:
            return set()

        all_codes = set()
        code_counts = {{}}

        for strategy_id, codes in signals.items():
            all_codes.update(codes)
            for code in codes:
                code_counts[code] = code_counts.get(code, 0) + 1

        if self.p.fusion_mode == 'and':
            n = len(self.p.signal_strategies)
            return {{c for c, cnt in code_counts.items() if cnt >= n}}
        elif self.p.fusion_mode == 'vote':
            return {{c for c, cnt in code_counts.items()
                    if cnt >= self.p.vote_threshold}}
        else:  # score
            return all_codes

    def _apply_filters(self, candidates, today):
        """应用过滤条件筛选候选股票。

        TODO: 从 indicators/selection/fund_flow 表读取数据
        """
        filtered = list(candidates)
        for col, op, value in self.p.filter_conditions:
            # 实际使用时查询对应表:
            # df = pd.read_sql(sql, params=(today,))
            # 应用条件过滤
            pass
        return filtered[:self.p.max_positions]

    def _manage_positions(self, candidates, today):
        """持仓管理: 到期平仓 + 新建仓位。"""
        # 平仓: 持仓到期
        for code in list(self.holding_counter.keys()):
            self.holding_counter[code] += 1
            if self.holding_counter[code] >= self.p.holding_days:
                # self.close(data_for_code)
                del self.holding_counter[code]

        # 开仓: 买入新候选
        available_slots = self.p.max_positions - len(self.holding_counter)
        for code in candidates[:available_slots]:
            if code not in self.holding_counter:
                # self.buy(data_for_code, size=...)
                self.holding_counter[code] = 0


if __name__ == '__main__':
    cerebro = bt.Cerebro()
    cerebro.addstrategy(FactorLabStrategy)
    cerebro.broker.setcash(1000000)
    cerebro.broker.setcommission(commission=0.001)
    # cerebro.adddata(...)  # 添加数据源
    results = cerebro.run()
    print(f"最终资产: {{cerebro.broker.getvalue():.2f}}")
'''
        return code
