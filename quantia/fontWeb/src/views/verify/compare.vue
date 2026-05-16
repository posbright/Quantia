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
      <div class="toolbar-group">
        <span class="toolbar-label">对比策略 (2-6个)</span>
        <div class="chip-area">
          <span v-for="s in selectedStrategies" :key="s" class="chip sel" :style="{ borderColor: getCategoryColor(s) }">
            {{ getStrategyCn(s) }}
            <span class="tag" :class="'t-' + getCategoryKey(s)">{{ getCategoryLabel(s) }}</span>
            <span class="x" @click="removeStrategy(s)">✕</span>
          </span>
          <el-popover placement="bottom" :width="280" trigger="click">
            <template #reference>
              <span class="chip chip-add">+ 添加策略</span>
            </template>
            <div class="strategy-picker">
              <div v-for="group in strategyGroups" :key="group.label" class="picker-group">
                <div class="picker-group-label">{{ group.label }}</div>
                <div
                  v-for="s in group.items" :key="s.value"
                  class="picker-item"
                  :class="{ active: selectedStrategies.includes(s.value), disabled: !selectedStrategies.includes(s.value) && selectedStrategies.length >= 6 }"
                  @click="toggleStrategy(s.value)"
                >
                  <span>{{ s.label }}</span>
                  <span v-if="selectedStrategies.includes(s.value)" style="color:#cf1322">✓</span>
                </div>
              </div>
            </div>
          </el-popover>
        </div>
      </div>
      <div class="toolbar-group">
        <span class="toolbar-label">统计周期</span>
        <div class="radio-group">
          <div v-for="p in periodPresets" :key="p.label" class="radio-btn" :class="{ active: activePeriod === p.label }" @click="setPeriod(p)">{{ p.label }}</div>
        </div>
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          unlink-panels
          range-separator="至"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          value-format="YYYY-MM-DD"
          style="width: 240px; margin-left: 8px"
          @change="activePeriod = ''"
        />
      </div>
      <div class="toolbar-group">
        <span class="toolbar-label">基准指数</span>
        <el-select v-model="benchmarkIndex" style="width: 120px">
          <el-option label="沪深300" value="000300" />
          <el-option label="中证500" value="000905" />
          <el-option label="上证50" value="000016" />
        </el-select>
      </div>
      <div class="toolbar-group">
        <el-button type="primary" :loading="loading" @click="runCompare">开始对比</el-button>
      </div>
    </div>

    <!-- 核心指标对比矩阵 -->
    <el-card v-if="matrixReady" shadow="never" style="margin-top: 16px">
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span>核心指标对比矩阵</span>
          <span class="sub-text">支持内置策略 + 基本面 + 用户自定义策略</span>
        </div>
      </template>
      <div class="table-wrapper">
        <table class="cmp-table matrix-table">
          <thead>
            <tr>
              <th width="130">指标</th>
              <th v-for="(item, idx) in compareData" :key="item.strategy" :style="{ borderTop: '3px solid ' + strategyColors[idx % strategyColors.length] }">
                {{ item.strategy_cn || item.strategy }}<br>
                <span class="tag" :class="'t-' + getCategoryKey(item.strategy)">{{ getCategoryLabel(item.strategy) }}</span>
              </th>
              <th width="40">🏆</th>
            </tr>
          </thead>
          <tbody>
            <!-- 📈 收益指标 -->
            <tr class="cat-row"><td :colspan="compareData.length + 2" style="color:#1890ff">📈 收益指标</td></tr>
            <tr v-for="period in [5, 10, 20]" :key="'ret-' + period">
              <td>{{ period }}日平均收益</td>
              <td v-for="(item, idx) in compareData" :key="idx"
                :class="[rateClass(getMultiPeriod(item.strategy, period, 'avg_return')), { 'is-best': isBest('ret_' + period, idx) }]">
                {{ fmtPct(getMultiPeriod(item.strategy, period, 'avg_return')) }}
              </td>
              <td><span class="rank" :class="rankClass('ret_' + period)">{{ rankLabel('ret_' + period) }}</span></td>
            </tr>
            <!-- 🛡️ 风险指标 -->
            <tr class="cat-row"><td :colspan="compareData.length + 2" style="color:#389e0d">🛡️ 风险指标 <span style="font-weight:400;font-size:10px">(蓝色=最优)</span></td></tr>
            <tr>
              <td>最大亏损</td>
              <td v-for="(item, idx) in compareData" :key="idx"
                :class="{ 'is-best text-good': isBestMin('max_loss', idx) }">
                {{ fmtPlain(item.max_single_loss) }}
              </td>
              <td><span class="rank" :class="rankClassMin('max_loss')">{{ rankLabelMin('max_loss') }}</span></td>
            </tr>
            <tr>
              <td>波动率 σ</td>
              <td v-for="(item, idx) in compareData" :key="idx"
                :class="{ 'is-best text-good': isBestMin('return_std', idx) }">
                {{ fmtPlain(item.return_std) }}
              </td>
              <td><span class="rank" :class="rankClassMin('return_std')">{{ rankLabelMin('return_std') }}</span></td>
            </tr>
            <!-- ⭐ 风险调整后收益 -->
            <tr class="cat-row"><td :colspan="compareData.length + 2" style="color:#cf1322">⭐ 风险调整后收益</td></tr>
            <tr style="background:#f6ffed">
              <td style="font-weight:600">夏普比率</td>
              <td v-for="(item, idx) in compareData" :key="idx"
                :class="[sharpeClass(item.sharpe_approx), { 'is-best': isBest('sharpe', idx) }]"
                :style="isBest('sharpe', idx) ? { fontSize: '14px' } : {}">
                {{ fmt(item.sharpe_approx) }}
              </td>
              <td><span class="rank" :class="rankClass('sharpe')">{{ rankLabel('sharpe') }}</span></td>
            </tr>
            <tr>
              <td>索提诺比率</td>
              <td v-for="(item, idx) in compareData" :key="idx"
                :class="{ 'is-best text-pos': isBest('sortino', idx) }">
                {{ fmt(item.sortino_approx) }}
              </td>
              <td><span class="rank" :class="rankClass('sortino')">{{ rankLabel('sortino') }}</span></td>
            </tr>
            <tr>
              <td>Calmar比率</td>
              <td v-for="(item, idx) in compareData" :key="idx"
                :class="{ 'is-best text-pos': isBest('calmar', idx) }">
                {{ fmt(item.calmar_ratio) }}
              </td>
              <td><span class="rank" :class="rankClass('calmar')">{{ rankLabel('calmar') }}</span></td>
            </tr>
            <!-- 📊 交易质量 -->
            <tr class="cat-row"><td :colspan="compareData.length + 2" style="color:#d46b08">📊 交易质量</td></tr>
            <tr>
              <td>胜率</td>
              <td v-for="(item, idx) in compareData" :key="idx"
                :class="{ 'is-best text-pos': isBest('win_rate', idx) }">
                {{ fmtPlain(item.win_rate) }}
              </td>
              <td><span class="rank" :class="rankClass('win_rate')">{{ rankLabel('win_rate') }}</span></td>
            </tr>
            <tr>
              <td>盈亏比</td>
              <td v-for="(item, idx) in compareData" :key="idx"
                :class="{ 'is-best text-pos': isBest('plr', idx) }">
                {{ fmt(item.profit_loss_ratio) }}
              </td>
              <td><span class="rank" :class="rankClass('plr')">{{ rankLabel('plr') }}</span></td>
            </tr>
            <tr>
              <td>日均信号数</td>
              <td v-for="(item, idx) in compareData" :key="idx">
                {{ item.daily_signal_count ?? item.signal_count }}
              </td>
              <td></td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="table-tip">数据来源: cn_stock_strategy_* 各表 rate_1..100 前瞻收益列</div>
    </el-card>

    <!-- 六维雷达图 + 累计收益走势 (并排) -->
    <el-row v-if="matrixReady" :gutter="16" style="margin-top: 16px">
      <el-col :span="12">
        <el-card shadow="never">
          <template #header><span>六维能力雷达图</span></template>
          <div ref="radarChartRef" style="height: 300px" />
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card shadow="never">
          <template #header><span>累计收益率走势</span></template>
          <div ref="navChartRef" style="height: 300px" />
        </el-card>
      </el-col>
    </el-row>

    <!-- 空状态 -->
    <el-empty v-if="!loading && compareData.length === 0 && hasQueried" description="暂无数据，请选择策略并点击开始对比" />

    <!-- 关键发现 -->
    <div v-if="insights.length > 0" class="insights-card">
      <div class="insights-title">💡 多策略类型对比发现</div>
      <div class="insights-body">
        <div v-for="(insight, idx) in insights" :key="idx" class="insight-item">
          {{ idx + 1 }}. <span v-html="insight"></span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'
