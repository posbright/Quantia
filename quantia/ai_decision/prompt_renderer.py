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
    "策略筛选阶段、事件风险上下文、账户与市场信息，请输出严格 JSON："
    '{"score":0-100,"action":"buy|sell|hold|skip|reduce|watch","confidence":0-1,'
    '"reason_summary":"...","evidence":[..],"risk_flags":[..],"threshold_result":{...}}。'
    "\n\n## 评分规则\n"
    "- 70分以上：建议执行买入\n"
    "- 50-70分：观望，等待确认信号\n"
    "- 50分以下：建议放弃/卖出\n\n"
    "## 以下情况直接低分（<30分）：\n"
    "- ST 预警 / 退市风险\n"
    "- 财务造假/重大违规公告\n"
    "- 业绩大幅下修（> -50%）\n"
    "- 实控人被调查/冻结\n"
    "- 连续多日主力大幅流出 + 利空新闻\n\n"
    "## 以下情况可加分（最高20分附加）：\n"
    "- 突破性技术/专利（与主营强相关）\n"
    "- 重大合同/政策利好（有具体金额/文件号）\n"
    "- 连续超预期财报 + 机构增持\n"
    "- 行业拐点确认（多公司同步受益）\n\n"
    "不允许使用未来数据；输出仅一个 JSON 对象，不带额外文本。"
)
_DEFAULT_USER_PROMPT_TEMPLATE = (
    "标的：{{ code }} {{ name }}\n"
    "决策日期：{{ decision_date }}，阶段：{{ decision_phase }}，方向：{{ direction }}\n"
    "指标摘要：{{ indicators }}\n"
    "筛选阶段：{{ selection }}\n"
    "账户上下文：{{ portfolio }}\n"
    "市场环境：{{ market }}\n"
    "\n## 风险事件\n{{ event_context.risk_events }}\n"
    "\n## 机会事件\n{{ event_context.opportunity_events }}\n"
    "\n## 近期公告\n{{ event_context.recent_announcements }}\n"
    "新闻情绪：{{ event_context.news_sentiment }}\n"
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
