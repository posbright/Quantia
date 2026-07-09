# -*- coding: utf-8 -*-
"""基金经理经验弱因子纯函数（P4 选基增量）。

用 `cn_fund_manager`（来源 akshare.fund_manager_em）里一只基金的**在管经理行**算：
- 任职经验：经理累计从业年限（`tenure_days`/365，取团队最大 + 平均）。
- 团队规模：在管经理数（多经理制透明化）。
- 历史业绩：经理现任基金最佳回报（团队最大）。
- 「一拖多」提示：团队里单个经理在管基金数最大值（越大越可能精力分散）。

严格定位（蓝图 §9.2 / P4）：
- **仅作详情页经理经验弱因子展示**，**不做硬拦截**、**不进入 TimingScore**，不影响无覆盖基金。
- 「累计从业时间」是经理**全市场累计从业**天数，**不是本基金任职起始日**（本基金任职链需
  更细数据源），故只作「经验」弱信号，不宣称「本基金经理稳定/未跳槽」。
- 纯函数：输入经理字典列表，输出标量/字典，无副作用、无 DB/网络（读取在 handler 层）。

分数语义：经验年限越大越资深；一拖多在管基金数越大风险提示越强。
"""

import math

__author__ = 'Quantia'
__date__ = '2026/07/09'

_DAYS_PER_YEAR = 365.0

# 经验档位（团队最大从业年限）
TENURE_SENIOR = 8.0   # ≥8 年 资深
TENURE_MATURE = 4.0   # 4–8 年 成熟；2–4 年 新锐；<2 年 新手
TENURE_JUNIOR = 2.0

# 「一拖多」提示阈值（团队内单人在管基金数最大值）
OVER_EXTENDED = 15    # ≥15 只 提示精力可能分散


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _int(v):
    f = _num(v)
    if f is None:
        return None
    return int(f)


def experience_label(years):
    """从业年限（团队最大）→ 经验档位标签。None → None。"""
    y = _num(years)
    if y is None:
        return None
    if y >= TENURE_SENIOR:
        return '资深'
    if y >= TENURE_MATURE:
        return '成熟'
    if y >= TENURE_JUNIOR:
        return '新锐'
    return '新手'


def manager_experience(managers):
    """聚合一只基金的经理经验弱因子。

    managers: 可迭代 {'manager','company','tenure_days'(天),'total_aum'(亿),
                      'best_return'(%),'fund_count'(经理在管基金数)}。
    返回 dict：
      manager_count: 有效经理数（tenure_days 可解析）
      names: [经理姓名] 去重保序
      company: 主要所属公司（第一位有效经理）
      max_tenure_years / avg_tenure_years: 团队从业年限最大/平均（四舍两位）
      experience_label: 经验档位（按 max_tenure_years）
      best_return: 团队现任基金最佳回报最大值(%)
      max_fund_count: 团队内单人在管基金数最大值
      over_extended: 是否触发一拖多提示（max_fund_count ≥ OVER_EXTENDED）
    经理列表为空或全部无 tenure → 返回 None（handler 据此不渲染卡）。
    """
    if managers is None:
        return None
    names = []
    tenures = []
    best_returns = []
    fund_counts = []
    company = None
    for m in managers:
        if not isinstance(m, dict):
            continue
        name = m.get('manager')
        name = str(name).strip() if name is not None else ''
        td = _num(m.get('tenure_days'))
        if not name or td is None or td <= 0:
            continue
        if name in names:
            # 同名经理同基金重复行，跳过（去重在取数层已做，双保险）
            continue
        names.append(name)
        tenures.append(td / _DAYS_PER_YEAR)
        if company is None:
            c = m.get('company')
            company = str(c).strip() if c is not None and str(c).strip() else None
        br = _num(m.get('best_return'))
        if br is not None:
            best_returns.append(br)
        fc = _int(m.get('fund_count'))
        if fc is not None and fc > 0:
            fund_counts.append(fc)
    if not names:
        return None
    max_tenure = round(max(tenures), 2)
    avg_tenure = round(sum(tenures) / len(tenures), 2)
    max_fund_count = max(fund_counts) if fund_counts else None
    return {
        'manager_count': len(names),
        'names': names,
        'company': company,
        'max_tenure_years': max_tenure,
        'avg_tenure_years': avg_tenure,
        'experience_label': experience_label(max_tenure),
        'best_return': round(max(best_returns), 2) if best_returns else None,
        'max_fund_count': max_fund_count,
        'over_extended': bool(max_fund_count is not None and max_fund_count >= OVER_EXTENDED),
    }
