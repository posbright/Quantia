# -*- coding: utf-8 -*-
import datetime
from unittest import mock

import pandas as pd
import pytest

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


@pytest.mark.parametrize('value', ['nan', 'inf', '0', '-0.1', '1.1'])
def test_completeness_threshold_rejects_unsafe_values(value):
    with mock.patch.dict('os.environ', {'QUANTIA_FUND_COMPLETENESS_THRESHOLD': value}):
        with pytest.raises(ValueError):
            score_job._completeness_threshold()


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


def test_load_rank_snapshot_uses_exact_replay_date():
    replay_date = datetime.date(2026, 7, 10)
    frame = pd.DataFrame({'code': ['000001']})
    with mock.patch.object(score_job.mdb, 'checkTableIsExist', return_value=True), \
         mock.patch.object(score_job.mdb, 'engine', return_value=object()), \
         mock.patch.object(score_job.pd, 'read_sql', return_value=frame) as read_sql, \
         mock.patch.object(score_job.mdb, 'executeSqlFetch') as fetch:
        result, snapshot = score_job._load_rank_snapshot(replay_date)
    assert snapshot == replay_date
    assert result['code'].tolist() == ['000001']
    assert read_sql.call_args.kwargs['params'] == (replay_date,)
    assert 'WHERE `date` = %s' in read_sql.call_args.args[0]
    fetch.assert_not_called()


def test_score_run_allow_stale_skips_gate_but_uses_requested_date():
    replay_date = datetime.date(2026, 7, 10)
    scored = pd.DataFrame({'code': ['000001']})
    with mock.patch.object(score_job, 'check_rank_readiness') as readiness, \
         mock.patch.object(score_job, 'build_score_df', return_value=(scored, replay_date)) as build, \
         mock.patch.object(score_job, '_save_scores', return_value=1), \
         mock.patch.object(score_job, 'record_task_start', return_value=0.0), \
         mock.patch.object(score_job, 'record_task_end'):
        assert score_job.run(score_date=replay_date, allow_stale=True) == 1
    readiness.assert_not_called()
    build.assert_called_once_with(replay_date)


def test_historical_auxiliary_queries_are_bounded_by_score_date():
    replay_date = datetime.date(2026, 7, 10)
    with mock.patch.object(score_job.mdb, 'checkTableIsExist', return_value=True), \
         mock.patch.object(score_job.mdb, 'executeSqlFetch', return_value=[]) as fetch:
        score_job._load_scale_map(replay_date)
    assert '`update_date` <= %s' in fetch.call_args.args[0]
    assert fetch.call_args.args[1] == (replay_date,)

    with mock.patch.object(score_job.mdb, 'engine', return_value=object()), \
         mock.patch.object(score_job.pd, 'read_sql', return_value=pd.DataFrame()) as read_sql:
        score_job._load_nav_series('000001', replay_date)
    assert '`nav_date` <= %s' in read_sql.call_args.args[0]
    assert read_sql.call_args.kwargs['params'] == ('000001', replay_date)


@pytest.mark.parametrize('argv', [
    ['analysis_fund_score_job.py', '--date=2026-07-10'],
    ['analysis_fund_score_job.py', '--allow-stale'],
])
def test_score_main_requires_date_and_allow_stale_together(argv):
    with mock.patch.object(score_job.sys, 'argv', argv), \
         mock.patch.object(score_job, 'run') as run:
        with pytest.raises(SystemExit):
            score_job.main()
    run.assert_not_called()