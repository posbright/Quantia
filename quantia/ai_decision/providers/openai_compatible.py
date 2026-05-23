# -*- coding: utf-8 -*-
"""OpenAI 兼容 Chat Completions provider（HTTP，stdlib only）。

不引入 ``openai`` / ``httpx`` 依赖。timeout 由调用方传入；超时与
非 200 状态都会抛 ``RuntimeError``，由上层 ``service`` 决定 fallback / fail_closed。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional
from urllib import error as urlerror
from urllib import request as urlrequest

from . import BaseProvider


class OpenAICompatibleProvider(BaseProvider):
    name = "openai_compatible"

    def generate(
        self,
        *,
        messages: List[Dict[str, str]],
        model_name: Optional[str],
        base_url: Optional[str],
        api_key: Optional[str],
        temperature: float = 0.2,
        max_tokens: int = 2048,
        timeout_seconds: int = 20,
    ) -> str:
        if not base_url:
            raise RuntimeError("缺少 base_url")
        if not model_name:
            raise RuntimeError("缺少 model_name")
        if not api_key:
            raise RuntimeError("缺少 api_key（请配置环境变量并通过 api_key_ref 引用）")
        url = base_url.rstrip("/") + "/v1/chat/completions"
        payload = {
            "model": model_name,
            "messages": messages,
            "temperature": float(temperature),
            "max_tokens": int(max_tokens),
            "response_format": {"type": "json_object"},
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urlrequest.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json; charset=utf-8",
            },
            method="POST",
        )
        try:
            with urlrequest.urlopen(req, timeout=int(timeout_seconds)) as resp:
                body = resp.read()
        except urlerror.URLError as exc:
            raise RuntimeError(f"AI 请求失败: {exc}") from exc
        text = body.decode("utf-8", errors="replace")
        try:
            obj = json.loads(text)
            choices = obj.get("choices") or []
            if not choices:
                raise RuntimeError("AI 返回缺少 choices")
            content = choices[0].get("message", {}).get("content")
            if not content:
                raise RuntimeError("AI 返回 content 为空")
            usage = obj.get("usage") or {}
            return content, {
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
            }
        except Exception as exc:
            logging.warning("[ai_decision] 解析 OpenAI 兼容响应失败: %s", exc)
            raise RuntimeError(f"AI 响应解析失败: {exc}") from exc
