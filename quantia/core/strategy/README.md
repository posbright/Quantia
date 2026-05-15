# 选股策略模块

## 目录结构

```
quantia/core/strategy/
├── __init__.py               # 模块入口
├── enter.py                  # 放量上涨策略
├── keep_increasing.py        # 均线多头策略
├── parking_apron.py          # 停机坪策略
├── backtrace_ma250.py        # 回踩年线策略
├── breakthrough_platform.py  # 突破平台策略
├── low_backtrace_increase.py # 无大幅回撤策略
├── turtle_trade.py           # 海龟交易法则策略
├── high_tight_flag.py        # 高而窄的旗形策略
├── climax_limitdown.py       # 放量跌停策略
├── low_atr.py                # 低ATR成长策略
├── gpt_value_strategy.py     # GPT综合选股策略（基本面）
├── base.py                   # 策略基类
├── technical/                # 技术策略扩展
│   ├── __init__.py
│   ├── ma_strategies.py      # 均线相关策略
│   └── value_invest_strategies.py  # 趋势回调/超跌反弹/突破确认
└── document/                 # 策略文档
    └── ChatGP选股策略文档.md   # GPT综合选股策略参考文档
```

## 策略分类

### 前端分类

在前端路由中，策略按照以下方式分类：

#### K线形态菜单（/kline/）

基于K线和成交量的技术策略：

| 策略文件 | 中文名 | 表名 | 说明 |
|---------|-------|------|------|
| `enter.py` | 放量上涨 | cn_stock_strategy_enter | 放量上涨超2%,量比超2 |
| `keep_increasing.py` | 均线多头 | cn_stock_strategy_keep_increasing | MA30均线持续上涨超20% |
| `parking_apron.py` | 停机坪 | cn_stock_strategy_parking_apron | 涨停后横盘整理 |
| `backtrace_ma250.py` | 回踩年线 | cn_stock_strategy_backtrace_ma250 | 突破年线后回踩不破 |
| `breakthrough_platform.py` | 突破平台 | cn_stock_strategy_breakthrough_platform | 放量突破60日均线 |
| `low_backtrace_increase.py` | 无大幅回撤 | cn_stock_strategy_low_backtrace_increase | 稳健上涨无大幅回撤 |

#### 策略选股菜单（/strategy/）

| 策略文件 | 中文名 | 表名 | 说明 |
|---------|-------|------|------|
| `turtle_trade.py` | 海龟交易法则 | cn_stock_strategy_turtle_trade | 突破60日新高 |
| `high_tight_flag.py` | 高而窄的旗形 | cn_stock_strategy_high_tight_flag | 快速上涨后窄幅整理 |
| `climax_limitdown.py` | 放量跌停 | cn_stock_strategy_climax_limitdown | 放量跌停,可能恐慌抛售 |
| `low_atr.py` | 低ATR成长 | cn_stock_strategy_low_atr | 低波动稳健上涨 |
| `technical/value_invest_strategies.py` | 趋势回调 | cn_stock_strategy_trend_pullback | 优质公司趋势内回调买入 |
| `technical/value_invest_strategies.py` | 超跌反弹 | cn_stock_strategy_oversold_rebound | 超跌修复买入 |
| `technical/value_invest_strategies.py` | 突破确认 | cn_stock_strategy_breakout_confirm | 横盘后放量突破确认买入 |
| `gpt_value_strategy.py` | GPT综合选股 | cn_stock_strategy_gpt_value | 基本面策略，独立作业 |

### 后端分类

- **K线策略**（在 `TABLE_CN_STOCK_STRATEGIES` 列表中）：共 13 种策略，由 `strategy_data_daily_job.py` 统一执行，使用历史K线数据判断。
- **GPT综合选股**（独立常量 `TABLE_CN_STOCK_STRATEGY_GPT_VALUE`）：基本面策略，由独立的 `gpt_value_data_job.py` 执行，使用 `cn_stock_selection` 表的财务数据筛选。

## 策略接口

### K线策略（标准接口）

所有K线策略实现统一的函数签名：

```python
def check(code_name, data, date=None, threshold=60):
    """
    检查股票是否满足策略条件

    Args:
        code_name: (date, code, name) 元组
        data: 历史K线数据 DataFrame
        date: 日期
        threshold: 最小数据长度要求

    Returns:
        bool: 是否满足条件
    """
```

### GPT综合选股（基本面接口）

GPT综合选股使用不同的接口，从 `cn_stock_selection` 数据中筛选：

```python
from quantia.core.strategy.gpt_value_strategy import (
    check_gpt_value_from_selection,
    filter_gpt_value_stocks
)

# 检查单只股票
result = check_gpt_value_from_selection(stock_row)

# 批量筛选
filtered = filter_gpt_value_stocks(selection_dataframe)
```

**筛选条件**：
1. 资产负债率 < 60%
2. 每股经营现金流 > 0
3. ROE(加权) >= 15%
4. 毛利率 >= 30%
5. 净利率 >= 10%
6. 营收3年CAGR > 10%
7. 净利润3年CAGR > 10%
8. PE(TTM) 在 (0, 50] 之间

## 策略注册

策略通过 `quantia/core/tablestructure.py` 进行注册：

- K线策略注册在 `TABLE_CN_STOCK_STRATEGIES` 列表中，每个策略包含表名、中文名、列定义和检查函数。
- GPT综合选股注册为独立常量 `TABLE_CN_STOCK_STRATEGY_GPT_VALUE`，并在 `singleton_stock_web_module_data.py` 中手动注册到 Web 模块数据。

## 作业执行

所有策略在 `execute_daily_job.py` 的作业流程中执行：

1. K线策略：步骤 5，由 `strategy_data_daily_job.py` 并行执行
2. GPT综合选股：步骤 5.1，由 `gpt_value_data_job.py` 并行执行
3. 回测：步骤 6，由 `backtest_data_daily_job.py` 统一回测所有策略（含GPT）

## 创建新策略

### 添加K线策略

1. 在 `quantia/core/strategy/` 创建策略文件
2. 实现 `check(code_name, data, date=None, threshold=60)` 函数
3. 在 `tablestructure.py` 的 `TABLE_CN_STOCK_STRATEGIES` 列表中注册

### 添加基本面策略

1. 在 `quantia/core/strategy/` 创建策略文件
2. 在 `tablestructure.py` 添加独立的表结构常量
3. 在 `quantia/job/` 创建独立的作业文件
4. 在 `execute_daily_job.py` 中添加作业调用
5. 在 `singleton_stock_web_module_data.py` 中注册 Web 模块数据
6. 在 `backtest_data_daily_job.py` 的 `prepare()` 中添加表到回测列表
7. 在前端 `router/index.ts` 中添加路由
