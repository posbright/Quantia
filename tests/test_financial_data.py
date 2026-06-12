#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
财务数据采集与回测集成测试模块

测试范围：
1. stock_financial_data.py — 数据采集、字段映射、upsert 逻辑
2. fundamentals.py — 真实财务数据加载与回退合成数据逻辑
3. tablestructure.py — 新表定义完整性
4. init_job.py — 建表 DDL 兼容性
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock
from datetime import date, datetime

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


class TestTableStructureFinancial(unittest.TestCase):
    """验证 cn_stock_financial 表定义的完整性和正确性"""

    def setUp(self):
        from quantia.core import tablestructure as tbs
        self.tbs = tbs

    def test_table_exists_in_module(self):
        """TABLE_CN_STOCK_FINANCIAL 应存在且包含必要属性"""
        table = self.tbs.TABLE_CN_STOCK_FINANCIAL
        self.assertIn('name', table)
        self.assertIn('columns', table)
        self.assertIn('cn', table)

    def test_table_name(self):
        """表名应为 cn_stock_financial"""
        self.assertEqual(self.tbs.TABLE_CN_STOCK_FINANCIAL['name'], 'cn_stock_financial')

    def test_required_columns_exist(self):
        """表应包含回测所需的所有关键财务字段"""
        cols = self.tbs.TABLE_CN_STOCK_FINANCIAL['columns']
        required = [
            'code', 'report_date', 'eps', 'bps', 'ocfps',
            'revenue', 'net_profit', 'revenue_yoy', 'net_profit_yoy',
            'roe', 'roa', 'gross_margin', 'net_profit_margin',
            'asset_liability_ratio', 'current_ratio', 'quick_ratio',
        ]
        for col in required:
            self.assertIn(col, cols, f"缺少必要列: {col}")

    def test_column_types(self):
        """关键字段的类型应正确"""
        from sqlalchemy import FLOAT, VARCHAR, DATE
        cols = self.tbs.TABLE_CN_STOCK_FINANCIAL['columns']
        self.assertIsInstance(cols['code']['type'], VARCHAR)
        # tablestructure 中存储的是类本身（非实例），检查 is 或 issubclass
        self.assertTrue(cols['report_date']['type'] is DATE or
                        issubclass(cols['report_date']['type'], DATE))
        self.assertTrue(cols['roe']['type'] is FLOAT or
                        issubclass(cols['roe']['type'], FLOAT))


