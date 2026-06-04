#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""基金 AI 按需分析 API Handler（F14，§4.7 懒加载 LLM 综合分析）。

设计要点（务必遵循 AGENTS 管道分离 + 验证优先）：
- **Web 管道**：本 handler 不抓取行情原始数据，只读 MySQL 已落库数据
  （cn_fund_rank / cn_fund_rank_score / cn_fund_holding / cn_fund_profile），
  把结构化数字交给 LLM；唯一的"外部访问"是 AI 运行时的 `web_search` 工具
  （AI runtime，非 fetch 管道），且只用于检索近期资讯、不落地行情数据。
- **缓存**：按 (code, data_date) 缓存到 cn_fund_ai_analysis，命中直接返回，
  避免重复花费 token。data_date 取 rank 快照日。
- **降级**：功能开关关闭 / LLM 异常 / 无 provider 时，回退到 F13 规则化
  综合分析（`composite`），并标注 ai_available=False，前端照常可用。
- 数字全部来自落库数据，prompt 明确禁止 LLM 篡改/预测/荐买。

端点：
- POST /quantia/api/fund/ai_analysis        body: {"code": "000001", "refresh": false}
- GET  /quantia/api/fund/ai_analysis?code=  仅查缓存（命中返回，未命中 ai_available=False）
"""

import datetime
import json
import logging
import math

import pandas as pd

import quantia.core.tablestructure as tbs
import quantia.lib.database as mdb
import quantia.web.base as webBase
import quantia.web.fundCompositeAnalysisHandler as cah
import quantia.web.fundPeerCompareHandler as peer

__author__ = 'Quantia'
__date__ = '2026/06/01'

logger = logging.getLogger(__name__)

_AI_TABLE = tbs.TABLE_CN_FUND_AI_ANALYSIS['name']
_RANK_TABLE = tbs.TABLE_CN_FUND_RANK['name']
_SCORE_TABLE = tbs.TABLE_CN_FUND_RANK_SCORE['name']
_HOLDING_TABLE = tbs.TABLE_CN_FUND_HOLDING['name']
_PROFILE_TABLE = tbs.TABLE_CN_FUND_PROFILE['name']

_SCENE = 'fund_analyst'
_FEATURE = 'fund_ai_analysis'
_PROMPT_NAME = 'fund_analyst'


# ── JSON / 数值工具（与 cah 保持一致）─────────────────────────────────────────

def _num(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if not math.isfinite(f) else f


def _write_json(handler, data):
    handler.set_header('Content-Type', 'application/json;charset=UTF-8')
    handler.write(json.dumps(data, ensure_ascii=False, default=cah._json_default))


def _write_error(handler, msg, code=400):
    handler.set_status(code)
    _write_json(handler, {'error': msg})


def _norm_date(d):
    """把 nav_date / 任意日期表达统一成 datetime.date；失败回退今天。"""
    if d is None:
        return datetime.date.today()
    try:
        ts = pd.to_datetime(d, errors='coerce')
        if pd.isna(ts):
            return datetime.date.today()
        return ts.date()
    except Exception:
        return datetime.date.today()


# ── 数据装配 ──────────────────────────────────────────────────────────────────

def gather_ctx(code, table_presence=None):
    """读取该基金已落库数据，返回 (ctx, composite, table_presence)。

    复用 F13 (cah) 的取数与规则装配，避免重复 SQL。
    基金数据表缺失或无该基金最新数据时返回 (None, None)。
    """
    if table_presence is None:
        table_presence = mdb.checkTablesExist([
            _AI_TABLE, _RANK_TABLE, _SCORE_TABLE, _HOLDING_TABLE, _PROFILE_TABLE
        ])
    if not table_presence.get(_RANK_TABLE, False):
        return None, None, table_presence

    rank = cah._fetch_one(
        _RANK_TABLE,
        ['name', 'fund_type', 'nav_date', 'rate_1y', 'rate_3y'],
        'code', code, extra_latest_date=True,
        table_exists=table_presence.get(_RANK_TABLE))
    if not rank:
        return None, None, table_presence

    fund_type = rank.get('fund_type')
    name = rank.get('name')

    score = cah._fetch_one(
        _SCORE_TABLE,
        ['score', 'sharpe', 'max_drawdown', 'rate_3y', 'rate_5y',
         'excess_1y', 'main_industry', 'rank_in_type'],
        'code', code, extra_latest_date=True,
        table_exists=table_presence.get(_SCORE_TABLE))
    profile = cah._fetch_one(
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

    peer_percentiles = {}
    if fund_type and table_presence.get(_SCORE_TABLE, False):
        try:
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
        except Exception:
            logger.warning("基金 AI 分析：同类分位计算失败（忽略）", exc_info=True)

    ctx = {
        'code': code, 'name': name, 'fund_type': fund_type,
        'data_date': rank.get('nav_date'),
        'rank': rank, 'score': score, 'profile': profile,
        'holdings': holdings, 'peer_percentiles': peer_percentiles,
    }
    composite = cah.build_composite_analysis(ctx)
    return ctx, composite, table_presence


def build_user_message(ctx, composite):
    """纯函数：把结构化落库数据拼成给 LLM 的 user prompt（只给数字，不给结论）。"""
    code = ctx.get('code')
    name = ctx.get('name') or ''
    fund_type = ctx.get('fund_type') or '未知'
    profile = ctx.get('profile') or {}
    perf = composite.get('performance') or {}
    conc = composite.get('concentration') or {}
    industry = composite.get('industry') or {}
    scale = composite.get('scale') or {}

    lines = [
        f'请分析以下场外开放式基金（数据快照日 {ctx.get("data_date")}）：',
        '',
        f'- 基金代码：{code}',
        f'- 基金名称：{name}',
        f'- 基金类型：{fund_type}',
    ]
    manager = profile.get('manager')
    company = profile.get('company')
    if manager:
        lines.append(f'- 基金经理：{manager}')
    if company:
        lines.append(f'- 基金公司：{company}')

    lines.append('')
    lines.append('【历史业绩与风险（已落库，禁止改写）】')
    perf_map = [
        ('近1年收益率(%)', perf.get('rate_1y')),
        ('近3年累计收益率(%)', perf.get('rate_3y')),
        ('近5年累计收益率(%)', perf.get('rate_5y')),
        ('夏普比率', perf.get('sharpe')),
        ('最大回撤(小数)', perf.get('max_drawdown')),
        ('近1年对同类平均超额(%)', perf.get('excess_1y')),
    ]
    for label_txt, val in perf_map:
        v = _num(val)
        lines.append(f'- {label_txt}：{"暂无" if v is None else round(v, 4)}')
    if perf.get('sharpe_pct') is not None:
        lines.append(f'- 夏普同类分位(百分位，越大越好)：{round(_num(perf.get("sharpe_pct")) or 0, 1)}')
    if perf.get('drawdown_pct') is not None:
        lines.append(f'- 抗跌同类分位(百分位，越大越抗跌)：{round(_num(perf.get("drawdown_pct")) or 0, 1)}')

    lines.append('')
    lines.append('【持仓与行业（前十大重仓，已落库）】')
    top10 = _num(conc.get('top10_sum'))
    lines.append(f'- 前十大重仓合计占比(%)：{"暂无" if top10 is None else round(top10, 2)}（{conc.get("text")}）')
    if industry.get('main_industry'):
        lines.append(f'- 主配行业：{industry.get("main_industry")}')
    dist = industry.get('distribution') or []
    if dist:
        top_inds = '、'.join(f'{d["industry"]}{d["ratio"]:.1f}%' for d in dist[:5])
        lines.append(f'- 行业分布(前5)：{top_inds}')
    holdings = ctx.get('holdings') or []
    named = [h for h in holdings if h.get('name')]
    if named:
        try:
            named_sorted = sorted(
                named, key=lambda h: _num(h.get('hold_ratio')) or 0, reverse=True)
        except Exception:
            named_sorted = named
        top_stocks = '、'.join(
            f'{h["name"]}({_num(h.get("hold_ratio")) or 0:.1f}%)' for h in named_sorted[:10])
        lines.append(f'- 前十大重仓股：{top_stocks}')

    lines.append('')
    lines.append('【规模与成立（已落库）】')
    scale_yi = _num(scale.get('scale_yi'))
    lines.append(f'- 最新规模(亿元)：{"暂无" if scale_yi is None else round(scale_yi, 2)}')
    if scale.get('years') is not None:
        lines.append(f'- 成立年限(年)：{scale.get("years")}')
    if scale.get('setup_date'):
        lines.append(f'- 成立日期：{scale.get("setup_date")}')

    lines.append('')
    lines.append(f'【规则引擎初判（供参考，可在分析中印证）】风险等级：{composite.get("risk_level")}；'
                 f'综合解读：{composite.get("summary")}')
    lines.append('')
    lines.append('请用 web_search 检索该基金 / 基金经理 / 主要重仓股的近期资讯（近一个月为主），'
                 '并严格按系统提示词的五段结构输出。所有数字只能引用上文给定值，'
                 '不得预测涨跌、不得出现买卖建议。')
    return '\n'.join(lines)


def _extract_sources(tool_calls):
    """从 web_search 工具调用结果里抽取 {title, url} 列表（去重）。"""
    sources = []
    seen = set()
    for tc in tool_calls or []:
        if tc.get('name') != 'web_search' or not tc.get('ok'):
            continue
        res = tc.get('result') or {}
        for item in (res.get('results') or []):
            url = (item.get('url') or '').strip()
            if not url or url in seen:
                continue
            seen.add(url)
            sources.append({'title': (item.get('title') or '').strip(), 'url': url})
    return sources


# ── 缓存读写 ──────────────────────────────────────────────────────────────────

def _load_cache(code, data_date, table_exists=None):
    """命中返回 {content, sources, model, created_at}，否则 None。"""
    if table_exists is False:
        return None
    rows = mdb.executeSqlFetch(
        f"SELECT `content`, `sources`, `model`, `created_at` FROM `{_AI_TABLE}` "
        f"WHERE `code` = %s AND `data_date` = %s LIMIT 1",
        (str(code), data_date))
    if not rows or not rows[0]:
        return None
    content, sources_raw, model, created_at = rows[0]
    try:
        sources = json.loads(sources_raw) if sources_raw else []
    except (ValueError, TypeError):
        sources = []
    return {'content': content, 'sources': sources, 'model': model,
            'created_at': created_at}


def _save_cache(code, data_date, content, sources, model, table_exists=None):
    """按主键 (code, data_date) 覆盖写缓存。失败仅告警不抛。"""
    try:
        df = pd.DataFrame([{
            'code': str(code),
            'data_date': data_date,
            'content': content or '',
            'sources': json.dumps(sources or [], ensure_ascii=False),
            'model': (model or '')[:40],
            'created_at': datetime.datetime.now(),
        }])
        if table_exists is True:
            try:
                mdb.executeSql(
                    f"DELETE FROM `{_AI_TABLE}` WHERE `code` = %s AND `data_date` = %s",
                    (str(code), data_date))
            except Exception:
                logger.warning("基金 AI 分析：删除旧缓存失败，改用 upsert", exc_info=True)
            cols_type = None
        else:
            cols_type = tbs.get_field_types(tbs.TABLE_CN_FUND_AI_ANALYSIS['columns'])
        mdb.insert_db_from_df(df, _AI_TABLE, cols_type, False, "`code`,`data_date`")
    except Exception:
        logger.warning("基金 AI 分析：写缓存失败（忽略）", exc_info=True)


# ── Handler ───────────────────────────────────────────────────────────────────

class FundAiAnalysisHandler(webBase.BaseHandler):
    """基金 AI 按需分析（懒加载 + 缓存 + 规则降级）。"""

    def get(self):
        """仅查缓存：命中返回，未命中返回 ai_available=False + 规则降级 composite。"""
        try:
            code = (self.get_argument('code', default='') or '').strip()
            if not code:
                _write_error(self, '缺少 code 参数')
                return
            ctx, composite, table_presence = gather_ctx(code)
            if ctx is None:
                _write_error(self, f'未找到基金 {code} 的最新数据', 404)
                return
            data_date = _norm_date(ctx.get('data_date'))
            cached = _load_cache(code, data_date, table_presence.get(_AI_TABLE))
            if cached:
                _write_json(self, {
                    'code': code, 'name': ctx.get('name'),
                    'data_date': str(data_date), 'cached': True,
                    'ai_available': True, 'content': cached['content'],
                    'sources': cached['sources'], 'model': cached['model'],
                    'composite': composite,
                })
                return
            _write_json(self, {
                'code': code, 'name': ctx.get('name'),
                'data_date': str(data_date), 'cached': False,
                'ai_available': False, 'content': '', 'sources': [],
                'composite': composite,
            })
        except Exception:
            logger.error("基金 AI 分析(GET)异常", exc_info=True)
            _write_error(self, '服务器内部错误', 500)

    def post(self):
        """触发 AI 分析：命中缓存直接返回；否则调用 LLM（web_search）并落缓存。"""
        try:
            code = self._read_code()
            refresh = self._read_refresh()
            if not code:
                _write_error(self, '缺少 code 参数')
                return

            ctx, composite, table_presence = gather_ctx(code)
            if ctx is None:
                _write_error(self, f'未找到基金 {code} 的最新数据', 404)
                return
            data_date = _norm_date(ctx.get('data_date'))

            if not refresh:
                cached = _load_cache(code, data_date, table_presence.get(_AI_TABLE))
                if cached:
                    _write_json(self, {
                        'code': code, 'name': ctx.get('name'),
                        'data_date': str(data_date), 'cached': True,
                        'ai_available': True, 'content': cached['content'],
                        'sources': cached['sources'], 'model': cached['model'],
                        'composite': composite,
                    })
                    return

            # ── 功能开关（fail-open）──
            try:
                from quantia.lib.ai.feature_switch import is_feature_enabled
                enabled = is_feature_enabled(_FEATURE)
            except Exception:
                enabled = True
            if not enabled:
                _write_json(self, self._fallback_payload(
                    code, ctx, composite, data_date,
                    note='AI 分析功能当前已关闭，以下为规则化综合分析。'))
                return

            # ── 调用 LLM ──
            try:
                from quantia.lib.ai import run_agent
                from quantia.lib.ai.prompt_loader import load as load_prompt
                system = load_prompt(_PROMPT_NAME)
                user_message = build_user_message(ctx, composite)
                result = run_agent(
                    user_message=user_message,
                    scene=_SCENE,
                    agent=_PROMPT_NAME,
                    system=system,
                    allowed_tools=['web_search'],
                )
                content = (result.content or '').strip()
                if not content:
                    raise RuntimeError('LLM 返回空内容')
                sources = _extract_sources(result.tool_calls)
                model = result.model or result.provider or ''
                _save_cache(code, data_date, content, sources, model, table_presence.get(_AI_TABLE))
                _write_json(self, {
                    'code': code, 'name': ctx.get('name'),
                    'data_date': str(data_date), 'cached': False,
                    'ai_available': True, 'content': content,
                    'sources': sources, 'model': model,
                    'rounds': result.rounds, 'total_tokens': result.total_tokens,
                    'composite': composite,
                })
            except Exception as exc:
                logger.warning("基金 AI 分析：LLM 调用失败，降级规则分析: %s", exc,
                               exc_info=True)
                _write_json(self, self._fallback_payload(
                    code, ctx, composite, data_date,
                    note='AI 暂不可用，以下为规则化综合分析。'))
        except Exception:
            logger.error("基金 AI 分析(POST)异常", exc_info=True)
            _write_error(self, '服务器内部错误', 500)

    # ── helpers ──
    def _read_code(self):
        code = (self.get_argument('code', default='') or '').strip()
        if code:
            return code
        try:
            body = self.request.body
            if body:
                data = json.loads(body)
                if isinstance(data, dict):
                    return str(data.get('code', '') or '').strip()
        except (ValueError, TypeError):
            pass
        return ''

    def _read_refresh(self):
        raw = (self.get_argument('refresh', default='') or '').strip().lower()
        if raw in ('1', 'true', 'yes'):
            return True
        try:
            body = self.request.body
            if body:
                data = json.loads(body)
                if isinstance(data, dict):
                    return bool(data.get('refresh', False))
        except (ValueError, TypeError):
            pass
        return False

    def _fallback_payload(self, code, ctx, composite, data_date, note):
        return {
            'code': code, 'name': ctx.get('name'),
            'data_date': str(data_date), 'cached': False,
            'ai_available': False, 'content': '', 'sources': [],
            'note': note, 'composite': composite,
        }
