#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Comprehensive unit tests for quantia/job/ modules.

All DB/network/subprocess calls are mocked. Focus on:
- Control flow logic (what gets called, in what order)
- Skip/freshness checks (job deduplication)
- Error handling (subprocess failures, missing data, retries)
"""

import datetime
import gc
import importlib
import logging
import os
import subprocess
import sys
import time
import unittest
from unittest.mock import patch, MagicMock, call

import pandas as pd

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path so `quantia.*` is importable
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, os.pardir))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Also add quantia/job so job modules can find peer imports (init_job, etc.)
_JOB_DIR = os.path.join(_ROOT, 'quantia', 'job')
if _JOB_DIR not in sys.path:
    sys.path.insert(0, _JOB_DIR)

# ---------------------------------------------------------------------------
# Shared test constants
# ---------------------------------------------------------------------------
TEST_DATE = datetime.datetime(2026, 3, 18)
TEST_DATE_STR = '2026-03-18'

# Convenience shorthand for modules
_mdb = 'quantia.lib.database'
_trd = 'quantia.lib.trade_time'
_stf = 'quantia.core.stockfetch'


# ============================================================================
# 1. execute_daily_job
# ============================================================================
class TestExecuteDailyJob(unittest.TestCase):
    """Tests for execute_daily_job.py — _run_job_subprocess, _is_analysis_done,
    _check_and_skip, _data_health_check, main."""

    def _mod(self):
        import quantia.job.execute_daily_job as edj
        return edj

    # -- _run_job_subprocess -----------------------------------------------
    @patch('subprocess.run')
    def test_run_job_subprocess_success(self, mock_run):
        """Subprocess returns 0 → True."""
        edj = self._mod()
        mock_run.return_value = MagicMock(returncode=0)
        self.assertTrue(edj._run_job_subprocess('dummy.py', 'label', timeout=60))

    @patch('subprocess.run')
    def test_run_job_subprocess_nonzero(self, mock_run):
        """Subprocess returns non-zero → False."""
        edj = self._mod()
        mock_run.return_value = MagicMock(returncode=1)
        self.assertFalse(edj._run_job_subprocess('dummy.py', 'label'))

    @patch('subprocess.run', side_effect=subprocess.TimeoutExpired('x', 10))
    def test_run_job_subprocess_timeout(self, mock_run):
        """Subprocess times out → False."""
        edj = self._mod()
        self.assertFalse(edj._run_job_subprocess('dummy.py', 'label', timeout=10))

    @patch('subprocess.run', side_effect=OSError('no such file'))
    def test_run_job_subprocess_oserror(self, mock_run):
        """Subprocess raises OSError → False."""
        edj = self._mod()
        self.assertFalse(edj._run_job_subprocess('dummy.py', 'label'))

    # -- _is_analysis_done -------------------------------------------------
    def test_is_analysis_done_force_env(self):
        """QUANTIA_FORCE_ANALYSIS=1 → always False (force run)."""
        edj = self._mod()
        with patch.object(edj._cfg, 'get_bool', return_value=True):
            self.assertFalse(edj._is_analysis_done(TEST_DATE))

    @patch(f'{_mdb}.executeSqlFetch')
    @patch(f'{_mdb}.checkTableIsExist', return_value=False)
    def test_is_analysis_done_table_missing(self, mock_exist, mock_fetch):
        """Table doesn't exist → False."""
        edj = self._mod()
        with patch.object(edj._cfg, 'get_bool', return_value=False):
            self.assertFalse(edj._is_analysis_done(TEST_DATE))

    @patch(f'{_mdb}.executeSqlFetch', return_value=[[2000]])
    @patch(f'{_mdb}.checkTableIsExist', return_value=True)
    def test_is_analysis_done_above_threshold(self, mock_exist, mock_fetch):
        """Row count >= threshold → True."""
        edj = self._mod()
        old = edj.ANALYSIS_DONE_THRESHOLD
        try:
            edj.ANALYSIS_DONE_THRESHOLD = 1000
            with patch.object(edj._cfg, 'get_bool', return_value=False):
                self.assertTrue(edj._is_analysis_done(TEST_DATE))
        finally:
            edj.ANALYSIS_DONE_THRESHOLD = old

    @patch(f'{_mdb}.executeSqlFetch', return_value=[[500]])
    @patch(f'{_mdb}.checkTableIsExist', return_value=True)
    def test_is_analysis_done_below_threshold(self, mock_exist, mock_fetch):
        """Row count < threshold → False."""
        edj = self._mod()
        old = edj.ANALYSIS_DONE_THRESHOLD
        try:
            edj.ANALYSIS_DONE_THRESHOLD = 1000
            with patch.object(edj._cfg, 'get_bool', return_value=False):
                self.assertFalse(edj._is_analysis_done(TEST_DATE))
        finally:
            edj.ANALYSIS_DONE_THRESHOLD = old

    @patch(f'{_mdb}.checkTableIsExist', side_effect=Exception('db err'))
    def test_is_analysis_done_exception_returns_false(self, _):
        """Exception during check → False (continue execution)."""
        edj = self._mod()
        with patch.object(edj._cfg, 'get_bool', return_value=False):
            self.assertFalse(edj._is_analysis_done(TEST_DATE))

    # -- _check_and_skip ---------------------------------------------------
    def test_check_and_skip_force_fetch(self):
        """QUANTIA_FORCE_FETCH=1 → never skip."""
        edj = self._mod()
        with patch.object(edj._cfg, 'get_bool', return_value=True):
            self.assertFalse(edj._check_and_skip('cn_stock_spot', TEST_DATE_STR, 'test'))

    @patch(f'{_trd}.is_post_settlement', return_value=False)
    def test_check_and_skip_pre_settlement(self, _):
        """Before settlement → don't skip."""
        edj = self._mod()
        with patch.object(edj._cfg, 'get_bool', return_value=False):
            self.assertFalse(edj._check_and_skip('cn_stock_spot', TEST_DATE_STR, 'test'))

    @patch('quantia.job.execute_daily_job.is_data_fresh', return_value=(True, 5000))
    @patch(f'{_trd}.is_post_settlement', return_value=True)
    def test_check_and_skip_fresh_data(self, mock_settle, mock_fresh):
        """Post-settlement + fresh data → skip (True)."""
        edj = self._mod()
        with patch.object(edj._cfg, 'get_bool', return_value=False):
            self.assertTrue(edj._check_and_skip('cn_stock_spot', TEST_DATE_STR, 'test'))

    @patch('quantia.job.execute_daily_job.is_data_fresh', return_value=(False, 10))
    @patch(f'{_trd}.is_post_settlement', return_value=True)
    def test_check_and_skip_stale_data(self, mock_settle, mock_fresh):
        """Post-settlement + stale data → don't skip."""
        edj = self._mod()
        with patch.object(edj._cfg, 'get_bool', return_value=False):
            self.assertFalse(edj._check_and_skip('cn_stock_spot', TEST_DATE_STR, 'test'))

    # -- _data_health_check ------------------------------------------------
    @patch(f'{_mdb}.executeSqlFetch', return_value=None)
    @patch(f'{_mdb}.checkTableIsExist', return_value=False)
    def test_data_health_check_no_crash(self, mock_exist, mock_fetch):
        """Health check logs but never raises."""
        edj = self._mod()
        try:
            edj._data_health_check(time.time(), TEST_DATE)
        except Exception:
            self.fail("_data_health_check raised an exception")

    # -- main 4-phase pipeline (smoke) -------------------------------------
    @patch('quantia.job.execute_daily_job._data_health_check')
    @patch('quantia.job.execute_daily_job._is_analysis_done', return_value=False)
    @patch('quantia.job.execute_daily_job._run_job_subprocess', return_value=True)
    @patch('quantia.job.execute_daily_job._check_and_skip', return_value=False)
    @patch('quantia.job.execute_daily_job._run_stock_spot_buy')
    @patch(f'{_trd}.get_trade_date_last', return_value=(TEST_DATE, TEST_DATE))
    def test_main_calls_all_phases(self, mock_td, mock_buy, mock_skip,
                                    mock_sub, mock_done, mock_health):
        """main() calls all phases when nothing is skipped."""
        edj = self._mod()
        with patch.object(edj, 'record_task_start', return_value=time.time()), \
             patch.object(edj, 'record_task_end'), \
             patch.object(edj, 'record_task_skipped'), \
             patch.object(edj.bj, 'main'), \
             patch.object(edj.hdj, 'main'), \
             patch.object(edj.sddj, 'main'), \
             patch.object(edj.gptj, 'main'), \
             patch.object(edj.saj, 'main') as mock_saj, \
             patch.object(edj.bdj, 'main') as mock_bdj:
            edj.main()
            # Subprocess called at least for basic_data_other + after_close + kline_cache
            self.assertGreaterEqual(mock_sub.call_count, 2)
            mock_saj.assert_called()
            mock_bdj.assert_called()


