#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EPO OPS 采集器单测 (离线, mock 网络)。"""
from __future__ import annotations

import base64
from unittest import mock

import pytest

from quantia.core.crawling import epo_ops_crawler as epo


# --------------------------------------------------------------------------
# 凭证 / 开关
# --------------------------------------------------------------------------

def test_no_credentials_disabled(monkeypatch):
    monkeypatch.delenv('QUANTIA_EPO_OPS_KEY', raising=False)
    monkeypatch.delenv('QUANTIA_EPO_OPS_SECRET', raising=False)
    assert epo.get_credentials() is None
    assert epo.is_enabled() is False
    # 缺凭证: 各网络入口优雅返回, 不抛出
    assert epo.get_access_token() is None
    assert epo.search_patents('宁德时代') == []
    assert epo.fetch_and_aggregate(['宁德时代']) == {}


def test_partial_credentials_disabled(monkeypatch):
    monkeypatch.setenv('QUANTIA_EPO_OPS_KEY', 'k')
    monkeypatch.delenv('QUANTIA_EPO_OPS_SECRET', raising=False)
    assert epo.get_credentials() is None


# --------------------------------------------------------------------------
# Token (mock)
# --------------------------------------------------------------------------

def test_get_access_token_success(monkeypatch):
    monkeypatch.setenv('QUANTIA_EPO_OPS_KEY', 'mykey')
    monkeypatch.setenv('QUANTIA_EPO_OPS_SECRET', 'mysecret')
    epo._token_cache.update({'token': None, 'expires_at': 0.0})

    resp = mock.Mock(status_code=200)
    resp.json.return_value = {'access_token': 'TOK123', 'expires_in': 1200}
    with mock.patch('quantia.core.singleton_proxy.proxied_request',
                    return_value=resp) as pr:
        tok = epo.get_access_token()
    assert tok == 'TOK123'
    # 校验 Basic auth 头
    _, kwargs = pr.call_args
    expected = base64.b64encode(b'mykey:mysecret').decode('ascii')
    assert kwargs['headers']['Authorization'] == f'Basic {expected}'
    # 第二次命中内存缓存, 不再请求
    with mock.patch('quantia.core.singleton_proxy.proxied_request') as pr2:
        assert epo.get_access_token() == 'TOK123'
        pr2.assert_not_called()


def test_get_access_token_http_error(monkeypatch):
    monkeypatch.setenv('QUANTIA_EPO_OPS_KEY', 'k')
    monkeypatch.setenv('QUANTIA_EPO_OPS_SECRET', 's')
    epo._token_cache.update({'token': None, 'expires_at': 0.0})
    resp = mock.Mock(status_code=403)
    with mock.patch('quantia.core.singleton_proxy.proxied_request',
                    return_value=resp):
        assert epo.get_access_token() is None


# --------------------------------------------------------------------------
# IPC 文本归一化
# --------------------------------------------------------------------------

@pytest.mark.parametrize('text,expected', [
    ('H01M  10/0525        20100101', 'H01M10/0525'),
    ('H01M', 'H01M'),
    ('G06F  3/041', 'G06F3/041'),
    ('not-an-ipc', None),
    ('', None),
])
def test_normalize_ipc(text, expected):
    assert epo._normalize_ipc(text) == expected


# --------------------------------------------------------------------------
# 解析 OPS JSON (合成样本, 对齐 OPS biblio 结构)
# --------------------------------------------------------------------------

def _sample_payload():
    def _doc(country, num, ipcs, date):
        return {
            'exchange-document': {
                '@country': country,
                'bibliographic-data': {
                    'publication-reference': {
                        'document-id': {'doc-number': {'$': num},
                                        'date': {'$': date}},
                    },
                    'classifications-ipcr': {
                        'classification-ipcr': [
                            {'text': {'$': ipc}} for ipc in ipcs
                        ],
                    },
                },
            }
        }
    return {
        'ops:world-patent-data': {
            'ops:biblio-search': {
                'ops:search-result': {
                    'exchange-documents': [
                        _doc('CN', '112233445A', ['H01M  10/05', 'H02J  7/00'], '20220301'),
                        _doc('CN', '113344556B', ['H01M  4/13'], '20230615'),
                    ],
                },
            },
        },
    }


def test_parse_ops_response():
    patents = epo.parse_ops_response(_sample_payload())
    assert len(patents) == 2
    p0 = patents[0]
    assert p0['country'] == 'CN'
    assert p0['filing_year'] == 2022
    assert 'H01M10/05' in p0['ipc_codes']
    assert 'H02J7/00' in p0['ipc_codes']
    assert p0['id'] == 'CN112233445A'


def test_parse_ops_response_empty():
    assert epo.parse_ops_response({}) == []
    assert epo.parse_ops_response(None) == []
    assert epo.parse_ops_response({'garbage': 1}) == []


def test_parse_skips_doc_without_ipc():
    payload = {
        'exchange-document': {
            '@country': 'CN',
            'bibliographic-data': {'publication-reference': {'date': {'$': '20220101'}}},
        }
    }
    assert epo.parse_ops_response(payload) == []


# --------------------------------------------------------------------------
# 聚合
# --------------------------------------------------------------------------

def test_aggregate_epo_patents():
    patents = epo.parse_ops_response(_sample_payload())
    agg = epo.aggregate_epo_patents(patents, years=5, end_year=2024)
    assert agg['total_patents'] == 2
    assert agg['data_source'] == 'epo_ops'
    assert agg['confidence_score'] == 85
    assert agg['ipc_primary'] is not None
    dist = agg['ipc_distribution']
    assert isinstance(dist, dict) and dist
    assert any(k.startswith('H01') for k in dist)
    # 趋势含 2022/2023 计数
    trend = {t['year']: t['count'] for t in agg['trend_5y']}
    assert trend.get(2022) == 1
    assert trend.get(2023) == 1


def test_aggregate_empty():
    assert epo.aggregate_epo_patents([]) == {}


# --------------------------------------------------------------------------
# search_patents (mock token + 响应)
# --------------------------------------------------------------------------

def test_search_patents_success(monkeypatch, tmp_path):
    monkeypatch.setenv('QUANTIA_EPO_OPS_KEY', 'k')
    monkeypatch.setenv('QUANTIA_EPO_OPS_SECRET', 's')
    monkeypatch.setattr(epo, '_DEFAULT_CACHE_DIR', tmp_path)
    monkeypatch.setattr(epo, '_REQUEST_INTERVAL', 0)
    epo._token_cache.update({'token': 'TOK', 'expires_at': 9e18})

    resp = mock.Mock(status_code=200)
    resp.json.return_value = _sample_payload()
    with mock.patch('quantia.core.singleton_proxy.proxied_request',
                    return_value=resp):
        out = epo.search_patents('宁德时代', use_cache=False)
    assert len(out) == 2
    assert out[0]['country'] == 'CN'


def test_search_patents_http_error(monkeypatch, tmp_path):
    monkeypatch.setenv('QUANTIA_EPO_OPS_KEY', 'k')
    monkeypatch.setenv('QUANTIA_EPO_OPS_SECRET', 's')
    monkeypatch.setattr(epo, '_DEFAULT_CACHE_DIR', tmp_path)
    epo._token_cache.update({'token': 'TOK', 'expires_at': 9e18})
    resp = mock.Mock(status_code=404)
    with mock.patch('quantia.core.singleton_proxy.proxied_request',
                    return_value=resp):
        assert epo.search_patents('x', use_cache=False) == []
