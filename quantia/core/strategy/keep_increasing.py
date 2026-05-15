#!/usr/local/bin/python
# -*- coding: utf-8 -*-

import numpy as np
import pandas as pd
import talib as tl

__author__ = 'Quantia'
__date__ = '2026/02/14'


# 持续上涨（MA30向上）
# 均线多头
# 1.30日前的30日均线<20日前的30日均线<10日前的30日均线<当日的30日均线
# 3.(当日的30日均线/30日前的30日均线)>1.2
def check(code_name, data, date=None, threshold=30):
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

    data.loc[:, 'ma30'] = tl.MA(data['close'].values, timeperiod=30)
    data['ma30'] = data['ma30'].replace([np.inf, -np.inf], np.nan)

    data = data.tail(n=threshold)

    step1 = round(threshold / 3)
    step2 = round(threshold * 2 / 3)

    ma30_start = data.iloc[0]['ma30']
    ma30_step1 = data.iloc[step1]['ma30']
    ma30_step2 = data.iloc[step2]['ma30']
    ma30_last = data.iloc[-1]['ma30']
    ma30_points = (ma30_start, ma30_step1, ma30_step2, ma30_last)
    if any(pd.isna(value) or not np.isfinite(value) for value in ma30_points) or ma30_start <= 0:
        return False

    if ma30_start < ma30_step1 < ma30_step2 < ma30_last and ma30_last > 1.2 * ma30_start:
        p_change = data.iloc[-1]['p_change'] if 'p_change' in data.columns else 0.0
        return {
            'p_change': round(float(p_change), 2),
            'close': round(float(data.iloc[-1]['close']), 2),
            'ma30': round(float(ma30_last), 2),
            'ma30_start': round(float(ma30_start), 2),
            'ma30_ratio': round(float(ma30_last / ma30_start), 2),
        }
    else:
        return False
