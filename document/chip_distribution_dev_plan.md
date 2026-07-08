# 筹码分布（历史）数据开发方案

> 状态：已实现（计算模块 + 表结构 + 流式接入 + 回填脚本 + 前端页面 + turnover DB 兜底 + 单测），待生产跑批验证。换手率来源见 §2.1（缓存 + DB 双保险，本地陈旧缓存也能算）。
> 归属阶段：数据分析管道扩展（Analysis pipeline）
> 关联规则：AGENTS.md 架构规则 1（Fetch/Analysis/Web 分离）、规则 7（列校验）、DB 写库规范（chunksize=500 / NaN 清洗）

## 1. 背景与目标

用户诉求：获取"各股票筹码分布"以及"历史筹码分布"数据，并优先使用免费数据源。

现状盘点（代码已存在的部分）：

- [quantia/core/kline/cyq.py](../quantia/core/kline/cyq.py)：Python 版 CYQ 筹码分布算法（三角形分布 + 换手率衰减）。
- [quantia/core/kline/cyq.js](../quantia/core/kline/cyq.js)：前端交互版算法。
- [quantia/core/kline/visualization.py](../quantia/core/kline/visualization.py)：K 线图右侧已实时渲染筹码分布（悬停某根 K 线时计算）。
- [quantia/core/crawling/stock_chip_race.py](../quantia/core/crawling/stock_chip_race.py)：**早盘/尾盘抢筹**，是集合竞价/尾盘资金异动榜，**不是**筹码分布，本方案不涉及。

缺口：项目**没有**把每只股票"每日筹码分布指标"落库，因此无法做筹码相关的选股、排序、回测、历史查询。

目标：新增"每日筹码分布指标"数据层，使系统可以：

1. 查询任意股票任意历史交易日的筹码分布核心指标（获利比例、平均成本、成本区间、集中度）。
2. 基于筹码指标做选股 / 排序 / 回测。
3. 全程零外部 API（分析管道只读本地 K 线缓存 + DB），符合架构规则 1。

## 2. 数据源决策

| 来源 | 免费 | 历史能力 | 结论 |
| --- | --- | --- | --- |
| 本地 K 线缓存 + 项目自带 CYQ 算法 | 是 | 可算全历史 | **主方案（采用）** |
| AkShare `stock_cyq_em`（东财 K 线派生） | 是（零 key） | 默认仅近 90 天，批量易限流 | 仅作**离线抽样校验**参考 |
| 通达信抢筹接口 | 是但不稳定 | 非筹码分布 | 不采用 |
| TuShare Pro 筹码接口 | 需积分/权限 | 结构化 | 不算真正免费，不采用 |
| Wind/Choice/同花顺数据服务 | 付费 | 完整 | 成本高，不采用 |

**关键判断**：`ak.stock_cyq_em` 本质也是"东财 K 线 + CYQ 算法"派生（本地 akshare 1.17.75 源码内嵌了与 cyq.js 同源的 JS 计算），并非交易所真实持仓账户分布。既然算法同源，直接用本地 K 线缓存自算即可，既免于批量打外网被限流，又能覆盖全历史，且天然满足 Fetch/Analysis 分离。

> 说明：筹码分布是**估算**（基于日 OHLC + 换手率的三角形分布衰减模型），不是真实账户级持仓。文档、页面与字段命名都应体现"估算"属性，避免误导。

### 2.1 数据前提：换手率 `turnover` 来源（缓存 + DB 双保险，已实现）

CYQ 衰减模型的每根 K 线权重来自**换手率** `turnover`。turnover 有两个来源，分析管道均**只读本地/DB、绝不发外网**（符合规则 1）：

**来源① K 线缓存**（`cache/hist/**/*qfq.gzip.pickle` 的 `turnover` 列，由 Fetch 管道写入）：

