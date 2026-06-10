# Quantia API 接口文档

本文档描述 Quantia 系统提供的 Web API 接口。

---

## 基础信息

- **Base URL**: `http://localhost:9988`
- **响应格式**: JSON / HTML
- **端口**: 9988

---

## 接口列表

### 1. 首页

#### 请求

```
GET /quantia/
```

#### 响应

返回系统首页 HTML 页面。

---

### 2. 获取数据表数据 (API)

#### 请求

```
GET /quantia/api_data
```

#### 参数

| 参数 | 类型 | 必填 | 说明 |
|-----|------|-----|------|
| table_name | string | 是 | 数据表名称 |
| date | string | 否 | 日期 (YYYY-MM-DD) |
| columns | string | 否 | 指定返回列 |
| order | string | 否 | 排序字段 |
| search | string | 否 | 搜索关键字 |
| start | int | 否 | 分页起始位置 |
| length | int | 否 | 每页数量 |

#### 支持的表名

| table_name | 说明 |
|-----------|------|
| cn_stock_spot | 每日股票数据 |
| cn_etf_spot | 每日ETF数据 |
| cn_stock_fund_flow | 股票资金流向 |
| cn_stock_fund_flow_industry | 行业资金流向 |
| cn_stock_fund_flow_concept | 概念资金流向 |
| cn_stock_bonus | 股票分红配送 |
| cn_stock_top | 股票龙虎榜(新浪) |
| cn_stock_lhb | 股票龙虎榜 |
| cn_stock_blocktrade | 股票大宗交易 |
| cn_stock_spot_buy | 基本面选股 |
| cn_stock_indicators | 股票指标数据 |
| cn_stock_strategy_enter | 放量上涨 |
| cn_stock_strategy_keep_increasing | 均线多头 |
| cn_stock_strategy_parking_apron | 停机坪 |
| cn_stock_strategy_backtrace_ma250 | 回踩年线 |
| cn_stock_strategy_breakthrough_platform | 突破平台 |
| cn_stock_strategy_low_backtrace_increase | 无大幅回撤 |
| cn_stock_strategy_turtle_trade | 海龟交易法则 |
| cn_stock_strategy_high_tight_flag | 高而窄的旗形 |
| cn_stock_strategy_climax_limitdown | 放量跌停 |
| cn_stock_strategy_low_atr | 低ATR成长 |
| cn_stock_strategy_trend_pullback | 趋势回调 |
| cn_stock_strategy_oversold_rebound | 超跌反弹 |
| cn_stock_strategy_breakout_confirm | 突破确认 |
| cn_stock_strategy_gpt_value | GPT综合选股 |
| cn_stock_kline_pattern_* | K线形态识别 |
| cn_stock_backtest | 回测验证汇总 |
| cn_stock_selection | 综合选股 |
| cn_stock_chip_race_open | 早盘抢筹数据 |
| cn_stock_chip_race_end | 尾盘抢筹数据 |
| cn_stock_limitup_reason | 涨停原因揭密 |
| cn_strategy_params | 策略参数配置 |

#### 响应示例

```json
{
    "draw": 1,
    "recordsTotal": 5000,
    "recordsFiltered": 5000,
    "data": [
        {
            "date": "2024-01-15",
            "code": "000001",
            "name": "平安银行",
            "new_price": 10.50,
            "change_rate": 1.25,
            ...
        }
    ]
}
```

---

### 3. 获取数据表页面 (HTML)

#### 请求

```
GET /quantia/data
```

#### 参数

| 参数 | 类型 | 必填 | 说明 |
|-----|------|-----|------|
| table_name | string | 是 | 数据表名称 |
| date | string | 否 | 日期 (YYYY-MM-DD) |

#### 响应

返回带有 DataTables 的 HTML 页面。

---

### 4. 获取股票指标图表

#### 请求

```
GET /quantia/data/indicators
```

#### 参数

| 参数 | 类型 | 必填 | 说明 |
|-----|------|-----|------|
| code | string | 是 | 股票代码 (如: 000001) |
| date | string | 否 | 日期 (YYYY-MM-DD) |
| type | string | 否 | 图表类型 |

#### 响应

返回包含 K线图、指标图、筹码分布图的 HTML 页面。

#### 图表内容

- K线图（日K线）
- 成交量图
- MACD 指标
- KDJ 指标
- RSI 指标
- BOLL 指标
- 筹码分布图

---

### 5. 添加/删除关注

