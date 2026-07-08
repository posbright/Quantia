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
│   ├── run_events_patents          ← Phase 1.5: 公告事件 + 专利采集聚合
│   ├── refresh_composite_universe  ← Phase 6: 综合指标股票池刷新
│   ├── refresh_ai_kb               ← Phase 7: AI 知识库索引
│   ├── run_fund_holding_batch      ← Phase 8: 基金重仓股全覆盖分批（方案C 开启时；否则秒级空跑）
│   └── run_workdayly               ← 编排器：串行执行 Phase 1→1.5→2→3→4→5→6→7→8
└── cron.monthly/
    ├── run_monthly                 ← 月度缓存清理
    ├── run_patents_annual          ← 年度专利采集（5月，巨潮年报全量）
    ├── run_patents_quarterly       ← 季度专利增量（1/4/7/10月，Google Patents）
    ├── run_company_profile         ← 月度公司概况采集（F10 经营范围/主营构成/经营评述）
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
| `run_events_patents` | 工作日 | `stock_announcement_em` + `stock_patent_crawler` + `aggregate_patent_data` | 公告事件采集 + 专利挖掘采集 + 专利含金量聚合（轻量 API/计算，非关键链） |
| `refresh_composite_universe` | 工作日 | `composite.dynamic_universe` | 综合指标股票池刷新（开盘前） |
| `refresh_ai_kb` | 工作日 | `quantia.lib.ai.retrieval.indexer` | AI 知识库 FULLTEXT 索引刷新 |
| `run_fund_holding_batch` | 工作日 | `fetch_fund_holding_job.py --full-if-enabled` | 基金重仓股「全覆盖（方案C）」每日分层分批增量采集；方案C 关闭时秒级空跑（轻量，非关键链） |
| `run_workdayly` | 工作日 | — | 编排器：串行调用 fetch→公告与专利→kline→analysis→paper→report_alert→综合指标池→AI知识库→基金重仓股全覆盖 |
| `run_monthly` | 每月1日 | — | 智能清理退市/除权缓存 + 财务数据更新 |
| `run_patents_annual` | 每年5月 | `fetch_patent_data.py` | 全市场近5年年报专利全量采集（主源） |
| `run_patents_quarterly` | 季度首月 | `fetch_patent_data.py --source google_patents` | Google Patents 增量补充 IPC/引用/趋势/PCT（备份源，脚本自判 1/4/7/10 月） |
| `run_company_profile` | 每月 | `fetch_company_profile_job.py` | F10 公司概况（经营范围/主营构成/经营评述）采集；主源东方财富，连续失败30次确认被封则整体切换同花顺备源续采（仅定性、无占比），备源再连续失败30次则中止；两源各自熔断；慢 job，含增量跳过(80天) |
| `run_fund_profile_holding` | 每月 | `fetch_fund_profile_job.py` + `fetch_fund_holding_job.py` | F10 基金画像（规模/经理/评级）+ F12 季度前十大重仓股采集 |
| `backfill_fund_all.sh` | 手动（首次） | `fetch_fund_nav_history_job.py` + `fetch_fund_profile_job.py` + `fetch_fund_holding_job.py` + `analysis_fund_score_job.py` | 基金中心一键全量铺底：按依赖顺序 F8 净值→F10 画像→F12 重仓→F7 评分；失败不阻断；TopN 可经环境覆盖（默认 200，`QUANTIA_FUND_NAV_TOPN=0` 为全量回填）。仅服务器本地跑，日常增量仍由上述定时任务维护 |

---

## 公司概况与主营构成采集

`run_company_profile` 是公司详情页「公司概况 / 主营构成」的数据来源，落库到
`cn_stock_company_profile`，供 `/quantia/api/stock/business` 读取后展示经营范围、经营评述、按行业/产品/地区拆分的主营收入占比与毛利率。

任务采用东方财富 F10 作为主源：可提供定量主营构成。若东方财富连续失败 30 次，脚本会整体切换到同花顺备源续采；同花顺仅提供经营范围、主营业务等定性信息，不提供收入占比和毛利率，因此不会编造 `mainop` 定量数据，也不会覆盖已有东方财富定量记录。

该任务属于慢 job，默认 `QUANTIA_COMPANY_PROFILE_MAX_SECONDS=5400` 软预算、`QUANTIA_COMPANY_PROFILE_TIMEOUT=5700` 硬超时。软预算到点会在个股之间干净自停，剩余股票留待下月或手动补跑；建议单独放在月度 day3 盘后窗口，避开月初财务数据和基金慢任务。

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

