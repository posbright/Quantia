"""
硬规则表达式安全沙箱（用户可自由编辑硬规则 — 决策 #4）。

设计目标：
1. 用户输入 Python 表达式，例如：
       (d['rsi14'] < 30) & (d['close'] > d['boll_lower']) & (d['volume'] > d['vol_ma5'] * 1.2)
2. 解析并求值，返回 pd.Series[bool]
3. 严格 AST 白名单：禁止 import / 函数定义 / 任何 dunder / Lambda / 文件操作
4. 错误友好化：把 NameError/SyntaxError 翻译成中文提示

允许的 AST 节点（白名单）：
    Module, Expression, Expr, Compare, BoolOp, BinOp, UnaryOp,
    Subscript, Index (py<3.9 兼容), Slice, Name, Constant, Attribute (限白名单),
    Call (限白名单方法), Tuple, List
允许的函数 / 方法：
    Series 链式：rolling/mean/std/sum/max/min/shift/abs/diff/clip/fillna
    内建：min, max, abs, len
    np / pd 子集：np.sign, np.where, np.nan
"""
from __future__ import annotations

import ast
from typing import Any

import numpy as np
import pandas as pd


class SecurityError(Exception):
    """规则违反沙箱安全策略。"""


class RuleEvalError(Exception):
    """规则求值失败（用户友好消息）。"""


# AST 节点白名单（除了下面这些，其他都拒绝）
_ALLOWED_NODES = {
    ast.Module, ast.Expression, ast.Expr, ast.Load,
    ast.Compare, ast.BoolOp, ast.BinOp, ast.UnaryOp,
    ast.Subscript, ast.Slice, ast.Name, ast.Constant, ast.Attribute,
    ast.Call, ast.Tuple, ast.List, ast.keyword,
    # 操作符
    ast.And, ast.Or, ast.Not, ast.Invert,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
    ast.BitAnd, ast.BitOr, ast.BitXor, ast.USub, ast.UAdd,
}

# Python 3.8 兼容
if hasattr(ast, "Index"):
    _ALLOWED_NODES.add(ast.Index)

# Series/DataFrame 允许的方法名
_ALLOWED_METHODS = {
    "rolling", "ewm", "mean", "std", "sum", "max", "min", "median", "quantile",
    "shift", "abs", "diff", "clip", "fillna", "between",
    "cumsum", "cummax", "cummin", "rank", "pct_change", "round",
    "isna", "notna", "astype",
}

# Attribute 允许的根名（只允许 d.xxx, np.xxx, pd.xxx）
_ALLOWED_ATTR_ROOTS = {"d", "np", "pd"}

# np / pd 允许的属性
_ALLOWED_NP_ATTRS = {"sign", "where", "nan", "inf", "abs", "log", "log1p", "sqrt", "maximum", "minimum"}
_ALLOWED_PD_ATTRS = {"NA", "NaT", "Series"}

# Builtins 暴露的安全子集
_SAFE_BUILTINS = {
    "min": min, "max": max, "abs": abs, "len": len,
    "True": True, "False": False, "None": None,
}


def _check_ast(tree: ast.AST) -> None:
    """递归检查所有节点必须在白名单中。"""
    for node in ast.walk(tree):
        if type(node) not in _ALLOWED_NODES:
            raise SecurityError(
                f"禁止使用语法 `{type(node).__name__}`（仅允许比较 / 算术 / 布尔运算 / 列访问 / 已注册方法调用）"
            )

        # Name 检查：禁止双下划线 (__xxx)
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            raise SecurityError(f"禁止使用双下划线名称：{node.id}")

        # Attribute 检查：禁止 dunder + 限制方法白名单
        if isinstance(node, ast.Attribute):
            if node.attr.startswith("__"):
                raise SecurityError(f"禁止访问双下划线属性：.{node.attr}")
            # 允许：d['xxx'].rolling(...).mean() 这样的链式
            # 禁止：os.system / subprocess.call 等
            # 简单规则：方法名必须在白名单 OR 顶层 attr (np.xxx / pd.xxx)
            if isinstance(node.value, ast.Name):
                if node.value.id == "np" and node.attr not in _ALLOWED_NP_ATTRS:
                    raise SecurityError(f"禁止访问 np.{node.attr}")
                if node.value.id == "pd" and node.attr not in _ALLOWED_PD_ATTRS:
                    raise SecurityError(f"禁止访问 pd.{node.attr}")
                if node.value.id == "d":
                    raise SecurityError(
                        f"请用 d['列名'] 访问 DataFrame，不要用 d.{node.attr}"
                    )
            elif node.attr not in _ALLOWED_METHODS:
                raise SecurityError(f"禁止调用方法：.{node.attr}（白名单见文档）")

        # Call 检查：函数必须是已注册的
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id not in _SAFE_BUILTINS:
                raise SecurityError(f"禁止调用函数：{func.id}()")
            # Attribute 调用已在 Attribute 检查中处理


def parse_hard_rules(expr: str) -> ast.Expression:
    """
    解析用户表达式 → 已验证的 AST。
    raise SecurityError 如果违反沙箱规则。
    raise RuleEvalError 如果语法错误。
    """
    if not isinstance(expr, str) or not expr.strip():
        raise RuleEvalError("规则表达式不能为空")
    if "__" in expr:
        raise SecurityError("禁止使用双下划线（`__`）")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise RuleEvalError(f"语法错误：{e.msg}（第 {e.lineno or 1} 行第 {e.offset or 0} 列）") from e
    _check_ast(tree)
    return tree


def eval_hard_rules(expr: str, d: pd.DataFrame) -> pd.Series:
    """
    解析 + 在受限作用域内求值，返回布尔 Series。

    可用绑定：
      d  : 已 enrich 的 DataFrame
      np : numpy 安全子集
      pd : pandas 安全子集
      min/max/abs/len : 安全 builtins
    """
    tree = parse_hard_rules(expr)
    code = compile(tree, "<hard_rules>", "eval")
    safe_globals = {"__builtins__": _SAFE_BUILTINS}
    safe_locals = {"d": d, "np": np, "pd": pd}
    try:
        result = eval(code, safe_globals, safe_locals)  # noqa: S307 - intentional sandbox
    except KeyError as e:
        raise RuleEvalError(f"未知字段：d[{e}]，请从右侧字段面板选择") from e
    except NameError as e:
        raise RuleEvalError(f"未知变量：{e}，仅允许 d/np/pd") from e
    except Exception as e:
        raise RuleEvalError(f"求值失败：{type(e).__name__}: {e}") from e

    if not isinstance(result, pd.Series):
        raise RuleEvalError(
            f"规则必须返回 pd.Series[bool]，实际返回 {type(result).__name__}"
        )
    return result.fillna(False).astype(bool)


__all__ = ["SecurityError", "RuleEvalError", "parse_hard_rules", "eval_hard_rules"]
