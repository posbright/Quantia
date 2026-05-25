# -*- coding: utf-8 -*-
"""Phase 2 — 交易信号 / 决策明细 / 指标快照 / 候选筛选快照 持久化。

本模块只负责落库，绝不调用通知或交易主流程。设计要点：

- DDL 与 ``_ensure_*_table`` 在首次写入时按需创建，遵循项目其它表 (``cn_stock_paper_trading`` 等) 的迁移风格。
- 整体写入用单独事务；任意步骤异常都不会传播到调用方（策略主事务），仅记录 warning。
- ``persist_signal_with_relations`` 是聚合入口：写 signal -> decision -> indicator_snapshot -> selection_snapshot。
- ``link_signal_to_trade`` 在 ``cn_stock_backtest_trade`` 行入库后回填 ``trade_id``。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional

from .trade_decision import serialize_for_db

SIGNAL_TABLE = "cn_stock_trade_signal"
DECISION_TABLE = "cn_stock_trade_decision"
INDICATOR_SNAPSHOT_TABLE = "cn_stock_trade_indicator_snapshot"
SELECTION_SNAPSHOT_TABLE = "cn_stock_trade_selection_snapshot"

_TABLES_ENSURED = False


def _get_db():
    import quantia.lib.database as mdb  # 延迟导入，避免测试 import 时连库
    return mdb


def ensure_trade_signal_tables():
    """幂等创建 4 张 Phase 2 表。若 mdb 不可用直接返回（测试场景）。"""
    global _TABLES_ENSURED
    if _TABLES_ENSURED:
        return
    try:
        mdb = _get_db()
    except Exception as exc:
        logging.debug("[trade_signal_store] database 模块加载失败，跳过表创建: %s", exc)
        return

    ddls = [
        # 与 dev_plan §5.1 一致；AI 相关列在 Phase 4 写入，本期保持 NULL。
        f"""
        CREATE TABLE IF NOT EXISTS `{SIGNAL_TABLE}` (
            `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
            `source_type` VARCHAR(32) NOT NULL COMMENT 'backtest/paper/live',
            `source_id` BIGINT NOT NULL COMMENT '回测ID、模拟盘ID或实盘策略ID',
            `run_id` VARCHAR(64) DEFAULT NULL COMMENT '单次运行ID',
            `strategy_id` BIGINT DEFAULT NULL,
            `strategy_name` VARCHAR(128) DEFAULT NULL,
            `trade_id` BIGINT DEFAULT NULL COMMENT '成交记录ID，撮合后回填',
            `signal_date` DATE NOT NULL,
            `code` VARCHAR(20) NOT NULL,
            `name` VARCHAR(64) DEFAULT NULL,
            `direction` VARCHAR(16) NOT NULL COMMENT 'buy/sell',
            `order_api` VARCHAR(64) DEFAULT NULL,
            `requested_amount` DECIMAL(20,4) DEFAULT NULL COMMENT '策略请求数量变化',
            `requested_value` DECIMAL(20,4) DEFAULT NULL COMMENT '策略请求金额变化',
            `target_amount` DECIMAL(20,4) DEFAULT NULL COMMENT '目标持仓数量',
            `target_percent` DECIMAL(12,6) DEFAULT NULL COMMENT '目标仓位比例',
            `reason` TEXT DEFAULT NULL,
            `reason_source` VARCHAR(32) DEFAULT 'strategy' COMMENT 'strategy/generated/manual/imported',
            `ai_score_id` BIGINT DEFAULT NULL COMMENT 'Phase4关联 cn_stock_trade_ai_score.id',
            `ai_score` DECIMAL(8,4) DEFAULT NULL,
            `ai_action` VARCHAR(32) DEFAULT NULL,
            `ai_gate_result` VARCHAR(32) DEFAULT NULL COMMENT 'not_enabled/pass/reject/fallback/error',
            `signal_hash` VARCHAR(64) NOT NULL,
            `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
            `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY `uk_signal_hash` (`signal_hash`),
            KEY `idx_source_run` (`source_type`, `source_id`, `run_id`),
            KEY `idx_trade_id` (`trade_id`),
            KEY `idx_ai_score_id` (`ai_score_id`),
            KEY `idx_code_date` (`code`, `signal_date`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='策略交易信号表'
        """,
        f"""
        CREATE TABLE IF NOT EXISTS `{DECISION_TABLE}` (
            `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
            `signal_id` BIGINT NOT NULL,
            `rule_group` VARCHAR(64) DEFAULT NULL,
            `rule_name` VARCHAR(128) NOT NULL,
            `indicator_key` VARCHAR(64) DEFAULT NULL,
            `threshold_expr` VARCHAR(255) DEFAULT NULL,
            `threshold_value` JSON DEFAULT NULL,
            `actual_value` JSON DEFAULT NULL,
            `passed` TINYINT(1) DEFAULT NULL,
            `weight` DECIMAL(10,4) DEFAULT NULL,
            `score` DECIMAL(10,4) DEFAULT NULL,
            `note` TEXT DEFAULT NULL,
            `sort_order` INT DEFAULT 0,
            `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
            KEY `idx_signal_id` (`signal_id`),
            KEY `idx_rule_group` (`signal_id`, `rule_group`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        # 与 dev_plan §5.3 一致：结构化 OHLCV + 各指标 JSON。
        f"""
        CREATE TABLE IF NOT EXISTS `{INDICATOR_SNAPSHOT_TABLE}` (
            `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
            `signal_id` BIGINT NOT NULL,
            `period` VARCHAR(16) DEFAULT 'daily' COMMENT 'daily/weekly/monthly',
            `kline_date` DATE DEFAULT NULL COMMENT '指标对应K线日期',
            `open` DECIMAL(20,6) DEFAULT NULL,
            `high` DECIMAL(20,6) DEFAULT NULL,
            `low` DECIMAL(20,6) DEFAULT NULL,
            `close` DECIMAL(20,6) DEFAULT NULL,
            `volume` DECIMAL(24,4) DEFAULT NULL,
            `amount` DECIMAL(24,4) DEFAULT NULL,
            `ma` JSON DEFAULT NULL,
            `boll` JSON DEFAULT NULL,
            `rsi` JSON DEFAULT NULL,
            `macd` JSON DEFAULT NULL,
            `kdj` JSON DEFAULT NULL,
            `extra` JSON DEFAULT NULL COMMENT '策略自定义指标',
            `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY `uk_signal_period` (`signal_id`, `period`),
            KEY `idx_signal_date` (`signal_id`, `kline_date`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='交易时点指标快照表'
        """,
        f"""
        CREATE TABLE IF NOT EXISTS `{SELECTION_SNAPSHOT_TABLE}` (
            `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
            `signal_id` BIGINT NOT NULL,
            `stage` VARCHAR(64) NOT NULL,
            `candidate_count_before` INT DEFAULT NULL,
            `candidate_count_after` INT DEFAULT NULL,
            `rank_value` DECIMAL(20,6) DEFAULT NULL,
            `rank_position` INT DEFAULT NULL,
            `filter_expr` VARCHAR(255) DEFAULT NULL,
            `actual_value` JSON DEFAULT NULL,
            `passed` TINYINT(1) DEFAULT NULL,
            `note` TEXT DEFAULT NULL,
            `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
            KEY `idx_signal_stage` (`signal_id`, `stage`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
    ]
    for ddl in ddls:
        try:
            mdb.executeSql(ddl)
        except Exception as exc:
            logging.warning("[trade_signal_store] 建表失败(将在下次写入时重试): %s", exc)
            return

    # 兼容性迁移：早期提交可能创建了简化版 schema（cn_stock_trade_signal 缺
    # target_amount/target_percent/ai_*；cn_stock_trade_indicator_snapshot 是
    # 单列 payload JSON）。CREATE TABLE IF NOT EXISTS 不会更新已存在的表，
    # 因此这里通过 INFORMATION_SCHEMA 检查并按需 ALTER / DROP 重建。
    try:
        _migrate_phase2_schema_if_needed(mdb)
    except Exception as exc:
        logging.warning("[trade_signal_store] Phase2 schema 迁移检查失败(忽略，下次重试): %s", exc)
        return

    _TABLES_ENSURED = True


def _column_exists(mdb, table: str, column: str) -> bool:
    rows = mdb.executeSqlFetch(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema=DATABASE() AND table_name=%s AND column_name=%s LIMIT 1",
        (table, column),
    ) or []
    return bool(rows)


def _migrate_phase2_schema_if_needed(mdb) -> None:
    # 1) cn_stock_trade_signal：补齐 target_amount/target_percent/ai_* 列
    if not _column_exists(mdb, SIGNAL_TABLE, "target_amount"):
        logging.info("[trade_signal_store] 迁移 %s 增加 target_amount/target_percent/ai_* 列", SIGNAL_TABLE)
        mdb.executeSql(
            f"ALTER TABLE `{SIGNAL_TABLE}` "
            "ADD COLUMN `target_amount` DECIMAL(20,4) DEFAULT NULL AFTER `requested_value`, "
            "ADD COLUMN `target_percent` DECIMAL(12,6) DEFAULT NULL AFTER `target_amount`, "
            "ADD COLUMN `ai_score_id` BIGINT DEFAULT NULL AFTER `reason_source`, "
            "ADD COLUMN `ai_score` DECIMAL(8,4) DEFAULT NULL AFTER `ai_score_id`, "
            "ADD COLUMN `ai_action` VARCHAR(32) DEFAULT NULL AFTER `ai_score`, "
            "ADD COLUMN `ai_gate_result` VARCHAR(32) DEFAULT NULL AFTER `ai_action`, "
            "ADD KEY `idx_ai_score_id` (`ai_score_id`)"
        )

    # 2) cn_stock_trade_indicator_snapshot：旧版是单列 payload JSON，需重建。
    #    Phase2 trace 表本身可重建，无外键依赖；若已有数据则 DROP 后重建。
    if _column_exists(mdb, INDICATOR_SNAPSHOT_TABLE, "payload") \
            and not _column_exists(mdb, INDICATOR_SNAPSHOT_TABLE, "close"):
        logging.warning(
            "[trade_signal_store] 检测到 %s 旧 schema(单列 payload)，DROP+重建为结构化列",
            INDICATOR_SNAPSHOT_TABLE,
        )
        mdb.executeSql(f"DROP TABLE `{INDICATOR_SNAPSHOT_TABLE}`")
        mdb.executeSql(
            f"CREATE TABLE `{INDICATOR_SNAPSHOT_TABLE}` ("
            " `id` BIGINT AUTO_INCREMENT PRIMARY KEY,"
            " `signal_id` BIGINT NOT NULL,"
            " `period` VARCHAR(16) DEFAULT 'daily',"
            " `kline_date` DATE DEFAULT NULL,"
            " `open` DECIMAL(20,6) DEFAULT NULL,"
            " `high` DECIMAL(20,6) DEFAULT NULL,"
            " `low` DECIMAL(20,6) DEFAULT NULL,"
            " `close` DECIMAL(20,6) DEFAULT NULL,"
            " `volume` DECIMAL(24,4) DEFAULT NULL,"
            " `amount` DECIMAL(24,4) DEFAULT NULL,"
            " `ma` JSON DEFAULT NULL,"
            " `boll` JSON DEFAULT NULL,"
            " `rsi` JSON DEFAULT NULL,"
            " `macd` JSON DEFAULT NULL,"
            " `kdj` JSON DEFAULT NULL,"
            " `extra` JSON DEFAULT NULL,"
            " `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,"
            " UNIQUE KEY `uk_signal_period` (`signal_id`, `period`),"
            " KEY `idx_signal_date` (`signal_id`, `kline_date`)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
        )


