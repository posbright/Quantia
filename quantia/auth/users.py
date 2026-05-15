# -*- coding: utf-8 -*-
"""Phase 8 Should 8：DB 持久化的多账户与角色。

设计与之前的「单管理员 env 注入」共存：

- 当数据库 ``cn_stock_admin_user`` 表中存在启用账户时，登录优先走 DB 校验。
- 表为空（典型场景：刚启用鉴权但未 bootstrap 任何账户）时，仍可使用
  ``QUANTIA_ADMIN_USER`` / ``QUANTIA_ADMIN_PASS_BCRYPT`` 这一对 env 单账户登录，
  且角色固定为 ``admin``，方便首次使用者通过 env 登录后再创建协作账户。
- 表存在且有 enabled 行时，env 单账户继续可用作为 ``admin`` 救援通道，但只有当
  env 用户名与 DB 中任一 enabled 账户都不冲突时才接受（避免 env 静悄悄地覆盖 DB 用户）。

角色（与文档 §8.2 一致）：

- ``admin``  —— 可改实盘开关、IP 白名单、用户管理、AI gate 配置等高危操作。
- ``operator`` —— 可读写 notification / ai-config / im-operator 这三类业务配置。
- ``viewer`` —— 仅读，所有 ``/save`` ``/delete`` 写操作返回 403。

数据库迁移
==========

启动时由 :func:`ensure_admin_user_table` 自动创建表（与文档 §8.4 SQL 等价）。
未启用鉴权时不会自动创建表，避免污染纯回测部署的 DB。
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional

from quantia.lib.database import executeSql, executeSqlFetch

from . import (
    ADMIN_PASS_BCRYPT_ENV, ADMIN_USER_ENV,
    configured_admin_pass_bcrypt, configured_admin_user, verify_password,
)


VALID_ROLES = ("admin", "operator", "viewer")
TABLE_NAME = "cn_stock_admin_user"

_TABLE_READY = False


def _row_to_dict(row) -> Dict[str, Any]:
    if not row:
        return {}
    return {
        "id": int(row[0]),
        "username": row[1],
        # password_bcrypt 故意不返回前端，避免泄漏
        "role": row[3] or "operator",
        "enabled": bool(row[4]),
        "last_login_at": row[5],
        "created_at": row[6],
        "updated_at": row[7],
        "email": row[8] if len(row) > 8 else None,
        "nickname": row[9] if len(row) > 9 else None,
    }


def ensure_admin_user_table(force: bool = False) -> None:
    """幂等创建 ``cn_stock_admin_user`` 表。失败仅 warning 不抛。

    会同时执行 email/nickname 列的兼容性迁移（旧库无此列时自动 ALTER）。
    """
    global _TABLE_READY
    if _TABLE_READY and not force:
        return
    sql = f"""
        CREATE TABLE IF NOT EXISTS `{TABLE_NAME}` (
          `id` INT AUTO_INCREMENT PRIMARY KEY,
          `username` VARCHAR(64) NOT NULL UNIQUE,
          `password_bcrypt` VARCHAR(120) NOT NULL,
          `role` ENUM('admin','operator','viewer') NOT NULL DEFAULT 'operator',
          `enabled` TINYINT(1) NOT NULL DEFAULT 1,
          `last_login_at` DATETIME NULL,
          `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
          `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
          `email` VARCHAR(120) NULL,
          `nickname` VARCHAR(64) NULL,
          UNIQUE KEY `uk_email` (`email`),
          UNIQUE KEY `uk_nickname` (`nickname`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """.strip()
    try:
        executeSql(sql)
        # 老库兼容性迁移：若列不存在则 ALTER 添加（容忍重复执行报错）
        for ddl in (
            f"ALTER TABLE `{TABLE_NAME}` ADD COLUMN `email` VARCHAR(120) NULL",
            f"ALTER TABLE `{TABLE_NAME}` ADD COLUMN `nickname` VARCHAR(64) NULL",
            f"ALTER TABLE `{TABLE_NAME}` ADD UNIQUE KEY `uk_email` (`email`)",
            f"ALTER TABLE `{TABLE_NAME}` ADD UNIQUE KEY `uk_nickname` (`nickname`)",
        ):
            try:
                executeSql(ddl)
            except Exception:  # noqa: BLE001
                # 列/索引已存在则忽略
                pass
        _TABLE_READY = True
    except Exception as exc:  # noqa: BLE001
        logging.warning("[auth.users] 创建 %s 失败: %s", TABLE_NAME, exc)


def _hash_password(plain: str) -> str:
    if not plain or len(plain) < 6:
        raise ValueError("密码至少 6 位")
    import bcrypt
    return bcrypt.hashpw(plain.encode("utf-8"),
                         bcrypt.gensalt()).decode("utf-8")


# ───────────────── 查询 ─────────────────


_FIELDS = ("id, username, password_bcrypt, role, enabled, "
           "last_login_at, created_at, updated_at, email, nickname")


def has_any_enabled_user() -> bool:
    """是否存在至少一个启用的 DB 账户。"""
    ensure_admin_user_table()
    try:
        rows = executeSqlFetch(
            f"SELECT id FROM {TABLE_NAME} WHERE enabled=1 LIMIT 1")
        return bool(rows)
    except Exception as exc:  # noqa: BLE001
        logging.debug("[auth.users] has_any_enabled_user 查询失败: %s", exc)
        return False


def get_user(username: str) -> Optional[Dict[str, Any]]:
    if not username:
        return None
    ensure_admin_user_table()
    try:
        rows = executeSqlFetch(
            f"SELECT {_FIELDS} FROM {TABLE_NAME} WHERE username=%s LIMIT 1",
            (username,))
    except Exception as exc:  # noqa: BLE001
        logging.warning("[auth.users] get_user 查询失败: %s", exc)
        return None
    if not rows:
        return None
    return _row_to_dict(rows[0])


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    if not email:
        return None
    ensure_admin_user_table()
    try:
        rows = executeSqlFetch(
            f"SELECT {_FIELDS} FROM {TABLE_NAME} WHERE email=%s LIMIT 1",
            (email.lower(),))
    except Exception as exc:  # noqa: BLE001
        logging.warning("[auth.users] get_user_by_email 失败: %s", exc)
        return None
    if not rows:
        return None
    return _row_to_dict(rows[0])


def get_user_by_nickname(nickname: str) -> Optional[Dict[str, Any]]:
    if not nickname:
        return None
    ensure_admin_user_table()
    try:
        rows = executeSqlFetch(
            f"SELECT {_FIELDS} FROM {TABLE_NAME} WHERE nickname=%s LIMIT 1",
            (nickname,))
    except Exception as exc:  # noqa: BLE001
        logging.warning("[auth.users] get_user_by_nickname 失败: %s", exc)
        return None
    if not rows:
        return None
    return _row_to_dict(rows[0])


def find_user_by_identifier(identifier: str) -> Optional[Dict[str, Any]]:
    """支持以 username / email / nickname 中任一定位用户。"""
    if not identifier:
        return None
    ident = identifier.strip()
    if "@" in ident:
        u = get_user_by_email(ident)
        if u:
            return u
    u = get_user(ident)
    if u:
        return u
    return get_user_by_nickname(ident)


def list_users() -> List[Dict[str, Any]]:
    ensure_admin_user_table()
    try:
        rows = executeSqlFetch(
            f"SELECT {_FIELDS} FROM {TABLE_NAME} ORDER BY id ASC")
    except Exception as exc:  # noqa: BLE001
        logging.warning("[auth.users] list_users 查询失败: %s", exc)
        return []
    return [_row_to_dict(r) for r in (rows or [])]


# ───────────────── 写入 ─────────────────


def create_user(username: str, password: str, role: str = "operator",
                enabled: bool = True,
                email: Optional[str] = None,
                nickname: Optional[str] = None) -> Dict[str, Any]:
    username = (username or "").strip()
    if not username or len(username) > 64:
        raise ValueError("用户名长度需在 1–64")
    if role not in VALID_ROLES:
        raise ValueError(f"role 必须是 {VALID_ROLES} 之一")
    if get_user(username):
        raise ValueError(f"用户名已存在：{username}")
    email_norm = email.strip().lower() if email else None
    nickname_norm = nickname.strip() if nickname else None
    if email_norm and get_user_by_email(email_norm):
        raise ValueError(f"邮箱已被注册：{email_norm}")
    if nickname_norm and get_user_by_nickname(nickname_norm):
        raise ValueError(f"昵称已被使用：{nickname_norm}")
    pw_hash = _hash_password(password)
    ensure_admin_user_table()
    executeSql(
        f"INSERT INTO {TABLE_NAME} "
        f"(username, password_bcrypt, role, enabled, email, nickname) "
        f"VALUES (%s, %s, %s, %s, %s, %s)",
        (username, pw_hash, role, 1 if enabled else 0,
         email_norm, nickname_norm))
    user = get_user(username)
    if not user:
        raise RuntimeError("创建后回查失败")
    return user


def register_user(email: str, password: str, nickname: str,
                  role: str = "viewer") -> Dict[str, Any]:
    """通过邮箱自助注册的便捷入口。

    - 用户名（username）默认取 email 本地部分；冲突时追加数字后缀。
    - 角色默认 ``viewer``；admin 通过用户管理面板手动提权。
    - 调用方需先校验邮箱验证码。
    """
    email_norm = (email or "").strip().lower()
    nickname_norm = (nickname or "").strip()
    if not email_norm or "@" not in email_norm or len(email_norm) > 120:
        raise ValueError("邮箱格式不正确")
    if not nickname_norm or len(nickname_norm) > 64:
        raise ValueError("昵称长度需在 1–64")
    if role not in VALID_ROLES:
        raise ValueError(f"role 必须是 {VALID_ROLES} 之一")
    if get_user_by_email(email_norm):
        raise ValueError("邮箱已被注册")
    if get_user_by_nickname(nickname_norm):
        raise ValueError("昵称已被使用")

    base = email_norm.split("@", 1)[0][:60] or "user"
    # 仅保留可见 ASCII 字符，避免奇怪用户名
    base = "".join(ch for ch in base if ch.isalnum() or ch in "._-") or "user"
    candidate = base
    suffix = 1
    while get_user(candidate):
        suffix += 1
        candidate = f"{base}{suffix}"
        if suffix > 9999:
            raise RuntimeError("生成 username 重试次数过多")
    return create_user(
        username=candidate, password=password, role=role,
        enabled=True, email=email_norm, nickname=nickname_norm,
    )


def update_user(user_id: int, *, role: Optional[str] = None,
                enabled: Optional[bool] = None,
                password: Optional[str] = None) -> Dict[str, Any]:
    ensure_admin_user_table()
    rows = executeSqlFetch(
        f"SELECT {_FIELDS} FROM {TABLE_NAME} WHERE id=%s LIMIT 1",
        (user_id,))
    if not rows:
        raise ValueError(f"用户不存在 id={user_id}")
    sets, params = [], []
    if role is not None:
        if role not in VALID_ROLES:
            raise ValueError(f"role 必须是 {VALID_ROLES} 之一")
        sets.append("role=%s")
        params.append(role)
    if enabled is not None:
        sets.append("enabled=%s")
        params.append(1 if enabled else 0)
    if password:
        sets.append("password_bcrypt=%s")
        params.append(_hash_password(password))
    if not sets:
        return _row_to_dict(rows[0])
    params.append(user_id)
    executeSql(
        f"UPDATE {TABLE_NAME} SET {', '.join(sets)} WHERE id=%s",
        tuple(params))
    return get_user(rows[0][1])  # type: ignore[arg-type]


def delete_user(user_id: int) -> None:
    ensure_admin_user_table()
    executeSql(f"DELETE FROM {TABLE_NAME} WHERE id=%s", (user_id,))


def touch_login(user_id: int) -> None:
    """更新 last_login_at；失败仅 warning。"""
    ensure_admin_user_table()
    try:
        executeSql(
            f"UPDATE {TABLE_NAME} SET last_login_at=NOW() WHERE id=%s",
            (user_id,))
    except Exception as exc:  # noqa: BLE001
        logging.debug("[auth.users] touch_login 失败: %s", exc)


# ───────────────── 登录核心 ─────────────────


def authenticate(username: str, plain_password: str) -> Optional[Dict[str, Any]]:
    """优先 DB → 回退 env 单账户。返回成功登录的用户 dict（含 role），失败返回 None。

    ``username`` 参数支持 username / email / nickname 三种身份标识。
    """
    username = (username or "").strip()
    if not username or not plain_password:
        return None
    # 1) DB（按 username/email/nickname 任一匹配）
    user = find_user_by_identifier(username)
    if user is not None:
        # 账号在 DB 中存在（启用或禁用）一律走 DB 分支；
        # 禁用账号直接拒绝，不回退 env，避免管理员禁用某账号
        # 后该名账号仍可通过同名 env 单账户继续登录。
        if not user.get("enabled"):
            return None
        try:
            rows = executeSqlFetch(
                f"SELECT password_bcrypt FROM {TABLE_NAME} "
                f"WHERE id=%s LIMIT 1", (user["id"],))
        except Exception as exc:  # noqa: BLE001
            logging.warning("[auth.users] authenticate 查哈希失败: %s", exc)
            rows = None
        if rows and verify_password(plain_password, rows[0][0]):
            touch_login(user["id"])
            return {
                "username": user["username"],
                "role": user["role"] or "operator",
                "email": user.get("email"),
                "nickname": user.get("nickname"),
                "source": "db",
            }
        # DB 命中但密码不对 → 不再回退 env，避免猜测攻击。
        return None
    # 2) env 单账户回退（仅在 DB 中不存在同名账号时）
    env_user = configured_admin_user()
    env_hash = configured_admin_pass_bcrypt()
    if env_user and env_hash and username == env_user and verify_password(
            plain_password, env_hash):
        return {"username": env_user, "role": "admin", "source": "env"}
    return None


__all__ = [
    "VALID_ROLES", "TABLE_NAME",
    "ensure_admin_user_table", "has_any_enabled_user",
    "get_user", "get_user_by_email", "get_user_by_nickname",
    "find_user_by_identifier", "list_users",
    "create_user", "register_user", "update_user", "delete_user",
    "touch_login", "authenticate",
]
