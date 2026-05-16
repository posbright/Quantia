<template>
  <div class="verify-compare">
    <!-- 使用说明 -->
    <UsageGuide
      title="📖 策略对比 使用说明（点击展开）"
      :steps="guideSteps"
      :example="guideExample"
      :metrics="guideMetrics"
      :tips="guideTips"
    />
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
        unlink-panels
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
              <th><el-tooltip content="持仓期结束后的平均涨跌幅。正值=整体盈利" placement="top"><span class="th-tip">平均收益% <i class="tip-icon">?</i></span></el-tooltip></th>
              <th><el-tooltip content="盈利信号占总信号比例。>55%较好，>65%优秀" placement="top"><span class="th-tip">胜率% <i class="tip-icon">?</i></span></el-tooltip></th>
              <th><el-tooltip content="(年化收益-无风险利率)/波动率。>1良好，>2优秀" placement="top"><span class="th-tip">年化夏普 <i class="tip-icon">?</i></span></el-tooltip></th>
              <th><el-tooltip content="只惩罚下行波动的夏普变种。>1.5良好" placement="top"><span class="th-tip">Sortino <i class="tip-icon">?</i></span></el-tooltip></th>
              <th><el-tooltip content="最差一笔信号的亏损幅度，用于评估尾部风险" placement="top"><span class="th-tip">最大单笔亏损% <i class="tip-icon">?</i></span></el-tooltip></th>
              <th><el-tooltip content="最好一笔信号的盈利幅度" placement="top"><span class="th-tip">最大单笔盈利% <i class="tip-icon">?</i></span></el-tooltip></th>
              <th><el-tooltip content="收益分布第10百分位(尾部亏损风险)" placement="top"><span class="th-tip">P10 <i class="tip-icon">?</i></span></el-tooltip></th>
              <th><el-tooltip content="收益分布第90百分位(盈利上限)" placement="top"><span class="th-tip">P90 <i class="tip-icon">?</i></span></el-tooltip></th>
              <th><el-tooltip content="该策略在选定时段产生的买入信号总数。越多统计越可靠" placement="top"><span class="th-tip">信号数 <i class="tip-icon">?</i></span></el-tooltip></th>
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

    <!-- 综合评分 + 雷达图 -->
    <el-row v-if="compareData.length > 1" :gutter="16" style="margin-top: 16px">
      <el-col :span="16">
        <el-card shadow="never">
          <template #header><span>综合评分排名</span></template>
          <div class="rank-list">
            <div v-for="(item, idx) in rankedData" :key="item.strategy" class="rank-item" :class="{ 'rank-best': idx === 0 }">
              <span class="rank-num">{{ idx + 1 }}</span>
              <span class="rank-name">{{ item.strategy_cn || item.strategy }}</span>
              <el-progress :percentage="item._score" :stroke-width="12" :color="idx === 0 ? '#cf1322' : idx === rankedData.length - 1 ? '#bfbfbf' : '#1890ff'" style="flex: 1; margin: 0 12px" />
              <span class="rank-score">{{ item._score.toFixed(1) }}</span>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="never">
          <template #header><span>能力雷达</span></template>
          <div ref="radarChartRef" style="height: 220px" />
        </el-card>
      </el-col>
    </el-row>

    <!-- 累计收益走势 + 水下回撤 -->
    <el-card v-if="seriesData.length > 0" shadow="never" style="margin-top: 16px">
      <template #header><span>累计收益走势 & 水下回撤</span></template>
      <div ref="navChartRef" style="height: 380px" />
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

    <!-- 关键发现 -->
    <el-card v-if="insights.length > 0" shadow="never" style="margin-top: 16px; border-left: 3px solid #409eff">
      <template #header><span>💡 多策略对比关键发现</span></template>
      <div class="insights-body">
        <div v-for="(insight, idx) in insights" :key="idx" class="insight-item">
          {{ idx + 1 }}. <span v-html="insight"></span>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'
import { getHoldingPeriod, getSignalDecay, getMarketRegime, getReturnSeries } from '@/api/verify'
import UsageGuide from '@/components/verify/UsageGuide.vue'

