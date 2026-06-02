"""
综合选股多因子评分 —— 纯计算核心（Compute 管道，AGENTS.md 规则 1）。

本模块**不做任何 DB / 网络调用**，全部为纯函数：输入 DataFrame / Series，输出 Series / dict。
DB 读取、结果落库由 `quantia/job/selection_score_job.py`、有效性验证由
`quantia/job/selection_factor_validation_job.py` 负责编排。

包含：
- 因子配置（方向、指标族分组、维度权重）——M0 验证与 M1 评分共用
- 标准化原语（方向化 / Winsorize / 稳健Z / logistic / 百分位）
- 绝对质量分 Q（全市场稳健Z，跨行业可比）
- 有效性验证原语（Spearman IC、分位分层、单调性）

设计依据见 document/chooseview/综合选股重构需求与开发文档.md（§4 双分制 v2、§4.8 验证）。
"""
from __future__ import annotations

import math
from typing import Iterable, Optional

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# 一、因子配置（M0 验证 / M1 评分共用）
# ---------------------------------------------------------------------------

# 字段 → 方向：'low' 越低越好（取负向后越大越好），'high' 越高越好
FACTOR_DIRECTIONS: dict[str, str] = {
    # 估值（低优；股息率高优）
    'pe9': 'low', 'pettmdeducted': 'low', 'pbnewmrq': 'low', 'ps9': 'low',
    'ycpeg': 'low', 'dtsyl': 'low', 'enterprise_value_multiple': 'low',
    'zxgxl': 'high',
    # 盈利（高优）
    'roe_weight': 'high', 'jroa': 'high', 'roic': 'high',
    'sale_gpr': 'high', 'sale_npr': 'high',
    # 成长（高优）
    'netprofit_yoy_ratio': 'high', 'deduct_netprofit_growthrate': 'high',
    'toi_yoy_ratio': 'high', 'netprofit_growthrate_3y': 'high',
    'income_growthrate_3y': 'high', 'predict_netprofit_ratio': 'high',
    'basiceps_yoy_ratio': 'high',
    # 财务健康（流动性/现金流高优；杠杆低优）
    'current_ratio': 'high', 'speed_ratio': 'high', 'per_netcash_operate': 'high',
    'debt_asset_ratio': 'low', 'goodwill_assets_ratro': 'low', 'pledge_ratio': 'low',
    # 资金/机构（持股高优；股东户数增长率低优=筹码集中）
    'allcorp_ratio': 'high', 'allcorp_fund_ratio': 'high', 'allcorp_sb_ratio': 'high',
    'allcorp_qfii_ratio': 'high', 'org_survey_3m': 'high',
    'holdnum_growthrate_3q': 'high', 'holder_ratio': 'low',
    # 情绪（量比/铁杆粉丝高优）
    'volume_ratio': 'high', 'bigfans_ratio': 'high',
}

# 维度 → 指标族 → 字段。族内取均值得 1 个代表值（消除共线性，P3），族间等权。
# 技术面（BIT 信号）单独处理，不在此连续因子表内。
DIMENSION_FAMILIES: dict[str, dict[str, list[str]]] = {
    'valuation': {
        'pe': ['pe9', 'pettmdeducted', 'dtsyl'],
        'pb': ['pbnewmrq'],
        'ps': ['ps9'],
        'peg': ['ycpeg'],
        'ev': ['enterprise_value_multiple'],
        'dividend': ['zxgxl'],
    },
    'profitability': {
        'roe': ['roe_weight', 'roic'],
        'roa': ['jroa'],
        'margin': ['sale_gpr', 'sale_npr'],
    },
    'growth': {
        'profit_growth': ['netprofit_yoy_ratio', 'deduct_netprofit_growthrate'],
        'revenue_growth': ['toi_yoy_ratio', 'income_growthrate_3y'],
        'profit_growth_3y': ['netprofit_growthrate_3y'],
        'forecast': ['predict_netprofit_ratio'],
        'eps_growth': ['basiceps_yoy_ratio'],
    },
    'health': {
        'liquidity': ['current_ratio', 'speed_ratio'],
        'cashflow': ['per_netcash_operate'],
        'leverage': ['debt_asset_ratio'],
    },
    'capital': {
        'inst_hold': ['allcorp_ratio', 'allcorp_fund_ratio', 'allcorp_sb_ratio', 'allcorp_qfii_ratio'],
        'survey': ['org_survey_3m'],
        'concentration': ['holdnum_growthrate_3q', 'holder_ratio'],
    },
    'sentiment': {
        'attention': ['volume_ratio', 'bigfans_ratio'],
    },
}

