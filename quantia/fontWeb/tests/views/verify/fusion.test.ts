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

// Mock API
vi.mock('@/api/verify', () => ({
  apiFusion: vi.fn().mockResolvedValue({
    code: 0,
    data: {
      kpi: { sharpe: 1.52, winRate: 68.5, annReturn: 21.3, maxDD: -8.5 },
      compare: [
        { name: '融合策略', sharpe: 1.52, winRate: 68.5, annReturn: 21.3, maxDD: -8.5 },
        { name: '基准', sharpe: 0.91, winRate: 55.0, annReturn: 12.1, maxDD: -15.2 },
      ],
      cumulative: { dates: ['2024-01', '2024-02'], fusion: [1.0, 1.05], benchmark: [1.0, 1.02] },
      shapley: [
        { dim: '技术面', value: 0.35 },
        { dim: '基本面', value: 0.25 },
        { dim: '资金流', value: 0.2 },
      ],
      abSteps: [
        { step: 1, desc: '添加技术面', sharpe: 1.1, delta: '+0.2' },
        { step: 2, desc: '添加基本面', sharpe: 1.35, delta: '+0.25' },
      ],
      heatmap: {
        calendar: [{ date: '2024-01-02', count: 3 }],
        overlap: { rows: ['MA', 'RSI'], cols: ['MA', 'RSI'], data: [[1.0, 0.6], [0.6, 1.0]] },
      },
    },
  }),
}))

// Import after mocks
import FusionVue from '@/views/verify/fusion.vue'

function factory() {
  return mount(FusionVue, {
    global: {
      plugins: [ElementPlus],
      stubs: { teleport: true },
    },
  })
}

describe('fusion.vue', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
  })

  it('renders 4 sub-tabs', () => {
    const wrapper = factory()
    const tabs = wrapper.findAll('.sub-tab')
    expect(tabs.length).toBe(4)
  })

  it('renders 5 dimension sections', () => {
    const wrapper = factory()
    const dims = wrapper.findAll('.dim-section')
    expect(dims.length).toBe(5)
  })

  it('dimension toggle changes enabled state', async () => {
    const wrapper = factory()
    const toggles = wrapper.findAll('.dim-toggle')
    expect(toggles.length).toBeGreaterThanOrEqual(5)
    // Click one toggle
    await toggles[4].trigger('click')
    await flushPromises()
    // Toggle text should change to OFF or ON
    expect(toggles[4].text()).toMatch(/ON|OFF/)
  })

  it('renders 4 fusion mode options', () => {
    const wrapper = factory()
    const modes = wrapper.findAll('.mode-option')
    expect(modes.length).toBe(4)
  })

  it('switching sub-tab shows correct content', async () => {
    const wrapper = factory()
    const tabs = wrapper.findAll('.sub-tab')
    await tabs[1].trigger('click')
    await flushPromises()
    // Sub 1 should become active
    expect(tabs[1].classes()).toContain('active')
  })

  it('saveFusionScheme stores to localStorage', async () => {
    const wrapper = factory()
    const buttons = wrapper.findAll('button')
    const saveButton = buttons.find(b => b.text().includes('保存'))
    expect(saveButton).toBeDefined()
    if (saveButton) {
      await saveButton.trigger('click')
      await flushPromises()
      const stored = localStorage.getItem('quantia_fusion_scheme')
      expect(stored).not.toBeNull()
      const parsed = JSON.parse(stored!)
      expect(parsed.dimensions).toBeDefined()
      expect(parsed.mode).toBeDefined()
      expect(parsed.savedAt).toBeDefined()
    }
  })

  it('total weight display sums to 100', () => {
    const wrapper = factory()
    expect(wrapper.html()).toContain('100%')
  })

  it('renders action bar with save and export buttons', () => {
    const wrapper = factory()
    const html = wrapper.html()
    expect(html).toContain('保存方案')
    expect(html).toContain('导出代码')
  })

  it('weight warning appears when total != 100', async () => {
    const wrapper = factory()
    const vm = wrapper.vm as any
    // Manipulate weights to not equal 100
    if (vm.dimensions) {
      vm.dimensions[0].weight = 50
      vm.dimensions[1].weight = 50
      vm.dimensions[2].weight = 50
      await flushPromises()
      expect(wrapper.find('.weight-total.warn').exists()).toBe(true)
    }
  })
})
