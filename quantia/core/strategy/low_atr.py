#!/usr/local/bin/python
# -*- coding: utf-8 -*-

import pandas as pd

__author__ = 'Quantia'
__date__ = '2026/02/14'


# 低ATR成长
# 1.必须至少上市交易 min_listing_days 日
# 2.最近 analysis_days 个交易日的平均波动 <= max_atr%
# 3.区间最高价/最低价 >= min_price_range
# 4.可选叠加区间涨幅、上涨天数占比、最大回撤、成交额过滤
#
# 参数（可经 UI/数据库 cn_strategy_params 真正接入每日选股与验证中心）：
#   max_atr          期间平均波动上限(%)，默认 10
#   min_price_range  最高/最低价比值下限，默认 1.1
#   analysis_days    近期分析窗口长度，默认 10
#   min_listing_days 最少上市交易天数，默认 250
#   min_total_return 区间最低涨幅(%)，默认 0（关闭）
#   min_up_days_ratio 上涨天数占比下限，默认 0（关闭）
#   max_drawdown     区间最大回撤上限(%)，默认 100（关闭）
#   min_turnover     最近一日最低成交额(亿)，默认 0（关闭）
# 兼容旧签名参数 ma_short/ma_long/threshold（threshold 作为 analysis_days 的兼容别名）。
def check_low_increase(code_name, data, date=None, ma_short=30, ma_long=250, threshold=10,
                       max_atr=10, min_price_range=1.1, analysis_days=None, min_listing_days=None,
                       min_total_return=0, min_up_days_ratio=0, max_drawdown=100, min_turnover=0):
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
    try:
        min_total_return = float(min_total_return)
    except (TypeError, ValueError):
        min_total_return = 0.0
    try:
        min_up_days_ratio = float(min_up_days_ratio)
    except (TypeError, ValueError):
        min_up_days_ratio = 0.0
    try:
        max_drawdown = float(max_drawdown)
    except (TypeError, ValueError):
        max_drawdown = 100.0
    try:
        min_turnover = float(min_turnover)
    except (TypeError, ValueError):
        min_turnover = 0.0
    # 阈值=比值-1（默认 1.1->0.1）。round 消除浮点误差，保证默认与旧逻辑 ratio>0.1 完全一致。
    min_range_threshold = round(min_price_range - 1.0, 10)

    if len(data.index) < listing_days:
        return False

    data = data.tail(n=window).copy()
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
    if 'p_change' in data.columns:
        change_values = pd.to_numeric(data['p_change'], errors='coerce').fillna(0).values
    else:
        change_values = pd.to_numeric(data['close'], errors='coerce').pct_change().fillna(0).mul(100).values
    for _close, _p_change in zip(data['close'].values, change_values):
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

    up_days_ratio = inc_days / days_count if days_count else 0
    if min_up_days_ratio > 0 and up_days_ratio < min_up_days_ratio:
        return False

    ratio = (highest_row - lowest_row) / lowest_row if lowest_row != 0 else 0
    first_close = float(data.iloc[0]['close']) if days_count else 0
    last_close = float(data.iloc[-1]['close']) if days_count else 0
    total_return = (last_close - first_close) / first_close * 100 if first_close else 0
    if min_total_return > 0 and total_return < min_total_return:
        return False

    close_series = pd.to_numeric(data['close'], errors='coerce')
    rolling_peak = close_series.cummax()
    drawdown_series = (rolling_peak - close_series) / rolling_peak.replace(0, pd.NA) * 100
    window_drawdown = float(drawdown_series.fillna(0).max())
    if max_drawdown < 100 and window_drawdown > max_drawdown:
        return False

    amount = None
    if min_turnover > 0:
        if 'volume' not in data.columns:
            return False
        last_vol = float(data.iloc[-1]['volume'] or 0)
        amount = last_close * last_vol
        if amount < min_turnover * 100000000:
            return False

    if ratio > min_range_threshold:
        p_change = data.iloc[-1]['p_change'] if 'p_change' in data.columns else 0.0
        metrics = {
            'p_change': round(float(p_change), 2),
            'close': round(last_close, 2),
            'atr': round(float(atr), 2),
            'highest_close': round(float(highest_row), 2),
            'lowest_close': round(float(lowest_row), 2),
            'range_ratio': round(float(ratio * 100), 2),
            'total_return': round(float(total_return), 2),
            'up_days_ratio': round(float(up_days_ratio * 100), 2),
            'max_drawdown': round(float(window_drawdown), 2),
        }
        if amount is not None:
            metrics['amount'] = round(float(amount), 2)
        return metrics

    return False
