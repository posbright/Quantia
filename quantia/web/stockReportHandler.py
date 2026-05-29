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
import os
import queue
import re
import threading
import time
import uuid
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
_executor = ThreadPoolExecutor(max_workers=4)

_ALLOWED_TOOLS = ['stock_profile', 'kline_fetch', 'web_search', 'sql_query']

_STRUCTURED_REPORT_FIELDS = [
    'rating', 'rating_score', 'short_term_advice', 'mid_term_advice',
    'long_term_advice', 'target_price_low', 'target_price_high',
    'stop_loss_price', 'moat_score', 'moat_factors',
    'report_version', 'prev_report_id',
]


def _decode_json_field(raw: Any) -> Any:
    if raw is None or raw == '':
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return raw


def _structured_report_payload(row: tuple, start: int) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    for idx, field in enumerate(_STRUCTURED_REPORT_FIELDS):
        value = row[start + idx]
        if field == 'moat_factors':
            value = _decode_json_field(value) or {}
        payload[field] = value
    return payload


def _build_fallback_report_from_tools(code: str, stock_name: str, tool_calls: List[Dict[str, Any]]) -> str:
    """Build a deterministic markdown report when LLM returns empty content."""
    profile = None
    for tc in (tool_calls or []):
        if tc.get('name') == 'stock_profile' and tc.get('ok'):
            profile = tc.get('result') or {}
            break
    if not isinstance(profile, dict) or not profile:
        return ''

    spot = profile.get('spot') or {}
    indicators = profile.get('indicators') or {}
    flow = profile.get('fund_flow_recent') or []
    patterns = profile.get('kline_patterns') or []
    financials = profile.get('financials') or {}

    resolved_name = stock_name or spot.get('name') or ''
    title = f"{code} {resolved_name}".strip()

    flow_lines = []
    for row in flow[:5]:
        date = row.get('date', '')
        main = row.get('main_net_inflow')
        if date and isinstance(main, (int, float)):
            sign = '+' if main >= 0 else ''
            flow_lines.append(f"- {date}: {sign}{main:.2f}")
    if not flow_lines:
        flow_lines.append('- 暂无近5日资金流数据')

    pattern_line = '、'.join(patterns[:8]) if patterns else '暂无显著 K 线形态信号'

    price = spot.get('new_price')
    pct = spot.get('change_rate')
    pe = spot.get('pe')
    pb = spot.get('pb')
    roe = financials.get('roe') if isinstance(financials, dict) else None

    macd = indicators.get('macd')
    macd_signal = indicators.get('macd_signal')
    rsi6 = indicators.get('rsi_6')
    kdj_k = indicators.get('kdj_k')

    report_lines = [
        f"# AI 快速分析（降级版）\n",
        f"标的：{title}\n",
        "## 一、行情概览",
        f"- 最新价：{price if price is not None else '-'}",
        f"- 涨跌幅：{pct if pct is not None else '-'}%",
        f"- PE / PB / ROE：{pe if pe is not None else '-'} / {pb if pb is not None else '-'} / {roe if roe is not None else '-'}",
        "",
        "## 二、技术面要点",
        f"- MACD：{macd if macd is not None else '-'}（Signal: {macd_signal if macd_signal is not None else '-'}）",
        f"- RSI(6)：{rsi6 if rsi6 is not None else '-'}",
        f"- KDJ(K)：{kdj_k if kdj_k is not None else '-'}",
        f"- 形态信号：{pattern_line}",
        "",
        "## 三、资金面（近5日主力净流）",
        *flow_lines,
        "",
        "## 四、风险提示",
        "- 当前报告由结构化数据自动生成（AI 正文为空时的降级方案）。",
        "- 建议结合行业景气度、公告事件与交易计划二次验证后决策。",
    ]
    return '\n'.join(report_lines).strip()


def _summarize_tool_errors(tool_calls: List[Dict[str, Any]]) -> str:
    errs: List[str] = []
    for tc in (tool_calls or []):
        if tc.get('ok'):
            continue
        name = tc.get('name', 'unknown')
        err = str(tc.get('error') or '')
        if err:
            errs.append(f"{name}: {err[:80]}")
    if not errs:
        return ''
    return '；'.join(errs[:3])


def _sanitize_error_text(text: str) -> str:
    """Sanitize provider error text before returning to frontend."""
    if not text:
        return ''
    out = text.strip()
    # Mask common key/token fragments
    out = re.sub(r'(sk-[A-Za-z0-9_-]{8,})', 'sk-***', out)
    out = re.sub(r'(api[_-]?key\s*[=:]\s*)([^\s,;]+)', r'\1***', out, flags=re.IGNORECASE)
    out = re.sub(r'(Authorization\s*[:=]\s*Bearer\s+)([^\s,;]+)', r'\1***', out, flags=re.IGNORECASE)
    return out[:160]


def _to_user_friendly_error(exc: Exception) -> str:
    """Map backend exceptions to actionable user-facing messages."""
    raw = _sanitize_error_text(str(exc))
    lower = (raw or '').lower()
    if not raw:
        return '报告生成失败，请稍后重试'

    if 'code 必须是6位数字股票代码' in raw:
        return raw
    if '已被管理员禁用' in raw or '预算已耗尽' in raw:
        return raw
    if 'timeout' in lower or 'timed out' in lower or '超时' in raw:
        return 'AI 服务响应超时，请稍后重试'
    if '未注册的 provider' in raw or 'provider' in lower or 'api_key' in lower or 'authentication' in lower:
        return 'AI 服务配置异常，请联系管理员检查 Provider/API Key'
    if 'quota' in lower or 'rate limit' in lower or '429' in lower:
        return 'AI 服务请求过于频繁，请稍后重试'
    return f'报告生成失败：{raw}'


def _get_effective_tools() -> list:
    """根据环境配置过滤实际可用的工具列表。

    web_search 已内置 DuckDuckGo 搜索后端，始终可用。
    """
    return list(_ALLOWED_TOOLS)


