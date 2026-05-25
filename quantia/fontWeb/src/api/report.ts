import request from './request'

// ---- Interfaces ----

export interface StockSearchItem {
  code: string
  name: string
  industry?: string
}

export interface ReportHistoryItem {
  id: number
  code: string
  name: string
  model: string
  tokens_used: number
  latency_ms: number
  created_at: string
}

export interface ReportDetail {
  id: number
  code: string
  name: string
  report_md: string
  model: string
  provider: string
  tools_used: string[]
  tokens_used: number
  latency_ms: number
  created_at: string
}

export interface ReportStreamEvent {
  type: 'progress' | 'chunk' | 'cached' | 'done' | 'error'
  step?: string
  status?: string
  elapsed_ms?: number
  text?: string
  report?: ReportDetail & { data_updated?: boolean; update_reason?: string }
  report_id?: number
  tokens_used?: number
  latency_ms?: number
  msg?: string
}

export interface FollowupStreamEvent {
  type: 'chunk' | 'done' | 'error'
  text?: string
  msg?: string
}

export interface StockFallbackData {
  code: string
  name?: string
  spot?: {
    name: string
    close: number
    change_pct: number
    pe: number
    pb: number
    roe: number
    bps: number
    eps: number
    market_cap: number
    turnover: number
  }
  fund_flow?: { date: string; main: number; super: number; big: number }[]
  indicators?: {
    macd: number
    macd_signal: number
    kdj_k: number
    kdj_d: number
    kdj_j: number
    rsi_6: number
  }
}

// ---- API functions ----

/**
 * 搜索股票（autocomplete）
 */
export function searchStock(q: string) {
  return request.get<{ items: StockSearchItem[] }>(
    '/api/ai/report/search_stock', { params: { q } }
  )
}

/**
 * 获取历史报告列表
 */
export function getReportHistory(params: { code?: string; limit?: number; offset?: number }) {
  return request.get<{ items: ReportHistoryItem[] }>(
    '/api/ai/report/history', { params }
  )
}

/**
 * 获取单条报告详情
 */
export function getReportDetail(id: number) {
  return request.get<ReportDetail>(
    '/api/ai/report/detail', { params: { id } }
  )
}

/**
 * SSE 流式生成报告
 */
export async function generateReportStream(
  code: string,
  onEvent: (ev: ReportStreamEvent) => void,
  options?: { force?: boolean; signal?: AbortSignal }
): Promise<void> {
  const resp = await fetch('/quantia/api/ai/report/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({ code, force: options?.force || false }),
    signal: options?.signal,
  })
  if (!resp.ok) {
    const text = await resp.text()
    onEvent({ type: 'error', msg: text || `HTTP ${resp.status}` })
    return
  }
  const reader = resp.body!.getReader()
  const decoder = new TextDecoder('utf-8')
  let buf = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    let idx: number
    while ((idx = buf.indexOf('\n\n')) !== -1) {
      const raw = buf.slice(0, idx).trim()
      buf = buf.slice(idx + 2)
      if (!raw.startsWith('data:')) continue
      try {
        const ev: ReportStreamEvent = JSON.parse(raw.slice(5).trim())
        onEvent(ev)
      } catch {
        // skip malformed events
      }
    }
  }
}

/**
 * SSE 流式追问
 */
export async function followupReportStream(
  code: string,
  question: string,
  reportMd: string,
  onEvent: (ev: FollowupStreamEvent) => void,
  options?: { signal?: AbortSignal }
): Promise<void> {
  const resp = await fetch('/quantia/api/ai/report/followup', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({ code, question, report_md: reportMd }),
    signal: options?.signal,
  })
  if (!resp.ok) {
    const text = await resp.text()
    onEvent({ type: 'error', msg: text || `HTTP ${resp.status}` })
    return
  }
  const reader = resp.body!.getReader()
  const decoder = new TextDecoder('utf-8')
  let buf = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    let idx: number
    while ((idx = buf.indexOf('\n\n')) !== -1) {
      const raw = buf.slice(0, idx).trim()
      buf = buf.slice(idx + 2)
      if (!raw.startsWith('data:')) continue
      try {
        const ev: FollowupStreamEvent = JSON.parse(raw.slice(5).trim())
        onEvent(ev)
      } catch {
        // skip malformed events
      }
    }
  }
}

/**
 * 提交报告反馈 (👍/👎)
 */
export function submitReportFeedback(reportId: number, feedback: 1 | -1, reason?: string) {
  return request.post('/api/ai/report/feedback', {
    report_id: reportId,
    feedback,
    reason: reason || '',
  })
}

/**
 * 获取快速结构化数据（AI 不可用时的 fallback 面板）
 */
export function getStockFallbackData(code: string) {
  return request.get<StockFallbackData>('/api/ai/report/stock_data', { params: { code } })
}

// ---- Score History & Timeline (Phase 3) ----

export interface ScoreHistoryItem {
  date: string
  score: number | null
  action: string
  reason: string
  phase: string
}

export interface ReportTimelineItem {
  id: number
  created_at: string
  model: string
  tokens_used: number
  latency_ms: number
  rating?: string
  summary?: string
}

