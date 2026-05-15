"""自定义指标 DDL + 内置预设 seed 集成测试。"""
import json
import pytest

from quantia.lib import database as mdb
from quantia.web.customIndicatorHandler import (
    _ensure_custom_indicator_table, _seed_builtin_indicators, bootstrap,
)


def test_table_creation_idempotent():
    _ensure_custom_indicator_table()
    assert mdb.checkTableIsExist("cn_stock_custom_indicator")
    # 二次调用不应 raise
    _ensure_custom_indicator_table()


def test_seed_inserts_three_builtins():
    bootstrap()
    rows = mdb.executeSqlFetch(
        "SELECT indicator_id, name, kind, is_builtin FROM cn_stock_custom_indicator "
        "WHERE is_builtin = 1 ORDER BY id"
    )
    ids = [r[0] for r in rows]
    assert "steady_oversold_rebound" in ids
    assert "dual_momentum_growth" in ids
    assert "score_alert_watchlist" in ids


def test_seed_idempotent_via_on_duplicate_key():
    bootstrap()
    n_before = mdb.executeSqlFetch(
        "SELECT COUNT(*) FROM cn_stock_custom_indicator WHERE is_builtin=1"
    )[0][0]
    bootstrap()
    n_after = mdb.executeSqlFetch(
        "SELECT COUNT(*) FROM cn_stock_custom_indicator WHERE is_builtin=1"
    )[0][0]
    assert n_after == n_before


def test_seeded_weights_and_risk_profile_are_json():
    bootstrap()
    row = mdb.executeSqlFetch(
        "SELECT weights, risk_profile FROM cn_stock_custom_indicator "
        "WHERE indicator_id = %s", ("score_alert_watchlist",)
    )[0]
    weights = json.loads(row[0])
    risk = json.loads(row[1])
    assert "n_ma_uptrend" in weights
    assert risk["stop"] < 0
    assert risk["max_hold"] > 0


def test_steady_preset_has_hard_rules():
    bootstrap()
    row = mdb.executeSqlFetch(
        "SELECT hard_rules FROM cn_stock_custom_indicator "
        "WHERE indicator_id = %s", ("steady_oversold_rebound",)
    )[0]
    assert row[0] is not None
    assert "rsi14" in row[0]
    assert "boll_lower" in row[0]