# 全量回填：TopN=0 表示不限桶内数量，回填所有非货币型/非债券型基金净值历史
# （让全部基金都能算出夏普/最大回撤/同行业对标，耗时与 API 配额较大，仅首次或扩容时跑）
# ⚠ 首次全量铺底建议把 F8/F10/F12/F7 的超时都放大到 50000：
#   F8 全量约 5~12h（串行单线程，每只基金 2 次东财请求 + 限速 sleep，瓶颈在 API 而非 DB）；
#   F10/F12 也会在 1h 默认超时内被截断，F7 依赖 F8 完成，必须一起放大，避免“前一阶段半成品、后一阶段照常跑”。
QUANTIA_FUND_NAV_TOPN=0 QUANTIA_FUND_NAV_TIMEOUT=50000 \
  QUANTIA_FUND_PROFILE_TIMEOUT=50000 QUANTIA_FUND_HOLDING_TIMEOUT=50000 \
  QUANTIA_FUND_SCORE_TIMEOUT=50000 \
  nohup bash cron/backfill_fund_all.sh &
```

> **断点续跑不省 API 时间**：`save_fund_nav_history` 是「先抓后过滤」——2 次请求在「跳过已有最新 nav_date」判断之前就发了。
> 中途崩溃重跑，已入库基金仍会重新请求一遍（仅不重复写库），API 层面相当于从头再来。建议一次性 `nohup` 后台跑完。
>
> **想提速只能上并发，别做「本地缓存→批量入库」**：DB 写走 localhost socket、且 `insert_db_from_df` 已是整段批量，只占单只耗时 ~6%；
> 真正的 94% 在网络请求 + 限速 sleep，唯一有效手段是有限并发抓取（如线程池 4 路可压到 ~3h）。1.6G 小内存下并发数勿超 4~8，否则易 OOM / 被东财限流。

#### 加速方案 A：服务器本地并发

`fetch_fund_nav_history_job.py` 支持 `--workers N`（或环境变量 `QUANTIA_FUND_NAV_WORKERS`，默认 1=串行保持原行为）。
**并发用多进程而非多线程**（akshare 依赖 py_mini_racer/V8，V8 isolate 非线程安全，多线程会 `partition_address_space Check failed` 崩溃）；
抓取在子进程并行（占 94% 耗时），写库仍在主进程串行：

```bash
# 服务器本地全量回填，4 进程并发抓取（~11h → ~3h）；写库仍走 localhost socket，安全
QUANTIA_FUND_NAV_TOPN=0 QUANTIA_FUND_NAV_WORKERS=4 \
  nohup python quantia/job/fetch_fund_nav_history_job.py &
```

> 每个抓取进程约数百 MB（各自加载 akshare+pandas）。1.6G 小内存服务器 workers 勿超 2~4，否则易 OOM 或被东财限流；16G 本机可放心设 8~12。

#### 加速方案 B：本地高内存机抓取 → 文件搬运 → 服务器本地入库（最快，推荐）

利用本地 16G 电脑高并发抓取，落盘成文件后 `scp` 到服务器，服务器只读文件增量入库。
**抓取与写库彻底解耦**：本地不写任何库、服务器不发任何 API，既拿到本地并发速度，又不违反「绝不经公网批量写远程小内存库」铁律。

```bash
# ① 本地（16G）：仅并发抓取 + 落盘，不连任何库写入
#    .csv.gz 零额外依赖（pandas 按扩展名自动 gzip）；.parquet 更紧凑但需 pip install pyarrow
#    本机连不上远程 MySQL 时加 QUANTIA_FUND_NAV_OFFLINE=1，跳过连库选 code、改用 akshare 排行
QUANTIA_FUND_NAV_OFFLINE=1 python quantia/job/fetch_fund_nav_history_job.py --export nav_dump.csv.gz --workers 12

# 各类型 Top-600 + 仅近 5 年净值 + 拆成 4 个分片文件（规避 GitHub 单文件 100MB 限制）
QUANTIA_FUND_NAV_OFFLINE=1 python quantia/job/fetch_fund_nav_history_job.py \
  --export nav_dump.csv.gz --workers 12 --topn 600 --years 5 --parts 4

