#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
银行股轮动策略回测 — 对标聚宽数据验证

聚宽期望指标：
- 策略收益: 17.81%
- 年化收益: 8.84%
- 最大回撤: 28.49%
- 夏普比率: 0.253
- 交易次数: 2 (盈利)
- 回测区间: 2024-03-11 ~ 2026-03-11
- 初始资金: ¥100,000
"""

import sys
import os
import json

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quantia.core.backtest.portfolio_engine import run_backtest

STRATEGY_CODE = '''
# 银行股轮动策略（聚宽风格）
def initialize(context):
    set_benchmark('399951.XSHE')
    set_option('use_real_price', True)
    set_order_cost(OrderCost(
        open_tax=0,
        close_tax=0.001,
        open_commission=0.0003,
        close_commission=0.0003,
        close_today_commission=0,
        min_commission=5
    ), type='stock')
    g.stocks = get_index_stocks('399951.XSHE')
    run_weekly(weekly_adjustment, weekday=1, time='open')

def weekly_adjustment(context):
    q = query(
        valuation.code,
        valuation.pb_ratio
    ).filter(
        valuation.code.in_(g.stocks)
    ).order_by(
        valuation.pb_ratio.asc()
    ).limit(1)
    df = get_fundamentals(q)
    if len(df) == 0:
        log.warn("未查到银行股基本面数据")
        return

    target_code = df['code'].iloc[0]
    target_pb = df['pb_ratio'].iloc[0]
    log.info("本周目标: " + target_code + " PB=" + str(round(target_pb, 3)))

    for code in list(context.portfolio.positions.keys()):
        if code != target_code:
            order_target(code, 0)
            log.info("轮出 " + code)

    if target_code not in context.portfolio.positions:
        cash = context.portfolio.available_cash
        if cash > 1000:
            order_value(target_code, cash * 0.98)
            log.info("买入 " + target_code + " 金额=" + str(round(cash * 0.98)))
    else:
        log.info("继续持有 " + target_code)
'''

# 聚宽期望指标
JQ_EXPECTED = {
    'total_return': 17.81,
    'annual_return': 8.84,
    'max_drawdown': 28.49,
    'sharpe_ratio': 0.253,
    'win_rate': 100.0,       # 胜率 1.000
    'profit_trades': 2,
    'loss_trades': 0,
    'sortino_ratio': 0.198,
    'info_ratio': 0.463,
    'volatility': 19.1,      # 策略波动率 0.191 → 19.1%
}


def main():
    print("=" * 70)
    print("银行股轮动策略回测 — 对标聚宽验证")
    print("回测区间: 2024-03-11 ~ 2026-03-11")
    print("初始资金: ¥100,000")
    print("=" * 70)

    result = run_backtest(
        strategy_code=STRATEGY_CODE,
        start_date='2024-03-11',
        end_date='2026-03-11',
        initial_cash=100000,
        benchmark='399951',
        commission=0.0003,
        tax=0.001,
        slippage=0.002,
    )

    if result['status'] != 'completed':
        print(f"\n*** 回测失败: {result.get('message', '未知错误')} ***")
        return

    metrics = result['metrics']
    trades = result['trades']
    logs = result.get('logs', [])

    print(f"\n回测完成! 耗时: {result['elapsed']}s")
    print(f"交易记录数: {len(trades)}")

    # 展示核心指标
    print("\n" + "=" * 70)
    print(f"{'指标':<20} {'本引擎':>12} {'聚宽':>12} {'差异':>12}")
    print("-" * 70)

    comparisons = [
        ('策略收益(%)', metrics.get('total_return', 0), JQ_EXPECTED['total_return']),
        ('年化收益(%)', metrics.get('annual_return', 0), JQ_EXPECTED['annual_return']),
        ('最大回撤(%)', metrics.get('max_drawdown', 0), JQ_EXPECTED['max_drawdown']),
        ('夏普比率', metrics.get('sharpe_ratio', 0), JQ_EXPECTED['sharpe_ratio']),
        ('索提诺比率', metrics.get('sortino_ratio', 0), JQ_EXPECTED['sortino_ratio']),
        ('波动率(%)', metrics.get('strategy_volatility', 0), JQ_EXPECTED['volatility']),
    ]

    for name, ours, jq in comparisons:
        diff = ours - jq
        print(f"{name:<20} {ours:>12.2f} {jq:>12.2f} {diff:>+12.2f}")

    print("=" * 70)

    # 交易详情
    print(f"\n交易记录 ({len(trades)} 笔):")
    print(f"{'日期':<12} {'代码':<8} {'方向':<6} {'价格':>10} {'数量':>8}")
    print("-" * 50)
    for t in trades[:30]:
        print(f"{t['date']:<12} {t['code']:<8} {t['direction']:<6} "
              f"{t['price']:>10.2f} {t['amount']:>8d}")
    if len(trades) > 30:
        print(f"... 共 {len(trades)} 笔交易")

    # 实际盈利/亏损交易统计
    buy_trades = [t for t in trades if t['direction'] == 'buy']
    sell_trades = [t for t in trades if t['direction'] == 'sell']
    print(f"\n买入: {len(buy_trades)} 笔, 卖出: {len(sell_trades)} 笔")

    # 策略日志 (最后20条)
    if logs:
        print(f"\n策略日志 (最后20条):")
        for log_msg in logs[-20:]:
            print(f"  {log_msg}")

    # 总结
    print("\n" + "=" * 70)
    print("聚宽对比总结:")
    our_ret = metrics.get('total_return', 0)
    jq_ret = JQ_EXPECTED['total_return']
    ret_diff = abs(our_ret - jq_ret)
    our_dd = metrics.get('max_drawdown', 0)
    jq_dd = JQ_EXPECTED['max_drawdown']
    dd_diff = abs(our_dd - jq_dd)

    if ret_diff < 5 and dd_diff < 5:
        print("  ✓ 收益与回撤差异较小，策略适配良好")
    else:
        print(f"  ! 收益差异: {ret_diff:.2f}%, 回撤差异: {dd_diff:.2f}%")
        print("  分析可能原因:")
        print("    - PB估算为近似值(假设净资产不变)")
        print("    - 成份股列表为固定快照，JQ使用动态调整")
        print("    - 滑点/佣金模型差异")
        print("    - K线数据源差异（东方财富 vs JQ自有数据）")
    print("=" * 70)


if __name__ == '__main__':
    main()
