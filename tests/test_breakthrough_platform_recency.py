# -*- coding: utf-8 -*-
"""突破平台策略 A+B+C 收紧后的回归测试。

针对生产事故：600664（哈药股份）2026-06-04 被"突破平台"误选——
3 个月前（2026-03-09）的一次突破，在之后约 60 个交易日里持续被判为买入，
即便当日股价已跌破 MA60 12.6%。

修复后要求：
- A 近期突破：突破日须在信号日当天或最近 recent_days 个交易日内
- B 仍站稳：突破日至信号日收盘价持续 >= MA60
- C 真实平台：突破日之前平台样本不少于 min_platform_days，且全部贴近 MA60
"""
import pandas as pd
import pytest

from quantia.core.strategy.breakthrough_platform import check

CODE_NAME = ("2026-06-04", "600664", "测试股")
_N = 130


def _build(scenario):
    """构造 130 个交易日的合成行情。平台基准价 20 元，平台量 400 万。"""
    dates = pd.bdate_range(end="2026-06-04", periods=_N)
    close = [20.0] * _N
    open_ = [20.0] * _N
    vol = [4_000_000.0] * _N

    def breakout(i):
        # 开盘价<MA60<=收盘价 且放量上涨（量比 3、成交额 ~2.5 亿、涨幅 +2.5%）
        open_[i] = 19.8
        close[i] = 20.5
        vol[i] = 12_000_000.0

    if scenario == "positive":
        # 信号日当天放量突破，且站稳均线
        breakout(_N - 1)
    elif scenario == "stale":
        # 突破发生在 10 个交易日前，之后一路下跌跌破 MA60（复现 600664）
        breakout(_N - 11)
        for k, i in enumerate(range(_N - 10, _N)):
            close[i] = 20.5 - 0.4 * (k + 1)
            open_[i] = close[i]
    elif scenario == "fallback":
        # 突破发生在 2 个交易日前，但随后跌回 MA60 下方（失效突破）
        breakout(_N - 3)
        close[_N - 2] = 19.0
        open_[_N - 2] = 19.0
        close[_N - 1] = 18.8
        open_[_N - 1] = 18.8
    else:
        raise ValueError(scenario)

    p_change = [0.0]
    for i in range(1, _N):
        p_change.append((close[i] - close[i - 1]) / close[i - 1] * 100)

    high = [max(open_[i], close[i]) * 1.01 for i in range(_N)]
    low = [min(open_[i], close[i]) * 0.99 for i in range(_N)]

    return pd.DataFrame({
        "date": dates,
        "open": open_,
        "close": close,
        "high": high,
        "low": low,
        "volume": vol,
        "p_change": p_change,
    })


def test_recent_platform_breakout_selected():
    """真实的近期平台突破：应被选中并返回指标字典。"""
    result = check(CODE_NAME, _build("positive"))
    assert isinstance(result, dict)
    assert result["close"] == pytest.approx(20.5)
    # 信号日仍站在 MA60 之上
    assert result["close"] >= result["ma60"]


def test_stale_breakthrough_rejected():
    """3 个月前突破、如今已跌破 MA60（600664 场景）：必须排除。"""
    assert check(CODE_NAME, _build("stale")) is False


def test_fallback_below_ma60_rejected():
    """近期突破但随后跌回 MA60 下方（失效假突破）：必须排除。"""
    assert check(CODE_NAME, _build("fallback")) is False


def test_oo_strategy_mirrors_core():
    """OO 版 BreakthroughPlatformStrategy 与核心 check 行为一致。"""
    from quantia.core.strategy.pattern.pattern_strategies import BreakthroughPlatformStrategy
    s = BreakthroughPlatformStrategy()
    assert s.check(CODE_NAME, _build("positive")) is True
    assert s.check(CODE_NAME, _build("stale")) is False
    assert s.check(CODE_NAME, _build("fallback")) is False
