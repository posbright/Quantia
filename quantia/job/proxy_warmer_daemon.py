#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
代理池预热常驻守护（方案 B）

背景：
    hourly / workdayly 等 cron 采集作业是"每次新起、约 1 分钟即退出"的短命进程。
    代理池 singleton_proxy 的抓取 / 验证 / HTTPS 升级 / 落盘全部在 daemon 后台线程，
    短进程退出即被杀，磁盘缓存 cache/proxy_cache.json 往往还没养起来就没了 —— 于是
    每个小时的采集进程启动时都读到空缓存 → get_proxies() 返回 None → 全程直连 → 东财对
    生产 IP 限流 → RemoteDisconnected → 切换下一个数据源。免费代理永远养不起来。

本守护进程的职责：
    以一个"活得够久"的常驻进程持有代理池单例，让其后台线程持续抓取 / 验证 / 刷新，
    并周期性补充 HTTPS 隧道验证 + 落盘。cron 短进程通过读磁盘缓存复用这些代理。
    磁盘缓存是跨进程共享可用代理的唯一载体。

部署：由 supervisor 常驻（见 supervisor/supervisord.conf 的 [program:proxy_warmer]）。

环境变量：
    QUANTIA_PROXY_WARMER_INTERVAL  主循环间隔秒数（默认 180）
    其余代理池参数（QUANTIA_PROXY_*）沿用 singleton_proxy 的配置。
"""

import os
import sys
import time
import signal
import logging

cpath_current = os.path.dirname(os.path.dirname(__file__))
cpath = os.path.abspath(os.path.join(cpath_current, os.pardir))
sys.path.append(cpath)

import quantia.lib.envconfig as _cfg
from quantia.core.singleton_proxy import proxys

__author__ = 'Quantia'
__date__ = '2026/07/02'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
)

# 主循环间隔（秒）。HTTPS 升级与落盘按此节奏进行；代理池自身的定时刷新走
# PROXY_REFRESH_INTERVAL（默认 600s），二者互补。
WARMER_INTERVAL = _cfg.get_int('QUANTIA_PROXY_WARMER_INTERVAL', 180)

_running = True


def _handle_signal(signum, _frame):
    global _running
    _running = False
    logging.info(f"代理池预热守护：收到信号 {signum}，准备优雅退出...")


def main():
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    logging.info(f"代理池预热守护：启动（主循环间隔 {WARMER_INTERVAL}s）")
    # 触发单例初始化：内部后台线程开始验证缓存、抓取新代理、启动定时刷新
    pool = proxys()

    while _running:
        # 分段睡眠，保证信号能及时中断
        slept = 0
        while _running and slept < WARMER_INTERVAL:
            time.sleep(min(5, WARMER_INTERVAL - slept))
            slept += 5

        if not _running:
            break

        try:
            # HTTPS 升级降频：距上次满 WARMER_HTTPS_INTERVAL 秒才补一次，为 https:// 接口
            # （东财股票实时行情 HTTPS 端点）养 https_ok 代理；避免每轮对 http-only 代理空验
            # （代理池 600s 刷新已覆盖 HTTPS 结果，二者重叠）。无待升级代理时该调用会立即返回。
            now = time.monotonic()
            if now - last_https_upgrade >= WARMER_HTTPS_INTERVAL:
                pool.ensure_https_upgraded()
                last_https_upgrade = now
            # 落盘：cron 短进程通过磁盘缓存复用这些代理（每轮都做，开销小）
            pool.persist()
            logging.info(f"代理池预热守护：存活，当前可用代理 {pool.pool_size()} 个")
        except Exception as e:
            logging.warning(f"代理池预热守护：本轮维护异常: {e}")

    # 退出前再落盘一次，尽量把本进程养到的代理留给后续短进程
    try:
        pool.stop()
        pool.persist()
    except Exception:
        logging.debug("代理池预热守护：退出落盘异常", exc_info=True)
    logging.info("代理池预热守护：已退出")


if __name__ == '__main__':
    main()
