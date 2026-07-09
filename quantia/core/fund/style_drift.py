# -*- coding: utf-8 -*-
"""持仓风格暴露 + 前向兼容风格漂移纯函数（F12/F9-F10 降级为风控辅助展示）。

用基金季报**前十大重仓股**（`cn_fund_holding` 的 `industry` + `hold_ratio`）算：
- **风格暴露**（单季即可）：按 `hold_ratio` 加权的行业分布、行业集中度 HHI、top 行业、
  `未分类` 占比透明化（科创板 688 断层，见蓝图 §9.2）。
- **风格漂移**（需 ≥2 季报）：相邻两季行业权重的 L1 变化 → 漂移分（越高=换仓越大）。

严格定位（蓝图 §9.2 / §F12）：
- **仅作详情页风控辅助展示（雷达/条形）**，**不做硬拦截**（否则半导体等主题基金会被误判
  "大漂移"冤杀），**不进入 TimingScore**，不影响无覆盖基金。
- `未分类`（含科创板龙头）**不计入集中度/漂移的行业口径**，仅透明化其占比，避免断层污染。
- 纯函数：输入持仓字典列表，输出标量/字典，无副作用、无 DB/网络（读取在 handler 层）。

分数语义：集中度 HHI∈[0,1]（越高=越集中单一赛道）；漂移分∈[0,100]（越高=换仓越剧烈）。
"""

import math

__author__ = 'Quantia'
__date__ = '2026/07/09'

UNCLASSIFIED = '未分类'          # 行业缺失/科创板断层统一归此桶（透明化，不计集中度）

# 集中度档位（HHI，仅对已分类行业口径）
HHI_HIGH = 0.50   # ≥0.50 高度集中（单一赛道为主）
HHI_MID = 0.30    # 0.30–0.50 适度集中；<0.30 行业分散

# 漂移档位（相邻季 L1/2 × 100，仅已分类行业口径）
DRIFT_HIGH = 50.0  # ≥50 显著漂移（换风格）
DRIFT_MID = 25.0   # 25–50 中等换仓；<25 风格稳定


def _clip(v, lo=0.0, hi=100.0):
    return float(max(lo, min(hi, v)))


def _norm_industry(name):
    """行业名规整：None/空/`未分类` → 统一 UNCLASSIFIED。"""
    if name is None:
        return UNCLASSIFIED
    s = str(name).strip()
    return s if s and s != UNCLASSIFIED else UNCLASSIFIED


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def industry_exposure(holdings):
    """单季持仓行业暴露聚合。

    holdings: 可迭代 {'industry': str|None, 'hold_ratio': float|None(%)}。
    返回 dict：
      industries: [{'industry','weight'(%),'share'(0-1 已分类占比)}] 按权重降序（**仅已分类**）
      unclassified_weight: `未分类` 权重(%)
      disclosed_ratio: 前十大合计权重(%)（穿透覆盖，透明化）
      classified_ratio: 已分类合计权重(%)
      unclassified_ratio: 未分类/披露 (0-1)|None
      hhi: 已分类行业集中度 (0-1)|None
      top3_share: 已分类 top3 占比 (0-1)|None
      n_industries: 已分类行业数
    无有效持仓 → 各标量 None/0、industries=[]。
    """
    agg = {}
    disclosed = 0.0
    for h in holdings or []:
        wf = _num((h or {}).get('hold_ratio'))
        if wf is None or wf <= 0:
            continue
        ind = _norm_industry((h or {}).get('industry'))
        agg[ind] = agg.get(ind, 0.0) + wf
        disclosed += wf

    unclassified = agg.pop(UNCLASSIFIED, 0.0)
    classified = disclosed - unclassified
    items = sorted(agg.items(), key=lambda kv: kv[1], reverse=True)

    industries = []
    for ind, w in items:
        share = (w / classified) if classified > 0 else None
        industries.append({
            'industry': ind,
            'weight': round(w, 2),
            'share': None if share is None else round(share, 4),
        })

    if classified > 0 and items:
        hhi = sum((w / classified) ** 2 for _, w in items)
        top3 = sum(w for _, w in items[:3]) / classified
    else:
        hhi = None
        top3 = None

    return {
        'industries': industries,
        'unclassified_weight': round(unclassified, 2),
        'disclosed_ratio': round(disclosed, 2),
        'classified_ratio': round(classified, 2),
        'unclassified_ratio': (round(unclassified / disclosed, 4) if disclosed > 0 else None),
        'hhi': None if hhi is None else round(hhi, 4),
        'top3_share': None if top3 is None else round(top3, 4),
        'n_industries': len(items),
    }


def concentration_label(hhi):
    """行业集中度 HHI → 档位标签。None → None。"""
    h = _num(hhi)
    if h is None:
        return None
    if h >= HHI_HIGH:
        return '高度集中'
    if h >= HHI_MID:
        return '适度集中'
    return '行业分散'


def _share_map(exposure):
    """从 exposure 取 {已分类行业: share(0-1)}。"""
    out = {}
    for it in (exposure or {}).get('industries', []) or []:
        sh = _num(it.get('share'))
        if sh is not None and sh > 0:
            out[it['industry']] = sh
    return out


def style_drift(prev_exposure, curr_exposure):
    """相邻两季行业风格漂移（仅已分类行业口径）。

    prev/curr_exposure: `industry_exposure` 的返回值。
    漂移分 = clip(Σ|curr_share - prev_share| / 2 × 100)，∈[0,100]。
    返回 {'drift_score', 'drift_label', 'top_changes':[{'industry','delta'(0-1)}...]}；
    任一季无已分类行业 → None。
    """
    p = _share_map(prev_exposure)
    c = _share_map(curr_exposure)
    if not p or not c:
        return None
    keys = set(p) | set(c)
    l1 = sum(abs(c.get(k, 0.0) - p.get(k, 0.0)) for k in keys)
    drift = _clip(l1 / 2.0 * 100.0)
    changes = sorted(
        ({'industry': k, 'delta': round(c.get(k, 0.0) - p.get(k, 0.0), 4)} for k in keys),
        key=lambda d: abs(d['delta']), reverse=True)
    return {
        'drift_score': round(drift, 1),
        'drift_label': drift_label(drift),
        'top_changes': changes[:5],
    }


def drift_label(score):
    """漂移分 → 档位标签（非买卖建议）。None → None。"""
    s = _num(score)
    if s is None:
        return None
    if s >= DRIFT_HIGH:
        return '显著漂移'
    if s >= DRIFT_MID:
        return '中等换仓'
    return '风格稳定'
