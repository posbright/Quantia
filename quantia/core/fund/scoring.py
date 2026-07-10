# -*- coding: utf-8 -*-
"""F7 基金多因子综合评分（截面打分，纯函数）。

核心约束（见 document/stock/fund_data_and_ranking_dev_plan.md §4.2）：
- **强制按 fund_type 分桶**做截面百分位 `rank(pct=True)*100`，**不跨桶**。
- 不复用 composite 的 `n_rank`（那是滚动时序百分位，误用于截面会错乱）。
- 长期收益/夏普/回撤一律用 `acc_nav`（累计净值，已还原分红拆分），不用 unit_nav。
- 货币型无单位净值波动 → 不算夏普/回撤/Calmar，独立成桶用 7日年化+万份收益+费率。
- 样本不足（< MIN_SHARPE_SAMPLES 交易日）夏普/Calmar 返回 None，不强算。
- 评分仅排序辅助，禁落库为可交易 strategy_template，前端需带风险提示。

所有函数纯计算：输入 DataFrame / 序列，输出 DataFrame / 标量，无副作用。
"""

import math

import numpy as np
import pandas as pd

__author__ = 'Quantia'
__date__ = '2026/06/01'

MONEY_TYPE = '货币型'
_UNKNOWN_INDUSTRY_LABEL = '未分类'

# ── 计算常量 ─────────────────────────────────────────────
RISK_FREE_ANNUAL = 0.02     # 无风险年化（夏普分母基准，可由 job 覆盖）
TRADING_DAYS = 252
MIN_SHARPE_SAMPLES = 60     # 夏普/Calmar 最小交易日样本
NEUTRAL = 50.0             # 缺披露因子在桶内填中性分

# ── B1 因子权重（净值型，合计 1.0）──────────────────────────
# 动量四周期小计 0.80；费率 0.08（负向）；规模 0.12（倒U）。
NAV_MOMENTUM_WEIGHTS = {'rate_3m': 0.18, 'rate_6m': 0.22, 'rate_1y': 0.28, 'rate_ytd': 0.12}
W_MOMENTUM = sum(NAV_MOMENTUM_WEIGHTS.values())  # 0.80
W_FEE = 0.08
W_SCALE = 0.12
# ── B2 风险调整权重（夏普/Calmar 可得时，从 B1 等比让渡）──────────
W_SHARPE = 0.15
W_CALMAR = 0.10

# ── 货币型权重（合计 1.0）──────────────────────────────────
MONEY_MOMENTUM_WEIGHTS = {'seven_day_annual': 0.55, 'million_unit_income': 0.30}
W_MONEY_MOMENTUM = sum(MONEY_MOMENTUM_WEIGHTS.values())  # 0.85
W_MONEY_FEE = 0.15

# 评分结果列（不含 date / rank_in_type，由 compute_scores 补）
SCORE_VALUE_COLS = [
    'score', 'momentum_score', 'fee_score', 'scale_score',
    'sharpe_score', 'calmar_score', 'sharpe', 'max_drawdown',
    'rate_3y', 'rate_5y', 'excess_1y', 'main_industry',
]


def cross_sectional_pct_rank(series):
    """桶内截面百分位 *100（0~100）。NaN 保留 NaN（由调用方决定填中性）。"""
    s = pd.to_numeric(series, errors='coerce')
    return s.rank(pct=True) * 100.0


def scale_inverted_u(scale_series):
    """规模倒U 分位：中位规模得分最高，过小/过大都减分。

    对 log(规模) 取桶内百分位 r∈[0,1]，得分 = 100 - |r-0.5|*200 ∈ [0,100]。
    规模缺失/<=0 → NaN（调用方填中性 50，不淘汰）。
    """
    s = pd.to_numeric(scale_series, errors='coerce')
    log_scale = np.log(s.where(s > 0))
    r = log_scale.rank(pct=True)
    return 100.0 - (r - 0.5).abs() * 200.0


# ── 净值序列派生指标（一律用 acc_nav）──────────────────────────

def _clean_nav(acc_nav):
    nav = pd.to_numeric(pd.Series(list(acc_nav)), errors='coerce').dropna()
    return nav[nav > 0].reset_index(drop=True)


def compute_sharpe(acc_nav, rf=RISK_FREE_ANNUAL, trading_days=TRADING_DAYS,
                   min_samples=MIN_SHARPE_SAMPLES):
    """年化夏普 = (年化收益 - rf) / 年化波动，基于 acc_nav 日收益。样本不足→None。"""
    nav = _clean_nav(acc_nav)
    if len(nav) < min_samples:
        return None
    rets = nav.pct_change().dropna()
    if len(rets) < 2:
        return None
    std = rets.std(ddof=1)
    if not math.isfinite(std) or std == 0:
        return None
    ann_ret = rets.mean() * trading_days
    ann_vol = std * math.sqrt(trading_days)
    if not math.isfinite(ann_vol) or ann_vol == 0:
        return None
    sharpe = (ann_ret - rf) / ann_vol
    return float(sharpe) if math.isfinite(sharpe) else None


