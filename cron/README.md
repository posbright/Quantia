# Cron 定时任务说明

## 架构概览

```
cron/
├── _common.sh                      ← 公共库（环境初始化、日志、运行器）
├── cron.hourly/
│   └── run_hourly                  ← 盘中/收盘行情快照
├── cron.workdayly/
│   ├── run_fetch                   ← Phase 1: API 数据获取
│   ├── run_kline_cache             ← Phase 2: K线缓存增量更新
│   ├── run_analysis                ← Phase 3: 本地数据分析
│   ├── run_paper_trading           ← Phase 4: 模拟交易执行
│   ├── run_report_alert            ← Phase 5: AI 定时报告 + 评分预警
│   ├── refresh_composite_universe  ← Phase 9: 综合指标股票池刷新
│   ├── refresh_ai_kb               ← M9: AI 知识库索引
│   └── run_workdayly               ← 编排器：串行执行 Phase 1→1.5→1.6→1.7→2→3→4→5
└── cron.monthly/
    ├── run_monthly                 ← 月度缓存清理
    ├── run_patents_annual          ← 年度专利采集（5月，巨潮年报全量）
    ├── run_patents_quarterly       ← 季度专利增量（1/4/7/10月，Google Patents）
    └── run_fund_profile_holding    ← 月度基金画像 + 重仓股采集（F10/F12）
```

所有脚本共享 `_common.sh` 公共库，消除重复的环境初始化代码。每个脚本仅 10~15 行。

---

## 脚本一览

| 脚本 | 频率 | Python 入口 | 说明 |
|------|------|-------------|------|
| `run_hourly` | 盘中/收盘 | `basic_data_daily_job.py` | 实时行情快照 |
| `run_fetch` | 工作日 | `fetch_daily_job.py` + `fetch_fund_nav_history_job.py` | API 数据采集（行情+选股+资金流向）；附 F8 基金净值历史回填 |
| `run_kline_cache` | 工作日 | `kline_cache_daily_job.py` | K线缓存增量更新（~5000只股票） |
| `run_analysis` | 工作日 | `analysis_daily_job.py` + `analysis_fund_score_job.py` | 本地分析（GPT+指标+策略+回测）；附 F7 基金多因子综合评分 |
| `run_paper_trading` | 工作日 | `paper_trading_daily_job.py` | 模拟交易每日执行 |
| `run_report_alert` | 工作日 | `stock_report_scheduled.py` | AI 定时报告分析 + 评分预警推送（模拟交易后） |
| `refresh_composite_universe` | 工作日 | `composite.dynamic_universe` | 综合指标股票池刷新（开盘前） |
| `refresh_ai_kb` | 工作日 | `quantia.lib.ai.retrieval.indexer` | AI 知识库 FULLTEXT 索引刷新 |
| `run_workdayly` | 工作日 | — | 编排器：串行调用 fetch→公告→专利采集→专利聚合→kline→analysis→paper→report_alert |
| `run_monthly` | 每月1日 | — | 智能清理退市/除权缓存 + 财务数据更新 |
| `run_patents_annual` | 每年5月 | `fetch_patent_data.py` | 全市场近5年年报专利全量采集（主源） |
| `run_patents_quarterly` | 季度首月 | `fetch_patent_data.py --source google_patents` | Google Patents 增量补充 IPC/引用/趋势/PCT（备份源，脚本自判 1/4/7/10 月） |
| `run_fund_profile_holding` | 每月 | `fetch_fund_profile_job.py` + `fetch_fund_holding_job.py` | F10 基金画像（规模/经理/评级）+ F12 季度前十大重仓股采集 |

---

## _common.sh 公共库

每个脚本在运行前 source `_common.sh`，获得以下能力：

| 函数 | 用途 |
|------|------|
| `init_env` | 设置 PATH/PYTHONPATH/编码、加载 `.env`、创建日志目录 |
| `log_info` / `log_warn` / `log_error` | 带时间戳的分级日志（写入 `$LOG_FILE`） |
| `elapsed_fmt` | 秒数格式化（`1h05m30s` / `3m22s` / `45s`） |
| `check_trade_day` | 非交易日自动 `exit 0`（节假日、周末不执行） |
| `run_job "标签" "脚本路径" [超时]` | 运行 Python 脚本，记录耗时和退出码 |
| `run_sub "标签" "脚本路径"` | 运行 Shell 子脚本（用于 `run_workdayly` 编排） |
| `stop_services_for_memory "原因"` | 停止 nginx + Quantia Web 服务，释放内存 |
| `start_services_after_memory` | 恢复之前停止的服务 |

