#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
作业状态追踪器

提供作业执行状态的记录与查询功能，用于：
1. 记录每个作业/子任务的执行状态、开始/结束时间、耗时
2. 检查某日作业是否已成功完成（避免备份 cron 重复执行）
3. 检查数据新鲜度（某表的当日数据是否已存在且完整）
4. 为 kline_cache_daily_job 提供 run_fetch 成功状态检查

存储方式：数据库表 cn_job_status
"""

import logging
import time
import datetime
import os
import sys

cpath_current = os.path.dirname(os.path.dirname(__file__))
cpath = os.path.abspath(os.path.join(cpath_current, os.pardir))
sys.path.append(cpath)
import quantia.lib.database as mdb

__author__ = 'Quantia'
__date__ = '2026/03/12'

# 作业状态表名
JOB_STATUS_TABLE = 'cn_job_status'


def _ensure_table():
    """确保 cn_job_status 表存在"""
    if mdb.checkTableIsExist(JOB_STATUS_TABLE):
        return
    try:
        create_sql = f"""
        CREATE TABLE IF NOT EXISTS `{JOB_STATUS_TABLE}` (
            `id` INT AUTO_INCREMENT PRIMARY KEY,
            `job_name` VARCHAR(100) NOT NULL COMMENT '作业名称',
            `task_name` VARCHAR(200) DEFAULT NULL COMMENT '子任务名称',
            `job_date` DATE NOT NULL COMMENT '作业日期',
            `status` VARCHAR(20) NOT NULL DEFAULT 'running' COMMENT '状态: running/success/failed/skipped',
            `start_time` DATETIME NOT NULL COMMENT '开始时间',
            `end_time` DATETIME DEFAULT NULL COMMENT '结束时间',
            `elapsed_seconds` FLOAT DEFAULT NULL COMMENT '耗时(秒)',
            `message` TEXT DEFAULT NULL COMMENT '备注信息',
            `rows_affected` INT DEFAULT NULL COMMENT '影响行数',
            UNIQUE KEY `uk_job_task_date` (`job_name`, `task_name`, `job_date`),
            INDEX `idx_job_date` (`job_name`, `job_date`),
            INDEX `idx_status` (`status`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
        COMMENT='作业执行状态追踪表'
        """
        mdb.executeSql(create_sql)
        logging.info(f"已创建作业状态表 {JOB_STATUS_TABLE}")
    except Exception as e:
        logging.warning(f"创建作业状态表异常: {e}")


def record_task_start(job_name, task_name, job_date):
    """
    记录子任务开始执行。

    Args:
        job_name: 主作业名 (如 'run_fetch', 'run_analysis')
        task_name: 子任务名 (如 'stock_spot', 'selection_data')
        job_date: 作业日期 (date 或 str)

    Returns:
        float: 开始时间戳，用于后续 record_task_end
    """
    _ensure_table()
    start_time = time.time()
    now = datetime.datetime.now()
    date_str = job_date.strftime("%Y-%m-%d") if hasattr(job_date, 'strftime') else str(job_date)

    try:
        # UPSERT: 如果已有记录则更新为 running
        sql = f"""
        INSERT INTO `{JOB_STATUS_TABLE}` (`job_name`, `task_name`, `job_date`, `status`, `start_time`)
        VALUES (%s, %s, %s, 'running', %s)
        ON DUPLICATE KEY UPDATE `status`='running', `start_time`=%s, `end_time`=NULL,
            `elapsed_seconds`=NULL, `message`=NULL, `rows_affected`=NULL
        """
        mdb.executeSql(sql, (job_name, task_name, date_str, now, now))
        logging.info(f"[{job_name}/{task_name}] 开始执行")
    except Exception as e:
        logging.warning(f"记录任务开始状态异常: {e}")

    return start_time


def record_task_end(job_name, task_name, job_date, start_time, success=True,
                    message=None, rows_affected=None):
    """
    记录子任务执行结束。

    Args:
        job_name: 主作业名
        task_name: 子任务名
        job_date: 作业日期
        start_time: record_task_start 返回的时间戳
        success: 是否成功
        message: 备注信息
        rows_affected: 影响行数
    """
    elapsed = time.time() - start_time
    now = datetime.datetime.now()
    status = 'success' if success else 'failed'
    date_str = job_date.strftime("%Y-%m-%d") if hasattr(job_date, 'strftime') else str(job_date)

    try:
        sql = f"""
        UPDATE `{JOB_STATUS_TABLE}`
        SET `status`=%s, `end_time`=%s, `elapsed_seconds`=%s, `message`=%s, `rows_affected`=%s
        WHERE `job_name`=%s AND `task_name`=%s AND `job_date`=%s
        """
        mdb.executeSql(sql, (status, now, round(elapsed, 2), message, rows_affected,
                             job_name, task_name, date_str))
        level = logging.INFO if success else logging.WARNING
        logging.log(level, f"[{job_name}/{task_name}] {'成功' if success else '失败'}，耗时 {elapsed:.1f}s"
                    + (f"，{message}" if message else ""))
    except Exception as e:
        logging.warning(f"记录任务结束状态异常: {e}")


def record_task_skipped(job_name, task_name, job_date, message=None):
    """记录子任务被跳过（数据已存在等原因）"""
    _ensure_table()
    now = datetime.datetime.now()
    date_str = job_date.strftime("%Y-%m-%d") if hasattr(job_date, 'strftime') else str(job_date)

    try:
        sql = f"""
        INSERT INTO `{JOB_STATUS_TABLE}` (`job_name`, `task_name`, `job_date`, `status`, `start_time`, `end_time`, `message`)
        VALUES (%s, %s, %s, 'skipped', %s, %s, %s)
        ON DUPLICATE KEY UPDATE `status`='skipped', `end_time`=%s, `message`=%s
        """
        mdb.executeSql(sql, (job_name, task_name, date_str, now, now, message, now, message))
        logging.info(f"[{job_name}/{task_name}] 跳过" + (f"：{message}" if message else ""))
    except Exception as e:
        logging.warning(f"记录任务跳过状态异常: {e}")


def is_job_completed(job_name, job_date):
    """
    检查指定作业当日是否已全部成功完成。

    检查逻辑：job_name 下存在 task_name='__overall__' 且 status='success' 的记录。

    Args:
        job_name: 作业名 (如 'run_fetch')
        job_date: 作业日期

    Returns:
        bool: True 表示已成功完成
    """
    _ensure_table()
    date_str = job_date.strftime("%Y-%m-%d") if hasattr(job_date, 'strftime') else str(job_date)

    try:
        row = mdb.executeSqlFetch(
            f"SELECT `status` FROM `{JOB_STATUS_TABLE}` "
            f"WHERE `job_name`=%s AND `task_name`='__overall__' AND `job_date`=%s",
            (job_name, date_str)
        )
        if row and row[0][0] == 'success':
            return True
    except Exception as e:
        logging.warning(f"查询作业完成状态异常: {e}")
    return False


def is_data_fresh(table_name, date_str, min_rows=1):
    """
    检查指定表的当日数据是否已存在且足够完整。

    Args:
        table_name: 数据库表名
        date_str: 日期字符串 'YYYY-MM-DD'
        min_rows: 最少行数阈值（低于此值认为数据不完整）

    Returns:
        (bool, int): (是否新鲜, 实际行数)
    """
    try:
        if not mdb.checkTableIsExist(table_name):
            return False, 0

        row = mdb.executeSqlFetch(
            f"SELECT COUNT(*) FROM `{table_name}` WHERE `date` = %s",
            (date_str,)
        )
        count = row[0][0] if row else 0
        is_fresh = count >= min_rows
        return is_fresh, count
    except Exception as e:
        logging.warning(f"检查数据新鲜度异常 ({table_name}): {e}")
        return False, 0


def get_task_status(job_name, task_name, job_date):
    """
    获取指定任务的执行状态。

    Returns:
        dict | None: {'status': str, 'start_time': datetime, 'end_time': datetime, ...}
    """
    _ensure_table()
    date_str = job_date.strftime("%Y-%m-%d") if hasattr(job_date, 'strftime') else str(job_date)

    try:
        row = mdb.executeSqlFetch(
            f"SELECT `status`, `start_time`, `end_time`, `elapsed_seconds`, `message`, `rows_affected` "
            f"FROM `{JOB_STATUS_TABLE}` "
            f"WHERE `job_name`=%s AND `task_name`=%s AND `job_date`=%s",
            (job_name, task_name, date_str)
        )
        if row:
            return {
                'status': row[0][0],
                'start_time': row[0][1],
                'end_time': row[0][2],
                'elapsed_seconds': row[0][3],
                'message': row[0][4],
                'rows_affected': row[0][5],
            }
    except Exception as e:
        logging.warning(f"查询任务状态异常: {e}")
    return None
