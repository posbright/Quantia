#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
K线预测代理 Handler

转发前端请求至 AgentPit kpred API，将 API Key 保持在服务端。
内置当日缓存：同一股票+天数在同一天内只请求一次上游 API，后续所有用户直接返回缓存。

可配置项（.env / 环境变量）：
  QUANTIA_AGENTPIT_API_KEY  — 必填，AgentPit API Key
  QUANTIA_KPRED_API_URL     — 可选，API 端点 URL（默认 https://api.agentpit.io/v1/open-api/kpred）
  QUANTIA_KPRED_TIMEOUT     — 可选，请求超时秒数（默认 300，范围 1~600）

前端请求体也可传入 timeout 参数覆盖超时。
"""

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
import tornado.web
from tornado.ioloop import IOLoop
import urllib.request
import urllib.error
import quantia.lib.envconfig  # noqa: F401 — 确保 .env 已加载

logger = logging.getLogger(__name__)

_DEFAULT_API_URL = 'https://api.agentpit.io/v1/open-api/kpred'
_DEFAULT_TIMEOUT = 300  # seconds
_executor = ThreadPoolExecutor(max_workers=4)

# ===== 服务端当日缓存 =====
# key: "code_days_YYYYMMDD"  value: (timestamp, response_dict)
# 同一股票+天数+日期的预测结果是确定性的（同模型、同输入数据），与用户无关。
# 缓存在进程内存中，web_service 重启或跨天自动失效。
_pred_cache: dict = {}
_pred_cache_date: str = ''  # 当前缓存所属日期，跨天时清空全部缓存


def _get_cache(code: str, days: int) -> dict | None:
    """查询当日缓存，命中返回 response dict，未命中返回 None"""
    global _pred_cache, _pred_cache_date
    today = time.strftime('%Y%m%d')
    if _pred_cache_date != today:
        # 跨天：清空前一天的缓存
        _pred_cache.clear()
        _pred_cache_date = today
        return None
    key = f'{code}_{days}_{today}'
    return _pred_cache.get(key)


def _set_cache(code: str, days: int, data: dict):
    """写入当日缓存"""
    global _pred_cache, _pred_cache_date
    today = time.strftime('%Y%m%d')
    if _pred_cache_date != today:
        _pred_cache.clear()
        _pred_cache_date = today
    key = f'{code}_{days}_{today}'
    _pred_cache[key] = data


def _get_api_key() -> str:
    """从 .env / 环境变量读取 QUANTIA_AGENTPIT_API_KEY"""
    return (os.environ.get('QUANTIA_AGENTPIT_API_KEY') or '').strip()


def _get_api_url() -> str:
    """从 .env / 环境变量读取 QUANTIA_KPRED_API_URL，缺省用官方地址"""
    url = (os.environ.get('QUANTIA_KPRED_API_URL') or '').strip()
    return url if url else _DEFAULT_API_URL


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


def _do_upstream_request(api_url: str, api_key: str, code: str, days: int, timeout: int) -> dict:
    """同步执行上游 HTTP 请求（在线程池中调用，不阻塞 IO 循环）"""
    payload = json.dumps({'code': code, 'days': days}).encode('utf-8')
    req = urllib.request.Request(
        api_url,
        data=payload,
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}',
        },
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        resp_body = resp.read().decode('utf-8')
        try:
            return json.loads(resp_body)
        except json.JSONDecodeError:
            raise ValueError(f'上游返回非 JSON 响应 (HTTP {resp.status}, body[:200]={resp_body[:200]})')


class GetKpredHandler(tornado.web.RequestHandler):
    """POST /quantia/api/kpred — 代理转发 AgentPit K线预测请求"""

    def set_default_headers(self):
        self.set_header('Content-Type', 'application/json; charset=UTF-8')
        self.set_header('Access-Control-Allow-Origin', '*')
        self.set_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.set_header('Access-Control-Allow-Headers', 'Content-Type')

    def options(self):
        self.set_status(204)
        self.finish()

    async def post(self):
        api_key = _get_api_key()
        if not api_key:
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

        days = body.get('days', 5)
        try:
            days = int(days)
            days = max(1, min(30, days))
        except (TypeError, ValueError):
            days = 5

        # === 服务端缓存命中：同一股票+天数+日期直接返回，无需调用上游 ===
        refresh = body.get('refresh', False)  # 前端"刷新"按钮传 refresh:true 绕过缓存
        if not refresh:
            cached = _get_cache(code, days)
            if cached is not None:
                logger.debug('kpred cache hit: %s days=%d', code, days)
                self.write(json.dumps({'code': 0, 'data': cached, '_cached': True},
                                      ensure_ascii=False))
                return

        timeout = _get_timeout(body.get('timeout'))
        api_url = _get_api_url()

        # 在线程池中执行同步 HTTP 请求，不阻塞 Tornado IO 循环
        loop = IOLoop.current()
        try:
            data = await loop.run_in_executor(
                _executor, _do_upstream_request, api_url, api_key, code, days, timeout
            )
        except urllib.error.HTTPError as e:
            status = e.code
            err_body = ''
            try:
                err_body = e.read().decode('utf-8', errors='replace')
            except Exception:
                pass
            logger.warning('kpred upstream HTTP %s: %s', status, err_body[:500])
            msg_map = {401: 'API Key 无效', 429: '月度额度已用完', 502: '预测服务异常'}
            self.set_status(status if status in (401, 429, 502) else 502)
            self.write(json.dumps({
                'code': -1,
                'msg': msg_map.get(status, f'预测服务错误 ({status})'),
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

        self.write(json.dumps({'code': 0, 'data': data}, ensure_ascii=False))
        # 缓存成功的预测结果（当天有效）
        _set_cache(code, days, data)
