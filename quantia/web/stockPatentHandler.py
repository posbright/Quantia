#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 4: 专利数据查询 API。

提供:
- GET /quantia/api/stock/patents?code=XXX           最新年度数据 + 5 年趋势
- GET /quantia/api/stock/patents/history?code=XXX   多年历史
- GET /quantia/api/stock/patents/compare?code=XXX   同行业对标
"""
from __future__ import annotations

import json
import logging
from abc import ABC
from typing import Any, Dict, List, Optional

from tornado import gen

import quantia.lib.database as mdb
import quantia.web.base as webBase
from quantia.core.patent_analytics import PATENTS_TABLE

_logger = logging.getLogger(__name__)


_LIST_COLUMNS = (
    'code', 'year',
    'total_patents', 'invention_patents', 'utility_patents', 'design_patents',
    'new_patents_year', 'invention_ratio', 'patent_quality_score',
    'avg_citation_count', 'pct_international', 'patent_maintenance_rate',
    'ipc_primary', 'ipc_primary_desc', 'ipc_distribution', 'tech_domain',
    'trend_5y', 'trend_5y_cagr', 'trend_direction',
    'rd_staff_count', 'rd_staff_ratio', 'key_tech_desc',
    'data_source', 'confidence_score', 'updated_at',
)
_JSON_COLUMNS = {'ipc_distribution', 'trend_5y'}


def _write_json(handler, data: Dict[str, Any], status: int = 200) -> None:
    handler.set_status(status)
    handler.set_header('Content-Type', 'application/json; charset=UTF-8')
    handler.write(json.dumps(data, ensure_ascii=False, default=str))


def _row_to_dict(row) -> Dict[str, Any]:
    """将数据库 row 元组按 _LIST_COLUMNS 映射为 dict, 自动解 JSON。"""
    out: Dict[str, Any] = {}
    for col, val in zip(_LIST_COLUMNS, row):
        if col in _JSON_COLUMNS and isinstance(val, (str, bytes)) and val:
            try:
                val = json.loads(val if isinstance(val, str) else val.decode('utf-8'))
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
        out[col] = val
    return out


def _table_exists() -> bool:
    """运行时校验, 表不存在时优雅返回。"""
    try:
        return mdb.checkTableIsExist(PATENTS_TABLE)
    except Exception:
        return False


def _fetch_latest(code: str) -> Optional[Dict[str, Any]]:
    cols = ', '.join(f'`{c}`' for c in _LIST_COLUMNS)
    try:
        rows = mdb.executeSqlFetch(
            f"SELECT {cols} FROM `{PATENTS_TABLE}` WHERE code=%s "
            f"ORDER BY year DESC LIMIT 1",
            (code,),
        )
    except Exception as exc:  # pragma: no cover - depends on live DB
        _logger.warning('[patent] _fetch_latest failed: %s', exc)
        return None
    if not rows:
        return None
    return _row_to_dict(rows[0])


def _fetch_history(code: str, limit: int = 10) -> List[Dict[str, Any]]:
    cols = ', '.join(f'`{c}`' for c in _LIST_COLUMNS)
    try:
        rows = mdb.executeSqlFetch(
            f"SELECT {cols} FROM `{PATENTS_TABLE}` WHERE code=%s "
            f"ORDER BY year DESC LIMIT %s",
            (code, limit),
        ) or []
    except Exception as exc:  # pragma: no cover
        _logger.warning('[patent] _fetch_history failed: %s', exc)
        rows = []
    return [_row_to_dict(r) for r in rows]


class StockPatentsHandler(webBase.BaseHandler, ABC):
    """GET /quantia/api/stock/patents?code=XXX — 最新年度数据。"""

    @gen.coroutine
    def get(self):
        code = (self.get_argument('code', '') or '').strip()
        if not code or len(code) != 6 or not code.isdigit():
            _write_json(self, {'error': 'code 必须是6位数字'}, 400)
            return

        if not _table_exists():
            _write_json(self, {'code': code, 'data': None, 'reason': '专利数据尚未采集'})
            return

        latest = _fetch_latest(code)
        if not latest:
            _write_json(self, {'code': code, 'data': None})
            return

        trend = latest.get('trend_5y') or []
        _write_json(self, {
            'code': code,
            'latest_year': latest.get('year'),
            'data': latest,
            'trend': trend,
            'ipc_distribution': latest.get('ipc_distribution') or {},
        })


class StockPatentsHistoryHandler(webBase.BaseHandler, ABC):
    """GET /quantia/api/stock/patents/history?code=XXX&years=5 — 多年历史。"""

    @gen.coroutine
    def get(self):
        code = (self.get_argument('code', '') or '').strip()
        if not code or len(code) != 6 or not code.isdigit():
            _write_json(self, {'error': 'code 必须是6位数字'}, 400)
            return
        try:
            years = min(20, max(1, int(self.get_argument('years', '5'))))
        except (ValueError, TypeError):
            years = 5

        if not _table_exists():
            _write_json(self, {'code': code, 'items': []})
            return

        items = _fetch_history(code, limit=years)
        _write_json(self, {'code': code, 'items': items, 'count': len(items)})


class StockPatentsCompareHandler(webBase.BaseHandler, ABC):
    """GET /quantia/api/stock/patents/compare?code=XXX — 同行业 TOP 对标。

    返回最新年度同行业按 total_patents 降序前 10 名 + 当前股票的排名。
    """

    @gen.coroutine
    def get(self):
        code = (self.get_argument('code', '') or '').strip()
        if not code or len(code) != 6 or not code.isdigit():
            _write_json(self, {'error': 'code 必须是6位数字'}, 400)
            return

        if not _table_exists():
            _write_json(self, {'code': code, 'industry': None, 'top': [], 'rank': None})
            return

        # 通过 cn_stock_spot.industry 获取行业
        try:
            ind_rows = mdb.executeSqlFetch(
                "SELECT industry FROM cn_stock_spot WHERE code=%s "
                "ORDER BY date DESC LIMIT 1",
                (code,),
            )
        except Exception:
            ind_rows = None
        industry = ind_rows[0][0] if ind_rows and ind_rows[0][0] else None
        if not industry:
            _write_json(self, {'code': code, 'industry': None, 'top': [], 'rank': None})
            return

        rows = mdb.executeSqlFetch(
            f"""
            SELECT p.code, s.name, p.year, p.total_patents,
                   p.invention_patents, p.patent_quality_score, p.tech_domain
            FROM `{PATENTS_TABLE}` p
            JOIN cn_stock_spot s ON p.code = s.code
            WHERE s.industry = %s
              AND s.date = (SELECT MAX(date) FROM cn_stock_spot)
              AND p.year = (SELECT MAX(year) FROM `{PATENTS_TABLE}` p2 WHERE p2.code = p.code)
            ORDER BY p.total_patents DESC
            LIMIT 50
            """,
            (industry,),
        ) or []

        top: List[Dict[str, Any]] = []
        rank: Optional[int] = None
        for i, r in enumerate(rows, start=1):
            entry = {
                'code': r[0], 'name': r[1], 'year': r[2],
                'total_patents': r[3], 'invention_patents': r[4],
                'patent_quality_score': r[5], 'tech_domain': r[6],
            }
            if i <= 10:
                top.append(entry)
            if r[0] == code:
                rank = i

        _write_json(self, {
            'code': code,
            'industry': industry,
            'top': top,
            'rank': rank,
            'total_in_industry': len(rows),
        })
