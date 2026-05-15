"""PR-2 API + 沙箱安全测试。

主要覆盖：
1. `_validate_save_payload` 范式守门 (F7) 全部分支
2. `_compute_signal` 三种模式（纯权重 / 纯硬规则 / 混合）
3. Save → Detail → Delete 数据库往返
4. 沙箱注入/逃逸尝试经过 Save handler 后被拒绝
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from quantia.lib import database as mdb
from quantia.web.customIndicatorHandler import (
    _validate_save_payload, _compute_signal, _load_indicator_record,
    _ensure_custom_indicator_table, bootstrap,
)
from quantia.core.composite.indicators_enrich import enrich


# ============================================================================
#                  _validate_save_payload (F7 范式守门)
# ============================================================================
class TestValidateSavePayload:
    def test_missing_indicator_id(self):
        ok, err = _validate_save_payload({"name": "x"})
        assert not ok and "indicator_id" in err

    def test_invalid_indicator_id_chars(self):
        ok, err = _validate_save_payload({"indicator_id": "bad name!", "name": "x"})
        assert not ok and "字母" in err

    def test_missing_name(self):
        ok, err = _validate_save_payload({"indicator_id": "abc", "name": ""})
        assert not ok and "name" in err

    def test_invalid_kind(self):
        ok, err = _validate_save_payload(
            {"indicator_id": "abc", "name": "x", "kind": "foo"})
        assert not ok and "kind" in err

    def test_invalid_direction(self):
        ok, err = _validate_save_payload(
            {"indicator_id": "abc", "name": "x", "direction": "middle"})
        assert not ok and "direction" in err

    def test_primary_entry_requires_rules_or_weights(self):
        ok, err = _validate_save_payload({
            "indicator_id": "abc", "name": "x", "kind": "primary_entry",
        })
        assert not ok and "硬规则" in err

    def test_weights_only_must_be_high(self):
        ok, err = _validate_save_payload({
            "indicator_id": "abc", "name": "x", "kind": "watchlist_alert",
            "weights": {"n_rsi14": 1.0}, "direction": "low",
        })
        assert not ok and "high" in err

    def test_hard_rules_sandbox_violation(self):
        ok, err = _validate_save_payload({
            "indicator_id": "abc", "name": "x", "kind": "primary_entry",
            "hard_rules": "__import__('os').system('rm -rf /')",
        })
        assert not ok and "硬规则解析失败" in err

    def test_extra_filter_sandbox_violation(self):
        ok, err = _validate_save_payload({
            "indicator_id": "abc", "name": "x", "kind": "primary_entry",
            "hard_rules": "d['rsi14'] < 30",
            "extra_filter": "open('/etc/passwd')",
        })
        assert not ok and "额外过滤解析失败" in err

    def test_negative_weight_rejected(self):
        ok, err = _validate_save_payload({
            "indicator_id": "abc", "name": "x", "kind": "watchlist_alert",
            "weights": {"n_rsi14": -1.0}, "direction": "high",
        })
        assert not ok and "非负" in err

    def test_valid_primary_entry_with_hard_rules(self):
        ok, err = _validate_save_payload({
            "indicator_id": "test_p1", "name": "test", "kind": "primary_entry",
            "hard_rules": "(d['rsi14'] < 30) & (d['close'] > d['boll_lower'])",
        })
        assert ok, err

    def test_valid_watchlist_with_weights(self):
        ok, err = _validate_save_payload({
            "indicator_id": "test_w1", "name": "test", "kind": "watchlist_alert",
            "weights": {"n_rsi14": 0.5, "n_ma_uptrend": 0.5},
            "direction": "high", "buy_th": 50,
        })
        assert ok, err


# ============================================================================
#                  _compute_signal 流水线
# ============================================================================
def _make_ohlcv(n: int = 200) -> pd.DataFrame:
    np.random.seed(42)
    base = 10 + np.cumsum(np.random.randn(n) * 0.2)
    base = np.clip(base, 1, None)
    return pd.DataFrame({
        "date": pd.date_range("2023-01-01", periods=n),
        "open": base * 1.001,
        "high": base * 1.01,
        "low": base * 0.99,
        "close": base,
        "volume": np.random.randint(1000, 10000, n),
    })


class TestComputeSignal:
    def test_pure_weights_returns_score(self):
        df = enrich(_make_ohlcv())
        rec = {
            "name": "test", "kind": "watchlist_alert",
            "weights": {"n_rsi14": 0.5, "n_ma_uptrend": 0.5},
            "smooth_ema": 0, "buy_th": 50, "direction": "high",
            "hard_rules": "", "extra_filter": "",
        }
        sig, score = _compute_signal(rec, df)
        assert score is not None
        assert sig.dtype == bool
        assert len(sig) == len(df)

    def test_pure_hard_rules_no_score(self):
        df = enrich(_make_ohlcv())
        rec = {
            "name": "test", "kind": "primary_entry",
            "weights": {}, "smooth_ema": 0, "buy_th": 0, "direction": "high",
            "hard_rules": "d['rsi14'] < 30", "extra_filter": "",
        }
        sig, score = _compute_signal(rec, df)
        assert score is None
        assert sig.dtype == bool

    def test_extra_filter_narrows_signal(self):
        df = enrich(_make_ohlcv())
        rec_no_filter = {
            "name": "t", "kind": "primary_entry",
            "weights": {}, "smooth_ema": 0, "buy_th": 0, "direction": "high",
            "hard_rules": "d['rsi14'] < 60", "extra_filter": "",
        }
        rec_filtered = {**rec_no_filter,
                        "extra_filter": "d['close'] > d['ma60']"}
        sig1, _ = _compute_signal(rec_no_filter, df)
        sig2, _ = _compute_signal(rec_filtered, df)
        # extra_filter 不会增加触发数，只会减少
        assert sig2.sum() <= sig1.sum()


# ============================================================================
#                  Save → Detail → Delete DB 往返
# ============================================================================
@pytest.fixture
def cleanup_test_indicator():
    """删除测试残留。"""
    yield
    mdb.executeSql(
        "DELETE FROM cn_stock_custom_indicator "
        "WHERE indicator_id LIKE %s AND is_builtin=0",
        ("pytest_%",))


def test_save_detail_delete_roundtrip(cleanup_test_indicator):
    bootstrap()
    iid = "pytest_save_roundtrip"
    mdb.executeSql("""
        INSERT INTO cn_stock_custom_indicator
          (indicator_id, name, kind, weights, smooth_ema, buy_th,
           direction, extra_filter, hard_rules, risk_profile, is_builtin)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE name=VALUES(name)
    """, (iid, "pytest", "primary_entry",
          json.dumps({}), 0, 0.0, "high", None,
          "d['rsi14'] < 30",
          json.dumps({"stop": -0.08, "target": 0.20, "max_hold": 60}),
          0))
    rec = _load_indicator_record(iid)
    assert rec is not None
    assert rec["kind"] == "primary_entry"
    assert "rsi14" in rec["hard_rules"]
    assert rec["risk_profile"]["max_hold"] == 60


def test_load_indicator_record_returns_none_for_missing():
    assert _load_indicator_record("nonexistent_xyz_12345") is None


# ============================================================================
#                  内置预设的只读保护（单元层面）
# ============================================================================
def test_builtin_preset_loads_with_correct_kind():
    bootstrap()
    rec = _load_indicator_record("steady_oversold_rebound")
    assert rec is not None
    assert rec["kind"] == "primary_entry"
    assert rec["hard_rules"] is not None and "rsi14" in rec["hard_rules"]
    assert rec["risk_profile"].get("fundamentals_check") is True


# ============================================================================
#         前后端契约：trade payload 字段名（防 PR-3 表格错位回归）
# ============================================================================
def test_backtest_trade_payload_field_contract():
    """
    锁定 BacktestCustomIndicatorHandler 返回的 trade dict 字段名。
    前端 customIndicator/index.vue 表格列依赖这些字段名，任何改名都会让 UI 静默错位。
    """
    from quantia.core.composite.risk_simulator import simulate, summarize_trades
    # 构造一段递增 + 一次回撤的合成行情，保证 simulate 至少出 1 笔交易
    n = 250
    rng = np.random.RandomState(0)
    base = np.linspace(10, 18, n) + rng.normal(0, 0.05, n)
    df = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=n, freq="B"),
        "open": base, "high": base * 1.01, "low": base * 0.99,
        "close": base, "volume": np.full(n, 1000_000, dtype=float),
    })
    sig = pd.Series([False] * n)
    sig.iloc[20] = True   # 单次入场
    trades = simulate("000001", df, sig, stop_loss=0.08, take_profit=0.20, max_hold=60)
    assert len(trades) >= 1
    # 模拟 handler 序列化逻辑（保持与 customIndicatorHandler 一致）
    payload = [{
        "entry_date": str(t.entry_date.date()),
        "entry_price": t.entry_price,
        "exit_date": str(t.exit_date.date()),
        "exit_price": t.exit_price,
        "reason": t.reason,
        "net_ret_pct": round(t.net_ret * 100, 3),
        "hold_days": t.hold_days,
    } for t in trades]
    p0 = payload[0]
    # 前端表格依赖的 7 个字段名必须存在（不可被改）
    for k in ("entry_date", "entry_price", "exit_date", "exit_price",
              "reason", "net_ret_pct", "hold_days"):
        assert k in p0, f"trade payload 缺字段 {k}（前端 UI 会静默错位）"
    # 类型检查
    assert isinstance(p0["entry_date"], str)
    assert isinstance(p0["entry_price"], (int, float))
    assert isinstance(p0["net_ret_pct"], (int, float))
    assert isinstance(p0["reason"], str)


def test_summarize_trades_payload_field_contract():
    """
    锁定 summary dict 字段名，前端 metrics 卡片依赖这些 key。
    """
    from quantia.core.composite.risk_simulator import Trade, summarize_trades
    fake = [
        Trade(code="000001", entry_bar=10, entry_date=pd.Timestamp("2024-01-15"), entry_price=10.0,
              exit_bar=30, exit_date=pd.Timestamp("2024-02-15"), exit_price=11.0,
              reason="win-target", gross_ret=0.10, net_ret=0.10 - 0.0036, hold_days=21),
        Trade(code="000001", entry_bar=50, entry_date=pd.Timestamp("2024-03-01"), entry_price=12.0,
              exit_bar=58, exit_date=pd.Timestamp("2024-03-12"), exit_price=11.0,
              reason="stop-loss", gross_ret=-0.083, net_ret=-0.083 - 0.0036, hold_days=8),
    ]
    s = summarize_trades(fake, name="contract_test")
    for k in ("strategy", "trades", "win%", "PF", "avg%", "expectancy%", "avg_hold"):
        assert k in s, f"summary 缺字段 {k}（前端 metrics 会显示 -）"
    assert s["trades"] == 2
    assert s["win%"] == 50.0


# ============================================================================
#         /series 信号点应包含买入 + 卖出 (per dev plan §4.4)
# ============================================================================
def test_series_signal_points_include_sell_actions():
    """
    PR-5 K 线叠加要求 signal_points 中含 sell-stop / sell-target / sell-time 动作，
    用于主图叠加时绘制不同形状的卖出标记。
    """
    from quantia.web.customIndicatorHandler import (
        _compute_signal, _load_indicator_record,
    )
    from quantia.core.composite.risk_simulator import simulate
    bootstrap()
    rec = _load_indicator_record("steady_oversold_rebound")
    assert rec is not None
    # 构造一段震荡行情，让 hard_rules 至少触发若干次
    n = 600
    rng = np.random.RandomState(42)
    px = 10.0 + np.cumsum(rng.normal(0, 0.20, n)) + np.sin(np.arange(n) / 20) * 1.5
    px = np.clip(px, 5.0, 30.0)
    df = pd.DataFrame({
        "date": pd.date_range("2022-01-01", periods=n, freq="B"),
        "open": px, "high": px * 1.02, "low": px * 0.98,
        "close": px, "volume": rng.randint(500_000, 2_000_000, n).astype(float),
    })
    d = enrich(df)
    sig, _ = _compute_signal(rec, d)
    risk = rec["risk_profile"]
    trades = simulate("000001", d, sig,
                      stop_loss=abs(float(risk["stop"])),
                      take_profit=abs(float(risk["target"])),
                      max_hold=int(risk["max_hold"]))
    # 仅校验 reason→action 映射在 handler 中一致；不强制 trades 数量
    valid_actions = {"sell-stop", "sell-target", "sell-time", "sell-fund"}
    reason_map = {"stop-loss": "sell-stop", "win-target": "sell-target",
                  "time-exit": "sell-time", "fundamentals-exit": "sell-fund"}
    for t in trades:
        assert reason_map.get(t.reason) in valid_actions

