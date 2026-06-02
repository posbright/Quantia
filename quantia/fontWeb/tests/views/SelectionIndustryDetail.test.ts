import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createWebHistory } from 'vue-router'
import SelectionIndustryDetail from '@/views/selection/industry.vue'

vi.mock('@/api/selectionScore', () => ({
  getSelectionScoreList: vi.fn(() => Promise.resolve({
    date_effective: '2026-06-02',
    total: 2,
    items: [
      {
        code: '000001',
        name: '平安银行',
        display_score: 81.5,
        quality_score: 77.2,
        rating: 'A',
        industry_rank: 1,
        score_valuation: 68,
        score_profitability: 82,
        score_growth: 63,
        score_health: 77,
        score_capital: 71,
        score_technical: 66,
        score_sentiment: 60,
      },
      {
        code: '600036',
        name: '招商银行',
        display_score: 79.2,
        quality_score: 76.8,
        rating: 'A',
        industry_rank: 2,
        score_valuation: 66,
        score_profitability: 81,
        score_growth: 61,
        score_health: 76,
        score_capital: 72,
        score_technical: 64,
        score_sentiment: 59,
      },
    ],
  })),
  getSelectionScoreIndustries: vi.fn(() => Promise.resolve({
    items: [
      {
        industry: '银行',
        avg_display_score: 80.35,
        leader_name: '平安银行',
        comparable_ratio: 1,
      },
    ],
  })),
}))

vi.mock('echarts', () => ({
  default: {},
  init: vi.fn(() => ({ setOption: vi.fn(), dispose: vi.fn() })),
}))

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/selection/all', component: { template: '<div>all</div>' } },
    { path: '/selection/industry/:name', component: SelectionIndustryDetail },
  ],
})

describe('SelectionIndustryDetail M5 页面', () => {
  it('渲染行业详情核心信息', async () => {
    await router.push('/selection/industry/%E9%93%B6%E8%A1%8C')
    await router.isReady()
    const wrapper = mount(SelectionIndustryDetail, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('银行评分榜')
    expect(wrapper.text()).toContain('行业概览')
    expect(wrapper.text()).toContain('行业内股票列表')
    expect(wrapper.text()).toContain('平安银行')
  })
})
