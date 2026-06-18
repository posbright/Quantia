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
def check(code_name, data, date=None, threshold=60, recent_days=3, min_platform_days=10,
          ma_period=60, min_deviation=-5, max_deviation=20):
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

    # 参数归一化（UI/DB 传入可能是字符串）
    try:
        ma_period = max(1, int(ma_period))
    except (TypeError, ValueError):
        ma_period = 60
    try:
        dev_lo = float(min_deviation) / 100.0
    except (TypeError, ValueError):
        dev_lo = -0.05
    try:
        dev_hi = float(max_deviation) / 100.0
    except (TypeError, ValueError):
        dev_hi = 0.2

    data.loc[:, 'ma60'] = tl.MA(data['close'].values, timeperiod=ma_period)
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

    # C. 突破日之前需构成真实平台：取紧邻突破日的最近 min_platform_days 个交易日，
    #    要求其全部贴近 MA60（落在偏离带内），构成横盘整理平台。
    #    注意：只校验紧邻突破日的整理窗口，而非整个回溯窗口——整个回溯窗口（突破在
    #    最近 recent_days 日内时约 57 天）会把平台之前的拉升/回调也强行纳入偏离带，
    #    导致几乎无股票能通过（实测 2026-06-10 起全市场连续多个交易日 0 选中）。
    #    “站稳 MA60 之上”由下方 B 段保证，故放宽 C 不会重新引入“收盘价远低于 MA60”的误选。
    data_front = data.loc[(data['date'] < breakthrough_row) & (data['ma60'] > 0)]
    if len(data_front) < min_platform_days:
        return False
    platform = data_front.tail(n=min_platform_days)
    for _close, _ma60 in zip(platform['close'].values, platform['ma60'].values):
        # 收盘价与均线偏离在 [min_deviation, max_deviation] 之间
        deviation = (_close - _ma60) / _ma60
        if not (dev_lo < deviation < dev_hi):
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
