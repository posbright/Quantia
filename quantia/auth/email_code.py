# -*- coding: utf-8 -*-
"""邮箱验证码：注册 / 找回密码等场景共用。

设计要点
========

1. **DB 持久化**：6 位数字验证码 + 5 分钟过期，保存到
   ``cn_stock_user_email_code``，过期/已用记录通过 cron 或下次发码时自动清理。
2. **节流**：同一邮箱 60 秒内最多发 1 条；24 小时内最多 10 条。
3. **校验**：消费一次即标记 ``consumed=1``；同时清理同邮箱+purpose 下所有
   已过期或已消费的旧码。
4. **SMTP 可选**：

   - 配置 ``QUANTIA_SMTP_HOST/PORT/USER/PASS/FROM`` 后真实发邮件；
   - 未配置时不发邮件，开发模式（``QUANTIA_REGISTER_DEV_MODE=true``）下
     验证码会在响应里回显 + 写日志，方便本地联调；非 dev 模式直接报错。
"""
from __future__ import annotations

import logging
import os
import random
import smtplib
import ssl
from datetime import datetime, timedelta
from email.message import EmailMessage
from typing import Any, Dict, Optional, Tuple

from quantia.lib.database import executeSql, executeSqlFetch


TABLE_NAME = "cn_stock_user_email_code"
CODE_TTL_MINUTES = 5
RESEND_COOLDOWN_SECONDS = 60
DAILY_LIMIT_PER_EMAIL = 10

REGISTER_ENABLED_ENV = "QUANTIA_REGISTER_ENABLED"
REGISTER_DEV_MODE_ENV = "QUANTIA_REGISTER_DEV_MODE"

SMTP_HOST_ENV = "QUANTIA_SMTP_HOST"
SMTP_PORT_ENV = "QUANTIA_SMTP_PORT"
SMTP_USER_ENV = "QUANTIA_SMTP_USER"
SMTP_PASS_ENV = "QUANTIA_SMTP_PASS"
SMTP_FROM_ENV = "QUANTIA_SMTP_FROM"
SMTP_USE_SSL_ENV = "QUANTIA_SMTP_USE_SSL"  # 默认 true，对 465 端口

_TABLE_READY = False


def is_register_enabled() -> bool:
    """``QUANTIA_REGISTER_ENABLED`` 控制是否开放自助注册。默认开启。"""
    raw = (os.getenv(REGISTER_ENABLED_ENV) or "true").strip().lower()
    return raw in ("1", "true", "yes", "on")


def is_dev_mode() -> bool:
    raw = (os.getenv(REGISTER_DEV_MODE_ENV) or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def ensure_email_code_table(force: bool = False) -> None:
    global _TABLE_READY
    if _TABLE_READY and not force:
        return
    sql = f"""
        CREATE TABLE IF NOT EXISTS `{TABLE_NAME}` (
          `id` INT AUTO_INCREMENT PRIMARY KEY,
          `email` VARCHAR(120) NOT NULL,
          `code` VARCHAR(8) NOT NULL,
          `purpose` VARCHAR(32) NOT NULL DEFAULT 'register',
          `expires_at` DATETIME NOT NULL,
          `consumed` TINYINT(1) NOT NULL DEFAULT 0,
          `send_ip` VARCHAR(64) NULL,
          `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
          INDEX `idx_email_purpose` (`email`, `purpose`),
          INDEX `idx_expires` (`expires_at`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """.strip()
    try:
        executeSql(sql)
        _TABLE_READY = True
    except Exception as exc:  # noqa: BLE001
        logging.warning("[auth.email_code] 创建 %s 失败: %s", TABLE_NAME, exc)


def _generate_code() -> str:
    return f"{random.SystemRandom().randint(0, 999999):06d}"


def _smtp_configured() -> bool:
    return bool(os.getenv(SMTP_HOST_ENV) and os.getenv(SMTP_FROM_ENV))


def _send_email(to_addr: str, code: str, purpose: str = "register") -> None:
    host = os.getenv(SMTP_HOST_ENV)
    port = int(os.getenv(SMTP_PORT_ENV) or "465")
    user = os.getenv(SMTP_USER_ENV) or ""
    password = os.getenv(SMTP_PASS_ENV) or ""
    sender = os.getenv(SMTP_FROM_ENV) or user
    use_ssl = (os.getenv(SMTP_USE_SSL_ENV) or "true").strip().lower() in (
        "1", "true", "yes", "on")

    msg = EmailMessage()
    subject_map = {
        "register": "Quantia 注册验证码",
        "reset": "Quantia 重置密码验证码",
    }
    msg["Subject"] = subject_map.get(purpose, "Quantia 验证码")
    msg["From"] = sender
    msg["To"] = to_addr
    msg.set_content(
        f"您的验证码是：{code}\n\n"
        f"该验证码 {CODE_TTL_MINUTES} 分钟内有效，请勿告知他人。\n"
        "如果不是您本人操作，请忽略本邮件。\n"
    )

    if use_ssl:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=15) as smtp:
            if user:
                smtp.login(user, password)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=15) as smtp:
            smtp.ehlo()
            try:
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
            except smtplib.SMTPException:
                # 服务端不支持 STARTTLS 时继续明文，下方仍要求 LOGIN
                pass
            if user:
                smtp.login(user, password)
            smtp.send_message(msg)


