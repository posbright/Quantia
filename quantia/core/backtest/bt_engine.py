#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Backtrader 回测引擎适配器

提供与现有选股策略系统的集成，支持使用Backtrader进行回测。
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
import pandas as pd
import numpy as np
from importlib import import_module

try:
    bt = import_module('backtrader')
    BACKTRADER_AVAILABLE = True
except ModuleNotFoundError:
    BACKTRADER_AVAILABLE = False
    bt = None

__author__ = 'Quantia'
__date__ = '2026/02/14'


class PandasData(bt.feeds.PandasData if BACKTRADER_AVAILABLE else object):
    """
    自定义Pandas数据源，适配项目数据格式
    """
    if BACKTRADER_AVAILABLE:
        params = (
            ('datetime', 'date'),
            ('open', 'open'),
            ('high', 'high'),
            ('low', 'low'),
            ('close', 'close'),
            ('volume', 'volume'),
            ('openinterest', -1),
        )


class SignalStrategy(bt.Strategy if BACKTRADER_AVAILABLE else object):
    """
    信号策略基类

    用于将现有选股信号转换为Backtrader策略
    """
    if BACKTRADER_AVAILABLE:
        params = (
            ('signal_dates', []),  # 选股信号日期列表
            ('hold_days', 5),      # 持仓天数
            ('position_pct', 0.1), # 仓位比例
        )

        def __init__(self):
            self.order = None
            self.buy_date = None
            self.signal_dates = set(self.params.signal_dates)

        def notify_order(self, order):
            if order.status in [order.Submitted, order.Accepted]:
                return

            if order.status in [order.Completed]:
                if order.isbuy():
                    logging.info(f'买入执行: 价格={order.executed.price:.2f}, '
                                f'数量={order.executed.size:.0f}, '
                                f'成本={order.executed.value:.2f}')
                    self.buy_date = self.datas[0].datetime.date(0)
                elif order.issell():
                    logging.info(f'卖出执行: 价格={order.executed.price:.2f}, '
                                f'数量={order.executed.size:.0f}')

            self.order = None

        def next(self):
            if self.order:
                return

            current_date = self.datas[0].datetime.date(0)
            current_date_str = current_date.strftime('%Y-%m-%d')

            # 检查是否有持仓需要卖出
            if self.position:
                if self.buy_date:
                    hold_days = (current_date - self.buy_date).days
                    if hold_days >= self.params.hold_days:
                        self.order = self.sell(size=self.position.size)
                        return

            # 检查买入信号
            if current_date_str in self.signal_dates and not self.position:
                cash = self.broker.getcash()
                price = self.datas[0].close[0]
                size = int(cash * self.params.position_pct / price / 100) * 100
                if size > 0:
                    self.order = self.buy(size=size)


class BacktestEngine:
    """
    回测引擎

    封装Backtrader，提供简洁的回测接口
    """

    def __init__(self, initial_cash: float = 100000.0,
                 commission: float = 0.001,
                 slippage: float = 0.001):
        """
        初始化回测引擎

        Args:
            initial_cash: 初始资金
            commission: 佣金比例
            slippage: 滑点比例
        """
        if not BACKTRADER_AVAILABLE:
            raise ImportError("Backtrader未安装，请运行: pip install backtrader")

        self.initial_cash = initial_cash
        self.commission = commission
        self.slippage = slippage
        self.cerebro = None
        self.results = None

    def setup(self):
        """设置回测引擎"""
        self.cerebro = bt.Cerebro()
        self.cerebro.broker.setcash(self.initial_cash)
        self.cerebro.broker.setcommission(commission=self.commission)

        # 添加分析器
        self.cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
        self.cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
        self.cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
        self.cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

    def add_data(self, data: pd.DataFrame, name: str = 'data'):
        """
        添加数据源

        Args:
            data: 包含OHLCV数据的DataFrame
            name: 数据名称
        """
        if self.cerebro is None:
            self.setup()

        # 确保日期列正确
        df = data.copy()
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])
            df.set_index('date', inplace=True)

        feed = PandasData(dataname=df)
        self.cerebro.adddata(feed, name=name)

    def add_signal_strategy(self, signal_dates: List[str],
                           hold_days: int = 5,
                           position_pct: float = 0.1):
        """
        添加信号策略

        Args:
            signal_dates: 买入信号日期列表
            hold_days: 持仓天数
            position_pct: 仓位比例
        """
        if self.cerebro is None:
            self.setup()

        self.cerebro.addstrategy(
            SignalStrategy,
            signal_dates=signal_dates,
            hold_days=hold_days,
            position_pct=position_pct
        )

    def run(self) -> Dict[str, Any]:
        """
        运行回测

        Returns:
            回测结果字典
        """
        if self.cerebro is None:
            raise ValueError("请先设置回测引擎并添加数据")

        logging.info(f'初始资金: {self.initial_cash:.2f}')
        self.results = self.cerebro.run()
        final_value = self.cerebro.broker.getvalue()
        logging.info(f'最终资金: {final_value:.2f}')

        # 提取分析结果
        strat = self.results[0]
        analysis = {
            'initial_cash': self.initial_cash,
            'final_value': final_value,
            'total_return': (final_value - self.initial_cash) / self.initial_cash * 100,
            'sharpe': strat.analyzers.sharpe.get_analysis().get('sharperatio'),
            'drawdown': strat.analyzers.drawdown.get_analysis(),
            'trades': strat.analyzers.trades.get_analysis()
        }

        return analysis

    def plot(self, **kwargs):
        """绘制回测图表"""
        if self.cerebro is None or self.results is None:
            raise ValueError("请先运行回测")

        self.cerebro.plot(**kwargs)


