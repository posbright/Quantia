#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import gc
import os.path
import datetime
import numpy as np
import pandas as pd
import talib as tl
import concurrent.futures
import quantia.core.tablestructure as tbs
import quantia.lib.trade_time as trd
import quantia.core.crawling.trade_date_hist as tdh
import quantia.core.crawling.fund_etf_em as fee
import quantia.core.crawling.fund_em as fem  # 场外开放式基金（净值型+货币型）
import quantia.core.crawling.stock_index_em as sie  # 指数行情
import quantia.core.crawling.stock_selection as sst
import quantia.core.crawling.stock_lhb_em as sle
import quantia.core.crawling.stock_lhb_sina as sls
import quantia.core.crawling.stock_dzjy_em as sde
import quantia.core.crawling.stock_hist_em as she
import quantia.core.crawling.stock_fund_em as sff
import quantia.core.crawling.stock_fhps_em as sfe
import quantia.core.crawling.stock_chip_race as scr
import quantia.core.crawling.stock_limitup_reason as slr
import quantia.core.crawling.stock_tencent as stc  # 腾讯财经备选
import quantia.core.crawling.stock_sina as ssa  # 新浪财经备选
import quantia.core.crawling.etf_tencent as etc  # ETF腾讯财经备选
import quantia.core.crawling.etf_sina as esa  # ETF新浪财经备选
import quantia.core.crawling.index_tencent as itc  # 指数腾讯财经备选
import quantia.core.crawling.index_sina as isa  # 指数新浪财经备选
import quantia.core.crawling.stock_fund_sina as sfs  # 新浪财经资金流向
import quantia.core.crawling.stock_hist_sina as shs  # 新浪财经历史K线
import quantia.core.crawling.stock_hist_tencent as sht  # 腾讯财经历史K线
import time
import random
import threading

__author__ = 'Quantia'

import quantia.lib.envconfig as _cfg

# 数据源重试配置
DATA_SOURCE_MAX_RETRIES = _cfg.get_int('DATA_SOURCE_MAX_RETRIES', 2)          # 单个数据源最大重试次数
DATA_SOURCE_RETRY_INTERVAL = _cfg.get_int('DATA_SOURCE_RETRY_INTERVAL', 90)  # 基础重试间隔（秒）

# 历史数据配置
HIST_DATA_DEFAULT_YEARS = _cfg.get_int('HIST_DATA_DEFAULT_YEARS', 10)   # 默认获取历史数据年数


# ══════════════════════════════════════════════
# 数据源健康度追踪（全局，线程安全）
# ══════════════════════════════════════════════
# 当某个数据源在短时间内连续失败时，将其降级处理：
# - 将该数据源排到列表末尾，优先使用其他数据源
# - 降级持续 SOURCE_COOLDOWN_SECONDS 秒后自动恢复
# 这样可以避免在免费代理不可用时反复尝试东方财富浪费大量时间
_source_health_lock = threading.Lock()
_source_fail_counts = {}       # {"东方财富": 5, "腾讯财经": 0, ...}
_source_cooldown_until = {}    # {"东方财富": timestamp, ...}
_source_degrade_count = {}     # {"东方财富": 3, ...}  累计降级次数（用于渐进退避）
_source_is_degraded = {}       # {"东方财富": True, ...}  是否已处于降级状态（控制日志只输出一次）

SOURCE_FAIL_THRESHOLD = _cfg.get_int('DATA_SOURCE_FAIL_THRESHOLD', 5)            # 连续失败 N 次后降级
SOURCE_COOLDOWN_SECONDS = _cfg.get_int('DATA_SOURCE_COOLDOWN_SECONDS', 300)      # 基础降级冷却时间（秒）
SOURCE_MAX_COOLDOWN_SECONDS = _cfg.get_int('DATA_SOURCE_MAX_COOLDOWN', 3600)     # 最大冷却时间（秒）


def _report_source_failure(source_name):
    """报告数据源失败，累积达到阈值时触发降级

    优化：
    - 仅在首次触发降级时输出 WARNING，后续只累计计数不重复输出
    - 渐进冷却：反复降级的数据源冷却时间翻倍（上限 SOURCE_MAX_COOLDOWN_SECONDS）
    """
    with _source_health_lock:
        _source_fail_counts[source_name] = _source_fail_counts.get(source_name, 0) + 1
        if _source_fail_counts[source_name] >= SOURCE_FAIL_THRESHOLD:
            already_degraded = _source_is_degraded.get(source_name, False)
            if not already_degraded:
                # 首次触发降级（或冷却恢复后再次降级）
                _source_is_degraded[source_name] = True
                degrade_n = _source_degrade_count.get(source_name, 0) + 1
                _source_degrade_count[source_name] = degrade_n
                # 渐进退避：每次降级冷却时间翻倍（300s → 600s → 1200s → ... → 最大3600s）
                cooldown = min(SOURCE_COOLDOWN_SECONDS * (2 ** (degrade_n - 1)), SOURCE_MAX_COOLDOWN_SECONDS)
                cooldown_end = time.time() + cooldown
                _source_cooldown_until[source_name] = cooldown_end
                logging.warning(
                    f"数据源 [{source_name}] 连续失败 {_source_fail_counts[source_name]} 次，"
                    f"降级 {cooldown} 秒（第{degrade_n}次降级，优先使用其他数据源）"
                )
            else:
                # 已处于降级状态，只刷新冷却计时器，不重复输出日志
                degrade_n = _source_degrade_count.get(source_name, 1)
                cooldown = min(SOURCE_COOLDOWN_SECONDS * (2 ** (degrade_n - 1)), SOURCE_MAX_COOLDOWN_SECONDS)
                _source_cooldown_until[source_name] = time.time() + cooldown


def _report_source_success(source_name):
    """报告数据源成功，重置失败计数和冷却状态"""
    with _source_health_lock:
        was_degraded = _source_is_degraded.get(source_name, False)
        old_fail_count = _source_fail_counts.get(source_name, 0)
        _source_fail_counts[source_name] = 0
        _source_cooldown_until.pop(source_name, None)
        _source_is_degraded[source_name] = False
        # 降级恢复且曾失败过 → 输出一条汇总日志
        if was_degraded and old_fail_count > 0:
            _source_degrade_count[source_name] = 0  # 成功后重置渐进退避
            logging.info(f"数据源 [{source_name}] 恢复正常（此前连续失败 {old_fail_count} 次）")


def _is_source_degraded(source_name):
    """检查数据源是否处于降级冷却期"""
    with _source_health_lock:
        cooldown_end = _source_cooldown_until.get(source_name)
        if cooldown_end is None:
            return False
        if time.time() >= cooldown_end:
            # 冷却期已过，自动恢复（但不重置渐进退避计数，需要成功请求才重置）
            _source_cooldown_until.pop(source_name, None)
            _source_fail_counts[source_name] = 0
            _source_is_degraded[source_name] = False
            logging.info(f"数据源 [{source_name}] 冷却期结束，尝试恢复")
            return False
        return True


def _sort_sources_by_health(data_sources):
    """按健康度排序数据源：降级的数据源排到末尾（仍可用，只是降低优先级）"""
    healthy = []
    degraded = []
    for item in data_sources:
        if _is_source_degraded(item[0]):
            degraded.append(item)
        else:
            healthy.append(item)
    return healthy + degraded


def _apply_source_priority(data_sources):
    """按环境变量 QUANTIA_SPOT_SOURCE_PRIORITY 重排实时行情数据源优先级。

    适用场景：当某个数据源在当前服务器长期不可用（如东方财富 push2 接口
    被机房 IP 限流），可通过配置把它降为兜底，避免每次任务都先试先败。

    - 配置为以逗号分隔的数据源名称，例如：腾讯财经,新浪财经,东方财富
    - 仅对在配置中出现的数据源生效；配置中出现、但本次列表里没有的名称忽略；
      未在配置中出现的数据源按原始相对顺序追加到末尾（保证不会丢源）。
    - 未配置或配置为空时，保持调用方传入的原始顺序（行为不变）。
    """
    priority_raw = _cfg.get_str('QUANTIA_SPOT_SOURCE_PRIORITY', '')
    priority = [name.strip() for name in priority_raw.split(',') if name.strip()]
    if not priority:
        return data_sources

    by_name = {item[0]: item for item in data_sources}
    ordered = []
    seen = set()
    for name in priority:
        item = by_name.get(name)
        if item is not None and name not in seen:
            ordered.append(item)
            seen.add(name)
    # 追加未在配置中列出的数据源，保持原始相对顺序
    for item in data_sources:
        if item[0] not in seen:
            ordered.append(item)
            seen.add(item[0])
    return ordered


# ══════════════════════════════════════════════
# 日志聚合（避免重复的代理失败日志刷屏）
# ══════════════════════════════════════════════
_log_agg_lock = threading.Lock()
_log_agg_counts = {}     # {source_name: count}
_log_agg_last_time = {}  # {source_name: timestamp}
_LOG_AGG_INTERVAL = 60   # 每 60 秒输出一次聚合日志


def _log_source_failure_aggregated(source_name, code, error_msg):
    """聚合同一数据源的连续失败日志，避免刷屏

    对于同一数据源，在 _LOG_AGG_INTERVAL 秒内只输出一条 WARNING 日志，
    后续的失败只计数，到达间隔后汇总输出。
    """
    with _log_agg_lock:
        now = time.time()
        last_time = _log_agg_last_time.get(source_name, 0)
        _log_agg_counts[source_name] = _log_agg_counts.get(source_name, 0) + 1

        if now - last_time >= _LOG_AGG_INTERVAL:
            count = _log_agg_counts[source_name]
            if count > 1:
                logging.warning(
                    f"从{source_name}获取数据失败（最近 {_LOG_AGG_INTERVAL}s 内累计 {count} 次）: "
                    f"最新失败 {code} - {error_msg}"
                )
            else:
                logging.warning(f"从{source_name}获取数据失败: {code} - {error_msg}")
            _log_agg_counts[source_name] = 0
            _log_agg_last_time[source_name] = now


def _retry_sleep(retry_count, base_interval=None):
    """
    指数退避重试等待
    第1次重试等待 base_interval 秒，第2次等待 base_interval*2 秒，以此类推
    加入较大的随机抖动避免多线程同步重试（惊群效应）

    抖动范围为 base_interval 的 10%-30%，确保多线程重试时错开足够时间
    """
    if base_interval is None:
        base_interval = DATA_SOURCE_RETRY_INTERVAL
    base_delay = base_interval * (2 ** retry_count)
    jitter = random.uniform(base_delay * 0.1, base_delay * 0.3)
    delay = base_delay + jitter
    logging.info(f"等待{delay:.0f}秒后重试...")
    time.sleep(delay)

__date__ = '2026/02/14'

# 设置基础目录，每次加载使用。
cpath_current = os.path.dirname(os.path.dirname(__file__))
stock_hist_cache_path = os.path.join(cpath_current, 'cache', 'hist')
if not os.path.exists(stock_hist_cache_path):
    os.makedirs(stock_hist_cache_path, exist_ok=True)  # 创建多个文件夹结构。


# 600 601 603 605开头的股票是上证A股
# 600开头的股票是上证A股，属于大盘股，其中6006开头的股票是最早上市的股票，
# 6016开头的股票为大盘蓝筹股；900开头的股票是上证B股；
# 688开头的是上证科创板股票；
# 000开头的股票是深证A股，001、002开头的股票也都属于深证A股，
# 其中002开头的股票是深证A股中小企业股票；
# 200开头的股票是深证B股；
# 300、301开头的股票是创业板股票；400开头的股票是三板市场股票。
# 430、83、87开头的股票是北证A股
def is_a_stock(code):
    # 上证A股  # 深证A股
    return code.startswith(('600', '601', '603', '605', '000', '001', '002', '003', '300', '301'))


# 过滤掉 st 股票。
def is_not_st(name):
    return not name.startswith(('*ST', 'ST'))


# 过滤价格，如果没有基本上是退市了。
def is_open(price):
    return not np.isnan(price)


def is_open_with_line(price):
    return price != '-'


# 读取股票交易日历数据（DB 优先 → Sina API fallback → 回写缓存）
# 数据源优先级：cn_stock_trade_date > cn_stock_spot > Sina API
# 设计原则：数据采集和数据分析分离。交易日历数据一旦入库就很少变动，
# 优先从 DB 读取可避免触发代理池初始化（~11分钟），让 Web 服务器和分析作业
# 不依赖外部 API / 代理即可获得交易日历。
def fetch_stocks_trade_date():
    # 首选：从 cn_stock_trade_date 表读取（最优，专用交易日历表）
    try:
        import quantia.lib.database as mdb
        if mdb.checkTableIsExist('cn_stock_trade_date'):
            import pandas as pd
            sql = "SELECT `trade_date` FROM `cn_stock_trade_date` ORDER BY `trade_date`"
            df = pd.read_sql(sql, con=mdb.engine())
            if df is not None and len(df) > 30:
                dates = set(pd.to_datetime(df['trade_date']).dt.date.tolist())
                # 补充 cn_stock_spot 中比缓存更新的交易日（每天 hdj.main 会写入当日行情）
                # 防止 cn_stock_trade_date 老化导致 is_trade_date(today) 返回 False
                try:
                    max_cached = max(dates)
                    if mdb.checkTableIsExist('cn_stock_spot'):
                        sql2 = "SELECT DISTINCT `date` FROM `cn_stock_spot` WHERE `date` > %s"
                        df2 = pd.read_sql(sql2, con=mdb.engine(), params=(max_cached,))
                        if df2 is not None and len(df2) > 0:
                            new_dates = set(pd.to_datetime(df2['date']).dt.date.tolist())
                            dates.update(new_dates)
                            _persist_trade_dates(new_dates)
                            logging.info(f"fetch_stocks_trade_date: 从 cn_stock_spot 补充 {len(new_dates)} 个新交易日")
                except Exception as e:
                    logging.debug(f"fetch_stocks_trade_date: 补充新交易日异常: {e}")
                logging.info(f"fetch_stocks_trade_date: 从 cn_stock_trade_date 获取 {len(dates)} 个交易日")
                return dates
            else:
                logging.info(f"fetch_stocks_trade_date: cn_stock_trade_date 仅有 {len(df) if df is not None else 0} 条记录，尝试其他数据源")
    except Exception as e:
        logging.warning(f"fetch_stocks_trade_date: cn_stock_trade_date 查询失败: {e}")

    # 次选：从 cn_stock_spot 表提取历史交易日期（零代理、零API）
    try:
        import quantia.lib.database as mdb
        if mdb.checkTableIsExist('cn_stock_spot'):
            import pandas as pd
            sql = "SELECT DISTINCT `date` FROM `cn_stock_spot` ORDER BY `date`"
            df = pd.read_sql(sql, con=mdb.engine())
            if df is not None and len(df) > 0:
                spot_dates = set(pd.to_datetime(df['date']).dt.date.tolist())
                if len(spot_dates) > 30:
                    logging.info(f"fetch_stocks_trade_date: 从 cn_stock_spot 获取 {len(spot_dates)} 个交易日")
                    _persist_trade_dates(spot_dates)
                    return spot_dates
                else:
                    logging.warning(f"fetch_stocks_trade_date: DB仅有{len(spot_dates)}个交易日，数据不足，降级到Sina API")
    except Exception as e:
        logging.warning(f"fetch_stocks_trade_date: DB查询失败: {e}")

    # 降级：Sina API（需要代理，会触发代理池初始化）
    try:
        data = tdh.tool_trade_date_hist_sina()
        if data is not None and len(data.index) > 0:
            data_date = set(data['trade_date'].values.tolist())
            _persist_trade_dates(data_date)
            return data_date
    except Exception as e:
        logging.error(f"stockfetch.fetch_stocks_trade_date处理异常", exc_info=True)

    return None


