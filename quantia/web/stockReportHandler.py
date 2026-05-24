#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 个股分析报告 Handler — SSE 流式输出 + 缓存 + 搜索。

路由（web_service.py 中注册）::

    POST /quantia/api/ai/report/generate      → SSE 流式生成报告
    POST /quantia/api/ai/report/followup      → SSE 追问
    POST /quantia/api/ai/report/feedback      → 提交报告反馈 (👍/👎)
    GET  /quantia/api/ai/report/history        → 历史报告列表
    GET  /quantia/api/ai/report/detail         → 单条报告详情
    GET  /quantia/api/ai/report/search_stock   → 股票搜索 autocomplete
    GET  /quantia/api/ai/report/stock_data     → 快速结构化数据（fallback 面板）
"""
from __future__ import annotations

import json
import logging
import queue
import threading
import time
from abc import ABC
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from tornado import gen
from tornado.ioloop import IOLoop
from concurrent.futures import ThreadPoolExecutor

import quantia.lib.database as mdb
import quantia.web.base as webBase

__author__ = 'Quantia'
__date__ = '2026/05/23'

_logger = logging.getLogger(__name__)

_REPORT_TABLE = 'cn_stock_ai_report'
_STREAM_SENTINEL = object()
_executor = ThreadPoolExecutor(max_workers=2)

_ALLOWED_TOOLS = ['stock_profile', 'kline_fetch', 'web_search']


def _load_analyst_prompt() -> str:
    """加载 stock_analyst agent 的 system prompt（从 prompt 文件读取，避免硬编码冗余）。"""
    from quantia.lib.ai.prompt_loader import load
    return load('stock_analyst')


def _ensure_report_table():
    """创建报告缓存表（幂等）。"""
    ddl = f"""
    CREATE TABLE IF NOT EXISTS `{_REPORT_TABLE}` (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        code VARCHAR(10) NOT NULL,
        name VARCHAR(32) DEFAULT NULL,
        report_md MEDIUMTEXT NOT NULL,
        model VARCHAR(64) DEFAULT NULL,
        provider VARCHAR(32) DEFAULT NULL,
        tools_used JSON DEFAULT NULL,
        tokens_used INT DEFAULT 0,
        latency_ms INT DEFAULT 0,
        quality_score TINYINT DEFAULT NULL COMMENT '结构校验: 100=通过, 50=部分, 0=失败',
        user_feedback TINYINT DEFAULT NULL COMMENT '1=满意, -1=不满意, NULL=未评',
        feedback_reason VARCHAR(200) DEFAULT NULL,
        data_cutoff_date DATE DEFAULT NULL COMMENT '报告依据的最新数据日期',
        source ENUM('user','cron','batch') DEFAULT 'user' COMMENT '生成来源',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_code_date (code, created_at DESC),
        INDEX idx_source (source, created_at DESC)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """
    try:
        mdb.executeSql(ddl)
    except Exception as exc:
        _logger.warning(f'[stockReport] 建表失败（可能已存在）: {exc}', exc_info=True)


_table_ensured = False
_table_lock = threading.Lock()


def _lazy_ensure_table():
    global _table_ensured
    if _table_ensured:
        return
    with _table_lock:
        if not _table_ensured:
            _ensure_report_table()
            _table_ensured = True


def _check_cache(code: str) -> Optional[Dict[str, Any]]:
    """检查缓存：盘中30min/收盘后当日有效。"""
    _lazy_ensure_table()
    now = datetime.now()
    hour = now.hour
    # 盘中 (09:30-15:00): TTL = 30 分钟
    # 收盘后: TTL = 当日剩余时间（限制为同一自然日）
    if 9 <= hour < 15:
        cutoff = now - timedelta(minutes=30)
    else:
        # 使用当天 00:00 作为下界，确保不会命中昨天的报告
        cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
    sql = f"""
        SELECT id, code, name, report_md, model, provider, tools_used,
               tokens_used, latency_ms, created_at
        FROM `{_REPORT_TABLE}`
        WHERE code = %s AND created_at >= %s
        ORDER BY created_at DESC LIMIT 1
    """
    rows = mdb.executeSqlFetch(sql, (code, cutoff.strftime('%Y-%m-%d %H:%M:%S')))
    if not rows:
        return None
    row = rows[0]
    return {
        'id': row[0],
        'code': row[1],
        'name': row[2],
        'report_md': row[3],
        'model': row[4],
        'provider': row[5],
        'tools_used': json.loads(row[6]) if row[6] else [],
        'tokens_used': row[7],
        'latency_ms': row[8],
        'created_at': str(row[9]),
    }


def _has_data_update(code: str, last_report_time: str) -> tuple:
    """检测自上次报告后是否有新数据更新。

    Returns: (has_update: bool, reason: str)
    """
    try:
        # 检查资金流向最新日期
        rows = mdb.executeSqlFetch(
            "SELECT MAX(date) FROM cn_stock_fund_flow WHERE code = %s", (code,))
        if rows and rows[0][0]:
            latest_flow = str(rows[0][0])
            if latest_flow > last_report_time[:10]:
                return True, f"资金面数据已更新至{latest_flow}"

        # 检查行情数据最新日期
        rows = mdb.executeSqlFetch(
            "SELECT MAX(date) FROM cn_stock_spot WHERE code = %s", (code,))
        if rows and rows[0][0]:
            latest_spot = str(rows[0][0])
            if latest_spot > last_report_time[:10]:
                return True, f"行情数据更新至{latest_spot}"
    except Exception as exc:
        _logger.warning(f'[stockReport] 数据变更检测失败: {exc}', exc_info=True)

    return False, ""


def _save_report(code: str, name: str, report_md: str, model: str,
                 provider: str, tools_used: List[str],
                 tokens_used: int, latency_ms: int) -> int:
    """持久化报告到 DB。"""
    _lazy_ensure_table()
    sql = f"""
        INSERT INTO `{_REPORT_TABLE}`
            (code, name, report_md, model, provider, tools_used,
             tokens_used, latency_ms, data_cutoff_date)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURDATE())
    """
    tools_json = json.dumps(tools_used, ensure_ascii=False)
    mdb.executeSql(sql, (code, name, report_md, model, provider,
                         tools_json, tokens_used, latency_ms))
    # Get last insert id
    rows = mdb.executeSqlFetch("SELECT LAST_INSERT_ID()")
    return rows[0][0] if rows else 0


def _write_json(handler, data: Dict[str, Any], status: int = 200):
    handler.set_status(status)
    handler.set_header("Content-Type", "application/json; charset=UTF-8")
    handler.write(json.dumps(data, ensure_ascii=False, default=str))


def _get_previous_report_summary(code: str) -> Optional[str]:
    """获取上一次报告的摘要（用于增量对比提示），仅取前600字。"""
    try:
        sql = f"""
            SELECT report_md, created_at
            FROM `{_REPORT_TABLE}`
            WHERE code = %s
            ORDER BY created_at DESC LIMIT 1
        """
        rows = mdb.executeSqlFetch(sql, (code,))
        if rows and rows[0][0]:
            report_md = rows[0][0]
            created_at = str(rows[0][1])
            # 提取摘要（前600字 + 截止日期）
            summary = report_md[:600]
            if len(report_md) > 600:
                summary += '...(截断)'
            return f"[上次报告 {created_at}]\n{summary}"
    except Exception:
        pass
    return None


def _run_agent_report(code: str, q: queue.Queue, cancel: threading.Event,
                      prev_summary: Optional[str] = None):
    """在线程中运行 Agent 生成报告，通过 queue 推送进度和文本。"""
    try:
        from quantia.lib.ai import run_agent
        from quantia.lib.ai.feature_switch import check_feature

        # 检查功能开关
        check_feature('stock_report')

        # 发送进度：开始获取数据
        q.put(('progress', {'step': 'stock_profile', 'status': 'running'}))

        user_message = f"请为 A 股 {code} 生成分析报告。"
        if prev_summary:
            user_message += (
                f"\n\n【增量对比参考】以下是上次分析报告的摘要，"
                f"如发现关键变化（如趋势反转、指标突破、资金流向逆转）请在报告中简要提及：\n"
                f"{prev_summary}"
            )
        started = time.time()

        result = run_agent(
            user_message=user_message,
            scene='stock_report',
            agent='stock_analyst',
            system=_load_analyst_prompt(),
            allowed_tools=_ALLOWED_TOOLS,
        )

        elapsed_ms = int((time.time() - started) * 1000)

        # 从 tool_calls 构建进度事件（逐工具回报 done）
        tools_used = []
        for tc in (result.tool_calls or []):
            name = tc.get('name', 'unknown')
            tools_used.append(name)
            q.put(('progress', {'step': name, 'status': 'done'}))

        # 发送报告生成完成进度
        q.put(('progress', {'step': 'report', 'status': 'done', 'elapsed_ms': elapsed_ms}))

        # 获取股票名称
        stock_name = ''
        for tc in (result.tool_calls or []):
            if tc.get('name') == 'stock_profile' and tc.get('ok'):
                r = tc.get('result', {})
                stock_name = r.get('name', '')
                break

        # 发送报告内容（分块模拟流式）
        content = result.content or ''
        chunk_size = 80
        for i in range(0, len(content), chunk_size):
            if cancel.is_set():
                break
            chunk = content[i:i + chunk_size]
            q.put(('chunk', chunk))

        # 发送元数据
        q.put(('meta', {
            'code': code,
            'name': stock_name,
            'model': result.model,
            'provider': result.provider,
            'tools_used': tools_used,
            'tokens_used': result.total_tokens or 0,
            'latency_ms': elapsed_ms,
        }))

    except Exception as exc:
        _logger.exception(f'[stockReport] Agent 报告生成失败: {exc}')
        q.put(('error', {'msg': str(exc)}))
    finally:
        q.put((_STREAM_SENTINEL, None))


class StockReportGenerateHandler(webBase.BaseHandler, ABC):
    """POST /quantia/api/ai/report/generate — SSE 流式生成报告。"""

    @gen.coroutine
    def post(self):
        try:
            body = json.loads(self.request.body or '{}')
        except (json.JSONDecodeError, TypeError):
            body = {}
        code = (body.get('code') or '').strip()
        if not code or len(code) != 6:
            _write_json(self, {'error': 'code 必须是6位股票代码'}, 400)
            return

        # 缓存检查
        force = body.get('force', False)
        if not force:
            cached = _check_cache(code)
            if cached:
                # 检查数据是否有更新
                has_update, update_reason = _has_data_update(
                    code, cached.get('created_at', ''))
                if has_update:
                    # 数据已更新，标记但仍返回旧报告 + 提示刷新
                    cached['data_updated'] = True
                    cached['update_reason'] = update_reason
                # 返回缓存报告 (SSE 格式)
                self.set_header('Content-Type', 'text/event-stream; charset=utf-8')
                self.set_header('Cache-Control', 'no-cache')
                self.set_header('X-Accel-Buffering', 'no')
                # 发送缓存命中事件
                self.write('data: ' + json.dumps(
                    {'type': 'cached', 'report': cached}, ensure_ascii=False, default=str
                ) + '\n\n')
                yield self.flush()
                self.write('data: ' + json.dumps({'type': 'done'}) + '\n\n')
                yield self.flush()
                return

        # SSE streaming
        self.set_header('Content-Type', 'text/event-stream; charset=utf-8')
        self.set_header('Cache-Control', 'no-cache')
        self.set_header('X-Accel-Buffering', 'no')

        # 获取上次报告摘要用于增量对比
        prev_summary = _get_previous_report_summary(code)

        q_out = queue.Queue(maxsize=128)
        cancel_event = threading.Event()

        # Start producer
        t = threading.Thread(
            target=_run_agent_report, args=(code, q_out, cancel_event, prev_summary), daemon=True)
        t.start()

        loop = IOLoop.current()
        full_text_parts: List[str] = []
        meta_info: Dict[str, Any] = {}

        def _queue_get():
            """Blocking queue get with timeout (runs in executor thread)."""
            import queue as _q
            try:
                return q_out.get(block=True, timeout=120)
            except _q.Empty:
                _logger.warning(f'[stockReport] 队列读取超时(120s)，Agent 可能卡死 (code={code})')
                return (_STREAM_SENTINEL, None)

        while True:
            try:
                item = yield loop.run_in_executor(_executor, _queue_get)
            except Exception as exc:
                _logger.debug(f'[stockReport] executor 异常: {type(exc).__name__}: {exc}')
                cancel_event.set()
                break
            kind, payload = item
            if kind is _STREAM_SENTINEL:
                break
            try:
                if kind == 'progress':
                    self.write('data: ' + json.dumps(
                        {'type': 'progress', **payload}, ensure_ascii=False) + '\n\n')
                    yield self.flush()
                elif kind == 'chunk':
                    full_text_parts.append(payload)
                    self.write('data: ' + json.dumps(
                        {'type': 'chunk', 'text': payload}, ensure_ascii=False) + '\n\n')
                    yield self.flush()
                elif kind == 'meta':
                    meta_info = payload
                elif kind == 'error':
                    self.write('data: ' + json.dumps(
                        {'type': 'error', 'msg': payload.get('msg', '生成失败')},
                        ensure_ascii=False) + '\n\n')
                    yield self.flush()
            except Exception as exc:
                # Client disconnected during write/flush
                _logger.debug(f'[stockReport] SSE 写入失败（客户端可能已断开）: {type(exc).__name__}: {exc}')
                cancel_event.set()
                break

        # 保存报告
        full_text = ''.join(full_text_parts)
        report_id = 0
        if full_text and meta_info:
            try:
                report_id = _save_report(
                    code=code,
                    name=meta_info.get('name', ''),
                    report_md=full_text,
                    model=meta_info.get('model', ''),
                    provider=meta_info.get('provider', ''),
                    tools_used=meta_info.get('tools_used', []),
                    tokens_used=meta_info.get('tokens_used', 0),
                    latency_ms=meta_info.get('latency_ms', 0),
                )
            except Exception as exc:
                _logger.warning(f'[stockReport] 保存报告失败: {exc}', exc_info=True)

        # 发送 done (best effort — client may already be gone)
        try:
            self.write('data: ' + json.dumps({
                'type': 'done',
                'report_id': report_id,
                'tokens_used': meta_info.get('tokens_used', 0),
                'latency_ms': meta_info.get('latency_ms', 0),
            }, ensure_ascii=False) + '\n\n')
            yield self.flush()
        except Exception as exc:
            _logger.debug(f'[stockReport] 发送 done 事件失败（客户端已断开）: {exc}')


class StockReportHistoryHandler(webBase.BaseHandler, ABC):
    """GET /quantia/api/ai/report/history — 历史报告列表。"""

    @gen.coroutine
    def get(self):
        _lazy_ensure_table()
        code = self.get_argument('code', '')
        try:
            limit = min(50, max(1, int(self.get_argument('limit', '20'))))
            offset = max(0, int(self.get_argument('offset', '0')))
        except (ValueError, TypeError):
            limit, offset = 20, 0

        where = ''
        params: List[Any] = []
        if code:
            where = 'WHERE code = %s'
            params.append(code)

        sql = f"""
            SELECT id, code, name, model, tokens_used, latency_ms, created_at
            FROM `{_REPORT_TABLE}`
            {where}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """
        params.extend([limit, offset])
        rows = mdb.executeSqlFetch(sql, tuple(params))
        items = []
        if rows:
            for r in rows:
                items.append({
                    'id': r[0], 'code': r[1], 'name': r[2],
                    'model': r[3], 'tokens_used': r[4],
                    'latency_ms': r[5], 'created_at': str(r[6]),
                })
        _write_json(self, {'items': items, 'limit': limit, 'offset': offset})


class StockReportDetailHandler(webBase.BaseHandler, ABC):
    """GET /quantia/api/ai/report/detail — 单条报告详情。"""

    @gen.coroutine
    def get(self):
        _lazy_ensure_table()
        report_id = self.get_argument('id', '')
        if not report_id:
            _write_json(self, {'error': '缺少 id 参数'}, 400)
            return
        sql = f"""
            SELECT id, code, name, report_md, model, provider, tools_used,
                   tokens_used, latency_ms, created_at
            FROM `{_REPORT_TABLE}`
            WHERE id = %s
        """
        rows = mdb.executeSqlFetch(sql, (report_id,))
        if not rows:
            _write_json(self, {'error': '报告不存在'}, 404)
            return
        r = rows[0]
        _write_json(self, {
            'id': r[0], 'code': r[1], 'name': r[2],
            'report_md': r[3], 'model': r[4], 'provider': r[5],
            'tools_used': json.loads(r[6]) if r[6] else [],
            'tokens_used': r[7], 'latency_ms': r[8],
            'created_at': str(r[9]),
        })


class StockSearchHandler(webBase.BaseHandler, ABC):
    """GET /quantia/api/ai/report/search_stock — 股票搜索 autocomplete。"""

    @gen.coroutine
    def get(self):
        q = (self.get_argument('q', '') or '').strip()
        if not q or len(q) < 1:
            _write_json(self, {'items': []})
            return

        # 搜索代码或名称（LIKE 匹配，返回 top 8）
        # 转义 SQL LIKE 通配符
        escaped_q = q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        sql = """
            SELECT code, name, industry
            FROM cn_stock_spot
            WHERE (code LIKE %s OR name LIKE %s)
            ORDER BY total_market_cap DESC
            LIMIT 50
        """
        pattern = f'%{escaped_q}%'
        rows = mdb.executeSqlFetch(sql, (pattern, pattern))
        items = []
        if rows:
            seen: dict = {}  # code -> {'code':..., 'name':..., 'industry':...}
            for r in rows:
                code_val = r[0]
                if code_val not in seen:
                    seen[code_val] = {'code': code_val, 'name': r[1] or '', 'industry': r[2] or ''}
                elif not seen[code_val]['industry'] and r[2]:
                    # 补充之前为空的 industry
                    seen[code_val]['industry'] = r[2]
            items = list(seen.values())[:8]
        _write_json(self, {'items': items})


def _run_followup(code: str, report_md: str, question: str,
                  q: queue.Queue, cancel: threading.Event):
    """在线程中运行追问 Agent，复用报告上下文，不重调 Tools。"""
    try:
        from quantia.lib.ai import run_agent
        from quantia.lib.ai.feature_switch import check_feature

        check_feature('stock_report')

        # 构造上下文：将原报告作为 assistant 历史 + 用户追问
        context_msg = (
            f"以下是之前为 {code} 生成的分析报告：\n\n{report_md}\n\n"
            f"---\n\n用户追问：{question}\n\n"
            "请基于已有报告数据回答，无需重新调用工具。回答简洁明了，200字以内。"
        )

        started = time.time()
        result = run_agent(
            user_message=context_msg,
            scene='stock_report',
            agent='stock_analyst',
            system='你是 Quantia AI 股票分析师。用户已生成了一份分析报告，现在有追问。基于已有报告中的数据作答，保持简洁专业。',
            allowed_tools=[],  # 不允许调工具，纯问答
        )
        elapsed_ms = int((time.time() - started) * 1000)

        content = result.content or ''
        chunk_size = 80
        for i in range(0, len(content), chunk_size):
            if cancel.is_set():
                break
            q.put(('chunk', content[i:i + chunk_size]))

        q.put(('meta', {
            'tokens_used': result.total_tokens or 0,
            'latency_ms': elapsed_ms,
        }))
    except Exception as exc:
        _logger.exception(f'[stockReport] 追问失败: {exc}')
        q.put(('error', {'msg': str(exc)}))
    finally:
        q.put((_STREAM_SENTINEL, None))


class StockReportFollowupHandler(webBase.BaseHandler, ABC):
    """POST /quantia/api/ai/report/followup — SSE 流式追问。"""

    @gen.coroutine
    def post(self):
        try:
            body = json.loads(self.request.body or '{}')
        except (json.JSONDecodeError, TypeError):
            body = {}
        code = (body.get('code') or '').strip()
        question = (body.get('question') or '').strip()
        report_md = (body.get('report_md') or '').strip()

        if not code or not question:
            _write_json(self, {'error': 'code 和 question 必填'}, 400)
            return
        if not report_md:
            _write_json(self, {'error': '缺少报告上下文 report_md'}, 400)
            return
        # 限制长度（防止 token 爆炸）
        report_md = report_md[:4000]
        question = question[:500]

        self.set_header('Content-Type', 'text/event-stream; charset=utf-8')
        self.set_header('Cache-Control', 'no-cache')
        self.set_header('X-Accel-Buffering', 'no')

        q_out = queue.Queue(maxsize=64)
        cancel_event = threading.Event()

        t = threading.Thread(
            target=_run_followup,
            args=(code, report_md, question, q_out, cancel_event),
            daemon=True,
        )
        t.start()

        loop = IOLoop.current()

        def _queue_get():
            import queue as _q
            try:
                return q_out.get(block=True, timeout=60)
            except _q.Empty:
                _logger.warning(f'[stockReport] 追问队列超时 (code={code})')
                return (_STREAM_SENTINEL, None)

        while True:
            try:
                item = yield loop.run_in_executor(_executor, _queue_get)
            except Exception:
                cancel_event.set()
                break
            kind, payload = item
            if kind is _STREAM_SENTINEL:
                break
            try:
                if kind == 'chunk':
                    self.write('data: ' + json.dumps(
                        {'type': 'chunk', 'text': payload}, ensure_ascii=False) + '\n\n')
                    yield self.flush()
                elif kind == 'error':
                    self.write('data: ' + json.dumps(
                        {'type': 'error', 'msg': payload.get('msg', '追问失败')},
                        ensure_ascii=False) + '\n\n')
                    yield self.flush()
                elif kind == 'meta':
                    pass  # meta sent in done
            except Exception:
                cancel_event.set()
                break

        # done event
        try:
            self.write('data: ' + json.dumps({'type': 'done'}) + '\n\n')
            yield self.flush()
        except Exception:
            pass


class StockReportFeedbackHandler(webBase.BaseHandler, ABC):
    """POST /quantia/api/ai/report/feedback — 提交报告反馈。"""

    @gen.coroutine
    def post(self):
        try:
            body = json.loads(self.request.body or '{}')
        except (json.JSONDecodeError, TypeError):
            body = {}
        report_id = body.get('report_id')
        feedback = body.get('feedback')  # 1=满意, -1=不满意
        reason = (body.get('reason') or '')[:200]

        if not report_id or feedback not in (1, -1):
            _write_json(self, {'error': 'report_id 和 feedback(1/-1) 必填'}, 400)
            return

        _lazy_ensure_table()
        sql = f"""
            UPDATE `{_REPORT_TABLE}`
            SET user_feedback = %s, feedback_reason = %s
            WHERE id = %s
        """
        try:
            mdb.executeSql(sql, (feedback, reason or None, report_id))
            _write_json(self, {'ok': True})
        except Exception as exc:
            _logger.warning(f'[stockReport] 反馈写入失败: {exc}', exc_info=True)
            _write_json(self, {'error': '写入失败'}, 500)


class StockReportAttentionListHandler(webBase.BaseHandler, ABC):
    """GET /quantia/api/ai/report/attention_list — 获取关注列表(code+name)。"""

    @gen.coroutine
    def get(self):
        import quantia.core.tablestructure as tbs
        table_name = tbs.TABLE_CN_STOCK_ATTENTION['name']
        sql = f"""
            SELECT a.code, COALESCE(MAX(s.name), '') as name
            FROM `{table_name}` a
            LEFT JOIN cn_stock_spot s ON a.code = s.code
            GROUP BY a.code
            ORDER BY MAX(a.datetime) DESC
            LIMIT 50
        """
        try:
            rows = mdb.executeSqlFetch(sql)
            items = [{'code': r[0], 'name': r[1]} for r in rows] if rows else []
            _write_json(self, {'items': items, 'count': len(items)})
        except Exception as exc:
            _logger.warning(f'[stockReport] 获取关注列表失败: {exc}', exc_info=True)
            _write_json(self, {'items': [], 'count': 0})


def _run_batch_summary(codes: List[str], q: queue.Queue, cancel: threading.Event):
    """在线程中依次为多只股票生成简短摘要（300字以内）。"""
    for code in codes:
        if cancel.is_set():
            break
        try:
            from quantia.lib.ai import run_agent
            from quantia.lib.ai.feature_switch import check_feature
            check_feature('stock_report')

            started = time.time()
            result = run_agent(
                user_message=(
                    f"请为 A 股 {code} 生成一段简短的投资分析摘要，不超过300字。"
                    f"包含：1）当前走势概括 2）主要技术信号 3）资金动向 4）综合评级（看多/看空/中性）"
                ),
                scene='stock_report',
                agent='stock_analyst',
                system=(
                    '你是 Quantia AI 股票分析师。请生成极简摘要卡片，'
                    '严格控制在300字以内。格式：一段文字概述 + 评级。'
                    '不要使用 markdown 标题，仅纯文本段落。'
                ),
                allowed_tools=_ALLOWED_TOOLS,
            )
            elapsed_ms = int((time.time() - started) * 1000)

            # 提取股票名称
            stock_name = ''
            for tc in (result.tool_calls or []):
                if tc.get('name') == 'stock_profile' and tc.get('ok'):
                    stock_name = tc.get('result', {}).get('name', '')
                    break

            content = (result.content or '')[:500]  # 硬截断防溢出

            # 从摘要中提取评级
            rating = 'neutral'
            if any(kw in content for kw in ('看多', '偏多', '看涨', '积极')):
                rating = 'bullish'
            elif any(kw in content for kw in ('看空', '偏空', '看跌', '谨慎', '回避')):
                rating = 'bearish'

            q.put(('item', {
                'code': code,
                'name': stock_name,
                'summary': content,
                'rating': rating,
                'tokens_used': result.total_tokens or 0,
                'latency_ms': elapsed_ms,
            }))
        except Exception as exc:
            _logger.warning(f'[stockReport] 批量摘要生成失败 {code}: {exc}')
            q.put(('item', {
                'code': code,
                'name': '',
                'summary': f'生成失败: {exc}',
                'error': True,
            }))
    q.put((_STREAM_SENTINEL, None))


class StockReportBatchHandler(webBase.BaseHandler, ABC):
    """POST /quantia/api/ai/report/batch_summary — SSE 批量摘要（关注列表）。"""

    @gen.coroutine
    def post(self):
        try:
            body = json.loads(self.request.body or '{}')
        except (json.JSONDecodeError, TypeError):
            body = {}
        codes = body.get('codes', [])
        if not codes or not isinstance(codes, list):
            _write_json(self, {'error': 'codes 必须是非空数组'}, 400)
            return
        # 限制最多 20 只
        codes = [c for c in codes[:20] if isinstance(c, str) and len(c) == 6]
        if not codes:
            _write_json(self, {'error': '无有效的6位股票代码'}, 400)
            return

        self.set_header('Content-Type', 'text/event-stream; charset=utf-8')
        self.set_header('Cache-Control', 'no-cache')
        self.set_header('X-Accel-Buffering', 'no')

        # 发送开始事件
        self.write('data: ' + json.dumps(
            {'type': 'start', 'total': len(codes)}, ensure_ascii=False) + '\n\n')
        yield self.flush()

        q_out = queue.Queue(maxsize=64)
        cancel_event = threading.Event()

        t = threading.Thread(
            target=_run_batch_summary, args=(codes, q_out, cancel_event), daemon=True)
        t.start()

        loop = IOLoop.current()

        def _queue_get():
            import queue as _q
            try:
                return q_out.get(block=True, timeout=180)
            except _q.Empty:
                return (_STREAM_SENTINEL, None)

        while True:
            try:
                item = yield loop.run_in_executor(_executor, _queue_get)
            except Exception:
                cancel_event.set()
                break
            kind, payload = item
            if kind is _STREAM_SENTINEL:
                break
            try:
                if kind == 'item':
                    self.write('data: ' + json.dumps(
                        {'type': 'item', **payload}, ensure_ascii=False) + '\n\n')
                    yield self.flush()
            except Exception:
                cancel_event.set()
                break

        # done
        try:
            self.write('data: ' + json.dumps({'type': 'done'}) + '\n\n')
            yield self.flush()
        except Exception:
            pass


class StockDataFallbackHandler(webBase.BaseHandler, ABC):
    """GET /quantia/api/ai/report/stock_data — 快速结构化数据（AI不可用时展示）。"""

    @gen.coroutine
    def get(self):
        code = (self.get_argument('code', '') or '').strip()
        if not code or len(code) != 6:
            _write_json(self, {'error': 'code 必须是6位'}, 400)
            return

        result: Dict[str, Any] = {'code': code}

        # 基础行情
        try:
            sql = """
                SELECT name, close, changepercent, pe9, pb, roe,
                       mgjzc, mgsy, total_market_cap, turnoverratio
                FROM cn_stock_spot
                WHERE code = %s
                ORDER BY date DESC LIMIT 1
            """
            rows = mdb.executeSqlFetch(sql, (code,))
            if rows:
                r = rows[0]
                result['spot'] = {
                    'name': r[0], 'close': r[1], 'change_pct': r[2],
                    'pe': r[3], 'pb': r[4], 'roe': r[5],
                    'bps': r[6], 'eps': r[7],
                    'market_cap': r[8], 'turnover': r[9],
                }
                result['name'] = r[0]
        except Exception as exc:
            _logger.debug(f'[stockReport] fallback spot 查询异常: {exc}')

        # 资金流向
        try:
            sql = """
                SELECT date, main_net_inflow, super_net_inflow, big_net_inflow
                FROM cn_stock_fund_flow
                WHERE code = %s
                ORDER BY date DESC LIMIT 5
            """
            rows = mdb.executeSqlFetch(sql, (code,))
            if rows:
                result['fund_flow'] = [
                    {'date': str(r[0]), 'main': r[1], 'super': r[2], 'big': r[3]}
                    for r in rows
                ]
        except Exception as exc:
            _logger.debug(f'[stockReport] fallback fund_flow 查询异常: {exc}')

        # 技术指标
        try:
            sql = """
                SELECT macd, macd_signal, kdj_k, kdj_d, kdj_j, rsi_6
                FROM cn_stock_indicators
                WHERE code = %s
                ORDER BY date DESC LIMIT 1
            """
            rows = mdb.executeSqlFetch(sql, (code,))
            if rows:
                r = rows[0]
                result['indicators'] = {
                    'macd': r[0], 'macd_signal': r[1],
                    'kdj_k': r[2], 'kdj_d': r[3], 'kdj_j': r[4],
                    'rsi_6': r[5],
                }
        except Exception as exc:
            _logger.debug(f'[stockReport] fallback indicators 查询异常: {exc}')

        _write_json(self, result)