# ─── 并发请求合并（同一 code 生成中时，后续请求等待缓存）─────────
# 每个 Event 关联到注册它的请求；pop 时只删除自己注册的 event
_generating_codes: Dict[str, threading.Event] = {}
_generating_lock = threading.Lock()


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
        rating ENUM('buy','hold','avoid') DEFAULT NULL COMMENT '结构化评级',
        rating_score TINYINT UNSIGNED DEFAULT NULL COMMENT '综合评分(0-100)',
        short_term_advice VARCHAR(500) DEFAULT NULL COMMENT '短期建议摘要',
        mid_term_advice VARCHAR(500) DEFAULT NULL COMMENT '中期建议摘要',
        long_term_advice VARCHAR(500) DEFAULT NULL COMMENT '长期建议摘要',
        target_price_low FLOAT DEFAULT NULL COMMENT '目标价下限',
        target_price_high FLOAT DEFAULT NULL COMMENT '目标价上限',
        stop_loss_price FLOAT DEFAULT NULL COMMENT '止损价',
        moat_score TINYINT DEFAULT NULL COMMENT '护城河评分(0-5)',
        moat_factors JSON DEFAULT NULL COMMENT '护城河因素',
        report_version INT DEFAULT 1 COMMENT '同一股票第N版报告',
        prev_report_id BIGINT DEFAULT NULL COMMENT '上一版报告ID',
        user_feedback TINYINT DEFAULT NULL COMMENT '1=满意, -1=不满意, NULL=未评',
        feedback_reason VARCHAR(200) DEFAULT NULL,
        data_cutoff_date DATE DEFAULT NULL COMMENT '报告依据的最新数据日期',
        source ENUM('user','cron','batch') DEFAULT 'user' COMMENT '生成来源',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_code_date (code, created_at DESC),
        INDEX idx_rating (rating, created_at DESC),
        INDEX idx_moat (moat_score, created_at DESC),
        INDEX idx_source (source, created_at DESC)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """
    try:
        mdb.executeSql(ddl)
    except Exception as exc:
        _logger.warning(f'[stockReport] 建表失败（可能已存在）: {exc}', exc_info=True)


def _ensure_share_column():
    """幂等添加 share_token 列（用于分享链接）。"""
    try:
        with mdb.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"ALTER TABLE `{_REPORT_TABLE}` ADD COLUMN share_token VARCHAR(36) DEFAULT NULL"
                )
            with conn.cursor() as cur:
                cur.execute(
                    f"ALTER TABLE `{_REPORT_TABLE}` ADD UNIQUE INDEX idx_share_token (share_token)"
                )
    except Exception as e:
        if 'Duplicate column' not in str(e) and 'Duplicate key name' not in str(e):
            _logger.debug(f'[stockReport] share_token列添加跳过: {e}')


def _ensure_missing_columns():
    """幂等添加后续版本新增的列（已有表可能缺少这些列）。"""
    _alter_stmts = [
        f"ALTER TABLE `{_REPORT_TABLE}` ADD COLUMN quality_score TINYINT DEFAULT NULL COMMENT '结构校验: 100=通过, 50=部分, 0=失败' AFTER latency_ms",
        f"ALTER TABLE `{_REPORT_TABLE}` ADD COLUMN rating ENUM('buy','hold','avoid') DEFAULT NULL COMMENT '结构化评级' AFTER quality_score",
        f"ALTER TABLE `{_REPORT_TABLE}` ADD COLUMN rating_score TINYINT UNSIGNED DEFAULT NULL COMMENT '综合评分(0-100)' AFTER rating",
        f"ALTER TABLE `{_REPORT_TABLE}` ADD COLUMN short_term_advice VARCHAR(500) DEFAULT NULL COMMENT '短期建议摘要' AFTER rating_score",
        f"ALTER TABLE `{_REPORT_TABLE}` ADD COLUMN mid_term_advice VARCHAR(500) DEFAULT NULL COMMENT '中期建议摘要' AFTER short_term_advice",
        f"ALTER TABLE `{_REPORT_TABLE}` ADD COLUMN long_term_advice VARCHAR(500) DEFAULT NULL COMMENT '长期建议摘要' AFTER mid_term_advice",
        f"ALTER TABLE `{_REPORT_TABLE}` ADD COLUMN target_price_low FLOAT DEFAULT NULL COMMENT '目标价下限' AFTER long_term_advice",
        f"ALTER TABLE `{_REPORT_TABLE}` ADD COLUMN target_price_high FLOAT DEFAULT NULL COMMENT '目标价上限' AFTER target_price_low",
        f"ALTER TABLE `{_REPORT_TABLE}` ADD COLUMN stop_loss_price FLOAT DEFAULT NULL COMMENT '止损价' AFTER target_price_high",
        f"ALTER TABLE `{_REPORT_TABLE}` ADD COLUMN moat_score TINYINT DEFAULT NULL COMMENT '护城河评分(0-5)' AFTER stop_loss_price",
        f"ALTER TABLE `{_REPORT_TABLE}` ADD COLUMN moat_factors JSON DEFAULT NULL COMMENT '护城河因素' AFTER moat_score",
        f"ALTER TABLE `{_REPORT_TABLE}` ADD COLUMN report_version INT DEFAULT 1 COMMENT '同一股票第N版报告' AFTER moat_factors",
        f"ALTER TABLE `{_REPORT_TABLE}` ADD COLUMN prev_report_id BIGINT DEFAULT NULL COMMENT '上一版报告ID' AFTER report_version",
        f"ALTER TABLE `{_REPORT_TABLE}` ADD COLUMN user_feedback TINYINT DEFAULT NULL COMMENT '1=满意, -1=不满意, NULL=未评' AFTER quality_score",
        f"ALTER TABLE `{_REPORT_TABLE}` ADD COLUMN feedback_reason VARCHAR(200) DEFAULT NULL AFTER user_feedback",
        f"ALTER TABLE `{_REPORT_TABLE}` ADD COLUMN source ENUM('user','cron','batch') DEFAULT 'user' COMMENT '生成来源' AFTER data_cutoff_date",
        f"ALTER TABLE `{_REPORT_TABLE}` ADD INDEX idx_rating (rating, created_at DESC)",
        f"ALTER TABLE `{_REPORT_TABLE}` ADD INDEX idx_moat (moat_score, created_at DESC)",
        f"ALTER TABLE `{_REPORT_TABLE}` ADD INDEX idx_source (source, created_at DESC)",
    ]
    for stmt in _alter_stmts:
        try:
            with mdb.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(stmt)
        except Exception as e:
            if 'Duplicate column' not in str(e) and 'Duplicate key name' not in str(e):
                _logger.debug(f'[stockReport] 列迁移跳过: {e}')


_table_ensured = False
_table_lock = threading.Lock()


def _lazy_ensure_table():
    global _table_ensured
    if _table_ensured:
        return
    with _table_lock:
        if not _table_ensured:
            _ensure_report_table()
            _ensure_share_column()
            _ensure_missing_columns()
            _table_ensured = True


def _check_cache(code: str) -> Optional[Dict[str, Any]]:
    """检查缓存：盘中30min/收盘后当日有效。

    quality_score=0 的报告（降级版）不作为有效缓存返回，
    允许用户再次点击"生成报告"时触发真正的 AI 分析。
    """
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
               tokens_used, latency_ms, created_at,
               rating, rating_score, short_term_advice, mid_term_advice,
               long_term_advice, target_price_low, target_price_high,
               stop_loss_price, moat_score, moat_factors,
               report_version, prev_report_id
        FROM `{_REPORT_TABLE}`
        WHERE code = %s AND created_at >= %s
              AND (quality_score IS NULL OR quality_score > 0)
        ORDER BY created_at DESC LIMIT 1
    """
    rows = mdb.executeSqlFetch(sql, (code, cutoff.strftime('%Y-%m-%d %H:%M:%S')))
    if not rows:
        return None
    row = rows[0]
    result = {
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
    result.update(_structured_report_payload(row, 10))
    return result


def _has_data_update(code: str, last_report_time: str) -> tuple:
    """检测自上次报告后是否有新数据更新。

    优先级：财报更新 > 资金流向 > 行情数据。
    Returns: (has_update: bool, reason: str)
    """
    try:
        # 1. 检查财报更新（最重要：新季报 = 新结论）
        rows = mdb.executeSqlFetch(
            "SELECT MAX(report_date) FROM cn_stock_financial WHERE code = %s", (code,))
        if rows and rows[0][0]:
            latest_financial = str(rows[0][0])
            if latest_financial > last_report_time[:10]:
                return True, f"新财报数据({latest_financial})"

        # 2. 检查资金流向最新日期
        rows = mdb.executeSqlFetch(
            "SELECT MAX(date) FROM cn_stock_fund_flow WHERE code = %s", (code,))
        if rows and rows[0][0]:
            latest_flow = str(rows[0][0])
            if latest_flow > last_report_time[:10]:
                return True, f"资金面数据已更新至{latest_flow}"

        # 3. 检查行情数据最新日期
        rows = mdb.executeSqlFetch(
            "SELECT MAX(date) FROM cn_stock_selection WHERE code = %s", (code,))
        if rows and rows[0][0]:
            latest_sel = str(rows[0][0])
            if latest_sel > last_report_time[:10]:
                return True, f"行情数据更新至{latest_sel}"
    except Exception as exc:
        _logger.warning(f'[stockReport] 数据变更检测失败: {exc}', exc_info=True)

    return False, ""


def _validate_report_structure(report_md: Optional[str]) -> int:
    """校验报告结构完整性，返回 quality_score (0/50/100)。

    100 = 包含全部 7 节标题 + 多空对比表 + 短/中/长期建议
     50 = 包含 >= 4 节标题
      0 = 不足 4 节标题
    """
    if not report_md:
        return 0
    import re
    # 检查 7 节标题
    required_headings = ['一、', '二、', '三、', '四、', '五、', '六、', '七、']
    found_headings = sum(1 for h in required_headings if h in report_md)
    # 检查多空对比表
    has_table = bool(re.search(r'看多因素.*看空因素|看空因素.*看多因素', report_md, re.DOTALL))
    # Phase 1 后报告应包含短/中/长期建议；缺少时降为部分通过。
    has_multi_term = all(kw in report_md for kw in ('短期', '中期', '长期'))
    if found_headings >= 7 and has_table and has_multi_term:
        return 100
    elif found_headings >= 4:
        return 50
    return 0


def _save_report(code: str, name: str, report_md: str, model: str,
                 provider: str, tools_used: List[str],
                 tokens_used: int, latency_ms: int) -> int:
    """持久化报告到 DB。"""
    from quantia.lib.ai.report_parser import extract_structured_fields

    _lazy_ensure_table()
    quality_score = _validate_report_structure(report_md)
    structured = extract_structured_fields(report_md)
    moat_factors_json = json.dumps(structured.get('moat_factors') or {}, ensure_ascii=False)
    sql = f"""
        INSERT INTO `{_REPORT_TABLE}`
            (code, name, report_md, model, provider, tools_used,
             tokens_used, latency_ms, quality_score,
             rating, rating_score, short_term_advice, mid_term_advice,
             long_term_advice, target_price_low, target_price_high,
             stop_loss_price, moat_score, moat_factors,
             report_version, prev_report_id, data_cutoff_date)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, CURDATE())
    """
    tools_json = json.dumps(tools_used, ensure_ascii=False)
    # 使用事务锁住同股票上一版报告，保证 report_version/prev_report_id 在并发下连续。
    with mdb.get_connection() as conn:
        try:
            conn.autocommit(False)
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT id, report_version
                    FROM `{_REPORT_TABLE}`
                    WHERE code = %s
                    ORDER BY created_at DESC, id DESC
                    LIMIT 1 FOR UPDATE
                    """,
                    (code,),
                )
                prev = cursor.fetchone()
                prev_report_id = prev[0] if prev else None
                report_version = int(prev[1] or 1) + 1 if prev else 1
                cursor.execute(sql, (
                    code, name, report_md, model, provider, tools_json,
                    tokens_used, latency_ms, quality_score,
                    structured.get('rating'), structured.get('rating_score'),
                    structured.get('short_term_advice'), structured.get('mid_term_advice'),
                    structured.get('long_term_advice'), structured.get('target_price_low'),
                    structured.get('target_price_high'), structured.get('stop_loss_price'),
                    structured.get('moat_score'), moat_factors_json,
                    report_version, prev_report_id,
                ))
                report_id = cursor.lastrowid or 0
            conn.commit()
            return report_id
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.autocommit(True)


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
                      prev_summary: Optional[str] = None,
                      focus_dims: Optional[List[str]] = None,
                      model_overrides: Optional[Dict[str, Any]] = None):
    """在线程中运行 Agent 生成报告，通过 queue 推送进度和文本。"""
    try:
        from quantia.lib.ai import run_agent
        from quantia.lib.ai.feature_switch import check_feature

        # 检查功能开关
        check_feature('stock_report')

        # 发送进度：开始获取数据
        q.put(('progress', {'step': 'stock_profile', 'status': 'running'}))

        user_message = f"请为 A 股 {code} 生成分析报告。"
        # 用户偏好：侧重维度
        if focus_dims:
            dim_labels = {
                'technical': '技术面', 'fundamental': '基本面',
                'fund_flow': '资金面', 'event': '事件面', 'ai_gate': 'AI Gate'
            }
            selected = [dim_labels.get(d, d) for d in focus_dims]
            user_message += f"\n请重点分析以下维度：{'、'.join(selected)}。其他维度可简略。"
        if prev_summary:
            user_message += (
                f"\n\n【增量对比参考】以下是上次分析报告的摘要，"
                f"如发现关键变化（如趋势反转、指标突破、资金流向逆转）请在报告中简要提及：\n"
                f"{prev_summary}"
            )
        started = time.time()

        agent_overrides: Dict[str, Any] = {'max_tokens': 10240, 'timeout': 360}
        if model_overrides:
            agent_overrides.update(model_overrides)

        result = run_agent(
            user_message=user_message,
            scene='stock_report',
            agent='stock_analyst',
            system=_load_analyst_prompt(),
            allowed_tools=_get_effective_tools(),
            overrides=agent_overrides,
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
        content = (result.content or '').strip()
        if not content:
            # Some providers occasionally finish with empty assistant content.
            # Build a deterministic markdown fallback from tool outputs.
            content = _build_fallback_report_from_tools(code, stock_name, result.tool_calls or [])

        if not content:
            diag = _summarize_tool_errors(result.tool_calls or [])
            msg = 'AI 本次返回空正文，请稍后重试'
            if diag:
                msg = f"{msg}（工具执行信息：{diag}）"
            q.put(('error', {'msg': msg}))
        else:
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
        q.put(('error', {'msg': _to_user_friendly_error(exc)}))
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
        if not code or len(code) != 6 or not code.isdigit():
            _write_json(self, {'error': 'code 必须是6位数字股票代码'}, 400)
            return

        # 缓存检查
        # 用户指定了 provider/model 时跳过缓存（期望用新模型重新生成）
        force = body.get('force', False) is True
        has_model_override = bool((body.get('provider') or '').strip() or (body.get('model') or '').strip())
        if not force and not has_model_override:
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

            # 并发请求合并：如果同一 code 正在生成中，等待其完成后返回缓存
            with _generating_lock:
                event = _generating_codes.get(code)
            if event:
                # 等待正在生成的请求完成（最多 120s）
                yield IOLoop.current().run_in_executor(
                    _executor, lambda: event.wait(timeout=120))
                # 再次检查缓存
                cached = _check_cache(code)
                if cached:
                    self.set_header('Content-Type', 'text/event-stream; charset=utf-8')
                    self.set_header('Cache-Control', 'no-cache')
                    self.set_header('X-Accel-Buffering', 'no')
                    self.write('data: ' + json.dumps(
                        {'type': 'cached', 'report': cached}, ensure_ascii=False, default=str
                    ) + '\n\n')
                    yield self.flush()
                    self.write('data: ' + json.dumps({'type': 'done'}) + '\n\n')
                    yield self.flush()
                    return

        # 注册正在生成的 code
        gen_event = threading.Event()
        with _generating_lock:
            _generating_codes[code] = gen_event

        # SSE streaming
        self.set_header('Content-Type', 'text/event-stream; charset=utf-8')
        self.set_header('Cache-Control', 'no-cache')
        self.set_header('X-Accel-Buffering', 'no')

        # 获取上次报告摘要用于增量对比
        prev_summary = _get_previous_report_summary(code)

        # 获取用户偏好的侧重维度
        focus_dims = None
        try:
            pref_sql = "SELECT focus_dimensions FROM `cn_stock_report_preference` ORDER BY updated_at DESC LIMIT 1"
            pref_rows = mdb.executeSqlFetch(pref_sql)
            if pref_rows and pref_rows[0][0]:
                parsed = json.loads(pref_rows[0][0])
                if isinstance(parsed, list) and all(isinstance(d, str) for d in parsed):
                    focus_dims = parsed
        except Exception:
            pass

        # 用户选择的模型/provider
        model_overrides: Optional[Dict[str, Any]] = None
        req_provider = (body.get('provider') or '').strip()
        req_model = (body.get('model') or '').strip()
        if req_provider or req_model:
            model_overrides = {}
            if req_provider:
                model_overrides['provider'] = req_provider
            if req_model:
                model_overrides['model'] = req_model

        q_out = queue.Queue(maxsize=128)
        cancel_event = threading.Event()

        # Start producer
        t = threading.Thread(
            target=_run_agent_report, args=(code, q_out, cancel_event, prev_summary, focus_dims, model_overrides), daemon=True)
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
                'model': meta_info.get('model', ''),
            }, ensure_ascii=False) + '\n\n')
            yield self.flush()
        except Exception as exc:
            _logger.debug(f'[stockReport] 发送 done 事件失败（客户端已断开）: {exc}')
        finally:
            # 释放并发锁，只释放自己注册的 event（避免 force=True 请求覆盖后的竞态）
            with _generating_lock:
                if _generating_codes.get(code) is gen_event:
                    _generating_codes.pop(code, None)
            gen_event.set()


class StockReportHistoryHandler(webBase.BaseHandler, ABC):
    """GET /quantia/api/ai/report/history — 历史报告列表。

    参数:
      code  — 按股票代码筛选（空=全部）
      limit — 每页数量（默认20，最大100）
      offset — 翻页偏移
      days  — 限制天数范围（默认30，仅无 code 时生效；传0=不限）
    """

    @gen.coroutine
    def get(self):
        _lazy_ensure_table()
        code = self.get_argument('code', '').strip()
        try:
            limit = min(100, max(1, int(self.get_argument('limit', '20'))))
            offset = max(0, int(self.get_argument('offset', '0')))
        except (ValueError, TypeError):
            limit, offset = 20, 0
        try:
            days = int(self.get_argument('days', '30'))
        except (ValueError, TypeError):
            days = 30

        conditions: List[str] = []
        params: List[Any] = []
        if code:
            conditions.append('code = %s')
            params.append(code)
        elif days > 0:
            # 无指定代码时，默认仅展示最近 N 天
            conditions.append('created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)')
            params.append(days)

        where = ('WHERE ' + ' AND '.join(conditions)) if conditions else ''

        # 查询总数
        count_sql = f"SELECT COUNT(*) FROM `{_REPORT_TABLE}` {where}"
        count_rows = mdb.executeSqlFetch(count_sql, tuple(params))
        total = count_rows[0][0] if count_rows else 0

        sql = f"""
            SELECT id, code, name, model, tokens_used, latency_ms, created_at,
                   rating, rating_score, short_term_advice, mid_term_advice,
                   long_term_advice, target_price_low, target_price_high,
                   stop_loss_price, moat_score, moat_factors,
                   report_version, prev_report_id
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
                items[-1].update(_structured_report_payload(r, 7))
        _write_json(self, {'items': items, 'total': total, 'limit': limit, 'offset': offset})


class StockReportDetailHandler(webBase.BaseHandler, ABC):
    """GET /quantia/api/ai/report/detail — 单条报告详情。"""

    @gen.coroutine
    def get(self):
        _lazy_ensure_table()
        report_id = self.get_argument('id', '')
        if not report_id:
            _write_json(self, {'error': '缺少 id 参数'}, 400)
            return
        try:
            report_id = int(report_id)
        except (TypeError, ValueError):
            _write_json(self, {'error': 'id 必须是整数'}, 400)
            return
        sql = f"""
            SELECT id, code, name, report_md, model, provider, tools_used,
                   tokens_used, latency_ms, created_at,
                   rating, rating_score, short_term_advice, mid_term_advice,
                   long_term_advice, target_price_low, target_price_high,
                   stop_loss_price, moat_score, moat_factors,
                   report_version, prev_report_id
            FROM `{_REPORT_TABLE}`
            WHERE id = %s
        """
        rows = mdb.executeSqlFetch(sql, (report_id,))
        if not rows:
            _write_json(self, {'error': '报告不存在'}, 404)
            return
        r = rows[0]
        result = {
            'id': r[0], 'code': r[1], 'name': r[2],
            'report_md': r[3], 'model': r[4], 'provider': r[5],
            'tools_used': json.loads(r[6]) if r[6] else [],
            'tokens_used': r[7], 'latency_ms': r[8],
            'created_at': str(r[9]),
        }
        result.update(_structured_report_payload(r, 10))
        _write_json(self, result)


class StockSearchHandler(webBase.BaseHandler, ABC):
    """GET /quantia/api/ai/report/search_stock — 股票搜索 autocomplete。"""

    @gen.coroutine
    def get(self):
        q = (self.get_argument('q', '') or '').strip()[:20]
        if not q or len(q) < 1:
            _write_json(self, {'items': []})
            return

        # 搜索代码或名称（LIKE 匹配，返回 top 8）
        # 转义 SQL LIKE 通配符
        escaped_q = q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        sql = """
            SELECT code, name, industry
            FROM cn_stock_spot
            WHERE (code LIKE %s ESCAPE '\\\\' OR name LIKE %s ESCAPE '\\\\')
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
        q.put(('error', {'msg': '追问失败，请稍后重试'}))
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

        # 类型规范化
        try:
            report_id = int(report_id)
        except (TypeError, ValueError):
            _write_json(self, {'error': 'report_id 必须是整数'}, 400)
            return
        try:
            feedback = int(feedback)
        except (TypeError, ValueError):
            feedback = None

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
                allowed_tools=_get_effective_tools(),
                overrides={'max_tokens': 4096, 'timeout': 120},
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
                'summary': '生成失败，请稍后重试',
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
        codes = [c for c in codes[:20] if isinstance(c, str) and len(c) == 6 and c.isdigit()]
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
        if not code or len(code) != 6 or not code.isdigit():
            _write_json(self, {'error': 'code 必须是6位数字'}, 400)
            return

        result: Dict[str, Any] = {'code': code}

        # 基础行情
        try:
            sql = """
                SELECT name, new_price, change_rate, pe9, pbnewmrq, roe_weight,
                       bvps, basic_eps, total_market_cap, turnoverrate
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
                SELECT date, fund_amount, fund_amount_super, fund_amount_large
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
                SELECT macd, macds, kdjk, kdjd, kdjj, rsi_6
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

        # 财务费用明细
        try:
            sql = """
                SELECT report_date, rd_expense, admin_expense, selling_expense,
                       financial_expense, rd_ratio, revenue, roe, gross_margin
                FROM cn_stock_financial
                WHERE code = %s
                ORDER BY report_date DESC LIMIT 1
            """
            rows = mdb.executeSqlFetch(sql, (code,))
            if rows:
                r = rows[0]
                financials = {}
                keys = ['report_date', 'rd_expense', 'admin_expense', 'selling_expense',
                        'financial_expense', 'rd_ratio', 'revenue', 'roe', 'gross_margin']
                for i, k in enumerate(keys):
                    if r[i] is not None:
                        financials[k] = str(r[i]) if k == 'report_date' else r[i]
                if financials:
                    result['financials'] = financials
        except Exception as exc:
            _logger.debug(f'[stockReport] fallback financials 查询异常: {exc}')

        _write_json(self, result)


class StockScoreHistoryHandler(webBase.BaseHandler, ABC):
    """GET /quantia/api/ai/report/score_history — AI评分历史趋势。

    查询 cn_stock_trade_ai_score 获取某股票近30天评分变化。
    返回: [{date, score, action, reason_summary, decision_phase}]
    """

    @gen.coroutine
    def get(self):
        code = self.get_argument('code', '').strip()
        if not code or len(code) != 6:
            _write_json(self, {'items': []})
            return

        try:
            days = min(90, max(1, int(self.get_argument('days', '30'))))
        except (ValueError, TypeError):
            days = 30

        sql = """
            SELECT decision_date, score, action, reason_summary, decision_phase
            FROM cn_stock_trade_ai_score
            WHERE code = %s AND decision_date >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
              AND status = 'succeeded'
            ORDER BY decision_date ASC, id ASC
        """
        try:
            rows = mdb.executeSqlFetch(sql, (code, days))
        except Exception:
            rows = None

        items = []
        if rows:
            for r in rows:
                items.append({
                    'date': str(r[0]) if r[0] else '',
                    'score': r[1],
                    'action': r[2] or '',
                    'reason': (r[3] or '')[:100],
                    'phase': r[4] or '',
                })
        _write_json(self, {'items': items, 'code': code, 'days': days})


class StockReportTimelineHandler(webBase.BaseHandler, ABC):
    """GET /quantia/api/ai/report/timeline — 同股票评级变化轨迹。

    返回同一股票多次报告的评分/评级变化时间线（含摘要）。
    """

    @gen.coroutine
    def get(self):
        _lazy_ensure_table()
        code = self.get_argument('code', '').strip()
        if not code or len(code) != 6:
            _write_json(self, {'items': []})
            return

        sql = f"""
            SELECT id, created_at, model, tokens_used, latency_ms,
                 LEFT(report_md, 300) AS summary_excerpt,
                 rating, rating_score, moat_score, report_version, prev_report_id
            FROM `{_REPORT_TABLE}`
            WHERE code = %s
            ORDER BY created_at DESC
            LIMIT 20
        """
        rows = mdb.executeSqlFetch(sql, (code,))
        items = []
        if rows:
            for r in rows:
                excerpt = r[5] or ''
                # 提取评级关键词
                rating = r[6] or ''
                if not rating:
                    for tag in ['🟢买入', '🟡观望', '🔴回避', '买入', '观望', '回避']:
                        if tag in excerpt:
                            rating = tag
                            break
                items.append({
                    'id': r[0],
                    'created_at': str(r[1]) if r[1] else '',
                    'model': r[2] or '',
                    'tokens_used': r[3],
                    'latency_ms': r[4],
                    'rating': rating,
                    'rating_score': r[7],
                    'moat_score': r[8],
                    'report_version': r[9],
                    'prev_report_id': r[10],
                    'summary': excerpt[:80].replace('\n', ' ').strip(),
                })
        _write_json(self, {'items': items, 'code': code})


class StockReportShareHandler(webBase.BaseHandler, ABC):
    """POST /quantia/api/ai/report/share — 生成分享链接。

    请求体: {"report_id": 123}
    返回: {"share_token": "uuid", "share_url": "/quantia/api/ai/report/shared/uuid"}
    """

    @gen.coroutine
    def post(self):
        _lazy_ensure_table()
        try:
            body = json.loads(self.request.body or '{}')
        except (json.JSONDecodeError, TypeError):
            _write_json(self, {'error': '无效请求体'}, 400)
            return

        report_id = body.get('report_id')
        if not report_id:
            _write_json(self, {'error': '缺少 report_id'}, 400)
            return
        try:
            report_id = int(report_id)
        except (TypeError, ValueError):
            _write_json(self, {'error': 'report_id 必须是整数'}, 400)
            return

        # 检查是否已有 share_token
        sql = f"SELECT share_token FROM `{_REPORT_TABLE}` WHERE id = %s"
        rows = mdb.executeSqlFetch(sql, (report_id,))
        if not rows:
            _write_json(self, {'error': '报告不存在'}, 404)
            return

        existing_token = rows[0][0]
        if existing_token:
            token = existing_token
        else:
            token = str(uuid.uuid4())
            mdb.executeSql(
                f"UPDATE `{_REPORT_TABLE}` SET share_token = %s WHERE id = %s",
                (token, report_id)
            )

        _write_json(self, {
            'share_token': token,
            'share_url': f'/quantia/api/ai/report/shared/{token}',
        })


class StockReportSharedViewHandler(webBase.BaseHandler, ABC):
    """GET /quantia/api/ai/report/shared/<token> — 只读公开报告（无需登录）。"""

    _UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE)

    @gen.coroutine
    def get(self, token: str):
        _lazy_ensure_table()
        if not token or not self._UUID_RE.match(token):
            _write_json(self, {'error': '无效链接'}, 400)
            return

        sql = f"""
            SELECT id, code, name, report_md, model, tokens_used, latency_ms, created_at,
                   rating, rating_score, short_term_advice, mid_term_advice,
                   long_term_advice, target_price_low, target_price_high,
                   stop_loss_price, moat_score, moat_factors,
                   report_version, prev_report_id
            FROM `{_REPORT_TABLE}`
            WHERE share_token = %s
        """
        rows = mdb.executeSqlFetch(sql, (token,))
        if not rows:
            _write_json(self, {'error': '报告不存在或链接已失效'}, 404)
            return
        r = rows[0]
        result = {
            'id': r[0], 'code': r[1], 'name': r[2],
            'report_md': r[3], 'model': r[4],
            'tokens_used': r[5], 'latency_ms': r[6],
            'created_at': str(r[7]),
            'shared': True,
        }
        result.update(_structured_report_payload(r, 8))
        _write_json(self, result)