# 维度估值族中、若 PE/PB/PS ≤ 0（亏损/负净资产）则该族剔除并重归一（P5）
VALUATION_POSITIVE_ONLY = {'pe9', 'pettmdeducted', 'dtsyl', 'pbnewmrq', 'ps9'}

def _normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    total = float(sum(weights.values()))
    if total <= 0:
        raise ValueError('weights must sum to a positive value')
    return {k: float(v) / total for k, v in weights.items()}


# 默认维度权重（均衡模板，是存储 Q/评级的唯一口径，P11）
DEFAULT_WEIGHTS: dict[str, float] = _normalize_weights({
    'profitability': 0.20, 'growth': 0.20, 'valuation': 0.18,
    'health': 0.15, 'capital': 0.12, 'technical': 0.10, 'sentiment': 0.05,
})

# M1 校准模板：在保持 balanced 口径可用的前提下，轻微上调盈利/健康，
# 并压低技术/情绪的影响，以贴近 selection 池与 financial pool 的联合验证结果。
CALIBRATED_WEIGHTS_M1: dict[str, float] = _normalize_weights({
    'profitability': 0.26,
    'growth': 0.15,
    'valuation': 0.16,
    'health': 0.18,
    'capital': 0.11,
    'technical': 0.08,
    'sentiment': 0.06,
})

WEIGHT_TEMPLATES: dict[str, dict[str, float]] = {
    'balanced': DEFAULT_WEIGHTS,
    'm1_selection_pool': CALIBRATED_WEIGHTS_M1,
}


def resolve_weight_template(template: str | dict[str, float] | None = None) -> dict[str, float]:
    """解析权重模板名或显式权重字典。"""
    if template is None or template == 'balanced':
        return dict(DEFAULT_WEIGHTS)
    if isinstance(template, dict):
        return _normalize_weights({str(k): float(v) for k, v in template.items()})
    key = str(template).strip().lower()
    if key not in WEIGHT_TEMPLATES:
        raise ValueError(f'unknown weight template: {template!r}')
    return dict(WEIGHT_TEMPLATES[key])


def constrain_relative_weights(weights: dict[str, float],
                               keys: list[str],
                               anchor: dict[str, float] | None = None,
                               lock_lower: float = 0.75,
                               lock_upper: float = 1.25,
                               rank_caps: list[float] | None = None) -> dict[str, float]:
    """对一组有效权重施加相对锁定与排名上限。"""
    if not keys:
        return dict(weights)

    active = [k for k in keys if float(weights.get(k, 0.0)) > 0]
    if not active:
        return dict(weights)

    base = {k: max(0.0, float(weights.get(k, 0.0))) for k in active}
    target_sum = sum(base.values())
    if target_sum <= 0:
        return dict(weights)

    if anchor is None:
        anchor = _normalize_weights(base)

    bounded: dict[str, float] = {}
    lower = max(0.0, float(lock_lower))
    upper = max(lower, float(lock_upper))
    for key in active:
        a = max(0.0, float(anchor.get(key, 0.0)))
        low = a * lower
        high = a * upper
        bounded[key] = min(max(base[key], low), high)

    if rank_caps:
        ranked = sorted(active, key=lambda k: bounded[k], reverse=True)
        for idx, key in enumerate(ranked):
            cap_ratio = rank_caps[min(idx, len(rank_caps) - 1)]
            cap_ratio = max(0.0, float(cap_ratio))
            if cap_ratio <= 1.0:
                bounded[key] = min(bounded[key], target_sum * cap_ratio)
            else:
                bounded[key] = min(bounded[key], cap_ratio)

    bounded_sum = sum(bounded.values())
    if bounded_sum > 0:
        bounded = {k: v * (target_sum / bounded_sum) for k, v in bounded.items()}

    out = dict(weights)
    for key in active:
        out[key] = bounded[key]

    total = sum(max(0.0, float(v)) for v in out.values())
    if total > 0:
        out = {k: max(0.0, float(v)) / total for k, v in out.items()}
    return out


# ---------------------------------------------------------------------------
# 二、标准化原语（纯函数）
# ---------------------------------------------------------------------------

def _as_float(s: pd.Series | Iterable) -> pd.Series:
    """转 float Series，非数值→NaN。"""
    return pd.to_numeric(pd.Series(s), errors='coerce').astype(float)


