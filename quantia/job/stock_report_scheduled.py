#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 4: 定时分析 + AI 评分预警推送。

功能:
1. 关注列表每日自动生成 AI 报告摘要 (scheduled_report_analysis)
2. AI 评分跌破阈值自动推送预警到钉钉 (score_alert_check)

可单独执行::

    python -m quantia.job.stock_report_scheduled --mode report
    python -m quantia.job.stock_report_scheduled --mode alert
    python -m quantia.job.stock_report_scheduled --mode all

集成到 cron/cron.workdayly/run_report_alert 中每日调度。
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

import quantia.lib.database as mdb

_logger = logging.getLogger(__name__)

# ─── 配置 ─────────────────────────────────────────────────────────
_SCORE_TABLE = 'cn_stock_trade_ai_score'
_ATTENTION_TABLE = 'cn_stock_attention'
_REPORT_TABLE = 'cn_stock_ai_report'
_ALERT_EVENT_TABLE = 'cn_stock_notification_event'
_NOTIFICATION_CONFIG_TABLE = 'cn_stock_notification_config'

DEFAULT_SCORE_THRESHOLD = 50  # 评分跌破此值触发预警
DEFAULT_ALERT_COOLDOWN_HOURS = 24  # 同一股票同一方向预警冷却时间
DEFAULT_MAX_STOCKS = 10  # 每日定时分析最大股票数（防 token 耗尽）
DEFAULT_MAX_FAILURES = 5  # 连续失败熔断阈值

_ALLOWED_TOOLS = ['stock_profile', 'kline_fetch', 'web_search', 'sql_query']


def _get_effective_tools() -> list:
    """根据环境配置过滤实际可用的工具列表。web_search 内置博查 Bocha → Bing CN 后端链，始终可用。"""
    return list(_ALLOWED_TOOLS)


# ─── 工具函数 ──────────────────────────────────────────────────────

def _get_attention_codes() -> List[str]:
    """获取关注列表中的股票代码（按最近添加时间排序，不限制数量）。

    关注列表本身不限数量；实际参与定时分析的股票数由
    `scheduled_report_analysis(max_stocks=...)` 控制（按偏好设置截取）。
    """
    sql = f"""SELECT code FROM (
        SELECT code, MAX(datetime) AS latest
        FROM `{_ATTENTION_TABLE}` GROUP BY code ORDER BY latest DESC
    ) t"""
    rows = mdb.executeSqlFetch(sql) or []
    return [r[0] for r in rows if r[0] and len(r[0]) == 6]


def _get_analysis_config() -> Dict[str, Any]:
    """从报告偏好表读取定时分析参数。

    返回 max_stocks / max_failures / analysis_mode / analysis_codes。
    用户可在前端"报告偏好"页面调整；读取失败或未配置时回退默认值。
    """
    config: Dict[str, Any] = {
        'max_stocks': DEFAULT_MAX_STOCKS,
        'max_failures': DEFAULT_MAX_FAILURES,
        'analysis_mode': 'top_score',
        'analysis_codes': [],
    }
    try:
        sql = """
            SELECT analysis_max_stocks, max_failures, analysis_mode, analysis_codes
            FROM `cn_stock_report_preference`
            ORDER BY updated_at DESC LIMIT 1
        """
        rows = mdb.executeSqlFetch(sql)
        if rows:
            if rows[0][0] is not None:
                config['max_stocks'] = max(int(rows[0][0]), 1)
            if rows[0][1] is not None:
                config['max_failures'] = max(int(rows[0][1]), 1)
            mode = rows[0][2]
            if mode in ('top_score', 'specified'):
                config['analysis_mode'] = mode
            raw_codes = rows[0][3]
            if raw_codes:
                try:
                    codes = json.loads(raw_codes)
                    config['analysis_codes'] = [
                        str(c) for c in codes
                        if str(c).isdigit() and len(str(c)) == 6
                    ]
                except (json.JSONDecodeError, TypeError):
                    pass
    except Exception:
        # 字段不存在（旧表）或读取失败 → 用默认值
        pass
    return config


