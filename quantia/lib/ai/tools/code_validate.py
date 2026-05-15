#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""code_validate 工具：调用 strategy_sandbox.validate_code_strict。"""

from typing import Any, Dict

from quantia.lib.ai.tools import Tool, ToolError

__author__ = 'Quantia'
__date__ = '2026/05/11'

_MAX_CODE_BYTES = 256 * 1024


class CodeValidateTool(Tool):
    name = 'code_validate'
    description = (
        '在沙箱中静态校验策略代码。返回 {ok: bool, error: str}；'
        'ok=true 表示通过严格沙箱（白名单 import + AST 检查）。'
    )
    parameters = {
        'type': 'object',
        'required': ['code'],
        'properties': {
            'code': {
                'type': 'string',
                'description': '完整的策略代码（含 def initialize / def handle_data 等）',
            },
        },
    }

    def run(self, args: Dict[str, Any]) -> Dict[str, Any]:
        code = args.get('code') or ''
        if not isinstance(code, str):
            raise ToolError('code 必须是字符串')
        if len(code.encode('utf-8')) > _MAX_CODE_BYTES:
            raise ToolError(f'代码超过 {_MAX_CODE_BYTES} 字节上限')
        try:
            from quantia.core.backtest.strategy_sandbox import validate_code_strict
            ok, err = validate_code_strict(code)
        except Exception as exc:
            raise ToolError(f'沙箱校验异常: {exc}') from exc
        return {'ok': bool(ok), 'error': err or ''}
