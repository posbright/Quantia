# -*- coding: utf-8 -*-
"""Phase 3 测试：回测引擎信号采集、聚合写入、统一详情 API。

不依赖真实 MySQL；用 monkeypatch 替换 ``trade_signal_store._get_db``。
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from quantia.core.backtest import trade_decision as td
from quantia.core.backtest import trade_signal_store as tss


# ---------- list_signals_for_source ----------

def test_list_signals_for_source_returns_summary(monkeypatch):
    fake_rows = [
        (101, "2026-04-30", "600016", "民生银行", "buy", "order_target_percent",
         None, 99484.0, None, 0.5, "BOLL 下轨反弹", "strategy", None, "backtest-7-x"),
        (102, "2026-05-04", "600016", "民生银行", "sell", "order_target",
         -100, None, 0, None, "止盈卖出", "strategy", None, "backtest-7-x"),
    ]

    def _fetch(sql, params):
        assert "FROM `cn_stock_trade_signal`" in sql
        assert params[0] == "backtest" and params[1] == 7
        return fake_rows

    monkeypatch.setattr(tss, "_get_db", lambda: SimpleNamespace(executeSqlFetch=_fetch))
    out = tss.list_signals_for_source("backtest", 7)
    assert len(out) == 2
    assert out[0]["signal_id"] == 101 and out[0]["direction"] == "buy"
    assert out[1]["reason_source"] == "strategy"


def test_list_signals_for_source_validates_inputs(monkeypatch):
    monkeypatch.setattr(tss, "_get_db", lambda: pytest.fail("应在校验阶段返回，不应触达 DB"))
    assert tss.list_signals_for_source("", 1) == []
    assert tss.list_signals_for_source("paper", 0) == []


# ---------- fetch_signal_with_decision Phase 3 扩展 ----------

def test_fetch_signal_with_decision_includes_indicators_and_selection(monkeypatch):
    """Phase 3：fetch 必须返回 indicators + selection，使前端可统一展示。"""
    queries = []
    indicator_payload = (
        "daily", "2026-04-30",
        3.70, 3.78, 3.69, 3.74, 100000, 374000.0,
        '{"ma5": 3.71, "ma20": 3.70}',
        '{"upper": 3.95, "mid": 3.81, "lower": 3.67}',
        None, None, None,
        '{"my_factor": 0.42}',
    )

    def _fetch(sql, params):
        queries.append(sql)
        sql_up = sql.upper()
        if "FROM `CN_STOCK_TRADE_SIGNAL`" in sql_up:
            return [(
                42, "BOLL 下轨反弹", "strategy", "600016", "民生银行", "buy",
                "2026-04-30", None, 99484.0, None, 0.5,
                "order_target_percent", "backtest", 7, "backtest-7-x", None,
                None, None, None, None,
            )]
        if "FROM `CN_STOCK_TRADE_DECISION`" in sql_up:
            return [
                ("entry", "BOLL 下轨接近度", "close<=lower*1.02",
                 None, '{"close": 3.74, "lower": 3.67}', 1, "在 2% 区间"),
            ]
        if "FROM `CN_STOCK_TRADE_INDICATOR_SNAPSHOT`" in sql_up:
            return [indicator_payload]
        if "FROM `CN_STOCK_TRADE_SELECTION_SNAPSHOT`" in sql_up:
            return [("final", 100, 1, 0.91, 1, "rank desc",
                     '{"score": 0.91}', 1, "BOLL 触发")]
        return []

    monkeypatch.setattr(tss, "_get_db", lambda: SimpleNamespace(executeSqlFetch=_fetch))
    out = tss.fetch_signal_with_decision(42)
    assert out["signal_id"] == 42
    assert out["target_percent"] == 0.5
    assert out["source_type"] == "backtest" and out["source_id"] == 7
    assert len(out["rules"]) == 1
    ind = out["indicators"]
    assert ind is not None and ind["close"] == 3.74
    assert "ma5" in ind["ma"]
    assert len(out["selection"]) == 1
    assert out["selection"][0]["stage"] == "final"
    # 4 张表都被查询了。
    assert sum("CN_STOCK_TRADE_SIGNAL" in q.upper() for q in queries) == 1
    assert sum("CN_STOCK_TRADE_DECISION" in q.upper() for q in queries) == 1
    assert sum("CN_STOCK_TRADE_INDICATOR_SNAPSHOT" in q.upper() for q in queries) == 1
    assert sum("CN_STOCK_TRADE_SELECTION_SNAPSHOT" in q.upper() for q in queries) == 1


def test_fetch_signal_with_decision_missing_returns_empty(monkeypatch):
    monkeypatch.setattr(tss, "_get_db",
                        lambda: SimpleNamespace(executeSqlFetch=lambda *a, **kw: []))
    assert tss.fetch_signal_with_decision(0) == {}
    assert tss.fetch_signal_with_decision(99999) == {}


# ---------- persist_backtest_signals ----------

class _StubTrade:
    __slots__ = ("date", "code", "name", "direction")

    def __init__(self, date, code, name, direction):
        self.date = date
        self.code = code
        self.name = name
        self.direction = direction


def test_persist_backtest_signals_invokes_persist_per_trade(monkeypatch):
    captured: List[Dict[str, Any]] = []

    def _fake_persist(**kw):
        captured.append(kw)
        return 1000 + len(captured)

    monkeypatch.setattr(tss, "persist_signal_with_relations", _fake_persist)
    trades = [
        _StubTrade("2026-04-30", "600016", "民生银行", "buy"),
        _StubTrade("2026-05-04", "600016", "民生银行", "sell"),
    ]
    inputs = [
        {"amount": None, "value": 99484.0, "order_api": "order_target_percent",
         "target_percent": 0.5,
         "reason": "BOLL 下轨反弹",
         "decision": {"rules": [{"name": "BOLL 下轨接近度", "passed": True}]},
         "indicators": {"close": 3.74, "ma": {"ma5": 3.71}},
         "selection": [{"stage": "final", "passed": True}]},
        {},  # 旧策略不传 → 触发 generated reason
    ]
    n = tss.persist_backtest_signals(
        backtest_id=7, run_id="backtest-7-x",
        trade_records=trades, signal_inputs=inputs,
    )
    assert n == 2
    assert captured[0]["source_type"] == "backtest" and captured[0]["source_id"] == 7
    assert captured[0]["reason_source"] == td.REASON_SOURCE_STRATEGY
    assert captured[0]["target_percent"] == 0.5
    # 第二笔没有 reason → 兜底说明
    assert captured[1]["reason_source"] == td.REASON_SOURCE_GENERATED
    # signal_hash 在两笔之间不同
    assert captured[0]["signal_hash"] != captured[1]["signal_hash"]


def test_persist_backtest_signals_handles_uneven_input_lengths(monkeypatch):
    def _fake_persist(**kw):
        # 输入缺失时，第二笔会用空 dict
        return 1
    monkeypatch.setattr(tss, "persist_signal_with_relations", _fake_persist)
    trades = [_StubTrade("2026-04-30", "600016", "民生银行", "buy")] * 3
    n = tss.persist_backtest_signals(
        backtest_id=7, run_id="r", trade_records=trades, signal_inputs=[{}],
    )
    assert n == 3


def test_persist_backtest_signals_no_op_for_empty(monkeypatch):
    called = {"n": 0}

    def _fake_persist(**kw):
        called["n"] += 1
        return 1
    monkeypatch.setattr(tss, "persist_signal_with_relations", _fake_persist)
    assert tss.persist_backtest_signals(backtest_id=0, run_id="r",
                                         trade_records=[], signal_inputs=[]) == 0
    assert tss.persist_backtest_signals(backtest_id=7, run_id="r",
                                         trade_records=[], signal_inputs=[]) == 0
    assert called["n"] == 0


def test_persist_backtest_signals_swallows_exceptions(monkeypatch):
    def _raise(**kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(tss, "persist_signal_with_relations", _raise)
    trades = [_StubTrade("2026-04-30", "600016", "民生银行", "buy")]
    n = tss.persist_backtest_signals(
        backtest_id=7, run_id="r", trade_records=trades, signal_inputs=[{}])
    assert n == 0  # 失败但不抛出


# ---------- portfolio_engine 信号采集（不跑真回测）----------

def test_portfolio_engine_order_lambdas_accept_kwargs():
    """旧策略调用签名不变；新策略可显式传 reason/decision。"""
    import inspect
    from quantia.core.backtest import portfolio_engine as pe
    src = inspect.getsource(pe.PortfolioBacktestEngine._create_strategy_api)
    assert "def order(code, amount, **kw)" in src
    assert "def order_target(code, target_amount, **kw)" in src
    assert "def order_value(code, value, **kw)" in src
    assert "def order_target_value(code, target_value, **kw)" in src
    assert "def order_target_percent(code, percent, **kw)" in src
    # _signal_inputs 应在 _execute_single_order 中 1:1 append
    src_exec = inspect.getsource(pe.PortfolioBacktestEngine._execute_single_order)
    assert "self._signal_inputs.append(order_info)" in src_exec
