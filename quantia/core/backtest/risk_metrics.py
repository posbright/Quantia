#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
风险指标计算 — 聚宽风格完整收益概述

从每日净值序列计算回测风险指标：
- 累计收益率 / 年化收益率 / 基准收益率
- 超额收益 / 日均超额收益
- 最大回撤（含区间）/ 超额收益最大回撤
- 夏普比率 / 索提诺比率 / 超额收益夏普比率 / 信息比率
- Alpha / Beta
- 策略波动率 / 基准波动率
- 日胜率 / 交易胜率 / 盈亏比
- 盈利次数 / 亏损次数
"""

import numpy as np
import pandas as pd

__author__ = 'Quantia'
__date__ = '2026/03/13'

# 每年交易日数
_TRADING_DAYS_PER_YEAR = 245
# 无风险年化利率（1年定期存款约1.5%）
_RISK_FREE_RATE = 0.015
# 回测主表（cn_stock_backtest_portfolio）指标列为 DECIMAL(10,4)，可表示范围
# 约 ±999999.9999。极端/退化输入（如极短窗口、近零波动）会让夏普、年化收益等
# 计算出 inf / nan / 超大数值，直接入库会触发 MySQL 1264 "Out of range value"，
# 导致整条回测结果写入失败。此处统一在指标产出口做有限化+夹断，保证 DB 安全。
_DB_DECIMAL_MAX = 999999.9999


def _safe_metric(value):
    """将单个指标值规整为有限、可入库 DECIMAL(10,4) 的浮点数。

    - NaN / Inf / -Inf → 0.0（退化输入下指标无意义，置零而非报错）
    - 超出 ±_DB_DECIMAL_MAX → 夹断到边界，保留符号与量级信息
    其它（int/str/None）原样返回，避免影响 trade_count、日期区间等非浮点字段。
    """
    if isinstance(value, bool) or not isinstance(value, float):
        return value
    if not np.isfinite(value):
        return 0.0
    if value > _DB_DECIMAL_MAX:
        return _DB_DECIMAL_MAX
    if value < -_DB_DECIMAL_MAX:
        return -_DB_DECIMAL_MAX
    return value


def _sanitize_metrics(metrics):
    """对指标字典中的所有浮点值做有限化+夹断，原地返回安全字典。"""
    return {k: _safe_metric(v) for k, v in metrics.items()}


def calculate_metrics(nav_series, benchmark_series=None, trades=None,
                      risk_free_rate=_RISK_FREE_RATE, dates=None):
    """
    计算回测风险指标（聚宽风格）。

    Args:
        nav_series: list/array of daily NAV values (从1.0开始)
        benchmark_series: list/array of benchmark NAV values (可选)
        trades: list of TradeRecord (可选)
        risk_free_rate: 年化无风险利率
        dates: list of date 对象（用于计算最大回撤区间，可选）

    Returns:
        dict: 风险指标字典
    """
    nav = np.array(nav_series, dtype=float)
    n_days = len(nav)

    if n_days < 2:
        return _empty_metrics()

    # ── 收益率 ──
    if nav[0] == 0:
        return _empty_metrics()  # 初始净值为0，无法计算
    total_return = (nav[-1] / nav[0] - 1) * 100
    n_years = n_days / _TRADING_DAYS_PER_YEAR
    annual_return = ((nav[-1] / nav[0]) ** (1 / n_years) - 1) * 100 if n_years > 0 else 0

    # ── 日收益率（防御净值归零导致除零） ──
    safe_nav = nav[:-1].copy()
    safe_nav[safe_nav == 0] = np.nan
    daily_returns = np.diff(nav) / safe_nav
    daily_returns = np.nan_to_num(daily_returns, nan=0.0, posinf=0.0, neginf=0.0)

    # ── 策略波动率（年化） ──
    strategy_volatility = float(np.std(daily_returns) * np.sqrt(_TRADING_DAYS_PER_YEAR)) * 100

    # ── 最大回撤（含区间）──
    peak = np.maximum.accumulate(nav)
    drawdown = (nav - peak) / peak
    max_dd_idx = int(np.argmin(drawdown))
    max_drawdown = abs(float(drawdown[max_dd_idx])) * 100
    dd_start_idx = int(np.argmax(nav[:max_dd_idx + 1]))
    dd_end_idx = max_dd_idx

    max_drawdown_start = ''
    max_drawdown_end = ''
    if dates and dd_start_idx < len(dates) and dd_end_idx < len(dates):
        max_drawdown_start = str(dates[dd_start_idx])
        max_drawdown_end = str(dates[dd_end_idx])

    # ── 夏普比率 ──
    daily_rf = risk_free_rate / _TRADING_DAYS_PER_YEAR
    excess_returns = daily_returns - daily_rf
    sharpe = 0.0
    if len(excess_returns) > 1 and np.std(excess_returns) > 0:
        sharpe = float(np.mean(excess_returns) / np.std(excess_returns) * np.sqrt(_TRADING_DAYS_PER_YEAR))

    # ── 索提诺比率 ──
    sortino = 0.0
    downside_returns = excess_returns[excess_returns < 0]
    if len(downside_returns) > 0:
        downside_std = np.sqrt(np.mean(downside_returns ** 2))
        if downside_std > 0:
            sortino = float(np.mean(excess_returns) / downside_std * np.sqrt(_TRADING_DAYS_PER_YEAR))

    # ── 日胜率（仅计算有持仓变动的交易日，排除纯现金日） ──
    win_days = int(np.sum(daily_returns > 1e-10))
    active_days = int(np.sum(np.abs(daily_returns) > 1e-10))  # 有实质变动的天数
    daily_win_rate = win_days / active_days * 100 if active_days > 0 else 0

    # ── 基准相关指标 ──
    alpha = 0.0
    beta = 0.0
    benchmark_return = 0.0
    benchmark_annual_return = 0.0
    benchmark_volatility = 0.0
    excess_return = 0.0
    avg_daily_excess = 0.0
    excess_max_drawdown = 0.0
    excess_sharpe = 0.0
    information_ratio = 0.0

    has_bm = (benchmark_series is not None and len(benchmark_series) == n_days)
    if has_bm:
        bm = np.array(benchmark_series, dtype=float)
        if bm[0] == 0:
            has_bm = False  # 基准起始价为0，跳过基准指标
    if has_bm:
        benchmark_return = (bm[-1] / bm[0] - 1) * 100
        benchmark_annual_return = ((bm[-1] / bm[0]) ** (1 / n_years) - 1) * 100 if n_years > 0 else 0
        safe_bm = bm[:-1].copy()
        safe_bm[safe_bm == 0] = np.nan
        bm_daily = np.diff(bm) / safe_bm
        bm_daily = np.nan_to_num(bm_daily, nan=0.0, posinf=0.0, neginf=0.0)

        # 基准波动率（年化）
        benchmark_volatility = float(np.std(bm_daily) * np.sqrt(_TRADING_DAYS_PER_YEAR)) * 100

        # 超额收益
        excess_return = total_return - benchmark_return

        # 日超额收益
        daily_excess = daily_returns - bm_daily
        avg_daily_excess = float(np.mean(daily_excess)) * 100

        # 超额收益净值曲线
        excess_nav = np.cumprod(1 + daily_excess)
        excess_nav = np.insert(excess_nav, 0, 1.0)

        # 超额收益最大回撤（防御 excess_peak=0 的除零问题）
        excess_peak = np.maximum.accumulate(excess_nav)
        safe_excess_peak = excess_peak.copy()
        safe_excess_peak[safe_excess_peak == 0] = np.nan
        excess_dd = (excess_nav - excess_peak) / safe_excess_peak
        excess_dd = np.nan_to_num(excess_dd, nan=0.0)
        excess_max_drawdown = abs(float(np.min(excess_dd))) * 100

        # 超额收益夏普比率
        if len(daily_excess) > 1 and np.std(daily_excess) > 0:
            excess_sharpe = float(np.mean(daily_excess) / np.std(daily_excess)
                                  * np.sqrt(_TRADING_DAYS_PER_YEAR))

        # Alpha / Beta
        if len(bm_daily) > 1 and np.var(bm_daily) > 0:
            cov = np.cov(daily_returns, bm_daily)
            beta = float(cov[0, 1] / cov[1, 1])
            alpha_daily = np.mean(daily_returns) - daily_rf - beta * (np.mean(bm_daily) - daily_rf)
            alpha = float(alpha_daily * _TRADING_DAYS_PER_YEAR)

        # 信息比率
        if len(daily_excess) > 1:
            tracking_error = float(np.std(daily_excess) * np.sqrt(_TRADING_DAYS_PER_YEAR))
            if tracking_error > 0:
                information_ratio = (annual_return / 100 - benchmark_annual_return / 100) / tracking_error

    # ── 交易统计（按金额加权的配对盈亏）──
    trade_count = 0
    trade_win_count = 0
    trade_loss_count = 0
    total_profit = 0.0
    total_loss = 0.0
    profit_loss_ratio = 0.0

    if trades:
        # 配对买卖：FIFO 匹配同一只股票的 buy → sell
        buy_queue = {}  # code -> list of (price, amount, commission, slippage)
        for t in trades:
            if t.direction == 'buy':
                buy_queue.setdefault(t.code, []).append({
                    'price': t.price, 'amount': t.amount,
                    'commission': getattr(t, 'commission', 0) or 0,
                    'slippage': getattr(t, 'slippage_cost', 0) or 0,
                })
            elif t.direction == 'sell' and t.code in buy_queue and buy_queue[t.code]:
                buy = buy_queue[t.code].pop(0)
                trade_count += 1
                # 金额加权盈亏 = 卖出收入 - 买入成本 - 全部费用
                buy_cost = buy['price'] * buy['amount'] + buy['commission'] + buy['slippage']
                sell_income = (t.price * t.amount
                               - (getattr(t, 'commission', 0) or 0)
                               - (getattr(t, 'tax', 0) or 0)
                               - (getattr(t, 'slippage_cost', 0) or 0))
                pnl = sell_income - buy_cost
                if pnl > 0:
                    trade_win_count += 1
                    total_profit += pnl
                else:
                    trade_loss_count += 1
                    total_loss += abs(pnl)

        if trade_win_count > 0 and trade_loss_count > 0:
            avg_profit = total_profit / trade_win_count
            avg_loss = total_loss / trade_loss_count
            if avg_loss > 0:
                profit_loss_ratio = avg_profit / avg_loss

    trade_win_rate = trade_win_count / trade_count * 100 if trade_count > 0 else 0
    total_trades = len(trades) if trades else 0

    return _sanitize_metrics({
        'total_return': round(total_return, 4),
        'annual_return': round(annual_return, 4),
        'benchmark_return': round(benchmark_return, 4),
        'benchmark_annual_return': round(benchmark_annual_return, 4),
        'excess_return': round(excess_return, 4),
        'avg_daily_excess': round(avg_daily_excess, 4),
        'max_drawdown': round(max_drawdown, 4),
        'max_drawdown_start': max_drawdown_start,
        'max_drawdown_end': max_drawdown_end,
        'strategy_volatility': round(strategy_volatility, 4),
        'benchmark_volatility': round(benchmark_volatility, 4),
        'excess_max_drawdown': round(excess_max_drawdown, 4),
        'sharpe_ratio': round(sharpe, 4),
        'sortino_ratio': round(sortino, 4),
        'excess_sharpe_ratio': round(excess_sharpe, 4),
        'information_ratio': round(information_ratio, 4),
        'alpha': round(alpha, 4),
        'beta': round(beta, 4),
        'daily_win_rate': round(daily_win_rate, 2),
        'trade_win_rate': round(trade_win_rate, 2),
        'profit_loss_ratio': round(profit_loss_ratio, 4),
        'trade_count': total_trades,
        'win_count': trade_win_count,
        'loss_count': trade_loss_count,
        'trading_days': n_days,
    })


def _empty_metrics():
    return {
        'total_return': 0, 'annual_return': 0,
        'benchmark_return': 0, 'benchmark_annual_return': 0,
        'excess_return': 0, 'avg_daily_excess': 0,
        'max_drawdown': 0, 'max_drawdown_start': '', 'max_drawdown_end': '',
        'strategy_volatility': 0, 'benchmark_volatility': 0,
        'excess_max_drawdown': 0,
        'sharpe_ratio': 0, 'sortino_ratio': 0,
        'excess_sharpe_ratio': 0, 'information_ratio': 0,
        'alpha': 0, 'beta': 0,
        'daily_win_rate': 0, 'trade_win_rate': 0,
        'profit_loss_ratio': 0, 'trade_count': 0,
        'win_count': 0, 'loss_count': 0, 'trading_days': 0,
    }
