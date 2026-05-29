#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 3a: 专利数据分析模块 — 含金量评分 / 5 年趋势 / 数据校验 / 双源合并。

设计参考: document/ai_moat_patent_enhancement_plan.md 第 2.4 / 9.3 / 9.5 节。

本模块属于 Compute 管道（见 AGENTS.md 规则 1），仅做纯计算与表结构保障，
不发起任何网络请求。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

_logger = logging.getLogger(__name__)

PATENTS_TABLE = 'cn_stock_patents'

_CREATE_SQL = f'''
CREATE TABLE IF NOT EXISTS `{PATENTS_TABLE}` (
    `code` VARCHAR(10) NOT NULL COMMENT '股票代码',
    `year` INT NOT NULL COMMENT '统计年度',

    `invention_patents` INT DEFAULT NULL COMMENT '发明专利数',
    `utility_patents` INT DEFAULT NULL COMMENT '实用新型专利数',
    `design_patents` INT DEFAULT NULL COMMENT '外观设计专利数',
    `total_patents` INT DEFAULT NULL COMMENT '专利总数',
    `new_patents_year` INT DEFAULT NULL COMMENT '当年新增专利',
    `patent_yoy` FLOAT DEFAULT NULL COMMENT '专利同比增长率(%)',

    `invention_ratio` FLOAT DEFAULT NULL COMMENT '发明专利占比(%)',
    `patent_quality_score` TINYINT UNSIGNED DEFAULT NULL COMMENT '专利含金量评分(0-100)',
    `avg_citation_count` FLOAT DEFAULT NULL COMMENT '平均被引用次数',
    `pct_international` INT DEFAULT NULL COMMENT 'PCT国际专利数量',
    `core_patents` INT DEFAULT NULL COMMENT '核心专利数',
    `patent_maintenance_rate` FLOAT DEFAULT NULL COMMENT '专利维持率(%)',

    `ipc_primary` VARCHAR(20) DEFAULT NULL COMMENT '主IPC分类号',
    `ipc_primary_desc` VARCHAR(100) DEFAULT NULL COMMENT '主IPC中文描述',
    `ipc_distribution` JSON DEFAULT NULL COMMENT 'IPC分布',
    `tech_domain` VARCHAR(50) DEFAULT NULL COMMENT '技术领域归类',

    `trend_5y` JSON DEFAULT NULL COMMENT '近5年申请数列表',
    `trend_5y_cagr` FLOAT DEFAULT NULL COMMENT '5年专利申请复合增长率(%)',
    `trend_direction` ENUM('accelerating','stable','decelerating','declining') DEFAULT NULL
        COMMENT '趋势方向',

    `rd_staff_count` INT DEFAULT NULL COMMENT '研发人员数量',
    `rd_staff_ratio` FLOAT DEFAULT NULL COMMENT '研发人员占比(%)',

    `key_tech_desc` TEXT COMMENT '核心技术描述',
    `competitive_position` VARCHAR(200) DEFAULT NULL COMMENT '行业专利排名描述',

    `data_source` ENUM('annual_report','google_patents','mixed') DEFAULT 'annual_report'
        COMMENT '数据来源',
    `source_detail` JSON DEFAULT NULL COMMENT '来源明细',
    `confidence_score` TINYINT UNSIGNED DEFAULT 80 COMMENT '数据可信度(0-100)',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '首次入库时间',
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (`code`, `year`),
    INDEX `idx_total` (`total_patents` DESC),
    INDEX `idx_quality` (`patent_quality_score` DESC),
    INDEX `idx_invention_ratio` (`invention_ratio` DESC),
    INDEX `idx_trend` (`trend_5y_cagr` DESC),
    INDEX `idx_ipc` (`ipc_primary`, `year`),
    INDEX `idx_tech_domain` (`tech_domain`, `total_patents` DESC),
    INDEX `idx_updated` (`updated_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='上市公司专利数据(护城河量化)'
'''


def ensure_patents_table() -> None:
    """确保 cn_stock_patents 表存在。"""
    import quantia.lib.database as mdb  # 延迟导入, 避免单测/无 DB 环境失败
    if not mdb.checkTableIsExist(PATENTS_TABLE):
        mdb.executeSql(_CREATE_SQL)
        _logger.info('[patent_analytics] 已创建表 %s', PATENTS_TABLE)


