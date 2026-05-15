# -*- coding: utf-8 -*-
"""Phase 8 鉴权 HTTP handler。

路由（`web_service.py` 中注册）::

    POST /quantia/api/auth/login   {username, password}    → set-cookie session + role + csrf
    POST /quantia/api/auth/logout                          → clear cookies
    GET  /quantia/api/auth/me                              → 当前会话信息（含 role）

    # Should 8 用户管理（仅 admin 可调用）：
    GET  /quantia/api/auth/users/list
    POST /quantia/api/auth/users/save     {id?, username, password?, role, enabled}
    POST /quantia/api/auth/users/delete   {id}

    # Should 7 审计聚合（admin/operator 可读）：
    GET  /quantia/api/auth/audit/list?limit=200

设计要点
========

- ``QUANTIA_AUTH_ENABLED=false`` 时：``/me`` 返回
  ``{"enabled": false, "username": null, "role": null}``；``/login`` 也接受请求
  但仅做空操作，方便前端在测试环境探测后端是否启用鉴权。
- 启用后：登录成功颁发 ``set_secure_cookie('QUANTIA_session', username)`` +
  ``set_secure_cookie('QUANTIA_role', role)`` + 非 httpOnly ``csrf_token`` cookie。
- 用户来源优先 DB；DB 命中用户名则不再回退 env 单账户（防猜测）；DB 中未命中
  且与 env 配置一致 → 以 ``role=admin`` 登录（兼容首次部署）。
"""
from __future__ import annotations

import json
import logging
from abc import ABC
from typing import Any, List

from tornado import gen

import quantia.web.base as webBase
from quantia import auth as _auth
from quantia.auth import users as _users
from quantia.auth import email_code as _email_code
from quantia.auth.decorators import ROLE_COOKIE_NAME
from quantia.auth import require_role
from quantia.lib.database import executeSqlFetch


# ──────────────── 通用基类 ────────────────


class _BaseAuthHandler(webBase.BaseHandler, ABC):
    def _write_json(self, data: Any, status: int = 200):
        self.set_status(status)
        self.set_header("Content-Type", "application/json; charset=utf-8")
        self.write(json.dumps(data, ensure_ascii=False, default=str))

    def _read_secure(self, name: str):
        try:
            raw = self.get_secure_cookie(
                name,
                max_age_days=_auth.session_ttl_seconds() / 86400.0,
            )
        except Exception:
            return None
        if not raw:
            return None
        try:
            return raw.decode("utf-8")
        except Exception:
            return None

    def _current_user(self):
        return self._read_secure(_auth.SESSION_COOKIE_NAME)

    def _current_role(self):
        return self._read_secure(ROLE_COOKIE_NAME)


# ──────────────── 登录 / 登出 / me ────────────────


class LoginHandler(_BaseAuthHandler, ABC):
    @gen.coroutine
    def post(self):
        try:
            try:
                body = json.loads(self.request.body or b"{}")
            except Exception:
                self._write_json({"ok": False, "error": "请求体非 JSON"},
                                 status=400)
                return
            if not _auth.is_auth_enabled():
                self._write_json({
                    "ok": True, "data": {
                        "enabled": False, "username": None, "role": None,
                    },
                })
                return
            username = (body.get("username") or body.get("identifier") or "").strip()
            password = body.get("password") or ""
            if not username or not password:
                self._write_json({"ok": False, "error": "缺少用户名或密码"},
                                 status=400)
                return
            user = None
            try:
                user = _users.authenticate(username, password)
            except Exception:  # noqa: BLE001
                logging.exception("[auth] authenticate 异常")
                # DB 异常时回退到 env 单账户，避免 DB 故障锁死管理员。
                env_user = _auth.configured_admin_user()
                env_hash = _auth.configured_admin_pass_bcrypt()
                if env_hash and username == env_user and _auth.verify_password(
                        password, env_hash):
                    user = {"username": env_user, "role": "admin",
                            "source": "env-fallback"}
            if not user:
                if (_auth.configured_admin_pass_bcrypt() is None
                        and not _users.has_any_enabled_user()):
                    self._write_json({
                        "ok": False, "error": "服务端未配置管理员账户",
                    }, status=503)
                    return
                self._write_json({"ok": False, "error": "用户名或密码错误"},
                                 status=401)
                return
            ttl_seconds = _auth.session_ttl_seconds()
            expires_days = ttl_seconds / 86400.0
            self.set_secure_cookie(
                _auth.SESSION_COOKIE_NAME, user["username"],
                expires_days=expires_days, httponly=True,
            )
            self.set_secure_cookie(
                ROLE_COOKIE_NAME, user["role"],
                expires_days=expires_days, httponly=True,
            )
            csrf = _auth.generate_csrf_token()
            self.set_cookie(
                _auth.CSRF_COOKIE_NAME, csrf,
                expires_days=expires_days, httponly=False,
            )
            self._write_json({
                "ok": True, "data": {
                    "enabled": True,
                    "username": user["username"],
                    "role": user["role"],
                    "email": user.get("email"),
                    "nickname": user.get("nickname"),
                    "source": user.get("source"),
                    "csrf_token": csrf,
                    "ttl_seconds": ttl_seconds,
                },
            })
        except Exception as exc:
            logging.exception("[auth] login 失败")
            self._write_json({"ok": False, "error": str(exc)}, status=500)


