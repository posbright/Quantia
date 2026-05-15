# -*- coding: utf-8 -*-
"""
低 ATR 成长策略（A股版）- 聚宽可回测实现
================================================

【策略概述】
本策略结合基本面成长因子和技术面低波动因子，
在A股市场中选取"业绩持续增长 + 走势稳健"的标的，
通过定期调仓和风控机制实现稳健的超额收益。

【核心逻辑】
1. 基础股票池过滤：去除ST/停牌/科创板/北交所/新股，确保流动性
2. 基本面成长筛选：营收增速 > 阈值、净利润增速 > 阈值、ROE > 阈值、
   经营现金流为正、资产负债率 < 阈值
3. 技术面过滤：
   - ATR(14)/收盘价 < 阈值 → 确保波动率低
   - 收盘价 > MA20 > MA60 → 多头排列
   - MA60 近期向上 → 中期趋势向好
   - 60 日涨幅在合理区间 → 避免追高或选弱势股
4. 综合评分排序：成长性 + 盈利质量 + 低波动 + 趋势强度加权打分
5. 定期调仓：每周调仓一次（周一），等权配置
6. 风控机制：
   - 固定止损（成本价 * (1 - 止损比例)）
   - 跌破 MA20 清仓
   - 过热止盈（偏离 MA20 超过阈值时减半仓）

【适用环境】
- 震荡偏多或温和上涨的市场环境效果最佳
- 极端单边下跌行情中仍会有回撤，但止损机制可控制损失
- 适合中长线持有，不适合超短线操作

【参数调优说明】
- 回测时建议至少 6 个月以上的数据区间
- 参数已基于 2023-2025 年A股市场数据调优
- max_hold_num 控制分散度，过大会稀释收益，过小会增大单票风险
- atr_pct_max 是核心参数：值越小选的股票越平稳，但候选池越窄
"""

import numpy as np
import pandas as pd
from jqdata import *
from jqlib.technical_analysis import ATR

# =============================================
# 第1部分：策略初始化
# =============================================
def initialize(context):
    """
    策略初始化函数 — 在回测开始时调用一次。

    完成以下设置：
    1. 设置基准指数（沪深300）
    2. 使用真实价格模式
    3. 配置交易成本（佣金 + 印花税 + 最低佣金）
    4. 定义所有策略参数（存储在全局变量 g 中）
    5. 注册定期调仓和风控回调
    """

    # --- 基准与环境设置 ---
    # 设置沪深300为基准，回测结果会对比基准收益
    set_benchmark('000300.XSHG')
    # 使用实际成交价进行回测（非复权价）
    set_option('use_real_price', True)
    # 仅在订单级别记录日志，减少噪声
    log.set_level('order', 'error')

    # --- 交易成本设置 ---
    # 模拟真实交易环境的手续费和税费
    set_order_cost(
        OrderCost(
            open_tax=0,             # 买入无印花税
            close_tax=0.001,        # 卖出印花税千分之一
            open_commission=0.0003, # 买入佣金万三
            close_commission=0.0003,# 卖出佣金万三
            close_today_commission=0, # 不单独收取今仓平仓费
            min_commission=5        # 最低佣金5元/笔
        ),
        type='stock'
    )

    # =============================================
    # 策略参数（可根据回测结果调整优化）
    # =============================================

    # --- 持仓管理 ---
    g.max_hold_num = 8                 # 最大持仓数（适度集中，8只兼顾分散与收益）
    g.rebalance_weekday = 1            # 每周第几个交易日调仓（1=周一）

    # --- 基础过滤条件 ---
    g.min_list_days = 180              # 最少上市天数（180天，过滤次新股波动）
    g.min_price = 3                    # 最低股价（3元，排除低价股风险）
    g.min_amount_20 = 3e7              # 20日日均成交额下限（3000万，确保流动性）

    # --- ATR 波动率过滤（核心参数）---
    g.atr_n = 14                       # ATR 计算周期（14日标准周期）
    g.atr_pct_max = 0.045              # ATR/收盘价 上限（4.5%，适度放宽以扩大候选池）

    # --- 趋势与动量参数 ---
    g.ret60_min = 0.02                 # 60日最低涨幅（2%，轻微上涨即可入选）
    g.ret60_max = 0.50                 # 60日最高涨幅（50%，避免过热股）
    g.high60_ratio_min = 0.85          # 当前价/60日最高价 下限（85%，允许适度回调）

    # --- 风控参数 ---
    g.stop_loss_pct = 0.10             # 固定止损比例（10%，给予合理波动空间）
    g.take_profit_ma20_gap = 0.20      # 偏离MA20止盈阈值（20%，过热减仓）

    # --- 基本面筛选参数 ---
    g.query_limit = 300                # 基本面初筛返回数量（增大以找到更多候选）
    g.stock_pool_limit = 200           # 技术面复筛最大数量（控制计算量）

    # --- 注册定时任务 ---
    # 每周一 10:30 执行调仓（避开开盘波动）
    run_weekly(rebalance, weekday=1, time='10:30')
    # 每日 14:30 执行风控检查（盘中最后时段，价格趋于稳定）
    run_daily(risk_control, time='14:30')

    log.info('低ATR成长策略初始化完成 | 最大持仓={} | ATR阈值={:.1%} | 止损={:.0%}'.format(
        g.max_hold_num, g.atr_pct_max, g.stop_loss_pct))