#### 请求

```
POST /quantia/control/attention
```

#### 请求体

```json
{
    "code": "000001",
    "action": "add"  // 或 "remove"
}
```

#### 参数

| 参数 | 类型 | 必填 | 说明 |
|-----|------|-----|------|
| code | string | 是 | 股票代码 |
| action | string | 是 | 操作类型: add(添加) / remove(删除) |

#### 响应

```json
{
    "status": "success",
    "message": "关注添加成功"
}
```

---

### 6. 获取策略参数

#### 请求

```
GET /quantia/api/strategy/params
```

#### 参数

| 参数 | 类型 | 必填 | 说明 |
|-----|------|-----|------|
| strategy | string | 是 | 策略类型: gpt_value / moat_scoring / ai_model |

#### 响应示例

```json
{
    "status": "success",
    "data": {
        "strategy": "gpt_value",
        "params": {
            "debt_asset_ratio": {"value": 60, "label": "资产负债率上限(%)"},
            "roe_weight": {"value": 15, "label": "ROE下限(%)"},
            "sale_gpr": {"value": 30, "label": "毛利率下限(%)"}
        }
    }
}
```

---

### 7. 保存策略参数

#### 请求

```
POST /quantia/api/strategy/params/save
```

#### 请求体

```json
{
    "strategy": "gpt_value",
    "params": {
        "debt_asset_ratio": 60,
        "roe_weight": 15,
        "sale_gpr": 30
    }
}
```

---

### 8. 重置策略参数

#### 请求

```
POST /quantia/api/strategy/params/reset
```

#### 请求体

```json
{
    "strategy": "gpt_value"
}
```

---

### 9. 动态筛选股票

#### 请求

```
GET /quantia/api/strategy/filter
```

#### 参数

| 参数 | 类型 | 必填 | 说明 |
|-----|------|-----|------|
| strategy | string | 是 | 策略类型 |
| date | string | 否 | 日期 (YYYY-MM-DD) |

#### 说明

根据用户配置的策略参数，从 `cn_stock_selection` 表动态执行SQL查询，返回满足条件的股票列表。结果有10分钟LRU缓存。

---

### 10. 策略参数生效机制（K线技术策略）

K线技术策略的可调参数（保存在 `cn_strategy_params` 表）通过统一白名单
`_PARAM_WIRED_STRATEGIES`（[strategy_data_daily_job.py](quantia/job/strategy_data_daily_job.py)）真正接入到策略 `check()`：

| 路径 | 是否应用已保存参数 | 说明 |
|------|------------------|------|
| 每日选股任务（`strategy_data_daily_job`） | 是 | `_load_strategy_kwargs(table, func)` 读 `cn_strategy_params`，按 `check()` 签名过滤后 `**kwargs` 传入；重算结果落 `cn_stock_strategy_*` 表 |
| 选股验证中心 / 策略因子实验室（`verifyOptimizeHandler`） | 是 | `_load_verify_strategy_kwargs` 复用同一加载器，扫描 K 线时把参数传入 `check()`；参数签名纳入信号缓存键，调参后缓存自动失效 |
| 动态筛选（`/api/strategy/filter` 的 K 线策略） | 间接 | 读预计算的 `cn_stock_strategy_*` 表，需待每日任务按新参数重算后才反映 |

已接入参数化的策略（参数 key 与 `check()` 形参一一对应，默认值等于历史硬编码、行为不变）：
`enter`、`keep_increasing`、`parking_apron`、`backtrace_ma250`、`breakthrough_platform`、
`low_backtrace_increase`、`turtle_trade`、`high_tight_flag`、`climax_limitdown`、`low_atr`。

> 基本面/指标类策略（`gpt_value`、`fundamental_buy`、`indicator_buy`、`indicator_sell`）的参数直接拼入筛选 SQL，始终即时生效。

> 调整参数后若要让「动态筛选/选股结果表」反映新逻辑，需重新运行 `strategy_data_daily_job`；验证中心则即时生效（首次扫描后走参数化缓存）。

---

## 数据表字段说明

### cn_stock_spot (每日股票数据)

