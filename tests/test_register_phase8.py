"""Phase 8 self-registration tests (no DB required).

Covers pure logic that does not depend on MySQL:
- email_code env helpers (is_register_enabled / is_dev_mode / TTL constants)
- request_code throttling validation (rejects bad email)
- find_user_by_identifier dispatch logic via monkeypatching
- register_user input validation paths via monkeypatching
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

from quantia.auth import email_code, users


class TestEmailCodeEnv(unittest.TestCase):
    def test_register_enabled_default_true(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("QUANTIA_REGISTER_ENABLED", None)
            self.assertTrue(email_code.is_register_enabled())

    def test_register_disabled(self):
        with mock.patch.dict(os.environ, {"QUANTIA_REGISTER_ENABLED": "false"}):
            self.assertFalse(email_code.is_register_enabled())

    def test_dev_mode_default_false(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("QUANTIA_REGISTER_DEV_MODE", None)
            self.assertFalse(email_code.is_dev_mode())

    def test_dev_mode_truthy(self):
        with mock.patch.dict(os.environ, {"QUANTIA_REGISTER_DEV_MODE": "1"}):
            self.assertTrue(email_code.is_dev_mode())

    def test_constants(self):
        self.assertEqual(email_code.CODE_TTL_MINUTES, 5)
        self.assertEqual(email_code.RESEND_COOLDOWN_SECONDS, 60)
        self.assertGreaterEqual(email_code.DAILY_LIMIT_PER_EMAIL, 5)


class TestRequestCodeValidation(unittest.TestCase):
    def test_rejects_empty_email(self):
        with self.assertRaises(ValueError):
            email_code.request_code("", purpose="register")

    def test_rejects_bad_email_format(self):
        with self.assertRaises(ValueError):
            email_code.request_code("not-an-email", purpose="register")


class TestFindUserByIdentifier(unittest.TestCase):
    def test_email_dispatch(self):
        with mock.patch.object(users, "get_user_by_email",
                               return_value={"id": 1, "username": "alice"}) as m_email, \
             mock.patch.object(users, "get_user") as m_user, \
             mock.patch.object(users, "get_user_by_nickname") as m_nick:
            r = users.find_user_by_identifier("alice@example.com")
            self.assertEqual(r["username"], "alice")
            m_email.assert_called_once()
            m_user.assert_not_called()
            m_nick.assert_not_called()

    def test_username_then_nickname_fallback(self):
        with mock.patch.object(users, "get_user_by_email") as m_email, \
             mock.patch.object(users, "get_user",
                               return_value=None) as m_user, \
             mock.patch.object(users, "get_user_by_nickname",
                               return_value={"id": 2, "username": "bob"}) as m_nick:
            r = users.find_user_by_identifier("BobNick")
            self.assertEqual(r["username"], "bob")
            m_email.assert_not_called()
            m_user.assert_called_once()
            m_nick.assert_called_once()


class TestRegisterUserValidation(unittest.TestCase):
    def test_rejects_invalid_email(self):
        with self.assertRaises(ValueError):
            users.register_user(email="bad", password="abcdef", nickname="x")

    def test_rejects_empty_nickname(self):
        with self.assertRaises(ValueError):
            users.register_user(email="a@b.com", password="abcdef", nickname="")

    def test_rejects_invalid_role(self):
        with self.assertRaises(ValueError):
            users.register_user(email="a@b.com", password="abcdef",
                                nickname="x", role="not-a-role")


if __name__ == "__main__":
    unittest.main()
