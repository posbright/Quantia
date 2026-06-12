#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
历史K线缓存增量更新作业（独立运行）

职责：批量更新 ~5000 只股票的历史K线缓存文件。
此任务内存密集型（单只股票 ~350KB DataFrame），已从 fetch_daily_job.py 独立拆分。

前置条件：
- run_fetch（fetch_daily_job）当日已成功完成
- 通过 cn_job_status 表中 run_fetch/__overall__ 记录检查

设计原则：
1. 必须在 run_fetch 成功后才执行（避免基于过期行情数据更新缓存）
2. 独立子进程运行，OOM 不影响已入库的数据
3. 支持通过 QUANTIA_FORCE_KLINE_CACHE=1 强制执行（跳过前置检查）
4. 单只股票失败不影响其他股票
5. 增量模式：仅更新缺失日期的数据
"""

import logging
import time
import os.path
import sys

cpath_current = os.path.dirname(os.path.dirname(__file__))
cpath = os.path.abspath(os.path.join(cpath_current, os.pardir))
sys.path.append(cpath)
try:
    from quantia.lib.log_config import setup_logging
    setup_logging('kline_cache')
except Exception:
    log_path = os.path.join(cpath_current, 'log')
    os.makedirs(log_path, exist_ok=True)
    logging.basicConfig(
        format='%(asctime)s [%(levelname)s] %(message)s',
        filename=os.path.join(log_path, 'stock_kline_cache_job.log'),
        level=logging.INFO,
    )
import quantia.lib.run_template as runt
import quantia.lib.envconfig as _cfg
import quantia.core.stockfetch as stf
import quantia.lib.trade_time as trd
import quantia.core.tablestructure as tbs
from quantia.core.singleton_stock import stock_data
from quantia.lib.job_tracker import (
    is_job_completed, record_task_start, record_task_end,
)

__author__ = 'Quantia'
__date__ = '2026/03/12'

_JOB_NAME = 'run_kline_cache'


def _check_fetch_completed(date):
    """
    检查 run_fetch 当日是否已成功完成。

    通过 cn_job_status 表查询 run_fetch/__overall__ 的状态。
    可通过 QUANTIA_FORCE_KLINE_CACHE=1 跳过此检查。
    """
    if _cfg.get_bool('QUANTIA_FORCE_KLINE_CACHE', False):
        logging.info("检测到 QUANTIA_FORCE_KLINE_CACHE=1，跳过 run_fetch 完成检查")
        return True

    if is_job_completed('run_fetch', date):
        logging.info(f"run_fetch 已于 {date} 成功完成，继续执行K线缓存更新")
        return True
    else:
        logging.warning(
            f"run_fetch 尚未于 {date} 成功完成，跳过K线缓存更新。"
            f"设置 QUANTIA_FORCE_KLINE_CACHE=1 可强制执行。"
        )
        return False


def fetch_all_data(date):
    """
    集中获取所有股票历史K线缓存数据。

    执行顺序：
    1. 检查 run_fetch 是否已完成
    2. 清理过期缓存（退市股票、除权除息数据）
    3. 预加载实时行情（stock_data 单例）
    4. 批量更新历史K线缓存（仅更新磁盘缓存，不保留在内存中）
    5. 更新指数K线缓存（~15个主要指数）
    6. 更新ETF K线缓存（读取 cn_etf_spot 最新交易日列表）

    参数：
        date: 交易日期
    """
    # Step 0: 检查前置条件
    if not _check_fetch_completed(date):
        return

    start_time = time.time()
    logging.info(f"===== K线缓存增量更新开始 [{date}] =====")

    overall_start = record_task_start(_JOB_NAME, '__overall__', date)

    # Step 1: 清理过期缓存
    t1 = record_task_start(_JOB_NAME, 'clean_cache', date)
    try:
        logging.info("Step 1/5: 清理过期缓存...")
        cleaned = stf.clean_expired_cache()
        logging.info(f"缓存清理完成，清理了 {cleaned} 个文件")
        record_task_end(_JOB_NAME, 'clean_cache', date, t1, success=True,
                        message=f"清理 {cleaned} 个文件")
    except Exception as e:
        logging.warning(f"缓存清理异常（不影响后续执行）：{e}")
        record_task_end(_JOB_NAME, 'clean_cache', date, t1, success=False, message=str(e))

    # Step 2: 预加载实时行情（stock_data 单例）
    t2 = record_task_start(_JOB_NAME, 'load_spot', date)
    try:
        logging.info("Step 2/5: 预加载实时行情数据...")
        spot_start = time.time()
        spot = stock_data(date).get_data()
        if spot is not None and len(spot) > 0:
            logging.info(f"实时行情加载成功：{len(spot)} 只股票，耗时 {time.time() - spot_start:.1f}秒")
            record_task_end(_JOB_NAME, 'load_spot', date, t2, success=True,
                            rows_affected=len(spot))
        else:
            # API 返回空时，尝试从数据库 cn_stock_spot 获取最近的股票列表
            logging.warning("API 实时行情为空，尝试从数据库获取股票列表...")
            try:
                import quantia.lib.database as mdb
                from sqlalchemy import text
                with mdb.engine().connect() as conn:
                    sql = text(
                        "SELECT date, code, name FROM cn_stock_spot "
                        "WHERE date = (SELECT MAX(date) FROM cn_stock_spot) "
                        "ORDER BY code"
                    )
                    rows = conn.execute(sql).fetchall()
                    if rows:
                        import pandas as _pd
                        spot = _pd.DataFrame(rows, columns=['date', 'code', 'name'])
                        logging.info(f"从数据库获取 {len(spot)} 只股票（DB回退）")
                        record_task_end(_JOB_NAME, 'load_spot', date, t2, success=True,
                                        rows_affected=len(spot), message="DB回退")
                    else:
                        logging.error("数据库 cn_stock_spot 也无数据，无法执行K线缓存更新")
                        record_task_end(_JOB_NAME, 'load_spot', date, t2, success=False,
                                        message="API 和 DB 均无数据")
                        return
            except Exception as db_err:
                logging.error(f"数据库回退失败：{db_err}")
                record_task_end(_JOB_NAME, 'load_spot', date, t2, success=False,
                                message=f"API为空且DB回退失败: {db_err}")
                return
    except Exception as e:
        logging.error(f"实时行情加载异常", exc_info=True)
        record_task_end(_JOB_NAME, 'load_spot', date, t2, success=False, message=str(e))
        return

    # Step 3: 批量更新历史K线缓存（自动检测本地/服务器模式）
    t3 = record_task_start(_JOB_NAME, 'update_kline_cache', date)
    try:
        logging.info("Step 3/5: 批量更新历史K线缓存...")
        hist_start = time.time()

        _subset = spot[list(tbs.TABLE_CN_STOCK_FOREIGN_KEY['columns'])]
        stocks = [tuple(x) for x in _subset.values]
        if not stocks:
            logging.warning("股票列表为空，跳过K线缓存更新")
            record_task_end(_JOB_NAME, 'update_kline_cache', date, t3, success=False,
                            message="股票列表为空")
            return

        years = stf.HIST_DATA_DEFAULT_YEARS
        date_start, _ = trd.get_trade_hist_interval(stocks[0][0], years)
        raw_date = stocks[0][0]
        if hasattr(raw_date, 'strftime'):
            date_end = raw_date.strftime("%Y%m%d")
        else:
            date_end = str(raw_date).replace("-", "").replace("/", "")[:8]

        success, fail = stf.update_all_caches(stocks, date_start, date_end,
                                                workers=_cfg.get_int('QUANTIA_KLINE_CACHE_WORKERS', 2),
                                                spot_df=spot)
        elapsed_hist = time.time() - hist_start
        logging.info(f"历史K线缓存更新完成：成功 {success}，失败 {fail}，耗时 {elapsed_hist:.1f}秒")
        record_task_end(_JOB_NAME, 'update_kline_cache', date, t3, success=True,
                        rows_affected=success,
                        message=f"成功 {success}，失败 {fail}")
    except Exception as e:
        logging.error(f"历史K线缓存更新异常", exc_info=True)
        record_task_end(_JOB_NAME, 'update_kline_cache', date, t3, success=False, message=str(e))

    # Step 4: 指数K线缓存更新（数据驱动：cn_index_spot 最新交易日全量指数，~535个）
    t4 = record_task_start(_JOB_NAME, 'update_index_cache', date)
    try:
        logging.info("Step 4/5: 更新指数K线缓存...")
        idx_start = time.time()
        idx_ok, idx_fail = stf.update_index_caches(date_start=date_start, date_end=date_end)
        elapsed_idx = time.time() - idx_start
        logging.info(f"指数K线缓存更新完成：成功 {idx_ok}，失败 {idx_fail}，耗时 {elapsed_idx:.1f}秒")
        record_task_end(_JOB_NAME, 'update_index_cache', date, t4, success=True,
                        rows_affected=idx_ok,
                        message=f"成功 {idx_ok}，失败 {idx_fail}")
    except Exception as e:
        logging.error(f"指数K线缓存更新异常", exc_info=True)
        record_task_end(_JOB_NAME, 'update_index_cache', date, t4, success=False, message=str(e))

    # Step 5: ETF K线缓存更新（读取 cn_etf_spot 最新交易日列表，复用增量/限流逻辑）
    t5 = record_task_start(_JOB_NAME, 'update_etf_cache', date)
    try:
        logging.info("Step 5/5: 更新ETF K线缓存...")
        etf_start = time.time()
        etf_ok, etf_fail = stf.update_all_etf_caches(date_start=date_start, date_end=date_end)
        elapsed_etf = time.time() - etf_start
        logging.info(f"ETF K线缓存更新完成：成功 {etf_ok}，失败 {etf_fail}，耗时 {elapsed_etf:.1f}秒")
        record_task_end(_JOB_NAME, 'update_etf_cache', date, t5, success=True,
                        rows_affected=etf_ok,
                        message=f"成功 {etf_ok}，失败 {etf_fail}")
    except Exception as e:
        logging.error(f"ETF K线缓存更新异常", exc_info=True)
        record_task_end(_JOB_NAME, 'update_etf_cache', date, t5, success=False, message=str(e))

    elapsed = time.time() - start_time
    record_task_end(_JOB_NAME, '__overall__', date, overall_start, success=True,
                    message=f"总耗时 {elapsed:.1f}s")
    logging.info(f"===== K线缓存增量更新完成，总耗时 {elapsed:.1f}秒 =====")


def main():
    """入口函数，通过 run_template 获取交易日期并执行"""
    runt.run_with_args(fetch_all_data)


# main函数入口
if __name__ == '__main__':
    main()
