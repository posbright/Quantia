# -*- coding: utf-8 -*-
import datetime
from unittest import mock

from quantia.core.fund import data_readiness
from quantia.job import analysis_fund_score_job as score_job


def test_readiness_accepts_threshold_boundary():
    result = data_readiness.evaluate(
        datetime.date(2026, 7, 10), datetime.date(2026, 7, 10),
        90, [100, 100, 100], 900, 1000)
    assert result['ready'] is True
    assert result['size_ratio'] == 0.9
    assert result['freshness_ratio'] == 0.9


def test_readiness_rejects_old_snapshot_and_89_percent():
    result = data_readiness.evaluate(
        datetime.date(2026, 7, 9), datetime.date(2026, 7, 10),
        89, [100, 100, 100], 890, 1000)
    assert result['ready'] is False
    assert len(result['reasons']) == 3


def test_check_rank_readiness_t_plus_one_uses_previous_trade_day():
    snapshots = [
        (datetime.date(2026, 7, 10), 20486),
        (datetime.date(2026, 7, 9), 20460),
        (datetime.date(2026, 7, 8), 20449),
    ]
    responses = [
        snapshots,
        [(datetime.date(2026, 7, 10),)],
        [(datetime.date(2026, 7, 9),)],
        [(19500, 19900)],
    ]
    with mock.patch.object(score_job.mdb, 'executeSqlFetch', side_effect=responses):
        result = score_job.check_rank_readiness(datetime.date(2026, 7, 13))
    assert result['ready'] is True
    assert result['schedule_mode'] == 't_plus_one'
    assert result['expected_snapshot'] == datetime.date(2026, 7, 10)
    assert result['target_nav_date'] == datetime.date(2026, 7, 9)


def test_check_rank_readiness_same_day_accepts_current_trade_day():
    responses = [
        [(datetime.date(2026, 7, 13), 20486),
         (datetime.date(2026, 7, 10), 20460)],
        [(datetime.date(2026, 7, 13),)],
        [(datetime.date(2026, 7, 10),)],
        [(19500, 19900)],
    ]
    with mock.patch.dict('os.environ', {'QUANTIA_ANALYSIS_SAME_DAY': '1'}), \
         mock.patch.object(score_job.mdb, 'executeSqlFetch', side_effect=responses) as fetch:
        result = score_job.check_rank_readiness(datetime.date(2026, 7, 13))
    assert result['ready'] is True
    assert result['schedule_mode'] == 'same_day'
    assert '<= %s' in fetch.call_args_list[1].args[0]


def test_check_rank_readiness_same_day_rejects_stale_snapshot():
    responses = [
        [(datetime.date(2026, 7, 10), 20486),
         (datetime.date(2026, 7, 9), 20460)],
        [(datetime.date(2026, 7, 13),)],
        [(datetime.date(2026, 7, 9),)],
        [(19500, 19900)],
    ]
    with mock.patch.dict('os.environ', {'QUANTIA_ANALYSIS_SAME_DAY': '1'}), \
         mock.patch.object(score_job.mdb, 'executeSqlFetch', side_effect=responses):
        result = score_job.check_rank_readiness(datetime.date(2026, 7, 13))
    assert result['ready'] is False
    assert '最新基金快照 2026-07-10，期望 2026-07-13' in result['reasons']


def test_check_rank_readiness_weekend_uses_last_trade_day():
    responses = [
        [(datetime.date(2026, 7, 10), 20486),
         (datetime.date(2026, 7, 9), 20460)],
        [(datetime.date(2026, 7, 10),)],
        [(datetime.date(2026, 7, 9),)],
        [(19500, 19900)],
    ]
    with mock.patch.object(score_job.mdb, 'executeSqlFetch', side_effect=responses):
        result = score_job.check_rank_readiness(datetime.date(2026, 7, 12))
    assert result['ready'] is True
    assert result['expected_snapshot'] == datetime.date(2026, 7, 10)


def test_score_run_stops_before_build_when_not_ready():
    readiness = {'ready': False, 'reasons': ['新鲜度不足']}
    with mock.patch.object(score_job, 'check_rank_readiness', return_value=readiness), \
         mock.patch.object(score_job, 'build_score_df') as build, \
         mock.patch.object(score_job, 'record_task_start', return_value=0.0), \
         mock.patch.object(score_job, 'record_task_end'):
        assert score_job.run(job_date=datetime.date(2026, 7, 13)) == 0
    build.assert_not_called()