class StrategyBacktester:
    """
    策略回测器

    用于批量回测选股策略
    """

    def __init__(self, initial_cash: float = 100000.0):
        """
        初始化策略回测器

        Args:
            initial_cash: 初始资金
        """
        self.initial_cash = initial_cash
        self.results = {}

    def backtest_signals(self,
                        stock_data: pd.DataFrame,
                        signal_dates: List[str],
                        hold_days: int = 5,
                        position_pct: float = 0.1) -> Dict[str, Any]:
        """
        回测选股信号

        Args:
            stock_data: 股票历史数据
            signal_dates: 选股信号日期列表
            hold_days: 持仓天数
            position_pct: 仓位比例

        Returns:
            回测结果
        """
        if not BACKTRADER_AVAILABLE:
            raise ImportError("Backtrader未安装")

        engine = BacktestEngine(initial_cash=self.initial_cash)
        engine.add_data(stock_data)
        engine.add_signal_strategy(signal_dates, hold_days, position_pct)

        return engine.run()

    def backtest_strategy(self,
                         strategy_name: str,
                         stocks_data: Dict[Tuple[str, str], pd.DataFrame],
                         start_date: str = None,
                         end_date: str = None,
                         hold_days: int = 5) -> Dict[str, Any]:
        """
        回测某个选股策略

        Args:
            strategy_name: 策略名称
            stocks_data: 股票数据字典
            start_date: 开始日期
            end_date: 结束日期
            hold_days: 持仓天数

        Returns:
            回测结果汇总
        """
        from ..strategy.base import get_strategy

        strategy_cls = get_strategy(strategy_name)
        strategy = strategy_cls()

        # 收集所有选股信号
        signals = []
        for code_name, data in stocks_data.items():
            if strategy.check(code_name, data):
                signals.append({
                    'date': code_name[0],
                    'code': code_name[1]
                })

        # 计算回测统计
        total_signals = len(signals)
        if total_signals == 0:
            return {
                'strategy': strategy_name,
                'total_signals': 0,
                'message': '无选股信号'
            }

        return {
            'strategy': strategy_name,
            'strategy_cn': strategy.cn_name,
            'total_signals': total_signals,
            'signals': signals
        }


def calculate_simple_returns(data: pd.DataFrame,
                            signal_date: str,
                            days: List[int] = None) -> Dict[int, float]:
    """
    计算简单收益率（兼容旧版本）

    修正：使用T+1开盘价作为买入基准，扣除交易成本。

    Args:
        data: 股票数据
        signal_date: 信号日期
        days: 收益天数列表

    Returns:
        各天数对应的收益率
    """
    from .rate_stats import ROUND_TRIP_COST_PCT

    if days is None:
        days = [1, 3, 5, 10, 20, 60]

    if not pd.api.types.is_datetime64_any_dtype(data['date']):
        data = data.copy()
        data['date'] = pd.to_datetime(data['date'])
    mask = data['date'] >= pd.Timestamp(signal_date)
    future_data = data.loc[mask].copy()

    # 至少需要信号日(T) + 执行日(T+1) = 2行
    if len(future_data) <= 1:
        return {d: None for d in days}

    # 使用T+1开盘价作为买入基准
    if 'open' in future_data.columns and len(future_data) >= 2:
        base_price = future_data.iloc[1]['open']
    else:
        base_price = future_data.iloc[0]['close']

    if base_price <= 0 or np.isnan(base_price):
        return {d: None for d in days}

    results = {}

    for d in days:
        # d=1 → future_data.iloc[1] → T+1 close（与 rate_stats.rate_1 一致）
        if len(future_data) > d:
            future_close = future_data.iloc[d]['close']
            raw_rate = round((future_close - base_price) / base_price * 100, 2)
            results[d] = round(raw_rate - ROUND_TRIP_COST_PCT, 2)
        else:
            results[d] = None

    return results


def run_backtest_report(strategy_name: str,
                       table_name: str = None,
                       start_date: str = None,
                       end_date: str = None,
                       hold_days: List[int] = None) -> pd.DataFrame:
    """
    生成回测报告

    Args:
        strategy_name: 策略名称
        table_name: 策略表名
        start_date: 开始日期
        end_date: 结束日期
        hold_days: 持仓天数列表

    Returns:
        回测报告DataFrame
    """
    if hold_days is None:
        hold_days = [1, 3, 5, 10, 20, 60]

    # 这里需要从数据库读取数据，具体实现依赖于项目配置
    logging.info(f"生成策略 {strategy_name} 的回测报告")

    # 返回空DataFrame作为占位符
    columns = ['date', 'code', 'name'] + [f'day_{d}' for d in hold_days]
    return pd.DataFrame(columns=columns)
