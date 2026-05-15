#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI: python -m quantia.lib.ai "你好" 或 python -m quantia.lib.ai --stream "..."

完整参数：
    --provider openai_compat
    --api-base https://api.deepseek.com/v1
    --api-key sk-xxx
    --model gpt-4o-mini
    --system "你是策略助手"
    --scene general
    --temperature 0.3
    --max-tokens 2000
    --stream
    [prompt]
"""

import argparse
import sys
from typing import Optional

__author__ = 'Quantia'
__date__ = '2026/05/11'


def _parse_args(argv: Optional[list] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog='python -m quantia.lib.ai',
        description='Quantia 统一 AI 服务命令行工具。',
    )
    p.add_argument('prompt', nargs='?', default=None, help='用户提示词；省略则从 stdin 读取')
    p.add_argument('--provider', default=None)
    p.add_argument('--api-base', dest='api_base', default=None)
    p.add_argument('--api-key', dest='api_key', default=None)
    p.add_argument('--model', default=None)
    p.add_argument('--system', default=None, help='system prompt')
    p.add_argument('--scene', default='cli')
    p.add_argument('--agent', default=None)
    p.add_argument('--temperature', type=float, default=None)
    p.add_argument('--max-tokens', dest='max_tokens', type=int, default=None)
    p.add_argument('--timeout', type=int, default=None)
    p.add_argument('--stream', action='store_true', help='流式输出')
    return p.parse_args(argv)


def _build_overrides(args: argparse.Namespace) -> dict:
    keys = ('provider', 'api_base', 'api_key', 'model', 'temperature', 'max_tokens', 'timeout')
    return {k: getattr(args, k) for k in keys if getattr(args, k) is not None}


def main(argv: Optional[list] = None) -> int:
    args = _parse_args(argv)
    prompt = args.prompt
    if prompt is None:
        prompt = sys.stdin.read().strip()
    if not prompt:
        print('错误：未提供 prompt（参数或 stdin 均为空）', file=sys.stderr)
        return 2

    # 延迟 import 避免 --help 时也加载 DB / dotenv
    from quantia.lib.ai import run_chat, stream_chat

    overrides = _build_overrides(args)
    try:
        if args.stream:
            for piece in stream_chat(
                prompt, scene=args.scene, system=args.system,
                agent=args.agent, overrides=overrides,
            ):
                sys.stdout.write(piece)
                sys.stdout.flush()
            sys.stdout.write('\n')
        else:
            text = run_chat(
                prompt, scene=args.scene, system=args.system,
                agent=args.agent, overrides=overrides,
            )
            print(text)
        return 0
    except Exception as exc:
        print(f'AI 调用失败: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
