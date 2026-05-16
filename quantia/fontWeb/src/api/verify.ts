import request from './request'

// ── 策略列表 ──────────────────────────────────────────────────────────

export interface StrategyItem {
  value: string
  label: string
  table?: string
  description?: string
  custom_id?: number
  type?: 'signal' | 'backtest'
  backtest_count?: number
}
export interface StrategyGroup {
  label: string
  category: string
  items: StrategyItem[]
}
export function getVerifyStrategyList(): Promise<{ groups: StrategyGroup[] }> {
  return request({ url: '/api/verify/strategy_list', method: 'get' }) as any
}

// ── 自定义策略对比 ────────────────────────────────────────────────────

export function getCustomCompare(params: { strategy: string }) {
  return request({ url: '/api/verify/custom_compare', method: 'get', params }) as any
}

export function getCustomReturnSeries(params: { strategy: string }) {
  return request({ url: '/api/verify/custom_return_series', method: 'get', params }) as any
}

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

// ── 卖出方式对比 ──────────────────────────────────────────────────────

export interface ExitCompareParams {
  strategy: string
  start_date: string
  end_date: string
  holding_days?: number
  trailing_days?: string
}

export function getExitCompare(params: ExitCompareParams) {
  return request({ url: '/api/verify/exit_compare', method: 'get', params })
}

// ── 策略融合 ──────────────────────────────────────────────────────────

export interface FusionParams {
  strategy_names: string[]
  mode: 'intersection' | 'union' | 'vote' | 'rotation'
  vote_threshold?: number
  start_date: string
  end_date: string
  holding_days?: number
  filters?: Record<string, number>
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

// ── 日级收益序列 ──────────────────────────────────────────────────────

export interface ReturnSeriesParams {
  strategy: string
  start_date: string
  end_date: string
  holding_days?: number
}

export function getReturnSeries(params: ReturnSeriesParams) {
  return request({ url: '/api/verify/return_series', method: 'get', params })
}
