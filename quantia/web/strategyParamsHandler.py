#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略参数管理 Handler

提供策略参数的查询、保存、重置和基于参数的动态筛选功能。
参数持久化到 MySQL 数据库表 cn_strategy_params。
"""

import json
import logging
from abc import ABC
import quantia.web.base as webBase
import quantia.lib.database as mdb
from quantia.lib.query_cache import filter_result_cache
from quantia.web.strategy_params_config import TECHNICAL_STRATEGY_PARAMS

__author__ = 'Quantia'
__date__ = '2026/02/14'


# ========== 默认策略参数定义 ==========

DEFAULT_STRATEGY_PARAMS = {
    "gpt_value": {
        "name": "GPT综合选股",
        "description": "基于基本面的多维度选股策略，通过财务安全、盈利能力、成长质量和估值四层过滤筛选优质股票。",
        "groups": [
            {
                "group_name": "财务安全过滤",
                "group_description": "排除高风险地雷股，确保财务基本安全",
                "params": [
                    {
                        "key": "debt_asset_ratio_max",
                        "label": "资产负债率上限(%)",
                        "description": "排除高财务杠杆的公司。银行/地产行业通常较高，可适当放宽。",
                        "type": "number",
                        "value": 60,
                        "min": 20,
                        "max": 90,
                        "step": 5,
                        "unit": "%",
                        "field": "debt_asset_ratio"
                    },
                    {
                        "key": "per_netcash_operate_min",
                        "label": "每股经营现金流下限",
                        "description": "确保公司具备造血能力，经营活动产生正现金流。",
                        "type": "number",
                        "value": 0,
                        "min": -5,
                        "max": 10,
                        "step": 0.5,
                        "unit": "元",
                        "field": "per_netcash_operate"
                    },
                    {
                        "key": "current_ratio_min",
                        "label": "流动比率下限",
                        "description": "衡量短期偿债能力。>=1.0表示流动资产大于流动负债，偿债有保障。",
                        "type": "number",
                        "value": 1.0,
                        "min": 0.5,
                        "max": 3.0,
                        "step": 0.1,
                        "unit": "",
                        "field": "current_ratio"
                    },
                    {
                        "key": "speed_ratio_min",
                        "label": "速动比率下限",
                        "description": "扣除存货后的快速偿债能力。制造业可适当降低至0.5。",
                        "type": "number",
                        "value": 0.7,
                        "min": 0.3,
                        "max": 2.0,
                        "step": 0.1,
                        "unit": "",
                        "field": "speed_ratio"
                    }
                ]
            },
            {
                "group_name": "盈利能力筛选",
                "group_description": "选出ROE高、利润率好的优质公司",
                "params": [
                    {
                        "key": "roe_weight_min",
                        "label": "ROE(加权)下限(%)",
                        "description": "净资产收益率反映股东回报。>=15%为优质企业标准，可放宽至10%扩大选股范围。",
                        "type": "number",
                        "value": 15,
                        "min": 5,
                        "max": 40,
                        "step": 1,
                        "unit": "%",
                        "field": "roe_weight"
                    },
                    {
                        "key": "sale_gpr_min",
                        "label": "毛利率下限(%)",
                        "description": "反映产品定价权和竞争优势。制造业通常较低(可设20%)，消费品/软件行业可设更高。",
                        "type": "number",
                        "value": 25,
                        "min": 10,
                        "max": 80,
                        "step": 5,
                        "unit": "%",
                        "field": "sale_gpr"
                    },
                    {
                        "key": "sale_npr_min",
                        "label": "净利率下限(%)",
                        "description": "衡量成本控制能力和最终盈利水平。工业企业>=8%已属优秀。",
                        "type": "number",
                        "value": 8,
                        "min": 3,
                        "max": 50,
                        "step": 1,
                        "unit": "%",
                        "field": "sale_npr"
                    },
                    {
                        "key": "jroa_min",
                        "label": "ROA下限(%)",
                        "description": "总资产净利率，衡量资产使用效率。资产较重的行业（制造业）可适当降低。",
                        "type": "number",
                        "value": 4,
                        "min": 1,
                        "max": 20,
                        "step": 1,
                        "unit": "%",
                        "field": "jroa"
                    }
                ]
            },
            {
                "group_name": "成长质量筛选",
                "group_description": "确保公司具备可持续增长能力",
                "params": [
                    {
                        "key": "income_growthrate_3y_min",
                        "label": "营收3年CAGR下限(%)",
                        "description": "营业收入3年复合增长率。>8%表明业务持续扩张，蓝筹股可放宽至5%。",
                        "type": "number",
                        "value": 8,
                        "min": 0,
                        "max": 50,
                        "step": 1,
                        "unit": "%",
                        "field": "income_growthrate_3y"
                    },
                    {
                        "key": "netprofit_growthrate_3y_min",
                        "label": "净利润3年CAGR下限(%)",
                        "description": "净利润3年复合增长率。>8%表明盈利能力持续增强。",
                        "type": "number",
                        "value": 8,
                        "min": 0,
                        "max": 50,
                        "step": 1,
                        "unit": "%",
                        "field": "netprofit_growthrate_3y"
                    },
                    {
                        "key": "deduct_netprofit_growthrate_min",
                        "label": "扣非净利润增长率下限(%)",
                        "description": "扣除非经常性损益后的净利润增长率。>0%确认主业盈利在增长，排除靠一次性收益粉饰业绩的公司。",
                        "type": "number",
                        "value": 0,
                        "min": -20,
                        "max": 50,
                        "step": 1,
                        "unit": "%",
                        "field": "deduct_netprofit_growthrate"
                    }
                ]
            },
            {
                "group_name": "估值约束",
                "group_description": "在合理价格买入好公司",
                "params": [
                    {
                        "key": "pe_min",
                        "label": "PE(TTM)下限",
                        "description": "排除亏损股(PE<=0)。设为0表示PE必须大于0。",
                        "type": "number",
                        "value": 0,
                        "min": 0,
                        "max": 10,
                        "step": 1,
                        "unit": "倍",
                        "field": "pe9"
                    },
                    {
                        "key": "pe_max",
                        "label": "PE(TTM)上限",
                        "description": "排除泡沫股。50为默认值，成长股可放宽至60-80，价值股可收紧至30。",
                        "type": "number",
                        "value": 50,
                        "min": 15,
                        "max": 200,
                        "step": 5,
                        "unit": "倍",
                        "field": "pe9"
                    },
                    {
                        "key": "pbnewmrq_max",
                        "label": "PB(MRQ)上限",
                        "description": "市净率上限，排除极端高估值股票。一般<=10为合理范围。",
                        "type": "number",
                        "value": 10,
                        "min": 2,
                        "max": 50,
                        "step": 1,
                        "unit": "倍",
                        "field": "pbnewmrq"
                    }
                ]
            }
        ]
    },
    "moat_scoring": {
        "name": "护城河评分模型",
        "description": "量化评估公司护城河强度的评分模型，用于AI分析的阈值和权重配置。",
        "groups": [
            {
                "group_name": "盈利能力权重",
                "group_description": "评估公司盈利质量的指标权重配置",
                "params": [
                    {
                        "key": "roe_weight",
                        "label": "ROE权重",
                        "description": "净资产收益率在评分中的权重。ROE是衡量股东回报最核心的指标。",
                        "type": "number",
                        "value": 0.15,
                        "min": 0.05,
                        "max": 0.30,
                        "step": 0.01,
                        "unit": ""
                    },
                    {
                        "key": "sale_gpr_weight",
                        "label": "毛利率权重",
                        "description": "毛利率在评分中的权重。高毛利率通常意味着定价权。",
                        "type": "number",
                        "value": 0.10,
                        "min": 0.05,
                        "max": 0.20,
                        "step": 0.01,
                        "unit": ""
                    },
                    {
                        "key": "sale_npr_weight",
                        "label": "净利率权重",
                        "description": "净利率在评分中的权重。反映公司综合盈利能力。",
                        "type": "number",
                        "value": 0.10,
                        "min": 0.05,
                        "max": 0.20,
                        "step": 0.01,
                        "unit": ""
                    }
                ]
            },
            {
                "group_name": "成长能力权重",
                "group_description": "评估公司成长质量的指标权重配置",
                "params": [
                    {
                        "key": "income_growth_weight",
                        "label": "营收增长权重",
                        "description": "营收3年CAGR在评分中的权重。",
                        "type": "number",
                        "value": 0.10,
                        "min": 0.05,
                        "max": 0.20,
                        "step": 0.01,
                        "unit": ""
                    },
                    {
                        "key": "profit_growth_weight",
                        "label": "净利润增长权重",
                        "description": "净利润3年CAGR在评分中的权重。",
                        "type": "number",
                        "value": 0.10,
                        "min": 0.05,
                        "max": 0.20,
                        "step": 0.01,
                        "unit": ""
                    }
                ]
            },
            {
                "group_name": "评级阈值",
                "group_description": "综合评分对应的投资评级分数线",
                "params": [
                    {
                        "key": "grade_a_threshold",
                        "label": "A级(强烈推荐)分数线",
                        "description": "总分达到此值评为A级，建议核心持仓。",
                        "type": "number",
                        "value": 80,
                        "min": 70,
                        "max": 95,
                        "step": 5,
                        "unit": "分"
                    },
                    {
                        "key": "grade_b_threshold",
                        "label": "B级(推荐关注)分数线",
                        "description": "总分达到此值评为B级，建议标准仓位。",
                        "type": "number",
                        "value": 65,
                        "min": 50,
                        "max": 80,
                        "step": 5,
                        "unit": "分"
                    },
                    {
                        "key": "grade_c_threshold",
                        "label": "C级(谨慎持有)分数线",
                        "description": "总分达到此值评为C级，建议降低仓位。低于此值为D级，不建议投资。",
                        "type": "number",
                        "value": 50,
                        "min": 30,
                        "max": 65,
                        "step": 5,
                        "unit": "分"
                    }
                ]
            },
            {
                "group_name": "综合评分权重",
                "group_description": "量化评分与定性评分的配比",
                "params": [
                    {
                        "key": "quantitative_weight",
                        "label": "量化评分权重",
                        "description": "量化指标（财务数据）在最终得分中的占比。定性权重自动为 1 - 此值。",
                        "type": "number",
                        "value": 0.60,
                        "min": 0.30,
                        "max": 0.90,
                        "step": 0.05,
                        "unit": ""
                    }
                ]
            }
        ]
    },
    "ai_model": {
        "name": "AI模型配置",
        "description": "配置AI大语言模型的接口参数,用于护城河分析和智能选股。支持OpenAI、DeepSeek等兼容API。",
        "groups": [
            {
                "group_name": "API接口配置",
                "group_description": "大语言模型的接口地址和认证信息",
                "params": [
                    {
                        "key": "api_base",
                        "label": "API基础地址",
                        "description": "AI服务的API地址。OpenAI: https://api.openai.com/v1,DeepSeek: https://api.deepseek.com/v1,本地: http://localhost:11434/v1",
                        "type": "text",
                        "value": "https://api.openai.com/v1"
                    },
                    {
                        "key": "api_key",
                        "label": "API密钥",
                        "description": "AI服务的认证密钥。请从对应平台获取。此密钥会加密存储。",
                        "type": "password",
                        "value": ""
                    },
                    {
                        "key": "model",
                        "label": "模型名称",
                        "description": "使用的模型标识。如 gpt-4、gpt-4o、gpt-3.5-turbo、deepseek-chat、qwen-plus 等。",
                        "type": "select",
                        "value": "gpt-4",
                        "options": [
                            {"label": "GPT-4", "value": "gpt-4"},
                            {"label": "GPT-4o", "value": "gpt-4o"},
                            {"label": "GPT-4o-mini", "value": "gpt-4o-mini"},
                            {"label": "GPT-3.5 Turbo", "value": "gpt-3.5-turbo"},
                            {"label": "DeepSeek Chat", "value": "deepseek-chat"},
                            {"label": "DeepSeek Reasoner", "value": "deepseek-reasoner"},
                            {"label": "通义千问 Plus", "value": "qwen-plus"},
                            {"label": "通义千问 Max", "value": "qwen-max"},
                            {"label": "自定义", "value": "custom"}
                        ]
                    },
                    {
                        "key": "custom_model",
                        "label": "自定义模型名",
                        "description": "当模型选择'自定义'时，在此填写实际的模型标识符。",
                        "type": "text",
                        "value": ""
                    }
                ]
            },
            {
                "group_name": "模型参数",
                "group_description": "调整AI生成的行为参数",
                "params": [
                    {
                        "key": "temperature",
                        "label": "温度(Temperature)",
                        "description": "控制生成随机性。0=完全确定性，1=最大随机性。分析任务建议0.1-0.4。",
                        "type": "number",
                        "value": 0.3,
                        "min": 0,
                        "max": 1.0,
                        "step": 0.1,
                        "unit": ""
                    },
                    {
                        "key": "max_tokens",
                        "label": "最大Token数",
                        "description": "AI单次回复的最大长度。分析报告建议2000-4000。过小会导致输出截断。",
                        "type": "number",
                        "value": 2000,
                        "min": 500,
                        "max": 8000,
                        "step": 500,
                        "unit": "tokens"
                    },
                    {
                        "key": "timeout",
                        "label": "请求超时时间",
                        "description": "API请求超时时间。网络较慢时可增大。",
                        "type": "number",
                        "value": 60,
                        "min": 10,
                        "max": 300,
                        "step": 10,
                        "unit": "秒"
                    }
                ]
            }
        ]
    }
}

# 合并技术策略参数定义
DEFAULT_STRATEGY_PARAMS.update(TECHNICAL_STRATEGY_PARAMS)

# 合并「指标买卖信号」参数定义（前端「指标设置」页复用通用 params 接口）
from quantia.web.indicator_params_config import INDICATOR_SIGNAL_PARAMS
DEFAULT_STRATEGY_PARAMS.update(INDICATOR_SIGNAL_PARAMS)


# ========== 数据库操作 ==========

_params_table_ready = False
_history_table_ready = False


def _ensure_params_table():
    """确保参数存储表存在"""
    global _params_table_ready
    if _params_table_ready:
        return
    try:
        if not mdb.checkTableIsExist('cn_strategy_params'):
            mdb.executeSql("""
                CREATE TABLE IF NOT EXISTS `cn_strategy_params` (
                    `strategy_key` VARCHAR(50) NOT NULL COMMENT '策略标识',
                    `param_key` VARCHAR(100) NOT NULL COMMENT '参数标识',
                    `param_value` TEXT COMMENT '参数值(JSON)',
                    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    PRIMARY KEY (`strategy_key`, `param_key`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='策略参数配置表';
            """)
            logging.info("已创建策略参数表 cn_strategy_params")
        _params_table_ready = True
    except Exception as e:
        mdb._invalidate_shared_conn()
        logging.error(f"创建策略参数表异常", exc_info=True)


def _ensure_history_table():
    """确保参数历史表存在"""
    global _history_table_ready
    if _history_table_ready:
        return
    try:
        if not mdb.checkTableIsExist('cn_strategy_params_history'):
            mdb.executeSql("""
                CREATE TABLE IF NOT EXISTS `cn_strategy_params_history` (
                    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
                    `strategy_key` VARCHAR(50) NOT NULL COMMENT '策略标识',
                    `version` INT NOT NULL COMMENT '版本号(自增)',
                    `params_snapshot` JSON COMMENT '完整参数快照',
                    `changed_keys` TEXT COMMENT '本次变更的参数key列表(JSON数组)',
                    `source` VARCHAR(20) DEFAULT 'manual' COMMENT '来源: manual/reset/backtest',
                    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
                    INDEX `idx_strategy_version` (`strategy_key`, `version` DESC),
                    INDEX `idx_strategy_created` (`strategy_key`, `created_at` DESC)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='策略参数变更历史';
            """)
            logging.info("已创建策略参数历史表 cn_strategy_params_history")
        _history_table_ready = True
    except Exception as e:
        mdb._invalidate_shared_conn()
        logging.error("创建策略参数历史表异常", exc_info=True)


def _load_saved_params(strategy_key):
    """从数据库加载已保存的参数"""
    try:
        result = mdb.executeSqlFetch(
            "SELECT `param_key`, `param_value` FROM `cn_strategy_params` WHERE `strategy_key` = %s",
            (strategy_key,)
        )
        if result:
            parsed = {}
            for row in result:
                raw = row[1]
                if raw is None:
                    continue
                # 已是 Python 标量/容器（驱动或历史写入未经 json.dumps）→ 直接保留
                if isinstance(raw, (int, float, bool, dict, list)):
                    parsed[row[0]] = raw
                    continue
                try:
                    parsed[row[0]] = json.loads(raw)
                except (TypeError, ValueError):
                    logging.warning(
                        "策略参数 %s.%s 反序列化失败，跳过该值", strategy_key, row[0])
            return parsed
    except Exception as e:
        logging.error(f"加载策略参数异常", exc_info=True)
    return {}


def _save_param(strategy_key, param_key, param_value):
    """保存单个参数到数据库"""
    try:
        value_json = json.dumps(param_value, ensure_ascii=False)
        mdb.executeSql(
            """INSERT INTO `cn_strategy_params` (`strategy_key`, `param_key`, `param_value`)
               VALUES (%s, %s, %s)
               ON DUPLICATE KEY UPDATE `param_value` = %s, `updated_at` = NOW()""",
            (strategy_key, param_key, value_json, value_json)
        )
        return True
    except Exception as e:
        logging.error(f"保存策略参数异常", exc_info=True)
        return False


def _delete_strategy_params(strategy_key):
    """删除某个策略的所有自定义参数（恢复默认）"""
    try:
        mdb.executeSql(
            "DELETE FROM `cn_strategy_params` WHERE `strategy_key` = %s",
            (strategy_key,)
        )
        return True
    except Exception as e:
        logging.error(f"删除策略参数异常", exc_info=True)
        return False


def _get_next_version(strategy_key):
    """获取策略下一个版本号"""
    try:
        row = mdb.executeSqlFetch(
            "SELECT MAX(`version`) FROM `cn_strategy_params_history` WHERE `strategy_key` = %s",
            (strategy_key,))
        if row and row[0][0] is not None:
            return int(row[0][0]) + 1
    except Exception:
        pass
    return 1


def _record_params_history(strategy_key, params_snapshot, changed_keys, source='manual'):
    """记录参数变更历史"""
    try:
        _ensure_history_table()
        version = _get_next_version(strategy_key)
        snapshot_json = json.dumps(params_snapshot, ensure_ascii=False)
        changed_json = json.dumps(changed_keys, ensure_ascii=False)
        mdb.executeSql(
            """INSERT INTO `cn_strategy_params_history`
               (`strategy_key`, `version`, `params_snapshot`, `changed_keys`, `source`)
               VALUES (%s, %s, %s, %s, %s)""",
            (strategy_key, version, snapshot_json, changed_json, source))
        return version
    except Exception as e:
        logging.error("记录参数历史异常", exc_info=True)
        return None


def _get_params_history(strategy_key, limit=50):
    """查询参数变更历史"""
    try:
        _ensure_history_table()
        rows = mdb.executeSqlFetch(
            """SELECT `id`, `version`, `params_snapshot`, `changed_keys`, `source`, `created_at`
               FROM `cn_strategy_params_history`
               WHERE `strategy_key` = %s
               ORDER BY `version` DESC LIMIT %s""",
            (strategy_key, limit))
        if not rows:
            return []
        result = []
        for r in rows:
            result.append({
                'id': r[0],
                'version': r[1],
                'params_snapshot': json.loads(r[2]) if r[2] else {},
                'changed_keys': json.loads(r[3]) if r[3] else [],
                'source': r[4],
                'created_at': r[5].strftime('%Y-%m-%d %H:%M:%S') if r[5] else '',
            })
        return result
    except Exception as e:
        logging.error("查询参数历史异常", exc_info=True)
        return []


def get_strategy_params(strategy_key):
    """
    获取策略参数（合并默认值和用户自定义值）
    
    Returns:
        dict: 完整的策略参数定义，value已替换为用户设定值
    """
    import copy
    if strategy_key not in DEFAULT_STRATEGY_PARAMS:
        return None
    
    _ensure_params_table()
    
    params_def = copy.deepcopy(DEFAULT_STRATEGY_PARAMS[strategy_key])
    saved = _load_saved_params(strategy_key)
    
    # 将保存的值合并到参数定义中
    for group in params_def.get('groups', []):
        for param in group.get('params', []):
            if param['key'] in saved:
                param['value'] = saved[param['key']]
                param['is_custom'] = True
            else:
                param['is_custom'] = False
    
    return params_def


def get_gpt_filter_values():
    """
    获取 GPT综合选股 的筛选参数值（用于实际筛选）
    
    Returns:
        dict: {param_key: value}
    """
    _ensure_params_table()
    saved = _load_saved_params("gpt_value")
    
    # 构建最终值：优先使用保存值，否则用默认值
    result = {}
    for group in DEFAULT_STRATEGY_PARAMS["gpt_value"]["groups"]:
        for param in group["params"]:
            key = param["key"]
            result[key] = saved.get(key, param["value"])
    
    return result


# ========== Handler ==========

class GetStrategyParamsHandler(webBase.BaseHandler, ABC):
    """获取策略参数配置"""
    
    def get(self):
        self.set_header('Content-Type', 'application/json;charset=UTF-8')
        strategy_key = self.get_argument("strategy", default=None, strip=True)
        
        if strategy_key is None:
            # 返回所有可配置的策略列表
            strategies = []
            for key, val in DEFAULT_STRATEGY_PARAMS.items():
                strategies.append({
                    "key": key,
                    "name": val["name"],
                    "description": val["description"]
                })
            self.write(json.dumps({"strategies": strategies}, ensure_ascii=False))
            return
        
        params = get_strategy_params(strategy_key)
        if params is None:
            self.set_status(404)
            self.write(json.dumps({"error": f"未知策略: {strategy_key}"}, ensure_ascii=False))
            return
        
        # 安全处理：对 password 类型的参数值进行脱敏，防止 API 密钥泄露
        for group in params.get('groups', []):
            for param in group.get('params', []):
                if param.get('type') == 'password' and param.get('value'):
                    val = str(param['value'])
                    if len(val) > 8:
                        param['value'] = val[:4] + '*' * (len(val) - 8) + val[-4:]
                    elif len(val) > 0:
                        param['value'] = '****'
        
        self.write(json.dumps(params, ensure_ascii=False))


class SaveStrategyParamsHandler(webBase.BaseHandler, ABC):
    """保存策略参数"""
    
    def post(self):
        self.set_header('Content-Type', 'application/json;charset=UTF-8')
        
        try:
            body = json.loads(self.request.body.decode('utf-8'))
        except Exception:
            self.set_status(400)
            self.write(json.dumps({"error": "请求体JSON解析失败"}, ensure_ascii=False))
            return
        
        strategy_key = body.get("strategy")
        params = body.get("params", {})
        
        if not strategy_key or strategy_key not in DEFAULT_STRATEGY_PARAMS:
            self.set_status(400)
            self.write(json.dumps({"error": f"无效的策略标识: {strategy_key}"}, ensure_ascii=False))
            return
        
        _ensure_params_table()
        
        # 保存前记录旧值，用于检测实际变更
        old_params = _load_saved_params(strategy_key)
        
        saved_count = 0
        changed_keys = []
        for key, value in params.items():
            old_val = old_params.get(key)
            if _save_param(strategy_key, key, value):
                saved_count += 1
                if old_val != value:
                    changed_keys.append(key)
        
        # 记录参数变更历史（仅在有实际变更时记录）
        if changed_keys:
            full_snapshot = _load_saved_params(strategy_key)
            _record_params_history(strategy_key, full_snapshot, changed_keys, source='manual')
        
        # 参数变更后清除筛选结果缓存
        filter_result_cache.invalidate()
        
        self.write(json.dumps({
            "success": True,
            "message": f"已保存 {saved_count} 个参数",
            "saved_count": saved_count
        }, ensure_ascii=False))


class ResetStrategyParamsHandler(webBase.BaseHandler, ABC):
    """重置策略参数为默认值"""
    
    def post(self):
        self.set_header('Content-Type', 'application/json;charset=UTF-8')
        
        try:
            body = json.loads(self.request.body.decode('utf-8'))
        except Exception:
            self.set_status(400)
            self.write(json.dumps({"error": "请求体JSON解析失败"}, ensure_ascii=False))
            return
        
        strategy_key = body.get("strategy")
        
        if not strategy_key or strategy_key not in DEFAULT_STRATEGY_PARAMS:
            self.set_status(400)
            self.write(json.dumps({"error": f"无效的策略标识: {strategy_key}"}, ensure_ascii=False))
            return
        
        _ensure_params_table()
        
        # 记录重置前的参数快照
        old_params = _load_saved_params(strategy_key)
        
        if _delete_strategy_params(strategy_key):
            # 记录重置操作到历史（快照记录默认值）
            if old_params:
                _record_params_history(strategy_key, {}, list(old_params.keys()), source='reset')
            # 参数重置后清除筛选结果缓存
            filter_result_cache.invalidate()
            self.write(json.dumps({
                "success": True,
                "message": f"策略 {strategy_key} 已重置为默认值"
            }, ensure_ascii=False))
        else:
            self.set_status(500)
            self.write(json.dumps({"error": "重置失败"}, ensure_ascii=False))


class FilterStocksHandler(webBase.BaseHandler, ABC):
    """根据当前策略参数动态筛选股票"""
    
    def get(self):
        self.set_header('Content-Type', 'application/json;charset=UTF-8')
        strategy_key = self.get_argument("strategy", default="gpt_value", strip=True)
        date = self.get_argument("date", default=None, strip=True)
        page = self.get_argument("page", default=None, strip=True)
        page_size = self.get_argument("page_size", default=None, strip=True)
        
        if strategy_key == "gpt_value":
            self._filter_gpt_value(date, page, page_size)
        elif strategy_key == "fundamental_buy":
            self._filter_fundamental(date, page, page_size)
        elif strategy_key in ("indicator_buy", "indicator_sell"):
            self._filter_indicator(strategy_key, date, page, page_size)
        elif strategy_key in TECHNICAL_STRATEGY_PARAMS and 'strategy_func' in TECHNICAL_STRATEGY_PARAMS[strategy_key]:
            self._filter_kline_strategy(strategy_key, date, page, page_size)
        else:
            self.set_status(400)
            self.write(json.dumps({"error": f"策略 {strategy_key} 暂不支持动态筛选"}, ensure_ascii=False))
    
    def _filter_gpt_value(self, date, page=None, page_size=None):
        """使用用户自定义参数筛选GPT综合选股"""
        params = get_gpt_filter_values()
        
        # 分页参数处理
        use_pagination = page is not None and page_size is not None
        limit_clause = ""
        if use_pagination:
            try:
                page_int = max(1, int(page))
                page_size_int = max(1, min(500, int(page_size)))
                offset = (page_int - 1) * page_size_int
                limit_clause = f" LIMIT {page_size_int} OFFSET {offset}"
            except (ValueError, TypeError):
                use_pagination = False
        
        # 构建SQL WHERE条件
        conditions = []
        sql_params = []
        
        if date:
            conditions.append("`date` = %s")
            sql_params.append(date)
        
        # === 第一层：财务安全过滤 ===
        # 资产负债率 < 上限
        conditions.append("`debt_asset_ratio` < %s")
        sql_params.append(params["debt_asset_ratio_max"])
        
        # 每股经营现金流 > 下限
        conditions.append("`per_netcash_operate` > %s")
        sql_params.append(params["per_netcash_operate_min"])
        
        # 流动比率 >= 下限（允许NULL，不因缺失而排除）
        if "current_ratio_min" in params:
            conditions.append("(`current_ratio` IS NULL OR `current_ratio` >= %s)")
            sql_params.append(params["current_ratio_min"])
        
        # 速动比率 >= 下限（允许NULL）
        if "speed_ratio_min" in params:
            conditions.append("(`speed_ratio` IS NULL OR `speed_ratio` >= %s)")
            sql_params.append(params["speed_ratio_min"])
        
        # === 第二层：盈利能力筛选 ===
        # ROE >= 下限
        conditions.append("`roe_weight` >= %s")
        sql_params.append(params["roe_weight_min"])
        
        # 毛利率 >= 下限
        conditions.append("`sale_gpr` >= %s")
        sql_params.append(params["sale_gpr_min"])
        
        # 净利率 >= 下限
        conditions.append("`sale_npr` >= %s")
        sql_params.append(params["sale_npr_min"])
        
        # ROA >= 下限（允许NULL）
        if "jroa_min" in params:
            conditions.append("(`jroa` IS NULL OR `jroa` >= %s)")
            sql_params.append(params["jroa_min"])
        
        # === 第三层：成长质量筛选 ===
        # 营收3年CAGR > 下限
        conditions.append("`income_growthrate_3y` > %s")
        sql_params.append(params["income_growthrate_3y_min"])
        
        # 净利润3年CAGR > 下限
        conditions.append("`netprofit_growthrate_3y` > %s")
        sql_params.append(params["netprofit_growthrate_3y_min"])
        
        # 扣非净利润增长率 > 下限（允许NULL）
        if "deduct_netprofit_growthrate_min" in params:
            conditions.append("(`deduct_netprofit_growthrate` IS NULL OR `deduct_netprofit_growthrate` > %s)")
            sql_params.append(params["deduct_netprofit_growthrate_min"])
        
        # === 第五层：估值约束 ===
        # PE 范围
        conditions.append("`pe9` > %s")
        sql_params.append(params["pe_min"])
        
        conditions.append("`pe9` <= %s")
        sql_params.append(params["pe_max"])
        
        # PB 上限（允许NULL）
        if "pbnewmrq_max" in params:
            conditions.append("(`pbnewmrq` IS NULL OR `pbnewmrq` <= %s)")
            sql_params.append(params["pbnewmrq_max"])
        
        # 排除空值（核心字段必须有值）
        not_null_fields = [
            'debt_asset_ratio', 'per_netcash_operate', 'roe_weight',
            'sale_gpr', 'sale_npr', 'income_growthrate_3y',
            'netprofit_growthrate_3y', 'pe9'
        ]
        for field in not_null_fields:
            conditions.append(f"`{field}` IS NOT NULL")
        
        where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
        
        count_sql = f"SELECT COUNT(*) AS cnt FROM `cn_stock_selection`{where_clause}"
        data_sql = f"""SELECT `date`, `code`, `name`, `pe9`, `pbnewmrq`, `roe_weight`, `sale_gpr`, 
                         `sale_npr`, `jroa`, `income_growthrate_3y`, `netprofit_growthrate_3y`, 
                         `deduct_netprofit_growthrate`, `debt_asset_ratio`, `per_netcash_operate`,
                         `current_ratio`, `speed_ratio`
                  FROM `cn_stock_selection`{where_clause}
                  ORDER BY `roe_weight` DESC{limit_clause}"""
        
        try:
            cache_params = tuple(sql_params)
            
            # 尝试从缓存获取总数
            hit, cached_total = filter_result_cache.get(count_sql, cache_params)
            if hit:
                total = cached_total
            else:
                total_result = self.db.query(count_sql, *sql_params)
                total = total_result[0]["cnt"] if total_result else 0
                filter_result_cache.put(count_sql, cache_params, total)
            
            # 尝试从缓存获取数据
            hit, cached_data = filter_result_cache.get(data_sql, cache_params)
            if hit:
                data = cached_data
            else:
                data = self.db.query(data_sql, *sql_params)
                filter_result_cache.put(data_sql, cache_params, data)
            
            # 列定义
            columns = [
                {"value": "date", "caption": "日期", "width": 110},
                {"value": "code", "caption": "代码", "width": 90},
                {"value": "name", "caption": "名称", "width": 100},
                {"value": "pe9", "caption": "PE(TTM)", "width": 80},
                {"value": "roe_weight", "caption": "ROE(%)", "width": 80},
                {"value": "sale_gpr", "caption": "毛利率(%)", "width": 90},
                {"value": "sale_npr", "caption": "净利率(%)", "width": 90},
                {"value": "income_growthrate_3y", "caption": "营收3年CAGR(%)", "width": 120},
                {"value": "netprofit_growthrate_3y", "caption": "净利润3年CAGR(%)", "width": 130},
                {"value": "debt_asset_ratio", "caption": "资产负债率(%)", "width": 110},
                {"value": "per_netcash_operate", "caption": "每股现金流", "width": 100}
            ]
            
            # 格式化数据
            from quantia.web.dataTableHandler import MyEncoder
            result = json.loads(json.dumps({
                "columns": columns,
                "data": data if data else [],
                "total": total,
                "params_used": params
            }, cls=MyEncoder))
            
            self.write(json.dumps(result, ensure_ascii=False))
            
        except Exception as e:
            error_msg = str(e)
            if "doesn't exist" in error_msg:
                self.write(json.dumps({
                    "columns": [],
                    "data": [],
                    "total": 0,
                    "params_used": params,
                    "warning": "cn_stock_selection 表尚未创建，请先执行选股作业"
                }, ensure_ascii=False))
            else:
                logging.error(f"FilterStocksHandler 查询异常", exc_info=True)
                self.set_status(500)
                self.write(json.dumps({"error": f"查询异常: {error_msg}"}, ensure_ascii=False))

    def _filter_fundamental(self, date, page, page_size):
        """基本面选股筛选"""
        params = self._get_strategy_values("fundamental_buy")
        
        limit_clause = self._build_limit(page, page_size)
        conditions, sql_params = [], []
        if date:
            conditions.append("`date` = %s")
            sql_params.append(date)
        
        conditions.append("`pe9` > 0")
        conditions.append("`pe9` <= %s")
        sql_params.append(params.get("pe_max", 20))
        conditions.append("`pbnewmrq` <= %s")
        sql_params.append(params.get("pb_max", 10))
        conditions.append("`roe_weight` >= %s")
        sql_params.append(params.get("roe_min", 15))
        
        where = " WHERE " + " AND ".join(conditions)
        table = "cn_stock_spot"
        
        self._exec_filter_query(table, where, sql_params, limit_clause, params,
            "`date`, `code`, `name`, `new_price`, `change_rate`, `pe9`, `pbnewmrq`, `roe_weight`",
            [{"value": "date", "caption": "日期", "width": 110},
             {"value": "code", "caption": "代码", "width": 90},
             {"value": "name", "caption": "名称", "width": 100},
             {"value": "new_price", "caption": "最新价", "width": 80},
             {"value": "change_rate", "caption": "涨跌幅(%)", "width": 90},
             {"value": "pe9", "caption": "PE(TTM)", "width": 80},
             {"value": "pbnewmrq", "caption": "市净率", "width": 80},
             {"value": "roe_weight", "caption": "ROE(%)", "width": 80}],
            " ORDER BY `roe_weight` DESC")
    
    def _filter_indicator(self, strategy_key, date, page, page_size):
        """指标买入/卖出信号筛选"""
        params = self._get_strategy_values(strategy_key)
        
        limit_clause = self._build_limit(page, page_size)
        conditions, sql_params = [], []
        
        table = "cn_stock_indicators"
        if not mdb.checkTableIsExist(table):
            self.write(json.dumps({"columns": [], "data": [], "total": 0, "warning": "指标表不存在"}, ensure_ascii=False))
            return
        
        if date:
            conditions.append("`date` = %s")
            sql_params.append(date)
        
        if strategy_key == "indicator_buy":
            indicator_map = {
                "kdjk_min": ("kdjk", ">="), "kdjd_min": ("kdjd", ">="), "kdjj_min": ("kdjj", ">="),
                "rsi6_min": ("rsi_6", ">="), "cci_min": ("cci", ">="),
                "cr_min": ("cr", ">="), "wr6_min": ("wr_6", ">="), "vr_min": ("vr", ">="),
            }
        else:
            indicator_map = {
                "kdjk_max": ("kdjk", "<"), "kdjd_max": ("kdjd", "<"), "kdjj_max": ("kdjj", "<"),
                "rsi6_max": ("rsi_6", "<"), "cci_max": ("cci", "<"),
                "cr_max": ("cr", "<"), "wr6_max": ("wr_6", "<"), "vr_max": ("vr", "<"),
            }
        
        for param_key, (col, op) in indicator_map.items():
            if param_key in params:
                conditions.append(f"`{col}` {op} %s")
                sql_params.append(params[param_key])
        
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        self._exec_filter_query(table, where, sql_params, limit_clause, params,
            "`date`, `code`, `name`, `kdjk`, `kdjd`, `kdjj`, `rsi_6`, `cci`, `cr`, `wr_6`, `vr`",
            [{"value": "date", "caption": "日期", "width": 110},
             {"value": "code", "caption": "代码", "width": 90},
             {"value": "name", "caption": "名称", "width": 100},
             {"value": "kdjk", "caption": "KDJ-K", "width": 70},
             {"value": "kdjd", "caption": "KDJ-D", "width": 70},
             {"value": "kdjj", "caption": "KDJ-J", "width": 70},
             {"value": "rsi_6", "caption": "RSI(6)", "width": 70},
             {"value": "cci", "caption": "CCI", "width": 70},
             {"value": "cr", "caption": "CR", "width": 70},
             {"value": "wr_6", "caption": "WR(6)", "width": 70},
             {"value": "vr", "caption": "VR", "width": 70}])
    
    def _filter_kline_strategy(self, strategy_key, date, page, page_size):
        """K线技术策略 — 从已有策略表读取数据"""
        strategy_config = TECHNICAL_STRATEGY_PARAMS.get(strategy_key, {})
        table_name = strategy_config.get('strategy_func', '')
        
        if not table_name or not mdb.checkTableIsExist(table_name):
            self.write(json.dumps({
                "columns": [], "data": [], "total": 0,
                "warning": f"策略表 {table_name} 不存在或无数据。请先在服务器运行流式分析任务。"
            }, ensure_ascii=False))
            return
        
        limit_clause = self._build_limit(page, page_size)
        conditions, sql_params = [], []
        if date:
            conditions.append("`date` = %s")
            sql_params.append(date)
        
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        self._exec_filter_query(table_name, where, sql_params, limit_clause, {},
            "`date`, `code`, `name`",
            [{"value": "date", "caption": "日期", "width": 110},
             {"value": "code", "caption": "代码", "width": 90},
             {"value": "name", "caption": "名称", "width": 100}],
            " ORDER BY `date` DESC")
    
    def _get_strategy_values(self, strategy_key):
        """获取策略的参数值（合并默认+用户自定义）"""
        _ensure_params_table()
        saved = _load_saved_params(strategy_key)
        result = {}
        strategy_def = DEFAULT_STRATEGY_PARAMS.get(strategy_key, {})
        for group in strategy_def.get('groups', []):
            for param in group.get('params', []):
                key = param['key']
                result[key] = saved.get(key, param['value'])
        return result
    
    def _build_limit(self, page, page_size):
        """构建LIMIT子句"""
        if page is not None and page_size is not None:
            try:
                page_int = max(1, int(page))
                page_size_int = max(1, min(500, int(page_size)))
                return f" LIMIT {page_size_int} OFFSET {(page_int - 1) * page_size_int}"
            except (ValueError, TypeError):
                pass
        return ""

    def _exec_filter_query(self, table, where, sql_params, limit_clause, params_used, select_cols, columns, order_by=""):
        """通用筛选查询执行"""
        try:
            from quantia.web.dataTableHandler import MyEncoder
            count_sql = f"SELECT COUNT(*) AS cnt FROM `{table}`{where}"
            data_sql = f"SELECT {select_cols} FROM `{table}`{where}{order_by}{limit_clause}"
            
            cache_params = tuple(sql_params) if sql_params else None
            hit, cached_total = filter_result_cache.get(count_sql, cache_params)
            if hit:
                total = cached_total
            else:
                total_result = self.db.query(count_sql, *sql_params) if sql_params else self.db.query(count_sql)
                total = total_result[0]["cnt"] if total_result else 0
                filter_result_cache.put(count_sql, cache_params, total)
            
            hit, cached_data = filter_result_cache.get(data_sql, cache_params)
            if hit:
                data = cached_data
            else:
                data = self.db.query(data_sql, *sql_params) if sql_params else self.db.query(data_sql)
                filter_result_cache.put(data_sql, cache_params, data)
            
            result = json.loads(json.dumps({
                "columns": columns,
                "data": data if data else [],
                "total": total,
                "params_used": params_used
            }, cls=MyEncoder))
            self.write(json.dumps(result, ensure_ascii=False))
        except Exception as e:
            error_msg = str(e)
            if "doesn't exist" in error_msg:
                self.write(json.dumps({"columns": [], "data": [], "total": 0, "warning": f"表不存在"}, ensure_ascii=False))
            else:
                logging.error(f"FilterStocksHandler 查询异常", exc_info=True)
                self.set_status(500)
                self.write(json.dumps({"error": f"查询异常: {error_msg}"}, ensure_ascii=False))


# 策略选股结果表名 -> {key, 中文名} 反查表，用于"历史选中"标注
_STRATEGY_TABLE_INFO = {
    cfg['strategy_func']: {'key': key, 'name': cfg.get('name', key)}
    for key, cfg in TECHNICAL_STRATEGY_PARAMS.items()
    if cfg.get('strategy_func')
}


class GetStrategyHistoryHandler(webBase.BaseHandler, ABC):
    """查询某只股票被某策略历史选中的全部日期。

    用于在指标详情页 K 线图上标注"该股票在哪些时间点被该策略选中"，
    从而直观展示策略的有效性。数据来源为每日流式分析任务写入的策略选股结果表。
    """

    def _resolve(self, strategy):
        """把策略 key 或表名解析为 (表名, 中文名)。非策略选股表一律返回 ('', '')。"""
        if not strategy:
            return '', ''
        # 1) 策略 key（如 enter）-> strategy_func 表名
        cfg = TECHNICAL_STRATEGY_PARAMS.get(strategy)
        if cfg and cfg.get('strategy_func'):
            table = cfg['strategy_func']
            return table, cfg.get('name', strategy)
        # 2) 直接传入策略表名（如 cn_stock_strategy_enter）
        info = _STRATEGY_TABLE_INFO.get(strategy)
        if info:
            return strategy, info['name']
        if strategy.startswith('cn_stock_strategy_'):
            return strategy, strategy
        return '', ''

    def get(self):
        self.set_header('Content-Type', 'application/json;charset=UTF-8')
        strategy = self.get_argument("strategy", default="", strip=True)
        code = self.get_argument("code", default="", strip=True)
        start_date = self.get_argument("start_date", default=None, strip=True)
        end_date = self.get_argument("end_date", default=None, strip=True)

        table_name, strategy_name = self._resolve(strategy)
        # 白名单 + 存在性校验：仅允许查询确实存在的策略选股结果表，杜绝任意表名注入
        if (not code or not table_name
                or not table_name.startswith('cn_stock_strategy_')
                or not mdb.checkTableIsExist(table_name)):
            self.write(json.dumps({
                "success": True, "strategy": strategy, "strategy_name": strategy_name,
                "code": code, "dates": []
            }, ensure_ascii=False))
            return

        conditions = ["`code` = %s"]
        sql_params = [code]
        if start_date:
            conditions.append("`date` >= %s")
            sql_params.append(start_date)
        if end_date:
            conditions.append("`date` <= %s")
            sql_params.append(end_date)
        where = " WHERE " + " AND ".join(conditions)
        sql = f"SELECT `date` FROM `{table_name}`{where} ORDER BY `date` ASC"
        try:
            rows = self.db.query(sql, *sql_params)
            dates = [str(r['date'])[:10] for r in (rows or []) if r.get('date') is not None]
            self.write(json.dumps({
                "success": True,
                "strategy": strategy,
                "strategy_name": strategy_name,
                "table": table_name,
                "code": code,
                "dates": dates,
            }, ensure_ascii=False))
        except Exception as e:
            logging.error("GetStrategyHistoryHandler 查询异常", exc_info=True)
            self.write(json.dumps({
                "success": False, "strategy": strategy, "code": code,
                "dates": [], "error": str(e)
            }, ensure_ascii=False))


class GetParamsHistoryHandler(webBase.BaseHandler, ABC):
    """查询策略参数变更历史"""

    def get(self):
        self.set_header('Content-Type', 'application/json;charset=UTF-8')
        strategy_key = self.get_argument("strategy", default=None, strip=True)
        if not strategy_key or strategy_key not in DEFAULT_STRATEGY_PARAMS:
            self.set_status(400)
            self.write(json.dumps({"error": "无效的策略标识"}, ensure_ascii=False))
            return

        limit = min(100, max(1, int(self.get_argument("limit", "50"))))
        history = _get_params_history(strategy_key, limit)

        # 为每条记录附加参数标签映射
        label_map = _build_param_label_map(strategy_key)
        for h in history:
            h['changed_labels'] = [label_map.get(k, k) for k in h.get('changed_keys', [])]

        self.write(json.dumps({"code": 0, "data": history}, ensure_ascii=False))


class GetParamsDiffHandler(webBase.BaseHandler, ABC):
    """对比两个参数版本的差异"""

    def get(self):
        self.set_header('Content-Type', 'application/json;charset=UTF-8')
        strategy_key = self.get_argument("strategy", default=None, strip=True)
        v1 = self.get_argument("v1", default=None, strip=True)
        v2 = self.get_argument("v2", default=None, strip=True)

        if not strategy_key or strategy_key not in DEFAULT_STRATEGY_PARAMS:
            self.set_status(400)
            self.write(json.dumps({"error": "无效的策略标识"}, ensure_ascii=False))
            return
        if not v1 or not v2:
            self.set_status(400)
            self.write(json.dumps({"error": "需要指定 v1 和 v2 版本号"}, ensure_ascii=False))
            return

        try:
            v1_int, v2_int = int(v1), int(v2)
        except ValueError:
            self.set_status(400)
            self.write(json.dumps({"error": "版本号必须为整数"}, ensure_ascii=False))
            return

        _ensure_history_table()
        rows = mdb.executeSqlFetch(
            """SELECT `version`, `params_snapshot`
               FROM `cn_strategy_params_history`
               WHERE `strategy_key` = %s AND `version` IN (%s, %s)""",
            (strategy_key, v1_int, v2_int))

        snapshots = {}
        if rows:
            for r in rows:
                snapshots[r[0]] = json.loads(r[1]) if r[1] else {}

        snap1 = snapshots.get(v1_int, {})
        snap2 = snapshots.get(v2_int, {})

        # 构建 diff
        all_keys = sorted(set(list(snap1.keys()) + list(snap2.keys())))
        label_map = _build_param_label_map(strategy_key)
        default_map = _build_default_value_map(strategy_key)

        diffs = []
        for k in all_keys:
            val1 = snap1.get(k, default_map.get(k))
            val2 = snap2.get(k, default_map.get(k))
            if val1 != val2:
                diffs.append({
                    'key': k,
                    'label': label_map.get(k, k),
                    'v1_value': val1,
                    'v2_value': val2,
                })

        self.write(json.dumps({
            "code": 0,
            "data": {
                "v1": v1_int, "v2": v2_int,
                "diffs": diffs,
                "total_changed": len(diffs),
            }
        }, ensure_ascii=False))


def _build_param_label_map(strategy_key):
    """构建 param_key -> label 映射"""
    label_map = {}
    if strategy_key in DEFAULT_STRATEGY_PARAMS:
        for group in DEFAULT_STRATEGY_PARAMS[strategy_key].get('groups', []):
            for param in group.get('params', []):
                label_map[param['key']] = param.get('label', param['key'])
    return label_map


def _build_default_value_map(strategy_key):
    """构建 param_key -> default_value 映射"""
    defaults = {}
    if strategy_key in DEFAULT_STRATEGY_PARAMS:
        for group in DEFAULT_STRATEGY_PARAMS[strategy_key].get('groups', []):
            for param in group.get('params', []):
                defaults[param['key']] = param.get('value')
    return defaults
