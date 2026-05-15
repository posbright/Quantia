// Mock 股票数据
export const mockStockSpotData = [
  {
    date: '2026-01-20',
    code: '000001',
    name: '平安银行',
    new_price: 12.35,
    change_rate: 0.0245,
    ups_downs: 0.30,
    volume: 98765432,
    turnover: 1234567890,
    amplitude: 0.035,
    high: 12.50,
    low: 12.10,
    open: 12.15,
    pre_close: 12.35,
    turnoverrate: 0.0156,
    cdatetime: '2026-01-19 10:30:00'  // 已关注
  },
  {
    date: '2026-01-20',
    code: '000002',
    name: '万科A',
    new_price: 8.88,
    change_rate: -0.0156,
    ups_downs: -0.14,
    volume: 56789012,
    turnover: 567890123,
    amplitude: 0.028,
    high: 9.05,
    low: 8.80,
    open: 9.00,
    pre_close: 8.88,
    turnoverrate: 0.0089,
    cdatetime: null
  },
  {
    date: '2026-01-20',
    code: '600519',
    name: '贵州茅台',
    new_price: 1688.00,
    change_rate: 0.0189,
    ups_downs: 31.50,
    volume: 2345678,
    turnover: 3987654321,
    amplitude: 0.025,
    high: 1695.00,
    low: 1650.00,
    open: 1660.00,
    pre_close: 1688.00,
    turnoverrate: 0.0023,
    cdatetime: null
  },
  {
    date: '2026-01-20',
    code: '300750',
    name: '宁德时代',
    new_price: 198.50,
    change_rate: 0.0356,
    ups_downs: 6.85,
    volume: 12345678,
    turnover: 2456789012,
    amplitude: 0.042,
    high: 201.00,
    low: 192.00,
    open: 193.00,
    pre_close: 198.50,
    turnoverrate: 0.0312,
    cdatetime: '2026-01-18 14:20:00'
  },
  {
    date: '2026-01-20',
    code: '601318',
    name: '中国平安',
    new_price: 45.60,
    change_rate: -0.0087,
    ups_downs: -0.40,
    volume: 34567890,
    turnover: 1567890123,
    amplitude: 0.022,
    high: 46.20,
    low: 45.30,
    open: 46.00,
    pre_close: 45.60,
    turnoverrate: 0.0145,
    cdatetime: null
  },
  {
    date: '2026-01-20',
    code: '002594',
    name: '比亚迪',
    new_price: 256.80,
    change_rate: 0.0523,
    ups_downs: 12.75,
    volume: 8765432,
    turnover: 2234567890,
    amplitude: 0.058,
    high: 260.00,
    low: 245.00,
    open: 246.00,
    pre_close: 256.80,
    turnoverrate: 0.0267,
    cdatetime: null
  },
  {
    date: '2026-01-20',
    code: '600036',
    name: '招商银行',
    new_price: 32.45,
    change_rate: 0.0134,
    ups_downs: 0.43,
    volume: 23456789,
    turnover: 765432109,
    amplitude: 0.019,
    high: 32.60,
    low: 31.90,
    open: 32.10,
    pre_close: 32.45,
    turnoverrate: 0.0098,
    cdatetime: null
  },
  {
    date: '2026-01-20',
    code: '601899',
    name: '紫金矿业',
    new_price: 15.28,
    change_rate: 0.0678,
    ups_downs: 0.97,
    volume: 45678901,
    turnover: 698765432,
    amplitude: 0.072,
    high: 15.50,
    low: 14.35,
    open: 14.40,
    pre_close: 15.28,
    turnoverrate: 0.0456,
    cdatetime: null
  },
  {
    date: '2026-01-20',
    code: '000858',
    name: '五粮液',
    new_price: 145.60,
    change_rate: -0.0234,
    ups_downs: -3.50,
    volume: 6789012,
    turnover: 987654321,
    amplitude: 0.031,
    high: 150.00,
    low: 144.50,
    open: 149.00,
    pre_close: 145.60,
    turnoverrate: 0.0178,
    cdatetime: null
  },
  {
    date: '2026-01-20',
    code: '300059',
    name: '东方财富',
    new_price: 18.95,
    change_rate: 0.0412,
    ups_downs: 0.75,
    volume: 89012345,
    turnover: 1678901234,
    amplitude: 0.048,
    high: 19.20,
    low: 18.25,
    open: 18.30,
    pre_close: 18.95,
    turnoverrate: 0.0534,
    cdatetime: null
  }
]

