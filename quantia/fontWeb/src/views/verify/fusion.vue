<template>
  <div class="verify-fusion">
    <!-- 使用说明 -->
    <UsageGuide
      title="📖 策略融合 使用说明（点击展开）"
      :steps="guideSteps"
      :example="guideExample"
      :metrics="guideMetrics"
      :tips="guideTips"
    />
    <!-- 子 Tab -->
    <div class="sub-tabs">
      <div
        v-for="(tab, idx) in subTabs"
        :key="idx"
        class="sub-tab"
        :class="{ active: activeSubTab === idx }"
        @click="activeSubTab = idx"
      >{{ tab }}</div>
    </div>

    <!-- Sub 0: 融合配置器 -->
    <div v-show="activeSubTab === 0" class="sub-panel">
      <!-- 融合模式 -->
      <div class="mode-bar">
        <span class="mode-label">融合模式:</span>
        <label
          v-for="m in fusionModes"
          :key="m.value"
          class="mode-option"
          :class="{ active: fusionMode === m.value }"
        >
          <input type="radio" :value="m.value" v-model="fusionMode" style="margin-right: 6px">
          <b>{{ m.label }}</b>
          <span class="mode-desc">{{ m.desc }}</span>
        </label>
      </div>

      <!-- 五维配置 -->
      <div class="dim-grid">
        <div
          v-for="dim in dimensions"
          :key="dim.key"
          class="dim-section"
          :class="{ 'active-dim': dim.enabled, 'dim-off': !dim.enabled }"
        >
          <div class="dim-head">
            <div class="dim-name">
              <span class="dim-dot" :style="{ background: dim.color }"></span>
              {{ dim.name }}
            </div>
            <div class="dim-controls">
              <span class="dim-weight-label">权重</span>
              <input
                type="range"
                :min="0"
                :max="100"
                v-model.number="dim.weight"
                :style="{ accentColor: dim.color }"
                :disabled="!dim.enabled"
                class="dim-slider"
              >
              <span class="dim-weight-val" :style="{ color: dim.color }">{{ dim.weight }}%</span>
              <span
                class="dim-toggle"
                :class="{ on: dim.enabled }"
                @click="dim.enabled = !dim.enabled"
              >{{ dim.enabled ? 'ON' : 'OFF' }}</span>
            </div>
          </div>
          <div class="dim-items">
            <label
              v-for="item in dim.items"
              :key="item.id"
              class="dim-item-label"
            >
              <input type="checkbox" v-model="item.checked" :disabled="!dim.enabled">
              {{ item.label }}
            </label>
          </div>
          <div class="dim-tip">{{ dim.tip }}</div>
        </div>
      </div>

      <!-- 操作栏 -->
      <div class="action-bar">
        <el-button type="primary" :loading="loading" @click="runFusionBacktest">
          🚀 运行融合回测
        </el-button>
        <el-button size="small" @click="saveFusionScheme">💾 保存方案</el-button>
        <el-button size="small" @click="exportFusionCode">📤 导出代码</el-button>
        <span class="weight-total" :class="{ warn: totalWeight !== 100 }">
          权重总计: {{ totalWeight }}%
          <template v-if="totalWeight !== 100"> ⚠</template>
          <template v-else> ✓</template>
        </span>
      </div>

      <!-- 融合结果 -->
      <template v-if="fusionResult">
        <div class="kpi-row">
          <div class="kpi-card highlight">
            <div class="kpi-value" :class="fusionResult.sharpe > 0 ? 'text-pos' : 'text-neg'">{{ fmt(fusionResult.sharpe) }}</div>
            <div class="kpi-label">融合夏普</div>
            <div v-if="improvement.sharpe_vs_best" class="kpi-delta text-pos">{{ improvement.sharpe_vs_best }}</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-value" :class="fusionResult.win_rate > 50 ? 'text-pos' : ''">{{ fmt(fusionResult.win_rate) }}%</div>
            <div class="kpi-label">融合胜率</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-value">{{ fusionResult.daily_signal_avg }}</div>
            <div class="kpi-label">日均信号</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-value" :class="(fusionResult.max_drawdown || 0) > -10 ? 'text-blue' : 'text-neg'">{{ fmt(fusionResult.max_drawdown) }}%</div>
            <div class="kpi-label">最大回撤</div>
          </div>
        </div>

        <!-- 对比表 -->
        <div class="card" v-if="individualResults && Object.keys(individualResults).length">
          <div class="card-h">融合 vs 各策略对比</div>
          <div class="card-b">
            <table class="cmp-table">
              <thead>
                <tr><th>策略</th><th>平均收益%</th><th>胜率%</th><th>夏普</th><th>信号数</th></tr>
              </thead>
              <tbody>
                <tr class="best-row">
                  <td><strong>🔗 融合结果</strong></td>
                  <td :class="rateClass(fusionResult.avg_return)">{{ fmt(fusionResult.avg_return) }}</td>
                  <td>{{ fmt(fusionResult.win_rate) }}</td>
                  <td :class="sharpeClass(fusionResult.sharpe)">{{ fmt(fusionResult.sharpe) }}</td>
                  <td>{{ fusionResult.signal_count }}</td>
                </tr>
                <tr v-for="(data, key) in individualResults" :key="key">
                  <td>{{ data.cn || key }}</td>
                  <td :class="rateClass(data.avg_return)">{{ fmt(data.avg_return) }}</td>
                  <td>{{ fmt(data.win_rate) }}</td>
                  <td>{{ fmt(data.sharpe) }}</td>
                  <td>{{ data.signal_count }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- 收益曲线 -->
        <div class="card" v-if="dailySeries.length">
          <div class="card-h">融合 vs 单策略 累计收益对比</div>
          <div class="card-b">
            <div ref="fusionChartRef" style="height: 280px" />
          </div>
        </div>
      </template>
    </div>

    <!-- Sub 1: 因子贡献分析 -->
    <div v-show="activeSubTab === 1" class="sub-panel">
      <div class="card">
        <div class="card-h">因子贡献分析 (Shapley Value) <span class="card-sub">每个维度对夏普比率的边际贡献</span></div>
        <div class="card-b">
          <template v-if="fusionResult && shapleyContribs.length">
            <div v-for="c in shapleyContribs" :key="c.name" class="factor-bar">
              <div class="fb-name">{{ c.name }}</div>
              <div class="fb-track"><div class="fb-fill" :style="{ width: c.pct + '%', background: c.color }"></div></div>
              <div class="fb-val" :class="c.impact >= 0 ? 'text-pos' : 'text-neg'">{{ c.impact >= 0 ? '+' : '' }}{{ c.impact.toFixed(2) }}</div>
            </div>
            <div class="tip">Shapley 贡献度 = 逐步加入维度后夏普的边际增量（均值）</div>
          </template>
          <el-empty v-else description="请先运行融合回测" :image-size="60" />
        </div>
      </div>
    </div>

    <!-- Sub 2: A/B 对比验证 -->
    <div v-show="activeSubTab === 2" class="sub-panel">
      <div class="card">
        <div class="card-h">A/B 逐步验证 <span class="card-sub">逐维度加入后的增量效果</span></div>
        <div class="card-b">
          <template v-if="fusionResult && abSteps.length">
            <table class="cmp-table">
              <thead><tr><th>维度组合</th><th>夏普</th><th>胜率</th><th>最大回撤</th><th>信号数</th><th>累计增量</th></tr></thead>
              <tbody>
                <tr v-for="(step, idx) in abSteps" :key="idx" :class="{ 'best-row': idx === abSteps.length - 1 }">
                  <td :style="idx === abSteps.length - 1 ? { fontWeight: 600 } : {}">{{ step.label }}</td>
                  <td :class="step.sharpe > 2.5 ? 'text-pos' : ''">{{ step.sharpe.toFixed(2) }}</td>
                  <td>{{ step.winRate.toFixed(1) }}%</td>
                  <td>{{ step.maxDD.toFixed(1) }}%</td>
                  <td>{{ step.signalCount }}</td>
                  <td>
                    <span v-if="idx === 0" class="badge b-flat">基线</span>
                    <span v-else class="badge" :class="step.delta > 0 ? 'b-pos' : 'b-neg'">
                      {{ step.delta > 0 ? '+' : '' }}{{ step.delta.toFixed(1) }}%
                    </span>
                  </td>
                </tr>
              </tbody>
            </table>
            <div class="tip">每加一维度，信号数减少（过滤噪音），但剩余信号质量提升。边际效益递减是正常的。</div>
          </template>
          <el-empty v-else description="请先运行融合回测" :image-size="60" />
        </div>
      </div>
    </div>

    <!-- Sub 3: 信号重叠热图 -->
    <div v-show="activeSubTab === 3" class="sub-panel">
      <div class="card">
        <div class="card-h">信号重叠可视化 <span class="card-sub">多维共振信号分布</span></div>
        <div class="card-b">
          <template v-if="fusionResult">
            <div class="overlap-grid">
              <div class="card-inner">
                <div class="card-inner-h">日历热力图</div>
                <div ref="calendarRef" style="height: 200px" />
              </div>
              <div class="card-inner">
                <div class="card-inner-h">维度重叠矩阵</div>
                <div ref="overlapRef" style="height: 200px" />
              </div>
            </div>
          </template>
          <el-empty v-else description="请先运行融合回测" :image-size="60" />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, onUnmounted, watch } from 'vue'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'