### 脚本模板

```bash
#!/bin/bash
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
source "$PROJECT_ROOT/cron/_common.sh"

init_env
LOG_FILE=$LOG_DIR/workdayly.log

check_trade_day "任务名称"
run_job "任务标签" "quantia/job/xxx_job.py"
```

Docker 版区别仅在前两行：

```bash
PROJECT_ROOT=/data/Quantia
source /etc/cron/_common.sh
```

---

## 每日流水线

各阶段独立运行，互不阻塞：

```
  09:30~14:55       17:55(+23:55重试)      23:00           04:30        05:00   05:30
    │                    │                   │               │            │       │
    ▼                    ▼                   ▼               ▼            ▼       ▼
┌──────────┐      ┌─────────┐      ┌──────────────┐  ┌──────────┐  ┌────────────┐ ┌────────────┐
│run_hourly│      │run_fetch │      │run_kline_cache│  │run_analysis│ │paper_trading│ │report_alert│
│(盘中快照) │      │(API调用) │      │(缓存更新)     │  │(本地计算)  │  │(模拟交易)   │ │(AI报告+预警)│
│6次/交易日 │      │~5-15min  │      │~20-60min     │  │~10min     │  │            │ │            │
└──────────┘      └─────────┘      └──────────────┘  └──────────┘  └────────────┘ └────────────┘
                       ↓
                  cn_job_status
                   (完成标记)─────→ kline_cache 前置检查

  06:00          08:30                              04:00(月初)   5月底/季度首月
    │              │                                   │              │
    ▼              ▼                                   ▼              ▼
┌───────────┐  ┌───────────────────────┐         ┌──────────┐  ┌──────────────┐
│refresh_ai_kb│ │refresh_composite_universe│        │run_monthly│  │run_patents_* │
│(知识库索引) │  │(综合指标股票池)          │         │(缓存清理) │  │(年度/季度专利)│
└───────────┘  └───────────────────────┘         └──────────┘  └──────────────┘
```

**阶段间依赖**：
- `run_kline_cache` 通过 `cn_job_status` 表检查 `run_fetch` 是否已完成，未完成则自动跳过
- `run_analysis` 无硬依赖，即使缓存未更新也能用历史数据运行
- 每个阶段失败不影响后续阶段继续执行

**`run_workdayly` 编排器**：适合单机一键运行，串行调用 8 个阶段，含自动 OOM 防护：

| Phase | 内容 | 入口 | 服务停止 |
|-------|------|------|----------|
| 1 | 数据获取 | `run_fetch`（`fetch_daily_job.py`） | 否 |
| 1.5 | 公告事件采集 | `stock_announcement_em --days 1` | 否 |
| 1.6 | 专利数据采集（巨潮公告挖掘） | `stock_patent_crawler --days 7` | 否 |
| 1.7 | 专利数据聚合（`cn_stock_patent_info` → `cn_stock_patents`） | `aggregate_patent_data` | 否 |
| 2 | K线缓存更新（内存密集型） | `run_kline_cache` | **是** |
| 3 | 数据分析（内存密集型） | `run_analysis` | **是** |
| 4 | 模拟交易 | `run_paper_trading` | 否（已恢复） |
| 5 | AI报告+评分预警 | `run_report_alert` | 否 |

> Phase 2/3 执行前自动停止 nginx + Quantia Web 释放内存，完成后恢复（`trap` 兜底）。
> Phase 1.5/1.6/1.7 为轻量 API/计算，异常仅 `log_warn` 不计入失败阶段数。
> 阶段失败统计以 5 个 `run_sub` 阶段（1/2/3/4/5）为分母。

---

## Crontab 配置

### 裸机部署（推荐拆分模式）

