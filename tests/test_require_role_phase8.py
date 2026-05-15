# -*- coding: utf-8 -*-
"""Phase 8 Should 8：require_role 装饰器单元测试（不需要真实 Tornado）。"""
from __future__ import annotations

import json
import os
from unittest import mock

import pytest

from quantia import auth as _auth
from quantia.auth import decorators as _dec
from quantia.auth.decorators import (
    DEFAULT_DISABLED_ROLE, ROLE_COOKIE_NAME, require_role,
)


class _FakeRequest:
    def __init__(self, method="POST", headers=None):
        self.method = method
        self.headers = headers or {}


class _FakeHandler:
    """模拟 Tornado handler 的最小子集。"""

    def __init__(self, *, method="POST", username=None, role=None,
                 csrf_cookie=None, csrf_header=None):
        self.request = _FakeRequest(
            method=method,
            headers={_auth.CSRF_HEADER_NAME: csrf_header} if csrf_header else {},
        )
        self._username = username
        self._role = role
        self._csrf = csrf_cookie
        self.status = 200
        self.body = None
        self.finished = False
        self.current_username = None
        self.current_role = None

    # secure_cookie 接口
    def get_secure_cookie(self, name, max_age_days=None):
        if name == _auth.SESSION_COOKIE_NAME and self._username:
            return self._username.encode("utf-8")
        if name == ROLE_COOKIE_NAME and self._role:
            return self._role.encode("utf-8")
        return None

    def get_cookie(self, name):
        if name == _auth.CSRF_COOKIE_NAME:
            return self._csrf
        return None

    def set_status(self, code):
        self.status = code

    def set_header(self, *_a, **_kw):
        pass

    def write(self, data):
        self.body = data

    def finish(self):
        self.finished = True


# ───── decorator behaviour ─────


@pytest.fixture
def enable_auth(monkeypatch):
    monkeypatch.setenv(_auth.AUTH_ENABLED_ENV, "true")


def _ok(self):
    self.body = json.dumps({"ok": True, "user": self.current_username,
                            "role": self.current_role})
    return "called"


def test_disabled_passthrough():
    h = _FakeHandler()
    res = require_role("admin")(_ok)(h)
    assert res == "called"
    assert h.current_username == "system"
    assert h.current_role == DEFAULT_DISABLED_ROLE


def test_enabled_no_session_returns_401(enable_auth):
    h = _FakeHandler()
    require_role("admin")(_ok)(h)
    assert h.status == 401
    assert h.finished


def test_enabled_session_no_csrf_returns_403(enable_auth):
    h = _FakeHandler(username="bob", role="admin")
    require_role("admin")(_ok)(h)
    assert h.status == 403


def test_enabled_session_csrf_role_mismatch_returns_403(enable_auth):
    h = _FakeHandler(username="bob", role="viewer",
                     csrf_cookie="t1", csrf_header="t1")
    require_role("admin")(_ok)(h)
    assert h.status == 403
    assert "viewer" in (h.body or "")


def test_enabled_session_csrf_role_match_passes(enable_auth):
    h = _FakeHandler(username="bob", role="admin",
                     csrf_cookie="t1", csrf_header="t1")
    res = require_role("admin", "operator")(_ok)(h)
    assert res == "called"
    assert h.current_username == "bob"
    assert h.current_role == "admin"


def test_get_does_not_require_csrf(enable_auth):
    h = _FakeHandler(method="GET", username="bob", role="operator")
    res = require_role("operator", "admin")(_ok)(h)
    assert res == "called"


def test_default_role_when_cookie_missing(enable_auth):
    """role cookie 缺失 → fallback 为 'viewer'（最保守）。"""
    h = _FakeHandler(username="bob", role=None,
                     csrf_cookie="t", csrf_header="t")
    # operator 端点应拒绝 'viewer' 默认值
    require_role("operator", "admin")(_ok)(h)
    assert h.status == 403


def test_require_role_rejects_empty_args():
    with pytest.raises(ValueError):
        require_role()
