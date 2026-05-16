<template>
  <div class="factor-lab">
    <!-- 顶部工具栏 -->
    <div class="lab-toolbar">
      <div class="toolbar-left">
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          range-separator="~"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          format="YYYY-MM-DD"
          value-format="YYYY-MM-DD"
          :disabled-date="(d: Date) => d > new Date()"
          size="small"
          style="width: 240px"
        />
        <el-select v-model="holdingDays" size="small" style="width: 120px">
          <el-option v-for="d in [1,3,5,7,10,15,20,30]" :key="d" :label="`${d}日持仓`" :value="d" />
        </el-select>
        <el-select v-model="fusionMode" size="small" style="width: 150px">
          <el-option label="全部满足(AND)" value="and" />
          <el-option label="满足N项(投票)" value="vote" />
          <el-option label="加权评分(Score)" value="score" />
        </el-select>
        <el-input-number
          v-if="fusionMode === 'vote'"
          v-model="voteThreshold"
          :min="2"
          :max="activeFactors.length"
          size="small"
          style="width: 100px"
          controls-position="right"
        />
      </div>
      <div class="toolbar-right">
        <el-button type="primary" :loading="running" size="small" @click="runBacktest">
          ▶ 运行回测
        </el-button>
      </div>
    </div>

    <!-- 预设模板 -->
    <div class="preset-bar">
      <span class="preset-label">预设:</span>
      <el-tag
        v-for="p in presets"
        :key="p.id"
        :type="p.id === activePreset ? '' : 'info'"
        size="small"
        class="preset-chip"
        @click="loadPreset(p)"
      >{{ p.name }}</el-tag>
    </div>

    <!-- 三栏布局 -->
    <div class="lab-grid">
      <!-- 左栏: 因子面板 -->
      <div class="lab-col lab-col-left">
        <div class="panel-header">因子面板</div>
        <el-input
          v-model="searchQuery"
          placeholder="搜索因子..."
          size="small"
          clearable
          prefix-icon="Search"
          class="factor-search"
        />
        <div class="factor-categories">
          <div
            v-for="cat in filteredCategories"
            :key="cat.key"
            class="cat-section"
          >
            <div class="cat-header" @click="toggleCategory(cat.key)">
              <span class="cat-icon">{{ cat.icon }}</span>
              <span class="cat-name">{{ cat.name }}</span>
              <span class="cat-count">({{ cat.factors.length }})</span>
              <el-icon class="cat-arrow">
                <ArrowDown v-if="expandedCats.has(cat.key)" />
                <ArrowRight v-else />
              </el-icon>
            </div>
            <div v-show="expandedCats.has(cat.key)" class="cat-items">
              <div
                v-for="f in cat.factors"
                :key="f.id"
                class="factor-item"
                :class="{ added: isFactorAdded(f.id) }"
                @click="addFactor(f)"
              >
                <span class="fi-icon" :style="{ background: categoryColor(f.category) }">
                  {{ f.icon }}
                </span>
                <span class="fi-name">{{ f.name }}</span>
                <el-icon v-if="!isFactorAdded(f.id)" class="fi-add"><Plus /></el-icon>
                <el-icon v-else class="fi-check"><Check /></el-icon>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 中栏: 活跃因子 -->
      <div class="lab-col lab-col-center">
        <div class="panel-header">
          活跃因子
          <span class="factor-count">{{ activeFactors.length }} / 15</span>
        </div>

        <!-- 权重警告 -->
        <div v-if="weightSum !== 100 && activeFactors.length > 0" class="weight-warn">
          <span class="ww-icon">⚠</span>
          <span>当前权重合计 <b>{{ weightSum }}%</b>，建议归一化到 100%</span>
          <el-button size="small" text type="warning" @click="normalizeWeights">
            一键归一化
          </el-button>
        </div>

        <!-- 因子卡片列表 -->
        <div class="active-factors">
          <div
            v-for="(af, idx) in activeFactors"
            :key="af.id"
            class="factor-card"
          >
            <div class="fc-head">
              <span class="fc-icon" :style="{ background: categoryColor(af.category) }">
                {{ af.icon }}
              </span>
              <span class="fc-name">
                {{ af.name }}
                <span class="fc-tag" :class="'t-' + af.category">
                  {{ categoryLabel(af.category) }}
                </span>
              </span>
              <span
                v-if="getContribution(af.id) !== null"
                class="fc-impact"
                :class="(getContribution(af.id) ?? 0) >= 0 ? 'text-pos' : 'text-neg'"
              >
                夏普{{ (getContribution(af.id) ?? 0) >= 0 ? '+' : '' }}{{ getContribution(af.id) }}
              </span>
              <el-switch v-model="af.enabled" size="small" />
              <el-button
                size="small"
                text
                type="danger"
                circle
                @click="removeFactor(idx)"
              >✕</el-button>
            </div>
            <div class="fc-body">
              <!-- 策略信号: 仅权重 -->
              <template v-if="af.type === 'signal'">
                <div class="param-row">
                  <span class="p-label">权重</span>
                  <el-slider
                    v-model="af.weight"
                    :min="0"
                    :max="100"
                    :show-tooltip="false"
                    size="small"
                    style="flex: 1; margin: 0 8px"
                  />
                  <el-input-number
                    v-model="af.weight"
                    :min="0"
                    :max="100"
                    size="small"
                    controls-position="right"
                    style="width: 80px"
                  />
                  <span class="p-unit">%</span>
                </div>
                <div class="fc-tip">此策略为信号类因子，仅有"是/否"状态。调整权重改变其在融合评分中的占比。</div>
              </template>

              <!-- 连续/区间指标: 条件 + 权重 -->
              <template v-else>
                <div class="param-row">
                  <span class="p-label">条件</span>
                  <el-select v-model="af.operator" size="small" style="width: 80px">
                    <el-option label="<" value="<" />
                    <el-option label="≤" value="<=" />
                    <el-option label=">" value=">" />
                    <el-option label="≥" value=">=" />
                    <el-option label="介于" value="between" />
                  </el-select>
                  <template v-if="af.operator === 'between'">
                    <el-input-number
                      v-model="(af.value as number[])[0]"
                      size="small"
                      controls-position="right"
                      style="width: 90px"
                    />
                    <span class="p-sep">~</span>
                    <el-input-number
                      v-model="(af.value as number[])[1]"
                      size="small"
                      controls-position="right"
                      style="width: 90px"
                    />
                  </template>
                  <template v-else>
                    <el-input-number
                      v-model="af.value as number"
                      size="small"
                      controls-position="right"
                      style="width: 120px"
                      @update:model-value="(v: number | undefined) => af.value = v ?? 0"
                    />
                  </template>
                </div>
                <div class="param-row">
                  <span class="p-label">权重</span>
                  <el-slider
                    v-model="af.weight"
                    :min="0"
                    :max="100"
                    :show-tooltip="false"
                    size="small"
                    style="flex: 1; margin: 0 8px"
                  />
                  <el-input-number
                    v-model="af.weight"
                    :min="0"
                    :max="100"
                    size="small"
                    controls-position="right"
                    style="width: 80px"
                  />
                  <span class="p-unit">%</span>
                </div>
                <!-- 快捷预设 -->
                <div v-if="af.presets && af.presets.length" class="preset-chips">
                  <span class="chips-label">快捷:</span>
                  <el-tag
                    v-for="(ps, pi) in af.presets"
                    :key="pi"
                    size="small"
                    :type="isPresetActive(af, ps) ? '' : 'info'"
                    class="chip"
                    @click="applyFactorPreset(af, ps)"
                  >{{ ps.label }}</el-tag>
                </div>
              </template>
            </div>
          </div>

          <!-- 空状态 -->
          <div v-if="activeFactors.length === 0" class="empty-state">
            ← 从左侧因子面板点击 + 添加因子<br>
            <span class="empty-hint">建议添加 3~8 个因子，不超过 15 个以避免过拟合</span>
          </div>
        </div>

        <!-- 信号稀疏警告 -->
        <div v-if="result && result.signal_sparse_warning" class="signal-warn">
          <span class="sw-icon">⚠</span>
          <span>日均信号数仅 <b>{{ result.kpi.daily_signal_avg }}</b>，接近稀疏阈值(3)。继续添加过滤因子可能影响回测可靠性。</span>
        </div>
      </div>

      <!-- 右栏: 结果面板 -->
      <div class="lab-col lab-col-right">
        <div class="panel-header">回测结果</div>

        <!-- 首次进入空状态 -->
        <div v-if="!result && !running" class="empty-result">
          <el-empty description="请添加因子并运行回测" :image-size="80" />
        </div>

        <!-- Loading -->
        <div v-if="running" class="loading-state">
          <el-skeleton :rows="6" animated />
        </div>

        <!-- 结果内容 -->
        <template v-if="result && !running">
          <!-- KPI 卡片 -->
          <div class="result-kpi">
            <div class="kpi highlight">
              <div class="k-label">夏普比率</div>
              <div class="k-value" :class="kpiColor(result.kpi.sharpe)">
                {{ result.kpi.sharpe ?? '-' }}
              </div>
              <div v-if="sharpeImprovement" class="k-delta text-pos">
                vs 基线 {{ sharpeImprovement }}
              </div>
            </div>
            <div class="kpi">
              <div class="k-label">胜率</div>
              <div class="k-value">{{ result.kpi.win_rate != null ? result.kpi.win_rate + '%' : '-' }}</div>
            </div>
            <div class="kpi">
              <div class="k-label">{{ holdingDays }}日平均收益</div>
              <div class="k-value" :class="(result.kpi.avg_return ?? 0) > 0 ? 'text-pos' : 'text-neg'">
                {{ result.kpi.avg_return != null ? (result.kpi.avg_return > 0 ? '+' : '') + result.kpi.avg_return + '%' : '-' }}
              </div>
            </div>
            <div class="kpi">
              <div class="k-label">最大回撤</div>
              <div class="k-value" :class="kpiColor(-(result.kpi.max_drawdown ?? 0))">
                {{ result.kpi.max_drawdown != null ? result.kpi.max_drawdown + '%' : '-' }}
              </div>
            </div>
            <div class="kpi">
              <div class="k-label">日均信号数</div>
              <div class="k-value">{{ result.kpi.daily_signal_avg }}</div>
              <div v-if="result.kpi.filter_rate" class="k-delta" style="color: #999">
                筛选率 {{ result.kpi.filter_rate }}%
              </div>
            </div>
            <div class="kpi">
              <div class="k-label">Calmar</div>
              <div class="k-value">{{ result.kpi.calmar ?? '-' }}</div>
            </div>
          </div>

          <!-- 迷你收益曲线 -->
          <div ref="chartRef" class="result-chart" />

          <!-- 因子贡献排名 -->
          <div v-if="result.factor_contributions.length" class="card">
            <div class="card-h">因子贡献排名 <span class="card-sub">对夏普的边际贡献</span></div>
            <div class="card-b">
              <div
                v-for="fc in result.factor_contributions"
                :key="fc.id"
                class="contrib-row"
              >
                <span class="cr-icon" :style="{ background: categoryColor(fc.category) }">
                  {{ fc.name[0] }}
                </span>
                <span class="cr-name">{{ fc.name }}</span>
                <div class="cr-bar">
                  <div
                    class="cr-fill"
                    :style="{
                      width: contribBarWidth(fc.impact) + '%',
                      background: (fc.impact ?? 0) >= 0 ? categoryColor(fc.category) : '#ff4d4f'
                    }"
                  />
                </div>
                <span
                  class="cr-val"
                  :class="(fc.impact ?? 0) >= 0 ? 'text-pos' : 'text-neg'"
                >{{ fc.impact != null ? ((fc.impact >= 0 ? '+' : '') + fc.impact) : '-' }}</span>
              </div>
            </div>
          </div>

          <!-- 对比表 -->
          <div class="card">
            <div class="card-h">与基线对比</div>
            <div class="card-b" style="padding: 0; overflow-x: auto">
              <table class="compare-table">
                <thead>
                  <tr>
                    <th>指标</th>
                    <th>纯策略信号</th>
                    <th class="best-col">当前方案</th>
                    <th>变化</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>{{ holdingDays }}日收益</td>
                    <td>{{ fmtPct(result.baseline.avg_return) }}</td>
                    <td class="best-cell">{{ fmtPct(result.kpi.avg_return) }}</td>
                    <td>{{ fmtDelta(result.kpi.avg_return, result.baseline.avg_return) }}</td>
                  </tr>
                  <tr>
                    <td>胜率</td>
                    <td>{{ fmtPct(result.baseline.win_rate) }}</td>
                    <td class="best-cell">{{ fmtPct(result.kpi.win_rate) }}</td>
                    <td>{{ fmtDeltaPP(result.kpi.win_rate, result.baseline.win_rate) }}</td>
                  </tr>
                  <tr>
                    <td>夏普</td>
                    <td>{{ result.baseline.sharpe ?? '-' }}</td>
                    <td class="best-cell">{{ result.kpi.sharpe ?? '-' }}</td>
                    <td>{{ fmtDelta(result.kpi.sharpe, result.baseline.sharpe) }}</td>
                  </tr>
                  <tr>
                    <td>最大回撤</td>
                    <td>{{ fmtPct(result.baseline.max_drawdown) }}</td>
                    <td class="best-cell">{{ fmtPct(result.kpi.max_drawdown) }}</td>
                    <td>{{ fmtDelta(result.kpi.max_drawdown, result.baseline.max_drawdown) }}</td>
                  </tr>
                  <tr>
                    <td>信号数</td>
                    <td>{{ result.baseline.signal_count }}</td>
                    <td>{{ result.kpi.signal_count }}</td>
                    <td>{{ fmtDelta(result.kpi.signal_count, result.baseline.signal_count) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, nextTick, onUnmounted, watch } from 'vue'
import { ArrowDown, ArrowRight, Plus, Check } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'
import dayjs from 'dayjs'
import {
  getFactorCatalog,
  getFactorPresets,
  runFactorLab,
  type FactorMeta,
  type FactorCategory,
  type Preset,
  type FactorLabRunResult,
} from '@/api/factorLab'

// ── 状态 ──────────────────────────────────────────────────────────────

const dateRange = ref<[string, string]>([
  dayjs().subtract(3, 'month').format('YYYY-MM-DD'),
  dayjs().format('YYYY-MM-DD'),
])
const holdingDays = ref(10)
const fusionMode = ref<'and' | 'vote' | 'score'>('score')
const voteThreshold = ref(3)
const running = ref(false)
const searchQuery = ref('')

// 因子目录
const categories = ref<FactorCategory[]>([])
const expandedCats = ref(new Set(['tech_signal']))
const presets = ref<Preset[]>([])
const activePreset = ref('')

// 活跃因子
interface ActiveFactorItem {
  id: string
  name: string
  category: string
  type: string
  icon: string
  weight: number
  enabled: boolean
  operator?: string
  value?: number | number[]
  presets?: { label: string; operator: string; value: number | number[] }[]
}
const activeFactors = ref<ActiveFactorItem[]>([])

// 回测结果
const result = ref<FactorLabRunResult | null>(null)
const chartRef = ref<HTMLDivElement | null>(null)
let chartInstance: echarts.ECharts | null = null

// ── 初始化 ────────────────────────────────────────────────────────────

onMounted(async () => {
  try {
    const [catRes, presetRes] = await Promise.all([
      getFactorCatalog(),
      getFactorPresets(),
    ])
    categories.value = catRes.data.categories
    presets.value = presetRes.data.presets
  } catch {
    ElMessage.error('加载因子目录失败')
  }
})

onUnmounted(() => {
  chartInstance?.dispose()
  chartInstance = null
})

// ── 因子操作 ──────────────────────────────────────────────────────────

const filteredCategories = computed(() => {
  const q = searchQuery.value.toLowerCase().trim()
  if (!q) return categories.value
  return categories.value
    .map((cat) => ({
      ...cat,
      factors: cat.factors.filter(
        (f) => f.name.toLowerCase().includes(q) || f.id.toLowerCase().includes(q)
      ),
    }))
    .filter((cat) => cat.factors.length > 0)
})

// Auto-expand categories when searching
watch(searchQuery, (q) => {
  if (q.trim()) {
    filteredCategories.value.forEach((c) => expandedCats.value.add(c.key))
  }
})

function toggleCategory(key: string) {
  if (expandedCats.value.has(key)) {
    expandedCats.value.delete(key)
  } else {
    expandedCats.value.add(key)
  }
}

function isFactorAdded(id: string) {
  return activeFactors.value.some((f) => f.id === id)
}

function addFactor(meta: FactorMeta) {
  if (isFactorAdded(meta.id)) return
  if (activeFactors.value.length >= 15) {
    ElMessage.warning('最多支持 15 个因子')
    return
  }
  const item: ActiveFactorItem = {
    id: meta.id,
    name: meta.name,
    category: meta.category,
    type: meta.type,
    icon: meta.icon,
    weight: 10,
    enabled: true,
    presets: meta.presets,
  }
  if (meta.type !== 'signal') {
    item.operator = meta.default_operator || '>'
    if (meta.default_value != null) {
      item.value = Array.isArray(meta.default_value)
        ? [...meta.default_value]
        : meta.default_value
    } else {
      item.value = 0
    }
  }
  activeFactors.value.push(item)
}

function removeFactor(idx: number) {
  activeFactors.value.splice(idx, 1)
}

// ── 权重 ──────────────────────────────────────────────────────────────

const weightSum = computed(() =>
  activeFactors.value.reduce((s, f) => s + (f.enabled ? f.weight : 0), 0)
)

function normalizeWeights() {
  const enabled = activeFactors.value.filter((f) => f.enabled)
  if (enabled.length === 0) return
  const total = enabled.reduce((s, f) => s + f.weight, 0)
  if (total === 0) {
    const each = Math.floor(100 / enabled.length)
    enabled.forEach((f) => (f.weight = each))
    enabled[0].weight += 100 - each * enabled.length
    return
  }
  let assigned = 0
  enabled.forEach((f, i) => {
    if (i === enabled.length - 1) {
      f.weight = 100 - assigned
    } else {
      f.weight = Math.round((f.weight / total) * 100)
      assigned += f.weight
    }
  })
}

// ── 预设 ──────────────────────────────────────────────────────────────

function loadPreset(preset: Preset) {
  activePreset.value = preset.id
  fusionMode.value = (preset.fusion_mode || 'and') as 'and' | 'vote' | 'score'
  if (preset.vote_threshold) voteThreshold.value = preset.vote_threshold

  activeFactors.value = preset.factors.map((pf) => {
    const meta = findFactorMeta(pf.id)
    return {
      id: pf.id,
      name: pf.name || meta?.name || pf.id,
      category: pf.category || meta?.category || 'tech_signal',
      type: pf.type || meta?.type || 'signal',
      icon: pf.icon || meta?.icon || '?',
      weight: pf.weight,
      enabled: pf.enabled,
      operator: pf.operator || meta?.default_operator,
      value: pf.value != null
        ? (Array.isArray(pf.value) ? [...pf.value] : pf.value)
        : meta?.default_value,
      presets: meta?.presets,
    }
  })
}

function findFactorMeta(id: string): FactorMeta | undefined {
  for (const cat of categories.value) {
    const f = cat.factors.find((f) => f.id === id)
    if (f) return f
  }
  return undefined
}

function applyFactorPreset(af: ActiveFactorItem, ps: { operator: string; value: number | number[] }) {
  af.operator = ps.operator
  af.value = Array.isArray(ps.value) ? [...ps.value] : ps.value
}

function isPresetActive(af: ActiveFactorItem, ps: { operator: string; value: number | number[] }) {
  if (af.operator !== ps.operator) return false
  if (Array.isArray(ps.value)) {
    return Array.isArray(af.value) && af.value[0] === ps.value[0] && af.value[1] === ps.value[1]
  }
  return af.value === ps.value
}

// ── 运行回测 ──────────────────────────────────────────────────────────

async function runBacktest() {
  const enabled = activeFactors.value.filter((f) => f.enabled)
  if (enabled.length === 0) {
    ElMessage.warning('请至少启用 1 个因子')
    return
  }
  if (!enabled.some((f) => f.type === 'signal')) {
    ElMessage.warning('至少需要 1 个策略信号因子')
    return
  }
  if (!dateRange.value || !dateRange.value[0]) {
    ElMessage.warning('请选择日期范围')
    return
  }

  running.value = true
  result.value = null

  try {
    const res = await runFactorLab({
      factors: enabled.map((f) => ({
        id: f.id,
        weight: f.weight,
        enabled: true,
        operator: f.operator,
        value: f.value,
      })),
      fusion_mode: fusionMode.value,
      vote_threshold: voteThreshold.value,
      holding_days: holdingDays.value,
      start_date: dateRange.value[0],
      end_date: dateRange.value[1],
    })
    result.value = res.data
    await nextTick()
    renderChart()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '回测失败')
  } finally {
    running.value = false
  }
}