```bash
crontab -e

# === quantia crontab (managed) ===
# 盘中行情快照（hourly：交易时段每小时 + 收盘前一刻）
30  9 * * 1-5  flock -xn /tmp/quantia_hourly.lock   /root/Quantia/cron/cron.hourly/run_hourly
30 10 * * 1-5  flock -xn /tmp/quantia_hourly.lock   /root/Quantia/cron/cron.hourly/run_hourly
25 11 * * 1-5  flock -xn /tmp/quantia_hourly.lock   /root/Quantia/cron/cron.hourly/run_hourly
30 13 * * 1-5  flock -xn /tmp/quantia_hourly.lock   /root/Quantia/cron/cron.hourly/run_hourly
30 14 * * 1-5  flock -xn /tmp/quantia_hourly.lock   /root/Quantia/cron/cron.hourly/run_hourly
55 14 * * 1-5  flock -xn /tmp/quantia_hourly.lock   /root/Quantia/cron/cron.hourly/run_hourly

# 数据获取 + 夜间重试
55 17 * * 1-5  flock -xn /tmp/quantia_fetch.lock    /root/Quantia/cron/cron.workdayly/run_fetch
55 23 * * 1-5  flock -xn /tmp/quantia_fetch.lock    /root/Quantia/cron/cron.workdayly/run_fetch

# K线缓存更新（当日夜间）
0  23 * * 2-6  flock -xn /tmp/quantia_kline.lock    /root/Quantia/cron/cron.workdayly/run_kline_cache

# 数据分析（次日凌晨）
30  4 * * 2-6  flock -xn /tmp/quantia_analysis.lock /root/Quantia/cron/cron.workdayly/run_analysis

# 模拟交易（分析完成后执行）
0   5 * * 2-6  flock -xn /tmp/quantia_paper.lock   /root/Quantia/cron/cron.workdayly/run_paper_trading

# AI 定时报告 + 评分预警（模拟交易完成后执行）
30  5 * * 2-6  flock -xn /tmp/quantia_report.lock  /root/Quantia/cron/cron.workdayly/run_report_alert

# 综合指标股票池刷新（开盘前）
30  8 * * 1-5  flock -xn /tmp/quantia_composite.lock /root/Quantia/cron/cron.workdayly/refresh_composite_universe

# AI 知识库索引刷新
0   6 * * 1-5  /root/Quantia/cron/cron.workdayly/refresh_ai_kb

# 月度缓存清理
0   4 1 * *    /root/Quantia/cron/cron.monthly/run_monthly

# 年度专利采集（5 月底，年报披露窗口结束后；全市场最近 5 年年报）
0   3 25 5 *   flock -xn /tmp/quantia_patents.lock /root/Quantia/cron/cron.monthly/run_patents_annual

# 季度专利增量（每月 1 日触发，脚本自判仅 1/4/7/10 月实际执行）
0   2 1 * *    flock -xn /tmp/quantia_patents.lock /root/Quantia/cron/cron.monthly/run_patents_quarterly

# 场外基金画像 + 重仓股月度采集（F10/F12，慢 job）
0   5 2 * *    flock -xn /tmp/quantia_fund.lock /root/Quantia/cron/cron.monthly/run_fund_profile_holding
```

> **flock 说明**：`-x` 排他锁 + `-n` 非阻塞，同类任务只能有一个在运行，后来者立即退出。
> 获取/K线/分析使用**不同锁文件**，三者互不阻塞。

### Docker 容器

Docker 定时任务在 Dockerfile 中自动配置，时间表与裸机相同，脚本路径为 `/etc/cron.*`。
新增 `_common.sh` 由 `COPY cron/_common.sh /etc/cron/_common.sh` 部署到容器中。

---

## 手动执行

```bash
# 执行每小时任务
./cron/cron.hourly/run_hourly

# 执行完整每日任务（fetch → kline_cache → analysis）
./cron/cron.workdayly/run_workdayly

# 仅执行数据获取
./cron/cron.workdayly/run_fetch

# 仅执行K线缓存增量更新
./cron/cron.workdayly/run_kline_cache

# 仅执行数据分析
./cron/cron.workdayly/run_analysis

# 仅执行 AI 报告 + 评分预警
./cron/cron.workdayly/run_report_alert

# 月度清理（智能清理）
./cron/cron.monthly/run_monthly

# 月度清理（全量清除）
./cron/cron.monthly/run_monthly --all

# 年度专利采集（巨潮年报，全市场）
./cron/cron.monthly/run_patents_annual

# 季度专利增量（Google Patents，仅 1/4/7/10 月生效）
./cron/cron.monthly/run_patents_quarterly
```

首次部署需设置可执行权限：

```bash
chmod +x cron/_common.sh cron/cron.hourly/* cron/cron.workdayly/* cron/cron.monthly/*
```

---

## 日志输出

日志写入 `quantia/log/` 目录：

| 文件 | 来源 |
|------|------|
| `hourly.log` | `run_hourly` |
| `workdayly.log` | `run_fetch` / `run_kline_cache` / `run_analysis` / `run_paper_trading` / `run_workdayly`（含 Phase 1.5/1.6/1.7 公告与专利采集聚合） |
| `report_alert.log` | `run_report_alert` |
| `refresh_composite_universe.log` | `refresh_composite_universe` |
| `refresh_ai_kb.log` | `refresh_ai_kb` |
| `monthly.log` | `run_monthly` |
| `patents_annual.log` | `run_patents_annual` |
| `patents_quarterly.log` | `run_patents_quarterly` |