- `_fetch_from_sources` 把新拉取数据列名按位对齐 `CN_STOCK_HIST_DATA`（东财日线第 11 列 `换手率`→`turnover`；腾讯同，新浪不提供则为 0），`stock_hist_cache_incremental` 增量 `pd.concat([旧缓存, 新数据])` 后 turnover 列被保留。
- **每日 fetch 追加的新行都带 turnover**；历史旧行若在"turnover 入列"之前抓取则为 `NaN`。

**来源② DB 每日快照**（`cn_stock_spot` / `cn_etf_spot` 的 `turnoverrate` 列）：

- 经远程库实测（`instockdb`）：`cn_stock_spot` 每日约 4930 只、`turnoverrate` **0 个 NULL**、约 93% 为正值，历史 2026-02-03 至今，单只约 95 个交易日。数据完整、每日增长。
- `quantia/core/stockfetch.py::backfill_turnover_from_spot(code, hist_data)` 在 compute 前**按需**从这两张表按 `date` 补齐 turnover：仅当缓存近窗口有效换手率样本 `< min_bars(20)` 时才查库；缓存已够则零查询直接返回（生产热路径零开销）。A 股查 `cn_stock_spot`，查不到再回退 `cn_etf_spot`。

**因此本地陈旧缓存（旧最简格式 `[date,open,high,low,close,volume,amount]`，实测 0/400 含 turnover）也能算出真实筹码**——由来源② 兜底。已在 `streaming_analysis_job`（`chip_input = stf.backfill_turnover_from_spot(...)`）与 `backfill_chip_distribution` 两条路径接入。

**安全降级**：来源①②均补不到 turnover 时，`total_chips<=0` → `compute_chip_metrics` 返回 `None` → 不落该行（不产生错误数据、不抛异常）。

**上线前置检查（可选）**：DB `cn_stock_spot.turnoverrate` 有 ~95 个交易日即可支撑 CYQ 窗口（`min_bars=20`）；随每日 fetch 覆盖度自然增长。**不要**在分析管道里发外网补 turnover（违反规则 1）——来源永远是 Fetch 管道写入的缓存或 DB 快照。


## 3. 算法（与现有 cyq.py / 东财同源）

对给定股票，取"最近 `lookback` 个交易日、截止到目标日 T"的窗口，按**从旧到新**遍历：

1. 价格网格：`min_price = 窗口最低价`，`max_price = 窗口最高价`，`accuracy = max(0.01, (max-min)/(factor-1))`，`factor` 个价位桶。
2. 每根 K 线：`avg = (open+high+low+close)/4`，`turnover_rate = min(1, turnover/100)`。
   - 先对全部桶做衰减：`x[n] *= (1 - turnover_rate)`。
   - 再把 `turnover_rate` 的新筹码按"三角形分布"叠加到 `[low, high]` 对应桶（峰在 `avg`）。一字板（high==low）特殊处理。
3. 遍历完得到 `xdata`（各价位筹码量）与 `total_chips = sum(xdata)`。
4. 指标：
   - 平均成本 `avg_cost` = 累计筹码达到 50% 处的价格。
   - 获利比例 `winner_rate` = 成本 ≤ 当前收盘价的筹码占比。
   - 90% / 70% 成本区间 `[low, high]` 与集中度 `concentration = (high-low)/(high+low)`。

与既有 `cyq.py` 的差异（**有意为之**）：

- `cyq.py::calc(index)` 用 `end = index - range + 1`、`start = end - tradingdays`，即计算"当前 K 线之前 range 根"的旧分布，服务于图表悬停的"前视投影"。
- 本方案计算"**截止到 T 当日**"的分布，语义与东财 `stock_cyq_em` 最后一行一致，更适合选股/回测。因此**不复用** `cyq.py` 的窗口口径，而是抽取其核心叠加数学，新建一个"截止当日"的批量函数。

参数（可环境变量覆盖）：

