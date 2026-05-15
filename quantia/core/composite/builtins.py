"""
三条内置预设的 Python 函数定义 — 与 DB seed 同源（避免维护两份）。

预设：
- 稳健抄底版    `steady_oversold_rebound`  (S12 五条硬规则, primary_entry)
- 进攻增长版    `dual_momentum_growth`     (S12 ∪ T3, primary_entry)
- 今日关注榜    `score_alert_watchlist`    (M1 七因子加权评分, watchlist_alert)

实证依据：document/medium_long_term_holding_analysis.md (V4-V6)
"""
from __future__ import annotations

import pandas as pd

from quantia.core.composite.composite_engine import Composite


# ============================ S12 (稳健抄底版) ================================
def signal_s12(d: pd.DataFrame) -> pd.Series:
    """
    五条硬规则 AND 链：
      RSI14 < 30
      AND 最近 5 日 low 触及过 BOLL 下轨 *1.01
      AND 收盘 > BOLL 下轨（已收回）
      AND 当日阳线 close > open
      AND 成交量 > 5 日均量 *1.2（放量）
    """
    vol_ma5 = d["volume"].shift(1).rolling(5).mean()
    touched = d["low"].rolling(5).min() <= d["boll_lower"] * 1.01
    return (
        (d["rsi14"] < 30)
        & touched
        & (d["close"] > d["boll_lower"])
        & (d["close"] > d["open"])
        & (d["volume"] > vol_ma5 * 1.2)
    ).fillna(False)


# ============================ T3 (动量共振) ===================================
T3 = Composite(
    name="T3 动量共振-平衡",
    weights={
        "n_rsi14": 0.20, "n_kdj_k": 0.15, "n_wr14": 0.15,
        "n_trend_st": 0.30, "n_vol_ratio_rank": 0.20,
    },
    smooth_ema=3, buy_th=25, direction="low",
)


# ============================ 进攻增长版 (S12 ∪ T3) ============================
def signal_s12_or_t3(d: pd.DataFrame) -> pd.Series:
    return signal_s12(d) | T3.signal(d)


# ============================ M1 综合评分 (今日关注榜) =========================
M1_WEIGHTS = {
    "n_ma_uptrend":         0.15,
    "n_macd_hist_rank":     0.15,
    "n_boll_pct_b":         0.15,
    "n_atr_pct_inv_rank":   0.10,
    "n_obv_slope_rank":     0.20,
    "n_vol_ratio_rank":     0.15,
    "n_rsi14":              0.10,
}

M1_WATCHLIST = Composite(
    name="M1 综合评分预警",
    weights=M1_WEIGHTS,
    smooth_ema=5, buy_th=50, direction="high",
)


# ============================ 内置预设元数据（DB seed 用）======================
BUILTIN_PRESETS = [
    {
        "indicator_id": "steady_oversold_rebound",
        "name": "稳健抄底版",
        "kind": "primary_entry",
        "description": "S12 五条硬规则：RSI14<30 + 触及BOLL下轨 + 收回 + 阳线 + 放量。"
                       "V4-V6 实证 PF 1.81~3.63，120d 持仓 Sharpe 1.22。",
        "weights": {},
        "smooth_ema": 0, "buy_th": 0, "direction": "high",
        "extra_filter": None,
        "hard_rules": (
            "(d['rsi14'] < 30) "
            "& (d['low'].rolling(5).min() <= d['boll_lower'] * 1.01) "
            "& (d['close'] > d['boll_lower']) "
            "& (d['close'] > d['open']) "
            "& (d['volume'] > d['volume'].shift(1).rolling(5).mean() * 1.2)"
        ),
        "risk_profile": {
            "stop": -0.12, "target": 0.40, "max_hold": 120,
            "fundamentals_check": True,
            "fundamentals_sell": {"score_quantile_lt": 0.30, "roe_yoy_drop_pct_lt": -50.0},
        },
        "is_builtin": 1,
    },
    {
        "indicator_id": "dual_momentum_growth",
        "name": "进攻增长版",
        "kind": "primary_entry",
        "description": "S12 ∪ T3 双信号（抄底 OR 动量共振）。V6 投资组合 CAGR 26.83%、总收益 +316%。",
        "weights": {},
        "smooth_ema": 0, "buy_th": 0, "direction": "high",
        "extra_filter": None,
        # 用 OR 实现双信号；右半部分是 T3 评分穿过 25 的简化重写
        "hard_rules": (
            "((d['rsi14'] < 30) "
            " & (d['low'].rolling(5).min() <= d['boll_lower'] * 1.01) "
            " & (d['close'] > d['boll_lower']) "
            " & (d['close'] > d['open']) "
            " & (d['volume'] > d['volume'].shift(1).rolling(5).mean() * 1.2)) "
            "| ("
            "  (d['n_trend_st'] > 50) "
            "  & (d['n_vol_ratio_rank'] > 60) "
            "  & (d['n_rsi14'] < 50)"
            ")"
        ),
        "risk_profile": {
            "stop": -0.12, "target": 0.40, "max_hold": 120,
            "fundamentals_check": True,
            "fundamentals_sell": {"score_quantile_lt": 0.30, "roe_yoy_drop_pct_lt": -50.0},
        },
        "is_builtin": 1,
    },
    {
        "indicator_id": "score_alert_watchlist",
        "name": "今日关注榜",
        "kind": "watchlist_alert",
        "description": "M1 七因子加权评分（趋势+波动+资金+动量四类正交）。"
                       "评分穿越 50 触发关注。⚠️ 仅供参考，禁止直接驱动交易。",
        "weights": M1_WEIGHTS,
        "smooth_ema": 5, "buy_th": 50.0, "direction": "high",
        "extra_filter": None,
        "hard_rules": None,
        "risk_profile": {
            "stop": -0.08, "target": 0.20, "max_hold": 60,
            "fundamentals_check": False,
        },
        "is_builtin": 1,
    },
]


__all__ = [
    "signal_s12", "signal_s12_or_t3", "T3", "M1_WATCHLIST", "M1_WEIGHTS",
    "BUILTIN_PRESETS",
]
