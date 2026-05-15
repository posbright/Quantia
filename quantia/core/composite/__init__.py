"""
Phase 9 — 自定义复合指标核心包。

包含从 _compare_composite_winrate_v2/v3/v5/v6 抽取的生产级模块：
    normalizers          — 归一化函数 (n_lin / n_rank / n_wr / ...)
    indicators_enrich    — enrich(df) → DataFrame with n_* 列
    composite_engine     — Composite 数据类（加权评分 + 触发）
    hard_rules_engine    — AST 沙箱解析 + 求值用户硬规则表达式
    risk_simulator       — 单股 simulate(stop/target/max_hold) + 基本面提前止盈
    dynamic_universe     — 实时基本面预筛股票池 + 缓存
    builtins             — 三条内置预设的 Python 函数定义（与 DB seed 同源）

实证依据：document/medium_long_term_holding_analysis.md (V4-V6)
"""
from __future__ import annotations

__all__ = [
    "normalizers",
    "indicators_enrich",
    "composite_engine",
    "hard_rules_engine",
    "risk_simulator",
    "dynamic_universe",
    "builtins",
]
