# -*- coding: utf-8 -*-
"""Provider 抽象。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


class BaseProvider:
    """所有 provider 子类需实现 ``generate`` 返回原始响应字符串。"""

    name = "base"

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
        raise NotImplementedError
