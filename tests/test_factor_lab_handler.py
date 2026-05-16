#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""因子实验室 — factorLabHandler 单元测试。"""

import json
import os
import sys
from unittest import mock

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tornado.testing import AsyncHTTPTestCase
from tornado.web import Application

import quantia.web.factorLabHandler as flh
import quantia.web.verifyOptimizeHandler as voh


# ── 测试数据工厂 ──────────────────────────────────────────────────────

def _reset_strategy_cache():
    voh._STRATEGY_MAP = None


def _make_strategy_df(n=60, seed=42):
    np.random.seed(seed)
    dates = pd.date_range('2025-01-01', periods=n, freq='B')
    return pd.DataFrame({
        'date': dates,
        'code': [f'60000{i % 9}' for i in range(n)],
        'rate': np.random.normal(1.0, 3.0, n),
    })


def _make_indicator_df(n=60, seed=42):
    np.random.seed(seed)
    dates = pd.date_range('2025-01-01', periods=n, freq='B')
    return pd.DataFrame({
        'date': dates,
        'code': [f'60000{i % 9}' for i in range(n)],
        'rsi_6': np.random.uniform(10, 90, n),
        'macd': np.random.normal(0, 1, n),
    })


def _make_selection_df(n=60, seed=42):
    np.random.seed(seed)
    dates = pd.date_range('2025-01-01', periods=n, freq='B')
    return pd.DataFrame({
        'date': dates,
        'code': [f'60000{i % 9}' for i in range(n)],
        'pe9': np.random.uniform(-5, 60, n),
        'roe_weight': np.random.uniform(-5, 30, n),
    })


def _make_fund_flow_df(n=60, seed=42):
    np.random.seed(seed)
    dates = pd.date_range('2025-01-01', periods=n, freq='B')
    return pd.DataFrame({
        'date': dates,
        'code': [f'60000{i % 9}' for i in range(n)],
        'fund_amount': np.random.normal(0, 1e8, n).astype(int),
    })


def _make_app():
    return Application([
        (r'/api/factor_lab/factors', flh.FactorCatalogHandler),
        (r'/api/factor_lab/run', flh.FactorLabRunHandler),
        (r'/api/factor_lab/factor_impact', flh.FactorImpactHandler),
        (r'/api/factor_lab/presets', flh.FactorPresetsHandler),
    ])


# ── FactorCatalogHandler 测试 ─────────────────────────────────────────

class TestFactorCatalogHandler(AsyncHTTPTestCase):
    def setUp(self):
        super().setUp()
        _reset_strategy_cache()

    def get_app(self):
        return _make_app()

    def test_get_factor_catalog(self):
        resp = self.fetch('/api/factor_lab/factors')
        self.assertEqual(resp.code, 200)
        data = json.loads(resp.body)
        cats = data['categories']
        self.assertEqual(len(cats), 4)
        cat_keys = [c['key'] for c in cats]
        self.assertIn('tech_signal', cat_keys)
        self.assertIn('tech_indicator', cat_keys)
        self.assertIn('fundamental', cat_keys)
        self.assertIn('fund_flow', cat_keys)

    def test_catalog_has_strategy_factors(self):
        resp = self.fetch('/api/factor_lab/factors')
        data = json.loads(resp.body)
        tech_signal = next(c for c in data['categories'] if c['key'] == 'tech_signal')
        ids = [f['id'] for f in tech_signal['factors']]
        self.assertIn('keep_increasing', ids)
        self.assertIn('breakout_confirm', ids)
        self.assertIn('gpt_value', ids)

    def test_catalog_has_indicator_factors(self):
        resp = self.fetch('/api/factor_lab/factors')
        data = json.loads(resp.body)
        tech_ind = next(c for c in data['categories'] if c['key'] == 'tech_indicator')
        ids = [f['id'] for f in tech_ind['factors']]
        self.assertIn('rsi_6', ids)
        self.assertIn('macd', ids)


# ── FactorPresetsHandler 测试 ─────────────────────────────────────────