# ---------------------------------------------------------------------------
# 含金量评分
# ---------------------------------------------------------------------------

def calculate_invention_ratio(row: Dict[str, Any]) -> Optional[float]:
    """计算发明专利占比 (%)。total 为 0 或缺失时返回 None。"""
    total = row.get('total_patents') or 0
    inv = row.get('invention_patents') or 0
    if total <= 0:
        return None
    return round(inv / total * 100, 2)


def calculate_patent_quality_score(row: Dict[str, Any]) -> int:
    """综合评估专利含金量 (0-100 分)。

    维度权重: 发明占比(30) + 数量规模(20) + 5年CAGR(20)
              + 平均被引(15) + PCT国际(10) + 维持率(5)
    缺失字段按最低档计分（不抛错）。
    """
    score = 0

    inv_ratio = row.get('invention_ratio')
    if inv_ratio is None:
        inv_ratio = calculate_invention_ratio(row) or 0
    if inv_ratio >= 80:
        score += 30
    elif inv_ratio >= 60:
        score += 25
    elif inv_ratio >= 40:
        score += 18
    elif inv_ratio >= 20:
        score += 10
    else:
        score += 5

    total = row.get('total_patents') or 0
    if total >= 500:
        score += 20
    elif total >= 200:
        score += 16
    elif total >= 100:
        score += 12
    elif total >= 30:
        score += 8
    else:
        score += 3

    cagr = row.get('trend_5y_cagr')
    if cagr is None:
        score += 8  # 数据缺失给中性分
    elif cagr >= 30:
        score += 20
    elif cagr >= 15:
        score += 16
    elif cagr >= 5:
        score += 12
    elif cagr >= 0:
        score += 8
    else:
        score += 3

    citations = row.get('avg_citation_count') or 0
    if citations >= 10:
        score += 15
    elif citations >= 5:
        score += 12
    elif citations >= 2:
        score += 8
    elif citations > 0:
        score += 4

    pct = row.get('pct_international') or 0
    if pct >= 20:
        score += 10
    elif pct >= 5:
        score += 7
    elif pct > 0:
        score += 4

    maint = row.get('patent_maintenance_rate') or 0
    if maint >= 80:
        score += 5
    elif maint >= 60:
        score += 3
    elif maint >= 40:
        score += 1

    return min(score, 100)


# ---------------------------------------------------------------------------
# 5 年趋势计算
# ---------------------------------------------------------------------------

