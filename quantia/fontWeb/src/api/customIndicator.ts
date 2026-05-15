import request from './request'
import { ElMessage } from 'element-plus'

/**
 * Phase 9 自定义综合指标 API
 *
 * 后端响应统一 envelope:  { code: 0, data: ... } / { code: -1, msg: ... }
 * 该 wrapper 自动 unwrap 并在 code != 0 时弹出错误并抛出
 */

export type IndicatorKind = 'primary_entry' | 'watchlist_alert'
export type IndicatorDirection = 'low' | 'high'

export interface IndicatorListItem {
  indicator_id: string
  name: string
  kind: IndicatorKind
  description: string | null
  is_builtin: 0 | 1
  updated_at: string | null
}

export interface RiskProfile {
  stop?: number
  target?: number
  max_hold?: number
}

export interface IndicatorRecord {
  indicator_id: string
  name: string
  kind: IndicatorKind
  description: string | null
  weights: Record<string, number>
  smooth_ema: number
  buy_th: number
  direction: IndicatorDirection
  hard_rules: string | null
  extra_filter: string | null
  risk_profile: RiskProfile
  is_builtin: 0 | 1
  created_at?: string
  updated_at?: string
}

export interface BacktestSummary {
  strategy?: string
  trades?: number
  'win%'?: number
  'avg%'?: number
  'med%'?: number
  'expectancy%'?: number
  PF?: number | null
  avg_hold?: number
  'stop%'?: number
  'tp%'?: number
  'time%'?: number
  'fund%'?: number
  [k: string]: any
}

export interface BacktestTrade {
  entry_date: string
  entry_price: number
  exit_date: string
  exit_price: number
  reason: string
  net_ret_pct: number
  hold_days: number
}

export interface BacktestResult {
  summary: BacktestSummary
  trades: BacktestTrade[]
}

export interface SignalPoint {
  date: string
  price: number
  action: string
  reason?: string
}

export interface ScorePoint {
  date: string
  score: number
}

export interface SeriesResult {
  indicator_id: string
  name: string
  kind: IndicatorKind
  signal_points: SignalPoint[]
  score_series: ScorePoint[]
}

export interface WatchlistItem {
  code: string
  name?: string
  latest_score?: number
  latest_signal?: boolean
  [k: string]: any
}

export interface WatchlistResult {
  indicator_id: string
  name?: string
  kind?: IndicatorKind
  warning?: string | null
  items: WatchlistItem[]
}

async function unwrap<T>(p: Promise<any>): Promise<T> {
  const res: any = await p
  if (res && res.code === 0) return res.data as T
  const msg = res?.msg || '未知错误'
  ElMessage.error(msg)
  throw new Error(msg)
}

export function listIndicators(kind?: IndicatorKind | '') {
  const params: any = {}
  if (kind) params.kind = kind
  return unwrap<IndicatorListItem[]>(request({
    url: '/api/custom_indicator/list',
    method: 'get',
    params,
  }))
}

export function getIndicator(indicatorId: string) {
  return unwrap<IndicatorRecord>(request({
    url: '/api/custom_indicator/detail',
    method: 'get',
    params: { indicator_id: indicatorId },
  }))
}

export function saveIndicator(record: Partial<IndicatorRecord>) {
  return unwrap<{ indicator_id: string }>(request({
    url: '/api/custom_indicator/save',
    method: 'post',
    data: record,
  }))
}

export function deleteIndicator(indicatorId: string) {
  return unwrap<{ indicator_id: string }>(request({
    url: '/api/custom_indicator/delete',
    method: 'post',
    data: { indicator_id: indicatorId },
  }))
}

export function backtestIndicator(payload: {
  indicator_id: string
  code: string
  start: string
  end: string
}) {
  return unwrap<BacktestResult>(request({
    url: '/api/custom_indicator/backtest',
    method: 'post',
    data: payload,
  }))
}

export function indicatorSeries(payload: {
  indicator_id: string
  code: string
  start: string
  end: string
  period?: 'daily' | 'weekly' | 'monthly'
}) {
  return unwrap<SeriesResult>(request({
    url: '/api/custom_indicator/series',
    method: 'get',
    params: payload,
  }))
}

export function watchlistToday(indicatorId: string, topN = 50) {
  return unwrap<WatchlistResult>(request({
    url: '/api/custom_indicator/watchlist',
    method: 'get',
    params: { indicator_id: indicatorId, top_n: topN },
  }))
}

/**
 * 可用归一化因子（n_*）一览，用于权重表组件下拉
 * 来源: quantia.core.composite.indicators_enrich.enrich
 */
export const NORMALIZED_FACTORS: { value: string; label: string }[] = [
  { value: 'n_rsi14',             label: 'n_rsi14 - RSI14 归一化（低位强）' },
  { value: 'n_rsi6',              label: 'n_rsi6 - RSI6 归一化（短线超卖）' },
  { value: 'n_kdj_k',             label: 'n_kdj_k - KDJ K 值' },
  { value: 'n_kdj_j',             label: 'n_kdj_j - KDJ J 值（弹性大）' },
  { value: 'n_wr14',              label: 'n_wr14 - 威廉指标（反向归一）' },
  { value: 'n_macd_hist_rank',    label: 'n_macd_hist_rank - MACD 柱滚动排名' },
  { value: 'n_trend_st',          label: 'n_trend_st - SuperTrend 多空' },
  { value: 'n_vol_ratio_rank',    label: 'n_vol_ratio_rank - 量比滚动排名' },
  { value: 'n_boll_pct_b',        label: 'n_boll_pct_b - 布林位置 %B' },
  { value: 'n_ma_uptrend',        label: 'n_ma_uptrend - MA20>MA60 上升趋势' },
  { value: 'n_long_uptrend',      label: 'n_long_uptrend - MA60>MA120 长趋势' },
  { value: 'n_atr_pct_inv_rank',  label: 'n_atr_pct_inv_rank - 低波动优先' },
  { value: 'n_obv_slope_rank',    label: 'n_obv_slope_rank - OBV 斜率排名' },
  { value: 'n_adx_rank',          label: 'n_adx_rank - ADX 强度排名' },
  { value: 'n_cci_inv',           label: 'n_cci_inv - CCI 反向（低位强）' },
]