# ============================================================================
# 2. basic_data_daily_job
# ============================================================================
class TestBasicDataDailyJob(unittest.TestCase):
    """Tests for basic_data_daily_job.py."""

    def _mod(self):
        import quantia.job.basic_data_daily_job as m
        return m

    @patch(f'{_mdb}.insert_db_from_df')
    @patch(f'{_mdb}.executeSql')
    @patch(f'{_mdb}.checkTableIsExist', return_value=True)
    def test_save_nph_stock_spot_data(self, mock_exists, mock_exec, mock_insert):
        """save_nph_stock_spot_data inserts when before=False."""
        m = self._mod()
        df = pd.DataFrame({'code': ['000001'], 'date': [TEST_DATE_STR], 'name': ['平安银行']})
        with patch('quantia.job.basic_data_daily_job.stock_data') as mock_sd:
            mock_sd.return_value.get_data.return_value = df
            m.save_nph_stock_spot_data(TEST_DATE, before=False)
        mock_insert.assert_called_once()

    def test_save_nph_stock_spot_data_before_returns(self):
        """before=True → return immediately, no DB calls."""
        m = self._mod()
        with patch(f'{_mdb}.insert_db_from_df') as mock_insert:
            m.save_nph_stock_spot_data(TEST_DATE, before=True)
            mock_insert.assert_not_called()

    @patch(f'{_mdb}.insert_db_from_df')
    @patch(f'{_mdb}.executeSql')
    @patch(f'{_mdb}.checkTableIsExist', return_value=True)
    @patch(f'{_stf}.fetch_etfs')
    def test_save_nph_etf_spot_data(self, mock_fetch, mock_exists, mock_exec, mock_insert):
        """save_nph_etf_spot_data calls fetch_etfs + insert."""
        m = self._mod()
        mock_fetch.return_value = pd.DataFrame({'code': ['510050'], 'date': [TEST_DATE_STR]})
        m.save_nph_etf_spot_data(TEST_DATE, before=False)
        mock_fetch.assert_called_once_with(TEST_DATE)
        mock_insert.assert_called_once()

    @patch(f'{_mdb}.insert_db_from_df')
    @patch(f'{_mdb}.executeSql')
    @patch(f'{_mdb}.checkTableIsExist', return_value=True)
    @patch(f'{_stf}.fetch_funds')
    def test_save_nph_fund_data(self, mock_fetch, mock_exists, mock_exec, mock_insert):
        """save_nph_fund_data calls fetch_funds + DELETE + insert."""
        m = self._mod()
        mock_fetch.return_value = pd.DataFrame({'code': ['000001'], 'date': [TEST_DATE_STR]})
        m.save_nph_fund_data(TEST_DATE, before=False)
        mock_fetch.assert_called_once_with(TEST_DATE)
        mock_exec.assert_called_once()
        mock_insert.assert_called_once()

    def test_save_nph_fund_data_before_returns(self):
        """before=True → return immediately, no fetch/insert."""
        m = self._mod()
        with patch(f'{_stf}.fetch_funds') as mock_fetch, \
             patch(f'{_mdb}.insert_db_from_df') as mock_insert:
            m.save_nph_fund_data(TEST_DATE, before=True)
            mock_fetch.assert_not_called()
            mock_insert.assert_not_called()

    @patch(f'{_mdb}.insert_db_from_df')
    @patch(f'{_mdb}.checkTableIsExist', return_value=True)
    @patch(f'{_stf}.fetch_funds', return_value=None)
    def test_save_nph_fund_data_no_data(self, mock_fetch, mock_exists, mock_insert):
        """fetch returns None → no DB write."""
        m = self._mod()
        m.save_nph_fund_data(TEST_DATE, before=False)
        mock_insert.assert_not_called()

    @patch(f'{_mdb}.insert_db_from_df')
    @patch(f'{_mdb}.executeSql')
    @patch(f'{_mdb}.checkTableIsExist', return_value=True)
    @patch(f'{_stf}.fetch_index_spots')
    def test_save_nph_index_spot_data(self, mock_fetch, mock_exists, mock_exec, mock_insert):
        """save_nph_index_spot_data calls fetch_index_spots + insert."""
        m = self._mod()
        mock_fetch.return_value = pd.DataFrame({'code': ['000001'], 'date': [TEST_DATE_STR]})
        m.save_nph_index_spot_data(TEST_DATE, before=False)
        mock_fetch.assert_called_once_with(TEST_DATE)
        mock_insert.assert_called_once()

    @patch(f'{_mdb}.insert_db_from_df')
    @patch(f'{_mdb}.checkTableIsExist', return_value=True)
    @patch(f'{_stf}.fetch_index_spots', return_value=None)
    def test_save_nph_index_spot_no_data(self, mock_fetch, mock_exists, mock_insert):
        """fetch returns None → no DB write."""
        m = self._mod()
        m.save_nph_index_spot_data(TEST_DATE, before=False)
        mock_insert.assert_not_called()

    @patch(f'{_trd}.get_trade_date_last', return_value=(TEST_DATE, TEST_DATE))
    def test_main_calls_all_three(self, mock_td):
        """main() calls all three save functions."""
        m = self._mod()
        with patch.object(sys, 'argv', ['basic_data_daily_job.py']), \
             patch.object(m, 'save_nph_stock_spot_data') as s1, \
             patch.object(m, 'save_nph_etf_spot_data') as s2, \
             patch.object(m, 'save_nph_index_spot_data') as s3:
            m.main()
            s1.assert_called_once()
            s2.assert_called_once()
            s3.assert_called_once()


# ============================================================================
# 3. basic_data_after_close_daily_job
# ============================================================================
class TestBasicDataAfterCloseDailyJob(unittest.TestCase):
    """Tests for basic_data_after_close_daily_job.py."""

    def _mod(self):
        import quantia.job.basic_data_after_close_daily_job as m
        return m

    @patch('time.sleep')
    def test_fetch_with_retry_success_first_try(self, mock_sleep):
        """Successful on first try → no retry, no sleep."""
        m = self._mod()
        fn = MagicMock(return_value=pd.DataFrame({'x': [1]}))
        result = m._fetch_with_retry(fn, 'test', retries=2, delay=1)
        self.assertIsNotNone(result)
        fn.assert_called_once()
        mock_sleep.assert_not_called()

    @patch('time.sleep')
    def test_fetch_with_retry_retries_on_empty(self, mock_sleep):
        """Empty result → retry → success."""
        m = self._mod()
        fn = MagicMock(side_effect=[None, pd.DataFrame({'x': [1]})])
        result = m._fetch_with_retry(fn, 'test', retries=1, delay=1)
        self.assertIsNotNone(result)
        self.assertEqual(fn.call_count, 2)
        mock_sleep.assert_called_once_with(1)

    @patch('time.sleep')
    def test_fetch_with_retry_retries_on_exception(self, mock_sleep):
        """Exception on first try → retry → success."""
        m = self._mod()
        fn = MagicMock(side_effect=[Exception('net err'), pd.DataFrame({'x': [1]})])
        result = m._fetch_with_retry(fn, 'test', retries=1, delay=5)
        self.assertIsNotNone(result)
        self.assertEqual(fn.call_count, 2)
        mock_sleep.assert_called_once_with(5)

    @patch('time.sleep')
    def test_fetch_with_retry_all_fail_raises(self, mock_sleep):
        """All attempts fail with exception → raises."""
        m = self._mod()
        fn = MagicMock(side_effect=Exception('persistent'))
        with self.assertRaises(Exception):
            m._fetch_with_retry(fn, 'test', retries=1, delay=1)
        self.assertEqual(fn.call_count, 2)

    @patch('time.sleep')
    def test_fetch_with_retry_all_empty(self, mock_sleep):
        """All attempts return None → returns None."""
        m = self._mod()
        fn = MagicMock(return_value=None)
        result = m._fetch_with_retry(fn, 'test', retries=1, delay=1)
        self.assertIsNone(result)
        self.assertEqual(fn.call_count, 2)

    @patch('time.sleep')
    def test_fetch_with_retry_zero_retries(self, mock_sleep):
        """retries=0 means only one attempt."""
        m = self._mod()
        fn = MagicMock(return_value=None)
        result = m._fetch_with_retry(fn, 'test', retries=0, delay=1)
        self.assertIsNone(result)
        fn.assert_called_once()

    @patch('time.sleep')
    def test_fetch_with_retry_exception_then_empty(self, mock_sleep):
        """Exception first try → empty on retry → None."""
        m = self._mod()
        fn = MagicMock(side_effect=[Exception('err'), None])
        result = m._fetch_with_retry(fn, 'test', retries=1, delay=1)
        self.assertIsNone(result)
        self.assertEqual(fn.call_count, 2)

    @patch(f'{_mdb}.insert_db_from_df')
    @patch(f'{_mdb}.executeSql')
    @patch(f'{_mdb}.checkTableIsExist', return_value=True)
    @patch(f'{_stf}.fetch_stock_blocktrade_data')
    def test_save_blocktrade(self, mock_fetch, mock_exists, mock_exec, mock_insert):
        """save_after_close_stock_blocktrade_data writes data."""
        m = self._mod()
        mock_fetch.return_value = pd.DataFrame({'code': ['000001'], 'date': [TEST_DATE_STR]})
        m.save_after_close_stock_blocktrade_data(TEST_DATE)
        mock_insert.assert_called_once()

    @patch(f'{_mdb}.insert_db_from_df')
    @patch(f'{_mdb}.executeSql')
    @patch(f'{_mdb}.checkTableIsExist', return_value=True)
    @patch(f'{_stf}.fetch_stock_chip_race_end')
    def test_save_chip_race_end(self, mock_fetch, mock_exists, mock_exec, mock_insert):
        """save_after_close_stock_chip_race_end_data writes data."""
        m = self._mod()
        mock_fetch.return_value = pd.DataFrame({'code': ['000001'], 'date': [TEST_DATE_STR]})
        m.save_after_close_stock_chip_race_end_data(TEST_DATE)
        mock_insert.assert_called_once()

    @patch('time.sleep')
    @patch('quantia.lib.run_template.run_with_args')
    def test_main_calls_both(self, mock_rwa, mock_sleep):
        """main() calls run_with_args for both functions."""
        m = self._mod()
        m.main()
        self.assertEqual(mock_rwa.call_count, 2)