// ── 收益曲线图 ────────────────────────────────────────────────────────

function renderChart() {
  if (!chartRef.value || !result.value?.daily_series?.length) return
  chartInstance?.dispose()
  chartInstance = echarts.init(chartRef.value)

  const dates = result.value.daily_series.map((d) => d.date)
  const cumulative = result.value.daily_series.map((d) => d.cumulative)
  const drawdown = result.value.daily_series.map((d) => d.drawdown)

  chartInstance.setOption({
    grid: [
      { left: 50, right: 16, top: 10, height: '55%' },
      { left: 50, right: 16, top: '72%', height: '22%' },
    ],
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
    },
    xAxis: [
      { type: 'category', data: dates, gridIndex: 0, show: false, boundaryGap: false },
      { type: 'category', data: dates, gridIndex: 1, boundaryGap: false,
        axisLabel: { fontSize: 10 } },
    ],
    yAxis: [
      { type: 'value', gridIndex: 0, name: '累计', axisLabel: { fontSize: 10 },
        splitLine: { lineStyle: { type: 'dashed' } } },
      { type: 'value', gridIndex: 1, name: '回撤%', axisLabel: { fontSize: 10 },
        splitLine: { lineStyle: { type: 'dashed' } } },
    ],
    series: [
      { name: '累计收益', type: 'line', data: cumulative, xAxisIndex: 0, yAxisIndex: 0,
        lineStyle: { width: 1.5, color: '#1890ff' }, symbol: 'none',
        areaStyle: { color: 'rgba(24,144,255,0.08)' } },
      { name: '回撤', type: 'line', data: drawdown, xAxisIndex: 1, yAxisIndex: 1,
        lineStyle: { width: 1, color: '#ff4d4f' }, symbol: 'none',
        areaStyle: { color: 'rgba(255,77,79,0.08)' } },
    ],
  })
}

