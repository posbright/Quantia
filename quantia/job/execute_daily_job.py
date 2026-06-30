#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
完整每日任务（获取 + 分析，服务器回退模式）

执行流程：
Phase 0: 初始化数据库
Phase 1: 轻量级数据入库（行情 + 选股 + 扩展数据 + 收盘后数据）
Phase 2: K线缓存批量更新（内存密集型，独立子进程）
Phase 3: 数据分析（GPT选股 + 基本面选股 + 流式分析）
Phase 4: 回测

设计原则：
- 轻量任务优先完成，确保关键数据安全入库
- K线缓存以独立子进程运行，OOM 不影响已入库数据
- 每个阶段/子任务记录开始/结束日志及耗时
- 分析阶段支持"已完成跳过"（本地优先模式）
- 作业状态通过 cn_job_status 表追踪
"""

import time
import datetime
import logging
import gc
import os.path
import sys

# 在项目运行时，临时将项目路径添加到环境变量
cpath_current = os.path.dirname(os.path.dirname(__file__))
cpath = os.path.abspath(os.path.join(cpath_current, os.pardir))
sys.path.append(cpath)
try:
    from quantia.lib.log_config import setup_logging
    setup_logging('execute')
except Exception:
    # 兼容旧环境：log_config 不可用时降级为 basicConfig
    log_path = os.path.join(cpath_current, 'log')
    os.makedirs(log_path, exist_ok=True)
    logging.basicConfig(
        format='%(asctime)s [%(levelname)s] %(message)s',
        filename=os.path.join(log_path, 'stock_execute_job.log'),
        level=logging.INFO,
    )
import init_job as bj
import subprocess
import basic_data_daily_job as hdj
import streaming_analysis_job as saj
import backtest_data_daily_job as bdj
import selection_data_daily_job as sddj
import gpt_value_data_job as gptj
import quantia.lib.database as mdb
import quantia.lib.trade_time as trd
from quantia.lib.job_tracker import (
    record_task_start, record_task_end, record_task_skipped,
    is_data_fresh,
)
import quantia.lib.envconfig as _cfg

__author__ = 'Quantia'
__date__ = '2026/03/12'

# 分析数据跳过阈值（同 analysis_daily_job.py）
ANALYSIS_DONE_THRESHOLD = _cfg.get_int('QUANTIA_ANALYSIS_DONE_THRESHOLD', 1000)

_JOB_DIR = os.path.dirname(os.path.abspath(__file__))
_JOB_NAME = 'run_workdayly'

# 子进程超时（秒）
_JOB_TIMEOUT = _cfg.get_int('QUANTIA_JOB_TIMEOUT', 1800)
_KLINE_JOB_TIMEOUT = _cfg.get_int('QUANTIA_KLINE_JOB_TIMEOUT', 36000)

# 数据新鲜度阈值
_FRESHNESS_THRESHOLDS = {
    'cn_stock_spot': _cfg.get_int('QUANTIA_FRESH_STOCK_SPOT', 3000),
    'cn_stock_selection': _cfg.get_int('QUANTIA_FRESH_SELECTION', 100),
}


def _run_job_subprocess(script_name, label, timeout=_JOB_TIMEOUT):
    """以独立子进程运行 job 脚本，防止 OOM 波及当前进程。

    Returns:
        bool: True 表示子进程正常退出（exit code 0），False 表示失败/超时/异常。
    """
    script_path = os.path.join(_JOB_DIR, script_name)
    try:
        logging.info(f"{label}: 启动子进程 {script_name}")
        result = subprocess.run(
            [sys.executable, script_path],
            env={**os.environ, 'PYTHONPATH': cpath},
            timeout=timeout,
        )
        if result.returncode != 0:
            logging.warning(f"{label}: 子进程退出码 {result.returncode}（可能 OOM 被杀）")
            return False
        else:
            logging.info(f"{label}: 子进程执行成功")
            return True
    except subprocess.TimeoutExpired:
        logging.error(f"{label}: 子进程执行超时（{timeout}秒）")
        return False
    except Exception as e:
        logging.error(f"{label}: 子进程启动异常", exc_info=True)
        return False


def _is_analysis_done(run_date_nph=None):
    """
    检查今日分析数据是否已由其他节点完成。
    用于 execute_daily_job 中跳过 Phase 3/4（分析+回测），
    但仍执行 Phase 0/1/2（初始化+轻量数据+K线缓存）。
    可通过 QUANTIA_FORCE_ANALYSIS=1 强制执行。

    参数：
        run_date_nph: 由调用方传入，避免重复调用 get_trade_date_last 产生 TOCTOU 时间竞争
    """
    if _cfg.get_bool('QUANTIA_FORCE_ANALYSIS', False):
        return False
    try:
        if run_date_nph is None:
            _, run_date_nph = trd.get_trade_date_last()
        date_str = run_date_nph.strftime("%Y-%m-%d")
        table_name = 'cn_stock_indicators'
        if not mdb.checkTableIsExist(table_name):
            return False
        row = mdb.executeSqlFetch(
            f"SELECT COUNT(*) FROM `{table_name}` WHERE `date` = %s",
            (date_str,)
        )
        count = row[0][0] if row else 0
        if count >= ANALYSIS_DONE_THRESHOLD:
            logging.info(
                f"分析数据已存在（{count} 条 >= {ANALYSIS_DONE_THRESHOLD}），"
                f"Phase 3/4 将跳过。设置 QUANTIA_FORCE_ANALYSIS=1 可强制执行。"
            )
            return True
        return False
    except Exception as e:
        logging.warning(f"检查分析完成状态异常（将继续执行）：{e}")
        return False


def _check_and_skip(table_name, date_str, task_label):
    """检查 API 数据新鲜度，决定是否跳过该任务。

    跳过条件（同时满足）：
    1. 未设置 QUANTIA_FORCE_FETCH=1
    2. 当前时间已过结算时间（默认 18:00），API 数据不再变化
    3. 表中当日数据行数 >= 阈值
    """
    if _cfg.get_bool('QUANTIA_FORCE_FETCH', False):
        return False

    # API 数据仅在结算时间后（默认 18:00）才可信赖跳过
    if not trd.is_post_settlement(date_str):
        logging.info(f"[{task_label}] 尚未过结算时间，需更新 API 数据")
        return False

    threshold = _FRESHNESS_THRESHOLDS.get(table_name, 1)
    fresh, count = is_data_fresh(table_name, date_str, threshold)
    if fresh:
        logging.info(f"[{task_label}] 数据已完整且已过结算时间（{table_name}: {count} 条 >= {threshold}），跳过")
        return True
    return False


def _run_stock_spot_buy(date):
    """基本面选股：筛选 PE<20、PB<10、ROE>=15% 的股票。

    优先从 cn_stock_selection（东方财富选股器）筛选，PE/ROE 更可靠；
    降级从 cn_stock_spot（行情数据）筛选。
    筛出的股票代码再从 cn_stock_spot 取完整行情数据写入 cn_stock_spot_buy。
    """
    import pandas as pd
    import quantia.core.tablestructure as tbs

    try:
        date_str = date.strftime("%Y-%m-%d") if hasattr(date, 'strftime') else str(date)
        qualified_codes = None

        # 优先从 cn_stock_selection 筛选
        sel_table = tbs.TABLE_CN_STOCK_SELECTION['name']
        if mdb.checkTableIsExist(sel_table):
            sel_sql = (f'SELECT `code` FROM `{sel_table}` WHERE `date` = %s '
                       f'AND `pe9` > 0 AND `pe9` <= 20 AND `pbnewmrq` <= 10 AND `roe_weight` >= 15')
            sel_data = pd.read_sql(sql=sel_sql, con=mdb.engine(), params=(date_str,))
            if len(sel_data) > 0:
                qualified_codes = set(sel_data['code'].values)
                logging.info(f"基本面选股：从 cn_stock_selection 筛出 {len(qualified_codes)} 只")

        # 降级从 cn_stock_spot
        if qualified_codes is None:
            spot_table = tbs.TABLE_CN_STOCK_SPOT['name']
            if mdb.checkTableIsExist(spot_table):
                spot_sql = (f'SELECT `code` FROM `{spot_table}` WHERE `date` = %s '
                            f'AND `pe9` > 0 AND `pe9` <= 20 AND `pbnewmrq` <= 10 AND `roe_weight` >= 15')
                spot_data = pd.read_sql(sql=spot_sql, con=mdb.engine(), params=(date_str,))
                if len(spot_data) > 0:
                    qualified_codes = set(spot_data['code'].values)
                    logging.info(f"基本面选股：降级从 cn_stock_spot 筛出 {len(qualified_codes)} 只")

        if not qualified_codes:
            return

        # 从 cn_stock_spot 取完整行情数据
        spot_table = tbs.TABLE_CN_STOCK_SPOT['name']
        if not mdb.checkTableIsExist(spot_table):
            return

        placeholders = ','.join(['%s'] * len(qualified_codes))
        data = pd.read_sql(
            f'SELECT * FROM `{spot_table}` WHERE `date` = %s AND `code` IN ({placeholders})',
            mdb.engine(), params=(date_str, *qualified_codes))
        data = data.drop_duplicates(subset="code", keep="last")
        if len(data.index) == 0:
            return

        table_name = tbs.TABLE_CN_STOCK_SPOT_BUY['name']
        if mdb.checkTableIsExist(table_name):
            del_sql = f"DELETE FROM `{table_name}` WHERE `date` = %s"
            mdb.executeSql(del_sql, (date_str,))
            cols_type = None
        else:
            cols_type = tbs.get_field_types(tbs.TABLE_CN_STOCK_SPOT_BUY['columns'])

        mdb.insert_db_from_df(data, table_name, cols_type, False, "`date`,`code`")
        logging.info(f"基本面选股：筛选出 {len(data)} 只股票")
    except Exception as e:
        logging.error(f"基本面选股处理异常", exc_info=True)


def _resolve_run_date(date_arg=None):
    """解析可选的运行日期参数，返回 (run_date, run_date_nph, overridden)。

    - date_arg 为空：回退 ``trd.get_trade_date_last()``，与历史默认行为完全一致
      （overridden=False）。无参数的定时任务路径不受任何影响。
    - date_arg 提供：解析 ``YYYY-MM-DD`` 或 ``YYYYMMDD``，并校验：
        * 格式合法；
        * 不晚于今天（不支持未来日期）；
        * 为交易日（按交易日历，日历不可用时降级为工作日判断）。
      指定日期场景不区分盘中/盘后，run_date 与 run_date_nph 取同一日期（overridden=True）。
    - date_arg 非法 / 为多日期或区间：抛出 ``ValueError``，由调用方记录并以非零码退出。

    重要限制：本函数仅决定 execute_daily_job 中"日期相关"步骤（作业记账、数据
    新鲜度检查、基本面选股 stock_spot_buy、分析完成判定、数据健康检查）所用的日期。
    行情/选股/分析等子作业内部各自按实时数据运行，**不接受**该日期参数，因此指定历史
    日期无法真正回补当日的实时快照，仅用于按该日重跑日期相关的派生步骤与记账。
    """
    if date_arg is None or not str(date_arg).strip():
        run_date, run_date_nph = trd.get_trade_date_last()
        return run_date, run_date_nph, False

    raw = str(date_arg).strip()
    if ',' in raw or ' ' in raw:
        raise ValueError(
            f"暂不支持多日期/区间批量（'{raw}'）：子作业按实时数据运行，无法真正回补历史区间，"
            f"请一次只指定单个交易日（YYYY-MM-DD）"
        )

    parsed = None
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            parsed = datetime.datetime.strptime(raw, fmt).date()
            break
        except ValueError:
            continue
    if parsed is None:
        raise ValueError(f"无法解析日期参数 '{raw}'，期望格式 YYYY-MM-DD 或 YYYYMMDD")

    today = datetime.datetime.now().date()
    if parsed > today:
        raise ValueError(f"日期参数 '{raw}' 晚于今天（{today}），不支持未来日期")
    if not trd.is_trade_date(parsed):
        raise ValueError(f"日期参数 '{raw}' 不是交易日（周末或节假日）")

    return parsed, parsed, True


def main(date_arg=None):
    start = time.time()
    _start = datetime.datetime.now()
    logging.info("######## 任务执行时间: %s #######" % _start.strftime("%Y-%m-%d %H:%M:%S.%f"))

    # 获取交易日期（无参数时取最近交易日；可选单日期参数覆盖日期相关步骤）
    try:
        run_date, run_date_nph, _date_overridden = _resolve_run_date(date_arg)
        date_str = run_date_nph.strftime("%Y-%m-%d")
    except ValueError as e:
        logging.error(f"命令行日期参数错误，任务终止：{e}")
        sys.exit(2)
    except Exception as e:
        logging.error("获取交易日期失败，无法继续", exc_info=True)
        return

    if _date_overridden:
        logging.warning(
            f"⚠ 已指定运行日期 {date_str}：作业记账、数据新鲜度检查、基本面选股(stock_spot_buy)"
            f"与数据健康检查将按该日期执行。注意：行情/选股/分析等子作业内部仍按实时数据运行，"
            f"无法真正回补历史某日的实时快照——指定历史日期主要用于按该日重跑日期相关的派生步骤与记账。"
        )

    overall_start = record_task_start(_JOB_NAME, '__overall__', run_date_nph)

    # ================================================================
    # Phase 0: 初始化
    # ================================================================
    t0 = record_task_start(_JOB_NAME, 'init_db', run_date_nph)
    try:
        bj.main()   # 初始化数据库
        record_task_end(_JOB_NAME, 'init_db', run_date_nph, t0, success=True)
    except Exception as e:
        logging.error(f"execute_daily_job init_job 异常", exc_info=True)
        record_task_end(_JOB_NAME, 'init_db', run_date_nph, t0, success=False, message=str(e))

    # ================================================================
    # Phase 1: 轻量级数据入库
    # ================================================================

    # Phase 1a: 实时行情预加载
    t1a = record_task_start(_JOB_NAME, 'spot_preload', run_date_nph)
    try:
        from quantia.core.singleton_stock import stock_data as sd_cls
        spot = sd_cls(run_date_nph).get_data()
        if spot is not None:
            logging.info(f"Phase 1a: 实时行情预加载成功，{len(spot)} 只股票")
            record_task_end(_JOB_NAME, 'spot_preload', run_date_nph, t1a, success=True,
                            rows_affected=len(spot))
        else:
            logging.error("Phase 1a: 实时行情预加载失败（stock_data 返回 None）")
            record_task_end(_JOB_NAME, 'spot_preload', run_date_nph, t1a, success=False)
    except Exception as e:
        logging.error(f"execute_daily_job Phase 1a 行情预加载异常", exc_info=True)
        record_task_end(_JOB_NAME, 'spot_preload', run_date_nph, t1a, success=False, message=str(e))

    # Phase 1b: 基础数据入库
    if _check_and_skip('cn_stock_spot', date_str, '股票行情'):
        record_task_skipped(_JOB_NAME, 'stock_spot', run_date_nph, '数据已完整')
    else:
        t1b = record_task_start(_JOB_NAME, 'stock_spot', run_date_nph)
        try:
            hdj.main()
            record_task_end(_JOB_NAME, 'stock_spot', run_date_nph, t1b, success=True)
        except Exception as e:
            logging.error(f"execute_daily_job basic_data_daily异常", exc_info=True)
            record_task_end(_JOB_NAME, 'stock_spot', run_date_nph, t1b, success=False, message=str(e))

    # Phase 1c: 综合选股数据
    if _check_and_skip('cn_stock_selection', date_str, '综合选股'):
        record_task_skipped(_JOB_NAME, 'selection_data', run_date_nph, '数据已完整')
    else:
        t1c = record_task_start(_JOB_NAME, 'selection_data', run_date_nph)
        try:
            sddj.main()
            record_task_end(_JOB_NAME, 'selection_data', run_date_nph, t1c, success=True)
        except Exception as e:
            logging.error(f"execute_daily_job selection_data异常", exc_info=True)
            record_task_end(_JOB_NAME, 'selection_data', run_date_nph, t1c, success=False, message=str(e))

    # Phase 1d: 扩展数据（资金流向、龙虎榜等）
    t1d = record_task_start(_JOB_NAME, 'basic_data_other', run_date_nph)
    ok = _run_job_subprocess('basic_data_other_daily_job.py', 'execute_daily_job basic_data_other')
    record_task_end(_JOB_NAME, 'basic_data_other', run_date_nph, t1d, success=ok)

    # Phase 1e: GPT综合选股 + 基本面选股
    t1e = record_task_start(_JOB_NAME, 'gpt_value', run_date_nph)
    try:
        gptj.main()
        record_task_end(_JOB_NAME, 'gpt_value', run_date_nph, t1e, success=True)
    except Exception as e:
        logging.error(f"execute_daily_job gpt_value异常", exc_info=True)
        record_task_end(_JOB_NAME, 'gpt_value', run_date_nph, t1e, success=False, message=str(e))

    t1e2 = record_task_start(_JOB_NAME, 'stock_spot_buy', run_date_nph)
    try:
        _run_stock_spot_buy(run_date_nph)
        record_task_end(_JOB_NAME, 'stock_spot_buy', run_date_nph, t1e2, success=True)
    except Exception as e:
        logging.error(f"execute_daily_job stock_spot_buy异常", exc_info=True)
        record_task_end(_JOB_NAME, 'stock_spot_buy', run_date_nph, t1e2, success=False, message=str(e))

    # Phase 1f: 收盘后数据
    t1f = record_task_start(_JOB_NAME, 'after_close', run_date_nph)
    ok = _run_job_subprocess('basic_data_after_close_daily_job.py', 'execute_daily_job after_close')
    record_task_end(_JOB_NAME, 'after_close', run_date_nph, t1f, success=ok)

    # 记录 run_fetch 完成状态（供 kline_cache_daily_job 前置检查使用）
    # execute_daily_job 自行完成数据获取（不经过 fetch_daily_job），
    # 但 kline_cache_daily_job 检查的是 run_fetch/__overall__ 完成状态
    try:
        _fetch_start = time.time()
        record_task_start('run_fetch', '__overall__', run_date_nph)
        record_task_end('run_fetch', '__overall__', run_date_nph, _fetch_start,
                        success=True, message='由 execute_daily_job Phase 1 完成')
    except Exception:
        logging.debug("记录 run_fetch 完成状态异常", exc_info=True)

    # ================================================================
    # Phase 2: K线缓存批量更新（独立子进程）
    # ================================================================
    try:
        from quantia.core.singleton_stock import stock_data
        stock_data.release()
        gc.collect()
        logging.info("Phase 2: 已释放 stock_data 单例，回收内存")
    except Exception:
        logging.debug("释放 stock_data 单例异常", exc_info=True)

    t2 = record_task_start(_JOB_NAME, 'kline_cache', run_date_nph)
    phase2_ok = _run_job_subprocess('kline_cache_daily_job.py', 'execute_daily_job K线缓存更新', timeout=_KLINE_JOB_TIMEOUT)
    record_task_end(_JOB_NAME, 'kline_cache', run_date_nph, t2, success=phase2_ok)
    if not phase2_ok:
        logging.warning(
            "⚠ Phase 2 K线缓存更新失败！Phase 3 将使用可能过期的缓存数据运行。"
            "指标/策略结果基于最后一次成功缓存的K线，结果可能与当日实际行情不符。"
        )
        os.environ['QUANTIA_PHASE2_FAILED'] = '1'
    else:
        os.environ.pop('QUANTIA_PHASE2_FAILED', None)

    # 释放 stock_data 单例（可能缓存了 None）
    try:
        from quantia.core.singleton_stock import stock_data
        _sd = getattr(stock_data, '_instance', None)
        if _sd is not None and _sd.data is None:
            stock_data.release()
            logging.warning("stock_data 返回 None，已释放单例以允许 Phase 3 重试")
    except Exception:
        logging.debug("释放 stock_data 单例异常", exc_info=True)

    # ================================================================
    # Phase 3: 数据分析（流式处理 — 低内存模式）
    # ================================================================
    analysis_already_done = _is_analysis_done(run_date_nph)

    if analysis_already_done:
        logging.info("Phase 3 跳过：分析数据已由其他节点完成")
        record_task_skipped(_JOB_NAME, 'streaming_analysis', run_date_nph, '已由其他节点完成')
    else:
        t3 = record_task_start(_JOB_NAME, 'streaming_analysis', run_date_nph)
        try:
            saj.main()
            record_task_end(_JOB_NAME, 'streaming_analysis', run_date_nph, t3, success=True)
        except Exception as e:
            logging.error(f"execute_daily_job streaming_analysis异常", exc_info=True)
            record_task_end(_JOB_NAME, 'streaming_analysis', run_date_nph, t3, success=False, message=str(e))

    # ================================================================
    # Phase 4: 回测与收尾
    # ================================================================
    try:
        from quantia.core.singleton_stock import stock_data
        stock_data.release()
        gc.collect()
    except Exception as e:
        logging.warning(f"释放单例异常（不影响后续执行）：{e}")

    if analysis_already_done:
        logging.info("Phase 4 跳过：回测数据已由其他节点完成")
        record_task_skipped(_JOB_NAME, 'backtest', run_date_nph, '已由其他节点完成')
    else:
        t4 = record_task_start(_JOB_NAME, 'backtest', run_date_nph)
        try:
            bdj.main()
            record_task_end(_JOB_NAME, 'backtest', run_date_nph, t4, success=True)
        except Exception as e:
            logging.error(f"execute_daily_job backtest异常", exc_info=True)
            record_task_end(_JOB_NAME, 'backtest', run_date_nph, t4, success=False, message=str(e))

    # ================================================================
    # 数据健康检查
    # ================================================================
    _data_health_check(start, run_date_nph)

    # ================================================================
    # Phase 5: 模拟交易（每日自动执行所有运行中的模拟盘）
    # ================================================================
    t5 = record_task_start(_JOB_NAME, 'paper_trading', run_date_nph)
    try:
        from quantia.paper_trading.paper_engine import run_all_paper_trading
        paper_results = run_all_paper_trading()
        if paper_results:
            ok_count = sum(1 for r in paper_results if r.get('status') == 'ok')
            logging.info(f"Phase 5: 模拟交易完成，{ok_count}/{len(paper_results)} 个模拟盘执行成功")
        else:
            logging.info("Phase 5: 无运行中的模拟盘")
        record_task_end(_JOB_NAME, 'paper_trading', run_date_nph, t5, success=True)
    except Exception as e:
        logging.error("execute_daily_job Phase 5 模拟交易异常", exc_info=True)
        record_task_end(_JOB_NAME, 'paper_trading', run_date_nph, t5, success=False, message=str(e))

    elapsed = time.time() - start
    record_task_end(_JOB_NAME, '__overall__', run_date_nph, overall_start,
                    success=True, message=f"总耗时 {elapsed:.1f}s")
    logging.info("######## 完成任务, 使用时间: %s 秒 #######" % (time.time() - start))


def _data_health_check(pipeline_start, run_date_nph=None):
    """流水线结束后，检查核心表是否有当日数据"""
    try:
        import quantia.lib.database as mdb
        if run_date_nph is None:
            import quantia.lib.trade_time as trd
            _, run_date_nph = trd.get_trade_date_last()
        date_str = run_date_nph.strftime("%Y-%m-%d")

        tables_to_check = [
            ('cn_stock_spot', '实时行情'),
            ('cn_stock_selection', '综合选股'),
            ('cn_stock_indicators', '技术指标'),
            ('cn_stock_kline_pattern', 'K线形态'),
            ('cn_stock_strategy_enter', '放量上涨(策略)'),
            ('cn_stock_strategy_gpt_value', 'GPT综合选股'),
            ('cn_stock_backtest', '回测汇总'),
        ]
        results = []
        for table, label in tables_to_check:
            try:
                if not mdb.checkTableIsExist(table):
                    results.append(f"  {label}({table}): 表不存在")
                    continue
                row = mdb.executeSqlFetch(
                    f"SELECT COUNT(*) AS cnt, MAX(`date`) AS latest FROM `{table}`"
                )
                if row:
                    cnt_today_row = mdb.executeSqlFetch(
                        f"SELECT COUNT(*) AS cnt FROM `{table}` WHERE `date` = %s",
                        (date_str,)
                    )
                    cnt_today = cnt_today_row[0][0] if cnt_today_row else 0
                    latest = row[0][1]
                    latest_str = latest.strftime("%Y-%m-%d") if hasattr(latest, 'strftime') else str(latest)
                    total = row[0][0]
                    results.append(f"  {label}: 今日({date_str})={cnt_today}条, 最近日期={latest_str}, 总计={total}条")
                else:
                    results.append(f"  {label}({table}): 空表")
            except Exception as e:
                results.append(f"  {label}({table}): 查询异常 {e}")

        health = "\n".join(results)
        logging.info(f"===== 数据健康检查 [{date_str}] =====\n{health}")
    except Exception as e:
        logging.warning(f"数据健康检查异常（不影响任务结果）：{e}")


# main函数入口
if __name__ == '__main__':
    # 仅支持单个可选日期参数（YYYY-MM-DD / YYYYMMDD）。多参数（区间/多日期）
    # 明确拒绝而非静默忽略——子作业按实时数据运行，无法真正回补历史区间。
    _extra_args = [a for a in sys.argv[1:] if a and a.strip()]
    if len(_extra_args) > 1:
        logging.error(
            f"execute_daily_job 仅支持单个日期参数（YYYY-MM-DD）；检测到多个参数 {_extra_args}，已拒绝。"
            f"子作业按实时数据运行，无法回补历史区间。"
        )
        sys.exit(2)
    main(_extra_args[0] if _extra_args else None)
