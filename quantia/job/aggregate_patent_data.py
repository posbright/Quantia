#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 3a: 从 cn_stock_patent_info 聚合生成 cn_stock_patents 分析表。

本脚本读取 cn_stock_patent_info（公告级别原始数据），
按 (code, year) 聚合为每只股票每年的专利概要，
并调用 patent_analytics 计算含金量评分和趋势指标。

用法::

    python -m quantia.job.aggregate_patent_data
    python -m quantia.job.aggregate_patent_data --code 000001
"""
from __future__ import annotations

import argparse
import logging
from typing import Any, Dict, List, Optional

import quantia.lib.database as mdb
from quantia.core.patent_analytics import (
    calculate_patent_quality_score,
    calculate_trend_metrics,
    ensure_patents_table,
    percentiles_from_values,
    validate_patent_data,
)

_logger = logging.getLogger(__name__)
_DB_INSERT_CHUNKSIZE = 500
_AGGREGATED_TABLE = 'cn_stock_patents'


def ensure_aggregated_table():
    """确保聚合表存在 (统一走 patent_analytics 的权威 DDL)。

    历史上本函数自带一套精简 DDL（仅 19 列），与 fetch_patent_data 走的
    patent_analytics._CREATE_SQL（28 列）分叉：谁先建表谁定 schema，
    导致生产表缺 new_patents_year / patent_yoy / core_patents 等列，
    stockPatentHandler SELECT 报 1054。现统一委托 ensure_patents_table，
    并对历史精简表做幂等列补齐 (reconcile_patents_columns)。
    """
    ensure_patents_table()


def _fetch_yearly_stats(code: Optional[str] = None) -> List[Dict[str, Any]]:
    """从 cn_stock_patent_info 聚合每只股票每年的专利统计。"""
    where = "WHERE code = %s" if code else ""
    params = (code,) if code else ()
    sql = f"""
        SELECT code,
               YEAR(announcement_date) AS yr,
               SUM(COALESCE(patent_count, 1)) AS total,
               SUM(CASE WHEN patent_type='invention' THEN COALESCE(patent_count,1) ELSE 0 END) AS inv,
               SUM(CASE WHEN patent_type='utility' THEN COALESCE(patent_count,1) ELSE 0 END) AS util,
               SUM(CASE WHEN patent_type='design' THEN COALESCE(patent_count,1) ELSE 0 END) AS des
        FROM cn_stock_patent_info
        {where}
        GROUP BY code, YEAR(announcement_date)
        ORDER BY code, yr
    """
    rows = mdb.executeSqlFetch(sql, params) or []
    results = []
    for row in rows:
        results.append({
            'code': row[0],
            'year': int(row[1]),
            'total_patents': int(row[2] or 0),
            'invention_patents': int(row[3] or 0),
            'utility_patents': int(row[4] or 0),
            'design_patents': int(row[5] or 0),
        })
    return results


def _fetch_rd_ratios() -> Dict[str, float]:
    """从 cn_stock_financial 获取各股票最新的研发费用率(近似研发人员占比)。"""
    sql = """
        SELECT f.code, f.rd_ratio
        FROM cn_stock_financial f
        INNER JOIN (
            SELECT code, MAX(report_date) AS max_date
            FROM cn_stock_financial
            WHERE rd_ratio IS NOT NULL
            GROUP BY code
        ) latest ON f.code = latest.code AND f.report_date = latest.max_date
        WHERE f.rd_ratio IS NOT NULL
    """
    try:
        rows = mdb.executeSqlFetch(sql) or []
    except Exception:
        _logger.warning('[专利聚合] 读取 cn_stock_financial.rd_ratio 失败')
        return {}
    return {row[0]: float(row[1]) for row in rows if row[1] is not None}


def _fetch_industry_map() -> Dict[str, str]:
    """从 cn_stock_selection 获取各股票所属行业（取最新交易日）。

    选用 cn_stock_selection 而非 cn_stock_spot：spot 最新快照 industry 常为空，
    selection 最新交易日 industry 覆盖率 100%。
    """
    sql = """
        SELECT code, industry
        FROM cn_stock_selection
        WHERE date = (SELECT MAX(date) FROM cn_stock_selection)
          AND industry IS NOT NULL AND industry <> ''
    """
    try:
        rows = mdb.executeSqlFetch(sql) or []
    except Exception:
        _logger.warning('[专利聚合] 读取 cn_stock_selection.industry 失败，跳过行业分位数评分')
        return {}
    return {row[0]: row[1] for row in rows if row[1]}


def _build_industry_percentiles(
    by_code: Dict[str, List[Dict]], industry_map: Dict[str, str]
) -> Dict[str, Dict[str, Any]]:
    """从本批聚合结果按行业计算 total_patents 的分位数 (§9.7)。

    每只股票取其最新年度的 total_patents 作为该行业样本，
    样本不足 MIN_INDUSTRY_SAMPLES 的行业不产出分位数（回退绝对阈值）。
    """
    from collections import defaultdict
    industry_totals: Dict[str, List[int]] = defaultdict(list)
    for stock_code, years_data in by_code.items():
        industry = industry_map.get(stock_code)
        if not industry:
            continue
        latest = max(years_data, key=lambda d: d['year'])
        industry_totals[industry].append(latest['total_patents'])
    result: Dict[str, Dict[str, Any]] = {}
    for industry, totals in industry_totals.items():
        pct = percentiles_from_values(totals)
        if pct is not None:
            result[industry] = pct
    return result


def aggregate_patent_data(code: Optional[str] = None) -> Dict[str, int]:
    """主聚合流程。

    1. 从 cn_stock_patent_info 按 (code, year) 聚合
    2. 计算发明占比、趋势指标、含金量评分
    3. Upsert 到 cn_stock_patents
    """
    ensure_aggregated_table()

    # 检查源表是否存在
    if not mdb.checkTableIsExist('cn_stock_patent_info'):
        _logger.warning('[专利聚合] 源表 cn_stock_patent_info 不存在，跳过')
        return {'processed': 0, 'written': 0}

    yearly_stats = _fetch_yearly_stats(code)
    if not yearly_stats:
        _logger.info('[专利聚合] 无数据可聚合')
        return {'processed': 0, 'written': 0}

    # 按 code 分组以计算趋势
    from collections import defaultdict
    by_code: Dict[str, List[Dict]] = defaultdict(list)
    for row in yearly_stats:
        by_code[row['code']].append(row)

    # 获取研发费用率
    rd_ratios = _fetch_rd_ratios()

    # 行业分位数（§9.7）：每只股票取最新年度 total_patents，按行业计算 P25/P50/P75/P90
    industry_map = _fetch_industry_map()
    industry_percentiles = _build_industry_percentiles(by_code, industry_map)

    # 计算衍生指标
    records_to_write = []
    for stock_code, years_data in by_code.items():
        # 趋势数据（全部年份）
        trend_input = [{'year': d['year'], 'count': d['total_patents']} for d in years_data]
        trend_result = calculate_trend_metrics(trend_input)

        rd_ratio = rd_ratios.get(stock_code)
        stock_industry_pct = industry_percentiles.get(industry_map.get(stock_code))

        # 上一年专利总数映射, 用于计算同比增长率 patent_yoy
        total_by_year = {d['year']: d['total_patents'] for d in years_data}

        for yr_data in years_data:
            # invention_ratio = 发明专利 / 总专利数 (含general/ip_transfer)
            total = yr_data['total_patents']
            inv = yr_data['invention_patents']
            inv_ratio = round(inv / total * 100, 2) if total > 0 and inv > 0 else (
                0.0 if total > 0 else None
            )

            # 专利同比增长率 (%): (本年 - 去年) / 去年 * 100, 去年缺失或为 0 时留空
            prev_total = total_by_year.get(yr_data['year'] - 1)
            if prev_total and prev_total > 0:
                patent_yoy = round((total - prev_total) / prev_total * 100, 2)
            else:
                patent_yoy = None

            # 含金量评分（数量规模维度按行业分位数校准, 不足样本回退绝对阈值）
            score_input = {
                'total_patents': yr_data['total_patents'],
                'invention_ratio': inv_ratio,
                'trend_5y_cagr': trend_result['trend_5y_cagr'],
                'rd_staff_ratio': rd_ratio,
            }
            quality_score = calculate_patent_quality_score(
                score_input, industry_percentiles=stock_industry_pct
            )

            record = {
                'code': stock_code,
                'year': yr_data['year'],
                'total_patents': yr_data['total_patents'],
                'invention_patents': yr_data['invention_patents'],
                'utility_patents': yr_data['utility_patents'],
                'design_patents': yr_data['design_patents'],
                'invention_ratio': inv_ratio,
                'patent_yoy': patent_yoy,
                'patent_quality_score': quality_score,
                'trend_5y_cagr': trend_result['trend_5y_cagr'],
                'trend_direction': trend_result['trend_direction'],
                'rd_staff_ratio': rd_ratio,
                'confidence_score': 70,
                'data_source': 'announcement',
            }

            is_valid, reason = validate_patent_data(record)
            if not is_valid:
                _logger.warning(f'[专利聚合] 数据校验失败 {stock_code}/{yr_data["year"]}: {reason}')
                continue

            records_to_write.append(record)

    # Upsert 写入
    written = _upsert_records(records_to_write)
    _logger.info(f'[专利聚合] 处理 {len(by_code)} 只股票, 写入 {written} 条记录')
    return {'processed': len(by_code), 'written': written}


def _upsert_records(records: List[Dict[str, Any]]) -> int:
    """批量 UPSERT 到 cn_stock_patents。

    master/slave 守卫: 公告聚合路径 confidence=70。若目标行已被
    fetch_patent_data 的年报/Google 路径写入更高可信度 (confidence>70)，
    则不覆盖其数量/趋势字段，避免每日 workday 聚合把每月权威数据冲掉。
    """
    if not records:
        return 0

    written = 0
    for i in range(0, len(records), _DB_INSERT_CHUNKSIZE):
        chunk = records[i:i + _DB_INSERT_CHUNKSIZE]
        values = []
        params = []
        for r in chunk:
            values.append('(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)')
            params.extend([
                r['code'], r['year'],
                r['total_patents'], r['invention_patents'],
                r['utility_patents'], r['design_patents'],
                r['invention_ratio'], r['patent_yoy'], r['patent_quality_score'],
                r['trend_5y_cagr'], r['trend_direction'],
                r['rd_staff_ratio'], r['confidence_score'],
                r.get('data_source', 'announcement'),
            ])

        # IF(confidence_score > 70, 旧值, 新值): 保护更高可信度的年报/Google 数据
        sql = f"""
            INSERT INTO `{_AGGREGATED_TABLE}`
                (code, year, total_patents, invention_patents,
                 utility_patents, design_patents, invention_ratio, patent_yoy,
                 patent_quality_score, trend_5y_cagr, trend_direction,
                 rd_staff_ratio, confidence_score, data_source)
            VALUES {', '.join(values)}
            ON DUPLICATE KEY UPDATE
                total_patents = IF(confidence_score > 70, total_patents, VALUES(total_patents)),
                invention_patents = IF(confidence_score > 70, invention_patents, VALUES(invention_patents)),
                utility_patents = IF(confidence_score > 70, utility_patents, VALUES(utility_patents)),
                design_patents = IF(confidence_score > 70, design_patents, VALUES(design_patents)),
                invention_ratio = IF(confidence_score > 70, invention_ratio, VALUES(invention_ratio)),
                patent_yoy = IF(confidence_score > 70, patent_yoy, VALUES(patent_yoy)),
                patent_quality_score = IF(confidence_score > 70, patent_quality_score, VALUES(patent_quality_score)),
                trend_5y_cagr = IF(confidence_score > 70, trend_5y_cagr, VALUES(trend_5y_cagr)),
                trend_direction = IF(confidence_score > 70, trend_direction, VALUES(trend_direction)),
                rd_staff_ratio = IF(confidence_score > 70, rd_staff_ratio, VALUES(rd_staff_ratio)),
                data_source = IF(confidence_score > 70, data_source, VALUES(data_source)),
                confidence_score = IF(confidence_score > 70, confidence_score, VALUES(confidence_score))
        """
        try:
            mdb.executeSql(sql, tuple(params))
            written += len(chunk)
        except Exception as exc:
            _logger.error(f'[专利聚合] 写入失败: {exc}')

    return written


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(name)s %(message)s',
    )

    parser = argparse.ArgumentParser(description='Quantia 专利数据聚合')
    parser.add_argument('--code', type=str, default=None, help='指定股票代码(可选)')
    args = parser.parse_args()

    result = aggregate_patent_data(code=args.code)
    print(f'完成: {result}')