class TestFactorPresetsHandler(AsyncHTTPTestCase):
    def setUp(self):
        super().setUp()
        _reset_strategy_cache()

    def get_app(self):
        return _make_app()

    def test_get_presets(self):
        resp = self.fetch('/api/factor_lab/presets')
        self.assertEqual(resp.code, 200)
        data = json.loads(resp.body)
        presets = data['presets']
        self.assertGreaterEqual(len(presets), 6)
        names = [p['name'] for p in presets]
        self.assertIn('空白', names)
        self.assertIn('技术+基本面(推荐)', names)
        self.assertIn('价值投资', names)

    def test_preset_factors_have_meta(self):
        resp = self.fetch('/api/factor_lab/presets')
        data = json.loads(resp.body)
        tech_fund = next(p for p in data['presets'] if p['id'] == 'tech_fund')
        self.assertGreater(len(tech_fund['factors']), 0)
        for f in tech_fund['factors']:
            self.assertIn('name', f)
            self.assertIn('category', f)


# ── FactorLabRunHandler 测试 ──────────────────────────────────────────

class TestFactorLabRunHandler(AsyncHTTPTestCase):
    def setUp(self):
        super().setUp()
        _reset_strategy_cache()

    def get_app(self):
        return _make_app()

    def _post(self, body):
        return self.fetch('/api/factor_lab/run', method='POST',
                          body=json.dumps(body),
                          headers={'Content-Type': 'application/json'})

    def test_empty_factors_error(self):
        resp = self._post({'factors': [], 'start_date': '2025-01-01',
                           'end_date': '2025-03-31', 'holding_days': 10})
        self.assertEqual(resp.code, 400)
        self.assertIn('至少需要', json.loads(resp.body)['error'])

    def test_too_many_factors_error(self):
        factors = [{'id': f'fake_{i}', 'weight': 5, 'enabled': True} for i in range(16)]
        resp = self._post({'factors': factors, 'start_date': '2025-01-01',
                           'end_date': '2025-03-31', 'holding_days': 10})
        self.assertEqual(resp.code, 400)
        self.assertIn('15', json.loads(resp.body)['error'])

    def test_no_signal_factor_error(self):
        resp = self._post({
            'factors': [{'id': 'rsi_6', 'weight': 50, 'enabled': True,
                         'operator': '<', 'value': 70}],
            'fusion_mode': 'and',
            'start_date': '2025-01-01', 'end_date': '2025-03-31',
            'holding_days': 10,
        })
        self.assertEqual(resp.code, 400)
        self.assertIn('策略信号因子', json.loads(resp.body)['error'])

    def test_missing_dates_error(self):
        resp = self._post({
            'factors': [{'id': 'keep_increasing', 'weight': 100, 'enabled': True}],
            'fusion_mode': 'and',
            'holding_days': 10,
        })
        self.assertEqual(resp.code, 400)
        self.assertIn('start_date', json.loads(resp.body)['error'])

    def test_invalid_fusion_mode(self):
        resp = self._post({
            'factors': [{'id': 'keep_increasing', 'weight': 100, 'enabled': True}],
            'fusion_mode': 'magic',
            'start_date': '2025-01-01', 'end_date': '2025-03-31',
            'holding_days': 10,
        })
        self.assertEqual(resp.code, 400)
        self.assertIn('fusion_mode', json.loads(resp.body)['error'])

    @mock.patch('quantia.lib.database.checkTableIsExist', return_value=True)
    @mock.patch('pandas.read_sql')
    def test_single_strategy_factor_run(self, mock_sql, mock_exists):
        mock_sql.return_value = _make_strategy_df()
        resp = self._post({
            'factors': [{'id': 'keep_increasing', 'weight': 100, 'enabled': True}],
            'fusion_mode': 'and',
            'start_date': '2025-01-01', 'end_date': '2025-03-31',
            'holding_days': 10,
        })
        self.assertEqual(resp.code, 200)
        data = json.loads(resp.body)
        self.assertIn('kpi', data)
        self.assertIn('baseline', data)
        self.assertIn('daily_series', data)
        self.assertIn('factor_contributions', data)
        kpi = data['kpi']
        self.assertIsNotNone(kpi['sharpe'])
        self.assertIsNotNone(kpi['win_rate'])
        self.assertIsNotNone(kpi['avg_return'])
        self.assertGreater(kpi['signal_count'], 0)

    @mock.patch('quantia.lib.database.checkTableIsExist', return_value=True)
    @mock.patch('pandas.read_sql')
    def test_multi_strategy_and_mode(self, mock_sql, mock_exists):
        mock_sql.return_value = _make_strategy_df()
        resp = self._post({
            'factors': [
                {'id': 'keep_increasing', 'weight': 50, 'enabled': True},
                {'id': 'breakout_confirm', 'weight': 50, 'enabled': True},
            ],
            'fusion_mode': 'and',
            'start_date': '2025-01-01', 'end_date': '2025-03-31',
            'holding_days': 5,
        })
        self.assertEqual(resp.code, 200)
        data = json.loads(resp.body)
        self.assertIn('kpi', data)
        self.assertEqual(data['fusion_mode'], 'and')

    @mock.patch('quantia.lib.database.checkTableIsExist', return_value=True)
    @mock.patch('pandas.read_sql')
    def test_strategy_with_indicator_filter(self, mock_sql, mock_exists):
        strat_df = _make_strategy_df()
        ind_df = _make_indicator_df()

        def side_effect(sql, con, params=None):
            if 'rsi_6' in sql:
                return ind_df
            return strat_df

        mock_sql.side_effect = side_effect

        resp = self._post({
            'factors': [
                {'id': 'keep_increasing', 'weight': 60, 'enabled': True},
                {'id': 'rsi_6', 'weight': 40, 'enabled': True,
                 'operator': '<', 'value': 70},
            ],
            'fusion_mode': 'score',
            'start_date': '2025-01-01', 'end_date': '2025-03-31',
            'holding_days': 10,
        })
        self.assertEqual(resp.code, 200)
        data = json.loads(resp.body)
        self.assertIn('kpi', data)
        self.assertIn('baseline', data)
        # 过滤后信号应 <= 基线
        self.assertLessEqual(
            data['kpi']['signal_count'], data['baseline']['signal_count'])

    @mock.patch('quantia.lib.database.checkTableIsExist', return_value=True)
    @mock.patch('pandas.read_sql')
    def test_between_operator(self, mock_sql, mock_exists):
        strat_df = _make_strategy_df()
        sel_df = _make_selection_df()

        def side_effect(sql, con, params=None):
            if 'pe9' in sql:
                return sel_df
            return strat_df

        mock_sql.side_effect = side_effect

        resp = self._post({
            'factors': [
                {'id': 'keep_increasing', 'weight': 70, 'enabled': True},
                {'id': 'pe9', 'weight': 30, 'enabled': True,
                 'operator': 'between', 'value': [0, 30]},
            ],
            'fusion_mode': 'and',
            'start_date': '2025-01-01', 'end_date': '2025-03-31',
            'holding_days': 10,
        })
        self.assertEqual(resp.code, 200)
        data = json.loads(resp.body)
        self.assertIn('kpi', data)

    @mock.patch('quantia.lib.database.checkTableIsExist', return_value=True)
    @mock.patch('pandas.read_sql')
    def test_disabled_factors_ignored(self, mock_sql, mock_exists):
        mock_sql.return_value = _make_strategy_df()
        resp = self._post({
            'factors': [
                {'id': 'keep_increasing', 'weight': 100, 'enabled': True},
                {'id': 'rsi_6', 'weight': 50, 'enabled': False,
                 'operator': '<', 'value': 30},
            ],
            'fusion_mode': 'and',
            'start_date': '2025-01-01', 'end_date': '2025-03-31',
            'holding_days': 10,
        })
        self.assertEqual(resp.code, 200)
        data = json.loads(resp.body)
        # 只有 1 个活跃因子，不应有指标 JOIN
        self.assertGreater(data['kpi']['signal_count'], 0)

    @mock.patch('quantia.lib.database.checkTableIsExist', return_value=True)
    @mock.patch('pandas.read_sql')
    def test_daily_series_in_result(self, mock_sql, mock_exists):
        mock_sql.return_value = _make_strategy_df()
        resp = self._post({
            'factors': [{'id': 'keep_increasing', 'weight': 100, 'enabled': True}],
            'fusion_mode': 'and',
            'start_date': '2025-01-01', 'end_date': '2025-03-31',
            'holding_days': 10,
        })
        self.assertEqual(resp.code, 200)
        data = json.loads(resp.body)
        series = data['daily_series']
        self.assertIsInstance(series, list)
        if len(series) > 0:
            self.assertIn('date', series[0])
            self.assertIn('cumulative', series[0])
            self.assertIn('drawdown', series[0])

    @mock.patch('quantia.lib.database.checkTableIsExist', return_value=True)
    @mock.patch('pandas.read_sql')
    def test_factor_contributions_in_result(self, mock_sql, mock_exists):
        mock_sql.return_value = _make_strategy_df()
        resp = self._post({
            'factors': [
                {'id': 'keep_increasing', 'weight': 50, 'enabled': True},
                {'id': 'breakout_confirm', 'weight': 50, 'enabled': True},
            ],
            'fusion_mode': 'score',
            'start_date': '2025-01-01', 'end_date': '2025-03-31',
            'holding_days': 10,
        })
        self.assertEqual(resp.code, 200)
        data = json.loads(resp.body)
        contribs = data['factor_contributions']
        self.assertIsInstance(contribs, list)
        self.assertEqual(len(contribs), 2)
        for c in contribs:
            self.assertIn('id', c)
            self.assertIn('name', c)
            self.assertIn('impact', c)

    @mock.patch('quantia.lib.database.checkTableIsExist', return_value=True)
    @mock.patch('pandas.read_sql')
    def test_vote_mode(self, mock_sql, mock_exists):
        mock_sql.return_value = _make_strategy_df()
        resp = self._post({
            'factors': [
                {'id': 'keep_increasing', 'weight': 30, 'enabled': True},
                {'id': 'breakout_confirm', 'weight': 30, 'enabled': True},
                {'id': 'trend_pullback', 'weight': 40, 'enabled': True},
            ],
            'fusion_mode': 'vote',
            'vote_threshold': 2,
            'start_date': '2025-01-01', 'end_date': '2025-03-31',
            'holding_days': 10,
        })
        self.assertEqual(resp.code, 200)
        data = json.loads(resp.body)
        self.assertEqual(data['fusion_mode'], 'vote')

    @mock.patch('quantia.lib.database.checkTableIsExist', return_value=True)
    @mock.patch('pandas.read_sql')
    def test_empty_data_returns_zero_kpi(self, mock_sql, mock_exists):
        mock_sql.return_value = pd.DataFrame(columns=['date', 'code', 'rate'])
        resp = self._post({
            'factors': [{'id': 'keep_increasing', 'weight': 100, 'enabled': True}],
            'fusion_mode': 'and',
            'start_date': '2025-01-01', 'end_date': '2025-03-31',
            'holding_days': 10,
        })
        self.assertEqual(resp.code, 200)
        data = json.loads(resp.body)
        self.assertEqual(data['kpi']['signal_count'], 0)
        self.assertTrue(data['signal_sparse_warning'])

    @mock.patch('quantia.lib.database.checkTableIsExist', return_value=True)
    @mock.patch('pandas.read_sql')
    def test_date_range_limit(self, mock_sql, mock_exists):
        mock_sql.return_value = _make_strategy_df()
        resp = self._post({
            'factors': [{'id': 'keep_increasing', 'weight': 100, 'enabled': True}],
            'fusion_mode': 'and',
            'start_date': '2023-01-01', 'end_date': '2025-03-31',
            'holding_days': 10,
        })
        self.assertEqual(resp.code, 400)
        self.assertIn('366', json.loads(resp.body)['error'])