class LogoutHandler(_BaseAuthHandler, ABC):
    @gen.coroutine
    def post(self):
        try:
            self.clear_cookie(_auth.SESSION_COOKIE_NAME)
            self.clear_cookie(ROLE_COOKIE_NAME)
            self.clear_cookie(_auth.CSRF_COOKIE_NAME)
            self._write_json({"ok": True})
        except Exception as exc:
            logging.exception("[auth] logout 失败")
            self._write_json({"ok": False, "error": str(exc)}, status=500)


class MeHandler(_BaseAuthHandler, ABC):
    @gen.coroutine
    def get(self):
        try:
            enabled = _auth.is_auth_enabled()
            username = self._current_user() if enabled else None
            role = self._current_role() if enabled and username else None
            self._write_json({
                "ok": True, "data": {
                    "enabled": enabled,
                    "username": username,
                    "role": role,
                },
            })
        except Exception as exc:
            logging.exception("[auth] me 失败")
            self._write_json({"ok": False, "error": str(exc)}, status=500)


# ──────────────── Should 8 用户管理（admin） ────────────────


def _to_int(v, default=None):
    if v is None or v == "":
        return default
    try:
        return int(v)
    except Exception:
        return default


# ──────────────── 自助注册（公开端点） ────────────────


class _PublicHandler(_BaseAuthHandler, ABC):
    """公开接口（不需要登录），但仍走 BaseHandler 的通用错误处理。

    注意：这里 *不* 用 ``require_login`` 装饰器，因为 ``QUANTIA_AUTH_ENABLED``
    未启用时这两个端点也应可用，方便未来开启鉴权前预先注册账号。
    """

    def _client_ip(self):
        try:
            return self.request.remote_ip
        except Exception:
            return None


class SendRegisterCodeHandler(_PublicHandler, ABC):
    """POST /quantia/api/auth/register/send-code  {email}

    向邮箱发送 6 位数字注册验证码（5 分钟内有效）。
    """

    @gen.coroutine
    def post(self):
        try:
            try:
                body = json.loads(self.request.body or b"{}")
            except Exception:
                self._write_json({"ok": False, "error": "请求体非 JSON"},
                                 status=400)
                return
            if not _email_code.is_register_enabled():
                self._write_json({"ok": False, "error": "服务端已关闭自助注册"},
                                 status=403)
                return
            email = (body.get("email") or "").strip()
            if not email:
                self._write_json({"ok": False, "error": "缺少邮箱"},
                                 status=400)
                return
            # 已注册过的邮箱不再发码（避免被探测）
            if _users.get_user_by_email(email.lower()):
                self._write_json({"ok": False, "error": "该邮箱已注册"},
                                 status=400)
                return
            try:
                result = _email_code.request_code(
                    email, purpose="register", send_ip=self._client_ip())
            except ValueError as ve:
                self._write_json({"ok": False, "error": str(ve)},
                                 status=400)
                return
            self._write_json({"ok": True, "data": result})
        except Exception as exc:
            logging.exception("[auth.register] 发码失败")
            self._write_json({"ok": False, "error": str(exc)}, status=500)


