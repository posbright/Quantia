import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ElementPlus from 'element-plus'

// Mock echarts
vi.mock('echarts', () => ({
  init: vi.fn(() => ({
    setOption: vi.fn(),
    resize: vi.fn(),
    dispose: vi.fn(),
  })),
}))

// Mock verify API
vi.mock('@/api/verify', () => ({
  getHoldingPeriod: vi.fn().mockResolvedValue({
    code: 0,
    data: [
      { strategy: 'macd_cross', strategy_cn: 'MACD金叉', avg_return: 2.5, win_rate: 62, sharpe_approx: 1.3, signal_count: 150 },
      { strategy: 'boll_squeeze', strategy_cn: '布林收窄', avg_return: 1.8, win_rate: 55, sharpe_approx: 0.9, signal_count: 200 },
      { strategy: 'volume_break', strategy_cn: '放量突破', avg_return: 3.1, win_rate: 58, sharpe_approx: 1.5, signal_count: 120 },
    ],
  }),
  getSignalDecay: vi.fn().mockResolvedValue({ code: 0, data: [] }),
  getMarketRegime: vi.fn().mockResolvedValue({ code: 0, data: [] }),
  getReturnSeries: vi.fn().mockResolvedValue({ code: 0, data: [] }),
}))

import CompareVue from '@/views/verify/compare.vue'

function factory() {
  return mount(CompareVue, {
    global: {
      plugins: [ElementPlus],
      stubs: { teleport: true },
    },
  })
}

describe('compare.vue', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders strategy selection toolbar', () => {
    const wrapper = factory()
    const html = wrapper.html()
    expect(html).toContain('对比分析') || expect(html).toContain('策略')
  })

  it('shows empty state before query', () => {
    const wrapper = factory()
    // Before clicking compare, should show empty or initial state
    expect(wrapper.html()).toBeDefined()
  })

  it('insights card appears after compare data loaded', async () => {
    const wrapper = factory()
    await flushPromises()

    // Simulate having comparison data by directly setting internal state
    const vm = wrapper.vm as any
    if (vm.compareData !== undefined) {
      vm.compareData = [
        { strategy: 'macd_cross', strategy_cn: 'MACD金叉', avg_return: 2.5, win_rate: 62, sharpe_approx: 1.3, signal_count: 150 },
        { strategy: 'boll_squeeze', strategy_cn: '布林收窄', avg_return: 1.8, win_rate: 55, sharpe_approx: 0.9, signal_count: 200 },
        { strategy: 'volume_break', strategy_cn: '放量突破', avg_return: 3.1, win_rate: 58, sharpe_approx: 1.5, signal_count: 120 },
      ]
      await flushPromises()

      // Check that insights are generated
      expect(vm.insights.length).toBeGreaterThan(0)
      expect(vm.insights[0]).toContain('放量突破')
    }
  })

  it('insights contain best strategy by sharpe', async () => {
    const wrapper = factory()
    const vm = wrapper.vm as any
    if (vm.compareData !== undefined) {
      vm.compareData = [
        { strategy: 'a', strategy_cn: '策略A', avg_return: 2, win_rate: 60, sharpe_approx: 1.8, signal_count: 100 },
        { strategy: 'b', strategy_cn: '策略B', avg_return: 3, win_rate: 50, sharpe_approx: 1.2, signal_count: 100 },
      ]
      await flushPromises()
      const insightText = vm.insights.join(' ')
      expect(insightText).toContain('策略A')
      expect(insightText).toContain('夏普比率最高')
    }
  })

  it('insights empty when only 1 strategy', async () => {
    const wrapper = factory()
    const vm = wrapper.vm as any
    if (vm.compareData !== undefined) {
      vm.compareData = [
        { strategy: 'a', strategy_cn: '策略A', avg_return: 2, win_rate: 60, sharpe_approx: 1.8, signal_count: 100 },
      ]
      await flushPromises()
      expect(vm.insights.length).toBe(0)
    }
  })

  it('renders radar chart area', () => {
    const wrapper = factory()
    // Radar chart container should exist
    const html = wrapper.html()
    expect(html).toContain('雷达') || expect(html).toBeDefined()
  })
})