def _persist_trade_dates(dates):
    """将交易日历数据持久化到 cn_stock_trade_date 表（INSERT IGNORE 去重）"""
    try:
        import quantia.lib.database as mdb
        import pandas as pd

        # 确保表存在
        mdb.executeSql(
            "CREATE TABLE IF NOT EXISTS `cn_stock_trade_date` ("
            "  `trade_date` date NOT NULL,"
            "  PRIMARY KEY (`trade_date`)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci"
        )

        # 转成 DataFrame 写入
        date_list = sorted(dates)
        df = pd.DataFrame({'trade_date': date_list})
        df['trade_date'] = pd.to_datetime(df['trade_date'])

        from sqlalchemy import Date
        mdb.insert_db_from_df(
            df,
            'cn_stock_trade_date',
            cols_type={'trade_date': Date},
            write_index=False,
            primary_keys=['trade_date'],
        )
        logging.info(f"_persist_trade_dates: 已写入/更新 {len(date_list)} 个交易日到 cn_stock_trade_date")
    except Exception as e:
        logging.warning(f"_persist_trade_dates: 持久化交易日历失败（不影响当前查询）: {e}")


# 读取当天ETF数据（支持多数据源自动切换）
# 优先级: 东方财富 -> 腾讯财经 -> 新浪财经
def fetch_etfs(date):
    data = None
    source = None

    # 数据源列表，按优先级排序（东方财富更稳定，作为首选）
    data_sources = [
        ("东方财富", fee.fund_etf_spot_em),
        ("腾讯财经", etc.fund_etf_spot_tencent),
        ("新浪财经", esa.fund_etf_spot_sina),
    ]
    data_sources = _apply_source_priority(data_sources)
    data_sources = _sort_sources_by_health(data_sources)

    for source_name, fetch_func in data_sources:
        try:
            logging.info(f"尝试从{source_name}获取ETF数据...")
            data = fetch_func()
            if data is not None and len(data.index) > 0:
                source = source_name
                _report_source_success(source_name)
                break
        except Exception as e:
            logging.warning(f"{source_name}ETF数据获取失败：{e}，切换下一个数据源")
            _report_source_failure(source_name)
            data = None

    # 所有数据源都失败
    if data is None or len(data.index) == 0:
        logging.error("所有ETF数据源均获取失败")
        return None

    try:
        logging.info(f"成功从{source}获取 {len(data)} 条ETF数据")
        if date is None:
            data.insert(0, 'date', datetime.datetime.now().strftime("%Y-%m-%d"))
        else:
            data.insert(0, 'date', date.strftime("%Y-%m-%d"))
        data.columns = list(tbs.TABLE_CN_ETF_SPOT['columns'])
        data = data.loc[data['new_price'].apply(is_open)]
        return data
    except Exception as e:
        logging.error(f"stockfetch.fetch_etfs处理异常", exc_info=True)
    return None


def fetch_funds(date):
    """场外开放式基金（净值型 + 货币型）每日净值与多周期收益率。

    数据源 akshare 单源（fund_em.fund_rank_all），属 fetch 管道。
    - date 写运行日（入库快照日），nav_date 保留 akshare 披露净值日。
    - 防跨类型桶重复：按 code 去重（keep='first'）。
    - 对齐 TABLE_CN_FUND_RANK 列序，缺失列补 NaN。
    """
    try:
        data = fem.fund_rank_all()
        if data is None or len(data.index) == 0:
            logging.error("所有基金数据源均获取失败")
            return None

        if date is None:
            date_str = datetime.datetime.now().strftime("%Y-%m-%d")
        else:
            date_str = date.strftime("%Y-%m-%d")
        data.insert(0, 'date', date_str)

        # 防跨类型桶重复（同一 code 理论只属一个桶，防御性去重）
        data = data.drop_duplicates(subset=['code'], keep='first')

        # 对齐表列序，缺失的互斥列（净值型无万份收益、货币型无单位净值）补 NaN
        cols = list(tbs.TABLE_CN_FUND_RANK['columns'])
        for col in cols:
            if col not in data.columns:
                data[col] = np.nan
        data = data[cols]
        logging.info(f"成功获取 {len(data)} 条基金数据")
        return data
    except Exception as e:
        logging.error(f"stockfetch.fetch_funds处理异常", exc_info=True)
    return None


# 读取当天指数数据（支持多数据源自动切换）
# 优先级: 东方财富 -> 腾讯财经 -> 新浪财经
def fetch_index_spots(date):
    """
    获取沪深两市全部指数的实时行情数据。
    数据结构与 TABLE_CN_INDEX_SPOT 对齐。

    支持多数据源自动切换：
    - 东方财富（首选）：覆盖最全（~1067个指数），数据最完整
    - 腾讯财经（备选）：覆盖常见指数（~533个），数据较完整
    - 新浪财经（兜底）：覆盖常见指数，缺少换手率和市值数据
    """
    data = None
    source = None

    # 数据源列表，按优先级排序
    data_sources = [
        ("东方财富", sie.stock_index_spot_em),
        ("腾讯财经", itc.index_spot_tencent),
        ("新浪财经", isa.index_spot_sina),
    ]
    data_sources = _apply_source_priority(data_sources)
    data_sources = _sort_sources_by_health(data_sources)

    for source_name, fetch_func in data_sources:
        try:
            logging.info(f"尝试从{source_name}获取指数数据...")
            data = fetch_func()
            if data is not None and len(data.index) > 0:
                source = source_name
                _report_source_success(source_name)
                break
        except Exception as e:
            logging.warning(f"{source_name}指数数据获取失败：{e}，切换下一个数据源")
            _report_source_failure(source_name)
            data = None

    # 所有数据源都失败
    if data is None or len(data.index) == 0:
        logging.error("所有指数数据源均获取失败")
        return None

    try:
        logging.info(f"成功从{source}获取 {len(data)} 条指数数据")
        if date is None:
            data.insert(0, 'date', datetime.datetime.now().strftime("%Y-%m-%d"))
        else:
            data.insert(0, 'date', date.strftime("%Y-%m-%d"))
        data.columns = list(tbs.TABLE_CN_INDEX_SPOT['columns'])
        # 指数不过滤停牌（指数始终有报价）
        return data
    except Exception as e:
        logging.error(f"stockfetch.fetch_index_spots处理异常", exc_info=True)
    return None


def _load_latest_shares_from_db():
    """从 cn_stock_spot 读取每只股票最近一次有效的总股本/流通股本。

    股本属于缓变量（除增发/配股/回购/转增/解禁外长期不变），可用于在
    新浪等不提供股本/市值/换手率的数据源降级时回算这些派生列。

    返回: dict { code: (total_shares, free_shares) }，仅包含 total_shares>0 的记录。
    查询失败时返回空 dict（调用方据此跳过回算）。
    """
    import quantia.lib.database as mdb
    try:
        # 取每只股票最近一个有股本数据的快照日的股本
        rows = mdb.executeSqlFetch(
            "SELECT s.code, s.total_shares, s.free_shares "
            "FROM cn_stock_spot s "
            "INNER JOIN ("
            "  SELECT code, MAX(date) AS max_date FROM cn_stock_spot "
            "  WHERE total_shares > 0 GROUP BY code"
            ") t ON s.code = t.code AND s.date = t.max_date",
            query_timeout_ms=_cfg.get_int('QUANTIA_FUND_DB_QUERY_TIMEOUT_MS', 8000),
        )
    except Exception as e:
        logging.warning(f"读取历史股本失败，跳过新浪市值/换手率回算：{e}")
        return {}

    shares_map = {}
    for row in (rows or []):
        try:
            code = row[0] if not isinstance(row, dict) else row.get('code')
            total_shares = row[1] if not isinstance(row, dict) else row.get('total_shares')
            free_shares = row[2] if not isinstance(row, dict) else row.get('free_shares')
            total_shares = int(total_shares or 0)
            free_shares = int(free_shares or 0)
            if code and total_shares > 0:
                shares_map[str(code)] = (total_shares, free_shares)
        except Exception:
            continue
    return shares_map


def _backfill_shares_derived_columns(data, shares_map):
    """用历史股本回算缺失的总市值/流通市值/换手率（就地修改 data）。

    仅回算当前为 0/缺失的单元格，公式：
    - total_market_cap = round(new_price * total_shares)
    - free_cap         = round(new_price * free_shares)
    - turnoverrate     = round(volume / free_shares * 100, 4)   # volume 与 free_shares 同为“股”

    新浪未提供股本的个股（DB 无历史，如新上市股）保持为 0。
    返回回算到市值的行数（用于日志统计）。
    """
    if data is None or len(data.index) == 0 or not shares_map:
        return 0

    codes = data['code'].astype(str)
    total_shares = codes.map(lambda c: shares_map.get(c, (0, 0))[0]).astype('float64')
    free_shares = codes.map(lambda c: shares_map.get(c, (0, 0))[1]).astype('float64')
    new_price = pd.to_numeric(data['new_price'], errors='coerce').fillna(0.0)
    volume = pd.to_numeric(data['volume'], errors='coerce').fillna(0.0)

    # 统一目标列 dtype，避免向 int 列写入小数（如换手率）触发 pandas dtype 错误
    data['total_market_cap'] = pd.to_numeric(data['total_market_cap'], errors='coerce').fillna(0).astype('int64')
    data['free_cap'] = pd.to_numeric(data['free_cap'], errors='coerce').fillna(0).astype('int64')
    data['turnoverrate'] = pd.to_numeric(data['turnoverrate'], errors='coerce').fillna(0.0).astype('float64')
    data['total_shares'] = pd.to_numeric(data['total_shares'], errors='coerce').fillna(0).astype('int64')
    data['free_shares'] = pd.to_numeric(data['free_shares'], errors='coerce').fillna(0).astype('int64')

    cur_total_cap = data['total_market_cap']
    cur_free_cap = data['free_cap']
    cur_turnover = data['turnoverrate']

    # 仅在原值为 0 且有可用股本时回算
    total_cap_mask = (cur_total_cap <= 0) & (total_shares > 0) & (new_price > 0)
    free_cap_mask = (cur_free_cap <= 0) & (free_shares > 0) & (new_price > 0)
    turnover_mask = (cur_turnover <= 0) & (free_shares > 0) & (volume > 0)

    data.loc[total_cap_mask, 'total_market_cap'] = (new_price * total_shares)[total_cap_mask].round().astype('int64')
    data.loc[free_cap_mask, 'free_cap'] = (new_price * free_shares)[free_cap_mask].round().astype('int64')
    data.loc[turnover_mask, 'turnoverrate'] = (volume / free_shares * 100)[turnover_mask].round(4)

    # 顺带补回股本列本身（便于下游使用）
    ts_mask = (data['total_shares'] <= 0) & (total_shares > 0)
    fs_mask = (data['free_shares'] <= 0) & (free_shares > 0)
    data.loc[ts_mask, 'total_shares'] = total_shares[ts_mask].astype('int64')
    data.loc[fs_mask, 'free_shares'] = free_shares[fs_mask].astype('int64')

    return int(total_cap_mask.sum())


# 读取当天股票数据（支持多数据源自动切换）
# 优先级: 东方财富 -> 腾讯财经 -> 新浪财经
def fetch_stocks(date):
    data = None
    source = None

    # 数据源列表，按优先级排序（东方财富更稳定，作为首选）
    data_sources = [
        ("东方财富", she.stock_zh_a_spot_em),
        ("腾讯财经", stc.stock_zh_a_spot_tencent),
        ("新浪财经", ssa.stock_zh_a_spot_sina),
    ]
    data_sources = _apply_source_priority(data_sources)
    data_sources = _sort_sources_by_health(data_sources)

    for source_name, fetch_func in data_sources:
        try:
            logging.info(f"尝试从{source_name}获取股票数据...")
            data = fetch_func()
            if data is not None and len(data.index) > 0:
                source = source_name
                _report_source_success(source_name)
                break
        except Exception as e:
            logging.warning(f"{source_name}数据获取失败：{e}，切换下一个数据源")
            _report_source_failure(source_name)
            data = None

    # 所有数据源都失败
    if data is None or len(data.index) == 0:
        logging.error("所有数据源均获取失败")
        return None

    try:
        logging.info(f"成功从{source}获取 {len(data)} 条股票数据")
        if date is None:
            data.insert(0, 'date', datetime.datetime.now().strftime("%Y-%m-%d"))
        else:
            data.insert(0, 'date', date.strftime("%Y-%m-%d"))
        data.columns = list(tbs.TABLE_CN_STOCK_SPOT['columns'])
        data = data.loc[data['code'].apply(is_a_stock)].loc[data['new_price'].apply(is_open)]

        # 新浪财经不提供股本/市值/换手率（这些列为 0），用历史股本回算弥补，
        # 避免市值为 0 导致下游按市值阈值过滤时被错误剔除。
        if source == '新浪财经':
            try:
                shares_map = _load_latest_shares_from_db()
                if shares_map:
                    filled = _backfill_shares_derived_columns(data, shares_map)
                    logging.info(
                        f"新浪数据缺市值/换手率，已用历史股本回算 {filled} 只"
                        f"（缺历史股本 {max(len(data.index) - filled, 0)} 只保持为空）"
                    )
            except Exception:
                logging.warning("新浪市值/换手率回算异常，保持原值", exc_info=True)

        return data
    except Exception as e:
        logging.error(f"stockfetch.fetch_stocks处理异常", exc_info=True)
    return None


# 选股器（支持多数据源：东方财富选股器 -> 新浪财经基础数据）
def fetch_stock_selection():
    data = None
    source = None

    # 数据源列表，按优先级排序
    # 东方财富提供更完整的数据（包含换手率等），作为首选
    # 新浪财经作为备选（不提供换手率、量比等）
    data_sources = [
        ("东方财富", sst.stock_selection),
        ("新浪财经", ssa.stock_zh_a_spot_sina),
    ]

    for source_name, fetch_func in data_sources:
        try:
            logging.info(f"尝试从{source_name}获取选股数据...")
            data = fetch_func()
            if data is not None and len(data.index) > 0:
                source = source_name
                break
        except Exception as e:
            logging.warning(f"{source_name}选股数据获取失败：{e}，切换下一个数据源")
            data = None

    if data is None or len(data.index) == 0:
        logging.error("所有选股数据源均获取失败")
        return None

    try:
        logging.info(f"成功从{source}获取 {len(data)} 条选股数据")

        # 先做一次 copy() 去碎片化，避免 PerformanceWarning
        data = data.copy()

        if source == "东方财富":
            # 东方财富返回的列名是大写的API字段名（map值），需要映射回数据库字段名
            cols = tbs.TABLE_CN_STOCK_SELECTION['columns']
            rename_map = {cols[k]['map']: k for k in cols if 'map' in cols[k]}
            data = data.rename(columns=rename_map)
            # 东方财富API不返回涨跌额，需要计算: ups_downs = new_price - pre_close
            if 'new_price' in data.columns and 'pre_close' in data.columns:
                data['ups_downs'] = (data['new_price'] - data['pre_close']).round(4)
        elif source == "新浪财经":
            # 新浪财经数据需要重命名列名为英文，与数据库字段一致
            data = data.rename(columns={
                '代码': 'code',
                '名称': 'name',
                '最新价': 'new_price',
                '涨跌幅': 'change_rate',
                '涨跌额': 'ups_downs',
                '成交量': 'volume',
                '成交额': 'turnover',
                '振幅': 'amplitude',
                '换手率': 'turnoverrate',
                '量比': 'volume_ratio',
                '今开': 'open',
                '最高': 'high',
                '最低': 'low',
                '昨收': 'pre_close',
            })

        # 添加 date 列（如果不存在）
        if 'date' not in data.columns:
            import datetime
            data['date'] = datetime.date.today()

        if 'code' in data.columns:
            data.drop_duplicates('code', keep='last', inplace=True)

        # 只保留表定义中存在的列，避免 INSERT 时列不匹配
        valid_columns = list(tbs.TABLE_CN_STOCK_SELECTION['columns'].keys())
        existing_columns = [col for col in valid_columns if col in data.columns]
        data = data[existing_columns]

        return data
    except Exception as e:
        logging.error(f"stockfetch.fetch_stocks_selection处理异常", exc_info=True)
    return None


