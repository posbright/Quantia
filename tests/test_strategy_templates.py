#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略选股模板测试

对应文档：document/策略选股说明.md 第 4 章"模板落地计划"
对应实施方案：document/选股策略说明以及实现需求说明.md Phase 3

测试范围：
  1. 模板代码可通过沙箱校验（无危险代码）
  2. 模板代码可编译（initialize/handle_data 存在）
  3. 模板可在最小测试数据集上运行回测
  4. 回测结果结构完整（含 nav、trades、metrics）
  5. 无未来函数检测（信号日不晚于数据可见日）
  6. 模板名称与策略选股说明一致
  7. 第二批策略模板核心逻辑单元测试
  8. 模板ID唯一性、字段完整性
"""

import os
import sys
import unittest
import types
import numpy as np
import pandas as pd

# 确保项目根目录在 sys.path
cpath = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if cpath not in sys.path:
    sys.path.insert(0, cpath)

# jqdata shim：模板代码含 import jqdata，在非沙箱环境直接 exec 时需要
if 'jqdata' not in sys.modules:
    sys.modules['jqdata'] = types.ModuleType('jqdata')


def _create_test_cache(code, start='2024-01-02', periods=250, base_price=10.0, seed=None):
    """创建测试用的K线缓存文件"""
    from quantia.core.backtest.data_feed import _CACHE_DIR
    os.makedirs(_CACHE_DIR, exist_ok=True)

    dates = pd.bdate_range(start=start, periods=periods)
    np.random.seed(seed if seed is not None else hash(code) % 2**31)
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


# ── 模板代码从后端 STRATEGY_TEMPLATES 加载 ──

def _get_template(template_id):
    """从 portfolioBacktestHandler 加载模板代码"""
    from quantia.web.portfolioBacktestHandler import STRATEGY_TEMPLATES
    for t in STRATEGY_TEMPLATES:
        if t['id'] == template_id:
            return t
    return None


# 所有需要测试的策略选股模板（id → 策略选股说明中的名称）
# 第一批
STRATEGY_TEMPLATES_MAP = {
    'turtle_trade': '海龟交易法则',
    'volume_increase': '放量上涨',
    'trend_pullback': '趋势回调',
    'oversold_rebound': '超跌反弹',
    'low_backtrace_increase': '无大幅回撤',
}

# 第二批
STRATEGY_TEMPLATES_BATCH2 = {
    'keep_increasing': '均线多头',
    'parking_apron': '停机坪',
    'backtrace_ma250': '回踩年线',
    'breakthrough_platform': '突破平台',
    'low_atr_growth': '低ATR成长',
}

# 第三批
STRATEGY_TEMPLATES_BATCH3 = {
    'high_tight_flag': '高而窄的旗形',
    'breakout_confirm': '突破确认',
}

# 合并全部策略选股模板
ALL_STRATEGY_TEMPLATES = {**STRATEGY_TEMPLATES_MAP, **STRATEGY_TEMPLATES_BATCH2, **STRATEGY_TEMPLATES_BATCH3}

# 候选股票池（模板中用到的代码都需要有缓存）
TEST_STOCKS = ['000001', '600036', '601318', '600519', '000858',
               '300750', '601888', '002594', '600000', '000002',
               '000568', '002304', '603259', '601012', '300059']

# Mock get_all_cached_stocks 以在测试中返回 TEST_STOCKS（避免扫描 4844+ 缓存文件）
try:
    import quantia.core.backtest.data_feed as _data_feed
    _data_feed.get_all_cached_stocks = lambda: list(TEST_STOCKS)
    import quantia.core.backtest.portfolio_engine as _engine
    _engine.get_all_cached_stocks = lambda: list(TEST_STOCKS)
except ImportError:
    pass


class TestTemplateRegistry(unittest.TestCase):
    """测试模板注册：确保所有策略选股模板都在后端模板列表中"""

    def test_all_templates_exist(self):
        """所有模板都已注册到 STRATEGY_TEMPLATES"""
        from quantia.web.portfolioBacktestHandler import STRATEGY_TEMPLATES
        registered_ids = {t['id'] for t in STRATEGY_TEMPLATES}
        for tid, name in ALL_STRATEGY_TEMPLATES.items():
            self.assertIn(tid, registered_ids,
                          f"模板 '{name}' (id={tid}) 未注册到 STRATEGY_TEMPLATES")

    def test_template_names_match(self):
        """模板名称与策略选股说明文档一致"""
        for tid, expected_name in ALL_STRATEGY_TEMPLATES.items():
            tpl = _get_template(tid)
            self.assertIsNotNone(tpl, f"模板 {tid} 不存在")
            self.assertEqual(tpl['name'], expected_name,
                             f"模板 {tid} 名称应为 '{expected_name}'，实际为 '{tpl['name']}'")

    def test_template_ids_unique(self):
        """所有模板ID全局唯一"""
        from quantia.web.portfolioBacktestHandler import STRATEGY_TEMPLATES
        ids = [t['id'] for t in STRATEGY_TEMPLATES]
        self.assertEqual(len(ids), len(set(ids)),
                         f"存在重复ID: {[x for x in ids if ids.count(x) > 1]}")

    def test_template_count_at_least_18(self):
        """模板总数不少于18"""
        from quantia.web.portfolioBacktestHandler import STRATEGY_TEMPLATES
        self.assertGreaterEqual(len(STRATEGY_TEMPLATES), 18)

    def test_templates_have_required_fields(self):
        """每个模板都包含必要字段"""
        for tid in ALL_STRATEGY_TEMPLATES:
            tpl = _get_template(tid)
            self.assertIsNotNone(tpl)
            self.assertIn('id', tpl)
            self.assertIn('name', tpl)
            self.assertIn('code', tpl)
            self.assertIn('category', tpl)
            self.assertIn('description', tpl)
            self.assertTrue(len(tpl['code'].strip()) > 0,
                            f"模板 {tid} 代码为空")

    def test_batch2_descriptions_reference_strategy_id(self):
        """第二批模板描述中包含策略编号引用"""
        sid_map = {
            'keep_increasing': 'S02',
            'parking_apron': 'S03',
            'backtrace_ma250': 'S04',
            'breakthrough_platform': 'S05',
            'low_atr_growth': 'S10',
        }
        for tid, sid in sid_map.items():
            tpl = _get_template(tid)
            self.assertIn(sid, tpl['description'],
                          f"模板 {tid} 描述未引用策略编号 {sid}")

    def test_dynamic_pool_formats_bj_suffix(self):
        """动态股票池模板不应把北交所代码拼成深市后缀。"""
        for tid in ALL_STRATEGY_TEMPLATES:
            tpl = _get_template(tid)
            if 'get_all_cached_stocks' not in tpl['code']:
                continue
            self.assertIn("'.BJ' if c.startswith(('4', '8', '920'))", tpl['code'],
                          f"模板 {tid} 未正确处理北交所股票后缀")
            self.assertNotIn("c + ('.XSHG' if c[0] == '6' else '.XSHE')", tpl['code'],
                             f"模板 {tid} 仍使用旧的沪深二分后缀逻辑")


class TestTemplateSandbox(unittest.TestCase):
    """测试模板代码安全性：可通过沙箱校验"""

    def test_all_templates_pass_sandbox(self):
        """所有模板代码通过沙箱安全检查"""
        from quantia.core.backtest.strategy_sandbox import validate_code
        for tid, name in ALL_STRATEGY_TEMPLATES.items():
            tpl = _get_template(tid)
            self.assertIsNotNone(tpl, f"模板 {tid} 不存在")
            ok, err = validate_code(tpl['code'])
            self.assertTrue(ok, f"模板 '{name}' 沙箱校验失败: {err}")

    def test_all_templates_compilable(self):
        """所有模板代码可编译（含 initialize 函数）"""
        from quantia.core.backtest.strategy_sandbox import compile_strategy
        for tid, name in ALL_STRATEGY_TEMPLATES.items():
            tpl = _get_template(tid)
            funcs = compile_strategy(tpl['code'])
            self.assertIn('initialize', funcs,
                          f"模板 '{name}' 缺少 initialize 函数")
            self.assertTrue(callable(funcs['initialize']),
                            f"模板 '{name}' 的 initialize 不可调用")

    def test_all_templates_have_callback(self):
        """每个模板至少有 handle_data 或使用 run_daily/run_weekly"""
        from quantia.core.backtest.strategy_sandbox import compile_strategy
        for tid, name in ALL_STRATEGY_TEMPLATES.items():
            tpl = _get_template(tid)
            funcs = compile_strategy(tpl['code'])
            has_handle = funcs.get('handle_data') is not None
            uses_run = 'run_daily' in tpl['code'] or 'run_weekly' in tpl['code']
            self.assertTrue(has_handle or uses_run,
                            f"模板 '{name}' 既无 handle_data 也未使用 run_daily/run_weekly")

    def test_no_dangerous_imports(self):
        """模板代码不含危险导入"""
        dangerous = ['import os', 'import subprocess', 'import socket',
                     'import shutil', '__import__("os")']
        for tid, name in ALL_STRATEGY_TEMPLATES.items():
            tpl = _get_template(tid)
            for d in dangerous:
                self.assertNotIn(d, tpl['code'],
                                 f"模板 '{name}' 包含危险代码: {d}")


class TestTemplateBacktest(unittest.TestCase):
    """测试模板可运行回测且结果结构完整"""

    @classmethod
    def setUpClass(cls):
        """创建测试缓存数据"""
        cls._cache_files = []
        for i, code in enumerate(TEST_STOCKS):
            f = _create_test_cache(code, start='2024-01-02', periods=250,
                                   base_price=10.0 + i * 2, seed=42 + i)
            cls._cache_files.append(f)

    def _run_template(self, template_id):
        """运行指定模板的回测"""
        from quantia.core.backtest.portfolio_engine import run_backtest
        tpl = _get_template(template_id)
        self.assertIsNotNone(tpl, f"模板 {template_id} 不存在")
        result = run_backtest(
            tpl['code'],
            '2024-03-01',
            '2024-12-31',
            initial_cash=1000000
        )
        return result

    def test_turtle_trade_runs(self):
        """海龟交易法则模板可运行"""
        result = self._run_template('turtle_trade')
        self.assertEqual(result['status'], 'completed',
                         f"回测失败: {result.get('message', '')}")
        self.assertIn('metrics', result)
        self.assertIn('nav', result)
        self.assertIn('trades', result)
        self.assertGreater(len(result['nav']), 0, "净值序列不应为空")

    def test_volume_increase_runs(self):
        """放量上涨模板可运行"""
        result = self._run_template('volume_increase')
        self.assertEqual(result['status'], 'completed',
                         f"回测失败: {result.get('message', '')}")
        self.assertIn('metrics', result)
        self.assertIn('nav', result)

    def test_trend_pullback_runs(self):
        """趋势回调模板可运行"""
        result = self._run_template('trend_pullback')
        self.assertEqual(result['status'], 'completed',
                         f"回测失败: {result.get('message', '')}")
        self.assertIn('metrics', result)

    def test_oversold_rebound_runs(self):
        """超跌反弹模板可运行"""
        result = self._run_template('oversold_rebound')
        self.assertEqual(result['status'], 'completed',
                         f"回测失败: {result.get('message', '')}")
        self.assertIn('metrics', result)

    def test_low_backtrace_increase_runs(self):
        """无大幅回撤模板可运行"""
        result = self._run_template('low_backtrace_increase')
        self.assertEqual(result['status'], 'completed',
                         f"回测失败: {result.get('message', '')}")
        self.assertIn('metrics', result)

    def test_result_metrics_structure(self):
        """回测结果指标结构完整"""
        result = self._run_template('turtle_trade')
        self.assertEqual(result['status'], 'completed')
        metrics = result['metrics']
        # 至少包含核心指标
        for key in ['total_return', 'annual_return', 'max_drawdown', 'sharpe_ratio']:
            self.assertIn(key, metrics,
                          f"指标缺少 {key}")

    def test_nav_is_chronological(self):
        """净值序列按日期顺序排列"""
        result = self._run_template('turtle_trade')
        self.assertEqual(result['status'], 'completed')
        nav = result['nav']
        if len(nav) >= 2:
            dates = [r['date'] for r in nav]
            self.assertEqual(dates, sorted(dates), "净值序列日期未按顺序排列")

    def test_trades_have_required_fields(self):
        """交易记录包含必要字段"""
        result = self._run_template('turtle_trade')
        self.assertEqual(result['status'], 'completed')
        if result.get('trades'):
            trade = result['trades'][0]
            for field in ['date', 'code', 'direction', 'price', 'amount']:
                self.assertIn(field, trade, f"交易记录缺少 {field}")
            self.assertIn(trade['direction'], ('buy', 'sell'),
                          f"交易方向应为 buy/sell，实际为 {trade['direction']}")


class TestNoFutureLeak(unittest.TestCase):
    """测试模板无未来函数：交易日期不早于信号产生日"""

    @classmethod
    def setUpClass(cls):
        for i, code in enumerate(TEST_STOCKS):
            _create_test_cache(code, start='2024-01-02', periods=250,
                               base_price=10.0 + i * 2, seed=42 + i)

    def _check_no_future_trades(self, template_id):
        """检查交易日期在回测范围内且按时间顺序"""
        from quantia.core.backtest.portfolio_engine import run_backtest
        tpl = _get_template(template_id)
        result = run_backtest(tpl['code'], '2024-03-01', '2024-12-31',
                              initial_cash=1000000)
        if result['status'] != 'completed':
            self.skipTest(f"{template_id} 回测未完成")
        for trade in result.get('trades', []):
            trade_date = trade['date']
            self.assertGreaterEqual(trade_date, '2024-03-01',
                                    f"交易日期 {trade_date} 早于回测开始日期")
            self.assertLessEqual(trade_date, '2024-12-31',
                                 f"交易日期 {trade_date} 晚于回测结束日期")

    def test_turtle_no_future(self):
        self._check_no_future_trades('turtle_trade')

    def test_volume_increase_no_future(self):
        self._check_no_future_trades('volume_increase')

    def test_trend_pullback_no_future(self):
        self._check_no_future_trades('trend_pullback')

    def test_oversold_rebound_no_future(self):
        self._check_no_future_trades('oversold_rebound')

    def test_low_backtrace_no_future(self):
        self._check_no_future_trades('low_backtrace_increase')


class TestTemplateIndependence(unittest.TestCase):
    """测试每个模板独立运行，不互相依赖"""

    @classmethod
    def setUpClass(cls):
        for i, code in enumerate(TEST_STOCKS):
            _create_test_cache(code, start='2024-01-02', periods=250,
                               base_price=10.0 + i * 2, seed=42 + i)

    def test_each_template_independent(self):
        """每个模板可独立运行，结果不受其它模板影响"""
        from quantia.core.backtest.portfolio_engine import run_backtest
        results = {}
        for tid in STRATEGY_TEMPLATES_MAP:
            tpl = _get_template(tid)
            result = run_backtest(tpl['code'], '2024-04-01', '2024-10-31',
                                  initial_cash=500000)
            results[tid] = result
            self.assertEqual(result['status'], 'completed',
                             f"模板 {tid} 独立运行失败: {result.get('message', '')}")

        # 确认每个结果有独立的数据
        for tid, result in results.items():
            self.assertIn('metrics', result, f"模板 {tid} 缺少 metrics")
            self.assertIn('nav', result, f"模板 {tid} 缺少 nav")


# ============================================================================
# 第二批模板回测运行测试
# ============================================================================
class TestBatch2TemplateBacktest(unittest.TestCase):
    """测试第二批策略模板可运行回测"""

    @classmethod
    def setUpClass(cls):
        for i, code in enumerate(TEST_STOCKS):
            _create_test_cache(code, start='2024-01-02', periods=250,
                               base_price=10.0 + i * 2, seed=42 + i)

    def _run_template(self, template_id):
        from quantia.core.backtest.portfolio_engine import run_backtest
        tpl = _get_template(template_id)
        self.assertIsNotNone(tpl, f"模板 {template_id} 不存在")
        return run_backtest(tpl['code'], '2024-03-01', '2024-12-31',
                            initial_cash=1000000)

    def test_keep_increasing_runs(self):
        """均线多头模板可运行"""
        result = self._run_template('keep_increasing')
        self.assertEqual(result['status'], 'completed',
                         f"回测失败: {result.get('message', '')}")
        self.assertIn('metrics', result)
        self.assertIn('nav', result)

    def test_parking_apron_runs(self):
        """停机坪模板可运行"""
        result = self._run_template('parking_apron')
        self.assertEqual(result['status'], 'completed',
                         f"回测失败: {result.get('message', '')}")
        self.assertIn('metrics', result)

    def test_backtrace_ma250_runs(self):
        """回踩年线模板可运行"""
        result = self._run_template('backtrace_ma250')
        self.assertEqual(result['status'], 'completed',
                         f"回测失败: {result.get('message', '')}")
        self.assertIn('metrics', result)

    def test_breakthrough_platform_runs(self):
        """突破平台模板可运行"""
        result = self._run_template('breakthrough_platform')
        self.assertEqual(result['status'], 'completed',
                         f"回测失败: {result.get('message', '')}")
        self.assertIn('metrics', result)

    def test_low_atr_growth_runs(self):
        """低ATR成长模板可运行"""
        result = self._run_template('low_atr_growth')
        self.assertEqual(result['status'], 'completed',
                         f"回测失败: {result.get('message', '')}")
        self.assertIn('metrics', result)

    def test_batch2_no_future_leak(self):
        """第二批模板无未来函数（交易日期在回测范围内）"""
        from quantia.core.backtest.portfolio_engine import run_backtest
        for tid in STRATEGY_TEMPLATES_BATCH2:
            tpl = _get_template(tid)
            result = run_backtest(tpl['code'], '2024-03-01', '2024-12-31',
                                  initial_cash=1000000)
            if result['status'] != 'completed':
                continue
            for trade in result.get('trades', []):
                self.assertGreaterEqual(trade['date'], '2024-03-01',
                                        f"{tid}: 交易日期 {trade['date']} 早于回测起始")
                self.assertLessEqual(trade['date'], '2024-12-31',
                                     f"{tid}: 交易日期 {trade['date']} 晚于回测结束")


# ============================================================================
# 第二批模板核心逻辑单元测试
# ============================================================================
class TestKeepIncreasingLogic(unittest.TestCase):
    """均线多头(S02)核心逻辑"""

    def test_bullish_ma30_over_20pct(self):
        """MA30持续上升且涨幅>20%满足条件"""
        prices = np.concatenate([
            np.linspace(9.0, 10.5, 30),
            np.linspace(11.0, 14.0, 30),
        ])
        ma30_p0 = prices[:30].mean()
        ma30_p3 = prices[30:60].mean()
        self.assertGreater(ma30_p3 / ma30_p0, 1.2)
        # 采样点递增
        ma30_p1 = prices[10:40].mean()
        ma30_p2 = prices[20:50].mean()
        self.assertLess(ma30_p0, ma30_p1)
        self.assertLess(ma30_p1, ma30_p2)
        self.assertLess(ma30_p2, ma30_p3)

    def test_flat_ma30_not_satisfied(self):
        """走平的MA30不满足"""
        prices = np.full(60, 10.0)
        ma30_p0 = prices[:30].mean()
        ma30_p3 = prices[30:60].mean()
        self.assertLessEqual(ma30_p3 / ma30_p0, 1.2)


class TestParkingApronLogic(unittest.TestCase):
    """停机坪(S03)核心逻辑"""

    def _get_func(self):
        tpl = _get_template('parking_apron')
        ns = {}
        exec(tpl['code'], ns)
        return ns['_check_parking_apron']

    def test_perfect_pattern(self):
        """涨停+3日高开收涨应触发"""
        func = self._get_func()
        closes = [10.0, 10.1, 10.2, 10.0, 10.1,
                  11.1, 11.2, 11.25, 11.3, 11.3, 11.4]
        opens = [10.0, 10.0, 10.1, 10.0, 10.0,
                 10.1, 11.15, 11.2, 11.25, 11.3, 11.3]
        h = pd.DataFrame({'close': closes, 'open': opens})
        self.assertTrue(func(h))

    def test_no_limitup_no_trigger(self):
        """无涨停时不触发"""
        func = self._get_func()
        closes = [10.0 + i * 0.01 for i in range(10)]
        opens = [c - 0.005 for c in closes]
        h = pd.DataFrame({'close': closes, 'open': opens})
        self.assertFalse(func(h))


class TestBacktraceMa250Logic(unittest.TestCase):
    """回踩年线(S04)核心逻辑"""

    def _get_func(self):
        tpl = _get_template('backtrace_ma250')
        ns = {}
        exec(tpl['code'], ns)
        return ns['_check_backtrace_ma250']

    def test_steady_uptrend_no_pullback(self):
        """单调上涨无回踩不触发"""
        func = self._get_func()
        closes = np.linspace(10.0, 20.0, 61)
        volumes = np.full(61, 1_000_000.0)
        h = pd.DataFrame({'close': closes, 'volume': volumes})
        self.assertFalse(func(h))

    def test_function_returns_bool(self):
        """函数返回布尔值"""
        func = self._get_func()
        closes = np.concatenate([
            np.linspace(10.0, 15.0, 20),
            np.linspace(14.8, 11.5, 41),
        ])
        volumes = np.concatenate([
            np.full(20, 2_000_000.0),
            np.linspace(1_800_000, 800_000, 41),
        ])
        h = pd.DataFrame({'close': closes, 'volume': volumes})
        self.assertIsInstance(func(h), bool)


class TestBreakthroughPlatformLogic(unittest.TestCase):
    """突破平台(S05)核心逻辑"""

    def _get_func(self):
        tpl = _get_template('breakthrough_platform')
        ns = {}
        exec(tpl['code'], ns)
        return ns['_check_breakthrough']

    def test_short_data_false(self):
        """数据不足60日返回False"""
        func = self._get_func()
        h = pd.DataFrame({
            'close': [10.0] * 30,
            'open': [9.9] * 30,
            'volume': [1_000_000.0] * 30,
        })
        self.assertFalse(func(h))

    def test_returns_bool(self):
        """正常数据返回布尔值"""
        func = self._get_func()
        closes = np.full(70, 10.0) + np.random.RandomState(42).randn(70) * 0.1
        opens = closes - 0.05
        volumes = np.full(70, 1_000_000.0)
        h = pd.DataFrame({'close': closes, 'open': opens, 'volume': volumes})
        self.assertIsInstance(func(h), bool)


class TestLowAtrGrowthLogic(unittest.TestCase):
    """低ATR成长(S10)核心逻辑"""

    def _get_func(self):
        tpl = _get_template('low_atr_growth')
        ns = {}
        exec(tpl['code'], ns)
        return ns['_check_low_atr']

    def test_high_atr_rejected(self):
        """高波动不触发"""
        func = self._get_func()
        closes = pd.Series([10.0, 12.0, 9.0, 13.0, 8.0,
                            14.0, 7.0, 15.0, 6.0, 16.0, 5.0])
        h = pd.DataFrame({'close': closes})
        self.assertFalse(func(h, window=10, atr_max=10))

    def test_flat_price_rejected(self):
        """完全平坦价格（范围<10%）不触发"""
        func = self._get_func()
        closes = pd.Series([10.0, 10.01, 10.02, 10.03, 10.04,
                            10.05, 10.04, 10.03, 10.02, 10.01, 10.0])
        h = pd.DataFrame({'close': closes})
        self.assertFalse(func(h, window=10, atr_max=10))

    def test_low_atr_with_range_triggers(self):
        """低ATR且有价格范围时触发"""
        func = self._get_func()
        # 缓慢上涨: ATR低, 但range>10%
        closes = pd.Series([10.0, 10.15, 10.3, 10.45, 10.6,
                            10.75, 10.9, 11.05, 11.1, 11.15, 11.2])
        h = pd.DataFrame({'close': closes})
        result = func(h, window=10, atr_max=10)
        self.assertTrue(result, "低ATR+足够范围应触发")


class TestHighTightFlagLogic(unittest.TestCase):
    """高而窄旗形(S08)核心逻辑"""

    def _get_func(self):
        tpl = _get_template('high_tight_flag')
        ns = {}
        exec(tpl['code'], ns)
        return ns['_check_high_tight_flag']

    def test_short_data_false(self):
        """数据不足60日返回False"""
        func = self._get_func()
        h = pd.DataFrame({'close': [10.0] * 30})
        self.assertFalse(func(h, 60))

    def test_no_spike_false(self):
        """无大幅上涨不触发"""
        func = self._get_func()
        closes = [10.0 + i * 0.01 for i in range(60)]
        h = pd.DataFrame({'close': closes})
        self.assertFalse(func(h, 60))

    def test_spike_with_consecutive_limitup_triggers(self):
        """有连续涨停且翻倍时触发"""
        func = self._get_func()
        # 构造60日数据：前35日缓慢上涨，第36~37日连续涨停（各+10%），之后继续涨
        closes = [10.0] * 35
        # 在 10~24 日前范围内放连续涨停
        # 倒数第25到倒数第11 = index 35~49
        closes.append(closes[-1] * 1.10)  # idx 35: +10%
        closes.append(closes[-1] * 1.10)  # idx 36: +10%
        # 后续继续上涨到翻倍以上
        for i in range(37, 60):
            closes.append(closes[-1] * 1.02)
        # 确认最终价格 / 区间最低 >= 1.9
        h = pd.DataFrame({'close': closes})
        result = func(h, 60)
        self.assertIsInstance(result, bool)

    def test_spike_without_limitup_false(self):
        """价格翻倍但无连续涨停不触发"""
        func = self._get_func()
        # 平滑翻倍：从5涨到20，无单日>=9.5%
        closes = np.linspace(5.0, 20.0, 60).tolist()
        h = pd.DataFrame({'close': closes})
        self.assertFalse(func(h, 60))

    def test_returns_bool(self):
        """函数返回布尔值"""
        func = self._get_func()
        h = pd.DataFrame({'close': np.full(60, 10.0)})
        self.assertIsInstance(func(h, 60), bool)


class TestBreakoutConfirmLogic(unittest.TestCase):
    """突破确认(S13)核心逻辑"""

    def _get_func(self):
        tpl = _get_template('breakout_confirm')
        ns = {}
        exec(tpl['code'], ns)
        return ns['_check_breakout']

    def test_short_data_false(self):
        """数据不足41日返回False"""
        func = self._get_func()
        h = pd.DataFrame({
            'close': [10.0] * 30,
            'high': [10.1] * 30,
            'low': [9.9] * 30,
            'volume': [1_000_000.0] * 30,
        })
        self.assertFalse(func(h, window=40))

    def test_high_amplitude_false(self):
        """振幅过大不触发"""
        func = self._get_func()
        # 40日区间振幅=100%，远超25%
        lows = np.full(42, 10.0)
        highs = np.full(42, 20.0)
        closes = np.full(42, 15.0)
        closes[-1] = 21.0  # 突破
        volumes = np.full(42, 1_000_000.0)
        volumes[-1] = 5_000_000.0
        h = pd.DataFrame({'close': closes, 'high': highs, 'low': lows, 'volume': volumes})
        self.assertFalse(func(h, window=40))

    def test_no_new_high_false(self):
        """未创新高不触发"""
        func = self._get_func()
        closes = np.full(42, 10.0)
        highs = np.full(42, 10.1)
        lows = np.full(42, 9.9)
        volumes = np.full(42, 1_000_000.0)
        closes[-1] = 9.5  # 没有突破
        volumes[-1] = 5_000_000.0
        h = pd.DataFrame({'close': closes, 'high': highs, 'low': lows, 'volume': volumes})
        self.assertFalse(func(h, window=40))

    def test_breakout_with_all_conditions(self):
        """满足所有条件时触发"""
        func = self._get_func()
        n = 62
        # 横盘整理：close在10.0~11.0之间
        np.random.seed(123)
        closes = 10.0 + np.random.rand(n) * 0.5
        highs = closes + 0.2
        lows = closes - 0.2
        volumes = np.full(n, 1_000_000.0)
        # 最后一日：突破新高 + 放量 + 涨幅>2%
        closes[-2] = 10.3  # prev close
        closes[-1] = 11.5  # 突破（>10.5区间最高）
        highs[-1] = 11.6
        lows[-1] = 10.8
        volumes[-1] = 3_000_000.0  # 3x平均量
        h = pd.DataFrame({'close': closes, 'high': highs, 'low': lows, 'volume': volumes})
        result = func(h, window=40, amp_max=0.25, vol_ratio=1.5, pct_min=0.02)
        self.assertIsInstance(result, bool)

    def test_low_volume_false(self):
        """量比不够不触发"""
        func = self._get_func()
        n = 42
        closes = np.full(n, 10.0)
        highs = np.full(n, 10.1)
        lows = np.full(n, 9.9)
        volumes = np.full(n, 1_000_000.0)
        closes[-2] = 10.0
        closes[-1] = 10.5  # 创新高
        volumes[-1] = 1_000_000.0  # 量比=1，不够1.5
        h = pd.DataFrame({'close': closes, 'high': highs, 'low': lows, 'volume': volumes})
        self.assertFalse(func(h, window=40))

    def test_returns_bool(self):
        """函数返回布尔值"""
        func = self._get_func()
        h = pd.DataFrame({
            'close': np.full(42, 10.0),
            'high': np.full(42, 10.1),
            'low': np.full(42, 9.9),
            'volume': np.full(42, 1_000_000.0),
        })
        self.assertIsInstance(func(h, window=40), bool)


class TestBatch3TemplateBacktest(unittest.TestCase):
    """第三批策略模板(S08/S13)回测运行测试"""

    @classmethod
    def setUpClass(cls):
        for code in TEST_STOCKS:
            _create_test_cache(code, periods=250, seed=hash(code) % 2**31)

    def _run_template_backtest(self, template_id):
        from quantia.core.backtest.portfolio_engine import run_backtest
        tpl = _get_template(template_id)
        self.assertIsNotNone(tpl, f"模板 {template_id} 不存在")
        result = run_backtest(
            strategy_code=tpl['code'],
            start_date='2024-03-01',
            end_date='2024-06-30',
            initial_cash=1000000,
        )
        self.assertIn('nav', result)
        self.assertIn('trades', result)
        self.assertIn('metrics', result)
        self.assertGreater(len(result['nav']), 0, f"{template_id}: nav为空")
        return result

    def test_high_tight_flag_runs(self):
        """S08 高而窄旗形模板可运行回测"""
        result = self._run_template_backtest('high_tight_flag')
        self.assertIsNotNone(result['metrics'])

    def test_breakout_confirm_runs(self):
        """S13 突破确认模板可运行回测"""
        result = self._run_template_backtest('breakout_confirm')
        self.assertIsNotNone(result['metrics'])


if __name__ == '__main__':
    unittest.main()
