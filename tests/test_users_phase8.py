# -*- coding: utf-8 -*-
"""Phase 8 Should 8：DB 用户与角色单元测试（mock DB 层）。"""
from __future__ import annotations

from unittest import mock

import bcrypt
import pytest

import quantia.auth.users as users_mod


class _FakeUserDB:
    """简化的用户表内存实现：模拟 cn_stock_admin_user。"""

    def __init__(self):
        self.rows = []  # list[dict]
        self._auto_id = 0
        self.created = False

    # ── lib/database 层接口 ──
    def executeSql(self, sql, params=()):
        s = sql.strip().lower()
        if s.startswith("create table"):
            self.created = True
            return None
        if s.startswith("insert into cn_stock_admin_user"):
            self._auto_id += 1
            username, pw_hash, role, enabled = params[0], params[1], params[2], params[3]
            email = params[4] if len(params) > 4 else None
            nickname = params[5] if len(params) > 5 else None
            self.rows.append({
                "id": self._auto_id, "username": username,
                "password_bcrypt": pw_hash, "role": role,
                "enabled": int(enabled), "last_login_at": None,
                "email": email, "nickname": nickname,
                "created_at": "2026-05-10 00:00:00",
                "updated_at": "2026-05-10 00:00:00",
            })
            return None
        if s.startswith("update cn_stock_admin_user"):
            # 简易实现：从 SQL 解析不出 SET 顺序，让单元测试只校验关键路径
            uid = params[-1]
            row = next((r for r in self.rows if r["id"] == uid), None)
            if row is None:
                return None
            # 解析 set 子句的字段名（有限集）
            set_part = s.split("set", 1)[1].split("where", 1)[0]
            fields = [seg.split("=")[0].strip()
                      for seg in set_part.split(",")]
            for k, v in zip(fields, params[:-1]):
                if k == "last_login_at":
                    row["last_login_at"] = "2026-05-10 12:00:00"
                else:
                    row[k] = v
            return None
        if s.startswith("delete from cn_stock_admin_user"):
            uid = params[0]
            self.rows = [r for r in self.rows if r["id"] != uid]
            return None
        return None

    def executeSqlFetch(self, sql, params=()):
        s = sql.strip().lower()
        if s.startswith("select id from cn_stock_admin_user where enabled=1"):
            for r in self.rows:
                if r["enabled"]:
                    return [(r["id"],)]
            return []
        if s.startswith("select password_bcrypt from cn_stock_admin_user"):
            uid = params[0]
            row = next((r for r in self.rows if r["id"] == uid), None)
            return [(row["password_bcrypt"],)] if row else []
        if "from cn_stock_admin_user" in s:
            # 全字段 SELECT
            if "where username" in s:
                username = params[0]
                rows = [r for r in self.rows if r["username"] == username]
            elif "where id" in s:
                uid = params[0]
                rows = [r for r in self.rows if r["id"] == uid]
            else:
                rows = list(self.rows)
            return [
                (r["id"], r["username"], r["password_bcrypt"], r["role"],
                 r["enabled"], r["last_login_at"],
                 r["created_at"], r["updated_at"])
                for r in rows
            ]
        return []


@pytest.fixture
def fake_db(monkeypatch):
    fake = _FakeUserDB()
    monkeypatch.setattr(users_mod, "executeSql", fake.executeSql)
    monkeypatch.setattr(users_mod, "executeSqlFetch", fake.executeSqlFetch)
    # 强制每个用例重新触发表创建
    monkeypatch.setattr(users_mod, "_TABLE_READY", False, raising=False)
    return fake


# ───────── ensure_admin_user_table ─────────


def test_ensure_table_runs_once(fake_db, monkeypatch):
    users_mod.ensure_admin_user_table()
    assert fake_db.created is True
    # 第二次调用不再 create
    fake_db.created = False
    users_mod.ensure_admin_user_table()
    assert fake_db.created is False


# ───────── create_user ─────────


def test_create_user_minimal(fake_db):
    user = users_mod.create_user("alice", "longpass", role="operator")
    assert user["id"] == 1
    assert user["username"] == "alice"
    assert user["role"] == "operator"
    assert user["enabled"] is True
    # 密码不应回传
    assert "password_bcrypt" not in user


def test_create_user_rejects_short_password(fake_db):
    with pytest.raises(ValueError, match="密码"):
        users_mod.create_user("bob", "abc", role="viewer")


def test_create_user_rejects_invalid_role(fake_db):
    with pytest.raises(ValueError, match="role"):
        users_mod.create_user("bob", "longpass", role="superuser")