# ── 工具函数测试 ──────────────────────────────────────────────────────

class TestUtilFunctions:
    def test_apply_condition_lt(self):
        s = pd.Series([10, 20, 30, 40, 50])
        mask = flh._apply_condition(s, '<', 30)
        assert mask.tolist() == [True, True, False, False, False]

    def test_apply_condition_gte(self):
        s = pd.Series([10, 20, 30, 40, 50])
        mask = flh._apply_condition(s, '>=', 30)
        assert mask.tolist() == [False, False, True, True, True]

    def test_apply_condition_between(self):
        s = pd.Series([10, 20, 30, 40, 50])
        mask = flh._apply_condition(s, 'between', [20, 40])
        assert mask.tolist() == [False, True, True, True, False]

    def test_compute_kpi_empty(self):
        kpi = flh._compute_kpi(np.array([]), 10)
        assert kpi['signal_count'] == 0
        assert kpi['sharpe'] is None

    def test_compute_kpi_valid(self):
        rates = np.array([1.0, 2.0, -0.5, 3.0, -1.0, 0.5, 1.5, 2.0, -0.3, 0.8])
        kpi = flh._compute_kpi(rates, 10, total_dates=5)
        assert kpi['signal_count'] == 10
        assert kpi['win_rate'] is not None
        assert kpi['sharpe'] is not None
        assert kpi['daily_signal_avg'] == 2.0

    def test_compute_daily_series(self):
        idx = pd.to_datetime(['2025-01-02', '2025-01-03', '2025-01-06'])
        rates = pd.Series([1.0, -0.5, 2.0], index=idx)
        series = flh._compute_daily_series(rates)
        assert len(series) == 3
        assert series[0]['date'] == '2025-01-02'
        assert 'cumulative' in series[0]
        assert 'drawdown' in series[0]

    def test_factor_catalog_no_duplicates(self):
        ids = [f['id'] for f in flh.FACTOR_CATALOG]
        assert len(ids) == len(set(ids)), "因子 id 有重复"

    def test_preset_factors_all_valid(self):
        for preset in flh.PRESET_TEMPLATES:
            for pf in preset.get('factors', []):
                assert pf['id'] in flh._FACTOR_MAP, \
                    f"预设 {preset['id']} 引用了未知因子 {pf['id']}"


