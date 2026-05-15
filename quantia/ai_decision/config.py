# -*- coding: utf-8 -*-
"""AI 决策配置：DDL + 加载。

策略侧只与 ``AIDecisionConfig`` 交互，密钥仅通过 ``api_key_ref``
（环境变量名）解析，不进数据库、不进日志。
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

CONFIG_TABLE = "cn_stock_ai_decision_config"
SCORE_TABLE = "cn_stock_trade_ai_score"
DEFAULT_API_KEY_ENV = "QUANTIA_AI_API_KEY"


class AIDecisionConfig:
    __slots__ = (
        "id", "name", "enabled", "source_type", "source_id", "strategy_id",
        "provider", "model_name", "base_url", "api_key_ref",
        "system_prompt", "user_prompt_template", "output_schema", "tool_config",
        "temperature", "max_tokens", "timeout_seconds", "retry_count",
        "enabled_as_gate", "fail_closed",
        "buy_threshold", "sell_threshold", "config_version",
    )

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))
        # 应用合理默认
        if self.enabled is None:
            self.enabled = 0
        if self.provider is None:
            self.provider = "openai_compatible"
        if self.temperature is None:
            self.temperature = 0.2
        if self.max_tokens is None:
            self.max_tokens = 2048
        if self.timeout_seconds is None:
            self.timeout_seconds = 20
        if self.retry_count is None:
            self.retry_count = 1
        if self.enabled_as_gate is None:
            self.enabled_as_gate = 0
        if self.fail_closed is None:
            self.fail_closed = 0
        if self.buy_threshold is None:
            self.buy_threshold = 70.0
        if self.sell_threshold is None:
            self.sell_threshold = 40.0
        if self.config_version is None:
            self.config_version = 1

    def is_enabled(self) -> bool:
        return bool(self.enabled)

    def is_gate(self) -> bool:
        return bool(self.enabled and self.enabled_as_gate)

    def resolve_api_key(self) -> Optional[str]:
        """密钥仅从环境变量获取；未配置时返回 None（允许 stub provider 跑通）。"""
        ref = (self.api_key_ref or "").strip() or DEFAULT_API_KEY_ENV
        return os.getenv(ref)

    def to_dict(self) -> Dict[str, Any]:
        d = {k: getattr(self, k, None) for k in self.__slots__}
        # 切勿落配置 dump 时泄漏环境变量值，仅保留引用名。
        return d


def ensure_ai_decision_tables() -> None:
    """幂等创建 Phase 4 两张表（与开发计划 §5.5 / §5.6 一致）。

    异常仅 warning，不抛出，不阻塞业务。
    """
    try:
        import quantia.lib.database as mdb
    except Exception as exc:  # pragma: no cover - import boundary
        logging.warning("[ai_decision] 加载 database 模块失败: %s", exc)
        return
    try:
        if not mdb.checkTableIsExist(CONFIG_TABLE):
            mdb.executeSql(f"""
                CREATE TABLE IF NOT EXISTS `{CONFIG_TABLE}` (
                    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
                    `name` VARCHAR(128) NOT NULL,
                    `enabled` TINYINT(1) DEFAULT 0,
                    `source_type` VARCHAR(32) DEFAULT 'paper',
                    `source_id` BIGINT DEFAULT NULL,
                    `strategy_id` BIGINT DEFAULT NULL,
                    `provider` VARCHAR(64) DEFAULT 'openai_compatible',
                    `model_name` VARCHAR(128) DEFAULT NULL,
                    `base_url` VARCHAR(255) DEFAULT NULL,
                    `api_key_ref` VARCHAR(255) DEFAULT NULL,
                    `system_prompt` MEDIUMTEXT,
                    `user_prompt_template` MEDIUMTEXT,
                    `output_schema` JSON DEFAULT NULL,
                    `tool_config` JSON DEFAULT NULL,
                    `temperature` DECIMAL(6,4) DEFAULT 0.2000,
                    `max_tokens` INT DEFAULT 2048,
                    `timeout_seconds` INT DEFAULT 20,
                    `retry_count` INT DEFAULT 1,
                    `enabled_as_gate` TINYINT(1) DEFAULT 0,
                    `fail_closed` TINYINT(1) DEFAULT 0,
                    `buy_threshold` DECIMAL(8,4) DEFAULT 70.0000,
                    `sell_threshold` DECIMAL(8,4) DEFAULT 40.0000,
                    `config_version` INT DEFAULT 1,
                    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
                    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    KEY `idx_enabled_source` (`enabled`, `source_type`, `source_id`),
                    KEY `idx_strategy` (`strategy_id`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI交易研判配置表'
            """)
        if not mdb.checkTableIsExist(SCORE_TABLE):
            mdb.executeSql(f"""
                CREATE TABLE IF NOT EXISTS `{SCORE_TABLE}` (
                    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
                    `config_id` BIGINT DEFAULT NULL,
                    `config_version` INT DEFAULT NULL,
                    `source_type` VARCHAR(32) NOT NULL,
                    `source_id` BIGINT NOT NULL,
                    `run_id` VARCHAR(64) DEFAULT NULL,
                    `signal_id` BIGINT DEFAULT NULL,
                    `strategy_id` BIGINT DEFAULT NULL,
                    `strategy_name` VARCHAR(128) DEFAULT NULL,
                    `code` VARCHAR(20) NOT NULL,
                    `name` VARCHAR(64) DEFAULT NULL,
                    `decision_date` DATE NOT NULL,
                    `decision_phase` VARCHAR(32) NOT NULL,
                    `input_hash` VARCHAR(64) NOT NULL,
                    `prompt_hash` VARCHAR(64) DEFAULT NULL,
                    `prompt_version` VARCHAR(64) DEFAULT NULL,
                    `model_name` VARCHAR(128) DEFAULT NULL,
                    `input_summary` JSON DEFAULT NULL,
                    `prompt_messages` JSON DEFAULT NULL,
                    `raw_response` MEDIUMTEXT,
                    `score` DECIMAL(8,4) DEFAULT NULL,
                    `action` VARCHAR(32) DEFAULT NULL,
                    `confidence` DECIMAL(8,4) DEFAULT NULL,
                    `reason_summary` TEXT,
                    `evidence` JSON DEFAULT NULL,
                    `risk_flags` JSON DEFAULT NULL,
                    `threshold_result` JSON DEFAULT NULL,
                    `gate_result` VARCHAR(32) DEFAULT 'not_enabled',
                    `status` VARCHAR(32) DEFAULT 'pending',
                    `latency_ms` INT DEFAULT NULL,
                    `error_message` TEXT,
                    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY `uk_input_phase` (`source_type`, `source_id`, `run_id`, `code`, `decision_phase`, `input_hash`),
                    KEY `idx_signal_id` (`signal_id`),
                    KEY `idx_code_date` (`code`, `decision_date`),
                    KEY `idx_score_action` (`score`, `action`),
                    KEY `idx_status` (`status`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI交易研判评分表'
            """)
    except Exception as exc:
        logging.warning("[ai_decision] 创建 AI 决策表失败: %s", exc)


def _row_to_config(row) -> AIDecisionConfig:
    # 与下文 SELECT 列序保持一致
    keys = [
        "id", "name", "enabled", "source_type", "source_id", "strategy_id",
        "provider", "model_name", "base_url", "api_key_ref",
        "system_prompt", "user_prompt_template", "output_schema", "tool_config",
        "temperature", "max_tokens", "timeout_seconds", "retry_count",
        "enabled_as_gate", "fail_closed",
        "buy_threshold", "sell_threshold", "config_version",
    ]
    kw = {k: row[i] for i, k in enumerate(keys)}
    # JSON 字段反序列化
    for jk in ("output_schema", "tool_config"):
        v = kw.get(jk)
        if isinstance(v, (bytes, bytearray)):
            try:
                v = v.decode("utf-8")
            except Exception:
                v = None
        if isinstance(v, str):
            try:
                kw[jk] = json.loads(v)
            except Exception:
                kw[jk] = None
    return AIDecisionConfig(**kw)


def load_config_for_source(
    source_type: str, source_id: Optional[int] = None,
    strategy_id: Optional[int] = None,
) -> Optional[AIDecisionConfig]:
    """选取最具体的启用配置：source_id+strategy_id 精确匹配 > 仅 source_type。

    无任何启用配置时返回 None；上游应据此跳过 AI（视为禁用）。
    异常仅 warning，不抛出。
    """
    try:
        import quantia.lib.database as mdb
    except Exception:
        return None
    try:
        if not mdb.checkTableIsExist(CONFIG_TABLE):
            return None
        cols = (
            "id, name, enabled, source_type, source_id, strategy_id, "
            "provider, model_name, base_url, api_key_ref, "
            "system_prompt, user_prompt_template, output_schema, tool_config, "
            "temperature, max_tokens, timeout_seconds, retry_count, "
            "enabled_as_gate, fail_closed, "
            "buy_threshold, sell_threshold, config_version"
        )
        # 优先级：source_id+strategy_id 精确，再单一 source_type，再 'all'。
        rows = mdb.executeSqlFetch(
            f"SELECT {cols} FROM `{CONFIG_TABLE}` "
            f"WHERE enabled=1 AND ("
            f"  (source_type=%s AND source_id=%s) OR "
            f"  (source_type=%s AND source_id IS NULL) OR "
            f"  (source_type='all')"
            f") "
            f"ORDER BY source_id IS NULL ASC, strategy_id IS NULL ASC, id DESC LIMIT 1",
            (source_type, int(source_id or 0), source_type),
        ) or []
        if not rows:
            return None
        return _row_to_config(rows[0])
    except Exception as exc:
        logging.warning("[ai_decision] 读取配置失败: %s", exc)
        return None
