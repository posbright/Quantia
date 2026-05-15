# -*- coding: utf-8 -*-
"""钉钉回调签名校验。

钉钉机器人回调签名规则（HMAC-SHA256）与 outbound webhook 一致：
- string_to_sign = ``f"{timestamp}\\n{secret}"``
- digest = HMAC-SHA256(secret, string_to_sign)
- sign = base64(digest)，URL-encode

回调端校验：
- 校验 ``timestamp`` 与服务器时间差 ≤ ``MAX_SKEW_SECONDS`` (默认 300s)。
- 重新计算 sign 并与请求中的 sign 做常量时间比较。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time
import urllib.parse
from typing import Optional

MAX_SKEW_SECONDS = 300  # 钉钉文档建议 ≤ 1 小时；这里收紧到 5 分钟


def compute_sign(secret: str, timestamp: str) -> str:
    """计算钉钉回调签名（base64-urlencoded）。"""
    string_to_sign = f"{timestamp}\n{secret}".encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), string_to_sign,
                      digestmod=hashlib.sha256).digest()
    return urllib.parse.quote_plus(base64.b64encode(digest))


def verify_dingtalk_signature(secret: str, timestamp: str, sign: str,
                              now_ms: Optional[int] = None) -> Optional[str]:
    """校验钉钉回调签名。

    Returns ``None`` 表示通过；否则返回错误说明字符串。
    """
    if not secret:
        return "未配置 secret，无法校验签名"
    if not timestamp or not sign:
        return "缺少 timestamp 或 sign"
    try:
        ts_ms = int(timestamp)
    except (TypeError, ValueError):
        return "timestamp 非法"
    cur_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    if abs(cur_ms - ts_ms) > MAX_SKEW_SECONDS * 1000:
        return f"timestamp 超出允许时间窗 ({MAX_SKEW_SECONDS}s)"
    expected = compute_sign(secret, timestamp)
    # 钉钉回调中的 sign 通常是 URL 解码后的 base64；为兼容两种形态都比较一次
    candidates = {sign, urllib.parse.quote_plus(sign)}
    for candidate in candidates:
        if hmac.compare_digest(candidate, expected):
            return None
    # 也尝试 URL-decode 后的形态
    try:
        decoded = urllib.parse.unquote_plus(sign)
        if hmac.compare_digest(urllib.parse.quote_plus(decoded), expected):
            return None
    except Exception:
        pass
    return "签名不匹配"
