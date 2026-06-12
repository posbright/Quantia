import request from './request'

export interface StockDataParams {
  name: string
  date?: string
  page?: number
  page_size?: number
  keyword?: string
  sort?: string
  order?: 'asc' | 'desc'
}

export interface AttentionParams {
  code: string
  otype: '0' | '1'  // 0: 添加关注, 1: 取消关注
}

/**
 * 获取股票数据列表
 * @param params 
 */
export function getStockData(params: StockDataParams) {
  return request({
    url: '/api_data',
    method: 'get',
    params
  })
}

/**
 * 添加/取消关注股票
 * @param params 
 */
export function toggleAttention(params: AttentionParams) {
  return request({
    url: '/control/attention',
    method: 'get',
    params
  })
}

/**
 * 获取最近交易日期
 * 返回 { run_date: 'YYYY-MM-DD', run_date_nph: 'YYYY-MM-DD' }
 * run_date: 最近已收盘的交易日
 * run_date_nph: 当前交易日（含未收盘）
 */
export function getTradeDate() {
  return request({
    url: '/api/trade_date',
    method: 'get'
  })
}

// ============= 回测相关 API =============

export interface BacktestParams {
  code?: string
  strategy?: string
  period?: string
  start_date?: string
  end_date?: string
  /** 回测输出点（逗号分隔，如 1,3,5,10,20） */
  checkpoints?: string
}

export interface BatchBacktestParams {
  strategy: string
  period?: string
  limit?: number
  /** 批量汇总使用的持有天数列表（逗号分隔，如 1,3,5,10,20） */
  horizons?: string
  /** 成功定义使用的持有天数（对应 rate_N > 0） */
  success_days?: number
}

/** 获取回测配置（可选周期、策略列表） */
export function getBacktestConfig() {
  return request({ url: '/api/backtest/config', method: 'get' })
}

/** 执行单只股票回测 */
export function runBacktest(params: BacktestParams) {
  return request({ url: '/api/backtest/run', method: 'get', params })
}

/** 批量回测（策略历史验证） */
export function runBatchBacktest(params: BatchBacktestParams) {
  return request({ url: '/api/backtest/batch', method: 'get', params })
}

// ============= 单股区间买卖点回测 API =============

export interface SingleBacktestParams {
  code: string
  strategy: string
  start_date: string
  end_date: string
  /** 持仓周期（正整数）；留空=按策略卖点出场 */
  hold_days?: number
  /** 是否允许同一持仓期内重复买入信号 */
  allow_overlap?: number
  /** 是否保存到回测历史 */
  save?: number
}

/** 执行单股区间买卖点回测 */
export function runSingleBacktest(params: SingleBacktestParams) {
  return request({ url: '/api/backtest/single', method: 'get', params })
}

export interface BacktestHistoryParams {
  page?: number
  page_size?: number
  code?: string
  strategy?: string
  /** 区间起始（后端读 start，非 start_date）*/
  start?: string
  /** 区间结束（后端读 end，非 end_date）*/
  end?: string
}

/** 回测历史列表 */
export function getBacktestHistory(params: BacktestHistoryParams) {
  return request({ url: '/api/backtest/history', method: 'get', params })
}

/** 回测历史详情 */
export function getBacktestHistoryDetail(id: number) {
  return request({ url: '/api/backtest/history/detail', method: 'get', params: { id } })
}

/** 删除回测历史 */
export function deleteBacktestHistory(id: number) {
  return request({ url: '/api/backtest/history/delete', method: 'delete', params: { id } })
}

// ============= 回测看板 API =============

export interface DashboardOverviewParams {
  days?: number
  metric?: number
  start_date?: string
  end_date?: string
}

export function getBacktestDashboardOverview(params: DashboardOverviewParams) {
  return request({ url: '/api/backtest/dashboard/overview', method: 'get', params })
}

