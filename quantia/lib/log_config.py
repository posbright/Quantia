#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一日志配置模块

使用方法（入口脚本顶部调用一次即可）：
    from quantia.lib.log_config import setup_logging
    setup_logging('fetch')     # → quantia/log/stock_fetch.log + stock_error.log
    setup_logging('analysis')  # → quantia/log/stock_analysis.log + stock_error.log
    setup_logging('web')       # → quantia/log/stock_web.log + stock_error.log

日志文件说明：
    stock_{name}.log   — 该脚本的全量日志（INFO+），按大小轮转（10MB × 5 份）
    stock_error.log    — 所有脚本的错误日志汇总（ERROR+，含完整堆栈）

日志格式：
    2026-02-14 18:30:05 [INFO] fetch_data_job: 数据获取开始
    2026-02-14 18:30:10 [ERROR] stockfetch: 获取失败
    Traceback (most recent call last):
      File "stockfetch.py", line 100, in _fetch_from_sources
        ...
    ConnectionError: Remote end closed connection

注意事项：
    - 入口脚本只需调用 setup_logging()，不要再调用 logging.basicConfig()
    - setup_logging() 会清除已有 handler 再重新配置，保证格式统一
    - 通过 logging.getLogger(__name__) 获取模块级 logger（推荐）
      或直接使用 logging.info() 等根 logger 方法（兼容现有代码）
"""

import logging
import logging.handlers
import os

__author__ = 'Quantia'
__date__ = '2026/02/14'

_LOG_FORMAT = '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
_LOG_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'
import quantia.lib.envconfig as _cfg
_LOG_MAX_BYTES = _cfg.get_int('QUANTIA_LOG_MAX_BYTES', 10 * 1024 * 1024)  # 默认 10 MB
_LOG_BACKUP_COUNT = _cfg.get_int('QUANTIA_LOG_BACKUP_COUNT', 5)

# 标记是否已初始化，防止同一进程内重复配置
_initialized = False


def setup_logging(name='execute', level=logging.INFO):
    """
    配置日志系统（三路输出：全量文件 + 错误文件 + 控制台）

    首次调用时清除已有 handler 并建立统一日志配置；
    重复调用时直接返回（同一进程内只生效一次）。

    Args:
        name: 日志名称，会生成 stock_{name}.log 文件
        level: 日志级别，默认 INFO
    """
    global _initialized
    if _initialized:
        return
    _initialized = True

    log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'log')
    os.makedirs(log_dir, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # 清除已有 handler（避免 basicConfig 遗留导致格式不统一）
    root_logger.handlers.clear()

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATE_FORMAT)

    # 1. 全量日志文件 — stock_{name}.log（INFO+，按大小轮转）
    full_handler = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, f'stock_{name}.log'),
        maxBytes=_LOG_MAX_BYTES,
        backupCount=_LOG_BACKUP_COUNT,
        encoding='utf-8',
    )
    full_handler.setLevel(level)
    full_handler.setFormatter(formatter)
    root_logger.addHandler(full_handler)

    # 2. 错误日志文件 — stock_error.log（ERROR+，所有脚本共享，按大小轮转）
    error_handler = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, 'stock_error.log'),
        maxBytes=_LOG_MAX_BYTES,
        backupCount=_LOG_BACKUP_COUNT,
        encoding='utf-8',
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    root_logger.addHandler(error_handler)

    # 3. 控制台 — WARNING+（避免大量 INFO 刷屏）
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%H:%M:%S',
    ))
    root_logger.addHandler(console_handler)

    # 4. 安装未捕获异常钩子 — 确保 main() 抛出的任何异常都会写入
    #    stock_{name}.log 和 stock_error.log（而非仅到 stderr）
    #    这是防止"进程执行失败但日志无任何错误信息"的关键保障。
    _install_excepthook()


def _install_excepthook():
    """将 sys.excepthook 重定向到 logging，保证未捕获异常留痕。

    覆盖场景：
    - 作业顶层 main() 未加 try/except 时的未捕获异常
    - 导入阶段（setup_logging 后）的异常
    注意：SIGKILL/OOM 杀死进程不会触发此钩子（Python 无法响应），
          这类场景需要依赖 cron 层捕获退出码 + 父进程子进程化保护。
    """
    import sys as _sys
    _orig_hook = _sys.excepthook

    def _log_uncaught(exc_type, exc_value, exc_tb):
        # KeyboardInterrupt 保留默认行为，方便 Ctrl+C 退出
        if issubclass(exc_type, KeyboardInterrupt):
            _orig_hook(exc_type, exc_value, exc_tb)
            return
        logging.critical(
            "未捕获异常导致进程终止",
            exc_info=(exc_type, exc_value, exc_tb),
        )
        # 仍调用原 hook，保留 stderr 输出便于 cron 层可见
        _orig_hook(exc_type, exc_value, exc_tb)

    _sys.excepthook = _log_uncaught
