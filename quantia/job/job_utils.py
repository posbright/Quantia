#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Job 层公共工具函数

将 basic_data_after_close_daily_job.py 和 basic_data_other_daily_job.py
共用的 _fetch_with_retry 抽取到此处，避免代码重复。
"""

import logging
import time as _time

__author__ = 'Quantia'
__date__ = '2026/03/19'


def fetch_with_retry(fetch_func, name, retries=1, delay=10):
    """带重试的API获取包装器，降低因网络瞬断或限流导致的数据丢失。

    Args:
        fetch_func: 无参可调用对象，返回数据或 None
        name: 任务描述名（用于日志）
        retries: 重试次数（不含首次）
        delay: 重试间隔（秒）

    Returns:
        成功时返回数据，全部失败时返回 None 或抛出异常
    """
    for attempt in range(1 + retries):
        try:
            data = fetch_func()
            if data is not None and len(data) > 0:
                return data
            if attempt < retries:
                logging.warning(f"{name}: 第{attempt+1}次获取为空，{delay}秒后重试")
                _time.sleep(delay)
        except Exception as e:
            if attempt < retries:
                logging.warning(f"{name}: 第{attempt+1}次获取异常（{e}），{delay}秒后重试")
                _time.sleep(delay)
            else:
                raise
    return None
