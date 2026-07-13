#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P0-B 基金评分、精选与通知补偿作业（Analysis 管道）。"""

import datetime
import logging
import os.path
import sys

cpath_current = os.path.dirname(os.path.dirname(__file__))
cpath = os.path.abspath(os.path.join(cpath_current, os.pardir))
sys.path.append(cpath)

import quantia.core.tablestructure as tbs
import quantia.lib.database as mdb
from quantia.job import analysis_fund_pick_job as pick_job
from quantia.job import analysis_fund_score_job as score_job
from quantia.job import notify_fund_pick_job as notify_job
from quantia.lib.job_tracker import record_task_end, record_task_start

_JOB_NAME = 'run_fund_pick_compensation'
_PICK_TABLE = tbs.TABLE_CN_FUND_DAILY_PICK['name']


def _existing_pick_date(score_as_of):
    if score_as_of is None or not mdb.checkTableIsExist(_PICK_TABLE):
        return None
    rows = mdb.executeSqlFetch(
        f"SELECT MAX(`date`) FROM `{_PICK_TABLE}` WHERE `score_as_of` = %s",
        (score_as_of,)) or []
    return rows[0][0] if rows and rows[0] else None


def run(job_date=None):
    job_date = job_date or datetime.date.today()
    start = record_task_start(_JOB_NAME, 'compensate', job_date)
    try:
        readiness = score_job.check_rank_readiness(job_date)
        score_as_of = readiness.get('expected_snapshot')
        existing_pick_date = _existing_pick_date(score_as_of)

        if existing_pick_date is not None:
            result = notify_job.run(pick_date=existing_pick_date, job_date=job_date)
            success = result.get('reason') != 'no_data'
            record_task_end(
                _JOB_NAME, 'compensate', job_date, start, success=success,
                message=f'既有榜单 {existing_pick_date}，通知结果 {result.get("reason")}',
                rows_affected=0)
            return 1 if success else 0

        if not readiness.get('ready') or score_as_of is None:
            message = '基金补偿数据未就绪：' + '；'.join(readiness.get('reasons') or [])
            record_task_end(_JOB_NAME, 'compensate', job_date, start, success=False,
                            message=message, rows_affected=0)
            logging.warning('%s；metrics=%s', message, readiness)
            return 0

        score_count = score_job.run(score_date=score_as_of, job_date=job_date)
        if score_count <= 0:
            record_task_end(_JOB_NAME, 'compensate', job_date, start, success=False,
                            message='基金补偿评分零产出', rows_affected=0)
            return 0

        pick_count = pick_job.run(pick_date=score_as_of, job_date=job_date)
        if pick_count <= 0:
            record_task_end(_JOB_NAME, 'compensate', job_date, start, success=False,
                            message='基金补偿精选零产出', rows_affected=0)
            return 0

        result = notify_job.run(pick_date=score_as_of, job_date=job_date)
        success = result.get('reason') != 'no_data'
        record_task_end(
            _JOB_NAME, 'compensate', job_date, start, success=success,
            message=f'补偿评分 {score_count}、精选 {pick_count}，通知 {result.get("reason")}',
            rows_affected=pick_count if success else 0)
        return pick_count if success else 0
    except Exception as exc:
        record_task_end(_JOB_NAME, 'compensate', job_date, start, success=False,
                        message=str(exc), rows_affected=0)
        logging.error('analysis_fund_pick_compensation_job 失败', exc_info=True)
        raise


def main():
    if run() <= 0:
        raise SystemExit(3)


if __name__ == '__main__':
    main()