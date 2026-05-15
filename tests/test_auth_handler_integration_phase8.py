# -*- coding: utf-8 -*-
"""Phase 8 鉴权 handler 真实 Tornado 集成测试。

之前的 ``test_require_login_phase8.py`` 用 FakeHandler 单元测试装饰器逻辑，
但 ``@require_login`` 和 ``@gen.coroutine`` 的装饰顺序在真实 Tornado
dispatcher 下能否正常协作，必须用 ``AsyncHTTPTestCase`` 验证。

覆盖：
- ``QUANTIA_AUTH_ENABLED=false``：写接口直通，旧测试基线不变。
- 启用后未登录 → 401 JSON 响应。
- 启用 + login → set-cookie + 后续请求成功。
- 启用 + 登录后 + 缺 CSRF → 403。
- 启用 + 登录后 + CSRF 一致 → 200 业务响应。
"""
from __future__ import annotations

import json
import os
import unittest
from abc import ABC
from typing import Any
from unittest import mock

import bcrypt
from tornado import gen
from tornado.testing import AsyncHTTPTestCase
from tornado.web import Application, RequestHandler

from quantia import auth as _auth
from quantia.auth import require_login


# ─────────── 简化的回显 handler，避开真实 DB / pinia 等依赖 ───────────


class _EchoHandler(RequestHandler, ABC):
    """模拟 NotificationConfig 的 save handler：require_login + 写 JSON。"""

    @require_login
    @gen.coroutine
    def post(self):
        body = json.loads(self.request.body or b"{}")
        # 模拟 modified_by 注入逻辑
        body["modified_by_injected"] = (
            getattr(self, "current_username", None) or "system"
        )
        self.set_header("Content-Type", "application/json; charset=utf-8")
        self.write(json.dumps({"ok": True, "data": body}, ensure_ascii=False))


class _EchoGetHandler(RequestHandler, ABC):
    """模拟 list/detail：require_login 但 GET 不强制 CSRF。"""

    @require_login
    @gen.coroutine
    def get(self):
        self.set_header("Content-Type", "application/json; charset=utf-8")
        self.write(json.dumps({
            "ok": True,
            "username": getattr(self, "current_username", None),
        }))


# ─────────── 测试基类 ───────────


class _BaseAuthIntegrationTest(AsyncHTTPTestCase):
    def get_app(self) -> Application:
        # cookie_secret 必须是固定值，否则每次启动 secure_cookie 都失效。
        return Application(
            [
                (r"/echo", _EchoHandler),
                (r"/echo_get", _EchoGetHandler),
            ],
            cookie_secret="phase8-integration-test-secret",
        )


# ─────────── 默认禁用：旧行为不变 ───────────


class AuthDisabledIntegrationTests(_BaseAuthIntegrationTest):
    def setUp(self) -> None:
        super().setUp()
        # 显式清掉 env，确保 is_auth_enabled() = False
        self._patcher = mock.patch.dict(os.environ, {}, clear=False)
        self._patcher.start()
        os.environ.pop(_auth.AUTH_ENABLED_ENV, None)

    def tearDown(self) -> None:
        self._patcher.stop()
        super().tearDown()

    def test_post_passthrough_without_login(self):
        resp = self.fetch("/echo", method="POST",
                          body=json.dumps({"hello": "world"}))
        self.assertEqual(resp.code, 200, resp.body)
        body = json.loads(resp.body)
        self.assertTrue(body["ok"])
        # 关闭态应注入 'system' 占位
        self.assertEqual(body["data"]["modified_by_injected"], "system")

    def test_get_passthrough(self):
        resp = self.fetch("/echo_get")
        self.assertEqual(resp.code, 200)
        self.assertEqual(json.loads(resp.body)["username"], "system")


# ─────────── 启用：未登录拒绝 + 登录后通过 ───────────