# 读取股票资金流向（支持多数据源：新浪财经 -> 东方财富）
def fetch_stocks_fund_flow(index):
    data = None
    source = None
    cn_flow = tbs.CN_STOCK_FUND_FLOW[index]

    # 数据源列表，按优先级排序（东方财富更稳定，作为首选）
    data_sources = [
        ("东方财富", lambda: sff.stock_individual_fund_flow_rank(indicator=cn_flow['cn'])),
        ("新浪财经", lambda: sfs.stock_individual_fund_flow_rank_sina(indicator=cn_flow['cn'])),
    ]

    for source_name, fetch_func in data_sources:
        try:
            logging.info(f"尝试从{source_name}获取资金流向数据...")
            data = fetch_func()
            if data is not None and len(data.index) > 0:
                source = source_name
                break
        except Exception as e:
            logging.warning(f"{source_name}资金流向数据获取失败：{e}，切换下一个数据源")
            data = None

    if data is None or len(data.index) == 0:
        logging.error("所有资金流向数据源均获取失败")
        return None

    try:
        logging.info(f"成功从{source}获取 {len(data)} 条资金流向数据")
        data.columns = list(cn_flow['columns'])
        data = data.loc[data['code'].apply(is_a_stock)].loc[data['new_price'].apply(is_open_with_line)]
        return data
    except Exception as e:
        logging.error(f"stockfetch.fetch_stocks_fund_flow处理异常", exc_info=True)
    return None


# 读取板块资金流向（支持多数据源：东方财富 → 新浪财经）
def fetch_stocks_sector_fund_flow(index_sector, index_indicator):
    cn_flow = tbs.CN_STOCK_SECTOR_FUND_FLOW[1][index_indicator]
    sector_type = tbs.CN_STOCK_SECTOR_FUND_FLOW[0][index_sector]

    data_sources = [
        ("东方财富", lambda: sff.stock_sector_fund_flow_rank(indicator=cn_flow['cn'], sector_type=sector_type)),
        ("新浪财经", lambda: sfs.stock_sector_fund_flow_rank_sina(indicator=cn_flow['cn'], sector_type=sector_type)),
    ]

    for source_name, fetch_func in data_sources:
        try:
            logging.info(f"尝试从{source_name}获取板块资金流向数据...")
            data = fetch_func()
            if data is not None and not data.empty:
                logging.info(f"成功从{source_name}获取 {len(data)} 条板块资金流向数据")
                data.columns = list(cn_flow['columns'])
                return data
        except Exception as e:
            logging.warning(f"{source_name}板块资金流向数据获取失败：{e}，切换下一个数据源")

    logging.error(f"所有板块资金流向数据源均获取失败：sector={index_sector}, indicator={cn_flow['cn']}")
    return None


# 读取股票分红配送
def fetch_stocks_bonus(date):
    try:
        data = sfe.stock_fhps_em(date=trd.get_bonus_report_date())
        if data is None or len(data.index) == 0:
            return None
        if date is None:
            data.insert(0, 'date', datetime.datetime.now().strftime("%Y-%m-%d"))
        else:
            data.insert(0, 'date', date.strftime("%Y-%m-%d"))
        data.columns = list(tbs.TABLE_CN_STOCK_BONUS['columns'])
        data = data.loc[data['code'].apply(is_a_stock)]
        return data
    except Exception as e:
        logging.error(f"stockfetch.fetch_stocks_bonus处理异常", exc_info=True)
    return None


# 股票近三月上龙虎榜且必须有2次以上机构参与的
def fetch_stock_top_entity_data(date):
    run_date = date + datetime.timedelta(days=-90)
    start_date = run_date.strftime("%Y%m%d")
    end_date = date.strftime("%Y%m%d")
    code_name = '代码'
    entity_amount_name = '买方机构数'
    try:
        data = sle.stock_lhb_jgmmtj_em(start_date, end_date)
        if data is None or len(data.index) == 0:
            return None

        # 机构买入次数大于1计算方法，首先：每次要有买方机构数(>0),然后：这段时间买方机构数求和大于1
        mask = (data[entity_amount_name] > 0)  # 首先：每次要有买方机构数(>0)
        data = data.loc[mask]

        if len(data.index) == 0:
            return None

        grouped = data.groupby(by=data[code_name])
        data_series = grouped[entity_amount_name].sum()
        data_code = set(data_series[data_series > 1].index.values)  # 然后：这段时间买方机构数求和大于1

        if not data_code:
            return None

        return data_code
    except Exception as e:
        logging.error(f"stockfetch.fetch_stock_top_entity_data处理异常", exc_info=True)
    return None

# 描述: 获取龙虎榜-个股上榜统计（支持多数据源：新浪财经 -> 东方财富）
def fetch_stock_lhb_data(date, count=12):
    data = None
    source = None
    start_date = trd.get_previous_trade_date(date, count).strftime("%Y%m%d")
    end_date = date.strftime("%Y%m%d")

    # 数据源列表，按优先级排序（东方财富更稳定，作为首选）
    data_sources = [
        ("东方财富", lambda: sle.stock_lhb_detail_em(start_date, end_date)),
        ("新浪财经", lambda: sls.stock_lhb_detail_daily_sina(end_date)),
    ]

    for source_name, fetch_func in data_sources:
        try:
            logging.info(f"尝试从{source_name}获取龙虎榜数据...")
            data = fetch_func()
            if data is not None and len(data.index) > 0:
                source = source_name
                break
        except Exception as e:
            logging.warning(f"{source_name}龙虎榜数据获取失败：{e}，切换下一个数据源")
            data = None

    if data is None or len(data.index) == 0:
        logging.error("所有龙虎榜数据源均获取失败")
        return None

    try:
        logging.info(f"成功从{source}获取 {len(data)} 条龙虎榜数据")

        # 根据数据源处理列名
        if source == "新浪财经":
            # 新浪数据列较少(序号,股票代码,股票名称,收盘价,对应值,成交量,成交额,指标)
            # 需要映射到标准表结构并填充缺失列
            import numpy as np
            data = data.rename(columns={
                '股票代码': 'code',
                '股票名称': 'name',
                '收盘价': 'new_price',
                '成交额': 'lhb_amount',
                '成交量': 'sum_buy',
                '指标': 'reason',
            })
            # 删除不需要的列
            for col in ['序号', '对应值']:
                if col in data.columns:
                    data.drop(col, axis=1, inplace=True)
            # 填充标准表结构中缺失的列
            target_columns = list(tbs.TABLE_CN_STOCK_lHB['columns'])
            for col in target_columns:
                if col not in data.columns and col != 'date':
                    data[col] = np.nan
            if 'date' not in data.columns:
                if date is None:
                    data.insert(0, 'date', datetime.datetime.now().strftime("%Y-%m-%d"))
                else:
                    data.insert(0, 'date', date.strftime("%Y-%m-%d"))
            # 按标准列顺序排列
            data = data[target_columns]
        else:
            _columns = list(tbs.TABLE_CN_STOCK_lHB['columns'])
            _columns.pop(0)
            data.columns = _columns
            if date is None:
                data.insert(0, 'date', datetime.datetime.now().strftime("%Y-%m-%d"))
            else:
                data.insert(0, 'date', date.strftime("%Y-%m-%d"))

        data = data.loc[data['code'].apply(is_a_stock)]
        data.drop_duplicates('code', keep='last', inplace=True)
        return data
    except Exception as e:
        logging.error(f"stockfetch.fetch_stock_lhb_data处理异常", exc_info=True)
    return None

# 描述: 获取新浪财经-龙虎榜-个股上榜统计
def fetch_stock_top_data(date):
    try:
        data = sls.stock_lhb_ggtj_sina()
        if data is None or len(data.index) == 0:
            return None
        _columns = list(tbs.TABLE_CN_STOCK_TOP['columns'])
        _columns.pop(0)
        data.columns = _columns
        data = data.loc[data['code'].apply(is_a_stock)]
        data.drop_duplicates('code', keep='last', inplace=True)
        if date is None:
            data.insert(0, 'date', datetime.datetime.now().strftime("%Y-%m-%d"))
        else:
            data.insert(0, 'date', date.strftime("%Y-%m-%d"))
        return data
    except Exception as e:
        logging.error(f"stockfetch.fetch_stock_top_data处理异常", exc_info=True)
    return None


# 描述: 获取东方财富网-数据中心-大宗交易-每日统计
def fetch_stock_blocktrade_data(date):
    date_str = date.strftime("%Y%m%d")
    try:
        data = sde.stock_dzjy_mrtj(start_date=date_str, end_date=date_str)
        if data is None or len(data.index) == 0:
            return None

        columns = list(tbs.TABLE_CN_STOCK_BLOCKTRADE['columns'])
        columns.insert(0, 'index')
        data.columns = columns
        data = data.loc[data['code'].apply(is_a_stock)]
        data.drop('index', axis=1, inplace=True, errors='ignore')
        return data
    except TypeError:
        logging.warning("目前还没有大宗交易数据，请17:00点后再获取")
        return None
    except Exception as e:
        logging.error(f"stockfetch.fetch_stock_blocktrade_data处理异常", exc_info=True)
    return None

# 读取早盘抢筹
def fetch_stock_chip_race_open(date):
    try:
        date_str =""
        if date != datetime.datetime.now().date():
            date_str = date.strftime("%Y%m%d")
        data = scr.stock_chip_race_open(date_str)
        if data is None or len(data.index) == 0:
            return None
        if date is None:
            data.insert(0, 'date', datetime.datetime.now().strftime("%Y-%m-%d"))
        else:
            data.insert(0, 'date', date.strftime("%Y-%m-%d"))
        data.columns = list(tbs.TABLE_CN_STOCK_CHIP_RACE_OPEN['columns'])
        return data
    except Exception as e:
        logging.warning(f"stockfetch.fetch_stock_chip_race_open处理异常: {e}")
    return None

# 读取尾盘抢筹
def fetch_stock_chip_race_end(date):
    try:
        date_str =""
        if date != datetime.datetime.now().date():
            date_str = date.strftime("%Y%m%d")
        data = scr.stock_chip_race_end(date_str)
        if data is None or len(data.index) == 0:
            return None
        if date is None:
            data.insert(0, 'date', datetime.datetime.now().strftime("%Y-%m-%d"))
        else:
            data.insert(0, 'date', date.strftime("%Y-%m-%d"))
        data.columns = list(tbs.TABLE_CN_STOCK_CHIP_RACE_END['columns'])
        return data
    except Exception as e:
        logging.warning(f"stockfetch.fetch_stock_chip_race_end处理异常: {e}")
    return None

def _normalize_volume_to_shares(data):
    """将 K 线 DataFrame 的 volume 列规范化为"股"。

    历史背景（修复 000001 等老股票 2026-02 起 K 线成交量 100× 偏差问题）：
    - 早期 akshare 数据源返回 volume 单位为 "股"
    - 2026 年初起，akshare 切换为返回 "手"（1 手 = 100 股）
    - 既有缓存里两段并存：旧段是股、新段是手
    - 旧代码统一 ``volume * 100``，导致旧段 100× 偏大，新段正确
      表现为 K 线成交量副图中 2026-02 之后柱状几乎贴底"消失"

    本函数按行检测 ``amount / (close * volume)`` 比值：
    - ≈1   → 已是股，保持不变
    - ≈100 → 是手，乘以 100 转换为股
    - 缺失 amount/close → 回退为 ×100（兼容旧逻辑）
    返回修改后的 DataFrame（就地修改并返回，便于链式调用）。
    """
    if data is None or 'volume' not in data.columns or len(data) == 0:
        return data
    try:
        import numpy as np
        volume = pd.to_numeric(data['volume'], errors='coerce').astype('float64')
        if 'amount' in data.columns and 'close' in data.columns:
            amount = pd.to_numeric(data['amount'], errors='coerce').astype('float64')
            close = pd.to_numeric(data['close'], errors='coerce').astype('float64')
            denom = volume * close
            with np.errstate(divide='ignore', invalid='ignore'):
                ratio = np.where((denom > 0) & (amount > 0), amount / denom, np.nan)
            # 阈值 30：远大于股价波动（<2），远小于 100；可靠区分两种单位
            is_lot = pd.Series(ratio, index=data.index) > 30
            no_info = pd.Series(ratio, index=data.index).isna()
            new_vol = volume.copy()
            new_vol.loc[is_lot] = volume.loc[is_lot] * 100
            # 缺失 amount 时回退到 ×100（保留旧行为，避免回测路径出现新偏差）
            new_vol.loc[no_info] = volume.loc[no_info] * 100
            data['volume'] = new_vol
        else:
            data['volume'] = volume * 100
    except Exception:
        # 兜底：异常时退回旧逻辑
        try:
            data['volume'] = data['volume'].astype('double') * 100
        except Exception:
            pass
    return data


# 读取涨停原因
def fetch_stock_limitup_reason(date):

    try:
        data = slr.stock_limitup_reason(date.strftime("%Y-%m-%d"))
        if data is None or len(data.index) == 0:
            return None
        data.columns = list(tbs.TABLE_CN_STOCK_LIMITUP_REASON['columns'])
        return data
    except Exception as e:
        logging.error(f"stockfetch.fetch_stock_limitup_reason处理异常", exc_info=True)
    return None

# 读取ETF历史数据（多数据源 + 缓存支持）
# ETF code_id_map 依赖东方财富的在线API（@lru_cache），当API不可用时直接降级到腾讯/新浪
# 腾讯和新浪使用市场前缀规则（5开头→sh，1开头→sz），无需在线code_id_map
def fetch_etf_hist(data_base, date_start=None, date_end=None, adjust='qfq'):
    date = data_base[0]
    code = data_base[1]

    if date_start is None:
        date_start, is_cache = trd.get_trade_hist_interval(date)
    else:
        is_cache = True

    if date_end is None:
        if isinstance(date, str):
            date_end = date.replace("-", "")
        else:
            date_end = date.strftime("%Y%m%d")

    try:
        # 复用股票的增量缓存 + 多数据源回退机制
        # ETF代码以1或5开头，_fetch_from_sources 中的三个数据源均已支持：
        # - 东方财富: code_id_map 已扩展支持1/5前缀
        # - 腾讯财经: _get_market_prefix 已修正 5→sh, 1→sz
        # - 新浪财经: 同上
        data = stock_hist_cache_incremental(code, date_start, date_end, is_cache, 'qfq')
        if data is not None:
            data = data.copy()
            data['p_change'] = tl.ROC(data['close'].values, 1)
            data['p_change'] = data['p_change'].fillna(0.0)
            # 成交量自适应规范化为"股"（兼容历史 "股" 段 + 新 "手" 段混存的缓存）
            data = _normalize_volume_to_shares(data)
        return data
    except Exception as e:
        logging.error(f"stockfetch.fetch_etf_hist处理异常: {code}", exc_info=True)
    return None


# 读取股票历史数据（支持增量更新）
# 参数说明：
#   data_base: (date, code) 元组
#   date_start: 起始日期，格式 YYYYMMDD，默认为20年前
#   date_end: 结束日期，格式 YYYYMMDD，默认为当前日期
#   is_cache: 是否使用缓存
#   years: 历史数据年数，默认10年
# 数据单位说明：
#   缓存中的 volume = 手（100股），各数据源已统一
#   本函数返回的 volume = 股（手 × 100）
#   amount = 元
def fetch_stock_hist(data_base, date_start=None, date_end=None, is_cache=True, years=None):
    date = data_base[0]
    code = data_base[1]

    if years is None:
        years = HIST_DATA_DEFAULT_YEARS

    if date_start is None:
        date_start, is_cache = trd.get_trade_hist_interval(date, years)

    if date_end is None:
        if isinstance(date, str):
            date_end = date.replace("-", "")
        else:
            date_end = date.strftime("%Y%m%d")

    try:
        data = stock_hist_cache_incremental(code, date_start, date_end, is_cache, 'qfq')
        if data is not None:
            # 创建数据副本以避免修改只读数组
            data = data.copy()
            data['p_change'] = tl.ROC(data['close'].values, 1)
            data['p_change'] = data['p_change'].fillna(0.0)
            # 成交量自适应规范化为"股"（兼容历史 "股" 段 + 新 "手" 段混存的缓存）
            data = _normalize_volume_to_shares(data)
        return data
    except Exception as e:
        logging.error(f"stockfetch.fetch_stock_hist处理异常", exc_info=True)
    return None


