import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createWebHistory } from 'vue-router'
import SelectionScoreHome from '@/views/selection/all.vue'

vi.mock('@/api/selectionScore', () => ({
  getSelectionScoreList: vi.fn(() => Promise.resolve({
    date_effective: '2026-06-02',
    api_contract_version: 'm3.8',
    total: 2,
    items: [
      { code: '000001', name: '平安银行', industry: '银行', display_score: 81.2, quality_score: 76.5, rating: 'A' },
      { code: '600036', name: '招商银行', industry: '银行', display_score: 79.6, quality_score: 77.1, rating: 'A' },
    ],
  })),
  getSelectionScoreIndustries: vi.fn(() => Promise.resolve({
    count: 1,
    items: [
      { industry: '银行', avg_display_score: 80.4, stock_count: 2, leader_name: '平安银行' },
    ],
  })),
  getSelectionScoreTop: vi.fn(() => Promise.resolve({
    items: [
      { code: '000001', name: '平安银行', quality_score: 76.5, display_score: 81.2 },
    ],
  })),
}))

describe('SelectionScoreHome M4 页面', () => {
  const router = createRouter({
    history: createWebHistory(),
    routes: [
      { path: '/selection/all', component: SelectionScoreHome },
      { path: '/selection/industry/:name', component: { template: '<div>industry</div>' } },
      { path: '/selection/detail/:code', component: { template: '<div>detail</div>' } },
    ],
  })

  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('渲染标题与核心区块', async () => {
    await router.push('/selection/all')
    await router.isReady()
    const wrapper = mount(SelectionScoreHome, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('综合选股评分榜')
    expect(wrapper.text()).toContain('全市场 Top10')
    expect(wrapper.text()).toContain('行业宫格')
    expect(wrapper.text()).toContain('评分列表')
  })

  it('渲染列表与行业数据', async () => {
    await router.push('/selection/all')
    await router.isReady()
    const wrapper = mount(SelectionScoreHome, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('平安银行')
    expect(wrapper.text()).toContain('银行')
    expect(wrapper.text()).toContain('股票总数')
  })
})
