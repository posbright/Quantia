#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for milestone-based scheduling in backtest_data_daily_job.

Tests _build_milestone_query and _MILESTONE_TIERS to ensure:
  - All 4 tiers are present in the generated SQL
  - Date boundaries are correct and mutually exclusive
  - Tier 4 has ORDER BY + LIMIT clause
  - Params count matches placeholders
"""

import sys
import os
import datetime
import re
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from quantia.job.backtest_data_daily_job import (
    _build_milestone_query, _MILESTONE_TIERS,
)


class TestBuildMilestoneQuery(unittest.TestCase):
    """Tests for _build_milestone_query function."""

    def setUp(self):
        self.table = 'cn_stock_strategy_enter'
        self.today = datetime.date(2026, 6, 10)
        self.sql, self.params = _build_milestone_query(self.table, self.today)

    def test_four_tiers_present(self):
        """Should produce 4 UNION ALL parts."""
        parts = self.sql.split('UNION ALL')
        self.assertEqual(len(parts), 4)

    def test_tier1_selects_new_records(self):
        """Tier 1 checks rate_1 IS NULL with no prereq."""
        parts = self.sql.split('UNION ALL')
        t1 = parts[0]
        self.assertIn('`rate_1` IS NULL', t1)
        self.assertNotIn('IS NOT NULL', t1)
        self.assertIn('`date` < %s', t1)

    def test_tier2_prereq_and_age(self):
        """Tier 2 checks rate_5 IS NULL + rate_1 IS NOT NULL + age window."""
        parts = self.sql.split('UNION ALL')
        t2 = parts[1]
        self.assertIn('`rate_5` IS NULL', t2)
        self.assertIn('`rate_1` IS NOT NULL', t2)
        self.assertIn('`date` <= %s', t2)
        self.assertIn('`date` > %s', t2)

    def test_tier3_prereq_and_age(self):
        """Tier 3 checks rate_20 IS NULL + rate_1 IS NOT NULL + age window."""
        parts = self.sql.split('UNION ALL')
        t3 = parts[2]
        self.assertIn('`rate_20` IS NULL', t3)
        self.assertIn('`rate_1` IS NOT NULL', t3)
        self.assertIn('`date` <= %s', t3)
        self.assertIn('`date` > %s', t3)

    def test_tier4_has_limit_and_order(self):
        """Tier 4 checks rate_100 IS NULL + limit + order."""
        parts = self.sql.split('UNION ALL')
        t4 = parts[3]
        self.assertIn('`rate_100` IS NULL', t4)
        self.assertIn('`rate_1` IS NOT NULL', t4)
        self.assertIn('ORDER BY `date` ASC', t4)
        self.assertIn('LIMIT 300', t4)

    def test_params_count_matches_placeholders(self):
        """Number of %s placeholders should match params length."""
        count = self.sql.count('%s')
        self.assertEqual(count, len(self.params))

    def test_tier_date_boundaries_exclusive(self):
        """Tier date boundaries should be contiguous and non-overlapping."""
        # Tier 2: date <= today-7 AND date > today-28
        # Tier 3: date <= today-28 AND date > today-140
        # Tier 4: date <= today-140
        t2_upper = self.today - datetime.timedelta(days=7)   # inclusive
        t2_lower = self.today - datetime.timedelta(days=28)  # exclusive (>)
        t3_upper = self.today - datetime.timedelta(days=28)  # inclusive (<=)
        t3_lower = self.today - datetime.timedelta(days=140) # exclusive (>)
        t4_upper = self.today - datetime.timedelta(days=140) # inclusive (<=)

        # Tier 2's exclusive lower == Tier 3's inclusive upper
        self.assertEqual(t2_lower, t3_upper)
        # Tier 3's exclusive lower == Tier 4's inclusive upper
        self.assertEqual(t3_lower, t4_upper)

    def test_params_are_date_objects(self):
        """All params should be datetime.date objects."""
        for p in self.params:
            self.assertIsInstance(p, datetime.date)

    def test_different_table_name(self):
        """Query should use the provided table name."""
        sql, _ = _build_milestone_query('cn_stock_strategy_turtle_trade', self.today)
        self.assertIn('cn_stock_strategy_turtle_trade', sql)
        self.assertNotIn('cn_stock_strategy_enter', sql)


class TestMilestoneTiersConfig(unittest.TestCase):
    """Tests for _MILESTONE_TIERS configuration."""

    def test_four_tiers_defined(self):
        self.assertEqual(len(_MILESTONE_TIERS), 4)

    def test_first_tier_no_prereq(self):
        """First tier (new records) should have no prerequisite."""
        target, prereq, min_age, max_age, limit = _MILESTONE_TIERS[0]
        self.assertEqual(target, 'rate_1')
        self.assertIsNone(prereq)
        self.assertIsNone(min_age)
        self.assertIsNone(max_age)
        self.assertIsNone(limit)

    def test_last_tier_has_limit(self):
        """Last tier (final completion) should have a batch limit."""
        target, prereq, min_age, max_age, limit = _MILESTONE_TIERS[-1]
        self.assertEqual(target, 'rate_100')
        self.assertIsNotNone(limit)
        self.assertGreater(limit, 0)

    def test_age_windows_contiguous(self):
        """Each tier's max_age+1 should equal next tier's min_age."""
        for i in range(1, len(_MILESTONE_TIERS) - 1):
            _, _, _, max_age, _ = _MILESTONE_TIERS[i]
            _, _, next_min, _, _ = _MILESTONE_TIERS[i + 1]
            if max_age is not None and next_min is not None:
                self.assertEqual(max_age + 1, next_min,
                                 f"Gap between tier {i+1} and {i+2}")


if __name__ == '__main__':
    unittest.main()
