#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
护城河评分模型数据结构

定义护城河评估的完整数据模型，包括：
1. 量化指标评分
2. 定性评估框架
3. AI辅助评分接口
4. 评分卡结构

数据结构设计用于:
- 数据库存储
- API接口返回
- 前端展示
- AI分析输入
"""

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional
from enum import Enum
import json
import logging
from datetime import datetime


class MoatCategory(Enum):
    """护城河类型枚举"""
    BRAND = "brand"                 # 品牌效应
    PATENTS = "patents"             # 专利技术
    SCALE = "scale"                 # 规模效应
    NETWORK = "network"             # 网络效应
    SWITCHING_COST = "switching"    # 转换成本
    COST_ADVANTAGE = "cost"         # 成本优势
    REGULATION = "regulation"       # 牌照/准入壁垒
    ECOSYSTEM = "ecosystem"         # 生态系统


class RiskLevel(Enum):
    """风险等级"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class QuantitativeMetric:
    """量化指标评分项"""
    name: str                       # 指标名称
    value: Optional[float] = None   # 实际值
    score: float = 0.0              # 得分 (0-100)
    weight: float = 1.0             # 权重
    threshold_low: float = 0.0      # 低阈值
    threshold_high: float = 100.0   # 高阈值
    unit: str = "%"                 # 单位
    description: str = ""           # 描述

    def weighted_score(self) -> float:
        """计算加权得分"""
        return self.score * self.weight


@dataclass
class QualitativeAssessment:
    """定性评估项"""
    category: MoatCategory          # 护城河类别
    question: str                   # 评估问题
    answer: Optional[str] = None    # 回答
    score: int = 0                  # 得分 (1-5)
    confidence: float = 0.0         # 置信度 (0-1)
    evidence: List[str] = field(default_factory=list)  # 证据
    source: str = ""                # 来源 (human/ai)


@dataclass
class RiskFactor:
    """风险因素"""
    name: str                       # 风险名称
    level: RiskLevel                # 风险等级
    description: str = ""           # 描述
    impact: str = ""                # 影响
    mitigation: str = ""            # 缓解措施


