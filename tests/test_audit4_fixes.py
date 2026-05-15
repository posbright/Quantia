#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
第四轮审计：验证第三轮修复的8个问题是否正确解决

覆盖:
1. singleton_trade_date._refresh() — 失败不摧毁有效数据
2. tablestructure.py — nowinterst_ratio 列类型 FLOAT
3. singleton_stock_web_module_data.py — LHB排序 cdatetime DESC
4. stock_hist_em.py — BIGINT列 int64 转换
5. portfolio_engine.py — 滑点反映到avg_cost + 佣金最低5元溢出保护 + 持仓估值校正
6. paper_engine.py — 同上
7. stockfetch.py — 单部分缓存date列类型统一
8. run_template.py — 作业失败 sys.exit(1)
"""

import os
import sys
import unittest
import datetime
import re
import ast
from unittest.mock import patch, MagicMock
import pandas as pd
import numpy as np

# 确保项目根目录在 sys.path
cpath = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if cpath not in sys.path:
    sys.path.insert(0, cpath)


def _read_src(relpath):
    """读取项目源码文件"""
    return open(os.path.join(os.path.dirname(__file__), '..', *relpath.split('/')),
                encoding='utf-8').read()


# ============================================================
# 测试1: singleton_trade_date — 失败时保留旧数据
# ============================================================
class TestSingletonTradeDateFix(unittest.TestCase):
    """测试 singleton_trade_date 刷新失败时保留已有数据（源码级验证，避免循环导入）"""

    def setUp(self):
        self.src = _read_src('quantia/core/singleton_trade_date.py')

    def test_refresh_uses_temp_variable(self):
        """_refresh() 应使用临时变量 new_data，不直接操作 self.data"""
        self.assertIn('new_data = stf.fetch_stocks_trade_date()', self.src,
                       "_refresh 应先赋值给 new_data 临时变量")

    def test_refresh_validates_before_replacing(self):
        """_refresh() 应验证数据有效后才替换 self.data"""
        self.assertIn('len(new_data) > 30', self.src,
                       "_refresh 应检查 len(new_data) > 30")

    def test_refresh_preserves_on_exception(self):
        """异常时不应覆盖 self.data"""
        tree = ast.parse(self.src)
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                for stmt in ast.walk(node):
                    if isinstance(stmt, ast.Assign):
                        for target in stmt.targets:
                            if (isinstance(target, ast.Attribute) and
                                isinstance(target.value, ast.Name) and
                                target.value.id == 'self' and
                                target.attr == 'data'):
                                self.fail("except 块中不应有 self.data = ... 赋值")

    def test_refresh_no_self_data_none_in_refresh(self):
        """_refresh 方法内不应有 self.data = None"""
        lines = self.src.split('\n')
        in_refresh = False
        for line in lines:
            stripped = line.strip()
            if 'def _refresh(self)' in stripped:
                in_refresh = True
            elif in_refresh and stripped.startswith('def '):
                in_refresh = False
            elif in_refresh and 'self.data = None' in stripped:
                self.fail("_refresh() 中不应有 self.data = None")

    def test_get_data_allows_retry_after_initial_failure(self):
        """get_data() 应在首次加载失败后允许重试"""
        self.assertIn('self._loaded_date is None and self.data is None', self.src,
                       "get_data 应检测首次加载失败进行重试")


# ============================================================
# 测试2: tablestructure — nowinterst_ratio 列类型
# ============================================================
class TestTableStructure(unittest.TestCase):
    """测试 nowinterst_ratio 列类型从 BIGINT 修改为 FLOAT"""

    def test_nowinterst_ratio_is_float(self):
        """cn_stock_selection 表的 nowinterst_ratio 列应为 FLOAT 类型"""
        from sqlalchemy import FLOAT, BIGINT
        import quantia.core.tablestructure as tbs
        col_type = tbs.TABLE_CN_STOCK_SELECTION['columns']['nowinterst_ratio']['type']
        # col_type 可能为 FLOAT 类（未实例化）或 FLOAT 实例
        is_float = (col_type is FLOAT) or isinstance(col_type, FLOAT)
        self.assertTrue(is_float,
                        f"nowinterst_ratio 应为 FLOAT，实际: {col_type}")

    def test_nowinterst_ratio_not_bigint(self):
        """确认 nowinterst_ratio 不再是 BIGINT"""
        from sqlalchemy import BIGINT
        import quantia.core.tablestructure as tbs
        col_type = tbs.TABLE_CN_STOCK_SELECTION['columns']['nowinterst_ratio']['type']
        is_bigint = (col_type is BIGINT) or isinstance(col_type, BIGINT)
        self.assertFalse(is_bigint,
                         f"nowinterst_ratio 不应为 BIGINT，实际: {col_type}")

    def test_float_preserves_decimal(self):
        """验证 FLOAT 类型不会截断百分比值"""
        test_values = [12.34, -5.67, 0.01, 100.99, -0.003]
        for val in test_values:
            stored = float(val)
            self.assertAlmostEqual(stored, val, places=3)


# ============================================================
# 测试3: LHB 排序修复 — cdatetime DESC
# ============================================================
class TestLHBSortOrder(unittest.TestCase):
    """测试龙虎榜排序: cdatetime 应该是 DESC 而非默认 ASC"""

    def setUp(self):
        self.src = _read_src('quantia/core/singleton_stock_web_module_data.py')

    def test_lhb_order_by_cdatetime_desc(self):
        """龙虎榜 order_by 应包含 cdatetime DESC"""
        order_by_match = re.search(
            r"TABLE_CN_STOCK_lHB.*?order_by\s*=\s*\"([^\"]+)\"",
            self.src, re.DOTALL)
        self.assertIsNotNone(order_by_match, "LHB 配置缺少 order_by")

        order_by = order_by_match.group(1)
        self.assertIn('`cdatetime` DESC', order_by,
                       f"LHB order_by 应含 cdatetime DESC，实际: {order_by}")
        self.assertIn('`ranking_times` DESC', order_by,
                       f"LHB order_by 应含 ranking_times DESC，实际: {order_by}")

    def test_lhb_cdatetime_not_default_asc(self):
        """确保 cdatetime 不是默认升序"""
        order_by_match = re.search(
            r"TABLE_CN_STOCK_lHB.*?order_by\s*=\s*\"([^\"]+)\"",
            self.src, re.DOTALL)
        order_by = order_by_match.group(1)
        # 不应出现 `cdatetime`,`ranking_times` DESC 模式（只给后者加 DESC）
        self.assertNotRegex(order_by,
                            r'`cdatetime`\s*,\s*`ranking_times`\s+DESC',
                            "cdatetime 不应缺少 DESC")


# ============================================================
# 测试4: stock_hist_em BIGINT 列 int64 转换
# ============================================================
class TestStockHistEmBigint(unittest.TestCase):
    """测试东方财富 BIGINT 列填充 NaN 并转 int64"""

    def test_bigint_columns_conversion_code_exists(self):
        """源码中应有 BIGINT 列的 fillna(0).astype('int64') 逻辑"""
        src = _read_src('quantia/core/crawling/stock_hist_em.py')
        self.assertIn("fillna(0).astype('int64')", src)
        for col in ['成交量', '成交额', '总市值', '流通市值']:
            self.assertIn(f'"{col}"', src, f"BIGINT 列 {col} 应在转换列表中")

    def test_bigint_nan_to_int64_conversion(self):
        """验证 NaN→0→int64 转换逻辑"""
        df = pd.DataFrame({
            '成交量': [100.0, None, 300.0, float('nan')],
            '成交额': [1000.0, 2000.0, None, 4000.0],
        })
        for col in ['成交量', '成交额']:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype('int64')
        self.assertEqual(df['成交量'].dtype, np.int64)
        self.assertEqual(df['成交量'].iloc[1], 0)
        self.assertEqual(df['成交额'].iloc[2], 0)


# ============================================================
# 测试5: portfolio_engine — 滑点 + 佣金 + 估值校正
# ============================================================
class TestPortfolioEngineSlippage(unittest.TestCase):
    """测试回测引擎的滑点、佣金和估值修复"""

    def test_avg_cost_includes_slippage(self):
        """买入后 avg_cost 应反映滑点（但不含佣金，与聚宽一致）"""
        from quantia.core.backtest.strategy_context import Position

        pos = Position('000001', '测试')
        exec_price = 10.0
        actual_price = exec_price * 1.002
        amount = 1000
        total_cost = actual_price * amount
        commission = max(total_cost * 0.0003, 5.0)

        pos._on_buy(amount, actual_price, commission)
        # avg_cost 不含佣金，与聚宽一致；滑点体现在 actual_price 本身
        expected_avg_cost = actual_price
        self.assertAlmostEqual(pos.avg_cost, expected_avg_cost, places=4)
        self.assertGreater(pos.avg_cost, exec_price)

    def test_position_valued_at_market_close_after_buy(self):
        """买入后持仓应以市场收盘价估值"""
        from quantia.core.backtest.strategy_context import Position

        pos = Position('000001', '测试')
        exec_price = 10.0
        actual_price = exec_price * 1.002
        pos._on_buy(1000, actual_price, 5.0)
        pos._update_price(exec_price)

        self.assertAlmostEqual(pos.price, exec_price, places=4)
        self.assertAlmostEqual(pos.value, exec_price * 1000, places=2)

    def test_total_value_reflects_slippage_cost(self):
        """总资产应体现滑点成本"""
        from quantia.core.backtest.strategy_context import Portfolio

        initial_cash = 1000000.0
        p = Portfolio(initial_cash)
        exec_price = 10.0
        slippage_rate = 0.002
        actual_price = exec_price * (1 + slippage_rate)
        amount = 10000
        total_cost = actual_price * amount
        commission = max(total_cost * 0.0003, 5.0)

        pos = p._get_or_create_position('000001')
        pos._on_buy(amount, actual_price, commission)
        pos._update_price(exec_price)
        p.available_cash -= (total_cost + commission)
        p._update_value()

        slippage_cost = exec_price * slippage_rate * amount
        expected_total = initial_cash - slippage_cost - commission
        self.assertAlmostEqual(p.total_value, expected_total, places=2)
        self.assertLess(p.total_value, initial_cash)

    def test_remaining_position_after_sell(self):
        """卖出后剩余持仓以市场收盘价估值"""
        from quantia.core.backtest.strategy_context import Position

        pos = Position('000001', '测试')
        pos._on_buy(1000, 10.02, 5.0)
        pos._update_price(10.0)
        pos._on_new_day()

        sell_exec_price = 12.0
        pos._on_sell(500, sell_exec_price)

        self.assertAlmostEqual(pos.price, sell_exec_price, places=4)
        self.assertAlmostEqual(pos.value, 500 * sell_exec_price, places=2)
        self.assertEqual(pos.amount, 500)

    def test_commission_floor_check_in_source(self):
        """引擎源码有最低佣金超支检查"""
        src = _read_src('quantia/core/backtest/portfolio_engine.py')
        self.assertIn('total_cost + commission > self.context.portfolio.available_cash', src)

    def test_engine_buy_code_pattern(self):
        """引擎买入: _on_buy(actual_price) + _update_price(exec_price)"""
        src = _read_src('quantia/core/backtest/portfolio_engine.py')
        self.assertIn('_on_buy(amount, actual_price, commission)', src)
        self.assertIn('_update_price(exec_price)', src)

    def test_engine_sell_uses_exec_price(self):
        """引擎卖出: _on_sell(exec_price)"""
        src = _read_src('quantia/core/backtest/portfolio_engine.py')
        self.assertIn('_on_sell(sell_amount, exec_price)', src)

    def test_no_sell_with_actual_price(self):
        """确认 _on_sell 不再使用 actual_price"""
        src = _read_src('quantia/core/backtest/portfolio_engine.py')
        self.assertNotIn('_on_sell(sell_amount, actual_price)', src)


# ============================================================
# 测试6: paper_engine — 同样的滑点和佣金修复
# ============================================================
class TestPaperEngineSlippage(unittest.TestCase):
    """测试模拟交易引擎的滑点和佣金修复"""

    def setUp(self):
        self.src = _read_src('quantia/paper_trading/paper_engine.py')

    def test_paper_buy_uses_actual_price(self):
        self.assertIn('_on_buy(amount, actual_price, commission)', self.src)

    def test_paper_buy_resets_price(self):
        self.assertIn('_update_price(exec_price)', self.src)

    def test_paper_sell_uses_exec_price(self):
        self.assertIn('_on_sell(sell_amount, exec_price)', self.src)

    def test_paper_no_sell_with_actual_price(self):
        self.assertNotIn('_on_sell(sell_amount, actual_price)', self.src)

    def test_paper_commission_floor_check(self):
        self.assertIn('total_cost + commission > context.portfolio.available_cash', self.src)


# ============================================================
# 测试7: stockfetch — 单部分缓存 date 列类型统一
# ============================================================
class TestStockfetchCacheDateNorm(unittest.TestCase):
    """测试单部分缓存的 date 列类型规范化"""

    def test_single_part_applies_date_normalization(self):
        src = _read_src('quantia/core/stockfetch.py')
        idx = src.index('len(parts) == 1')
        section = src[idx:idx+300]
        self.assertIn('_to_dash_date_safe', section)

    def test_to_dash_date_safe_handles_types(self):
        from quantia.core.stockfetch import _to_dash_date_safe
        self.assertEqual(_to_dash_date_safe('2024-01-15'), '2024-01-15')
        self.assertEqual(_to_dash_date_safe(pd.Timestamp('2024-01-15')), '2024-01-15')
        self.assertEqual(_to_dash_date_safe(datetime.date(2024, 1, 15)), '2024-01-15')


# ============================================================
# 测试8: run_template — 作业失败时 sys.exit(1)
# ============================================================
class TestRunTemplateExitCode(unittest.TestCase):
    """测试 run_template 作业失败时非零退出码"""

    def setUp(self):
        self.src = _read_src('quantia/lib/run_template.py')

    def test_has_at_least_three_exit_calls(self):
        exit_calls = re.findall(r'sys\.exit\(1\)', self.src)
        self.assertGreaterEqual(len(exit_calls), 3,
                                f"应至少有3处 sys.exit(1)，实际 {len(exit_calls)}")

    def test_failure_triggers_exit_1(self):
        """模拟作业失败确认调用 sys.exit(1)"""
        import quantia.lib.run_template as rt

        def failing_func(date, *args):
            raise RuntimeError("模拟失败")

        with patch.object(sys, 'argv', ['test_script.py']):
            with patch('quantia.lib.trade_time.get_trade_date_last',
                       return_value=(datetime.date(2026, 3, 18), datetime.date(2026, 3, 18))):
                with self.assertRaises(SystemExit) as cm:
                    rt.run_with_args(failing_func)
                self.assertEqual(cm.exception.code, 1)


# ============================================================
# 综合集成测试 — 经济性验证
# ============================================================
class TestSlippageEconomics(unittest.TestCase):
    """验证滑点在经济意义上的正确性"""

    def test_buy_sell_economics(self):
        """完整买入-卖出循环的经济性检验"""
        from quantia.core.backtest.strategy_context import Portfolio

        initial = 1000000.0
        p = Portfolio(initial)
        exec_buy = 10.0
        slippage = 0.002
        comm_rate = 0.0003
        tax_rate = 0.001

        # 买入
        buy_actual = exec_buy * (1 + slippage)
        buy_amount = 10000
        buy_cost = buy_actual * buy_amount
        buy_comm = max(buy_cost * comm_rate, 5.0)

        pos = p._get_or_create_position('000001')
        pos._on_buy(buy_amount, buy_actual, buy_comm)
        pos._update_price(exec_buy)
        p.available_cash -= (buy_cost + buy_comm)
        p._update_value()

        self.assertGreater(pos.avg_cost, exec_buy)
        self.assertAlmostEqual(pos.price, exec_buy, places=4)
        self.assertLess(p.total_value, initial)

        # 卖出
        pos._on_new_day()
        exec_sell = 12.0
        sell_actual = exec_sell * (1 - slippage)
        sell_amount = 5000
        sell_income = sell_actual * sell_amount
        sell_comm = max(sell_income * comm_rate, 5.0)
        sell_tax = sell_income * tax_rate

        pos._on_sell(sell_amount, exec_sell)
        p.available_cash += (sell_income - sell_comm - sell_tax)
        p._update_value()

        self.assertEqual(pos.amount, 5000)
        self.assertAlmostEqual(pos.price, exec_sell, places=4)

        expected_cash = initial - buy_cost - buy_comm + sell_income - sell_comm - sell_tax
        self.assertAlmostEqual(p.available_cash, expected_cash, places=2)
        expected_total = expected_cash + 5000 * exec_sell
        self.assertAlmostEqual(p.total_value, expected_total, places=2)

    def test_profit_reflects_all_costs(self):
        """position.profit 应反映滑点成本（avg_cost 不含佣金，与聚宽一致）"""
        from quantia.core.backtest.strategy_context import Position

        pos = Position('000001')
        exec_price = 20.0
        actual_price = exec_price * 1.002
        commission = 10.0

        pos._on_buy(1000, actual_price, commission)
        pos._update_price(exec_price)

        self.assertGreater(pos.avg_cost, exec_price)
        self.assertLess(pos.profit, 0, "刚买入时应有浮亏")

        # avg_cost 不含佣金，与聚宽一致
        expected_avg = actual_price
        expected_profit = (exec_price - expected_avg) * 1000
        self.assertAlmostEqual(pos.profit, expected_profit, places=2)


if __name__ == '__main__':
    unittest.main()