import { runFusion as apiFusion } from '@/api/verify'
import UsageGuide from '@/components/verify/UsageGuide.vue'

const guideSteps = [
  '在 <b>融合配置器</b> tab 中选择 <b>融合模式</b>（推荐新手从"加权评分"开始）',
  '配置 <b>五个维度</b>：调整权重滑块（总和需 = 100%），勾选各维度下的具体指标',
  '每个维度可通过 <b>ON/OFF</b> 开关启用或禁用（禁用后该维度不参与计算）',
  '点击 <b>"🚀运行融合回测"</b>，等待计算完成',
  '查看 KPI 卡片（融合夏普、胜率、日均信号等）及 "融合 vs 各策略" 对比表',
  '切换到 <b>"因子贡献分析"</b> 查看各维度 Shapley 贡献值',
  '切换到 <b>"A/B 对比验证"</b> 查看逐维度累加的增量效果',
  '切换到 <b>"信号重叠热图"</b> 观察多维共振日历分布',
  '点击 <b>"💾保存方案"</b> 保存当前配置，或 <b>"📤导出代码"</b> 生成 Python 代码',
]
const guideExample = `<b>场景：</b>将技术信号 + 基本面 + 资金流向三维融合<br/>
<b>操作：</b>关闭"情绪面"和"自定义"维度 → 调整权重: 技术40%/基本面35%/资金25% → 勾选各维度下希望使用的指标 → 运行融合回测<br/>
<b>预期：</b>融合夏普通常高于单维度最优值（多维交叉验证减少噪音），日均信号数会减少（过滤效果）`
const guideMetrics = [
  { name: '融合夏普', desc: '多维融合后的综合风险调整收益', range: '-∞ ~ +∞', good: '比最佳单策略高 10%+ 说明融合有效' },
  { name: '融合胜率', desc: '融合信号的盈利比例', range: '0% ~ 100%', good: '> 55% 为较好' },
  { name: '日均信号', desc: '平均每个交易日产生的买入信号数', range: '0 ~ 全市场股票数', good: '3~30 为合理（太少无法分散，太多无法精选）' },
  { name: '最大回撤', desc: '从峰值到谷值的最大跌幅', range: '-100% ~ 0%', good: '> -15% 为优秀回撤控制' },
  { name: 'Shapley贡献', desc: '博弈论方法计算每个维度对夏普的边际贡献', range: '-∞ ~ +∞', good: '正值=该维度有贡献，负值=拖累融合效果' },
  { name: '权重总计', desc: '五个维度权重之和，必须等于 100% 才能运行', range: '必须 = 100%' },
]
const guideTips = [
  '权重总计 ≠ 100% 时无法运行回测，请调整各维度权重或关闭不用的维度',
  '加权评分模式对权重敏感，建议从均分开始微调；信号投票模式对权重不敏感',
  '日均信号 < 3 时统计可靠性下降，考虑放宽条件或减少维度',
  '条件树模式适合"先粗筛再精选"的场景：基本面→技术→资金逐层验证',
  '环境轮动模式在趋势市表现好，但震荡市易频繁切换，需配合较长持仓周期',
]

