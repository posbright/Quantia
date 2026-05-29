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
    validate_patent_data,
)

_logger = logging.getLogger(__name__)
_DB_INSERT_CHUNKSIZE = 500
_AGGREGATED_TABLE = 'cn_stock_patents'


def ensure_aggregated_table():
    """确保聚合表存在。"""
    if mdb.checkTableIsExist(_AGGREGATED_TABLE):
        return
    # NOTE: DDL 中不能用 % 符号，PyMySQL 会误认为格式化占位符
    ddl = (
        "CREATE TABLE IF NOT EXISTS `" + _AGGREGATED_TABLE + "` ("
        "`code` VARCHAR(10) NOT NULL COMMENT '股票代码',"
        "`year` SMALLINT NOT NULL COMMENT '统计年份',"
        "`total_patents` INT DEFAULT 0 COMMENT '专利公告总数',"
        "`invention_patents` INT DEFAULT 0 COMMENT '发明专利数',"
        "`utility_patents` INT DEFAULT 0 COMMENT '实用新型专利数',"
        "`design_patents` INT DEFAULT 0 COMMENT '外观设计专利数',"
        "`invention_ratio` FLOAT DEFAULT NULL COMMENT '发明专利占比',"
        "`patent_quality_score` TINYINT UNSIGNED DEFAULT NULL COMMENT '含金量评分0-100',"
        "`trend_5y_cagr` FLOAT DEFAULT NULL COMMENT '5年专利申请复合增长率',"
        "`trend_direction` ENUM('accelerating','stable','decelerating','declining')"
        " DEFAULT NULL COMMENT '趋势方向',"
        "`ipc_primary` VARCHAR(10) DEFAULT NULL COMMENT 'IPC主分类号',"
        "`ipc_primary_desc` VARCHAR(50) DEFAULT NULL COMMENT 'IPC主分类中文',"
        "`tech_domain` VARCHAR(50) DEFAULT NULL COMMENT '技术领域',"
        "`avg_citation_count` FLOAT DEFAULT NULL COMMENT '平均被引次数',"
        "`pct_international` INT DEFAULT NULL COMMENT 'PCT国际专利数',"
        "`rd_staff_ratio` FLOAT DEFAULT NULL COMMENT '研发人员占比(来自财报)',"
        "`key_tech_desc` TEXT DEFAULT NULL COMMENT '核心技术描述',"
        "`confidence_score` TINYINT UNSIGNED DEFAULT 70"
        " COMMENT '数据可信度0-100: 公告聚合70 年报95',"
        "`updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,"
        "PRIMARY KEY (`code`, `year`),"
        "INDEX `idx_quality` (`patent_quality_score` DESC),"
        "INDEX `idx_total` (`total_patents` DESC),"
        "INDEX `idx_trend` (`trend_5y_cagr` DESC),"
        "INDEX `idx_updated` (`updated_at`)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
        " COMMENT='上市公司专利数据聚合表'"
    )
    mdb.executeSql(ddl)
    _logger.info(f'[专利聚合] 创建表 {_AGGREGATED_TABLE}')


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

    # 计算衍生指标
    records_to_write = []
    for stock_code, years_data in by_code.items():
        # 趋势数据（全部年份）
        trend_input = [{'year': d['year'], 'count': d['total_patents']} for d in years_data]
        trend_result = calculate_trend_metrics(trend_input)

        rd_ratio = rd_ratios.get(stock_code)

        for yr_data in years_data:
            # invention_ratio = 发明专利 / 总专利数 (含general/ip_transfer)
            total = yr_data['total_patents']
            inv = yr_data['invention_patents']
            inv_ratio = round(inv / total * 100, 2) if total > 0 and inv > 0 else (
                0.0 if total > 0 else None
            )

            # 含金量评分
            score_input = {
                'total_patents': yr_data['total_patents'],
                'invention_ratio': inv_ratio,
                'trend_5y_cagr': trend_result['trend_5y_cagr'],
                'rd_staff_ratio': rd_ratio,
            }
            quality_score = calculate_patent_quality_score(score_input)

            record = {
                'code': stock_code,
                'year': yr_data['year'],
                'total_patents': yr_data['total_patents'],
                'invention_patents': yr_data['invention_patents'],
                'utility_patents': yr_data['utility_patents'],
                'design_patents': yr_data['design_patents'],
                'invention_ratio': inv_ratio,
                'patent_quality_score': quality_score,
                'trend_5y_cagr': trend_result['trend_5y_cagr'],
                'trend_direction': trend_result['trend_direction'],
                'rd_staff_ratio': rd_ratio,
                'confidence_score': 70,
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
    """批量 UPSERT 到 cn_stock_patents。"""
    if not records:
        return 0

    written = 0
    for i in range(0, len(records), _DB_INSERT_CHUNKSIZE):
        chunk = records[i:i + _DB_INSERT_CHUNKSIZE]
        values = []
        params = []
        for r in chunk:
            values.append('(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)')
            params.extend([
                r['code'], r['year'],
                r['total_patents'], r['invention_patents'],
                r['utility_patents'], r['design_patents'],
                r['invention_ratio'], r['patent_quality_score'],
                r['trend_5y_cagr'], r['trend_direction'],
                r['rd_staff_ratio'], r['confidence_score'],
            ])

        sql = f"""
            INSERT INTO `{_AGGREGATED_TABLE}`
                (code, year, total_patents, invention_patents,
                 utility_patents, design_patents, invention_ratio,
                 patent_quality_score, trend_5y_cagr, trend_direction,
                 rd_staff_ratio, confidence_score)
            VALUES {', '.join(values)}
            ON DUPLICATE KEY UPDATE
                total_patents = VALUES(total_patents),
                invention_patents = VALUES(invention_patents),
                utility_patents = VALUES(utility_patents),
                design_patents = VALUES(design_patents),
                invention_ratio = VALUES(invention_ratio),
                patent_quality_score = VALUES(patent_quality_score),
                trend_5y_cagr = VALUES(trend_5y_cagr),
                trend_direction = VALUES(trend_direction),
                rd_staff_ratio = VALUES(rd_staff_ratio),
                confidence_score = VALUES(confidence_score)
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
