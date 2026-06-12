"""
A股历史财务数据采集（项目集成版）
数据来源：AkShare (https://akshare.akfamily.xyz) — 东方财富个股财务分析指标
目标数据库：quantiadb.cn_stock_financial

采集内容：
  - 个股财务分析指标（东方财富），包括：
    EPS、BPS、每股经营现金流、营业收入、净利润、
    营收同比增长率、净利润同比增长率、ROE、ROA、
    毛利率、净利率、资产负债率、流动比率、速动比率、
    总资产周转率、存货周转率、应收账款周转率

用途：
  - 为《低ATR成长策略》等多因子策略回测提供真实财务数据
  - 替换 fundamentals.py 中的合成基本面数据

用法：
  python stock_financial_data.py                 # 全量采集
  python stock_financial_data.py --test 10       # 测试模式，仅采集前10只
  python stock_financial_data.py --incremental   # 增量模式，仅采集最近报告期
  python stock_financial_data.py --years 5       # 仅采集最近5年的数据
"""

import logging
import time
import argparse
import os
import sys
import json
from datetime import datetime

import akshare as ak
import pandas as pd

# 确保项目根目录在 sys.path 中
cpath_current = os.path.dirname(os.path.dirname(__file__))
cpath = os.path.abspath(os.path.join(cpath_current, os.pardir))
sys.path.append(cpath)

import quantia.lib.database as mdb
import quantia.lib.envconfig as _cfg
from quantia.core.tablestructure import TABLE_CN_STOCK_FINANCIAL

__author__ = 'Quantia'
__date__ = '2026/03/23'

log = logging.getLogger(__name__)


# ─── 配置 ────────────────────────────────────────────────────────────────────
SLEEP_PER_STOCK = _cfg.get_float('QUANTIA_FINANCIAL_SLEEP', 2.0)
RETRY_TIMES = _cfg.get_int('QUANTIA_FINANCIAL_RETRIES', 2)
RETRY_SLEEP = _cfg.get_int('QUANTIA_FINANCIAL_RETRY_SLEEP', 5)
DB_RETRY_TIMES = _cfg.get_int('QUANTIA_FINANCIAL_DB_RETRIES', 3)
DB_RETRY_SLEEP = _cfg.get_int('QUANTIA_FINANCIAL_DB_RETRY_SLEEP', 3)
# 连续失败熔断：连续 N 只股票失败即判定系统性故障（如DB持续宕机），主动中止，
# 避免在持续故障下对数千只股票逐一空转重试（设为 0 可禁用）。
MAX_CONSECUTIVE_FAILS = _cfg.get_int('QUANTIA_FINANCIAL_MAX_CONSECUTIVE_FAILS', 30)
# 断点续跑：将已处理股票落盘，进程意外退出后可从上次位置继续（设 0 可禁用）。
CKPT_ENABLED = _cfg.get_int('QUANTIA_FINANCIAL_CKPT', 1)
CKPT_SAVE_EVERY = _cfg.get_int('QUANTIA_FINANCIAL_CKPT_EVERY', 20)
_CKPT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'log'))

# 东方财富 API 字段到数据库字段的映射
_EM_COL_MAP = {
    'SECURITY_CODE': 'code',
    'REPORT_DATE': 'report_date',
    'REPORT_DATE_NAME': 'report_name',
    'EPSJB': 'eps',
    'BPS': 'bps',
    'MGJYXJJE': 'ocfps',
    'TOTALOPERATEREVE': 'revenue',
    'PARENTNETPROFIT': 'net_profit',
    'TOTALOPERATEREVETZ': 'revenue_yoy',
    'PARENTNETPROFITTZ': 'net_profit_yoy',
    'ROEJQ': 'roe',
    'ZZCJLL': 'roa',
    'XSMLL': 'gross_margin',
    'XSJLL': 'net_profit_margin',
    'ZCFZL': 'asset_liability_ratio',
    'LD': 'current_ratio',
    'SD': 'quick_ratio',
    'TOAZZL': 'total_asset_turnover',
    'CHZZL': 'inventory_turnover',
    'YSZKZZL': 'receivable_turnover',
}

# 数据库表中所有业务字段（用于 upsert）
_DB_FIELDS = [
    'code', 'report_date', 'report_name', 'eps', 'bps', 'ocfps',
    'revenue', 'net_profit', 'revenue_yoy', 'net_profit_yoy',
    'roe', 'roa', 'gross_margin', 'net_profit_margin',
    'asset_liability_ratio', 'current_ratio', 'quick_ratio',
    'total_asset_turnover', 'inventory_turnover', 'receivable_turnover',
    'rd_expense', 'admin_expense', 'selling_expense', 'financial_expense',
    'rd_ratio',
]

