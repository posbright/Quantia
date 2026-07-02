#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
代理池管理模块

功能：
1. 从多个免费代理源自动抓取代理IP
2. 验证代理可用性（针对东方财富API测试）
3. 后台定时刷新：定期获取新代理、移除不可用代理
4. 支持手动配置：proxy.txt 中的代理优先级最高
5. 线程安全：所有操作均加锁保护
6. 磁盘缓存：验证过的代理持久化，下次启动秒加载
7. 非阻塞初始化：__init__ 瞬间返回，代理验证在后台完成

使用方式不变：proxys().get_proxies() 返回可用代理或 None
"""

import os.path
import sys
import json
import random
import time
import logging
import threading
import requests
from quantia.lib.singleton_type import singleton_type

# 在项目运行时，临时将项目路径添加到环境变量
cpath_current = os.path.dirname(os.path.dirname(__file__))
cpath = os.path.abspath(os.path.join(cpath_current, os.pardir))
sys.path.append(cpath)
proxy_filename = os.path.join(cpath_current, 'config', 'proxy.txt')
# 磁盘缓存路径：保存已验证代理，下次启动时快速恢复
_PROXY_CACHE_FILE = os.path.join(cpath_current, 'cache', 'proxy_cache.json')

__author__ = 'Quantia'
__date__ = '2026/02/14'

# ── 配置（均可通过 .env / 环境变量覆盖） ──
import quantia.lib.envconfig as _cfg
PROXY_VALIDATE_URL = _cfg.get_str('QUANTIA_PROXY_VALIDATE_URL', 'http://datacenter.eastmoney.com/api/data/get')  # HTTP验证URL
PROXY_VALIDATE_TIMEOUT = _cfg.get_int('QUANTIA_PROXY_VALIDATE_TIMEOUT', 5)       # 验证超时（秒）
PROXY_REFRESH_INTERVAL = _cfg.get_int('QUANTIA_PROXY_REFRESH_INTERVAL', 600)     # 后台刷新间隔（秒）
PROXY_MIN_POOL_SIZE = _cfg.get_int('QUANTIA_PROXY_MIN_POOL_SIZE', 3)             # 代理池最少保有量
PROXY_FETCH_WORKERS = _cfg.get_int('QUANTIA_PROXY_FETCH_WORKERS', 50)            # 并发验证线程数
PROXY_INIT_BATCH_SIZE = _cfg.get_int('QUANTIA_PROXY_INIT_BATCH_SIZE', 200)       # 初始化验证候选数
PROXY_MAX_FAIL_COUNT = _cfg.get_int('QUANTIA_PROXY_MAX_FAIL_COUNT', 3)           # 连续失败次数阈值
PROXY_STALE_SECONDS = _cfg.get_int('QUANTIA_PROXY_STALE_SECONDS', 600)           # 验证新鲜度阈值（秒）
PROXY_CACHE_MAX_AGE = _cfg.get_int('QUANTIA_PROXY_CACHE_MAX_AGE', 86400)         # 磁盘缓存有效期（秒）
PROXY_TARGET_POOL_SIZE = _cfg.get_int('QUANTIA_PROXY_TARGET_POOL_SIZE', 15)      # 代理池目标保有量
PROXY_EMERGENCY_COOLDOWN = _cfg.get_int('QUANTIA_PROXY_EMERGENCY_COOLDOWN', 30)  # 紧急补充冷却时间（秒）
# ── 代理源质量评估 / 轮换（按"活跃度 + 存活率"动态择优，定期更换数据源） ──
PROXY_SOURCE_EXPLORE_RATIO = _cfg.get_float('QUANTIA_PROXY_SOURCE_EXPLORE_RATIO', 0.3)  # 探索比例：每次抓取中用于"重新尝试/更换"数据源的占比
PROXY_SOURCE_DECAY = _cfg.get_float('QUANTIA_PROXY_SOURCE_DECAY', 0.8)                   # 每次刷新对历史统计的衰减系数（越小遗忘越快，越易轮换）
PROXY_SOURCE_MIN_SAMPLES = _cfg.get_int('QUANTIA_PROXY_SOURCE_MIN_SAMPLES', 20)         # 低于该验证样本数的源视为"待探索"，优先重新尝试


class proxys(metaclass=singleton_type):
    """
    代理池管理器（单例）

    生命周期：
    1. 首次 proxys() 时初始化：加载 proxy.txt + 磁盘缓存（瞬间完成）
    2. 后台线程异步验证：缓存代理快速验证 → 抓取新代理 → 补充验证
    3. get_proxies() 随机返回一个可用代理（初始化完成前返回 None → 直连）
    4. report_failure(proxy) 报告代理失败，累积失败次数达阈值后自动移除
    5. 后台线程每 PROXY_REFRESH_INTERVAL 秒自动刷新
    """

    def __init__(self):
        self._lock = threading.RLock()
        # {proxy_url: {"fail_count": int, "last_verified": float}}
        self._pool = {}
        self._manual_proxies = []  # proxy.txt 中的手动配置代理
        self._running = False
        self._refresh_thread = None
        self._initialized = False

        # 代理源质量统计：{source_name: {"candidates", "validated", "passed", "attempts", "last_active"}}
        #   candidates：累计抓到的候选数（活跃度）；validated：累计验证数；passed：累计验证通过数（存活率）
        # 用于"按活跃度 + 存活率动态择优 / 定期更换免费代理数据源"
        self._source_stats = {}
        # 最近一次抓取的 候选代理 -> 来源 映射，用于把验证结果归因到具体数据源
        self._fetch_source_map = {}

        # 同步加载（瞬间完成）：手动代理 + 磁盘缓存
        self._load_manual_proxies()
        cached_count = self._load_disk_cache()

        # 异步初始化：后台线程完成验证和抓取，不阻塞调用方
        self._init_thread = threading.Thread(target=self._async_init, args=(cached_count,), daemon=True)
        self._init_thread.start()
        logging.info("代理池：初始化已启动（后台异步，不阻塞）")

    def _async_init(self, cached_count):
        """后台异步初始化：验证缓存代理 → 不足时抓取新代理 → 启动定时刷新"""
        init_start = time.time()
        try:
            # Phase 1: 快速验证磁盘缓存中的代理（通常 <10s）
            if cached_count > 0:
                self._revalidate_existing(http_only=True)
                usable = self.pool_size()
                logging.info(f"代理池：缓存验证完成，{usable}/{cached_count} 个可用 ({time.time() - init_start:.1f}s)")
                if usable >= PROXY_MIN_POOL_SIZE:
                    self._initialized = True

            # Phase 2: 代理不足时抓取新代理
            if self.pool_size() < PROXY_MIN_POOL_SIZE:
                self._initial_fetch()

            self._initialized = True

            # Phase 3: 后台补充 HTTPS 验证（不阻塞，低优先级）
            self._upgrade_https_in_background()
        except Exception as e:
            logging.warning(f"代理池：异步初始化异常: {e}")
            self._initialized = True  # 即使失败也标记完成，避免永远阻塞
        finally:
            elapsed = time.time() - init_start
            logging.info(f"代理池：初始化完成，可用 {self.pool_size()} 个 ({elapsed:.1f}s)")
            # 持久化到磁盘
            self._save_disk_cache()
            # 启动后台定时刷新
            self._start_background_refresh()

    def _load_manual_proxies(self):
        """从 proxy.txt 加载手动配置的代理"""
        try:
            with open(proxy_filename, "r") as f:
                lines = [line.strip() for line in f.readlines() if line.strip()]
                self._manual_proxies = list(set(lines))
                for proxy in self._manual_proxies:
                    self._pool[proxy] = {"fail_count": 0, "last_verified": time.time(), "manual": True}
                if self._manual_proxies:
                    logging.info(f"代理池：从 proxy.txt 加载了 {len(self._manual_proxies)} 个手动代理")
        except Exception:
            logging.debug("代理池：加载 proxy.txt 异常", exc_info=True)

    def _load_disk_cache(self):
        """
        从磁盘缓存加载上次验证过的代理（瞬间完成）。
        仅加载到 _pool 中（fail_count=0 但 last_verified 保留原始时间），
        后续 _revalidate_existing 会重新验证。
        返回加载的代理数量。
        """
        try:
            if not os.path.isfile(_PROXY_CACHE_FILE):
                return 0
            with open(_PROXY_CACHE_FILE, 'r', encoding='utf-8') as f:
                cache = json.load(f)
            if not isinstance(cache, dict):
                return 0
            now = time.time()
            loaded = 0
            # 恢复代理源质量统计（跨进程持久化：cron 每次新进程也能延续择优 / 轮换）
            stats = cache.get('source_stats')
            if isinstance(stats, dict):
                self._source_stats = {
                    name: {
                        "candidates": float(s.get("candidates", 0) or 0),
                        "validated": float(s.get("validated", 0) or 0),
                        "passed": float(s.get("passed", 0) or 0),
                        "attempts": int(s.get("attempts", 0) or 0),
                        "last_active": float(s.get("last_active", 0) or 0),
                    }
                    for name, s in stats.items() if isinstance(s, dict)
                }
            for proxy_url, info in cache.get('proxies', {}).items():
                # 跳过过期缓存
                last_verified = info.get('last_verified', 0)
                if now - last_verified > PROXY_CACHE_MAX_AGE:
                    continue
                # 跳过已在池中的（手动代理优先）
                if proxy_url in self._pool:
                    continue
                self._pool[proxy_url] = {
                    "fail_count": 0,
                    "last_verified": last_verified,
                    "manual": False,
                    "https_ok": info.get("https_ok", False),
                }
                loaded += 1
            if loaded > 0:
                logging.info(f"代理池：从磁盘缓存加载了 {loaded} 个代理（待验证）")
            return loaded
        except Exception:
            logging.debug("代理池：加载磁盘缓存异常", exc_info=True)
            return 0

    def _save_disk_cache(self):
        """将当前可用代理持久化到磁盘"""
        try:
            with self._lock:
                available = {
                    p: {"last_verified": info["last_verified"], "https_ok": info.get("https_ok", False)}
                    for p, info in self._pool.items()
                    if info["fail_count"] < PROXY_MAX_FAIL_COUNT and not info.get("manual", False)
                }
                source_stats = {k: dict(v) for k, v in self._source_stats.items()}
            if not available and not source_stats:
                return
            os.makedirs(os.path.dirname(_PROXY_CACHE_FILE), exist_ok=True)
            cache = {"saved_at": time.time(), "proxies": available, "source_stats": source_stats}
            with open(_PROXY_CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(cache, f, indent=2)
            logging.debug(f"代理池：已缓存 {len(available)} 个代理 / {len(source_stats)} 个源统计到磁盘")
        except Exception:
            logging.debug("代理池：保存磁盘缓存异常", exc_info=True)

    def _upgrade_https_in_background(self):
        """对池中未测试 HTTPS 的代理补充 HTTPS 验证（低优先级）"""
        with self._lock:
            to_upgrade = [p for p, info in self._pool.items()
                          if info["fail_count"] < PROXY_MAX_FAIL_COUNT and not info.get("https_ok")]
        if not to_upgrade:
            return

        import concurrent.futures
        https_upgraded = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=PROXY_FETCH_WORKERS) as executor:
            futures = {}
            for proxy_url in to_upgrade:
                # 只做 HTTPS 单项验证
                futures[executor.submit(self._validate_https_only, proxy_url)] = proxy_url
            for future in concurrent.futures.as_completed(futures):
                proxy_url = futures[future]
                try:
                    https_ok = future.result()
                    if https_ok:
                        with self._lock:
                            if proxy_url in self._pool:
                                self._pool[proxy_url]["https_ok"] = True
                                https_upgraded += 1
                except Exception:
                    pass
        if https_upgraded > 0:
            logging.info(f"代理池：HTTPS升级完成，{https_upgraded} 个代理支持 HTTPS 隧道")

    def _validate_https_only(self, proxy_url):
        """仅验证 HTTPS 隧道（假设 HTTP 已通过验证）"""
        proxies = {"http": proxy_url, "https": proxy_url}
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://quote.eastmoney.com/',
        }
        try:
            r = requests.get(
                "https://push2.eastmoney.com/api/qt/clist/get",
                headers=headers,
                proxies=proxies,
                timeout=PROXY_VALIDATE_TIMEOUT,
                params={"pn": "1", "pz": "3", "fields": "f2,f12,f14",
                        "fs": "m:0+t:6+f:!2", "ut": "fa5fd1943c7b386f172d6893dbfba10b"}
            )
            return r.status_code == 200 and len(r.text) > 50
        except Exception:
            return False

    def _initial_fetch(self):
        """初始化抓取：选取6个源获取代理并验证（仅HTTP，跳过HTTPS以加速）"""
        logging.info("代理池：正在从免费代理源获取代理（初始化，选取6个源）...")
        candidates = self._fetch_from_sources(num_sources=6)
        if candidates:
            random.shuffle(candidates)
            batch = candidates[:PROXY_INIT_BATCH_SIZE]
            verified = self._batch_validate(batch, http_only=True)
            logging.info(f"代理池：获取 {len(candidates)} 个候选代理，验证 {len(batch)} 个，通过 {len(verified)} 个")
        else:
            logging.warning("代理池：未能从免费代理源获取到候选代理")
        self._initialized = True

    # ══════════════════════════════════════════════
    # 公共接口（与旧版兼容）
    # ══════════════════════════════════════════════

    def get_data(self):
        """兼容旧接口：返回所有可用代理列表"""
        with self._lock:
            available = [p for p, info in self._pool.items() if info["fail_count"] < PROXY_MAX_FAIL_COUNT]
            return available if available else None

    @property
    def data(self):
        return self.get_data()

    def get_proxies(self):
        """
        随机返回一个可用代理。

        策略：
        - 代理池充足时（>= 10）：30% 直连概率
        - 代理池偏少时（3~9）：60% 直连概率（避免少量代理被过度使用导致全部封禁）
        - 代理池极少时（< 3）：80% 直连概率（几乎全部直连，代理仅偶尔使用）
        - 优先选择最近验证时间较新的代理（过期太久的代理可能已失效）
        - 有 HTTPS 可用代理时，50% 概率选 HTTPS 代理（支持所有流量）
        - 否则返回 HTTP-only 代理（仅代理 HTTP 请求，HTTPS 走直连）

        返回：{"http": proxy, "https": proxy} 或 {"http": proxy} 或 None
        """
        with self._lock:
            all_available = [(p, info) for p, info in self._pool.items()
                             if info["fail_count"] < PROXY_MAX_FAIL_COUNT]

        if not all_available:
            # 代理池已耗尽，触发异步紧急补充（不阻塞当前请求）
            self._trigger_emergency_refresh()
            return None

        # 根据代理池大小动态调整直连概率
        pool_count = len(all_available)
        if pool_count >= 10:
            direct_probability = 0.3
        elif pool_count >= PROXY_MIN_POOL_SIZE:
            direct_probability = 0.6
        else:
            direct_probability = 0.8

        if random.random() < direct_probability:
            return None

        # 过滤掉验证时间过久的代理（超过 PROXY_STALE_SECONDS 秒未验证的降低权重）
        now = time.time()

        # 分离 HTTPS 可用和 HTTP-only 代理
        https_proxies = [(p, info) for p, info in all_available if info.get("https_ok")]
        http_only_proxies = [(p, info) for p, info in all_available if not info.get("https_ok")]

        # 如果有 HTTPS 代理，50% 概率优先用（避免少量HTTPS代理被过度使用）
        if https_proxies and (not http_only_proxies or random.random() < 0.5):
            proxy = self._freshness_weighted_choice(https_proxies, now)
            return {"http": proxy, "https": proxy}

        # 使用 HTTP-only 代理：仅代理 HTTP 流量，HTTPS 走直连
        if all_available:
            proxy = self._freshness_weighted_choice(all_available, now)
            return {"http": proxy}

        return None

    def get_https_proxy(self):
        """返回一个支持 HTTPS 隧道的代理 URL（字符串），无可用时返回 None（直连）。

        用于 HTTPS 接口（如东方财富 datacenter / 同花顺 / Google Patents），
        这些接口经 HTTP-only 代理无法隧道转发，必须使用 https_ok 代理。
        与 get_proxies 一样保留一定直连概率以分散来源、降低单一 IP 被限流的风险。
        """
        with self._lock:
            https_proxies = [(p, info) for p, info in self._pool.items()
                             if info["fail_count"] < PROXY_MAX_FAIL_COUNT and info.get("https_ok")]

        if not https_proxies:
            # 没有 HTTPS 代理可用：若池子整体也空了，触发紧急补充
            if self.pool_size() == 0:
                self._trigger_emergency_refresh()
            return None

        # 动态直连概率：HTTPS 代理较稀缺，池子越大越可放心使用代理
        count = len(https_proxies)
        direct_probability = 0.3 if count >= 5 else (0.5 if count >= PROXY_MIN_POOL_SIZE else 0.7)
        if random.random() < direct_probability:
            return None

        return self._freshness_weighted_choice(https_proxies, time.time())

    def _freshness_weighted_choice(self, available_with_info, now):
        """加权随机选择：失败次数越少 + 验证时间越新 → 权重越高

        权重 = (MAX_FAIL - fail_count) * freshness_factor
        freshness_factor:
          - 验证在 PROXY_STALE_SECONDS 秒之内: 1.0
          - 超过 PROXY_STALE_SECONDS 秒: 0.3（大幅降低但不为零，仍可被选中）
        """
        weights = []
        for p, info in available_with_info:
            fail = info.get("fail_count", 0)
            base_weight = max(1, PROXY_MAX_FAIL_COUNT - fail)
            # 新鲜度衰减
            age = now - info.get("last_verified", 0)
            freshness = 1.0 if age < PROXY_STALE_SECONDS else 0.3
            weights.append(base_weight * freshness)
        proxies = [p for p, _ in available_with_info]
        return random.choices(proxies, weights=weights, k=1)[0]

    def report_failure(self, proxy_url):
        """
        报告代理失败（由调用方在请求失败时调用）
        累积失败次数达阈值后自动从池中移除
        """
        if proxy_url is None:
            return
        with self._lock:
            if proxy_url in self._pool:
                self._pool[proxy_url]["fail_count"] += 1
                if self._pool[proxy_url]["fail_count"] >= PROXY_MAX_FAIL_COUNT:
                    is_manual = self._pool[proxy_url].get("manual", False)
                    if not is_manual:
                        del self._pool[proxy_url]
                        logging.debug(f"代理池：移除失败代理 {proxy_url}")

    def report_success(self, proxy_url):
        """报告代理成功，重置失败计数"""
        if proxy_url is None:
            return
        with self._lock:
            if proxy_url in self._pool:
                self._pool[proxy_url]["fail_count"] = 0
                self._pool[proxy_url]["last_verified"] = time.time()

    def pool_size(self):
        """返回当前可用代理数量"""
        with self._lock:
            return len([p for p, info in self._pool.items() if info["fail_count"] < PROXY_MAX_FAIL_COUNT])

    def force_refresh(self):
        """手动触发刷新"""
        threading.Thread(target=self._refresh_cycle, daemon=True).start()

    def ensure_https_upgraded(self):
        """公开接口：对池中尚未验证 HTTPS 的代理补充 HTTPS 隧道验证（阻塞至完成）。

        供常驻预热守护周期性调用，为 https:// 接口（如东财股票实时行情
        push2.eastmoney.com HTTPS 端点）持续养出 https_ok 代理。
        若无待升级代理，方法内部立即返回。
        """
        self._upgrade_https_in_background()

    def persist(self):
        """公开接口：将当前可用代理及数据源统计落盘到磁盘缓存。

        磁盘缓存是 cron 短命进程之间共享可用代理的唯一载体，预热守护
        通过持续落盘，让每个短进程启动即可从缓存秒加载可用代理。
        """
        self._save_disk_cache()

    def _trigger_emergency_refresh(self):
        """
        代理池耗尽时触发紧急补充（异步，不阻塞调用方）。

        防抖：PROXY_EMERGENCY_COOLDOWN 秒内最多触发一次。
        紧急补充使用更多代理源（8个）以尽快恢复可用代理。
        """
        now = time.time()
        with self._lock:
            last = getattr(self, '_last_emergency_refresh', 0)
            if now - last < PROXY_EMERGENCY_COOLDOWN:
                return  # 冷却期内已触发过，跳过
            self._last_emergency_refresh = now
        logging.warning("代理池：可用代理已耗尽，触发紧急补充（异步）")
        threading.Thread(target=self._emergency_fetch, daemon=True).start()

    def _emergency_fetch(self):
        """紧急补充：使用更多代理源（8个），快速恢复代理池"""
        try:
            candidates = self._fetch_from_sources(num_sources=8)
            if candidates:
                random.shuffle(candidates)
                batch = candidates[:PROXY_INIT_BATCH_SIZE]
                verified = self._batch_validate(batch, http_only=True)
                logging.info(f"代理池：紧急补充完成，新增 {len(verified)} 个，当前可用 {self.pool_size()} 个")
                self._save_disk_cache()
        except Exception as e:
            logging.warning(f"代理池：紧急补充异常: {e}")

    # ══════════════════════════════════════════════
    # 免费代理源抓取
    # ══════════════════════════════════════════════

    def _get_all_fetchers(self):
        """返回所有代理源，按优先级分层

        Tier 1（快速可靠，API接口或小型列表）：优先选取
        Tier 2（GitHub大型列表，数据量大但获取较慢）：补充选取
        """
        tier1 = [
            ("proxylist.geonode.com", self._fetch_geonode),
            ("proxy-list.download", self._fetch_proxy_list_download),
            ("proxifly/free-proxy-list", self._fetch_proxifly),
            ("monosans/proxy-list", self._fetch_monosans),
            ("www.fate0.com/proxylist", self._fetch_fate0),
        ]
        tier2 = [
            ("TheSpeedX/PROXY-List", self._fetch_thespeedx),
            ("clarketm/proxy-list", self._fetch_clarketm),
            ("mmpx12/proxy-list", self._fetch_mmpx12),
            ("roosterkid/openproxylist", self._fetch_roosterkid),
            ("sunny9577/proxy-scraper", self._fetch_sunny9577),
            ("MuRongPIG/Proxy-Master", self._fetch_murongpig),
            ("rdavydov/proxy-list", self._fetch_rdavydov),
        ]
        return tier1, tier2

    def _source_score(self, name):
        """计算代理源的"择优分数" = 平滑存活率 × 活跃度。

        - 平滑存活率：(passed + 1) / (validated + 2)（贝叶斯平滑，避免小样本极端值）
        - 活跃度：最近仍能抓到候选（last_active 近、candidates>0）→ 1.0，否则衰减
        样本不足（validated < PROXY_SOURCE_MIN_SAMPLES）的源返回 None，按"待探索"处理。
        """
        s = self._source_stats.get(name)
        if not s:
            return None
        validated = s.get("validated", 0)
        if validated < PROXY_SOURCE_MIN_SAMPLES:
            return None
        passed = s.get("passed", 0)
        survival = (passed + 1.0) / (validated + 2.0)
        # 活跃度：近 24h 有产出权重高；越久没产出权重越低
        age = time.time() - s.get("last_active", 0)
        if age < 6 * 3600:
            activity = 1.0
        elif age < 24 * 3600:
            activity = 0.7
        else:
            activity = 0.4
        if s.get("candidates", 0) <= 0:
            activity *= 0.5
        return survival * activity

    def _select_sources_by_quality(self, num_sources):
        """按"活跃度 + 存活率"动态择优选取数据源，并保留探索/轮换名额。

        机制（实现"每隔一段时间重新更换免费代理数据源"）：
        - 利用（exploitation）：选取历史存活率高、近期活跃的源（占大头）
        - 探索（exploration）：按 PROXY_SOURCE_EXPLORE_RATIO 比例随机选取
          "样本不足/久未尝试/低分"的源重新试探，使数据源持续轮换、择优更新
        - 配合 _refresh_cycle 中对统计的指数衰减（PROXY_SOURCE_DECAY），
          旧的优胜源分数会随时间回落，从而被定期重新评估、替换。
        """
        tier1, tier2 = self._get_all_fetchers()
        all_fetchers = tier1 + tier2
        if num_sources is None or num_sources >= len(all_fetchers):
            return all_fetchers

        with self._lock:
            scored = []      # [(score, name, fetcher)] 已有足够样本的源
            unscored = []    # [(name, fetcher)] 待探索的源（样本不足/从未尝试）
            last_active = {}
            for name, fn in all_fetchers:
                sc = self._source_score(name)
                if sc is None:
                    unscored.append((name, fn))
                else:
                    scored.append((sc, name, fn))
                last_active[name] = self._source_stats.get(name, {}).get("last_active", 0)

        explore_n = max(1, int(round(num_sources * PROXY_SOURCE_EXPLORE_RATIO)))
        exploit_n = max(0, num_sources - explore_n)

        # 利用：取历史分数最高的源
        scored.sort(key=lambda x: x[0], reverse=True)
        selected = [(name, fn) for _, name, fn in scored[:exploit_n]]

        # 探索池：优先"待探索"源，其次"近期最久未尝试"的低分源（实现轮换）
        explore_pool = list(unscored)
        leftover_scored = [(name, fn) for _, name, fn in scored[exploit_n:]]
        leftover_scored.sort(key=lambda nf: last_active.get(nf[0], 0))  # 越久没尝试越靠前
        random.shuffle(explore_pool)
        explore_pool += leftover_scored

        for item in explore_pool:
            if len(selected) >= num_sources:
                break
            if item not in selected:
                selected.append(item)

        # 兜底：仍不足则从全部源随机补齐
        if len(selected) < num_sources:
            remaining = [f for f in all_fetchers if f not in selected]
            random.shuffle(remaining)
            selected += remaining[:num_sources - len(selected)]

        return selected[:num_sources]

    def _credit_source_validation(self, batch, verified):
        """把一批候选的验证结果归因到其来源，更新 validated / passed 统计（存活率）。"""
        if not batch:
            return
        fmap = self._fetch_source_map
        if not fmap:
            return
        verified_set = set(verified or [])
        with self._lock:
            for proxy in batch:
                name = fmap.get(proxy)
                if not name:
                    continue
                st = self._source_stats.setdefault(
                    name, {"candidates": 0.0, "validated": 0.0, "passed": 0.0,
                           "attempts": 0, "last_active": 0.0})
                st["validated"] = st.get("validated", 0) + 1
                if proxy in verified_set:
                    st["passed"] = st.get("passed", 0) + 1

    def _decay_source_stats(self):
        """对代理源累计统计做指数衰减，使评分随时间"遗忘"，便于定期重新评估/轮换数据源。"""
        if PROXY_SOURCE_DECAY >= 1.0:
            return
        with self._lock:
            for st in self._source_stats.values():
                for k in ("candidates", "validated", "passed"):
                    st[k] = st.get(k, 0) * PROXY_SOURCE_DECAY
                    if st[k] < 0.01:
                        st[k] = 0.0

    def _fetch_from_sources(self, num_sources=None):
        """从代理源中选取 num_sources 个并发抓取，返回去重列表。

        选取策略：
        - num_sources=None: 全部源（仅在定时全量刷新时使用）
        - num_sources=N: 按"活跃度 + 存活率"动态择优 + 探索轮换（见 _select_sources_by_quality）
        - 早停机制：已获取足够候选时不再等未完成的慢源

        同时记录 候选->来源 映射与每源抓取量（活跃度），供后续验证结果归因。
        每个代理源独立抓取，单个源失败不影响其他源。
        """
        if num_sources is not None:
            fetchers = self._select_sources_by_quality(num_sources)
        else:
            tier1, tier2 = self._get_all_fetchers()
            fetchers = tier1 + tier2

        candidates = set()
        fetch_source_map = {}   # proxy -> 首个贡献它的来源
        per_source_new = {}     # name -> 本次新增候选数
        selected_names = [name for name, _ in fetchers]
        # 排除已在池中的代理（避免重复验证）
        with self._lock:
            existing = set(self._pool.keys())
        # 候选目标数：需要补充到 PROXY_TARGET_POOL_SIZE 的量 + 冗余（验证通过率约5-15%）
        target_candidates = max(PROXY_INIT_BATCH_SIZE, (PROXY_TARGET_POOL_SIZE - self.pool_size()) * 15)

        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(fetchers), 10)) as executor:
            future_to_name = {executor.submit(fetcher): name for name, fetcher in fetchers}
            for future in concurrent.futures.as_completed(future_to_name):
                name = future_to_name[future]
                try:
                    proxies = future.result()
                    if proxies:
                        new_proxies = [p for p in proxies if p not in existing and p not in candidates]
                        candidates.update(new_proxies)
                        for p in new_proxies:
                            fetch_source_map.setdefault(p, name)
                        per_source_new[name] = per_source_new.get(name, 0) + len(new_proxies)
                        logging.debug(f"代理池：从 {name} 获取 {len(proxies)} 个候选（新 {len(new_proxies)} 个）")
                except Exception as e:
                    logging.debug(f"代理池：从 {name} 获取失败: {e}")
                # 早停：已获取足够候选就不再等待（但不强制取消未完成的任务）
                if len(candidates) >= target_candidates:
                    logging.debug(f"代理池：已获取 {len(candidates)} 个候选，达到目标 {target_candidates}，跳过剩余源")
                    # 取消未开始的任务
                    for f in future_to_name:
                        f.cancel()
                    break

        # 更新来源活跃度统计（candidates / attempts / last_active），并记录归因映射
        now = time.time()
        with self._lock:
            self._fetch_source_map = fetch_source_map
            for name in selected_names:
                st = self._source_stats.setdefault(
                    name, {"candidates": 0.0, "validated": 0.0, "passed": 0.0,
                           "attempts": 0, "last_active": 0.0})
                st["attempts"] = st.get("attempts", 0) + 1
                new_n = per_source_new.get(name, 0)
                if new_n > 0:
                    st["candidates"] = st.get("candidates", 0) + new_n
                    st["last_active"] = now

        logging.info(f"代理池：从 {len(fetchers)} 个来源获取 {len(candidates)} 个候选代理")
        return list(candidates)

    def _fetch_geonode(self):
        """从 geonode.com 获取免费代理"""
        proxies = []
        try:
            url = "https://proxylist.geonode.com/api/proxy-list?limit=50&page=1&sort_by=lastChecked&sort_type=desc&protocols=http%2Chttps&anonymityLevel=elite%2Canonymous"
            r = requests.get(url, timeout=10, headers=self._ua_headers())
            if r.status_code == 200:
                data = r.json()
                for item in data.get("data", []):
                    ip = item.get("ip")
                    port = item.get("port")
                    protocols = item.get("protocols", [])
                    if ip and port:
                        proto = "https" if "https" in protocols else "http"
                        proxies.append(f"{proto}://{ip}:{port}")
        except Exception:
            logging.debug("代理池：从 geonode 获取异常", exc_info=True)
        return proxies

    def _fetch_fate0(self):
        """从 fate0 proxy list 获取"""
        proxies = []
        try:
            url = "http://proxylist.fate0.com/proxy.list"
            r = requests.get(url, timeout=10, headers=self._ua_headers())
            if r.status_code == 200:
                import json
                for line in r.text.strip().split("\n"):
                    try:
                        item = json.loads(line)
                        host = item.get("host")
                        port = item.get("port")
                        proto = item.get("type", "http")
                        if host and port:
                            proxies.append(f"{proto}://{host}:{port}")
                    except Exception:
                        continue
        except Exception:
            logging.debug("代理池：从 fate0 获取异常", exc_info=True)
        return proxies

    @staticmethod
    def _normalize_proxy(line, default_proto="http"):
        """规范化代理地址格式，确保有协议前缀且不重复"""
        line = line.strip()
        if not line or ":" not in line:
            return None
        # 已有协议前缀
        if line.startswith("http://") or line.startswith("https://") or line.startswith("socks"):
            return line
        # 纯 IP:PORT 格式
        return f"{default_proto}://{line}"

    def _fetch_proxifly(self):
        """从 proxifly GitHub 获取（返回格式：http://IP:PORT）"""
        proxies = []
        urls = [
            "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/http/data.txt",
            "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/https/data.txt",
        ]
        for url in urls:
            try:
                r = requests.get(url, timeout=10, headers=self._ua_headers())
                if r.status_code == 200:
                    for line in r.text.strip().split("\n"):
                        p = self._normalize_proxy(line)
                        if p:
                            proxies.append(p)
            except Exception:
                logging.debug("代理池：从 proxifly 获取异常", exc_info=True)
                continue
        return proxies

    def _fetch_thespeedx(self):
        """从 TheSpeedX/PROXY-List GitHub 获取（返回格式：IP:PORT）"""
        proxies = []
        try:
            url = "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt"
            r = requests.get(url, timeout=15, headers=self._ua_headers())
            if r.status_code == 200:
                lines = r.text.strip().split("\n")
                # 取前500个（该源通常有5000+个，全部验证太慢）
                for line in lines[:500]:
                    p = self._normalize_proxy(line, "http")
                    if p:
                        proxies.append(p)
        except Exception:
            logging.debug("代理池：从 TheSpeedX 获取异常", exc_info=True)
        return proxies

    def _fetch_monosans(self):
        """从 monosans/proxy-list GitHub 获取（返回格式：IP:PORT）"""
        proxies = []
        try:
            url = "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt"
            r = requests.get(url, timeout=15, headers=self._ua_headers())
            if r.status_code == 200:
                lines = r.text.strip().split("\n")
                for line in lines[:500]:
                    p = self._normalize_proxy(line, "http")
                    if p:
                        proxies.append(p)
        except Exception:
            logging.debug("代理池：从 monosans 获取异常", exc_info=True)
        return proxies

    def _fetch_clarketm(self):
        """从 clarketm/proxy-list GitHub 获取"""
        proxies = []
        try:
            url = "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt"
            r = requests.get(url, timeout=15, headers=self._ua_headers())
            if r.status_code == 200:
                for line in r.text.strip().split("\n")[:300]:
                    p = self._normalize_proxy(line, "http")
                    if p:
                        proxies.append(p)
        except Exception:
            logging.debug("代理池：从 clarketm 获取异常", exc_info=True)
        return proxies

    def _fetch_mmpx12(self):
        """从 mmpx12/proxy-list GitHub 获取（HTTP + HTTPS）"""
        proxies = []
        urls = [
            "https://raw.githubusercontent.com/mmpx12/proxy-list/master/http.txt",
            "https://raw.githubusercontent.com/mmpx12/proxy-list/master/https.txt",
        ]
        for url in urls:
            try:
                r = requests.get(url, timeout=15, headers=self._ua_headers())
                if r.status_code == 200:
                    proto = "https" if "https.txt" in url else "http"
                    for line in r.text.strip().split("\n")[:300]:
                        p = self._normalize_proxy(line, proto)
                        if p:
                            proxies.append(p)
            except Exception:
                logging.debug("代理池：从 mmpx12 获取异常", exc_info=True)
                continue
        return proxies

    def _fetch_roosterkid(self):
        """从 roosterkid/openproxylist GitHub 获取"""
        proxies = []
        try:
            url = "https://raw.githubusercontent.com/roosterkid/openproxylist/main/HTTPS_RAW.txt"
            r = requests.get(url, timeout=15, headers=self._ua_headers())
            if r.status_code == 200:
                for line in r.text.strip().split("\n")[:300]:
                    p = self._normalize_proxy(line, "https")
                    if p:
                        proxies.append(p)
        except Exception:
            logging.debug("代理池：从 roosterkid 获取异常", exc_info=True)
        return proxies

    def _fetch_sunny9577(self):
        """从 sunny9577/proxy-scraper GitHub 获取"""
        proxies = []
        urls = [
            "https://raw.githubusercontent.com/sunny9577/proxy-scraper/master/generated/http_proxies.txt",
            "https://raw.githubusercontent.com/sunny9577/proxy-scraper/master/generated/https_proxies.txt",
        ]
        for url in urls:
            try:
                r = requests.get(url, timeout=15, headers=self._ua_headers())
                if r.status_code == 200:
                    proto = "https" if "https_proxies" in url else "http"
                    for line in r.text.strip().split("\n")[:300]:
                        p = self._normalize_proxy(line, proto)
                        if p:
                            proxies.append(p)
            except Exception:
                logging.debug("代理池：从 sunny9577 获取异常", exc_info=True)
                continue
        return proxies

    def _fetch_murongpig(self):
        """从 MuRongPIG/Proxy-Master GitHub 获取"""
        proxies = []
        try:
            url = "https://raw.githubusercontent.com/MuRongPIG/Proxy-Master/main/http.txt"
            r = requests.get(url, timeout=15, headers=self._ua_headers())
            if r.status_code == 200:
                for line in r.text.strip().split("\n")[:300]:
                    p = self._normalize_proxy(line, "http")
                    if p:
                        proxies.append(p)
        except Exception:
            logging.debug("代理池：从 MuRongPIG 获取异常", exc_info=True)
        return proxies

    def _fetch_rdavydov(self):
        """从 rdavydov/proxy-list GitHub 获取"""
        proxies = []
        urls = [
            "https://raw.githubusercontent.com/rdavydov/proxy-list/main/proxies/http.txt",
            "https://raw.githubusercontent.com/rdavydov/proxy-list/main/proxies/https.txt",
        ]
        for url in urls:
            try:
                r = requests.get(url, timeout=15, headers=self._ua_headers())
                if r.status_code == 200:
                    proto = "https" if "https.txt" in url else "http"
                    for line in r.text.strip().split("\n")[:300]:
                        p = self._normalize_proxy(line, proto)
                        if p:
                            proxies.append(p)
            except Exception:
                logging.debug("代理池：从 rdavydov 获取异常", exc_info=True)
                continue
        return proxies

    def _fetch_proxy_list_download(self):
        """从 proxy-list.download 获取（API接口）"""
        proxies = []
        urls = [
            "https://www.proxy-list.download/api/v1/get?type=http",
            "https://www.proxy-list.download/api/v1/get?type=https",
        ]
        for url in urls:
            try:
                r = requests.get(url, timeout=15, headers=self._ua_headers())
                if r.status_code == 200:
                    proto = "https" if "type=https" in url else "http"
                    for line in r.text.strip().split("\r\n"):
                        p = self._normalize_proxy(line.strip(), proto)
                        if p:
                            proxies.append(p)
            except Exception:
                logging.debug("代理池：从 proxy-list.download 获取异常", exc_info=True)
                continue
        return proxies

    # ══════════════════════════════════════════════
    # 代理验证
    # ══════════════════════════════════════════════

    def _validate_one(self, proxy_url, http_only=False):
        """
        验证单个代理是否可用
        1. 先测 HTTP 连通性（用东方财富 datacenter API）
        2. http_only=False 时，再测 HTTPS 隧道支持（用 push2 API）
        返回 (http_ok, https_ok)
        """
        proxies = {"http": proxy_url, "https": proxy_url}
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        }

        # Step 1: HTTP 验证
        http_ok = False
        try:
            r = requests.get(
                PROXY_VALIDATE_URL,
                headers=headers,
                proxies=proxies,
                timeout=PROXY_VALIDATE_TIMEOUT,
                params={"type": "RPT_DAILYBILLBOARD_DETAILSNEW", "sty": "ALL", "p": "1", "ps": "3"}
            )
            if r.status_code == 200 and len(r.text) > 100:
                try:
                    data = r.json()
                    http_ok = data is not None
                except Exception:
                    logging.debug(f"代理验证JSON解析失败：{proxy_url}")
        except Exception:
            pass  # 网络不通是正常情况，不记录

        if not http_ok:
            return False, False

        # http_only 模式跳过 HTTPS 验证（初始化时用，节省一半时间）
        if http_only:
            return True, False

        # Step 2: HTTPS 隧道验证（可选，不通过也保留为 HTTP-only 代理）
        https_ok = False
        try:
            r2 = requests.get(
                "https://push2.eastmoney.com/api/qt/clist/get",
                headers={**headers, 'Referer': 'https://quote.eastmoney.com/'},
                proxies=proxies,
                timeout=PROXY_VALIDATE_TIMEOUT,
                params={"pn": "1", "pz": "3", "fields": "f2,f12,f14",
                        "fs": "m:0+t:6+f:!2", "ut": "fa5fd1943c7b386f172d6893dbfba10b"}
            )
            if r2.status_code == 200 and len(r2.text) > 50:
                https_ok = True
        except Exception:
            pass  # HTTPS隧道不通是正常情况，保留为HTTP-only代理

        return http_ok, https_ok

    def _batch_validate(self, candidates, max_workers=None, http_only=False):
        """
        批量并发验证代理，将通过验证的加入池中
        http_only=True 时跳过 HTTPS 验证（初始化加速）
        返回通过验证的代理列表
        """
        if not candidates:
            return []

        if max_workers is None:
            max_workers = PROXY_FETCH_WORKERS

        # 排除已在池中的
        with self._lock:
            existing = set(self._pool.keys())
        new_candidates = [p for p in candidates if p not in existing]

        if not new_candidates:
            return []

        verified = []
        https_count = 0
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_proxy = {executor.submit(self._validate_one, p, http_only): p for p in new_candidates}
            for future in concurrent.futures.as_completed(future_to_proxy):
                proxy = future_to_proxy[future]
                try:
                    http_ok, https_ok = future.result()
                    if http_ok:
                        with self._lock:
                            self._pool[proxy] = {
                                "fail_count": 0,
                                "last_verified": time.time(),
                                "manual": False,
                                "https_ok": https_ok,
                            }
                        verified.append(proxy)
                        if https_ok:
                            https_count += 1
                except Exception:
                    logging.debug(f"代理池：验证代理线程异常：{proxy}", exc_info=True)

        # 把验证结果归因到数据源（更新各源存活率统计）
        self._credit_source_validation(new_candidates, verified)

        if https_count > 0:
            logging.info(f"代理池：其中 {https_count} 个支持 HTTPS 隧道")
        return verified

    def _revalidate_existing(self, http_only=False):
        """重新验证池中已有代理，移除不可用的"""
        with self._lock:
            to_check = list(self._pool.keys())

        if not to_check:
            return

        removed = 0
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=PROXY_FETCH_WORKERS) as executor:
            future_to_proxy = {executor.submit(self._validate_one, p, http_only): p for p in to_check}
            for future in concurrent.futures.as_completed(future_to_proxy):
                proxy = future_to_proxy[future]
                try:
                    http_ok, https_ok = future.result()
                    with self._lock:
                        if proxy in self._pool:
                            if http_ok:
                                self._pool[proxy]["fail_count"] = 0
                                self._pool[proxy]["last_verified"] = time.time()
                                self._pool[proxy]["https_ok"] = https_ok
                            else:
                                is_manual = self._pool[proxy].get("manual", False)
                                if is_manual:
                                    self._pool[proxy]["fail_count"] = min(
                                        self._pool[proxy]["fail_count"] + 1,
                                        PROXY_MAX_FAIL_COUNT
                                    )
                                else:
                                    del self._pool[proxy]
                                    removed += 1
                except Exception:
                    logging.debug(f"代理池：重新验证线程异常：{proxy}", exc_info=True)

        if removed > 0:
            logging.info(f"代理池：重新验证完成，移除 {removed} 个失效代理，剩余 {self.pool_size()} 个")

    # ══════════════════════════════════════════════
    # 后台自动刷新
    # ══════════════════════════════════════════════

    def _start_background_refresh(self):
        """启动后台刷新线程"""
        if self._running:
            return
        self._running = True
        self._refresh_thread = threading.Thread(target=self._background_loop, daemon=True)
        self._refresh_thread.start()
        logging.info(f"代理池：后台刷新已启动（间隔 {PROXY_REFRESH_INTERVAL} 秒）")

    def _background_loop(self):
        """后台循环：定时刷新代理池"""
        while self._running:
            try:
                time.sleep(PROXY_REFRESH_INTERVAL)
                self._refresh_cycle()
            except Exception as e:
                logging.debug(f"代理池：后台刷新异常: {e}")

    def _refresh_cycle(self):
        """单次刷新：重新验证现有代理 + 按需补充新代理

        补充策略（分级响应）：
        - pool_size < PROXY_MIN_POOL_SIZE (3): 紧急，选8个源大量补充
        - pool_size < PROXY_TARGET_POOL_SIZE (15): 常规，选4个源适量补充
        - pool_size >= PROXY_TARGET_POOL_SIZE: 健康，不补充
        """
        # Step 0: 对代理源历史统计做指数衰减（实现"定期重新评估 / 更换数据源"）
        #   旧的优胜源分数随时间回落，配合 _select_sources_by_quality 的探索名额被重新评估、替换
        self._decay_source_stats()

        # Step 1: 重新验证现有代理
        self._revalidate_existing()

        # Step 2: 按需补充新代理（分级响应）
        current_size = self.pool_size()
        if current_size < PROXY_MIN_POOL_SIZE:
            # 紧急：代理严重不足，多选源快速补充
            num_sources = 8
            logging.info(f"代理池：可用代理严重不足（{current_size}/{PROXY_MIN_POOL_SIZE}），紧急补充（{num_sources}个源）...")
            candidates = self._fetch_from_sources(num_sources=num_sources)
            if candidates:
                random.shuffle(candidates)
                verified = self._batch_validate(candidates[:PROXY_INIT_BATCH_SIZE], http_only=True)
                logging.info(f"代理池：紧急补充完成，新增 {len(verified)} 个，当前可用 {self.pool_size()} 个")
        elif current_size < PROXY_TARGET_POOL_SIZE:
            # 常规：代理偏少，少选源适量补充
            num_sources = 4
            logging.info(f"代理池：可用代理偏少（{current_size}/{PROXY_TARGET_POOL_SIZE}），常规补充（{num_sources}个源）...")
            candidates = self._fetch_from_sources(num_sources=num_sources)
            if candidates:
                random.shuffle(candidates)
                need = PROXY_TARGET_POOL_SIZE - current_size
                batch_size = min(len(candidates), max(need * 15, 100))  # 按需验证，通过率约5-15%
                verified = self._batch_validate(candidates[:batch_size], http_only=True)
                logging.info(f"代理池：常规补充完成，新增 {len(verified)} 个，当前可用 {self.pool_size()} 个")
        else:
            logging.debug(f"代理池：当前可用 {current_size} 个代理，状态健康")

        # Step 3: 重新加载 proxy.txt（支持运行时修改）
        self._load_manual_proxies()

        # Step 4: 持久化到磁盘
        self._save_disk_cache()

    def stop(self):
        """停止后台刷新"""
        self._running = False

    @staticmethod
    def _ua_headers():
        """返回随机 User-Agent 请求头"""
        uas = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
        ]
        return {"User-Agent": random.choice(uas)}


