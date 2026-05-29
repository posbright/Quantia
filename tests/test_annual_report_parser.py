"""Unit tests for quantia/core/crawling/annual_report_parser.py (Phase 3a)."""
from __future__ import annotations

import pytest

from quantia.core.crawling import annual_report_parser as arp


# 模拟一段典型的"研发投入"年报文本
_SAMPLE_TEXT = """
第五节 经营情况讨论与分析

四、研发投入情况

截至报告期末，公司累计获得专利 286 项，其中发明专利 158 项，
实用新型专利 98 项，外观设计专利 30 项。报告期内新增专利 42 项。
公司 PCT 国际申请 15 件。
公司研发人员共 1,235 人，研发人员占员工总数的比例为 28.6%。

公司核心技术及其先进性:
公司在5G通信、物联网及人工智能领域拥有多项核心专利技术，覆盖芯片设计、
通信协议、AI算法等关键环节。主要 IPC 分类: H04L 数据交换网络、
H04W 无线通信网络、G06F 电数据处理。新一代基带芯片采用 7nm 工艺。

公司其它无关章节...
"""

_SAMPLE_NO_PATENT = """
本公司主要从事零售业务，2024年实现营业收入 100 亿元，同比增长 5%。
报告期内门店数量从 200 家增至 250 家。
"""


class TestLocateSection:
    def test_finds_anchor(self):
        section = arp.locate_rd_section(_SAMPLE_TEXT)
        assert '专利' in section

    def test_no_anchor_returns_full(self):
        # 没有任何锚点关键词时返回原文
        section = arp.locate_rd_section('一段无关文本')
        assert section == '一段无关文本'

    def test_empty(self):
        assert arp.locate_rd_section('') == ''


class TestExtractCounts:
    def test_all_fields(self):
        r = arp.extract_patent_counts(_SAMPLE_TEXT)
        assert r['total_patents'] == 286
        assert r['invention_patents'] == 158
        assert r['utility_patents'] == 98
        assert r['design_patents'] == 30
        assert r['new_patents_year'] == 42
        assert r['pct_international'] == 15

    def test_missing(self):
        r = arp.extract_patent_counts(_SAMPLE_NO_PATENT)
        assert r['total_patents'] is None
        assert r['invention_patents'] is None


class TestExtractRdStaff:
    def test_basic(self):
        r = arp.extract_rd_staff(_SAMPLE_TEXT)
        assert r['rd_staff_count'] == 1235
        assert r['rd_staff_ratio'] == 28.6

    def test_missing(self):
        r = arp.extract_rd_staff('无关文本')
        assert r['rd_staff_count'] is None
        assert r['rd_staff_ratio'] is None


class TestExtractIpc:
    def test_finds_codes(self):
        r = arp.extract_ipc_info(_SAMPLE_TEXT)
        assert r['ipc_primary'] in ('H04L', 'H04W', 'G06F')
        # H 大类应胜出 (H04L + H04W = 2 个)
        assert r['ipc_primary'].startswith('H') or r['ipc_primary'] == 'G06F'
        assert r['ipc_distribution'] is not None
        assert len(r['ipc_distribution']) >= 2
        assert r['tech_domain'] is not None

    def test_no_ipc(self):
        r = arp.extract_ipc_info(_SAMPLE_NO_PATENT)
        assert r['ipc_primary'] is None
        assert r['ipc_distribution'] is None
        assert r['tech_domain'] is None


class TestExtractKeyTech:
    def test_finds(self):
        desc = arp.extract_key_tech_desc(_SAMPLE_TEXT)
        assert desc is not None
        assert '核心' in desc or '5G' in desc or 'AI' in desc
        assert len(desc) <= 500

    def test_missing(self):
        assert arp.extract_key_tech_desc('无关文本') is None


class TestParseAnnualReport:
    def test_text_input(self):
        r = arp.parse_annual_report(_SAMPLE_TEXT, code='000001', year=2024)
        assert r['code'] == '000001'
        assert r['year'] == 2024
        assert r['total_patents'] == 286
        assert r['invention_patents'] == 158
        assert r['invention_ratio'] == round(158 / 286 * 100, 2)
        assert r['data_source'] == 'annual_report'
        assert r['confidence_score'] == 95
        assert r['rd_staff_count'] == 1235

    def test_no_patent_text(self):
        r = arp.parse_annual_report(_SAMPLE_NO_PATENT, code='000002', year=2024)
        assert r['code'] == '000002'
        assert r['total_patents'] is None
        assert r['invention_ratio'] is None

    def test_invalid_source_type(self):
        with pytest.raises(TypeError):
            arp.parse_annual_report(12345)  # type: ignore


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
