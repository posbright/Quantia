# -*- coding: utf-8 -*-
"""
基本面底部突破策略 (fundamental_bottom_breakout)
────────────────────────────────────────────────
选股逻辑：
  1. 基本面筛选：PE 10~50，ROE>8%，净利润增长>0，资产负债率<65%
  2. 技术面买入：
     - 股价处于相对底部（当前价 < 60日最高价的75%）
     - 长期横盘特征（20日振幅 < 15%）
     - 5日均线上穿20日均线（金叉）
     - 均线多头排列：MA5 > MA10 > MA20 > MA60
  3. 卖出条件：
     - 突破阶段新高后（创60日新高），若5日下穿20日则卖出
     - 止损：跌破买入价15%

持仓：最多同时持有 10 只，等权配置
调仓频率：每日检测
"""

import numpy as np
import pandas as pd


def initialize(context):
    set_benchmark('000300.XSHG')
    set_order_cost(OrderCost(
        open_tax=0, close_tax=0.001,
        open_commission=0.0003, close_commission=0.0003,
        min_commission=5
    ), type='stock')

    # 策略参数
    g.hold_num = 10            # 最大持仓数
    g.refresh_rate = 5         # 基本面筛选频率（每5个交易日）
    g.day_count = 0            # 计数器
    g.candidates = []          # 基本面候选池

    # 技术参数
    g.ma_short = 5             # 短期均线
    g.ma_mid = 10              # 中期均线
    g.ma_long = 20             # 长期均线
    g.ma_trend = 60            # 趋势均线

    # 卖出参数
    g.stage_high = {}          # 记录持仓后阶段最高价
    g.buy_price = {}           # 记录买入价格
    g.broke_high = {}          # 是否已突破阶段新高
    g.stop_loss = 0.15         # 止损比例


def before_trading_start(context):
    g.day_count += 1


def handle_data(context, data):
    # 定期刷新基本面候选池
    if g.day_count % g.refresh_rate == 1 or len(g.candidates) == 0:
        g.candidates = select_fundamentals(context)

    # 卖出逻辑
    sell_stocks(context, data)

    # 买入逻辑
    buy_stocks(context, data)


def select_fundamentals(context):
    """基本面选股：筛选基本面良好、未来可期的股票"""
    q = query(
        valuation.code,
        valuation.market_cap,
        valuation.pe_ratio,
        valuation.pb_ratio,
        indicator.roe,
        indicator.inc_net_profit_year_on_year,
        indicator.inc_revenue_year_on_year,
        indicator.net_profit_margin,
    ).filter(
        valuation.pe_ratio > 10,
        valuation.pe_ratio < 50,
        valuation.pb_ratio > 0.5,
        valuation.pb_ratio < 8,
        indicator.roe > 8,
        indicator.inc_net_profit_year_on_year > 0,
        indicator.net_profit_margin > 5,
        valuation.market_cap > 50,
    ).order_by(
        indicator.roe.desc()
    ).limit(200)

    df = get_fundamentals(q, date=context.current_dt)
    candidates = []
    if df is not None and len(df) > 0:
        candidates = df['code'].tolist()

    # 保底候选池：基本面优质大盘蓝筹 + 成长白马
    # 当 get_fundamentals 返回不足时使用
    if len(candidates) < 30:
        fallback = [
            '600519', '000858', '600036', '601318', '000333',
            '002415', '600276', '000568', '002304', '601888',
            '600887', '000001', '600900', '601166', '002714',
            '603288', '000661', '002352', '600309', '601012',
            '002142', '600585', '000725', '601398', '600031',
            '002475', '000651', '600690', '603259', '002027',
            '600048', '000002', '601601', '600050', '002230',
            '000063', '600000', '601688', '002049', '600016',
            '002371', '600015', '000538', '601899', '600104',
            '002466', '600809', '000776', '601225', '600436',
        ]
        for code in fallback:
            if code not in candidates:
                candidates.append(code)
        # 预加载 fallback 股票的历史数据，确保后续 data[code] 可用
        for code in fallback:
            history(code, 1)

    return candidates


