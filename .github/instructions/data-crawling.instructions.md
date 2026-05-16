---
description: "Use when editing data crawlers (quantia/core/crawling/), the multi-source scheduler (quantia/core/stockfetch.py), or fetch jobs (quantia/job/fetch_*). Covers source priority, health tracking, retry/backoff, and adding new crawlers."
applyTo: "quantia/core/crawling/**/*.py, quantia/core/stockfetch.py, quantia/job/fetch_*.py"
---
# 数据爬虫 / 多源采集规范

## 三级数据源优先级
所有行情类端点的默认优先级：
1. **东方财富 (EastMoney)** — 主源，数据最全
2. **腾讯财经 (Tencent)** — 备用，覆盖 400–600 资产
3. **新浪财经 (Sina)** — 兜底，部分需代理

调度入口：[quantia/core/stockfetch.py](../../quantia/core/stockfetch.py)，`_sort_sources_by_health()` 按健康度动态排序。

## 健康追踪与降级
- `_source_fail_counts`：连续失败计数
- `SOURCE_FAIL_THRESHOLD=5`（env）：达到阈值后降级该源
- `SOURCE_COOLDOWN_SECONDS=300`（base）→ 每次降级翻倍 → `SOURCE_MAX_COOLDOWN_SECONDS=3600`
- 降级源仍可重试但排在最后

## 重试与退避
- `DATA_SOURCE_MAX_RETRIES=2`（env），基础间隔 `DATA_SOURCE_RETRY_INTERVAL=90s`
- 指数退避：`base_delay * 2^retry_count + 10–30% jitter`
- 同源错误日志聚合：60 秒内同源重复失败只记一次（`_LOG_AGG_INTERVAL`）

## 爬虫模块目录
[quantia/core/crawling/](../../quantia/core/crawling/) 按 `<资产类型>_<源>` 命名：
- EastMoney：`stock_hist_em`、`stock_index_em`、`fund_etf_em`、`stock_lhb_em`（龙虎榜）等
- Tencent：`stock_hist_tencent`、`index_tencent`、`etf_tencent` 等
- Sina：`stock_hist_sina`、`stock_sina`、`index_sina`、`stock_fund_sina` 等
- 通用：`trade_date_hist`、`stock_selection`、`stock_chip_race` 等

## 添加新爬虫
1. 在 `quantia/core/crawling/` 新建模块，函数签名保持与同类爬虫一致。
2. 在 `stockfetch.py` 的源列表中注册，遵守优先级顺序。
3. 仅在 Fetch 管道中调用——**禁止**在 handler / analysis job 中直接调用爬虫（[AGENTS.md](../../AGENTS.md) 规则 1）。
4. 补充测试时 mock 网络调用，不要在 CI 中真实请求外部 API。

## 配置环境变量
| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DATA_SOURCE_MAX_RETRIES` | 2 | 最大重试次数 |
| `DATA_SOURCE_RETRY_INTERVAL` | 90 | 基础重试间隔（秒） |
| `DATA_SOURCE_FAIL_THRESHOLD` | 5 | 连续失败降级阈值 |
| `DATA_SOURCE_COOLDOWN_SECONDS` | 300 | 降级冷却基础值（秒） |
| `DATA_SOURCE_MAX_COOLDOWN` | 3600 | 最大冷却时间（秒） |
| `QUANTIA_CRAWL_WORKERS` | 5 | 并发爬虫线程数 |
| `QUANTIA_BATCH_SIZE` | 50 | 批量请求大小 |
| `QUANTIA_LOCAL_MODE` | 0 | =1 时提高并发、缩短延迟 |
