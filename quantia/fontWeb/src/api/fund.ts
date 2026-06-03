import request from './request'

// ── 场外开放式基金排名（F6 方案 A）──────────────────────────────────

export interface FundPeriodOption {
  value: string
  label: string
}

export interface FundRankMeta {
  fund_types: string[]
  periods: FundPeriodOption[]
  default_period: string
  default_limit: number
  latest_date: string | null
}

export interface FundRankItem {
  code: string
  name: string
  fund_type: string
  nav_date: string | null
  unit_nav: number | null
  acc_nav: number | null
  day_growth: number | null
  million_unit_income: number | null
  seven_day_annual: number | null
  rate_1w: number | null
  rate_1m: number | null
  rate_3m: number | null
  rate_6m: number | null
  rate_1y: number | null
  rate_2y: number | null
  rate_3y: number | null
  rate_ytd: number | null
  rate_since: number | null
  fee: number | null
  main_industry?: string | null
  // 评分表派生（净值型桶，JOIN cn_fund_rank_score）
  score?: number | null
  sharpe?: number | null
  max_drawdown?: number | null
  rate_5y?: number | null
  excess_1y?: number | null
  rank_in_type?: number | null
  // 画像表派生（JOIN cn_fund_profile）
  scale_yi?: number | null
  rating?: string | null
}

export interface FundRankResult {
  date: string | null
  fund_type: string
  period: string
  industry?: string | null
  count: number
  items: FundRankItem[]
}

export interface FundIndustriesResult {
  fund_type: string
  supported: boolean
  industries: string[]
}

export function getFundRankMeta() {
  return request<FundRankMeta>({
    url: '/api/fund/rank/meta',
    method: 'get',
  })
}

export function getFundRank(params: {
  fund_type: string
  period: string
  limit?: number
  industry?: string
}) {
  return request<FundRankResult>({
    url: '/api/fund/rank',
    method: 'get',
    params,
  })
}

export function getFundRankIndustries(fund_type: string) {
  return request<FundIndustriesResult>({
    url: '/api/fund/rank/industries',
    method: 'get',
    params: { fund_type },
  })
}

// ── 同类评比（F11，五维雷达）─────────────────────────────────────────

export interface FundPeerDim {
  key: string
  label: string
  value: number | null
  peer: number
}

export interface FundPeerCompare {
  code: string
  name: string | null
  fund_type: string | null
  industry?: string | null
  peer_count: number
  dims: FundPeerDim[]
  percentiles: Record<string, number | null>
  value_labels: string[]
  disclaimer: string
}

export function getFundPeerCompare(code: string, industry?: string) {
  return request<FundPeerCompare>({
    url: '/api/fund/peer_compare',
    method: 'get',
    params: industry ? { code, industry } : { code },
  })
}

// ── 综合分析（F13，规则引擎，非投资建议）──────────────────────────────

export interface FundComposite {
  code: string
  name: string | null
  fund_type: string | null
  data_date: string | null
  performance: {
    rate_1y: number | null
    rate_3y: number | null
    rate_5y: number | null
    sharpe: number | null
    max_drawdown: number | null
    excess_1y: number | null
    sharpe_pct: number | null
    drawdown_pct: number | null
    texts: string[]
  }
  concentration: { top10_sum: number | null; level: string; text: string }
  industry: {
    main_industry: string | null
    distribution: { industry: string; ratio: number }[]
    text: string | null
  }
  style: { fund_type_detail: string | null; text: string }
  scale: { scale_yi: number | null; setup_date: string | null; years: number | null; texts: string[] }
  profile?: {
    company: string | null
    manager: string | null
    rating: string | null
    fund_type_detail: string | null
    strategy: string | null
    objective: string | null
    benchmark: string | null
    setup_date: string | null
  }
  holdings?: {
    quarter: string | null
    top: { name: string; stock_code: string | null; industry: string; hold_ratio: number | null }[]
  }
  risk_level: string
  summary: string
  disclaimer: string
}

export function getFundCompositeAnalysis(code: string) {
  return request<FundComposite>({
    url: '/api/fund/composite_analysis',
    method: 'get',
    params: { code },
  })
}

// ── 净值曲线（F9 §9.3，读 cn_fund_nav_history）────────────────

export interface FundNavPoint {
  date: string
  unit_nav: number | null
  acc_nav: number | null
}

export interface FundNavHistory {
  code: string
  name: string | null
  range: string
  count: number
  points: FundNavPoint[]
}

export function getFundNavHistory(code: string, range = '1y') {
  return request<FundNavHistory>({
    url: '/api/fund/nav_history',
    method: 'get',
    params: { code, range },
  })
}

// 同类平均净值增长基线（§9.3 叠加对比看超额）
export interface FundNavPeerPoint {
  date: string
  growth: number
}

export interface FundNavPeer {
  code: string
  fund_type: string | null
  range: string
  peer_count: number
  count: number
  points: FundNavPeerPoint[]
}

export function getFundNavPeer(code: string, range = '1y') {
  return request<FundNavPeer>({
    url: '/api/fund/nav_peer',
    method: 'get',
    params: { code, range },
  })
}

// ── AI 按需分析（F14，懒加载 LLM）──────────────────────────────────

export interface FundAiSource {
  title: string
  url: string
}

export interface FundAiAnalysis {
  code: string
  name: string | null
  data_date: string | null
  cached: boolean
  ai_available: boolean
  content: string
  sources: FundAiSource[]
  model?: string
  note?: string
  rounds?: number
  total_tokens?: number | null
  composite: FundComposite
}

/** 仅查缓存（未命中 ai_available=false，但附带规则化 composite） */
export function getFundAiAnalysis(code: string) {
  return request<FundAiAnalysis>({
    url: '/api/fund/ai_analysis',
    method: 'get',
    params: { code },
  })
}

/** 触发 AI 分析（命中缓存直接返回；refresh=true 强制重算） */
export function runFundAiAnalysis(code: string, refresh = false) {
  return request<FundAiAnalysis>({
    url: '/api/fund/ai_analysis',
    method: 'post',
    data: { code, refresh },
  })
}
