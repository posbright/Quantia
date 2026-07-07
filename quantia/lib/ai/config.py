#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 服务层配置：三层合并 (.env ← cn_stock_strategy_params.ai_model ← request overrides)。

读取顺序（高 → 低）：
  1. 调用方 overrides（dict 参数）
  2. 数据库 ai_model 组（用户在策略参数页设置）
  3. 环境变量（QUANTIA_AI_*）
  4. 代码默认值
"""

import logging
from dataclasses import dataclass, asdict, field
from typing import Any, Dict, Optional

import quantia.lib.envconfig as _cfg

__author__ = 'Quantia'
__date__ = '2026/05/11'


# ── 默认值 ──
_DEFAULT_PROVIDER = 'openai_compat'
_DEFAULT_API_BASE = 'https://api.openai.com/v1'
_DEFAULT_MODEL = 'gpt-4o-mini'
_DEFAULT_TEMPERATURE = 0.3
_DEFAULT_MAX_TOKENS = 2000
_DEFAULT_TIMEOUT = 60


@dataclass
class AIConfig:
    """单次 AI 调用所需的运行时配置。"""

    provider: str = _DEFAULT_PROVIDER
    api_base: str = _DEFAULT_API_BASE
    api_key: str = ''
    model: str = _DEFAULT_MODEL
    temperature: float = _DEFAULT_TEMPERATURE
    max_tokens: int = _DEFAULT_MAX_TOKENS
    timeout: int = _DEFAULT_TIMEOUT
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _load_from_env() -> Dict[str, Any]:
    """从环境变量读取（最低优先级层之一）。

    G1：兼容文档 §4.2 的 `QUANTIA_AI_DEFAULT_*` 命名；优先取
    `QUANTIA_AI_*`，回退到 `QUANTIA_AI_DEFAULT_*`。
    """
    def _str(name: str) -> str:
        v = _cfg.get_str(name, '')
        if v:
            return v
        return _cfg.get_str(name.replace('QUANTIA_AI_', 'QUANTIA_AI_DEFAULT_', 1), '')

    out: Dict[str, Any] = {}
    provider = _str('QUANTIA_AI_PROVIDER')
    if provider:
        out['provider'] = provider
    api_base = _str('QUANTIA_AI_API_BASE')
    if api_base:
        out['api_base'] = api_base
    api_key = _str('QUANTIA_AI_API_KEY')
    if api_key:
        out['api_key'] = api_key
    model = _str('QUANTIA_AI_MODEL')
    if model:
        out['model'] = model
    env = _envkeys()
    if 'QUANTIA_AI_TEMPERATURE' in env or 'QUANTIA_AI_DEFAULT_TEMPERATURE' in env:
        key = 'QUANTIA_AI_TEMPERATURE' if 'QUANTIA_AI_TEMPERATURE' in env else 'QUANTIA_AI_DEFAULT_TEMPERATURE'
        out['temperature'] = _cfg.get_float(key, _DEFAULT_TEMPERATURE)
    if 'QUANTIA_AI_MAX_TOKENS' in env or 'QUANTIA_AI_DEFAULT_MAX_TOKENS' in env:
        key = 'QUANTIA_AI_MAX_TOKENS' if 'QUANTIA_AI_MAX_TOKENS' in env else 'QUANTIA_AI_DEFAULT_MAX_TOKENS'
        out['max_tokens'] = _cfg.get_int(key, _DEFAULT_MAX_TOKENS)
    if 'QUANTIA_AI_TIMEOUT' in env or 'QUANTIA_AI_DEFAULT_TIMEOUT' in env:
        key = 'QUANTIA_AI_TIMEOUT' if 'QUANTIA_AI_TIMEOUT' in env else 'QUANTIA_AI_DEFAULT_TIMEOUT'
        out['timeout'] = _cfg.get_int(key, _DEFAULT_TIMEOUT)
    return out


def _envkeys():
    import os
    return os.environ


def _has_real_api_key(value: str) -> bool:
    """Return False for empty or template placeholder API keys."""
    raw = (value or '').strip()
    if not raw:
        return False
    low = raw.lower()
    placeholder_tokens = (
        'your_', 'your-', 'your ', 'replace_me', 'placeholder',
        'xxx', '你的真实key', '你的真实', '填入', '示例',
    )
    return not any(token in low for token in placeholder_tokens)


def _load_from_db() -> Dict[str, Any]:
    """从 cn_stock_strategy_params 的 ai_model 组读取。

    复用现有 strategyParamsHandler.get_strategy_params。失败时返回空 dict（不阻断）。
    """
    out: Dict[str, Any] = {}
    try:
        from quantia.web.strategyParamsHandler import get_strategy_params
        params = get_strategy_params('ai_model')
    except Exception as exc:
        logging.debug(f"[ai.config] 读取 ai_model 组失败（首次启动属正常）: {exc}")
        return out
    if not params:
        return out
    values: Dict[str, Any] = {}
    for group in params.get('groups', []):
        for p in group.get('params', []):
            values[p['key']] = p['value']
    if not values:
        return out
    if values.get('api_base'):
        out['api_base'] = values['api_base']
    if values.get('api_key'):
        out['api_key'] = values['api_key']
    model = values.get('model')
    if model == 'custom':
        model = values.get('custom_model') or None
    if model:
        out['model'] = model
    for k, caster in (('temperature', float), ('max_tokens', int), ('timeout', int)):
        if values.get(k) not in (None, ''):
            try:
                out[k] = caster(values[k])
            except (ValueError, TypeError):
                pass
    return out


def _load_namespaced_provider(name: str) -> Dict[str, Any]:
    """P0-10b（七轮）：读取 QUANTIA_AI_PROVIDER_<NAME>_* 对应的 api_base / api_key /
    default_model，供该 provider 成为 overrides.provider 时覆盖 default 填衡。
    返回空 dict 表示未配置（调用者应保留 default 值）。
    """
    if not name:
        return {}
    import os
    env = os.environ
    upper = name.upper()
    out: Dict[str, Any] = {}
    # 兼容文档 §4.2 写的 BASE_URL 与代码原先使用的 API_BASE 两种命名
    base = env.get(f'QUANTIA_AI_PROVIDER_{upper}_API_BASE') \
        or env.get(f'QUANTIA_AI_PROVIDER_{upper}_BASE_URL')
    if base:
        out['api_base'] = base
    key = env.get(f'QUANTIA_AI_PROVIDER_{upper}_API_KEY')
    if key:
        out['api_key'] = key
    model = env.get(f'QUANTIA_AI_PROVIDER_{upper}_DEFAULT_MODEL')
    if model:
        out['model'] = model
    return out


def load_config(overrides: Optional[Dict[str, Any]] = None) -> AIConfig:
    """三层合并生成 AIConfig。"""
    merged: Dict[str, Any] = {}
    merged.update(_load_from_env())
    merged.update(_load_from_db())
    if overrides:
        merged.update({k: v for k, v in overrides.items() if v is not None})
    # P0-10b（七轮）：若 overrides.provider 指名了 namespaced provider（如 azure_openai）
    # 且 caller 未显式指定 api_base/api_key，则从该 namespace 中加载，避免用
    # default provider 的密钥调用另一个服务商 endpoint 导致 401。
    if overrides and overrides.get('provider'):
        ns = _load_namespaced_provider(str(overrides['provider']))
        for k in ('api_base', 'api_key', 'model'):
            if k in ns and (overrides.get(k) in (None, '')):
                merged[k] = ns[k]
    # 修复：当 provider 来自 env 默认 (QUANTIA_AI_DEFAULT_PROVIDER) 或 db 时，
    # 若同名 namespaced 配置 (QUANTIA_AI_PROVIDER_<NAME>_*) 存在，则 namespace
    # 优先于顶层 QUANTIA_AI_API_BASE/_API_KEY/_MODEL（后者通常是另一个 provider
    # 的 fallback，例如默认 OpenAI key），避免错配导致 401。
    # 仅当 overrides 未显式指定 provider/api_base/api_key/model 时生效。
    elif merged.get('provider'):
        ns = _load_namespaced_provider(str(merged['provider']))
        if ns:
            for k in ('api_base', 'api_key', 'model'):
                if k in ns and not (overrides and overrides.get(k)):
                    merged[k] = ns[k]
    valid_keys = {'provider', 'api_base', 'api_key', 'model',
                  'temperature', 'max_tokens', 'timeout', 'extra'}
    extra = {k: v for k, v in merged.items() if k not in valid_keys}
    cfg_kwargs = {k: v for k, v in merged.items() if k in valid_keys}
    if extra:
        cfg_kwargs.setdefault('extra', {}).update(extra)
    return AIConfig(**cfg_kwargs)


# ──────────────────────────────────────────────────────────────────────
# M5：列出已配置的 provider 与 model（供 /ai/config 使用）
#
# 设计：
#   * provider profile 通过 env 命名空间发现：
#       QUANTIA_AI_PROVIDER_<NAME>_API_BASE
#       QUANTIA_AI_PROVIDER_<NAME>_API_KEY
#       QUANTIA_AI_PROVIDER_<NAME>_MODELS  (逗号分隔模型列表，可选)
#       QUANTIA_AI_PROVIDER_<NAME>_DEFAULT_MODEL (可选)
#   * 始终包含一个 fallback 'default' profile，对应 QUANTIA_AI_API_BASE/_KEY/_MODEL
#   * api_key 永不外露（只返回是否已配置）
# ──────────────────────────────────────────────────────────────────────
def list_provider_profiles() -> Dict[str, Any]:
    """枚举可用 provider profile。返回 {profiles: [...], default: <name>}。"""
    import os
    env = os.environ
    profiles: Dict[str, Dict[str, Any]] = {}
    prefix = 'QUANTIA_AI_PROVIDER_'
    # P0-1（六轮）：provider 名可含下划线（如 AZURE_OPENAI），不能用
    # split('_', 1) 从左切；改为后缀匹配，未识别的 attr 则跳过。
    _SUFFIXES = ('API_BASE', 'BASE_URL', 'API_KEY', 'MODELS', 'DEFAULT_MODEL', 'LABEL')
    for k, _v in env.items():
        if not k.startswith(prefix):
            continue
        rest = k[len(prefix):]
        attr = None
        for s in _SUFFIXES:
            if rest.endswith('_' + s):
                attr = s
                name = rest[: -(len(s) + 1)]
                break
        if not attr or not name:
            continue
        name = name.lower()
        prof = profiles.setdefault(name, {'name': name})
        if attr in ('API_BASE', 'BASE_URL'):
            prof['api_base'] = env[k]
        elif attr == 'API_KEY':
            prof['has_key'] = _has_real_api_key(env[k])
        elif attr == 'MODELS':
            prof['models'] = [m.strip() for m in env[k].split(',') if m.strip()]
        elif attr == 'DEFAULT_MODEL':
            prof['default_model'] = env[k]
        elif attr == 'LABEL':
            prof['label'] = env[k]

    # 总是追加 default profile（来自 QUANTIA_AI_* 直配）
    cfg = load_config()
    if 'default' not in profiles:
        profiles['default'] = {
            'name': 'default',
            'api_base': cfg.api_base,
            'has_key': bool(cfg.api_key),
            'default_model': cfg.model,
        }
    # 默认 profile 名（启动时实际生效的那一个）
    default_name = (env.get('QUANTIA_AI_DEFAULT_PROVIDER') or 'default').lower()
    if default_name not in profiles:
        default_name = 'default'

    # P1-4（六轮）：返回前稳定排序，default 置顶，其余字母序
    sorted_profiles = sorted(
        profiles.values(),
        key=lambda p: (0 if p['name'] == 'default' else 1, p['name']),
    )
    return {
        'profiles': sorted_profiles,
        'default': default_name,
        'default_model': cfg.model,
        'temperature': cfg.temperature,
        'max_tokens': cfg.max_tokens,
        'timeout': cfg.timeout,
    }
