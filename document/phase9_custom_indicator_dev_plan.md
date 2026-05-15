# Phase 9 — 自定义复合指标 + 中长期 Alpha 落地开发计划 (v2 已纳入用户决策)

> **Status**: 🟢 用户决策已落实，待最终审核 (updated 2026-05-08, branch `backTest_dev`)
> **基础**: V2/V3/V4/V5/V6 全部实证完成；本文档将所有结论落地为可执行的 PR。
> **本版变更**：依据用户对 7 个核对项的回复进行重写：见名之意命名 / 实时基本面池 / 10 万实盘资金 / 自由编辑硬规则 / 评分类禁止落库 / PR 充分验证 / **新增 K 线图通用指标叠加 (PR-5)**。

---

## 用户决策落地一览

| # | 决策点 | 用户选择 | 落实位置 |
|---|---|---|---|
| 1 | 命名 | **中文名** | §2.3 改为 `稳健抄底版` / `进攻增长版` / `今日关注榜` |
| 2 | 股票池 | 实时 + **效率优先，缓存文件** | §3.6 每日 09:00 cron 刷新 `_universe_today.pkl`，回测/UI 直接读缓存 |
| 3 | 仓位 | **最优解 = 4 仓 × 25%** | §1.3（详见仓位评估表）|
| 4 | 基本面阈值 | **暂定当前配置，保留后期调整空间** | §3.6 `risk_profile.fundamentals_sell` 字段化，UI 可改 |
| 5 | K 线叠加 UI | **独立副图区域 + 主图叠加二选一可双开** | §4.4 改为「副图模式」`/`「主图叠加」`/`「双开」3 模式 |
| 6 | PR 节奏 | **可并行**（PR-4 / PR-5 都依赖 PR-3）| §6 标注并行关系图 |

### 最终核对项已全部清空 ✅ 进入实施阶段

---

## 0. 实证结论汇总（V6 投资组合级回测最终数据）

`_compare_composite_winrate_v6_portfolio.py` — 1,000,000 起始资金，最多 8 仓并发，每仓 12.5%，扣 0.36% 双边成本，89 只基本面预筛股票，2020-01 ~ 2025-12，约 6 年。

### 60 天持仓窗口（止损 -8% / 止盈 +20%）

| 策略 | 笔数 | 胜率 | 总收益 | CAGR | 最大回撤 | Sharpe |
|---|---|---|---|---|---|---|
| **S12+T3 双信号** | **462** | **40.9%** | **+277.6%** | **24.79%** | **-29.0%** | **1.21** |
| T3 单独 | 439 | 40.1% | +225.2% | 21.72% | -30.4% | 1.13 |
| BH 60d 定投 | 398 | 35.9% | +70.8% | 9.33% | -25.6% | 0.59 |
| S12 单独 | 93 | 47.3% | +62.1% | 8.38% | -10.5% | **1.02** |
| M1 评分预警 | 647 | 34.2% | +43.4% | 6.19% | **-53.8%** | 0.38 |

### 120 天持仓窗口（止损 -12% / 止盈 +40%）

| 策略 | 笔数 | 胜率 | 总收益 | CAGR | 最大回撤 | Sharpe |
|---|---|---|---|---|---|---|
| **S12+T3 双信号** | **216** | **42.6%** | **+316.3%** | **26.83%** | -32.5% | **1.18** |
| M1 评分预警 | 298 | 34.2% | +194.0% | 19.69% | -40.2% | 0.84 |
| T3 单独 | 215 | 40.0% | +187.9% | 19.27% | -31.2% | 0.92 |
| **S12 单独** | **86** | **47.7%** | **+143.8%** | **16.01%** | **-19.6%** | **1.22** |
| BH 60d 定投 | 211 | 33.6% | +69.1% | 9.15% | -50.2% | 0.52 |

### 关键结论

