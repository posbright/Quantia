# -*- coding: utf-8 -*-
"""Phase 3: 通用交易信号详情/列表 API。

为回测详情、模拟交易详情、未来实盘 GUI 提供同一套 signal/decision/
indicator/selection 数据。所有读取都委托给 ``trade_signal_store``，
本文件只负责 HTTP 接入。
"""
from __future__ import annotations

import json
import logging
from abc import ABC

from tornado import gen

import quantia.web.base as webBase
from quantia.core.backtest import trade_signal_store as tss


def _json_default(value):
    # 兼容 datetime/date 与 Decimal
    try:
        import datetime as _dt
        from decimal import Decimal
    except Exception:
        return str(value)
    if isinstance(value, (_dt.date, _dt.datetime)):
        return value.strftime("%Y-%m-%d %H:%M:%S") if isinstance(value, _dt.datetime) else value.strftime("%Y-%m-%d")
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


class GetTradeSignalListHandler(webBase.BaseHandler, ABC):
    """GET /quantia/api/trade/signal/list?source_type=&source_id=

    列出某次回测或模拟盘的所有交易信号摘要。
    """

    @gen.coroutine
    def get(self):
        try:
            source_type = (self.get_argument("source_type", "") or "").strip()
            try:
                source_id = int(self.get_argument("source_id", "0") or 0)
            except Exception:
                source_id = 0
            if source_type not in ("paper", "backtest", "live") or source_id <= 0:
                self.write(json.dumps({"code": -1, "msg": "缺少或非法的 source_type/source_id"}, ensure_ascii=False))
                return
            try:
                limit = int(self.get_argument("limit", "500") or 500)
            except Exception:
                limit = 500
            limit = max(1, min(limit, 5000))
            rows = tss.list_signals_for_source(source_type, source_id, limit=limit)
            self.write(json.dumps({"code": 0, "data": rows}, ensure_ascii=False, default=_json_default))
        except Exception as e:
            logging.error("GetTradeSignalList异常", exc_info=True)
            self.write(json.dumps({"code": -1, "msg": str(e)}, ensure_ascii=False))


class GetTradeSignalDetailHandler(webBase.BaseHandler, ABC):
    """GET /quantia/api/trade/signal/detail?signal_id=

    返回 signal + 决策规则 + 指标快照 + 候选筛选快照。
    """

    @gen.coroutine
    def get(self):
        try:
            try:
                signal_id = int(self.get_argument("signal_id", "0") or 0)
            except Exception:
                signal_id = 0
            if signal_id <= 0:
                self.write(json.dumps({"code": -1, "msg": "缺少 signal_id"}, ensure_ascii=False))
                return
            data = tss.fetch_signal_with_decision(signal_id)
            if not data:
                self.write(json.dumps({"code": -1, "msg": "信号不存在"}, ensure_ascii=False))
                return
            self.write(json.dumps({"code": 0, "data": data}, ensure_ascii=False, default=_json_default))
        except Exception as e:
            logging.error("GetTradeSignalDetail异常", exc_info=True)
            self.write(json.dumps({"code": -1, "msg": str(e)}, ensure_ascii=False))
