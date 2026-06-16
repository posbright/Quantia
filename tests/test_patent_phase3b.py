"""Phase 3b 单元测试: IPC 映射 / Google Patents 聚合 / 增量合并 job。

全部离线运行 — 网络函数被 mock, 纯聚合函数直接调用。
"""
from __future__ import annotations

import json
import sys
import types
from unittest import mock

import pytest


class _AutoStub(types.ModuleType):
    def __getattr__(self, item):
        return mock.MagicMock(name=f'{self.__name__}.{item}')


if 'talib' not in sys.modules:
    sys.modules['talib'] = _AutoStub('talib')


# ---------------------------------------------------------------------------
# patent_ipc_mapping
# ---------------------------------------------------------------------------

class TestIpcMapping:

    def test_parse_ipc_code_variants(self):
        from quantia.core import patent_ipc_mapping as m
        assert m.parse_ipc_code('H04L') == ('H', 'H04', 'H04L')
        assert m.parse_ipc_code('H04L 29/06') == ('H', 'H04', 'H04L')
        assert m.parse_ipc_code('g06f') == ('G', 'G06', 'G06F')
        assert m.parse_ipc_code('H 04 L') == ('H', 'H04', 'H04L')
        assert m.parse_ipc_code('H04') == ('H', 'H04', None)

    def test_parse_ipc_code_invalid(self):
        from quantia.core import patent_ipc_mapping as m
        assert m.parse_ipc_code('') is None
        assert m.parse_ipc_code('XYZ') is None
        assert m.parse_ipc_code(None) is None

    def test_ipc_to_desc_class_then_section(self):
        from quantia.core import patent_ipc_mapping as m
        assert m.ipc_to_desc('H04L') == '电通信技术'       # 大类级
        assert m.ipc_to_desc('H99Z') == '电学'             # 回退部级
        assert m.ipc_to_desc('A61K') == '医学/兽医/卫生'

    def test_ipc_to_tech_domain(self):
        from quantia.core import patent_ipc_mapping as m
        assert m.ipc_to_tech_domain('H04L') == '通信'
        assert m.ipc_to_tech_domain('G06F') == '计算机/AI'
        assert m.ipc_to_tech_domain('A61K') == '生物医药'
        assert m.ipc_to_tech_domain('E04B') == '建筑/建材'   # 回退部级

    def test_build_ipc_distribution(self):
        from quantia.core import patent_ipc_mapping as m
        codes = ['H04L29/06', 'H04L12/00', 'G06F1/00', 'H01M10/05', 'bad']
        dist = m.build_ipc_distribution(codes)
        assert dist['H04'] == 2
        assert dist['G06'] == 1
        assert dist['H01'] == 1
        assert 'bad' not in dist

    def test_primary_ipc(self):
        from quantia.core import patent_ipc_mapping as m
        codes = ['H04L29/06', 'H04W4/00', 'G06F1/00']
        res = m.primary_ipc(codes)
        assert res['ipc_primary'] == 'H04'
        assert res['ipc_primary_desc'] == '电通信技术'
        assert res['tech_domain'] == '通信'
        assert res['ipc_distribution']['H04'] == 2

    def test_primary_ipc_empty(self):
        from quantia.core import patent_ipc_mapping as m
        res = m.primary_ipc([])
        assert res['ipc_primary'] is None
        assert res['ipc_distribution'] is None


# ---------------------------------------------------------------------------
# google_patents_crawler — 纯聚合函数
# ---------------------------------------------------------------------------

def _sample_patents():
    return [
        {'id': 'CN111A', 'ipc_codes': ['H04L29/06'], 'citation_count': 5,
         'filing_year': 2022, 'is_pct': False, 'country': 'CN'},
        {'id': 'CN222A', 'ipc_codes': ['H04L12/00', 'G06F1/00'], 'citation_count': 1,
         'filing_year': 2023, 'is_pct': False, 'country': 'CN'},
        {'id': 'WO333', 'ipc_codes': ['H04W4/00'], 'citation_count': 9,
         'filing_year': 2024, 'is_pct': True, 'country': 'WO'},
    ]


