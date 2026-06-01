"""Tests for fetch_patent_data job and stockPatentHandler — mock DB/network."""
from __future__ import annotations

import json
import sys
import types
from unittest import mock

import pytest


def _stub(name: str) -> None:
    if name not in sys.modules:
        sys.modules[name] = types.ModuleType(name)


class _AutoStub(types.ModuleType):
    """对任意属性返回 Mock 的桩模块, 用于规避 talib 等原生依赖。"""

    def __getattr__(self, item):  # noqa: D401
        return mock.MagicMock(name=f'{self.__name__}.{item}')


# 为缺失的可选/原生依赖打桩, 确保被测模块可导入
if 'talib' not in sys.modules:
    sys.modules['talib'] = _AutoStub('talib')


# ---------------------------------------------------------------------------
# fetch_patent_data job
# ---------------------------------------------------------------------------

class TestFetchPatentDataJob:

    def test_upsert_builds_correct_sql(self):
        from quantia.job import fetch_patent_data as job
        with mock.patch.object(job.mdb, 'executeSql') as exec_sql, \
                mock.patch.object(job.pa, 'ensure_patents_table'):
            job.upsert_patents({
                'code': '300750', 'year': 2024,
                'total_patents': 100, 'invention_patents': 60,
                'ipc_distribution': {'H04L': 10, 'G06F': 5},
                'trend_5y': [{'year': 2024, 'count': 100}],
                'data_source': 'annual_report',
            })
            assert exec_sql.called
            sql, params = exec_sql.call_args[0]
            assert 'INSERT INTO' in sql
            assert 'ON DUPLICATE KEY UPDATE' in sql
            assert '`code`' in sql and '`year`' in sql
            # JSON 字段必须被序列化为字符串
            params_list = list(params)
            json_strs = [p for p in params_list if isinstance(p, str) and '{' in p]
            ipc_str = next(p for p in json_strs if 'H04L' in p)
            assert json.loads(ipc_str) == {'H04L': 10, 'G06F': 5}

    def test_upsert_skips_none_fields(self):
        from quantia.job import fetch_patent_data as job
        with mock.patch.object(job.mdb, 'executeSql') as exec_sql, \
                mock.patch.object(job.pa, 'ensure_patents_table'):
            job.upsert_patents({'code': '000001', 'year': 2024,
                                'total_patents': 10})
            sql = exec_sql.call_args[0][0]
            # 未提供的字段不应出现
            assert 'avg_citation_count' not in sql
            assert 'pct_international' not in sql
            assert 'total_patents' in sql

    def test_process_stock_year_skipped_on_no_pdf(self):
        from quantia.job import fetch_patent_data as job
        with mock.patch.object(job.cninfo, 'download_annual_report', return_value=None):
            r = job.process_stock_year('000001', 2024)
            assert r['status'] == 'skipped'
            assert '年报' in r['reason']

    def test_process_stock_year_skipped_when_no_patents_extracted(self, tmp_path):
        from quantia.job import fetch_patent_data as job
        fake_pdf = tmp_path / 'a.pdf'
        fake_pdf.write_bytes(b'%PDF-1.4 fake')
        with mock.patch.object(job.cninfo, 'download_annual_report', return_value=fake_pdf), \
                mock.patch.object(job.parser, 'parse_annual_report',
                                  return_value={'code': '000001', 'year': 2024,
                                                'total_patents': None}):
            r = job.process_stock_year('000001', 2024)
            assert r['status'] == 'skipped'

    def test_process_stock_year_failed_on_validate(self, tmp_path):
        from quantia.job import fetch_patent_data as job
        fake_pdf = tmp_path / 'a.pdf'
        fake_pdf.write_bytes(b'%PDF-1.4 fake')
        bad = {'code': '000001', 'year': 2024,
               'total_patents': 99999, 'invention_patents': 10}
        with mock.patch.object(job.cninfo, 'download_annual_report', return_value=fake_pdf), \
                mock.patch.object(job.parser, 'parse_annual_report', return_value=bad):
            r = job.process_stock_year('000001', 2024)
            assert r['status'] == 'failed'

    def test_process_stock_year_ok_path(self, tmp_path):
        from quantia.job import fetch_patent_data as job
        fake_pdf = tmp_path / 'a.pdf'
        fake_pdf.write_bytes(b'%PDF-1.4 fake')
        good = {
            'code': '300750', 'year': 2024,
            'total_patents': 286, 'invention_patents': 158,
            'utility_patents': 98, 'design_patents': 30,
            'invention_ratio': 55.24, 'rd_staff_count': 1235,
            'rd_staff_ratio': 28.6,
        }
        with mock.patch.object(job.cninfo, 'download_annual_report', return_value=fake_pdf), \
                mock.patch.object(job.parser, 'parse_annual_report', return_value=good), \
                mock.patch.object(job.mdb, 'executeSqlFetch', return_value=[]), \
                mock.patch.object(job.mdb, 'executeSql') as exec_sql, \
                mock.patch.object(job.pa, 'ensure_patents_table'):
            r = job.process_stock_year('300750', 2024)
            assert r['status'] == 'ok'
            assert exec_sql.called

    def test_build_trend_input_combines_history(self):
        from quantia.job import fetch_patent_data as job
        # 历史 2023:50, 2022:30 + 当前 2024:100
        with mock.patch.object(job.mdb, 'executeSqlFetch',
                               return_value=[(2023, 50), (2022, 30)]):
            data = job._build_trend_input('000001', 2024, 100)
            assert {'year': 2024, 'count': 100} in data
            years = [d['year'] for d in data]
            assert 2023 in years and 2022 in years and 2024 in years


# ---------------------------------------------------------------------------
# stockPatentHandler
# ---------------------------------------------------------------------------

class TestStockPatentHandler:

    def test_row_to_dict_parses_json_fields(self):
        from quantia.web import stockPatentHandler as h
        row = list(range(len(h._LIST_COLUMNS)))
        # 模拟 JSON 字段
        ipc_idx = h._LIST_COLUMNS.index('ipc_distribution')
        trend_idx = h._LIST_COLUMNS.index('trend_5y')
        row[ipc_idx] = '{"H04L": 5}'
        row[trend_idx] = '[{"year": 2024, "count": 10}]'
        out = h._row_to_dict(tuple(row))
        assert out['ipc_distribution'] == {'H04L': 5}
        assert out['trend_5y'] == [{'year': 2024, 'count': 10}]
        assert out['code'] == 0  # 数字字段未被破坏

    def test_row_to_dict_handles_malformed_json(self):
        from quantia.web import stockPatentHandler as h
        row = [None] * len(h._LIST_COLUMNS)
        ipc_idx = h._LIST_COLUMNS.index('ipc_distribution')
        row[ipc_idx] = 'not-a-json'
        out = h._row_to_dict(tuple(row))
        # 解析失败时保留原值, 不抛错
        assert out['ipc_distribution'] == 'not-a-json'

    def test_table_exists_returns_false_on_error(self):
        from quantia.web import stockPatentHandler as h
        with mock.patch.object(h.mdb, 'checkTableIsExist',
                               side_effect=RuntimeError('no db')):
            assert h._table_exists() is False


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