# 仅 EM 来源字段（不含费用列，避免 upsert 覆盖已有费用数据）
_EM_DB_FIELDS = [
    'code', 'report_date', 'report_name', 'eps', 'bps', 'ocfps',
    'revenue', 'net_profit', 'revenue_yoy', 'net_profit_yoy',
    'roe', 'roa', 'gross_margin', 'net_profit_margin',
    'asset_liability_ratio', 'current_ratio', 'quick_ratio',
    'total_asset_turnover', 'inventory_turnover', 'receivable_turnover',
]

_NUMERIC_FIELDS = set(_DB_FIELDS) - {'code', 'report_date', 'report_name'}


def _code_to_secucode(code):
    """将6位股票代码转为东方财富格式（如 000001 → 000001.SZ）"""
    code = str(code).zfill(6)
    if code.startswith(('6', '5')):
        return f"{code}.SH"
    elif code.startswith(('0', '3', '2')):
        return f"{code}.SZ"
    elif code.startswith(('4', '8', '9')):
        return f"{code}.BJ"
    return f"{code}.SZ"


def _parse_cn_amount(val) -> float | None:
    """解析中文金额字符串（如 '5931.07万', '18.54亿', '-1.16亿'）为浮点数（单位：元）。

    Returns:
        float (单位：元) 或 None（无法解析时）
    """
    if val is None or (isinstance(val, float) and val != val):
        return None
    s = str(val).strip()
    if not s or s == '--' or s == '-' or s.lower() == 'nan':
        return None
    try:
        if s.endswith('亿'):
            return float(s[:-1]) * 1e8
        elif s.endswith('万'):
            return float(s[:-1]) * 1e4
        else:
            # 尝试直接解析为数字
            result = float(s)
            # 防止 float('nan') / float('inf') 通过
            if result != result or result == float('inf') or result == float('-inf'):
                return None
            return result
    except (ValueError, TypeError):
        return None


def _ckpt_path(phase):
    """断点文件路径（按阶段区分：em / expense）。"""
    return os.path.join(_CKPT_DIR, f'financial_ckpt_{phase}.json')