# =============================================
# 第2部分：工具函数
# =============================================

def filter_basic_stock(context, stock_list):
    """
    基础股票池过滤 — 去除不适合交易的股票。

    过滤规则：
    1. 去除科创板（688xxx）和北交所（8xxx/4xxx）
    2. 去除 ST/*ST 股票（有退市风险）
    3. 去除停牌股票（无法交易）
    4. 去除上市时间不足 min_list_days 的新股（波动大、规律弱）

    Args:
        context: 策略上下文，包含 current_dt 等信息
        stock_list: 待过滤的股票代码列表

    Returns:
        list: 过滤后的股票代码列表
    """
    current_data = get_current_data()
    filtered = []

    for stock in stock_list:
        # --- 板块过滤 ---
        # 科创板：代码以 688 开头，波动大、涨跌幅 20%
        if stock.startswith('688'):
            continue
        # 北交所：代码以 8 或 4 开头
        if stock.startswith('8') or stock.startswith('4'):
            continue

        # --- ST / 停牌 / 退市风险 ---
        # is_st 属性标记当前是否为 ST 状态
        if current_data[stock].is_st:
            continue
        # 名称中包含 ST 或 * 的也排除（含 *ST、ST、S*ST 等变体）
        stock_name = current_data[stock].name
        if 'ST' in stock_name or '*' in stock_name:
            continue
        # 排除停牌（无法交易的股票）
        if current_data[stock].paused:
            continue

        # --- 上市时间检查 ---
        # 获取股票上市日期，过滤不足 min_list_days 天的次新股
        info = get_security_info(stock)
        if info is None:
            continue
        days_listed = (context.current_dt.date() - info.start_date).days
        if days_listed < g.min_list_days:
            continue

        filtered.append(stock)

    return filtered


def filter_limit_tradeable(stock_list):
    """
    涨跌停过滤 — 去除接近涨停/跌停的股票。

    逻辑说明：
    - 接近涨停（最新价 >= 涨停价 * 99.5%）→ 买不进去
    - 接近跌停（最新价 <= 跌停价 * 100.5%）→ 卖不出去
    - 保留价格在正常区间的股票

    Args:
        stock_list: 候选股票列表

    Returns:
        list: 过滤后可正常交易的股票列表
    """
    current_data = get_current_data()
    res = []
    for stock in stock_list:
        try:
            last_price = current_data[stock].last_price
            high_limit = current_data[stock].high_limit
            low_limit = current_data[stock].low_limit
        except:
            continue

        # 接近涨停 → 无法买入，跳过
        if last_price >= high_limit * 0.995:
            continue
        # 接近跌停 → 无法卖出，跳过
        if last_price <= low_limit * 1.005:
            continue

        res.append(stock)
    return res