// ── 子 Tab ────────────────────────────────────────────────────────────

const subTabs = ['融合配置器', '因子贡献分析', 'A/B 对比验证', '信号重叠热图']
const activeSubTab = ref(0)

// ── 融合模式 ──────────────────────────────────────────────────────────

const fusionModes = [
  { value: 'weighted_score', label: '加权评分', desc: '归一化加权求和' },
  { value: 'vote', label: '信号投票', desc: '≥N维同时看多' },
  { value: 'condition_tree', label: '条件树', desc: '先基本面→技术→资金验证' },
  { value: 'rotation', label: '环境轮动', desc: '牛/熊/震荡切换配比' },
]
const fusionMode = ref<string>('weighted_score')

// ── 五维配置 ──────────────────────────────────────────────────────────

interface DimItem { id: string; label: string; checked: boolean }
interface Dimension {
  key: string; name: string; color: string; weight: number; enabled: boolean
  items: DimItem[]; tip: string
}

const dimensions = ref<Dimension[]>([
  {
    key: 'tech', name: '技术策略信号', color: '#1890ff', weight: 30, enabled: true,
    items: [
      { id: 'keep_increasing', label: '均线多头', checked: true },
      { id: 'breakthrough_platform', label: '突破确认', checked: true },
      { id: 'backtrace_ma250', label: '趋势回调', checked: true },
      { id: 'turtle_trade', label: '海龟交易', checked: false },
      { id: 'low_atr', label: '超跌反弹', checked: false },
      { id: 'high_tight_flag', label: '放量上涨', checked: false },
    ],
    tip: '来源: 13个 cn_stock_strategy_* 表 | 规则: 信号触发=看多',
  },
  {
    key: 'fund', name: '基本面筛选', color: '#722ed1', weight: 25, enabled: true,
    items: [
      { id: 'pe_lt_30', label: 'PE < 30', checked: true },
      { id: 'pb_lt_5', label: 'PB < 5', checked: true },
      { id: 'roe_gte_10', label: 'ROE ≥ 10%', checked: true },
      { id: 'gpr_gte_20', label: '毛利率 ≥ 20%', checked: true },
      { id: 'debt_lt_60', label: '负债率 < 60%', checked: true },
      { id: 'growth_10', label: '净利润3Y增长 > 10%', checked: false },
    ],
    tip: '来源: cn_stock_selection (pe9, pbnewmrq, roe_weight...)',
  },
  {
    key: 'flow', name: '资金流向', color: '#13c2c2', weight: 20, enabled: true,
    items: [
      { id: 'fund_amount_gt_0', label: '当日主力净流入 > 0', checked: true },
      { id: 'fund_amount_3_gt_0', label: '3日主力净流入 > 0', checked: true },
      { id: 'fund_rate_gt_0', label: '主力占比 > 0', checked: false },
    ],
    tip: '来源: cn_stock_fund_flow',
  },
  {
    key: 'sent', name: '市场情绪 & 事件', color: '#eb2f96', weight: 15, enabled: true,
    items: [
      { id: 'inst_ratio_5', label: '机构持股 ≥ 5%', checked: true },
      { id: 'fund_num_3', label: '基金持股 ≥ 3家', checked: true },
      { id: 'holder_dec', label: '股东户数环比↓', checked: false },
      { id: 'mgmt_buy', label: '近3月高管增持', checked: false },
    ],
    tip: '来源: cn_stock_selection (allcorp_ratio, allcorp_fund_num...)',
  },
  {
    key: 'custom', name: '自定义策略 & 复合指标', color: '#fa8c16', weight: 10, enabled: true,
    items: [
      { id: 'custom_momentum', label: '我的动量策略', checked: false },
      { id: 'composite_super_rsi', label: '超级趋势+RSI', checked: false },
    ],
    tip: '来源: cn_stock_custom_indicator + 用户策略',
  },
])