# ═══════════════════════════════════════════════════════════════════
# Phase 4: 报告对比（两只股票 side-by-side）
# ═══════════════════════════════════════════════════════════════════

class StockReportCompareHandler(webBase.BaseHandler, ABC):
    """POST /quantia/api/ai/report/compare — 两只股票对比分析。

    请求体: {"codes": ["000001", "600036"]}
    返回 SSE 流式对比报告。
    """

    @gen.coroutine
    def post(self):
        try:
            body = json.loads(self.request.body or '{}')
        except (json.JSONDecodeError, TypeError):
            _write_json(self, {'error': '无效请求体'}, 400)
            return

        codes = body.get('codes', [])
        if not isinstance(codes, list) or len(codes) != 2:
            _write_json(self, {'error': 'codes 必须是包含2个股票代码的数组'}, 400)
            return
        codes = [c.strip() for c in codes if isinstance(c, str) and len(c.strip()) == 6 and c.strip().isdigit()]
        if len(codes) != 2:
            _write_json(self, {'error': '需要2个有效的6位数字股票代码'}, 400)
            return

        self.set_header('Content-Type', 'text/event-stream; charset=utf-8')
        self.set_header('Cache-Control', 'no-cache')
        self.set_header('X-Accel-Buffering', 'no')

        # 进度事件
        self.write('data: ' + json.dumps(
            {'type': 'progress', 'step': 'compare_start', 'status': 'running'},
            ensure_ascii=False) + '\n\n')
        yield self.flush()

        q_out = queue.Queue(maxsize=32)

        def _run_compare():
            try:
                from quantia.lib.ai import run_agent
                from quantia.lib.ai.feature_switch import check_feature
                check_feature('stock_report')

                result = run_agent(
                    user_message=(
                        f"请对比分析 A 股 {codes[0]} 和 {codes[1]} 两只股票。\n"
                        f"要求：\n"
                        f"1. 分别获取两只股票的基本面、技术面、资金面数据\n"
                        f"2. 使用对比表格展示关键指标差异\n"
                        f"3. 从估值、成长性、技术趋势、资金流向四个维度对比\n"
                        f"4. 给出综合对比结论和投资建议\n"
                        f"格式：Markdown，包含对比表格和总结。"
                    ),
                    scene='stock_report',
                    agent='stock_analyst',
                    system=(
                        '你是 Quantia AI 股票对比分析师。请对两只股票进行全方位对比分析。'
                        '使用结构化表格展示差异，给出明确的对比结论。'
                        '格式要求：Markdown，包含对比表格和总结建议。'
                    ),
                    allowed_tools=_get_effective_tools(),
                    overrides={'max_tokens': 4096, 'timeout': 120},
                )
                content = result.content or ''
                q_out.put(('done', {
                    'report_md': content,
                    'codes': codes,
                    'tokens_used': result.total_tokens or 0,
                    'model': result.model or '',
                }))
            except Exception as exc:
                _logger.warning(f'[stockReport] 对比分析失败: {exc}', exc_info=True)
                q_out.put(('error', '对比分析失败，请稍后重试'))

        t = threading.Thread(target=_run_compare, daemon=True)
        t.start()

        loop = IOLoop.current()

        def _wait():
            import queue as _q
            try:
                return q_out.get(block=True, timeout=120)
            except _q.Empty:
                return ('error', '对比分析超时')

        item = yield loop.run_in_executor(_executor, _wait)
        kind, payload = item

        try:
            if kind == 'done':
                self.write('data: ' + json.dumps(
                    {'type': 'done', **payload}, ensure_ascii=False) + '\n\n')
            else:
                self.write('data: ' + json.dumps(
                    {'type': 'error', 'msg': payload}, ensure_ascii=False) + '\n\n')
            yield self.flush()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════
