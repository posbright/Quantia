import request from './request'

// ── 因子目录 ──────────────────────────────────────────────────────────

export interface FactorMeta {
  id: string
  name: string
  category: 'tech_signal' | 'tech_indicator' | 'fundamental' | 'fund_flow'
  type: 'signal' | 'continuous' | 'range'
  table: string
  column: string | null
  icon: string
  direction?: 'asc' | 'desc'
  description?: string
  default_operator?: string
  default_value?: number | number[]
  presets?: { label: string; operator: string; value: number | number[] }[]
}

export interface FactorCategory {
  key: string
  name: string
  icon: string
  factors: FactorMeta[]
}

export function getFactorCatalog() {
  return request<{ categories: FactorCategory[] }>({
    url: '/api/factor_lab/factors',
    method: 'get',
  })
}

// ── 运行因子组合回测 ──────────────────────────────────────────────────

export interface ActiveFactor {
  id: string
  weight: number
  enabled: boolean
  operator?: string
  value?: number | number[]
}

export interface FactorLabRunParams {
  factors: ActiveFactor[]
  fusion_mode: 'and' | 'vote' | 'score'
  vote_threshold?: number
  holding_days: number
  start_date: string
  end_date: string
}

export interface KPI {
  sharpe: number | null
  win_rate: number | null
  avg_return: number | null
  max_drawdown: number | null
  calmar: number | null
  daily_signal_avg: number
  signal_count: number
  filter_rate: number | null
}

export interface DailyPoint {
  date: string
  cumulative: number
  drawdown: number
}

export interface FactorContribution {
  id: string
  name: string
  category: string
  impact: number | null
}

export interface FactorLabRunResult {
  kpi: KPI
  baseline: KPI
  daily_series: DailyPoint[]
  factor_contributions: FactorContribution[]
  signal_sparse_warning: boolean
  holding_days: number
  period: string
  fusion_mode: string
}

export function runFactorLab(data: FactorLabRunParams) {
  return request<FactorLabRunResult>({
    url: '/api/factor_lab/run',
    method: 'post',
    data,
  })
}

// ── 预设模板 ──────────────────────────────────────────────────────────

export interface PresetFactor {
  id: string
  name: string
  category: string
  type: string
  icon: string
  weight: number
  enabled: boolean
  operator?: string
  value?: number | number[]
}

export interface Preset {
  id: string
  name: string
  fusion_mode: string
  vote_threshold?: number
  factors: PresetFactor[]
}

export function getFactorPresets() {
  return request<{ presets: Preset[] }>({
    url: '/api/factor_lab/presets',
    method: 'get',
  })
}
