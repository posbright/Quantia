# -*- coding: utf-8 -*-
"""基金分批建仓回测（纯函数，无副作用）。

回答"随机选取若干基金、分多少次买入收益最优"的统计实验内核。

关键方法论约束（务必同步给上层报告）：
- 一律用 `acc_nav`（累计净值，已还原分红拆分），不用 unit_nav。
- "总收益率"对不同分批次数 k 不公平：分批使后投入资金在场时间更短，
  上涨市中几乎必然 k=1（一次性全仓）最高 → 平凡解。因此同时给出
  **IRR（资金加权年化）** 与 **最大回撤**，分批的价值在于降低回撤/择时风险。
- 序列稀疏（周末/节假日/分红日无净值）→ 按净值点（非日历日）等分买点。

所有函数输入序列、输出标量/字典，可在无 DB 环境下用合成数据验证。
"""

import math

import numpy as np
import pandas as pd

import quantia.core.fund.scoring as scoring

__author__ = 'Quantia'
__date__ = '2026/06/03'


def _clean_series(nav_dates, acc_nav):
    """对齐 (nav_date, acc_nav)：转数值、去 NaN、取正、按日期升序去重。"""
    s = pd.Series(
        pd.to_numeric(pd.Series(list(acc_nav)), errors='coerce').values,
        index=pd.to_datetime(pd.Series(list(nav_dates)), errors='coerce'),
    )
    s = s[~s.index.isna()].dropna()
    s = s[s > 0]
    s = s[~s.index.duplicated(keep='last')].sort_index()
    return s


def _buy_indices(n, k):
    """在 [0, n-1] 上放 k 个等距买点（首点=0，末点 < n-1，留持有期）。

    第 j 个买点 idx = floor(j * n / k)，保证互不相同且升序。
    """
    if k <= 1:
        return [0]
    idx = sorted({int(math.floor(j * n / k)) for j in range(k)})
    # 极端短序列去重后可能不足 k 个，直接返回去重结果（实际买点数=len）。
    return idx


def xirr(cash_flows, *, lo=-0.9999, hi=10.0, tol=1e-6, max_iter=200):
    """资金加权年化收益率（XIRR），二分求解 NPV(rate)=0。

    cash_flows: [(date, amount), ...]，投入为负、赎回为正。
    返回年化小数（如 0.08=+8%）；现金流全同号或无解→None。
    """
    flows = [(pd.Timestamp(d), float(a)) for d, a in cash_flows if a != 0]
    if len(flows) < 2:
        return None
    signs = {1 if a > 0 else -1 for _, a in flows}
    if len(signs) < 2:
        return None
    t0 = min(d for d, _ in flows)
    years = [(d - t0).days / 365.0 for d, _ in flows]
    amts = [a for _, a in flows]

    def npv(rate):
        return sum(a / (1.0 + rate) ** y for a, y in zip(amts, years))

    f_lo, f_hi = npv(lo), npv(hi)
    if not (math.isfinite(f_lo) and math.isfinite(f_hi)) or f_lo * f_hi > 0:
        return None
    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        f_mid = npv(mid)
        if not math.isfinite(f_mid):
            return None
        if abs(f_mid) < tol:
            return float(mid)
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return float((lo + hi) / 2.0)


def simulate_staged_buy(nav_dates, acc_nav, k, capital=10000.0):
    """把 capital 分 k 等份在窗口内 k 个等距买点投入，持有到期末。

    Args:
        nav_dates: 净值日期序列（窗口内）。
        acc_nav:   对应累计净值序列。
        k:         分批次数（1=一次性全仓）。
        capital:   总投入金额。

    Returns:
        dict 或 None（序列过短无法回测）：
        - k_requested / k_effective: 计划/实际买点数（短序列去重后可能更少）
        - invested:    总投入（=capital）
        - final_value: 期末市值
        - total_return: 简单总收益率 = final_value/capital - 1（不计时间价值）
        - irr:         资金加权年化收益率（公平对比不同 k 的核心指标）
        - max_drawdown: 组合市值路径最大回撤（负数，分批的真实价值所在）
        - n_points:    窗口内净值点数
        - buy_dates:   实际买点日期列表
    """
    s = _clean_series(nav_dates, acc_nav)
    n = len(s)
    if n < 2 or capital <= 0:
        return None

    dates = list(s.index)
    navs = s.values.astype(float)
    buy_idx = [i for i in _buy_indices(n, max(1, int(k))) if 0 <= i < n]
    k_eff = len(buy_idx)
    if k_eff == 0:
        return None
    tranche = capital / k_eff

    # 组合市值路径：每个净值点 value = 未投现金 + 已买份额 * 当日净值。
    shares_cum = 0.0
    invested_cum = 0.0
    buy_set = {}
    for i in buy_idx:
        buy_set[i] = buy_set.get(i, 0) + 1  # 同点重复（短序列）累加份数
    value_path = np.empty(n, dtype=float)
    cash_flows = []
    for t in range(n):
        if t in buy_set:
            cnt = buy_set[t]
            amt = tranche * cnt
            shares_cum += amt / navs[t]
            invested_cum += amt
            cash_flows.append((dates[t], -amt))
        cash_remaining = capital - invested_cum
        value_path[t] = cash_remaining + shares_cum * navs[t]

    final_value = float(shares_cum * navs[-1])  # 期末全部赎回
    cash_flows.append((dates[-1], final_value))

    total_return = final_value / capital - 1.0
    mdd = scoring.compute_max_drawdown(value_path)
    irr = xirr(cash_flows)

    return {
        'k_requested': int(k),
        'k_effective': k_eff,
        'invested': float(capital),
        'final_value': final_value,
        'total_return': float(total_return),
        'irr': irr,
        'max_drawdown': mdd,
        'n_points': int(n),
        'buy_dates': [d.date().isoformat() for d in (dates[i] for i in buy_idx)],
    }