# Phase 4: 自定义报告偏好
# ═══════════════════════════════════════════════════════════════════

_PREFERENCE_TABLE = 'cn_stock_report_preference'


def _ensure_preference_table():
    """确保用户偏好表存在。"""
    if not mdb.checkTableIsExist(_PREFERENCE_TABLE):
        mdb.executeSql(f'''
            CREATE TABLE IF NOT EXISTS `{_PREFERENCE_TABLE}` (
                `id` INT AUTO_INCREMENT PRIMARY KEY,
                `user_id` VARCHAR(64) DEFAULT 'default',
                `focus_dimensions` TEXT COMMENT '侧重维度JSON: ["technical","fundamental","fund_flow","event","ai_gate"]',
                `language` VARCHAR(16) DEFAULT 'zh' COMMENT '报告语言: zh/en',
                `voice_enabled` TINYINT(1) DEFAULT 0 COMMENT '是否启用语音播报',
                `alert_threshold` INT DEFAULT 50 COMMENT '评分预警阈值',
                `auto_report` TINYINT(1) DEFAULT 0 COMMENT '是否启用定时自动分析',
                `push_enabled` TINYINT(1) DEFAULT 0 COMMENT '是否启用钉钉推送',
                `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
                `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY `uq_user` (`user_id`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        ''')