# ② 搬运到服务器（百万行 csv.gz 仅几十 MB，秒级传输）
scp nav_dump.csv.gz root@<server>:/root/Quantia/        # 单文件
scp nav_dump.part*.csv.gz root@<server>:/root/Quantia/  # 分片（--parts N 产物）

# ③ 服务器（1.6G）：只读文件增量 upsert 到 localhost MySQL，不发任何 API
cd /root/Quantia
python quantia/job/fetch_fund_nav_history_job.py --import nav_dump.csv.gz
python quantia/job/fetch_fund_nav_history_job.py --import nav_dump.part01.csv.gz
python quantia/job/fetch_fund_nav_history_job.py --import nav_dump.part02.csv.gz
python quantia/job/fetch_fund_nav_history_job.py --import nav_dump.part03.csv.gz
python quantia/job/fetch_fund_nav_history_job.py --import nav_dump.part04.csv.gz
#   --import 自动发现同名分片 nav_dump.part*.csv.gz；也可传目录或通配符（逐文件入库省内存）
```
##### 验证导入数据库是否成功sql:
SELECT COUNT(*) AS total_rows,COUNT(DISTINCT code) AS fund_count,MIN(nav_date) AS min_date,MAX(nav_date) AS max_date FROM cn_fund_nav_history;
##### 再看最近是否有写入（按你导入的是近 5 年数据）：

SELECT nav_date, COUNT(*) AS rows_per_day FROM cn_fund_nav_history WHERE nav_date >= CURDATE() - INTERVAL 7 DAY GROUP BY nav_date ORDER BY nav_date DESC;

##### 用任务状态表确认“导入任务”记录
导入脚本会写任务跟踪，查最近几条：
SELECT * FROM cn_job_status WHERE job_name = 'run_fund_nav_history' ORDER BY id DESC LIMIT 5;
> 导出选项：`--topn N` 各 fund_type 桶 Top-N（默认读 `QUANTIA_FUND_NAV_TOPN`，未设为 200）；
> `--years N` 仅保留最近 N 年净值（成立不足者保留全部）；`--parts N` 按基金均分成 N 个分片文件，
> 规避 GitHub 单文件 100MB 限制（整只基金不跨文件，便于按基金增量入库）。
> 选 code 一律排除**货币型、债券型**（货币型无净值走势，债券型波动小、回测意义有限）。

> `--export` 仍会读一次 `cn_fund_rank` 选 code（轻量 SELECT，公网可承受）；如需完全离线可显式传 code 列表。
> 入库走 `_write_hist_incremental`：按 code 过滤「库中已有最新 nav_date 之后」的增量行 + `ON DUPLICATE KEY UPDATE`，
> **增量、幂等、可重跑**，非全量覆盖。

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
| `record_stage "标签" 退出码 [warn] [耗时秒]` | 累积一个阶段的成功/失败/警告结果与耗时；省略耗时时自动取 `run_job`/`run_sub` 导出的 `LAST_STAGE_DURATION` |
| `print_stage_summary` | 在日志末尾输出各阶段成功/失败明细 + 统计 + 耗时降序排行 + 总耗时 |
| `stop_services_for_memory "原因"` | 停止 nginx + Quantia Web 服务，释放内存 |
| `start_services_after_memory` | 恢复之前停止的服务 |

> **任务汇总（`record_stage` + `print_stage_summary`）**：多任务脚本在末尾汇总各子任务结果，便于运维核对与按耗时编排。
> 已接入：`run_workdayly`（8 阶段统一汇总）、`run_fetch`（数据获取 + 基金净值回填）、`run_analysis`（数据分析 + 基金评分）。
> 单任务脚本（`run_kline_cache` / `run_paper_trading`）的 `run_job` 行已含「✓/✗ + 耗时」，无需额外汇总。
> `record_stage` 第三参数为 `warn` 时，失败记为 ⚠ 警告（非关键，不计入失败数）——用于基金回填/评分等非阻断子任务。

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

**交易日检测（T vs T+1）**：
- `run_fetch` / `run_kline_cache` 在 **T 日盘后**运行，使用 `check_trade_day`（校验运行当天是否为交易日）。
- `run_analysis` / `run_paper_trading` / `run_report_alert` 在 **T+1 凌晨**运行（DOW 2-6，含**周六**凌晨处理**周五**数据），
  使用 `check_trade_day_t1`（校验「最近一个交易日」是否在 N 天内）。
  > 修复缺陷：原先这三个 T+1 任务复用 `check_trade_day`，周六凌晨因 `is_trade_date(周六)=False` 被误跳过，
  > 导致**每个周五的策略选股/模拟交易/报告永久缺失**。改用 `check_trade_day_t1` 后周六槽位可正常处理周五数据。

**`run_workdayly` 编排器**：适合单机一键运行，串行调用全部工作日阶段，含自动 OOM 防护。
**它是所有工作日任务的超集**——单机部署只需调度这一个脚本即可覆盖每日全链路：

| Phase | 内容 | 入口 | 服务停止 | 失败计入 |
|-------|------|------|----------|----------|
| 1 | 数据获取 | `run_fetch`（`fetch_daily_job.py`） | 否 | ✓ 关键 |
| 1.5 | 公告与专利采集（公告→专利采集→专利聚合） | `run_events_patents` | 否 | ⚠ 非关键 |
| 2 | K线缓存更新（内存密集型） | `run_kline_cache` | **是** | ✓ 关键 |
| 3 | 数据分析（内存密集型） | `run_analysis` | **是** | ✓ 关键 |
| 4 | 模拟交易 | `run_paper_trading` | 否（已恢复） | ✓ 关键 |
| 5 | AI报告+评分预警 | `run_report_alert` | 否 | ✓ 关键 |
| 6 | 综合指标股票池刷新 | `refresh_composite_universe` | 否 | ⚠ 非关键 |
| 7 | AI知识库索引刷新 | `refresh_ai_kb` | 否 | ⚠ 非关键 |
| 8 | 基金重仓股全覆盖分批 | `run_fund_holding_batch` | 否 | ⚠ 非关键 |

> **失败计数口径**：仅 5 个关键数据阶段（1/2/3/4/5）计入 `FAILED`，对应结束语 `✗ (X/5 阶段异常)`。
> Phase 1.5/6/7/8 为轻量非关键链（公告/专利/综合指标池/AI 知识库/基金重仓股），异常仅记 ⚠ 警告，不计入失败数。
> 末尾 `print_stage_summary` 会输出全部阶段的成功/失败/警告明细 + 耗时降序排行 + 阶段总耗时。

> Phase 2/3 执行前自动停止 nginx + Quantia Web 释放内存，完成后恢复（`trap` 兜底）。
> Phase 1.5/6/7/8 为轻量 API/计算，异常仅记 ⚠ 警告不计入失败阶段数。
> 阶段失败统计以 5 个关键 `run_sub` 阶段（1/2/3/4/5）为分母。

### 容错与超时（编排模式不会因单阶段卡死而阻塞后续）

编排模式是**单进程严格串行**，因此必须保证「任一阶段出错或卡死都不会阻塞/中断后续阶段」。设计要点：

- **不级联退出**：`run_workdayly` 无 `set -e`；每个 `run_sub` 在**独立子进程**中运行，子脚本内部的
  `exit`（如非交易日 `check_trade_day` 的 `exit 0`）只结束该子进程，不会冒泡终止编排器。
  每个 Phase 都 `rc=$?` 捕获后继续，单阶段失败仅记 ✗/⚠，后续 Phase 照常执行。
- **不无限阻塞**：所有 Python 作业均带**超时兜底**（`timeout` 直接包裹 python，超时发 SIGTERM 可靠杀掉
  python 子进程并释放内存，避免 1.6G 机 OOM）。超时退出码 124 记为失败/警告，编排器继续下一阶段。
  默认值（秒，均可经 `.env` 覆盖）：

  | 阶段 | 超时变量 | 默认 |
  |------|----------|------|
  | 数据获取 fetch_daily | `QUANTIA_FETCH_TIMEOUT` | 7200 |
  | 基金净值回填 | `QUANTIA_FUND_NAV_TIMEOUT` | 3600 |
  | 公告采集 | `QUANTIA_ANNOUNCE_TIMEOUT` | 1800 |
  | 专利采集 | `QUANTIA_PATENT_CRAWL_TIMEOUT` | 3600 |
  | 专利聚合 | `QUANTIA_PATENT_AGG_TIMEOUT` | 1800 |
  | K线缓存 | `QUANTIA_KLINE_TIMEOUT` | 21600 |
  | 数据分析（含回测，最长 ~2h） | `QUANTIA_ANALYSIS_TIMEOUT` | 14400 |
  | 基金综合评分 | `QUANTIA_FUND_SCORE_TIMEOUT` | 1800 |
  | 模拟交易 | `QUANTIA_PAPER_TIMEOUT` | 3600 |
  | AI报告+评分预警（LLM 调用） | `QUANTIA_REPORT_TIMEOUT` | 7200 |
  | 综合指标股票池 | `QUANTIA_COMPOSITE_TIMEOUT` | 1800 |
  | AI知识库索引 | `QUANTIA_AIKB_TIMEOUT` | 1800 |
  | 基金重仓股全覆盖分批软预算 | `QUANTIA_FUND_HOLDING_BATCH_SECONDS` | 3000 |
  | 基金重仓股全覆盖分批硬超时 | `QUANTIA_FUND_HOLDING_BATCH_TIMEOUT` | 3300 |
  | 公司概况采集软预算 | `QUANTIA_COMPANY_PROFILE_MAX_SECONDS` | 5400 |
  | 公司概况采集硬超时 | `QUANTIA_COMPANY_PROFILE_TIMEOUT` | 5700 |

- **超时值取舍原则**：超时是「防卡死」安全网而非 SLA，必须 ≥ 任务理论最坏耗时（避免截断正常运行）。
  各值已按真实规模核算：fetch/kline ~2h（5000 标的，2× 文档 20-60min）、analysis 4h（含回测最长 ~2h）、
  AI报告 2h（每只 4 轮 × 60s LLM + 工具 ≈ 8min，×10 只 ≈ 80min 上限）；纯本地计算类（公告聚合/基金评分/
  综合指标池/AI知识库）实测分钟级，给 30min 已是 3~300× 余量。内存密集的 kline/analysis 因停服期间运行，
  不设过长超时以免拖长服务停机；AI报告处于链路末端（服务已恢复），放宽到 2h 无副作用。

- **退出码透传**：关键子脚本（`run_fetch`/`run_kline_cache`/`run_analysis`/`run_paper_trading`/
  `run_report_alert`）以**关键作业的退出码**退出，确保编排器 `FAILED/5` 计数与真实失败一致；
  各脚本内附的非关键作业（基金净值/评分等）失败不改写主退出码。

---

## Crontab 配置

> **两种部署模式，二选一**（见文末[「拆分模式 vs 编排模式」](#拆分模式-vs-编排模式如何选)对比）：
> - **拆分模式**：每个阶段一条独立 cron，失败隔离、可分机、可单独重试；多机/大内存推荐。
> - **编排模式**：只调度 `run_workdayly` 一条，严格串行、单一内存峰值、不漏子任务；单机/小内存（1.6G）推荐。

### 方式一：裸机拆分模式

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

# 公告事件 + 专利采集聚合（轻量 API/计算；fetch 主跑后执行，独立锁不阻塞 fetch 重试）
45 18 * * 1-5  flock -xn /tmp/quantia_events.lock   /root/Quantia/cron/cron.workdayly/run_events_patents

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

# 基金重仓股全覆盖每日分批（仅前端开启方案C 时生效，否则秒级空跑；盘后空档，独立锁）
0  16 * * 1-5  flock -xn /tmp/quantia_fund_holding.lock /root/Quantia/cron/cron.workdayly/run_fund_holding_batch

# === 月度任务：月初夜间 + 盘后慢任务窗口，彼此错峰 ===
# 季度专利增量（每月 1 日触发，脚本自判仅 1/4/7/10 月实际执行）
0   0 1 * *    flock -xn /tmp/quantia_patents.lock /root/Quantia/cron/cron.monthly/run_patents_quarterly

# 月度缓存清理 + 财务数据更新（慢 job，给足到 04:00 的缓冲）
30  1 1 * *    flock -xn /tmp/quantia_monthly.lock /root/Quantia/cron/cron.monthly/run_monthly

# 年度专利采集（5 月底，年报披露窗口结束后；全市场最近 5 年年报）
30  2 25 5 *   flock -xn /tmp/quantia_patents.lock /root/Quantia/cron/cron.monthly/run_patents_annual

# 场外基金画像 + 重仓股月度采集（F10/F12，慢 job）
# 放在 day2 盘后空档 15:30，彻底避开夜间重任务窗口（kline 23:00 / analysis 04:00 / paper 05:30）
30  15 2 * *   flock -xn /tmp/quantia_fund.lock /root/Quantia/cron/cron.monthly/run_fund_profile_holding

# 公司概况 + 主营构成月度采集（F10 经营范围/主营构成/经营评述，慢 job）
# 放在 day3 盘后空档，避开 day1 财务/月度清理与 day2 基金慢任务；数据供公司概况卡片展示主营结构占比
30  15 3 * *   flock -xn /tmp/quantia_company_profile.lock /root/Quantia/cron/cron.monthly/run_company_profile
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

### 方式二：裸机编排模式（单机 / 小内存推荐）

`run_workdayly` 一条即覆盖全部工作日阶段（fetch→公告专利→kline→analysis→paper→report→综合指标池→AI知识库），
严格串行、单一内存峰值、不会漏掉任何子任务。盘中快照与月度任务仍单独调度：

```bash
crontab -e

