import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, vi } from 'vitest'
import FundDailyPickTab from '@/views/fund/FundDailyPickTab.vue'

vi.mock('@/api/fund', () => ({
  getFundDailyPick: vi.fn(async () => ({
    date: '2026-07-09',
    score_as_of: '2026-07-09',
    disclaimer: '仅供测试',
    buckets: [
      {
        fund_type: '混合型',
        timing_applicable: true,
        has_timing: true,
        picks: [
          {
            rank_in_type: 1,
            code: '021523',
            name: '财通价值动量混合C',
            quality_score: 95.9,
            timing_score: 80,
            timing_tier: '定投',
            final_score: 95.9,
            max_drawdown: -0.3785,
            rate_1y: 313.46,
            nav_as_of: '2026-07-09',
            data_lag_days: 0,
          },
        ],
      },
      {
        fund_type: '债券型',
        timing_applicable: true,
        has_timing: true,
        picks: [
          {
            rank_in_type: 1,
            code: '000001',
            name: '测试债券基金',
            quality_score: 88.1,
            timing_score: 60,
            timing_tier: '观望',
            final_score: 88.1,
            max_drawdown: -0.021,
            rate_1y: 4.2,
            nav_as_of: '2026-07-09',
            data_lag_days: 0,
          },
        ],
      },
    ],
  })),
}))

vi.mock('@/composables/useResponsive', () => ({
  useResponsive: () => ({ isMobile: { value: false } }),
}))

describe('FundDailyPickTab', () => {
  it('uses parent fund type and does not render duplicate type capsules', async () => {
    const wrapper = mount(FundDailyPickTab, {
      props: { fundType: '债券型' },
    })

    await flushPromises()

    expect(wrapper.find('.pick-capsules').exists()).toBe(false)
    expect(wrapper.text()).toContain('测试债券基金')
    expect(wrapper.text()).not.toContain('财通价值动量混合C')
  })
})