# ============================================================================
# 4. basic_data_other_daily_job
# ============================================================================
class TestBasicDataOtherDailyJob(unittest.TestCase):
    """Tests for basic_data_other_daily_job.py."""

    def _mod(self):
        import quantia.job.basic_data_other_daily_job as m
        return m

    @patch('time.sleep')
    def test_fetch_with_retry_other_module(self, mock_sleep):
        """Distinct _fetch_with_retry in this module works correctly."""
        m = self._mod()
        fn = MagicMock(return_value=pd.DataFrame({'x': [1]}))
        result = m._fetch_with_retry(fn, 'test', retries=0, delay=1)
        self.assertIsNotNone(result)
        fn.assert_called_once()

    @patch('time.sleep')
    def test_fetch_with_retry_custom_delay(self, mock_sleep):
        """Custom delay is passed to time.sleep."""
        m = self._mod()
        fn = MagicMock(side_effect=[None, pd.DataFrame({'x': [1]})])
        m._fetch_with_retry(fn, 'test', retries=1, delay=42)
        mock_sleep.assert_called_once_with(42)

    def test_save_lhb_before_returns(self):
        """before=True → no fetch."""
        m = self._mod()
        with patch(f'{_stf}.fetch_stock_lhb_data') as mock_fetch:
            m.save_nph_stock_lhb_data(TEST_DATE, before=True)
            mock_fetch.assert_not_called()

    @patch(f'{_mdb}.insert_db_from_df')
    @patch(f'{_mdb}.executeSql')
    @patch(f'{_mdb}.checkTableIsExist', return_value=True)
    @patch(f'{_stf}.fetch_stock_lhb_data')
    def test_save_lhb_data(self, mock_fetch, mock_exists, mock_exec, mock_insert):
        """save_nph_stock_lhb_data fetches and inserts."""
        m = self._mod()
        mock_fetch.return_value = pd.DataFrame({'code': ['000001'], 'date': [TEST_DATE_STR]})
        m.save_nph_stock_lhb_data(TEST_DATE, before=False)
        mock_insert.assert_called_once()

    @patch(f'{_mdb}.engine')
    @patch(f'{_mdb}.insert_db_from_df')
    @patch(f'{_mdb}.executeSql')
    @patch(f'{_mdb}.checkTableIsExist', return_value=True)
    def test_stock_spot_buy(self, mock_exists, mock_exec, mock_insert, mock_engine):
        """stock_spot_buy reads + filters + inserts."""
        m = self._mod()
        df = pd.DataFrame({
            'code': ['000001'], 'date': [TEST_DATE],
            'pe9': [10], 'pbnewmrq': [5], 'roe_weight': [20],
        })
        with patch('pandas.read_sql', return_value=df):
            m.stock_spot_buy(TEST_DATE)
        mock_insert.assert_called_once()

    @patch('time.sleep')
    @patch('quantia.lib.run_template.run_with_args')
    def test_main_calls_all_tasks(self, mock_rwa, mock_sleep):
        """main() calls run_with_args for all 6 sub-tasks."""
        m = self._mod()
        m.main()
        self.assertEqual(mock_rwa.call_count, 6)


# ============================================================================
# 5. fetch_daily_job
# ============================================================================
class TestFetchDailyJob(unittest.TestCase):
    """Tests for fetch_daily_job.py."""

    def _mod(self):
        import quantia.job.fetch_daily_job as m
        return m

    @patch('subprocess.run')
    def test_run_job_subprocess_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        self.assertTrue(self._mod()._run_job_subprocess('dummy.py', 'label'))

    @patch('subprocess.run')
    def test_run_job_subprocess_fail(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1)
        self.assertFalse(self._mod()._run_job_subprocess('dummy.py', 'label'))

    @patch('subprocess.run', side_effect=subprocess.TimeoutExpired('x', 5))
    def test_run_job_subprocess_timeout(self, _):
        self.assertFalse(self._mod()._run_job_subprocess('dummy.py', 'label', timeout=5))

    def test_check_and_skip_force_fetch(self):
        m = self._mod()
        with patch.object(m._cfg, 'get_bool', return_value=True):
            self.assertFalse(m._check_and_skip('cn_stock_spot', TEST_DATE_STR, 'test'))

    @patch(f'{_trd}.is_post_settlement', return_value=False)
    def test_check_and_skip_pre_settlement(self, _):
        m = self._mod()
        with patch.object(m._cfg, 'get_bool', return_value=False):
            self.assertFalse(m._check_and_skip('cn_stock_spot', TEST_DATE_STR, 'test'))

    @patch('quantia.job.fetch_daily_job.is_data_fresh', return_value=(True, 5000))
    @patch(f'{_trd}.is_post_settlement', return_value=True)
    def test_check_and_skip_fresh_data_skips(self, mock_settle, mock_fresh):
        m = self._mod()
        with patch.object(m._cfg, 'get_bool', return_value=False):
            self.assertTrue(m._check_and_skip('cn_stock_spot', TEST_DATE_STR, 'test'))

    @patch('quantia.job.fetch_daily_job._run_job_subprocess', return_value=True)
    @patch('quantia.job.fetch_daily_job._check_and_skip', return_value=False)
    @patch(f'{_trd}.get_trade_date_last', return_value=(TEST_DATE, TEST_DATE))
    def test_main_runs_phases(self, mock_td, mock_skip, mock_sub):
        """main() invokes init, stock_spot, selection, subprocess phases."""
        m = self._mod()
        with patch.object(m, 'is_job_completed', return_value=False), \
             patch.object(m, 'record_task_start', return_value=time.time()), \
             patch.object(m, 'record_task_end'), \
             patch.object(m, 'record_task_skipped'), \
             patch.object(m, '_enrich_stock_spot_from_selection'), \
             patch.object(m.bj, 'main'), \
             patch.object(m.hdj, 'main') as mock_hdj, \
             patch.object(m.hdj, 'save_nph_fund_data') as mock_fund, \
             patch.object(m.sddj, 'main') as mock_sddj:
            m.main()
            mock_hdj.assert_called()
            mock_sddj.assert_called()
            mock_fund.assert_called_once()
            self.assertGreaterEqual(mock_sub.call_count, 2)

    def test_check_and_skip_passes_fund_settlement_hour(self):
        """基金 Phase 传入的 settlement_hour 须透传给 is_post_settlement。"""
        m = self._mod()
        with patch.object(m._cfg, 'get_bool', return_value=False), \
             patch(f'{_trd}.is_post_settlement', return_value=False) as mock_settle:
            m._check_and_skip('cn_fund_rank', TEST_DATE_STR, '基金排名', settlement_hour=23)
            mock_settle.assert_called_once_with(TEST_DATE_STR, settlement_hour=23)


