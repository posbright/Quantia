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
  signal_sparse_reason?: 'no_base_signal' | 'filtered_out' | 'low_density' | null
  signal_sparse_hint?: string | null
  signal_diagnosis?: {
    base_signal_count: number
    filtered_signal_count: number
    filter_factor_count?: number
    per_strategy_counts?: Record<string, number>
  }
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

// ── 保存/加载/删除因子配置 ────────────────────────────────────────────

export interface FactorLabConfig {
  id: number
  name: string
  description: string
  factors: ActiveFactor[]
  fusion_mode: string
  vote_threshold: number
  holding_days: number
  created_at: string
  updated_at: string
}

export interface SaveConfigParams {
  id?: number
  name: string
  description?: string
  factors: ActiveFactor[]
  fusion_mode: string
  vote_threshold?: number
  holding_days?: number
}

export function saveFactorConfig(data: SaveConfigParams) {
  return request<{ id: number; message: string }>({
    url: '/api/factor_lab/save',
    method: 'post',
    data,
  })
}

export function getMyConfigs() {
  return request<{ configs: FactorLabConfig[] }>({
    url: '/api/factor_lab/my_configs',
    method: 'get',
  })
}

export function deleteFactorConfig(id: number) {
  return request<{ message: string; id: number }>({
    url: `/api/factor_lab/configs/${id}`,
    method: 'delete',
  })
}

// ── 导出代码 ──────────────────────────────────────────────────────────

export interface ExportCodeParams {
  factors: ActiveFactor[]
  fusion_mode: string
  vote_threshold?: number
  holding_days?: number
}

export interface ExportCodeResult {
  code: string
  filename: string
}

export function exportFactorCode(data: ExportCodeParams) {
  return request<ExportCodeResult>({
    url: '/api/factor_lab/export_code',
    method: 'post',
    data,
  })
}
