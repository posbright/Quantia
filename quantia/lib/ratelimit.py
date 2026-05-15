# -*- coding: utf-8 -*-
"""Phase 8: 进程内令牌桶限速器（轻量、零依赖）。

设计目标：
- 用于钉钉回调（按 ``operator_id`` 限速）与 ``execute_pending`` 实盘触发
  （按客户端 IP 限速）。
- **零环境变量时完全 no-op**，不影响现网默认行为，也不影响既有测试基线。
- 线程安全（``threading.Lock``）；进程内独立桶；多进程部署时各进程独立计数。
- 不依赖 redis / 数据库；目的只是吸收意外突发请求与保护下游 broker。

接口：
- :class:`TokenBucket`：单 key 桶；``allow()`` 返回是否放行。
- :func:`check`：模块级便捷函数；按 ``(scope, key)`` 复用桶；按调用时
  指定 ``capacity`` 与 ``refill_per_sec`` 决定速率。

用法示例：

>>> from quantia.lib import ratelimit
>>> ok = ratelimit.check("dingtalk_callback", "user-123",
...                       capacity=12, refill_per_sec=12 / 60.0)
>>> if not ok:
...     return 429

读取环境变量的便捷封装：

- :func:`dingtalk_callback_rpm` 读取 ``QUANTIA_DINGTALK_CALLBACK_RPM``
  （默认 0=禁用限速）。
- :func:`live_execute_rps` 读取 ``QUANTIA_LIVE_EXECUTE_RPS``（默认 0）。
"""
from __future__ import annotations

import os
import threading
import time
from typing import Dict, Tuple


__all__ = [
    "TokenBucket", "check", "reset",
    "dingtalk_callback_rpm", "live_execute_rps",
]


class TokenBucket:
    """经典令牌桶。

    :param capacity: 桶容量（同时允许的最大突发请求数）。
    :param refill_per_sec: 每秒补充的令牌数。
    :param now_func: 单调时钟函数；测试可注入 mock。
    """

    __slots__ = ("capacity", "refill_per_sec", "_tokens", "_last_ts",
                 "_lock", "_now")

    def __init__(self, capacity: float, refill_per_sec: float,
                 now_func=time.monotonic):
        if capacity <= 0:
            raise ValueError("capacity 必须 > 0")
        if refill_per_sec <= 0:
            raise ValueError("refill_per_sec 必须 > 0")
        self.capacity = float(capacity)
        self.refill_per_sec = float(refill_per_sec)
        self._tokens = float(capacity)
        self._now = now_func
        self._last_ts = now_func()
        self._lock = threading.Lock()

    def allow(self, cost: float = 1.0) -> bool:
        """尝试消费 ``cost`` 个令牌；放行返回 True，限速返回 False。"""
        with self._lock:
            now = self._now()
            elapsed = max(0.0, now - self._last_ts)
            self._tokens = min(self.capacity,
                               self._tokens + elapsed * self.refill_per_sec)
            self._last_ts = now
            if self._tokens >= cost:
                self._tokens -= cost
                return True
            return False


_BUCKETS: Dict[Tuple[str, str], TokenBucket] = {}
_BUCKETS_LOCK = threading.Lock()


def check(scope: str, key: str, *,
          capacity: float, refill_per_sec: float,
          now_func=time.monotonic) -> bool:
    """按 ``(scope, key)`` 复用桶；返回是否放行。

    若 ``capacity<=0`` 或 ``refill_per_sec<=0`` 则视为 **禁用限速**，
    始终返回 True。这使得调用方可以用 ``capacity=env_int(...)`` 直接禁用。
    """
    if capacity <= 0 or refill_per_sec <= 0:
        return True
    composite = (scope, str(key))
    bucket = _BUCKETS.get(composite)
    if bucket is None:
        with _BUCKETS_LOCK:
            bucket = _BUCKETS.get(composite)
            if bucket is None:
                bucket = TokenBucket(capacity, refill_per_sec, now_func)
                _BUCKETS[composite] = bucket
    return bucket.allow()


def reset(scope: str | None = None) -> None:
    """清空所有桶（仅测试使用）。指定 scope 时只清该 scope。"""
    with _BUCKETS_LOCK:
        if scope is None:
            _BUCKETS.clear()
            return
        keys = [k for k in _BUCKETS if k[0] == scope]
        for k in keys:
            _BUCKETS.pop(k, None)


# ─────────────── env 便捷封装 ───────────────


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except Exception:
        return default


def dingtalk_callback_rpm() -> int:
    """读取 ``QUANTIA_DINGTALK_CALLBACK_RPM``，默认 0（禁用）。

    解释：每个 ``operator_id`` 每分钟最多允许 N 次回调；超过返回 429。
    """
    return _env_int("QUANTIA_DINGTALK_CALLBACK_RPM", 0)


def live_execute_rps() -> int:
    """读取 ``QUANTIA_LIVE_EXECUTE_RPS``，默认 0（禁用）。

    解释：每个客户端 IP 每秒最多允许 N 次 ``/api/live/execute_pending``。
    """
    return _env_int("QUANTIA_LIVE_EXECUTE_RPS", 0)