| 字段 | 类型 | 说明 |
|-----|------|------|
| date | DATE | 日期 |
| code | VARCHAR(6) | 股票代码 |
| name | VARCHAR(20) | 股票名称 |
| new_price | FLOAT | 最新价 |
| change_rate | FLOAT | 涨跌幅(%) |
| ups_downs | FLOAT | 涨跌额 |
| volume | BIGINT | 成交量(股) |
| deal_amount | BIGINT | 成交额(元) |
| amplitude | FLOAT | 振幅(%) |
| turnoverrate | FLOAT | 换手率(%) |
| volume_ratio | FLOAT | 量比 |
| open_price | FLOAT | 今开 |
| high_price | FLOAT | 最高 |
| low_price | FLOAT | 最低 |
| pre_close_price | FLOAT | 昨收 |
| pe | FLOAT | 市盈率(静) |
| pbnewmrq | FLOAT | 市净率 |
| total_market_cap | BIGINT | 总市值 |
| free_cap | BIGINT | 流通市值 |
| industry | VARCHAR(20) | 所属行业 |

### cn_stock_indicators (技术指标数据)

| 字段 | 类型 | 说明 |
|-----|------|------|
| date | DATE | 日期 |
| code | VARCHAR(6) | 股票代码 |
| macd | FLOAT | MACD值 |
| macds | FLOAT | MACD信号线 |
| macdh | FLOAT | MACD柱 |
| kdjk | FLOAT | KDJ-K值 |
| kdjd | FLOAT | KDJ-D值 |
| kdjj | FLOAT | KDJ-J值 |
| rsi | FLOAT | RSI(14) |
| rsi_6 | FLOAT | RSI(6) |
| boll | FLOAT | BOLL中轨 |
| boll_ub | FLOAT | BOLL上轨 |
| boll_lb | FLOAT | BOLL下轨 |
| cr | FLOAT | CR指标 |
| wr | FLOAT | 威廉指标 |
| cci | FLOAT | CCI指标 |
| atr | FLOAT | ATR指标 |
| pdi | FLOAT | +DI |
| mdi | FLOAT | -DI |
| adx | FLOAT | ADX |

---

## 错误处理

### 错误响应格式

```json
{
    "error": true,
    "message": "错误描述信息"
}
```

### 常见错误码

| 错误 | 说明 |
|-----|------|
| 400 | 参数错误 |
| 404 | 资源不存在 |
| 500 | 服务器内部错误 |

---

## 使用示例

### Python 示例

```python
import requests

# 获取股票数据
response = requests.get(
    'http://localhost:9988/quantia/api_data',
    params={
        'table_name': 'cn_stock_spot',
        'date': '2024-01-15',
        'length': 100
    }
)
data = response.json()
print(f"获取到 {len(data['data'])} 条数据")

# 添加关注
response = requests.post(
    'http://localhost:9988/quantia/control/attention',
    json={'code': '000001', 'action': 'add'}
)
print(response.json())
```

### JavaScript 示例

```javascript
// 获取股票数据
fetch('/quantia/api_data?table_name=cn_stock_spot&date=2024-01-15')
    .then(response => response.json())
    .then(data => {
        console.log(`获取到 ${data.data.length} 条数据`);
    });

// 添加关注
fetch('/quantia/control/attention', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({code: '000001', action: 'add'})
})
    .then(response => response.json())
    .then(data => console.log(data));
```

### cURL 示例

```bash
# 获取股票数据
curl "http://localhost:9988/quantia/api_data?table_name=cn_stock_spot&date=2024-01-15"

# 添加关注
curl -X POST "http://localhost:9988/quantia/control/attention" \
    -H "Content-Type: application/json" \
    -d '{"code":"000001","action":"add"}'
```

---

## 注意事项

1. 所有日期参数格式为 `YYYY-MM-DD`
2. 股票代码为6位数字字符串
3. API 返回数据量较大时建议使用分页
4. 关注功能需要先运行数据作业创建相关表

---

## 回测验证 API

### 获取回测配置

```
GET /quantia/api/backtest/config
```

**响应**: 返回可用的回测周期和策略列表

```json
{
  "periods": [{"value": "1w", "label": "1周", "days": 5}, ...],
    "strategies": [{"name": "cn_stock_strategy_enter", "cn": "放量上涨", "type": "strategy"}, ...],
    "default_horizons": [1, 3, 5, 10, 20],
    "max_table_horizon": 100
}
```

### 执行单股回测

```
GET /quantia/api/backtest/run
```

