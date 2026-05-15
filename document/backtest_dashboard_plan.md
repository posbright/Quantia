# 回测看板计划（对齐当前实现）

更新时间：2026-02-27

本文档用于记录“回测看板”功能的计划与实现对齐结果：哪些已实现、哪些按约束降级、哪些尚未实现但可作为后续迭代。

---

## 1. 目标与范围（v1）

### 目标
- 让回测汇总结果更“人性化”：跨策略对比、单策略明细、收益分布、时间序列、买入→卖出配对收益。
- 解决历史遗留的固定 `rate_1~rate_100` 展示不合理问题：用户可配置持有天数（horizons/checkpoints）。
- 页面跳转与关联更合理：汇总列表 → 看板，并支持 deep-link 直接定位到时间序列/明细。

### v1 范围边界
- 不做数据库宽表结构重构（继续复用 `rate_1~rate_100`）。
- 跨策略总览与时间序列优先基于 `cn_stock_backtest`（现有字段限制见“数据约束”）。
- UI 按“可用/清晰”优先：采用单页分区 + 表格为主，时间序列使用 ECharts 折线。

---

## 2. 已实现内容（v1）

### 2.1 后端：看板 API（Tornado）
- 模块：`quantia/web/backtestDashboardHandler.py`
- 路由注册：`quantia/web/web_service.py`

已提供 5 个接口：
1) `GET /quantia/api/backtest/dashboard/overview`
- 跨策略总览（基于 `cn_stock_backtest`）

2) `GET /quantia/api/backtest/dashboard/timeline`
- 时间序列：按信号日汇总的 `avg_rate_{h}`（基于 `cn_stock_backtest`）

3) `GET /quantia/api/backtest/dashboard/strategy_detail`
- 单策略明细：分页返回选股行，支持自定义 horizons（来自策略宽表 `rate_{h}`）

4) `GET /quantia/api/backtest/dashboard/distribution`
- 收益分布：按指定 horizon 的 `rate_{h}` 做分箱统计

5) `GET /quantia/api/backtest/dashboard/trade_pairs`
- 买入-卖出配对：买入来自策略/指标买入表；卖出来自 `cn_stock_indicators_sell`（buy_date 之后最早一次）；无卖点则按 `max_hold` 超时退出

### 2.2 后端：统一支持 start_date/end_date
所有看板 API 统一支持以下“区间优先级”：
- 若请求包含 `start_date` 或 `end_date`：使用显式日期区间（优先于 days）
- 否则：使用 `days`（最近 N 个交易日窗口）

日期格式支持：`YYYY-MM-DD` / `YYYYMMDD` / `YYYY/MM/DD` / `YYYY.MM.DD`

显式日期区间规则：
- 只传一个日期：视为单日区间（start=end）
- start > end：自动交换
- 区间跨度限制：自然日不超过 366 天（避免误传导致大查询）

响应里会返回：
- `date_range = { start, end, count }`
- 其中 `count` 为表内 `COUNT(DISTINCT date)`（显式区间下可能为 0）

### 2.3 前端：看板页 + 深链
- 页面：`quantia/fontWeb/src/views/backtest/dashboard.vue`
- 路由：`/backtest/dashboard`
- API client：`quantia/fontWeb/src/api/stock.ts`

页面结构（单页纵向分区）：
- 策略总览（表格）
- 策略时间序列（ECharts 折线）
- 策略明细（表格 + 分页）
- 收益分布（表格）
- 买入-卖出配对（表格 + 分页）

深链支持：
- `?strategy=xxx` 预选策略
- `?focus=overview|timeline|detail` 自动滚动定位
- `?days=...`（部分场景使用）
- `?timeline_days=...`（时间序列区间）
- `?metric=...`（总览排名指标 horizon）
- `?horizon=...`（时间序列 horizon）
- `?detail_days=...`、`?detail_horizons=1,3,5,10,...`（明细配置）

新增：全局日期区间选择
- 顶部新增“日期区间”daterange，可清空
- 若选择日期区间：所有请求使用 `start_date/end_date`，并禁用各区块的 `days` 输入
- 同时支持从 URL query 带入：`?start_date=20260101&end_date=20260201`

---

## 3. 参数约定（重点）

### 3.1 days vs start_date/end_date
- `start_date/end_date`：显式区间，优先级最高
- `days`：最近 N 个交易日窗口；仅在未传显式区间时生效

建议：
- 分享链接/复现问题时优先使用 `start_date/end_date`
- 快速浏览趋势时使用 `days`

### 3.2 horizons 的约束
- `cn_stock_backtest` 目前仅有：`avg_rate_1/3/5/10/20`
  - 因此 overview/timeline 的 horizon 仅支持 `[1,3,5,10,20]`
- 策略宽表：`rate_1~rate_100`
  - 因此 detail/distribution 的 horizon 支持 `1..100`

备注：若前端传入超过 100 的 horizon（例如 120），后端会过滤/截断（v1 不做扩表）。

---

## 4. 数据来源与口径说明（v1）

### 4.1 时间序列（timeline）
- 使用 `cn_stock_backtest` 的 `avg_rate_{h}`
- 语义："某日产生的信号集合，在 h 日后的平均收益"（按信号日聚合）
- v1 不做复利净值曲线、不做逐笔交易资金曲线

### 4.2 买入-卖出配对（trade_pairs）
- 买入信号：来自指定 strategy 的表（策略表或指标买入表）
- 卖出信号：来自 `cn_stock_indicators_sell`
- 配对规则：同 code 且 `sell_date > buy_date` 的最早 sell_date
- 无卖点：按 `max_hold` 选择超时退出日

---

## 5. 计划中的降级/未实现（当前状态）

以下为“原计划中提到，但当前实现降级或未实现”的典型项：

### 5.1 UI（降级）
- 原计划：多 Tab、更多图表（柱状图/排名/直方图等）
- 当前：单页分区 + 表格为主，仅时间序列使用折线图

### 5.2 统计项（未实现）
- 明细/总览额外统计：胜率排名、盈亏次数、中位数/分位数、极值、回撤等
- 当前：以接口返回的基础字段为主（rows/total 与简单聚合）

### 5.3 更复杂的日期筛选（部分实现）
- 已实现：`start_date/end_date` 显式区间 + `days` 窗口
- 未实现：更复杂的前端快捷区间按钮、按交易日历精确限制等（可选迭代）

---

## 6. 后续迭代建议（v1.1 / v2）

### v1.1（不改表，增强体验）
- 地址栏同步：当用户在看板页选择日期区间时，自动把 `start_date/end_date` 写入 URL query（便于复制分享）
- 分布图表化：把“收益分布表格”升级为 ECharts 直方图
- 明细统计增强：在 detail/distribution 接口返回中增加简单统计（count、均值、中位数、正收益占比等）

### v2（需要改表/改 job）
- 扩展 `cn_stock_backtest`：增加 `avg_rate_30/60/120` 等字段
- 同步更新 daily job 写入逻辑与数据库迁移脚本
- 让 overview/timeline 也能覆盖更长 horizon（与明细对齐）

---

## 7. 快速验证清单

后端：
- 显式区间：`/overview?start_date=2026-01-01&end_date=2026-02-01`
- days 窗口：`/overview?days=60`

前端：
- 打开 `/backtest/dashboard?strategy=xxx&focus=timeline&start_date=20260101&end_date=20260201`
- 清空日期区间后，确认各区块 `days` 输入恢复可用
