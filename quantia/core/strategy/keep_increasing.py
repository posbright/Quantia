#!/usr/local/bin/python
# -*- coding: utf-8 -*-

import numpy as np
import pandas as pd
import talib as tl

__author__ = 'Quantia'
__date__ = '2026/02/14'


# 均线多头排列（可调优版本）
# 中长期均线自上而下多头排列，但对短期均线噪声与长期均线滞后做了可配置放宽：
#   A. 短期容差（include_ma5）：默认不强制 MA5>MA10，仅要求 MA5>MA20，
#      容忍上升通道中 1~3 日的正常小回调（MA5 短暂跌破 MA10），避免漏掉上升初/中段。
#   B. 长期趋势确认（ma60_mode）：默认不强制 MA30>MA60（该条件在回调后因 MA60 高悬而严重滞后），
#      改用「MA60 斜率向上」确认长期趋势已转上行，使上升初期即可入选。
#   C. 以上行为全部可通过参数调节（include_ma5 / ma60_mode / ma60_slope_window），
#      并可经 UI/数据库（cn_strategy_params）真正接入每日选股任务。
# 统计多头排列从最新交易日向前连续出现的天数 bull_days，返回 dict 供结果表展示。
_MA_PERIODS = (5, 10, 20, 30, 60)


def check(code_name, data, date=None, threshold=60,
          include_ma5=0, ma60_mode='rising', ma60_slope_window=5):
    """检测均线多头排列。

    参数
    ----
    threshold: 分析所需最少历史交易日数（≥60 以计算 MA60）。
    include_ma5: 是否把 MA5>MA10 纳入严格多头链。
        - 真值（1/True）：沿用旧逻辑，强制 MA5>MA10（短期噪声敏感）。
        - 假值（0/False，默认）：放宽为 MA5>MA20，容忍短期回调。
    ma60_mode: MA30 与 MA60 的长期关系判定方式。
        - 'strict'：严格要求 MA30>MA60（旧逻辑，入场滞后）。
        - 'rising'（默认）：用 MA60 斜率向上替代，上升初期即可入选。
        - 'either'：MA30>MA60 或 MA60 斜率向上，任一满足即可。
    ma60_slope_window: 计算 MA60 斜率向上的回看根数。
    """
    if date is None:
        end_date = code_name[0]
    else:
        end_date = date.strftime("%Y-%m-%d")
    if end_date is not None:
        if not pd.api.types.is_datetime64_any_dtype(data['date']):
            data = data.copy()
            data['date'] = pd.to_datetime(data['date'])
        end_date = pd.Timestamp(end_date)
        mask = (data['date'] <= end_date)
        data = data.loc[mask].copy()
    # MA60 至少需要 60 根 K 线
    if len(data.index) < max(threshold, 60):
        return False

    # 参数归一化（UI/DB 传入可能是字符串或 0/1）
    include_ma5 = bool(include_ma5) and str(include_ma5).lower() not in ('0', 'false', '')
    ma60_mode = str(ma60_mode).lower() if ma60_mode is not None else 'rising'
    if ma60_mode not in ('strict', 'rising', 'either'):
        ma60_mode = 'rising'
    try:
        ma60_slope_window = max(1, int(ma60_slope_window))
    except (TypeError, ValueError):
        ma60_slope_window = 5

    data = data.copy()
    for period in _MA_PERIODS:
        ma = tl.MA(data['close'].values, timeperiod=period)
        data[f'ma{period}'] = pd.Series(ma, index=data.index).replace([np.inf, -np.inf], np.nan)

    ma5 = data['ma5'].values
    ma10 = data['ma10'].values
    ma20 = data['ma20'].values
    ma30 = data['ma30'].values
    ma60 = data['ma60'].values

    finite = (
        np.isfinite(ma5) & np.isfinite(ma10) & np.isfinite(ma20) &
        np.isfinite(ma30) & np.isfinite(ma60)
    )

    # A. 短期条件：默认放宽为 MA5>MA20（容忍 MA5 短暂跌破 MA10 的小回调）
    if include_ma5:
        short_ok = ma5 > ma10
    else:
        short_ok = ma5 > ma20

    # B. 长期条件：默认用 MA60 斜率向上替代严格 MA30>MA60
    ma60_prev = np.full_like(ma60, np.nan)
    if ma60_slope_window < len(ma60):
        ma60_prev[ma60_slope_window:] = ma60[:-ma60_slope_window]
    ma60_rising = np.isfinite(ma60_prev) & (ma60 > ma60_prev)
    if ma60_mode == 'strict':
        long_ok = ma30 > ma60
    elif ma60_mode == 'either':
        long_ok = (ma30 > ma60) | ma60_rising
    else:  # 'rising'
        long_ok = ma60_rising

    # 多头排列（含中期严格链 MA10>MA20>MA30 + 短/长期可调条件）
    bull = (
        finite & short_ok & (ma10 > ma20) & (ma20 > ma30) &
        long_ok & (ma60 > 0)
    )

    # 最新交易日必须处于多头排列
    if not bool(bull[-1]):
        return False

    # 从最新交易日向前回溯，统计连续多头排列天数
    not_bull_idx = np.where(~bull)[0]
    if len(not_bull_idx) == 0:
        bull_days = int(len(bull))
    else:
        bull_days = int(len(bull) - 1 - not_bull_idx[-1])

    last = data.iloc[-1]
    p_change = last['p_change'] if 'p_change' in data.columns else 0.0
    return {
        'p_change': round(float(p_change), 2),
        'close': round(float(last['close']), 2),
        'bull_days': bull_days,
        'ma5': round(float(last['ma5']), 3),
        'ma10': round(float(last['ma10']), 3),
        'ma20': round(float(last['ma20']), 3),
        'ma30': round(float(last['ma30']), 3),
        'ma60': round(float(last['ma60']), 3),
    }