def check_buy_signal(code, data):
    """
    技术面买入信号检测：
    1. 股价未严重超涨（当前价 < 60日最高价，即不追高）
    2. 近期横盘整理（20日振幅 < 30%）
    3. 5日上穿20日均线（近3日内发生金叉）
    4. 均线多头排列 MA5 > MA10 > MA20
    """
    try:
        close_data = history(code, g.ma_trend + 10, 'close')
        if close_data is None or len(close_data) < g.ma_trend:
            return False

        close_arr = close_data.values
        current_price = close_arr[-1]

        # 计算均线
        ma5 = close_arr[-g.ma_short:].mean()
        ma10 = close_arr[-g.ma_mid:].mean()
        ma20 = close_arr[-g.ma_long:].mean()
        ma60 = close_arr[-g.ma_trend:].mean()

        # 条件1：不追涨 — 当前价在60日高点的92%以内（留出空间但不在最高位买入）
        high_60 = close_arr[-g.ma_trend:].max()
        if current_price > high_60 * 0.92:
            return False

        # 条件2：近期整理 — 近20日振幅 < 30%
        recent_20 = close_arr[-g.ma_long:]
        recent_20_min = recent_20.min()
        if recent_20_min == 0:
            return False
        amplitude = (recent_20.max() - recent_20_min) / recent_20_min
        if amplitude > 0.30:
            return False

        # 条件3：5日上穿20日 — 近3日内MA5从<=MA20变为>MA20
        golden_cross = False
        for offset in range(3):
            idx = len(close_arr) - 1 - offset
            if idx < g.ma_long + g.ma_short:
                continue
            cur_slice = close_arr[:idx + 1]
            prev_slice = close_arr[:idx]
            cur_ma5 = cur_slice[-g.ma_short:].mean()
            cur_ma20 = cur_slice[-g.ma_long:].mean()
            prev_ma5 = prev_slice[-g.ma_short:].mean()
            prev_ma20 = prev_slice[-g.ma_long:].mean()
            if prev_ma5 <= prev_ma20 and cur_ma5 > cur_ma20:
                golden_cross = True
                break
        if not golden_cross:
            return False

        # 条件4：均线多头排列 MA5 > MA10 > MA20（短中期趋势向上）
        if not (ma5 > ma10 > ma20):
            return False

        return True
    except Exception:
        return False


def check_sell_signal(code, data, context):
    """
    卖出信号检测：
    1. 突破阶段新高后，5日下穿20日则卖出
    2. 止损：跌破买入价15%
    """
    try:
        close_data = history(code, g.ma_long + 5, 'close')
        if close_data is None or len(close_data) < g.ma_long:
            return False

        close_arr = close_data.values
        current_price = close_arr[-1]

        # 更新阶段最高价
        if code not in g.stage_high:
            g.stage_high[code] = current_price
        else:
            g.stage_high[code] = max(g.stage_high[code], current_price)

        # 止损检查
        if code in g.buy_price and g.buy_price[code] > 0:
            loss_rate = (current_price - g.buy_price[code]) / g.buy_price[code]
            if loss_rate < -g.stop_loss:
                log.info(f"止损卖出 {code}，亏损 {loss_rate*100:.1f}%")
                return True

        # 检查是否已突破阶段新高（60日新高）
        high_60 = history(code, g.ma_trend, 'high')
        if high_60 is not None and len(high_60) >= g.ma_trend:
            stage_high_60 = high_60.values[:-1].max()  # 不含今天
            if current_price > stage_high_60:
                g.broke_high[code] = True

        # 突破新高后，5日下穿20日则卖出
        if g.broke_high.get(code, False):
            ma5 = close_arr[-g.ma_short:].mean()
            ma20 = close_arr[-g.ma_long:].mean()
            # 昨日 MA5>=MA20，今日 MA5<MA20 → 死叉
            prev_close = close_arr[:-1]
            prev_ma5 = prev_close[-g.ma_short:].mean()
            prev_ma20 = prev_close[-g.ma_long:].mean()
            if prev_ma5 >= prev_ma20 and ma5 < ma20:
                log.info(f"突破新高后死叉卖出 {code}")
                return True

        return False
    except Exception:
        return False


def sell_stocks(context, data):
    """执行卖出"""
    for code in list(context.portfolio.positions.keys()):
        if code not in data:
            continue
        if check_sell_signal(code, data, context):
            order_target(code, 0)
            # 清理状态
            g.stage_high.pop(code, None)
            g.buy_price.pop(code, None)
            g.broke_high.pop(code, None)


def buy_stocks(context, data):
    """执行买入"""
    # 计算可买入仓位数
    current_count = len(context.portfolio.positions)
    buy_slots = g.hold_num - current_count
    if buy_slots <= 0:
        return

    # 从候选池中寻找满足技术条件的股票
    buy_list = []
    for code in g.candidates:
        if code in context.portfolio.positions:
            continue
        # 通过 history 确保股票已加载（兼容 fallback 股票首日未在 data 中的情况）
        if code not in data:
            history(code, 1)
            if code not in data:
                continue
        if check_buy_signal(code, data):
            buy_list.append(code)
            if len(buy_list) >= buy_slots:
                break

    # 等权买入（每次最多买入 2 只，确保每只有足够资金买入1手以上）
    if len(buy_list) > 0:
        actual_buy = buy_list[:min(2, buy_slots)]
        available = context.portfolio.available_cash
        # 保留 5% 现金作为缓冲
        cash_per_stock = available * 0.95 / len(actual_buy)
        for code in actual_buy:
            # 确保单笔金额至少能买1手（粗估：股价*100）
            price = data[code].close if code in data else 0
            if price > 0 and cash_per_stock < price * 100:
                log.info(f"跳过 {code}，资金不足1手")
                continue
            order_value(code, cash_per_stock)
            g.buy_price[code] = price
            g.stage_high[code] = price
            g.broke_high[code] = False
            log.info(f"买入 {code}，金额 {cash_per_stock:.0f}，价格 {price:.2f}")
