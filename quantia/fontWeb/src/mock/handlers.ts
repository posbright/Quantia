// MSW (Mock Service Worker) 处理器配置
import { http, HttpResponse } from 'msw'
import {
  mockStockSpotData,
  mockIndicatorsData,
  mockIndicatorsBuyData,
  mockIndicatorsSellData,
  mockKlinePatternData,
  mockStrategyEnterData,
  mockLHBData,
  mockETFData,
  mockFundFlowData,
  mockKlineHistoryData
} from './stockData'

// API 路由映射到 Mock 数据
const tableDataMap: Record<string, any[]> = {
  'cn_stock_spot': mockStockSpotData,
  'cn_stock_selection': mockStockSpotData,
  'cn_stock_indicators': mockIndicatorsData,
  'cn_stock_indicators_buy': mockIndicatorsBuyData,
  'cn_stock_indicators_sell': mockIndicatorsSellData,
  'cn_stock_kline_pattern': mockKlinePatternData,
  'cn_stock_strategy_enter': mockStrategyEnterData,
  'cn_stock_lhb': mockLHBData,
  'cn_etf_spot': mockETFData,
  'cn_stock_fund_flow': mockFundFlowData
}

export const handlers = [
  // 获取股票数据列表
  http.get('/quantia/api_data', ({ request }) => {
    const url = new URL(request.url)
    const name = url.searchParams.get('name') || 'cn_stock_spot'
    const date = url.searchParams.get('date')

    let data = tableDataMap[name] || mockStockSpotData

    // 如果有日期参数，过滤数据
    if (date) {
      data = data.filter((item: any) => item.date === date)
    }

    return HttpResponse.json(data)
  }),

  // 关注/取消关注股票
  http.get('/quantia/control/attention', ({ request }) => {
    const url = new URL(request.url)
    const code = url.searchParams.get('code')
    const otype = url.searchParams.get('otype')

    console.log(`[Mock] ${otype === '1' ? '取消关注' : '添加关注'}: ${code}`)

    return HttpResponse.json({ data: [{}] })
  }),

  // 获取K线历史数据
  http.get('/quantia/api/kline', ({ request }) => {
    const url = new URL(request.url)
    const code = url.searchParams.get('code')
    console.log(`[Mock] 获取K线数据: ${code}`)

    return HttpResponse.json(mockKlineHistoryData)
  }),

  // 获取股票指标详情页（HTML）
  http.get('/quantia/data/indicators', ({ request }) => {
    const url = new URL(request.url)
    const code = url.searchParams.get('code')
    const date = url.searchParams.get('date')

    console.log(`[Mock] 获取指标详情: ${code}, ${date}`)

    // 返回空HTML，实际使用时前端会自己渲染
    return new HttpResponse('<html><body>Mock Indicators</body></html>', {
      headers: { 'Content-Type': 'text/html' }
    })
  })
]
