#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
集中式环境变量配置模块

功能：
1. 自动加载项目根目录下的 .env 文件（python-dotenv，可选依赖）
2. 提供类型安全的配置读取函数：get_str / get_int / get_float / get_bool
3. .env 文件中的值不会覆盖已设置的系统环境变量（方法 A 优先于方法 B）
4. 所有模块均可通过 os.environ.get() 直接读取（dotenv 已注入 os.environ）
5. QUANTIA_* 为统一配置名

使用方式：
    # 方式一：依赖自动加载（import 本模块即触发 .env 加载）
    import quantia.lib.envconfig  # noqa: F401  — 仅用于触发 .env 加载

    # 方式二：使用类型安全的辅助函数
    from quantia.lib.envconfig import get_int, get_bool
    port = get_int('QUANTIA_WEB_PORT', 9988)
    force = get_bool('QUANTIA_FORCE_FETCH', False)

配置优先级（高 → 低）：
    1. 系统环境变量（export / set / Docker ENV）
    2. .env 文件（项目根目录）
    3. 代码中的默认值
"""

import os

__author__ = 'Quantia'
__date__ = '2026/03/12'

# ── .env 自动加载 ──
# 向上查找到项目根目录（quantia/lib/envconfig.py → 项目根）
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
_env_path = os.path.join(_project_root, '.env')

_dotenv_loaded = False

try:
    from dotenv import load_dotenv as _load_dotenv
    if os.path.isfile(_env_path):
        _load_dotenv(_env_path, override=False)
        _dotenv_loaded = True
except ImportError:
    pass  # python-dotenv 未安装时静默跳过，仅使用环境变量


def get_raw(key: str) -> str | None:
    """读取原始配置值。"""
    if key in os.environ:
        return os.environ[key]
    return None


# ── 类型安全的配置读取函数 ──

def get_str(key: str, default: str = '') -> str:
    """读取字符串配置"""
    val = get_raw(key)
    return default if val is None else val


def get_int(key: str, default: int = 0) -> int:
    """读取整数配置，值无效时返回默认值"""
    val = get_raw(key)
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def get_float(key: str, default: float = 0.0) -> float:
    """读取浮点数配置，值无效时返回默认值"""
    val = get_raw(key)
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def get_bool(key: str, default: bool = False) -> bool:
    """读取布尔配置，支持 1/true/yes/on（不区分大小写）"""
    val = get_raw(key)
    if val is None:
        return default
    return val.strip().lower() in ('1', 'true', 'yes', 'on')