def test_create_user_rejects_duplicate(fake_db):
    users_mod.create_user("alice", "longpass", role="admin")
    with pytest.raises(ValueError, match="已存在"):
        users_mod.create_user("alice", "longpass", role="viewer")


def test_create_user_rejects_empty_username(fake_db):
    with pytest.raises(ValueError):
        users_mod.create_user("", "longpass")


# ───────── update_user ─────────


def test_update_user_role_and_enabled(fake_db):
    u = users_mod.create_user("alice", "longpass", role="operator")
    upd = users_mod.update_user(u["id"], role="admin", enabled=False)
    assert upd["role"] == "admin"
    assert upd["enabled"] is False


def test_update_user_password_rehashes(fake_db):
    u = users_mod.create_user("alice", "longpass", role="operator")
    users_mod.update_user(u["id"], password="newlongpass")
    # 新密码应能登录
    res = users_mod.authenticate("alice", "newlongpass")
    assert res is not None
    assert res["role"] == "operator"


def test_update_user_missing_id(fake_db):
    with pytest.raises(ValueError, match="不存在"):
        users_mod.update_user(99, role="admin")


# ───────── delete_user ─────────


def test_delete_user(fake_db):
    u = users_mod.create_user("alice", "longpass", role="operator")
    users_mod.delete_user(u["id"])
    assert users_mod.get_user("alice") is None


# ───────── authenticate ─────────


def test_authenticate_db_success(fake_db):
    users_mod.create_user("alice", "longpass", role="operator")
    res = users_mod.authenticate("alice", "longpass")
    assert res == {"username": "alice", "role": "operator", "email": None, "nickname": None, "source": "db"}


def test_authenticate_db_wrong_password_no_env_fallback(
        fake_db, monkeypatch):
    """DB 命中用户名但密码错 → 不回退 env，避免猜测攻击。"""
    users_mod.create_user("alice", "longpass", role="operator")
    monkeypatch.setenv("QUANTIA_ADMIN_USER", "alice")
    pw_hash = bcrypt.hashpw(b"envpass", bcrypt.gensalt()).decode()
    monkeypatch.setenv("QUANTIA_ADMIN_PASS_BCRYPT", pw_hash)
    assert users_mod.authenticate("alice", "envpass") is None
    assert users_mod.authenticate("alice", "wrong") is None


def test_authenticate_disabled_db_user_blocks_env_fallback(
        fake_db, monkeypatch):
    """DB 中同名用户被 disabled → 不能再走 env fallback。

    这避免「管理员禁用某账号后该账号仍可通过同名 env 单账户登录」这一提权问题。
    """
    u = users_mod.create_user("admin", "dbpass", role="admin")
    users_mod.update_user(u["id"], enabled=False)
    pw_hash = bcrypt.hashpw(b"envpass", bcrypt.gensalt()).decode()
    monkeypatch.setenv("QUANTIA_ADMIN_USER", "admin")
    monkeypatch.setenv("QUANTIA_ADMIN_PASS_BCRYPT", pw_hash)
    # 同名账号在 DB 中 disabled → 拒绝登录（不回退 env）
    assert users_mod.authenticate("admin", "envpass") is None
    assert users_mod.authenticate("admin", "dbpass") is None


def test_authenticate_env_only_no_db(fake_db, monkeypatch):
    pw_hash = bcrypt.hashpw(b"envpass", bcrypt.gensalt()).decode()
    monkeypatch.setenv("QUANTIA_ADMIN_USER", "root")
    monkeypatch.setenv("QUANTIA_ADMIN_PASS_BCRYPT", pw_hash)
    res = users_mod.authenticate("root", "envpass")
    assert res == {"username": "root", "role": "admin", "source": "env"}


def test_authenticate_empty_inputs(fake_db):
    assert users_mod.authenticate("", "x") is None
    assert users_mod.authenticate("alice", "") is None


def test_has_any_enabled_user(fake_db):
    assert users_mod.has_any_enabled_user() is False
    u = users_mod.create_user("alice", "longpass", role="admin")
    assert users_mod.has_any_enabled_user() is True
    users_mod.update_user(u["id"], enabled=False)
    assert users_mod.has_any_enabled_user() is False


def test_list_users_excludes_password_hash(fake_db):
    users_mod.create_user("alice", "longpass", role="admin")
    users_mod.create_user("bob", "longpass", role="viewer")
    rows = users_mod.list_users()
    assert len(rows) == 2
    for r in rows:
        assert "password_bcrypt" not in r
