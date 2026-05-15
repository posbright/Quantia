#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
from abc import ABC
import tornado.web
import quantia.core.singleton_stock_web_module_data as sswmd

__author__ = 'Quantia'
__date__ = '2026/02/14'


# 基础handler，主要负责检查mysql的数据库链接，并支持CORS跨域。
class BaseHandler(tornado.web.RequestHandler, ABC):

    def set_default_headers(self):
        """设置CORS跨域请求头"""
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Headers", "x-requested-with, content-type")
        self.set_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS, DELETE, PUT")
        self.set_header("Access-Control-Max-Age", "3600")

    def options(self):
        """处理预检请求"""
        self.set_status(204)
        self.finish()

    @property
    def db(self):
        try:
            # check every time。
            self.application.db.query("SELECT 1 ")
        except Exception as e:
            logging.warning(f"DB连接检查失败，尝试重连: {e}")
            self.application.db.reconnect()
        return self.application.db


class LeftMenu:
    def __init__(self, url):
        self.leftMenuList = sswmd.stock_web_module_data().get_data_list()
        self.current_url = url


# 获得左菜单。
def GetLeftMenu(url):
    return LeftMenu(url)
