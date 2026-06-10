#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模拟交易状态管理器

负责将模拟盘的运行状态（持仓、现金、g 对象）序列化到数据库，
以及从数据库恢复状态，使模拟盘可以跨日持续运行。
"""

import json
import logging
import datetime

__author__ = 'Quantia'
__date__ = '2026/03/13'


# context 上由 state 顶层字段单独序列化 / 由引擎管理的属性，不纳入 context_vars，
# 避免与显式字段重复或覆盖引擎内部对象。
_CTX_SERIALIZED_KEYS = {
    'portfolio', 'current_dt', 'previous_dt', 'benchmark',
    'benchmark_base_code', 'benchmark_base_date', 'benchmark_base_price',
    'commission_rate', 'stamp_tax_rate', 'slippage_rate',
}


def serialize_portfolio(context):
    """
    将 Portfolio + GlobalVars 序列化为 JSON 字符串。

    Args:
        context: Context 对象

    Returns:
        str: JSON 字符串
    """
    positions = {}
    for code, pos in context.portfolio.positions.items():
        if pos.amount > 0:
            positions[code] = {
                'code': pos.code,
                'name': pos.name,
                'amount': pos.amount,
                'closeable_amount': pos.closeable_amount,
                'avg_cost': pos.avg_cost,
                'price': pos.price,
            }

    # 序列化 g 对象（仅基本类型）
    g_vars = {}
    if hasattr(context, '_engine') and context._engine and hasattr(context._engine, 'g'):
        g = context._engine.g
        for attr in dir(g):
            if attr.startswith('_'):
                continue
            val = getattr(g, attr, None)
            if isinstance(val, (str, int, float, bool, list, dict, type(None))):
                g_vars[attr] = val

    # 序列化 context 上的运行期标量状态（如 hold_days / days 等调仓计数器）。
    # initialize() 每轮都会重新执行并把这些计数器重置为默认值，若不持久化并在
    # initialize 后回填，hourly 调度下 hold_days 永远为 1，调仓门 hold_days%20==1
    # 恒真 → 每次运行都调仓（同日卖出又买入）。这里只保存标量，不动 portfolio。
    context_vars = {}
    for attr, val in list(vars(context).items()):
        if attr.startswith('_') or attr in _CTX_SERIALIZED_KEYS:
            continue
        if isinstance(val, (str, int, float, bool, list, dict, type(None))):
            context_vars[attr] = val

    state = {
        'available_cash': context.portfolio.available_cash,
        'positions': positions,
        'g_vars': g_vars,
        'context_vars': context_vars,
        'current_dt': str(context.current_dt) if context.current_dt else None,
        'benchmark': context.benchmark,
        'benchmark_base_code': getattr(context, 'benchmark_base_code', context.benchmark),
        'benchmark_base_date': getattr(context, 'benchmark_base_date', None),
        'benchmark_base_price': getattr(context, 'benchmark_base_price', None),
        'commission_rate': context.commission_rate,
        'stamp_tax_rate': context.stamp_tax_rate,
        'slippage_rate': context.slippage_rate,
    }
    return json.dumps(state, ensure_ascii=False, default=str)


def restore_portfolio(context, state_json, g_obj=None):
    """
    从 JSON 字符串恢复 Portfolio 和 GlobalVars 状态。

    Args:
        context: Context 对象
        state_json: JSON 字符串
        g_obj: GlobalVars 对象（可选）
    """
    if not state_json:
        return

    try:
        state = json.loads(state_json)
    except (json.JSONDecodeError, TypeError):
        logging.warning("模拟盘状态恢复失败：JSON 解析错误")
        return

    # 恢复现金
    context.portfolio.available_cash = state.get('available_cash', context.portfolio.starting_cash)

    # 恢复持仓
    from quantia.core.backtest.strategy_context import Position
    context.portfolio.positions.clear()
    for code, pos_data in state.get('positions', {}).items():
        pos = Position(code, pos_data.get('name', ''))
        pos.amount = pos_data.get('amount', 0)
        pos.closeable_amount = pos_data.get('closeable_amount', 0)
        pos.avg_cost = pos_data.get('avg_cost', 0)
        pos.price = pos_data.get('price', 0)
        pos.value = pos.amount * pos.price
        if pos.amount > 0:
            context.portfolio.positions[code] = pos

    context.portfolio._update_value()

    # 恢复交易成本
    context.benchmark = state.get('benchmark', '000300')
    context.benchmark_base_code = state.get('benchmark_base_code') or context.benchmark
    context.benchmark_base_date = state.get('benchmark_base_date')
    context.benchmark_base_price = state.get('benchmark_base_price')
    context.commission_rate = state.get('commission_rate', 0.0003)
    context.stamp_tax_rate = state.get('stamp_tax_rate', 0.001)
    context.slippage_rate = state.get('slippage_rate', 0.002)

    # 恢复 g 对象
    if g_obj and 'g_vars' in state:
        for key, val in state['g_vars'].items():
            setattr(g_obj, key, val)


def restore_runtime_vars(context, state_json, g_obj=None):
    """在 initialize() 重新执行（会把 hold_days/days 等计数器重置为默认值）之后，
    回填持久化的运行期标量状态（context_vars + g_vars）。

    必须在 initialize 之后调用：引擎每轮都会重跑 initialize 以重新注册 run_daily
    等回调，副作用是把调仓计数器清零。此处回填真实计数器值，使调仓门按真实交易日
    连续推进，避免 hourly 调度下 hold_days 恒为 1、每次运行都调仓的同日买卖问题。
    """
    if not state_json:
        return
    try:
        state = json.loads(state_json)
    except (json.JSONDecodeError, TypeError):
        return

    for key, val in (state.get('context_vars') or {}).items():
        try:
            setattr(context, key, val)
        except Exception:
            pass

    if g_obj is not None:
        for key, val in (state.get('g_vars') or {}).items():
            try:
                setattr(g_obj, key, val)
            except Exception:
                pass
