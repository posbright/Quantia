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
    `code` VARCHAR(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL COMMENT '股票代码',
    `year` INT NOT NULL COMMENT '统计年度',

    `invention_patents` INT DEFAULT NULL COMMENT '发明专利数',
    `utility_patents` INT DEFAULT NULL COMMENT '实用新型专利数',
    `design_patents` INT DEFAULT NULL COMMENT '外观设计专利数',
    `total_patents` INT DEFAULT NULL COMMENT '专利总数',
    `new_patents_year` INT DEFAULT NULL COMMENT '当年新增专利',
    `patent_yoy` FLOAT DEFAULT NULL COMMENT '专利同比增长率(百分比)',

    `invention_ratio` FLOAT DEFAULT NULL COMMENT '发明专利占比(百分比)',
    `patent_quality_score` TINYINT UNSIGNED DEFAULT NULL COMMENT '专利含金量评分(0-100)',
    `avg_citation_count` FLOAT DEFAULT NULL COMMENT '平均被引用次数',
    `pct_international` INT DEFAULT NULL COMMENT 'PCT国际专利数量',
    `core_patents` INT DEFAULT NULL COMMENT '核心专利数',
    `patent_maintenance_rate` FLOAT DEFAULT NULL COMMENT '专利维持率(百分比)',

    `ipc_primary` VARCHAR(20) DEFAULT NULL COMMENT '主IPC分类号',
    `ipc_primary_desc` VARCHAR(100) DEFAULT NULL COMMENT '主IPC中文描述',
    `ipc_distribution` JSON DEFAULT NULL COMMENT 'IPC分布',
    `tech_domain` VARCHAR(50) DEFAULT NULL COMMENT '技术领域归类',

    `trend_5y` JSON DEFAULT NULL COMMENT '近5年申请数列表',
    `trend_5y_cagr` FLOAT DEFAULT NULL COMMENT '5年专利申请复合增长率(百分比)',
    `trend_direction` ENUM('accelerating','stable','decelerating','declining') DEFAULT NULL
        COMMENT '趋势方向',

    `rd_staff_count` INT DEFAULT NULL COMMENT '研发人员数量',
    `rd_staff_ratio` FLOAT DEFAULT NULL COMMENT '研发人员占比(百分比)',

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


# 完整列定义 (除主键 code/year 外)。reconcile_patents_columns 用它对历史精简表
# 做幂等 ALTER ADD，弥补早期 aggregate_patent_data 建表只含 19 列、缺失下列字段
# 导致 stockPatentHandler SELECT 报 1054 的问题。顺序与 _CREATE_SQL 保持一致。
_PATENT_COLUMN_DEFS: List[Tuple[str, str]] = [
    ('invention_patents', "INT DEFAULT NULL COMMENT '发明专利数'"),
    ('utility_patents', "INT DEFAULT NULL COMMENT '实用新型专利数'"),
    ('design_patents', "INT DEFAULT NULL COMMENT '外观设计专利数'"),
    ('total_patents', "INT DEFAULT NULL COMMENT '专利总数'"),
    ('new_patents_year', "INT DEFAULT NULL COMMENT '当年新增专利'"),
    ('patent_yoy', "FLOAT DEFAULT NULL COMMENT '专利同比增长率(百分比)'"),
    ('invention_ratio', "FLOAT DEFAULT NULL COMMENT '发明专利占比(百分比)'"),
    ('patent_quality_score', "TINYINT UNSIGNED DEFAULT NULL COMMENT '专利含金量评分(0-100)'"),
    ('avg_citation_count', "FLOAT DEFAULT NULL COMMENT '平均被引用次数'"),
    ('pct_international', "INT DEFAULT NULL COMMENT 'PCT国际专利数量'"),
    ('core_patents', "INT DEFAULT NULL COMMENT '核心专利数'"),
    ('patent_maintenance_rate', "FLOAT DEFAULT NULL COMMENT '专利维持率(百分比)'"),
    ('ipc_primary', "VARCHAR(20) DEFAULT NULL COMMENT '主IPC分类号'"),
    ('ipc_primary_desc', "VARCHAR(100) DEFAULT NULL COMMENT '主IPC中文描述'"),
    ('ipc_distribution', "JSON DEFAULT NULL COMMENT 'IPC分布'"),
    ('tech_domain', "VARCHAR(50) DEFAULT NULL COMMENT '技术领域归类'"),
    ('trend_5y', "JSON DEFAULT NULL COMMENT '近5年申请数列表'"),
    ('trend_5y_cagr', "FLOAT DEFAULT NULL COMMENT '5年专利申请复合增长率(百分比)'"),
    ('trend_direction',
     "ENUM('accelerating','stable','decelerating','declining') DEFAULT NULL COMMENT '趋势方向'"),
    ('rd_staff_count', "INT DEFAULT NULL COMMENT '研发人员数量'"),
    ('rd_staff_ratio', "FLOAT DEFAULT NULL COMMENT '研发人员占比(百分比)'"),
    ('key_tech_desc', "TEXT COMMENT '核心技术描述'"),
    ('competitive_position', "VARCHAR(200) DEFAULT NULL COMMENT '行业专利排名描述'"),
    ('data_source',
     "ENUM('annual_report','google_patents','mixed') DEFAULT 'annual_report' COMMENT '数据来源'"),
    ('source_detail', "JSON DEFAULT NULL COMMENT '来源明细'"),
    ('confidence_score', "TINYINT UNSIGNED DEFAULT 80 COMMENT '数据可信度(0-100)'"),
    ('created_at', "DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '首次入库时间'"),
    ('updated_at', "DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
]


def reconcile_patents_columns() -> None:
    """对已存在的 cn_stock_patents 表做幂等列补齐。

    历史上 aggregate_patent_data 用精简 DDL 抢先建表（仅 19 列），
    使完整 schema 的 new_patents_year / patent_yoy / core_patents /
    patent_maintenance_rate / ipc_distribution / trend_5y / rd_staff_count /
    competitive_position / data_source / source_detail / created_at 等列缺失，
    导致 stockPatentHandler 的 SELECT 报 1054、fetch_patent_data 写入崩溃。
    本函数比对 INFORMATION_SCHEMA，仅对缺失列执行 ALTER ADD COLUMN。
    """
    import quantia.lib.database as mdb  # 延迟导入
    try:
        rows = mdb.executeSqlFetch(
            "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_NAME=%s AND TABLE_SCHEMA=DATABASE()",
            (PATENTS_TABLE,),
        ) or []
    except Exception as exc:
        _logger.warning('[patent_analytics] 读取列信息失败, 跳过补齐: %s', exc)
        return
    existing = {r[0] for r in rows}
    missing = [(name, ddl) for name, ddl in _PATENT_COLUMN_DEFS if name not in existing]
    if not missing:
        return
    for name, ddl in missing:
        try:
            mdb.executeSql(f"ALTER TABLE `{PATENTS_TABLE}` ADD COLUMN `{name}` {ddl}")
            _logger.info('[patent_analytics] 补齐缺失列 %s.%s', PATENTS_TABLE, name)
        except Exception as exc:
            _logger.warning('[patent_analytics] 补齐列 %s 失败: %s', name, exc)


def ensure_patents_table() -> None:
    """确保 cn_stock_patents 表存在且 schema 完整 (单一权威建表入口)。

    aggregate_patent_data 与 fetch_patent_data 均经此函数建表，
    避免两套 DDL 分叉。表已存在时做幂等列补齐 (reconcile_patents_columns)。
    """
    import quantia.lib.database as mdb  # 延迟导入, 避免单测/无 DB 环境失败
    if not mdb.checkTableIsExist(PATENTS_TABLE):
        mdb.executeSql(_CREATE_SQL)
        _logger.info('[patent_analytics] 已创建表 %s', PATENTS_TABLE)
    else:
        reconcile_patents_columns()


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


# ---------------------------------------------------------------------------
# 行业分位数评分 (§9.7) — 含金量"数量规模"维度的行业校准
# ---------------------------------------------------------------------------

# 计算行业分位数所需的最小样本量；不足时回退到绝对阈值
MIN_INDUSTRY_SAMPLES = 5


def _percentile(sorted_vals: List[float], pct: float) -> float:
    """对升序列表做线性插值求分位数 (pct ∈ [0,100])。"""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    rank = (pct / 100.0) * (len(sorted_vals) - 1)
    low = int(rank)
    high = min(low + 1, len(sorted_vals) - 1)
    frac = rank - low
    return float(sorted_vals[low]) + (float(sorted_vals[high]) - float(sorted_vals[low])) * frac


def percentiles_from_values(values: List[Any]) -> Optional[Dict[str, Any]]:
    """从一组专利数量样本计算 P25/P50/P75/P90。

    样本量不足 MIN_INDUSTRY_SAMPLES 时返回 None（调用方应回退到绝对阈值）。
    """
    nums = sorted(float(v) for v in values if v is not None)
    if len(nums) < MIN_INDUSTRY_SAMPLES:
        return None
    return {
        'p25': round(_percentile(nums, 25), 2),
        'p50': round(_percentile(nums, 50), 2),
        'p75': round(_percentile(nums, 75), 2),
        'p90': round(_percentile(nums, 90), 2),
        'count': len(nums),
    }


def score_by_industry_percentile(total: Any, percentiles: Dict[str, Any]) -> int:
    """按行业内分位数给"数量规模"维度打分 (0-20)。"""
    total = total or 0
    if total >= percentiles['p90']:
        return 20
    if total >= percentiles['p75']:
        return 16
    if total >= percentiles['p50']:
        return 12
    if total >= percentiles['p25']:
        return 8
    return 3


def _score_quantity_absolute(total: Any) -> int:
    """数量规模维度的绝对阈值打分 (0-20)，行业分位数不可用时的回退。"""
    total = total or 0
    if total >= 500:
        return 20
    if total >= 200:
        return 16
    if total >= 100:
        return 12
    if total >= 30:
        return 8
    return 3


def get_industry_patent_percentiles(
    industry: Optional[str], year: Optional[int] = None
) -> Optional[Dict[str, Any]]:
    """查询某行业 total_patents 的 P25/P50/P75/P90 分位数。

    数据来自 cn_stock_patents JOIN cn_stock_selection.industry（每只股票取最新年度）。
    选用 cn_stock_selection 而非 cn_stock_spot 取行业：spot 最新快照 industry 常为空，
    selection 最新交易日 industry 覆盖率 100%。样本不足或表缺失时返回 None。
    属 Analysis 管道，只读 MySQL。
    """
    if not industry:
        return None
    import quantia.lib.database as mdb  # 延迟导入, 保持纯计算函数 DB 无关
    try:
        if year is not None:
            rows = mdb.executeSqlFetch(
                f"""
                SELECT p.total_patents FROM `{PATENTS_TABLE}` p
                JOIN cn_stock_selection sel ON p.code = sel.code COLLATE utf8mb4_general_ci
                WHERE sel.industry = %s AND p.year = %s
                  AND sel.date = (SELECT MAX(date) FROM cn_stock_selection)
                """,
                (industry, year),
            )
        else:
            rows = mdb.executeSqlFetch(
                f"""
                SELECT p.total_patents FROM `{PATENTS_TABLE}` p
                JOIN cn_stock_selection sel ON p.code = sel.code COLLATE utf8mb4_general_ci
                WHERE sel.industry = %s
                  AND sel.date = (SELECT MAX(date) FROM cn_stock_selection)
                  AND p.year = (SELECT MAX(year) FROM `{PATENTS_TABLE}` p2 WHERE p2.code = p.code)
                """,
                (industry,),
            )
    except Exception:
        return None
    return percentiles_from_values([r[0] for r in (rows or [])])


def calculate_patent_quality_score(
    row: Dict[str, Any],
    industry_percentiles: Optional[Dict[str, Any]] = None,
) -> int:
    """综合评估专利含金量 (0-100 分)。

    维度权重: 发明占比(30) + 数量规模(20) + 5年CAGR(20)
              + 平均被引(15) + PCT国际(10) + 维持率(5)
    缺失字段按最低档计分（不抛错）。

    数量规模维度: 若提供 industry_percentiles（§9.7 行业校准），按行业分位数打分；
    否则回退到绝对阈值。
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
    if industry_percentiles and industry_percentiles.get('count', 0) >= MIN_INDUSTRY_SAMPLES:
        score += score_by_industry_percentile(total, industry_percentiles)
    else:
        score += _score_quantity_absolute(total)

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
