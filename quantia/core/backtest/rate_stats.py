#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import datetime
import logging
import numpy as np
import pandas as pd

__author__ = 'Quantia'
__date__ = '2026/02/14'

# ====================================================================
# 交易成本参数（A股）
# 用于回测时从收益率中扣除，模拟真实交易的摩擦成本。
#
# 佣金: 买卖各 0.025%（万2.5，大部分券商水平）
# 印花税: 卖出时 0.05%（2023年8月28日起减半）
# 滑点: 买卖各 0.05%（保守估计）
#
# 单次交易（买入+卖出）总成本:
#   买入: 佣金 0.025% + 滑点 0.05% = 0.075%
#   卖出: 佣金 0.025% + 印花税 0.05% + 滑点 0.05% = 0.125%
#   合计: 0.20%
# ====================================================================
import quantia.lib.envconfig as _cfg
COMMISSION_RATE = _cfg.get_float('QUANTIA_COMMISSION_RATE', 0.00025)   # 佣金比例（单边）
STAMP_TAX_RATE = _cfg.get_float('QUANTIA_STAMP_TAX_RATE', 0.0005)     # 印花税（卖出方）
SLIPPAGE_RATE = _cfg.get_float('QUANTIA_SLIPPAGE_RATE', 0.0005)       # 滑点（单边）

# 单次交易（买入+卖出）总成本百分比
ROUND_TRIP_COST_PCT = (COMMISSION_RATE + SLIPPAGE_RATE +    # 买入侧
                       COMMISSION_RATE + STAMP_TAX_RATE + SLIPPAGE_RATE  # 卖出侧
                       ) * 100  # 转为百分比，约 0.20%


def get_rates(code_name, data, stock_column, threshold=101):
    """
    计算选股信号的 N 日收益率序列。

    修正说明（v2）：
    1. 买入价使用信号日 T+1 的开盘价（而非 T 日收盘价），
       因为信号在 T 日收盘后产生，实盘最早在 T+1 开盘买入。
    2. 扣除交易成本（佣金+印花税+滑点），使回测更贴近真实收益。
    3. 过滤涨停/跌停：T+1 开盘涨停（无法买入）时返回 None。

    参数:
        code_name: (date, code) 元组，date 为信号日
        data: 含 date/open/close/high/low 的 DataFrame（已前复权）
        stock_column: 返回 Series 的列名列表 [date, code, rate_1, rate_2, ...]
        threshold: 最大回测天数+1

    返回:
        pd.Series: [date, code, rate_1, ..., rate_N]，其中 rate_N 为扣费后百分比收益
        None: 数据不足或无法交易
    """
    if data is None:
        return None

    try:
        start_date = code_name[0]
        code = code_name[1]
        stock_data_list = [start_date, code]

        # 统一 date 类型：缓存数据的 date 列可能是 datetime64/Timestamp/datetime.date，
        # 而 start_date 来自 SQL 结果转字符串（如 '2026-03-09'），
        # 混合类型无法直接比较，需统一为 pd.Timestamp。
        if not pd.api.types.is_datetime64_any_dtype(data['date']):
            data['date'] = pd.to_datetime(data['date'])
        if not isinstance(start_date, (pd.Timestamp, datetime.datetime)):
            start_date = pd.Timestamp(start_date)

        mask = (data['date'] >= start_date)
        data = data.loc[mask].copy()
        data = data.head(n=threshold)

        # 至少需要信号日(T) + 执行日(T+1) = 2 行
        if len(data.index) <= 1:
            return None

        # ----- 修正1: 使用 T+1 开盘价作为买入基准 -----
        # data.iloc[0] = 信号日(T)，data.iloc[1] = 执行日(T+1)
        if 'open' in data.columns:
            buy_price = data.iloc[1]['open']
            # 涨停检测：T+1 开盘价 >= T 收盘价 * 1.095（接近10%涨停）
            # 涨停时实际无法买入，回测应跳过
            t_close = data.iloc[0]['close']
            if buy_price > 0 and t_close > 0:
                gap_pct = (buy_price - t_close) / t_close
                if gap_pct >= 0.095:  # 涨停开盘，无法买入
                    return None
        else:
            # 缓存数据无 open 列时降级为 T 日收盘价（不推荐）
            buy_price = data.iloc[0]['close']

        if buy_price <= 0 or np.isnan(buy_price):
            return None

        # ----- 修正2: 计算收益率（从 T+1 开始）并扣除交易成本 -----
        # rate_N = N日持有收益 = (close[T+N] - buy_price) / buy_price * 100 - 交易成本
        # 注意：data.iloc[1] 对应 rate_1（持有1天），data.iloc[2] 对应 rate_2，...
        future_closes = data['close'].values[1:]  # T+1, T+2, ...
        raw_rates = np.around(100 * (future_closes - buy_price) / buy_price, decimals=2)
        # 扣除交易成本（每笔交易固定扣除，不随持有天数增加）
        net_rates = np.around(raw_rates - ROUND_TRIP_COST_PCT, decimals=2)

        for rate in net_rates:
            stock_data_list.append(rate)

        # 不足的部分填 None
        _l = len(stock_column) - len(stock_data_list)
        for i in range(0, _l):
            stock_data_list.append(None)

        return pd.Series(stock_data_list, index=stock_column)
    except Exception as e:
        logging.error(f"rate_stats.get_rates处理异常：{code_name}代码", exc_info=True)
        return None


