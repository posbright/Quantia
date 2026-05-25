#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GPT综合选股策略

基于 ChatGP选股策略文档.md v3.0 中定义的五层过滤标准：
1. 财务安全过滤 - 资产负债率 < 60%, 每股经营现金流 > 0, 流动比率 >= 1.0, 速动比率 >= 0.7
2. 盈利能力筛选 - ROE >= 15%, 毛利率 >= 25%, 净利率 >= 8%, ROA >= 4%
3. 成长质量筛选 - 营收3年CAGR > 8%, 净利润3年CAGR > 8%, 扣非净利润增长率 > 0%
4. 估值约束 - PE(TTM) 0 < PE <= 50, PB(MRQ) <= 10

这个策略使用 cn_stock_selection 表中的财务数据进行筛选。
"""

import logging
import math
import pandas as pd

__author__ = 'Quantia'
__date__ = '2026/02/14'


# ========== 默认参数值 ==========
_DEFAULT_PARAMS = {
    # 第一层：财务安全
    "debt_asset_ratio_max": 60,
    "per_netcash_operate_min": 0,
    "current_ratio_min": 1.0,
    "speed_ratio_min": 0.7,
    # 第二层：盈利能力
    "roe_weight_min": 10,
    "sale_gpr_min": 15,
    "sale_npr_min": 5,
    "jroa_min": 3,
    # 第三层：成长质量
    "income_growthrate_3y_min": 3,
    "netprofit_growthrate_3y_min": 3,
    "deduct_netprofit_growthrate_min": 0,
    # 第五层：估值约束
    "pe_min": 0,
    "pe_max": 50,
    "pbnewmrq_max": 10,
}


def _load_params():
    """加载用户配置的参数，失败时使用默认值"""
    try:
        from quantia.web.strategyParamsHandler import get_gpt_filter_values
        return get_gpt_filter_values()
    except Exception as e:
        logging.debug(f"加载策略参数失败，使用默认值: {e}")
        return _DEFAULT_PARAMS.copy()


def _get_roe_season_factor():
    """根据季报披露周期返回 ROE 年化因子。

    东方财富 roe_weight 字段在季报披露后更新为单报告期累计 ROE，
    而非年化值。5~8月为 Q1 报表（约为全年 1/4），需对阈值做等比缩放。
    """
    import datetime
    month = datetime.date.today().month
    if 5 <= month <= 8:
        return 4.0
    elif 9 <= month <= 10:
        return 2.0
    elif month >= 11:
        return 4.0 / 3.0
    else:
        return 1.0


def check_gpt_value(code_name, data, date=None, threshold=60):
    """
    GPT综合选股策略检查函数

    由于这是一个基本面策略，需要使用 cn_stock_selection 表的数据，
    而不是历史K线数据。此函数用于兼容现有的策略框架。

    实际筛选逻辑在 selection_data_job 中执行。

    Args:
        code_name: (date, code, name) 元组
        data: K线历史数据 DataFrame
        date: 日期
        threshold: 最小数据长度要求

    Returns:
        bool: 是否满足条件
    """
    # 基本面策略无法使用K线数据判断
    # 这里返回False，实际筛选通过专门的 job 完成
    return False


def check_gpt_value_from_selection(stock_row, params=None):
    """
    从 cn_stock_selection 数据中检查是否满足GPT综合选股条件

    Args:
        stock_row: pd.Series, cn_stock_selection 表中的一行数据
        params: dict, 筛选参数。为None时自动从数据库加载用户配置

    Returns:
        bool: 是否满足所有条件
    """
    if params is None:
        params = _load_params()

    def _is_valid_number(val):
        """检查值是否为有效的有限数值（排除None、NaN、inf、-inf）"""
        return val is not None and not pd.isna(val) and math.isfinite(float(val))

    try:
        # ===== 第一层：财务安全过滤 =====
        # 所有字段统一逻辑：数据缺失时跳过该项检查（不因缺数据而淘汰）
        debt_ratio = stock_row.get('debt_asset_ratio', None)
        if _is_valid_number(debt_ratio) and debt_ratio >= params["debt_asset_ratio_max"]:
            return False

        cashflow = stock_row.get('per_netcash_operate', None)
        if _is_valid_number(cashflow) and cashflow <= params["per_netcash_operate_min"]:
            return False

        current_r = stock_row.get('current_ratio', None)
        if _is_valid_number(current_r) and current_r < params.get("current_ratio_min", 1.0):
            return False

        speed_r = stock_row.get('speed_ratio', None)
        if _is_valid_number(speed_r) and speed_r < params.get("speed_ratio_min", 0.7):
            return False

        # ===== 第二层：盈利能力筛选 =====
        roe = stock_row.get('roe_weight', None)
        if _is_valid_number(roe):
            # 根据季报周期调整阈值：Q1报表后 roe_weight 为单季度值
            roe_min = params["roe_weight_min"] / _get_roe_season_factor()
            if roe < roe_min:
                return False

        gpr = stock_row.get('sale_gpr', None)
        if _is_valid_number(gpr) and gpr < params["sale_gpr_min"]:
            return False

        npr = stock_row.get('sale_npr', None)
        if _is_valid_number(npr) and npr < params["sale_npr_min"]:
            return False

        roa = stock_row.get('jroa', None)
        if _is_valid_number(roa):
            roa_min = params.get("jroa_min", 3) / _get_roe_season_factor()
            if roa < roa_min:
                return False

        # ===== 第三层：成长质量筛选 =====
        revenue_growth = stock_row.get('income_growthrate_3y', None)
        if _is_valid_number(revenue_growth) and revenue_growth <= params["income_growthrate_3y_min"]:
            return False

        profit_growth = stock_row.get('netprofit_growthrate_3y', None)
        if _is_valid_number(profit_growth) and profit_growth <= params["netprofit_growthrate_3y_min"]:
            return False

        deduct_growth = stock_row.get('deduct_netprofit_growthrate', None)
        if _is_valid_number(deduct_growth) and deduct_growth <= params.get("deduct_netprofit_growthrate_min", 0):
            return False

        # ===== 第五层：估值约束 =====
        pe = stock_row.get('pe9', None)
        if _is_valid_number(pe) and (pe <= params["pe_min"] or pe > params["pe_max"]):
            return False

        pb = stock_row.get('pbnewmrq', None)
        if _is_valid_number(pb) and pb > params.get("pbnewmrq_max", 10):
            return False

        # ===== 最低数据质量要求 =====
        # 至少要有 3 个关键财务指标有效，防止全空数据通过筛选
        _critical_fields = [
            'roe_weight', 'pe9', 'sale_gpr', 'sale_npr',
            'debt_asset_ratio', 'income_growthrate_3y',
        ]
        _valid_count = sum(
            1 for f in _critical_fields
            if _is_valid_number(stock_row.get(f, None))
        )
        if _valid_count < 3:
            return False

        # 通过所有筛选
        return True

    except Exception:
        return False


def filter_gpt_value_stocks(selection_data):
    """
    批量筛选满足GPT综合选股条件的股票

    使用数据库中保存的用户自定义参数进行筛选。

    Args:
        selection_data: pd.DataFrame, cn_stock_selection 表的数据

    Returns:
        pd.DataFrame: 满足条件的股票
    """
    if selection_data is None or len(selection_data) == 0:
        return pd.DataFrame()

    # 加载一次参数，供所有行复用
    params = _load_params()
    mask = selection_data.apply(lambda row: check_gpt_value_from_selection(row, params), axis=1)
    filtered = selection_data[mask].copy()

    if len(filtered) == 0:
        return filtered

    # 计算综合评分和提取指标值
    scores_and_indicators = filtered.apply(
        lambda row: compute_gpt_score(row, params), axis=1, result_type='expand'
    )
    for col in scores_and_indicators.columns:
        filtered[col] = scores_and_indicators[col].values

    return filtered


# GPT综合选股使用的指标字段列表（与 _DEFAULT_PARAMS 中的筛选条件对应）
GPT_INDICATOR_FIELDS = [
    'gpt_score',           # 综合评分
    'debt_asset_ratio',    # 资产负债率
    'per_netcash_operate', # 每股经营现金流
    'current_ratio',       # 流动比率
    'speed_ratio',         # 速动比率
    'roe_weight',          # ROE
    'sale_gpr',            # 毛利率
    'sale_npr',            # 净利率
    'jroa',                # ROA
    'income_growthrate_3y',       # 营收3年CAGR
    'netprofit_growthrate_3y',    # 净利润3年CAGR
    'deduct_netprofit_growthrate', # 扣非净利润增长率
    'pe9',                 # 市盈率TTM
    'pbnewmrq',            # 市净率MRQ
]


def compute_gpt_score(stock_row, params=None):
    """
    计算GPT综合选股评分（0~100分）

    评分逻辑：各指标按超过阈值的程度加分，满分100。
    - 财务安全（20分）：资产负债率越低、现金流越高、流动/速动比率越高越好
    - 盈利能力（30分）：ROE、毛利率、净利率、ROA 越高越好
    - 成长质量（30分）：营收/利润增速越高越好
    - 估值优势（20分）：PE/PB 越低越好

    Args:
        stock_row: pd.Series
        params: dict

    Returns:
        dict: {'gpt_score': float, 指标字段: 实际值, ...}
    """
    if params is None:
        params = _load_params()

    import math

    def _val(key):
        v = stock_row.get(key, None)
        if v is not None and not pd.isna(v) and math.isfinite(float(v)):
            return float(v)
        return None

    result = {}
    for field in GPT_INDICATOR_FIELDS:
        if field == 'gpt_score':
            continue
        result[field] = _val(field)

    score = 0.0

    # --- 财务安全 20分 ---
    debt = _val('debt_asset_ratio')
    if debt is not None:
        # 阈值60, 值越低越好, 0→满分5, 60→0分
        score += max(0, min(5, 5 * (params['debt_asset_ratio_max'] - debt) / params['debt_asset_ratio_max']))

    cash = _val('per_netcash_operate')
    if cash is not None and cash > 0:
        # 现金流>0 即得基础分, 越高加分
        score += min(5, 2 + cash * 0.5)

    cur_r = _val('current_ratio')
    if cur_r is not None:
        score += max(0, min(5, 5 * min(cur_r / 2.0, 1)))

    spd_r = _val('speed_ratio')
    if spd_r is not None:
        score += max(0, min(5, 5 * min(spd_r / 1.5, 1)))

    # --- 盈利能力 30分 ---
    roe = _val('roe_weight')
    if roe is not None:
        score += max(0, min(10, 10 * min(roe / 30, 1)))

    gpr = _val('sale_gpr')
    if gpr is not None:
        score += max(0, min(8, 8 * min(gpr / 50, 1)))

    npr = _val('sale_npr')
    if npr is not None:
        score += max(0, min(7, 7 * min(npr / 20, 1)))

    roa = _val('jroa')
    if roa is not None:
        score += max(0, min(5, 5 * min(roa / 10, 1)))

    # --- 成长质量 30分 ---
    rev_g = _val('income_growthrate_3y')
    if rev_g is not None:
        score += max(0, min(10, 10 * min(rev_g / 30, 1)))

    pft_g = _val('netprofit_growthrate_3y')
    if pft_g is not None:
        score += max(0, min(10, 10 * min(pft_g / 30, 1)))

    ded_g = _val('deduct_netprofit_growthrate')
    if ded_g is not None:
        score += max(0, min(10, 10 * min(ded_g / 30, 1)))

    # --- 估值优势 20分 ---
    pe = _val('pe9')
    if pe is not None and pe > 0:
        # PE 越低越好, 10→满分, 50→0分
        score += max(0, min(10, 10 * (params['pe_max'] - pe) / params['pe_max']))

    pb = _val('pbnewmrq')
    if pb is not None and pb > 0:
        score += max(0, min(10, 10 * (params['pbnewmrq_max'] - pb) / params['pbnewmrq_max']))

    result['gpt_score'] = round(score, 1)
    return result