export interface DashboardTimelineParams {
  strategies?: string
  days?: number
  horizon?: number
  start_date?: string
  end_date?: string
}

export function getBacktestDashboardTimeline(params: DashboardTimelineParams) {
  return request({ url: '/api/backtest/dashboard/timeline', method: 'get', params })
}

export interface DashboardStrategyDetailParams {
  strategy: string
  days?: number
  horizons?: string
  page?: number
  page_size?: number
  start_date?: string
  end_date?: string
}

export function getBacktestDashboardStrategyDetail(params: DashboardStrategyDetailParams) {
  return request({ url: '/api/backtest/dashboard/strategy_detail', method: 'get', params })
}

export interface DashboardDistributionParams {
  strategy: string
  days?: number
  horizon?: number
  start_date?: string
  end_date?: string
}

export function getBacktestDashboardDistribution(params: DashboardDistributionParams) {
  return request({ url: '/api/backtest/dashboard/distribution', method: 'get', params })
}

export interface DashboardTradePairsParams {
  strategy: string
  days?: number
  page?: number
  page_size?: number
  max_hold?: number
  start_date?: string
  end_date?: string
}

export function getBacktestDashboardTradePairs(params: DashboardTradePairsParams) {
  return request({ url: '/api/backtest/dashboard/trade_pairs', method: 'get', params })
}

// ============= K线数据 API =============

export interface KlineParams {
  code: string
  date?: string
  start_date?: string
  end_date?: string
  period?: string   // daily / weekly / monthly / quarterly / yearly
  days?: number
  warmup_days?: number
  name?: string
  type?: string     // 'index' | 'stock' — 指定数据源类型，避免同代码股票/指数混淆
}

/** 获取K线数据（含技术指标：MA/BOLL/RSI/MACD） */
export function getKlineData(params: KlineParams) {
  return request({ url: '/api/kline', method: 'get', params })
}

/** 股票财务摘要（估值 + 最新财务 + 历史序列） */
export interface FinancialHistoryItem {
  report_date: string
  report_name: string
  eps: number | null
  bps: number | null
  revenue: number | null
  net_profit: number | null
  revenue_yoy: number | null
  net_profit_yoy: number | null
  roe: number | null
  gross_margin: number | null
  net_profit_margin: number | null
  asset_liability_ratio: number | null
  current_ratio: number | null
  quick_ratio: number | null
  total_asset_turnover: number | null
  ocfps: number | null
  rd_expense: number | null
  admin_expense: number | null
  selling_expense: number | null
  financial_expense: number | null
  rd_ratio: number | null
}

export interface FinancialSummaryResult {
  code: string
  latest: FinancialHistoryItem | null
  history: FinancialHistoryItem[]
  valuation?: {
    name: string
    price: number
    change_pct: number
    pe: number
    pb: number
    market_cap: number   // 万元
    turnover_rate: number
    total_shares: number // 万股
    free_shares: number  // 万股
  }
}

export function getFinancialSummary(code: string, limit = 12) {
  return request<FinancialSummaryResult>({ url: '/api/stock/financial_summary', method: 'get', params: { code, limit } })
}

// ============= 专利数据 API (Phase 3a/4) =============

export interface PatentTrendItem {
  year: number
  count: number
  invention?: number | null
}

export interface PatentData {
  code: string
  year: number | null
  total_patents: number | null
  invention_patents: number | null
  utility_patents: number | null
  design_patents: number | null
  new_patents_year: number | null
  invention_ratio: number | null
  patent_quality_score: number | null
  avg_citation_count: number | null
  pct_international: number | null
  patent_maintenance_rate: number | null
  ipc_primary: string | null
  ipc_primary_desc: string | null
  ipc_distribution: Record<string, number> | null
  tech_domain: string | null
  trend_5y: PatentTrendItem[] | null
  trend_5y_cagr: number | null
  trend_direction: 'accelerating' | 'stable' | 'decelerating' | 'declining' | null
  rd_staff_count: number | null
  rd_staff_ratio: number | null
  key_tech_desc: string | null
  data_source: string | null
  confidence_score: number | null
  updated_at: string | null
}