def _get_cache_file_path(code, adjust=''):
    """获取缓存文件路径（按股票代码组织）"""
    cache_dir = os.path.join(stock_hist_cache_path, code[:3])  # 按代码前3位分组
    try:
        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir, exist_ok=True)
    except Exception as e:
        logging.debug(f"创建缓存目录失败: {cache_dir} - {e}")
    return os.path.join(cache_dir, f"{code}{adjust}.gzip.pickle")


def _get_cache_meta_path(code, adjust=''):
    """获取缓存元数据文件路径"""
    cache_dir = os.path.join(stock_hist_cache_path, code[:3])
    return os.path.join(cache_dir, f"{code}{adjust}.meta")


# ══════════════════════════════════════════════
# 指数缓存目录（与股票缓存分离，避免代码冲突）
# cache/hist/index/{code}.gzip.pickle
# ══════════════════════════════════════════════
index_hist_cache_path = os.path.join(stock_hist_cache_path, 'index')
if not os.path.exists(index_hist_cache_path):
    os.makedirs(index_hist_cache_path, exist_ok=True)


def _get_index_cache_file_path(code):
    """获取指数缓存文件路径（指数无复权，不需要 adjust 参数）"""
    return os.path.join(index_hist_cache_path, f"{code}.gzip.pickle")


def _get_index_cache_meta_path(code):
    """获取指数缓存元数据文件路径"""
    return os.path.join(index_hist_cache_path, f"{code}.meta")


def index_hist_cache_incremental(code, date_start, date_end):
    """
    增量更新指数历史 K 线缓存。

    与 stock_hist_cache_incremental 类似，但使用指数专用 API 和缓存目录。
    指数无复权，缓存路径为 cache/hist/index/{code}.gzip.pickle

    参数：
        code: 指数代码（如 '000300'）
        date_start: 起始日期 YYYYMMDD
        date_end: 结束日期 YYYYMMDD

    返回：
        DataFrame 或 None
    """
    _standard_columns = ('date', 'open', 'close', 'high', 'low', 'volume',
                         'deal_amount', 'amplitude', 'quote_change', 'ups_downs', 'turnoverrate')
    cache_file = _get_index_cache_file_path(code)

    try:
        cached_data = None
        cache_first_date = None
        cache_last_date = None

        # 1. 读取缓存
        if os.path.isfile(cache_file):
            try:
                cached_data = pd.read_pickle(cache_file, compression="gzip")
                if cached_data is not None and len(cached_data) > 0 and 'date' in cached_data.columns:
                    valid_cols = [c for c in _standard_columns if c in cached_data.columns]
                    cached_data = cached_data[valid_cols]
                    cache_first_date = _to_date_str(cached_data['date'].min())
                    cache_last_date = _to_date_str(cached_data['date'].max())
                else:
                    cached_data = None
            except Exception as e:
                logging.warning(f"读取指数缓存失败，将重新获取: {code} - {e}")
                cached_data = None

        # 2. 确定需要拉取的区间
        need_tail = False
        need_head = False
        tail_start = None
        head_end = None

        if cached_data is None:
            need_tail = True
            tail_start = date_start
        else:
            if cache_last_date < date_end:
                need_tail = True
                # 与 stock_hist_cache_incremental 一致：跳过已缓存的最后一天，从下一天开始拉取
                last_obj = datetime.datetime.strptime(cache_last_date, "%Y%m%d")
                next_day = (last_obj + datetime.timedelta(days=1)).strftime("%Y%m%d")
                tail_start = next_day
            if date_start < cache_first_date:
                need_head = True
                head_end = cache_first_date

        # 3. 从东方财富获取新增数据
        new_parts = []
        if need_tail:
            try:
                raw = sie.stock_index_hist_em(
                    symbol=code, period='daily',
                    start_date=tail_start, end_date=date_end
                )
                if raw is not None and len(raw) > 0:
                    _df = _normalize_index_hist(raw, _standard_columns)
                    if _df is not None:
                        new_parts.append(_df)
                        logging.info(f"指数 {code} 尾部增量: +{len(_df)} 条")
            except Exception as e:
                logging.warning(f"获取指数 {code} 尾部数据失败: {e}")

        if need_head:
            try:
                raw = sie.stock_index_hist_em(
                    symbol=code, period='daily',
                    start_date=date_start, end_date=head_end
                )
                if raw is not None and len(raw) > 0:
                    _df = _normalize_index_hist(raw, _standard_columns)
                    if _df is not None:
                        new_parts.append(_df)
                        logging.info(f"指数 {code} 头部补全: +{len(_df)} 条")
            except Exception as e:
                logging.warning(f"获取指数 {code} 头部数据失败: {e}")

        # 4. 合并并保存
        if new_parts:
            all_parts = ([cached_data] if cached_data is not None else []) + new_parts
            merged = pd.concat(all_parts, ignore_index=True)
            merged['date'] = pd.to_datetime(merged['date'])
            merged = merged.drop_duplicates(subset=['date'], keep='last')
            merged = merged.sort_values('date').reset_index(drop=True)

            # 原子写入缓存
            tmp_file = cache_file + '.tmp'
            try:
                merged.to_pickle(tmp_file, compression="gzip")
                if os.path.exists(cache_file):
                    os.remove(cache_file)
                os.rename(tmp_file, cache_file)
            except Exception as e:
                logging.warning(f"写入指数缓存失败: {code} - {e}")
                if os.path.exists(tmp_file):
                    try:
                        os.remove(tmp_file)
                    except Exception:
                        pass

            # 写入 meta
            try:
                meta_path = _get_index_cache_meta_path(code)
                last_date = _to_date_str(merged['date'].max())
                with open(meta_path, 'w') as f:
                    f.write(f"{last_date},{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}")
            except Exception as e:
                logging.debug(f"写入指数缓存 meta 失败: {code} - {e}")

            return merged

        return cached_data

    except Exception as e:
        logging.error(f"index_hist_cache_incremental 异常: {code} - {e}", exc_info=True)
    return None


def _normalize_index_hist(raw_df, standard_columns):
    """
    将东方财富返回的中文列名指数 K 线数据 → 标准化 DataFrame

    映射关系与 stock_zh_a_hist 返回格式一致。
    """
    col_map = {
        '日期': 'date', '开盘': 'open', '收盘': 'close',
        '最高': 'high', '最低': 'low', '成交量': 'volume',
        '成交额': 'deal_amount', '振幅': 'amplitude',
        '涨跌幅': 'quote_change', '涨跌额': 'ups_downs',
        '换手率': 'turnoverrate',
    }
    df = raw_df.rename(columns=col_map)
    valid_cols = [c for c in standard_columns if c in df.columns]
    if 'date' not in valid_cols or 'close' not in valid_cols:
        return None
    df = df[valid_cols].copy()
    df['date'] = pd.to_datetime(df['date'])
    for c in ['open', 'high', 'low', 'close', 'volume']:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce')
    return df


def read_index_hist_from_cache(code, date_start=None, date_end=None):
    """
    从缓存读取指数历史 K 线数据（只读，不发起 API 请求）。

    与 read_stock_hist_from_cache 类似，但读取指数专用缓存目录。

    返回包含 date/open/high/low/close/volume 列的 DataFrame，或 None。
    """
    try:
        cache_file = _get_index_cache_file_path(code)
        if not os.path.isfile(cache_file):
            return None

        data = pd.read_pickle(cache_file, compression="gzip")
        if data is None or len(data) == 0 or 'date' not in data.columns:
            return None

        data['date'] = pd.to_datetime(data['date'])

        # 日期过滤
        if date_start:
            data = data[data['date'] >= pd.Timestamp(str(date_start))]
        if date_end:
            data = data[data['date'] <= pd.Timestamp(str(date_end))]

        if len(data) == 0:
            return None

        data = data.sort_values('date').reset_index(drop=True)

        # 计算 p_change（涨跌幅 ROC 1日）
        if 'close' in data.columns:
            data = data.copy()
            data['p_change'] = tl.ROC(data['close'].values, 1)
            data['p_change'] = data['p_change'].fillna(0.0)

        return data
    except Exception as e:
        logging.warning(f"读取指数缓存异常 {code}: {e}")
        return None


def update_index_caches(index_codes=None, date_start=None, date_end=None, index_spot_df=None):
    """
    批量更新指数的 K 线缓存（数据驱动覆盖全市场指数）。

    与旧版（硬编码 14 个主要指数）的区别：
    - 默认从数据库 cn_index_spot 最新交易日读取全部指数代码（仅读 DB，无 API 调用），
      覆盖全市场指数；DB 不可用时回退到硬编码主要指数列表。
    - 每个指数走 index_hist_cache_incremental（东财指数 K线 API）增量更新；
      meta 已最新则跳过。

    设计说明（为何不做 Spot 快速追加）：
        指数不同于股票/ETF —— 实测 cn_index_spot.volume 与指数 K线 API 成交量的单位
        在不同指数间不一致（部分指数 100×，部分 1×，且历史日比值不稳定），
        固定/推导系数都无法保证成交量正确，会在 K 线末端注入错误的成交量柱。
        故指数始终走单一数据源的 API 增量，保证 OHLCV 内部自洽。

    参数：
        index_codes: 指数代码列表。None 时从 cn_index_spot 最新日动态获取。
        date_start: 起始日期 YYYYMMDD，None 时取 HIST_DATA_DEFAULT_YEARS 年前
        date_end:   结束日期 YYYYMMDD，None 时取今天
        index_spot_df: 可选，已加载的指数实时行情 DataFrame（须含 code 列）；
                       None 时从 cn_index_spot 最新交易日读取代码列表。

    返回：
        (success_count, fail_count)
    """
    import quantia.lib.database as mdb

    if date_start is None:
        _years = HIST_DATA_DEFAULT_YEARS
        start_dt = datetime.datetime.now() - datetime.timedelta(days=_years * 365)
        date_start = start_dt.strftime("%Y%m%d")
    if date_end is None:
        date_end = datetime.datetime.now().strftime("%Y%m%d")

    # 硬编码主要指数（仅作 DB 读取失败时的兜底）
    _HARDCODED = [
        '000001', '000002', '000003', '000016', '000300', '000688',
        '000852', '000905', '399001', '399005', '399006', '399300',
        '399673', '399951',
    ]

    # 决定要更新的指数代码集合：优先 cn_index_spot 最新交易日全量（仅读 DB，无 API）
    if index_codes is None:
        if index_spot_df is None and mdb.checkTableIsExist('cn_index_spot'):
            try:
                sql = (
                    "SELECT DISTINCT `code` FROM `cn_index_spot` "
                    "WHERE `date` = (SELECT MAX(`date`) FROM `cn_index_spot`) "
                    "AND `new_price` > 0 ORDER BY `code`"
                )
                index_spot_df = pd.read_sql(sql, mdb.engine())
            except Exception as e:
                logging.warning(f"update_index_caches：读取 cn_index_spot 失败，回退硬编码列表：{e}")
                index_spot_df = None
        if index_spot_df is not None and len(index_spot_df) > 0:
            index_codes = index_spot_df['code'].astype(str).tolist()
        else:
            index_codes = _HARDCODED

    # 指数间请求延迟（可通过环境变量配置）
    idx_delay_min = _cfg.get_float('QUANTIA_INDEX_DELAY_MIN', 0.5)
    idx_delay_max = _cfg.get_float('QUANTIA_INDEX_DELAY_MAX', 1.5)

    success = 0
    fail = 0
    skip = 0
    for code in index_codes:
        code = str(code)
        try:
            # 预检查：meta 已最新则跳过（与股票缓存一致）
            meta_path = _get_index_cache_meta_path(code)
            if os.path.isfile(meta_path):
                try:
                    with open(meta_path, 'r') as f:
                        meta_last_date = f.read().strip().split(',')[0]
                    if meta_last_date and meta_last_date >= date_end:
                        skip += 1
                        continue
                except Exception:
                    pass  # meta 读取失败不影响，继续正常更新

            result = index_hist_cache_incremental(code, date_start, date_end)
            if result is not None and len(result) > 0:
                success += 1
            else:
                fail += 1
                logging.warning(f"指数 {code} K线缓存更新失败: 无数据")
            # 实际发起 API 请求，添加延迟防限流
            time.sleep(random.uniform(idx_delay_min, idx_delay_max))
        except Exception as e:
            fail += 1
            logging.warning(f"指数 {code} K线缓存更新异常: {e}")

    logging.info(
        f"指数缓存更新：API成功={success}, 失败={fail}, 已最新跳过={skip}"
    )
    return success + skip, fail
# 当此版本号与 .meta 中的 filtered_version 匹配时，读取缓存可跳过 _filter_ohlc_outliers
_FILTER_VERSION = 2


def _read_cache_meta(code, adjust=''):
    """读取缓存元数据（最后更新日期 + 过滤版本号）"""
    meta_path = _get_cache_meta_path(code, adjust)
    try:
        if os.path.isfile(meta_path):
            with open(meta_path, 'r') as f:
                content = f.read().strip()
                parts = content.split(',')
                return {
                    'last_date': parts[0] if len(parts) > 0 else None,
                    'update_time': parts[1] if len(parts) > 1 else None,
                    'filtered_version': int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
                }
    except Exception as e:
        logging.debug(f"读取缓存元数据失败: {code} - {e}")
    return None


def _write_cache_meta(code, last_date, adjust='', filtered_version=0):
    """写入缓存元数据（含过滤版本号），使用原子写入避免并发读到半写文件"""
    meta_path = _get_cache_meta_path(code, adjust)
    try:
        tmp_path = meta_path + '.tmp'
        with open(tmp_path, 'w') as f:
            f.write(f"{last_date},{datetime.datetime.now().strftime('%Y%m%d%H%M%S')},{filtered_version}")
        os.replace(tmp_path, meta_path)
    except Exception as e:
        logging.warning(f"写入缓存元数据失败: {code} - {e}")
        # 清理临时文件
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass  # 临时文件清理失败影响较小，忽略


def _delete_cache(code, adjust=''):
    """删除指定股票的缓存文件和元数据文件"""
    try:
        cf = _get_cache_file_path(code, adjust)
        mf = _get_cache_meta_path(code, adjust)
        if os.path.exists(cf):
            os.remove(cf)
        if os.path.exists(mf):
            os.remove(mf)
    except Exception as e:
        logging.warning(f"删除缓存失败: {code} - {e}")


