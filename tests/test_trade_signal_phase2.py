# -*- coding: utf-8 -*-
"""Phase 2 单元/集成测试 — 不依赖 MySQL，全部使用 monkeypatch + mock 替换数据库。"""
from __future__ import annotations

import datetime
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from quantia.core.backtest import trade_decision as td
from quantia.core.backtest import trade_signal_store as tss


# ---------- normalize / reason ----------

def test_resolve_reason_strategy_wins_when_provided():
    out = td.resolve_reason("buy", "BOLL 下轨反弹 + MA5 上穿 MA20")
    assert out["reason_source"] == td.REASON_SOURCE_STRATEGY
    assert "BOLL" in out["reason"]


def test_resolve_reason_falls_back_with_clear_marker():
    out = td.resolve_reason("buy", None)
    assert out["reason_source"] == td.REASON_SOURCE_GENERATED
    assert "由系统" in out["reason"] and "买入" in out["reason"]
    out_sell = td.resolve_reason("sell", "")
    assert out_sell["reason_source"] == td.REASON_SOURCE_GENERATED
    assert "卖出" in out_sell["reason"]


def test_normalize_decision_payload_filters_and_orders():
    payload = {
        "rules": [
            {"name": "BOLL 下轨", "threshold": "close<=lower*1.02",
             "actual": {"close": 3.74, "lower": 3.67}, "passed": True, "weight": 1.0},
            {"name": "MA5 > MA20", "actual_value": {"ma5": 3.71, "ma20": 3.70}, "passed": "yes"},
            "not_a_dict_should_be_dropped",
        ],
    }
    norm = td.normalize_decision_payload(payload)
    assert len(norm["rules"]) == 2
    assert norm["rules"][0]["sort_order"] == 0 and norm["rules"][1]["sort_order"] == 1
    assert norm["rules"][0]["passed"] == 1
    assert norm["rules"][1]["passed"] == 1
    assert norm["rules"][0]["threshold_expr"] == "close<=lower*1.02"


def test_normalize_decision_payload_handles_none():
    assert td.normalize_decision_payload(None) == {"rules": [], "indicators": {}, "selection": []}


def test_compute_signal_hash_deterministic_and_distinct():
    base = dict(source_type="paper", source_id=4, run_id="r1", code="600016",
                direction="buy", signal_date="2026-04-30", requested_amount=200, requested_value=None)
    h1 = td.compute_signal_hash(**base)
    h2 = td.compute_signal_hash(**base)
    assert h1 == h2 and len(h1) == 64
    h_diff = td.compute_signal_hash(**{**base, "direction": "sell"})
    assert h_diff != h1


# ---------- persist_signal_with_relations ----------

