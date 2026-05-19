import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ElementPlus from 'element-plus'

// ── Mocks ─────────────────────────────────────────────────────────────

vi.mock('echarts', () => ({
  init: vi.fn(() => ({
    setOption: vi.fn(),
    resize: vi.fn(),
    dispose: vi.fn(),
    getOption: vi.fn(),
  })),
  getInstanceByDom: vi.fn(() => null),
  dispose: vi.fn(),
}))

// Mock for @/api/verify (runFusion is the exported function)
const runFusionMock = vi.fn().mockResolvedValue({
  version: 2,
  mode: 'weighted_score',
  holding_days: 10,
  period: { start: '2025-01-01', end: '2025-12-31' },
  fusion_result: { sharpe: 1.87, win_rate: 60, daily_signal_avg: 3.5, max_drawdown: -8.2, signal_count: 842, avg_return: 1.2 },
  individual_results: {
    tech: { cn: '技术信号', sharpe: 1.2, win_rate: 55, max_drawdown: -12.5, signal_count: 2850, avg_return: 0.8 },
    fund: { cn: '基本面', sharpe: 1.0, win_rate: 52, max_drawdown: -10.1, signal_count: 1420, avg_return: 0.5 },
  },
  daily_series: [
    { date: '2025-09-01', cumulative: 0, drawdown: 0 },
    { date: '2025-09-02', cumulative: 1.2, drawdown: -0.5 },
  ],
  shapley: [
    { dim: 'tech', name: '技术信号', contrib: 0.45 },
    { dim: 'fund', name: '基本面', contrib: 0.32 },
  ],
  ab_steps: [
    { step: 1, dims: ['tech'], label: '技术信号', sharpe: 1.2, win_rate: 55, max_drawdown: -12.5, signal_count: 2850 },
    { step: 2, dims: ['tech', 'fund'], label: '技术信号 + 基本面', sharpe: 1.87, win_rate: 60, max_drawdown: -8.2, signal_count: 842 },
  ],
  overlap: {
    calendar: [
      { date: '2025-09-01', signal_count: 12, dims_hit: 2 },
      { date: '2025-09-02', signal_count: 18, dims_hit: 2 },
    ],
    co_occurrence: [
      { a: 'tech', b: 'tech', jaccard: 1.0 },
      { a: 'tech', b: 'fund', jaccard: 0.42 },
      { a: 'fund', b: 'tech', jaccard: 0.42 },
      { a: 'fund', b: 'fund', jaccard: 1.0 },
    ],
  },
  improvement: { sharpe_vs_best_single: '+55.8%', drawdown_vs_worst_single: '+18.8%' },
  warnings: [],
  diagnostics: { enabled_dims: ['tech', 'fund'] },
})
vi.mock('@/api/verify', () => ({
  runFusion: (...args: any[]) => runFusionMock(...args),
  getVerifyStrategyList: (...args: any[]) => getStrategyListMock(...args),
  exportFusionCodeApi: (...args: any[]) => exportFusionCodeMock(...args),
  saveFusionSchemeApi: (...args: any[]) => saveFusionSchemeMock(...args),
}))

const getStrategyListMock = vi.fn().mockResolvedValue({ groups: [] })
const exportFusionCodeMock = vi.fn().mockResolvedValue({ code: '# fake', length: 6 })
const saveFusionSchemeMock = vi.fn().mockResolvedValue({ id: 1, message: '已保存' })