def _get_selection_score_map(codes: List[str]) -> Dict[str, float]:
    """批量获取股票的综合选股评分（code -> total_score，取最新交易日）。

    数据源 cn_stock_selection_score（每日多因子综合打分）。无评分的股票不在返回中。
    """
    if not codes:
        return {}
    try:
        placeholders = ','.join(['%s'] * len(codes))
        sql = f"""
            SELECT s.code, s.total_score
            FROM `cn_stock_selection_score` s
            JOIN (
                SELECT code, MAX(date) AS mx
                FROM `cn_stock_selection_score`
                WHERE code IN ({placeholders})
                GROUP BY code
            ) m ON s.code = m.code AND s.date = m.mx
        """
        rows = mdb.executeSqlFetch(sql, tuple(codes)) or []
        return {r[0]: float(r[1]) for r in rows if r[1] is not None}
    except Exception as exc:
        _logger.debug(f'[定时分析] 读取综合选股评分失败: {exc}')
        return {}


def _select_analysis_codes(max_stocks: int, mode: str,
                           specified_codes: List[str]) -> List[str]:
    """根据选股方式确定本次定时分析的股票代码列表。

    - mode='specified': 直接使用用户指定的股票（最多 max_stocks 只）。
    - mode='top_score': 取关注列表中综合选股评分最高的前 max_stocks 只
      （无评分的股票排在最后，按关注时间兜底排序）。
    """
    if mode == 'specified':
        return specified_codes[:max_stocks]

    # top_score: 关注列表按综合选股评分降序
    codes = _get_attention_codes()
    if not codes:
        return []
    score_map = _get_selection_score_map(codes)
    # 有评分的优先（按评分降序），无评分的保留原顺序（关注时间）排在后面
    ranked = sorted(
        codes,
        key=lambda c: (c in score_map, score_map.get(c, float('-inf'))),
        reverse=True,
    )
    return ranked[:max_stocks]



def _get_user_preference() -> Dict[str, Any]:
    """读取用户报告偏好设置（auto_report, push_enabled 等）。"""
    try:
        sql = """
            SELECT auto_report, push_enabled FROM `cn_stock_report_preference`
            ORDER BY updated_at DESC LIMIT 1
        """
        rows = mdb.executeSqlFetch(sql)
        if rows:
            return {'auto_report': bool(rows[0][0]), 'push_enabled': bool(rows[0][1])}
    except Exception:
        pass
    # 默认：启用自动分析，禁用推送（保守策略）
    return {'auto_report': True, 'push_enabled': False}


def _get_score_threshold() -> int:
    """获取用户配置的评分预警阈值（默认50）。

    优先从 cn_stock_report_preference 读取（前端偏好设置），
    fallback 到 cn_stock_notification_config（通知配置表）。
    """
    # 优先读取偏好设置表
    try:
        sql = """
            SELECT alert_threshold FROM `cn_stock_report_preference`
            ORDER BY updated_at DESC LIMIT 1
        """
        rows = mdb.executeSqlFetch(sql)
        if rows and rows[0][0] is not None:
            return int(rows[0][0])
    except Exception:
        pass

    # fallback: 通知配置表
    try:
        sql = f"""
            SELECT detail_config FROM `{_NOTIFICATION_CONFIG_TABLE}`
            WHERE event_type = 'score_alert' AND enabled = 1
            LIMIT 1
        """
        rows = mdb.executeSqlFetch(sql)
        if rows and rows[0][0]:
            config = json.loads(rows[0][0])
            return int(config.get('threshold', DEFAULT_SCORE_THRESHOLD))
    except Exception:
        pass
    return DEFAULT_SCORE_THRESHOLD


def _build_alert_dedupe_key(code: str, direction: str, trade_date: str) -> str:
    """生成预警去重 key。"""
    raw = f"score_alert|{code}|{direction}|{trade_date}"
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:64]


def _is_alert_cooled_down(code: str, direction: str, cooldown_hours: int = DEFAULT_ALERT_COOLDOWN_HOURS) -> bool:
    """检查该股票预警是否在冷却期内。"""
    try:
        cutoff = datetime.datetime.now() - datetime.timedelta(hours=cooldown_hours)
        sql = f"""
            SELECT COUNT(*) FROM `{_ALERT_EVENT_TABLE}`
            WHERE event_type = 'score_alert'
              AND code = %s AND direction = %s
              AND status IN ('sent', 'pending')
              AND created_at >= %s
        """
        rows = mdb.executeSqlFetch(sql, (code, direction, cutoff))
        return bool(rows and rows[0][0] > 0)
    except Exception:
        return False