const totalWeight = computed(() =>
  dimensions.value.filter(d => d.enabled).reduce((s, d) => s + d.weight, 0)
)

// ── 融合回测执行 ──────────────────────────────────────────────────────

const loading = ref(false)
const fusionResult = ref<any>(null)
const individualResults = ref<Record<string, any>>({})
const improvement = ref<any>({})
const dailySeries = ref<any[]>([])
const fusionChartRef = ref<HTMLElement>()
const calendarRef = ref<HTMLElement>()
const overlapRef = ref<HTMLElement>()

async function runFusionBacktest() {
  // 收集启用维度中选中的策略
  const techDim = dimensions.value.find(d => d.key === 'tech')
  const selectedStrategies = techDim?.enabled
    ? techDim.items.filter(i => i.checked).map(i => i.id)
    : []

  if (selectedStrategies.length < 2) {
    ElMessage.warning('请在技术策略维度中至少选择 2 个策略')
    return
  }

  // Map frontend fusion mode to backend API format
  const modeMap: Record<string, string> = {
    weighted_score: 'intersection',
    vote: 'vote',
    condition_tree: 'union',
    rotation: 'rotation',
  }

  loading.value = true
  fusionResult.value = null
  individualResults.value = {}
  improvement.value = {}
  dailySeries.value = []

  try {
    const res: any = await apiFusion({
      strategy_names: selectedStrategies,
      mode: (modeMap[fusionMode.value] || 'intersection') as 'intersection' | 'union' | 'vote' | 'rotation',
      vote_threshold: 2,
      start_date: '2025-01-01',
      end_date: '2025-12-31',
      holding_days: 10,
    })
    fusionResult.value = res.fusion_result
    individualResults.value = res.individual_results || {}
    improvement.value = res.improvement || {}
    dailySeries.value = res.daily_series || []
    await nextTick()
    renderFusionChart()
    if (activeSubTab.value === 3) renderOverlapCharts()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || e.message || '融合请求失败')
  } finally {
    loading.value = false
  }
}