class StockReportPreferenceHandler(webBase.BaseHandler, ABC):
    """GET/POST /quantia/api/ai/report/preference — 用户报告偏好设置。

    GET: 获取当前偏好
    POST: 保存偏好 {"focus_dimensions": [...], "language": "zh", ...}
    """

    @gen.coroutine
    def get(self):
        _ensure_preference_table()
        user_id = (self.get_argument('user_id', 'default') or 'default')[:64]
        if not user_id.replace('_', '').replace('-', '').isalnum():
            user_id = 'default'
        sql = f"""
            SELECT focus_dimensions, language, voice_enabled, alert_threshold,
                   auto_report, push_enabled
            FROM `{_PREFERENCE_TABLE}`
            WHERE user_id = %s
        """
        rows = mdb.executeSqlFetch(sql, (user_id,))
        if rows:
            r = rows[0]
            try:
                dims = json.loads(r[0]) if r[0] else ['technical', 'fundamental', 'fund_flow']
            except (json.JSONDecodeError, TypeError):
                dims = ['technical', 'fundamental', 'fund_flow']
            _write_json(self, {
                'focus_dimensions': dims,
                'language': r[1] or 'zh',
                'voice_enabled': bool(r[2]),
                'alert_threshold': r[3] or 50,
                'auto_report': bool(r[4]),
                'push_enabled': bool(r[5]),
            })
        else:
            _write_json(self, {
                'focus_dimensions': ['technical', 'fundamental', 'fund_flow'],
                'language': 'zh',
                'voice_enabled': False,
                'alert_threshold': 50,
                'auto_report': False,
                'push_enabled': False,
            })

    @gen.coroutine
    def post(self):
        _ensure_preference_table()
        try:
            body = json.loads(self.request.body or '{}')
        except (json.JSONDecodeError, TypeError):
            _write_json(self, {'error': '无效请求体'}, 400)
            return

        user_id = (body.get('user_id') or 'default')[:64]
        if not user_id.replace('_', '').replace('-', '').isalnum():
            user_id = 'default'
        allowed_dims = ['technical', 'fundamental', 'fund_flow', 'event', 'ai_gate']
        dims = body.get('focus_dimensions', ['technical', 'fundamental', 'fund_flow'])
        dims = [d for d in dims if d in allowed_dims]

        language = body.get('language', 'zh')
        if language not in ('zh', 'en'):
            language = 'zh'

        voice_enabled = 1 if body.get('voice_enabled') else 0
        try:
            alert_threshold = min(max(int(body.get('alert_threshold', 50)), 10), 90)
        except (ValueError, TypeError):
            alert_threshold = 50
        auto_report = 1 if body.get('auto_report') else 0
        push_enabled = 1 if body.get('push_enabled') else 0

        sql = f"""
            INSERT INTO `{_PREFERENCE_TABLE}`
                (user_id, focus_dimensions, language, voice_enabled,
                 alert_threshold, auto_report, push_enabled)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                focus_dimensions = VALUES(focus_dimensions),
                language = VALUES(language),
                voice_enabled = VALUES(voice_enabled),
                alert_threshold = VALUES(alert_threshold),
                auto_report = VALUES(auto_report),
                push_enabled = VALUES(push_enabled)
        """
        try:
            mdb.executeSql(sql, (
                user_id, json.dumps(dims), language, voice_enabled,
                alert_threshold, auto_report, push_enabled,
            ))
            _write_json(self, {'ok': True})
        except Exception as exc:
            _logger.warning(f'[preference] 保存失败: {exc}')
            _write_json(self, {'error': '保存失败'}, 500)


