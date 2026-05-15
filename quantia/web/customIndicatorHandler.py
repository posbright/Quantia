"""
自定义综合指标 — DDL + 内置预设 seed + 7 个 REST API handler（PR-1/PR-2）。

PR-1 提供：
- `_ensure_custom_indicator_table()`  幂等建表
- `_seed_builtin_indicators()`         写入/更新三条内置预设
- `bootstrap()`                        启动时一次性调用

PR-2 增加（7 个 REST API handler）：
- ListCustomIndicatorHandler        GET  /quantia/api/custom_indicator/list
- GetCustomIndicatorHandler         GET  /quantia/api/custom_indicator/detail
- SaveCustomIndicatorHandler        POST /quantia/api/custom_indicator/save
- DeleteCustomIndicatorHandler      POST /quantia/api/custom_indicator/delete
- BacktestCustomIndicatorHandler    POST /quantia/api/custom_indicator/backtest
- WatchlistTodayHandler             GET  /quantia/api/custom_indicator/watchlist
- IndicatorSeriesHandler            GET  /quantia/api/custom_indicator/series  (PR-5 K 线叠加)
"""
from __future__ import annotations

import datetime
import json
import logging
import re
import uuid
from abc import ABC
from typing import Any

import numpy as np
import pandas as pd
from tornado import gen

import quantia.web.base as webBase
from quantia.lib import database as mdb
from quantia.core.composite.builtins import BUILTIN_PRESETS
from quantia.core.composite.composite_engine import Composite
from quantia.core.composite.hard_rules_engine import (
    SecurityError, RuleEvalError, parse_hard_rules, eval_hard_rules,
)
from quantia.core.composite.indicators_enrich import enrich
from quantia.core.composite import dynamic_universe as du
from quantia.core.composite.risk_simulator import simulate, summarize_trades

_table_ready = False


