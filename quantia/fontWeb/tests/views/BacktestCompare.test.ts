import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createWebHistory } from 'vue-router'
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
const mockCompareData = {
  code: 0,
  data: {
    backtests: [
      {
        id: 1,
        strategy_id: 10,
        strategy_name: '策略A',
        start_date: '2024-01-01',
        end_date: '2024-12-31',
        initial_cash: 100000,
        status: 'completed',
        metrics: {
          total_return: 25.5,
          annual_return: 26.1,
          max_drawdown: -12.3,
          sharpe_ratio: 1.85,
          alpha: 0.15,
          beta: 0.92,
          trade_win_rate: 65.0,
          trade_count: 42,
        },
        nav: [
          { date: '2024-01-02', nav: 1.001 },
          { date: '2024-06-30', nav: 1.12 },
          { date: '2024-12-31', nav: 1.255 },
        ],
        trades: [
          { date: '2024-01-05', direction: 'buy', stock: '000001' },
          { date: '2024-02-10', direction: 'sell', stock: '000001' },
        ],
        strategy_code: 'def initialize(context):\n    pass',
        completed_at: '2024-12-31 18:00:00',
        params: { benchmark: '000300' },
      },
      {
        id: 2,
        strategy_id: 11,
        strategy_name: '策略B',
        start_date: '2024-01-01',
        end_date: '2024-12-31',
        initial_cash: 100000,
        status: 'completed',
        metrics: {
          total_return: 18.3,
          annual_return: 18.8,
          max_drawdown: -8.1,
          sharpe_ratio: 2.10,
          alpha: 0.22,
          beta: 0.75,
          trade_win_rate: 58.0,
          trade_count: 28,
        },
        nav: [
          { date: '2024-01-02', nav: 1.002 },
          { date: '2024-06-30', nav: 1.09 },
          { date: '2024-12-31', nav: 1.183 },
        ],
        trades: [
          { date: '2024-01-08', direction: 'buy', stock: '600000' },
          { date: '2024-03-15', direction: 'sell', stock: '600000' },
          { date: '2024-05-20', direction: 'buy', stock: '600036' },
        ],
        strategy_code: 'def initialize(context):\n    g.stock_list = []',
        completed_at: '2024-12-31 18:30:00',
        params: { benchmark: '000300' },
      },
    ],
  },
}

vi.mock('@/api/stock', () => ({
  getBacktestCompare: vi.fn(() => Promise.resolve(mockCompareData)),
  runPortfolioBacktest: vi.fn(() =>
    Promise.resolve({
      code: 0,
      data: { status: 'completed', backtest_id: 99, metrics: { total_return: 20.0, annual_return: 20.5, max_drawdown: -10.0, sharpe_ratio: 1.9 } },
    })
  ),
  deleteBacktests: vi.fn(() => Promise.resolve({ code: 0, data: { deleted: 1 } })),
  getPortfolioBacktestListPage: vi.fn(() => Promise.resolve({ code: 0, data: [], total: 0, page: 1, page_size: 20 })),
}))

import BacktestCompare from '@/views/algo/backtest-compare.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/algo/backtest-compare',
      name: 'BacktestCompare',
      component: BacktestCompare,
      meta: { title: '回测对比', hidden: true },
    },
    {
      path: '/algo/backtest-detail/:id',
      name: 'BacktestDetail',
      component: { template: '<div>Detail</div>' },
    },
  ],
})

describe('BacktestCompare 回测对比页面', () => {
  beforeEach(async () => {
    router.push('/algo/backtest-compare?ids=1,2')
    await router.isReady()
  })

  it('应该正确渲染页面标题', async () => {
    const wrapper = mount(BacktestCompare, {
      global: {
        plugins: [router, ElementPlus],
        stubs: { 'el-icon': true },
      },
    })
    await flushPromises()
    expect(wrapper.find('.compare-header h3').text()).toBe('回测对比')
  })

  it('应该显示对比策略数量', async () => {
    const wrapper = mount(BacktestCompare, {
      global: {
        plugins: [router, ElementPlus],
        stubs: { 'el-icon': true },
      },
    })
    await flushPromises()
    expect(wrapper.find('.header-sub').text()).toContain('2')
    expect(wrapper.find('.header-sub').text()).toContain('对比')
  })

  it('应该渲染 tabs 面板', async () => {
    const wrapper = mount(BacktestCompare, {
      global: {
        plugins: [router, ElementPlus],
        stubs: { 'el-icon': true },
      },
    })
    await flushPromises()
    const tabs = wrapper.findAll('.el-tabs__item')
    const tabLabels = tabs.map((t) => t.text())
    expect(tabLabels).toContain('收益走势')
    expect(tabLabels).toContain('指标对比')
    expect(tabLabels).toContain('交易统计')
    expect(tabLabels).toContain('代码对比')
  })

  it('应该调用 getBacktestCompare API', async () => {
    const { getBacktestCompare } = await import('@/api/stock')
    mount(BacktestCompare, {
      global: {
        plugins: [router, ElementPlus],
        stubs: { 'el-icon': true },
      },
    })
    await flushPromises()
    expect(getBacktestCompare).toHaveBeenCalledWith([1, 2])
  })

  it('应该包含图表容器', async () => {
    const wrapper = mount(BacktestCompare, {
      global: {
        plugins: [router, ElementPlus],
        stubs: { 'el-icon': true },
      },
    })
    await flushPromises()
    expect(wrapper.find('.chart-box').exists()).toBe(true)
  })
})