# === quantia crontab (orchestration mode) ===
# 盘中行情快照（与拆分模式相同）
30  9 * * 1-5  flock -xn /tmp/quantia_hourly.lock /root/Quantia/cron/cron.hourly/run_hourly
30 10 * * 1-5  flock -xn /tmp/quantia_hourly.lock /root/Quantia/cron/cron.hourly/run_hourly
25 11 * * 1-5  flock -xn /tmp/quantia_hourly.lock /root/Quantia/cron/cron.hourly/run_hourly
30 13 * * 1-5  flock -xn /tmp/quantia_hourly.lock /root/Quantia/cron/cron.hourly/run_hourly
30 14 * * 1-5  flock -xn /tmp/quantia_hourly.lock /root/Quantia/cron/cron.hourly/run_hourly
55 14 * * 1-5  flock -xn /tmp/quantia_hourly.lock /root/Quantia/cron/cron.hourly/run_hourly

# 每日完整链路（T 日 18:10 一键串行；内部 check_trade_day 自动跳过非交易日）
# run_workdayly 当晚串行跑完 fetch→公告专利→kline→analysis→paper→report→综合指标池→AI知识库→基金重仓股全覆盖
10 18 * * 1-5  flock -xn /tmp/quantia_workdayly.lock /root/Quantia/cron/cron.workdayly/run_workdayly

