<template>
  <div class="verify-compare">
    <!-- 工具栏 -->
    <div class="toolbar">
      <el-select
        v-model="selectedStrategies"
        multiple
        collapse-tags
        collapse-tags-tooltip
        placeholder="选择策略（最多5个）"
        style="width: 360px"
        :max-collapse-tags="3"
      >
        <el-option-group v-for="group in strategyGroups" :key="group.label" :label="group.label">
          <el-option v-for="s in group.items" :key="s.value" :label="s.label" :value="s.value" />
        </el-option-group>
      </el-select>
      <el-select v-model="holdingDays" placeholder="持仓周期" style="width: 120px; margin-left: 12px">
        <el-option v-for="d in dayOptions" :key="d" :label="`${d}天`" :value="d" />
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
      <el-button type="primary" :loading="loading" style="margin-left: 12px" @click="runCompare">
        对比分析
      </el-button>
    </div>

    <!-- 指标矩阵 -->
    <el-card v-if="compareData.length > 0" shadow="never" style="margin-top: 16px">
      <template #header><span>核心指标矩阵</span></template>
      <div class="table-wrapper">
        <table class="cmp-table">
          <thead>
            <tr>
              <th>策略</th>
              <th>平均收益%</th>
              <th>胜率%</th>
              <th>年化夏普</th>
              <th>Sortino</th>
              <th>最大单笔亏损%</th>
              <th>最大单笔盈利%</th>
              <th>P10</th>
              <th>P90</th>
              <th>信号数</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in compareData" :key="item.strategy">
              <td><strong>{{ item.strategy_cn || item.strategy }}</strong></td>
              <td :class="rateClass(item.avg_return)">{{ fmt(item.avg_return) }}</td>
              <td>{{ fmt(item.win_rate) }}</td>
              <td :class="sharpeClass(item.sharpe_approx)">{{ fmt(item.sharpe_approx) }}</td>
              <td>{{ fmt(item.sortino_approx) }}</td>
              <td class="text-green">{{ fmt(item.max_single_loss) }}</td>
              <td class="text-red">{{ fmt(item.max_single_gain) }}</td>
              <td>{{ fmt(item.percentile_10) }}</td>
              <td>{{ fmt(item.percentile_90) }}</td>
              <td>{{ item.signal_count }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </el-card>

    <!-- 信号衰减月度趋势 -->
    <el-card v-if="decayData.length > 0" shadow="never" style="margin-top: 16px">
      <template #header><span>信号衰减趋势（月度）</span></template>
      <div ref="decayChartRef" style="height: 320px" />
    </el-card>

    <!-- 市场环境适应性 -->
    <el-card v-if="Object.keys(regimeData).length > 0" shadow="never" style="margin-top: 16px">
      <template #header><span>市场环境适应性</span></template>
      <div class="table-wrapper">
        <table class="cmp-table">
          <thead>
            <tr><th>环境</th><th>平均收益%</th><th>胜率%</th><th>夏普</th><th>信号数</th></tr>
          </thead>
          <tbody>
            <tr v-for="(data, regime) in regimeData" :key="regime">
              <td><el-tag :type="regimeTagType(regime as string)" size="small">{{ regimeLabel(regime as string) }}</el-tag></td>
              <td :class="rateClass(data.avg_return)">{{ fmt(data.avg_return) }}</td>
              <td>{{ fmt(data.win_rate) }}</td>
              <td>{{ fmt(data.sharpe) }}</td>
              <td>{{ data.signal_count }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </el-card>

    <!-- 空状态 -->
    <el-empty v-if="!loading && compareData.length === 0 && hasQueried" description="暂无数据，请选择策略并点击对比分析" />
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'
import { getHoldingPeriod, getSignalDecay, getMarketRegime } from '@/api/verify'

const selectedStrategies = ref<string[]>([])
const holdingDays = ref(5)
const dateRange = ref<[string, string]>(['2025-01-01', '2025-12-31'])
const loading = ref(false)
const hasQueried = ref(false)
const compareData = ref<any[]>([])
const decayData = ref<any[]>([])
const regimeData = ref<Record<string, any>>({})
const decayChartRef = ref<HTMLElement>()

const dayOptions = [1, 3, 5, 7, 10, 15, 20, 30, 60]

const strategyGroups = [
  {
    label: '技术指标',
    items: [
      { value: 'keep_increasing', label: '放量上涨' },
      { value: 'parking_apron', label: '停机坪' },
      { value: 'backtrace_ma250', label: '回踩年线' },
      { value: 'breakthrough_platform', label: '突破平台' },
      { value: 'low_atr', label: '低ATR成长' },
    ],
  },
  {
    label: '量价形态',
    items: [
      { value: 'climax_limitdown', label: '放量跌停' },
      { value: 'high_tight_flag', label: '高而窄旗形' },
      { value: 'low_backtrace_increase', label: '无大幅回撤' },
    ],
  },
  {
    label: '趋势突破',
    items: [
      { value: 'turtle_trade', label: '海龟交易' },
      { value: 'enter_strategy', label: '企业战略' },
      { value: 'share_holder_increase', label: '股东增持' },
      { value: 'roaming_loong', label: '游龙' },
    ],
  },
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
  if (v >= 2) return 'text-red font-bold'
  if (v < 0) return 'text-green'
  return ''
}

function regimeLabel(r: string): string {
  const map: Record<string, string> = { bull: '牛市', bear: '熊市', sideways: '震荡' }
  return map[r] || r
}

function regimeTagType(r: string): '' | 'success' | 'warning' | 'danger' | 'info' {
  const map: Record<string, '' | 'success' | 'warning' | 'danger' | 'info'> = { bull: 'danger', bear: 'success', sideways: 'info' }
  return map[r] || 'info'
}

async function runCompare() {
  if (selectedStrategies.value.length === 0) {
    ElMessage.warning('请至少选择一个策略')
    return
  }
  if (!dateRange.value || !dateRange.value[0]) {
    ElMessage.warning('请选择日期范围')
    return
  }

  loading.value = true
  hasQueried.value = true
  compareData.value = []
  decayData.value = []
  regimeData.value = {}

  const [startDate, endDate] = dateRange.value

  try {
    // 并行请求各策略的持仓天数分析
    const promises = selectedStrategies.value.map(s =>
      getHoldingPeriod({ strategy: s, start_date: startDate, end_date: endDate, holding_days: String(holdingDays.value) })
    )
    const results = await Promise.all(promises)

    compareData.value = results.map((res: any) => {
      const analysis = res.analysis?.[0] || {}
      return { strategy: res.strategy, strategy_cn: res.strategy_cn, ...analysis }
    })

    // 第一个策略的信号衰减
    if (selectedStrategies.value.length > 0) {
      const decayRes: any = await getSignalDecay({ strategy: selectedStrategies.value[0], start_date: startDate, end_date: endDate, holding_days: holdingDays.value })
      decayData.value = decayRes.monthly || []
      await nextTick()
      renderDecayChart()
    }

    // 第一个策略的市场环境
    if (selectedStrategies.value.length > 0) {
      const regimeRes: any = await getMarketRegime({ strategy: selectedStrategies.value[0], start_date: startDate, end_date: endDate, holding_days: holdingDays.value })
      regimeData.value = regimeRes.strategy_by_regime || {}
    }
  } catch (e: any) {
    ElMessage.error(e.message || '请求失败')
  } finally {
    loading.value = false
  }
}

function renderDecayChart() {
  if (!decayChartRef.value || decayData.value.length === 0) return
  const chart = echarts.init(decayChartRef.value)
  const months = decayData.value.map((d: any) => d.month)
  chart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['胜率%', '平均收益%', '夏普'], top: 0 },
    grid: { left: 50, right: 50, bottom: 30, top: 40 },
    xAxis: { type: 'category', data: months },
    yAxis: [
      { type: 'value', name: '胜率/收益%' },
      { type: 'value', name: '夏普', position: 'right' },
    ],
    series: [
      { name: '胜率%', type: 'line', data: decayData.value.map((d: any) => d.win_rate) },
      { name: '平均收益%', type: 'line', data: decayData.value.map((d: any) => d.avg_return) },
      { name: '夏普', type: 'line', yAxisIndex: 1, data: decayData.value.map((d: any) => d.sharpe) },
    ],
  })
}
</script>

<style scoped>
.verify-compare { padding: 16px; }
.toolbar { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.table-wrapper { overflow-x: auto; }
.cmp-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.cmp-table th, .cmp-table td { border: 1px solid #ebeef5; padding: 8px 12px; text-align: center; white-space: nowrap; }
.cmp-table th { background: #fafafa; font-weight: 600; }
.text-red { color: #cf1322; }
.text-green { color: #389e0d; }
.font-bold { font-weight: 700; }
</style>