# ═══════════════════════════════════════════════════════════════════
# Phase 4: 多语言摘要（英文版）
# ═══════════════════════════════════════════════════════════════════

class StockReportTranslateHandler(webBase.BaseHandler, ABC):
    """POST /quantia/api/ai/report/translate — 报告翻译为英文。

    请求体: {"report_id": 123} 或 {"report_md": "原始markdown..."}
    返回: {"translated_md": "...", "language": "en"}
    """

    @gen.coroutine
    def post(self):
        try:
            body = json.loads(self.request.body or '{}')
        except (json.JSONDecodeError, TypeError):
            _write_json(self, {'error': '无效请求体'}, 400)
            return

        report_md = body.get('report_md', '')
        report_id = body.get('report_id')

        # 如果给了 report_id 就从 DB 加载
        if report_id and not report_md:
            try:
                report_id = int(report_id)
            except (TypeError, ValueError):
                _write_json(self, {'error': 'report_id 必须是整数'}, 400)
                return
            _lazy_ensure_table()
            sql = f"SELECT report_md FROM `{_REPORT_TABLE}` WHERE id = %s"
            rows = mdb.executeSqlFetch(sql, (report_id,))
            if rows:
                report_md = rows[0][0] or ''
            else:
                _write_json(self, {'error': '报告不存在'}, 404)
                return

        if not report_md or len(report_md.strip()) < 20:
            _write_json(self, {'error': '报告内容为空或太短'}, 400)
            return

        # 使用 AI 翻译（限制长度防止 token 过大）
        source_text = report_md[:5000]

        q_out = queue.Queue(maxsize=4)

        def _run_translate():
            try:
                from quantia.lib.ai import run_agent
                from quantia.lib.ai.feature_switch import check_feature
                check_feature('stock_report')

                result = run_agent(
                    user_message=(
                        f"Please translate the following Chinese stock analysis report "
                        f"into professional English. Keep the Markdown format, tables, "
                        f"and structure intact. Do not add or remove content.\n\n"
                        f"---\n{source_text}\n---"
                    ),
                    scene='stock_report',
                    agent='stock_analyst',
                    system=(
                        'You are a professional financial translator. '
                        'Translate Chinese stock reports into clear, professional English. '
                        'Preserve all Markdown formatting, tables, and data. '
                        'Use standard financial terminology.'
                    ),
                    allowed_tools=[],
                )
                q_out.put(('ok', result.content or ''))
            except Exception as exc:
                _logger.warning(f'[stockReport] 翻译失败: {exc}', exc_info=True)
                q_out.put(('error', '翻译失败，请稍后重试'))

        t = threading.Thread(target=_run_translate, daemon=True)
        t.start()

        loop = IOLoop.current()

        def _wait():
            import queue as _q
            try:
                return q_out.get(block=True, timeout=60)
            except _q.Empty:
                return ('error', '翻译超时')

        item = yield loop.run_in_executor(_executor, _wait)
        kind, payload = item

        if kind == 'ok':
            _write_json(self, {'translated_md': payload, 'language': 'en'})
        else:
            _write_json(self, {'error': payload}, 500)


