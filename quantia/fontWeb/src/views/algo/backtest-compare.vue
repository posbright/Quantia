<template>
  <div class="bt-compare" v-loading="loading">
    <!-- Header -->
    <div class="compare-header">
      <el-button text @click="$router.back()">
        <el-icon><ArrowLeft /></el-icon> 返回
      </el-button>
      <h3>回测对比</h3>
      <span class="header-sub" v-if="backtests.length">
        {{ backtests.length }} 个策略对比
      </span>
    </div>

    <template v-if="!loading && backtests.length > 0">
      <el-tabs v-model="activeTab" @tab-click="onTabClick">
        <!-- Tab 1: 收益走势对比 -->
        <el-tab-pane label="收益走势" name="chart">
          <div ref="chartEl" class="chart-box"></div>
        </el-tab-pane>

        <!-- Tab 2: 指标对比表 -->
        <el-tab-pane label="指标对比" name="metrics">
          <div class="metrics-compare">
            <table class="cmp-table">
              <thead>
                <tr>
                  <th class="cmp-lbl">指标</th>
                  <th v-for="bt in backtests" :key="bt.id" class="cmp-val">
                    <div class="cmp-hdr">
                      <span class="cmp-name">{{ bt.strategy_name }}</span>
                      <span class="cmp-id">#{{ bt.id }}</span>
                    </div>
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in metricRows" :key="row.key">
                  <td class="cmp-lbl">{{ row.label }}</td>
                  <td v-for="bt in backtests" :key="bt.id" class="cmp-val"
                      :class="{ 'is-best': row.bestId === bt.id }">
                    <span :class="row.colorFn ? row.colorFn(row.getValue(bt)) : ''">
                      {{ row.format(row.getValue(bt)) }}
                    </span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </el-tab-pane>

        <!-- Tab 3: 交易统计对比 -->
        <el-tab-pane label="交易统计" name="trades">
          <div class="metrics-compare">
            <table class="cmp-table">
              <thead>
                <tr>
                  <th class="cmp-lbl">统计项</th>
                  <th v-for="bt in backtests" :key="bt.id" class="cmp-val">
                    <span class="cmp-name">{{ bt.strategy_name }}</span>
                    <span class="cmp-id">#{{ bt.id }}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td class="cmp-lbl">总交易次数</td>
                  <td v-for="bt in backtests" :key="bt.id" class="cmp-val">{{ bt.trades?.length || 0 }}</td>
                </tr>
                <tr>
                  <td class="cmp-lbl">买入次数</td>
                  <td v-for="bt in backtests" :key="bt.id" class="cmp-val">{{ countTrades(bt, 'buy') }}</td>
                </tr>
                <tr>
                  <td class="cmp-lbl">卖出次数</td>
                  <td v-for="bt in backtests" :key="bt.id" class="cmp-val">{{ countTrades(bt, 'sell') }}</td>
                </tr>
                <tr>
                  <td class="cmp-lbl">首次交易</td>
                  <td v-for="bt in backtests" :key="bt.id" class="cmp-val">{{ firstTradeDate(bt) }}</td>
                </tr>
                <tr>
                  <td class="cmp-lbl">末次交易</td>
                  <td v-for="bt in backtests" :key="bt.id" class="cmp-val">{{ lastTradeDate(bt) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </el-tab-pane>

        <!-- Tab 4: 策略代码对比 & 调参回测 -->
        <el-tab-pane label="代码对比" name="code">
          <div class="code-compare">
            <div class="code-panels">
              <div v-for="(bt, idx) in backtests" :key="bt.id" class="code-panel">
                <div class="code-panel-header">
                  <span class="cmp-name">{{ bt.strategy_name }} #{{ bt.id }}</span>
                  <el-tag size="small" :type="idx === editingIdx ? 'warning' : 'info'">
                    {{ idx === editingIdx ? '编辑中' : '原始' }}
                  </el-tag>
                </div>
                <div class="code-params">
                  <el-form :inline="true" size="small">
                    <el-form-item label="开始">
                      <el-date-picker v-model="paramEditors[idx].start_date" type="date"
                                      value-format="YYYY-MM-DD" style="width: 130px;" />
                    </el-form-item>
                    <el-form-item label="结束">
                      <el-date-picker v-model="paramEditors[idx].end_date" type="date"
                                      value-format="YYYY-MM-DD" style="width: 130px;" />
                    </el-form-item>
                    <el-form-item label="资金">
                      <el-input-number v-model="paramEditors[idx].initial_cash" :min="10000" :step="100000" style="width: 130px;" />
                    </el-form-item>
                    <el-form-item label="基准">
                      <el-input v-model="paramEditors[idx].benchmark" style="width: 100px;" />
                    </el-form-item>
                  </el-form>
                </div>
                <el-input v-model="codeEditors[idx]" type="textarea" :rows="18"
                          @focus="editingIdx = idx"
                          class="code-editor" />
                <div class="code-panel-actions">
                  <el-button size="small" @click="resetCode(idx)">重置</el-button>
                  <el-button size="small" type="primary" @click="runModifiedBacktest(idx)" :loading="runningIdx === idx">
                    运行回测
                  </el-button>
                </div>
              </div>
            </div>
            <!-- 新回测结果 -->
            <div v-if="newBacktestResult" class="new-result-card">
              <el-alert title="新回测完成" type="success" :closable="false" style="margin-bottom: 12px">
                <template #default>
                  策略收益: <b :class="pctCls(newBacktestResult.metrics?.total_return)">{{ fmtPct(newBacktestResult.metrics?.total_return) }}</b>
                  &nbsp;|&nbsp; 年化: <b>{{ fmtPct(newBacktestResult.metrics?.annual_return) }}</b>
                  &nbsp;|&nbsp; 最大回撤: <b class="val-green">{{ fmtPct(newBacktestResult.metrics?.max_drawdown) }}</b>
                  &nbsp;|&nbsp; 夏普: <b>{{ fmtNum(newBacktestResult.metrics?.sharpe_ratio) }}</b>
                  <span v-if="newBacktestResult.backtest_id">
                    &nbsp;|&nbsp; <el-link type="primary" @click="viewNewBacktest">查看详情 #{{ newBacktestResult.backtest_id }}</el-link>
                  </span>
                </template>
              </el-alert>
            </div>
          </div>
        </el-tab-pane>
      </el-tabs>
    </template>

    <el-empty v-if="!loading && backtests.length === 0" description="未加载到对比数据" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, onActivated, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft } from '@element-plus/icons-vue'
import { getBacktestCompare, runPortfolioBacktest } from '@/api/stock'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'
import { useResponsive } from '@/composables/useResponsive'

const route = useRoute()
const router = useRouter()
const { isMobile } = useResponsive()
const loading = ref(false)
const activeTab = ref('chart')
const backtests = ref<any[]>([])
const codeEditors = ref<string[]>([])
const paramEditors = ref<any[]>([])
const editingIdx = ref(0)
const runningIdx = ref(-1)
const newBacktestResult = ref<any>(null)
let lastLoadedIds = ''  // 记录上次加载的 ids 参数，用于 keep-alive 激活时判断是否重新加载

const chartEl = ref<HTMLElement>()
let chart: echarts.ECharts | null = null

function fmtPct(v: number | undefined | null, d = 2) {
  if (v == null) return '--'
  return `${Number(v) >= 0 ? '+' : ''}${Number(v).toFixed(d)}%`
}
function fmtNum(v: number | undefined | null, d = 3) {
  if (v == null) return '--'
  return Number(v).toFixed(d)
}
function pctCls(v: number | undefined | null) {
  if (v == null || v === 0) return ''
  return Number(v) > 0 ? 'val-red' : 'val-green'
}

// ── 指标对比行定义 ──
type MetricRow = {
  key: string; label: string
  getValue: (bt: any) => number
  format: (v: number) => string
  higher?: boolean
  lower?: boolean
  colorFn?: (v: number) => string
  bestId?: number
}

const metricRows = computed<MetricRow[]>(() => {
  const rows: MetricRow[] = [
    { key: 'total_return', label: '策略收益', getValue: bt => bt.metrics?.total_return ?? 0, format: v => fmtPct(v), higher: true, colorFn: pctCls },
    { key: 'annual_return', label: '年化收益', getValue: bt => bt.metrics?.annual_return ?? 0, format: v => fmtPct(v), higher: true, colorFn: pctCls },
    { key: 'benchmark_return', label: '基准收益', getValue: bt => bt.metrics?.benchmark_return ?? 0, format: v => fmtPct(v), colorFn: pctCls },
    { key: 'excess_return', label: '超额收益', getValue: bt => bt.metrics?.excess_return ?? 0, format: v => fmtPct(v), higher: true, colorFn: pctCls },
    { key: 'max_drawdown', label: '最大回撤', getValue: bt => bt.metrics?.max_drawdown ?? 0, format: v => fmtPct(v), lower: true },
    { key: 'sharpe_ratio', label: '夏普比率', getValue: bt => bt.metrics?.sharpe_ratio ?? 0, format: v => fmtNum(v), higher: true },
    { key: 'sortino_ratio', label: '索提诺比率', getValue: bt => bt.metrics?.sortino_ratio ?? 0, format: v => fmtNum(v), higher: true },
    { key: 'information_ratio', label: '信息比率', getValue: bt => bt.metrics?.information_ratio ?? 0, format: v => fmtNum(v), higher: true },
    { key: 'alpha', label: '阿尔法', getValue: bt => bt.metrics?.alpha ?? 0, format: v => fmtNum(v), higher: true },
    { key: 'beta', label: '贝塔', getValue: bt => bt.metrics?.beta ?? 0, format: v => fmtNum(v) },
    { key: 'strategy_volatility', label: '策略波动率', getValue: bt => bt.metrics?.strategy_volatility ?? 0, format: v => fmtPct(v), lower: true },
    { key: 'trade_win_rate', label: '胜率', getValue: bt => bt.metrics?.trade_win_rate ?? 0, format: v => fmtPct(v, 1), higher: true },
    { key: 'profit_loss_ratio', label: '盈亏比', getValue: bt => bt.metrics?.profit_loss_ratio ?? 0, format: v => fmtNum(v), higher: true },
    { key: 'trade_count', label: '交易次数', getValue: bt => bt.metrics?.trade_count ?? 0, format: v => String(Math.round(v)) },
  ]
  for (const row of rows) {
    if (row.higher || row.lower) {
      let bestVal = row.higher ? -Infinity : Infinity
      let bestId = 0
      for (const bt of backtests.value) {
        const v = row.getValue(bt)
        if (row.higher && v > bestVal) { bestVal = v; bestId = bt.id }
        if (row.lower && v < bestVal) { bestVal = v; bestId = bt.id }
      }
      row.bestId = bestId
    }
  }
  return rows
})

function countTrades(bt: any, dir: string) {
  return (bt.trades || []).filter((t: any) => t.direction === dir).length
}
function firstTradeDate(bt: any) {
  const t = bt.trades
  return t && t.length > 0 ? t[0].date : '-'
}
function lastTradeDate(bt: any) {
  const t = bt.trades
  return t && t.length > 0 ? t[t.length - 1].date : '-'
}

// ── 重置代码 ──
function resetCode(idx: number) {
  const bt = backtests.value[idx]
  codeEditors.value[idx] = bt.strategy_code || ''
  paramEditors.value[idx] = {
    start_date: bt.start_date,
    end_date: bt.end_date,
    initial_cash: bt.initial_cash || 1000000,
    benchmark: bt.params?.benchmark || '000300',
  }
}

// ── 运行修改后的回测 ──
async function runModifiedBacktest(idx: number) {
  const bt = backtests.value[idx]
  const code = codeEditors.value[idx]
  const params = paramEditors.value[idx]
  if (!code?.trim()) { ElMessage.warning('策略代码不能为空'); return }

  runningIdx.value = idx
  newBacktestResult.value = null
  try {
    const res = await runPortfolioBacktest({
      code,
      strategy_id: bt.strategy_id,
      start_date: params.start_date || bt.start_date,
      end_date: params.end_date || bt.end_date,
      initial_cash: params.initial_cash || bt.initial_cash,
      benchmark: params.benchmark || '000300',
    }) as any
    const data = res?.code === 0 ? res.data : (res?.data || res)
    if (data?.status === 'completed') {
      newBacktestResult.value = data
      ElMessage.success('回测完成')
    } else {
      ElMessage.error(data?.message || data?.msg || '回测失败')
    }
  } catch (e: any) {
    ElMessage.error(e?.message || '回测运行异常')
  } finally {
    runningIdx.value = -1
  }
}

function viewNewBacktest() {
  if (newBacktestResult.value?.backtest_id) {
    router.push('/algo/backtest-detail/' + newBacktestResult.value.backtest_id)
  }
}

// ── 图表 ──
const COLORS = ['#e6a23c', '#409eff', '#67c23a', '#f56c6c', '#909399', '#ff6b81', '#7f5af0', '#00cec9', '#fd79a8', '#636e72']

function renderChart() {
  const el = chartEl.value
  if (!el || backtests.value.length === 0) return
  // 等待 DOM 可见
  if (el.clientWidth === 0 || el.clientHeight === 0) {
    setTimeout(renderChart, 150)
    return
  }
  if (chart) { chart.dispose(); chart = null }
  chart = echarts.init(el)

  const allDates = new Set<string>()
  backtests.value.forEach(bt => {
    (bt.nav || []).forEach((r: any) => allDates.add(r.date))
  })
  const dates = Array.from(allDates).sort()

  if (dates.length === 0) {
    chart.setOption({ title: { text: '无净值数据', left: 'center', top: 'center', textStyle: { color: '#909399', fontSize: 14 } } })
    return
  }

  const legend: string[] = []
  const series: any[] = []

  backtests.value.forEach((bt, i) => {
    const name = `${bt.strategy_name} #${bt.id}`
    legend.push(name)
    const navMap = new Map<string, number>()
    ;(bt.nav || []).forEach((r: any) => navMap.set(r.date, r.nav))
    const data = dates.map(d => {
      const nav = navMap.get(d)
      return nav != null ? +((nav - 1) * 100).toFixed(2) : null
    })
    series.push({
      name, type: 'line', data, symbol: 'none', connectNulls: true,
      lineStyle: { width: 2, color: COLORS[i % COLORS.length] },
      itemStyle: { color: COLORS[i % COLORS.length] },
    })
  })

  chart.setOption({
    tooltip: {
      trigger: 'axis',
      formatter(p: any) {
        if (!p || !p.length) return ''
        let h = `<b>${p[0].axisValue}</b>`
        p.forEach((s: any) => {
          if (s.value != null) h += `<br/>${s.marker} ${s.seriesName}: ${s.value >= 0 ? '+' : ''}${s.value}%`
        })
        return h
      },
    },
    legend: { data: legend, top: 4, textStyle: { fontSize: 11 } },
    grid: { left: isMobile.value ? 40 : 55, right: isMobile.value ? 8 : 20, top: 40, bottom: 36 },
    dataZoom: [{ type: 'inside', start: 0, end: 100 }],
    xAxis: { type: 'category', data: dates, boundaryGap: false, axisLabel: { fontSize: 10 } },
    yAxis: { type: 'value', axisLabel: { formatter: '{value}%', fontSize: 10 }, splitLine: { lineStyle: { type: 'dashed', color: '#eee' } } },
    series,
  })
}

function onTabClick() {
  if (activeTab.value === 'chart') {
    nextTick(() => setTimeout(renderChart, 100))
  }
}

// ── lifecycle ──
async function loadCompareData() {
  const idsParam = route.query.ids as string
  if (!idsParam) { ElMessage.error('缺少回测ID参数'); return }

  // 清理旧状态
  if (chart) { chart.dispose(); chart = null }
  backtests.value = []
  codeEditors.value = []
  paramEditors.value = []
  activeTab.value = 'chart'
  editingIdx.value = 0
  runningIdx.value = -1
  newBacktestResult.value = null

  loading.value = true
  try {
    const res = await getBacktestCompare(idsParam.split(',').map(Number)) as any
    // res is {code: 0, data: {backtests: [...]}} (axios interceptor unwraps response.data)
    let data: any
    if (res?.code === 0) {
      data = res.data
    } else {
      data = res?.data || res
    }
    const btList = data?.backtests || []
    backtests.value = btList
    codeEditors.value = btList.map((bt: any) => bt.strategy_code || '')
    paramEditors.value = btList.map((bt: any) => ({
      start_date: bt.start_date,
      end_date: bt.end_date,
      initial_cash: bt.initial_cash || 1000000,
      benchmark: bt.params?.benchmark || '000300',
    }))
    lastLoadedIds = idsParam

    if (btList.length === 0) {
      ElMessage.warning('未找到回测数据')
    } else {
      // 等待 DOM 渲染完成后再画图表
      await nextTick()
      setTimeout(renderChart, 200)
    }
  } catch (e: any) {
    console.error('加载对比数据失败', e)
    ElMessage.error(e?.message || '加载对比数据失败')
  } finally {
    loading.value = false
  }
}

onMounted(() => loadCompareData())

// keep-alive 激活时，检查 ids 参数是否变化，如有变化则重新加载
onActivated(() => {
  const idsParam = (route.query.ids as string) || ''
  if (idsParam && idsParam !== lastLoadedIds) {
    loadCompareData()
  }
})

// 同一组件激活期间，路由 query.ids 变化时也重新加载
watch(() => route.query.ids, (newIds, oldIds) => {
  if (newIds && newIds !== oldIds && newIds !== lastLoadedIds) {
    loadCompareData()
  }
})

const onResize = () => chart?.resize()
window.addEventListener('resize', onResize)
onUnmounted(() => { window.removeEventListener('resize', onResize); chart?.dispose() })
</script>

<style scoped>
.bt-compare { padding: 16px 20px; }
.compare-header { display: flex; align-items: center; gap: 12px; margin-bottom: 14px; }
.compare-header h3 { margin: 0; font-size: 16px; }
.header-sub { color: #909399; font-size: 13px; }

.chart-box { width: 100%; height: 420px; min-height: 300px; }

/* ── 指标对比表格（聚宽风格） ── */
.metrics-compare { overflow-x: auto; }
.cmp-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.cmp-table th, .cmp-table td { padding: 10px 14px; border-bottom: 1px solid #f0f0f0; }
.cmp-table thead th { background: #fafafa; font-weight: 600; text-align: center; }
.cmp-lbl { color: #606266; white-space: nowrap; width: 120px; background: #fafafa; text-align: left; }
.cmp-val { text-align: center; font-variant-numeric: tabular-nums; }
.cmp-val.is-best { background: #fef0e1; font-weight: 700; }
.cmp-hdr { display: flex; flex-direction: column; align-items: center; gap: 2px; }
.cmp-name { font-weight: 600; }
.cmp-id { color: #909399; font-size: 11px; }
.val-red { color: #f56c6c !important; }
.val-green { color: #67c23a !important; }

/* ── 代码对比面板 ── */
.code-compare { margin-top: 8px; }
.code-panels { display: grid; grid-template-columns: repeat(auto-fit, minmax(480px, 1fr)); gap: 16px; }
.code-panel { border: 1px solid #ebeef5; border-radius: 6px; overflow: hidden; }
.code-panel-header { display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; background: #fafafa; border-bottom: 1px solid #ebeef5; }
.code-params { padding: 8px 12px; background: #fafcff; border-bottom: 1px solid #ebeef5; }
.code-params :deep(.el-form-item) { margin-bottom: 0; margin-right: 12px; }
.code-params :deep(.el-form-item__label) { font-size: 12px; }
.code-editor :deep(.el-textarea__inner) { font-family: 'Consolas', 'Monaco', 'Courier New', monospace; font-size: 12px; line-height: 1.6; border: none; border-radius: 0; }
.code-panel-actions { padding: 8px 12px; text-align: right; border-top: 1px solid #ebeef5; display: flex; justify-content: flex-end; gap: 8px; }
.new-result-card { margin-top: 16px; }

/* ── PR-10 F: 移动端适配 ── */
@media (max-width: 991.98px) {
  /* 代码对比面板：自动换行（最小宽度从 480 降到 320） */
  .code-panels { grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 12px; }
}
@media (max-width: 767.98px) {
  .bt-compare { padding: 10px 12px; }
  .compare-header { flex-wrap: wrap; gap: 6px 10px; }
  .compare-header h3 { font-size: 15px; }
  .header-sub { flex-basis: 100%; font-size: 12px; }
  .chart-box { height: 300px; min-height: 240px; }
  /* 对比表：缩小字号 + 第一列 sticky */
  .cmp-table { font-size: 11px; }
  .cmp-table th, .cmp-table td { padding: 6px 8px; }
  .cmp-lbl {
    width: auto;
    min-width: 84px;
    position: sticky; left: 0; z-index: 1;
  }
  .cmp-name { font-size: 11px; }
  .cmp-id { font-size: 10px; }
  /* 代码对比单列、行编辑器折叠 */
  .code-panels { grid-template-columns: 1fr; gap: 10px; }
  .code-panel { font-size: 12px; }
  .code-params :deep(.el-form-item) { margin-right: 6px; margin-bottom: 6px; }
  .code-params :deep(.el-form-item__label) { font-size: 11px; }
  :deep(.el-tabs__item) { padding: 0 10px; font-size: 13px; }
}
</style>
