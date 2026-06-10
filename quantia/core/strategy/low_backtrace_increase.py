#!/usr/local/bin/python
# -*- coding: utf-8 -*-

import pandas as pd

__author__ = 'Quantia'
__date__ = '2026/02/14'


# 无大幅回撤
# 1.当日收盘价比 threshold 日前的收盘价的涨幅大于 min_increase_ratio
# 2.最近 threshold 日，无单日跌幅超 max_single_day_drop%、两日累计跌幅超 max_two_day_drop%
#
# 参数（可经 UI/数据库 cn_strategy_params 真正接入每日选股与验证中心）：
#   min_increase_ratio    期间收盘价最低涨幅比例，默认 0.6
#   max_single_day_drop   单日最大跌幅(%)，默认 -7
#   max_two_day_drop      两日累计最大跌幅(%)，默认 -10
#   threshold             分析窗口长度，默认 60
def check(code_name, data, date=None, threshold=60,
          min_increase_ratio=0.6, max_single_day_drop=-7, max_two_day_drop=-10):
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

    # 参数归一化（UI/DB 传入可能是字符串）
    try:
        min_increase_ratio = float(min_increase_ratio)
    except (TypeError, ValueError):
        min_increase_ratio = 0.6
    try:
        max_single_day_drop = float(max_single_day_drop)
    except (TypeError, ValueError):
        max_single_day_drop = -7.0
    try:
        max_two_day_drop = float(max_two_day_drop)
    except (TypeError, ValueError):
        max_two_day_drop = -10.0

    data = data.tail(n=threshold)

    first_close = data.iloc[0]['close']
    if first_close == 0:
        return False
    ratio_increase = (data.iloc[-1]['close'] - first_close) / first_close
    if ratio_increase < min_increase_ratio:
        return False

    # 允许有一次“洗盘”
    previous_p_change = 100.0
    previous_open = data.iloc[0]['open']  # 用首日开盘价初始化，避免-1000000导致首次迭代永远返回False
    max_single_drop = 0.0
    max_2day_drop = 0.0
    for _p_change, _close, _open in zip(data['p_change'].values, data['close'].values, data['open'].values):
        single_drop = min(float(_p_change), (_close - _open) / _open * 100 if _open != 0 else 0)
        two_day_drop = min(float(previous_p_change + _p_change), (_close - previous_open) / previous_open * 100 if previous_open != 0 else 0)
        max_single_drop = min(max_single_drop, single_drop)
        max_2day_drop = min(max_2day_drop, two_day_drop)
        # 单日跌幅超阈值；两日累计跌幅超阈值（含高开低走）
        if single_drop < max_single_day_drop or two_day_drop < max_two_day_drop:
            return False
        previous_p_change = _p_change
        previous_open = _open
    p_change = data.iloc[-1]['p_change'] if 'p_change' in data.columns else 0.0
    return {
        'p_change': round(float(p_change), 2),
        'close': round(float(data.iloc[-1]['close']), 2),
        'total_return': round(float(ratio_increase * 100), 2),
        'max_single_drop': round(float(max_single_drop), 2),
        'max_2day_drop': round(float(max_2day_drop), 2),
    }