// 窗口 resize
const onResize = () => chartInstance?.resize()
onMounted(() => window.addEventListener('resize', onResize))
onUnmounted(() => window.removeEventListener('resize', onResize))

// ── 辅助函数 ──────────────────────────────────────────────────────────

function categoryColor(cat: string) {
  const m: Record<string, string> = {
    tech_signal: '#1890ff',
    tech_indicator: '#40a9ff',
    fundamental: '#52c41a',
    fund_flow: '#faad14',
  }
  return m[cat] || '#999'
}

function categoryLabel(cat: string) {
  const m: Record<string, string> = {
    tech_signal: '策略信号',
    tech_indicator: '技术指标',
    fundamental: '基本面',
    fund_flow: '资金流',
  }
  return m[cat] || cat
}

function getContribution(id: string): number | null {
  if (!result.value) return null
  const c = result.value.factor_contributions.find((fc) => fc.id === id)
  return c?.impact ?? null
}

const sharpeImprovement = computed(() => {
  if (!result.value) return ''
  const curr = result.value.kpi.sharpe
  const base = result.value.baseline.sharpe
  if (curr == null || base == null || base === 0) return ''
  const pct = ((curr - base) / Math.abs(base) * 100).toFixed(1)
  return (Number(pct) > 0 ? '+' : '') + pct + '%'
})

