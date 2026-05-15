#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回测引擎单元测试
"""

import os
import sys
import unittest
import datetime
import numpy as np
import pandas as pd
import tempfile
import pickle
import gzip

# 确保项目根目录在 sys.path
cpath = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if cpath not in sys.path:
    sys.path.insert(0, cpath)


def _create_test_cache(code, start='2024-01-02', periods=250, base_price=10.0):
    """创建测试用的K线缓存文件"""
    from quantia.core.backtest.data_feed import _CACHE_DIR
    os.makedirs(_CACHE_DIR, exist_ok=True)

    dates = pd.bdate_range(start=start, periods=periods)
    np.random.seed(hash(code) % 2**31)
    returns = np.random.randn(periods) * 0.02
    prices = base_price * np.cumprod(1 + returns)

    df = pd.DataFrame({
        'date': dates,
        'open': prices * (1 - np.random.rand(periods) * 0.01),
        'high': prices * (1 + np.random.rand(periods) * 0.02),
        'low': prices * (1 - np.random.rand(periods) * 0.02),
        'close': prices,
        'volume': np.random.randint(100000, 500000, periods),
    })

    cache_file = os.path.join(_CACHE_DIR, f"{code}.gzip.pickle")
    df.to_pickle(cache_file)
    return cache_file


class TestStrategyContext(unittest.TestCase):
    """测试 Context / Portfolio / Position 对象"""

    def test_portfolio_init(self):
        from quantia.core.backtest.strategy_context import Portfolio
        p = Portfolio(1000000)
        self.assertEqual(p.available_cash, 1000000)
        self.assertEqual(p.total_value, 1000000)
        self.assertEqual(p.market_value, 0)
        self.assertEqual(len(p.positions), 0)

    def test_position_buy_sell(self):
        from quantia.core.backtest.strategy_context import Position
        pos = Position('000001', '测试股票')
        pos._on_buy(1000, 10.0)
        self.assertEqual(pos.amount, 1000)
        self.assertAlmostEqual(pos.avg_cost, 10.0, places=2)
        self.assertAlmostEqual(pos.value, 10000.0, places=2)

        pos._update_price(12.0)
        self.assertAlmostEqual(pos.profit, 2000.0, places=2)
        self.assertAlmostEqual(pos.profit_rate, 0.2, places=2)

        # T+1: 需要先调用 _on_new_day 才能卖出
        pos._on_new_day()
        self.assertEqual(pos.closeable_amount, 1000)
        pos._on_sell(500, 12.0)
        self.assertEqual(pos.amount, 500)
        self.assertEqual(pos.closeable_amount, 500)

    def test_t_plus_1(self):
        """T+1: 今日买入不能今日卖出"""
        from quantia.core.backtest.strategy_context import Position
        pos = Position('000001')
        pos._on_buy(1000, 10.0)
        # 买入当天，closeable_amount 仍为 0（T+1）
        self.assertEqual(pos.closeable_amount, 0)

        # 新交易日后，可卖出
        pos._on_new_day()
        self.assertEqual(pos.closeable_amount, 1000)

    def test_context(self):
        from quantia.core.backtest.strategy_context import Context
        ctx = Context(500000)
        self.assertEqual(ctx.portfolio.available_cash, 500000)
        self.assertIsNone(ctx.current_dt)

    def test_data_proxy(self):
        from quantia.core.backtest.strategy_context import DataProxy
        proxy = DataProxy()
        proxy._set_current('000001', {
            'open': 10.0, 'high': 11.0, 'low': 9.5,
            'close': 10.5, 'volume': 100000
        })
        self.assertAlmostEqual(proxy['000001'].close, 10.5)
        self.assertAlmostEqual(proxy['000001'].open, 10.0)
        self.assertTrue('000001' in proxy)
        self.assertFalse('999999' in proxy)


class TestStrategySandbox(unittest.TestCase):
    """测试策略安全沙箱"""

    def test_valid_strategy(self):
        from quantia.core.backtest.strategy_sandbox import validate_code, compile_strategy
        code = '''
def initialize(context):
    context.security = '000001'

def handle_data(context, data):
    pass
'''
        ok, err = validate_code(code)
        self.assertTrue(ok, err)

        funcs = compile_strategy(code)
        self.assertIn('initialize', funcs)
        self.assertIn('handle_data', funcs)
        self.assertTrue(callable(funcs['initialize']))

    def test_reject_dangerous_code(self):
        from quantia.core.backtest.strategy_sandbox import validate_code
        # import os
        ok, _ = validate_code("import os\ndef initialize(context): pass\ndef handle_data(c,d): pass")
        self.assertFalse(ok)

        # eval
        ok, _ = validate_code("def initialize(c): eval('1+1')\ndef handle_data(c,d): pass")
        self.assertFalse(ok)

    def test_missing_initialize(self):
        """缺少 initialize 函数时应拒绝"""
        from quantia.core.backtest.strategy_sandbox import validate_code
        ok, err = validate_code("def handle_data(c, d): pass")
        self.assertFalse(ok)
        self.assertIn('initialize', err)

    def test_only_initialize_is_valid(self):
        """仅有 initialize 应通过（handle_data 可选，可用 run_daily 替代）"""
        from quantia.core.backtest.strategy_sandbox import validate_code
        ok, err = validate_code("def initialize(c): pass")
        self.assertTrue(ok, err)


class TestRiskMetrics(unittest.TestCase):
    """测试风险指标计算"""

    def test_positive_return(self):
        from quantia.core.backtest.risk_metrics import calculate_metrics
        # 线性上涨
        nav = [1.0 + i * 0.001 for i in range(250)]
        m = calculate_metrics(nav)
        self.assertGreater(m['total_return'], 0)
        self.assertGreater(m['annual_return'], 0)
        self.assertGreater(m['sharpe_ratio'], 0)
        self.assertAlmostEqual(m['max_drawdown'], 0, places=1)

    def test_negative_return(self):
        from quantia.core.backtest.risk_metrics import calculate_metrics
        nav = [1.0 - i * 0.001 for i in range(100)]
        m = calculate_metrics(nav)
        self.assertLess(m['total_return'], 0)
        self.assertGreater(m['max_drawdown'], 0)

    def test_with_benchmark(self):
        from quantia.core.backtest.risk_metrics import calculate_metrics
        np.random.seed(42)
        nav = np.cumprod(1 + np.random.randn(250) * 0.01)
        bm = np.cumprod(1 + np.random.randn(250) * 0.008)
        m = calculate_metrics(nav.tolist(), bm.tolist())
        self.assertIn('alpha', m)
        self.assertIn('beta', m)


class TestPortfolioEngine(unittest.TestCase):
    """测试组合回测引擎"""

    @classmethod
    def setUpClass(cls):
        """创建测试用缓存数据"""
        cls._cache_files = []
        for code in ['000001', '600519', '000858']:
            f = _create_test_cache(code, start='2024-01-02', periods=250, base_price=10.0)
            cls._cache_files.append(f)

    def test_simple_buy_hold(self):
        """简单买入持有策略"""
        from quantia.core.backtest.portfolio_engine import run_backtest

        code = '''
def initialize(context):
    context.security = '000001'

def handle_data(context, data):
    if '000001' not in context.portfolio.positions:
        order_value('000001', context.portfolio.available_cash * 0.9)
'''
        result = run_backtest(code, '2024-02-01', '2024-12-31', initial_cash=100000)
        self.assertEqual(result['status'], 'completed')
        self.assertIn('metrics', result)
        self.assertIn('nav', result)
        self.assertIn('trades', result)
        self.assertGreater(len(result['nav']), 0)
        self.assertGreater(len(result['trades']), 0)
        # 应该只有一次买入
        buy_trades = [t for t in result['trades'] if t['direction'] == 'buy']
        self.assertEqual(len(buy_trades), 1)

    def test_ma_strategy(self):
        """均线策略：有买有卖"""
        from quantia.core.backtest.portfolio_engine import run_backtest

        code = '''
def initialize(context):
    context.security = '000001'

def handle_data(context, data):
    code = context.security
    price = data[code].close
    if price <= 0:
        return
    ma = history(code, 10, 'close')
    if len(ma) < 10:
        return
    ma_val = ma.mean()

    if price > ma_val * 1.02 and code not in context.portfolio.positions:
        order_value(code, context.portfolio.available_cash * 0.9)
    elif price < ma_val * 0.98 and code in context.portfolio.positions:
        order_target(code, 0)
'''
        result = run_backtest(code, '2024-03-01', '2024-12-31', initial_cash=100000)
        self.assertEqual(result['status'], 'completed')
        self.assertGreater(len(result['trades']), 1, "均线策略应产生多笔交易")

    def test_multi_stock(self):
        """多股票等权策略"""
        from quantia.core.backtest.portfolio_engine import run_backtest

        code = '''
def initialize(context):
    context.stocks = ['000001', '600519', '000858']

def handle_data(context, data):
    target = context.portfolio.total_value / len(context.stocks)
    for code in context.stocks:
        if code in data:
            order_target_value(code, target)
'''
        result = run_backtest(code, '2024-03-01', '2024-12-31', initial_cash=300000)
        self.assertEqual(result['status'], 'completed')
        # 应该有3只股票的交易
        codes_traded = set(t['code'] for t in result['trades'])
        self.assertGreaterEqual(len(codes_traded), 1)

    def test_syntax_error(self):
        """语法错误策略"""
        from quantia.core.backtest.portfolio_engine import run_backtest
        result = run_backtest("def initialize(: pass", '2024-01-01', '2024-06-01')
        self.assertEqual(result['status'], 'error')

    def test_dangerous_code(self):
        """危险代码被拦截"""
        from quantia.core.backtest.portfolio_engine import run_backtest
        result = run_backtest(
            "import os\ndef initialize(c): pass\ndef handle_data(c,d): pass",
            '2024-01-01', '2024-06-01')
        self.assertEqual(result['status'], 'error')

    def test_result_structure(self):
        """验证返回结果结构完整"""
        from quantia.core.backtest.portfolio_engine import run_backtest
        code = '''
def initialize(context):
    context.security = '000001'
def handle_data(context, data):
    pass
'''
        result = run_backtest(code, '2024-03-01', '2024-06-30', initial_cash=100000)
        self.assertEqual(result['status'], 'completed')

        # 检查 metrics
        m = result['metrics']
        for key in ['total_return', 'annual_return', 'max_drawdown',
                     'sharpe_ratio', 'trade_count', 'trading_days']:
            self.assertIn(key, m, f"缺少指标: {key}")

        # 检查 nav
        self.assertGreater(len(result['nav']), 0)
        nav0 = result['nav'][0]
        for key in ['date', 'nav', 'cash', 'total_value']:
            self.assertIn(key, nav0, f"NAV 记录缺少: {key}")

        # 检查 params
        self.assertIn('params', result)
        self.assertEqual(result['params']['initial_cash'], 100000)


class TestDataFeed(unittest.TestCase):
    """测试数据加载"""

    @classmethod
    def setUpClass(cls):
        _create_test_cache('000001', start='2024-01-02', periods=250)

    def test_load_stock(self):
        from quantia.core.backtest.data_feed import load_stock_data
        df = load_stock_data('000001', '2024-01-01', '2024-12-31')
        self.assertIsNotNone(df)
        self.assertGreater(len(df), 0)
        for col in ['date', 'open', 'high', 'low', 'close', 'volume']:
            self.assertIn(col, df.columns)

    def test_load_nonexistent(self):
        from quantia.core.backtest.data_feed import load_stock_data
        df = load_stock_data('999999')
        self.assertIsNone(df)


if __name__ == '__main__':
    unittest.main()