/**
 * AI评分历史趋势（近N天评分变化）
 */
export function getScoreHistory(code: string, days?: number) {
  return request.get<{ items: ScoreHistoryItem[]; code: string; days: number }>(
    '/api/ai/report/score_history', { params: { code, days: days || 30 } }
  )
}

/**
 * 同股票报告版本时间线
 */
export function getReportTimeline(code: string) {
  return request.get<{ items: ReportTimelineItem[]; code: string }>(
    '/api/ai/report/timeline', { params: { code } }
  )
}

// ---- Export & Share (Phase 3c) ----

export interface ShareResult {
  share_token: string
  share_url: string
}

/**
 * 生成分享链接
 */
export function createShareLink(reportId: number) {
  return request.post<ShareResult>('/api/ai/report/share', { report_id: reportId })
}

// ---- Batch Analysis (§10.6) ----

export interface AttentionListItem {
  code: string
  name: string
}

export interface BatchSummaryEvent {
  type: 'start' | 'item' | 'done'
  total?: number
  code?: string
  name?: string
  summary?: string
  rating?: string
  tokens_used?: number
  latency_ms?: number
  error?: boolean
}

/**
 * 获取关注列表
 */
export function getAttentionList() {
  return request.get<{ items: AttentionListItem[]; count: number }>(
    '/api/ai/report/attention_list'
  )
}

/**
 * SSE 批量摘要生成（关注列表）
 */
export async function batchSummaryStream(
  codes: string[],
  onEvent: (ev: BatchSummaryEvent) => void,
  options?: { signal?: AbortSignal }
): Promise<void> {
  const resp = await fetch('/quantia/api/ai/report/batch_summary', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({ codes }),
    signal: options?.signal,
  })
  if (!resp.ok) {
    const text = await resp.text()
    onEvent({ type: 'done' })
    throw new Error(text || `HTTP ${resp.status}`)
  }
  const reader = resp.body!.getReader()
  const decoder = new TextDecoder('utf-8')
  let buf = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    let idx: number
    while ((idx = buf.indexOf('\n\n')) !== -1) {
      const raw = buf.slice(0, idx).trim()
      buf = buf.slice(idx + 2)
      if (!raw.startsWith('data:')) continue
      try {
        const ev: BatchSummaryEvent = JSON.parse(raw.slice(5).trim())
        onEvent(ev)
      } catch {
        // skip malformed
      }
    }
  }
}

// ---- Phase 4: Report Comparison ----

export interface CompareResult {
  type: 'progress' | 'done' | 'error'
  report_md?: string
  codes?: string[]
  tokens_used?: number
  model?: string
  msg?: string
}

/**
 * SSE 流式对比报告
 */
export async function compareReportStream(
  codes: [string, string],
  onEvent: (ev: CompareResult) => void,
  options?: { signal?: AbortSignal }
): Promise<void> {
  const resp = await fetch('/quantia/api/ai/report/compare', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({ codes }),
    signal: options?.signal,
  })
  if (!resp.ok) {
    const text = await resp.text()
    onEvent({ type: 'error', msg: text || `HTTP ${resp.status}` })
    return
  }
  const reader = resp.body!.getReader()
  const decoder = new TextDecoder('utf-8')
  let buf = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    let idx: number
    while ((idx = buf.indexOf('\n\n')) !== -1) {
      const raw = buf.slice(0, idx).trim()
      buf = buf.slice(idx + 2)
      if (!raw.startsWith('data:')) continue
      try {
        const ev: CompareResult = JSON.parse(raw.slice(5).trim())
        onEvent(ev)
      } catch {
        // skip
      }
    }
  }
}

// ---- Phase 4: User Preferences ----

export interface ReportPreference {
  focus_dimensions: string[]
  language: 'zh' | 'en'
  voice_enabled: boolean
  alert_threshold: number
  auto_report: boolean
  push_enabled: boolean
}

/**
 * 获取用户报告偏好
 */
export function getReportPreference(userId?: string) {
  return request.get<ReportPreference>(
    '/api/ai/report/preference', { params: { user_id: userId || 'default' } }
  )
}

/**
 * 保存用户报告偏好
 */
export function saveReportPreference(pref: Partial<ReportPreference> & { user_id?: string }) {
  return request.post<{ ok: boolean }>('/api/ai/report/preference', pref)
}

// ---- Phase 4: Multi-language Translation ----

export interface TranslateResult {
  translated_md: string
  language: string
}

/**
 * 翻译报告为英文
 */
export function translateReport(params: { report_id?: number; report_md?: string }) {
  return request.post<TranslateResult>('/api/ai/report/translate', params)
}

// ---- Phase 4: Voice Broadcast ----

export interface SpeechTextResult {
  speech_text: string
  estimated_duration_sec: number
  char_count: number
}

/**
 * 获取报告语音播报文本
 */
export function getSpeechText(params: { report_id?: number; report_md?: string }) {
  return request.post<SpeechTextResult>('/api/ai/report/speech_text', params)
}
