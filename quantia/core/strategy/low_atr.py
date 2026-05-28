#!/usr/local/bin/python
# -*- coding: utf-8 -*-

import pandas as pd

__author__ = 'Quantia'
__date__ = '2026/02/14'


# 低ATR成长
# 1.必须至少上市交易250日
# 2.最近10个交易日的最高收盘价必须比最近10个交易日的最低收盘价高1.1倍
def check_low_increase(code_name, data, date=None, ma_short=30, ma_long=250, threshold=10):
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
        data = data.loc[mask]
    if len(data.index) < ma_long:
        return False

    # data.loc[:, 'ma_short'] = tl.MA(data['close'].values, timeperiod=ma_short)
    # data['ma_short'].values[np.isnan(data['ma_short'].values)] = 0.0
    # data.loc[:, 'ma_long'] = tl.MA(data['close'].values, timeperiod=ma_long)
    # data['ma_long'].values[np.isnan(data['ma_long'].values)] = 0.0

    data = data.tail(n=threshold)
    inc_days = 0
    dec_days = 0
    days_count = len(data.index)
    if days_count < threshold:
        return False

    # 区间最低点
    lowest_row = 1000000
    # 区间最高点
    highest_row = 0

    total_change = 0.0
    for _close, _p_change in zip(data['close'].values, data['p_change'].values):
        if _p_change > 0:
            total_change += abs(_p_change)
            inc_days = inc_days + 1
        elif _p_change < 0:
            total_change += abs(_p_change)
            dec_days = dec_days + 1

        if _close > highest_row:
            highest_row = _close
        if _close < lowest_row:
            lowest_row = _close

    atr = total_change / days_count
    if atr > 10:
        return False

    ratio = (highest_row - lowest_row) / lowest_row if lowest_row != 0 else 0

    if ratio > 0.1:
        p_change = data.iloc[-1]['p_change'] if 'p_change' in data.columns else 0.0
        return {
            'p_change': round(float(p_change), 2),
            'close': round(float(data.iloc[-1]['close']), 2),
            'atr': round(float(atr), 2),
            'highest_close': round(float(highest_row), 2),
            'lowest_close': round(float(lowest_row), 2),
            'range_ratio': round(float(ratio * 100), 2),
        }

    return False
