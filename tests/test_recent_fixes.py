#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证最近三次修复的正确性：
1. stock_chip_race.py — JSONDecodeError 处理
2. stockfetch._fetch_from_sources — 空数据不重试
3. stockfetch.update_all_caches — KeyboardInterrupt 优雅退出
"""

import sys
import os
import unittest
from unittest.mock import patch, MagicMock, PropertyMock
import pandas as pd
import logging

# 确保项目根目录在 sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


# ══════════════════════════════════════════════
# 1. stock_chip_race.py — JSONDecodeError 处理
# ══════════════════════════════════════════════
class TestChipRaceJSONDecodeError(unittest.TestCase):
    """验证 stock_chip_race 在各种异常响应下不崩溃，返回空 DataFrame"""

    @patch('quantia.core.crawling.stock_chip_race.proxys')
    @patch('quantia.core.crawling.stock_chip_race.requests.post')
    def test_open_http_500_returns_empty(self, mock_post, mock_proxys):
        """HTTP 500 → 返回空 DataFrame，不抛异常"""
        from quantia.core.crawling.stock_chip_race import stock_chip_race_open
        mock_proxy_inst = MagicMock()
        mock_proxy_inst.get_proxies.return_value = {}
        mock_proxys.return_value = mock_proxy_inst
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_post.return_value = mock_response
        result = stock_chip_race_open()
        self.assertIsInstance(result, pd.DataFrame)
        self.assertEqual(len(result), 0)

    @patch('quantia.core.crawling.stock_chip_race.proxys')
    @patch('quantia.core.crawling.stock_chip_race.requests.post')
    def test_open_json_decode_error_returns_empty(self, mock_post, mock_proxys):
        """响应 200 但 body 非 JSON → 捕获 JSONDecodeError，返回空 DataFrame"""
        from quantia.core.crawling.stock_chip_race import stock_chip_race_open
        import requests
        mock_proxy_inst = MagicMock()
        mock_proxy_inst.get_proxies.return_value = {}
        mock_proxys.return_value = mock_proxy_inst
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = requests.exceptions.JSONDecodeError("msg", "doc", 0)
        mock_response.text = ""
        mock_post.return_value = mock_response
        result = stock_chip_race_open()
        self.assertIsInstance(result, pd.DataFrame)
        self.assertEqual(len(result), 0)

    @patch('quantia.core.crawling.stock_chip_race.proxys')
    @patch('quantia.core.crawling.stock_chip_race.requests.post')
    def test_open_value_error_returns_empty(self, mock_post, mock_proxys):
        """响应 200 但 json() 抛 ValueError → 捕获，返回空 DataFrame"""
        from quantia.core.crawling.stock_chip_race import stock_chip_race_open
        mock_proxy_inst = MagicMock()
        mock_proxy_inst.get_proxies.return_value = {}
        mock_proxys.return_value = mock_proxy_inst
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("No JSON")
        mock_response.text = "<!DOCTYPE html>"
        mock_post.return_value = mock_response
        result = stock_chip_race_open()
        self.assertIsInstance(result, pd.DataFrame)
        self.assertEqual(len(result), 0)

    @patch('quantia.core.crawling.stock_chip_race.proxys')
    @patch('quantia.core.crawling.stock_chip_race.requests.post')
    def test_open_empty_datas_returns_empty(self, mock_post, mock_proxys):
        """JSON 正常但 datas 为空 → 返回空 DataFrame"""
        from quantia.core.crawling.stock_chip_race import stock_chip_race_open
        mock_proxy_inst = MagicMock()
        mock_proxy_inst.get_proxies.return_value = {}
        mock_proxys.return_value = mock_proxy_inst
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"datas": []}
        mock_post.return_value = mock_response
        result = stock_chip_race_open()
        self.assertIsInstance(result, pd.DataFrame)
        self.assertEqual(len(result), 0)

    @patch('quantia.core.crawling.stock_chip_race.proxys')
    @patch('quantia.core.crawling.stock_chip_race.requests.post')
    def test_open_connection_error_returns_empty(self, mock_post, mock_proxys):
        """requests.post 连接异常 → 返回空 DataFrame"""
        from quantia.core.crawling.stock_chip_race import stock_chip_race_open
        mock_proxy_inst = MagicMock()
        mock_proxy_inst.get_proxies.return_value = {}
        mock_proxys.return_value = mock_proxy_inst
        mock_post.side_effect = ConnectionError("Connection refused")
        result = stock_chip_race_open()
        self.assertIsInstance(result, pd.DataFrame)
        self.assertEqual(len(result), 0)

    @patch('quantia.core.crawling.stock_chip_race.proxys')
    @patch('quantia.core.crawling.stock_chip_race.requests.post')
    def test_end_http_500_returns_empty(self, mock_post, mock_proxys):
        """stock_chip_race_end: HTTP 500 → 返回空 DataFrame"""
        from quantia.core.crawling.stock_chip_race import stock_chip_race_end
        mock_proxy_inst = MagicMock()
        mock_proxy_inst.get_proxies.return_value = {}
        mock_proxys.return_value = mock_proxy_inst
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_post.return_value = mock_response
        result = stock_chip_race_end()
        self.assertIsInstance(result, pd.DataFrame)
        self.assertEqual(len(result), 0)

    @patch('quantia.core.crawling.stock_chip_race.proxys')
    @patch('quantia.core.crawling.stock_chip_race.requests.post')
    def test_end_json_decode_error_returns_empty(self, mock_post, mock_proxys):
        """stock_chip_race_end: 非 JSON 响应 → 返回空 DataFrame"""
        from quantia.core.crawling.stock_chip_race import stock_chip_race_end
        import requests
        mock_proxy_inst = MagicMock()
        mock_proxy_inst.get_proxies.return_value = {}
        mock_proxys.return_value = mock_proxy_inst
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = requests.exceptions.JSONDecodeError("msg", "doc", 0)
        mock_response.text = ""
        mock_post.return_value = mock_response
        result = stock_chip_race_end()
        self.assertIsInstance(result, pd.DataFrame)
        self.assertEqual(len(result), 0)

    @patch('quantia.core.crawling.stock_chip_race.proxys')
    @patch('quantia.core.crawling.stock_chip_race.requests.post')
    def test_open_valid_json_returns_data(self, mock_post, mock_proxys):
        """正常 JSON 响应 → 应返回有数据的 DataFrame"""
        from quantia.core.crawling.stock_chip_race import stock_chip_race_open
        mock_proxy_inst = MagicMock()
        mock_proxy_inst.get_proxies.return_value = {}
        mock_proxys.return_value = mock_proxy_inst
        mock_response = MagicMock()
        mock_response.status_code = 200
        # 模拟一行真实数据: [代码, 名称, 昨收*10000, 今开*10000, 开盘金额, 抢筹幅度/100, 委托金额, 成交金额, 最新价, _, 天, 板]
        mock_response.json.return_value = {
            "datas": [
                ["000001", "平安银行", 100000, 105000, 500000, 0.05, 300000, 200000, 10.50, 0, 3, 1]
            ]
        }
        mock_post.return_value = mock_response
        result = stock_chip_race_open()
        self.assertIsInstance(result, pd.DataFrame)
        self.assertEqual(len(result), 1)
        self.assertIn("代码", result.columns)
        self.assertEqual(result.iloc[0]["代码"], "000001")


# ══════════════════════════════════════════════
# 2. _fetch_from_sources — 空数据不重试
# ══════════════════════════════════════════════
class TestFetchFromSourcesEmptyData(unittest.TestCase):
    """验证 _fetch_from_sources 在 API 返回空数据时立即返回，不重试不换源"""

    def setUp(self):
        """重置数据源健康状态"""
        import quantia.core.stockfetch as stf
        with stf._source_health_lock:
            stf._source_fail_counts.clear()
            stf._source_cooldown_until.clear()
            stf._source_degrade_count.clear()
            stf._source_is_degraded.clear()

    @patch('quantia.core.stockfetch.shs.stock_zh_a_hist_sina')
    @patch('quantia.core.stockfetch.sht.stock_zh_a_hist_tencent')
    @patch('quantia.core.stockfetch.she.stock_zh_a_hist')
    def test_empty_dataframe_returns_none_immediately(self, mock_em, mock_tc, mock_sina):
        """数据源返回空 DataFrame → 立即返回 None，不调用其他数据源"""
        from quantia.core.stockfetch import _fetch_from_sources
        mock_em.return_value = pd.DataFrame()  # 空 DataFrame
        result = _fetch_from_sources('000001', '20260101', '20260312')
        self.assertIsNone(result)
        # 关键验证：只调了东方财富一次，腾讯和新浪根本没被调用
        mock_em.assert_called_once()
        mock_tc.assert_not_called()
        mock_sina.assert_not_called()

    @patch('quantia.core.stockfetch.shs.stock_zh_a_hist_sina')
    @patch('quantia.core.stockfetch.sht.stock_zh_a_hist_tencent')
    @patch('quantia.core.stockfetch.she.stock_zh_a_hist')
    def test_none_returns_none_immediately(self, mock_em, mock_tc, mock_sina):
        """数据源返回 None → 立即返回 None，不调用其他数据源"""
        from quantia.core.stockfetch import _fetch_from_sources
        mock_em.return_value = None
        result = _fetch_from_sources('000001', '20260101', '20260312')
        self.assertIsNone(result)
        mock_em.assert_called_once()
        mock_tc.assert_not_called()
        mock_sina.assert_not_called()

    @patch('quantia.core.stockfetch._report_source_failure')
    @patch('quantia.core.stockfetch.shs.stock_zh_a_hist_sina')
    @patch('quantia.core.stockfetch.sht.stock_zh_a_hist_tencent')
    @patch('quantia.core.stockfetch.she.stock_zh_a_hist')
    def test_empty_data_not_reported_as_failure(self, mock_em, mock_tc, mock_sina, mock_report_fail):
        """空数据不应触发 _report_source_failure"""
        from quantia.core.stockfetch import _fetch_from_sources
        mock_em.return_value = pd.DataFrame()
        _fetch_from_sources('000001', '20260101', '20260312')
        mock_report_fail.assert_not_called()

    @patch('quantia.core.stockfetch._report_source_success')
    @patch('quantia.core.stockfetch.shs.stock_zh_a_hist_sina')
    @patch('quantia.core.stockfetch.sht.stock_zh_a_hist_tencent')
    @patch('quantia.core.stockfetch.she.stock_zh_a_hist')
    def test_valid_data_returns_dataframe(self, mock_em, mock_tc, mock_sina, mock_report_ok):
        """有数据时正常返回 DataFrame 并报告成功"""
        from quantia.core.stockfetch import _fetch_from_sources
        import quantia.core.tablestructure as tbs
        cols = tuple(tbs.CN_STOCK_HIST_DATA['columns'])
        mock_data = pd.DataFrame([[
            '2026-03-12', 10.0, 10.5, 11.0, 9.8, 100000, 1050000, 5.0, 2.5, 0.25, 3.2
        ]], columns=list(cols))
        mock_em.return_value = mock_data
        result = _fetch_from_sources('000001', '20260312', '20260312')
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 1)
        mock_report_ok.assert_called_once()
        mock_tc.assert_not_called()  # 成功后不应尝试其他数据源

    @patch('quantia.core.stockfetch._retry_sleep')
    @patch('quantia.core.stockfetch.shs.stock_zh_a_hist_sina')
    @patch('quantia.core.stockfetch.sht.stock_zh_a_hist_tencent')
    @patch('quantia.core.stockfetch.she.stock_zh_a_hist')
    def test_connection_error_switches_source(self, mock_em, mock_tc, mock_sina, mock_sleep):
        """连接异常时应换源（不重试同一源），最终第二个源的空数据也立即返回"""
        from quantia.core.stockfetch import _fetch_from_sources
        mock_em.side_effect = ConnectionError("Connection refused")
        mock_tc.return_value = pd.DataFrame()  # 腾讯返回空
        result = _fetch_from_sources('000001', '20260101', '20260312')
        self.assertIsNone(result)
        mock_em.assert_called_once()  # 东方财富只调一次（连接错误直接换源）
        mock_tc.assert_called_once()  # 腾讯被调了一次
        mock_sina.assert_not_called()  # 腾讯返回空 → 直接return，新浪不被调用

    @patch('quantia.core.stockfetch._retry_sleep')
    @patch('quantia.core.stockfetch.shs.stock_zh_a_hist_sina')
    @patch('quantia.core.stockfetch.sht.stock_zh_a_hist_tencent')
    @patch('quantia.core.stockfetch.she.stock_zh_a_hist')
    def test_exception_retries_then_switches(self, mock_em, mock_tc, mock_sina, mock_sleep):
        """普通异常走重试逻辑 → 重试完毕后换源"""
        from quantia.core.stockfetch import _fetch_from_sources, DATA_SOURCE_MAX_RETRIES
        mock_em.side_effect = RuntimeError("unknown error")
        mock_tc.return_value = pd.DataFrame()
        result = _fetch_from_sources('000001', '20260101', '20260312')
        self.assertIsNone(result)
        # 东方财富被调用 MAX_RETRIES 次
        self.assertEqual(mock_em.call_count, DATA_SOURCE_MAX_RETRIES)
        # 腾讯返回空 → 立即返回
        mock_tc.assert_called_once()


# ══════════════════════════════════════════════
# 3. stockfetch.py — chip_race 日志降级验证
# ══════════════════════════════════════════════
class TestChipRaceLogLevel(unittest.TestCase):
    """验证 chip_race fetch 函数异常时使用 WARNING 而非 ERROR"""

    @patch('quantia.core.stockfetch.scr.stock_chip_race_open')
    def test_chip_race_open_logs_warning_not_error(self, mock_open):
        """chip_race_open 异常应输出 WARNING，不应是 ERROR"""
        import quantia.core.stockfetch as stf
        mock_open.side_effect = RuntimeError("test error")
        with self.assertLogs('root', level='WARNING') as cm:
            result = stf.fetch_stock_chip_race_open(
                __import__('datetime').date(2026, 3, 11)
            )
        self.assertIsNone(result)
        # 确保输出的是 WARNING 级别
        self.assertTrue(any('WARNING' in msg for msg in cm.output))
        # 确保不包含 ERROR 级别
        self.assertFalse(any('ERROR' in msg for msg in cm.output))

    @patch('quantia.core.stockfetch.scr.stock_chip_race_end')
    def test_chip_race_end_logs_warning_not_error(self, mock_end):
        """chip_race_end 异常应输出 WARNING，不应是 ERROR"""
        import quantia.core.stockfetch as stf
        mock_end.side_effect = RuntimeError("test error")
        with self.assertLogs('root', level='WARNING') as cm:
            result = stf.fetch_stock_chip_race_end(
                __import__('datetime').date(2026, 3, 11)
            )
        self.assertIsNone(result)
        self.assertTrue(any('WARNING' in msg for msg in cm.output))
        self.assertFalse(any('ERROR' in msg for msg in cm.output))


# ══════════════════════════════════════════════
# 4. update_all_caches — KeyboardInterrupt 处理
# ══════════════════════════════════════════════
class TestUpdateAllCachesKeyboardInterrupt(unittest.TestCase):
    """验证 update_all_caches 捕获 KeyboardInterrupt 不传播异常"""

    @patch('quantia.core.stockfetch.stock_hist_cache_incremental')
    @patch('quantia.core.stockfetch._read_cache_meta')
    @patch('quantia.core.stockfetch.time.sleep')
    @patch('quantia.core.stockfetch.gc.collect')
    def test_keyboard_interrupt_does_not_propagate(self, mock_gc, mock_sleep,
                                                    mock_meta, mock_cache):
        """Ctrl+C 不应传播为未捕获异常"""
        import quantia.core.stockfetch as stf
        # 模拟第一次缓存检查触发 KeyboardInterrupt
        mock_meta.return_value = None  # 缓存不是最新 → 需要API请求
        mock_cache.side_effect = KeyboardInterrupt()
        stocks = [('2026-03-12', '000001'), ('2026-03-12', '000002')]
        # 不应抛出异常
        try:
            result = stf.update_all_caches(stocks, '20160312', '20260312', workers=1)
        except KeyboardInterrupt:
            self.fail("KeyboardInterrupt 不应传播出 update_all_caches")

    @patch('quantia.core.stockfetch.stock_hist_cache_incremental')
    @patch('quantia.core.stockfetch._read_cache_meta')
    @patch('quantia.core.stockfetch.time.sleep')
    @patch('quantia.core.stockfetch.gc.collect')
    def test_normal_completion_returns_counts(self, mock_gc, mock_sleep,
                                              mock_meta, mock_cache):
        """正常完成时返回 (success+skip, fail) 元组"""
        import quantia.core.stockfetch as stf
        mock_meta.return_value = {'last_date': '20260312'}  # 缓存已最新 → skip
        stocks = [('2026-03-12', '000001'), ('2026-03-12', '000002')]
        result = stf.update_all_caches(stocks, '20160312', '20260312', workers=1)
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        success_skip, fail = result
        self.assertEqual(success_skip, 2)  # 2 skipped
        self.assertEqual(fail, 0)

    @patch('quantia.core.stockfetch.stock_hist_cache_incremental')
    @patch('quantia.core.stockfetch._read_cache_meta')
    @patch('quantia.core.stockfetch.time.sleep')
    @patch('quantia.core.stockfetch.gc.collect')
    def test_mixed_success_and_failure(self, mock_gc, mock_sleep,
                                       mock_meta, mock_cache):
        """验证成功/失败/跳过的计数正确性"""
        import quantia.core.stockfetch as stf
        # 奇数 code 缓存已最新(skip)，偶数 code 需要更新
        def meta_side_effect(code, adjust='qfq'):
            if code in ('000001', '000003'):
                return {'last_date': '20260312'}  # skip
            return None  # 需要更新

        mock_meta.side_effect = meta_side_effect
        # cache_incremental: 000002成功, 000004返回None(失败)
        call_count = [0]
        def cache_side_effect(code, start, end, is_cache=True, adjust='qfq'):
            if code == '000002':
                return pd.DataFrame({'date': ['2026-03-12'], 'close': [10.0]})
            return None  # 000004 失败

        mock_cache.side_effect = cache_side_effect
        stocks = [
            ('2026-03-12', '000001'),  # skip
            ('2026-03-12', '000002'),  # success
            ('2026-03-12', '000003'),  # skip
            ('2026-03-12', '000004'),  # fail
        ]
        result = stf.update_all_caches(stocks, '20160312', '20260312', workers=1)
        success_skip, fail = result
        # 2 skipped + 1 success = 3, 1 fail
        self.assertEqual(success_skip, 3)
        self.assertEqual(fail, 1)


# ══════════════════════════════════════════════
# 5. 端到端集成逻辑验证
# ══════════════════════════════════════════════
class TestEndToEndLogic(unittest.TestCase):
    """验证修复后各模块的协作逻辑"""

    @patch('quantia.core.crawling.stock_chip_race.proxys')
    @patch('quantia.core.crawling.stock_chip_race.requests.post')
    def test_chip_race_open_http_error_then_caller_handles_none(self, mock_post, mock_proxys):
        """chip_race_open HTTP 错误 → 返回空 DF → stockfetch 调用方得到 None"""
        import quantia.core.stockfetch as stf
        import datetime
        mock_proxy_inst = MagicMock()
        mock_proxy_inst.get_proxies.return_value = {}
        mock_proxys.return_value = mock_proxy_inst
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_post.return_value = mock_response
        # fetch_stock_chip_race_open 内部调用 scr.stock_chip_race_open
        # 后者返回空 DF → "if data is None or len(data.index) == 0: return None"
        result = stf.fetch_stock_chip_race_open(datetime.date(2026, 3, 11))
        self.assertIsNone(result)

    @patch('quantia.core.stockfetch.shs.stock_zh_a_hist_sina')
    @patch('quantia.core.stockfetch.sht.stock_zh_a_hist_tencent')
    @patch('quantia.core.stockfetch.she.stock_zh_a_hist')
    def test_fetch_from_sources_no_retry_sleep_on_empty(self, mock_em, mock_tc, mock_sina):
        """空数据返回时不应调用 _retry_sleep（即没有无意义的等待）"""
        from quantia.core.stockfetch import _fetch_from_sources
        mock_em.return_value = pd.DataFrame()
        with patch('quantia.core.stockfetch._retry_sleep') as mock_sleep:
            _fetch_from_sources('000001', '20260101', '20260312')
            mock_sleep.assert_not_called()


if __name__ == '__main__':
    unittest.main()