// Mock for @/api/request (legacy; no longer used by fusion.vue but kept to avoid import errors)
const requestMock = vi.fn().mockResolvedValue([])
vi.mock('@/api/request', () => ({
  default: (...args: any[]) => requestMock(...args),
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

describe('fusion.vue v2', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    runFusionMock.mockClear()
    requestMock.mockClear()
    requestMock.mockResolvedValue([])
    getStrategyListMock.mockClear()
    getStrategyListMock.mockResolvedValue({ groups: [] })
    exportFusionCodeMock.mockClear()
    saveFusionSchemeMock.mockClear()
    localStorage.clear()
  })

  it('renders 4 sub-tabs', () => {
    const wrapper = factory()
    expect(wrapper.findAll('.sub-tab').length).toBe(4)
  })

  it('renders 5 dimension sections', () => {
    const wrapper = factory()
    expect(wrapper.findAll('.dim-section').length).toBe(5)
  })

  it('renders 4 fusion mode options', () => {
    const wrapper = factory()
    expect(wrapper.findAll('.mode-option').length).toBe(4)
  })

  it('renders param bar with date / holding inputs', () => {
    const wrapper = factory()
    expect(wrapper.find('.param-bar').exists()).toBe(true)
    expect(wrapper.html()).toContain('回测区间')
    expect(wrapper.html()).toContain('持仓天数')
  })

  it('loads custom strategies on mount via /verify/strategy_list', async () => {
    getStrategyListMock.mockResolvedValueOnce({
      groups: [
        { label: '技术指标', category: 'tech', items: [] },
        {
          label: '用户自定义', category: 'custom',
          items: [
            { value: 'custom_7', label: '我的均线', custom_id: 7, backtest_count: 3 },
            { value: 'custom_9', label: '我的动量', custom_id: 9, backtest_count: 1 },
          ],
        },
      ],
    })
    const wrapper = factory()
    await flushPromises()
    const vm = wrapper.vm as any
    const customDim = vm.dimensions.find((d: any) => d.key === 'custom')
    expect(customDim.items.length).toBe(2)
    expect(customDim.items[0].id).toBe('custom_7')
    expect(customDim.items[0].label).toContain('我的均线')
  })

  it('runFusionBacktest sends v2 payload with all 5 dimensions', async () => {
    const wrapper = factory()
    await flushPromises()
    const vm = wrapper.vm as any
    // Ensure totalWeight = 100
    vm.dimensions[0].weight = 30
    vm.dimensions[1].weight = 25
    vm.dimensions[2].weight = 20
    vm.dimensions[3].weight = 15
    vm.dimensions[4].weight = 10
    vm.dimensions[4].enabled = true
    vm.dimensions[4].items = [{ id: 'cn_stock_strategy_custom_1', label: '自定义', checked: true }]
    await vm.runFusionBacktest()
    expect(runFusionMock).toHaveBeenCalledTimes(1)
    const payload = runFusionMock.mock.calls[0][0]
    expect(payload.version).toBe(2)
    expect(payload.mode).toBe('weighted_score')
    expect(payload.dimensions).toHaveProperty('tech')
    expect(payload.dimensions).toHaveProperty('fund')
    expect(payload.dimensions).toHaveProperty('flow')
    expect(payload.dimensions).toHaveProperty('sent')
    expect(payload.dimensions).toHaveProperty('custom')
    expect(payload.dimensions.tech.enabled).toBe(true)
    expect(payload.dimensions.tech.items.length).toBeGreaterThan(0)
  })

  it('passes mode through without legacy mapping', async () => {
    const wrapper = factory()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.fusionMode = 'condition_tree'
    vm.dimensions[0].weight = 30
    vm.dimensions[1].weight = 30
    vm.dimensions[2].weight = 25
    vm.dimensions[3].weight = 15
    vm.dimensions[4].enabled = false
    await vm.runFusionBacktest()
    expect(runFusionMock).toHaveBeenCalled()
    expect(runFusionMock.mock.calls[0][0].mode).toBe('condition_tree')
  })

  it('disabled dim is sent with enabled=false', async () => {
    const wrapper = factory()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.dimensions[3].enabled = false  // disable sent
    vm.dimensions[0].weight = 35
    vm.dimensions[1].weight = 35
    vm.dimensions[2].weight = 30
    vm.dimensions[3].weight = 0
    vm.dimensions[4].weight = 0
    vm.dimensions[4].enabled = false
    await vm.runFusionBacktest()
    const payload = runFusionMock.mock.calls[0][0]
    expect(payload.dimensions.sent.enabled).toBe(false)
  })

  it('does not call API when total weight != 100', async () => {
    const wrapper = factory()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.dimensions[0].weight = 60
    vm.dimensions[1].weight = 30
    vm.dimensions[2].weight = 20  // total = 110
    vm.dimensions[3].weight = 15
    vm.dimensions[4].weight = 10
    await vm.runFusionBacktest()
    expect(runFusionMock).not.toHaveBeenCalled()
  })

  it('bind backend fusion_result KPIs after run', async () => {
    const wrapper = factory()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.dimensions[0].weight = 30
    vm.dimensions[1].weight = 30
    vm.dimensions[2].weight = 25
    vm.dimensions[3].weight = 15
    vm.dimensions[4].enabled = false
    await vm.runFusionBacktest()
    await flushPromises()
    expect(vm.fusionResult.sharpe).toBe(1.87)
    expect(vm.fusionResult.signal_count).toBe(842)
    expect(vm.improvement.sharpe_vs_best_single).toBe('+55.8%')
  })

  it('binds shapley data from backend', async () => {
    const wrapper = factory()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.dimensions[0].weight = 30
    vm.dimensions[1].weight = 30
    vm.dimensions[2].weight = 25
    vm.dimensions[3].weight = 15
    vm.dimensions[4].enabled = false
    await vm.runFusionBacktest()
    await flushPromises()
    expect(vm.shapleyContribs.length).toBe(2)
    expect(vm.shapleyContribs[0].impact).toBeCloseTo(0.45, 2)
  })

  it('saveFusionScheme stores v2 schema to localStorage', async () => {
    const wrapper = factory()
    await flushPromises()
    const buttons = wrapper.findAll('button')
    const saveButton = buttons.find(b => b.text().includes('保存'))
    expect(saveButton).toBeDefined()
    await saveButton!.trigger('click')
    await flushPromises()
    const stored = localStorage.getItem('quantia_fusion_scheme_v2')
    expect(stored).not.toBeNull()
    const parsed = JSON.parse(stored!)
    expect(parsed.version).toBe(2)
    expect(parsed.mode).toBeDefined()
    expect(parsed.dimensions.length).toBe(5)
    expect(parsed.start_date).toBeDefined()
  })

  it('exportFusionCode calls backend export API and writes to clipboard', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    exportFusionCodeMock.mockResolvedValueOnce({ code: '# generated fusion code', length: 24 })
    const wrapper = factory()
    await flushPromises()
    const buttons = wrapper.findAll('button')
    const exportBtn = buttons.find(b => b.text().includes('导出代码'))
    expect(exportBtn).toBeDefined()
    await exportBtn!.trigger('click')
    await flushPromises()
    expect(exportFusionCodeMock).toHaveBeenCalledTimes(1)
    const payload = exportFusionCodeMock.mock.calls[0][0]
    expect(payload.version).toBe(2)
    expect(payload.dimensions).toBeDefined()
    expect(writeText).toHaveBeenCalledWith('# generated fusion code')
  })

  it('weight warning appears when total != 100', async () => {
    const wrapper = factory()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.dimensions[0].weight = 50
    vm.dimensions[1].weight = 50
    vm.dimensions[2].weight = 50
    await flushPromises()
    expect(wrapper.find('.weight-total.warn').exists()).toBe(true)
  })

  it('switching sub-tab updates active class', async () => {
    const wrapper = factory()
    const tabs = wrapper.findAll('.sub-tab')
    await tabs[1].trigger('click')
    await flushPromises()
    expect(tabs[1].classes()).toContain('active')
  })

  it('shapleyContribs sorted by impact desc with rank order', async () => {
    const wrapper = factory()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.dimensions[0].weight = 30
    vm.dimensions[1].weight = 30
    vm.dimensions[2].weight = 25
    vm.dimensions[3].weight = 15
    vm.dimensions[4].enabled = false
    await vm.runFusionBacktest()
    await flushPromises()
    const contribs = vm.shapleyContribs
    expect(contribs.length).toBe(2)
    // Sorted: 0.45 first, 0.32 second
    expect(contribs[0].impact).toBeGreaterThanOrEqual(contribs[1].impact)
    expect(contribs[0].name).toBe('技术信号')
  })

  it('abSteps binds backend ab_steps array', async () => {
    const wrapper = factory()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.dimensions[0].weight = 30
    vm.dimensions[1].weight = 30
    vm.dimensions[2].weight = 25
    vm.dimensions[3].weight = 15
    vm.dimensions[4].enabled = false
    await vm.runFusionBacktest()
    await flushPromises()
    expect(vm.abSteps.length).toBe(2)
    expect(vm.abSteps[0].label).toBe('技术信号')
    expect(vm.abSteps[1].label).toBe('技术信号 + 基本面')
    expect(vm.abSteps[1].sharpe).toBeCloseTo(1.87, 2)
    expect(vm.abSteps[1].signalCount).toBe(842)
  })

  it('overlapData binds calendar and co_occurrence from backend', async () => {
    const wrapper = factory()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.dimensions[0].weight = 30
    vm.dimensions[1].weight = 30
    vm.dimensions[2].weight = 25
    vm.dimensions[3].weight = 15
    vm.dimensions[4].enabled = false
    await vm.runFusionBacktest()
    await flushPromises()
    expect(vm.overlapData.calendar.length).toBe(2)
    expect(vm.overlapData.co_occurrence.length).toBe(4)
    const pair = vm.overlapData.co_occurrence.find((p: any) => p.a === 'tech' && p.b === 'fund')
    expect(pair).toBeDefined()
    expect(pair.jaccard).toBeCloseTo(0.42, 2)
  })
})
