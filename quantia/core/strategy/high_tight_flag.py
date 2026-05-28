#!/usr/local/bin/python
# -*- coding: utf-8 -*-

import pandas as pd

__author__ = 'Quantia'
__date__ = '2026/02/14'


# 高而窄的旗形
# 1.必须至少上市交易60日
# 2.当日收盘价/之前24~10日的最低价>=1.9
# 3.之前24~10日必须连续两天涨幅大于等于9.5%
def check_high_tight(code_name, data, date=None, threshold=60, istop=False):
    # 龙虎榜上必须有机构
    if not istop:
        return False
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

    current_close = data.iloc[-1]['close']  # 保存当日收盘价
    data = data.tail(n=24)
    data = data.head(n=14)
    low = data['low'].values.min()
    if low == 0:
        return False
    ratio_increase = current_close / low  # 当日收盘价/区间最低价
    if ratio_increase < 1.9:
        return False

    # 连续两天涨幅大于等于10%
    previous_p_change = 0.0
    for _p_change in data['p_change'].values:
        # 单日跌幅超7%；高开低走7%；两日累计跌幅10%；两日高开低走累计10%
        if _p_change >= 9.5:
            if previous_p_change >= 9.5:
                last_p_change = data.iloc[-1]['p_change'] if 'p_change' in data.columns else 0.0
                return {
                    'p_change': round(float(last_p_change), 2),
                    'close': round(float(current_close), 2),
                    'period_low': round(float(low), 2),
                    'rise_ratio': round(float(ratio_increase), 2),
                }
            else:
                previous_p_change = _p_change
        else:
            previous_p_change = 0.0

    return False
