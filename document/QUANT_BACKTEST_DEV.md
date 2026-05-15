# 回测引擎 & 模拟交易 — 开发文档

> **分支**: `backTest_dev`
> **日期**: 2026-04-20
> **状态**: Phase 1–Phase 3 已完成（v3.0）

---

## 一、项目目标

基于 Quantia 现有数据和 Backtrader 适配器，构建两个新功能模块：

1. **组合回测系统** — 支持用户编写 Python 策略，进行组合级别的回测
2. **模拟交易系统** — 支持策略的每日自动模拟执行

**核心原则**：最大化复用现有代码，与原项目自然融合。

---

## 二、整合策略

### 2.1 复用现有组件

| 现有组件 | 复用方式 |
|---------|---------|
| `bt_engine.py`（BacktestEngine） | **核心引擎**，扩展为支持自定义策略 |
| `rate_stats.py` | 交易成本计算 |
| `cache/hist/*.gzip.pickle` | 回测数据源，直接读取 |
| `cn_stock_trade_date` | 交易日历 |
| `cn_stock_spot` / `cn_stock_selection` | 当日行情 / 基本面数据 |
| `stockfetch.py` | 获取指数数据（新增沪深300 K线获取） |
| `backtestHandler.py` | 现有回测 API，扩展新端点 |
| `backtestDashboardHandler.py` | 现有看板，扩展组合回测看板 |
| `web_service.py` | 路由注册，新增端点 |
| ECharts（前端） | 收益曲线、持仓图表 |

### 2.2 模块划分

```
quantia/
├── core/backtest/                   ← 扩展现有目录
│   ├── bt_engine.py                 # [已有] Backtrader 适配器 → 扩展
│   ├── rate_stats.py                # [已有] 交易成本
│   ├── portfolio_engine.py          # [新增] 组合回测引擎（基于 Backtrader）
│   ├── strategy_context.py          # [新增] Context/Portfolio/Position 对象
│   ├── data_feed.py                 # [新增] 数据源适配（cache → Backtrader）
│   ├── risk_metrics.py              # [新增] 风险指标（Sharpe/Alpha/MaxDD）
│   └── strategy_sandbox.py          # [新增] 策略安全执行沙箱
│
├── core/stockfetch.py               # [扩展] 新增 fetch_index_hist() 获取指数K线
│
├── paper_trading/                    ← 新增：模拟交易模块
│   ├── __init__.py
│   ├── paper_engine.py              # 模拟交易执行引擎
│   ├── state_manager.py             # 状态持久化
│   └── scheduler.py                 # 每日定时触发
│
├── web/
│   ├── backtestHandler.py           # [扩展] 新增组合回测 API 端点
│   ├── backtestDashboardHandler.py  # [扩展] 新增组合回测看板
│   └── paperTradingHandler.py       # [新增] 模拟交易 API
│
└── fontWeb/src/
    ├── views/
    │   ├── backtest/                 # [已有] 现有回测模块
    │   │   ├── portfolio.vue         # [新增] 组合回测页面
    │   │   └── components/
    │   │       ├── StrategyEditor.vue  # [新增] 策略编辑器
    │   │       ├── NavChart.vue        # [新增] 净值曲线
    │   │       └── TradeTable.vue      # [新增] 交易明细表
    │   └── paper-trading/             # [新增] 模拟交易模块
    │       ├── index.vue              # 模拟盘列表
    │       └── detail.vue             # 单策略详情
    └── api/
        └── stock.ts                   # [扩展] 新增回测/模拟交易 API
```

---

## 三、数据库设计

新增表使用 `cn_stock_` 前缀（与原项目一致）：

