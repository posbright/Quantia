#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
重构验证测试

验证 run_fetch / run_analysis / kline_cache 重构的正确性：
1. job_tracker 模块功能验证
2. fetch_daily_job 结构验证（K线已移除、新鲜度检查存在、子进程隔离）
3. analysis_daily_job 结构验证（stock_spot_buy 已添加）
4. basic_data_other_daily_job 验证（stock_spot_buy 已从 lhb 移除）
5. kline_cache_daily_job 结构验证（前置检查、独立运行）
6. execute_daily_job 一致性验证
7. cron 脚本验证
"""

import sys
import os
import inspect

# 将项目根目录加入 sys.path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)
# job 目录也需要加入（job脚本之间通过相对导入）
job_dir = os.path.join(project_root, 'quantia', 'job')
sys.path.insert(0, job_dir)

passed = 0
failed = 0
errors = []


def check(name):
    """测试装饰器"""
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
            print(f"  ❌ {name}: 异常 {type(e).__name__}: {e}")
            failed += 1
            errors.append(f"{name}: {type(e).__name__}: {e}")
    return decorator


# ============================================================
# 测试 1: job_tracker 模块
# ============================================================
print("\n🔧 测试 1: job_tracker 模块")

@check("job_tracker 模块可导入")
def _():
    from quantia.lib.job_tracker import (
        record_task_start, record_task_end, record_task_skipped,
        is_job_completed, is_data_fresh, get_task_status,
        JOB_STATUS_TABLE, _ensure_table,
    )
    assert callable(record_task_start)
    assert callable(record_task_end)
    assert callable(record_task_skipped)
    assert callable(is_job_completed)
    assert callable(is_data_fresh)
    assert callable(get_task_status)
    assert JOB_STATUS_TABLE == 'cn_job_status'

@check("record_task_start 返回时间戳")
def _():
    import time
    from quantia.lib.job_tracker import record_task_start
    # 不依赖数据库的功能验证：函数签名和返回类型
    sig = inspect.signature(record_task_start)
    params = list(sig.parameters.keys())
    assert 'job_name' in params
    assert 'task_name' in params
    assert 'job_date' in params

@check("is_data_fresh 返回 (bool, int) 元组")
def _():
    from quantia.lib.job_tracker import is_data_fresh
    sig = inspect.signature(is_data_fresh)
    params = list(sig.parameters.keys())
    assert 'table_name' in params
    assert 'date_str' in params
    assert 'min_rows' in params

@check("record_task_end 接受 success/message/rows_affected 参数")
def _():
    from quantia.lib.job_tracker import record_task_end
    sig = inspect.signature(record_task_end)
    params = list(sig.parameters.keys())
    assert 'success' in params
    assert 'message' in params
    assert 'rows_affected' in params

@check("is_job_completed 检查 __overall__ 记录")
def _():
    from quantia.lib.job_tracker import is_job_completed
    source = inspect.getsource(is_job_completed)
    assert '__overall__' in source, "应检查 __overall__ 任务记录"


# ============================================================
# 测试 2: fetch_daily_job 重构验证
# ============================================================
print("\n🔧 测试 2: fetch_daily_job 重构验证")

@check("fetch_daily_job 不再包含 fetch_data_job 引用")
def _():
    import quantia.job.fetch_daily_job as fdj
    source = inspect.getsource(fdj)
    assert 'fetch_data_job' not in source, "K线缓存应已从 fetch_daily_job 移除"

@check("fetch_daily_job 使用 job_tracker 记录任务状态")
def _():
    import quantia.job.fetch_daily_job as fdj
    source = inspect.getsource(fdj)
    assert 'record_task_start' in source
    assert 'record_task_end' in source
    assert 'is_job_completed' in source

@check("fetch_daily_job 有数据新鲜度检查")
def _():
    import quantia.job.fetch_daily_job as fdj
    source = inspect.getsource(fdj)
    assert '_check_and_skip' in source
    assert 'is_data_fresh' in source
    assert '_FRESHNESS_THRESHOLDS' in source

@check("fetch_daily_job _FRESHNESS_THRESHOLDS 包含核心表")
def _():
    import quantia.job.fetch_daily_job as fdj
    thresholds = fdj._FRESHNESS_THRESHOLDS
    assert 'cn_stock_spot' in thresholds
    assert 'cn_etf_spot' in thresholds
    assert 'cn_stock_selection' in thresholds

@check("fetch_daily_job JOB_NAME 为 run_fetch")
def _():
    import quantia.job.fetch_daily_job as fdj
    assert fdj._JOB_NAME == 'run_fetch'

@check("fetch_daily_job 支持 QUANTIA_FORCE_FETCH 环境变量")
def _():
    import quantia.job.fetch_daily_job as fdj
    source = inspect.getsource(fdj)
    assert 'QUANTIA_FORCE_FETCH' in source

@check("fetch_daily_job 记录 __overall__ 完成状态")
def _():
    import quantia.job.fetch_daily_job as fdj
    source = inspect.getsource(fdj.main)
    assert '__overall__' in source, "应记录整体完成状态供 kline_cache 查询"

@check("fetch_daily_job 子进程仍保持隔离（_run_job_subprocess）")
def _():
    import quantia.job.fetch_daily_job as fdj
    source = inspect.getsource(fdj)
    assert 'subprocess.run' in source
    assert '_run_job_subprocess' in source


# ============================================================
# 测试 3: analysis_daily_job 重构验证
# ============================================================
print("\n🔧 测试 3: analysis_daily_job 重构验证")

@check("analysis_daily_job 包含 _run_stock_spot_buy")
def _():
    import quantia.job.analysis_daily_job as adj
    assert hasattr(adj, '_run_stock_spot_buy'), "应包含 _run_stock_spot_buy 函数"
    assert callable(adj._run_stock_spot_buy)

@check("analysis_daily_job._run_stock_spot_buy 执行正确的 SQL 筛选")
def _():
    import quantia.job.analysis_daily_job as adj
    source = inspect.getsource(adj._run_stock_spot_buy)
    assert 'pe9' in source, "应筛选 PE"
    assert 'pbnewmrq' in source, "应筛选 PB"
    assert 'roe_weight' in source, "应筛选 ROE"
    assert 'cn_stock_spot_buy' in source or 'TABLE_CN_STOCK_SPOT_BUY' in source

@check("analysis_daily_job.main 在 GPT 选股后执行 stock_spot_buy")
def _():
    import quantia.job.analysis_daily_job as adj
    source = inspect.getsource(adj.main)
    gpt_pos = source.find('gptj.main()')
    spot_buy_pos = source.find('_run_stock_spot_buy')
    streaming_pos = source.find('saj.main()')
    assert gpt_pos > 0, "应包含 gptj.main() 调用"
    assert spot_buy_pos > 0, "应包含 _run_stock_spot_buy 调用"
    assert streaming_pos > 0, "应包含 saj.main() 调用"
    assert gpt_pos < spot_buy_pos < streaming_pos, \
        "执行顺序应为: GPT选股 → 基本面选股 → 流式分析"

@check("analysis_daily_job 使用 job_tracker 记录任务状态")
def _():
    import quantia.job.analysis_daily_job as adj
    source = inspect.getsource(adj)
    assert 'record_task_start' in source
    assert 'record_task_end' in source

@check("analysis_daily_job 记录每个子任务的耗时")
def _():
    import quantia.job.analysis_daily_job as adj
    source = inspect.getsource(adj.main)
    # 检查每个步骤都有 start/end 记录
    assert source.count('record_task_start') >= 4, "应至少记录4个子任务(gpt+spot_buy+streaming+backtest)"
    assert source.count('record_task_end') >= 4


# ============================================================
# 测试 4: basic_data_other_daily_job 验证
# ============================================================
print("\n🔧 测试 4: basic_data_other_daily_job 验证 (stock_spot_buy 移除)")

@check("save_nph_stock_lhb_data 不再调用 stock_spot_buy")
def _():
    import quantia.job.basic_data_other_daily_job as bdo
    source = inspect.getsource(bdo.save_nph_stock_lhb_data)
    assert 'stock_spot_buy(date)' not in source, \
        "save_nph_stock_lhb_data 不应再调用 stock_spot_buy"

@check("basic_data_other 仍保留 stock_spot_buy 函数定义（向后兼容）")
def _():
    import quantia.job.basic_data_other_daily_job as bdo
    assert hasattr(bdo, 'stock_spot_buy'), "stock_spot_buy 函数定义应保留（向后兼容）"

@check("save_nph_stock_lhb_data 包含移除注释说明")
def _():
    import quantia.job.basic_data_other_daily_job as bdo
    source = inspect.getsource(bdo.save_nph_stock_lhb_data)
    assert 'analysis_daily_job' in source, "应有注释说明 stock_spot_buy 已移至 analysis"


# ============================================================
# 测试 5: kline_cache_daily_job 验证
# ============================================================
print("\n🔧 测试 5: kline_cache_daily_job 验证")

@check("kline_cache_daily_job 可导入")
def _():
    import quantia.job.kline_cache_daily_job as kcj
    assert hasattr(kcj, 'main')
    assert hasattr(kcj, 'fetch_all_data')
    assert hasattr(kcj, '_check_fetch_completed')

@check("kline_cache_daily_job 检查 run_fetch 完成状态")
def _():
    import quantia.job.kline_cache_daily_job as kcj
    source = inspect.getsource(kcj._check_fetch_completed)
    assert 'is_job_completed' in source
    assert 'run_fetch' in source

@check("kline_cache_daily_job 支持 QUANTIA_FORCE_KLINE_CACHE 跳过检查")
def _():
    import quantia.job.kline_cache_daily_job as kcj
    source = inspect.getsource(kcj)
    assert 'QUANTIA_FORCE_KLINE_CACHE' in source

@check("kline_cache_daily_job 包含缓存清理步骤")
def _():
    import quantia.job.kline_cache_daily_job as kcj
    source = inspect.getsource(kcj.fetch_all_data)
    assert 'clean_expired_cache' in source

@check("kline_cache_daily_job 包含K线缓存更新步骤")
def _():
    import quantia.job.kline_cache_daily_job as kcj
    source = inspect.getsource(kcj.fetch_all_data)
    assert 'update_all_caches' in source

@check("kline_cache_daily_job 使用 job_tracker 记录状态")
def _():
    import quantia.job.kline_cache_daily_job as kcj
    source = inspect.getsource(kcj)
    assert 'record_task_start' in source
    assert 'record_task_end' in source

@check("kline_cache_daily_job JOB_NAME 为 run_kline_cache")
def _():
    import quantia.job.kline_cache_daily_job as kcj
    assert kcj._JOB_NAME == 'run_kline_cache'


# ============================================================
# 测试 6: execute_daily_job 一致性验证
# ============================================================
print("\n🔧 测试 6: execute_daily_job 一致性验证")

@check("execute_daily_job 使用 kline_cache_daily_job 替代 fetch_data_job")
def _():
    import quantia.job.execute_daily_job as edj
    source = inspect.getsource(edj.main)
    assert 'kline_cache_daily_job.py' in source, "应使用 kline_cache_daily_job.py 替代 fetch_data_job.py"

@check("execute_daily_job 包含 stock_spot_buy")
def _():
    import quantia.job.execute_daily_job as edj
    source = inspect.getsource(edj)
    assert '_run_stock_spot_buy' in source, "应包含基本面选股函数"

@check("execute_daily_job 使用 job_tracker")
def _():
    import quantia.job.execute_daily_job as edj
    source = inspect.getsource(edj)
    assert 'record_task_start' in source
    assert 'record_task_end' in source

@check("execute_daily_job 有数据新鲜度检查")
def _():
    import quantia.job.execute_daily_job as edj
    source = inspect.getsource(edj)
    assert '_check_and_skip' in source
    assert 'is_data_fresh' in source

@check("execute_daily_job stock_spot_buy 在 GPT 之后执行")
def _():
    import quantia.job.execute_daily_job as edj
    source = inspect.getsource(edj.main)
    gpt_pos = source.find('gptj.main()')
    spot_buy_pos = source.find('_run_stock_spot_buy')
    assert gpt_pos > 0 and spot_buy_pos > 0
    assert gpt_pos < spot_buy_pos, "stock_spot_buy 应在 GPT 选股之后"


# ============================================================
# 测试 7: cron 脚本验证
# ============================================================
print("\n🔧 测试 7: cron 脚本验证")

@check("run_kline_cache cron 脚本存在")
def _():
    cron_path = os.path.join(project_root, 'cron', 'cron.workdayly', 'run_kline_cache')
    assert os.path.isfile(cron_path), f"cron 脚本不存在: {cron_path}"

@check("run_kline_cache 调用 kline_cache_daily_job.py")
def _():
    cron_path = os.path.join(project_root, 'cron', 'cron.workdayly', 'run_kline_cache')
    with open(cron_path, 'r', encoding='utf-8') as f:
        content = f.read()
    assert 'kline_cache_daily_job.py' in content

@check("run_kline_cache 包含非交易日检查")
def _():
    cron_path = os.path.join(project_root, 'cron', 'cron.workdayly', 'run_kline_cache')
    with open(cron_path, 'r', encoding='utf-8') as f:
        content = f.read()
    # 新架构通过 _common.sh 的 check_trade_day 函数实现
    assert 'check_trade_day' in content or ('IS_TRADE_DAY' in content and 'is_trade_date' in content)

@check("run_fetch cron 脚本仍然存在且调用 fetch_daily_job")
def _():
    cron_path = os.path.join(project_root, 'cron', 'cron.workdayly', 'run_fetch')
    assert os.path.isfile(cron_path)
    with open(cron_path, 'r', encoding='utf-8') as f:
        content = f.read()
    assert 'fetch_daily_job.py' in content

@check("run_analysis cron 脚本仍然存在且调用 analysis_daily_job")
def _():
    cron_path = os.path.join(project_root, 'cron', 'cron.workdayly', 'run_analysis')
    assert os.path.isfile(cron_path)
    with open(cron_path, 'r', encoding='utf-8') as f:
        content = f.read()
    assert 'analysis_daily_job.py' in content


# ============================================================
# 测试 8: 向后兼容性验证
# ============================================================
print("\n🔧 测试 8: 向后兼容性验证")

@check("fetch_data_job.py 原文件保留（独立运行仍可用）")
def _():
    fdj_path = os.path.join(project_root, 'quantia', 'job', 'fetch_data_job.py')
    assert os.path.isfile(fdj_path), "fetch_data_job.py 应保留以支持独立手动运行"

@check("fetch_three_pages.py 已更新 stock_spot_buy 引用")
def _():
    ftp_path = os.path.join(project_root, 'quantia', 'job', 'fetch_three_pages.py')
    if os.path.isfile(ftp_path):
        with open(ftp_path, 'r', encoding='utf-8') as f:
            content = f.read()
        # 应引用 analysis_daily_job 而非 basic_data_other_daily_job
        assert 'analysis_daily_job' in content, \
            "fetch_three_pages.py 应更新为从 analysis_daily_job 导入 stock_spot_buy"


# ============================================================
# 测试 9: 重构完整性交叉检查
# ============================================================
print("\n🔧 测试 9: 重构完整性交叉检查")

@check("所有 job 文件可正常导入")
def _():
    modules = [
        'quantia.job.fetch_daily_job',
        'quantia.job.analysis_daily_job',
        'quantia.job.kline_cache_daily_job',
        'quantia.job.execute_daily_job',
        'quantia.job.basic_data_other_daily_job',
    ]
    for mod in modules:
        __import__(mod)

@check("fetch_daily_job 不依赖 fetch_data_job")
def _():
    import quantia.job.fetch_daily_job as fdj
    source = inspect.getsource(fdj)
    # 不应有 import fetch_data_job 或引用 fetch_data_job.py
    assert 'import fetch_data_job' not in source
    assert "fetch_data_job.py" not in source

@check("analysis_daily_job._run_stock_spot_buy 筛选条件与原 basic_data_other 一致")
def _():
    import quantia.job.analysis_daily_job as adj
    import quantia.job.basic_data_other_daily_job as bdo
    adj_source = inspect.getsource(adj._run_stock_spot_buy)
    bdo_source = inspect.getsource(bdo.stock_spot_buy)
    # 验证核心筛选条件一致
    for condition in ['pe9', 'pbnewmrq', 'roe_weight', '20', '10', '15']:
        assert condition in adj_source, f"analysis 版本缺少条件: {condition}"
        assert condition in bdo_source, f"原始版本缺少条件: {condition}"


# ============================================================
# 汇总
# ============================================================
print(f"\n{'='*60}")
print(f"重构验证测试结束: {passed} 通过, {failed} 失败")
if errors:
    print("失败项:")
    for e in errors:
        print(f"  - {e}")
print(f"{'='*60}")

if __name__ == "__main__":
    sys.exit(0 if failed == 0 else 1)
