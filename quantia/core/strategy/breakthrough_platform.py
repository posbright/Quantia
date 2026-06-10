#!/usr/local/bin/python
# -*- coding: utf-8 -*-

from datetime import datetime
import numpy as np
import pandas as pd
import talib as tl
from quantia.core.strategy import enter

__author__ = 'Quantia'
__date__ = '2026/02/14'


# 平台突破策略（与策略名称严格对应：必须是"近期"从横盘平台向上突破，且当前仍站稳平台之上）
#
# 选股条件：
# 1. 真实平台（C）：突破日之前需有不少于 min_platform_days 个交易日收盘价贴近 MA60
#    （偏离 -5%~20%），构成横盘整理平台；避免突破日恰为窗口首日时平台校验被"空跑"绕过。
# 2. 近期突破（A）：突破日（开盘价<MA60<=收盘价 且放量上涨）必须发生在信号日当天或最近
#    recent_days 个交易日内，且取最近一次突破；避免把数月前的一次突破在之后约 60 个交易日里
#    持续误判为买入信号。
# 3. 仍站稳平台（B）：突破日至信号日之间收盘价持续 >= MA60，未跌回均线下方；
#    过滤已经反转、跌破均线的失效突破（典型误选：3 个月前突破、如今已跌破 MA60 仍被选中）。
def check(code_name, data, date=None, threshold=60, recent_days=3, min_platform_days=10):
    origin_data = data
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
    if len(data.index) < threshold:
        return False

    data.loc[:, 'ma60'] = tl.MA(data['close'].values, timeperiod=60)
    data['ma60'] = data['ma60'].fillna(0.0)

    data = data.tail(n=threshold)

    # A. 仅在最近 recent_days 个交易日内寻找突破日，并取最近的一次突破。
    recent = data.tail(n=max(1, recent_days))
    breakthrough_row = None
    for _close, _open, _date, _ma60 in zip(
            recent['close'].values[::-1], recent['open'].values[::-1],
            recent['date'].values[::-1], recent['ma60'].values[::-1]):
        if _ma60 > 0 and _open < _ma60 <= _close:
            if enter.check_volume(code_name, origin_data, date=pd.Timestamp(_date), threshold=threshold):
                breakthrough_row = _date
                break

    if breakthrough_row is None:
        return False

    # C. 突破日之前需构成真实平台：样本足够多，且全部贴近 MA60。
    data_front = data.loc[(data['date'] < breakthrough_row) & (data['ma60'] > 0)]
    if len(data_front) < min_platform_days:
        return False
    for _close, _ma60 in zip(data_front['close'].values, data_front['ma60'].values):
        # 收盘价与60日均线偏离在-5%~20%之间
        deviation = (_close - _ma60) / _ma60
        if not (-0.05 < deviation < 0.2):
            return False

    # B. 突破日至信号日收盘价需持续站稳 MA60 之上，未跌回均线下方。
    data_after = data.loc[data['date'] >= breakthrough_row]
    for _close, _ma60 in zip(data_after['close'].values, data_after['ma60'].values):
        if _ma60 <= 0 or _close < _ma60:
            return False

    p_change = data.iloc[-1]['p_change'] if 'p_change' in data.columns else 0.0
    last_close = data.iloc[-1]['close']
    last_ma60 = data.iloc[-1]['ma60']
    last_deviation = (last_close - last_ma60) / last_ma60 if last_ma60 != 0 else 0
    return {
        'p_change': round(float(p_change), 2),
        'close': round(float(last_close), 2),
        'ma60': round(float(last_ma60), 2),
        'deviation': round(float(last_deviation * 100), 2),
    }