export interface PatentLatestResp {
  code: string
  latest_year?: number | null
  data: PatentData | null
  trend?: PatentTrendItem[]
  ipc_distribution?: Record<string, number>
  reason?: string
}

export interface PatentHistoryResp {
  code: string
  items: PatentData[]
  count: number
}

export interface PatentCompareItem {
  code: string
  name: string
  year: number
  total_patents: number | null
  invention_patents: number | null
  patent_quality_score: number | null
  tech_domain: string | null
}

export interface PatentPercentiles {
  p25: number
  p50: number
  p75: number
  p90: number
  count: number
}

export interface PatentCompareResp {
  code: string
  industry: string | null
  top: PatentCompareItem[]
  rank: number | null
  total_in_industry?: number
  percentiles?: PatentPercentiles | null
  self_total_patents?: number | null
  self_percentile?: number | null
}

export function getStockPatents(code: string) {
  return request<PatentLatestResp>({ url: '/api/stock/patents', method: 'get', params: { code } })
}

export function getStockPatentsHistory(code: string, years = 5) {
  return request<PatentHistoryResp>({ url: '/api/stock/patents/history', method: 'get', params: { code, years } })
}

export function getStockPatentsCompare(code: string) {
  return request<PatentCompareResp>({ url: '/api/stock/patents/compare', method: 'get', params: { code } })
}

// ============= 组合回测 & 策略管理 API =============

/** 获取内置策略模板 */
export function getStrategyTemplates() {
  return request({ url: '/api/strategy/templates', method: 'get' })
}

/** 同步内置策略模板到策略库（同名策略会更新代码） */
export function syncStrategyTemplates() {
  return request({ url: '/api/strategy/sync_templates', method: 'post' })
}

/** 获取策略列表（含文件夹） */
export function getStrategyCodeList(params?: { folder_id?: number }) {
  return request({ url: '/api/strategy/code/list', method: 'get', params })
}

/** 获取策略详情 */
export function getStrategyCodeDetail(id: number) {
  return request({ url: '/api/strategy/code/detail', method: 'get', params: { id } })
}

/** 保存策略代码 */
export function saveStrategyCode(data: {
  id?: number
  name: string
  code: string
  description?: string
  category?: string
  folder_id?: number
  initial_cash?: number
  benchmark?: string
  commission_rate?: number
  stamp_tax_rate?: number
  slippage?: number
  // M2 §3.1：AI 来源元数据
  source?: 'manual' | 'template' | 'ai'
  ai_prompt?: string
  ai_model?: string
  ai_agent?: string
  ai_repair_count?: number
}) {
  return request({ url: '/api/strategy/code', method: 'post', data })
}

/** 重命名策略 */
export function renameStrategy(id: number, name: string) {
  return request({ url: '/api/strategy/rename', method: 'post', data: { id, name } })
}

/** 移动策略到文件夹 */
export function moveStrategy(ids: number[], folder_id: number) {
  return request({ url: '/api/strategy/move', method: 'post', data: { ids, folder_id } })
}

/** 批量删除策略 */
export function batchDeleteStrategy(ids: number[]) {
  return request({ url: '/api/strategy/batch_delete', method: 'post', data: { ids } })
}

/** 创建文件夹 */
export function createFolder(name: string) {
  return request({ url: '/api/strategy/folder/create', method: 'post', data: { name } })
}

/** 重命名文件夹 */
export function renameFolder(id: number, name: string) {
  return request({ url: '/api/strategy/folder/rename', method: 'post', data: { id, name } })
}

/** 删除文件夹 */
export function deleteFolder(id: number) {
  return request({ url: '/api/strategy/folder/delete', method: 'post', data: { id } })
}