1. **🏆 S12+T3 双信号在 120d 窗口 CAGR 26.8%、Sharpe 1.18 是绝对 Alpha 冠军**
2. **⚖️ S12 单独在 120d 窗口 Sharpe 1.22 + 回撤仅 -19.6% 是风险调整后的最佳策略**
3. **❌ M1 评分类指标在 60d 窗口最大回撤 -53.8% — 绝对禁止作为主交易信号**
4. ✅ 评分类指标 (M1) 仅适合做"今日值得关注"watchlist
5. ✅ 不择时定投 BH 在并发约束下 CAGR 仅 9.3%，远低于双信号策略 — 择时仍有价值

---

## 1. Phase 9 范围定义

### 1.1 必须交付（MVP）

| # | 功能 | 优先级 |
|---|---|---|
| F1 | 自定义复合指标（CRUD + 加权评分计算） | P0 |
| F2 | 触发模式：cross_down / cross_up / persistent / hard_AND_chain | P0 |
| F3 | 指标类型标签：`primary_entry` (硬规则) / `watchlist_alert` (评分类) | P0 |
| F4 | 单股历史回测视图（k 线 + 信号点 + 评分曲线） | P0 |
| F5 | 内置三档预设：稳健 (S12-60d) / 进攻 (S12+T3-120d) / 预警 (M1-watchlist) | P0 |
| F6 | 投资组合级回测 + 止损止盈参数 + 并发约束 | P1 |
| F7 | 指标范式守门（评分类禁止直接落库为 strategy_template） | P1 |

### 1.2 不在 Phase 9 范围（推到 Phase 10+）

- 实时推送 watchlist 到 IM（需要先做完 Phase 8 的安全收口）
- 多因子机器学习（XGBoost 选股）
- 期权 / 商品 / 美股扩展
- 实盘连接交易接口

### 1.3 资金 / 仓位参数（按用户 10 万实盘 — 最优解）

**仓位评估（基于 V6 实证 + 10 万资金的精度损失分析）**：

| 仓位数 | 单仓金额 | 50 元/股 可买 | 仓位精度 | 流动性 | 综合评分 |
|---|---|---|---|---|---|
| 3 仓 × 33% | 3.3 万 | 6 手 (3000 股) | 99% | 单股集中度高，回撤风险大 | ⭐⭐⭐ |
| **4 仓 × 25%** | **2.5 万** | **5 手 (2500 股)** | **99%** | **平衡（推荐）** | ⭐⭐⭐⭐⭐ |
| 5 仓 × 20% | 2 万 | 4 手 (2000 股) | 95% | 单仓最低 1.5 万对 30 元/股仅 5 手，部分票精度损失 | ⭐⭐⭐⭐ |
| 8 仓 × 12.5% | 1.25 万 | 2 手 (1000 股) | 80% | 精度损失 20%，且 V6 同时持有 8 仓需要资金量 ≥ 50 万才合理 | ⭐⭐ |

**结论：4 仓 × 25% 为最优解**

| 参数 | 默认值 | 说明 |
|---|---|---|
| 初始资金 | ¥100,000 | 用户实盘量级 |
| **最大并发仓位** | **4** | 综合评分最优 |
| 单仓权重 | 25% | 等权 |
| 单笔最低 | 100 股 (1 手) | 自动向下取整 |
| 现金保留 | 5% | 防极端跌停补仓 |

---

## 2. 数据库 Schema 改动

### 2.1 新增表 `cn_stock_custom_indicator`

