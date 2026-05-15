#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M10 内置编排预设。

§11.4 / §18-M10：strategy_analyst → strategy_coder → strategy_repairer。
默认 tester 步骤用 `validate_code_strict` 做静态校验闭环（最多 3 轮）。
"""

import logging
import re
from typing import Any, Dict

from quantia.lib.ai.orchestrator.pipeline import Pipeline, Step

__author__ = 'Quantia'
__date__ = '2026/05/12'


_PY_BLOCK_RE = re.compile(r'```(?:python|py)?\s*\n(.*?)```', re.DOTALL | re.IGNORECASE)


def _extract_python_block(text: str) -> str:
    """优先取第一个 ```python``` 代码块；没有则原样返回（去 markdown 围栏）。

    audit-fix-2-P2: 现在默认 prompt 要求输出裸 Python，所以多数情况走 fallback
    分支；保留围栏提取以兼容 LLM 仁心加围栏的情况。
    """
    if not text:
        return ''
    m = _PY_BLOCK_RE.search(text)
    if m:
        return m.group(1).strip()
    return text.strip()


def _tester_passes(output: str, ctx: Dict[str, Any]) -> bool:
    """tester 步骤的终止条件：strict 校验 OK 即通过。

    audit-fix-1-P1: 验证 **本轮输出**（tester 产出的修复后代码），而不是
    原始的 ctx['coder']——后者在 loop 重试期间永不更新，会导致任何修复
    都被误判为未通过。如果 tester 输出为空，回退到 ctx['coder']以充当
    'tester 没变动代码' 的语义。
    """
    code = _extract_python_block(output or '') or _extract_python_block(
        ctx.get('coder', '') or '')
    if not code:
        return False
    try:
        from quantia.core.backtest.strategy_sandbox import validate_code_strict
        ok, _msg = validate_code_strict(code)
        return bool(ok)
    except Exception as exc:
        logging.warning(f'[ai.orchestrator.presets] strict 校验异常视为不通过: {exc}')
        return False


# ── analyst → coder → tester（带最多 3 轮 self-fix）
# audit-fix-2-P2: 与 strategy_coder.md / strategy_repairer.md 一致，
# user_template 不再要求输出 Markdown 代码块（两者原本矛盾）。
# _extract_python_block 同时兼容裸代码与 ```python``` 围栏，作为兏底。
STRATEGY_PIPELINE = Pipeline([
    Step(
        name='analyst',
        agent='strategy_analyst',
        # 不写 user_template：直接用初始 input 作为问题
    ),
    Step(
        name='coder',
        agent='strategy_coder',
        user_template=(
            '需求：{input}\n\n'
            '已分析的思路与伪代码：\n{analyst}\n\n'
            '请严格按 sandbox 规范输出可执行 Python 代码（只输出源码，不要 Markdown 围栏与讲解）。'
        ),
    ),
    Step(
        name='tester',
        agent='strategy_repairer',
        user_template=(
            '请审查并在必要时修复下面的策略代码，使其通过沙箱静态校验。\n'
            '原始需求：{input}\n\n'
            '当前代码：\n{coder}\n\n'
            '只输出最终的完整 Python 源码（不要 Markdown 围栏与讲解）。'
        ),
        loop_until=_tester_passes,
        max_iters=3,
    ),
])


__all__ = ['STRATEGY_PIPELINE']