function kpiColor(v: number | null) {
  if (v == null) return ''
  return v > 0 ? 'text-pos' : v < 0 ? 'text-neg' : ''
}

function contribBarWidth(impact: number | null) {
  if (!result.value || impact == null) return 0
  const maxAbs = Math.max(
    ...result.value.factor_contributions.map((c) => Math.abs(c.impact ?? 0)),
    0.01
  )
  return Math.min(100, (Math.abs(impact) / maxAbs) * 100)
}

function fmtPct(v: number | null) {
  if (v == null) return '-'
  return (v > 0 ? '+' : '') + v + '%'
}

function fmtDelta(curr: number | null, base: number | null) {
  if (curr == null || base == null || base === 0) return '-'
  const pct = ((curr - base) / Math.abs(base) * 100).toFixed(1)
  return (Number(pct) > 0 ? '+' : '') + pct + '%'
}

function fmtDeltaPP(curr: number | null, base: number | null) {
  if (curr == null || base == null) return '-'
  const pp = (curr - base).toFixed(1)
  return (Number(pp) > 0 ? '+' : '') + pp + 'pp'
}
</script>

<style scoped>
.factor-lab {
  padding: 12px 16px;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  font-size: 13px;
}

/* 工具栏 */
.lab-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
  flex-shrink: 0;
}
.toolbar-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* 预设栏 */
.preset-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
  flex-shrink: 0;
}
.preset-label {
  font-size: 12px;
  color: #999;
}
.preset-chip {
  cursor: pointer;
}

