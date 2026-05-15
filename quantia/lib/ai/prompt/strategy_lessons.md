# 策略代码常见 bug 知识库（自动注入到 strategy_coder / strategy_repairer / strategy_analyst 系统提示词）

> 本文件由 `prompt_loader.load()` 在加载策略相关 agent 系统提示词时自动追加。
> 新条目通过 AI 修复成功后 `record_lesson()` 自动追加，也可由开发者手工补充。
> **格式**：`### [严重程度] 简短标题`，下分 "症状/原因/修复" 三段。

## 必看：历史已踩过的坑（生成代码时严禁重犯）

### [HIGH] AI 擅自扩张用户需求范围（最高频踩坑）
- **症状**：用户明确说"买卖信号仅依赖 5/20 均线金叉死叉，不引入任何其他技术指标或条件"，AI 却额外加上 RSI 过滤 / BOLL 确认 / 量能放大 / 止盈止损，生成的策略与需求出入很大。或者用户说"保持原有季度基本面选股逻辑"，AI 却把 ROE 阈值、PE 区间、频率都改了。
- **原因**：模型倾向于"做加法"——觉得多加几个指标更稳，但用户其实就是想验证一个干净的最小策略。
- **修复**：
  1. **生成前的强制自检**：数一下用户原话里点名了几个买入/卖出条件，点名了几个指标。
  2. **看到限定词就锁死**：用户出现"仅 / 只 / 只依赖 / 不引入 / 不要加 / 保持 / 维持 / 不变"等词，**绝对不允许**写清单外的东西。
  3. **refine 场景**：用户说"保持原有 X"时，X 部分必须**逐字符**与原代码一致；只动用户点名要改的部分。
  4. **风控不是默认项**：用户没明说要止盈止损 / 仓位上限 / 回撤过滤时，**不要**自作主张加。
  5. 写完最后扫一遍代码：每一行能否对应到用户原话里的一个具体要求？不能 → 删掉。

  **反例（违规）**：
  ```python
  # 用户要求："仅 MA5/MA20 金叉死叉买卖"
  # ❌ AI 却加了一堆其他指标
  if ma5 > ma20 and rsi < 70 and close > boll_middle and volume > vol_ma5:
      order_target_value(...)
  ```
  **正例**：
  ```python
  # ✅ 严格按用户原话
  if ma5_yest <= ma20_yest and ma5_today > ma20_today:
      order_target_value(...)
  ```

### [HIGH] talib.STOCH 解包数量错误
- **症状**：策略 `try: k, d, j = talib.STOCH(...) except: continue` 导致全程 0 笔交易，且 `errors[]` 为空（错误被裸 except 吞掉）。
- **原因**：`talib.STOCH` 在 Python 绑定里只返回 `(slowk, slowd)` 两个值，**不是三个**。`k, d, j = ...` 立即抛 `ValueError: not enough values to unpack`，被 `except: continue` 静默吞掉，每个 bar 都在指标计算阶段直接跳过。
- **修复**：
  ```python
  slowk, slowd = talib.STOCH(high, low, close,
                             fastk_period=9, slowk_period=3, slowk_matype=0,
                             slowd_period=3, slowd_matype=0)
  k = pd.Series(slowk); d = pd.Series(slowd)
  # 若策略需要 J 线：j = pd.Series(3*slowk - 2*slowd)
  ```

### [HIGH] 用 `context.current_dt.day == 1` 触发选股 / 调仓
- **症状**：策略在每月 / 每季度首日触发，但实际 0 笔交易；日志里看不到选股记录。
- **原因**：A 股 1/1、5/1、10/1 都是节假日，`handle_data` 当天根本不会被调用，整月 / 整季度被跳过。
- **修复**：用 `g.last_select_month` 游标判断"当前月与上次不同"。
  ```python
  def initialize(context):
      g.last_select_month = None
  def handle_data(context, data):
      m = context.current_dt.month
      if m in (1, 4, 7, 10) and m != g.last_select_month:
          # 选股 ...
          g.last_select_month = m
  ```
  也可用 `context.hold_days += 1; if context.hold_days % rebalance_days != 1: return`（参考策略 89）。

