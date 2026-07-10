#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
综合选股策略 composite_alpha_v1 —— 纯截面打分核心（Compute 管道）。

设计依据：document/综合选股策略方案_多因子融合与回测优化_V1.md（含 V1.1 二次审计修订）。

关键修订对齐：
- 本模块是**横截面**打分（一次看到全部候选股票），不是逐票 check()，因此不注册进
  TABLE_CN_STOCK_STRATEGIES；由独立 job / 回测脚本调用（见 6.5）。
- 四个维度分（基本面/技术/筹码/资金流）先各自标准化到同一 0–1 量纲，再加权，
  从根源规避“夏普被百分数指标淹没”的量纲问题（见 5.2 的同类修订思路）。
- 维度数据缺失时自动降级：该维度权重置 0 并在可用维度上重归一（feature_available_mask，见 6.1）。
- 资金流/抢筹在历史回测期缺失时降级；筹码分布可回填故可参与（见 6.1）。

本模块**不做任何 DB / 网络调用**，全部纯函数，便于单测与回测复用。
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from quantia.core.selection_scoring import standardized_factor, logistic

__author__ = 'Quantia'
__date__ = '2026/07/10'


# 维度 -> [(因子列名, 方向)]。方向 'high' 越大越好，'low' 越小越好。
# 只用当前项目真实存在的字段；技术/筹码列由调用方（回测/ job）预先算好后并入 df。
DIMENSION_FACTORS: dict[str, list[tuple[str, str]]] = {
    # 基本面质量（cn_stock_financial / cn_stock_selection）
    'fund': [
        ('roe_weight', 'high'),
        ('sale_gpr', 'high'),
        ('sale_npr', 'high'),
        ('netprofit_growthrate_3y', 'high'),
        ('income_growthrate_3y', 'high'),
        ('debt_asset_ratio', 'low'),
    ],
    # 技术行为（由 K 线预计算：atr 越低越好、20日均线斜率越大越好、动量适中）
    'tech': [
        ('atr_pct', 'low'),
        ('ma20_slope', 'high'),
        ('mom_20', 'high'),
    ],
    # 估值（越低越便宜；PE/PB 代理由 现价/每股收益、现价/每股净资产 计算，可 PIT）
    'value': [
        ('pe_proxy', 'low'),
        ('pb_proxy', 'low'),
        ('pe9', 'low'),
        ('pbnewmrq', 'low'),
    ],
    # 筹码结构（cn_stock_chip_distribution，可回填，可回测）
    'chip': [
        ('winner_rate', 'high'),
        ('concentration_90', 'high'),
    ],
    # 资金流（cn_stock_selection 标签 / cn_stock_fund_flow；历史回测期通常缺失→降级）
    'flow': [
        ('main_net_inflow', 'high'),
        ('low_funds_inflow', 'high'),
    ],
}

# 维度默认权重（文档 11.3 实证固化：估值反转+低波主导，故 value 提权；chip/flow 为确认层，
# 上线后实时可用。回测最优相对比例 fund:value:tech ≈ 0.40:0.35:0.25）
DEFAULT_WEIGHTS: dict[str, float] = {
    'fund': 0.35,
    'value': 0.30,
    'tech': 0.20,
    'chip': 0.10,
    'flow': 0.05,
}

# 可上线候选默认参数（文档 11.3；2022-2025 四折样本外夏普全正、回撤≈8.5%、逐笔胜率≈53.8%、
# 对成本不敏感）。交易/选股层参数，供独立截面 job 与回测脚本引用。
DEFAULT_PARAMS: dict[str, float] = {
    'quality_gate': 55.0,    # 基本面质量门槛（fund_score >= 该值）
    'trade_gate': 60.0,      # 交易门槛（composite_score >= 该值）
    'top_positions': 15,     # 最大持仓数
    'regime_ma': 60,         # 大盘择时均线窗口（沪深300 低于该均线则空仓；0=关闭）
    'rebalance_days': 21,    # 月度调仓
    'lag_days': 60,          # 财务披露滞后（PIT 防前视）
    'cost_buy': 0.0005,      # 买入侧成本
    'cost_sell': 0.0015,     # 卖出侧成本
}


def _dimension_available(df: pd.DataFrame, factors: list[tuple[str, str]]) -> bool:
    """该维度是否有至少一个存在且含有效值的因子列。"""
    for col, _ in factors:
        if col in df.columns and pd.to_numeric(df[col], errors='coerce').notna().any():
            return True
    return False


def _dimension_score(df: pd.DataFrame, factors: list[tuple[str, str]],
                     factor_weights: Optional[dict[str, float]] = None) -> Optional[pd.Series]:
    """维度分 ∈ [0,1]：各因子方向化+Winsorize+稳健Z 后加权均值 → logistic。

    factor_weights：可选的 {列名: 权重}（用于 IC 加权）；缺省等权。
    无任何可用因子列时返回 None（该维度视为缺失，交由降级逻辑重归一）。
    """
    zs = []
    ws = []
    for col, direction in factors:
        if col in df.columns and pd.to_numeric(df[col], errors='coerce').notna().any():
            zs.append(standardized_factor(df[col], direction))
            w = 1.0 if factor_weights is None else float(factor_weights.get(col, 0.0))
            ws.append(max(0.0, w))
    if not zs:
        return None
    mat = pd.concat(zs, axis=1)
    wsum = sum(ws)
    if wsum <= 0:
        raw = mat.mean(axis=1)
    else:
        weights_arr = np.array(ws, dtype=float) / wsum
        raw = (mat * weights_arr).sum(axis=1)
    return logistic(raw)