class _FakeCursor:
    def __init__(self, store):
        self.store = store
        self._last_select_result = None

    def execute(self, sql, params=()):
        self.store["calls"].append((sql.strip().split()[0].upper(), sql, params))
        sql_upper = sql.upper()
        if sql_upper.startswith("INSERT INTO `CN_STOCK_TRADE_SIGNAL`"):
            self.store["signal_inserts"].append(params)
        elif sql_upper.startswith("SELECT ID FROM `CN_STOCK_TRADE_SIGNAL`"):
            self._last_select_result = (12345,)
        elif sql_upper.startswith("INSERT INTO `CN_STOCK_TRADE_DECISION`"):
            self.store["decision_inserts"].append(params)
        elif sql_upper.startswith("DELETE FROM `CN_STOCK_TRADE_DECISION`"):
            self.store["decision_deletes"].append(params)
        elif sql_upper.startswith("INSERT INTO `CN_STOCK_TRADE_INDICATOR_SNAPSHOT`"):
            self.store["indicator_inserts"].append(params)
        elif sql_upper.startswith("INSERT INTO `CN_STOCK_TRADE_SELECTION_SNAPSHOT`"):
            self.store["selection_inserts"].append(params)
        elif sql_upper.startswith("DELETE FROM `CN_STOCK_TRADE_SELECTION_SNAPSHOT`"):
            self.store["selection_deletes"].append(params)
        elif sql_upper.startswith("UPDATE `CN_STOCK_TRADE_SIGNAL`"):
            self.store["signal_updates"].append(params)

    def fetchone(self):
        return self._last_select_result

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeConn:
    def __init__(self, store):
        self.store = store

    def cursor(self):
        return _FakeCursor(self.store)

    def commit(self):
        self.store["committed"] = True

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def fake_db(monkeypatch):
    store: Dict[str, Any] = {
        "calls": [], "signal_inserts": [], "decision_inserts": [],
        "indicator_inserts": [], "selection_inserts": [],
        "decision_deletes": [], "selection_deletes": [],
        "signal_updates": [], "committed": False, "ddl_executed": [],
    }

    fake_mdb = SimpleNamespace(
        executeSql=lambda sql, params=(): store["ddl_executed"].append(sql),
        get_connection=lambda: _FakeConn(store),
        executeSqlFetch=lambda sql, params=(): None,
    )
    monkeypatch.setattr(tss, "_get_db", lambda: fake_mdb)
    monkeypatch.setattr(tss, "_TABLES_ENSURED", False, raising=False)
    return store, fake_mdb


def test_persist_signal_with_relations_writes_all_tables(fake_db):
    store, _ = fake_db
    sig_id = tss.persist_signal_with_relations(
        source_type="paper", source_id=4, run_id="paper-4-x",
        strategy_id=1, strategy_name="BOLL",
        signal_date="2026-04-30", code="600016", name="民生银行",
        direction="buy", order_api="order_target_percent",
        requested_amount=None, requested_value=99484.0,
        target_percent=0.5,
        reason="BOLL 下轨反弹", reason_source="strategy",
        signal_hash="hash-001",
        decision_rules=[
            td.normalize_rule({"name": "BOLL 下轨", "threshold": "close<=lower*1.02",
                                "actual": {"close": 3.74}, "passed": True}, 0),
            td.normalize_rule({"name": "MA5>MA20", "passed": True}, 1),
        ],
        indicators={"close": 3.74, "open": 3.70, "high": 3.78, "low": 3.69,
                    "ma": {"ma5": 3.71, "ma20": 3.70},
                    "boll": {"upper": 3.95, "mid": 3.81, "lower": 3.67},
                    "my_factor": 0.42},
        selection=[{"stage": "final", "candidate_count_after": 1, "passed": True}],
    )
    assert sig_id == 12345
    assert store["committed"] is True
    assert len(store["signal_inserts"]) == 1
    # signal INSERT 参数应包含 target_percent。
    assert 0.5 in store["signal_inserts"][0]
    assert len(store["decision_inserts"]) == 2
    assert len(store["indicator_inserts"]) == 1
    # 指标表应拆分出 OHLCV 与 ma/boll JSON。
    ind_params = store["indicator_inserts"][0]
    assert 3.74 in ind_params  # close
    assert any("ma5" in str(p) for p in ind_params if p)  # ma JSON
    assert any("my_factor" in str(p) for p in ind_params if p)  # extra JSON
    assert len(store["selection_inserts"]) == 1


def test_persist_signal_swallows_db_errors(monkeypatch):
    def _raise(*a, **kw):
        raise RuntimeError("db down")
    fake_mdb = SimpleNamespace(executeSql=_raise, get_connection=_raise, executeSqlFetch=_raise)
    monkeypatch.setattr(tss, "_get_db", lambda: fake_mdb)
    monkeypatch.setattr(tss, "_TABLES_ENSURED", True, raising=False)
    sig_id = tss.persist_signal_with_relations(
        source_type="paper", source_id=4, run_id="r", strategy_id=None, strategy_name=None,
        signal_date="2026-04-30", code="600016", name="x", direction="buy",
        order_api="order", requested_amount=100, requested_value=None,
        reason="r", reason_source="strategy", signal_hash="h",
    )
    assert sig_id is None  # 失败静默


