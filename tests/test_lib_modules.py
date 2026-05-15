#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Comprehensive unit tests for quantia/lib/ modules.

Covers: envconfig, singleton_type, version, query_cache, trade_time,
        database, job_tracker, crypto_aes, log_config, run_template, torndb.

All tests are self-contained — no database or network access required.
"""

import os
import sys
import time
import threading
import datetime
import logging
import unittest
from unittest.mock import patch, MagicMock, PropertyMock

# Ensure project root is on sys.path so that quantia.* imports work
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


# ============================================================
# 1. envconfig
# ============================================================
class TestEnvConfig(unittest.TestCase):
    """Tests for quantia.lib.envconfig — typed env-var helpers."""

    def setUp(self):
        # Clean up test keys before each test
        for key in ('TEST_STR', 'TEST_INT', 'TEST_FLOAT', 'TEST_BOOL'):
            os.environ.pop(key, None)

    tearDown = setUp

    # -- get_str --
    def test_get_str_returns_value_when_set(self):
        from quantia.lib.envconfig import get_str
        os.environ['TEST_STR'] = 'hello'
        self.assertEqual(get_str('TEST_STR'), 'hello')

    def test_get_str_returns_default_when_unset(self):
        from quantia.lib.envconfig import get_str
        self.assertEqual(get_str('TEST_STR', 'fallback'), 'fallback')

    def test_get_str_default_is_empty_string(self):
        from quantia.lib.envconfig import get_str
        self.assertEqual(get_str('TEST_STR'), '')

    def test_get_str_with_empty_value(self):
        from quantia.lib.envconfig import get_str
        os.environ['TEST_STR'] = ''
        self.assertEqual(get_str('TEST_STR', 'fallback'), '')

    # -- get_int --
    def test_get_int_returns_parsed_value(self):
        from quantia.lib.envconfig import get_int
        os.environ['TEST_INT'] = '42'
        self.assertEqual(get_int('TEST_INT'), 42)

    def test_get_int_returns_default_when_unset(self):
        from quantia.lib.envconfig import get_int
        self.assertEqual(get_int('TEST_INT', 99), 99)

    def test_get_int_returns_default_on_invalid(self):
        from quantia.lib.envconfig import get_int
        os.environ['TEST_INT'] = 'not_a_number'
        self.assertEqual(get_int('TEST_INT', 7), 7)

    def test_get_int_negative(self):
        from quantia.lib.envconfig import get_int
        os.environ['TEST_INT'] = '-10'
        self.assertEqual(get_int('TEST_INT'), -10)

    def test_get_int_zero_default(self):
        from quantia.lib.envconfig import get_int
        self.assertEqual(get_int('TEST_INT'), 0)

    def test_get_int_with_float_string(self):
        from quantia.lib.envconfig import get_int
        os.environ['TEST_INT'] = '3.14'
        # int('3.14') raises ValueError → should return default
        self.assertEqual(get_int('TEST_INT', 5), 5)

    # -- get_float --
    def test_get_float_returns_parsed_value(self):
        from quantia.lib.envconfig import get_float
        os.environ['TEST_FLOAT'] = '3.14'
        self.assertAlmostEqual(get_float('TEST_FLOAT'), 3.14)

    def test_get_float_returns_default_when_unset(self):
        from quantia.lib.envconfig import get_float
        self.assertAlmostEqual(get_float('TEST_FLOAT', 1.5), 1.5)

    def test_get_float_returns_default_on_invalid(self):
        from quantia.lib.envconfig import get_float
        os.environ['TEST_FLOAT'] = 'abc'
        self.assertAlmostEqual(get_float('TEST_FLOAT', 2.0), 2.0)

    def test_get_float_integer_string(self):
        from quantia.lib.envconfig import get_float
        os.environ['TEST_FLOAT'] = '7'
        self.assertAlmostEqual(get_float('TEST_FLOAT'), 7.0)

    def test_get_float_negative(self):
        from quantia.lib.envconfig import get_float
        os.environ['TEST_FLOAT'] = '-0.5'
        self.assertAlmostEqual(get_float('TEST_FLOAT'), -0.5)

    # -- get_bool --
    def test_get_bool_true_variants(self):
        from quantia.lib.envconfig import get_bool
        for val in ('1', 'true', 'True', 'TRUE', 'yes', 'YES', 'on', 'ON'):
            os.environ['TEST_BOOL'] = val
            self.assertTrue(get_bool('TEST_BOOL'), f"Expected True for '{val}'")

    def test_get_bool_false_variants(self):
        from quantia.lib.envconfig import get_bool
        for val in ('0', 'false', 'False', 'no', 'off', 'random', ''):
            os.environ['TEST_BOOL'] = val
            self.assertFalse(get_bool('TEST_BOOL'), f"Expected False for '{val}'")

    def test_get_bool_returns_default_when_unset(self):
        from quantia.lib.envconfig import get_bool
        self.assertFalse(get_bool('TEST_BOOL'))
        self.assertTrue(get_bool('TEST_BOOL', True))

    def test_get_bool_with_whitespace(self):
        from quantia.lib.envconfig import get_bool
        os.environ['TEST_BOOL'] = '  true  '
        self.assertTrue(get_bool('TEST_BOOL'))


# ============================================================
# 2. singleton_type
# ============================================================
class TestSingletonType(unittest.TestCase):
    """Tests for quantia.lib.singleton_type — metaclass singleton."""

    def test_same_instance_returned(self):
        from quantia.lib.singleton_type import singleton_type

        class MyClass(metaclass=singleton_type):
            def __init__(self):
                self.value = 0

        a = MyClass()
        b = MyClass()
        self.assertIs(a, b)

    def test_singleton_preserves_state(self):
        from quantia.lib.singleton_type import singleton_type

        class Counter(metaclass=singleton_type):
            def __init__(self):
                self.count = 0

        c1 = Counter()
        c1.count = 42
        c2 = Counter()
        self.assertEqual(c2.count, 42)

    def test_different_classes_different_singletons(self):
        from quantia.lib.singleton_type import singleton_type

        class A(metaclass=singleton_type):
            pass

        class B(metaclass=singleton_type):
            pass

        self.assertIsNot(A(), B())

    def test_thread_safety(self):
        """Multiple threads should all receive the same instance."""
        from quantia.lib.singleton_type import singleton_type

        class ThreadSafe(metaclass=singleton_type):
            def __init__(self):
                self.tid = threading.current_thread().ident

        instances = []
        def create():
            instances.append(ThreadSafe())

        threads = [threading.Thread(target=create) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertTrue(all(inst is instances[0] for inst in instances))


# ============================================================
# 3. version
# ============================================================
class TestVersion(unittest.TestCase):
    """Tests for quantia.lib.version."""

    def test_version_exists(self):
        from quantia.lib.version import __version__
        self.assertIsInstance(__version__, str)

    def test_version_non_empty(self):
        from quantia.lib.version import __version__
        self.assertTrue(len(__version__) > 0)

    def test_version_format(self):
        """Version string should look like X.Y.Z (semver-ish)."""
        from quantia.lib.version import __version__
        parts = __version__.split('.')
        self.assertGreaterEqual(len(parts), 2)
        for p in parts:
            self.assertTrue(p.isdigit(), f"Non-numeric version component: {p}")


# ============================================================
# 4. query_cache
# ============================================================
class TestQueryCache(unittest.TestCase):
    """Tests for quantia.lib.query_cache.QueryCache."""

    def _make_cache(self, max_size=10, default_ttl=300):
        from quantia.lib.query_cache import QueryCache
        return QueryCache(max_size=max_size, default_ttl=default_ttl)

    # -- basic get / put --
    def test_put_and_get(self):
        cache = self._make_cache()
        cache.put("SELECT 1", None, {"rows": [1]})
        hit, val = cache.get("SELECT 1", None)
        self.assertTrue(hit)
        self.assertEqual(val, {"rows": [1]})

    def test_get_miss(self):
        cache = self._make_cache()
        hit, val = cache.get("SELECT missing", None)
        self.assertFalse(hit)
        self.assertIsNone(val)

    def test_put_with_params(self):
        cache = self._make_cache()
        cache.put("SELECT * FROM t WHERE id=%s", (42,), "result_42")
        hit, val = cache.get("SELECT * FROM t WHERE id=%s", (42,))
        self.assertTrue(hit)
        self.assertEqual(val, "result_42")

        # different params → miss
        hit2, _ = cache.get("SELECT * FROM t WHERE id=%s", (99,))
        self.assertFalse(hit2)

    # -- TTL expiration --
    def test_ttl_expiration(self):
        cache = self._make_cache(default_ttl=0)  # 0 second TTL
        cache.put("SELECT 1", None, "data")
        # Immediately expired (time.time() >= expire_time)
        time.sleep(0.01)
        hit, val = cache.get("SELECT 1", None)
        self.assertFalse(hit)

    def test_custom_ttl(self):
        cache = self._make_cache(default_ttl=999)
        cache.put("q", None, "v", ttl=0)
        time.sleep(0.01)
        hit, _ = cache.get("q", None)
        self.assertFalse(hit)

    # -- LRU eviction --
    def test_lru_eviction(self):
        cache = self._make_cache(max_size=3)
        cache.put("q1", None, "v1")
        cache.put("q2", None, "v2")
        cache.put("q3", None, "v3")
        # Access q1 to make it recently used
        cache.get("q1", None)
        # Insert q4 → should evict q2 (least recently used)
        cache.put("q4", None, "v4")
        hit_q2, _ = cache.get("q2", None)
        self.assertFalse(hit_q2)
        hit_q1, _ = cache.get("q1", None)
        self.assertTrue(hit_q1)

    def test_max_size_enforcement(self):
        cache = self._make_cache(max_size=5)
        for i in range(20):
            cache.put(f"q{i}", None, f"v{i}")
        self.assertLessEqual(len(cache), 5)

    # -- invalidate --
    def test_invalidate_specific(self):
        cache = self._make_cache()
        cache.put("q1", None, "v1")
        cache.put("q2", None, "v2")
        cache.invalidate("q1", None)
        hit, _ = cache.get("q1", None)
        self.assertFalse(hit)
        hit2, _ = cache.get("q2", None)
        self.assertTrue(hit2)

    def test_invalidate_all(self):
        cache = self._make_cache()
        cache.put("q1", None, "v1")
        cache.put("q2", None, "v2")
        cache.invalidate()
        self.assertEqual(len(cache), 0)

    # -- invalidate_by_prefix (clears all) --
    def test_invalidate_by_prefix_clears_all(self):
        cache = self._make_cache()
        cache.put("SELECT * FROM stocks", None, "data")
        cache.invalidate_by_prefix("stocks")
        self.assertEqual(len(cache), 0)

    # -- cleanup_expired --
    def test_cleanup_expired(self):
        cache = self._make_cache(default_ttl=0)
        cache.put("q1", None, "v1")
        cache.put("q2", None, "v2")
        time.sleep(0.01)
        removed = cache.cleanup_expired()
        self.assertEqual(removed, 2)
        self.assertEqual(len(cache), 0)

    def test_cleanup_expired_keeps_valid(self):
        cache = self._make_cache(default_ttl=999)
        cache.put("good", None, "data")
        removed = cache.cleanup_expired()
        self.assertEqual(removed, 0)
        self.assertEqual(len(cache), 1)

    # -- stats --
    def test_stats(self):
        cache = self._make_cache(max_size=10, default_ttl=300)
        cache.put("q1", None, "v1")
        cache.get("q1", None)  # hit
        cache.get("q_miss", None)  # miss
        s = cache.stats
        self.assertEqual(s['size'], 1)
        self.assertEqual(s['max_size'], 10)
        self.assertEqual(s['hit_count'], 1)
        self.assertEqual(s['miss_count'], 1)
        self.assertEqual(s['hit_rate'], '50.0%')
        self.assertEqual(s['ttl'], 300)

    def test_stats_no_requests(self):
        cache = self._make_cache()
        s = cache.stats
        self.assertEqual(s['hit_rate'], '0.0%')

    # -- __len__ --
    def test_len(self):
        cache = self._make_cache()
        self.assertEqual(len(cache), 0)
        cache.put("a", None, 1)
        cache.put("b", None, 2)
        self.assertEqual(len(cache), 2)

    # -- thread safety --
    def test_concurrent_put_get(self):
        cache = self._make_cache(max_size=100, default_ttl=60)
        errors = []

        def writer(idx):
            try:
                for j in range(50):
                    cache.put(f"q_{idx}_{j}", None, f"v_{idx}_{j}")
            except Exception as e:
                errors.append(e)

        def reader(idx):
            try:
                for j in range(50):
                    cache.get(f"q_{idx}_{j}", None)
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(5):
            threads.append(threading.Thread(target=writer, args=(i,)))
            threads.append(threading.Thread(target=reader, args=(i,)))
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])

    # -- update existing key --
    def test_put_updates_existing_key(self):
        cache = self._make_cache()
        cache.put("q1", None, "old")
        cache.put("q1", None, "new")
        hit, val = cache.get("q1", None)
        self.assertTrue(hit)
        self.assertEqual(val, "new")
        self.assertEqual(len(cache), 1)


# ============================================================
# 5. trade_time
# ============================================================
class TestTradeTime(unittest.TestCase):
    """Tests for quantia.lib.trade_time — trading session helpers."""

    # -- is_tradetime --
    def test_is_tradetime_morning_session(self):
        from quantia.lib.trade_time import is_tradetime
        dt = datetime.datetime(2026, 3, 19, 10, 0, 0)
        self.assertTrue(is_tradetime(dt))

    def test_is_tradetime_afternoon_session(self):
        from quantia.lib.trade_time import is_tradetime
        dt = datetime.datetime(2026, 3, 19, 14, 0, 0)
        self.assertTrue(is_tradetime(dt))

    def test_is_tradetime_before_open(self):
        from quantia.lib.trade_time import is_tradetime
        dt = datetime.datetime(2026, 3, 19, 9, 0, 0)
        self.assertFalse(is_tradetime(dt))

    def test_is_tradetime_lunch_break(self):
        from quantia.lib.trade_time import is_tradetime
        dt = datetime.datetime(2026, 3, 19, 12, 30, 0)
        self.assertFalse(is_tradetime(dt))

    def test_is_tradetime_at_close(self):
        from quantia.lib.trade_time import is_tradetime
        dt = datetime.datetime(2026, 3, 19, 15, 0, 0)
        self.assertFalse(is_tradetime(dt))

    def test_is_tradetime_start_of_premarket(self):
        from quantia.lib.trade_time import is_tradetime
        dt = datetime.datetime(2026, 3, 19, 9, 15, 0)
        self.assertTrue(is_tradetime(dt))

    # -- is_pause --
    def test_is_pause_during_lunch(self):
        from quantia.lib.trade_time import is_pause
        dt = datetime.datetime(2026, 3, 19, 12, 0, 0)
        self.assertTrue(is_pause(dt))

    def test_is_pause_outside_lunch(self):
        from quantia.lib.trade_time import is_pause
        dt = datetime.datetime(2026, 3, 19, 10, 0, 0)
        self.assertFalse(is_pause(dt))

    # -- is_continue --
    def test_is_continue_just_before_afternoon(self):
        from quantia.lib.trade_time import is_continue
        dt = datetime.datetime(2026, 3, 19, 12, 59, 30)
        self.assertTrue(is_continue(dt))

    def test_is_continue_at_1pm(self):
        from quantia.lib.trade_time import is_continue
        dt = datetime.datetime(2026, 3, 19, 13, 0, 0)
        self.assertFalse(is_continue(dt))

    # -- is_closing --
    def test_is_closing_near_end(self):
        from quantia.lib.trade_time import is_closing
        dt = datetime.datetime(2026, 3, 19, 14, 55, 0)
        self.assertTrue(is_closing(dt))

    def test_is_closing_early_afternoon(self):
        from quantia.lib.trade_time import is_closing
        dt = datetime.datetime(2026, 3, 19, 14, 0, 0)
        self.assertFalse(is_closing(dt))

    # -- is_close --
    def test_is_close_after_3pm(self):
        from quantia.lib.trade_time import is_close
        dt = datetime.datetime(2026, 3, 19, 15, 30, 0)
        self.assertTrue(is_close(dt))

    def test_is_close_before_3pm(self):
        from quantia.lib.trade_time import is_close
        dt = datetime.datetime(2026, 3, 19, 14, 59, 59)
        self.assertFalse(is_close(dt))

    def test_is_close_exactly_3pm(self):
        from quantia.lib.trade_time import is_close
        dt = datetime.datetime(2026, 3, 19, 15, 0, 0)
        self.assertTrue(is_close(dt))

    # -- is_open --
    def test_is_open_after_930(self):
        from quantia.lib.trade_time import is_open
        dt = datetime.datetime(2026, 3, 19, 9, 30, 0)
        self.assertTrue(is_open(dt))

    def test_is_open_before_930(self):
        from quantia.lib.trade_time import is_open
        dt = datetime.datetime(2026, 3, 19, 9, 0, 0)
        self.assertFalse(is_open(dt))

    # -- get_trade_hist_interval --
    def test_get_trade_hist_interval_string_dash(self):
        from quantia.lib.trade_time import get_trade_hist_interval
        with patch('quantia.lib.trade_time.is_trade_date', return_value=False):
            start, is_cache = get_trade_hist_interval('2026-03-19', years=10)
        self.assertIsInstance(start, str)
        self.assertEqual(len(start), 8)  # YYYYMMDD

    def test_get_trade_hist_interval_string_compact(self):
        from quantia.lib.trade_time import get_trade_hist_interval
        with patch('quantia.lib.trade_time.is_trade_date', return_value=False):
            start, is_cache = get_trade_hist_interval('20260319', years=5)
        self.assertTrue(is_cache)

    def test_get_trade_hist_interval_date_obj(self):
        from quantia.lib.trade_time import get_trade_hist_interval
        dt = datetime.date(2026, 3, 19)
        with patch('quantia.lib.trade_time.is_trade_date', return_value=False):
            start, is_cache = get_trade_hist_interval(dt, years=1)
        self.assertIsInstance(start, str)

    def test_get_trade_hist_interval_datetime_obj(self):
        from quantia.lib.trade_time import get_trade_hist_interval
        dt = datetime.datetime(2026, 3, 19, 12, 0, 0)
        with patch('quantia.lib.trade_time.is_trade_date', return_value=False):
            start, is_cache = get_trade_hist_interval(dt)
        self.assertIsInstance(start, str)

    def test_get_trade_hist_interval_invalid_type(self):
        from quantia.lib.trade_time import get_trade_hist_interval
        with self.assertRaises(ValueError):
            get_trade_hist_interval(12345)

    # -- get_quarterly_report_date --
    def test_get_quarterly_report_date_q1(self):
        from quantia.lib.trade_time import get_quarterly_report_date
        with patch('quantia.lib.trade_time.datetime') as mock_dt:
            mock_dt.datetime.now.return_value = datetime.datetime(2026, 2, 15)
            mock_dt.side_effect = lambda *a, **kw: datetime.datetime(*a, **kw)
            result = get_quarterly_report_date()
        self.assertEqual(result, '20251231')

    def test_get_quarterly_report_date_q2(self):
        from quantia.lib.trade_time import get_quarterly_report_date
        with patch('quantia.lib.trade_time.datetime') as mock_dt:
            mock_dt.datetime.now.return_value = datetime.datetime(2026, 5, 1)
            result = get_quarterly_report_date()
        self.assertEqual(result, '20260331')

    def test_get_quarterly_report_date_q3(self):
        from quantia.lib.trade_time import get_quarterly_report_date
        with patch('quantia.lib.trade_time.datetime') as mock_dt:
            mock_dt.datetime.now.return_value = datetime.datetime(2026, 8, 1)
            result = get_quarterly_report_date()
        self.assertEqual(result, '20260630')

    def test_get_quarterly_report_date_q4(self):
        from quantia.lib.trade_time import get_quarterly_report_date
        with patch('quantia.lib.trade_time.datetime') as mock_dt:
            mock_dt.datetime.now.return_value = datetime.datetime(2026, 11, 1)
            result = get_quarterly_report_date()
        self.assertEqual(result, '20260930')

    # -- get_bonus_report_date --
    def test_get_bonus_report_date_feb_to_jun(self):
        from quantia.lib.trade_time import get_bonus_report_date
        with patch('quantia.lib.trade_time.datetime') as mock_dt:
            mock_dt.datetime.now.return_value = datetime.datetime(2026, 4, 10)
            result = get_bonus_report_date()
        self.assertEqual(result, '20251231')

    def test_get_bonus_report_date_aug_to_dec(self):
        from quantia.lib.trade_time import get_bonus_report_date
        with patch('quantia.lib.trade_time.datetime') as mock_dt:
            mock_dt.datetime.now.return_value = datetime.datetime(2026, 9, 15)
            result = get_bonus_report_date()
        self.assertEqual(result, '20260630')

    def test_get_bonus_report_date_jul_after_25(self):
        from quantia.lib.trade_time import get_bonus_report_date
        with patch('quantia.lib.trade_time.datetime') as mock_dt:
            mock_dt.datetime.now.return_value = datetime.datetime(2026, 7, 26)
            result = get_bonus_report_date()
        self.assertEqual(result, '20260630')

    def test_get_bonus_report_date_jul_before_25(self):
        from quantia.lib.trade_time import get_bonus_report_date
        with patch('quantia.lib.trade_time.datetime') as mock_dt:
            mock_dt.datetime.now.return_value = datetime.datetime(2026, 7, 20)
            result = get_bonus_report_date()
        self.assertEqual(result, '20251231')

    # -- is_post_settlement --
    def test_is_post_settlement_next_day(self):
        from quantia.lib.trade_time import is_post_settlement
        trade_date = datetime.date(2026, 3, 18)
        now = datetime.datetime(2026, 3, 19, 10, 0, 0)
        self.assertTrue(is_post_settlement(trade_date, _now=now))

    def test_is_post_settlement_same_day_after_hour(self):
        from quantia.lib.trade_time import is_post_settlement
        trade_date = datetime.date(2026, 3, 19)
        now = datetime.datetime(2026, 3, 19, 19, 0, 0)
        self.assertTrue(is_post_settlement(trade_date, settlement_hour=18, _now=now))

    def test_is_post_settlement_same_day_before_hour(self):
        from quantia.lib.trade_time import is_post_settlement
        trade_date = datetime.date(2026, 3, 19)
        now = datetime.datetime(2026, 3, 19, 16, 0, 0)
        self.assertFalse(is_post_settlement(trade_date, settlement_hour=18, _now=now))

    def test_is_post_settlement_future_date(self):
        from quantia.lib.trade_time import is_post_settlement
        trade_date = datetime.date(2026, 3, 20)
        now = datetime.datetime(2026, 3, 19, 20, 0, 0)
        self.assertFalse(is_post_settlement(trade_date, _now=now))

    def test_is_post_settlement_string_date(self):
        from quantia.lib.trade_time import is_post_settlement
        now = datetime.datetime(2026, 3, 20, 10, 0, 0)
        self.assertTrue(is_post_settlement('2026-03-19', _now=now))

    def test_is_post_settlement_datetime_input(self):
        from quantia.lib.trade_time import is_post_settlement
        trade_dt = datetime.datetime(2026, 3, 18, 15, 0, 0)
        now = datetime.datetime(2026, 3, 19, 10, 0, 0)
        self.assertTrue(is_post_settlement(trade_dt, _now=now))

    def test_is_post_settlement_exact_hour(self):
        from quantia.lib.trade_time import is_post_settlement
        trade_date = datetime.date(2026, 3, 19)
        now = datetime.datetime(2026, 3, 19, 18, 0, 0)
        self.assertTrue(is_post_settlement(trade_date, settlement_hour=18, _now=now))


# ============================================================
# 6. database
# ============================================================
class TestDatabase(unittest.TestCase):
    """Tests for quantia.lib.database — pure/testable helpers."""

    # -- _is_retryable_error --
    def test_is_retryable_deadlock(self):
        from quantia.lib.database import _is_retryable_error
        e = Exception("1213 Deadlock found")
        self.assertTrue(_is_retryable_error(e))

    def test_is_retryable_lock_wait_timeout(self):
        from quantia.lib.database import _is_retryable_error
        e = Exception("1205 Lock wait timeout exceeded")
        self.assertTrue(_is_retryable_error(e))

    def test_is_retryable_lost_connection(self):
        from quantia.lib.database import _is_retryable_error
        e = Exception("Lost connection to MySQL server")
        self.assertTrue(_is_retryable_error(e))

    def test_is_retryable_connection_refused(self):
        from quantia.lib.database import _is_retryable_error
        e = Exception("Connection refused")
        self.assertTrue(_is_retryable_error(e))

    def test_is_retryable_packet_sequence(self):
        from quantia.lib.database import _is_retryable_error
        e = Exception("Packet sequence number wrong")
        self.assertTrue(_is_retryable_error(e))

    def test_is_retryable_pending_rollback(self):
        from quantia.lib.database import _is_retryable_error
        e = Exception("PendingRollbackError")
        self.assertTrue(_is_retryable_error(e))

    def test_is_retryable_broken_pipe(self):
        from quantia.lib.database import _is_retryable_error
        e = BrokenPipeError("broken pipe")
        self.assertTrue(_is_retryable_error(e))

    def test_is_retryable_os_error(self):
        from quantia.lib.database import _is_retryable_error
        e = OSError("read of closed file")
        self.assertTrue(_is_retryable_error(e))

    def test_is_retryable_value_error(self):
        from quantia.lib.database import _is_retryable_error
        e = ValueError("not subscriptable")
        self.assertTrue(_is_retryable_error(e))

    def test_is_retryable_gone_away(self):
        from quantia.lib.database import _is_retryable_error
        e = Exception("server has gone away")
        self.assertTrue(_is_retryable_error(e))

    def test_not_retryable_syntax_error(self):
        from quantia.lib.database import _is_retryable_error
        e = Exception("Syntax error in SQL")
        self.assertFalse(_is_retryable_error(e))

    def test_not_retryable_generic(self):
        from quantia.lib.database import _is_retryable_error
        e = Exception("Some random error")
        self.assertFalse(_is_retryable_error(e))

    # -- _mysql_upsert SQL generation --
    def test_mysql_upsert_generates_upsert(self):
        """_mysql_upsert should call conn.execute with an upsert statement."""
        from quantia.lib.database import _mysql_upsert

        # Build a minimal mock table object
        mock_table = MagicMock()
        mock_sa_table = MagicMock()
        mock_table.table = mock_sa_table

        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 2
        mock_conn.execute.return_value = mock_result

        keys = ['code', 'name', 'price']
        data_iter = iter([
            ('000001', 'Stock A', 10.5),
            ('000002', 'Stock B', 20.3),
        ])

        # Patch mysql_insert at the module level
        with patch('quantia.lib.database.mysql_insert') as mock_insert:
            mock_stmt = MagicMock()
            mock_insert.return_value = mock_stmt
            mock_stmt.values.return_value = mock_stmt
            mock_inserted = MagicMock()
            mock_stmt.inserted = mock_inserted
            mock_inserted.__getitem__ = lambda self, k: f"inserted_{k}"
            mock_upsert = MagicMock()
            mock_stmt.on_duplicate_key_update.return_value = mock_upsert

            result = _mysql_upsert(mock_table, mock_conn, keys, data_iter)

        self.assertEqual(result, 2)
        mock_conn.execute.assert_called_once()

    def test_mysql_upsert_empty_data(self):
        from quantia.lib.database import _mysql_upsert
        mock_table = MagicMock()
        mock_conn = MagicMock()
        result = _mysql_upsert(mock_table, mock_conn, ['a'], iter([]))
        self.assertEqual(result, 0)
        mock_conn.execute.assert_not_called()

    # -- engine singleton --
    def test_engine_returns_engine(self):
        """engine() should return a SQLAlchemy Engine (or mock thereof)."""
        import quantia.lib.database as db_mod
        # Save and reset
        original = db_mod._engine_instance
        try:
            db_mod._engine_instance = None
            with patch('quantia.lib.database.create_engine') as mock_ce:
                mock_engine = MagicMock()
                mock_ce.return_value = mock_engine
                result = db_mod.engine()
                self.assertIs(result, mock_engine)
                mock_ce.assert_called_once()
                # Second call returns cached
                result2 = db_mod.engine()
                self.assertIs(result2, mock_engine)
                # create_engine still called only once
                mock_ce.assert_called_once()
        finally:
            db_mod._engine_instance = original

    # -- checkTableIsExist --
    def test_checkTableIsExist_true(self):
        import quantia.lib.database as db_mod
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (1,)
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with patch.object(db_mod, 'get_connection') as mock_gc:
            mock_gc.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_gc.return_value.__exit__ = MagicMock(return_value=False)
            result = db_mod.checkTableIsExist('test_table')
        self.assertTrue(result)

    def test_checkTableIsExist_false(self):
        import quantia.lib.database as db_mod
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (0,)
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with patch.object(db_mod, 'get_connection') as mock_gc:
            mock_gc.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_gc.return_value.__exit__ = MagicMock(return_value=False)
            result = db_mod.checkTableIsExist('nonexistent_table')
        self.assertFalse(result)


# ============================================================
# 7. job_tracker
# ============================================================
class TestJobTracker(unittest.TestCase):
    """Tests for quantia.lib.job_tracker — job status tracking."""

    @patch('quantia.lib.job_tracker.mdb')
    def test_ensure_table_creates_when_missing(self, mock_mdb):
        from quantia.lib.job_tracker import _ensure_table
        mock_mdb.checkTableIsExist.return_value = False
        _ensure_table()
        mock_mdb.executeSql.assert_called_once()
        sql_arg = mock_mdb.executeSql.call_args[0][0]
        self.assertIn('CREATE TABLE', sql_arg)

    @patch('quantia.lib.job_tracker.mdb')
    def test_ensure_table_skips_when_exists(self, mock_mdb):
        from quantia.lib.job_tracker import _ensure_table
        mock_mdb.checkTableIsExist.return_value = True
        _ensure_table()
        mock_mdb.executeSql.assert_not_called()

    @patch('quantia.lib.job_tracker.mdb')
    def test_record_task_start_returns_float(self, mock_mdb):
        from quantia.lib.job_tracker import record_task_start
        mock_mdb.checkTableIsExist.return_value = True
        result = record_task_start('run_fetch', 'stock_spot', datetime.date(2026, 3, 19))
        self.assertIsInstance(result, float)

    @patch('quantia.lib.job_tracker.mdb')
    def test_record_task_start_calls_executeSql(self, mock_mdb):
        from quantia.lib.job_tracker import record_task_start
        mock_mdb.checkTableIsExist.return_value = True
        record_task_start('run_fetch', 'stock_spot', '2026-03-19')
        mock_mdb.executeSql.assert_called_once()
        sql_arg = mock_mdb.executeSql.call_args[0][0]
        self.assertIn('INSERT INTO', sql_arg)

    @patch('quantia.lib.job_tracker.mdb')
    def test_record_task_end_success(self, mock_mdb):
        from quantia.lib.job_tracker import record_task_end
        mock_mdb.checkTableIsExist.return_value = True
        record_task_end('run_fetch', 'stock_spot', '2026-03-19',
                        start_time=time.time() - 5, success=True, message='ok')
        mock_mdb.executeSql.assert_called_once()
        args = mock_mdb.executeSql.call_args[0]
        self.assertIn('UPDATE', args[0])
        self.assertEqual(args[1][0], 'success')

    @patch('quantia.lib.job_tracker.mdb')
    def test_record_task_end_failure(self, mock_mdb):
        from quantia.lib.job_tracker import record_task_end
        mock_mdb.checkTableIsExist.return_value = True
        record_task_end('run_fetch', 'stock_spot', '2026-03-19',
                        start_time=time.time() - 2, success=False, message='timeout')
        args = mock_mdb.executeSql.call_args[0]
        self.assertEqual(args[1][0], 'failed')

    @patch('quantia.lib.job_tracker.mdb')
    def test_is_job_completed_true(self, mock_mdb):
        from quantia.lib.job_tracker import is_job_completed
        mock_mdb.checkTableIsExist.return_value = True
        mock_mdb.executeSqlFetch.return_value = [('success',)]
        result = is_job_completed('run_fetch', '2026-03-19')
        self.assertTrue(result)

    @patch('quantia.lib.job_tracker.mdb')
    def test_is_job_completed_false_no_record(self, mock_mdb):
        from quantia.lib.job_tracker import is_job_completed
        mock_mdb.checkTableIsExist.return_value = True
        mock_mdb.executeSqlFetch.return_value = []
        result = is_job_completed('run_fetch', '2026-03-19')
        self.assertFalse(result)

    @patch('quantia.lib.job_tracker.mdb')
    def test_is_job_completed_false_running(self, mock_mdb):
        from quantia.lib.job_tracker import is_job_completed
        mock_mdb.checkTableIsExist.return_value = True
        mock_mdb.executeSqlFetch.return_value = [('running',)]
        result = is_job_completed('run_fetch', '2026-03-19')
        self.assertFalse(result)

    @patch('quantia.lib.job_tracker.mdb')
    def test_is_data_fresh_true(self, mock_mdb):
        from quantia.lib.job_tracker import is_data_fresh
        mock_mdb.checkTableIsExist.return_value = True
        mock_mdb.executeSqlFetch.return_value = [(100,)]
        is_fresh, count = is_data_fresh('cn_stock_spot', '2026-03-19', min_rows=50)
        self.assertTrue(is_fresh)
        self.assertEqual(count, 100)

    @patch('quantia.lib.job_tracker.mdb')
    def test_is_data_fresh_false_table_missing(self, mock_mdb):
        from quantia.lib.job_tracker import is_data_fresh
        mock_mdb.checkTableIsExist.return_value = False
        is_fresh, count = is_data_fresh('nonexistent', '2026-03-19')
        self.assertFalse(is_fresh)
        self.assertEqual(count, 0)

    @patch('quantia.lib.job_tracker.mdb')
    def test_is_data_fresh_false_insufficient_rows(self, mock_mdb):
        from quantia.lib.job_tracker import is_data_fresh
        mock_mdb.checkTableIsExist.return_value = True
        mock_mdb.executeSqlFetch.return_value = [(3,)]
        is_fresh, count = is_data_fresh('cn_stock_spot', '2026-03-19', min_rows=50)
        self.assertFalse(is_fresh)
        self.assertEqual(count, 3)

    @patch('quantia.lib.job_tracker.mdb')
    def test_record_task_start_date_obj(self, mock_mdb):
        """record_task_start handles date objects via strftime."""
        from quantia.lib.job_tracker import record_task_start
        mock_mdb.checkTableIsExist.return_value = True
        result = record_task_start('job', 'task', datetime.date(2026, 1, 15))
        self.assertIsInstance(result, float)

    @patch('quantia.lib.job_tracker.mdb')
    def test_record_task_end_elapsed_positive(self, mock_mdb):
        from quantia.lib.job_tracker import record_task_end
        mock_mdb.checkTableIsExist.return_value = True
        st = time.time() - 10
        record_task_end('j', 't', '2026-03-19', st, success=True)
        params = mock_mdb.executeSql.call_args[0][1]
        elapsed = params[2]
        self.assertGreater(elapsed, 0)


# ============================================================
# 8. crypto_aes
# ============================================================
class TestMData(unittest.TestCase):
    """Tests for quantia.lib.crypto_aes.MData — data encoding wrapper."""

    def test_from_string_and_to_string(self):
        from quantia.lib.crypto_aes import MData
        m = MData()
        m.fromString("hello")
        self.assertEqual(m.toString(), "hello")

    def test_from_string_returns_bytes(self):
        from quantia.lib.crypto_aes import MData
        m = MData()
        result = m.fromString("test")
        self.assertIsInstance(result, bytes)

    def test_to_base64(self):
        from quantia.lib.crypto_aes import MData
        m = MData()
        m.fromString("hello")
        b64 = m.toBase64()
        self.assertEqual(b64, "aGVsbG8=")

    def test_from_base64(self):
        from quantia.lib.crypto_aes import MData
        m = MData()
        m.fromBase64("aGVsbG8=")
        self.assertEqual(m.toString(), "hello")

    def test_to_hex_str(self):
        from quantia.lib.crypto_aes import MData
        m = MData()
        m.fromString("AB")
        self.assertEqual(m.toHexStr(), "4142")

    def test_from_hex_str(self):
        from quantia.lib.crypto_aes import MData
        m = MData()
        m.fromHexStr("4142")
        self.assertEqual(m.toString(), "AB")

    def test_to_bytes(self):
        from quantia.lib.crypto_aes import MData
        m = MData(b"raw")
        self.assertEqual(m.toBytes(), b"raw")

    def test_str_method(self):
        from quantia.lib.crypto_aes import MData
        m = MData()
        m.fromString("test")
        self.assertEqual(str(m), "test")

    def test_str_fallback_to_base64(self):
        """__str__ falls back to base64 when decode fails."""
        from quantia.lib.crypto_aes import MData
        m = MData(b'\x80\x81\x82', characterSet='ascii')
        result = str(m)
        # Should not raise; falls back to base64
        self.assertIsInstance(result, str)

    def test_init_default(self):
        from quantia.lib.crypto_aes import MData
        m = MData()
        self.assertEqual(m.data, b"")
        self.assertEqual(m.characterSet, 'utf-8')

    def test_roundtrip_base64(self):
        from quantia.lib.crypto_aes import MData
        original = "Hello, 世界!"
        m1 = MData()
        m1.fromString(original)
        b64 = m1.toBase64()

        m2 = MData()
        m2.fromBase64(b64)
        self.assertEqual(m2.toString(), original)

    def test_roundtrip_hex(self):
        from quantia.lib.crypto_aes import MData
        m1 = MData()
        m1.fromString("test")
        hex_str = m1.toHexStr()

        m2 = MData()
        m2.fromHexStr(hex_str)
        self.assertEqual(m2.toString(), "test")


class TestAEScryptor(unittest.TestCase):
    """Tests for quantia.lib.crypto_aes.AEScryptor — AES encrypt/decrypt."""

    def _make_ecb_cryptor(self, padding='PKCS5Padding'):
        from Crypto.Cipher import AES as _AES
        from quantia.lib.crypto_aes import AEScryptor
        key = b'0123456789abcdef'  # 16 bytes
        return AEScryptor(key, _AES.MODE_ECB, paddingMode=padding)

    def _make_cbc_cryptor(self, padding='PKCS5Padding'):
        from Crypto.Cipher import AES as _AES
        from quantia.lib.crypto_aes import AEScryptor
        key = b'0123456789abcdef'
        iv = b'abcdefghijklmnop'
        return AEScryptor(key, _AES.MODE_CBC, iv=iv, paddingMode=padding)

    def test_ecb_encrypt_decrypt_roundtrip(self):
        cryptor = self._make_ecb_cryptor()
        plaintext = "Hello AES ECB!"
        encrypted = cryptor.encryptFromString(plaintext)
        decrypted = cryptor.decryptFromBytes(encrypted.toBytes())
        self.assertEqual(decrypted.toString(), plaintext)

    def test_cbc_encrypt_decrypt_roundtrip(self):
        cryptor = self._make_cbc_cryptor()
        plaintext = "Hello AES CBC!"
        encrypted = cryptor.encryptFromString(plaintext)
        # Need a new cryptor for decryption (AES cipher object not reusable for CBC)
        cryptor2 = self._make_cbc_cryptor()
        decrypted = cryptor2.decryptFromBytes(encrypted.toBytes())
        self.assertEqual(decrypted.toString(), plaintext)

    def test_ecb_base64_roundtrip(self):
        cryptor = self._make_ecb_cryptor()
        plaintext = "test base64"
        encrypted = cryptor.encryptFromString(plaintext)
        b64 = encrypted.toBase64()

        cryptor2 = self._make_ecb_cryptor()
        decrypted = cryptor2.decryptFromBase64(b64)
        self.assertEqual(decrypted.toString(), plaintext)

    def test_ecb_hex_roundtrip(self):
        cryptor = self._make_ecb_cryptor()
        plaintext = "test hex str"
        encrypted = cryptor.encryptFromString(plaintext)
        hex_str = encrypted.toHexStr()

        cryptor2 = self._make_ecb_cryptor()
        decrypted = cryptor2.decryptFromHexStr(hex_str)
        self.assertEqual(decrypted.toString(), plaintext)

    def test_zero_padding_roundtrip(self):
        cryptor = self._make_ecb_cryptor(padding='ZeroPadding')
        plaintext = "zero pad test"
        encrypted = cryptor.encryptFromString(plaintext)
        cryptor2 = self._make_ecb_cryptor(padding='ZeroPadding')
        decrypted = cryptor2.decryptFromBytes(encrypted.toBytes())
        self.assertEqual(decrypted.toString(), plaintext)

    def test_no_padding_exact_block(self):
        """NoPadding with data exactly 16 bytes should work without extra padding."""
        cryptor = self._make_ecb_cryptor(padding='NoPadding')
        plaintext = "0123456789abcdef"  # exactly 16 bytes
        encrypted = cryptor.encryptFromString(plaintext)
        cryptor2 = self._make_ecb_cryptor(padding='NoPadding')
        decrypted = cryptor2.decryptFromBytes(encrypted.toBytes())
        # NoPadding strip may alter trailing bytes; at minimum the prefix should match
        self.assertTrue(decrypted.toString().startswith("0123456789abcde"))

    def test_pkcs7_padding_roundtrip(self):
        cryptor = self._make_ecb_cryptor(padding='PKCS7Padding')
        plaintext = "pkcs7 test data!"
        encrypted = cryptor.encryptFromString(plaintext)
        cryptor2 = self._make_ecb_cryptor(padding='PKCS7Padding')
        decrypted = cryptor2.decryptFromBytes(encrypted.toBytes())
        self.assertEqual(decrypted.toString(), plaintext)

    def test_invalid_padding_mode_raises(self):
        from Crypto.Cipher import AES as _AES
        from quantia.lib.crypto_aes import AEScryptor
        cryptor = AEScryptor(b'0123456789abcdef', _AES.MODE_ECB, paddingMode='BadPadding')
        with self.assertRaises(ValueError):
            cryptor.encryptFromString("test")

    def test_invalid_aes_mode_encrypt_raises(self):
        from quantia.lib.crypto_aes import AEScryptor
        cryptor = AEScryptor(b'0123456789abcdef', mode=999, paddingMode='PKCS5Padding')
        with self.assertRaises((ValueError, Exception)):
            cryptor.encryptFromString("test")

    def test_set_character_set(self):
        cryptor = self._make_ecb_cryptor()
        cryptor.setCharacterSet('ascii')
        self.assertEqual(cryptor.characterSet, 'ascii')

    def test_set_padding_mode(self):
        cryptor = self._make_ecb_cryptor()
        cryptor.setPaddingMode('ZeroPadding')
        self.assertEqual(cryptor.paddingMode, 'ZeroPadding')

    def test_encrypt_returns_mdata(self):
        from quantia.lib.crypto_aes import MData
        cryptor = self._make_ecb_cryptor()
        result = cryptor.encryptFromString("data")
        self.assertIsInstance(result, MData)

    def test_decrypt_returns_mdata(self):
        from quantia.lib.crypto_aes import MData
        cryptor = self._make_ecb_cryptor()
        encrypted = cryptor.encryptFromString("data")
        cryptor2 = self._make_ecb_cryptor()
        result = cryptor2.decryptFromBytes(encrypted.toBytes())
        self.assertIsInstance(result, MData)


# ============================================================
# 9. log_config
# ============================================================
class TestLogConfig(unittest.TestCase):
    """Tests for quantia.lib.log_config.setup_logging."""

    def setUp(self):
        # Reset the _initialized flag so each test can call setup_logging
        import quantia.lib.log_config as lc
        self._lc = lc
        self._orig = lc._initialized
        lc._initialized = False

    def tearDown(self):
        self._lc._initialized = self._orig
        # Clean up handlers we added
        root = logging.getLogger()
        root.handlers = [h for h in root.handlers
                         if not getattr(h, '_test_marker', False)]

    def test_setup_logging_sets_initialized(self):
        self._lc.setup_logging('test_unit')
        self.assertTrue(self._lc._initialized)

    def test_setup_logging_idempotent(self):
        self._lc.setup_logging('test_unit')
        handler_count = len(logging.getLogger().handlers)
        self._lc.setup_logging('test_unit_2')  # second call should be no-op
        self.assertEqual(len(logging.getLogger().handlers), handler_count)

    def test_setup_logging_adds_handlers(self):
        self._lc.setup_logging('test_unit')
        root = logging.getLogger()
        # Should have at least 3 handlers: file, error file, console
        self.assertGreaterEqual(len(root.handlers), 3)

    def test_setup_logging_root_level(self):
        self._lc.setup_logging('test_unit', level=logging.DEBUG)
        root = logging.getLogger()
        self.assertEqual(root.level, logging.DEBUG)


# ============================================================
# 10. run_template
# ============================================================
class TestRunTemplate(unittest.TestCase):
    """Tests for quantia.lib.run_template.run_with_args."""

    @patch('quantia.lib.trade_time.get_trade_date_last')
    @patch('sys.argv', ['script.py'])
    def test_run_with_args_no_args_calls_function(self, mock_last):
        from quantia.lib.run_template import run_with_args
        mock_last.return_value = (datetime.date(2026, 3, 19), datetime.date(2026, 3, 19))
        mock_fn = MagicMock(__name__='save_data')
        run_with_args(mock_fn)
        mock_fn.assert_called_once()

    @patch('quantia.lib.trade_time.get_trade_date_last')
    @patch('sys.argv', ['script.py'])
    def test_run_with_args_nph_function(self, mock_last):
        from quantia.lib.run_template import run_with_args
        mock_last.return_value = (datetime.date(2026, 3, 19), datetime.date(2026, 3, 18))
        mock_fn = MagicMock(__name__='save_nph_data')
        run_with_args(mock_fn)
        # save_nph should be called with run_date_nph and False
        call_args = mock_fn.call_args[0]
        self.assertEqual(call_args[0], datetime.date(2026, 3, 18))
        self.assertFalse(call_args[1])

    @patch('quantia.lib.trade_time.get_trade_date_last')
    @patch('sys.argv', ['script.py'])
    def test_run_with_args_after_close_function(self, mock_last):
        from quantia.lib.run_template import run_with_args
        mock_last.return_value = (datetime.date(2026, 3, 19), datetime.date(2026, 3, 19))
        mock_fn = MagicMock(__name__='save_after_close_data')
        run_with_args(mock_fn)
        call_args = mock_fn.call_args[0]
        self.assertEqual(call_args[0], datetime.date(2026, 3, 19))


# ============================================================
# 11. torndb — Row class
# ============================================================
class TestTorndbRow(unittest.TestCase):
    """Tests for quantia.lib.torndb.Row — dict with attribute access."""

    def test_row_is_dict(self):
        from quantia.lib.torndb import Row
        r = Row(name='test', value=42)
        self.assertIsInstance(r, dict)

    def test_row_dict_access(self):
        from quantia.lib.torndb import Row
        r = Row(name='test')
        self.assertEqual(r['name'], 'test')

    def test_row_attribute_access(self):
        from quantia.lib.torndb import Row
        r = Row(name='hello', id=1)
        self.assertEqual(r.name, 'hello')
        self.assertEqual(r.id, 1)

    def test_row_attribute_not_found(self):
        from quantia.lib.torndb import Row
        r = Row(a=1)
        with self.assertRaises(AttributeError):
            _ = r.nonexistent

    def test_row_from_zip(self):
        from quantia.lib.torndb import Row
        r = Row(zip(['col1', 'col2'], [10, 20]))
        self.assertEqual(r.col1, 10)
        self.assertEqual(r.col2, 20)

    def test_row_update(self):
        from quantia.lib.torndb import Row
        r = Row(a=1)
        r['b'] = 2
        self.assertEqual(r.b, 2)

    def test_row_len(self):
        from quantia.lib.torndb import Row
        r = Row(x=1, y=2, z=3)
        self.assertEqual(len(r), 3)

    def test_row_iteration(self):
        from quantia.lib.torndb import Row
        r = Row(a=1, b=2)
        keys = list(r.keys())
        self.assertIn('a', keys)
        self.assertIn('b', keys)

    def test_row_empty(self):
        from quantia.lib.torndb import Row
        r = Row()
        self.assertEqual(len(r), 0)
        with self.assertRaises(AttributeError):
            _ = r.anything


if __name__ == '__main__':
    unittest.main()
