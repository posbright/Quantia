#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
钉钉通知诊断脚本 — 在生产服务器上执行：

    cd /root/Quantia
    /root/Quantia/.venv/bin/python tools/diagnose_dingtalk.py

会做以下事情，**不发送钉钉测试消息**：
1. 打印 .env 是否被加载、webhook/secret 是否就绪
2. 列出 cn_stock_notification_config 全部配置（如有）
3. 列出最近 3 天的通知事件（含状态/错误/重试次数）
4. 列出最近 2 天的模拟交易记录，对比是否每笔都有事件
5. 检查可能的环境问题（系统时间偏移、网络出站）

若加 --send-test 参数则尝试发送一条测试消息。
"""
import argparse
import datetime
import json
import os
import socket
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import quantia.lib.envconfig  # noqa: F401  触发 .env 加载
import quantia.lib.database as mdb


def _print_section(title: str):
    print('\n' + '=' * 6 + ' ' + title + ' ' + '=' * 6, flush=True)


def check_env():
    _print_section('1. .env 加载状态')
    from quantia.lib.envconfig import _dotenv_loaded, _env_path
    print(f'.env 路径   : {_env_path}')
    print(f'.env 已加载 : {_dotenv_loaded}')
    wh = os.getenv('QUANTIA_DINGTALK_WEBHOOK', '')
    sec = os.getenv('QUANTIA_DINGTALK_SECRET', '')
    print(f'WEBHOOK 是否设置 : {bool(wh)}  (前 60 字: {wh[:60]})')
    print(f'SECRET  是否设置 : {bool(sec)}  (长度 {len(sec)})')
    if not wh:
        print('!! 关键问题: QUANTIA_DINGTALK_WEBHOOK 未设置 — 通知会被静默 skipped')
    return wh, sec


def check_clock():
    _print_section('2. 系统时间检查（钉钉签名要求时差 < 1 小时）')
    try:
        # Use a known UTC time API would be too noisy; use NTP-like check via socket
        # Just print current and ask user to compare with phone
        now = datetime.datetime.now()
        utc = datetime.datetime.utcnow()
        print(f'本地时间: {now}')
        print(f'UTC时间:  {utc}')
        print('请人工核对：与你的手机时间是否相差 > 1 分钟？若超过 1 小时，签名会被钉钉拒绝。')
    except Exception as e:
        print(f'时间检查异常: {e}')


def check_config_table():
    _print_section('3. cn_stock_notification_config 表内容')
    try:
        rows = mdb.executeSqlFetch(
            'SELECT id, paper_id, channel, event_type, enabled, webhook_env, secret_env, '
            'created_at, updated_at FROM cn_stock_notification_config ORDER BY id DESC LIMIT 50'
        ) or []
        if not rows:
            print('(表为空 — 走 .env fallback；只要 .env 配置正确就 OK)')
        for r in rows:
            print(r)
            if r[4] == 0:
                print('  !! 该行 enabled=0，会导致此 paper_id/event_type 的通知被 skipped')
    except Exception as e:
        print(f'查询异常（表可能不存在）: {e}')


def check_events():
    _print_section('4. cn_stock_notification_event 最近 3 天事件')
    try:
        rows = mdb.executeSqlFetch(
            "SELECT id, paper_id, event_type, channel, trade_date, code, direction, status, "
            "retry_count, error_message, LEFT(response_json, 200), created_at, sent_at, next_retry_at "
            "FROM cn_stock_notification_event WHERE created_at >= NOW() - INTERVAL 3 DAY "
            "ORDER BY id DESC LIMIT 100"
        ) or []
        if not rows:
            print('(最近 3 天没有任何事件入库 — 可能 trade_records 为空，或 enqueue 异常被吞)')
        for r in rows:
            print(r)
        if rows:
            stats = {}
            for r in rows:
                stats[r[7]] = stats.get(r[7], 0) + 1
            print('\n按状态统计:', stats)
            failed = [r for r in rows if r[7] in ('failed', 'skipped')]
            for r in failed[:10]:
                print(f'  -> id={r[0]} status={r[7]} err={r[9]!r}')
    except Exception as e:
        print(f'查询异常: {e}')


def check_recent_trades():
    _print_section('5. 最近 2 天模拟交易执行日志（核对是否每笔成交都有对应通知事件）')
    try:
        rows = mdb.executeSqlFetch(
            "SELECT id, paper_id, trade_date, status, message, trade_count, total_value, "
            "started_at, finished_at FROM cn_stock_paper_execution_log "
            "WHERE trade_date >= CURDATE() - INTERVAL 2 DAY ORDER BY id DESC LIMIT 50"
        ) or []
        if not rows:
            print('(最近 2 天 cn_stock_paper_execution_log 无记录 — 调度未触发或未执行)')
        for r in rows:
            print(r)
            if r[5] and r[5] > 0:
                print(f'  -> paper_id={r[1]} trade_date={r[2]} 产生 {r[5]} 笔成交，应有对应通知事件')
    except Exception as e:
        print(f'查询异常: {e}')


def check_running_papers():
    _print_section('6. 运行中的模拟盘')
    try:
        rows = mdb.executeSqlFetch(
            "SELECT id, name, status, strategy_id, last_run_date, last_run_at "
            "FROM cn_stock_paper_trading WHERE status='running' ORDER BY id"
        ) or []
        for r in rows:
            print(r)
    except Exception as e:
        print(f'查询异常: {e}')


def check_dingtalk_reachability():
    _print_section('7. 钉钉网关网络可达性 (oapi.dingtalk.com:443)')
    try:
        s = socket.create_connection(('oapi.dingtalk.com', 443), timeout=5)
        s.close()
        print('TCP 连接 oapi.dingtalk.com:443 成功')
    except Exception as e:
        print(f'!! TCP 连接失败: {e}  — 出站网络/防火墙问题')


def send_test():
    _print_section('8. 主动发送测试消息')
    wh = os.getenv('QUANTIA_DINGTALK_WEBHOOK', '')
    sec = os.getenv('QUANTIA_DINGTALK_SECRET', '')
    if not wh:
        print('未配置 webhook，跳过')
        return
    from quantia.notification.channels.dingtalk import DingTalkChannel
    payload = DingTalkChannel.build_markdown_payload(
        title='模拟交易诊断测试',
        markdown='## 模拟交易诊断测试\n\n- 这是一条由 diagnose_dingtalk.py 主动发送的测试消息。\n- 时间：' + str(datetime.datetime.now()),
    )
    result = DingTalkChannel(wh, sec).send(payload)
    print(f'send ok={result.ok}  status={result.status_code}  err={result.error}')
    print(f'response={json.dumps(result.response, ensure_ascii=False)[:500]}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--send-test', action='store_true', help='主动尝试发送一条测试消息')
    args = ap.parse_args()

    check_env()
    check_clock()
    check_config_table()
    check_events()
    check_recent_trades()
    check_running_papers()
    check_dingtalk_reachability()
    if args.send_test:
        send_test()


if __name__ == '__main__':
    main()