# ============================================================================
# 6. fetch_data_job
# ============================================================================
class TestFetchDataJob(unittest.TestCase):
    """Tests for fetch_data_job.py — fetch_all_data()."""

    def _mod(self):
        import quantia.job.fetch_data_job as m
        return m

    @patch(f'{_stf}.update_index_caches', return_value=(10, 0))
    @patch(f'{_stf}.update_all_caches', return_value=(4800, 100))
    @patch(f'{_trd}.get_trade_hist_interval', return_value=('20230101', None))
    @patch(f'{_stf}.clean_expired_cache', return_value=5)
    def test_fetch_all_data_4_step_pipeline(self, mock_clean, mock_interval,
                                              mock_update, mock_index):
        """fetch_all_data follows the 4-step pipeline."""
        m = self._mod()
        import quantia.core.tablestructure as tbs
        fk_keys = list(tbs.TABLE_CN_STOCK_FOREIGN_KEY['columns'].keys())
        df = pd.DataFrame({k: ['000001' if k == 'code' else TEST_DATE_STR] for k in fk_keys})
        with patch('quantia.job.fetch_data_job.stock_data') as mock_sd:
            mock_sd.return_value.get_data.return_value = df
            m.fetch_all_data(TEST_DATE)
        mock_clean.assert_called_once()          # Step 1
        mock_update.assert_called_once()         # Step 3
        mock_index.assert_called_once()          # Step 4

    @patch(f'{_stf}.clean_expired_cache', return_value=0)
    def test_fetch_all_data_spot_none_aborts(self, mock_clean):
        """stock_data returns None → aborts early."""
        m = self._mod()
        with patch('quantia.job.fetch_data_job.stock_data') as mock_sd, \
             patch(f'{_stf}.update_all_caches') as mock_update:
            mock_sd.return_value.get_data.return_value = None
            m.fetch_all_data(TEST_DATE)
            mock_update.assert_not_called()

    @patch('quantia.lib.run_template.run_with_args')
    def test_main_delegates(self, mock_rwa):
        self._mod().main()
        mock_rwa.assert_called_once()


# ============================================================================
# 7. kline_cache_daily_job
# ============================================================================
class TestKlineCacheDailyJob(unittest.TestCase):
    """Tests for kline_cache_daily_job.py."""

    def _mod(self):
        import quantia.job.kline_cache_daily_job as m
        return m

    def test_check_fetch_completed_force_env(self):
        m = self._mod()
        with patch.object(m._cfg, 'get_bool', return_value=True):
            self.assertTrue(m._check_fetch_completed(TEST_DATE))

    @patch('quantia.job.kline_cache_daily_job.is_job_completed', return_value=True)
    def test_check_fetch_completed_job_done(self, _):
        m = self._mod()
        with patch.object(m._cfg, 'get_bool', return_value=False):
            self.assertTrue(m._check_fetch_completed(TEST_DATE))

    @patch('quantia.job.kline_cache_daily_job.is_job_completed', return_value=False)
    def test_check_fetch_completed_job_not_done(self, _):
        m = self._mod()
        with patch.object(m._cfg, 'get_bool', return_value=False):
            self.assertFalse(m._check_fetch_completed(TEST_DATE))

    @patch('quantia.lib.run_template.run_with_args')
    def test_main_delegates(self, mock_rwa):
        self._mod().main()
        mock_rwa.assert_called_once()


# ============================================================================
# 8. analysis_daily_job
# ============================================================================
class TestAnalysisDailyJob(unittest.TestCase):
    """Tests for analysis_daily_job.py."""

    def _mod(self):
        import quantia.job.analysis_daily_job as m
        return m

    def test_is_analysis_done_force(self):
        m = self._mod()
        with patch.object(m._cfg, 'get_bool', return_value=True):
            self.assertFalse(m._is_analysis_done(TEST_DATE_STR))

    @patch(f'{_mdb}.checkTableIsExist', return_value=False)
    def test_is_analysis_done_table_missing(self, _):
        m = self._mod()
        with patch.object(m._cfg, 'get_bool', return_value=False):
            self.assertFalse(m._is_analysis_done(TEST_DATE_STR))

    @patch(f'{_mdb}.executeSqlFetch', return_value=[[5000]])
    @patch(f'{_mdb}.checkTableIsExist', return_value=True)
    def test_is_analysis_done_above(self, mock_exist, mock_fetch):
        m = self._mod()
        old = m.ANALYSIS_DONE_THRESHOLD
        try:
            m.ANALYSIS_DONE_THRESHOLD = 1000
            with patch.object(m._cfg, 'get_bool', return_value=False):
                self.assertTrue(m._is_analysis_done(TEST_DATE_STR))
        finally:
            m.ANALYSIS_DONE_THRESHOLD = old

    @patch(f'{_mdb}.executeSqlFetch', return_value=[[100]])
    @patch(f'{_mdb}.checkTableIsExist', return_value=True)
    def test_is_analysis_done_below(self, mock_exist, mock_fetch):
        m = self._mod()
        old = m.ANALYSIS_DONE_THRESHOLD
        try:
            m.ANALYSIS_DONE_THRESHOLD = 1000
            with patch.object(m._cfg, 'get_bool', return_value=False):
                self.assertFalse(m._is_analysis_done(TEST_DATE_STR))
        finally:
            m.ANALYSIS_DONE_THRESHOLD = old

    @patch(f'{_mdb}.checkTableIsExist', side_effect=Exception('err'))
    def test_is_analysis_done_exception(self, _):
        m = self._mod()
        with patch.object(m._cfg, 'get_bool', return_value=False):
            self.assertFalse(m._is_analysis_done(TEST_DATE_STR))

    @patch(f'{_mdb}.insert_db_from_df')
    @patch(f'{_mdb}.executeSql')
    @patch(f'{_mdb}.engine')
    @patch(f'{_mdb}.checkTableIsExist', return_value=True)
    def test_run_stock_spot_buy_selection_source(self, mock_exist, mock_engine,
                                                   mock_exec, mock_insert):
        """_run_stock_spot_buy uses cn_stock_selection first."""
        m = self._mod()
        sel_df = pd.DataFrame({'code': ['000001']})
        spot_df = pd.DataFrame({
            'code': ['000001'], 'date': [TEST_DATE_STR],
            'pe9': [10], 'pbnewmrq': [5], 'roe_weight': [20],
        })
        with patch('pandas.read_sql', side_effect=[sel_df, spot_df]):
            m._run_stock_spot_buy(TEST_DATE)
        mock_insert.assert_called_once()

    @patch(f'{_mdb}.insert_db_from_df')
    @patch(f'{_mdb}.engine')
    @patch(f'{_mdb}.checkTableIsExist', return_value=True)
    def test_run_stock_spot_buy_no_qualified(self, mock_exist, mock_engine, mock_insert):
        """No stocks meet criteria → no insert."""
        m = self._mod()
        with patch('pandas.read_sql', return_value=pd.DataFrame(columns=['code'])):
            m._run_stock_spot_buy(TEST_DATE)
        mock_insert.assert_not_called()

    @patch(f'{_trd}.get_trade_date_last', return_value=(TEST_DATE, TEST_DATE))
    def test_main_runs_all_steps(self, mock_td):
        m = self._mod()
        with patch.object(m, '_is_analysis_done', return_value=False), \
             patch.object(m, 'record_task_start', return_value=time.time()), \
             patch.object(m, 'record_task_end'), \
             patch.object(m, '_run_stock_spot_buy') as mock_buy, \
             patch.object(m, '_run_job_subprocess', return_value=True) as mock_backtest, \
             patch.object(m.gptj, 'main') as mock_gpt, \
             patch.object(m.saj, 'main') as mock_saj:
            m.main()
            mock_gpt.assert_called_once()
            mock_buy.assert_called_once()
            mock_saj.assert_called_once()
            mock_backtest.assert_called_once_with(
                'backtest_data_daily_job.py', '数据分析 backtest',
                timeout=m._BACKTEST_TIMEOUT)

    @patch(f'{_trd}.get_trade_date_last', return_value=(TEST_DATE, TEST_DATE))
    def test_main_skips_when_done(self, mock_td):
        m = self._mod()
        with patch.object(m, '_is_analysis_done', return_value=True), \
             patch.object(m.gptj, 'main') as mock_gpt, \
             patch.object(m.saj, 'main') as mock_saj:
            m.main()
            mock_gpt.assert_not_called()
            mock_saj.assert_not_called()


