#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同类基金评比 API Handler（F11，§4.5 同类评比 + 投资价值分析）。

只读 MySQL（Fetch/Analysis/Web 分离）：给定 code，定位其 fund_type 桶，
在桶内做 5 维截面百分位对标（收益/抗跌/稳定/成本/规模），输出目标基金 vs
同类中位的雷达数据 + 规则化投资价值标签（非投资建议）。

端点：
- GET /quantia/api/fund/peer_compare?code=000001
- GET /quantia/api/fund/peer_compare?code=000001&industry=医药生物
  传 industry 时，桶收窄为同 fund_type + 同主行业（main_industry），
  百分位改为行业内相对（需评分表就绪，main_industry 存于评分表）。
"""

import json
import logging
import math

import pandas as pd

import quantia.core.tablestructure as tbs
import quantia.core.fund.scoring as scoring
import quantia.core.fund.labels as labels
import quantia.lib.database as mdb
import quantia.web.base as webBase

__author__ = 'Quantia'
__date__ = '2026/06/01'

logger = logging.getLogger(__name__)

_RANK_TABLE = tbs.TABLE_CN_FUND_RANK['name']
_SCORE_TABLE = tbs.TABLE_CN_FUND_RANK_SCORE['name']
_PROFILE_TABLE = tbs.TABLE_CN_FUND_PROFILE['name']

# 雷达 5 维（key → 中文标签）
_DIM_LABELS = [
    ('return', '收益'),
    ('drawdown', '抗跌'),
    ('sharpe', '稳定'),
    ('fee', '成本'),
    ('scale', '规模'),
]
_PEER_BASELINE = 50.0  # 同类中位百分位基线


def _finite(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return v
    return None if not math.isfinite(f) else f


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


def _write_error(handler, msg, code=400):
    handler.set_status(code)
    _write_json(handler, {'error': msg})


def _col(df, name):
    """取列；列缺失（评分/画像表未就绪时被省略）→ 全 NaN 序列，避免崩溃。"""
    if name in df.columns:
        return df[name]
    return pd.Series([float('nan')] * len(df.index), index=df.index)


def compute_peer_dims(bucket_df, code):
    """桶内 5 维截面百分位 + 目标基金分位（纯函数，便于单测）。

    bucket_df 列：code, rate_1y, fee, sharpe, max_drawdown, scale_yi。
    缺失列（评分/画像表未就绪）按全 NaN 处理，对应维度取中性基线。
    返回 {dims: [{key,label,value,peer}], percentiles: {...}, peer_count}。
    """
    df = bucket_df.copy()
    df['code'] = df['code'].astype(str)
    code = str(code)

    # 各维桶内百分位（越大越好）
    pct = pd.DataFrame({'code': df['code']})
    pct['return'] = scoring.cross_sectional_pct_rank(_col(df, 'rate_1y'))
    # 抗跌：max_drawdown 为负，越接近 0 越好 → 直接排序（升序分位）即可
    pct['drawdown'] = scoring.cross_sectional_pct_rank(_col(df, 'max_drawdown'))
    pct['sharpe'] = scoring.cross_sectional_pct_rank(_col(df, 'sharpe'))
    pct['fee'] = 100.0 - scoring.cross_sectional_pct_rank(_col(df, 'fee'))
    pct['scale'] = scoring.scale_inverted_u(_col(df, 'scale_yi'))

    row = pct[pct['code'] == code]
    percentiles = {}
    dims = []
    for key, label in _DIM_LABELS:
        v = None
        if not row.empty:
            v = _finite(row.iloc[0].get(key))
        percentiles[key] = v
        dims.append({'key': key, 'label': label, 'value': v, 'peer': _PEER_BASELINE})
    return {'dims': dims, 'percentiles': percentiles, 'peer_count': int(len(df.index))}


class FundPeerCompareHandler(webBase.BaseHandler):
    """GET /quantia/api/fund/peer_compare?code=xxx

    返回目标基金在同 fund_type 桶内的 5 维雷达分位 + 投资价值标签。
    """

    def get(self):
        try:
            code = (self.get_argument('code', default='') or '').strip()
            industry = (self.get_argument('industry', default='') or '').strip()
            if not code:
                _write_error(self, '缺少 code 参数')
                return
            table_presence = mdb.checkTablesExist([_RANK_TABLE, _SCORE_TABLE, _PROFILE_TABLE])
            if not table_presence.get(_RANK_TABLE, False):
                _write_error(self, '基金数据尚未就绪', 503)
                return

            # 定位目标基金类型 + 名称（最新快照日）
            meta = mdb.executeSqlFetch(
                f"SELECT `name`, `fund_type` FROM `{_RANK_TABLE}` "
                f"WHERE `code` = %s AND `date` = (SELECT MAX(`date`) FROM `{_RANK_TABLE}`) "
                f"LIMIT 1", (code,))
            if not meta or not meta[0]:
                _write_error(self, f'未找到基金 {code} 的最新数据', 404)
                return
            name, fund_type = meta[0][0], meta[0][1]

            # 同类桶：rank(rate_1y,fee) 必有；score(sharpe,max_drawdown) / profile(scale_yi)
            # 为可选表，缺失（如评分/画像 job 未就绪）时跳过对应 JOIN，避免整条查询失败。
            has_score = table_presence.get(_SCORE_TABLE, False)
            has_profile = table_presence.get(_PROFILE_TABLE, False)
            select_parts = ['r.`code` AS code', 'r.`rate_1y` AS rate_1y', 'r.`fee` AS fee']
            joins = ''
            if has_score:
                select_parts += ['s.`sharpe` AS sharpe', 's.`max_drawdown` AS max_drawdown']
                joins += (
                    f" LEFT JOIN `{_SCORE_TABLE}` s "
                    f"  ON s.`code` = r.`code` "
                    f"  AND s.`date` = (SELECT MAX(`date`) FROM `{_SCORE_TABLE}`)")
            if has_profile:
                select_parts += ['p.`scale_yi` AS scale_yi']
                joins += f" LEFT JOIN `{_PROFILE_TABLE}` p ON p.`code` = r.`code`"
            where = (
                f"WHERE r.`date` = (SELECT MAX(`date`) FROM `{_RANK_TABLE}`) "
                f"  AND r.`fund_type` = %s"
            )
            params = [fund_type]
            # 同行业对标：仅在评分表就绪时生效（main_industry 存于评分表）。
            # 加 s.main_industry 过滤后，桶 = 同 fund_type + 同行业，百分位变为行业内相对。
            applied_industry = None
            if industry and has_score:
                where += " AND s.`main_industry` = %s"
                params.append(industry)
                applied_industry = industry
            sql = (
                f"SELECT {', '.join(select_parts)} "
                f"FROM `{_RANK_TABLE}` r{joins} "
                f"{where}"
            )
            bucket = pd.read_sql(sql, con=mdb.engine(), params=tuple(params))
            if bucket.empty:
                _write_error(self, f'同类桶 {fund_type} 无数据', 404)
                return

            result = compute_peer_dims(bucket, code)
            value_tags = labels.value_labels(result['percentiles'])

            _write_json(self, {
                'code': code,
                'name': name,
                'fund_type': fund_type,
                'industry': applied_industry,
                'peer_count': result['peer_count'],
                'dims': result['dims'],
                'percentiles': result['percentiles'],
                'value_labels': value_tags,
                'disclaimer': labels.RISK_DISCLAIMER,
            })
        except Exception:
            logger.error("基金同类评比异常", exc_info=True)
            _write_error(self, '服务器内部错误', 500)