def compute_max_drawdown(acc_nav):
    """最大回撤（负数，如 -0.35）= min_t(acc_t / 历史峰值 - 1)。样本<2→None。"""
    nav = _clean_nav(acc_nav)
    if len(nav) < 2:
        return None
    running_max = nav.cummax()
    dd = nav / running_max - 1.0
    mdd = dd.min()
    return float(mdd) if math.isfinite(mdd) else None


def compute_calmar(acc_nav, trading_days=TRADING_DAYS, min_samples=MIN_SHARPE_SAMPLES):
    """Calmar = 年化收益 / |最大回撤|。样本不足或无回撤→None。"""
    nav = _clean_nav(acc_nav)
    if len(nav) < min_samples:
        return None
    years = len(nav) / float(trading_days)
    if years <= 0:
        return None
    total = nav.iloc[-1] / nav.iloc[0]
    if total <= 0:
        return None
    ann_ret = total ** (1.0 / years) - 1.0
    mdd = compute_max_drawdown(nav)
    if mdd is None or mdd == 0:
        return None
    calmar = ann_ret / abs(mdd)
    return float(calmar) if math.isfinite(calmar) else None


def compute_rate_5y(nav_dates, acc_nav):
    """近5年收益% = acc_最新 / acc_(最新-5年) - 1。成立不足5年→None。"""
    s = pd.Series(pd.to_numeric(pd.Series(list(acc_nav)), errors='coerce').values,
                  index=pd.to_datetime(pd.Series(list(nav_dates)), errors='coerce'))
    s = s[~s.index.isna()].dropna()
    s = s[s > 0].sort_index()
    if len(s) < 2:
        return None
    last_date = s.index[-1]
    target = last_date - pd.DateOffset(years=5)
    if s.index[0] > target:  # 成立不足5年
        return None
    past = s[s.index <= target]
    if past.empty:
        return None
    base = past.iloc[-1]
    if base <= 0:
        return None
    return float(s.iloc[-1] / base - 1.0) * 100.0


def compute_main_industry(holding_df):
    """由前十大重仓股 industry 按 hold_ratio 加权得各基金主行业。返回 {code: industry}。

    只在「已披露的已知行业」中取加权最大者，忽略 '未分类'：行业数据缺口（如科创板/
    北交所暂无库内行业）不应压过基金真实的行业倾向，否则半导体主题基金会因大量重仓
    落在未分类而被判为「未分类」→ 前端风格为空。忽略未分类后仍是「加权最大已知行业」，
    对已有已知主行业的基金结果不变（严格增量，不会抹掉原有标注）。
    """
    if holding_df is None or len(holding_df.index) == 0:
        return {}
    df = holding_df[['code', 'industry', 'hold_ratio']].copy()
    df['hold_ratio'] = pd.to_numeric(df['hold_ratio'], errors='coerce').fillna(0.0)
    df['industry'] = df['industry'].fillna(_UNKNOWN_INDUSTRY_LABEL)
    # 忽略未分类：只在已知行业中判定主行业（数据缺口不参与 argmax）
    df = df[df['industry'].astype(str).str.strip() != _UNKNOWN_INDUSTRY_LABEL]
    if df.empty:
        return {}
    agg = df.groupby(['code', 'industry'], as_index=False)['hold_ratio'].sum()
    if agg.empty:
        return {}
    idx = agg.groupby('code')['hold_ratio'].idxmax()
    top = agg.loc[idx]
    return {str(c): ind for c, ind in zip(top['code'], top['industry'])}


# ── 桶内评分 ─────────────────────────────────────────────

def _series(g, col, default=np.nan):
    if col in g.columns:
        return pd.to_numeric(g[col], errors='coerce')
    return pd.Series(default, index=g.index)