class TestStockFinancialDataModule(unittest.TestCase):
    """验证 stock_financial_data.py 的核心函数逻辑"""

    def test_code_to_secucode(self):
        """股票代码到东方财富格式的转换"""
        from quantia.job.stock_financial_data import _code_to_secucode
        self.assertEqual(_code_to_secucode('000001'), '000001.SZ')
        self.assertEqual(_code_to_secucode('600000'), '600000.SH')
        self.assertEqual(_code_to_secucode('300001'), '300001.SZ')
        self.assertEqual(_code_to_secucode('688001'), '688001.SH')
        self.assertEqual(_code_to_secucode('830001'), '830001.BJ')

    def test_clean_nan(self):
        """NaN 应被替换为 None"""
        from quantia.job.stock_financial_data import _clean_nan
        rows = [
            {'a': 1.0, 'b': float('nan'), 'c': 'text'},
            {'a': float('nan'), 'b': 2.0, 'c': None},
        ]
        cleaned = _clean_nan(rows)
        self.assertIsNone(cleaned[0]['b'])
        self.assertIsNone(cleaned[1]['a'])
        self.assertEqual(cleaned[0]['a'], 1.0)
        self.assertEqual(cleaned[1]['b'], 2.0)
        self.assertEqual(cleaned[0]['c'], 'text')
        self.assertIsNone(cleaned[1]['c'])

    def test_em_col_map_completeness(self):
        """东方财富字段映射应包含所有必要字段"""
        from quantia.job.stock_financial_data import _EM_COL_MAP
        required_targets = [
            'revenue_yoy', 'net_profit_yoy', 'roe', 'roa',
            'asset_liability_ratio', 'eps', 'bps', 'ocfps',
        ]
        mapped_values = set(_EM_COL_MAP.values())
        for target in required_targets:
            self.assertIn(target, mapped_values, f"映射缺少目标字段: {target}")

    def test_db_fields_match_col_map(self):
        """DB 字段列表应覆盖所有映射目标字段"""
        from quantia.job.stock_financial_data import _EM_COL_MAP, _DB_FIELDS
        db_set = set(_DB_FIELDS)
        for target in _EM_COL_MAP.values():
            self.assertIn(target, db_set, f"_DB_FIELDS 缺少字段: {target}")

    def test_retry_call_success(self):
        """_retry_call 成功时应返回结果"""
        from quantia.job.stock_financial_data import _retry_call
        result = _retry_call(lambda: 42, name="test")
        self.assertEqual(result, 42)

    def test_retry_call_retries_on_failure(self):
        """_retry_call 失败时应重试指定次数"""
        from quantia.job.stock_financial_data import _retry_call
        counter = {'n': 0}

        def flaky():
            counter['n'] += 1
            if counter['n'] < 3:
                raise Exception("not yet")
            return "ok"

        result = _retry_call(flaky, name="test", retries=3, sleep=0)
        self.assertEqual(result, "ok")
        self.assertEqual(counter['n'], 3)

    @patch('quantia.job.stock_financial_data.mdb')
    def test_get_stock_list_from_db(self, mock_mdb):
        """应优先从数据库获取股票列表"""
        from quantia.job.stock_financial_data import get_stock_list
        mock_mdb.executeSqlFetch.return_value = [('000001',), ('600000',), ('300001',)]
        codes = get_stock_list()
        self.assertEqual(codes, ['000001', '600000', '300001'])

    @patch('quantia.job.stock_financial_data.ak')
    @patch('quantia.job.stock_financial_data.mdb')
    def test_fetch_single_stock_success(self, mock_mdb, mock_ak):
        """fetch_single_stock 应正确处理东方财富 API 返回数据"""
        from quantia.job.stock_financial_data import fetch_single_stock

        # 模拟 API 返回
        mock_df = pd.DataFrame({
            'SECURITY_CODE': ['000001', '000001'],
            'REPORT_DATE': ['2024-12-31', '2024-09-30'],
            'REPORT_DATE_NAME': ['2024年报', '2024三季报'],
            'EPSJB': [2.07, 1.87],
            'BPS': [23.25, 23.08],
            'MGJYXJJE': [16.28, 3.70],
            'TOTALOPERATEREVE': [1.31e11, 1.01e11],
            'PARENTNETPROFIT': [4.26e10, 3.83e10],
            'TOTALOPERATEREVETZ': [-10.40, -9.78],
            'PARENTNETPROFITTZ': [-4.21, -3.50],
            'ROEJQ': [9.15, 8.28],
            'ZZCJLL': [0.73, 0.66],
            'XSMLL': [None, None],
            'XSJLL': [32.43, 38.08],
            'ZCFZL': [90.70, 91.02],
            'LD': [None, None],
            'SD': [None, None],
            'TOAZZL': [0.02, 0.02],
            'CHZZL': [None, None],
            'YSZKZZL': [None, None],
        })
        mock_ak.stock_financial_analysis_indicator_em.return_value = mock_df
        mock_mdb.engine.return_value = MagicMock()
        mock_mdb.checkTableIsExist.return_value = True

        result = fetch_single_stock('000001', incremental=False)
        self.assertEqual(result, 2)  # 2 rows

    @patch('quantia.job.stock_financial_data.ak')
    def test_fetch_single_stock_empty(self, mock_ak):
        """空 DataFrame 应返回 0"""
        from quantia.job.stock_financial_data import fetch_single_stock
        mock_ak.stock_financial_analysis_indicator_em.return_value = pd.DataFrame()
        result = fetch_single_stock('000001')
        self.assertEqual(result, 0)

    @patch('quantia.job.stock_financial_data.ak')
    def test_fetch_single_stock_api_error(self, mock_ak):
        """API 异常应返回 -1"""
        from quantia.job.stock_financial_data import fetch_single_stock
        mock_ak.stock_financial_analysis_indicator_em.side_effect = Exception("API error")
        result = fetch_single_stock('000001')
        self.assertEqual(result, -1)

    @patch('quantia.job.stock_financial_data.mdb')
    def test_get_financial_data_batch_empty(self, mock_mdb):
        """空代码列表应返回空字典"""
        from quantia.job.stock_financial_data import get_financial_data_batch
        result = get_financial_data_batch([])
        self.assertEqual(result, {})

    @patch('quantia.job.stock_financial_data.mdb')
    def test_get_financial_data_batch_no_table(self, mock_mdb):
        """表不存在时应返回空字典"""
        from quantia.job.stock_financial_data import get_financial_data_batch
        mock_mdb.checkTableIsExist.return_value = False
        result = get_financial_data_batch(['000001'])
        self.assertEqual(result, {})