class TestGooglePatentsAggregation:

    def test_normalize_patent_from_xhr(self):
        from quantia.core.crawling import google_patents_crawler as g
        raw = {
            'publication_number': 'CN112233445A',
            'title': '一种电池管理方法',
            'assignee': '宁德时代新能源科技股份有限公司',
            'filing_date': '2022-05-01',
            'ipc': 'H01M10/05;H01M50/00',
            'cited_by_count': '7',
        }
        n = g.normalize_patent(raw)
        assert n['id'] == 'CN112233445A'
        assert n['filing_year'] == 2022
        assert n['ipc_codes'] == ['H01M10/05', 'H01M50/00']
        assert n['citation_count'] == 7
        assert n['country'] == 'CN'
        assert n['is_pct'] is False

    def test_normalize_patent_pct_detection(self):
        from quantia.core.crawling import google_patents_crawler as g
        n = g.normalize_patent({'publication_number': 'WO2022123456A1',
                                'ipc': [{'code': 'H04L'}]})
        assert n['is_pct'] is True
        assert n['ipc_codes'] == ['H04L']

    def test_extract_ipc_distribution(self):
        from quantia.core.crawling import google_patents_crawler as g
        dist = g.extract_ipc_distribution(_sample_patents())
        assert dist['H04'] == 3
        assert dist['G06'] == 1

    def test_extract_citation_stats(self):
        from quantia.core.crawling import google_patents_crawler as g
        stats = g.extract_citation_stats(_sample_patents())
        assert stats['avg_citation_count'] == 5.0
        assert stats['max_citation_count'] == 9

    def test_extract_citation_stats_empty(self):
        from quantia.core.crawling import google_patents_crawler as g
        stats = g.extract_citation_stats([])
        assert stats['avg_citation_count'] is None

    def test_extract_yearly_trend_fills_zero_years(self):
        from quantia.core.crawling import google_patents_crawler as g
        trend = g.extract_yearly_trend(_sample_patents(), years=5, end_year=2024)
        years = [d['year'] for d in trend]
        assert years == [2020, 2021, 2022, 2023, 2024]
        counts = {d['year']: d['count'] for d in trend}
        assert counts[2022] == 1 and counts[2023] == 1 and counts[2024] == 1
        assert counts[2020] == 0 and counts[2021] == 0

    def test_calculate_pct_count(self):
        from quantia.core.crawling import google_patents_crawler as g
        assert g.calculate_pct_count(_sample_patents()) == 1

    def test_aggregate_google_patents(self):
        from quantia.core.crawling import google_patents_crawler as g
        agg = g.aggregate_google_patents(_sample_patents(), end_year=2024)
        assert agg['total_patents'] == 3
        assert agg['pct_international'] == 1
        assert agg['ipc_primary'] == 'H04'
        assert agg['tech_domain'] == '通信'
        assert agg['data_source'] == 'google_patents'
        assert agg['confidence_score'] == 80
        assert len(agg['trend_5y']) == 5

    def test_aggregate_empty(self):
        from quantia.core.crawling import google_patents_crawler as g
        assert g.aggregate_google_patents([]) == {}

    def test_search_patents_graceful_on_no_assignee(self):
        from quantia.core.crawling import google_patents_crawler as g
        assert g.search_patents('') == []

    def test_search_patents_uses_cache(self):
        from quantia.core.crawling import google_patents_crawler as g
        with mock.patch.object(g, '_load_cache', return_value=_sample_patents()):
            res = g.search_patents('宁德时代')
            assert len(res) == 3

    def test_search_patents_handles_http_error(self):
        from quantia.core.crawling import google_patents_crawler as g
        fake_requests = mock.MagicMock()
        fake_resp = mock.MagicMock(status_code=503)
        fake_requests.get.return_value = fake_resp
        with mock.patch.object(g, '_load_cache', return_value=None), \
                mock.patch.dict(sys.modules, {'requests': fake_requests}):
            assert g.search_patents('某公司') == []

    def test_search_patents_retries_on_503_then_succeeds(self):
        # 503 限流时应换 IP 退避重试; 第二次 200 则解析成功。
        from quantia.core.crawling import google_patents_crawler as g
        payload = {'results': {'cluster': [
            {'result': [{'patent': {'publication_number': 'CN1A', 'ipc': 'H04L',
                                    'filing_date': '2023-01-01'}}]}
        ]}}
        resp_503 = mock.MagicMock(status_code=503)
        resp_200 = mock.MagicMock(status_code=200, text=json.dumps(payload))
        pr = mock.MagicMock(side_effect=[resp_503, resp_200])
        with mock.patch.object(g, '_load_cache', return_value=None), \
                mock.patch.object(g, '_save_cache'), \
                mock.patch('quantia.core.singleton_proxy.proxied_request', pr), \
                mock.patch.object(g.time, 'sleep'):
            res = g.search_patents('某公司', use_cache=False)
        assert pr.call_count == 2
        assert len(res) == 1
        assert res[0]['id'] == 'CN1A'

    def test_search_patents_gives_up_after_max_retries(self):
        # 持续 503 时应在重试上限后优雅返回 []。
        from quantia.core.crawling import google_patents_crawler as g
        resp_503 = mock.MagicMock(status_code=503)
        pr = mock.MagicMock(return_value=resp_503)
        with mock.patch.object(g, '_load_cache', return_value=None), \
                mock.patch('quantia.core.singleton_proxy.proxied_request', pr), \
                mock.patch.object(g.time, 'sleep'):
            res = g.search_patents('某公司', use_cache=False)
        assert res == []
        assert pr.call_count == 3

    def test_parse_xhr_results(self):
        from quantia.core.crawling import google_patents_crawler as g
        payload = {'results': {'cluster': [
            {'result': [
                {'patent': {'publication_number': 'CN1A', 'ipc': 'H04L',
                            'filing_date': '2023-01-01'}},
                {'patent': {'publication_number': 'CN2A', 'ipc': 'G06F',
                            'filing_date': '2024-01-01'}},
            ]}
        ]}}
        out = g._parse_xhr_results(payload)
        assert len(out) == 2
        assert out[0]['id'] == 'CN1A'

    def test_fetch_and_aggregate_dedups(self):
        from quantia.core.crawling import google_patents_crawler as g
        dup = _sample_patents()
        with mock.patch.object(g, 'search_patents', return_value=dup):
            # 两个名字返回同样 3 条 → 去重后仍 3 条
            agg = g.fetch_and_aggregate(['全称A', '简称B'], years=5)
            assert agg['total_patents'] == 3