# ============================================================================
# 9. streaming_analysis_job
# ============================================================================
class TestStreamingAnalysisJob(unittest.TestCase):
    """Tests for streaming_analysis_job.py."""

    def _mod(self):
        import quantia.job.streaming_analysis_job as m
        return m

    @patch(f'{_mdb}.engine')
    @patch(f'{_mdb}.checkTableIsExist', return_value=True)
    def test_get_stock_list_from_db_exists(self, mock_exist, mock_engine):
        m = self._mod()
        df = pd.DataFrame({'date': [TEST_DATE_STR], 'code': ['000001'], 'name': ['T']})
        with patch('pandas.read_sql', return_value=df):
            result = m._get_stock_list_from_db(TEST_DATE)
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 1)

    @patch(f'{_mdb}.checkTableIsExist', return_value=False)
    def test_get_stock_list_from_db_no_table(self, _):
        self.assertIsNone(self._mod()._get_stock_list_from_db(TEST_DATE))

    def test_prepare_tables_is_noop(self):
        """_prepare_tables is a no-op (deferred deletion)."""
        self._mod()._prepare_tables(TEST_DATE_STR, [])

    @patch(f'{_mdb}.executeSql')
    @patch(f'{_mdb}.checkTableIsExist', return_value=True)
    def test_clean_table_if_needed_first_time(self, mock_exist, mock_exec):
        m = self._mod()
        cleaned = set()
        m._clean_table_if_needed('test_table', TEST_DATE_STR, cleaned)
        mock_exec.assert_called_once()
        self.assertIn('test_table', cleaned)

    def test_clean_table_if_needed_already_cleaned(self):
        m = self._mod()
        cleaned = {'test_table'}
        with patch(f'{_mdb}.executeSql') as mock_exec:
            m._clean_table_if_needed('test_table', TEST_DATE_STR, cleaned)
            mock_exec.assert_not_called()

    @patch(f'{_mdb}.checkTableIsExist', return_value=False)
    def test_ensure_table_schema_table_not_exist(self, _):
        """Table doesn't exist → no-op."""
        m = self._mod()
        with patch(f'{_mdb}.executeSql') as mock_exec:
            m._ensure_table_schema('t', {'c1': 'INT', 'c2': 'FLOAT'})
            mock_exec.assert_not_called()

    @patch(f'{_mdb}.executeSql')
    @patch(f'{_mdb}.checkTableIsExist', return_value=True)
    def test_ensure_table_schema_missing_columns_drops(self, mock_exist, mock_exec):
        """Table missing columns → DROP TABLE."""
        m = self._mod()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [('col1',)]  # only col1
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_cur_ctx = MagicMock()
        mock_cur_ctx.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cur_ctx.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cur_ctx

        with patch(f'{_mdb}.get_connection', return_value=mock_conn):
            m._ensure_table_schema('t', {'col1': 'INT', 'col2': 'FLOAT', 'col3': 'VARCHAR'})
        drop_calls = [c for c in mock_exec.call_args_list if 'DROP' in str(c)]
        self.assertGreater(len(drop_calls), 0)

    @patch(f'{_mdb}.executeSql')
    @patch(f'{_mdb}.checkTableIsExist', return_value=True)
    def test_ensure_table_schema_invalidates_cache_after_drop(self, mock_exist, mock_exec):
        """DROP TABLE 后必须清除 checkTableIsExist 缓存，否则重建时 cols_type=None
        会把 date 列推断为 TEXT，导致 ADD PRIMARY KEY 失败（1170）。回归：backtrace_ma250。"""
        m = self._mod()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [('col1',)]  # 缺 col2/col3 → 触发 DROP
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_cur_ctx = MagicMock()
        mock_cur_ctx.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cur_ctx.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cur_ctx

        with patch(f'{_mdb}.get_connection', return_value=mock_conn), \
             patch(f'{_mdb}.invalidate_table_exists_cache') as mock_inv:
            m._ensure_table_schema('t', {'col1': 'INT', 'col2': 'FLOAT', 'col3': 'VARCHAR'})
        mock_inv.assert_called_once_with('t')

    def test_flush_results_empty(self):
        """Empty data → no DB writes."""
        m = self._mod()
        cleaned = set()
        with patch(f'{_mdb}.insert_db_from_df') as mock_insert:
            m._flush_results({}, {}, {}, {}, TEST_DATE_STR, [], cleaned)
            mock_insert.assert_not_called()

    @patch(f'{_mdb}.checkTableIsExist', return_value=False)
    def test_get_stock_tops_table_missing(self, _):
        self.assertIsNone(self._mod()._get_stock_tops_from_db(TEST_DATE))

    @patch(f'{_mdb}.engine')
    @patch(f'{_mdb}.checkTableIsExist', return_value=True)
    def test_get_stock_tops_with_data(self, mock_exist, mock_engine):
        m = self._mod()
        df = pd.DataFrame({'code': ['000001', '000002']})
        with patch('pandas.read_sql', return_value=df):
            result = m._get_stock_tops_from_db(TEST_DATE)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, set)
        self.assertIn('000001', result)

    @patch(f'{_mdb}.executeSql', side_effect=Exception('lock'))
    @patch(f'{_mdb}.checkTableIsExist', return_value=True)
    def test_clean_table_exception_still_marks(self, mock_exist, mock_exec):
        """Exception during DELETE → table still marked as cleaned."""
        m = self._mod()
        cleaned = set()
        m._clean_table_if_needed('t', TEST_DATE_STR, cleaned)
        self.assertIn('t', cleaned)

    @patch('quantia.lib.run_template.run_with_args')
    def test_main_delegates(self, mock_rwa):
        self._mod().main()
        self.assertEqual(mock_rwa.call_count, 2)

    def _run_streaming_single(self, cache_max_date):
        """以单只股票跑一遍 streaming_analysis，返回 _flush_results 收到的 strategy_results。

        通过 cache_max_date 控制缓存新鲜度：早于目标日 → stale。
        策略列表被替换成单个永远命中的假策略，便于观察是否被 stale 守卫跳过。
        """
        import quantia.job.streaming_analysis_job as m
        import quantia.core.tablestructure as tbs

        target = datetime.datetime(2026, 6, 22)

        def fake_check(stock, hist, date=None):
            return True

        fake_strategy = {'name': 'cn_stock_strategy_fake', 'func': fake_check, 'columns': {}}
        spot = pd.DataFrame({'date': ['2026-06-22'], 'code': ['603056'], 'name': ['T']})
        hist = pd.DataFrame({'date': pd.to_datetime([cache_max_date]), 'close': [10.0]})

        captured = {}

        def capture_flush(ind, kl, strat, extras, ds, strs, cleaned):
            captured['strategy_results'] = {k: list(v) for k, v in strat.items()}

        with patch.object(m.tbs, 'TABLE_CN_STOCK_STRATEGIES', [fake_strategy]), \
             patch.object(m, '_get_stock_list_from_db', return_value=spot), \
             patch.object(m, '_get_stock_tops_from_db', return_value=None), \
             patch.object(m, '_ensure_table_schema'), \
             patch.object(m, '_flush_results', side_effect=capture_flush), \
             patch.object(m.stf, 'read_stock_hist_from_cache', return_value=hist), \
             patch.object(m.idr, 'get_indicator', return_value=None), \
             patch.object(m.kpr, 'get_pattern_recognition', return_value=None), \
             patch('quantia.job.strategy_data_daily_job._load_strategy_kwargs', return_value={}):
            m.streaming_analysis(target)
        return captured.get('strategy_results', {})

    def test_streaming_skips_strategy_for_stale_stock(self):
        """停牌/缓存陈旧（无目标日K线）的股票不应被写入任何策略选股结果。"""
        results = self._run_streaming_single('2026-01-20')
        self.assertEqual(results.get('cn_stock_strategy_fake'), [])

    def test_streaming_keeps_strategy_for_fresh_stock(self):
        """缓存覆盖目标交易日的股票正常参与策略选股（零回归）。"""
        results = self._run_streaming_single('2026-06-22')
        self.assertEqual(len(results.get('cn_stock_strategy_fake', [])), 1)


# ============================================================================
# 9b. database 表存在缓存失效（回归：backtrace_ma250 TEXT date 主键失败）
# ============================================================================
class TestDatabaseTableExistsCache(unittest.TestCase):
    """invalidate_table_exists_cache 必须能清除 checkTableIsExist 的 TTL 缓存。"""

    def _mod(self):
        import quantia.lib.database as mdb
        return mdb

    def test_invalidate_single_table(self):
        mdb = self._mod()
        if mdb._TABLE_EXISTS_TTL <= 0:
            self.skipTest('表存在缓存被禁用')
        mdb._cache_table_exists('t_keep', True)
        mdb._cache_table_exists('t_drop', True)
        self.assertTrue(mdb._get_cached_table_exists('t_drop'))
        mdb.invalidate_table_exists_cache('t_drop')
        # 目标表缓存被清除（返回 None 触发重新查询），其它表不受影响
        self.assertIsNone(mdb._get_cached_table_exists('t_drop'))
        self.assertTrue(mdb._get_cached_table_exists('t_keep'))

    def test_invalidate_all(self):
        mdb = self._mod()
        if mdb._TABLE_EXISTS_TTL <= 0:
            self.skipTest('表存在缓存被禁用')
        mdb._cache_table_exists('t_a', True)
        mdb._cache_table_exists('t_b', False)
        mdb.invalidate_table_exists_cache(None)
        self.assertIsNone(mdb._get_cached_table_exists('t_a'))
        self.assertIsNone(mdb._get_cached_table_exists('t_b'))


