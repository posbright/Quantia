#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
长期价值投资策略组

基于 ChatGPT 选股策略文档实现的三类买入策略：
1. 趋势回调买入 - 优质股票在上涨趋势中的回调买点
2. 超跌反弹买入 - 情绪错杀后的修复机会
3. 突破确认买入 - 横盘整理后的放量突破

这些策略侧重于技术择时，适合结合基本面选股使用。
"""

import numpy as np
import talib as tl
from datetime import datetime
from ..base import TechnicalStrategy, register_strategy

__author__ = 'Quantia'
__date__ = '2026/02/14'


@register_strategy
class TrendPullbackStrategy(TechnicalStrategy):
    """
    趋势回调买入策略

    适用场景：优质公司处于长期上涨趋势中的回调买点

    买入条件（全部满足）：
    1. MA20 > MA60（中期趋势向上）
    2. 价格回调至 MA20 附近（±3%）
    3. RSI(14) 在 35-55 区间（不过热也不过冷）
    4. 回调过程缩量（当日成交量 < 5日均量）

    逻辑解释：
    - 均线多头排列确保趋势向上
    - 价格回踩均线提供低吸机会
    - RSI居中表明动能适中，有上涨空间
    - 缩量回调说明抛压不大，有利于反弹
    """
    name = "trend_pullback"
    cn_name = "趋势回调"
    default_threshold = 60
    description = "上涨趋势中的回调买点，RSI居中，缩量整理"

    def check(self, code_name, data, date=None, **kwargs):
        data = self.prepare_data(code_name, data, date)
        if data is None or len(data) < self.threshold:
            return False

        try:
            close = data['close'].values
            volume = data['volume'].values

            # 计算均线
            ma20 = tl.MA(close, timeperiod=20)
            ma60 = tl.MA(close, timeperiod=60)

            # 计算RSI
            rsi = tl.RSI(close, timeperiod=14)

            # 计算成交量均线（5日均量，与策略说明口径一致：缩量回调判断）
            vol_ma5 = tl.MA(volume.astype(float), timeperiod=5)

            # 获取最新数据
            last_close = close[-1]
            last_ma20 = ma20[-1]
            last_ma60 = ma60[-1]
            last_rsi = rsi[-1]
            last_vol = volume[-1]
            last_vol_ma5 = vol_ma5[-1]

            # 处理NaN值
            if np.isnan(last_ma20) or np.isnan(last_ma60) or np.isnan(last_rsi):
                return False
            if np.isnan(last_vol_ma5) or last_vol_ma5 == 0:
                return False

            # 条件1: MA20 > MA60（趋势向上）
            if last_ma20 <= last_ma60:
                return False

            # 条件2: 价格在MA20附近（±3%）
            ma20_deviation = abs(last_close - last_ma20) / last_ma20
            if ma20_deviation > 0.03:
                return False

            # 条件3: RSI在35-55区间
            if not (35 <= last_rsi <= 55):
                return False

            # 条件4: 缩量回调（成交量低于5日均量的80%）
            if last_vol >= last_vol_ma5 * 0.8:
                return False

            p_change = data.iloc[-1]['p_change'] if 'p_change' in data.columns else 0.0
            return {
                'p_change': round(float(p_change), 2),
                'close': round(float(last_close), 2),
                'ma20': round(float(last_ma20), 2),
                'ma60': round(float(last_ma60), 2),
                'ma20_dev': round(float(ma20_deviation * 100), 2),
                'rsi14': round(float(last_rsi), 2),
                'volume': int(last_vol),
                'vol_ma5': int(round(last_vol_ma5)),
            }

        except Exception:
            return False


@register_strategy
class OversoldReboundStrategy(TechnicalStrategy):
    """
    超跌反弹买入策略

    适用场景：市场恐慌导致的情绪错杀，基本面未变的优质股

    买入条件（全部满足）：
    1. RSI(14) < 30（超卖状态）
    2. 股价曾跌破布林下轨
    3. 当日收盘站回布林下轨之上（修复信号）
    4. 当日为阳线（收盘价 > 开盘价）
    5. 成交量放大（> 5日均量 * 1.2）

    逻辑解释：
    - RSI超卖表明短期跌幅过大
    - 跌破布林下轨是极端超卖
    - 收回下轨+放量阳线表明资金介入
    """
    name = "oversold_rebound"
    cn_name = "超跌反弹"
    default_threshold = 30
    description = "RSI超卖后放量反弹，价格收回布林下轨"

    def check(self, code_name, data, date=None, **kwargs):
        data = self.prepare_data(code_name, data, date)
        if data is None or len(data) < self.threshold:
            return False

        try:
            close = data['close'].values
            open_price = data['open'].values
            low = data['low'].values
            volume = data['volume'].values

            # 计算RSI
            rsi = tl.RSI(close, timeperiod=14)

            # 计算布林带
            upper, middle, lower = tl.BBANDS(close, timeperiod=20, nbdevup=2, nbdevdn=2)

            # 计算成交量均线
            vol_ma5 = tl.MA(volume.astype(float), timeperiod=5)

            # 获取最新数据
            last_close = close[-1]
            last_open = open_price[-1]
            last_rsi = rsi[-1]
            last_lower = lower[-1]
            last_vol = volume[-1]
            last_vol_ma5 = vol_ma5[-1]

            # 处理NaN值
            if np.isnan(last_rsi) or np.isnan(last_lower) or np.isnan(last_vol_ma5):
                return False
            if last_vol_ma5 == 0:
                return False

            # 条件1: RSI < 30（超卖）
            if last_rsi >= 30:
                return False

            # 条件2: 最近5日内价格接近或跌破布林下轨（低于下轨+10%范围内）
            recent_near_lower = False
            for i in range(-5, 0):
                if len(low) > abs(i) and len(lower) > abs(i):
                    if not np.isnan(lower[i]):
                        # 价格低于布林下轨的110%视为接近下轨
                        if low[i] < lower[i] * 1.1:
                            recent_near_lower = True
                            break
            if not recent_near_lower:
                return False

            # 条件3: 当日收盘站回布林下轨之上
            if last_close < last_lower:
                return False

            # 条件4: 当日为阳线
            if last_close <= last_open:
                return False

            # 条件5: 放量（成交量 > 5日均量 * 1.2）
            if last_vol < last_vol_ma5 * 1.2:
                return False

            p_change = data.iloc[-1]['p_change'] if 'p_change' in data.columns else 0.0
            return {
                'p_change': round(float(p_change), 2),
                'close': round(float(last_close), 2),
                'rsi14': round(float(last_rsi), 2),
                'boll_lower': round(float(last_lower), 2),
                'volume': int(last_vol),
                'vol_ma5': int(round(last_vol_ma5)),
            }

        except Exception:
            return False


@register_strategy
class BreakoutConfirmStrategy(TechnicalStrategy):
    """
    突破确认买入策略

    适用场景：横盘整理后的放量突破，适合核心资产

    买入条件（全部满足）：
    1. 过去40个交易日振幅较小（整理形态）
    2. 当日收盘创近40日新高
    3. 当日成交量 >= 20日均量 * 1.5（放量突破）
    4. 当日涨幅 > 2%（有效突破）
    5. 收盘价 > MA60（站上长期均线）

    逻辑解释：
    - 长期横盘积蓄能量
    - 放量突破新高表明主力入场
    - 站上MA60确认趋势
    """
    name = "breakout_confirm"
    cn_name = "突破确认"
    default_threshold = 60
    description = "横盘整理后放量突破创新高，站上MA60"

    def check(self, code_name, data, date=None, **kwargs):
        data = self.prepare_data(code_name, data, date)
        if data is None or len(data) < self.threshold:
            return False

        try:
            close = data['close'].values
            high = data['high'].values
            low = data['low'].values
            volume = data['volume'].values

            # 计算MA60
            ma60 = tl.MA(close, timeperiod=60)

            # 计算成交量均线
            vol_ma20 = tl.MA(volume.astype(float), timeperiod=20)

            # 获取最新数据
            last_close = close[-1]
            last_ma60 = ma60[-1]
            last_vol = volume[-1]
            last_vol_ma20 = vol_ma20[-1]

            # 处理NaN值
            if np.isnan(last_ma60) or np.isnan(last_vol_ma20):
                return False
            if last_vol_ma20 == 0:
                return False

            # 计算40日区间
            period = min(40, len(close) - 1)
            recent_close = close[-period-1:-1]  # 不包含今天
            recent_high = high[-period-1:-1]
            recent_low = low[-period-1:-1]

            if len(recent_close) < period:
                return False

            # 条件1: 过去40日振幅较小（整理形态）
            period_high = np.max(recent_high)
            period_low = np.min(recent_low)
            if period_low == 0:
                return False
            amplitude = (period_high - period_low) / period_low

            # 振幅小于25%视为整理
            if amplitude > 0.25:
                return False

            # 条件2: 当日收盘创近40日新高
            period_max_close = np.max(recent_close)
            if last_close <= period_max_close:
                return False

            # 条件3: 放量突破（成交量 >= 20日均量 * 1.5）
            if last_vol < last_vol_ma20 * 1.5:
                return False

            # 条件4: 当日涨幅 > 2%
            prev_close = close[-2] if len(close) > 1 else close[-1]
            if prev_close == 0:
                return False
            pct_change = (last_close - prev_close) / prev_close * 100
            if pct_change <= 2:
                return False

            # 条件5: 收盘价 > MA60
            if last_close <= last_ma60:
                return False

            p_change_val = data.iloc[-1]['p_change'] if 'p_change' in data.columns else 0.0
            return {
                'p_change': round(float(p_change_val), 2),
                'close': round(float(last_close), 2),
                'ma60': round(float(last_ma60), 2),
                'amplitude': round(float(amplitude * 100), 2),
                'period_max': round(float(period_max_close), 2),
                'pct_change': round(float(pct_change), 2),
                'volume': int(last_vol),
                'vol_ma20': int(round(last_vol_ma20)),
            }

        except Exception:
            return False


# 兼容性函数 - 供旧代码调用
def check_trend_pullback(code_name, data, date=None, threshold=60):
    """趋势回调策略检查函数（兼容旧接口）"""
    strategy = TrendPullbackStrategy(threshold=threshold)
    return strategy.check(code_name, data, date)


def check_oversold_rebound(code_name, data, date=None, threshold=30):
    """超跌反弹策略检查函数（兼容旧接口）"""
    strategy = OversoldReboundStrategy(threshold=threshold)
    return strategy.check(code_name, data, date)


def check_breakout_confirm(code_name, data, date=None, threshold=60):
    """突破确认策略检查函数（兼容旧接口）"""
    strategy = BreakoutConfirmStrategy(threshold=threshold)
    return strategy.check(code_name, data, date)
