#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import logging
import pymysql
import os.path
import sys
import time

cpath_current = os.path.dirname(os.path.dirname(__file__))
cpath = os.path.abspath(os.path.join(cpath_current, os.pardir))
sys.path.append(cpath)
import quantia.lib.database as mdb
import quantia.lib.envconfig as _cfg

__author__ = 'Quantia'
__date__ = '2026/02/14'

# 远程连接重试配置
_MAX_RETRIES = _cfg.get_int('QUANTIA_DB_MAX_RETRIES', 3)
_RETRY_DELAY = _cfg.get_int('QUANTIA_DB_RETRY_DELAY', 5)  # 秒


# 创建新数据库。
def create_new_database():
    _MYSQL_CONN_DBAPI = mdb.MYSQL_CONN_DBAPI.copy()
    _MYSQL_CONN_DBAPI['database'] = "mysql"
    with pymysql.connect(**_MYSQL_CONN_DBAPI) as conn:
        with conn.cursor() as db:
            try:
                create_sql = f"CREATE DATABASE IF NOT EXISTS `{mdb.db_database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci"
                db.execute(create_sql)
                create_new_base_table()
            except Exception as e:
                logging.error(f"init_job.create_new_database处理异常", exc_info=True)


# 创建基础表。
def create_new_base_table():
    with pymysql.connect(**mdb.MYSQL_CONN_DBAPI) as conn:
        with conn.cursor() as db:
            create_table_sql = """CREATE TABLE IF NOT EXISTS `cn_stock_attention` (
                                  `datetime` datetime(0) NULL DEFAULT NULL,
                                  `code` varchar(6) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL,
                                  PRIMARY KEY (`code`) USING BTREE,
                                  INDEX `INIX_DATETIME`(`datetime`) USING BTREE
                                  ) CHARACTER SET = utf8mb4 COLLATE = utf8mb4_general_ci ROW_FORMAT = Dynamic;"""
            db.execute(create_table_sql)

            # 交易日历表（由 fetch_stocks_trade_date 在首次获取时自动填充）
            create_trade_date_sql = """CREATE TABLE IF NOT EXISTS `cn_stock_trade_date` (
                                  `trade_date` date NOT NULL,
                                  PRIMARY KEY (`trade_date`)
                                  ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;"""
            db.execute(create_trade_date_sql)

            # 个股历史财务数据表（回测用，由 stock_financial_data.py 填充）
            create_financial_sql = """CREATE TABLE IF NOT EXISTS `cn_stock_financial` (
                                  `code`                   VARCHAR(6)    NOT NULL COMMENT '股票代码',
                                  `report_date`            DATE          NOT NULL COMMENT '报告期',
                                  `report_name`            VARCHAR(20)   COMMENT '报告期名称',
                                  `eps`                    FLOAT         COMMENT '基本每股收益(元)',
                                  `bps`                    FLOAT         COMMENT '每股净资产(元)',
                                  `ocfps`                  FLOAT         COMMENT '每股经营现金流(元)',
                                  `revenue`                FLOAT         COMMENT '营业总收入(元)',
                                  `net_profit`             FLOAT         COMMENT '归母净利润(元)',
                                  `revenue_yoy`            FLOAT         COMMENT '营收同比增长(%)',
                                  `net_profit_yoy`         FLOAT         COMMENT '净利润同比增长(%)',
                                  `roe`                    FLOAT         COMMENT 'ROE净资产收益率(%)',
                                  `roa`                    FLOAT         COMMENT '总资产净利率(%)',
                                  `gross_margin`           FLOAT         COMMENT '毛利率(%)',
                                  `net_profit_margin`      FLOAT         COMMENT '净利率(%)',
                                  `asset_liability_ratio`  FLOAT         COMMENT '资产负债率(%)',
                                  `current_ratio`          FLOAT         COMMENT '流动比率',
                                  `quick_ratio`            FLOAT         COMMENT '速动比率',
                                  `total_asset_turnover`   FLOAT         COMMENT '总资产周转率(次)',
                                  `inventory_turnover`     FLOAT         COMMENT '存货周转率(次)',
                                  `receivable_turnover`    FLOAT         COMMENT '应收账款周转率(次)',
                                  `updated_at`             DATETIME      DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                                  PRIMARY KEY (`code`, `report_date`),
                                  INDEX `idx_report_date` (`report_date`),
                                  INDEX `idx_code` (`code`)
                                  ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
                                    COMMENT='个股财务分析指标-东方财富(回测用)';"""
            db.execute(create_financial_sql)


def check_database():
    with pymysql.connect(**mdb.MYSQL_CONN_DBAPI) as conn:
        with conn.cursor() as db:
            db.execute(" select 1 ")


def _connect_with_retry(conn_params, label="数据库连接"):
    """带重试的数据库连接，应对远程服务器间歇性超时。"""
    last_err = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            conn = pymysql.connect(**conn_params)
            if attempt > 1:
                logging.info(f"{label}: 第{attempt}次重试成功")
            return conn
        except (pymysql.err.OperationalError, pymysql.err.InterfaceError) as e:
            last_err = e
            err_code = e.args[0] if e.args else 0
            # 2003=Can't connect, 2013=Lost connection (timeout)
            if err_code in (2003, 2013) and attempt < _MAX_RETRIES:
                logging.warning(
                    f"{label}: 连接超时（第{attempt}/{_MAX_RETRIES}次），"
                    f"{_RETRY_DELAY}秒后重试... [{e}]"
                )
                time.sleep(_RETRY_DELAY)
            else:
                raise
    raise last_err


def main():
    # 检查，如果执行 select 1 失败，说明数据库不存在，然后创建一个新的数据库。
    try:
        conn = _connect_with_retry(mdb.MYSQL_CONN_DBAPI, "检查数据库")
        with conn:
            with conn.cursor() as db:
                db.execute(" select 1 ")
    except pymysql.err.OperationalError as e:
        err_code = e.args[0] if e.args else 0
        if err_code in (1049,):  # 1049 = Unknown database
            logging.warning("执行信息：数据库不存在，将创建。")
            _MYSQL_CONN_DBAPI = mdb.MYSQL_CONN_DBAPI.copy()
            _MYSQL_CONN_DBAPI['database'] = "mysql"
            conn = _connect_with_retry(_MYSQL_CONN_DBAPI, "创建数据库")
            with conn:
                with conn.cursor() as db:
                    try:
                        create_sql = f"CREATE DATABASE IF NOT EXISTS `{mdb.db_database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci"
                        db.execute(create_sql)
                    except Exception as e2:
                        logging.error(f"init_job.create_new_database处理异常", exc_info=True)
        else:
            raise  # 非数据库不存在错误，向上抛出

    # 无论数据库是新建还是已存在，确保基础表存在（CREATE TABLE IF NOT EXISTS 幂等）
    try:
        create_new_base_table()
    except Exception as e:
        logging.error(f"init_job.create_new_base_table处理异常", exc_info=True)


# main函数入口
if __name__ == '__main__':
    main()
