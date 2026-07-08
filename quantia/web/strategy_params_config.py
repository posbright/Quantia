#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全部策略参数定义（K线技术策略 + 指标筛选策略）

每个策略包含:
- name: 中文名
- description: 策略详细说明（包含原理、适用场景、风险提示）
- groups: 参数分组，每组包含多个可调参数

指标买入/卖出（indicator_buy / indicator_sell）的参数 schema 直接复用
indicator_params_config.INDICATOR_SIGNAL_PARAMS（单一真源，引用
buy_sell_signal.DEFAULT_PARAMS），并通过 storage_key='indicator_signal'
与「指标设置」页共用同一份底层参数，避免双处漂移、保证保存即生效。
"""

import copy

from quantia.web.indicator_params_config import INDICATOR_SIGNAL_PARAMS as _ISP


def _sig_groups(*group_names):
    """从 INDICATOR_SIGNAL_PARAMS 中按 group_name 取出指定分组的深拷贝。

    指标买入页只展示「买入 + 风险排除 + 基本面」分组，卖出页只展示
    「卖出 + 风险排除」分组；底层仍是同一份 indicator_signal 参数。
    """
    src = _ISP['indicator_signal']['groups']
    by_name = {g['group_name']: g for g in src}
    return [copy.deepcopy(by_name[name]) for name in group_names if name in by_name]


TECHNICAL_STRATEGY_PARAMS = {
    "enter": {
        "name": "放量上涨",
        "description": "检测高成交量伴随大幅上涨的股票，通常意味着主力资金介入。\n\n"
                       "选股条件：\n"
                       "1. 当日涨幅 ≥ 设定阈值且收阳线（收盘价 > 开盘价）\n"
                       "2. 当日成交额 ≥ 设定金额（过滤小票）\n"
                       "3. 当日成交量 ≥ 5日均量的N倍（确认放量）\n\n"
                       "适用场景：捕捉突破启动信号，建议配合均线位置和形态综合判断。\n"
                       "风险提示：放量上涨也可能是主力出货，注意结合后续走势确认。",
        "strategy_func": "cn_stock_strategy_enter",
        "groups": [
            {
                "group_name": "涨幅条件",
                "params": [
                    {"key": "min_change", "label": "最低涨幅(%)", "description": "当日涨幅必须大于此值",
                     "type": "number", "value": 2, "min": 0.5, "max": 10, "step": 0.5, "unit": "%"},
                ]
            },
            {
                "group_name": "成交量条件",
                "params": [
                    {"key": "vol_ma_period", "label": "均量周期(天)", "description": "计算平均成交量的天数",
                     "type": "number", "value": 5, "min": 3, "max": 20, "step": 1, "unit": "天"},
                    {"key": "vol_ratio", "label": "放量倍数", "description": "当日成交量需达到均量的N倍",
                     "type": "number", "value": 2, "min": 1.2, "max": 5, "step": 0.1, "unit": "倍"},
                    {"key": "min_turnover", "label": "最低成交额(亿)", "description": "过滤成交额过小的股票",
                     "type": "number", "value": 2, "min": 0.5, "max": 10, "step": 0.5, "unit": "亿"},
                ]
            },
            {
                "group_name": "窗口设置",
                "params": [
                    {"key": "threshold", "label": "回溯天数", "description": "分析所需的最少历史交易日数",
                     "type": "number", "value": 60, "min": 20, "max": 250, "step": 10, "unit": "天"},
                ]
            }
        ]
    },
    "keep_increasing": {
        "name": "均线多头",
        "description": "检测均线多头排列的股票：短、中、长期均线自上而下排列，中期趋势向好。\n\n"
                       "选股条件（可调优）：\n"
                       "1. 中期严格多头：MA10 > MA20 > MA30\n"
                       "2. 短期条件：默认放宽为 MA5 > MA20（容忍上升通道中的小回调）；可切换为严格 MA5 > MA10\n"
                       "3. 长期趋势：默认用「MA60 斜率向上」确认（上升初期即可入选）；可切换为严格 MA30 > MA60\n"
                       "4. 统计多头排列已连续出现的天数（bull_days）\n\n"
                       "结果默认按多头排列天数从小到大排序，天数越小表示刚形成多头排列。\n"
                       "适用场景：中线趋势投资，适合追踪刚确认上升趋势的标的。\n"
                       "风险提示：均线是滞后指标，趋势末期可能发出虚假信号。",
        "strategy_func": "cn_stock_strategy_keep_increasing",
        "groups": [
            {
                "group_name": "均线参数",
                "params": [
                    {"key": "threshold", "label": "回溯天数", "description": "分析所需的最少历史交易日数（需≥60以计算MA60）",
                     "type": "number", "value": 60, "min": 60, "max": 250, "step": 10, "unit": "天"},
                    {"key": "include_ma5", "label": "短期均线约束", "description": "短期均线判定方式。放宽(推荐)：仅要求 MA5>MA20，容忍上升途中的小回调；严格：要求 MA5>MA10，对短期噪声敏感、信号更少。",
                     "type": "select", "value": 0,
                     "options": [{"label": "放宽 MA5>MA20（推荐）", "value": 0}, {"label": "严格 MA5>MA10", "value": 1}]},
                    {"key": "ma60_mode", "label": "长期趋势判定", "description": "MA30 与 MA60 的关系判定。斜率向上(推荐)：MA60 上行即确认，入场更早；严格：要求 MA30>MA60，入场滞后；任一满足：两者满足其一。",
                     "type": "select", "value": "rising",
                     "options": [{"label": "MA60 斜率向上（推荐）", "value": "rising"}, {"label": "严格 MA30>MA60", "value": "strict"}, {"label": "任一满足", "value": "either"}]},
                    {"key": "ma60_slope_window", "label": "MA60斜率回看", "description": "判定 MA60 斜率向上时的回看交易日数（当前MA60 > N日前MA60 即视为上行）",
                     "type": "number", "value": 5, "min": 1, "max": 20, "step": 1, "unit": "天"},
                ]
            }
        ]
    },
    "low_ma_convergence": {
        "name": "低位均线粘合",
        "description": "捕捉价格处于阶段低位，且 MA5/10/20/30/60 多条均线高度靠拢的股票。\n\n"
                       "选股条件：\n"
                       "1. 当前收盘价处于近N日高低价区间的中低位，默认不高于80%位置\n"
                       "2. MA5、MA10、MA20、MA30、MA60 五条均线最大差距 ≤ 均线均值的设定比例\n"
                       "3. 当前收盘价没有明显远离MA60，避免价格已脱离粘合区\n"
                       "4. MA60 不能继续明显下行，过滤下降趋势中的假粘合\n\n"
                       "适用场景：寻找长期下跌或横盘后的低位收敛形态，适合等待方向选择。\n"
                       "风险提示：均线粘合只代表波动收敛，不代表一定向上突破，建议结合成交量和基本面确认。",
        "strategy_func": "cn_stock_strategy_low_ma_convergence",
        "groups": [
            {
                "group_name": "低位条件",
                "params": [
                    {"key": "low_window", "label": "低位观察窗口", "description": "用近N日高低价区间判断当前价格位置",
                     "type": "number", "value": 120, "min": 60, "max": 500, "step": 10, "unit": "天"},
                    {"key": "low_position_pct", "label": "最高低位百分位(%)", "description": "收盘价在区间内的位置需不高于此百分位，越低越严格",
                     "type": "number", "value": 80, "min": 5, "max": 90, "step": 1, "unit": "%"},
                ]
            },
            {
                "group_name": "均线粘合",
                "params": [
                    {"key": "convergence_pct", "label": "最大粘合度(%)", "description": "五条均线最大值与最小值的差距 / 均线均值，越小越严格",
                     "type": "number", "value": 6, "min": 1, "max": 15, "step": 0.5, "unit": "%"},
                    {"key": "max_close_ma60_dev", "label": "收盘偏离MA60上限(%)", "description": "避免股价已明显脱离长期均线粘合区",
                     "type": "number", "value": 8, "min": 1, "max": 20, "step": 0.5, "unit": "%"},
                    {"key": "threshold", "label": "回溯天数", "description": "分析所需的最少历史交易日数，通常与低位观察窗口一致或更长",
                     "type": "number", "value": 120, "min": 60, "max": 500, "step": 10, "unit": "天"},
                ]
            },
            {
                "group_name": "趋势过滤",
                "params": [
                    {"key": "enable_trend_filter", "label": "启用趋势过滤", "description": "开启后要求 MA60 近N日不能继续明显下行，过滤下降趋势中的均线粘合",
                     "type": "select", "value": 1,
                     "options": [{"label": "开启（推荐）", "value": 1}, {"label": "关闭", "value": 0}]},
                    {"key": "trend_slope_window", "label": "趋势斜率回看", "description": "计算 MA30/MA60 斜率的回看交易日数；默认1日用于判断MA60当日是否继续下行",
                     "type": "number", "value": 1, "min": 1, "max": 60, "step": 1, "unit": "天"},
                    {"key": "min_ma30_slope_pct", "label": "MA30斜率下限(%)", "description": "MA30 近N日涨跌幅不得低于此值；主要过滤短中期均线明显下压",
                     "type": "number", "value": -0.5, "min": -10, "max": 5, "step": 0.1, "unit": "%"},
                    {"key": "min_ma60_slope_pct", "label": "MA60斜率下限(%)", "description": "MA60 近N日涨跌幅不得低于此值；默认允许极小噪声，明显下行则过滤",
                     "type": "number", "value": -0.1, "min": -10, "max": 5, "step": 0.1, "unit": "%"},
                ]
            }
        ]
    },
    "parking_apron": {
        "name": "停机坪",
        "description": "高位放量涨停后的窄幅整理形态，类似飞机在停机坪暂停准备再次起飞。\n\n"
                       "选股条件：\n"
                       "1. 近N日内有≥涨停阈值的大阳线，且该涨停日收盘创近N日新高（突破确认）\n"
                       "2. 涨停后的整理日收盘/开盘偏差 < 设定比例\n"
                       "3. 整理日涨跌幅在设定范围内\n\n"
                       "适用场景：短线强势股整理后二次拉升机会。\n"
                       "风险提示：假突破风险较高，需结合大盘环境判断。",
        "strategy_func": "cn_stock_strategy_parking_apron",
        "groups": [
            {
                "group_name": "涨停条件",
                "params": [
                    {"key": "limit_up_pct", "label": "涨停阈值(%)", "description": "认定为涨停的最低涨幅",
                     "type": "number", "value": 9.5, "min": 5, "max": 20, "step": 0.5, "unit": "%"},
                ]
            },
            {
                "group_name": "整理条件",
                "params": [
                    {"key": "consolidation_days", "label": "整理天数", "description": "涨停后检查的整理天数",
                     "type": "number", "value": 3, "min": 1, "max": 10, "step": 1, "unit": "天"},
                    {"key": "max_open_close_ratio", "label": "开收盘偏差上限(%)", "description": "整理日开盘与收盘的最大偏差",
                     "type": "number", "value": 3, "min": 1, "max": 5, "step": 0.5, "unit": "%"},
                    {"key": "max_daily_change", "label": "日涨跌幅上限(%)", "description": "整理日最大允许的涨跌幅",
                     "type": "number", "value": 5, "min": 2, "max": 10, "step": 0.5, "unit": "%"},
                ]
            },
            {
                "group_name": "窗口设置",
                "params": [
                    {"key": "threshold", "label": "回溯天数", "description": "分析窗口长度",
                     "type": "number", "value": 15, "min": 5, "max": 30, "step": 1, "unit": "天"},
                ]
            }
        ]
    },
    "backtrace_ma250": {
        "name": "回踩年线",
        "description": "股价突破250日均线后回踩不破，伴随缩量，是经典的买入位置。\n\n"
                       "选股条件：\n"
                       "1. 前段从MA250以下向上突破\n"
                       "2. 后段始终在MA250以上运行\n"
                       "3. 最高价日与回踩最低价日相差在设定天数范围内\n"
                       "4. 回踩伴随缩量，缩量比和回撤比需满足阈值\n\n"
                       "适用场景：中长线布局，适合在牛市初期或个股突破后的回踩确认买入。\n"
                       "风险提示：假突破后回踩可能直接跌破年线。",
        "strategy_func": "cn_stock_strategy_backtrace_ma250",
        "groups": [
            {
                "group_name": "均线参数",
                "params": [
                    {"key": "ma_period", "label": "均线周期", "description": "年线的MA周期（通常250日）",
                     "type": "number", "value": 250, "min": 120, "max": 300, "step": 10, "unit": "天"},
                ]
            },
            {
                "group_name": "回踩条件",
                "params": [
                    {"key": "min_pullback_days", "label": "最少回踩天数", "description": "最高价到最低价的最少间隔天数",
                     "type": "number", "value": 10, "min": 3, "max": 30, "step": 1, "unit": "天"},
                    {"key": "max_pullback_days", "label": "最多回踩天数", "description": "最高价到最低价的最多间隔天数",
                     "type": "number", "value": 50, "min": 20, "max": 120, "step": 5, "unit": "天"},
                    {"key": "vol_shrink_ratio", "label": "缩量比例", "description": "最高价日成交量 / 回踩最低价日成交量 需大于此值",
                     "type": "number", "value": 2, "min": 1.2, "max": 5, "step": 0.2, "unit": "倍"},
                    {"key": "max_back_ratio", "label": "最大回撤比", "description": "回踩最低价 / 最高价 需小于此值",
                     "type": "number", "value": 0.8, "min": 0.5, "max": 0.95, "step": 0.05, "unit": ""},
                ]
            },
            {
                "group_name": "窗口设置",
                "params": [
                    {"key": "threshold", "label": "回溯天数", "description": "寻找最高/最低价的窗口",
                     "type": "number", "value": 60, "min": 20, "max": 120, "step": 10, "unit": "天"},
                ]
            }
        ]
    },
    "breakthrough_platform": {
        "name": "突破平台",
        "description": "股价在MA60附近横盘整理形成平台后，近期放量向上突破，且当前仍站稳均线之上。\n\n"
                       "选股条件：\n"
                       "1. 平台整理：突破日之前紧邻的整理窗口（至少「平台最少天数」个交易日）收盘价持续贴近MA60（偏离在设定范围内），构成横盘平台\n"
                       "2. 近期突破：突破日（开盘价<MA60≤收盘价 且放量上涨）须发生在信号日当天或最近「近期突破窗口」个交易日内，取最近一次突破\n"
                       "3. 站稳均线：突破日至今收盘价持续≥MA60，未跌回均线下方（过滤已失效的旧突破）\n\n"
                       "适用场景：突破横盘整理平台的启动信号。\n"
                       "风险提示：假突破风险，建议等突破确认后再入场。",
        "strategy_func": "cn_stock_strategy_breakthrough_platform",
        "groups": [
            {
                "group_name": "平台参数",
                "params": [
                    {"key": "ma_period", "label": "均线周期", "description": "平台关键均线周期（MA60）",
                     "type": "number", "value": 60, "min": 20, "max": 120, "step": 10, "unit": "天"},
                    {"key": "min_platform_days", "label": "平台最少天数", "description": "突破日前紧邻的整理窗口最少交易日数，该窗口内收盘价须全部贴近MA60",
                     "type": "number", "value": 10, "min": 5, "max": 30, "step": 1, "unit": "天"},
                    {"key": "min_deviation", "label": "最小偏离(%)", "description": "平台期收盘价相对MA的最小偏离（负值=允许收盘价在MA下方，如-5%表示最多低于MA 5%）",
                     "type": "number", "value": -5, "min": -20, "max": 0, "step": 1, "unit": "%"},
                    {"key": "max_deviation", "label": "最大偏离(%)", "description": "平台期收盘价相对MA的最大偏离（正值=允许收盘价在MA上方，如20%表示最多高于MA 20%）",
                     "type": "number", "value": 20, "min": 5, "max": 50, "step": 5, "unit": "%"},
                ]
            },
            {
                "group_name": "突破窗口",
                "params": [
                    {"key": "recent_days", "label": "近期突破窗口", "description": "突破日须发生在信号日当天或最近N个交易日内（取最近一次突破），避免数月前的旧突破被持续误选",
                     "type": "number", "value": 3, "min": 1, "max": 10, "step": 1, "unit": "天"},
                    {"key": "threshold", "label": "回溯天数", "description": "分析窗口长度",
                     "type": "number", "value": 60, "min": 20, "max": 120, "step": 10, "unit": "天"},
                ]
            }
        ]
    },
    "low_backtrace_increase": {
        "name": "无大幅回撤",
        "description": "低波动稳健上涨，适合寻找走势平稳的上升趋势股。\n\n"
                       "选股条件：\n"
                       "1. 期间涨幅 ≥ 设定比例\n"
                       "2. 无单日跌幅超过阈值\n"
                       "3. 无两日累计跌幅超过阈值\n"
                       "4. 无高开低走超过阈值\n\n"
                       "适用场景：趋势稳健的中线投资标的筛选。\n"
                       "风险提示：历史低回撤不代表未来不会出现大幅回撤。",
        "strategy_func": "cn_stock_strategy_low_backtrace_increase",
        "groups": [
            {
                "group_name": "涨幅条件",
                "params": [
                    {"key": "min_increase_ratio", "label": "最低涨幅比例", "description": "期间收盘价涨幅需低于此比例（0.6=涨60%内）",
                     "type": "number", "value": 0.6, "min": 0.1, "max": 2.0, "step": 0.1, "unit": ""},
                ]
            },
            {
                "group_name": "回撤限制",
                "params": [
                    {"key": "max_single_day_drop", "label": "单日最大跌幅(%)", "description": "任意单日跌幅不能超过此值",
                     "type": "number", "value": -7, "min": -15, "max": -3, "step": 0.5, "unit": "%"},
                    {"key": "max_two_day_drop", "label": "两日累计最大跌幅(%)", "description": "任意连续两日累计跌幅不超过此值",
                     "type": "number", "value": -10, "min": -20, "max": -5, "step": 1, "unit": "%"},
                ]
            },
            {
                "group_name": "窗口设置",
                "params": [
                    {"key": "threshold", "label": "回溯天数", "description": "分析窗口长度",
                     "type": "number", "value": 60, "min": 20, "max": 120, "step": 10, "unit": "天"},
                ]
            }
        ]
    },
    "turtle_trade": {
        "name": "海龟交易法则",
        "description": "经典趋势跟踪策略，突破N日最高价时买入。\n\n"
                       "选股条件：\n"
                       "当日收盘价 ≥ 过去N个交易日的最高收盘价（通道突破）\n\n"
                       "适用场景：趋势跟踪，适合在强势市场中追涨强势股。\n"
                       "风险提示：震荡市中频繁假突破，建议在趋势确认后使用。",
        "strategy_func": "cn_stock_strategy_turtle_trade",
        "groups": [
            {
                "group_name": "通道参数",
                "params": [
                    {"key": "threshold", "label": "突破周期(天)", "description": "突破N日最高价的N值",
                     "type": "number", "value": 60, "min": 10, "max": 250, "step": 5, "unit": "天"},
                ]
            }
        ]
    },
    "high_tight_flag": {
        "name": "高而窄的旗形",
        "description": "快速大幅上涨后的窄幅整理，需机构参与确认。\n\n"
                       "选股条件：\n"
                       "1. 近3个月龙虎榜有机构买入（买方机构次数>1）\n"
                       "2. 收盘价 / 区间最低价 ≥ 涨幅倍数（几乎翻倍）\n"
                       "3. 区间内有连续两日涨幅 ≥ 涨停阈值\n\n"
                       "适用场景：超级强势股的二次拉升机会，极少出现。\n"
                       "风险提示：高风险高收益，仓位需严格控制。",
        "strategy_func": "cn_stock_strategy_high_tight_flag",
        "groups": [
            {
                "group_name": "涨幅条件",
                "params": [
                    {"key": "price_ratio", "label": "涨幅倍数", "description": "收盘价需达到区间最低价的倍数",
                     "type": "number", "value": 1.9, "min": 1.3, "max": 3.0, "step": 0.1, "unit": "倍"},
                    {"key": "limit_up_pct", "label": "涨停阈值(%)", "description": "连续涨停的最低涨幅",
                     "type": "number", "value": 9.5, "min": 5, "max": 20, "step": 0.5, "unit": "%"},
                ]
            },
            {
                "group_name": "窗口设置",
                "params": [
                    {"key": "threshold", "label": "最少上市天数", "description": "股票需至少上市交易的天数",
                     "type": "number", "value": 60, "min": 30, "max": 250, "step": 10, "unit": "天"},
                ]
            }
        ]
    },
    "climax_limitdown": {
        "name": "放量跌停",
        "description": "检测放量封死跌停板的恐慌性抛售。\n\n"
                       "选股条件：\n"
                       "1. 单日真实跌幅贴近所属板块跌停限制（主板±10%、创业板/科创板±20%、"
                       "北交所±30%、主板ST±5%，自适应判定，并剔除除权/停牌复牌造成的价格伪跳变）\n"
                       "2. 收盘价封死在当日最低价附近（封板确认）\n"
                       "3. 当日成交量 ≥ 5日均量的N倍，且成交额 ≥ 设定金额（放量）\n\n"
                       "适用场景：极端恐慌封板后的超跌反弹机会。\n"
                       "风险提示：极高风险策略，可能继续下跌。仅适合有经验的短线交易者。",
        "strategy_func": "cn_stock_strategy_climax_limitdown",
        "groups": [
            {
                "group_name": "跌停条件",
                "params": [
                    {"key": "near_limit_buffer", "label": "跌停容差(%)", "description": "距板块跌停限制的容差，跌幅≥(限制-容差)即视为触及跌停",
                     "type": "number", "value": 0.8, "min": 0, "max": 3, "step": 0.1, "unit": "%"},
                    {"key": "sealed_tol", "label": "封板容差(%)", "description": "收盘价 ≤ 当日最低价×(1+容差) 视为封死跌停",
                     "type": "number", "value": 0.5, "min": 0, "max": 2, "step": 0.1, "unit": "%"},
                ]
            },
            {
                "group_name": "成交量条件",
                "params": [
                    {"key": "vol_ratio", "label": "放量倍数", "description": "当日成交量需达到5日均量的N倍",
                     "type": "number", "value": 2, "min": 1.5, "max": 10, "step": 0.5, "unit": "倍"},
                    {"key": "min_turnover", "label": "最低成交额(亿)", "description": "过滤成交额过小的股票",
                     "type": "number", "value": 2, "min": 0.5, "max": 10, "step": 0.5, "unit": "亿"},
                ]
            },
            {
                "group_name": "窗口设置",
                "params": [
                    {"key": "threshold", "label": "回溯天数", "description": "分析所需的最少历史交易日数",
                     "type": "number", "value": 60, "min": 20, "max": 250, "step": 10, "unit": "天"},
                ]
            }
        ]
    },
    "low_atr": {
        "name": "低ATR成长",
        "description": "低波动率中存在上涨空间的股票。\n\n"
                       "选股条件：\n"
                       "1. 需至少上市交易N天\n"
                       "2. 近期平均日波动 ≤ ATR上限\n"
                       "3. 区间最高价 / 最低价 ≥ 价格振幅比\n\n"
                       "适用场景：寻找波动平稳但悄然上涨的标的。\n"
                       "风险提示：低波动可能因为缺乏关注，流动性可能不足。",
        "strategy_func": "cn_stock_strategy_low_atr",
        "groups": [
            {
                "group_name": "波动条件",
                "params": [
                    {"key": "max_atr", "label": "ATR上限(%)", "description": "期间平均每日绝对涨跌幅上限",
                     "type": "number", "value": 10, "min": 3, "max": 20, "step": 1, "unit": "%"},
                    {"key": "min_price_range", "label": "最低价格振幅", "description": "最高/最低价比值需大于此值",
                     "type": "number", "value": 1.1, "min": 1.02, "max": 1.5, "step": 0.02, "unit": "倍"},
                ]
            },
            {
                "group_name": "窗口设置",
                "params": [
                    {"key": "analysis_days", "label": "分析天数", "description": "近期分析窗口长度",
                     "type": "number", "value": 10, "min": 5, "max": 30, "step": 1, "unit": "天"},
                    {"key": "min_listing_days", "label": "最少上市天数", "description": "股票需至少上市多少天",
                     "type": "number", "value": 250, "min": 60, "max": 500, "step": 10, "unit": "天"},
                ]
            }
        ]
    },
    "indicator_buy": {
        "name": "指标买入信号",
        "description": "「指标买入」榜单：自历史最高深跌（默认回撤≥80%）+ 多指标极度超卖 + 排除 ST/退市"
                       "（可选叠加基本面区间）。\n\n"
                       "筛选逻辑：技术超卖条件全部满足（AND）→ 回撤闸门 → 风险排除 →（可选）基本面过滤。\n\n"
                       "指标含义（均为「低于阈值」触发）：\n"
                       "• RSI(6)：<15 极度超卖\n"
                       "• KDJ-J：<0 极度超卖\n"
                       "• WR(6)：<-90 极度超卖（值域 -100~0）\n"
                       "• CCI：<-150 极度超卖\n"
                       "• MFI：<20 资金流出后的超卖\n\n"
                       "适用场景：深跌标的的左侧抄底/超跌反弹。\n"
                       "风险提示：超卖可能长期持续，须结合基本面与趋势确认，不能机械抄底。\n\n"
                       "注：本参数与「指标设置」页共用底层 indicator_signal 参数，保存后下一次"
                       "定时计算（或点击「立即重算」）生效。",
        "storage_key": "indicator_signal",
        "groups": _sig_groups(
            "买入 · 技术超卖阈值", "买入 · 深跌回撤", "风险排除", "基本面可选过滤（默认关闭）"),
    },
    "indicator_sell": {
        "name": "指标卖出信号",
        "description": "「指标卖出」榜单：现价贴近历史最高（默认≥峰值80%）+ 多指标极度超买 + 排除 ST/退市。\n\n"
                       "筛选逻辑：技术超买条件全部满足（AND）→ 贴近峰值闸门 → 风险排除。\n\n"
                       "指标含义（均为「高于阈值」触发）：\n"
                       "• RSI(6)：>85 极度超买\n"
                       "• KDJ-J：>100 极度超买\n"
                       "• WR(6)：>-10 极度超买（值域 -100~0）\n"
                       "• CCI：>150 极度超买\n"
                       "• MFI：>80 资金流入后的超买\n\n"
                       "适用场景：高位见顶派发/止盈提示。\n"
                       "风险提示：超买不代表立即下跌，强势股可能继续冲高。\n\n"
                       "注：本参数与「指标设置」页共用底层 indicator_signal 参数，保存后下一次"
                       "定时计算（或点击「立即重算」）生效。",
        "storage_key": "indicator_signal",
        "groups": _sig_groups("卖出 · 技术超买阈值", "卖出 · 贴近峰值", "风险排除"),
    },
    "fundamental_buy": {
        "name": "基本面选股",
        "description": "通过市盈率、市净率和ROE筛选基本面优质且估值合理的股票。\n\n"
                       "筛选条件：\n"
                       "1. PE(TTM) > 0 且 ≤ 设定上限（排除亏损和高估值）\n"
                       "2. 市净率 ≤ 设定上限\n"
                       "3. ROE(加权) ≥ 设定下限\n\n"
                       "适用场景：长期价值投资选股。\n"
                       "数据来源：每日股票行情数据。",
        "strategy_func": "fundamental_buy",
        "groups": [
            {
                "group_name": "估值条件",
                "params": [
                    {"key": "pe_max", "label": "PE(TTM)上限", "description": "市盈率上限，排除高估值股票",
                     "type": "number", "value": 20, "min": 5, "max": 100, "step": 5, "unit": "倍"},
                    {"key": "pb_max", "label": "市净率上限", "description": "市净率上限，排除高溢价股票",
                     "type": "number", "value": 10, "min": 1, "max": 30, "step": 1, "unit": "倍"},
                ]
            },
            {
                "group_name": "盈利条件",
                "params": [
                    {"key": "roe_min", "label": "ROE(加权)下限(%)", "description": "加权净资产收益率下限",
                     "type": "number", "value": 15, "min": 5, "max": 40, "step": 1, "unit": "%"},
                ]
            }
        ]
    },
}