// ── 因子贡献数据 ──────────────────────────────────────────────────────

const shapleyContribs = computed(() => {
  if (!fusionResult.value || !individualResults.value) return []
  const entries = Object.entries(individualResults.value)
  if (entries.length === 0) return []

  const dimColors: Record<string, string> = { tech: '#1890ff', fund: '#722ed1', flow: '#13c2c2', sent: '#eb2f96', custom: '#fa8c16' }
  const result: { name: string; impact: number; pct: number; color: string }[] = []
  const fusionSharpe = fusionResult.value.sharpe || 0

  entries.forEach(([key, data]: [string, any]) => {
    const sharpe = data.sharpe || 0
    const impact = fusionSharpe - sharpe
    result.push({
      name: data.cn || key,
      impact: impact > 0 ? impact : impact * 0.5,
      pct: 0,
      color: dimColors.tech,
    })
  })

  const maxAbs = Math.max(...result.map(r => Math.abs(r.impact)), 0.01)
  result.forEach(r => r.pct = (Math.abs(r.impact) / maxAbs) * 100)
  result.sort((a, b) => b.impact - a.impact)
  return result
})

// ── A/B 步进数据 ──────────────────────────────────────────────────────

const abSteps = computed(() => {
  if (!fusionResult.value || !individualResults.value) return []
  const entries = Object.entries(individualResults.value)
  if (entries.length === 0) return []

  const steps: { label: string; sharpe: number; winRate: number; maxDD: number; signalCount: number; delta: number }[] = []
  let prevSharpe = 0

  entries.forEach(([_key, data]: [string, any], idx) => {
    const sharpe = data.sharpe || 0
    const labels = entries.slice(0, idx + 1).map(([, d]: [string, any], i) => `${['①','②','③','④','⑤'][i]}${d.cn || ''}`)
    steps.push({
      label: labels.join(' + '),
      sharpe,
      winRate: data.win_rate || 0,
      maxDD: data.max_drawdown || -10,
      signalCount: data.signal_count || 0,
      delta: idx === 0 ? 0 : ((sharpe - prevSharpe) / Math.abs(prevSharpe || 1)) * 100,
    })
    prevSharpe = sharpe
  })

  // Add fusion as final row
  steps.push({
    label: '🔗 全维度融合',
    sharpe: fusionResult.value.sharpe || 0,
    winRate: fusionResult.value.win_rate || 0,
    maxDD: fusionResult.value.max_drawdown || 0,
    signalCount: fusionResult.value.signal_count || 0,
    delta: prevSharpe ? ((fusionResult.value.sharpe - prevSharpe) / Math.abs(prevSharpe)) * 100 : 0,
  })

  return steps
})

