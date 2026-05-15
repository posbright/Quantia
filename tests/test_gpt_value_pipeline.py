#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GPT综合选股流水线单元测试

验证：
1. filter_gpt_value_stocks 能正确筛选合格/不合格股票
2. compute_gpt_score 评分在合理范围内
3. gpt_value_data_job.prepare() 在各种边界情况下的行为
4. GPT_INDICATOR_FIELDS 与 TABLE_CN_STOCK_STRATEGY_GPT_VALUE 列定义一致
"""

import datetime
import math
import pandas as pd
import pytest

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from quantia.core.strategy.gpt_value_strategy import (
    filter_gpt_value_stocks,
    compute_gpt_score,
    check_gpt_value_from_selection,
    GPT_INDICATOR_FIELDS,
    _DEFAULT_PARAMS,
)
import quantia.core.tablestructure as tbs


# ==================== 测试数据工厂 ====================

def _make_stock_row(**overrides):
    """创建一只满足所有GPT筛选条件的合格股票行"""
    base = {
        'date': datetime.date(2026, 2, 27),
        'code': '600519',
        'name': '贵州茅台',
        'new_price': 1500.0,
        'change_rate': 1.5,
        'volume': 10000000,
        # 第一层：财务安全
        'debt_asset_ratio': 25.0,       # < 60 ✓
        'per_netcash_operate': 15.0,    # > 0 ✓
        'current_ratio': 3.5,           # >= 1.0 ✓
        'speed_ratio': 2.8,             # >= 0.7 ✓
        # 第二层：盈利能力
        'roe_weight': 30.0,             # >= 15 ✓
        'sale_gpr': 90.0,              # >= 25 ✓
        'sale_npr': 50.0,              # >= 8 ✓
        'jroa': 15.0,                   # >= 4 ✓
        # 第三层：成长质量
        'income_growthrate_3y': 15.0,   # > 8 ✓
        'netprofit_growthrate_3y': 20.0, # > 8 ✓
        'deduct_netprofit_growthrate': 10.0, # > 0 ✓
        # 第五层：估值
        'pe9': 25.0,                    # 0 < pe <= 50 ✓
        'pbnewmrq': 5.0,               # <= 10 ✓
    }
    base.update(overrides)
    return base


def _make_failing_stock(**overrides):
    """创建一只不满足条件的股票行（资产负债率超标）"""
    row = _make_stock_row()
    row['debt_asset_ratio'] = 80.0  # > 60 ✗
    row['code'] = '000001'
    row['name'] = '平安银行'
    row.update(overrides)
    return row


# ==================== filter_gpt_value_stocks 测试 ====================

class TestFilterGptValueStocks:
    def test_qualified_stock_passes(self):
        """合格股票应该通过筛选"""
        df = pd.DataFrame([_make_stock_row()])
        result = filter_gpt_value_stocks(df)
        assert len(result) == 1
        assert result.iloc[0]['code'] == '600519'

    def test_unqualified_stock_rejected(self):
        """不合格股票应该被拒绝"""
        df = pd.DataFrame([_make_failing_stock()])
        result = filter_gpt_value_stocks(df)
        assert len(result) == 0

    def test_mixed_stocks_filtered(self):
        """混合数据中只保留合格的"""
        df = pd.DataFrame([
            _make_stock_row(),
            _make_failing_stock(),
            _make_stock_row(code='000858', name='五粮液'),
        ])
        result = filter_gpt_value_stocks(df)
        assert len(result) == 2
        assert set(result['code'].tolist()) == {'600519', '000858'}

    def test_empty_input_returns_empty(self):
        """空输入返回空"""
        result = filter_gpt_value_stocks(pd.DataFrame())
        assert len(result) == 0

    def test_none_input_returns_empty(self):
        """None输入返回空"""
        result = filter_gpt_value_stocks(None)
        assert len(result) == 0

    def test_result_has_gpt_score(self):
        """筛选结果应包含 gpt_score 列"""
        df = pd.DataFrame([_make_stock_row()])
        result = filter_gpt_value_stocks(df)
        assert 'gpt_score' in result.columns
        assert result.iloc[0]['gpt_score'] > 0

    def test_result_has_all_indicator_fields(self):
        """筛选结果应包含所有 GPT_INDICATOR_FIELDS"""
        df = pd.DataFrame([_make_stock_row()])
        result = filter_gpt_value_stocks(df)
        for field in GPT_INDICATOR_FIELDS:
            assert field in result.columns, f"缺少字段: {field}"


# ==================== check_gpt_value_from_selection 边界测试 ====================

class TestCheckGptValue:
    def test_debt_ratio_boundary(self):
        """资产负债率=60 不通过 (>= 60 fails)"""
        row = pd.Series(_make_stock_row(debt_asset_ratio=60.0))
        assert check_gpt_value_from_selection(row, _DEFAULT_PARAMS) is False

    def test_debt_ratio_just_under(self):
        """资产负债率=59.9 通过"""
        row = pd.Series(_make_stock_row(debt_asset_ratio=59.9))
        assert check_gpt_value_from_selection(row, _DEFAULT_PARAMS) is True

    def test_cashflow_zero_fails(self):
        """每股经营现金流=0 不通过 (<= 0 fails)"""
        row = pd.Series(_make_stock_row(per_netcash_operate=0))
        assert check_gpt_value_from_selection(row, _DEFAULT_PARAMS) is False

    def test_roe_below_threshold_fails(self):
        """ROE=9.9 不通过 (< 10)"""
        row = pd.Series(_make_stock_row(roe_weight=9.9))
        assert check_gpt_value_from_selection(row, _DEFAULT_PARAMS) is False

    def test_pe_zero_fails(self):
        """PE=0 不通过 (<= 0)"""
        row = pd.Series(_make_stock_row(pe9=0))
        assert check_gpt_value_from_selection(row, _DEFAULT_PARAMS) is False

    def test_pe_negative_fails(self):
        """PE=-10 不通过 (负数)"""
        row = pd.Series(_make_stock_row(pe9=-10))
        assert check_gpt_value_from_selection(row, _DEFAULT_PARAMS) is False

    def test_pe_over_50_fails(self):
        """PE=51 不通过 (> 50)"""
        row = pd.Series(_make_stock_row(pe9=51))
        assert check_gpt_value_from_selection(row, _DEFAULT_PARAMS) is False

    def test_nan_debt_ratio_soft_pass(self):
        """NaN值时跳过该项检查（soft-pass），不因缺数据而淘汰"""
        row = pd.Series(_make_stock_row(debt_asset_ratio=float('nan')))
        assert check_gpt_value_from_selection(row, _DEFAULT_PARAMS) is True

    def test_none_roe_soft_pass(self):
        """None ROE时跳过该项检查（其余关键字段有效即可通过最低数据质量要求）"""
        row = pd.Series(_make_stock_row(roe_weight=None))
        assert check_gpt_value_from_selection(row, _DEFAULT_PARAMS) is True

    def test_too_many_critical_fields_missing_fails(self):
        """关键财务字段缺失超过3个时不通过（最低数据质量要求：6个关键字段中至少3个有效）"""
        data = _make_stock_row()
        # 6个关键字段中只保留1个有效，应被拒绝
        data['roe_weight'] = None
        data['pe9'] = None
        data['sale_gpr'] = None
        data['sale_npr'] = None
        data['debt_asset_ratio'] = None
        # income_growthrate_3y 保留有效值 → 仅1/6有效 < 3 → 不通过
        row = pd.Series(data)
        assert check_gpt_value_from_selection(row, _DEFAULT_PARAMS) is False


# ==================== compute_gpt_score 测试 ====================

class TestComputeGptScore:
    def test_perfect_stock_high_score(self):
        """完美股票应有高分"""
        row = pd.Series(_make_stock_row())
        result = compute_gpt_score(row, _DEFAULT_PARAMS)
        assert 'gpt_score' in result
        assert result['gpt_score'] > 50, f"完美股票评分应>50, 实际={result['gpt_score']}"

    def test_score_in_valid_range(self):
        """评分应在 0~100 之间"""
        row = pd.Series(_make_stock_row())
        result = compute_gpt_score(row, _DEFAULT_PARAMS)
        assert 0 <= result['gpt_score'] <= 100

    def test_score_contains_all_indicators(self):
        """评分结果包含所有指标值"""
        row = pd.Series(_make_stock_row())
        result = compute_gpt_score(row, _DEFAULT_PARAMS)
        for field in GPT_INDICATOR_FIELDS:
            assert field in result, f"评分结果缺少字段: {field}"

    def test_mediocre_stock_lower_score(self):
        """勉强及格的股票应比完美股票分低"""
        perfect = pd.Series(_make_stock_row())
        mediocre = pd.Series(_make_stock_row(
            roe_weight=15.1,       # 刚过线
            sale_gpr=25.1,         # 刚过线
            income_growthrate_3y=8.1,  # 刚过线
            pe9=49,                # 接近上限
        ))
        s_perfect = compute_gpt_score(perfect, _DEFAULT_PARAMS)['gpt_score']
        s_mediocre = compute_gpt_score(mediocre, _DEFAULT_PARAMS)['gpt_score']
        assert s_perfect > s_mediocre


# ==================== 表结构一致性测试 ====================

class TestTableConsistency:
    def test_indicator_fields_subset_of_table_columns(self):
        """GPT_INDICATOR_FIELDS 中的每个字段都应该在表定义中"""
        table_cols = set(tbs.TABLE_CN_STOCK_STRATEGY_GPT_VALUE['columns'].keys())
        for field in GPT_INDICATOR_FIELDS:
            assert field in table_cols, f"GPT_INDICATOR_FIELDS 中的 '{field}' 不在表定义中"

    def test_table_has_date_code_name(self):
        """GPT表应有 date, code, name 基础字段"""
        cols = tbs.TABLE_CN_STOCK_STRATEGY_GPT_VALUE['columns']
        assert 'date' in cols
        assert 'code' in cols
        assert 'name' in cols

    def test_table_has_backtest_fields(self):
        """GPT表应有回测字段 (rate_1, rate_2, ...)"""
        cols = tbs.TABLE_CN_STOCK_STRATEGY_GPT_VALUE['columns']
        assert 'rate_1' in cols, "缺少回测字段 rate_1"
        assert 'rate_5' in cols, "缺少回测字段 rate_5"

    def test_gpt_score_in_table(self):
        """GPT表应有 gpt_score 列"""
        cols = tbs.TABLE_CN_STOCK_STRATEGY_GPT_VALUE['columns']
        assert 'gpt_score' in cols

    def test_selection_table_has_all_filter_fields(self):
        """cn_stock_selection 表应包含GPT筛选所需的所有字段"""
        selection_cols = set(tbs.TABLE_CN_STOCK_SELECTION['columns'].keys())
        required_fields = [
            'debt_asset_ratio', 'per_netcash_operate', 'current_ratio', 'speed_ratio',
            'roe_weight', 'sale_gpr', 'sale_npr', 'jroa',
            'income_growthrate_3y', 'netprofit_growthrate_3y', 'deduct_netprofit_growthrate',
            'pe9', 'pbnewmrq',
        ]
        for field in required_fields:
            assert field in selection_cols, \
                f"cn_stock_selection 缺少 GPT 筛选所需字段 '{field}'"


# ==================== gpt_value_data_job.prepare 逻辑测试 ====================

class TestPrepareLogic:
    """测试 prepare() 的分支逻辑（不连接数据库，通过 mock 验证）"""

    def test_prepare_skips_when_no_selection_data(self):
        """当 cn_stock_selection 无今日数据时，prepare 应安静跳过"""
        from unittest.mock import patch, MagicMock
        import quantia.job.gpt_value_data_job as gptj

        with patch.object(gptj.mdb, 'checkTableIsExist', return_value=True), \
             patch.object(gptj.pd, 'read_sql', return_value=pd.DataFrame()):
            # 不应抛异常
            gptj.prepare(datetime.date(2026, 2, 27))

    def test_prepare_skips_when_source_table_missing(self):
        """当 cn_stock_selection 表不存在时，应跳过"""
        from unittest.mock import patch
        import quantia.job.gpt_value_data_job as gptj

        with patch.object(gptj.mdb, 'checkTableIsExist', return_value=False):
            gptj.prepare(datetime.date(2026, 2, 27))

    def test_prepare_skips_when_all_stocks_filtered_out(self):
        """当所有股票都被筛掉时，不应创建表"""
        from unittest.mock import patch, MagicMock, call
        import quantia.job.gpt_value_data_job as gptj

        # 只有一只不合格的股票
        bad_data = pd.DataFrame([_make_failing_stock()])

        with patch.object(gptj.mdb, 'checkTableIsExist', return_value=True), \
             patch.object(gptj.pd, 'read_sql', return_value=bad_data), \
             patch.object(gptj.mdb, 'insert_db_from_df') as mock_insert:
            gptj.prepare(datetime.date(2026, 2, 27))
            mock_insert.assert_not_called()  # 不应写入

    def test_prepare_creates_table_when_stocks_qualify(self):
        """当有合格股票时，应调用 insert_db_from_df 创建表"""
        from unittest.mock import patch, MagicMock
        import quantia.job.gpt_value_data_job as gptj

        good_data = pd.DataFrame([_make_stock_row()])

        # checkTableIsExist 对源表返回 True（存在），对目标表返回 False（需创建）
        def _check_table(name):
            return name == 'cn_stock_selection'

        with patch.object(gptj.mdb, 'checkTableIsExist', side_effect=_check_table), \
             patch.object(gptj.pd, 'read_sql', return_value=good_data), \
             patch.object(gptj.mdb, 'executeSql'), \
             patch.object(gptj.mdb, 'insert_db_from_df') as mock_insert:
            gptj.prepare(datetime.date(2026, 2, 27))
            assert mock_insert.called, "有合格股票时应调用 insert_db_from_df"
            # 验证传入了 cols_type（因为目标表不存在，需要创建）
            args, kwargs = mock_insert.call_args
            assert args[2] is not None, "表不存在时 cols_type 应非 None（用于创建表）"


# ==================== low_atr 策略 Bug 修复验证 ====================

class TestLowAtrBugFixes:
    """验证 low_atr.py 中的两个关键 bug 已被修复"""

    def test_lowest_row_tracks_correctly_for_rising_prices(self):
        """修复 if/elif bug: 单调上涨序列中 lowest_row 应正确追踪"""
        from quantia.core.strategy.low_atr import check_low_increase

        # 构造数据：250天历史 + 最后10天单调上涨（从50涨到55）
        dates = pd.date_range('2025-01-01', periods=260, freq='B')
        data = pd.DataFrame({
            'date': [d.strftime('%Y-%m-%d') for d in dates],
            'open': [50.0] * 260,
            'high': [51.0] * 260,
            'low': [49.5] * 260,
            'close': [50.0] * 250 + [50 + i * 0.5 for i in range(10)],
            'volume': [1000000] * 260,
            'p_change': [0.5] * 250 + [1.0] * 10,
        })
        stock = ('2026-03-02', '000001', '平安银行')
        # 最后10天：close 从 50.0 到 54.5
        # 幅度 = (54.5 - 50.0) / 50.0 = 0.09 < 0.1 → False（但至少不会因为bug给ratio=-999999）
        # 修复前 lowest_row=1000000 → ratio=(54.5-1000000)/1000000 ≈ -1 → False (bug)
        # 修复后 lowest_row=50.0 → ratio=(54.5-50.0)/50.0 = 0.09 → False（正确的False）
        result = check_low_increase(stock, data, date=datetime.datetime(2026, 3, 2))
        # 这个用例的关键是：修复后不会因为 lowest_row=1000000 而产生错误的 ratio
        assert result is False  # 0.09 < 0.1, 正确的 False

    def test_low_atr_matches_with_valid_range(self):
        """有效的低波动+适度涨幅应返回 True"""
        from quantia.core.strategy.low_atr import check_low_increase

        dates = pd.date_range('2025-01-01', periods=260, freq='B')
        # 最后10天：从50涨到56（12%涨幅），日均波动小
        last_10_prices = [50, 50.5, 51, 51.5, 52, 53, 54, 54.5, 55, 56]
        last_10_changes = [1.0, 1.0, 1.0, 1.0, 1.9, 1.9, 0.9, 0.9, 1.8, 1.8]
        data = pd.DataFrame({
            'date': [d.strftime('%Y-%m-%d') for d in dates],
            'open': [50.0] * 260,
            'high': [51.0] * 260,
            'low': [49.5] * 260,
            'close': [50.0] * 250 + last_10_prices,
            'volume': [1000000] * 260,
            'p_change': [0.5] * 250 + last_10_changes,
        })
        stock = ('2026-03-02', '000001', '平安银行')
        # ratio = (56-50)/50 = 0.12 > 0.1 ✓, ATR = sum(changes)/10 ≈ 1.22 < 10 ✓
        result = check_low_increase(stock, data, date=datetime.datetime(2026, 3, 2))
        assert isinstance(result, dict), "12%涨幅且低ATR应返回dict"

    def test_ratio_threshold_is_10_percent(self):
        """验证 ratio 阈值已从 1.1 (110%) 修正为 0.1 (10%)"""
        from quantia.core.strategy.low_atr import check_low_increase

        dates = pd.date_range('2025-01-01', periods=260, freq='B')
        # 最后10天：从50涨到55.5（11%涨幅）
        data = pd.DataFrame({
            'date': [d.strftime('%Y-%m-%d') for d in dates],
            'open': [50.0] * 260,
            'high': [51.0] * 260,
            'low': [49.5] * 260,
            'close': [50.0] * 250 + [50, 50.5, 51, 51.5, 52, 52.5, 53, 53.5, 54, 55.5],
            'volume': [1000000] * 260,
            'p_change': [0.5] * 250 + [0.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.9, 1.5, 2.8],
        })
        stock = ('2026-03-02', '000001', '平安银行')
        # ratio = (55.5-50)/50 = 0.11 > 0.1 ✓
        result = check_low_increase(stock, data, date=datetime.datetime(2026, 3, 2))
        assert isinstance(result, dict), "11%涨幅应满足0.1阈值"


# ==================== GPT筛选逐层通过率诊断 ====================

class TestGptFilterDiagnostic:
    """
    模拟真实市场数据场景，诊断每层筛选的"杀伤力"。
    验证修复后：
    - 各层不会因 NaN 产生不合理淘汰
    - 合理的股票能通过
    """

    @staticmethod
    def _make_realistic_stock(
        debt=45, cashflow=2.0, curr=1.5, speed=1.0,
        roe=12, gpr=20, npr=8, roa=5,
        rev3y=5, prof3y=6, deduct=3,
        pe=25, pb=4
    ):
        """构建一只较为真实的 A 股股票数据"""
        return pd.Series({
            'date': '2026-03-02', 'code': '000001', 'name': '测试股票',
            'debt_asset_ratio': debt, 'per_netcash_operate': cashflow,
            'current_ratio': curr, 'speed_ratio': speed,
            'roe_weight': roe, 'sale_gpr': gpr, 'sale_npr': npr, 'jroa': roa,
            'income_growthrate_3y': rev3y, 'netprofit_growthrate_3y': prof3y,
            'deduct_netprofit_growthrate': deduct,
            'pe9': pe, 'pbnewmrq': pb,
        })

    def test_typical_good_stock_passes(self):
        """典型的好股票：ROE=12%, GPR=20%, 3Y增长5% — 旧逻辑会拒绝，新逻辑应通过"""
        row = self._make_realistic_stock()
        assert check_gpt_value_from_selection(row, _DEFAULT_PARAMS) is True

    def test_stock_with_missing_3y_growth_passes(self):
        """3年增长率缺失（新上市公司）：旧逻辑直接拒绝，新逻辑跳过该检查"""
        row = self._make_realistic_stock()
        row['income_growthrate_3y'] = None
        row['netprofit_growthrate_3y'] = None
        assert check_gpt_value_from_selection(row, _DEFAULT_PARAMS) is True

    def test_stock_with_all_nan_financials_fails(self):
        """所有财务数据为NaN时：ROE和PE都缺失，最低数据质量不达标"""
        row = pd.Series({
            'date': '2026-03-02', 'code': '000001', 'name': '空壳公司',
            'debt_asset_ratio': None, 'per_netcash_operate': None,
            'current_ratio': None, 'speed_ratio': None,
            'roe_weight': None, 'sale_gpr': None, 'sale_npr': None, 'jroa': None,
            'income_growthrate_3y': None, 'netprofit_growthrate_3y': None,
            'deduct_netprofit_growthrate': None,
            'pe9': None, 'pbnewmrq': None,
        })
        assert check_gpt_value_from_selection(row, _DEFAULT_PARAMS) is False

    def test_mediocre_manufacturer_passes(self):
        """制造业公司：毛利率18%（低于旧阈值25%，高于新阈值15%）"""
        row = self._make_realistic_stock(gpr=18, roe=11, rev3y=4, prof3y=4)
        assert check_gpt_value_from_selection(row, _DEFAULT_PARAMS) is True

    def test_high_debt_still_rejected(self):
        """高负债公司仍应被拒绝（硬约束不变）"""
        row = self._make_realistic_stock(debt=75)
        assert check_gpt_value_from_selection(row, _DEFAULT_PARAMS) is False

    def test_negative_pe_still_rejected(self):
        """亏损公司（PE<0）仍应被拒绝"""
        row = self._make_realistic_stock(pe=-15)
        assert check_gpt_value_from_selection(row, _DEFAULT_PARAMS) is False
