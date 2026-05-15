#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略基类模块

提供所有选股策略的基类和通用工具方法。
"""

from abc import ABC, abstractmethod
from typing import Optional, Tuple, Any
import numpy as np
import talib as tl
import pandas as pd
from datetime import datetime

__author__ = 'Quantia'
__date__ = '2026/02/14'


class BaseStrategy(ABC):
    """
    选股策略基类

    所有选股策略都应该继承这个基类，并实现 check 方法。
    """

    # 策略名称
    name: str = "base"
    # 策略中文名
    cn_name: str = "基础策略"
    # 默认数据长度阈值
    default_threshold: int = 60
    # 策略分类
    category: str = "other"
    # 策略描述
    description: str = ""

    def __init__(self, threshold: int = None):
        """
        初始化策略

        Args:
            threshold: 数据长度阈值，默认使用类属性 default_threshold
        """
        self.threshold = threshold or self.default_threshold

    @abstractmethod
    def check(self, code_name: Tuple[str, str], data: pd.DataFrame,
              date: datetime = None, **kwargs) -> bool:
        """
        检查股票是否符合策略条件

        Args:
            code_name: (date, code) 股票标识元组
            data: 股票历史K线数据
            date: 检查日期，默认为None使用code_name中的日期
            **kwargs: 额外参数

        Returns:
            bool: 是否符合策略条件
        """
        pass

    def prepare_data(self, code_name: Tuple[str, str], data: pd.DataFrame,
                     date: datetime = None) -> Optional[pd.DataFrame]:
        """
        准备数据，过滤到指定日期之前的数据

        Args:
            code_name: (date, code) 股票标识元组
            data: 股票历史K线数据
            date: 检查日期

        Returns:
            过滤后的数据，如果数据不足返回None
        """
        if date is None:
            end_date = code_name[0]
        else:
            end_date = date.strftime("%Y-%m-%d")

        if end_date is not None:
            # 统一 date 类型，避免 datetime.date vs str 比较异常
            if not pd.api.types.is_datetime64_any_dtype(data['date']):
                data = data.copy()
                data['date'] = pd.to_datetime(data['date'])
            if not isinstance(end_date, pd.Timestamp):
                end_date = pd.Timestamp(end_date)
            mask = (data['date'] <= end_date)
            data = data.loc[mask].copy()

        if len(data.index) < self.threshold:
            return None

        return data

    def __call__(self, code_name: Tuple[str, str], data: pd.DataFrame,
                 date: datetime = None, **kwargs) -> bool:
        """
        使策略实例可直接调用
        """
        return self.check(code_name, data, date, **kwargs)


class TechnicalStrategy(BaseStrategy):
    """技术指标策略基类"""
    category = "technical"

    @staticmethod
    def calc_ma(data: pd.DataFrame, column: str = 'close', period: int = 5) -> np.ndarray:
        """计算移动平均线"""
        ma = tl.MA(data[column].values, timeperiod=period)
        ma[np.isnan(ma)] = 0.0
        return ma

    @staticmethod
    def calc_ema(data: pd.DataFrame, column: str = 'close', period: int = 5) -> np.ndarray:
        """计算指数移动平均线"""
        ema = tl.EMA(data[column].values, timeperiod=period)
        ema[np.isnan(ema)] = 0.0
        return ema

    @staticmethod
    def calc_atr(data: pd.DataFrame, period: int = 14) -> np.ndarray:
        """计算ATR"""
        atr = tl.ATR(data['high'].values, data['low'].values,
                     data['close'].values, timeperiod=period)
        atr[np.isnan(atr)] = 0.0
        return atr


class VolumeStrategy(BaseStrategy):
    """成交量策略基类"""
    category = "volume"

    @staticmethod
    def calc_vol_ma(data: pd.DataFrame, period: int = 5) -> np.ndarray:
        """计算成交量移动平均"""
        vol_ma = tl.MA(data['volume'].values, timeperiod=period)
        vol_ma[np.isnan(vol_ma)] = 0.0
        return vol_ma

    @staticmethod
    def calc_amount(data: pd.DataFrame, row_index: int = -1) -> float:
        """计算成交额"""
        close = data.iloc[row_index]['close']
        volume = data.iloc[row_index]['volume']
        return close * volume


class TrendStrategy(BaseStrategy):
    """趋势策略基类"""
    category = "trend"


class PatternStrategy(BaseStrategy):
    """形态策略基类"""
    category = "pattern"


# 策略注册表
STRATEGY_REGISTRY = {}


def register_strategy(cls):
    """
    策略注册装饰器

    用法:
        @register_strategy
        class MyStrategy(BaseStrategy):
            name = "my_strategy"
            ...
    """
    STRATEGY_REGISTRY[cls.name] = cls
    return cls


def get_strategy(name: str) -> BaseStrategy:
    """
    通过名称获取策略类

    Args:
        name: 策略名称

    Returns:
        策略类
    """
    if name not in STRATEGY_REGISTRY:
        raise ValueError(f"策略 '{name}' 未注册")
    return STRATEGY_REGISTRY[name]


def get_all_strategies():
    """获取所有注册的策略"""
    return STRATEGY_REGISTRY.copy()


def get_strategies_by_category(category: str):
    """
    按分类获取策略

    Args:
        category: 策略分类 (technical, volume, trend, pattern, other)
    """
    return {name: cls for name, cls in STRATEGY_REGISTRY.items()
            if cls.category == category}
