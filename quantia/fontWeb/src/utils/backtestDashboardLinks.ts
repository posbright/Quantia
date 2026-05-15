export type BacktestDashboardFocus = 'overview' | 'timeline' | 'detail'

export const DEFAULT_BACKTEST_TIMELINE_DAYS = '90'
export const DEFAULT_BACKTEST_TIMELINE_HORIZON = '5'
export const DEFAULT_BACKTEST_DETAIL_DAYS = '90'
export const DEFAULT_BACKTEST_DETAIL_HORIZONS = '1,3,5,10,20,30,60,90,120'

export function extractBacktestStrategyName(row: any): string {
  const strategy = row?.strategy_name || row?.strategy || row?.name || ''
  return String(strategy || '')
}

export function buildBacktestDashboardQuery(row: any, focus?: BacktestDashboardFocus): Record<string, string> {
  const strategy = extractBacktestStrategyName(row)
  const query: Record<string, string> = { strategy }

  if (focus === 'timeline') {
    query.focus = 'timeline'
    query.days = DEFAULT_BACKTEST_TIMELINE_DAYS
    query.horizon = DEFAULT_BACKTEST_TIMELINE_HORIZON
  }

  if (focus === 'detail') {
    query.focus = 'detail'
    query.detail_days = DEFAULT_BACKTEST_DETAIL_DAYS
    query.detail_horizons = DEFAULT_BACKTEST_DETAIL_HORIZONS
  }

  return query
}
