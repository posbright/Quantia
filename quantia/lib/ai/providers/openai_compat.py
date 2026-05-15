#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OpenAI 兼容 Provider：覆盖 OpenAI / DeepSeek / Qwen / Kimi / vLLM / Ollama 等。

零新增依赖：使用项目已存在的 `requests`。
"""

import json
import logging
import re
from typing import Iterator, List

import requests

from quantia.lib.ai.exceptions import ProviderError, RateLimitError
from quantia.lib.ai.providers.base import ChatMessage, ChatResult, Provider, ToolCall

__author__ = 'Quantia'
__date__ = '2026/05/11'

# C2：异常消息中可能回显请求头/凭证 → 在外抛前做正则脱敏
# 覆盖：Bearer xxx / sk-xxx / api_key=xxx / x-api-key: xxx / ?key=xxx
_SECRET_RE = re.compile(
    r'(Bearer\s+[A-Za-z0-9._\-]{8,}'
    r'|sk-[A-Za-z0-9._\-]{8,}'
    r'|(?:x-)?api[_-]?key["\']?\s*[:=]\s*["\']?[A-Za-z0-9._\-]{8,}'
    r'|[?&]key=[A-Za-z0-9._\-]{8,})',
    re.IGNORECASE,
)


def _scrub(text: str) -> str:
    if not text:
        return text
    return _SECRET_RE.sub('[REDACTED]', text)


def _is_overloaded_429(body: str) -> bool:
    """识别上游 429 是否属于"模型过载"语义而非"配额超限"。

    Moonshot / Kimi: {"error":{"type":"engine_overloaded_error", ...}}
    OpenAI:          status=503 居多，但偶有 429 + "overloaded"/"server is busy"。
    DeepSeek:        message 含 "currently overloaded" / "server is busy"。

    严格匹配：仅当 body 包含明确"过载"关键字时才视为 overloaded，
    避免把真正的"用户配额超限"误判成可重试错误。
    """
    if not body:
        return False
    low = body.lower()
    return (
        'engine_overloaded' in low
        or 'overloaded' in low
        or 'server is busy' in low
        or 'currently overloaded' in low
        or 'try again later' in low and 'rate' not in low
    )


class OpenAICompatProvider(Provider):
    name = 'openai_compat'

    def _headers(self):
        h = {'Content-Type': 'application/json'}
        if self.config.api_key:
            h['Authorization'] = f'Bearer {self.config.api_key}'
        return h

    def _build_payload(self, messages: List[ChatMessage], **kwargs) -> dict:
        payload = {
            'model': kwargs.get('model') or self.config.model,
            'messages': [
                {k: v for k, v in {
                    'role': m.role,
                    'content': m.content,
                    'name': m.name,
                    'tool_call_id': m.tool_call_id,
                    'tool_calls': m.tool_calls,
                }.items() if v is not None}
                for m in messages
            ],
            'temperature': kwargs.get('temperature', self.config.temperature),
            'max_tokens': kwargs.get('max_tokens', self.config.max_tokens),
        }
        # 透传扩展字段（tools/tool_choice/response_format 等）
        for k in ('tools', 'tool_choice', 'response_format', 'top_p', 'stop'):
            if k in kwargs and kwargs[k] is not None:
                payload[k] = kwargs[k]
        return payload

    def chat(self, messages: List[ChatMessage], **kwargs) -> ChatResult:
        url = f"{self.config.api_base.rstrip('/')}/chat/completions"
        payload = self._build_payload(messages, **kwargs)
        # 上游过载 (engine_overloaded_error 等) 自动指数退避重试 —— 这种错误
        # 是 provider 服务器繁忙、非用户配额超限，重试通常能恢复。
        # 仅对"明确过载语义"的 429 / 5xx 重试，其余直接抛 RateLimitError(overloaded=False)。
        import time as _time
        max_retries = int(kwargs.get('overload_retries', 2))
        backoffs = (1.0, 2.5)  # 秒；最多 2 次重试 ≈ 总等待 3.5s
        last_429_body = ''
        for attempt in range(max_retries + 1):
            try:
                resp = requests.post(
                    url, headers=self._headers(), json=payload,
                    timeout=kwargs.get('timeout', self.config.timeout),
                )
            except requests.RequestException as exc:
                raise ProviderError(f'网络错误: {_scrub(str(exc))}') from exc

            if resp.status_code == 429:
                body = resp.text[:500]
                overloaded = _is_overloaded_429(body)
                last_429_body = body
                if overloaded and attempt < max_retries:
                    logging.warning(
                        f'[ai] 上游过载 (429 engine_overloaded), '
                        f'第 {attempt+1}/{max_retries} 次重试，'
                        f'{backoffs[attempt]}s 后再试'
                    )
                    _time.sleep(backoffs[attempt])
                    continue
                raise RateLimitError(
                    f'上游 429: {_scrub(body[:200])}',
                    overloaded=overloaded,
                )
            if resp.status_code in (502, 503, 504) and attempt < max_retries:
                logging.warning(
                    f'[ai] 上游 {resp.status_code}（瞬时不可用），'
                    f'第 {attempt+1}/{max_retries} 次重试，'
                    f'{backoffs[attempt]}s 后再试'
                )
                _time.sleep(backoffs[attempt])
                continue
            break

        if resp.status_code >= 400:
            raise ProviderError(
                f'HTTP {resp.status_code}',
                status_code=resp.status_code,
                body=_scrub(resp.text[:500]),
            )

        try:
            data = resp.json()
        except ValueError as exc:
            raise ProviderError(f'非 JSON 响应: {resp.text[:200]}') from exc

        try:
            choice = data['choices'][0]
            message = choice.get('message') or {}
            content = message.get('content') or ''
            finish_reason = choice.get('finish_reason') or ''
            # M6：解析 tool_calls（OpenAI 函数调用协议）
            tool_calls: List[ToolCall] = []
            for tc in (message.get('tool_calls') or []):
                func = tc.get('function') or {}
                args_raw = func.get('arguments') or '{}'
                if isinstance(args_raw, str):
                    try:
                        args = json.loads(args_raw)
                    except (ValueError, TypeError):
                        args = {'_raw': args_raw}
                else:
                    args = dict(args_raw) if isinstance(args_raw, dict) else {}
                tool_calls.append(ToolCall(
                    id=str(tc.get('id') or ''),
                    name=str(func.get('name') or ''),
                    arguments=args,
                ))
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f'响应结构异常: {str(data)[:200]}') from exc

        usage = data.get('usage') or {}
        return ChatResult(
            content=content,
            prompt_tokens=int(usage.get('prompt_tokens') or 0),
            completion_tokens=int(usage.get('completion_tokens') or 0),
            total_tokens=int(usage.get('total_tokens') or 0),
            finish_reason=finish_reason,
            raw=data,
            tool_calls=tool_calls,
        )

    def stream(self, messages: List[ChatMessage], **kwargs) -> Iterator[str]:
        url = f"{self.config.api_base.rstrip('/')}/chat/completions"
        payload = self._build_payload(messages, **kwargs)
        payload['stream'] = True
        try:
            # 使用 with 确保消费者中途异常 / GeneratorExit 时连接被释放（B4）
            resp = requests.post(
                url, headers=self._headers(), json=payload, stream=True,
                timeout=kwargs.get('timeout', self.config.timeout),
            )
        except requests.RequestException as exc:
            raise ProviderError(f'网络错误: {_scrub(str(exc))}') from exc

        try:
            if resp.status_code == 429:
                body = resp.text[:500]
                raise RateLimitError(
                    f'上游 429: {_scrub(body[:200])}',
                    overloaded=_is_overloaded_429(body),
                )
            if resp.status_code >= 400:
                raise ProviderError(
                    f'HTTP {resp.status_code}',
                    status_code=resp.status_code,
                    body=_scrub(resp.text[:500]),
                )

            # 关键：OpenAI 兼容供应商（Moonshot/DeepSeek/...）的 SSE 响应往往不
            # 声明 charset，requests 默认按 ISO-8859-1 解码 text/event-stream，
            # 中文会变成 latin-1 字节再被前端/DB 当 UTF-8 存入，导致双重编码
            # mojibake（如 "基本面" → "å\x9fºæ\x9c¬é\x9d¢"）。
            # 这里强制 utf-8 解码，与非流式 chat() 路径的 resp.json() 行为一致。
            resp.encoding = 'utf-8'

            for raw_line in resp.iter_lines(decode_unicode=True):
                if not raw_line:
                    continue
                line = raw_line.strip()
                if not line.startswith('data:'):
                    continue
                payload_str = line[5:].strip()
                if payload_str == '[DONE]':
                    break
                try:
                    chunk = json.loads(payload_str)
                    delta = (chunk.get('choices', [{}])[0].get('delta') or {})
                    piece = delta.get('content')
                    if piece:
                        yield piece
                except Exception as exc:
                    logging.debug(f"[ai.openai_compat] 流式解析失败: {exc}")
                    continue
        except requests.RequestException as exc:
            # P0-E2：迭代过程中网络异常也需脱敏后再外抛
            raise ProviderError(f'流式读取失败: {_scrub(str(exc))}') from exc
        finally:
            # 无论正常 break / 早退 / 异常，都关闭底层连接
            try:
                resp.close()
            except Exception:
                pass