# ============================================================================
# 10. indicators_data_daily_job
# ============================================================================
class TestIndicatorsDataDailyJob(unittest.TestCase):
    """Tests for indicators_data_daily_job.py."""

    def _mod(self):
        import quantia.job.indicators_data_daily_job as m
        return m

    @patch(f'{_mdb}.insert_db_from_df')
    @patch(f'{_mdb}.executeSql')
    @patch(f'{_mdb}.checkTableIsExist', return_value=True)
    @patch('quantia.core.indicator.calculate_indicator.get_indicator')
    def test_prepare_happy_path(self, mock_ind, mock_exist, mock_exec, mock_insert):
        m = self._mod()
        stock_key = (TEST_DATE_STR, '000001', 'Test')
        hist_df = pd.DataFrame({'date': [TEST_DATE_STR], 'close': [10.0]})
        mock_ind.return_value = pd.Series({'code': '000001', 'date': TEST_DATE_STR, 'kdjk': 50})
        with patch('quantia.job.indicators_data_daily_job.stock_hist_data') as mock_hd:
            mock_hd.return_value.get_data.return_value = {stock_key: hist_df}
            m.prepare(TEST_DATE)
        mock_insert.assert_called_once()

    def test_prepare_no_data(self):
        m = self._mod()
        with patch('quantia.job.indicators_data_daily_job.stock_hist_data') as mock_hd, \
             patch(f'{_mdb}.insert_db_from_df') as mock_insert:
            mock_hd.return_value.get_data.return_value = None
            m.prepare(TEST_DATE)
            mock_insert.assert_not_called()

    def test_run_check_empty_returns_none(self):
        result = self._mod().run_check({}, date=TEST_DATE, workers=1)
        self.assertIsNone(result)

    @patch(f'{_mdb}.insert_db_from_df')
    @patch(f'{_mdb}.executeSql')
    @patch(f'{_mdb}.checkTableIsExist', return_value=True)
    @patch(f'{_mdb}.engine')
    def test_guess_buy_inserts(self, mock_engine, mock_exist, mock_exec, mock_insert):
        m = self._mod()
        df = pd.DataFrame({'date': [TEST_DATE_STR], 'code': ['000001'], 'name': ['T']})
        with patch('pandas.read_sql', return_value=df), \
             patch('quantia.core.indicator.buy_sell_signal._peak_drawdown_ok', return_value=True):
            m.guess_buy(TEST_DATE)
        mock_insert.assert_called_once()

    @patch(f'{_mdb}.checkTableIsExist', return_value=True)
    @patch(f'{_mdb}.engine')
    def test_guess_buy_empty_no_insert(self, mock_engine, mock_exist):
        m = self._mod()
        with patch('pandas.read_sql', return_value=pd.DataFrame()), \
             patch(f'{_mdb}.insert_db_from_df') as mock_insert:
            m.guess_buy(TEST_DATE)
            mock_insert.assert_not_called()

    @patch(f'{_mdb}.insert_db_from_df')
    @patch(f'{_mdb}.executeSql')
    @patch(f'{_mdb}.checkTableIsExist', return_value=True)
    @patch(f'{_mdb}.engine')
    def test_guess_sell_inserts(self, mock_engine, mock_exist, mock_exec, mock_insert):
        m = self._mod()
        df = pd.DataFrame({'date': [TEST_DATE_STR], 'code': ['000001'], 'name': ['T']})
        with patch('pandas.read_sql', return_value=df), \
             patch('quantia.core.indicator.buy_sell_signal._peak_drawdown_ok', return_value=True):
            m.guess_sell(TEST_DATE)
        mock_insert.assert_called_once()

    @patch('quantia.lib.run_template.run_with_args')
    def test_main_calls_three(self, mock_rwa):
        self._mod().main()
        self.assertEqual(mock_rwa.call_count, 3)


# ============================================================================
# 11. strategy_data_daily_job
# ============================================================================
class TestStrategyDataDailyJob(unittest.TestCase):
    """Tests for strategy_data_daily_job.py."""

    def _mod(self):
        import quantia.job.strategy_data_daily_job as m
        return m

    @patch(f'{_mdb}.insert_db_from_df')
    @patch(f'{_mdb}.executeSql')
    @patch(f'{_mdb}.checkTableIsExist', return_value=True)
    def test_prepare_inserts(self, mock_exist, mock_exec, mock_insert):
        m = self._mod()
        stock_key = (TEST_DATE_STR, '000001', 'Test')
        hist_df = pd.DataFrame({'date': [TEST_DATE_STR], 'close': [10.0]})
        strategy = {
            'name': 'cn_stock_strategy_test',
            'func': MagicMock(return_value=True, __name__='check_test'),
            'columns': {'date': 'DATE', 'code': 'VARCHAR(6)', 'name': 'VARCHAR(20)'},
        }
        with patch('quantia.job.strategy_data_daily_job.stock_hist_data') as mock_hd:
            mock_hd.return_value.get_data.return_value = {stock_key: hist_df}
            m.prepare(TEST_DATE, strategy)
        mock_insert.assert_called_once()

    def test_prepare_no_data(self):
        m = self._mod()
        strategy = {'name': 'test', 'func': MagicMock(__name__='f')}
        with patch('quantia.job.strategy_data_daily_job.stock_hist_data') as mock_hd, \
             patch(f'{_mdb}.insert_db_from_df') as mock_insert:
            mock_hd.return_value.get_data.return_value = None
            m.prepare(TEST_DATE, strategy)
            mock_insert.assert_not_called()

    def test_run_check_no_match(self):
        m = self._mod()
        fn = MagicMock(return_value=False, __name__='check_test')
        stock_key = (TEST_DATE_STR, '000001', 'Test')
        stocks = {stock_key: pd.DataFrame({'close': [10.0]})}
        result, extras = m.run_check(fn, 'tbl', stocks, TEST_DATE, workers=1)
        self.assertIsNone(result)
        self.assertEqual(extras, {})

    def test_run_check_match_returns_list(self):
        m = self._mod()
        fn = MagicMock(return_value=True, __name__='check_test')
        stock_key = (TEST_DATE_STR, '000001', 'Test')
        stocks = {stock_key: pd.DataFrame({'close': [10.0]})}
        result, extras = m.run_check(fn, 'tbl', stocks, TEST_DATE, workers=1)
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 1)
        self.assertEqual(extras, {})

    def test_run_check_dict_result_captures_extras(self):
        m = self._mod()
        metrics = {'p_change': 3.5, 'vol_ratio': 2.5}
        fn = MagicMock(return_value=metrics, __name__='check_test')
        stock_key = (TEST_DATE_STR, '000001', 'Test')
        stocks = {stock_key: pd.DataFrame({'close': [10.0]})}
        result, extras = m.run_check(fn, 'tbl', stocks, TEST_DATE, workers=1)
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 1)
        self.assertIn(stock_key, extras)
        self.assertEqual(extras[stock_key]['p_change'], 3.5)

    def test_load_strategy_kwargs_not_whitelisted(self):
        """非白名单策略：直接返回空 dict，不查库。"""
        m = self._mod()
        self.assertEqual(
            m._load_strategy_kwargs('cn_stock_strategy_unknown', lambda *a, **k: None), {})

    @patch(f'{_mdb}.checkTableIsExist', return_value=False)
    def test_load_strategy_kwargs_no_params_table(self, _):
        """参数表不存在：返回空 dict，check() 用默认参数（零回归）。"""
        m = self._mod()
        from quantia.core.strategy import breakthrough_platform as bp
        self.assertEqual(
            m._load_strategy_kwargs('cn_stock_strategy_breakthrough_platform', bp.check), {})

    @patch(f'{_mdb}.executeSqlFetch')
    @patch(f'{_mdb}.checkTableIsExist', return_value=True)
    def test_load_strategy_kwargs_filters_by_signature(self, mock_exist, mock_fetch):
        """仅保留 check() 签名内的参数：标量与 JSON 字符串均解析，签名外的键被丢弃。"""
        m = self._mod()
        from quantia.core.strategy import breakthrough_platform as bp
        mock_fetch.return_value = [
            ('min_platform_days', 15),   # 标量，签名内
            ('recent_days', '5'),         # JSON 字符串，签名内
            ('foobar', 99),               # 签名外，应被丢弃
        ]
        kw = m._load_strategy_kwargs('cn_stock_strategy_breakthrough_platform', bp.check)
        self.assertEqual(kw, {'min_platform_days': 15, 'recent_days': 5})


