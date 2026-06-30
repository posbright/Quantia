#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""F14 基金 AI 按需分析 单元测试（纯函数 + handler mock：DB / LLM 全部打桩）。

禁真实网络/DB/LLM：build_user_message / _extract_sources 直接断言；
handler 用 mock.patch 打 gather_ctx / 缓存 / run_agent / feature_switch。
"""
import json
import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tornado.testing import AsyncHTTPTestCase
from tornado.web import Application

import quantia.web.fundAiAnalysisHandler as fah


def _sample_ctx():
    return {
        'code': '001000', 'name': '测试成长', 'fund_type': '股票型',
        'data_date': '2026-05-29',
        'rank': {'name': '测试成长', 'fund_type': '股票型', 'nav_date': '2026-05-29',
                 'rate_1y': 25.0, 'rate_3y': 60.0},
        'score': {'score': 88.0, 'sharpe': 1.6, 'max_drawdown': -0.18,
                  'rate_3y': 60.0, 'rate_5y': 110.0, 'excess_1y': 6.0,
                  'main_industry': '半导体', 'rank_in_type': 1},
        'profile': {'fund_type_detail': '股票型-普通', 'scale_yi': 12.0,
                    'setup_date': '2018-01-01', 'company': '某基金公司',
                    'manager': '张三', 'rating': '5星'},
        'holdings': [{'name': '甲股', 'industry': '半导体', 'hold_ratio': 9.0},
                     {'name': '乙股', 'industry': '电子', 'hold_ratio': 7.0}],
        'peer_percentiles': {'sharpe': 85.0, 'drawdown': 70.0},
    }


def _sample_composite():
    return fah.cah.build_composite_analysis(_sample_ctx())


class _FakeResult:
    def __init__(self, content, tool_calls):
        self.content = content
        self.tool_calls = tool_calls
        self.model = 'deepseek-chat'
        self.provider = 'deepseek'
        self.rounds = 2
        self.prompt_tokens = 100
        self.completion_tokens = 200
        self.total_tokens = 300
        self.finish_reason = 'stop'


# ──────────────────────────────────────────────────────────
# 纯函数
# ──────────────────────────────────────────────────────────
class TestBuildUserMessage:
    def test_includes_numbers_and_instructions(self):
        ctx = _sample_ctx()
        msg = fah.build_user_message(ctx, _sample_composite())
        assert '001000' in msg
        assert '测试成长' in msg
        assert '张三' in msg          # 经理
        assert '1.6' in msg           # 夏普照抄
        assert 'web_search' in msg    # 要求检索
        assert '甲股' in msg          # 重仓股名
        # 禁止 prompt 自带买卖结论
        for forbidden in ('买入', '卖出', '加仓', '减仓'):
            assert forbidden not in msg

    def test_handles_missing_fields(self):
        ctx = {'code': '002000', 'name': None, 'fund_type': None,
               'data_date': None, 'rank': {}, 'score': {}, 'profile': {},
               'holdings': [], 'peer_percentiles': {}}
        comp = fah.cah.build_composite_analysis(ctx)
        msg = fah.build_user_message(ctx, comp)
        assert '002000' in msg
        assert '暂无' in msg          # 缺失值兜底


class TestExtractSources:
    def test_extracts_and_dedupes(self):
        tool_calls = [
            {'name': 'web_search', 'ok': True, 'result': {'results': [
                {'title': 'A', 'url': 'http://x/1'},
                {'title': 'B', 'url': 'http://x/2'},
                {'title': 'A-dup', 'url': 'http://x/1'},  # 重复 url 去重
            ]}},
            {'name': 'other_tool', 'ok': True, 'result': {'results': [
                {'title': 'C', 'url': 'http://x/3'}]}},  # 非 web_search 忽略
            {'name': 'web_search', 'ok': False, 'error': 'boom'},  # 失败忽略
        ]
        out = fah._extract_sources(tool_calls)
        urls = [s['url'] for s in out]
        assert urls == ['http://x/1', 'http://x/2']

    def test_empty(self):
        assert fah._extract_sources(None) == []
        assert fah._extract_sources([]) == []


# ──────────────────────────────────────────────────────────
# Handler 端到端（mock gather_ctx / 缓存 / LLM）
# ──────────────────────────────────────────────────────────
class TestFundAiHandler(AsyncHTTPTestCase):
    def get_app(self):
        return Application([(r'/api/fund/ai_analysis', fah.FundAiAnalysisHandler)])

    def test_post_runs_llm_and_caches(self):
        ctx = _sample_ctx()
        comp = _sample_composite()
        fake = _FakeResult('## 一、业绩与风险概览\n夏普1.6。', [
            {'name': 'web_search', 'ok': True,
             'result': {'results': [{'title': '资讯A', 'url': 'http://n/1'}]}}])
        with mock.patch.object(fah, 'gather_ctx', return_value=(ctx, comp, {})), \
             mock.patch.object(fah, '_load_cache', return_value=None), \
             mock.patch.object(fah, '_save_cache') as save_mock, \
             mock.patch('quantia.lib.ai.prompt_loader.load', return_value='SYS'), \
             mock.patch('quantia.lib.ai.run_agent', return_value=fake), \
             mock.patch('quantia.lib.ai.feature_switch.is_feature_enabled',
                        return_value=True):
            resp = self.fetch('/api/fund/ai_analysis', method='POST',
                              body=json.dumps({'code': '001000'}))
        assert resp.code == 200
        data = json.loads(resp.body)
        assert data['ai_available'] is True
        assert data['cached'] is False
        assert '夏普1.6' in data['content']
        assert data['sources'][0]['url'] == 'http://n/1'
        assert data['composite']['code'] == '001000'
        save_mock.assert_called_once()

    def test_post_cache_hit_skips_llm(self):
        ctx = _sample_ctx()
        comp = _sample_composite()
        cached = {'content': '缓存内容', 'sources': [{'title': 't', 'url': 'u'}],
                  'model': 'm', 'created_at': None}
        with mock.patch.object(fah, 'gather_ctx', return_value=(ctx, comp, {})), \
             mock.patch.object(fah, '_load_cache', return_value=cached), \
             mock.patch('quantia.lib.ai.run_agent') as run_mock:
            resp = self.fetch('/api/fund/ai_analysis', method='POST',
                              body=json.dumps({'code': '001000'}))
        assert resp.code == 200
        data = json.loads(resp.body)
        assert data['cached'] is True
        assert data['content'] == '缓存内容'
        run_mock.assert_not_called()

    def test_post_llm_failure_falls_back_to_rules(self):
        ctx = _sample_ctx()
        comp = _sample_composite()
        with mock.patch.object(fah, 'gather_ctx', return_value=(ctx, comp, {})), \
             mock.patch.object(fah, '_load_cache', return_value=None), \
             mock.patch('quantia.lib.ai.prompt_loader.load', return_value='SYS'), \
             mock.patch('quantia.lib.ai.run_agent',
                        side_effect=RuntimeError('provider down')), \
             mock.patch('quantia.lib.ai.feature_switch.is_feature_enabled',
                        return_value=True):
            resp = self.fetch('/api/fund/ai_analysis', method='POST',
                              body=json.dumps({'code': '001000'}))
        assert resp.code == 200
        data = json.loads(resp.body)
        assert data['ai_available'] is False
        assert data['composite']['code'] == '001000'
        assert 'note' in data

    def test_post_feature_disabled_returns_fallback(self):
        ctx = _sample_ctx()
        comp = _sample_composite()
        with mock.patch.object(fah, 'gather_ctx', return_value=(ctx, comp, {})), \
             mock.patch.object(fah, '_load_cache', return_value=None), \
             mock.patch('quantia.lib.ai.feature_switch.is_feature_enabled',
                        return_value=False), \
             mock.patch('quantia.lib.ai.run_agent') as run_mock:
            resp = self.fetch('/api/fund/ai_analysis', method='POST',
                              body=json.dumps({'code': '001000'}))
        assert resp.code == 200
        data = json.loads(resp.body)
        assert data['ai_available'] is False
        run_mock.assert_not_called()

    def test_post_missing_code(self):
        resp = self.fetch('/api/fund/ai_analysis', method='POST', body='{}')
        assert resp.code == 400

    def test_post_fund_not_found(self):
        with mock.patch.object(fah, 'gather_ctx', return_value=(None, None, {})):
            resp = self.fetch('/api/fund/ai_analysis', method='POST',
                              body=json.dumps({'code': 'zzz'}))
        assert resp.code == 404

    def test_get_cache_only_hit(self):
        ctx = _sample_ctx()
        comp = _sample_composite()
        cached = {'content': '历史缓存', 'sources': [], 'model': 'm',
                  'created_at': None}
        with mock.patch.object(fah, 'gather_ctx', return_value=(ctx, comp, {})), \
             mock.patch.object(fah, '_load_cache', return_value=cached):
            resp = self.fetch('/api/fund/ai_analysis?code=001000')
        assert resp.code == 200
        data = json.loads(resp.body)
        assert data['cached'] is True
        assert data['ai_available'] is True
        assert data['content'] == '历史缓存'

    def test_get_cache_only_miss(self):
        ctx = _sample_ctx()
        comp = _sample_composite()
        with mock.patch.object(fah, 'gather_ctx', return_value=(ctx, comp, {})), \
             mock.patch.object(fah, '_load_cache', return_value=None):
            resp = self.fetch('/api/fund/ai_analysis?code=001000')
        assert resp.code == 200
        data = json.loads(resp.body)
        assert data['cached'] is False
        assert data['ai_available'] is False
        assert data['composite']['code'] == '001000'
