#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全部策略参数定义（K线技术策略 + 指标筛选策略）

每个策略包含:
- name: 中文名
- description: 策略详细说明（包含原理、适用场景、风险提示）
- groups: 参数分组，每组包含多个可调参数
"""

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
        "description": "检测均线多头排列的股票：短、中、长期均线自上而下依次排列，中期趋势向好。\n\n"
                       "选股条件：\n"
                       "1. 最新交易日 MA5 > MA10 > MA20 > MA30 > MA60（多头排列）\n"
                       "2. 统计多头排列已连续出现的天数（bull_days）\n\n"
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
                ]
            }
        ]
    },
    "parking_apron": {
        "name": "停机坪",
        "description": "高位放量涨停后的窄幅整理形态，类似飞机在停机坪暂停准备再次起飞。\n\n"
                       "选股条件：\n"
                       "1. 近N日内有≥涨停阈值的大阳线，且满足放量条件\n"
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
        "description": "股价在MA60附近长期横盘整理后放量突破，形成上升趋势。\n\n"
                       "选股条件：\n"
                       "1. 某日开盘价低于MA60，收盘价高于MA60（穿越）\n"
                       "2. 穿越日满足放量上涨条件\n"
                       "3. 穿越前所有交易日收盘价与MA60偏离在设定范围内\n\n"
                       "适用场景：突破长期整理平台的启动信号。\n"
                       "风险提示：假突破风险，建议等突破确认后再入场。",
        "strategy_func": "cn_stock_strategy_breakthrough_platform",
        "groups": [
            {
                "group_name": "平台参数",
                "params": [
                    {"key": "ma_period", "label": "均线周期", "description": "平台关键均线周期（MA60）",
                     "type": "number", "value": 60, "min": 20, "max": 120, "step": 10, "unit": "天"},
                    {"key": "min_deviation", "label": "最小偏离(%)", "description": "平台期收盘价与MA的最小偏差（负值=允许在MA上方）",
                     "type": "number", "value": -5, "min": -20, "max": 0, "step": 1, "unit": "%"},
                    {"key": "max_deviation", "label": "最大偏离(%)", "description": "平台期收盘价与MA的最大偏差（正值=允许在MA下方）",
                     "type": "number", "value": 20, "min": 5, "max": 50, "step": 5, "unit": "%"},
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
        "description": "检测恐慌性暴跌后的反弹机会。\n\n"
                       "选股条件：\n"
                       "1. 当日跌幅 ≥ 跌停阈值\n"
                       "2. 当日成交额 ≥ 设定金额\n"
                       "3. 当日成交量 ≥ 5日均量的N倍\n\n"
                       "适用场景：极端恐慌后的超跌反弹机会。\n"
                       "风险提示：极高风险策略，可能继续下跌。仅适合有经验的短线交易者。",
        "strategy_func": "cn_stock_strategy_climax_limitdown",
        "groups": [
            {
                "group_name": "跌幅条件",
                "params": [
                    {"key": "limit_down_pct", "label": "跌停阈值(%)", "description": "当日最低跌幅（取绝对值）",
                     "type": "number", "value": 9.5, "min": 5, "max": 20, "step": 0.5, "unit": "%"},
                ]
            },
            {
                "group_name": "成交量条件",
                "params": [
                    {"key": "vol_ratio", "label": "放量倍数", "description": "当日成交量需达到5日均量的N倍",
                     "type": "number", "value": 4, "min": 2, "max": 10, "step": 0.5, "unit": "倍"},
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
        "description": "当多个技术指标同时进入超买区时发出买入信号。\n\n"
                       "筛选逻辑：所有指标条件必须同时满足（AND逻辑）\n\n"
                       "指标说明：\n"
                       "• KDJ：超买区K≥80, D≥70, J≥100\n"
                       "• RSI(6)：超买区 ≥80\n"
                       "• CCI：强势 ≥100\n"
                       "• CR：超强 ≥300\n"
                       "• WR(6)：接近顶部 ≥-20\n"
                       "• VR：活跃 ≥160\n\n"
                       "适用场景：强势股追涨信号，适合短线交易。\n"
                       "风险提示：超买不等于立即下跌，需结合趋势方向。",
        "strategy_func": "indicators_buy",
        "groups": [
            {
                "group_name": "KDJ指标",
                "params": [
                    {"key": "kdjk_min", "label": "KDJ-K下限", "description": "K值超买区阈值",
                     "type": "number", "value": 80, "min": 50, "max": 95, "step": 5, "unit": ""},
                    {"key": "kdjd_min", "label": "KDJ-D下限", "description": "D值超买区阈值",
                     "type": "number", "value": 70, "min": 50, "max": 90, "step": 5, "unit": ""},
                    {"key": "kdjj_min", "label": "KDJ-J下限", "description": "J值超买区阈值",
                     "type": "number", "value": 100, "min": 80, "max": 120, "step": 5, "unit": ""},
                ]
            },
            {
                "group_name": "RSI / CCI",
                "params": [
                    {"key": "rsi6_min", "label": "RSI(6)下限", "description": "6日RSI超买区阈值",
                     "type": "number", "value": 80, "min": 60, "max": 95, "step": 5, "unit": ""},
                    {"key": "cci_min", "label": "CCI下限", "description": "CCI强势区阈值",
                     "type": "number", "value": 100, "min": 50, "max": 200, "step": 10, "unit": ""},
                ]
            },
            {
                "group_name": "CR / WR / VR",
                "params": [
                    {"key": "cr_min", "label": "CR下限", "description": "CR能量指标超强阈值",
                     "type": "number", "value": 300, "min": 100, "max": 500, "step": 20, "unit": ""},
                    {"key": "wr6_min", "label": "WR(6)下限", "description": "威廉指标（值域-100~0，接近0为超买）",
                     "type": "number", "value": -20, "min": -50, "max": 0, "step": 5, "unit": ""},
                    {"key": "vr_min", "label": "VR下限", "description": "成交量比率阈值",
                     "type": "number", "value": 160, "min": 100, "max": 300, "step": 10, "unit": ""},
                ]
            }
        ]
    },
    "indicator_sell": {
        "name": "指标卖出信号",
        "description": "当多个技术指标同时进入超卖区时发出卖出信号。\n\n"
                       "筛选逻辑：所有指标条件必须同时满足（AND逻辑）\n\n"
                       "指标说明：\n"
                       "• KDJ：超卖区K<20, D<30, J<10\n"
                       "• RSI(6)：超卖区 <20\n"
                       "• CCI：弱势 <-100\n"
                       "• CR：超弱 <40\n"
                       "• WR(6)：接近底部 <-80\n"
                       "• VR：低迷 <40\n\n"
                       "适用场景：超跌反弹信号，或确认底部区域。\n"
                       "风险提示：超卖可能持续很长时间，不能机械买入。",
        "strategy_func": "indicators_sell",
        "groups": [
            {
                "group_name": "KDJ指标",
                "params": [
                    {"key": "kdjk_max", "label": "KDJ-K上限", "description": "K值超卖区阈值",
                     "type": "number", "value": 20, "min": 5, "max": 40, "step": 5, "unit": ""},
                    {"key": "kdjd_max", "label": "KDJ-D上限", "description": "D值超卖区阈值",
                     "type": "number", "value": 30, "min": 10, "max": 50, "step": 5, "unit": ""},
                    {"key": "kdjj_max", "label": "KDJ-J上限", "description": "J值超卖区阈值",
                     "type": "number", "value": 10, "min": -10, "max": 30, "step": 5, "unit": ""},
                ]
            },
            {
                "group_name": "RSI / CCI",
                "params": [
                    {"key": "rsi6_max", "label": "RSI(6)上限", "description": "6日RSI超卖区阈值",
                     "type": "number", "value": 20, "min": 5, "max": 40, "step": 5, "unit": ""},
                    {"key": "cci_max", "label": "CCI上限", "description": "CCI弱势区阈值",
                     "type": "number", "value": -100, "min": -300, "max": -50, "step": 10, "unit": ""},
                ]
            },
            {
                "group_name": "CR / WR / VR",
                "params": [
                    {"key": "cr_max", "label": "CR上限", "description": "CR能量指标超弱阈值",
                     "type": "number", "value": 40, "min": 10, "max": 100, "step": 5, "unit": ""},
                    {"key": "wr6_max", "label": "WR(6)上限", "description": "威廉指标超卖阈值",
                     "type": "number", "value": -80, "min": -100, "max": -50, "step": 5, "unit": ""},
                    {"key": "vr_max", "label": "VR上限", "description": "成交量比率阈值",
                     "type": "number", "value": 40, "min": 10, "max": 80, "step": 5, "unit": ""},
                ]
            }
        ]
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