def directionalize(s: pd.Series, direction: str) -> pd.Series:
    """方向化：'low'（越低越好）取负，使所有因子统一为'越大越好'。"""
    out = _as_float(s)
    return -out if direction == 'low' else out


def winsorize(s: pd.Series, lower: float = 0.01, upper: float = 0.99) -> pd.Series:
    """按分位截断极端值。有效样本 < 2 时原样返回。"""
    out = _as_float(s)
    if out.notna().sum() < 2:
        return out
    lo, hi = out.quantile(lower), out.quantile(upper)
    if pd.isna(lo) or pd.isna(hi):
        return out
    return out.clip(lo, hi)


def robust_z(s: pd.Series) -> pd.Series:
    """稳健 Z：(x − median) / (1.4826·MAD)。MAD 为 0 时回退到标准差；再退化则全 0。"""
    out = _as_float(s)
    med = out.median()
    if pd.isna(med):
        return pd.Series(np.nan, index=out.index)
    mad = (out - med).abs().median()
    if mad and not pd.isna(mad) and mad > 0:
        return (out - med) / (1.4826 * mad)
    std = out.std()
    if std and not pd.isna(std) and std > 0:
        return (out - med) / std
    # 常量列：有值的位置记 0，缺失保持 NaN
    return pd.Series(np.where(out.notna(), 0.0, np.nan), index=out.index)


def logistic(z: pd.Series) -> pd.Series:
    """logistic 映射到 (0, 1)，z 截断到 [-10, 10] 防溢出。"""
    out = _as_float(z).clip(-10, 10)
    return 1.0 / (1.0 + np.exp(-out))


def percentile_rank(s: pd.Series) -> pd.Series:
    """百分位归一到 [0, 1]（行业内相对分 R 用），缺失保持 NaN。"""
    return _as_float(s).rank(pct=True)


def standardized_factor(s: pd.Series, direction: str) -> pd.Series:
    """单因子标准化：方向化 → Winsorize → 稳健Z。"""
    return robust_z(winsorize(directionalize(s, direction)))


# ---------------------------------------------------------------------------
# 三、维度分与绝对质量分 Q（全市场稳健Z，跨行业可比）
# ---------------------------------------------------------------------------

def _family_representative(df: pd.DataFrame, fields: list[str]) -> Optional[pd.Series]:
    """族内：各字段标准化后取均值得 1 个代表值（消除共线性）。无可用字段返回 None。"""
    present = [f for f in fields if f in df.columns]
    if not present:
        return None
    zs = [standardized_factor(df[f], FACTOR_DIRECTIONS.get(f, 'high')) for f in present]
    return pd.concat(zs, axis=1).mean(axis=1)


def compute_dimension_q(df: pd.DataFrame, dimension: str) -> Optional[pd.Series]:
    """维度绝对分 Q_d ∈ [0,1]：族间等权聚合标准化值 → logistic。无可用族返回 None。"""
    families = DIMENSION_FAMILIES.get(dimension)
    if not families:
        return None
    fam_means: list[pd.Series] = []
    for fields in families.values():
        rep = _family_representative(df, fields)
        if rep is not None:
            fam_means.append(rep)
    if not fam_means:
        return None
    dim_raw = pd.concat(fam_means, axis=1).mean(axis=1)
    return logistic(dim_raw)


def compute_quality_score(
    df: pd.DataFrame,
    weights: Optional[dict[str, float]] = None,
) -> tuple[pd.Series, dict[str, pd.Series]]:
    """
    绝对质量分 Q（0–100，clamp）。对缺失维度（如无技术面字段）在现有维度上重归一权重。

    Returns:
        (q_score 0–100, {dimension: dim_q 0–100})
    """
    weights = weights or DEFAULT_WEIGHTS
    dim_scores: dict[str, pd.Series] = {}
    for dim in weights:
        q = compute_dimension_q(df, dim)
        if q is not None:
            dim_scores[dim] = q
    if not dim_scores:
        nan = pd.Series(np.nan, index=df.index)
        return nan, {}
    wsum = sum(weights[d] for d in dim_scores)
    total = sum(dim_scores[d] * weights[d] for d in dim_scores) / wsum
    q_score = (total * 100).clip(0, 100)
    return q_score, {d: (s * 100).clip(0, 100) for d, s in dim_scores.items()}


# ---------------------------------------------------------------------------
# 四、M2 结果表与日度结果生成（供 selection_score_job 编排）
# ---------------------------------------------------------------------------

SELECTION_SCORE_TABLE = 'cn_stock_selection_score'


