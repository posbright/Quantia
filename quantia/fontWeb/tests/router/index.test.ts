import { describe, it, expect, beforeAll, afterAll, afterEach } from 'vitest'
import { createRouter, createWebHistory } from 'vue-router'

// 路由配置测试
const routes = [
  { path: '/', redirect: '/home' },
  { path: '/home', name: 'Home', component: { template: '<div>Home</div>' } },
  { path: '/selection/all', name: 'StockSelection', meta: { title: '综合选股', tableName: 'cn_stock_selection' } },
  { path: '/basic/spot', name: 'StockSpot', meta: { title: '每日股票数据', tableName: 'cn_stock_spot' } },
  { path: '/basic/fund-flow', name: 'FundFlow', meta: { title: '股票资金流向', tableName: 'cn_stock_fund_flow' } },
  { path: '/indicator/list', name: 'IndicatorList', meta: { title: '股票指标', tableName: 'cn_stock_indicators' } },
  { path: '/indicator/detail', name: 'IndicatorDetail', meta: { title: '指标详情', hidden: true } },
  { path: '/kline/pattern', name: 'KlinePattern', meta: { title: 'K线形态识别', tableName: 'cn_stock_kline_pattern' } },
  { path: '/strategy/enter', name: 'StrategyEnter', meta: { title: '放量上涨', tableName: 'cn_stock_strategy_enter' } }
]

describe('Router 路由配置测试', () => {
  const router = createRouter({
    history: createWebHistory(),
    routes
  })

  it('应该正确配置首页路由', async () => {
    await router.push('/')
    expect(router.currentRoute.value.path).toBe('/home')
  })

  it('应该正确导航到综合选股页面', async () => {
    await router.push('/selection/all')
    expect(router.currentRoute.value.name).toBe('StockSelection')
    expect(router.currentRoute.value.meta.tableName).toBe('cn_stock_selection')
  })

  it('应该正确导航到股票数据页面', async () => {
    await router.push('/basic/spot')
    expect(router.currentRoute.value.name).toBe('StockSpot')
    expect(router.currentRoute.value.meta.title).toBe('每日股票数据')
  })

  it('应该正确导航到指标详情页面并传递参数', async () => {
    await router.push({
      path: '/indicator/detail',
      query: { code: '000001', date: '2026-01-20', name: '平安银行' }
    })
    expect(router.currentRoute.value.name).toBe('IndicatorDetail')
    expect(router.currentRoute.value.query.code).toBe('000001')
    expect(router.currentRoute.value.query.date).toBe('2026-01-20')
  })

  it('应该正确导航到策略选股页面', async () => {
    await router.push('/strategy/enter')
    expect(router.currentRoute.value.name).toBe('StrategyEnter')
    expect(router.currentRoute.value.meta.tableName).toBe('cn_stock_strategy_enter')
  })

  it('隐藏路由应该有 hidden 标记', async () => {
    await router.push('/indicator/detail')
    expect(router.currentRoute.value.meta.hidden).toBe(true)
  })
})