import { getHoldingPeriod, getReturnSeries } from '@/api/verify'
import UsageGuide from '@/components/verify/UsageGuide.vue'
import dayjs from 'dayjs'

const guideSteps = [
  '在左侧点击 <b>"+ 添加策略"</b> 选择 2~6 个策略（支持分组搜索）',
  '选择 <b>统计周期</b>（近1月/近3月/近6月/近1年 或自定义日期）',
  '选择 <b>基准指数</b>（沪深300/中证500/上证50）',
  '点击 <b>"开始对比"</b> 按钮，等待计算完成',
  '查看下方 <b>指标矩阵</b>（分4大类12项指标）、<b>雷达图</b>、<b>收益走势</b> 等结果',
]
const guideExample = `<b>场景：</b>比较"放量上涨"与"海龟交易"策略在 2025 年的表现<br/>
<b>操作：</b>添加两个策略 → 统计周期选 近1年 → 基准选 沪深300 → 点击开始对比<br/>
<b>预期：</b>矩阵表显示 5/10/20日 多周期收益、夏普/Sortino/Calmar 风险调整指标、胜率/盈亏比等交易质量，雷达图可视化六维能力差异`
const guideMetrics = [
  { name: '平均收益%', desc: '所有买入信号在持仓期结束后的平均涨跌幅', range: '-∞ ~ +∞（A股通常 -5% ~ +8%）', good: '> 2% 为优秀' },
  { name: '胜率%', desc: '盈利信号数 / 总信号数 × 100%', range: '0% ~ 100%', good: '> 55% 为较好，> 65% 为优秀' },
  { name: '年化夏普', desc: '(年化收益 - 无风险利率) / 年化波动率，衡量风险调整后收益', range: '-∞ ~ +∞', good: '> 1.0 良好，> 2.0 优秀，> 3.0 卓越' },
  { name: 'Sortino', desc: '类似夏普，但只考虑下行波动（惩罚亏损而非盈利波动）', range: '-∞ ~ +∞', good: '> 1.5 良好，> 2.5 优秀' },
  { name: 'Calmar', desc: '年化收益 / 最大亏损，衡量收益与极端风险的比值', range: '0 ~ +∞', good: '> 2.0 良好，> 3.0 优秀' },
  { name: '盈亏比', desc: '平均盈利 / 平均亏损，衡量每笔交易的风险回报', range: '0 ~ +∞', good: '> 1.5 良好，> 2.0 优秀' },
  { name: '综合评分', desc: '夏普×40% + 收益×30% + 回撤控制×20% + 胜率×10% 的归一化加权', range: '0 ~ 100', good: '> 70 为表现突出' },
]
const guideTips = [
  '策略间信号数差异大时，信号少的策略统计置信度较低，需关注日均信号数',
  '高夏普 + 低胜率 = 策略依赖少数大盈利覆盖多数小亏损（趋势型）',
  '高胜率 + 低夏普 = 策略盈亏比差，每笔盈利小（均值回归型）',
  '建议选择互补型策略融合使用，可在"策略融合"页进一步实验',
]