def _load_checkpoint(phase, signature):
    """加载断点。

    Returns:
        tuple(set, dict): (已处理代码集合, 累计统计)。签名不匹配/损坏/禁用时返回空。
    """
    if not CKPT_ENABLED:
        return set(), {}
    p = _ckpt_path(phase)
    try:
        if not os.path.exists(p):
            return set(), {}
        with open(p, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if data.get('signature') != signature:
            log.info(f"[{phase}] 断点签名与本次任务不一致（参数或股票数已变），忽略旧断点，从头开始")
            return set(), {}
        done = set(data.get('done', []))
        stats = data.get('stats', {}) or {}
        if done:
            log.info(f"[{phase}] 命中断点：已处理 {len(done)} 只（{data.get('updated_at', '?')}），续跑剩余股票")
        return done, stats
    except Exception as e:
        log.warning(f"[{phase}] 读取断点失败，将从头开始: {e}")
        return set(), {}


def _save_checkpoint(phase, signature, done_codes, stats):
    """原子写入断点（写临时文件后 rename，避免写一半被中断导致损坏）。"""
    if not CKPT_ENABLED:
        return
    p = _ckpt_path(phase)
    tmp = p + '.tmp'
    try:
        os.makedirs(_CKPT_DIR, exist_ok=True)
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({
                'signature': signature,
                'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'done': sorted(done_codes),
                'stats': stats,
            }, f, ensure_ascii=False)
        os.replace(tmp, p)
    except Exception as e:
        log.warning(f"[{phase}] 写断点失败（忽略，继续运行）: {e}")


def _clear_checkpoint(phase):
    """任务正常跑完后清理断点文件。"""
    if not CKPT_ENABLED:
        return
    p = _ckpt_path(phase)
    try:
        if os.path.exists(p):
            os.remove(p)
    except Exception as e:
        log.warning(f"[{phase}] 清理断点失败（忽略）: {e}")


def _retry_call(fn, name="", retries=RETRY_TIMES, sleep=RETRY_SLEEP):
    """带重试的函数调用"""
    for i in range(retries + 1):
        try:
            return fn()
        except Exception as e:
            if i < retries:
                log.debug(f"{name} 第{i+1}次失败，{sleep}秒后重试: {e}")
                time.sleep(sleep)
            else:
                raise


def _is_retryable_db_error(e):
    """判断数据库异常是否可重试（网络抖动/连接丢失/死锁等）。"""
    try:
        checker = getattr(mdb, '_is_retryable_error', None)
        if callable(checker) and checker(e):
            return True
    except Exception:
        pass

    s = str(e).lower()
    retry_signals = (
        'lost connection', 'gone away', "can't connect", 'connection refused',
        'timed out', 'timeout', 'deadlock', 'lock wait timeout', 'server has gone',
        'packet sequence', 'read of closed file', 'broken pipe', '(2003,', '(2013,'
    )
    return any(sig in s for sig in retry_signals)


def _execute_upsert_with_retry(sql, rows, label='upsert'):
    """执行 upsert，遇到可重试数据库异常时重试并重建连接池。"""
    last_err = None
    for attempt in range(DB_RETRY_TIMES + 1):
        try:
            eng = mdb.engine()
            with eng.connect() as conn:
                conn.execute(sql, rows)
                conn.commit()
            return
        except Exception as e:
            last_err = e
            retryable = _is_retryable_db_error(e)
            if retryable and attempt < DB_RETRY_TIMES:
                wait_s = DB_RETRY_SLEEP * (attempt + 1)
                log.warning(
                    f"{label} 数据库连接瞬态异常，准备重试 {attempt + 1}/{DB_RETRY_TIMES}，"
                    f"{wait_s}s后继续: {e}"
                )
                try:
                    # 丢弃旧连接池，强制下次拿新连接
                    mdb.engine().dispose()
                except Exception:
                    pass
                time.sleep(wait_s)
                continue
            raise

    if last_err is not None:
        raise last_err


def _ak_proxied(fn):
    """通过代理池执行一次 akshare 调用，降低东方财富/同花顺限流风险。

    akshare 的财务接口内部用裸 requests.get（HTTPS），不读取 ak.set_proxies，
    但 requests 默认 trust_env=True，会读取环境变量 HTTP(S)_PROXY。
    因此这里临时设置环境变量代理，调用结束后恢复。

    - 从代理池取一个支持 HTTPS 隧道的代理（无可用则直连）；
    - 调用成功/失败分别上报 report_success / report_failure，供代理池择优；
    - 异常向上抛出，交由 _retry_call 重试（每次重试会换新代理）。

    注意：环境变量代理是进程级、非线程安全的。本采集任务为独立单进程、
    单只股票串行执行，故安全；勿在多线程并发抓取中复用本函数。
    """
    try:
        from quantia.core.singleton_proxy import proxys
    except Exception:
        return fn()

    pool = proxys()
    proxy_url = pool.get_https_proxy()
    if not proxy_url:
        return fn()  # 无 HTTPS 代理可用 → 直连

    _saved = {k: os.environ.get(k) for k in
              ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy")}
    try:
        for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            os.environ[k] = proxy_url
        result = fn()
        pool.report_success(proxy_url)
        return result
    except Exception:
        pool.report_failure(proxy_url)
        raise
    finally:
        for k, v in _saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _clean_nan(rows):
    """将 dict 列表中的 float('nan') 替换为 None（MySQL 不接受 NaN）"""
    cleaned = []
    for r in rows:
        cleaned.append({k: (None if (isinstance(v, float) and v != v) else v)
                        for k, v in r.items()})
    return cleaned


def create_financial_table():
    """创建 cn_stock_financial 表（幂等）"""
    table_name = TABLE_CN_STOCK_FINANCIAL['name']
    if mdb.checkTableIsExist(table_name):
        # 表已存在，尝试添加新列（幂等）
        _alter_add_expense_columns()
        return

    import pymysql
    ddl = """
    CREATE TABLE IF NOT EXISTS `cn_stock_financial` (
        `code`                   VARCHAR(6)    NOT NULL COMMENT '股票代码',
        `report_date`            DATE          NOT NULL COMMENT '报告期',
        `report_name`            VARCHAR(20)   COMMENT '报告期名称',
        `eps`                    FLOAT         COMMENT '基本每股收益(元)',
        `bps`                    FLOAT         COMMENT '每股净资产(元)',
        `ocfps`                  FLOAT         COMMENT '每股经营现金流(元)',
        `revenue`                FLOAT         COMMENT '营业总收入(元)',
        `net_profit`             FLOAT         COMMENT '归母净利润(元)',
        `revenue_yoy`            FLOAT         COMMENT '营收同比增长',
        `net_profit_yoy`         FLOAT         COMMENT '净利润同比增长',
        `roe`                    FLOAT         COMMENT 'ROE净资产收益率',
        `roa`                    FLOAT         COMMENT '总资产净利率',
        `gross_margin`           FLOAT         COMMENT '毛利率',
        `net_profit_margin`      FLOAT         COMMENT '净利率',
        `asset_liability_ratio`  FLOAT         COMMENT '资产负债率',
        `current_ratio`          FLOAT         COMMENT '流动比率',
        `quick_ratio`            FLOAT         COMMENT '速动比率',
        `total_asset_turnover`   FLOAT         COMMENT '总资产周转率(次)',
        `inventory_turnover`     FLOAT         COMMENT '存货周转率(次)',
        `receivable_turnover`    FLOAT         COMMENT '应收账款周转率(次)',
        `rd_expense`             FLOAT         COMMENT '研发费用(元)',
        `admin_expense`          FLOAT         COMMENT '管理费用(元)',
        `selling_expense`        FLOAT         COMMENT '销售费用(元)',
        `financial_expense`      FLOAT         COMMENT '财务费用(元)',
        `rd_ratio`               FLOAT         COMMENT '研发占营收比',
        `updated_at`             DATETIME      DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (`code`, `report_date`),
        INDEX `idx_report_date` (`report_date`),
        INDEX `idx_code` (`code`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
      COMMENT='个股财务分析指标-东方财富(回测用)';
    """
    with pymysql.connect(**mdb.MYSQL_CONN_DBAPI) as conn:
        with conn.cursor() as db:
            db.execute(ddl)
    log.info(f"创建 {table_name} 表完成")


def _alter_add_expense_columns():
    """为已有表添加费用相关列（幂等，先检查列是否存在再 ALTER）"""
    new_cols = [
        ("rd_expense", "FLOAT COMMENT '研发费用(元)'"),
        ("admin_expense", "FLOAT COMMENT '管理费用(元)'"),
        ("selling_expense", "FLOAT COMMENT '销售费用(元)'"),
        ("financial_expense", "FLOAT COMMENT '财务费用(元)'"),
        ("rd_ratio", "FLOAT COMMENT '研发占营收比'"),
    ]
    import pymysql
    with pymysql.connect(**mdb.MYSQL_CONN_DBAPI) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'cn_stock_financial'"
            )
            existing = {row[0] for row in cur.fetchall()}
        for col_name, col_def in new_cols:
            if col_name in existing:
                continue
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        f"ALTER TABLE `cn_stock_financial` ADD COLUMN `{col_name}` {col_def}"
                    )
                log.info(f"添加列 {col_name} 成功")
            except Exception as e:
                if 'Duplicate column' not in str(e):
                    log.debug(f"添加列 {col_name} 跳过: {e}")


