"""Phase 3a: 专利含金量评分 + 趋势计算 + 发明占比。

从 cn_stock_patent_info 公告数据聚合出分析指标，
写入 cn_stock_patents 聚合表供 AI 报告使用。
"""
from __future__ import annotations

import datetime
import logging
from typing import Any, Dict, List, Optional

_logger = logging.getLogger(__name__)


def calculate_invention_ratio(
    invention: int, utility: int, design: int, other: int = 0
) -> Optional[float]:
    """计算发明专利占比 (%)。"""
    total = invention + utility + design + other
    if total <= 0:
        return None
    return round(invention / total * 100, 2)


def calculate_trend_metrics(trend_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """从多年数据计算趋势指标。

    Args:
        trend_data: [{"year": 2021, "count": 30}, {"year": 2022, "count": 45}, ...]

    Returns:
        {
            "trend_5y_cagr": 15.2,
            "trend_direction": "accelerating" | "stable" | "decelerating" | "declining",
            "trend_5y": [...],
        }
    """
    if not trend_data or len(trend_data) < 2:
        return {'trend_5y_cagr': None, 'trend_direction': None, 'trend_5y': trend_data or []}

    # 按 year 升序排列
    trend_data = sorted(trend_data, key=lambda x: x['year'])
    # 过滤异常值
    trend_data = [d for d in trend_data if (d.get('count') or 0) >= 0]
    if len(trend_data) < 2:
        return {'trend_5y_cagr': None, 'trend_direction': None, 'trend_5y': trend_data}

    first_count = trend_data[0]['count']
    last_count = trend_data[-1]['count']
    years = trend_data[-1]['year'] - trend_data[0]['year']

    # CAGR (需要至少跨1年)
    if years <= 0:
        cagr = None
    elif first_count > 0:
        cagr = ((last_count / first_count) ** (1 / years) - 1) * 100
    elif first_count == 0 and last_count > 0:
        cagr = 100.0
    else:
        cagr = 0.0

    # 趋势方向 — 至少3个数据点才能判断加速/减速
    direction: Optional[str] = None
    if len(trend_data) >= 3:
        mid = len(trend_data) // 2
        first_half_growth = (
            (trend_data[mid]['count'] - trend_data[0]['count'])
            / max(trend_data[0]['count'], 1)
        )
        second_half_growth = (
            (trend_data[-1]['count'] - trend_data[mid]['count'])
            / max(trend_data[mid]['count'], 1)
        )
        # 先判断整体方向
        if last_count < first_count * 0.9:
            # 整体下降
            if second_half_growth >= 0:
                direction = 'decelerating'  # 下降减缓/企稳
            elif abs(second_half_growth) < abs(first_half_growth) * 0.7:
                direction = 'decelerating'  # 跌幅收窄
            else:
                direction = 'declining'  # 持续下跌
        elif last_count > first_count * 1.1:
            # 整体增长
            if second_half_growth > first_half_growth * 1.2 and first_half_growth > 0:
                direction = 'accelerating'
            elif second_half_growth > first_half_growth * 0.5 or second_half_growth > 0:
                direction = 'stable'
            else:
                direction = 'decelerating'  # 增速放缓
        else:
            direction = 'stable'

    return {
        'trend_5y_cagr': round(cagr, 2) if cagr is not None else None,
        'trend_direction': direction,
        'trend_5y': trend_data,
    }


def calculate_patent_quality_score(row: Dict[str, Any]) -> int:
    """综合评估专利含金量 (0-100分)。

    维度权重:
    - 发明专利占比 (35%): 发明专利技术门槛最高
    - 专利数量规模 (25%): 绝对数量代表研发投入
    - 5年增长趋势 (25%): 持续创新能力
    - 研发人员占比 (15%): 研发投入另一维度
    """
    score = 0

    # 1. 发明专利占比 (35分)
    inv_ratio = row.get('invention_ratio') or 0
    if inv_ratio >= 80:
        score += 35
    elif inv_ratio >= 60:
        score += 28
    elif inv_ratio >= 40:
        score += 20
    elif inv_ratio >= 20:
        score += 12
    else:
        score += 5

    # 2. 专利数量 (25分)
    total = row.get('total_patents') or 0
    if total >= 500:
        score += 25
    elif total >= 200:
        score += 20
    elif total >= 100:
        score += 15
    elif total >= 30:
        score += 10
    elif total >= 10:
        score += 6
    else:
        score += 2

    # 3. 5年CAGR (25分)
    cagr = row.get('trend_5y_cagr')
    if cagr is None:
        score += 10  # 无趋势数据给中间分
    elif cagr >= 30:
        score += 25
    elif cagr >= 15:
        score += 20
    elif cagr >= 5:
        score += 15
    elif cagr >= 0:
        score += 10
    else:
        score += 3  # 负增长

    # 4. 研发人员占比 (15分)
    rd_ratio = row.get('rd_staff_ratio')
    if rd_ratio is None:
        score += 5  # 无数据给基础分
    elif rd_ratio >= 30:
        score += 15
    elif rd_ratio >= 20:
        score += 12
    elif rd_ratio >= 10:
        score += 8
    elif rd_ratio >= 5:
        score += 5
    else:
        score += 2

    return min(score, 100)


def validate_patent_data(data: Dict[str, Any]) -> tuple:
    """校验专利数据合理性。返回 (is_valid, reason)。"""
    # 数量非负
    for field in ('total_patents', 'invention_patents', 'utility_patents', 'design_patents'):
        val = data.get(field)
        if val is not None and val < 0:
            return False, f'{field} 不能为负数: {val}'

    # 分项之和 ≤ 总数 (允许10%误差)
    inv = data.get('invention_patents') or 0
    util = data.get('utility_patents') or 0
    des = data.get('design_patents') or 0
    total = data.get('total_patents') or 0
    if total > 0 and (inv + util + des) > total * 1.1:
        return False, (
            f'分项之和({inv}+{util}+{des}={inv + util + des}) '
            f'超过总数({total})的110%'
        )

    # 专利总数不超过 50000
    if total > 50000:
        return False, f'专利总数异常偏高: {total}'

    # 研发人员占比 0-100%
    ratio = data.get('rd_staff_ratio')
    if ratio is not None and (ratio < 0 or ratio > 100):
        return False, f'rd_staff_ratio 超出范围: {ratio}%'

    # 年份合理性
    year = data.get('year')
    current_year = datetime.date.today().year
    if year is not None and (year < 1990 or year > current_year + 1):
        return False, f'year 超出合理范围: {year}'

    return True, 'OK'
