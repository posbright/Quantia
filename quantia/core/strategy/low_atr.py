#!/usr/local/bin/python
# -*- coding: utf-8 -*-

import pandas as pd

__author__ = 'Quantia'
__date__ = '2026/02/14'


# 低ATR成长
# 1.必须至少上市交易 min_listing_days 日
# 2.最近 analysis_days 个交易日的平均日波动 <= max_atr%
# 3.区间最高价/最低价 >= min_price_range
#
# 参数（可经 UI/数据库 cn_strategy_params 真正接入每日选股与验证中心）：
#   max_atr          期间平均每日绝对涨跌幅上限(%)，默认 10
#   min_price_range  最高/最低价比值下限，默认 1.1
#   analysis_days    近期分析窗口长度，默认 10
#   min_listing_days 最少上市交易天数，默认 250
# 兼容旧签名参数 ma_short/ma_long/threshold（threshold 作为 analysis_days 的兼容别名）。
def check_low_increase(code_name, data, date=None, ma_short=30, ma_long=250, threshold=10,
                       max_atr=10, min_price_range=1.1, analysis_days=None, min_listing_days=None):
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

    # 参数归一化（UI/DB 传入可能是字符串）；analysis_days 缺省回退到旧 threshold
    try:
        window = int(analysis_days) if analysis_days is not None else int(threshold)
    except (TypeError, ValueError):
        window = 10
    window = max(1, window)
    try:
        listing_days = int(min_listing_days) if min_listing_days is not None else int(ma_long)
    except (TypeError, ValueError):
        listing_days = 250
    try:
        max_atr = float(max_atr)
    except (TypeError, ValueError):
        max_atr = 10.0
    try:
        min_price_range = float(min_price_range)
    except (TypeError, ValueError):
        min_price_range = 1.1
    # 阈值=比值-1（默认 1.1->0.1）。round 消除浮点误差，保证默认与旧逻辑 ratio>0.1 完全一致。
    min_range_threshold = round(min_price_range - 1.0, 10)

    if len(data.index) < listing_days:
        return False

    data = data.tail(n=window)
    inc_days = 0
    dec_days = 0
    days_count = len(data.index)
    if days_count < window:
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
    if atr > max_atr:
        return False

    ratio = (highest_row - lowest_row) / lowest_row if lowest_row != 0 else 0

    if ratio > min_range_threshold:
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
