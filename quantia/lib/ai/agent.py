#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M6 AgentRuntime：function-calling 循环 + 工具调度。

工作流程：
    1. 构建 system + user 消息，附带 tools schemas（受 allowed_tools 过滤）
    2. provider.chat(messages, tools=...) → ChatResult
    3. 若 result.tool_calls 非空：
         - 对每个 tool_call 校验 allowed → 执行 → 把 tool_result 作为
           role='tool' 消息追加，并把 assistant 的 tool_calls 回放追加
         - 进入下一轮
       否则返回最终 content
    4. 累计 tools_used 用于审计

约束：
    - 最多 _MAX_ROUNDS 轮（默认 4，可被 QUANTIA_AI_AGENT_MAX_ROUNDS 覆盖）
    - 单个工具结果按字节截断 32 KB
    - tool_call.name 不在 allowed → 返回错误结果让 LLM 自行处理
"""

import json
import logging
import os
import time
import uuid
from typing import Any, Dict, Iterable, List, Optional

from quantia.lib.ai import audit
from quantia.lib.ai.config import AIConfig, load_config
from quantia.lib.ai.exceptions import AIError, ProviderError, RateLimitError
from quantia.lib.ai.providers.base import ChatMessage, ChatResult, Provider, ToolCall
from quantia.lib.ai.tools import ToolError, get_registry

__author__ = 'Quantia'
__date__ = '2026/05/11'

_DEFAULT_MAX_ROUNDS = 4
_MAX_TOOL_RESULT_BYTES = 32 * 1024


def _max_rounds() -> int:
    try:
        return max(1, int(os.environ.get('QUANTIA_AI_AGENT_MAX_ROUNDS', _DEFAULT_MAX_ROUNDS)))
    except (TypeError, ValueError):
        return _DEFAULT_MAX_ROUNDS


def _truncate_json(obj: Any) -> str:
    text = json.dumps(obj, ensure_ascii=False, default=str)
    encoded = text.encode('utf-8')
    if len(encoded) <= _MAX_TOOL_RESULT_BYTES:
        return text
    truncated = encoded[:_MAX_TOOL_RESULT_BYTES].decode('utf-8', errors='ignore')
    return truncated + '...[truncated]'


class AgentRunResult:
    def __init__(self, content: str, tool_calls: List[Dict[str, Any]],
                 rounds: int, model: str, provider: str,
                 prompt_tokens: int = 0, completion_tokens: int = 0,
                 total_tokens: int = 0, finish_reason: str = ''):
        self.content = content
        self.tool_calls = tool_calls  # [{'name', 'arguments', 'ok', 'result'/'error'}]
        self.rounds = rounds
        self.model = model
        self.provider = provider
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens
        self.finish_reason = finish_reason


class AgentRuntime:
    def __init__(self, provider: Provider, *, allowed_tools: Optional[Iterable[str]] = None):
        self.provider = provider
        self.allowed_tools = set(allowed_tools) if allowed_tools is not None else None
        self.registry = get_registry()

    def _tool_schemas(self) -> List[Dict[str, Any]]:
        return self.registry.schemas(self.allowed_tools)

    def _is_allowed(self, name: str) -> bool:
        if self.allowed_tools is None:
            return True
        return name in self.allowed_tools

    def _exec_tool(self, call: ToolCall) -> Dict[str, Any]:
        rec: Dict[str, Any] = {
            'name': call.name,
            'arguments': call.arguments,
            'ok': False,
        }
        if not self._is_allowed(call.name):
            rec['error'] = f'tool {call.name} not allowed'
            return rec
        tool = self.registry.get(call.name)
        if tool is None:
            rec['error'] = f'unknown tool: {call.name}'
            return rec
        try:
            result = tool.run(call.arguments or {})
            rec['ok'] = True
            rec['result'] = result
        except ToolError as exc:
            rec['error'] = f'ToolError: {exc}'
        except Exception as exc:
            logging.exception(f'[ai.agent] tool {call.name} 内部异常')
            rec['error'] = f'internal: {exc}'
        return rec

    def run(self, *, system: Optional[str], user_message: str,
            extra_messages: Optional[List[ChatMessage]] = None,
            **chat_kwargs) -> AgentRunResult:
        messages: List[ChatMessage] = []
        if system:
            messages.append(ChatMessage(role='system', content=system))
        if extra_messages:
            messages.extend(extra_messages)
        messages.append(ChatMessage(role='user', content=user_message))

        tool_schemas = self._tool_schemas()
        tools_used: List[Dict[str, Any]] = []
        rounds = 0
        last_result: Optional[ChatResult] = None
        max_rounds = _max_rounds()

        while rounds < max_rounds:
            rounds += 1
            kwargs = dict(chat_kwargs)
            if tool_schemas:
                kwargs.setdefault('tools', tool_schemas)
                kwargs.setdefault('tool_choice', 'auto')
            last_result = self.provider.chat(messages, **kwargs)
            if not last_result.tool_calls:
                break
            # P1-1（一轮审计）：某些 provider 可能不返回 tool_call.id，
            # 补上本地 UUID 避免后续请求中 tool_call_id 为空导致 400。
            for tc in last_result.tool_calls:
                if not tc.id:
                    tc.id = f'call_{uuid.uuid4().hex[:12]}'
            # 把 assistant 的 tool_calls 回放
            assistant_tool_calls = [
                {
                    'id': tc.id,
                    'type': 'function',
                    'function': {
                        'name': tc.name,
                        'arguments': json.dumps(tc.arguments, ensure_ascii=False),
                    },
                }
                for tc in last_result.tool_calls
            ]
            messages.append(ChatMessage(
                role='assistant',
                content=last_result.content or '',
                tool_calls=assistant_tool_calls,
            ))
            for tc in last_result.tool_calls:
                rec = self._exec_tool(tc)
                tools_used.append(rec)
                payload = rec.get('result') if rec['ok'] else {'error': rec.get('error')}
                messages.append(ChatMessage(
                    role='tool',
                    content=_truncate_json(payload),
                    tool_call_id=tc.id,
                    name=tc.name,
                ))
        if last_result is None:
            raise AIError('agent loop produced no result')

        # P1-2（一轮审计）：若 max_rounds 耗尽但最后一轮仍是 tool_calls，
        # 强制再调一次 chat（不带 tools）拿到最终文本回答，避免返回空 content。
        if last_result.tool_calls and rounds >= max_rounds:
            try:
                kwargs2 = dict(chat_kwargs)
                kwargs2.pop('tools', None)
                kwargs2.pop('tool_choice', None)
                final = self.provider.chat(messages, **kwargs2)
                last_result = final
            except Exception as exc:
                logging.warning(f'[ai.agent] 最终总结调用失败（保留原始空 content）: {exc}')

        return AgentRunResult(
            content=last_result.content or '',
            tool_calls=tools_used,
            rounds=rounds,
            model=getattr(self.provider.config, 'model', '') or '',
            provider=getattr(self.provider.config, 'provider', '') or '',
            prompt_tokens=last_result.prompt_tokens,
            completion_tokens=last_result.completion_tokens,
            total_tokens=last_result.total_tokens,
            finish_reason=last_result.finish_reason,
        )


def run_agent(
    *,
    user_message: str,
    scene: str = 'agent',
    agent: Optional[str] = None,
    system: Optional[str] = None,
    user_id: Optional[str] = None,
    overrides: Optional[Dict[str, Any]] = None,
    allowed_tools: Optional[Iterable[str]] = None,
    rate_limit_loop: bool = False,
    **chat_kwargs,
) -> AgentRunResult:
    """便捷入口。会写入审计 cn_stock_ai_call_log（含 tools_used）。

    rate_limit_loop=True 表示当前是修复闭环内部重试（spec §4.4），
    不计入 (user_id, scene) 滑窗配额。
    """
    from quantia.lib.ai import get_provider
    from quantia.lib.ai import rate_limiter
    cfg: AIConfig = load_config(overrides)
    rate_limiter.check_quota(
        user_id=user_id, scene=scene, rate_limit_loop=rate_limit_loop)
    provider = get_provider(cfg)
    runtime = AgentRuntime(provider, allowed_tools=allowed_tools)
    started = time.time()
    err_text: Optional[str] = None
    result: Optional[AgentRunResult] = None
    ok = False
    try:
        result = runtime.run(system=system, user_message=user_message, **chat_kwargs)
        ok = True
        return result
    except (ProviderError, RateLimitError, AIError) as exc:
        err_text = str(exc)
        raise
    except Exception as exc:
        err_text = str(exc)
        raise
    finally:
        latency_ms = int((time.time() - started) * 1000)
        try:
            audit.record_call(
                scene=scene,
                agent=agent,
                provider=cfg.provider,
                model=cfg.model,
                user_id=user_id,
                prompt=user_message,
                response=(result.content if result else ''),
                ok=ok,
                tools_used=([t for t in result.tool_calls] if result else None),
                prompt_tokens=(result.prompt_tokens if result else None),
                completion_tokens=(result.completion_tokens if result else None),
                total_tokens=(result.total_tokens if result else None),
                latency_ms=latency_ms,
                error=err_text,
                rate_limit_loop=rate_limit_loop,
            )
        except Exception as audit_exc:
            logging.warning(f'[ai.run_agent] 审计写入失败（忽略）: {audit_exc}')
