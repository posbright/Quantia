"""Unit tests for quantia/core/patent_analytics.py (Phase 3a)."""
from __future__ import annotations

import pytest

from quantia.core import patent_analytics as pa


class TestInventionRatio:
    def test_basic(self):
        assert pa.calculate_invention_ratio(
            {'total_patents': 100, 'invention_patents': 60}) == 60.0

    def test_total_zero(self):
        assert pa.calculate_invention_ratio(
            {'total_patents': 0, 'invention_patents': 5}) is None

    def test_missing_field(self):
        assert pa.calculate_invention_ratio({}) is None


class TestQualityScore:
    def test_high_quality_company(self):
        # 高质量: 高发明占比 + 大量专利 + 强增长 + 引用 + PCT
        row = {
            'total_patents': 1000,
            'invention_patents': 850,
            'invention_ratio': 85,
            'trend_5y_cagr': 35,
            'avg_citation_count': 12,
            'pct_international': 30,
            'patent_maintenance_rate': 85,
        }
        score = pa.calculate_patent_quality_score(row)
        assert score >= 90

    def test_low_quality_company(self):
        row = {
            'total_patents': 5,
            'invention_patents': 0,
            'invention_ratio': 0,
            'trend_5y_cagr': -10,
        }
        score = pa.calculate_patent_quality_score(row)
        assert 0 <= score <= 30

    def test_missing_cagr_neutral(self):
        # CAGR 缺失应给中性分, 不影响其它维度
        row = {'total_patents': 200, 'invention_patents': 100, 'invention_ratio': 50}
        score = pa.calculate_patent_quality_score(row)
        assert 30 <= score <= 60

    def test_capped_at_100(self):
        row = {
            'total_patents': 5000, 'invention_patents': 5000, 'invention_ratio': 100,
            'trend_5y_cagr': 100, 'avg_citation_count': 50,
            'pct_international': 100, 'patent_maintenance_rate': 100,
        }
        assert pa.calculate_patent_quality_score(row) == 100


class TestTrendMetrics:
    def test_accelerating(self):
        data = [
            {'year': 2020, 'count': 10},
            {'year': 2021, 'count': 12},
            {'year': 2022, 'count': 18},
            {'year': 2023, 'count': 30},
            {'year': 2024, 'count': 60},
        ]
        r = pa.calculate_trend_metrics(data)
        assert r['trend_direction'] == 'accelerating'
        assert r['trend_5y_cagr'] is not None and r['trend_5y_cagr'] > 50

    def test_declining(self):
        data = [
            {'year': 2020, 'count': 100},
            {'year': 2021, 'count': 80},
            {'year': 2022, 'count': 60},
            {'year': 2023, 'count': 40},
            {'year': 2024, 'count': 20},
        ]
        r = pa.calculate_trend_metrics(data)
        assert r['trend_direction'] in ('declining', 'decelerating')
        assert r['trend_5y_cagr'] is not None and r['trend_5y_cagr'] < 0

    def test_unsorted_input(self):
        # 故意打乱顺序, 函数应内部排序
        data = [
            {'year': 2024, 'count': 60},
            {'year': 2020, 'count': 10},
            {'year': 2022, 'count': 18},
        ]
        r = pa.calculate_trend_metrics(data)
        assert r['trend_5y'][0]['year'] == 2020
        assert r['trend_5y'][-1]['year'] == 2024

    def test_zero_to_positive(self):
        data = [{'year': 2020, 'count': 0}, {'year': 2024, 'count': 50}]
        r = pa.calculate_trend_metrics(data)
        assert r['trend_5y_cagr'] == 100.0

    def test_too_few_points(self):
        assert pa.calculate_trend_metrics([])['trend_5y_cagr'] is None
        assert pa.calculate_trend_metrics([{'year': 2024, 'count': 1}])['trend_5y_cagr'] is None

    def test_negative_count_filtered(self):
        data = [
            {'year': 2020, 'count': 10},
            {'year': 2021, 'count': -5},  # 异常, 应被过滤
            {'year': 2022, 'count': 20},
        ]
        r = pa.calculate_trend_metrics(data)
        assert all((d['count'] or 0) >= 0 for d in r['trend_5y'])


class TestValidate:
    def test_ok(self):
        ok, _ = pa.validate_patent_data({
            'total_patents': 100, 'invention_patents': 60,
            'utility_patents': 30, 'design_patents': 5,
            'rd_staff_ratio': 25, 'invention_ratio': 60,
            'year': 2024,
        })
        assert ok

    def test_negative_count(self):
        ok, msg = pa.validate_patent_data({'total_patents': -1})
        assert not ok and '负数' in msg

    def test_subitems_exceed_total(self):
        ok, msg = pa.validate_patent_data({
            'total_patents': 10, 'invention_patents': 20, 'utility_patents': 0,
            'design_patents': 0,
        })
        assert not ok and '超过' in msg

    def test_subitems_within_10pct_tolerance(self):
        ok, _ = pa.validate_patent_data({
            'total_patents': 100, 'invention_patents': 60,
            'utility_patents': 45, 'design_patents': 0,
        })  # 105 <= 110, 通过
        assert ok

    def test_extreme_total(self):
        ok, msg = pa.validate_patent_data({'total_patents': 99999})
        assert not ok and '异常' in msg

    def test_ratio_out_of_range(self):
        ok, _ = pa.validate_patent_data({'rd_staff_ratio': 150})
        assert not ok
        ok, _ = pa.validate_patent_data({'invention_ratio': -5})
        assert not ok

    def test_year_out_of_range(self):
        ok, _ = pa.validate_patent_data({'year': 1900})
        assert not ok


