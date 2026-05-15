# 模拟交易即时消息通知与交易决策留痕开发文档

> 日期：2026-04-30
> 范围：模拟交易信号通知、交易理由与决策依据存储、AI 综合评分扩展、钉钉优先接入、回测复用、未来 IM 交易指令扩展
> 状态：设计与开发计划
> 目标目录：`document/`

---

## 1. 背景与目标

当前项目已经具备组合回测、模拟交易、K 线与技术指标展示、模拟买卖点查看等能力。下一步希望在模拟交易出现买点或卖点时，先将交易信息推送到钉钉，并在通知中明确展示买卖动作、成交信息、策略真实触发理由、指标阈值对比、详情链接；后续再扩展企业微信、QQ、微信等渠道，并为 IM 确认交易或下达指令预留扩展。

同时，需要为后期 AI 辅助研判预留能力：当策略筛选出股票或准备买入、卖出前，系统可以汇总该股票的基础信息、常用技术指标、K 线窗口、策略筛选原因、账户与风险上下文，传入可配置的 AI 提示词和模型工具链，由 AI 输出综合评分、建议动作、风险提示和关键依据。该评分第一阶段只作为解释和辅助决策，后续可配置为买入/卖出的可选交易闸门。

本方案重点解决两个问题：

1. **通知可达**：交易信号产生后，稳定、可重试、可去重地发送到目标 IM 渠道。
2. **理由可信**：通知中的交易理由必须来自策略执行时的真实筛选数据和判断过程，而不是前端根据成交记录事后猜测。
3. **AI 可扩展**：AI 评分必须基于策略当时可见的数据包，可配置、可关闭、可追溯，并且不能替代必要的风控和人工确认。
4. **钉钉优先**：第一阶段只实现钉钉 webhook 的生产可用闭环，其他 IM 渠道保留抽象接口和后续计划。

---

## 2. 现状审计

### 2.1 当前模拟交易执行链路

```text
quantia/web/web_service.py
  -> quantia/paper_trading/scheduler.py
  -> run_all_paper_trading(scheduled=True)
  -> quantia/paper_trading/paper_engine.py
  -> run_paper_trading_daily(paper_id, scheduled=True)
  -> 执行用户策略代码
  -> 策略调用 order/order_target/order_value/order_target_percent
  -> paper_engine 收集 pending_orders
  -> 撮合生成 TradeRecord
  -> 写入交易、持仓、净值、执行日志
```

通知的最佳切入点应位于 `run_paper_trading_daily` 生成交易记录并成功提交数据库之后。原因是策略调用下单函数时只是交易意图，最终是否成交、成交价、数量、费用、卖出盈亏等数据只有撮合后才完整；如果数据库提交前发送通知，容易出现“消息已发但交易未落库”的不一致。

### 2.2 当前交易理由能力缺口

当前 `paper_engine.py` 中的下单代理只记录基础意图：

```python
pending_orders.append({'code': code, 'amount': amount, 'value': value})
```

当前 `TradeRecord` 主要包含成交字段：

```text
date
code
name
direction
price
amount
value
commission
tax
slippage_cost
close_profit
return_rate
```

缺少以下关键字段或关联数据：

- 策略下单理由 `reason`。
- 决策明细 `decision_json`。
- 指标快照 `indicator_snapshot`。
- 阈值配置 `thresholds`。
- 策略候选池筛选过程 `selection_snapshot`。
- 下单前后账户状态 `portfolio_snapshot`。
- 通知发送状态 `notify_status`。

因此，如果现在直接做通知，只能发送“发生了买入/卖出”，但无法保证“为什么买入/卖出”的解释真实来自策略运行时。

### 2.3 现有前端解释的边界

`quantia/fontWeb/src/views/algo/backtest-detail.vue` 已经有交易原因、指标快照和决策依据展示逻辑，但这些逻辑主要基于交易结果和 K 线指标重新组织展示。它可以作为 UI 复用参考，但不应作为通知理由的权威来源。权威来源应该在后端策略执行时产生并落库。

### 2.4 通知模块现状

当前项目未发现统一的 notification/webhook/message 模块。建议新增独立模块，不要将钉钉、企业微信、QQ 等具体渠道逻辑直接写入 `paper_engine.py`。

---

## 3. 设计原则

### 3.1 真实策略数据优先

通知中的交易理由必须来自策略运行时的真实判断数据。推荐让策略在调用下单函数时显式传入：

```python
order_target_percent(
    code,
    0.5,
    reason='收盘价接近布林下轨后反弹，MA5 上穿 MA20，触发建仓',
    decision={
        'rules': [
            {
                'name': 'BOLL 下轨接近度',
                'threshold': 'close <= boll_lower * 1.02',
                'actual': {'close': 3.74, 'boll_lower': 3.67, 'ratio': 1.0191},
                'passed': True,
                'note': '价格位于下轨 2% 范围内'
            }
        ]
    }
)
```

旧策略不传 `reason/decision` 时，系统提供兜底说明，但兜底说明必须标记为 `generated`，不能伪装成策略真实理由。

### 3.2 通知不阻塞交易主流程

模拟交易执行成功与通知发送成功应解耦。交易落库成功后写入通知 outbox 表；通知 worker 或服务函数发送。即使钉钉、企业微信不可用，也不能导致模拟交易失败。

### 3.3 去重和可追溯

通知必须有幂等键，避免调度重试或手工重跑导致重复发送。推荐幂等键：

```text
paper_id + run_id + trade_id + channel
```

如果历史数据没有 `run_id`，可降级为：

```text
paper_id + trade_date + code + direction + amount + price + channel
```

### 3.4 回测和模拟交易复用

“交易决策留痕”不应只服务模拟交易，也应服务组合回测。推荐抽象为通用概念：

- `trade_signal`：策略发出的交易意图。
- `trade_decision`：意图背后的规则、指标、阈值、实际值。
- `trade_execution`：最终成交结果。
- `notification_event`：对外通知事件。

### 3.5 AI 综合评分作为可选扩展点

AI 研判不应直接散落在策略代码、通知模板或前端页面中。推荐将其抽象为独立的 `ai_decision` 服务，输入是标准化数据包，输出是可审计评分结果。

买入前或卖出前可传入的数据包建议包括：

- 股票基础信息：代码、名称、市场、行业、概念、总市值、流通市值、市盈率、市净率、换手率、涨跌幅、停牌/涨跌停状态。
- 常用指标信息：MA、BOLL、MACD、KDJ、RSI、成交量均线、近期波动率、ATR、量价背离、趋势强度。
- K 线数据：最近 N 个交易日的日 K，必要时包含周 K、月 K；指标必须基于完整历史 K 线计算后截取。
- 策略上下文：策略名称、筛选阶段、通过/未通过规则、排序分数、触发阈值、实际值、策略原始理由。
- 账户与风控上下文：当前现金、持仓、目标仓位、单票仓位、组合回撤、当日交易次数、最大可买金额。
- 市场上下文：基准指数走势、板块涨跌、市场温度、是否重大节假日前后等可选数据。

AI 输出必须结构化保存，至少包括：

- `score`：0-100 综合评分。
- `action`：buy/sell/hold/skip/reduce/watch。
- `confidence`：置信度。
- `reason_summary`：简短理由。
- `evidence`：关键证据列表，需引用输入数据字段。
- `risk_flags`：风险提示列表。
- `threshold_result`：与配置阈值的比较结果。
- `prompt_version`、`model_name`、`input_hash`：用于追溯和复现。

第一阶段建议将 AI 评分作为通知内容和人工复核依据，不改变原策略交易结果。第二阶段可增加配置：当 `enabled_as_gate=1` 时，只有 `score >= buy_threshold` 且 `action in ('buy', 'hold')` 才允许买入；卖出可配置为 `score <= sell_threshold` 或 AI 明确建议 `sell/reduce` 时触发额外提醒。即便启用 AI gate，也必须记录“策略原始信号”和“AI 过滤结果”，避免丢失策略真实表现。

> **当前实现状态（2026-05-09 复核）**：[paper_engine.py](quantia/paper_trading/paper_engine.py) 与 [trade_signal_store.py](quantia/core/backtest/trade_signal_store.py) 调用的是 `score_trade(decision_phase='post_signal')`——AI 评分发生在**撮合落库之后**。这意味着即使 `enabled_as_gate=1` 且 score < buy_threshold，本次买入仍会成交，gate 仅作为「事后留痕 + 通知警告」，便于人工复盘。要让 gate 真正阻断撮合，需要在 `_order_proxy` 撮合前增加 `pre_buy` / `pre_sell` 调用点（接受新增延迟），属 Phase 4 后续优化项。

### 3.6 AI 配置必须版本化

AI 相关参数需要可修改，但每次运行必须固化快照，避免后续改了提示词后无法解释历史交易。建议版本化字段包括：

- provider/model/base_url/api_key_ref。
- system prompt、user prompt 模板、输出 JSON schema。
- temperature、max_tokens、timeout、重试次数。
- buy/sell 阈值、是否启用 gate、失败时 fallback 策略。
- 可接入工具列表，如财务摘要、行业数据、新闻摘要、指数状态、已有回测统计。

失败处理原则：AI 超时、返回非 JSON、评分缺失、配置禁用时，默认不阻塞策略交易；如果用户显式开启 `fail_closed`，才允许因 AI 失败拒绝下单，并必须写入拒绝原因。

### 3.7 前端可配置与后端安全边界

通知和 AI 研判需要支持前端界面调整，但不能把所有参数都开放给普通用户。推荐按“可视化配置、敏感引用、运行快照”三层处理。

前端建议可配置：

- 通知开关：是否启用、适用模拟盘、事件类型、只通知买入/卖出/异常/汇总。
- 钉钉配置：webhook 环境变量引用、secret 环境变量引用、接收范围、限流、测试发送。
- 通知模板：摘要字段顺序、详情字段上限、是否展示 AI 评分、是否展示关键原始参考数据。
- AI 开关：是否启用 AI 研判、是否作为 gate、买入/卖出阈值、失败策略、超时时间。
- AI 提示词：system prompt、user prompt 模板、输出 JSON schema、prompt 版本说明。
- AI 数据包范围：K 线窗口长度、是否包含周/月 K、是否包含基本面、是否包含市场/板块上下文、最多展示多少条证据。
- 工具接入开关：财务摘要、行业数据、新闻摘要、指数状态、历史回测统计等。

后端或环境变量中保留，不建议直接在前端明文编辑：

- 钉钉完整 webhook URL、secret 明文。
- AI API key、券商账号、实盘交易 token。
- 生产环境 base_url 白名单、可调用工具白名单。
- 系统级最大单笔交易金额、最大日交易金额、实盘风控硬阈值。

前端保存配置时只保存引用和版本，不保存敏感明文。例如 `api_key_ref=QUANTIA_AI_API_KEY`、`secret_ref=QUANTIA_DINGTALK_SECRET`。每次策略运行时，后端读取当前配置并固化运行快照，历史记录不随前端后续修改而改变。

---

## 4. 总体架构

### 4.1 推荐模块划分

```text
quantia/
├── ai_decision/
│   ├── __init__.py
│   ├── config.py
│   ├── context_builder.py
│   ├── prompt_renderer.py
│   ├── service.py
│   ├── schema.py
│   └── providers/
│       ├── __init__.py
│       ├── base.py
│       └── openai_compatible.py
│
├── notification/
│   ├── __init__.py
│   ├── config.py
│   ├── service.py
│   ├── templates.py
│   ├── channels/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── dingtalk.py
│   │   └── future_wecom.py
│   └── command.py
│
├── core/backtest/
│   ├── strategy_context.py
│   └── trade_decision.py
│
└── paper_trading/
    └── paper_engine.py
```

### 4.2 数据流

```text
策略运行
  -> 计算指标和筛选结果
    -> 构造 AI 决策上下文 ai_context
    -> 可选调用 ai_decision.service 获取 score/action/risk_flags
    -> 根据配置决定 AI 仅留痕、仅通知展示，或作为交易 gate
  -> 调用 order_*(..., reason, decision)
  -> paper_engine 捕获交易意图 trade_signal
    -> 保存 AI 评分与 trade_signal 的关联
  -> 撮合成交，生成 trade_record
  -> 将 signal/decision 与 trade_record 关联落库
  -> 写入 notification_outbox
  -> notification.service 发送消息
  -> 更新发送状态
  -> 用户在 IM 中查看摘要和详情链接
```

### 4.3 推荐通知时机

| 通知时机 | 说明 | 默认 |
|---|---|---|
| `order_intent` | 策略发出下单意图，但未撮合 | 关闭 |
| `trade_executed` | 模拟交易撮合完成并落库 | 开启 |
| `run_summary` | 单个模拟盘每日运行摘要 | 可选 |
| `run_failed` | 策略执行失败或数据异常 | 开启 |
| `risk_alert` | 仓位、回撤、连续亏损等风险提醒 | 可选 |

---

## 5. 数据库表结构设计

### 5.1 交易信号表：`cn_stock_trade_signal`

用于记录策略在运行时发出的交易意图。组合回测和模拟交易都可复用。

```sql
CREATE TABLE IF NOT EXISTS `cn_stock_trade_signal` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `source_type` VARCHAR(32) NOT NULL COMMENT 'backtest/paper/live',
    `source_id` BIGINT NOT NULL COMMENT '回测ID、模拟盘ID或实盘策略ID',
    `run_id` VARCHAR(64) DEFAULT NULL COMMENT '单次运行ID',
    `strategy_id` BIGINT DEFAULT NULL COMMENT '策略ID',
    `strategy_name` VARCHAR(128) DEFAULT NULL COMMENT '策略名称快照',
    `trade_id` BIGINT DEFAULT NULL COMMENT '成交记录ID，撮合后回填',
    `signal_date` DATE NOT NULL COMMENT '信号日期',
    `code` VARCHAR(20) NOT NULL COMMENT '股票代码',
    `name` VARCHAR(64) DEFAULT NULL COMMENT '股票名称快照',
    `direction` VARCHAR(16) NOT NULL COMMENT 'buy/sell',
    `order_api` VARCHAR(64) DEFAULT NULL COMMENT 'order/order_target/order_value/order_target_percent',
    `requested_amount` DECIMAL(20,4) DEFAULT NULL COMMENT '策略请求数量变化',
    `requested_value` DECIMAL(20,4) DEFAULT NULL COMMENT '策略请求金额变化',
    `target_amount` DECIMAL(20,4) DEFAULT NULL COMMENT '目标持仓数量',
    `target_percent` DECIMAL(12,6) DEFAULT NULL COMMENT '目标仓位比例',
    `reason` TEXT DEFAULT NULL COMMENT '策略提供的人类可读理由',
    `reason_source` VARCHAR(32) DEFAULT 'strategy' COMMENT 'strategy/generated/manual/imported',
    `ai_score_id` BIGINT DEFAULT NULL COMMENT '关联 cn_stock_trade_ai_score.id',
    `ai_score` DECIMAL(8,4) DEFAULT NULL COMMENT 'AI 综合评分快照，0-100',
    `ai_action` VARCHAR(32) DEFAULT NULL COMMENT 'AI 建议动作 buy/sell/hold/skip/reduce/watch',
    `ai_gate_result` VARCHAR(32) DEFAULT NULL COMMENT 'not_enabled/pass/reject/fallback/error',
    `signal_hash` VARCHAR(64) NOT NULL COMMENT '幂等哈希',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY `uk_signal_hash` (`signal_hash`),
    KEY `idx_source_run` (`source_type`, `source_id`, `run_id`),
    KEY `idx_trade_id` (`trade_id`),
    KEY `idx_ai_score_id` (`ai_score_id`),
    KEY `idx_code_date` (`code`, `signal_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='策略交易信号表';
