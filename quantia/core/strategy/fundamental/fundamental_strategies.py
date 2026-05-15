#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基本面选股策略

提供可注册到系统的基本面选股策略:
1. 价值投资策略 - 筛选高质量价值股
2. 成长投资策略 - 筛选高成长潜力股
3. 护城河策略 - 筛选具有竞争壁垒的公司
"""

import logging
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import datetime

from quantia.core.strategy.base import BaseStrategy, register_strategy
from .fundamental_filter import (
    FundamentalFilter,
    FundamentalCriteria,
    MoatScorer,
    FilterLevel
)

__author__ = 'Quantia'
__date__ = '2026/02/14'


@register_strategy
class ValueInvestStrategy(BaseStrategy):
    """
    价值投资策略

    选股逻辑:
    - ROE >= 15%
    - 毛利率 >= 30%
    - 净利率 >= 10%
    - 资产负债率 < 60%
    - 每股经营现金流 > 0
    - PE在合理范围 (0-50)

    适用场景: 寻找财务健康、盈利能力强的优质公司
    """

    strategy_id = "value_invest"
    strategy_name = "价值投资策略"
    description = "筛选ROE≥15%、毛利率≥30%、净利率≥10%的优质价值股"
    category = "fundamental"

    # 策略参数
    params = {
        'min_roe': 15.0,
        'min_gross_margin': 30.0,
        'min_net_margin': 10.0,
        'max_debt_ratio': 60.0,
        'min_pe': 0.0,
        'max_pe': 50.0
    }

    def __init__(self):
        super().__init__()
        self.criteria = FundamentalCriteria(
            min_roe=self.params['min_roe'],
            min_gross_margin=self.params['min_gross_margin'],
            min_net_margin=self.params['min_net_margin'],
            max_debt_ratio=self.params['max_debt_ratio'],
            min_pe_ttm=self.params['min_pe'],
            max_pe_ttm=self.params['max_pe']
        )
        self.filter = FundamentalFilter(self.criteria)

    def check(self, stock_data: pd.Series) -> bool:
        """检查单只股票是否符合价值投资标准"""
        try:
            # ROE检查
            roe = stock_data.get('roe_weight', 0)
            if pd.isna(roe) or roe < self.params['min_roe']:
                return False

            # 毛利率检查
            gpr = stock_data.get('sale_gpr', 0)
            if pd.isna(gpr) or gpr < self.params['min_gross_margin']:
                return False

            # 净利率检查
            npr = stock_data.get('sale_npr', 0)
            if pd.isna(npr) or npr < self.params['min_net_margin']:
                return False

            # 资产负债率检查
            debt = stock_data.get('debt_asset_ratio', 100)
            if pd.isna(debt) or debt >= self.params['max_debt_ratio']:
                return False

            # 现金流检查
            cashflow = stock_data.get('per_netcash_operate', 0)
            if pd.isna(cashflow) or cashflow <= 0:
                return False

            # PE检查
            pe = stock_data.get('pe9', 0)
            if pd.isna(pe) or pe <= self.params['min_pe'] or pe > self.params['max_pe']:
                return False

            return True

        except Exception as e:
            logging.error(f"价值投资策略检查异常", exc_info=True)
            return False

    def filter_stocks(self, data: pd.DataFrame) -> pd.DataFrame:
        """批量筛选符合价值投资标准的股票"""
        levels = [
            FilterLevel.SAFETY,
            FilterLevel.PROFITABILITY,
            FilterLevel.VALUATION
        ]
        return self.filter.filter_stocks(data, levels)


@register_strategy
class GrowthInvestStrategy(BaseStrategy):
    """
    成长投资策略

    选股逻辑:
    - 营收3年复合增长率 > 15%
    - 净利润3年复合增长率 > 15%
    - ROE >= 12%
    - 毛利率 >= 25%
    - 资产负债率 < 65%

    适用场景: 寻找高速成长的成长股
    """

    strategy_id = "growth_invest"
    strategy_name = "成长投资策略"
    description = "筛选营收和利润3年复合增长率>15%的高成长股"
    category = "fundamental"

    params = {
        'min_revenue_growth': 15.0,
        'min_profit_growth': 15.0,
        'min_roe': 12.0,
        'min_gross_margin': 25.0,
        'max_debt_ratio': 65.0
    }

    def __init__(self):
        super().__init__()
        self.criteria = FundamentalCriteria(
            min_roe=self.params['min_roe'],
            min_gross_margin=self.params['min_gross_margin'],
            max_debt_ratio=self.params['max_debt_ratio'],
            min_revenue_growth_3y=self.params['min_revenue_growth'],
            min_profit_growth_3y=self.params['min_profit_growth']
        )
        self.filter = FundamentalFilter(self.criteria)

    def check(self, stock_data: pd.Series) -> bool:
        """检查单只股票是否符合成长投资标准"""
        try:
            # 营收增长率检查
            revenue_growth = stock_data.get('income_growthrate_3y', 0)
            if pd.isna(revenue_growth) or revenue_growth < self.params['min_revenue_growth']:
                return False

            # 利润增长率检查
            profit_growth = stock_data.get('netprofit_growthrate_3y', 0)
            if pd.isna(profit_growth) or profit_growth < self.params['min_profit_growth']:
                return False

            # ROE检查
            roe = stock_data.get('roe_weight', 0)
            if pd.isna(roe) or roe < self.params['min_roe']:
                return False

            # 毛利率检查
            gpr = stock_data.get('sale_gpr', 0)
            if pd.isna(gpr) or gpr < self.params['min_gross_margin']:
                return False

            # 资产负债率检查
            debt = stock_data.get('debt_asset_ratio', 100)
            if pd.isna(debt) or debt >= self.params['max_debt_ratio']:
                return False

            return True

        except Exception as e:
            logging.error(f"成长投资策略检查异常", exc_info=True)
            return False

    def filter_stocks(self, data: pd.DataFrame) -> pd.DataFrame:
        """批量筛选符合成长投资标准的股票"""
        levels = [
            FilterLevel.SAFETY,
            FilterLevel.PROFITABILITY,
            FilterLevel.GROWTH
        ]
        return self.filter.filter_stocks(data, levels)


@register_strategy
class MoatStrategy(BaseStrategy):
    """
    护城河策略

    选股逻辑:
    - 护城河评分 >= 65分
    - ROE >= 15%
    - 毛利率 >= 35%
    - 资产负债率 < 55%
    - 连续3年盈利增长

    适用场景: 寻找具有持久竞争优势的护城河企业
    """

    strategy_id = "moat_invest"
    strategy_name = "护城河策略"
    description = "筛选护城河评分≥65分、具有持久竞争优势的企业"
    category = "fundamental"

    params = {
        'min_moat_score': 65.0,
        'min_roe': 15.0,
        'min_gross_margin': 35.0,
        'max_debt_ratio': 55.0
    }

    def __init__(self):
        super().__init__()
        self.scorer = MoatScorer()
        self.criteria = FundamentalCriteria(
            min_roe=self.params['min_roe'],
            min_gross_margin=self.params['min_gross_margin'],
            max_debt_ratio=self.params['max_debt_ratio']
        )
        self.filter = FundamentalFilter(self.criteria)

    def check(self, stock_data: pd.Series) -> bool:
        """检查单只股票是否符合护城河标准"""
        try:
            # 基本面预筛
            roe = stock_data.get('roe_weight', 0)
            if pd.isna(roe) or roe < self.params['min_roe']:
                return False

            gpr = stock_data.get('sale_gpr', 0)
            if pd.isna(gpr) or gpr < self.params['min_gross_margin']:
                return False

            debt = stock_data.get('debt_asset_ratio', 100)
            if pd.isna(debt) or debt >= self.params['max_debt_ratio']:
                return False

            # 护城河评分
            score = self.scorer.calculate_score(stock_data)
            if score.total_score < self.params['min_moat_score']:
                return False

            return True

        except Exception as e:
            logging.error(f"护城河策略检查异常", exc_info=True)
            return False

    def filter_stocks(self, data: pd.DataFrame) -> pd.DataFrame:
        """批量筛选符合护城河标准的股票"""
        # 先进行基本面筛选
        levels = [
            FilterLevel.SAFETY,
            FilterLevel.PROFITABILITY
        ]
        filtered = self.filter.filter_stocks(data, levels)

        if filtered is None or len(filtered) == 0:
            return filtered

        # 计算护城河评分并筛选
        scored = self.scorer.batch_score(filtered)
        result = scored[scored['moat_score'] >= self.params['min_moat_score']]

        # 按评分排序
        result = result.sort_values('moat_score', ascending=False)

        return result


@register_strategy
class DividendGrowthStrategy(BaseStrategy):
    """
    股息成长策略

    选股逻辑:
    - 股息率 > 2%
    - ROE >= 12%
    - 利润增长率 > 5%
    - 资产负债率 < 60%
    - 每股现金流 > 每股股息

    适用场景: 寻找稳定分红且具有成长性的防御型股票
    """

    strategy_id = "dividend_growth"
    strategy_name = "股息成长策略"
    description = "筛选股息率>2%、且利润持续增长的分红成长股"
    category = "fundamental"

    params = {
        'min_dividend_yield': 2.0,
        'min_roe': 12.0,
        'min_profit_growth': 5.0,
        'max_debt_ratio': 60.0
    }

    def check(self, stock_data: pd.Series) -> bool:
        """检查单只股票是否符合股息成长标准"""
        try:
            # 股息率检查
            dividend = stock_data.get('zxgxl', 0)
            if pd.isna(dividend) or dividend < self.params['min_dividend_yield']:
                return False

            # ROE检查
            roe = stock_data.get('roe_weight', 0)
            if pd.isna(roe) or roe < self.params['min_roe']:
                return False

            # 利润增长检查
            profit_growth = stock_data.get('netprofit_growthrate_3y', 0)
            if pd.isna(profit_growth) or profit_growth < self.params['min_profit_growth']:
                return False

            # 资产负债率检查
            debt = stock_data.get('debt_asset_ratio', 100)
            if pd.isna(debt) or debt >= self.params['max_debt_ratio']:
                return False

            # 现金流检查
            cashflow = stock_data.get('per_netcash_operate', 0)
            if pd.isna(cashflow) or cashflow <= 0:
                return False

            return True

        except Exception as e:
            logging.error(f"股息成长策略检查异常", exc_info=True)
            return False
