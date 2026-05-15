#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kline_fetch 工具：拉取股票/指数 K 线（包装现有 data_feed.load_stock_data）。"""

from typing import Any, Dict, List

import math

from quantia.lib.ai.tools import Tool, ToolError

__author__ = 'Quantia'
__date__ = '2026/05/11'

_MAX_BARS = 500


class KlineFetchTool(Tool):
    name = 'kline_fetch'
    description = (
        '拉取股票或指数的日线 K 线（OHLCV）。'
        '返回最多 500 条；超出会按 end_date 截尾。'
    )
    parameters = {
        'type': 'object',
        'required': ['code'],
        'properties': {
            'code': {
                'type': 'string',
                'description': '6 位股票代码（如 600000）或指数代码（如 000300）',
            },
            'start_date': {
                'type': 'string',
                'description': 'YYYY-MM-DD，省略则取最近窗口',
            },
            'end_date': {
                'type': 'string',
                'description': 'YYYY-MM-DD，省略则取最新交易日',
            },
            'limit': {
                'type': 'integer',
                'description': f'返回的最大 K 线数量（默认 60，最大 {_MAX_BARS}）',
                'minimum': 1,
                'maximum': _MAX_BARS,
            },
        },
    }

    def run(self, args: Dict[str, Any]) -> Dict[str, Any]:
        code = (args.get('code') or '').strip()
        if not code:
            raise ToolError('code 不能为空')
        start_date = args.get('start_date') or None
        end_date = args.get('end_date') or None
        limit = args.get('limit') or 60
        try:
            limit = max(1, min(_MAX_BARS, int(limit)))
        except (TypeError, ValueError):
            raise ToolError('limit 必须是整数')
        try:
            from quantia.core.backtest.data_feed import load_stock_data
            df = load_stock_data(code, start_date, end_date)
        except Exception as exc:
            raise ToolError(f'加载 K 线失败: {exc}') from exc
        if df is None or len(df) == 0:
            return {'code': code, 'bar_count': 0, 'bars': []}
        df = df.tail(limit)
        bars: List[Dict[str, Any]] = []
        for _, row in df.iterrows():
            bar: Dict[str, Any] = {}
            for k in ('date', 'open', 'high', 'low', 'close', 'volume', 'amount'):
                if k not in row:
                    continue
                v = row[k]
                # P1-3（一轮审计）：NaN 不是 None，需显式跳过
                if v is None:
                    continue
                if isinstance(v, float) and math.isnan(v):
                    continue
                if hasattr(v, 'isoformat'):
                    bar[k] = str(v)
                elif k in ('open', 'high', 'low', 'close'):
                    try:
                        bar[k] = float(v)
                    except (TypeError, ValueError):
                        continue
                elif k in ('volume',):
                    try:
                        bar[k] = int(v)
                    except (TypeError, ValueError):
                        try:
                            bar[k] = int(float(v))
                        except (TypeError, ValueError):
                            continue
                else:
                    bar[k] = v
            bars.append(bar)
        return {'code': code, 'bar_count': len(bars), 'bars': bars}