def _insert_report(code: str, name: str, content: str, result: Any, source: str) -> None:
    """持久化 AI 报告并抽取结构化字段（评级 / AI评分 / 操作建议等）。

    定时任务原先只写 report_md，导致 cn_stock_ai_report.rating / rating_score
    全为 NULL，前端"AI评分"无内容可显示。此处与 SSE 生成路径一致，调用
    report_parser.extract_structured_fields 抽取结构化字段后再写库。
    """
    try:
        from quantia.lib.ai.report_parser import extract_structured_fields
        structured = extract_structured_fields(content) or {}
    except Exception as exc:
        _logger.debug(f'[定时分析] {code} 结构化抽取失败(降级写入): {exc}')
        structured = {}

    moat_factors_json = json.dumps(structured.get('moat_factors') or {}, ensure_ascii=False)
    tools_json = json.dumps([tc.get('name') for tc in (result.tool_calls or [])])
    mdb.executeSql(
        f"""INSERT INTO `{_REPORT_TABLE}`
            (code, name, report_md, model, provider, tools_used,
             tokens_used, latency_ms,
             rating, rating_score, short_term_advice, mid_term_advice,
             long_term_advice, target_price_low, target_price_high,
             stop_loss_price, moat_score, moat_factors,
             source, data_cutoff_date, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, CURDATE(), NOW())""",
        (
            code, name or '', content,
            result.model or '', result.provider or '',
            tools_json,
            result.total_tokens or 0, 0,
            structured.get('rating'), structured.get('rating_score'),
            structured.get('short_term_advice'), structured.get('mid_term_advice'),
            structured.get('long_term_advice'), structured.get('target_price_low'),
            structured.get('target_price_high'), structured.get('stop_loss_price'),
            structured.get('moat_score'), moat_factors_json,
            source,
        ),
    )


# ─── 功能 1: 定时分析 ─────────────────────────────────────────────

def scheduled_report_analysis(max_stocks: Optional[int] = None,
                              max_failures: Optional[int] = None) -> Dict[str, Any]:
    """为关注列表中的股票自动生成 AI 分析报告。

    - 每日最多生成 max_stocks 只（防止 token 耗尽）
    - 跳过今日已有报告的股票
    - 结果存入 cn_stock_ai_report
    - 仅当用户偏好 auto_report=True 时执行

    max_stocks / max_failures 为 None 时从报告偏好表读取（用户可配置），
    显式传参时优先使用传入值。
    """
    pref = _get_user_preference()
    if not pref.get('auto_report', True):
        _logger.info('[定时分析] 用户偏好已关闭自动分析，跳过')
        return {'generated': 0, 'skipped': 0, 'failed': 0, 'total': 0, 'reason': 'disabled'}

    cfg = _get_analysis_config()
    if max_stocks is None:
        max_stocks = cfg['max_stocks']
    if max_failures is None:
        max_failures = cfg['max_failures']
    max_stocks = max(int(max_stocks), 1)
    max_failures = max(int(max_failures), 1)
    mode = cfg.get('analysis_mode', 'top_score')
    specified_codes = cfg.get('analysis_codes', [])
    _logger.info(
        f'[定时分析] 参数: max_stocks={max_stocks}, max_failures={max_failures}, '
        f'mode={mode}, specified={len(specified_codes)}只'
    )

    codes = _select_analysis_codes(max_stocks, mode, specified_codes)
    if not codes:
        if mode == 'specified':
            _logger.info('[定时分析] 指定股票列表为空，跳过')
        else:
            _logger.info('[定时分析] 关注列表为空，跳过')
        return {'generated': 0, 'skipped': 0, 'failed': 0, 'total': 0}

    today = datetime.date.today().isoformat()
    stats = {'generated': 0, 'skipped': 0, 'failed': 0, 'total': len(codes)}

    for code in codes:
        # 检查今日是否已有报告
        try:
            sql = f"""
                SELECT COUNT(*) FROM `{_REPORT_TABLE}`
                WHERE code = %s AND DATE(created_at) = %s
            """
            rows = mdb.executeSqlFetch(sql, (code, today))
            if rows and rows[0][0] > 0:
                stats['skipped'] += 1
                continue
        except Exception:
            pass

        # 生成报告
        try:
            from quantia.lib.ai import run_agent
            from quantia.lib.ai.feature_switch import check_feature
            check_feature('stock_report')

            result = run_agent(
                user_message=(
                    f"请为 A 股 {code} 生成一份完整的投资分析报告。"
                    f"包含：技术面、基本面、资金面、事件面综合分析，"
                    f"并给出综合评级（看多/看空/中性）和操作建议。"
                ),
                scene='stock_report',
                agent='stock_analyst',
                system=(
                    '你是 Quantia AI 股票分析师。请生成完整的个股分析报告。'
                    '格式要求：使用 Markdown，包含技术指标、财务数据、资金流向、'
                    '事件风险等维度，最后给出综合评级和操作建议。'
                ),
                allowed_tools=_get_effective_tools(),
            )

            # 存入数据库
            content = (result.content or '')[:10000]
            stock_name = ''
            for tc in (result.tool_calls or []):
                if tc.get('name') == 'stock_profile' and tc.get('ok'):
                    stock_name = tc.get('result', {}).get('name', '')
                    break

            _insert_report(code, stock_name, content, result, 'cron')
            stats['generated'] += 1
            _logger.info(f'[定时分析] {code} {stock_name} 报告生成成功')

            # 推送报告摘要到钉钉
            try:
                summary = content[:500]
                push_report_summary_to_dingtalk(code, stock_name, summary)
            except Exception as push_exc:
                _logger.debug(f'[定时分析] {code} 推送失败(不影响主流程): {push_exc}')

        except Exception as exc:
            stats['failed'] += 1
            _logger.warning(f'[定时分析] {code} 报告生成失败: {exc}')

        # 熔断：连续失败过多则提前终止
        if stats['failed'] >= max_failures and stats['generated'] == 0:
            _logger.error(f'[定时分析] 连续失败 {stats["failed"]} 次（阈值 {max_failures}），熔断终止')
            break

        # 简单限速，避免 API 过载
        time.sleep(2)

    _logger.info(f'[定时分析] 完成: {stats}')
    return stats


