import request from './request'

export interface KronosConfig {
  schema_version: number
  enabled: boolean
  mode: 'shadow' | 'canary' | 'production'
  qualification_status: 'not_qualified' | 'challenger' | 'qualified'
  preset_name: string
  provider_url: string
  lookback: number
  horizons: number[]
  sample_count: number
  sample_batch_size: number
  temperature: number
  top_k: number
  top_p: number
  clip: number
  timeout_seconds: number
  require_human_approval: boolean
  notes: string
  config_hash?: string
  updated_at?: string
}

export interface KronosRunConfig {
  id: string
  configuration: Record<string, number>
  status: string
  qualified: boolean | null
  operational_qualified: boolean | null
  robust_qualified: boolean | null
  failures: string[]
  records: number
  complete: boolean
}

export interface KronosRun {
  name: string
  status: string
  complete: boolean
  configuration_count: number
  represented_configurations: number
  completed_configurations: number
  qualified_count: number
  records: number
  expected_records: number
  progress: number | null
  observed: number
  provider_errors: number
  audited: number
  updated_at: number
  configurations: KronosRunConfig[]
}

export interface KronosOverview {
  config: KronosConfig
  runs_root: string
  run_count: number
  latest: KronosRun | null
  has_qualified_candidate: boolean
}

export interface KronosHealth {
  reachable: boolean
  url: string
  error?: string
  data?: Record<string, any>
}

interface ApiResult<T> {
  ok: boolean
  data: T
  error?: string
}

export const getKronosConfig = () =>
  request.get<any, ApiResult<KronosConfig>>('/api/kronos/config')

export const saveKronosConfig = (payload: KronosConfig) =>
  request.post<any, ApiResult<KronosConfig>>('/api/kronos/config', payload)

export const getKronosOverview = () =>
  request.get<any, ApiResult<KronosOverview>>('/api/kronos/monitor/overview')

export const getKronosRuns = () =>
  request.get<any, ApiResult<KronosRun[]>>('/api/kronos/monitor/runs')

export const getKronosHealth = () =>
  request.get<any, ApiResult<KronosHealth>>('/api/kronos/monitor/health')