# ---------------------------------------------------------------------------
# fetch_patent_data — Google 增量路径
# ---------------------------------------------------------------------------

class TestGoogleIncrementalJob:

    def test_get_company_names(self):
        from quantia.job import fetch_patent_data as job
        with mock.patch.object(job.mdb, 'executeSqlFetch',
                               return_value=[('宁德时代',)]):
            names = job.get_company_names('300750')
            assert '宁德时代' in names
            assert any('股份有限公司' in n for n in names)

    def test_process_google_patents_skipped_no_names(self):
        from quantia.job import fetch_patent_data as job
        with mock.patch.object(job, 'get_company_names', return_value=[]):
            r = job.process_google_patents('300750', 2024)
            assert r['status'] == 'skipped'

    def test_process_google_patents_skipped_no_google_result(self):
        from quantia.job import fetch_patent_data as job
        with mock.patch.object(job, 'get_company_names', return_value=['宁德时代']), \
                mock.patch.object(job.gpatents, 'fetch_and_aggregate', return_value={}):
            r = job.process_google_patents('300750', 2024)
            assert r['status'] == 'skipped'

    def test_process_google_patents_merges_and_upserts(self):
        from quantia.job import fetch_patent_data as job
        google = {
            'total_patents': 300, 'avg_citation_count': 6.2,
            'pct_international': 12, 'ipc_primary': 'H01',
            'ipc_primary_desc': '基本电气元件', 'tech_domain': '电子元件',
            'ipc_distribution': {'H01': 30},
            'trend_5y': [{'year': 2023, 'count': 40}, {'year': 2024, 'count': 60}],
            'data_source': 'google_patents', 'confidence_score': 80,
        }
        annual = {'total_patents': 286, 'invention_patents': 158,
                  'rd_staff_ratio': 28.6, 'key_tech_desc': '5G'}
        with mock.patch.object(job, 'get_company_names', return_value=['宁德时代']), \
                mock.patch.object(job.gpatents, 'fetch_and_aggregate', return_value=google), \
                mock.patch.object(job, '_fetch_annual_row', return_value=annual), \
                mock.patch.object(job, 'upsert_patents') as up:
            r = job.process_google_patents('300750', 2024)
            assert r['status'] == 'ok'
            merged = up.call_args[0][0]
            # 年报权威字段优先
            assert merged['total_patents'] == 286
            # Google 字段补充
            assert merged['avg_citation_count'] == 6.2
            assert merged['pct_international'] == 12
            assert merged['data_source'] == 'mixed'
            assert merged['confidence_score'] == 85
            assert merged['patent_quality_score'] is not None
            import re as _re
            sd = merged['source_detail']['google_patents']
            assert _re.fullmatch(r'\d{4}-Q[1-4]', sd), sd
            assert merged['source_detail']['annual_report'] == '2024'

    def test_process_google_patents_google_only(self):
        from quantia.job import fetch_patent_data as job
        google = {
            'total_patents': 120, 'avg_citation_count': 3.0,
            'pct_international': 4, 'ipc_primary': 'G06',
            'ipc_primary_desc': '计算/推算/计数（含计算机）', 'tech_domain': '计算机/AI',
            'ipc_distribution': {'G06': 20},
            'trend_5y': [{'year': 2023, 'count': 50}, {'year': 2024, 'count': 70}],
            'data_source': 'google_patents', 'confidence_score': 80,
        }
        with mock.patch.object(job, 'get_company_names', return_value=['某科技']), \
                mock.patch.object(job.gpatents, 'fetch_and_aggregate', return_value=google), \
                mock.patch.object(job, '_fetch_annual_row', return_value=None), \
                mock.patch.object(job, 'upsert_patents') as up:
            r = job.process_google_patents('300001', 2024)
            assert r['status'] == 'ok'
            merged = up.call_args[0][0]
            assert merged['total_patents'] == 120
            assert merged['data_source'] == 'google_patents'
            assert merged['confidence_score'] == 80
            assert 'annual_report' not in merged['source_detail']

    def test_run_dispatches_to_google_source(self):
        from quantia.job import fetch_patent_data as job
        with mock.patch.object(job.pa, 'ensure_patents_table'), \
                mock.patch.object(job, 'process_google_patents',
                                  return_value={'status': 'ok'}) as pg, \
                mock.patch.object(job, 'process_stock_year') as psy:
            stats = job.run(codes=['300750'], years=[2024], source='google_patents')
            assert stats['ok'] == 1
            assert pg.called
            assert not psy.called


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