def ensure_selection_score_table(mdb_module=None) -> None:
    """幂等创建 M2 结果表。"""
    mdb = mdb_module
    if mdb is None:
        import quantia.lib.database as mdb  # 延迟导入，避免纯计算单测连库

    ddl = f"""
    CREATE TABLE IF NOT EXISTS `{SELECTION_SCORE_TABLE}` (
      `date` DATE NOT NULL,
      `code` VARCHAR(10) NOT NULL,
      `name` VARCHAR(20) DEFAULT NULL,
      `industry` VARCHAR(50) DEFAULT NULL,
      `total_score` FLOAT DEFAULT NULL,
      `total_score_raw` FLOAT DEFAULT NULL,
      `quality_score` FLOAT DEFAULT NULL,
      `industry_score` FLOAT DEFAULT NULL,
      `rating` VARCHAR(2) DEFAULT NULL,
      `industry_rank` INT DEFAULT NULL,
      `industry_total` INT DEFAULT NULL,
      `rank_change_1d` INT DEFAULT NULL,
      `data_completeness` FLOAT DEFAULT NULL,
      `score_valuation` FLOAT DEFAULT NULL,
      `score_profitability` FLOAT DEFAULT NULL,
      `score_growth` FLOAT DEFAULT NULL,
      `score_health` FLOAT DEFAULT NULL,
      `score_capital` FLOAT DEFAULT NULL,
      `score_technical` FLOAT DEFAULT NULL,
      `score_sentiment` FLOAT DEFAULT NULL,
      `risk_penalty` FLOAT DEFAULT 0,
      `tags` JSON DEFAULT NULL,
      `risk_flags` JSON DEFAULT NULL,
      `weight_template` VARCHAR(20) DEFAULT 'balanced',
      `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
      PRIMARY KEY (`date`, `code`),
      KEY `idx_industry_score` (`industry`, `total_score`),
      KEY `idx_score` (`total_score`),
      KEY `idx_rating` (`rating`, `date`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='综合选股多因子评分结果'
    """
    mdb.executeSql(ddl)


def _rating_from_quality(q: pd.Series) -> pd.Series:
    out = pd.Series('D', index=q.index)
    out = out.mask(q >= 45, 'C')
    out = out.mask(q >= 60, 'B')
    out = out.mask(q >= 75, 'A')
    out = out.mask(q >= 85, 'S')
    return out


def build_daily_selection_scores(
    panel: pd.DataFrame,
    weight_template: str | dict[str, float] | None = 'balanced',
    alpha: float = 0.6,
) -> pd.DataFrame:
    """
    从单日 `cn_stock_selection` 快照生成 M2 结果表 DataFrame。

    说明：
    - 当前实现为 M2 最小可运行版：按单日快照产出 total/quality/industry/rank。
    - `total_score` 先等于 `total_score_raw`（EMA 平滑在后续增量阶段接入）。
    """
    if panel is None or panel.empty:
        return pd.DataFrame()

    df = panel.copy()
    if 'date' not in df.columns:
        raise ValueError('panel must include date column')
    if 'code' not in df.columns:
        raise ValueError('panel must include code column')

    as_of = pd.to_datetime(df['date']).max()
    df = df[pd.to_datetime(df['date']) == as_of].copy()
    if df.empty:
        return pd.DataFrame()

    df['code'] = df['code'].astype(str)
    df['industry'] = df.get('industry', pd.Series(index=df.index, dtype=object)).fillna('其他').replace('', '其他')

    weights = resolve_weight_template(weight_template)
    q_score, dim_scores = compute_quality_score(df, weights=weights)

    # 行业内百分位（1~100），用于行业内相对分与排名。
    industry_score = q_score.groupby(df['industry']).rank(method='average', pct=True) * 100.0
    total_raw = (float(alpha) * q_score + (1.0 - float(alpha)) * industry_score).clip(0, 100)

    out = pd.DataFrame({
        'date': pd.to_datetime(as_of).date(),
        'code': df['code'],
        'name': df['name'] if 'name' in df.columns else None,
        'industry': df['industry'],
        'total_score': total_raw,
        'total_score_raw': total_raw,
        'quality_score': q_score,
        'industry_score': industry_score,
        'rating': _rating_from_quality(q_score),
        'industry_rank': total_raw.groupby(df['industry']).rank(method='min', ascending=False).astype('Int64'),
        'industry_total': df.groupby('industry')['code'].transform('count').astype('Int64'),
        'rank_change_1d': 0,
        'risk_penalty': 0.0,
        'tags': '[]',
        'risk_flags': '[]',
        'weight_template': 'balanced' if weight_template is None else str(weight_template),
    })

    # 数据完整度：核心连续因子非空占比。
    fac_cols = [c for c in FACTOR_DIRECTIONS if c in df.columns]
    if fac_cols:
        out['data_completeness'] = df[fac_cols].notna().mean(axis=1).astype(float)
    else:
        out['data_completeness'] = 0.0

    for dim in ('valuation', 'profitability', 'growth', 'health', 'capital', 'technical', 'sentiment'):
        key = f'score_{dim}'
        if dim in dim_scores:
            out[key] = dim_scores[dim]
        else:
            out[key] = np.nan

    return out


