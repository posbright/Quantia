# -*- coding: utf-8 -*-
"""沙箱校验对 UTF-8/latin-1 双重编码 mojibake 的检测。

回归背景：Moonshot SSE 响应不声明 charset，导致 requests 默认按 ISO-8859-1
解码中文 UTF-8，二次入库形成 mojibake。即便流式层已修复，仍需在沙箱校验
拦截存量来源。
"""
import pytest

from quantia.core.backtest.strategy_sandbox import (
    validate_code_strict,
    _detect_mojibake,
)


# ──────────────────────────────────────────────────────────────
# _detect_mojibake 单元测试
# ──────────────────────────────────────────────────────────────

def test_detect_mojibake_clean_chinese_ok():
    """正常 UTF-8 中文不应误报。"""
    assert _detect_mojibake('"""基本面筛选：用户限定的条件写在这里"""') == ''


def test_detect_mojibake_ascii_only_ok():
    """纯 ASCII 不应误报。"""
    assert _detect_mojibake('def initialize(context): pass') == ''


def test_detect_mojibake_empty_ok():
    assert _detect_mojibake('') == ''
    assert _detect_mojibake(None) == ''


def test_detect_mojibake_double_encoded_caught():
    """构造 UTF-8 -> latin-1 双重编码后再次解码出来的 mojibake，必须被检出。"""
    original = '"""基本面筛选：用户限定的条件写在这里，季度调仓"""'
    # 模拟 requests 错误解码：UTF-8 字节 -> latin-1 字符串
    mojibake = original.encode('utf-8').decode('latin-1')
    msg = _detect_mojibake(mojibake)
    assert msg, f'expected mojibake detection, got empty for: {mojibake!r}'
    assert '双重编码' in msg or 'mojibake' in msg.lower() or '乱码' in msg


def test_detect_mojibake_pure_latin1_no_false_positive():
    """纯英文 + 少量 latin-1 字符（如 ©®）不应被误报为 mojibake。"""
    text = '# Copyright © 2026 — résumé naïve façade café'
    # 这种文本即使含 latin-1 扩展字符，反解 utf-8 后不会出现大量中文。
    assert _detect_mojibake(text) == ''


# ──────────────────────────────────────────────────────────────
# validate_code_strict 集成测试
# ──────────────────────────────────────────────────────────────

def test_validate_strict_clean_code_passes():
    code = (
        'def initialize(context):\n'
        '    """初始化：设置基准与调仓节奏"""\n'
        '    g.refresh_days = 60\n'
        '\n'
        'def handle(context):\n'
        '    """日内回调：金叉买入死叉卖出"""\n'
        '    pass\n'
    )
    ok, err = validate_code_strict(code)
    assert ok, f'clean code should pass, got error: {err}'


def test_validate_strict_mojibake_code_rejected():
    """带 mojibake docstring 的代码应被沙箱拒绝。"""
    original = (
        'def initialize(context):\n'
        '    """基本面筛选：每个季度选取 ROE 最高的若干只股票，'
        '季度调仓 + 日内根据 5/20 均线择时"""\n'
        '    g.refresh_days = 60\n'
    )
    corrupted = original.encode('utf-8').decode('latin-1')
    ok, err = validate_code_strict(corrupted)
    assert not ok, '双重编码的注释应该被拒绝'
    assert err  # 错误信息非空
