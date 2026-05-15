# -*- coding: utf-8 -*-
"""Prompt 模板渲染 + 哈希。

支持 ``{{ var }}`` 风格的简易模板（不引入 jinja2 依赖以避免增加供应链面）。
不支持的 placeholder 会保持原样 + warning，避免静默吞掉错误。
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

_PLACEHOLDER_RE = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_\.]*)\s*}}")


def _resolve_path(ctx: Dict[str, Any], dotted: str):
    cur: Any = ctx
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _render_template(tpl: str, ctx: Dict[str, Any]) -> str:
    if not tpl:
        return ""

    def repl(m: re.Match) -> str:
        key = m.group(1)
        v = _resolve_path(ctx, key)
        if v is None:
            return m.group(0)  # 保留原 placeholder 便于调试
        if isinstance(v, (dict, list)):
            try:
                return json.dumps(v, ensure_ascii=False, default=str)
            except Exception:
                return str(v)
        return str(v)

    return _PLACEHOLDER_RE.sub(repl, tpl)


_DEFAULT_SYSTEM_PROMPT = (
    "你是一位严谨的 A 股短线辅助研判助手。给定股票当前可见的指标快照、"
    "策略筛选阶段、账户与市场上下文，请输出严格 JSON："
    '{"score":0-100,"action":"buy|sell|hold|skip|reduce|watch","confidence":0-1,'
    '"reason_summary":"...","evidence":[..],"risk_flags":[..],"threshold_result":{...}}。'
    "不允许使用未来数据；输出仅一个 JSON 对象，不带额外文本。"
)
_DEFAULT_USER_PROMPT_TEMPLATE = (
    "标的：{{ code }} {{ name }}\n"
    "决策日期：{{ decision_date }}，阶段：{{ decision_phase }}，方向：{{ direction }}\n"
    "指标摘要：{{ indicators }}\n"
    "筛选阶段：{{ selection }}\n"
    "账户上下文：{{ portfolio }}\n"
)


def render_messages(
    *,
    system_prompt: Optional[str],
    user_prompt_template: Optional[str],
    input_summary: Dict[str, Any],
) -> List[Dict[str, str]]:
    """返回 OpenAI 兼容 messages 数组。"""
    sys_text = (system_prompt or _DEFAULT_SYSTEM_PROMPT).strip()
    user_tpl = (user_prompt_template or _DEFAULT_USER_PROMPT_TEMPLATE)
    try:
        user_text = _render_template(user_tpl, input_summary or {})
    except Exception as exc:
        logging.warning("[ai_decision] prompt 渲染失败，使用原模板: %s", exc)
        user_text = user_tpl
    return [
        {"role": "system", "content": sys_text},
        {"role": "user", "content": user_text},
    ]


def compute_prompt_hash(messages: List[Dict[str, str]]) -> str:
    raw = json.dumps(messages, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