# ---------------------------------------------------------------------------
# 五、有效性验证原语（M0：IC / 分层 / 单调性）
# ---------------------------------------------------------------------------

def _spearman(a: pd.Series, b: pd.Series) -> float:
    """Spearman = 先秩次化再取 Pearson（避开 scipy 依赖）。"""
    return float(a.rank().corr(b.rank()))


def spearman_ic(factor: pd.Series, forward_ret: pd.Series, min_n: int = 5) -> float:
    """因子值与未来收益的 Spearman 秩相关（IC）。有效样本 < min_n 返回 NaN。"""
    f = _as_float(pd.Series(factor).reset_index(drop=True))
    r = _as_float(pd.Series(forward_ret).reset_index(drop=True))
    n = min(len(f), len(r))
    f, r = f.iloc[:n], r.iloc[:n]
    mask = f.notna() & r.notna()
    if mask.sum() < min_n:
        return float('nan')
    if f[mask].nunique() < 2 or r[mask].nunique() < 2:
        return float('nan')
    return _spearman(f[mask], r[mask])


def ic_summary(ic_values: Iterable[float]) -> dict:
    """IC 时间序列汇总：均值、std、IR(=mean/std)、t 统计量、IC 胜率。"""
    s = _as_float(pd.Series(list(ic_values))).dropna()
    n = int(len(s))
    if n == 0:
        return {'n': 0, 'ic_mean': float('nan'), 'ic_std': float('nan'),
                'ir': float('nan'), 't_stat': float('nan'), 'ic_win_rate': float('nan')}
    mean = float(s.mean())
    std = float(s.std(ddof=1)) if n > 1 else 0.0
    ir = mean / std if std > 0 else float('nan')
    t_stat = mean / (std / math.sqrt(n)) if std > 0 else float('nan')
    win = float((s > 0).mean())
    return {'n': n, 'ic_mean': mean, 'ic_std': std, 'ir': ir,
            't_stat': t_stat, 'ic_win_rate': win}


def quantile_groups(scores: pd.Series, n: int = 5) -> pd.Series:
    """按分数等分为 n 组（0=最低 … n-1=最高），缺失保持 NaN。样本不足返回全 NaN。"""
    s = _as_float(scores)
    valid = s.notna()
    out = pd.Series(np.nan, index=s.index)
    if int(valid.sum()) < n:
        return out
    try:
        ranked = s[valid].rank(method='first')
        out.loc[valid] = pd.qcut(ranked, n, labels=False).astype(float)
    except ValueError:
        return pd.Series(np.nan, index=s.index)
    return out


def layered_returns(scores: pd.Series, forward_ret: pd.Series, n: int = 5) -> dict[int, float]:
    """分层回测：按分数分 n 组，返回每组未来平均收益 {组序: 平均收益}。"""
    df = pd.DataFrame({
        'score': _as_float(pd.Series(scores).reset_index(drop=True)),
        'ret': _as_float(pd.Series(forward_ret).reset_index(drop=True)),
    }).dropna()
    if len(df) < n:
        return {}
    df['grp'] = quantile_groups(df['score'], n)
    df = df.dropna(subset=['grp'])
    if df.empty:
        return {}
    grp_ret = df.groupby('grp')['ret'].mean()
    return {int(k): float(v) for k, v in grp_ret.items()}


def monotonicity(grp_ret: dict[int, float]) -> float:
    """分层单调性：组序与平均收益的 Spearman 相关。+1=完全递增（高分组收益更高）。"""
    if not grp_ret or len(grp_ret) < 2:
        return float('nan')
    keys = sorted(grp_ret.keys())
    vals = [grp_ret[k] for k in keys]
    if len(set(vals)) < 2:
        return float('nan')
    return _spearman(pd.Series(keys, dtype=float), pd.Series(vals, dtype=float))
