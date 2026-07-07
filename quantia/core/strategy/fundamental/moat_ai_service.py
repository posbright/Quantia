#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI辅助护城河评估服务

通过大语言模型辅助进行定性护城河评估：
1. 生成评估提示词
2. 解析AI返回结果
3. 整合到评分卡

支持的AI后端：
- OpenAI API
- 本地模型接口
- 自定义API

使用方法:
    service = MoatAIService(api_key="your-key")
    result = service.analyze_moat("600519", "贵州茅台", financial_data)
"""

import json
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass

from .moat_model import (
    MoatScorecard,
    MoatCategory,
    RiskLevel,
    AIAnalysisRequest,
    AIAnalysisResult,
    create_default_scorecard
)

__author__ = 'Quantia'
__date__ = '2026/02/14'


# ========== 提示词模板 ==========

MOAT_ANALYSIS_PROMPT = """
你是一位专业的价值投资分析师，请分析以下股票的护城河和投资价值。

## 基本信息
- 股票代码: {stock_code}
- 股票名称: {stock_name}
- 所属行业: {industry}

## 财务数据
{financial_data}

{additional_info}

## 分析要求

请从以下维度进行深入分析：

### 1. 护城河类型识别
识别该公司可能具有的护城河类型，从以下选项中选择：
- brand: 品牌效应（高毛利率、定价权、品牌溢价）
- patents: 专利技术（研发壁垒、技术领先）
- scale: 规模效应（成本领先、规模优势）
- network: 网络效应（用户越多价值越大）
- switching: 转换成本（客户粘性高）
- cost: 成本优势（供应链、生产效率）
- regulation: 牌照壁垒（准入资质稀缺）
- ecosystem: 生态系统（平台生态）

### 2. 护城河强度评分
对每种识别到的护城河类型，给出1-5分的强度评分：
- 5分：极强护城河，竞争对手几乎无法突破
- 4分：强护城河，需要巨大投入才能挑战
- 3分：中等护城河，存在但可被挑战
- 2分：弱护城河，竞争者有机会
- 1分：极弱/疑似护城河

### 3. 风险因素
识别主要风险，并评估风险等级（low/medium/high/critical）

### 4. 投资论点
给出简洁的投资论点（50字以内）

### 5. 关注问题
列出3-5个值得投资者进一步研究的问题

## 输出格式

请严格按以下JSON格式返回（不要添加其他文字）：

```json
{{
    "moat_types": [
        {{"type": "brand", "score": 4, "reason": "高端白酒龙头，品牌溢价能力强"}},
        {{"type": "scale", "score": 3, "reason": "市场份额领先，具有规模效应"}}
    ],
    "risk_factors": [
        {{"name": "政策风险", "level": "medium", "description": "白酒行业可能面临消费税调整"}}
    ],
    "investment_thesis": "A股最强品牌护城河之一，长期确定性高，估值合理时可配置",
    "concerns": [
        "年轻一代白酒消费习惯是否改变？",
        "渠道库存水平如何？",
        "茅台冰淇淋等多元化是否稀释品牌？"
    ],
    "overall_score": 85,
    "confidence": 0.8
}}
```
"""


QUICK_MOAT_PROMPT = """
快速评估以下股票的护城河（一句话回答）：

股票：{stock_name}（{stock_code}）
行业：{industry}
ROE：{roe}%
毛利率：{gross_margin}%
3年营收增长：{revenue_growth}%