def _upsert_batch(rows):
    """批量 upsert 财务数据到 cn_stock_financial（仅 EM 来源字段，不覆盖费用列）"""
    if not rows:
        return
    from sqlalchemy import text as sa_text

    defaults = {f: None for f in _EM_DB_FIELDS}
    rows = [{**defaults, **{k: v for k, v in r.items() if k in _EM_DB_FIELDS}} for r in rows]

    placeholders = ", ".join([f":{f}" for f in _EM_DB_FIELDS])
    updates = ", ".join([f"`{f}`=VALUES(`{f}`)" for f in _EM_DB_FIELDS
                         if f not in ('code', 'report_date')])
    sql = sa_text(f"""
        INSERT INTO `cn_stock_financial` ({', '.join([f'`{f}`' for f in _EM_DB_FIELDS])})
        VALUES ({placeholders})
        ON DUPLICATE KEY UPDATE {updates}, `updated_at`=CURRENT_TIMESTAMP
    """)
    try:
        _execute_upsert_with_retry(sql, rows, label='EM财务upsert')
    except Exception as e:
        log.error(f"批量写入财务数据失败: {e}")
        raise


def get_stock_list():
    """从数据库 cn_stock_spot 获取最新的A股股票列表"""
    try:
        rows = mdb.executeSqlFetch(
            "SELECT DISTINCT `code` FROM `cn_stock_spot` "
            "WHERE `date` = (SELECT MAX(`date`) FROM `cn_stock_spot`) "
            "AND `code` REGEXP '^[036]' "
            "ORDER BY `code`"
        )
        if rows:
            codes = [r[0] for r in rows]
            log.info(f"从数据库获取到 {len(codes)} 只A股代码")
            return codes
    except Exception as e:
        log.warning(f"从数据库获取股票列表失败: {e}")

    # 降级：通过 AKShare 获取
    log.info("降级：通过 AKShare 获取股票列表...")
    try:
        df = ak.stock_info_a_code_name()
        codes = df.iloc[:, 0].astype(str).str.zfill(6).tolist()
        # 仅保留 A 股主板+创业板+中小板
        codes = [c for c in codes if c[0] in ('0', '3', '6')]
        log.info(f"从 AKShare 获取到 {len(codes)} 只A股代码")
        return codes
    except Exception as e:
        log.error(f"获取股票列表失败: {e}")
        return []


def _latest_expected_report_date(today=None):
    """按A股法定披露截止日，返回'此刻应已披露'的最近报告期（保守取值，宁可多抓不漏抓）。

    披露截止：年报(12/31)与一季报(3/31) -> 4/30；半年报(6/30) -> 8/31；三季报(9/30) -> 10/31。
    采用月份粒度并在截止月之后才推进目标，避免在披露窗口内误判已追平。
    """
    from datetime import date as _date
    d = today or _date.today()
    y, m = d.year, d.month
    if m <= 4:        # 1-4月：上年三季报已确定披露（年报/一季报尚在披露期）
        return _date(y - 1, 9, 30)
    elif m <= 8:      # 5-8月：年报+一季报已披露
        return _date(y, 3, 31)
    elif m <= 10:     # 9-10月：半年报已披露
        return _date(y, 6, 30)
    else:             # 11-12月：三季报已披露
        return _date(y, 9, 30)