- `QUANTIA_CYQ_LOOKBACK`：窗口长度，默认 `120`（约半年，换手衰减已弱化更早筹码的影响）。
- `QUANTIA_CYQ_FACTOR`：价位桶数，默认 `150`（与 cyq.js 一致）。
- `QUANTIA_CYQ_MIN_BARS`：窗口内最少 K 线数，默认 `20`，不足则跳过（新股/次新噪声大）。

## 4. 数据表设计

新增表 `cn_stock_chip_distribution`（cn：筹码分布），**只存标量指标**，主键 `(date, code)`。

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| date | DATE | 交易日 |
| code | VARCHAR(6) | 代码 |
| name | VARCHAR(20) | 名称 |
| close | FLOAT | 当日收盘价 |
| winner_rate | FLOAT | 获利比例(%) |
| avg_cost | FLOAT | 平均成本 |
| cost_90_low | FLOAT | 90% 成本-低 |
| cost_90_high | FLOAT | 90% 成本-高 |
| concentration_90 | FLOAT | 90% 集中度 |
| cost_70_low | FLOAT | 70% 成本-低 |
| cost_70_high | FLOAT | 70% 成本-高 |
| concentration_70 | FLOAT | 70% 集中度 |

**不存**完整 150 桶分布数组。原因：5000 股 × 250 交易日 × 150 桶 ≈ 1.9 亿行/年，得不偿失。完整曲线继续由 [visualization.py](../quantia/core/kline/visualization.py) 在查看个股时实时计算。

行量级：约 4900 行/交易日，一年约 120 万行，10 个 FLOAT 列，完全可控。

## 5. 代码改动清单

### 5.1 新增计算模块 `quantia/core/kline/chip_distribution.py`

- `compute_chip_metrics(hist_data, lookback=None, factor=None, min_bars=None, close_override=None) -> dict | None`
  - 入参 `hist_data`：`read_stock_hist_from_cache` 返回的 DataFrame（含 date/open/high/low/close/turnover）。
  - 取尾部 `lookback` 根，`turnover` 强制 `pd.to_numeric(errors='coerce').fillna(0)`。
  - `total_chips <= 0`（停牌/换手全 0）→ 返回 `None`（不落该行）。
  - 返回 dict：`winner_rate, avg_cost, cost_90_low, cost_90_high, concentration_90, cost_70_low, cost_70_high, concentration_70, close`。
  - **所有返回值保证有限**：任何 `NaN/inf` 就地置 `None`（不把清洗甩给 DB 层，符合 DB 规范）。
- 抽取 `cyq.py` 的三角形叠加数学为内部私有函数，两处保持一致（后续可让 cyq.py 也复用，本期不强改以免回归图表）。

### 5.2 表结构注册 `quantia/core/tablestructure.py`

- 新增 `TABLE_CN_STOCK_CHIP_DISTRIBUTION = {'name': 'cn_stock_chip_distribution', 'cn': '筹码分布', 'columns': {...}}`，列顺序 = 外键三列 + 上表标量列。
- 在 `FIELD_FORMAT_MAP` 增加格式化：`winner_rate/concentration_* → pct`，`avg_cost/cost_* → price`。

### 5.3 接入流式分析 `quantia/job/streaming_analysis_job.py`

- 顶部 `import quantia.core.kline.chip_distribution as cyqd`。
- `streaming_analysis()` 起始处：`_ensure_table_schema(tbs.TABLE_CN_STOCK_CHIP_DISTRIBUTION['name'], tbs.TABLE_CN_STOCK_CHIP_DISTRIBUTION['columns'])`。
- 结果缓冲：新增 `chip_results = {}`。
- `_process_one_stock` 内，**复用已读的 `hist_data`**（零额外 I/O），计算 `chip = cyqd.compute_chip_metrics(hist_data)`；非 None 则 `result['chip'] = chip`。
  - 与指标一致：不因 `stale` 跳过（个股详情展示需要），date 写 `date_str`。
