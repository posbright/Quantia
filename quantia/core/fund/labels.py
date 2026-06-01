# -*- coding: utf-8 -*-
"""基金投资价值标签 + 风险等级（F11 §4.5.2 / F13 §4.6 共享阈值，纯规则）。

强约束：
- **禁止"买/卖/加仓/减仓/建议买入"措辞**——只输出风险/特征描述标签。
- 阈值常量集中此处，F11 价值标签与 F13 综合分析共用，避免两处口径不一致。
- 风险等级是规则阈值映射，非模型预测；每张卡片必须带 RISK_DISCLAIMER。
"""

__author__ = 'Quantia'
__date__ = '2026/06/01'

# 固定风险提示文案（前端每张分析卡片底部必须展示）
RISK_DISCLAIMER = '历史业绩不代表未来，以上为基于历史数据的规则化分析，非投资建议。'

# 分位分档阈值（百分位 0~100）
TIER_LEAD = 90      # 领先
TIER_GOOD = 70      # 较优
TIER_MID = 40       # 中等
TIER_WEAK = 20      # 偏弱（其下为靠后）

# 持仓集中度阈值（前十大 hold_ratio 之和，单位 %）
CONC_DISPERSED = 40    # < 40 分散
CONC_MODERATE = 60     # 40~60 适中；> 60 集中


def tier_label(pct):
    """桶内百分位 → 分档中文标签。None → None。"""
    if pct is None:
        return None
    try:
        p = float(pct)
    except (TypeError, ValueError):
        return None
    if p != p:  # NaN
        return None
    if p >= TIER_LEAD:
        return '领先'
    if p >= TIER_GOOD:
        return '较优'
    if p >= TIER_MID:
        return '中等'
    if p >= TIER_WEAK:
        return '偏弱'
    return '靠后'


def _is_num(v):
    try:
        return v is not None and float(v) == float(v)
    except (TypeError, ValueError):
        return False


def value_labels(dims):
    """由 5 维桶内分位生成可解释价值标签（非投资建议）。

    dims: {'return','drawdown','sharpe','fee','scale'} 各为百分位 0~100（可缺）。
    """
    out = []
    ret = dims.get('return')
    if _is_num(ret):
        if ret >= 90:
            out.append('同类收益前10%')
        elif ret >= 75:
            out.append('同类收益前25%')
        elif ret <= 25:
            out.append('同类收益靠后')
    dd = dims.get('drawdown')
    if _is_num(dd):
        if dd >= 85:
            out.append(f'回撤控制优于同类{int(round(dd))}%')
        elif dd <= 20:
            out.append('回撤幅度大于多数同类')
    sh = dims.get('sharpe')
    if _is_num(sh):
        if sh >= 80:
            out.append('风险调整后收益领先')
        elif sh <= 20:
            out.append('风险调整后收益偏弱')
    fee = dims.get('fee')
    if _is_num(fee):
        if fee >= 70:
            out.append('费率低于同类中位')
        elif fee <= 30:
            out.append('费率高于同类中位')
    scale = dims.get('scale')
    if _is_num(scale):
        if scale >= 70:
            out.append('规模适中')
        elif scale <= 25:
            out.append('规模偏离适中区间（过小或过大）')
    return out


def concentration_label(top_ratio_sum):
    """前十大持仓集中度文案。返回 (level, text)；输入 None → (None, None)。"""
    if not _is_num(top_ratio_sum):
        return None, None
    s = float(top_ratio_sum)
    if s < CONC_DISPERSED:
        return 'dispersed', f'前十大重仓合计{s:.1f}%，持仓分散'
    if s <= CONC_MODERATE:
        return 'moderate', f'前十大重仓合计{s:.1f}%，集中度适中'
    return 'concentrated', f'前十大重仓合计{s:.1f}%，持仓集中（高弹性高风险）'


def risk_level(max_drawdown=None, concentration=None, fund_type=None,
               sharpe=None):
    """规则阈值映射风险等级：低 / 中 / 中高 / 高（非模型预测）。

    max_drawdown: 负数（如 -0.35）或 None；concentration: 前十大合计 %（None 可）。
    货币型默认「低」。
    """
    if fund_type == '货币型':
        return '低'
    if fund_type in ('债券型',) and not _is_num(max_drawdown):
        return '中'

    score = 0
    if _is_num(max_drawdown):
        dd = abs(float(max_drawdown))
        if dd >= 0.40:
            score += 3
        elif dd >= 0.25:
            score += 2
        elif dd >= 0.12:
            score += 1
    if _is_num(concentration):
        c = float(concentration)
        if c >= CONC_MODERATE:
            score += 1
    # 权益类基线：无回撤数据时按类型给中性偏高
    if not _is_num(max_drawdown) and fund_type in ('股票型', '指数型', 'QDII', '混合型'):
        score = max(score, 2)

    if score >= 4:
        return '高'
    if score >= 2:
        return '中高'
    if score >= 1:
        return '中'
    return '低'