def _get_caught_up_codes(field='revenue'):
    """返回'最新报告期已达应披露期且 field 非空'的股票集合。

    增量模式据此按整只股票跳过 API 调用，避免重复抓取已是最新且字段完整的股票。
    判据取「每只股票的最新报告期」本身：最新期 < 应披露期、或最新期 field 为空者
    均不纳入（会被照常采集），从而既不漏抓新披露/修订，又能自愈历史 NULL。

    field 为内部常量（白名单校验），非外部输入。
    """
    if field not in ('revenue', 'rd_expense'):
        raise ValueError(f"unsupported field: {field}")
    target = _latest_expected_report_date()
    table = TABLE_CN_STOCK_FINANCIAL['name']
    if not mdb.checkTableIsExist(table):
        return set()
    try:
        rows = mdb.executeSqlFetch(
            f"SELECT t.`code` FROM "
            f"(SELECT `code`, MAX(`report_date`) md FROM `{table}` GROUP BY `code`) t "
            f"JOIN `{table}` f ON f.`code` = t.`code` AND f.`report_date` = t.md "
            f"WHERE t.md >= %s AND f.`{field}` IS NOT NULL",
            (target,)
        )
        return {r[0] for r in rows} if rows else set()
    except Exception as e:
        log.warning(f"查询已追平股票集合失败，将全量采集: {e}")
        return set()


def fetch_single_stock(code, min_date=None):
    """采集单只股票的财务数据（总是 upsert 全部报告期，回填历史 NULL 并捕获修订）。

    增量模式的跳过在 fetch_all_stocks 层按"整只股票"进行（详见 _get_caught_up_codes）。

    Args:
        code: 6位股票代码
        min_date: 最早报告期日期（date对象），早于此日期的记录将被过滤

    Returns:
        int: 入库记录数，-1 表示失败
    """
    secucode = _code_to_secucode(code)
    try:
        df = _retry_call(
            lambda: _ak_proxied(
                lambda: ak.stock_financial_analysis_indicator_em(
                    symbol=secucode, indicator="按报告期")),
            name=f"em_{secucode}"
        )
        if df is None or df.empty:
            return 0
    except Exception as e:
        log.debug(f"[{code}] 财务数据获取失败: {e}")
        return -1

    # 仅保留需要的列
    available_cols = {k: v for k, v in _EM_COL_MAP.items() if k in df.columns}
    df = df[list(available_cols.keys())].copy()
    df = df.rename(columns=available_cols)

    # 处理报告期日期
    if 'report_date' in df.columns:
        df['report_date'] = pd.to_datetime(df['report_date'], errors='coerce').dt.date
        df = df.dropna(subset=['report_date'])

    if df.empty:
        return 0

    # 按年份过滤
    if min_date is not None:
        df = df[df['report_date'] >= min_date]
        if df.empty:
            return 0

    # 补充代码字段
    df['code'] = code

    # 数值字段处理
    for c in df.columns:
        if c in _NUMERIC_FIELDS:
            df[c] = pd.to_numeric(df[c], errors='coerce')

    # 注：增量跳过在 fetch_all_stocks 层按"整只股票"进行（省去 API 调用）。
    # 单只采集时总是 upsert 全部报告期，以回填历史 NULL 核心字段并捕获财报修订。
    rows = _clean_nan(df.to_dict(orient='records'))
    try:
        _upsert_batch(rows)
    except Exception as e:
        # 单只股票入库失败不应中断全量任务
        log.warning(f"[{code}] 财务数据入库失败，已记失败并继续: {e}")
        return -1
    return len(rows)