def calculate_trend_metrics(trend_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """从 5 年专利申请数计算 CAGR 与趋势方向。

    Args:
        trend_data: [{"year": 2021, "count": 30}, ...] 不要求已排序。

    Returns:
        {'trend_5y_cagr', 'trend_direction', 'trend_5y'}
    """
    if not trend_data or len(trend_data) < 2:
        return {'trend_5y_cagr': None, 'trend_direction': None, 'trend_5y': trend_data or []}

    cleaned = [d for d in trend_data if isinstance(d, dict)
               and d.get('year') is not None and (d.get('count') or 0) >= 0]
    cleaned = sorted(cleaned, key=lambda x: x['year'])
    if len(cleaned) < 2:
        return {'trend_5y_cagr': None, 'trend_direction': None, 'trend_5y': cleaned}

    first = cleaned[0]['count'] or 0
    last = cleaned[-1]['count'] or 0
    years = cleaned[-1]['year'] - cleaned[0]['year']

    if first > 0 and years > 0:
        cagr = ((last / first) ** (1 / years) - 1) * 100
    elif first == 0 and last > 0:
        cagr = 100.0
    else:
        cagr = 0.0

    mid = len(cleaned) // 2
    first_base = max(cleaned[0]['count'] or 0, 1)
    second_base = max(cleaned[mid]['count'] or 0, 1)
    first_half_growth = ((cleaned[mid]['count'] or 0) - (cleaned[0]['count'] or 0)) / first_base
    second_half_growth = ((cleaned[-1]['count'] or 0) - (cleaned[mid]['count'] or 0)) / second_base

    if second_half_growth > first_half_growth * 1.2:
        direction = 'accelerating'
    elif second_half_growth > first_half_growth * 0.8:
        direction = 'stable'
    elif second_half_growth > 0:
        direction = 'decelerating'
    else:
        direction = 'declining'

    return {
        'trend_5y_cagr': round(cagr, 2),
        'trend_direction': direction,
        'trend_5y': cleaned,
    }


# ---------------------------------------------------------------------------
# 数据校验
# ---------------------------------------------------------------------------

def validate_patent_data(data: Dict[str, Any]) -> Tuple[bool, str]:
    """校验解析结果合理性, 返回 (is_valid, reason)。"""
    for field in ('total_patents', 'invention_patents', 'utility_patents', 'design_patents'):
        v = data.get(field)
        if v is not None and v < 0:
            return False, f'{field} 不能为负数: {v}'

    inv = data.get('invention_patents') or 0
    util = data.get('utility_patents') or 0
    des = data.get('design_patents') or 0
    total = data.get('total_patents') or 0
    if total > 0 and (inv + util + des) > total * 1.1:
        return False, (f'分项之和({inv}+{util}+{des}={inv + util + des}) '
                       f'超过总数({total})的110%')

    if total > 50000:
        return False, f'专利总数异常偏高: {total} (可能解析错误)'

    ratio = data.get('rd_staff_ratio')
    if ratio is not None and (ratio < 0 or ratio > 100):
        return False, f'rd_staff_ratio 超出范围: {ratio}%'

    inv_ratio = data.get('invention_ratio')
    if inv_ratio is not None and (inv_ratio < 0 or inv_ratio > 100):
        return False, f'invention_ratio 超出范围: {inv_ratio}%'

    import datetime
    year = data.get('year')
    current_year = datetime.date.today().year
    if year is not None and (year < 1990 or year > current_year + 1):
        return False, f'year 超出合理范围: {year}'

    return True, 'OK'


# ---------------------------------------------------------------------------
# 双源合并 (年报 + Google Patents)
# ---------------------------------------------------------------------------

_ANNUAL_PRIORITY_FIELDS = (
    'total_patents', 'invention_patents', 'utility_patents',
    'design_patents', 'new_patents_year', 'rd_staff_count', 'rd_staff_ratio',
    'key_tech_desc',
)
_GOOGLE_ONLY_FIELDS = (
    'avg_citation_count', 'pct_international', 'patent_maintenance_rate',
)


def merge_patent_data(
    annual_report: Optional[Dict[str, Any]],
    google_data: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """合并年报与 Google Patents 数据。年报字段优先, Google 仅补充缺失字段。"""
    if not annual_report and not google_data:
        return {'data_source': None, 'confidence_score': 0}

    annual_report = annual_report or {}
    google_data = google_data or {}
    merged: Dict[str, Any] = {}

    for field in _ANNUAL_PRIORITY_FIELDS:
        merged[field] = annual_report.get(field) or google_data.get(field)

    for field in _GOOGLE_ONLY_FIELDS:
        merged[field] = google_data.get(field)

    merged['ipc_primary'] = annual_report.get('ipc_primary') or google_data.get('ipc_primary')
    merged['ipc_primary_desc'] = (
        annual_report.get('ipc_primary_desc') or google_data.get('ipc_primary_desc')
    )
    merged['ipc_distribution'] = (
        annual_report.get('ipc_distribution') or google_data.get('ipc_distribution')
    )
    merged['tech_domain'] = annual_report.get('tech_domain') or google_data.get('tech_domain')

    # 趋势优先 Google (更精确的年度统计)
    merged['trend_5y'] = google_data.get('trend_5y') or annual_report.get('trend_5y')

    ar_total = annual_report.get('total_patents') or 0
    gp_total = google_data.get('total_patents') or 0
    if ar_total > 0 and gp_total > 0:
        diff_ratio = abs(ar_total - gp_total) / max(ar_total, gp_total)
        if diff_ratio > 0.5:
            merged['_conflict_flag'] = True
            merged['_conflict_detail'] = (
                f'年报={ar_total}, Google={gp_total}, 差异={diff_ratio:.0%}'
            )

    if annual_report and google_data:
        merged['data_source'] = 'mixed'
        merged['confidence_score'] = 85
    elif annual_report:
        merged['data_source'] = 'annual_report'
        merged['confidence_score'] = 95
    else:
        merged['data_source'] = 'google_patents'
        merged['confidence_score'] = 80

    return merged