# === 月度任务（与拆分模式完全相同，错峰至月初夜间 / 盘后 15:30）===
0   0 1 * *    flock -xn /tmp/quantia_patents.lock /root/Quantia/cron/cron.monthly/run_patents_quarterly
30  1 1 * *    flock -xn /tmp/quantia_monthly.lock /root/Quantia/cron/cron.monthly/run_monthly
30  2 25 5 *   flock -xn /tmp/quantia_patents.lock /root/Quantia/cron/cron.monthly/run_patents_annual
30 15 2 * *    flock -xn /tmp/quantia_fund.lock    /root/Quantia/cron/cron.monthly/run_fund_profile_holding
30 15 3 * *    flock -xn /tmp/quantia_company_profile.lock /root/Quantia/cron/cron.monthly/run_company_profile
```

> **编排模式注意**：
> - `run_workdayly` 内部 Phase 3/4/5（analysis/paper/report）按 **T 日当晚连续**跑完，不再拆成 T+1 凌晨。
>   单机一晚跑完全链路；若担心 18:10 启动后总时长过长（回测最长 ~2h），可把启动改到 17:00 或盘后更早。
> - 编排模式下**不要再单独调度** `run_fetch`/`run_kline_cache`/`run_analysis`/`run_paper_trading`/
>   `run_report_alert`/`run_events_patents`/`refresh_composite_universe`/`refresh_ai_kb`/`run_fund_holding_batch`——它们已被 `run_workdayly` 接管，
>   重复调度会与编排实例抢锁/抢内存。
> - 服务停启由 `run_workdayly` 统一管理（仅 Phase 2/3 停服），子脚本经 `QUANTIA_NO_SERVICE_STOP=1` 抑制重复停服。

### 拆分模式 vs 编排模式（如何选）

两种模式**覆盖的任务完全一致**（`run_workdayly` 是拆分模式全部工作日任务的超集），区别只在调度粒度：

| 维度 | 拆分模式（多条 cron） | 编排模式（`run_workdayly` 一条） |
|------|----------------------|--------------------------------|
| 内存峰值 | 靠错峰**时间**保证不重叠；极端尾延仍有轻微重叠风险 | **严格串行**，任意时刻仅一个阶段，单一峰值，最稳 |
| 失败隔离 | 一个阶段挂不影响其它 cron（独立进程） | 一个阶段挂不阻断后续（脚本内 `&&`-free），但同进程 |
| 重试粒度 | 可单独重跑某阶段（如只重跑 analysis） | 只能整体重跑 run_workdayly |
| 分机部署 | ✅ 可把 fetch / 分析分到不同机器 | ❌ 绑定单机 |
| 漏任务风险 | ⚠ 需人工保证 crontab 列全（曾漏 events/patents） | ✅ 子任务写死在脚本里，不会漏 |
| 时间利用 | analysis/paper/report 放 T+1 凌晨，错峰更从容 | 当晚连续跑完，总时长受回测尾延影响 |
| 日志可观测 | 各阶段散在 workdayly.log，无统一汇总 | 末尾 `print_stage_summary` 统一成功/失败/耗时汇总 |
| 运维复杂度 | crontab 行多，改动面大 | 一行搞定，最简单 |

**选型建议**：
- **1.6G 小内存单机 / 想要"一键 + 不漏任务 + 统一汇总日志"** → **编排模式**（`run_workdayly`）。
- **多机或大内存、需要按阶段独立重试 / 分机扩展** → **拆分模式**，但务必保证 crontab 把
  `run_events_patents` / `refresh_composite_universe` / `refresh_ai_kb` / `run_fund_holding_batch` 都列上（本次修复前拆分模式漏了 events/patents）。
- 两种模式**不可混用**：选定一种，避免同一阶段被重复调度而抢锁/抢内存。

### Docker 容器

Docker 定时任务在 Dockerfile 中自动配置，时间表与裸机相同，脚本路径为 `/etc/cron.*`。
新增 `_common.sh` 由 `COPY cron/_common.sh /etc/cron/_common.sh` 部署到容器中。

---

## 手动执行

```bash
# 执行每小时任务
./cron/cron.hourly/run_hourly

