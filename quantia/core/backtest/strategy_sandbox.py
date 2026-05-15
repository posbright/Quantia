#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略安全沙箱 — 编译和验证用户策略代码

安全措施：
- 白名单导入（仅允许 math/numpy/pandas/talib）
- 禁止危险函数（exec/eval/open/import os/sys）
- 超时保护（回测引擎层面实现）
- AI 通道可使用 ``validate_code_strict()`` 走 AST 双层校验
"""

import ast
import logging
import re

__author__ = 'Quantia'
__date__ = '2026/03/13'

# 禁止的关键字和模块
_FORBIDDEN_PATTERNS = [
    r'\bimport\s+os\b',
    r'\bimport\s+sys\b',
    r'\bimport\s+subprocess\b',
    r'\bimport\s+shutil\b',
    r'\bfrom\s+os\b',
    r'\bfrom\s+sys\b',
    r'\bfrom\s+subprocess\b',
    r'\bfrom\s+shutil\b',
    r'\b__import__\b',
    r'\beval\s*\(',
    r'\bexec\s*\(',
    r'\bcompile\s*\(',
    r'\bopen\s*\(',
    r'\bgetattr\s*\(',
    r'\bsetattr\s*\(',
    r'\bdelattr\s*\(',
    r'\bglobals\s*\(',
    r'\blocals\s*\(',
    r'__class__',
    r'__bases__',
    r'__subclasses__',
    r'__mro__',
    r'__dict__',
    r'__globals__',
    r'__code__',
    r'__builtins__',
    r'__import__',
]

# 允许的导入模块
_ALLOWED_IMPORTS = {
    'math', 'numpy', 'np', 'pandas', 'pd',
    'talib', 'ta', 'datetime', 'collections',
    'functools', 'itertools', 'operator',
    # 聚宽兼容：这些模块在沙箱中被 stub，不会实际导入
    'jqdata', 'jqlib',
}


def validate_code(code_str):
    """
    验证策略代码安全性。

    Args:
        code_str: Python 策略代码字符串

    Returns:
        (bool, str): (是否安全, 错误信息)
    """
    if not code_str or not code_str.strip():
        return False, "策略代码为空"

    # 检查禁止的模式
    for pattern in _FORBIDDEN_PATTERNS:
        match = re.search(pattern, code_str)
        if match:
            return False, f"策略代码包含禁止的操作: {match.group()}"

    # 检查导入语句（同时覆盖 import X 和 from X import Y）
    import_pattern = r'(?:^|\n)\s*(?:import|from)\s+(\w+)'
    for match in re.finditer(import_pattern, code_str):
        module = match.group(1)
        if module not in _ALLOWED_IMPORTS:
            return False, f"不允许导入模块: {module}（允许的模块: {', '.join(sorted(_ALLOWED_IMPORTS))}）"

    # 检查必要函数
    if 'def initialize' not in code_str:
        return False, "策略代码必须定义 initialize(context) 函数"

    # handle_data 可选：如果使用 run_daily 注册日级回调则不需要
    # if 'def handle_data' not in code_str:
    #     return False, "策略代码必须定义 handle_data(context, data) 函数"

    return True, ""


# ────────────────────────────────────────────────────────────────
# AST 强校验（AI 生成通道使用，比正则黑名单更难绕过）
# ────────────────────────────────────────────────────────────────

# 危险的内置/全局名（直接调用形式）
_AST_FORBIDDEN_NAMES = {
    '__import__', 'eval', 'exec', 'compile', 'open',
    'getattr', 'setattr', 'delattr', 'globals', 'locals', 'vars',
    'breakpoint', 'help', 'input',
}

# 危险的属性名（属性访问形式）—— 防止 ().__class__.__bases__[0].__subclasses__() 等
_AST_FORBIDDEN_ATTRS = {
    '__class__', '__bases__', '__subclasses__', '__mro__',
    '__dict__', '__globals__', '__code__', '__builtins__',
    '__loader__', '__spec__', '__import__',
    'f_locals', 'f_globals', 'gi_frame', 'cr_frame',
}


# ── 中文编码完整性检测（防 mojibake） ──────────────────────────
# 历史故障：OpenAI-compatible 供应商的 SSE 流响应若不声明 charset，
# requests 默认按 ISO-8859-1 解码，中文 UTF-8 字节被当 latin-1 字符串切片，
# 再次以 UTF-8 入库时会形成"å\x9fºæ\x9c¬"这种双重编码 mojibake。
# 即便流式解码层修好了，存量代码 / 其它来源的 mojibake 仍需在落库前拦截。
def _detect_mojibake(text):
    """检测疑似 UTF-8 → latin-1 双重编码 mojibake。

    Returns:
        str: 空字符串表示未检出；非空表示问题摘要。
    """
    if not text:
        return ''
    # 启发式 1：含有大量 latin-1 扩展区字符（U+0080-U+00FF）且无正常中文。
    bad = 0
    cjk = 0
    for ch in text:
        cp = ord(ch)
        if 0x80 <= cp <= 0xFF:
            bad += 1
        elif 0x4E00 <= cp <= 0x9FFF:
            cjk += 1
    if bad < 10:
        return ''
    # 启发式 2：尝试 latin-1 -> utf-8 反解，看能否还原出大量中文字符；
    # 能还原 → 几乎可确定是双重编码 mojibake。
    try:
        recovered = text.encode('latin-1', errors='strict').decode('utf-8', errors='strict')
    except (UnicodeEncodeError, UnicodeDecodeError):
        return ''
    recovered_cjk = sum(1 for ch in recovered if 0x4E00 <= ord(ch) <= 0x9FFF)
    if recovered_cjk >= 5 and recovered_cjk > cjk:
        sample = recovered[:60].replace('\n', ' ')
        return (f'检测到 UTF-8/latin-1 双重编码乱码（约 {bad} 个异常字符，'
                f'还原后含 {recovered_cjk} 个中文字符）。还原片段示例: "{sample}…"。'
                '请检查上游响应是否未声明 charset=utf-8。')
    return ''



def validate_code_strict(code_str):
    """
    AST 级强校验 — 适用于 AI 通道、外部用户输入等不可信来源。

    在 ``validate_code()`` 通过的基础上额外检查：
    - import / from-import 的模块必须在白名单内（AST 层，不可被字符串拼接绕过）
    - 任何属性访问中的属性名不得命中危险列表
    - 任何 Name/Call 中的标识符不得命中危险列表

    Returns:
        (bool, str): (是否安全, 错误信息)
    """
    ok, err = validate_code(code_str)
    if not ok:
        return ok, err

    # 中文 mojibake 拦截（注释 / docstring 双重编码会让用户读不懂、
    # 也可能让回测里的 log.info 输出错乱）。
    mojibake = _detect_mojibake(code_str)
    if mojibake:
        return False, mojibake

    try:
        tree = ast.parse(code_str)
    except SyntaxError as e:
        return False, f"策略代码语法错误 (行{e.lineno}): {e.msg}"

    for node in ast.walk(tree):
        # import X / import X.Y
        if isinstance(node, ast.Import):
            for alias in node.names:
                base = (alias.name or '').split('.')[0]
                if base and base not in _ALLOWED_IMPORTS:
                    return False, f"AST 拒绝导入模块: {alias.name}"
        # from X import ...
        elif isinstance(node, ast.ImportFrom):
            base = (node.module or '').split('.')[0]
            if base and base not in _ALLOWED_IMPORTS:
                return False, f"AST 拒绝导入模块: {node.module}"
        # foo.__class__.__bases__ 等
        elif isinstance(node, ast.Attribute):
            if node.attr in _AST_FORBIDDEN_ATTRS:
                return False, f"AST 拒绝属性访问: {node.attr}"
        # 直接引用危险标识符
        elif isinstance(node, ast.Name):
            if node.id in _AST_FORBIDDEN_NAMES:
                return False, f"AST 拒绝标识符: {node.id}"

    return True, ""


def compile_strategy(code_str):
    """
    编译策略代码，提取策略函数。

    Args:
        code_str: Python 策略代码字符串

    Returns:
        dict: {
            'initialize': callable,
            'handle_data': callable,
            'before_trading_start': callable or None,
            'after_trading_end': callable or None,
        }

    Raises:
        ValueError: 代码验证失败
        SyntaxError: Python 语法错误
    """
    # 安全验证
    ok, err = validate_code(code_str)
    if not ok:
        raise ValueError(f"策略代码验证失败: {err}")

    # 编译执行
    namespace = _create_safe_namespace()

    try:
        exec(compile(code_str, '<strategy>', 'exec'), namespace)
    except SyntaxError as e:
        raise SyntaxError(f"策略代码语法错误 (行{e.lineno}): {e.msg}")

    # 提取函数
    result = {}

    if 'initialize' not in namespace or not callable(namespace['initialize']):
        raise ValueError("未找到 initialize(context) 函数")
    result['initialize'] = namespace['initialize']

    # handle_data 可选 — 使用 run_daily 时可不定义
    if 'handle_data' in namespace and callable(namespace['handle_data']):
        result['handle_data'] = namespace['handle_data']
    else:
        result['handle_data'] = None

    result['before_trading_start'] = namespace.get('before_trading_start')
    result['after_trading_end'] = namespace.get('after_trading_end')

    return result


def _create_safe_namespace():
    """创建安全的执行命名空间"""
    import math
    import types

    # 创建 jqdata / jqlib stub 模块
    def _make_jq_stubs():
        jqdata = types.ModuleType('jqdata')
        jqdata.__all__ = []  # from jqdata import * 不导入任何内容

        jqlib = types.ModuleType('jqlib')
        jqlib_ta = types.ModuleType('jqlib.technical_analysis')
        # ATR stub — 返回空字典，策略中有手动 fallback
        jqlib_ta.ATR = lambda *args, **kwargs: {}
        jqlib.technical_analysis = jqlib_ta

        return {'jqdata': jqdata, 'jqlib': jqlib, 'jqlib.technical_analysis': jqlib_ta}

    _jq_modules = _make_jq_stubs()

    def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
        """安全的 __import__ — 仅允许白名单模块"""
        # 处理 jqdata / jqlib stub
        if name in _jq_modules:
            return _jq_modules[name]
        # 处理 jqlib.technical_analysis
        if name.startswith('jqlib.'):
            parts = name.split('.')
            if name in _jq_modules:
                return _jq_modules[name]
            # from jqlib.technical_analysis import ATR → name='jqlib', fromlist=('...',)
            return _jq_modules.get('jqlib', _jq_modules['jqlib'])

        # 允许白名单模块的真实导入
        base_module = name.split('.')[0]
        if base_module in _ALLOWED_IMPORTS:
            import builtins
            return builtins.__import__(name, globals, locals, fromlist, level)
        raise ImportError(f"沙箱不允许导入: {name}")

    ns = {
        '__builtins__': {
            # 安全的内置函数（移除 type 防止类层次遍历攻击）
            'abs': abs, 'all': all, 'any': any, 'bool': bool,
            'dict': dict, 'enumerate': enumerate, 'filter': filter,
            'float': float, 'frozenset': frozenset, 'hasattr': hasattr,
            'int': int, 'isinstance': isinstance, 'len': len, 'list': list,
            'map': map, 'max': max, 'min': min, 'print': print,
            'range': range, 'reversed': reversed, 'round': round,
            'set': set, 'slice': slice, 'sorted': sorted, 'str': str,
            'sum': sum, 'tuple': tuple, 'zip': zip,
            'True': True, 'False': False, 'None': None,
            'Exception': Exception, 'ValueError': ValueError,
            'TypeError': TypeError, 'KeyError': KeyError,
            'IndexError': IndexError, 'AttributeError': AttributeError,
            '__import__': _safe_import,
        },
        'math': math,
    }

    # 尝试注入可选库
    try:
        import numpy
        ns['numpy'] = numpy
        ns['np'] = numpy
    except ImportError:
        pass

    try:
        import pandas
        ns['pandas'] = pandas
        ns['pd'] = pandas
    except ImportError:
        pass

    try:
        import talib
        ns['talib'] = talib
    except ImportError:
        pass

    return ns