def fetch_expense_data(code, min_date=None):
    """从同花顺利润表获取费用明细（研发/管理/销售/财务费用），更新到 cn_stock_financial。

    Args:
        code: 6位股票代码
        min_date: 最早报告期日期

    Returns:
        int: 更新记录数，-1 表示失败
    """
    try:
        df = _retry_call(
            lambda: _ak_proxied(
                lambda: ak.stock_financial_benefit_ths(symbol=code, indicator="按报告期")),
            name=f"ths_benefit_{code}"
        )
        if df is None or df.empty:
            return 0
    except Exception as e:
        log.debug(f"[{code}] THS利润表获取失败: {e}")
        return -1

    # 解析报告期
    if '报告期' not in df.columns:
        return 0
    df['report_date'] = pd.to_datetime(df['报告期'], errors='coerce').dt.date
    df = df.dropna(subset=['report_date'])

    if df.empty:
        return 0

    # 按年份过滤
    if min_date is not None:
        df = df[df['report_date'] >= min_date]
        if df.empty:
            return 0

    # 解析费用字段（中文金额 → 元）
    rows = []
    for _, row in df.iterrows():
        rd = _parse_cn_amount(row.get('研发费用'))
        admin = _parse_cn_amount(row.get('管理费用'))
        selling = _parse_cn_amount(row.get('销售费用'))
        financial = _parse_cn_amount(row.get('财务费用'))
        revenue = _parse_cn_amount(row.get('*营业总收入'))

        # 计算研发占营收比
        rd_ratio = None
        if rd is not None and revenue and revenue > 0:
            rd_ratio = round(rd / revenue * 100, 4)

        rows.append({
            'code': code,
            'report_date': row['report_date'],
            'rd_expense': rd,
            'admin_expense': admin,
            'selling_expense': selling,
            'financial_expense': financial,
            'rd_ratio': rd_ratio,
        })

    if not rows:
        return 0

    # 批量更新费用字段（UPDATE 已有行，INSERT 新行时仅填费用）
    try:
        _upsert_expense_batch(rows)
    except Exception as e:
        # 单只股票入库失败不应中断全量任务
        log.warning(f"[{code}] 费用明细入库失败，已记失败并继续: {e}")
        return -1
    return len(rows)


def _upsert_expense_batch(rows):
    """批量 upsert 费用数据到 cn_stock_financial（仅更新费用列）"""
    if not rows:
        return
    from sqlalchemy import text as sa_text

    expense_fields = ['code', 'report_date', 'rd_expense', 'admin_expense',
                      'selling_expense', 'financial_expense', 'rd_ratio']
    placeholders = ", ".join([f":{f}" for f in expense_fields])
    updates = ", ".join([
        f"`{f}`=VALUES(`{f}`)" for f in expense_fields if f not in ('code', 'report_date')
    ])
    sql = sa_text(f"""
        INSERT INTO `cn_stock_financial` ({', '.join([f'`{f}`' for f in expense_fields])})
        VALUES ({placeholders})
        ON DUPLICATE KEY UPDATE {updates}, `updated_at`=CURRENT_TIMESTAMP
    """)
    clean_rows = _clean_nan(rows)
    # 确保每行有所有字段
    defaults = {f: None for f in expense_fields}
    clean_rows = [{**defaults, **{k: v for k, v in r.items() if k in expense_fields}}
                  for r in clean_rows]
    try:
        _execute_upsert_with_retry(sql, clean_rows, label='THS费用upsert')
    except Exception as e:
        log.error(f"批量写入费用数据失败: {e}")
        raise


def fetch_all_expenses(stock_codes, min_date=None, incremental=False):
    """批量采集所有股票的费用明细数据（THS利润表）

    增量模式：跳过"已追平至最近应披露报告期且研发费用非空"的股票（不发 API）。

    Returns:
        tuple: (成功数, 失败数, 跳过数, 更新总行数)
    """
    total = len(stock_codes)
    success, fail, skip, total_rows = 0, 0, 0, 0

    caught_up = _get_caught_up_codes('rd_expense') if incremental else set()
    suffix = (f"（增量：已追平 {len(caught_up)} 只至 {_latest_expected_report_date()}，将跳过）"
              if incremental else "")
    log.info(f"开始采集费用明细数据（THS利润表），共 {total} 只股票{suffix}")

    signature = f"expense|inc={incremental}|min={min_date}|n={total}"
    done_codes, _stats = _load_checkpoint('expense', signature)
    success = _stats.get('success', 0)
    skip = _stats.get('skip', 0)
    total_rows = _stats.get('total_rows', 0)

    consecutive_fail = 0
    aborted = False
    since_save = 0
    for i, code in enumerate(stock_codes):
        done = i + 1
        if code in done_codes:
            continue
        if incremental and code in caught_up:
            skip += 1
            done_codes.add(code)
            if done % 100 == 0 or done == total:
                log.info(f"费用采集进度: {done}/{total} "
                         f"(成功={success}, 跳过={skip}, 失败={fail}, 更新={total_rows}行)")
            continue

        result = fetch_expense_data(code, min_date=min_date)
        if result < 0:
            fail += 1
            consecutive_fail += 1
        else:
            consecutive_fail = 0
            done_codes.add(code)
            if result == 0:
                skip += 1
            else:
                success += 1
                total_rows += result

        since_save += 1
        if since_save >= CKPT_SAVE_EVERY:
            _save_checkpoint('expense', signature, done_codes,
                             {'success': success, 'skip': skip, 'total_rows': total_rows})
            since_save = 0

        if done % 100 == 0 or done == total:
            log.info(f"费用采集进度: {done}/{total} "
                     f"(成功={success}, 跳过={skip}, 失败={fail}, 更新={total_rows}行)")

        if MAX_CONSECUTIVE_FAILS > 0 and consecutive_fail >= MAX_CONSECUTIVE_FAILS:
            log.error(f"费用采集连续失败 {consecutive_fail} 只，疑似系统性故障（DB/网络），中止本次任务")
            aborted = True
            break

        time.sleep(SLEEP_PER_STOCK)

    if aborted:
        _save_checkpoint('expense', signature, done_codes,
                         {'success': success, 'skip': skip, 'total_rows': total_rows})
        log.warning(f"费用采集已中止，断点已落盘（已处理 {len(done_codes)} 只），重跑同一命令可续跑")
    else:
        _clear_checkpoint('expense')

    log.info(f"费用数据采集完成: 成功={success}, 跳过={skip}, 失败={fail}, "
             f"更新={total_rows}行")
    return success, fail, skip, total_rows