```sql
CREATE TABLE IF NOT EXISTS `cn_stock_custom_indicator` (
  `id`           INT AUTO_INCREMENT PRIMARY KEY,
  `indicator_id` VARCHAR(64)  NOT NULL UNIQUE COMMENT '业务 ID, e.g. user_001_master',
  `name`         VARCHAR(128) NOT NULL,
  `kind`         ENUM('primary_entry','watchlist_alert') NOT NULL,
  `description`  TEXT,
  `weights`      JSON         NOT NULL COMMENT '加权评分组件 e.g. {"n_rsi14":0.1,...}',
  `smooth_ema`   TINYINT      DEFAULT 0,
  `buy_th`       FLOAT        DEFAULT 50,
  `direction`    ENUM('low','high') NOT NULL DEFAULT 'high',
  `extra_filter` TEXT         COMMENT 'Python 表达式字符串, eval 在受限作用域',
  `hard_rules`   TEXT         COMMENT '可选: AND 链规则 (Python 表达式), kind=primary_entry 必填',
  `risk_profile` JSON         NOT NULL COMMENT '{"stop":-0.08,"target":0.2,"max_hold":60}',
  `owner`        VARCHAR(64)  NOT NULL DEFAULT 'system',
  `is_builtin`   TINYINT      DEFAULT 0,
  `created_at`   DATETIME     DEFAULT CURRENT_TIMESTAMP,
  `updated_at`   DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX `ix_kind` (`kind`),
  INDEX `ix_owner` (`owner`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 2.2 自动迁移

- 沿用现有约定：在 `quantia/web/portfolioBacktestHandler.py` 新增 `_ensure_custom_indicator_table()`，在模块加载时调用
- 不使用 Alembic（项目历史风格），保持一致

### 2.3 内置数据（中文命名）

启动时 `_seed_builtin_indicators()` 写入三条记录（如果不存在）：

| indicator_id | name (中文显示) | kind | 来源 |
|---|---|---|---|
| `steady_oversold_rebound` | **稳健抄底版** | primary_entry | V4-V6 实证 PF 1.81~3.63 / 最佳 Sharpe（S12 五条硬规则）|
| `dual_momentum_growth` | **进攻增长版** | primary_entry | V6 CAGR 26.83% / 总收益 +316%（S12 ∪ T3）|
| `score_alert_watchlist` | **今日关注榜** | watchlist_alert | V5 范式守门示例（M1 七因子加权评分，仅供参考）|

> `indicator_id` 仍用英文蛇形（DB 主键约束/URL 友好），UI 与日志全部显示中文 `name`。

---

## 3. 后端代码改动

### 3.1 新增模块 `quantia/core/composite/`

```
quantia/core/composite/
├── __init__.py
├── normalizers.py      # n_lin / n_rank / n_wr / n_supertrend / n_cci ... (从 _v2.py 抽出)
├── indicators_enrich.py # enrich(df) -> 加 n_* 列 (从 _v2.py 抽出)
├── composite_engine.py  # Composite 数据类 + .value(d) + .signal(d) (从 _v2.py 抽出)
├── hard_rules_engine.py # 解析 hard_rules 表达式 -> bool Series
├── risk_simulator.py    # simulate(code, df, sig, sl, tp, max_hold) (从 _v3.py 抽出)
└── builtins.py          # S12 / T3 / E1-3 / MASTER / M1 等可复用函数
```

**职责分离原则**：
- `_v2/_v3/_v4/_v5/_v6` 这些根目录脚本**不动**（实证存档）
- 所有生产代码从这些脚本"提炼"到 `quantia/core/composite/`
- 单元测试覆盖：normalizers 数值正确性、composite_engine 触发方向、hard_rules eval 沙箱安全

### 3.2 新增 Web Handler

文件：`quantia/web/customIndicatorHandler.py`（新建）

```python
class ListCustomIndicatorHandler(...)        # GET  /quantia/api/custom_indicator/list
class GetCustomIndicatorHandler(...)         # GET  /quantia/api/custom_indicator/detail?id=
class SaveCustomIndicatorHandler(...)        # POST /quantia/api/custom_indicator/save
class DeleteCustomIndicatorHandler(...)      # POST /quantia/api/custom_indicator/delete
class BacktestCustomIndicatorHandler(...)    # POST /quantia/api/custom_indicator/backtest
class WatchlistTodayHandler(...)             # GET  /quantia/api/custom_indicator/watchlist?id=
class IndicatorSeriesHandler(...)            # GET  /quantia/api/custom_indicator/series?id=&code=&start=&end=&period=
```

> ⚠️ 实施备注：
> - 实际表 DDL 索引名为 `idx_kind` / `idx_builtin`（按 `is_builtin` 而非 `owner` 过滤更贴合当前单用户场景），未实现 `owner` 字段（推到多用户阶段）。
> - `BacktestCustomIndicatorHandler` 返回的 `summary` 字段集合：`strategy / trades / win% / avg% / med% / expectancy% / PF / avg_hold / stop% / tp% / time% / fund%`（不含 CAGR / MDD —— 单股回测不计算）。
> - `BacktestCustomIndicatorHandler` 返回的 `trades[*]` 字段集合：`entry_date / entry_price / exit_date / exit_price / reason / net_ret_pct / hold_days`（前端表格列名严格对齐这些字段，已通过 `test_backtest_trade_payload_field_contract` 锁定）。

### 3.3 路由注册

在 `quantia/web/web_service.py` 第 ~110 行处增 7 条路由（含 PR-5 `/series`）

### 3.4 范式守门 (F7)

`SaveCustomIndicatorHandler` 的校验逻辑：
- `kind=primary_entry` ⇒ 必须有 `hard_rules` 表达式且通过 sandbox 解析
- `kind=watchlist_alert` ⇒ 允许只有 weights，但 UI 上始终标红色 "仅供参考，禁止实盘"
- 评分类指标的 `direction` 强制 `high`（V5 实证唯一有效改动）

### 3.5 表达式 Sandbox（用户可自由编辑）

`hard_rules_engine.py`：
- AST 白名单：`Compare`/`BoolOp`/`BinOp`/`UnaryOp`/`Subscript`/`Name`/`Constant`/`Attribute`(限于 pandas Series 已知方法 head/tail/rolling/shift/mean/...)
- 禁止：`Import` / `Call(Name=='__import__'/'exec'/'eval'/'open')` / 任何 dunder 名 (`__xxx__`) / `Lambda`
- 求值环境：`{'__builtins__': {}}` + `{'d': df, 'np': numpy_safe_subset, 'pd': pandas_safe_subset}`
- **错误输出友好化**：把 SyntaxError/NameError 翻译成"第 X 行：未知字段 `xxx`，请从右侧字段面板选择"

UI 编辑器（PR-3）配套：
- 多行 textarea + 行号
- 右侧"字段面板"列出所有可用列：`d['close']`, `d['ma5']`, `d['rsi14']`, `d['boll_lower']` 等，点击插入
- "试运行"按钮：选一只股票实时返回触发次数 + 错误信息

### 3.6 动态股票池模块 `quantia/core/composite/dynamic_universe.py`

按用户决策 #2，效率优先 + 缓存文件：

```python
CACHE_FILE = "quantia/cache/composite/_universe_today.pkl"
CACHE_TTL_HOURS = 24