// ── 策略分组 & 类别映射 ──────────────────────────────────
const strategyGroups = [
  {
    label: '技术指标',
    category: 'tech',
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
    category: 'pat',
    items: [
      { value: 'climax_limitdown', label: '放量跌停' },
      { value: 'high_tight_flag', label: '高而窄旗形' },
      { value: 'low_backtrace_increase', label: '无大幅回撤' },
    ],
  },
  {
    label: '趋势突破',
    category: 'vol',
    items: [
      { value: 'turtle_trade', label: '海龟交易' },
      { value: 'enter_strategy', label: '企业战略' },
      { value: 'share_holder_increase', label: '股东增持' },
      { value: 'roaming_loong', label: '游龙' },
    ],
  },
]

// 策略 → 类别/颜色映射
const categoryMap: Record<string, { label: string; key: string; color: string }> = {}
for (const g of strategyGroups) {
  const colorMap: Record<string, string> = { tech: '#1890ff', pat: '#d46b08', vol: '#389e0d' }
  for (const s of g.items) {
    categoryMap[s.value] = { label: g.label === '技术指标' ? '技术' : g.label === '量价形态' ? '形态' : '趋势', key: g.category, color: colorMap[g.category] || '#1890ff' }
  }
}

function getCategoryLabel(s: string) { return categoryMap[s]?.label || '策略' }
function getCategoryKey(s: string) { return categoryMap[s]?.key || 'tech' }
function getCategoryColor(s: string) { return categoryMap[s]?.color || '#1890ff' }
function getStrategyCn(s: string) {
  for (const g of strategyGroups) {
    const item = g.items.find(i => i.value === s)
    if (item) return item.label
  }
  return s
}