| 参数 | 类型 | 必填 | 说明 |
|-----|------|-----|------|
| code | string | 是 | 股票代码（如 000001） |
| strategy | string | 否 | 策略名称 |
| period | string | 否 | 回测周期（1w/2w/1m/3m/6m/1y），默认 1m |
| start_date | string | 否 | 开始日期（YYYY-MM-DD），默认自动选择 |
| end_date | string | 否 | 结束日期（YYYY-MM-DD），默认自动选择 |
| checkpoints | string | 否 | 回测输出点（逗号分隔，如 1,3,5,10,20），默认使用系统默认值 |

**响应**: 返回买入价、各周期收益率、最大涨幅/回撤、策略命中、关键指标

### 批量策略回测

```
GET /quantia/api/backtest/batch
```

| 参数 | 类型 | 必填 | 说明 |
|-----|------|-----|------|
| strategy | string | 是 | 策略名称 |
| period | string | 否 | 回测周期，默认 1m |
| limit | int | 否 | 统计天数，默认 30 |
| horizons | string | 否 | 汇总使用的持有天数列表（逗号分隔，如 1,3,5,10,20） |
| success_days | int | 否 | 成功定义使用的持有天数（对应 rate_N > 0） |

**响应**: 返回策略按日汇总的选股数量、成功率、平均收益

---

## 回测看板 API

> 用于 Vue 前端菜单：选股验证 → 回测看板。

### 日期区间参数说明

看板相关接口统一支持以下区间参数：

- `start_date` / `end_date`：显式日期区间（优先级最高）
- `days`：最近 N 个交易日窗口（未传显式区间时生效）

日期格式建议使用 `YYYY-MM-DD`。

看板接口兼容：`YYYYMMDD` / `YYYY/MM/DD` / `YYYY.MM.DD`。

> 说明：若传入了 `start_date` 或 `end_date` 但格式不合法，接口将返回 `error`。

错误响应示例：

```json
{
    "error": "start_date 格式不正确，支持 YYYY-MM-DD 或 YYYYMMDD"
}
```

### 跨策略总览

```
GET /quantia/api/backtest/dashboard/overview
```

| 参数 | 类型 | 必填 | 说明 |
|-----|------|-----|------|
| days | int | 否 | 最近 N 个交易日窗口，默认 60 |
| start_date | string | 否 | 显式区间开始日期 |
| end_date | string | 否 | 显式区间结束日期 |
| metric | int | 否 | 排名指标持有天数（仅支持 1/3/5/10/20），默认 5 |

**响应**: 返回每个策略的信号数、平均成功率、各 horizon 的平均收益、最佳/最差日期。

示例：

```json
{
    "date_range": {"start": "2026-01-02", "end": "2026-02-27", "count": 40},
    "horizons": [1, 3, 5, 10, 20],
    "metric_horizon": 5,
    "items": [
        {
            "strategy_name": "cn_stock_strategy_enter",
            "strategy_cn": "放量上涨",
            "type": "strategy",
            "total_signals": 123,
            "avg_success_rate": 56.78,
            "avg_returns": {"1d": 0.12, "3d": 0.56, "5d": 1.23, "10d": 2.34, "20d": 3.21},
            "best_day": "2026-02-10",
            "worst_day": "2026-01-13"
        }
    ]
}
```

### 策略表现时间序列（按信号日）

```
GET /quantia/api/backtest/dashboard/timeline
```

| 参数 | 类型 | 必填 | 说明 |
|-----|------|-----|------|
| strategies | string | 否 | 策略列表（逗号分隔），为空表示全部 |
| days | int | 否 | 最近 N 个交易日窗口，默认 90 |
| start_date | string | 否 | 显式区间开始日期 |
| end_date | string | 否 | 显式区间结束日期 |
| horizon | int | 否 | 收益周期（仅支持 1/3/5/10/20），默认 5 |

**响应**: 返回每个策略的时间序列点（date/value）。

示例：

```json
{
    "date_range": {"start": "2026-01-02", "end": "2026-02-27", "count": 40},
    "horizon": 5,
    "series": [
        {
            "strategy_name": "cn_stock_strategy_enter",
            "strategy_cn": "放量上涨",
            "data": [
                {"date": "2026-02-25", "value": 1.23},
                {"date": "2026-02-26", "value": 0.56},
                {"date": "2026-02-27", "value": null}
            ]
        }
    ]
}
```

### 单策略明细（选股列表）

```
GET /quantia/api/backtest/dashboard/strategy_detail
```

