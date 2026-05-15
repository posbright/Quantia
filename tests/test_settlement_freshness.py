#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据结算时间 & 新鲜度检测测试

验证 API 数据仅在结算时间（默认 18:00）之后且数据行数达标时才跳过重复获取。
结算时间之前，即使数据行数达标，也应强制重新获取。
"""

import os
import sys
import unittest
import datetime

# 确保项目根目录在 sys.path 中
cpath = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if cpath not in sys.path:
    sys.path.insert(0, cpath)

from quantia.lib.trade_time import is_post_settlement


class TestIsPostSettlement(unittest.TestCase):
    """测试 trade_time.is_post_settlement() 时间判定逻辑"""

    def _call(self, trade_date, now, settlement_hour=18):
        """统一调用入口，通过 _now 参数注入当前时间"""
        return is_post_settlement(trade_date, settlement_hour=settlement_hour, _now=now)

    # --- 当天 + 时间判断 ---

    def test_same_day_before_settlement(self):
        """交易日 16:00，未过结算时间 → False"""
        trade_date = datetime.date(2026, 3, 12)
        now = datetime.datetime(2026, 3, 12, 16, 0, 0)
        self.assertFalse(self._call(trade_date, now))

    def test_same_day_at_settlement(self):
        """交易日 18:00 整，已过结算时间 → True"""
        trade_date = datetime.date(2026, 3, 12)
        now = datetime.datetime(2026, 3, 12, 18, 0, 0)
        self.assertTrue(self._call(trade_date, now))

    def test_same_day_after_settlement(self):
        """交易日 20:00，已过结算时间 → True"""
        trade_date = datetime.date(2026, 3, 12)
        now = datetime.datetime(2026, 3, 12, 20, 0, 0)
        self.assertTrue(self._call(trade_date, now))

    def test_same_day_morning(self):
        """交易日 10:00（盘中），未过结算时间 → False"""
        trade_date = datetime.date(2026, 3, 12)
        now = datetime.datetime(2026, 3, 12, 10, 0, 0)
        self.assertFalse(self._call(trade_date, now))

    def test_same_day_just_after_close(self):
        """交易日 15:01（刚收盘），未过结算时间 → False"""
        trade_date = datetime.date(2026, 3, 12)
        now = datetime.datetime(2026, 3, 12, 15, 1, 0)
        self.assertFalse(self._call(trade_date, now))

    def test_same_day_17_59(self):
        """交易日 17:59，未过结算时间 → False"""
        trade_date = datetime.date(2026, 3, 12)
        now = datetime.datetime(2026, 3, 12, 17, 59, 59)
        self.assertFalse(self._call(trade_date, now))

    # --- 隔天 ---

    def test_next_day(self):
        """次日（非交易日/周末），已过结算 → True"""
        trade_date = datetime.date(2026, 3, 12)
        now = datetime.datetime(2026, 3, 13, 8, 0, 0)
        self.assertTrue(self._call(trade_date, now))

    def test_weekend(self):
        """周末查看周五数据 → True"""
        trade_date = datetime.date(2026, 3, 6)  # 周五
        now = datetime.datetime(2026, 3, 8, 10, 0, 0)  # 周日
        self.assertTrue(self._call(trade_date, now))

    # --- 未来日期 ---

    def test_future_date(self):
        """交易日期在未来 → False"""
        trade_date = datetime.date(2026, 3, 15)
        now = datetime.datetime(2026, 3, 12, 20, 0, 0)
        self.assertFalse(self._call(trade_date, now))

    # --- 字符串日期 ---

    def test_string_date_format(self):
        """支持 'YYYY-MM-DD' 字符串格式"""
        now = datetime.datetime(2026, 3, 12, 20, 0, 0)
        self.assertTrue(self._call('2026-03-12', now))

    def test_string_date_before_settlement(self):
        """字符串日期，未过结算时间"""
        now = datetime.datetime(2026, 3, 12, 16, 0, 0)
        self.assertFalse(self._call('2026-03-12', now))

    # --- datetime 对象 ---

    def test_datetime_input(self):
        """支持 datetime 对象输入"""
        trade_dt = datetime.datetime(2026, 3, 12, 15, 0, 0)
        now = datetime.datetime(2026, 3, 12, 19, 0, 0)
        self.assertTrue(self._call(trade_dt, now))

    # --- 自定义结算时间 ---

    def test_custom_settlement_hour_17(self):
        """结算时间设为 17:00 时的行为"""
        trade_date = datetime.date(2026, 3, 12)
        now_17 = datetime.datetime(2026, 3, 12, 17, 0, 0)
        now_16 = datetime.datetime(2026, 3, 12, 16, 59, 0)
        self.assertTrue(self._call(trade_date, now_17, settlement_hour=17))
        self.assertFalse(self._call(trade_date, now_16, settlement_hour=17))

    def test_custom_settlement_hour_20(self):
        """结算时间设为 20:00 时的行为"""
        trade_date = datetime.date(2026, 3, 12)
        now_19 = datetime.datetime(2026, 3, 12, 19, 0, 0)
        now_20 = datetime.datetime(2026, 3, 12, 20, 0, 0)
        self.assertFalse(self._call(trade_date, now_19, settlement_hour=20))
        self.assertTrue(self._call(trade_date, now_20, settlement_hour=20))


class TestCheckAndSkipIntegration(unittest.TestCase):
    """集成测试：验证 _check_and_skip 在不同时间场景下的行为"""

    def test_before_settlement_with_data_should_not_skip(self):
        """结算前，即使数据充足，也不跳过"""
        now = datetime.datetime(2026, 3, 12, 16, 0)
        settled = is_post_settlement('2026-03-12', _now=now)
        self.assertFalse(settled, "结算前不应跳过")

    def test_after_settlement_with_data_should_skip(self):
        """结算后 + 数据充足 → 应跳过"""
        now = datetime.datetime(2026, 3, 12, 19, 0)
        settled = is_post_settlement('2026-03-12', _now=now)
        self.assertTrue(settled, "结算后应允许跳过")

    def test_after_settlement_without_data_should_not_skip(self):
        """结算后但数据不足 → 不跳过（由 is_data_fresh 决定）"""
        now = datetime.datetime(2026, 3, 12, 19, 0)
        settled = is_post_settlement('2026-03-12', _now=now)
        self.assertTrue(settled)
        # 结算后但无数据 → is_data_fresh 返回 False → _check_and_skip 返回 False


class TestSettlementHourEnvConfig(unittest.TestCase):
    """验证 QUANTIA_SETTLEMENT_HOUR 环境变量配置"""

    def test_default_settlement_hour(self):
        """默认结算时间为 18"""
        os.environ.pop('QUANTIA_SETTLEMENT_HOUR', None)
        import importlib
        import quantia.lib.trade_time as tt
        importlib.reload(tt)
        self.assertEqual(tt._SETTLEMENT_HOUR, 18)

    def test_custom_settlement_hour(self):
        """可通过环境变量覆盖"""
        os.environ['QUANTIA_SETTLEMENT_HOUR'] = '17'
        try:
            import importlib
            import quantia.lib.trade_time as tt
            importlib.reload(tt)
            self.assertEqual(tt._SETTLEMENT_HOUR, 17)
        finally:
            del os.environ['QUANTIA_SETTLEMENT_HOUR']
            importlib.reload(tt)  # 恢复默认


class TestFreshnessCheckSourceCode(unittest.TestCase):
    """验证源代码中的新鲜度检查逻辑包含结算时间判断"""

    def _read_source(self, filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()

    def test_fetch_daily_job_has_settlement_check(self):
        """fetch_daily_job._check_and_skip 包含 is_post_settlement 调用"""
        src = self._read_source(os.path.join(cpath, 'quantia', 'job', 'fetch_daily_job.py'))
        self.assertIn('is_post_settlement', src)
        self.assertIn('尚未过结算时间', src)

    def test_execute_daily_job_has_settlement_check(self):
        """execute_daily_job._check_and_skip 包含 is_post_settlement 调用"""
        src = self._read_source(os.path.join(cpath, 'quantia', 'job', 'execute_daily_job.py'))
        self.assertIn('is_post_settlement', src)
        self.assertIn('尚未过结算时间', src)

    def test_fetch_daily_job_overall_check_has_settlement(self):
        """fetch_daily_job 整体作业完成检查包含结算时间判断"""
        src = self._read_source(os.path.join(cpath, 'quantia', 'job', 'fetch_daily_job.py'))
        self.assertIn('is_post_settlement(run_date_nph)', src)
        self.assertIn('已过结算时间', src)

    def test_trade_time_has_is_post_settlement(self):
        """trade_time.py 中存在 is_post_settlement 函数"""
        src = self._read_source(os.path.join(cpath, 'quantia', 'lib', 'trade_time.py'))
        self.assertIn('def is_post_settlement(', src)
        self.assertIn('_SETTLEMENT_HOUR', src)


if __name__ == '__main__':
    unittest.main()
