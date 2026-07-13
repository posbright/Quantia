# -*- coding: utf-8 -*-
import datetime
from unittest import mock

from quantia.job import analysis_fund_pick_compensation_job as job


def _ready(score_as_of):
    return {'ready': True, 'expected_snapshot': score_as_of, 'reasons': []}


def test_existing_pick_only_retries_exact_notification_date():
    job_date = datetime.date(2026, 7, 13)
    score_as_of = datetime.date(2026, 7, 10)
    pick_date = datetime.date(2026, 7, 11)
    with mock.patch.object(job.score_job, 'check_rank_readiness', return_value=_ready(score_as_of)), \
         mock.patch.object(job, '_existing_pick_date', return_value=pick_date), \
         mock.patch.object(job.score_job, 'run') as score, \
         mock.patch.object(job.pick_job, 'run') as pick, \
         mock.patch.object(job.notify_job, 'run', return_value={'reason': 'duplicate'}) as notify, \
         mock.patch.object(job, 'record_task_start', return_value=0.0), \
         mock.patch.object(job, 'record_task_end'):
        assert job.run(job_date) == 1
    score.assert_not_called()
    pick.assert_not_called()
    notify.assert_called_once_with(pick_date=pick_date, job_date=job_date)


def test_compensation_stops_when_readiness_still_fails():
    readiness = {'ready': False, 'expected_snapshot': datetime.date(2026, 7, 10),
                 'reasons': ['新鲜度不足']}
    with mock.patch.object(job.score_job, 'check_rank_readiness', return_value=readiness), \
         mock.patch.object(job, '_existing_pick_date', return_value=None), \
         mock.patch.object(job.score_job, 'run') as score, \
         mock.patch.object(job, 'record_task_start', return_value=0.0), \
         mock.patch.object(job, 'record_task_end'):
        assert job.run(datetime.date(2026, 7, 13)) == 0
    score.assert_not_called()


def test_compensation_rebuilds_exact_trade_date_and_notifies_it():
    job_date = datetime.date(2026, 7, 13)
    score_as_of = datetime.date(2026, 7, 10)
    with mock.patch.object(job.score_job, 'check_rank_readiness', return_value=_ready(score_as_of)), \
         mock.patch.object(job, '_existing_pick_date', return_value=None), \
         mock.patch.object(job.score_job, 'run', return_value=100) as score, \
         mock.patch.object(job.pick_job, 'run', return_value=70) as pick, \
         mock.patch.object(job.notify_job, 'run', return_value={'reason': 'sent'}) as notify, \
         mock.patch.object(job, 'record_task_start', return_value=0.0), \
         mock.patch.object(job, 'record_task_end'):
        assert job.run(job_date) == 70
    score.assert_called_once_with(score_date=score_as_of, job_date=job_date)
    pick.assert_called_once_with(pick_date=score_as_of, job_date=job_date)
    notify.assert_called_once_with(pick_date=score_as_of, job_date=job_date)