def _try_spot_append(code, spot_row, date_end, exrights_threshold):
    """
    尝试使用实时行情数据(spot)追加到K线缓存，避免逐股API调用。

    前置条件：
    - 缓存最后日期恰好是前一个交易日（仅差1天数据）
    - 该股票当日有交易（已在外部检查）

    安全检查：
    - 除权除息检测：比较spot的昨收(pre_close_price)与缓存最后收盘价
      如果差异超过阈值，说明发生了除权除息，前复权数据全部变化，
      需要删除缓存并全量重新获取
    - 数据完整性：读取pickle失败则回退到API

    列映射（spot → hist cache）：
      open_price → open, new_price → close, high_price → high, low_price → low,
      volume/100 → volume（股→手）, deal_amount → amount, amplitude → amplitude,
      change_rate → quote_change, ups_downs → ups_downs, turnoverrate → turnover

    Returns:
        'success'  — 追加成功，无需API调用
        'exrights' — 检测到除权除息，需要删除缓存全量重新获取
        'error'    — 追加失败，回退到API
    """
    try:
        cache_file = _get_cache_file_path(code, 'qfq')
        if not os.path.isfile(cache_file):
            return 'error'

        # 读取现有缓存
        cached_data = pd.read_pickle(cache_file, compression="gzip")
        if cached_data is None or len(cached_data) == 0 or 'date' not in cached_data.columns:
            return 'error'

        # ── 除权除息检测 ──
        # 前复权(qfq)下，除权除息会改变全部历史价格。
        # 比较 spot 的昨收价与缓存最后一天收盘价，差异过大说明已发生除权。
        last_close = float(cached_data['close'].iloc[-1])
        _raw_pre = spot_row.get('pre_close_price', 0)
        pre_close = float(_raw_pre if _raw_pre is not None else 0)
        # NaN 保护：pre_close 或 last_close 为 NaN 时无法做除权判断，回退到 API
        if pd.isna(pre_close) or pd.isna(last_close):
            return 'error'
        if last_close > 0 and pre_close > 0:
            diff_ratio = abs(pre_close - last_close) / last_close
            if diff_ratio > exrights_threshold:
                logging.info(
                    f"检测到除权除息: {code}, spot昨收={pre_close:.2f}, "
                    f"缓存末收盘={last_close:.2f}, 差异={diff_ratio:.2%}"
                )
                return 'exrights'
        elif last_close <= 0 or pre_close <= 0:
            # 数据异常，回退到API
            return 'error'

        # ── 构造新行（spot → hist格式）──
        def _safe_float(v):
            """安全转换为float，NaN/None/空值均返回0.0"""
            try:
                v = float(v or 0)
                return 0.0 if pd.isna(v) else v
            except (ValueError, TypeError):
                return 0.0

        date_end_dash = _to_dash_date(date_end)
        _open = _safe_float(spot_row.get('open_price', 0))
        _close = _safe_float(spot_row.get('new_price', 0))
        _high = _safe_float(spot_row.get('high_price', 0))
        _low = _safe_float(spot_row.get('low_price', 0))
        # OHLC 完整性校验：任一价格字段为 0 则数据不可信，回退到 API
        if _open <= 0 or _close <= 0 or _high <= 0 or _low <= 0:
            return 'error'
        new_row = pd.DataFrame([{
            'date': date_end_dash,
            'open': _open,
            'close': _close,
            'high': _high,
            'low': _low,
            'volume': _safe_float(spot_row.get('volume', 0)) / 100,  # 股 → 手
            'amount': _safe_float(spot_row.get('deal_amount', 0)),
            'amplitude': _safe_float(spot_row.get('amplitude', 0)),
            'quote_change': _safe_float(spot_row.get('change_rate', 0)),
            'ups_downs': _safe_float(spot_row.get('ups_downs', 0)),
            'turnover': _safe_float(spot_row.get('turnoverrate', 0)),
        }])

        # ── 追加并去重 ──
        combined = pd.concat([cached_data, new_row], ignore_index=True)
        # 统一 date 列类型为字符串，避免 Timestamp vs str 导致 drop_duplicates 失效
        combined['date'] = combined['date'].apply(_to_dash_date_safe)
        combined = combined.drop_duplicates(subset=['date'], keep='last')
        combined = combined.sort_values(by='date').reset_index(drop=True)

        # ── 原子写入 ──
        tmp_file = cache_file + '.tmp'
        combined.to_pickle(tmp_file, compression="gzip")
        os.replace(tmp_file, cache_file)
        # 标记 filtered_version：spot数据来自交易所API（已收盘），不会是异常值。
        # 即使未经 _filter_ohlc_outliers 过滤，下次增量更新有新API数据时也会触发过滤。
        _write_cache_meta(code, date_end, 'qfq', filtered_version=_FILTER_VERSION)

        return 'success'
    except Exception as e:
        logging.warning(f"Spot追加失败: {code} - {e}")
        # 清理可能残留的临时文件
        try:
            tmp = _get_cache_file_path(code, 'qfq') + '.tmp'
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        return 'error'


def _fetch_from_sources(code, fetch_start, date_end, adjust=''):
    """
    从多个数据源获取K线数据（东方财富 → 腾讯财经 → 新浪财经）

    所有数据源返回的数据格式已统一：
    - 列顺序：[date, open, close, high, low, volume, amount, amplitude, quote_change, ups_downs, turnover]
    - volume 单位：手（100股）
    - amount 单位：元
    - date 格式：YYYY-MM-DD

    参数：
        code: 股票代码
        fetch_start: 起始日期 YYYYMMDD
        date_end: 结束日期 YYYYMMDD
        adjust: 复权类型
    返回：
        DataFrame 或 None
    """
    data_sources = [
        ('东方财富', lambda: she.stock_zh_a_hist(
            symbol=code, period="daily",
            start_date=fetch_start, end_date=date_end, adjust=adjust
        )),
        ('腾讯财经', lambda: sht.stock_zh_a_hist_tencent(
            symbol=code, period="daily",
            start_date=fetch_start, end_date=date_end, adjust=adjust
        )),
        ('新浪财经', lambda: shs.stock_zh_a_hist_sina(
            symbol=code, period="daily",
            start_date=fetch_start, end_date=date_end, adjust=adjust
        ))
    ]

    # 按数据源健康度排序：降级的排到末尾，减少不必要的超时等待
    data_sources = _sort_sources_by_health(data_sources)

    for source_name, fetch_func in data_sources:
        for retry in range(DATA_SOURCE_MAX_RETRIES):
            try:
                new_data = fetch_func()
                if new_data is not None and len(new_data) > 0:
                    # 统一列名为 CN_STOCK_HIST_DATA 标准
                    new_data.columns = tuple(tbs.CN_STOCK_HIST_DATA['columns'])
                    logging.debug(f"从{source_name}成功获取数据: {code} ({fetch_start}-{date_end})")
                    _report_source_success(source_name)
                    return new_data
                else:
                    # API 调用成功但返回空数据 —— 正常情况（停牌、无交易等），
                    # 不视为失败，不重试，不切换数据源，直接返回
                    logging.debug(f"从{source_name}获取数据为空(非错误): {code} ({fetch_start}-{date_end})")
                    return None
            except (ConnectionError, ConnectionResetError, ConnectionAbortedError) as e:
                # 连接级错误（IP封禁/网络不可达）：立即跳到下一个数据源，不浪费时间重试
                _log_source_failure_aggregated(source_name, code, str(e))
                _report_source_failure(source_name)
                break
            except Exception as e:
                err_str = str(e)
                # 检查是否为连接类错误或服务端过载（可能被包装在其他异常中）
                # 503/504 表示服务端暂时不可用，重试同一源无意义，应立即换源
                if any(keyword in err_str for keyword in [
                    'RemoteDisconnected', 'Connection aborted', 'ConnectionReset',
                    'SSLError', 'SSLEOFError', 'UNEXPECTED_EOF', 'Max retries exceeded',
                    '503 Server Error', '504 Server Error', '502 Server Error',
                    'Service Unavailable', 'Gateway Time-out', 'Bad Gateway',
                ]):
                    _log_source_failure_aggregated(source_name, code, err_str)
                    _report_source_failure(source_name)
                    break
                logging.warning(f"从{source_name}获取数据失败(尝试{retry+1}/{DATA_SOURCE_MAX_RETRIES}): {code} - {e}")
                if retry < DATA_SOURCE_MAX_RETRIES - 1:
                    _retry_sleep(retry)
                else:
                    _report_source_failure(source_name)

        # 当前数据源所有重试都失败，尝试下一个

    # ── 所有三大数据源都失败 → 尝试 Akshare 备用通道 ──
    # akshare.stock_zh_a_hist 走 EastMoney 的 kline-pre 端点，
    # 当 push2his 接口 500 时往往仍可用。
    try:
        import akshare as ak
        new_data = ak.stock_zh_a_hist(
            symbol=code, period='daily',
            start_date=fetch_start, end_date=date_end, adjust=adjust or 'qfq'
        )
        if new_data is not None and len(new_data) > 0:
            new_data.columns = tuple(tbs.CN_STOCK_HIST_DATA['columns'])
            logging.info(f"从 Akshare 备用通道成功获取数据: {code} ({fetch_start}-{date_end}), {len(new_data)} 条")
            return new_data
    except Exception as e:
        logging.debug(f"Akshare 备用通道也失败: {code} - {e}")

    return None


def _to_date_str(d):
    """将日期转为 YYYYMMDD 格式字符串"""
    if isinstance(d, str):
        return d.replace("-", "")
    return d.strftime("%Y%m%d")


def _to_dash_date(yyyymmdd):
    """将 YYYYMMDD 转为 YYYY-MM-DD"""
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:]}"


def _to_dash_date_safe(d):
    """将任意日期类型（str / Timestamp / datetime）统一转为 YYYY-MM-DD 字符串。
    用于 drop_duplicates 前的类型归一化，防止 Timestamp vs str 导致去重失败。"""
    if isinstance(d, str):
        # 已经是字符串
        if '-' in d:
            return d[:10]  # 截取 YYYY-MM-DD
        # YYYYMMDD → YYYY-MM-DD
        return f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) >= 8 else d
    # Timestamp / datetime
    try:
        return d.strftime("%Y-%m-%d")
    except (AttributeError, ValueError):
        return str(d)


def stock_hist_cache_incremental(code, date_start, date_end, is_cache=True, adjust=''):
    """
    增量更新的股票历史数据缓存（多数据源支持）

    支持三种增量场景：
    1. 尾部追加：缓存最后日期 < date_end，从缓存末尾向后拉取
    2. 向前补数据：date_start < 缓存最早日期，从 date_start 到缓存起始拉取
    3. 无缓存：全量拉取 date_start ~ date_end

    数据源优先级：东方财富 → 腾讯财经 → 新浪财经

    参数：
        code: 股票代码
        date_start: 起始日期 YYYYMMDD
        date_end: 结束日期 YYYYMMDD
        is_cache: 是否使用缓存
        adjust: 复权类型 qfq/hfq/''
    """
    # 标准列名（用于缓存统一）
    _standard_columns = tuple(tbs.CN_STOCK_HIST_DATA['columns'])
    # 旧列名 → 新列名映射（兼容旧缓存数据）
    _column_rename_map = {
        'pct_chg': 'quote_change',
        'change': 'ups_downs',
    }
    cache_file = _get_cache_file_path(code, adjust)

    try:
        cached_data = None
        cache_first_date = None
        cache_last_date = None

        # 1. 读取缓存
        if is_cache and os.path.isfile(cache_file):
            try:
                cached_data = pd.read_pickle(cache_file, compression="gzip")
                if cached_data is not None and len(cached_data) > 0 and 'date' in cached_data.columns:
                    # 统一旧缓存列名（兼容 EastMoney 旧列名 pct_chg/change）
                    cached_data = cached_data.rename(columns=_column_rename_map)
                    # 合并重复列（旧缓存可能已含新旧两套列名，用 fillna 合并）
                    dup_mask = cached_data.columns.duplicated(keep=False)
                    if dup_mask.any():
                        for col_name in cached_data.columns[dup_mask].unique():
                            dup_cols = cached_data.loc[:, cached_data.columns == col_name]
                            merged = dup_cols.iloc[:, 0].fillna(dup_cols.iloc[:, 1])
                            cached_data = cached_data.loc[:, cached_data.columns != col_name]
                            cached_data[col_name] = merged
                    # 确保只保留标准列，丢弃多余列
                    valid_cols = [c for c in _standard_columns if c in cached_data.columns]
                    cached_data = cached_data[valid_cols]
                    cache_first_date = _to_date_str(cached_data['date'].min())
                    cache_last_date = _to_date_str(cached_data['date'].max())
                else:
                    cached_data = None
            except Exception as e:
                logging.warning(f"读取缓存失败，将重新获取: {code} - {e}")
                cached_data = None

        # 2. 确定需要拉取的区间
        fetch_ranges = []  # [(start, end), ...]

        if cached_data is not None:
            # 2a. 向前补数据：请求起始日期 < 缓存最早日期
            if date_start < cache_first_date:
                # 从 date_start 拉到缓存最早日期的前一天
                first_date_obj = datetime.datetime.strptime(cache_first_date, "%Y%m%d")
                prev_day = (first_date_obj - datetime.timedelta(days=1)).strftime("%Y%m%d")
                if date_start <= prev_day:
                    fetch_ranges.append((date_start, prev_day))

            # 2b. 尾部追加：缓存最后日期 < 请求结束日期
            if cache_last_date < date_end:
                last_date_obj = datetime.datetime.strptime(cache_last_date, "%Y%m%d")
                next_day = (last_date_obj + datetime.timedelta(days=1)).strftime("%Y%m%d")
                if next_day <= date_end:
                    fetch_ranges.append((next_day, date_end))
        else:
            # 2c. 无缓存，全量拉取
            fetch_ranges.append((date_start, date_end))

        # 3. 执行数据拉取
        all_new_data = []
        for fetch_start, fetch_end in fetch_ranges:
            new_data = _fetch_from_sources(code, fetch_start, fetch_end, adjust)
            if new_data is not None and len(new_data) > 0:
                all_new_data.append(new_data)

        # 4. 合并数据
        parts = []
        if cached_data is not None:
            parts.append(cached_data)
        parts.extend(all_new_data)

        if not parts:
            return None

        if len(parts) == 1:
            combined_data = parts[0]
            # 单部分也需统一 date 列类型（缓存可能含 Timestamp 类型）
            if 'date' in combined_data.columns:
                combined_data['date'] = combined_data['date'].apply(_to_dash_date_safe)
        else:
            combined_data = pd.concat(parts, ignore_index=True)
            # 统一 date 列类型，避免 Timestamp vs str 导致 drop_duplicates 失效
            combined_data['date'] = combined_data['date'].apply(_to_dash_date_safe)
            combined_data = combined_data.drop_duplicates(subset=['date'], keep='last')
            combined_data = combined_data.sort_values(by='date').reset_index(drop=True)

        # 4.5 过滤异常行（防止污染数据写入缓存）
        # 优化：无新数据 + meta 标记已过滤 → 跳过 _filter_ohlc_outliers（节省 ~7ms/stock）
        has_new_data = len(all_new_data) > 0
        if has_new_data:
            # 有新 API 数据混入，必须过滤
            combined_data, n_outliers = _filter_ohlc_outliers(combined_data, code)
        else:
            # 纯缓存数据 — 检查 meta 是否已标记当前版本
            meta = _read_cache_meta(code, adjust)
            if meta is not None and meta.get('filtered_version', 0) >= _FILTER_VERSION:
                n_outliers = 0  # 已过滤，跳过
            else:
                combined_data, n_outliers = _filter_ohlc_outliers(combined_data, code)
                # 即使无异常也更新 meta 版本号（标记已检查，下次跳过）
                if is_cache and n_outliers == 0 and combined_data is not None and len(combined_data) > 0:
                    try:
                        if 'date' in combined_data.columns:
                            last_date = _to_date_str(combined_data['date'].max())
                            _write_cache_meta(code, last_date, adjust, filtered_version=_FILTER_VERSION)
                    except Exception:
                        logging.debug(f"缓存meta写入异常：{code}", exc_info=True)

        # 5. 保存更新后的缓存（有新数据或清除了异常行时写入）
        # 使用原子写入模式（写临时文件 → os.replace）避免并发读取到半写的pickle文件
        need_save = has_new_data or n_outliers > 0
        if is_cache and need_save and combined_data is not None and len(combined_data) > 0:
            tmp_file = cache_file + '.tmp'
            try:
                combined_data.to_pickle(tmp_file, compression="gzip")
                os.replace(tmp_file, cache_file)
                if 'date' in combined_data.columns:
                    last_date = _to_date_str(combined_data['date'].max())
                    _write_cache_meta(code, last_date, adjust, filtered_version=_FILTER_VERSION)
            except Exception as e:
                logging.warning(f"保存缓存失败: {code} - {e}")
                try:
                    if os.path.exists(tmp_file):
                        os.remove(tmp_file)
                except Exception:
                    pass

        # 6. 过滤并返回请求范围内的数据
        result = combined_data[
            (combined_data['date'] >= _to_dash_date(date_start)) &
            (combined_data['date'] <= _to_dash_date(date_end))
        ].copy()

        return result if len(result) > 0 else None

    except Exception as e:
        logging.error(f"stockfetch.stock_hist_cache_incremental处理异常：{code}代码", exc_info=True)
    return None


