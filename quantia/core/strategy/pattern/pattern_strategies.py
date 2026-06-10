#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
形态类策略

包含：
- 突破平台
- 停机坪
- 高而窄的旗形
- 无大幅回撤
"""

import numpy as np
import pandas as pd
import talib as tl
from datetime import datetime
from ..base import PatternStrategy, register_strategy

__author__ = 'Quantia'
__date__ = '2026/02/14'


@register_strategy
class BreakthroughPlatformStrategy(PatternStrategy):
    """
    突破平台策略

    选股条件:
    1. 真实平台: 突破日之前需有不少于 min_platform_days 个交易日收盘价贴近 MA60（偏离 -5%~20%）
    2. 近期突破: 突破日（开盘价<MA60<=收盘价 且放量上涨）须发生在信号日当天或最近 recent_days 个交易日内
    3. 仍站稳平台: 突破日至信号日收盘价持续 >= MA60，未跌回均线下方
    """
    name = "breakthrough_platform"
    cn_name = "突破平台"
    default_threshold = 60
    description = "在横盘平台后近期放量突破60日均线，且当前仍站稳均线之上"

    def check(self, code_name, data, date=None, **kwargs):
        from ..volume.volume_strategies import VolumeIncreaseStrategy

        recent_days = kwargs.get('recent_days', 3)
        min_platform_days = kwargs.get('min_platform_days', 10)

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
            data = data.loc[mask].copy()
        if len(data.index) < self.threshold:
            return False

        data.loc[:, 'ma60'] = tl.MA(data['close'].values, timeperiod=60)
        data['ma60'] = data['ma60'].fillna(0.0)

        data = data.tail(n=self.threshold)

        volume_strategy = VolumeIncreaseStrategy(threshold=self.threshold)

        # A. 仅在最近 recent_days 个交易日内寻找突破日，并取最近的一次突破。
        recent = data.tail(n=max(1, recent_days))
        breakthrough_row = None
        for _close, _open, _date, _ma60 in zip(
                recent['close'].values[::-1], recent['open'].values[::-1],
                recent['date'].values[::-1], recent['ma60'].values[::-1]):
            if _ma60 > 0 and _open < _ma60 <= _close:
                check_date = pd.Timestamp(_date)
                if volume_strategy.check(code_name, origin_data, date=check_date):
                    breakthrough_row = _date
                    break

        if breakthrough_row is None:
            return False

        # C. 突破日之前需构成真实平台：样本足够多，且全部贴近 MA60。
        data_front = data.loc[(data['date'] < breakthrough_row) & (data['ma60'] > 0)]
        if len(data_front) < min_platform_days:
            return False
        for _close, _ma60 in zip(data_front['close'].values, data_front['ma60'].values):
            # 收盘价与60日均线偏离在-5%~20%之间
            deviation = (_close - _ma60) / _ma60
            if not (-0.05 < deviation < 0.2):
                return False

        # B. 突破日至信号日收盘价需持续站稳 MA60 之上，未跌回均线下方。
        data_after = data.loc[data['date'] >= breakthrough_row]
        for _close, _ma60 in zip(data_after['close'].values, data_after['ma60'].values):
            if _ma60 <= 0 or _close < _ma60:
                return False

        return True


@register_strategy
class ParkingApronStrategy(PatternStrategy):
    """
    停机坪策略

    选股条件:
    1. 最近15日有涨幅大于9.5%，且必须是放量上涨
    2. 紧接的下个交易日必须高开，收盘价必须上涨，且与开盘价不能大于等于相差3%
    3. 接下2、3个交易日必须高开，收盘价必须上涨，且与开盘价不能大于等于相差3%，且每天涨跌幅在5%间
    """
    name = "parking_apron"
    cn_name = "停机坪"
    default_threshold = 15
    description = "涨停后横盘整理，蓄势待发"

    def check(self, code_name, data, date=None, **kwargs):
        from ..technical.ma_strategies import TurtleTradingStrategy

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
        if len(data.index) < self.threshold:
            return False

        data = data.tail(n=self.threshold)

        turtle_strategy = TurtleTradingStrategy(threshold=self.threshold)

        limitup_row = [1000000, '']
        for _close, _p_change, _date in zip(data['close'].values, data['p_change'].values, data['date'].values):
            if _p_change > 9.5:
                check_date = pd.Timestamp(_date)
                if turtle_strategy.check(code_name, origin_data, date=check_date):
                    limitup_row = [_close, _date]
                    if self._check_internal(data, limitup_row):
                        return True
        return False

    def _check_internal(self, data, limitup_row):
        """检查涨停后的整理形态"""
        limitup_price = limitup_row[0]
        limitup_end = data.loc[(data['date'] > limitup_row[1])]
        limitup_end = limitup_end.head(n=3)
        if len(limitup_end.index) < 3:
            return False

        consolidation_day1 = limitup_end.iloc[0]
        consolidation_day23 = limitup_end.tail(n=2)

        # 第一天检查
        if not (consolidation_day1['close'] > limitup_price and
                consolidation_day1['open'] > limitup_price and
                consolidation_day1['open'] != 0 and
                0.97 < consolidation_day1['close'] / consolidation_day1['open'] < 1.03):
            return False

        # 第二、三天检查
        for _close, _p_change, _open in zip(consolidation_day23['close'].values,
                                            consolidation_day23['p_change'].values,
                                            consolidation_day23['open'].values):
            if not (0.97 < (_close / _open) < 1.03 and -5 < _p_change < 5
                    and _close > limitup_price and _open > limitup_price and _open != 0):
                return False

        return True


@register_strategy
class HighTightFlagStrategy(PatternStrategy):
    """
    高而窄的旗形策略

    选股条件:
    1. 必须至少上市交易60日
    2. 当日收盘价/之前24~10日的最低价>=1.9
    3. 之前24~10日必须连续两天涨幅大于等于9.5%
    4. 龙虎榜上必须有机构
    """
    name = "high_tight_flag"
    cn_name = "高而窄的旗形"
    default_threshold = 60
    description = "短期快速上涨后窄幅整理，有机构参与"

    def check(self, code_name, data, date=None, istop=False, **kwargs):
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
        if len(data.index) < self.threshold:
            return False

        data = data.tail(n=self.threshold)
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
            if _p_change >= 9.5:
                if previous_p_change >= 9.5:
                    return True
                else:
                    previous_p_change = _p_change
            else:
                previous_p_change = 0.0

        return False


@register_strategy
class LowBacktraceIncreaseStrategy(PatternStrategy):
    """
    无大幅回撤策略

    选股条件:
    1. 当日收盘价比60日前的收盘价的涨幅大于60%
    2. 最近60日，不能有单日跌幅超7%、高开低走7%、两日累计跌幅10%、两日高开低走累计10%
    """
    name = "low_backtrace_increase"
    cn_name = "无大幅回撤"
    default_threshold = 60
    description = "稳健上涨无大幅回撤，走势健康"

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
            data = data.loc[mask]
        if len(data.index) < self.threshold:
            return False

        data = data.tail(n=self.threshold)

        # 涨幅检查
        first_close = data.iloc[0]['close']
        if first_close == 0:
            return False
        ratio_increase = (data.iloc[-1]['close'] - first_close) / first_close
        if ratio_increase < 0.6:
            return False

        # 回撤检查
        previous_p_change = 100.0
        previous_open = data.iloc[0]['open']  # 用首日开盘价初始化，避免-1000000导致首次迭代永远返回False
        for _p_change, _close, _open in zip(data['p_change'].values, data['close'].values, data['open'].values):
            if (_p_change < -7 or
                (_open != 0 and (_close - _open) / _open * 100 < -7) or
                previous_p_change + _p_change < -10 or
                (previous_open != 0 and (_close - previous_open) / previous_open * 100 < -10)):
                return False
            previous_p_change = _p_change
            previous_open = _open

        return True


# 兼容性函数 - 供旧代码调用
def check_breakthrough(code_name, data, date=None, threshold=60):
    """突破平台策略检查函数（兼容旧接口）"""
    strategy = BreakthroughPlatformStrategy(threshold=threshold)
    return strategy.check(code_name, data, date)


def check_parking(code_name, data, date=None, threshold=15):
    """停机坪策略检查函数（兼容旧接口）"""
    strategy = ParkingApronStrategy(threshold=threshold)
    return strategy.check(code_name, data, date)


def check_high_tight(code_name, data, date=None, threshold=60, istop=False):
    """高而窄的旗形策略检查函数（兼容旧接口）"""
    strategy = HighTightFlagStrategy(threshold=threshold)
    return strategy.check(code_name, data, date, istop=istop)


def check_low_backtrace(code_name, data, date=None, threshold=60):
    """无大幅回撤策略检查函数（兼容旧接口）"""
    strategy = LowBacktraceIncreaseStrategy(threshold=threshold)
    return strategy.check(code_name, data, date)
