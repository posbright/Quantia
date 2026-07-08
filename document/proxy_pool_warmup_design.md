# 代理池预热守护设计决策记录（proxy_warmer）

> 记录时间：2026-07-02　状态：已落地（代码）　适用：`quantia/core/singleton_proxy.py`、`quantia/job/proxy_warmer_daemon.py`、`quantia/bin/run_proxy_warmer.sh`、`supervisor/supervisord.conf`

记录“代理池预热”优化的**问题背景、探讨过的方案、最终选择及理由**，方便日后回顾。

---

## 1. 起因

生产 master（`115.29.213.22`）`hourly.log` 频繁出现：

```
WARNING:root:东方财富数据获取失败：(Connection aborted, RemoteDisconnected)，切换下一个数据源
```

诉求：hourly 是否用了代理池？为何频繁切换数据源？能否减少切换、提升东财成功率？

初步结论：hourly 采集经 `eastmoney_fetcher` 层**确实**用到代理池，但在短命 cron 进程里形同虚设。该 WARNING **不是 bug**——是正常降级记录：东财失败后切腾讯/新浪，作业最终仍完成。要优化的是“减少切换”。

---

## 2. 根因：短命进程 + daemon 线程被杀 + 磁盘缓存养不起来（恶性循环）

- hourly/workdayly 是 cron 每次新起、约 1 分钟即退出的短命进程。
- 代理池 `singleton_proxy` 的抓取/验证/HTTPS 升级/落盘**全在 daemon 后台线程**，主进程退出即被杀。
- 新抓代理常还没验证/落盘进程就结束，`cache/proxy_cache.json` 一直空/陈旧。
- 下个进程读空缓存，`get_proxies()` 返回 None，全程直连，东财对本机 IP 限流，重试失败，WARNING + 切换备用源（作业仍成功）。
- 循环往复，**免费代理永远养不起来**。

---

## 3. 三个决定成败的技术事实

### 3.1 接口协议不同，代理要求不同

| 数据 | 爬虫 | 端点 | 代理要求 |
| --- | --- | --- | --- |
| 股票实时 | `crawling/stock_hist_em.py` | `https://push2` | 必须 https_ok 代理（稀缺） |
| ETF 实时 | `crawling/fund_etf_em.py` | `http://push2` | HTTP-only 代理即可 |
| 指数实时 | `crawling/stock_index_em.py` | `http://push2` | HTTP-only 代理即可 |

预热对 HTTP 的 ETF/指数收益明显；对 HTTPS 股票接口收益有限（免费 https_ok 稀缺、分钟级失效）。

### 3.2 磁盘缓存是唯一跨进程载体

cron 短进程内存不共享，`cache/proxy_cache.json` 是唯一通道。`__init__` 的 `_load_disk_cache()` 把缓存代理直接放进 `_pool`（fail_count=0），只要缓存有未过期代理，进程启动后首次 `get_proxies()` 即命中。**预热本质=让一个活得够久的进程把缓存持续养好。**

### 3.3（关键）https_ok 字段是“易失”的

追踪全部 https_ok 引用发现多个写入点会覆盖它：

- `_revalidate_existing(http_only=True)` 经 `_validate_one` 返回 (http_ok, False)：每次进程启动 Phase1 把已有代理 https_ok 重置为 False。
- `_revalidate_existing(http_only=False)`（`_refresh_cycle` 每 600s）：用真实 HTTPS 结果覆盖。
- `_upgrade_https_in_background`：只把成功的补回 True，失败不标记。

HTTPS 结果本来每 600s 就完整刷新一次。此事实直接影响 §6 的 A/B 抉择。

---

## 4. 实施路径选择：为何选“常驻预热守护”（路径①）

| 路径 | 机制 | 可靠性 | 成本 | 贴合免费代理短命 |
| --- | --- | --- | --- | --- |
| ① 常驻守护（已选） | supervisor 常驻进程持有单例，后台线程持续养池+落盘；cron 读缓存复用 | 高 | 零 | 是 |
| ② 独立预热 job + 高频 cron | 阻塞等验证+落盘后退出，每 10-15min | 中 | 零 | 整点可能已过期 |
| ③ config/proxy.txt 稳定代理 | 手动配置，`_load_manual_proxies` 同步加载、永不删除、启动即用 | 最高 | 需付费/自建 | N/A |

