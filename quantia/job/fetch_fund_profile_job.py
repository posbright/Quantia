#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""F10 基金规模 + 画像缓存（独立慢 job，周/月频）。

逐基金抓取 fund_individual_basic_info_xq（规模/公司/经理/评级/策略/基准），
透视为单行 upsert 写 cn_fund_profile（主键 code 覆盖），供规模因子 +
投资价值分析。规模/经理/评级季度级稳定，不必每日。

抓取范围：默认覆盖各 fund_type 桶按近1年收益的 Top-N（含货币型，画像通用）。
属 fetch 管道（akshare 单源）。低频 cron（cron.monthly）或手动触发。

用法：
    python fetch_fund_profile_job.py [code1 code2 ...]
    python fetch_fund_profile_job.py
"""
import datetime
import logging
import os.path
import random
import sys
import time

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
        filename=os.path.join(log_path, 'fund_profile_job.log'),
        level=logging.INFO,
    )

import quantia.core.tablestructure as tbs
import quantia.core.crawling.fund_em as fem
import quantia.lib.database as mdb
import quantia.lib.envconfig as _cfg
from quantia.lib.job_tracker import record_task_start, record_task_end

__author__ = 'Quantia'
__date__ = '2026/06/01'

_JOB_NAME = 'run_fund_profile'
_RANK_TABLE = tbs.TABLE_CN_FUND_RANK['name']
_PROFILE_TABLE = tbs.TABLE_CN_FUND_PROFILE['name']
_PROFILE_COLS = list(tbs.TABLE_CN_FUND_PROFILE['columns'])


def _select_target_codes(limit_per_type):
    """各 fund_type 桶按近1年收益取 Top-N 的 code（含货币型）。"""
    if not mdb.checkTableIsExist(_RANK_TABLE):
        return []
    sql = (
        f"SELECT code FROM ("
        f"  SELECT code,"
        f"    ROW_NUMBER() OVER (PARTITION BY fund_type ORDER BY (`rate_1y` IS NULL), `rate_1y` DESC) AS rn"
        f"  FROM `{_RANK_TABLE}`"
        f"  WHERE `date` = (SELECT MAX(`date`) FROM `{_RANK_TABLE}`)"
        f") t WHERE t.rn <= %s"
    )
    rows = mdb.executeSqlFetch(sql, (int(limit_per_type),))
    return [str(r[0]) for r in rows if r and r[0] is not None]


def save_fund_profile(code, update_date):
    """抓取 + upsert 单只基金画像，返回 1（成功）/ 0（无数据/失败）。"""
    row = fem.fund_profile(code)
    if not row:
        return 0
    row['update_date'] = update_date
    # 对齐表列序，缺失列补 None
    data = {c: row.get(c) for c in _PROFILE_COLS}
    df = pd.DataFrame([data])[_PROFILE_COLS]

    cols_type = None
    if not mdb.checkTableIsExist(_PROFILE_TABLE):
        cols_type = tbs.get_field_types(tbs.TABLE_CN_FUND_PROFILE['columns'])
    mdb.insert_db_from_df(df, _PROFILE_TABLE, cols_type, False, "`code`")
    return 1


def run(codes=None, limit_per_type=None, job_date=None):
    job_date = job_date or datetime.date.today()
    update_date = job_date
    if limit_per_type is None:
        limit_per_type = _cfg.get_int('QUANTIA_FUND_PROFILE_TOPN', 200)
    if not codes:
        codes = _select_target_codes(limit_per_type)
    if not codes:
        logging.warning("fetch_fund_profile_job: 无目标基金（cn_fund_rank 为空？）")
        return 0

    start = record_task_start(_JOB_NAME, 'profile', job_date)
    ok = 0
    for code in codes:
        try:
            ok += save_fund_profile(code, update_date)
        except Exception:
            logging.warning(f"fetch_fund_profile_job: {code} 处理失败，跳过", exc_info=True)
        finally:
            time.sleep(random.uniform(0.5, 1.5))  # 限速
    record_task_end(_JOB_NAME, 'profile', job_date, start, success=True,
                    message=f"{ok}/{len(codes)} 基金画像更新", rows_affected=ok)
    logging.info(f"fetch_fund_profile_job 完成：{ok}/{len(codes)} 基金画像")
    return ok


def main():
    args = [a for a in sys.argv[1:] if a.strip()]
    run(codes=args or None)


if __name__ == '__main__':
    main()
