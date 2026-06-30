#!/usr/bin/env python
# -*- coding:utf-8 -*-
"""轻量级系统级 KV 配置（cn_system_config）。

用于需要跨进程（Web 服务 ↔ 定时任务/job）共享、且可由前端运行时切换的开关型配置，
例如「基金重仓股全覆盖（方案C）」开关。区别于 .env 环境变量（改后需重启、前端无法控制）。

表 cn_system_config： config_key(主键) / config_value / update_time。
读写均走 quantia.lib.database，属普通 MySQL 访问（非外部 API），analysis/web/job 均可调用。
"""
import datetime
import logging

import quantia.lib.database as mdb

_TABLE = 'cn_system_config'
_table_ready = False

_TRUE_SET = {'1', 'true', 'yes', 'on', 'y', 't'}


def _ensure_table():
    global _table_ready
    if _table_ready:
        return
    try:
        mdb.executeSql(
            f"CREATE TABLE IF NOT EXISTS `{_TABLE}` ("
            f"  `config_key` VARCHAR(64) NOT NULL,"
            f"  `config_value` VARCHAR(255) DEFAULT NULL,"
            f"  `update_time` DATETIME DEFAULT NULL,"
            f"  PRIMARY KEY (`config_key`)"
            f") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4")
        _table_ready = True
    except Exception:
        logging.warning("sysconfig._ensure_table 失败", exc_info=True)


def get(key, default=None):
    """取字符串配置值；缺表/缺键/异常返回 default。"""
    try:
        _ensure_table()
        rows = mdb.executeSqlFetch(
            f"SELECT `config_value` FROM `{_TABLE}` WHERE `config_key` = %s", (str(key),))
        if rows and rows[0] and rows[0][0] is not None:
            return rows[0][0]
    except Exception:
        logging.warning(f"sysconfig.get({key}) 失败", exc_info=True)
    return default


def get_bool(key, default=False):
    """取布尔开关；存储值 ∈ {1,true,yes,on,...} 视为 True。"""
    val = get(key, None)
    if val is None:
        return bool(default)
    return str(val).strip().lower() in _TRUE_SET


def set(key, value):
    """写入/更新配置（upsert）。布尔统一存 '1'/'0'。返回是否成功。"""
    if isinstance(value, bool):
        value = '1' if value else '0'
    try:
        _ensure_table()
        mdb.executeSql(
            f"INSERT INTO `{_TABLE}` (`config_key`, `config_value`, `update_time`) "
            f"VALUES (%s, %s, %s) "
            f"ON DUPLICATE KEY UPDATE `config_value` = VALUES(`config_value`), "
            f"`update_time` = VALUES(`update_time`)",
            (str(key), None if value is None else str(value), datetime.datetime.now()))
        return True
    except Exception:
        logging.warning(f"sysconfig.set({key}) 失败", exc_info=True)
        return False
