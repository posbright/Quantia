#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
形态策略模块
"""

from .pattern_strategies import (
    BreakthroughPlatformStrategy,
    ParkingApronStrategy,
    HighTightFlagStrategy,
    LowBacktraceIncreaseStrategy,
    check_breakthrough,
    check_parking,
    check_high_tight,
    check_low_backtrace
)

__all__ = [
    'BreakthroughPlatformStrategy',
    'ParkingApronStrategy',
    'HighTightFlagStrategy',
    'LowBacktraceIncreaseStrategy',
    'check_breakthrough',
    'check_parking',
    'check_high_tight',
    'check_low_backtrace'
]