def _ensure_custom_indicator_table() -> None:
    """幂等建表 — 详细字段见 phase9 dev plan §2.1。"""
    global _table_ready
    if _table_ready:
        return
    if not mdb.checkTableIsExist("cn_stock_custom_indicator"):
        mdb.executeSql("""
            CREATE TABLE IF NOT EXISTS `cn_stock_custom_indicator` (
              `id` INT AUTO_INCREMENT PRIMARY KEY,
              `indicator_id` VARCHAR(64) NOT NULL UNIQUE COMMENT '业务键（builtin 用稳定字符串）',
              `name` VARCHAR(200) NOT NULL,
              `kind` ENUM('primary_entry','watchlist_alert') NOT NULL DEFAULT 'watchlist_alert',
              `description` TEXT,
              `weights` JSON COMMENT '{字段名: 权重} 评分用',
              `smooth_ema` INT DEFAULT 0,
              `buy_th` DECIMAL(10,4) DEFAULT 0,
              `direction` ENUM('low','high') DEFAULT 'high',
              `extra_filter` TEXT COMMENT '可选 AST 表达式（与 hard_rules 同沙箱）',
              `hard_rules` TEXT COMMENT '硬规则 AST 表达式（替代/补充评分）',
              `risk_profile` JSON COMMENT '止损/止盈/最大持有/基本面卖出阈值',
              `is_builtin` TINYINT(1) DEFAULT 0,
              `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
              `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              INDEX `idx_kind` (`kind`),
              INDEX `idx_builtin` (`is_builtin`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        logging.info("[custom_indicator] 已创建表 cn_stock_custom_indicator")
    _table_ready = True


def _seed_builtin_indicators() -> int:
    """
    写入/更新三条内置预设（用 ON DUPLICATE KEY UPDATE）。
    返回受影响行数。
    """
    _ensure_custom_indicator_table()
    affected = 0
    sql = """
        INSERT INTO cn_stock_custom_indicator
          (indicator_id, name, kind, description, weights, smooth_ema, buy_th,
           direction, extra_filter, hard_rules, risk_profile, is_builtin)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
          name=VALUES(name), kind=VALUES(kind), description=VALUES(description),
          weights=VALUES(weights), smooth_ema=VALUES(smooth_ema), buy_th=VALUES(buy_th),
          direction=VALUES(direction), extra_filter=VALUES(extra_filter),
          hard_rules=VALUES(hard_rules), risk_profile=VALUES(risk_profile),
          is_builtin=VALUES(is_builtin)
    """
    for p in BUILTIN_PRESETS:
        params = (
            p["indicator_id"], p["name"], p["kind"], p.get("description"),
            json.dumps(p.get("weights") or {}, ensure_ascii=False),
            int(p.get("smooth_ema", 0)),
            float(p.get("buy_th", 0)),
            p.get("direction", "high"),
            p.get("extra_filter"),
            p.get("hard_rules"),
            json.dumps(p.get("risk_profile") or {}, ensure_ascii=False),
            int(p.get("is_builtin", 1)),
        )
        try:
            mdb.executeSql(sql, params)
            affected += 1
        except Exception as e:
            logging.error(f"[custom_indicator] seed {p['indicator_id']} 失败: {e}")
    return affected


def bootstrap() -> None:
    _ensure_custom_indicator_table()
    n = _seed_builtin_indicators()
    logging.info(f"[custom_indicator] seeded {n} builtin presets")


# ============================================================================
#                  PR-2: REST API Handlers (7 endpoints)
# ============================================================================

# 业务键校验：仅允许 [a-z0-9_-] 长度 1~64
_INDICATOR_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")


def _row_to_dict(row, columns: list[str]) -> dict:
    """torndb 返回 Storage 或元组都兼容。"""
    if isinstance(row, dict):
        return {k: row.get(k) for k in columns}
    return dict(zip(columns, row))


def _parse_json_field(val: Any, default: Any) -> Any:
    """JSON 字段反序列化（容忍 None / 已是 dict / 损坏字符串）。"""
    if val is None or val == "":
        return default
    if isinstance(val, (dict, list)):
        return val
    try:
        return json.loads(val)
    except Exception:
        return default


def _validate_save_payload(body: dict) -> tuple[bool, str]:
    """范式守门 (F7) — kind 与字段一致性校验。"""
    indicator_id = (body.get("indicator_id") or "").strip()
    if not indicator_id:
        return False, "indicator_id 不能为空"
    if not _INDICATOR_ID_RE.match(indicator_id):
        return False, "indicator_id 仅允许字母/数字/下划线/连字符，长度 1~64"
    if not (body.get("name") or "").strip():
        return False, "name 不能为空"
    kind = body.get("kind", "watchlist_alert")
    if kind not in ("primary_entry", "watchlist_alert"):
        return False, "kind 必须为 primary_entry 或 watchlist_alert"
    weights = body.get("weights") or {}
    hard_rules = (body.get("hard_rules") or "").strip()
    extra_filter = (body.get("extra_filter") or "").strip()
    direction = body.get("direction", "high")
    if direction not in ("low", "high"):
        return False, "direction 必须为 low 或 high"

    # F7-a: primary_entry 必须有 hard_rules 或 weights（任意一个能产生信号）
    if kind == "primary_entry" and not hard_rules and not weights:
        return False, "主信号指标 (primary_entry) 必须填写硬规则或权重表至少其一"
    # F7-b: 评分指标(纯 weights) direction 强制 high（V5 实证）
    if weights and not hard_rules and direction != "high":
        return False, "纯评分指标的 direction 必须为 high（V5 实证唯一有效改动）"
    # F7-c: 沙箱解析校验
    if hard_rules:
        try:
            parse_hard_rules(hard_rules)
        except (SecurityError, RuleEvalError) as e:
            return False, f"硬规则解析失败：{e}"
    if extra_filter:
        try:
            parse_hard_rules(extra_filter)
        except (SecurityError, RuleEvalError) as e:
            return False, f"额外过滤解析失败：{e}"
    # F7-d: weights 非空时需要数字权重
    if weights:
        if not isinstance(weights, dict):
            return False, "weights 必须为对象 {字段名: 权重}"
        for k, v in weights.items():
            if not isinstance(v, (int, float)) or v < 0:
                return False, f"weights[{k}] 必须为非负数字"
    return True, ""


# ----------------------------------------------------------------------------
# 1. List
# ----------------------------------------------------------------------------
class ListCustomIndicatorHandler(webBase.BaseHandler, ABC):
    """GET /quantia/api/custom_indicator/list[?kind=primary_entry|watchlist_alert]"""

    @gen.coroutine
    def get(self):
        try:
            _ensure_custom_indicator_table()
            kind = self.get_argument("kind", default=None)
            sql = ("SELECT id, indicator_id, name, kind, description, "
                   "is_builtin, updated_at FROM cn_stock_custom_indicator")
            params: tuple = ()
            if kind in ("primary_entry", "watchlist_alert"):
                sql += " WHERE kind = %s"
                params = (kind,)
            sql += " ORDER BY is_builtin DESC, updated_at DESC"
            rows = mdb.executeSqlFetch(sql, params) or []
            cols = ["id", "indicator_id", "name", "kind", "description",
                    "is_builtin", "updated_at"]
            data = []
            for r in rows:
                d = _row_to_dict(r, cols)
                if d.get("updated_at"):
                    d["updated_at"] = str(d["updated_at"])
                data.append(d)
            self.write(json.dumps({"code": 0, "data": data}, ensure_ascii=False))
        except Exception as e:
            logging.error("ListCustomIndicator 异常", exc_info=True)
            self.write(json.dumps({"code": -1, "msg": str(e)}, ensure_ascii=False))


# ----------------------------------------------------------------------------
# 2. Detail
# ----------------------------------------------------------------------------
class GetCustomIndicatorHandler(webBase.BaseHandler, ABC):
    """GET /quantia/api/custom_indicator/detail?indicator_id=xxx"""

    @gen.coroutine
    def get(self):
        try:
            _ensure_custom_indicator_table()
            iid = self.get_argument("indicator_id", default="").strip()
            if not iid:
                self.write(json.dumps({"code": -1, "msg": "indicator_id 不能为空"},
                                      ensure_ascii=False))
                return
            cols = ["id", "indicator_id", "name", "kind", "description",
                    "weights", "smooth_ema", "buy_th", "direction",
                    "extra_filter", "hard_rules", "risk_profile",
                    "is_builtin", "created_at", "updated_at"]
            sql = (f"SELECT {', '.join(cols)} FROM cn_stock_custom_indicator "
                   "WHERE indicator_id = %s LIMIT 1")
            rows = mdb.executeSqlFetch(sql, (iid,)) or []
            if not rows:
                self.write(json.dumps({"code": -1, "msg": "指标不存在"},
                                      ensure_ascii=False))
                return
            d = _row_to_dict(rows[0], cols)
            d["weights"] = _parse_json_field(d.get("weights"), {})
            d["risk_profile"] = _parse_json_field(d.get("risk_profile"), {})
            for k in ("created_at", "updated_at"):
                if d.get(k):
                    d[k] = str(d[k])
            if d.get("buy_th") is not None:
                try:
                    d["buy_th"] = float(d["buy_th"])
                except Exception:
                    pass
            self.write(json.dumps({"code": 0, "data": d}, ensure_ascii=False))
        except Exception as e:
            logging.error("GetCustomIndicator 异常", exc_info=True)
            self.write(json.dumps({"code": -1, "msg": str(e)}, ensure_ascii=False))


# ----------------------------------------------------------------------------
# 3. Save
# ----------------------------------------------------------------------------
class SaveCustomIndicatorHandler(webBase.BaseHandler, ABC):
    """POST /quantia/api/custom_indicator/save —— upsert by indicator_id；内置预设禁修改。"""

    @gen.coroutine
    def post(self):
        try:
            _ensure_custom_indicator_table()
            body = json.loads(self.request.body or b"{}")
            ok, err = _validate_save_payload(body)
            if not ok:
                self.write(json.dumps({"code": -1, "msg": err}, ensure_ascii=False))
                return
            iid = body["indicator_id"].strip()
            # 不允许修改内置预设
            row = mdb.executeSqlFetch(
                "SELECT is_builtin FROM cn_stock_custom_indicator WHERE indicator_id=%s",
                (iid,)) or []
            if row:
                is_builtin = row[0][0] if isinstance(row[0], (list, tuple)) else row[0].get("is_builtin", 0)
                if int(is_builtin) == 1:
                    self.write(json.dumps(
                        {"code": -1, "msg": "内置预设不可修改，请另存为新指标"},
                        ensure_ascii=False))
                    return

            params = (
                iid,
                body["name"].strip(),
                body.get("kind", "watchlist_alert"),
                body.get("description") or None,
                json.dumps(body.get("weights") or {}, ensure_ascii=False),
                int(body.get("smooth_ema") or 0),
                float(body.get("buy_th") or 0),
                body.get("direction", "high"),
                body.get("extra_filter") or None,
                body.get("hard_rules") or None,
                json.dumps(body.get("risk_profile") or {}, ensure_ascii=False),
                0,  # is_builtin = 0 for user-created
            )
            mdb.executeSql("""
                INSERT INTO cn_stock_custom_indicator
                  (indicator_id, name, kind, description, weights, smooth_ema, buy_th,
                   direction, extra_filter, hard_rules, risk_profile, is_builtin)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE
                  name=VALUES(name), kind=VALUES(kind), description=VALUES(description),
                  weights=VALUES(weights), smooth_ema=VALUES(smooth_ema),
                  buy_th=VALUES(buy_th), direction=VALUES(direction),
                  extra_filter=VALUES(extra_filter), hard_rules=VALUES(hard_rules),
                  risk_profile=VALUES(risk_profile)
            """, params)
            self.write(json.dumps({"code": 0, "data": {"indicator_id": iid}},
                                  ensure_ascii=False))
        except Exception as e:
            logging.error("SaveCustomIndicator 异常", exc_info=True)
            self.write(json.dumps({"code": -1, "msg": str(e)}, ensure_ascii=False))


# ----------------------------------------------------------------------------
# 4. Delete
# ----------------------------------------------------------------------------
class DeleteCustomIndicatorHandler(webBase.BaseHandler, ABC):
    """POST /quantia/api/custom_indicator/delete  —— 内置预设禁删除。"""

    @gen.coroutine
    def post(self):
        try:
            _ensure_custom_indicator_table()
            body = json.loads(self.request.body or b"{}")
            iid = (body.get("indicator_id") or "").strip()
            if not iid:
                self.write(json.dumps({"code": -1, "msg": "indicator_id 不能为空"},
                                      ensure_ascii=False))
                return
            row = mdb.executeSqlFetch(
                "SELECT is_builtin FROM cn_stock_custom_indicator WHERE indicator_id=%s",
                (iid,)) or []
            if not row:
                self.write(json.dumps({"code": -1, "msg": "指标不存在"},
                                      ensure_ascii=False))
                return
            is_builtin = row[0][0] if isinstance(row[0], (list, tuple)) else row[0].get("is_builtin", 0)
            if int(is_builtin) == 1:
                self.write(json.dumps({"code": -1, "msg": "内置预设不可删除"},
                                      ensure_ascii=False))
                return
            mdb.executeSql(
                "DELETE FROM cn_stock_custom_indicator WHERE indicator_id=%s",
                (iid,))
            self.write(json.dumps({"code": 0}, ensure_ascii=False))
        except Exception as e:
            logging.error("DeleteCustomIndicator 异常", exc_info=True)
            self.write(json.dumps({"code": -1, "msg": str(e)}, ensure_ascii=False))


# ============================================================================
#                  共享：Indicator → Signal → Trade 流水线
# ============================================================================

def _load_indicator_record(iid: str) -> dict | None:
    cols = ["indicator_id", "name", "kind", "weights", "smooth_ema", "buy_th",
            "direction", "extra_filter", "hard_rules", "risk_profile"]
    sql = (f"SELECT {', '.join(cols)} FROM cn_stock_custom_indicator "
           "WHERE indicator_id=%s LIMIT 1")
    rows = mdb.executeSqlFetch(sql, (iid,)) or []
    if not rows:
        return None
    d = _row_to_dict(rows[0], cols)
    d["weights"] = _parse_json_field(d.get("weights"), {})
    d["risk_profile"] = _parse_json_field(d.get("risk_profile"), {})
    return d


def _load_hist_df(code: str, years: int = 5) -> pd.DataFrame | None:
    """统一从 stockfetch 缓存加载 OHLCV（与 K 线 handler 同源）。"""
    try:
        import quantia.core.stockfetch as stf
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        df = stf.read_hist_from_cache((today, code), years=years)
        if df is None or df.empty:
            df = stf.read_index_hist_from_cache(code)
        if df is None or df.empty:
            return None
        df = df.copy()
        df["date"] = pd.to_datetime(df["date"])
        return df.sort_values("date").reset_index(drop=True)
    except Exception as e:
        logging.warning(f"_load_hist_df({code}) failed: {e}")
        return None


def _compute_signal(rec: dict, d: pd.DataFrame) -> tuple[pd.Series, pd.Series | None]:
    """
    返回 (signal_bool_series, score_series_or_None)。
    主信号策略：hard_rules（如有）AND extra_filter（如有）。
    评分策略：weights 加权（direction high/low）+ extra_filter（如有）。
    """
    score: pd.Series | None = None
    sig: pd.Series | None = None

    weights = rec.get("weights") or {}
    if weights:
        comp = Composite(
            name=rec.get("name", ""),
            weights={k: float(v) for k, v in weights.items()},
            smooth_ema=int(rec.get("smooth_ema") or 0),
            buy_th=float(rec.get("buy_th") or 0),
            direction=rec.get("direction") or "high",
        )
        score = comp.value(d)
        sig = comp.signal(d)

    hard_rules = rec.get("hard_rules") or ""
    if hard_rules:
        rule_sig = eval_hard_rules(hard_rules, d)
        sig = rule_sig if sig is None else (sig | rule_sig)

    extra = rec.get("extra_filter") or ""
    if extra and sig is not None:
        sig = sig & eval_hard_rules(extra, d)

    if sig is None:
        # 兜底：无 weights、无 hard_rules — 全 False
        sig = pd.Series([False] * len(d), index=d.index)
    return sig.fillna(False).astype(bool), score


# ----------------------------------------------------------------------------
# 5. Backtest（单股快速回测）
# ----------------------------------------------------------------------------
class BacktestCustomIndicatorHandler(webBase.BaseHandler, ABC):
    """
    POST /quantia/api/custom_indicator/backtest
    body: { indicator_id, code, start?, end?, stop?, target?, max_hold? }

    返回：交易明细 + 汇总（PF / win% / expectancy% / avg_hold ...）
    """

    @gen.coroutine
    def post(self):
        try:
            body = json.loads(self.request.body or b"{}")
            iid = (body.get("indicator_id") or "").strip()
            code = (body.get("code") or "").strip().zfill(6)
            if not iid or not code:
                self.write(json.dumps(
                    {"code": -1, "msg": "indicator_id / code 不能为空"},
                    ensure_ascii=False))
                return
            rec = _load_indicator_record(iid)
            if not rec:
                self.write(json.dumps({"code": -1, "msg": "指标不存在"},
                                      ensure_ascii=False))
                return

            df = _load_hist_df(code)
            if df is None:
                self.write(json.dumps(
                    {"code": -1, "msg": f"无 K 线数据：{code}"},
                    ensure_ascii=False))
                return

            start = body.get("start")
            end = body.get("end")
            if start:
                df = df[df["date"] >= pd.Timestamp(start)].reset_index(drop=True)
            if end:
                df = df[df["date"] <= pd.Timestamp(end)].reset_index(drop=True)
            if len(df) < 60:
                self.write(json.dumps(
                    {"code": -1, "msg": "数据量不足 60 根，无法回测"},
                    ensure_ascii=False))
                return

            d = enrich(df)
            try:
                sig, _ = _compute_signal(rec, d)
            except (SecurityError, RuleEvalError) as e:
                self.write(json.dumps({"code": -1, "msg": str(e)}, ensure_ascii=False))
                return
            except KeyError as e:
                self.write(json.dumps(
                    {"code": -1, "msg": f"指标字段缺失：{e}"},
                    ensure_ascii=False))
                return

            risk = rec.get("risk_profile") or {}
            stop = float(body.get("stop") or risk.get("stop") or -0.08)
            target = float(body.get("target") or risk.get("target") or 0.20)
            max_hold = int(body.get("max_hold") or risk.get("max_hold") or 60)
            # 由于 simulate 使用 stop_loss 正值
            trades = simulate(
                code, d, sig,
                stop_loss=abs(stop),
                take_profit=abs(target),
                max_hold=max_hold,
            )
            summary = summarize_trades(trades, name=rec.get("name", ""))
            trades_payload = [{
                "entry_date": str(t.entry_date.date()),
                "entry_price": t.entry_price,
                "exit_date": str(t.exit_date.date()),
                "exit_price": t.exit_price,
                "reason": t.reason,
                "net_ret_pct": round(t.net_ret * 100, 3),
                "hold_days": t.hold_days,
            } for t in trades]
            self.write(json.dumps({
                "code": 0,
                "data": {
                    "indicator_id": iid,
                    "stock_code": code,
                    "trades": trades_payload,
                    "summary": summary,
                }
            }, ensure_ascii=False))
        except Exception as e:
            logging.error("BacktestCustomIndicator 异常", exc_info=True)
            self.write(json.dumps({"code": -1, "msg": str(e)}, ensure_ascii=False))


# ----------------------------------------------------------------------------
# 6. Watchlist Today
# ----------------------------------------------------------------------------
class WatchlistTodayHandler(webBase.BaseHandler, ABC):
    """
    GET /quantia/api/custom_indicator/watchlist?indicator_id=xxx[&top_n=50]

    扫描动态股票池，返回今天触发信号的股票（评分类返回最新 score 排序前 N）。
    """

    @gen.coroutine
    def get(self):
        try:
            iid = self.get_argument("indicator_id", default="").strip()
            top_n = int(self.get_argument("top_n", default="50"))
            top_n = min(max(top_n, 1), 200)
            if not iid:
                self.write(json.dumps({"code": -1, "msg": "indicator_id 不能为空"},
                                      ensure_ascii=False))
                return
            rec = _load_indicator_record(iid)
            if not rec:
                self.write(json.dumps({"code": -1, "msg": "指标不存在"},
                                      ensure_ascii=False))
                return
            universe = du.fetch_universe(top_n=200)
            if universe is None or universe.empty:
                self.write(json.dumps({"code": 0, "data": {"items": [], "msg": "股票池为空"}},
                                      ensure_ascii=False))
                return
            items = []
            for _, row in universe.iterrows():
                code = str(row["code"]).zfill(6)
                df = _load_hist_df(code, years=2)
                if df is None or len(df) < 60:
                    continue
                try:
                    d = enrich(df)
                    sig, score = _compute_signal(rec, d)
                except (SecurityError, RuleEvalError, KeyError):
                    continue
                today_sig = bool(sig.iloc[-1]) if len(sig) else False
                latest_score = (float(score.iloc[-1])
                                if score is not None and len(score) and pd.notna(score.iloc[-1])
                                else None)
                if rec["kind"] == "primary_entry":
                    if today_sig:
                        items.append({
                            "code": code, "name": row.get("name"),
                            "industry": row.get("industry"),
                            "close": float(df["close"].iloc[-1]),
                            "fundamentals_score": float(row.get("score") or 0),
                            "latest_score": latest_score,
                        })
                else:
                    items.append({
                        "code": code, "name": row.get("name"),
                        "industry": row.get("industry"),
                        "close": float(df["close"].iloc[-1]),
                        "fundamentals_score": float(row.get("score") or 0),
                        "latest_score": latest_score,
                    })
                if len(items) >= top_n * 2:
                    break
            # 评分类：按 latest_score 排序
            if rec["kind"] == "watchlist_alert":
                items.sort(key=lambda x: (x.get("latest_score") or 0), reverse=True)
            items = items[:top_n]
            self.write(json.dumps({
                "code": 0,
                "data": {
                    "indicator_id": iid,
                    "kind": rec["kind"],
                    "name": rec["name"],
                    "items": items,
                    "warning": ("⚠️ 评分类指标，仅供参考，禁止直接驱动交易"
                                if rec["kind"] == "watchlist_alert" else None),
                },
            }, ensure_ascii=False))
        except Exception as e:
            logging.error("WatchlistToday 异常", exc_info=True)
            self.write(json.dumps({"code": -1, "msg": str(e)}, ensure_ascii=False))


# ----------------------------------------------------------------------------
# 7. Series （PR-5 K 线叠加用）
# ----------------------------------------------------------------------------
class IndicatorSeriesHandler(webBase.BaseHandler, ABC):
    """
    GET /quantia/api/custom_indicator/series
        ?indicator_id=xxx&code=000001&start=YYYY-MM-DD&end=YYYY-MM-DD&period=daily

    返回评分曲线 + 信号点：
    {
      indicator_id, name, kind,
      score_series: [{date, score}, ...],
      signal_points: [{date, price, action}, ...]
    }
    """

    @gen.coroutine
    def get(self):
        try:
            iid = self.get_argument("indicator_id", default="").strip()
            code = self.get_argument("code", default="").strip().zfill(6)
            start = self.get_argument("start", default=None)
            end = self.get_argument("end", default=None)
            period = self.get_argument("period", default="daily")
            if not iid or not code:
                self.write(json.dumps(
                    {"code": -1, "msg": "indicator_id / code 不能为空"},
                    ensure_ascii=False))
                return
            if period != "daily":
                # 暂仅支持 daily（与回测一致），其他周期将在 PR-5 末端补齐
                self.write(json.dumps(
                    {"code": -1, "msg": f"暂不支持周期：{period}（仅 daily）"},
                    ensure_ascii=False))
                return
            rec = _load_indicator_record(iid)
            if not rec:
                self.write(json.dumps({"code": -1, "msg": "指标不存在"},
                                      ensure_ascii=False))
                return
            # 根据 start 参数自适应回溯年限，确保覆盖前端 K 线起始位置
            # （否则默认 5 年加载会让长上市股票（如 300059 自 2010 上市）
            #  的副图曲线只从 ~5 年前开始）
            years = 5
            if start:
                try:
                    yrs_needed = max(
                        1,
                        int((datetime.datetime.now()
                             - datetime.datetime.strptime(start[:10], "%Y-%m-%d")
                             ).days / 365) + 1,
                    )
                    years = max(years, yrs_needed)
                except Exception:
                    pass
            df = _load_hist_df(code, years=years)
            if df is None:
                self.write(json.dumps(
                    {"code": -1, "msg": f"无 K 线数据：{code}"},
                    ensure_ascii=False))
                return
            d = enrich(df)
            try:
                sig, score = _compute_signal(rec, d)
            except (SecurityError, RuleEvalError) as e:
                self.write(json.dumps({"code": -1, "msg": str(e)}, ensure_ascii=False))
                return
            except KeyError as e:
                self.write(json.dumps(
                    {"code": -1, "msg": f"指标字段缺失：{e}"},
                    ensure_ascii=False))
                return
            # 切片
            mask = pd.Series([True] * len(d), index=d.index)
            if start:
                mask &= d["date"] >= pd.Timestamp(start)
            if end:
                mask &= d["date"] <= pd.Timestamp(end)
            d = d[mask].reset_index(drop=True)
            sig = sig[mask.values].reset_index(drop=True)
            if score is not None:
                score = score[mask.values].reset_index(drop=True)

            # score 优先用 weights composite；纯 hard_rules 指标无连续评分，
            # 退化为 0/100 二值序列以便副图展示"信号触发窗口"
            score_series = []
            if score is not None:
                for dt, v in zip(d["date"], score):
                    if pd.notna(v):
                        score_series.append({
                            "date": str(pd.Timestamp(dt).date()),
                            "score": round(float(v), 3),
                        })
            else:
                for dt, hit in zip(d["date"], sig):
                    score_series.append({
                        "date": str(pd.Timestamp(dt).date()),
                        "score": 100.0 if bool(hit) else 0.0,
                    })

            # 买入信号点 + 风控模拟出场点（per dev plan §4.4 sell-stop / sell-target / sell-time）
            # 构造买入理由（取指标的 hard_rules / extra_filter / weights 摘要）
            buy_reason_parts = []
            if rec.get("hard_rules"):
                buy_reason_parts.append(f"硬规则命中: {rec['hard_rules']}")
            if rec.get("extra_filter"):
                buy_reason_parts.append(f"过滤条件: {rec['extra_filter']}")
            if rec.get("weights"):
                _w = rec.get("weights") or {}
                _top = sorted(_w.items(), key=lambda kv: -abs(float(kv[1] or 0)))[:5]
                buy_reason_parts.append(
                    "评分权重Top: " + ", ".join(f"{k}({v:+.2f})" for k, v in _top)
                )
            buy_reason = "; ".join(buy_reason_parts) or f"{rec['name']} 信号触发"
            _reason_text = {
                "buy": buy_reason,
                "sell-stop": f"止损出场（≤ {abs(float((rec.get('risk_profile') or {}).get('stop') or -0.08))*100:.1f}%）",
                "sell-target": f"止盈出场（≥ {abs(float((rec.get('risk_profile') or {}).get('target') or 0.20))*100:.1f}%）",
                "sell-time": f"持有到期出场（{int((rec.get('risk_profile') or {}).get('max_hold') or 60)} 日）",
                "sell-fund": "基本面恶化出场",
                "sell": "策略卖出",
            }
            signal_points = []
            for i in range(len(d)):
                if bool(sig.iloc[i]):
                    signal_points.append({
                        "date": str(pd.Timestamp(d["date"].iloc[i]).date()),
                        "price": round(float(d["close"].iloc[i]), 4),
                        "action": "buy",
                        "reason": _reason_text["buy"],
                    })

            risk = rec.get("risk_profile") or {}
            try:
                trades = simulate(
                    code, d, sig,
                    stop_loss=abs(float(risk.get("stop") or -0.08)),
                    take_profit=abs(float(risk.get("target") or 0.20)),
                    max_hold=int(risk.get("max_hold") or 60),
                )
                _reason_to_action = {
                    "stop-loss": "sell-stop",
                    "win-target": "sell-target",
                    "time-exit": "sell-time",
                    "fundamentals-exit": "sell-fund",
                }
                for t in trades:
                    act = _reason_to_action.get(t.reason, "sell")
                    signal_points.append({
                        "date": str(t.exit_date.date()),
                        "price": round(float(t.exit_price), 4),
                        "action": act,
                        "reason": _reason_text.get(act, "策略卖出"),
                    })
            except Exception as _e:
                logging.debug(f"IndicatorSeries simulate skipped: {_e}")

            self.write(json.dumps({
                "code": 0,
                "data": {
                    "indicator_id": iid,
                    "name": rec["name"],
                    "kind": rec["kind"],
                    "score_series": score_series,
                    "signal_points": signal_points,
                },
            }, ensure_ascii=False))
        except Exception as e:
            logging.error("IndicatorSeries 异常", exc_info=True)
            self.write(json.dumps({"code": -1, "msg": str(e)}, ensure_ascii=False))


__all__ = [
    "_ensure_custom_indicator_table",
    "_seed_builtin_indicators",
    "bootstrap",
    # Handlers
    "ListCustomIndicatorHandler",
    "GetCustomIndicatorHandler",
    "SaveCustomIndicatorHandler",
    "DeleteCustomIndicatorHandler",
    "BacktestCustomIndicatorHandler",
    "WatchlistTodayHandler",
    "IndicatorSeriesHandler",
]
