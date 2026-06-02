#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""综合选股评分列表 API（M2.3）。

端点：
- GET /quantia/api/selection/score/list
- GET /quantia/api/selection/score/detail
- GET /quantia/api/selection/score/industries
- GET /quantia/api/selection/score/top

本阶段目标：在列表结果中透出 rank_change 是否可比，
当 risk_flags 包含 "rank_change_not_comparable" 时返回 rank_change_comparable=false。
"""

from __future__ import annotations

import json
import logging
import math

import pandas as pd

import quantia.core.selection_scoring as scoring
import quantia.lib.database as mdb
import quantia.web.base as webBase

__author__ = 'Quantia'
__date__ = '2026/06/02'

logger = logging.getLogger(__name__)
SELECTION_SCORE_API_CONTRACT_VERSION = 'm3.8'


def _json_default(o):
    if isinstance(o, float):
        return None if not math.isfinite(o) else o
    if hasattr(o, 'isoformat'):
        return o.isoformat()
    if hasattr(o, 'item'):
        return o.item()
    return str(o)


def _write_json(handler, data):
    handler.set_header('Content-Type', 'application/json;charset=UTF-8')
    handler.write(json.dumps(data, ensure_ascii=False, default=_json_default))


def _with_contract(data: dict, endpoint: str) -> dict:
    """为评分接口响应补充契约版本标识（M3.8）。"""
    out = dict(data)
    out.setdefault('api_contract_version', SELECTION_SCORE_API_CONTRACT_VERSION)
    out.setdefault('api_contract_endpoint', endpoint)
    return out


def _parse_flag_list(risk_flags) -> list[str]:
    if isinstance(risk_flags, list):
        return [str(x) for x in risk_flags if x is not None]
    if not isinstance(risk_flags, str):
        return []
    text = risk_flags.strip()
    if not text:
        return []
    try:
        arr = json.loads(text)
    except Exception:
        return []
    if not isinstance(arr, list):
        return []
    return [str(x) for x in arr if x is not None]


def _rank_change_comparable_from_flags(risk_flags) -> bool:
    flags = _parse_flag_list(risk_flags)
    return 'rank_change_not_comparable' not in flags


def _parse_json_array_field(value):
    """将 JSON 数组字段解析为 list；异常输入返回空列表。"""
    if isinstance(value, list):
        return value
    if not isinstance(value, str):
        return []
    text = value.strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except Exception:
        return []
    return parsed if isinstance(parsed, list) else []


def _normalize_score_row(row: dict, use_view_score: bool = False) -> dict:
    """标准化单条评分记录，补充可比标记与显示分字段。"""
    item = dict(row)
    item['risk_flags'] = _parse_json_array_field(item.get('risk_flags'))
    item['tags'] = _parse_json_array_field(item.get('tags'))
    item['rank_change_comparable'] = _rank_change_comparable_from_flags(item.get('risk_flags'))

    total_score = pd.to_numeric(pd.Series([item.get('total_score')]), errors='coerce').iloc[0]
    total_score_view = pd.to_numeric(pd.Series([item.get('total_score_view')]), errors='coerce').iloc[0]
    if use_view_score and pd.notna(total_score_view):
        item['display_score'] = float(total_score_view)
        item['display_score_source'] = 'total_score_view'
    elif pd.notna(total_score):
        item['display_score'] = float(total_score)
        item['display_score_source'] = 'total_score'
    else:
        item['display_score'] = None
        item['display_score_source'] = 'total_score_view' if use_view_score else 'total_score'

    return item


def _resolve_template_weights(template: str | dict | None) -> dict | None:
    """解析权重模板；balanced/无效模板返回 None。"""
    if template is None:
        return None
    t = str(template).strip().lower()
    if not t or t == 'balanced':
        return None
    try:
        return scoring.resolve_weight_template(template)
    except Exception:
        return None


def _resolve_template_context(template: str | dict | None) -> dict:
    """解析模板请求语义，统一返回请求/生效/回退状态。"""
    requested = str(template).strip().lower() if template is not None else ''
    requested = requested or 'balanced'
    if requested == 'balanced':
        return {
            'template_requested': 'balanced',
            'template_effective': 'balanced',
            'template_fallback': False,
            'view_template_active': False,
        }

    weights = _resolve_template_weights(requested)
    if weights is None:
        return {
            'template_requested': requested,
            'template_effective': 'balanced',
            'template_fallback': True,
            'view_template_active': False,
        }

    return {
        'template_requested': requested,
        'template_effective': requested,
        'template_fallback': False,
        'view_template_active': True,
    }


def _resolve_sort_context(sort: str | None) -> dict:
    """解析列表排序请求，统一返回请求/生效/回退状态。"""
    requested = (str(sort).strip().lower() if sort is not None else '') or 'total_score'
    supported = {'total_score', 'total_score_view', 'quality_score', 'industry_rank'}
    if requested in supported:
        return {
            'sort_requested': requested,
            'sort_effective': requested,
            'sort_fallback': False,
        }
    return {
        'sort_requested': requested,
        'sort_effective': 'total_score',
        'sort_fallback': True,
    }


def _apply_template_total_score(df: pd.DataFrame, template: str | dict | None) -> pd.DataFrame:
    """基于存储维度分实时重加权，产出 `total_score_view`（M3）。"""
    out = df.copy()
    out['total_score_view'] = pd.to_numeric(out.get('total_score'), errors='coerce')
    weights = _resolve_template_weights(template)
    if not weights:
        return out

    comp = pd.DataFrame(index=out.index)
    w_used = []
    dim_to_col = {
        'valuation': 'score_valuation',
        'profitability': 'score_profitability',
        'growth': 'score_growth',
        'health': 'score_health',
        'capital': 'score_capital',
        'technical': 'score_technical',
        'sentiment': 'score_sentiment',
    }
    for dim, col in dim_to_col.items():
        if col in out.columns and dim in weights and float(weights[dim]) > 0:
            comp[col] = pd.to_numeric(out[col], errors='coerce')
            w_used.append((col, float(weights[dim])))
    if not w_used:
        return out

    weighted_sum = pd.Series(0.0, index=out.index)
    valid_weight = pd.Series(0.0, index=out.index)
    for col, w in w_used:
        v = comp[col]
        mask = v.notna()
        weighted_sum.loc[mask] += v.loc[mask] * w
        valid_weight.loc[mask] += w
    view = weighted_sum / valid_weight.where(valid_weight > 0)
    out['total_score_view'] = view.fillna(out['total_score_view']).clip(0, 100)
    return out


def _build_industry_summary_items(df: pd.DataFrame, use_view_score: bool = False) -> list[dict]:
    """按 industry 聚合行业摘要（M2.5/M3.4）。"""
    if df is None or df.empty:
        return []

    data = df.copy()
    if 'industry' not in data.columns:
        return []
    data['industry'] = data['industry'].fillna('其他').replace('', '其他')
    score_col = 'total_score_view' if use_view_score and 'total_score_view' in data.columns else 'total_score'
    score_source = 'total_score_view' if score_col == 'total_score_view' else 'total_score'
    data[score_col] = pd.to_numeric(data.get(score_col), errors='coerce')
    if 'rank_change_comparable' not in data.columns:
        data['rank_change_comparable'] = data.get('risk_flags', '[]').apply(_rank_change_comparable_from_flags)

    items = []
    for industry, g in data.groupby('industry', sort=True):
        g2 = g.sort_values([score_col, 'quality_score'], ascending=[False, False], kind='mergesort')
        leader = g2.iloc[0]
        total = int(len(g2))
        non_comparable = int((~g2['rank_change_comparable'].astype(bool)).sum())
        comparable_ratio = float(g2['rank_change_comparable'].astype(bool).mean()) if total > 0 else 0.0

        item = {
            'industry': str(industry),
            'stock_count': total,
            'avg_total_score': float(pd.to_numeric(g2[score_col], errors='coerce').mean()),
            'avg_quality_score': float(pd.to_numeric(g2['quality_score'], errors='coerce').mean()),
            'leader_code': str(leader.get('code', '')),
            'leader_name': leader.get('name', ''),
            'leader_total_score': float(leader.get(score_col)) if pd.notna(leader.get(score_col)) else None,
            'leader_quality_score': float(leader.get('quality_score')) if pd.notna(leader.get('quality_score')) else None,
            'avg_display_score': float(pd.to_numeric(g2[score_col], errors='coerce').mean()),
            'avg_display_score_source': score_source,
            'leader_display_score': float(leader.get(score_col)) if pd.notna(leader.get(score_col)) else None,
            'leader_display_score_source': score_source,
            'comparable_ratio': comparable_ratio,
            'non_comparable_count': non_comparable,
        }
        if 'score_growth' in g2.columns:
            item['prosperity_score'] = float(pd.to_numeric(g2['score_growth'], errors='coerce').mean())
        items.append(item)

    items.sort(key=lambda x: (-(x.get('avg_total_score') or 0.0), x.get('industry', '')))
    return items


def _build_top_items(df: pd.DataFrame, n: int) -> list[dict]:
    """按 quality_score 固定降序生成 TopN（M2.6）。"""
    if df is None or df.empty:
        return []
    limit = max(1, int(n))
    d = df.copy()
    d['quality_score'] = pd.to_numeric(d.get('quality_score'), errors='coerce')
    d = d.sort_values(['quality_score', 'total_score'], ascending=[False, False], kind='mergesort').head(limit)
    return [_normalize_score_row(row, use_view_score=False) for row in d.to_dict(orient='records')]


def _sort_list_dataframe(df: pd.DataFrame, sort: str, template: str) -> tuple[pd.DataFrame, str, bool]:
    """对 list 查询结果应用排序，返回 (df, sort_by, view_score_active)。"""
    s = (sort or 'total_score').strip().lower()
    template_active = _resolve_template_weights(template) is not None
    out = _apply_template_total_score(df, template)

    # M3.2: 显式支持 sort=total_score_view；兼容旧行为：template!=balanced 且 sort=total_score 时按 view 排序。
    use_view = (s == 'total_score_view') or (s == 'total_score' and template_active)
    if use_view:
        out = out.sort_values(['total_score_view', 'quality_score'], ascending=[False, False], kind='mergesort')
        return out, 'total_score_view', True
    if s == 'quality_score':
        out = out.sort_values(['quality_score', 'total_score'], ascending=[False, False], kind='mergesort')
        return out, 'quality_score', False
    if s == 'industry_rank':
        out = out.sort_values(['industry_rank', 'total_score'], ascending=[True, False], kind='mergesort')
        return out, 'industry_rank', False

    out = out.sort_values(['total_score', 'quality_score'], ascending=[False, False], kind='mergesort')
    return out, 'total_score', False


class SelectionScoreListHandler(webBase.BaseHandler):
    """GET /quantia/api/selection/score/list

    Query:
    - date: 可选，默认最新日期
    - industry: 可选
    - rating: 可选（S/A/B/C/D）
    - min_quality: 可选
    - page/page_size: 分页
    - sort: total_score|total_score_view|quality_score|industry_rank（默认 total_score）
    - template: 可选，list/industries 支持实时重加权视图排序
    """

    _SORT_MAP = {
        'total_score': '`total_score` DESC',
        'quality_score': '`quality_score` DESC',
        'industry_rank': '`industry_rank` ASC',
    }

    def get(self):
        try:
            if not mdb.checkTableIsExist(scoring.SELECTION_SCORE_TABLE):
                _write_json(self, _with_contract({
                    'date': None,
                    'total': 0,
                    'items': [],
                    'warning': 'cn_stock_selection_score 表尚未创建，请先执行 selection_score_job',
                }, 'list'))
                return

            date_arg = self.get_argument('date', default='').strip()
            industry = self.get_argument('industry', default='').strip()
            rating = self.get_argument('rating', default='').strip().upper()
            min_quality_raw = self.get_argument('min_quality', default='').strip()
            sort_raw = self.get_argument('sort', default='total_score').strip()
            sort_ctx = _resolve_sort_context(sort_raw)
            sort_requested = sort_ctx['sort_requested']
            sort_effective = sort_ctx['sort_effective']
            sort_fallback = bool(sort_ctx['sort_fallback'])
            template_raw = self.get_argument('template', default='').strip()
            template_ctx = _resolve_template_context(template_raw)
            template_requested = template_ctx['template_requested']
            template_effective = template_ctx['template_effective']
            template_fallback = bool(template_ctx['template_fallback'])
            template_active = bool(template_ctx['view_template_active'])
            page = max(1, int(self.get_argument('page', default='1')))
            page_size = min(200, max(1, int(self.get_argument('page_size', default='50'))))
            offset = (page - 1) * page_size

            where = []
            params = []

            if date_arg:
                where.append('`date` = %s')
                params.append(date_arg)
            else:
                where.append(f"`date` = (SELECT MAX(`date`) FROM `{scoring.SELECTION_SCORE_TABLE}`)")

            if industry:
                where.append('`industry` = %s')
                params.append(industry)

            if rating in {'S', 'A', 'B', 'C', 'D'}:
                where.append('`rating` = %s')
                params.append(rating)

            if min_quality_raw:
                try:
                    min_quality = float(min_quality_raw)
                    where.append('`quality_score` >= %s')
                    params.append(min_quality)
                except ValueError:
                    pass

            where_sql = (' WHERE ' + ' AND '.join(where)) if where else ''
            order_sql = self._SORT_MAP.get(sort_effective, self._SORT_MAP['total_score'])
            sort_key = sort_effective
            need_python_sort = (sort_key == 'total_score_view') or (template_active and sort_key == 'total_score')

            count_sql = f"SELECT COUNT(*) AS cnt FROM `{scoring.SELECTION_SCORE_TABLE}`{where_sql}"
            data_sql = (
                f"SELECT `date`,`code`,`name`,`industry`,`total_score`,`total_score_raw`,`quality_score`,`industry_score`,"
                f"`rating`,`industry_rank`,`industry_total`,`rank_change_1d`,`data_completeness`,`risk_flags`,`tags`,"
                f"`score_valuation`,`score_profitability`,`score_growth`,`score_health`,`score_capital`,`score_technical`,`score_sentiment` "
                f"FROM `{scoring.SELECTION_SCORE_TABLE}`{where_sql} "
                f"ORDER BY {order_sql} LIMIT %s OFFSET %s"
            )
            data_sql_all = (
                f"SELECT `date`,`code`,`name`,`industry`,`total_score`,`total_score_raw`,`quality_score`,`industry_score`,"
                f"`rating`,`industry_rank`,`industry_total`,`rank_change_1d`,`data_completeness`,`risk_flags`,`tags`,"
                f"`score_valuation`,`score_profitability`,`score_growth`,`score_health`,`score_capital`,`score_technical`,`score_sentiment` "
                f"FROM `{scoring.SELECTION_SCORE_TABLE}`{where_sql}"
            )

            total_df = pd.read_sql(count_sql, con=mdb.engine(), params=tuple(params))
            total = int(total_df.iloc[0]['cnt']) if not total_df.empty else 0

            if need_python_sort:
                df_all = pd.read_sql(data_sql_all, con=mdb.engine(), params=tuple(params))
                df_all, sort_by, view_active = _sort_list_dataframe(df_all, sort_effective, template_effective)
                df = df_all.iloc[offset: offset + page_size].copy()
            else:
                data_params = list(params) + [page_size, offset]
                df = pd.read_sql(data_sql, con=mdb.engine(), params=tuple(data_params))
                df, sort_by, view_active = _sort_list_dataframe(df, sort_effective, template_effective)

            items = []
            for row in df.to_dict(orient='records'):
                items.append(_normalize_score_row(row, use_view_score=view_active))

            date_rows = mdb.executeSqlFetch(
                f"SELECT MAX(`date`) FROM `{scoring.SELECTION_SCORE_TABLE}`"
            )
            latest_date = None
            if date_rows and date_rows[0] and date_rows[0][0] is not None:
                d = date_rows[0][0]
                latest_date = d.isoformat() if hasattr(d, 'isoformat') else str(d)

            _write_json(self, _with_contract({
                'date': latest_date,
                'page': page,
                'page_size': page_size,
                'total': total,
                'template_requested': template_requested,
                'template_used': template_effective,
                'template_effective': template_effective,
                'template_fallback': template_fallback,
                'sort_requested': sort_requested,
                'sort_effective': sort_by,
                'sort_fallback': sort_fallback,
                'sort_by': sort_by,
                'view_score_active': view_active,
                'display_score_field': 'total_score_view' if view_active else 'total_score',
                'items': items,
            }, 'list'))
        except Exception:
            logger.error('SelectionScoreListHandler 查询异常', exc_info=True)
            self.set_status(500)
            _write_json(self, _with_contract({'error': '服务器内部错误'}, 'list'))


class SelectionScoreDetailHandler(webBase.BaseHandler):
    """GET /quantia/api/selection/score/detail

    Query:
    - code: 必填
    - date: 可选，默认该 code 最新评分日期
    """

    def get(self):
        try:
            if not mdb.checkTableIsExist(scoring.SELECTION_SCORE_TABLE):
                _write_json(self, _with_contract({
                    'item': None,
                    'warning': 'cn_stock_selection_score 表尚未创建，请先执行 selection_score_job',
                }, 'detail'))
                return

            code = self.get_argument('code', default='').strip()
            date_arg = self.get_argument('date', default='').strip()
            if not code:
                self.set_status(400)
                _write_json(self, _with_contract({'error': '缺少必填参数: code'}, 'detail'))
                return

            if date_arg:
                sql = (
                    f"SELECT `date`,`code`,`name`,`industry`,`total_score`,`total_score_raw`,`quality_score`,`industry_score`,"
                    f"`rating`,`industry_rank`,`industry_total`,`rank_change_1d`,`data_completeness`,"
                    f"`score_valuation`,`score_profitability`,`score_growth`,`score_health`,`score_capital`,`score_technical`,`score_sentiment`,"
                    f"`risk_penalty`,`risk_flags`,`tags`,`weight_template` "
                    f"FROM `{scoring.SELECTION_SCORE_TABLE}` WHERE `code`=%s AND `date`=%s LIMIT 1"
                )
                params = (code, date_arg)
            else:
                sql = (
                    f"SELECT `date`,`code`,`name`,`industry`,`total_score`,`total_score_raw`,`quality_score`,`industry_score`,"
                    f"`rating`,`industry_rank`,`industry_total`,`rank_change_1d`,`data_completeness`,"
                    f"`score_valuation`,`score_profitability`,`score_growth`,`score_health`,`score_capital`,`score_technical`,`score_sentiment`,"
                    f"`risk_penalty`,`risk_flags`,`tags`,`weight_template` "
                    f"FROM `{scoring.SELECTION_SCORE_TABLE}` WHERE `code`=%s "
                    f"ORDER BY `date` DESC LIMIT 1"
                )
                params = (code,)

            df = pd.read_sql(sql, con=mdb.engine(), params=params)
            if df.empty:
                _write_json(self, _with_contract({'item': None}, 'detail'))
                return

            item = _normalize_score_row(df.to_dict(orient='records')[0])
            _write_json(self, _with_contract({
                'item': item,
                'template_requested': 'balanced',
                'template_effective': 'balanced',
                'template_fallback': False,
                'display_score_field': 'total_score',
                'view_score_active': False,
            }, 'detail'))
        except Exception:
            logger.error('SelectionScoreDetailHandler 查询异常', exc_info=True)
            self.set_status(500)
            _write_json(self, _with_contract({'error': '服务器内部错误'}, 'detail'))


class SelectionScoreIndustriesHandler(webBase.BaseHandler):
    """GET /quantia/api/selection/score/industries

    Query:
    - date: 可选，默认最新评分日期
    - template: 可选，行业卡片按实时重加权总分排序与聚合
    - min_quality: 可选，按 quality_score 过滤
    """

    def get(self):
        try:
            if not mdb.checkTableIsExist(scoring.SELECTION_SCORE_TABLE):
                _write_json(self, _with_contract({
                    'date': None,
                    'count': 0,
                    'items': [],
                    'warning': 'cn_stock_selection_score 表尚未创建，请先执行 selection_score_job',
                }, 'industries'))
                return

            date_arg = self.get_argument('date', default='').strip()
            template_raw = self.get_argument('template', default='').strip()
            template_ctx = _resolve_template_context(template_raw)
            template_requested = template_ctx['template_requested']
            template_effective = template_ctx['template_effective']
            template_fallback = bool(template_ctx['template_fallback'])
            template_active = bool(template_ctx['view_template_active'])
            min_quality_raw = self.get_argument('min_quality', default='').strip()

            where = []
            params = []
            if date_arg:
                where.append('`date` = %s')
                params.append(date_arg)
            else:
                where.append(f"`date` = (SELECT MAX(`date`) FROM `{scoring.SELECTION_SCORE_TABLE}`)")

            if min_quality_raw:
                try:
                    min_quality = float(min_quality_raw)
                    where.append('`quality_score` >= %s')
                    params.append(min_quality)
                except ValueError:
                    pass

            where_sql = (' WHERE ' + ' AND '.join(where)) if where else ''
            sql = (
                f"SELECT `industry`,`code`,`name`,`total_score`,`quality_score`,`score_growth`,`risk_flags` "
                f"FROM `{scoring.SELECTION_SCORE_TABLE}`{where_sql}"
            )
            df = pd.read_sql(sql, con=mdb.engine(), params=tuple(params))
            if df.empty:
                _write_json(self, _with_contract({'date': None, 'count': 0, 'items': []}, 'industries'))
                return

            df['rank_change_comparable'] = df['risk_flags'].apply(_rank_change_comparable_from_flags)
            df = _apply_template_total_score(df, template_effective)
            items = _build_industry_summary_items(df, use_view_score=template_active)

            date_rows = mdb.executeSqlFetch(
                f"SELECT MAX(`date`) FROM `{scoring.SELECTION_SCORE_TABLE}`"
            )
            latest_date = None
            if date_rows and date_rows[0] and date_rows[0][0] is not None:
                d = date_rows[0][0]
                latest_date = d.isoformat() if hasattr(d, 'isoformat') else str(d)

            _write_json(self, _with_contract({
                'date': latest_date,
                'count': len(items),
                'template_requested': template_requested,
                'template_used': template_effective,
                'template_effective': template_effective,
                'template_fallback': template_fallback,
                'view_score_active': template_active,
                'display_score_field': 'total_score_view' if template_active else 'total_score',
                'items': items,
            }, 'industries'))
        except Exception:
            logger.error('SelectionScoreIndustriesHandler 查询异常', exc_info=True)
            self.set_status(500)
            _write_json(self, _with_contract({'error': '服务器内部错误'}, 'industries'))


class SelectionScoreTopHandler(webBase.BaseHandler):
    """GET /quantia/api/selection/score/top

    Query:
    - n: 可选，默认 20，最大 200
    - date: 可选，默认最新评分日期
    - template: 忽略（该接口固定按 quality_score 排序，保证全市场可比）
    """

    def get(self):
        try:
            if not mdb.checkTableIsExist(scoring.SELECTION_SCORE_TABLE):
                _write_json(self, _with_contract({
                    'date': None,
                    'count': 0,
                    'items': [],
                    'warning': 'cn_stock_selection_score 表尚未创建，请先执行 selection_score_job',
                }, 'top'))
                return

            n_raw = self.get_argument('n', default='20').strip()
            date_arg = self.get_argument('date', default='').strip()
            template_raw = self.get_argument('template', default='').strip()
            try:
                n = int(n_raw)
            except (TypeError, ValueError):
                n = 20
            n = min(200, max(1, n))

            where = []
            params = []
            if date_arg:
                where.append('`date` = %s')
                params.append(date_arg)
            else:
                where.append(f"`date` = (SELECT MAX(`date`) FROM `{scoring.SELECTION_SCORE_TABLE}`)")
            where_sql = ' WHERE ' + ' AND '.join(where)

            sql = (
                f"SELECT `date`,`code`,`name`,`industry`,`total_score`,`quality_score`,`industry_score`,`rating`,"
                f"`industry_rank`,`industry_total`,`rank_change_1d`,`risk_flags`,`tags` "
                f"FROM `{scoring.SELECTION_SCORE_TABLE}`{where_sql} "
                f"ORDER BY `quality_score` DESC, `total_score` DESC LIMIT %s"
            )
            df = pd.read_sql(sql, con=mdb.engine(), params=tuple(list(params) + [n]))
            items = _build_top_items(df, n)

            date_rows = mdb.executeSqlFetch(
                f"SELECT MAX(`date`) FROM `{scoring.SELECTION_SCORE_TABLE}`"
            )
            latest_date = None
            if date_rows and date_rows[0] and date_rows[0][0] is not None:
                d = date_rows[0][0]
                latest_date = d.isoformat() if hasattr(d, 'isoformat') else str(d)

            _write_json(self, _with_contract({
                'date': latest_date,
                'count': len(items),
                'items': items,
                'sort_by': 'quality_score',
                'template_requested': str(template_raw).strip().lower() or 'balanced',
                'template_effective': 'balanced',
                'template_fallback': False,
                'display_score_field': 'total_score',
                'view_score_active': False,
                'template_ignored': True,
            }, 'top'))
        except Exception:
            logger.error('SelectionScoreTopHandler 查询异常', exc_info=True)
            self.set_status(500)
            _write_json(self, _with_contract({'error': '服务器内部错误'}, 'top'))
