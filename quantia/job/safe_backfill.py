#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
安全补跑脚本：先停 web 服务释放内存，再执行 fetch + analysis

用法（在服务器上运行）：
    python3 /root/Quantia/quantia/job/safe_backfill.py

特点：
- 停止 web_service 进程释放 ~160MB
- 使用 workers=1 最小内存占用
- 补跑完毕后自动重启 web_service
"""

import os
import sys
import subprocess
import signal
import time
import logging
import gc

cpath_current = os.path.dirname(os.path.dirname(__file__))
cpath = os.path.abspath(os.path.join(cpath_current, os.pardir))
sys.path.append(cpath)
os.chdir(os.path.dirname(__file__))

from quantia.lib.log_config import setup_logging
setup_logging('backfill')

# ── Step 0: 停止 web 服务，释放 ~160MB ──
logging.info("=== 安全补跑：停止 web_service 释放内存 ===")
try:
    # 使用 PID 文件精确匹配 web_service 进程，避免 pkill -f 误杀
    _pid_file = os.path.join(cpath, 'quantia', 'web', 'web_service.pid')
    if os.path.isfile(_pid_file):
        with open(_pid_file, 'r') as f:
            _pid = int(f.read().strip())
        try:
            os.kill(_pid, signal.SIGTERM)
            logging.info(f"已向 web_service (PID {_pid}) 发送 SIGTERM")
        except ProcessLookupError:
            logging.info(f"web_service (PID {_pid}) 已不存在")
        except Exception as e:
            logging.warning(f"停止 web_service (PID {_pid}) 异常: {e}")
    else:
        # PID 文件不存在时降级为 pkill，但使用更精确的匹配
        result = subprocess.run(
            ["pkill", "-f", "python.*web_service\\.py$"],
            capture_output=True, timeout=10
        )
        logging.info(f"pkill web_service: 退出码 {result.returncode}")
    time.sleep(3)
except Exception as e:
    logging.warning(f"停止 web_service 异常: {e}")

gc.collect()

# ── Step 1: 获取作业（K线缓存更新）──
logging.info("=== Step 1: 执行 fetch_daily_job（K线缓存更新）===")
try:
    # 设置环境变量控制并发度
    os.environ['QUANTIA_ANALYSIS_WORKERS'] = '1'
    os.environ['QUANTIA_BATCH_SIZE'] = '30'
    os.environ['QUANTIA_BACKTEST_OUTER_WORKERS'] = '1'
    os.environ['QUANTIA_BACKTEST_INNER_WORKERS'] = '1'

    import fetch_daily_job as fdj
    fdj.main()
except Exception as e:
    logging.error("fetch_daily_job 异常", exc_info=True)

gc.collect()

# ── Step 2: 分析作业 ──
logging.info("=== Step 2: 执行 analysis_daily_job（指标+策略+回测）===")
try:
    import analysis_daily_job as adj
    adj.main()
except Exception as e:
    logging.error("analysis_daily_job 异常", exc_info=True)

gc.collect()

# ── Step 3: 重启 web_service ──
logging.info("=== Step 3: 重启 web_service ===")
try:
    web_script = os.path.join(cpath, 'quantia', 'web', 'web_service.py')
    subprocess.Popen(
        [sys.executable, web_script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True
    )
    logging.info("web_service 已重启")
except Exception as e:
    logging.error(f"重启 web_service 异常: {e}")

logging.info("=== 安全补跑完成 ===")