def fetch_universe(top_n=100, force_refresh=False, **filters):
    """
    1) 若 CACHE_FILE 存在且 mtime < 24h，直接返回（毫秒级）
    2) 否则查 cn_stock_selection 实时计算综合评分 → 写缓存 → 返回
    评分公式（与 V3 一致）：
      0.20·rank(ROE) + 0.20·rank(net_profit_3y_cagr)
    + 0.15·rank(profit_yoy) + 0.15·rank(1-debt_ratio)
    + 0.15·rank(net_margin) + 0.10·rank(1-PE) + 0.05·rank(1-PB)
    SQL 过滤：market_cap > 30亿 AND PE 0~80 AND ROE > 7 AND debt < 80%
    """

def fundamentals_signal(code, snapshot_date=None):
    """
    返回当日基本面买卖参考（结构化数据，UI 后期可改阈值）：
      {"score": 87.3, "buy_bias": True, "sell_bias": False,
       "details": {"ROE_yoy_drop_pct": -8.2, "score_quantile": 0.92}}
    """
```

**Cron 集成**：在 `cron/cron.workdayly/` 新增 `refresh_composite_universe.sh`，每个交易日 08:30 调用 `python -m quantia.core.composite.dynamic_universe --refresh`，开盘前刷新缓存。

**用户决策 #4 — 阈值字段化（保留后期调整空间）**：
所有阈值不写死在代码里，而是放进每个指标的 `risk_profile` JSON：

```json
{
  "stop": -0.08, "target": 0.20, "max_hold": 60,
  "fundamentals_check": true,
  "fundamentals_sell": {
    "score_quantile_lt": 0.30,
    "roe_yoy_drop_pct_lt": -50.0
  }
}
```

UI 编辑页（PR-3）会暴露这两个阈值的 input 框，用户随时调整。

---

## 4. 前端改动

### 4.1 新增页面 `/customIndicator.html`

复用 `portfolioBacktest.html` 的 Vue 3 + Element Plus 框架：

- 左侧：指标列表 + 新建按钮
- 右侧编辑面板：
  - 基本信息：name / kind (radio: 主信号 / 预警类) / description
  - **kind=primary_entry**：硬规则编辑器（多行表达式，支持快速插入：`d['ma5']>d['ma20']` 等）
  - **kind=watchlist_alert**：权重表格（可加减行，组件下拉选择，权重数字输入）
  - 触发参数：smooth_ema / buy_th / direction
  - 风控参数：stop_loss / take_profit / max_hold
  - 实时回测按钮 → 显示单股回测结果 (PF / CAGR / DD / 净值曲线)
- **顶部红色横幅**：当 kind=watchlist_alert 时显示「⚠️ 评分类指标，仅做今日值得关注列表，禁止直接驱动交易」

### 4.2 文件清单

```
quantia/web/static/customIndicator.html              # 新建 ~80 行
quantia/web/static/js/custom_indicator.js            # 新建 ~600 行 Vue 组件
quantia/web/static/css/custom_indicator.css          # 新建 ~80 行
quantia/web/static/index.html                        # 加导航菜单项
```

### 4.3 在投资组合回测页加"导入自定义指标"

`portfolioBacktest.html`：策略下拉框旁加按钮「从自定义指标导入」→ 弹窗只列出 `kind=primary_entry` 的项 → 选中后自动生成对应 strategy code。

### 4.4 K 线图通用指标叠加层（用户决策 #5/#7）

**目标**：在所有涉及 K 线图的页面，让用户可以选择把任意自定义指标的"评分曲线 + 买卖信号点"展示到图表中，**支持三种显示模式**（用户决策 #5）：

| 模式 | 显示位置 | 用途 |
|---|---|---|
| **🎯 主图叠加** | 买卖信号点叠加到 K 线主图（红三角/绿菱形）| 看信号触发位置 |
| **📊 副图独立** | 评分曲线放在与 MACD/KDJ 同级的独立副图 | 看评分变化趋势 |
| **🔀 双开** | 主图叠加 + 副图独立 同时显示 | 信号点 + 评分配合分析 |
| ⛔ 关闭 | 不显示任何自定义指标内容 | 默认 |

**涉及的 3 处页面 + 1 个公共组件**：

| 页面 | 文件 | 集成方式 |
|---|---|---|
| 单股 K 线指标 | [quantia/fontWeb/src/views/indicator/index.vue](../quantia/fontWeb/src/views/indicator/index.vue) | 在主图工具栏加"自定义指标"select + "显示模式"3-选 1 单选 |
| 模拟盘个股详情 | [quantia/fontWeb/src/views/paper-trading/index.vue](../quantia/fontWeb/src/views/paper-trading/index.vue) | 同上，挂在 daily/weekly/monthly 三个 tab |
| 回测详情个股轨迹 | [quantia/fontWeb/src/views/algo/backtest-detail.vue](../quantia/fontWeb/src/views/algo/backtest-detail.vue) | 同上 |
| **公共组件 (新)** | `quantia/fontWeb/src/components/CustomIndicatorOverlay.vue` | 输入：echarts option + 指标 ID + 显示模式；输出：合并后的 option |

**新后端 API**：

```
GET /quantia/api/custom_indicator/series?id=<indicator_id>&code=<6位代码>&start=YYYY-MM-DD&end=YYYY-MM-DD&period=daily|weekly|monthly

