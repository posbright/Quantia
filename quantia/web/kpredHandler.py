#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
K 线预测 Provider Handler

转发前端请求至 AgentPit 或兼容的本地服务，将 API Key 保持在服务端。
内置当日缓存：同一 provider+股票+天数在同一天内只请求一次供应商 API。

可配置项（.env / 环境变量）：
    QUANTIA_KPRED_PROVIDER       — agentpit / local（默认 agentpit）
    QUANTIA_AGENTPIT_API_KEY     — AgentPit 模式必填
    QUANTIA_KPRED_API_URL        — AgentPit API 端点
    QUANTIA_KPRED_LOCAL_URL      — 本地部署 API 端点
    QUANTIA_KPRED_LOCAL_API_KEY  — 本地部署鉴权（可选）
    QUANTIA_KPRED_TIMEOUT        — 请求超时秒数（默认 300，范围 1~600）

前端请求体也可传入 timeout 参数覆盖超时。
"""

import json
import asyncio
import hashlib
import logging
import os
import time
import datetime
from concurrent.futures import ThreadPoolExecutor
import tornado.web
from tornado.ioloop import IOLoop
import urllib.request
import urllib.error
import quantia.lib.envconfig  # noqa: F401 — 确保 .env 已加载

logger = logging.getLogger(__name__)

_DEFAULT_API_URL = 'https://api.agentpit.io/v1/open-api/kpred'
_DEFAULT_LOCAL_URL = 'http://127.0.0.1:18081/v1/open-api/kpred'
_DEFAULT_TIMEOUT = 300  # seconds
_DEFAULT_HORIZONS = (1, 3, 5, 10, 15, 30)
_executor = ThreadPoolExecutor(max_workers=4)

# ===== 服务端当日缓存 =====
# key includes provider, request settings, and local history fingerprint.
# 缓存在进程内存中，web_service 重启或跨天自动失效。
_pred_cache: dict = {}
_pred_cache_date: str = ''  # 当前缓存所属日期，跨天时清空全部缓存
_singleflight_tasks: dict[str, asyncio.Task] = {}


class KpredRequestError(ValueError):
    def __init__(self, message: str, status: int, error_code: str) -> None:
        super().__init__(message)
        self.status = status
        self.error_code = error_code


def _cache_key(code: str, days: int, provider: str, context: str = '') -> str:
    today = time.strftime('%Y%m%d')
    return f'{provider}_{code}_{days}_{today}_{context}'


def _get_cache(code: str, days: int, provider: str = 'agentpit',
               context: str = '') -> dict | None:
    """查询当日缓存，命中返回 response dict，未命中返回 None"""
    global _pred_cache, _pred_cache_date
    today = time.strftime('%Y%m%d')
    if _pred_cache_date != today:
        # 跨天：清空前一天的缓存
        _pred_cache.clear()
        _pred_cache_date = today
        return None
    return _pred_cache.get(_cache_key(code, days, provider, context))


def _set_cache(code: str, days: int, data: dict, provider: str = 'agentpit',
               context: str = ''):
    """写入当日缓存"""
    global _pred_cache, _pred_cache_date
    today = time.strftime('%Y%m%d')
    if _pred_cache_date != today:
        _pred_cache.clear()
        _pred_cache_date = today
    _pred_cache[_cache_key(code, days, provider, context)] = data


def _cache_context(provider: str, payload: dict | None = None) -> str:
    """Fingerprint settings and local history so corrected inputs invalidate cache."""
    settings = {
        'provider': provider,
        'url': _get_api_url(provider),
        'model_version': os.environ.get('QUANTIA_KPRED_MODEL_VERSION', ''),
    }
    if provider == 'local':
        settings.update({
            'lookback': os.environ.get('KRONOS_LOOKBACK', '256'),
            'sample_count': os.environ.get('KRONOS_SAMPLE_COUNT', '1'),
            'temperature': os.environ.get('KRONOS_TEMPERATURE', '1.0'),
            'top_k': os.environ.get('KRONOS_TOP_K', '1'),
            'top_p': os.environ.get('KRONOS_TOP_P', '1.0'),
            'history': (payload or {}).get('history', []),
            'future_timestamps': (payload or {}).get('future_timestamps', []),
        })
    encoded = json.dumps(
        settings, sort_keys=True, separators=(',', ':'), allow_nan=False
    ).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()[:24]


def _clear_singleflight(flight_key: str, task: asyncio.Task) -> None:
    if _singleflight_tasks.get(flight_key) is task:
        _singleflight_tasks.pop(flight_key, None)


def _get_provider() -> str:
    """返回当前预测供应商；非法配置直接报错，避免静默走错服务。"""
    provider = (os.environ.get('QUANTIA_KPRED_PROVIDER') or 'agentpit').strip().lower()
    if provider not in ('agentpit', 'local'):
        raise ValueError('QUANTIA_KPRED_PROVIDER 仅支持 agentpit/local')
    return provider


def _get_api_key(provider: str = 'agentpit') -> str:
    """读取供应商鉴权；本地部署默认允许无 Key。"""
    env_name = 'QUANTIA_KPRED_LOCAL_API_KEY' if provider == 'local' else 'QUANTIA_AGENTPIT_API_KEY'
    return (os.environ.get(env_name) or '').strip()


def _get_api_url(provider: str = 'agentpit') -> str:
    """按 provider 读取 API 地址。"""
    if provider == 'local':
        return (os.environ.get('QUANTIA_KPRED_LOCAL_URL') or '').strip() or _DEFAULT_LOCAL_URL
    return (os.environ.get('QUANTIA_KPRED_API_URL') or '').strip() or _DEFAULT_API_URL


def _get_timeout(request_timeout=None) -> int:
    """优先用请求参数 timeout，其次环境变量，最后默认 300s"""
    if request_timeout is not None:
        try:
            t = int(request_timeout)
            if 1 <= t <= 600:
                return t
        except (TypeError, ValueError):
            pass
    env_val = os.environ.get('QUANTIA_KPRED_TIMEOUT', '').strip()
    if env_val:
        try:
            t = int(env_val)
            if 1 <= t <= 600:
                return t
        except (TypeError, ValueError):
            pass
    return _DEFAULT_TIMEOUT


def _get_supported_horizons() -> tuple[int, ...]:
    """返回允许的预测交易日选项，非法配置直接失败。"""
    raw = os.environ.get('QUANTIA_KPRED_HORIZONS', '1,3,5,10,15,30')
    try:
        horizons = tuple(sorted({int(value.strip()) for value in raw.split(',') if value.strip()}))
    except ValueError as exc:
        raise ValueError('QUANTIA_KPRED_HORIZONS 必须是逗号分隔的正整数') from exc
    if not horizons or horizons[0] < 1 or horizons[-1] > 120:
        raise ValueError('QUANTIA_KPRED_HORIZONS 必须位于 1~120 且不能为空')
    return horizons


def _do_provider_request(api_url: str, api_key: str, code: str, days: int, timeout: int,
                         payload: dict | None = None) -> dict:
    """同步执行供应商 HTTP 请求（在线程池中调用，不阻塞 IO 循环）。"""
    request_body = json.dumps(payload or {'code': code, 'days': days}).encode('utf-8')
    headers = {'Content-Type': 'application/json'}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    req = urllib.request.Request(
        api_url,
        data=request_body,
        headers=headers,
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        resp_body = resp.read().decode('utf-8')
        try:
            return json.loads(resp_body)
        except json.JSONDecodeError:
            raise ValueError(f'上游返回非 JSON 响应 (HTTP {resp.status}, body[:200]={resp_body[:200]})')


def _do_upstream_request(api_url: str, api_key: str, code: str, days: int, timeout: int) -> dict:
    """兼容旧调用名。"""
    return _do_provider_request(api_url, api_key, code, days, timeout)


def _completed_daily_cutoff(now: datetime.datetime | None = None) -> datetime.date:
    """返回当前时点可安全使用的最后一个完整日线交易日。"""
    from quantia.lib.trade_time import (
        get_previous_trade_date,
        is_post_settlement,
        is_trade_date,
    )

    now = now or datetime.datetime.now()
    today = now.date()
    if not is_trade_date(today):
        return get_previous_trade_date(today)
    if not is_post_settlement(today, _now=now):
        return get_previous_trade_date(today)
    return today


def _prepare_local_payload(code: str, days: int,
                           now: datetime.datetime | None = None) -> dict:
    """从 Quantia 本地缓存构造 Kronos 请求，不触发外部行情请求。"""
    import pandas as pd
    from quantia.core.backtest.data_feed import load_stock_data
    from quantia.lib.trade_time import get_next_trade_date

    cutoff_date = _completed_daily_cutoff(now)
    history = load_stock_data(code, end_date=cutoff_date, cache_only=True)
    if history is None or len(history) == 0:
        raise KpredRequestError(f'本地无 {code} K 线缓存', 404, 'HISTORY_NOT_FOUND')
    history = history.sort_values('date').drop_duplicates('date', keep='last')
    lookback = max(32, min(512, int(os.environ.get('KRONOS_LOOKBACK', '256'))))
    if len(history) < lookback:
        raise KpredRequestError(
            f'{code} 本地历史不足：需要 {lookback} 根，实际 {len(history)} 根',
            422,
            'INSUFFICIENT_HISTORY',
        )
    history = history.tail(lookback).copy()
    if 'amount' not in history.columns:
        history['amount'] = history['volume'] * history[['open', 'high', 'low', 'close']].mean(axis=1)

    last_date = pd.Timestamp(history['date'].iloc[-1]).date()
    history_stale = last_date < cutoff_date
    reject_stale = (os.environ.get('KRONOS_REJECT_STALE_HISTORY', '1').strip().lower()
                    in ('1', 'true', 'yes', 'on'))
    if history_stale and reject_stale:
        raise KpredRequestError(
            f'{code} 本地历史已过期：最后完整日线 {last_date}，应至少更新到 {cutoff_date}',
            409,
            'HISTORY_STALE',
        )
    future_dates = []
    cursor = last_date
    for _ in range(days):
        next_date = get_next_trade_date(cursor)
        if next_date <= cursor:
            raise ValueError(f'交易日历无法生成 {cursor} 之后的交易日')
        future_dates.append(next_date.isoformat())
        cursor = next_date

    rows = []
    for _, row in history.iterrows():
        rows.append({
            'date': pd.Timestamp(row['date']).date().isoformat(),
            'open': float(row['open']),
            'high': float(row['high']),
            'low': float(row['low']),
            'close': float(row['close']),
            'volume': float(row.get('volume', 0) or 0),
            'amount': float(row.get('amount', 0) or 0),
        })
    return {
        'code': code,
        'days': days,
        'history': rows,
        'future_timestamps': future_dates,
        'history_cutoff_date': cutoff_date.isoformat(),
        'prediction_start_date': future_dates[0],
        'history_stale': history_stale,
    }


def _normalize_provider_response(response: dict, provider: str) -> dict:
    """把直接业务对象或 {code, data} 包装统一成前端所需的单层对象。"""
    if not isinstance(response, dict):
        raise ValueError('预测服务返回格式无效：顶层必须是 JSON object')

    nested = response.get('data')
    wrapped = isinstance(nested, dict)
    has_predictions = isinstance(response.get('predictions'), list)
    if 'code' in response and response.get('code') not in (0, '0', None) and (wrapped or not has_predictions):
        raise ValueError(str(response.get('msg') or response.get('message') or '预测服务返回失败'))

    data = nested if wrapped else response
    if not isinstance(data.get('predictions'), list):
        raise ValueError('预测服务返回格式无效：缺少 predictions 数组')
    if data.get('pro') is not None and not isinstance(data.get('pro'), dict):
        raise ValueError('预测服务返回格式无效：pro 必须是 object 或 null')

    normalized = dict(data)
    normalized.setdefault('provider', provider)
    return normalized


async def _request_provider_data(api_url: str, api_key: str, code: str, days: int,
                                 timeout: int, payload: dict | None,
                                 provider: str) -> dict:
    loop = IOLoop.current()
    response = await loop.run_in_executor(
        _executor, _do_provider_request, api_url, api_key, code, days, timeout, payload
    )
    return _normalize_provider_response(response, provider)


class GetKpredHandler(tornado.web.RequestHandler):
    """POST /quantia/api/kpred — 转发 AgentPit / 本地 K 线预测请求。"""

    def set_default_headers(self):
        self.set_header('Content-Type', 'application/json; charset=UTF-8')
        self.set_header('Access-Control-Allow-Origin', '*')
        self.set_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.set_header('Access-Control-Allow-Headers', 'Content-Type')

    def options(self):
        self.set_status(204)
        self.finish()

    async def post(self):
        try:
            provider = _get_provider()
        except ValueError as e:
            self.set_status(500)
            self.write(json.dumps({'code': -1, 'msg': str(e)}, ensure_ascii=False))
            return

        api_key = _get_api_key(provider)
        if provider == 'agentpit' and not api_key:
            self.set_status(500)
            self.write(json.dumps({'code': -1, 'msg': '服务端未配置 QUANTIA_AGENTPIT_API_KEY'},
                                  ensure_ascii=False))
            return

        try:
            body = json.loads(self.request.body or '{}')
        except Exception:
            self.set_status(400)
            self.write(json.dumps({'code': -1, 'msg': '请求体 JSON 解析失败'}, ensure_ascii=False))
            return

        code = (body.get('code') or '').strip()
        if not code:
            self.set_status(400)
            self.write(json.dumps({'code': -1, 'msg': '缺少 code 参数'}, ensure_ascii=False))
            return

        # 校验 code 格式：仅允许数字（6位A股代码），防止注入
        if not code.isdigit() or len(code) != 6:
            self.set_status(400)
            self.write(json.dumps({'code': -1, 'msg': 'code 参数格式无效，需6位数字股票代码'},
                                  ensure_ascii=False))
            return

        try:
            supported_horizons = _get_supported_horizons()
            max_days = max(1, min(120, int(os.environ.get(
                'QUANTIA_KPRED_MAX_DAYS', str(max(_DEFAULT_HORIZONS))
            ))))
            supported_horizons = tuple(day for day in supported_horizons if day <= max_days)
            if not supported_horizons:
                raise ValueError('预测周期配置为空，请检查 QUANTIA_KPRED_MAX_DAYS/HORIZONS')
        except ValueError as e:
            self.set_status(500)
            self.write(json.dumps({'code': -1, 'msg': str(e)}, ensure_ascii=False))
            return
        days = body.get('days', 5)
        try:
            days = int(days)
        except (TypeError, ValueError):
            self.set_status(400)
            self.write(json.dumps({'code': -1, 'msg': 'days 必须是整数'}, ensure_ascii=False))
            return
        if days not in supported_horizons:
            self.set_status(400)
            self.write(json.dumps({
                'code': -1,
                'msg': f'days 仅支持 {list(supported_horizons)}',
                'supported_horizons': list(supported_horizons),
            }, ensure_ascii=False))
            return

        timeout = _get_timeout(body.get('timeout'))
        api_url = _get_api_url(provider)
        loop = IOLoop.current()
        try:
            provider_payload = None
            if provider == 'local':
                provider_payload = await loop.run_in_executor(
                    _executor, _prepare_local_payload, code, days
                )
            cache_context = _cache_context(provider, provider_payload)
        except KpredRequestError as e:
            self.set_status(e.status)
            self.write(json.dumps({
                'code': -1, 'msg': str(e), 'error_code': e.error_code,
            }, ensure_ascii=False))
            return
        except Exception as e:
            logger.exception('kpred local payload failed: %s', e)
            self.set_status(500)
            self.write(json.dumps({
                'code': -1, 'msg': f'本地历史处理失败: {e}', 'error_code': 'INVALID_HISTORY',
            }, ensure_ascii=False))
            return

        # === 服务端缓存命中：同一输入指纹直接返回，无需调用上游 ===
        refresh = body.get('refresh', False)  # 前端"刷新"按钮传 refresh:true 绕过缓存
        if not refresh:
            cached = _get_cache(code, days, provider, cache_context)
            if cached is not None:
                logger.debug('kpred cache hit: provider=%s code=%s days=%d', provider, code, days)
                self.write(json.dumps({'code': 0, 'data': cached, '_cached': True},
                                      ensure_ascii=False))
                return

        flight_key = _cache_key(code, days, provider, cache_context)
        request_task = _singleflight_tasks.get(flight_key)
        coalesced = request_task is not None
        if request_task is None:
            request_task = asyncio.create_task(_request_provider_data(
                api_url, api_key, code, days, timeout, provider_payload, provider
            ))
            _singleflight_tasks[flight_key] = request_task
            request_task.add_done_callback(
                lambda task, key=flight_key: _clear_singleflight(key, task)
            )
        try:
            data = await asyncio.shield(request_task)
        except urllib.error.HTTPError as e:
            status = e.code
            err_body = ''
            try:
                err_body = e.read().decode('utf-8', errors='replace')
            except Exception:
                pass
            logger.warning('kpred upstream HTTP %s: %s', status, err_body[:500])
            error_payload = {}
            try:
                error_payload = json.loads(err_body)
            except (TypeError, json.JSONDecodeError):
                pass
            msg_map = {401: 'API Key 无效', 429: '月度额度已用完', 502: '预测服务异常'}
            allowed_status = (400, 401, 404, 409, 422, 429, 502, 503, 504)
            self.set_status(status if status in allowed_status else 502)
            self.write(json.dumps({
                'code': -1,
                'msg': error_payload.get('msg') or msg_map.get(status, f'预测服务错误 ({status})'),
                'error_code': error_payload.get('error_code') or 'UPSTREAM_ERROR',
            }, ensure_ascii=False))
            return
        except urllib.error.URLError as e:
            logger.warning('kpred upstream connection error: %s', e.reason)
            self.set_status(502)
            self.write(json.dumps({'code': -1, 'msg': f'预测服务连接失败: {e.reason}'},
                                  ensure_ascii=False))
            return
        except Exception as e:
            logger.exception('kpred request failed: %s', e)
            self.set_status(502)
            self.write(json.dumps({'code': -1, 'msg': f'预测服务请求失败: {e}'}, ensure_ascii=False))
            return

        self.write(json.dumps({
            'code': 0, 'data': data, **({'_singleflight': True} if coalesced else {}),
        }, ensure_ascii=False))
        # 缓存成功的预测结果（当天有效）
        _set_cache(code, days, data, provider, cache_context)