/* 三栏网格 */
.lab-grid {
  display: grid;
  grid-template-columns: 240px 1fr 320px;
  gap: 12px;
  flex: 1;
  overflow: hidden;
}
.lab-col {
  overflow-y: auto;
  border: 1px solid #eee;
  border-radius: 6px;
  background: #fff;
}
.lab-col-left {
  min-width: 220px;
}
.lab-col-center {
  min-width: 0;
}
.lab-col-right {
  min-width: 300px;
}

.panel-header {
  font-size: 13px;
  font-weight: 600;
  padding: 10px 12px 8px;
  border-bottom: 1px solid #f0f0f0;
  position: sticky;
  top: 0;
  background: #fff;
  z-index: 2;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.factor-count {
  font-weight: normal;
  font-size: 11px;
  color: #999;
}

/* 因子搜索 */
.factor-search {
  margin: 8px 8px 4px;
}

/* 分类 */
.cat-section {
  border-bottom: 1px solid #f5f5f5;
}
.cat-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  cursor: pointer;
  font-size: 12px;
  font-weight: 600;
  user-select: none;
}
.cat-header:hover {
  background: #fafafa;
}
.cat-icon {
  font-size: 14px;
}
.cat-count {
  color: #bbb;
  font-weight: normal;
  font-size: 11px;
}
.cat-arrow {
  margin-left: auto;
  font-size: 12px;
  color: #ccc;
}