| 参数 | 类型 | 必填 | 说明 |
|-----|------|-----|------|
| strategy | string | 是 | 策略名称 |
| days | int | 否 | 最近 N 个交易日窗口，默认 30 |
| start_date | string | 否 | 显式区间开始日期 |
| end_date | string | 否 | 显式区间结束日期 |
| horizons | string | 否 | 明细收益周期列表（逗号分隔，支持 1..100），默认 1,3,5,10,20 |
| page | int | 否 | 页码，默认 1 |
| page_size | int | 否 | 每页数量，默认 50 |

**响应**: 返回分页 rows，包含 `rate_{h}` 列。

示例：

```json
{
    "strategy_name": "cn_stock_strategy_enter",
    "strategy_cn": "放量上涨",
    "date_range": {"start": "2026-02-01", "end": "2026-02-27", "count": 20},
    "horizons": [1, 3, 5, 10, 20],
    "page": 1,
    "page_size": 50,
    "total": 321,
    "rows": [
        {
            "date": "2026-02-27",
            "code": "000001",
            "name": "平安银行",
            "rate_1": 0.12,
            "rate_3": 0.56,
            "rate_5": 1.23,
            "rate_10": 2.34,
            "rate_20": 3.21
        }
    ]
}
```

### 收益分布

```
GET /quantia/api/backtest/dashboard/distribution
```

| 参数 | 类型 | 必填 | 说明 |
|-----|------|-----|------|
| strategy | string | 是 | 策略名称 |
| days | int | 否 | 最近 N 个交易日窗口，默认 60 |
| start_date | string | 否 | 显式区间开始日期 |
| end_date | string | 否 | 显式区间结束日期 |
| horizon | int | 否 | 收益周期（支持 1..100），默认 5 |

**响应**: 返回分箱统计 bins（range/count/percentage）。

示例：

```json
{
    "strategy_name": "cn_stock_strategy_enter",
    "strategy_cn": "放量上涨",
    "date_range": {"start": "2026-01-02", "end": "2026-02-27", "count": 40},
    "horizon": 5,
    "bins": [
        {"range": "<-10%", "count": 3, "percentage": 1.2},
        {"range": "-10%~-5%", "count": 12, "percentage": 4.8},
        {"range": "-5%~0%", "count": 88, "percentage": 35.2},
        {"range": "0%~5%", "count": 110, "percentage": 44.0},
        {"range": "5%~10%", "count": 30, "percentage": 12.0},
        {"range": ">10%", "count": 7, "percentage": 2.8}
    ],
    "total": 250
}
```

### 买入-卖出配对明细

```
GET /quantia/api/backtest/dashboard/trade_pairs
```

| 参数 | 类型 | 必填 | 说明 |
|-----|------|-----|------|
| strategy | string | 是 | 策略名称（买入信号来源） |
| days | int | 否 | 最近 N 个交易日窗口，默认 60 |
| start_date | string | 否 | 显式区间开始日期 |
| end_date | string | 否 | 显式区间结束日期 |
| max_hold | int | 否 | 最大持有天数（无卖点时超时退出），默认 100 |
| page | int | 否 | 页码，默认 1 |
| page_size | int | 否 | 每页数量，默认 50 |

**响应**: 返回 buy/sell 日期、价格、持有天数、收益率与退出类型（signal/timeout）。

示例：

```json
{
    "strategy_name": "cn_stock_strategy_enter",
    "strategy_cn": "放量上涨",
    "date_range": {"start": "2026-01-02", "end": "2026-02-27", "count": 40},
    "page": 1,
    "page_size": 50,
    "total": 321,
    "max_hold": 100,
    "rows": [
        {
            "buy_date": "2026-02-10",
            "sell_date": "2026-02-18",
            "code": "000001",
            "name": "平安银行",
            "hold_days": 6,
            "buy_price": 12.34,
            "sell_price": 13.21,
            "return_rate": 7.05,
            "exit_type": "signal"
        },
        {
            "buy_date": "2026-02-12",
            "sell_date": "2026-02-27",
            "code": "000002",
            "name": "万科A",
            "hold_days": 11,
            "buy_price": 9.87,
            "sell_price": 9.55,
            "return_rate": -3.24,
            "exit_type": "timeout"
        }
    ]
}
```

---

## 交易日期 API

### 获取最近交易日期

```
GET /quantia/api/trade_date
```

**响应**:

```json
{
  "run_date": "2026-02-13",
  "run_date_nph": "2026-02-13"
}
```

- `run_date`: 最近已收盘的交易日（用于非实时数据表）
- `run_date_nph`: 当前交易日（含未收盘，用于实时数据表）

