#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模拟交易每日任务

执行所有状态为 running 的模拟盘的每日交易。
可由 cron 定时触发，每个交易日收盘后执行。
"""

import logging
import os
import sys

# 在项目运行时，临时将项目路径添加到环境变量
cpath_current = os.path.dirname(os.path.dirname(__file__))
cpath = os.path.abspath(os.path.join(cpath_current, os.pardir))
if cpath not in sys.path:
    sys.path.append(cpath)

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s')


def main():
    try:
        from quantia.paper_trading.paper_engine import run_all_paper_trading
        results = run_all_paper_trading()
        if results:
            ok = sum(1 for r in results if r.get('status') == 'ok')
            log.info(f"模拟交易完成: {ok}/{len(results)} 个模拟盘执行成功")
        else:
            log.info("无运行中的模拟盘")
    except Exception:
        log.error("模拟交易执行异常", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