def clean_expired_cache(expire_days=None):
    """
    智能清理缓存文件：
    1. 删除已退市股票（不在当前股票列表中）的缓存
    2. 删除除权除息后前复权数据已过时的缓存（以便下次运行时重新拉取正确的前复权数据）
    3. 删除损坏的缓存文件（无法解析的 .meta 文件）

    保留策略：
    - 活跃股票的缓存始终保留（历史数据不可变，具有分析价值）
    - 停牌股票的缓存保留（停牌结束后可继续增量更新）
    - 长假期间的缓存保留（不因未更新而误删）

    参数：
        expire_days: 兼容参数，不再使用（保留以避免调用方报错）
    """
    # 获取当前全部A股代码集合（包含停牌股，不过滤价格）
    # 注意：不能使用 fetch_stocks()，因为它会用 is_open 过滤掉停牌股（价格为NaN），
    #       导致停牌股被误判为退市而删除缓存
    active_codes = set()
    try:
        raw_data = she.stock_zh_a_spot_em()
        if raw_data is not None and len(raw_data) > 0:
            # 东方财富返回的列中，'代码'列（f12字段）包含股票代码
            if '代码' in raw_data.columns:
                code_col = '代码'
            else:
                logging.warning("clean_expired_cache: 代码列未找到，跳过退市清理")
                active_codes = set()
                code_col = None
            if code_col is not None:
                all_codes = raw_data[code_col].astype(str).tolist()
                # 只保留A股代码
                active_codes = set(c for c in all_codes if is_a_stock(c))
                logging.info(f"获取到 {len(active_codes)} 只A股代码（含停牌股）")
        else:
            logging.warning("无法获取股票列表，跳过退市股票清理（避免误删）")
    except Exception as e:
        logging.warning(f"获取股票列表失败，跳过退市股票清理：{e}")

    # 获取近期除权除息的股票代码及其除权日（需要刷新前复权缓存）
    # 关键修复：避免在35天窗口内"每天重复删除同一只股票缓存"。
    # 删除条件下移到逐文件判定：仅当「除权已发生 且 缓存生成于除权日前」时删一次。
    bonus_exdiv_map = {}  # {code: ex_dividend_date(datetime.date)}
    try:
        bonus_data = fetch_stocks_bonus(None)
        if bonus_data is not None and len(bonus_data) > 0:
            # 只筛选除权除息日在最近35天内的股票（即上个月内已实施除权的）
            cutoff_date = (datetime.datetime.now() - datetime.timedelta(days=35)).strftime("%Y-%m-%d")
            ex_div_col = 'ex_dividend_date'
            if ex_div_col in bonus_data.columns:
                recent_bonus = bonus_data[
                    bonus_data[ex_div_col].notna() &
                    (bonus_data[ex_div_col].astype(str) >= cutoff_date)
                ]
                if len(recent_bonus) > 0:
                    # 每只股票保留最新的除权日（同一窗口内可能有多条记录）
                    _tmp = recent_bonus[['code', ex_div_col]].copy()
                    _tmp[ex_div_col] = pd.to_datetime(_tmp[ex_div_col], errors='coerce').dt.date
                    _tmp = _tmp.dropna(subset=[ex_div_col])
                    if len(_tmp) > 0:
                        _tmp = _tmp.sort_values(ex_div_col).drop_duplicates(subset=['code'], keep='last')
                        bonus_exdiv_map = {str(r['code']): r[ex_div_col] for _, r in _tmp.iterrows()}
            if bonus_exdiv_map:
                logging.info(f"发现 {len(bonus_exdiv_map)} 只近期已除权除息的股票")
    except Exception:
        logging.debug("获取除权除息数据异常，不影响缓存清理", exc_info=True)  # 获取失败不影响清理

    delisted_count = 0
    bonus_count = 0
    corrupt_count = 0

    try:
        for root, dirs, files in os.walk(stock_hist_cache_path):
            # 跳过 index/ 子目录 — 指数缓存不属于A股，不应被退市清理删除
            dirs[:] = [d for d in dirs if d != 'index']
            for file in files:
                if not file.endswith('.meta'):
                    continue

                meta_path = os.path.join(root, file)

                # 从文件名提取股票代码（格式：000001qfq.meta）
                code = None
                adjust = ''
                try:
                    base_name = file.replace('.meta', '')
                    # 代码为6位数字
                    if len(base_name) >= 6 and base_name[:6].isdigit():
                        code = base_name[:6]
                        adjust = base_name[6:]  # 如 'qfq', 'hfq', ''
                except Exception:
                    logging.debug(f"解析缓存文件名异常：{file}", exc_info=True)

                if code is None:
                    # 文件名格式无法解析，视为损坏文件
                    _remove_cache_pair(meta_path)
                    corrupt_count += 1
                    continue

                # 1. 清理退市股票缓存
                if active_codes and code not in active_codes:
                    _remove_cache_pair(meta_path)
                    delisted_count += 1
                    continue

                # 2. 清理有除权除息的股票的前复权缓存（以便重新拉取正确数据）
                # 仅在「除权已发生 且 缓存在除权日前生成」时删除一次，避免：
                #   (a) 未来已公告未执行的除权：qfq 调整因子尚未变化，旧缓存仍正确，不应删；
                #   (b) 已在除权日当天/之后重建的缓存：已是正确调整，不重复删。
                # 新鲜度判定用 meta 的 update_time（本程序写入，比文件系统 mtime 更可靠）。
                if code in bonus_exdiv_map and adjust == 'qfq':
                    ex_div_date = bonus_exdiv_map.get(code)
                    today = datetime.date.today()
                    should_remove = False
                    # 仅当除权除息日已到达（<= 今天）才需要刷新前复权缓存
                    if ex_div_date is not None and ex_div_date <= today:
                        meta = _read_cache_meta(code, adjust)
                        cache_refreshed = False
                        ut = str(meta['update_time']) if (meta and meta.get('update_time')) else ''
                        if len(ut) >= 8:
                            try:
                                cache_update_date = datetime.datetime.strptime(ut[:8], "%Y%m%d").date()
                                # 缓存在除权日当天或之后写入 → 已含正确调整，无需再删
                                cache_refreshed = cache_update_date >= ex_div_date
                            except ValueError:
                                cache_refreshed = False
                        should_remove = not cache_refreshed

                    if should_remove:
                        _remove_cache_pair(meta_path)
                        bonus_count += 1
                        continue

    except Exception as e:
        logging.error(f"清理缓存失败", exc_info=True)

    total = delisted_count + bonus_count + corrupt_count
    if total > 0:
        logging.info(
            f"缓存清理完成：退市股票 {delisted_count} 个，"
            f"除权除息刷新 {bonus_count} 个，"
            f"损坏文件 {corrupt_count} 个，"
            f"共清理 {total} 个"
        )
    else:
        logging.info("缓存清理完成：无需清理")

    return total


def _remove_cache_pair(meta_path):
    """删除缓存文件对（.meta + .gzip.pickle）"""
    try:
        cache_file = meta_path.replace('.meta', '.gzip.pickle')
        if os.path.exists(cache_file):
            os.remove(cache_file)
        if os.path.exists(meta_path):
            os.remove(meta_path)
    except Exception as e:
        logging.warning(f"删除缓存文件失败: {meta_path} - {e}")


# 保留原有函数以兼容旧代码
def stock_hist_cache(code, date_start, date_end=None, is_cache=True, adjust=''):
    """
    兼容旧版本的缓存函数，内部调用增量更新版本
    """
    if date_end is None:
        date_end = datetime.datetime.now().strftime("%Y%m%d")
    return stock_hist_cache_incremental(code, date_start, date_end, is_cache, adjust)