/* 因子项 */
.factor-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px 5px 24px;
  cursor: pointer;
  font-size: 12px;
}
.factor-item:hover {
  background: #f6f9ff;
}
.factor-item.added {
  opacity: 0.5;
  cursor: default;
}
.fi-icon {
  width: 20px;
  height: 20px;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 10px;
  flex-shrink: 0;
}
.fi-name {
  flex: 1;
}
.fi-add, .fi-check {
  font-size: 14px;
  color: #ccc;
}

/* 活跃因子区 */
.active-factors {
  padding: 8px;
}
.empty-state {
  text-align: center;
  padding: 32px 16px;
  color: #bbb;
  font-size: 12px;
  border: 1px dashed #e0e0e0;
  border-radius: 6px;
  margin: 8px;
}
.empty-hint {
  font-size: 10px;
  margin-top: 6px;
  display: inline-block;
}

/* 权重警告 */
.weight-warn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  margin: 0 8px 6px;
  background: #fff7e6;
  border: 1px solid #ffe58f;
  border-radius: 4px;
  font-size: 11px;
  color: #fa8c16;
}
.ww-icon { font-size: 14px; }

/* 信号稀疏警告 */
.signal-warn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  margin: 6px 8px;
  background: #fff2f0;
  border: 1px solid #ffccc7;
  border-radius: 4px;
  font-size: 11px;
  color: #ff4d4f;
}
.sw-icon { font-size: 14px; }

