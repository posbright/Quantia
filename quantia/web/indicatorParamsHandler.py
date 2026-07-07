#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""指标买卖信号 —— 立即重算 + AI 参数顾问 Handler。

- RecomputeIndicatorSignalsHandler: 用当前已保存的参数立即重算指定日期的买/卖榜单
  （只读 cn_stock_indicators + K 线缓存，写 cn_stock_indicators_buy/sell，绝不发外部 API）。
- IndicatorAdvisorHandler: 让 AI 基于当前阈值 + 当前榜单命中数，给出推荐阈值组合与理由，
  返回结构化 JSON 供前端「一键填入」。

参数的增删改查复用 strategyParamsHandler 的通用接口（strategy_key='indicator_signal'）。
"""

import json
import logging
import re
from abc import ABC
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from tornado import gen
from tornado.ioloop import IOLoop

import quantia.web.base as webBase
import quantia.lib.database as mdb
import quantia.core.tablestructure as tbs
import quantia.core.indicator.buy_sell_signal as bss
from quantia.web.indicator_params_config import INDICATOR_SIGNAL_PARAMS

__author__ = 'Quantia'

_EXECUTOR: Optional[ThreadPoolExecutor] = None


def _executor() -> ThreadPoolExecutor:
    global _EXECUTOR
    if _EXECUTOR is None:
        _EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix='ind-params')
    return _EXECUTOR


def _write_json(handler, obj, status=200):
    handler.set_status(status)
    handler.set_header('Content-Type', 'application/json;charset=UTF-8')
    handler.write(json.dumps(obj, ensure_ascii=False, default=str))


def _latest_indicator_date():
    """返回 cn_stock_indicators 中最新的交易日（字符串）。无数据返回 None。"""
    try:
        ind = tbs.TABLE_CN_STOCK_INDICATORS['name']
        if not mdb.checkTableIsExist(ind):
            return None
        rows = mdb.executeSqlFetch(f"SELECT MAX(`date`) FROM `{ind}`")
        if rows and rows[0][0] is not None:
            return str(rows[0][0])[:10]
    except Exception:
        logging.debug("查询最新指标日期异常", exc_info=True)
    return None


# 扁平化 schema：{key: {min, max, type}}，用于校验/裁剪 AI 推荐值
def _flat_schema():
    flat = {}
    for group in INDICATOR_SIGNAL_PARAMS['indicator_signal']['groups']:
        for p in group['params']:
            flat[p['key']] = {'min': p.get('min'), 'max': p.get('max'), 'type': p.get('type')}
    return flat


class RecomputeIndicatorSignalsHandler(webBase.BaseHandler, ABC):
    """POST {date?} → 用当前已保存参数立即重算买/卖信号榜单。"""

    @gen.coroutine
    def post(self):
        try:
            body = json.loads(self.request.body or b'{}')
        except Exception as exc:
            _write_json(self, {'success': False, 'error': f'请求体解析失败: {exc}'}, 400)
            return

        date = (body.get('date') or '').strip() or _latest_indicator_date()
        if not date:
            _write_json(self, {'success': False, 'error': '无可用交易日（cn_stock_indicators 为空）'}, 400)
            return

        try:
            result = yield IOLoop.current().run_in_executor(_executor(), bss.recompute, date)
        except Exception as exc:
            logging.exception('指标信号立即重算失败')
            _write_json(self, {'success': False, 'error': f'重算失败: {exc}'}, 500)
            return

        _write_json(self, {
            'success': True,
            'date': date,
            'buy_count': result.get('buy', 0),
            'sell_count': result.get('sell', 0),
            'message': f"已重算 {date}：买入 {result.get('buy', 0)} 只 / 卖出 {result.get('sell', 0)} 只",
        })


def _current_signal_counts(date):
    """当前买/卖榜单命中数，用于给 AI 反馈"过松/过紧"。"""
    counts = {'buy': None, 'sell': None}
    try:
        for key, meta in (('buy', tbs.TABLE_CN_STOCK_INDICATORS_BUY),
                          ('sell', tbs.TABLE_CN_STOCK_INDICATORS_SELL)):
            t = meta['name']
            if mdb.checkTableIsExist(t):
                rows = mdb.executeSqlFetch(
                    f"SELECT COUNT(*) FROM `{t}` WHERE `date` = %s", (date,))
                counts[key] = int(rows[0][0]) if rows and rows[0][0] is not None else 0
    except Exception:
        logging.debug("查询当前信号数异常", exc_info=True)
    return counts


def _build_advisor_prompt(params, counts, date):
    """构造 AI 顾问 prompt：附带当前阈值、含义、命中数，要求输出 JSON。"""
    lines = []
    lines.append("你是一名 A 股量化指标参数顾问。当前有一套「超卖深跌抄底 / 超买见顶派发」的指标买卖信号策略，")
    lines.append("请基于下面的当前阈值与近期命中情况，给出更合理的推荐阈值组合，并解释理由。\n")
    lines.append(f"评估交易日：{date}")
    if counts.get('buy') is not None:
        lines.append(f"当前买入榜命中：{counts['buy']} 只；卖出榜命中：{counts.get('sell')} 只。")
        lines.append("（命中过少说明阈值过严，可适度放宽；命中过多说明过松，可适度收紧。）\n")

    lines.append("当前各参数（key | 含义 | 当前值 | 允许范围）：")
    flat = _flat_schema()
    for group in INDICATOR_SIGNAL_PARAMS['indicator_signal']['groups']:
        lines.append(f"\n【{group['group_name']}】{group['group_description']}")
        for p in group['params']:
            key = p['key']
            cur = params.get(key, p['value'])
            rng = f"{flat[key]['min']} ~ {flat[key]['max']}"
            lines.append(f"- {key} | {p['label']}：{p['description']} | 当前={cur} | 范围={rng}")

    allowed_keys = list(flat.keys())
    lines.append(
        "\n请只针对上述 key 给出建议，数值必须落在各自允许范围内；switch 类参数(exclude_st/"
        "exclude_delist/fund_filter_enabled)取 0 或 1。\n"
        "严格只输出一个 JSON 对象（不要 markdown 代码块、不要多余文字），格式：\n"
        '{"recommendations": {"<key>": <number>, ...}, '
        '"reasons": {"<key>": "<一句话理由>", ...}, '
        '"summary": "<整体调参思路 2-3 句>"}\n'
        f"可用 key：{allowed_keys}"
    )
    return "\n".join(lines)


def _parse_advisor_json(raw):
    """从 LLM 输出中提取首个 JSON 对象。失败返回 None。"""
    if not raw:
        return None
    text = raw.strip()
    # 去掉可能的 ```json fence
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r'\{.*\}', text, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None


def _sanitize_recommendations(parsed):
    """裁剪 AI 推荐：仅保留已知 key，数值 clamp 到 schema 范围；switch 归一到 0/1。"""
    flat = _flat_schema()
    recs = {}
    if not isinstance(parsed, dict):
        return recs, {}
    raw_recs = parsed.get('recommendations') or {}
    for key, val in raw_recs.items():
        if key not in flat:
            continue
        try:
            num = float(val)
        except (TypeError, ValueError):
            continue
        meta = flat[key]
        if meta.get('type') == 'switch':
            num = 1 if num >= 0.5 else 0
        else:
            lo, hi = meta.get('min'), meta.get('max')
            if lo is not None:
                num = max(num, float(lo))
            if hi is not None:
                num = min(num, float(hi))
            if float(num).is_integer():
                num = int(num)
        recs[key] = num
    reasons = parsed.get('reasons') if isinstance(parsed.get('reasons'), dict) else {}
    reasons = {k: str(v) for k, v in reasons.items() if k in flat}
    return recs, reasons


def _flat_current_params():
    """取当前生效参数（合并已保存值），扁平 {key: value}。"""
    p = bss.load_params()
    return p


class IndicatorAdvisorHandler(webBase.BaseHandler, ABC):
    """POST {date?, model?, api_key?, api_base?} → AI 推荐阈值组合（结构化）。"""

    @gen.coroutine
    def post(self):
        try:
            body = json.loads(self.request.body or b'{}')
        except Exception as exc:
            _write_json(self, {'success': False, 'error': f'请求体解析失败: {exc}'}, 400)
            return

        date = (body.get('date') or '').strip() or _latest_indicator_date() or ''
        params = _flat_current_params()
        counts = _current_signal_counts(date) if date else {'buy': None, 'sell': None}
        prompt = _build_advisor_prompt(params, counts, date)

        overrides = {}
        for k_src, k_dst in (('model', 'model'), ('api_key', 'api_key'), ('api_base', 'api_base')):
            v = body.get(k_src)
            if v:
                overrides[k_dst] = v

        def _call():
            from quantia.lib.ai.failover import run_chat_with_failover
            return run_chat_with_failover(
                prompt,
                scene='indicator_advisor',
                system='你是严谨的 A 股量化指标参数顾问，只输出符合要求的 JSON。',
                overrides=overrides or None,
            )

        try:
            raw = yield IOLoop.current().run_in_executor(_executor(), _call)
        except Exception as exc:
            logging.exception('指标参数 AI 顾问调用失败')
            _write_json(self, {'success': False, 'error': f'AI 调用失败: {exc}'}, 502)
            return

        parsed = _parse_advisor_json(raw)
        if not parsed:
            _write_json(self, {
                'success': False,
                'error': 'AI 返回无法解析为 JSON',
                'raw': raw[:2000] if isinstance(raw, str) else str(raw)[:2000],
            }, 502)
            return

        recs, reasons = _sanitize_recommendations(parsed)
        _write_json(self, {
            'success': True,
            'date': date,
            'current_counts': counts,
            'recommendations': recs,
            'reasons': reasons,
            'summary': str(parsed.get('summary', '')),
        })
