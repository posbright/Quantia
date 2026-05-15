#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
选股策略模块

策略分类:
- technical: 技术指标策略 (均线、ATR等)
- volume: 成交量策略 (放量、缩量等)
- pattern: 形态策略 (突破、旗形等)

使用方法:
1. 通过类使用:
    from quantia.core.strategy import VolumeIncreaseStrategy
    strategy = VolumeIncreaseStrategy()
    result = strategy.check(code_name, data, date)

2. 通过兼容函数使用(旧接口):
    from quantia.core.strategy import enter
    result = enter.check_volume(code_name, data, date)

3. 通过注册表使用:
    from quantia.core.strategy.base import get_strategy
    strategy = get_strategy('enter')()
    result = strategy.check(code_name, data, date)
"""

__author__ = 'Quantia'
__date__ = '2026/02/14'

# 导入基类
from .base import (
    BaseStrategy,
    TechnicalStrategy,
    VolumeStrategy,
    TrendStrategy,
    PatternStrategy,
    register_strategy,
    get_strategy,
    get_all_strategies,
    get_strategies_by_category,
    STRATEGY_REGISTRY
)

# 导入技术指标策略
from .technical import (
    MABullishStrategy,
    MA250PullbackStrategy,
    TurtleTradingStrategy,
    LowATRGrowthStrategy
)

# 导入成交量策略
from .volume import (
    VolumeIncreaseStrategy,
    ClimaxLimitdownStrategy
)

# 导入形态策略
from .pattern import (
    BreakthroughPlatformStrategy,
    ParkingApronStrategy,
    HighTightFlagStrategy,
    LowBacktraceIncreaseStrategy
)

# 兼容性模块导入 - 保持旧代码可用
from . import enter
from . import turtle_trade
from . import climax_limitdown
from . import low_atr
from . import backtrace_ma250
from . import breakthrough_platform
from . import parking_apron
from . import low_backtrace_increase
from . import keep_increasing
from . import high_tight_flag

__all__ = [
    # 基类
    'BaseStrategy',
    'TechnicalStrategy',
    'VolumeStrategy',
    'TrendStrategy',
    'PatternStrategy',
    'register_strategy',
    'get_strategy',
    'get_all_strategies',
    'get_strategies_by_category',
    'STRATEGY_REGISTRY',

    # 技术策略
    'MABullishStrategy',
    'MA250PullbackStrategy',
    'TurtleTradingStrategy',
    'LowATRGrowthStrategy',

    # 成交量策略
    'VolumeIncreaseStrategy',
    'ClimaxLimitdownStrategy',

    # 形态策略
    'BreakthroughPlatformStrategy',
    'ParkingApronStrategy',
    'HighTightFlagStrategy',
    'LowBacktraceIncreaseStrategy',

    # 兼容性模块
    'enter',
    'turtle_trade',
    'climax_limitdown',
    'low_atr',
    'backtrace_ma250',
    'breakthrough_platform',
    'parking_apron',
    'low_backtrace_increase',
    'keep_increasing',
    'high_tight_flag'
]
