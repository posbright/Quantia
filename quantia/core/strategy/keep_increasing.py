#!/usr/local/bin/python
# -*- coding: utf-8 -*-

import numpy as np
import pandas as pd
import talib as tl

__author__ = 'Quantia'
__date__ = '2026/02/14'


# 均线多头排列
# 1. 最新交易日 MA5 > MA10 > MA20 > MA30 > MA60 > 0（短中长期均线自上而下多头排列）
# 2. 统计该多头排列从最新交易日向前连续出现的天数 bull_days
# 返回 dict（含 bull_days 及各周期均线），供选股结果表展示并按多头天数升序排列
_MA_PERIODS = (5, 10, 20, 30, 60)


def check(code_name, data, date=None, threshold=60):
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

    data = data.copy()
    for period in _MA_PERIODS:
        ma = tl.MA(data['close'].values, timeperiod=period)
        data[f'ma{period}'] = pd.Series(ma, index=data.index).replace([np.inf, -np.inf], np.nan)

    ma5 = data['ma5'].values
    ma10 = data['ma10'].values
    ma20 = data['ma20'].values
    ma30 = data['ma30'].values
    ma60 = data['ma60'].values

    # 每个交易日是否构成多头排列：MA5 > MA10 > MA20 > MA30 > MA60 > 0
    finite = (
        np.isfinite(ma5) & np.isfinite(ma10) & np.isfinite(ma20) &
        np.isfinite(ma30) & np.isfinite(ma60)
    )
    bull = finite & (ma5 > ma10) & (ma10 > ma20) & (ma20 > ma30) & (ma30 > ma60) & (ma60 > 0)

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