def fetch_all_stocks(stock_codes, incremental=False, min_date=None):
    """批量采集所有股票的财务数据

    增量模式：仅跳过"已追平至最近应披露报告期且核心字段(营收)非空"的股票（不发 API），
    其余股票照常采集；被采集的股票一律 upsert 全部报告期（回填历史 NULL、捕获修订）。

    Returns:
        tuple: (成功数, 失败数, 跳过数, 入库总行数)
    """
    total = len(stock_codes)
    success, fail, skip, total_rows = 0, 0, 0, 0

    caught_up = _get_caught_up_codes('revenue') if incremental else set()
    if incremental:
        mode = f'增量模式(已追平 {len(caught_up)} 只至 {_latest_expected_report_date()}，将跳过)'
    else:
        mode = '全量模式' if min_date is None else f'近{min_date}起'
    log.info(f"开始采集财务数据，共 {total} 只股票（{mode}）")

    signature = f"em|inc={incremental}|min={min_date}|n={total}"
    done_codes, _stats = _load_checkpoint('em', signature)
    success = _stats.get('success', 0)
    skip = _stats.get('skip', 0)
    total_rows = _stats.get('total_rows', 0)

    consecutive_fail = 0
    aborted = False
    since_save = 0
    for i, code in enumerate(stock_codes):
        done = i + 1
        if code in done_codes:
            continue
        # 整只跳过：已追平的股票不再发起 API 请求（也不 sleep）
        if incremental and code in caught_up:
            skip += 1
            done_codes.add(code)
            if done % 100 == 0 or done == total:
                log.info(f"采集进度: {done}/{total} "
                         f"(成功={success}, 跳过={skip}, 失败={fail}, 入库={total_rows}行)")
            continue

        result = fetch_single_stock(code, min_date=min_date)
        if result < 0:
            fail += 1
            consecutive_fail += 1
        else:
            consecutive_fail = 0
            done_codes.add(code)
            if result == 0:
                skip += 1
            else:
                success += 1
                total_rows += result

        since_save += 1
        if since_save >= CKPT_SAVE_EVERY:
            _save_checkpoint('em', signature, done_codes,
                             {'success': success, 'skip': skip, 'total_rows': total_rows})
            since_save = 0

        # 进度日志
        if done % 100 == 0 or done == total:
            log.info(f"采集进度: {done}/{total} "
                     f"(成功={success}, 跳过={skip}, 失败={fail}, 入库={total_rows}行)")

        if MAX_CONSECUTIVE_FAILS > 0 and consecutive_fail >= MAX_CONSECUTIVE_FAILS:
            log.error(f"财务采集连续失败 {consecutive_fail} 只，疑似系统性故障（DB/网络），中止本次任务")
            aborted = True
            break

        # 每次API调用后休眠（已发起请求）
        time.sleep(SLEEP_PER_STOCK)

    if aborted:
        _save_checkpoint('em', signature, done_codes,
                         {'success': success, 'skip': skip, 'total_rows': total_rows})
        log.warning(f"财务采集已中止，断点已落盘（已处理 {len(done_codes)} 只），重跑同一命令可续跑")
    else:
        _clear_checkpoint('em')

    log.info(f"财务数据采集完成: 成功={success}, 跳过={skip}, 失败={fail}, "
             f"入库={total_rows}行")
    return success, fail, skip, total_rows


def get_financial_data(code, report_date=None):
    """查询指定股票的财务数据（供回测使用）

    Args:
        code: 股票代码
        report_date: 报告期截止日期（返回该日期及之前的最新数据）

    Returns:
        dict or None: 财务数据字典
    """
    if report_date:
        sql = ("SELECT * FROM `cn_stock_financial` "
               "WHERE `code` = %s AND `report_date` <= %s "
               "ORDER BY `report_date` DESC LIMIT 1")
        params = (code, report_date)
    else:
        sql = ("SELECT * FROM `cn_stock_financial` "
               "WHERE `code` = %s "
               "ORDER BY `report_date` DESC LIMIT 1")
        params = (code,)

    try:
        with mdb.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                row = cur.fetchone()
                if not row:
                    return None
                col_names = [desc[0] for desc in cur.description]
                return dict(zip(col_names, row))
    except Exception as e:
        log.error(f"查询财务数据失败[{code}]: {e}")
        return None