// Mock 股票指标数据
export const mockIndicatorsData = [
  {
    date: '2026-01-20',
    code: '000001',
    name: '平安银行',
    macd: 0.15,
    macd_dea: 0.12,
    macd_dif: 0.18,
    kdj_k: 72.5,
    kdj_d: 65.3,
    kdj_j: 86.9,
    rsi_6: 58.6,
    rsi_12: 55.2,
    rsi_24: 52.8,
    cci: 85.6,
    wr_6: 25.4,
    wr_10: 32.1,
    cdatetime: '2026-01-19 10:30:00'  // 已关注
  },
  {
    date: '2026-01-20',
    code: '600519',
    name: '贵州茅台',
    macd: 25.6,
    macd_dea: 22.3,
    macd_dif: 28.9,
    kdj_k: 85.2,
    kdj_d: 78.6,
    kdj_j: 98.4,
    rsi_6: 72.3,
    rsi_12: 68.5,
    rsi_24: 64.2,
    cci: 125.8,
    wr_6: 12.5,
    wr_10: 18.6,
    cdatetime: null
  },
  {
    date: '2026-01-20',
    code: '300750',
    name: '宁德时代',
    macd: 3.25,
    macd_dea: 2.85,
    macd_dif: 3.65,
    kdj_k: 68.9,
    kdj_d: 62.4,
    kdj_j: 81.9,
    rsi_6: 62.5,
    rsi_12: 58.3,
    rsi_24: 55.6,
    cci: 95.2,
    wr_6: 28.6,
    wr_10: 35.2,
    cdatetime: null
  }
]

// Mock 买入信号数据
export const mockIndicatorsBuyData = [
  {
    date: '2026-01-20',
    code: '601899',
    name: '紫金矿业',
    signal_type: 'KDJ金叉',
    kdj_k: 25.6,
    kdj_d: 22.3,
    kdj_j: 32.2,
    rsi_6: 28.5,
    cci: -120.5,
    cdatetime: null
  },
  {
    date: '2026-01-20',
    code: '000858',
    name: '五粮液',
    signal_type: 'RSI超卖',
    kdj_k: 18.5,
    kdj_d: 15.2,
    kdj_j: 25.1,
    rsi_6: 18.6,
    cci: -145.2,
    cdatetime: '2026-01-18 09:45:00'  // 已关注
  }
]

// Mock 卖出信号数据
export const mockIndicatorsSellData = [
  {
    date: '2026-01-20',
    code: '600519',
    name: '贵州茅台',
    signal_type: 'KDJ超买',
    kdj_k: 92.5,
    kdj_d: 88.6,
    kdj_j: 100.3,
    rsi_6: 85.2,
    cci: 180.5,
    cdatetime: null
  }
]

// Mock K线形态数据
export const mockKlinePatternData = [
  {
    date: '2026-01-20',
    code: '000001',
    name: '平安银行',
    CDL2CROWS: 0,
    CDL3BLACKCROWS: 0,
    CDL3INSIDE: 100,
    CDL3LINESTRIKE: 0,
    CDL3OUTSIDE: 0,
    CDLMORNINGSTAR: 100,
    CDLEVENINGSTAR: 0,
    CDLHAMMER: 0,
    CDLHANGINGMAN: 0,
    CDLDOJI: 0,
    cdatetime: null
  },
  {
    date: '2026-01-20',
    code: '300750',
    name: '宁德时代',
    CDL2CROWS: 0,
    CDL3BLACKCROWS: 0,
    CDL3INSIDE: 0,
    CDL3LINESTRIKE: 0,
    CDL3OUTSIDE: 100,
    CDLMORNINGSTAR: 0,
    CDLEVENINGSTAR: 0,
    CDLHAMMER: 100,
    CDLHANGINGMAN: 0,
    CDLDOJI: 0,
    cdatetime: '2026-01-17 15:00:00'  // 已关注
  },
  {
    date: '2026-01-20',
    code: '002594',
    name: '比亚迪',
    CDL2CROWS: 0,
    CDL3BLACKCROWS: 0,
    CDL3INSIDE: 0,
    CDL3LINESTRIKE: 100,
    CDL3OUTSIDE: 0,
    CDLMORNINGSTAR: 0,
    CDLEVENINGSTAR: 0,
    CDLHAMMER: 0,
    CDLHANGINGMAN: 0,
    CDLDOJI: 100,
    cdatetime: null
  }
]

