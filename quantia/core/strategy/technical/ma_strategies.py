#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
均线技术类策略

包含：
- 均线多头
- 回踩年线
- 海龟交易法则
- 低ATR成长
"""

import numpy as np
import pandas as pd
import talib as tl
from datetime import datetime, timedelta
from ..base import TechnicalStrategy, register_strategy

__author__ = 'Quantia'
__date__ = '2026/02/14'


@register_strategy
class MABullishStrategy(TechnicalStrategy):
    """
    均线多头策略

    选股条件:
    1. 30日前的30日均线<20日前的30日均线<10日前的30日均线<当日的30日均线
    2. (当日的30日均线/30日前的30日均线)>1.2
    """
    name = "keep_increasing"
    cn_name = "均线多头"
    default_threshold = 30
    description = "MA30均线持续上涨，涨幅超过20%"

    def check(self, code_name, data, date=None, **kwargs):
        data = self.prepare_data(code_name, data, date)
        if data is None:
            return False

        data.loc[:, 'ma30'] = self.calc_ma(data, 'close', 30)
        data = data.tail(n=self.threshold)

        if len(data) < self.threshold:
            return False

        step1 = round(self.threshold / 3)
        step2 = round(self.threshold * 2 / 3)

        # 均线持续上涨
        if (data.iloc[0]['ma30'] < data.iloc[step1]['ma30'] <
            data.iloc[step2]['ma30'] < data.iloc[-1]['ma30'] and
            data.iloc[-1]['ma30'] > 1.2 * data.iloc[0]['ma30']):
            return True
        return False


@register_strategy
class MA250PullbackStrategy(TechnicalStrategy):
    """
    回踩年线策略

    选股条件:
    1. 前段由年线(250日)以下向上突破
    2. 后段必须在年线以上运行，且后段最低价日与最高价日相差必须在10-50日间
    3. 回踩伴随缩量：最高价日交易量/后段最低价日交易量>2, 后段最低价/最高价<0.8
    """
    name = "backtrace_ma250"
    cn_name = "回踩年线"
    default_threshold = 60
    description = "突破年线后回踩不破年线，缩量整理"

    def check(self, code_name, data, date=None, **kwargs):
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
        if len(data.index) < 250:
            return False

        data.loc[:, 'ma250'] = self.calc_ma(data, 'close', 250)
        data = data.tail(n=self.threshold)

        # 区间最低点、最高点
        lowest_row = [1000000, 0, '']
        highest_row = [0, 0, '']
        recent_lowest_row = [1000000, 0, '']

        for _close, _volume, _date in zip(data['close'].values, data['volume'].values, data['date'].values):
            if _close > highest_row[0]:
                highest_row = [_close, _volume, _date]
            if _close < lowest_row[0]:
                lowest_row = [_close, _volume, _date]

        if lowest_row[1] == 0 or highest_row[1] == 0:
            return False

        data_front = data.loc[(data['date'] < highest_row[2])]
        data_end = data.loc[(data['date'] >= highest_row[2])]

        if data_front.empty:
            return False

        # 前半段由年线以下向上突破
        if not (data_front.iloc[0]['close'] < data_front.iloc[0]['ma250'] and
                data_front.iloc[-1]['close'] > data_front.iloc[-1]['ma250']):
            return False

        if not data_end.empty:
            # 后半段必须在年线以上运行
            for _close, _volume, _date, _ma250 in zip(data_end['close'].values, data_end['volume'].values,
                                                       data_end['date'].values, data_end['ma250'].values):
                if _close < _ma250:
                    return False
                if _close < recent_lowest_row[0]:
                    recent_lowest_row = [_close, _volume, _date]

        try:
            date_diff = pd.Timestamp(recent_lowest_row[2]) - pd.Timestamp(highest_row[2])
        except (ValueError, TypeError):
            return False

        if not (timedelta(days=10) <= date_diff <= timedelta(days=50)):
            return False

        # 回踩伴随缩量
        if recent_lowest_row[1] == 0:
            return False
        vol_ratio = highest_row[1] / recent_lowest_row[1]
        back_ratio = recent_lowest_row[0] / highest_row[0]

        return vol_ratio > 2 and back_ratio < 0.8


@register_strategy
class TurtleTradingStrategy(TechnicalStrategy):
    """
    海龟交易法则

    选股条件:
    1. 当日收盘价>=最近60日最高收盘价
    """
    name = "turtle_trade"
    cn_name = "海龟交易法则"
    default_threshold = 60
    description = "突破60日新高，海龟交易买入信号"

    def check(self, code_name, data, date=None, **kwargs):
        data = self.prepare_data(code_name, data, date)
        if data is None:
            return False

        data = data.tail(n=self.threshold)

        if len(data) < self.threshold:
            return False

        max_price = data['close'].max()
        last_close = data.iloc[-1]['close']

        return last_close >= max_price


@register_strategy
class LowATRGrowthStrategy(TechnicalStrategy):
    """
    低ATR成长策略

    选股条件:
    1. ATR值较低，波动性小
    2. 股价稳健上涨
    """
    name = "low_atr"
    cn_name = "低ATR成长"
    default_threshold = 120
    description = "低波动稳健上涨股票"

    def check(self, code_name, data, date=None, **kwargs):
        data = self.prepare_data(code_name, data, date)
        if data is None:
            return False

        if len(data) < 120:
            return False

        # 计算ATR
        data.loc[:, 'atr'] = self.calc_atr(data, 14)
        data = data.tail(n=self.threshold)

        last = data.iloc[-1]

        # ATR相对于价格的比例
        atr_ratio = last['atr'] / last['close']

        # ATR比例低于3%
        if atr_ratio > 0.03:
            return False

        # 120日内涨幅超过10%
        first_close = data.iloc[0]['close']
        last_close = last['close']

        if last_close <= first_close * 1.1:
            return False

        return True


# 兼容性函数 - 供旧代码调用
def check(code_name, data, date=None, threshold=30):
    """均线多头策略检查函数（兼容旧接口）"""
    strategy = MABullishStrategy(threshold=threshold)
    return strategy.check(code_name, data, date)


def check_ma250(code_name, data, date=None, threshold=60):
    """回踩年线策略检查函数（兼容旧接口）"""
    strategy = MA250PullbackStrategy(threshold=threshold)
    return strategy.check(code_name, data, date)


def check_enter(code_name, data, date=None, threshold=60):
    """海龟交易策略检查函数（兼容旧接口）"""
    strategy = TurtleTradingStrategy(threshold=threshold)
    return strategy.check(code_name, data, date)


def check_low_increase(code_name, data, date=None, threshold=120):
    """低ATR成长策略检查函数（兼容旧接口）"""
    strategy = LowATRGrowthStrategy(threshold=threshold)
    return strategy.check(code_name, data, date)
