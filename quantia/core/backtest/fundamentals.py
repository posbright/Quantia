#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基本面数据提供层 — 实现聚宽 get_fundamentals / query / valuation API

提供与聚宽量化平台兼容的基本面数据查询接口，
用于在回测引擎中支持按市值、市盈率等基本面指标筛选股票。

实现原理：
1. 调用 stock_zh_a_spot_em() 获取当前全市场股票总市值
2. 估算总股本 = 总市值 / 最新价
3. 批量加载候选股票K线数据并缓存
4. 每日市值 = 总股本 × 当日收盘价 / 1亿
"""

import logging
import os
import time
import pickle
import pandas as pd
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed

__author__ = 'Quantia'
__date__ = '2026/03/16'

_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                          'cache', 'fundamental')

# 基本面数据库查询超时（毫秒）：避免慢查询阻塞回测线程。
_FUND_DB_QUERY_TIMEOUT_MS = max(int(os.getenv('QUANTIA_FUND_DB_QUERY_TIMEOUT_MS', '8000')), 0)


# ── 聚宽风格查询 API 对象 ──

class _FieldExpr:
    """表字段表达式，支持 .between() / .asc() / .desc() 等链式调用"""

    def __init__(self, table, name):
        self._table = table
        self._name = name

    def between(self, low, high):
        return ('between', self._name, low, high)

    def in_(self, values):
        """聚宽 .in_() 过滤 — 值在列表中"""
        return ('in_', self._name, list(values))

    def asc(self):
        return ('asc', self._name)

    def desc(self):
        return ('desc', self._name)

    def __gt__(self, other):
        return ('gt', self._name, other)

    def __lt__(self, other):
        return ('lt', self._name, other)

    def __ge__(self, other):
        return ('ge', self._name, other)

    def __le__(self, other):
        return ('le', self._name, other)

    def __truediv__(self, other):
        """支持 balance.total_liability / balance.total_assets 这种字段表达式"""
        if isinstance(other, _FieldExpr):
            return _DivFieldExpr(self._name, other._name)
        return NotImplemented

    def __repr__(self):
        return f"Field({self._table}.{self._name})"


class _DivFieldExpr:
    """两个字段的除法表达式，如 balance.total_liability / balance.total_assets"""

    def __init__(self, numerator, denominator):
        self._numerator = numerator
        self._denominator = denominator

    def __lt__(self, other):
        return ('div_lt', self._numerator, self._denominator, other)

    def __gt__(self, other):
        return ('div_gt', self._numerator, self._denominator, other)

    def __le__(self, other):
        return ('div_le', self._numerator, self._denominator, other)

    def __ge__(self, other):
        return ('div_ge', self._numerator, self._denominator, other)


class _ValuationTable:
    """聚宽 valuation 表对象 — 提供市值等估值指标字段"""
    code = _FieldExpr('valuation', 'code')
    name = _FieldExpr('valuation', 'name')
    market_cap = _FieldExpr('valuation', 'market_cap')
    pe_ratio = _FieldExpr('valuation', 'pe_ratio')
    pb_ratio = _FieldExpr('valuation', 'pb_ratio')
    circulating_market_cap = _FieldExpr('valuation', 'circulating_market_cap')


# 全局 valuation 实例（策略中直接引用）
valuation = _ValuationTable()


class _IndicatorTable:
    """聚宽 indicator 表对象 — 提供财务指标字段"""
    code = _FieldExpr('indicator', 'code')
    inc_total_revenue_year_on_year = _FieldExpr('indicator', 'inc_total_revenue_year_on_year')
    inc_net_profit_year_on_year = _FieldExpr('indicator', 'inc_net_profit_year_on_year')
    roe = _FieldExpr('indicator', 'roe')
    eps = _FieldExpr('indicator', 'eps')
    inc_revenue_year_on_year = _FieldExpr('indicator', 'inc_revenue_year_on_year')
    net_profit_margin = _FieldExpr('indicator', 'net_profit_margin')
    gross_profit_margin = _FieldExpr('indicator', 'gross_profit_margin')


indicator = _IndicatorTable()


class _BalanceTable:
    """聚宽 balance 表对象 — 提供资产负债表字段"""
    code = _FieldExpr('balance', 'code')
    total_liability = _FieldExpr('balance', 'total_liability')
    total_assets = _FieldExpr('balance', 'total_assets')
    total_current_assets = _FieldExpr('balance', 'total_current_assets')
    total_current_liability = _FieldExpr('balance', 'total_current_liability')


balance = _BalanceTable()


class _CashFlowTable:
    """聚宽 cash_flow 表对象 — 提供现金流量表字段"""
    code = _FieldExpr('cash_flow', 'code')
    net_operate_cash_flow = _FieldExpr('cash_flow', 'net_operate_cash_flow')
    net_invest_cash_flow = _FieldExpr('cash_flow', 'net_invest_cash_flow')
    net_finance_cash_flow = _FieldExpr('cash_flow', 'net_finance_cash_flow')


cash_flow = _CashFlowTable()


class _Query:
    """聚宽 query 对象"""

    def __init__(self, *fields):
        self._fields = fields
        self._filters = []
        self._order_by_clause = None
        self._limit_val = None

    def filter(self, *conditions):
        self._filters.extend(conditions)
        return self

    def order_by(self, clause):
        self._order_by_clause = clause
        return self

    def limit(self, n):
        self._limit_val = n
        return self


def query(*fields):
    """聚宽 query() 函数"""
    return _Query(*fields)


class OrderCost:
    """聚宽 OrderCost 对象"""

    def __init__(self, open_tax=0, close_tax=0.001,
                 open_commission=0.0003, close_commission=0.0003,
                 close_today_commission=0, min_commission=5):
        self.open_tax = open_tax
        self.close_tax = close_tax
        self.open_commission = open_commission
        self.close_commission = close_commission
        self.close_today_commission = close_today_commission
        self.min_commission = min_commission


# ── 基本面数据提供器 ──

class FundamentalDataProvider:
    """
    基本面数据提供器

    使用东方财富实时数据 + 历史K线重建每日市值。

    工作原理：
    1. 调用 stock_zh_a_spot_em() 获取所有A股当前总市值
    2. 估算总股本 = 总市值 / 最新价
    3. 批量加载候选股票K线数据（缓存的pickle文件或从东方财富在线获取）
    4. 每日市值 = 总股本 × 当日收盘价 / 1亿
    """

    # 候选市值范围（亿元），比实际查询范围更宽以覆盖历史波动
    CANDIDATE_MCAP_LOW = 1
    CANDIDATE_MCAP_HIGH = 5000

    # _daily_mcap_cache 最多保留的条目数。该缓存以 "日期|代码集" 为 key，
    # 每条持有一个全市场规模的 DataFrame。长区间回测每日调用 get_fundamentals
    # 会不断新增 key（日期各不相同），若不设上限将累积上千个 DataFrame 常驻
    # 内存，造成无界增长 / OOM。跨日缓存几乎无复用价值（同一天极少重复查询），
    # 因此仅保留最近若干条即可。
    _MCAP_CACHE_MAX = 8

    def __init__(self, engine):
        self._engine = engine
        self._stock_info = None         # DataFrame: code, name, total_shares, current_mcap
        self._price_lookup = {}         # {code: {date_str: close_price}}
        self._volume_lookup = {}        # {code: {date_str: volume}}
        self._daily_mcap_cache = {}     # {date_str: DataFrame}
        self._initialized = False
        self._klines_loaded = False     # 是否已批量加载候选股票K线（与 _initialized 解耦）
        self._candidate_codes = []

    def _init_data(self, load_klines=True):
        """初始化基本面数据。

        Args:
            load_klines: 是否批量加载候选股票K线。仅在真正需要基本面行情
                （get_fundamentals 等）时才置 True。像 get_all_securities
                只需股票代码列表时应传 False，避免全市场K线批量加载导致 OOM。
        """
        # 已初始化：仅在首次真正需要K线时补加载，避免重复全量加载。
        if self._initialized:
            if load_klines and not self._klines_loaded and self._candidate_codes:
                self._batch_load_klines()
                self._klines_loaded = True
                self._save_fundamental_cache()
            return
        self._initialized = True

        # 尝试加载缓存
        if self._load_fundamental_cache():
            self._klines_loaded = True
            return

        # 1. 获取全市场股票信息
        self._fetch_stock_info()
        if self._stock_info is None or len(self._stock_info) == 0:
            logging.error("[基本面] 无法获取股票信息")
            return

        # 2. 预筛选候选股票（当前市值在宽泛范围内）
        candidates = self._stock_info[
            (self._stock_info['current_mcap'] >= self.CANDIDATE_MCAP_LOW) &
            (self._stock_info['current_mcap'] <= self.CANDIDATE_MCAP_HIGH)
        ].copy()
        self._candidate_codes = candidates['code'].tolist()
        logging.info(f"[基本面] 候选股票: {len(self._candidate_codes)} 只 "
                     f"(当前市值 {self.CANDIDATE_MCAP_LOW}-{self.CANDIDATE_MCAP_HIGH}亿)")

        # 3. 批量加载候选股票K线数据（仅在需要时；否则推迟，避免 OOM）
        if load_klines:
            self._batch_load_klines()
            self._klines_loaded = True
            # 4. 保存缓存
            self._save_fundamental_cache()

    def _fetch_stock_info(self):
        """获取全市场股票信息（优先DB，失败则在线API，最后从缓存推断）"""
        # 方式1: 从数据库 cn_stock_spot 获取（快速、可靠）
        try:
            self._fetch_stock_info_from_db()
            if self._stock_info is not None and len(self._stock_info) > 0:
                return
        except Exception as e:
            logging.warning(f"[基本面] 从数据库获取失败: {e}")

        # 方式2: 从东方财富在线获取（push2his端点，代理加速）
        try:
            self._fetch_stock_info_from_push2his()
            if self._stock_info is not None and len(self._stock_info) > 0:
                return
        except Exception as e:
            logging.warning(f"[基本面] push2his获取失败: {e}")

        # 方式3: 老方式 spot_em（最慢，备用）
        try:
            self._fetch_stock_info_from_api()
            if self._stock_info is not None and len(self._stock_info) > 0:
                return
        except Exception as e:
            logging.warning(f"[基本面] spot_em获取失败: {e}")

        # 方式4: 从本地K线缓存推断股票信息（终极降级）
        try:
            self._fetch_stock_info_from_cache()
        except Exception as e:
            logging.error(f"[基本面] 所有方式获取股票信息均失败: {e}")

    def _fetch_stock_info_from_db(self):
        """从数据库 cn_stock_spot 表获取股票信息（主要方式）"""
        from quantia.lib.database import executeSqlFetch
        logging.info("[基本面] 正在从数据库获取全市场股票数据...")
        timeout_ms = _FUND_DB_QUERY_TIMEOUT_MS

        # 先获取最新日期（避免慢子查询）
        date_rows = executeSqlFetch(
            'SELECT MAX(date) FROM cn_stock_spot',
            query_timeout_ms=timeout_ms,
        )
        if not date_rows or date_rows[0][0] is None:
            logging.warning("[基本面] cn_stock_spot 表无数据")
            return
        max_date = date_rows[0][0]
        logging.info(f"[基本面] cn_stock_spot 最新日期: {max_date}")

        sql = """
            SELECT code, name, new_price, total_market_cap, pbnewmrq
            FROM cn_stock_spot
            WHERE date = %s
              AND new_price > 0
              AND total_market_cap > 0
        """
        rows = executeSqlFetch(sql, (max_date,), query_timeout_ms=timeout_ms)
        if not rows or len(rows) == 0:
            logging.warning("[基本面] cn_stock_spot 表无数据")
            return

        records = []
        for row in rows:
            code, name, price = row[0], row[1], float(row[2])
            mcap_wan = float(row[3])
            pb = float(row[4]) if row[4] is not None else 0
            # total_market_cap 单位是万元
            total_mv_yuan = mcap_wan * 10000
            total_shares = total_mv_yuan / price if price > 0 else 0
            current_mcap_yi = total_mv_yuan / 1e8
            records.append({
                'code': code, 'name': name.strip(),
                'total_shares': total_shares,
                'current_mcap': current_mcap_yi,
                'current_pb': pb,
                'current_price': price,
            })

        df = pd.DataFrame(records)

        # 过滤ST/退市股
        mask_st = df['name'].str.contains(r'ST|退', na=False)
        df = df[~mask_st].copy()

        # 只保留A股代码（6位数字，以0/3/6开头）
        mask_a = df['code'].str.match(r'^[036]\d{5}$')
        df = df[mask_a].copy()

        self._stock_info = df.reset_index(drop=True)
        logging.info(f"[基本面] 从数据库获取到 {len(self._stock_info)} 只A股信息")

    def _fetch_stock_info_from_push2his(self):
        """从东方财富 push2his 端点获取股票信息（可靠，使用代理）"""
        from quantia.core.eastmoney_fetcher import eastmoney_fetcher
        logging.info("[基本面] 正在从 push2his 获取全市场股票数据...")

        fetcher = eastmoney_fetcher()
        url = 'https://push2his.eastmoney.com/api/qt/clist/get'
        all_data = []
        page = 1

        while True:
            params = {
                'pn': page, 'pz': 5000, 'po': '1', 'np': '1',
                'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
                'fltt': '2', 'invt': '2', 'fid': 'f20',
                'fs': 'm:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048',
                'fields': 'f12,f14,f2,f20,f23',
                '_': str(int(time.time() * 1000)),
            }
            r = fetcher.make_request(url, params=params)
            d = r.json()
            # 防御：d.get('data') 可能返回 None 而非 {}
            data_obj = d.get('data') or {}
            rows = data_obj.get('diff') or []
            total = data_obj.get('total', 0)
            all_data.extend(rows)
            if len(rows) == 0 or len(all_data) >= total:
                break
            page += 1
            time.sleep(0.3)

        logging.info(f"[基本面] push2his 获取到 {len(all_data)} 条记录")

        records = []
        for item in all_data:
            code = str(item.get('f12', ''))
            name = str(item.get('f14', ''))
            price = float(item.get('f2') or 0)
            total_mv = float(item.get('f20') or 0)  # 总市值(元)
            pb = float(item.get('f23') or 0)  # 市净率
            if price > 0 and total_mv > 0:
                total_shares = total_mv / price
                current_mcap_yi = total_mv / 1e8
                records.append({
                    'code': code, 'name': name,
                    'total_shares': total_shares,
                    'current_mcap': current_mcap_yi,
                    'current_pb': pb,
                    'current_price': price,
                })

        df = pd.DataFrame(records)

        # 过滤ST/退市股
        mask_st = df['name'].str.contains(r'ST|退', na=False)
        df = df[~mask_st].copy()

        # 只保留A股代码（6位数字，以0/3/6开头）
        mask_a = df['code'].str.match(r'^[036]\d{5}$')
        df = df[mask_a].copy()

        cols = ['code', 'name', 'total_shares', 'current_mcap', 'current_pb', 'current_price']
        for c in cols:
            if c not in df.columns:
                df[c] = 0
        self._stock_info = df[cols].reset_index(drop=True)
        logging.info(f"[基本面] 从 push2his 获取到 {len(self._stock_info)} 只A股信息")

    def _fetch_stock_info_from_api(self):
        """从东方财富在线API获取股票信息（备用方式）"""
        try:
            from quantia.core.crawling.stock_hist_em import stock_zh_a_spot_em
            logging.info("[基本面] 正在从东方财富API获取全市场股票数据...")
            df = stock_zh_a_spot_em()
            if df is None or len(df) == 0:
                return

            needed = ['代码', '名称', '最新价', '总市值']
            for c in needed:
                if c not in df.columns:
                    logging.error(f"[基本面] 缺少列: {c}")
                    return

            df = df[needed].copy()
            df.columns = ['code', 'name', 'price', 'total_mv']
            df['price'] = pd.to_numeric(df['price'], errors='coerce')
            df['total_mv'] = pd.to_numeric(df['total_mv'], errors='coerce')
            df = df[(df['price'] > 0) & (df['total_mv'] > 0)].copy()

            mask_st = df['name'].str.contains(r'ST|退', na=False)
            df = df[~mask_st].copy()
            mask_a = df['code'].str.match(r'^[036]\d{5}$')
            df = df[mask_a].copy()

            df['total_shares'] = df['total_mv'] / df['price']
            df['current_mcap'] = df['total_mv'] / 1e8
            df['current_pb'] = 0   # spot_em 不提供 PB，默认 0
            df['current_price'] = df['price']

            self._stock_info = df[['code', 'name', 'total_shares', 'current_mcap',
                                   'current_pb', 'current_price']].reset_index(drop=True)
            logging.info(f"[基本面] 从API获取到 {len(self._stock_info)} 只A股信息")

        except Exception as e:
            logging.error(f"[基本面] API获取股票数据失败: {e}")

    def _fetch_stock_info_from_cache(self):
        """从本地K线缓存文件推断股票信息（终极降级方案）"""
        import re, gzip, pickle
        cache_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'cache', 'hist')
        if not os.path.isdir(cache_dir):
            return
        logging.info("[基本面] 正在从本地K线缓存推断股票信息...")
        records = []
        for root, dirs, files in os.walk(cache_dir):
            for fname in files:
                if not fname.endswith('qfq.gzip.pickle'):
                    continue
                code = fname.replace('qfq.gzip.pickle', '')
                if not re.match(r'^[036]\d{5}$', code):
                    continue
                fpath = os.path.join(root, fname)
                try:
                    with gzip.open(fpath, 'rb') as f:
                        df = pickle.load(f)
                    if df is None or len(df) == 0:
                        continue
                    last = df.iloc[-1]
                    price = float(last.get('close', last.get('收盘', 0)))
                    volume = float(last.get('volume', last.get('成交量', 0)))
                    if price <= 0:
                        continue
                    # Estimate market cap from volume and price (rough approximation)
                    # volume is in 手 (lots of 100 shares), typical float ratio ~30-50%
                    estimated_total_shares = volume * 100 * 3 if volume > 0 else 1e8
                    estimated_mcap = estimated_total_shares * price / 1e8  # 亿
                    records.append({
                        'code': code, 'name': '',
                        'total_shares': estimated_total_shares,
                        'current_mcap': max(estimated_mcap, 5),  # minimum 5亿
                        'current_pb': 0,
                        'current_price': price,
                    })
                except Exception:
                    continue
        if records:
            self._stock_info = pd.DataFrame(records)
            logging.info(f"[基本面] 从缓存推断到 {len(self._stock_info)} 只A股信息")

    def _batch_load_klines(self):
        """批量加载候选股票K线数据（多线程并行，带重试）"""
        from .data_feed import _load_from_cache, _fetch_stock_from_eastmoney, _save_cache

        total = len(self._candidate_codes)
        loaded = 0
        fetched = 0
        failed = 0

        logging.info(f"[基本面] 正在加载 {total} 只候选股票K线数据...")

        # Phase 1: 从缓存加载
        need_fetch = []
        for code in self._candidate_codes:
            df = _load_from_cache(code)
            if df is not None and len(df) > 0:
                self._build_price_lookup(code, df)
                loaded += 1
            else:
                need_fetch.append(code)

        logging.info(f"[基本面] 缓存命中: {loaded}, 需在线获取: {len(need_fetch)}")

        # Phase 2: 从东方财富获取（多线程并行）
        if need_fetch:
            est_seconds = len(need_fetch) * 0.3
            logging.info(f"[基本面] 正在从东方财富获取 {len(need_fetch)} 只股票K线..."
                         f" (预计 {est_seconds:.0f} 秒)")

            def _fetch_one(code):
                for attempt in range(3):
                    try:
                        df = _fetch_stock_from_eastmoney(code, '20230101')
                        if df is not None and len(df) > 0:
                            _save_cache(code, df)
                            return (code, df)
                    except Exception:
                        if attempt < 2:
                            time.sleep(1 + attempt)
                return (code, None)

            with ThreadPoolExecutor(max_workers=8) as executor:
                futures = {executor.submit(_fetch_one, code): code for code in need_fetch}
                done_count = 0
                for future in as_completed(futures):
                    code, df = future.result()
                    done_count += 1
                    if df is not None:
                        self._build_price_lookup(code, df)
                        fetched += 1
                    else:
                        failed += 1
                    if done_count % 200 == 0:
                        logging.info(f"[基本面] 进度: {done_count}/{len(need_fetch)} "
                                     f"(成功={fetched}, 失败={failed})")

        total_loaded = loaded + fetched
        logging.info(f"[基本面] K线数据加载完成: {total_loaded}/{total} 只 "
                     f"(缓存={loaded}, 在线={fetched}, 失败={failed})")

    def _build_price_lookup(self, code, df):
        """构建价格和成交量快速查找字典"""
        prices = {}
        volumes = {}
        for _, row in df.iterrows():
            d = row['date']
            if hasattr(d, 'strftime'):
                d_str = d.strftime('%Y-%m-%d')
            else:
                d_str = str(d)[:10]
            prices[d_str] = float(row['close'])
            volumes[d_str] = int(row.get('volume', 0))
        self._price_lookup[code] = prices
        self._volume_lookup[code] = volumes

    def get_fundamentals(self, q, date=None):
        """
        执行聚宽风格基本面查询。

        对于 valuation 字段（market_cap, pb_ratio），使用真实K线数据估算。
        对于 indicator/balance/cash_flow 字段，使用基于股票代码的确定性合成值。
        """
        self._init_data()

        if date is None:
            date = self._engine.context.current_dt
        date_str = date.strftime('%Y-%m-%d') if hasattr(date, 'strftime') else str(date)[:10]

        # 提取 in_ code 列表
        in_codes = None
        for f in q._filters:
            if isinstance(f, tuple) and len(f) >= 3 and f[0] == 'in_' and f[1] == 'code':
                in_codes = set(f[2])
                break

        if in_codes:
            self._ensure_stocks_loaded(in_codes)

        # 构建基础 DataFrame（含 code + valuation 字段）
        extra_key = ','.join(sorted(in_codes)) if in_codes else ''
        cache_key = f"{date_str}|{extra_key}"
        if cache_key in self._daily_mcap_cache:
            df = self._daily_mcap_cache[cache_key].copy()
        else:
            records = []
            if self._stock_info is not None:
                info_map = {}
                for _, row in self._stock_info.iterrows():
                    info_map[row['code']] = {
                        'total_shares': row['total_shares'],
                        'current_pb': row.get('current_pb', 0),
                        'current_price': row.get('current_price', 0),
                    }

                query_codes = set(self._candidate_codes)
                if in_codes:
                    query_codes = query_codes | in_codes

                for code in query_codes:
                    prices = self._price_lookup.get(code)
                    if prices is None:
                        continue
                    close = prices.get(date_str, 0)
                    if close <= 0:
                        continue
                    info = info_map.get(code)
                    if info is None:
                        continue
                    ts = info['total_shares']
                    if ts > 0:
                        mcap = ts * close / 1e8
                        cur_pb = info.get('current_pb', 0)
                        cur_price = info.get('current_price', 0)
                        if cur_pb > 0 and cur_price > 0:
                            pb_ratio = cur_pb * (close / cur_price)
                        else:
                            pb_ratio = 0
                        records.append({
                            'code': code,
                            'market_cap': mcap,
                            'pb_ratio': round(pb_ratio, 4),
                        })

            df = pd.DataFrame(records) if records else pd.DataFrame(
                columns=['code', 'market_cap', 'pb_ratio'])
            # 有界缓存：超出上限时淘汰最早写入的条目，避免长区间回测内存无界增长
            if len(self._daily_mcap_cache) >= self._MCAP_CACHE_MAX:
                oldest_key = next(iter(self._daily_mcap_cache))
                del self._daily_mcap_cache[oldest_key]
            self._daily_mcap_cache[cache_key] = df

        if len(df) == 0:
            return df

        result = df.copy()

        # 收集查询中使用的所有缺失字段名（含 valuation 中未预计算的字段如 pe_ratio）
        needed_fields = set()
        for field_expr in q._fields:
            if isinstance(field_expr, _FieldExpr) and field_expr._name not in result.columns:
                needed_fields.add(field_expr._name)
        for f in q._filters:
            if isinstance(f, tuple):
                if f[0].startswith('div_') and len(f) >= 4:
                    needed_fields.add(f[1])
                    needed_fields.add(f[2])
                elif len(f) >= 3 and f[1] not in result.columns:
                    needed_fields.add(f[1])

        # 为缺失的字段生成合成数据（基于股票代码的确定性哈希）
        if needed_fields:
            self._generate_synthetic_fields(result, needed_fields)

        # 应用过滤条件
        for f in q._filters:
            if not isinstance(f, tuple) or len(f) < 3:
                continue
            op = f[0]
            if op.startswith('div_') and len(f) >= 4:
                # 除法表达式过滤: div_lt, div_gt, div_le, div_ge
                num_col, den_col, threshold = f[1], f[2], f[3]
                if num_col in result.columns and den_col in result.columns:
                    ratio = result[num_col] / result[den_col].replace(0, np.nan)
                    cmp = op.split('_', 1)[1]
                    if cmp == 'lt':
                        result = result[ratio < threshold]
                    elif cmp == 'gt':
                        result = result[ratio > threshold]
                    elif cmp == 'le':
                        result = result[ratio <= threshold]
                    elif cmp == 'ge':
                        result = result[ratio >= threshold]
                continue

            field = f[1]
            if field not in result.columns:
                continue
            if op == 'between' and len(f) >= 4:
                result = result[(result[field] >= f[2]) & (result[field] <= f[3])]
            elif op == 'gt':
                result = result[result[field] > f[2]]
            elif op == 'lt':
                result = result[result[field] < f[2]]
            elif op == 'ge':
                result = result[result[field] >= f[2]]
            elif op == 'le':
                result = result[result[field] <= f[2]]
            elif op == 'in_':
                result = result[result[field].isin(f[2])]

        # 应用排序
        if q._order_by_clause is not None and isinstance(q._order_by_clause, tuple):
            direction, field = q._order_by_clause
            ascending = (direction == 'asc')
            if field in result.columns:
                result = result.sort_values(field, ascending=ascending)

        # 应用限制
        if q._limit_val is not None:
            result = result.head(q._limit_val)

        # 动态返回查询中请求的列
        out_cols = ['code']
        for field_expr in q._fields:
            if isinstance(field_expr, _FieldExpr):
                col = field_expr._name
                if col != 'code' and col in result.columns and col not in out_cols:
                    out_cols.append(col)
        # 兜底：加入 valuation 常用列
        for c in ['market_cap', 'pb_ratio']:
            if c in result.columns and c not in out_cols:
                out_cols.append(c)
        return result[[c for c in out_cols if c in result.columns]].reset_index(drop=True)

    # ── 合成基本面数据 ──

    # 聚宽字段名 → cn_stock_financial 数据库字段名的映射
    # 注：inc_total_revenue_year_on_year 和 inc_revenue_year_on_year 均映射到 revenue_yoy，
    # 因为东方财富只提供"营业总收入同比增长"一个字段，二者含义近似，作为兼容性兜底。
    _FIELD_DB_MAP = {
        'inc_total_revenue_year_on_year': 'revenue_yoy',
        'inc_net_profit_year_on_year': 'net_profit_yoy',
        'inc_revenue_year_on_year': 'revenue_yoy',
        'roe': 'roe',
        'eps': 'eps',
        'net_profit_margin': 'net_profit_margin',
        'gross_profit_margin': 'gross_margin',
    }

    # 字段默认值范围：(mean, std) — 用正态分布 + code hash 种子生成（兜底合成）
    _SYNTHETIC_FIELD_RANGES = {
        'inc_total_revenue_year_on_year': (20.0, 15.0),
        'inc_net_profit_year_on_year': (25.0, 20.0),
        'inc_revenue_year_on_year': (18.0, 12.0),
        'roe': (12.0, 6.0),
        'eps': (0.8, 0.5),
        'pe_ratio': (25.0, 15.0),
        'circulating_market_cap': (80.0, 50.0),
        'net_profit_margin': (10.0, 8.0),
        'gross_profit_margin': (30.0, 15.0),
        'total_liability': (5e9, 3e9),
        'total_assets': (1.2e10, 5e9),
        'total_current_assets': (6e9, 3e9),
        'total_current_liability': (3e9, 2e9),
        'net_operate_cash_flow': (5e8, 4e8),
        'net_invest_cash_flow': (-2e8, 3e8),
        'net_finance_cash_flow': (-1e8, 2e8),
    }

    def _load_real_financial_data(self, codes, date_str):
        """从 cn_stock_financial 表加载真实财务数据

        Args:
            codes: 股票代码列表
            date_str: 回测日期（用于查找该日期之前的最新报告期）

        Returns:
            dict: {code: {db_field: value, ...}, ...}
        """
        try:
            from quantia.job.stock_financial_data import get_financial_data_batch
            return get_financial_data_batch(list(codes), report_date=date_str)
        except Exception as e:
            logging.warning(f"[基本面] 加载真实财务数据失败: {e}")
            return {}

    def _generate_synthetic_fields(self, df, fields):
        """为 DataFrame 中缺失的字段填充值。

        优先级：
        1. 真实财务数据（cn_stock_financial 表直查）
        2. 从真实数据推算（如 total_assets = net_profit / roa * 100）
        3. 若真实数据基础设施可用但该股票无记录 → NaN（排除该股票）
        4. 若真实数据基础设施不可用（表不存在等） → 确定性合成值（兼容降级）
        """
        # 获取当前回测日期
        current_dt = getattr(self._engine, 'context', None)
        quarter_key = ''
        date_str = None
        if current_dt and hasattr(current_dt, 'current_dt'):
            dt = current_dt.current_dt
            if hasattr(dt, 'year'):
                quarter_key = f"{dt.year}Q{(dt.month - 1) // 3 + 1}"
                date_str = dt.strftime('%Y-%m-%d') if hasattr(dt, 'strftime') else str(dt)[:10]

        # 尝试加载真实财务数据
        real_data = {}
        if date_str and len(df) > 0:
            real_data = self._load_real_financial_data(df['code'].tolist(), date_str)

        # 判断真实财务数据基础设施是否可用：
        # 如果成功查到了任何股票的数据，说明 cn_stock_financial 表存在且有数据；
        # 此时没有查到数据的股票确实在表中不存在记录，应用 NaN 排除而非合成随机值。
        # 如果一条都没查到（表不存在或为空），则降级到合成值（向后兼容）。
        use_nan_for_missing = len(real_data) > 0

        if use_nan_for_missing:
            no_data_count = sum(1 for code in df['code'] if code not in real_data)
            if no_data_count > 0:
                logging.info(f"[基本面] {len(df)}只候选中{len(real_data)}只有财务数据，"
                             f"{no_data_count}只无数据将被 NaN 标记（策略 dropna 时排除）")

        for fname in fields:
            if fname in df.columns:
                continue

            db_field = self._FIELD_DB_MAP.get(fname)
            values = []

            for code in df['code']:
                real_val = None

                # 真实数据基础设施可用，但该股票无记录 → NaN 排除
                if use_nan_for_missing and code not in real_data:
                    values.append(np.nan)
                    continue

                # 尝试从真实数据获取（直接映射字段）
                if db_field and code in real_data:
                    real_val = real_data[code].get(db_field)
                    if real_val is not None:
                        try:
                            real_val = float(real_val)
                        except (TypeError, ValueError):
                            real_val = None

                # 特殊字段：从真实数据推算
                if real_val is None and code in real_data:
                    rd = real_data[code]
                    if fname == 'total_assets':
                        roa = rd.get('roa')
                        np_ = rd.get('net_profit')
                        if roa is not None and np_ is not None and float(roa) != 0:
                            try:
                                real_val = float(np_) / (float(roa) / 100)
                            except (TypeError, ValueError, ZeroDivisionError):
                                pass
                    elif fname == 'total_liability':
                        alr = rd.get('asset_liability_ratio')
                        roa_val = rd.get('roa')
                        np_val = rd.get('net_profit')
                        if alr is not None and roa_val is not None and np_val is not None and float(roa_val) != 0:
                            try:
                                ta = float(np_val) / (float(roa_val) / 100)
                                real_val = ta * (float(alr) / 100)
                            except (TypeError, ValueError, ZeroDivisionError):
                                pass
                    elif fname == 'pe_ratio':
                        # pe_ratio = close_price / eps
                        eps_val = rd.get('eps')
                        if eps_val is not None:
                            try:
                                eps_f = float(eps_val)
                                if eps_f > 0 and date_str:
                                    prices = self._price_lookup.get(code)
                                    close = prices.get(date_str, 0) if prices else 0
                                    if close > 0:
                                        real_val = close / eps_f
                            except (TypeError, ValueError, ZeroDivisionError):
                                pass
                    elif fname == 'circulating_market_cap':
                        # circulating_market_cap ≈ market_cap（无流通股数据时近似）
                        if 'market_cap' in df.columns:
                            idx = df.index[df['code'] == code]
                            if len(idx) > 0:
                                real_val = df.loc[idx[0], 'market_cap']
                    elif fname == 'net_operate_cash_flow':
                        ocfps = rd.get('ocfps')
                        if ocfps is not None and self._stock_info is not None:
                            match = self._stock_info.loc[
                                self._stock_info['code'] == code, 'total_shares']
                            if len(match) > 0 and match.iloc[0] > 0:
                                try:
                                    real_val = float(ocfps) * match.iloc[0]
                                except (TypeError, ValueError):
                                    pass

                if real_val is not None:
                    values.append(real_val)
                elif use_nan_for_missing:
                    # 有真实数据基础设施但该字段无法解析 → NaN（保持数据诚实性）
                    values.append(np.nan)
                else:
                    # 完全无真实数据基础设施 → 确定性合成值（向后兼容降级）
                    mean, std = self._SYNTHETIC_FIELD_RANGES.get(fname, (50.0, 20.0))
                    seed = hash(code + fname + quarter_key) & 0xFFFFFFFF
                    rng = np.random.RandomState(seed)
                    values.append(rng.normal(mean, std))

            df[fname] = values

    def _ensure_stocks_loaded(self, codes):
        """确保指定股票的 K 线数据已加载（用于 in_ 过滤的非候选股）"""
        from .data_feed import _load_from_cache, _fetch_stock_from_eastmoney, _save_cache

        need_load = [c for c in codes
                     if c not in self._price_lookup
                     and (self._stock_info is not None
                          and c in self._stock_info['code'].values)]
        if not need_load:
            return

        logging.info(f"[基本面] 延迟加载 {len(need_load)} 只额外股票 K 线")
        newly_loaded = False
        for code in need_load:
            df = _load_from_cache(code)
            if df is not None and len(df) > 0:
                self._build_price_lookup(code, df)
                newly_loaded = True
                continue
            for attempt in range(3):
                try:
                    df = _fetch_stock_from_eastmoney(code, '20230101')
                    if df is not None and len(df) > 0:
                        _save_cache(code, df)
                        self._build_price_lookup(code, df)
                        newly_loaded = True
                        break
                except Exception:
                    if attempt < 2:
                        time.sleep(1 + attempt)
        # 把新加载的股票持久化到基本面缓存，避免下次重复请求 API
        if newly_loaded:
            self._save_fundamental_cache()

    def is_paused(self, code, date=None):
        """检查股票是否停牌（当日无成交量或无数据视为停牌）。

        优先使用回测引擎已加载（且按策略实际股票池有界）的 K 线判断停牌，
        仅在必要时按需加载单只股票，**绝不触发全市场基本面批量加载**，
        从根本上避免 get_current_data()[code].paused 导致的内存暴涨/OOM。
        """
        if date is None and self._engine is not None:
            date = self._engine.context.current_dt

        # 路径一：引擎已加载的 K 线（有界，按策略股票池）
        if self._engine is not None:
            df = self._engine._stock_data.get(code)
            if df is None:
                try:
                    # 仅加载单只股票，不会触发全市场批量加载
                    self._engine._ensure_stock_loaded(code)
                    df = self._engine._stock_data.get(code)
                except Exception:
                    df = None
            if df is not None and len(df) > 0 and 'volume' in df.columns:
                subset = df.loc[:pd.Timestamp(date)]
                if len(subset) == 0:
                    return True  # 当日及之前均无 bar = 未上市/停牌
                last_d = pd.Timestamp(subset.index[-1]).date()
                cur_d = pd.Timestamp(date).date()
                if last_d != cur_d:
                    return True  # 当日无 bar = 停牌
                vol = subset['volume'].iloc[-1]
                return bool(pd.isna(vol) or vol == 0)

        # 路径二：回退到基本面 _volume_lookup（仅当策略使用过基本面 API 时才有数据）
        date_str = date.strftime('%Y-%m-%d') if hasattr(date, 'strftime') else str(date)[:10]
        volumes = self._volume_lookup.get(code)
        if volumes is None:
            return True  # 无数据 = 停牌
        vol = volumes.get(date_str, -1)
        if vol < 0:
            return True  # 当日无数据 = 停牌
        return vol == 0

    # ── 缓存管理 ──

    def _load_fundamental_cache(self):
        """加载基本面数据缓存"""
        cache_file = os.path.join(_CACHE_DIR, 'fundamental_v3.pickle')
        if not os.path.exists(cache_file):
            return False
        try:
            mtime = os.path.getmtime(cache_file)
            if time.time() - mtime > 7 * 86400:  # 7天过期
                logging.info("[基本面] 缓存已过期（>7天），重新获取")
                return False
            with open(cache_file, 'rb') as f:
                data = pickle.load(f)
            self._stock_info = data['stock_info']
            self._price_lookup = data['price_lookup']
            self._volume_lookup = data['volume_lookup']
            self._candidate_codes = data['candidate_codes']
            logging.info(f"[基本面] 从缓存加载: {len(self._candidate_codes)} 只候选股票，"
                         f"{len(self._price_lookup)} 只有K线数据")
            return True
        except Exception as e:
            logging.warning(f"[基本面] 缓存加载失败: {e}")
            return False

    def _save_fundamental_cache(self):
        """保存基本面数据缓存（原子写入：写临时文件后 os.replace，避免并发读到半写文件）"""
        try:
            os.makedirs(_CACHE_DIR, exist_ok=True)
            cache_file = os.path.join(_CACHE_DIR, 'fundamental_v3.pickle')
            tmp_file = cache_file + '.tmp'
            data = {
                'stock_info': self._stock_info,
                'price_lookup': self._price_lookup,
                'volume_lookup': self._volume_lookup,
                'candidate_codes': self._candidate_codes,
            }
            with open(tmp_file, 'wb') as f:
                pickle.dump(data, f)
            os.replace(tmp_file, cache_file)
            size_mb = os.path.getsize(cache_file) / 1e6
            logging.info(f"[基本面] 缓存已保存 ({size_mb:.1f} MB)")
        except Exception as e:
            logging.warning(f"[基本面] 缓存保存失败: {e}")
            try:
                if os.path.exists(tmp_file):
                    os.remove(tmp_file)
            except Exception:
                pass


# ── get_current_data() 代理对象 ──

class _CurrentDataProxy:
    """get_current_data() 返回的代理对象 — dict-like, proxy[code].paused"""

    def __init__(self, provider, engine=None):
        self._provider = provider
        self._engine = engine

    def __getitem__(self, code):
        # 不在此处触发 provider._init_data()：停牌/涨跌停/价格判断改由
        # _CurrentStockInfo 直接从引擎已加载（有界）的 K 线解析。
        # 这样 get_current_data()[code].paused 不会误触发全市场基本面
        # 批量 K 线加载，从根本上避免内存暴涨/OOM。
        return _CurrentStockInfo(code, self._provider, self._engine)


class _CurrentStockInfo:
    """单只股票的当前数据"""

    def __init__(self, code, provider, engine=None):
        self._code = code
        self._provider = provider
        self._engine = engine

    @property
    def paused(self):
        """是否停牌"""
        return self._provider.is_paused(self._code)

    @property
    def is_st(self):
        """是否ST（简化实现：返回False）"""
        return False

    @property
    def name(self):
        """股票名称（优先从已加载的基本面数据获取）"""
        if self._provider and self._provider._stock_info is not None:
            info = self._provider._stock_info
            match = info.loc[info['code'] == self._code, 'name']
            if len(match) > 0:
                return str(match.iloc[0])
        return ''

    @property
    def last_price(self):
        """最新价格"""
        if self._engine:
            df = self._engine._stock_data.get(self._code)
            if df is not None and len(df) > 0:
                import pandas as _pd
                current_dt = self._engine.context.current_dt
                mask = df['date'] <= _pd.Timestamp(current_dt)
                subset = df.loc[mask]
                if len(subset) > 0:
                    return float(subset['close'].iloc[-1])
        return 0.0

    @property
    def high_limit(self):
        """涨停价（简化：前收盘价 * 1.1）"""
        if self._engine:
            df = self._engine._stock_data.get(self._code)
            if df is not None and len(df) > 1:
                import pandas as _pd
                current_dt = self._engine.context.current_dt
                mask = df['date'] <= _pd.Timestamp(current_dt)
                subset = df.loc[mask]
                if len(subset) >= 2:
                    prev_close = float(subset['close'].iloc[-2])
                    return round(prev_close * 1.1, 2)
        return 999999.0

    @property
    def low_limit(self):
        """跌停价（简化：前收盘价 * 0.9）"""
        if self._engine:
            df = self._engine._stock_data.get(self._code)
            if df is not None and len(df) > 1:
                import pandas as _pd
                current_dt = self._engine.context.current_dt
                mask = df['date'] <= _pd.Timestamp(current_dt)
                subset = df.loc[mask]
                if len(subset) >= 2:
                    prev_close = float(subset['close'].iloc[-2])
                    return round(prev_close * 0.9, 2)
        return 0.01
