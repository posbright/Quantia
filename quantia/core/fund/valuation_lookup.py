#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T3 估值分位查询（单一事实源，Handler 与 pick_job 共用）。

只读 MySQL（`cn_fund_profile.benchmark` + `cn_index_valuation.pe_ttm`）+ 纯计算，
不调外部 API（AGENTS 规则 1：Analysis/Web 管道均可只读 DB）。SELECT 显式列（规则 7）。

流程：基金 benchmark → `benchmark_map` 映射宽基指数 → 指数 PE 全历史分位
（`timing.valuation_percentile_score`，低估→高分）。无 profile / 无法映射 /
无估值数据 → None（该维缺失，`compose_timing_score` 自动降维）。

抽离目的：`fundTimingHandler._valuation_score`（抽屉 T1+T2+T3）与
`analysis_fund_pick_job`（榜单择时徽章）必须**口径完全一致**（蓝图 §4.2），
避免两处各写一套 SQL/过滤导致列表徽章与抽屉档位不符。
"""
import logging

import quantia.core.tablestructure as tbs
import quantia.lib.database as mdb
from quantia.core.fund import benchmark_map, timing

logger = logging.getLogger(__name__)

_PROFILE_TABLE = tbs.TABLE_CN_FUND_PROFILE['name']
_INDEX_VAL_TABLE = tbs.TABLE_CN_INDEX_VALUATION['name']
_MIN_SAMPLES = 2


def _num(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float('inf'), float('-inf')):
        return None
    return f


def index_code_for_fund(code):
    """基金 code → 映射到的宽基指数 code（无 profile/无法映射 → None）。"""
    try:
        if not code or not mdb.checkTableIsExist(_PROFILE_TABLE):
            return None
        prows = mdb.executeSqlFetch(
            f"SELECT `benchmark` FROM `{_PROFILE_TABLE}` WHERE `code` = %s LIMIT 1",
            (code,))
        if not prows or not prows[0] or not prows[0][0]:
            return None
        return benchmark_map.map_benchmark_to_index(prows[0][0])
    except Exception:
        logger.warning("基金基准映射失败 code=%s", code, exc_info=True)
        return None


def valuation_score_for_index(index_code):
    """宽基指数 code → PE 全历史估值分位分（0-100，低估→高分）；无覆盖 → None。"""
    try:
        if not index_code or not mdb.checkTableIsExist(_INDEX_VAL_TABLE):
            return None
        vrows = mdb.executeSqlFetch(
            f"SELECT `pe_ttm` FROM `{_INDEX_VAL_TABLE}` "
            f"WHERE `index_code` = %s ORDER BY `date` ASC", (index_code,))
        if not vrows:
            return None
        pe_series = [_num(r[0]) for r in vrows]
        pe_series = [v for v in pe_series if v is not None and v > 0]
        if len(pe_series) < _MIN_SAMPLES:
            return None
        return timing.valuation_percentile_score(pe_series)
    except Exception:
        logger.warning("估值分位计算失败 index=%s", index_code, exc_info=True)
        return None


def valuation_score_for_fund(code, index_cache=None):
    """基金 code → (映射指数 code, 估值分位分)。

    `index_cache`（可选 dict）按 index_code 缓存分位分，批量场景（pick_job 一次
    评 ~70 只，多只共享同一宽基）避免重复全表扫描 `cn_index_valuation`。
    返回 (index_code|None, score|None)；index_code 命中映射即返回（即便无估值数据），
    供前端透明展示挂钩的宽基。
    """
    idx = index_code_for_fund(code)
    if not idx:
        return None, None
    if index_cache is not None and idx in index_cache:
        return idx, index_cache[idx]
    score = valuation_score_for_index(idx)
    if index_cache is not None:
        index_cache[idx] = score
    return idx, score