const guideSteps = [
  '在左侧下拉框中选择 <b>1~5 个策略</b>（支持分组搜索）',
  '选择 <b>持仓周期</b>（建议先用 5~10 天观察短线效果）',
  '设定 <b>日期范围</b>（建议至少覆盖 6 个月，含牛熊市场）',
  '点击 <b>"对比分析"</b> 按钮，等待计算完成',
  '查看下方 <b>指标矩阵</b>、<b>综合评分排名</b>、<b>雷达图</b>、<b>收益走势</b> 等结果',
]
const guideExample = `<b>场景：</b>比较"放量上涨"与"海龟交易"策略在 2025 年的表现<br/>
<b>操作：</b>选择两个策略 → 持仓周期选 10天 → 日期选 2025-01-01 至 2025-12-31 → 点击对比分析<br/>
<b>预期：</b>矩阵表显示两策略的收益/夏普/胜率对比，雷达图可视化多维能力差异，底部"关键发现"自动总结优劣`
const guideMetrics = [
  { name: '平均收益%', desc: '所有买入信号在持仓期结束后的平均涨跌幅', range: '-∞ ~ +∞（A股通常 -5% ~ +8%）', good: '> 2% 为优秀' },
  { name: '胜率%', desc: '盈利信号数 / 总信号数 × 100%', range: '0% ~ 100%', good: '> 55% 为较好，> 65% 为优秀' },
  { name: '年化夏普', desc: '(年化收益 - 无风险利率) / 年化波动率，衡量风险调整后收益', range: '-∞ ~ +∞', good: '> 1.0 良好，> 2.0 优秀，> 3.0 卓越' },
  { name: 'Sortino', desc: '类似夏普，但只考虑下行波动（惩罚亏损而非盈利波动）', range: '-∞ ~ +∞', good: '> 1.5 良好，> 2.5 优秀' },
  { name: '最大单笔亏损%', desc: '所有信号中最差一笔的亏损幅度', range: '-100% ~ 0%', good: '> -8% (即亏损控制在8%以内)' },
  { name: 'P10 / P90', desc: '收益分布的第10/90百分位，反映尾部风险和盈利上限', range: 'P10通常为负，P90通常为正' },
  { name: '综合评分', desc: '夏普×40% + 收益×30% + 回撤控制×20% + 胜率×10% 的归一化加权', range: '0 ~ 100', good: '> 70 为表现突出' },
]
const guideTips = [
  '策略间信号数差异大时，信号少的策略统计置信度较低，需关注信号数列',
  '高夏普 + 低胜率 = 策略依赖少数大盈利覆盖多数小亏损（趋势型）',
  '高胜率 + 低夏普 = 策略盈亏比差，每笔盈利小（均值回归型）',
  '建议选择互补型策略融合使用，可在"策略融合"页进一步实验',
]

const selectedStrategies = ref<string[]>([])
const holdingDays = ref(5)
const dateRange = ref<[string, string]>(['2025-01-01', '2025-12-31'])
const loading = ref(false)
const hasQueried = ref(false)
const compareData = ref<any[]>([])
const decayData = ref<any[]>([])
const regimeData = ref<Record<string, any>>({})
const seriesData = ref<any[]>([])  // [{strategy, strategy_cn, series: [{date, cumulative, drawdown}]}]
const decayChartRef = ref<HTMLElement>()
const radarChartRef = ref<HTMLElement>()
const navChartRef = ref<HTMLElement>()
const rankedData = ref<any[]>([])

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

