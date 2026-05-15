#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基本面筛选策略模块

基于优化后的长期价值投资策略，提供多层次的基本面筛选：
1. 财务安全过滤 - 排除财务风险
2. 盈利能力筛选 - 选出高质量公司
3. 成长质量筛选 - 确保可持续增长
4. 竞争壁垒评估 - 识别护城河
5. 估值约束 - 合理买入价格

数据来源：东方财富选股器 (cn_stock_selection 表)
"""

import logging
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

__author__ = 'Quantia'
__date__ = '2026/02/14'


class FilterLevel(Enum):
    """筛选层级"""
    SAFETY = 1      # 财务安全
    PROFITABILITY = 2   # 盈利能力
    GROWTH = 3      # 成长质量
    MOAT = 4        # 竞争壁垒
    VALUATION = 5   # 估值约束


@dataclass
class FundamentalCriteria:
    """基本面筛选条件配置"""

    # ===== 第一层：财务安全过滤 =====
    # 有息负债率 < 40%（用资产负债率代替，更严格）
    max_debt_ratio: float = 60.0
    # 商誉/净资产 < 20%（需额外计算，暂用资产负债率辅助）
    # 经营现金流连续3年为正（用每股经营现金流>0代替）
    min_cashflow_per_share: float = 0.0

    # ===== 第二层：盈利能力筛选 =====
    # ROE(加权) >= 15%
    min_roe: float = 15.0
    # 毛利率 >= 30%
    min_gross_margin: float = 30.0
    # 净利率 >= 10%
    min_net_margin: float = 10.0
    # ROA >= 5%
    min_roa: float = 5.0

    # ===== 第三层：成长质量筛选 =====
    # 营收3年复合增长率 > 10%
    min_revenue_growth_3y: float = 10.0
    # 净利润3年复合增长率 > 营收增长率（用>10%代替）
    min_profit_growth_3y: float = 10.0
    # 扣非净利润增长率 > 0
    min_deduct_profit_growth: float = 0.0

    # ===== 第四层：竞争壁垒评估 =====
    # 上市时间 >= 5年（筛选经过市场验证的公司）
    min_listing_years: int = 5
    # 流动比率 >= 1.0（短期偿债能力）
    min_current_ratio: float = 1.0
    # 速动比率 >= 0.8
    min_quick_ratio: float = 0.8

    # ===== 第五层：估值约束 =====
    # 市盈率TTM <= 50（排除泡沫股）
    max_pe_ttm: float = 50.0
    # 市盈率TTM > 0（排除亏损股）
    min_pe_ttm: float = 0.0
    # 市净率MRQ <= 10
    max_pb_mrq: float = 10.0
    # PEG <= 1.5（仅对高成长股）
    max_peg: float = 1.5

    # ===== 可选加分项 =====
    # 股息率 > 0（有分红意识）
    prefer_dividend: bool = True
    min_dividend_yield: float = 0.0

    # 户均持股数增长（筹码集中）
    prefer_concentrated: bool = True


@dataclass
class MoatScore:
    """护城河评分结果"""
    total_score: float = 0.0          # 总分 (0-100)
    profitability_score: float = 0.0  # 盈利能力得分 (0-25)
    stability_score: float = 0.0      # 稳定性得分 (0-20)
    growth_score: float = 0.0         # 成长能力得分 (0-20)
    efficiency_score: float = 0.0     # 经营效率得分 (0-15)
    safety_score: float = 0.0         # 财务安全得分 (0-20)

    grade: str = 'D'  # 评级: A/B/C/D
    moat_type: List[str] = field(default_factory=list)  # 护城河类型
    risk_factors: List[str] = field(default_factory=list)  # 风险因素

    def calculate_grade(self):
        """根据总分计算评级"""
        if self.total_score >= 80:
            self.grade = 'A'
        elif self.total_score >= 65:
            self.grade = 'B'
        elif self.total_score >= 50:
            self.grade = 'C'
        else:
            self.grade = 'D'


class FundamentalFilter:
    """
    基本面筛选器

    使用方法:
        filter = FundamentalFilter()
        result = filter.filter_stocks(stock_data)

    或者自定义条件:
        criteria = FundamentalCriteria(min_roe=20.0, min_gross_margin=40.0)
        filter = FundamentalFilter(criteria)
        result = filter.filter_stocks(stock_data)
    """

    def __init__(self, criteria: FundamentalCriteria = None):
        self.criteria = criteria or FundamentalCriteria()

    def filter_stocks(self, data: pd.DataFrame,
                     levels: List[FilterLevel] = None) -> pd.DataFrame:
        """
        多层次基本面筛选

        Args:
            data: 股票数据DataFrame（需包含财务指标列）
            levels: 要应用的筛选层级列表，默认全部

        Returns:
            筛选后的DataFrame
        """
        if data is None or len(data) == 0:
            return data

        if levels is None:
            levels = list(FilterLevel)

        result = data.copy()

        for level in levels:
            before_count = len(result)

            if level == FilterLevel.SAFETY:
                result = self._filter_safety(result)
            elif level == FilterLevel.PROFITABILITY:
                result = self._filter_profitability(result)
            elif level == FilterLevel.GROWTH:
                result = self._filter_growth(result)
            elif level == FilterLevel.MOAT:
                result = self._filter_moat(result)
            elif level == FilterLevel.VALUATION:
                result = self._filter_valuation(result)

            after_count = len(result)
            logging.info(f"第{level.value}层筛选({level.name}): {before_count} -> {after_count}")

        return result

    def _filter_safety(self, data: pd.DataFrame) -> pd.DataFrame:
        """第一层：财务安全过滤"""
        result = data.copy()

        # 资产负债率 < max_debt_ratio
        if 'debt_asset_ratio' in result.columns:
            result = result[
                (result['debt_asset_ratio'].notna()) &
                (result['debt_asset_ratio'] < self.criteria.max_debt_ratio)
            ]

        # 每股经营现金流 > 0
        if 'per_netcash_operate' in result.columns:
            result = result[
                (result['per_netcash_operate'].notna()) &
                (result['per_netcash_operate'] > self.criteria.min_cashflow_per_share)
            ]

        return result

    def _filter_profitability(self, data: pd.DataFrame) -> pd.DataFrame:
        """第二层：盈利能力筛选"""
        result = data.copy()

        # ROE >= min_roe
        if 'roe_weight' in result.columns:
            result = result[
                (result['roe_weight'].notna()) &
                (result['roe_weight'] >= self.criteria.min_roe)
            ]

        # 毛利率 >= min_gross_margin
        if 'sale_gpr' in result.columns:
            result = result[
                (result['sale_gpr'].notna()) &
                (result['sale_gpr'] >= self.criteria.min_gross_margin)
            ]

        # 净利率 >= min_net_margin
        if 'sale_npr' in result.columns:
            result = result[
                (result['sale_npr'].notna()) &
                (result['sale_npr'] >= self.criteria.min_net_margin)
            ]

        # ROA >= min_roa
        if 'jroa' in result.columns:
            result = result[
                (result['jroa'].notna()) &
                (result['jroa'] >= self.criteria.min_roa)
            ]

        return result

    def _filter_growth(self, data: pd.DataFrame) -> pd.DataFrame:
        """第三层：成长质量筛选"""
        result = data.copy()

        # 营收3年复合增长率 > min_revenue_growth_3y
        if 'income_growthrate_3y' in result.columns:
            result = result[
                (result['income_growthrate_3y'].notna()) &
                (result['income_growthrate_3y'] > self.criteria.min_revenue_growth_3y)
            ]

        # 净利润3年复合增长率 > min_profit_growth_3y
        if 'netprofit_growthrate_3y' in result.columns:
            result = result[
                (result['netprofit_growthrate_3y'].notna()) &
                (result['netprofit_growthrate_3y'] > self.criteria.min_profit_growth_3y)
            ]

        # 扣非净利润增长率 > 0
        if 'deduct_netprofit_growthrate' in result.columns:
            result = result[
                (result['deduct_netprofit_growthrate'].notna()) &
                (result['deduct_netprofit_growthrate'] > self.criteria.min_deduct_profit_growth)
            ]

        return result

    def _filter_moat(self, data: pd.DataFrame) -> pd.DataFrame:
        """第四层：竞争壁垒评估"""
        result = data.copy()

        # 流动比率 >= min_current_ratio
        if 'current_ratio' in result.columns:
            result = result[
                (result['current_ratio'].notna()) &
                (result['current_ratio'] >= self.criteria.min_current_ratio)
            ]

        # 速动比率 >= min_quick_ratio
        if 'speed_ratio' in result.columns:
            result = result[
                (result['speed_ratio'].notna()) &
                (result['speed_ratio'] >= self.criteria.min_quick_ratio)
            ]

        # 上市时间筛选（如果有listing_date字段）
        # 需要额外计算上市年限

        return result

    def _filter_valuation(self, data: pd.DataFrame) -> pd.DataFrame:
        """第五层：估值约束"""
        result = data.copy()

        # 市盈率TTM在合理范围
        if 'pe9' in result.columns:
            result = result[
                (result['pe9'].notna()) &
                (result['pe9'] > self.criteria.min_pe_ttm) &
                (result['pe9'] <= self.criteria.max_pe_ttm)
            ]

        # 市净率MRQ <= max_pb_mrq
        if 'pbnewmrq' in result.columns:
            result = result[
                (result['pbnewmrq'].notna()) &
                (result['pbnewmrq'] > 0) &
                (result['pbnewmrq'] <= self.criteria.max_pb_mrq)
            ]

        return result


class MoatScorer:
    """
    护城河评分器

    评分维度：
    1. 盈利能力 (25分) - ROE、毛利率、净利率
    2. 稳定性 (20分) - 盈利波动、毛利率稳定性
    3. 成长能力 (20分) - 营收增长、利润增长
    4. 经营效率 (15分) - ROA、周转率
    5. 财务安全 (20分) - 负债率、现金流

    使用方法:
        scorer = MoatScorer()
        score = scorer.calculate_score(stock_row)
        print(f"总分: {score.total_score}, 评级: {score.grade}")
    """

    def __init__(self):
        pass

    def calculate_score(self, stock: pd.Series) -> MoatScore:
        """
        计算单只股票的护城河评分

        Args:
            stock: 股票数据Series（包含财务指标）

        Returns:
            MoatScore对象
        """
        score = MoatScore()

        # 1. 盈利能力得分 (0-25分)
        score.profitability_score = self._score_profitability(stock)

        # 2. 稳定性得分 (0-20分)
        score.stability_score = self._score_stability(stock)

        # 3. 成长能力得分 (0-20分)
        score.growth_score = self._score_growth(stock)

        # 4. 经营效率得分 (0-15分)
        score.efficiency_score = self._score_efficiency(stock)

        # 5. 财务安全得分 (0-20分)
        score.safety_score = self._score_safety(stock)

        # 计算总分
        score.total_score = (
            score.profitability_score +
            score.stability_score +
            score.growth_score +
            score.efficiency_score +
            score.safety_score
        )

        # 计算评级
        score.calculate_grade()

        # 识别护城河类型
        score.moat_type = self._identify_moat_type(stock, score)

        # 识别风险因素
        score.risk_factors = self._identify_risks(stock)

        return score

    def _score_profitability(self, stock: pd.Series) -> float:
        """盈利能力评分 (0-25分)"""
        score = 0.0

        # ROE评分 (0-10分)
        roe = self._safe_get(stock, 'roe_weight', 0)
        if roe >= 25:
            score += 10
        elif roe >= 20:
            score += 8
        elif roe >= 15:
            score += 6
        elif roe >= 10:
            score += 4
        elif roe >= 5:
            score += 2

        # 毛利率评分 (0-8分)
        gpr = self._safe_get(stock, 'sale_gpr', 0)
        if gpr >= 50:
            score += 8
        elif gpr >= 40:
            score += 6
        elif gpr >= 30:
            score += 4
        elif gpr >= 20:
            score += 2

        # 净利率评分 (0-7分)
        npr = self._safe_get(stock, 'sale_npr', 0)
        if npr >= 20:
            score += 7
        elif npr >= 15:
            score += 5
        elif npr >= 10:
            score += 3
        elif npr >= 5:
            score += 1

        return min(score, 25)

    def _score_stability(self, stock: pd.Series) -> float:
        """稳定性评分 (0-20分)"""
        score = 0.0

        # 由于缺乏历史数据，使用当前指标估算稳定性
        # 毛利率高且ROE高 -> 可能较稳定
        gpr = self._safe_get(stock, 'sale_gpr', 0)
        roe = self._safe_get(stock, 'roe_weight', 0)

        # 高毛利率通常意味着稳定的竞争优势
        if gpr >= 40 and roe >= 15:
            score += 15
        elif gpr >= 30 and roe >= 12:
            score += 10
        elif gpr >= 20 and roe >= 8:
            score += 5

        # 股息率加分（有分红说明盈利稳定）
        dividend = self._safe_get(stock, 'zxgxl', 0)
        if dividend >= 3:
            score += 5
        elif dividend >= 1:
            score += 3

        return min(score, 20)

    def _score_growth(self, stock: pd.Series) -> float:
        """成长能力评分 (0-20分)"""
        score = 0.0

        # 营收3年复合增长率 (0-10分)
        revenue_growth = self._safe_get(stock, 'income_growthrate_3y', 0)
        if revenue_growth >= 30:
            score += 10
        elif revenue_growth >= 20:
            score += 8
        elif revenue_growth >= 15:
            score += 6
        elif revenue_growth >= 10:
            score += 4
        elif revenue_growth > 0:
            score += 2

        # 净利润3年复合增长率 (0-10分)
        profit_growth = self._safe_get(stock, 'netprofit_growthrate_3y', 0)
        if profit_growth >= 30:
            score += 10
        elif profit_growth >= 20:
            score += 8
        elif profit_growth >= 15:
            score += 6
        elif profit_growth >= 10:
            score += 4
        elif profit_growth > 0:
            score += 2

        return min(score, 20)

    def _score_efficiency(self, stock: pd.Series) -> float:
        """经营效率评分 (0-15分)"""
        score = 0.0

        # ROA评分 (0-8分)
        roa = self._safe_get(stock, 'jroa', 0)
        if roa >= 15:
            score += 8
        elif roa >= 10:
            score += 6
        elif roa >= 7:
            score += 4
        elif roa >= 5:
            score += 2

        # ROIC评分 (0-7分)
        roic = self._safe_get(stock, 'roic', 0)
        if roic >= 20:
            score += 7
        elif roic >= 15:
            score += 5
        elif roic >= 10:
            score += 3
        elif roic >= 5:
            score += 1

        return min(score, 15)

    def _score_safety(self, stock: pd.Series) -> float:
        """财务安全评分 (0-20分)"""
        score = 0.0

        # 资产负债率评分 (0-8分)，越低越好
        debt_ratio = self._safe_get(stock, 'debt_asset_ratio', 100)
        if debt_ratio < 30:
            score += 8
        elif debt_ratio < 40:
            score += 6
        elif debt_ratio < 50:
            score += 4
        elif debt_ratio < 60:
            score += 2

        # 流动比率评分 (0-6分)
        current = self._safe_get(stock, 'current_ratio', 0)
        if current >= 2:
            score += 6
        elif current >= 1.5:
            score += 4
        elif current >= 1:
            score += 2

        # 每股现金流评分 (0-6分)
        cashflow = self._safe_get(stock, 'per_netcash_operate', 0)
        if cashflow >= 1:
            score += 6
        elif cashflow >= 0.5:
            score += 4
        elif cashflow > 0:
            score += 2

        return min(score, 20)

    def _identify_moat_type(self, stock: pd.Series, score: MoatScore) -> List[str]:
        """识别护城河类型"""
        moat_types = []

        gpr = self._safe_get(stock, 'sale_gpr', 0)
        roe = self._safe_get(stock, 'roe_weight', 0)
        roic = self._safe_get(stock, 'roic', 0)

        # 高毛利率 -> 定价权/品牌护城河
        if gpr >= 40:
            moat_types.append("定价权")

        # 高ROE且高ROIC -> 可能有规模效应
        if roe >= 20 and roic >= 15:
            moat_types.append("规模效应")

        # 高毛利率且增长快 -> 可能有技术壁垒
        revenue_growth = self._safe_get(stock, 'income_growthrate_3y', 0)
        if gpr >= 35 and revenue_growth >= 20:
            moat_types.append("技术壁垒")

        # 高股息且稳定增长 -> 成熟期龙头
        dividend = self._safe_get(stock, 'zxgxl', 0)
        profit_growth = self._safe_get(stock, 'netprofit_growthrate_3y', 0)
        if dividend >= 2 and profit_growth >= 10:
            moat_types.append("成熟龙头")

        if not moat_types:
            moat_types.append("待评估")

        return moat_types

    def _identify_risks(self, stock: pd.Series) -> List[str]:
        """识别风险因素"""
        risks = []

        # 高负债风险
        debt_ratio = self._safe_get(stock, 'debt_asset_ratio', 0)
        if debt_ratio >= 60:
            risks.append("高负债")

        # 现金流风险
        cashflow = self._safe_get(stock, 'per_netcash_operate', 0)
        if cashflow <= 0:
            risks.append("现金流为负")

        # 增长放缓风险
        revenue_growth = self._safe_get(stock, 'income_growthrate_3y', 0)
        profit_growth = self._safe_get(stock, 'netprofit_growthrate_3y', 0)
        if revenue_growth < profit_growth * 0.5:
            risks.append("增长质量存疑")

        # 估值风险
        pe = self._safe_get(stock, 'pe9', 0)
        if pe > 50:
            risks.append("估值偏高")

        # 低毛利率风险
        gpr = self._safe_get(stock, 'sale_gpr', 0)
        if gpr < 15:
            risks.append("毛利率过低")

        return risks

    def _safe_get(self, stock: pd.Series, key: str, default: float = 0) -> float:
        """安全获取字段值"""
        try:
            value = stock.get(key, default)
            if pd.isna(value):
                return default
            return float(value)
        except (ValueError, TypeError):
            return default

    def batch_score(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        批量计算护城河评分

        Args:
            data: 股票数据DataFrame

        Returns:
            添加了评分列的DataFrame
        """
        if data is None or len(data) == 0:
            return data

        result = data.copy()

        scores = []
        for idx, row in result.iterrows():
            score = self.calculate_score(row)
            scores.append({
                'moat_score': score.total_score,
                'moat_grade': score.grade,
                'profitability_score': score.profitability_score,
                'stability_score': score.stability_score,
                'growth_score': score.growth_score,
                'efficiency_score': score.efficiency_score,
                'safety_score': score.safety_score,
                'moat_type': ','.join(score.moat_type),
                'risk_factors': ','.join(score.risk_factors)
            })

        score_df = pd.DataFrame(scores, index=result.index)
        result = pd.concat([result, score_df], axis=1)

        return result