// ── 状态 ──────────────────────────────────────────────────
const selectedStrategies = ref<string[]>([])
const dateRange = ref<[string, string]>(['2026-01-01', '2026-05-15'])
const activePeriod = ref('')
const benchmarkIndex = ref('000300')
const loading = ref(false)
const hasQueried = ref(false)
const compareData = ref<any[]>([])          // 10日周期的主指标
const multiPeriodData = ref<Record<string, Record<number, any>>>({})  // strategy → { 5: {...}, 10: {...}, 20: {...} }
const seriesData = ref<any[]>([])
const radarChartRef = ref<HTMLElement>()
const navChartRef = ref<HTMLElement>()

const strategyColors = ['#1890ff', '#d46b08', '#389e0d', '#722ed1', '#cf1322', '#13c2c2']

const periodPresets = [
  { label: '近1月', months: 1 },
  { label: '近3月', months: 3 },
  { label: '近6月', months: 6 },
  { label: '近1年', months: 12 },
]

function setPeriod(p: { label: string; months: number }) {
  activePeriod.value = p.label
  const end = dayjs()
  const start = end.subtract(p.months, 'month')
  dateRange.value = [start.format('YYYY-MM-DD'), end.format('YYYY-MM-DD')]
}

function toggleStrategy(v: string) {
  const idx = selectedStrategies.value.indexOf(v)
  if (idx >= 0) {
    selectedStrategies.value.splice(idx, 1)
  } else if (selectedStrategies.value.length < 6) {
    selectedStrategies.value.push(v)
  }
}

function removeStrategy(v: string) {
  const idx = selectedStrategies.value.indexOf(v)
  if (idx >= 0) selectedStrategies.value.splice(idx, 1)
}

const matrixReady = computed(() => compareData.value.length > 0)