class AuthEnabledIntegrationTests(_BaseAuthIntegrationTest):
    def setUp(self) -> None:
        super().setUp()
        self._patcher = mock.patch.dict(os.environ, {
            _auth.AUTH_ENABLED_ENV: "true",
        })
        self._patcher.start()

    def tearDown(self) -> None:
        self._patcher.stop()
        super().tearDown()

    def _make_session_cookie(self) -> str:
        """直接构造 secure_cookie 字符串绕过 login handler，专注测试装饰器。

        Tornado 的 secure_cookie 协议：使用 ``create_signed_value``。
        """
        from tornado.web import create_signed_value
        value = create_signed_value(
            "phase8-integration-test-secret",
            _auth.SESSION_COOKIE_NAME,
            "alice",
        )
        return value.decode("utf-8")

    def test_post_without_session_returns_401(self):
        resp = self.fetch("/echo", method="POST",
                          body=json.dumps({"foo": 1}))
        self.assertEqual(resp.code, 401)
        body = json.loads(resp.body)
        self.assertFalse(body["ok"])

    def test_get_without_session_returns_401(self):
        resp = self.fetch("/echo_get")
        self.assertEqual(resp.code, 401)

    def test_post_with_session_but_no_csrf_returns_403(self):
        cookie = self._make_session_cookie()
        resp = self.fetch(
            "/echo", method="POST",
            body=json.dumps({"foo": 1}),
            headers={
                "Cookie": f"{_auth.SESSION_COOKIE_NAME}={cookie}",
            },
        )
        self.assertEqual(resp.code, 403)

    def test_post_with_session_and_csrf_succeeds_and_injects_username(self):
        cookie = self._make_session_cookie()
        resp = self.fetch(
            "/echo", method="POST",
            body=json.dumps({"foo": 1}),
            headers={
                "Cookie": (
                    f"{_auth.SESSION_COOKIE_NAME}={cookie}; "
                    f"{_auth.CSRF_COOKIE_NAME}=tok-1"
                ),
                _auth.CSRF_HEADER_NAME: "tok-1",
            },
        )
        self.assertEqual(resp.code, 200, resp.body)
        body = json.loads(resp.body)
        self.assertTrue(body["ok"])
        # 关键：current_username 被正确注入。
        self.assertEqual(body["data"]["modified_by_injected"], "alice")

    def test_get_with_session_does_not_require_csrf(self):
        cookie = self._make_session_cookie()
        resp = self.fetch(
            "/echo_get",
            headers={"Cookie": f"{_auth.SESSION_COOKIE_NAME}={cookie}"},
        )
        self.assertEqual(resp.code, 200)
        self.assertEqual(json.loads(resp.body)["username"], "alice")


# ─────────── 端到端：login → 用 cookie 调写接口 ───────────


class _LoginPlusEchoApp(_BaseAuthIntegrationTest):
    def get_app(self) -> Application:
        from quantia.web.authHandler import (
            LoginHandler, LogoutHandler, MeHandler,
        )
        return Application(
            [
                (r"/api/auth/login", LoginHandler),
                (r"/api/auth/logout", LogoutHandler),
                (r"/api/auth/me", MeHandler),
                (r"/echo", _EchoHandler),
            ],
            cookie_secret="phase8-integration-test-secret",
        )


class LoginEndToEndTests(_LoginPlusEchoApp):
    def setUp(self) -> None:
        super().setUp()
        self._hash = bcrypt.hashpw(
            b"goodpass", bcrypt.gensalt()).decode("utf-8")
        self._patcher = mock.patch.dict(os.environ, {
            _auth.AUTH_ENABLED_ENV: "true",
            _auth.ADMIN_USER_ENV: "admin",
            _auth.ADMIN_PASS_BCRYPT_ENV: self._hash,
        })
        self._patcher.start()

    def tearDown(self) -> None:
        self._patcher.stop()
        super().tearDown()

    def _parse_cookies(self, headers) -> dict:
        result = {}
        for raw in headers.get_list("Set-Cookie"):
            # 简化解析：仅取 name=value，丢掉属性。
            head = raw.split(";", 1)[0]
            if "=" in head:
                k, v = head.split("=", 1)
                result[k.strip()] = v.strip()
        return result

    def test_full_login_then_save(self):
        # 1. 错误密码 → 401
        bad = self.fetch(
            "/api/auth/login", method="POST",
            body=json.dumps({"username": "admin", "password": "wrong"}),
        )
        self.assertEqual(bad.code, 401)

        # 2. 正确密码 → 200 + cookie
        ok = self.fetch(
            "/api/auth/login", method="POST",
            body=json.dumps({"username": "admin", "password": "goodpass"}),
        )
        self.assertEqual(ok.code, 200, ok.body)
        cookies = self._parse_cookies(ok.headers)
        self.assertIn(_auth.SESSION_COOKIE_NAME, cookies)
        self.assertIn(_auth.CSRF_COOKIE_NAME, cookies)
        sess = cookies[_auth.SESSION_COOKIE_NAME]
        csrf = cookies[_auth.CSRF_COOKIE_NAME]
        login_data = json.loads(ok.body)["data"]
        self.assertEqual(login_data["username"], "admin")
        self.assertEqual(login_data["csrf_token"], csrf)

        # 3. 用拿到的 cookie 调写接口
        save = self.fetch(
            "/echo", method="POST",
            body=json.dumps({"key": "value"}),
            headers={
                "Cookie": (
                    f"{_auth.SESSION_COOKIE_NAME}={sess}; "
                    f"{_auth.CSRF_COOKIE_NAME}={csrf}"
                ),
                _auth.CSRF_HEADER_NAME: csrf,
            },
        )
        self.assertEqual(save.code, 200, save.body)
        body = json.loads(save.body)
        self.assertEqual(body["data"]["modified_by_injected"], "admin")


if __name__ == "__main__":
    unittest.main()