// 关键发现 - 自动从对比数据生成洞察
const insights = computed(() => {
  if (compareData.value.length < 2) return []
  const data = compareData.value
  const result: string[] = []

  // 找最佳策略
  const bestSharpe = [...data].sort((a, b) => (b.sharpe_approx ?? 0) - (a.sharpe_approx ?? 0))[0]
  const bestWinRate = [...data].sort((a, b) => (b.win_rate ?? 0) - (a.win_rate ?? 0))[0]
  const bestReturn = [...data].sort((a, b) => (b.avg_return ?? 0) - (a.avg_return ?? 0))[0]

  if (bestSharpe) {
    result.push(`<b>${bestSharpe.strategy_cn || bestSharpe.strategy}</b> 夏普比率最高(${fmt(bestSharpe.sharpe_approx)})，风险调整后收益表现最优`)
  }
  if (bestWinRate && bestWinRate.strategy !== bestSharpe?.strategy) {
    result.push(`<b>${bestWinRate.strategy_cn || bestWinRate.strategy}</b> 胜率最高(${fmt(bestWinRate.win_rate)}%)，信号可靠性强`)
  }
  if (bestReturn && bestReturn.strategy !== bestSharpe?.strategy) {
    result.push(`<b>${bestReturn.strategy_cn || bestReturn.strategy}</b> ${holdingDays.value}日平均收益最高(${fmt(bestReturn.avg_return)}%)，但需关注波动`)
  }

  // 提升空间
  if (data.length >= 3) {
    result.push('建议: 将高夏普策略与高胜率策略融合，可进一步提升综合表现 → 前往 <b>"多维融合"</b> 页实验')
  }
  return result
})

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

    // 综合评分 + 雷达图
    computeRanking()
    await nextTick()
    renderRadarChart()

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

    // 各策略累计收益走势
    const seriesPromises = selectedStrategies.value.map(s =>
      getReturnSeries({ strategy: s, start_date: startDate, end_date: endDate, holding_days: holdingDays.value })
    )
    const seriesResults = await Promise.all(seriesPromises)
    seriesData.value = seriesResults.map((r: any) => ({
      strategy: r.strategy,
      strategy_cn: r.strategy_cn,
      series: r.series || [],
    }))
    await nextTick()
    renderNavChart()
  } catch (e: any) {
    ElMessage.error(e.message || '请求失败')
  } finally {
    loading.value = false
  }
}

onUnmounted(() => {
  if (decayChartRef.value) echarts.dispose(decayChartRef.value)
  if (radarChartRef.value) echarts.dispose(radarChartRef.value)
  if (navChartRef.value) echarts.dispose(navChartRef.value)
})

function computeRanking() {
  // 综合评分: 夏普40% + 收益30% + 回撤控制20% + 胜率10%
  const data = compareData.value
  if (data.length === 0) { rankedData.value = []; return }

  // 归一化各维度到 0-100
  const sharpes = data.map(d => d.sharpe_approx ?? 0)
  const returns = data.map(d => d.avg_return ?? 0)
  const winRates = data.map(d => d.win_rate ?? 0)
  const maxLoss = data.map(d => -(d.max_single_loss ?? 0)) // 负越少越好，取反

  function normalize(arr: number[]): number[] {
    const min = Math.min(...arr)
    const max = Math.max(...arr)
    if (max === min) return arr.map(() => 50)
    return arr.map(v => ((v - min) / (max - min)) * 100)
  }

  const nSharpe = normalize(sharpes)
  const nReturn = normalize(returns)
  const nWin = normalize(winRates)
  const nDrawdown = normalize(maxLoss)

  const scored = data.map((d, i) => ({
    ...d,
    _score: nSharpe[i] * 0.4 + nReturn[i] * 0.3 + nDrawdown[i] * 0.2 + nWin[i] * 0.1,
  }))
  scored.sort((a, b) => b._score - a._score)
  rankedData.value = scored
}

function renderRadarChart() {
  if (!radarChartRef.value || compareData.value.length === 0) return
  const existing = echarts.getInstanceByDom(radarChartRef.value)
  if (existing) existing.dispose()
  const chart = echarts.init(radarChartRef.value)

  // 维度: 收益率 / 夏普 / 胜率 / 盈亏比 / 回撤控制 / 稳定性
  const indicators = [
    { name: '收益率', max: 100 },
    { name: '夏普', max: 100 },
    { name: '胜率', max: 100 },
    { name: '回撤控制', max: 100 },
    { name: '稳定性', max: 100 },
  ]

  // 归一化各维度
  const data = compareData.value
  const vals = {
    ret: data.map(d => d.avg_return ?? 0),
    sharpe: data.map(d => d.sharpe_approx ?? 0),
    win: data.map(d => d.win_rate ?? 0),
    dd: data.map(d => -(d.max_single_loss ?? 0)),
    stable: data.map(d => 100 - (d.return_std ?? 0)),
  }

  function norm(arr: number[]): number[] {
    const min = Math.min(...arr)
    const max = Math.max(...arr)
    if (max === min) return arr.map(() => 50)
    return arr.map(v => ((v - min) / (max - min)) * 100)
  }

  const nR = norm(vals.ret), nS = norm(vals.sharpe), nW = norm(vals.win), nD = norm(vals.dd), nSt = norm(vals.stable)

  const series = data.map((d, i) => ({
    name: d.strategy_cn || d.strategy,
    value: [nR[i], nS[i], nW[i], nD[i], nSt[i]],
  }))

  chart.setOption({
    tooltip: {},
    legend: { bottom: 0, data: series.map(s => s.name) },
    radar: { indicator: indicators, radius: 70, center: ['50%', '45%'] },
    series: [{ type: 'radar', data: series.map(s => ({ name: s.name, value: s.value, areaStyle: { opacity: 0.15 } })) }],
  })
}