def test_link_signal_to_trade_skips_when_missing(monkeypatch):
    called = {"n": 0}

    def _exec(sql, params):
        called["n"] += 1

    monkeypatch.setattr(tss, "_get_db", lambda: SimpleNamespace(executeSql=_exec))
    assert tss.link_signal_to_trade(0, 5) is False
    assert tss.link_signal_to_trade(7, 0) is False
    assert called["n"] == 0


def test_link_signal_to_trade_writes_when_valid(monkeypatch):
    captured = {}

    def _exec(sql, params):
        captured["sql"] = sql
        captured["params"] = params

    monkeypatch.setattr(tss, "_get_db", lambda: SimpleNamespace(executeSql=_exec))
    assert tss.link_signal_to_trade(7, 99) is True
    assert "UPDATE" in captured["sql"].upper()
    assert captured["params"] == (99, 7)


def test_phase2_schema_migration_alters_legacy_signal_table(monkeypatch):
    """旧版 cn_stock_trade_signal 缺 target_amount 时应自动 ALTER。"""
    executed_sql = []

    def _fetch(sql, params):
        # 模拟 information_schema：signal 表缺 target_amount，indicator 表已是新结构（含 close）。
        if "columns" in sql.lower():
            table, col = params
            if table == tss.SIGNAL_TABLE and col == "target_amount":
                return []  # 缺列
            if table == tss.INDICATOR_SNAPSHOT_TABLE and col == "payload":
                return []  # 没有旧 payload 列 → 跳过 indicator DROP
            return [(1,)]
        return []

    def _exec(sql, params=()):
        executed_sql.append(sql)

    fake_mdb = SimpleNamespace(executeSql=_exec, executeSqlFetch=_fetch)
    monkeypatch.setattr(tss, "_get_db", lambda: fake_mdb)
    monkeypatch.setattr(tss, "_TABLES_ENSURED", False, raising=False)

    tss.ensure_trade_signal_tables()
    joined = "\n".join(executed_sql).lower()
    assert "alter table" in joined
    assert "target_amount" in joined
    assert "ai_score_id" in joined


def test_phase2_schema_migration_drops_legacy_indicator_payload(monkeypatch):
    """旧版 cn_stock_trade_indicator_snapshot 是单列 payload 时应 DROP+重建。"""
    executed_sql = []

    def _fetch(sql, params):
        table, col = params
        if table == tss.SIGNAL_TABLE and col == "target_amount":
            return [(1,)]  # 已是新 schema
        if table == tss.INDICATOR_SNAPSHOT_TABLE and col == "payload":
            return [(1,)]  # 旧 schema 存在
        if table == tss.INDICATOR_SNAPSHOT_TABLE and col == "close":
            return []  # 没有 close 列 → 触发重建
        return []

    def _exec(sql, params=()):
        executed_sql.append(sql)

    fake_mdb = SimpleNamespace(executeSql=_exec, executeSqlFetch=_fetch)
    monkeypatch.setattr(tss, "_get_db", lambda: fake_mdb)
    monkeypatch.setattr(tss, "_TABLES_ENSURED", False, raising=False)

    tss.ensure_trade_signal_tables()
    joined = "\n".join(executed_sql).lower()
    assert f"drop table `{tss.INDICATOR_SNAPSHOT_TABLE}`".lower() in joined
    # 之后必须重建，包含结构化列。
    assert "`close` decimal" in joined
    assert "`open` decimal" in joined


# ---------- notification template Phase 2 ----------

