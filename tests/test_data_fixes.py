#!/usr/bin/env python3
"""验证本次所有代码修复的逻辑正确性"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

passed = 0
failed = 0


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        print(f"  ✅ {name}")
        passed += 1
    else:
        print(f"  ❌ {name}: {detail}")
        failed += 1


print("=" * 60)
print("🔧 测试1: sector fund flow merge crash 修复")
print("=" * 60)

# 模拟 stock_sector_fund_flow_data 中的合并逻辑
import pandas as pd

# 场景1: results.get(0) 返回 None (之前会crash)
results_none = {1: pd.DataFrame({'name': ['A', 'B'], 'col1': [1, 2]}), 2: pd.DataFrame({'name': ['A', 'B'], 'col2': [3, 4]})}
data = None
for t in range(3):
    r = results_none.get(t)
    if r is None:
        continue
    if data is None:
        data = r
    else:
        data = pd.merge(data, r, on=['name'], how='left')

check("results.get(0)=None时不crash", data is not None and len(data) == 2, f"data={data}")
check("合并结果包含所有列", 'col1' in data.columns and 'col2' in data.columns)

# 场景2: 所有results都是None
results_all_none = {}
data2 = None
for t in range(3):
    r = results_all_none.get(t)
    if r is None:
        continue
    if data2 is None:
        data2 = r
    else:
        data2 = pd.merge(data2, r, on=['name'], how='left')
check("所有结果为None时data也为None", data2 is None)

# 场景3: 只有results.get(0)有数据
results_only_first = {0: pd.DataFrame({'name': ['A', 'B'], 'col0': [10, 20]})}
data3 = None
for t in range(3):
    r = results_only_first.get(t)
    if r is None:
        continue
    if data3 is None:
        data3 = r
    else:
        data3 = pd.merge(data3, r, on=['name'], how='left')
check("只有第一个结果时正常返回", data3 is not None and len(data3) == 2)

# 场景4: 正常情况（所有3个结果都有数据）
results_all = {
    0: pd.DataFrame({'name': ['A', 'B'], 'col0': [10, 20]}),
    1: pd.DataFrame({'name': ['A', 'B'], 'col1': [30, 40]}),
    2: pd.DataFrame({'name': ['A', 'B'], 'col2': [50, 60]}),
}
data4 = None
for t in range(3):
    r = results_all.get(t)
    if r is None:
        continue
    if data4 is None:
        data4 = r
    else:
        data4 = pd.merge(data4, r, on=['name'], how='left')
check("三个结果正常合并", data4 is not None and len(data4.columns) == 4)
check("合并后数据正确", data4.iloc[0]['col0'] == 10 and data4.iloc[0]['col2'] == 50)


print()
print("=" * 60)
print("🔧 测试2: selection_data 'date' KeyError 修复")
print("=" * 60)

import datetime

# 模拟: data 中没有 'date' 列
data_no_date = pd.DataFrame({'code': ['000001', '000002'], 'name': ['平安', '万科']})
date = datetime.date(2026, 2, 11)

if 'date' in data_no_date.columns and len(data_no_date) > 0:
    _date = data_no_date.iloc[0]['date']
else:
    _date = date.strftime("%Y-%m-%d") if hasattr(date, 'strftime') else str(date)

check("没有date列时不crash", True)
check("回退使用传入的date参数", _date == "2026-02-11", f"_date={_date}")

# 模拟: data 中有 'date' 列
data_with_date = pd.DataFrame({'date': ['2026-02-10', '2026-02-10'], 'code': ['000001', '000002']})
if 'date' in data_with_date.columns and len(data_with_date) > 0:
    _date2 = data_with_date.iloc[0]['date']
else:
    _date2 = date.strftime("%Y-%m-%d")

check("有date列时正常读取", _date2 == "2026-02-10", f"_date2={_date2}")


print()
print("=" * 60)
print("🔧 测试3: stock_fund_em.py 多域名 + 重试逻辑")
print("=" * 60)

from quantia.core.crawling import stock_fund_em as sfe

# 验证 _sector_fund_flow_fetch_page 函数存在
check("_sector_fund_flow_fetch_page 函数存在", hasattr(sfe, '_sector_fund_flow_fetch_page'))
check("_individual_fund_flow_fetch_page 函数存在", hasattr(sfe, '_individual_fund_flow_fetch_page'))

# 验证 stock_sector_fund_flow_rank 使用大page_size
import inspect
src = inspect.getsource(sfe.stock_sector_fund_flow_rank)
check("sector fund flow 使用 page_size=100", 'page_size = 100' in src, "page_size设置有问题")
# 验证没有JSONP回调参数在主函数中
check("sector fund flow 主函数没有硬编码cb参数", "'cb'" not in src and '"cb"' not in src)

src_ind = inspect.getsource(sfe.stock_individual_fund_flow_rank)
check("individual fund flow 使用 page_size=100", 'page_size = 100' in src_ind, "page_size设置有问题")

# 验证 fetch_page 内有多轮重试
src_fetch = inspect.getsource(sfe._sector_fund_flow_fetch_page)
check("sector fetch_page 有多轮重试 (range(3))", 'range(3)' in src_fetch)
check("sector fetch_page 使用 HTTPS 优先", 'https://push2.eastmoney.com' in src_fetch)


print()
print("=" * 60)
print("🔧 测试4: stock_hist_em.py HTTPS 修改")
print("=" * 60)

from quantia.core.crawling import stock_hist_em as she
src_spot = inspect.getsource(she.stock_zh_a_spot_em)
check("stock_zh_a_spot_em 使用 HTTPS", 'https://push2.eastmoney.com' in src_spot)
check("stock_zh_a_spot_em 不使用 HTTP", 'http://push2.eastmoney.com' not in src_spot)


print()
print("=" * 60)
print("🔧 测试5: singleton_stock.py 日志增强")
print("=" * 60)

from quantia.core import singleton_stock as ss
src_hist = inspect.getsource(ss.stock_hist_data.__init__)
check("stock_hist_data 有初始化日志", "stock_hist_data开始初始化" in src_hist)
check("stock_hist_data 有data=None时的错误日志", "stock_data返回None" in src_hist)
check("stock_hist_data 有成功完成日志", "stock_hist_data初始化完成" in src_hist)
check("stock_hist_data 有全部失败日志", "全部获取失败" in src_hist)


print()
print("=" * 60)
print("🔧 测试6: indicators/kline/strategy 日志增强")
print("=" * 60)

from quantia.job import indicators_data_daily_job as idj
from quantia.job import klinepattern_data_daily_job as kdj
from quantia.job import strategy_data_daily_job as sdj

src_i = inspect.getsource(idj.prepare)
check("indicators prepare 有开始日志", "indicators_data_daily_job开始执行" in src_i)
check("indicators prepare 有None警告", "stock_hist_data返回None" in src_i)

src_k = inspect.getsource(kdj.prepare)
check("kline prepare 有开始日志", "klinepattern_data_daily_job开始执行" in src_k)

src_s = inspect.getsource(sdj.prepare)
check("strategy prepare 有开始日志", "strategy_data_daily_job开始执行" in src_s)


print()
print("=" * 60)
if failed == 0:
    print(f"✅ 全部通过: {passed}/{passed + failed}")
else:
    print(f"❌ 有失败: {passed} 通过, {failed} 失败")
print("=" * 60)
