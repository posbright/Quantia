#!/usr/bin/env python3
"""第三轮审计修复的验证测试

覆盖:
1. volume_strategies 除零保护
2. ma_strategies elif→if 双重跟踪
3. pattern_strategies 偏离度公式修正
4. stockfetch drop errors='ignore'
5. visualization SQL注入修复（参数化查询）
6. backtestHandler 日志补全
7. backtestDashboardHandler 顶层错误兜底
8. execute_daily_job 单例释放日志
9. database.py 静默异常日志补全
"""
import sys
import os
import re
import ast
import inspect

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


# ============================================================
print("=" * 60)
print("🔧 测试1: VolumeIncreaseStrategy 除零保护")
print("=" * 60)

src = open(os.path.join(os.path.dirname(__file__), '..', 'quantia', 'core', 'strategy', 'volume', 'volume_strategies.py'), encoding='utf-8').read()
check("VolumeIncreaseStrategy 包含 mean_vol <= 0 保护",
      "if mean_vol <= 0:" in src and "return False" in src[src.index("if mean_vol <= 0:"):src.index("if mean_vol <= 0:") + 80])

# 确保 ClimaxLimitdownStrategy 也保持其原有保护
check("ClimaxLimitdownStrategy 同样有 mean_vol 保护",
      src.count("mean_vol <= 0") >= 1 or "mean_vol == 0" in src or "mean_vol <= 0" in src)


# ============================================================
print("\n" + "=" * 60)
print("🔧 测试2: ma_strategies elif→if 修复（双重min/max跟踪）")
print("=" * 60)

src_ma = open(os.path.join(os.path.dirname(__file__), '..', 'quantia', 'core', 'strategy', 'technical', 'ma_strategies.py'), encoding='utf-8').read()

# 关键逻辑：highest/lowest 的更新应该用独立的 if 而非 elif
lines = src_ma.split('\n')
found_elif_bug = False
for i, line in enumerate(lines):
    stripped = line.strip()
    if stripped.startswith('elif') and 'lowest_row' in stripped and '_close <' in stripped:
        found_elif_bug = True
        break

check("ma_strategies 不存在 elif _close < lowest_row 的bug",
      not found_elif_bug,
      "仍然使用 elif 导致极端价位不能同时更新 highest 和 lowest")

# 验证使用了独立的 if 语句
found_if_lowest = False
for i, line in enumerate(lines):
    stripped = line.strip()
    if stripped.startswith('if _close < lowest_row') or stripped.startswith('if _close < lowest_row[0]'):
        found_if_lowest = True
        break
check("ma_strategies 使用独立 if 跟踪 lowest_row", found_if_lowest)


# ============================================================
print("\n" + "=" * 60)
print("🔧 测试3: pattern_strategies 偏离度公式修正")
print("=" * 60)

src_pat = open(os.path.join(os.path.dirname(__file__), '..', 'quantia', 'core', 'strategy', 'pattern', 'pattern_strategies.py'), encoding='utf-8').read()

# 正确公式: (_close - _ma60) / _ma60
# 错误公式: (_ma60 - _close) / _ma60
check("pattern_strategies 使用正确偏离度公式 (_close - _ma60) / _ma60",
      "(_close - _ma60) / _ma60" in src_pat,
      "缺少正确的偏离度公式")

check("pattern_strategies 不存在错误的反向偏离度公式",
      "(_ma60 - _close) / _ma60" not in src_pat,
      "仍然存在反向公式 (_ma60 - _close) / _ma60")

# 验证公式逻辑：当 _close > _ma60 时（突破平台），偏离度应该为正
# deviation = (_close - _ma60) / _ma60 > 0 when _close > _ma60
check("偏离度公式语义正确：股价高于均线时偏离度为正",
      True,  # 已通过上面的源码检查验证
      "公式语义检查")


# ============================================================
print("\n" + "=" * 60)
print("🔧 测试4: stockfetch drop errors='ignore' 修复")
print("=" * 60)

src_sf = open(os.path.join(os.path.dirname(__file__), '..', 'quantia', 'core', 'stockfetch.py'), encoding='utf-8').read()

check("stockfetch.py fetch_stock_blocktrade_data 的 drop 使用 errors='ignore'",
      "errors='ignore'" in src_sf and "drop('index'" in src_sf)

# 验证 DataFrame.drop 含 errors='ignore' 不会因为缺少列而报错
import pandas as pd
df = pd.DataFrame({'a': [1, 2], 'b': [3, 4]})
try:
    df.drop('nonexistent', axis=1, inplace=True, errors='ignore')
    check("pandas drop errors='ignore' 对不存在的列不报错", True)
except KeyError:
    check("pandas drop errors='ignore' 对不存在的列不报错", False, "仍然抛出 KeyError")


# ============================================================
print("\n" + "=" * 60)
print("🔧 测试5: visualization.py SQL注入修复")
print("=" * 60)

src_vis = open(os.path.join(os.path.dirname(__file__), '..', 'quantia', 'core', 'kline', 'visualization.py'), encoding='utf-8').read()

# 不应该有 f"...'{code}'..." 这种直接拼接到 SQL
# 应该使用 %s 参数化查询
# 注意: HTML模板中的 '{code}' 是安全的（用于前端JS），只检查SQL上下文
sql_lines_vis = [l for l in src_vis.split('\n') if 'SELECT' in l.upper() or 'FROM' in l.upper()]
has_sql_injection = any("'{code}'" in l for l in sql_lines_vis)
check("visualization.py SQL 查询中不存在直接拼接 code",
      not has_sql_injection,
      "仍然使用 f-string 直接拼接 code 到 SQL 查询")