```sql
-- 用户策略定义表
CREATE TABLE IF NOT EXISTS `cn_stock_strategy_code` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `name` VARCHAR(100) NOT NULL COMMENT '策略名称',
    `code` TEXT NOT NULL COMMENT 'Python策略代码',
    `description` TEXT COMMENT '策略描述',
    `initial_cash` DECIMAL(15,2) DEFAULT 1000000.00 COMMENT '初始资金',
    `benchmark` VARCHAR(20) DEFAULT '000300' COMMENT '基准指数代码',
    `commission_rate` DECIMAL(8,6) DEFAULT 0.000300 COMMENT '佣金率',
    `stamp_tax_rate` DECIMAL(8,6) DEFAULT 0.001000 COMMENT '印花税',
    `slippage` DECIMAL(8,6) DEFAULT 0.000500 COMMENT '滑点率',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    `status` ENUM('draft','active','archived') DEFAULT 'draft'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户自定义策略代码';

-- 组合回测任务表
CREATE TABLE IF NOT EXISTS `cn_stock_backtest_portfolio` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `strategy_id` INT NOT NULL COMMENT '策略ID',
    `start_date` DATE NOT NULL,
    `end_date` DATE NOT NULL,
    `initial_cash` DECIMAL(15,2),
    `status` ENUM('pending','running','completed','failed') DEFAULT 'pending',
    `started_at` DATETIME,
    `completed_at` DATETIME,
    `error_message` TEXT,
    `total_return` DECIMAL(10,4) COMMENT '累计收益率%',
    `annual_return` DECIMAL(10,4) COMMENT '年化收益率%',
    `max_drawdown` DECIMAL(10,4) COMMENT '最大回撤%',
    `sharpe_ratio` DECIMAL(10,4),
    `alpha` DECIMAL(10,4),
    `beta` DECIMAL(10,4),
    `win_rate` DECIMAL(10,4) COMMENT '胜率%',
    `trade_count` INT COMMENT '交易笔数',
    INDEX `idx_strategy` (`strategy_id`),
    INDEX `idx_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='组合回测任务及结果';

