#!/usr/local/bin/python
# -*- coding: utf-8 -*-

import numpy as np
import pandas as pd
import talib as tl

__author__ = 'Quantia'
__date__ = '2026/07/06'


_MA_PERIODS = (5, 10, 20, 30, 60)


def _to_float(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_bool(value, default=True):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().lower()
    if text in ('1', 'true', 'yes', 'on'):
        return True
    if text in ('0', 'false', 'no', 'off'):
        return False
    return default


def _calc_ma_slope_pct(series, window):
    try:
        window = max(1, int(window))
    except (TypeError, ValueError):
        window = 20
    if len(series.index) <= window:
        return np.nan
    current = float(series.iloc[-1])
    previous = float(series.iloc[-1 - window])
    if not np.isfinite(current) or not np.isfinite(previous) or previous <= 0:
        return np.nan
    return (current - previous) / previous * 100


def _calc_hit_count(data, low_window, low_position_pct, convergence_pct, max_close_ma60_dev,
                    enable_trend_filter, trend_slope_window,
                    min_ma30_slope_pct, min_ma60_slope_pct):
    close = data['close'].astype(float)
    low = data['low'].astype(float) if 'low' in data.columns else close
    high = data['high'].astype(float) if 'high' in data.columns else close

    ma_cols = [f'ma{period}' for period in _MA_PERIODS]
    ma_frame = data[ma_cols]
    ma_max = ma_frame.max(axis=1)
    ma_min = ma_frame.min(axis=1)
    ma_mean = ma_frame.mean(axis=1)
    convergence = (ma_max - ma_min) / ma_mean * 100

    period_low = low.rolling(low_window, min_periods=low_window).min()
    period_high = high.rolling(low_window, min_periods=low_window).max()
    low_position = (close - period_low) / (period_high - period_low) * 100
    close_ma60_dev = (close - data['ma60'].astype(float)).abs() / data['ma60'].astype(float) * 100

    trend_ok = pd.Series(True, index=data.index)
    if enable_trend_filter:
        ma30_slope = (data['ma30'].astype(float) - data['ma30'].astype(float).shift(trend_slope_window)) / data['ma30'].astype(float).shift(trend_slope_window) * 100
        ma60_slope = (data['ma60'].astype(float) - data['ma60'].astype(float).shift(trend_slope_window)) / data['ma60'].astype(float).shift(trend_slope_window) * 100
        trend_ok = (
            ma30_slope.replace([np.inf, -np.inf], np.nan).notna() &
            ma60_slope.replace([np.inf, -np.inf], np.nan).notna() &
            (ma30_slope >= min_ma30_slope_pct) &
            (ma60_slope >= min_ma60_slope_pct)
        )

    hits = (
        ma_frame.notna().all(axis=1) &
        (ma_frame > 0).all(axis=1) &
        (ma_mean > 0) &
        (period_high > period_low) &
        (convergence <= convergence_pct) &
        (low_position <= low_position_pct) &
                (close_ma60_dev <= max_close_ma60_dev) &
                trend_ok
    )
    return int(hits.tail(low_window).sum())


def check(code_name, data, date=None, threshold=120, low_window=120,
                    low_position_pct=80, convergence_pct=6.0, max_close_ma60_dev=8,
                    enable_trend_filter=1, trend_slope_window=1,
                    min_ma30_slope_pct=-0.5, min_ma60_slope_pct=-0.1):
    """低位均线粘合策略。

    选股条件：
    1. 当前收盘价处于近 low_window 日价格区间的中低位，默认不高于 80% 分位；
    2. MA5/10/20/30/60 五条均线粘合，最大均线与最小均线的差距不超过均线均值的 6.0%；
    3. 当前收盘价没有明显远离 MA60，默认偏离不超过 8%；
    4. MA60 近 trend_slope_window 日不能继续明显下行，过滤下降趋势中的“假粘合”。
    """
    if date is None:
        end_date = code_name[0]
    else:
        end_date = date.strftime("%Y-%m-%d")
    if end_date is not None:
        if not pd.api.types.is_datetime64_any_dtype(data['date']):
            data = data.copy()
            data['date'] = pd.to_datetime(data['date'])
        end_date = pd.Timestamp(end_date)
        data = data.loc[data['date'] <= end_date].copy()

    low_window = max(60, _to_int(low_window, 120))
    threshold = max(60, _to_int(threshold, low_window))
    low_position_pct = _to_float(low_position_pct, 80.0)
    convergence_pct = _to_float(convergence_pct, 6.0)
    max_close_ma60_dev = _to_float(max_close_ma60_dev, 8.0)
    enable_trend_filter = _to_bool(enable_trend_filter, True)
    trend_slope_window = max(1, _to_int(trend_slope_window, 1))
    min_ma30_slope_pct = _to_float(min_ma30_slope_pct, -0.5)
    min_ma60_slope_pct = _to_float(min_ma60_slope_pct, -0.1)

    if len(data.index) < max(threshold, low_window, max(_MA_PERIODS) + trend_slope_window):
        return False

    data = data.copy()
    for period in _MA_PERIODS:
        ma = tl.MA(data['close'].values, timeperiod=period)
        data[f'ma{period}'] = pd.Series(ma, index=data.index).replace([np.inf, -np.inf], np.nan)

    last = data.iloc[-1]
    ma_values = np.array([last[f'ma{period}'] for period in _MA_PERIODS], dtype=float)
    if not np.isfinite(ma_values).all() or np.any(ma_values <= 0):
        return False

    ma_mean = float(ma_values.mean())
    if ma_mean <= 0:
        return False
    convergence = (float(ma_values.max()) - float(ma_values.min())) / ma_mean * 100
    if convergence > convergence_pct:
        return False

    close = float(last['close'])
    low_data = data.tail(low_window)
    period_low = float(low_data['low'].min() if 'low' in low_data.columns else low_data['close'].min())
    period_high = float(low_data['high'].max() if 'high' in low_data.columns else low_data['close'].max())
    if period_high <= period_low:
        return False

    low_position = (close - period_low) / (period_high - period_low) * 100
    if low_position > low_position_pct:
        return False

    close_ma60_dev = abs(close - float(last['ma60'])) / float(last['ma60']) * 100
    if close_ma60_dev > max_close_ma60_dev:
        return False

    ma30_slope = _calc_ma_slope_pct(data['ma30'].astype(float), trend_slope_window)
    ma60_slope = _calc_ma_slope_pct(data['ma60'].astype(float), trend_slope_window)
    if enable_trend_filter:
        if not (np.isfinite(ma30_slope) and np.isfinite(ma60_slope)):
            return False
        if ma30_slope < min_ma30_slope_pct or ma60_slope < min_ma60_slope_pct:
            return False

    hit_count = _calc_hit_count(
        data, low_window, low_position_pct, convergence_pct, max_close_ma60_dev,
        enable_trend_filter, trend_slope_window,
        min_ma30_slope_pct, min_ma60_slope_pct
    )

    p_change = last['p_change'] if 'p_change' in data.columns else 0.0
    return {
        'p_change': round(float(p_change), 2),
        'close': round(close, 2),
        'hit_count': hit_count,
        'low_position': round(float(low_position), 2),
        'ma_convergence': round(float(convergence), 2),
        'close_ma60_dev': round(float(close_ma60_dev), 2),
        'ma30_slope': round(float(ma30_slope), 2) if np.isfinite(ma30_slope) else None,
        'ma60_slope': round(float(ma60_slope), 2) if np.isfinite(ma60_slope) else None,
        'ma5': round(float(last['ma5']), 3),
        'ma10': round(float(last['ma10']), 3),
        'ma20': round(float(last['ma20']), 3),
        'ma30': round(float(last['ma30']), 3),
        'ma60': round(float(last['ma60']), 3),
    }