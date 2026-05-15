#!/usr/bin/env python
"""
聚宽双均线策略回测验证 — 对比聚宽平台的收益概述指标

运行方式:
    python tests/run_jq_strategy_test.py

差异分析:
    由于数据源不同（本项目使用东方财富前复权数据，聚宽使用自有数据源），
    部分指标存在合理偏差。以下为预期的可接受差异范围:
    - 基准收益: ±2pp（指数数据源差异）
    - 策略收益: ±5pp（个股价格/信号差异）
    - 最大回撤: ±2pp
    - 夏普/索提诺: ±0.5
    - 超额收益最大回撤: ±1pp
    - 最大回撤区间: 起点一致，终点 ±2 天
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from quantia.core.backtest.portfolio_engine import run_backtest

STRATEGY_CODE = '''
# 双均线策略 (聚宽模板移植版)
# 5日均线择时：价格高于均价1%买入，低于均价卖出
# 标的：平安银行(000001)

def initialize(context):
    set_benchmark('000300')
    # 聚宽原版费率: 佣金万三, 印花税千一, 无滑点
    set_order_cost(commission=0.0003, tax=0.001, slippage=0.0)
    g.security = '000001'
    log.info('双均线策略初始化完成')

def handle_data(context, data):
    security = g.security
    # 获取最近5日收盘价
    close_data = history(security, 5, 'close')
    if len(close_data) < 5:
        return

    MA5 = close_data.mean()
    current_price = close_data.iloc[-1]
    cash = context.portfolio.available_cash

    # 价格高于均价1%, 全仓买入
    if (current_price > 1.01 * MA5) and (cash > 0):
        log.info('价格高于均价1%%, 买入 ' + security)
        order_value(security, cash)
    # 价格低于均价, 全仓卖出
    elif current_price < MA5:
        pos = context.portfolio.positions.get(security)
        if pos and pos.closeable_amount > 0:
            log.info('价格低于均价, 卖出 ' + security)
            order_target(security, 0)
'''

# 聚宽预期值（百分比统一为 % 格式，比率保持原样）
JQ_EXPECTED = {
    'total_return': -14.87,
    'annual_return': -8.00,
    'excess_return': -35.45,
    'benchmark_return': 31.87,
    'alpha': -0.170,
    'beta': 0.438,
    'sharpe_ratio': -0.852,
    'trade_win_rate': 21.6,       # JQ原值 0.216 → 21.6%
    'profit_loss_ratio': 0.734,
    'max_drawdown': 26.94,
    'sortino_ratio': -0.778,
    'avg_daily_excess': -0.09,
    'excess_max_drawdown': 36.87,
    'excess_sharpe_ratio': -1.558,
    'daily_win_rate': 44.1,       # JQ原值 0.441 → 44.1%
    'win_count': 8,
    'loss_count': 29,
    'information_ratio': -1.513,
    'strategy_volatility': 14.1,  # JQ原值 0.141 → 14.1%
    'benchmark_volatility': 18.2, # JQ原值 0.182 → 18.2%
    'max_drawdown_range': '2024/10/08 ~ 2026/02/13',
}

def main():
    import io, sys
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_tmp_result.txt')
    buf = io.StringIO()

    result = run_backtest(
        STRATEGY_CODE,
        start_date='2024-03-11',
        end_date='2026-03-10',
        initial_cash=100000,
        benchmark='000300',
        commission=0.0003,
        tax=0.001,
        slippage=0.0,
    )

    if result['status'] != 'completed':
        buf.write(f'FAILED: {result.get("message")}\n')
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(buf.getvalue())
        return

    m = result['metrics']

    buf.write('=' * 72 + '\n')
    buf.write(f'{"指标":<22} {"我们":>12} {"聚宽":>12} {"差异":>10}\n')
    buf.write('-' * 72 + '\n')

    checks = [
        ('策略收益%', 'total_return', '%'),
        ('策略年化收益%', 'annual_return', '%'),
        ('超额收益%', 'excess_return', '%'),
        ('基准收益%', 'benchmark_return', '%'),
        ('阿尔法', 'alpha', ''),
        ('贝塔', 'beta', ''),
        ('夏普比率', 'sharpe_ratio', ''),
        ('胜率', 'trade_win_rate', ''),
        ('盈亏比', 'profit_loss_ratio', ''),
        ('最大回撤%', 'max_drawdown', '%'),
        ('索提诺比率', 'sortino_ratio', ''),
        ('日均超额收益%', 'avg_daily_excess', '%'),
        ('超额收益最大回撤%', 'excess_max_drawdown', '%'),
        ('超额收益夏普比率', 'excess_sharpe_ratio', ''),
        ('日胜率', 'daily_win_rate', ''),
        ('盈利次数', 'win_count', 'int'),
        ('亏损次数', 'loss_count', 'int'),
        ('信息比率', 'information_ratio', ''),
        ('策略波动率', 'strategy_volatility', ''),
        ('基准波动率', 'benchmark_volatility', ''),
    ]

    for label, key, fmt in checks:
        ours = m.get(key, 0)
        jq = JQ_EXPECTED.get(key, 0)
        if fmt == 'int':
            diff = int(ours) - int(jq)
            s = f'{label:<22} {int(ours):>12} {int(jq):>12} {diff:>+10}'
        elif fmt == '%':
            diff = ours - jq
            s = f'{label:<22} {ours:>12.2f} {jq:>12.2f} {diff:>+10.2f}'
        else:
            diff = ours - jq
            s = f'{label:<22} {ours:>12.3f} {jq:>12.3f} {diff:>+10.3f}'
        buf.write(s + '\n')

    dd_range = f"{m.get('max_drawdown_start', '')} ~ {m.get('max_drawdown_end', '')}"
    buf.write(f'\n最大回撤区间: 我们={dd_range}  聚宽={JQ_EXPECTED["max_drawdown_range"]}\n')
    buf.write(f'交易次数: {m["trade_count"]}  交易日数: {m["trading_days"]}  耗时: {result["elapsed"]}s\n')

    trades = result.get('trades', [])
    buf.write(f'\n=== 前10笔交易 ===\n')
    for t in trades[:10]:
        buf.write(f'  {t["date"]} {t["direction"]:>4} {t["code"]} {t.get("name",""):>6} '
              f'价格={t["price"]:.2f} 数量={t["amount"]} 佣金={t["commission"]:.2f} '
              f'税={t["tax"]:.2f} 滑点={t["slippage_cost"]:.2f}\n')

    buf.write(f'\n=== 最后10笔交易 ===\n')
    for t in trades[-10:]:
        buf.write(f'  {t["date"]} {t["direction"]:>4} {t["code"]} {t.get("name",""):>6} '
              f'价格={t["price"]:.2f} 数量={t["amount"]} 佣金={t["commission"]:.2f} '
              f'税={t["tax"]:.2f} 滑点={t["slippage_cost"]:.2f}\n')

    text = buf.getvalue()
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(text)
    # Also print (may fail on non-utf8 console)
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        print(text)
    except Exception:
        print("Results written to", out_path)

if __name__ == '__main__':
    main()
