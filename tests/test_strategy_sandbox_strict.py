"""Tests for quantia.core.backtest.strategy_sandbox.validate_code_strict."""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from quantia.core.backtest.strategy_sandbox import validate_code, validate_code_strict


_GOOD_CODE = """
import numpy as np
import pandas as pd

def initialize(context):
    g.security_universe = []

def handle_data(context, data):
    pass
"""


def test_strict_accepts_clean_code():
    ok, err = validate_code_strict(_GOOD_CODE)
    assert ok, err


def test_strict_rejects_import_os_via_ast():
    # 老 validate_code 已能挡，确认 strict 也挡
    code = "import os\n" + _GOOD_CODE
    ok, err = validate_code_strict(code)
    assert not ok
    assert 'os' in err


def test_strict_rejects_dunder_class_chain():
    code = _GOOD_CODE + "\nx = ().__class__\n"
    ok, err = validate_code_strict(code)
    # 老 validate_code 已能挡 __class__；strict 也挡（覆盖 attr）
    assert not ok


def test_strict_rejects_obfuscated_import_via_subclasses():
    # 即使老正则放过此组合，AST 层仍要挡 __subclasses__
    code = _GOOD_CODE + "\ndef initialize(context):\n    s = object.__subclasses__\n"
    ok, err = validate_code_strict(code)
    assert not ok


def test_strict_rejects_eval_call():
    code = _GOOD_CODE + "\nval = eval('1+1')\n"
    ok, err = validate_code_strict(code)
    assert not ok
    assert 'eval' in err


def test_strict_rejects_disallowed_from_import():
    code = "from urllib import request\n" + _GOOD_CODE
    ok, err = validate_code_strict(code)
    assert not ok
    assert 'urllib' in err


def test_strict_rejects_syntax_error():
    code = "def initialize(context):\n    pass\n  oops\n"
    ok, err = validate_code_strict(code)
    assert not ok
    assert '语法错误' in err or 'syntax' in err.lower()


def test_strict_passes_through_validate_code_failure():
    """validate_code_strict 必须先经过 validate_code，老规则失败时直接返回。"""
    code = "open('/etc/passwd')\n" + _GOOD_CODE
    ok_loose, err_loose = validate_code(code)
    assert not ok_loose
    ok, err = validate_code_strict(code)
    assert not ok
    # 错误来自老规则即可
    assert err == err_loose


def test_strict_allows_talib_and_math():
    code = """
import math
import talib as ta

def initialize(context):
    g.x = math.pi

def handle_data(context, data):
    pass
"""
    ok, err = validate_code_strict(code)
    assert ok, err