- 主循环把 `result['chip']` 收进 `chip_results[stock]`。
- `_flush_results` 增参 `chip_results`，新增 `_write_chip_results(chip_results, date_str, tables_cleaned)`（镜像 `_write_indicator_results`：`get_field_types` 提供 cols_type、`insert_db_from_df(..., "\`date\`,\`code\`")`、`chunksize=500` 由 `insert_db_from_df` 内部保证）。
- 每批 flush 后 `chip_results.clear()`。

> 内存：仅新增 ~10 个 float / 只，峰值影响可忽略，维持 <100 MB 单遍设计。

### 5.4 一次性回填 `quantia/job/backfill_chip_distribution.py`（可选）

- 目的：立即产出历史序列，而非等每日任务自然累积。
- 逻辑：逐股读全量缓存，对最近 `N` 个交易日（默认 `QUANTIA_CYQ_BACKFILL_DAYS=90`）逐日滑动窗口计算并落库。
- **时间预算**：`QUANTIA_CYQ_BACKFILL_MAX_SECONDS`（默认 0=不限），到预算在"股票之间"干净自停，剩余下次续跑（参考基金重仓股全覆盖模式）。
- 写库同样 `chunksize=500` + NaN 清洗；按 `(date,code)` 去重覆盖。
- 该脚本属分析管道：只读缓存 + 写库，**零 API**。

### 5.5 Web/前端展示（已实现）

本期已交付前端页面，**复用现有通用数据表基础设施，零新增 handler / 零新增 Vue 组件**：

- **后端路由**：无需新增。通用接口 `GET /quantia/api_data?name=cn_stock_chip_distribution&date=...&page=...`（[dataTableHandler.py](../quantia/web/dataTableHandler.py) `GetStockDataHandler`，已在 [web_service.py](../quantia/web/web_service.py) 注册，满足规则 8）。
- **数据表注册**：[singleton_stock_web_module_data.py](../quantia/core/singleton_stock_web_module_data.py) 新增一条 `web_module_data`（type=股票指标数据，ico=fa fa-pie-chart，`column_names=get_field_cns(..., format_hints=FIELD_FORMAT_MAP)`，`order_by cdatetime DESC`）。**handler 以此白名单校验表名**，注册后接口即可访问。
- **前端路由/菜单**：[router/index.ts](../quantia/fontWeb/src/router/index.ts) 在「技术指标」分组下新增 `path: 'chip-distribution'`，`component: StockData.vue`，`meta: { title: '筹码分布', tableName: 'cn_stock_chip_distribution', isRealtime: false }`。侧边栏由路由 `meta.title` 自动生成菜单项。
- **移动端适配**：通用视图 [StockData.vue](../quantia/fontWeb/src/views/stock/StockData.vue) **已内置** `useResponsive` 桌面 `el-table` + 移动端 `.card-list` 卡片视图（`mobileCardColumns`）、`100dvh` 高度、分页移动端简化布局，天然满足 AGENTS.md 移动端规范，无需另写卡片。
- **列说明 tooltip**：[columnTooltips.ts](../quantia/fontWeb/src/utils/columnTooltips.ts) `commonColumnDescriptions` 增加 `winner_rate/avg_cost/cost_9x/cost_7x/concentration_*` 中文释义。
- **完整分布曲线**：个股 K 线图右侧筹码峰形图由 [visualization.py](../quantia/core/kline/visualization.py) 实时渲染（既有能力，非本方案改动）。本页提供的是**可筛选/排序/翻页的历史标量指标**。
- **部署**：改前端后 `npm run build`（含 `vue-tsc`）→ copy `dist/**` 到 [quantia/web/static](../quantia/web/static)；改后端后重启 `web_service.py`（restart-and-deploy skill）。

## 6. 边界与异常处理