请回答：
1. 最可能的护城河类型是什么？
2. 护城河强度（1-5分）？
3. 一句话投资建议
"""


@dataclass
class MoatAIConfig:
    """AI服务配置"""
    api_base: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4"
    temperature: float = 0.3
    max_tokens: int = 2000
    timeout: int = 60

    @classmethod
    def from_db(cls) -> 'MoatAIConfig':
        """从数据库加载用户配置的AI参数"""
        try:
            from quantia.web.strategyParamsHandler import get_strategy_params
            params = get_strategy_params("ai_model")
            if params is None:
                return cls()

            # 提取所有参数值到字典
            values = {}
            for group in params.get('groups', []):
                for p in group.get('params', []):
                    values[p['key']] = p['value']

            model = values.get('model', 'gpt-4')
            if model == 'custom':
                model = values.get('custom_model') or 'gpt-4'

            return cls(
                api_base=values.get('api_base', 'https://api.openai.com/v1'),
                api_key=values.get('api_key', ''),
                model=model,
                temperature=float(values.get('temperature', 0.3)),
                max_tokens=int(values.get('max_tokens', 2000)),
                timeout=int(values.get('timeout', 60))
            )
        except Exception as e:
            logging.warning(f"从数据库加载AI配置失败，使用默认值: {e}")
            return cls()


class MoatAIService:
    """
    AI辅助护城河评估服务

    使用示例:
        service = MoatAIService(api_key="sk-xxx")

        # 完整分析
        result = service.analyze_moat(
            stock_code="600519",
            stock_name="贵州茅台",
            industry="白酒",
            financial_data={"roe": 25, "gross_margin": 91}
        )

        # 快速评估
        quick = service.quick_assess("600519", "贵州茅台", "白酒", 25, 91, 15)
    """

    def __init__(self, config: MoatAIConfig = None, api_key: str = None):
        if config:
            self.config = config
        else:
            # 默认从数据库加载用户配置
            self.config = MoatAIConfig.from_db()
        if api_key:
            self.config.api_key = api_key

    def analyze_moat(self,
                     stock_code: str,
                     stock_name: str,
                     industry: str,
                     financial_data: Dict,
                     additional_info: str = "") -> Optional[AIAnalysisResult]:
        """
        完整的AI护城河分析

        Args:
            stock_code: 股票代码
            stock_name: 股票名称
            industry: 行业
            financial_data: 财务数据字典
            additional_info: 额外信息（公司描述、新闻等）

        Returns:
            AIAnalysisResult对象，或None（失败时）
        """
        prompt = MOAT_ANALYSIS_PROMPT.format(
            stock_code=stock_code,
            stock_name=stock_name,
            industry=industry,
            financial_data=json.dumps(financial_data, ensure_ascii=False, indent=2),
            additional_info=additional_info
        )

        try:
            response = self._call_ai(prompt)
            if response:
                return self._parse_analysis_result(response)
        except Exception as e:
            logging.error(f"AI分析失败", exc_info=True)

        return None

    def quick_assess(self,
                     stock_code: str,
                     stock_name: str,
                     industry: str,
                     roe: float,
                     gross_margin: float,
                     revenue_growth: float) -> Optional[str]:
        """
        快速AI评估（返回简短文本）
        """
        prompt = QUICK_MOAT_PROMPT.format(
            stock_code=stock_code,
            stock_name=stock_name,
            industry=industry,
            roe=roe,
            gross_margin=gross_margin,
            revenue_growth=revenue_growth
        )

        return self._call_ai(prompt)

    def enrich_scorecard(self,
                         scorecard: MoatScorecard,
                         financial_data: Dict) -> MoatScorecard:
        """
        用AI分析结果丰富评分卡

        Args:
            scorecard: 已有的评分卡
            financial_data: 财务数据

        Returns:
            丰富后的评分卡
        """
        result = self.analyze_moat(
            stock_code=scorecard.stock_code,
            stock_name=scorecard.stock_name,
            industry=scorecard.industry,
            financial_data=financial_data
        )

        if result:
            # 更新AI分析结果
            scorecard.ai_moat_summary = result.investment_thesis
            scorecard.ai_investment_thesis = result.investment_thesis
            scorecard.ai_concerns = result.concerns

            # 添加AI识别的护城河
            for moat in result.moat_types:
                moat_type = moat.get('type', '')
                try:
                    category = MoatCategory(moat_type)
                    if category not in scorecard.identified_moats:
                        scorecard.identified_moats.append(category)
                except ValueError:
                    pass

            # 添加AI识别的风险
            for risk in result.risk_factors:
                try:
                    level = RiskLevel(risk.get('level', 'medium'))
                except ValueError:
                    level = RiskLevel.MEDIUM

                scorecard.add_risk(
                    name=risk.get('name', '未知风险'),
                    level=level,
                    description=risk.get('description', '')
                )

        return scorecard

    def _call_ai(self, prompt: str) -> Optional[str]:
        """调用 AI 接口。

        M10：从原本自带的 `requests.post(.../chat/completions)` 切换到统一的
        `quantia.lib.ai.run_chat()` —— 这样限流 / 审计 / token 统计 /
        错误重试都走同一份代码，避免 spec §10.1 / §12 提到的 "双套 AI 配置漂移"。

        行为约束（保持向后兼容，§13 验收）：
          * 未配置 api_key → 直接返回 None（不报错、不写审计），与旧实现一致。
          * 网络/服务异常 → 返回 None 而不是抛出（旧实现 try/except 兜底，
            护城河评估走"AI 失败也能用纯量化结果"路径，§13）。
          * 单测通过 mock `_call_ai` 直接接管，不会真打 LLM。
        """
        if not self.config.api_key:
            logging.warning("未配置AI API密钥，跳过AI分析")
            return None
        try:
            from quantia.lib.ai.failover import run_chat_with_failover
            return run_chat_with_failover(
                prompt,
                scene='moat_analysis',
                # audit-fix-1-P3: 使用专用 user_id，避免与 Web 用户调用共享全局限流桶
                user_id='__moat_service__',
                # audit-fix-1-P3: agent 名与 scene 对齐，便于审计检索（不需注册为 builtin）
                agent='moat_analysis',
                system='你是一位专业的价值投资分析师。',
                overrides={
                    'api_base': self.config.api_base,
                    'api_key': self.config.api_key,
                    'model': self.config.model,
                    'temperature': self.config.temperature,
                    'max_tokens': self.config.max_tokens,
                    'timeout': self.config.timeout,
                },
            )
        except Exception:
            logging.error('AI API调用异常', exc_info=True)
            return None

    def _parse_analysis_result(self, response: str) -> Optional[AIAnalysisResult]:
        """解析AI返回的JSON结果"""
        try:
            # 提取JSON部分（处理markdown代码块）
            json_str = response
            if '```json' in response:
                start = response.find('```json') + 7
                end = response.find('```', start)
                json_str = response[start:end].strip()
            elif '```' in response:
                start = response.find('```') + 3
                end = response.find('```', start)
                json_str = response[start:end].strip()

            return AIAnalysisResult.from_json(json_str)

        except json.JSONDecodeError as e:
            logging.error(f"JSON解析失败", exc_info=True)
            return None
        except Exception as e:
            logging.error(f"结果解析失败", exc_info=True)
            return None


# ========== 工具函数 ==========

def generate_moat_report(scorecard: MoatScorecard) -> str:
    """
    生成护城河评估报告（Markdown格式）

    Args:
        scorecard: 评分卡对象

    Returns:
        Markdown格式的报告文本
    """
    report = f"""
