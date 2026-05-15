"""硬规则 AST 沙箱单元测试 — 包含安全性测试。"""
import numpy as np
import pandas as pd
import pytest

from quantia.core.composite.hard_rules_engine import (
    SecurityError, RuleEvalError,
    parse_hard_rules, eval_hard_rules,
)


def _df():
    return pd.DataFrame({
        "rsi14": [50.0, 25.0, 35.0, 28.0],
        "close": [10.0, 9.0, 9.5, 9.2],
        "open":  [10.0, 9.5, 9.4, 9.0],
        "boll_lower": [9.0, 9.0, 9.0, 9.0],
        "volume": [1000, 2000, 1500, 3000],
    })


# ============================ 正常用例 =======================================
def test_simple_comparison():
    out = eval_hard_rules("d['rsi14'] < 30", _df())
    assert out.tolist() == [False, True, False, True]


def test_combined_conditions():
    out = eval_hard_rules(
        "(d['rsi14'] < 30) & (d['close'] > d['boll_lower'])", _df()
    )
    assert out.tolist() == [False, False, False, True]


def test_method_call_rolling_mean():
    out = eval_hard_rules(
        "d['volume'] > d['volume'].rolling(2).mean()", _df()
    )
    # 第二行: 2000 > (1000+2000)/2=1500 → True
    assert out.iloc[1] == True
    # NaN 行被填 False
    assert out.iloc[0] == False


def test_safe_builtin_min_max():
    out = eval_hard_rules("d['close'] > min(9.0, 8.0)", _df())
    assert out.all()


def test_returns_bool_series():
    out = eval_hard_rules("d['rsi14'] < 30", _df())
    assert isinstance(out, pd.Series)
    assert out.dtype == bool


# ============================ 安全性测试 — 必须 raise SecurityError =========
@pytest.mark.parametrize("expr", [
    "__import__('os')",
    "d.__class__",
    "(0).__class__.__bases__",
    "open('x.txt')",                  # 未注册函数
    "exec('x=1')",
    "eval('1+1')",
    "lambda x: x",                    # 禁止 lambda
    "d.values",                       # d.xxx 禁止
    "np.array([1])",                  # np.array 不在白名单
])
def test_security_blocks_dangerous(expr):
    with pytest.raises((SecurityError, RuleEvalError)):
        parse_hard_rules(expr)


def test_friendly_error_on_missing_column():
    with pytest.raises(RuleEvalError, match="未知字段"):
        eval_hard_rules("d['nonexistent_col'] > 0", _df())


def test_friendly_error_on_syntax():
    with pytest.raises(RuleEvalError, match="语法"):
        eval_hard_rules("d['rsi14'] < <", _df())


def test_must_return_series_not_scalar():
    with pytest.raises(RuleEvalError, match="pd.Series"):
        eval_hard_rules("1 < 2", _df())
