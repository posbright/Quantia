# -*- coding: utf-8 -*-
"""基金入场择时纯函数（T1 回撤 + T2 趋势 + T3 估值，纯计算无 I/O）。

设计约束（见 document/fund/fund_pick_timing_impl_plan.md §2.1）：
- **绝对时序刻度**：dd_score / trend_score 按**单基金自身净值时序**映射到 0–100，
  严禁跨基金截面百分位（否则永远约 25% 基金被标低吸，失去"位置"含义）。
- **缺失维度 drop + 权重重归一化**（非填中性 50）：某维数据不足时丢弃该维，
  对剩余维度权重重新归一到 1，与 scoring 的"缺失填中性"语义不同，勿混用。
- 一律用 acc_nav（累计净值，已还原分红拆分）；acc_nav 缺失由上层用 unit_nav 兜底。
- 档位阈值为**绝对分固定阈值**，与前端原型 tierOf 一致，不做全样本调参。
- 纯函数：输入序列/标量，输出标量/字典，无副作用、无 DB/网络。

与 scoring.py 的关系：复用 `_clean_nav` 口径（正数、去 NaN），但**不复用**
`cross_sectional_pct_rank`（截面口径，误用会错乱，见 impl_plan B1）。
"""

import math

import numpy as np
import pandas as pd

__author__ = 'Quantia'
__date__ = '2026/07/09'

# ── 档位阈值（对齐蓝图 §3.2 与前端原型 tierOf）──────────────
TIER_LOW = 75.0    # 低吸 ≥75
TIER_DCA = 50.0    # 定投 50–75
TIER_WAIT = 30.0   # 观望 30–50
#                  高估勿追 <30

# ── T1/T2 参数 ────────────────────────────────────────────
DD_CAP = 0.30          # 回撤映射上限：跌幅 ≥30% → dd_score 封顶 100（防接飞刀无限抄底）
TREND_MA_WINDOW = 60   # 趋势长均线窗口（交易日）
TREND_R_GAIN = 250.0   # 净值相对均线偏离 → 分数增益系数
TREND_SLOPE_BONUS = 10.0  # 均线斜率方向加/减分

# ── 三维默认权重（缺维时对剩余重归一化到 1）──────────────────
DEFAULT_WEIGHTS = {'dd': 0.5, 'trend': 0.3, 'val': 0.2}


def _clean_nav(acc_nav):
    """与 scoring._clean_nav 同口径：转数值、去 NaN、仅保留正值、重置索引。"""
    nav = pd.to_numeric(pd.Series(list(acc_nav)), errors='coerce').dropna()
    return nav[nav > 0].reset_index(drop=True)


def _clip(v, lo=0.0, hi=100.0):
    return float(max(lo, min(hi, v)))


def drawdown_from_high(acc_nav, cap=DD_CAP):
    """T1 回撤入场分（0–100，绝对时序）。

    dd = last / 历史峰值 - 1（≤0）；跌幅 m = -dd。
    score = clip(m / cap * 100, 0, 100)。m ≥ cap（默认 30%）→ 100（越跌越"低吸"，有封顶）。
    样本 < 2 或清洗后为空 → None。
    """
    nav = _clean_nav(acc_nav)
    if len(nav) < 2:
        return None
    peak = nav.cummax().iloc[-1]
    if not math.isfinite(peak) or peak <= 0:
        return None
    dd = nav.iloc[-1] / peak - 1.0  # ≤ 0
    if not math.isfinite(dd):
        return None
    m = max(0.0, -dd)
    if cap <= 0:
        return None
    return _clip(m / cap * 100.0)


def nav_trend_score(acc_nav, ma_window=TREND_MA_WINDOW):
    """T2 趋势确认分（0–100，绝对时序）。

    站上自身长均线 + 均线斜率向上 → 高分（右侧确认，防接飞刀）；跌破 → 低分。
    r = last / ma - 1；slope = ma 末端相对前段的方向。
    score = clip(50 + r*TREND_R_GAIN + (slope>0 ? +BONUS : -BONUS), 0, 100)。
    样本 < ma_window → None（该维缺失，交由 compose 重归一化）。
    """
    nav = _clean_nav(acc_nav)
    if len(nav) < ma_window or ma_window < 2:
        return None
    ma = nav.rolling(ma_window).mean().dropna()
    if len(ma) < 2:
        return None
    ma_last = ma.iloc[-1]
    if not math.isfinite(ma_last) or ma_last <= 0:
        return None
    r = nav.iloc[-1] / ma_last - 1.0
    # 斜率：末端均线 vs 约一窗口前均线（不足则用首个可得均线）
    prev_idx = max(0, len(ma) - 1 - ma_window)
    slope = ma.iloc[-1] - ma.iloc[prev_idx]
    bonus = TREND_SLOPE_BONUS if slope > 0 else -TREND_SLOPE_BONUS
    if not math.isfinite(r):
        return None
    return _clip(50.0 + r * TREND_R_GAIN + bonus)


def valuation_percentile_score(pe_or_pb_series):
    """T3 估值分位分（0–100，绝对时序）。P1 不接入（上层传 None）。

    输入为该基金跟踪指数的 PE/PB 历史时序；当前值处于历史低分位 → 高分（便宜）。
    score = clip((1 - percentile_of_last) * 100, 0, 100)。序列 < 2 → None。
    """
    if pe_or_pb_series is None:
        return None
    s = pd.to_numeric(pd.Series(list(pe_or_pb_series)), errors='coerce').dropna()
    if len(s) < 2:
        return None
    last = s.iloc[-1]
    if not math.isfinite(last):
        return None
    # 当前值在历史序列中的分位（含自身）：越低越便宜
    pct = (s <= last).mean()
    if not math.isfinite(pct):
        return None
    return _clip((1.0 - pct) * 100.0)


def tier_of(score):
    """综合分 → 档位中文标签。None → None。"""
    if score is None:
        return None
    try:
        s = float(score)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(s):
        return None
    if s >= TIER_LOW:
        return '低吸'
    if s >= TIER_DCA:
        return '定投'
    if s >= TIER_WAIT:
        return '观望'
    return '高估勿追'


def compose_timing_score(dd, trend, val, weights=None):
    """三维加权合成综合择时分（缺维 drop + 权重重归一化到 1）。

    dd/trend/val 为各维 0–100 分或 None。缺失维度不参与、其权重重新分摊给剩余维。
    返回 {'score': 0-100|None, 'tier': str|None,
          'components': {'dd','trend','val'}, 'dims_used': [...]}。
    全维缺失 → score=None, tier=None。
    """
    w = dict(weights) if weights else dict(DEFAULT_WEIGHTS)
    comps = {'dd': dd, 'trend': trend, 'val': val}
    used = {}
    for k, v in comps.items():
        if v is None:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(fv):
            used[k] = fv
    if not used:
        return {'score': None, 'tier': None, 'components': comps, 'dims_used': []}
    wsum = sum(w.get(k, 0.0) for k in used)
    if wsum <= 0:
        # 权重表未覆盖任何可用维 → 等权兜底
        score = sum(used.values()) / len(used)
    else:
        score = sum(used[k] * w.get(k, 0.0) for k in used) / wsum
    score = _clip(score)
    return {
        'score': score,
        'tier': tier_of(score),
        'components': comps,
        'dims_used': sorted(used.keys()),
    }
