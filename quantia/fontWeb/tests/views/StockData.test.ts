import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createWebHistory } from 'vue-router'
import StockData from '@/views/stock/StockData.vue'
import { mockStockSpotData } from '@/mock/stockData'

// Mock axios
vi.mock('@/api/request', () => ({
  default: vi.fn(() => Promise.resolve(mockStockSpotData))
}))

// 创建测试用路由
const router = createRouter({
  history: createWebHistory(),
  routes: [
    { 
      path: '/basic/spot', 
      name: 'StockSpot',
      component: StockData,
      meta: { title: '每日股票数据', tableName: 'cn_stock_spot' }
    },
    {
      path: '/indicator/detail',
      name: 'IndicatorDetail',
      component: { template: '<div>Indicator</div>' }
    }
  ]
})

describe('StockData 股票数据组件', () => {
  beforeEach(async () => {
    router.push('/basic/spot')
    await router.isReady()
  })

  it('应该正确渲染组件结构', async () => {
    const wrapper = mount(StockData, {
      global: {
        plugins: [router]
      }
    })

    // 检查工具栏存在
    expect(wrapper.find('.toolbar-card').exists()).toBe(true)
    
    // 检查表格存在
    expect(wrapper.find('.el-table').exists()).toBe(true)
  })

  it('应该显示日期选择器', async () => {
    const wrapper = mount(StockData, {
      global: {
        plugins: [router]
      }
    })

    const datePicker = wrapper.find('.el-date-editor')
    expect(datePicker.exists()).toBe(true)
  })

  it('应该显示搜索输入框', async () => {
    const wrapper = mount(StockData, {
      global: {
        plugins: [router]
      }
    })

    const searchInput = wrapper.find('.el-input')
    expect(searchInput.exists()).toBe(true)
  })

  it('应该显示刷新和导出按钮', async () => {
    const wrapper = mount(StockData, {
      global: {
        plugins: [router]
      }
    })

    const buttons = wrapper.findAll('.el-button')
    const buttonTexts = buttons.map(b => b.text())
    
    expect(buttonTexts.some(t => t.includes('刷新'))).toBe(true)
    expect(buttonTexts.some(t => t.includes('导出'))).toBe(true)
  })

  it('应该正确显示分页组件', async () => {
    const wrapper = mount(StockData, {
      global: {
        plugins: [router]
      }
    })

    const pagination = wrapper.find('.el-pagination')
    expect(pagination.exists()).toBe(true)
  })
})
