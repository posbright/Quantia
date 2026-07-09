#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P4 基金经理经验缓存（独立慢 job，低频）。

一次抓取 fund_manager_em() 全量经理×基金行，映射英文列 + 计算每位经理在管基金数，
默认按 cn_fund_rank 现有基金全集过滤后 upsert 写 cn_fund_manager（主键 (code, manager)
覆盖），供详情页「经理经验弱因子」展示。属 fetch 管道（akshare 单源）。

严格定位：经理经验仅弱因子展示，不硬拦截、不进入 TimingScore（蓝图 §9.2 / P4）。
「累计从业时间」是经理全市场累计从业天数，非本基金任职起始日。

用法：
    python fetch_fund_manager_job.py            # 覆盖 cn_fund_rank 全部基金
    python fetch_fund_manager_job.py --all      # 写全部经理行（不按 rank 过滤）
    python fetch_fund_manager_job.py 015495 011251   # 仅指定基金
"""
import datetime
import logging
import os.path
import sys

import pandas as pd

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
        filename=os.path.join(log_path, 'fund_manager_job.log'),
        level=logging.INFO,
    )

import quantia.core.tablestructure as tbs
import quantia.core.crawling.fund_em as fem
import quantia.lib.database as mdb
from quantia.lib.job_tracker import record_task_start, record_task_end

__author__ = 'Quantia'
__date__ = '2026/07/09'

_JOB_NAME = 'run_fund_manager'
_RANK_TABLE = tbs.TABLE_CN_FUND_RANK['name']
_MANAGER_TABLE = tbs.TABLE_CN_FUND_MANAGER['name']
_MANAGER_COLS = list(tbs.TABLE_CN_FUND_MANAGER['columns'])


def _rank_codes():
    """cn_fund_rank 最新交易日的基金代码全集。"""
    if not mdb.checkTableIsExist(_RANK_TABLE):
        return set()
    sql = (f"SELECT DISTINCT code FROM `{_RANK_TABLE}` "
           f"WHERE `date` = (SELECT MAX(`date`) FROM `{_RANK_TABLE}`)")
    rows = mdb.executeSqlFetch(sql)
    return {str(r[0]).zfill(6) for r in rows if r and r[0] is not None}


def run(codes=None, keep_all=False, job_date=None):
    job_date = job_date or datetime.date.today()
    start = record_task_start(_JOB_NAME, 'manager', job_date)

    df = fem.fund_manager_all()
    if df is None or len(df.index) == 0:
        logging.warning("fetch_fund_manager_job: 经理全量抓取无数据")
        record_task_end(_JOB_NAME, 'manager', job_date, start, success=False,
                        message="经理全量抓取无数据", rows_affected=0)
        return 0

    # 过滤：指定 codes > rank 全集 > 全部
    if codes:
        want = {str(c).zfill(6) for c in codes}
        df = df[df['code'].isin(want)]
    elif not keep_all:
        want = _rank_codes()
        if want:
            df = df[df['code'].isin(want)]

    if len(df.index) == 0:
        logging.warning("fetch_fund_manager_job: 过滤后无经理行")
        record_task_end(_JOB_NAME, 'manager', job_date, start, success=True,
                        message="过滤后无经理行", rows_affected=0)
        return 0

    df = df.copy()
    df['update_date'] = job_date
    # 对齐表列序，缺失列补 None
    for c in _MANAGER_COLS:
        if c not in df.columns:
            df[c] = None
    out = df[_MANAGER_COLS].copy()

    cols_type = None
    if not mdb.checkTableIsExist(_MANAGER_TABLE):
        cols_type = tbs.get_field_types(tbs.TABLE_CN_FUND_MANAGER['columns'])
    mdb.insert_db_from_df(out, _MANAGER_TABLE, cols_type, False, "`code`,`manager`")

    rows = len(out.index)
    record_task_end(_JOB_NAME, 'manager', job_date, start, success=True,
                    message=f"{rows} 条经理记录（{out['code'].nunique()} 只基金）", rows_affected=rows)
    logging.info(f"fetch_fund_manager_job 完成：{rows} 条 / {out['code'].nunique()} 只基金")
    return rows


def main():
    args = [a for a in sys.argv[1:] if a.strip()]
    keep_all = '--all' in args
    codes = [a for a in args if a != '--all']
    run(codes=codes or None, keep_all=keep_all)


if __name__ == '__main__':
    main()