-- 每日净值记录
CREATE TABLE IF NOT EXISTS `cn_stock_backtest_nav` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `backtest_id` INT NOT NULL,
    `date` DATE NOT NULL,
    `nav` DECIMAL(15,6) NOT NULL COMMENT '单位净值',
    `benchmark_nav` DECIMAL(15,6) COMMENT '基准净值',
    `cash` DECIMAL(15,2),
    `market_value` DECIMAL(15,2),
    `total_value` DECIMAL(15,2),
    `daily_return` DECIMAL(10,6),
    `benchmark_return` DECIMAL(10,6),
    UNIQUE KEY `uk_bt_date` (`backtest_id`, `date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='回测每日净值';

-- 交易记录（回测+模拟交易共用）
CREATE TABLE IF NOT EXISTS `cn_stock_backtest_trade` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `backtest_id` INT DEFAULT NULL,
    `paper_id` INT DEFAULT NULL,
    `date` DATE NOT NULL,
    `code` VARCHAR(6) NOT NULL,
    `name` VARCHAR(20),
    `direction` ENUM('buy','sell') NOT NULL,
    `price` DECIMAL(10,3) NOT NULL,
    `amount` INT NOT NULL COMMENT '成交股数',
    `value` DECIMAL(15,2) COMMENT '成交金额',
    `commission` DECIMAL(10,2),
    `tax` DECIMAL(10,2),
    INDEX `idx_bt_date` (`backtest_id`, `date`),
    INDEX `idx_paper_date` (`paper_id`, `date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='回测/模拟交易记录';

-- 持仓快照
CREATE TABLE IF NOT EXISTS `cn_stock_backtest_position` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `backtest_id` INT DEFAULT NULL,
    `paper_id` INT DEFAULT NULL,
    `date` DATE NOT NULL,
    `code` VARCHAR(6) NOT NULL,
    `name` VARCHAR(20),
    `amount` INT NOT NULL,
    `avg_cost` DECIMAL(10,3),
    `close_price` DECIMAL(10,3),
    `market_value` DECIMAL(15,2),
    `profit` DECIMAL(15,2),
    `profit_rate` DECIMAL(10,6),
    `weight` DECIMAL(10,6) COMMENT '持仓权重',
    INDEX `idx_bt_date` (`backtest_id`, `date`),
    INDEX `idx_paper_date` (`paper_id`, `date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='持仓快照';

-- 模拟交易实例
CREATE TABLE IF NOT EXISTS `cn_stock_paper_trading` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `strategy_id` INT NOT NULL,
    `name` VARCHAR(100) COMMENT '模拟盘名称',
    `initial_cash` DECIMAL(15,2) DEFAULT 1000000.00,
    `current_cash` DECIMAL(15,2),
    `current_value` DECIMAL(15,2),
    `status` ENUM('running','paused','stopped') DEFAULT 'running',
    `started_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `last_run_date` DATE,
    `state_json` LONGTEXT COMMENT '序列化的 g 对象和上下文',
    INDEX `idx_strategy` (`strategy_id`),
    INDEX `idx_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='模拟交易实例';
```

---

## 四、API 端点设计

在现有路由结构上扩展（`/quantia/api/` 前缀）：

### 4.1 策略管理

| Method | Path | 说明 |
|--------|------|------|
| POST | `/quantia/api/strategy/code` | 保存策略代码 |
| GET | `/quantia/api/strategy/code/list` | 策略列表 |
| GET | `/quantia/api/strategy/code/:id` | 策略详情 |
| DELETE | `/quantia/api/strategy/code/:id` | 删除策略 |
| GET | `/quantia/api/strategy/templates` | 内置策略模板 |

### 4.2 组合回测

| Method | Path | 说明 |
|--------|------|------|
| POST | `/quantia/api/backtest/portfolio/run` | 启动组合回测 |
| GET | `/quantia/api/backtest/portfolio/:id` | 回测结果 |
| GET | `/quantia/api/backtest/portfolio/:id/nav` | 净值曲线 |
| GET | `/quantia/api/backtest/portfolio/:id/trades` | 交易明细 |
| GET | `/quantia/api/backtest/portfolio/:id/positions` | 持仓变化 |
| GET | `/quantia/api/backtest/portfolio/list` | 任务列表 |

### 4.3 模拟交易

| Method | Path | 说明 |
|--------|------|------|
| POST | `/quantia/api/paper/create` | 创建模拟盘 |
| POST | `/quantia/api/paper/:id/pause` | 暂停 |
| POST | `/quantia/api/paper/:id/resume` | 恢复 |
| POST | `/quantia/api/paper/:id/stop` | 停止 |
| GET | `/quantia/api/paper/:id` | 状态 |
| GET | `/quantia/api/paper/list` | 列表 |

---

## 五、核心架构：基于 Backtrader 扩展

### 5.1 现有 bt_engine.py 能力

| 能力 | 状态 |
|------|------|
| Cerebro 初始化 + 资金/佣金设定 | ✅ 已有 |
| PandasData 适配 | ✅ 已有 |
| SignalStrategy（信号→买卖） | ✅ 已有 |
| SharpeRatio / DrawDown / Returns / TradeAnalyzer | ✅ 已有 |
| StrategyBacktester 批量回测 | ✅ 已有 |
| calculate_simple_returns（收益计算） | ✅ 已有 |

### 5.2 需要扩展

| 需求 | 实现方式 |
|------|---------|
| 自定义策略代码 → bt.Strategy | `portfolio_engine.py` 编译适配 |
| 多股票同时加载 | `data_feed.py` 批量加载 cache |
| 基准指数数据 | `stockfetch.py` 新增 `fetch_index_hist()` |
| 聚宽风格 API | `strategy_context.py` 适配层 |
| 净值/持仓每日记录 | Backtrader Observer + Analyzer |
| 结果写入 DB | `portfolio_engine.py` 完成后持久化 |

### 5.3 策略编译流程

```
用户 Python 策略代码（聚宽风格）
        │
        ▼
strategy_sandbox.py 安全检查 + exec()
        │
        ▼
提取 initialize() / handle_data() 函数
        │
        ▼
portfolio_engine.py 包装为 bt.Strategy 子类
  - __init__() → 调用用户 initialize()
  - next()     → 调用用户 handle_data()
  - 注入 context / data / order 等 API
        │
        ▼
Cerebro.addstrategy() + adddata() + run()
        │
        ▼
提取 Analyzer 结果 → 写入 DB
```

---

## 六、实现计划

### Phase 1: 回测引擎核心（后端）

| 序号 | 文件 | 内容 |
|------|------|------|
| 1 | `strategy_context.py` | Context / Portfolio / Position / GlobalVars |
| 2 | `data_feed.py` | cache → PandasData，含基准指数 |
| 3 | `portfolio_engine.py` | 编译策略 + 运行 Cerebro + 输出结果 |
| 4 | `strategy_sandbox.py` | 安全执行用户代码 |
| 5 | `risk_metrics.py` | 从 Analyzer 提取 Sharpe/Alpha/MaxDD |
| 6 | `stockfetch.py` 扩展 | `fetch_index_hist()` |
| 7 | 单元测试 | 均线策略回测验证 |

### Phase 2: Web 集成

| 序号 | 文件 | 内容 |
|------|------|------|
| 1 | `backtestHandler.py` 扩展 | 策略 CRUD + 组合回测 API |
| 2 | `web_service.py` 扩展 | 注册新路由 |
| 3 | `portfolio.vue` | 策略编辑器 + 参数 + 结果展示 |
| 4 | `NavChart.vue` | 净值曲线 ECharts |
| 5 | `stock.ts` 扩展 | 新增 API |

### Phase 3: 模拟交易

| 序号 | 文件 | 内容 |
|------|------|------|
| 1 | `paper_engine.py` | 每日执行策略 + 虚拟成交 |
| 2 | `state_manager.py` | 序列化/恢复 |
| 3 | `paperTradingHandler.py` | API |
| 4 | `paper-trading/*.vue` | 前端面板 |

### Phase 3 已完成的增强功能（2026-04-20）

#### 模拟交易数据源架构

**核心原则**：模拟交易中除账户金额是虚拟的外，所有数据均为实盘数据。

```
行情数据加载优先级：
  pickle 缓存 (cache/hist/) → MySQL cn_stock_spot → EastMoney API

基本面数据加载优先级：
  cn_stock_selection（70+列真实数据） → FundamentalDataProvider 回退
```

| 数据类别 | 数据源 | 实时性 |
|---------|--------|--------|
| K线/行情 | pickle缓存 + cn_stock_spot DB + EastMoney API | 当日 |
| PE/PB/市值 | cn_stock_selection.pe9/pbnewmrq/total_market_cap | 当日 |
| ROE/EPS/毛利率 | cn_stock_selection.roe_weight/basic_eps/sale_gpr | 当日 |
| 资产负债率 | cn_stock_selection.debt_asset_ratio | 当日 |
| 增长率 | cn_stock_selection.netprofit_yoy_ratio/toi_yoy_ratio | 当日 |

#### 新增聚宽 API

| API | 说明 |
|-----|------|
| `order_target_percent(code, percent)` | 按目标仓位百分比调仓 |
| `run_daily(func, time)` | 注册日级回调（每次运行重新注册） |
| `run_weekly(func, weekday, time)` | 注册周级回调（存储 (func, weekday) 元组） |
| `run_monthly(func, monthday, time)` | 注册月级回调 |
| `get_fundamentals(query)` | 从 cn_stock_selection 查询真实基本面数据 |
| `get_all_cached_stocks()` | 获取全部缓存股票代码（~4800只） |
| `get_index_stocks(index_code)` | 获取指数成份股（内置 399951 银行指数） |
| `get_all_securities()` | 获取全部股票信息 DataFrame |

---

## 七、策略 API 参考

### 策略生命周期

```python
def initialize(context):
    """策略初始化，整个回测只执行一次"""
    context.security = '000001'
    context.benchmark = '000300'  # 基准指数
    # 设置交易成本
    set_order_cost(commission=0.0003, tax=0.001, slippage=0.002)

def before_trading_start(context):
    """每个交易日开盘前执行（可选）"""
    pass

def handle_data(context, data):
    """每个交易日执行一次（核心策略逻辑）"""
    pass

def after_trading_end(context):
    """每个交易日收盘后执行（可选）"""
    pass
```

### 下单函数

| 函数 | 说明 |
|------|------|
| `order(code, amount)` | 按股数买入（正）/卖出（负），A股按100股整数 |
| `order_target(code, amount)` | 调整到目标持仓股数 |
| `order_value(code, value)` | 买入指定金额的股票 |
| `order_target_value(code, value)` | 调整到目标持仓金额 |
| `order_target_percent(code, percent)` | 按目标仓位百分比调仓 |

**A股规则**：
- T+1 交易：今日买入的股票明日才能卖出
- 涨跌停限制：涨停无法买入，跌停无法卖出
- 最小交易单位：100 股（1 手）

### 数据获取

| 表达式 | 说明 |
|--------|------|
| `data[code].close` | 上一交易日收盘价 |
| `data[code].open / high / low / volume` | OHLCV 数据 |
| `history(code, N, field)` | 最近 N 个交易日的 field 数据（返回 Series） |
| `get_price(code, start, end, fields)` | 指定区间的历史数据（返回 DataFrame） |

### 账户信息

| 属性 | 说明 |
|------|------|
| `context.portfolio.available_cash` | 可用现金 |
| `context.portfolio.total_value` | 总资产（现金 + 持仓市值） |
| `context.portfolio.market_value` | 持仓市值 |
| `context.portfolio.positions` | 持仓字典 `{code: Position}` |
| `context.portfolio.positions[code].amount` | 总持仓股数 |
| `context.portfolio.positions[code].closeable_amount` | 可卖出股数（T+1） |
| `context.portfolio.positions[code].avg_cost` | 持仓成本价 |
| `context.portfolio.positions[code].price` | 当前市价 |
| `context.portfolio.positions[code].value` | 持仓市值 |
| `context.current_dt` | 当前交易日期 |
| `context.previous_dt` | 上一交易日期 |

### 设置函数

| 函数 | 说明 |
|------|------|
| `set_benchmark(code)` | 设定基准指数（默认沪深300） |
| `set_order_cost(commission, tax, slippage)` | 设定交易成本 |

### 工具函数

| 函数 | 说明 |
|------|------|
| `log.info(msg)` | 日志记录 |
| `record(**kwargs)` | 记录自定义指标（会在收益曲线下方展示） |

### 回测结果指标

| 指标 | 说明 |
|------|------|
| 累计收益率 | 策略总回报 |
| 年化收益率 | 年化后的回报率 |
| 基准收益率 | 基准指数同期回报 |
| 最大回撤 | 峰谷最大跌幅 |
| 夏普比率 | 风险调整收益（无风险利率取1年定期存款） |
| 胜率 | 盈利交易占比 |
| 总交易笔数 | 买入+卖出次数 |
| 日均换手率 | 每日交易金额/总资产 |

---

## 八、内置策略模板

### 均线突破

```python
def initialize(context):
    context.security = '000001'

def handle_data(context, data):
    price = data[context.security].close
    ma5 = history(context.security, 5, 'close').mean()
    if price > ma5 * 1.01 and context.portfolio.available_cash > 0:
        order_value(context.security, context.portfolio.available_cash * 0.9)
    elif price < ma5 * 0.99:
        order_target(context.security, 0)
```

### 多股票等权

```python
def initialize(context):
    context.stocks = ['600519', '000858', '601318', '600036', '300750']

def handle_data(context, data):
    target = context.portfolio.total_value / len(context.stocks)
    for code in context.stocks:
        order_target_value(code, target)
```

### 双均线

```python
def initialize(context):
    context.security = '600519'

def handle_data(context, data):
    ma5 = history(context.security, 5, 'close').mean()
    ma20 = history(context.security, 20, 'close').mean()
    if ma5 > ma20 and context.security not in context.portfolio.positions:
        order_value(context.security, context.portfolio.available_cash * 0.9)
    elif ma5 < ma20:
        order_target(context.security, 0)
```
