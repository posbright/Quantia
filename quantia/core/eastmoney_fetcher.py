#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import logging
import requests
import threading
from pathlib import Path
import time
import random
from quantia.core.singleton_proxy import proxys
import quantia.lib.envconfig as _cfg

__author__ = 'Quantia'
__date__ = '2026/02/14'

class eastmoney_fetcher:
    """
    东方财富网数据获取器
    封装了Cookie管理、会话管理和请求发送功能
    """

    def __init__(self):
        """初始化获取器"""
        self.base_dir = os.path.dirname(os.path.dirname(__file__))
        self.session = self._create_session()
        # 使用 threading.local 为每个线程提供独立的 Session
        # requests.Session 不是线程安全的，多线程共享同一 Session 对象
        # 会导致连接池损坏、cookie 混乱等问题
        self._thread_local = threading.local()

    def _get_cookie(self):
        """
        获取东方财富网的Cookie
        优先级：环境变量 > 文件 > 默认Cookie
        """
        # 1. 尝试从环境变量获取
        cookie = os.environ.get('EAST_MONEY_COOKIE')
        if cookie:
            # print("环境变量中的Cookie: 已设置")
            return cookie

        # 2. 尝试从文件获取
        cookie_file = Path(os.path.join(self.base_dir, 'config', 'eastmoney_cookie.txt'))
        if cookie_file.exists():
            with open(cookie_file, 'r') as f:
                cookie = f.read().strip()
            if cookie:
                # print("文件中的Cookie: 已设置")
                return cookie

        # 3. 默认Cookie（可能过期，仅作为备选）
        return ''

    def _create_session(self):
        """创建并配置会话"""
        session = requests.Session()
        # 设置请求头（不设置Cookie，避免复杂Cookie导致500错误）
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://quote.eastmoney.com/',
            'Accept': '*/*',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
        }
        session.headers.update(headers)
        return session

    def _get_thread_session(self):
        """获取当前线程的 Session（线程安全）"""
        if not hasattr(self._thread_local, 'session'):
            self._thread_local.session = self._create_session()
        return self._thread_local.session

    def make_request(self, url, params=None,
                     retry=_cfg.get_int('QUANTIA_EM_RETRY', 3),
                     timeout=_cfg.get_int('QUANTIA_EM_TIMEOUT', 30)):
        """
        发送请求（线程安全：每个线程使用独立的 Session）
        :param url: 请求URL
        :param params: 请求参数
        :param retry: 重试次数（每次使用不同代理/直连，最后一次强制直连）
        :param timeout: 超时时间（直连时使用；走代理时自动缩短以避免长时间等待失效代理）
        :return: 响应对象
        """
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://quote.eastmoney.com/',
            'Accept': '*/*',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        }
        
        session = self._get_thread_session()
        proxy_pool = proxys()
        
        for i in range(retry):
            # 最后一次重试强制直连，确保不受坏代理影响
            if i == retry - 1:
                current_proxy = None
            else:
                current_proxy = proxy_pool.get_proxies()
            # 记录当前使用的代理URL（用于后续反馈成功/失败）
            proxy_url = current_proxy.get("http") if current_proxy else None
            # 走代理时使用更短的超时（免费代理不稳定，长等待没有意义）
            effective_timeout = min(timeout, 15) if proxy_url else timeout
            try:
                response = session.get(
                    url,
                    headers=headers,
                    proxies=current_proxy,
                    params=params,
                    timeout=effective_timeout
                )
                response.raise_for_status()  # 检查HTTP错误
                # 请求成功，反馈给代理池
                proxy_pool.report_success(proxy_url)
                return response
            except requests.exceptions.RequestException as e:
                # 请求失败，反馈给代理池（累积失败次数，达阈值后自动移除）
                proxy_pool.report_failure(proxy_url)
                err_str = str(e)
                # 连接级错误（代理断开/过载等）：换代理或直连重试
                is_connection_error = any(kw in err_str for kw in [
                    'RemoteDisconnected', 'Connection aborted', 'ConnectionReset',
                    'Connection refused', 'Max retries exceeded',
                    'SSLError', 'SSLEOFError',
                    '503 Server Error', '504 Server Error', '502 Server Error',
                    'Service Unavailable', 'Gateway Time-out', 'Bad Gateway',
                ])
                if is_connection_error:
                    proxy_label = proxy_url or '直连'
                    if i < retry - 1:
                        logging.debug(f"请求连接错误(代理:{proxy_label}): {e}，将换代理/直连重试")
                        time.sleep(random.uniform(1, 3))
                        continue
                    else:
                        logging.debug(f"请求连接错误(代理:{proxy_label}): {e}，已用尽重试次数")
                        raise
                logging.debug(f"请求错误: {e}, 第 {i + 1}/{retry} 次重试")
                if i < retry - 1:
                    # 随机延迟后重试，逐步增加延迟
                    time.sleep(random.uniform(2, 5) * (i + 1))
                else:
                    raise

    def update_cookie(self, new_cookie):
        """
        更新Cookie
        :param new_cookie: 新的Cookie值
        """
        self.session.cookies.update({'Cookie': new_cookie})
