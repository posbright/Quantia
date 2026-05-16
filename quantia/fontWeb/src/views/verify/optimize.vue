<template>
  <div class="verify-optimize">
    <!-- 工具栏 -->
    <div class="toolbar">
      <el-select v-model="strategy" placeholder="选择策略" style="width: 200px">
        <el-option v-for="s in strategyOptions" :key="s.value" :label="s.label" :value="s.value" />
      </el-select>
      <el-date-picker
        v-model="dateRange"
        type="daterange"
        range-separator="至"
        start-placeholder="开始日期"
        end-placeholder="结束日期"
        value-format="YYYY-MM-DD"
        style="margin-left: 12px; width: 260px"
      />
      <el-button type="primary" :loading="loading" style="margin-left: 12px" @click="runAnalysis">
        开始分析
      </el-button>
    </div>

    <!-- Sub-Tabs -->
    <el-tabs v-model="activeTab" type="card" style="margin-top: 16px">
      <!-- 持仓优化 -->
      <el-tab-pane label="持仓优化" name="holding">
        <div v-if="holdingData.length > 0">
          <p class="info-text">共 {{ totalSignals }} 个信号</p>
          <div class="table-wrapper">
            <table class="cmp-table">
              <thead>
                <tr>
                  <th>持仓天数</th>
                  <th>平均收益%</th>
                  <th>中位数%</th>
                  <th>胜率%</th>
                  <th>夏普</th>
                  <th>Sortino</th>
                  <th>波动率%</th>
                  <th>P10</th>
                  <th>P25</th>
                  <th>P75</th>
                  <th>P90</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in holdingData" :key="item.holding_days" :class="{ 'best-row': item.holding_days === bestHoldingDays }">
                  <td><strong>{{ item.holding_days }}天</strong></td>
                  <td :class="rateClass(item.avg_return)">{{ fmt(item.avg_return) }}</td>
                  <td :class="rateClass(item.median_return)">{{ fmt(item.median_return) }}</td>
                  <td>{{ fmt(item.win_rate) }}</td>
                  <td :class="sharpeClass(item.sharpe_approx)">{{ fmt(item.sharpe_approx) }}</td>
                  <td>{{ fmt(item.sortino_approx) }}</td>
                  <td>{{ fmt(item.return_std) }}</td>
                  <td>{{ fmt(item.percentile_10) }}</td>
                  <td>{{ fmt(item.percentile_25) }}</td>
                  <td>{{ fmt(item.percentile_75) }}</td>
                  <td>{{ fmt(item.percentile_90) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div ref="holdingChartRef" style="height: 300px; margin-top: 16px" />
        </div>
        <el-empty v-else-if="!loading && hasQueried" description="无数据" />
      </el-tab-pane>

      <!-- 信号诊断 -->
      <el-tab-pane label="信号诊断" name="signal">
        <div style="margin-bottom: 12px">
          <el-select v-model="signalIndicator" placeholder="诊断指标" style="width: 160px" @change="loadSignalQuality">
            <el-option v-for="ind in indicatorOptions" :key="ind" :label="ind" :value="ind" />
          </el-select>
        </div>
        <div v-if="signalBuckets.length > 0" class="table-wrapper">
          <table class="cmp-table">
            <thead>
              <tr><th>区间</th><th>信号数</th><th>占比%</th><th>平均收益%</th><th>胜率%</th><th>夏普</th><th>质量</th></tr>
            </thead>
            <tbody>
              <tr v-for="b in signalBuckets" :key="b.range">
                <td>{{ b.range }}</td>
                <td>{{ b.signal_count }}</td>
                <td>{{ fmt(b.pct) }}</td>
                <td :class="rateClass(b.avg_return)">{{ fmt(b.avg_return) }}</td>
                <td>{{ fmt(b.win_rate) }}</td>
                <td>{{ fmt(b.sharpe) }}</td>
                <td><el-tag :type="qualityTagType(b.quality)" size="small">{{ qualityLabel(b.quality) }}</el-tag></td>
              </tr>
            </tbody>
          </table>
        </div>
      </el-tab-pane>

      <!-- 止盈止损 -->
      <el-tab-pane label="止盈止损" name="sltp">
        <div ref="sltpChartRef" style="height: 400px" />
        <div v-if="sltpBest" class="best-combo">
          最优组合: 止损 {{ sltpBest.stop_loss }}% / 止盈 {{ sltpBest.take_profit }}%（夏普 {{ fmt(sltpBest.sharpe) }}）
        </div>
      </el-tab-pane>

      <!-- 风险控制 -->
      <el-tab-pane label="风险控制" name="risk">
        <el-card shadow="never">
          <template #header>交易成本敏感性</template>
          <div v-if="costData.length > 0" class="table-wrapper">
            <table class="cmp-table">
              <thead>
                <tr><th>成本%</th><th>平均收益%</th><th>胜率%</th><th>夏普</th><th></th></tr>
              </thead>
              <tbody>
                <tr v-for="s in costData" :key="s.cost_pct" :class="{ 'best-row': s.is_current }">
                  <td>{{ s.cost_pct }}%</td>
                  <td :class="rateClass(s.avg_return)">{{ fmt(s.avg_return) }}</td>
                  <td>{{ fmt(s.win_rate) }}</td>
                  <td>{{ fmt(s.sharpe) }}</td>
                  <td>{{ s.is_current ? '← 当前' : '' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <!-- AI 优化建议 -->
    <el-card v-if="suggestions.length > 0" shadow="never" style="margin-top: 16px">
      <template #header><span>AI 优化建议</span></template>
      <el-row :gutter="16">
        <el-col v-for="s in suggestions" :key="s.type" :span="8">
          <div class="suggest-card">
            <div class="suggest-icon">{{ s.icon }}</div>
            <div class="suggest-title">{{ s.title }}</div>
            <div class="suggest-content">{{ s.content }}</div>
          </div>
        </el-col>
      </el-row>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'
import { getHoldingPeriod, getSignalQuality, getSlTpMatrix, getCostSensitivity, getOptimizeSuggest } from '@/api/verify'

const strategy = ref('')
const dateRange = ref<[string, string]>(['2025-01-01', '2025-12-31'])
const loading = ref(false)
const hasQueried = ref(false)
const activeTab = ref('holding')

// 持仓优化
const holdingData = ref<any[]>([])
const totalSignals = ref(0)
const bestHoldingDays = ref<number | null>(null)
const holdingChartRef = ref<HTMLElement>()

// 信号诊断
const signalIndicator = ref('rsi_6')
const signalBuckets = ref<any[]>([])
const indicatorOptions = ['rsi_6', 'rsi_12', 'macd', 'macds', 'kdjk', 'kdjd', 'cci', 'atr', 'cr']

// 止盈止损
const sltpChartRef = ref<HTMLElement>()
const sltpBest = ref<any>(null)

// 成本敏感性
const costData = ref<any[]>([])

// 优化建议
const suggestions = ref<any[]>([])

const strategyOptions = [
  { value: 'keep_increasing', label: '放量上涨' },
  { value: 'parking_apron', label: '停机坪' },
  { value: 'backtrace_ma250', label: '回踩年线' },
  { value: 'breakthrough_platform', label: '突破平台' },
  { value: 'low_atr', label: '低ATR成长' },
  { value: 'climax_limitdown', label: '放量跌停' },
  { value: 'high_tight_flag', label: '高而窄旗形' },
  { value: 'low_backtrace_increase', label: '无大幅回撤' },
  { value: 'turtle_trade', label: '海龟交易' },
  { value: 'enter_strategy', label: '企业战略' },
  { value: 'share_holder_increase', label: '股东增持' },
  { value: 'roaming_loong', label: '游龙' },
]

function fmt(v: number | null | undefined): string {
  if (v === null || v === undefined) return '--'
  return Number(v).toFixed(2)
}
function rateClass(v: number | null): string {
  if (v === null || v === undefined) return ''
  return v > 0 ? 'text-red' : v < 0 ? 'text-green' : ''
}
function sharpeClass(v: number | null): string {
  if (v === null || v === undefined) return ''
  return v !== null && v >= 2 ? 'text-red font-bold' : v !== null && v < 0 ? 'text-green' : ''
}
function qualityLabel(q: string): string {
  const map: Record<string, string> = { golden: '黄金', good: '良好', neutral: '中性', filter: '过滤' }
  return map[q] || q
}
function qualityTagType(q: string): '' | 'success' | 'warning' | 'danger' | 'info' {
  const map: Record<string, '' | 'success' | 'warning' | 'danger' | 'info'> = { golden: 'danger', good: 'success', neutral: 'info', filter: 'warning' }
  return map[q] || 'info'
}

async function runAnalysis() {
  if (!strategy.value) { ElMessage.warning('请选择策略'); return }
  if (!dateRange.value?.[0]) { ElMessage.warning('请选择日期范围'); return }

  loading.value = true
  hasQueried.value = true
  const [startDate, endDate] = dateRange.value
  const params = { strategy: strategy.value, start_date: startDate, end_date: endDate }

  try {
    // 并行请求
    const [holdingRes, sltpRes, costRes, suggestRes] = await Promise.all([
      getHoldingPeriod({ ...params, holding_days: '1,3,5,7,10,15,20,30,60' }),
      getSlTpMatrix({ ...params, max_hold_days: 20 }),
      getCostSensitivity({ ...params, holding_days: 5 }),
      getOptimizeSuggest(params),
    ]) as any[]

    // 持仓优化
    holdingData.value = holdingRes.analysis || []
    totalSignals.value = holdingRes.total_signals || 0
    bestHoldingDays.value = holdingRes.best_holding_days
    await nextTick()
    renderHoldingChart()

    // 止盈止损
    sltpBest.value = sltpRes.best_combo
    await nextTick()
    renderSltpChart(sltpRes.matrix || [])

    // 成本
    costData.value = costRes.scenarios || []

    // 建议
    suggestions.value = suggestRes.suggestions || []

    // 信号诊断
    await loadSignalQuality()
  } catch (e: any) {
    ElMessage.error(e.message || '请求失败')
  } finally {
    loading.value = false
  }
}

async function loadSignalQuality() {
  if (!strategy.value || !dateRange.value?.[0]) return
  const [startDate, endDate] = dateRange.value
  try {
    const res: any = await getSignalQuality({ strategy: strategy.value, start_date: startDate, end_date: endDate, indicator: signalIndicator.value, holding_days: 5 })
    signalBuckets.value = res.buckets || []
  } catch { /* ignore */ }
}

onUnmounted(() => {
  if (holdingChartRef.value) echarts.dispose(holdingChartRef.value)
  if (sltpChartRef.value) echarts.dispose(sltpChartRef.value)
})

function renderHoldingChart() {
  if (!holdingChartRef.value || holdingData.value.length === 0) return
  const existing = echarts.getInstanceByDom(holdingChartRef.value)
  if (existing) existing.dispose()
  const chart = echarts.init(holdingChartRef.value)
  const days = holdingData.value.map((d: any) => `${d.holding_days}天`)
  chart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['夏普', '平均收益%'], top: 0 },
    grid: { left: 50, right: 50, bottom: 30, top: 40 },
    xAxis: { type: 'category', data: days },
    yAxis: [
      { type: 'value', name: '夏普' },
      { type: 'value', name: '收益%', position: 'right' },
    ],
    series: [
      { name: '夏普', type: 'line', data: holdingData.value.map((d: any) => d.sharpe_approx), markPoint: { data: [{ type: 'max', name: '最优' }] } },
      { name: '平均收益%', type: 'bar', yAxisIndex: 1, data: holdingData.value.map((d: any) => d.avg_return), itemStyle: { color: '#91cc75' } },
    ],
  })
}

function renderSltpChart(matrix: any[]) {
  if (!sltpChartRef.value || matrix.length === 0) return
  const existing = echarts.getInstanceByDom(sltpChartRef.value)
  if (existing) existing.dispose()
  const chart = echarts.init(sltpChartRef.value)
  const slValues = [...new Set(matrix.map(m => m.stop_loss))].sort((a, b) => a - b)
  const tpValues = [...new Set(matrix.map(m => m.take_profit))].sort((a, b) => a - b)
  const data = matrix.map(m => [tpValues.indexOf(m.take_profit), slValues.indexOf(m.stop_loss), m.sharpe ?? 0])

  chart.setOption({
    tooltip: { formatter: (p: any) => `止盈${tpValues[p.data[0]]}% / 止损${slValues[p.data[1]]}%<br/>夏普: ${p.data[2]?.toFixed(2)}` },
    grid: { left: 80, right: 80, bottom: 40, top: 30 },
    xAxis: { type: 'category', data: tpValues.map(v => `${v}%`), name: '止盈' },
    yAxis: { type: 'category', data: slValues.map(v => `${v}%`), name: '止损' },
    visualMap: { min: -1, max: 4, calculable: true, orient: 'horizontal', left: 'center', bottom: 0, inRange: { color: ['#3060cf', '#ffffff', '#cf1322'] } },
    series: [{ type: 'heatmap', data, label: { show: true, formatter: (p: any) => p.data[2]?.toFixed(1) } }],
  })
}
</script>

<style scoped>
.verify-optimize { padding: 16px; }
.toolbar { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.table-wrapper { overflow-x: auto; }
.cmp-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.cmp-table th, .cmp-table td { border: 1px solid #ebeef5; padding: 8px 12px; text-align: center; white-space: nowrap; }
.cmp-table th { background: #fafafa; font-weight: 600; }
.best-row { background: #fff7e6; }
.best-combo { margin-top: 12px; padding: 10px 16px; background: #f6ffed; border-radius: 4px; font-weight: 600; color: #389e0d; }
.text-red { color: #cf1322; }
.text-green { color: #389e0d; }
.font-bold { font-weight: 700; }
.info-text { color: #8c8c8c; font-size: 13px; margin-bottom: 8px; }
.suggest-card { padding: 16px; background: #fafafa; border-radius: 8px; text-align: center; }
.suggest-icon { font-size: 24px; margin-bottom: 8px; }
.suggest-title { font-weight: 600; margin-bottom: 6px; }
.suggest-content { font-size: 13px; color: #595959; }
</style>
