#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""F12 基金季度前十大重仓股缓存（独立慢 job，季频）。

逐基金抓取 fund_portfolio_hold_em 最新季度前十大重仓股，LEFT JOIN 本项目股票
行业表（cn_stock_selection，只读 MySQL）回填 industry，写 cn_fund_holding。
支持「按行业筛选/对比」+ 详情持仓展示。

抓取范围：默认覆盖含权益的桶（股票型/混合型/指数型）按近1年收益的 Top-N；
货币型/纯债型无股票重仓 → 跳过。行业映射仅对 A 股有效，QDII/港股/海外/债券
持仓归 "未分类"。属 fetch 管道（akshare 抓取 + 读库回填，均允许）。
低频 cron（cron.monthly）或手动触发。

用法：
    python fetch_fund_holding_job.py [code1 code2 ...]
    python fetch_fund_holding_job.py
"""
import datetime
import logging
import os.path
import random
import sys
import time

cpath_current = os.path.dirname(os.path.dirname(__file__))
cpath = os.path.abspath(os.path.join(cpath_current, os.pardir))
sys.path.append(cpath)
try:
    from quantia.lib.log_config import setup_logging
    setup_logging('fetch')
except Exception:
    log_path = os.path.join(cpath_current, 'log')
    os.makedirs(log_path, exist_ok=True)
    logging.basicConfig(
        format='%(asctime)s [%(levelname)s] %(message)s',
        filename=os.path.join(log_path, 'fund_holding_job.log'),
        level=logging.INFO,
    )

import quantia.core.tablestructure as tbs
import quantia.core.crawling.fund_em as fem
import quantia.lib.database as mdb
import quantia.lib.envconfig as _cfg
import quantia.lib.sysconfig as sysconfig
from quantia.lib.job_tracker import record_task_start, record_task_end

__author__ = 'Quantia'
__date__ = '2026/06/01'

_JOB_NAME = 'run_fund_holding'
_RANK_TABLE = tbs.TABLE_CN_FUND_RANK['name']
_HOLDING_TABLE = tbs.TABLE_CN_FUND_HOLDING['name']
_SELECTION_TABLE = tbs.TABLE_CN_STOCK_SELECTION['name']
_HOLDING_COLS = list(tbs.TABLE_CN_FUND_HOLDING['columns'])
# 含权益重仓的桶（货币型/纯债无股票重仓）
_EQUITY_TYPES = ['股票型', '混合型', '指数型']
_UNKNOWN_INDUSTRY = '未分类'

# 方案C「全覆盖」开关键（cn_system_config，前端可切换、cron 读取决定是否分层分批全量抓）。
FULL_COVERAGE_KEY = 'fund_holding_full_coverage'

# 方案C 抓取尝试日志表：记录「本周期已尝试过」的基金（含 akshare 返回空的），
# 使分层分批可单调推进——空数据基金（如指数/ETF联接无 fund_portfolio_hold_em 披露）
# 不会因为永远没有持仓行而被反复重选，保证本周期能跑完并幂等续跑。
_ATTEMPT_TABLE = 'cn_fund_holding_attempt'
_attempt_table_ready = False


def _ensure_attempt_table():
    global _attempt_table_ready
    if _attempt_table_ready:
        return
    try:
        mdb.executeSql(
            f"CREATE TABLE IF NOT EXISTS `{_ATTEMPT_TABLE}` ("
            f"  `code` VARCHAR(8) NOT NULL,"
            f"  `attempt_date` DATE DEFAULT NULL,"
            f"  `has_data` TINYINT(1) DEFAULT 0,"
            f"  `update_time` DATETIME DEFAULT NULL,"
            f"  PRIMARY KEY (`code`),"
            f"  KEY `idx_attempt_date` (`attempt_date`)"
            f") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci")
        _attempt_table_ready = True
    except Exception:
        logging.warning("fetch_fund_holding_job: 创建抓取尝试日志表失败", exc_info=True)


def _record_attempt(code, has_data, attempt_date):
    """记录单只基金本次抓取尝试（成功或空均记），供全覆盖跳过已尝试。"""
    try:
        _ensure_attempt_table()
        mdb.executeSql(
            f"INSERT INTO `{_ATTEMPT_TABLE}` (`code`, `attempt_date`, `has_data`, `update_time`) "
            f"VALUES (%s, %s, %s, %s) "
            f"ON DUPLICATE KEY UPDATE `attempt_date` = VALUES(`attempt_date`), "
            f"`has_data` = VALUES(`has_data`), `update_time` = VALUES(`update_time`)",
            (str(code), attempt_date, 1 if has_data else 0, datetime.datetime.now()))
    except Exception:
        logging.warning(f"fetch_fund_holding_job: {code} 记录抓取尝试失败", exc_info=True)


def _select_target_codes(limit_per_type):
    """含权益桶按近1年收益取 Top-N 的 code。"""
    if not mdb.checkTableIsExist(_RANK_TABLE):
        return []
    placeholders = ','.join(['%s'] * len(_EQUITY_TYPES))
    sql = (
        f"SELECT code FROM ("
        f"  SELECT code,"
        f"    ROW_NUMBER() OVER (PARTITION BY fund_type ORDER BY (`rate_1y` IS NULL), `rate_1y` DESC) AS rn"
        f"  FROM `{_RANK_TABLE}`"
        f"  WHERE `date` = (SELECT MAX(`date`) FROM `{_RANK_TABLE}`)"
        f"    AND fund_type IN ({placeholders})"
        f") t WHERE t.rn <= %s"
    )
    rows = mdb.executeSqlFetch(sql, (*_EQUITY_TYPES, int(limit_per_type)))
    return [str(r[0]) for r in rows if r and r[0] is not None]


def _select_full_coverage_batch(batch_per_type, cycle_floor):
    """方案C 分层分批：每类按近1年收益 DESC（分层=好基金优先）取「本周期尚未抓过」
    的前 batch_per_type 只（分批）。已在 cycle_floor 之后抓过的基金自动跳过（可断点续跑/幂等）。
    """
    if not mdb.checkTableIsExist(_RANK_TABLE):
        return []
    _ensure_attempt_table()
    placeholders = ','.join(['%s'] * len(_EQUITY_TYPES))
    sql = (
        f"SELECT code FROM ("
        f"  SELECT r.code,"
        f"    ROW_NUMBER() OVER (PARTITION BY r.fund_type ORDER BY (r.`rate_1y` IS NULL), r.`rate_1y` DESC) AS rn"
        f"  FROM `{_RANK_TABLE}` r"
        f"  WHERE r.`date` = (SELECT MAX(`date`) FROM `{_RANK_TABLE}`)"
        f"    AND r.fund_type IN ({placeholders})"
        f"    AND NOT EXISTS ("
        f"      SELECT 1 FROM `{_HOLDING_TABLE}` h"
        f"      WHERE h.`code` = r.code AND h.`update_date` >= %s)"
        f"    AND NOT EXISTS ("
        f"      SELECT 1 FROM `{_ATTEMPT_TABLE}` a"
        f"      WHERE a.`code` = r.code AND a.`attempt_date` >= %s)"
        f") t WHERE t.rn <= %s"
    )
    rows = mdb.executeSqlFetch(sql, (*_EQUITY_TYPES, cycle_floor, cycle_floor, int(batch_per_type)))
    return [str(r[0]) for r in rows if r and r[0] is not None]


def _count_remaining_full_coverage(cycle_floor):
    """方案C 本周期尚未抓且尚未尝试的权益基金数量（用于进度/收尾日志）。"""
    if not mdb.checkTableIsExist(_RANK_TABLE):
        return 0
    _ensure_attempt_table()
    placeholders = ','.join(['%s'] * len(_EQUITY_TYPES))
    sql = (
        f"SELECT COUNT(*) FROM `{_RANK_TABLE}` r"
        f"  WHERE r.`date` = (SELECT MAX(`date`) FROM `{_RANK_TABLE}`)"
        f"    AND r.fund_type IN ({placeholders})"
        f"    AND NOT EXISTS ("
        f"      SELECT 1 FROM `{_HOLDING_TABLE}` h"
        f"      WHERE h.`code` = r.code AND h.`update_date` >= %s)"
        f"    AND NOT EXISTS ("
        f"      SELECT 1 FROM `{_ATTEMPT_TABLE}` a"
        f"      WHERE a.`code` = r.code AND a.`attempt_date` >= %s)"
    )
    rows = mdb.executeSqlFetch(sql, (*_EQUITY_TYPES, cycle_floor, cycle_floor))
    return int(rows[0][0]) if rows and rows[0] else 0


def _load_industry_map():
    """读 cn_stock_selection 的 (stock_code → industry) 映射（只读 MySQL，不调外部 API）。"""
    if not mdb.checkTableIsExist(_SELECTION_TABLE):
        return {}
    try:
        rows = mdb.executeSqlFetch(
            f"SELECT `code`, `industry` FROM `{_SELECTION_TABLE}`")
    except Exception:
        logging.warning("fetch_fund_holding_job: 读取行业映射失败，全部归未分类", exc_info=True)
        return {}
    out = {}
    for r in rows:
        if r and r[0] is not None:
            out[str(r[0]).zfill(6)] = r[1]
    return out


def _join_industry(df, industry_map):
    """按 stock_code 回填 industry，缺失填 未分类。纯函数。"""
    def _lookup(sc):
        ind = industry_map.get(str(sc).zfill(6)) if sc is not None else None
        return ind if ind else _UNKNOWN_INDUSTRY
    df = df.copy()
    df['industry'] = df['stock_code'].map(_lookup)
    return df


def save_fund_holding(code, year, industry_map, update_date):
    """抓取 + 行业回填 + 删旧重写单只基金最新季度持仓，返回写入行数。"""
    df = fem.fund_holding_latest(code, year)
    if df is None or len(df.index) == 0:
        return 0
    df = _join_industry(df, industry_map)
    df['update_date'] = update_date
    # 对齐表列序，缺失列补 None
    for col in _HOLDING_COLS:
        if col not in df.columns:
            df[col] = None
    df = df[_HOLDING_COLS]

    # 删旧（同 code 旧季度）后重写，避免换季后陈旧季度残留
    if mdb.checkTableIsExist(_HOLDING_TABLE):
        try:
            mdb.executeSql(
                f"DELETE FROM `{_HOLDING_TABLE}` WHERE `code` = %s", (str(code),))
        except Exception:
            logging.warning(f"fetch_fund_holding_job: {code} 删除旧持仓失败，改用 upsert", exc_info=True)
        cols_type = None
    else:
        cols_type = tbs.get_field_types(tbs.TABLE_CN_FUND_HOLDING['columns'])
    mdb.insert_db_from_df(df, _HOLDING_TABLE, cols_type, False,
                          "`code`,`quarter`,`stock_code`")
    return len(df.index)


def _crawl_codes(codes, year, industry_map, update_date, deadline=None):
    """逐只抓取 + 限速，返回 (ok有持仓数, total_rows, stopped, attempted)。单只异常吞掉跳过，不中断批量。

    deadline（time.monotonic 时刻）非空时，在「每只之间」检查时间预算并干净停止，
    避免被外层 timeout SIGTERM 在 save_fund_holding 的「删旧→写新」之间打断。
    attempted = 本批中「未抛异常、已记录 attempt」的基金数；用于上层判断数据源是否整体不可达。
    """
    total_rows = 0
    ok = 0
    attempted = 0
    stopped = False
    for code in codes:
        if deadline is not None and time.monotonic() >= deadline:
            stopped = True
            break
        try:
            n = save_fund_holding(code, year, industry_map, update_date)
            total_rows += n
            if n > 0:
                ok += 1
            _record_attempt(code, n > 0, update_date)
            attempted += 1
        except Exception:
            logging.warning(f"fetch_fund_holding_job: {code} 处理失败，跳过", exc_info=True)
        finally:
            time.sleep(random.uniform(0.5, 1.5))  # 限速
    return ok, total_rows, stopped, attempted


def run(codes=None, limit_per_type=None, job_date=None):
    job_date = job_date or datetime.date.today()
    update_date = job_date
    year = job_date.year
    if limit_per_type is None:
        limit_per_type = _cfg.get_int('QUANTIA_FUND_HOLDING_TOPN', 200)
    if not codes:
        codes = _select_target_codes(limit_per_type)
    if not codes:
        logging.warning("fetch_fund_holding_job: 无目标基金（cn_fund_rank 为空？）")
        return 0

    industry_map = _load_industry_map()
    start = record_task_start(_JOB_NAME, 'holding', job_date)
    ok, total_rows, _, _ = _crawl_codes(codes, year, industry_map, update_date)
    record_task_end(_JOB_NAME, 'holding', job_date, start, success=True,
                    message=f"{ok}/{len(codes)} 基金有持仓", rows_affected=total_rows)
    logging.info(f"fetch_fund_holding_job 完成：{ok}/{len(codes)} 基金，共 {total_rows} 行持仓")
    return total_rows


def run_full_coverage(batch_per_type=None, max_seconds=None, job_date=None):
    """方案C：分层（按 rate_1y DESC）分批（每类 batch_per_type 只/批）全量抓取。

    幂等可断点续跑：已在本周期（本月）抓过的基金自动跳过。反复调用会逐步覆盖全市场，
    每只基金本月只抓一次。max_seconds>0 时达时间预算就停，剩余留待下次。保证准确性：
    仅写 akshare 返回的有效行，DELETE+insert 避免陈旧季度残留，SSL 瞬态失败已由 fund_em 重试。
    """
    job_date = job_date or datetime.date.today()
    update_date = job_date
    year = job_date.year
    cycle_floor = job_date.replace(day=1)  # 本月首日：本周期刷新地板
    if batch_per_type is None:
        batch_per_type = _cfg.get_int('QUANTIA_FUND_HOLDING_BATCH', 1000)
    if max_seconds is None:
        max_seconds = _cfg.get_int('QUANTIA_FUND_HOLDING_MAX_SECONDS', 0)  # 0=不限时
    deadline = time.monotonic() + max_seconds if max_seconds and max_seconds > 0 else None

    industry_map = _load_industry_map()
    start = record_task_start(_JOB_NAME, 'holding_full', job_date)
    grand_total = 0
    grand_ok = 0
    batch_no = 0
    while True:
        if deadline and time.monotonic() >= deadline:
            logging.info("fetch_fund_holding_job 全覆盖：达到时间预算，剩余留待下次")
            break
        codes = _select_full_coverage_batch(batch_per_type, cycle_floor)
        if not codes:
            logging.info("fetch_fund_holding_job 全覆盖：本周期已全部覆盖")
            break
        batch_no += 1
        ok, rows, stopped, attempted = _crawl_codes(codes, year, industry_map, update_date, deadline=deadline)
        grand_total += rows
        grand_ok += ok
        logging.info(f"fetch_fund_holding_job 全覆盖第{batch_no}批：{ok}/{len(codes)} 只有持仓，本批 {rows} 行")
        if stopped:
            logging.info("fetch_fund_holding_job 全覆盖：批内达到时间预算，干净停止，剩余留待下次")
            break
        # 无进展守卫：整批基金全部抛异常（attempted==0）且无新行，说明数据源整体不可达
        # （如东方财富封禁本机 IP）。此时不记录任何 attempt → 下一轮会重选同一批 →
        # 在无 deadline 时陷入死循环、有 deadline 时持续空转并疯狂重试，反而加重封禁。
        # 直接干净停止，剩余留待下次（届时 IP 可能已解封）。
        if attempted == 0:
            logging.warning(
                f"fetch_fund_holding_job 全覆盖：本批 {len(codes)} 只全部抓取失败且 0 进展，"
                f"数据源疑似不可达/被封禁，提前停止避免空转与重试风暴，剩余留待下次")
            break
    remaining = _count_remaining_full_coverage(cycle_floor)
    record_task_end(_JOB_NAME, 'holding_full', job_date, start, success=True,
                    message=f"全覆盖{batch_no}批 ok={grand_ok} 剩余={remaining}",
                    rows_affected=grand_total)
    logging.info(f"fetch_fund_holding_job 全覆盖完成：{batch_no}批，ok={grand_ok}，共 {grand_total} 行，本周期剩余 {remaining} 只")
    return grand_total


def main():
    args = [a for a in sys.argv[1:] if a.strip()]
    flags = {a for a in args if a.startswith('--')}
    codes = [a for a in args if not a.startswith('--')]
    if codes:
        # 显式 code：定点补抓，忽略全覆盖开关
        run(codes=codes)
        return
    # --full-if-enabled：仅当全覆盖开关开启时分层分批抓取，否则空跑退出（供每日定时器调用）
    if '--full-if-enabled' in flags:
        if sysconfig.get_bool(FULL_COVERAGE_KEY, False):
            run_full_coverage()
        else:
            logging.info("fetch_fund_holding_job: 全覆盖(方案C)未开启，--full-if-enabled 空跑跳过")
        return
    # 无显式 code：根据开关（前端可切）或 --full 决定是否走方案C 分层分批全量
    if '--full' in flags or sysconfig.get_bool(FULL_COVERAGE_KEY, False):
        run_full_coverage()
    else:
        run()


if __name__ == '__main__':
    main()
