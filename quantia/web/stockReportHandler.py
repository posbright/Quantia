#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 个股分析报告 Handler — SSE 流式输出 + 缓存 + 搜索。

路由（web_service.py 中注册）::

    POST /quantia/api/ai/report/generate      → SSE 流式生成报告
    GET  /quantia/api/ai/report/history        → 历史报告列表
    GET  /quantia/api/ai/report/detail         → 单条报告详情
    GET  /quantia/api/ai/report/search_stock   → 股票搜索 autocomplete
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

# Agent system prompt for stock analysis
_ANALYST_SYSTEM_PROMPT = """你是 Quantia 平台的 AI 股票分析师。基于用户指定的 A 股代码，使用工具获取数据后生成结构化分析报告。

## 报告结构（严格遵循）

### 📊 {name} ({code}) 分析报告

#### 一、核心数据
- 当前价格、今日涨跌（来自 stock_profile）
- 市值、PE、PB
- 近期资金流向趋势

#### 二、技术面分析
- K线趋势判断（上涨/下跌/震荡/突破）
- 关键指标信号（MACD金叉/死叉、KDJ超买超卖、RSI状态）
- K线形态信号（如有）
- 支撑位/压力位估算

#### 三、资金面
- 近5日主力净流入/流出趋势
- 大单/特大单方向

#### 四、近期事件（如 web_search 可用）
- 近期重大新闻/公告（仅直接相关的）

#### 五、多空对比

| 🟢 看多因素 | 🔴 看空因素 |
|------------|------------|
| (具体事实+数据支撑) | (具体事实+数据支撑) |

#### 六、综合判断与操作建议
- **评级**: 🟢买入 / 🟡观望 / 🔴回避（一句话理由）
- **已持仓**: 建议操作
- **观望者**: 入场条件
- **短线**: 机会与风险

#### 七、风险提示
- 核心风险因素（1-3条）

## 工具使用规则
1. 必须先调用 `stock_profile` 获取基础数据
2. 如需更长K线历史，调用 `kline_fetch`（limit=120）
3. `web_search` 用于搜索新闻（若不可用则跳过第四节，不要编造）
4. 所有数据结论必须标注来源工具，禁止编造价格/事件
5. 对高估值成长股保持中立，不因 PE 高就看空

## 输出格式
- 使用 Markdown
- 表格用标准 Markdown 语法
- 数字精确到小数点后 2 位
- 总长度 800-1500 字
"""

_ALLOWED_TOOLS = ['stock_profile', 'kline_fetch', 'web_search']


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
        data_cutoff_date DATE DEFAULT NULL COMMENT '报告依据的最新数据日期',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_code_date (code, created_at DESC)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """
    try:
        mdb.executeSql(ddl)
    except Exception as exc:
        _logger.warning(f'[stockReport] 建表失败（可能已存在）: {exc}')


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


def _run_agent_report(code: str, q: queue.Queue, cancel: threading.Event):
    """在线程中运行 Agent 生成报告，通过 queue 推送进度和文本。"""
    try:
        from quantia.lib.ai import run_agent
        from quantia.lib.ai.feature_switch import check_feature

        # 检查功能开关
        check_feature('stock_report')

        # 发送进度：开始
        q.put(('progress', {'step': 'stock_profile', 'status': 'running'}))

        user_message = f"请为 A 股 {code} 生成分析报告。"
        started = time.time()

        result = run_agent(
            user_message=user_message,
            scene='stock_report',
            agent='stock_analyst',
            system=_ANALYST_SYSTEM_PROMPT,
            allowed_tools=_ALLOWED_TOOLS,
        )

        elapsed_ms = int((time.time() - started) * 1000)

        # 从 tool_calls 构建进度事件
        tools_used = []
        for tc in (result.tool_calls or []):
            name = tc.get('name', 'unknown')
            tools_used.append(name)

        # 发送完成进度
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
                # 返回缓存报告 (非 SSE，直接 JSON)
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

        q_out = queue.Queue(maxsize=128)
        cancel_event = threading.Event()

        # Start producer
        t = threading.Thread(
            target=_run_agent_report, args=(code, q_out, cancel_event), daemon=True)
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
                return (_STREAM_SENTINEL, None)

        while True:
            try:
                item = yield loop.run_in_executor(_executor, _queue_get)
            except Exception:
                # Connection closed or other error
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
            except Exception:
                # Client disconnected during write/flush
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
                _logger.warning(f'[stockReport] 保存报告失败: {exc}')

        # 发送 done (best effort — client may already be gone)
        try:
            self.write('data: ' + json.dumps({
                'type': 'done',
                'report_id': report_id,
                'tokens_used': meta_info.get('tokens_used', 0),
                'latency_ms': meta_info.get('latency_ms', 0),
            }, ensure_ascii=False) + '\n\n')
            yield self.flush()
        except Exception:
            pass


class StockReportHistoryHandler(webBase.BaseHandler, ABC):
    """GET /quantia/api/ai/report/history — 历史报告列表。"""

    @gen.coroutine
    def get(self):
        _lazy_ensure_table()
        code = self.get_argument('code', '')
        limit = min(50, max(1, int(self.get_argument('limit', '20'))))
        offset = max(0, int(self.get_argument('offset', '0')))

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
            SELECT code, name
            FROM cn_stock_spot
            WHERE (code LIKE %s OR name LIKE %s)
            ORDER BY total_market_cap DESC
            LIMIT 8
        """
        pattern = f'%{escaped_q}%'
        rows = mdb.executeSqlFetch(sql, (pattern, pattern))
        items = []
        if rows:
            seen = set()
            for r in rows:
                if r[0] not in seen:
                    seen.add(r[0])
                    items.append({'code': r[0], 'name': r[1] or ''})
        _write_json(self, {'items': items})
