#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
筹码分布指标（截止当日）批量计算。

与 quantia/core/kline/cyq.py 同源的三角形分布 + 换手率衰减模型，但窗口口径为
"最近 lookback 根、截止到目标日"，语义与东财 stock_cyq_em 最后一行一致，适合选股/回测。

设计要点：
- 纯函数，零 I/O、零 API（数据由调用方从本地 K 线缓存读入后传入）。
- 输出全部保证有限（NaN/inf 就地置 None，不把清洗甩给 DB 层）。
- total_chips<=0（停牌/换手全 0）或 K 线不足 → 返回 None，不落该行。
"""

import math

import numpy as np
import pandas as pd

import quantia.lib.envconfig as _cfg

__author__ = 'Quantia'
__date__ = '2026/07/07'

# 窗口长度（约半年，换手衰减已弱化更早筹码影响）
_LOOKBACK = _cfg.get_int('QUANTIA_CYQ_LOOKBACK', 120)
# 价位桶数（与 cyq.js 一致）
_FACTOR = _cfg.get_int('QUANTIA_CYQ_FACTOR', 150)
# 窗口内最少 K 线数，不足则跳过（新股/次新噪声大）
_MIN_BARS = _cfg.get_int('QUANTIA_CYQ_MIN_BARS', 20)

_REQUIRED_COLUMNS = ('open', 'high', 'low', 'close', 'turnover')


def _finite_or_none(value):
    """转 float，非有限（NaN/inf）或不可转 → None。"""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return f


def _accumulate_distribution(kdata, factor):
    """核心：三角形分布 + 换手率衰减叠加（从旧到新遍历）。

    Args:
        kdata: DataFrame，含 open/high/low/close/turnover，按时间升序。
        factor: 价位桶数。

    Returns:
        (xdata:list[float], min_price:float, accuracy:float) | None
    """
    opens = kdata['open'].to_numpy(dtype=float)
    highs = kdata['high'].to_numpy(dtype=float)
    lows = kdata['low'].to_numpy(dtype=float)
    closes = kdata['close'].to_numpy(dtype=float)
    turns = kdata['turnover'].to_numpy(dtype=float)

    max_price = float(np.max(highs))
    min_price = float(np.min(lows))
    if not (math.isfinite(max_price) and math.isfinite(min_price)):
        return None
    accuracy = max(0.01, (max_price - min_price) / (factor - 1))

    xdata = [0.0] * factor
    for open_p, close, high, low, turnover in zip(opens, closes, highs, lows, turns):
        if not math.isfinite(turnover) or turnover < 0:
            turnover = 0.0
        avg = (open_p + close + high + low) / 4.0
        turnover_rate = min(1.0, turnover / 100.0)

        g0 = (factor - 1) if high == low else 2.0 / (high - low)
        g1 = int((avg - min_price) / accuracy)

        # 换手衰减（旧筹码换手离场）
        if turnover_rate > 0:
            decay = 1.0 - turnover_rate
            for n in range(factor):
                xdata[n] *= decay

        if high == low:
            idx = min(max(g1, 0), factor - 1)
            xdata[idx] += g0 * turnover_rate / 2.0
        else:
            low_idx = int((low - min_price) / accuracy + 0.99)
            high_idx = int((high - min_price) / accuracy)
            for j in range(max(low_idx, 0), min(high_idx + 1, factor)):
                curprice = min_price + accuracy * j
                if curprice <= avg:
                    if abs(avg - low) < 1e-8:
                        xdata[j] += g0 * turnover_rate
                    else:
                        xdata[j] += (curprice - low) / (avg - low) * g0 * turnover_rate
                else:
                    if abs(high - avg) < 1e-8:
                        xdata[j] += g0 * turnover_rate
                    else:
                        xdata[j] += (high - curprice) / (high - avg) * g0 * turnover_rate

    return xdata, min_price, accuracy


def compute_chip_metrics(hist_data, lookback=None, factor=None, min_bars=None,
                         close_override=None):
    """计算"截止当日"的筹码分布核心指标。

    Args:
        hist_data: read_stock_hist_from_cache 返回的 DataFrame（时间升序，
            含 open/high/low/close/turnover）。
        lookback/factor/min_bars: 覆盖默认参数（缺省读环境变量）。
        close_override: 用指定收盘价计算获利比例（默认取窗口最后一根 close）。

    Returns:
        dict | None：非 None 时含
        close, winner_rate(%), avg_cost, cost_90_low/high, concentration_90,
        cost_70_low/high, concentration_70。任何退化情形返回 None。
    """
    if hist_data is None or len(hist_data) == 0:
        return None
    if not all(c in hist_data.columns for c in _REQUIRED_COLUMNS):
        return None

    lookback = _LOOKBACK if lookback is None else int(lookback)
    factor = _FACTOR if factor is None else int(factor)
    min_bars = _MIN_BARS if min_bars is None else int(min_bars)
    if factor < 2:
        return None

    kdata = hist_data.tail(lookback).copy()
    kdata['turnover'] = pd.to_numeric(kdata['turnover'], errors='coerce').fillna(0.0)
    for col in ('open', 'high', 'low', 'close'):
        kdata[col] = pd.to_numeric(kdata[col], errors='coerce')
    kdata = kdata.dropna(subset=['open', 'high', 'low', 'close'])
    if len(kdata) < min_bars:
        return None

    acc = _accumulate_distribution(kdata, factor)
    if acc is None:
        return None
    xdata, min_price, accuracy = acc

    total_chips = math.fsum(xdata)
    if not math.isfinite(total_chips) or total_chips <= 0:
        return None

    if close_override is not None:
        current_price = _finite_or_none(close_override)
    else:
        current_price = _finite_or_none(kdata.iloc[-1]['close'])
    if current_price is None:
        return None

    def cost_by_chip(chip):
        acc_sum = 0.0
        for i in range(factor):
            x = xdata[i]
            if acc_sum + x > chip:
                return min_price + i * accuracy
            acc_sum += x
        return min_price + (factor - 1) * accuracy

    def benefit_part(price):
        below = 0.0
        for i in range(factor):
            if price >= min_price + i * accuracy:
                below += xdata[i]
        return below / total_chips

    def pct_range(percent):
        lo = cost_by_chip(total_chips * (1 - percent) / 2.0)
        hi = cost_by_chip(total_chips * (1 + percent) / 2.0)
        conc = 0.0 if (lo + hi) == 0 else (hi - lo) / (lo + hi)
        return lo, hi, conc

    winner_rate = benefit_part(current_price) * 100.0
    avg_cost = cost_by_chip(total_chips * 0.5)
    c90_low, c90_high, conc90 = pct_range(0.9)
    c70_low, c70_high, conc70 = pct_range(0.7)

    return {
        'close': _finite_or_none(current_price),
        'winner_rate': _finite_or_none(winner_rate),
        'avg_cost': _finite_or_none(avg_cost),
        'cost_90_low': _finite_or_none(c90_low),
        'cost_90_high': _finite_or_none(c90_high),
        'concentration_90': _finite_or_none(conc90),
        'cost_70_low': _finite_or_none(c70_low),
        'cost_70_high': _finite_or_none(c70_high),
        'concentration_70': _finite_or_none(conc70),
    }
