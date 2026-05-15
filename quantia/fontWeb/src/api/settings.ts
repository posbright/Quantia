import request from './request'

// ─────────── Notification config ───────────

export interface NotificationConfig {
  id?: number
  paper_id?: number | null
  channel: string
  event_type: string
  enabled: boolean
  webhook_env?: string
  secret_env?: string
  webhook_is_configured?: boolean
  secret_is_configured?: boolean
  summary_config?: Record<string, any>
  detail_config?: Record<string, any>
  config_version?: number
  created_at?: string
  updated_at?: string
}

export const listNotificationConfigs = (params?: { paper_id?: number; channel?: string }) =>
  request.get<any, { ok: boolean; data: NotificationConfig[] }>('/api/notification/config/list', { params })

export const getNotificationConfig = (id: number) =>
  request.get<any, { ok: boolean; data: NotificationConfig }>('/api/notification/config/detail', { params: { id } })

export const saveNotificationConfig = (payload: NotificationConfig) =>
  request.post<any, { ok: boolean; data: NotificationConfig; error?: string }>('/api/notification/config/save', payload)

export const deleteNotificationConfig = (id: number) =>
  request.post<any, { ok: boolean; error?: string }>('/api/notification/config/delete', { id })

export const testSendNotification = (payload: { paper_id?: number | null; channel?: string }) =>
  request.post<any, { ok: boolean; data: any; error?: string }>('/api/notification/config/test_send', payload)

export const retryNotificationEvent = (event_id: number) =>
  request.post<any, { ok: boolean; data: any }>('/api/notification/event/retry', { event_id })

// ─────────── Notification event admin (Phase 3) ───────────

export const listNotificationEvents = (params?: Record<string, any>) =>
  request.get<any, { ok: boolean; data: any[] }>('/api/notification/event/list', { params })

export const getNotificationEventDetail = (event_id: number) =>
  request.get<any, { ok: boolean; data: any }>('/api/notification/event/detail', { params: { event_id } })

// ─────────── AI decision config ───────────

export interface AIDecisionConfig {
  id?: number
  name: string
  enabled: boolean
  source_type: string
  source_id?: number | null
  strategy_id?: number | null
  provider: string
  model_name?: string | null
  base_url?: string | null
  api_key_ref?: string | null
  api_key_is_configured?: boolean
  system_prompt?: string | null
  user_prompt_template?: string | null
  output_schema?: Record<string, any> | null
  tool_config?: Record<string, any> | null
  temperature?: number
  max_tokens?: number
  timeout_seconds?: number
  retry_count?: number
  enabled_as_gate?: boolean
  fail_closed?: boolean
  buy_threshold?: number
  sell_threshold?: number
  config_version?: number
  created_at?: string
  updated_at?: string
}

export const listAIConfigs = (params?: { source_type?: string; source_id?: number }) =>
  request.get<any, { ok: boolean; data: AIDecisionConfig[] }>('/api/ai/config/list', { params })

export const getAIConfig = (id: number) =>
  request.get<any, { ok: boolean; data: AIDecisionConfig }>('/api/ai/config/detail', { params: { id } })

export const saveAIConfig = (payload: AIDecisionConfig) =>
  request.post<any, { ok: boolean; data: AIDecisionConfig; error?: string }>('/api/ai/config/save', payload)

export const deleteAIConfig = (id: number) =>
  request.post<any, { ok: boolean; error?: string }>('/api/ai/config/delete', { id })