def get_fundamental_candidates(context):
    """
    基本面成长初筛 — 从全市场中选出基本面达标的候选股票。

    筛选条件（聚宽财务字段）：
    ┌───────────────────────────────────┬──────────┐
    │ 指标                              │ 阈值     │
    ├───────────────────────────────────┼──────────┤
    │ 营收同比增长率 (inc_total_revenue) │ > 15%    │
    │ 净利润同比增长率 (inc_net_profit)  │ > 20%    │
    │ ROE (净资产收益率)                 │ > 10%    │
    │ 经营活动现金流净额                  │ > 0      │
    │ 资产负债率                         │ < 70%    │
    └───────────────────────────────────┴──────────┘

    Returns:
        DataFrame: 包含 code, revenue_yoy, profit_yoy, roe 等列
    """
    # 获取全 A 股列表并进行基础过滤
    stock_list = list(get_all_securities(types=['stock'], date=context.current_dt).index)
    stock_list = filter_basic_stock(context, stock_list)

    # 构建聚宽风格的多表联合查询
    q = query(
        valuation.code,                              # 股票代码
        indicator.inc_total_revenue_year_on_year,     # 营收同比增长率 (%)
        indicator.inc_net_profit_year_on_year,        # 净利润同比增长率 (%)
        indicator.roe,                                # 净资产收益率 (%)
        balance.total_liability,                      # 总负债（元）
        balance.total_assets,                         # 总资产（元）
        cash_flow.net_operate_cash_flow               # 经营活动现金流净额（元）
    ).filter(
        valuation.code.in_(stock_list),               # 限定在基础池内
        indicator.inc_total_revenue_year_on_year > 15, # 营收增速 > 15%
        indicator.inc_net_profit_year_on_year > 20,    # 利润增速 > 20%
        indicator.roe > 10,                            # ROE > 10%（盈利能力强）
        cash_flow.net_operate_cash_flow > 0,           # 经营现金流为正（有真金白银）
        balance.total_liability / balance.total_assets < 0.70  # 资产负债率 < 70%（不过度举债）
    ).limit(g.query_limit)

    df = get_fundamentals(q)
    if df is None or len(df) == 0:
        return pd.DataFrame()

    # 去除含空值的行（数据不全的股票直接排除）
    df = df.dropna()
    if len(df) == 0:
        return pd.DataFrame()

    # 统一列名为简短别名，方便后续使用
    df = df.rename(columns={
        'code': 'code',
        'inc_total_revenue_year_on_year': 'revenue_yoy',
        'inc_net_profit_year_on_year': 'profit_yoy',
        'roe': 'roe',
        'net_operate_cash_flow': 'op_cashflow',
        'total_liability': 'total_liability',
        'total_assets': 'total_assets'
    })

    # 兼容不同环境的列名差异
    if 'revenue_yoy' not in df.columns and 'inc_total_revenue_year_on_year' in df.columns:
        df['revenue_yoy'] = df['inc_total_revenue_year_on_year']
    if 'profit_yoy' not in df.columns and 'inc_net_profit_year_on_year' in df.columns:
        df['profit_yoy'] = df['inc_net_profit_year_on_year']
    if 'op_cashflow' not in df.columns and 'net_operate_cash_flow' in df.columns:
        df['op_cashflow'] = df['net_operate_cash_flow']

    return df