/* 因子卡片 */
.factor-card {
  border: 1px solid #f0f0f0;
  border-radius: 6px;
  margin-bottom: 8px;
  overflow: hidden;
}
.fc-head {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 10px;
  background: #fafafa;
}
.fc-icon {
  width: 22px;
  height: 22px;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 11px;
  flex-shrink: 0;
}
.fc-name {
  flex: 1;
  font-size: 12px;
  font-weight: 500;
}
.fc-tag {
  font-size: 10px;
  padding: 1px 4px;
  border-radius: 2px;
  margin-left: 4px;
  font-weight: normal;
}
.t-tech_signal { background: #e6f7ff; color: #1890ff; }
.t-tech_indicator { background: #e6f7ff; color: #40a9ff; }
.t-fundamental { background: #f6ffed; color: #52c41a; }
.t-fund_flow { background: #fff7e6; color: #faad14; }
.fc-impact {
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}
.fc-body {
  padding: 8px 10px;
}
.fc-tip {
  font-size: 10px;
  color: #bbb;
  margin-top: 6px;
}
.param-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}
.p-label {
  font-size: 11px;
  color: #666;
  width: 36px;
  flex-shrink: 0;
}
.p-unit {
  font-size: 11px;
  color: #999;
}
.p-sep {
  font-size: 11px;
  color: #999;
}

/* 快捷预设 */
.preset-chips {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
  margin-top: 4px;
}
.chips-label {
  font-size: 10px;
  color: #bbb;
}
.chip {
  cursor: pointer;
  font-size: 10px !important;
}

/* 颜色类 */
.text-pos { color: #52c41a; }
.text-neg { color: #ff4d4f; }

/* 右栏结果 */
.empty-result {
  padding: 32px 0;
}
.loading-state {
  padding: 16px;
}

/* KPI 卡片 */
.result-kpi {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  padding: 10px;
}
.kpi {
  padding: 8px 10px;
  border: 1px solid #f0f0f0;
  border-radius: 6px;
}
.kpi.highlight {
  border-color: #1890ff;
  background: #f0f8ff;
}
.k-label {
  font-size: 11px;
  color: #999;
}
.k-value {
  font-size: 18px;
  font-weight: 700;
  margin: 2px 0;
}
.k-delta {
  font-size: 10px;
}

/* 收益曲线 */
.result-chart {
  height: 200px;
  margin: 0 10px 8px;
}

/* 卡片通用 */
.card {
  margin: 0 10px 10px;
  border: 1px solid #f0f0f0;
  border-radius: 6px;
  overflow: hidden;
}
.card-h {
  font-size: 12px;
  font-weight: 600;
  padding: 8px 12px;
  border-bottom: 1px solid #f5f5f5;
}
.card-sub {
  font-weight: normal;
  color: #bbb;
  margin-left: 6px;
  font-size: 11px;
}
.card-b {
  padding: 8px 12px;
}

/* 因子贡献 */
.contrib-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 5px;
}
.cr-icon {
  width: 18px;
  height: 18px;
  border-radius: 3px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 9px;
  flex-shrink: 0;
}
.cr-name {
  font-size: 11px;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cr-bar {
  width: 70px;
  height: 5px;
  background: #f0f0f0;
  border-radius: 3px;
  overflow: hidden;
  flex-shrink: 0;
}
.cr-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.3s;
}
.cr-val {
  font-size: 11px;
  font-weight: 600;
  width: 44px;
  text-align: right;
  flex-shrink: 0;
}

/* 对比表 */
.compare-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 11px;
}
.compare-table th,
.compare-table td {
  padding: 6px 8px;
  border-bottom: 1px solid #f5f5f5;
  text-align: center;
}
.compare-table th {
  background: #fafafa;
  font-weight: 600;
}
.best-col {
  background: #f0fff0 !important;
}
.best-cell {
  background: #f0fff0;
  font-weight: 600;
}

/* 响应式 */
@media (max-width: 960px) {
  .lab-grid {
    grid-template-columns: 1fr;
    grid-template-rows: auto;
  }
  .lab-col {
    max-height: 400px;
  }
}
</style>
</template>
