// 股票数据类型定义
// 字段名与数据库实际字段名保持一致

export interface StockSpot {
  date: string
  code: string
  name: string
  new_price: number  // 最新价/收盘价
  change_rate: number  // 涨跌幅
  ups_downs: number  // 涨跌额
  volume: number  // 成交量
  turnover: number  // 成交额（数据库字段名）
  amplitude: number  // 振幅
  high: number  // 最高价（数据库字段名）
  low: number  // 最低价（数据库字段名）
  open?: number  // 开盘价（数据库字段名，部分表有）
  pre_close: number  // 昨收价（数据库字段名）
  volume_ratio: number  // 量比
  turnoverrate: number  // 换手率
  cdatetime?: string  // 关注时间，有值表示已关注
}

export interface StockIndicator {
  date: string
  code: string
  name: string
  macd: number
  macd_dea: number
  macd_dif: number
  kdj_k: number
  kdj_d: number
  kdj_j: number
  rsi_6: number
  rsi_12: number
  rsi_24: number
  boll_upper: number
  boll_mid: number
  boll_lower: number
  cci: number
  wr_6: number
  wr_10: number
  // ... 更多指标
}

export interface KlineData {
  date: string
  open: number
  close: number
  high: number
  low: number
  volume: number
  amount?: number
}

export interface KlinePattern {
  date: string
  code: string
  name: string
  pattern_name: string
  pattern_value: number  // 正: 买入信号, 负: 卖出信号, 0: 无信号
}

export interface StrategyResult {
  date: string
  code: string
  name: string
  strategy_name: string
  // ... 策略相关字段
}

export interface BacktestResult {
  date: string
  code: string
  name: string
  buy_date: string
  sell_date: string
  profit_rate: number
  success: boolean
}
