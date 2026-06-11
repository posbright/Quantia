#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
组合回测 & 策略管理 API Handler

提供策略代码 CRUD、组合回测运行、回测结果查询等 API。
"""

import json
import logging
import datetime
import traceback
import uuid
import time as _time
import hashlib
from abc import ABC
from tornado import gen, ioloop
import quantia.web.base as webBase
import quantia.lib.database as mdb
from quantia.core.backtest.boll_lower_band_strategy import BOLL_LOWER_BAND_VALUE_TEMPLATE

__author__ = 'Quantia'
__date__ = '2026/03/13'

# ── 运行中回测任务注册表（用于日志实时流） ──
# { task_id: { 'engine': PortfolioBacktestEngine, 'status': 'running'|'done', 'result': dict|None } }
_running_tasks = {}

# ── 内置策略模板 ──
STRATEGY_TEMPLATES = [
    BOLL_LOWER_BAND_VALUE_TEMPLATE,
    {
        'id': 'small_cap',
        'name': '小市值策略',
        'category': 'stock',
        'description': '每月初选出市值最小的5只股票等权买入，月末调仓',
        'code': '''# 小市值策略
# 思路：长期来看小市值股票超额收益显著
# 每月初调仓：卖出持仓，买入市值最小的N只

def initialize(context):
    # 候选股票池
    context.stocks = ['000001', '000002', '600000', '600036', '601318',
                      '600519', '000858', '002594', '300750', '601888',
                      '000568', '002304', '603259', '601012', '300059']
    context.hold_num = 5  # 持仓数量
    context.day_count = 0

def handle_data(context, data):
    context.day_count += 1
    # 每20个交易日调仓一次（约一个月）
    if context.day_count % 20 != 1:
        return

    # 获取各股票最新价格，按价格排序（模拟市值排序）
    prices = {}
    for code in context.stocks:
        if code in data and data[code].close > 0:
            prices[code] = data[code].close

    if len(prices) < context.hold_num:
        return

    # 选出价格最低的N只（模拟小市值）
    selected = sorted(prices, key=prices.get)[:context.hold_num]

    # 卖出不在选中列表中的股票
    for code in list(context.portfolio.positions.keys()):
        if code not in selected:
            order_target(code, 0)
            log.info("卖出 " + code)

    # 等权买入选中的股票
    target_value = context.portfolio.total_value / context.hold_num
    for code in selected:
        order_target_value(code, target_value)

    log.info("调仓完成，持仓: " + str(selected))
''',
    },
    {
        'id': 'dual_ma',
        'name': '双均线策略',
        'category': 'stock',
        'description': '5日均线上穿20日均线（金叉）买入，下穿（死叉）卖出',
        'code': '''# 双均线策略
# 经典技术分析策略：利用短期和长期均线的交叉信号
# 金叉（短期上穿长期）买入，死叉（短期下穿长期）卖出

def initialize(context):
    context.security = '000001'  # 平安银行

def handle_data(context, data):
    security = context.security
    # 获取收盘价
    close_data = history(security, 21, 'close')
    if len(close_data) < 21:
        return

    # 计算5日和20日均线
    MA5 = close_data[-5:].mean()
    MA20 = close_data.mean()

    # 取得当前价格和现金
    current_price = data[security].close
    cash = context.portfolio.available_cash

    # 金叉：5日均线上穿20日均线，买入
    if MA5 > MA20 and security not in context.portfolio.positions:
        order_value(security, cash * 0.95)
        log.info("金叉买入 " + security + " 价格: " + str(round(current_price, 2)))

    # 死叉：5日均线下穿20日均线，卖出
    elif MA5 < MA20 and security in context.portfolio.positions:
        order_target(security, 0)
        log.info("死叉卖出 " + security + " 价格: " + str(round(current_price, 2)))
''',
    },
    {
        'id': 'bank_rotation',
        'name': '银行股轮动策略(聚宽)',
        'category': 'stock',
        'description': '持有中证银行指数(399951)成份股中PB最低的银行股，每周一轮动',
        'code': '''# 银行股轮动策略（聚宽风格）
# 策略来源：聚宽 JoinQuant 经典银行轮动策略
# 原理：在中证银行指数(399951)成份股中选择PB最低的1只持有，每周一轮动
# 低PB银行股通常具有更高的安全边际和股息率

def initialize(context):
    set_benchmark('399951.XSHE')  # 中证银行指数
    set_option('use_real_price', True)
    set_order_cost(OrderCost(
        open_tax=0,
        close_tax=0.001,
        open_commission=0.0003,
        close_commission=0.0003,
        close_today_commission=0,
        min_commission=5
    ), type='stock')
    run_weekly(check_stocks, weekday=1, time='before_open')
    run_weekly(trade, weekday=1, time='open')

def check_stocks(context):
    g.stocks = get_index_stocks('399951.XSHE')
    if len(g.stocks) > 0:
        g.df = get_fundamentals(
            query(
                valuation.code,
                valuation.pb_ratio
            ).filter(
                valuation.code.in_(g.stocks)
            ).order_by(
                valuation.pb_ratio.asc()
            )
        )
        if len(g.df) > 0:
            g.code = g.df["code"].iloc[0]
            log.info("选股: " + g.code + " PB=" + str(round(g.df["pb_ratio"].iloc[0], 3)))

def trade(context):
    if not hasattr(g, "code") or not hasattr(g, "stocks"):
        return
    if len(g.stocks) > 0:
        code = g.code
        for stock in list(context.portfolio.positions.keys()):
            if stock != code:
                order_target(stock, 0)
                log.info("轮出 " + stock)
        if len(context.portfolio.positions) > 0:
            return
        else:
            order_value(code, context.portfolio.cash)
            log.info("买入 " + code + " 金额=" + str(round(context.portfolio.cash)))
''',
    },
    {
        'id': 'equal_weight',
        'name': '多股票等权配置',
        'category': 'portfolio',
        'description': '将资金等分配置到多只股票，定期再平衡',
        'code': '''# 多股票等权配置策略
def initialize(context):
    context.stocks = ['600519', '000858', '601318', '600036', '300750']
    context.rebalance_days = 0

def handle_data(context, data):
    context.rebalance_days += 1
    if context.rebalance_days % 20 != 1:
        return
    target = context.portfolio.total_value / len(context.stocks)
    for code in context.stocks:
        if code in data:
            order_target_value(code, target)
    log.info("调仓: 目标每只 " + str(round(target)) + " 元")
''',
    },
    {
        'id': 'momentum',
        'name': '动量策略',
        'category': 'multi_factor',
        'description': '买入近20日涨幅最大的股票，持有20日后换仓',
        'code': '''# 动量策略
def initialize(context):
    context.stocks = ['600519', '000858', '601318', '600036', '300750',
                      '000001', '600000', '601888', '002594', '300059']
    context.hold_days = 0

def handle_data(context, data):
    context.hold_days += 1
    if context.hold_days % 20 != 1:
        return
    momentum = {}
    for code in context.stocks:
        h = history(code, 20, 'close')
        if len(h) >= 20 and h.iloc[0] > 0:
            momentum[code] = (h.iloc[-1] / h.iloc[0] - 1)
    if not momentum:
        return
    top3 = sorted(momentum, key=momentum.get, reverse=True)[:3]
    for code in list(context.portfolio.positions.keys()):
        if code not in top3:
            order_target(code, 0)
    target = context.portfolio.total_value / 3
    for code in top3:
        order_target_value(code, target)
    log.info("动量选股: " + str(top3))
''',
    },
    {
        'id': 'fundamental_momentum',
        'name': '基本面筛选动量策略',
        'category': 'multi_factor',
        'description': '通过基本面指标（ROE、净利润增速、市盈率）从全市场筛选优质股票，再按动量排序选出前10只，每20个交易日调仓',
        'code': '''# 基本面筛选动量策略
# 1. 从全市场筛选基本面优质股票：ROE>8%、净利润正增长、PE合理(0-60)
# 2. 在优质股票池中按近20日动量排序，选出前10只
# 3. 等权持有，每20个交易日调仓一次
import jqdata

def initialize(context):
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001,
                             open_commission=0.0003, close_commission=0.0003,
                             close_today_commission=0, min_commission=5), type='stock')
    g.hold_num = 10          # 持股数量
    g.refresh_rate = 20      # 调仓周期（交易日）
    g.days = 0
    run_daily(rebalance, 'every_bar')

def get_fundamental_pool(context):
    """基本面筛选：ROE>8、净利润同比增速>0、PE在0-60之间、市值>30亿"""
    q = query(
        valuation.code,
        valuation.market_cap,
        valuation.pe_ratio,
        indicator.roe,
        indicator.inc_net_profit_year_on_year
    ).filter(
        indicator.roe > 8,
        indicator.inc_net_profit_year_on_year > 0,
        valuation.pe_ratio > 0,
        valuation.pe_ratio < 60,
        valuation.market_cap > 30
    ).order_by(
        indicator.roe.desc()
    ).limit(100)
    df = get_fundamentals(q)
    if df is None or len(df) == 0:
        return []
    stock_list = list(df['code'])
    # 过滤停牌股票
    stock_list = filter_paused(stock_list)
    return stock_list

def filter_paused(stock_list):
    """过滤停牌股票"""
    current_data = get_current_data()
    return [s for s in stock_list if not current_data[s].paused]

def select_by_momentum(stock_list, top_n):
    """在基本面股票池中按近20日动量排序，选出前N只"""
    momentum = {}
    for code in stock_list:
        h = history(code, 20, 'close')
        if len(h) >= 20 and h.iloc[0] > 0:
            momentum[code] = h.iloc[-1] / h.iloc[0] - 1
    if not momentum:
        return []
    ranked = sorted(momentum, key=momentum.get, reverse=True)
    return ranked[:top_n]

def rebalance(context):
    g.days += 1
    if g.days % g.refresh_rate != 1:
        return

    # 第一步：基本面筛选
    pool = get_fundamental_pool(context)
    if not pool:
        log.info("基本面筛选无结果，跳过调仓")
        return

    # 第二步：动量排序选股
    targets = select_by_momentum(pool, g.hold_num)
    if not targets:
        log.info("动量排序无结果，跳过调仓")
        return

    log.info("基本面+动量选股: " + str(targets))

    # 卖出不在目标列表中的持仓
    for code in list(context.portfolio.positions.keys()):
        if code not in targets:
            order_target(code, 0)
            log.info("调仓卖出 " + code)

    # 等权买入目标股票
    target_value = context.portfolio.total_value / g.hold_num
    for code in targets:
        order_target_value(code, target_value)
''',
    },
    {
        'id': 'small_cap_jq',
        'name': '小市值策略(聚宽)',
        'category': 'stock',
        'description': '筛选市值介于20-30亿的股票，选取市值最小的3只，持有5个交易日后调仓（需要基本面数据支持）',
        'code': '''# 小市值策略(聚宽)
# 筛选出市值介于20-30亿的股票，选取其中市值最小的三只股票
# 每天开盘买入，持有五个交易日，然后调仓

def initialize(context):
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    set_option('order_volume_ratio', 1)
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001,
                             open_commission=0.0003, close_commission=0.0003,
                             close_today_commission=0, min_commission=5), type='stock')
    g.stocknum = 3
    g.days = 0
    g.refresh_rate = 5
    run_daily(trade, 'every_bar')

def check_stocks(context):
    q = query(
        valuation.code,
        valuation.market_cap
    ).filter(
        valuation.market_cap.between(20, 30)
    ).order_by(
        valuation.market_cap.asc()
    )
    df = get_fundamentals(q)
    buylist = list(df['code'])
    buylist = filter_paused_stock(buylist)
    return buylist[:g.stocknum]

def trade(context):
    if g.days % g.refresh_rate == 0:
        sell_list = list(context.portfolio.positions.keys())
        if len(sell_list) > 0:
            for stock in sell_list:
                order_target_value(stock, 0)

        if len(context.portfolio.positions) < g.stocknum:
            Num = g.stocknum - len(context.portfolio.positions)
            Cash = context.portfolio.cash / Num
        else:
            Cash = 0

        stock_list = check_stocks(context)

        for stock in stock_list:
            if len(context.portfolio.positions.keys()) < g.stocknum:
                order_value(stock, Cash)

        g.days = 1
    else:
        g.days += 1

def filter_paused_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list if not current_data[stock].paused]
''',
    },
    # ── 策略选股模板（兼容聚宽 + 本地引擎，基于 document/策略选股说明.md） ──
    {
        'id': 'turtle_trade',
        'name': '海龟交易法则',
        'category': 'stock',
        'description': '经典趋势突破策略：当日收盘价创60日新高时买入，跌破20日最低价时卖出。对应策略选股 S07。',
        'code': '''# 海龟交易法则（策略选股模板 S07）
# 买入：收盘价创60日新高
# 卖出：收盘价跌破20日最低价（经典海龟退出）
# 风险控制：止损-10%，单票仓位≤20%，最多持5只
# 兼容聚宽 + 本地回测引擎
import jqdata

def initialize(context):
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001,
                             open_commission=0.0003, close_commission=0.0003,
                             close_today_commission=0, min_commission=5), type='stock')
    # 动态股票池：从本地缓存/聚宽获取全部可用股票（统一为聚宽格式 XXXXXX.XSHG/XSHE）
    try:
        _raw = get_all_cached_stocks()
        g.stocks = [c + ('.XSHG' if c[0] == '6' else '.XSHE') for c in _raw]
    except Exception:
        g.stocks = list(get_all_securities().index)
    g.entry_window = 60
    g.exit_window = 20
    g.max_positions = 5
    g.stop_loss = -0.10
    run_daily(market_open, time='every_bar')

def market_open(context):
    # ── 先检查卖出 ──
    for code in list(context.portfolio.positions.keys()):
        pos = context.portfolio.positions[code]
        if pos.avg_cost <= 0:
            continue
        profit_rate = (pos.price - pos.avg_cost) / pos.avg_cost
        # 止损
        if profit_rate <= g.stop_loss:
            order_target(code, 0)
            log.info("止损卖出 " + code + " 盈亏:" + str(round(profit_rate * 100, 1)) + "%")
            continue
        # 跌破20日最低价退出
        h = attribute_history(code, g.exit_window, '1d', ['close'])
        if len(h) >= g.exit_window and pos.price <= h['close'].min():
            order_target(code, 0)
            log.info("跌破" + str(g.exit_window) + "日低点卖出 " + code)

    # ── 再检查买入 ──
    current_count = len(context.portfolio.positions)
    if current_count >= g.max_positions:
        return

    for code in g.stocks:
        if code in context.portfolio.positions:
            continue
        if current_count >= g.max_positions:
            break
        h = attribute_history(code, g.entry_window, '1d', ['close'])
        if len(h) < g.entry_window:
            continue
        current_price = h['close'].iloc[-1]
        if current_price <= 0:
            continue
        # 创60日新高
        if current_price >= h['close'].max():
            cash_per = context.portfolio.total_value / g.max_positions
            order_value(code, min(cash_per, context.portfolio.available_cash * 0.95))
            current_count += 1
            log.info("突破" + str(g.entry_window) + "日新高买入 " + code)
''',
    },
    {
        'id': 'volume_increase',
        'name': '放量上涨',
        'category': 'stock',
        'description': '量价策略：涨幅≥2%、成交额≥2亿、量比≥2时买入，止盈15%/止损7%。对应策略选股 S01。',
        'code': '''# 放量上涨（策略选股模板 S01）
# 买入：涨幅≥2% + 阳线 + 成交额≥2亿 + 量比≥2
# 卖出：止盈+15%，止损-7%，最长持有20日
# 兼容聚宽 + 本地回测引擎
import jqdata

def initialize(context):
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001,
                             open_commission=0.0003, close_commission=0.0003,
                             close_today_commission=0, min_commission=5), type='stock')
    # 动态股票池：从本地缓存/聚宽获取全部可用股票（统一为聚宽格式 XXXXXX.XSHG/XSHE）
    try:
        _raw = get_all_cached_stocks()
        g.stocks = [c + ('.XSHG' if c[0] == '6' else '.XSHE') for c in _raw]
    except Exception:
        g.stocks = list(get_all_securities().index)
    g.max_positions = 5
    g.take_profit = 0.15
    g.stop_loss = -0.07
    g.max_hold_days = 20
    g.hold_days = {}
    run_daily(market_open, time='every_bar')

def market_open(context):
    # ── 更新持有天数并检查卖出 ──
    for code in list(context.portfolio.positions.keys()):
        g.hold_days[code] = g.hold_days.get(code, 0) + 1
        pos = context.portfolio.positions[code]
        if pos.avg_cost <= 0:
            continue
        profit_rate = (pos.price - pos.avg_cost) / pos.avg_cost
        if profit_rate >= g.take_profit:
            order_target(code, 0)
            log.info("止盈卖出 " + code + " +" + str(round(profit_rate * 100, 1)) + "%")
            g.hold_days.pop(code, None)
            continue
        if profit_rate <= g.stop_loss:
            order_target(code, 0)
            log.info("止损卖出 " + code + " " + str(round(profit_rate * 100, 1)) + "%")
            g.hold_days.pop(code, None)
            continue
        if g.hold_days.get(code, 0) >= g.max_hold_days:
            order_target(code, 0)
            log.info("超时卖出 " + code)
            g.hold_days.pop(code, None)

    # ── 检查买入信号 ──
    current_count = len(context.portfolio.positions)
    if current_count >= g.max_positions:
        return

    for code in g.stocks:
        if code in context.portfolio.positions or current_count >= g.max_positions:
            continue
        h = attribute_history(code, 6, '1d', ['close', 'open', 'volume'])
        if len(h) < 2:
            continue
        price = h['close'].iloc[-1]
        open_p = h['open'].iloc[-1]
        vol_today = h['volume'].iloc[-1]
        prev_close = h['close'].iloc[-2]
        if price <= 0 or prev_close <= 0 or open_p <= 0:
            continue

        # 条件1：涨幅≥2% 且 阳线
        pct_change = (price - prev_close) / prev_close
        if pct_change < 0.02 or price <= open_p:
            continue

        # 条件2：成交额≥2亿（close * volume 近似）
        amount = price * vol_today
        if amount < 200000000:
            continue

        # 条件3：量比≥2
        vol_ma5 = h['volume'].iloc[:-1].mean()
        if vol_ma5 <= 0:
            continue
        vol_ratio = vol_today / vol_ma5
        if vol_ratio < 2:
            continue

        cash_per = context.portfolio.total_value / g.max_positions
        order_value(code, min(cash_per, context.portfolio.available_cash * 0.95))
        g.hold_days[code] = 0
        current_count += 1
        log.info("放量上涨买入 " + code + " 涨幅:" + str(round(pct_change * 100, 1))
                 + "% 量比:" + str(round(vol_ratio, 1)))
''',
    },
    {
        'id': 'trend_pullback',
        'name': '趋势回调',
        'category': 'stock',
        'description': '上涨趋势中的缩量回调买点：MA20>MA60，价格回踩MA20附近，RSI中性，缩量。对应策略选股 S11。',
        'code': '''# 趋势回调（策略选股模板 S11）
# 买入：MA20>MA60 + 价格在MA20±3% + RSI(14)在35~55 + 缩量
# 卖出：止盈+15%，止损-7%，最长持有20日
# 兼容聚宽 + 本地回测引擎
import jqdata

def initialize(context):
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001,
                             open_commission=0.0003, close_commission=0.0003,
                             close_today_commission=0, min_commission=5), type='stock')
    # 动态股票池：从本地缓存/聚宽获取全部可用股票（统一为聚宽格式 XXXXXX.XSHG/XSHE）
    try:
        _raw = get_all_cached_stocks()
        g.stocks = [c + ('.XSHG' if c[0] == '6' else '.XSHE') for c in _raw]
    except Exception:
        g.stocks = list(get_all_securities().index)
    g.max_positions = 5
    g.take_profit = 0.15
    g.stop_loss = -0.07
    g.max_hold_days = 20
    g.hold_days = {}
    run_daily(market_open, time='every_bar')

def _calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50
    deltas = []
    for i in range(1, len(closes)):
        deltas.append(closes.iloc[i] - closes.iloc[i - 1])
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def market_open(context):
    # ── 卖出检查 ──
    for code in list(context.portfolio.positions.keys()):
        g.hold_days[code] = g.hold_days.get(code, 0) + 1
        pos = context.portfolio.positions[code]
        if pos.avg_cost <= 0:
            continue
        profit_rate = (pos.price - pos.avg_cost) / pos.avg_cost
        if profit_rate >= g.take_profit:
            order_target(code, 0)
            log.info("止盈 " + code + " +" + str(round(profit_rate * 100, 1)) + "%")
            g.hold_days.pop(code, None)
            continue
        if profit_rate <= g.stop_loss:
            order_target(code, 0)
            log.info("止损 " + code + " " + str(round(profit_rate * 100, 1)) + "%")
            g.hold_days.pop(code, None)
            continue
        if g.hold_days.get(code, 0) >= g.max_hold_days:
            order_target(code, 0)
            log.info("超时卖出 " + code)
            g.hold_days.pop(code, None)

    # ── 买入检查 ──
    current_count = len(context.portfolio.positions)
    if current_count >= g.max_positions:
        return

    for code in g.stocks:
        if code in context.portfolio.positions or current_count >= g.max_positions:
            continue
        h = attribute_history(code, 61, '1d', ['close', 'volume'])
        if len(h) < 61:
            continue

        price = h['close'].iloc[-1]
        if price <= 0:
            continue

        ma20 = h['close'].iloc[-20:].mean()
        ma60 = h['close'].mean()
        if ma20 <= ma60:
            continue
        deviation = abs(price - ma20) / ma20
        if deviation > 0.03:
            continue

        rsi = _calc_rsi(h['close'], 14)
        if rsi < 35 or rsi > 55:
            continue

        vol_today = h['volume'].iloc[-1]
        vol_ma5 = h['volume'].iloc[-6:-1].mean()
        if vol_ma5 > 0 and vol_today >= vol_ma5 * 0.8:
            continue

        cash_per = context.portfolio.total_value / g.max_positions
        order_value(code, min(cash_per, context.portfolio.available_cash * 0.95))
        g.hold_days[code] = 0
        current_count += 1
        log.info("趋势回调买入 " + code + " RSI=" + str(round(rsi, 1))
                 + " 偏离MA20:" + str(round(deviation * 100, 1)) + "%")
''',
    },
    {
        'id': 'oversold_rebound',
        'name': '超跌反弹',
        'category': 'stock',
        'description': '逆向策略：RSI<30极度超卖 + 布林带下轨回升 + 阳线放量反弹时买入。对应策略选股 S12。',
        'code': '''# 超跌反弹（策略选股模板 S12）
# 买入：RSI<30 + 近5日触及布林下轨 + 当日收回下轨 + 阳线 + 放量
# 卖出：止盈+10%，止损-5%，最长持有10日
# 兼容聚宽 + 本地回测引擎
import jqdata

def initialize(context):
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001,
                             open_commission=0.0003, close_commission=0.0003,
                             close_today_commission=0, min_commission=5), type='stock')
    # 动态股票池：从本地缓存/聚宽获取全部可用股票（统一为聚宽格式 XXXXXX.XSHG/XSHE）
    try:
        _raw = get_all_cached_stocks()
        g.stocks = [c + ('.XSHG' if c[0] == '6' else '.XSHE') for c in _raw]
    except Exception:
        g.stocks = list(get_all_securities().index)
    g.max_positions = 5
    g.take_profit = 0.10
    g.stop_loss = -0.05
    g.max_hold_days = 10
    g.hold_days = {}
    run_daily(market_open, time='every_bar')

def _calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50
    deltas = []
    for i in range(1, len(closes)):
        deltas.append(closes.iloc[i] - closes.iloc[i - 1])
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def _calc_bollinger(closes, period=20, num_std=2):
    if len(closes) < period:
        return None, None, None
    recent = closes.iloc[-period:]
    ma = recent.mean()
    std = recent.std()
    return ma, ma + num_std * std, ma - num_std * std

def market_open(context):
    # ── 卖出检查 ──
    for code in list(context.portfolio.positions.keys()):
        g.hold_days[code] = g.hold_days.get(code, 0) + 1
        pos = context.portfolio.positions[code]
        if pos.avg_cost <= 0:
            continue
        profit_rate = (pos.price - pos.avg_cost) / pos.avg_cost
        if profit_rate >= g.take_profit:
            order_target(code, 0)
            log.info("止盈 " + code + " +" + str(round(profit_rate * 100, 1)) + "%")
            g.hold_days.pop(code, None)
            continue
        if profit_rate <= g.stop_loss:
            order_target(code, 0)
            log.info("止损 " + code + " " + str(round(profit_rate * 100, 1)) + "%")
            g.hold_days.pop(code, None)
            continue
        if g.hold_days.get(code, 0) >= g.max_hold_days:
            order_target(code, 0)
            log.info("超时卖出 " + code)
            g.hold_days.pop(code, None)

    # ── 买入检查 ──
    current_count = len(context.portfolio.positions)
    if current_count >= g.max_positions:
        return

    for code in g.stocks:
        if code in context.portfolio.positions or current_count >= g.max_positions:
            continue
        h = attribute_history(code, 30, '1d', ['close', 'open', 'low', 'volume'])
        if len(h) < 21:
            continue

        price = h['close'].iloc[-1]
        open_p = h['open'].iloc[-1]
        vol_today = h['volume'].iloc[-1]
        if price <= 0 or open_p <= 0:
            continue

        rsi = _calc_rsi(h['close'], 14)
        if rsi >= 30:
            continue

        mid, upper, lower = _calc_bollinger(h['close'], 20, 2)
        if lower is None:
            continue

        recent_lows = h['low'].iloc[-5:]
        touched_lower = any(lo <= lower * 1.01 for lo in recent_lows)
        if not touched_lower:
            continue
        if price <= lower:
            continue
        if price <= open_p:
            continue

        vol_ma5 = h['volume'].iloc[-6:-1].mean()
        if vol_ma5 <= 0 or vol_today <= vol_ma5 * 1.2:
            continue

        cash_per = context.portfolio.total_value / g.max_positions
        order_value(code, min(cash_per, context.portfolio.available_cash * 0.95))
        g.hold_days[code] = 0
        current_count += 1
        log.info("超跌反弹买入 " + code + " RSI=" + str(round(rsi, 1))
                 + " 布林下轨:" + str(round(lower, 2)))
''',
    },
    {
        'id': 'low_backtrace_increase',
        'name': '无大幅回撤',
        'category': 'stock',
        'description': '趋势过滤策略：60日涨幅≥60%且无单日大跌、无连续两日大跌。止盈20%/止损10%。对应策略选股 S06。',
        'code': '''# 无大幅回撤（策略选股模板 S06）
# 买入：60日涨幅≥60% + 无单日跌>7% + 无两日累计跌>10%
# 卖出：止盈+20%，止损-10%，最长持有20日
# 兼容聚宽 + 本地回测引擎
import jqdata

def initialize(context):
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001,
                             open_commission=0.0003, close_commission=0.0003,
                             close_today_commission=0, min_commission=5), type='stock')
    # 动态股票池：从本地缓存/聚宽获取全部可用股票（统一为聚宽格式 XXXXXX.XSHG/XSHE）
    try:
        _raw = get_all_cached_stocks()
        g.stocks = [c + ('.XSHG' if c[0] == '6' else '.XSHE') for c in _raw]
    except Exception:
        g.stocks = list(get_all_securities().index)
    g.max_positions = 5
    g.take_profit = 0.20
    g.stop_loss = -0.10
    g.max_hold_days = 20
    g.hold_days = {}
    g.window = 60
    run_daily(market_open, time='every_bar')

def _check_low_backtrace(closes, opens, window=60):
    if len(closes) < window:
        return False
    rc = closes.iloc[-window:]
    ro = opens.iloc[-window:]
    ratio = (rc.iloc[-1] - rc.iloc[0]) / rc.iloc[0]
    if ratio < 0.6:
        return False
    prev_pct = 0.0
    prev_open = ro.iloc[0]
    for i in range(len(rc)):
        c = rc.iloc[i]
        o = ro.iloc[i]
        pct = 0
        if i > 0 and rc.iloc[i - 1] > 0:
            pct = (c - rc.iloc[i - 1]) / rc.iloc[i - 1] * 100
        if pct < -7:
            return False
        if o > 0 and (c - o) / o * 100 < -7:
            return False
        if prev_pct + pct < -10:
            return False
        if prev_open > 0 and (c - prev_open) / prev_open * 100 < -10:
            return False
        prev_pct = pct
        prev_open = o
    return True

def market_open(context):
    # ── 卖出检查 ──
    for code in list(context.portfolio.positions.keys()):
        g.hold_days[code] = g.hold_days.get(code, 0) + 1
        pos = context.portfolio.positions[code]
        if pos.avg_cost <= 0:
            continue
        profit_rate = (pos.price - pos.avg_cost) / pos.avg_cost
        if profit_rate >= g.take_profit:
            order_target(code, 0)
            log.info("止盈 " + code + " +" + str(round(profit_rate * 100, 1)) + "%")
            g.hold_days.pop(code, None)
            continue
        if profit_rate <= g.stop_loss:
            order_target(code, 0)
            log.info("止损 " + code + " " + str(round(profit_rate * 100, 1)) + "%")
            g.hold_days.pop(code, None)
            continue
        if g.hold_days.get(code, 0) >= g.max_hold_days:
            order_target(code, 0)
            log.info("超时卖出 " + code)
            g.hold_days.pop(code, None)

    # ── 买入检查 ──
    current_count = len(context.portfolio.positions)
    if current_count >= g.max_positions:
        return

    for code in g.stocks:
        if code in context.portfolio.positions or current_count >= g.max_positions:
            continue
        n = g.window + 1
        h = attribute_history(code, n, '1d', ['close', 'open'])
        if len(h) < g.window:
            continue

        if _check_low_backtrace(h['close'], h['open'], g.window):
            cash_per = context.portfolio.total_value / g.max_positions
            order_value(code, min(cash_per, context.portfolio.available_cash * 0.95))
            g.hold_days[code] = 0
            current_count += 1
            gain = (h['close'].iloc[-1] - h['close'].iloc[-g.window]) / h['close'].iloc[-g.window]
            log.info("无大幅回撤买入 " + code + " 60日涨幅:" + str(round(gain * 100, 1)) + "%")
''',
    },
    # ── 第二批策略选股模板（S02, S03, S04, S05, S10） ──
    {
        'id': 'keep_increasing',
        'name': '均线多头',
        'category': 'stock',
        'description': '趋势策略：MA30持续上升且30日涨幅超20%时买入，均线走平或止损时卖出。对应策略选股 S02。',
        'code': '''# 均线多头（策略选股模板 S02）
# 买入：MA30在30日内持续上升（4个采样点递增）且涨幅>20%
# 卖出：止盈+20%，止损-10%，最长持有30日，或MA30开始下降
# 兼容聚宽 + 本地回测引擎
import jqdata

def initialize(context):
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001,
                             open_commission=0.0003, close_commission=0.0003,
                             close_today_commission=0, min_commission=5), type='stock')
    # 动态股票池：从本地缓存/聚宽获取全部可用股票（统一为聚宽格式 XXXXXX.XSHG/XSHE）
    try:
        _raw = get_all_cached_stocks()
        g.stocks = [c + ('.XSHG' if c[0] == '6' else '.XSHE') for c in _raw]
    except Exception:
        g.stocks = list(get_all_securities().index)
    g.max_positions = 5
    g.take_profit = 0.20
    g.stop_loss = -0.10
    g.max_hold_days = 30
    g.hold_days = {}
    g.ma_window = 30
    run_daily(market_open, time='every_bar')

def _calc_ma(closes, period):
    if len(closes) < period:
        return 0
    return closes.iloc[-period:].mean()

def market_open(context):
    # ── 卖出检查 ──
    for code in list(context.portfolio.positions.keys()):
        g.hold_days[code] = g.hold_days.get(code, 0) + 1
        pos = context.portfolio.positions[code]
        if pos.avg_cost <= 0:
            continue
        profit_rate = (pos.price - pos.avg_cost) / pos.avg_cost
        if profit_rate >= g.take_profit:
            order_target(code, 0)
            log.info("止盈 " + code + " +" + str(round(profit_rate * 100, 1)) + "%")
            g.hold_days.pop(code, None)
            continue
        if profit_rate <= g.stop_loss:
            order_target(code, 0)
            log.info("止损 " + code + " " + str(round(profit_rate * 100, 1)) + "%")
            g.hold_days.pop(code, None)
            continue
        if g.hold_days.get(code, 0) >= g.max_hold_days:
            order_target(code, 0)
            log.info("超时卖出 " + code)
            g.hold_days.pop(code, None)
            continue
        # MA30开始下降时卖出
        h = attribute_history(code, 62, '1d', ['close'])
        if len(h) >= 62:
            ma_today = h['close'].iloc[-30:].mean()
            ma_yesterday = h['close'].iloc[-31:-1].mean()
            if ma_today < ma_yesterday:
                order_target(code, 0)
                log.info("均线走平卖出 " + code)
                g.hold_days.pop(code, None)

    # ── 买入检查 ──
    current_count = len(context.portfolio.positions)
    if current_count >= g.max_positions:
        return

    for code in g.stocks:
        if code in context.portfolio.positions or current_count >= g.max_positions:
            continue
        h = attribute_history(code, 60, '1d', ['close'])
        if len(h) < 60:
            continue
        # 取最近30日数据中4个采样点的MA30
        # 采样点：30日前、20日前、10日前、当日
        ma30_p0 = h['close'].iloc[:30].mean()   # 30日前的MA30
        ma30_p1 = h['close'].iloc[10:40].mean() # 20日前的MA30
        ma30_p2 = h['close'].iloc[20:50].mean() # 10日前的MA30
        ma30_p3 = h['close'].iloc[30:60].mean() # 当日的MA30
        if ma30_p0 <= 0:
            continue
        # 条件1：4个采样点递增
        if not (ma30_p0 < ma30_p1 < ma30_p2 < ma30_p3):
            continue
        # 条件2：当日MA30 / 30日前MA30 > 1.2
        if ma30_p3 / ma30_p0 <= 1.2:
            continue

        cash_per = context.portfolio.total_value / g.max_positions
        order_value(code, min(cash_per, context.portfolio.available_cash * 0.95))
        g.hold_days[code] = 0
        current_count += 1
        ma_gain = (ma30_p3 / ma30_p0 - 1) * 100
        log.info("均线多头买入 " + code + " MA30涨幅:" + str(round(ma_gain, 1)) + "%")
''',
    },
    {
        'id': 'parking_apron',
        'name': '停机坪',
        'category': 'stock',
        'description': '涨停后横盘蓄力策略：近15日内出现涨停+放量，随后3日高开收涨且振幅<3%。对应策略选股 S03。',
        'code': '''# 停机坪（策略选股模板 S03）
# 买入：近15日内有涨停（涨幅≥9.5%）且放量，之后3日高开收涨、振幅<3%、日涨跌幅<5%
# 卖出：止盈+15%，止损-7%，最长持有15日
# 兼容聚宽 + 本地回测引擎
import jqdata

def initialize(context):
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001,
                             open_commission=0.0003, close_commission=0.0003,
                             close_today_commission=0, min_commission=5), type='stock')
    # 动态股票池：从本地缓存/聚宽获取全部可用股票（统一为聚宽格式 XXXXXX.XSHG/XSHE）
    try:
        _raw = get_all_cached_stocks()
        g.stocks = [c + ('.XSHG' if c[0] == '6' else '.XSHE') for c in _raw]
    except Exception:
        g.stocks = list(get_all_securities().index)
    g.max_positions = 5
    g.take_profit = 0.15
    g.stop_loss = -0.07
    g.max_hold_days = 15
    g.hold_days = {}
    run_daily(market_open, time='every_bar')

def _check_parking_apron(h):
    """检测停机坪形态：涨停 + 3日横盘蓄力"""
    if len(h) < 5:
        return False
    closes = h['close']
    opens = h['open']
    # 在前面的数据中寻找涨停日
    for i in range(len(h) - 4):
        if i == 0:
            continue
        prev_close = closes.iloc[i - 1]
        if prev_close <= 0:
            continue
        pct = (closes.iloc[i] - prev_close) / prev_close * 100
        if pct < 9.5:
            continue
        # 涨停日找到，检查后续3天
        limitup_close = closes.iloc[i]
        ok = True
        for j in range(1, 4):
            idx = i + j
            if idx >= len(h):
                ok = False
                break
            c = closes.iloc[idx]
            o = opens.iloc[idx]
            if o <= 0 or limitup_close <= 0:
                ok = False
                break
            # 高开：开盘价 > 涨停日收盘价
            if o <= limitup_close:
                ok = False
                break
            # 收涨：收盘 > 涨停日收盘
            if c <= limitup_close:
                ok = False
                break
            # 振幅 < 3%
            if abs(c / o - 1) >= 0.03:
                ok = False
                break
            # 日涨跌幅 < 5%（相对前日）
            prev_c = closes.iloc[idx - 1]
            if prev_c > 0 and abs((c - prev_c) / prev_c) >= 0.05:
                ok = False
                break
        if ok:
            return True
    return False

def market_open(context):
    # ── 卖出检查 ──
    for code in list(context.portfolio.positions.keys()):
        g.hold_days[code] = g.hold_days.get(code, 0) + 1
        pos = context.portfolio.positions[code]
        if pos.avg_cost <= 0:
            continue
        profit_rate = (pos.price - pos.avg_cost) / pos.avg_cost
        if profit_rate >= g.take_profit:
            order_target(code, 0)
            log.info("止盈 " + code + " +" + str(round(profit_rate * 100, 1)) + "%")
            g.hold_days.pop(code, None)
            continue
        if profit_rate <= g.stop_loss:
            order_target(code, 0)
            log.info("止损 " + code + " " + str(round(profit_rate * 100, 1)) + "%")
            g.hold_days.pop(code, None)
            continue
        if g.hold_days.get(code, 0) >= g.max_hold_days:
            order_target(code, 0)
            log.info("超时卖出 " + code)
            g.hold_days.pop(code, None)

    # ── 买入检查 ──
    current_count = len(context.portfolio.positions)
    if current_count >= g.max_positions:
        return

    for code in g.stocks:
        if code in context.portfolio.positions or current_count >= g.max_positions:
            continue
        h = attribute_history(code, 16, '1d', ['close', 'open'])
        if len(h) < 5:
            continue
        if _check_parking_apron(h):
            cash_per = context.portfolio.total_value / g.max_positions
            order_value(code, min(cash_per, context.portfolio.available_cash * 0.95))
            g.hold_days[code] = 0
            current_count += 1
            log.info("停机坪买入 " + code + " 价格:" + str(round(h['close'].iloc[-1], 2)))
''',
    },
    {
        'id': 'backtrace_ma250',
        'name': '回踩年线',
        'category': 'stock',
        'description': '中长线策略：突破MA250后缩量回踩年线，回踩幅度≥20%且量比>2。对应策略选股 S04。',
        'code': '''# 回踩年线（策略选股模板 S04）
# 买入：60日内从MA250下方突破后回踩，后段始终在MA250上方
#       最高价日与回踩最低日间隔10-50日，量比>2，回踩幅度≥20%
# 卖出：止盈+20%，止损-10%，最长持有30日
# 需要至少250日历史数据
# 兼容聚宽 + 本地回测引擎
import jqdata

def initialize(context):
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001,
                             open_commission=0.0003, close_commission=0.0003,
                             close_today_commission=0, min_commission=5), type='stock')
    # 动态股票池：从本地缓存/聚宽获取全部可用股票（统一为聚宽格式 XXXXXX.XSHG/XSHE）
    try:
        _raw = get_all_cached_stocks()
        g.stocks = [c + ('.XSHG' if c[0] == '6' else '.XSHE') for c in _raw]
    except Exception:
        g.stocks = list(get_all_securities().index)
    g.max_positions = 5
    g.take_profit = 0.20
    g.stop_loss = -0.10
    g.max_hold_days = 30
    g.hold_days = {}
    g.check_window = 60
    run_daily(market_open, time='every_bar')

def _check_backtrace_ma250(h):
    """检测回踩年线形态"""
    closes = h['close']
    volumes = h['volume']
    n = len(closes)
    if n < 60:
        return False

    # 简化MA250：用全部可用数据计算（需要引擎提供足够前导数据）
    # 这里用最近60日窗口中各日的估算MA250
    # 找出60日窗口内最高价及其位置
    window = closes.iloc[-60:]
    vol_window = volumes.iloc[-60:]
    highest_idx = window.values.argmax()
    highest_price = window.iloc[highest_idx]
    highest_vol = vol_window.iloc[highest_idx]
    if highest_idx == 0 or highest_idx >= 59:
        return False

    # 前段：最高价之前
    front = window.iloc[:highest_idx + 1]
    # 后段：最高价之后（含最高价日）
    back = window.iloc[highest_idx:]
    back_vol = vol_window.iloc[highest_idx:]

    if len(front) < 2 or len(back) < 2:
        return False

    # 简化检查：前段首日价格 < 前段末日价格（向上突破趋势）
    if front.iloc[0] >= front.iloc[-1]:
        return False

    # 后段找最低价
    back_lowest_idx = back.values.argmin()
    back_lowest_price = back.iloc[back_lowest_idx]
    back_lowest_vol = back_vol.iloc[back_lowest_idx]

    # 回踩天数在10-50日间
    days_diff = back_lowest_idx
    if days_diff < 10 or days_diff > 50:
        return False

    # 量比 > 2（最高价日成交量 / 回踩最低价日成交量）
    if back_lowest_vol <= 0:
        return False
    vol_ratio = highest_vol / back_lowest_vol
    if vol_ratio <= 2:
        return False

    # 回踩幅度 ≥ 20%
    if highest_price <= 0:
        return False
    back_ratio = back_lowest_price / highest_price
    if back_ratio >= 0.8:
        return False

    return True

def market_open(context):
    # ── 卖出检查 ──
    for code in list(context.portfolio.positions.keys()):
        g.hold_days[code] = g.hold_days.get(code, 0) + 1
        pos = context.portfolio.positions[code]
        if pos.avg_cost <= 0:
            continue
        profit_rate = (pos.price - pos.avg_cost) / pos.avg_cost
        if profit_rate >= g.take_profit:
            order_target(code, 0)
            log.info("止盈 " + code + " +" + str(round(profit_rate * 100, 1)) + "%")
            g.hold_days.pop(code, None)
            continue
        if profit_rate <= g.stop_loss:
            order_target(code, 0)
            log.info("止损 " + code + " " + str(round(profit_rate * 100, 1)) + "%")
            g.hold_days.pop(code, None)
            continue
        if g.hold_days.get(code, 0) >= g.max_hold_days:
            order_target(code, 0)
            log.info("超时卖出 " + code)
            g.hold_days.pop(code, None)

    # ── 买入检查 ──
    current_count = len(context.portfolio.positions)
    if current_count >= g.max_positions:
        return

    for code in g.stocks:
        if code in context.portfolio.positions or current_count >= g.max_positions:
            continue
        h = attribute_history(code, 61, '1d', ['close', 'volume'])
        if len(h) < 60:
            continue
        if _check_backtrace_ma250(h):
            cash_per = context.portfolio.total_value / g.max_positions
            order_value(code, min(cash_per, context.portfolio.available_cash * 0.95))
            g.hold_days[code] = 0
            current_count += 1
            log.info("回踩年线买入 " + code + " 价格:" + str(round(h['close'].iloc[-1], 2)))
''',
    },
    {
        'id': 'breakthrough_platform',
        'name': '突破平台',
        'category': 'stock',
        'description': '横盘突破策略：60日内价格在MA60附近整理后放量上穿MA60买入。对应策略选股 S05。',
        'code': '''# 突破平台（策略选股模板 S05）
# 买入：60日内某日开盘<MA60≤收盘（上穿），且放量
#       上穿日之前所有交易日，收盘价偏离MA60在-5%~+20%（横盘整理）
# 卖出：止盈+15%，止损-7%，最长持有20日
# 兼容聚宽 + 本地回测引擎
import jqdata

def initialize(context):
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001,
                             open_commission=0.0003, close_commission=0.0003,
                             close_today_commission=0, min_commission=5), type='stock')
    # 动态股票池：从本地缓存/聚宽获取全部可用股票（统一为聚宽格式 XXXXXX.XSHG/XSHE）
    try:
        _raw = get_all_cached_stocks()
        g.stocks = [c + ('.XSHG' if c[0] == '6' else '.XSHE') for c in _raw]
    except Exception:
        g.stocks = list(get_all_securities().index)
    g.max_positions = 5
    g.take_profit = 0.15
    g.stop_loss = -0.07
    g.max_hold_days = 20
    g.hold_days = {}
    run_daily(market_open, time='every_bar')

def _check_breakthrough(h):
    """检测突破平台形态"""
    closes = h['close']
    opens = h['open']
    volumes = h['volume']
    n = len(closes)
    if n < 60:
        return False

    # 计算每日MA60（简化：用整个窗口的滚动均值）
    # 检查最近几日是否有上穿
    recent = 10  # 在最近10日内寻找突破
    for i in range(n - recent, n):
        if i < 59:
            continue
        ma60 = closes.iloc[i - 59:i + 1].mean()
        c = closes.iloc[i]
        o = opens.iloc[i]
        if ma60 <= 0:
            continue
        # 上穿条件：开盘价 < MA60 ≤ 收盘价
        if not (o < ma60 <= c):
            continue
        # 放量条件：当日成交量 > 5日均量 * 1.5
        if i >= 5:
            vol_ma5 = volumes.iloc[i - 5:i].mean()
            if vol_ma5 > 0 and volumes.iloc[i] < vol_ma5 * 1.5:
                continue
        # 检查上穿日之前的横盘：偏离MA60在-5%~+20%
        platform_ok = True
        for j in range(max(0, i - 59), i):
            if j < 59:
                continue
            ma60_j = closes.iloc[j - 59:j + 1].mean()
            if ma60_j <= 0:
                continue
            deviation = (closes.iloc[j] - ma60_j) / ma60_j
            if deviation < -0.05 or deviation > 0.20:
                platform_ok = False
                break
        if platform_ok:
            return True
    return False

def market_open(context):
    # ── 卖出检查 ──
    for code in list(context.portfolio.positions.keys()):
        g.hold_days[code] = g.hold_days.get(code, 0) + 1
        pos = context.portfolio.positions[code]
        if pos.avg_cost <= 0:
            continue
        profit_rate = (pos.price - pos.avg_cost) / pos.avg_cost
        if profit_rate >= g.take_profit:
            order_target(code, 0)
            log.info("止盈 " + code + " +" + str(round(profit_rate * 100, 1)) + "%")
            g.hold_days.pop(code, None)
            continue
        if profit_rate <= g.stop_loss:
            order_target(code, 0)
            log.info("止损 " + code + " " + str(round(profit_rate * 100, 1)) + "%")
            g.hold_days.pop(code, None)
            continue
        if g.hold_days.get(code, 0) >= g.max_hold_days:
            order_target(code, 0)
            log.info("超时卖出 " + code)
            g.hold_days.pop(code, None)

    # ── 买入检查 ──
    current_count = len(context.portfolio.positions)
    if current_count >= g.max_positions:
        return

    for code in g.stocks:
        if code in context.portfolio.positions or current_count >= g.max_positions:
            continue
        h = attribute_history(code, 70, '1d', ['close', 'open', 'volume'])
        if len(h) < 60:
            continue
        if _check_breakthrough(h):
            cash_per = context.portfolio.total_value / g.max_positions
            order_value(code, min(cash_per, context.portfolio.available_cash * 0.95))
            g.hold_days[code] = 0
            current_count += 1
            log.info("突破平台买入 " + code + " 价格:" + str(round(h['close'].iloc[-1], 2)))
''',
    },
    {
        'id': 'low_atr_growth',
        'name': '低ATR成长',
        'category': 'stock',
        'description': '低波动成长策略：上市满250日，近10日ATR≤10%且最高/最低价比>1.1。对应策略选股 S10。',
        'code': '''# 低ATR成长（策略选股模板 S10）
# 买入：上市满250日 + 近10日ATR≤10% + 近10日最高/最低收盘价比>1.1
# 卖出：止盈+15%，止损-7%，最长持有20日
# 兼容聚宽 + 本地回测引擎
import jqdata

def initialize(context):
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001,
                             open_commission=0.0003, close_commission=0.0003,
                             close_today_commission=0, min_commission=5), type='stock')
    # 动态股票池：从本地缓存/聚宽获取全部可用股票（统一为聚宽格式 XXXXXX.XSHG/XSHE）
    try:
        _raw = get_all_cached_stocks()
        g.stocks = [c + ('.XSHG' if c[0] == '6' else '.XSHE') for c in _raw]
    except Exception:
        g.stocks = list(get_all_securities().index)
    g.max_positions = 5
    g.take_profit = 0.15
    g.stop_loss = -0.07
    g.max_hold_days = 20
    g.hold_days = {}
    g.atr_window = 10
    g.atr_threshold = 10
    run_daily(market_open, time='every_bar')

def _check_low_atr(h, window=10, atr_max=10):
    """检测低ATR成长条件"""
    if len(h) < window:
        return False
    closes = h['close'].iloc[-window:]
    if closes.min() <= 0:
        return False
    # 计算ATR：日涨跌幅绝对值之和 / 天数
    total_change = 0.0
    for i in range(1, len(closes)):
        prev = closes.iloc[i - 1]
        if prev > 0:
            total_change += abs((closes.iloc[i] - prev) / prev * 100)
    atr = total_change / window
    if atr > atr_max:
        return False
    # 最高/最低收盘价比 > 1.1
    ratio = (closes.max() - closes.min()) / closes.min()
    if ratio <= 0.1:
        return False
    return True

def market_open(context):
    # ── 卖出检查 ──
    for code in list(context.portfolio.positions.keys()):
        g.hold_days[code] = g.hold_days.get(code, 0) + 1
        pos = context.portfolio.positions[code]
        if pos.avg_cost <= 0:
            continue
        profit_rate = (pos.price - pos.avg_cost) / pos.avg_cost
        if profit_rate >= g.take_profit:
            order_target(code, 0)
            log.info("止盈 " + code + " +" + str(round(profit_rate * 100, 1)) + "%")
            g.hold_days.pop(code, None)
            continue
        if profit_rate <= g.stop_loss:
            order_target(code, 0)
            log.info("止损 " + code + " " + str(round(profit_rate * 100, 1)) + "%")
            g.hold_days.pop(code, None)
            continue
        if g.hold_days.get(code, 0) >= g.max_hold_days:
            order_target(code, 0)
            log.info("超时卖出 " + code)
            g.hold_days.pop(code, None)

    # ── 买入检查 ──
    current_count = len(context.portfolio.positions)
    if current_count >= g.max_positions:
        return

    for code in g.stocks:
        if code in context.portfolio.positions or current_count >= g.max_positions:
            continue
        h = attribute_history(code, 11, '1d', ['close'])
        if len(h) < g.atr_window:
            continue
        if _check_low_atr(h, g.atr_window, g.atr_threshold):
            cash_per = context.portfolio.total_value / g.max_positions
            order_value(code, min(cash_per, context.portfolio.available_cash * 0.95))
            g.hold_days[code] = 0
            current_count += 1
            log.info("低ATR成长买入 " + code + " 价格:" + str(round(h['close'].iloc[-1], 2)))
''',
    },
    {
        'id': 'high_tight_flag',
        'name': '高而窄的旗形',
        'category': 'stock',
        'description': '极端强势形态：短期翻倍且含连续涨停，止盈20%/止损10%。对应策略选股 S08。',
        'code': '''# 高而窄的旗形（策略选股模板 S08）
# 买入：上市满60日 + 收盘价/10~24日前最低价≥1.9 + 区间内连续两日涨幅≥9.5%
# 卖出：止盈+20%，止损-10%，最长持有15日
# 兼容聚宽 + 本地回测引擎
import jqdata

def initialize(context):
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001,
                             open_commission=0.0003, close_commission=0.0003,
                             close_today_commission=0, min_commission=5), type='stock')
    # 动态股票池：从本地缓存/聚宽获取全部可用股票（统一为聚宽格式 XXXXXX.XSHG/XSHE）
    try:
        _raw = get_all_cached_stocks()
        g.stocks = [c + ('.XSHG' if c[0] == '6' else '.XSHE') for c in _raw]
    except Exception:
        g.stocks = list(get_all_securities().index)
    g.max_positions = 5
    g.take_profit = 0.20
    g.stop_loss = -0.10
    g.max_hold_days = 15
    g.hold_days = {}
    run_daily(market_open, time='every_bar')

def _check_high_tight_flag(h, threshold=60):
    """检测高而窄旗形：收盘价/10~24日前最低价>=1.9，且该区间有连续两日涨幅>=9.5%"""
    if len(h) < threshold:
        return False
    closes = h['close'].values
    current_close = closes[-1]
    if current_close <= 0:
        return False
    # 取 10~24 日前的数据片段（即倒数第25到倒数第11行）
    seg_start = max(0, len(closes) - 25)
    seg_end = max(0, len(closes) - 10)
    if seg_end <= seg_start:
        return False
    segment = closes[seg_start:seg_end]
    if len(segment) < 2:
        return False
    low = segment.min()
    if low <= 0:
        return False
    # 条件1：涨幅 >= 90%
    if current_close / low < 1.9:
        return False
    # 条件2：该段内连续两日涨幅 >= 9.5%
    prev_pct = 0.0
    for i in range(1, len(segment)):
        if segment[i - 1] <= 0:
            prev_pct = 0.0
            continue
        pct = (segment[i] - segment[i - 1]) / segment[i - 1] * 100
        if pct >= 9.5:
            if prev_pct >= 9.5:
                return True
            prev_pct = pct
        else:
            prev_pct = 0.0
    return False

def market_open(context):
    # ── 卖出检查 ──
    for code in list(context.portfolio.positions.keys()):
        g.hold_days[code] = g.hold_days.get(code, 0) + 1
        pos = context.portfolio.positions[code]
        if pos.avg_cost <= 0:
            continue
        profit_rate = (pos.price - pos.avg_cost) / pos.avg_cost
        if profit_rate >= g.take_profit:
            order_target(code, 0)
            log.info("止盈 " + code + " +" + str(round(profit_rate * 100, 1)) + "%")
            g.hold_days.pop(code, None)
            continue
        if profit_rate <= g.stop_loss:
            order_target(code, 0)
            log.info("止损 " + code + " " + str(round(profit_rate * 100, 1)) + "%")
            g.hold_days.pop(code, None)
            continue
        if g.hold_days.get(code, 0) >= g.max_hold_days:
            order_target(code, 0)
            log.info("超时卖出 " + code)
            g.hold_days.pop(code, None)

    # ── 买入检查 ──
    current_count = len(context.portfolio.positions)
    if current_count >= g.max_positions:
        return

    for code in g.stocks:
        if code in context.portfolio.positions or current_count >= g.max_positions:
            continue
        h = attribute_history(code, 60, '1d', ['close'])
        if len(h) < 60:
            continue
        if _check_high_tight_flag(h, 60):
            cash_per = context.portfolio.total_value / g.max_positions
            order_value(code, min(cash_per, context.portfolio.available_cash * 0.95))
            g.hold_days[code] = 0
            current_count += 1
            log.info("高而窄旗形买入 " + code + " 价格:" + str(round(h['close'].iloc[-1], 2)))
''',
    },
    {
        'id': 'breakout_confirm',
        'name': '突破确认',
        'category': 'stock',
        'description': '横盘后放量突破策略：40日振幅<25%、创新高、量比≥1.5、涨幅>2%、站上MA60。对应策略选股 S13。',
        'code': '''# 突破确认（策略选股模板 S13）
# 买入：40日振幅<25% + 收盘创40日新高 + 量比≥1.5 + 涨幅>2% + 收盘>MA60
# 卖出：止盈+20%，止损-8%，最长持有20日
# 兼容聚宽 + 本地回测引擎
import jqdata

def initialize(context):
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001,
                             open_commission=0.0003, close_commission=0.0003,
                             close_today_commission=0, min_commission=5), type='stock')
    # 动态股票池：从本地缓存/聚宽获取全部可用股票（统一为聚宽格式 XXXXXX.XSHG/XSHE）
    try:
        _raw = get_all_cached_stocks()
        g.stocks = [c + ('.XSHG' if c[0] == '6' else '.XSHE') for c in _raw]
    except Exception:
        g.stocks = list(get_all_securities().index)
    g.max_positions = 5
    g.take_profit = 0.20
    g.stop_loss = -0.08
    g.max_hold_days = 20
    g.hold_days = {}
    g.consolidation_window = 40
    g.amplitude_max = 0.25
    g.volume_ratio_min = 1.5
    g.min_pct_change = 0.02
    run_daily(market_open, time='every_bar')

def _check_breakout(h, window=40, amp_max=0.25, vol_ratio=1.5, pct_min=0.02):
    """检测横盘突破条件"""
    if len(h) < window + 1:
        return False
    closes = h['close'].values
    highs = h['high'].values
    lows = h['low'].values
    volumes = h['volume'].values

    last_close = closes[-1]
    last_vol = volumes[-1]
    if last_close <= 0:
        return False

    # 过去40日（不含今日）
    seg_close = closes[-(window + 1):-1]
    seg_high = highs[-(window + 1):-1]
    seg_low = lows[-(window + 1):-1]
    seg_vol = volumes[-(window + 1):-1]

    if len(seg_close) < window:
        return False

    # 条件1：振幅 < 25%
    period_high = seg_high.max()
    period_low = seg_low.min()
    if period_low <= 0:
        return False
    amplitude = (period_high - period_low) / period_low
    if amplitude >= amp_max:
        return False

    # 条件2：当日创新高
    if last_close <= seg_close.max():
        return False

    # 条件3：量比 >= 1.5（相对过去20日均量）
    vol_ma = volumes[-(21):-1].mean() if len(volumes) >= 21 else seg_vol.mean()
    if vol_ma <= 0:
        return False
    if last_vol / vol_ma < vol_ratio:
        return False

    # 条件4：涨幅 > 2%
    prev_close = closes[-2]
    if prev_close <= 0:
        return False
    pct_change = (last_close - prev_close) / prev_close
    if pct_change <= pct_min:
        return False

    # 条件5：站上MA60
    if len(closes) >= 60:
        ma60 = closes[-60:].mean()
        if last_close <= ma60:
            return False
    # 数据不足60日时跳过MA60检查

    return True

def market_open(context):
    # ── 卖出检查 ──
    for code in list(context.portfolio.positions.keys()):
        g.hold_days[code] = g.hold_days.get(code, 0) + 1
        pos = context.portfolio.positions[code]
        if pos.avg_cost <= 0:
            continue
        profit_rate = (pos.price - pos.avg_cost) / pos.avg_cost
        if profit_rate >= g.take_profit:
            order_target(code, 0)
            log.info("止盈 " + code + " +" + str(round(profit_rate * 100, 1)) + "%")
            g.hold_days.pop(code, None)
            continue
        if profit_rate <= g.stop_loss:
            order_target(code, 0)
            log.info("止损 " + code + " " + str(round(profit_rate * 100, 1)) + "%")
            g.hold_days.pop(code, None)
            continue
        if g.hold_days.get(code, 0) >= g.max_hold_days:
            order_target(code, 0)
            log.info("超时卖出 " + code)
            g.hold_days.pop(code, None)

    # ── 买入检查 ──
    current_count = len(context.portfolio.positions)
    if current_count >= g.max_positions:
        return

    for code in g.stocks:
        if code in context.portfolio.positions or current_count >= g.max_positions:
            continue
        h = attribute_history(code, 61, '1d', ['close', 'high', 'low', 'volume'])
        if len(h) < g.consolidation_window + 1:
            continue
        if _check_breakout(h, g.consolidation_window, g.amplitude_max,
                           g.volume_ratio_min, g.min_pct_change):
            cash_per = context.portfolio.total_value / g.max_positions
            order_value(code, min(cash_per, context.portfolio.available_cash * 0.95))
            g.hold_days[code] = 0
            current_count += 1
            log.info("突破确认买入 " + code + " 价格:" + str(round(h['close'].iloc[-1], 2)))
''',
    },
    {
        'id': 'quarterly_top5_ma_cross',
        'name': '季度基本面Top5+均线交叉',
        'category': 'multi_factor',
        'description': '每季度从全市场筛选基本面最优的5只股票作为股票池（ROE>8%、净利润正增长、PE 0-60、市值>30亿，按ROE降序取前5）；每日检查MA5与MA20，金叉买入、死叉卖出，等权配置。',
        'code': '''# 季度基本面 Top5 + 均线交叉策略
# 思路：
#   1. 每 60 个交易日（约 1 季度）从全市场筛选基本面最优的 5 只股票作为目标股票池
#      筛选条件：ROE>8、净利润同比正增长、PE 0-60、市值>30亿；按 ROE 降序取前 5
#   2. 季度调仓时，清掉不在新池中的持仓
#   3. 对股票池内的标的，每日检查 5/20 日均线穿越：
#       - 金叉（昨日 MA5 <= MA20 且今日 MA5 > MA20）且未持仓 → 等权买入
#       - 死叉（昨日 MA5 >= MA20 且今日 MA5 < MA20）且持仓中 → 全部卖出

def initialize(context):
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001,
                             open_commission=0.0003, close_commission=0.0003,
                             close_today_commission=0, min_commission=5), type='stock')
    g.pool_size = 5
    g.refresh_days = 60      # 约一个季度
    g.short_n = 5
    g.long_n = 20
    g.pool = []
    g.days = 0
    run_daily(handle, 'every_bar')

def select_fundamental_pool():
    """基本面筛选：ROE>8、净利润同比正增长、PE 合理、市值>30亿；按 ROE 降序取前 N"""
    q = query(
        valuation.code,
        valuation.market_cap,
        valuation.pe_ratio,
        indicator.roe,
        indicator.inc_net_profit_year_on_year
    ).filter(
        indicator.roe > 8,
        indicator.inc_net_profit_year_on_year > 0,
        valuation.pe_ratio > 0,
        valuation.pe_ratio < 60,
        valuation.market_cap > 30
    ).order_by(
        indicator.roe.desc()
    ).limit(g.pool_size)
    df = get_fundamentals(q)
    if df is None or len(df) == 0:
        return []
    return list(df['code'])

def handle(context):
    g.days += 1

    # 季度选股：第 1 个交易日 + 此后每 refresh_days 切一次
    if g.days == 1 or (g.days - 1) % g.refresh_days == 0:
        new_pool = select_fundamental_pool()
        if new_pool:
            log.info("季度调仓 基本面 Top5: " + str(new_pool))
            # 清仓不在新池中的持仓
            for code in list(context.portfolio.positions.keys()):
                if code not in new_pool:
                    order_target(code, 0)
                    log.info("调仓卖出 " + code)
            g.pool = new_pool
        else:
            log.info("季度选股无结果，沿用旧池")

    if not g.pool:
        return

    # 每日均线交叉
    target_value = context.portfolio.total_value / g.pool_size
    for code in g.pool:
        h = attribute_history(code, g.long_n + 1, '1d', ['close'])
        if h is None or len(h) < g.long_n + 1:
            continue
        closes = h['close']
        ma5_today = closes.iloc[-g.short_n:].mean()
        ma20_today = closes.iloc[-g.long_n:].mean()
        ma5_yest = closes.iloc[-g.short_n - 1:-1].mean()
        ma20_yest = closes.iloc[-g.long_n - 1:-1].mean()
        in_pos = code in context.portfolio.positions

        # 金叉买入
        if ma5_yest <= ma20_yest and ma5_today > ma20_today and not in_pos:
            order_target_value(code, target_value)
            log.info("金叉买入 " + code +
                     " MA5=" + str(round(ma5_today, 2)) +
                     " MA20=" + str(round(ma20_today, 2)))
        # 死叉卖出
        elif ma5_yest >= ma20_yest and ma5_today < ma20_today and in_pos:
            order_target(code, 0)
            log.info("死叉卖出 " + code +
                     " MA5=" + str(round(ma5_today, 2)) +
                     " MA20=" + str(round(ma20_today, 2)))
''',
    },
]


class GetStrategyTemplatesHandler(webBase.BaseHandler, ABC):
    """获取内置策略模板列表"""

    @gen.coroutine
    def get(self):
        try:
            self.write(json.dumps({
                'code': 0,
                'data': _normalized_strategy_templates(STRATEGY_TEMPLATES)
            }, ensure_ascii=False))
        except Exception as e:
            self.write(json.dumps({'code': -1, 'msg': str(e)}))


class SyncStrategyTemplatesHandler(webBase.BaseHandler, ABC):
    """同步内置模板到数据库（upsert：同名更新代码，不存在则新增）"""

    @gen.coroutine
    def post(self):
        try:
            result = sync_strategy_templates_to_db()
            updated = result.get('updated', 0) if isinstance(result, dict) else 0
            inserted = result.get('inserted', 0) if isinstance(result, dict) else 0
            self.write(json.dumps({
                'code': 0,
                'msg': f"同步完成：更新 {updated} 个，新增 {inserted} 个",
                'data': result
            }, ensure_ascii=False))
        except Exception as e:
            logging.error("SyncStrategyTemplates异常", exc_info=True)
            self.write(json.dumps({'code': -1, 'msg': str(e)}))

    @gen.coroutine
    def get(self):
        """GET 方式也支持，方便浏览器直接调用"""
        yield self.post()


class SaveStrategyCodeHandler(webBase.BaseHandler, ABC):
    """保存/更新策略代码"""

    @gen.coroutine
    def post(self):
        try:
            body = json.loads(self.request.body)
            name = body.get('name', '').strip()
            code = body.get('code', '').strip()
            description = body.get('description', '')
            strategy_id = body.get('id')
            category = body.get('category', 'stock')
            folder_id = body.get('folder_id', 0)
            initial_cash = body.get('initial_cash', 1000000)
            benchmark = body.get('benchmark', '000300')
            commission = body.get('commission_rate', 0.0003)
            tax = body.get('stamp_tax_rate', 0.001)
            slippage = body.get('slippage', 0.0005)
            # AI 元数据（由 AiChatDrawer 提交时携带；手工编辑则为 None / 'manual'）
            source = (body.get('source') or 'manual')
            if source not in ('manual', 'template', 'ai'):
                source = 'manual'
            ai_prompt = body.get('ai_prompt')
            ai_model = body.get('ai_model')
            ai_agent = body.get('ai_agent')
            try:
                ai_repair_count = int(body.get('ai_repair_count') or 0)
            except (TypeError, ValueError):
                ai_repair_count = 0

            if not name:
                self.write(json.dumps({'code': -1, 'msg': '策略名称不能为空'}))
                return
            if not code:
                self.write(json.dumps({'code': -1, 'msg': '策略代码不能为空'}))
                return

            # 验证代码安全性：AI 来源走 strict 校验（与 aiAssistantHandler 一致）
            if source == 'ai':
                from quantia.core.backtest.strategy_sandbox import validate_code_strict
                ok, err = validate_code_strict(code)
            else:
                from quantia.core.backtest.strategy_sandbox import validate_code
                ok, err = validate_code(code)
            if not ok:
                self.write(json.dumps({'code': -1, 'msg': f'代码验证失败: {err}'}, ensure_ascii=False))
                return

            _ensure_strategy_table()

            if strategy_id:
                user_modified = _resolve_user_modified_flag(strategy_id, code)
                # 更新
                mdb.executeSql(
                    'UPDATE cn_stock_strategy_code SET name=%s, code=%s, description=%s, '
                    'category=%s, initial_cash=%s, benchmark=%s, commission_rate=%s, '
                    'stamp_tax_rate=%s, slippage=%s, status=%s, '
                    'user_modified=%s, source=%s, ai_prompt=%s, ai_model=%s, '
                    'ai_agent=%s, ai_repair_count=%s '
                    'WHERE id=%s',
                    (name, code, description, category, initial_cash, benchmark,
                     commission, tax, slippage, 'active', user_modified,
                     source, ai_prompt, ai_model, ai_agent, ai_repair_count, strategy_id))
                result_id = strategy_id
            else:
                # 新增 —— 同名且未归档的策略视为重复，直接返回已有记录
                existing = mdb.executeSqlFetch(
                    "SELECT id FROM cn_stock_strategy_code WHERE name=%s AND status!='archived' LIMIT 1",
                    (name,))
                if existing and len(existing) > 0:
                    result_id = existing[0][0] if isinstance(existing[0], (list, tuple)) else existing[0].get('id', existing[0])
                    self.write(json.dumps({'code': 0, 'data': {'id': result_id, 'duplicate': True}}, ensure_ascii=False))
                    return
                result_id = _insert_and_get_id(
                    'INSERT INTO cn_stock_strategy_code '
                    '(name, code, description, category, folder_id, initial_cash, '
                    'benchmark, commission_rate, stamp_tax_rate, slippage, status, '
                    'source, ai_prompt, ai_model, ai_agent, ai_repair_count) '
                    'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                    (name, code, description, category, folder_id, initial_cash,
                     benchmark, commission, tax, slippage, 'active',
                     source, ai_prompt, ai_model, ai_agent, ai_repair_count))

            self.write(json.dumps({'code': 0, 'data': {'id': result_id}}, ensure_ascii=False))
        except Exception as e:
            logging.error("SaveStrategyCode异常", exc_info=True)
            self.write(json.dumps({'code': -1, 'msg': str(e)}))


class GetStrategyCodeListHandler(webBase.BaseHandler, ABC):
    """获取策略列表（含文件夹）"""

    @gen.coroutine
    def get(self):
        try:
            _ensure_strategy_table()
            folder_id = self.get_argument('folder_id', None)

            # 获取文件夹列表
            folders = []
            folder_rows = mdb.executeSqlFetch(
                'SELECT id, name, created_at FROM cn_stock_strategy_folder ORDER BY name')
            if folder_rows:
                for r in folder_rows:
                    folders.append({
                        'id': r[0], 'name': r[1], 'type': 'folder',
                        'created_at': r[2].strftime('%Y-%m-%d %H:%M') if r[2] else '',
                    })

            # 获取策略列表
            where = 'WHERE status != %s'
            params = ['archived']
            if folder_id is not None:
                where += ' AND folder_id = %s'
                params.append(int(folder_id))

            rows = mdb.executeSqlFetch(
                f'SELECT id, name, description, category, folder_id, initial_cash, benchmark, '
                f'compile_count, backtest_count, status, created_at, updated_at '
                f'FROM cn_stock_strategy_code {where} ORDER BY updated_at DESC', tuple(params))
            data = []
            if rows:
                for r in rows:
                    data.append({
                        'id': r[0], 'name': r[1], 'description': r[2] or '',
                        'category': r[3] or 'stock',
                        'folder_id': r[4] or 0,
                        'initial_cash': float(r[5]) if r[5] else 1000000,
                        'benchmark': r[6] or '000300',
                        'compile_count': r[7] or 0,
                        'backtest_count': r[8] or 0,
                        'status': r[9],
                        'created_at': r[10].strftime('%Y-%m-%d %H:%M:%S') if r[10] else '',
                        'updated_at': r[11].strftime('%Y-%m-%d %H:%M:%S') if r[11] else '',
                        'type': 'strategy',
                    })
            self.write(json.dumps({
                'code': 0, 'data': {'strategies': data, 'folders': folders}
            }, ensure_ascii=False))
        except Exception as e:
            self.write(json.dumps({'code': -1, 'msg': str(e)}))


class GetStrategyCodeDetailHandler(webBase.BaseHandler, ABC):
    """获取策略详情（含代码）"""

    @gen.coroutine
    def get(self):
        try:
            strategy_id = self.get_argument('id', None)
            if not strategy_id:
                self.write(json.dumps({'code': -1, 'msg': '缺少参数 id'}))
                return
            _ensure_strategy_table()
            rows = mdb.executeSqlFetch(
                'SELECT id, name, code, description, initial_cash, benchmark, '
                'commission_rate, stamp_tax_rate, slippage, status '
                'FROM cn_stock_strategy_code WHERE id = %s', (strategy_id,))
            if not rows:
                self.write(json.dumps({'code': -1, 'msg': '策略不存在'}))
                return
            r = rows[0]
            self.write(json.dumps({'code': 0, 'data': {
                'id': r[0], 'name': r[1], 'code': r[2],
                'description': r[3],
                'initial_cash': float(r[4]) if r[4] else 1000000,
                'benchmark': r[5] or '000300',
                'commission_rate': float(r[6]) if r[6] else 0.0003,
                'stamp_tax_rate': float(r[7]) if r[7] else 0.001,
                'slippage': float(r[8]) if r[8] else 0.0005,
                'status': r[9],
            }}, ensure_ascii=False))
        except Exception as e:
            self.write(json.dumps({'code': -1, 'msg': str(e)}))


class DeleteStrategyCodeHandler(webBase.BaseHandler, ABC):
    """删除策略（标记为 archived）"""

    @gen.coroutine
    def post(self):
        try:
            body = json.loads(self.request.body)
            strategy_id = body.get('id')
            if not strategy_id:
                self.write(json.dumps({'code': -1, 'msg': '缺少参数 id'}))
                return
            mdb.executeSql(
                'UPDATE cn_stock_strategy_code SET status=%s WHERE id=%s',
                ('archived', strategy_id))
            self.write(json.dumps({'code': 0}))
        except Exception as e:
            self.write(json.dumps({'code': -1, 'msg': str(e)}))


class RunPortfolioBacktestHandler(webBase.BaseHandler, ABC):
    """运行组合回测（结果持久化到 DB）— 使用线程池避免阻塞 IOLoop"""

    # 共享线程池：限制并发回测数量，避免资源耗尽
    _executor = None

    @classmethod
    def _get_executor(cls):
        if cls._executor is None:
            from concurrent.futures import ThreadPoolExecutor
            cls._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='backtest')
        return cls._executor

    @gen.coroutine
    def post(self):
        try:
            body = json.loads(self.request.body)
            strategy_code = body.get('code', '')
            strategy_id = body.get('strategy_id')
            strategy_name = body.get('strategy_name', '')
            start_date = body.get('start_date', '')
            end_date = body.get('end_date', '')
            initial_cash = body.get('initial_cash', 1000000)
            benchmark = body.get('benchmark', '000300')
            commission = body.get('commission_rate', 0.0003)
            tax = body.get('stamp_tax_rate', 0.001)
            slippage = body.get('slippage', 0.002)

            # 如果前端未传名称，尝试从 DB 查
            if not strategy_name and strategy_id:
                try:
                    _name_rows = mdb.executeSqlFetch(
                        'SELECT name FROM cn_stock_strategy_code WHERE id=%s', (strategy_id,))
                    if _name_rows and _name_rows[0][0]:
                        strategy_name = _name_rows[0][0]
                except Exception:
                    pass

            if not strategy_code or not start_date or not end_date:
                self.write(json.dumps({'code': -1, 'msg': '缺少必填参数'}, ensure_ascii=False))
                return

            from quantia.core.backtest.portfolio_engine import PortfolioBacktestEngine
            from tornado.ioloop import IOLoop

            # 创建引擎并注册到任务表（供日志流读取）
            task_id = str(uuid.uuid4())[:8]
            engine = PortfolioBacktestEngine()
            _running_tasks[task_id] = {'engine': engine, 'status': 'running', 'result': None}

            def _run():
                try:
                    return engine.run(
                        strategy_code, start_date, end_date,
                        initial_cash=initial_cash, benchmark=benchmark,
                        commission=commission, tax=tax, slippage=slippage)
                finally:
                    try:
                        import quantia.lib.database as _mdb
                        _mdb.close_thread_connection()
                    except Exception:
                        pass

            # 在线程池中运行回测，不阻塞 Tornado IOLoop
            result = yield IOLoop.current().run_in_executor(
                self._get_executor(), _run)

            _running_tasks[task_id]['status'] = 'done'
            _running_tasks[task_id]['result'] = result

            # 30秒后自动清理任务引用
            IOLoop.current().call_later(30, lambda: _running_tasks.pop(task_id, None))

            # 持久化到 DB
            bt_id = None
            if result.get('status') == 'completed':
                try:
                    _ensure_backtest_table()
                    m = result.get('metrics', {})
                    now = datetime.datetime.now()
                    # 将策略代码快照存入 result_json，避免策略修改后历史回测丢失原始代码
                    result['strategy_code_snapshot'] = strategy_code
                    bt_id = _insert_and_get_id(
                        'INSERT INTO cn_stock_backtest_portfolio '
                        '(strategy_id, strategy_name, start_date, end_date, initial_cash, status, '
                        'started_at, completed_at, total_return, annual_return, '
                        'max_drawdown, sharpe_ratio, alpha, beta, win_rate, trade_count, '
                        'result_json) '
                        'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                        (strategy_id, strategy_name or None, start_date, end_date, initial_cash, 'completed',
                         now, now, m.get('total_return'), m.get('annual_return'),
                         m.get('max_drawdown'), m.get('sharpe_ratio'),
                         m.get('alpha'), m.get('beta'),
                         m.get('daily_win_rate'), m.get('trade_count'),
                         json.dumps(result, ensure_ascii=False, default=str)))
                    # Phase 3: 回测主表入库后，将策略交易信号（reason/decision/
                    # indicators/selection）落入 cn_stock_trade_signal/decision/
                    # indicator_snapshot/selection_snapshot，供回测详情页与模拟交易详
                    # 情页复用同一套决策依据展示。失败只警告，不回滻主表。
                    try:
                        from quantia.core.backtest import trade_signal_store as _tss
                        run_id_bt = f"backtest-{bt_id}-{task_id}"
                        _tss.persist_backtest_signals(
                            backtest_id=int(bt_id), run_id=run_id_bt,
                            trade_records=getattr(engine, '_trade_records', []) or [],
                            signal_inputs=getattr(engine, '_signal_inputs', []) or [],
                        )
                    except Exception as _sig_err:
                        logging.warning(f"回测交易信号持久化异常(不影响主结果): {_sig_err}")
                    # 更新策略的 backtest_count 和 compile_count
                    if strategy_id:
                        try:
                            mdb.executeSql(
                                'UPDATE cn_stock_strategy_code SET backtest_count=backtest_count+1, '
                                'compile_count=compile_count+1 WHERE id=%s', (strategy_id,))
                        except Exception as e:
                            logging.debug(f"backtest_count 更新异常（不影响回测结果）: strategy_id={strategy_id} - {e}")
                except Exception as e:
                    logging.warning(f"回测结果持久化异常: {e}")

            result['backtest_id'] = bt_id
            result['task_id'] = task_id
            # M0: 引擎返回非 completed 状态也要入库（运行期逻辑错误等）
            if result.get('status') and result.get('status') != 'completed':
                try:
                    from quantia.core.backtest.task_recorder import record_failed
                    record_failed(
                        strategy_id=strategy_id, strategy_name=strategy_name,
                        start_date=start_date, end_date=end_date,
                        initial_cash=initial_cash, benchmark=benchmark,
                        error_text=str(result.get('message') or result.get('error') or 'unknown'),
                        traceback_text=str(result.get('traceback') or ''),
                        extra_result=result,
                    )
                except Exception as rec_err:
                    logging.warning(f"失败任务入库异常: {rec_err}")
            self.write(json.dumps({'code': 0, 'data': result}, ensure_ascii=False, default=str))
        except Exception as e:
            logging.error("RunPortfolioBacktest异常", exc_info=True)
            # M0: handler 最外层异常也入库
            try:
                from quantia.core.backtest.task_recorder import record_failed
                record_failed(
                    strategy_id=locals().get('strategy_id'), strategy_name=locals().get('strategy_name'),
                    start_date=locals().get('start_date', ''), end_date=locals().get('end_date', ''),
                    initial_cash=locals().get('initial_cash', 0),
                    benchmark=locals().get('benchmark', '000300'),
                    error_text=str(e), traceback_text=traceback.format_exc(),
                )
            except Exception:
                pass
            self.write(json.dumps({'code': -1, 'msg': str(e)}))


class StartPortfolioBacktestHandler(webBase.BaseHandler, ABC):
    """异步启动回测并立即返回 task_id（配合日志流使用）"""

    _executor = None

    @classmethod
    def _get_executor(cls):
        if cls._executor is None:
            from concurrent.futures import ThreadPoolExecutor
            cls._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='backtest-async')
        return cls._executor

    @gen.coroutine
    def post(self):
        try:
            body = json.loads(self.request.body)
            strategy_code = body.get('code', '')
            strategy_id = body.get('strategy_id')
            strategy_name = body.get('strategy_name', '')
            start_date = body.get('start_date', '')
            end_date = body.get('end_date', '')
            initial_cash = body.get('initial_cash', 1000000)
            benchmark = body.get('benchmark', '000300')
            commission = body.get('commission_rate', 0.0003)
            tax = body.get('stamp_tax_rate', 0.001)
            slippage = body.get('slippage', 0.002)

            # 如果前端未传名称，尝试从 DB 查
            if not strategy_name and strategy_id:
                try:
                    _name_rows = mdb.executeSqlFetch(
                        'SELECT name FROM cn_stock_strategy_code WHERE id=%s', (strategy_id,))
                    if _name_rows and _name_rows[0][0]:
                        strategy_name = _name_rows[0][0]
                except Exception:
                    pass

            if not strategy_code or not start_date or not end_date:
                self.write(json.dumps({'code': -1, 'msg': '缺少必填参数'}, ensure_ascii=False))
                return

            from quantia.core.backtest.portfolio_engine import PortfolioBacktestEngine

            task_id = str(uuid.uuid4())[:8]
            engine = PortfolioBacktestEngine()
            _running_tasks[task_id] = {
                'engine': engine, 'status': 'running', 'result': None,
                'strategy_id': strategy_id,
            }

            def _run_and_finish():
                try:
                    result = engine.run(
                        strategy_code, start_date, end_date,
                        initial_cash=initial_cash, benchmark=benchmark,
                        commission=commission, tax=tax, slippage=slippage)
                    task = _running_tasks.get(task_id)
                    if task:
                        task['status'] = 'done'
                        task['result'] = result
                        # 持久化（在回调线程中执行）
                        if result.get('status') == 'completed':
                            try:
                                _ensure_backtest_table()
                                m = result.get('metrics', {})
                                now = datetime.datetime.now()
                                # 将策略代码快照存入 result_json
                                result['strategy_code_snapshot'] = strategy_code
                                bt_id = _insert_and_get_id(
                                    'INSERT INTO cn_stock_backtest_portfolio '
                                    '(strategy_id, strategy_name, start_date, end_date, initial_cash, status, '
                                    'started_at, completed_at, total_return, annual_return, '
                                    'max_drawdown, sharpe_ratio, alpha, beta, win_rate, trade_count, '
                                    'result_json) '
                                    'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                                    (strategy_id, strategy_name or None, start_date, end_date, initial_cash, 'completed',
                                     now, now, m.get('total_return'), m.get('annual_return'),
                                     m.get('max_drawdown'), m.get('sharpe_ratio'),
                                     m.get('alpha'), m.get('beta'),
                                     m.get('daily_win_rate'), m.get('trade_count'),
                                     json.dumps(result, ensure_ascii=False, default=str)))
                                result['backtest_id'] = bt_id
                                # Phase 3: 交易信号详细落库（失败仅警告）。
                                try:
                                    from quantia.core.backtest import trade_signal_store as _tss
                                    run_id_bt = f"backtest-{bt_id}-{task_id}"
                                    _tss.persist_backtest_signals(
                                        backtest_id=int(bt_id), run_id=run_id_bt,
                                        trade_records=getattr(engine, '_trade_records', []) or [],
                                        signal_inputs=getattr(engine, '_signal_inputs', []) or [],
                                    )
                                except Exception as _sig_err:
                                    logging.warning(f"回测交易信号持久化异常(不影响主结果): {_sig_err}")
                                # 更新策略的 backtest_count 和 compile_count（与同步入口保持一致）
                                # 此前仅 RunPortfolioBacktestHandler 更新，导致前端编辑页（用 Start*）跑多次仍显示 0。
                                if strategy_id:
                                    try:
                                        mdb.executeSql(
                                            'UPDATE cn_stock_strategy_code SET backtest_count=backtest_count+1, '
                                            'compile_count=compile_count+1 WHERE id=%s', (strategy_id,))
                                    except Exception as e:
                                        logging.debug(f"backtest_count 更新异常（不影响回测结果）: strategy_id={strategy_id} - {e}")
                            except Exception as e:
                                logging.warning(f"回测持久化异常: {e}")
                        # M0+: 即使 status=completed，只要策略代码在交易日产生过运行时错误
                        # （_record_error 收集到 _strategy_errors[]），也额外写一条 failed
                        # 记录，供 AI 修复闭环 fetch_last_failure 取用。
                        try:
                            errs = result.get('errors') or []
                            if errs:
                                # 取首条错误作为代表（含 traceback 字段）
                                first = errs[0] if isinstance(errs[0], dict) else {'error': str(errs[0])}
                                err_msg = (first.get('error') or first.get('message') or '策略运行错误')[:500]
                                tb = first.get('traceback') or ''
                                from quantia.core.backtest.task_recorder import record_failed as _rf
                                _rf(
                                    strategy_id=strategy_id, strategy_name=strategy_name,
                                    start_date=start_date, end_date=end_date,
                                    initial_cash=initial_cash, benchmark=benchmark,
                                    error_text=f'策略运行期共 {len(errs)} 处错误，首条: {err_msg}',
                                    traceback_text=tb,
                                    extra_result={'all_errors': errs[:50]},
                                )
                        except Exception as _e:
                            logging.debug(f"runtime errors record_failed 失败: {_e}")
                except Exception as e:
                    err_text = str(e)
                    tb_text = traceback.format_exc()
                    task = _running_tasks.get(task_id)
                    if task:
                        task['status'] = 'done'
                        task['result'] = {'status': 'error', 'message': err_text, 'traceback': tb_text}
                    logging.error(f"异步回测异常: {e}", exc_info=True)
                    # M0: 失败任务必须入库（为 AI 修复闭环提供 error_message）
                    try:
                        from quantia.core.backtest.task_recorder import record_failed
                        record_failed(
                            strategy_id=strategy_id, strategy_name=strategy_name,
                            start_date=start_date, end_date=end_date,
                            initial_cash=initial_cash, benchmark=benchmark,
                            error_text=err_text, traceback_text=tb_text,
                        )
                    except Exception as rec_err:
                        logging.warning(f"失败任务入库异常: {rec_err}")
                finally:
                    try:
                        import quantia.lib.database as _mdb
                        _mdb.close_thread_connection()
                    except Exception:
                        pass

            # 提交到线程池 — 不 yield 等待
            self._get_executor().submit(_run_and_finish)

            # 立即返回 task_id
            self.write(json.dumps({'code': 0, 'data': {'task_id': task_id}}, ensure_ascii=False))
        except Exception as e:
            logging.error("StartPortfolioBacktest异常", exc_info=True)
            self.write(json.dumps({'code': -1, 'msg': str(e)}))


class BacktestLogStreamHandler(webBase.BaseHandler, ABC):
    """SSE 日志流 — 实时推送回测过程日志"""

    @gen.coroutine
    def get(self):
        task_id = self.get_argument('task_id', '')
        if not task_id or task_id not in _running_tasks:
            self.set_status(404)
            self.write('task not found')
            return

        self.set_header('Content-Type', 'text/event-stream; charset=utf-8')
        self.set_header('Cache-Control', 'no-cache')
        self.set_header('Connection', 'keep-alive')
        self.set_header('X-Accel-Buffering', 'no')
        self.set_header('Access-Control-Allow-Origin', '*')

        sent_count = 0
        sent_error_count = 0

        while True:
            task = _running_tasks.get(task_id)
            if task is None:
                self.write('event: done\ndata: {"status":"not_found"}\n\n')
                self.flush()
                break

            engine = task['engine']
            # 发送新的日志行
            logs = getattr(engine, '_log_messages', [])
            errors = getattr(engine, '_strategy_errors', [])

            if len(logs) > sent_count:
                new_logs = logs[sent_count:]
                sent_count = len(logs)
                for line in new_logs:
                    data = json.dumps({'type': 'log', 'msg': line}, ensure_ascii=False)
                    self.write(f'data: {data}\n\n')
                try:
                    self.flush()
                except Exception:
                    break

            if len(errors) > sent_error_count:
                new_errors = errors[sent_error_count:]
                sent_error_count = len(errors)
                for err in new_errors:
                    data = json.dumps({'type': 'error', 'context': err.get('context', ''),
                                       'error': err.get('error', ''), 'error_type': err.get('type', '')},
                                      ensure_ascii=False)
                    self.write(f'data: {data}\n\n')
                try:
                    self.flush()
                except Exception:
                    break

            if task['status'] == 'done':
                result = task.get('result', {})
                data = json.dumps({
                    'type': 'complete',
                    'status': result.get('status', 'error'),
                    'message': result.get('message', ''),
                }, ensure_ascii=False)
                self.write(f'event: done\ndata: {data}\n\n')
                try:
                    self.flush()
                except Exception:
                    pass
                break

            # 等待 300ms 再检查
            yield gen.sleep(0.3)

        self.finish()


class BacktestTaskResultHandler(webBase.BaseHandler, ABC):
    """获取已完成回测任务的完整结果"""

    def get(self):
        task_id = self.get_argument('task_id', '')
        task = _running_tasks.get(task_id)
        if not task:
            self.write(json.dumps({'code': -1, 'msg': '任务不存在或已过期'}))
            return
        if task['status'] != 'done':
            self.write(json.dumps({'code': 0, 'data': {'status': 'running'}}))
            return
        result = task.get('result', {})
        self.write(json.dumps({'code': 0, 'data': result}, ensure_ascii=False, default=str))


class GetPortfolioBacktestListHandler(webBase.BaseHandler, ABC):
    """获取历史回测列表（支持按策略ID筛选）"""

    @gen.coroutine
    def get(self):
        try:
            _ensure_backtest_table()
            strategy_id = self.get_argument('strategy_id', None)

            where = ''
            params = []
            if strategy_id:
                where = 'WHERE bp.strategy_id = %s'
                params.append(int(strategy_id))

            rows = mdb.executeSqlFetch(
                f'SELECT bp.id, bp.strategy_id, COALESCE(bp.strategy_name, sc.name) as strategy_name, '
                f'bp.start_date, bp.end_date, bp.initial_cash, bp.status, '
                f'bp.total_return, bp.annual_return, bp.max_drawdown, '
                f'bp.sharpe_ratio, bp.alpha, bp.beta, bp.win_rate, '
                f'bp.trade_count, bp.completed_at, bp.result_json '
                f'FROM cn_stock_backtest_portfolio bp '
                f'LEFT JOIN cn_stock_strategy_code sc ON bp.strategy_id = sc.id '
                f'{where} ORDER BY bp.id DESC LIMIT 100', tuple(params) if params else None)
            data = []
            if rows:
                for r in rows:
                    # 从 result_json 提取扩展指标
                    extra_metrics = {}
                    elapsed = ''
                    if r[16]:
                        try:
                            rj = json.loads(r[16]) if isinstance(r[16], str) else r[16]
                            m = rj.get('metrics', {})
                            extra_metrics = {
                                'benchmark_return': float(m.get('benchmark_return', 0)),
                                'excess_return': float(m.get('excess_return', 0)),
                                'excess_max_drawdown': float(m.get('excess_max_drawdown', 0)),
                                'excess_sharpe_ratio': float(m.get('excess_sharpe_ratio', 0)),
                                'benchmark_annual_return': float(m.get('benchmark_annual_return', 0)),
                            }
                            elapsed = rj.get('elapsed', '')
                        except Exception as e:
                            logging.debug(f"result_json 解析异常（回测列表）: id={r[0]} - {e}")
                    item = {
                        'id': r[0],
                        'strategy_id': r[1],
                        'strategy_name': r[2] or '临时策略',
                        'start_date': str(r[3]) if r[3] else '',
                        'end_date': str(r[4]) if r[4] else '',
                        'initial_cash': float(r[5]) if r[5] else 0,
                        'status': r[6] or 'unknown',
                        'total_return': float(r[7]) if r[7] else 0,
                        'annual_return': float(r[8]) if r[8] else 0,
                        'max_drawdown': float(r[9]) if r[9] else 0,
                        'sharpe_ratio': float(r[10]) if r[10] else 0,
                        'alpha': float(r[11]) if r[11] else 0,
                        'beta': float(r[12]) if r[12] else 0,
                        'win_rate': float(r[13]) if r[13] else 0,
                        'trade_count': r[14] or 0,
                        'completed_at': r[15].strftime('%Y-%m-%d %H:%M:%S') if r[15] else '',
                        'elapsed': elapsed,
                    }
                    item.update(extra_metrics)
                    data.append(item)
            self.write(json.dumps({'code': 0, 'data': data}, ensure_ascii=False))
        except Exception as e:
            self.write(json.dumps({'code': -1, 'msg': str(e)}))


class GetPortfolioBacktestDetailHandler(webBase.BaseHandler, ABC):
    """获取回测详情（含完整的净值/交易/持仓数据）"""

    @gen.coroutine
    def get(self):
        try:
            bt_id = self.get_argument('id', None)
            if not bt_id:
                self.write(json.dumps({'code': -1, 'msg': '缺少 id'}))
                return

            _ensure_backtest_table()
            rows = mdb.executeSqlFetch(
                'SELECT bp.id, bp.strategy_id, COALESCE(bp.strategy_name, sc.name), bp.start_date, bp.end_date, '
                'bp.initial_cash, bp.status, bp.total_return, bp.annual_return, '
                'bp.max_drawdown, bp.sharpe_ratio, bp.alpha, bp.beta, bp.win_rate, '
                'bp.trade_count, bp.completed_at, bp.result_json, bp.benchmark, '
                'bp.error_message '
                'FROM cn_stock_backtest_portfolio bp '
                'LEFT JOIN cn_stock_strategy_code sc ON bp.strategy_id = sc.id '
                'WHERE bp.id = %s', (bt_id,))

            if not rows:
                self.write(json.dumps({'code': -1, 'msg': '回测记录不存在'}))
                return

            r = rows[0]
            info = {
                'id': r[0], 'strategy_id': r[1],
                'strategy_name': r[2] or '临时策略',
                'start_date': str(r[3]) if r[3] else '',
                'end_date': str(r[4]) if r[4] else '',
                'initial_cash': float(r[5]) if r[5] else 0,
                'status': r[6],
                'metrics': {
                    'total_return': float(r[7]) if r[7] else 0,
                    'annual_return': float(r[8]) if r[8] else 0,
                    'max_drawdown': float(r[9]) if r[9] else 0,
                    'sharpe_ratio': float(r[10]) if r[10] else 0,
                    'alpha': float(r[11]) if r[11] else 0,
                    'beta': float(r[12]) if r[12] else 0,
                    'daily_win_rate': float(r[13]) if r[13] else 0,
                    'trade_count': r[14] or 0,
                },
                'completed_at': r[15].strftime('%Y-%m-%d %H:%M:%S') if r[15] else '',
                'error_message': (r[18] or '')[:2000],
            }

            # 尝试从 result_json 恢复完整数据（净值/交易/持仓）
            result_json = r[16]
            full_data = {}
            if result_json:
                try:
                    full_data = json.loads(result_json)
                except Exception as e:
                    logging.warning(f"result_json 解析失败（回测详情）: backtest_id={r[0]} - {e}")

            # 如果 result_json 中有完整 metrics，用它覆盖（字段更全）
            if full_data.get('metrics'):
                info['metrics'] = full_data['metrics']

            params = full_data.get('params', {}) if isinstance(full_data.get('params', {}), dict) else {}
            info['benchmark'] = params.get('benchmark') or r[17] or '000300'

            info['nav'] = full_data.get('nav', [])
            info['trades'] = full_data.get('trades', [])
            info['positions'] = full_data.get('positions', [])
            info['logs'] = full_data.get('logs', [])
            info['strategy_code'] = full_data.get('strategy_code_snapshot', '')

            self.write(json.dumps({'code': 0, 'data': info}, ensure_ascii=False, default=str))
        except Exception as e:
            logging.error("GetPortfolioBacktestDetail异常", exc_info=True)
            self.write(json.dumps({'code': -1, 'msg': str(e)}))


class GetBacktestCompareHandler(webBase.BaseHandler, ABC):
    """回测对比：接收多个回测ID，返回对比数据（指标+曲线+策略代码）"""

    @gen.coroutine
    def get(self):
        try:
            ids_str = self.get_argument('ids', '')
            if not ids_str:
                self.write(json.dumps({'code': -1, 'msg': '缺少 ids 参数'}))
                return

            bt_ids = [int(x.strip()) for x in ids_str.split(',') if x.strip().isdigit()]
            if len(bt_ids) < 2:
                self.write(json.dumps({'code': -1, 'msg': '至少选择2个回测进行对比'}))
                return
            if len(bt_ids) > 10:
                self.write(json.dumps({'code': -1, 'msg': '最多支持10个回测对比'}))
                return

            _ensure_backtest_table()
            placeholders = ','.join(['%s'] * len(bt_ids))
            rows = mdb.executeSqlFetch(
                f'SELECT bp.id, bp.strategy_id, COALESCE(bp.strategy_name, sc.name), bp.start_date, bp.end_date, '
                f'bp.initial_cash, bp.status, bp.total_return, bp.annual_return, '
                f'bp.max_drawdown, bp.sharpe_ratio, bp.alpha, bp.beta, bp.win_rate, '
                f'bp.trade_count, bp.completed_at, bp.result_json, sc.code as strategy_code '
                f'FROM cn_stock_backtest_portfolio bp '
                f'LEFT JOIN cn_stock_strategy_code sc ON bp.strategy_id = sc.id '
                f'WHERE bp.id IN ({placeholders}) ORDER BY bp.id',
                tuple(bt_ids))

            if not rows or len(rows) < 2:
                self.write(json.dumps({'code': -1, 'msg': '回测记录不足，无法对比'}))
                return

            backtests = []
            for r in rows:
                full_data = {}
                result_json = r[16]
                if result_json:
                    try:
                        full_data = json.loads(result_json) if isinstance(result_json, str) else result_json
                    except Exception:
                        pass

                metrics = full_data.get('metrics', {})
                if not metrics:
                    metrics = {
                        'total_return': float(r[7]) if r[7] else 0,
                        'annual_return': float(r[8]) if r[8] else 0,
                        'max_drawdown': float(r[9]) if r[9] else 0,
                        'sharpe_ratio': float(r[10]) if r[10] else 0,
                        'alpha': float(r[11]) if r[11] else 0,
                        'beta': float(r[12]) if r[12] else 0,
                        'daily_win_rate': float(r[13]) if r[13] else 0,
                        'trade_count': r[14] or 0,
                    }

                bt_item = {
                    'id': r[0],
                    'strategy_id': r[1],
                    'strategy_name': r[2] or '临时策略',
                    'start_date': str(r[3]) if r[3] else '',
                    'end_date': str(r[4]) if r[4] else '',
                    'initial_cash': float(r[5]) if r[5] else 0,
                    'status': r[6] or 'unknown',
                    'metrics': metrics,
                    'nav': full_data.get('nav', []),
                    'trades': full_data.get('trades', []),
                    'strategy_code': full_data.get('strategy_code_snapshot') or r[17] or '',
                    'completed_at': r[15].strftime('%Y-%m-%d %H:%M:%S') if r[15] else '',
                    'params': full_data.get('params', {}),
                }
                backtests.append(bt_item)

            self.write(json.dumps({'code': 0, 'data': {'backtests': backtests}},
                                  ensure_ascii=False, default=str))
        except Exception as e:
            logging.error("GetBacktestCompare异常", exc_info=True)
            self.write(json.dumps({'code': -1, 'msg': str(e)}))


class DeleteBacktestHandler(webBase.BaseHandler, ABC):
    """批量删除回测记录"""

    @gen.coroutine
    def post(self):
        try:
            body = json.loads(self.request.body)
            ids = body.get('ids', [])
            if not ids or not isinstance(ids, list):
                self.write(json.dumps({'code': -1, 'msg': '缺少 ids 参数'}))
                return
            # 过滤合法整数
            bt_ids = [int(x) for x in ids if isinstance(x, (int, float, str)) and str(x).strip().isdigit()]
            if not bt_ids:
                self.write(json.dumps({'code': -1, 'msg': 'ids 参数无效'}))
                return

            _ensure_backtest_table()
            placeholders = ','.join(['%s'] * len(bt_ids))
            mdb.executeSql(
                f'DELETE FROM cn_stock_backtest_portfolio WHERE id IN ({placeholders})',
                tuple(bt_ids))
            self.write(json.dumps({'code': 0, 'data': {'deleted': len(bt_ids)}}))
        except Exception as e:
            logging.error("DeleteBacktest异常", exc_info=True)
            self.write(json.dumps({'code': -1, 'msg': str(e)}))


class GetPortfolioBacktestListPageHandler(webBase.BaseHandler, ABC):
    """获取历史回测列表（分页版本）"""

    # 允许排序的列白名单（防止 SQL 注入）
    _SORT_WHITELIST = {
        'id', 'total_return', 'annual_return', 'max_drawdown',
        'sharpe_ratio', 'trade_count', 'completed_at', 'win_rate',
        'alpha', 'beta', 'initial_cash',
    }

    @gen.coroutine
    def get(self):
        try:
            _ensure_backtest_table()
            strategy_id = self.get_argument('strategy_id', None)
            page = int(self.get_argument('page', '1'))
            page_size = int(self.get_argument('page_size', '20'))
            sort_by = self.get_argument('sort_by', 'total_return')
            sort_order = self.get_argument('sort_order', 'desc')
            if page < 1:
                page = 1
            if page_size < 1 or page_size > 200:
                page_size = 20
            if sort_by not in self._SORT_WHITELIST:
                sort_by = 'total_return'
            if sort_order.lower() not in ('asc', 'desc'):
                sort_order = 'desc'
            offset = (page - 1) * page_size

            where = ''
            params = []
            if strategy_id:
                where = 'WHERE bp.strategy_id = %s'
                params.append(int(strategy_id))

            # 总数
            count_row = mdb.executeSqlFetch(
                f'SELECT COUNT(*) FROM cn_stock_backtest_portfolio bp {where}',
                tuple(params) if params else None)
            total = count_row[0][0] if count_row else 0

            order_clause = f'ORDER BY bp.{sort_by} {sort_order.upper()}'
            rows = mdb.executeSqlFetch(
                f'SELECT bp.id, bp.strategy_id, COALESCE(bp.strategy_name, sc.name) as strategy_name, '
                f'bp.start_date, bp.end_date, bp.initial_cash, bp.status, '
                f'bp.total_return, bp.annual_return, bp.max_drawdown, '
                f'bp.sharpe_ratio, bp.alpha, bp.beta, bp.win_rate, '
                f'bp.trade_count, bp.completed_at, bp.result_json '
                f'FROM cn_stock_backtest_portfolio bp '
                f'LEFT JOIN cn_stock_strategy_code sc ON bp.strategy_id = sc.id '
                f'{where} {order_clause} LIMIT %s OFFSET %s',
                tuple(params + [page_size, offset]) if params else (page_size, offset))
            data = []
            if rows:
                for r in rows:
                    extra_metrics = {}
                    elapsed = ''
                    if r[16]:
                        try:
                            rj = json.loads(r[16]) if isinstance(r[16], str) else r[16]
                            m = rj.get('metrics', {})
                            extra_metrics = {
                                'benchmark_return': float(m.get('benchmark_return', 0)),
                                'excess_return': float(m.get('excess_return', 0)),
                                'excess_max_drawdown': float(m.get('excess_max_drawdown', 0)),
                                'excess_sharpe_ratio': float(m.get('excess_sharpe_ratio', 0)),
                                'benchmark_annual_return': float(m.get('benchmark_annual_return', 0)),
                                'sortino_ratio': float(m.get('sortino_ratio', 0)),
                                'information_ratio': float(m.get('information_ratio', 0)),
                                'profit_loss_ratio': float(m.get('profit_loss_ratio', 0)),
                                'strategy_volatility': float(m.get('strategy_volatility', 0)),
                            }
                            elapsed = rj.get('elapsed', '')
                        except Exception as e:
                            logging.debug(f"result_json 解析异常（回测列表分页）: id={r[0]} - {e}")
                    item = {
                        'id': r[0],
                        'strategy_id': r[1],
                        'strategy_name': r[2] or '临时策略',
                        'start_date': str(r[3]) if r[3] else '',
                        'end_date': str(r[4]) if r[4] else '',
                        'initial_cash': float(r[5]) if r[5] else 0,
                        'status': r[6] or 'unknown',
                        'total_return': float(r[7]) if r[7] else 0,
                        'annual_return': float(r[8]) if r[8] else 0,
                        'max_drawdown': float(r[9]) if r[9] else 0,
                        'sharpe_ratio': float(r[10]) if r[10] else 0,
                        'alpha': float(r[11]) if r[11] else 0,
                        'beta': float(r[12]) if r[12] else 0,
                        'win_rate': float(r[13]) if r[13] else 0,
                        'trade_count': r[14] or 0,
                        'completed_at': r[15].strftime('%Y-%m-%d %H:%M:%S') if r[15] else '',
                        'elapsed': elapsed,
                    }
                    item.update(extra_metrics)
                    data.append(item)
            self.write(json.dumps({
                'code': 0,
                'data': data,
                'total': total,
                'page': page,
                'page_size': page_size,
            }, ensure_ascii=False))
        except Exception as e:
            self.write(json.dumps({'code': -1, 'msg': str(e)}))


# ── 辅助函数 ──

def _insert_and_get_id(sql, params=()):
    """INSERT 并返回 LAST_INSERT_ID()，在同一个连接中完成。
    线程安全，带错误处理和连接失效保护。"""
    try:
        with mdb.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                cur.execute('SELECT LAST_INSERT_ID()')
                row = cur.fetchone()
                if row is None:
                    raise RuntimeError("LAST_INSERT_ID() 返回 None，INSERT 可能未成功")
                return row[0]
    except Exception:
        mdb._invalidate_shared_conn()
        raise


def _row_get(row, key, index, default=None):
    if isinstance(row, dict):
        return row.get(key, default)
    if isinstance(row, (list, tuple)) and len(row) > index:
        return row[index]
    return default


_TEMPLATE_PARAM_SELF_HEAL_SNIPPET = r'''\

# [Quantia Template Param Self-Heal v1]
def _quantia_set_default(name, value):
    try:
        if not hasattr(g, name):
            setattr(g, name, value)
    except Exception:
        pass


def _quantia_param_self_heal():
    _quantia_set_default('ma60_slope_min', -0.005)
    _quantia_set_default('scan_interval', 1)
    _quantia_set_default('_day', 0)
    _quantia_set_default('_bars_cache', {})
    _quantia_set_default('_bars_cache_day', None)
    _quantia_set_default('flat_lookback', 5)
    _quantia_set_default('slope_lookback', 3)
    _quantia_set_default('high_window', 250)
    _quantia_set_default('cross_lookback', 5)
    _quantia_set_default('near_band', 0.10)
    _quantia_set_default('stop_loss', 0.08)
    _quantia_set_default('fund_bad', set())
    _quantia_set_default('fund_month', None)


try:
    _quantia_orig_initialize = initialize
except Exception:
    _quantia_orig_initialize = None


if _quantia_orig_initialize is not None:
    def initialize(context):
        _quantia_orig_initialize(context)
        _quantia_param_self_heal()


try:
    _quantia_orig_handle_data = handle_data
except Exception:
    _quantia_orig_handle_data = None


if _quantia_orig_handle_data is not None:
    def handle_data(context, data):
        _quantia_param_self_heal()
        return _quantia_orig_handle_data(context, data)
'''


def _inject_template_param_self_heal(code):
    code = (code or '').strip()
    if not code:
        return code
    if '[Quantia Template Param Self-Heal v1]' in code:
        return code
    return code + _TEMPLATE_PARAM_SELF_HEAL_SNIPPET


def _strip_template_param_self_heal(code):
    code = code or ''
    if '[Quantia Template Param Self-Heal v1]' not in code:
        return code
    return code.replace(_TEMPLATE_PARAM_SELF_HEAL_SNIPPET, '').strip()


def _normalized_strategy_templates(templates):
    normalized = []
    for tpl in (templates or []):
        item = dict(tpl)
        item['code'] = _inject_template_param_self_heal(item.get('code', ''))
        normalized.append(item)
    return normalized


def sync_strategy_templates_to_db(templates=None):
    """Upsert built-in strategy templates into the strategy table.

    The frontend edit and backtest pages run the strategy code stored in
    cn_stock_strategy_code, so template source changes must be copied there.
    """
    _ensure_strategy_table()
    updated = 0
    inserted = 0
    unchanged = 0
    skipped_user_modified = 0
    target_templates = _normalized_strategy_templates(templates or STRATEGY_TEMPLATES)

    for tpl in target_templates:
        template_id = tpl.get('id', tpl['name'])
        name = tpl['name']
        code = tpl['code']
        desc = tpl.get('description', '')
        cat = tpl.get('category', 'stock')
        code_hash = _template_hash(code)
        existing = mdb.executeSqlFetch(
            'SELECT id, code, description, category, template_hash, user_modified '
            'FROM cn_stock_strategy_code '
            "WHERE template_id=%s AND status!='archived' LIMIT 1",
            (template_id,))
        if not existing:
            existing = mdb.executeSqlFetch(
                'SELECT id, code, description, category, template_hash, user_modified '
                'FROM cn_stock_strategy_code '
                "WHERE name=%s AND status!='archived' LIMIT 1",
                (name,))
        if existing and len(existing) > 0:
            row = existing[0]
            eid = _row_get(row, 'id', 0)
            old_code = _row_get(row, 'code', 1, '') or ''
            old_desc = _row_get(row, 'description', 2, '') or ''
            old_cat = _row_get(row, 'category', 3, 'stock') or 'stock'
            user_modified = int(_row_get(row, 'user_modified', 5, 0) or 0)
            if user_modified and old_code != code:
                skipped_user_modified += 1
                continue
            if old_code == code and old_desc == desc and old_cat == cat:
                mdb.executeSql(
                    'UPDATE cn_stock_strategy_code SET template_id=%s, template_hash=%s, user_modified=%s '
                    'WHERE id=%s AND (template_id IS NULL OR template_id!=%s OR template_hash IS NULL '
                    'OR template_hash!=%s OR user_modified!=0)',
                    (template_id, code_hash, 0, eid, template_id, code_hash))
                unchanged += 1
                continue
            mdb.executeSql(
                'UPDATE cn_stock_strategy_code SET code=%s, description=%s, category=%s, '
                'template_id=%s, template_hash=%s, user_modified=%s WHERE id=%s',
                (code, desc, cat, template_id, code_hash, 0, eid))
            updated += 1
        else:
            _insert_and_get_id(
                'INSERT INTO cn_stock_strategy_code '
                '(name, code, description, category, folder_id, initial_cash, '
                'benchmark, commission_rate, stamp_tax_rate, slippage, status, '
                'template_id, template_hash, user_modified) '
                'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                (name, code, desc, cat, 0, 1000000,
                 '000300', 0.0003, 0.001, 0.0005, 'active',
                 template_id, code_hash, 0))
            inserted += 1

    return {
        'updated': updated,
        'inserted': inserted,
        'unchanged': unchanged,
        'skipped_user_modified': skipped_user_modified,
    }


def _template_hash(code):
    return hashlib.md5((code or '').encode('utf-8')).hexdigest()


def _find_strategy_template(template_id):
    for tpl in _normalized_strategy_templates(STRATEGY_TEMPLATES):
        if tpl.get('id', tpl['name']) == template_id:
            return tpl
    return None


def _resolve_user_modified_flag(strategy_id, code):
    rows = mdb.executeSqlFetch(
        'SELECT template_id FROM cn_stock_strategy_code WHERE id=%s',
        (strategy_id,),
    )
    if not rows:
        return 0
    template_id = _row_get(rows[0], 'template_id', 0)
    if not template_id:
        return 0
    tpl = _find_strategy_template(template_id)
    current_code = _strip_template_param_self_heal(code)
    template_code = _strip_template_param_self_heal((tpl or {}).get('code') or '')
    if tpl and current_code.strip() == template_code.strip():
        return 0
    return 1


_strategy_table_ready = False

def _ensure_strategy_table():
    """确保策略表存在（含 folder/category 扩展字段）—— 仅首次调用时执行"""
    global _strategy_table_ready
    if _strategy_table_ready:
        return
    if not mdb.checkTableIsExist('cn_stock_strategy_code'):
        mdb.executeSql('''
            CREATE TABLE IF NOT EXISTS `cn_stock_strategy_code` (
                `id` INT AUTO_INCREMENT PRIMARY KEY,
                `name` VARCHAR(100) NOT NULL,
                `code` TEXT NOT NULL,
                `description` TEXT,
                `category` VARCHAR(30) DEFAULT 'stock' COMMENT '分类: stock/multi_factor/portfolio/blank',
                `folder_id` INT DEFAULT 0 COMMENT '文件夹ID,0=根目录',
                `initial_cash` DECIMAL(15,2) DEFAULT 1000000.00,
                `benchmark` VARCHAR(20) DEFAULT '000300',
                `commission_rate` DECIMAL(8,6) DEFAULT 0.000300,
                `stamp_tax_rate` DECIMAL(8,6) DEFAULT 0.001000,
                `slippage` DECIMAL(8,6) DEFAULT 0.000500,
                `compile_count` INT DEFAULT 0 COMMENT '历史编译运行次数',
                `backtest_count` INT DEFAULT 0 COMMENT '历史回测次数',
                `template_id` VARCHAR(100) DEFAULT NULL COMMENT '内置模板ID',
                `template_hash` CHAR(32) DEFAULT NULL COMMENT '内置模板代码哈希',
                `user_modified` TINYINT DEFAULT 0 COMMENT '是否由用户修改过内置模板',
                `source` ENUM('manual','template','ai') NOT NULL DEFAULT 'manual' COMMENT '代码来源',
                `ai_prompt` TEXT NULL COMMENT '最近一次 AI 生成/修改使用的 prompt',
                `ai_model` VARCHAR(64) NULL,
                `ai_agent` VARCHAR(64) NULL COMMENT '使用的 agent 名',
                `ai_repair_count` INT NOT NULL DEFAULT 0 COMMENT '自动修复次数',
                `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
                `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                `status` ENUM('draft','active','archived') DEFAULT 'draft'
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        ''')
    else:
        # 增量添加新字段（通过 INFORMATION_SCHEMA 检查列是否存在，避免 ALTER TABLE 报错）
        def _column_exists(table_name, column_name):
            """通过 INFORMATION_SCHEMA 检查列是否存在（MySQL 全版本兼容）"""
            try:
                with mdb.get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS "
                            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s",
                            (table_name, column_name)
                        )
                        return cur.fetchone() is not None
            except Exception as e:
                logging.warning(f"检查列是否存在异常：{table_name}.{column_name} - {e}")
                return True  # 出错时保守地认为列已存在，避免重复 ALTER

        def _add_col_safe(table_name, col_name, col_def):
            """安全添加列：先检查再 ALTER，避免静默异常"""
            if _column_exists(table_name, col_name):
                return  # 列已存在，无需操作
            try:
                with mdb.get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(f'ALTER TABLE `{table_name}` ADD COLUMN {col_def}')
                logging.info(f"成功添加列：{table_name}.{col_name}")
            except Exception as e:
                logging.warning(f"ALTER TABLE ADD COLUMN 异常：{table_name}.{col_name} - {e}")

        _add_col_safe('cn_stock_strategy_code', 'category', '`category` VARCHAR(30) DEFAULT "stock" AFTER `description`')
        _add_col_safe('cn_stock_strategy_code', 'folder_id', '`folder_id` INT DEFAULT 0 AFTER `category`')
        _add_col_safe('cn_stock_strategy_code', 'compile_count', '`compile_count` INT DEFAULT 0 AFTER `slippage`')
        _add_col_safe('cn_stock_strategy_code', 'backtest_count', '`backtest_count` INT DEFAULT 0 AFTER `compile_count`')
        _add_col_safe('cn_stock_strategy_code', 'template_id', '`template_id` VARCHAR(100) DEFAULT NULL AFTER `backtest_count`')
        _add_col_safe('cn_stock_strategy_code', 'template_hash', '`template_hash` CHAR(32) DEFAULT NULL AFTER `template_id`')
        _add_col_safe('cn_stock_strategy_code', 'user_modified', '`user_modified` TINYINT DEFAULT 0 AFTER `template_hash`')
        # AI 来源元数据（§3.1 / M2 一并完成）
        _add_col_safe('cn_stock_strategy_code', 'source',
                      "`source` ENUM('manual','template','ai') NOT NULL DEFAULT 'manual' AFTER `user_modified`")
        _add_col_safe('cn_stock_strategy_code', 'ai_prompt',
                      "`ai_prompt` TEXT NULL COMMENT '最近一次 AI 生成/修改使用的 prompt' AFTER `source`")
        _add_col_safe('cn_stock_strategy_code', 'ai_model',
                      "`ai_model` VARCHAR(64) NULL AFTER `ai_prompt`")
        _add_col_safe('cn_stock_strategy_code', 'ai_agent',
                      "`ai_agent` VARCHAR(64) NULL COMMENT '使用的 agent 名' AFTER `ai_model`")
        _add_col_safe('cn_stock_strategy_code', 'ai_repair_count',
                      "`ai_repair_count` INT NOT NULL DEFAULT 0 COMMENT '自动修复次数' AFTER `ai_agent`")

    # 确保文件夹表存在
    if not mdb.checkTableIsExist('cn_stock_strategy_folder'):
        mdb.executeSql('''
            CREATE TABLE IF NOT EXISTS `cn_stock_strategy_folder` (
                `id` INT AUTO_INCREMENT PRIMARY KEY,
                `name` VARCHAR(100) NOT NULL,
                `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        ''')
    _strategy_table_ready = True


class CreateFolderHandler(webBase.BaseHandler, ABC):
    """创建文件夹"""
    @gen.coroutine
    def post(self):
        try:
            body = json.loads(self.request.body)
            name = body.get('name', '').strip()
            if not name:
                self.write(json.dumps({'code': -1, 'msg': '文件夹名称不能为空'}))
                return
            _ensure_strategy_table()
            folder_id = _insert_and_get_id(
                'INSERT INTO cn_stock_strategy_folder (name) VALUES (%s)', (name,))
            self.write(json.dumps({'code': 0, 'data': {'id': folder_id}}))
        except Exception as e:
            self.write(json.dumps({'code': -1, 'msg': str(e)}))


class RenameFolderHandler(webBase.BaseHandler, ABC):
    """重命名文件夹"""
    @gen.coroutine
    def post(self):
        try:
            body = json.loads(self.request.body)
            folder_id = body.get('id')
            name = body.get('name', '').strip()
            if not folder_id or not name:
                self.write(json.dumps({'code': -1, 'msg': '参数错误'}))
                return
            mdb.executeSql('UPDATE cn_stock_strategy_folder SET name=%s WHERE id=%s', (name, folder_id))
            self.write(json.dumps({'code': 0}))
        except Exception as e:
            self.write(json.dumps({'code': -1, 'msg': str(e)}))


class DeleteFolderHandler(webBase.BaseHandler, ABC):
    """删除文件夹（策略移到根目录）"""
    @gen.coroutine
    def post(self):
        try:
            body = json.loads(self.request.body)
            folder_id = body.get('id')
            if not folder_id:
                self.write(json.dumps({'code': -1, 'msg': '参数错误'}))
                return
            mdb.executeSql('UPDATE cn_stock_strategy_code SET folder_id=0 WHERE folder_id=%s', (folder_id,))
            mdb.executeSql('DELETE FROM cn_stock_strategy_folder WHERE id=%s', (folder_id,))
            self.write(json.dumps({'code': 0}))
        except Exception as e:
            self.write(json.dumps({'code': -1, 'msg': str(e)}))


class MoveStrategyHandler(webBase.BaseHandler, ABC):
    """将策略移动到指定文件夹"""
    @gen.coroutine
    def post(self):
        try:
            body = json.loads(self.request.body)
            strategy_ids = body.get('ids', [])
            folder_id = body.get('folder_id', 0)
            if not strategy_ids:
                self.write(json.dumps({'code': -1, 'msg': '未选择策略'}))
                return
            placeholders = ','.join(['%s'] * len(strategy_ids))
            mdb.executeSql(
                f'UPDATE cn_stock_strategy_code SET folder_id=%s WHERE id IN ({placeholders})',
                (folder_id, *strategy_ids))
            self.write(json.dumps({'code': 0}))
        except Exception as e:
            self.write(json.dumps({'code': -1, 'msg': str(e)}))


class BatchDeleteStrategyHandler(webBase.BaseHandler, ABC):
    """批量删除策略"""
    @gen.coroutine
    def post(self):
        try:
            body = json.loads(self.request.body)
            ids = body.get('ids', [])
            if not ids:
                self.write(json.dumps({'code': -1, 'msg': '未选择策略'}))
                return
            placeholders = ','.join(['%s'] * len(ids))
            mdb.executeSql(
                f'UPDATE cn_stock_strategy_code SET status=%s WHERE id IN ({placeholders})',
                ('archived', *ids))
            self.write(json.dumps({'code': 0}))
        except Exception as e:
            self.write(json.dumps({'code': -1, 'msg': str(e)}))


class RenameStrategyHandler(webBase.BaseHandler, ABC):
    """重命名策略"""
    @gen.coroutine
    def post(self):
        try:
            body = json.loads(self.request.body)
            strategy_id = body.get('id')
            name = body.get('name', '').strip()
            if not strategy_id or not name:
                self.write(json.dumps({'code': -1, 'msg': '参数错误'}))
                return
            mdb.executeSql('UPDATE cn_stock_strategy_code SET name=%s WHERE id=%s', (name, strategy_id))
            self.write(json.dumps({'code': 0}))
        except Exception as e:
            self.write(json.dumps({'code': -1, 'msg': str(e)}))


_backtest_table_ready = False

def _ensure_backtest_table():
    """确保回测任务表存在——仅首次调用时执行"""
    global _backtest_table_ready
    if _backtest_table_ready:
        return
    if not mdb.checkTableIsExist('cn_stock_backtest_portfolio'):
        mdb.executeSql('''
            CREATE TABLE IF NOT EXISTS `cn_stock_backtest_portfolio` (
                `id` INT AUTO_INCREMENT PRIMARY KEY,
                `strategy_id` INT,
                `strategy_name` VARCHAR(200) DEFAULT NULL COMMENT '策略名称快照（写入时冻结）',
                `start_date` DATE,
                `end_date` DATE,
                `initial_cash` DECIMAL(15,2),
                `benchmark` VARCHAR(20) DEFAULT '000300',
                `status` ENUM('pending','running','completed','failed') DEFAULT 'pending',
                `started_at` DATETIME,
                `completed_at` DATETIME,
                `error_message` TEXT,
                `total_return` DECIMAL(10,4),
                `annual_return` DECIMAL(10,4),
                `max_drawdown` DECIMAL(10,4),
                `sharpe_ratio` DECIMAL(10,4),
                `alpha` DECIMAL(10,4),
                `beta` DECIMAL(10,4),
                `win_rate` DECIMAL(10,4),
                `trade_count` INT,
                `result_json` LONGTEXT COMMENT '完整回测结果JSON',
                INDEX `idx_strategy` (`strategy_id`),
                INDEX `idx_status` (`status`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        ''')
    else:
        # 使用 _column_exists（在 _ensure_strategy_table 中定义）检查后再 ALTER
        try:
            _col_check_sql = (
                "SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'cn_stock_backtest_portfolio' "
                "AND COLUMN_NAME = 'result_json'"
            )
            with mdb.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(_col_check_sql)
                    if cur.fetchone() is None:
                        cur.execute('ALTER TABLE cn_stock_backtest_portfolio '
                                    'ADD COLUMN `result_json` LONGTEXT AFTER `trade_count`')
                        logging.info("成功添加列：cn_stock_backtest_portfolio.result_json")
                    # 添加 strategy_name 列（增量迁移）
                    cur.execute(
                        "SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS "
                        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'cn_stock_backtest_portfolio' "
                        "AND COLUMN_NAME = 'strategy_name'")
                    if cur.fetchone() is None:
                        cur.execute('ALTER TABLE cn_stock_backtest_portfolio '
                                    'ADD COLUMN `strategy_name` VARCHAR(200) DEFAULT NULL '
                                    'COMMENT %s AFTER `strategy_id`',
                                    ('策略名称快照（写入时冻结）',))
                        logging.info("成功添加列：cn_stock_backtest_portfolio.strategy_name")
                    # 添加 benchmark 列（历史库兼容）
                    cur.execute(
                        "SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS "
                        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'cn_stock_backtest_portfolio' "
                        "AND COLUMN_NAME = 'benchmark'")
                    if cur.fetchone() is None:
                        cur.execute('ALTER TABLE cn_stock_backtest_portfolio '
                                    "ADD COLUMN `benchmark` VARCHAR(20) DEFAULT '000300' AFTER `initial_cash`")
                        logging.info("成功添加列：cn_stock_backtest_portfolio.benchmark")
        except Exception as e:
            logging.warning(f"ALTER TABLE cn_stock_backtest_portfolio 异常：{e}")
    _backtest_table_ready = True