class TestIncrementalSkipLogic(unittest.TestCase):
    """验证增量模式的整只股票级跳过逻辑（日历+完整性感知）"""

    def test_latest_expected_report_date_by_month(self):
        """披露日历应保守返回'已确定披露'的最近报告期"""
        from quantia.job.stock_financial_data import _latest_expected_report_date
        # 1-4月 -> 上年三季报(9/30)
        self.assertEqual(_latest_expected_report_date(date(2026, 2, 15)), date(2025, 9, 30))
        self.assertEqual(_latest_expected_report_date(date(2026, 4, 30)), date(2025, 9, 30))
        # 5-8月 -> 当年一季报(3/31)
        self.assertEqual(_latest_expected_report_date(date(2026, 5, 1)), date(2026, 3, 31))
        self.assertEqual(_latest_expected_report_date(date(2026, 8, 31)), date(2026, 3, 31))
        # 9-10月 -> 当年半年报(6/30)
        self.assertEqual(_latest_expected_report_date(date(2026, 9, 1)), date(2026, 6, 30))
        self.assertEqual(_latest_expected_report_date(date(2026, 10, 31)), date(2026, 6, 30))
        # 11-12月 -> 当年三季报(9/30)
        self.assertEqual(_latest_expected_report_date(date(2026, 11, 1)), date(2026, 9, 30))
        self.assertEqual(_latest_expected_report_date(date(2026, 12, 31)), date(2026, 9, 30))

    @patch('quantia.job.stock_financial_data.mdb')
    def test_get_caught_up_codes_returns_set(self, mock_mdb):
        """已追平股票集合应来自 report_date>=目标 且字段非空的查询结果"""
        from quantia.job.stock_financial_data import _get_caught_up_codes
        mock_mdb.checkTableIsExist.return_value = True
        mock_mdb.executeSqlFetch.return_value = [('000001',), ('600000',)]
        codes = _get_caught_up_codes('revenue')
        self.assertEqual(codes, {'000001', '600000'})

    @patch('quantia.job.stock_financial_data.mdb')
    def test_get_caught_up_codes_no_table(self, mock_mdb):
        """表不存在时应返回空集合（即全量采集）"""
        from quantia.job.stock_financial_data import _get_caught_up_codes
        mock_mdb.checkTableIsExist.return_value = False
        self.assertEqual(_get_caught_up_codes('revenue'), set())

    def test_get_caught_up_codes_rejects_unknown_field(self):
        """field 应做白名单校验，拒绝非法输入"""
        from quantia.job.stock_financial_data import _get_caught_up_codes
        with self.assertRaises(ValueError):
            _get_caught_up_codes('revenue; DROP TABLE x')

    @patch('quantia.job.stock_financial_data.time.sleep')
    @patch('quantia.job.stock_financial_data.fetch_single_stock')
    @patch('quantia.job.stock_financial_data._get_caught_up_codes')
    def test_fetch_all_stocks_skips_caught_up(self, mock_caught, mock_fetch, mock_sleep):
        """增量模式应跳过已追平股票，且不对其调用API/休眠"""
        from quantia.job.stock_financial_data import fetch_all_stocks
        mock_caught.return_value = {'000001'}
        mock_fetch.return_value = 5
        success, fail, skip, rows = fetch_all_stocks(
            ['000001', '600000'], incremental=True)
        # 000001 被跳过（无API、无sleep），仅 600000 被采集
        mock_fetch.assert_called_once_with('600000', min_date=None)
        self.assertEqual(mock_sleep.call_count, 1)
        self.assertEqual(skip, 1)
        self.assertEqual(success, 1)
        self.assertEqual(rows, 5)

    @patch('quantia.job.stock_financial_data.time.sleep')
    @patch('quantia.job.stock_financial_data.fetch_single_stock')
    @patch('quantia.job.stock_financial_data._get_caught_up_codes')
    def test_fetch_all_stocks_full_mode_no_skip(self, mock_caught, mock_fetch, mock_sleep):
        """全量模式不应查询/跳过任何股票"""
        from quantia.job.stock_financial_data import fetch_all_stocks
        mock_fetch.return_value = 3
        fetch_all_stocks(['000001', '600000'], incremental=False)
        mock_caught.assert_not_called()
        self.assertEqual(mock_fetch.call_count, 2)


