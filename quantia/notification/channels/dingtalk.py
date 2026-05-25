#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import base64
import hashlib
import hmac
import time
from typing import Any, Dict, Optional
from urllib.parse import quote_plus, urlparse

import requests

from .base import NotificationChannel, NotificationSendResult


class DingTalkChannel(NotificationChannel):
    """DingTalk group robot webhook channel."""

    channel = "dingtalk"

    def __init__(self, webhook: str, secret: str = "", timeout: int = 8):
        self.webhook = (webhook or "").strip()
        self.secret = (secret or "").strip()
        self.timeout = timeout

    @staticmethod
    def build_signed_url(webhook: str, secret: str, timestamp_ms: Optional[int] = None) -> str:
        if not secret:
            return webhook
        timestamp = str(timestamp_ms if timestamp_ms is not None else int(time.time() * 1000))
        string_to_sign = f"{timestamp}\n{secret}".encode("utf-8")
        digest = hmac.new(secret.encode("utf-8"), string_to_sign, digestmod=hashlib.sha256).digest()
        sign = quote_plus(base64.b64encode(digest))
        separator = "&" if "?" in webhook else "?"
        return f"{webhook}{separator}timestamp={timestamp}&sign={sign}"

    @staticmethod
    def build_markdown_payload(title: str, markdown: str, at_mobiles=None, is_at_all: bool = False) -> Dict[str, Any]:
        at_mobiles = at_mobiles or []
        return {
            "msgtype": "markdown",
            "markdown": {"title": title[:64] or "模拟交易通知", "text": markdown},
            "at": {"atMobiles": at_mobiles, "isAtAll": bool(is_at_all)},
        }

    def send(self, payload: Dict[str, Any]) -> NotificationSendResult:
        if not self.webhook:
            return NotificationSendResult(ok=False, error="DingTalk webhook is empty")
        # 校验 webhook URL 安全性（防止 SSRF）
        parsed = urlparse(self.webhook)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname:
            return NotificationSendResult(ok=False, error="Invalid webhook URL scheme or host")
        try:
            url = self.build_signed_url(self.webhook, self.secret)
            response = requests.post(url, json=payload, timeout=self.timeout)
            response_json = None
            try:
                response_json = response.json()
            except Exception:
                response_json = {"text": response.text[:500]}
            ok = response.status_code == 200 and int(response_json.get("errcode", 0)) == 0
            error = "" if ok else str(response_json.get("errmsg") or response.text[:500])
            return NotificationSendResult(
                ok=ok,
                status_code=response.status_code,
                response=response_json,
                error=error,
            )
        except Exception as exc:
            return NotificationSendResult(ok=False, error=str(exc))