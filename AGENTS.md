# AGENTS.md — Quantia 量化选股系统

Quantitative A-stock / ETF analysis platform. Tornado backend + Vue 3 frontend, MySQL storage, multi-source crawlers (EastMoney → Tencent → Sina), TA-Lib indicators, Backtrader backtests, paper trading.

For background, prefer linking over re-reading:
- Architecture, data-source strategy, module map: [PROJECT_DOCUMENTATION.md](PROJECT_DOCUMENTATION.md)
- Setup / common commands: [QUICKSTART.md](QUICKSTART.md)
- API surface: [document/API_REFERENCE.md](document/API_REFERENCE.md)
- DB schema: [document/database_schema.md](document/database_schema.md)
- Domain plans (read on demand): [document/](document/)

## Build & test

Python (run from repo root, venv activated):
- Install: `pip install -r requirements.txt`
- Full suite: `pytest -q` (≈1700+ tests; some require MySQL — see env below)
- Single test: `pytest tests/test_<name>.py -q`
- Note: [tests/conftest.py](tests/conftest.py) already ignores script-style files (`test_bugfixes.py`, `test_data_fixes.py`, `test_data_source_consistency.py`, `test_pagination.py`, `test_sector_api.py`). Don't add them back to runs.
- Smoke verifiers (top-level `_verify_*.py`) are runnable scripts, not pytest tests.

Frontend (in [quantia/fontWeb](quantia/fontWeb)):
- `npm install` then `npm run dev` (or `npm run dev:mock`)
- Type-check + build: `npm run build` — 等价于 `vue-tsc --noEmit && vite build`。**绝不**用 `npx vite build` / `vite build` 单跳来绕过 `vue-tsc`（等同 `--no-verify`）。TS6133 / TS2xxx 必须真正修掉，禁止 bypass。
- Unit tests: `npm test`
- Production: copy `quantia/fontWeb/dist/**` into [quantia/web/static](quantia/web/static) — Tornado serves from there. Vite build alone is not enough.

Web service:
- Start: [quantia/bin/run_web.sh](quantia/bin/run_web.sh) / `run_web.bat` → http://localhost:9988
- After ANY backend Python change, restart `web_service.py` (long-running process; modules are cached). Remote: `/root/Quantia/quantia/bin/restart_web.sh`.
- **Restart 必须配验证**：commit / push 不等于生效。后端改动后必须 (a) 重启 `web_service.py`，(b) 黑盒调用一个被改动的接口（`Invoke-RestMethod` / curl）确认 200 + 预期字段后再向用户报告完成。Phase 7 commit 后没重启 → `custom_93` 接口仍返回旧白名单 "未知 strategy" 就是教训。

Env: copy `.env` template; required keys are `QUANTIA_DB_HOST/QUANTIA_DB_USER/QUANTIA_DB_PASSWORD/QUANTIA_DB_DATABASE`. AI provider keys (`QUANTIA_AI_PROVIDER_*`) are only needed for AI features. `QUANTIA_LOCAL_MODE=1` enables higher concurrency.

## 开发工作流期望（验证优先，必须遵循）

修 bug / 审查改动 / 看日志类请求默认走"验证优先"工作流（详见 skill `diagnose-verify-fix`）：

1. **先证实问题真实存在 + 定位根因**，再动手——禁止按用户描述表面补丁。无法复现就如实说明、不要瞎改。
2. **多方案择优**：≥2 个方案时列优缺点对比，主动评估"是否有更优解"，选最优最合理的（用户高频要求）。
3. **回归自检**：每次改完显式回答"是否引入新 bug / 不符合预期行为"，跑相关 `pytest` + 黑盒接口验证后才声明完成。
4. **文档/Phase 一致性**：按 `document/*.md` 当前 phase 推进，改动与需求文档核对。
5. 生产根因诊断常基于阿里云 `115.29.213.22`（库 `instockdb`）的 `quantia/log/*.log`；分析时仍守管道分离（规则 1）。

## Architecture rules (do not violate)