# ── FactorLabSaveHandler 测试 ─────────────────────────────────────────

def _make_app_v2():
    """含 Phase 7 新路由的测试 Application。"""
    return Application([
        (r'/api/factor_lab/factors', flh.FactorCatalogHandler),
        (r'/api/factor_lab/run', flh.FactorLabRunHandler),
        (r'/api/factor_lab/factor_impact', flh.FactorImpactHandler),
        (r'/api/factor_lab/presets', flh.FactorPresetsHandler),
        (r'/api/factor_lab/save', flh.FactorLabSaveHandler),
        (r'/api/factor_lab/my_configs', flh.FactorLabConfigsHandler),
        (r'/api/factor_lab/configs/(\d+)', flh.FactorLabDeleteConfigHandler),
        (r'/api/factor_lab/export_code', flh.FactorLabExportCodeHandler),
    ])


class TestFactorLabSaveHandler(AsyncHTTPTestCase):
    def setUp(self):
        super().setUp()
        flh._config_table_ready = True  # 跳过建表

    def get_app(self):
        return _make_app_v2()

    def _post(self, body):
        return self.fetch('/api/factor_lab/save', method='POST',
                          body=json.dumps(body),
                          headers={'Content-Type': 'application/json'})

    def test_save_empty_name_error(self):
        resp = self._post({
            'name': '',
            'factors': [{'id': 'keep_increasing', 'weight': 100, 'enabled': True}],
            'fusion_mode': 'and',
        })
        self.assertEqual(resp.code, 400)
        self.assertIn('名称', json.loads(resp.body)['error'])

    def test_save_empty_factors_error(self):
        resp = self._post({
            'name': '测试方案',
            'factors': [],
            'fusion_mode': 'and',
        })
        self.assertEqual(resp.code, 400)
        self.assertIn('因子', json.loads(resp.body)['error'])

    def test_save_invalid_fusion_mode(self):
        resp = self._post({
            'name': '测试方案',
            'factors': [{'id': 'keep_increasing', 'weight': 100, 'enabled': True}],
            'fusion_mode': 'invalid',
        })
        self.assertEqual(resp.code, 400)
        self.assertIn('fusion_mode', json.loads(resp.body)['error'])

    @mock.patch('quantia.lib.database.executeSqlFetch', return_value=[(42,)])
    @mock.patch('quantia.lib.database.executeSql')
    @mock.patch('quantia.lib.database.checkTableIsExist', return_value=True)
    def test_save_new_config_success(self, mock_exists, mock_exec, mock_fetch):
        resp = self._post({
            'name': '我的策略方案',
            'description': '测试描述',
            'factors': [
                {'id': 'keep_increasing', 'weight': 60, 'enabled': True},
                {'id': 'rsi_6', 'weight': 40, 'enabled': True,
                 'operator': '<', 'value': 70},
            ],
            'fusion_mode': 'score',
            'holding_days': 10,
        })
        self.assertEqual(resp.code, 200)
        data = json.loads(resp.body)
        self.assertEqual(data['id'], 42)
        self.assertIn('已保存', data['message'])

    @mock.patch('quantia.lib.database.executeSql')
    @mock.patch('quantia.lib.database.checkTableIsExist', return_value=True)
    def test_save_update_existing(self, mock_exists, mock_exec):
        resp = self._post({
            'id': 7,
            'name': '更新方案',
            'factors': [{'id': 'keep_increasing', 'weight': 100, 'enabled': True}],
            'fusion_mode': 'and',
        })
        self.assertEqual(resp.code, 200)
        data = json.loads(resp.body)
        self.assertEqual(data['id'], 7)
        self.assertIn('已更新', data['message'])

    def test_save_too_many_factors_error(self):
        factors = [{'id': f'x_{i}', 'weight': 5, 'enabled': True} for i in range(16)]
        resp = self._post({
            'name': '大量因子',
            'factors': factors,
            'fusion_mode': 'and',
        })
        self.assertEqual(resp.code, 400)
        self.assertIn('15', json.loads(resp.body)['error'])


