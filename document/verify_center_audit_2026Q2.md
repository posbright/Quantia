# 选股验证中心 第三轮全功能审计报告（2026 Q2）

> 范围：`/quantia/api/verify/*` 全部 14 个端点 + 前端 `optimize / compare / fusion /
> factorLab` 四个视图，关注 **DB 数据不足 / 异常参数 / 安全注入** 三类场景，
> 排查"静默吞错"与"错误信息隐藏"。

## 1. 审计方法

| 维度 | 做法 |
| --- | --- |
| 代码审阅 | 全文阅读 `verifyOptimizeHandler.py`（~2700 行）、`verifyFusionHandler.py`、`factorLabHandler.py`；按 `except` / `_write_error` / `warnings.append` 三个关键字盘点错误分支 |
| 黑盒探针 | 编写 PowerShell 脚本 `_audit_probe3.ps1`，对 25+ 边界场景（未来日期、超大 max_hold、非法 indicator、SQL 注入、custom_xxx 不存在、空 fusion 配置等）逐一打 HTTP，落库到 `_audit_out.txt` |
| 真实数据回归 | 用 `cn_stock_strategy_enter` 在 `2026-03-01 ~ 2026-05-14` 区间（4322 条信号）跑全部端点，确认 200 + 业务数值合理 |
| 静默吞错扫描 | 全仓 grep `except\s*\w*\s*:\s*pass`、`except:\s*$`、`logging\.error.*exc_info=False`，并人工复核 `verify` 相关模块 |

## 2. 端点总览