1. **Fetch / Analysis / Web separation** — only the Fetch pipeline ([quantia/job/fetch_*](quantia/job), `quantia/core/stockfetch.py`, `quantia/core/crawling/`) may call external APIs. Analysis and Web pipelines must read from MySQL + `cache/hist/` only. Never add `requests`/`akshare` calls inside `quantia/web/*Handler.py` or analysis jobs.
2. **Table metadata** lives in [quantia/core/tablestructure.py](quantia/core/tablestructure.py). Do **not** import `quantia.lib.tablestructure` for stock metadata — it is not the source of truth.
3. **Index codes** (`000300`, `399xxx`, …) in backtests must go through `load_benchmark_data`, not `load_stock_data`. Routing them to `load_stock_data` makes EastMoney `secid=0.000300` → HTTP 500.
4. **Index cache invariant** — `cache/hist/index/{code}.gzip.pickle` holds the *full* history. `quantia/core/backtest/data_feed.py::_save_index_cache` MERGES new rows (drop_duplicates by date, keep='last'). Never blind-overwrite with a date-bounded slice. Source of truth for repair: `akshare.stock_zh_index_daily(symbol='sh000300')`.
5. **Dynamic universe strategies** (fundamental selectors) discover candidates after preload. Backtest and paper-trading `history` / `attribute_history` paths require lazy K-line loading + normalized daily timestamps for order price lookup.
6. **Paper-trading display truth**: latest `cn_stock_paper_nav` row is authoritative for current asset/cash/profit. `cn_stock_paper_trading.current_value/current_cash` may be stale. Use `initial_cash` (not first NAV) as full-life baseline for metrics/charts.
7. **Validate-first data access** — All SQL queries (in AI tools, handlers, jobs) must validate referenced columns against the real DB schema **before** execution. The `sql_query` tool uses `INFORMATION_SCHEMA.COLUMNS` to pre-check; other tools use explicit column lists in their SELECT statements. Never assume `tablestructure.py` definitions are deployed (e.g. `concept` column is defined but doesn't exist in prod DB). Field mappings must be verified, not guessed.
8. **Route registration parity** — Every frontend API call (`quantia/fontWeb/src/api/` + `src/lib/`) must have a corresponding handler registered in `web_service.py`. Before adding a frontend API call, verify the route exists. Before removing a handler, verify no frontend code depends on it.

## DB write hygiene

- All `df.to_sql` writes must pass `chunksize=500` (constant `_DB_INSERT_CHUNKSIZE` in [quantia/lib/database.py](quantia/lib/database.py)). Without it, `_mysql_upsert` builds one giant INSERT and OOM-kills the 1.6 GB server. (Regression history: commit bba51731.)
- MySQL/PyMySQL rejects NaN/inf (`inf can not be used with MySQL`). Sanitize at the source AND rely on the guard in `quantia/lib/database.py` before write. Do not silently fillna in handlers.
- Strategy ratio math: keep finite at compute time — don't push the burden onto the DB layer.

## Frontend / template sync

- Built-in strategy source changes are synced to DB by `portfolioBacktestHandler.sync_strategy_templates_to_db()` on Web service startup, and by `POST /quantia/api/strategy/sync_templates`. Algo list "导入示例策略" uses the same endpoint.
- Sync tracks `template_id`, `template_hash`, `user_modified`. Frontend-saved built-ins are protected from overwrite when their code differs from official templates.
- If you change a template's code, restart the web service so sync runs (or hit the sync endpoint) — otherwise frontend edit / backtest pages keep the old code.

## Frontend mobile adaptation（新增/改动前端页面必须遵循）

所有新增或改动的前端页面（`quantia/fontWeb/src/views/**`、`src/components/**`）**必须**做移动端适配，禁止只在桌面宽度下能用。统一基础设施：

- **断点真相源**：`src/composables/useResponsive.ts`（`isMobile` < 768，xs<576 / sm<768 / md<992 / lg/xl/xxl）+ SCSS mixin `src/styles/_breakpoints.scss`。**禁止**裸写 `@media (max-width: 768px)`，新增媒体查询走 mixin（`@include sm-down` / `@include mobile-only` 等）或对齐 useResponsive 断点值（767.98px）。
- **宽表格（`el-table` ≥ 5 列）必须提供移动端卡片视图**：桌面 `<el-table v-if="!isMobile">`，移动端 `<div v-if="isMobile" class="xxx-card-list">` 渲染卡片。参考实现：[paper-trading/index.vue](quantia/fontWeb/src/views/paper-trading/index.vue)（`.pt-card`）、[attention/index.vue](quantia/fontWeb/src/views/attention/index.vue)（`.att-card`）。卡片结构：头部（代码/名称/关键标签）+ body（`grid-template-columns: 1fr 1fr` 字段对）+ ops（操作行）。
- **弹窗 `el-dialog`**：移动端用 `:fullscreen="isMobile"` 或 `:width="isMobile ? '100vw' : '...'"` + `:top="isMobile ? '0' : '...'"`。
- **ECharts**：移动端缩小 `grid.left/right` 内边距与轴字号（`isMobile.value ? 38 : 60` 等），参考 [indicator/index.vue](quantia/fontWeb/src/views/indicator/index.vue)。
- **视口高度**用 `100dvh` 而非 `100vh`（iOS/Android 地址栏折叠）。
- **零桌面端回归**：所有移动样式必须包在断点内，桌面表现不变。`localStorage.setItem('quantia.forceDesktop','1')` 可强制桌面回滚验证。
- **完整未适配清单**见 [document/mobile_adaptation_plan.md](document/mobile_adaptation_plan.md)；改动相邻页面时顺手适配。已知高优先级未适配宽表页：`strategy/StrategyConfig.vue`、`stock/report-history.vue`、`settings/im-commands.vue`、`fund/index.vue`、`backtest/history.vue`、`backtest/dashboard.vue` 及多数 `settings/*`。


## Memory efficiency

Streaming analysis ([quantia/job/streaming_analysis_job.py]) processes 4900+ stocks with <100 MB peak memory by single-pass iteration. Don't materialize full universe DataFrames in handlers or jobs.

## Key directories

| Path | Purpose |
| --- | --- |
| [quantia/core/stockfetch.py](quantia/core/stockfetch.py) | Multi-source data scheduler + incremental cache |
| [quantia/core/crawling/](quantia/core/crawling) | Per-source HTTP crawlers (EastMoney/Tencent/Sina) |
| [quantia/core/strategy/](quantia/core/strategy) | 14 built-in selection strategies |
| [quantia/core/indicator/](quantia/core/indicator), [quantia/core/pattern/](quantia/core/pattern), [quantia/core/kline/](quantia/core/kline) | TA-Lib indicators, 61 K-line patterns, K-line utils |
| [quantia/core/backtest/](quantia/core/backtest) | Backtrader feeds, runners, metrics |
| [quantia/core/composite/](quantia/core/composite) | Phase 9 自定义综合指标 (normalizers, hard-rule AST sandbox, risk simulator, dynamic universe) |
| [quantia/job/](quantia/job) | Daily / hourly batch jobs (fetch + analysis pipelines) |
| [quantia/web/](quantia/web) | Tornado handlers + Jinja templates + static assets |
| [quantia/paper_trading/](quantia/paper_trading), [quantia/live/](quantia/live), [quantia/trade/](quantia/trade) | Paper / live / brokerage trading |
| [quantia/ai_decision/](quantia/ai_decision) | AI assistant + multi-provider LLM integration |
| [quantia/auth/](quantia/auth), [quantia/notification/](quantia/notification), [quantia/im/](quantia/im) | Auth, notifications, DingTalk/IM |
| [cron/](cron) | Cron entry scripts (hourly / workdayly / monthly) |

## Subagent / scripted command safety（必须遵循）

调用 `execution_subagent` 或在终端跑脚本时，**严禁**让其执行可倒退用户未提交编辑的命令：

- 禁止：`git checkout <path>` / `git restore <path>` / `git reset --hard` / `git clean -fd` / 任意 `git stash` 后不恢复 / `git rm` 含未提交改动的文件。
- 禁止用 `vite build` / 跳过 lint 等方式"修复"构建失败——把真实错误回报给主代理，由主代理修代码。
- 调用 subagent 前，prompt 里要明确写 **Hard rules**：`DO NOT run git checkout/reset/restore/clean. If npm run build fails, paste the verbatim error and STOP.`
- 调用 subagent 后，若它报告"通过"，要校验 `git status` 没有意外的 "checked out" / "reverted"。曾发生 subagent 为绕过 TS6133 静默 `git checkout src/views/verify/optimize.vue` 倒退本会话编辑的事故。

## Custom-strategy parity（前后端必须遵循）

买卖点优化 / 策略对比 / 策略融合 / 因子实验室 / AI 决策 等"验证中心"页面同时支持内置 `cn_stock_strategy_*` 与用户自定义策略 `custom_<id>`。**每个**后端 handler 与前端 tab 都必须显式处理自定义分支：

- 后端：在 `_handle` 入口判断 `strategy.startswith('custom_')`，路由到 `_handle_custom`，**不要**走 `_resolve_strategy_meta` 白名单（会被拒为"未知 strategy"）。
- 前端：v-if 不要写 `!isCustomStrategy && ...` 把图表 / 数据直接隐藏掉（Phase 7→8 反复发生）。如果该 tab 暂无自定义数据，让条件只判断数据本身（`data.length > 0`），用占位文案给提示。
- 自定义策略的统计口径必须与内置一致：
  - 滚动 NAV 夏普用**非重叠**采样 `nav[::d]`（与 `_calc_rolling_nav_analysis` 一致），`len(samples) < 3` 时返回 None；不要用重叠窗口（会把 std 严重低估，sharpe 飙到 20+ / 胜率 100%）。
  - 同步过滤 `(date, value)` 数组，不要先 filter 一个再按下标切另一个 — 必然日期错位。
  - 样本外验证用真实 NAV 70/30 切，禁止用固定系数（`*0.86`、`*0.83`、`*0.94`、`*0.88`）造伪 train/test 数据误导用户。
- 新增 tab / 新数据流时，要把"内置 vs 自定义"两条路径都跑一遍验证，不能只测一侧。

## ECharts in tabs

切换 tab 后 v-show 重新出现的 ECharts 容器尺寸可能为 0：tab change 时调 `chart.resize()`，或在 `nextTick` 后再 `init`。详见 commit e6d6268。

## 策略融合 v2（verifyFusionHandler）

`POST /quantia/api/verify/fusion` 双版本路由：请求体带 `version: 2` 走 v2 真五维（tech/fund/flow/sent/custom）× 4 模式（weighted_score / vote / condition_tree / rotation）；否则走 v1 旧 `strategy_names` 交并集。详见 [document/API_REFERENCE.md](document/API_REFERENCE.md#策略融合验证-v2)。

不可违反：
- **fund/flow items 必须是白名单表达式** —— `<col>_<op>_<val>`，col 来自 `_FUND_ALLOWED_COLS` / `_FLOW_ALLOWED_COLS`，op ∈ {lt,gt,lte,gte,eq}。直接拼 SQL 是注入面。`_parse_item_expr` 是唯一入口。
- **Shapley 守恒** —— `_shapley_real` 返回值满足 $\sum_k \phi_k = v(N)$（v(∅)=0）。如果你修改 `_fuse_subset_signals` / `_evaluate` 让任一子集回退到默认 sharpe，等式会破，单元测试 `test_shapley_real_three_dims_sums_to_fusion_minus_empty` 会立刻挂。
- **子集权重必须重归一化** —— `_fuse_subset_signals` 对子集内 enabled dim 把 weight 拉回到合计 100；`vote_threshold` clip 到子集大小，且对 `None` 兼容（`spec.get('vote_threshold') or 2`）。
- **Shapley 8s 超时降级** —— `_shapley_real` 用 `time.monotonic()` 控预算；超时返回 `(None, True, {'reason':'timeout', ...})`，`_handle_v2` 必须 fallback 到 `_shapley_naive` 并写入 warning `"Shapley 真值计算超时（已评估 X/Y 子集），降级为快速估算"`。
- **Overlap co_occurrence 是扁平 N×N list**（含对角与对称对，jaccard 对角 = 1.0），不是上三角。前端 heatmap 用 `enabledKeys.indexOf(row.a)` 索引到矩阵。
- **测试数据**：单元用 `_make_signal_df(codes, dates)` / `_make_rate_df(codes, dates, rate_value)` 合成；端到端 mock 用 `mock.patch.object(vfh, '_load_dim_signals')` + `_load_rate_df`，不打 DB。
- **黑盒 smoke 用 2026-03-01 ~ 2026-05-14**（系统时钟已到 2026，2025 区间在生产 DB 里是空集）。

## Destructive file ops（必须遵循）

**严禁**未经用户确认就执行以下操作（无论用什么工具：terminal / execution_subagent / 文件系统调用 / git）：

1. 删除任何**目录**（`Remove-Item -Recurse` / `rm -rf` / `rmdir /s` / `git rm -r` / `shutil.rmtree`）。
2. **批量**删除多个文件（≥ 2 个文件，或使用 glob/通配 `*.xxx`、`-Recurse`、`find -delete`）。
3. 清空 `cache/` / `quantia/log/` / `quantia/cache/` / `quantia/web/static/` 等目录内容。
4. `git clean -fd` / `git clean -fdx`。
5. 截断或覆写非自己刚创建的二进制 / 数据文件（`.gzip.pickle`、`.parquet`、`.db`、`.sqlite`）。

**正确流程**：

1. 列出**完整待删文件清单**（路径 + 大小或最后修改时间），即使数量很多也要展示全部或前 20 项 + 总数。
2. 用 `vscode_askQuestions` 询问，至少提供：`全部删除` / `保留<某子集>` / `不删除`，**禁止默认勾选删除**。
3. 用户明确同意后才执行；执行后报告实际删除条数与剩余。
4. 删除前先确认不在 git 未提交改动里（`git status` 一遍），有未提交内容就先提示用户。

允许直接进行的安全例外（无需询问）：

- 删除**当前任务内自己刚创建**且明显是失败产物 / 临时文件的**单个**文件（如 build 失败的半成品）。
- 移动文件（`mv` / `Rename-Item`）——但跨目录或覆盖已存在文件仍需提示。
- 工具本身的临时文件（如 `__pycache__/` 自动重生）不主动删除；用户明确说"清一下 __pycache__"再删。

任何"我以为是安全的清理"都不是例外：宁可多问一次。

## Commit & push workflow（必须遵循）

完成一项用户请求（修复 bug / 新功能 / 重构）并通过自检（lint / 测试 / 构建）后：

1. **必须主动询问**用户是否要 `git add -A && git commit && git push`，使用 `vscode_askQuestions` 工具，至少包含两个问题：
   - 提交范围：`全部一起提交` / `只提交后端（不含 dist）` / `拆分多个语义化 commit` / `先不提交`
   - 是否 push：`立即 push origin <当前分支>` / `仅本地 commit`
2. 询问前先 `git status --short` + `git log --oneline -3` 让用户看到上下文。
3. **敏感信息提交前拦截**：任何 commit / push 前，必须检查待提交 diff（先看 `git diff`，暂存后再看 `git diff --cached`）是否包含真实敏感信息，并在提交前替换为占位符，禁止把真实值推到远端：
  - IP / 主机：真实公网 IP、云服务器 IP、内网固定 IP、数据库/Redis/SSH 主机地址 → `<HOST>` / `<DB_HOST>` / `<REDIS_HOST>` / `<REMOTE_HOST>`。示例文档 IP 可用 `203.0.113.10`、`198.51.100.10`、`192.0.2.10` 等 RFC 5737 保留地址。
  - 密码 / Token / API Key / Secret / Cookie / Authorization：任何真实凭证 → `<PASSWORD>` / `<API_KEY>` / `<TOKEN>` / `<SECRET>` / `<COOKIE>`。
  - DSN / URL / 连接串：如 `mysql://user:pass@host:3306/db`、`redis://:pass@host:6379/0`、带 key 的 webhook URL → 用占位符重写用户名、密码、host 与 token。
  - 私钥 / 证书 / 会话文件：`BEGIN PRIVATE KEY`、`.pem`、`.key`、导出的 cookie/session 等不得提交；若必须提供模板，只提交 `.example` 且内容为占位符。
  - 发现敏感信息后先修改文件为占位符，再重新运行 diff 检查；若敏感值已经被 commit / push，立即停止并提示需要历史重写，不要继续普通 push。
4. commit message 用中文，第一行 `<type>: <概要>`（type ∈ fix/feat/chore/docs/refactor/test/perf），后续段落分组列出前端/后端/测试/文档/构建变更，简明扼要。
5. **绝不**使用 `--force` / `--no-verify` / `git reset --hard` / 删除分支等危险操作，除非用户在当前对话里明确要求。
6. 仅本机改动（venv / cache / log / .env）不必提示提交；纯讨论 / 纯查询任务也不必提示。
7. 若 `git status` 没有变化，跳过本流程。

例外：用户明确说"先不要提交"或在本对话里已经回答过"先本地 commit"，本次回合不再追问。

## Pitfalls quick list

- Don't add API calls to handlers / analysis jobs (rule 1).
- Don't import `quantia.lib.tablestructure` for stock metadata (rule 2).
- Don't route index codes through `load_stock_data` (rule 3).
- Don't `to_pickle` blind-overwrite the index cache (rule 4).
- Don't omit `chunksize=500` in `to_sql`.
- Don't forget to restart the web service after backend edits — and **verify with a black-box endpoint call** before declaring done.
- Don't forget to copy Vite `dist/` into `quantia/web/static` for prod.
- Don't `vite build` past a `vue-tsc` error — fix the TS error.
- Don't let subagents run `git checkout / reset / restore / clean` (see Subagent safety).
- Don't gate custom-strategy tabs behind `!isCustomStrategy` (see Custom-strategy parity).
- Don't compute Sharpe / win-rate on overlapping rolling windows — use non-overlapping `nav[::d]`, return null when `len(samples) < 3`.
- Don't fabricate OOS train/test metrics with fixed multipliers — split the real NAV.
- Don't forget to ask about commit & push when a user-facing change is finished (see Commit workflow).
- Don't surface-patch a reported bug — first prove it's real and find the root cause, then evaluate alternatives and pick the optimal fix, then regression-check (see skill `diagnose-verify-fix`).
- Don't delete directories or batch-delete files without listing them and getting user confirmation first (see Destructive file ops).
- Hard-rule expressions (composite): AST sandbox blocks `__import__`, dunders, lambda, file ops, exec/eval, attribute access on dicts. Don't try to "improve" the sandbox by relaxing these.
- Fusion v2 fund/flow items must pass `_parse_item_expr` whitelist — don't accept raw SQL fragments. Shapley sum invariant must hold (`∑φ_k = v(N)`); subset weights must be renormalized to 100 in `_fuse_subset_signals`. Use `2026-03~05` for black-box smoke.
- Don't use vague table/column references in AI prompts — always provide exact column lists + negative constraints ("**没有** X 列"). LLM will hallucinate `concept`/`main_inflow`/`net_flow` if not explicitly told they don't exist.
- Don't assume `tablestructure.py` columns exist in prod DB — validate against `INFORMATION_SCHEMA.COLUMNS` (rule 7).
- Don't add frontend API calls without verifying the route exists in `web_service.py` (rule 8).
