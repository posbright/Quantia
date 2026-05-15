#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pandas as pd


def _fake_kline_result(periods=100):
    dates = pd.bdate_range('2024-01-01', periods=periods).strftime('%Y-%m-%d').tolist()
    closes = list(range(1, periods + 1))
    ma60 = [None] * 59 + [sum(closes[i - 59:i + 1]) / 60 for i in range(59, periods)]
    return {
        'code': '000001',
        'period': 'daily',
        'total': periods,
        'dates': dates,
        'ohlc': [[v, v, v, v] for v in closes],
        'volumes': [1000] * periods,
        'ma': {'ma60': ma60},
        'boll': {'middle': ma60[:]},
        'macd': {'histogram': [0] * periods},
    }


def test_kline_slice_keeps_warmup_before_backtest_start_for_indicators():
    from quantia.web.klineHandler import _slice_kline_result

    original = _fake_kline_result()
    start_date = original['dates'][70]
    end_date = original['dates'][80]

    sliced = _slice_kline_result(original, start_date=start_date, end_date=end_date, warmup_days=20)

    assert sliced['dates'][0] == original['dates'][50]
    assert start_date in sliced['dates']
    start_index = sliced['dates'].index(start_date)
    assert sliced['ma']['ma60'][start_index] is not None
    assert sliced['boll']['middle'][start_index] is not None
    assert sliced['indicator_source'] == 'full_cache_before_slice'
    assert sliced['source_total'] == len(original['dates'])


def test_kline_slice_applies_days_after_indicator_arrays_exist():
    from quantia.web.klineHandler import _slice_kline_result

    original = _fake_kline_result()
    sliced = _slice_kline_result(original, days=30)

    assert len(sliced['dates']) == 30
    assert len(sliced['ma']['ma60']) == 30
    assert sliced['ma']['ma60'][0] is not None
