#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 3a: 专利数据采集 Job —
    巨潮年报下载 → 解析 → 校验 → 评分 / 趋势 → upsert 入库。

属于 Fetch 管道（见 AGENTS.md 规则 1）。

用法::

    # 全量（最近 5 年）— 谨慎使用，耗时数小时
    python -m quantia.job.fetch_patent_data

    # 单只 / 指定年份
    python -m quantia.job.fetch_patent_data --code 300750 --years 2024,2023,2022

    # 测试模式 (只跑前 N 只)
    python -m quantia.job.fetch_patent_data --limit 5
"""
from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional

cpath_current = os.path.dirname(os.path.dirname(__file__))
cpath = os.path.abspath(os.path.join(cpath_current, os.pardir))
if cpath not in sys.path:
    sys.path.append(cpath)

import quantia.lib.database as mdb
from quantia.core import patent_analytics as pa
from quantia.core.crawling import cninfo_annual_report as cninfo
from quantia.core.crawling import annual_report_parser as parser
from quantia.core.crawling import google_patents_crawler as gpatents
from quantia.core.crawling import epo_ops_crawler as epo

_logger = logging.getLogger(__name__)


def get_stock_list(limit: Optional[int] = None) -> List[str]:
    """从 cn_stock_spot 获取最新 A 股代码列表。"""
    try:
        rows = mdb.executeSqlFetch(
            "SELECT DISTINCT `code` FROM `cn_stock_spot` "
            "WHERE `date` = (SELECT MAX(`date`) FROM `cn_stock_spot`) "
            "AND `code` REGEXP '^[036]' "
            "ORDER BY `code`"
        )
    except Exception as exc:
        _logger.error('[fetch_patent] 获取股票列表失败: %s', exc)
        return []
    if not rows:
        return []
    codes = [r[0] for r in rows]
    if limit:
        codes = codes[:limit]
    _logger.info('[fetch_patent] 共 %d 只待处理', len(codes))
    return codes


def _build_trend_input(code: str, current_year: int, current_total: int) -> List[Dict[str, Any]]:
    """读取该股票历史年份记录, 加上当前年份, 生成 trend_5y 计算输入。"""
    try:
        rows = mdb.executeSqlFetch(
            f"SELECT year, total_patents FROM `{pa.PATENTS_TABLE}` "
            f"WHERE code=%s AND year < %s ORDER BY year DESC LIMIT 4",
            (code, current_year),
        ) or []
    except Exception:
        rows = []
    data: List[Dict[str, Any]] = [
        {'year': r[0], 'count': r[1] or 0} for r in rows if r[1] is not None
    ]
    data.append({'year': current_year, 'count': current_total})
    return data


def process_stock_year(code: str, year: int, force: bool = False) -> Dict[str, Any]:
    """处理单只股票单年: 下载→解析→入库。

    Returns:
        {'code', 'year', 'status': 'ok'/'skipped'/'failed', 'reason'?}
    """
    pdf = cninfo.download_annual_report(code, year, force=force)
    if not pdf:
        return {'code': code, 'year': year, 'status': 'skipped', 'reason': '年报未找到'}

    try:
        data = parser.parse_annual_report(pdf, code=code, year=year)
    except Exception as exc:
        _logger.warning('[fetch_patent] 解析失败 %s/%s: %s', code, year, exc)
        return {'code': code, 'year': year, 'status': 'failed', 'reason': f'parse: {exc}'}

    if not data.get('total_patents'):
        return {'code': code, 'year': year, 'status': 'skipped', 'reason': '未提取到专利数'}

    ok, reason = pa.validate_patent_data(data)
    if not ok:
        _logger.warning('[fetch_patent] 校验失败 %s/%s: %s', code, year, reason)
        return {'code': code, 'year': year, 'status': 'failed', 'reason': reason}

    # 衍生指标
    trend_input = _build_trend_input(code, year, data.get('total_patents') or 0)
    trend = pa.calculate_trend_metrics(trend_input)
    data.update(trend)
    data['patent_quality_score'] = pa.calculate_patent_quality_score(data)

    upsert_patents(data)
    return {'code': code, 'year': year, 'status': 'ok'}


# ---------------------------------------------------------------------------
# Phase 3b: Google Patents 备份源 (增量补充 IPC/引用/趋势/PCT)
# ---------------------------------------------------------------------------

def get_company_names(code: str) -> List[str]:
    """获取用于 Google Patents 搜索的公司名候选 (简称 + 全称)。

    上市公司简称 != 专利申请人全称, 这里尽量给出多个候选以提高命中率。
    数据源: cn_stock_spot.name (简称)。全称需额外数据源, 暂用简称兜底。
    """
    names: List[str] = []
    try:
        rows = mdb.executeSqlFetch(
            "SELECT `name` FROM `cn_stock_spot` WHERE `code`=%s "
            "ORDER BY `date` DESC LIMIT 1",
            (code,),
        ) or []
    except Exception as exc:
        _logger.warning('[fetch_patent] 获取公司名失败 %s: %s', code, exc)
        rows = []
    short = rows[0][0] if rows and rows[0] and rows[0][0] else None
    if short:
        names.append(short)
        # 常见全称后缀, 提高申请人匹配率
        for suffix in ('股份有限公司', '有限公司'):
            names.append(f'{short}{suffix}')
    return names


def _fetch_annual_row(code: str, year: int) -> Optional[Dict[str, Any]]:
    """读取已入库的年报数据行 (用于双源合并基线)。"""
    fields = (
        'total_patents', 'invention_patents', 'utility_patents', 'design_patents',
        'new_patents_year', 'rd_staff_count', 'rd_staff_ratio', 'key_tech_desc',
        'ipc_primary', 'ipc_primary_desc', 'tech_domain',
    )
    cols = ', '.join(f'`{f}`' for f in fields)
    try:
        rows = mdb.executeSqlFetch(
            f"SELECT {cols} FROM `{pa.PATENTS_TABLE}` WHERE code=%s AND year=%s LIMIT 1",
            (code, year),
        ) or []
    except Exception:
        return None
    if not rows:
        return None
    return dict(zip(fields, rows[0]))


def process_google_patents(code: str, year: int) -> Dict[str, Any]:
    """Google Patents 增量采集: 搜索→聚合→与年报合并→入库。

    只补充 Google 擅长字段 (IPC/引用/趋势/PCT), 不覆盖年报权威数量字段。
    """
    names = get_company_names(code)
    if not names:
        return {'code': code, 'year': year, 'status': 'skipped', 'reason': '无公司名'}

    google = gpatents.fetch_and_aggregate(names, years=5)
    if not google:
        return {'code': code, 'year': year, 'status': 'skipped', 'reason': 'Google 无结果'}

    annual = _fetch_annual_row(code, year)
    merged = pa.merge_patent_data(annual, google)
    merged['code'] = code
    merged['year'] = year

    # 衍生指标 (基于合并后数据重算)
    if merged.get('invention_ratio') is None:
        merged['invention_ratio'] = pa.calculate_invention_ratio(merged)
    trend = pa.calculate_trend_metrics(google.get('trend_5y') or [])
    merged['trend_5y'] = trend['trend_5y']
    merged['trend_5y_cagr'] = trend['trend_5y_cagr']
    merged['trend_direction'] = trend['trend_direction']
    merged['patent_quality_score'] = pa.calculate_patent_quality_score(merged)
    today = datetime.date.today()
    quarter_label = f'{today.year}-Q{(today.month - 1) // 3 + 1}'
    merged['source_detail'] = {
        'google_patents': quarter_label,
        **({'annual_report': str(year)} if annual else {}),
    }

    ok, reason = pa.validate_patent_data(merged)
    if not ok:
        _logger.warning('[fetch_patent] Google 校验失败 %s/%s: %s', code, year, reason)
        return {'code': code, 'year': year, 'status': 'failed', 'reason': reason}

    upsert_patents(merged)
    return {'code': code, 'year': year, 'status': 'ok'}


def process_epo_ops(code: str, year: int) -> Dict[str, Any]:
    """EPO OPS 增量采集: 申请人检索→聚合 IPC→与年报合并→入库。

    与 Google 路径同构, 只补充 IPC/趋势/PCT 等结构化维度, 不覆盖年报权威数量。
    缺凭证 (QUANTIA_EPO_OPS_KEY/SECRET) 时 fetch_and_aggregate 返回 {} → skipped。
    """
    if not epo.is_enabled():
        return {'code': code, 'year': year, 'status': 'skipped', 'reason': 'EPO 未配置凭证'}

    names = get_company_names(code)
    if not names:
        return {'code': code, 'year': year, 'status': 'skipped', 'reason': '无公司名'}

    ops = epo.fetch_and_aggregate(names, years=5)
    if not ops:
        return {'code': code, 'year': year, 'status': 'skipped', 'reason': 'EPO 无结果'}

    annual = _fetch_annual_row(code, year)
    merged = pa.merge_patent_data(annual, ops)
    merged['code'] = code
    merged['year'] = year

    if merged.get('invention_ratio') is None:
        merged['invention_ratio'] = pa.calculate_invention_ratio(merged)
    trend = pa.calculate_trend_metrics(ops.get('trend_5y') or [])
    merged['trend_5y'] = trend['trend_5y']
    merged['trend_5y_cagr'] = trend['trend_5y_cagr']
    merged['trend_direction'] = trend['trend_direction']
    merged['patent_quality_score'] = pa.calculate_patent_quality_score(merged)
    today = datetime.date.today()
    quarter_label = f'{today.year}-Q{(today.month - 1) // 3 + 1}'
    merged['source_detail'] = {
        'epo_ops': quarter_label,
        **({'annual_report': str(year)} if annual else {}),
    }

    ok, reason = pa.validate_patent_data(merged)
    if not ok:
        _logger.warning('[fetch_patent] EPO 校验失败 %s/%s: %s', code, year, reason)
        return {'code': code, 'year': year, 'status': 'failed', 'reason': reason}

    upsert_patents(merged)
    return {'code': code, 'year': year, 'status': 'ok'}


_UPSERT_FIELDS = (
    'code', 'year',
    'invention_patents', 'utility_patents', 'design_patents', 'total_patents',
    'new_patents_year', 'patent_yoy',
    'invention_ratio', 'patent_quality_score', 'avg_citation_count',
    'pct_international', 'core_patents', 'patent_maintenance_rate',
    'ipc_primary', 'ipc_primary_desc', 'ipc_distribution', 'tech_domain',
    'trend_5y', 'trend_5y_cagr', 'trend_direction',
    'rd_staff_count', 'rd_staff_ratio',
    'key_tech_desc', 'competitive_position',
    'data_source', 'source_detail', 'confidence_score',
)
_JSON_FIELDS = {'ipc_distribution', 'trend_5y', 'source_detail'}


def upsert_patents(data: Dict[str, Any]) -> None:
    """将解析结果 upsert 到 cn_stock_patents。"""
    if not data.get('code') or data.get('year') is None:
        raise ValueError('upsert_patents 需要非空 code 与 year')
    pa.ensure_patents_table()

    columns: List[str] = []
    placeholders: List[str] = []
    values: List[Any] = []
    updates: List[str] = []
    for field in _UPSERT_FIELDS:
        v = data.get(field)
        if v is None and field not in ('code', 'year'):
            continue
        columns.append(f'`{field}`')
        placeholders.append('%s')
        if field in _JSON_FIELDS and v is not None:
            v = json.dumps(v, ensure_ascii=False, default=str)
        values.append(v)
        if field not in ('code', 'year'):
            updates.append(f'`{field}`=VALUES(`{field}`)')

    sql = (
        f"INSERT INTO `{pa.PATENTS_TABLE}` ({', '.join(columns)}) "
        f"VALUES ({', '.join(placeholders)}) "
        f"ON DUPLICATE KEY UPDATE {', '.join(updates)}"
    )
    mdb.executeSql(sql, tuple(values))


def run(
    codes: Optional[List[str]] = None,
    years: Optional[List[int]] = None,
    limit: Optional[int] = None,
    force: bool = False,
    source: str = 'annual_report',
) -> Dict[str, int]:
    """主流程。

    Args:
        source: 'annual_report' (主源/默认) / 'google_patents' (季度增量) /
                'epo_ops' (EPO 官方 IPC 主备源, 需配置凭证)。
    """
    pa.ensure_patents_table()

    if not codes:
        codes = get_stock_list(limit=limit)
    if not codes:
        _logger.warning('[fetch_patent] 无可处理股票')
        return {'ok': 0, 'skipped': 0, 'failed': 0}

    if not years:
        # 默认采集最近 5 年（财年, 即年份-1）
        today = datetime.date.today()
        last_year = today.year - 1 if today.month >= 5 else today.year - 2
        years = list(range(last_year - 4, last_year + 1))

    stats = {'ok': 0, 'skipped': 0, 'failed': 0}
    for code in codes:
        for year in years:
            if source == 'google_patents':
                r = process_google_patents(code, year)
            elif source == 'epo_ops':
                r = process_epo_ops(code, year)
            else:
                r = process_stock_year(code, year, force=force)
            stats[r['status']] = stats.get(r['status'], 0) + 1
            if r['status'] != 'ok':
                _logger.info('[fetch_patent] %s/%s %s: %s',
                             code, year, r['status'], r.get('reason', ''))
    _logger.info('[fetch_patent] 完成 (source=%s) %s', source, stats)
    return stats


def main():
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(name)s %(message)s')
    ap = argparse.ArgumentParser(description='专利数据采集 Job')
    ap.add_argument('--code', help='单只股票或逗号分隔多只')
    ap.add_argument('--years', help='年份, 逗号分隔, e.g. 2024,2023')
    ap.add_argument('--limit', type=int, default=None, help='测试: 只跑前 N 只股票')
    ap.add_argument('--force', action='store_true', help='强制重新下载年报')
    ap.add_argument('--source',
                    choices=['annual_report', 'google_patents', 'epo_ops'],
                    default='annual_report',
                    help='数据源: annual_report(主源,默认) / google_patents(季度增量) / '
                         'epo_ops(EPO 官方 IPC 主备源, 需 QUANTIA_EPO_OPS_KEY/SECRET)')
    args = ap.parse_args()

    codes = [c.strip() for c in args.code.split(',')] if args.code else None
    years = [int(y) for y in args.years.split(',')] if args.years else None
    stats = run(codes=codes, years=years, limit=args.limit,
                force=args.force, source=args.source)
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except AttributeError:
        pass
    print(f'结果: {stats}')


if __name__ == '__main__':
    main()
