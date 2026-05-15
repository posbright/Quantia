#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基本面策略模块

提供长期价值投资所需的基本面筛选和护城河评估工具。

包含：
- FundamentalFilter: 多层次基本面筛选器
- MoatScorer: 护城河评分器
- MoatScorecard: 护城河评分卡数据结构
- MoatAIService: AI辅助护城河评估服务
- 策略类: ValueInvestStrategy, GrowthInvestStrategy, MoatStrategy, DividendGrowthStrategy
"""

from .fundamental_filter import (
    FundamentalFilter,
    FundamentalCriteria,
    MoatScorer,
    MoatScore,
    FilterLevel,
    filter_value_stocks,
    score_stocks,
    get_top_moat_stocks
)

from .moat_model import (
    MoatCategory,
    RiskLevel,
    QuantitativeMetric,
    QualitativeAssessment,
    RiskFactor,
    MoatScorecard,
    AIAnalysisRequest,
    AIAnalysisResult,
    create_default_scorecard,
    get_threshold_config,
    SCORING_THRESHOLDS
)

from .fundamental_strategies import (
    ValueInvestStrategy,
    GrowthInvestStrategy,
    MoatStrategy,
    DividendGrowthStrategy
)

from .moat_ai_service import (
    MoatAIService,
    MoatAIConfig,
    generate_moat_report
)

__all__ = [
    # 筛选器
    'FundamentalFilter',
    'FundamentalCriteria',
    'MoatScorer',
    'MoatScore',
    'FilterLevel',
    
    # 数据模型
    'MoatCategory',
    'RiskLevel',
    'QuantitativeMetric',
    'QualitativeAssessment',
    'RiskFactor',
    'MoatScorecard',
    'AIAnalysisRequest',
    'AIAnalysisResult',
    
    # AI服务
    'MoatAIService',
    'MoatAIConfig',
    'generate_moat_report',
    
    # 策略类
    'ValueInvestStrategy',
    'GrowthInvestStrategy',
    'MoatStrategy',
    'DividendGrowthStrategy',
    
    # 便捷函数
    'filter_value_stocks',
    'score_stocks',
    'get_top_moat_stocks',
    'create_default_scorecard',
    'get_threshold_config',
    
    # 配置
    'SCORING_THRESHOLDS'
]