class RegisterHandler(_PublicHandler, ABC):
    """POST /quantia/api/auth/register
    {email, code, password, password_confirm, nickname}

    校验验证码 → 创建账号（默认 viewer 角色） → 自动登录并颁发 cookie。
    """

    @gen.coroutine
    def post(self):
        try:
            try:
                body = json.loads(self.request.body or b"{}")
            except Exception:
                self._write_json({"ok": False, "error": "请求体非 JSON"},
                                 status=400)
                return
            if not _email_code.is_register_enabled():
                self._write_json({"ok": False, "error": "服务端已关闭自助注册"},
                                 status=403)
                return
            email = (body.get("email") or "").strip().lower()
            code = (body.get("code") or "").strip()
            password = body.get("password") or ""
            password_confirm = body.get("password_confirm") or password
            nickname = (body.get("nickname") or "").strip()

            if not email or not code or not password or not nickname:
                self._write_json({
                    "ok": False,
                    "error": "缺少必填字段（email / code / password / nickname）",
                }, status=400)
                return
            if password != password_confirm:
                self._write_json({"ok": False, "error": "两次输入的密码不一致"},
                                 status=400)
                return
            if len(password) < 6 or len(password) > 64:
                self._write_json({"ok": False, "error": "密码长度需在 6–64"},
                                 status=400)
                return

            ok, err = _email_code.verify_code(email, code, purpose="register",
                                              consume=True)
            if not ok:
                self._write_json({"ok": False, "error": err or "验证码错误"},
                                 status=400)
                return

            try:
                user = _users.register_user(
                    email=email, password=password, nickname=nickname,
                    role="viewer",
                )
            except ValueError as ve:
                self._write_json({"ok": False, "error": str(ve)}, status=400)
                return

            # 注册成功 → 自动登录（仅当鉴权启用时下发 cookie；
            # 否则只返回创建结果，前端根据 enabled=false 直接进入应用）
            if _auth.is_auth_enabled():
                ttl_seconds = _auth.session_ttl_seconds()
                expires_days = ttl_seconds / 86400.0
                self.set_secure_cookie(
                    _auth.SESSION_COOKIE_NAME, user["username"],
                    expires_days=expires_days, httponly=True,
                )
                self.set_secure_cookie(
                    ROLE_COOKIE_NAME, user["role"],
                    expires_days=expires_days, httponly=True,
                )
                csrf = _auth.generate_csrf_token()
                self.set_cookie(
                    _auth.CSRF_COOKIE_NAME, csrf,
                    expires_days=expires_days, httponly=False,
                )
                self._write_json({"ok": True, "data": {
                    "enabled": True,
                    "username": user["username"],
                    "role": user["role"],
                    "email": user.get("email"),
                    "nickname": user.get("nickname"),
                    "csrf_token": csrf,
                    "ttl_seconds": ttl_seconds,
                }})
            else:
                self._write_json({"ok": True, "data": {
                    "enabled": False,
                    "username": user["username"],
                    "email": user.get("email"),
                    "nickname": user.get("nickname"),
                    "role": user["role"],
                }})
        except Exception as exc:
            logging.exception("[auth.register] 注册失败")
            self._write_json({"ok": False, "error": str(exc)}, status=500)


# ──────────────── 用户管理（admin） ────────────────


class ListUsersHandler(_BaseAuthHandler, ABC):
    @require_role("admin")
    @gen.coroutine
    def get(self):
        try:
            self._write_json({"ok": True, "data": _users.list_users()})
        except Exception as exc:
            logging.exception("[auth.users] list 失败")
            self._write_json({"ok": False, "error": str(exc)}, status=500)


