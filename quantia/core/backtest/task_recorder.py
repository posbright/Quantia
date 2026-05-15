#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回测任务持久化记录器 — 统一 ``cn_stock_backtest_portfolio`` 三种终态入库。

历史问题（修复前）：
  * ``RunPortfolioBacktestHandler`` 与 ``StartPortfolioBacktestHandler`` 仅在
    ``result['status'] == 'completed'`` 时才 INSERT；
  * 引擎 ``run()`` 抛异常或返回 ``status='error'`` 时不入库；
  * 因此 ``cn_stock_backtest_portfolio.error_message`` 列长期为空，
    历史失败任务无从追溯，AI 自动修复闭环也无输入数据。

本模块统一三种终态：
  * ``record_completed(...)``  成功
  * ``record_failed(...)``     失败（含 traceback）
  * ``fetch_last_failure(strategy_id)``  AI 修复闭环读取
"""

import datetime
import json
import logging
from typing import Any, Dict, Optional

import quantia.lib.database as mdb

__author__ = 'Quantia'
__date__ = '2026/05/06'

_TABLE = 'cn_stock_backtest_portfolio'
_MAX_ERROR_LEN = 8000


def _insert_and_get_id(sql: str, params: tuple) -> Optional[int]:
    """与 portfolioBacktestHandler 内同名工具一致的简易封装。"""
    try:
        with mdb.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                cur.execute('SELECT LAST_INSERT_ID()')
                row = cur.fetchone()
                return int(row[0]) if row and row[0] is not None else None
    except Exception as exc:
        logging.warning(f"[task_recorder] INSERT 失败: {exc}")
        return None


def _ensure_table():
    """惰性确保表存在（复用 portfolioBacktestHandler 的迁移）。"""
    try:
        from quantia.web.portfolioBacktestHandler import _ensure_backtest_table
        _ensure_backtest_table()
    except Exception as exc:
        logging.debug(f"[task_recorder] _ensure_backtest_table 调用失败: {exc}")


def record_completed(
    *,
    strategy_id: Optional[int],
    strategy_name: Optional[str],
    start_date: str,
    end_date: str,
    initial_cash: float,
    benchmark: str,
    result: Dict[str, Any],
    started_at: Optional[datetime.datetime] = None,
) -> Optional[int]:
    """记录一次成功的回测，返回 cn_stock_backtest_portfolio.id。"""
    _ensure_table()
    metrics = (result or {}).get('metrics', {}) or {}
    now = datetime.datetime.now()
    started = started_at or now
    return _insert_and_get_id(
        f'INSERT INTO {_TABLE} '
        '(strategy_id, strategy_name, start_date, end_date, initial_cash, benchmark, status, '
        ' started_at, completed_at, total_return, annual_return, '
        ' max_drawdown, sharpe_ratio, alpha, beta, win_rate, trade_count, result_json) '
        'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
        (
            strategy_id, strategy_name or None, start_date, end_date, initial_cash, benchmark,
            'completed', started, now,
            metrics.get('total_return'), metrics.get('annual_return'),
            metrics.get('max_drawdown'), metrics.get('sharpe_ratio'),
            metrics.get('alpha'), metrics.get('beta'),
            metrics.get('daily_win_rate'), metrics.get('trade_count'),
            json.dumps(result, ensure_ascii=False, default=str),
        ),
    )


def record_failed(
    *,
    strategy_id: Optional[int],
    strategy_name: Optional[str],
    start_date: str,
    end_date: str,
    initial_cash: float,
    benchmark: str,
    error_text: str,
    traceback_text: str = '',
    started_at: Optional[datetime.datetime] = None,
    extra_result: Optional[Dict[str, Any]] = None,
) -> Optional[int]:
    """记录一次失败的回测；写入 ``error_message`` 与 ``result_json`` 供 AI 修复闭环读取。"""
    _ensure_table()
    now = datetime.datetime.now()
    started = started_at or now
    msg = (traceback_text or error_text or '')[:_MAX_ERROR_LEN]
    payload = {
        'status': 'failed',
        'error': error_text or '',
        'traceback': traceback_text or '',
    }
    if extra_result:
        payload.update(extra_result)
    return _insert_and_get_id(
        f'INSERT INTO {_TABLE} '
        '(strategy_id, strategy_name, start_date, end_date, initial_cash, benchmark, status, '
        ' started_at, completed_at, error_message, result_json) '
        'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
        (
            strategy_id, strategy_name or None, start_date, end_date, initial_cash, benchmark,
            'failed', started, now, msg,
            json.dumps(payload, ensure_ascii=False, default=str),
        ),
    )


def _parse_result_json(raw: Any) -> Dict[str, Any]:
    """安全解析 result_json 列；非法 JSON 时退化为空 dict。"""
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw) if isinstance(raw, (str, bytes, bytearray)) else {}
    except Exception:
        return {}


def fetch_last_failure(strategy_id: int) -> Optional[Dict[str, Any]]:
    """返回该策略最近一次失败任务的完整失败信息，供 AI 自动修复闭环喂回 LLM。

    返回字段：
        ``id``               回测任务主键
        ``started_at``       开始时间
        ``completed_at``     结束时间
        ``error_message``    error_message 列（首要错误摘要，最长 8KB）
        ``traceback``        从 ``result_json.traceback`` 解析出的完整堆栈
        ``error``            从 ``result_json.error`` 解析出的简短错误文本
    """
    if strategy_id is None:
        return None
    try:
        rows = mdb.executeSqlFetch(
            f'SELECT id, started_at, completed_at, error_message, result_json '
            f'FROM {_TABLE} WHERE strategy_id=%s AND status=%s '
            f'ORDER BY id DESC LIMIT 1',
            (int(strategy_id), 'failed'),
        ) or []
    except Exception as exc:
        logging.warning(f"[task_recorder] fetch_last_failure 异常: {exc}")
        return None
    if not rows:
        return None
    r = rows[0]
    payload = _parse_result_json(r[4] if len(r) > 4 else None)
    return {
        'id': r[0],
        'started_at': r[1],
        'completed_at': r[2],
        'error_message': r[3] or '',
        'traceback': str(payload.get('traceback') or '')[:_MAX_ERROR_LEN],
        'error': str(payload.get('error') or '')[:2000],
    }


def fetch_recent_failures(strategy_id: int, limit: int = 5) -> list:
    """返回该策略最近 N 次失败任务（按 id 倒序），供 AI 看历史避免重复同一类修复。

    每个元素同 ``fetch_last_failure`` 的字段。
    """
    if strategy_id is None or limit <= 0:
        return []
    try:
        rows = mdb.executeSqlFetch(
            f'SELECT id, started_at, completed_at, error_message, result_json '
            f'FROM {_TABLE} WHERE strategy_id=%s AND status=%s '
            f'ORDER BY id DESC LIMIT %s',
            (int(strategy_id), 'failed', int(limit)),
        ) or []
    except Exception as exc:
        logging.warning(f"[task_recorder] fetch_recent_failures 异常: {exc}")
        return []
    out = []
    for r in rows:
        payload = _parse_result_json(r[4] if len(r) > 4 else None)
        out.append({
            'id': r[0],
            'started_at': r[1],
            'completed_at': r[2],
            'error_message': r[3] or '',
            'traceback': str(payload.get('traceback') or '')[:_MAX_ERROR_LEN],
            'error': str(payload.get('error') or '')[:2000],
        })
    return out
