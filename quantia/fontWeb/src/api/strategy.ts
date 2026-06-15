import request from './request'

/**
 * 策略参数相关API
 */

export interface StrategyParam {
  key: string
  label: string
  description: string
  type: 'number' | 'text' | 'password' | 'select' | 'switch'
  value: any
  min?: number
  max?: number
  step?: number
  unit?: string
  field?: string
  options?: { label: string; value: string }[]
  is_custom?: boolean
}

export interface ParamGroup {
  group_name: string
  group_description: string
  params: StrategyParam[]
}

export interface StrategyParamsResponse {
  name: string
  description: string
  groups: ParamGroup[]
}

export interface StrategyListItem {
  key: string
  name: string
  description: string
}

/**
 * 获取可配置的策略列表
 */
export function getStrategyList() {
  return request({
    url: '/api/strategy/params',
    method: 'get'
  })
}

/**
 * 获取指定策略的参数配置
 */
export function getStrategyParams(strategy: string) {
  return request({
    url: '/api/strategy/params',
    method: 'get',
    params: { strategy }
  })
}

/**
 * 保存策略参数
 */
export function saveStrategyParams(strategy: string, params: Record<string, any>) {
  return request({
    url: '/api/strategy/params/save',
    method: 'post',
    data: { strategy, params }
  })
}

/**
 * 重置策略参数为默认值
 */
export function resetStrategyParams(strategy: string) {
  return request({
    url: '/api/strategy/params/reset',
    method: 'post',
    data: { strategy }
  })
}

/**
 * 根据当前参数动态筛选股票
 */
export function filterStocks(strategy: string, date?: string, page?: number, pageSize?: number) {
  return request({
    url: '/api/strategy/filter',
    method: 'get',
    params: { strategy, date, page, page_size: pageSize }
  })
}

/**
 * 查询策略参数变更历史
 */
export function getParamsHistory(strategy: string, limit?: number) {
  return request({
    url: '/api/strategy/params/history',
    method: 'get',
    params: { strategy, limit }
  })
}

/**
 * 对比两个参数版本的差异
 */
export function getParamsDiff(strategy: string, v1: number, v2: number) {
  return request({
    url: '/api/strategy/params/diff',
    method: 'get',
    params: { strategy, v1, v2 }
  })
}

/**
 * 查询某只股票被某策略历史选中的全部日期（用于在指标详情页标注策略有效性）
 * @param strategy 策略 key（如 enter）或策略选股结果表名（如 cn_stock_strategy_enter）
 */
export function getStrategyHistory(strategy: string, code: string, startDate?: string, endDate?: string) {
  return request({
    url: '/api/strategy/history',
    method: 'get',
    params: { strategy, code, start_date: startDate, end_date: endDate }
  })
}