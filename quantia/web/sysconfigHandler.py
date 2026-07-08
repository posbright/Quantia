#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通用系统配置 KV 读写 Handler（cn_system_config 表）。

仅允许白名单中的 key 被前端读写，防止任意 key 注入。
需要新增可配置项时，在 _ALLOWED_KEYS 中添加即可。

端点：
- GET  /quantia/api/sysconfig?key=<key>         返回单个配置值
- POST /quantia/api/sysconfig   body {key, value}  写入配置
"""
import json
import logging
from abc import ABC

import quantia.lib.sysconfig as sysconfig
import quantia.web.base as webBase

__author__ = 'Quantia'
__date__ = '2026/07/04'

logger = logging.getLogger(__name__)

# ── 允许前端读写的配置 key 白名单 ─────────────────────────────────────────
_ALLOWED_KEYS = frozenset([
    'web_search_engine',           # AI Web Search 引擎偏好
    'fund_holding_full_coverage',  # 基金重仓全覆盖开关（已有专用 handler，这里备冗余）
])


def _write_json(handler, data):
    handler.set_header('Content-Type', 'application/json;charset=UTF-8')
    handler.write(json.dumps(data, ensure_ascii=False))


class SysconfigHandler(webBase.BaseHandler, ABC):
    """GET/POST /quantia/api/sysconfig —— 通用 KV 配置读写。"""

    def get(self):
        key = self.get_argument('key', '').strip()
        if not key:
            self.set_status(400)
            _write_json(self, {'code': -1, 'msg': '缺少 key 参数'})
            return
        if key not in _ALLOWED_KEYS:
            self.set_status(403)
            _write_json(self, {'code': -1, 'msg': f'配置项 "{key}" 不允许通过 API 访问'})
            return
        try:
            value = sysconfig.get(key)
            _write_json(self, {'code': 0, 'data': {'key': key, 'value': value}})
        except Exception:
            logger.error("sysconfig GET 异常 key=%s", key, exc_info=True)
            self.set_status(500)
            _write_json(self, {'code': -1, 'msg': '服务器内部错误'})

    def post(self):
        try:
            body = json.loads(self.request.body) if self.request.body else {}
        except (json.JSONDecodeError, TypeError):
            self.set_status(400)
            _write_json(self, {'code': -1, 'msg': '无效的 JSON body'})
            return

        key = str(body.get('key') or '').strip()
        value = str(body.get('value') or '').strip()
        if not key:
            self.set_status(400)
            _write_json(self, {'code': -1, 'msg': '缺少 key'})
            return
        if key not in _ALLOWED_KEYS:
            self.set_status(403)
            _write_json(self, {'code': -1, 'msg': f'配置项 "{key}" 不允许通过 API 写入'})
            return

        try:
            ok = sysconfig.set(key, value)
            if not ok:
                self.set_status(500)
                _write_json(self, {'code': -1, 'msg': '写入失败'})
                return
            _write_json(self, {'code': 0, 'data': {'key': key, 'value': value}})
        except Exception:
            logger.error("sysconfig POST 异常 key=%s", key, exc_info=True)
            self.set_status(500)
            _write_json(self, {'code': -1, 'msg': '服务器内部错误'})