// ── 格式化 ──────────────────────────────────────────────
function fmt(v: number | null | undefined): string {
  if (v === null || v === undefined || !isFinite(v as number)) return '--'
  return Number(v).toFixed(2)
}
function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined || !isFinite(v as number)) return '--'
  const n = Number(v)
  return (n > 0 ? '+' : '') + n.toFixed(2) + '%'
}
function fmtPlain(v: number | null | undefined): string {
  if (v === null || v === undefined || !isFinite(v as number)) return '--'
  return Number(v).toFixed(2) + '%'
}
function rateClass(v: number | null): string {
  if (v === null || v === undefined) return ''
  return v > 0 ? 'text-pos' : v < 0 ? 'text-neg' : ''
}
function sharpeClass(v: number | null): string {
  if (v === null || v === undefined) return ''
  if (v >= 2) return 'text-pos font-bold'
  if (v < 0) return 'text-neg'
  return ''
}

// ── 多周期数据获取 ──────────────────────────────────────
function getMultiPeriod(strategy: string, period: number, field: string): number | null {
  return multiPeriodData.value[strategy]?.[period]?.[field] ?? null
}

// ── 排名逻辑 (越大越好) ──────────────────────────────────
function getBestIdx(metricKey: string): number {
  const data = compareData.value
  if (data.length === 0) return -1
  const vals = data.map((d, i) => {
    if (metricKey.startsWith('ret_')) {
      const period = parseInt(metricKey.split('_')[1])
      return { i, v: getMultiPeriod(d.strategy, period, 'avg_return') ?? -Infinity }
    }
    const fieldMap: Record<string, string> = { sharpe: 'sharpe_approx', sortino: 'sortino_approx', calmar: 'calmar_ratio', win_rate: 'win_rate', plr: 'profit_loss_ratio' }
    return { i, v: d[fieldMap[metricKey]] ?? -Infinity }
  })
  vals.sort((a, b) => b.v - a.v)
  return vals[0].i
}
function isBest(metricKey: string, idx: number): boolean { return getBestIdx(metricKey) === idx }
function rankLabel(metricKey: string): string {
  const best = getBestIdx(metricKey)
  if (best < 0) return ''
  const item = compareData.value[best]
  const cn = item?.strategy_cn || item?.strategy || ''
  return cn.substring(0, 1)
}
function rankClass(metricKey: string): string {
  const best = getBestIdx(metricKey)
  return best >= 0 ? `r${(best % 4) + 1}` : ''
}

// 越小越好 (风险类指标)
function getBestMinIdx(metricKey: string): number {
  const data = compareData.value
  if (data.length === 0) return -1
  const fieldMap: Record<string, string> = { max_loss: 'max_single_loss', return_std: 'return_std' }
  const field = fieldMap[metricKey] || metricKey
  const vals = data.map((d, i) => ({ i, v: Math.abs(d[field] ?? Infinity) }))
  vals.sort((a, b) => a.v - b.v)
  return vals[0].i
}
function isBestMin(metricKey: string, idx: number): boolean { return getBestMinIdx(metricKey) === idx }
function rankLabelMin(metricKey: string): string {
  const best = getBestMinIdx(metricKey)
  if (best < 0) return ''
  const item = compareData.value[best]
  return (item?.strategy_cn || item?.strategy || '').substring(0, 1)
}
function rankClassMin(metricKey: string): string {
  const best = getBestMinIdx(metricKey)
  return best >= 0 ? `r${(best % 4) + 1}` : ''
}

