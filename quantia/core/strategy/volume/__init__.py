#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
成交量策略模块
"""

from .volume_strategies import (
    VolumeIncreaseStrategy,
    ClimaxLimitdownStrategy,
    check_volume,
    check as check_climax
)

__all__ = [
    'VolumeIncreaseStrategy',
    'ClimaxLimitdownStrategy',
    'check_volume',
    'check_climax'
]
