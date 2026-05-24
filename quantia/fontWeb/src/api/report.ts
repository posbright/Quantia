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