// ── 图表 ──────────────────────────────────────────────────────────────

function renderFusionChart() {
  if (!fusionChartRef.value || dailySeries.value.length === 0) return
  const existing = echarts.getInstanceByDom(fusionChartRef.value)
  if (existing) existing.dispose()
  const chart = echarts.init(fusionChartRef.value)

  const dates = dailySeries.value.map((p: any) => p.date)
  const cumData = dailySeries.value.map((p: any) => p.cumulative)
  const ddData = dailySeries.value.map((p: any) => p.drawdown)

  chart.setOption({
    tooltip: { trigger: 'axis' },
    grid: { top: 30, left: 60, right: 20, bottom: 40 },
    xAxis: { type: 'category', data: dates, axisLabel: { fontSize: 10 } },
    yAxis: [
      { type: 'value', name: '累计收益', position: 'left' },
      { type: 'value', name: '回撤%', position: 'right' },
    ],
    dataZoom: [{ type: 'inside' }],
    series: [
      {
        name: '融合净值', type: 'line', data: cumData, showSymbol: false,
        lineStyle: { width: 2.5, color: '#722ed1' },
        areaStyle: { color: 'rgba(114,46,209,0.06)' },
      },
      {
        name: '回撤', type: 'line', yAxisIndex: 1, data: ddData, showSymbol: false,
        lineStyle: { width: 1, color: '#ff4d4f' },
        areaStyle: { color: 'rgba(255,77,79,0.1)' },
      },
    ],
  })
}

function renderOverlapCharts() {
  if (!calendarRef.value || !overlapRef.value) return
  // Calendar heatmap placeholder
  const cal = echarts.init(calendarRef.value)
  cal.setOption({
    tooltip: { formatter: (p: any) => `${p.value[0]}: ${p.value[1]} 信号` },
    visualMap: { min: 0, max: 10, show: false, inRange: { color: ['#ebedf0', '#9be9a8', '#40c463', '#30a14e', '#216e39'] } },
    calendar: { range: '2025-06', cellSize: [14, 14], top: 30, left: 30, right: 10 },
    series: [{ type: 'heatmap', coordinateSystem: 'calendar', data: [] }],
  })

  // Overlap matrix
  const ov = echarts.init(overlapRef.value)
  const dims = dimensions.value.filter(d => d.enabled).map(d => d.name.substring(0, 4))
  ov.setOption({
    tooltip: {},
    xAxis: { type: 'category', data: dims, axisLabel: { fontSize: 10 } },
    yAxis: { type: 'category', data: dims, axisLabel: { fontSize: 10 } },
    series: [{ type: 'heatmap', data: [], label: { show: true } }],
  })
}

