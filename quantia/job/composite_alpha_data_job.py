#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""综合多因子选股作业 composite_alpha_v1（独立横截面 job，Analysis 管道）。

设计依据：core/strategy/document/综合选股策略方案_多因子融合与回测优化_V1.md（6.5 修订 + 11 实证）。

- 横截面打分（一次看到全部候选），非逐票 check，故不进 TABLE_CN_STOCK_STRATEGIES。
- 数据源 cn_stock_selection（含基本面 fund + 估值 pe9/pbnewmrq）。
- 先用 fund+value 初筛候选池（≈prefilter_n），再对候选在 K 线缓存上算技术因子（低波/斜率/动量），
  重算 fund+value+tech 综合分（对齐回测口径，避免全市场 K 线计算，见 6.3）。
- 大盘择时：沪深300 低于 regime_ma 日均线则当日空仓（不出手）。
- 双门槛选股（quality_gate + trade_gate），结果落 cn_stock_strategy_composite_alpha_v1。

纯计算核心 `select_composite` 不做 DB / K线 IO，便于单测；DB/K线编排在 prepare()。
"""

import logging
import os.path
import sys

import numpy as np
import pandas as pd

cpath_current = os.path.dirname(os.path.dirname(__file__))
cpath = os.path.abspath(os.path.join(cpath_current, os.pardir))
sys.path.append(cpath)
import quantia.lib.run_template as runt
import quantia.core.tablestructure as tbs
import quantia.lib.database as mdb
from quantia.core.strategy import composite_alpha_v1 as ca

__author__ = 'Quantia'
__date__ = '2026/07/10'

_SOURCE_TABLE = 'cn_stock_selection'
_BENCHMARK = '000300'

# 直接复用模块固化默认（文档 11.3）
_WEIGHTS_FULL = {'fund': ca.DEFAULT_WEIGHTS['fund'],
                 'value': ca.DEFAULT_WEIGHTS['value'],
                 'tech': ca.DEFAULT_WEIGHTS['tech']}
_PREFILTER_N = 300  # 初筛候选池规模（K 线技术因子仅在此池内计算）

# 初筛只用 fund+value（cn_stock_selection 直接可得，无需 K 线）
_PREFILTER_DIMS = {
    'fund': ca.DIMENSION_FACTORS['fund'],
    'value': [('pe9', 'low'), ('pbnewmrq', 'low')],
}
# 全量打分维度（value 用 selection 的 pe9/pbnewmrq；tech 由 K 线预计算并入）
_FULL_DIMS = {
    'fund': ca.DIMENSION_FACTORS['fund'],
    'value': [('pe9', 'low'), ('pbnewmrq', 'low')],
    'tech': ca.DIMENSION_FACTORS['tech'],
}


def _exclude_risk_names(df):
    """排除 ST/退市/N/新股占位等风险标的（按名称）。"""
    if 'name' not in df.columns:
        return df
    name = df['name'].astype(str)
    bad = name.str.contains('ST', case=False, na=False) | name.str.contains('退', na=False)
    return df[~bad]


def select_composite(selection_df, tech_map=None, weights=None,
                     quality_gate=None, trade_gate=None, top_positions=None,
                     prefilter_n=_PREFILTER_N):
    """纯计算核心：从 cn_stock_selection 截面选出综合多因子标的。

    Args:
        selection_df: cn_stock_selection 一日截面（含 code/name/基本面/估值列）。
        tech_map: {code: (atr_pct, ma20_slope, mom_20)}；None 时技术维度降级。
        weights/quality_gate/trade_gate/top_positions: 缺省取模块固化默认。
        prefilter_n: 初筛候选池规模。

    Returns:
        picked DataFrame（含各维度分与 composite_score，按综合分降序）；无标的返回空表。
    """
    params = ca.DEFAULT_PARAMS
    quality_gate = params['quality_gate'] if quality_gate is None else quality_gate
    trade_gate = params['trade_gate'] if trade_gate is None else trade_gate
    top_positions = int(params['top_positions'] if top_positions is None else top_positions)
    weights = weights or _WEIGHTS_FULL

    if selection_df is None or len(selection_df) == 0:
        return pd.DataFrame()

    df = _exclude_risk_names(selection_df).copy()
    if 'new_price' in df.columns:
        df = df[pd.to_numeric(df['new_price'], errors='coerce').fillna(0) > 0]
        # 结果表 close 列取自最新价（cn_stock_selection.new_price）
        df['close'] = pd.to_numeric(df['new_price'], errors='coerce')
    df['code'] = df['code'].astype(str).str.zfill(6)
    if df.empty:
        return pd.DataFrame()

    # 1) fund+value 初筛
    pre = ca.compute_composite_scores(df, weights={'fund': 0.6, 'value': 0.4},
                                      dimension_factors=_PREFILTER_DIMS)
    df = df.assign(_pre=pd.to_numeric(pre['composite_score'], errors='coerce'))
    cand = df.sort_values('_pre', ascending=False).head(int(prefilter_n)).copy()
    if cand.empty:
        return pd.DataFrame()

    # 2) 并入技术因子（K 线预计算；缺失则技术维度降级）
    if tech_map:
        cand['atr_pct'] = cand['code'].map(lambda c: (tech_map.get(c) or (np.nan,)*3)[0])
        cand['ma20_slope'] = cand['code'].map(lambda c: (tech_map.get(c) or (np.nan,)*3)[1])
        cand['mom_20'] = cand['code'].map(lambda c: (tech_map.get(c) or (np.nan,)*3)[2])

    # 3) 全量综合打分 + 双门槛选股
    scores = ca.compute_composite_scores(cand, weights=weights, dimension_factors=_FULL_DIMS)
    picked = ca.select_candidates(cand, scores=scores, quality_gate=quality_gate,
                                  trade_gate=trade_gate, top_n=top_positions)
    return picked


# ─────────────────────── DB / K线 编排 ───────────────────────

def _load_selection_data(source_table, date_str):
    """读 cn_stock_selection，支持最近7天日期回退。返回 (DataFrame, actual_date_str)。"""
    sql = f"SELECT * FROM `{source_table}` WHERE `date` = %s"
    data = pd.read_sql(sql, mdb.engine(), params=(date_str,))
    if data is not None and len(data) > 0:
        return data, date_str
    fb = (f"SELECT MAX(`date`) AS latest FROM `{source_table}` "
          f"WHERE `date` >= DATE_SUB(%s, INTERVAL 7 DAY) AND `date` < %s")
    try:
        r = pd.read_sql(fb, mdb.engine(), params=(date_str, date_str))
        if r is not None and len(r) > 0 and r.iloc[0]['latest'] is not None:
            latest = r.iloc[0]['latest']
            fd = latest.strftime("%Y-%m-%d") if hasattr(latest, 'strftime') else str(latest)
            data = pd.read_sql(sql, mdb.engine(), params=(fd,))
            if data is not None and len(data) > 0:
                return data, fd
    except Exception as e:
        logging.warning(f"综合多因子选股：日期回退查询异常: {e}")
    return None, date_str


def _compute_tech_map(codes, date_str):
    """在 K 线缓存上为候选码计算 (atr_pct, ma20_slope, mom_20)。仅读缓存，无 API。"""
    import quantia.core.stockfetch as sf
    start = (pd.Timestamp(date_str) - pd.DateOffset(days=200)).strftime('%Y-%m-%d')
    window = 20
    out = {}
    for code in codes:
        try:
            df = sf.read_stock_hist_from_cache(code, start, date_str)
        except Exception:
            df = None
        if df is None or len(df) < window * 2 or 'close' not in df.columns:
            continue
        close = pd.to_numeric(df.sort_values('date')['close'], errors='coerce').to_numpy(dtype=float)
        i = len(close) - 1
        win = close[i - window + 1:i + 1]
        prev = close[i - window:i]
        with np.errstate(divide='ignore', invalid='ignore'):
            pchg = np.abs((win - prev) / np.where(prev == 0, np.nan, prev)) * 100
        atr_pct = float(np.nanmean(pchg))
        ma_now = float(np.mean(close[i - window + 1:i + 1]))
        ma_prev = float(np.mean(close[i - 2 * window + 1:i - window + 1]))
        ma20_slope = (ma_now / ma_prev - 1.0) * 100 if ma_prev > 0 else 0.0
        first = float(close[i - window + 1])
        mom_20 = (float(close[i]) / first - 1.0) * 100 if first > 0 else 0.0
        out[str(code).zfill(6)] = (atr_pct, ma20_slope, mom_20)
    return out


def _regime_ok(date_str):
    """大盘择时：沪深300 收盘 >= regime_ma 日均线视为可出手。数据不足则放行。"""
    ma = int(ca.DEFAULT_PARAMS.get('regime_ma', 0) or 0)
    if ma <= 0:
        return True
    try:
        from quantia.core.backtest import data_feed
        start = (pd.Timestamp(date_str) - pd.DateOffset(days=ma * 2 + 60)).strftime('%Y-%m-%d')
        bdf = data_feed.load_benchmark_data(_BENCHMARK, start, date_str)
        if bdf is None or len(bdf) < ma:
            return True
        close = pd.to_numeric(bdf.sort_values('date')['close'], errors='coerce').to_numpy(dtype=float)
        return float(close[-1]) >= float(np.mean(close[-ma:]))
    except Exception as e:
        logging.warning(f"综合多因子选股：择时判断异常，放行: {e}")
        return True


def prepare(date):
    """执行综合多因子选股，将结果写入 cn_stock_strategy_composite_alpha_v1。"""
    try:
        date_str = date.strftime("%Y-%m-%d")
        table_name = tbs.TABLE_CN_STOCK_STRATEGY_COMPOSITE_ALPHA['name']

        if not mdb.checkTableIsExist(_SOURCE_TABLE):
            logging.warning(f"源表 {_SOURCE_TABLE} 不存在，跳过综合多因子选股。")
            return

        selection_data, actual = _load_selection_data(_SOURCE_TABLE, date_str)
        if selection_data is None or len(selection_data) == 0:
            logging.warning(f"综合多因子选股：{date_str} 无选股数据（近7天均无），跳过。")
            return

        # 大盘择时：弱市当日空仓（清当日结果，不选股）
        if not _regime_ok(actual):
            logging.info(f"综合多因子选股：{actual} 大盘处于弱市（低于均线），当日空仓。")
            _write_results(pd.DataFrame(), table_name, date_str)
            return

        # 初筛（fund+value）
        pre = ca.compute_composite_scores(
            _exclude_risk_names(selection_data),
            weights={'fund': 0.6, 'value': 0.4}, dimension_factors=_PREFILTER_DIMS)
        tmp = _exclude_risk_names(selection_data).assign(
            _pre=pd.to_numeric(pre['composite_score'], errors='coerce'))
        tmp['code'] = tmp['code'].astype(str).str.zfill(6)
        cand_codes = tmp.sort_values('_pre', ascending=False).head(_PREFILTER_N)['code'].tolist()

        # 候选池内算技术因子
        tech_map = _compute_tech_map(cand_codes, actual)

        picked = select_composite(selection_data, tech_map=tech_map)
        if picked is None or len(picked) == 0:
            logging.info(f"综合多因子选股：{actual} 无符合条件标的，当日空仓。")
            _write_results(pd.DataFrame(), table_name, date_str)
            return

        picked = picked.copy()
        picked['date'] = date_str
        logging.info(f"综合多因子选股：{actual} 选出 {len(picked)} 只"
                     f"{'（回退日期）' if actual != date_str else ''}")
        _write_results(picked, table_name, date_str)

    except Exception:
        logging.error("composite_alpha_data_job.prepare 处理异常", exc_info=True)
        mdb._invalidate_shared_conn()


def _write_results(picked, table_name, date_str):
    """删除当日旧数据并写入新结果（picked 为空则仅清空当日）。"""
    fk_cols = list(tbs.TABLE_CN_STOCK_FOREIGN_KEY['columns'])  # date, code, name
    score_cols = ['composite_score', 'fund_score', 'value_score', 'tech_score',
                  'chip_score', 'flow_score', 'available_dims', 'close']
    bt_cols = list(tbs.TABLE_CN_STOCK_BACKTEST_DATA['columns'])
    all_cols = fk_cols + score_cols + bt_cols

    table_existed = mdb.checkTableIsExist(table_name)
    if table_existed:
        mdb.executeSql(f"DELETE FROM `{table_name}` WHERE `date` = %s", (date_str,))
        cols_type = None
    else:
        cols_type = tbs.get_field_types(tbs.TABLE_CN_STOCK_STRATEGY_COMPOSITE_ALPHA['columns'])

    if picked is None or len(picked) == 0:
        return

    data = pd.DataFrame()
    data['date'] = picked['date'] if 'date' in picked.columns else date_str
    data['code'] = picked['code'].astype(str).str.zfill(6)
    data['name'] = picked['name'] if 'name' in picked.columns else ''
    for c in score_cols:
        data[c] = picked[c] if c in picked.columns else None
    data = data.reindex(columns=all_cols)
    mdb.insert_db_from_df(data, table_name, cols_type, False, "`date`,`code`")


def main():
    runt.run_with_args(prepare)


if __name__ == '__main__':
    main()
