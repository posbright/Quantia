import request from './request'

// ─────────── Phase 6: IM Command + Operator Whitelist ───────────

export interface IMOperator {
  id?: number
  channel: string
  operator_id: string
  operator_name?: string | null
  enabled: boolean
  note?: string | null
  created_at?: string
  updated_at?: string
}

export interface IMCommand {
  id: number
  source_channel: string
  source_message_id?: string | null
  operator_id?: string | null
  operator_name?: string | null
  command_type: string
  paper_id?: number | null
  signal_id?: number | null
  code?: string | null
  direction?: string | null
  amount?: number | null
  value?: number | null
  price_limit?: number | null
  status: string
  risk_check?: any
  request_payload?: any
  expire_at?: string | null
  approved_at?: string | null
  executed_at?: string | null
  execution_result?: any
  created_at?: string
  updated_at?: string
}

export interface IMStatus {
  enabled: boolean
  enabled_env: string
  max_single_value: number
  max_daily_value: number
  ttl_seconds: number
}

export const getIMStatus = () =>
  request.get<any, { ok: boolean; data: IMStatus }>('/api/im/status')

export const listIMCommands = (params?: { status?: string; paper_id?: number; limit?: number; offset?: number }) =>
  request.get<any, { ok: boolean; data: IMCommand[] }>('/api/im/command/list', { params })

export const getIMCommand = (id: number) =>
  request.get<any, { ok: boolean; data: IMCommand }>('/api/im/command/detail', { params: { id } })

export const listIMOperators = (params?: { channel?: string }) =>
  request.get<any, { ok: boolean; data: IMOperator[] }>('/api/im/operator/list', { params })

export const saveIMOperator = (payload: IMOperator) =>
  request.post<any, { ok: boolean; data: IMOperator; error?: string }>('/api/im/operator/save', payload)

export const deleteIMOperator = (id: number) =>
  request.post<any, { ok: boolean; error?: string }>('/api/im/operator/delete', { id })

// ─────────── Phase 7: Live trading executor ───────────

export interface LiveStatus {
  enabled: boolean
  enabled_env: string
  broker: string
  broker_env: string
  trading_hours: string
}

export interface LiveExecuteStats {
  status: string // 'ok' | 'disabled'
  reason?: string
  broker?: string
  processed: number
  executed: number
  expired: number
  rejected: number
  failed: number
  details: Array<{ id: number; status: string; order_id?: string; error?: string }>
}

export const getLiveStatus = () =>
  request.get<any, { ok: boolean; data: LiveStatus }>('/api/live/status')

export const executeLivePending = (limit = 20) =>
  request.post<any, { ok: boolean; data: LiveExecuteStats; error?: string }>('/api/live/execute_pending', { limit })