class TestMerge:
    def test_empty_both(self):
        r = pa.merge_patent_data(None, None)
        assert r['data_source'] is None
        assert r['confidence_score'] == 0

    def test_annual_only(self):
        r = pa.merge_patent_data(
            {'total_patents': 100, 'invention_patents': 50, 'key_tech_desc': 'foo'},
            None,
        )
        assert r['data_source'] == 'annual_report'
        assert r['confidence_score'] == 95
        assert r['total_patents'] == 100
        assert r['avg_citation_count'] is None

    def test_google_only(self):
        r = pa.merge_patent_data(
            None,
            {'total_patents': 200, 'avg_citation_count': 8, 'pct_international': 10},
        )
        assert r['data_source'] == 'google_patents'
        assert r['confidence_score'] == 80
        assert r['avg_citation_count'] == 8

    def test_mixed_annual_priority(self):
        r = pa.merge_patent_data(
            {'total_patents': 100, 'invention_patents': 60},
            {'total_patents': 120, 'avg_citation_count': 5, 'pct_international': 3},
        )
        assert r['data_source'] == 'mixed'
        assert r['confidence_score'] == 85
        assert r['total_patents'] == 100  # 年报优先
        assert r['avg_citation_count'] == 5  # Google 独有

    def test_conflict_flag(self):
        # 年报 100 vs Google 300, 差异 66% > 50%, 应标记冲突
        r = pa.merge_patent_data(
            {'total_patents': 100, 'invention_patents': 50},
            {'total_patents': 300},
        )
        assert r.get('_conflict_flag') is True
        assert '差异' in r.get('_conflict_detail', '')

    def test_no_conflict_within_threshold(self):
        r = pa.merge_patent_data(
            {'total_patents': 100, 'invention_patents': 50},
            {'total_patents': 130},  # 差异 23% < 50%
        )
        assert '_conflict_flag' not in r


class TestTableSql:
    def test_create_sql_well_formed(self):
        # 仅做语法层面检查: 包含表名、PK、关键索引
        sql = pa._CREATE_SQL
        assert pa.PATENTS_TABLE in sql
        assert 'PRIMARY KEY (`code`, `year`)' in sql
        assert 'patent_quality_score' in sql
        assert 'trend_5y_cagr' in sql


class TestIndustryPercentile:
    """§9.7 行业分位数评分。"""

    def test_percentiles_from_values_basic(self):
        # 0..100 共 11 个样本
        pct = pa.percentiles_from_values(list(range(0, 101, 10)))
        assert pct is not None
        assert pct['count'] == 11
        assert pct['p25'] == 25.0
        assert pct['p50'] == 50.0
        assert pct['p75'] == 75.0
        assert pct['p90'] == 90.0

    def test_percentiles_insufficient_sample(self):
        # 样本不足 MIN_INDUSTRY_SAMPLES 返回 None
        assert pa.percentiles_from_values([1, 2, 3, 4]) is None

    def test_percentiles_ignores_none(self):
        pct = pa.percentiles_from_values([10, None, 20, 30, None, 40, 50])
        assert pct is not None
        assert pct['count'] == 5

    def test_score_by_industry_percentile_buckets(self):
        p = {'p25': 10, 'p50': 50, 'p75': 100, 'p90': 200, 'count': 10}
        assert pa.score_by_industry_percentile(250, p) == 20  # >= p90
        assert pa.score_by_industry_percentile(120, p) == 16  # >= p75
        assert pa.score_by_industry_percentile(60, p) == 12   # >= p50
        assert pa.score_by_industry_percentile(15, p) == 8    # >= p25
        assert pa.score_by_industry_percentile(5, p) == 3     # < p25

    def test_quality_score_uses_percentile_when_provided(self):
        # 同一只股票, total=120: 绝对阈值给 16 分 (>=100), 行业分位给 8 分 (>=p25)
        row = {'total_patents': 120, 'invention_ratio': 50}
        low_industry = {'p25': 100, 'p50': 300, 'p75': 800, 'p90': 1500, 'count': 10}
        score_abs = pa.calculate_patent_quality_score(row)
        score_pct = pa.calculate_patent_quality_score(
            row, industry_percentiles=low_industry)
        # 行业巨头林立时同样的专利数得分应更低
        assert score_pct < score_abs

    def test_quality_score_falls_back_when_sample_insufficient(self):
        row = {'total_patents': 120, 'invention_ratio': 50}
        thin = {'p25': 100, 'p50': 300, 'p75': 800, 'p90': 1500, 'count': 2}
        assert (pa.calculate_patent_quality_score(row, industry_percentiles=thin)
                == pa.calculate_patent_quality_score(row))


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