def _score_nav_bucket(g):
    """净值型桶：B1（动量+费率+规模）+ B2（夏普/Calmar 可得时叠加）。"""
    g = g.copy()
    # 动量：四周期截面分位加权（缺失填中性），再归一到 0~100
    mom = pd.Series(0.0, index=g.index)
    wsum = 0.0
    for col, w in NAV_MOMENTUM_WEIGHTS.items():
        r = cross_sectional_pct_rank(_series(g, col)).fillna(NEUTRAL)
        mom = mom + w * r
        wsum += w
    momentum_score = mom / wsum if wsum > 0 else pd.Series(NEUTRAL, index=g.index)

    fee_score = 100.0 - cross_sectional_pct_rank(_series(g, 'fee')).fillna(NEUTRAL)
    scale_score = scale_inverted_u(_series(g, 'scale_yi')).fillna(NEUTRAL)

    score_b1 = W_MOMENTUM * momentum_score + W_FEE * fee_score + W_SCALE * scale_score

    sharpe_score = cross_sectional_pct_rank(_series(g, 'sharpe'))
    calmar_score = cross_sectional_pct_rank(_series(g, 'calmar'))

    has_s = sharpe_score.notna().to_numpy()
    has_c = calmar_score.notna().to_numpy()
    w_s = np.where(has_s, W_SHARPE, 0.0)
    w_c = np.where(has_c, W_CALMAR, 0.0)
    w_b1 = 1.0 - w_s - w_c
    score = (w_b1 * score_b1.to_numpy()
             + w_s * sharpe_score.fillna(0.0).to_numpy()
             + w_c * calmar_score.fillna(0.0).to_numpy())

    rate_1y = _series(g, 'rate_1y')
    excess_1y = rate_1y - rate_1y.mean()

    out = pd.DataFrame({'code': g['code'].astype(str).values,
                        'fund_type': g['fund_type'].values})
    out['score'] = np.round(score, 4)
    out['momentum_score'] = np.round(momentum_score.to_numpy(), 4)
    out['fee_score'] = np.round(fee_score.to_numpy(), 4)
    out['scale_score'] = np.round(scale_score.to_numpy(), 4)
    out['sharpe_score'] = sharpe_score.to_numpy()
    out['calmar_score'] = calmar_score.to_numpy()
    out['sharpe'] = _series(g, 'sharpe').to_numpy()
    out['max_drawdown'] = _series(g, 'max_drawdown').to_numpy()
    out['rate_3y'] = _series(g, 'rate_3y').to_numpy()
    out['rate_5y'] = _series(g, 'rate_5y').to_numpy()
    out['excess_1y'] = excess_1y.to_numpy()
    out['main_industry'] = (g['main_industry'].values
                            if 'main_industry' in g.columns else None)
    return out


def _score_money_bucket(g):
    """货币型桶：7日年化 + 万份收益 + 费率，不算夏普/回撤/行业。"""
    g = g.copy()
    mom = pd.Series(0.0, index=g.index)
    wsum = 0.0
    for col, w in MONEY_MOMENTUM_WEIGHTS.items():
        r = cross_sectional_pct_rank(_series(g, col)).fillna(NEUTRAL)
        mom = mom + w * r
        wsum += w
    momentum_score = mom / wsum if wsum > 0 else pd.Series(NEUTRAL, index=g.index)
    fee_score = 100.0 - cross_sectional_pct_rank(_series(g, 'fee')).fillna(NEUTRAL)
    score = W_MONEY_MOMENTUM * momentum_score + W_MONEY_FEE * fee_score

    rate_1y = _series(g, 'rate_1y')
    excess_1y = rate_1y - rate_1y.mean()

    out = pd.DataFrame({'code': g['code'].astype(str).values,
                        'fund_type': g['fund_type'].values})
    out['score'] = np.round(score, 4)
    out['momentum_score'] = np.round(momentum_score.to_numpy(), 4)
    out['fee_score'] = np.round(fee_score.to_numpy(), 4)
    out['scale_score'] = np.nan
    out['sharpe_score'] = np.nan
    out['calmar_score'] = np.nan
    out['sharpe'] = np.nan
    out['max_drawdown'] = np.nan
    out['rate_3y'] = _series(g, 'rate_3y').to_numpy()
    out['rate_5y'] = np.nan
    out['excess_1y'] = excess_1y.to_numpy()
    out['main_industry'] = None
    return out


def compute_scores(df, score_date=None):
    """按 fund_type 分桶截面打分，返回对齐 cn_fund_rank_score 的 DataFrame。

    df 至少需 code/fund_type，以及可用的因子列（rate_*、fee、scale_yi、
    sharpe、calmar、max_drawdown、rate_3y、rate_5y、main_industry、
    seven_day_annual、million_unit_income）。缺列按中性/None 处理。
    """
    cols = ['date', 'code', 'fund_type'] + SCORE_VALUE_COLS + ['rank_in_type']
    if df is None or len(df.index) == 0:
        return pd.DataFrame(columns=cols)

    parts = []
    for ftype, g in df.groupby('fund_type'):
        if ftype == MONEY_TYPE:
            parts.append(_score_money_bucket(g))
        else:
            parts.append(_score_nav_bucket(g))
    out = pd.concat(parts, ignore_index=True)

    # 桶内名次（score 降序，并列取小）
    out['rank_in_type'] = (out.groupby('fund_type')['score']
                           .rank(ascending=False, method='min'))
    out['rank_in_type'] = out['rank_in_type'].astype('Int64')
    out['date'] = score_date
    return out[cols]
