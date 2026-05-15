#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import base64
import datetime
import hashlib
import hmac
import json
from urllib.parse import quote_plus

from quantia.core.backtest.strategy_context import TradeRecord
from quantia.notification.channels.dingtalk import DingTalkChannel
from quantia.notification.service import build_trade_dedupe_key, notify_trade_records
from quantia.notification.templates import build_trade_markdown


def test_dingtalk_signed_url_matches_official_algorithm():
    webhook = "https://oapi.dingtalk.com/robot/send?access_token=abc"
    secret = "SEC-test"
    timestamp = 1760000000000
    digest = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}\n{secret}".encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    expected_sign = quote_plus(base64.b64encode(digest))

    signed_url = DingTalkChannel.build_signed_url(webhook, secret, timestamp)

    assert f"timestamp={timestamp}" in signed_url
    assert f"sign={expected_sign}" in signed_url


def test_trade_markdown_summary_is_before_details():
    message = build_trade_markdown({
        "paper_id": 4,
        "trade_date": "2026-04-30",
        "executed_at": datetime.datetime(2026, 4, 30, 15, 1),
        "code": "600016",
        "name": "民生银行",
        "direction": "buy",
        "price": 4.321,
        "amount": 1000,
        "value": 4321,
        "dedupe_key": "abc",
    })

    assert "## 摘要" in message["markdown"]
    assert "## 详情" in message["markdown"]
    assert message["markdown"].index("## 摘要") < message["markdown"].index("## 详情")
    assert "600016 民生银行" in message["markdown"]


def test_trade_markdown_buy_matches_doc_section_7_1():
    """文档 §7.1 买入通知模板：标题、6 项摘要、标的与运行、成交信息字段。"""
    md = build_trade_markdown({
        "paper_id": 4, "trade_date": "2026-04-27",
        "executed_at": datetime.datetime(2026, 4, 27, 15, 30, 0),
        "code": "600016", "name": "民生银行", "direction": "buy",
        "price": 3.74, "amount": 26600, "value": 99484.0,
        "commission": 29.85, "tax": 0, "slippage_cost": 49.74,
        "position_after_pct": 0.498,
        "paper_name": "BOLL 下轨策略模拟盘",
        "strategy_name": "BOLL 下轨反弹策略",
        "run_id": "paper-4-20260427-153000",
        "reason": "BOLL 下轨附近反弹，MA5 上穿 MA20",
        "reason_source": "strategy",
        "ai_score": 82.5, "ai_action": "buy", "ai_gate_result": "pass",
        "ai_risk_flags": ["MA60 仍偏弱，跌破下轨需复核止损"],
    })
    assert md["title"] == "【模拟盘买入信号】600016 民生银行"
    body = md["markdown"]
    # 摘要（含 6 项）
    assert "## 摘要" in body
    assert "- 标的：600016 民生银行" in body
    assert "- 方向：买入" in body
    assert "82.50/100" in body and "建议 buy" in body and "Gate 通过" in body
    assert "99,484.00 元" in body and "成交后仓位 49.80%" in body
    assert "核心理由：" in body
    assert "关键风险：" in body
    # 标的与运行
    assert "BOLL 下轨策略模拟盘" in body and "#4" in body
    assert "BOLL 下轨反弹策略" in body
    assert "paper-4-20260427-153000" in body
    assert "2026-04-27" in body
    # 成交信息（命名为 ## 详情 以保持兼容）
    assert "成交价" in body and "3.740" in body
    assert "26,600 股" in body
    assert "佣金：29.85 元" in body
    assert "滑点成本：49.74 元" in body


def test_trade_markdown_sell_includes_close_profit_and_return_rate():
    """文档 §7.2 卖出通知模板：印花税、平仓盈亏、收益率、负号格式。"""
    md = build_trade_markdown({
        "paper_id": 4, "trade_date": "2026-05-07",
        "executed_at": datetime.datetime(2026, 5, 7, 15, 0, 0),
        "code": "600016", "name": "民生银行", "direction": "sell",
        "price": 3.92, "amount": 26600, "value": 104272.0,
        "commission": 31.28, "tax": 104.27, "slippage_cost": 52.14,
        "close_profit": 4590.72, "return_rate": 4.61,
        "position_after_pct": 0.0,
    })["markdown"]
    assert "【模拟盘卖出信号】600016 民生银行" not in md  # 在 title 不在 body
    assert "- 方向：卖出" in md
    assert "印花税：104.27 元" in md
    assert "+4,590.72 元" in md
    assert "收益率：+4.61%" in md


def test_trade_markdown_link_block_uses_hostname_fallback(monkeypatch):
    """没有配置 QUANTIA_WEB_BASE_URL 时，回退到 http://<hostname>:9988，仍渲染可点击链接。"""
    monkeypatch.delenv("QUANTIA_WEB_BASE_URL", raising=False)
    md = build_trade_markdown({
        "paper_id": 4, "trade_date": "2026-04-30",
        "code": "600016", "name": "民生银行", "direction": "buy",
        "price": 3.74, "amount": 100, "value": 374,
    })["markdown"]
    assert "## 查看详情" in md
    # Markdown 链接语法 [text](url) 让 DingTalk 客户端可直接点击跳浏览器
    assert "](http://" in md
    assert ":9988/algo/paper?id=4" in md


