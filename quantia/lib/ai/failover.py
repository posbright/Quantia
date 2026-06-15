#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI provider/model 故障转移（failover）。

用于定时任务等无人值守场景：当默认模型欠费 / 配额耗尽 / 不可用时，
自动切换到其它已配置的 provider/model 重试，避免整批任务因单一模型
故障而失败。

核心入口：
    run_agent_with_failover(*, overrides=None, fallback_chain=None,
                            on_failover=None, **run_agent_kwargs)
        - 按 fallback_chain（默认自动构建）依次尝试 run_agent；
        - 命中"可转移"错误（欠费 / 限流 / 上游不可用）→ 切换下一个 provider；
        - 命中不可转移错误（如输出校验失败 ValidationError）→ 立即抛出；
        - 全部尝试失败 → 抛出最后一个异常（调用方既有失败计数/熔断逻辑生效）。

故障转移链构建顺序（build_fallback_chain）：
    1) 调用方传入的 overrides（即当前默认配置）作为第 1 个尝试；
    2) 若设置了 QUANTIA_AI_FALLBACK_CHAIN（逗号分隔，支持 provider[:model]），
       按该顺序作为后续备用；
    3) 否则自动枚举 list_provider_profiles() 中其它已配置 API Key 的 provider
       （排除默认 provider，按字母序），各取其 default_model。
"""

import logging
import os
from typing import Any, Callable, Dict, List, Optional

from quantia.lib.ai.config import list_provider_profiles
from quantia.lib.ai.exceptions import AIError, ValidationError

__author__ = 'Quantia'
__date__ = '2026/05/15'

_logger = logging.getLogger('quantia.ai.failover')


def should_failover(exc: BaseException) -> bool:
    """判断异常是否值得切换到下一个 provider 重试。

    可转移（返回 True）：
        - RateLimitError：上游 429（配额耗尽 / 过载）—— 换一家通常可恢复；
        - ProviderError：上游 401/402/403（鉴权/欠费）、404（模型不存在）、
          5xx（服务端故障）、网络错误（已被 provider 层包装）等 —— 均换一家重试；
        - 其它 AIError：如 provider 解析失败 —— 兜底转移。
    不可转移（返回 False）：
        - ValidationError：模型输出/沙箱校验失败，换 provider 也无济于事；
        - 非 AIError（TypeError/KeyError 等程序/配置 bug）：provider 层已把所有
          上游与网络错误包装成 ProviderError/RateLimitError，故裸异常必然是真实
          bug，重试其它 provider 无意义且会掩盖问题 —— 立即抛出。
    """
    if isinstance(exc, ValidationError):
        return False
    return isinstance(exc, AIError)



def build_fallback_chain(
    base_overrides: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """构建 override 故障转移链。

    返回一个 override-dict 列表，列表[0] 为默认配置（base_overrides），
    其余为备用 provider。每个元素可直接作为 run_agent(overrides=...) 传入。
    """
    base: Dict[str, Any] = dict(base_overrides or {})
    chain: List[Dict[str, Any]] = [base]

    info = list_provider_profiles()
    default_name = (info.get('default') or 'default')
    profiles = info.get('profiles', []) or []
    by_name = {p.get('name'): p for p in profiles}

    # 第 1 个尝试用的 provider（用于在备用链中去重，避免重复尝试同一家）
    seen = {(base.get('provider') or default_name)}

    explicit = (os.environ.get('QUANTIA_AI_FALLBACK_CHAIN') or '').strip()
    ordered_tokens: List[str] = []
    if explicit:
        ordered_tokens = [t.strip() for t in explicit.split(',') if t.strip()]
    else:
        for p in profiles:
            name = p.get('name')
            if not name or name in ('default', default_name):
                continue
            if p.get('has_key'):
                ordered_tokens.append(name)

    for token in ordered_tokens:
        name, model = token, None
        if ':' in token:
            name, model = token.split(':', 1)
            name, model = name.strip(), model.strip()
        if not name or name in seen:
            continue
        prof = by_name.get(name)
        ov: Dict[str, Any] = {'provider': name}
        chosen_model = model or (prof.get('default_model') if prof else None)
        if chosen_model:
            ov['model'] = chosen_model
        chain.append(ov)
        seen.add(name)

    return chain


def run_agent_with_failover(
    *,
    overrides: Optional[Dict[str, Any]] = None,
    fallback_chain: Optional[List[Dict[str, Any]]] = None,
    on_failover: Optional[Callable[[Dict[str, Any], Dict[str, Any], BaseException], None]] = None,
    **run_agent_kwargs: Any,
):
    """run_agent 的故障转移封装。

    Args:
        overrides: 默认配置 override（首次尝试）。
        fallback_chain: 显式指定的尝试链；为 None 时自动调用 build_fallback_chain。
        on_failover: 可选回调 (failed_override, next_override, exc)，用于上报/统计。
        **run_agent_kwargs: 透传给 run_agent 的其余参数（user_message/scene/agent/...）。

    Returns:
        AgentRunResult —— 首个成功的 provider 返回结果。

    Raises:
        最后一个 provider 的异常（全部失败时），或不可转移错误（立即抛出）。
    """
    # 延迟导入，避免与 quantia.lib.ai.__init__ 形成循环导入
    from quantia.lib.ai import run_agent

    chain = fallback_chain if fallback_chain is not None else build_fallback_chain(overrides)
    if not chain:
        chain = [dict(overrides or {})]

    total = len(chain)
    last_exc: Optional[BaseException] = None

    for idx, ov in enumerate(chain):
        prov_label = (ov or {}).get('provider') or '<default>'
        try:
            result = run_agent(overrides=(ov or None), **run_agent_kwargs)
            if idx > 0:
                _logger.info(
                    '[AI failover] 已切换到备用 provider=%s model=%s 并成功生成',
                    prov_label, (ov or {}).get('model') or '<default>',
                )
            return result
        except Exception as exc:  # noqa: BLE001 —— 需按错误类型决定转移/抛出
            last_exc = exc
            is_last = idx >= total - 1
            if not should_failover(exc) or is_last:
                raise
            next_ov = chain[idx + 1]
            next_label = (next_ov or {}).get('provider') or '<default>'
            _logger.warning(
                '[AI failover] provider=%s 调用失败 (%s: %s)，切换到 provider=%s 重试',
                prov_label, type(exc).__name__, exc, next_label,
            )
            if on_failover is not None:
                try:
                    on_failover(ov, next_ov, exc)
                except Exception:  # noqa: BLE001 —— 回调异常不应中断转移
                    _logger.debug('[AI failover] on_failover 回调异常', exc_info=True)

    # 理论不可达（最后一次会在循环内 raise），兜底
    if last_exc is not None:
        raise last_exc
    raise AIError('run_agent_with_failover: 故障转移链为空')
