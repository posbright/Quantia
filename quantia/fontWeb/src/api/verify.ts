import request from './request'

// ── 持仓天数扫描 ──────────────────────────────────────────────────────

export interface HoldingPeriodParams {
  strategy: string
  start_date: string
  end_date: string
  holding_days?: string
}

export function getHoldingPeriod(params: HoldingPeriodParams) {
  return request({ url: '/api/verify/holding_period', method: 'get', params })
}

// ── 信号质量诊断 ──────────────────────────────────────────────────────

export interface SignalQualityParams {
  strategy: string
  start_date: string
  end_date: string
  indicator?: string
  holding_days?: number
  buckets?: string
}

export function getSignalQuality(params: SignalQualityParams) {
  return request({ url: '/api/verify/signal_quality', method: 'get', params })
}

// ── 止盈止损矩阵 ──────────────────────────────────────────────────────

export interface SlTpMatrixParams {
  strategy: string
  start_date: string
  end_date: string
  sl_range?: string
  tp_range?: string
  max_hold_days?: number
}

export function getSlTpMatrix(params: SlTpMatrixParams) {
  return request({ url: '/api/verify/sl_tp_matrix', method: 'get', params })
}

// ── 市场环境分类 ──────────────────────────────────────────────────────

export interface MarketRegimeParams {
  strategy: string
  start_date: string
  end_date: string
  benchmark?: string
  holding_days?: number
}

export function getMarketRegime(params: MarketRegimeParams) {
  return request({ url: '/api/verify/market_regime', method: 'get', params })
}

// ── 信号衰减分析 ──────────────────────────────────────────────────────

export interface SignalDecayParams {
  strategy: string
  start_date: string
  end_date: string
  holding_days?: number
}

export function getSignalDecay(params: SignalDecayParams) {
  return request({ url: '/api/verify/signal_decay', method: 'get', params })
}

// ── 交易成本敏感性 ────────────────────────────────────────────────────

export interface CostSensitivityParams {
  strategy: string
  start_date: string
  end_date: string
  holding_days?: number
}

export function getCostSensitivity(params: CostSensitivityParams) {
  return request({ url: '/api/verify/cost_sensitivity', method: 'get', params })
}

// ── 策略融合 ──────────────────────────────────────────────────────────

export interface FusionParams {
  strategy_names: string[]
  mode: 'intersection' | 'union' | 'vote'
  vote_threshold?: number
  start_date: string
  end_date: string
  holding_days?: number
}

export function runFusion(data: FusionParams) {
  return request({ url: '/api/verify/fusion', method: 'post', data })
}

// ── 优化建议 ──────────────────────────────────────────────────────────

export interface OptimizeSuggestParams {
  strategy: string
  start_date: string
  end_date: string
}

export function getOptimizeSuggest(params: OptimizeSuggestParams) {
  return request({ url: '/api/verify/optimize_suggest', method: 'get', params })
}
