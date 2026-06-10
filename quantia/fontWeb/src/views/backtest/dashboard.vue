<script setup lang="ts">
import { computed, onMounted, ref, watch, nextTick, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'
import {
  getBacktestDashboardOverview,
  getBacktestDashboardTimeline,
  getBacktestDashboardStrategyDetail,
  getBacktestDashboardDistribution,
  getBacktestDashboardTradePairs,
} from '@/api/stock'
import { useResponsive } from '@/composables/useResponsive'

const { isMobile } = useResponsive()
const route = useRoute()
const router = useRouter()

const loading = ref(false)

// Global date range (preferred over days)
const dateRange = ref<[string, string] | []>([])
const hasExplicitRange = computed(() => Array.isArray(dateRange.value) && (dateRange.value as any).length === 2)

const parseDateText = (v: any): string => {
  const s = String(v || '').trim()
  if (!s) return ''
  // accept YYYY-MM-DD / YYYYMMDD / YYYY/MM/DD
  const m = s.match(/^(\d{4})[-/.]?(\d{1,2})[-/.]?(\d{1,2})$/)
  if (!m) return ''
  const y = m[1]
  const mo = String(m[2]).padStart(2, '0')
  const d = String(m[3]).padStart(2, '0')
  return `${y}-${mo}-${d}`
}

const buildRangeParams = () => {
  if (!hasExplicitRange.value) return {}
  const [start_date, end_date] = dateRange.value as [string, string]
  if (!start_date || !end_date) return {}
  return { start_date, end_date }
}

// Overview
const overviewDays = ref(60)
const overviewMetric = ref(5)
const overview = ref<any>(null)

// Timeline
const timelineDays = ref(90)
const timelineHorizon = ref(5)
const timelineStrategies = ref<string[]>([])
const timeline = ref<any>(null)
const timelineChartRef = ref<HTMLDivElement>()
let timelineChart: echarts.ECharts | null = null

const overviewCardRef = ref<any>(null)
const timelineCardRef = ref<any>(null)
const detailCardRef = ref<any>(null)
const pendingFocus = ref('')

// Strategy detail
const selectedStrategy = ref('')
const detailDays = ref(30)
const detailHorizons = ref<number[]>([1, 3, 5, 10, 20, 30, 60, 90, 120])
const detailPage = ref(1)
const detailPageSize = ref(50)
const detail = ref<any>(null)

// Distribution
const distDays = ref(60)
const distHorizon = ref(5)
const distribution = ref<any>(null)

// Trade pairs
const pairDays = ref(60)
const pairMaxHold = ref(100)
const pairPage = ref(1)
const pairPageSize = ref(50)
const tradePairs = ref<any>(null)

const applyQueryParams = () => {
  const q: any = route.query || {}

  const qs = parseDateText(q.start_date)
  const qe = parseDateText(q.end_date)
  if (qs || qe) {
    const start = qs || qe
    const end = qe || qs
    if (start && end) dateRange.value = [start, end]
  }

  if (q.focus) {
    pendingFocus.value = String(q.focus || '')
  }

  if (q.days) {
    const n = Number(q.days)
    if (Number.isFinite(n) && n > 0) {
      const daysValue = Math.min(365, Math.max(1, Math.floor(n)))
      if (pendingFocus.value === 'timeline') {
        timelineDays.value = daysValue
      } else {
        overviewDays.value = daysValue
      }
    }
  }

  if (q.timeline_days) {
    const n = Number(q.timeline_days)
    if (Number.isFinite(n) && n > 0) {
      timelineDays.value = Math.min(365, Math.max(1, Math.floor(n)))
    }
  }

  if (q.metric) {
    const n = Number(q.metric)
    if (Number.isFinite(n) && n > 0) {
      overviewMetric.value = Math.min(120, Math.max(1, Math.floor(n)))
    }
  }
  if (q.horizon) {
    const n = Number(q.horizon)
    if (Number.isFinite(n) && n > 0) {
      timelineHorizon.value = Math.min(120, Math.max(1, Math.floor(n)))
    }
  }

  if (q.detail_days) {
    const n = Number(q.detail_days)
    if (Number.isFinite(n) && n > 0) {
      detailDays.value = Math.min(365, Math.max(1, Math.floor(n)))
    }
  }
  if (q.detail_horizons) {
    const arr = String(q.detail_horizons)
      .split(',')
      .map(s => Number(s.trim()))
      .filter(v => Number.isFinite(v) && v >= 1 && v <= 120)
    if (arr.length) {
      detailHorizons.value = Array.from(new Set(arr)).sort((a, b) => a - b)
    }
  }

  if (q.strategy) {
    const s = String(q.strategy)
    if (s) selectedStrategy.value = s
  }
}

const scrollToFocus = async () => {
  if (!pendingFocus.value) return
  await nextTick()

  const unwrapEl = (r: any): HTMLElement | null => {
    if (!r) return null
    return (r.$el || r) as HTMLElement
  }

  let target: HTMLElement | null = null
  if (pendingFocus.value === 'timeline') target = unwrapEl(timelineCardRef.value)
  if (pendingFocus.value === 'detail') target = unwrapEl(detailCardRef.value)
  if (pendingFocus.value === 'overview') target = unwrapEl(overviewCardRef.value)

  if (target?.scrollIntoView) {
    target.scrollIntoView({ block: 'start', behavior: 'auto' })
  }
  pendingFocus.value = ''
}

const overviewItems = computed(() => overview.value?.items || [])
const overviewHorizonList = computed(() => overview.value?.horizons || [1, 3, 5, 10, 20, 30, 60, 90, 120])

const formatRate = (val: any) => {
  if (val === null || val === undefined) return '-'
  const num = Number(val)
  if (Number.isNaN(num)) return '-'
  return num >= 0 ? `+${num.toFixed(2)}%` : `${num.toFixed(2)}%`
}

const getRateClass = (val: any) => {
  if (val === null || val === undefined) return ''
  const num = Number(val)
  if (Number.isNaN(num)) return ''
  return num >= 0 ? 'text-up' : 'text-down'
}

const joinNumbers = (arr: any[]) => {
  return (arr || [])
    .map(v => Number(v))
    .filter(v => Number.isFinite(v) && v > 0)
    .join(',')
}

const loadOverview = async () => {
  const params: any = {
    metric: overviewMetric.value,
    ...buildRangeParams(),
  }
  if (!params.start_date) params.days = overviewDays.value

  const res: any = await getBacktestDashboardOverview(params)
  if (res?.error) throw new Error(res.error)
  overview.value = res

  if (!selectedStrategy.value && res?.items?.length) {
    selectedStrategy.value = res.items[0].strategy_name
  }
}

const loadTimeline = async () => {
  const params: any = {
    strategies: timelineStrategies.value.join(','),
    horizon: timelineHorizon.value,
    ...buildRangeParams(),
  }
  if (!params.start_date) params.days = timelineDays.value

  const res: any = await getBacktestDashboardTimeline(params)
  if (res?.error) throw new Error(res.error)
  timeline.value = res
  await nextTick()
  renderTimelineChart()
}

const renderTimelineChart = () => {
  if (!timelineChartRef.value || !timeline.value) return

  if (timelineChart) timelineChart.dispose()
  timelineChart = echarts.init(timelineChartRef.value)

  const series = (timeline.value.series || []).map((s: any) => ({
    name: s.strategy_cn || s.strategy_name,
    type: 'line',
    smooth: true,
    symbol: 'none',
    data: (s.data || []).map((d: any) => [d.date, d.value]),
  }))

  timelineChart.setOption({
    animation: false,
    tooltip: { trigger: 'axis' },
    legend: { top: 0, textStyle: { fontSize: 11 } },
    grid: { left: '8%', right: '4%', top: 36, bottom: 24 },
    xAxis: { type: 'time' },
    yAxis: { type: 'value', axisLabel: { formatter: (v: any) => `${v}%` } },
    series,
  })
}

const loadStrategyDetail = async () => {
  if (!selectedStrategy.value) {
    detail.value = null
    return
  }
  const params: any = {
    strategy: selectedStrategy.value,
    horizons: joinNumbers(detailHorizons.value),
    page: detailPage.value,
    page_size: detailPageSize.value,
    ...buildRangeParams(),
  }
  if (!params.start_date) params.days = detailDays.value

  const res: any = await getBacktestDashboardStrategyDetail(params)
  if (res?.error) { detail.value = null; console.warn('strategyDetail:', res.error); return }
  detail.value = res
}

const loadDistribution = async () => {
  if (!selectedStrategy.value) {
    distribution.value = null
    return
  }
  const params: any = {
    strategy: selectedStrategy.value,
    horizon: distHorizon.value,
    ...buildRangeParams(),
  }
  if (!params.start_date) params.days = distDays.value

  const res: any = await getBacktestDashboardDistribution(params)
  if (res?.error) { distribution.value = null; console.warn('distribution:', res.error); return }
  distribution.value = res
}

const loadTradePairs = async () => {
  if (!selectedStrategy.value) {
    tradePairs.value = null
    return
  }
  const params: any = {
    strategy: selectedStrategy.value,
    page: pairPage.value,
    page_size: pairPageSize.value,
    max_hold: pairMaxHold.value,
    ...buildRangeParams(),
  }
  if (!params.start_date) params.days = pairDays.value

  const res: any = await getBacktestDashboardTradePairs(params)
  if (res?.error) { tradePairs.value = null; console.warn('tradePairs:', res.error); return }
  tradePairs.value = res
}

const refreshAll = async () => {
  loading.value = true
  try {
    await loadOverview()
    if (timelineStrategies.value.length === 0 && overviewItems.value.length) {
      timelineStrategies.value = overviewItems.value.slice(0, 6).map((x: any) => x.strategy_name)
    }
    await Promise.all([loadTimeline(), loadStrategyDetail(), loadDistribution(), loadTradePairs()])
    await scrollToFocus()
  } catch (e: any) {
    ElMessage.error(e?.message || '加载失败')
  } finally {
    loading.value = false
  }
}

const selectStrategyFromOverview = async (strategyName: string) => {
  selectedStrategy.value = strategyName
  detailPage.value = 1
  pairPage.value = 1
  await refreshAll()
}

const goIndicatorDetail = (row: any) => {
  router.push({
    path: '/indicator/detail',
    query: {
      code: row.code,
      name: row.name,
      date: row.date,
      strategy: selectedStrategy.value || undefined,
    },
  })
}

const goCustomBacktest = (row: any) => {
  router.push({
    path: '/backtest/custom',
    query: {
      code: row.code,
      name: row.name,
      strategy: selectedStrategy.value || undefined,
    },
  })
}

const handleResize = () => timelineChart?.resize()

onMounted(async () => {
  window.addEventListener('resize', handleResize)
  applyQueryParams()
  await refreshAll()
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  if (timelineChart) timelineChart.dispose()
  timelineChart = null
})

watch([timelineDays, timelineHorizon, timelineStrategies], () => {
  if (!overview.value) return
  loadTimeline().catch(() => {})
})

watch(
  () => dateRange.value,
  () => {
    detailPage.value = 1
    pairPage.value = 1
    refreshAll().catch(() => {})
  }
)

watch(
  () => route.query,
  () => {
    applyQueryParams()
    refreshAll().catch(() => {})
  }
)
</script>

<template>
  <div class="dashboard-container">
    <el-card shadow="never" class="config-card">
      <template #header>
        <div class="header-row">
          <span class="card-title">回测看板</span>
          <el-button type="primary" :loading="loading" @click="refreshAll">刷新</el-button>
        </div>
      </template>

      <el-form inline label-width="120px">
        <el-form-item label="日期区间">
          <el-date-picker
            v-model="dateRange"
            type="daterange"
            unlink-panels
            range-separator="-"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            value-format="YYYY-MM-DD"
            :clearable="true"
            style="width: 320px"
          />
        </el-form-item>
        <el-form-item label="总览区间(天)">
          <el-input-number v-model="overviewDays" :min="1" :max="365" :disabled="hasExplicitRange" />
        </el-form-item>
        <el-form-item label="排名指标(天)">
          <el-select v-model="overviewMetric" style="width: 140px">
            <el-option v-for="h in overviewHorizonList" :key="h" :label="`${h}日收益`" :value="h" />
          </el-select>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card ref="overviewCardRef" shadow="never" class="result-card">
      <template #header>
        <span class="card-title">策略总览</span>
      </template>

      <el-table :data="overviewItems" border size="small" stripe :scroll-x="true">
        <el-table-column prop="strategy_cn" label="策略" min-width="140" fixed="left" />
        <el-table-column prop="total_signals" label="信号数" width="80" align="right" />
        <el-table-column prop="avg_success_rate" label="平均成功率" width="100" align="right">
          <template #default="{ row }">{{
            row.avg_success_rate === null || row.avg_success_rate === undefined ? '-' : `${row.avg_success_rate}%`
          }}</template>
        </el-table-column>
        <el-table-column v-for="h in overviewHorizonList" :key="h" :label="`${h}日均值`" width="100" align="right">
          <template #default="{ row }">
            <span :class="getRateClass(row.avg_returns?.[`${h}d`])">{{ formatRate(row.avg_returns?.[`${h}d`]) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100" align="center" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="selectStrategyFromOverview(row.strategy_name)">查看明细</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card ref="timelineCardRef" shadow="never" class="result-card">
      <template #header>
        <span class="card-title">策略时间序列（按信号日平均收益）</span>
      </template>

      <el-form inline label-width="120px" style="margin-bottom: 8px">
        <el-form-item label="区间(天)">
          <el-input-number v-model="timelineDays" :min="1" :max="365" :disabled="hasExplicitRange" />
        </el-form-item>
        <el-form-item label="收益周期(天)">
          <el-select v-model="timelineHorizon" style="width: 140px">
            <el-option v-for="h in overviewHorizonList" :key="h" :label="`${h}日`" :value="h" />
          </el-select>
        </el-form-item>
        <el-form-item label="策略">
          <el-select v-model="timelineStrategies" multiple filterable style="width: 360px">
            <el-option v-for="s in overviewItems" :key="s.strategy_name" :label="s.strategy_cn" :value="s.strategy_name" />
          </el-select>
        </el-form-item>
      </el-form>

      <div ref="timelineChartRef" class="chart"></div>
    </el-card>

    <el-card ref="detailCardRef" shadow="never" class="result-card">
      <template #header>
        <span class="card-title">策略明细（选股列表）</span>
      </template>

      <el-form inline label-width="120px" style="margin-bottom: 8px">
        <el-form-item label="策略">
          <el-select v-model="selectedStrategy" style="width: 280px" @change="detailPage = 1; pairPage = 1; refreshAll()">
            <el-option v-for="s in overviewItems" :key="s.strategy_name" :label="s.strategy_cn" :value="s.strategy_name" />
          </el-select>
        </el-form-item>
        <el-form-item label="区间(天)">
          <el-input-number v-model="detailDays" :min="1" :max="365" :disabled="hasExplicitRange" @change="detailPage = 1; refreshAll()" />
        </el-form-item>
        <el-form-item label="收益周期">
          <el-select v-model="detailHorizons" multiple filterable allow-create default-first-option :reserve-keyword="false" style="width: 360px" @change="detailPage = 1; refreshAll()">
            <el-option v-for="h in detailHorizons" :key="h" :label="`${h}日`" :value="h" />
          </el-select>
        </el-form-item>
      </el-form>

      <el-table v-if="!isMobile" :data="detail?.rows || []" border size="small" stripe>
        <el-table-column prop="date" label="日期" width="120" align="center" />
        <el-table-column prop="code" label="代码" width="100" align="center" />
        <el-table-column prop="name" label="名称" min-width="120" />
        <el-table-column v-for="h in (detail?.horizons || [])" :key="h" :label="`${h}日收益`" width="110" align="right">
          <template #default="{ row }">
            <span :class="getRateClass(row[`rate_${h}`])">{{ formatRate(row[`rate_${h}`]) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="跳转" width="140" align="center">
          <template #default="{ row }">
            <el-button link type="primary" @click="goIndicatorDetail(row)">K线指标</el-button>
            <el-button link type="primary" @click="goCustomBacktest(row)">单股回测</el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 移动端卡片视图 -->
      <div v-if="isMobile" class="bd-card-list">
        <el-empty v-if="(detail?.rows || []).length === 0" description="暂无明细" :image-size="60" />
        <div v-for="(row, ri) in (detail?.rows || [])" :key="ri" class="bd-card">
          <div class="bd-card-head">
            <span class="bd-card-title">{{ row.code }} {{ row.name }}</span>
            <span class="bd-card-date">{{ row.date }}</span>
          </div>
          <div class="bd-card-body">
            <div v-for="h in (detail?.horizons || [])" :key="h" class="bd-field">
              <span class="bd-lbl">{{ h }}日收益</span>
              <span :class="getRateClass(row[`rate_${h}`])">{{ formatRate(row[`rate_${h}`]) }}</span>
            </div>
          </div>
          <div class="bd-card-ops">
            <span class="bd-op" @click="goIndicatorDetail(row)">K线指标</span>
            <span class="bd-op-sep">|</span>
            <span class="bd-op" @click="goCustomBacktest(row)">单股回测</span>
          </div>
        </div>
      </div>

      <div class="pager">
        <el-pagination
          background
          layout="prev, pager, next"
          :current-page="detailPage"
          :page-size="detailPageSize"
          :total="detail?.total || 0"
          @current-change="(p:number) => { detailPage = p; loadStrategyDetail().catch(() => {}) }"
        />
      </div>
    </el-card>

    <el-card shadow="never" class="result-card">
      <template #header>
        <span class="card-title">收益分布</span>
      </template>

      <el-form inline label-width="120px" style="margin-bottom: 8px">
        <el-form-item label="区间(天)">
          <el-input-number v-model="distDays" :min="1" :max="365" :disabled="hasExplicitRange" @change="refreshAll()" />
        </el-form-item>
        <el-form-item label="收益周期(天)">
          <el-input-number v-model="distHorizon" :min="1" :max="100" @change="refreshAll()" />
        </el-form-item>
      </el-form>

      <el-table :data="distribution?.bins || []" border size="small" stripe style="max-width: 520px">
        <el-table-column prop="range" label="区间" width="140" />
        <el-table-column prop="count" label="数量" width="100" align="right" />
        <el-table-column prop="percentage" label="占比" width="120" align="right">
          <template #default="{ row }">{{ row.percentage }}%</template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card shadow="never" class="result-card">
      <template #header>
        <span class="card-title">买入-卖出配对（卖出点来自指标卖出表）</span>
      </template>

      <el-form inline label-width="120px" style="margin-bottom: 8px">
        <el-form-item label="区间(天)">
          <el-input-number v-model="pairDays" :min="1" :max="365" :disabled="hasExplicitRange" @change="pairPage = 1; refreshAll()" />
        </el-form-item>
        <el-form-item label="最大持有(天)">
          <el-input-number v-model="pairMaxHold" :min="1" :max="250" @change="pairPage = 1; refreshAll()" />
        </el-form-item>
      </el-form>

      <el-table v-if="!isMobile" :data="tradePairs?.rows || []" border size="small" stripe>
        <el-table-column prop="buy_date" label="买入日" width="120" align="center" />
        <el-table-column prop="sell_date" label="卖出日" width="120" align="center" />
        <el-table-column prop="code" label="代码" width="100" align="center" />
        <el-table-column prop="name" label="名称" min-width="120" />
        <el-table-column prop="hold_days" label="持有" width="80" align="right" />
        <el-table-column prop="buy_price" label="买入价" width="90" align="right" />
        <el-table-column prop="sell_price" label="卖出价" width="90" align="right" />
        <el-table-column prop="return_rate" label="收益" width="110" align="right">
          <template #default="{ row }">
            <span :class="getRateClass(row.return_rate)">{{ formatRate(row.return_rate) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="跳转" width="140" align="center">
          <template #default="{ row }">
            <el-button link type="primary" @click="goIndicatorDetail({ code: row.code, name: row.name, date: row.buy_date })">K线指标</el-button>
            <el-button link type="primary" @click="goCustomBacktest({ code: row.code, name: row.name })">单股回测</el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 移动端卡片视图 -->
      <div v-if="isMobile" class="bd-card-list">
        <el-empty v-if="(tradePairs?.rows || []).length === 0" description="暂无配对" :image-size="60" />
        <div v-for="(row, ri) in (tradePairs?.rows || [])" :key="ri" class="bd-card">
          <div class="bd-card-head">
            <span class="bd-card-title">{{ row.code }} {{ row.name }}</span>
            <span :class="getRateClass(row.return_rate)">{{ formatRate(row.return_rate) }}</span>
          </div>
          <div class="bd-card-body">
            <div class="bd-field"><span class="bd-lbl">买入日</span><span>{{ row.buy_date }}</span></div>
            <div class="bd-field"><span class="bd-lbl">卖出日</span><span>{{ row.sell_date }}</span></div>
            <div class="bd-field"><span class="bd-lbl">持有(天)</span><span>{{ row.hold_days }}</span></div>
            <div class="bd-field"><span class="bd-lbl">买入价</span><span>{{ row.buy_price }}</span></div>
            <div class="bd-field"><span class="bd-lbl">卖出价</span><span>{{ row.sell_price }}</span></div>
          </div>
          <div class="bd-card-ops">
            <span class="bd-op" @click="goIndicatorDetail({ code: row.code, name: row.name, date: row.buy_date })">K线指标</span>
            <span class="bd-op-sep">|</span>
            <span class="bd-op" @click="goCustomBacktest({ code: row.code, name: row.name })">单股回测</span>
          </div>
        </div>
      </div>

      <div class="pager">
        <el-pagination
          background
          layout="prev, pager, next"
          :current-page="pairPage"
          :page-size="pairPageSize"
          :total="tradePairs?.total || 0"
          @current-change="(p:number) => { pairPage = p; loadTradePairs().catch(() => {}) }"
        />
      </div>
    </el-card>
  </div>
</template>

<style lang="scss" scoped>
.dashboard-container {
  padding: 0;
}

.config-card {
  margin-bottom: 16px;
}

.result-card {
  margin-bottom: 16px;
}

.card-title {
  font-size: 16px;
  font-weight: 600;
}

.header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.chart {
  height: 320px;
  width: 100%;
}

.pager {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}

.text-up {
  color: #f56c6c;
  font-weight: 500;
}

.text-down {
  color: #67c23a;
  font-weight: 500;
}

/* ─── 移动端卡片视图 ─── */
.bd-card-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.bd-card {
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 10px 12px;
}
.bd-card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-bottom: 8px;
  border-bottom: 1px dashed #ebeef5;
}
.bd-card-title {
  font-weight: 600;
  color: #303133;
  font-size: 14px;
}
.bd-card-date {
  font-size: 12px;
  color: #909399;
}
.bd-card-body {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px 12px;
  font-size: 13px;
  padding: 8px 0;
}
.bd-field {
  display: flex;
  justify-content: space-between;
}
.bd-lbl {
  color: #909399;
}
.bd-card-ops {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 8px;
  padding-top: 8px;
  border-top: 1px dashed #ebeef5;
}
.bd-op {
  color: #409eff;
  cursor: pointer;
  font-size: 13px;
}
.bd-op-sep {
  color: #dcdfe6;
}

@include sm-down {
  .config-card,
  .result-card {
    margin-bottom: 12px;
  }
  .header-row {
    flex-wrap: wrap;
    gap: 8px;
  }
  .chart {
    height: 240px;
  }
  :deep(.el-form--inline) {
    .el-form-item {
      display: flex;
      margin-right: 0;
      margin-bottom: 10px;
      width: 100%;
    }
    .el-form-item__content {
      flex: 1;
    }
    .el-form-item__content > * {
      width: 100% !important;
    }
  }
  .pager {
    justify-content: center;
  }
}
</style>
