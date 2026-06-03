# Cron 定时任务说明

## 架构概览

```
cron/
├── _common.sh                      ← 公共库（环境初始化、日志、运行器）
├── backfill_fund_all.sh            ← 基金中心一键全量铺底（首次初始化，手动跑，非定时）
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
| `backfill_fund_all.sh` | 手动（首次） | `fetch_fund_nav_history_job.py` + `fetch_fund_profile_job.py` + `fetch_fund_holding_job.py` + `analysis_fund_score_job.py` | 基金中心一键全量铺底：按依赖顺序 F8 净值→F10 画像→F12 重仓→F7 评分；失败不阻断；TopN 可经环境覆盖（默认 200）。仅服务器本地跑，日常增量仍由上述定时任务维护 |

---

## 基金中心数据全量铺底

首次启用基金中心（排行榜评分条、夏普/最大回撤/规模/评级、详情抽屉图表）需先铺底 4 张表：
`cn_fund_nav_history` / `cn_fund_profile` / `cn_fund_holding` / `cn_fund_rank_score`。

**务必在服务器 `/root/Quantia` 本地执行**（job 写 localhost MySQL，零公网压力；从本地经公网批量写远程小内存库会 OOM）：

```bash
cd /root/Quantia
chmod +x cron/backfill_fund_all.sh
nohup bash cron/backfill_fund_all.sh &        # 后台跑，避免 SSH 断开中断
tail -f quantia/log/backfill_fund_all.log     # 实时进度

# 可选：覆盖 TopN（每个净值型桶按近1年收益取前 N 只）
QUANTIA_FUND_NAV_TOPN=300 bash cron/backfill_fund_all.sh
```

依赖顺序（脚本已内置）：F8 净值历史 + `cn_fund_rank` → F7 综合评分（夏普/最大回撤/近5年依赖净值历史）；F10 画像、F12 重仓股相互独立。

铺底后日常增量自动维护：F8/F7 随工作日 `run_fetch` / `run_analysis`，F10/F12 随每月 `run_fund_profile_holding`，无需重复手动跑。

验证：

```bash
python -c "import quantia.lib.database as mdb; \
print('nav', mdb.executeSqlFetch('SELECT COUNT(DISTINCT code) FROM cn_fund_nav_history')); \
print('profile', mdb.executeSqlFetch('SELECT COUNT(*) FROM cn_fund_profile')); \
print('holding', mdb.executeSqlFetch('SELECT COUNT(DISTINCT code) FROM cn_fund_holding')); \
print('score', mdb.executeSqlFetch('SELECT COUNT(*) FROM cn_fund_rank_score'))"
```

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
  09:30~14:55       18:10(+22:00重试)      23:00           04:00        05:30   06:15
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

  07:00          08:30                              01:30(月初)   5月底/季度首月
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

# 数据获取（主跑：清算时点 18:00 之后才拉，避免抢到未结算的龙虎榜/资金流向）
# 夜间重试安排在 K线缓存之前，确保重试补回的数据当晚就能被缓存消费
10 18 * * 1-5  flock -xn /tmp/quantia_fetch.lock    /root/Quantia/cron/cron.workdayly/run_fetch
0  22 * * 1-5  flock -xn /tmp/quantia_fetch.lock    /root/Quantia/cron/cron.workdayly/run_fetch

# K线缓存更新（当日夜间；DOW 与 fetch 对齐为 1-5，修复周一夜间被漏更新的缺陷）
0  23 * * 1-5  flock -xn /tmp/quantia_kline.lock    /root/Quantia/cron/cron.workdayly/run_kline_cache

# 数据分析（次日凌晨；DOW 2-6 对应 T+1 早晨）
0   4 * * 2-6  flock -xn /tmp/quantia_analysis.lock /root/Quantia/cron/cron.workdayly/run_analysis

# 模拟交易（分析完成后；留 1.5h 间隔，降低与分析重叠概率）
30  5 * * 2-6  flock -xn /tmp/quantia_paper.lock   /root/Quantia/cron/cron.workdayly/run_paper_trading

# AI 定时报告 + 评分预警（模拟交易完成后执行）
15  6 * * 2-6  flock -xn /tmp/quantia_report.lock  /root/Quantia/cron/cron.workdayly/run_report_alert

# AI 知识库索引刷新（错峰至 07:00，避开 06:15 报告预警）
0   7 * * 1-5  /root/Quantia/cron/cron.workdayly/refresh_ai_kb

# 综合指标股票池刷新（开盘前）
30  8 * * 1-5  flock -xn /tmp/quantia_composite.lock /root/Quantia/cron/cron.workdayly/refresh_composite_universe

# === 月度任务：全部排在 00:00~02:30，安全早于 04:00 数据分析；彼此错峰 ===
# 季度专利增量（每月 1 日触发，脚本自判仅 1/4/7/10 月实际执行）
0   0 1 * *    flock -xn /tmp/quantia_patents.lock /root/Quantia/cron/cron.monthly/run_patents_quarterly

# 月度缓存清理 + 财务数据更新（慢 job，给足到 04:00 的缓冲）
30  1 1 * *    flock -xn /tmp/quantia_monthly.lock /root/Quantia/cron/cron.monthly/run_monthly

# 年度专利采集（5 月底，年报披露窗口结束后；全市场最近 5 年年报）
30  2 25 5 *   flock -xn /tmp/quantia_patents.lock /root/Quantia/cron/cron.monthly/run_patents_annual

# 场外基金画像 + 重仓股月度采集（F10/F12，慢 job）
# 放在 day2 盘后空档 15:30，彻底避开夜间重任务窗口（kline 23:00 / analysis 04:00 / paper 05:30）
30  15 2 * *   flock -xn /tmp/quantia_fund.lock /root/Quantia/cron/cron.monthly/run_fund_profile_holding
```

