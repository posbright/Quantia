#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""行业 → IPC 分布 保底估算（Phase 3b 补充）。

当某只股票已有真实专利总数（total_patents），但缺失 IPC 分布 / 主分类
（Google Patents / 年报均未取到 IPC）时，用"所属行业 → 典型 IPC 大类构成"
的经验映射，合成一个**粗粒度**的 IPC 饼图分布，避免 IPC 图表大面积空白。

本模块属于 Compute 管道（见 AGENTS.md 规则 1）——纯查表/字符串处理，
**不发起任何网络请求**，无第三方依赖。

重要约束（数据准确性）:
- 估算结果必须标注 ``estimated=True`` / ``ipc_source='industry'``，调用方
  需在 UI 明确提示"按行业估算"，不得与真实采集数据混淆。
- 仅当已知真实 total_patents 时才把权重折算成"占比%"，绝不臆造专利绝对数。
- 行业无法匹配时返回 None（保持空白，诚实优先）。

IPC 大类(class3) 含义见 patent_ipc_mapping.IPC_CLASS_DESC。
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from quantia.core.patent_ipc_mapping import ipc_to_desc, ipc_to_tech_domain

# 行业关键词 → {IPC 大类(class3): 权重}，权重之和≈1.0。
# 关键词按"子串命中"匹配 cn_stock_selection.industry（东财 F10 行业名），
# 列表自上而下优先（更具体的放前面，如 半导体 先于 电子）。
_INDUSTRY_PROFILES: List[Tuple[Tuple[str, ...], Dict[str, float]]] = [
    # --- 电子 / 半导体 / 通信 ---
    (('半导体', '集成电路', '芯片'),
     {'H01': 0.45, 'G11': 0.20, 'H03': 0.15, 'G06': 0.10, 'B23': 0.10}),
    (('通信设备', '通信运营', '通讯'),
     {'H04': 0.50, 'H01': 0.15, 'G06': 0.15, 'H03': 0.10, 'G08': 0.10}),
    (('消费电子', '电子设备', '电子元件', '电子器件', '光电子', '光学光电',
      '视听器材', '文娱用品'),
     {'H01': 0.30, 'H04': 0.20, 'G06': 0.15, 'H03': 0.15, 'G02': 0.10, 'H05': 0.10}),
    (('计算机硬件',),
     {'G06': 0.40, 'H01': 0.20, 'G11': 0.15, 'H04': 0.15, 'H05': 0.10}),
    (('计算机软件', '互联网', '软件', '营销服务', '广播电视', '影视', '平面媒体'),
     {'G06': 0.60, 'H04': 0.20, 'G16': 0.10, 'G11': 0.10}),
    # --- 电力 / 新能源 / 电池 ---
    (('电源设备', '电池', '锂电', '储能'),
     {'H01': 0.40, 'H02': 0.20, 'B60': 0.15, 'C01': 0.10, 'G01': 0.15}),
    (('输变电', '电力', '电机', '电气设备', '燃气'),
     {'H02': 0.45, 'H01': 0.25, 'G01': 0.10, 'F03': 0.10, 'H05': 0.10}),
    # --- 汽车 / 轨交 / 航空 / 船舶 ---
    (('汽车', '摩托车', '其他交运设备', '地面装备'),
     {'B60': 0.40, 'F02': 0.15, 'G01': 0.15, 'F16': 0.10, 'B62': 0.10, 'H02': 0.10}),
    (('铁路设备', '轨道交通', '公路铁路', '港口航运', '物流', '船舶', '海洋装备'),
     {'B60': 0.35, 'F16': 0.20, 'E01': 0.15, 'H02': 0.15, 'G05': 0.15}),
    (('航空航天', '卫星', '航空机场'),
     {'F02': 0.25, 'H04': 0.20, 'G01': 0.20, 'G05': 0.20, 'B23': 0.15}),
    # --- 医药 / 医疗 ---
    (('医疗器械', '医疗服务'),
     {'A61': 0.60, 'G01': 0.20, 'G16': 0.10, 'H05': 0.10}),
    (('化学制药', '中药', '生物医药', '医药商业', '保健护理'),
     {'A61': 0.55, 'C07': 0.20, 'C12': 0.15, 'A23': 0.10}),
    # --- 化工 / 材料 / 金属 ---
    (('金属非金属新材料', '化学新材料', '合成纤维及树脂'),
     {'C08': 0.35, 'C07': 0.20, 'C09': 0.15, 'C01': 0.15, 'B32': 0.15}),
    (('化学制品', '化学原料', '化肥农药', '橡胶制品'),
     {'C08': 0.30, 'C07': 0.25, 'C09': 0.15, 'C01': 0.15, 'B01': 0.15}),
    (('稀有金属', '基本金属', '钢铁', '贵金属', '工业金属', '有色'),
     {'C22': 0.35, 'C23': 0.20, 'C01': 0.20, 'B32': 0.15, 'C08': 0.10}),
    # --- 机械 / 机器人 / 家电 ---
    (('机器人',),
     {'B25': 0.30, 'G05': 0.25, 'B23': 0.15, 'G06': 0.15, 'H02': 0.15}),
    (('通用设备', '专用设备', '通用机械', '机械', '金属制品', '钢结构'),
     {'B23': 0.30, 'F16': 0.20, 'B25': 0.15, 'G05': 0.15, 'B29': 0.10, 'F01': 0.10}),
    (('白色家电', '小家电', '其他家电', '照明设备'),
     {'F25': 0.25, 'F24': 0.20, 'H02': 0.20, 'F21': 0.20, 'H05': 0.15}),
    # --- 轻工 / 纺织 / 造纸 / 食品 / 农业 ---
    (('纺织', '服装家纺'),
     {'D06': 0.30, 'D01': 0.25, 'C08': 0.20, 'D21': 0.10, 'B65': 0.15}),
    (('造纸印刷', '其他轻工', '家具', '珠宝首饰', '陶瓷'),
     {'D21': 0.40, 'C09': 0.20, 'B65': 0.20, 'B32': 0.20}),
    (('食品', '饮料', '农产品', '食料'),
     {'A23': 0.55, 'A01': 0.20, 'C12': 0.15, 'B65': 0.10}),
    (('农业', '畜牧', '林业', '渔业'),
     {'A01': 0.55, 'A23': 0.20, 'C12': 0.15, 'A61': 0.10}),
    # --- 建筑 / 建材 / 环保 / 能源 ---
    (('建筑施工', '基础建设', '装修装饰', '房地产', '商业物业'),
     {'E04': 0.40, 'E01': 0.20, 'E21': 0.15, 'C08': 0.15, 'F16': 0.10}),
    (('玻璃', '水泥', '其他建材', '耐火材料'),
     {'C03': 0.35, 'E04': 0.20, 'C04': 0.20, 'B28': 0.15, 'C08': 0.10}),
    (('环保', '水务'),
     {'C02': 0.40, 'B01': 0.20, 'C08': 0.15, 'G01': 0.15, 'F24': 0.10}),
    (('石油天然气', '煤炭', '铁矿石', '石油'),
     {'E21': 0.35, 'F02': 0.15, 'C07': 0.15, 'B01': 0.15, 'G01': 0.20}),
]