# ───────────────── 节流 ─────────────────


def _recent_send_count(email: str, purpose: str, since: datetime) -> int:
    try:
        rows = executeSqlFetch(
            f"SELECT COUNT(*) FROM {TABLE_NAME} "
            f"WHERE email=%s AND purpose=%s AND created_at >= %s",
            (email, purpose, since))
        if rows and rows[0]:
            return int(rows[0][0])
    except Exception as exc:  # noqa: BLE001
        logging.debug("[auth.email_code] _recent_send_count 失败: %s", exc)
    return 0


def _last_send_at(email: str, purpose: str) -> Optional[datetime]:
    try:
        rows = executeSqlFetch(
            f"SELECT MAX(created_at) FROM {TABLE_NAME} "
            f"WHERE email=%s AND purpose=%s",
            (email, purpose))
        if rows and rows[0] and rows[0][0]:
            return rows[0][0]
    except Exception as exc:  # noqa: BLE001
        logging.debug("[auth.email_code] _last_send_at 失败: %s", exc)
    return None


# ───────────────── 公开 API ─────────────────


def request_code(email: str, purpose: str = "register",
                 send_ip: Optional[str] = None) -> Dict[str, Any]:
    """生成并尝试投递一条验证码。

    返回 ``{"ok": True, "expires_in": 300}``；dev 模式下额外带 ``dev_code``。
    抛出 ``ValueError`` 表示业务错误（节流 / SMTP 未配置等）。
    """
    email_norm = (email or "").strip().lower()
    if not email_norm or "@" not in email_norm or len(email_norm) > 120:
        raise ValueError("邮箱格式不正确")

    ensure_email_code_table()

    last = _last_send_at(email_norm, purpose)
    if last:
        elapsed = (datetime.now() - last).total_seconds()
        if elapsed < RESEND_COOLDOWN_SECONDS:
            wait = int(RESEND_COOLDOWN_SECONDS - elapsed)
            raise ValueError(f"发送过于频繁，请 {wait} 秒后再试")

    daily = _recent_send_count(
        email_norm, purpose, datetime.now() - timedelta(days=1))
    if daily >= DAILY_LIMIT_PER_EMAIL:
        raise ValueError("今日发送次数已达上限，请明天再试")

    code = _generate_code()
    expires_at = datetime.now() + timedelta(minutes=CODE_TTL_MINUTES)

    smtp_ok = _smtp_configured()
    dev = is_dev_mode()
    if not smtp_ok and not dev:
        raise ValueError(
            "服务端未配置邮件发送 (QUANTIA_SMTP_HOST/PORT/USER/PASS/FROM)，"
            "无法发送验证码")

    # 先入库再发邮件，发邮件失败时回滚此条记录，避免占用节流配额。
    try:
        executeSql(
            f"INSERT INTO {TABLE_NAME} "
            f"(email, code, purpose, expires_at, send_ip) "
            f"VALUES (%s, %s, %s, %s, %s)",
            (email_norm, code, purpose, expires_at, send_ip))
    except Exception as exc:  # noqa: BLE001
        logging.exception("[auth.email_code] 写入验证码失败")
        raise ValueError(f"验证码写入失败: {exc}") from exc

    if smtp_ok:
        try:
            _send_email(email_norm, code, purpose)
        except Exception as exc:  # noqa: BLE001
            logging.exception("[auth.email_code] 发送邮件失败 %s", email_norm)
            # 发送失败 → 删除刚写入的码（保留节流配额）
            try:
                executeSql(
                    f"DELETE FROM {TABLE_NAME} "
                    f"WHERE email=%s AND code=%s AND purpose=%s",
                    (email_norm, code, purpose))
            except Exception:  # noqa: BLE001
                pass
            raise ValueError(f"邮件发送失败：{exc}") from exc

    result: Dict[str, Any] = {
        "ok": True,
        "expires_in": CODE_TTL_MINUTES * 60,
        "smtp_sent": smtp_ok,
    }
    if dev:
        # 开发模式：日志/响应回显，方便本地无 SMTP 的联调
        logging.warning(
            "[auth.email_code][DEV] %s purpose=%s code=%s 有效 %d 分钟",
            email_norm, purpose, code, CODE_TTL_MINUTES)
        result["dev_code"] = code
    return result