返回：
{
  "indicator_id": "steady_oversold_rebound",
  "name": "稳健抄底版",
  "kind": "primary_entry",
  "score_series": [{"date":"2024-01-02","score":42.3}, ...]   // 副图模式用
  "signal_points": [{"date":"2024-01-15","price":12.34,"action":"buy"},
                    {"date":"2024-02-10","price":13.78,"action":"sell-stop"},
                    {"date":"2024-03-05","price":15.20,"action":"sell-target"},
                    {"date":"2024-04-12","price":13.50,"action":"sell-time"}, ...]
  // action 枚举：buy / sell-stop / sell-target / sell-time / sell-fund
  //   sell-* 来自 risk_simulator.simulate() 的 reason 映射：
  //   stop-loss→sell-stop, win-target→sell-target, time-exit→sell-time, fundamentals-exit→sell-fund
}
```

**默认行为（用户决策 #5）**：默认 ⛔ 关闭，需用户主动选择指标 + 选择模式。用户偏好（最近选过哪几个指标 / 上次的显示模式）保存在 `localStorage`。

---

## 5. 测试计划

### 5.1 单元测试

| 文件 | 用例数 | 覆盖范围 |
|---|---|---|
| `tests/test_composite_normalizers.py` | ~12 | n_lin / n_rank / n_wr / n_supertrend 边界与 NaN |
| `tests/test_composite_engine.py` | ~8 | direction='low'/'high' 触发、smooth_ema、extra_filter |
| `tests/test_hard_rules_engine.py` | ~10 | sandbox 安全（拒绝 import/open）、eval 正确性 |
| `tests/test_risk_simulator.py` | ~6 | stop/target/time-exit 三路径、T+1 进场 |
| `tests/test_custom_indicator_handler.py` | ~14 | CRUD、kind 守门、内置 seed |

总计 ~50 个新测试，加在现有 325 个之后保持全绿。

### 5.2 集成回归

- 确保 `pytest tests/ -q` 全部通过
- 用内置 `builtin_s12_steady` 在 UI 上跑一遍 89 股 6 年回测，验证 CAGR ≈ V6 数据 ±2% 内（容许并发实现差异）

### 5.3 Sandbox 安全测试

```python
def test_hard_rules_blocks_import():
    with pytest.raises(SecurityError):
        parse_hard_rules("__import__('os').system('rm -rf /')")