| 端点 | 路径 | 空数据 | 异常参数 | 自定义策略 | 静默吞错 | 备注 |
| --- | --- | --- | --- | --- | --- | --- |
| holding_period | `verify/holding_period` | ✅ 200+msg | ✅ 400 校验 | ❌ 未支持 | 无 | 前端不触发 custom，影响仅 API 层 |
| signal_quality | `verify/signal_quality` | ✅ 200+msg | ✅ 400（提示可用 indicator 白名单） | ❌ 未支持 | 无 | indicator 必须 `rsi_6/rsi_12/macd_dif/...`，不接受裸 `rsi` |
| sl_tp_matrix | `verify/sl_tp_matrix` | ✅ 200+msg | ✅（含 P1 修复） | ✅ `_handle_custom` | 无 | **P1 修复见 §3.1** |
| market_regime | `verify/market_regime` | ✅ 200+msg（**P2 修复**） | ✅ 400 | ❌ 未支持 | 无 | **P2 修复见 §3.2** |
| signal_decay | `verify/signal_decay` | ✅ 200+msg | ✅ 400 | ❌ 未支持 | 无 | |
| cost_sensitivity | `verify/cost_sensitivity` | ✅ 200+msg | ✅ 400 | ❌ 未支持 | 无 | |
| exit_compare | `verify/exit_compare` | ✅ 200+msg | ✅ 400 | ❌ 未支持 | 无 | 同步加 float64 强转（§3.1） |
| return_series | `verify/return_series` | ✅ 200+msg | ✅ 400 | ❌ 未支持 | 无 | |
| optimize_suggest | `verify/optimize_suggest` | ✅ 200+msg | ✅ 400 | ✅ | 无 | |
| custom_compare | `verify/custom_compare` | ✅ 202 轮询 / 200+msg | ✅ 400 | ✅ | 无 | Shapley 超时 → warning，非静默 |
| custom_return_series | `verify/custom_return_series` | ✅ 200+msg | ✅ 400 | ✅ | 无 | |
| fusion_evaluate | `verify/fusion/evaluate` | ✅ 200+warnings | ✅ 400 | ✅ | 无 | 维度命中 0 → `warnings:["..."]` 显式上报 |
| fusion_save / list / delete | `verify/fusion/scheme_*` | ✅ | ✅ 400 | – | 无 | |
| factor_lab/* | `verify/factor_lab/*` | ✅ 200+msg | ✅ 400 | – | 无 | |

> 图例：✅ = 已确认正常；❌ = 已知缺口（详见 §4 已知差距）；P1/P2 表示本轮发现并修复的缺陷。

## 3. 本轮发现并修复的缺陷

### 3.1 P1：`sl_tp_matrix` / `exit_compare` 在 `max_hold_days` 超过实际有数据的列数时 500

**复现**

```http
GET /quantia/api/verify/sl_tp_matrix
    ?strategy=cn_stock_strategy_enter
    &start_date=2026-03-01&end_date=2026-05-14
    &max_hold_days=99999
→ 500 {"error": "服务器内部错误"}
```

**根因**

- `max_hold` 被 clamp 到 `RATE_FIELDS_COUNT=100`；`SELECT rate_1..rate_100` 时，
  对于离 `end_date` 不到 100 个交易日的信号，尾部 `rate_31..rate_100` 全为
  NULL；
- pandas 把这些全 NULL 列推断为 **object dtype**，`DataFrame.values` 得到
  object ndarray；
- `np.isfinite(mat)` 在 object dtype 上抛
  `TypeError: ufunc 'isfinite' not supported for the input types ...`，
  被外层 `except Exception` 捕获，仅向客户端返回 `500 {"error":"服务器内部错误"}`，
  细节只在 `quantia/log/stock_error.log` 留下 traceback。

**修复**

- `quantia/web/verifyOptimizeHandler.py`：
  - `StopLossTakeProfitMatrixHandler._handle`（line 1813）把 `rates_matrix`
    构造改为 `np.asarray(rate_df.values, dtype=np.float64)`；
  - `ExitCompareHandler._handle`（line 2370）同上；
  - `_simulate_sl_tp` 内部 `mat = np.array(..., dtype=np.float64, copy=True)`
    作为兜底，避免任何上游再次传入 object dtype 时复发。
- 行为变化：尾部 NULL → NaN，原有的 `np.cumprod(np.isfinite(mat))` 自然把这些
  位置标为"无效"，输出 `max_hold_days=100`、`matrix` 长度不变，与
  `max_hold_days=20` 比较的数值保持一致（4322 条信号、win_rate=40.04% 等）。
- 黑盒验证：

  ```
  [200] sl_tp_matrix max_hold_days=99999  → total_signals=4322, matrix=非空
  [200] sl_tp_matrix max_hold_days=20     → total_signals=4322, matrix=非空
  [200] exit_compare trailing_days=5,10,99999 → 200, exit_strategies=非空
  ```

### 3.2 P2：`market_regime` 基准数据缺失返回 400，与其它端点 200+message 不一致

**复现**

```http
GET /quantia/api/verify/market_regime
    ?strategy=cn_stock_strategy_enter
    &start_date=2030-01-01&end_date=2030-02-01
→ 400 {"error": "无法加载基准 000300 数据"}
```

**问题**

- 该分支处理的是 **正常的"该区间无基准数据"**（如未来日期 / 极冷门指数），并
  非配置错误；
- 其它所有 verify-optimize 端点统一采用 `200 + {message:"该时间范围内无策略信号"}`，
  前端会把 400 当作"参数错误 / 鉴权失败"红色提示，造成误导。

**修复**

- `MarketRegimeHandler._handle`：基准为空时改为 `200` + `regimes:[]` +
  `message:"基准 {benchmark} 在该时间范围内无数据"`，并保留 `logging.info` 便于排
  查缓存层问题（不再静默，但级别从 ERROR 降到 INFO）。
- 黑盒验证：

  ```
  [200] market_regime start_date=2030-01-01 → regimes:[], message:"基准 000300 在该时间范围内无数据"
  ```

## 4. 已知差距（不在本次修复内）

### 4.1 自定义策略在 6 个 verify-optimize 端点的 API 层未覆盖

`holding_period / signal_quality / market_regime / signal_decay / cost_sensitivity /
exit_compare / return_series` 七个 handler 的 `_resolve_strategy_meta` 白名单不包含
`custom_*`，调用时返回 `400 未知 strategy`。

- **用户实际影响**：`optimize.vue` 在 `isCustomStrategy=true` 时只调用
  `custom_compare` 与 `sl_tp_matrix`，**前端不会触发其它端点**，因此当前 UI 无
  破口；
- **AGENTS.md 一致性**：违反"自定义策略与 jq 策略黑盒一致"原则，留待后续在
  `_resolve_strategy_meta` 与 `_load_backtest_data` 中走 K 线补算路径统一处理。

### 4.2 `signal_quality` 必须使用完整 indicator key

接受 `rsi_6 / rsi_12 / macd_dif / macd_dea / kdj_k / boll_upper / ma5 / ma10 ...`，
不接受裸 `rsi`。已通过 400 错误体显式列出可选项，**不是静默吞错**。

## 5. 安全 & 静默吞错复核

| 项 | 结果 |
| --- | --- |
| SQL 注入（`fund_filter=pe_lt_30 OR 1=1`） | 被 `_FUND_ALLOWED_COLS` / `_FUND_ALLOWED_OPS` 白名单拦截，warnings 显式上报 |
| 资金流 `flow_filter` 同上 | 拦截 + warning |
| 全 K 线缓存命中 0 | 200 + warnings: `["技术信号维度命中 0 条，已剔除", "所有启用维度命中为 0，无法融合"]` |
| 自定义策略未找到 | 200 + `message:"自定义策略不存在或已归档"`（非 500） |
| 全部维度 disabled | 400 + `error:"至少需要启用一个维度"` |
| `holding_days<=0` / 非法日期 | 400 + 明确文本 |
| `except: pass` / `except: ...` 静默 | 全仓 grep 未在 `verify*` / `factorLabHandler.py` / `_load_backtest_data` 命中关键路径 |
| `logging.error(exc_info=False)` 隐藏 traceback | 未命中 |
| `_write_error` 5xx 路径 | 全部带 `logging.error(..., exc_info=True)`，错误日志可在 `quantia/log/stock_error.log` 复现 |

## 6. 改动文件清单

- `quantia/web/verifyOptimizeHandler.py`
  - `StopLossTakeProfitMatrixHandler._handle`：`rates_matrix` 强制 float64
  - `ExitCompareHandler._handle`：同上
  - `StopLossTakeProfitMatrixHandler._simulate_sl_tp`：内部兜底 float64
  - `MarketRegimeHandler._handle`：基准为空 → 200 + message
- `document/verify_center_audit_2026Q2.md`（本文件）

## 7. 复测脚本（保留供后续回归）

最终用于验收的最小回归命令（PowerShell）：

```powershell
function P($p,$q){ $r=Invoke-WebRequest -Uri ("http://localhost:9988/quantia/api/verify/{0}?{1}" -f $p,$q) -TimeoutSec 90 -SkipHttpErrorCheck; "[$($r.StatusCode)] $p" }
P 'sl_tp_matrix'  'strategy=cn_stock_strategy_enter&start_date=2026-03-01&end_date=2026-05-14&max_hold_days=99999'
P 'sl_tp_matrix'  'strategy=cn_stock_strategy_enter&start_date=2026-03-01&end_date=2026-05-14&max_hold_days=20'
P 'exit_compare' 'strategy=cn_stock_strategy_enter&start_date=2026-03-01&end_date=2026-05-14&trailing_days=5,10,99999'
P 'market_regime' 'strategy=cn_stock_strategy_enter&start_date=2030-01-01&end_date=2030-02-01'
```

预期全部 `[200]`。