# ═══════════════════════════════════════════════════════════════════
# Phase 4: 语音播报文本提取
# ═══════════════════════════════════════════════════════════════════

class StockReportSpeechTextHandler(webBase.BaseHandler, ABC):
    """POST /quantia/api/ai/report/speech_text — 提取报告语音播报文本。

    将 Markdown 报告转换为适合 Web Speech API 朗读的纯文本。
    请求体: {"report_id": 123} 或 {"report_md": "..."}
    返回: {"speech_text": "...", "estimated_duration_sec": 45}
    """

    @gen.coroutine
    def post(self):
        try:
            body = json.loads(self.request.body or '{}')
        except (json.JSONDecodeError, TypeError):
            _write_json(self, {'error': '无效请求体'}, 400)
            return

        report_md = body.get('report_md', '')
        report_id = body.get('report_id')

        if report_id and not report_md:
            try:
                report_id = int(report_id)
            except (TypeError, ValueError):
                _write_json(self, {'error': 'report_id 必须是整数'}, 400)
                return
            _lazy_ensure_table()
            sql = f"SELECT report_md FROM `{_REPORT_TABLE}` WHERE id = %s"
            rows = mdb.executeSqlFetch(sql, (report_id,))
            if rows:
                report_md = rows[0][0] or ''
            else:
                _write_json(self, {'error': '报告不存在'}, 404)
                return

        if not report_md:
            _write_json(self, {'error': '报告内容为空'}, 400)
            return

        # Markdown → 纯文本（去除标记语法）
        import re
        text = report_md
        # 去除代码块
        text = re.sub(r'```[\s\S]*?```', '', text)
        # 去除行内代码
        text = re.sub(r'`[^`]+`', '', text)
        # 去除图片/链接
        text = re.sub(r'!\[.*?\]\(.*?\)', '', text)
        text = re.sub(r'\[([^\]]+)\]\(.*?\)', r'\1', text)
        # 去除 HTML 标签
        text = re.sub(r'<[^>]+>', '', text)
        # 去除标题符号
        text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
        # 去除加粗/斜体
        text = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', text)
        # 去除表格分隔线
        text = re.sub(r'\|?[-:]+\|[-:|]+\|?', '', text)
        # 去除表格管道符
        text = re.sub(r'\|', '，', text)
        # 去除多余空行
        text = re.sub(r'\n{3,}', '\n\n', text)
        # 清理空白
        text = text.strip()

        # 估算朗读时长（中文约 3 字/秒）
        char_count = len(text.replace('\n', '').replace(' ', ''))
        estimated_sec = max(10, char_count // 3)

        _write_json(self, {
            'speech_text': text[:3000],  # 限制长度
            'estimated_duration_sec': estimated_sec,
            'char_count': char_count,
        })


class StockIndustryPercentileHandler(webBase.BaseHandler, ABC):
    """GET /quantia/api/ai/report/industry_percentile?code=xxx

    返回个股 PE/PB/ROE 在所属行业中的分位数排名。
    用于报告内关键数字的交互式 Tooltip（§10.4）。
    """

    @gen.coroutine
    def get(self):
        code = self.get_argument('code', '').strip()
        if not code or len(code) != 6 or not code.isdigit():
            _write_json(self, {'error': 'code 必须是6位数字'}, 400)
            return

        try:
            result = yield IOLoop.current().run_in_executor(
                _executor, self._compute_percentile, code)
            _write_json(self, result)
        except Exception as exc:
            _logger.warning(f'[industry_percentile] 计算失败 code={code}: {exc}')
            _write_json(self, {'error': '计算行业分位数失败'}, 500)

    @staticmethod
    def _compute_percentile(code: str) -> Dict[str, Any]:
        """计算 PE/PB/ROE 在同行业中的百分位排名。"""
        import math

        # 1. 获取该股票的行业分类
        sql_industry = """
            SELECT industry, pe9, pbnewmrq, roe_weight, name
            FROM cn_stock_spot
            WHERE code = %s
            ORDER BY date DESC LIMIT 1
        """
        rows = mdb.executeSqlFetch(sql_industry, (code,))
        if not rows:
            return {'code': code, 'industry': None, 'metrics': {}}

        industry = rows[0][0]
        my_pe = rows[0][1]
        my_pb = rows[0][2]
        my_roe = rows[0][3]
        name = rows[0][4] or ''

        if not industry:
            return {'code': code, 'name': name, 'industry': None, 'metrics': {}}

        # 2. 获取同行业所有股票的 PE/PB/ROE（最新交易日）
        sql_peers = """
            SELECT pe9, pbnewmrq, roe_weight
            FROM cn_stock_spot
            WHERE industry = %s
              AND date = (SELECT MAX(date) FROM cn_stock_spot WHERE code = %s)
        """
        peers = mdb.executeSqlFetch(sql_peers, (industry, code))
        if not peers:
            return {'code': code, 'name': name, 'industry': industry, 'metrics': {}}

        def _percentile(my_val, all_vals):
            """计算百分位排名（0~100），越低表示越便宜/越低。"""
            if my_val is None:
                return None
            valid = [v for v in all_vals if v is not None
                     and not (isinstance(v, float) and (math.isnan(v) or math.isinf(v)))]
            if len(valid) < 3:
                return None
            valid.sort()
            count_below = sum(1 for v in valid if v < my_val)
            return round(count_below / len(valid) * 100, 1)

        def _median(vals):
            valid = sorted(v for v in vals if v is not None
                           and not (isinstance(v, float) and (math.isnan(v) or math.isinf(v))))
            if not valid:
                return None
            n = len(valid)
            if n % 2 == 1:
                return round(valid[n // 2], 2)
            return round((valid[n // 2 - 1] + valid[n // 2]) / 2, 2)

        pe_vals = [r[0] for r in peers if r[0] is not None and r[0] > 0]
        pb_vals = [r[1] for r in peers if r[1] is not None and r[1] > 0]
        roe_vals = [r[2] for r in peers if r[2] is not None]

        metrics = {}
        if my_pe is not None and my_pe > 0:
            metrics['pe'] = {
                'value': round(float(my_pe), 2),
                'percentile': _percentile(my_pe, pe_vals),
                'industry_median': _median(pe_vals),
                'peer_count': len(pe_vals),
            }
        if my_pb is not None and my_pb > 0:
            metrics['pb'] = {
                'value': round(float(my_pb), 2),
                'percentile': _percentile(my_pb, pb_vals),
                'industry_median': _median(pb_vals),
                'peer_count': len(pb_vals),
            }
        if my_roe is not None:
            metrics['roe'] = {
                'value': round(float(my_roe), 2),
                'percentile': _percentile(my_roe, roe_vals),
                'industry_median': _median(roe_vals),
                'peer_count': len(roe_vals),
            }

        return {
            'code': code,
            'name': name,
            'industry': industry,
            'peer_count': len(peers),
            'metrics': metrics,
        }