// ── 关键发现 ──────────────────────────────────────────
const insights = computed(() => {
  if (compareData.value.length < 2) return []
  const data = compareData.value
  const result: string[] = []

  const bestSharpe = [...data].sort((a, b) => (b.sharpe_approx ?? 0) - (a.sharpe_approx ?? 0))[0]
  const bestWinRate = [...data].sort((a, b) => (b.win_rate ?? 0) - (a.win_rate ?? 0))[0]
  const bestReturn = [...data].sort((a, b) => (b.avg_return ?? 0) - (a.avg_return ?? 0))[0]

  if (bestSharpe) {
    const cat = getCategoryLabel(bestSharpe.strategy)
    result.push(`<b>${cat}策略 (${bestSharpe.strategy_cn || bestSharpe.strategy})</b> 夏普比率最高(${fmt(bestSharpe.sharpe_approx)})，风险调整后收益表现最优`)
  }
  if (bestWinRate && bestWinRate.strategy !== bestSharpe?.strategy) {
    result.push(`<b>${bestWinRate.strategy_cn || bestWinRate.strategy}</b> 胜率最高(${fmt(bestWinRate.win_rate)}%)，信号可靠性强`)
  }
  if (bestReturn && bestReturn.strategy !== bestSharpe?.strategy) {
    result.push(`<b>${bestReturn.strategy_cn || bestReturn.strategy}</b> 10日平均收益最高(${fmtPct(bestReturn.avg_return)})，但需关注波动`)
  }
  if (data.length >= 3) {
    result.push('<b>提升空间:</b> 技术信号 + 基本面过滤 + 资金流验证 → 建议到 <b>"策略融合"</b> 页实验组合效果')
  }
  return result
})