class TestFundamentalsIntegration(unittest.TestCase):
    """验证 fundamentals.py 真实数据加载与合成数据降级逻辑"""

    def test_field_db_map_covers_strategy_fields(self):
        """字段映射应覆盖低ATR成长策略所需的核心字段"""
        from quantia.core.backtest.fundamentals import FundamentalDataProvider
        mapping = FundamentalDataProvider._FIELD_DB_MAP
        # 低ATR策略需要: inc_total_revenue_year_on_year, inc_net_profit_year_on_year, roe
        self.assertIn('inc_total_revenue_year_on_year', mapping)
        self.assertIn('inc_net_profit_year_on_year', mapping)
        self.assertIn('roe', mapping)
        self.assertIn('eps', mapping)

    def test_field_db_map_values_match_db_columns(self):
        """映射的目标字段应匹配 cn_stock_financial 表的列名"""
        from quantia.core.backtest.fundamentals import FundamentalDataProvider
        from quantia.core.tablestructure import TABLE_CN_STOCK_FINANCIAL

        db_cols = set(TABLE_CN_STOCK_FINANCIAL['columns'].keys())
        for jq_field, db_field in FundamentalDataProvider._FIELD_DB_MAP.items():
            self.assertIn(db_field, db_cols,
                          f"映射目标 '{db_field}' (来自 '{jq_field}') 不在 cn_stock_financial 表中")

    def test_synthetic_fallback_still_works(self):
        """当无真实数据时，合成数据逻辑应正常工作"""
        from quantia.core.backtest.fundamentals import FundamentalDataProvider

        # 创建一个最小化的 mock engine
        mock_engine = MagicMock()
        mock_engine.context = MagicMock()
        mock_engine.context.current_dt = datetime(2024, 6, 15)

        provider = FundamentalDataProvider(mock_engine)
        provider._initialized = True
        provider._stock_info = pd.DataFrame({
            'code': ['000001', '600000'],
            'total_shares': [1e10, 2e10],
            'current_mcap': [3000, 5000],
        })

        df = pd.DataFrame({'code': ['000001', '600000']})

        # 模拟 get_financial_data_batch 返回空
        with patch('quantia.core.backtest.fundamentals.FundamentalDataProvider._load_real_financial_data',
                   return_value={}):
            provider._generate_synthetic_fields(df, {'roe', 'eps'})

        self.assertIn('roe', df.columns)
        self.assertIn('eps', df.columns)
        self.assertEqual(len(df), 2)
        # 合成值应为数字
        self.assertTrue(np.isfinite(df['roe'].iloc[0]))
        self.assertTrue(np.isfinite(df['eps'].iloc[0]))

    def test_real_data_used_when_available(self):
        """当有真实数据时，应使用真实值而非合成值"""
        from quantia.core.backtest.fundamentals import FundamentalDataProvider

        mock_engine = MagicMock()
        mock_engine.context = MagicMock()
        mock_engine.context.current_dt = datetime(2024, 6, 15)

        provider = FundamentalDataProvider(mock_engine)
        provider._initialized = True
        provider._stock_info = pd.DataFrame({
            'code': ['000001'],
            'total_shares': [1e10],
            'current_mcap': [3000],
        })

        df = pd.DataFrame({'code': ['000001']})

        real_data = {
            '000001': {
                'revenue_yoy': 15.5,
                'net_profit_yoy': 20.3,
                'roe': 12.8,
                'eps': 2.07,
                'net_profit_margin': 32.4,
                'gross_margin': None,  # 缺失，应降级
            }
        }

        with patch('quantia.core.backtest.fundamentals.FundamentalDataProvider._load_real_financial_data',
                   return_value=real_data):
            provider._generate_synthetic_fields(
                df, {'inc_total_revenue_year_on_year', 'inc_net_profit_year_on_year',
                     'roe', 'eps', 'gross_profit_margin'})

        # 有映射且有真实值的字段应使用真实值
        self.assertAlmostEqual(df['inc_total_revenue_year_on_year'].iloc[0], 15.5, places=1)
        self.assertAlmostEqual(df['inc_net_profit_year_on_year'].iloc[0], 20.3, places=1)
        self.assertAlmostEqual(df['roe'].iloc[0], 12.8, places=1)
        self.assertAlmostEqual(df['eps'].iloc[0], 2.07, places=2)
        # gross_profit_margin 映射到 gross_margin 为 None，
        # 真实数据基础设施可用时应为 NaN（而非合成随机值）
        self.assertTrue(np.isnan(df['gross_profit_margin'].iloc[0]))

    def test_query_api_objects_exist(self):
        """聚宽风格的查询 API 对象应正常导入"""
        from quantia.core.backtest.fundamentals import (
            valuation, indicator, balance, cash_flow, query, OrderCost
        )
        self.assertIsNotNone(valuation.code)
        self.assertIsNotNone(indicator.roe)
        self.assertIsNotNone(balance.total_assets)
        self.assertIsNotNone(cash_flow.net_operate_cash_flow)

    def test_div_field_expr(self):
        """除法字段表达式应正常工作（如 balance.total_liability / balance.total_assets）"""
        from quantia.core.backtest.fundamentals import balance
        expr = balance.total_liability / balance.total_assets
        result = expr < 0.70
        self.assertIsInstance(result, tuple)
        self.assertEqual(result[0], 'div_lt')

    def test_zero_value_not_treated_as_missing(self):
        """DB中值为0.0时应使用真实值0而非合成随机值（truthiness bug回归测试）"""
        from quantia.core.backtest.fundamentals import FundamentalDataProvider

        mock_engine = MagicMock()
        mock_engine.context = MagicMock()
        mock_engine.context.current_dt = datetime(2024, 6, 15)

        provider = FundamentalDataProvider(mock_engine)
        provider._initialized = True
        provider._stock_info = pd.DataFrame({
            'code': ['000001'],
            'total_shares': [1e10],
            'current_mcap': [3000],
        })

        df = pd.DataFrame({'code': ['000001']})

        # ocfps=0.0 → net_operate_cash_flow 应为 0，不应降级为合成值
        # alr=0.0 → total_liability 应为 0（零负债），不应降级为合成值
        real_data = {
            '000001': {
                'ocfps': 0.0,
                'roa': 5.0,
                'net_profit': 1e9,
                'asset_liability_ratio': 0.0,
            }
        }

        with patch('quantia.core.backtest.fundamentals.FundamentalDataProvider._load_real_financial_data',
                   return_value=real_data):
            provider._generate_synthetic_fields(
                df, {'net_operate_cash_flow', 'total_liability'})

        # ocfps=0 × total_shares = 0，不是随机正数
        self.assertEqual(df['net_operate_cash_flow'].iloc[0], 0.0)
        # alr=0% → total_liability = total_assets × 0 = 0
        self.assertEqual(df['total_liability'].iloc[0], 0.0)

    def test_no_real_data_stock_gets_nan(self):
        """无真实财务数据的股票应得到NaN而非合成随机值（防止污染选股）"""
        from quantia.core.backtest.fundamentals import FundamentalDataProvider

        mock_engine = MagicMock()
        mock_engine.context = MagicMock()
        mock_engine.context.current_dt = datetime(2024, 6, 15)

        provider = FundamentalDataProvider(mock_engine)
        provider._initialized = True
        provider._stock_info = pd.DataFrame({
            'code': ['000001', '999999'],
            'total_shares': [1e10, 5e9],
            'current_mcap': [3000, 100],
        })

        df = pd.DataFrame({'code': ['000001', '999999']})

        # 只有 000001 有真实数据；999999 无数据
        real_data = {
            '000001': {
                'revenue_yoy': 25.0,
                'net_profit_yoy': 30.0,
                'roe': 15.0,
            }
        }

        with patch('quantia.core.backtest.fundamentals.FundamentalDataProvider._load_real_financial_data',
                   return_value=real_data):
            provider._generate_synthetic_fields(
                df, {'inc_total_revenue_year_on_year', 'inc_net_profit_year_on_year', 'roe'})

        # 000001 有真实数据，应使用真值
        self.assertAlmostEqual(df['inc_total_revenue_year_on_year'].iloc[0], 25.0)
        self.assertAlmostEqual(df['roe'].iloc[0], 15.0)
        # 999999 无真实数据，所有字段应为 NaN（而非合成随机值）
        self.assertTrue(np.isnan(df['inc_total_revenue_year_on_year'].iloc[1]))
        self.assertTrue(np.isnan(df['inc_net_profit_year_on_year'].iloc[1]))
        self.assertTrue(np.isnan(df['roe'].iloc[1]))

    def test_synthetic_fallback_when_no_table(self):
        """当财务数据表完全不存在时，仍保留合成值降级（向后兼容）"""
        from quantia.core.backtest.fundamentals import FundamentalDataProvider

        mock_engine = MagicMock()
        mock_engine.context = MagicMock()
        mock_engine.context.current_dt = datetime(2024, 6, 15)

        provider = FundamentalDataProvider(mock_engine)
        provider._initialized = True
        provider._stock_info = pd.DataFrame({
            'code': ['000001'],
            'total_shares': [1e10],
            'current_mcap': [3000],
        })

        df = pd.DataFrame({'code': ['000001']})

        # 模拟 cn_stock_financial 表不存在 → 返回空字典
        with patch('quantia.core.backtest.fundamentals.FundamentalDataProvider._load_real_financial_data',
                   return_value={}):
            provider._generate_synthetic_fields(df, {'roe', 'eps'})

        # 无真实数据基础设施时应降级到合成值（有限数值，非NaN）
        self.assertTrue(np.isfinite(df['roe'].iloc[0]))
        self.assertTrue(np.isfinite(df['eps'].iloc[0]))