| 场景 | 处理 |
| --- | --- |
| 缓存缺失 / 空 | `_process_one_stock` 已 `skipped`，chip 自然不产出 |
| `turnover` 缺列/全 NaN | 强制 `fillna(0)` → `total_chips=0` → 返回 None，不落行 |
| 停牌（volume=0） | 换手 0 → total_chips 衰减为 0 → 跳过 |
| 窗口 K 线 < `min_bars` | 返回 None，跳过 |
| 一字板（high==low） | 沿用 cyq.py 特殊分支 |
| 计算出 NaN/inf | 模块内置 None，绝不入库 |
| 旧表 schema 不符 | `_ensure_table_schema` 自动 DROP 重建（与指标表一致） |
| 除权（前复权缓存） | 缓存本就是 qfq，成本/价格口径自洽；文档标注为前复权成本 |

## 7. 开发步骤（顺序）

1. 新建 `chip_distribution.py`，实现 `compute_chip_metrics` + 私有叠加函数。
2. `tablestructure.py` 注册表 + 格式化。
3. 单元测试 `tests/test_chip_distribution.py`（见 §8）先行，红灯。
4. 让单测转绿。
5. 接入 `streaming_analysis_job.py`（buffer + flush + schema）。
6. 新建 `backfill_chip_distribution.py`。
7. `py_compile` 全量 + `pytest` 相关用例。
8. 本地/接口冒烟（见 §9）。
9. 更新本文件"状态"为已实现，按提交流程询问提交。

## 8. 测试计划（`tests/test_chip_distribution.py`）

纯函数、不打 DB、不联网：

- `test_basic_metrics_ranges`：构造上涨趋势合成 K 线，断言 `0 <= winner_rate <= 100`、`avg_cost` 落在 `[min_low, max_high]`、`cost_90_low <= cost_90_high`、`cost_70_*` 区间被 `cost_90_*` 包含。
- `test_all_profit_when_price_above_all_cost`：最新价显著高于历史 → `winner_rate` 接近 100。
- `test_all_loss_when_price_below_all_cost`：最新价显著低于历史 → `winner_rate` 接近 0。
- `test_zero_turnover_returns_none`：turnover 全 0 → 返回 None。
- `test_insufficient_bars_returns_none`：K 线数 < min_bars → None。
- `test_missing_turnover_column_returns_none`：无 turnover 列 → None（不抛异常）。
- `test_no_nan_inf_in_output`：所有返回值 `math.isfinite` 或 None。
- `test_one_word_board`：一字板（high==low）不崩溃、返回有限值。
- `test_concentration_monotonic`：窄幅横盘的集中度 < 大幅震荡的集中度。
- `test_streaming_wiring`（可选，mock）：`mock.patch` `read_stock_hist_from_cache` 与 `insert_db_from_df`，断言 `_write_chip_results` 被以正确表名/去重键调用。

## 9. 验证流程（黑盒）

1. `python -m py_compile quantia/core/kline/chip_distribution.py quantia/job/streaming_analysis_job.py quantia/job/backfill_chip_distribution.py`
2. `pytest tests/test_chip_distribution.py -q`
3. 本地跑一小批：临时对 5~10 只有缓存的股票调用 `compute_chip_metrics`，人工核对 `avg_cost` 与收盘价量级合理。
4. （可选）离线抽样校验：对 1~2 只票，联网 `ak.stock_cyq_em(symbol=...)` 取最后一行，与本地自算做**趋势/量级**比对（不要求逐位相等，算法窗口与复权口径有差异）。
5. 若接入生产：服务器 `git pull` → 重跑 `run_analysis`（或等次日 cron）→ 用 `SELECT COUNT(*), MIN(date), MAX(date) FROM cn_stock_chip_distribution` 确认落库，抽查几行数值。

## 10. 回滚

- 数据层为**新增**，不改动既有表与既有指标计算；回滚只需：还原 `streaming_analysis_job.py` 的接入片段 + 删除新表（可选）。新表不存在时其余管道零影响。

## 11. 明确不做（避免范围蔓延）

- 不批量调用 `ak.stock_cyq_em` 抓全市场（限流 + 仅近 90 天 + 违反规则 1）。
- 不存 150 桶完整分布数组。
- 不在 handler/analysis 里发起任何外部请求。
- 本期不交付前端页面（列为后续 Phase）。
