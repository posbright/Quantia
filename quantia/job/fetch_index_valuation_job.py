#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T3 宽基指数估值 Fetch job（legulegu 全历史 PE + 历史分位 → cn_index_valuation）。

逐指数抓取「PE(TTM/LYR) + 历史分位」全历史，增量 upsert 写 cn_index_valuation，
供 fundTimingHandler 的 T3 估值分位择时（`valuation_percentile_score`）。

属 fetch 管道（仅此处 + crawling + stockfetch 可调外部 API，AGENTS 规则 1）。
低频 cron（cron.workdayly）或手动触发；写库 chunksize=500（insert_db_from_df 内置）。

用法：
    python fetch_index_valuation_job.py                 # 全 12 只宽基
    python fetch_index_valuation_job.py 沪深300 中证500   # 指定指数
"""
import datetime
import logging
import os.path
import random
import sys
import time

cpath_current = os.path.dirname(os.path.dirname(__file__))
cpath = os.path.abspath(os.path.join(cpath_current, os.pardir))
sys.path.append(cpath)
try:
    from quantia.lib.log_config import setup_logging
    setup_logging('fetch')
except Exception:
    log_path = os.path.join(cpath_current, 'log')
    os.makedirs(log_path, exist_ok=True)
    logging.basicConfig(
        format='%(asctime)s [%(levelname)s] %(message)s',
        filename=os.path.join(log_path, 'index_valuation_job.log'),
        level=logging.INFO,
    )

import quantia.core.tablestructure as tbs
import quantia.core.crawling.index_valuation_lg as ivlg
import quantia.lib.database as mdb
from quantia.lib.job_tracker import record_task_start, record_task_end

__author__ = 'Quantia'
__date__ = '2026/07/09'

_JOB_NAME = 'run_index_valuation'
_TABLE = tbs.TABLE_CN_INDEX_VALUATION['name']


def _existing_max_date(index_code):
    """库中该指数已有的最新日期（断点续抓增量过滤），无则 None。"""
    if not mdb.checkTableIsExist(_TABLE):
        return None
    rows = mdb.executeSqlFetch(
        f"SELECT MAX(`date`) FROM `{_TABLE}` WHERE `index_code` = %s", (index_code,))
    if rows and rows[0] and rows[0][0] is not None:
        return rows[0][0]
    return None


def _write_incremental(df):
    """增量过滤（仅 > 库中最新日）+ upsert 写库，返回写入行数。"""
    if df is None or len(df.index) == 0:
        return 0
    index_code = str(df['index_code'].iloc[0])
    max_date = _existing_max_date(index_code)
    if max_date is not None:
        df = df[df['date'].map(lambda d: d is not None and d > max_date)]
    if len(df.index) == 0:
        return 0
    cols_type = None
    if not mdb.checkTableIsExist(_TABLE):
        cols_type = tbs.get_field_types(tbs.TABLE_CN_INDEX_VALUATION['columns'])
    mdb.insert_db_from_df(df, _TABLE, cols_type, False, "`index_code`,`date`")
    return len(df.index)


def save_index_valuation(symbol):
    """抓取 + 增量写入单只指数估值历史，返回写入行数（0 表示无新增/失败）。"""
    try:
        df = ivlg.fetch_index_valuation(symbol)
    except Exception:
        logging.warning("fetch_index_valuation_job: %s 抓取失败，跳过", symbol, exc_info=True)
        return 0
    return _write_incremental(df)


def run(symbols=None, job_date=None):
    job_date = job_date or datetime.date.today()
    if not symbols:
        symbols = list(ivlg.INDEX_SYMBOLS.keys())

    start = record_task_start(_JOB_NAME, 'index_valuation', job_date)
    total_rows = 0
    ok = 0
    success = True
    try:
        for i, symbol in enumerate(symbols):
            n = save_index_valuation(symbol)
            total_rows += n
            if n > 0:
                ok += 1
            logging.info("fetch_index_valuation_job: %s 写入 %d 行", symbol, n)
            if i < len(symbols) - 1:
                time.sleep(random.uniform(0.8, 2.0))  # 限速
    except Exception:
        success = False
        raise
    finally:
        record_task_end(_JOB_NAME, 'index_valuation', job_date, start,
                        success=success, message=f"{ok}/{len(symbols)} 指数",
                        rows_affected=total_rows)
    logging.info("fetch_index_valuation_job: 完成 %d/%d 指数, 共 %d 行",
                 ok, len(symbols), total_rows)
    return total_rows


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('-')]
    run(symbols=args or None)
