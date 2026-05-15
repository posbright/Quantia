#!/usr/local/bin/python
# -*- coding: utf-8 -*-

import pandas as pd

__author__ = 'Quantia'
__date__ = '2026/02/14'

import quantia.lib.envconfig as _cfg
# 总市值（模拟资金）
BALANCE = _cfg.get_int('QUANTIA_TURTLE_BALANCE', 200000)

# 海龟交易法则
# 最后一个交易日收市价为指定区间内最高价
# 1.当日收盘价>=最近60日最高收盘价
def check_enter(code_name, data, date=None, threshold=60):
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
    if len(data.index) < threshold:
        return False

    data = data.tail(n=threshold)

    max_price = 0
    for _close in data['close'].values:
        if _close > max_price:
            max_price = _close

    last_close = data.iloc[-1]['close']

    if last_close >= max_price:
        p_change = data.iloc[-1]['p_change'] if 'p_change' in data.columns else 0.0
        # 20日最低价（经典海龟 System 2 退出信号参考线）
        low_20d = float(data.tail(20)['low'].min()) if 'low' in data.columns else float(data.tail(20)['close'].min())
        return {
            'p_change': round(float(p_change), 2),
            'close': round(float(last_close), 2),
            'high_60d': round(float(max_price), 2),
            'low_20d': round(low_20d, 2),
        }

    return False