# ══════════════════════════════════════════════════════════════
# 通用代理请求封装：供各采集器（巨潮 / Google Patents 等）复用
# ══════════════════════════════════════════════════════════════

def proxied_request(method, url, *, max_attempts=3, **kwargs):
    """通过代理池发起 HTTP(S) 请求，失败自动更换代理重试，最终回退直连。

    - 自动从代理池取代理：HTTPS URL 取 https_ok 代理（get_https_proxy），
      HTTP URL 用 get_proxies（HTTP-only 代理即可）。两者均保留一定直连概率，
      以分散来源、降低单一出口 IP 被限流的风险。
    - 请求传输异常（连接/超时等）时上报 report_failure 并更换代理重试；
      成功则 report_success。注意：HTTP 状态码（如 429）由调用方判断，
      本函数仅在抛出传输异常时才轮换。
    - 重试耗尽后做一次直连兜底，尽量不因代理问题导致整体失败。

    返回 requests.Response；全部失败则抛出最后一次异常。
    用法：proxied_request('get', url, headers=..., timeout=..., stream=True)
    """
    pool = proxys()
    is_https = str(url).lower().startswith('https')
    last_exc = None
    for _ in range(max(1, max_attempts)):
        if is_https:
            p = pool.get_https_proxy()
            current = {"http": p, "https": p} if p else None
        else:
            current = pool.get_proxies()
        proxy_url = current.get("http") if current else None
        try:
            resp = requests.request(method, url, proxies=current, **kwargs)
            if proxy_url:
                pool.report_success(proxy_url)
            return resp
        except Exception as exc:  # 传输层异常：换代理重试
            last_exc = exc
            if proxy_url:
                pool.report_failure(proxy_url)
            continue
    # 兜底：直连再试一次
    try:
        return requests.request(method, url, **kwargs)
    except Exception as exc:
        raise last_exc or exc
