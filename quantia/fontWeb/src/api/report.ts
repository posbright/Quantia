import request from './request'

// ---- Interfaces ----

export interface StockSearchItem {
  code: string
  name: string
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
  report?: ReportDetail
  report_id?: number
  tokens_used?: number
  latency_ms?: number
  msg?: string
}

// ---- API functions ----

/**
 * 搜索股票（autocomplete）
 */
export function searchStock(q: string) {
  return request.get<{ items: StockSearchItem[] }>(
    '/quantia/api/ai/report/search_stock', { params: { q } }
  )
}

/**
 * 获取历史报告列表
 */
export function getReportHistory(params: { code?: string; limit?: number; offset?: number }) {
  return request.get<{ items: ReportHistoryItem[] }>(
    '/quantia/api/ai/report/history', { params }
  )
}

/**
 * 获取单条报告详情
 */
export function getReportDetail(id: number) {
  return request.get<ReportDetail>(
    '/quantia/api/ai/report/detail', { params: { id } }
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
