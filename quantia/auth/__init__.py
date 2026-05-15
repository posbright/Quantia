# -*- coding: utf-8 -*-
"""Phase 8 鉴权：单管理员账户 + 会话 + CSRF + IP 白名单。

设计原则
========

1. **默认关闭**：``QUANTIA_AUTH_ENABLED`` 未设置或为 ``"false"``/``"0"`` 时，
   所有装饰器/校验函数返回 ``True``（直通），保持 Phase 1–7 测试基线
   不变。
2. **单账户内嵌**：通过环境变量 ``QUANTIA_ADMIN_USER`` /
   ``QUANTIA_ADMIN_PASS_BCRYPT`` 注入；不引入用户表，不依赖 Redis / JWT。
3. **会话**：使用 Tornado ``set_secure_cookie`` / ``get_secure_cookie``，
   cookie name = ``QUANTIA_session``，TTL 由 ``QUANTIA_SESSION_TTL_HOURS``
   控制（默认 8 小时）。
4. **CSRF**：登录成功时颁发独立的非 httpOnly cookie ``csrf_token``；
   写操作（POST/PUT/DELETE）要求请求头 ``X-CSRF-Token`` 与 cookie
   一致。GET 不强制。
5. **IP 白名单**（钉钉回调专用）：``QUANTIA_DINGTALK_CALLBACK_ALLOW_IPS``
   逗号分隔的 IP / CIDR 列表，未配置时不强制。

模块入口
========

- :func:`is_auth_enabled` —— 总开关，所有调用方先判断。
- :func:`verify_password` —— bcrypt 校验。
- :func:`is_ip_allowed` —— IP 白名单匹配。
- :func:`generate_csrf_token` —— 生成新的 CSRF token。
"""
from __future__ import annotations

import ipaddress
import logging
import os
import secrets
from typing import Iterable, Optional


AUTH_ENABLED_ENV = "QUANTIA_AUTH_ENABLED"
ADMIN_USER_ENV = "QUANTIA_ADMIN_USER"
ADMIN_PASS_BCRYPT_ENV = "QUANTIA_ADMIN_PASS_BCRYPT"
SESSION_TTL_HOURS_ENV = "QUANTIA_SESSION_TTL_HOURS"
CALLBACK_ALLOW_IPS_ENV = "QUANTIA_DINGTALK_CALLBACK_ALLOW_IPS"

SESSION_COOKIE_NAME = "QUANTIA_session"
CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"

DEFAULT_SESSION_TTL_HOURS = 8


def is_auth_enabled() -> bool:
    """``QUANTIA_AUTH_ENABLED`` 是否为开启态。

    True 形态接受 ``"1"`` / ``"true"`` / ``"yes"`` / ``"on"``（大小写不敏感）。
    其它值（含未设置）一律视为关闭。
    """
    raw = (os.getenv(AUTH_ENABLED_ENV) or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def session_ttl_seconds() -> int:
    """会话有效期（秒）；env 异常时回退到默认。"""
    raw = os.getenv(SESSION_TTL_HOURS_ENV)
    if not raw:
        return DEFAULT_SESSION_TTL_HOURS * 3600
    try:
        hrs = float(raw)
        if hrs <= 0:
            return DEFAULT_SESSION_TTL_HOURS * 3600
        return int(hrs * 3600)
    except (TypeError, ValueError):
        logging.warning("[auth] %s=%r 解析失败，使用默认 %d 小时",
                        SESSION_TTL_HOURS_ENV, raw, DEFAULT_SESSION_TTL_HOURS)
        return DEFAULT_SESSION_TTL_HOURS * 3600


def configured_admin_user() -> str:
    return (os.getenv(ADMIN_USER_ENV) or "admin").strip() or "admin"


def configured_admin_pass_bcrypt() -> Optional[str]:
    """返回管理员密码 bcrypt 哈希；未配置返回 None。

    注意：当 ``is_auth_enabled()=True`` 但本函数返回 None 时，登录将永远
    失败。调用方应在启用鉴权前提前生成哈希（例如 Python REPL 中
    ``bcrypt.hashpw(b'pwd', bcrypt.gensalt()).decode()``）。
    """
    val = (os.getenv(ADMIN_PASS_BCRYPT_ENV) or "").strip()
    return val or None


def verify_password(plain: str, bcrypt_hash: Optional[str]) -> bool:
    """常时安全的 bcrypt 校验。哈希为空时永远返回 False。"""
    if not plain or not bcrypt_hash:
        return False
    try:
        import bcrypt
    except ImportError:
        logging.error("[auth] bcrypt 未安装，无法校验密码")
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"),
                              bcrypt_hash.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        # 哈希格式非法（例如手抄漏字符）时不暴露细节，统一拒绝。
        logging.warning("[auth] bcrypt 校验异常: %s", exc)
        return False


def generate_csrf_token() -> str:
    """生成 32 字节 url-safe token。"""
    return secrets.token_urlsafe(32)


# ─────────────── IP 白名单 ───────────────


def _parse_allow_list(raw: str) -> list:
    items = []
    for tok in (raw or "").split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            # 支持单 IP / CIDR；strict=False 允许 host bits set。
            items.append(ipaddress.ip_network(tok, strict=False))
        except ValueError:
            logging.warning("[auth] 跳过非法的 IP 白名单条目: %r", tok)
    return items


def is_ip_allowed(client_ip: Optional[str],
                  allow_list: Optional[Iterable[str]] = None) -> bool:
    """检查 ``client_ip`` 是否在白名单内。

    - ``allow_list`` 为 None 时从 :data:`CALLBACK_ALLOW_IPS_ENV` 读取。
    - 解析后白名单为空 → 视为「未启用 IP 限制」→ 永远返回 True。
    - 客户端 IP 为空 → 默认拒绝（仅在白名单已启用时生效）。
    """
    if allow_list is None:
        raw = os.getenv(CALLBACK_ALLOW_IPS_ENV) or ""
        nets = _parse_allow_list(raw)
    else:
        nets = _parse_allow_list(",".join(allow_list))
    if not nets:
        return True  # 未启用
    if not client_ip:
        return False
    try:
        addr = ipaddress.ip_address(client_ip.strip())
    except ValueError:
        logging.warning("[auth] 无法解析客户端 IP: %r", client_ip)
        return False
    return any(addr in net for net in nets)


__all__ = [
    "AUTH_ENABLED_ENV", "ADMIN_USER_ENV", "ADMIN_PASS_BCRYPT_ENV",
    "SESSION_TTL_HOURS_ENV", "CALLBACK_ALLOW_IPS_ENV",
    "SESSION_COOKIE_NAME", "CSRF_COOKIE_NAME", "CSRF_HEADER_NAME",
    "ROLE_COOKIE_NAME",
    "is_auth_enabled", "session_ttl_seconds",
    "configured_admin_user", "configured_admin_pass_bcrypt",
    "verify_password", "generate_csrf_token", "is_ip_allowed",
    "require_login", "require_role",
]


# 装饰器在子模块里定义；放到包级 export 方便 ``from quantia.auth import
# require_login``。注意 import 在 __all__ 之后，避免循环引用。
from .decorators import (  # noqa: E402
    ROLE_COOKIE_NAME, require_login, require_role,
)
