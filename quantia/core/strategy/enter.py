#!/usr/local/bin/python
# -*- coding: utf-8 -*-

import numpy as np
import pandas as pd
import talib as tl


__author__ = 'Quantia'
__date__ = '2026/02/14'


# 放量上涨
# 1.当日比前一天上涨小于 min_change% 或收盘价小于开盘价
# 2.当日成交额不低于 min_turnover 亿
# 3.当日成交量/vol_ma_period 日平均成交量 >= vol_ratio
#
# 参数（可经 UI/数据库 cn_strategy_params 真正接入每日选股与验证中心）：
#   min_change     当日最低涨幅(%)，默认 2
#   vol_ma_period  计算平均成交量的天数，默认 5
#   vol_ratio      当日成交量需达到均量的倍数，默认 2
#   min_turnover   最低成交额(亿)，默认 2
#   threshold      分析所需最少历史交易日数，默认 60
def check_volume(code_name, data, date=None, threshold=60,
                 min_change=2, vol_ma_period=5, vol_ratio=2, min_turnover=2):
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
        min_change = float(min_change)
    except (TypeError, ValueError):
        min_change = 2.0
    try:
        vol_ma_period = max(1, int(vol_ma_period))
    except (TypeError, ValueError):
        vol_ma_period = 5
    try:
        vol_ratio_th = float(vol_ratio)
    except (TypeError, ValueError):
        vol_ratio_th = 2.0
    try:
        min_amount = float(min_turnover) * 100000000
    except (TypeError, ValueError):
        min_amount = 200000000

    p_change = data.iloc[-1]['p_change']
    if p_change < min_change or data.iloc[-1]['close'] < data.iloc[-1]['open']:
        return False

    data.loc[:, 'vol_ma5'] = tl.MA(data['volume'].values, timeperiod=vol_ma_period)
    data['vol_ma5'] = data['vol_ma5'].fillna(0.0)

    data = data.tail(n=threshold + 1)
    if len(data) < threshold + 1:
        return False

    # 最后一天收盘价
    last_close = data.iloc[-1]['close']
    # 最后一天成交量
    last_vol = data.iloc[-1]['volume']

    amount = last_close * last_vol

    # 成交额不低于 min_turnover 亿
    if amount < min_amount:
        return False

    data = data.head(n=threshold)

    mean_vol = data.iloc[-1]['vol_ma5']

    if mean_vol <= 0:
        return False

    vol_ratio = last_vol / mean_vol
    if vol_ratio >= vol_ratio_th:
        return {
            'p_change': round(p_change, 2),
            'volume': int(last_vol),
            'vol_ma5': int(round(mean_vol)),
            'vol_ratio': round(vol_ratio, 2),
            'amount': round(amount, 2),
        }
    else:
        return False
