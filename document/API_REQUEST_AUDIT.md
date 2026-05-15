# External API Request Patterns — Comprehensive Audit

> Generated: 2026-03-18
> Scope: `quantia/` Python codebase
> Purpose: Document every external HTTP request, its throttling, retry, caching, and concurrency model

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Data Source 1: EastMoney / 东方财富](#2-eastmoney)
3. [Data Source 2: Tencent / 腾讯财经](#3-tencent)
4. [Data Source 3: Sina / 新浪财经](#4-sina)
5. [Data Source 4: TongHuaShun / 同花顺](#5-tonghuashun)
6. [Data Source 5: TongDaXin / 通达信](#6-tongdaxin)
7. [Data Source 6: Proxy Pool Sources](#7-proxy-pool)
8. [Orchestration: stockfetch.py](#8-orchestration)
9. [update_all_caches — Deep Dive](#9-update-all-caches)
10. [Environment Variable Reference](#10-env-vars)
11. [Total Request Count Estimation](#11-request-count)

---

## 1. Executive Summary

| Metric | Value |
|---|---|
| **External data sources** | 6 (EastMoney, Tencent, Sina, TongHuaShun, TongDaXin, Proxy sources) |
| **Crawling modules** | 20 files in `quantia/core/crawling/` |
| **Unique API endpoints** | ~25 |
| **Total daily API calls (typical ~5000 stocks)** | **~5,500–11,000** (see §11) |
| **Concurrency model** | ThreadPoolExecutor (2–12 workers depending on mode) |
| **Rate limiting layers** | 5-layer throttling in `update_all_caches` |
| **Retry mechanism** | Exponential backoff with jitter via `_retry_sleep` |
| **Caching** | Incremental pickle cache per stock + `.meta` skip optimization |

---

## 2. EastMoney / 东方财富 {#2-eastmoney}

Central HTTP client: [`quantia/core/eastmoney_fetcher.py`](quantia/core/eastmoney_fetcher.py)

### 2.1 HTTP Client (`eastmoney_fetcher.make_request`)

| Property | Value | Line |
|---|---|---|
| **File** | [eastmoney_fetcher.py](quantia/core/eastmoney_fetcher.py#L80-L148) | |
| **Thread safety** | `threading.local()` — each thread gets its own `requests.Session` | L31, L82 |
| **Default retry** | `QUANTIA_EM_RETRY` env var, default **3** | L84 |
| **Default timeout** | `QUANTIA_EM_TIMEOUT` env var, default **30s** | L85 |
| **Proxy timeout** | Capped at **15s** when using proxy (`min(timeout, 15)`) | L106 |
| **Last retry** | Forces direct connection (no proxy) | L101–103 |
| **Retry delay (connection error)** | `random.uniform(1, 3)` seconds | L131 |
| **Retry delay (other error)** | `random.uniform(2, 5) * (i + 1)` seconds (escalating) | L136 |
| **Proxy feedback** | `proxy_pool.report_success/failure(proxy_url)` on every request | L112, L117 |

### 2.2 Realtime Spot Quotes — `stock_zh_a_spot_em()`

| Property | Value |
|---|---|
| **File** | [stock_hist_em.py](quantia/core/crawling/stock_hist_em.py#L22-L150) |
| **Function** | `stock_zh_a_spot_em()` |
| **URL** | `https://push2.eastmoney.com/api/qt/clist/get` |
| **Data** | All A-share realtime quotes (~5000 stocks) |
| **Page size** | 5000 per page |
| **Pagination delay** | `time.sleep(random.uniform(2, 3))` between pages |
| **Total calls** | **1–2** (5000 stocks / 5000 per page = 1 page typical) |
| **Retry** | Via `fetcher.make_request` (3 retries) |
| **Caching** | None (realtime data) |

### 2.3 Historical K-Line — `stock_zh_a_hist()`

| Property | Value |
|---|---|
| **File** | [stock_hist_em.py](quantia/core/crawling/stock_hist_em.py#L261-L338) |
| **Function** | `stock_zh_a_hist(symbol, period, start_date, end_date, adjust)` |
| **URL** | `http://push2his.eastmoney.com/api/qt/stock/kline/get` |
| **Data** | Single stock daily/weekly/monthly K-line |
| **Pre-request delay** | `time.sleep(random.uniform(0.2, 0.5))` |
| **Total calls** | **1 per stock** (single request, all history returned) |
| **Retry** | Via `fetcher.make_request` (3 retries) |
| **Caching** | Incremental pickle cache in `cache/hist/{code[:3]}/{code}qfq.gzip.pickle` |

### 2.4 Intraday K-Line — `stock_zh_a_hist_min_em()`

| Property | Value |
|---|---|
| **File** | [stock_hist_em.py](quantia/core/crawling/stock_hist_em.py#L340-L460) |
| **URLs** | `https://push2his.eastmoney.com/api/qt/stock/trends2/get` (1-min), `http://push2his.eastmoney.com/api/qt/stock/kline/get` (5/15/30/60-min) |
| **Data** | Intraday minute-level K-line |
| **Delay** | None (on-demand, not batch) |
| **Caching** | None |

### 2.5 Pre-market Intraday — `stock_zh_a_hist_pre_min_em()`

| Property | Value |
|---|---|
| **File** | [stock_hist_em.py](quantia/core/crawling/stock_hist_em.py#L462-L520) |
| **URL** | `https://push2.eastmoney.com/api/qt/stock/trends2/get` |
| **Data** | Pre-market + intraday minute data |

### 2.6 ETF Spot Quotes — `fund_etf_spot_em()`

| Property | Value |
|---|---|
| **File** | [fund_etf_em.py](quantia/core/crawling/fund_etf_em.py#L22-L120) |
| **URL** | `http://push2.eastmoney.com/api/qt/clist/get` |
| **Data** | All ETF realtime quotes |
| **Page size** | 50 per page |
| **Pagination delay** | `time.sleep(random.uniform(2, 3))` |
| **Total calls** | ~15 pages (750+ ETFs / 50 per page) |

### 2.7 ETF Code-ID Map — `_fund_etf_code_id_map_em()`

| Property | Value |
|---|---|
| **File** | [fund_etf_em.py](quantia/core/crawling/fund_etf_em.py#L122-L145) |
| **URL** | `http://push2.eastmoney.com/api/qt/clist/get` |
| **Data** | ETF code → market ID mapping |
| **Caching** | `@lru_cache()` — cached in memory for process lifetime |
| **Total calls** | **1** per process |

### 2.8 ETF Historical K-Line — `fund_etf_hist_em()`

| Property | Value |
|---|---|
| **File** | [fund_etf_em.py](quantia/core/crawling/fund_etf_em.py#L147-L250) |
| **URL** | `http://push2his.eastmoney.com/api/qt/stock/kline/get` |
| **Data** | Single ETF historical K-line |
| **Total calls** | 1 per ETF |

### 2.9 Individual Fund Flow Ranking — `stock_individual_fund_flow_rank()`

| Property | Value |
|---|---|
| **File** | [stock_fund_em.py](quantia/core/crawling/stock_fund_em.py#L48-L200) |
| **URLs** | `https://push2.eastmoney.com/api/qt/clist/get`, `http://push2.eastmoney.com/api/qt/clist/get` |
| **Data** | A-share fund flow ranking (今日/3日/5日/10日) |
| **Page size** | 100 per page |
| **Internal retry** | `_individual_fund_flow_fetch_page`: 3 attempts × 2 URLs = 6 total tries per page |
| **Retry delay** | `time.sleep(random.uniform(2, 4) * attempt)` |
| **Pagination delay** | `time.sleep(random.uniform(1, 1.5))` |
| **Total calls** | ~50 pages (5000 stocks / 100 per page) per indicator |

### 2.10 Sector Fund Flow Ranking — `stock_sector_fund_flow_rank()`

| Property | Value |
|---|---|
| **File** | [stock_fund_em.py](quantia/core/crawling/stock_fund_em.py#L300-L500) |
| **URL** | `https://push2.eastmoney.com/api/qt/clist/get` |
| **Data** | Sector/concept/region fund flow ranking |
| **Internal retry** | `_sector_fund_flow_fetch_page`: 3 attempts × 2 URLs |
| **Pagination delay** | `time.sleep(random.uniform(1, 1.5))` |

### 2.11 LHB Detail — `stock_lhb_detail_em()`

| Property | Value |
|---|---|
| **File** | [stock_lhb_em.py](quantia/core/crawling/stock_lhb_em.py#L35-L135) |
| **URL** | `https://datacenter-web.eastmoney.com/api/data/v1/get` |
| **Report** | `RPT_DAILYBILLBOARD_DETAILSNEW` |
| **Data** | Dragon-Tiger Board details (date range) |
| **Page size** | 5000 |
| **Pagination delay** | `time.sleep(random.uniform(1, 1.5))` |

### 2.12 LHB Institutional Trading Stats — `stock_lhb_jgmmtj_em()`

| Property | Value |
|---|---|
| **File** | [stock_lhb_em.py](quantia/core/crawling/stock_lhb_em.py#L258-L340) |
| **URL** | `https://datacenter-web.eastmoney.com/api/data/v1/get` |
| **Report** | `RPT_ORGANIZATION_TRADE_DETAILS` |
| **Page size** | 5000 |

### 2.13 LHB Stock Statistics — various `stock_lhb_*_em()` functions

| Function | Report Name | Pagination delay |
|---|---|---|
| `stock_lhb_stock_statistic_em` | `RPT_BILLBOARD_TRADEALL` | N/A (single page) |
| `stock_lhb_jgstatistic_em` | `RPT_ORGANIZATION_SEATNEW` | `random.uniform(1, 1.5)` |
| `stock_lhb_hyyyb_em` | `RPT_OPERATEDEPT_ACTIVE` | `random.uniform(1, 1.5)` |
| `stock_lhb_yybph_em` | `RPT_RATEDEPT_RETURNT_RANKING` | `random.uniform(1, 1.5)` |
| `stock_lhb_traderstatistic_em` | `RPT_OPERATEDEPT_LIST_STATISTICS` | `random.uniform(1, 1.5)` |
| `stock_lhb_stock_detail_date_em` | `RPT_LHB_BOARDDATE` | N/A |
| `stock_lhb_stock_detail_em` | `RPT_BILLBOARD_DAILYDETAILSBUY/SELL` | N/A |

### 2.14 Block Trade — `stock_dzjy_mrtj()` etc.

| Property | Value |
|---|---|
| **File** | [stock_dzjy_em.py](quantia/core/crawling/stock_dzjy_em.py) |
| **URL** | `https://datacenter-web.eastmoney.com/api/data/v1/get` |
| **Reports** | `PRT_BLOCKTRADE_MARKET_STA`, `RPT_DATA_BLOCKTRADE`, `RPT_BLOCKTRADE_STA` |
| **Pagination delay** | `time.sleep(random.uniform(1, 1.5))` |

### 2.15 Dividend/Bonus — `stock_fhps_em()`

| Property | Value |
|---|---|
| **File** | [stock_fhps_em.py](quantia/core/crawling/stock_fhps_em.py) |
| **URL** | `https://datacenter-web.eastmoney.com/api/data/v1/get` |
| **Report** | `RPT_SHAREBONUS_DET` |
| **Page size** | 500 |
| **Pagination delay** | `time.sleep(random.uniform(1, 1.5))` |

### 2.16 Stock Selection — `stock_selection()`

| Property | Value |
|---|---|
| **File** | [stock_selection.py](quantia/core/crawling/stock_selection.py) |
| **URL** | `https://data.eastmoney.com/dataapi/xuangu/list` |
| **Data** | Stock screener data (fundamentals) |
| **Page size** | 500 per page (~10 pages for all A-shares) |
| **Per-page delay** | `time.sleep(random.uniform(0.5, 1.5))` |
| **Per-page retry** | 3 attempts with `time.sleep(random.uniform(2, 4))` |
| **First page retry** | 3 attempts with `time.sleep(random.uniform(2, 5))` |

### 2.17 CPBD / Capital Flow — `stock_cpbd_em()`, `stock_zjlx_em()`

| Property | Value |
|---|---|
| **File** | [stock_cpbd.py](quantia/core/crawling/stock_cpbd.py) |
| **URLs** | `https://emweb.securities.eastmoney.com/PC_HSF10/OperationsRequired/PageAjax`, `https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get` |
| **Data** | Per-stock fundamentals summary, daily capital flow |
| **Total calls** | 1 per stock per function |

### 2.18 Index Spot Quotes — `stock_index_spot_em()`

| Property | Value |
|---|---|
| **File** | [stock_index_em.py](quantia/core/crawling/stock_index_em.py#L36-L115) |
| **URL** | `http://push2.eastmoney.com/api/qt/clist/get` |
| **Data** | All SH/SZ index realtime quotes |
| **Page size** | 50 |
| **Pagination delay** | `time.sleep(random.uniform(2, 3))` |

### 2.19 Index Historical K-Line — `stock_index_hist_em()`

| Property | Value |
|---|---|
| **File** | [stock_index_em.py](quantia/core/crawling/stock_index_em.py#L128-L193) |
| **URL** | `http://push2his.eastmoney.com/api/qt/stock/kline/get` |
| **Data** | Single index historical K-line |
| **Pre-request delay** | `time.sleep(random.uniform(0.2, 0.5))` |

---

## 3. Tencent / 腾讯财经 {#3-tencent}

### 3.1 Stock Spot Quotes — `stock_zh_a_spot_tencent()`

| Property | Value |
|---|---|
| **File** | [stock_tencent.py](quantia/core/crawling/stock_tencent.py) |
| **Function** | `stock_zh_a_spot_tencent()` → `_fetch_batch()` |
| **URL** | `http://qt.gtimg.cn/q={codes}` |
| **Data** | A-share realtime quotes |
| **Batch size** | 100 codes per request |
| **Workers** | `QUANTIA_CRAWL_WORKERS` env var, default **5** threads |
| **Rate limiting** | Every 10th batch: `time.sleep(random.uniform(0.5, 1))` |
| **Total batches** | ~110 (11,000 candidate codes / 100 per batch) |
| **Total calls** | ~110, but most return empty (only ~5000 active stocks) |
| **Retry** | None (single attempt per batch) |
| **Caching** | None |

### 3.2 ETF Spot Quotes — `fund_etf_spot_tencent()`

| Property | Value |
|---|---|
| **File** | [etf_tencent.py](quantia/core/crawling/etf_tencent.py) |
| **URL** | `http://qt.gtimg.cn/q={codes}` |
| **Batch size** | 100 codes per request |
| **Workers** | `QUANTIA_CRAWL_WORKERS`, default **5** |
| **Rate limiting** | Every 10th batch: `time.sleep(random.uniform(0.5, 1))` |
| **Total batches** | ~230 (23,000 candidate ETF codes / 100) |

### 3.3 Stock Historical K-Line — `stock_zh_a_hist_tencent()`

| Property | Value |
|---|---|
| **File** | [stock_hist_tencent.py](quantia/core/crawling/stock_hist_tencent.py) |
| **URL** | `https://web.ifzq.gtimg.cn/appstock/app/fqkline/get` |
| **Data** | Single stock daily K-line history |
| **Max per request** | 300 records |
| **Batching** | Splits time range into ~428 natural-day chunks when >300 trading days needed |
| **Per-batch delay** | `time.sleep(random.uniform(0.3, 0.8))` (single batch), `time.sleep(random.uniform(0.5, 1.5))` (multi-batch) |
| **Safety limit** | Max 50 batches (~35 years) |
| **Total calls** | 1–8 per stock (10 years ≈ 2500 trading days / 300 = ~8 batches) |
| **Retry** | None (single attempt per batch) |

---

## 4. Sina / 新浪财经 {#4-sina}

### 4.1 Stock Spot Quotes — `stock_zh_a_spot_sina()`

| Property | Value |
|---|---|
| **File** | [stock_sina.py](quantia/core/crawling/stock_sina.py) |
| **URL** | `http://hq.sinajs.cn/list={codes}` |
| **Data** | A-share realtime quotes |
| **Batch size** | 100 codes per request |
| **Workers** | `QUANTIA_CRAWL_WORKERS`, default **5** |
| **Rate limiting** | Every 10th batch: `time.sleep(random.uniform(0.5, 1))` |
| **Total batches** | ~110 |
| **Retry** | None |

### 4.2 ETF Spot Quotes — `fund_etf_spot_sina()`

| Property | Value |
|---|---|
| **File** | [etf_sina.py](quantia/core/crawling/etf_sina.py) |
| **URL** | `http://hq.sinajs.cn/list={codes}` |
| **Identical pattern** to stock_sina.py (100 per batch, 5 workers, every-10th-batch pause) |

### 4.3 Stock Historical K-Line — `stock_zh_a_hist_sina()`

| Property | Value |
|---|---|
| **File** | [stock_hist_sina.py](quantia/core/crawling/stock_hist_sina.py#L68-L195) |
| **URL** | `https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData` |
| **Data** | Single stock daily K-line |
| **Pre-request delay** | **`time.sleep(random.uniform(3, 6))`** (most aggressive throttling — prevents 456 rate limit) |
| **Max datalen** | 5000 records per request |
| **Total calls** | **1 per stock** |
| **Retry** | None |

### 4.4 Stock Historical K-Line V2 — `stock_zh_a_hist_sina_v2()`

| Property | Value |
|---|---|
| **File** | [stock_hist_sina.py](quantia/core/crawling/stock_hist_sina.py#L230-L330) |
| **URL** | `https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData` |
| **Pre-request delay** | **`time.sleep(random.uniform(3, 6))`** |
| **Backup function** | Alternate endpoint, same pattern |

### 4.5 Individual Fund Flow — `stock_individual_fund_flow_rank_sina()`

| Property | Value |
|---|---|
| **File** | [stock_fund_sina.py](quantia/core/crawling/stock_fund_sina.py#L22-L100) |
| **URL** | `http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/MoneyFlow.ssl_bkzj_ssggzj` |
| **Data** | Per-stock fund flow ranking (today only, no 3/5/10 day breakdown) |
| **Page size** | 5000 (single page) |
| **Total calls** | **1** |
| **Proxy** | Uses `proxys().get_proxies()` |

### 4.6 Sector Fund Flow — `stock_sector_fund_flow_rank_sina()`

| Property | Value |
|---|---|
| **File** | [stock_fund_sina.py](quantia/core/crawling/stock_fund_sina.py#L130-L210) |
| **URL** | `http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/MoneyFlow.ssl_bkzj_bk` |
| **Data** | Sector/concept fund flow (today only) |
| **Total calls** | **1** |
| **Proxy** | Uses `proxys().get_proxies()` |

### 4.7 LHB Daily Detail — `stock_lhb_detail_daily_sina()`

| Property | Value |
|---|---|
| **File** | [stock_lhb_sina.py](quantia/core/crawling/stock_lhb_sina.py#L44-L90) |
| **URL** | `https://vip.stock.finance.sina.com.cn/q/go.php/vInvestConsult/kind/lhb/index.phtml` |
| **Data** | Dragon-Tiger board daily detail |
| **Total calls** | **1** |
| **Proxy** | Via `_sina_request()` → `proxys().get_proxies()` |

### 4.8 LHB Stock Statistics — `stock_lhb_ggtj_sina()`

| Property | Value |
|---|---|
| **File** | [stock_lhb_sina.py](quantia/core/crawling/stock_lhb_sina.py#L125-L165) |
| **URL** | `https://vip.stock.finance.sina.com.cn/q/go.php/vLHBData/kind/ggtj/index.phtml` |
| **Data** | LHB individual stock statistics |
| **Pagination** | Dynamic (finds last page first via `_find_last_page`) |
| **Total calls** | 2-20+ (page discovery + data pages) |

### 4.9 Trade Date Calendar — `tool_trade_date_hist_sina()`

| Property | Value |
|---|---|
| **File** | [trade_date_hist.py](quantia/core/crawling/trade_date_hist.py#L350-L388) |
| **URL** | `https://finance.sina.com.cn/realstock/company/klc_td_sh.txt` |
| **Data** | Historical trading calendar (encrypted JS) |
| **Total calls** | **1** |
| **SSL retry** | `_request_with_ssl_retry`: proxy → direct → direct+no_verify, 2 retries each |
| **Proxy** | Uses `proxys().get_proxies()` |

---

## 5. TongHuaShun / 同花顺 {#5-tonghuashun}

### 5.1 Limit-Up Reason — `stock_limitup_reason()`

| Property | Value |
|---|---|
| **File** | [stock_limitup_reason.py](quantia/core/crawling/stock_limitup_reason.py#L18-L75) |
| **URL** | `http://zx.10jqka.com.cn/event/api/getharden/date/{date}/orderby/date/orderway/desc/charset/GBK/` |
| **Data** | Daily limit-up stock reasons |
| **Total calls** | **1** |
| **Proxy** | Uses `proxys().get_proxies()` |

### 5.2 Limit-Up Detail — `stock_limitup_detail()`

| Property | Value |
|---|---|
| **File** | [stock_limitup_reason.py](quantia/core/crawling/stock_limitup_reason.py#L100-L130) |
| **URL** | `http://zx.10jqka.com.cn/event/harden/stockreason/id/{ID}` |
| **Data** | Detailed reason for each limit-up stock |
| **Total calls** | **1 per limit-up stock** (typically 30-80/day) |
| **Timeout** | 15s |
| **Proxy** | Uses `proxys().get_proxies()` |

---

## 6. TongDaXin / 通达信 {#6-tongdaxin}

### 6.1 Chip Race Open/Close — `stock_chip_race_open()`, `stock_chip_race_end()`

| Property | Value |
|---|---|
| **File** | [stock_chip_race.py](quantia/core/crawling/stock_chip_race.py) |
| **URL** | `http://excalc.icfqs.com:7616/TQLEX?Entry=HQServ.hq_nlp` |
| **Method** | **POST** (JSON body) |
| **Data** | Pre-market auction chip race (early/late) |
| **Auth** | Static token `6679f5cadca97d68245a086793fc1bfc0a50b487487c812f` |
| **Total calls** | **1** per function |
| **Proxy** | Uses `proxys().get_proxies()` |
| **Timeout** | 30s |

---

## 7. Proxy Pool Sources {#7-proxy-pool}

**File**: [singleton_proxy.py](quantia/core/singleton_proxy.py)

### 7.1 Proxy Source Fetchers

The proxy pool fetches free proxies from **10+ external sources**, organized in 2 tiers:

| Tier | Source | URL | Method |
|---|---|---|---|
| T1 | geonode.com | `https://proxylist.geonode.com/api/proxy-list?...` | GET JSON |
| T1 | fate0 | `http://proxylist.fate0.com/proxy.list` | GET text |
| T1 | proxifly (GitHub) | `https://raw.githubusercontent.com/proxifly/free-proxy-list/main/...` | GET text |
| T1 | TheSpeedX (GitHub) | `https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt` | GET text (limit 500) |
| T1 | monosans (GitHub) | `https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt` | GET text (limit 500) |
| T1 | clarketm (GitHub) | `https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt` | GET text (limit 300) |
| T2 | sunny9577 (GitHub) | `https://raw.githubusercontent.com/sunny9577/proxy-scraper/...` | GET text |
| T2 | MuRongPIG (GitHub) | `https://raw.githubusercontent.com/MuRongPIG/Proxy-Master/...` | GET text |
| T2 | rdavydov (GitHub) | `https://raw.githubusercontent.com/rdavydov/proxy-list/...` | GET text |

### 7.2 Proxy Validation

| Property | Value |
|---|---|
| **Validation URL (HTTP)** | `http://datacenter.eastmoney.com/api/data/get` (`QUANTIA_PROXY_VALIDATE_URL`) |
| **Validation URL (HTTPS)** | `https://push2.eastmoney.com/api/qt/clist/get` |
| **Validation timeout** | **5s** (`QUANTIA_PROXY_VALIDATE_TIMEOUT`) |
| **Validation workers** | **50** concurrent threads (`QUANTIA_PROXY_FETCH_WORKERS`) |
| **Init batch size** | **200** candidates (`QUANTIA_PROXY_INIT_BATCH_SIZE`) |
| **Max fail count** | **3** before auto-removal (`QUANTIA_PROXY_MAX_FAIL_COUNT`) |
| **Refresh interval** | **600s** (10 min) (`QUANTIA_PROXY_REFRESH_INTERVAL`) |
| **Disk cache** | `cache/proxy_cache.json`, max age **86400s** (24h) |
| **Target pool size** | **15** (`QUANTIA_PROXY_TARGET_POOL_SIZE`) |

### 7.3 Proxy Selection Strategy

| Pool Size | Direct Connection Probability |
|---|---|
| ≥ 10 | 30% |
| 3–9 | 60% |
| < 3 | 80% |

---

## 8. Orchestration: stockfetch.py {#8-orchestration}

**File**: [stockfetch.py](quantia/core/stockfetch.py) (2081 lines)

### 8.1 Multi-Source Fallback Pattern

All major data types use the same pattern: **try source A → fail → try source B → fail → try source C**:

| Function | Priority 1 | Priority 2 | Priority 3 |
|---|---|---|---|
| `fetch_stocks()` | 东方财富 | 腾讯财经 | 新浪财经 |
| `fetch_etfs()` | 东方财富 | 腾讯财经 | 新浪财经 |
| `fetch_stocks_fund_flow()` | 东方财富 | 新浪财经 | — |
| `fetch_stocks_sector_fund_flow()` | 东方财富 | 新浪财经 | — |
| `fetch_stock_lhb_data()` | 东方财富 | 新浪财经 | — |
| `_fetch_from_sources()` (K-line) | 东方财富 | 腾讯财经 | 新浪财经 |

### 8.2 Data Source Health Tracking System

**Location**: [stockfetch.py](quantia/core/stockfetch.py#L49-L123)

| Component | Description |
|---|---|
| `_report_source_failure(name)` | Increments fail count; triggers degradation at threshold |
| `_report_source_success(name)` | Resets fail count, clears cooldown, resets progressive backoff |
| `_is_source_degraded(name)` | Checks if source is in cooldown period |
| `_sort_sources_by_health(sources)` | Moves degraded sources to end of priority list |

| Config | Env Var | Default |
|---|---|---|
| Fail threshold | `DATA_SOURCE_FAIL_THRESHOLD` | **5** consecutive failures |
| Base cooldown | `DATA_SOURCE_COOLDOWN_SECONDS` | **300s** (5 min) |
| Max cooldown | `DATA_SOURCE_MAX_COOLDOWN` | **3600s** (1 hour) |
| Progressive backoff | `300s → 600s → 1200s → ... → 3600s` (doubles each degradation) |

### 8.3 `_retry_sleep()` Function

**Location**: [stockfetch.py](quantia/core/stockfetch.py#L176-L187)

```python
def _retry_sleep(retry_count, base_interval=None):
    if base_interval is None:
        base_interval = DATA_SOURCE_RETRY_INTERVAL  # default 90s
    base_delay = base_interval * (2 ** retry_count)
    jitter = random.uniform(base_delay * 0.1, base_delay * 0.3)
    delay = base_delay + jitter
    time.sleep(delay)
```

| Retry # | Base Delay | Jitter Range | Total Delay |
|---|---|---|---|
| 0 | 90s | 9–27s | **99–117s** |
| 1 | 180s | 18–54s | **198–234s** |

### 8.4 `_fetch_from_sources()` — Per-Stock K-Line Fetch

**Location**: [stockfetch.py](quantia/core/stockfetch.py#L1228-L1285)

For each stock's K-line data:
1. Try sources in health-sorted order (EM → Tencent → Sina)
2. Per source: up to `DATA_SOURCE_MAX_RETRIES` (default **2**) retries
3. Between retries: `_retry_sleep(retry_count)` (90s exponential backoff)
4. Connection-level errors (503/504/SSL/disconnect): **immediately skip to next source** (no retry)
5. Empty data response: treated as **non-error**, returns `None` immediately
6. Success: calls `_report_source_success()` / Failure: calls `_report_source_failure()`

### 8.5 Log Aggregation

**Location**: [stockfetch.py](quantia/core/stockfetch.py#L140-L170)

- `_log_source_failure_aggregated()`: Groups failures by source name
- Outputs aggregated WARNING every **60 seconds** (prevents log spam)
- Thread-safe via `_log_agg_lock`

### 8.6 Incremental Cache: `stock_hist_cache_incremental()`

**Location**: [stockfetch.py](quantia/core/stockfetch.py#L1305-L1440)

Supports 3 incremental scenarios:
1. **Tail append**: cache_last_date < date_end → fetch from cache end to date_end
2. **Head prepend**: date_start < cache_first_date → fetch from date_start to cache start
3. **Full fetch**: no cache → fetch entire range

Cache format: `cache/hist/{code[:3]}/{code}qfq.gzip.pickle`
Meta format: `cache/hist/{code[:3]}/{code}qfq.meta` → `{last_date},{update_time},{filtered_version}`

**Atomic write**: writes to `.tmp` file first, then `os.replace()` to prevent concurrent corruption.

### 8.7 Meta-Check Skip Optimization

**Location**: [stockfetch.py](quantia/core/stockfetch.py#L1175-L1190)

In `_read_cache_meta()`:
- Reads `.meta` file which contains `last_date,update_time,filtered_version`
- `_FILTER_VERSION = 2` — when meta's `filtered_version >= 2`, skips `_filter_ohlc_outliers()` (saves ~7ms/stock)
- In `update_all_caches._update_one()`: if `meta.last_date >= date_end`, returns `'skip'` immediately (**zero API calls**)

---

## 9. `update_all_caches` — Deep Dive {#9-update-all-caches}

**Location**: [stockfetch.py](quantia/core/stockfetch.py#L1628-L1850)

### 9.1 LOCAL Mode vs SERVER Mode

| Config | LOCAL (`QUANTIA_LOCAL_MODE=1`) | SERVER (default) |
|---|---|---|
| Default workers | **6** | **2** |
| Max workers | **12** | **4** |
| Request delay | **0.2–0.5s** | **1.0–3.0s** |
| Batch pause interval | Every **300** stocks | Every **100** stocks |
| Batch pause duration | **2–4s** | **8–15s** |
| Consecutive fail threshold | **5** | **3** |
| Base throttle pause | **60s** | **120s** |
| Max throttle triggers | **5** | **3** |
| Chunk size | **300** | **100** |

### 9.2 The 5-Layer Throttling Mechanism

| Layer | Mechanism | Details |
|---|---|---|
| **Layer 1 — Concurrency** | `ThreadPoolExecutor(max_workers=N)` | 2–12 threads (env configurable) |
| **Layer 2 — Request interval** | `time.sleep(random.uniform(delay_min, delay_max))` | After every stock (0.2–3.0s) |
| **Layer 3 — Batch pause** | After N stocks, pause M seconds | Every 100–300 stocks, pause 2–15s + `gc.collect()` |
| **Layer 4 — Throttle detection** | N consecutive failures → pause | 3–5 fails → 120–60s pause, exponentially doubles |
| **Layer 5 — Circuit breaker** | N throttle events → abort | 3–5 throttle events → terminate job entirely |

### 9.3 Meta-Check Skip Optimization

In `_update_one()`:
```python
meta = _read_cache_meta(code, 'qfq')
if meta and meta.get('last_date') and meta['last_date'] >= date_end:
    return 'skip'  # Zero API calls, zero delay
```

For a typical run where most stocks are already cached: **~80-95% of stocks skip entirely**.

### 9.4 Adaptive Request Delay

After each throttle event triggers and recovers:
```python
request_delay[0] = min(request_delay[0] * 1.5, 5.0)
request_delay[1] = min(request_delay[1] * 1.5, 8.0)
```

Delays grow: `1.0–3.0s → 1.5–4.5s → 2.25–6.75s → 3.38–8.0s` (capped at 5–8s).

### 9.5 Chunk-Based Processing

Instead of submitting all ~5000 futures at once:
- Groups stocks into chunks of `CHUNK_SIZE` (100 or 300)
- Creates a new `ThreadPoolExecutor` per chunk
- `gc.collect()` between chunks to release Future/DataFrame memory
- Logs progress: `已处理 {n}/{total}（成功=X, 失败=Y, 跳过=Z）`

---

## 10. Environment Variable Reference {#10-env-vars}

### EastMoney Fetcher
| Variable | Default | Description |
|---|---|---|
| `QUANTIA_EM_RETRY` | 3 | HTTP retry count |
| `QUANTIA_EM_TIMEOUT` | 30 | HTTP timeout (seconds) |

### Data Source Retry
| Variable | Default | Description |
|---|---|---|
| `DATA_SOURCE_MAX_RETRIES` | 2 | Per-source retry count for K-line fetch |
| `DATA_SOURCE_RETRY_INTERVAL` | 90 | Base retry interval (seconds) |
| `DATA_SOURCE_FAIL_THRESHOLD` | 5 | Failures before source degradation |
| `DATA_SOURCE_COOLDOWN_SECONDS` | 300 | Base cooldown period (seconds) |
| `DATA_SOURCE_MAX_COOLDOWN` | 3600 | Maximum cooldown (seconds) |

### K-Line Cache Workers
| Variable | Default | Description |
|---|---|---|
| `QUANTIA_LOCAL_MODE` | False | Enable local mode (high concurrency) |
| `QUANTIA_KLINE_CACHE_WORKERS` | 2 (server) / 6 (local) | Worker threads |
| `QUANTIA_KLINE_REQUEST_DELAY_MIN` | 1.0 (server) / 0.2 (local) | Min delay between requests |
| `QUANTIA_KLINE_REQUEST_DELAY_MAX` | 3.0 (server) / 0.5 (local) | Max delay between requests |
| `QUANTIA_KLINE_BATCH_INTERVAL` | 100 (server) / 300 (local) | Stocks per batch-pause cycle |
| `QUANTIA_KLINE_BATCH_PAUSE_MIN` | 8 (server) / 2 (local) | Min batch pause (seconds) |
| `QUANTIA_KLINE_BATCH_PAUSE_MAX` | 15 (server) / 4 (local) | Max batch pause (seconds) |
| `QUANTIA_KLINE_CHUNK_SIZE` | 100 (server) / 300 (local) | Chunk size for memory management |

### Crawling Workers
| Variable | Default | Description |
|---|---|---|
| `QUANTIA_CRAWL_WORKERS` | 5 | Thread workers for Sina/Tencent batch fetching |

### Proxy Pool
| Variable | Default | Description |
|---|---|---|
| `QUANTIA_PROXY_VALIDATE_URL` | `http://datacenter.eastmoney.com/api/data/get` | Proxy validation endpoint |
| `QUANTIA_PROXY_VALIDATE_TIMEOUT` | 5 | Validation timeout (seconds) |
| `QUANTIA_PROXY_REFRESH_INTERVAL` | 600 | Background refresh cycle (seconds) |
| `QUANTIA_PROXY_MIN_POOL_SIZE` | 3 | Minimum usable proxies |
| `QUANTIA_PROXY_FETCH_WORKERS` | 50 | Concurrent validation threads |
| `QUANTIA_PROXY_INIT_BATCH_SIZE` | 200 | Candidates to validate on init |
| `QUANTIA_PROXY_MAX_FAIL_COUNT` | 3 | Failures before proxy removal |
| `QUANTIA_PROXY_STALE_SECONDS` | 600 | Proxy freshness threshold |
| `QUANTIA_PROXY_CACHE_MAX_AGE` | 86400 | Disk cache validity (seconds) |
| `QUANTIA_PROXY_TARGET_POOL_SIZE` | 15 | Target pool size |
| `QUANTIA_PROXY_EMERGENCY_COOLDOWN` | 30 | Emergency refresh cooldown |

### History Data
| Variable | Default | Description |
|---|---|---|
| `HIST_DATA_DEFAULT_YEARS` | 10 | Default years of history to fetch |

### Job Control
| Variable | Default | Description |
|---|---|---|
| `QUANTIA_JOB_TIMEOUT` | 1800 | Subprocess timeout (seconds) |
| `QUANTIA_FORCE_KLINE_CACHE` | False | Skip run_fetch completion check |
| `QUANTIA_FRESH_STOCK_SPOT` | 3000 | Freshness threshold (row count) |

---

## 11. Total Request Count Estimation {#11-request-count}

### Scenario: Typical daily run with ~5000 A-shares

#### Phase 1: fetch_daily_job (Realtime Data)

| Task | Source | Calls | Notes |
|---|---|---|---|
| Stock spot quotes | EM (primary) | **1–2** | 5000/page, 1 page |
| ETF spot quotes | EM (primary) | **~15** | 50/page, ~750 ETFs |
| Index spot quotes | EM | **~3** | 50/page |
| Stock selection | EM | **~10** | 500/page |
| Fund flow (4 indicators) | EM | **~200** | 50 pages/indicator × 4 |
| Sector fund flow (2 sectors × 3 indicators) | EM | **~30** | |
| LHB detail + stats | EM | **~5** | |
| LHB institutional | EM | **~2** | |
| Block trade | EM | **~1** | |
| Dividend/bonus | EM | **~5** | |
| Limitup reason + details | THS | **~50** | 1 + up to ~50 detail requests |
| Chip race (open + close) | TDX | **2** | |
| Trade date calendar | Sina | **0–1** | DB-first, API fallback only |
| **Phase 1 subtotal** | | **~325** | |

#### Phase 2: kline_cache_daily_job (Historical K-Line)

| Scenario | Calls per stock | Total (5000 stocks) |
|---|---|---|
| **Cache already up-to-date (meta skip)** | **0** | **0** |
| **Incremental update (tail append, EM success)** | **1** | 1 × N |
| **EM fail → Tencent fallback** | **1+1** | 2 × N |
| **EM fail → Tencent fail → Sina fallback** | **1+1+1** | 3 × N |
| **Full fetch (new stock, no cache)** | **1** | 1 × N |

**Typical incremental run** (90% cached, 10% need 1-day update):
- 4500 stocks skip (meta check) = **0 calls**
- 500 stocks need tail append = **500 calls** (EM primary)
- Total: **~500 API calls**

**First run / after cache clear** (all 5000 stocks):
- 5000 × 1 call each = **5000 calls** minimum
- With fallbacks and retries: **5000–15000 calls**

#### Phase 3: Index Cache Update

| Task | Calls |
|---|---|
| 14 indices × 1–2 calls each | **~20** |
| Delay between indices | `random.uniform(0.5, 1.5)s` |

#### Proxy Pool (background)

| Task | Calls |
|---|---|
| Initial fetch (6 sources) | **~6** |
| Validation (200 candidates × parallel) | **~200** (to EM validation URL) |
| Periodic refresh (every 10 min) | **~50** per cycle |

### Grand Total Per Day

| Scenario | Estimated API Calls |
|---|---|
| **Fully cached (normal daily run)** | **~800–1,500** |
| **Partial cache miss (10% stocks)** | **~1,500–2,500** |
| **First run (no cache)** | **~5,500–11,000** |
| **All sources failing (with retries)** | **~15,000–25,000** |

---

## Summary of All sleep/delay Patterns

| Location | Pattern | Context |
|---|---|---|
| [eastmoney_fetcher.py](quantia/core/eastmoney_fetcher.py#L131) | `random.uniform(1, 3)` | Connection error retry |
| [eastmoney_fetcher.py](quantia/core/eastmoney_fetcher.py#L136) | `random.uniform(2, 5) * (i+1)` | General error retry |
| [stock_hist_em.py](quantia/core/crawling/stock_hist_em.py#L57) | `random.uniform(2, 3)` | Spot pagination |
| [stock_hist_em.py](quantia/core/crawling/stock_hist_em.py#L316) | `random.uniform(0.2, 0.5)` | Pre K-line request |
| [stock_sina.py](quantia/core/crawling/stock_sina.py#L190) | `random.uniform(0.5, 1)` every 10 batches | Spot batch throttle |
| [stock_tencent.py](quantia/core/crawling/stock_tencent.py#L179) | `random.uniform(0.5, 1)` every 10 batches | Spot batch throttle |
| [stock_hist_sina.py](quantia/core/crawling/stock_hist_sina.py#L120) | `random.uniform(3, 6)` | Pre K-line request (anti-456) |
| [stock_hist_tencent.py](quantia/core/crawling/stock_hist_tencent.py#L149) | `random.uniform(0.3, 0.8)` / `random.uniform(0.5, 1.5)` | Per-batch K-line |
| [stock_fund_em.py](quantia/core/crawling/stock_fund_em.py#L36) | `random.uniform(2, 4) * attempt` | Fund flow page retry |
| [stock_fund_em.py](quantia/core/crawling/stock_fund_em.py#L105) | `random.uniform(1, 1.5)` | Fund flow pagination |
| [stock_lhb_em.py](quantia/core/crawling/stock_lhb_em.py#L72) | `random.uniform(1, 1.5)` | LHB pagination |
| [stock_dzjy_em.py](quantia/core/crawling/stock_dzjy_em.py#L48) | `random.uniform(1, 1.5)` | Block trade pagination |
| [stock_fhps_em.py](quantia/core/crawling/stock_fhps_em.py#L72) | `random.uniform(1, 1.5)` | Dividend pagination |
| [stock_selection.py](quantia/core/crawling/stock_selection.py#L62) | `random.uniform(0.5, 1.5)` | Selection pagination |
| [stock_selection.py](quantia/core/crawling/stock_selection.py#L51) | `random.uniform(2, 5)` | First page retry |
| [stock_index_em.py](quantia/core/crawling/stock_index_em.py#L72) | `random.uniform(2, 3)` | Index spot pagination |
| [stock_index_em.py](quantia/core/crawling/stock_index_em.py#L176) | `random.uniform(0.2, 0.5)` | Pre index K-line request |
| [fund_etf_em.py](quantia/core/crawling/fund_etf_em.py#L54) | `random.uniform(2, 3)` | ETF spot pagination |
| [etf_sina.py](quantia/core/crawling/etf_sina.py#L158) | `random.uniform(0.5, 1)` every 10 batches | ETF batch throttle |
| [etf_tencent.py](quantia/core/crawling/etf_tencent.py#L149) | `random.uniform(0.5, 1)` every 10 batches | ETF batch throttle |
| [stockfetch.py](quantia/core/stockfetch.py#L176-L187) | `base_interval * 2^retry + 10-30% jitter` | `_retry_sleep()` |
| [stockfetch.py](quantia/core/stockfetch.py#L1160) | `random.uniform(0.5, 1.5)` | Between index cache updates |
| [stockfetch.py](quantia/core/stockfetch.py#L1760) | `random.uniform(delay[0], delay[1])` | Per-stock in `update_all_caches` |
| [stockfetch.py](quantia/core/stockfetch.py#L1830) | `random.uniform(*batch_pause)` | Between chunks in `update_all_caches` |
