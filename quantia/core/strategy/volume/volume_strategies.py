#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
成交量类策略

包含：
- 放量上涨
- 放量跌停
"""

import numpy as np
import talib as tl
from ..base import VolumeStrategy, register_strategy

__author__ = 'Quantia'
__date__ = '2026/02/14'


@register_strategy
class VolumeIncreaseStrategy(VolumeStrategy):
    """
    放量上涨策略

    选股条件:
    1. 当日比前一天上涨大于2%且收盘价大于开盘价
    2. 当日成交额不低于2亿
    3. 当日成交量/5日平均成交量>=2
    """
    name = "enter"
    cn_name = "放量上涨"
    default_threshold = 60
    description = "当日放量上涨超过2%，成交额超2亿，量比超2"

    def check(self, code_name, data, date=None, **kwargs):
        data = self.prepare_data(code_name, data, date)
        if data is None:
            return False

        # 涨幅判断
        p_change = data.iloc[-1]['p_change']
        if p_change < 2 or data.iloc[-1]['close'] < data.iloc[-1]['open']:
            return False

        # 计算5日均量
        data.loc[:, 'vol_ma5'] = self.calc_vol_ma(data, period=5)

        data = data.tail(n=self.threshold + 1)
        if len(data) < self.threshold + 1:
            return False

        # 最后一天数据
        last_close = data.iloc[-1]['close']
        last_vol = data.iloc[-1]['volume']

        # 成交额不低于2亿
        amount = last_close * last_vol
        if amount < 200000000:
            return False

        data = data.head(n=self.threshold)
        mean_vol = data.iloc[-1]['vol_ma5']

        if mean_vol <= 0:
            return False

        # 量比>=2
        vol_ratio = last_vol / mean_vol
        return vol_ratio >= 2


@register_strategy
class ClimaxLimitdownStrategy(VolumeStrategy):
    """
    放量跌停策略

    选股条件:
    1. 单日真实跌幅贴近所属板块跌停限制（主板±10/创业板·科创±20/北交所±30/主板ST±5，
       自适应，并剔除除权·复牌价格伪跳变）
    2. 收盘价封死在当日最低价附近（封板确认）
    3. 放量（量比 + 成交额）

    实现委托给 quantia.core.strategy.climax_limitdown.check，保持与每日选股一致。
    """
    name = "climax_limitdown"
    cn_name = "放量跌停"
    default_threshold = 60
    description = "当日放量封死跌停板，可能是恐慌性抛售"

    def check(self, code_name, data, date=None, **kwargs):
        from ..climax_limitdown import check as _check
        return _check(code_name, data, date=date, threshold=self.threshold, **kwargs)


# 兼容性函数 - 供旧代码调用
def check_volume(code_name, data, date=None, threshold=60):
    """放量上涨策略检查函数（兼容旧接口）"""
    strategy = VolumeIncreaseStrategy(threshold=threshold)
    return strategy.check(code_name, data, date)


def check(code_name, data, date=None, threshold=60):
    """放量跌停策略检查函数（兼容旧接口）"""
    strategy = ClimaxLimitdownStrategy(threshold=threshold)
    return strategy.check(code_name, data, date)