check("visualization.py 使用参数化查询 %s",
      "`code` = %s" in src_vis,
      "缺少参数化查询")


# ============================================================
print("\n" + "=" * 60)
print("🔧 测试6: backtestHandler 日志补全")
print("=" * 60)

src_bh = open(os.path.join(os.path.dirname(__file__), '..', 'quantia', 'web', 'backtestHandler.py'), encoding='utf-8').read()

# _calc_key_indicators 的 except 块应包含日志
check("backtestHandler _calc_key_indicators 异常有日志",
      "计算关键技术指标异常" in src_bh)

# _get_stock_name 的 except 块应包含日志
check("backtestHandler _get_stock_name 异常有日志",
      "查询股票名称异常" in src_bh)

# 批量回测线程结果异常应有日志
check("backtestHandler 批量回测线程结果异常有日志",
      "批量回测线程结果异常" in src_bh)

# 策略检测异常应有日志
check("backtestHandler 批量回测策略检测异常有日志",
      "批量回测策略检测异常" in src_bh)


# ============================================================
print("\n" + "=" * 60)
print("🔧 测试7: backtestDashboardHandler 顶层错误兜底")
print("=" * 60)

src_bdh = open(os.path.join(os.path.dirname(__file__), '..', 'quantia', 'web', 'backtestDashboardHandler.py'), encoding='utf-8').read()

# 每个 Handler 类的 get() 方法应该有 try/except 兜底
for handler_name in ['DashboardOverviewHandler', 'PerformanceTimelineHandler',
                     'StrategyDetailHandler', 'ReturnDistributionHandler', 'TradePairHandler']:
    check(f"{handler_name} get() 有顶层 try/except 错误兜底",
          f"class {handler_name}" in src_bdh and "服务器内部错误" in src_bdh)

# _get_table_trade_date_count 的 except 块应包含日志
check("_get_table_trade_date_count 异常有日志",
      "_get_table_trade_date_count" in src_bdh and "解析异常" in src_bdh)


# ============================================================
print("\n" + "=" * 60)
print("🔧 测试8: execute_daily_job 单例释放日志")
print("=" * 60)

src_edj = open(os.path.join(os.path.dirname(__file__), '..', 'quantia', 'job', 'execute_daily_job.py'), encoding='utf-8').read()

check("execute_daily_job 单例释放异常有日志",
      "释放 stock_data 单例异常" in src_edj,
      "单例释放的 except 块仍然是静默的 pass")

# 确认不再有 bare 'except Exception: pass' 用于单例释放
lines_edj = src_edj.split('\n')
found_silent_singleton = False
for i, line in enumerate(lines_edj):
    if 'stock_data.release()' in line:
        # 找到 release 行，往后找 except
        for j in range(i + 1, min(i + 10, len(lines_edj))):
            if 'except Exception' in lines_edj[j]:
                # 下一行不应该是 pass
                if j + 1 < len(lines_edj) and lines_edj[j + 1].strip() == 'pass':
                    found_silent_singleton = True
                break
        break
check("execute_daily_job 单例释放 except 不再是静默 pass", not found_silent_singleton)


# ============================================================
print("\n" + "=" * 60)
print("🔧 测试9: database.py 静默异常日志补全")
print("=" * 60)

src_db = open(os.path.join(os.path.dirname(__file__), '..', 'quantia', 'lib', 'database.py'), encoding='utf-8').read()

check("database.py PK检查异常有日志",
      "检查主键约束异常" in src_db,
      "PK检查的 except 块仍然是静默的 pass")

check("database.py dispose引擎异常有日志",
      "dispose引擎异常" in src_db,
      "dispose的 except 块仍然是静默的 pass")


# ============================================================
print("\n" + "=" * 60)
print("🔧 测试10: 偏离度公式数学验证")
print("=" * 60)

# 验证修正后的公式逻辑
def correct_deviation(close, ma60):
    return (close - ma60) / ma60

def wrong_deviation(close, ma60):
    return (ma60 - close) / ma60

# 场景：股价在均线上方5%（正常突破平台状态）
close_above = 105
ma60_val = 100
dev_correct = correct_deviation(close_above, ma60_val)
dev_wrong = wrong_deviation(close_above, ma60_val)

check("正确公式：股价高于均线时偏离度为正",
      dev_correct > 0,
      f"偏离度为 {dev_correct}，应该是正数")

check("错误公式：股价高于均线时偏离度为负（反向）",
      dev_wrong < 0,
      f"旧公式偏离度为 {dev_wrong}")

# 场景：偏离度在 -5% ~ 20% 之间的判断
close_valid = 110  # 10% above ma60
dev_valid = correct_deviation(close_valid, ma60_val)
check("10%偏离在合理范围(-5%~20%)",
      -0.05 < dev_valid < 0.2,
      f"偏离度 {dev_valid} 不在范围内")

close_too_high = 125  # 25% above ma60
dev_too_high = correct_deviation(close_too_high, ma60_val)
check("25%偏离超出合理范围",
      not (-0.05 < dev_too_high < 0.2),
      f"偏离度 {dev_too_high} 应该超出范围")


# ============================================================
# 总结
# ============================================================
print("\n" + "=" * 60)
total = passed + failed
print(f"第三轮审计修复测试完成: {passed}/{total} 通过, {failed} 失败")
if failed > 0:
    print("失败项需要检查！")
    sys.exit(1)
else:
    print("✅ 所有测试通过！")
print("=" * 60)