def update_all_caches(stocks, date_start, date_end, workers=2, spot_df=None):
    """
    批量更新所有股票的缓存文件（仅更新缓存，不保留在内存中）

    与 stock_hist_data 的区别：
    - stock_hist_data: 全部加载到内存的 dict 中（~1.6GB），供后续分析直接读取
    - update_all_caches: 仅触发增量缓存更新，处理完每只股票即释放内存

    核心优化 — Spot快速追加（spot_df 不为 None 时启用）：
    使用批量实时行情数据(1-2次API)替代逐股历史API调用，大幅减少请求数。
    仅当缓存恰好差1天数据时生效，其他情况回退到传统API获取。

    安全机制：
    - 除权除息检测：比较 spot 昨收价 vs 缓存最后收盘价，差异过大则删除缓存全量重取
    - 停牌跳过：当日成交量为0的股票无新K线数据，直接跳过
    - 缓存损坏：读取失败自动回退到API

    5层限流防护策略：
    第1层 - 控制并发：服务器默认 3 线程（本地 6，最大 4/12），可通过环境变量 QUANTIA_KLINE_CACHE_WORKERS 配置
    第2层 - 请求间隔：每次 API 请求后等待（可通过环境变量配置）
    第3层 - 批次冷却：每 N 只股票暂停（可通过环境变量配置）
    第4层 - 限流检测：连续 N 次失败即触发暂停，渐进退避
    第5层 - 熔断保护：累计 N 次限流后终止任务，恢复后自动降速

    本地 vs 服务器环境配置：
    - 本地环境（QUANTIA_LOCAL_MODE=1）：高并发、少延迟、大内存
    - 服务器环境（默认）：低并发、多延迟、小内存防OOM

    参数：
        stocks: 股票列表 [(date, code), ...]
        date_start: 起始日期 YYYYMMDD
        date_end: 结束日期 YYYYMMDD
        workers: 并发线程数（服务器默认3，本地默认6，可通过环境变量覆盖）
        spot_df: 实时行情DataFrame（来自 stock_data().get_data()），
                 包含全市场当日OHLCV数据，用于快速追加模式
    返回：
        (success_count, fail_count)
    """
    import threading

    # ── 本地/服务器环境自适应配置 ──
    # 本地模式：高并发、少延迟、大内存（不用担心OOM）
    # 服务器模式：低并发、多延迟、小内存防OOM
    IS_LOCAL_MODE = _cfg.get_bool('QUANTIA_LOCAL_MODE', False)

    if IS_LOCAL_MODE:
        # 本地模式：更激进的配置
        DEFAULT_WORKERS = 6              # 本地默认6线程
        MAX_WORKERS = 12                 # 本地最大12线程
        REQUEST_DELAY = (0.2, 0.5)       # 本地请求间隔更短
        BATCH_PAUSE_SECONDS = (2, 4)     # 本地暂停时间更短
        CONSECUTIVE_FAIL_THRESHOLD = 5   # 本地容忍更多失败
        BASE_THROTTLE_PAUSE = 60         # 本地限流暂停更短
        MAX_THROTTLE_COUNT = 5           # 本地容忍更多限流
        CHUNK_SIZE = 300                 # 本地更大的批次
        logging.info("K线缓存更新：本地模式（高并发、少延迟）")
    else:
        # 服务器模式：平衡配置（优先避免超时，同时保留限流/熔断保护）
        DEFAULT_WORKERS = 3              # 服务器默认3线程
        MAX_WORKERS = 4                  # 服务器最大4线程
        REQUEST_DELAY = (0.6, 1.5)       # 服务器请求间隔适度放宽吞吐
        BATCH_PAUSE_SECONDS = (5, 10)    # 服务器批次暂停缩短，降低总耗时
        CONSECUTIVE_FAIL_THRESHOLD = 4   # 服务器容忍少量瞬时失败，避免过早退避
        BASE_THROTTLE_PAUSE = 90         # 服务器限流暂停保守但不过长
        MAX_THROTTLE_COUNT = 4           # 服务器允许更多次限流恢复
        CHUNK_SIZE = 150                 # 服务器批次略增，减少批间停顿占比

    # 允许通过环境变量覆盖默认值
    workers = _cfg.get_int('QUANTIA_KLINE_CACHE_WORKERS', workers if workers > 2 else DEFAULT_WORKERS)
    REQUEST_DELAY_MIN = _cfg.get_float('QUANTIA_KLINE_REQUEST_DELAY_MIN', REQUEST_DELAY[0])
    REQUEST_DELAY_MAX = _cfg.get_float('QUANTIA_KLINE_REQUEST_DELAY_MAX', REQUEST_DELAY[1])
    BATCH_PAUSE_MIN = _cfg.get_float('QUANTIA_KLINE_BATCH_PAUSE_MIN', BATCH_PAUSE_SECONDS[0])
    BATCH_PAUSE_MAX = _cfg.get_float('QUANTIA_KLINE_BATCH_PAUSE_MAX', BATCH_PAUSE_SECONDS[1])
    CHUNK_SIZE = _cfg.get_int('QUANTIA_KLINE_CHUNK_SIZE', CHUNK_SIZE)

    success = 0
    fail = 0
    skip = 0                           # 缓存已最新，无需请求API
    spot_appended = 0                  # 通过Spot快速追加更新（零API调用）
    suspended_skip = 0                 # 停牌股跳过
    exrights_refetch = 0               # 除权除息全量重取
    consecutive_fails = 0              # 连续失败计数（用于检测限流）
    throttle_count = 0                 # 限流暂停累计触发次数
    _lock = threading.Lock()           # 保护所有共享计数器
    _throttle_event = threading.Event()  # 限流暂停信号
    _throttle_event.set()              # 初始状态：不暂停
    _abort = False                     # 熔断标志

    # 自适应请求延迟（每次限流恢复后自动加大 50%，上限 5-8 秒）
    request_delay = [REQUEST_DELAY_MIN, REQUEST_DELAY_MAX]
    batch_pause_seconds = (BATCH_PAUSE_MIN, BATCH_PAUSE_MAX)

    # ── Spot快速追加配置 ──
    # 使用批量行情数据(1-2次API调用)直接追加到缓存，替代逐股API调用
    # 可将每日增量更新从 ~5000次 降低到 <100次 API调用
    SPOT_APPEND_ENABLED = _cfg.get_bool('QUANTIA_SPOT_APPEND_ENABLED', True) and spot_df is not None
    SKIP_SUSPENDED = _cfg.get_bool('QUANTIA_SKIP_SUSPENDED', True)
    EXRIGHTS_THRESHOLD = _cfg.get_float('QUANTIA_EXRIGHTS_THRESHOLD', 0.01)  # 1%差异视为除权

    # ── Spot数据时效性安全检查 ──
    # spot API (stock_zh_a_spot_em) 始终返回当前实时行情，而非历史数据。
    # 仅当以下条件同时满足时，spot数据才可安全用于日K缓存追加：
    #   1. date_end 是今天（spot数据对应的日期必须匹配目标日期）
    #   2. 当天A股市场已收盘（>= 15:00），数据代表完整的日K
    #
    # 危险场景 — 盘中运行：
    #   spot数据是不完整的盘中快照（如14:00的价格/成交量），追加后meta会标记
    #   该日期为已更新。收盘后重运行时meta检查通过（last_date >= date_end），
    #   导致跳过该股票，缓存中永久保留错误的盘中数据。
    #   传统API路径(stock_zh_a_hist)不受影响，因为K线API只返回已完成交易日数据。
    #
    # 危险场景 — 手动指定历史日期：
    #   python kline_cache_daily_job.py 2026-03-10 时，spot API返回的是今天的
    #   实时数据而非3月10日的数据，用于追加会写入错误的OHLCV。
    if SPOT_APPEND_ENABLED:
        _now = datetime.datetime.now()
        _today_str = _now.strftime("%Y%m%d")

        if date_end != _today_str:
            # date_end 不是今天 — 两种情况：
            # (a) 凌晨运行，date_end 是前一交易日 → spot 数据有效（收盘后 API 返回完整日K）
            # (b) 手动指定历史日期或周末补跑 → spot 数据不匹配，必须禁用
            _prev_trade_date = trd.get_previous_trade_date(_now.date())
            _prev_trade_str = _prev_trade_date.strftime("%Y%m%d")
            if date_end == _prev_trade_str and _now.hour < 9:
                # 凌晨执行前一交易日任务：市场已收盘，spot 数据对应 date_end
                logging.info(
                    f"Spot快速追加：date_end({date_end}) 是前一交易日，"
                    f"当前凌晨 {_now.strftime('%H:%M')}，市场已收盘，spot数据有效"
                )
            else:
                SPOT_APPEND_ENABLED = False
                logging.info(
                    f"Spot快速追加已禁用：date_end({date_end}) ≠ 今天({_today_str})，"
                    f"spot数据不匹配目标日期，回退到传统API模式"
                )
        elif not trd.is_close(_now):
            # 市场未收盘：spot数据是不完整的盘中快照，不可用于日K缓存追加
            SPOT_APPEND_ENABLED = False
            logging.info(
                f"Spot快速追加已禁用：A股市场尚未收盘（当前 {_now.strftime('%H:%M')}），"
                f"spot数据不完整，回退到传统API模式"
            )

    # 预处理 spot 数据，建立 code → row 的快速索引
    spot_indexed = None
    prev_trade_date_str = None
    if SPOT_APPEND_ENABLED:
        try:
            spot_indexed = spot_df.set_index('code')
            # 计算前一个交易日（用于判断缓存是否恰好差1天）
            date_end_obj = datetime.datetime.strptime(date_end, "%Y%m%d").date()
            prev_trade_date = trd.get_previous_trade_date(date_end_obj)
            prev_trade_date_str = prev_trade_date.strftime("%Y%m%d")
            logging.info(
                f"Spot快速追加已启用：{len(spot_indexed)} 只股票，"
                f"前一交易日={prev_trade_date_str}，除权阈值={EXRIGHTS_THRESHOLD:.1%}"
            )
        except Exception as e:
            logging.warning(f"Spot数据预处理失败，将回退到API模式: {e}")
            SPOT_APPEND_ENABLED = False
            spot_indexed = None

    def _update_one(stock):
        """
        更新单只股票的缓存。

        返回值：
            'skip'  — 缓存已最新，无需任何操作
            'spot'  — 通过Spot快速追加完成（零API调用）
            'suspended' — 停牌股跳过
            True    — API调用成功
            False   — API调用失败
        """
        nonlocal consecutive_fails, exrights_refetch
        code = stock[1]

        # 熔断检查：任务已终止则立即返回
        if _abort:
            return False

        # 预检查：缓存已最新则跳过（零延迟，不发起任何API请求）
        meta = _read_cache_meta(code, 'qfq')
        if meta and meta.get('last_date') and meta['last_date'] >= date_end:
            return 'skip'

        # ── Spot快速追加路径（核心优化）──
        # 条件：spot数据可用 + 缓存恰好差1天 + 股票当日有交易
        if SPOT_APPEND_ENABLED and spot_indexed is not None:
            try:
                if code in spot_indexed.index:
                    spot_row = spot_indexed.loc[code]
                    # 处理 set_index 后可能返回 DataFrame（重复代码）的情况
                    if isinstance(spot_row, pd.DataFrame):
                        spot_row = spot_row.iloc[0]

                    stock_volume = float(spot_row.get('volume', 0) or 0)
                    stock_price = float(spot_row.get('new_price', 0) or 0)

                    # 停牌检测：当日无成交或无价格 → 无新K线数据可追加
                    if SKIP_SUSPENDED and (stock_volume == 0 or stock_price == 0):
                        return 'suspended'

                    # 仅当缓存恰好差1天时可用spot追加
                    if meta and meta.get('last_date') and meta['last_date'] == prev_trade_date_str:
                        result = _try_spot_append(code, spot_row, date_end, EXRIGHTS_THRESHOLD)
                        if result == 'success':
                            return 'spot'
                        elif result == 'exrights':
                            # 除权除息：删除缓存，后续走API全量获取
                            _delete_cache(code, 'qfq')
                            with _lock:
                                exrights_refetch += 1
                            logging.info(f"除权除息已清理缓存: {code}，将全量重新获取")
                            # 继续向下走API路径
                        # else: 'error' — 回退到API路径
                else:
                    # 不在spot数据中（可能已退市或非A股），跳过
                    if SKIP_SUSPENDED:
                        return 'suspended'
            except Exception as e:
                logging.debug(f"Spot快速追加预检查异常: {code} - {e}")
                # 异常不影响，回退到API路径

        # ── 传统API获取路径 ──
        # 等待限流暂停恢复
        _throttle_event.wait()

        if _abort:
            return False

        try:
            data = stock_hist_cache_incremental(code, date_start, date_end, is_cache=True, adjust='qfq')
            ok = data is not None and len(data) > 0
            if ok:
                with _lock:
                    consecutive_fails = 0  # 成功时重置连续失败计数
            # 实际发起了API请求，添加请求间隔防限流
            if not _abort:
                time.sleep(random.uniform(request_delay[0], request_delay[1]))
            return ok
        except Exception as e:
            logging.error(f"update_all_caches处理异常：{code} -", exc_info=True)
            if not _abort:
                time.sleep(random.uniform(request_delay[0], request_delay[1]))
            return False

    # 限制并发数，避免过多线程同时请求 API
    workers = min(workers, MAX_WORKERS)

    # ── 分批提交（时间换空间）──
    # 关键优化：不再一次性创建 ~4900 个 Future 对象，改为每批提交 CHUNK_SIZE 只
    # 每批处理完后 gc.collect()，避免 Future/结果对象在内存中累积
    # CHUNK_SIZE 已在函数开头根据本地/服务器模式配置

    try:
        processed_total = 0
        api_processed = 0  # 实际发起 API 请求的累计数量

        for chunk_start in range(0, len(stocks), CHUNK_SIZE):
            chunk_api_count = 0  # 本批次实际 API 请求数（用于判断是否需要批次暂停）
            if _abort:
                break

            chunk = stocks[chunk_start:chunk_start + CHUNK_SIZE]

            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                future_to_stock = {executor.submit(_update_one, stock): stock for stock in chunk}
                try:
                    for future in concurrent.futures.as_completed(future_to_stock):
                        if _abort:
                            break

                        try:
                            result = future.result()
                            if result == 'skip':
                                skip += 1
                            elif result == 'spot':
                                spot_appended += 1
                            elif result == 'suspended':
                                suspended_skip += 1
                            elif result:
                                success += 1
                                api_processed += 1
                                chunk_api_count += 1
                            else:
                                fail += 1
                                api_processed += 1
                                chunk_api_count += 1
                                # 限流检测：连续失败达到阈值时触发暂停
                                should_throttle = False
                                pause_time = 0
                                with _lock:
                                    consecutive_fails += 1
                                    # 仅当未处于限流暂停状态时才触发新的暂停
                                    if consecutive_fails >= CONSECUTIVE_FAIL_THRESHOLD and _throttle_event.is_set():
                                        throttle_count += 1
                                        pause_time = BASE_THROTTLE_PAUSE * (2 ** (throttle_count - 1))

                                        if throttle_count >= MAX_THROTTLE_COUNT:
                                            logging.error(
                                                f"限流已触发 {throttle_count} 次，疑似 IP 被封禁，"
                                                f"终止任务以避免进一步封禁。"
                                                f"当前进度：API成功={success}, 失败={fail}, "
                                                f"Spot追加={spot_appended}, 跳过={skip}, 停牌={suspended_skip}"
                                            )
                                            _abort = True
                                            break

                                        should_throttle = True
                                        _throttle_event.clear()  # 阻塞所有工作线程

                                if should_throttle:
                                    logging.warning(
                                        f"连续 {CONSECUTIVE_FAIL_THRESHOLD} 次获取失败，"
                                        f"第{throttle_count}次触发限流保护，暂停 {pause_time} 秒..."
                                    )
                                    time.sleep(pause_time)
                                    with _lock:
                                        consecutive_fails = 0
                                        # 恢复后自动降速：请求间隔加大 50%（上限 5-8 秒）
                                        request_delay[0] = min(request_delay[0] * 1.5, 5.0)
                                        request_delay[1] = min(request_delay[1] * 1.5, 8.0)
                                    _throttle_event.set()  # 恢复所有工作线程
                                    logging.info(
                                        f"限流暂停结束，恢复请求。"
                                        f"请求间隔已调整为 {request_delay[0]:.1f}-{request_delay[1]:.1f} 秒"
                                    )

                        except Exception as e:
                            fail += 1
                            api_processed += 1
                            chunk_api_count += 1
                            stock = future_to_stock[future]
                            logging.error(f"update_all_caches处理异常：{stock[1]} -", exc_info=True)

                        processed_total += 1
                except KeyboardInterrupt:
                    logging.warning(
                        f"用户中断(Ctrl+C)，正在取消剩余任务... "
                        f"当前进度：API成功={success}, 失败={fail}, "
                        f"Spot追加={spot_appended}, 跳过={skip}, 停牌={suspended_skip}"
                    )
                    _abort = True
                    for f in future_to_stock:
                        f.cancel()

            # ── 批次间隔：GC + 冷却暂停 ──
            # ThreadPoolExecutor 上下文退出后，本批所有线程/Future 已释放
            gc.collect()
            remaining = len(stocks) - processed_total
            if remaining > 0 and not _abort and chunk_api_count > 0:
                # 仅在本批有实际API请求时才暂停（全部skip/spot的批次无需暂停）
                pause = random.uniform(*batch_pause_seconds)
                logging.info(
                    f"已处理 {processed_total}/{len(stocks)}"
                    f"（API成功={success}, 失败={fail}, Spot追加={spot_appended}, "
                    f"跳过={skip}, 停牌={suspended_skip}），"
                    f"暂停 {pause:.0f} 秒，剩余 {remaining}"
                )
                time.sleep(pause)
    except KeyboardInterrupt:
        logging.warning(
            f"用户中断(Ctrl+C)，缓存更新已停止。"
            f"当前进度：API成功={success}, 失败={fail}, "
            f"Spot追加={spot_appended}, 跳过={skip}, 停牌={suspended_skip}"
        )
    except Exception as e:
        logging.error(f"update_all_caches处理异常", exc_info=True)

    logging.info(
        f"缓存更新完成：API成功={success}, 失败={fail}, "
        f"Spot快速追加={spot_appended}, 缓存已最新={skip}, "
        f"停牌跳过={suspended_skip}, 除权重取={exrights_refetch}, "
        f"限流触发={throttle_count}次, "
        f"实际API调用={api_processed}次"
    )

    return success + skip + spot_appended + suspended_skip, fail


def update_all_etf_caches(date_start=None, date_end=None, etf_spot_df=None):
    """
    批量更新所有 ETF 的历史 K 线缓存（复用 update_all_caches 的限流/熔断/增量逻辑）。

    与股票缓存的区别：
    - 股票列表来自实时行情 API（stock_data 单例）；
      ETF 列表/行情读取自数据库 cn_etf_spot 的最新交易日（fetch_daily_job 已入库），
      避免额外 API 调用，并保持 Fetch/Analysis 管道分离。
    - ETF 代码以 1/5 开头，三个数据源(东财/腾讯/新浪)的 secid 路由均已支持，
      逐 ETF 走 stock_hist_cache_incremental 与股票一致。
    - cn_etf_spot 含 _try_spot_append 所需全部列（new_price/open_price/high_price/
      low_price/volume/deal_amount/change_rate/ups_downs/turnoverrate/pre_close_price），
      仅缺 amplitude（_try_spot_append 已对缺失列默认 0），故 Spot 快速追加同样可用。

    参数：
        date_start: 起始日期 YYYYMMDD，None 时取 HIST_DATA_DEFAULT_YEARS 年前
        date_end:   结束日期 YYYYMMDD，None 时取今天
        etf_spot_df: 可选，已加载的 ETF 实时行情 DataFrame（须含 code 及 OHLCV 列）。
                     None 时从 cn_etf_spot 最新交易日读取。

    返回：
        (success_count, fail_count)
    """
    import quantia.lib.database as mdb

    if date_end is None:
        date_end = datetime.datetime.now().strftime("%Y%m%d")
    if date_start is None:
        _years = HIST_DATA_DEFAULT_YEARS
        start_dt = datetime.datetime.now() - datetime.timedelta(days=_years * 365)
        date_start = start_dt.strftime("%Y%m%d")

    # 从数据库读取最新交易日的 ETF 行情（仅读 DB，无 API 调用）
    if etf_spot_df is None:
        if not mdb.checkTableIsExist('cn_etf_spot'):
            logging.warning("update_all_etf_caches：cn_etf_spot 表不存在，跳过 ETF 缓存更新")
            return 0, 0
        try:
            sql = (
                "SELECT `date`, `code`, `new_price`, `open_price`, `high_price`, "
                "`low_price`, `volume`, `deal_amount`, `change_rate`, `ups_downs`, "
                "`turnoverrate`, `pre_close_price` "
                "FROM `cn_etf_spot` "
                "WHERE `date` = (SELECT MAX(`date`) FROM `cn_etf_spot`) "
                "AND `new_price` > 0 "
                "ORDER BY `code`"
            )
            etf_spot_df = pd.read_sql(sql, mdb.engine())
        except Exception as e:
            logging.error(f"update_all_etf_caches：读取 cn_etf_spot 失败：{e}", exc_info=True)
            return 0, 0

    if etf_spot_df is None or len(etf_spot_df) == 0:
        logging.warning("update_all_etf_caches：cn_etf_spot 无可用数据，跳过 ETF 缓存更新")
        return 0, 0

    # 构造 (date, code) 列表，复用股票缓存批处理逻辑
    etf_stocks = [(date_end, str(code)) for code in etf_spot_df['code'].tolist()]
    logging.info(f"update_all_etf_caches：开始更新 {len(etf_stocks)} 只 ETF 的 K 线缓存")

    return update_all_caches(etf_stocks, date_start, date_end,
                             workers=_cfg.get_int('QUANTIA_KLINE_CACHE_WORKERS', 2),
                             spot_df=etf_spot_df)


def read_hist_from_cache(data_base, years=None):
    """
    从缓存读取历史数据（Web层专用，零API调用）。

    与 fetch_stock_hist / fetch_etf_hist 接口兼容（接受 (date, code) 元组），
    但绝不发起外部 API 请求。适用于：
    - Web handler 展示 K 线 / 指标
    - 任何需要"只读缓存、缺失则报告"的场景

    缺失数据时返回 None 并写 warning 日志。
    """
    date = data_base[0]
    code = data_base[1]
    if years is None:
        years = HIST_DATA_DEFAULT_YEARS
    date_start, _ = trd.get_trade_hist_interval(date, years)
    if isinstance(date, str):
        date_end = date.replace("-", "")
    else:
        date_end = date.strftime("%Y%m%d")
    data = read_stock_hist_from_cache(code, date_start, date_end)
    if data is None:
        logging.warning(f"read_hist_from_cache: {code} 缓存无数据（{date_start}~{date_end}），"
                        f"请确认 fetch_daily_job 已正常运行")
    return data