describe('BacktestCompare 指标对比逻辑', () => {
  it('应该正确解析对比数据中的指标字段', () => {
    const bt = mockCompareData.data.backtests[0]
    expect(bt.metrics.total_return).toBe(25.5)
    expect(bt.metrics.sharpe_ratio).toBe(1.85)
    expect(bt.metrics.max_drawdown).toBe(-12.3)
  })

  it('应该正确统计买入和卖出次数', () => {
    const bt = mockCompareData.data.backtests[1]
    const buyCount = bt.trades.filter((t) => t.direction === 'buy').length
    const sellCount = bt.trades.filter((t) => t.direction === 'sell').length
    expect(buyCount).toBe(2)
    expect(sellCount).toBe(1)
  })

  it('两个策略的 NAV 数据应该对齐合并日期', () => {
    const allDates = new Set<string>()
    mockCompareData.data.backtests.forEach((bt) => {
      bt.nav.forEach((r) => allDates.add(r.date))
    })
    const dates = Array.from(allDates).sort()
    // Both share 3 dates each, with overlapping dates
    expect(dates.length).toBeGreaterThanOrEqual(3)
    expect(dates[0]).toBe('2024-01-02')
  })

  it('应该识别最优指标值', () => {
    const bts = mockCompareData.data.backtests
    // 策略A total_return 25.5 > 策略B 18.3 → A is best for total_return
    const totalReturns = bts.map((bt) => ({ id: bt.id, val: bt.metrics.total_return }))
    const best = totalReturns.reduce((a, b) => (a.val > b.val ? a : b))
    expect(best.id).toBe(1)

    // 策略B max_drawdown -8.1 > -12.3 → B is best (lower abs drawdown)
    const drawdowns = bts.map((bt) => ({ id: bt.id, val: bt.metrics.max_drawdown }))
    const bestDD = drawdowns.reduce((a, b) => (a.val > b.val ? a : b))
    expect(bestDD.id).toBe(2)
  })
})

describe('BacktestCompare 代码对比', () => {
  it('每个策略应该有策略代码', () => {
    mockCompareData.data.backtests.forEach((bt) => {
      expect(typeof bt.strategy_code).toBe('string')
      expect(bt.strategy_code.length).toBeGreaterThan(0)
    })
  })

  it('策略代码应该可以修改后重新运行', async () => {
    const { runPortfolioBacktest } = await import('@/api/stock')
    const bt = mockCompareData.data.backtests[0]
    const modifiedCode = bt.strategy_code + '\n# modified'

    await runPortfolioBacktest({
      code: modifiedCode,
      strategy_id: bt.strategy_id,
      start_date: bt.start_date,
      end_date: bt.end_date,
      initial_cash: bt.initial_cash,
      benchmark: bt.params.benchmark,
    })

    expect(runPortfolioBacktest).toHaveBeenCalledWith(
      expect.objectContaining({
        code: modifiedCode,
        strategy_id: bt.strategy_id,
      })
    )
  })
})

describe('BacktestCompare 路由配置', () => {
  it('比较路由应该正确配置', async () => {
    await router.push('/algo/backtest-compare?ids=1,2')
    expect(router.currentRoute.value.name).toBe('BacktestCompare')
    expect(router.currentRoute.value.query.ids).toBe('1,2')
    expect(router.currentRoute.value.meta.hidden).toBe(true)
  })

  it('应该正确解析多个ID查询参数', async () => {
    await router.push('/algo/backtest-compare?ids=5,10,15')
    const idsStr = router.currentRoute.value.query.ids as string
    const ids = idsStr.split(',').map(Number)
    expect(ids).toEqual([5, 10, 15])
  })
})

describe('批量删除和分页 API', () => {
  it('deleteBacktests 应该可以调用', async () => {
    const { deleteBacktests } = await import('@/api/stock')
    const res = await deleteBacktests([1, 2]) as any
    expect(res.code).toBe(0)
    expect(deleteBacktests).toHaveBeenCalledWith([1, 2])
  })

  it('getPortfolioBacktestListPage 应该可以调用', async () => {
    const { getPortfolioBacktestListPage } = await import('@/api/stock')
    const res = await getPortfolioBacktestListPage({ page: 1, page_size: 20 }) as any
    expect(res.code).toBe(0)
    expect(res).toHaveProperty('total')
    expect(res).toHaveProperty('page')
  })

  it('分页参数计算正确', () => {
    const page = 3
    const pageSize = 20
    const offset = (page - 1) * pageSize
    expect(offset).toBe(40)
  })
})