class TestMainEntryPoint(unittest.TestCase):
    """验证 main() 函数的参数解析和流程"""

    @patch('quantia.job.stock_financial_data.fetch_all_stocks', return_value=(5, 1, 2, 100))
    @patch('quantia.job.stock_financial_data.get_stock_list', return_value=['000001', '000002'])
    @patch('quantia.job.stock_financial_data.create_financial_table')
    def test_main_test_mode(self, mock_create, mock_list, mock_fetch):
        """--test 模式应限制股票数量"""
        from quantia.job.stock_financial_data import main
        with patch('sys.argv', ['prog', '--test', '1']):
            main()
        mock_fetch.assert_called_once()
        args, kwargs = mock_fetch.call_args
        self.assertEqual(len(args[0]), 1)  # 只取1只

    @patch('quantia.job.stock_financial_data.fetch_all_stocks', return_value=(2, 0, 0, 40))
    @patch('quantia.job.stock_financial_data.get_stock_list', return_value=['000001', '000002'])
    @patch('quantia.job.stock_financial_data.create_financial_table')
    def test_main_years_mode(self, mock_create, mock_list, mock_fetch):
        """--years 模式应传递 min_date 参数"""
        from quantia.job.stock_financial_data import main
        from datetime import date
        with patch('sys.argv', ['prog', '--years', '5']):
            main()
        mock_fetch.assert_called_once()
        args, kwargs = mock_fetch.call_args
        min_date = kwargs.get('min_date')
        self.assertIsNotNone(min_date)
        self.assertIsInstance(min_date, date)
        # 5年前的1月1日
        expected_year = date.today().year - 5
        self.assertEqual(min_date.year, expected_year)
        self.assertEqual(min_date.month, 1)
        self.assertEqual(min_date.day, 1)


if __name__ == '__main__':
    unittest.main()