# ─── 功能 2: AI 评分预警 ──────────────────────────────────────────

def score_alert_check() -> Dict[str, Any]:
    """检查关注列表股票的 AI 评分，跌破阈值则推送钉钉预警。

    逻辑:
    1. 获取关注列表
    2. 查询每只股票最新 AI 评分
    3. 低于阈值 + 未在冷却期 → 推送预警
    """
    from quantia.notification.service import ensure_notification_tables
    ensure_notification_tables()

    codes = _get_attention_codes()
    if not codes:
        _logger.info('[评分预警] 关注列表为空，跳过')
        return {'checked': 0, 'alerted': 0, 'cooled': 0}

    threshold = _get_score_threshold()
    stats = {'checked': 0, 'alerted': 0, 'cooled': 0, 'threshold': threshold}

    for code in codes:
        stats['checked'] += 1
        try:
            sql = f"""
                SELECT score, action, code, reason_summary, decision_phase,
                       created_at
                FROM `{_SCORE_TABLE}`
                WHERE code = %s
                ORDER BY created_at DESC LIMIT 1
            """
            rows = mdb.executeSqlFetch(sql, (code,))
            if not rows:
                continue

            score, action, _, reason_summary, phase, created_at = rows[0]
            if score is None or float(score) >= threshold:
                continue

            # 确定预警方向
            direction = 'score_drop'

            # 冷却检查
            if _is_alert_cooled_down(code, direction):
                stats['cooled'] += 1
                continue

            # 构建预警消息
            stock_name = _get_stock_name(code)
            alert_msg = _build_score_alert_message(
                code, stock_name, float(score), threshold,
                action or '', reason_summary or '', str(created_at)
            )

            # 推送预警
            _send_score_alert(code, stock_name, direction, alert_msg, float(score))
            stats['alerted'] += 1
            _logger.info(f'[评分预警] {code} {stock_name} 评分 {score} < {threshold}，已推送')

        except Exception as exc:
            _logger.warning(f'[评分预警] {code} 检查失败: {exc}')

    _logger.info(f'[评分预警] 完成: {stats}')
    return stats


def _get_stock_name(code: str) -> str:
    """获取股票名称。"""
    try:
        rows = mdb.executeSqlFetch(
            "SELECT name FROM cn_stock_spot WHERE code = %s LIMIT 1", (code,)
        )
        return rows[0][0] if rows else ''
    except Exception:
        return ''


