#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import logging
import datetime
import concurrent.futures
import os
import re
import sys
import time
import quantia.lib.trade_time as trd
import quantia.lib.envconfig as _cfg
import quantia.lib.database as mdb

__author__ = 'Quantia'
__date__ = '2026/02/14'

_BATCH_DATE_WORKERS = _cfg.get_int('QUANTIA_BATCH_DATE_WORKERS', 3)
_DATE_RE = re.compile(r'^\d{4}-\d{1,2}-\d{1,2}$')


def _looks_like_date(s: str) -> bool:
    """Check if a string looks like YYYY-MM-DD format."""
    return bool(_DATE_RE.match(s.strip())) if s else False


# 通用函数，获得日期参数，支持批量作业。
def run_with_args(run_fun, *args):
    # 单独执行时自动初始化日志（通过父脚本调用时已有handler，不会重复）
    if not logging.getLogger().handlers:
        try:
            from quantia.lib.log_config import setup_logging
            # 从调用脚本文件名推导日志名: strategy_data_daily_job → strategy
            import inspect
            caller = inspect.stack()
            caller_file = caller[-1].filename if len(caller) > 1 else ''
            base = os.path.basename(caller_file).replace('.py', '')
            log_name = base.replace('_daily_job', '').replace('_data', '').replace('_job', '') or 'job'
            setup_logging(log_name)
        except Exception:
            logging.basicConfig(
                format='%(asctime)s [%(levelname)s] %(message)s',
                level=logging.INFO,
            )

    if len(sys.argv) == 3 and _looks_like_date(sys.argv[1]) and _looks_like_date(sys.argv[2]):
        # 区间作业 python xxx.py 2023-03-01 2023-03-21
        try:
            start_date = datetime.datetime.strptime(sys.argv[1].strip(), '%Y-%m-%d').date()
            end_date = datetime.datetime.strptime(sys.argv[2].strip(), '%Y-%m-%d').date()
        except (ValueError, TypeError) as e:
            logging.error(f"run_template: 日期参数格式错误，期望 YYYY-MM-DD，实际 sys.argv={sys.argv}: {e}")
            sys.exit(1)
        run_date = start_date
        try:
            futures = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=_BATCH_DATE_WORKERS) as executor:
                while run_date <= end_date:
                    if trd.is_trade_date(run_date):
                        if run_fun.__name__.startswith('save_nph'):
                            futures.append(executor.submit(run_fun, run_date, False, *args))
                        else:
                            futures.append(executor.submit(run_fun, run_date, *args))
                        time.sleep(2)
                    run_date += datetime.timedelta(days=1)
                for future in concurrent.futures.as_completed(futures):
                    try:
                        future.result()
                    except Exception as e:
                        logging.error(f"run_template批量任务异常：{run_fun}", exc_info=True)
            # 线程池退出后清理残留 DB 连接，防止 MySQL Too many connections
            mdb.close_thread_connection()
        except Exception as e:
            logging.error(f"run_template.run_with_args处理异常：{run_fun}{sys.argv}", exc_info=True)
            sys.exit(1)
    elif len(sys.argv) == 2 and all(_looks_like_date(d) for d in sys.argv[1].split(',')):
        # N个时间作业 python xxx.py 2023-03-01,2023-03-02
        dates = sys.argv[1].split(',')
        try:
            futures = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=_BATCH_DATE_WORKERS) as executor:
                for date in dates:
                    run_date = datetime.datetime.strptime(date.strip(), '%Y-%m-%d').date()
                    if trd.is_trade_date(run_date):
                        if run_fun.__name__.startswith('save_nph'):
                            futures.append(executor.submit(run_fun, run_date, False, *args))
                        else:
                            futures.append(executor.submit(run_fun, run_date, *args))
                        time.sleep(2)
                for future in concurrent.futures.as_completed(futures):
                    try:
                        future.result()
                    except Exception as e:
                        logging.error(f"run_template批量任务异常：{run_fun}", exc_info=True)
            # 线程池退出后清理残留 DB 连接
            mdb.close_thread_connection()
        except Exception as e:
            logging.error(f"run_template.run_with_args处理异常：{run_fun}{sys.argv}", exc_info=True)
            sys.exit(1)
    else:
        # 当前时间作业 python xxx.py
        try:
            run_date, run_date_nph = trd.get_trade_date_last()
            if run_fun.__name__.startswith('save_nph'):
                run_fun(run_date_nph, False)
            elif run_fun.__name__.startswith('save_after_close'):
                run_fun(run_date, *args)
            else:
                run_fun(run_date_nph, *args)
        except Exception as e:
            logging.error(f"run_template.run_with_args处理异常：{run_fun}{sys.argv}", exc_info=True)
            sys.exit(1)
