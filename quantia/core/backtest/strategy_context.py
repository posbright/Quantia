#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略上下文对象 — 聚宽风格的 Context / Portfolio / Position

提供与聚宽量化平台兼容的策略编程接口。
"""

import datetime
import logging
from collections import defaultdict

__author__ = 'Quantia'
__date__ = '2026/03/13'


class Position:
    """单只股票的持仓信息"""

    __slots__ = ('code', 'name', 'amount', 'closeable_amount',
                 'avg_cost', 'price', 'value', '_today_bought')

    def __init__(self, code, name=''):
        self.code = code
        self.name = name
        self.amount = 0               # 总持仓股数
        self.closeable_amount = 0     # 可卖出股数（T+1 规则）
        self.avg_cost = 0.0           # 持仓均价
        self.price = 0.0              # 最新市价
        self.value = 0.0              # 持仓市值
        self._today_bought = 0        # 今日买入量（用于 T+1 计算）

    def _update_price(self, price):
        """更新市价和市值"""
        self.price = price
        self.value = self.amount * price

    def _on_buy(self, amount, price, cost=0.0):
        """买入成交更新（avg_cost 不含佣金，与聚宽一致）"""
        total_cost = self.avg_cost * self.amount + price * amount
        self.amount += amount
        self._today_bought += amount
        if self.amount > 0:
            self.avg_cost = total_cost / self.amount
        self._update_price(price)

    def _on_sell(self, amount, price):
        """卖出成交更新"""
        sell_amount = min(amount, self.closeable_amount)
        self.amount -= sell_amount
        self.closeable_amount = max(0, self.closeable_amount - sell_amount)
        if self.amount <= 0:
            self.amount = 0
            self.closeable_amount = 0
            self.avg_cost = 0.0
        self._update_price(price)

    def _on_new_day(self):
        """新交易日：昨日买入的股票今日可卖"""
        self.closeable_amount = self.amount
        self._today_bought = 0

    @property
    def total_amount(self):
        """总持仓股数（聚宽兼容别名）"""
        return self.amount

    @property
    def price_basis(self):
        """持仓成本价（聚宽兼容别名，等同 avg_cost）"""
        return self.avg_cost

    @property
    def hold_cost(self):
        """持仓成本价（聚宽兼容别名，等同 avg_cost）"""
        return self.avg_cost

    @property
    def init_time(self):
        """占位：建仓时间（向后兼容，返回 None）"""
        return None

    @property
    def profit(self):
        """浮动盈亏"""
        if self.amount == 0:
            return 0.0
        return (self.price - self.avg_cost) * self.amount

    @property
    def profit_rate(self):
        """浮动盈亏率"""
        if self.avg_cost == 0 or self.amount == 0:
            return 0.0
        return (self.price - self.avg_cost) / self.avg_cost

    def __repr__(self):
        return (f"Position(code={self.code}, amount={self.amount}, "
                f"cost={self.avg_cost:.3f}, price={self.price:.3f})")


class PositionsDict(dict):
    """持仓字典 — 自动将聚宽风格代码（'000001.XSHE'）映射到纯数字代码"""

    @staticmethod
    def _clean(key):
        if isinstance(key, str) and '.' in key:
            return key.split('.')[0]
        return key

    def __getitem__(self, key):
        return super().__getitem__(self._clean(key))

    def __contains__(self, key):
        return super().__contains__(self._clean(key))

    def get(self, key, default=None):
        return super().get(self._clean(key), default)

    def __delitem__(self, key):
        super().__delitem__(self._clean(key))


class Portfolio:
    """投资组合（账户信息）"""

    def __init__(self, initial_cash=1000000.0):
        self.starting_cash = initial_cash
        self.available_cash = initial_cash    # 可用现金
        self.total_value = initial_cash       # 总资产
        self.market_value = 0.0               # 持仓市值
        self.positions = PositionsDict()      # {code: Position}
        self._frozen_cash = 0.0               # 冻结资金（挂单中）

    @property
    def cash(self):
        """可用现金（兼容聚宽 context.portfolio.cash）"""
        return self.available_cash

    @cash.setter
    def cash(self, value):
        self.available_cash = value

    def _update_value(self):
        """更新组合市值"""
        self.market_value = sum(p.value for p in self.positions.values() if p.amount > 0)
        self.total_value = self.available_cash + self.market_value

    def _get_or_create_position(self, code, name=''):
        """获取或创建持仓"""
        if code not in self.positions:
            self.positions[code] = Position(code, name)
        return self.positions[code]

    def _on_new_day(self, prices):
        """新交易日处理：更新 T+1、价格、清理空仓"""
        # T+1: 昨日买入今日可卖
        for pos in self.positions.values():
            pos._on_new_day()

        # 更新持仓市价
        for code, pos in list(self.positions.items()):
            if code in prices and pos.amount > 0:
                pos._update_price(prices[code])

        # 清理空仓
        empty = [c for c, p in self.positions.items() if p.amount == 0]
        for c in empty:
            del self.positions[c]

        self._update_value()


class GlobalVars:
    """全局变量容器 g — 用于在策略函数间共享变量"""
    pass


class Context:
    """策略运行上下文"""

    def __init__(self, initial_cash=1000000.0):
        self.portfolio = Portfolio(initial_cash)
        self.current_dt = None           # 当前交易日（datetime.date）
        self.previous_dt = None          # 上一交易日
        self.benchmark = '000300'        # 基准指数
        # 交易成本
        self.commission_rate = 0.0003    # 佣金率（双边）
        self.stamp_tax_rate = 0.001      # 印花税（卖方）
        self.slippage_rate = 0.002       # 滑点率
        # 引擎内部引用（策略代码不直接使用）
        self._engine = None

    def __repr__(self):
        return (f"Context(dt={self.current_dt}, "
                f"cash={self.portfolio.available_cash:.2f}, "
                f"value={self.portfolio.total_value:.2f})")


class DataProxy:
    """
    数据代理 — 提供 data[code].close 风格的访问

    在每个交易日，engine 会更新 _current_bar 和 _history_data
    """

    def __init__(self):
        self._current_bars = {}      # {code: {open,high,low,close,volume}}
        self._history_cache = {}     # {code: DataFrame}  完整K线

    def __getitem__(self, code):
        """data[code] → StockData 对象（支持聚宽 .XSHE/.XSHG 后缀）"""
        clean = code.split('.')[0] if isinstance(code, str) and '.' in code else code
        return StockData(clean, self)

    def __contains__(self, code):
        clean = code.split('.')[0] if isinstance(code, str) and '.' in code else code
        return clean in self._current_bars

    # 聚宽兼容：data 在策略中常被当作 dict 使用 (data.keys()/iter/len/get)。
    def keys(self):
        return list(self._current_bars.keys())

    def __iter__(self):
        return iter(self._current_bars.keys())

    def __len__(self):
        return len(self._current_bars)

    def get(self, code, default=None):
        clean = code.split('.')[0] if isinstance(code, str) and '.' in code else code
        if clean in self._current_bars:
            return StockData(clean, self)
        return default

    def _set_current(self, code, bar_dict):
        """设置当日行情"""
        self._current_bars[code] = bar_dict

    def _set_history(self, code, df):
        """设置完整 K 线历史"""
        self._history_cache[code] = df


class StockData:
    """单只股票的数据访问代理"""

    def __init__(self, code, proxy):
        self._code = code
        self._proxy = proxy

    @property
    def close(self):
        bar = self._proxy._current_bars.get(self._code)
        return bar['close'] if bar else 0.0

    @property
    def open(self):
        bar = self._proxy._current_bars.get(self._code)
        return bar['open'] if bar else 0.0

    @property
    def high(self):
        bar = self._proxy._current_bars.get(self._code)
        return bar['high'] if bar else 0.0

    @property
    def low(self):
        bar = self._proxy._current_bars.get(self._code)
        return bar['low'] if bar else 0.0

    @property
    def volume(self):
        bar = self._proxy._current_bars.get(self._code)
        return bar['volume'] if bar else 0

    @property
    def high_limit(self):
        """涨停价"""
        bar = self._proxy._current_bars.get(self._code)
        if bar and 'pre_close' in bar:
            return round(bar['pre_close'] * 1.1, 2)
        return self.close * 1.1

    @property
    def low_limit(self):
        """跌停价"""
        bar = self._proxy._current_bars.get(self._code)
        if bar and 'pre_close' in bar:
            return round(bar['pre_close'] * 0.9, 2)
        return self.close * 0.9


class TradeRecord:
    """交易记录"""
    __slots__ = ('date', 'code', 'name', 'direction', 'price',
                 'amount', 'value', 'commission', 'tax', 'slippage_cost',
                 'close_profit', 'return_rate', 'reason', 'reason_source')

    def __init__(self, date, code, name, direction, price, amount):
        self.date = date
        self.code = code
        self.name = name
        self.direction = direction  # 'buy' or 'sell'
        self.price = price
        self.amount = amount
        self.value = price * amount
        self.commission = 0.0
        self.tax = 0.0
        self.slippage_cost = 0.0
        self.close_profit = 0.0    # 平仓盈亏（卖出时有效）
        self.return_rate = 0.0     # 收益率 %（卖出时有效）
        # Phase 3 扩展：策略真实理由（or 系统兜底说明），随 to_dict 写入 result_json，
        # 让回测详情前端 (backtest-detail.vue tradeReason()) 不改动即可读取。
        self.reason = ''
        self.reason_source = ''  # 'strategy' / 'generated' / ''

    @property
    def total_cost(self):
        return self.commission + self.tax + self.slippage_cost

    def to_dict(self):
        return {
            'date': self.date.strftime('%Y-%m-%d') if hasattr(self.date, 'strftime') else str(self.date),
            'code': self.code,
            'name': self.name,
            'direction': self.direction,
            'price': self.price,
            'amount': self.amount,
            'value': self.value,
            'commission': self.commission,
            'tax': self.tax,
            'slippage_cost': self.slippage_cost,
            'close_profit': round(self.close_profit, 2),
            'return_rate': round(self.return_rate, 2),
            'reason': getattr(self, 'reason', '') or '',
            'reason_source': getattr(self, 'reason_source', '') or '',
        }


class NavRecord:
    """每日净值记录"""
    __slots__ = ('date', 'nav', 'benchmark_nav', 'cash',
                 'market_value', 'total_value', 'daily_return', 'benchmark_return')

    def __init__(self, date, nav, benchmark_nav=1.0, cash=0, market_value=0,
                 total_value=0, daily_return=0, benchmark_return=0):
        self.date = date
        self.nav = nav
        self.benchmark_nav = benchmark_nav
        self.cash = cash
        self.market_value = market_value
        self.total_value = total_value
        self.daily_return = daily_return
        self.benchmark_return = benchmark_return

    def to_dict(self):
        return {
            'date': self.date.strftime('%Y-%m-%d') if hasattr(self.date, 'strftime') else str(self.date),
            'nav': round(self.nav, 6),
            'benchmark_nav': round(self.benchmark_nav, 6),
            'cash': round(self.cash, 2),
            'market_value': round(self.market_value, 2),
            'total_value': round(self.total_value, 2),
            'daily_return': round(self.daily_return, 6),
            'benchmark_return': round(self.benchmark_return, 6),
        }