class SaveUserHandler(_BaseAuthHandler, ABC):
    @require_role("admin")
    @gen.coroutine
    def post(self):
        try:
            try:
                body = json.loads(self.request.body or b"{}")
            except Exception:
                self._write_json({"ok": False, "error": "请求体非 JSON"},
                                 status=400)
                return
            uid = _to_int(body.get("id"))
            password = body.get("password") or ""
            # 只有请求体明确携带的字段才会被更新，避免静默覆盖
            # （例：只传 password 时不应重置 role/enabled）。
            role = (body.get("role") or "").strip() or None
            if "enabled" in body:
                enabled_bool = bool(body.get("enabled"))
            else:
                enabled_bool = None
            try:
                if uid:
                    # Should 8 自保护：管理员不能把自己降为非 admin
                    # 或禁用自己，避免意外锁出。
                    self_username = getattr(self, "current_username", None)
                    target = next(
                        (u for u in _users.list_users() if u["id"] == uid),
                        None,
                    )
                    if (target and self_username
                            and target["username"] == self_username):
                        if role and role != "admin":
                            self._write_json({
                                "ok": False,
                                "error": "不能修改自己的角色为非 admin",
                            }, status=400)
                            return
                        if enabled_bool is False:
                            self._write_json({
                                "ok": False,
                                "error": "不能禁用自己的账号",
                            }, status=400)
                            return
                    user = _users.update_user(
                        uid,
                        role=role,
                        enabled=enabled_bool,
                        password=password if password else None,
                    )
                else:
                    username = (body.get("username") or "").strip()
                    user = _users.create_user(
                        username=username,
                        password=password,
                        role=role or "operator",
                        enabled=enabled_bool if enabled_bool is not None
                        else True,
                    )
            except ValueError as ve:
                self._write_json({"ok": False, "error": str(ve)}, status=400)
                return
            self._write_json({"ok": True, "data": user})
        except Exception as exc:
            logging.exception("[auth.users] save 失败")
            self._write_json({"ok": False, "error": str(exc)}, status=500)


class DeleteUserHandler(_BaseAuthHandler, ABC):
    @require_role("admin")
    @gen.coroutine
    def post(self):
        try:
            try:
                body = json.loads(self.request.body or b"{}")
            except Exception:
                body = {}
            uid = _to_int(body.get("id"))
            if not uid:
                self._write_json({"ok": False, "error": "缺少 id"}, status=400)
                return
            users = _users.list_users()
            target = next((u for u in users if u["id"] == uid), None)
            # Should 8 自保护：不能删除自己
            self_username = getattr(self, "current_username", None)
            if target and self_username and target["username"] == self_username:
                self._write_json({
                    "ok": False, "error": "不能删除自己的账号",
                }, status=400)
                return
            # 安全锁：禁止删除最后一个 enabled admin
            if target and target["role"] == "admin" and target["enabled"]:
                remain = [u for u in users
                          if u["id"] != uid and u["role"] == "admin"
                          and u["enabled"]]
                if not remain:
                    self._write_json({
                        "ok": False,
                        "error": "禁止删除最后一个启用的 admin 账户",
                    }, status=400)
                    return
            _users.delete_user(uid)
            self._write_json({"ok": True})
        except Exception as exc:
            logging.exception("[auth.users] delete 失败")
            self._write_json({"ok": False, "error": str(exc)}, status=500)


# ──────────────── Should 7 审计聚合（admin/operator） ────────────────


_AUDIT_TABLES = (
    ("notification", "cn_stock_notification_config",
     "id, paper_id, channel, modified_by, updated_at, config_version"),
    ("ai_decision", "cn_stock_ai_decision_config",
     "id, source_type, source_id, modified_by, updated_at, config_version"),
    ("im_operator", "cn_stock_im_operator_whitelist",
     "id, channel, operator_id, modified_by, updated_at, NULL"),
)


class AuditListHandler(_BaseAuthHandler, ABC):
    @require_role("admin", "operator")
    @gen.coroutine
    def get(self):
        try:
            limit = _to_int(self.get_argument("limit", "200"), 200) or 200
            limit = max(1, min(1000, limit))
            results: List[dict] = []
            for kind, table, fields in _AUDIT_TABLES:
                try:
                    rows = executeSqlFetch(
                        f"SELECT {fields} FROM `{table}` "
                        f"ORDER BY updated_at DESC LIMIT %s",
                        (limit,))
                except Exception as exc:  # noqa: BLE001
                    logging.debug("[auth.audit] 跳过 %s：%s", table, exc)
                    continue
                for r in rows or []:
                    results.append({
                        "kind": kind,
                        "id": r[0],
                        "ref_a": r[1],
                        "ref_b": r[2],
                        "modified_by": r[3] or "system",
                        "updated_at": r[4],
                        "config_version": r[5],
                    })
            results.sort(
                key=lambda x: (x["updated_at"] or ""), reverse=True)
            self._write_json({"ok": True, "data": results[:limit]})
        except Exception as exc:
            logging.exception("[auth.audit] list 失败")
            self._write_json({"ok": False, "error": str(exc)}, status=500)
