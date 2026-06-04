#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""基金综合分析与建议 API Handler（F13，§4.6 规则引擎，非投资建议）。

只读 MySQL（Fetch/Analysis/Web 分离）：汇聚 cn_fund_rank / cn_fund_rank_score /
cn_fund_holding / cn_fund_profile，按确定性规则生成结构化解读（历史业绩 /
持仓集中度 / 行业分布 / 风格 / 规模成立 / 风险等级），**不调用 LLM**，
**禁止"买/卖/加仓/减仓"措辞**，与 F11 共享阈值常量（labels.py）。

端点：
- GET /quantia/api/fund/composite_analysis?code=000001
"""

import datetime
import json
import logging
import math

import pandas as pd

import quantia.core.tablestructure as tbs
import quantia.core.fund.scoring as scoring
import quantia.core.fund.labels as labels
import quantia.lib.database as mdb
import quantia.web.base as webBase
import quantia.web.fundPeerCompareHandler as peer

__author__ = 'Quantia'
__date__ = '2026/06/01'

logger = logging.getLogger(__name__)

_RANK_TABLE = tbs.TABLE_CN_FUND_RANK['name']
_SCORE_TABLE = tbs.TABLE_CN_FUND_RANK_SCORE['name']
_HOLDING_TABLE = tbs.TABLE_CN_FUND_HOLDING['name']
_PROFILE_TABLE = tbs.TABLE_CN_FUND_PROFILE['name']


def _num(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
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


def _years_since(setup_date):
    if setup_date is None:
        return None
    try:
        d = pd.to_datetime(setup_date, errors='coerce')
        if pd.isna(d):
            return None
        return round((datetime.date.today() - d.date()).days / 365.25, 1)
    except Exception:
        return None


def build_composite_analysis(ctx):
    """由已落库数据装配结构化综合分析（纯函数，便于单测）。

    ctx: {code, name, fund_type, data_date, rank:{}, score:{}, profile:{},
          holdings:[{industry,hold_ratio},...], peer_percentiles:{}}
    """
    fund_type = ctx.get('fund_type')
    rank = ctx.get('rank') or {}
    score = ctx.get('score') or {}
    profile = ctx.get('profile') or {}
    holdings = ctx.get('holdings') or []
    pct = ctx.get('peer_percentiles') or {}

    # ── 历史业绩 ──
    sharpe = _num(score.get('sharpe'))
    max_dd = _num(score.get('max_drawdown'))
    excess = _num(score.get('excess_1y'))
    perf_texts = []
    rate_3y = _num(rank.get('rate_3y')) if rank.get('rate_3y') is not None else _num(score.get('rate_3y'))
    rate_5y = _num(score.get('rate_5y'))
    rate_1y = _num(rank.get('rate_1y'))
    if rate_1y is not None:
        perf_texts.append(f'近1年收益{rate_1y:.2f}%')
    if rate_3y is not None:
        perf_texts.append(f'近3年累计{rate_3y:.2f}%')
    if rate_5y is not None:
        perf_texts.append(f'近5年累计{rate_5y:.2f}%')
    sharpe_pct = pct.get('sharpe')
    if sharpe is not None:
        if sharpe_pct is not None:
            perf_texts.append(f'夏普{sharpe:.2f}（同类前{max(1, int(round(100 - sharpe_pct)))}%）')
        else:
            perf_texts.append(f'夏普{sharpe:.2f}')
    dd_pct = pct.get('drawdown')
    if max_dd is not None:
        if dd_pct is not None:
            perf_texts.append(f'最大回撤{abs(max_dd) * 100:.1f}%（抗跌优于同类{int(round(dd_pct))}%）')
        else:
            perf_texts.append(f'最大回撤{abs(max_dd) * 100:.1f}%')
    if excess is not None:
        if excess >= 0:
            perf_texts.append(f'近1年跑赢对照基线(同类平均){excess:.2f}%')
        else:
            perf_texts.append(f'近1年落后对照基线(同类平均){abs(excess):.2f}%')

    # ── 持仓集中度 + 行业分布 ──
    conc_sum = None
    industry_dist = []
    main_industry = score.get('main_industry')
    if holdings:
        hdf = pd.DataFrame(holdings)
        if 'hold_ratio' in hdf.columns:
            hdf['hold_ratio'] = pd.to_numeric(hdf['hold_ratio'], errors='coerce').fillna(0.0)
            conc_sum = float(hdf['hold_ratio'].sum())
            if 'industry' in hdf.columns:
                hdf['industry'] = hdf['industry'].fillna('未分类')
                grp = (hdf.groupby('industry', as_index=False)['hold_ratio'].sum()
                       .sort_values('hold_ratio', ascending=False))
                industry_dist = [{'industry': r['industry'], 'ratio': round(float(r['hold_ratio']), 2)}
                                 for _, r in grp.iterrows()]
                if not main_industry and industry_dist:
                    main_industry = industry_dist[0]['industry']
    conc_level, conc_text = labels.concentration_label(conc_sum)

    industry_text = None
    if industry_dist:
        top = industry_dist[0]
        n_ind = len(industry_dist)
        if n_ind <= 2:
            industry_text = f'重仓集中于{top["industry"]}（占前十大{top["ratio"]:.1f}%）'
        else:
            industry_text = f'主配{top["industry"]}，分散于{n_ind}个行业'

    # ── 风格 ──
    fund_type_detail = profile.get('fund_type_detail')
    style_map = {'股票型': '偏股', '指数型': '偏股(指数)', '混合型': '股债均衡',
                 '债券型': '偏债', '货币型': '货币', 'QDII': '跨境', 'FOF': '基金组合'}
    style_text = style_map.get(fund_type, fund_type)
    if fund_type_detail:
        style_text = f'{fund_type_detail}（{style_text}）'

    # ── 规模 / 成立 ──
    scale_yi = _num(profile.get('scale_yi'))
    setup_date = profile.get('setup_date')
    years = _years_since(setup_date)
    scale_texts = []
    if scale_yi is not None:
        if scale_yi < 0.5:
            scale_texts.append(f'规模{scale_yi:.2f}亿，偏小需留意清盘风险')
        elif scale_yi > 200:
            scale_texts.append(f'规模{scale_yi:.1f}亿，体量较大调仓灵活度受限')
        else:
            scale_texts.append(f'规模{scale_yi:.2f}亿，体量适中')
    if years is not None:
        if years >= 3:
            scale_texts.append(f'成立满{years:.1f}年，具备完整市场周期')
        else:
            scale_texts.append(f'成立{years:.1f}年，历史区间较短')

    # ── 持仓明细（前十大重仓股，按占比降序）──
    top_holdings = []
    quarter = None
    if holdings:
        for h in holdings:
            r = _num(h.get('hold_ratio'))
            if h.get('quarter') and not quarter:
                quarter = h.get('quarter')
            if h.get('name'):
                top_holdings.append({
                    'name': h.get('name'),
                    'stock_code': h.get('stock_code'),
                    'industry': h.get('industry') or '未分类',
                    'hold_ratio': r,
                })
        top_holdings.sort(key=lambda x: (x['hold_ratio'] is None, -(x['hold_ratio'] or 0)))
        top_holdings = top_holdings[:10]

    # ── 风险等级 ──
    level = labels.risk_level(max_drawdown=max_dd, concentration=conc_sum,
                              fund_type=fund_type, sharpe=sharpe)

    # ── 一句话总结 ──
    score_tier = labels.tier_label(_num(score.get('score')))
    summary_bits = []
    if score_tier:
        summary_bits.append(f'综合评分同类{score_tier}')
    if conc_level == 'concentrated':
        summary_bits.append('持仓集中')
    elif conc_level == 'dispersed':
        summary_bits.append('持仓分散')
    summary_bits.append(f'风险等级{level}')
    summary = '；'.join(summary_bits) if summary_bits else '数据有限，暂无足够维度生成总结'

    return {
        'code': ctx.get('code'),
        'name': ctx.get('name'),
        'fund_type': fund_type,
        'data_date': ctx.get('data_date'),
        'performance': {
            'rate_1y': rate_1y, 'rate_3y': rate_3y, 'rate_5y': rate_5y,
            'sharpe': sharpe, 'max_drawdown': max_dd, 'excess_1y': excess,
            'sharpe_pct': sharpe_pct, 'drawdown_pct': dd_pct,
            'texts': perf_texts,
        },
        'concentration': {'top10_sum': conc_sum, 'level': conc_level, 'text': conc_text},
        'industry': {'main_industry': main_industry, 'distribution': industry_dist,
                     'text': industry_text},
        'style': {'fund_type_detail': fund_type_detail, 'text': style_text},
        'scale': {'scale_yi': scale_yi, 'setup_date': setup_date, 'years': years,
                  'texts': scale_texts},
        'profile': {
            'company': profile.get('company'),
            'manager': profile.get('manager'),
            'rating': profile.get('rating'),
            'fund_type_detail': fund_type_detail,
            'strategy': profile.get('strategy'),
            'objective': profile.get('objective'),
            'benchmark': profile.get('benchmark'),
            'setup_date': setup_date,
        },
        'holdings': {'quarter': quarter, 'top': top_holdings},
        'risk_level': level,
        'summary': summary,
        'disclaimer': labels.RISK_DISCLAIMER,
    }


def _fetch_one(table, cols, where_code, code, extra_latest_date=None, table_exists=None):
    """读单行 dict（最新快照日，可选）。表不存在返回 {}。"""
    if table_exists is False:
        return {}
    col_sql = ', '.join(f'`{c}`' for c in cols)
    sql = f"SELECT {col_sql} FROM `{table}` WHERE `{where_code}` = %s"
    if extra_latest_date:
        sql += f" AND `date` = (SELECT MAX(`date`) FROM `{table}`)"
    sql += " LIMIT 1"
    rows = mdb.executeSqlFetch(sql, (str(code),))
    if not rows or not rows[0]:
        return {}
    return dict(zip(cols, rows[0]))


class FundCompositeAnalysisHandler(webBase.BaseHandler):
    """GET /quantia/api/fund/composite_analysis?code=xxx

    汇聚已落库数据，规则化生成结构化综合分析（确定性、非投资建议）。
    """

    def get(self):
        try:
            code = (self.get_argument('code', default='') or '').strip()
            if not code:
                _write_error(self, '缺少 code 参数')
                return
            table_presence = mdb.checkTablesExist([
                _RANK_TABLE, _SCORE_TABLE, _HOLDING_TABLE, _PROFILE_TABLE
            ])
            if not table_presence.get(_RANK_TABLE, False):
                _write_error(self, '基金数据尚未就绪', 503)
                return

            rank = _fetch_one(
                _RANK_TABLE,
                ['name', 'fund_type', 'nav_date', 'rate_1y', 'rate_3y'],
                'code', code, extra_latest_date=True,
                table_exists=table_presence.get(_RANK_TABLE))
            if not rank:
                _write_error(self, f'未找到基金 {code} 的最新数据', 404)
                return
            fund_type = rank.get('fund_type')
            name = rank.get('name')

            score = _fetch_one(
                _SCORE_TABLE,
                ['score', 'sharpe', 'max_drawdown', 'rate_3y', 'rate_5y',
                 'excess_1y', 'main_industry', 'rank_in_type'],
                'code', code, extra_latest_date=True,
                table_exists=table_presence.get(_SCORE_TABLE))
            profile = _fetch_one(
                _PROFILE_TABLE,
                ['fund_type_detail', 'scale_yi', 'setup_date', 'company',
                 'manager', 'rating', 'strategy', 'objective', 'benchmark'],
                'code', code,
                table_exists=table_presence.get(_PROFILE_TABLE))

            holdings = []
            if table_presence.get(_HOLDING_TABLE, False):
                hrows = mdb.executeSqlFetch(
                    f"SELECT `stock_name`, `stock_code`, `industry`, `hold_ratio`, `quarter` "
                    f"FROM `{_HOLDING_TABLE}` WHERE `code` = %s", (str(code),))
                holdings = [{'name': r[0], 'stock_code': r[1], 'industry': r[2],
                             'hold_ratio': r[3], 'quarter': r[4]} for r in (hrows or [])]

            # 同类桶分位（夏普/抗跌的「同类前 Z%」需桶内对标）
            peer_percentiles = {}
            if fund_type and table_presence.get(_SCORE_TABLE, False):
                bucket = pd.read_sql(
                    f"SELECT r.`code` AS code, r.`rate_1y` AS rate_1y, r.`fee` AS fee, "
                    f"       s.`sharpe` AS sharpe, s.`max_drawdown` AS max_drawdown, "
                    f"       p.`scale_yi` AS scale_yi "
                    f"FROM `{_RANK_TABLE}` r "
                    f"LEFT JOIN `{_SCORE_TABLE}` s "
                    f"  ON s.`code` = r.`code` AND s.`date` = (SELECT MAX(`date`) FROM `{_SCORE_TABLE}`) "
                    f"LEFT JOIN `{_PROFILE_TABLE}` p ON p.`code` = r.`code` "
                    f"WHERE r.`date` = (SELECT MAX(`date`) FROM `{_RANK_TABLE}`) "
                    f"  AND r.`fund_type` = %s",
                    con=mdb.engine(), params=(fund_type,))
                if not bucket.empty:
                    peer_percentiles = peer.compute_peer_dims(bucket, code)['percentiles']

            ctx = {
                'code': code, 'name': name, 'fund_type': fund_type,
                'data_date': rank.get('nav_date'),
                'rank': rank, 'score': score, 'profile': profile,
                'holdings': holdings, 'peer_percentiles': peer_percentiles,
            }
            _write_json(self, build_composite_analysis(ctx))
        except Exception:
            logger.error("基金综合分析异常", exc_info=True)
            _write_error(self, '服务器内部错误', 500)
