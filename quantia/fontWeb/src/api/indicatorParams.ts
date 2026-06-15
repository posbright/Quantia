import request from './request'

/**
 * 指标买卖信号「指标设置」相关 API。
 *
 * 参数的查询/保存/重置复用通用的 strategy 参数接口（strategy_key='indicator_signal'），
 * 立即重算与 AI 顾问为本模块专属接口。
 */

export const INDICATOR_SIGNAL_KEY = 'indicator_signal'

export interface RecomputeResult {
  success: boolean
  date?: string
  buy_count?: number
  sell_count?: number
  message?: string
  error?: string
}

export interface AdvisorResult {
  success: boolean
  date?: string
  current_counts?: { buy: number | null; sell: number | null }
  recommendations?: Record<string, number>
  reasons?: Record<string, string>
  summary?: string
  error?: string
  raw?: string
}

/** 获取指标信号参数配置（含已保存值与默认值合并） */
export function getIndicatorParams() {
  return request({
    url: '/api/strategy/params',
    method: 'get',
    params: { strategy: INDICATOR_SIGNAL_KEY }
  })
}

/** 保存指标信号参数 */
export function saveIndicatorParams(params: Record<string, any>) {
  return request({
    url: '/api/strategy/params/save',
    method: 'post',
    data: { strategy: INDICATOR_SIGNAL_KEY, params }
  })
}

/** 重置指标信号参数为默认值 */
export function resetIndicatorParams() {
  return request({
    url: '/api/strategy/params/reset',
    method: 'post',
    data: { strategy: INDICATOR_SIGNAL_KEY }
  })
}

/** 用当前已保存参数立即重算买/卖信号榜单 */
export function recomputeIndicatorSignals(date?: string) {
  return request({
    url: '/api/indicator/signal_recompute',
    method: 'post',
    data: { date }
  })
}

/** 让 AI 基于当前阈值与命中情况推荐参数组合 */
export function getIndicatorAdvice(payload: {
  date?: string
  model?: string
  api_key?: string
  api_base?: string
} = {}) {
  return request({
    url: '/api/indicator/advisor',
    method: 'post',
    data: payload
  })
}
