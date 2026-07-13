#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P0-A 基金申购/赎回当前状态 Fetch job。"""

import datetime
import logging
import os.path
import sys

cpath_current = os.path.dirname(os.path.dirname(__file__))
cpath = os.path.abspath(os.path.join(cpath_current, os.pardir))
sys.path.append(cpath)

import quantia.core.tablestructure as tbs
import quantia.lib.database as mdb
from quantia.core.crawling import fund_em
from quantia.lib.job_tracker import record_task_end, record_task_start

_JOB_NAME = 'run_fund_purchase_status'
_TABLE = tbs.TABLE_CN_FUND_PURCHASE_STATUS['name']
_COLUMNS = list(tbs.TABLE_CN_FUND_PURCHASE_STATUS['columns'])


def run(fetched_at=None, job_date=None):
    fetched_at = fetched_at or datetime.datetime.now()
    job_date = job_date or fetched_at.date()
    start = record_task_start(_JOB_NAME, 'purchase_status', job_date)
    try:
        df = fund_em.fund_purchase_status_all()
        if df is None or len(df.index) == 0:
            record_task_end(_JOB_NAME, 'purchase_status', job_date, start, success=False,
                            message='申购状态源返回空数据，保留旧表', rows_affected=0)
            logging.warning('fetch_fund_purchase_status_job: 源返回空数据，保留旧表')
            return 0
        out = df.copy()
        out['fetched_at'] = fetched_at
        for column in _COLUMNS:
            if column not in out.columns:
                out[column] = None
        out = out[_COLUMNS].astype(object).where(out.notna(), None)
        cols_type = None if mdb.checkTableIsExist(_TABLE) else \
            tbs.get_field_types(tbs.TABLE_CN_FUND_PURCHASE_STATUS['columns'])
        mdb.insert_db_from_df(out, _TABLE, cols_type, False, '`code`')
        rows = len(out.index)
        record_task_end(_JOB_NAME, 'purchase_status', job_date, start, success=True,
                        message=f'更新 {rows} 只基金申购状态', rows_affected=rows)
        logging.info('fetch_fund_purchase_status_job 完成：%s 只', rows)
        return rows
    except Exception as exc:
        record_task_end(_JOB_NAME, 'purchase_status', job_date, start, success=False,
                        message=str(exc), rows_affected=0)
        logging.error('fetch_fund_purchase_status_job 失败', exc_info=True)
        raise


if __name__ == '__main__':
    run()