> **flock 说明**：`-x` 排他锁 + `-n` 非阻塞，同类任务只能有一个在运行，后来者立即退出。
> 获取/K线/分析使用**不同锁文件**，三者互不阻塞。
>
> **编排时间设计要点**：
> - **fetch 主跑 18:10**：晚于清算时点 18:00（`QUANTIA_SETTLEMENT_HOUR`），确保拿到当日完整结算数据；
>   原 17:55 早于结算，可能抓到未就绪的龙虎榜/资金流向。
> - **fetch 重试 22:00 → kline 23:00**：重试在缓存之前，重试补回的数据当晚即可被 K线缓存消费；
>   原重试 23:55 在 kline 23:00 之后，对当晚缓存毫无帮助。
> - **kline DOW 1-5**（原 2-6）：与 fetch 对齐。原 2-6 会漏掉周一夜间缓存（周一 1∉2-6，周六 6 又被非交易日跳过）。
> - **morning 链路拉开间隔**：analysis 04:00 → paper 05:30 → report 06:15 → ai_kb 07:00 → composite 08:30，
>   逐级留 45min~1.5h，降低慢任务（回测最长 2h）尾延导致的重叠。
>
> **OOM 防护（1.6G 小内存服务器）**：
> - `run_fetch` / `run_kline_cache` / `run_analysis` 在拆分模式下各自会停止 nginx + Quantia Web
>   释放内存（`stop_services_for_memory`），任务结束（含异常/OOM kill）由 `trap` 兜底恢复。
>   `run_workdayly` 编排模式通过 `QUANTIA_NO_SERVICE_STOP=1` 统一接管，子脚本不重复停服。
> - 夜间重任务（kline/analysis）已在时间上完全错开（23:00 vs 04:00），任意时刻只有一个内存高峰。
> - 月度慢 job 全部前移到 00:00~02:30 或盘后 15:30，避免与每日重任务及本地 MySQL 同时争抢内存。
> - **残留风险**：若某次 analysis 触发满 2h 回测，尾部可能与 05:30 paper 轻微重叠；
>   1.6G 下因服务已停、analysis 峰值 <50MB 仍安全，但若要严格串行请改用 `run_workdayly` 编排模式。

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
[2026-01-15 18:10:02] [INFO]  ────── 数据获取 (fetch_daily_job) 开始 ──────
[2026-01-15 18:22:35] [INFO]  ────── 数据获取 (fetch_daily_job) 完成 ✓ (12m33s) ──────
[2026-01-15 23:00:01] [INFO]  ────── K线缓存增量更新 (kline_cache_daily_job) 开始 ──────
[2026-01-15 23:45:18] [INFO]  ────── K线缓存增量更新 (kline_cache_daily_job) 完成 ✓ (45m17s) ──────
[2026-01-16 04:00:01] [INFO]  ────── 数据分析 (analysis_daily_job) 开始 ──────
[2026-01-16 04:38:44] [INFO]  ────── 数据分析 (analysis_daily_job) 完成 ✓ (8m43s) ──────
```

`run_workdayly` 编排模式下，额外输出阶段分隔符：

```
[2026-01-15 18:10:01] [INFO]  ============ 每日完整任务开始 ============
[2026-01-15 18:10:01] [INFO]  ══════ Phase 1: 数据获取 开始 ══════
[2026-01-15 18:10:02] [INFO]  ────── 数据获取 (fetch_daily_job) 开始 ──────
...
[2026-01-15 18:22:35] [INFO]  ────── 数据获取 (fetch_daily_job) 完成 ✓ (12m33s) ──────
[2026-01-15 18:22:35] [INFO]  ══════ Phase 1: 数据获取 完成 ✓ (12m34s) ══════
[2026-01-15 18:22:35] [INFO]  ══════ Phase 2: K线缓存更新 开始 ══════
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
`run_fetch` / `run_kline_cache` / `run_analysis` 独立运行时均会自行停止/恢复服务
（`stop_services_for_memory` + `trap` 兑底），无需手动包裹。三者在时间上完全错峰
（fetch 18:10 / kline 23:00 / analysis 04:00），任意时刻只有一个内存高峰。

### 配置

```bash
# .env - 自定义需要停止的服务
QUANTIA_STOP_SERVICES=nginx          # 默认只停 nginx

# 如果不需要 OOM 防护（内存充足的机器）
QUANTIA_NO_SERVICE_STOP=1
```

### 手动运行内存密集任务时

`run_kline_cache` 和 `run_analysis` 已内置服务停止/恢复逻辑，独立手动运行即可：

```bash
bash cron/cron.workdayly/run_kline_cache    # 自动停服 → 跑 → 恢复
```

若在内存充足的机器上不需要停服，设 `QUANTIA_NO_SERVICE_STOP=1` 跳过。
Python 端由 `quantia/lib/envconfig.py` 统一加载 `.env`。完整变量列表见项目根目录 `.env.example`。
