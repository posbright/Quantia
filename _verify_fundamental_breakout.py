# -*- coding: utf-8 -*-
"""
验证基本面底部突破策略
运行回测并输出关键指标
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quantia.core.backtest.portfolio_engine import PortfolioBacktestEngine


def main():
    # 读取策略代码
    strategy_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'quantia', 'core', 'strategy', 'templates',
        'fundamental_bottom_breakout.py'
    )
    with open(strategy_path, 'r', encoding='utf-8') as f:
        strategy_code = f.read()

    print("=" * 60)
    print("基本面底部突破策略 — 回测验证")
    print("=" * 60)

    engine = PortfolioBacktestEngine()
    result = engine.run(
        strategy_code=strategy_code,
        start_date='2024-06-01',
        end_date='2025-12-31',
        initial_cash=1000000,
        benchmark='000300',
        commission=0.0003,
        tax=0.001,
        slippage=0.002,
    )

    if result.get('status') == 'error':
        print(f"\n回测失败: {result.get('error', '未知错误')}")
        if 'traceback' in result:
            print(result['traceback'])
        return

    print(f"\n状态: {result.get('status')}")

    metrics = result.get('metrics', {})
    if metrics:
        print("\n" + "-" * 40)
        print("回测指标")
        print("-" * 40)
        print(f"  总收益率:     {metrics.get('total_return', 0)*100:.2f}%")
        print(f"  年化收益率:   {metrics.get('annual_return', 0)*100:.2f}%")
        print(f"  最大回撤:     {metrics.get('max_drawdown', 0)*100:.2f}%")
        print(f"  夏普比率:     {metrics.get('sharpe_ratio', 0):.3f}")
        print(f"  胜率:         {metrics.get('win_rate', 0)*100:.1f}%")
        print(f"  盈亏比:       {metrics.get('profit_loss_ratio', 0):.2f}")
        print(f"  交易次数:     {metrics.get('trade_count', 0)}")
        print(f"  基准收益率:   {metrics.get('benchmark_return', 0)*100:.2f}%")
        alpha = metrics.get('total_return', 0) - metrics.get('benchmark_return', 0)
        print(f"  超额收益:     {alpha*100:.2f}%")

    trades = result.get('trades', [])
    print(f"\n交易记录: {len(trades)} 笔")
    if trades:
        print("\n最近 10 笔交易:")
        for t in trades[-10:]:
            direction = "买入" if t.get('amount', 0) > 0 else "卖出"
            print(f"  {t.get('date', '')} {direction} {t.get('code', '')} "
                  f"价格={t.get('price', 0):.2f} 数量={abs(t.get('amount', 0))}")

    nav = result.get('nav', [])
    print(f"\n净值曲线: {len(nav)} 个数据点")
    if nav:
        print(f"  起始净值: {nav[0].get('value', 1.0):.4f}")
        print(f"  结束净值: {nav[-1].get('value', 1.0):.4f}")

    # 输出策略日志（最后20条）
    logs = result.get('logs', [])
    if logs:
        print(f"\n策略日志（最后 20 条 / 共 {len(logs)} 条）:")
        for msg in logs[-20:]:
            print(f"  {msg}")

    print("\n" + "=" * 60)
    print("回测完成")
    print("=" * 60)


if __name__ == '__main__':
    main()