def get_financial_data_batch(codes, report_date=None):
    """批量查询多只股票的最新财务数据（供回测使用）

    Args:
        codes: 股票代码列表
        report_date: 报告期截止日期

    Returns:
        dict: {code: {field: value, ...}, ...}
    """
    if not codes:
        return {}

    table_name = TABLE_CN_STOCK_FINANCIAL['name']
    if not mdb.checkTableIsExist(table_name):
        return {}

    placeholders = ','.join(['%s'] * len(codes))
    if report_date:
        sql = f"""
            SELECT f.* FROM `cn_stock_financial` f
            INNER JOIN (
                SELECT `code`, MAX(`report_date`) as max_date
                FROM `cn_stock_financial`
                WHERE `code` IN ({placeholders}) AND `report_date` <= %s
                GROUP BY `code`
            ) latest ON f.`code` = latest.`code` AND f.`report_date` = latest.max_date
        """
        params = tuple(codes) + (report_date,)
    else:
        sql = f"""
            SELECT f.* FROM `cn_stock_financial` f
            INNER JOIN (
                SELECT `code`, MAX(`report_date`) as max_date
                FROM `cn_stock_financial`
                WHERE `code` IN ({placeholders})
                GROUP BY `code`
            ) latest ON f.`code` = latest.`code` AND f.`report_date` = latest.max_date
        """
        params = tuple(codes)

    try:
        with mdb.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
                if not rows:
                    return {}
                col_names = [desc[0] for desc in cur.description]

        result = {}
        for row in rows:
            d = dict(zip(col_names, row))
            result[d['code']] = d
        return result
    except Exception as e:
        log.error(f"批量查询财务数据失败: {e}")
        return {}


def main():
    parser = argparse.ArgumentParser(description="A股历史财务数据采集（项目集成版）")
    parser.add_argument("--test", type=int, default=0,
                        help="测试模式：仅采集前N只股票")
    parser.add_argument("--incremental", action="store_true",
                        help="增量模式：跳过最新报告期已达应披露期且字段非空的股票（不发API）")
    parser.add_argument("--years", type=int, default=0,
                        help="仅采集最近N年的数据（0=不限制）")
    parser.add_argument("--expenses", action="store_true",
                        help="同时采集费用明细（研发/管理/销售/财务费用，来源: THS利润表）")
    parser.add_argument("--expenses-only", action="store_true",
                        help="仅采集费用明细，跳过基础财务指标")
    args = parser.parse_args()

    # 计算日期过滤
    from datetime import date as _date
    min_date = None
    if args.years > 0:
        min_date = _date(datetime.now().year - args.years, 1, 1)

    log.info("=" * 60)
    log.info("A股财务数据采集开始")
    log.info(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if args.test:
        log.info(f"[测试模式] 仅采集前 {args.test} 只股票")
    if args.incremental:
        log.info("[增量模式] 仅采集新报告期数据")
    if min_date:
        log.info(f"[年份过滤] 仅保留 {min_date} 之后的报告期")
    if args.expenses or args.expenses_only:
        log.info("[费用明细] 将采集研发/管理/销售/财务费用（THS利润表）")
    log.info("=" * 60)

    # 1. 建表（含新列迁移）
    create_financial_table()

    # 2. 获取股票列表
    stock_codes = get_stock_list()
    if not stock_codes:
        log.error("无法获取股票列表，退出")
        return

    if args.test:
        stock_codes = stock_codes[:args.test]

    # 3. 采集基础财务指标（EM）
    if not args.expenses_only:
        success, fail, skip, total_rows = fetch_all_stocks(
            stock_codes, incremental=args.incremental, min_date=min_date)

        log.info("=" * 60)
        log.info("基础财务指标采集完成:")
        log.info(f"  股票数: {len(stock_codes)}")
        log.info(f"  成功: {success}, 失败: {fail}, 跳过: {skip}")
        log.info(f"  入库总行数: {total_rows}")
        log.info("=" * 60)

    # 4. 采集费用明细（THS利润表）
    if args.expenses or args.expenses_only:
        e_success, e_fail, e_skip, e_rows = fetch_all_expenses(
            stock_codes, min_date=min_date, incremental=args.incremental)

        log.info("=" * 60)
        log.info("费用明细采集完成:")
        log.info(f"  股票数: {len(stock_codes)}")
        log.info(f"  成功: {e_success}, 失败: {e_fail}, 跳过: {e_skip}")
        log.info(f"  更新总行数: {e_rows}")
        log.info("=" * 60)

    log.info(f"结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(
                os.path.join(os.path.dirname(__file__), '..', 'log', 'stock_financial_data.log'),
                encoding='utf-8'
            ),
        ],
    )
    main()
