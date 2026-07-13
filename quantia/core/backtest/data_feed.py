#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据加载层 — 从本地 K 线缓存 / EastMoney API 加载回测用数据

支持：
- 从 cache/hist/ 加载单只/多只股票的日 K 线
- 当缓存不足时自动从 EastMoney API 补全
- 加载基准指数（沪深300等）日 K 线
- 获取交易日历
"""

import os
import logging
import datetime
import time
import concurrent.futures
import pandas as pd
import numpy as np

from quantia.lib.log_config import warn_throttled

__author__ = 'Quantia'
__date__ = '2026/03/16'

# 缓存目录
_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                          'cache', 'hist')

_KNOWN_INDEX_CODES = {
    '000001', '000002', '000003', '000016', '000300', '000688',
    '000852', '000905', '000906', '000985',
    '399001', '399006', '399300', '399905', '399951',
}

# These codes do not collide with common A-share stock symbols and should never
# be sent to the stock K-line endpoint.
_STOCK_LOADER_INDEX_CODES = _KNOWN_INDEX_CODES - {'000001', '000002', '000003'}


def _normalize_code(code):
    text = str(code or '').strip()
    return text.split('.')[0] if '.' in text else text


def _should_route_stock_loader_to_index(code):
    clean = _normalize_code(code)
    return clean in _STOCK_LOADER_INDEX_CODES or clean.startswith('399')


# A 股代码合法前缀（沪市6/5；深市/北交所 0/1/3/4/8/920）。
# 用于在调用东方财富前过滤明显非法的代码（如 900001/999999），避免日志噪声和无谓重试。
_VALID_STOCK_PREFIXES = ('0', '1', '3', '4', '5', '6', '8')


def _is_likely_stock_code(code):
    clean = _normalize_code(code)
    return (len(clean) == 6 and clean.isdigit()
            and (clean[0] in _VALID_STOCK_PREFIXES or clean.startswith('920')))


def _normalize_em_df(raw, code):
    """将东方财富中文列 DataFrame 转为标准化结果，失败返回 None。"""
    col_map = {'日期': 'date', '开盘': 'open', '收盘': 'close',
               '最高': 'high', '最低': 'low', '成交量': 'volume',
               '成交额': 'amount'}
    df = raw.rename(columns=col_map)
    for c in ['date', 'open', 'high', 'low', 'close', 'volume']:
        if c not in df.columns:
            logging.warning(f"EastMoney数据缺少 {c} 列: {code}")
            return None
    df['date'] = pd.to_datetime(df['date'])
    for c in ['open', 'high', 'low', 'close']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df['volume'] = pd.to_numeric(df['volume'], errors='coerce').fillna(0).astype('int64')
    if 'amount' in df.columns:
        df['amount'] = pd.to_numeric(df['amount'], errors='coerce').fillna(0)
        df = df[['date', 'open', 'high', 'low', 'close', 'volume', 'amount']]
    else:
        df = df[['date', 'open', 'high', 'low', 'close', 'volume']]
    return df.sort_values('date').reset_index(drop=True)


def _fetch_stock_from_akshare(code, start_date=None, end_date=None, adjust='qfq'):
    """akshare 备用通道：当 EastMoney push2his 接口持续 500/网络异常时使用。

    akshare.stock_zh_a_hist 走的是不同的 EM 端点（kline-pre），
    在 push2his 故障时往往仍可用。返回标准化 DataFrame 或 None。
    """
    try:
        import akshare as ak
        sd = pd.Timestamp(start_date).strftime('%Y%m%d') if start_date else '19700101'
        ed = pd.Timestamp(end_date).strftime('%Y%m%d') if end_date else '20500101'
        raw = ak.stock_zh_a_hist(symbol=code, period='daily',
                                 start_date=sd, end_date=ed, adjust=adjust)
        if raw is None or len(raw) == 0:
            return None
        df = _normalize_em_df(raw, code)
        if df is not None and len(df) > 0:
            logging.info(f"从 akshare 获取 {code} K线数据(EM 备用通道): {len(df)} 条 "
                         f"({df['date'].iloc[0].date()} ~ {df['date'].iloc[-1].date()})")
        return df
    except Exception as e:
        logging.debug(f"akshare 获取 {code} 数据失败: {e}")
        return None


def _fetch_stock_from_eastmoney(code, start_date=None, end_date=None, adjust='qfq'):
    """
    从 EastMoney API 获取个股日 K 线，返回标准化的 DataFrame。

    若 EastMoney push2his 持续 5xx/网络异常，自动降级到 akshare 备用通道。
    Returns:
        DataFrame with columns [date, open, high, low, close, volume] or None
    """
    # 早期过滤明显非法代码（避免对 999999 等占位符发请求并刷日志）
    if not _is_likely_stock_code(code):
        logging.debug(f"跳过非 A 股代码: {code}")
        return None

    try:
        from quantia.core.crawling.stock_hist_em import stock_zh_a_hist
        sd = pd.Timestamp(start_date).strftime('%Y%m%d') if start_date else '19700101'
        ed = pd.Timestamp(end_date).strftime('%Y%m%d') if end_date else '20500101'
        raw = stock_zh_a_hist(symbol=code, start_date=sd, end_date=ed,
                              period='daily', adjust=adjust)
        if raw is None or len(raw) == 0:
            # 主通道空数据 → 尝试 akshare 备用通道
            return _fetch_stock_from_akshare(code, start_date, end_date, adjust)

        df = _normalize_em_df(raw, code)
        if df is None:
            return None
        logging.info(f"从 EastMoney 获取 {code} K线数据: {len(df)} 条 "
                     f"({df['date'].iloc[0].date()} ~ {df['date'].iloc[-1].date()})")
        return df
    except KeyError as e:
        # 未知股票代码前缀 → 不需要重试，DEBUG 级别
        logging.debug(f"跳过 EastMoney 获取 {code}: {e}")
        return None
    except Exception as e:
        # 含 5xx / 网络异常等：尝试 akshare 备用通道
        err_str = str(e)
        is_transient = any(kw in err_str for kw in (
            '500 Server Error', '502', '503', '504',
            'ConnectionError', 'Timeout', 'timed out', 'Max retries',
            'RemoteDisconnected', 'SSLError',
        ))
        if is_transient:
            # 整库回测时会出现成千上万条同类降级告警 → 限频聚合，每 10 分钟汇总一次
            warn_throttled(
                'em_stock_fallback',
                f"EastMoney 获取个股失败({type(e).__name__})，降级 akshare（最近 {code}）: {err_str[:120]}",
                window_sec=600,
            )
            fallback = _fetch_stock_from_akshare(code, start_date, end_date, adjust)
            if fallback is not None:
                return fallback
        else:
            logging.warning(f"EastMoney 获取 {code} 数据失败: {e}")
        return None


def _save_cache(code, df):
    """保存 DataFrame 到缓存文件（统一路径 cache/hist/{prefix}/{code}qfq.gzip.pickle）"""
    try:
        sub_dir = os.path.join(_CACHE_DIR, code[:3])
        os.makedirs(sub_dir, exist_ok=True)
        cache_file = os.path.join(sub_dir, f"{code}qfq.gzip.pickle")
        df.to_pickle(cache_file, compression="gzip")
        logging.debug(f"缓存已更新: {code} ({len(df)} 条)")
    except Exception as e:
        logging.warning(f"缓存保存失败 {code}: {e}")


def _load_spot_range_from_db(code, start_date_str, end_date_str):
    """
    从 cn_stock_spot 表加载指定日期区间的行情数据。

    每日定时任务会将全市场行情写入 cn_stock_spot，
    此处作为 K 线缓存与在线 API 之间的中间层，避免大量网络请求。

    Returns:
        DataFrame with [date, open, high, low, close, volume] or None
    """
    try:
        import quantia.lib.database as mdb
        rows = mdb.executeSqlFetch(
            'SELECT date, open_price, high_price, low_price, new_price, volume, '
            'pre_close_price, deal_amount '
            'FROM cn_stock_spot WHERE code = %s AND date >= %s AND date <= %s '
            'ORDER BY date',
            (code, start_date_str, end_date_str))
        if not rows or len(rows) == 0:
            return None
        records = []
        for row in rows:
            # 跳过无效数据（停牌等: new_price=0 或 None）
            if not row[4] or float(row[4]) <= 0:
                continue
            records.append({
                'date': pd.Timestamp(row[0]),
                'open': float(row[1] or row[4]),
                'high': float(row[2] or row[4]),
                'low': float(row[3] or row[4]),
                'close': float(row[4]),
                'volume': int(row[5] or 0),
                'pre_close': float(row[6]) if row[6] else None,
                'amount': float(row[7] or 0),
            })
        return pd.DataFrame(records) if records else None
    except Exception as e:
        logging.debug(
            f"从 cn_stock_spot 加载 {code} {start_date_str}~{end_date_str} 失败: {e}")
        return None


def _load_today_from_db(code, date_str):
    """从 cn_stock_spot 加载指定日期，保留原有单日调用接口。"""
    return _load_spot_range_from_db(code, date_str, date_str)


def _batch_load_today_from_db(codes, date_str):
    """
    批量从 cn_stock_spot 加载指定日期的行情数据。

    Returns:
        dict: {code: {open, high, low, close, volume, pre_close}} 或空字典
    """
    if not codes:
        return {}
    try:
        import quantia.lib.database as mdb
        placeholders = ','.join(['%s'] * len(codes))
        rows = mdb.executeSqlFetch(
            f'SELECT code, date, open_price, high_price, low_price, new_price, '
            f'volume, pre_close_price, deal_amount '
            f'FROM cn_stock_spot WHERE code IN ({placeholders}) AND date = %s',
            (*codes, date_str))
        if not rows:
            return {}
        result = {}
        for r in rows:
            code = r[0]
            new_price = r[5]
            if not new_price or float(new_price) <= 0:
                continue
            result[code] = {
                'date': pd.Timestamp(r[1]),
                'open': float(r[2] or new_price),
                'high': float(r[3] or new_price),
                'low': float(r[4] or new_price),
                'close': float(new_price),
                'volume': int(r[6] or 0),
                'pre_close': float(r[7]) if r[7] else None,
                'amount': float(r[8] or 0),
            }
        if result:
            logging.info(f"从 cn_stock_spot 批量加载 {len(result)}/{len(codes)} 只股票 {date_str} 行情")
        return result
    except Exception as e:
        logging.debug(f"批量从 cn_stock_spot 加载失败: {e}")
        return {}


def load_stock_data(code, start_date=None, end_date=None, cache_only=False):
    """
    加载股票日 K 线数据。优先从缓存加载，缓存不足时从 EastMoney 补全。

    Args:
        code: 6位股票代码（如 '000001'）
        start_date: 开始日期（str 'YYYY-MM-DD' 或 date 对象）
        end_date: 结束日期
        cache_only: True 时仅使用本地缓存和 cn_stock_spot 数据库，不调用任何在线 API。
                    回测场景下应传 True，缓存不足的股票直接返回 None（由引擎跳过该股），
                    彻底避免 EastMoney/akshare 网络请求阻塞回测线程。

    Returns:
        DataFrame: 包含 date/open/high/low/close/volume/pre_close 列，
                   按日期升序排列。无数据返回 None。
    """
    code = _normalize_code(code)
    if _should_route_stock_loader_to_index(code):
        return load_benchmark_data(code, start_date, end_date)

    df = _load_from_cache(code)
    need_online = False

    if df is None or len(df) == 0:
        need_online = True
    elif end_date:
        # 缓存不足时，先连续合并 DB 中缓存末日之后的全部日线快照。
        cache_end = df['date'].max().date() if hasattr(df['date'].max(), 'date') else df['date'].max()
        req_end = pd.Timestamp(end_date).date()
        if cache_end < req_end:
            db_start = (cache_end + datetime.timedelta(days=1)).strftime('%Y-%m-%d')
            db_end = req_end.strftime('%Y-%m-%d')
            db_tail = _load_spot_range_from_db(code, db_start, db_end)
            if db_tail is not None and len(db_tail) > 0:
                df = pd.concat([df, db_tail], ignore_index=True).drop_duplicates(
                    subset=['date'], keep='last').sort_values('date').reset_index(drop=True)
                cache_end = df['date'].max().date()

        # DB 仍未覆盖需求日期时，保留3天宽松度处理周末/节假日。
        if cache_end < req_end - datetime.timedelta(days=3):
            if cache_only:
                logging.debug(
                    f"{code} 本地数据截止 {cache_end} < 需求 {req_end}，回测离线模式跳过在线补全")
            else:
                need_online = True
                logging.info(
                    f"{code} 本地数据截止 {cache_end}，需要数据到 {req_end}，尝试在线获取")

    if need_online and not cache_only:
        # 完全缺失时也先尝试 DB
        if end_date:
            end_str = pd.Timestamp(end_date).strftime('%Y-%m-%d')
            db_row = _load_today_from_db(code, end_str)
            if db_row is not None and df is not None and len(df) > 0:
                df = pd.concat([df, db_row], ignore_index=True).drop_duplicates(
                    subset=['date'], keep='last').sort_values('date').reset_index(drop=True)
                need_online = False
            elif db_row is not None and (df is None or len(df) == 0):
                # 只有今天的 DB 数据，仍需在线补历史
                pass

    if need_online and not cache_only:
        online_df = _fetch_stock_from_eastmoney(code, start_date, end_date)
        if online_df is not None and len(online_df) > 0:
            df = online_df
            # 更新缓存（保存完整获取范围）
            _save_cache(code, df)

    if need_online and cache_only and (df is None or len(df) == 0):
        # 回测离线模式：缓存完全缺失，直接返回 None，引擎将跳过该股票
        logging.debug(f"{code} 无本地缓存，回测离线模式跳过")
        return None

    if df is None or len(df) == 0:
        return None

    # 日期过滤
    if start_date:
        df = df[df['date'] >= pd.Timestamp(start_date)]
    if end_date:
        df = df[df['date'] <= pd.Timestamp(end_date)]

    if len(df) == 0:
        return None

    # 计算前收盘价
    df = df.sort_values('date').reset_index(drop=True)
    df['pre_close'] = df['close'].shift(1)
    return df


def _quarantine_corrupt_cache(path):
    """把损坏的缓存文件改名为 .corrupt，避免反复读取报警。

    后续 _save_cache / _save_index_cache 写入时，原路径已不存在，
    会作为全新缓存写入，相当于"读取失败 → 强制重写"。
    """
    try:
        if os.path.exists(path):
            backup = path + '.corrupt'
            try:
                if os.path.exists(backup):
                    os.remove(backup)
            except Exception:
                pass
            os.rename(path, backup)
            logging.warning(f"已将损坏缓存改名为 {os.path.basename(backup)}，下次访问将重建")
    except Exception as e:
        logging.debug(f"隔离损坏缓存失败 {path}: {e}")


def _load_from_cache(code):
    """
    从本地 pickle 缓存加载，返回 DataFrame 或 None

    缓存搜索顺序：
    1. stockfetch 统一缓存路径: cache/hist/{code[:3]}/{code}qfq.gzip.pickle（压缩pickle）
    2. data_feed 旧缓存路径: cache/hist/{code}.gzip.pickle（普通pickle）

    读取失败的缓存文件会被改名为 .corrupt，并返回 None
    以触发上层在线获取并重写完整缓存。
    """
    # 优先：stockfetch 统一路径
    cache_dir_unified = os.path.join(_CACHE_DIR, code[:3])
    cache_file_unified = os.path.join(cache_dir_unified, f"{code}qfq.gzip.pickle")
    if os.path.exists(cache_file_unified):
        try:
            df = pd.read_pickle(cache_file_unified, compression="gzip")
            df = _normalize_cache_df(df)
            if df is not None:
                return df
            # 文件可读但无法标准化：视为损坏
            logging.warning(f"统一缓存内容不合法 {code}，触发隔离重建")
            _quarantine_corrupt_cache(cache_file_unified)
        except Exception as e:
            logging.warning(f"读取统一缓存失败 {code}: {e}")
            _quarantine_corrupt_cache(cache_file_unified)
            # 读取失败时强制返回 None，触发在线重新拉取并重写完整缓存
            return None

    # 降级：旧 data_feed 路径
    cache_file = os.path.join(_CACHE_DIR, f"{code}.gzip.pickle")
    if not os.path.exists(cache_file):
        return None
    try:
        df = pd.read_pickle(cache_file)
        normalized = _normalize_cache_df(df)
        if normalized is None:
            _quarantine_corrupt_cache(cache_file)
        return normalized
    except Exception as e:
        logging.warning(f"加载K线缓存异常 {code}: {e}")
        _quarantine_corrupt_cache(cache_file)
        return None


def _load_index_from_cache(code):
    """
    从指数缓存目录加载，返回 DataFrame 或 None

    缓存路径: cache/hist/index/{code}.gzip.pickle
    读取失败的文件会被改名为 .corrupt，由 _save_index_cache 重写。
    """
    cache_file = os.path.join(_CACHE_DIR, 'index', f"{code}.gzip.pickle")
    if not os.path.exists(cache_file):
        return None
    try:
        df = pd.read_pickle(cache_file, compression="gzip")
        normalized = _normalize_cache_df(df)
        if normalized is None:
            logging.warning(f"指数缓存内容不合法 {code}，触发隔离重建")
            _quarantine_corrupt_cache(cache_file)
        return normalized
    except Exception as e:
        logging.warning(f"加载指数缓存异常 {code}: {e}")
        _quarantine_corrupt_cache(cache_file)
        return None


def _save_index_cache(code, df):
    """合并并保存指数 DataFrame 到缓存文件。

    与现有缓存按 date 去重合并后整体写入，避免回测仅请求局部区间时
    把已有的多年历史数据覆盖成短区间（曾导致 K 线页面基准只显示
    2022-2024 的数据）。
    """
    try:
        if df is None or len(df) == 0:
            return
        index_dir = os.path.join(_CACHE_DIR, 'index')
        os.makedirs(index_dir, exist_ok=True)
        cache_file = os.path.join(index_dir, f"{code}.gzip.pickle")

        merged = df.copy()
        if 'date' in merged.columns:
            merged['date'] = pd.to_datetime(merged['date'])

        # 与已有缓存合并（如存在）
        if os.path.exists(cache_file):
            try:
                existing = pd.read_pickle(cache_file, compression="gzip")
                if existing is not None and len(existing) > 0 and 'date' in existing.columns:
                    existing = existing.copy()
                    existing['date'] = pd.to_datetime(existing['date'])
                    merged = pd.concat([existing, merged], ignore_index=True)
            except Exception as e:
                logging.warning(f"读取已有指数缓存失败，将以新数据覆盖: {code} - {e}")

        if 'date' in merged.columns:
            # 保留新写入的数据（after concat，新数据在后），按日期去重排序
            merged = merged.drop_duplicates(subset=['date'], keep='last')
            merged = merged.sort_values('date').reset_index(drop=True)

        # 原子写入
        tmp_file = cache_file + '.tmp'
        merged.to_pickle(tmp_file, compression="gzip")
        if os.path.exists(cache_file):
            os.remove(cache_file)
        os.rename(tmp_file, cache_file)
        logging.debug(f"指数缓存已更新（合并）: {code} ({len(merged)} 条)")
    except Exception as e:
        logging.warning(f"指数缓存保存失败 {code}: {e}")


def _normalize_cache_df(df):
    """标准化缓存 DataFrame，确保包含必需列"""
    if df is None or len(df) == 0:
        return None

    # 确保日期列
    if 'date' in df.columns:
        if not pd.api.types.is_datetime64_any_dtype(df['date']):
            df['date'] = pd.to_datetime(df['date'])
    elif df.index.name == 'date' or isinstance(df.index, pd.DatetimeIndex):
        df = df.reset_index()
        df.rename(columns={df.columns[0]: 'date'}, inplace=True)
        df['date'] = pd.to_datetime(df['date'])

    if 'date' not in df.columns:
        return None

    # 检查必需列
    for c in ['open', 'high', 'low', 'close', 'volume']:
        if c not in df.columns:
            return None

    return df.sort_values('date').reset_index(drop=True)


def load_multiple_stocks(codes, start_date=None, end_date=None, cache_only=False):
    """
    批量加载多只股票数据（多线程并行）。

    Args:
        codes: 股票代码列表
        start_date: 开始日期
        end_date: 结束日期
        cache_only: True 时仅使用本地缓存和 DB，不调用在线 API。
                    缓存不存在或不足的股票将被静默跳过。

    Returns:
        dict: {code: DataFrame}，无数据的股票不包含
    """
    result = {}
    # 低内存环境限制并发数，减少同时驻留的 DataFrame 数量
    max_workers = min(8, len(codes)) if codes else 1

    def _load_one(code):
        return code, load_stock_data(code, start_date, end_date, cache_only=cache_only)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_load_one, code): code for code in codes}
        for future in concurrent.futures.as_completed(futures):
            try:
                code, df = future.result()
                if df is not None and len(df) > 0:
                    result[code] = df
            except Exception as e:
                logging.debug(f"加载股票 {futures[future]} 失败: {e}")
    return result


def get_all_cached_stocks():
    """
    扫描本地缓存目录，返回所有可用的股票代码列表。

    Returns:
        list[str]: 6位股票代码列表（如 ['000001', '600036', ...]）
    """
    codes = set()
    if not os.path.isdir(_CACHE_DIR):
        return []
    # 根目录下的 .gzip.pickle
    for f in os.listdir(_CACHE_DIR):
        if f.endswith('.gzip.pickle') and len(f) >= 18:
            code = f[:6]
            if code.isdigit():
                codes.add(code)
    # 子目录下的 {code}qfq.gzip.pickle
    for sub in os.listdir(_CACHE_DIR):
        sub_path = os.path.join(_CACHE_DIR, sub)
        if not os.path.isdir(sub_path) or sub in ('index', 'sh6', 'sz0'):
            continue
        for f in os.listdir(sub_path):
            if f.endswith('qfq.gzip.pickle'):
                code = f.replace('qfq.gzip.pickle', '')
                if len(code) == 6 and code.isdigit():
                    codes.add(code)
    return sorted(codes)


def get_trading_dates(start_date, end_date):
    """
    获取交易日列表。

    优先从数据库 cn_stock_trade_date 获取，
    降级为从任一股票的 K 线缓存提取。

    Returns:
        list[datetime.date]: 交易日列表，升序
    """
    # 尝试从数据库获取
    try:
        import quantia.lib.trade_time as trd
        from quantia.core.singleton_trade_date import stock_trade_date
        all_dates = stock_trade_date().get_data()
        if all_dates:
            start = pd.Timestamp(start_date).date() if isinstance(start_date, str) else start_date
            end = pd.Timestamp(end_date).date() if isinstance(end_date, str) else end_date
            dates = sorted([d for d in all_dates if start <= d <= end])
            if dates:
                return dates
    except Exception:
        logging.debug("从 DB 获取交易日异常，降级到缓存", exc_info=True)

    # 降级：从沪深300指数或常见股票的 K 线提取交易日
    # 000300 是指数，必须走指数数据源；否则会被股票接口误判为深市股票
    # 并请求 secid=0.000300，EastMoney 会返回 500。
    candidates = [
        ('000300', load_benchmark_data),
        ('000001', load_stock_data),
        ('600000', load_stock_data),
    ]
    for code, loader in candidates:
        df = loader(code, start_date, end_date)
        if df is not None and len(df) > 0:
            dates = sorted(df['date'].dt.date.tolist())
            return dates

    # 最终降级：pd.bdate_range
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    return [d.date() for d in pd.bdate_range(start, end)]


def load_benchmark_data(code='000300', start_date=None, end_date=None):
    """
    加载基准指数 K 线数据。

    优先级：
    1. 指数专用缓存（cache/hist/index/{code}.gzip.pickle）
    2. 东方财富指数 API（stock_index_hist_em，使用正确的 secid 前缀）
    3. 股票缓存（兼容旧路径，仅用于非指数代码）
    4. AkShare 在线获取（最终降级）

    Args:
        code: 指数代码（默认沪深300 = '000300'）
        start_date: 开始日期
        end_date: 结束日期

    Returns:
        DataFrame: 包含 date/close 列。无数据返回 None。
    """
    code = _normalize_code(code)
    is_index = code in _KNOWN_INDEX_CODES or code.startswith('399')

    # 1. 优先从指数缓存加载
    df = _load_index_from_cache(code)
    if df is not None:
        # 日期过滤
        if start_date:
            df = df[df['date'] >= pd.Timestamp(start_date)]
        if end_date:
            df = df[df['date'] <= pd.Timestamp(end_date)]
        if len(df) > 0:
            df = df.sort_values('date').reset_index(drop=True)
            df['pre_close'] = df['close'].shift(1)
            logging.info(f"从指数缓存加载基准 {code} 数据: {len(df)} 条")
            return df

    # 2. 尝试东方财富指数专用 API（使用正确的 secid 前缀，避免股票 API 500 错误）
    if is_index:
        try:
            from quantia.core.crawling.stock_index_em import stock_index_hist_em
            sd = pd.Timestamp(start_date).strftime('%Y%m%d') if start_date else '19700101'
            ed = pd.Timestamp(end_date).strftime('%Y%m%d') if end_date else '20500101'
            raw = stock_index_hist_em(symbol=code, period='daily',
                                      start_date=sd, end_date=ed)
            if raw is not None and len(raw) > 0:
                col_map = {'日期': 'date', '开盘': 'open', '收盘': 'close',
                           '最高': 'high', '最低': 'low', '成交量': 'volume'}
                idx_df = raw.rename(columns=col_map)
                if 'date' in idx_df.columns and 'close' in idx_df.columns:
                    idx_df['date'] = pd.to_datetime(idx_df['date'])
                    for c in ['open', 'high', 'low', 'close']:
                        if c in idx_df.columns:
                            idx_df[c] = pd.to_numeric(idx_df[c], errors='coerce')
                    if 'volume' in idx_df.columns:
                        idx_df['volume'] = pd.to_numeric(idx_df['volume'], errors='coerce').fillna(0).astype(int)
                    idx_df = idx_df.sort_values('date').reset_index(drop=True)
                    idx_df['pre_close'] = idx_df['close'].shift(1)
                    # 写入指数缓存供后续使用
                    _save_index_cache(code, idx_df)
                    logging.info(f"从 EastMoney 指数API 获取基准 {code} 数据: {len(idx_df)} 条")
                    return idx_df
        except Exception as e:
            err_str = str(e)
            is_transient = any(kw in err_str for kw in (
                '500 Server Error', '502', '503', '504',
                'ConnectionError', 'Timeout', 'timed out', 'Max retries',
                'RemoteDisconnected', 'SSLError',
            ))
            if is_transient:
                warn_throttled(
                    f'em_index_fail:{code}',
                    f"EastMoney 指数API 获取 {code} 失败({type(e).__name__})，将尝试 AkShare 备用通道",
                    window_sec=3600,
                )
            else:
                logging.debug(f"EastMoney 指数API 获取 {code} 失败: {e}")

    # 3. 降级：尝试从股票缓存加载（仅对非指数代码有效，避免对指数代码调用股票 API 产生 500 错误）
    if not is_index:
        df = load_stock_data(code, start_date, end_date)
        if df is not None:
            return df

    # 4. 最终降级：尝试用 AkShare 获取指数数据
    # 主要上证/中证指数（以 0 开头但属上海交易所）
    _SH_INDICES = {'000001', '000002', '000003', '000016', '000300',
                   '000688', '000852', '000905', '000906', '000985'}
    try:
        import akshare as ak
        # 确定 AkShare 所需的前缀
        if code in _SH_INDICES or code.startswith(('9', '5')):
            ak_code = f"sh{code}"
        elif code.startswith(('6', '1')):
            ak_code = f"sh{code}"
        else:
            ak_code = f"sz{code}"

        idx_df = ak.stock_zh_index_daily(symbol=ak_code)
        if idx_df is not None and len(idx_df) > 0:
            idx_df = idx_df.copy()
            idx_df['date'] = pd.to_datetime(idx_df['date'])
            if 'volume' in idx_df.columns:
                idx_df['volume'] = pd.to_numeric(idx_df['volume'], errors='coerce').fillna(0).astype('int64')
            # 写入指数缓存（_save_index_cache 已合并，不会覆盖历史）
            if is_index:
                _save_index_cache(code, idx_df)
            if start_date:
                idx_df = idx_df[idx_df['date'] >= pd.Timestamp(start_date)]
            if end_date:
                idx_df = idx_df[idx_df['date'] <= pd.Timestamp(end_date)]
            idx_df = idx_df.sort_values('date').reset_index(drop=True)
            if len(idx_df) > 0:
                idx_df['pre_close'] = idx_df['close'].shift(1)
                logging.info(f"从 AkShare 获取基准指数 {code} ({ak_code}) 数据: {len(idx_df)} 条")
                return idx_df

        # 如果上面失败，尝试另一前缀
        alt_code = f"sh{code}" if ak_code.startswith('sz') else f"sz{code}"
        logging.debug(f"尝试替代前缀 {alt_code}")
        idx_df = ak.stock_zh_index_daily(symbol=alt_code)
        if idx_df is not None and len(idx_df) > 0:
            idx_df = idx_df.copy()
            idx_df['date'] = pd.to_datetime(idx_df['date'])
            if 'volume' in idx_df.columns:
                idx_df['volume'] = pd.to_numeric(idx_df['volume'], errors='coerce').fillna(0).astype('int64')
            if is_index:
                _save_index_cache(code, idx_df)
            if start_date:
                idx_df = idx_df[idx_df['date'] >= pd.Timestamp(start_date)]
            if end_date:
                idx_df = idx_df[idx_df['date'] <= pd.Timestamp(end_date)]
            idx_df = idx_df.sort_values('date').reset_index(drop=True)
            if len(idx_df) > 0:
                idx_df['pre_close'] = idx_df['close'].shift(1)
                logging.info(f"从 AkShare 获取基准指数 {code} ({alt_code}) 数据: {len(idx_df)} 条")
                return idx_df
    except Exception as e:
        logging.debug(f"AkShare 获取指数数据失败: {e}")

    # 同一基准指数若持续不可用，多个分析任务会每小时重复刷此告警 → 限频
    warn_throttled(f'benchmark_fail:{code}', f"无法获取基准指数 {code} 的数据", window_sec=3600)
    return None
