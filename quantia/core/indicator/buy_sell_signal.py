#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""指标买卖信号筛选（超卖深跌抄底 / 超买见顶派发）。

业务定义（用户确认 2026）：
- 买入：自历史最高点深跌（现价 ≤ (1-回撤比例) × 历史最高高点）+ 指标极度超卖
        + 排除 ST / *ST / 退市风险股 +（可选）基本面区间过滤（默认关闭）。
- 卖出：买入的镜像 —— 现价贴近历史最高（现价 ≥ 回撤比例 × 历史最高高点）+ 指标极度超买
        + 排除 ST / *ST / 退市风险股。

所有阈值均可由用户在前端「指标设置」页调整，持久化到 cn_strategy_params
（strategy_key='indicator_signal'）。本模块在 cron job 中运行，运行时从 DB 读取
用户参数（无配置则回退到 DEFAULT_PARAMS），因此调参后需下一次 cron 运行（或前端
「立即重算」按钮触发 recompute）才生效。

历史最高点需要全量 K 线历史，单日 cn_stock_indicators 表无法提供，因此采用
"SQL 预筛 → 仅对极少数候选回读缓存判定回撤" 的两段式：
先用极严超卖/超买 + 排除 ST(+可选基本面) 把候选收敛到个位数，
再对这几只回读 K 线缓存计算历史最高点，避免全市场遍历（内存安全）。
"""

import json
import logging

import pandas as pd

import quantia.core.tablestructure as tbs
import quantia.lib.database as mdb
import quantia.core.stockfetch as stf

# 持久化键：复用 cn_strategy_params 键值表，与前端「指标设置」页对应。
PARAMS_STRATEGY_KEY = 'indicator_signal'

# ── 默认参数值（前端 UI schema 的 value 引用这里，避免双处漂移）──
DEFAULT_PARAMS = {
    # 买入：极度超卖阈值
    'buy_rsi_6': 15,
    'buy_kdjj': 0,
    'buy_wr_6': -90,
    'buy_cci': -150,
    'buy_mfi': 20,
    # 买入：自历史最高的最小回撤比例（0.80 = 跌掉 80% 以上）
    'buy_drawdown_ratio': 0.80,
    # 卖出：极度超买阈值
    'sell_rsi_6': 85,
    'sell_kdjj': 100,
    'sell_wr_6': -10,
    'sell_cci': 150,
    'sell_mfi': 80,
    # 卖出：贴近历史最高的比例（0.80 = 现价 ≥ 峰值 80%）
    'sell_drawdown_ratio': 0.80,
    # 风险排除
    'exclude_st': 1,
    'exclude_delist': 1,
    # 基本面可选过滤（默认关闭；启用后买入信号与 cn_stock_spot 同日 JOIN）
    'fund_filter_enabled': 0,
    'fund_pe_min': 0,
    'fund_pe_max': 20,
    'fund_pb_max': 10,
    'fund_roe_min': 15,
}

# ST / *ST / 退市风险（名称含 ST 或 退）。作为参数传入，避免 % 转义问题。
_ST_LIKE = '%ST%'
_DELIST_LIKE = '%退%'


def load_params():
    """从 cn_strategy_params 读取用户调整后的参数，合并到 DEFAULT_PARAMS。

    表不存在 / 读取失败 / 无配置 → 全部回退默认值（保证 cron 永不因缺配置中断）。
    """
    params = dict(DEFAULT_PARAMS)
    try:
        if not mdb.checkTableIsExist('cn_strategy_params'):
            return params
        rows = mdb.executeSqlFetch(
            "SELECT `param_key`, `param_value` FROM `cn_strategy_params` WHERE `strategy_key` = %s",
            (PARAMS_STRATEGY_KEY,))
        if not rows:
            return params
        for key, raw in rows:
            if key not in DEFAULT_PARAMS or raw is None:
                continue
            val = raw
            if isinstance(raw, str):
                try:
                    val = json.loads(raw)
                except (TypeError, ValueError):
                    continue
            params[key] = val
    except Exception:
        logging.debug("load_params 读取 cn_strategy_params 异常，使用默认值", exc_info=True)
    return params


def _to_num(v, default):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _build_oversold(p):
    return (f"i.`rsi_6` < {_to_num(p['buy_rsi_6'], 15)} "
            f"AND i.`kdjj` < {_to_num(p['buy_kdjj'], 0)} "
            f"AND i.`wr_6` < {_to_num(p['buy_wr_6'], -90)} "
            f"AND i.`cci` < {_to_num(p['buy_cci'], -150)} "
            f"AND i.`mfi` < {_to_num(p['buy_mfi'], 20)}")


def _build_overbought(p):
    return (f"i.`rsi_6` > {_to_num(p['sell_rsi_6'], 85)} "
            f"AND i.`kdjj` > {_to_num(p['sell_kdjj'], 100)} "
            f"AND i.`wr_6` > {_to_num(p['sell_wr_6'], -10)} "
            f"AND i.`cci` > {_to_num(p['sell_cci'], 150)} "
            f"AND i.`mfi` > {_to_num(p['sell_mfi'], 80)}")


def _peak_drawdown_ok(code, date_str, mode, ratio):
    """回读个股 K 线缓存，判定现价相对历史最高点的位置是否满足条件。

    mode='buy' : 现价 ≤ (1-ratio) × 历史最高高点（深跌抄底）
    mode='sell': 现价 ≥ ratio × 历史最高高点（贴近峰值派发）

    仅读缓存，绝不发起 API 请求。无缓存 / 数据异常 → False（保守，不发信号）。
    """
    try:
        hist = stf.read_stock_hist_from_cache(code, '1990-01-01', '2099-12-31')
        if hist is None or len(hist) == 0:
            return False
        if 'high' not in hist.columns or 'close' not in hist.columns or 'date' not in hist.columns:
            return False

        # 只看 <= date_str 的历史（防止用到未来数据）：历史最高与现价都基于该截面，
        # 否则对历史日期 recompute 时会用未来高点判定回撤，产生前视偏差（look-ahead bias）。
        d = pd.to_datetime(hist['date'], errors='coerce')
        target = pd.to_datetime(str(date_str)[:10], errors='coerce')
        mask = (d <= target) if not pd.isna(target) else d.notna()
        sub = hist[mask]
        sub_dates = d[mask]
        if len(sub) == 0:
            return False

        peak = pd.to_numeric(sub['high'], errors='coerce').max()
        if pd.isna(peak) or peak <= 0:
            return False

        # 现价取截面内日期最大的那一行（缓存顺序不保证升序，不能用 iloc[-1]）。
        latest_idx = sub_dates.idxmax()
        latest_close = pd.to_numeric(hist.loc[latest_idx, 'close'], errors='coerce')
        if pd.isna(latest_close) or latest_close <= 0:
            return False

        peak = float(peak)
        latest_close = float(latest_close)
        ratio = float(ratio)
        if mode == 'buy':
            return latest_close <= (1.0 - ratio) * peak
        return latest_close >= ratio * peak
    except Exception:
        logging.debug("peak drawdown gate 异常: %s", code, exc_info=True)
        return False


def _apply_drawdown_gate(data, mode, ratio):
    """对 SQL 预筛后的极少数候选逐只回读缓存，应用历史最高点回撤闸门。"""
    if data is None or len(data.index) == 0:
        return None
    keep_idx = [idx for idx, row in data.iterrows()
                if _peak_drawdown_ok(row['code'], row['date'], mode, ratio)]
    if not keep_idx:
        return None
    return data.loc[keep_idx].copy()


def _name_exclude_clause(p, params_list):
    """根据 exclude_st / exclude_delist 拼接名称排除条件，并追加对应 LIKE 参数。"""
    clauses = []
    if int(_to_num(p.get('exclude_st', 1), 1)):
        clauses.append("i.`name` NOT LIKE %s")
        params_list.append(_ST_LIKE)
    if int(_to_num(p.get('exclude_delist', 1), 1)):
        clauses.append("i.`name` NOT LIKE %s")
        params_list.append(_DELIST_LIKE)
    return (" AND " + " AND ".join(clauses)) if clauses else ""


def select_buy_signals(date, params=None):
    """超卖深跌抄底 + 排除 ST/退市 +（可选）基本面区间。返回 (date,code,name) DataFrame 或 None。

    参数从 cn_strategy_params 读取（params=None 时自动 load_params）。
    基本面过滤默认关闭；启用时与 cn_stock_spot（同日）JOIN 并按 PE/PB/ROE 区间过滤。
    """
    p = params if params is not None else load_params()
    ind = tbs.TABLE_CN_STOCK_INDICATORS['name']
    if not mdb.checkTableIsExist(ind):
        return None

    fk = tuple(tbs.TABLE_CN_STOCK_FOREIGN_KEY['columns'])
    selcol = ', '.join(f"i.`{c}`" for c in fk)
    sql_params = []

    join_clause = ''
    fund_clause = ''
    if int(_to_num(p.get('fund_filter_enabled', 0), 0)) and mdb.checkTableIsExist('cn_stock_spot'):
        join_clause = " JOIN `cn_stock_spot` b ON i.`code` = b.`code` AND i.`date` = b.`date`"
        fund_clause = (f" AND b.`pe9` > {_to_num(p['fund_pe_min'], 0)} "
                       f"AND b.`pe9` <= {_to_num(p['fund_pe_max'], 20)} "
                       f"AND b.`pbnewmrq` <= {_to_num(p['fund_pb_max'], 10)} "
                       f"AND b.`roe_weight` >= {_to_num(p['fund_roe_min'], 15)}")

    name_clause = _name_exclude_clause(p, sql_params)
    sql = (f"SELECT {selcol} FROM `{ind}` i{join_clause} "
           f"WHERE i.`date` = %s AND {_build_oversold(p)}{fund_clause}{name_clause}")
    sql_params.insert(0, date)
    data = pd.read_sql(sql=sql, con=mdb.engine(), params=tuple(sql_params))
    data = data.drop_duplicates(subset='code', keep='last')
    return _apply_drawdown_gate(data, 'buy', _to_num(p.get('buy_drawdown_ratio', 0.80), 0.80))


def select_sell_signals(date, params=None):
    """超买见顶派发 + 贴近历史峰值 + 排除 ST/退市。返回 DataFrame 或 None。"""
    p = params if params is not None else load_params()
    ind = tbs.TABLE_CN_STOCK_INDICATORS['name']
    if not mdb.checkTableIsExist(ind):
        return None

    fk = tuple(tbs.TABLE_CN_STOCK_FOREIGN_KEY['columns'])
    selcol = ', '.join(f"i.`{c}`" for c in fk)
    sql_params = []
    name_clause = _name_exclude_clause(p, sql_params)
    sql = (f"SELECT {selcol} FROM `{ind}` i "
           f"WHERE i.`date` = %s AND {_build_overbought(p)}{name_clause}")
    sql_params.insert(0, date)
    data = pd.read_sql(sql=sql, con=mdb.engine(), params=tuple(sql_params))
    data = data.drop_duplicates(subset='code', keep='last')
    return _apply_drawdown_gate(data, 'sell', _to_num(p.get('sell_drawdown_ratio', 0.80), 0.80))


def _store_signals(date, data, table_meta):
    """将信号 DataFrame 写入买/卖表（与 job 写库逻辑一致：删旧日 + 补回测列 + upsert）。"""
    table_name = table_meta['name']
    if mdb.checkTableIsExist(table_name):
        mdb.executeSql(f"DELETE FROM `{table_name}` WHERE `date` = %s", (date,))
        cols_type = None
    else:
        cols_type = tbs.get_field_types(table_meta['columns'])
    _columns_backtest = list(tbs.TABLE_CN_STOCK_BACKTEST_DATA['columns'])
    data = data.reindex(columns=list(data.columns) + _columns_backtest)
    mdb.insert_db_from_df(data, table_name, cols_type, False, "`date`,`code`")


def _delete_day(table_meta, date):
    t = table_meta['name']
    if mdb.checkTableIsExist(t):
        mdb.executeSql(f"DELETE FROM `{t}` WHERE `date` = %s", (date,))


def recompute(date, params=None):
    """用当前（或传入）参数立即重算并写入买/卖信号表。供前端「立即重算」按钮调用。

    仅读取 cn_stock_indicators + K 线缓存，写入 cn_stock_indicators_buy/sell；不发外部请求。
    返回 {'buy': n_buy, 'sell': n_sell}。
    """
    p = params if params is not None else load_params()
    buy = select_buy_signals(date, p)
    sell = select_sell_signals(date, p)
    n_buy = 0 if buy is None else len(buy.index)
    n_sell = 0 if sell is None else len(sell.index)
    if n_buy:
        _store_signals(date, buy, tbs.TABLE_CN_STOCK_INDICATORS_BUY)
    else:
        # 无买入信号时也清掉当日旧数据，避免展示陈旧结果
        _delete_day(tbs.TABLE_CN_STOCK_INDICATORS_BUY, date)
    if n_sell:
        _store_signals(date, sell, tbs.TABLE_CN_STOCK_INDICATORS_SELL)
    else:
        _delete_day(tbs.TABLE_CN_STOCK_INDICATORS_SELL, date)
    return {'buy': n_buy, 'sell': n_sell}
