#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P6 基金精选榜钉钉推送单测：markdown 构建 + 深链 + 幂等/门控。

纯函数（build_fund_pick_markdown / _fund_detail_url / _pick_list_url）不打 DB；
run() 用 mock 打 notification.service 与 DingTalkChannel，不触真实 DB/网络。
"""
import datetime
import os
import unittest
from unittest import mock

from quantia.job import notify_fund_pick_job as job


def _pick(code, name, quality=80.0, tier='定投', rate_1y=12.3,
          mdd=-0.15, lag=0, nav_as_of=None, tscore=None, seven_day_annual=None):
    return {
        'code': code, 'name': name, 'quality_score': quality,
        'timing_tier': tier, 'timing_score': tscore, 'rate_1y': rate_1y,
        'max_drawdown': mdd, 'data_lag_days': lag,
        'nav_as_of': nav_as_of or datetime.date(2026, 7, 8),
        'seven_day_annual': seven_day_annual,
    }


class TestUrls(unittest.TestCase):
    def test_detail_url_with_base_env(self):
        with mock.patch.dict(os.environ, {'QUANTIA_WEB_BASE_URL': 'https://q.example.com'}):
            url = job._fund_detail_url('017730', '华夏基金')
            self.assertTrue(url.startswith('https://q.example.com/fund/rank?code=017730'))
            self.assertIn('name=', url)

    def test_detail_url_strips_quantia_suffix(self):
        with mock.patch.dict(os.environ, {'QUANTIA_WEB_BASE_URL': 'https://q.example.com/quantia'}):
            url = job._fund_detail_url('000300')
            self.assertTrue(url.startswith('https://q.example.com/fund/rank?code=000300'))
            self.assertNotIn('/quantia/fund', url)

    def test_list_url(self):
        with mock.patch.dict(os.environ, {'QUANTIA_WEB_BASE_URL': 'https://q.example.com'}):
            self.assertEqual(job._pick_list_url(), 'https://q.example.com/fund/rank?pick=1')

    def test_base_fallback_no_env(self):
        env = dict(os.environ)
        env.pop('QUANTIA_WEB_BASE_URL', None)
        with mock.patch.dict(os.environ, env, clear=True):
            base = job._base_url()
            self.assertTrue(base.startswith('http://'))
            self.assertIn(':9988', base)


class TestBuildMarkdown(unittest.TestCase):
    def _buckets(self):
        return [
            {'fund_type': '股票型', 'timing_applicable': True,
             'picks': [_pick('017730', '华夏A', 82, '低吸', tscore=78),
                       _pick('018230', '易方达B', 80, '定投', tscore=61),
                       _pick('016721', '广发C', 78, '观望', tscore=42)]},
            {'fund_type': '货币型', 'timing_applicable': False,
             'picks': [_pick('000198', '天弘余额宝', 75, None, rate_1y=2.1)]},
        ]

    def test_title_and_date(self):
        title, md = job.build_fund_pick_markdown(
            datetime.date(2026, 7, 9), self._buckets(), base='https://q.example.com')
        self.assertIn('每日基金精选榜 2026-07-09', title)
        self.assertIn('## 📈 每日基金精选榜 2026-07-09', md)

    def test_top3_and_links(self):
        _, md = job.build_fund_pick_markdown(
            datetime.date(2026, 7, 9), self._buckets(), base='https://q.example.com')
        self.assertIn('**股票型** · Top3', md)
        self.assertIn('[017730 华夏A](https://q.example.com/fund/rank?code=017730', md)
        self.assertIn('质量82', md)
        # 徽章含择时分数（对齐原型「低吸78」）
        self.assertIn('🟢低吸78', md)
        self.assertIn('🟠定投61', md)

    def test_null_tier_shows_placeholder(self):
        buckets = [{'fund_type': '债券型', 'timing_applicable': True,
                    'picks': [_pick('016699', '某短债', 88, None, lag=37)]}]
        _, md = job.build_fund_pick_markdown(
            datetime.date(2026, 7, 9), buckets, base='https://q.example.com')
        self.assertIn('择时暂无', md)
        self.assertIn('净值滞后37天', md)

    def test_name_bracket_escaped(self):
        buckets = [{'fund_type': '股票型', 'timing_applicable': True,
                    'picks': [_pick('017730', '华夏[A]份额', 82, '低吸', tscore=78)]}]
        _, md = job.build_fund_pick_markdown(
            datetime.date(2026, 7, 9), buckets, base='https://q.example.com')
        # 链接显示文本里的方括号被转义，避免破坏 markdown 结构
        self.assertIn('华夏【A】份额', md)
        self.assertNotIn('华夏[A]份额', md)

    def test_money_bucket_seven_day_annual(self):
        buckets = [{'fund_type': '货币型', 'timing_applicable': False,
                    'picks': [_pick('000198', '天弘余额宝', 75, None,
                                    rate_1y=2.1, seven_day_annual=1.83)]}]
        _, md = job.build_fund_pick_markdown(
            datetime.date(2026, 7, 9), buckets, base='https://q.example.com')
        self.assertIn('七日年化1.83%', md)
        self.assertNotIn('近1年', md)

    def test_money_bucket_no_timing_badge(self):
        _, md = job.build_fund_pick_markdown(
            datetime.date(2026, 7, 9), self._buckets(), base='https://q.example.com')
        # 货币型行不得出现择时档位徽章文字
        money_line = [l for l in md.splitlines() if '000198' in l][0]
        for tier in ('低吸', '定投', '观望', '高估勿追'):
            self.assertNotIn(tier, money_line)
        self.assertIn('近1年2.10%', money_line)

    def test_lag_flag_shown(self):
        buckets = [{'fund_type': 'QDII', 'timing_applicable': True,
                    'picks': [_pick('006479', '广发全球', 70, '定投', lag=6)]}]
        _, md = job.build_fund_pick_markdown(
            datetime.date(2026, 7, 9), buckets, base='https://q.example.com')
        self.assertIn('净值滞后6天', md)

    def test_disclaimer_and_list_link(self):
        _, md = job.build_fund_pick_markdown(
            datetime.date(2026, 7, 9), self._buckets(), base='https://q.example.com')
        self.assertIn('查看完整每类 Top10 榜单', md)
        self.assertIn('https://q.example.com/fund/rank?pick=1', md)
        self.assertIn('历史业绩不代表未来', md)

    def test_empty_bucket_skipped(self):
        buckets = [{'fund_type': '债券型', 'timing_applicable': True, 'picks': []}]
        _, md = job.build_fund_pick_markdown(
            datetime.date(2026, 7, 9), buckets, base='https://q.example.com')
        self.assertNotIn('**债券型**', md)


class TestDedupeKey(unittest.TestCase):
    def test_stable_and_date_scoped(self):
        k1 = job._dedupe_key('2026-07-09')
        k2 = job._dedupe_key('2026-07-09')
        k3 = job._dedupe_key('2026-07-10')
        self.assertEqual(k1, k2)
        self.assertNotEqual(k1, k3)
        self.assertEqual(len(k1), 64)


class TestRun(unittest.TestCase):
    _buckets = [{'fund_type': '股票型', 'timing_applicable': True,
                 'picks': [_pick('017730', '华夏A', 82, '低吸')]}]

    def test_no_data_returns_no_data(self):
        with mock.patch.object(job, 'read_latest_picks', return_value=(None, [])), \
                mock.patch.object(job, 'record_task_start', return_value=None), \
                mock.patch.object(job, 'record_task_end'):
            res = job.run()
            self.assertFalse(res['sent'])
            self.assertEqual(res['reason'], 'no_data')

    def test_duplicate_idempotent_skip(self):
        with mock.patch.object(job, 'read_latest_picks',
                               return_value=(datetime.date(2026, 7, 9), self._buckets)), \
                mock.patch.object(job, 'record_task_start', return_value=None), \
                mock.patch.object(job, 'record_task_end'):
            from quantia.notification import service as svc
            with mock.patch.object(svc, 'ensure_notification_tables'), \
                    mock.patch.object(svc, '_load_config',
                                      return_value={'enabled': True, 'webhook': 'http://x'}), \
                    mock.patch.object(svc, '_insert_event', return_value=None) as ins, \
                    mock.patch.object(svc, '_send_payload_for_event') as send:
                res = job.run()
                self.assertFalse(res['sent'])
                self.assertEqual(res['reason'], 'duplicate')
                ins.assert_called_once()
                send.assert_not_called()

    def test_disabled_records_skipped_no_send(self):
        with mock.patch.object(job, 'read_latest_picks',
                               return_value=(datetime.date(2026, 7, 9), self._buckets)), \
                mock.patch.object(job, 'record_task_start', return_value=None), \
                mock.patch.object(job, 'record_task_end'):
            from quantia.notification import service as svc
            with mock.patch.object(svc, 'ensure_notification_tables'), \
                    mock.patch.object(svc, '_load_config',
                                      return_value={'enabled': False, 'webhook': ''}), \
                    mock.patch.object(svc, '_insert_event', return_value=123) as ins, \
                    mock.patch.object(svc, '_send_payload_for_event') as send:
                res = job.run()
                self.assertFalse(res['sent'])
                self.assertEqual(res['reason'], 'disabled')
                ins.assert_called_once()
                send.assert_not_called()
                # 入库事件状态应标 skipped
                self.assertEqual(ins.call_args[0][0]['status'], 'skipped')

    def test_enabled_sends(self):
        with mock.patch.object(job, 'read_latest_picks',
                               return_value=(datetime.date(2026, 7, 9), self._buckets)), \
                mock.patch.object(job, 'record_task_start', return_value=None), \
                mock.patch.object(job, 'record_task_end'):
            from quantia.notification import service as svc
            with mock.patch.object(svc, 'ensure_notification_tables'), \
                    mock.patch.object(svc, '_load_config',
                                      return_value={'enabled': True, 'webhook': 'http://x'}), \
                    mock.patch.object(svc, '_insert_event', return_value=456), \
                    mock.patch.object(svc, '_send_payload_for_event', return_value=True) as send:
                res = job.run()
                self.assertTrue(res['sent'])
                self.assertEqual(res['event_id'], 456)
                send.assert_called_once()
                self.assertEqual(send.call_args[0][2], 'fund_daily_pick')

    def test_dry_run_no_side_effects(self):
        with mock.patch.object(job, 'read_latest_picks',
                               return_value=(datetime.date(2026, 7, 9), self._buckets)), \
                mock.patch.object(job, 'record_task_start', return_value=None), \
                mock.patch.object(job, 'record_task_end'):
            from quantia.notification import service as svc
            with mock.patch.object(svc, '_insert_event') as ins, \
                    mock.patch.object(svc, '_send_payload_for_event') as send:
                res = job.run(dry_run=True)
                self.assertFalse(res['sent'])
                self.assertEqual(res['reason'], 'dry_run')
                self.assertIn('每日基金精选榜', res['markdown'])
                ins.assert_not_called()
                send.assert_not_called()


if __name__ == '__main__':
    unittest.main()