# ── FactorLabConfigsHandler 测试 ──────────────────────────────────────

class TestFactorLabConfigsHandler(AsyncHTTPTestCase):
    def setUp(self):
        super().setUp()
        flh._config_table_ready = True

    def get_app(self):
        return _make_app_v2()

    @mock.patch('quantia.lib.database.executeSqlFetch')
    @mock.patch('quantia.lib.database.checkTableIsExist', return_value=True)
    def test_get_configs_list(self, mock_exists, mock_fetch):
        from datetime import datetime
        mock_fetch.return_value = [
            (1, '方案A', '描述', json.dumps([{'id': 'keep_increasing', 'weight': 100, 'enabled': True}]),
             'and', 2, 10, datetime(2025, 5, 1, 10, 0), datetime(2025, 5, 2, 12, 0)),
        ]
        resp = self.fetch('/api/factor_lab/my_configs')
        self.assertEqual(resp.code, 200)
        data = json.loads(resp.body)
        configs = data['configs']
        self.assertEqual(len(configs), 1)
        self.assertEqual(configs[0]['name'], '方案A')
        self.assertEqual(configs[0]['fusion_mode'], 'and')
        self.assertIsInstance(configs[0]['factors'], list)

    @mock.patch('quantia.lib.database.executeSqlFetch', return_value=[])
    @mock.patch('quantia.lib.database.checkTableIsExist', return_value=True)
    def test_get_configs_empty(self, mock_exists, mock_fetch):
        resp = self.fetch('/api/factor_lab/my_configs')
        self.assertEqual(resp.code, 200)
        data = json.loads(resp.body)
        self.assertEqual(data['configs'], [])