def persist_signal_with_relations(
    *,
    source_type: str,
    source_id: int,
    run_id: Optional[str],
    strategy_id: Optional[int],
    strategy_name: Optional[str],
    signal_date,
    code: str,
    name: Optional[str],
    direction: str,
    order_api: Optional[str],
    requested_amount: Optional[float],
    requested_value: Optional[float],
    reason: str,
    reason_source: str,
    signal_hash: str,
    target_amount: Optional[float] = None,
    target_percent: Optional[float] = None,
    decision_rules: Optional[List[Dict[str, Any]]] = None,
    indicators: Optional[Dict[str, Any]] = None,
    selection: Optional[List[Dict[str, Any]]] = None,
    ai_score_id: Optional[int] = None,
    ai_score: Optional[float] = None,
    ai_action: Optional[str] = None,
    ai_gate_result: Optional[str] = None,
) -> Optional[int]:
    """聚合写入。返回 signal_id 或 None（失败时静默，不抛出）。"""
    try:
        ensure_trade_signal_tables()
        mdb = _get_db()
    except Exception as exc:
        logging.debug("[trade_signal_store] 跳过持久化(无法获取 DB): %s", exc)
        return None

    try:
        with mdb.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"INSERT INTO `{SIGNAL_TABLE}` "
                    "(source_type, source_id, run_id, strategy_id, strategy_name, "
                    " signal_date, code, name, direction, order_api, "
                    " requested_amount, requested_value, target_amount, target_percent, "
                    " reason, reason_source, signal_hash, "
                    " ai_score_id, ai_score, ai_action, ai_gate_result) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON DUPLICATE KEY UPDATE reason=VALUES(reason), reason_source=VALUES(reason_source), "
                    " requested_amount=VALUES(requested_amount), requested_value=VALUES(requested_value), "
                    " target_amount=VALUES(target_amount), target_percent=VALUES(target_percent), "
                    " strategy_name=VALUES(strategy_name), "
                    " ai_score_id=COALESCE(VALUES(ai_score_id), ai_score_id), "
                    " ai_score=COALESCE(VALUES(ai_score), ai_score), "
                    " ai_action=COALESCE(VALUES(ai_action), ai_action), "
                    " ai_gate_result=COALESCE(VALUES(ai_gate_result), ai_gate_result)",
                    (
                        source_type, int(source_id or 0), run_id, strategy_id, strategy_name,
                        signal_date, code, name, direction, order_api,
                        requested_amount, requested_value, target_amount, target_percent,
                        reason, reason_source, signal_hash,
                        ai_score_id, ai_score, ai_action, ai_gate_result,
                    ),
                )
                cur.execute(
                    f"SELECT id FROM `{SIGNAL_TABLE}` WHERE signal_hash=%s LIMIT 1",
                    (signal_hash,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                signal_id = int(row[0])

                # decision rules
                if decision_rules:
                    cur.execute(f"DELETE FROM `{DECISION_TABLE}` WHERE signal_id=%s", (signal_id,))
                    for rule in decision_rules:
                        cur.execute(
                            f"INSERT INTO `{DECISION_TABLE}` "
                            "(signal_id, rule_group, rule_name, indicator_key, threshold_expr, "
                            " threshold_value, actual_value, passed, weight, score, note, sort_order) "
                            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                            (
                                signal_id, rule.get("rule_group"), rule.get("rule_name"),
                                rule.get("indicator_key"), rule.get("threshold_expr"),
                                serialize_for_db(rule.get("threshold_value")),
                                serialize_for_db(rule.get("actual_value")),
                                rule.get("passed"), rule.get("weight"), rule.get("score"),
                                rule.get("note"), int(rule.get("sort_order") or 0),
                            ),
                        )

                # indicator snapshot：拆分 OHLCV / ma / boll / rsi / macd / kdj / extra
                if indicators:
                    ind = indicators if isinstance(indicators, dict) else {}
                    ohlcv_keys = {"open", "high", "low", "close", "volume", "amount"}
                    json_keys = {"ma", "boll", "rsi", "macd", "kdj"}
                    extra = {k: v for k, v in ind.items()
                            if k not in ohlcv_keys and k not in json_keys and k != "kline_date"}
                    cur.execute(
                        f"INSERT INTO `{INDICATOR_SNAPSHOT_TABLE}` "
                        "(signal_id, period, kline_date, `open`, high, low, `close`, volume, amount, "
                        " ma, boll, rsi, macd, kdj, extra) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                        "ON DUPLICATE KEY UPDATE kline_date=VALUES(kline_date), "
                        " `open`=VALUES(`open`), high=VALUES(high), low=VALUES(low), `close`=VALUES(`close`), "
                        " volume=VALUES(volume), amount=VALUES(amount), "
                        " ma=VALUES(ma), boll=VALUES(boll), rsi=VALUES(rsi), macd=VALUES(macd), "
                        " kdj=VALUES(kdj), extra=VALUES(extra)",
                        (
                            signal_id, "daily", ind.get("kline_date") or signal_date,
                            ind.get("open"), ind.get("high"), ind.get("low"), ind.get("close"),
                            ind.get("volume"), ind.get("amount"),
                            serialize_for_db(ind.get("ma")),
                            serialize_for_db(ind.get("boll")),
                            serialize_for_db(ind.get("rsi")),
                            serialize_for_db(ind.get("macd")),
                            serialize_for_db(ind.get("kdj")),
                            serialize_for_db(extra) if extra else None,
                        ),
                    )

                # selection snapshot
                if selection:
                    cur.execute(f"DELETE FROM `{SELECTION_SNAPSHOT_TABLE}` WHERE signal_id=%s", (signal_id,))
                    for stage in selection:
                        cur.execute(
                            f"INSERT INTO `{SELECTION_SNAPSHOT_TABLE}` "
                            "(signal_id, stage, candidate_count_before, candidate_count_after, "
                            " rank_value, rank_position, filter_expr, actual_value, passed, note) "
                            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                            (
                                signal_id, stage.get("stage"),
                                stage.get("candidate_count_before"), stage.get("candidate_count_after"),
                                stage.get("rank_value"), stage.get("rank_position"),
                                stage.get("filter_expr"),
                                serialize_for_db(stage.get("actual_value")),
                                stage.get("passed"), stage.get("note"),
                            ),
                        )
                conn.commit()
                return signal_id
    except Exception as exc:
        logging.warning("[trade_signal_store] persist_signal_with_relations 失败 code=%s dir=%s: %s",
                        code, direction, exc)
        return None


def link_signal_to_trade(signal_id: int, trade_id: int) -> bool:
    """成交行入库后回填 trade_id；失败仅 warning。"""
    if not signal_id or not trade_id:
        return False
    try:
        mdb = _get_db()
        mdb.executeSql(
            f"UPDATE `{SIGNAL_TABLE}` SET trade_id=%s WHERE id=%s",
            (int(trade_id), int(signal_id)),
        )
        return True
    except Exception as exc:
        logging.warning("[trade_signal_store] 回填 trade_id 失败 signal_id=%s trade_id=%s: %s",
                        signal_id, trade_id, exc)
        return False


def _query_indicators_fallback(mdb, code: str, signal_date) -> Optional[Dict[str, Any]]:
    """当 cn_stock_trade_indicator_snapshot 没有该 signal 的数据时，
    从 cn_stock_indicators + cn_stock_spot 合成"信号发生当日（或最近交易日）"的
    OHLCV + 主要指标快照，使前端"指标快照"面板始终能展示真实数据。
    任何异常 → 返回 None，不影响主流程。
    """
    if not code or signal_date is None:
        return None
    try:
        # 指标行：取 signal_date 当日，否则最近 14 个交易日内最新一条。
        ind_rows = mdb.executeSqlFetch(
            "SELECT date, close, rsi, macd, macds, macdh, boll, boll_ub, boll_lb, "
            " kdjk, kdjd, kdjj, atr, cci, mfi, obv, vr "
            "FROM cn_stock_indicators "
            "WHERE code=%s AND date<=%s ORDER BY date DESC LIMIT 1",
            (str(code), signal_date),
        ) or []
        spot_rows = mdb.executeSqlFetch(
            "SELECT date, open_price, high_price, low_price, new_price, volume, deal_amount "
            "FROM cn_stock_spot "
            "WHERE code=%s AND date<=%s ORDER BY date DESC LIMIT 1",
            (str(code), signal_date),
        ) or []
        if not ind_rows and not spot_rows:
            return None
        kline_date = (ind_rows[0][0] if ind_rows else None) or (spot_rows[0][0] if spot_rows else None)
        result: Dict[str, Any] = {
            "period": "daily",
            "kline_date": kline_date,
            "open": None, "high": None, "low": None, "close": None,
            "volume": None, "amount": None,
            "ma": None, "boll": None, "rsi": None, "macd": None, "kdj": None,
            "extra": {"source": "synthesized_from_indicators_table"},
        }
        if spot_rows:
            sp = spot_rows[0]
            result["open"] = sp[1]
            result["high"] = sp[2]
            result["low"] = sp[3]
            result["close"] = sp[4]
            result["volume"] = sp[5]
            result["amount"] = sp[6]
        if ind_rows:
            ir = ind_rows[0]
            if result["close"] is None:
                result["close"] = ir[1]
            result["rsi"] = {"rsi14": ir[2]} if ir[2] is not None else None
            if ir[3] is not None or ir[4] is not None or ir[5] is not None:
                result["macd"] = {"dif": ir[3], "dea": ir[4], "hist": ir[5]}
            if ir[6] is not None or ir[7] is not None or ir[8] is not None:
                result["boll"] = {"mid": ir[6], "upper": ir[7], "lower": ir[8]}
            if ir[9] is not None or ir[10] is not None or ir[11] is not None:
                result["kdj"] = {"k": ir[9], "d": ir[10], "j": ir[11]}
            extra = result["extra"]
            for k, idx in (("atr", 12), ("cci", 13), ("mfi", 14), ("obv", 15), ("vr", 16)):
                if ir[idx] is not None:
                    extra[k] = ir[idx]
        return result
    except Exception as exc:
        logging.debug("[trade_signal_store] _query_indicators_fallback 失败 code=%s date=%s: %s",
                      code, signal_date, exc)
        return None


def _synthesize_fallback_rules(reason: str, reason_source: str, direction: str,
                                indicators: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """当 cn_stock_trade_decision 为空时（多数内置策略不显式写决策规则），
    根据 reason 文本 + 真实指标快照合成"事实型"规则行，让用户看到决策时的真实数据。
    与 algo/backtest-detail.vue::decisionRowsForTrade 思路保持一致：
    - 第 1 行：策略决策（说明 reason 的来源）。
    - 后续行：仅在 reason 文本提到对应指标时追加（不硬塞通用阈值）。
    """
    import re
    rows: List[Dict[str, Any]] = []
    text = str(reason or "")
    is_buy = (direction or "").lower() == "buy"

    if reason_source == "strategy":
        source_label = "策略显式说明（reason=）"
    elif reason_source == "derived":
        source_label = "从策略当日 log.info 派生"
    elif reason_source == "generated":
        source_label = "系统兜底文案"
    else:
        source_label = f"reason_source={reason_source or '--'}"
    rows.append({
        "rule_group": "summary",
        "rule_name": "策略决策",
        "threshold_expr": "本笔买入/建仓的策略说明" if is_buy else "本笔卖出/调仓/风控的策略说明",
        "threshold_value": None,
        "actual_value": text or "--",
        "passed": None,
        "note": source_label,
        "sort_order": 0,
    })

    if not indicators:
        return rows

    def _add(name: str, threshold: str, actual: str, note: str):
        rows.append({
            "rule_group": "indicator_snapshot",
            "rule_name": name,
            "threshold_expr": threshold,
            "threshold_value": None,
            "actual_value": actual,
            "passed": None,
            "note": note,
            "sort_order": len(rows),
        })

    def _fmt(v):
        if v is None: return "--"
        try:
            f = float(v)
            return f"{f:.4f}" if abs(f) < 100 else f"{f:.2f}"
        except Exception:
            return str(v)

    has_ma = bool(re.search(r"MA\d|均线|金叉|死叉|上穿|下穿", text, re.I))
    has_boll = bool(re.search(r"BOLL|布林|上轨|下轨|中轨", text, re.I))
    has_rsi = bool(re.search(r"RSI", text, re.I))
    has_macd = bool(re.search(r"MACD|DIF|DEA|柱", text, re.I))
    has_vol = bool(re.search(r"成交量|量能|放量|缩量|换手", text, re.I))
    has_risk = bool(re.search(r"止损|止盈|风控|超时|最大持有|max[_ ]?hold|海龟|突破|入场", text, re.I))

    close = indicators.get("close")
    if has_ma and indicators.get("ma"):
        ma = indicators["ma"]
        if isinstance(ma, dict):
            parts = [f"{k.upper()} {_fmt(v)}" for k, v in ma.items() if v is not None]
            _add("均线快照", "策略提及均线 / 金叉死叉，列出当前实际值",
                 " / ".join(parts) if parts else "--", "事实数据，仅供核对")
    if has_boll and indicators.get("boll"):
        b = indicators["boll"]
        if isinstance(b, dict):
            _add("BOLL 快照", "策略提及布林通道，列出当前实际值",
                 f"收盘 {_fmt(close)} / 下轨 {_fmt(b.get('lower'))} / 中轨 {_fmt(b.get('mid'))} / 上轨 {_fmt(b.get('upper'))}",
                 "事实数据，仅供核对")
    if has_rsi and indicators.get("rsi"):
        r = indicators["rsi"]
        if isinstance(r, dict):
            parts = [f"{k.upper()} {_fmt(v)}" for k, v in r.items() if v is not None]
            _add("RSI 快照", "策略提及 RSI，列出当前实际值",
                 " / ".join(parts) if parts else "--", "事实数据，仅供核对")
    if has_macd and indicators.get("macd"):
        m = indicators["macd"]
        if isinstance(m, dict):
            _add("MACD 快照", "策略提及 MACD，列出当前实际值",
                 f"DIF {_fmt(m.get('dif'))} / DEA {_fmt(m.get('dea'))} / 柱 {_fmt(m.get('hist'))}",
                 "事实数据，仅供核对")
    if has_vol and indicators.get("volume") is not None:
        _add("量能快照", "策略提及量能，列出当前实际值",
             f"成交量 {_fmt(indicators.get('volume'))} / 成交额 {_fmt(indicators.get('amount'))}",
             "事实数据，仅供核对")
    if has_risk:
        _add("风控触发", "策略提及止盈 / 止损 / 风控 / 突破 / 海龟入场",
             text, "由策略自身的入场/风控规则触发，详见左列说明")

    if len(rows) == 1:
        # reason 未点名具体指标 → 仍把 K 线/收盘价兜底列一行
        _add("当日 K 线", "未识别到具体指标关键词，列出当日 OHLCV 供核对",
             f"开 {_fmt(indicators.get('open'))} / 高 {_fmt(indicators.get('high'))} / "
             f"低 {_fmt(indicators.get('low'))} / 收 {_fmt(close)} / 量 {_fmt(indicators.get('volume'))}",
             "事实数据，仅供核对")
    return rows


def fetch_signal_with_decision(signal_id: int) -> Dict[str, Any]:
    """供通知模板/详情接口读取。失败返回空 dict。

    Phase 3: 同时返回 indicator_snapshot 与 selection_snapshot，使
    回测详情、模拟交易详情与通知共享一致的"决策依据"展示数据。
    """
    if not signal_id:
        return {}
    try:
        mdb = _get_db()
        signal_rows = mdb.executeSqlFetch(
            f"SELECT id, reason, reason_source, code, name, direction, signal_date, "
            f" requested_amount, requested_value, target_amount, target_percent, "
            f" order_api, source_type, source_id, run_id, trade_id, "
            f" ai_score_id, ai_score, ai_action, ai_gate_result "
            f"FROM `{SIGNAL_TABLE}` WHERE id=%s",
            (int(signal_id),),
        ) or []
        if not signal_rows:
            return {}
        s = signal_rows[0]
        rules = mdb.executeSqlFetch(
            f"SELECT rule_group, rule_name, threshold_expr, threshold_value, actual_value, passed, note "
            f"FROM `{DECISION_TABLE}` WHERE signal_id=%s ORDER BY sort_order ASC, id ASC",
            (int(signal_id),),
        ) or []
        ind_rows = mdb.executeSqlFetch(
            f"SELECT period, kline_date, `open`, high, low, `close`, volume, amount, "
            f" ma, boll, rsi, macd, kdj, extra "
            f"FROM `{INDICATOR_SNAPSHOT_TABLE}` WHERE signal_id=%s",
            (int(signal_id),),
        ) or []
        sel_rows = mdb.executeSqlFetch(
            f"SELECT stage, candidate_count_before, candidate_count_after, "
            f" rank_value, rank_position, filter_expr, actual_value, passed, note "
            f"FROM `{SELECTION_SNAPSHOT_TABLE}` WHERE signal_id=%s ORDER BY id ASC",
            (int(signal_id),),
        ) or []
        indicators = None
        if ind_rows:
            i = ind_rows[0]
            indicators = {
                "period": i[0], "kline_date": i[1],
                "open": i[2], "high": i[3], "low": i[4], "close": i[5],
                "volume": i[6], "amount": i[7],
                "ma": i[8], "boll": i[9], "rsi": i[10], "macd": i[11],
                "kdj": i[12], "extra": i[13],
            }
        # 兜底：snapshot 表无数据时，从 cn_stock_indicators + cn_stock_spot 合成。
        if not indicators:
            indicators = _query_indicators_fallback(mdb, s[3], s[6])
        # 决策规则兜底：rules 表为空时，按 reason+indicators 合成事实型规则。
        rules_out: List[Dict[str, Any]] = [
            {
                "rule_group": r[0], "rule_name": r[1], "threshold_expr": r[2],
                "threshold_value": r[3], "actual_value": r[4],
                "passed": r[5], "note": r[6],
            }
            for r in rules
        ]
        if not rules_out:
            rules_out = _synthesize_fallback_rules(s[1] or "", s[2] or "strategy", s[5] or "", indicators)
        # JOIN cn_stock_trade_ai_score 获取 AI Gate 详细理由
        ai_reason = None
        ai_score_id = s[16]
        if ai_score_id:
            try:
                ai_rows = mdb.executeSqlFetch(
                    "SELECT reason_summary, evidence, risk_flags "
                    "FROM `cn_stock_trade_ai_score` WHERE id=%s",
                    (int(ai_score_id),),
                ) or []
                if ai_rows:
                    ai_reason = {
                        "reason_summary": ai_rows[0][0] or "",
                        "evidence": ai_rows[0][1] or "",
                        "risk_flags": ai_rows[0][2] or "",
                    }
            except Exception:
                pass
        return {
            "signal_id": int(s[0]),
            "reason": s[1] or "",
            "reason_source": s[2] or "strategy",
            "code": s[3], "name": s[4], "direction": s[5],
            "signal_date": s[6],
            "requested_amount": s[7], "requested_value": s[8],
            "target_amount": s[9], "target_percent": s[10],
            "order_api": s[11],
            "source_type": s[12], "source_id": s[13], "run_id": s[14], "trade_id": s[15],
            "ai_score_id": s[16], "ai_score": s[17], "ai_action": s[18], "ai_gate_result": s[19],
            "ai_reason": ai_reason,
            "rules": rules_out,
            "indicators": indicators,
            "selection": [
                {
                    "stage": s2[0],
                    "candidate_count_before": s2[1],
                    "candidate_count_after": s2[2],
                    "rank_value": s2[3], "rank_position": s2[4],
                    "filter_expr": s2[5], "actual_value": s2[6],
                    "passed": s2[7], "note": s2[8],
                }
                for s2 in sel_rows
            ],
        }
    except Exception as exc:
        logging.warning("[trade_signal_store] 读取 signal 失败 id=%s: %s", signal_id, exc)
        return {}


def list_signals_for_source(source_type: str, source_id: int,
                             limit: int = 500) -> List[Dict[str, Any]]:
    """Phase 3: 列出某次回测/模拟盘的所有 signal 摘要（不含完整规则）。

    供回测详情、模拟交易详情前端展示信号列表使用。
    """
    if not source_type or not source_id:
        return []
    try:
        mdb = _get_db()
        rows = mdb.executeSqlFetch(
            f"SELECT id, signal_date, code, name, direction, order_api, "
            f" requested_amount, requested_value, target_amount, target_percent, "
            f" reason, reason_source, trade_id, run_id "
            f"FROM `{SIGNAL_TABLE}` "
            f"WHERE source_type=%s AND source_id=%s "
            f"ORDER BY signal_date ASC, id ASC LIMIT %s",
            (source_type, int(source_id), int(limit)),
        ) or []
        return [
            {
                "signal_id": int(r[0]), "signal_date": r[1],
                "code": r[2], "name": r[3], "direction": r[4], "order_api": r[5],
                "requested_amount": r[6], "requested_value": r[7],
                "target_amount": r[8], "target_percent": r[9],
                "reason": r[10] or "", "reason_source": r[11] or "strategy",
                "trade_id": r[12], "run_id": r[13],
            }
            for r in rows
        ]
    except Exception as exc:
        logging.warning("[trade_signal_store] list_signals_for_source 失败: %s", exc)
        return []


def persist_backtest_signals(*, backtest_id: int, run_id: str,
                             trade_records, signal_inputs) -> int:
    """Phase 3: 在回测主结果落库 (cn_stock_backtest_portfolio) 后，
    把 ``engine._trade_records`` 与 ``engine._signal_inputs`` 翻译为
    cn_stock_trade_signal/decision/indicator/selection 行。

    回测的成交存放在 cn_stock_backtest_portfolio.result_json 中（无独立
    cn_stock_backtest_trade 行），故 ``trade_id`` 字段保持 NULL；
    前端通过 (source_type='backtest', source_id=backtest_id, signal_date,
    code, direction) 关联。

    返回成功持久化的 signal 数。失败仅 warning，不抛出。
    """
    from .trade_decision import (
        compute_signal_hash, normalize_decision_payload, resolve_reason,
    )
    if not backtest_id or not trade_records:
        return 0
    n_inputs = len(signal_inputs) if signal_inputs is not None else 0
    success = 0
    for idx, t in enumerate(trade_records):
        try:
            order_info = signal_inputs[idx] if idx < n_inputs else {}
            order_info = order_info or {}
            resolved = resolve_reason(t.direction, order_info.get("reason"))
            norm = normalize_decision_payload(
                order_info.get("decision"),
                indicators=order_info.get("indicators"),
                selection=order_info.get("selection"),
            )
            signal_date = getattr(t, "date", None)
            sig_hash = compute_signal_hash(
                source_type="backtest", source_id=backtest_id, run_id=run_id,
                code=t.code, direction=t.direction, signal_date=signal_date,
                requested_amount=order_info.get("amount"),
                requested_value=order_info.get("value"),
            )
            # Phase 4: AI 评分（默认禁用 → ai_meta = {}；持久化时所有 ai_* 字段为 None）
            _ai_meta = {}
            try:
                from quantia.ai_decision import service as _ai_svc
                from quantia.ai_decision import config as _ai_cfg
                _cfg = _ai_cfg.load_config_for_source("backtest", backtest_id)
                if _cfg is not None and _cfg.is_enabled():
                    _ai_meta = _ai_svc.score_trade(
                        cfg=_cfg, source_type="backtest", source_id=backtest_id, run_id=run_id,
                        code=t.code, name=getattr(t, "name", None),
                        decision_date=signal_date,
                        decision_phase="post_signal",
                        direction=t.direction,
                        indicators=order_info.get("indicators"),
                        selection=order_info.get("selection"),
                    ) or {}
            except Exception as _ai_err:
                logging.warning("[trade_signal_store] AI 评分(回测)调用失败: %s", _ai_err)
                _ai_meta = {}
            sig_id = persist_signal_with_relations(
                source_type="backtest", source_id=backtest_id, run_id=run_id,
                strategy_id=None, strategy_name=None,
                signal_date=signal_date, code=t.code, name=getattr(t, "name", None),
                direction=t.direction, order_api=order_info.get("order_api"),
                requested_amount=order_info.get("amount"),
                requested_value=order_info.get("value"),
                target_amount=order_info.get("target_amount"),
                target_percent=order_info.get("target_percent"),
                reason=resolved["reason"], reason_source=resolved["reason_source"],
                signal_hash=sig_hash,
                decision_rules=norm.get("rules") or None,
                indicators=norm.get("indicators") or None,
                selection=norm.get("selection") or None,
                ai_score_id=_ai_meta.get("ai_score_id") if _ai_meta else None,
                ai_score=_ai_meta.get("ai_score") if _ai_meta else None,
                ai_action=_ai_meta.get("ai_action") if _ai_meta else None,
                ai_gate_result=_ai_meta.get("ai_gate_result") if _ai_meta else None,
            )
            if sig_id:
                success += 1
        except Exception as exc:
            logging.warning("[trade_signal_store] 回测 signal 持久化失败 idx=%s: %s", idx, exc)
    return success