def compute_composite_scores(
    df: pd.DataFrame,
    weights: Optional[dict[str, float]] = None,
    dimension_factors: Optional[dict[str, list[tuple[str, str]]]] = None,
    factor_weights: Optional[dict[str, float]] = None,
) -> pd.DataFrame:
    """对一个横截面（同一交易日的候选股票）计算综合得分。

    Args:
        df: 每行一只股票，列为各因子字段（缺失维度自动降级）。
        weights: 维度权重，默认 DEFAULT_WEIGHTS。
        dimension_factors: 维度->因子配置，默认 DIMENSION_FACTORS。
        factor_weights: 可选 {因子列名: 权重}，用于维度内按 IC 加权（缺省等权）。

    Returns:
        DataFrame（与 df 对齐 index），列：
          fund_score/tech_score/chip_score/flow_score（缺失维度为 NaN，0–100）,
          available_dims（该行/该截面可用维度列表，字符串）,
          composite_score（0–100）。
    """
    weights = dict(weights or DEFAULT_WEIGHTS)
    dimension_factors = dimension_factors or DIMENSION_FACTORS

    out = pd.DataFrame(index=df.index)
    available: list[str] = []
    dim_scores: dict[str, pd.Series] = {}
    for dim, factors in dimension_factors.items():
        if dim not in weights:
            continue
        score = _dimension_score(df, factors, factor_weights=factor_weights)
        if score is not None and _dimension_available(df, factors):
            dim_scores[dim] = score
            available.append(dim)
            out[f'{dim}_score'] = (score * 100).clip(0, 100)
        else:
            out[f'{dim}_score'] = np.nan

    if not dim_scores:
        out['available_dims'] = ''
        out['composite_score'] = np.nan
        return out

    # 降级重归一：仅在可用维度上按原权重比例归一（feature_available_mask）
    wsum = sum(weights[d] for d in dim_scores)
    if wsum <= 0:
        wsum = float(len(dim_scores))
        norm_w = {d: 1.0 / wsum for d in dim_scores}
    else:
        norm_w = {d: weights[d] / wsum for d in dim_scores}

    composite = pd.Series(0.0, index=df.index)
    weight_present = pd.Series(0.0, index=df.index)
    for d, s in dim_scores.items():
        filled = s.fillna(s.median() if s.notna().any() else 0.5)
        composite = composite + filled * norm_w[d]
        weight_present = weight_present + norm_w[d]
    # 若某行全维度 NaN（理论上不会），保底 0.5
    composite = composite.where(weight_present > 0, 0.5)

    out['available_dims'] = ','.join(available)
    out['composite_score'] = (composite * 100).clip(0, 100)
    return out


def select_candidates(
    df: pd.DataFrame,
    scores: Optional[pd.DataFrame] = None,
    quality_gate: float = 50.0,
    trade_gate: float = 60.0,
    top_n: int = 20,
    weights: Optional[dict[str, float]] = None,
) -> pd.DataFrame:
    """双门槛选股（文档 4.2）：

    门槛A（质量门槛）：fund_score >= quality_gate（基本面必须达标）。
    门槛B（交易门槛）：composite_score >= trade_gate。
    两者都满足才入选，最后按 composite_score 降序取 top_n。

    Args:
        df: 候选股票横截面（含因子列，最好含 'code'）。
        scores: 预先算好的得分（compute_composite_scores 结果）；None 时内部计算。
        quality_gate/trade_gate: 门槛值（0–100）。
        top_n: 最多返回数量。

    Returns:
        入选股票 DataFrame（df 原列 + 得分列），按 composite_score 降序。
        不满足时返回空表（允许“当日不出手”）。
    """
    if scores is None:
        scores = compute_composite_scores(df, weights=weights)
    merged = df.copy()
    for col in ('fund_score', 'tech_score', 'chip_score', 'flow_score',
                'available_dims', 'composite_score'):
        if col in scores.columns:
            merged[col] = scores[col]

    fund = pd.to_numeric(merged.get('fund_score'), errors='coerce')
    comp = pd.to_numeric(merged.get('composite_score'), errors='coerce')
    # 质量门槛：若基本面维度整体缺失（全 NaN），则跳过该门槛（长周期早期降级场景）
    if fund is not None and fund.notna().any():
        pass_quality = fund.fillna(-1) >= quality_gate
    else:
        pass_quality = pd.Series(True, index=merged.index)
    pass_trade = comp.fillna(-1) >= trade_gate

    picked = merged[pass_quality & pass_trade].copy()
    if picked.empty:
        return picked
    return picked.sort_values('composite_score', ascending=False).head(top_n).reset_index(drop=True)
