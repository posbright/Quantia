#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
查询缓存模块
为 Web API 提供内存缓存，减少数据库重复查询。

缓存策略:
  - 使用 LRU（最近最少使用）淘汰策略
  - 每条缓存有 TTL（过期时间），过期后自动失效
  - COUNT 查询和 DATA 查询分别缓存
  - 缓存 key 由 SQL + 参数组成，确保唯一性
  - 线程安全
"""

import time
import hashlib
import threading
import logging
from collections import OrderedDict

__author__ = 'Quantia'
__date__ = '2026/02/14'

logger = logging.getLogger(__name__)


class QueryCache:
    """
    线程安全的 LRU 缓存，支持 TTL 过期。

    参数:
        max_size: 最大缓存条目数，默认 512
        default_ttl: 默认过期时间（秒），默认 300（5分钟）
    """

    def __init__(self, max_size=512, default_ttl=300):
        self._cache = OrderedDict()   # key -> (value, expire_time)
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._lock = threading.Lock()
        self._hit_count = 0
        self._miss_count = 0

    def _make_key(self, sql, params=None):
        """根据 SQL 和参数生成缓存 key"""
        raw = sql
        if params:
            raw += "|" + "|".join(str(p) for p in params)
        return hashlib.md5(raw.encode('utf-8')).hexdigest()

    def get(self, sql, params=None):
        """
        获取缓存。
        返回 (True, value) 如果命中，(False, None) 如果未命中或已过期。
        """
        key = self._make_key(sql, params)
        with self._lock:
            if key in self._cache:
                value, expire_time = self._cache[key]
                if time.time() < expire_time:
                    # 命中，移到末尾（最近使用）
                    self._cache.move_to_end(key)
                    self._hit_count += 1
                    return True, value
                else:
                    # 已过期，删除
                    del self._cache[key]
            self._miss_count += 1
            return False, None

    def put(self, sql, params, value, ttl=None):
        """
        设置缓存。
        ttl: 过期时间（秒），None 使用默认值。
        """
        if ttl is None:
            ttl = self._default_ttl
        key = self._make_key(sql, params)
        expire_time = time.time() + ttl

        with self._lock:
            if key in self._cache:
                # 更新已有条目
                self._cache.move_to_end(key)
                self._cache[key] = (value, expire_time)
            else:
                # 新条目
                self._cache[key] = (value, expire_time)
                # 超出容量则淘汰最早的
                while len(self._cache) > self._max_size:
                    self._cache.popitem(last=False)

    def invalidate(self, sql=None, params=None):
        """
        使指定缓存失效。如果不传参数则清空所有缓存。
        """
        with self._lock:
            if sql is None:
                self._cache.clear()
            else:
                key = self._make_key(sql, params)
                self._cache.pop(key, None)

    def invalidate_by_prefix(self, table_name):
        """
        使包含指定表名的所有缓存失效。
        用于数据更新后清除相关缓存。
        """
        with self._lock:
            # 无法通过 hash key 反推表名，所以记录原始 key 不实际
            # 简单方案：清空全部缓存
            self._cache.clear()

    def cleanup_expired(self):
        """清除所有过期条目"""
        now = time.time()
        with self._lock:
            expired_keys = [k for k, (_, exp) in self._cache.items() if now >= exp]
            for k in expired_keys:
                del self._cache[k]
        return len(expired_keys)

    @property
    def stats(self):
        """返回缓存统计信息"""
        with self._lock:
            total = self._hit_count + self._miss_count
            hit_rate = (self._hit_count / total * 100) if total > 0 else 0
            return {
                "size": len(self._cache),
                "max_size": self._max_size,
                "hit_count": self._hit_count,
                "miss_count": self._miss_count,
                "hit_rate": f"{hit_rate:.1f}%",
                "ttl": self._default_ttl
            }

    def __len__(self):
        with self._lock:
            return len(self._cache)


# ============================================================
# 全局缓存实例
# ============================================================

# 数据查询缓存（StockData 页面）
import quantia.lib.envconfig as _cfg
stock_data_cache = QueryCache(
    max_size=_cfg.get_int('QUANTIA_CACHE_MAX_SIZE', 512),
    default_ttl=_cfg.get_int('QUANTIA_CACHE_TTL', 300))

# 筛选结果缓存（StrategyConfig 筛选）
filter_result_cache = QueryCache(
    max_size=_cfg.get_int('QUANTIA_FILTER_CACHE_MAX_SIZE', 128),
    default_ttl=_cfg.get_int('QUANTIA_FILTER_CACHE_TTL', 600))