function renderNavChart() {
  if (!navChartRef.value || seriesData.value.length === 0) return
  const existing = echarts.getInstanceByDom(navChartRef.value)
  if (existing) existing.dispose()
  const chart = echarts.init(navChartRef.value)

  // 颜色列表
  const colors = ['#cf1322', '#1890ff', '#389e0d', '#d46b08', '#722ed1', '#13c2c2']

  // 上部: 累计收益; 下部: 水下回撤
  const cumSeries = seriesData.value.map((item: any, idx: number) => ({
    name: item.strategy_cn || item.strategy,
    type: 'line',
    xAxisIndex: 0,
    yAxisIndex: 0,
    data: item.series.map((p: any) => [p.date, p.cumulative]),
    showSymbol: false,
    lineStyle: { width: 2 },
    itemStyle: { color: colors[idx % colors.length] },
  }))
  const ddSeries = seriesData.value.map((item: any, idx: number) => ({
    name: item.strategy_cn || item.strategy,
    type: 'line',
    xAxisIndex: 1,
    yAxisIndex: 1,
    data: item.series.map((p: any) => [p.date, p.drawdown]),
    showSymbol: false,
    lineStyle: { width: 1.5 },
    areaStyle: { opacity: 0.15 },
    itemStyle: { color: colors[idx % colors.length] },
  }))

  chart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { bottom: 0, data: cumSeries.map(s => s.name) },
    grid: [
      { top: 30, left: 60, right: 20, height: '55%' },
      { left: 60, right: 20, top: '72%', height: '20%' },
    ],
    xAxis: [
      { type: 'category', gridIndex: 0, axisLabel: { show: false }, data: seriesData.value[0]?.series.map((p: any) => p.date) || [] },
      { type: 'category', gridIndex: 1, data: seriesData.value[0]?.series.map((p: any) => p.date) || [] },
    ],
    yAxis: [
      { type: 'value', gridIndex: 0, name: '累计净值', axisLabel: { formatter: '{value}' } },
      { type: 'value', gridIndex: 1, name: '回撤%', axisLabel: { formatter: '{value}%' } },
    ],
    dataZoom: [{ type: 'inside', xAxisIndex: [0, 1] }],
    series: [...cumSeries, ...ddSeries],
  })
}

function renderDecayChart() {
  if (!decayChartRef.value || decayData.value.length === 0) return
  const existing = echarts.getInstanceByDom(decayChartRef.value)
  if (existing) existing.dispose()
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
.rank-list { display: flex; flex-direction: column; gap: 10px; }
.rank-item { display: flex; align-items: center; padding: 6px 8px; border-radius: 4px; }
.rank-item.rank-best { background: #fff7e6; }
.rank-num { width: 24px; height: 24px; border-radius: 50%; background: #f0f0f0; display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 12px; }
.rank-best .rank-num { background: #cf1322; color: #fff; }
.rank-name { width: 80px; font-size: 13px; margin-left: 8px; }
.rank-score { font-weight: 700; font-size: 14px; width: 40px; text-align: right; }
/* 关键发现 */
.insights-body { line-height: 1.8; }
.insight-item { padding: 4px 0; font-size: 13px; color: #333; }
/* Tooltip header tips */
.th-tip { cursor: help; display: inline-flex; align-items: center; gap: 2px; }
.tip-icon { display: inline-flex; align-items: center; justify-content: center; width: 14px; height: 14px; border-radius: 50%; background: #e6e8eb; color: #606266; font-size: 10px; font-style: normal; }
</style>
