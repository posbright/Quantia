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

## Architecture rules (do not violate)

1. **Fetch / Analysis / Web separation** — only the Fetch pipeline ([quantia/job/fetch_*](quantia/job), `quantia/core/stockfetch.py`, `quantia/core/crawling/`) may call external APIs. Analysis and Web pipelines must read from MySQL + `cache/hist/` only. Never add `requests`/`akshare` calls inside `quantia/web/*Handler.py` or analysis jobs.
2. **Table metadata** lives in [quantia/core/tablestructure.py](quantia/core/tablestructure.py). Do **not** import `quantia.lib.tablestructure` for stock metadata — it is not the source of truth.
3. **Index codes** (`000300`, `399xxx`, …) in backtests must go through `load_benchmark_data`, not `load_stock_data`. Routing them to `load_stock_data` makes EastMoney `secid=0.000300` → HTTP 500.
4. **Index cache invariant** — `cache/hist/index/{code}.gzip.pickle` holds the *full* history. `quantia/core/backtest/data_feed.py::_save_index_cache` MERGES new rows (drop_duplicates by date, keep='last'). Never blind-overwrite with a date-bounded slice. Source of truth for repair: `akshare.stock_zh_index_daily(symbol='sh000300')`.
5. **Dynamic universe strategies** (fundamental selectors) discover candidates after preload. Backtest and paper-trading `history` / `attribute_history` paths require lazy K-line loading + normalized daily timestamps for order price lookup.
6. **Paper-trading display truth**: latest `cn_stock_paper_nav` row is authoritative for current asset/cash/profit. `cn_stock_paper_trading.current_value/current_cash` may be stale. Use `initial_cash` (not first NAV) as full-life baseline for metrics/charts.

## DB write hygiene

- All `df.to_sql` writes must pass `chunksize=500` (constant `_DB_INSERT_CHUNKSIZE` in [quantia/lib/database.py](quantia/lib/database.py)). Without it, `_mysql_upsert` builds one giant INSERT and OOM-kills the 1.6 GB server. (Regression history: commit bba51731.)
- MySQL/PyMySQL rejects NaN/inf (`inf can not be used with MySQL`). Sanitize at the source AND rely on the guard in `quantia/lib/database.py` before write. Do not silently fillna in handlers.
- Strategy ratio math: keep finite at compute time — don't push the burden onto the DB layer.

## Frontend / template sync

- Built-in strategy source changes are synced to DB by `portfolioBacktestHandler.sync_strategy_templates_to_db()` on Web service startup, and by `POST /quantia/api/strategy/sync_templates`. Algo list "导入示例策略" uses the same endpoint.
- Sync tracks `template_id`, `template_hash`, `user_modified`. Frontend-saved built-ins are protected from overwrite when their code differs from official templates.
- If you change a template's code, restart the web service so sync runs (or hit the sync endpoint) — otherwise frontend edit / backtest pages keep the old code.

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
3. commit message 用中文，第一行 `<type>: <概要>`（type ∈ fix/feat/chore/docs/refactor/test/perf），后续段落分组列出前端/后端/测试/文档/构建变更，简明扼要。
4. **绝不**使用 `--force` / `--no-verify` / `git reset --hard` / 删除分支等危险操作，除非用户在当前对话里明确要求。
5. 仅本机改动（venv / cache / log / .env）不必提示提交；纯讨论 / 纯查询任务也不必提示。
6. 若 `git status` 没有变化，跳过本流程。

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
- Don't delete directories or batch-delete files without listing them and getting user confirmation first (see Destructive file ops).
- Hard-rule expressions (composite): AST sandbox blocks `__import__`, dunders, lambda, file ops, exec/eval, attribute access on dicts. Don't try to "improve" the sandbox by relaxing these.
