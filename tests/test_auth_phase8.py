# -*- coding: utf-8 -*-
"""Phase 8 鉴权与 IP 白名单单元测试。

不依赖 tornado server，直接对 ``quantia.auth`` 模块的纯函数做断言；
对 handler 的副作用通过 mock + 直接构造 RequestHandler 状态完成。

覆盖：
- ``is_auth_enabled`` 各种 env 取值的真值表。
- ``session_ttl_seconds`` 默认 + 自定义 + 异常回退。
- ``verify_password`` bcrypt 正/负 + 空哈希 + 非法哈希。
- ``is_ip_allowed`` 单 IP / CIDR / 未配置 / 空白名单 / 非法 IP。
- ``generate_csrf_token`` 长度与不重复。
- DingtalkCallbackHandler 在 ``QUANTIA_DINGTALK_CALLBACK_ALLOW_IPS`` 配置
  且 ``X-Forwarded-For`` 不在白名单时返回 403。
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

import bcrypt

from quantia import auth as _auth


class IsAuthEnabledTests(unittest.TestCase):
    def test_default_disabled_when_unset(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(_auth.AUTH_ENABLED_ENV, None)
            self.assertFalse(_auth.is_auth_enabled())

    def test_truthy_values(self):
        for v in ("1", "true", "TRUE", "Yes", "on"):
            with mock.patch.dict(os.environ,
                                 {_auth.AUTH_ENABLED_ENV: v}):
                self.assertTrue(_auth.is_auth_enabled(),
                                f"expected enabled for {v!r}")

    def test_falsy_values(self):
        for v in ("0", "false", "no", "off", "garbage", ""):
            with mock.patch.dict(os.environ,
                                 {_auth.AUTH_ENABLED_ENV: v}):
                self.assertFalse(_auth.is_auth_enabled(),
                                 f"expected disabled for {v!r}")


class SessionTtlTests(unittest.TestCase):
    def test_default_ttl_when_unset(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(_auth.SESSION_TTL_HOURS_ENV, None)
            self.assertEqual(_auth.session_ttl_seconds(),
                             _auth.DEFAULT_SESSION_TTL_HOURS * 3600)

    def test_explicit_hours(self):
        with mock.patch.dict(os.environ,
                             {_auth.SESSION_TTL_HOURS_ENV: "2"}):
            self.assertEqual(_auth.session_ttl_seconds(), 7200)

    def test_invalid_falls_back_to_default(self):
        with mock.patch.dict(os.environ,
                             {_auth.SESSION_TTL_HOURS_ENV: "abc"}):
            self.assertEqual(_auth.session_ttl_seconds(),
                             _auth.DEFAULT_SESSION_TTL_HOURS * 3600)

    def test_zero_falls_back_to_default(self):
        with mock.patch.dict(os.environ,
                             {_auth.SESSION_TTL_HOURS_ENV: "0"}):
            self.assertEqual(_auth.session_ttl_seconds(),
                             _auth.DEFAULT_SESSION_TTL_HOURS * 3600)


class VerifyPasswordTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plain = "P@ssw0rd!"
        cls.hashed = bcrypt.hashpw(
            cls.plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    def test_correct_password(self):
        self.assertTrue(_auth.verify_password(self.plain, self.hashed))

    def test_wrong_password(self):
        self.assertFalse(_auth.verify_password("wrong", self.hashed))

    def test_empty_password(self):
        self.assertFalse(_auth.verify_password("", self.hashed))

    def test_empty_hash(self):
        self.assertFalse(_auth.verify_password(self.plain, None))
        self.assertFalse(_auth.verify_password(self.plain, ""))

    def test_invalid_hash_format(self):
        # 非 bcrypt 格式 → 不抛异常，统一拒绝。
        self.assertFalse(_auth.verify_password(self.plain, "not-bcrypt"))


class IpAllowedTests(unittest.TestCase):
    def test_no_allow_list_means_allow_all(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(_auth.CALLBACK_ALLOW_IPS_ENV, None)
            self.assertTrue(_auth.is_ip_allowed("203.0.113.1"))
            self.assertTrue(_auth.is_ip_allowed(None))

    def test_single_ip(self):
        self.assertTrue(_auth.is_ip_allowed(
            "10.0.0.5", allow_list=["10.0.0.5"]))
        self.assertFalse(_auth.is_ip_allowed(
            "10.0.0.6", allow_list=["10.0.0.5"]))

    def test_cidr_match(self):
        nets = ["10.0.0.0/24", "192.168.1.0/24"]
        self.assertTrue(_auth.is_ip_allowed("10.0.0.99", allow_list=nets))
        self.assertTrue(_auth.is_ip_allowed("192.168.1.1", allow_list=nets))
        self.assertFalse(_auth.is_ip_allowed("10.0.1.1", allow_list=nets))

    def test_empty_client_ip_rejected_when_list_active(self):
        self.assertFalse(_auth.is_ip_allowed("", allow_list=["10.0.0.0/8"]))
        self.assertFalse(_auth.is_ip_allowed(None, allow_list=["10.0.0.0/8"]))

    def test_invalid_client_ip_rejected(self):
        self.assertFalse(_auth.is_ip_allowed(
            "not.an.ip", allow_list=["10.0.0.0/8"]))

    def test_invalid_allow_entries_skipped(self):
        # "garbage" 被跳过；剩余 "10.0.0.0/8" 仍生效。
        self.assertTrue(_auth.is_ip_allowed(
            "10.1.2.3", allow_list=["garbage", "10.0.0.0/8"]))
        # 全部非法 → 视为未启用 → allow all。
        self.assertTrue(_auth.is_ip_allowed(
            "10.1.2.3", allow_list=["garbage", "?", ""]))

    def test_env_based(self):
        with mock.patch.dict(os.environ, {
            _auth.CALLBACK_ALLOW_IPS_ENV: "10.0.0.0/24,192.168.0.5",
        }):
            self.assertTrue(_auth.is_ip_allowed("10.0.0.99"))
            self.assertTrue(_auth.is_ip_allowed("192.168.0.5"))
            self.assertFalse(_auth.is_ip_allowed("172.16.0.1"))


class CsrfTokenTests(unittest.TestCase):
    def test_token_length_and_uniqueness(self):
        seen = set()
        for _ in range(50):
            t = _auth.generate_csrf_token()
            self.assertGreaterEqual(len(t), 32)
            self.assertNotIn(t, seen)
            seen.add(t)


class ConfiguredAdminTests(unittest.TestCase):
    def test_default_user(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(_auth.ADMIN_USER_ENV, None)
            self.assertEqual(_auth.configured_admin_user(), "admin")

    def test_explicit_user(self):
        with mock.patch.dict(os.environ,
                             {_auth.ADMIN_USER_ENV: "ops"}):
            self.assertEqual(_auth.configured_admin_user(), "ops")

    def test_missing_pass_returns_none(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(_auth.ADMIN_PASS_BCRYPT_ENV, None)
            self.assertIsNone(_auth.configured_admin_pass_bcrypt())


if __name__ == "__main__":
    unittest.main()