def calc_technical_score(context, stock, fundamental_row):
    """
    技术面过滤与评分 — 对单只候选股票进行技术指标筛选和打分。

    技术过滤条件（所有条件必须同时满足）：
    1. 20日日均成交额 >= min_amount_20 → 流动性充足
    2. 最新股价 >= min_price → 排除低价股
    3. 收盘价 > MA20 > MA60 → 均线多头排列
    4. MA60 近5日上升 → 中期趋势向上
    5. 60日涨幅在 [ret60_min, ret60_max] 区间 → 不追高不选弱
    6. 当前价/60日最高 >= high60_ratio_min → 未大幅回调
    7. ATR(14)/收盘价 < atr_pct_max → 波动率低

    Args:
        context: 策略上下文
        stock: 股票代码（如 '000001'）
        fundamental_row: 基本面数据行（Series）

    Returns:
        dict: 评分指标字典；若不满足条件返回 None
    """
    # --- 获取近80个交易日的行情数据 ---
    # 需要80日数据是因为：MA60 需要60日 + ATR 需要14日 + 余量
    df = get_price(
        stock,
        end_date=context.current_dt,
        count=80,
        frequency='daily',
        fields=['open', 'high', 'low', 'close', 'money', 'paused'],
        fq='pre'  # 前复权，消除除权除息的影响
    )

    # 数据量不足，跳过（至少需要70个有效交易日）
    if df is None or len(df) < 70:
        return None

    df = df.dropna()
    if len(df) < 70:
        return None

    # --- 条件1：流动性检查 ---
    # 20日日均成交额（money字段），成交额太低说明有流动性风险
    amount20 = df['money'].tail(20).mean()
    if amount20 < g.min_amount_20:
        return None

    close = df['close']
    high = df['high']
    low = df['low']

    current_price = close.iloc[-1]

    # --- 条件2：最低股价 ---
    if current_price < g.min_price:
        return None

    # --- 计算均线 ---
    ma20 = close.rolling(20).mean()   # 20日均线（短期趋势）
    ma60 = close.rolling(60).mean()   # 60日均线（中期趋势）

    # 均线值必须有效（NaN 说明数据不够）
    if np.isnan(ma20.iloc[-1]) or np.isnan(ma60.iloc[-1]) or np.isnan(ma60.iloc[-5]):
        return None

    # --- 条件3：均线多头排列 ---
    # 收盘价 > MA20 > MA60 → 短中期趋势向上
    if not (current_price > ma20.iloc[-1] > ma60.iloc[-1]):
        return None

    # --- 条件4：MA60 上升趋势 ---
    # 对比5天前的MA60，确认中期趋势仍在上升
    if ma60.iloc[-1] <= ma60.iloc[-5]:
        return None

    # --- 条件5：60日涨幅在合理区间 ---
    # 涨幅 = (当前价 - 60日前价) / 60日前价
    ret60 = current_price / close.iloc[-60] - 1
    if ret60 < g.ret60_min or ret60 > g.ret60_max:
        return None

    # --- 条件6：离近期高点不远 ---
    # 当前价 / 60日最高价 >= 阈值 → 确保没有大幅回落
    high60 = close.tail(60).max()
    if current_price / high60 < g.high60_ratio_min:
        return None

    # --- 条件7：ATR 波动率检查 ---
    # ATR (Average True Range) 衡量股票的日均波动幅度
    try:
        # 优先使用聚宽内置 ATR 函数
        atr_dict = ATR(stock, check_date=context.current_dt, timeperiod=g.atr_n)
        atr_value = atr_dict.get(stock, np.nan)
    except:
        atr_value = np.nan

    # 若内置函数不可用，手动计算 ATR
    if pd.isna(atr_value):
        pre_close = close.shift(1)  # 前一日收盘价
        # True Range = max(当日高-低, |当日高-前收|, |当日低-前收|)
        tr = pd.concat([
            high - low,
            (high - pre_close).abs(),
            (low - pre_close).abs()
        ], axis=1).max(axis=1)
        # ATR = TR 的 N 日简单移动平均
        atr_value = tr.rolling(g.atr_n).mean().iloc[-1]

    if pd.isna(atr_value) or atr_value <= 0:
        return None

    # ATR百分比 = ATR / 收盘价 → 归一化的波动率指标
    atr_pct = atr_value / current_price
    if atr_pct >= g.atr_pct_max:
        return None

    # --- 构造评分指标 ---
    revenue_yoy = float(fundamental_row['revenue_yoy'])
    profit_yoy = float(fundamental_row['profit_yoy'])
    roe = float(fundamental_row['roe'])

    return {
        'code': stock,
        'revenue_yoy': revenue_yoy,    # 营收同比增长率
        'profit_yoy': profit_yoy,      # 净利润同比增长率
        'roe': roe,                     # ROE
        'atr_pct': float(atr_pct),     # ATR 百分比（越小越稳）
        'ret60': float(ret60),         # 60日涨幅
        'amount20': float(amount20),   # 20日日均成交额
        'price': float(current_price), # 当前股价
        'ma20': float(ma20.iloc[-1]),  # 20日均线值
        'ma60': float(ma60.iloc[-1]),  # 60日均线值
        'high60_ratio': float(current_price / high60),  # 距60日最高价比值
    }


