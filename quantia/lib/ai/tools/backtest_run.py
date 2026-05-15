#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""backtest_run 工具：在独立子进程中跑一段最近交易日的 dry-run 回测。

Windows-compatible：使用 multiprocessing.Process + terminate()，不依赖 SIGALRM。
输出按字节截断 8 KB。
"""

import os
import sys
import json
import multiprocessing
import tempfile
from typing import Any, Dict

from quantia.lib.ai.tools import Tool, ToolError

__author__ = 'Quantia'
__date__ = '2026/05/11'

_DEFAULT_TIMEOUT_SEC = 10
_MAX_TIMEOUT_SEC = 30
_MAX_OUTPUT_BYTES = 8 * 1024
_MAX_CODE_BYTES = 256 * 1024


def _dryrun_worker(code: str, days: int, output_path: str) -> None:
    """在子进程中运行：仅做 strategy_sandbox.run_dryrun（如可用），否则做 validate。
    结果写入 output_path（json）。
    """
    result: Dict[str, Any] = {'ok': False, 'error': '', 'output': ''}
    try:
        from quantia.core.backtest.strategy_sandbox import validate_code_strict
        ok, err = validate_code_strict(code)
        result['validated'] = bool(ok)
        result['validation_error'] = err or ''
        if not ok:
            result['ok'] = False
            result['error'] = f'sandbox validation failed: {err}'
        else:
            # 尝试调用 dry-run（如可用）；不可用则仅返回 validation 通过
            try:
                from quantia.core.backtest import strategy_sandbox as _ss
                runner = getattr(_ss, 'run_dryrun', None) or getattr(_ss, 'dry_run', None)
                if callable(runner):
                    out = runner(code, days=days)
                    result['ok'] = True
                    result['output'] = str(out)[:_MAX_OUTPUT_BYTES]
                else:
                    result['ok'] = True
                    result['output'] = '(no dry-run available; validation only)'
            except Exception as exc:
                result['ok'] = False
                result['error'] = f'dry-run exception: {exc}'
    except Exception as exc:
        result['ok'] = False
        result['error'] = f'worker exception: {exc}'
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False)
    except Exception:
        pass


class BacktestRunTool(Tool):
    name = 'backtest_run'
    description = (
        '在独立子进程中跑一段最近交易日的策略 dry-run（可被父进程在超时后强杀）。'
        '不会写入数据库；返回 {ok, output, error}。'
    )
    parameters = {
        'type': 'object',
        'required': ['code'],
        'properties': {
            'code': {
                'type': 'string',
                'description': '完整策略代码',
            },
            'days': {
                'type': 'integer',
                'description': 'dry-run 覆盖的最近交易日天数（默认 30，最大 90）',
                'minimum': 5,
                'maximum': 90,
            },
            'timeout': {
                'type': 'integer',
                'description': f'子进程最大执行秒数（默认 {_DEFAULT_TIMEOUT_SEC}，最大 {_MAX_TIMEOUT_SEC}）',
                'minimum': 1,
                'maximum': _MAX_TIMEOUT_SEC,
            },
        },
    }

    def run(self, args: Dict[str, Any]) -> Dict[str, Any]:
        code = args.get('code') or ''
        if not isinstance(code, str) or not code.strip():
            raise ToolError('code 不能为空')
        if len(code.encode('utf-8')) > _MAX_CODE_BYTES:
            raise ToolError(f'代码超过 {_MAX_CODE_BYTES} 字节上限')
        try:
            days = int(args.get('days') or 30)
            timeout = int(args.get('timeout') or _DEFAULT_TIMEOUT_SEC)
        except (TypeError, ValueError):
            raise ToolError('days/timeout 必须是整数')
        days = max(5, min(90, days))
        timeout = max(1, min(_MAX_TIMEOUT_SEC, timeout))

        tmp = tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False, encoding='utf-8')
        tmp.close()
        proc = multiprocessing.Process(
            target=_dryrun_worker, args=(code, days, tmp.name))
        proc.start()
        proc.join(timeout)
        if proc.is_alive():
            proc.terminate()
            proc.join(2)
            if proc.is_alive():
                try:
                    proc.kill()
                except Exception:
                    pass
            try:
                os.unlink(tmp.name)
            except Exception:
                pass
            return {
                'ok': False,
                'error': f'timeout after {timeout}s; process terminated',
                'output': '',
            }
        try:
            with open(tmp.name, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as exc:
            data = {'ok': False, 'error': f'读取子进程结果失败: {exc}', 'output': ''}
        finally:
            try:
                os.unlink(tmp.name)
            except Exception:
                pass
        # 输出截断
        if isinstance(data.get('output'), str) and len(data['output'].encode('utf-8')) > _MAX_OUTPUT_BYTES:
            data['output'] = data['output'].encode('utf-8')[:_MAX_OUTPUT_BYTES].decode('utf-8', errors='ignore') + '...[truncated]'
        return data