# ── FactorLabDeleteConfigHandler 测试 ─────────────────────────────────

class TestFactorLabDeleteConfigHandler(AsyncHTTPTestCase):
    def setUp(self):
        super().setUp()
        flh._config_table_ready = True

    def get_app(self):
        return _make_app_v2()

    @mock.patch('quantia.lib.database.executeSql')
    @mock.patch('quantia.lib.database.checkTableIsExist', return_value=True)
    def test_delete_config_success(self, mock_exists, mock_exec):
        resp = self.fetch('/api/factor_lab/configs/5', method='DELETE')
        self.assertEqual(resp.code, 200)
        data = json.loads(resp.body)
        self.assertEqual(data['id'], 5)
        self.assertIn('已删除', data['message'])


# ── FactorLabExportCodeHandler 测试 ───────────────────────────────────

class TestFactorLabExportCodeHandler(AsyncHTTPTestCase):
    def get_app(self):
        return _make_app_v2()

    def _post(self, body):
        return self.fetch('/api/factor_lab/export_code', method='POST',
                          body=json.dumps(body),
                          headers={'Content-Type': 'application/json'})

    def test_export_empty_factors_error(self):
        resp = self._post({'factors': [], 'fusion_mode': 'and'})
        self.assertEqual(resp.code, 400)
        self.assertIn('因子', json.loads(resp.body)['error'])

    def test_export_single_signal_factor(self):
        resp = self._post({
            'factors': [{'id': 'keep_increasing', 'weight': 100, 'enabled': True}],
            'fusion_mode': 'and',
            'holding_days': 10,
        })
        self.assertEqual(resp.code, 200)
        data = json.loads(resp.body)
        self.assertIn('code', data)
        self.assertIn('filename', data)
        self.assertIn('backtrader', data['code'].lower())
        self.assertIn('FactorLabStrategy', data['code'])
        self.assertIn('keep_increasing', data['code'])

    def test_export_with_filters(self):
        resp = self._post({
            'factors': [
                {'id': 'keep_increasing', 'weight': 50, 'enabled': True},
                {'id': 'rsi_6', 'weight': 30, 'enabled': True, 'operator': '<', 'value': 70},
                {'id': 'pe9', 'weight': 20, 'enabled': True, 'operator': 'between', 'value': [0, 30]},
            ],
            'fusion_mode': 'score',
            'holding_days': 5,
        })
        self.assertEqual(resp.code, 200)
        data = json.loads(resp.body)
        code = data['code']
        self.assertIn('rsi_6', code)
        self.assertIn('pe9', code)
        self.assertIn("'score'", code)
        self.assertIn('5', code)

    def test_export_vote_mode(self):
        resp = self._post({
            'factors': [
                {'id': 'keep_increasing', 'weight': 50, 'enabled': True},
                {'id': 'breakout_confirm', 'weight': 50, 'enabled': True},
            ],
            'fusion_mode': 'vote',
            'vote_threshold': 2,
            'holding_days': 7,
        })
        self.assertEqual(resp.code, 200)
        data = json.loads(resp.body)
        self.assertIn('vote', data['code'])
        self.assertIn('factor_lab_vote_7d', data['filename'])

    def test_export_disabled_factors_skipped(self):
        resp = self._post({
            'factors': [
                {'id': 'keep_increasing', 'weight': 100, 'enabled': True},
                {'id': 'rsi_6', 'weight': 50, 'enabled': False, 'operator': '<', 'value': 30},
            ],
            'fusion_mode': 'and',
            'holding_days': 10,
        })
        self.assertEqual(resp.code, 200)
        data = json.loads(resp.body)
        self.assertNotIn('rsi_6', data['code'])