# ============================================================================
# 12. klinepattern_data_daily_job
# ============================================================================
class TestKlinepatternDataDailyJob(unittest.TestCase):
    """Tests for klinepattern_data_daily_job.py."""

    def _mod(self):
        import quantia.job.klinepattern_data_daily_job as m
        return m

    @patch(f'{_mdb}.insert_db_from_df')
    @patch(f'{_mdb}.executeSql')
    @patch(f'{_mdb}.checkTableIsExist', return_value=True)
    @patch('quantia.core.pattern.pattern_recognitions.get_pattern_recognition')
    def test_prepare_inserts(self, mock_pat, mock_exist, mock_exec, mock_insert):
        m = self._mod()
        stock_key = (TEST_DATE_STR, '000001', 'Test')
        hist_df = pd.DataFrame({'date': [TEST_DATE_STR], 'close': [10.0]})
        mock_pat.return_value = pd.Series({'code': '000001', 'CDL2CROWS': 0})
        with patch('quantia.job.klinepattern_data_daily_job.stock_hist_data') as mock_hd:
            mock_hd.return_value.get_data.return_value = {stock_key: hist_df}
            m.prepare(TEST_DATE)
        mock_insert.assert_called_once()

    def test_prepare_no_data(self):
        m = self._mod()
        with patch('quantia.job.klinepattern_data_daily_job.stock_hist_data') as mock_hd, \
             patch(f'{_mdb}.insert_db_from_df') as mock_insert:
            mock_hd.return_value.get_data.return_value = None
            m.prepare(TEST_DATE)
            mock_insert.assert_not_called()

    def test_run_check_empty(self):
        self.assertIsNone(self._mod().run_check({}, date=TEST_DATE, workers=1))

    @patch('quantia.lib.run_template.run_with_args')
    def test_main(self, mock_rwa):
        self._mod().main()
        mock_rwa.assert_called_once()


# ============================================================================
# 13. backtest_data_daily_job
# ============================================================================
class TestBacktestDataDailyJob(unittest.TestCase):
    """Tests for backtest_data_daily_job.py."""

    def _mod(self):
        import quantia.job.backtest_data_daily_job as m
        return m

    @patch(f'{_stf}.read_stock_hist_from_cache', return_value=None)
    def test_run_check_no_cache(self, _):
        m = self._mod()
        stocks = [(TEST_DATE_STR, '000001', 'T')]
        result = m.run_check(stocks, '20230101', '20260318', ['date', 'code', 'rate_1'], workers=1)
        self.assertIsNone(result)

    @patch('quantia.core.backtest.rate_stats.get_rates')
    @patch(f'{_stf}.read_stock_hist_from_cache')
    def test_run_check_with_data(self, mock_cache, mock_rates):
        m = self._mod()
        mock_cache.return_value = pd.DataFrame({'date': [TEST_DATE_STR], 'close': [10.0]})
        mock_rates.return_value = pd.Series({'date': TEST_DATE_STR, 'code': '000001', 'rate_1': 1.5})
        result = m.run_check([(TEST_DATE_STR, '000001', 'T')],
                             '20230101', '20260318', ['date', 'code', 'rate_1'], workers=1)
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 1)

    @patch(f'{_mdb}.executeSqlFetch')
    @patch(f'{_mdb}.executeSql')
    def test_migrate_summary_columns_adds_missing(self, mock_exec, mock_fetch):
        m = self._mod()
        mock_fetch.return_value = [('date',), ('strategy_name',), ('avg_rate_1',)]
        m._migrate_summary_columns('cn_stock_backtest', [1, 3, 5])
        alter_calls = [c for c in mock_exec.call_args_list if 'ALTER' in str(c)]
        self.assertEqual(len(alter_calls), 2)  # avg_rate_3 + avg_rate_5

    @patch(f'{_mdb}.executeSqlFetch', return_value=[])
    @patch(f'{_mdb}.executeSql')
    def test_migrate_summary_columns_empty_show(self, mock_exec, mock_fetch):
        m = self._mod()
        m._migrate_summary_columns('cn_stock_backtest', [1, 3])
        alter_calls = [c for c in mock_exec.call_args_list if 'ALTER' in str(c)]
        self.assertEqual(len(alter_calls), 2)

    def test_main_calls_prepare_and_summarize(self):
        m = self._mod()
        with patch.object(m, 'prepare') as mock_prep, \
             patch.object(m, 'summarize_backtest') as mock_sum:
            m.main()
            mock_prep.assert_called_once()
            mock_sum.assert_called_once()

    @patch(f'{_mdb}.checkTableIsExist', return_value=False)
    def test_process_table_not_exist(self, _):
        m = self._mod()
        with patch(f'{_mdb}.update_db_from_df') as mock_update:
            m.process({'name': 'nonexist', 'columns': {'date': 'x', 'last': 'y'}},
                      '20230101', '20260318', ['date', 'code', 'rate_1'])
            mock_update.assert_not_called()

    @patch(f'{_mdb}.engine')
    @patch(f'{_mdb}.checkTableIsExist', return_value=True)
    def test_process_no_null_rows(self, mock_exist, mock_engine):
        m = self._mod()
        with patch('pandas.read_sql', return_value=pd.DataFrame()), \
             patch(f'{_mdb}.update_db_from_df') as mock_update:
            table = {'name': 'test_tbl', 'columns': {'date': 'x', 'code': 'y', 'last': 'z'}}
            m.process(table, '20230101', '20260318', ['date', 'code', 'rate_1'])
            mock_update.assert_not_called()

    @patch(f'{_mdb}.insert_db_from_df')
    @patch(f'{_mdb}.executeSql')
    @patch(f'{_mdb}.engine')
    @patch(f'{_mdb}.checkTableIsExist', return_value=True)
    @patch(f'{_mdb}.executeSqlFetch')
    def test_summarize_backtest_aggregates(self, mock_fetch, mock_exist, mock_engine,
                                            mock_exec, mock_insert):
        """summarize_backtest reads strategy tables and inserts summary."""
        m = self._mod()
        import quantia.core.tablestructure as tbs

        # Mock SHOW COLUMNS for migration
        all_cols = [('date',), ('strategy_name',), ('stock_count',),
                    ('success_count',), ('success_rate',), ('backtested_count',)]
        all_cols += [(f'avg_rate_{h}',) for h in [1, 3, 5, 10, 20, 30, 60, 90, 120]]
        mock_fetch.return_value = all_cols

        # Prepare summary data with all required columns
        summary_df = pd.DataFrame({
            'date': [TEST_DATE_STR], 'stock_count': [100],
            'backtested_count': [80], 'success_count': [50],
        })
        for h in [1, 3, 5, 10, 20, 30, 60, 90, 120]:
            summary_df[f'avg_rate_{h}'] = 1.5

        with patch('pandas.read_sql', return_value=summary_df):
            m.summarize_backtest()
        mock_insert.assert_called_once()


# ============================================================================
# 14. selection_data_daily_job
# ============================================================================
class TestSelectionDataDailyJob(unittest.TestCase):
    """Tests for selection_data_daily_job.py."""

    def _mod(self):
        import quantia.job.selection_data_daily_job as m
        return m

    @patch(f'{_mdb}.insert_db_from_df')
    @patch(f'{_mdb}.executeSql')
    @patch(f'{_mdb}.checkTableIsExist', return_value=True)
    @patch(f'{_stf}.fetch_stock_selection')
    def test_save_selection(self, mock_fetch, mock_exist, mock_exec, mock_insert):
        m = self._mod()
        mock_fetch.return_value = pd.DataFrame({'code': ['000001'], 'date': [TEST_DATE_STR], 'name': ['T']})
        m.save_nph_stock_selection_data(TEST_DATE, before=False)
        mock_insert.assert_called_once()

    @patch(f'{_stf}.fetch_stock_selection')
    def test_save_selection_before_returns(self, mock_fetch):
        self._mod().save_nph_stock_selection_data(TEST_DATE, before=True)
        mock_fetch.assert_not_called()

    @patch('time.sleep')
    @patch(f'{_mdb}.insert_db_from_df')
    @patch(f'{_mdb}.executeSql')
    @patch(f'{_mdb}.checkTableIsExist', return_value=True)
    @patch(f'{_stf}.fetch_stock_selection')
    def test_save_selection_retry_on_first_fail(self, mock_fetch, mock_exist,
                                                  mock_exec, mock_insert, mock_sleep):
        m = self._mod()
        df = pd.DataFrame({'code': ['000001'], 'date': [TEST_DATE_STR], 'name': ['T']})
        mock_fetch.side_effect = [None, df]
        m.save_nph_stock_selection_data(TEST_DATE, before=False)
        self.assertEqual(mock_fetch.call_count, 2)
        mock_sleep.assert_called_once_with(10)
        mock_insert.assert_called_once()

    @patch('quantia.lib.run_template.run_with_args')
    def test_main(self, mock_rwa):
        self._mod().main()
        mock_rwa.assert_called_once()