def _filter_ohlc_outliers(data, code=''):
    """
    过滤 OHLC 异常行：检测并移除价格与相邻行严重偏离的数据点（向量化实现）。

    已知问题：某些缓存文件中混入了月度聚合数据（来源不明），
    表现为月末最后一个交易日的 OHLC 值偏离正常价格，
    且 volume 异常大（为月度成交量总和）。此函数可安全移除这类异常行。

    检测逻辑（三重检测，命中任一即标记）：
    1. 价格+成交量联合检测：close 偏离邻居中位数 >25% 且 volume > 邻居中位数 3 倍
    2. 极端价格偏离：close 偏离邻居中位数 >60%（无论 volume）
    3. 无效价格：close <= 0

    安全阀：异常行不超过总行数 15% 时才执行过滤。

    返回值：(filtered_data, n_outliers_removed)
        - filtered_data: 过滤后的 DataFrame
        - n_outliers_removed: 被移除的异常行数（0 表示无变化）
    """
    if data is None or len(data) < 10:
        return data, 0

    try:
        close = pd.to_numeric(data['close'], errors='coerce')
        volume = pd.to_numeric(data.get('volume', pd.Series(dtype='float64')), errors='coerce')
        if close.isna().all():
            return data, 0

        # --- 向量化：取 ±2 位置的邻居（排除自身）计算中位数 ---
        # 与原始 for 循环逻辑完全一致：neighbor_idx = [i-2, i-1, i+1, i+2]
        c_m2 = close.shift(2)    # 邻居 i-2
        c_m1 = close.shift(1)    # 邻居 i-1
        c_p1 = close.shift(-1)   # 邻居 i+1
        c_p2 = close.shift(-2)   # 邻居 i+2
        neighbor_close = pd.DataFrame({'a': c_m2, 'b': c_m1, 'c': c_p1, 'd': c_p2})
        # 要求至少 2 个有效邻居（与原始 len(neighbor_closes) < 2 一致）
        neighbor_median_close = neighbor_close.median(axis=1, skipna=True)
        neighbor_count = neighbor_close.notna().sum(axis=1)
        has_enough_neighbors = neighbor_count >= 2

        v_m2 = volume.shift(2)
        v_m1 = volume.shift(1)
        v_p1 = volume.shift(-1)
        v_p2 = volume.shift(-2)
        neighbor_vol = pd.DataFrame({'a': v_m2, 'b': v_m1, 'c': v_p1, 'd': v_p2})
        neighbor_median_vol = neighbor_vol.median(axis=1, skipna=True)
        neighbor_vol_count = neighbor_vol.notna().sum(axis=1)
        has_enough_vol_neighbors = neighbor_vol_count >= 2

        # 价格比率：当前值 / 邻居中位数（排除自身）
        safe_median = neighbor_median_close.replace(0, np.nan)
        safe_median = safe_median.where(safe_median > 0, np.nan)
        price_ratio = close / safe_median

        # 检测 3：无效价格（负数或零），且邻居有正常正价格
        # 注意：前复权（qfq）小盘股可能出现大片 close<=0 的合法数据，
        # 只有邻居价格正常时才视为异常（与原始算法行为一致）
        invalid_price = (close <= 0) & has_enough_neighbors & (neighbor_median_close > 0)

        # 检测 2：极端价格偏离 >60%（ratio < 0.4 或 > 2.5）
        extreme_deviation = has_enough_neighbors & ((price_ratio < 0.4) | (price_ratio > 2.5))

        # 检测 1：价格偏离 >25% + 成交量异常 >3x
        price_deviated = has_enough_neighbors & ((price_ratio < 0.75) | (price_ratio > 1.33))
        safe_vol_median = neighbor_median_vol.replace(0, np.nan)
        vol_ratio = volume / safe_vol_median
        vol_abnormal = has_enough_vol_neighbors & (vol_ratio > 3.0)
        joint_detection = price_deviated & vol_abnormal

        # 合并所有检测结果
        outlier_mask = invalid_price | extreme_deviation | joint_detection
        # NaN 处理：边缘位置的 NaN 不应被标记为异常
        outlier_mask = outlier_mask.fillna(False)

        n_outliers = int(outlier_mask.sum())
        if n_outliers > 0 and n_outliers < len(data) * 0.15:  # 异常行不超过15%才过滤
            outlier_dates = data.loc[outlier_mask, 'date'].tolist()
            logging.warning(
                f"_filter_ohlc_outliers: {code} 发现 {n_outliers} 行 OHLC 异常数据已过滤，"
                f"日期: {outlier_dates[:5]}{'...' if n_outliers > 5 else ''}"
            )
            data = data.loc[~outlier_mask].reset_index(drop=True)
            return data, n_outliers

        return data, 0
    except Exception as e:
        logging.warning(f"_filter_ohlc_outliers 异常: {code} - {e}")
        return data, 0


def read_stock_hist_from_cache(code, date_start, date_end):
    """
    从缓存文件读取单只股票的历史数据（流式处理用）

    与 fetch_stock_hist / stock_hist_cache_incremental 的区别：
    - fetch_stock_hist: 触发缓存增量更新 + API 拉取
    - stock_hist_cache_incremental: 读取缓存 + 按需发起 API 拉取
    - read_stock_hist_from_cache: **仅从已有缓存读取，绝不发起 API 请求**

    如果缓存文件不存在或数据为空，返回 None（不会 fallback 到 API）。
    返回的数据已包含 p_change 列和 volume 单位转换（股）。
    """
    try:
        # 标准列名和兼容映射
        _standard_columns = tuple(tbs.CN_STOCK_HIST_DATA['columns'])
        _column_rename_map = {
            'pct_chg': 'quote_change',
            'change': 'ups_downs',
        }
        cache_file = _get_cache_file_path(code, 'qfq')

        if not os.path.isfile(cache_file):
            # 缓存文件不存在 → 尝试从 cn_stock_spot 表构建 K线数据
            data = _fallback_kline_from_spot(code, date_start, date_end)
            if data is not None and len(data) > 0:
                data['p_change'] = tl.ROC(data['close'].values, 1)
                data['p_change'] = data['p_change'].fillna(0.0)
                data = _normalize_volume_to_shares(data)
                return data
            return None

        data = pd.read_pickle(cache_file, compression="gzip")
        if data is None or len(data) == 0 or 'date' not in data.columns:
            return None

        # 统一旧缓存列名
        data = data.rename(columns=_column_rename_map)
        # 合并重复列
        dup_mask = data.columns.duplicated(keep=False)
        if dup_mask.any():
            for col_name in data.columns[dup_mask].unique():
                dup_cols = data.loc[:, data.columns == col_name]
                merged = dup_cols.iloc[:, 0].fillna(dup_cols.iloc[:, 1])
                data = data.loc[:, data.columns != col_name]
                data[col_name] = merged
        # 确保只保留标准列
        valid_cols = [c for c in _standard_columns if c in data.columns]
        data = data[valid_cols]

        # 过滤 OHLC 异常行 — 仅在缓存未经当前版本过滤时执行
        # 若 stock_hist_cache_incremental 已过滤并标记 filtered_version，则跳过
        meta = _read_cache_meta(code, 'qfq')
        already_filtered = (meta is not None and meta.get('filtered_version', 0) >= _FILTER_VERSION)

        if already_filtered:
            n_outliers = 0
        else:
            data, n_outliers = _filter_ohlc_outliers(data, code)
            # 更新 meta 版本号：后续读取可跳过 _filter_ohlc_outliers
            if data is not None and len(data) > 0:
                try:
                    if n_outliers > 0:
                        # 有异常行被清除 → 回写数据 + 更新 meta（原子写入）
                        _tmp = cache_file + '.tmp'
                        data.to_pickle(_tmp, compression="gzip")
                        os.replace(_tmp, cache_file)
                    # 无论是否有异常行，都更新 meta 版本号（标记已检查）
                    last_date = _to_date_str(data['date'].max())
                    _write_cache_meta(code, last_date, 'qfq', filtered_version=_FILTER_VERSION)
                except Exception:
                    logging.debug(f"缓存回写异常：{code}", exc_info=True)  # 回写失败不影响正常读取

        # 按请求日期范围过滤
        data_dates = data['date'].apply(_to_date_str)
        mask = (data_dates >= date_start) & (data_dates <= date_end)
        data = data.loc[mask].copy()

        if len(data) == 0:
            return None

        # ── DB 回填：缓存不含目标日期时，从 cn_stock_spot 补充当日行情 ──
        # 场景：Phase 2（K线缓存更新）因 OOM 被杀，缓存停留在前一天，
        # 但 Phase 1 已成功入库当日 cn_stock_spot 行情。
        # 此处从 DB 读取当日行情并追加到缓存 DataFrame，使分析能产出当日指标。
        try:
            data_max_str = _to_date_str(data['date'].max())
            if data_max_str < date_end:
                _spot_row = _backfill_from_spot(code, date_end)
                if _spot_row is not None:
                    # 保留与缓存相同的列
                    valid_cols = [c for c in data.columns if c in _spot_row.columns]
                    _spot_row = _spot_row[valid_cols]
                    data = pd.concat([data, _spot_row], ignore_index=True)
                    # 统一 date 类型并去重，防止 Timestamp vs str 导致重复行
                    data['date'] = data['date'].apply(_to_dash_date_safe)
                    data = data.drop_duplicates(subset=['date'], keep='last').reset_index(drop=True)
                    logging.debug(f"DB回填：{code} 补充 {_to_dash_date(date_end)} 行情（来自 cn_stock_spot）")
        except Exception as e:
            logging.debug(f"DB回填异常（不影响已有数据）：{code} - {e}")

        # 添加 p_change 列
        data['p_change'] = tl.ROC(data['close'].values, 1)
        data['p_change'] = data['p_change'].fillna(0.0)
        # 成交量自适应规范化为"股"（兼容历史 "股" 段 + 新 "手" 段混存的缓存）
        data = _normalize_volume_to_shares(data)
        return data
    except Exception as e:
        logging.error(f"read_stock_hist_from_cache处理异常：{code} -", exc_info=True)
    return None


def _backfill_from_spot(code, date_end_yyyymmdd):
    """
    从 cn_stock_spot 表读取指定日期的行情，转换为 K线缓存兼容的格式。

    cn_stock_spot 列名与 K线缓存列名的映射：
      new_price → close, open_price → open, high_price → high, low_price → low
      volume → volume（单位：股，缓存中是手，需要 /100）
      deal_amount → amount, amplitude → amplitude
      change_rate → quote_change, ups_downs → ups_downs
      turnoverrate → turnover

    Returns:
        pd.DataFrame | None: 包含一行的 DataFrame（与缓存列名兼容），或 None
    """
    try:
        import quantia.lib.database as mdb
        date_dash = _to_dash_date(date_end_yyyymmdd)
        if not mdb.checkTableIsExist('cn_stock_spot'):
            return None
        sql = (
            "SELECT `date`, `new_price` AS `close`, `open_price` AS `open`, "
            "`high_price` AS `high`, `low_price` AS `low`, "
            "`volume` / 100 AS `volume`, `deal_amount` AS `amount`, "
            "`amplitude`, `change_rate` AS `quote_change`, "
            "`ups_downs`, `turnoverrate` AS `turnover` "
            "FROM `cn_stock_spot` WHERE `code` = %s AND `date` = %s LIMIT 1"
        )
        df = pd.read_sql(sql, mdb.engine(), params=(code, date_dash))
        if df is not None and len(df) > 0:
            # 过滤无效OHLC，避免注入异常末根（如 open/high/low 为 0 的脏数据）
            for c in ('open', 'close', 'high', 'low'):
                if c in df.columns:
                    df[c] = pd.to_numeric(df[c], errors='coerce')
            valid = (
                (df['open'] > 0) &
                (df['close'] > 0) &
                (df['high'] > 0) &
                (df['low'] > 0)
            )
            if not bool(valid.all()):
                invalid_cnt = int((~valid).sum())
                logging.debug(f"_backfill_from_spot: 过滤 {code} 无效OHLC行 {invalid_cnt} 条")
            df = df.loc[valid].copy()
            if len(df) == 0:
                return None
            # 统一 date 列类型为 Timestamp（与缓存 pickle 中的 datetime64 一致）
            if 'date' in df.columns:
                df['date'] = pd.to_datetime(df['date'])
            return df
    except Exception as e:
        logging.debug(f"_backfill_from_spot 异常：{code} {date_end_yyyymmdd} - {e}")
    return None


def _fallback_kline_from_spot(code, date_start, date_end):
    """
    当缓存文件不存在时，从已入库的每日快照表读取日线行情构建 K线 DataFrame。

    不发起外部 API 请求，仅从已入库数据中提取。优先读 cn_stock_spot（A股）；
    若无数据（如 ETF 代码 159xxx/51xxx 不在 cn_stock_spot），回退读 cn_etf_spot。
    两表 volume 均为"股"，统一 /100 后由 _normalize_volume_to_shares 按
    amount/(close*volume) 比值还原为股（与 cn_stock_spot 路径一致）。
    cn_etf_spot 无 amplitude 列，故 ETF 分支不取该列。
    """
    try:
        import quantia.lib.database as mdb
        date_start_dash = _to_dash_date(date_start) if len(date_start) == 8 else date_start
        date_end_dash = _to_dash_date(date_end) if len(date_end) == 8 else date_end

        def _filter_valid_ohlc(df, source_name):
            if df is None or len(df) == 0:
                return None
            for c in ('open', 'close', 'high', 'low'):
                if c in df.columns:
                    df[c] = pd.to_numeric(df[c], errors='coerce')
            valid = (
                (df['open'] > 0) &
                (df['close'] > 0) &
                (df['high'] > 0) &
                (df['low'] > 0)
            )
            if not bool(valid.all()):
                invalid_cnt = int((~valid).sum())
                logging.debug(f"_fallback_kline_from_spot: {source_name} 过滤 {code} 无效OHLC行 {invalid_cnt} 条")
            df = df.loc[valid].copy()
            return df if len(df) > 0 else None

        # 1) A股快照
        if mdb.checkTableIsExist('cn_stock_spot'):
            sql = (
                "SELECT `date`, `new_price` AS `close`, `open_price` AS `open`, "
                "`high_price` AS `high`, `low_price` AS `low`, "
                "`volume` / 100 AS `volume`, `deal_amount` AS `amount`, "
                "`amplitude`, `change_rate` AS `quote_change`, "
                "`ups_downs`, `turnoverrate` AS `turnover` "
                "FROM `cn_stock_spot` WHERE `code` = %s AND `date` >= %s AND `date` <= %s "
                "ORDER BY `date`"
            )
            df = pd.read_sql(sql, mdb.engine(), params=(code, date_start_dash, date_end_dash))
            df = _filter_valid_ohlc(df, 'cn_stock_spot')
            if df is not None:
                df['date'] = pd.to_datetime(df['date'])
                logging.debug(f"_fallback_kline_from_spot: {code} 从 cn_stock_spot 读取 {len(df)} 行 "
                              f"({date_start_dash}~{date_end_dash})")
                return df

        # 2) ETF 快照（cn_etf_spot 无 amplitude 列）
        if mdb.checkTableIsExist('cn_etf_spot'):
            sql_etf = (
                "SELECT `date`, `new_price` AS `close`, `open_price` AS `open`, "
                "`high_price` AS `high`, `low_price` AS `low`, "
                "`volume` / 100 AS `volume`, `deal_amount` AS `amount`, "
                "`change_rate` AS `quote_change`, "
                "`ups_downs`, `turnoverrate` AS `turnover` "
                "FROM `cn_etf_spot` WHERE `code` = %s AND `date` >= %s AND `date` <= %s "
                "AND `new_price` > 0 "
                "ORDER BY `date`"
            )
            df_etf = pd.read_sql(sql_etf, mdb.engine(), params=(code, date_start_dash, date_end_dash))
            df_etf = _filter_valid_ohlc(df_etf, 'cn_etf_spot')
            if df_etf is not None:
                df_etf['date'] = pd.to_datetime(df_etf['date'])
                logging.debug(f"_fallback_kline_from_spot: {code} 从 cn_etf_spot 读取 {len(df_etf)} 行 "
                              f"({date_start_dash}~{date_end_dash})")
                return df_etf
    except Exception as e:
        logging.debug(f"_fallback_kline_from_spot 异常：{code} - {e}")
    return None