选①理由：零成本、复用已有 supervisor、契合免费代理需持续养的特性。③最可靠但需稳定代理资源，作为后续根治保留（§7）。

---

## 5. 健壮性修复：磁盘缓存原子写

`_save_disk_cache()` 原用 open(w) 截断 + json.dump 直写（非原子）。守护高频落盘与 cron 读缓存并发时，可能读到“写一半”的损坏 JSON，`_load_disk_cache` 静默返回 0（空缓存），退回直连。

修复：改**原子写**——写 xxx.<pid>.tmp 再 os.replace() 原子替换，finally 清理残留 tmp。

---

## 6. 方案 A vs 方案 B：为何选 A（降频）而非治根

守护最初每轮（180s）都调 `ensure_https_upgraded()`，它对所有未标记 https_ok 的代理重做 HTTPS 验证。由 §3.3，验证失败的 http-only 代理永远 https_ok=False，**每轮反复空验**（重复开销，非 bug）。

- 方案 A（降频）：HTTPS 升级降到每 600s 一次（时间戳控制），只改 proxy_warmer_daemon.py。
- 方案 B（时间戳治根）：给代理加 https_checked_at，跳过近期测过的；需改 `_upgrade_https_in_background`/`_validate_one`/`_revalidate_existing`/磁盘缓存。

| 维度 | 方案 A | 方案 B |
| --- | --- | --- |
| 改动 | 仅守护脚本 | 代理池核心全链路 |
| 真正消除空验 | 消除 180s 空验大部分 | 还需改 600s 刷新才算根治，否则被抵消 |
| 回归风险 | 极低 | 中高（失效代理可能被误判可用） |

**选 A 理由**：① 空验实际开销本就很小；② B 治根要动 600s 刷新，影响面大、性价比低，且 HTTPS 本就每 600s 刷新，B 收益被抵消；③ 真正的“根”是免费 https_ok 代理稀缺短命，优化验证频率改变不了，根治靠 §7 稳定代理。A 零风险压低额外开销，不动核心链路。

落地：WARMER_HTTPS_INTERVAL（默认 600，QUANTIA_PROXY_WARMER_HTTPS_INTERVAL 可配）+ time.monotonic() 时间戳 last_https_upgrade 控频；persist() 仍每轮做。

---

## 7. 现实预期与根治建议

- 免费代理对 HTTPS 股票接口提升有限，对 HTTP 的 ETF/指数受益明显。
- 根治源切换：config/proxy.txt 配少量稳定代理（付费/自建，最好支持 HTTPS）。manual=True 永不删除、启动即用；3-5 个即可显著减少切换。此为路径③，下一步可选增强。

---

## 8. 最终落地清单

| 文件 | 变更 |
| --- | --- |
| quantia/core/singleton_proxy.py | 新增公开 ensure_https_upgraded() / persist()；_save_disk_cache() 改原子写 |
| quantia/job/proxy_warmer_daemon.py | 新建常驻守护：持有单例保活，HTTPS 升级降频（600s）+ 每轮落盘 + 打点，信号优雅退出 |
| quantia/bin/run_proxy_warmer.sh | 启动脚本 |
| supervisor/supervisord.conf | 新增 [program:proxy_warmer]（autorestart、独立 log） |

### 部署

```
chmod +x /data/Quantia/quantia/bin/run_proxy_warmer.sh
supervisorctl reread && supervisorctl update
supervisorctl start proxy_warmer
supervisorctl tail -f proxy_warmer
head -c 400 /data/Quantia/quantia/cache/proxy_cache.json
```

### 参数

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| QUANTIA_PROXY_WARMER_INTERVAL | 180 | 守护主循环间隔（落盘 + 打点） |
| QUANTIA_PROXY_WARMER_HTTPS_INTERVAL | 600 | HTTPS 升级间隔（降频避免空验） |
| 其余 QUANTIA_PROXY_* | 见代码 | 沿用代理池既有配置 |
