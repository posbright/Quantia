#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P6 每日基金精选榜钉钉推送（对齐既有推送链路，不新造轮子）。

蓝图 §7.3/§7.4：清晨段（T+1）在 `analysis_fund_pick_job` 生成榜单后触发。
只读 `cn_fund_daily_pick`（Analysis/Web 管道，不调外部行情 API），构建**紧凑摘要**
（每桶 Top3 + 详情深链），复用现网通知基础设施：

- 配置门控：`notification.service._load_config(0, 'fund_daily_pick', 'dingtalk')`，
  未启用（enabled/webhook 缺）则记 skipped 不发送——避免未经同意每日触达。
- 幂等/重试：复用 `cn_stock_notification_event`（`dedupe_key` 唯一 `INSERT IGNORE`
  天然幂等 + status/retry_count/next_retry_at）。dedupe_key = sha256(
  'fund_daily_pick|dingtalk|<pick_date>')；并发/重复调度被挡下（rowcount==0）。
- 发送：`DingTalkChannel`（单群广播 + 全局开关模型，非 per-user，对齐蓝图口径修正）。

深链：详情 `{BASE}/#/fund/rank?code=XXXXXX`（前端已支持 `route.query.code` 自动开
抽屉、`route.query.pick` 定位精选分区）；整榜 `{BASE}/#/fund/rank?pick=1`。
BASE 取 `QUANTIA_WEB_BASE_URL`（未配置回退 `http://<host>:9988`，生产须配公网域名）。

**非买卖措辞**，带风险免责（对齐 F13 / labels.RISK_DISCLAIMER）。货币型不做点位
择时（不显示"低吸/高估"档位徽章，改显近1年收益，对齐 §7.1bis/§7.3）。

用法：
    python notify_fund_pick_job.py                # 推最新运行日榜单
    python notify_fund_pick_job.py --date=2026-07-09
    python notify_fund_pick_job.py --dry-run      # 只构建不发送（打印 markdown）