---

## 模拟交易 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/quantia/api/paper/list` | 获取所有模拟账户列表 |
| POST | `/quantia/api/paper/create` | 创建模拟账户（指定策略+初始资金） |
| POST | `/quantia/api/paper/start` | 启动模拟交易 |
| POST | `/quantia/api/paper/stop` | 停止模拟交易 |
| GET | `/quantia/api/paper/detail` | 账户详情（持仓+NAV+收益） |
| GET | `/quantia/api/paper/history` | 历史交易记录 |
| GET | `/quantia/api/paper/nav` | 净值曲线数据 |
| POST | `/quantia/api/paper/code` | 获取/保存策略代码 |
| POST | `/quantia/api/paper/backtest` | 对当前策略代码运行回测 |

---

## 自定义综合指标 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/quantia/api/custom_indicator/list` | 指标列表 |
| POST | `/quantia/api/custom_indicator/save` | 创建/更新指标 |
| DELETE | `/quantia/api/custom_indicator/delete` | 删除指标 |
| GET | `/quantia/api/custom_indicator/detail` | 指标详情（含配置） |
| POST | `/quantia/api/custom_indicator/backtest` | 指标回测 |
| GET | `/quantia/api/custom_indicator/universe` | 当前股票池结果 |
| GET | `/quantia/api/custom_indicator/watchlist` | 关注榜 |

---

## 因子实验室 API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/quantia/api/factor/ic_analysis` | IC/IR 因子有效性分析 |
| POST | `/quantia/api/factor/decay` | 因子衰减分析 |
| POST | `/quantia/api/factor/group_return` | 分组回测收益 |
| POST | `/quantia/api/factor/correlation` | 因子相关性矩阵 |
| POST | `/quantia/api/factor/turnover` | 换手率分析 |
| POST | `/quantia/api/factor/composite` | 复合因子构建 |
| GET | `/quantia/api/factor/available_factors` | 可用因子列表 |
| GET | `/quantia/api/factor/presets` | 预设因子组合 |

---

## AI 策略助手 API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/quantia/api/ai/generate` | AI 策略生成 |
| POST | `/quantia/api/ai/optimize` | 策略优化建议 |
| POST | `/quantia/api/ai/repair` | 策略错误修复 |
| POST | `/quantia/api/ai/chat` | 对话（支持工具调用） |
| GET | `/quantia/api/ai/conversations` | 会话列表 |
| GET | `/quantia/api/ai/conversation/:id` | 会话历史 |
| DELETE | `/quantia/api/ai/conversation/:id` | 删除会话 |
| GET | `/quantia/api/ai/agents` | Agent 列表 |
| POST | `/quantia/api/ai/agent` | 创建/更新 Agent |
| DELETE | `/quantia/api/ai/agent/:id` | 删除 Agent |
| GET | `/quantia/api/ai/config` | AI 配置（模型列表） |
| POST | `/quantia/api/ai/kb/search` | 知识库检索 |

---

## 通知配置 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/quantia/api/notification/config` | 获取通知配置 |
| POST | `/quantia/api/notification/config` | 保存通知配置 |
| POST | `/quantia/api/notification/test` | 发送测试通知 |
| GET | `/quantia/api/notification/channels` | 通道列表 |
| POST | `/quantia/api/notification/channel` | 创建/更新通道 |
| DELETE | `/quantia/api/notification/channel/:id` | 删除通道 |
| GET | `/quantia/api/notification/events` | 通知事件列表 |
| GET | `/quantia/api/notification/event/:id` | 事件详情 |

---

## 鉴权 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/quantia/api/auth/me` | 当前用户信息（未启用鉴权返回 enabled=false） |
| POST | `/quantia/api/auth/login` | 登录（用户名/邮箱/昵称） |
| POST | `/quantia/api/auth/logout` | 退出 |
| POST | `/quantia/api/auth/register` | 自助注册 |
| POST | `/quantia/api/auth/send_code` | 发送邮箱验证码 |
| GET | `/quantia/api/auth/users` | 用户列表（admin） |
| PUT | `/quantia/api/auth/user/:id` | 更新用户角色/状态 |
| DELETE | `/quantia/api/auth/user/:id` | 删除用户 |
| GET | `/quantia/api/auth/audit` | 操作审计日志 |

---