# ============================================================================
# 15. gpt_value_data_job
# ============================================================================
class TestGptValueDataJob(unittest.TestCase):
    """Tests for gpt_value_data_job.py."""

    def _mod(self):
        import quantia.job.gpt_value_data_job as m
        return m

    @patch(f'{_mdb}.engine')
    def test_load_selection_data_exact_date(self, mock_engine):
        m = self._mod()
        df = pd.DataFrame({'code': ['000001'], 'date': [TEST_DATE_STR]})
        with patch('pandas.read_sql', return_value=df):
            result, actual = m._load_selection_data('cn_stock_selection', TEST_DATE_STR)
        self.assertIsNotNone(result)
        self.assertEqual(actual, TEST_DATE_STR)

    @patch(f'{_mdb}.engine')
    def test_load_selection_data_fallback(self, mock_engine):
        m = self._mod()
        empty_df = pd.DataFrame()
        fallback_df = pd.DataFrame({'latest': ['2026-03-17']})
        data_df = pd.DataFrame({'code': ['000001'], 'date': ['2026-03-17']})
        with patch('pandas.read_sql', side_effect=[empty_df, fallback_df, data_df]):
            result, actual = m._load_selection_data('cn_stock_selection', TEST_DATE_STR)
        self.assertIsNotNone(result)
        self.assertEqual(actual, '2026-03-17')

    @patch(f'{_mdb}.engine')
    def test_load_selection_data_all_empty(self, mock_engine):
        m = self._mod()
        empty = pd.DataFrame()
        fallback = pd.DataFrame({'latest': [None]})
        diag = pd.DataFrame({'latest': [None], 'days': [0]})
        with patch('pandas.read_sql', side_effect=[empty, fallback, diag]):
            result, actual = m._load_selection_data('cn_stock_selection', TEST_DATE_STR)
        self.assertIsNone(result)
        self.assertEqual(actual, TEST_DATE_STR)

    @patch(f'{_mdb}.executeSql')
    @patch(f'{_mdb}.checkTableIsExist', return_value=True)
    def test_check_and_rebuild_table_missing_cols(self, mock_exist, mock_exec):
        m = self._mod()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [('date',), ('code',)]
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_cur_ctx = MagicMock()
        mock_cur_ctx.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cur_ctx.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cur_ctx
        with patch('pymysql.connect', return_value=mock_conn):
            m._check_and_rebuild_table('cn_stock_strategy_gpt_value')
        drop_calls = [c for c in mock_exec.call_args_list if 'DROP' in str(c)]
        self.assertGreater(len(drop_calls), 0)

    @patch(f'{_mdb}.checkTableIsExist', return_value=False)
    def test_prepare_source_table_missing(self, _):
        m = self._mod()
        with patch(f'{_mdb}.insert_db_from_df') as mock_insert:
            m.prepare(TEST_DATE)
            mock_insert.assert_not_called()

    @patch('quantia.lib.run_template.run_with_args')
    def test_main(self, mock_rwa):
        self._mod().main()
        mock_rwa.assert_called_once()


# ============================================================================
# 16. init_job
# ============================================================================
class TestInitJob(unittest.TestCase):
    """Tests for init_job.py."""

    def _mod(self):
        import quantia.job.init_job as m
        return m

    def _mock_conn(self):
        """Create a mock pymysql connection."""
        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        return mock_conn, mock_cursor

    @patch('pymysql.connect')
    def test_create_new_database_sql(self, mock_connect):
        m = self._mod()
        conn, cursor = self._mock_conn()
        mock_connect.return_value = conn
        with patch.object(m, 'create_new_base_table'):
            m.create_new_database()
        create_calls = [c for c in cursor.execute.call_args_list if 'CREATE DATABASE' in str(c)]
        self.assertGreater(len(create_calls), 0)

    @patch('pymysql.connect')
    def test_create_new_base_table_two_tables(self, mock_connect):
        m = self._mod()
        conn, cursor = self._mock_conn()
        mock_connect.return_value = conn
        m.create_new_base_table()
        create_calls = [c for c in cursor.execute.call_args_list if 'CREATE TABLE' in str(c)]
        self.assertEqual(len(create_calls), 3)

    @patch('pymysql.connect')
    def test_main_existing_db(self, mock_connect):
        m = self._mod()
        conn, cursor = self._mock_conn()
        mock_connect.return_value = conn
        m.main()
        self.assertGreater(cursor.execute.call_count, 0)

    @patch('time.sleep')
    @patch('pymysql.connect')
    def test_connect_with_retry_succeeds_after_retries(self, mock_connect, mock_sleep):
        import pymysql
        m = self._mod()
        mock_connect.side_effect = [
            pymysql.err.OperationalError(2003, 'cant connect'),
            MagicMock(),
        ]
        conn = m._connect_with_retry({'host': 'localhost'}, label='test')
        self.assertIsNotNone(conn)
        self.assertEqual(mock_connect.call_count, 2)

    @patch('pymysql.connect')
    def test_main_db_not_exist_creates(self, mock_connect):
        """main() creates DB if OperationalError 1049."""
        import pymysql
        m = self._mod()
        conn, cursor = self._mock_conn()
        mock_connect.side_effect = [
            pymysql.err.OperationalError(1049, 'Unknown database'),
            conn,   # create DB
            conn,   # base tables
        ]
        m.main()
        create_calls = [c for c in cursor.execute.call_args_list if 'CREATE DATABASE' in str(c)]
        self.assertGreater(len(create_calls), 0)


# ============================================================================
# 17. safe_backfill
# ============================================================================
class TestSafeBackfill(unittest.TestCase):
    """Tests for safe_backfill.py — validate it's valid Python syntax."""

    def test_syntax_valid(self):
        """safe_backfill.py compiles without syntax errors."""
        import py_compile
        src = os.path.join(_JOB_DIR, 'safe_backfill.py')
        try:
            py_compile.compile(src, doraise=True)
            compiled = True
        except py_compile.PyCompileError:
            compiled = False
        self.assertTrue(compiled)


# ============================================================================
# 18. fetch_three_pages
# ============================================================================
class TestFetchThreePages(unittest.TestCase):
    """Tests for fetch_three_pages.py."""

    def _mod(self):
        import quantia.job.fetch_three_pages as m
        return m

    @patch(f'{_mdb}.executeSqlFetch', return_value=[[1]])
    def test_verify_db_connection_ok(self, _):
        self.assertTrue(self._mod().verify_db_connection())

    @patch(f'{_mdb}.executeSqlFetch', side_effect=Exception('conn err'))
    def test_verify_db_connection_fail(self, _):
        self.assertFalse(self._mod().verify_db_connection())

    @patch(f'{_mdb}.executeSqlFetch', return_value=[[42]])
    def test_verify_table_data(self, _):
        self.assertEqual(self._mod().verify_table_data('cn_stock_spot', TEST_DATE_STR), 42)

    @patch(f'{_mdb}.executeSqlFetch', side_effect=Exception('err'))
    def test_verify_table_data_error(self, _):
        self.assertEqual(self._mod().verify_table_data('cn_stock_spot', TEST_DATE_STR), -1)

    @patch('quantia.job.fetch_three_pages.verify_table_data', return_value=100)
    def test_fetch_for_date_calls_steps(self, mock_verify):
        m = self._mod()
        with patch('quantia.job.basic_data_daily_job.save_nph_stock_spot_data'), \
             patch('quantia.job.selection_data_daily_job.save_nph_stock_selection_data'), \
             patch('quantia.job.analysis_daily_job._run_stock_spot_buy'), \
             patch('quantia.job.gpt_value_data_job.prepare'):
            results = m.fetch_for_date(TEST_DATE)
        self.assertIsInstance(results, dict)
        self.assertIn('cn_stock_spot', results)
        self.assertIn('cn_stock_selection', results)
        self.assertIn('cn_stock_spot_buy', results)
        self.assertIn('cn_stock_strategy_gpt_value', results)

    @patch('quantia.job.fetch_three_pages.verify_table_data', return_value=100)
    def test_fetch_for_date_handles_failure(self, mock_verify):
        m = self._mod()
        with patch('quantia.job.basic_data_daily_job.save_nph_stock_spot_data',
                   side_effect=Exception('boom')), \
             patch('quantia.job.selection_data_daily_job.save_nph_stock_selection_data'), \
             patch('quantia.job.analysis_daily_job._run_stock_spot_buy'), \
             patch('quantia.job.gpt_value_data_job.prepare'):
            results = m.fetch_for_date(TEST_DATE)
        self.assertEqual(results['cn_stock_spot'], -1)
        self.assertEqual(results['cn_stock_selection'], 100)


# ============================================================================
if __name__ == '__main__':
    unittest.main()