def rank_and_select(candidates_df):
    """
    综合评分排序 — 对候选股票进行多因子打分并选出最优标的。

    评分维度与权重：
    ┌──────────────┬──────┬───────────────────────────┐
    │ 因子          │ 权重 │ 含义                       │
    ├──────────────┼──────┼───────────────────────────┤
    │ 营收增速      │ 25%  │ 越高越好                   │
    │ 利润增速      │ 30%  │ 越高越好（最重要因子）      │
    │ ROE          │ 15%  │ 越高越好（盈利能力）        │
    │ ATR 百分比    │ 20%  │ 越低越好（低波动）          │
    │ 60日涨幅      │ 10%  │ 越高越好（趋势强度）        │
    └──────────────┴──────┴───────────────────────────┘

    Args:
        candidates_df: 候选股票 DataFrame

    Returns:
        list: 最终选入的股票代码列表（最多 max_hold_num 只）
    """
    if candidates_df is None or len(candidates_df) == 0:
        return []

    df = candidates_df.copy()

    # 对每个因子做百分位排名（pct=True → 值域 0~1）
    df['score_revenue'] = df['revenue_yoy'].rank(pct=True)   # 营收：越高排名越高
    df['score_profit'] = df['profit_yoy'].rank(pct=True)     # 利润：越高排名越高
    df['score_roe'] = df['roe'].rank(pct=True)               # ROE：越高排名越高
    df['score_ret60'] = df['ret60'].rank(pct=True)           # 涨幅：越高排名越高
    df['score_atr'] = 1 - df['atr_pct'].rank(pct=True)      # ATR：越低排名越高（取反）

    # 加权综合评分
    df['score'] = (
        df['score_revenue'] * 0.25 +    # 营收增速权重 25%
        df['score_profit'] * 0.30 +     # 利润增速权重 30%（最高，成长性最重要）
        df['score_roe'] * 0.15 +        # ROE 权重 15%
        df['score_atr'] * 0.20 +        # 低波动权重 20%
        df['score_ret60'] * 0.10        # 趋势强度权重 10%
    )

    # 按综合评分降序排列，取前 max_hold_num 只
    df = df.sort_values('score', ascending=False)
    return list(df['code'].head(g.max_hold_num))


def get_target_stocks(context):
    """
    获取最终选股列表 — 串联基本面筛选和技术面筛选。

    流程：
    1. 基本面初筛 → 得到成长性达标的候选 DataFrame
    2. 控制候选数量（避免技术面筛选耗时过长）
    3. 逐只计算技术指标和评分
    4. 综合排序并选出最终标的
    5. 过滤涨跌停不可交易的股票

    Returns:
        list: 最终选入的股票代码列表
    """
    # 第一步：基本面筛选
    funda_df = get_fundamental_candidates(context)
    if funda_df is None or len(funda_df) == 0:
        log.info('基本面筛选无结果')
        return []

    # 控制技术面复筛数量，减少回测耗时
    if len(funda_df) > g.stock_pool_limit:
        funda_df = funda_df.sort_values(by='revenue_yoy', ascending=False).head(g.stock_pool_limit)

    # 第二步：遍历候选，计算技术指标和评分
    candidate_rows = []
    for _, row in funda_df.iterrows():
        stock = row['code']
        item = calc_technical_score(context, stock, row)
        if item is not None:
            candidate_rows.append(item)

    if len(candidate_rows) == 0:
        log.info('技术面筛选无结果')
        return []

    # 第三步：综合评分排序
    candidates_df = pd.DataFrame(candidate_rows)
    candidates_df = candidates_df.dropna()
    if len(candidates_df) == 0:
        return []

    selected = rank_and_select(candidates_df)

    # 第四步：过滤涨跌停（确保可以实际交易）
    selected = filter_limit_tradeable(selected)

    log.info('本期候选股 ({} 只): {}'.format(len(selected), selected))
    return selected