@dataclass
class MoatScorecard:
    """
    护城河评分卡（完整数据结构）

    这是护城河评估的核心数据模型，包含：
    - 股票基本信息
    - 量化财务指标评分
    - 定性护城河评估
    - 风险因素列表
    - AI辅助分析结果
    - 综合评级

    示例使用:
        scorecard = MoatScorecard(
            stock_code="600519",
            stock_name="贵州茅台"
        )
        scorecard.add_quantitative_score("ROE", 25.5, weight=0.15)
        scorecard.add_qualitative_assessment(
            MoatCategory.BRAND,
            "品牌是否有定价权?",
            "是，高端白酒龙头",
            score=5
        )
        scorecard.calculate_final_score()
    """

    # ===== 基本信息 =====
    stock_code: str                         # 股票代码
    stock_name: str = ""                    # 股票名称
    industry: str = ""                      # 行业
    sector: str = ""                        # 板块
    market_cap: float = 0.0                 # 市值（亿）
    evaluation_date: str = field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d")
    )

    # ===== 量化指标评分 =====
    profitability_metrics: List[QuantitativeMetric] = field(default_factory=list)
    growth_metrics: List[QuantitativeMetric] = field(default_factory=list)
    safety_metrics: List[QuantitativeMetric] = field(default_factory=list)
    efficiency_metrics: List[QuantitativeMetric] = field(default_factory=list)
    valuation_metrics: List[QuantitativeMetric] = field(default_factory=list)

    # ===== 定性护城河评估 =====
    moat_assessments: List[QualitativeAssessment] = field(default_factory=list)
    identified_moats: List[MoatCategory] = field(default_factory=list)

    # ===== 风险评估 =====
    risk_factors: List[RiskFactor] = field(default_factory=list)
    overall_risk: RiskLevel = RiskLevel.MEDIUM

    # ===== AI辅助分析 =====
    ai_analysis: Dict = field(default_factory=dict)
    ai_moat_summary: str = ""               # AI生成的护城河总结
    ai_investment_thesis: str = ""          # AI生成的投资论点
    ai_concerns: List[str] = field(default_factory=list)  # AI提出的担忧

    # ===== 综合评分 =====
    quantitative_score: float = 0.0         # 量化得分 (0-100)
    qualitative_score: float = 0.0          # 定性得分 (0-100)
    final_score: float = 0.0                # 最终得分 (0-100)
    grade: str = "D"                        # 评级 A/B/C/D
    recommendation: str = ""                # 投资建议

    def add_quantitative_score(self, name: str, value: float,
                               category: str = "profitability",
                               weight: float = 1.0,
                               thresholds: tuple = (0, 100)) -> None:
        """添加量化指标评分"""
        metric = QuantitativeMetric(
            name=name,
            value=value,
            weight=weight,
            threshold_low=thresholds[0],
            threshold_high=thresholds[1]
        )

        # 计算得分 (线性映射)
        if value is not None:
            if value <= thresholds[0]:
                metric.score = 0
            elif value >= thresholds[1]:
                metric.score = 100
            else:
                metric.score = ((value - thresholds[0]) /
                               (thresholds[1] - thresholds[0]) * 100)

        # 添加到对应类别
        category_map = {
            "profitability": self.profitability_metrics,
            "growth": self.growth_metrics,
            "safety": self.safety_metrics,
            "efficiency": self.efficiency_metrics,
            "valuation": self.valuation_metrics
        }

        if category in category_map:
            category_map[category].append(metric)

    def add_qualitative_assessment(self, category: MoatCategory,
                                   question: str,
                                   answer: str,
                                   score: int,
                                   source: str = "human") -> None:
        """添加定性评估"""
        assessment = QualitativeAssessment(
            category=category,
            question=question,
            answer=answer,
            score=score,
            source=source
        )
        self.moat_assessments.append(assessment)

        # 如果评分较高，添加到已识别的护城河
        if score >= 4 and category not in self.identified_moats:
            self.identified_moats.append(category)

    def add_risk(self, name: str, level: RiskLevel,
                 description: str = "", impact: str = "") -> None:
        """添加风险因素"""
        risk = RiskFactor(
            name=name,
            level=level,
            description=description,
            impact=impact
        )
        self.risk_factors.append(risk)

    def calculate_final_score(self,
                              quantitative_weight: float = 0.6,
                              qualitative_weight: float = 0.4) -> None:
        """计算最终评分"""
        # 计算量化得分
        all_metrics = (self.profitability_metrics +
                      self.growth_metrics +
                      self.safety_metrics +
                      self.efficiency_metrics +
                      self.valuation_metrics)

        if all_metrics:
            total_weight = sum(m.weight for m in all_metrics)
            if total_weight > 0:
                self.quantitative_score = (
                    sum(m.weighted_score() for m in all_metrics) / total_weight
                )

        # 计算定性得分
        if self.moat_assessments:
            avg_score = sum(a.score for a in self.moat_assessments) / len(self.moat_assessments)
            self.qualitative_score = avg_score * 20  # 1-5 -> 0-100

        # 综合得分
        self.final_score = (
            self.quantitative_score * quantitative_weight +
            self.qualitative_score * qualitative_weight
        )

        # 风险调整
        risk_penalty = {
            RiskLevel.LOW: 0,
            RiskLevel.MEDIUM: 5,
            RiskLevel.HIGH: 15,
            RiskLevel.CRITICAL: 30
        }
        self.final_score -= risk_penalty.get(self.overall_risk, 0)
        self.final_score = max(0, min(100, self.final_score))

        # 确定评级
        if self.final_score >= 80:
            self.grade = "A"
            self.recommendation = "强烈推荐"
        elif self.final_score >= 65:
            self.grade = "B"
            self.recommendation = "推荐关注"
        elif self.final_score >= 50:
            self.grade = "C"
            self.recommendation = "谨慎持有"
        else:
            self.grade = "D"
            self.recommendation = "不建议"

    def to_dict(self) -> Dict:
        """转换为字典（用于JSON序列化）"""
        return {
            "basic_info": {
                "stock_code": self.stock_code,
                "stock_name": self.stock_name,
                "industry": self.industry,
                "market_cap": self.market_cap,
                "evaluation_date": self.evaluation_date
            },
            "quantitative": {
                "profitability": [asdict(m) for m in self.profitability_metrics],
                "growth": [asdict(m) for m in self.growth_metrics],
                "safety": [asdict(m) for m in self.safety_metrics],
                "efficiency": [asdict(m) for m in self.efficiency_metrics],
                "valuation": [asdict(m) for m in self.valuation_metrics]
            },
            "qualitative": {
                "assessments": [
                    {
                        "category": a.category.value,
                        "question": a.question,
                        "answer": a.answer,
                        "score": a.score,
                        "source": a.source
                    } for a in self.moat_assessments
                ],
                "identified_moats": [m.value for m in self.identified_moats]
            },
            "risks": [
                {
                    "name": r.name,
                    "level": r.level.value,
                    "description": r.description,
                    "impact": r.impact
                } for r in self.risk_factors
            ],
            "ai_analysis": {
                "summary": self.ai_moat_summary,
                "thesis": self.ai_investment_thesis,
                "concerns": self.ai_concerns
            },
            "scores": {
                "quantitative": round(self.quantitative_score, 2),
                "qualitative": round(self.qualitative_score, 2),
                "final": round(self.final_score, 2),
                "grade": self.grade,
                "recommendation": self.recommendation
            }
        }

    def to_json(self, indent: int = 2) -> str:
        """转换为JSON字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


# ========== 评分卡模板 ==========

def create_default_scorecard(stock_code: str, stock_name: str = "") -> MoatScorecard:
    """创建默认评分卡模板"""
    scorecard = MoatScorecard(
        stock_code=stock_code,
        stock_name=stock_name
    )

    # 预置定性评估问题
    default_questions = [
        (MoatCategory.BRAND, "公司品牌是否具有定价权？"),
        (MoatCategory.BRAND, "品牌在消费者心中的认知度和美誉度如何？"),
        (MoatCategory.PATENTS, "公司是否拥有关键专利或技术壁垒？"),
        (MoatCategory.PATENTS, "研发投入占比和专利数量如何？"),
        (MoatCategory.SCALE, "公司是否具有规模效应带来的成本优势？"),
        (MoatCategory.SCALE, "市场份额是否领先？"),
        (MoatCategory.NETWORK, "产品/服务是否具有网络效应？"),
        (MoatCategory.SWITCHING_COST, "客户转换到竞争对手的成本高吗？"),
        (MoatCategory.SWITCHING_COST, "客户留存率和复购率如何？"),
        (MoatCategory.COST_ADVANTAGE, "公司是否是成本领先者？"),
        (MoatCategory.REGULATION, "公司是否拥有稀缺的牌照或准入资质？"),
        (MoatCategory.ECOSYSTEM, "公司是否建立了完整的生态系统？")
    ]

    for category, question in default_questions:
        assessment = QualitativeAssessment(
            category=category,
            question=question
        )
        scorecard.moat_assessments.append(assessment)

    return scorecard


# ========== AI辅助评分接口 ==========

@dataclass
class AIAnalysisRequest:
    """AI分析请求"""
    stock_code: str
    stock_name: str
    industry: str
    financial_data: Dict               # 财务数据
    company_description: str = ""      # 公司描述
    recent_news: List[str] = field(default_factory=list)  # 近期新闻

    def to_prompt(self) -> str:
        """生成AI分析提示词"""
        prompt = f"""
