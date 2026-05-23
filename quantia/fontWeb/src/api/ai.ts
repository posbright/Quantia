import request from './request'

export interface AiOverrides {
  provider?: string
  api_base?: string
  api_key?: string
  model?: string
  temperature?: number
  max_tokens?: number
  timeout?: number
}

export interface GenerateRequest extends AiOverrides {
  prompt: string
}

export interface RefineRequest extends AiOverrides {
  prompt: string
  code: string
}

export interface RepairRequest extends AiOverrides {
  strategy_id: number | string
  code?: string
  // 预演回测参数（仅当 DB 无失败记录时由后端使用 — 见 RepairStrategyHandler）
  auto_backtest?: boolean
  start_date?: string
  end_date?: string
  initial_cash?: number
  benchmark?: string
  strategy_name?: string
}

export interface ChatRequest extends AiOverrides {
  prompt: string
  system?: string
  scene?: string
  agent?: string
  conversation_id?: string
}

export interface ChatResponse {
  code: number
  msg?: string
  data?: {
    content: string
    model?: string
    conversation_id?: string
    history_count?: number
  }
}

export interface StrategyAiResponse {
  code: number  // 0=ok, -2=validation_failed, -1=error, 429=rate_limit
  msg?: string
  data?: {
    code: string
    raw: string
    validated: boolean
    validation_error?: string
    model?: string
    repair_attempts?: number
    repair_status?: 'success' | 'unrepaired' | 'max_attempts' | 'no_progress' | 'rate_limited' | 'provider_error'
    failure?: {
      error_message: string
      started_at: string
      backtest_id: number
    }
  }
}

// AI 策略接口的超时单独拉长到 5 分钟——闭环验收最多包含 3 轮 AI 调用
// (单次 Kimi 可达 60s) + 3 次运行期预演回测，全局 60s 超时不够用。
const AI_LONG_TIMEOUT = 5 * 60 * 1000

export function aiGenerateStrategy(data: GenerateRequest) {
  return request({ url: '/api/ai/strategy/generate', method: 'post', data,
    timeout: AI_LONG_TIMEOUT })
}

export function aiRefineStrategy(data: RefineRequest) {
  return request({ url: '/api/ai/strategy/refine', method: 'post', data,
    timeout: AI_LONG_TIMEOUT })
}

export function aiRepairStrategy(data: RepairRequest) {
  return request({ url: '/api/ai/strategy/repair', method: 'post', data,
    timeout: AI_LONG_TIMEOUT })
}

export function aiChat(data: ChatRequest) {
  return request({ url: '/api/ai/chat', method: 'post', data,
    timeout: AI_LONG_TIMEOUT }) as Promise<ChatResponse>
}

// ── M8: 多轮对话历史 ────────────────────────────────────────────
export interface AiConversationSummary {
  conversation_id: string
  scene: string
  agent?: string | null
  title?: string | null
  user_id?: string | null
  message_count: number
  total_tokens: number
  created_at: number
  updated_at: number
}

export interface AiConversationDetail extends AiConversationSummary {
  messages: Array<{ role: string; content: string; ts: number }>
}

export function aiListConversations(params: { scene?: string; mine?: boolean; limit?: number } = {}) {
  return request({
    url: '/api/ai/conversations',
    method: 'get',
    params: {
      ...(params.scene ? { scene: params.scene } : {}),
      ...(params.mine ? { mine: 1 } : {}),
      ...(params.limit ? { limit: params.limit } : {}),
    },
  }) as Promise<{ code: number; msg?: string; data?: AiConversationSummary[] }>
}

export function aiGetConversation(conversation_id: string) {
  return request({
    url: '/api/ai/conversations/detail',
    method: 'get',
    params: { conversation_id },
  }) as Promise<{ code: number; msg?: string; data?: AiConversationDetail }>
}

export function aiDeleteConversation(conversation_id: string) {
  return request({
    url: '/api/ai/conversations',
    method: 'delete',
    params: { conversation_id },
  }) as Promise<{ code: number; msg?: string; data?: { deleted: boolean } }>
}

export function aiRenameConversation(conversation_id: string, title: string) {
  return request({
    url: '/api/ai/conversations/rename',
    method: 'post',
    data: { conversation_id, title },
  }) as Promise<{ code: number; msg?: string; data?: { renamed: boolean } }>
}

// ── M5: provider/model/agent 元数据 ────────────────────────────
export interface AiProviderProfile {
  name: string
  label?: string
  api_base?: string
  has_key?: boolean
  models?: string[]
  default_model?: string
}

export interface AiAgentMeta {
  name: string
  display_name?: string
  description?: string
  is_builtin?: boolean
  has_prompt?: boolean
}

export interface AiConfigResponse {
  code: number
  msg?: string
  data?: {
    profiles: AiProviderProfile[]
    default: string
    default_model?: string
    temperature?: number
    max_tokens?: number
    timeout?: number
    agents: AiAgentMeta[]
  }
}

export function aiGetConfig() {
  return request({ url: '/api/ai/config', method: 'get' }) as Promise<AiConfigResponse>
}