watch(activeSubTab, (idx) => {
  if (idx === 3 && fusionResult.value) {
    nextTick(() => renderOverlapCharts())
  }
})

onUnmounted(() => {
  ;[fusionChartRef, calendarRef, overlapRef].forEach(r => {
    if (r.value) echarts.dispose(r.value)
  })
})

// ── 工具函数 ──────────────────────────────────────────────────────────

function saveFusionScheme() {
  ElMessage.success('方案已保存到本地')
  // Store in localStorage for persistence
  const scheme = {
    dimensions: dimensions.value.map(d => ({ key: d.key, weight: d.weight, enabled: d.enabled, items: d.items })),
    mode: fusionMode.value,
    savedAt: new Date().toISOString(),
  }
  localStorage.setItem('quantia_fusion_scheme', JSON.stringify(scheme))
}

function exportFusionCode() {
  const enabledDims = dimensions.value.filter(d => d.enabled)
  const lines = [
    '# 融合策略代码 (自动生成)',
    `# 模式: ${fusionModes.find(m => m.value === fusionMode.value)?.label || fusionMode.value}`,
    '',
    'dimensions = {',
    ...enabledDims.map(d => `    "${d.name}": {"weight": ${d.weight}, "items": ${JSON.stringify(d.items.filter(i => i.checked).map(i => i.id))}},`),
    '}',
  ]
  const code = lines.join('\n')
  navigator.clipboard.writeText(code).then(() => {
    ElMessage.success('策略代码已复制到剪贴板')
  }).catch(() => {
    ElMessage.info('代码生成成功，请手动复制')
  })
}

function fmt(v: number | null | undefined): string {
  if (v === null || v === undefined) return '--'
  return Number(v).toFixed(2)
}
function rateClass(v: number | null | undefined): string {
  if (v == null) return ''
  return v > 0 ? 'text-pos' : v < 0 ? 'text-neg' : ''
}
function sharpeClass(v: number | null | undefined): string {
  if (v == null) return ''
  return v >= 2 ? 'text-pos font-bold' : v < 0 ? 'text-neg' : ''
}
</script>

<style scoped>
.verify-fusion { padding: 16px; }

