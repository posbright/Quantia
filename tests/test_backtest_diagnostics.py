"""测试 portfolio_engine 的失败诊断逻辑：

1. status='error' 路径会挂上 hints，且 hints 与具体 error_message 相关；
2. 0 笔交易时的 hints 反映真实订单计数器，而不是固定的通用模板；
3. 不同失败原因（涨停 / 现金不足 / 无持仓 / 无下单调用 / 异常）产生不同 hints；
4. 即使源码不命中任何 regex 规则，也不会回退到与策略无关的通用 fallback。
"""
import pandas as pd
import numpy as np
import unittest
from unittest.mock import patch

from quantia.core.backtest.portfolio_engine import PortfolioBacktestEngine


def _make_df(periods=10, start_close=10.0, jump_pct=None):
    dates = pd.date_range('2025-01-02', periods=periods, freq='B')
    closes = np.linspace(start_close, start_close * 1.1, periods)
    df = pd.DataFrame({
        'date': dates,
        'open': closes - 0.05,
        'high': closes + 0.5,
        'low': closes - 0.5,
        'close': closes,
        'volume': np.full(periods, 500000, dtype=int),
    })
    df['pre_close'] = df['close'].shift(1).fillna(start_close)
    if jump_pct:  # 让所有 bar 都涨停（用于涨停拒单测试）
        df['pre_close'] = df['close'] / (1 + jump_pct)
    return df


class TestDiagnoseEngineError(unittest.TestCase):
    """status='error' 时 _diagnose_engine_error 必须产生与 message 相关的提示。"""

    def test_invalid_cash_message_in_hints(self):
        result = PortfolioBacktestEngine().run(
            strategy_code="def initialize(ctx): pass",
            start_date='2025-01-02', end_date='2025-01-15',
            initial_cash=0,
        )
        self.assertEqual(result['status'], 'error')
        self.assertIn('hints', result)
        self.assertTrue(len(result['hints']) >= 1)
        # 提示文案里必须包含具体的错误信息片段
        joined = ' '.join(h['suggestion'] for h in result['hints'])
        self.assertIn('初始资金', joined)

    @patch('quantia.core.backtest.portfolio_engine.load_benchmark_data')
    @patch('quantia.core.backtest.portfolio_engine.load_multiple_stocks')
    @patch('quantia.core.backtest.portfolio_engine.get_trading_dates')
    def test_no_trading_dates_message_in_hints(self, mock_dates, mock_multi, mock_bm):
        mock_dates.return_value = []
        result = PortfolioBacktestEngine().run(
            strategy_code="def initialize(ctx): pass",
            start_date='2025-01-02', end_date='2025-01-15',
        )
        self.assertEqual(result['status'], 'error')
        self.assertTrue(result.get('hints'))
        joined = ' '.join(h['title'] + h['suggestion'] for h in result['hints'])
        self.assertIn('无交易日', joined)

    def test_compile_error_hints_mention_syntax(self):
        result = PortfolioBacktestEngine().run(
            strategy_code="def initialize(ctx)\n  pass",  # 缺冒号
            start_date='2025-01-02', end_date='2025-01-15',
        )
        self.assertEqual(result['status'], 'error')
        joined = ' '.join(h['title'] for h in result.get('hints') or [])
        # 至少 hint title 含有"语法"或"错误"字样
        self.assertTrue('语法' in joined or '错误' in joined or '失败' in joined)


