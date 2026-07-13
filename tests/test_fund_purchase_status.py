# -*- coding: utf-8 -*-
import datetime
from unittest import mock

import pandas as pd
import pytest

import quantia.core.tablestructure as tbs
from quantia.core.fund import purchase_status
from quantia.job import fetch_fund_purchase_status_job as job
from quantia.job import analysis_fund_pick_job as pick_job
from quantia.web import fundPurchaseStatusHandler as purchase_handler


def test_classify_purchase_status_and_staleness():
    as_of = datetime.date(2026, 7, 13)
    fresh = datetime.datetime(2026, 7, 12, 23, 0)
    assert purchase_status.classify('开放申购', fresh, as_of) == 'available'
    assert purchase_status.classify('限大额', fresh, as_of) == 'limited'
    assert purchase_status.classify('暂停申购', fresh, as_of) == 'unavailable'
    assert purchase_status.classify('新状态', fresh, as_of) == 'unknown'
    assert purchase_status.classify('开放申购', datetime.date(2026, 7, 10), as_of) == 'unknown'
    assert purchase_status.classify('开放申购', datetime.date(2026, 7, 14), as_of) == 'unknown'
    assert purchase_status.classify('开放申购', None, as_of) == 'unknown'


def test_fetch_job_upserts_aligned_current_state():
    source = pd.DataFrame({
        'code': ['000001'], 'name': ['基金A'],
        'purchase_status': ['开放申购'], 'redemption_status': ['开放赎回'],
        'next_open_date': [None], 'min_purchase': [10.0],
        'daily_limit': [100000.0], 'fee': [0.15],
    })
    captured = {}

    def fake_insert(frame, table, cols_type, write_index, primary_keys):
        captured['columns'] = list(frame.columns)
        captured['table'] = table
        captured['primary_keys'] = primary_keys

    with mock.patch.object(job.fund_em, 'fund_purchase_status_all', return_value=source), \
         mock.patch.object(job.mdb, 'checkTableIsExist', return_value=True), \
         mock.patch.object(job.mdb, 'insert_db_from_df', side_effect=fake_insert), \
         mock.patch.object(job, 'record_task_start', return_value=0.0), \
         mock.patch.object(job, 'record_task_end'):
        count = job.run(fetched_at=datetime.datetime(2026, 7, 13, 8, 0))
    assert count == 1
    assert captured['columns'] == list(tbs.TABLE_CN_FUND_PURCHASE_STATUS['columns'])
    assert captured['table'] == tbs.TABLE_CN_FUND_PURCHASE_STATUS['name']
    assert captured['primary_keys'] == '`code`'


def test_fetch_job_empty_source_preserves_table():
    with mock.patch.object(job.fund_em, 'fund_purchase_status_all', return_value=None), \
         mock.patch.object(job.mdb, 'insert_db_from_df') as insert, \
         mock.patch.object(job, 'record_task_start', return_value=0.0), \
         mock.patch.object(job, 'record_task_end'):
        assert job.run(fetched_at=datetime.datetime(2026, 7, 13, 8, 0)) == 0
    insert.assert_not_called()


def test_fetch_job_main_exits_nonzero_when_source_is_empty():
    with mock.patch.object(job, 'run', return_value=0):
        with pytest.raises(SystemExit) as exc:
            job.main()
    assert exc.value.code == 3


def test_pick_filter_removes_unavailable_and_keeps_limited_unknown():
    pick_date = datetime.date(2026, 7, 13)
    candidates = [
        {'code': '000001', 'quality_score': 99},
        {'code': '000002', 'quality_score': 98},
        {'code': '000003', 'quality_score': 97},
    ]
    status_map = {
        '000001': {'purchase_status': '暂停申购', 'purchase_as_of': pick_date},
        '000002': {'purchase_status': '限大额', 'daily_limit': 100.0,
                   'purchase_as_of': pick_date},
    }
    out = pick_job._apply_purchase_status(candidates, status_map, pick_date)
    assert [row['code'] for row in out] == ['000002', '000003']
    assert out[0]['purchase_availability'] == 'limited'
    assert out[0]['daily_limit'] == 100.0
    assert out[1]['purchase_availability'] == 'unknown'


def test_pick_main_exits_nonzero_when_no_picks_generated():
    with mock.patch.object(pick_job, 'run', return_value=0), \
         mock.patch.object(pick_job.sys, 'argv', ['analysis_fund_pick_job.py']):
        try:
            pick_job.main()
        except SystemExit as exc:
            assert exc.code == 3
        else:
            raise AssertionError('zero-pick main must exit nonzero')


def test_pick_schema_migration_adds_only_missing_columns():
    existing = [('date',), ('purchase_status',)]
    with mock.patch.object(pick_job.mdb, 'checkTableIsExist', return_value=True), \
         mock.patch.object(pick_job.mdb, 'executeSqlFetch', return_value=existing), \
         mock.patch.object(pick_job.mdb, 'executeSql') as execute:
        pick_job._ensure_pick_purchase_columns()
    statements = [call.args[0] for call in execute.call_args_list]
    assert len(statements) == 4
    assert all('purchase_status' not in statement for statement in statements)
    assert any('purchase_availability' in statement for statement in statements)


def test_purchase_handler_returns_unknown_for_missing_table():
    with mock.patch.object(purchase_handler.mdb, 'checkTableIsExist', return_value=False):
        result = purchase_handler.load_purchase_status('000001')
    assert result['data_available'] is False
    assert result['availability'] == 'unknown'


def test_purchase_handler_classifies_fresh_row():
    row = [('限大额', '开放赎回', None, 10.0, 100.0, 0.15,
            datetime.datetime(2026, 7, 13, 8, 0))]
    with mock.patch.object(purchase_handler.mdb, 'checkTableIsExist', return_value=True), \
         mock.patch.object(purchase_handler.mdb, 'executeSqlFetch', return_value=row):
        result = purchase_handler.load_purchase_status(
            '017730', as_of=datetime.date(2026, 7, 13))
    assert result['availability'] == 'limited'
    assert result['daily_limit'] == 100.0