日志格式示例：

```
[2026-01-15 17:55:02] [INFO]  ────── 数据获取 (fetch_daily_job) 开始 ──────
[2026-01-15 18:07:35] [INFO]  ────── 数据获取 (fetch_daily_job) 完成 ✓ (12m33s) ──────
[2026-01-15 23:00:01] [INFO]  ────── K线缓存增量更新 (kline_cache_daily_job) 开始 ──────
[2026-01-15 23:45:18] [INFO]  ────── K线缓存增量更新 (kline_cache_daily_job) 完成 ✓ (45m17s) ──────
[2026-01-16 04:30:01] [INFO]  ────── 数据分析 (analysis_daily_job) 开始 ──────
[2026-01-16 04:38:44] [INFO]  ────── 数据分析 (analysis_daily_job) 完成 ✓ (8m43s) ──────
```

`run_workdayly` 编排模式下，额外输出阶段分隔符：

```
[2026-01-15 17:55:01] [INFO]  ============ 每日完整任务开始 ============
[2026-01-15 17:55:01] [INFO]  ══════ Phase 1: 数据获取 开始 ══════
[2026-01-15 17:55:02] [INFO]  ────── 数据获取 (fetch_daily_job) 开始 ──────
...
[2026-01-15 18:07:35] [INFO]  ────── 数据获取 (fetch_daily_job) 完成 ✓ (12m33s) ──────
[2026-01-15 18:07:35] [INFO]  ══════ Phase 1: 数据获取 完成 ✓ (12m34s) ══════
[2026-01-15 18:07:35] [INFO]  ══════ Phase 2: K线缓存更新 开始 ══════
...
[2026-01-15 19:58:10] [INFO]  ============ 每日完整任务结束 ✓ (全部成功, 1h58m09s) ============
```

---

## 重试安全性（幂等性保证）

所有任务均**可安全重试**，不会因重复执行导致数据冗余或资源浪费：

### 防重复执行机制

| 机制 | 层级 | 说明 |
|------|------|------|
| `flock -xn` | Shell | 排他锁+非阻塞，同类任务只能有一个实例 |
| `check_trade_day()` | Shell | 非交易日自动跳过 |
| `is_data_fresh()` | Python | 各表数据新鲜度检查，已有完整数据时跳过 |
| `is_job_completed()` | Python | `run_fetch` 整体完成检查（`cn_job_status` 表） |
| `_is_analysis_done()` | Python | 分析数据已存在（≥1000条）时自动跳过 |
| `_check_fetch_completed()` | Python | `run_kline_cache` 前置检查：fetch 未完成则跳过 |

### 数据写入幂等性

| 操作 | 机制 | 安全 |
|------|------|------|
| DB 数据入库 | `DELETE WHERE date=X` → `INSERT` | ✅ 重跑覆盖旧数据 |
| 并发写入 | `INSERT ... ON DUPLICATE KEY UPDATE` | ✅ 主键冲突自动更新 |
| K线缓存更新 | 增量模式：只拉新数据 | ✅ 已有数据不重拉 |
| 回测计算 | 只处理 `backtest IS NULL` 的记录 | ✅ 已回测的不重算 |

---

## 异常恢复

### K线缓存

- 增量逻辑：读取 `.meta` 最后日期 → 只从数据源拉取新增数据 → 合并写入
- 缓存损坏（写入时崩溃）：下次读取自动检测 → 触发全量重拉
- API 拉取失败：返回已有缓存数据，不覆盖写入

### 各 Job 异常后重跑

| Job | 重跑恢复 | 可补历史 | 说明 |
|-----|---------|---------|------|
| `fetch_daily_job` | ✅ | ✅ 增量 | 缓存机制，首次全量，后续补缺 |
| `basic_data_daily_job` | ✅ | ❌ 仅当天 | 实时行情快照，不提供历史回查 |
| `selection_data_daily_job` | ✅ | ❌ 仅当天 | 综合选股为实时快照 |
| `basic_data_other_daily_job` | ✅ | ⚠️ 部分 | 龙虎榜/资金流为实时 |
| `streaming_analysis_job` | ✅ | ✅ 可补跑 | 基于缓存计算，支持日期参数 |
| `backtest_data_daily_job` | ✅ | ✅ 自动补 | 查询 NULL 字段自动补填 |

