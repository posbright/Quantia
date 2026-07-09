# -*- coding: utf-8 -*-
"""T6 穿透式持仓位置纯函数（Look-through Holdings，仅展示参考，非硬因子）。

把基金前十大重仓股当作一篮子 A 股，对每只用其 K 线收盘序列算「当前技术位置」
（距高点回撤 / 长均线位置 / RSI 超卖度），越"低位"分越高（越适合分批建仓），
再按 `hold_ratio` 加权得基金"底层位置分"。

严格定位（见 document/fund/good_fund_selection_and_entry_timing_plan.md §T6）：
- **仅作详情页参考卡展示**，明确标注"季报滞后 + 覆盖不足"，**不进入 TimingScore 硬计算**，
  不影响无覆盖基金；穿透不完整（前十大常仅占净值 40–60%）→ 返回 covered_ratio 透明化。
- 纯函数：输入收盘序列/标量，输出标量/字典，无副作用、无 DB/网络（K 线读取在 handler 层）。
- 回撤维度复用 `timing.drawdown_from_high`（已含 B12 滚动峰值修复），保持口径一致。

分数语义：三维均为 0–100，**高分 = 低位（便宜/超卖/破位在下方）= 越适合分批**。
"""

import math

import numpy as np
import pandas as pd

from quantia.core.fund import timing

__author__ = 'Quantia'
__date__ = '2026/07/09'

# ── 个股位置参数（个股波动大于基金净值，故 cap/lookback 与 timing 基金口径不同）──
DD_CAP_STOCK = 0.50        # 个股回撤映射上限：距高点跌 ≥50% → dd 位置分封顶 100
DD_LOOKBACK_STOCK = 250    # 回撤滚动峰值窗口（≈ 1 年交易日）
MA_WINDOW = 60             # 长均线窗口（交易日）
MA_GAIN = 200.0            # 均线偏离 → 位置分增益（低于均线越多分越高）
RSI_N = 14                 # RSI 周期

# 底层位置分档位（软提示，非买卖建议）
POS_LOW = 65.0    # ≥65 多数处于低位
POS_MID = 45.0    # 45–65 中性偏均衡
#                  <45 多数处于高位


def _clean_close(close):
    """转数值、去 NaN、仅保留正值、重置索引。"""
    s = pd.to_numeric(pd.Series(list(close)), errors='coerce').dropna()
    return s[s > 0].reset_index(drop=True)


def _clip(v, lo=0.0, hi=100.0):
    return float(max(lo, min(hi, v)))


def drawdown_position(close, cap=DD_CAP_STOCK, lookback=DD_LOOKBACK_STOCK):
    """距滚动高点回撤位置分（0–100，高=深度回撤=低位）。复用 timing 回撤口径。"""
    return timing.drawdown_from_high(close, cap=cap, lookback=lookback)


def ma_position(close, ma_window=MA_WINDOW, gain=MA_GAIN):
    """长均线位置分（0–100，高=收盘在长均线下方越多=低位）。样本<ma_window→None。"""
    nav = _clean_close(close)
    if len(nav) < ma_window or ma_window < 2:
        return None
    ma = nav.rolling(ma_window).mean().dropna()
    if len(ma) < 1:
        return None
    ma_last = ma.iloc[-1]
    if not math.isfinite(ma_last) or ma_last <= 0:
        return None
    r = nav.iloc[-1] / ma_last - 1.0  # <0 → 在均线下方（低位）
    if not math.isfinite(r):
        return None
    # 位置分与趋势相反：低于均线 → 高分
    return _clip(50.0 - r * gain)


def rsi_position(close, n=RSI_N):
    """RSI 超卖位置分（0–100，高=RSI 低=超卖=低位）。样本≤n→None。"""
    s = _clean_close(close)
    if len(s) <= n or n < 2:
        return None
    delta = s.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    avg_loss = loss.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    ag = avg_gain.iloc[-1]
    al = avg_loss.iloc[-1]
    if not math.isfinite(ag) or not math.isfinite(al):
        return None
    if al == 0:
        rsi = 100.0 if ag > 0 else 50.0  # 无下跌：极强（RSI→100）；全平：中性
    else:
        rs = ag / al
        rsi = 100.0 - 100.0 / (1.0 + rs)
    if not math.isfinite(rsi):
        return None
    # 位置分：超卖(RSI低) → 高分
    return _clip(100.0 - rsi)


def stock_position(close):
    """单只重仓股综合位置分（三维缺失 drop + 等权平均）。

    返回 {'score': 0-100|None, 'dd', 'ma', 'rsi'}；三维全缺 → score=None。
    """
    dd = drawdown_position(close)
    ma = ma_position(close)
    rsi = rsi_position(close)
    parts = [v for v in (dd, ma, rsi) if v is not None and math.isfinite(float(v))]
    score = (sum(parts) / len(parts)) if parts else None
    return {
        'score': None if score is None else _clip(score),
        'dd': dd, 'ma': ma, 'rsi': rsi,
    }


def aggregate_positions(items):
    """按 hold_ratio 加权聚合基金底层位置分。

    items: 可迭代的 {'hold_ratio': float|None, 'score': float|None}。
    只计入 score 与 hold_ratio 均有效且 hold_ratio>0 的重仓股。
    返回 {'position_score': 0-100|None, 'covered_ratio': float(%), 'n': int}：
      - covered_ratio：计入个股的 hold_ratio 之和（透明化穿透不完整）。
      - 无有效个股 → position_score=None, covered_ratio=0, n=0。
    """
    wsum = 0.0
    acc = 0.0
    n = 0
    for it in items or []:
        sc = it.get('score')
        w = it.get('hold_ratio')
        try:
            scf = float(sc)
            wf = float(w)
        except (TypeError, ValueError):
            continue
        if not (math.isfinite(scf) and math.isfinite(wf)) or wf <= 0:
            continue
        acc += scf * wf
        wsum += wf
        n += 1
    if n == 0 or wsum <= 0:
        return {'position_score': None, 'covered_ratio': 0.0, 'n': 0}
    return {
        'position_score': _clip(acc / wsum),
        'covered_ratio': round(float(wsum), 2),
        'n': n,
    }


def position_label(score):
    """底层位置分 → 软提示标签（非买卖建议）。None → None。"""
    if score is None:
        return None
    try:
        s = float(score)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(s):
        return None
    if s >= POS_LOW:
        return '多数处于低位'
    if s >= POS_MID:
        return '中性偏均衡'
    return '多数处于高位'
