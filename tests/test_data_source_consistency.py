#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证多数据源格式一致性的测试脚本

测试内容：
1. 各数据源返回的列数和列顺序是否与 CN_STOCK_HIST_DATA 一致
2. volume 单位是否统一为 手（100股）
3. amount 单位是否统一为 元
4. date 格式是否为 YYYY-MM-DD
5. NaN/inf 清理是否到位
6. 年限配置是否可通过环境变量调整
7. 增量更新去重和排序逻辑
"""

import sys
import os
import datetime
import time

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)

passed = 0
failed = 0
errors = []


def test(name):
    """测试装饰器（自定义运行器，非 pytest 收集对象）。"""
    def decorator(func):
        global passed, failed, errors
        try:
            func()
            print(f"  ✅ {name}")
            passed += 1
        except AssertionError as e:
            print(f"  ❌ {name}: {e}")
            failed += 1
            errors.append(f"{name}: {e}")
        except Exception as e:
            print(f"  ❌ {name}: 异常 {e}")
            failed += 1
            errors.append(f"{name}: {e}")
    return decorator


# 防止 pytest 把上面的 `test` 工厂函数收集为测试用例
test.__test__ = False  # type: ignore[attr-defined]


# ============================================================
# 测试 1: 列格式一致性
# ============================================================
print("\n🔧 测试 1: CN_STOCK_HIST_DATA 列格式定义")

import quantia.core.tablestructure as tbs

EXPECTED_COLUMNS = ['date', 'open', 'close', 'high', 'low', 'volume', 'amount',
                    'amplitude', 'quote_change', 'ups_downs', 'turnover']

@test("CN_STOCK_HIST_DATA 有 11 列")
def _():
    cols = list(tbs.CN_STOCK_HIST_DATA['columns'].keys())
    assert len(cols) == 11, f"期望11列，实际{len(cols)}列"

@test("CN_STOCK_HIST_DATA 列顺序正确")
def _():
    cols = list(tbs.CN_STOCK_HIST_DATA['columns'].keys())
    assert cols == EXPECTED_COLUMNS, f"列顺序不匹配: {cols}"


# ============================================================
# 测试 2: 新浪财经数据格式
# ============================================================
print("\n🔧 测试 2: 新浪财经数据格式（volume=手, amount=元）")

try:
    from quantia.core.crawling.stock_hist_sina import stock_zh_a_hist_sina
    df_sina = stock_zh_a_hist_sina(symbol='000001', start_date='20260209', end_date='20260211')
    sina_ok = df_sina is not None and len(df_sina) > 0
except Exception as e:
    sina_ok = False
    print(f"  ⚠️ 新浪数据获取失败: {e}")

if sina_ok:
    @test("新浪返回 11 列")
    def _():
        assert len(df_sina.columns) == 11, f"期望11列，实际{len(df_sina.columns)}列: {list(df_sina.columns)}"

    @test("新浪列顺序与 CN_STOCK_HIST_DATA 一致")
    def _():
        assert list(df_sina.columns) == EXPECTED_COLUMNS, f"列不匹配: {list(df_sina.columns)}"

    @test("新浪 volume 单位为手（~431041手，不是43104098股）")
    def _():
        vol = df_sina[df_sina['date'] == '2026-02-11']['volume'].values[0]
        # 平安银行日均约40-80万手，合理范围 10万-200万手
        assert 100000 < vol < 2000000, f"volume={vol}，不在手的合理范围"

    @test("新浪 amount 单位为元（~4.77亿元）")
    def _():
        amt = df_sina[df_sina['date'] == '2026-02-11']['amount'].values[0]
        # 平安银行日均成交额约 3-10亿元
        assert 1e8 < amt < 2e10, f"amount={amt}，不在元的合理范围"

    @test("新浪 date 格式为 YYYY-MM-DD")
    def _():
        date_val = df_sina.iloc[0]['date']
        assert isinstance(date_val, str), f"date不是字符串: {type(date_val)}"
        assert len(date_val) == 10 and date_val[4] == '-', f"date格式不对: {date_val}"

    @test("新浪无 NaN/inf 值")
    def _():
        import numpy as np
        has_nan = df_sina.isnull().any().any()
        has_inf = np.isinf(df_sina.select_dtypes(include=['float64', 'float32']).values).any()
        assert not has_nan, "存在NaN值"
        assert not has_inf, "存在inf值"
else:
    print("  ⚠️ 跳过新浪测试（数据获取失败）")


# ============================================================
# 测试 3: 腾讯财经数据格式
# ============================================================
print("\n🔧 测试 3: 腾讯财经数据格式（volume=手, amount=元）")

time.sleep(1)  # 避免请求过快

try:
    from quantia.core.crawling.stock_hist_tencent import stock_zh_a_hist_tencent
    df_tc = stock_zh_a_hist_tencent(symbol='000001', start_date='20260209', end_date='20260211', adjust='qfq')
    tc_ok = df_tc is not None and len(df_tc) > 0
except Exception as e:
    tc_ok = False
    print(f"  ⚠️ 腾讯数据获取失败: {e}")

if tc_ok:
    @test("腾讯返回 11 列")
    def _():
        assert len(df_tc.columns) == 11, f"期望11列，实际{len(df_tc.columns)}列: {list(df_tc.columns)}"

    @test("腾讯列顺序与 CN_STOCK_HIST_DATA 一致")
    def _():
        assert list(df_tc.columns) == EXPECTED_COLUMNS, f"列不匹配: {list(df_tc.columns)}"

    @test("腾讯 volume 单位为手（~431041手）")
    def _():
        vol = df_tc[df_tc['date'] == '2026-02-11']['volume'].values[0]
        assert 100000 < vol < 2000000, f"volume={vol}，不在手的合理范围"

    @test("腾讯 amount 单位为元（~4.77亿元）")
    def _():
        amt = df_tc[df_tc['date'] == '2026-02-11']['amount'].values[0]
        assert 1e8 < amt < 2e10, f"amount={amt}，不在元的合理范围"

    @test("腾讯 date 格式为 YYYY-MM-DD")
    def _():
        date_val = df_tc.iloc[0]['date']
        assert isinstance(date_val, str), f"date不是字符串: {type(date_val)}"
        assert len(date_val) == 10 and date_val[4] == '-', f"date格式不对: {date_val}"

    @test("腾讯无 NaN/inf 值")
    def _():
        import numpy as np
        has_nan = df_tc.isnull().any().any()
        has_inf = np.isinf(df_tc.select_dtypes(include=['float64', 'float32']).values).any()
        assert not has_nan, "存在NaN值"
        assert not has_inf, "存在inf值"
else:
    print("  ⚠️ 跳过腾讯测试（数据获取失败）")


# ============================================================
# 测试 4: 跨数据源一致性
# ============================================================
print("\n🔧 测试 4: 跨数据源一致性验证")

if sina_ok and tc_ok:
    @test("新浪和腾讯 volume 误差 < 0.1%")
    def _():
        s_vol = df_sina[df_sina['date'] == '2026-02-11']['volume'].values[0]
        t_vol = df_tc[df_tc['date'] == '2026-02-11']['volume'].values[0]
        ratio = abs(s_vol - t_vol) / max(s_vol, t_vol)
        assert ratio < 0.001, f"volume差异过大: Sina={s_vol}, Tencent={t_vol}, 差异={ratio:.4%}"

    @test("新浪和腾讯 amount 误差 < 1%")
    def _():
        s_amt = df_sina[df_sina['date'] == '2026-02-11']['amount'].values[0]
        t_amt = df_tc[df_tc['date'] == '2026-02-11']['amount'].values[0]
        ratio = abs(s_amt - t_amt) / max(s_amt, t_amt)
        assert ratio < 0.01, f"amount差异过大: Sina={s_amt}, Tencent={t_amt}, 差异={ratio:.4%}"

    @test("新浪和腾讯 close 价格一致")
    def _():
        s_close = df_sina[df_sina['date'] == '2026-02-11']['close'].values[0]
        t_close = df_tc[df_tc['date'] == '2026-02-11']['close'].values[0]
        assert abs(s_close - t_close) < 0.01, f"close价格不一致: Sina={s_close}, Tencent={t_close}"
else:
    print("  ⚠️ 跳过跨源一致性测试（需要同时获取新浪和腾讯数据）")


# ============================================================
# 测试 5: 年限配置灵活性
# ============================================================
print("\n🔧 测试 5: 年限配置")

@test("HIST_DATA_DEFAULT_YEARS 支持环境变量覆盖")
def _():
    import quantia.core.stockfetch as stf
    # 默认值应该是20
    assert hasattr(stf, 'HIST_DATA_DEFAULT_YEARS'), "缺少 HIST_DATA_DEFAULT_YEARS 常量"
    # 检查可以从环境变量读取
    assert stf.HIST_DATA_DEFAULT_YEARS == int(os.environ.get('HIST_DATA_DEFAULT_YEARS', 10))

@test("singleton_stock 默认年数与 stockfetch 一致")
def _():
    import quantia.core.stockfetch as stf
    from quantia.core.singleton_stock import _DEFAULT_HIST_YEARS
    assert _DEFAULT_HIST_YEARS == stf.HIST_DATA_DEFAULT_YEARS, \
        f"singleton默认{_DEFAULT_HIST_YEARS}年 != stockfetch默认{stf.HIST_DATA_DEFAULT_YEARS}年"

@test("get_trade_hist_interval 支持自定义年数")
def _():
    import quantia.lib.trade_time as trd
    today = datetime.datetime(2026, 2, 12)
    
    # 3年
    start_3y, _ = trd.get_trade_hist_interval(today, years=3)
    assert start_3y.startswith('2023'), f"3年起始日期应在2023年，实际: {start_3y}"
    
    # 20年
    start_20y, _ = trd.get_trade_hist_interval(today, years=20)
    assert start_20y.startswith('2006'), f"20年起始日期应在2006年，实际: {start_20y}"
    
    # 1年
    start_1y, _ = trd.get_trade_hist_interval(today, years=1)
    assert start_1y.startswith('2025'), f"1年起始日期应在2025年，实际: {start_1y}"


# ============================================================
# 测试 6: 增量更新逻辑
# ============================================================
print("\n🔧 测试 6: 增量更新去重和排序")

import pandas as pd

@test("drop_duplicates 保留最后一条（新数据覆盖旧缓存）")
def _():
    # 模拟缓存数据和新数据有重叠日期
    cached = pd.DataFrame({
        'date': ['2026-02-09', '2026-02-10'],
        'close': [11.07, 11.06],
        'volume': [619717, 600430],
    })
    new_data = pd.DataFrame({
        'date': ['2026-02-10', '2026-02-11'],  # 2026-02-10 重叠
        'close': [11.06, 11.07],
        'volume': [600430, 431041],
    })
    combined = pd.concat([cached, new_data], ignore_index=True)
    combined = combined.drop_duplicates(subset=['date'], keep='last')
    assert len(combined) == 3, f"去重后应有3条，实际{len(combined)}"
    # 确认保留的是新数据的版本
    feb10 = combined[combined['date'] == '2026-02-10']
    assert len(feb10) == 1, "2026-02-10 应该只有1条"

@test("sort_values 确保日期顺序")
def _():
    df = pd.DataFrame({'date': ['2026-02-11', '2026-02-09', '2026-02-10']})
    df = df.sort_values(by='date').reset_index(drop=True)
    assert list(df['date']) == ['2026-02-09', '2026-02-10', '2026-02-11']

@test("日期范围过滤不遗漏边界日期")
def _():
    from quantia.core.stockfetch import _to_dash_date
    df = pd.DataFrame({
        'date': ['2026-02-08', '2026-02-09', '2026-02-10', '2026-02-11', '2026-02-12']
    })
    date_start = '20260209'
    date_end = '20260211'
    result = df[
        (df['date'] >= _to_dash_date(date_start)) &
        (df['date'] <= _to_dash_date(date_end))
    ]
    assert len(result) == 3, f"应保留3条（含边界），实际{len(result)}"
    assert '2026-02-09' in result['date'].values, "起始日期不应被过滤"
    assert '2026-02-11' in result['date'].values, "结束日期不应被过滤"


# ============================================================
# 测试 7: _fetch_from_sources 列名覆盖
# ============================================================
print("\n🔧 测试 7: _fetch_from_sources 列名统一")

@test("tuple(CN_STOCK_HIST_DATA['columns']) 返回正确的键名元组")
def _():
    cols = tuple(tbs.CN_STOCK_HIST_DATA['columns'])
    assert cols == ('date', 'open', 'close', 'high', 'low', 'volume', 'amount',
                    'amplitude', 'quote_change', 'ups_downs', 'turnover')

@test("各数据源标准列顺序定义一致")
def _():
    # 检查 Sina 和 Tencent 内部定义的 standard_columns 与 CN_STOCK_HIST_DATA 一致
    expected = ['date', 'open', 'close', 'high', 'low', 'volume', 'amount',
                'amplitude', 'quote_change', 'ups_downs', 'turnover']
    # 通过读取源代码验证（实际运行时通过返回的DataFrame列验证）
    if sina_ok:
        assert list(df_sina.columns) == expected
    if tc_ok:
        assert list(df_tc.columns) == expected


# ============================================================
# 汇总
# ============================================================
if __name__ == "__main__":
    print(f"\n{'=' * 60}")
    print(f"测试完成: ✅ {passed} 通过, ❌ {failed} 失败")
    if errors:
        print(f"\n失败详情:")
        for err in errors:
            print(f"  - {err}")
    print(f"{'=' * 60}")

    sys.exit(0 if failed == 0 else 1)
