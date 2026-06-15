#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""指标买卖信号「指标设置」页 UI Schema。

合并进 strategyParamsHandler.DEFAULT_STRATEGY_PARAMS 后，前端即可复用通用的
/quantia/api/strategy/params(/save/reset) 接口管理 strategy_key='indicator_signal'。

value 全部引用 buy_sell_signal.DEFAULT_PARAMS，避免与计算端默认值漂移。
每个参数都带 description 注明业务含义，供前端 tooltip 展示。
"""

import quantia.core.indicator.buy_sell_signal as bss

_D = bss.DEFAULT_PARAMS

INDICATOR_SIGNAL_PARAMS = {
    "indicator_signal": {
        "name": "指标买卖信号",
        "description": (
            "「指标买入 / 指标卖出」榜单的筛选阈值。买入 = 自历史最高深跌 + 指标极度超卖；"
            "卖出 = 贴近历史峰值 + 指标极度超买。所有阈值可在此调整，保存后下一次定时计算"
            "（或点击「立即重算」）生效。"
        ),
        "groups": [
            {
                "group_name": "买入 · 技术超卖阈值",
                "group_description": "五个动量/超买超卖指标同时进入极度超卖区，才视为抄底候选。阈值越低越严格。",
                "params": [
                    {
                        "key": "buy_rsi_6",
                        "label": "RSI(6) 上限",
                        "description": "RSI 相对强弱指标（6日）：衡量近期涨跌力量，0~100。<20 为超卖、<15 极度超卖。买入要求 RSI(6) 低于该值。",
                        "type": "number", "value": _D['buy_rsi_6'],
                        "min": 5, "max": 40, "step": 1, "unit": ""
                    },
                    {
                        "key": "buy_kdjj",
                        "label": "KDJ-J 上限",
                        "description": "KDJ 随机指标的 J 值：对超买超卖最敏感，可 <0 或 >100。J<0 表示极度超卖。买入要求 J 低于该值。",
                        "type": "number", "value": _D['buy_kdjj'],
                        "min": -30, "max": 20, "step": 1, "unit": ""
                    },
                    {
                        "key": "buy_wr_6",
                        "label": "WR(6) 上限",
                        "description": "威廉指标（6日），范围 -100~0。越接近 -100 越超卖（<-80 超卖，<-90 极度超卖）。买入要求 WR(6) 低于该值。",
                        "type": "number", "value": _D['buy_wr_6'],
                        "min": -100, "max": -70, "step": 1, "unit": ""
                    },
                    {
                        "key": "buy_cci",
                        "label": "CCI 上限",
                        "description": "顺势指标 CCI：衡量价格偏离均值的程度。<-100 超卖，<-150 极度超卖。买入要求 CCI 低于该值。",
                        "type": "number", "value": _D['buy_cci'],
                        "min": -300, "max": -100, "step": 10, "unit": ""
                    },
                    {
                        "key": "buy_mfi",
                        "label": "MFI 上限",
                        "description": "资金流量指标 MFI（量价版 RSI），0~100。<20 表示资金大幅流出后的超卖。买入要求 MFI 低于该值。",
                        "type": "number", "value": _D['buy_mfi'],
                        "min": 5, "max": 40, "step": 1, "unit": ""
                    },
                ]
            },
            {
                "group_name": "买入 · 深跌回撤",
                "group_description": "要求现价相对历史最高点已深度回撤，过滤掉仅短期回调的标的。",
                "params": [
                    {
                        "key": "buy_drawdown_ratio",
                        "label": "最小回撤比例",
                        "description": "现价需 ≤ (1 - 该比例) × 历史最高高点。0.80 = 自最高点跌幅 ≥ 80% 才算抄底候选；调低可放宽（如 0.50 = 跌 50% 即可）。",
                        "type": "number", "value": _D['buy_drawdown_ratio'],
                        "min": 0.30, "max": 0.95, "step": 0.05, "unit": ""
                    },
                ]
            },
            {
                "group_name": "卖出 · 技术超买阈值",
                "group_description": "五个指标同时进入极度超买区，视为见顶派发候选。阈值越高越严格。",
                "params": [
                    {
                        "key": "sell_rsi_6",
                        "label": "RSI(6) 下限",
                        "description": "RSI 相对强弱指标（6日）。>80 超买、>85 极度超买。卖出要求 RSI(6) 高于该值。",
                        "type": "number", "value": _D['sell_rsi_6'],
                        "min": 60, "max": 95, "step": 1, "unit": ""
                    },
                    {
                        "key": "sell_kdjj",
                        "label": "KDJ-J 下限",
                        "description": "KDJ 的 J 值。J>100 表示极度超买。卖出要求 J 高于该值。",
                        "type": "number", "value": _D['sell_kdjj'],
                        "min": 80, "max": 130, "step": 1, "unit": ""
                    },
                    {
                        "key": "sell_wr_6",
                        "label": "WR(6) 下限",
                        "description": "威廉指标（6日），-100~0。越接近 0 越超买（>-20 超买，>-10 极度超买）。卖出要求 WR(6) 高于该值。",
                        "type": "number", "value": _D['sell_wr_6'],
                        "min": -30, "max": 0, "step": 1, "unit": ""
                    },
                    {
                        "key": "sell_cci",
                        "label": "CCI 下限",
                        "description": "顺势指标 CCI。>100 超买，>150 极度超买。卖出要求 CCI 高于该值。",
                        "type": "number", "value": _D['sell_cci'],
                        "min": 100, "max": 300, "step": 10, "unit": ""
                    },
                    {
                        "key": "sell_mfi",
                        "label": "MFI 下限",
                        "description": "资金流量指标 MFI，0~100。>80 表示资金大幅流入后的超买。卖出要求 MFI 高于该值。",
                        "type": "number", "value": _D['sell_mfi'],
                        "min": 60, "max": 95, "step": 1, "unit": ""
                    },
                ]
            },
            {
                "group_name": "卖出 · 贴近峰值",
                "group_description": "要求现价已回到历史最高点附近，确认是高位派发而非低位反弹。",
                "params": [
                    {
                        "key": "sell_drawdown_ratio",
                        "label": "贴近峰值比例",
                        "description": "现价需 ≥ 该比例 × 历史最高高点。0.80 = 现价已回到历史最高的 80% 以上才算见顶派发候选。",
                        "type": "number", "value": _D['sell_drawdown_ratio'],
                        "min": 0.50, "max": 1.00, "step": 0.05, "unit": ""
                    },
                ]
            },
            {
                "group_name": "风险排除",
                "group_description": "剔除退市/风险警示类标的，避免抄底踩雷。",
                "params": [
                    {
                        "key": "exclude_st",
                        "label": "排除 ST / *ST",
                        "description": "开启后剔除名称含「ST」的风险警示股（财务异常、被特别处理）。",
                        "type": "switch", "value": _D['exclude_st'],
                        "min": 0, "max": 1, "step": 1, "unit": ""
                    },
                    {
                        "key": "exclude_delist",
                        "label": "排除退市风险",
                        "description": "开启后剔除名称含「退」的退市整理/已退市标的。",
                        "type": "switch", "value": _D['exclude_delist'],
                        "min": 0, "max": 1, "step": 1, "unit": ""
                    },
                ]
            },
            {
                "group_name": "基本面可选过滤（默认关闭）",
                "group_description": "可选地叠加估值/盈利质量过滤。开启后买入信号会与当日行情快照按 PE/PB/ROE 区间过滤，信号将明显变少。",
                "params": [
                    {
                        "key": "fund_filter_enabled",
                        "label": "启用基本面过滤",
                        "description": "总开关。关闭时仅用技术 + 回撤 + 风险排除；开启后再叠加下方 PE/PB/ROE 区间。",
                        "type": "switch", "value": _D['fund_filter_enabled'],
                        "min": 0, "max": 1, "step": 1, "unit": ""
                    },
                    {
                        "key": "fund_pe_min",
                        "label": "市盈率(动) 下限",
                        "description": "PE(TTM) 下限。设为 >0 可剔除亏损股（PE 为负或为 0）。",
                        "type": "number", "value": _D['fund_pe_min'],
                        "min": 0, "max": 30, "step": 1, "unit": "倍"
                    },
                    {
                        "key": "fund_pe_max",
                        "label": "市盈率(动) 上限",
                        "description": "PE(TTM) 上限。越低越偏低估值；成长股可适当放宽。",
                        "type": "number", "value": _D['fund_pe_max'],
                        "min": 5, "max": 100, "step": 1, "unit": "倍"
                    },
                    {
                        "key": "fund_pb_max",
                        "label": "市净率 上限",
                        "description": "PB(MRQ) 上限。越低越偏向破净/低估值；重资产行业可放宽。",
                        "type": "number", "value": _D['fund_pb_max'],
                        "min": 1, "max": 30, "step": 1, "unit": "倍"
                    },
                    {
                        "key": "fund_roe_min",
                        "label": "ROE(加权) 下限(%)",
                        "description": "加权净资产收益率下限。>=15% 为优质企业标准，可放宽至 10% 扩大范围。",
                        "type": "number", "value": _D['fund_roe_min'],
                        "min": 0, "max": 40, "step": 1, "unit": "%"
                    },
                ]
            },
        ]
    }
}
