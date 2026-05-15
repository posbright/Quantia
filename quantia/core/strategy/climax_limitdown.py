#!/usr/local/bin/python
# -*- coding: utf-8 -*-


import numpy as np
import pandas as pd
import talib as tl

__author__ = 'Quantia'
__date__ = '2026/02/14'

# 放量跌停
# 1.跌>9.5%
# 2.成交额不低于2亿
# 3.成交量至少是5日平均成交量的4倍
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
    if len(data.index) < threshold:
        return False

    p_change = data.iloc[-1]['p_change']
    if p_change > -9.5:
        return False

    data.loc[:, 'vol_ma5'] = tl.MA(data['volume'].values, timeperiod=5)
    data['vol_ma5'] = data['vol_ma5'].fillna(0.0)

    data = data.tail(n=threshold + 1)
    if len(data.index) < threshold + 1:
        return False

    # 最后一天收盘价
    last_close = data.iloc[-1]['close']
    # 最后一天成交量
    last_vol = data.iloc[-1]['volume']

    amount = last_close * last_vol

    # 成交额不低于2亿
    if amount < 200000000:
        return False

    data = data.head(n=threshold)

    mean_vol = data.iloc[-1]['vol_ma5']

    if mean_vol <= 0:
        return False

    vol_ratio = last_vol / mean_vol
    if vol_ratio >= 4:
        return {
            'p_change': round(float(p_change), 2),
            'volume': int(last_vol),
            'vol_ma5': int(round(mean_vol)),
            'vol_ratio': round(float(vol_ratio), 2),
            'amount': round(float(amount), 2),
        }
    else:
        return False