def _build_score_alert_message(
    code: str, name: str, score: float, threshold: int,
    action: str, reason: str, scored_at: str
) -> Dict[str, str]:
    """构建钉钉预警 markdown 消息。"""
    title = f"⚠️ AI 评分预警: {code} {name}"
    action_label = {'reject': '拒绝交易', 'hold': '建议观望', 'pass': '允许交易'}.get(
        action, action or '未知'
    )
    markdown = (
        f"## ⚠️ AI 评分预警\n\n"
        f"**标的**: {code} {name}\n\n"
        f"**当前评分**: {score:.1f} / 100（阈值 {threshold}）\n\n"
        f"**AI 建议**: {action_label}\n\n"
    )
    if reason:
        markdown += f"**摘要**: {reason[:200]}\n\n"
    markdown += (
        f"**评分时间**: {scored_at}\n\n"
        f"---\n\n"
        f"> 请及时关注该股票风险状况。此预警由 Quantia AI 自动生成。"
    )
    return {'title': title, 'markdown': markdown}


def _send_score_alert(code: str, name: str, direction: str, message: Dict[str, str], score: float):
    """发送评分预警到钉钉。"""
    from quantia.notification.channels.dingtalk import DingTalkChannel
    from quantia.notification.service import ensure_notification_tables, _load_config

    ensure_notification_tables()

    # 插入预警事件
    dedupe_key = _build_alert_dedupe_key(code, direction, datetime.date.today().isoformat())
    payload = DingTalkChannel.build_markdown_payload(message['title'], message['markdown'])

    config = _load_config(0, 'score_alert', 'dingtalk')
    status = 'pending' if config.get('enabled') and config.get('webhook') else 'skipped'

    try:
        mdb.executeSql(
            f"""INSERT IGNORE INTO `{_ALERT_EVENT_TABLE}`
                (dedupe_key, paper_id, event_type, channel, trade_date, code,
                 direction, status, payload_json)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                dedupe_key, None, 'score_alert', 'dingtalk',
                datetime.date.today().isoformat(), code,
                direction, status, json.dumps(payload, ensure_ascii=False),
            )
        )
    except Exception as exc:
        _logger.warning(f'[评分预警] 事件入库失败: {exc}')
        return

    if status == 'skipped':
        _logger.info(f'[评分预警] {code} 通知已跳过（未配置 webhook）')
        return

    # 立即发送
    try:
        channel = DingTalkChannel(config['webhook'], config.get('secret', ''))
        result = channel.send(payload)
        new_status = 'sent' if result.ok else 'failed'
        mdb.executeSql(
            f"UPDATE `{_ALERT_EVENT_TABLE}` SET status = %s, sent_at = NOW() WHERE dedupe_key = %s",
            (new_status, dedupe_key)
        )
    except Exception as exc:
        _logger.warning(f'[评分预警] 发送失败: {exc}')


# ─── 功能 3: 钉钉推送报告摘要 ────────────────────────────────────

def push_report_summary_to_dingtalk(code: str, name: str, summary: str, rating: str = '') -> bool:
    """将报告摘要推送到钉钉群。受用户偏好 push_enabled 控制。"""
    # 检查用户偏好
    pref = _get_user_preference()
    if not pref.get('push_enabled', False):
        _logger.debug(f'[报告推送] {code} 用户偏好未启用推送')
        return False

    from quantia.notification.channels.dingtalk import DingTalkChannel
    from quantia.notification.service import _load_config

    config = _load_config(0, 'report_summary', 'dingtalk')
    if not config.get('enabled') or not config.get('webhook'):
        _logger.debug(f'[报告推送] {code} 钉钉推送未启用')
        return False

    title = f"📊 AI 报告: {code} {name}"
    rating_emoji = {'bullish': '🟢看多', 'bearish': '🔴看空', 'neutral': '🟡中性'}.get(
        rating, rating or '—'
    )
    markdown = (
        f"## 📊 AI 分析报告摘要\n\n"
        f"**标的**: {code} {name}\n\n"
        f"**评级**: {rating_emoji}\n\n"
        f"**摘要**:\n\n{summary[:500]}\n\n"
        f"---\n\n"
        f"> 由 Quantia AI 定时分析生成，完整报告请登录系统查看。"
    )

    payload = DingTalkChannel.build_markdown_payload(title, markdown)
    try:
        channel = DingTalkChannel(config['webhook'], config.get('secret', ''))
        result = channel.send(payload)
        return result.ok
    except Exception as exc:
        _logger.warning(f'[报告推送] {code} 钉钉发送失败: {exc}')
        return False


# ─── 功能 4: 热门股票预生成 (optimization_review §13) ──────────────

def pregenerate_hot_stocks(top_n: int = 50,
                           max_failures: Optional[int] = None) -> Dict[str, Any]:
    """收盘后对今日成交额 Top N 股票预生成报告，命中缓存时毫秒级响应。

    - 受 feature_switch 'report_cron_pregenerate' 开关控制
    - 跳过今日已有报告的股票
    - 结果标记 source='batch'
    """
    if max_failures is None:
        max_failures = _get_analysis_config()['max_failures']
    max_failures = max(int(max_failures), 1)
    try:
        from quantia.lib.ai.feature_switch import check_feature
        check_feature('report_cron_pregenerate')
    except Exception as exc:
        _logger.info(f'[热门预生成] 功能未启用: {exc}')
        return {'generated': 0, 'skipped': 0, 'failed': 0, 'reason': 'disabled'}

    # 查询今日成交额 Top N
    sql = """
        SELECT code, name FROM cn_stock_spot
        WHERE amount IS NOT NULL AND amount > 0
        ORDER BY amount DESC LIMIT %s
    """
    rows = mdb.executeSqlFetch(sql, (top_n,)) or []
    if not rows:
        _logger.info('[热门预生成] 无行情数据')
        return {'generated': 0, 'skipped': 0, 'failed': 0}

    today = datetime.date.today().isoformat()
    stats = {'generated': 0, 'skipped': 0, 'failed': 0, 'total': len(rows)}

    for code, name in rows:
        if not code or len(code) != 6:
            continue
        # 跳过今日已有报告
        try:
            exist_rows = mdb.executeSqlFetch(
                f"SELECT COUNT(*) FROM `{_REPORT_TABLE}` WHERE code = %s AND DATE(created_at) = %s",
                (code, today),
            )
            if exist_rows and exist_rows[0][0] > 0:
                stats['skipped'] += 1
                continue
        except Exception:
            pass

        try:
            from quantia.lib.ai import run_agent
            result = run_agent(
                user_message=f"请为 A 股 {code} 生成分析报告。",
                scene='report_cron',
                agent='stock_analyst',
                allowed_tools=_get_effective_tools(),
            )
            content = (result.content or '')[:10000]
            _insert_report(code, name, content, result, 'batch')
            stats['generated'] += 1
            _logger.info(f'[热门预生成] {code} {name} 完成')
        except Exception as exc:
            stats['failed'] += 1
            _logger.warning(f'[热门预生成] {code} 失败: {exc}')

        # 熔断：连续失败过多则提前终止
        if stats['failed'] >= max_failures and stats['generated'] == 0:
            _logger.error(f'[热门预生成] 连续失败 {stats["failed"]} 次（阈值 {max_failures}），熔断终止')
            break

        time.sleep(3)  # 限速，避免 API 过载

    _logger.info(f'[热门预生成] 完成: {stats}')
    return stats


# ─── 入口 ─────────────────────────────────────────────────────────

def run_all(max_stocks: Optional[int] = None,
            max_failures: Optional[int] = None):
    """执行所有定时任务。"""
    _logger.info('=' * 40 + ' 定时分析任务开始 ' + '=' * 40)

    # 1. 定时分析
    report_stats = scheduled_report_analysis(max_stocks=max_stocks, max_failures=max_failures)

    # 2. 评分预警
    alert_stats = score_alert_check()

    _logger.info(f'定时分析结果: {report_stats}')
    _logger.info(f'评分预警结果: {alert_stats}')
    _logger.info('=' * 40 + ' 定时分析任务结束 ' + '=' * 40)

    return {'report': report_stats, 'alert': alert_stats}


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(name)s %(message)s'
    )

    parser = argparse.ArgumentParser(description='Quantia 定时分析 + 评分预警')
    parser.add_argument('--mode', choices=['report', 'alert', 'pregenerate', 'all'], default='all',
                        help='执行模式: report=仅定时分析, alert=仅评分预警, pregenerate=热门预生成, all=全部')
    parser.add_argument('--max-stocks', type=int, default=None,
                        help='定时分析最大股票数（不传则从报告偏好表读取，默认 10）')
    parser.add_argument('--max-failures', type=int, default=None,
                        help='连续失败熔断阈值（不传则从报告偏好表读取，默认 5）')
    parser.add_argument('--top-n', type=int, default=50,
                        help='热门预生成 Top N')
    args = parser.parse_args()

    if args.mode == 'report':
        scheduled_report_analysis(max_stocks=args.max_stocks, max_failures=args.max_failures)
    elif args.mode == 'alert':
        score_alert_check()
    elif args.mode == 'pregenerate':
        pregenerate_hot_stocks(top_n=args.top_n, max_failures=args.max_failures)
    else:
        run_all(max_stocks=args.max_stocks, max_failures=args.max_failures)
