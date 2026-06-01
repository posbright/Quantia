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
}

export interface FundRankResult {
  date: string | null
  fund_type: string
  period: string
  count: number
  items: FundRankItem[]
}

export function getFundRankMeta() {
  return request<FundRankMeta>({
    url: '/api/fund/rank/meta',
    method: 'get',
  })
}

export function getFundRank(params: { fund_type: string; period: string; limit?: number }) {
  return request<FundRankResult>({
    url: '/api/fund/rank',
    method: 'get',
    params,
  })
}