请分析以下股票的护城河和投资价值:

## 基本信息
- 股票代码: {self.stock_code}
- 股票名称: {self.stock_name}
- 所属行业: {self.industry}

## 财务数据
{json.dumps(self.financial_data, ensure_ascii=False, indent=2)}

## 公司描述
{self.company_description}

请从以下维度进行分析:
1. 识别该公司可能具有的护城河类型（品牌、专利、规模、网络效应、转换成本等）
2. 评估各类护城河的强度 (1-5分)
3. 识别主要风险因素
4. 给出投资论点总结
5. 提出值得关注的问题

请以JSON格式返回分析结果。
"""
        return prompt


@dataclass
class AIAnalysisResult:
    """AI分析结果"""
    moat_types: List[Dict]          # 护城河类型和评分
    risk_factors: List[str]         # 风险因素
    investment_thesis: str          # 投资论点
    concerns: List[str]             # 担忧点
    overall_score: int              # 总体评分 (1-100)
    confidence: float               # 置信度 (0-1)

    @classmethod
    def from_json(cls, json_str: str) -> 'AIAnalysisResult':
        """从JSON解析AI分析结果"""
        data = json.loads(json_str)
        return cls(
            moat_types=data.get('moat_types', []),
            risk_factors=data.get('risk_factors', []),
            investment_thesis=data.get('investment_thesis', ''),
            concerns=data.get('concerns', []),
            overall_score=data.get('overall_score', 50),
            confidence=data.get('confidence', 0.5)
        )


# ========== 评分阈值配置 ==========

SCORING_THRESHOLDS = {
    # 盈利能力
    "roe_weight": {"low": 5, "high": 25, "weight": 0.15},
    "sale_gpr": {"low": 15, "high": 50, "weight": 0.10},
    "sale_npr": {"low": 5, "high": 25, "weight": 0.10},
    "jroa": {"low": 3, "high": 15, "weight": 0.08},
    "roic": {"low": 8, "high": 25, "weight": 0.07},

    # 成长能力
    "income_growthrate_3y": {"low": 0, "high": 30, "weight": 0.10},
    "netprofit_growthrate_3y": {"low": 0, "high": 30, "weight": 0.10},

    # 财务安全 (反向指标，值越低越好)
    "debt_asset_ratio": {"low": 60, "high": 20, "weight": 0.08, "inverse": True},

    # 效率指标
    "current_ratio": {"low": 0.5, "high": 2.5, "weight": 0.05},
    "speed_ratio": {"low": 0.3, "high": 2.0, "weight": 0.05},

    # 现金流
    "per_netcash_operate": {"low": 0, "high": 3, "weight": 0.07},

    # 估值 (反向指标)
    "pe9": {"low": 50, "high": 10, "weight": 0.05, "inverse": True}
}


def get_threshold_config() -> Dict:
    """获取评分阈值配置（优先从数据库加载用户自定义值）"""
    import copy
    config = copy.deepcopy(SCORING_THRESHOLDS)
    try:
        from quantia.web.strategyParamsHandler import get_strategy_params
        params = get_strategy_params("moat_scoring")
        if params:
            values = {}
            for group in params.get('groups', []):
                for p in group.get('params', []):
                    values[p['key']] = p['value']
            # 更新权重
            weight_map = {
                'roe_weight': 'roe_weight',
                'sale_gpr_weight': 'sale_gpr',
                'sale_npr_weight': 'sale_npr',
                'income_growth_weight': 'income_growthrate_3y',
                'profit_growth_weight': 'netprofit_growthrate_3y',
            }
            for param_key, threshold_key in weight_map.items():
                if param_key in values and threshold_key in config:
                    config[threshold_key]['weight'] = values[param_key]
    except Exception:
        logging.debug("加载护城河自定义权重异常", exc_info=True)
    return config