// Mock 策略选股数据
export const mockStrategyEnterData = [
  {
    date: '2026-01-20',
    code: '601899',
    name: '紫金矿业',
    new_price: 15.28,
    change_rate: 0.0678,
    volume_ratio: 2.85,
    turnoverrate: 0.0456,
    cdatetime: '2026-01-19 14:30:00'  // 已关注
  },
  {
    date: '2026-01-20',
    code: '002594',
    name: '比亚迪',
    new_price: 256.80,
    change_rate: 0.0523,
    volume_ratio: 2.35,
    turnoverrate: 0.0267,
    cdatetime: null
  }
]

// Mock 龙虎榜数据
export const mockLHBData = [
  {
    date: '2026-01-20',
    code: '601899',
    name: '紫金矿业',
    pre_close: 15.28,
    change_rate: 0.0678,
    ranking_times: 3,
    buy_amount: 156789000,
    sell_amount: 98765000,
    net_amount: 58024000,
    reason: '涨幅偏离值达7%',
    cdatetime: null
  },
  {
    date: '2026-01-20',
    code: '300059',
    name: '东方财富',
    pre_close: 18.95,
    change_rate: 0.0412,
    ranking_times: 2,
    buy_amount: 234567000,
    sell_amount: 187654000,
    net_amount: 46913000,
    reason: '换手率达20%',
    cdatetime: '2026-01-18 11:20:00'  // 已关注
  }
]

// Mock K线历史数据
export const mockKlineHistoryData = Array.from({ length: 60 }, (_, i) => {
  const date = new Date('2026-01-20')
  date.setDate(date.getDate() - (59 - i))
  const basePrice = 12 + Math.sin(i / 10) * 2 + Math.random() * 0.5
  const change = (Math.random() - 0.5) * 0.8
  const open = basePrice
  const close = basePrice + change
  const high = Math.max(open, close) + Math.random() * 0.3
  const low = Math.min(open, close) - Math.random() * 0.3
  
  return {
    date: date.toISOString().split('T')[0],
    open: +open.toFixed(2),
    pre_close: +close.toFixed(2),
    high: +high.toFixed(2),
    low: +low.toFixed(2),
    volume: Math.floor(Math.random() * 50000000) + 10000000,
    amount: Math.floor(Math.random() * 500000000) + 100000000
  }
})

// Mock ETF 数据
export const mockETFData = [
  {
    date: '2026-01-20',
    code: '510300',
    name: '沪深300ETF',
    new_price: 4.125,
    change_rate: 0.0185,
    ups_downs: 0.075,
    volume: 234567890,
    turnover: 967890123,
    amplitude: 0.022,
    high: 4.15,
    low: 4.06,
    open: 4.08,
    pre_close: 4.125,
    turnoverrate: 0.0856,
    cdatetime: '2026-01-16 10:00:00'  // 已关注
  },
  {
    date: '2026-01-20',
    code: '159915',
    name: '创业板ETF',
    new_price: 2.356,
    change_rate: 0.0268,
    ups_downs: 0.062,
    volume: 345678901,
    turnover: 812345678,
    amplitude: 0.032,
    high: 2.38,
    low: 2.30,
    open: 2.31,
    pre_close: 2.356,
    turnoverrate: 0.1234,
    cdatetime: null
  }
]

// Mock 资金流向数据
export const mockFundFlowData = [
  {
    date: '2026-01-20',
    code: '000001',
    name: '平安银行',
    main_net_inflow: 125680000,
    main_net_inflow_rate: 0.0856,
    super_large_net_inflow: 56780000,
    large_net_inflow: 68900000,
    medium_net_inflow: -23450000,
    small_net_inflow: -45670000,
    cdatetime: null
  },
  {
    date: '2026-01-20',
    code: '600519',
    name: '贵州茅台',
    main_net_inflow: 356780000,
    main_net_inflow_rate: 0.0923,
    super_large_net_inflow: 198760000,
    large_net_inflow: 158020000,
    medium_net_inflow: -67890000,
    small_net_inflow: -89650000,
    cdatetime: '2026-01-17 09:35:00'  // 已关注
  }
]
