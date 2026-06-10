#!/usr/local/bin/python
# -*- coding: utf-8 -*-

from datetime import datetime
import pandas as pd
from quantia.core.strategy import turtle_trade

__author__ = 'Quantia'
__date__ = '2026/02/14'


# 停机坪
# 1.最近 threshold 日有涨幅大于 limit_up_pct%，且必须是放量上涨
# 2.紧接的下个交易日必须高开，收盘价必须上涨，且与开盘价偏差不超过 max_open_close_ratio%
# 3.接下 consolidation_days-1 个交易日同样满足上述条件，且每天涨跌幅在 ±max_daily_change% 间
#
# 参数（可经 UI/数据库 cn_strategy_params 真正接入每日选股与验证中心）：
#   limit_up_pct          认定为涨停的最低涨幅(%)，默认 9.5
#   consolidation_days    涨停后检查的整理天数，默认 3
#   max_open_close_ratio  整理日开盘与收盘的最大偏差(%)，默认 3
#   max_daily_change      整理日最大允许的涨跌幅(%)，默认 5
#   threshold             分析窗口长度，默认 15
def check(code_name, data, date=None, threshold=15,
          limit_up_pct=9.5, consolidation_days=3,
          max_open_close_ratio=3, max_daily_change=5):
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
        data = data.loc[mask]
    if len(data.index) < threshold:
        return False

    # 参数归一化（UI/DB 传入可能是字符串）
    try:
        limit_up_pct = float(limit_up_pct)
    except (TypeError, ValueError):
        limit_up_pct = 9.5
    try:
        consolidation_days = max(2, int(consolidation_days))
    except (TypeError, ValueError):
        consolidation_days = 3
    try:
        oc_band = float(max_open_close_ratio) / 100.0
    except (TypeError, ValueError):
        oc_band = 0.03
    try:
        max_daily_change = float(max_daily_change)
    except (TypeError, ValueError):
        max_daily_change = 5.0

    data = data.tail(n=threshold)

    limitup_row = [1000000, '']
    # 找出涨停日
    for _close, _p_change, _date in zip(data['close'].values, data['p_change'].values, data['date'].values):
        if _p_change > limit_up_pct:
            if turtle_trade.check_enter(code_name, origin_data, date=pd.Timestamp(_date), threshold=threshold):
                limitup_row[0] = _close
                limitup_row[1] = _date
                if check_internal(data, limitup_row, consolidation_days, oc_band, max_daily_change):
                    last_p_change = data.iloc[-1]['p_change'] if 'p_change' in data.columns else 0.0
                    return {
                        'p_change': round(float(last_p_change), 2),
                        'close': round(float(data.iloc[-1]['close']), 2),
                        'limitup_price': round(float(_close), 2),
                        'limitup_pchange': round(float(_p_change), 2),
                    }
    return False

def check_internal(data, limitup_row, consolidation_days=3, oc_band=0.03, max_daily_change=5):
    limitup_price = limitup_row[0]
    limitup_end = data.loc[(data['date'] > limitup_row[1])]
    limitup_end = limitup_end.head(n=consolidation_days)
    if len(limitup_end.index) < consolidation_days:
        return False

    consolidation_day1 = limitup_end.iloc[0]
    consolidation_day_rest = limitup_end.tail(n=consolidation_days - 1)

    lo, hi = 1.0 - oc_band, 1.0 + oc_band
    if not (consolidation_day1['close'] > limitup_price and consolidation_day1['open'] > limitup_price and
            consolidation_day1['open'] != 0 and
            lo < consolidation_day1['close'] / consolidation_day1['open'] < hi):
        return False

    for _close, _p_change, _open in zip(consolidation_day_rest['close'].values, consolidation_day_rest['p_change'].values, consolidation_day_rest['open'].values):
        if not (lo < (_close / _open) < hi and -max_daily_change < _p_change < max_daily_change
                and _close > limitup_price and _open > limitup_price and _open != 0):
            return False

    return True
