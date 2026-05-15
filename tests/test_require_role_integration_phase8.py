# -*- coding: utf-8 -*-
"""Phase 8 Should 8：require_role 在真实 Tornado dispatch 下的集成测试。"""
from __future__ import annotations

import json
import os
from abc import ABC
from unittest import mock

from tornado import gen
from tornado.testing import AsyncHTTPTestCase
from tornado.web import Application, RequestHandler, create_signed_value

from quantia import auth as _auth
from quantia.auth import require_role
from quantia.auth.decorators import ROLE_COOKIE_NAME


# ───────────── Fake handlers covering role boundaries ─────────────


class _AdminOnly(RequestHandler, ABC):
    @require_role("admin")
    @gen.coroutine
    def post(self):
        self.write(json.dumps({"ok": True, "role": self.current_role,
                               "user": self.current_username}))


class _OperatorOrAdmin(RequestHandler, ABC):
    @require_role("admin", "operator")
    @gen.coroutine
    def post(self):
        self.write(json.dumps({"ok": True, "role": self.current_role}))


class _AdminGet(RequestHandler, ABC):
    @require_role("admin")
    @gen.coroutine
    def get(self):
        self.write(json.dumps({"ok": True, "role": self.current_role}))


SECRET = "phase8-role-integration-secret"


class _Base(AsyncHTTPTestCase):
    def get_app(self) -> Application:
        return Application(
            [
                (r"/admin", _AdminOnly),
                (r"/admin_get", _AdminGet),
                (r"/op", _OperatorOrAdmin),
            ],
            cookie_secret=SECRET,
        )

    def _cookie(self, name, value):
        return create_signed_value(SECRET, name, value).decode("utf-8")

    def _headers(self, *, username=None, role=None, csrf=None):
        cookie_parts = []
        if username:
            cookie_parts.append(
                f"{_auth.SESSION_COOKIE_NAME}={self._cookie(_auth.SESSION_COOKIE_NAME, username)}")
        if role:
            cookie_parts.append(
                f"{ROLE_COOKIE_NAME}={self._cookie(ROLE_COOKIE_NAME, role)}")
        if csrf:
            cookie_parts.append(f"{_auth.CSRF_COOKIE_NAME}={csrf}")
        h = {}
        if cookie_parts:
            h["Cookie"] = "; ".join(cookie_parts)
        if csrf:
            h[_auth.CSRF_HEADER_NAME] = csrf
        return h


# ───────────── 关闭态：直通 ─────────────


class RoleDisabledTests(_Base):
    def setUp(self):
        super().setUp()
        os.environ.pop(_auth.AUTH_ENABLED_ENV, None)

    def test_admin_only_passthrough(self):
        resp = self.fetch("/admin", method="POST", body="{}")
        self.assertEqual(resp.code, 200, resp.body)
        body = json.loads(resp.body)
        self.assertEqual(body["role"], "admin")
        self.assertEqual(body["user"], "system")


# ───────────── 启用态：角色边界 ─────────────


class RoleEnabledTests(_Base):
    def setUp(self):
        super().setUp()
        self._patcher = mock.patch.dict(
            os.environ, {_auth.AUTH_ENABLED_ENV: "true"})
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        super().tearDown()

    def test_viewer_blocked_from_admin_endpoint(self):
        resp = self.fetch(
            "/admin", method="POST", body="{}",
            headers=self._headers(username="alice", role="viewer", csrf="t"),
        )
        self.assertEqual(resp.code, 403)
        self.assertIn(b"viewer", resp.body)

    def test_operator_blocked_from_admin_endpoint(self):
        resp = self.fetch(
            "/admin", method="POST", body="{}",
            headers=self._headers(username="bob", role="operator", csrf="t"),
        )
        self.assertEqual(resp.code, 403)

    def test_admin_passes_admin_endpoint(self):
        resp = self.fetch(
            "/admin", method="POST", body="{}",
            headers=self._headers(username="root", role="admin", csrf="t"),
        )
        self.assertEqual(resp.code, 200, resp.body)
        body = json.loads(resp.body)
        self.assertEqual(body["role"], "admin")
        self.assertEqual(body["user"], "root")

    def test_operator_passes_operator_endpoint(self):
        resp = self.fetch(
            "/op", method="POST", body="{}",
            headers=self._headers(username="bob", role="operator", csrf="t"),
        )
        self.assertEqual(resp.code, 200, resp.body)

    def test_viewer_blocked_from_operator_endpoint(self):
        resp = self.fetch(
            "/op", method="POST", body="{}",
            headers=self._headers(username="zoe", role="viewer", csrf="t"),
        )
        self.assertEqual(resp.code, 403)

    def test_no_session_returns_401(self):
        resp = self.fetch("/admin", method="POST", body="{}")
        self.assertEqual(resp.code, 401)

    def test_get_does_not_require_csrf(self):
        resp = self.fetch(
            "/admin_get",
            headers=self._headers(username="root", role="admin"),
        )
        self.assertEqual(resp.code, 200)

    def test_session_without_role_cookie_defaults_to_viewer(self):
        """role cookie 缺失 → fallback 'viewer'，operator 端点拒绝。"""
        resp = self.fetch(
            "/op", method="POST", body="{}",
            headers=self._headers(username="bob", csrf="t"),  # 无 role cookie
        )
        self.assertEqual(resp.code, 403)


if __name__ == "__main__":
    import unittest
    unittest.main()