/** 运行组合回测 */
export function runPortfolioBacktest(data: {
  code: string
  strategy_id?: number
  strategy_name?: string
  start_date: string
  end_date: string
  initial_cash?: number
  benchmark?: string
  commission_rate?: number
  stamp_tax_rate?: number
  slippage?: number
}) {
  return request({ url: '/api/backtest/portfolio/run', method: 'post', data })
}

/** 异步启动回测（立即返回 task_id） */
export function startPortfolioBacktest(data: {
  code: string
  strategy_id?: number
  strategy_name?: string
  start_date: string
  end_date: string
  initial_cash?: number
  benchmark?: string
  commission_rate?: number
  stamp_tax_rate?: number
  slippage?: number
}) {
  return request({ url: '/api/backtest/portfolio/start', method: 'post', data })
}

/** 获取回测任务完整结果 */
export function getBacktestTaskResult(taskId: string) {
  return request({ url: '/api/backtest/portfolio/task_result', method: 'get', params: { task_id: taskId } })
}

/** 获取回测历史列表 */
export function getPortfolioBacktestList(params?: { strategy_id?: number }) {
  return request({ url: '/api/backtest/portfolio/list', method: 'get', params })
}

/** 获取回测详情 */
export function getPortfolioBacktestDetail(id: number) {
  return request({ url: '/api/backtest/portfolio/detail', method: 'get', params: { id } })
}

/** 获取回测对比数据（多个ID） */
export function getBacktestCompare(ids: number[]) {
  return request({ url: '/api/backtest/portfolio/compare', method: 'get', params: { ids: ids.join(',') } })
}

/** 批量删除回测记录 */
export function deleteBacktests(ids: number[]) {
  return request({ url: '/api/backtest/portfolio/delete', method: 'post', data: { ids } })
}

/** 获取回测历史列表（分页） */
export function getPortfolioBacktestListPage(params?: { strategy_id?: number; page?: number; page_size?: number }) {
  return request({ url: '/api/backtest/portfolio/list_page', method: 'get', params })
}

// ============= 模拟交易 API =============

/** 创建模拟盘 */
export function createPaperTrading(data: {
  strategy_id: number
  backtest_id?: number | null
  name?: string
  initial_cash?: number
  run_frequency?: 'daily' | 'hourly' | '15m'
  start_at?: string
}) {
  return request({ url: '/api/paper/create', method: 'post', data })
}

/** 更新模拟盘设置 */
export function updatePaperTrading(data: {
  id: number
  name?: string
  initial_cash?: number
  run_frequency?: 'daily' | 'hourly' | '15m'
  start_at?: string
}) {
  return request({ url: '/api/paper/update', method: 'post', data })
}

/** 模拟盘操作（暂停/恢复/停止） */
export function paperTradingAction(data: { id: number; action: 'pause' | 'resume' | 'stop' }) {
  return request({ url: '/api/paper/action', method: 'post', data })
}

/** 获取模拟盘列表 */
export function getPaperTradingList() {
  return request({ url: '/api/paper/list', method: 'get' })
}

/** 获取模拟盘详情 */
export function getPaperTradingDetail(id: number, posDate?: string, benchmarkStartMode?: 'paper_start' | 'first_trade') {
  const params: any = { id }
  if (posDate) params.pos_date = posDate
  if (benchmarkStartMode) params.benchmark_start_mode = benchmarkStartMode
  return request({ url: '/api/paper/detail', method: 'get', params })
}

/** 手动触发模拟盘执行 */
export function runPaperTrading(id: number) {
  return request({ url: '/api/paper/run', method: 'post', data: { id } })
}

/** 模拟盘多策略对比 */
export function getPaperCompare(ids: number[]) {
  return request({ url: '/api/paper/compare', method: 'get', params: { ids: ids.join(',') } })
}

/** 删除模拟盘 */
export function deletePaperTrading(id: number) {
  return request({ url: '/api/paper/delete', method: 'post', data: { id } })
}