### [HIGH] 裸 except: continue 静默吞掉异常
- **症状**：策略明显跑出 0 笔交易但 `errors[]` 为空、`logs[]` 没有 WARN 行。
- **原因**：`try/except: continue` 把所有异常吞掉，连 `NameError`/`ValueError` 都看不见。
- **修复**：必须捕获 Exception 并记录日志。
  ```python
  try:
      slowk, slowd = talib.STOCH(...)
  except Exception as e:
      log.warn(f"{stock} 指标异常: {e}")
      continue
  ```

### [HIGH] 中间变量在某条 if 分支里赋值，外层无条件引用 → NameError
- **症状**：`NameError: name 'boll_middle_prev' is not defined`，且每天都抛同样错误，最终 0 笔交易。
- **原因**：`boll_middle_prev = boll_middle.iloc[-2]` 写在某个 if 分支内，但下面的 if 引用它。沙箱不会拦 NameError，进入分支就全军覆没。
- **修复**：所有 `*_prev` / `*_now` 中间变量必须**先无条件赋值**再使用，缺数据时给安全默认值。
  ```python
  boll_middle_now = boll_middle.iloc[-1] if len(boll_middle) > 0 else 0
  boll_middle_prev = boll_middle.iloc[-2] if len(boll_middle) >= 2 else 0
  ```

### [HIGH] 选股池为空时未做兜底，导致整段策略空转
- **症状**：基本面筛选条件过严（如 PE<20 + ROE>15% + 营收增速>30% 同时满足），`get_fundamentals` 返回空 df，策略全程 0 笔交易。
- **修复**：
  - 放宽某一维度 OR
  - 准备 `core_pool = ['600519', '000858', '601318', '600036', ...]` 兜底白马股，当动态池为空或不足时合并进去（参考策略 89 `_get_dynamic_pool`）：
    ```python
    for core_code in context.core_pool:
        if core_code not in pool and _is_tradeable(core_code):
            pool.append(core_code)
    ```

### [HIGH] data[code] 直接索引未做存在性检查 → KeyError
- **症状**：`KeyError: '600519'`，单只股票当天没有行情就抛。
- **修复**：
  ```python
  if stock not in data or data[stock].close == 0:
      continue
  ```

### [MED] history() 数据不足未检查 → IndexError / 全 NaN
- **症状**：策略上线初期 / 新股次日 `closes.iloc[-2]` 抛 IndexError，或 `ma20` 全为 NaN。
- **修复**：
  ```python
  closes = history(stock, period + 1, 'close')
  if len(closes) < period + 1:
      continue
  ```

### [MED] 多 AND 共振条件中"刚好跨越"硬边界 → 触发概率极低
- **症状**：3 个以上 AND 条件每个都是"昨天不满足、今天首次满足"，理论合理但实测每股每年只触发 0~2 次，整体 trade_count<5。
- **修复**：保留 AND 方向性逻辑，但把"刚突破"放宽为"在边界 ±2% 范围内"或"近 3 日内任一日满足"。**不要**擅自删条件 / 把 AND 改 OR（违背用户原意）。
  ```python
  # 原：current > lower and prev <= lower  （首次跨越）
  # 改：current > lower * 0.98 and current < lower * 1.02  （边界附近）
  ```

### [MED] cash_per_stock = available_cash * 0.95 / N → 仓位严重不均衡
- **症状**：第 1 只买完后 available_cash 变小，第 2 只买的少，第 3 只更少 …… 实际持仓权重 50%/30%/15%/5%。
- **修复**：用 `total_value / N` 作为每只目标价值，配 `order_target_value`（参考策略 89）：
  ```python
  target_value = context.portfolio.total_value / context.hold_num
  for code in targets:
      order_target_value(code, target_value)
  ```

