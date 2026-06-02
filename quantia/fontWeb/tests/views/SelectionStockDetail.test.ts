import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createWebHistory } from 'vue-router'
import SelectionStockDetail from '@/views/selection/detail.vue'

vi.mock('@/api/selectionScore', () => ({
  getSelectionScoreDetail: vi.fn(() => Promise.resolve({
    date_effective: '2026-06-02',
    item: {
      code: '000001',
      name: '平安银行',
      industry: '银行',
      rating: 'A',
      display_score: 81.2,
      quality_score: 76.4,
      industry_score: 70.2,
      industry_rank: 1,
      industry_total: 42,
      score_valuation: 68,
      score_profitability: 82,
      score_growth: 63,
      score_health: 77,
      score_capital: 71,
      score_technical: 66,
      score_sentiment: 60,
      tags: ['高分红', '低波动'],
      risk_flags: ['rank_change_not_comparable'],
    },
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
    { path: '/selection/detail/:code', component: SelectionStockDetail },
  ],
})

describe('SelectionStockDetail M5 页面', () => {
  it('渲染个股评分详情核心信息', async () => {
    await router.push('/selection/detail/000001')
    await router.isReady()
    const wrapper = mount(SelectionStockDetail, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('平安银行')
    expect(wrapper.text()).toContain('七维雷达')
    expect(wrapper.text()).toContain('分数归因')
    expect(wrapper.text()).toContain('亮点标签')
    expect(wrapper.text()).toContain('风险标签')
  })
})
