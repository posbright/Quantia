#!/usr/bin/env python3
# -*- coding: utf-8 -*-


from threading import RLock


__author__ = 'Quantia'
__date__ = '2026/02/14'


class singleton_type(type):
    single_lock = RLock()

    def __call__(cls, *args, **kwargs):  # 创建cls的对象时候调用
        with singleton_type.single_lock:
            if not hasattr(cls, "_instance"):
                cls._instance = super(singleton_type, cls).__call__(*args, **kwargs)  # 创建cls的对象
            return cls._instance
