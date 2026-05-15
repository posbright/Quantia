#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
性能参数环境变量配置测试

验证所有新增的并发/超时环境变量可通过 envconfig 正确读取，
并且在未设置时使用正确的默认值。
"""

import os
import unittest


class TestPerfEnvDefaults(unittest.TestCase):
    """验证各模块的性能参数默认值正确"""

    def test_indicator_workers_default(self):
        os.environ.pop('QUANTIA_INDICATOR_WORKERS', None)
        import importlib, quantia.job.indicators_data_daily_job as m
        importlib.reload(m)
        self.assertEqual(m._INDICATOR_WORKERS, 4)

    def test_kline_pattern_workers_default(self):
        os.environ.pop('QUANTIA_KLINE_PATTERN_WORKERS', None)
        import importlib, quantia.job.klinepattern_data_daily_job as m
        importlib.reload(m)
        self.assertEqual(m._KLINE_PATTERN_WORKERS, 4)

    def test_strategy_workers_default(self):
        os.environ.pop('QUANTIA_STRATEGY_WORKERS', None)
        os.environ.pop('QUANTIA_STRATEGY_OUTER_WORKERS', None)
        import importlib, quantia.job.strategy_data_daily_job as m
        importlib.reload(m)
        self.assertEqual(m._STRATEGY_WORKERS, 4)
        self.assertEqual(m._STRATEGY_OUTER_WORKERS, 2)

    def test_batch_date_workers_default(self):
        os.environ.pop('QUANTIA_BATCH_DATE_WORKERS', None)
        import importlib, quantia.lib.run_template as m
        importlib.reload(m)
        self.assertEqual(m._BATCH_DATE_WORKERS, 3)

    def test_crawl_workers_default(self):
        os.environ.pop('QUANTIA_CRAWL_WORKERS', None)
        import importlib, quantia.core.crawling.stock_sina as m
        importlib.reload(m)
        self.assertEqual(m._CRAWL_WORKERS, 5)

    def test_db_conn_retries_default(self):
        # 默认 3：max_retries == 1 时 `attempt < max_retries` 永远 False，
        # 重试逻辑形同虚设，会导致 MySQL 偶发超时直接雪崩（见 stock_error.log 2026-04-28）。
        os.environ.pop('QUANTIA_DB_CONN_RETRIES', None)
        import importlib, quantia.lib.database as m
        importlib.reload(m)
        self.assertEqual(m._DB_CONN_RETRIES, 3)

    def test_job_timeout_defaults(self):
        """验证 execute_daily_job 中的超时默认值（通过 envconfig 间接验证）"""
        os.environ.pop('QUANTIA_JOB_TIMEOUT', None)
        os.environ.pop('QUANTIA_KLINE_JOB_TIMEOUT', None)
        import quantia.lib.envconfig as _cfg
        self.assertEqual(_cfg.get_int('QUANTIA_JOB_TIMEOUT', 1800), 1800)
        self.assertEqual(_cfg.get_int('QUANTIA_KLINE_JOB_TIMEOUT', 36000), 36000)


class TestPerfEnvOverride(unittest.TestCase):
    """验证通过环境变量可覆盖默认值"""

    def test_indicator_workers_override(self):
        os.environ['QUANTIA_INDICATOR_WORKERS'] = '16'
        try:
            import importlib, quantia.job.indicators_data_daily_job as m
            importlib.reload(m)
            self.assertEqual(m._INDICATOR_WORKERS, 16)
        finally:
            del os.environ['QUANTIA_INDICATOR_WORKERS']

    def test_crawl_workers_override(self):
        os.environ['QUANTIA_CRAWL_WORKERS'] = '20'
        try:
            import importlib, quantia.core.crawling.stock_sina as m
            importlib.reload(m)
            self.assertEqual(m._CRAWL_WORKERS, 20)
        finally:
            del os.environ['QUANTIA_CRAWL_WORKERS']

    def test_strategy_outer_workers_override(self):
        os.environ['QUANTIA_STRATEGY_OUTER_WORKERS'] = '6'
        try:
            import importlib, quantia.job.strategy_data_daily_job as m
            importlib.reload(m)
            self.assertEqual(m._STRATEGY_OUTER_WORKERS, 6)
        finally:
            del os.environ['QUANTIA_STRATEGY_OUTER_WORKERS']

    def test_db_conn_retries_override(self):
        os.environ['QUANTIA_DB_CONN_RETRIES'] = '5'
        try:
            import importlib, quantia.lib.database as m
            importlib.reload(m)
            self.assertEqual(m._DB_CONN_RETRIES, 5)
        finally:
            del os.environ['QUANTIA_DB_CONN_RETRIES']

    def test_job_timeout_override(self):
        """验证超时环境变量覆盖（通过 envconfig 间接验证）"""
        os.environ['QUANTIA_JOB_TIMEOUT'] = '3600'
        os.environ['QUANTIA_KLINE_JOB_TIMEOUT'] = '72000'
        try:
            import quantia.lib.envconfig as _cfg
            self.assertEqual(_cfg.get_int('QUANTIA_JOB_TIMEOUT', 1800), 3600)
            self.assertEqual(_cfg.get_int('QUANTIA_KLINE_JOB_TIMEOUT', 36000), 72000)
        finally:
            del os.environ['QUANTIA_JOB_TIMEOUT']
            del os.environ['QUANTIA_KLINE_JOB_TIMEOUT']


if __name__ == '__main__':
    unittest.main()