# 执行完整每日任务（fetch → 公告专利 → kline_cache → analysis → paper → report → 综合指标池 → AI知识库 → 基金重仓股全覆盖）
./cron/cron.workdayly/run_workdayly

# 仅执行数据获取
./cron/cron.workdayly/run_fetch

# 仅执行公告事件 + 专利采集聚合
./cron/cron.workdayly/run_events_patents

# 仅执行基金重仓股全覆盖分批（仅方案C 开启时生效，否则秒级空跑）
./cron/cron.workdayly/run_fund_holding_batch

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

# 月度公司概况 + 主营构成采集（东方财富主源，同花顺定性备源）
./cron/cron.monthly/run_company_profile

# 月度基金画像 + 重仓股采集
./cron/cron.monthly/run_fund_profile_holding
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
| `workdayly.log` | `run_fetch` / `run_events_patents` / `run_kline_cache` / `run_analysis` / `run_paper_trading` / `run_workdayly`（含公告与专利采集聚合 Phase 1.5） |
| `report_alert.log` | `run_report_alert` |
| `refresh_composite_universe.log` | `refresh_composite_universe` |
| `refresh_ai_kb.log` | `refresh_ai_kb` |
| `monthly.log` | `run_monthly` |
| `patents_annual.log` | `run_patents_annual` |
| `patents_quarterly.log` | `run_patents_quarterly` |
| `company_profile.log` | `run_company_profile` |
| `fund_profile_holding.log` | `run_fund_profile_holding` |
| `fund_holding_batch.log` | `run_fund_holding_batch` |

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
| `QUANTIA_KLINE_CACHE_WORKERS` | 3 | K线缓存更新并发数 |
| `QUANTIA_FUND_NAV_WORKERS` | 1 | F8 基金净值历史并发**进程**数（1=串行；akshare 依赖 py_mini_racer/V8 非线程安全，故用多进程而非多线程；每进程约数百 MB，16G 本机可设 8~12，1.6G 服务器勿超 2~4） |
| `QUANTIA_FUND_NAV_OFFLINE` | 0 | 设为 `1` 时 `--export` 跳过数据库选 code、直接用 akshare 全市场排行（本机连不上 MySQL 时用，省去连库超时重试） |
| `QUANTIA_FUND_NAV_YEARS` | 0 | `--export` 默认仅保留最近 N 年净值（成立不足者保留全部）；0=不限。命令行 `--years` 优先 |
| `QUANTIA_FUND_PROFILE_TOPN` | 200 | 基金画像铺底 TopN，`backfill_fund_all.sh` 使用 |
| `QUANTIA_FUND_HOLDING_TOPN` | 200 | 基金重仓股铺底 TopN，`backfill_fund_all.sh` 使用 |
| `QUANTIA_BACKTEST_OUTER_WORKERS` | 1 | 回测外层并发（按表） |
| `QUANTIA_BACKTEST_INNER_WORKERS` | 2 | 回测内层并发（按股票） |
| `QUANTIA_STOP_SERVICES` | nginx | 内存密集任务前停止的系统服务（空格分隔） |
| `QUANTIA_NO_SERVICE_STOP` | 0 | 设为 `1` 禁用自动停止/恢复服务 |
| `QUANTIA_SETTLEMENT_HOUR` | 18 | API 数据结算时间（小时） |
| `QUANTIA_FETCH_TIMEOUT` | 7200 | `run_fetch` 超时秒数（默认 2 小时） |
| `QUANTIA_FUND_NAV_TIMEOUT` | 3600 | 基金净值历史回填超时秒数 |
| `QUANTIA_ANNOUNCE_TIMEOUT` | 1800 | 公告采集超时秒数 |
| `QUANTIA_PATENT_CRAWL_TIMEOUT` | 3600 | 专利采集超时秒数 |
| `QUANTIA_PATENT_AGG_TIMEOUT` | 1800 | 专利聚合超时秒数 |
| `QUANTIA_KLINE_TIMEOUT` | 21600 | K线缓存增量更新超时秒数 |
| `QUANTIA_ANALYSIS_TIMEOUT` | 14400 | 数据分析超时秒数 |
| `QUANTIA_FUND_SCORE_TIMEOUT` | 1800 | 基金综合评分超时秒数 |
| `QUANTIA_PAPER_TIMEOUT` | 3600 | 模拟交易超时秒数 |
| `QUANTIA_REPORT_TIMEOUT` | 7200 | AI 报告 + 评分预警超时秒数；调大分析股票数时需同步放宽 |
| `QUANTIA_COMPOSITE_TIMEOUT` | 1800 | 综合指标股票池刷新超时秒数 |
| `QUANTIA_AIKB_TIMEOUT` | 1800 | AI 知识库索引刷新超时秒数 |
| `QUANTIA_FUND_PROFILE_TIMEOUT` | 3600 | 基金画像月度采集超时秒数 |
| `QUANTIA_FUND_HOLDING_MAX_SECONDS` | 3300 | 基金重仓股月度采集软预算；到点在基金之间干净自停 |
| `QUANTIA_FUND_HOLDING_TIMEOUT` | 3600 | 基金重仓股月度采集硬超时秒数 |
| `QUANTIA_FUND_HOLDING_BATCH_SECONDS` | 3000 | 基金重仓股每日全覆盖分批软预算 |
| `QUANTIA_FUND_HOLDING_BATCH_TIMEOUT` | 3300 | 基金重仓股每日全覆盖分批硬超时秒数 |
| `QUANTIA_COMPANY_PROFILE_MAX_SECONDS` | 5400 | 公司概况月度采集软预算；到点在个股之间干净自停，适合下月续跑 |
| `QUANTIA_COMPANY_PROFILE_TIMEOUT` | 5700 | 公司概况月度采集硬超时秒数，略高于软预算作兜底 |
| `PYTHON_BIN` | 自动探测 | Python 解释器路径（**所有** cron 脚本统一使用）。不设时 `init_env` 优先用 `$PROJECT_ROOT/.venv/bin/python`（存在时），否则回退系统 `python3`；显式设置（env / `.env`）始终优先。刻意不自动探测 `quantia_env`（现网 web 以系统 python3 运行，cron 默认与之一致）；如需用 quantia_env 请在 `.env` 显式设 `PYTHON_BIN` |

可通过 `.env` 文件或系统环境变量设置，`_common.sh` 的 `init_env` 会自动加载 `.env` 文件。

---

## OOM 防护（低内存服务器）

1.6GB 服务器同时运行 MySQL + nginx + Quantia Web + Python 分析任务时容易 OOM。
`run_fetch` / `run_kline_cache` / `run_analysis` 在独立调度时会自动停止 nginx 和 Quantia Web 服务，
完成后自动恢复；`run_workdayly` 编排模式会统一接管服务生命周期，仅在 Phase 2/3 前停服并在 Phase 3 后恢复。

### 工作流程

**`run_workdayly` 编排模式**（推荐）：
```
◆ Phase 1: run_fetch（由编排器设置 QUANTIA_NO_SERVICE_STOP=1，不单独停服）
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
