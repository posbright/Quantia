# -*- coding: utf-8 -*-
"""Phase 8 require_login 装饰器单元测试。

不启动真正的 Tornado server；通过 Mock 模拟 RequestHandler 的关键方法
（``get_secure_cookie`` / ``get_cookie`` / ``set_status`` /
``set_header`` / ``write`` / ``finish`` / ``request.method``），验证：

- ``QUANTIA_AUTH_ENABLED=false`` → 装饰器直通，``current_username='system'``。
- 启用后未登录 → 401，原方法不被调用。
- 启用 + 已登录 + 写操作 + CSRF 一致 → 通过，``current_username`` 注入。
- 启用 + 已登录 + 写操作 + CSRF 不一致 → 403。
- 启用 + 已登录 + 读操作（GET）→ 不强制 CSRF。
"""
from __future__ import annotations

import json
import os
import unittest
from unittest import mock

from quantia.auth import (
    AUTH_ENABLED_ENV, CSRF_COOKIE_NAME, CSRF_HEADER_NAME,
    SESSION_COOKIE_NAME, require_login,
)


class _FakeRequest:
    def __init__(self, method: str = "POST",
                 csrf_header: str | None = None):
        self.method = method
        self.headers = {CSRF_HEADER_NAME: csrf_header} if csrf_header else {}
        # MutableMapping-like get
        if not csrf_header:
            self.headers = {}


class _FakeHandler:
    """模拟 Tornado RequestHandler 关键 API。"""

    def __init__(self, *, http_method: str = "POST",
                 secure_cookie_value: bytes | None = None,
                 csrf_cookie: str | None = None,
                 csrf_header: str | None = None):
        self._secure_cookie = secure_cookie_value
        self._csrf_cookie = csrf_cookie
        self.request = _FakeRequest(http_method, csrf_header)
        self.status = None
        self.headers_set = {}
        self.body_chunks = []
        self.finished = False
        self.current_username: str | None = None

    def get_secure_cookie(self, name, max_age_days=None):
        return self._secure_cookie if name == SESSION_COOKIE_NAME else None

    def get_cookie(self, name):
        return self._csrf_cookie if name == CSRF_COOKIE_NAME else None

    def set_status(self, status):
        self.status = status

    def set_header(self, name, value):
        self.headers_set[name] = value

    def write(self, chunk):
        self.body_chunks.append(chunk)

    def finish(self):
        self.finished = True

    @property
    def body_json(self):
        if not self.body_chunks:
            return None
        return json.loads("".join(self.body_chunks))


def _make_decorated(captured: list):
    @require_login
    def post(self):
        captured.append(self.current_username)
        return "ok"
    return post


class RequireLoginDisabledTests(unittest.TestCase):
    def setUp(self) -> None:
        self.captured: list = []
        self.method = _make_decorated(self.captured)

    def test_disabled_passthrough_sets_system_username(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(AUTH_ENABLED_ENV, None)
            handler = _FakeHandler()
            result = self.method(handler)
            self.assertEqual(result, "ok")
            self.assertEqual(handler.current_username, "system")
            self.assertEqual(self.captured, ["system"])
            self.assertIsNone(handler.status)
            self.assertFalse(handler.finished)


class RequireLoginEnabledTests(unittest.TestCase):
    def setUp(self) -> None:
        self.captured: list = []
        self.method = _make_decorated(self.captured)
        self.env_patch = mock.patch.dict(
            os.environ, {AUTH_ENABLED_ENV: "true"})
        self.env_patch.start()

    def tearDown(self) -> None:
        self.env_patch.stop()

    def test_no_session_returns_401(self):
        handler = _FakeHandler(secure_cookie_value=None)
        self.method(handler)
        self.assertEqual(handler.status, 401)
        self.assertTrue(handler.finished)
        self.assertEqual(self.captured, [])
        self.assertEqual(handler.body_json["ok"], False)

    def test_logged_in_csrf_match_post_passes(self):
        handler = _FakeHandler(
            http_method="POST",
            secure_cookie_value=b"alice",
            csrf_cookie="tok-1",
            csrf_header="tok-1",
        )
        result = self.method(handler)
        self.assertEqual(result, "ok")
        self.assertEqual(handler.current_username, "alice")
        self.assertEqual(self.captured, ["alice"])
        self.assertIsNone(handler.status)

    def test_logged_in_csrf_mismatch_returns_403(self):
        handler = _FakeHandler(
            http_method="POST",
            secure_cookie_value=b"alice",
            csrf_cookie="tok-1",
            csrf_header="tok-2",
        )
        self.method(handler)
        self.assertEqual(handler.status, 403)
        self.assertTrue(handler.finished)
        self.assertEqual(self.captured, [])

    def test_logged_in_csrf_missing_header_returns_403(self):
        handler = _FakeHandler(
            http_method="POST",
            secure_cookie_value=b"alice",
            csrf_cookie="tok-1",
            csrf_header=None,
        )
        self.method(handler)
        self.assertEqual(handler.status, 403)
        self.assertEqual(self.captured, [])

    def test_logged_in_get_does_not_require_csrf(self):
        handler = _FakeHandler(
            http_method="GET",
            secure_cookie_value=b"alice",
            csrf_cookie=None,
            csrf_header=None,
        )
        result = self.method(handler)
        self.assertEqual(result, "ok")
        self.assertEqual(handler.current_username, "alice")


if __name__ == "__main__":
    unittest.main()