### 补跑历史数据

```bash
cd /root/Quantia

# 补跑单个日期
python3 quantia/job/strategy_data_daily_job.py 2026-02-06

# 补跑日期区间
python3 quantia/job/strategy_data_daily_job.py 2026-02-01 2026-02-06

# 补跑多个指定日期
python3 quantia/job/indicators_data_daily_job.py 2026-02-03,2026-02-05
```

---

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `QUANTIA_FORCE_FETCH` | — | 设为 `1` 强制执行数据获取（跳过新鲜度检查） |
| `QUANTIA_FORCE_KLINE_CACHE` | — | 设为 `1` 强制执行K线缓存更新（跳过前置检查） |
| `QUANTIA_FORCE_ANALYSIS` | — | 设为 `1` 强制执行数据分析（跳过已完成检查） |
| `QUANTIA_FRESH_STOCK_SPOT` | 3000 | stock_spot 新鲜度阈值（行数） |
| `QUANTIA_FRESH_ETF_SPOT` | 200 | etf_spot 新鲜度阈值（行数） |
| `QUANTIA_FRESH_SELECTION` | 100 | selection 新鲜度阈值（行数） |
| `QUANTIA_FRESH_FUND_FLOW` | 2000 | fund_flow 新鲜度阈值（行数） |
| `HIST_DATA_DEFAULT_YEARS` | 10 (Docker: 3) | 历史K线默认获取年数 |
| `QUANTIA_BATCH_SIZE` | 50 | 流式分析每批处理股票数 |
| `QUANTIA_ANALYSIS_WORKERS` | 2 | 流式分析并发线程数 |
| `QUANTIA_KLINE_CACHE_WORKERS` | 2 | K线缓存更新并发数 |
| `QUANTIA_BACKTEST_OUTER_WORKERS` | 1 | 回测外层并发（按表） |
| `QUANTIA_BACKTEST_INNER_WORKERS` | 2 | 回测内层并发（按股票） |
| `QUANTIA_STOP_SERVICES` | nginx | 内存密集任务前停止的系统服务（空格分隔） |
| `QUANTIA_NO_SERVICE_STOP` | 0 | 设为 `1` 禁用自动停止/恢复服务 |
| `QUANTIA_SETTLEMENT_HOUR` | 18 | API 数据结算时间（小时） |
| `QUANTIA_FETCH_TIMEOUT` | 7200 | `run_fetch` 超时秒数（默认 2 小时） |
| `PYTHON_BIN` | python3 | Python 解释器路径（`refresh_*` 脚本使用） |

可通过 `.env` 文件或系统环境变量设置，`_common.sh` 的 `init_env` 会自动加载 `.env` 文件。

---

## OOM 防护（低内存服务器）

1.6GB 服务器同时运行 MySQL + nginx + Quantia Web + Python 分析任务时容易 OOM。
`run_workdayly` 和 `run_fetch`（独立调度时）都会在执行前自动停止 nginx 和 Quantia Web 服务，
完成后自动恢复。

### 工作流程

**`run_workdayly` 编排模式**（推荐）：
```
◆ Phase 1: run_fetch（自带停止/恢复服务）
    ↓
◆ 停止 nginx + Quantia Web（释放 ~200MB）
    ↓
Phase 2: K线缓存更新（内存密集）
Phase 3: 数据分析（内存密集）
    ↓
◆ 恢复 nginx + Quantia Web
    ↓
Phase 4: 模拟交易（低内存）
```

**独立调度模式**（crontab 拆分）：
`run_fetch` 独立运行时自行停止/恢复服务；`run_kline_cache` 和 `run_analysis` 不含 OOM 逻辑，
需手动管理或通过 `run_workdayly` 包裹。

### 配置

```bash
# .env - 自定义需要停止的服务
QUANTIA_STOP_SERVICES=nginx          # 默认只停 nginx

# 如果不需要 OOM 防护（内存充足的机器）
QUANTIA_NO_SERVICE_STOP=1
```

### 手动运行内存密集任务时

如果单独运行 `run_kline_cache` 或 `run_analysis`（不通过 `run_workdayly`），
需要手动停止/恢复服务，或在脚本中调用：

```bash
source cron/_common.sh && init_env
stop_services_for_memory "手动K线缓存更新"
bash cron/cron.workdayly/run_kline_cache
start_services_after_memory
```
Python 端由 `quantia/lib/envconfig.py` 统一加载 `.env`。完整变量列表见项目根目录 `.env.example`。