## IM 指令 API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/quantia/api/im/callback` | 钉钉回调入口 |
| GET | `/quantia/api/im/operators` | 操作人白名单 |
| POST | `/quantia/api/im/operator` | 添加操作人 |
| DELETE | `/quantia/api/im/operator/:id` | 删除操作人 |
| GET | `/quantia/api/im/commands` | 指令记录 |
| POST | `/quantia/api/im/confirm` | 手动确认指令 |
| POST | `/quantia/api/im/reject` | 手动拒绝指令 |

---

## 组合回测 API

> 聚宽风格的组合回测引擎，支持多股票持仓、T+1交易、基本面选股。

### 获取策略模板列表

```
GET /quantia/api/strategy/templates
```

**响应**:

```json
{
  "code": 0,
  "data": [
    {
      "id": "bank_rotation",
      "name": "银行股轮动策略(聚宽)",
      "category": "stock",
      "description": "持有中证银行指数(399951)成份股中PB最低的银行股，每周一轮动",
      "code": "def initialize(context): ..."
    }
  ]
}
```

### 运行组合回测

```
POST /quantia/api/backtest/portfolio/run
```

**请求体 (JSON)**:

| 字段 | 类型 | 必填 | 说明 |
|------|------|-----|------|
| code | string | 是 | Python策略代码 |
| strategy_id | int | 否 | 关联的策略ID |
| start_date | string | 是 | 开始日期 YYYY-MM-DD |
| end_date | string | 是 | 结束日期 YYYY-MM-DD |
| initial_cash | float | 否 | 初始资金，默认1000000 |
| benchmark | string | 否 | 基准指数代码，默认000300 |
| commission_rate | float | 否 | 佣金率，默认0.0003 |
| stamp_tax_rate | float | 否 | 印花税率，默认0.001 |
| slippage | float | 否 | 滑点率，默认0.002 |

> 注意：回测在后台线程池中运行（max_workers=2），不会阻塞其他API请求。

**响应**:

```json
{
  "code": 0,
  "data": {
    "status": "completed",
    "backtest_id": 42,
    "metrics": {
      "total_return": 18.20,
      "annual_return": 8.83,
      "max_drawdown": 26.90,
      "sharpe_ratio": 0.44,
      "sortino_ratio": 0.50,
      "trade_count": 7
    },
    "nav": [...],
    "trades": [...],
    "positions": [...],
    "logs": [...]
  }
}
```

### 获取历史回测列表

```
GET /quantia/api/backtest/portfolio/list
```

**参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|-----|------|
| strategy_id | int | 否 | 按策略ID筛选 |

### 获取回测详情

```
GET /quantia/api/backtest/portfolio/detail?id={backtest_id}
```

**响应**: 包含完整的 metrics / nav / trades / positions / logs 数据。

---

## 策略融合验证 v2

`/quantia/api/verify/fusion` 支持 v1（多条 `strategy_names` 简单交并集，兼容旧前端）与 v2（5 维 × 4 模式真融合，含 Shapley/AB/Overlap 贡献分析）。请求体携带 `version: 2` 切换到 v2 路径。

### POST /quantia/api/verify/fusion （v2）

**请求体**：

```jsonc
{
  "version": 2,
  "mode": "weighted_score",          // weighted_score | vote | condition_tree | rotation
  "start_date": "2026-03-01",         // 必填，YYYY-MM-DD；区间 ≤ 366 天
  "end_date": "2026-05-14",           // 必填
  "holding_days": 10,                  // 持仓天数，影响 rate_df 计算口径
  "min_score": 0.4,                    // weighted_score 模式生效，[0,1]
  "vote_threshold": 2,                 // vote 模式生效，至少命中维度数
  "dimensions": {
    "tech":   { "enabled": true,  "weight": 40, "items": ["cn_stock_strategy_keep_increasing"] },
    "fund":   { "enabled": true,  "weight": 30, "items": ["pe9_lt_30", "roe_weight_gte_10"] },
    "flow":   { "enabled": true,  "weight": 30, "items": ["fund_amount_gt_0"] },
    "sent":   { "enabled": false, "weight": 0,  "items": [] },
    "custom": { "enabled": false, "weight": 0,  "items": [] }   // items 形如 "cn_stock_strategy_custom_<id>"
  }
}
```

**维度 items 取值约定**：