# =============================================
# 第3部分：调仓逻辑
# =============================================

def rebalance(context):
    """
    每周调仓函数 — 卖出不在目标池的持仓，等权买入目标股票。

    调仓逻辑：
    1. 获取本期目标股票列表
    2. 卖出当前持仓中不在目标列表的股票
    3. 将总资金等分，对每只目标股设定目标持仓金额
    4. 通过 order_target_value 自动计算需要买入/卖出的数量

    Args:
        context: 策略上下文（包含持仓信息和资金信息）
    """
    # 获取本期目标股票
    target_stocks = get_target_stocks(context)
    current_positions = list(context.portfolio.positions.keys())

    if len(target_stocks) == 0:
        log.info('无目标股票，本次不调仓')
        return

    # --- 先卖出：清除不在目标池的持仓 ---
    for stock in current_positions:
        if stock not in target_stocks:
            log.info('调仓卖出: {}'.format(stock))
            order_target_value(stock, 0)  # 目标持仓金额=0 → 全部卖出

    # --- 后买入：等权配置目标股票 ---
    # 用总市值（非可用现金）等分，避免因卖出延迟导致资金不足
    total_value = context.portfolio.total_value
    target_value = total_value / len(target_stocks)

    for stock in target_stocks:
        log.info('调仓买入/持有: {} (目标金额: {:.0f})'.format(stock, target_value))
        order_target_value(stock, target_value)


# =============================================
# 第4部分：风控逻辑
# =============================================

def risk_control(context):
    """
    每日风控函数 — 检查持仓是否触发止损/止盈条件。

    风控规则（按优先级执行，触发即操作）：
    1. 固定止损：当前价 < 持仓成本 * (1 - stop_loss_pct) → 全部卖出
       目的：控制单票最大亏损，防止深度套牢
    2. 跌破 MA20：当前价 < 20日均线 → 全部卖出
       目的：中短期趋势已转弱，及时离场
    3. 过热止盈：当前价 > MA20 * (1 + take_profit_ma20_gap) → 减半仓
       目的：涨幅过大偏离均线，部分落袋为安

    Args:
        context: 策略上下文
    """
    positions = context.portfolio.positions
    if len(positions) == 0:
        return

    for stock in list(positions.keys()):
        pos = positions[stock]
        # 跳过空仓（amount=0 的残留记录）
        if pos.total_amount <= 0:
            continue

        # 获取近25个交易日的收盘价数据
        price_df = get_price(
            stock,
            end_date=context.current_dt,
            count=25,
            frequency='daily',
            fields=['close'],
            fq='pre'
        )

        if price_df is None or len(price_df) < 20:
            continue

        close = price_df['close']
        current_price = close.iloc[-1]
        ma20 = close.rolling(20).mean().iloc[-1]

        if np.isnan(ma20):
            continue

        # --- 规则1：固定止损 ---
        # 如果当前价格跌破了买入成本的 (1 - stop_loss_pct)，触发止损
        avg_cost = pos.avg_cost
        if avg_cost > 0 and current_price < avg_cost * (1 - g.stop_loss_pct):
            log.info('止损卖出: {} | 成本={:.2f} 现价={:.2f} 亏损={:.1%}'.format(
                stock, avg_cost, current_price, current_price/avg_cost - 1))
            order_target_value(stock, 0)
            continue

        # --- 规则2：跌破 MA20 ---
        # 价格跌破短期均线，说明短期趋势走弱
        if current_price < ma20:
            log.info('跌破MA20卖出: {} | 价格={:.2f} MA20={:.2f}'.format(
                stock, current_price, ma20))
            order_target_value(stock, 0)
            continue

        # --- 规则3：过热止盈 ---
        # 价格远超均线，可能短期过热，减半仓落袋为安
        if current_price > ma20 * (1 + g.take_profit_ma20_gap):
            target_value = pos.value * 0.5  # 保留一半仓位
            log.info('过热止盈: {} | 价格={:.2f} MA20={:.2f} 偏离={:.1%}'.format(
                stock, current_price, ma20, current_price/ma20 - 1))
            order_target_value(stock, target_value)