def test_template_renders_strategy_reason_block():
    from quantia.notification.templates import build_trade_markdown
    out = build_trade_markdown({
        "direction": "buy", "code": "600016", "name": "民生银行",
        "price": 3.74, "amount": 26600, "value": 99484.0,
        "paper_id": 4, "trade_date": "2026-04-30",
        "executed_at": datetime.datetime(2026, 4, 30, 15, 30, 0),
        "commission": 29.85, "tax": 0,
        "dedupe_key": "abc",
        "reason": "BOLL 下轨反弹 + MA5 上穿 MA20", "reason_source": "strategy",
        "decision_rules": [
            {"rule_name": "BOLL 下轨接近度", "threshold_expr": "close<=lower*1.02",
             "actual_value": {"close": 3.74, "lower": 3.67}, "passed": 1},
            {"rule_name": "MA5 上穿 MA20", "threshold_expr": "ma5>ma20",
             "actual_value": {"ma5": 3.71, "ma20": 3.70}, "passed": True},
        ],
        "signal_id": 555,
    })
    md = out["markdown"]
    assert "策略真实理由" in md
    assert "BOLL 下轨反弹" in md
    assert "决策规则对比" in md
    assert "通过" in md
    assert "信号 ID：555" in md


def test_template_renders_generated_reason_with_explicit_label():
    from quantia.notification.templates import build_trade_markdown
    out = build_trade_markdown({
        "direction": "sell", "code": "600016", "name": "民生银行",
        "price": 3.92, "amount": 26600, "value": 104272.0,
        "paper_id": 4, "trade_date": "2026-04-30",
        "executed_at": None, "commission": 31.28, "tax": 104.27,
        "dedupe_key": "xyz",
        "reason": td.build_generated_reason("sell"),
        "reason_source": "generated",
        "decision_rules": [],
    })
    md = out["markdown"]
    assert "系统兜底说明" in md
    assert "由系统" in md
    # 没有规则时不应渲染表格
    assert "决策规则对比" not in md


def test_template_summary_before_details():
    from quantia.notification.templates import build_trade_markdown
    out = build_trade_markdown({
        "direction": "buy", "code": "600016",
        "price": 3.74, "amount": 100, "value": 374,
        "paper_id": 4, "trade_date": "2026-04-30",
        "reason": "策略提供", "reason_source": "strategy",
        "decision_rules": [{"rule_name": "x", "passed": 1}],
    })
    md = out["markdown"]
    # 摘要必须在详情之前出现
    assert md.find("## 摘要") < md.find("## 详情")
    # 决策规则也应在详情之前
    assert md.find("决策规则对比") < md.find("## 详情")


def test_template_caps_decision_rules_to_max():
    from quantia.notification.templates import build_trade_markdown
    rules = [{"rule_name": f"rule-{i}", "passed": 1} for i in range(8)]
    out = build_trade_markdown({
        "direction": "buy", "code": "x", "price": 1, "amount": 100, "value": 100,
        "paper_id": 1, "trade_date": "2026-04-30",
        "decision_rules": rules,
    })
    md = out["markdown"]
    # 默认上限 5
    assert "rule-0" in md and "rule-4" in md
    assert "rule-5" not in md
    assert "剩余 3 条" in md


# ---------- order proxy kwargs (paper_engine 兼容性，不实际跑策略) ----------

def test_order_proxy_kwargs_signature_matches_legacy():
    """Phase 2 扩展不能破坏旧策略调用签名。
    旧策略：order(code, 100) / order_target_percent(code, 0.5) — 不带 kwargs；
    新策略：order(code, 100, reason='x', decision={...}).
    本测试仅验证 lambda 签名形态，避免回归。
    """
    import inspect
    from quantia.paper_trading import paper_engine as pe
    src = inspect.getsource(pe.run_paper_trading_daily)
    # 5 个 order_* 都要支持 **kw
    assert "api_ns['order'] = lambda code, amount, **kw" in src
    assert "api_ns['order_target'] = lambda code, target, **kw" in src
    assert "api_ns['order_value'] = lambda code, value, **kw" in src
    assert "api_ns['order_target_value'] = lambda code, target_value, **kw" in src
    assert "api_ns['order_target_percent'] = lambda code, percent, **kw" in src