### [MED] 调仓时未清理"跌出股票池"的旧持仓
- **症状**：第 N 季度入选了股票 A，第 N+1 季度 A 跌出股票池但策略只买入新股，A 一直被持有占用资金。
- **修复**：调仓前先卖掉所有不在新池中的旧持仓（参考策略 89）：
  ```python
  for code in list(context.portfolio.positions.keys()):
      if code not in buffer:
          order_target(code, 0)
  ```

### [LOW] order_target_value 反复调整微小差额 → 手续费侵蚀收益
- **症状**：trade_count 异常高（每天都换手），但每笔金额很小。
- **修复**：加 `drift_threshold` 偏离阈值，差额小于 ±10% 不调整（参考策略 89）：
  ```python
  if abs(current_value - target_value) > target_value * context.drift_threshold:
      order_target_value(code, target_value)
  ```

### [LOW] profit_rate 未扣除手续费就触发止盈/止损
- **症状**：止盈 +5% 触发后实际净收益 +3.5%（被双边 0.15% 手续费 + 0.1% 印花税侵蚀）。
- **修复**：在比较前扣除往返成本（约 0.15%）：
  ```python
  net = ((bar - cost) / cost - context.cost_round_trip) if cost > 0 else 0
  if net <= context.stop_loss: ...
  ```

## 推荐的健壮性辅助函数（直接复制）

```python
def _safe_float(value, default=0):
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default

def _is_tradeable(code):
    """检查股票当日是否可交易（未停牌）"""
    try:
        current_data = get_current_data()
        info = current_data[code]
        return not info.paused
    except Exception:
        return True
```

## 推荐的策略骨架（参考策略 89《动量策略执行优化型》）

```python
def initialize(context):
    context.hold_days = 0
    context.pool_size = 80
    context.hold_num = 3
    context.buffer_num = 8         # 调仓前先卖掉跌出 buffer 的旧持仓
    context.rebalance_days = 20    # 周期调仓，避开 day==1 陷阱
    context.drift_threshold = 0.10 # 偏离 10% 才调整，节省手续费
    context.core_pool = ['600519', '000858', '601318', '600036', ...]  # 兜底白马
    g.last_select_month = None

def handle_data(context, data):
    context.hold_days += 1
    if context.hold_days % context.rebalance_days != 1:
        return

    pool, fundamentals = _get_dynamic_pool(context)  # 含 core_pool 兜底
    if not pool:
        log.info("股票池为空，本期不调仓")
        return

    scores = {}
    for code in pool:
        prices = history(code, 20, 'close')
        if len(prices) < 20 or prices.iloc[0] == 0:  # 数据不足/异常防御
            continue
        # ... 计算评分 ...

    if not scores:
        log.info("无足够历史行情，本期不调仓")
        return

    ranked = sorted(scores, key=scores.get, reverse=True)
    targets = ranked[:context.hold_num]
    buffer  = ranked[:max(context.buffer_num, context.hold_num)]

    # 1) 先卖：跌出 buffer 的清仓
    for code in list(context.portfolio.positions.keys()):
        if code not in buffer:
            order_target(code, 0)

    # 2) 再买：等权目标价值 + 偏离阈值
    target_value = context.portfolio.total_value / context.hold_num
    for code in targets:
        current_pos = context.portfolio.positions.get(code, None)
        current_value = current_pos.value if current_pos else 0
        if abs(current_value - target_value) > target_value * context.drift_threshold:
            order_target_value(code, target_value)
```




### [HIGH] NameError 中间变量未先赋值
- **症状**：修复历史: 错误特征 "NameError" 在生成代码中出现
- **修复**：所有 `*_prev` / `*_now` 中间变量必须先无条件赋值再使用，缺数据时给安全默认值，例如 `boll_middle_prev = boll_middle.iloc[-2] if len(boll_middle) >= 2 else 0`。