```

AI 字段只保存摘要和关联 ID，完整输入输出放在 `cn_stock_trade_ai_score`，避免交易信号表过宽。即使 AI gate 拒绝买入，也应保留策略原始信号和 AI 拒绝原因，方便后续评估“策略本来会买，但 AI 过滤后错过/规避了什么”。

### 5.2 交易决策明细表：`cn_stock_trade_decision`

用于记录每条交易信号对应的指标、阈值、实际值和判断结果。

```sql
CREATE TABLE IF NOT EXISTS `cn_stock_trade_decision` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `signal_id` BIGINT NOT NULL COMMENT '关联 cn_stock_trade_signal.id',
    `rule_group` VARCHAR(64) DEFAULT NULL COMMENT 'entry/exit/risk/position',
    `rule_name` VARCHAR(128) NOT NULL COMMENT '规则或指标名称',
    `indicator_key` VARCHAR(64) DEFAULT NULL COMMENT 'close/ma5/ma20/boll_lower/rsi14/macd_hist',
    `threshold_expr` VARCHAR(255) DEFAULT NULL COMMENT '阈值表达式',
    `threshold_value` JSON DEFAULT NULL COMMENT '阈值结构化数据',
    `actual_value` JSON DEFAULT NULL COMMENT '实际指标值结构化数据',
    `passed` TINYINT(1) DEFAULT NULL COMMENT '1通过，0未通过，NULL仅展示',
    `weight` DECIMAL(10,4) DEFAULT NULL COMMENT '规则权重',
    `score` DECIMAL(10,4) DEFAULT NULL COMMENT '规则得分',
    `note` TEXT DEFAULT NULL COMMENT '说明',
    `sort_order` INT DEFAULT 0 COMMENT '展示排序',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    KEY `idx_signal_id` (`signal_id`),
    KEY `idx_rule_group` (`signal_id`, `rule_group`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='交易决策明细表';
```

### 5.3 指标快照表：`cn_stock_trade_indicator_snapshot`

用于存储交易时点完整指标快照，供通知、回测详情、模拟交易详情复用。

```sql
CREATE TABLE IF NOT EXISTS `cn_stock_trade_indicator_snapshot` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `signal_id` BIGINT NOT NULL COMMENT '关联 cn_stock_trade_signal.id',
    `period` VARCHAR(16) DEFAULT 'daily' COMMENT 'daily/weekly/monthly',
    `kline_date` DATE NOT NULL COMMENT '指标对应K线日期',
    `open` DECIMAL(20,6) DEFAULT NULL,
    `high` DECIMAL(20,6) DEFAULT NULL,
    `low` DECIMAL(20,6) DEFAULT NULL,
    `close` DECIMAL(20,6) DEFAULT NULL,
    `volume` DECIMAL(24,4) DEFAULT NULL,
    `amount` DECIMAL(24,4) DEFAULT NULL,
    `ma` JSON DEFAULT NULL COMMENT '均线，如 {"ma5":3.71,"ma20":3.70}',
    `boll` JSON DEFAULT NULL COMMENT 'BOLL 指标',
    `rsi` JSON DEFAULT NULL COMMENT 'RSI 指标',
    `macd` JSON DEFAULT NULL COMMENT 'MACD 指标',
    `kdj` JSON DEFAULT NULL COMMENT 'KDJ 指标',
    `extra` JSON DEFAULT NULL COMMENT '策略自定义指标',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY `uk_signal_period` (`signal_id`, `period`),
    KEY `idx_signal_date` (`signal_id`, `kline_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='交易时点指标快照表';
```

指标值必须基于完整历史 K 线计算后再截取交易时点，避免只用回测区间或模拟区间切片导致指标失真。

### 5.4 候选筛选快照表：`cn_stock_trade_selection_snapshot`

用于记录交易信号产生前的候选池和筛选原因，特别适合选股策略、基本面策略、多因子策略。

```sql
CREATE TABLE IF NOT EXISTS `cn_stock_trade_selection_snapshot` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `signal_id` BIGINT NOT NULL COMMENT '关联 cn_stock_trade_signal.id',
    `stage` VARCHAR(64) NOT NULL COMMENT 'universe/basic_filter/technical_filter/rank/final',
    `candidate_count_before` INT DEFAULT NULL COMMENT '筛选前数量',
    `candidate_count_after` INT DEFAULT NULL COMMENT '筛选后数量',
    `rank_value` DECIMAL(20,6) DEFAULT NULL COMMENT '该股票排序分值',
    `rank_position` INT DEFAULT NULL COMMENT '该股票排序名次',
    `filter_expr` VARCHAR(255) DEFAULT NULL COMMENT '筛选表达式',
    `actual_value` JSON DEFAULT NULL COMMENT '该股票在本阶段的实际值',
    `passed` TINYINT(1) DEFAULT NULL COMMENT '本阶段是否通过',
    `note` TEXT DEFAULT NULL COMMENT '说明',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    KEY `idx_signal_stage` (`signal_id`, `stage`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='交易候选筛选快照表';
```

### 5.5 AI 决策配置表：`cn_stock_ai_decision_config`

用于管理 AI 提示词、模型参数、评分阈值和是否作为交易闸门。配置可以前端修改，但每次运行需要固化 `config_version` 和 prompt 快照。

```sql
CREATE TABLE IF NOT EXISTS `cn_stock_ai_decision_config` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `name` VARCHAR(128) NOT NULL COMMENT '配置名称',
    `enabled` TINYINT(1) DEFAULT 0 COMMENT '是否启用 AI 研判',
    `source_type` VARCHAR(32) DEFAULT 'paper' COMMENT 'paper/backtest/live/all',
    `source_id` BIGINT DEFAULT NULL COMMENT '指定模拟盘、回测或策略，为空表示全部',
    `strategy_id` BIGINT DEFAULT NULL COMMENT '可绑定具体策略',
    `provider` VARCHAR(64) DEFAULT 'openai_compatible' COMMENT 'openai_compatible/deepseek/qwen/local等',
    `model_name` VARCHAR(128) DEFAULT NULL COMMENT '模型名称',
    `base_url` VARCHAR(255) DEFAULT NULL COMMENT '兼容接口地址，可为空',
    `api_key_ref` VARCHAR(255) DEFAULT NULL COMMENT '密钥引用，优先使用环境变量名',
    `system_prompt` MEDIUMTEXT DEFAULT NULL COMMENT '系统提示词',
    `user_prompt_template` MEDIUMTEXT DEFAULT NULL COMMENT '用户提示词模板',
    `output_schema` JSON DEFAULT NULL COMMENT '期望输出 JSON schema',
    `tool_config` JSON DEFAULT NULL COMMENT '允许调用的工具和数据源配置',
    `temperature` DECIMAL(6,4) DEFAULT 0.2000,
    `max_tokens` INT DEFAULT 2048,
    `timeout_seconds` INT DEFAULT 20,
    `retry_count` INT DEFAULT 1,
    `enabled_as_gate` TINYINT(1) DEFAULT 0 COMMENT '是否作为交易闸门',
    `fail_closed` TINYINT(1) DEFAULT 0 COMMENT 'AI失败时是否拒绝交易',
    `buy_threshold` DECIMAL(8,4) DEFAULT 70.0000 COMMENT '买入通过评分阈值',
    `sell_threshold` DECIMAL(8,4) DEFAULT 40.0000 COMMENT '卖出/减仓提醒阈值',
    `config_version` INT DEFAULT 1 COMMENT '配置版本',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY `idx_enabled_source` (`enabled`, `source_type`, `source_id`),
    KEY `idx_strategy` (`strategy_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI交易研判配置表';
```

密钥只保存引用，不保存明文。示例环境变量：`QUANTIA_AI_API_KEY`、`QUANTIA_AI_BASE_URL`、`QUANTIA_AI_MODEL`。

### 5.6 AI 评分结果表：`cn_stock_trade_ai_score`

用于保存某次策略筛选或交易前 AI 研判的输入摘要、输出评分、建议动作和失败状态。该表可被模拟交易、回测和未来实盘共用。

```sql
CREATE TABLE IF NOT EXISTS `cn_stock_trade_ai_score` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `config_id` BIGINT DEFAULT NULL COMMENT '关联 cn_stock_ai_decision_config.id',
    `config_version` INT DEFAULT NULL COMMENT '运行时配置版本快照',
    `source_type` VARCHAR(32) NOT NULL COMMENT 'paper/backtest/live',
    `source_id` BIGINT NOT NULL COMMENT '模拟盘、回测或实盘策略ID',
    `run_id` VARCHAR(64) DEFAULT NULL COMMENT '单次运行ID',
    `signal_id` BIGINT DEFAULT NULL COMMENT '关联 cn_stock_trade_signal.id，可后置回填',
    `strategy_id` BIGINT DEFAULT NULL,
    `strategy_name` VARCHAR(128) DEFAULT NULL,
    `code` VARCHAR(20) NOT NULL,
    `name` VARCHAR(64) DEFAULT NULL,
    `decision_date` DATE NOT NULL COMMENT '研判日期',
    `decision_phase` VARCHAR(32) NOT NULL COMMENT 'pre_buy/pre_sell/post_signal/review',
    `input_hash` VARCHAR(64) NOT NULL COMMENT '输入数据包哈希',
    `prompt_hash` VARCHAR(64) DEFAULT NULL COMMENT '提示词哈希',
    `prompt_version` VARCHAR(64) DEFAULT NULL COMMENT '提示词版本标签',
    `model_name` VARCHAR(128) DEFAULT NULL,
    `input_summary` JSON DEFAULT NULL COMMENT '基础信息、指标、K线窗口等摘要',
    `prompt_messages` JSON DEFAULT NULL COMMENT '实际发送的消息快照，可按安全策略裁剪',
    `raw_response` MEDIUMTEXT DEFAULT NULL COMMENT '模型原始响应',
    `score` DECIMAL(8,4) DEFAULT NULL COMMENT '0-100 综合评分',
    `action` VARCHAR(32) DEFAULT NULL COMMENT 'buy/sell/hold/skip/reduce/watch',
    `confidence` DECIMAL(8,4) DEFAULT NULL COMMENT '0-1 置信度',
    `reason_summary` TEXT DEFAULT NULL COMMENT 'AI 摘要理由',
    `evidence` JSON DEFAULT NULL COMMENT '引用输入字段的关键证据',
    `risk_flags` JSON DEFAULT NULL COMMENT '风险提示',
    `threshold_result` JSON DEFAULT NULL COMMENT '与 buy/sell 阈值比较结果',
    `gate_result` VARCHAR(32) DEFAULT 'not_enabled' COMMENT 'not_enabled/pass/reject/fallback/error',
    `status` VARCHAR(32) DEFAULT 'pending' COMMENT 'pending/succeeded/failed/skipped/timeout',
    `latency_ms` INT DEFAULT NULL,
    `error_message` TEXT DEFAULT NULL,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY `uk_input_phase` (`source_type`, `source_id`, `run_id`, `code`, `decision_phase`, `input_hash`),
    KEY `idx_signal_id` (`signal_id`),
    KEY `idx_code_date` (`code`, `decision_date`),
    KEY `idx_score_action` (`score`, `action`),
    KEY `idx_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI交易研判评分表';
```

`input_summary` 不建议存储完整长 K 线原文，可保存窗口长度、关键 OHLCV 切片、指标摘要和数据哈希；完整数据可通过 `source_type/source_id/run_id/code/decision_date` 重建。对外通知只展示 AI 摘要、评分、关键证据和风险提示，不展示 API key、完整 prompt 或敏感账户信息。

### 5.7 通知配置表：`cn_stock_notification_config`

```sql
CREATE TABLE IF NOT EXISTS `cn_stock_notification_config` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `name` VARCHAR(128) NOT NULL COMMENT '配置名称',
    `channel` VARCHAR(32) NOT NULL COMMENT 'dingtalk/wecom/qq/serverchan/pushplus，第一阶段仅实现 dingtalk',
    `enabled` TINYINT(1) DEFAULT 1 COMMENT '是否启用',
    `source_type` VARCHAR(32) DEFAULT 'paper' COMMENT 'paper/backtest/live/all',
    `source_id` BIGINT DEFAULT NULL COMMENT '指定模拟盘或策略ID，为空表示全部',
    `event_types` JSON DEFAULT NULL COMMENT '启用事件类型列表',
    `webhook_url` TEXT DEFAULT NULL COMMENT 'Webhook URL，应加密或迁移至环境变量',
    `secret_ref` VARCHAR(255) DEFAULT NULL COMMENT '密钥引用，优先使用环境变量名',
    `receiver_config` JSON DEFAULT NULL COMMENT '接收人、群、机器人配置',
    `template_config` JSON DEFAULT NULL COMMENT '模板配置',
    `summary_config` JSON DEFAULT NULL COMMENT '通知摘要字段、排序和展示开关',
    `detail_config` JSON DEFAULT NULL COMMENT '通知详情字段、AI依据、原始参考数据展示上限',
    `rate_limit_per_minute` INT DEFAULT 20 COMMENT '限流',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY `idx_channel_enabled` (`channel`, `enabled`),
    KEY `idx_source` (`source_type`, `source_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='通知配置表';
```

安全建议：`webhook_url` 和密钥不建议明文长期存储。优先存环境变量名，例如 `QUANTIA_DINGTALK_WEBHOOK`、`QUANTIA_DINGTALK_SECRET`。

### 5.8 通知事件表：`cn_stock_notification_event`

用于 outbox、发送状态、失败重试和审计。

```sql
CREATE TABLE IF NOT EXISTS `cn_stock_notification_event` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `event_type` VARCHAR(64) NOT NULL COMMENT 'trade_executed/run_failed/run_summary/risk_alert',
    `source_type` VARCHAR(32) NOT NULL COMMENT 'paper/backtest/live',
    `source_id` BIGINT NOT NULL COMMENT '来源ID',
    `run_id` VARCHAR(64) DEFAULT NULL COMMENT '运行ID',
    `signal_id` BIGINT DEFAULT NULL COMMENT '交易信号ID',
    `trade_id` BIGINT DEFAULT NULL COMMENT '成交ID',
    `channel` VARCHAR(32) NOT NULL COMMENT '通知渠道',
    `config_id` BIGINT DEFAULT NULL COMMENT '通知配置ID',
    `dedupe_key` VARCHAR(128) NOT NULL COMMENT '通知幂等键',
    `title` VARCHAR(255) DEFAULT NULL COMMENT '标题',
    `message_text` MEDIUMTEXT DEFAULT NULL COMMENT '文本消息',
    `message_payload` JSON DEFAULT NULL COMMENT '渠道原始payload',
    `status` VARCHAR(32) DEFAULT 'pending' COMMENT 'pending/sending/sent/failed/skipped',
    `attempt_count` INT DEFAULT 0 COMMENT '发送次数',
    `next_retry_at` DATETIME DEFAULT NULL COMMENT '下次重试时间',
    `last_error` TEXT DEFAULT NULL COMMENT '最后错误',
    `sent_at` DATETIME DEFAULT NULL COMMENT '发送成功时间',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY `uk_dedupe` (`dedupe_key`),
    KEY `idx_status_retry` (`status`, `next_retry_at`),
    KEY `idx_signal` (`signal_id`),
    KEY `idx_source_run` (`source_type`, `source_id`, `run_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='通知事件表';
```

### 5.9 IM 交易指令表：`cn_stock_trade_command`

用于未来通过 IM 确认或下达交易指令。第一阶段可不实现，仅预留设计。

```sql
CREATE TABLE IF NOT EXISTS `cn_stock_trade_command` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `source_channel` VARCHAR(32) NOT NULL COMMENT 'dingtalk/wecom/qq',
    `source_message_id` VARCHAR(128) DEFAULT NULL COMMENT 'IM消息ID',
    `operator_id` VARCHAR(128) DEFAULT NULL COMMENT '操作人外部ID',
    `operator_name` VARCHAR(128) DEFAULT NULL COMMENT '操作人名称',
    `command_type` VARCHAR(32) NOT NULL COMMENT 'confirm_buy/confirm_sell/cancel/adjust',
    `paper_id` BIGINT DEFAULT NULL COMMENT '关联模拟盘',
    `signal_id` BIGINT DEFAULT NULL COMMENT '关联交易信号',
    `code` VARCHAR(20) NOT NULL COMMENT '股票代码',
    `direction` VARCHAR(16) NOT NULL COMMENT 'buy/sell',
    `amount` DECIMAL(20,4) DEFAULT NULL COMMENT '指令数量',
    `value` DECIMAL(20,4) DEFAULT NULL COMMENT '指令金额',
    `price_limit` DECIMAL(20,6) DEFAULT NULL COMMENT '限价，可选',
    `status` VARCHAR(32) DEFAULT 'pending' COMMENT 'pending/approved/rejected/expired/executed/failed',
    `risk_check_json` JSON DEFAULT NULL COMMENT '风控检查结果',
    `request_payload` JSON DEFAULT NULL COMMENT '原始回调内容',
    `expire_at` DATETIME DEFAULT NULL COMMENT '指令过期时间',
    `approved_at` DATETIME DEFAULT NULL COMMENT '确认时间',
    `executed_at` DATETIME DEFAULT NULL COMMENT '执行时间',
    `execution_result` JSON DEFAULT NULL COMMENT '执行结果',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY `uk_channel_message` (`source_channel`, `source_message_id`),
    KEY `idx_signal` (`signal_id`),
    KEY `idx_status` (`status`, `expire_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='IM交易指令表';
```

---

## 6. 策略 API 扩展设计

### 6.1 兼容旧策略

当前策略可能大量使用：

```python
order(code, amount)
order_target(code, target)
order_value(code, value)
order_target_value(code, target_value)
order_target_percent(code, percent)
```

建议扩展为兼容形式：

```python
order(code, amount, reason=None, decision=None, indicators=None, selection=None)
order_target(code, target, reason=None, decision=None, indicators=None, selection=None)
order_value(code, value, reason=None, decision=None, indicators=None, selection=None)
order_target_value(code, target_value, reason=None, decision=None, indicators=None, selection=None)
order_target_percent(code, percent, reason=None, decision=None, indicators=None, selection=None)
```

旧策略无需修改即可运行。新策略可以传入结构化解释。

AI 评分建议不强制要求策略手工传入，而是由引擎在策略筛选结果和下单意图之间统一调用。策略可以选择传入 `selection/indicators` 作为 AI 输入增强数据，系统再补齐基础信息、K 线窗口、账户和风险上下文。

### 6.2 新增辅助 API（未来计划，当前未实现）

> 现状（2026-05-09 复核）：以下 sugar API **尚未实现**。当前策略只能直接传 dict（`decision={'rules': [...]}`）；AI 评分通过引擎统一调用 [quantia/ai_decision/service.py](quantia/ai_decision/service.py)::`score_trade(decision_phase=...)`，策略层无须显式调用。下面示例保留为后续语法糖设计参考。

为了减少策略代码中手工拼 JSON 的成本，未来可考虑提供辅助函数：

```python
# 未实现
record_trade_decision(
    code,
    reason='...',
    rules=[...],
    indicators={...},
    selection=[...]
)

# 未实现
decision_rule(
    name='MA5 上穿 MA20',
    threshold='ma5 > ma20',
    actual={'ma5': ma5, 'ma20': ma20},
    passed=ma5 > ma20,
    note='短期趋势改善'
)
```

AI 研判辅助函数建议放在独立模块，避免策略直接绑定具体模型。当前实现入口为：

```python
# 实际入口（已实现）
from quantia.ai_decision.service import score_trade
result = score_trade(
    source_type='paper',          # 'paper' / 'backtest' / 'live'
    source_id=paper_id,
    code=code,
    decision_date=trade_date,
    decision_phase='post_signal', # 'pre_buy' / 'pre_sell' / 'post_signal' / 'review'
    strategy_context={...},
    indicators={...},
    selection=[...],
)
# result.score / result.action / result.gate_result / result.evidence / result.risks
```

以下 wrapper 形态尚未实现，仅作未来设计参考：

```python
# 未实现
build_ai_decision_context(code, phase='pre_buy', ...)
score_trade_with_ai(context_payload, config_name='default_paper_pre_buy')
```

策略侧可只关心“是否需要 AI 评分”和“把哪些自定义指标交给系统”，具体 provider、prompt、阈值、超时、是否作为 gate 由配置决定。

### 6.3 默认兜底解释

当策略未提供 `reason` 时，系统可以生成兜底解释：

- 买入：`策略触发买入信号，按模拟盘撮合规则成交；该理由由系统根据成交结果生成，非策略显式说明。`
- 卖出：`策略触发卖出/调仓/风控信号，按模拟盘撮合规则成交；该理由由系统根据成交结果生成，非策略显式说明。`

同时写入：

```text
reason_source = generated
```

通知中也应展示“理由来源：系统兜底说明”。

---

## 7. 通知消息设计

通知消息必须采用“摘要优先、详情随后”的结构。用户在钉钉消息列表和手机通知中首先看到结论，点开后再看交易细节、策略依据、AI 评分和原始参考数据。

推荐结构：

```text
标题
摘要总结
    -> 方向、股票、评分、建议动作、成交金额、关键风险、是否需要人工复核
核心结论
    -> 策略理由一句话、AI 理由一句话、gate 结果
详情
    -> 成交信息、规则阈值对比、AI 关键依据、重要原始参考数据、风险提示
链接
    -> 系统详情页、信号详情 API、AI 评分详情 API
```

摘要中只放最重要的 5-8 个字段，详情中再展开数据。这样既能保证通知直观，也避免一条消息过长导致用户错过关键信息。

### 7.1 买入通知模板

```text
【模拟盘买入信号】600016 民生银行

摘要总结：
- 方向：买入
- AI评分：82.5 / 100，建议 buy，Gate 通过
- 成交金额：99,484.00 元，成交后仓位 49.80%
- 核心理由：BOLL 下轨附近反弹，MA5 上穿 MA20
- 关键风险：MA60 仍偏弱，跌破下轨需复核止损

模拟盘：BOLL 下轨策略模拟盘
策略：BOLL 下轨反弹策略
日期：2026-04-27
运行ID：paper-4-20260427-153000

成交信息：
- 方向：买入
- 成交价：3.74
- 数量：26,600 股
- 成交金额：99,484.00 元
- 佣金：29.85 元
- 滑点成本：49.74 元
- 成交后仓位：49.80%

买入理由：
BOLL 下轨附近反弹且 MA5 上穿 MA20，触发买入。

确认数据对比：
1. BOLL 下轨接近度
   阈值：close <= boll_lower * 1.02
   实际：close=3.74，boll_lower=3.67，ratio=1.0191
   结果：通过

2. 均线改善
   阈值：ma5 > ma20
   实际：ma5=3.71，ma20=3.70
   结果：通过

查看详情：
http://localhost:3000/algo/paper?id=4
信号详情：
http://localhost:3000/trade/signal?signal_id=12345
```

若启用 AI 研判，买入通知追加 AI 摘要块：

```text
AI 综合研判：
- 评分：82.5 / 100
- 建议：buy
- 置信度：0.76
- Gate：通过，阈值 buy_threshold=70

AI 关键依据：
1. 日线 close 位于 BOLL 下轨 2% 范围内，且 MA5 已重新站上 MA20。
2. 最近 20 日成交量温和放大，未出现明显放量破位。
3. 当前单票目标仓位 49.8%，未超过模拟盘最大仓位限制。

AI 风险提示：
- 中期 MA60 仍偏弱，若跌破下轨需触发止损复核。
- 评分来自配置版本 default_paper_pre_buy:v3，仅作为辅助研判。
```

### 7.2 卖出通知模板

```text
【模拟盘卖出信号】600016 民生银行

摘要总结：
- 方向：卖出/减仓
- AI评分：38.0 / 100，建议 reduce
- 平仓盈亏：+4,590.72 元，收益率 +4.61%
- 核心理由：止盈阈值达成，MACD 动能减弱
- 关键风险：若继续持有，需要复核止盈回撤阈值

成交信息：
- 方向：卖出
- 成交价：3.92
- 数量：26,600 股
- 成交金额：104,272.00 元
- 佣金：31.28 元
- 印花税：104.27 元
- 滑点成本：52.14 元
- 平仓盈亏：+4,590.72 元
- 收益率：+4.61%

卖出理由：
价格达到止盈阈值且 MACD 柱缩短，触发止盈卖出。

确认数据对比：
1. 止盈阈值
   阈值：return_rate >= 4.5%
   实际：return_rate=4.61%
   结果：通过

2. 动能减弱
   阈值：macd_hist_today < macd_hist_yesterday
   实际：today=0.012，yesterday=0.018
   结果：通过

AI 综合研判：
- 评分：38.0 / 100
- 建议：reduce
- Gate：触发减仓提醒

AI 风险提示：
- 短期收益已达到策略止盈区间，MACD 动能下降。
- 若继续持有，需要重新确认止盈回撤阈值。
```

### 7.3 渠道格式降级

钉钉 markdown 可以使用表格或分段列表。第一阶段以钉钉 markdown 为标准模板，企业微信、QQ、Server 酱等渠道后续通过模板降级适配：

```markdown
| 规则 | 阈值/判定 | 实际数据 | 结果 |
|---|---|---|---|
| BOLL 下轨接近度 | close <= lower * 1.02 | close=3.74, lower=3.67 | 通过 |
| MA5 上穿 MA20 | ma5 > ma20 | ma5=3.71, ma20=3.70 | 通过 |
```

QQ/普通文本渠道不一定支持 markdown 表格，因此模板层需要支持 plain text 降级。AI 评分块也必须支持降级为普通文本，避免重要风险提示在低能力渠道丢失。

### 7.4 AI 依据与重要原始参考数据展示规则

通知中应展示 AI 评价依据和重要原始参考数据，但不应展示完整 prompt、完整长 K 线、API key 或敏感账户信息。推荐分为“摘要可见”和“详情可见”。

摘要可见字段：

- AI 综合评分、建议动作、置信度、gate 结果。
- AI 一句话理由。
- 1-3 条最重要风险提示。
- 最关键的 2-3 个实际指标值，例如 `close`、`ma5`、`ma20`、`boll_lower`、`rsi14`、`macd_hist`。

详情可见字段：

- 股票基础快照：行业、市值、PE/PB、涨跌幅、换手率、停牌/涨跌停状态。
- K 线窗口摘要：数据截止日期、窗口长度、最近 5 根 OHLCV、近 20/60 日涨跌幅、波动率。
- 指标快照：MA/BOLL/MACD/KDJ/RSI/成交量均线等当前值和关键前值。
- 策略筛选证据：通过的筛选阶段、阈值、实际值、排名分数、候选池数量变化。
- 账户与风控快照：当前现金、目标仓位、单票仓位、组合回撤、当日交易次数。
- AI 输出结构：评分、建议、证据、风险、阈值比较、配置版本、模型名称、输入 hash。

不在通知中展示：

- 完整 API key、webhook、secret、券商账号。
- 完整 system prompt 和 user prompt 原文。
- 大段历史 K 线原文。通知只展示摘要和最近关键切片，完整数据通过系统详情页查看。
- 任何未来日期数据或交易日之后才可见的数据。

详情链接应指向系统页面，例如模拟交易详情、交易信号详情或 AI 评分详情。详情 API 需要支持权限控制，避免任何拿到钉钉消息的人都能访问敏感数据。

---

## 8. 通知渠道实现建议

| 渠道 | 发送提醒 | 接收指令 | 推荐度 | 说明 |
|---|---:|---:|---:|---|
| 钉钉群机器人 | 容易 | 中等 | 高 | webhook 简单，适合第一阶段 |
| 企业微信机器人/应用 | 容易 | 中等 | 高 | 通知和确认流程更稳 |
| QQ | 中等 | 中高 | 中 | 多依赖 OneBot 等生态，维护成本较高 |
| 个人微信 | 难 | 难 | 低 | 稳定性和风控风险较高，不建议优先做 |
| Server酱/PushPlus | 很容易 | 难 | 中 | 适合轻量通知，不适合交易指令 |

第一阶段只建议实现钉钉群机器人，目标是先把“成交后通知、签名、去重、重试、模板、AI 评分摘要展示”做成稳定闭环。企业微信保留模块接口和表字段兼容，但不作为第一批验收范围；QQ 和个人微信暂不进入实现计划。

### 8.1 钉钉一期实现边界

钉钉一期建议只实现群机器人 webhook：

- 配置项：`QUANTIA_DINGTALK_WEBHOOK`、`QUANTIA_DINGTALK_SECRET`、启用事件类型、限流参数。
- 安全：支持加签 `timestamp + secret`，不在日志中打印完整 webhook。
- 消息类型：优先 markdown；异常情况下降级为 text。
- 触发事件：`trade_executed`、`run_failed`、可选 `run_summary`。
- 内容：成交信息、策略真实理由、阈值实际值对比、AI 评分摘要、风险提示、详情链接。
- 可靠性：outbox 去重、失败重试、失败不阻塞模拟交易。
- 运维：提供测试发送函数和最小健康检查。

---

## 9. IM 交易指令扩展设计

不要直接实现“收到 IM 消息立即真实下单”。推荐流程：

```text
信号通知
  -> 用户确认
  -> 后端生成 trade_command
  -> 权限校验
  -> 风控校验
  -> 二次确认或人工审批
  -> 实盘交易服务执行
  -> 结果回传 IM
```

必要安全控制：

1. 操作人白名单。
2. IM 平台签名校验。
3. 回调请求防重放。
4. 指令一次性 token。
5. 指令过期时间。
6. 最大单笔金额限制。
7. 最大单日交易金额限制。
8. 禁止重复确认同一 signal。
9. 审计日志。
10. 实盘执行与模拟盘信号解耦。

当前项目已有 `quantia/trade/trade_service.py` 和券商客户端配置基础，但真实交易系统和模拟交易系统需要通过独立的 `trade_command` 队列连接，不能直接在通知回调中调用券商下单。

---

## 10. 与回测系统的复用方案

### 10.1 后端复用

建议新增：

```text
quantia/core/backtest/trade_decision.py
```

提供统一结构：

```python
class TradeDecisionRule:
    pass

class TradeDecisionSnapshot:
    pass

def normalize_decision_payload(payload):
    pass

def build_generated_reason(trade_record):
    pass
```

模拟交易和回测都调用该模块，避免两套理由结构。

### 10.2 前端复用（部分实现，组件抽取待办）

> 现状（2026-05-09 复核）：通用后端 API（`/quantia/api/trade/signal/{list,detail}`）已被 [paper-trading/index.vue](quantia/fontWeb/src/views/paper-trading/index.vue) 与 [algo/backtest-detail.vue](quantia/fontWeb/src/views/algo/backtest-detail.vue) **共同消费**，但前端决策弹窗目前**仍是两份各自实现的代码**，组件抽取尚未完成。

建议后续将交易决策展示抽取为共享组件：

```text
quantia/fontWeb/src/components/trade-decision/
├── TradeDecisionPanel.vue        # 待抽取
├── IndicatorSnapshotPanel.vue    # 待抽取
├── TradeReasonSummary.vue        # 待抽取
└── TradeMarkerTooltip.ts         # 待抽取
```

回测详情页和模拟交易详情页应共同使用。通知消息模板使用同一套后端结构生成摘要（已落地）。

### 10.3 API 复用

建议新增通用 API：

```text
GET /quantia/api/trade/signal/detail?source_type=paper&source_id=4&trade_id=xxx
GET /quantia/api/trade/signal/list?source_type=paper&source_id=4
GET /quantia/api/trade/decision?signal_id=xxx
```

模拟交易详情接口可以内嵌最近或全部决策数据；回测详情接口也可以逐步迁移到该结构。

---

## 11. 开发计划

### Phase 1：钉钉通知基础设施 ✅ 已完成 (2026-05-07)

> 验收记录：
> - 模块文件：`quantia/notification/{__init__,service,templates}.py`、`channels/{base,dingtalk}.py`。
> - 数据库表：`cn_stock_notification_config` + `cn_stock_notification_event`（uq_dedupe_key）。
> - 接入点：`quantia/paper_trading/paper_engine.py` 成交落库后调用 `notify_trade_records()`。
> - 测试：`tests/test_notification_phase1.py` 10/10 通过（钉钉签名、payload、去重、出 box、process_pending、失败不阻塞；2026-05-09 复跑确认）。
> - 生产事件：`cn_stock_notification_event` 已观测到 sent + skipped 行（依赖 .env webhook）。
> - 修复记录：`tools/diagnose_dingtalk.py` 排查脚本；`paper_engine.py` 修复 1062 race condition（commit `a118c82`）。

目标：模拟交易成交后能通过钉钉发送基础通知，具备配置、签名、去重、失败重试能力。

开发内容：

1. 新增 `quantia/notification` 模块。
2. 实现 `NotificationChannel` 抽象。
3. 实现钉钉 webhook channel。
4. 新增 `cn_stock_notification_config`。
5. 新增 `cn_stock_notification_event`。
6. 在 `paper_engine.py` 成交落库后写入通知事件。
7. 实现同步发送和失败状态记录。
8. 支持配置开关：按模拟盘、按事件类型启用。
9. 保留企业微信、QQ 等 channel 抽象，不在第一阶段实现。

验收标准：

- 手工运行模拟盘后，能生成通知事件。
- 钉钉能收到买入/卖出通知。
- 重复运行不会重复发送同一事件。
- webhook 失败时交易主流程不失败。

### Phase 2：策略真实理由与决策留痕 ✅ 已完成 (2026-05-07)

> 验收记录：
> - 新模块：`quantia/core/backtest/trade_decision.py`（normalize/resolve_reason/compute_signal_hash/serialize）；`quantia/core/backtest/trade_signal_store.py`（DDL + persist + link + fetch）。
> - 4 张新表（按需创建，DDL 幂等，单独事务，列结构与 §5.1–§5.4 完全一致）：`cn_stock_trade_signal`（含 `target_amount/target_percent` 与 Phase 4 预留的 `ai_score_id/ai_score/ai_action/ai_gate_result`）、`cn_stock_trade_decision`、`cn_stock_trade_indicator_snapshot`（结构化 OHLCV + ma/boll/rsi/macd/kdj/extra JSON）、`cn_stock_trade_selection_snapshot`。
> - paper_engine 改造：`_order_proxy(..., reason, decision, indicators, selection, order_api, target_amount, target_percent)`；5 个 `order_*` lambda 全部接受 **kw 兼容旧策略；`order_target` 自动捕获 `target_amount`，`order_target_percent` 自动捕获 `target_percent`；撮合后建立 `signal_inputs` 平行表；主事务提交后 capture trade_id 并 `link_signal_to_trade`；信号持久化失败仅 warning，不回滚成交。
> - 通知模板扩展：`reason` + `reason_source` + `decision_rules` 渲染为「交易理由（来源标注）」与「决策规则对比」表，最多 5 行；`reason_source=generated` 时显式标注「系统兜底说明（非策略显式提供）」。
> - 通知服务：`enqueue_trade_notification(..., signal_id=...)` 自动 `fetch_signal_with_decision()` 注入策略真实 reason。
> - 测试：`tests/test_trade_signal_phase2.py` 16/16 通过（含结构化 OHLCV 拆分、target_percent 持久化校验）；与 Phase 1 / 1062 修复 / sandbox / recorder / recent_fixes 共 58/58 通过。

目标：通知中的交易理由来自策略运行时真实数据。

开发内容：

1. 扩展 `order_*` API，支持 `reason/decision/indicators/selection`。
2. 新增 `cn_stock_trade_signal`。
3. 新增 `cn_stock_trade_decision`。
4. 新增 `cn_stock_trade_indicator_snapshot`。
5. 新增 `cn_stock_trade_selection_snapshot`。
6. 撮合成交后将 `signal_id` 与 `trade_id` 关联。
7. 通知模板读取真实决策数据。
8. 未提供理由时生成兜底说明，并标记 `reason_source=generated`。

验收标准：

- 新策略传入 `reason/decision` 后，数据库能完整保存。
- 通知中能展示阈值、实际值、判断结果。
- 旧策略不传理由也能正常运行。
- 旧策略通知明确标记理由来源为系统兜底。

### Phase 3：回测与前端复用 ✅ 已完成 (2026-05-07)

> 验收记录：
> - 回测引擎接入：`quantia/core/backtest/portfolio_engine.py` 5 个 `order_*` 全部接受 `**kw`（旧策略调用 100% 兼容），`_submit_order` 透传 `reason/decision/indicators/selection/order_api/target_amount/target_percent`；`_execute_single_order` 在 buy/sell 两条分支同时 `_signal_inputs.append(order_info)`，与 `_trade_records` 严格 1:1 对应。新增 `order_target_percent` API 与 paper 引擎齐平。
> - 持久化复用：`quantia/core/backtest/trade_signal_store.py` 新增 `persist_backtest_signals(backtest_id, run_id, trade_records, signal_inputs)`，复用 Phase 2 的 `persist_signal_with_relations`；`source_type='backtest'` 写入同一套 `cn_stock_trade_signal/decision/indicator_snapshot/selection_snapshot` 表。回测主结果落库后由 `RunPortfolioBacktestHandler` 与 `StartPortfolioBacktestHandler` 各自调用，失败仅 warning，不回滚回测主结果。回测无独立 `cn_stock_backtest_trade` 行，故 `trade_id` 字段保持 NULL，复用通过 `(source_type, source_id, signal_date, code, direction)` 关联。
> - 详情数据扩展：`fetch_signal_with_decision()` 在 Phase 2 基础上追加 `indicators` 与 `selection` 两块（结构化 OHLCV + ma/boll/rsi/macd/kdj/extra；候选筛选阶段、阈值、实际值、排名）。新增 `list_signals_for_source(source_type, source_id)` 用于回测/模拟盘列表。
> - 统一 API：新增 `quantia/web/tradeSignalHandler.py`，注册路由 `GET /quantia/api/trade/signal/list?source_type=&source_id=` 与 `GET /quantia/api/trade/signal/detail?signal_id=`；前端在 backtest-detail 与 paper-detail 页面可消费同一接口拿到一致的决策依据展示数据。
> - 测试：`tests/test_trade_signal_phase3.py` 9/9 通过（2026-05-09 复跑确认；早期版本 11 用例后合并 / 重命名）。
> - 不变性保证：未触碰前端 backtest-detail.vue / paper detail Vue 组件（已自然兼容 `trade.reason`）；未改动 `cn_stock_backtest_portfolio` 与 `cn_stock_backtest_trade` schema；未改动 paper_engine 主撮合事务。
>
> Phase 3 扩展（同日提交）：
> - 前端零改动可见性闭环：`TradeRecord` 新增 `reason` / `reason_source` slot；`portfolio_engine` 与 `paper_engine` 在 buy/sell append 后调用 `trade_decision.resolve_reason` 写入 `trade.reason`，写入 `result_json['trades']`；现有 `quantia/fontWeb/src/views/algo/backtest-detail.vue` 已读取 `trade.reason` 与 `decisionRows`，无需修改即可看到策略真实理由（旧策略显示「系统兜底说明」标记）。
> - 钉钉发送内容后台可查：新增 `quantia/web/notificationAdminHandler.py`，注册 `GET /quantia/api/notification/event/{list,detail}`；`list` 支持 `paper_id/status/channel/event_type/code/since/limit` 过滤（status/channel 白名单校验，limit ≤ 500），返回 payload/response 预览；`detail` 返回完整 payload/response/error 用于排查发送失败。`cn_stock_notification_event` 表本身不存储 webhook URL/secret，因此该接口不会泄露密钥。
> - 测试：`tests/test_notification_admin_phase3.py` 9/9 通过（2026-05-09 复跑确认）。
>
> Phase 3 补丁（2026-05-09，paper-trading 前端可见性补齐）：
> - **审计发现**：上述「未触碰前端 paper detail Vue 组件」描述并不等于「前端可见」。`quantia/web/paperTradingHandler.py` 的 trades 查询直接 `SELECT ... FROM cn_stock_backtest_trade WHERE paper_id=...`，未 JOIN `cn_stock_trade_signal`，故 reason / signal_id / ai_* 字段从未送达前端；同时 `quantia/fontWeb/src/views/paper-trading/index.vue` 的「下单详情」表 12 列里既无「交易原因」列，也没有点击查看决策的入口，跟 backtest-detail 页面行为不一致。文档原 §13.2 #5 / §12.6 的 ✅ 仅对回测一侧成立，对模拟盘不成立。
> - 后端 fix：`paperTradingHandler.py` trades SELECT 改为 `LEFT JOIN cn_stock_trade_signal s ON s.trade_id = t.id AND s.source_type='paper' AND s.source_id=...`，多返回 `signal_id / reason / reason_source / ai_score / ai_action / ai_gate_result`；旧库（`cn_stock_trade_signal` 不存在时）走原 SELECT 兼容路径，行为零回归。
> - 前端 fix：`paper-trading/index.vue` 在「下单详情」表追加「交易原因」列（带 `reason_source=generated` / `AI <action> <score>` 标签）+「决策依据」操作列；点击 → 通过 `request.get('/quantia/api/trade/signal/detail', { signal_id })` 调用 Phase 3 已有路由，弹窗里展示成交摘要 + 策略理由 + AI 评分块 + 决策规则对比表（指标/阈值/实际/通过/权重）+ 指标快照表，与 backtest-detail 弹窗信息口径一致。
> - 兼容性：旧策略 / 无 signal 行 → reason 列显示 `--`，决策依据列显示 `--`；不调用 detail API；与之前 174 用例无任何回归。

目标：回测详情和模拟交易详情复用同一套交易决策展示。

开发内容：

1. 新增 `trade_decision.py` 通用结构。
2. 回测引擎接入 `TradeSignal/TradeDecision`。
3. 模拟交易详情接口返回 `signals/decisions/snapshots`。
4. 回测详情接口返回相同结构。
5. 抽取前端 `TradeDecisionPanel` 等组件。（**待办**：当前两个页面各自实现弹窗，未抽取）
6. 回测详情页和模拟交易详情页共同使用同一组共享后端 API。（**已落地**）

验收标准：

- 回测交易和模拟交易都能展示同样风格的决策依据。
- 指标快照与 K 线图上的交易日期一致。
- 前端 tooltip、详情面板、通知内容中的关键数据一致。

### Phase 4：AI 综合评分扩展 ✅ 已完成 (2026-05-07)

> 验收记录：
> - 新模块：`quantia/ai_decision/{__init__,schema,config,context_builder,prompt_renderer,service}.py` + `providers/{__init__,openai_compatible}.py`。Provider 仅用 stdlib `urllib`，未新增供应链依赖。
> - 新增 2 张表（DDL 幂等，§5.5/§5.6 严格对齐）：`cn_stock_ai_decision_config`（含 enabled/source_type/source_id/strategy_id/provider/model/base_url/api_key_ref/system_prompt/user_prompt_template/output_schema/temperature/max_tokens/timeout/retry/enabled_as_gate/fail_closed/buy_threshold/sell_threshold/config_version）、`cn_stock_trade_ai_score`（含 input_summary/prompt_messages/raw_response/score/action/confidence/reason_summary/evidence/risk_flags/threshold_result/gate_result/status/latency_ms/error_message + uk_input_phase 唯一键）。
> - 决策流：`build_input_summary` 强制按 `decision_date` 截断 K 线（§14.6 防未来函数）；`compute_input_hash` / `compute_prompt_hash` 固化复现键；`render_messages` 提供默认 system+user prompt + `{{ var }}` 占位符渲染；`OpenAICompatibleProvider` 走 `/v1/chat/completions` + `response_format=json_object`；`normalize_ai_payload` 宽松解析（缺字段/非法 action/数值越界自动 clamp）。
> - 接入点：
>   - `paper_engine.py` 主事务提交后的 signal 持久化循环中：按 `(source_type='paper', source_id=paper_id)` 加载配置；启用时调用 `score_trade(decision_phase='post_signal')`，结果通过 `persist_signal_with_relations(ai_score_id, ai_score, ai_action, ai_gate_result)` 与 signal 关联；任何 AI 异常仅 warning，不影响交易主事务（§3.2 通知不阻塞交易主流程同样适用 AI）。
>   - `trade_signal_store.persist_backtest_signals` 同样路径接入 `(source_type='backtest', source_id=backtest_id)`。
>   - 持久化扩展：`persist_signal_with_relations` 接受 `ai_score_id/ai_score/ai_action/ai_gate_result`，使用 `ON DUPLICATE KEY UPDATE ... COALESCE(...)` 保护已有评分不被空值覆盖。
>   - `fetch_signal_with_decision` 同步返回 ai_* 字段。
> - 通知模板：新增 `_build_ai_block`，渲染评分/动作/置信度/Gate 标签/AI 摘要/最多 3 条证据/最多 3 条风险；保持「摘要 → 决策规则 → AI → 详情」顺序（§7 摘要在前）。`enqueue_trade_notification` 自动从 signal + ai_score 表加载 confidence/reason_summary/evidence/risk_flags 注入模板上下文；缺省时 AI 块自动隐藏（与 Phase 1/2/3 通知格式 100% 兼容）。
> - 安全（§3.7 / §14.3）：
>   - `api_key` **不**进数据库、**不**进日志，仅通过 `api_key_ref` 引用环境变量（默认 `QUANTIA_AI_API_KEY`）。
>   - 通知中不展示完整 prompt、原始 raw_response、长 K 线（仅 `reason_summary`/`evidence`/`risk_flags`）。
>   - `cn_stock_trade_ai_score.uk_input_phase` 同 (source/run/code/phase/input_hash) 幂等，重复调用不双写。
> - Gate 行为对齐 §3.5 / §14.8：
>   - 默认 `enabled=0` → `STATUS_SKIPPED`，gate=`not_enabled`，**完全不调用模型**。
>   - `enabled=1, enabled_as_gate=0` → 仅留痕 + 通知摘要展示，**交易结果不变**。
>   - `enabled=1, enabled_as_gate=1` → 买入 `score >= buy_threshold` 通过；卖出 `score <= sell_threshold` 通过；其余 `reject`。
>   - 失败/超时按 `fail_closed` 决定 `fallback`（默认放行）或 `reject`，错误原因落库。
> - 测试：`tests/test_ai_decision_phase4.py` 28/28 通过（覆盖文档 §13.2 场景 6/7/8/9：禁用、启用-非 gate、gate-pass、gate-reject、超时-fail_closed、超时-放行、非法 JSON、prompt 版本化 hash、剔除未来 K 线、模板含/不含 AI 块、配置 `to_dict` 不泄漏密钥）；含 Phase 1/2/3、portfolio_backtest、recent_fixes、paper_trading 共 **202/202 通过**。

目标：策略筛选出的股票在买入前或卖出前可以生成 AI 综合评分，并将评分、建议动作、关键依据和风险提示落库，供通知、模拟交易详情、回测分析复用。

开发内容：

1. 新增 `quantia/ai_decision` 模块。
2. 新增 `cn_stock_ai_decision_config`。
3. 新增 `cn_stock_trade_ai_score`。
4. 实现股票基础信息、常用指标、K 线窗口、策略筛选原因、账户风控上下文的数据包构造。
5. 实现 prompt 模板渲染和 JSON 输出解析。
6. 支持 provider/model/prompt/temperature/max_tokens/timeout/threshold/gate 配置。
7. 默认 AI 只留痕和通知展示，不改变交易结果。
8. 可配置启用 AI gate，根据评分决定是否放行买入或触发卖出复核。
9. 通知模板展示 AI 评分摘要、关键证据、风险提示和配置版本。

验收标准：

- AI 禁用时，策略和通知流程完全不受影响。
- AI 启用但不作为 gate 时，交易照常执行，评分结果可追溯。
- AI 作为 gate 时，低于买入阈值的信号被标记为 `reject`，并保留策略原始信号。
- AI 超时或返回格式错误时，按 `fail_closed` 配置决定放行或拒绝，并落库错误原因。
- 修改 prompt 后，新交易记录保存新的 `prompt_version/prompt_hash`，历史记录不被覆盖。

### Phase 5：前端配置管理页面 ✅ 已完成 (2026-05-07)

> 验收记录：
> - 后端模块：
>   - `quantia/web/notificationConfigHandler.py`：`list/detail/save/delete/test_send/retry_event` 6 个 API + 服务函数。
>   - `quantia/web/aiDecisionConfigHandler.py`：AI 配置 `list/detail/save/delete` 4 个 API + 服务函数。
>   - 路由注册（`quantia/web/web_service.py`）：
>     - `GET  /quantia/api/notification/config/list`、`/detail`
>     - `POST /quantia/api/notification/config/save`、`/delete`
>     - `POST /quantia/api/notification/config/test_send`
>     - `POST /quantia/api/notification/event/retry`
>     - `GET  /quantia/api/ai/config/list`、`/detail`
>     - `POST /quantia/api/ai/config/save`、`/delete`
> - 配置版本化（§3.6）：
>   - `cn_stock_notification_config` 自动迁移补齐 `config_version` 列；`UPDATE` 时使用 `config_version=COALESCE(config_version,1)+1`，新建为 1。
>   - `cn_stock_ai_decision_config` 同样语义；保存自动 `+1`。历史 `cn_stock_trade_ai_score` 已固化 `config_version + prompt_hash + input_hash`，前端修改 prompt/阈值不会改写历史评分（§14.7）。
> - 安全（§3.7 / §14.3）：
>   - 后端校验拒绝写入：`webhook_url` / `webhook` / `secret` / `secret_value` / `api_key` / `apiKey` / `token` / `password` 字段；`webhook_env` / `api_key_ref` 中含 `/`、`http`、空格、以 `sk-` 或 `Bearer ` 开头时直接 400 拒绝。
>   - 响应永不回显环境变量明文，仅返回 `webhook_env/secret_env/api_key_ref` 引用名 + `webhook_is_configured/secret_is_configured/api_key_is_configured` 布尔值（基于 `os.getenv` 当前进程视角）。
>   - 测试发送 `send_test_message` 使用专用 dedupe `test|<channel>|<paper_id>|<timestamp>`，与真实交易事件隔离；未启用或 webhook 未注入时返回 `skipped`，不抛异常、不影响业务流程。
>   - 单事件重试 `retry_event` 仅重置目标事件状态为 pending，不会触发批量重发。
> - 数值范围校验（前端 + 后端双重）：`temperature 0–2`、`max_tokens 1–32000`、`timeout_seconds 1–300`、`retry_count 0–5`、`buy_threshold/sell_threshold 0–100`；`enabled_as_gate=1 + enabled=0` 自动纠正为 `enabled=1`（与 §3.5 一致：gate 启用必须先启用 AI）。
> - 前端：
>   - `quantia/fontWeb/src/api/settings.ts`：CRUD/test_send/retry 全套 axios 客户端 + TS 类型定义。
>   - `quantia/fontWeb/src/views/settings/notification.vue`：通知配置列表 + 编辑弹窗 + 测试发送按钮 + 删除；摘要/详情 JSON 编辑。
>   - `quantia/fontWeb/src/views/settings/ai-config.vue`：AI 配置列表 + 编辑弹窗（provider/model/base_url/api_key_ref + system/user prompt + temperature/tokens/timeout/retry + buy/sell threshold + gate/fail_closed 开关）。
>   - 路由：`/settings/notification` 和 `/settings/ai-config` 注册到 `Layout`，左侧菜单图标 `Setting`。
> - 测试：`tests/test_phase5_config_api.py` 25/25 通过（覆盖：保存版本=1 → 更新+1；拒绝 webhook_url/secret 明文写入；env 字段含 URL 拒绝；非法 channel/event_type/provider/source_type 拒绝；范围外 temperature/buy_threshold/timeout 拒绝；gate 隐含 enabled；list/get/delete；webhook_is_configured / api_key_is_configured 反映当前 env；test_send 在 webhook 缺失时 skipped；retry 不存在事件返回错误；响应 dict 不含任何密钥字段；2026-05-09 复跑确认）。
> - 联跑全量回归 **285/285 通过**（Phase1 6 + Phase2 16 + Phase3 11 + Phase3 admin 10 + Phase4 28 + Phase5 24 + portfolio_backtest 16 + recent_fixes 21 + paper_trading 138 + scheduler 15）。
> - 部署提示：前端新增 2 个 .vue + 1 个 .ts，需要在 `quantia/fontWeb/` 下执行 `npm run build` 后将 `dist/` 同步到 `quantia/web/static/` 才会在生产 SPA 中可见；后端 API 部署立即生效。

目标：用户可以在前端配置通知渠道、通知模板、AI 研判参数和展示范围，同时敏感密钥仍由环境变量或后端安全配置管理。

开发内容：

1. 新增通知配置 API。
2. 新增通知事件列表 API。
3. 新增通知重试 API。
4. 新增 AI 配置 API。
5. 前端新增通知设置页面。
6. 前端新增 AI 研判配置页面。
7. 支持测试发送钉钉消息。
8. 支持按模拟盘、策略、事件类型启用或关闭通知。
9. 支持调整通知摘要字段、详情字段、AI 依据展示上限。
10. 支持调整 prompt 模板、模型参数、评分阈值、是否启用 gate。
11. 保存配置时生成 `config_version`，历史运行快照不被覆盖。

前端配置页面建议包含：

- 通知总开关、钉钉 channel 开关、测试发送按钮。
- 模拟盘/策略适用范围选择器。
- 事件类型多选：买入、卖出、异常、每日汇总、AI 拒绝。
- 摘要字段排序器：方向、股票、评分、成交额、仓位、核心理由、关键风险。
- 详情字段开关：成交明细、规则阈值、指标快照、AI 证据、原始参考数据摘要。
- AI provider/model/base_url 引用、prompt 编辑器、JSON schema 编辑器。
- AI 数据包范围：K 线窗口、周/月 K、基本面、市场上下文、账户风控上下文。
- AI gate 配置：启用状态、买入阈值、卖出阈值、失败策略、超时时间。

验收标准：

- 前端可以启用/禁用钉钉通知并测试发送。
- 前端可以调整摘要和详情展示字段，通知中摘要始终位于详情之前。
- 前端可以调整 AI prompt、阈值、数据包范围并生成新版本。
- 密钥明文不会出现在前端响应、浏览器控制台和通知事件日志中。
- 旧版本配置产生的历史 AI 评分记录不受新配置影响。

### Phase 6：IM 指令确认 ✅ 已完成 (2026-05-07)

> 验收记录：
> - 总开关默认关闭：`QUANTIA_IM_COMMAND_ENABLED` 未设置或非 truthy 时，回调 handler 直接返回 `status=disabled` HTTP 503，不触发任何 DB 写入。生产部署默认即「只接收策略信号、不开放手动确认」，作为后期扩展再开。测试与验证可临时设 `QUANTIA_IM_COMMAND_ENABLED=1` 走完整路径。
> - 后端模块：
>   - `quantia/im/schema.py`：幂等创建 `cn_stock_trade_command`（§5.9 全字段）+ `cn_stock_im_operator_whitelist` 两表。
>   - `quantia/im/signature.py`：钉钉 HMAC-SHA256 签名校验，时间窗 ≤ 300 秒、常量时间比较、URL-encode 兼容。
>   - `quantia/im/service.py`：`is_enabled` / `handle_dingtalk_callback` / 操作人白名单 CRUD / 风控（单笔金额、单日金额、同 signal 重复确认）/ 指令落库 / 文本解析。
>   - `quantia/web/imCommandHandler.py`：Tornado 7 个 handler（status / callback / command list+detail / operator list+save+delete）。
>   - `quantia/web/web_service.py`：注册 `/quantia/api/im/*` 7 条新路由。
> - 安全 / 审计（§9 + §12.7）：
>   - **签名校验**：缺失 `secret/timestamp/sign`、timestamp 解析失败、超出 300 秒时间窗、签名不匹配 → 返回 `signature_failed`，不落库（不暴露内部状态给探测者）。
>   - **操作人白名单**：未在 `cn_stock_im_operator_whitelist` 启用的 `operator_id` → 返回 `unauthorized`，**仍落库一条 status=unauthorized 的记录用于审计**。
>   - **防重放**：`UNIQUE(source_channel, source_message_id)` + 入口先查重，重复 message_id 第二次回调返回 `duplicate` 并复用第一次的 `command_id`，DB 中只一条记录。
>   - **指令过期**：每条 approved 指令写 `expire_at = now + QUANTIA_IM_COMMAND_TTL_SECONDS`（默认 300s），Phase 7 真实下单前必须再次校验未过期。
>   - **风控落库**：`risk_check_json` 含每项 check 的 `name/limit/actual/passed`；失败时 `status=rejected` 仍落库，便于复盘攻击/误操作。
>   - **金额限制**：`QUANTIA_IM_MAX_SINGLE_VALUE`（默认 10w）单笔上限 + `QUANTIA_IM_MAX_DAILY_VALUE`（默认 50w）按 `(operator_id, channel, today)` 聚合限额。
>   - **同信号唯一确认**：同一 `signal_id` 已有 `approved/executed` 命令 → 后续 confirm_buy/confirm_sell 拒绝，避免双倍下单。
>   - **禁止直接调券商**：`handle_dingtalk_callback` 只写入 `cn_stock_trade_command`，永不调用 `quantia/trade/trade_service.py`；Phase 7 才接入。
>   - **完整请求 / 响应审计**：`request_payload` 保留 callback 原始 body；handler 返回 `risk_result` 让前端展示拒绝原因。
> - 测试：`tests/test_im_command_phase6.py` 22/22 通过，覆盖：默认关闭 / truthy 取值 / disabled 不写库 / 签名缺组件 / 时间窗 / round-trip / 不匹配 / 失败不写库 / 操作人 CRUD 幂等 / 非法 ID 拒绝 / 未授权落审计 / 单笔超限 / 日累计超限 / 同信号重确认拒绝 / 防重放 duplicate / 非法 command_type / 非法 direction / 文本解析 / payload 合并 / happy-path 字段完整 / 默认 max/ttl 读取。
> - 联跑全量回归 **308/308 通过**（Phase1 6 + Phase2 16 + Phase3 11 + Phase3 admin 10 + Phase4 28 + Phase5 25 + Phase6 22 + portfolio_backtest 16 + recent_fixes 21 + paper_trading 138 + scheduler 15）。
> - 部署提示：
>   - 生产环境**默认关闭**手动确认；如需在测试环境开启，导出环境变量：
>     ```bash
>     export QUANTIA_IM_COMMAND_ENABLED=1
>     export QUANTIA_DINGTALK_CALLBACK_SECRET=<钉钉机器人加签 secret>
>     export QUANTIA_IM_MAX_SINGLE_VALUE=100000   # 可选
>     export QUANTIA_IM_MAX_DAILY_VALUE=500000    # 可选
>     export QUANTIA_IM_COMMAND_TTL_SECONDS=300   # 可选
>     ```
>   - 后端 web 重启后即生效（schema 自动迁移）。前端管理页（指令列表 / 白名单管理）将在 Phase 7 一起补 UI；当前可通过 API 直接管理白名单。
>
目标：支持通过钉钉对交易信号进行确认或忽略；企业微信作为后续渠道扩展。

开发内容：

1. 新增 `cn_stock_trade_command`。
2. 实现 IM 回调 API。
3. 实现签名校验和操作人白名单。
4. 实现指令解析。
5. 实现指令过期与防重放。
6. 实现风控检查。
7. 暂时只写入指令表，不直接实盘下单。

### Phase 7：实盘交易连接 ✅ 已完成 (2026-05-07)

> 验收记录：
> - 主开关默认关闭：`QUANTIA_LIVE_TRADING_ENABLED` 未设置时，`execute_pending_commands()` 直接返回 `{"status": "disabled"}` 且**不读不写 DB**；`/quantia/api/live/execute_pending` 返回 HTTP 503。生产部署默认即此状态。
> - Broker 抽象（`quantia/live/executor.py`）：
>   - `BrokerAdapter` 协议 + `BrokerOrderResult` dataclass。
>   - 默认 `DryRunBroker`：永不调用真实券商，只返回带 `DRY-` 前缀的模拟 order_id；测试与体检用。
>   - `register_broker(name, adapter)` 注入真实券商实现；通过 `QUANTIA_LIVE_BROKER` env 切换。仓库内**未绑定任何 broker client**，与 `quantia/trade/trade_service.py` 解耦，避免误用。
> - 二次风控（执行前再校验，不依赖 Phase 6 当时的快照）：
>   1. `expire_at > now`，否则 status=expired；
>   2. `operator_id` 仍在 `cn_stock_im_operator_whitelist` 启用列表内；
>   3. 单笔金额 ≤ `QUANTIA_IM_MAX_SINGLE_VALUE`（实时读取，可热更）；
>   4. 当日 `(operator_id, channel, today)` 累计 ≤ `QUANTIA_IM_MAX_DAILY_VALUE`；
>   5. 同 `signal_id` 在其它指令上未出现 `status='executed'`；
>   6. 当前在 `QUANTIA_TRADING_HOURS`（如 `09:30-11:30,13:00-15:00`，未配置即不限）窗口内。
>   - 任一未通过 → 状态写入 `expired/rejected`，并把完整 `risk` 列表落 `execution_result`。
> - 状态回写 + IM 反馈：
>   - 成功 → status=executed + executed_at + execution_result（含 broker name + order_id + filled_amount + filled_price + raw）。
>   - 失败 → status=failed + execution_result（含 broker error + risk）。
>   - **每条状态变更都通过 Phase 1 outbox 写一条 `event_type='trade_executed'` 通知**，dedupe 为 `sha256("trade_executed|<command_id>|<status>")`，保证同一指令一次通知；通知模块未配置时静默跳过，不影响执行流。
> - 异常隔离：broker `place_order` 抛异常被捕获 → 该指令 status=failed + error 记录，循环继续处理后续指令；不影响其它命令。
> - 幂等：`execute_pending_commands` 仅扫 `status='approved'`；已执行/已拒绝/已过期/已失败的指令不会被重复处理（DB WHERE 过滤 + 状态机单向迁移）。
> - 路由（`quantia/web/liveTradingHandler.py`）：
>   - `GET  /quantia/api/live/status` → `{enabled, broker, trading_hours}`。
>   - `POST /quantia/api/live/execute_pending`（body: `{limit?: 1-100}`）→ 触发一次扫描，返回执行统计；总开关关闭时 503。
> - 测试：`tests/test_live_trading_phase7.py` 17/17 通过：默认关闭 / disabled 不写 DB / DryRun happy path（含通知 outbox）/ 过期 → expired / 操作人移除 → rejected / 单笔超限 → rejected / 时段限制 / 自定义 broker 注入 / 注册类型校验 / broker 异常隔离 / 同 signal 二次执行阻断 / 仅扫 approved / 时段解析 / DryRun 兜底返回 order_id。
> - 联跑全量回归 **328 passed / 1 known-failed = 329 collected**（2026-05-09 复跑；分布：Phase1 10 + Phase2 16 + Phase3 9 + Phase3 admin 9 + Phase4 28 + Phase5 25 + Phase6 22 + Phase7 17 + portfolio_backtest + recent_fixes + paper_trading + scheduler）。仅有的一处失败 `tests/test_paper_trading.py::TestEnsureTradeAndPositionTables::test_ensure_trade_table_migrates_executed_at` 与 Phase 1–7 业务无关（migration smoke test 受历史 schema 影响），不阻塞功能验收。
> - 部署提示：
>   - 生产**默认即安全状态**（kill-switch 关闭 + DryRunBroker）。
>   - 启用真实交易需：
>     ```bash
>     export QUANTIA_LIVE_TRADING_ENABLED=1
>     export QUANTIA_LIVE_BROKER=<已注册的 broker name>
>     export QUANTIA_TRADING_HOURS="09:30-11:30,13:00-15:00"  # 可选
>     # 同时确保 Phase 6 的 QUANTIA_IM_COMMAND_ENABLED + 钉钉签名 + 白名单已就绪
>     ```
>     并在启动入口（如 `quantia/web/web_service.py` 启动前）显式 `live.register_broker("xxx", MyAdapter())`。
>   - 调度建议：通过 cron 或 supervisord 定期 POST `/quantia/api/live/execute_pending`（如每 30 秒一次，limit=20）；或在 broker 进程内嵌循环。仓库不预置调度，避免与未配置环境的部署冲突。

> Phase 6 + 7 前端 UI 补齐 (2026-05-07)：
> - 新增 `quantia/fontWeb/src/api/imLive.ts`：覆盖 `/quantia/api/im/*` 与 `/quantia/api/live/*` 全部 9 个接口的 TS 类型 + axios 客户端。
> - 新增 `quantia/fontWeb/src/views/settings/im-operator.vue`：操作人白名单 CRUD，顶部展示 IM 总开关 / 单笔上限 / 单日上限 / TTL，禁用 wecom（占位）。
> - 新增 `quantia/fontWeb/src/views/settings/im-commands.vue`：指令列表（含 status/paper_id 过滤、分页），点击「详情」弹窗以 JSON 形式显示 `risk_check` / `request_payload` / `execution_result`，便于审计排查。
> - 新增 `quantia/fontWeb/src/views/settings/live-trading.vue`：实盘开关展示 + 单次手动「触发执行」按钮，结果以统计卡 + 明细表呈现 (`processed/executed/rejected/expired/failed` + 每条 command_id/order_id/error)；总开关关闭时按钮禁用并提示。
> - `src/router/index.ts` 在 `/settings` 路由组内追加 `im-operator`、`im-commands`、`live-trading` 三页。生产部署需在 `quantia/fontWeb/` 下 `npm run build` 后同步 `dist/` 到 `quantia/web/static/` 才生效。
>
> 联跑全量回归 **328 passed / 1 unrelated failure 仍维持**（前端纯客户端，仅静态资源变更）。

#### Phase 6 + 7 完整性审计（2026-05-07）

逐项核对后端 + 前端 + 安全约束：

| 维度 | 状态 | 说明 |
|---|---|---|
| Phase 6 双开关默认关闭 | ✅ | `QUANTIA_IM_COMMAND_ENABLED` 不设置 → 503，零 DB 操作 |
| Phase 7 双开关默认关闭 | ✅ | `QUANTIA_LIVE_TRADING_ENABLED` 不设置 → 503，零 DB 操作；即使开关打开，broker 默认 `dry_run` 永不下真单 |
| Phase 6 → Phase 7 的金额双计算 | ✅ 已复核 | Phase 6 入库前 `_daily_used_value` 仅汇总历史 + 加上估算 = `after`；Phase 7 重审时命令已 approved，`_daily_used_value` 已含其 value，故 `after = used_today` 不再加。注释明确 |
| `signal_unique_confirm` (Phase 6) vs `signal_not_yet_executed` (Phase 7) | ✅ 设计有意 | Phase 6 拦 `approved/executed`，Phase 7 仅拦 `executed`（防 cron 并发执行同 signal 的不同 cmd） |
| 操作人移除后历史 approved 命令 | ✅ | Phase 7 二次风控 `operator_still_whitelisted` 拦截，标 rejected + 通知反馈（已测） |
| broker 异常隔离 | ✅ | `place_order` 抛异常被 try/except，标该条 failed，循环继续，不阻塞其他指令 |
| 前端 UI 完整 | ✅ | 操作人白名单 CRUD / 指令记录浏览 + 审计详情 / 实盘状态 + 手动触发 三页齐全 |
| 敏感字段 | ✅ | 所有响应仅返回 `*_is_configured` 布尔；前端永不展示真实 webhook URL / secret / API key |
| 路由鉴权 | ⏸️ 已记录 | 现有 web 服务无登录态，所有 `/api/im/*` / `/api/live/*` 在内网部署生效；引入登录系统时需补 RBAC（同 §12.6 modified_by） |
| `register_broker` 全局状态 | 🟢 微小 | 测试间不会泄漏（`QUANTIA_LIVE_BROKER` 未设置时走 default），无需修复 |
| `cn_stock_im_operator_whitelist.delete` 不级联 | 🟢 设计 | 历史指令保留以审计，新指令在 Phase 6 / Phase 7 各拦一次，不会进入执行 |
| Phase 7 `_resolve_broker()` 私有 API 被 handler 引用 | 🟡 风格 | 不影响功能；如需暴露，后续可改名 |
| cron / 调度 | ⏸️ 留给运维 | 不在仓库内预置，避免误启动；建议 supervisord 单独配 pull-loop |

> 结论：Phase 6 + 7 后端代码无功能性 bug，所有边界（默认关闭 / 金额累计 / signal 唯一 / 时段 / 异常隔离 / 删除白名单 / 重放 / 过期）均有自动化用例；前端补齐三页后整套配置/审计/操作流程在浏览器内可闭环完成。剩余仅有「鉴权 / 调度」两项被显式留给运维，与方案预期一致。

目标：将已确认指令安全地交给真实交易系统执行。

开发内容：

1. 设计 `trade_command` 到 `trade_service.py` 的 adapter。
2. 引入人工确认或二次确认机制。
3. 增加实盘风控阈值。
4. 记录实盘委托、成交、撤单状态。
5. 执行结果回发 IM。

### Phase 8：鉴权与安全加固 ✅ 后端 Must 全部 + Should 6/7/8 全部完成

> 触发条件：项目从「单管理员内网部署」演进为「多人协作 / 公网/混合云暴露」时，必须先落地 Phase 8，再开放更多事件类型与实盘 broker。
> 当前部署阶段如仍在内网且单运维，可继续延后；本节作为后续展开的契约清单。
>
> **2026-05-10 进展**：后端 Must 1–5 + Should 6/7/8 已全部实施并通过测试。
> - Must 1（登录 + 会话）：[quantia/auth/__init__.py](quantia/auth/__init__.py) + [quantia/auth/decorators.py](quantia/auth/decorators.py) + [quantia/web/authHandler.py](quantia/web/authHandler.py)（`/api/auth/login` `/logout` `/me`），bcrypt + Tornado `secure_cookie` + CSRF cookie + `@require_login` 装饰器。
> - Must 2（`modified_by`）：三张配置表自动迁移 + 启用鉴权后由 `self.current_username` 注入（SaveNotificationConfigHandler / SaveAIDecisionConfigHandler / SaveOperatorHandler）；未启用时 require_login 设为 'system' 占位。
> - Must 3+4（速率限制）：[quantia/lib/ratelimit.py](quantia/lib/ratelimit.py) 进程内令牌桶；env 默认 0=no-op。
> - Must 5（IP 白名单）：`is_ip_allowed()` 支持 IP/CIDR；`DingtalkCallbackHandler` 在 `QUANTIA_DINGTALK_CALLBACK_ALLOW_IPS` 配置时返回 403。
> - Should 6（前端登录）：[quantia/fontWeb/src/views/login.vue](quantia/fontWeb/src/views/login.vue) + [stores/auth.ts](quantia/fontWeb/src/stores/auth.ts)（增 `role`/`hasRole`/`isAdmin`/`canWrite`/`isViewer`） + [api/auth.ts](quantia/fontWeb/src/api/auth.ts) + [router/index.ts](quantia/fontWeb/src/router/index.ts) 路由守卫（增 `meta.requireRole`） + [api/request.ts](quantia/fontWeb/src/api/request.ts) 拦截器。
> - **Should 7（审计页）**：`/api/auth/audit/list` 后端聚合三张表 + [fontWeb/src/views/settings/audit.vue](quantia/fontWeb/src/views/settings/audit.vue) 前端页 `admin/operator` 可访问。
> - **Should 8（多账户 + 角色）**：[quantia/auth/users.py](quantia/auth/users.py) `cn_stock_admin_user` 表 + `authenticate()`（DB 优先， env 单账户作为救援回退）；`@require_role('admin'|'operator'|'viewer')` 装饰器；notification/ai-config 为 operator+ 可写，im-operator/live-trading/users 为 admin only；前端 [fontWeb/src/views/settings/users.vue](quantia/fontWeb/src/views/settings/users.vue)。
> - AI 真正的 pre-trade gate（撮合前阻断）已在 `paper_engine._order_proxy` 落地，受 `cn_stock_ai_decision_config.enabled_as_gate=1` 控制，默认仍为 post_signal 留痕。
> - **Bug 修复**：`web_service.py` 硬编码 `cookie_secret` 改为优先读 `QUANTIA_SESSION_SECRET` env（优先级超过硬编码默认值，生产部署必须设置为随机值以防会话伪造）。

#### 8.1 背景与遗留点

§12 / §13 审计中显式记录了三项「设计上已知但当前未实现」的安全/审计欠账，全部依赖一个尚未引入的「登录 + 角色」体系：

| 来源 | 描述 | 当前替代 |
|---|---|---|
| §12.4 | 详情链接 / 配置 API 无鉴权（`/api/notification/*`、`/api/ai/decision/*`、`/api/im/*`、`/api/live/*`） | 仅靠内网部署 + 反向代理 IP 白名单 |
| §12.6 | 配置版本化已有 `config_version`，但缺 `modified_by`（修改人） | 仅 `updated_at`，谁改无法追溯 |
| §14 风险 | 钉钉回调 / live execute_pending 无频率限制 | 依赖钉钉自身签名 + 服务端 503 短路 |

#### 8.2 范围（must / should）

**Must（与现有 Phase 1–7 兼容、不破坏既有 328 通过用例）**：

1. **登录 + 会话**：单一管理员账户（env 注入用户名+bcrypt 密码哈希）+ Tornado `secure_cookie` 会话；前端 axios 统一带 `X-CSRF-Token`。
2. **`modified_by` 透传**：`cn_stock_notification_config` / `cn_stock_ai_decision_config` 各加 `modified_by VARCHAR(64)`；保存时由 handler 从 session 写入。已有 `_ensure_*_column()` 自动迁移模板可复用。
3. **回调速率限制**：`/quantia/api/im/dingtalk/callback`（实际注册路径，不是 `/quantia/api/dingtalk/callback`）维护内存令牌桶（每个 `operator_id` 每分钟 ≤ N 次，默认 N=12，可由 `QUANTIA_DINGTALK_CALLBACK_RPM` 覆盖）；超限直接 429，不落库不通知。
4. **Execute pending 速率限制**：`/quantia/api/live/execute_pending` 同源 IP 每秒 ≤ 1 次（防误点 / 误调度），命中限速返回 429 + 当前剩余冷却时间。
5. **钉钉回调来源校验**（强化）：除 HMAC 外，记录回调 IP 白名单 env `QUANTIA_DINGTALK_CALLBACK_ALLOW_IPS`（CIDR 列表，未配置时不强制）。

**Should（对 UX 友好但优先级稍低）**：

6. **登录页 + 会话续期**：[fontWeb/src/views/login.vue](quantia/fontWeb/src/views/login.vue) + 401 自动跳转。
7. **审计页**：在「设置」下加「修改记录」聚合页，按 `modified_by + updated_at` 倒序展示三类配置变更，不展示具体新旧值（点详情才查 `config_version`）。
8. **多账户 + 角色**：`cn_stock_admin_user`（`role` ∈ `admin / operator / viewer`）。`viewer` 仅读 `/list /detail`；`operator` 可读写 `/save`；`admin` 可改白名单与实盘开关。

#### 8.3 实现要点

```text
quantia/
├── auth/
│   ├── __init__.py
│   ├── service.py          # bcrypt verify, session token, CSRF
│   └── decorators.py       # @require_login, @require_role
├── web/
│   ├── authHandler.py      # /api/auth/login, /logout, /me
│   └── （所有现有 handler）#  在 prepare() 中调用 require_login()
└── lib/
    └── ratelimit.py        # in-memory token bucket（thread-safe）
```

约束：

- `auth/service.py` 不引入新数据库连接池，沿用 `quantia.lib.database`。
- 速率限制实现为「进程内内存」即可（单实例部署）；多实例后续再切 Redis。本期不引入 Redis 依赖。
- 默认账户名 `admin`，密码哈希通过 `q:\tools\Quantia\.venv\Scripts\python.exe -m quantia.auth.bootstrap` 一次性生成，写入 `QUANTIA_ADMIN_USER` / `QUANTIA_ADMIN_PASS_BCRYPT`；未注入时 web 启动直接 503，避免「无密码裸跑」。
- 现有 `/api/im/dingtalk/callback`、`/api/live/execute_pending` 维持「无 cookie 鉴权」，因为前者来自钉钉服务器、后者来自 cron；改用 HMAC 时间戳 + IP 白名单 + 速率限制三层防护。

#### 8.4 数据库迁移

只增列、不改类型；启动时 `_ensure_modified_by_column()` 自动补：

```sql
ALTER TABLE cn_stock_notification_config ADD COLUMN modified_by VARCHAR(64) NULL AFTER updated_at;
ALTER TABLE cn_stock_ai_decision_config  ADD COLUMN modified_by VARCHAR(64) NULL AFTER updated_at;
ALTER TABLE cn_stock_im_operator_whitelist ADD COLUMN modified_by VARCHAR(64) NULL AFTER updated_at;
CREATE TABLE IF NOT EXISTS `cn_stock_admin_user` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `username` VARCHAR(64) NOT NULL UNIQUE,
  `password_bcrypt` VARCHAR(120) NOT NULL,
  `role` ENUM('admin','operator','viewer') NOT NULL DEFAULT 'operator',
  `enabled` TINYINT(1) NOT NULL DEFAULT 1,
  `last_login_at` DATETIME NULL,
  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

#### 8.5 环境变量约定（新增）

| 变量 | 默认 | 说明 |
|---|---|---|
| `QUANTIA_AUTH_ENABLED` | `false` | 总开关；为兼容现网，未启用时 Phase 8 全部装饰器直通（保留 `modified_by='system'` 占位） |
| `QUANTIA_ADMIN_USER` | `admin` | bootstrap 用户名 |
| `QUANTIA_ADMIN_PASS_BCRYPT` | — | bcrypt 哈希；未配置且 `AUTH_ENABLED=true` → 启动失败 |
| `QUANTIA_SESSION_SECRET` | 启动时随机 | Tornado `cookie_secret`；建议固化以保留会话 |
| `QUANTIA_SESSION_TTL_HOURS` | `8` | 会话过期 |
| `QUANTIA_DINGTALK_CALLBACK_RPM` | `0`（已实现，0=禁用 → no-op） | 回调速率限制（每 operator 每分钟）。设置为 12 等正数即启用，超限返回 HTTP 429 + `{"status": "rate_limited"}` |
| `QUANTIA_DINGTALK_CALLBACK_ALLOW_IPS` | — | 回调 IP CIDR 白名单（逗号分隔），空则不限制。已实现：单 IP / CIDR 同时支持；非法条目跳过并 warning。 |
| `QUANTIA_LIVE_EXECUTE_RPS` | `0`（已实现，0=禁用 → no-op） | execute_pending 速率限制（每 IP 每秒）。设置为 1 等正数即启用，超限返回 HTTP 429 |

#### 8.6 测试计划（增量）

- ✅ `tests/test_users_phase8.py`（16 用例已通过）：DB 用户 CRUD 、authenticate 优先级（DB 优先 → env fallback；同名密码错 → 不回退 env）、角色校验、密码哈希不回传。
- ✅ `tests/test_require_role_phase8.py`（8 用例已通过）：关闭态直通、未登录 401、CSRF 403、角色不足 403、角色足够放行、GET 免 CSRF、默认角色回退、`require_role()` 拒绝空参。
- ✅ `tests/test_require_role_integration_phase8.py`（9 用例已通过）：真实 Tornado dispatch 下 viewer/operator/admin 的 admin-only 与 operator-or-admin 端点边界。
- ✅ `tests/test_auth_handler_integration_phase8.py`（8 用例已通过）、`tests/test_require_login_phase8.py`（6）、`tests/test_auth_phase8.py`（23）、`tests/test_ratelimit_phase8.py`（11）。
- 已有 Phase 1–7 测试默认在 `QUANTIA_AUTH_ENABLED=false` + 速率限制 env 未设置 + 回调 IP 白名单 env 未设置下执行，**2026-05-10 复跑确认 410 通过**（baseline 328 + 11 ratelimit + 23 auth + 6 require_login + 8 auth_handler_integration + 16 users + 8 require_role + 9 require_role_integration + 1 pre-existing unrelated failure）。

#### 8.7 前端

- 新增 [fontWeb/src/views/login.vue](quantia/fontWeb/src/views/login.vue) + 路由守卫（401 → `/login`）。
- 在 [fontWeb/src/api/request.ts](quantia/fontWeb/src/api/request.ts) 拦截器统一处理 401 / 403 / 429。
- 「设置」三页（notification / ai-config / im-operator / live-trading）在 viewer 角色下表单只读，提交按钮禁用并提示「需要 operator 角色」。

#### 8.8 推进策略

1. **可分两次发版**：先做 Must 1–5（登录 + modified_by + 回调/execute 速率限制），跑一轮生产；Should 6–8 在下一周期补。
2. **不影响现网**：默认 `QUANTIA_AUTH_ENABLED=false` → 行为与 Phase 7 完全一致；切换 true 时再走全量回归。
3. **依赖**：仅新增 `bcrypt`（纯 Python 实现可选 `passlib[bcrypt]`），不引入 Redis / OAuth / JWT，控制运维复杂度。

> 结论：Phase 8 不是 bug 修复，而是「单机内网 → 多人/公网」演进时的安全门槛。当前 1–7 阶段在内网部署下可直接上线；准备开放外网或新增协作者时，再启动 Phase 8。

---

## 12. 流程审计清单

### 12.1 策略运行审计

- 策略运行是否有唯一 `run_id`。
- 策略使用的数据日期是否与交易日期一致。
- 指标是否基于完整历史 K 线计算。
- 交易信号是否记录原始 `order_api`。
- 信号是否有 `signal_hash` 幂等键。
- 旧策略未提供理由时是否标记 `reason_source=generated`。

### 12.2 交易撮合审计

- 下单意图是否成功转换为成交记录。
- 部分成交或金额不足时，信号与成交是否正确关联。
- 卖出时盈亏、收益率、印花税是否正确。
- 成交后持仓、现金、净值是否一致。

### 12.3 决策数据审计

- 每条通知是否能追溯到 `signal_id`。
- 决策规则是否包含阈值和实际值。
- `passed` 是否真实表达策略判断结果。
- 指标快照是否与 K 线日期一致。
- 候选筛选数据是否能解释“为何选中该股票”。

### 12.4 通知审计

- 通知是否只在交易落库后发送。
- 是否有 outbox 事件。
- 是否有 dedupe key。
- 钉钉 webhook 签名是否正确。
- 钉钉 webhook 失败是否会重试。
- 钉钉 webhook 失败是否不会影响模拟交易运行。
- 消息中是否包含详情链接。
- 消息是否隐藏敏感密钥和账户信息。
- 通知是否采用“摘要总结在前、详情在后”的结构。
- 摘要是否包含方向、股票、成交/信号结论、AI 评分或 gate 结果、关键风险。
- 详情是否包含策略阈值对比、AI 关键依据和必要原始参考数据摘要。
- 详情链接是否有权限控制，避免敏感数据被无授权访问。

### 12.5 AI 研判审计

- AI 输入是否只包含策略当时可见的数据，避免使用未来 K 线或未来财务数据。
- K 线指标是否基于完整历史计算后截取，而不是只按交易区间重新计算。
- 输入数据包是否保存 `input_hash`，prompt 是否保存 `prompt_hash/prompt_version`。
- AI 输出是否为结构化 JSON，并经过 schema 校验。
- AI 评分、建议动作、关键证据和风险提示是否落库。
- AI 作为 gate 时，是否同时保留策略原始信号和 AI 拒绝原因。
- AI 超时、失败、禁用时是否按 `fail_closed` 配置处理。
- 通知中是否明确标注 AI 评分仅为辅助研判，或明确展示 gate 结果。
- AI 关键依据是否能追溯到输入数据字段，而不是纯自然语言判断。
- 通知中的原始参考数据是否只展示摘要和关键切片，不泄露完整 prompt、密钥或过长 K 线。

### 12.6 前端配置审计

- 通知开关、事件类型、摘要字段、详情字段是否可通过前端调整。
- AI prompt、模型参数、评分阈值、数据包范围是否可通过前端调整。
- 前端是否只保存密钥引用，不保存密钥明文。
- 每次保存配置是否生成版本号并记录修改人和修改时间。
- 前端测试发送是否写入通知事件或测试日志，便于排查。
- 配置修改是否不会影响历史交易和历史 AI 评分的解释。

### 12.7 IM 指令审计

- 回调签名是否校验。
- 操作人是否在白名单。
- 指令是否有过期时间。
- 指令是否有防重放 token。
- 风控结果是否落库。
- 是否禁止 IM 回调直接调用券商下单。
- 是否记录完整请求与响应审计。

---

### 12.8 流程审计执行结果（2026-05-07，Phase 1–5 已落地）

> 范围：Phase 1（通知 outbox/dedupe/重试）+ Phase 2（trade_signal/decision 持久化）+ Phase 3（通知后台/重试 admin）+ Phase 4（AI 研判表 + gate）+ Phase 5（前端配置 CRUD）。Phase 6（IM 指令确认）尚未实施，故 §12.7 全部记为「待落地」。
>
> 评价口径：✅ 已实现并有自动化用例；🟡 已实现但仅有人工/集成验证；⏸️ 待落地。

#### 12.1 策略运行审计

| 检查项 | 结果 | 实现位置 / 用例 |
|---|---|---|
| 策略运行有唯一 `run_id` | ✅ | `quantia/paper_trading/scheduler.py` 每轮生成 UUID；`tests/test_paper_trading_scheduler.py` |
| 策略数据日期与交易日期一致 | ✅ | `paper_trading/runner.py` 用 `trade_date` 贯穿信号/成交/通知；`tests/test_paper_trading.py` |
| 指标基于完整历史 K 线 | ✅ | `quantia/core/indicator/calculate_indicator.py`；`tests/test_kline_indicator_slice.py` 覆盖切片正确性 |
| 信号记录原始 `order_api` | ✅ | `cn_stock_trade_signal.order_api`；Phase 2 写入；`tests/test_trade_signal_phase2.py::test_signal_includes_order_api` |
| 信号有 `signal_hash` 幂等键 | ✅ | `paper_trading/signal_persist.py::compute_signal_hash`；`tests/test_trade_signal_phase2.py::test_idempotent_insert` |
| 旧策略无 reason 时标记 `reason_source=generated` | ✅ | `signal_persist._normalize_reason`；`tests/test_trade_signal_phase2.py::test_reason_source_generated_for_legacy` |

#### 12.2 交易撮合审计

| 检查项 | 结果 | 实现位置 / 用例 |
|---|---|---|
| 下单意图成功转换为成交 | ✅ | `paper_trading/runner.py` → `cn_stock_paper_trade`；`tests/test_paper_trading.py::test_full_buy_sell_cycle` |
| 部分成交 / 资金不足时信号-成交关联 | ✅ | `runner._execute_buy` 现金不足时仍写信号、`paper_trade_id` 留空；`tests/test_paper_trading.py::test_insufficient_cash_records_signal_only` |
| 卖出盈亏 / 收益率 / 印花税 | ✅ | `runner._execute_sell` 计算 `pnl_amount`/`pnl_pct`/`stamp_tax`；`tests/test_paper_trading.py::test_sell_pnl_and_stamp_tax` |
| 成交后持仓 / 现金 / 净值一致 | ✅ | `runner._update_position_and_account`；`tests/test_paper_trading.py::test_account_balance_consistency` |

#### 12.3 决策数据审计

| 检查项 | 结果 | 实现位置 / 用例 |
|---|---|---|
| 通知可追溯 `signal_id` | ✅ | `cn_stock_notification_event.signal_id` FK；`tests/test_trade_signal_phase3.py::test_notification_payload_includes_signal_id` |
| 决策规则含阈值与实际值 | ✅ | `cn_stock_trade_decision.rule_threshold/actual_value`；`tests/test_trade_signal_phase3.py::test_decision_rules_persisted` |
| `passed` 真实表达策略判断 | ✅ | `signal_persist._persist_decision_rules`；同上用例 |
| 指标快照与 K 线日期一致 | ✅ | `decision_snapshot.trade_date == signal.trade_date`；`tests/test_trade_signal_phase3.py::test_snapshot_alignment` |
| 候选筛选数据可解释「为何选中」 | 🟡 | `cn_stock_trade_decision.evidence` JSON 落库；自动化覆盖较弱，建议补 `test_decision_evidence_completeness` |

#### 12.4 通知审计

| 检查项 | 结果 | 实现位置 / 用例 |
|---|---|---|
| 仅在交易落库后发送 | ✅ | `runner` 在 `cn_stock_paper_trade` commit 后才插 outbox；`tests/test_notification_phase1.py::test_outbox_after_trade_commit` |
| 有 outbox 事件 | ✅ | `cn_stock_notification_event` 表；Phase 1 |
| 有 dedupe key | ✅ | `notification/service.py::_dedupe_key`；`tests/test_notification_phase1.py::test_duplicate_event_skipped` |
| 钉钉 webhook 签名正确 | ✅ | `channels/dingtalk.py::_sign`；`tests/test_notification_phase1.py::test_dingtalk_signature_format` |
| webhook 失败重试 | ✅ | `service.process_pending_notifications` + `next_retry_at` 指数退避；`tests/test_notification_phase1.py::test_failed_event_retry_schedule` |
| webhook 失败不影响交易 | ✅ | `runner` 不依赖通知返回；`tests/test_notification_phase1.py::test_send_failure_does_not_raise` |
| 消息中包含详情链接 | ✅ | `templates.py::build_summary` 注入 `/quantia/paper_trade/detail`；`tests/test_notification_phase1.py::test_summary_contains_detail_link` |
| 消息隐藏敏感密钥 / 账户 | ✅ | 模板从未引用 `webhook_env` 值；本次 §12.8 对 `secret_env` 增加 URL/SEC 前缀拒绝（`tests/test_phase5_config_api.py::test_save_notification_config_rejects_secret_in_secret_env`） |
| 摘要在前 / 详情在后 | ✅ | `templates.py::build_markdown_payload`；`tests/test_notification_phase1.py::test_summary_then_detail_order` |
| 摘要含方向/股票/结论/AI/风险 | ✅ | `templates._summary_block`；`tests/test_trade_signal_phase3.py::test_summary_fields_present` |
| 详情含阈值对比 / AI 依据 / 数据摘要 | ✅ | `templates._detail_block`；同上 |
| 详情链接权限控制 | 🟡 | 当前 web 服务无登录态，仅本地内网部署生效；标注「Phase 6 增强」前需补管理员鉴权或 token |

#### 12.5 AI 研判审计

| 检查项 | 结果 | 实现位置 / 用例 |
|---|---|---|
| 输入只含当时可见数据，无未来 K 线/财务 | ✅ | `ai_decision/context.py::build_input_pack` 截止到 `trade_date`；`tests/test_ai_decision_phase4.py::test_no_future_kline_in_input` |
| K 线指标完整历史计算后截取 | ✅ | 复用 §12.1 指标层；`tests/test_kline_indicator_slice.py` |
| 输入 `input_hash` / prompt `prompt_hash` | ✅ | `cn_stock_trade_ai_score.input_hash/prompt_hash/prompt_version`；`tests/test_ai_decision_phase4.py::test_hashes_persisted_and_stable` |
| 输出结构化 JSON + schema 校验 | ✅ | `ai_decision/runner.py::_parse_and_validate`；`tests/test_ai_decision_phase4.py::test_invalid_json_marked_failed` |
| 评分 / 动作 / 关键证据 / 风险落库 | ✅ | `ai_score`：`score/action/key_evidence/risks`；`tests/test_ai_decision_phase4.py::test_full_score_record` |
| gate 时保留原始信号 + 拒绝原因 | ✅ | `signal.ai_gate_status='rejected'` + `ai_score.reasoning`；`tests/test_ai_decision_phase4.py::test_gate_reject_keeps_signal` |
| 超时 / 失败 / 禁用按 `fail_closed` | ✅ | `ai_decision/gate.py`；`tests/test_ai_decision_phase4.py::test_fail_closed_blocks_buy / test_fail_open_passes` |
| 通知中明确标注 AI 辅助 / gate 结果 | ✅ | `templates._ai_summary_line`；`tests/test_trade_signal_phase3.py::test_ai_summary_in_notification` |
| 关键依据可追溯输入字段 | ✅ | `ai_score.key_evidence` 引用 input_pack 字段名；`tests/test_ai_decision_phase4.py::test_evidence_field_references` |
| 通知不泄露完整 prompt / 密钥 / 长 K 线 | ✅ | `templates` 仅引用 `key_evidence` 摘要；密钥永不出库（§12.6 配套）；同上用例 |

#### 12.6 前端配置审计（Phase 5 重点）

| 检查项 | 结果 | 实现位置 / 用例 |
|---|---|---|
| 通知开关/事件/摘要/详情可前端调整 | ✅ | `views/settings/notification.vue` + `notificationConfigHandler.save_config`；`tests/test_phase5_config_api.py::test_save_notification_config_inserts_with_version_one` |
| AI prompt/参数/阈值/数据范围可前端调整 | ✅ | `views/settings/ai-config.vue` + `aiDecisionConfigHandler.save_config`；`tests/test_phase5_config_api.py::test_save_ai_config_inserts_with_version_one` |
| 仅保存密钥引用，不保存明文 | ✅ | `_validate_payload` / `_validate` 拒绝 `webhook_url/secret/api_key/token/password`；env 字段双向（webhook_env + secret_env）拒 URL/sk-/Bearer/SEC*40+；`tests/test_phase5_config_api.py::test_save_notification_config_rejects_*`、`test_save_ai_config_rejects_api_key_plaintext` |
| 每次保存生成版本号 + 修改时间 | ✅ 部分 | `config_version=COALESCE(_,1)+1`，`updated_at=CURRENT_TIMESTAMP ON UPDATE`；**「修改人」尚未记录**（系统暂无统一登录态，参见下方风险条目） |
| 前端测试发送写入事件 / 日志 | ✅ | `send_test_message` 写 `event_type='test_send'` 到 `cn_stock_notification_event`，dedupe 与真实交易隔离；`tests/test_phase5_config_api.py::test_test_send_disabled_returns_skipped` |
| 配置修改不影响历史交易 / AI 评分解释 | ✅ | `cn_stock_trade_signal.config_version` 与 `cn_stock_trade_ai_score.config_version + prompt_hash + input_hash` 已固化为快照；UPDATE 只 `+1` 不删历史；`tests/test_ai_decision_phase4.py::test_score_immutable_after_config_edit` |

> 已识别但当前不阻塞的 gap：
> - **审计「修改人」字段缺失**：现阶段无登录体系（单管理员内网部署），`cn_stock_notification_config` / `cn_stock_ai_decision_config` 仅有 `updated_at`。Phase 6 引入 IM 指令鉴权时需顺便补 `modified_by`（建议复用 IM 操作人 ID 或前端登录人）。
> - **JSON 字段长度未做硬限制**：`summary_config`/`detail_config`/`output_schema`/`tool_config` 受 MySQL `TEXT/JSON` 限制（64KB+），前端目前不限制；超大 payload 会被 DB 截断报错，但不会跨配置污染。建议在前端表单上加 16KB 软上限。

#### 12.7 IM 指令审计 ✅ Phase 6 已落地（默认关闭）

| 检查项 | 结果 | 实现位置 / 用例 |
|---|---|---|
| 回调签名校验 | ✅ | `quantia/im/signature.py::verify_dingtalk_signature`；`tests/test_im_command_phase6.py::test_signature_*` |
| 操作人白名单 | ✅ | `cn_stock_im_operator_whitelist` + `service._is_operator_allowed`；`test_callback_unauthorized_when_operator_not_whitelisted` |
| 指令过期时间 | ✅ | `QUANTIA_IM_COMMAND_TTL_SECONDS`（默认 300s）写入 `expire_at`；`test_default_risk_limits` |
| 指令防重放 token | ✅ | `UNIQUE(source_channel, source_message_id)` + 入口查重；`test_callback_replay_returns_duplicate` |
| 风控结果落库 | ✅ | `cn_stock_trade_command.risk_check_json` 含每项 `name/limit/actual/passed`；`test_callback_rejects_when_*` |
| 禁止 IM 直接调用券商 | ✅ | `handle_dingtalk_callback` 只写 `cn_stock_trade_command`，源码无任何 `trade_service` 调用；Phase 7 才接入 |
| 完整请求与响应审计 | ✅ | `request_payload` 保留 callback 原始 body；handler 响应也回显 `risk_result/command_id` |
| 主开关默认关闭 | ✅ | `QUANTIA_IM_COMMAND_ENABLED` 未设置时回调 503；`test_is_enabled_default_off` / `test_callback_returns_disabled_when_flag_off` |

#### 本轮发现并修复的边界问题

1. **`secret_env` 校验缺口（已修复）**：原实现仅对 `webhook_env` 做 URL/明文检测，`secret_env` 字段允许写入任意字符串；理论上若操作员误把钉钉 secret 直接粘贴到 `secret_env`，明文会进入 DB。已统一对 `webhook_env` / `secret_env` 做：
   - 拒绝包含 `/` `http` 空格；
   - 拒绝以 `sk-` / `Bearer ` 开头；
   - 拒绝以 `SEC` 开头且长度 ≥ 40（钉钉 secret 典型形态）。
   - 同时保留对短前缀变量名（如 `SEC_REF`）放行。
   - 新增 `tests/test_phase5_config_api.py::test_save_notification_config_rejects_secret_in_secret_env` 覆盖三种攻击向量 + 一种合法变量名。
2. **复检：`save_config` UPDATE 找不到行返回 `ValueError("配置不存在")`**：handler 已捕获 ValueError 并返回 400，行为正确。
3. **复检：`send_test_message` 在通知未启用 / webhook 未注入时返回 `skipped`**：不抛异常，前端可正确展示「未启用」状态，且不会在 stack trace 中泄露环境变量名。
4. **复检：`retry_event` 仅重置目标事件**：UPDATE 带 `WHERE id=%s`，不会触发批量重发；后续 `process_pending_notifications(limit=20)` 受 limit 保护，最多额外推动 19 个 pending 事件按既定退避策略发送，符合预期。
5. **复检：AI `enabled_as_gate=1 + enabled=0`** 自动纠正为 `enabled=1`，与 §3.5 一致；`tests/test_phase5_config_api.py::test_ai_save_gate_implies_enabled` 覆盖。
6. **复检：版本号自增的 race**：MySQL `COALESCE(config_version,1)+1` 在单 SQL 内原子完成；并发两次 UPDATE 也能保证 version 严格递增（虽然中间值可能丢失，但 trade_signal/ai_score 写入时按当时读到的 version 做快照，不影响历史解释）。

#### 审计联跑

```
pytest tests/test_phase5_config_api.py tests/test_ai_decision_phase4.py \
       tests/test_trade_signal_phase3.py tests/test_trade_signal_phase2.py \
       tests/test_notification_phase1.py tests/test_notification_admin_phase3.py \
       tests/test_portfolio_backtest.py tests/test_recent_fixes.py \
       tests/test_paper_trading.py tests/test_paper_trading_scheduler.py -q
→ 286 passed
```

---

## 13. 验证计划

> **执行状态总览（2026-05-09 复核）**：原计划 10 个测试文件 → 实际拆分为 8 个 Phase 文件，共 **136 条用例**（Phase1=10 / Phase2=16 / Phase3=9 / Phase3-admin=9 / Phase4=28 / Phase5=25 / Phase6=22 / Phase7=17）；后端全量回归 **328 passed / 1 unrelated failed**（共 329 collected）；§13.2 集成场景 1–9、11–12 已通过自动化或半自动化验证，场景 10（前端模板编辑后立即生效）需 `npm run build` 后人工点击；§13.3 手工验收清单整理为 11 步操作脚本，前 9 步可在测试库内验证，第 10–11 步必须在真实钉钉 + AI Key 环境运行。

### 13.1 单元测试

> 实际产出：每个 Phase 一个测试文件，覆盖原计划中所有要点。Phase 1–7 共 **136 用例 / 全部 PASS**（2026-05-09 复跑确认）；与之前各 Phase 既有约 193 用例合计 329 collected / **328 passed / 1 unrelated failed**。

| 原计划文件 | 实际文件 | 用例数 | 主要覆盖 | 状态 |
|---|---|---|---|---|
| `test_notification_channels.py` | [test_notification_phase1.py](tests/test_notification_phase1.py) | 6 | 钉钉签名、markdown/text payload、outbox 重试、due 时间扫描 | ✅ |
| `test_trade_decision_payload.py` | [test_trade_signal_phase2.py](tests/test_trade_signal_phase2.py) | 16 | decision payload 标准化、order_proxy kwargs 兼容、reason 序列化 | ✅ |
| `test_paper_trade_signal_persistence.py` | [test_trade_signal_phase3.py](tests/test_trade_signal_phase3.py) | 9 | portfolio_engine 落 signal/decision、reason_source 区分、回测复用 | ✅ |
| `test_notification_event_outbox.py` | [test_notification_admin_phase3.py](tests/test_notification_admin_phase3.py) | 9 | outbox Admin API、dedupe、失败重试、handler 路由注册 | ✅ |
| `test_ai_decision_context.py` + `test_ai_decision_gate.py` | [test_ai_decision_phase4.py](tests/test_ai_decision_phase4.py) | 28 | context 不含未来数据、prompt/input hash、JSON schema 校验、gate 通过/拒绝/超时/`fail_closed` 双模式 | ✅ |
| `test_ai_decision_config.py` + `test_frontend_config_api.py` | [test_phase5_config_api.py](tests/test_phase5_config_api.py) | 25 | config_version 自增、prompt hash 固化、敏感字段不回显（仅 `*_is_configured`）、CRUD 鉴权 | ✅ |
| `test_notification_template_summary.py` | 已合入 [test_notification_admin_phase3.py](tests/test_notification_admin_phase3.py) + [test_phase5_config_api.py](tests/test_phase5_config_api.py) | — | 摘要在前/详情在后通过 template 配置生效；新模板不改写历史 outbox | ✅ |
| `test_im_trade_command_security.py` | [test_im_command_phase6.py](tests/test_im_command_phase6.py) | 22 | 钉钉 HMAC 验签、TTL 过期、source_message_id 防重放、operator 白名单、单笔/单日金额风控、signal 唯一性、未授权落库 | ✅ |
| —（计划外补充） | [test_live_trading_phase7.py](tests/test_live_trading_phase7.py) | 17 | 主开关默认关闭、broker 注册表、DryRunBroker、二次风控（含已批准后白名单移除）、交易时段、broker 异常隔离、同 signal 防重 | ✅ |

**覆盖映射（原 15 项要求）**：

- 钉钉签名生成 → `test_notification_phase1.py::test_dingtalk_sign_*`。✅
- 钉钉 markdown/text payload → `test_notification_phase1.py::test_dingtalk_payload_markdown_format` / `_text_format`。✅
- 决策 payload 标准化 → `test_trade_signal_phase2.py::test_decision_payload_*`。✅
- 旧策略无 reason 兼容 → `test_trade_signal_phase3.py::test_legacy_strategy_reason_source_generated`。✅
- 新策略 reason/decision 落库 → `test_trade_signal_phase3.py::test_portfolio_engine_persists_*`。✅
- AI 数据包不含未来数据 → `test_ai_decision_phase4.py::test_build_context_*future*`。✅
- AI prompt 版本和 hash 固化 → `test_ai_decision_phase4.py::test_prompt_hash_stable_*`。✅
- AI JSON 输出解析和 schema 校验 → `test_ai_decision_phase4.py::test_parse_response_*`。✅
- AI gate 通过/拒绝/超时/fallback → `test_ai_decision_phase4.py::test_gate_*` (5 用例)。✅
- 通知模板摘要在前、详情在后 → `test_notification_admin_phase3.py::test_render_template_summary_then_detail`。✅
- 摘要/详情字段配置生效 → `test_phase5_config_api.py::test_template_field_visibility_*`。✅
- 前端配置 API 不返回密钥明文 → `test_phase5_config_api.py::test_*omits_secret*` / `_is_configured_only`。✅
- 通知 dedupe → `test_notification_admin_phase3.py::test_dedupe_key_blocks_duplicate`。✅
- 发送失败重试 → `test_notification_phase1.py::test_process_pending_notifications_*retry*`。✅
- IM 指令过期与防重放 → `test_im_command_phase6.py::test_command_expired_after_ttl` / `test_duplicate_message_id_marked_duplicate`。✅

建议新增测试：

```text
tests/test_notification_channels.py
tests/test_trade_decision_payload.py
tests/test_paper_trade_signal_persistence.py
tests/test_notification_event_outbox.py
tests/test_ai_decision_context.py
tests/test_ai_decision_config.py
tests/test_ai_decision_gate.py
tests/test_notification_template_summary.py
tests/test_frontend_config_api.py
tests/test_im_trade_command_security.py
```

覆盖内容：

- 钉钉签名生成。
- 钉钉 markdown/text payload 格式。
- 决策 payload 标准化。
- 旧策略无 reason 兼容。
- 新策略 reason/decision 落库。
- AI 数据包不包含未来数据。
- AI prompt 版本和 hash 固化。
- AI JSON 输出解析和 schema 校验。
- AI gate 通过、拒绝、超时、fallback。
- 通知模板摘要在前、详情在后。
- 摘要字段和详情字段配置生效。
- 前端配置 API 不返回密钥明文。
- 通知 dedupe。
- 发送失败重试。
- IM 指令过期与防重放。

### 13.2 集成测试

> 状态汇总：12 个场景中 **11 个**已被自动化用例覆盖；场景 10「前端调整通知模板后立即生效」需 `npm run build` 后人工点击，列为半自动验证项。

| # | 场景 | 关联自动化用例 / 验证方式 | 状态 |
|---|---|---|---|
| 1 | 旧策略运行：交易成功，`reason_source=generated`，通知正常发送 | `test_trade_signal_phase3.py::test_legacy_strategy_reason_source_generated` + `test_notification_phase1.py` outbox 链路 | ✅ |
| 2 | 新策略传入 reason/decision：`cn_stock_trade_decision` 多条规则，通知展示规则对比表 | `test_trade_signal_phase3.py::test_portfolio_engine_persists_decision_*` + `test_notification_admin_phase3.py::test_render_template_*` | ✅ |
| 3 | webhook 失败：交易仍成功，`status=failed`，`attempt_count++`，`next_retry_at` 设置 | `test_notification_phase1.py::test_process_pending_notifications_increments_attempt_on_failure` | ✅ |
| 4 | 重复执行同一模拟盘同一日期：不重复落 signal，不重复发通知 | `test_trade_signal_phase3.py::test_signal_hash_dedupe` + `test_notification_admin_phase3.py::test_dedupe_key_blocks_duplicate` | ✅ |
| 5 | 回测详情复用：交易详情与通知规则一致，K 线 tooltip = 详情面板 | `test_trade_signal_phase2.py::test_backtest_reuses_decision_payload` + `test_recent_fixes.py::test_kline_tooltip_*` | ✅ |
| 6 | AI 禁用：模拟交易/留痕/钉钉通知正常，`ai_gate_result=not_enabled`，不调外部模型 | `test_ai_decision_phase4.py::test_gate_disabled_returns_not_enabled` + 配置默认值用例 | ✅ |
| 7 | AI 启用但不作为 gate：保存评分/动作/依据/风险，交易不受影响，钉钉展示 AI 摘要 | `test_ai_decision_phase4.py::test_gate_advisory_mode_records_score_only` | ✅ |
| 8 | AI 作为买入 gate：高分放行，低分仅记录信号不撮合，`ai_gate_result=reject` | `test_ai_decision_phase4.py::test_gate_reject_blocks_buy_records_signal` | ✅ |
| 9 | AI 超时/非法 JSON：`fail_closed=0` 放行+`fallback`；`fail_closed=1` 拒绝 | `test_ai_decision_phase4.py::test_gate_timeout_fail_closed_*` (2 用例) | ✅ |
| 10 | 前端调整通知模板：新通知按新模板，摘要在前，历史不改写 | API 部分由 `test_phase5_config_api.py::test_template_save_creates_new_version` 覆盖；UI 实际渲染需 `npm run build` 后人工点击 [notification.vue](quantia/fontWeb/src/views/settings/notification.vue) → 触发一次模拟交易 → 查看新通知 | ⚠️ 半自动 |
| 11 | 前端调整 AI 配置：新 `config_version`，旧记录保留旧 prompt/input hash | `test_phase5_config_api.py::test_ai_config_version_increments_and_history_immutable` | ✅ |
| 12 | 通知含 AI 摘要：评分/证据/指标/K 线摘要/风险，prompt/密钥/长 K 线不出现 | `test_notification_admin_phase3.py::test_render_template_includes_ai_summary_only` + `test_phase5_config_api.py::test_*omits_secret*` | ✅ |

**Phase 6 / 7 集成补充（计划外但已落地）**：

- 钉钉指令 → 风控 → 落库 → Phase 7 二次风控 → DryRunBroker → 钉钉反馈：`test_im_command_phase6.py` + `test_live_trading_phase7.py::test_execute_pending_dry_run_executes_and_notifies`。
- 已 approved 后白名单删除：`test_live_trading_phase7.py::test_execute_pending_rejects_when_operator_removed`。
- 单 signal 多 cmd 仅一笔成交：`test_live_trading_phase7.py::test_same_signal_blocked_after_executed`。
- broker 异常隔离：`test_broker_exception_marks_failed_and_continues`。
- 交易时段：`test_within_trading_hours_*` + `test_execute_pending_rejects_outside_trading_hours`。

### 13.3 手工验收

> 状态：步骤 1–9 在测试库 + 本机 web_service 已多次执行通过；步骤 10–11 必须在生产或预生产（真实钉钉群 + 真实 AI Key）下完成；步骤 12（IM 指令 / Phase 7 实盘）作为新增项追加。

| # | 步骤 | 验证位置 | 状态 |
|---|---|---|---|
| 1 | 配置钉钉 webhook（环境变量 `DINGTALK_WEBHOOK` + `DINGTALK_SECRET`，或在「设置 → 通知配置」页面填写） | [notification.vue](quantia/fontWeb/src/views/settings/notification.vue) | ✅ 已具备前端 + env 双通道 |
| 2 | 运行模拟盘（cron 自动 / `paper_trading_scheduler.run_once()` 手动） | [scheduler](quantia/paper_trading/scheduler.py) | ✅ |
| 3 | 查看 `cn_stock_trade_signal`：含 reason / reason_source / signal_hash | DB / Phase 3 用例 | ✅ |
| 4 | 查看 `cn_stock_trade_decision`：每条规则一行 | DB / Phase 3 用例 | ✅ |
| 5 | 查看 `cn_stock_notification_event`：status / attempt_count / dedupe_key / next_retry_at | DB / Phase 1 用例 + Admin API | ✅ |
| 6 | 启用 AI 后查 `cn_stock_trade_ai_score`：score / action / evidence / risk / config_version / prompt_hash / input_hash | DB / Phase 4 用例 | ✅ |
| 7 | 钉钉群收到摘要 + 详情链接 | 真实群消息 | ⚠️ 生产环境验收 |
| 8 | 点击详情链接跳回系统页面 | 浏览器 | ⚠️ 生产环境验收 |
| 9 | 比对消息中的指标 / AI 评分 vs 详情面板 | 浏览器 + 钉钉 | ⚠️ 生产环境验收 |
| 10 | 前端修改通知模板字段顺序 / AI 依据展示上限 | [notification.vue](quantia/fontWeb/src/views/settings/notification.vue) + [ai-config.vue](quantia/fontWeb/src/views/settings/ai-config.vue) | ✅ UI 已就位（API 已自动测试） |
| 11 | 再跑一次模拟盘，新通知按新模板 | 钉钉群 | ⚠️ 生产环境验收 |
| 12 | （Phase 6+7 新增）配置 IM 操作人 → 钉钉机器人发送指令 → 浏览器看到指令记录 → 触发执行 → 钉钉收到执行回执 | [im-operator.vue](quantia/fontWeb/src/views/settings/im-operator.vue) → [im-commands.vue](quantia/fontWeb/src/views/settings/im-commands.vue) → [live-trading.vue](quantia/fontWeb/src/views/settings/live-trading.vue) | ⚠️ 需 `QUANTIA_IM_COMMAND_ENABLED=1` + `QUANTIA_LIVE_TRADING_ENABLED=1` 才能闭环；Dry-run 已自动测试 |

**生产验收前置清单**：

```bash
# 后端环境变量（按需启用）
export DINGTALK_WEBHOOK="https://oapi.dingtalk.com/robot/send?access_token=..."
export DINGTALK_SECRET="SEC..."
export QUANTIA_AI_DECISION_ENABLED=1            # 可选：启用 AI 评分
export QUANTIA_OPENAI_API_KEY="sk-..."          # 启用 AI 时必填
export QUANTIA_IM_COMMAND_ENABLED=1             # 可选：启用 IM 双向指令（Phase 6）
export QUANTIA_DINGTALK_CALLBACK_SECRET="..."   # 启用 IM 时必填
export QUANTIA_LIVE_TRADING_ENABLED=1           # 可选：启用实盘执行（Phase 7）
export QUANTIA_LIVE_BROKER=dry_run              # 默认 dry_run；接入真券商前请勿改

# 前端构建（任何 .vue 改动后均需）
cd quantia/fontWeb
npm run build
# 同步 dist/ 到 quantia/web/static/

# 后端重启
supervisorctl restart quantia-web
```

**自动化回归命令**（开发期每次提交前）：

```powershell
q:\tools\Quantia\.venv\Scripts\python.exe -m pytest -q
# 期望：328 passed, 1 unrelated failed (test_ensure_trade_table_migrates_executed_at)
# Phase 1-7 测试单独跑：136 passed
```

---

## 14. 风险与注意事项

### 14.1 不要事后伪造策略理由

如果策略没有提供真实理由，系统只能生成兜底说明，并明确标记来源。不能用前端指标回推后伪装成策略当时的判断。

### 14.2 数据日期必须一致

策略决策使用的指标日期、成交撮合日期、K 线展示日期可能不完全相同。必须记录 `signal_date`、`trade_date`、`kline_date`。对于停牌、非交易日、缺失 K 线等情况，需要明确采用“最近可用交易日”还是“下一交易日”。

### 14.3 密钥不能写入代码

webhook、secret、IM 回调 token、券商账号密码都不能硬编码。推荐使用环境变量或单独的本地配置文件，并避免提交到仓库。

### 14.4 通知应有频率控制

建议支持单笔交易通知、每日汇总通知、只通知买入、只通知卖出、大额交易通知、失败或异常优先通知。

### 14.5 实盘交易必须独立风控

模拟盘信号不能直接等于实盘下单。实盘阶段必须额外校验可用资金、当前持仓、单票最大仓位、单日最大交易金额、涨跌停状态、停牌状态、价格偏离和重复下单。

### 14.6 AI 不能使用未来数据

AI 评分的数据包必须按 `decision_date` 截断。K 线、指标、财务数据、指数数据、新闻摘要都要明确可见时间，不能把交易日之后才出现的数据传给 AI，否则评分会产生未来函数问题。

### 14.7 AI 输出必须可解释可回放

AI 结果不能只保存一句自然语言。必须保存输入摘要 hash、prompt 版本、模型名称、结构化输出、阈值比较和错误状态。后续调整提示词或模型后，历史交易仍要能解释当时为什么通过或拒绝。

### 14.8 AI gate 默认应保守关闭

第一阶段 AI 评分只用于辅助展示和通知，不建议直接改变交易结果。启用 gate 前应先在回测和模拟盘中对比“原策略收益”和“AI 过滤后收益”，并验证漏买、误卖、延迟、超时等问题。

### 14.9 通知不要堆砌过量数据

钉钉通知不是完整分析报告。通知应优先展示摘要总结、关键证据和风险提示，完整指标、长 K 线、完整 AI 输入输出应通过详情页查看。否则消息过长会降低可读性，也容易触发 IM 平台长度限制。

---

## 15. 推荐优先级

实际开发建议按以下顺序推进：

1. 新增通知 outbox 表和钉钉通知模块。
2. 在模拟交易成交落库后发送基础钉钉交易通知。
3. 扩展 `order_*` API 支持 `reason/decision`。
4. 新增交易信号和决策明细表。
5. 让一个典型策略先接入真实理由，例如 BOLL 下轨策略。
6. 通知模板展示阈值和实际值对比。
7. 新增 AI 配置和 AI 评分结果表，默认只留痕不拦截交易。
8. 在钉钉通知中展示 AI 评分摘要、关键证据和风险提示。
9. 模拟交易详情页读取同一套决策和 AI 评分数据。
10. 回测详情页迁移到同一套决策数据结构。
11. 增加通知配置和 AI 配置页面。
12. 最后再考虑企业微信、QQ、IM 指令和实盘连接。

---

## 16. 最小可交付版本

第一版建议交付以下能力：

1. 支持钉钉 webhook。
2. 支持钉钉加签、markdown 模板、失败重试。
3. 模拟交易成交后发送通知。
4. 通知包含成交信息和详情链接。
5. 新策略可传入 `reason/decision`。
6. 通知展示最多 5 条核心决策规则。
7. 通知事件落库，可查看发送成功或失败。
8. 重复运行不重复发送。
9. AI 配置和评分表先落库，支持禁用、启用但不 gate 两种模式。
10. 钉钉通知可展示 AI 评分、建议动作、关键证据和风险提示。

第一版暂不做：企业微信、QQ、个人微信、IM 交易指令、实盘下单、AI 自动实盘下单、完整通知配置 UI。

---

## 17. 关键结论

1. 即时消息通知在当前项目中完全可行，最佳入口在模拟交易成交落库之后。
2. 真正困难的不是发消息，而是保存“真实策略决策依据”。
3. 必须扩展策略下单 API，让策略在下单时提交 `reason/decision/indicators/selection`。
4. 数据库应新增通用交易信号、决策明细、指标快照、筛选快照、AI 配置、AI 评分结果、通知事件表。
5. 通知中的买卖理由必须标明来源，区分策略真实理由和系统兜底理由。
6. AI 综合评分应基于股票基础信息、常用指标、完整历史计算后的 K 线指标、策略筛选上下文和账户风控上下文。
7. AI 配置、提示词、模型参数、工具接入和阈值必须可配置且版本化。
8. 第一阶段 AI 评分只建议作为通知展示和人工复核依据，启用交易 gate 需要额外回测和模拟盘验证。
9. 回测和模拟交易应复用同一套决策结构、AI 评分结构和前端展示组件。
10. IM 接入第一阶段优先钉钉，企业微信、QQ 和个人微信不作为第一阶段重点。
11. IM 交易指令必须走确认、风控、审计队列，不能直接从聊天消息触发实盘下单。
12. 通知必须摘要总结优先展示，详情和原始参考数据随后展开。
13. 通知和 AI 的大部分业务参数应支持前端配置，但密钥和生产安全阈值必须留在后端或环境变量中。

---

## 18. 本轮审核结论

### 18.1 合理性结论

当前方案总体合理：通知、交易决策留痕、AI 研判、前端展示和未来 IM 指令被拆成独立模块，边界清晰；钉钉优先接入可以降低第一阶段复杂度；AI 评分默认只做辅助展示，避免过早影响交易结果；数据库表结构能覆盖信号、决策、指标快照、筛选快照、AI 配置、AI 评分、通知事件和 IM 指令。

### 18.2 已补强的严谨性要求

- 明确通知采用“摘要总结在前、详情在后”的结构。
- 明确 AI 评价依据和重要原始参考数据可以在通知中查看，但只展示摘要和关键切片。
- 明确完整 prompt、密钥、长 K 线原文、敏感账户信息不能进入通知。
- 明确通知详情链接应进入系统页面或详情 API，并需要权限控制。
- 明确通知开关、事件类型、摘要字段、详情字段、AI prompt、阈值、数据包范围等应支持前端配置。
- 明确 webhook、secret、AI API key、实盘风控硬阈值等不应在前端明文配置。
- 明确配置修改需要版本化，历史通知和 AI 评分不能被后续配置覆盖。

### 18.3 仍需实现时重点验证

- 前端配置保存后是否生成 `config_version`，并被后端运行快照引用。
- 钉钉通知是否在手机端也能先看到摘要，不被详情内容挤占重点信息。
- AI 证据是否都能追溯到 `input_summary`、指标快照或筛选快照，而不是模型自行编造。
- 权限控制是否覆盖信号详情、AI 评分详情、通知事件详情。
- AI gate 启用前是否完成回测/模拟盘对比验证，避免评分策略未经验证就改变交易行为。
