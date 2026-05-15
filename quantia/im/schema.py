# -*- coding: utf-8 -*-
"""Phase 6: IM 指令相关表 schema 定义。

- ``cn_stock_trade_command``：指令主表（§5.9）。
- ``cn_stock_im_operator_whitelist``：操作人白名单（§12.7）。
"""
from __future__ import annotations

import logging

TRADE_COMMAND_TABLE = "cn_stock_trade_command"
OPERATOR_WHITELIST_TABLE = "cn_stock_im_operator_whitelist"


def ensure_im_tables() -> None:
    """幂等地创建 IM 相关表。失败仅记录，不抛异常以免阻塞 web 启动。"""
    try:
        import quantia.lib.database as mdb
    except Exception as exc:
        logging.debug("[im.schema] 数据库模块加载失败: %s", exc)
        return
    try:
        if not mdb.checkTableIsExist(TRADE_COMMAND_TABLE):
            mdb.executeSql(f'''
                CREATE TABLE IF NOT EXISTS `{TRADE_COMMAND_TABLE}` (
                    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
                    `source_channel` VARCHAR(32) NOT NULL,
                    `source_message_id` VARCHAR(128) DEFAULT NULL,
                    `operator_id` VARCHAR(128) DEFAULT NULL,
                    `operator_name` VARCHAR(128) DEFAULT NULL,
                    `command_type` VARCHAR(32) NOT NULL,
                    `paper_id` BIGINT DEFAULT NULL,
                    `signal_id` BIGINT DEFAULT NULL,
                    `code` VARCHAR(20) DEFAULT NULL,
                    `direction` VARCHAR(16) DEFAULT NULL,
                    `amount` DECIMAL(20,4) DEFAULT NULL,
                    `value` DECIMAL(20,4) DEFAULT NULL,
                    `price_limit` DECIMAL(20,6) DEFAULT NULL,
                    `status` VARCHAR(32) DEFAULT 'pending',
                    `risk_check_json` LONGTEXT,
                    `request_payload` LONGTEXT,
                    `expire_at` DATETIME DEFAULT NULL,
                    `approved_at` DATETIME DEFAULT NULL,
                    `executed_at` DATETIME DEFAULT NULL,
                    `execution_result` LONGTEXT,
                    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
                    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    UNIQUE KEY `uk_channel_message` (`source_channel`, `source_message_id`),
                    KEY `idx_signal` (`signal_id`),
                    KEY `idx_status` (`status`, `expire_at`),
                    KEY `idx_paper` (`paper_id`, `created_at`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='IM交易指令表'
            ''')
    except Exception as exc:
        logging.warning("[im.schema] 创建 %s 失败: %s", TRADE_COMMAND_TABLE, exc)
    try:
        if not mdb.checkTableIsExist(OPERATOR_WHITELIST_TABLE):
            mdb.executeSql(f'''
                CREATE TABLE IF NOT EXISTS `{OPERATOR_WHITELIST_TABLE}` (
                    `id` INT AUTO_INCREMENT PRIMARY KEY,
                    `channel` VARCHAR(32) NOT NULL,
                    `operator_id` VARCHAR(128) NOT NULL,
                    `operator_name` VARCHAR(128) DEFAULT NULL,
                    `enabled` TINYINT(1) NOT NULL DEFAULT 1,
                    `note` VARCHAR(255) DEFAULT NULL,
                    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
                    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    UNIQUE KEY `uk_channel_op` (`channel`, `operator_id`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='IM操作人白名单'
            ''')
    except Exception as exc:
        logging.warning("[im.schema] 创建 %s 失败: %s", OPERATOR_WHITELIST_TABLE, exc)