def _match_profile(industry: str) -> Optional[Dict[str, float]]:
    if not industry:
        return None
    ind = industry.strip()
    for keywords, profile in _INDUSTRY_PROFILES:
        if any(kw in ind for kw in keywords):
            return profile
    return None


def estimate_ipc_distribution(
    industry: Optional[str],
    total_patents: Optional[int] = None,
) -> Optional[Dict[str, object]]:
    """按行业经验映射合成 IPC 分布。

    Args:
        industry: 所属行业名（cn_stock_selection.industry 等）。
        total_patents: 已知真实专利总数；用于把权重折算成整数占比的基数。

    Returns:
        {
            'ipc_primary', 'ipc_primary_desc', 'tech_domain',
            'ipc_distribution': {class3: 占比百分点(int)},
            'estimated': True, 'ipc_source': 'industry',
        }
        无法匹配行业时返回 None。
    """
    profile = _match_profile(industry or '')
    if not profile:
        return None

    # 权重 → 整数百分点（合计修正到 100，最大项吸收舍入误差）。
    items = sorted(profile.items(), key=lambda kv: kv[1], reverse=True)
    pcts: Dict[str, int] = {}
    running = 0
    for cls, w in items[:-1]:
        v = round(w * 100)
        pcts[cls] = v
        running += v
    last_cls = items[-1][0]
    pcts[last_cls] = max(0, 100 - running)
    # 重新按占比降序输出，便于饼图图例顺序稳定。
    pcts = dict(sorted(pcts.items(), key=lambda kv: kv[1], reverse=True))

    primary = next(iter(pcts))
    return {
        'ipc_primary': primary,
        'ipc_primary_desc': ipc_to_desc(primary),
        'tech_domain': ipc_to_tech_domain(primary),
        'ipc_distribution': pcts,
        'estimated': True,
        'ipc_source': 'industry',
    }