export function aiListAgents(includePrompt = false) {
  return request({
    url: '/api/ai/agents',
    method: 'get',
    params: includePrompt ? { include_prompt: 1 } : undefined,
  })
}

// ── M7: 自定义 Agent 管理 ───────────────────────────────────────
export interface AiAgentRecord {
  name: string
  display_name?: string
  description?: string
  system_prompt?: string
  default_provider?: string
  default_model?: string
  allowed_tools?: string[] | null
  temperature?: number
  max_tokens?: number
  is_builtin?: boolean
  enabled?: boolean
  created_at?: string
  updated_at?: string
}

export function aiListManagedAgents(includePrompt = false) {
  return request({
    url: '/api/ai/agents/manage',
    method: 'get',
    params: includePrompt ? { include_prompt: 1 } : undefined,
  })
}

export function aiGetAgentDetail(name: string) {
  return request({
    url: '/api/ai/agents/detail',
    method: 'get',
    params: { name },
  })
}

export function aiSaveAgent(data: Partial<AiAgentRecord>) {
  return request({
    url: '/api/ai/agents/manage',
    method: 'post',
    data,
  })
}

export function aiDeleteAgent(name: string) {
  return request({
    url: '/api/ai/agents/manage',
    method: 'delete',
    params: { name },
  })
}

// SSE 事件类型（B1）
export type AiStreamEvent =
  | { type: 'chunk'; text: string }
  | { type: 'repair'; attempt: number }
  | { type: 'done'; code: string; raw: string; validated: boolean; validation_error?: string; model?: string; repair_attempts?: number; repair_status?: string; truncated?: boolean }
  | { type: 'error'; code: number; msg: string }

/**
 * 流式生成策略代码。基于 fetch + ReadableStream 解析 SSE。
 * 调用方通过 onEvent 接收每个事件；返回 Promise 在流结束/出错时 resolve/reject。
 */
export async function aiGenerateStrategyStream(
  data: GenerateRequest,
  onEvent: (ev: AiStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const resp = await fetch('/quantia/api/ai/strategy/generate/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(data),
    signal,
  })
  if (!resp.ok || !resp.body) {
    throw new Error(`HTTP ${resp.status}`)
  }
  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buf = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    // SSE 事件以空行分隔
    let idx: number
    while ((idx = buf.indexOf('\n\n')) !== -1) {
      const raw = buf.slice(0, idx).trim()
      buf = buf.slice(idx + 2)
      if (!raw.startsWith('data:')) continue
      const payload = raw.slice(5).trim()
      try {
        onEvent(JSON.parse(payload) as AiStreamEvent)
      } catch (e) {
        // ignore malformed event
      }
    }
  }
}

// ── Token 用量统计 + 功能开关 ──────────────────────────────────
export interface TokenSummary {
  today_tokens: number
  today_calls: number
  month_tokens: number
  hour_calls: number
  hour_tokens: number
  hour_limit_calls: number
  hour_limit_tokens: number
}

export interface TokenByModel {
  model: string
  total_tokens: number
  call_count: number
}

export interface TokenByScene {
  scene: string
  total_tokens: number
  call_count: number
}

export interface TokenDailyTrend {
  date: string
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  call_count: number
}

export interface TokenFeatureStatus {
  feature: string
  enabled: boolean
  daily_budget: number | null
  used_today: number
  remaining: number | null
  modified_by?: string
  updated_at?: string
}

export interface TokenRecentCall {
  id: number
  scene: string
  model: string
  provider: string
  total_tokens: number | null
  latency_ms: number | null
  ok: boolean
  created_at: string
}

export function aiTokenSummary() {
  return request({ url: '/api/ai/token/summary', method: 'get' }) as
    Promise<{ ok: boolean; data?: TokenSummary; error?: string }>
}

export function aiTokenByModel(days = 30) {
  return request({ url: '/api/ai/token/by_model', method: 'get', params: { days } }) as
    Promise<{ ok: boolean; data?: TokenByModel[]; error?: string }>
}

export function aiTokenByScene(days = 30) {
  return request({ url: '/api/ai/token/by_scene', method: 'get', params: { days } }) as
    Promise<{ ok: boolean; data?: TokenByScene[]; error?: string }>
}

export function aiTokenDailyTrend(days = 30) {
  return request({ url: '/api/ai/token/daily_trend', method: 'get', params: { days } }) as
    Promise<{ ok: boolean; data?: TokenDailyTrend[]; error?: string }>
}

export function aiTokenFeatureStatus() {
  return request({ url: '/api/ai/token/feature_status', method: 'get' }) as
    Promise<{ ok: boolean; data?: TokenFeatureStatus[]; error?: string }>
}

export function aiTokenRecentCalls(limit = 50) {
  return request({ url: '/api/ai/token/recent_calls', method: 'get', params: { limit } }) as
    Promise<{ ok: boolean; data?: TokenRecentCall[]; error?: string }>
}

export function aiTokenUpdateFeature(feature: string, params: { enabled?: boolean; daily_token_budget?: number | null }) {
  return request({ url: '/api/ai/token/update_feature', method: 'post', data: { feature, ...params } }) as
    Promise<{ ok: boolean; error?: string }>
}