# ========== 便捷函数 ==========

def filter_value_stocks(data: pd.DataFrame,
                       strict: bool = False) -> pd.DataFrame:
    """
    价值投资选股（快捷函数）

    Args:
        data: 股票数据DataFrame
        strict: 是否使用严格标准

    Returns:
        筛选后的DataFrame
    """
    if strict:
        criteria = FundamentalCriteria(
            min_roe=20.0,
            min_gross_margin=40.0,
            min_net_margin=15.0,
            min_revenue_growth_3y=15.0,
            min_profit_growth_3y=15.0,
            max_pe_ttm=40.0
        )
    else:
        criteria = FundamentalCriteria()

    filter_obj = FundamentalFilter(criteria)
    return filter_obj.filter_stocks(data)


def score_stocks(data: pd.DataFrame) -> pd.DataFrame:
    """
    护城河评分（快捷函数）

    Args:
        data: 股票数据DataFrame

    Returns:
        添加了评分的DataFrame
    """
    scorer = MoatScorer()
    return scorer.batch_score(data)


def get_top_moat_stocks(data: pd.DataFrame, top_n: int = 20) -> pd.DataFrame:
    """
    获取护城河评分最高的股票

    Args:
        data: 股票数据DataFrame
        top_n: 返回数量

    Returns:
        评分最高的top_n只股票
    """
    scored = score_stocks(data)
    scored = scored.sort_values('moat_score', ascending=False)
    return scored.head(top_n)