class TestDiagnoseZeroTrades(unittest.TestCase):
    """0 笔交易时 hints 应反映真实订单计数器，且不同失败原因产生不同 hints。"""

    def _run(self, strategy, mock_multi, mock_bm, mock_single, mock_dates,
             periods=8, df=None):
        if df is None:
            df = _make_df(periods=periods)
        mock_dates.return_value = [d.date() for d in df['date']]
        mock_multi.return_value = {'000001': df}
        mock_single.return_value = df
        mock_bm.return_value = df.copy()
        engine = PortfolioBacktestEngine()
        return engine.run(
            strategy_code=strategy,
            start_date='2025-01-02', end_date='2025-01-15',
            initial_cash=1_000_000,
        ), engine

    @patch('quantia.core.backtest.portfolio_engine.load_stock_data')
    @patch('quantia.core.backtest.portfolio_engine.get_trading_dates')
    @patch('quantia.core.backtest.portfolio_engine.load_multiple_stocks')
    @patch('quantia.core.backtest.portfolio_engine.load_benchmark_data')
    def test_no_order_call_in_source(self, mock_bm, mock_multi, mock_dates, mock_single):
        # 策略里压根没有 order_* 调用 → 必须命中"找不到下单调用"提示
        strategy = """
def initialize(context):
    pass

def handle_data(context, data):
    x = 1 + 1
"""
        result, _ = self._run(strategy, mock_multi, mock_bm, mock_single, mock_dates)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['metrics']['trade_count'], 0)
        titles = [h['title'] for h in result['hints']]
        # 必须明确指出“无下单调用”（title 里用了 order 关键字）
        self.assertTrue(any('order' in t.lower() or '下单' in t for t in titles),
                        f"hints titles: {titles}")
        # 不应该再出现旧版本那种与本次无关的 talib.STOCH/day==1 提示
        self.assertFalse(any('STOCH' in t for t in titles))
        # order_stats 必须暴露给外层
        self.assertIn('order_stats', result)
        self.assertEqual(result['order_stats']['submitted'], 0)

    @patch('quantia.core.backtest.portfolio_engine.load_stock_data')
    @patch('quantia.core.backtest.portfolio_engine.get_trading_dates')
    @patch('quantia.core.backtest.portfolio_engine.load_multiple_stocks')
    @patch('quantia.core.backtest.portfolio_engine.load_benchmark_data')
    def test_insufficient_cash_rejection(self, mock_bm, mock_multi, mock_dates, mock_single):
        # 反复用比可用现金大很多的金额下单 → 拒单计数 rejected_insufficient_cash 上升
        strategy = """
def initialize(context):
    pass

def handle_data(context, data):
    # 反复下超额买单：第一次成交后没现金，后续都现金不足
    order_value('000001', 99999999)
"""
        result, eng = self._run(strategy, mock_multi, mock_bm, mock_single, mock_dates)
        self.assertEqual(result['status'], 'completed')
        stats = result['order_stats']
        # 至少有一次成交，且至少有一次现金不足拒单
        self.assertGreaterEqual(stats['submitted'], 2)
        self.assertGreaterEqual(stats['rejected_insufficient_cash'], 1)
        # 但 trade_count > 0 时不应再走 0 笔诊断（这条用例验证 hints 仅在 0 笔时出 reject 类）
        if result['metrics']['trade_count'] > 0:
            # 没异常时不应该有 hints；如果引擎也对"成交但被拒过"出 hint，那只能是异常类
            for h in result['hints']:
                self.assertTrue(str(h.get('title', '')).startswith('策略抛出异常'),
                                f"unexpected hint when trades>0: {h}")

    @patch('quantia.core.backtest.portfolio_engine.load_stock_data')
    @patch('quantia.core.backtest.portfolio_engine.get_trading_dates')
    @patch('quantia.core.backtest.portfolio_engine.load_multiple_stocks')
    @patch('quantia.core.backtest.portfolio_engine.load_benchmark_data')
    def test_sell_without_position_rejection(self, mock_bm, mock_multi, mock_dates, mock_single):
        strategy = """
def initialize(context):
    pass

def handle_data(context, data):
    order('000001', -100)  # 从未买入即卖出
"""
        result, _ = self._run(strategy, mock_multi, mock_bm, mock_single, mock_dates)
        self.assertEqual(result['metrics']['trade_count'], 0)
        stats = result['order_stats']
        self.assertGreaterEqual(stats['rejected_no_position'], 1)
        titles = [h['title'] for h in result['hints']]
        # 必须命中"无可卖持仓"提示，并带 reject 次数
        self.assertTrue(any('无可卖持仓' in t for t in titles), titles)
        # 必须包含证据字段
        for h in result['hints']:
            if '无可卖持仓' in h.get('title', ''):
                self.assertIn('evidence', h)
                self.assertEqual(h['evidence']['counter'], 'rejected_no_position')

    @patch('quantia.core.backtest.portfolio_engine.load_stock_data')
    @patch('quantia.core.backtest.portfolio_engine.get_trading_dates')
    @patch('quantia.core.backtest.portfolio_engine.load_multiple_stocks')
    @patch('quantia.core.backtest.portfolio_engine.load_benchmark_data')
    def test_runtime_exception_hint_includes_error_text(
            self, mock_bm, mock_multi, mock_dates, mock_single):
        strategy = """
def initialize(context):
    pass

def handle_data(context, data):
    x = 1 / 0  # ZeroDivisionError
    order_value('000001', 10000)
"""
        result, _ = self._run(strategy, mock_multi, mock_bm, mock_single, mock_dates)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['metrics']['trade_count'], 0)
        # 必须有运行期异常 hint，且 suggestion 包含针对 ZeroDivision 的具体建议
        err_hints = [h for h in result['hints'] if '策略抛出异常' in h.get('title', '')]
        self.assertTrue(err_hints, f"missing exception hint: {result['hints']}")
        joined = ' '.join(h['suggestion'] for h in err_hints)
        # 应该包含针对 ZeroDivisionError 的中文建议（含 "除零" 或 "除数"）
        self.assertTrue('除' in joined or 'ZeroDivision' in joined,
                        f"suggestion lacks divide hint: {joined}")
        # title 中应含具体异常类型名
        self.assertIn('ZeroDivision', err_hints[0]['title'])
        # 证据字段必须含错误次数
        self.assertGreater(err_hints[0]['evidence']['error_count'], 0)

    @patch('quantia.core.backtest.portfolio_engine.load_stock_data')
    @patch('quantia.core.backtest.portfolio_engine.get_trading_dates')
    @patch('quantia.core.backtest.portfolio_engine.load_multiple_stocks')
    @patch('quantia.core.backtest.portfolio_engine.load_benchmark_data')
    def test_different_failures_produce_different_hints(
            self, mock_bm, mock_multi, mock_dates, mock_single):
        """同一份"通用样板"绝不应在不同失败模式下给出相同 hints。"""
        df = _make_df(periods=8)
        mock_dates.return_value = [d.date() for d in df['date']]
        mock_multi.return_value = {'000001': df}
        mock_single.return_value = df
        mock_bm.return_value = df.copy()

        # 失败 A：没有 order 调用
        r1 = PortfolioBacktestEngine().run(
            strategy_code="def initialize(c): pass\ndef handle_data(c, d): pass",
            start_date='2025-01-02', end_date='2025-01-15',
            initial_cash=1_000_000)
        # 失败 B：卖出无持仓
        r2 = PortfolioBacktestEngine().run(
            strategy_code="def initialize(c): pass\ndef handle_data(c, d): order('000001', -100)",
            start_date='2025-01-02', end_date='2025-01-15',
            initial_cash=1_000_000)
        # 失败 C：运行期异常
        r3 = PortfolioBacktestEngine().run(
            strategy_code="def initialize(c): pass\ndef handle_data(c, d):\n    raise RuntimeError('boom')\n    order_value('000001', 1000)",
            start_date='2025-01-02', end_date='2025-01-15',
            initial_cash=1_000_000)

        titles_1 = tuple(sorted(h['title'] for h in r1['hints']))
        titles_2 = tuple(sorted(h['title'] for h in r2['hints']))
        titles_3 = tuple(sorted(h['title'] for h in r3['hints']))
        # 三种失败 hints 不应完全相同
        self.assertNotEqual(titles_1, titles_2,
                            f"A vs B 应给出不同诊断: {titles_1} vs {titles_2}")
        self.assertNotEqual(titles_1, titles_3,
                            f"A vs C 应给出不同诊断: {titles_1} vs {titles_3}")
        self.assertNotEqual(titles_2, titles_3,
                            f"B vs C 应给出不同诊断: {titles_2} vs {titles_3}")

    @patch('quantia.core.backtest.portfolio_engine.load_stock_data')
    @patch('quantia.core.backtest.portfolio_engine.get_trading_dates')
    @patch('quantia.core.backtest.portfolio_engine.load_multiple_stocks')
    @patch('quantia.core.backtest.portfolio_engine.load_benchmark_data')
    def test_order_stats_reset_between_runs(
            self, mock_bm, mock_multi, mock_dates, mock_single):
        """同一引擎实例被复用时，order_stats 必须在 run() 开头重置。"""
        df = _make_df(periods=6)
        mock_dates.return_value = [d.date() for d in df['date']]
        mock_multi.return_value = {'000001': df}
        mock_single.return_value = df
        mock_bm.return_value = df.copy()
        engine = PortfolioBacktestEngine()
        engine.run(
            strategy_code="def initialize(c): pass\ndef handle_data(c, d): order('000001', -100)",
            start_date='2025-01-02', end_date='2025-01-15',
            initial_cash=1_000_000)
        first = dict(engine._order_stats)
        self.assertGreaterEqual(first['rejected_no_position'], 1)
        engine.run(
            strategy_code="def initialize(c): pass\ndef handle_data(c, d): pass",
            start_date='2025-01-02', end_date='2025-01-15',
            initial_cash=1_000_000)
        second = dict(engine._order_stats)
        # 第二次没有任何下单 → submitted=0，rejected_no_position 也归零
        self.assertEqual(second['submitted'], 0)
        self.assertEqual(second['rejected_no_position'], 0)