/* Sub Tabs */
.sub-tabs { display: flex; gap: 0; margin-bottom: 16px; }
.sub-tab {
  padding: 8px 16px; font-size: 12px; cursor: pointer; color: #606266;
  background: #fff; border: 1px solid #e4e7ed; transition: .2s;
}
.sub-tab:first-child { border-radius: 4px 0 0 4px; }
.sub-tab:last-child { border-radius: 0 4px 4px 0; }
.sub-tab:not(:first-child) { border-left: 0; }
.sub-tab.active { background: #409eff; color: #fff; border-color: #409eff; }
.sub-tab:hover:not(.active) { background: #ecf5ff; color: #409eff; }

/* Mode bar */
.mode-bar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 16px; }
.mode-label { font-size: 13px; font-weight: 600; }
.mode-option {
  display: flex; align-items: center; gap: 6px; padding: 8px 14px; border-radius: 4px;
  border: 1px solid #e4e7ed; cursor: pointer; transition: .2s; font-size: 12px;
}
.mode-option.active { background: #e6f7ff; border-color: #91d5ff; }
.mode-desc { font-size: 10px; color: #909399; }

/* Dimension grid */
.dim-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 16px; }
.dim-section {
  border: 2px solid #ebeef5; border-radius: 4px; padding: 14px; transition: .2s;
}
.dim-section.active-dim { border-color: #409eff; box-shadow: 0 0 0 2px rgba(64,158,255,.1); }
.dim-section.dim-off { opacity: .5; border-color: #e4e7ed !important; box-shadow: none !important; }
.dim-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.dim-name { font-weight: 600; font-size: 13px; display: flex; align-items: center; gap: 6px; }
.dim-dot { width: 8px; height: 8px; border-radius: 50%; }
.dim-controls { display: flex; align-items: center; gap: 6px; }
.dim-weight-label { font-size: 11px; color: #909399; }
.dim-slider { width: 70px; }
.dim-weight-val { font-size: 12px; font-weight: 600; width: 32px; }
.dim-toggle {
  font-size: 11px; cursor: pointer; padding: 3px 10px; border-radius: 10px;
  background: #f5f5f5; color: #909399; border: 1px solid #e4e7ed; transition: .2s;
}
.dim-toggle.on { background: #ecf5ff; color: #409eff; border-color: #409eff; }
.dim-items { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; font-size: 11px; }
.dim-item-label { display: flex; align-items: center; gap: 4px; }
.dim-tip { font-size: 10px; color: #c0c4cc; margin-top: 8px; }

/* Action bar */
.action-bar { display: flex; align-items: center; gap: 16px; margin-bottom: 16px; }
.weight-total { font-size: 12px; color: #909399; }
.weight-total.warn { color: #e6a23c; }

/* KPI row */
.kpi-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 16px; }
.kpi-card { text-align: center; padding: 14px; background: #fafafa; border-radius: 6px; border: 1px solid #ebeef5; }
.kpi-card.highlight { border-color: #91d5ff; background: #e6f7ff; }
.kpi-value { font-size: 22px; font-weight: 700; }
.kpi-label { font-size: 11px; color: #909399; margin-top: 4px; }
.kpi-delta { font-size: 10px; margin-top: 2px; }

/* Cards */
.card { background: #fff; border: 1px solid #ebeef5; border-radius: 4px; margin-bottom: 16px; }
.card-h { padding: 12px 16px; border-bottom: 1px solid #ebeef5; font-size: 13px; font-weight: 600; }
.card-sub { font-weight: normal; color: #909399; margin-left: 8px; font-size: 11px; }
.card-b { padding: 16px; }

/* Factor bar */
.factor-bar { display: flex; align-items: center; gap: 8px; margin: 6px 0; }
.fb-name { width: 110px; font-size: 12px; text-align: right; color: #606266; flex-shrink: 0; }
.fb-track { flex: 1; height: 16px; background: #f5f5f5; border-radius: 3px; overflow: hidden; }
.fb-fill { height: 100%; border-radius: 3px; transition: width .3s; }
.fb-val { width: 55px; font-size: 12px; font-weight: 600; flex-shrink: 0; }

/* Table */
.cmp-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.cmp-table th, .cmp-table td { padding: 8px 12px; border-bottom: 1px solid #f0f0f0; text-align: center; }
.cmp-table th { background: #fafafa; font-weight: 600; }
.best-row { background: #e6f7ff; }

/* Badge */
.badge { display: inline-flex; padding: 2px 8px; border-radius: 10px; font-size: 10px; font-weight: 600; }
.b-pos { background: #f6ffed; color: #389e0d; }
.b-neg { background: #fff2f0; color: #cf1322; }
.b-flat { background: #f5f5f5; color: #8c8c8c; }

/* Overlap grid */
.overlap-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.card-inner { border: 1px solid #f0f0f0; border-radius: 4px; padding: 12px; }
.card-inner-h { font-size: 12px; font-weight: 600; margin-bottom: 8px; }

/* Utility */
.tip { font-size: 10px; color: #c0c4cc; margin-top: 10px; }
.text-pos { color: #cf1322; }
.text-neg { color: #389e0d; }
.text-blue { color: #1890ff; }
.font-bold { font-weight: 700; }

@media (max-width: 960px) {
  .dim-grid { grid-template-columns: 1fr; }
  .kpi-row { grid-template-columns: 1fr 1fr; }
}
</style>