"""
import datetime
import hashlib
import logging
import math
import os
import os.path
import socket
import sys
from urllib.parse import quote

cpath_current = os.path.dirname(os.path.dirname(__file__))
cpath = os.path.abspath(os.path.join(cpath_current, os.pardir))
sys.path.append(cpath)
try:
    from quantia.lib.log_config import setup_logging
    setup_logging('analysis')
except Exception:
    log_path = os.path.join(cpath_current, 'log')
    os.makedirs(log_path, exist_ok=True)
    logging.basicConfig(
        format='%(asctime)s [%(levelname)s] %(message)s',
        filename=os.path.join(log_path, 'fund_pick_push.log'),
        level=logging.INFO,
    )

import quantia.core.tablestructure as tbs
import quantia.lib.database as mdb
from quantia.core.fund import labels
from quantia.lib.job_tracker import record_task_start, record_task_end

__author__ = 'Quantia'
__date__ = '2026/07/10'

logger = logging.getLogger(__name__)

_JOB_NAME = 'run_fund_pick_push'
_EVENT_TYPE = 'fund_daily_pick'
_CHANNEL = 'dingtalk'
_PICK_TABLE = tbs.TABLE_CN_FUND_DAILY_PICK['name']
_RANK_TABLE = tbs.TABLE_CN_FUND_RANK['name']
_MONEY_TYPE = '货币型'
_TOP_N_PER_BUCKET = 3
_LAG_WARN_DAYS = 5
# 桶展示顺序（与 fundDailyPickHandler._TYPE_ORDER 一致，其余类型按字典序追加）
_TYPE_ORDER = ['股票型', '混合型', '指数型', 'QDII', 'FOF', '债券型', '货币型']
# 档位徽章 emoji（对齐 timing.tier_of 输出与原型色语义：低吸绿/定投橙/观望灰/高估红）
_TIER_EMOJI = {'低吸': '🟢', '定投': '🟠', '观望': '⚪', '高估勿追': '🔴'}


def _to_date(v):
    if v is None:
        return None
    if isinstance(v, datetime.datetime):
        return v.date()
    if isinstance(v, datetime.date):
        return v
    try:
        return datetime.datetime.strptime(str(v)[:10], '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None


def _num(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if not math.isfinite(f) else f


def _base_url():
    """前端基址：优先 QUANTIA_WEB_BASE_URL，未配置回退 http://<host>:9988。

    与 stock_report_scheduled._build_report_detail_url 同源策略（剥离误配的
    /quantia 段，避免拼出命中 SPA fallback 的 404 链接）。
    """
    base = (os.environ.get('QUANTIA_WEB_BASE_URL') or '').rstrip('/')
    if not base:
        try:
            host = socket.gethostname() or '127.0.0.1'
        except Exception:
            host = '127.0.0.1'
        base = f'http://{host}:9988'
    if base.lower().endswith('/quantia'):
        base = base[:-len('/quantia')].rstrip('/')
    return base


def _fund_detail_url(code, name='', base=None):
    base = base or _base_url()
    url = f"{base}/#/fund/rank?code={quote(str(code))}"
    if name:
        url += f"&name={quote(str(name))}"
    return url


def _pick_list_url(base=None):
    base = base or _base_url()
    return f"{base}/#/fund/rank?pick=1"


def _dedupe_key(pick_date):
    raw = f"{_EVENT_TYPE}|{_CHANNEL}|{pick_date}"
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:64]


def _safe_link_text(s):
    """转义 markdown 链接显示文本里的方括号，避免破坏 [text](url) 结构。"""
    return str(s).replace('[', '【').replace(']', '】')


def _fetch_seven_day_annual(codes):
    """读货币型基金最新 7 日年化（cn_fund_rank.seven_day_annual）。

    只读 MySQL（规则 1），SELECT 显式列（规则 7）。返回 {code: float}。
    取每只基金 cn_fund_rank 中最新 date 的 seven_day_annual。
    """
    codes = [c for c in (codes or []) if c]
    if not codes or not mdb.checkTableIsExist(_RANK_TABLE):
        return {}
    placeholders = ', '.join(['%s'] * len(codes))
    rows = mdb.executeSqlFetch(
        f"SELECT r.`code`, r.`seven_day_annual` FROM `{_RANK_TABLE}` r "
        f"JOIN (SELECT `code`, MAX(`date`) AS d FROM `{_RANK_TABLE}` "
        f"WHERE `code` IN ({placeholders}) GROUP BY `code`) m "
        f"ON r.`code` = m.`code` AND r.`date` = m.d",
        tuple(codes)) or []
    out = {}
    for code, sda in rows:
        v = _num(sda)
        if v is not None:
            out[code] = v
    return out


def read_latest_picks(pick_date=None):
    """读 cn_fund_daily_pick 指定/最新运行日，按桶返回 Top-N（默认 Top3）。

    返回 (pick_date, buckets)。buckets 为 [{fund_type, timing_applicable,
    picks:[{code,name,quality_score,timing_tier,timing_score,rate_1y,
    max_drawdown,data_lag_days,nav_as_of,seven_day_annual}]}]，按 _TYPE_ORDER
    排序。无数据返回 (None, [])。只读 MySQL（规则 1），SELECT 显式列（规则 7）。
    """
    if not mdb.checkTableIsExist(_PICK_TABLE):
        return None, []
    pd = _to_date(pick_date)
    if pd is None:
        drow = mdb.executeSqlFetch(f"SELECT MAX(`date`) FROM `{_PICK_TABLE}`")
        pd = _to_date(drow[0][0]) if drow and drow[0] else None
    if pd is None:
        return None, []

    rows = mdb.executeSqlFetch(
        f"SELECT `fund_type`, `rank_in_type`, `code`, `name`, `quality_score`, "
        f"`timing_tier`, `timing_score`, `rate_1y`, `max_drawdown`, "
        f"`data_lag_days`, `nav_as_of` "
        f"FROM `{_PICK_TABLE}` WHERE `date` = %s "
        f"ORDER BY `fund_type`, `rank_in_type`", (pd,)) or []

    groups = {}
    for r in rows:
        (ftype, rank, code, name, quality, tier, tscore,
         rate_1y, mdd, lag, nav_as_of) = r
        bucket = groups.setdefault(ftype, [])
        if len(bucket) >= _TOP_N_PER_BUCKET:
            continue
        bucket.append({
            'code': code,
            'name': name,
            'quality_score': _num(quality),
            'timing_tier': tier,
            'timing_score': _num(tscore),
            'rate_1y': _num(rate_1y),
            'max_drawdown': _num(mdd),
            'data_lag_days': int(lag) if lag is not None else None,
            'nav_as_of': _to_date(nav_as_of),
            'seven_day_annual': None,
        })

    # 货币型桶：补 7 日年化（cn_fund_rank），对齐原型「收益稳定性」展示
    money_codes = [p['code'] for p in groups.get(_MONEY_TYPE, []) if p.get('code')]
    if money_codes:
        sda_map = _fetch_seven_day_annual(money_codes)
        for p in groups.get(_MONEY_TYPE, []):
            p['seven_day_annual'] = sda_map.get(p.get('code'))

    ordered = [t for t in _TYPE_ORDER if t in groups]
    ordered += sorted(t for t in groups if t not in _TYPE_ORDER)
    buckets = []
    for ftype in ordered:
        buckets.append({
            'fund_type': ftype,
            'timing_applicable': ftype != _MONEY_TYPE,
            'picks': groups[ftype],
        })
    return pd, buckets


def _fmt_pick_line(pick, timing_applicable, base):
    """单只基金一行 markdown：[代码 简称](深链) 质量XX · 徽章/收益。"""
    code = pick.get('code') or ''
    name = pick.get('name') or code
    url = _fund_detail_url(code, name, base)
    parts = [f"[{code} {_safe_link_text(name)}]({url})"]
    q = pick.get('quality_score')
    if q is not None:
        parts.append(f"质量{q:.0f}")
    if timing_applicable:
        tier = pick.get('timing_tier')
        if tier:
            emoji = _TIER_EMOJI.get(tier, '')
            tscore = pick.get('timing_score')
            badge = f"{emoji}{tier}{tscore:.0f}" if tscore is not None else f"{emoji}{tier}"
            parts.append(badge)
        else:
            # 净值数据不足/滞后无法定档：显式标注「暂无」，对齐原型
            parts.append("择时暂无")
        lag = pick.get('data_lag_days')
        if lag is not None and lag >= _LAG_WARN_DAYS:
            parts.append(f"净值滞后{lag}天")
    else:
        # 货币型/不做点位择时：优先显示 7 日年化，回退近1年，避免择时措辞
        sda = pick.get('seven_day_annual')
        if sda is not None:
            parts.append(f"七日年化{sda:.2f}%")
        else:
            r = pick.get('rate_1y')
            if r is not None:
                parts.append(f"近1年{r:.2f}%")
    return "- " + " · ".join(parts)


def build_fund_pick_markdown(pick_date, buckets, base=None):
    """构建紧凑摘要 markdown（每桶 Top3 + 详情深链）。返回 (title, markdown)。

    纯函数（不触 DB / 不发送），便于单测。货币型不显示择时徽章（§7.3）。
    """
    base = base or _base_url()
    date_str = pick_date.isoformat() if hasattr(pick_date, 'isoformat') else str(pick_date)
    title = f"📈 每日基金精选榜 {date_str}"

    lines = [f"## {title}", ""]
    for b in buckets:
        ftype = b.get('fund_type') or '其他'
        picks = b.get('picks') or []
        if not picks:
            continue
        lines.append(f"**{ftype}** · Top{len(picks)}")
        for p in picks:
            lines.append(_fmt_pick_line(p, b.get('timing_applicable', True), base))
        lines.append("")
    lines.append(f"[📋 查看完整每类 Top10 榜单]({_pick_list_url(base)})")
    lines.append("")
    lines.append("---")
    lines.append(f"> {labels.RISK_DISCLAIMER}")
    markdown = "\n".join(lines)
    return title, markdown


def run(pick_date=None, send_now=True, dry_run=False, job_date=None):
    """推送最新（或指定）运行日榜单。返回 result dict。

    dry_run=True 只构建 markdown 并打印，不落事件/不发送（本地验证用）。
    """
    from quantia.notification.channels.dingtalk import DingTalkChannel
    from quantia.notification import service as notify_service

    job_date = job_date or datetime.date.today()
    start = record_task_start(_JOB_NAME, 'push', job_date)
    try:
        pd, buckets = read_latest_picks(pick_date)
        if pd is None or not buckets:
            record_task_end(_JOB_NAME, 'push', job_date, start, success=True,
                            message='无可推送榜单（cn_fund_daily_pick 为空？）',
                            rows_affected=0)
            logger.warning("notify_fund_pick_job: 无可推送榜单")
            return {'sent': False, 'reason': 'no_data'}

        title, markdown = build_fund_pick_markdown(pd, buckets)
        payload = DingTalkChannel.build_markdown_payload(title, markdown)

        if dry_run:
            record_task_end(_JOB_NAME, 'push', job_date, start, success=True,
                            message=f'dry-run（{len(buckets)} 桶，未发送）', rows_affected=0)
            print(markdown)
            return {'sent': False, 'reason': 'dry_run', 'title': title,
                    'markdown': markdown}

        notify_service.ensure_notification_tables()
        config = notify_service._load_config(0, _EVENT_TYPE, _CHANNEL)
        enabled = bool(config.get('enabled') and config.get('webhook'))

        event = {
            'dedupe_key': _dedupe_key(pd),
            'paper_id': 0,
            'event_type': _EVENT_TYPE,
            'channel': _CHANNEL,
            'trade_date': str(pd),
            'code': None,
            'direction': None,
            'status': 'pending' if enabled else 'skipped',
            'payload': payload,
            'error_message': '' if enabled else 'DingTalk notification disabled or webhook missing',
        }
        event_id = notify_service._insert_event(event)
        if event_id is None:
            # dedupe_key 已存在：重复调度/并发被幂等挡下
            record_task_end(_JOB_NAME, 'push', job_date, start, success=True,
                            message=f'幂等跳过（{pd} 已推送）', rows_affected=0)
            logger.info("notify_fund_pick_job: 幂等跳过 date=%s", pd)
            return {'sent': False, 'reason': 'duplicate', 'dedupe_key': event['dedupe_key']}

        if not enabled:
            record_task_end(_JOB_NAME, 'push', job_date, start, success=True,
                            message='通知未启用/webhook 缺，已记 skipped',
                            rows_affected=0)
            logger.info("notify_fund_pick_job: 通知未启用，跳过发送 date=%s", pd)
            return {'sent': False, 'reason': 'disabled', 'event_id': event_id}

        if not send_now:
            record_task_end(_JOB_NAME, 'push', job_date, start, success=True,
                            message='仅入队未发送（send_now=False）', rows_affected=1)
            return {'sent': False, 'reason': 'queued', 'event_id': event_id}

        sent = notify_service._send_payload_for_event(event_id, 0, _EVENT_TYPE, payload)
        record_task_end(_JOB_NAME, 'push', job_date, start, success=True,
                        message=('已推送' if sent else '发送失败，待重试'),
                        rows_affected=1 if sent else 0)
        logger.info("notify_fund_pick_job: date=%s sent=%s", pd, sent)
        return {'sent': sent, 'event_id': event_id, 'reason': 'sent' if sent else 'failed'}
    except Exception as e:
        record_task_end(_JOB_NAME, 'push', job_date, start, success=False,
                        message=str(e), rows_affected=0)
        logger.error("notify_fund_pick_job 失败", exc_info=True)
        raise


def main():
    pick_date = None
    dry_run = False
    for arg in sys.argv[1:]:
        if arg.startswith('--date='):
            pick_date = arg.split('=', 1)[1].strip()
        elif arg == '--dry-run':
            dry_run = True
    run(pick_date=pick_date, dry_run=dry_run)


if __name__ == '__main__':
    main()
