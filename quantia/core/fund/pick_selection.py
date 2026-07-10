#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每日精选榜 P5：桶内 A/C 份额去重 + Top10 截取（纯函数，无 DB / 网络）。

对齐 document/fund/good_fund_selection_and_entry_timing_plan.md §7 与风险 5：
- **取数顺序**：桶内先取 Top-N（N=20–30，>10）by quality → 类名称正规化去重（AC
  De-duplication，同底层双份额只留主份额）→ 再截 Top10。**禁止**先截 10 再去重
  （去重后不足 10 只会缺额）。
- 主份额优先级（同名归并时保留者）：规模 AUM 较大 > A 类优先 > code 较小（稳定）。
  V1 无规模列时按 A 类优先 + code 稳定序。
- final_score V1 = quality_score（择时不参与主排序，仅作展示标签）。

本模块只做**选择/排序/去重**，不读库、不算 timing、不落库。timing 由 timing.py
统一计算；本模块保持可单元测试的纯函数。
"""

import re

__author__ = 'Quantia'
__date__ = '2026/07/09'

# 尾部份额类别标记：A/B/C/D/E/H/I/O/R（可带“类”/括号），用于归并 A/C 双份额。
# CN 基金简称尾部单个拉丁字母几乎必为份额类别，桶内去重可安全归并。
_SHARE_SUFFIX_RE = re.compile(r'[\(（]?([A-EHIOR])类?[\)）]?$')


def normalize_fund_name(name):
    """份额类别正规化：剥离尾部份额标记，得到归并键。

    "华夏核心价值混合A" / "华夏核心价值混合C" → "华夏核心价值混合"
    "南方原油(QDII)A" → "南方原油(QDII)"（先剥 A，QDII 括号保留）
    空 / None → ''。
    """
    if not name:
        return ''
    s = str(name).strip()
    if not s:
        return ''
    stripped = _SHARE_SUFFIX_RE.sub('', s).strip()
    # 全部被剥光（极端命名）时回退原名，避免不同基金归并成空键。
    return stripped or s


def _num(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    import math
    return None if not math.isfinite(f) else f


def _share_rank_key(cand):
    """主份额优先级排序键（越小越优先保留）。

    1) 规模 AUM 大者优先（缺失视为 -inf，最劣）
    2) A 类优先（名称尾部为 A）
    3) code 较小
    """
    scale = _num(cand.get('scale'))
    scale_key = -scale if scale is not None else float('inf')
    name = str(cand.get('name') or '')
    m = _SHARE_SUFFIX_RE.search(name)
    is_a = 0 if (m and m.group(1) == 'A') else 1
    code = str(cand.get('code') or '')
    return (scale_key, is_a, code)


def dedup_ac(candidates):
    """AC 份额去重：同 normalize_fund_name 归并为一组，保留主份额。

    输入/输出均为 dict 列表（含 code/name/quality_score/scale 等）。输出保留
    每组主份额，并按输入的**质量序**稳定输出（去重不改变后续排序）。
    """
    groups = {}
    order = []
    for cand in candidates:
        key = normalize_fund_name(cand.get('name'))
        code = str(cand.get('code') or '')
        # 名称为空时以 code 单独成组，避免全部空名归并。
        gkey = key if key else '__code__' + code
        if gkey not in groups:
            groups[gkey] = []
            order.append(gkey)
        groups[gkey].append(cand)

    result = []
    for gkey in order:
        members = groups[gkey]
        if len(members) == 1:
            result.append(members[0])
        else:
            result.append(sorted(members, key=_share_rank_key)[0])
    return result


def select_bucket_top(candidates, top_k=10, pre_n=25):
    """桶内精选：Top-N by quality → AC 去重 → 截 Top10，并写入 rank_in_type。

    - candidates：dict 列表，须含 quality_score（None 视为最劣，排末尾）。
    - 排序键：quality_score 降序，tie → code 升序（稳定）。
    - 顺序：先按质量取前 pre_n → 去重 → 再取前 top_k。
    返回新 dict 列表（浅拷贝 + rank_in_type=1..k）。
    """
    def q_key(c):
        q = _num(c.get('quality_score'))
        return (0 if q is not None else 1, -(q if q is not None else 0.0),
                str(c.get('code') or ''))

    ranked = sorted(candidates, key=q_key)
    top_n = ranked[:max(pre_n, top_k)]
    deduped = dedup_ac(top_n)
    # 去重可能保留了非首见的主份额（如同组保留 A 类但 C 类质量更高先出现），
    # 需按**保留者自身质量**重排，否则名次会被首见份额位移。
    deduped.sort(key=q_key)
    picked = deduped[:top_k]
    out = []
    for i, c in enumerate(picked, start=1):
        row = dict(c)
        row['rank_in_type'] = i
        out.append(row)
    return out
