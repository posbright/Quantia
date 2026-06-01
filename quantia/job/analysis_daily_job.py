#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据分析作业（独立运行）

职责：基于本地缓存和数据库数据执行所有分析、筛选、回测任务。
与 fetch_daily_job.py 配合使用，实现获取与分析解耦。

包含：
- GPT综合选股（从 cn_stock_selection 表筛选）
- 基本面选股（PE/PB/ROE筛选，从 cn_stock_spot 表读取）
- 流式分析（技术指标 + K线形态 + 策略选股）
- 回测数据计算

不包含：
- 任何外部 API 调用
- 所有数据来源：磁盘缓存 + 数据库

设计原则：
- 零 API 调用，纯本地计算
- 依赖 fetch_daily_job.py 已更新的缓存，但即使缓存未更新也能用历史缓存运行
- 峰值内存 < 50 MB（通过环境变量可调节并发度和批量大小）
- 每个子任务记录开始/结束日志及耗时
- 可独立于数据获取任务运行
"""

import time
import datetime
import logging
import gc
import os.path
import sys
import subprocess

cpath_current = os.path.dirname(os.path.dirname(__file__))
cpath = os.path.abspath(os.path.join(cpath_current, os.pardir))
sys.path.append(cpath)
try:
    from quantia.lib.log_config import setup_logging
    setup_logging('analysis')
except Exception:
    log_path = os.path.join(cpath_current, 'log')
    os.makedirs(log_path, exist_ok=True)
    logging.basicConfig(
        format='%(asctime)s [%(levelname)s] %(message)s',
        filename=os.path.join(log_path, 'stock_analysis_job.log'),
        level=logging.INFO,
    )
import quantia.lib.database as mdb
import quantia.lib.trade_time as trd
import gpt_value_data_job as gptj
import streaming_analysis_job as saj
# 注：backtest_data_daily_job 通过子进程调用，不在此导入
from quantia.lib.job_tracker import record_task_start, record_task_end, record_task_skipped
import quantia.lib.envconfig as _cfg

__author__ = 'Quantia'
__date__ = '2026/03/12'

# 分析数据跳过阈值：cn_stock_indicators 今日行数 >= 此值时认为分析已完成
# 正常交易日约 4800+ 条，设 1000 作为安全阈值避免误跳过部分完成的情况
ANALYSIS_DONE_THRESHOLD = _cfg.get_int('QUANTIA_ANALYSIS_DONE_THRESHOLD', 1000)

_JOB_NAME = 'run_analysis'
_JOB_DIR = os.path.dirname(os.path.abspath(__file__))
# 回测子进程超时（默认 2 小时）
_BACKTEST_TIMEOUT = _cfg.get_int('QUANTIA_BACKTEST_TIMEOUT', 7200)


def _run_job_subprocess(script_name, label, timeout):
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
        logging.info(f"{label}: 子进程执行成功")
        return True
    except subprocess.TimeoutExpired:
        logging.error(f"{label}: 子进程执行超时（{timeout}秒）")
        return False
    except Exception:
        logging.error(f"{label}: 子进程启动异常", exc_info=True)
        return False


def _is_analysis_done(date_str):
    """
    检查今日分析数据是否已由其他节点（如本地计算机）完成。

    检查 cn_stock_indicators 表的今日行数：
    - >= ANALYSIS_DONE_THRESHOLD → 已完成，跳过
    - < ANALYSIS_DONE_THRESHOLD → 未完成或部分完成，需要执行

    用于服务器 cron 回退模式：当本地已执行完分析任务后，
    服务器 cron 触发时自动跳过，避免低内存环境重复计算。
    可通过 QUANTIA_FORCE_ANALYSIS=1 环境变量强制执行。
    """
    if _cfg.get_bool('QUANTIA_FORCE_ANALYSIS', False):
        logging.info("检测到 QUANTIA_FORCE_ANALYSIS=1，强制执行分析任务")
        return False

    try:
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
                f"今日分析数据已存在（{table_name} 有 {count} 条 >= 阈值 {ANALYSIS_DONE_THRESHOLD}），"
                f"跳过分析任务。设置 QUANTIA_FORCE_ANALYSIS=1 可强制执行。"
            )
            return True
        logging.info(f"今日分析数据不足（{table_name} 有 {count} 条 < 阈值 {ANALYSIS_DONE_THRESHOLD}），继续执行")
        return False
    except Exception as e:
        logging.warning(f"检查分析数据是否完成时异常（将继续执行）：{e}")
        return False


def _get_roe_threshold(date):
    """根据季报披露周期动态调整 ROE 阈值。

    东方财富 roe_weight 字段在季报披露后会更新为该报告期的累计 ROE，
    而非年化 ROE。例如 Q1 报表（4月底前披露）后，该字段约为全年 ROE 的 1/4。
    固定阈值 15% 在 Q1 披露后只能筛出极少数股票。

    按报告周期年化换算：
    - 5~8 月（Q1 报表为主）：阈值 = 15 / 4 = 3.75
    - 9~10 月（半年报为主）：阈值 = 15 / 2 = 7.5
    - 11~12 月（Q3 报表为主）：阈值 = 15 * 3 / 4 = 11.25
    - 1~4 月（年报为主）：阈值 = 15.0
    """
    month = date.month if hasattr(date, 'month') else int(str(date).split('-')[1])
    if 5 <= month <= 8:
        return 3.75
    elif 9 <= month <= 10:
        return 7.5
    elif month >= 11:
        return 11.25
    else:
        return 15.0


def _run_stock_spot_buy(date):
    """
    基本面选股：筛选 PE<20、PB<10、ROE>=年化15% 的股票。

    数据源优先级：
    1. cn_stock_selection（东方财富选股器 API，PE/ROE 数据更可靠）
    2. cn_stock_spot（行情 API，降级到腾讯/新浪时 PE/ROE=0）

    筛选逻辑：从数据源筛出符合条件的股票代码，再用代码去 cn_stock_spot 取完整行情数据写入。
    ROE 阈值根据季报披露周期动态调整（避免 Q1 报表后阈值过严）。
    """
    import pandas as pd
    import quantia.core.tablestructure as tbs

    try:
        date_str = date.strftime("%Y-%m-%d") if hasattr(date, 'strftime') else str(date)
        qualified_codes = None
        roe_threshold = _get_roe_threshold(date)

        # 优先从 cn_stock_selection 筛选（PE/ROE 数据更可靠）
        sel_table = tbs.TABLE_CN_STOCK_SELECTION['name']
        if mdb.checkTableIsExist(sel_table):
            sel_sql = (f'SELECT `code` FROM `{sel_table}` WHERE `date` = %s '
                       f'AND `pe9` > 0 AND `pe9` <= 20 AND `pbnewmrq` <= 10 AND `roe_weight` >= %s')
            sel_data = pd.read_sql(sql=sel_sql, con=mdb.engine(), params=(date_str, roe_threshold))
            if len(sel_data) > 0:
                qualified_codes = set(sel_data['code'].values)
                logging.info(f"基本面选股：从 cn_stock_selection 筛出 {len(qualified_codes)} 只符合条件"
                             f"（ROE阈值={roe_threshold}%）")

        # 降级：从 cn_stock_spot 筛选
        # 注意：降级行情源（腾讯/新浪）不提供 TTM 市盈率(pe9)与加权ROE(roe_weight)，
        # 二者在 cn_stock_spot 中恒为 0。此时：
        #   1) 用动态市盈率(dtsyl)替代 pe9 做 PE 估值过滤；
        #   2) 若该日 spot 无任何有效 roe_weight，则放弃 ROE 约束（仅按 PE+PB 估值降级筛选），
        #      避免因 pe9/roe_weight=0 导致降级时选不出任何股票。
        if qualified_codes is None:
            spot_table = tbs.TABLE_CN_STOCK_SPOT['name']
            if mdb.checkTableIsExist(spot_table):
                # PE：优先 TTM(pe9)，缺失时回退动态市盈率(dtsyl)
                pe_expr = ('CASE WHEN `pe9` > 0 THEN `pe9` '
                           'WHEN `dtsyl` > 0 THEN `dtsyl` ELSE NULL END')
                try:
                    roe_cnt = mdb.executeSqlFetch(
                        f'SELECT COUNT(*) FROM `{spot_table}` WHERE `date` = %s AND `roe_weight` != 0',
                        (date_str,))
                    has_roe = bool(roe_cnt and (roe_cnt[0][0] or 0) > 0)
                except Exception:
                    has_roe = False

                if has_roe:
                    spot_sql = (f'SELECT `code` FROM `{spot_table}` WHERE `date` = %s '
                                f'AND ({pe_expr}) > 0 AND ({pe_expr}) <= 20 '
                                f'AND `pbnewmrq` > 0 AND `pbnewmrq` <= 10 AND `roe_weight` >= %s')
                    spot_params = (date_str, roe_threshold)
                else:
                    spot_sql = (f'SELECT `code` FROM `{spot_table}` WHERE `date` = %s '
                                f'AND ({pe_expr}) > 0 AND ({pe_expr}) <= 20 '
                                f'AND `pbnewmrq` > 0 AND `pbnewmrq` <= 10')
                    spot_params = (date_str,)
                    logging.warning("基本面选股：降级行情源缺少 ROE/TTM 市盈率数据，"
                                    "改用 动态市盈率(dtsyl)+PB 估值降级筛选（无 ROE 约束）")

                spot_data = pd.read_sql(sql=spot_sql, con=mdb.engine(), params=spot_params)
                if len(spot_data) > 0:
                    qualified_codes = set(spot_data['code'].values)
                    logging.info(f"基本面选股：降级从 cn_stock_spot 筛出 {len(qualified_codes)} 只符合条件"
                                 f"（ROE阈值={roe_threshold if has_roe else 'N/A'}）")

        if not qualified_codes:
            logging.info("基本面选股：无符合条件的股票")
            return

        # 从 cn_stock_spot 取完整行情数据（保持 cn_stock_spot_buy 表结构一致）
        spot_table = tbs.TABLE_CN_STOCK_SPOT['name']
        if not mdb.checkTableIsExist(spot_table):
            logging.warning("基本面选股：cn_stock_spot 表不存在，跳过")
            return

        placeholders = ','.join(['%s'] * len(qualified_codes))
        data = pd.read_sql(
            f'SELECT * FROM `{spot_table}` WHERE `date` = %s AND `code` IN ({placeholders})',
            mdb.engine(), params=(date_str, *qualified_codes))
        data = data.drop_duplicates(subset="code", keep="last")
        if len(data.index) == 0:
            logging.info("基本面选股：cn_stock_spot 中未找到对应股票数据")
            return

        table_name = tbs.TABLE_CN_STOCK_SPOT_BUY['name']
        if mdb.checkTableIsExist(table_name):
            del_sql = f"DELETE FROM `{table_name}` WHERE `date` = %s"
            mdb.executeSql(del_sql, (date_str,))
            cols_type = None
        else:
            cols_type = tbs.get_field_types(tbs.TABLE_CN_STOCK_SPOT_BUY['columns'])

        mdb.insert_db_from_df(data, table_name, cols_type, False, "`date`,`code`")
        logging.info(f"基本面选股：筛选出 {len(data)} 只股票写入 {table_name}")
    except Exception as e:
        logging.error(f"基本面选股处理异常", exc_info=True)


def main():
    start = time.time()
    logging.info("====== 数据分析任务开始 [%s] ======" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    # 检查今日分析是否已由其他节点完成（本地计算机优先模式）
    try:
        run_date, run_date_nph = trd.get_trade_date_last()
        date_str = run_date_nph.strftime("%Y-%m-%d")
        if _is_analysis_done(date_str):
            elapsed = time.time() - start
            logging.info("====== 数据分析任务跳过（已完成），耗时 %.1f 秒 ======" % elapsed)
            return
    except Exception as e:
        logging.warning(f"检查分析完成状态异常（将继续执行）：{e}")
        run_date, run_date_nph = trd.get_trade_date_last()
        date_str = run_date_nph.strftime("%Y-%m-%d")

    overall_start = record_task_start(_JOB_NAME, '__overall__', run_date_nph)

    # Step 1: GPT综合选股（纯 DB 读取 + 筛选，无 API）
    t1 = record_task_start(_JOB_NAME, 'gpt_value', run_date_nph)
    try:
        gptj.main()
        record_task_end(_JOB_NAME, 'gpt_value', run_date_nph, t1, success=True)
    except Exception as e:
        logging.error("数据分析 gpt_value 异常", exc_info=True)
        record_task_end(_JOB_NAME, 'gpt_value', run_date_nph, t1, success=False, message=str(e))
    gc.collect()

    # Step 2: 基本面选股（从 cn_stock_spot 筛选 PE/PB/ROE）
    t2 = record_task_start(_JOB_NAME, 'stock_spot_buy', run_date_nph)
    try:
        _run_stock_spot_buy(run_date_nph)
        record_task_end(_JOB_NAME, 'stock_spot_buy', run_date_nph, t2, success=True)
    except Exception as e:
        logging.error("数据分析 stock_spot_buy 异常", exc_info=True)
        record_task_end(_JOB_NAME, 'stock_spot_buy', run_date_nph, t2, success=False, message=str(e))
    gc.collect()

    # Step 3: 流式分析：指标计算 + K线形态识别 + 策略选股（从磁盘缓存读取）
    t3 = record_task_start(_JOB_NAME, 'streaming_analysis', run_date_nph)
    try:
        saj.main()
        record_task_end(_JOB_NAME, 'streaming_analysis', run_date_nph, t3, success=True)
    except Exception as e:
        logging.error("数据分析 streaming_analysis 异常", exc_info=True)
        record_task_end(_JOB_NAME, 'streaming_analysis', run_date_nph, t3, success=False, message=str(e))
    gc.collect()

    # Step 4: 策略回测（从磁盘缓存按需读取）
    # ⚠️ 以独立子进程运行：回测需要加载大量 K 线数据和 ThreadPoolExecutor，
    # 在低内存机器上易 OOM。子进程隔离确保 OOM 不会波及当前进程，保证
    # 完成日志和 task_runs 状态能正确写入。
    t4 = record_task_start(_JOB_NAME, 'backtest', run_date_nph)
    try:
        ok = _run_job_subprocess('backtest_data_daily_job.py', '数据分析 backtest',
                                 timeout=_BACKTEST_TIMEOUT)
        if ok:
            record_task_end(_JOB_NAME, 'backtest', run_date_nph, t4, success=True)
        else:
            record_task_end(_JOB_NAME, 'backtest', run_date_nph, t4,
                            success=False, message='子进程失败/超时/OOM')
    except Exception as e:
        logging.error("数据分析 backtest 异常", exc_info=True)
        record_task_end(_JOB_NAME, 'backtest', run_date_nph, t4, success=False, message=str(e))
    gc.collect()

    # 释放可能加载的单例
    try:
        from quantia.core.singleton_stock import stock_data, stock_hist_data
        stock_data.release()
        stock_hist_data.release()
        gc.collect()
    except Exception as e:
        logging.debug(f"释放单例跳过: {e}")

    elapsed = time.time() - start
    record_task_end(
        _JOB_NAME, '__overall__', run_date_nph, overall_start,
        success=True, message=f"总耗时 {elapsed:.1f}s"
    )
    logging.info("====== 数据分析任务完成，耗时 %.1f 秒 ======" % elapsed)


if __name__ == '__main__':
    main()
