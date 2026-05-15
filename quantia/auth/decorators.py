# -*- coding: utf-8 -*-
"""Phase 8 鉴权装饰器与 mixin。

设计原则
========

1. **默认直通**：``QUANTIA_AUTH_ENABLED`` 未启用时，所有装饰器立即返回，
   不读取 cookie、不写状态码，等价于装饰前的旧行为。
2. **写操作 CSRF**：装饰 ``post/put/delete`` 时 *自动* 校验
   ``X-CSRF-Token`` 与 cookie 一致；GET 不校验。
3. **session 用户透出**：成功通过校验后把 username 写入
   ``handler.current_username``，handler 可直接读取用作 ``modified_by``。
4. **角色（Should 8）**：登录后 ``QUANTIA_role`` secure_cookie 携带角色；
   :func:`require_role` 用于「只允许 admin/operator 等」的接口。
5. **不引入 Tornado 中间件**：通过 mixin / 装饰器形式按需启用，避免影响
   不需要鉴权的接口（例如 K 线、行情、回测列表等读接口）。
"""
from __future__ import annotations

import functools
import logging
from typing import Any, Callable, Optional

from . import (
    CSRF_COOKIE_NAME, CSRF_HEADER_NAME, SESSION_COOKIE_NAME,
    is_auth_enabled, session_ttl_seconds,
)


ROLE_COOKIE_NAME = "QUANTIA_role"
DEFAULT_DISABLED_ROLE = "admin"  # 关闭鉴权时占位角色（最大权限，保持旧行为）


def _read_secure(handler: Any, name: str) -> Optional[str]:
    try:
        raw = handler.get_secure_cookie(
            name,
            max_age_days=session_ttl_seconds() / 86400.0,
        )
    except Exception:
        return None
    if not raw:
        return None
    try:
        return raw.decode("utf-8")
    except Exception:
        return None


def _read_session_username(handler: Any) -> Optional[str]:
    return _read_secure(handler, SESSION_COOKIE_NAME)


def _read_session_role(handler: Any) -> Optional[str]:
    return _read_secure(handler, ROLE_COOKIE_NAME)


def _check_csrf(handler: Any) -> bool:
    """写操作 CSRF 校验：cookie 与 header 一致即放行。"""
    try:
        token_cookie = handler.get_cookie(CSRF_COOKIE_NAME)
    except Exception:
        token_cookie = None
    token_header = handler.request.headers.get(CSRF_HEADER_NAME)
    if not token_cookie or not token_header:
        return False
    return token_cookie == token_header


def _write_error(handler: Any, status: int, error: str) -> None:
    """统一 401/403 错误响应（JSON）。"""
    try:
        handler.set_status(status)
        handler.set_header("Content-Type", "application/json; charset=utf-8")
        import json
        handler.write(json.dumps({"ok": False, "error": error},
                                 ensure_ascii=False))
        handler.finish()
    except Exception:
        logging.warning("[auth] 写错误响应失败", exc_info=True)


def _enforce_session(self) -> Optional[str]:
    """提取共享的 session+CSRF 校验逻辑。

    返回：
    - ``str``：登录用户名（成功）。
    - ``None``：已写入 401/403 响应。
    """
    username = _read_session_username(self)
    if not username:
        _write_error(self, 401, "未登录或会话已过期")
        return None
    http_method = (
        getattr(self, "request", None)
        and self.request.method or ""
    ).upper()
    if http_method in ("POST", "PUT", "DELETE", "PATCH"):
        if not _check_csrf(self):
            _write_error(self, 403, "CSRF 校验失败")
            return None
    return username


def require_login(method: Callable) -> Callable:
    """装饰 handler 的 HTTP 方法（GET/POST/...）；要求会话有效。

    关闭态：直通，``current_username='system'``、``current_role='admin'``。
    启用态：未登录 → 401；写操作 CSRF 失败 → 403；通过后注入
    ``self.current_username`` / ``self.current_role``。
    """
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        if not is_auth_enabled():
            self.current_username = "system"
            self.current_role = DEFAULT_DISABLED_ROLE
            return method(self, *args, **kwargs)
        username = _enforce_session(self)
        if username is None:
            return None
        self.current_username = username
        # 默认 'viewer'：若 role cookie 缺失或被篕改，取最保守角色，
        # 避免从占位默认获得写权限。
        self.current_role = _read_session_role(self) or "viewer"
        return method(self, *args, **kwargs)
    return wrapper


def require_role(*allowed_roles: str) -> Callable:
    """要求当前会话角色属于 ``allowed_roles``。

    关闭鉴权时直通；启用时先做 session+CSRF 校验，再判角色，不匹配 → 403。
    无需在外再叠 :func:`require_login`，避免双层 401。
    """
    if not allowed_roles:
        raise ValueError("require_role 至少传一个角色")
    allowed = tuple({r.strip() for r in allowed_roles if r and r.strip()})

    def deco(method: Callable) -> Callable:
        @functools.wraps(method)
        def wrapper(self, *args, **kwargs):
            if not is_auth_enabled():
                self.current_username = "system"
                self.current_role = DEFAULT_DISABLED_ROLE
                return method(self, *args, **kwargs)
            username = _enforce_session(self)
            if username is None:
                return None
            # role cookie 缺失 → 'viewer'（最保守），避免装饰器被误放行。
            role = _read_session_role(self) or "viewer"
            if role not in allowed:
                _write_error(
                    self, 403,
                    f"角色不足：需要 {'/'.join(allowed)}，当前 {role}",
                )
                return None
            self.current_username = username
            self.current_role = role
            return method(self, *args, **kwargs)
        return wrapper
    return deco


__all__ = ["require_login", "require_role", "ROLE_COOKIE_NAME"]
