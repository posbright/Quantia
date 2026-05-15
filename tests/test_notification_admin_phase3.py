#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 3 扩展验收：

1. ``TradeRecord.to_dict()`` 暴露 ``reason`` 与 ``reason_source``，
   保证回测详情前端 (``backtest-detail.vue``) 不修改即可读取
   策略真实理由。
2. ``notificationAdminHandler`` 的查询/汇总辅助函数：行白名单、
   payload 预览裁剪、JSON 解析兜底。
"""
import datetime
import json
from unittest.mock import patch

from quantia.core.backtest.strategy_context import TradeRecord
from quantia.web import notificationAdminHandler as nah


def test_traderecord_to_dict_exposes_reason_for_frontend():
    t = TradeRecord(datetime.date(2026, 5, 7), '600016', '民生银行', 'buy', 3.74, 100)
    t.reason = '布林下轨反弹+MA5上穿MA20'
    t.reason_source = 'strategy'
    d = t.to_dict()
    assert d['reason'] == '布林下轨反弹+MA5上穿MA20'
    assert d['reason_source'] == 'strategy'
    # 兼容旧消费者：原有字段不变
    assert d['code'] == '600016'
    assert d['direction'] == 'buy'
    assert d['amount'] == 100


def test_traderecord_to_dict_default_reason_empty_for_legacy_strategies():
    t = TradeRecord(datetime.date(2026, 5, 7), '600016', '民生银行', 'sell', 3.92, 100)
    d = t.to_dict()
    assert d['reason'] == ''
    assert d['reason_source'] == ''


def test_safe_str_truncates_long_text():
    s = 'x' * 1000
    out = nah._safe_str(s, max_len=128)
    assert len(out) == 128
    assert nah._safe_str(None) == ''


def test_try_parse_json_handles_dict_str_and_garbage():
    assert nah._try_parse_json(None) is None
    assert nah._try_parse_json('') is None
    assert nah._try_parse_json('{"a": 1}') == {"a": 1}
    # 非 JSON 文本应原样返回（便于人工排查）
    assert nah._try_parse_json('not-json{') == 'not-json{'
    # 已是结构化对象时直接透传
    assert nah._try_parse_json({"x": 2}) == {"x": 2}


def _fake_row():
    return (
        42,                                # id
        'dedupe-abc',                      # dedupe_key
        7,                                 # paper_id
        'paper_trade',                     # event_type
        'dingtalk',                        # channel
        datetime.date(2026, 5, 7),         # trade_date
        '600016',                          # code
        'buy',                             # direction
        'sent',                            # status
        1,                                 # retry_count
        3,                                 # max_retries
        None,                              # next_retry_at
        '',                                # error_message
        datetime.datetime(2026, 5, 7, 15, 30, 0),  # created_at
        datetime.datetime(2026, 5, 7, 15, 30, 1),  # updated_at
        datetime.datetime(2026, 5, 7, 15, 30, 1),  # sent_at
        json.dumps({"msgtype": "markdown", "markdown": {"text": "买入信号"}}, ensure_ascii=False),
        json.dumps({"errcode": 0, "errmsg": "ok"}),
    )


def test_row_to_summary_list_mode_returns_preview_only():
    s = nah._row_to_summary(_fake_row(), include_full_payload=False)
    assert s['event_id'] == 42
    assert s['paper_id'] == 7
    assert s['status'] == 'sent'
    assert s['code'] == '600016'
    # 列表模式：仅返回 preview 字段，不返回完整 payload/response
    assert 'payload_preview' in s and 'response_preview' in s
    assert 'payload' not in s and 'response' not in s
    assert '买入信号' in s['payload_preview']


def test_row_to_summary_detail_mode_returns_parsed_payload():
    s = nah._row_to_summary(_fake_row(), include_full_payload=True)
    assert s['event_id'] == 42
    assert s['payload'] == {"msgtype": "markdown", "markdown": {"text": "买入信号"}}
    assert s['response'] == {"errcode": 0, "errmsg": "ok"}
    # 详情模式不再包含 preview
    assert 'payload_preview' not in s
    assert 'response_preview' not in s


def test_query_events_applies_filters_and_limit_clamp():
    captured = {}

    def fake_fetch(sql, params):
        captured['sql'] = sql
        captured['params'] = params
        return [_fake_row()]

    with patch('quantia.lib.database.executeSqlFetch', side_effect=fake_fetch):
        rows = nah._query_events(
            {"paper_id": 7, "status": "sent", "channel": "dingtalk",
             "code": "600016", "since": "2026-05-01"},
            limit=50,
        )
    assert len(rows) == 1
    sql = captured['sql']
    assert 'paper_id = %s' in sql
    assert 'status = %s' in sql
    assert 'channel = %s' in sql
    assert 'code = %s' in sql
    assert 'created_at >= %s' in sql
    # 7 个参数 + limit
    assert captured['params'] == (7, 'sent', 'dingtalk', '600016', '2026-05-01', 50)


def test_query_events_no_filters_returns_recent_events():
    captured = {}

    def fake_fetch(sql, params):
        captured['sql'] = sql
        captured['params'] = params
        return [_fake_row(), _fake_row()]

    with patch('quantia.lib.database.executeSqlFetch', side_effect=fake_fetch):
        rows = nah._query_events({}, limit=10)
    assert len(rows) == 2
    assert captured['params'] == (10,)
    assert 'ORDER BY id DESC' in captured['sql']


def test_routes_registered_on_application():
    # 验证路由在 web_service 内已注册（不启动 HTTP server）
    import quantia.web.web_service as ws
    app = ws.Application()
    rules = []
    for h in app.default_router.rules[0].target.rules:
        try:
            rules.append(h.matcher.regex.pattern)
        except Exception:
            pass
    joined = ' '.join(rules)
    assert '/quantia/api/notification/event/list' in joined
    assert '/quantia/api/notification/event/detail' in joined
    assert '/quantia/api/trade/signal/list' in joined
    assert '/quantia/api/trade/signal/detail' in joined
