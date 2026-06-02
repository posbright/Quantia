import request from './request'

export interface SelectionScoreListParams {
  date?: string
  industry?: string
  rating?: string
  min_quality?: number
  template?: string
  sort?: string
  page?: number
  page_size?: number
}

export interface SelectionScoreIndustriesParams {
  date?: string
  min_quality?: number
  template?: string
}

export interface SelectionScoreTopParams {
  date?: string
  n?: number
}

export function getSelectionScoreList(params: SelectionScoreListParams) {
  return request({
    url: '/api/selection/score/list',
    method: 'get',
    params,
  })
}

export function getSelectionScoreIndustries(params: SelectionScoreIndustriesParams) {
  return request({
    url: '/api/selection/score/industries',
    method: 'get',
    params,
  })
}

export function getSelectionScoreTop(params: SelectionScoreTopParams) {
  return request({
    url: '/api/selection/score/top',
    method: 'get',
    params,
  })
}