def verify_code(email: str, code: str,
                purpose: str = "register",
                consume: bool = True) -> Tuple[bool, Optional[str]]:
    """校验验证码。``consume=True`` 时一次性消费。

    Returns:
        (True, None) 校验通过 / (False, error_message)
    """
    email_norm = (email or "").strip().lower()
    code_norm = (code or "").strip()
    if not email_norm or not code_norm:
        return False, "邮箱或验证码为空"
    ensure_email_code_table()
    try:
        rows = executeSqlFetch(
            f"SELECT id, expires_at, consumed FROM {TABLE_NAME} "
            f"WHERE email=%s AND code=%s AND purpose=%s "
            f"ORDER BY id DESC LIMIT 1",
            (email_norm, code_norm, purpose))
    except Exception as exc:  # noqa: BLE001
        logging.warning("[auth.email_code] verify_code 查询失败: %s", exc)
        return False, "服务异常，请稍后再试"
    if not rows:
        return False, "验证码错误"
    cid, expires_at, consumed = rows[0]
    if int(consumed or 0):
        return False, "验证码已被使用"
    if expires_at and expires_at < datetime.now():
        return False, "验证码已过期"
    if consume:
        try:
            executeSql(
                f"UPDATE {TABLE_NAME} SET consumed=1 WHERE id=%s",
                (cid,))
        except Exception as exc:  # noqa: BLE001
            logging.warning("[auth.email_code] 标记消费失败: %s", exc)
    return True, None


def cleanup_expired() -> int:
    """删除过期 + 已消费 24 小时以上的旧码。返回 0/1（仅指示是否成功执行）。"""
    ensure_email_code_table()
    try:
        before = datetime.now() - timedelta(days=1)
        executeSql(
            f"DELETE FROM {TABLE_NAME} "
            f"WHERE expires_at < %s OR (consumed=1 AND created_at < %s)",
            (datetime.now(), before))
        return 1
    except Exception as exc:  # noqa: BLE001
        logging.debug("[auth.email_code] cleanup_expired 失败: %s", exc)
        return 0


__all__ = [
    "TABLE_NAME", "CODE_TTL_MINUTES",
    "is_register_enabled", "is_dev_mode",
    "ensure_email_code_table", "request_code", "verify_code", "cleanup_expired",
]
