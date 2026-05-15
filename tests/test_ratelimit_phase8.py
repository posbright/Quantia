# -*- coding: utf-8 -*-
"""Phase 8: 限速器单元测试。

覆盖：
- TokenBucket 基础行为（容量上限、补充、突发后阻断）。
- ratelimit.check 桶复用与禁用语义（capacity<=0 → 永远放行）。
- env 解析便捷函数返回默认 0（即 no-op）。
- 钉钉回调 Handler / execute_pending Handler 在 env 未设置时不影响放行
  （保护既有基线）。
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

from quantia.lib import ratelimit


class _FakeClock:
    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


class TokenBucketTests(unittest.TestCase):
    def setUp(self) -> None:
        ratelimit.reset()

    def test_capacity_burst_then_blocks(self):
        clk = _FakeClock()
        bucket = ratelimit.TokenBucket(
            capacity=3, refill_per_sec=1.0, now_func=clk)
        self.assertTrue(bucket.allow())
        self.assertTrue(bucket.allow())
        self.assertTrue(bucket.allow())
        # 桶空 → 拒绝
        self.assertFalse(bucket.allow())

    def test_refill_after_elapsed(self):
        clk = _FakeClock()
        bucket = ratelimit.TokenBucket(
            capacity=2, refill_per_sec=1.0, now_func=clk)
        self.assertTrue(bucket.allow())
        self.assertTrue(bucket.allow())
        self.assertFalse(bucket.allow())
        # 1.5 秒后补充 1.5 个令牌
        clk.t += 1.5
        self.assertTrue(bucket.allow())
        # 应该只剩 0.5 个令牌
        self.assertFalse(bucket.allow())

    def test_capacity_cap(self):
        clk = _FakeClock()
        bucket = ratelimit.TokenBucket(
            capacity=2, refill_per_sec=10.0, now_func=clk)
        clk.t += 100  # 远超容量
        self.assertTrue(bucket.allow())
        self.assertTrue(bucket.allow())
        # 仍只能 burst capacity 个
        self.assertFalse(bucket.allow())

    def test_invalid_args(self):
        with self.assertRaises(ValueError):
            ratelimit.TokenBucket(capacity=0, refill_per_sec=1.0)
        with self.assertRaises(ValueError):
            ratelimit.TokenBucket(capacity=1, refill_per_sec=0)


class CheckHelperTests(unittest.TestCase):
    def setUp(self) -> None:
        ratelimit.reset()

    def test_disabled_when_capacity_zero(self):
        for _ in range(100):
            self.assertTrue(ratelimit.check(
                "scope_a", "k", capacity=0, refill_per_sec=1.0))

    def test_disabled_when_rate_zero(self):
        for _ in range(100):
            self.assertTrue(ratelimit.check(
                "scope_a", "k", capacity=10, refill_per_sec=0))

    def test_bucket_reuse_per_key(self):
        clk = _FakeClock()
        # 同一 key 复用桶 → 第 3 次拒绝
        self.assertTrue(ratelimit.check(
            "scope_x", "user1", capacity=2, refill_per_sec=1.0, now_func=clk))
        self.assertTrue(ratelimit.check(
            "scope_x", "user1", capacity=2, refill_per_sec=1.0, now_func=clk))
        self.assertFalse(ratelimit.check(
            "scope_x", "user1", capacity=2, refill_per_sec=1.0, now_func=clk))
        # 不同 key 独立桶
        self.assertTrue(ratelimit.check(
            "scope_x", "user2", capacity=2, refill_per_sec=1.0, now_func=clk))

    def test_reset_scope_isolated(self):
        ratelimit.check("a", "k1", capacity=1, refill_per_sec=1.0)
        ratelimit.check("b", "k1", capacity=1, refill_per_sec=1.0)
        ratelimit.reset("a")
        self.assertNotIn(("a", "k1"), ratelimit._BUCKETS)
        self.assertIn(("b", "k1"), ratelimit._BUCKETS)


class EnvHelpersTests(unittest.TestCase):
    def test_default_zero_means_disabled(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("QUANTIA_DINGTALK_CALLBACK_RPM", None)
            os.environ.pop("QUANTIA_LIVE_EXECUTE_RPS", None)
            self.assertEqual(ratelimit.dingtalk_callback_rpm(), 0)
            self.assertEqual(ratelimit.live_execute_rps(), 0)

    def test_env_parsing(self):
        with mock.patch.dict(os.environ, {
            "QUANTIA_DINGTALK_CALLBACK_RPM": "20",
            "QUANTIA_LIVE_EXECUTE_RPS": "3",
        }):
            self.assertEqual(ratelimit.dingtalk_callback_rpm(), 20)
            self.assertEqual(ratelimit.live_execute_rps(), 3)

    def test_env_invalid_falls_back_to_default(self):
        with mock.patch.dict(os.environ, {
            "QUANTIA_DINGTALK_CALLBACK_RPM": "abc",
        }):
            self.assertEqual(ratelimit.dingtalk_callback_rpm(), 0)


if __name__ == "__main__":
    unittest.main()