# 护城河评估报告

## 基本信息

| 项目 | 内容 |
|------|------|
| 股票代码 | {scorecard.stock_code} |
| 股票名称 | {scorecard.stock_name} |
| 所属行业 | {scorecard.industry} |
| 评估日期 | {scorecard.evaluation_date} |

## 评分结果

| 维度 | 得分 |
|------|------|
| 盈利能力 | {scorecard.quantitative_score:.1f}/100 |
| 定性评估 | {scorecard.qualitative_score:.1f}/100 |
| **最终得分** | **{scorecard.final_score:.1f}/100** |
| **评级** | **{scorecard.grade}** |
| **投资建议** | {scorecard.recommendation} |

## 识别的护城河类型

"""

    if scorecard.identified_moats:
        for moat in scorecard.identified_moats:
            moat_names = {
                MoatCategory.BRAND: "品牌效应",
                MoatCategory.PATENTS: "专利技术",
                MoatCategory.SCALE: "规模效应",
                MoatCategory.NETWORK: "网络效应",
                MoatCategory.SWITCHING_COST: "转换成本",
                MoatCategory.COST_ADVANTAGE: "成本优势",
                MoatCategory.REGULATION: "牌照壁垒",
                MoatCategory.ECOSYSTEM: "生态系统"
            }
            report += f"- {moat_names.get(moat, moat.value)}\n"
    else:
        report += "暂未识别明显护城河\n"

    report += "\n## 风险因素\n\n"

    if scorecard.risk_factors:
        for risk in scorecard.risk_factors:
            level_names = {
                RiskLevel.LOW: "🟢 低",
                RiskLevel.MEDIUM: "🟡 中",
                RiskLevel.HIGH: "🟠 高",
                RiskLevel.CRITICAL: "🔴 极高"
            }
            report += f"- **{risk.name}** [{level_names.get(risk.level, '中')}]: {risk.description}\n"
    else:
        report += "暂无明显风险因素\n"

    if scorecard.ai_investment_thesis:
        report += f"\n## AI投资论点\n\n{scorecard.ai_investment_thesis}\n"

    if scorecard.ai_concerns:
        report += "\n## 值得关注的问题\n\n"
        for concern in scorecard.ai_concerns:
            report += f"- {concern}\n"

    return report
