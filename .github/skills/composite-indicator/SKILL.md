---
name: composite-indicator
description: "Use when adding, editing, debugging, or reviewing custom composite indicators (Phase 9 自定义综合指标) under quantia/core/composite/, including normalizers (n_lin/n_wr/n_rank/n_supertrend/n_pctb/n_cci), hard-rule AST sandbox expressions, risk simulator stop/target/max-hold + fundamentals exit, dynamic universe filters, and the cn_stock_custom_indicator handler. Use when writing builtins or wiring the customIndicatorHandler / refresh_composite_universe cron."
---

# 自定义综合指标（Phase 9）开发与维护

## 模块布局
- [quantia/core/composite/normalizers.py](../../../quantia/core/composite/normalizers.py) — 归一化算子 `n_lin / n_wr / n_rank / n_supertrend / n_pctb / n_cci`
- [quantia/core/composite/indicators_enrich.py](../../../quantia/core/composite/indicators_enrich.py) — 原始指标 + `enrich(df)` 注入派生列
- [quantia/core/composite/composite_engine.py](../../../quantia/core/composite/composite_engine.py) — `Composite` dataclass，校验权重 / 表达式
- [quantia/core/composite/hard_rules_engine.py](../../../quantia/core/composite/hard_rules_engine.py) — AST 沙箱（`parse_hard_rules` / `eval_hard_rules`）
- [quantia/core/composite/risk_simulator.py](../../../quantia/core/composite/risk_simulator.py) — `simulate(stop / target / max_hold)` + 基本面退出
- [quantia/core/composite/dynamic_universe.py](../../../quantia/core/composite/dynamic_universe.py) — `fetch_universe` + 缓存 + `fundamentals_signal`
- [quantia/core/composite/builtins.py](../../../quantia/core/composite/builtins.py) — 3 个内置预设
- [quantia/web/customIndicatorHandler.py](../../../quantia/web/customIndicatorHandler.py) — DDL `cn_stock_custom_indicator` + 种子
- [cron/cron.workdayly/refresh_composite_universe](../../../cron/cron.workdayly/refresh_composite_universe) — 每日 08:30 缓存刷新

## 硬性约束（不要试图"放宽"）

### AST 沙箱黑名单
`hard_rules_engine.py` 拒绝以下：
- `__import__`、任何双下划线名称（dunder）
- `lambda`、`exec`、`eval`、`compile`
- 文件操作（`open`、`Path` 等）
- 字典对象的 `.attr` 访问（只允许 `d['key']`）

> 任何"为了支持新表达式而放宽沙箱"的改动必须先与作者确认。这层防护是给用户输入用的，不是开发者便利层。

### 动态宇宙缓存与过滤
- 缓存文件：`quantia/cache/composite/_universe_today.pkl`，TTL **24 小时**。
- 过滤阈值（与对照实验 V3 一致，**不要随手改**）：
  - `mcap >= 30 亿`
  - `0 <= pe9 <= 80`
  - `roe_weight >= 7`
  - `debt <= 80`
  - `profit_yoy >= -20`

### 基本面卖出偏置（字段化，已与作者确认）
位于 `risk_profile.fundamentals_sell`：
- `score_quantile_lt = 0.30`
- `roe_yoy_drop_pct_lt = -50.0`

## 添加新归一化算子的步骤
1. 在 `normalizers.py` 实现 `n_xxx(series, **kwargs) -> pd.Series`，输出范围 `[0, 1]` 或 `[-1, 1]`，并在 docstring 写清楚映射含义。
2. 在 `composite_engine.py` 的允许列表中注册，否则 `Composite` 校验会拒绝。
3. 在 [tests/test_composite_normalizers.py](../../../tests/test_composite_normalizers.py) 加用例（边界：全 NaN、单点、常数序列、足够长序列）。
4. 跑 `pytest tests/test_composite_normalizers.py -q` 通过后，再跑 `_verify_pr1_smoke.py`。

## 添加新内置预设的步骤
1. 在 `builtins.py` 写一个 `BUILTIN_XXX = Composite(...)`，权重和必须为 1.0。
2. 硬规则用沙箱可解析的表达式（参考已有预设）。
3. 在 `customIndicatorHandler.py` 的种子列表里追加，重启 Web 后会自动落库（`template_id` 唯一）。
4. 在 [tests/test_composite_engine.py](../../../tests/test_composite_engine.py) / [tests/test_custom_indicator_handler.py](../../../tests/test_custom_indicator_handler.py) 补回归用例。

## 修复缓存 / 调试
- 缓存陈旧或基本面字段缺列：删除 `quantia/cache/composite/_universe_today.pkl` 后重新跑 `cron/cron.workdayly/refresh_composite_universe`。
- 沙箱报错信息不直观：把表达式用 `parse_hard_rules` 单独跑一次，看 AST 在哪一节点被拒绝。
- 风险模拟与回测结果不一致：先用 `_compare_composite_winrate_v5_master_fix.py` 跑同一个 composite，对照 winrate / drawdown / 持仓时长再定位。

## 验证脚本
- `_verify_pr1_smoke.py` — 后端核心 smoke，PR 合入前必跑。
- `pytest tests/test_composite_*.py tests/test_hard_rules_engine.py tests/test_risk_simulator.py tests/test_dynamic_universe.py tests/test_custom_indicator_handler.py -q` — 全模块回归。

## 文档参考
- [document/phase9_custom_indicator_dev_plan.md](../../../document/phase9_custom_indicator_dev_plan.md)
- [document/custom_indicator_winrate_analysis.md](../../../document/custom_indicator_winrate_analysis.md)
- [document/custom_indicator_winrate_analysis_v3_fundamentals_sl_tp.md](../../../document/custom_indicator_winrate_analysis_v3_fundamentals_sl_tp.md)