| 维度 | items 形式 | 数据源 |
|------|-----------|--------|
| `tech` | `cn_stock_strategy_<name>` | `cn_stock_strategy_*` 信号表 |
| `fund` | `<col>_<op>_<val>`，op ∈ {lt,gt,lte,gte,eq}，col ∈ `_FUND_ALLOWED_COLS` | `cn_stock_indicators_buy` |
| `flow` | `<col>_<op>_<val>`，col ∈ `_FLOW_ALLOWED_COLS` | `cn_stock_fund_flow` |
| `sent` | TODO（Stage 1 暂未接入） | — |
| `custom` | `cn_stock_strategy_custom_<id>` | 自定义策略落库表 |

**响应**：

```jsonc
{
  "version": 2,
  "mode": "weighted_score",
  "holding_days": 10,
  "period": { "start": "2026-03-01", "end": "2026-05-14" },
  "fusion_result": {
    "sharpe": -0.169, "win_rate": 48.2, "max_drawdown": -8.7,
    "signal_count": 20166, "avg_return": 0.31, "daily_signal_avg": 429.1
  },
  "individual_results": {
    "tech": { "cn": "技术信号", "sharpe": -0.16, "win_rate": 48.0, ... },
    "fund": { ... }, "flow": { ... }
  },
  "daily_series": [ { "date": "2026-03-02", "cumulative": 0.0, "drawdown": 0.0 }, ... ],

  // ── Stage 3 真贡献分析 ──
  "shapley": [
    { "dim": "tech", "cn": "技术信号", "name": "技术信号",
      "contrib": 0.4456, "contribution": 0.4456, "sharpe_delta": 0.4456, "rank": 1 },
    { "dim": "flow", ..., "rank": 2 },
    { "dim": "fund", ..., "rank": 3 }
  ],
  "ab_steps": [
    { "step": 1, "dims": ["tech"], "label": "技术信号",
      "sharpe": -0.159, "win_rate": 47.8, "max_drawdown": -8.2,
      "signal_count": 19951, "avg_return": 0.28 },
    { "step": 2, "dims": ["tech","flow"], "label": "技术信号 + 资金流", ... },
    { "step": 3, "dims": ["tech","flow","fund"], ... }
  ],
  "overlap": {
    "calendar":      [ { "date": "2026-03-02", "signal_count": 2699, "dims_hit": 3 }, ... ],
    "co_occurrence": [ { "a": "tech", "b": "tech", "jaccard": 1.0 },
                       { "a": "tech", "b": "fund", "jaccard": 0.0188 }, ... ]   // N×N 扁平 list（含对角）
  },

  "improvement": { "sharpe_vs_best_single": "+12.3%", "drawdown_vs_worst_single": "+4.5%" },
  "warnings": [],
  "diagnostics": {
    "enabled_dims": ["tech", "fund", "flow"],
    "shapley": { "n_dims": 3, "n_subsets_evaluated": 7, "total_subsets": 8, "elapsed_s": 1.32 }
  }
}
```

**Shapley 实现**：`_shapley_real` 用 $2^n - 1$ 个非空子集枚举（`math.factorial` 权重），满足 $\sum_k \phi_k = v(N)$（v(∅)=0）。8 秒时间预算超时则降级为 `_shapley_naive`（单 dim 留一法），响应 `warnings` 会包含 `"Shapley 真值计算超时（已评估 X/Y 子集），降级为快速估算"`。

**AB 步进**：按 Shapley `rank` 升序逐步累加维度，每步重算融合得到 `sharpe / win_rate / max_drawdown / signal_count`。`_fuse_subset_signals` 会将子集内权重重新归一化到 100，`vote_threshold` clip 到子集大小。

**Overlap**：
- `calendar` 按日期聚合不重复股票数 + `dims_hit`（当日出现的维度数）。
- `co_occurrence` 用 (date, code) pair 集合的 Jaccard：对角恒为 1.0，矩阵对称。

**错误**：

| code | 场景 |
|------|------|
| 400 | `mode` 非法 / 无 enabled 维度 / 区间 > 366 天 / 维度 weight 非法 / item 表达式不合法 |
| 200 + warnings | 某维度命中 0（该维度被丢弃，`diagnostics.enabled_dims` 不含它） |

### POST /quantia/api/verify/fusion （v1 — 旧版兼容）

省略 `version` 或 `version != 2` 时走旧路径。请求体：

```jsonc
{ "strategy_names": ["放量上涨", "均线多头"],
  "mode": "intersection",          // intersection | union | weighted
  "start_date": "2026-03-01", "end_date": "2026-05-14" }
```

返回简单交并集统计；不含 shapley/ab_steps/overlap 字段。