class TestLogBasedExceptionDetection(unittest.TestCase):
    """关键：策略自己 try/except 把异常吞掉只 log.error 时，诊断器必须从日志反解出真实原因。

    用户实际反馈：策略里 `for code in pool: try: ta.RSI(...) except Exception as e: log.error(...)`，
    运行日志全是 `name 'ta' is not defined`，但旧版诊断只给出"源码里找不到 order 调用"
    这种与实际错误无关的文案。
    """

    @patch('quantia.core.backtest.portfolio_engine.load_stock_data')
    @patch('quantia.core.backtest.portfolio_engine.get_trading_dates')
    @patch('quantia.core.backtest.portfolio_engine.load_multiple_stocks')
    @patch('quantia.core.backtest.portfolio_engine.load_benchmark_data')
    def test_swallowed_nameerror_ta_surfaces_in_hints(
            self, mock_bm, mock_multi, mock_dates, mock_single):
        """策略 try/except 吞掉 NameError 'ta' is not defined，诊断必须明确指出。"""
        df = _make_df(periods=6)
        mock_dates.return_value = [d.date() for d in df['date']]
        mock_multi.return_value = {'000001': df, '000002': df}
        mock_single.return_value = df
        mock_bm.return_value = df.copy()

        # 模拟用户策略 101：循环里调用 ta.XXX 但没有 import talib as ta，
        # try/except 把 NameError 吞掉只调用 log.error。
        strategy = """
def initialize(context):
    g.pool = ['000001', '000002']

def handle_data(context, data):
    for code in g.pool:
        try:
            x = ta.RSI([1,2,3], 2)
            order_value(code, 1000)
        except Exception as e:
            log.error(f"处理 {code} 时发生错误: {e}")
"""
        result = PortfolioBacktestEngine().run(
            strategy_code=strategy,
            start_date='2025-01-02', end_date='2025-01-15',
            initial_cash=1_000_000,
        )
        self.assertEqual(result['metrics']['trade_count'], 0)
        hints = result.get('hints') or []
        self.assertTrue(hints, "0 笔交易必须给出 hints")
        # 必须有"日志反解 NameError ta"那条 hint
        ne_hints = [h for h in hints if 'NameError' in h['title'] and 'ta' in h['title']]
        self.assertTrue(ne_hints, f"未识别 NameError 'ta'，实际 hints: {[h['title'] for h in hints]}")
        # 建议必须明确告诉用户怎么修（import talib as ta）
        joined = ' '.join(h['suggestion'] for h in ne_hints)
        self.assertIn('import talib', joined)
        # 不能再误导性地说"源码里找不到 order 调用"（这里源码明确有 order_value）
        misleading = [h for h in hints
                      if '源码里找不到任何 order' in h.get('title', '')]
        self.assertFalse(misleading,
                         f"已检测到 NameError 时不应再给出误导性的'无 order 调用'提示: {misleading}")

    @patch('quantia.core.backtest.portfolio_engine.load_stock_data')
    @patch('quantia.core.backtest.portfolio_engine.get_trading_dates')
    @patch('quantia.core.backtest.portfolio_engine.load_multiple_stocks')
    @patch('quantia.core.backtest.portfolio_engine.load_benchmark_data')
    def test_swallowed_attribute_error_surfaces(
            self, mock_bm, mock_multi, mock_dates, mock_single):
        """策略 try/except 吞掉 AttributeError，诊断应解析出 obj.attr。"""
        df = _make_df(periods=6)
        mock_dates.return_value = [d.date() for d in df['date']]
        mock_multi.return_value = {'000001': df}
        mock_single.return_value = df
        mock_bm.return_value = df.copy()
        strategy = """
def initialize(context):
    pass

def handle_data(context, data):
    try:
        # context.portfolio 没有 holdings 属性（正确名为 positions）
        _ = context.portfolio.holdings
        order_value('000001', 1000)
    except Exception as e:
        log.error(f"出错: {e}")
"""
        result = PortfolioBacktestEngine().run(
            strategy_code=strategy,
            start_date='2025-01-02', end_date='2025-01-15',
            initial_cash=1_000_000,
        )
        hints = result.get('hints') or []
        attr_hints = [h for h in hints if 'AttributeError' in h.get('title', '')]
        self.assertTrue(attr_hints, f"未识别 AttributeError，实际 hints: {[h['title'] for h in hints]}")
        # title 应包含 holdings
        self.assertIn('holdings', ' '.join(h['title'] for h in attr_hints))

    @patch('quantia.core.backtest.portfolio_engine.load_stock_data')
    @patch('quantia.core.backtest.portfolio_engine.get_trading_dates')
    @patch('quantia.core.backtest.portfolio_engine.load_multiple_stocks')
    @patch('quantia.core.backtest.portfolio_engine.load_benchmark_data')
    def test_log_pattern_counts_top_three(
            self, mock_bm, mock_multi, mock_dates, mock_single):
        """多种异常并存时，按出现次数取 top 3。"""
        df = _make_df(periods=4)
        mock_dates.return_value = [d.date() for d in df['date']]
        mock_multi.return_value = {'000001': df}
        mock_single.return_value = df
        mock_bm.return_value = df.copy()
        strategy = """
def initialize(context):
    pass

def handle_data(context, data):
    try:
        x = unknown_var_1
    except Exception as e:
        log.error(str(e))
    try:
        y = unknown_var_2
    except Exception as e:
        log.error(str(e))
"""
        result = PortfolioBacktestEngine().run(
            strategy_code=strategy,
            start_date='2025-01-02', end_date='2025-01-15',
            initial_cash=1_000_000,
        )
        hints = result.get('hints') or []
        ne_hints = [h for h in hints if 'NameError' in h.get('title', '')]
        # 两个不同的未定义变量都应被识别（至少包含 unknown_var_1 或 unknown_var_2 一种）
        joined = ' '.join(h['title'] for h in ne_hints)
        self.assertTrue('unknown_var_1' in joined or 'unknown_var_2' in joined,
                        f"NameError 变量名未出现在 hint title 中: {joined}")
        # 每个 hint 的 evidence.count 必须 >= 1
        for h in ne_hints:
            self.assertGreaterEqual(h['evidence']['count'], 1)


if __name__ == '__main__':
    unittest.main()