// ── 主请求 ──────────────────────────────────────────────
async function runCompare() {
  if (selectedStrategies.value.length < 2) {
    ElMessage.warning('请至少选择 2 个策略进行对比')
    return
  }
  if (!dateRange.value || !dateRange.value[0]) {
    ElMessage.warning('请选择日期范围')
    return
  }

  loading.value = true
  hasQueried.value = true
  compareData.value = []
  multiPeriodData.value = {}
  seriesData.value = []

  const [startDate, endDate] = dateRange.value

  try {
    // 1) 并行请求各策略的 5/10/20 日数据
    const promises = selectedStrategies.value.map(s =>
      getHoldingPeriod({ strategy: s, start_date: startDate, end_date: endDate, holding_days: '5,10,20' })
    )
    const results = await Promise.all(promises)

    const mpd: Record<string, Record<number, any>> = {}
    const mainData: any[] = []

    results.forEach((res: any, i: number) => {
      const tableKey = res.strategy
      const frontendKey = selectedStrategies.value[i]
      mpd[frontendKey] = {}
      for (const a of (res.analysis || [])) {
        mpd[frontendKey][a.holding_days] = a
      }
      // 主指标使用 10 日
      const main = mpd[frontendKey][10] || mpd[frontendKey][5] || (res.analysis?.[0]) || {}
      mainData.push({ strategy: frontendKey, strategy_cn: res.strategy_cn, _table: tableKey, ...main })
    })

    multiPeriodData.value = mpd
    compareData.value = mainData

    await nextTick()
    renderRadarChart()

    // 2) 各策略累计收益走势 (10日)
    const seriesPromises = selectedStrategies.value.map(s =>
      getReturnSeries({ strategy: s, start_date: startDate, end_date: endDate, holding_days: 10 })
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
  if (radarChartRef.value) echarts.dispose(radarChartRef.value)
  if (navChartRef.value) echarts.dispose(navChartRef.value)
})

// ── 雷达图 ──────────────────────────────────────────────
function renderRadarChart() {
  if (!radarChartRef.value || compareData.value.length === 0) return
  const existing = echarts.getInstanceByDom(radarChartRef.value)
  if (existing) existing.dispose()
  const chart = echarts.init(radarChartRef.value)

  const indicators = [
    { name: '收益率', max: 100 },
    { name: '胜率', max: 100 },
    { name: '夏普', max: 100 },
    { name: '低回撤', max: 100 },
    { name: '稳定性', max: 100 },
    { name: '信号频率', max: 100 },
  ]

  const data = compareData.value
  const vals = {
    ret: data.map(d => d.avg_return ?? 0),
    win: data.map(d => d.win_rate ?? 0),
    sharpe: data.map(d => d.sharpe_approx ?? 0),
    dd: data.map(d => -(d.max_single_loss ?? 0)),
    stable: data.map(d => 100 - (d.return_std ?? 0)),
    signal: data.map(d => d.daily_signal_count ?? d.signal_count ?? 0),
  }

  function norm(arr: number[]): number[] {
    const min = Math.min(...arr), max = Math.max(...arr)
    if (max === min) return arr.map(() => 50)
    return arr.map(v => ((v - min) / (max - min)) * 100)
  }

  const nR = norm(vals.ret), nW = norm(vals.win), nS = norm(vals.sharpe)
  const nD = norm(vals.dd), nSt = norm(vals.stable), nSig = norm(vals.signal)

  const series = data.map((d, i) => ({
    name: d.strategy_cn || d.strategy,
    value: [nR[i], nW[i], nS[i], nD[i], nSt[i], nSig[i]],
  }))

  chart.setOption({
    tooltip: {},
    legend: { bottom: 0, data: series.map(s => s.name), textStyle: { fontSize: 11 } },
    radar: { indicator: indicators, radius: 80, center: ['50%', '45%'] },
    series: [{ type: 'radar', data: series.map((s, i) => ({ name: s.name, value: s.value, areaStyle: { opacity: 0.15 }, lineStyle: { color: strategyColors[i % strategyColors.length] }, itemStyle: { color: strategyColors[i % strategyColors.length] } })) }],
  })
}

// ── 累计收益走势 (含基准) ──────────────────────────────────
function renderNavChart() {
  if (!navChartRef.value || seriesData.value.length === 0) return
  const existing = echarts.getInstanceByDom(navChartRef.value)
  if (existing) existing.dispose()
  const chart = echarts.init(navChartRef.value)

  const allSeries = seriesData.value.map((item: any, idx: number) => ({
    name: item.strategy_cn || item.strategy,
    type: 'line',
    data: item.series.map((p: any) => [p.date, p.cumulative]),
    showSymbol: false,
    lineStyle: { width: 2 },
    itemStyle: { color: strategyColors[idx % strategyColors.length] },
  }))

  // 基准线: 归一化为 100 基准
  const benchmarkName = benchmarkIndex.value === '000300' ? '沪深300' : benchmarkIndex.value === '000905' ? '中证500' : '上证50'
  if (seriesData.value[0]?.series.length > 0) {
    const dates = seriesData.value[0].series.map((p: any) => p.date)
    allSeries.push({
      name: benchmarkName + '(基准)',
      type: 'line',
      data: dates.map((d: string) => [d, 100]),
      showSymbol: false,
      lineStyle: { width: 1.5, type: 'dashed' as any, color: '#999' } as any,
      itemStyle: { color: '#999' },
    })
  }

  chart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { bottom: 0, data: allSeries.map(s => s.name), textStyle: { fontSize: 11 } },
    grid: { top: 30, left: 60, right: 20, bottom: 50 },
    xAxis: { type: 'category', data: seriesData.value[0]?.series.map((p: any) => p.date) || [] },
    yAxis: { type: 'value', name: '累计净值', axisLabel: { formatter: '{value}' } },
    dataZoom: [{ type: 'inside' }],
    series: allSeries,
  })
}
</script>

<style scoped>
.verify-compare { padding: 16px; }