```

---

## 6. PR 拆分（每个 PR 独立可合，每个合并前须用户确认）

> 用户决策 #6：每个 PR 必须 (a) 全部新单测通过 (b) 全量 325 回归通过 (c) 用户在浏览器/curl 实际验证 (d) 我整理 PR 总结提交审查 → 用户确认无 bug 后才进入下一 PR。
>
> **PR 依赖图（用户决策 #6 — 可并行）**：
> ```
> PR-1 (后端核心) → PR-2 (REST API) → PR-3 (前端编辑器)
>                                      ├─→ PR-4 (投资组合集成)  ┐
>                                      └─→ PR-5 (K线叠加)       ├ 可并行
> ```

### PR-1 — 后端核心抽取（无 UI、无 HTTP）

**Scope**：建表迁移 + `quantia/core/composite/` 全套模块 + `dynamic_universe.py` + 单元测试 + 三条内置指标 seed
**预计变更**：~1500 行新代码 + ~50 个测试
**完成后可独立运行**：`pytest tests/test_composite_*.py` 全绿；MySQL 中可见 `cn_stock_custom_indicator` 表 + 3 条 seed 记录；脚本 `python -c "from quantia.core.composite.dynamic_universe import fetch_universe; print(len(fetch_universe()))"` 返回 ≥ 80
**用户验证清单**：
- [ ] DB 中查 `SELECT indicator_id, name, kind FROM cn_stock_custom_indicator;` 看到 3 行
- [ ] 跑 `python _verify_pr1_smoke.py` (我会随 PR 提供) 输出 OK
- [ ] `pytest -q` 全绿（含历史 325 + 新 50 ≈ 375 个）

### PR-2 — Web Handler + REST API（共 7 个端点）

**Scope**：`customIndicatorHandler.py` + 7 路由 + handler 单元测试
**新增 API**：5 个 CRUD/回测 (§3.2) + `watchlist_today` + **`/series` (用于 PR-5 K 线叠加)**
**依赖**：PR-1 已合并
**预计变更**：~700 行
**用户验证清单**：
- [ ] `_verify_pr2_curl.sh` 提供，逐个 API 用 curl 跑通
- [ ] 范式守门：尝试用 kind=watchlist_alert 提交带 hard_rules 的请求 → 返回 400 + 友好错误
- [ ] sandbox 安全测试：尝试 hard_rules=`__import__('os').system('echo pwn')` → 返回 400

### PR-3 — 前端编辑器 + 内置预设浏览

**Scope**：`customIndicator.vue` 主页面 + 字段面板 + 试运行 + 单股回测预览 + 红色横幅
**依赖**：PR-2 已合并
**预计变更**：~800 行 Vue 3 + Element Plus
**用户验证清单**：
- [ ] 浏览器打开 /customIndicator，能看见 3 条内置预设
- [ ] 复制内置 `steady_oversold_rebound` → 改名 → 改两条规则 → 保存 → 跑单股回测看到 PF
- [ ] 切到 watchlist_alert 类型，红色横幅显示

### PR-4 — 投资组合集成 + 范式守门 UI

**Scope**：`portfolioBacktest.vue` 加"导入自定义指标"按钮 + watchlist 今日列表页面
**依赖**：PR-3 已合并
**预计变更**：~400 行
**用户验证清单**：
- [ ] 在投资组合回测页选中 `dual_momentum_growth` 跑 89 股 6 年，CAGR 偏差 < 5%（与 V6 数据 26.83%）
- [ ] watchlist 页面显示今日触发的股票

### PR-5 — K 线图通用指标叠加层（用户决策 #7）

**Scope**：
- 新建公共组件 `CustomIndicatorOverlay.vue` (~250 行)
- 改 [quantia/fontWeb/src/views/indicator/index.vue](../quantia/fontWeb/src/views/indicator/index.vue) (主图工具栏 + 副图集成 ~80 行)
- 改 [quantia/fontWeb/src/views/paper-trading/index.vue](../quantia/fontWeb/src/views/paper-trading/index.vue) (~80 行)
- 改 [quantia/fontWeb/src/views/algo/backtest-detail.vue](../quantia/fontWeb/src/views/algo/backtest-detail.vue) (~80 行)
- 后端 `/series` API 已在 PR-2 提供，本 PR 只接消费

**依赖**：PR-2 (后端 API) + PR-3 (CRUD) 已合并；PR-4 可与本 PR 并行
**预计变更**：~500 行 Vue
**用户验证清单**：
- [ ] 三个页面分别打开 K 线图，能在工具栏看到「叠加自定义指标」下拉
- [ ] 选中 `steady_oversold_rebound` 显示买卖三角形
- [ ] 选中 `score_alert_watchlist` 显示评分曲线（副图）+ 红色提示
- [ ] 关闭叠加时图表恢复原样，无残留 series

---

## 7. 时间盒 / 里程碑

> 不给具体时间估算。每个检查点完成后用户确认 → 进入下一 PR。

| 检查点 | 进入条件 |
|---|---|
| **CP1** | PR-1 通过本地 pytest 全绿（375 个）；3 条内置指标在 MySQL 落库；`fetch_universe()` 实时返回 ≥80 只 |
| **CP2** | PR-2 通过 curl 测试 7 个 API；范式守门拒绝错误 kind；sandbox 拒绝 `__import__` |
| **CP3** | PR-3 在浏览器手动操作完成 CRUD + 试运行 + 单股回测预览；watchlist 红色横幅显示 |
| **CP4** | PR-4 在投资组合回测页跑通 `dual_momentum_growth`，CAGR 偏差 < 5% |
| **CP5** | PR-5 在 3 个 K 线页面成功叠加自定义指标，开关切换无残留 |

---

## 8. 风险与缓解

| 风险 | 缓解措施 |
|---|---|
| Sandbox 表达式逃逸 | AST 白名单 + ban `__` 前缀 + ban 关键 builtins |
| 评分类指标被滥用为实盘信号 | DB 层 ENUM 约束 + Handler 校验 + UI 红色横幅三重防线 |
| 投资组合回测性能（89 股 × 6 年） | V6 实测 89 股 ~30 秒，可接受；UI 加 progress bar |
| MASTER 调参陷阱（V5 教训） | 内置预设固定参数 + UI 上写"此为实证最优，慎修改" |
| 基本面预筛前视偏差 | 预设说明文字标明，并在 PR-5 (后续阶段) 接入历史财报快照 |
| 现有 325 测试回归 | 每个 PR 跑全量回归 |

---

## 9. 文档同步

每个 PR 合并时同步更新：

- `document/QUANT_BACKTEST_DEV.md` — 加 §10 自定义指标 API 说明
- `document/API_REFERENCE.md` — 加 6 个新 endpoint
- `README.md` — 在功能列表加一条
- `/memories/repo/` — 创建 `phase9_custom_indicator.md` 记录 schema + 关键约束

---

## 10. 实施前的最后核对项（请用户确认）

请用户在本版基础上做最终签字：

- [ ] **核对 1**：内置预设命名 `steady_oversold_rebound` / `dual_momentum_growth` / `score_alert_watchlist` 是否符合"见名之意"？还是要更口语化（如 `稳健抄底版` / `进攻增长版` / `今日关注榜`）？
- [ ] **核对 2**：动态股票池触发频率 — 是 (a) 每次回测/今日清单刷新都重查 DB，还是 (b) 每天 09:00 定时任务预算并缓存到 `_universe_today.pkl`？方案 b 更快但 09:00 前为空。
- [ ] **核对 3**：4 仓 × 25% 设定 OK 吗？（10 万规模）若实盘想"试水更轻"我可以默认 3 仓 × 33%。
- [ ] **核对 4**：基本面恶化提前止盈的阈值 — `综合评分 < 30 分位 OR ROE 同比 < -50%`，是否过严或过松？
- [ ] **核对 5**：K 线叠加（PR-5）默认显示哪个指标？建议默认不开任何叠加（用户主动选择），避免干扰原视觉。
- [ ] **核对 6**：5 个 PR 是否按顺序合（PR-1→2→3→4→5）？还是允许 PR-4/PR-5 并行（都依赖 PR-3 已合）？

---

## 11. 文档关联

- V2 报告：[document/custom_indicator_winrate_analysis.md](custom_indicator_winrate_analysis.md)
- V3 报告：[document/custom_indicator_winrate_analysis_v3_fundamentals_sl_tp.md](custom_indicator_winrate_analysis_v3_fundamentals_sl_tp.md)
- V4/V5 报告：[document/medium_long_term_holding_analysis.md](medium_long_term_holding_analysis.md)
- 指标百科：[document/technical_indicators_guide_and_optimal_combo.md](technical_indicators_guide_and_optimal_combo.md)
- V6 投资组合回测脚本：[_compare_composite_winrate_v6_portfolio.py](../_compare_composite_winrate_v6_portfolio.py)
- 本文：[document/phase9_custom_indicator_dev_plan.md](phase9_custom_indicator_dev_plan.md)