def get_rates_with_exit(code_name, data, stock_column, threshold=101,
                        trailing_exit_days=20, stop_loss_pct=None):
    """
    计算带止损/止盈退出机制的 N 日收益率序列（海龟交易法则专用）。

    退出规则（经典海龟 System 2）：
    1. 趋势跟踪止盈/止损：持有期间收盘价跌破最近 trailing_exit_days 日最低价时卖出
    2. 固定止损（可选）：收盘价跌破买入价 * (1 - stop_loss_pct/100) 时卖出

    退出后 rate_N 锁定为退出当日的收益率（不再随后续价格变化）。

    参数:
        code_name: (date, code) 元组，date 为信号日
        data: 含 date/open/close/high/low 的 DataFrame（已前复权）
        stock_column: 返回 Series 的列名列表 [date, code, rate_1, rate_2, ...]
        threshold: 最大回测天数+1
        trailing_exit_days: 跟踪止损回看天数（默认20日，经典海龟 System 2）
        stop_loss_pct: 固定止损百分比（如 10 表示亏损10%强制退出），None 不启用

    返回:
        pd.Series: [date, code, rate_1, ..., rate_N]，退出后收益率锁定
        None: 数据不足或无法交易
    """
    if data is None:
        return None

    try:
        start_date = code_name[0]
        code = code_name[1]
        stock_data_list = [start_date, code]

        if not pd.api.types.is_datetime64_any_dtype(data['date']):
            data['date'] = pd.to_datetime(data['date'])
        if not isinstance(start_date, (pd.Timestamp, datetime.datetime)):
            start_date = pd.Timestamp(start_date)

        mask = (data['date'] >= start_date)
        data = data.loc[mask].copy()
        data = data.head(n=threshold)

        if len(data.index) <= 1:
            return None

        # 使用 T+1 开盘价作为买入基准
        if 'open' in data.columns:
            buy_price = data.iloc[1]['open']
            t_close = data.iloc[0]['close']
            if buy_price > 0 and t_close > 0:
                gap_pct = (buy_price - t_close) / t_close
                if gap_pct >= 0.095:
                    return None
        else:
            buy_price = data.iloc[0]['close']

        if buy_price <= 0 or np.isnan(buy_price):
            return None

        # 获取信号日之前的历史数据用于初始化滚动最低价窗口
        # data.iloc[0] = 信号日(T)，data.iloc[1] = T+1（买入日）
        # 需要信号日及之前的 trailing_exit_days 个交易日的 low 价来初始化窗口
        future_data = data.iloc[1:]  # T+1 开始
        future_closes = future_data['close'].values
        future_lows = future_data['low'].values if 'low' in data.columns else future_closes

        # 初始化滚动窗口：用信号日(T)及之前的 close 数据
        # 由于 data 已经从信号日开始截取，无法获取更早数据，
        # 用买入价作为初始窗口的基准（首日不会触发退出）
        exit_day = None  # 退出日的索引（在 future_closes 中的位置）
        exit_rate = None

        # 滚动最低价窗口：用 low 价序列计算
        # 前 trailing_exit_days 天建立窗口，之后开始检测退出
        for i in range(len(future_closes)):
            # 计算当前持有收益率
            current_rate = round(100 * (future_closes[i] - buy_price) / buy_price - ROUND_TRIP_COST_PCT, 2)

            # 固定止损检测
            if stop_loss_pct is not None:
                stop_price = buy_price * (1 - stop_loss_pct / 100)
                if future_closes[i] <= stop_price:
                    exit_day = i
                    exit_rate = current_rate
                    break

            # 跟踪止损检测：收盘价跌破最近 trailing_exit_days 日最低价
            # 从持有第 trailing_exit_days 天起开始检测（前面建立窗口）
            if i >= trailing_exit_days:
                window_lows = future_lows[max(0, i - trailing_exit_days):i]
                trailing_low = np.min(window_lows)
                if future_closes[i] < trailing_low:
                    exit_day = i
                    exit_rate = current_rate
                    break

        # 构建收益率序列
        for i in range(len(future_closes)):
            if exit_day is not None and i >= exit_day:
                # 退出后锁定退出日的收益率
                stock_data_list.append(exit_rate)
            else:
                r = round(100 * (future_closes[i] - buy_price) / buy_price - ROUND_TRIP_COST_PCT, 2)
                stock_data_list.append(r)

        # 不足的部分填 None
        _l = len(stock_column) - len(stock_data_list)
        for i in range(0, _l):
            stock_data_list.append(None)

        return pd.Series(stock_data_list, index=stock_column)
    except Exception as e:
        logging.error(f"rate_stats.get_rates_with_exit处理异常：{code_name}代码", exc_info=True)
        return None