/* ── 工具栏 ── */
.toolbar { display: flex; align-items: flex-end; flex-wrap: wrap; gap: 16px; padding: 12px 16px; background: #fafafa; border-radius: 6px; border: 1px solid #ebeef5; }
.toolbar-group { display: flex; flex-direction: column; gap: 4px; }
.toolbar-label { font-size: 12px; color: #909399; font-weight: 500; }

/* 策略芯片 */
.chip-area { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
.chip { display: inline-flex; align-items: center; gap: 4px; padding: 4px 10px; border-radius: 4px; font-size: 12px; border: 1px solid #d9d9d9; background: #fff; cursor: default; }
.chip.sel { border-width: 2px; background: #f6f8ff; }
.chip .x { cursor: pointer; color: #999; margin-left: 2px; font-size: 11px; }
.chip .x:hover { color: #cf1322; }
.chip-add { border-style: dashed; cursor: pointer; color: #1890ff; }
.chip-add:hover { background: #e6f7ff; }

/* 类别标签 */
.tag { display: inline-block; padding: 0 6px; border-radius: 2px; font-size: 10px; line-height: 18px; color: #fff; }
.t-tech { background: #1890ff; }
.t-pat { background: #d46b08; }
.t-vol { background: #389e0d; }
.t-fund { background: #722ed1; }
.t-custom { background: #cf1322; }

/* 策略选择弹出框 */
.strategy-picker { max-height: 300px; overflow-y: auto; }
.picker-group { margin-bottom: 8px; }
.picker-group-label { font-size: 11px; color: #909399; font-weight: 600; margin-bottom: 4px; padding: 2px 4px; }
.picker-item { padding: 6px 8px; cursor: pointer; border-radius: 4px; display: flex; justify-content: space-between; align-items: center; font-size: 13px; }
.picker-item:hover { background: #e6f7ff; }
.picker-item.active { background: #f6ffed; color: #389e0d; font-weight: 500; }
.picker-item.disabled { opacity: 0.4; cursor: not-allowed; }

/* 时间预设 */
.radio-group { display: flex; gap: 0; }
.radio-btn { padding: 5px 14px; border: 1px solid #d9d9d9; font-size: 12px; cursor: pointer; background: #fff; }
.radio-btn:first-child { border-radius: 4px 0 0 4px; }
.radio-btn:last-child { border-radius: 0 4px 4px 0; }
.radio-btn + .radio-btn { margin-left: -1px; }
.radio-btn.active { background: #1890ff; color: #fff; border-color: #1890ff; z-index: 1; position: relative; }
.radio-btn:hover:not(.active) { color: #1890ff; border-color: #1890ff; z-index: 1; position: relative; }

/* ── 表格 ── */
.table-wrapper { overflow-x: auto; }
.cmp-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.cmp-table th, .cmp-table td { border: 1px solid #ebeef5; padding: 8px 12px; text-align: center; white-space: nowrap; }
.cmp-table th { background: #fafafa; font-weight: 600; }
.matrix-table td:first-child { text-align: left; font-weight: 500; background: #fafbfc; }

/* 分组行 */
.cat-row td { background: #f0f5ff !important; font-weight: 600; font-size: 13px; text-align: left !important; border-bottom: 2px solid #d9d9d9; }

/* 最优值高亮 */
.is-best { font-weight: 700; }
.text-pos { color: #cf1322; }
.text-neg { color: #389e0d; }
.text-good { color: #1890ff; }
.font-bold { font-weight: 700; }

/* 排名徽章 */
.rank { display: inline-flex; align-items: center; justify-content: center; width: 20px; height: 20px; border-radius: 50%; font-size: 10px; font-weight: 700; color: #fff; }
.r1 { background: #cf1322; }
.r2 { background: #d46b08; }
.r3 { background: #1890ff; }
.r4 { background: #bfbfbf; }

.sub-text { font-size: 12px; color: #909399; font-weight: 400; }
.table-tip { padding: 6px 12px; font-size: 11px; color: #999; }

/* ── 关键发现卡片 ── */
.insights-card {
  margin-top: 16px;
  padding: 14px 18px;
  background: linear-gradient(135deg, #e8f0fe 0%, #f0e6ff 100%);
  border-radius: 8px;
  border: 1px solid #d6e4ff;
}
.insights-title { font-weight: 600; margin-bottom: 8px; font-size: 14px; color: #333; }
.insights-body { line-height: 1.8; }
.insight-item { padding: 2px 0; font-size: 12px; color: #444; }
</style>