def test_trade_markdown_renders_link_block_when_base_url_set(monkeypatch):
    monkeypatch.setenv("QUANTIA_WEB_BASE_URL", "https://example.com/quantia")
    md = build_trade_markdown({
        "paper_id": 4, "trade_date": "2026-04-30",
        "code": "600016", "name": "民生银行", "direction": "buy",
        "price": 3.74, "amount": 100, "value": 374, "signal_id": 12345,
    })["markdown"]
    assert "## 查看详情" in md
    # base 末尾的 /quantia 必须被剥离（Vue Router 默认 base='/'，SPA 路由不带
    # /quantia 前缀；保留会被前端识别为 NotFound → 显示 404）。
    assert "https://example.com/algo/paper?id=4&signal_id=12345" in md
    assert "/quantia/algo/paper" not in md
    # 必须使用 Markdown [text](url) 语法
    assert "](https://example.com/algo/paper?id=4&signal_id=12345)" in md
    # 旧的 /trade/signal 路由前端不存在（NotFound），不应再出现
    assert "/trade/signal?" not in md


def test_trade_markdown_keeps_link_when_base_url_has_no_QUANTIA_suffix(monkeypatch):
    """正常配置（base 不含 /quantia）时不应受影响。"""
    monkeypatch.setenv("QUANTIA_WEB_BASE_URL", "https://example.com")
    md = build_trade_markdown({
        "paper_id": 7, "trade_date": "2026-04-30",
        "code": "600016", "name": "民生银行", "direction": "sell",
        "price": 3.92, "amount": 100, "value": 392, "signal_id": 999,
    })["markdown"]
    assert "https://example.com/algo/paper?id=7&signal_id=999" in md



def test_trade_dedupe_key_is_stable_and_channel_scoped():
    trade = TradeRecord(datetime.date(2026, 4, 30), "600016", "民生银行", "buy", 4.32, 1000)

    key1 = build_trade_dedupe_key(4, trade, "2026-04-30", "dingtalk")
    key2 = build_trade_dedupe_key(4, trade, "2026-04-30", "dingtalk")
    key3 = build_trade_dedupe_key(4, trade, "2026-04-30", "other")

    assert key1 == key2
    assert key1 != key3
    assert len(key1) == 64


class _FakeCursor:
    def __init__(self, state):
        self.state = state
        self.rowcount = 0
        self._row = None

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def execute(self, sql, params=()):
        sql_upper = sql.strip().upper()
        if sql_upper.startswith("INSERT IGNORE"):
            dedupe_key = params[0]
            if dedupe_key in self.state["dedupe"]:
                self.rowcount = 0
            else:
                self.state["dedupe"].add(dedupe_key)
                self.state["last_id"] += 1
                self.rowcount = 1
                self.state["events"].append({
                    "id": self.state["last_id"],
                    "dedupe_key": dedupe_key,
                    "status": params[7],
                    "payload": json.loads(params[8]),
                    "error": params[9],
                })
        elif sql_upper.startswith("SELECT LAST_INSERT_ID"):
            self._row = (self.state["last_id"],)
        elif sql_upper.startswith("UPDATE"):
            self.state["updates"].append((sql, params))
            self.rowcount = 1

    def fetchone(self):
        return self._row


class _FakeConnection:
    def __init__(self, state):
        self.state = state

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def cursor(self):
        return _FakeCursor(self.state)


def test_enqueue_creates_skipped_event_and_dedupes_without_webhook(monkeypatch):
    import quantia.lib.database as mdb
    import quantia.notification.service as service

    state = {"dedupe": set(), "last_id": 0, "events": [], "updates": []}
    monkeypatch.delenv("QUANTIA_DINGTALK_WEBHOOK", raising=False)
    monkeypatch.setattr(mdb, "checkTableIsExist", lambda table: True)
    monkeypatch.setattr(mdb, "executeSql", lambda sql, params=(): state["updates"].append((sql, params)))
    monkeypatch.setattr(mdb, "executeSqlFetch", lambda sql, params=(): [])
    monkeypatch.setattr(mdb, "get_connection", lambda: _FakeConnection(state))

    trade = TradeRecord(datetime.date(2026, 4, 30), "600016", "民生银行", "buy", 4.32, 1000)
    first = service.enqueue_trade_notification(4, trade, "2026-04-30", send_now=True)
    second = service.enqueue_trade_notification(4, trade, "2026-04-30", send_now=True)

    assert first["created"] is True
    assert first["status"] == "skipped"
    assert second["created"] is False
    assert len(state["events"]) == 1
    assert state["events"][0]["payload"]["msgtype"] == "markdown"


def test_notify_trade_records_isolation_when_single_event_raises(monkeypatch):
    import quantia.notification.service as service

    trade = TradeRecord(datetime.date(2026, 4, 30), "600016", "民生银行", "sell", 4.32, 1000)

    def _raise(*args, **kwargs):
        raise RuntimeError("webhook down")

    monkeypatch.setattr(service, "enqueue_trade_notification", _raise)

    stats = notify_trade_records(4, [trade], "2026-04-30")

    assert stats["failed"] == 1
    assert stats["created"] == 0
    assert stats["sent"] == 0


def test_process_pending_notifications_sends_due_outbox_event(monkeypatch):
    import quantia.lib.database as mdb
    import quantia.notification.service as service

    payload = {"msgtype": "markdown", "markdown": {"title": "t", "text": "body"}}
    calls = []

    monkeypatch.setattr(service, "ensure_notification_tables", lambda: None)
    monkeypatch.setattr(
        mdb,
        "executeSqlFetch",
        lambda sql, params=(): [(11, 4, "paper_trade", json.dumps(payload, ensure_ascii=False))]
        if "payload_json" in sql else [("sent",)],
    )
    monkeypatch.setattr(
        service,
        "_send_payload_for_event",
        lambda event_id, paper_id, event_type, event_payload: calls.append(
            (event_id, paper_id, event_type, event_payload)
        ) or True,
    )

    stats = service.process_pending_notifications(limit=5)

    assert stats == {"processed": 1, "sent": 1, "failed": 0, "skipped": 0}
    assert calls == [(11, 4, "paper_trade", payload)]