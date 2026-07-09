<template>
  <el-drawer
    v-model="show"
    :title="drawerTitle"
    direction="rtl"
    :size="isMobile ? '100%' : '560px'"
    :destroy-on-close="false"
    @opened="onOpened"
  >
    <div v-loading="loading" class="fdd-body">
      <div v-if="loadError" class="fdd-error">{{ loadError }}</div>

      <template v-else>
        <!-- 摘要条 -->
        <div v-if="composite" class="fdd-summary">
          <div class="fdd-summary-line">
            <el-tag size="small" type="info">{{ composite.fund_type || '—' }}</el-tag>
            <el-tag size="small" :type="riskTagType(composite.risk_level)">
              风险 {{ composite.risk_level }}
            </el-tag>
            <span v-if="composite.style?.text" class="fdd-style">{{ composite.style.text }}</span>
          </div>
          <div class="fdd-summary-text">{{ composite.summary }}</div>
        </div>

        <!-- 投资价值标签 chips（F11 value_labels）-->
        <div v-if="valueTags.length" class="fdd-value-chips">
          <span v-for="(t, i) in valueTags" :key="i" class="fdd-value-chip">{{ t }}</span>
        </div>

        <!-- 关键指标条（§9.3 KPI：近1/3/5年/夏普/回撤/基准超额，正负着色）-->
        <div v-if="kpiItems.length" class="fdd-kpi-bar">
          <div v-for="k in kpiItems" :key="k.label" class="fdd-kpi">
            <div class="fdd-kpi-label">{{ k.label }}</div>
            <div class="fdd-kpi-value" :style="{ color: k.color }">{{ k.text }}</div>
          </div>
        </div>

        <!-- 入场时机（P1：T1 回撤位置 + T2 趋势确认，读 cn_fund_nav_history）-->
        <div v-if="timing" class="fdd-section fdd-timing">
          <div class="fdd-section-title">🎯 入场时机</div>
          <div v-if="!timing.timing_applicable" class="fdd-empty">货币型不做点位择时。</div>
          <div v-else-if="!timing.data_available" class="fdd-empty">暂无择时数据（无净值历史）。</div>
          <template v-else>
            <div class="fdd-timing-head">
              <span
                v-if="!timing.stale && timing.tier"
                class="fdd-tier"
                :class="tierClass(timing.tier)"
              >{{ timing.tier }}</span>
              <span v-if="!timing.stale && timing.timing_score != null" class="fdd-timing-score">
                择时分 <b>{{ timing.timing_score.toFixed(0) }}</b>
              </span>
              <span v-if="timing.stale" class="fdd-timing-stale">
                净值滞后（{{ timing.as_of || '—' }}），暂不产出档位
              </span>
              <span v-if="timing.acc_null" class="fdd-timing-flag" title="缺累计净值，用单位净值近似">缺累计·近似</span>
              <span v-if="timing.quality_pass" class="fdd-timing-quality">质量优选</span>
            </div>
            <div v-if="timingComponents.length" class="fdd-timing-bars">
              <div v-for="c in timingComponents" :key="c.key" class="fdd-timing-bar-row">
                <span class="fdd-timing-bar-label">{{ c.label }}</span>
                <div class="fdd-timing-track">
                  <div class="fdd-timing-fill" :style="{ width: c.width, background: c.color }"></div>
                </div>
                <span class="fdd-timing-bar-val">{{ c.text }}</span>
              </div>
            </div>
            <div class="fdd-timing-note">
              低吸≥75 · 定投50–75 · 观望30–50 · 高估勿追&lt;30；回撤越深 / 站稳长均线 / 指数估值越低得分越高，仅供参考、非买卖建议。
            </div>
          </template>
        </div>

        <!-- 底层持仓位置（P4 T6：季报前十大重仓股技术位置，仅展示参考，不入择时分）-->
        <div v-if="lookThrough && lookThrough.data_available" class="fdd-section fdd-lookthrough">
          <div class="fdd-section-title">
            🔬 底层持仓位置
            <span v-if="lookThroughQuarter" class="fdd-muted">（{{ lookThroughQuarter }} · 参考）</span>
          </div>
          <div class="fdd-lt-head">
            <span class="fdd-tier" :class="ltLabelClass(lookThrough.position_label)">
              {{ lookThrough.position_label }}
            </span>
            <span v-if="lookThrough.position_score != null" class="fdd-timing-score">
              位置分 <b>{{ lookThrough.position_score.toFixed(0) }}</b>
            </span>
            <span class="fdd-muted">
              已评估 {{ lookThrough.scored_count }}/{{ lookThrough.holdings_count }} 只 · 覆盖净值 {{ lookThrough.covered_ratio.toFixed(1) }}%
            </span>
          </div>
          <div class="fdd-lt-list">
            <div v-for="h in lookThrough.holdings" :key="h.stock_code" class="fdd-lt-row">
              <span class="fdd-lt-name">
                {{ h.stock_name || h.stock_code }}
                <i v-if="h.hold_ratio != null" class="fdd-muted">{{ h.hold_ratio.toFixed(1) }}%</i>
              </span>
              <template v-if="h.priced && h.position_score != null">
                <div class="fdd-timing-track">
                  <div
                    class="fdd-timing-fill"
                    :style="{ width: `${Math.max(0, Math.min(100, h.position_score))}%`, background: timingBarColor(h.position_score) }"
                  ></div>
                </div>
                <span class="fdd-lt-val">{{ h.position_score.toFixed(0) }}</span>
              </template>
              <span v-else class="fdd-lt-na fdd-muted">无本地行情</span>
            </div>
          </div>
          <div class="fdd-timing-note">
            位置分越高＝底仓越处历史低位（距高点回撤深 / 跌破长均线 / RSI 超卖），越适合分批建仓；季报滞后约一季度、穿透不完整，仅供参考、非买卖建议。
          </div>
        </div>

        <!-- 持仓风格暴露（P4：季报行业暴露/集中度 + 前向兼容漂移，风控辅助展示，非硬拦截）-->
        <div v-if="style && style.data_available" class="fdd-section fdd-style">
          <div class="fdd-section-title">
            🎯 持仓风格暴露
            <span v-if="styleQuarter" class="fdd-muted">（{{ styleQuarter }} · 参考）</span>
          </div>
          <div class="fdd-lt-head">
            <span v-if="style.concentration_label" class="fdd-tier" :class="concClass(style.concentration_label)">
              {{ style.concentration_label }}
            </span>
            <span v-if="style.hhi != null" class="fdd-timing-score">
              集中度 <b>{{ (style.hhi * 100).toFixed(0) }}</b>
            </span>
            <span class="fdd-muted">
              覆盖净值 {{ style.disclosed_ratio.toFixed(1) }}%
              <template v-if="style.unclassified_ratio != null"> · 未分类 {{ (style.unclassified_ratio * 100).toFixed(0) }}%</template>
            </span>
          </div>
          <div class="fdd-lt-list">
            <div v-for="ind in style.industries" :key="ind.industry" class="fdd-lt-row">
              <span class="fdd-lt-name">{{ ind.industry }}</span>
              <div class="fdd-timing-track">
                <div class="fdd-timing-fill fdd-style-fill" :style="{ width: `${industryBarWidth(ind.share)}%` }"></div>
              </div>
              <span class="fdd-lt-val">{{ ind.weight.toFixed(1) }}%</span>
            </div>
          </div>
          <!-- 风格漂移：需 ≥2 季报，历史累积后自动点亮 -->
          <div v-if="style.drift_available && style.drift" class="fdd-style-drift">
            <span class="fdd-tier" :class="driftClass(style.drift.drift_label)">
              {{ style.drift.drift_label }}
            </span>
            <span class="fdd-timing-score">漂移 <b>{{ style.drift.drift_score.toFixed(0) }}</b></span>
            <span v-if="style.prev_quarter" class="fdd-muted">vs 上季</span>
            <span
              v-for="ch in style.drift.top_changes.slice(0, 3)"
              :key="ch.industry"
              class="fdd-style-chg"
              :class="ch.delta >= 0 ? 'up' : 'down'"
            >{{ ch.industry }} {{ ch.delta >= 0 ? '+' : '' }}{{ (ch.delta * 100).toFixed(0) }}%</span>
          </div>
          <div v-else class="fdd-timing-note fdd-muted">风格漂移需 ≥2 期季报，历史累积中，暂不可用。</div>
          <div class="fdd-timing-note">
            按季报前十大重仓股行业加权；集中度越高＝越押注单一赛道。「未分类」含科创板等未回填行业个股，仅透明化占比、不计入集中度。仅风控辅助、非买卖建议。
          </div>
        </div>

        <!-- 净值走势曲线 -->
        <div class="fdd-section">
          <div class="fdd-section-title fdd-nav-title">
            <span>净值走势</span>
            <div class="fdd-nav-ranges">
              <span
                v-for="r in navRanges"
                :key="r.value"
                class="fdd-nav-range"
                :class="{ active: r.value === navRange }"
                @click="switchNavRange(r.value)"
              >{{ r.label }}</span>
            </div>
          </div>
          <div v-show="hasNav" ref="navRef" v-loading="navLoading" class="fdd-navchart"></div>
          <div v-if="!hasNav && !navLoading" class="fdd-empty">暂无净值历史数据</div>
        </div>

        <!-- 五维同类雷达 -->
        <div class="fdd-section">
          <div class="fdd-section-title">
            同类评比
            <span v-if="peer" class="fdd-peer-count">（同类 {{ peer.peer_count }} 只）</span>
          </div>
          <div v-show="hasRadar" ref="radarRef" class="fdd-radar"></div>
          <div v-if="!hasRadar && !loading" class="fdd-empty">暂无同类对比数据</div>
          <div v-if="peer && peer.dims?.length" class="fdd-dim-legend">
            <span
              v-for="d in peer.dims"
              :key="d.key"
              class="fdd-dim-chip"
              :title="`本基金 ${fmtScore(d.value)} / 同类基准 ${fmtScore(d.peer)}`"
            >
              {{ d.label }} <b>{{ fmtScore(d.value) }}</b>
            </span>
          </div>
        </div>

        <!-- 综合分析卡片 -->
        <div v-if="composite" class="fdd-section">
          <div class="fdd-section-title">综合分析</div>

          <div class="fdd-card">
            <div class="fdd-card-h">📈 历史业绩与风险</div>
            <ul class="fdd-list">
              <li v-for="(t, i) in composite.performance.texts" :key="i">{{ t }}</li>
              <li v-if="!composite.performance.texts.length" class="fdd-muted">暂无业绩指标</li>
            </ul>
          </div>

          <div class="fdd-card">
            <div class="fdd-card-h">📊 持仓与行业</div>
            <div class="fdd-kv">{{ composite.concentration.text }}</div>
            <div v-if="composite.industry?.text" class="fdd-kv">{{ composite.industry.text }}</div>
            <div v-if="topIndustries.length" class="fdd-ind-bars">
              <div v-for="ind in topIndustries" :key="ind.industry" class="fdd-ind-row">
                <span class="fdd-ind-name">{{ ind.industry }}</span>
                <div class="fdd-ind-track">
                  <div class="fdd-ind-fill" :style="{ width: indWidth(ind.ratio) }"></div>
                </div>
                <span class="fdd-ind-val">{{ ind.ratio.toFixed(1) }}%</span>
              </div>
            </div>
            <div v-show="hasIndustryPie" ref="pieRef" class="fdd-piechart"></div>
            <!-- 前十大重仓股明细 -->
            <template v-if="topHoldings.length">
              <div class="fdd-holdings-h">
                前十大重仓股<span v-if="holdingsQuarter" class="fdd-muted">（{{ holdingsQuarter }}）</span>
              </div>
              <table class="fdd-holdings">
                <thead>
                  <tr><th>股票</th><th>代码</th><th>行业</th><th class="r">占净值</th></tr>
                </thead>
                <tbody>
                  <tr v-for="h in topHoldings" :key="h.name + (h.stock_code || '')">
                    <td>{{ h.name }}</td>
                    <td class="fdd-muted">{{ h.stock_code || '—' }}</td>
                    <td>{{ h.industry || '—' }}</td>
                    <td class="r">{{ h.hold_ratio != null ? h.hold_ratio.toFixed(2) + '%' : '—' }}</td>
                  </tr>
                </tbody>
              </table>
            </template>
          </div>

          <div class="fdd-card">
            <div class="fdd-card-h">🏢 规模与成立</div>
            <ul class="fdd-list">
              <li v-for="(t, i) in composite.scale.texts" :key="i">{{ t }}</li>
              <li v-if="!composite.scale.texts.length" class="fdd-muted">暂无规模信息</li>
            </ul>
          </div>

          <div v-if="profileRows.length" class="fdd-card">
            <div class="fdd-card-h">🪪 基金画像</div>
            <table class="fdd-profile">
              <tbody>
                <tr v-for="row in profileRows" :key="row.label">
                  <th>{{ row.label }}</th>
                  <td>{{ row.value }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- AI 按需分析 -->
        <div class="fdd-section">
          <div class="fdd-section-title fdd-ai-title">
            <span>🤖 AI 综合解读</span>
            <el-button
              size="small"
              type="primary"
              :loading="aiLoading"
              @click="runAi(aiLoaded)"
            >{{ aiBtnText }}</el-button>
          </div>

          <div v-if="aiNote" class="fdd-ai-note">{{ aiNote }}</div>
          <div v-if="aiHtml" class="fdd-ai-content markdown-body" v-html="aiHtml"></div>
          <div v-else-if="!aiLoading" class="fdd-empty">
            点击「{{ aiBtnText }}」由 AI 结合近期资讯生成客观解读（非投资建议）。
          </div>

          <div v-if="aiSources.length" class="fdd-sources">
            <div class="fdd-sources-h">资讯来源</div>
            <a
              v-for="(s, i) in aiSources"
              :key="i"
              :href="s.url"
              target="_blank"
              rel="noopener noreferrer"
              class="fdd-source-link"
            >{{ s.title || s.url }}</a>
          </div>
        </div>

        <div class="fdd-disclaimer">
          {{ composite?.disclaimer || '历史业绩不代表未来，以上为基于历史数据的规则化分析，非投资建议。' }}
        </div>
      </template>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, watch } from 'vue'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'
import { useResponsive } from '@/composables/useResponsive'
import {
  getFundPeerCompare,
  getFundCompositeAnalysis,
  getFundAiAnalysis,
  runFundAiAnalysis,
  getFundNavHistory,
  getFundNavPeer,
  getFundTiming,
  getFundLookThrough,
  getFundStyle,
  type FundPeerCompare,
  type FundComposite,
  type FundAiSource,
  type FundAiAnalysis,
  type FundNavHistory,
  type FundNavPeer,
  type FundTiming,
  type FundLookThrough,
  type FundStyle,
} from '@/api/fund'

const props = defineProps<{
  modelValue: boolean
  code: string
  name?: string
}>()
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void }>()

const { isMobile } = useResponsive()

const show = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const loading = ref(false)
const loadError = ref('')
const peer = ref<FundPeerCompare | null>(null)
const composite = ref<FundComposite | null>(null)
const timing = ref<FundTiming | null>(null)
const lookThrough = ref<FundLookThrough | null>(null)
const style = ref<FundStyle | null>(null)

const aiLoading = ref(false)
const aiLoaded = ref(false)
const aiHtml = ref('')
const aiNote = ref('')
const aiSources = ref<FundAiSource[]>([])

const radarRef = ref<HTMLElement | null>(null)
let radarChart: echarts.ECharts | null = null
let mdInstance: { render: (src: string) => string } | null = null
let loadedCode = ''

// 净值曲线
const navRef = ref<HTMLElement | null>(null)
let navChart: echarts.ECharts | null = null
const navHistory = ref<FundNavHistory | null>(null)
const navPeer = ref<FundNavPeer | null>(null)
const navLoading = ref(false)
const navRange = ref('1y')
const navRanges = [
  { value: '3m', label: '近3月' },
  { value: '6m', label: '近6月' },
  { value: '1y', label: '近1年' },
  { value: '3y', label: '近3年' },
  { value: 'all', label: '成立以来' },
]
const hasNav = computed(() => !!(navHistory.value && navHistory.value.points.length))

// 行业饼图
const pieRef = ref<HTMLElement | null>(null)
let pieChart: echarts.ECharts | null = null

const drawerTitle = computed(() => {
  const n = props.name || peer.value?.name || composite.value?.name || ''
  return n ? `${n}（${props.code}）` : props.code
})

const hasRadar = computed(() => !!(peer.value && peer.value.dims && peer.value.dims.length))

const topIndustries = computed(() => {
  const dist = composite.value?.industry?.distribution || []
  return dist.slice(0, 5)
})

const hasIndustryPie = computed(() => (composite.value?.industry?.distribution?.length || 0) >= 2)

const valueTags = computed(() => {
  const v = peer.value?.value_labels
  if (!Array.isArray(v)) return [] as string[]
  return v.filter((s): s is string => !!s)
})

// 关键指标条（§9.3）：仅读 composite 已算好的派生指标，不臆造数字（防幻觉）。
const kpiItems = computed(() => {
  const p = composite.value?.performance
  if (!p) return [] as { label: string; text: string; color: string }[]
  const up = '#d23b3b'
  const down = '#16a34a'
  const neutral = '#303133'
  const pct = (v: number | null | undefined, signed = true) => {
    if (v === null || v === undefined || Number.isNaN(v)) return { text: '—', color: '#909399' }
    return {
      text: `${signed && v > 0 ? '+' : ''}${v.toFixed(2)}%`,
      color: v > 0 ? up : v < 0 ? down : neutral,
    }
  }
  const num = (v: number | null | undefined, good: 'high' | 'low') => {
    if (v === null || v === undefined || Number.isNaN(v)) return { text: '—', color: '#909399' }
    let color = neutral
    if (good === 'high') color = v >= 1 ? down : v < 0 ? up : neutral
    else color = v <= -0.3 ? up : v >= -0.1 ? down : neutral
    return { text: v.toFixed(2), color }
  }
  const ddPct = (v: number | null | undefined) => {
    if (v === null || v === undefined || Number.isNaN(v)) return { text: '—', color: '#909399' }
    return {
      text: `${(v * 100).toFixed(2)}%`,
      color: v <= -0.3 ? up : v >= -0.1 ? down : neutral,
    }
  }
  const r1 = pct(p.rate_1y)
  const r3 = pct(p.rate_3y)
  const r5 = pct(p.rate_5y)
  const sh = num(p.sharpe, 'high')
  const dd = ddPct(p.max_drawdown)
  const ex = pct(p.excess_1y)
  return [
    { label: '近1年', ...r1 },
    { label: '近3年', ...r3 },
    { label: '近5年', ...r5 },
    { label: '夏普', ...sh },
    { label: '最大回撤', ...dd },
    { label: '基准超额', ...ex },
  ]
})

const topHoldings = computed(() => composite.value?.holdings?.top || [])
const holdingsQuarter = computed(() => composite.value?.holdings?.quarter || '')

// 入场时机三维分量条（P1 仅 dd/trend 非空；val 估值分位 P3 接入）。
const TIMING_DIM_LABELS: Record<string, string> = {
  dd: '回撤位置',
  trend: '趋势确认',
  val: '估值分位',
}
function timingBarColor(v: number): string {
  // 对齐原型 dimBar：高分=绿（低吸友好）→ 低分=红（高估风险）
  if (v >= 75) return '#16a34a'
  if (v >= 50) return '#e6a23c'
  if (v >= 30) return '#606266'
  return '#d23b3b'
}
const timingComponents = computed(() => {
  const c = timing.value?.components
  if (!c) return [] as { key: string; label: string; width: string; text: string; color: string }[]
  const keys: (keyof typeof c)[] = ['dd', 'trend', 'val']
  const out: { key: string; label: string; width: string; text: string; color: string }[] = []
  for (const k of keys) {
    const v = c[k]
    if (v === null || v === undefined || Number.isNaN(v)) continue
    const clamped = Math.max(0, Math.min(100, v))
    out.push({
      key: k,
      label: TIMING_DIM_LABELS[k] || k,
      width: `${clamped}%`,
      text: v.toFixed(0),
      color: timingBarColor(v),
    })
  }
  return out
})
function tierClass(tier: string | null): string {
  if (tier === '低吸') return 'tier-low'
  if (tier === '定投') return 'tier-dca'
  if (tier === '观望') return 'tier-wait'
  if (tier === '高估勿追') return 'tier-high'
  return ''
}

// T6 穿透式持仓位置（P4 参考卡）：位置分高=底仓处历史低位（回撤深/破长均线/RSI超卖）
const lookThroughQuarter = computed(() => {
  const q = lookThrough.value?.quarter || ''
  const m = q.match(/^(\d{4}年\d季度)/)
  return m ? m[1] : q
})
function ltLabelClass(label: string | null): string {
  if (label === '多数处于低位') return 'tier-low'
  if (label === '中性偏均衡') return 'tier-dca'
  if (label === '多数处于高位') return 'tier-high'
  return ''
}

// 持仓风格暴露（P4 风控辅助卡）：行业条形按权重着色，集中度/漂移仅提示不硬拦
const styleQuarter = computed(() => {
  const q = style.value?.quarter || ''
  const m = q.match(/^(\d{4}年\d季度)/)
  return m ? m[1] : q
})
function concClass(label: string | null): string {
  if (label === '高度集中') return 'tier-high'
  if (label === '适度集中') return 'tier-dca'
  if (label === '行业分散') return 'tier-low'
  return ''
}
function driftClass(label: string | null): string {
  if (label === '显著漂移') return 'tier-high'
  if (label === '中等换仓') return 'tier-dca'
  if (label === '风格稳定') return 'tier-low'
  return ''
}
// 行业条形宽度：以第一大行业为满格，其余按占比归一
function industryBarWidth(share: number | null): number {
  const top = style.value?.industries?.[0]?.share ?? null
  if (share == null || top == null || top <= 0) return 0
  return Math.max(4, Math.min(100, (share / top) * 100))
}

const profileRows = computed(() => {
  const p = composite.value?.profile
  if (!p) return [] as { label: string; value: string }[]
  const rows: { label: string; value: string }[] = []
  const push = (label: string, value: string | null | undefined) => {
    if (value) rows.push({ label, value })
  }
  push('基金公司', p.company)
  push('基金经理', p.manager)
  push('评级', p.rating)
  push('类型', p.fund_type_detail)
  push('成立日', p.setup_date)
  push('投资策略', p.strategy)
  push('投资目标', p.objective)
  push('业绩基准', p.benchmark)
  return rows
})

const aiBtnText = computed(() => (aiLoaded.value ? '重新生成' : '生成 AI 解读'))

function fmtScore(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return v.toFixed(0)
}

function riskTagType(level: string): 'success' | 'warning' | 'danger' | 'info' {
  if (level?.includes('低')) return 'success'
  if (level?.includes('高')) return 'danger'
  if (level?.includes('中')) return 'warning'
  return 'info'
}

function indWidth(ratio: number): string {
  const max = topIndustries.value[0]?.ratio || 1
  const pct = Math.max(4, Math.min(100, (ratio / max) * 100))
  return `${pct}%`
}

async function ensureMd() {
  if (mdInstance) return mdInstance
  const MarkdownIt = (await import('markdown-it')).default
  mdInstance = new MarkdownIt({ html: false, linkify: true, typographer: true })
  return mdInstance
}

async function renderRadar() {
  if (!hasRadar.value || !radarRef.value) return
  await nextTick()
  if (!radarChart) {
    radarChart = echarts.init(radarRef.value)
  }
  const dims = peer.value!.dims
  const indicator = dims.map((d) => ({ name: d.label, max: 100 }))
  radarChart.setOption({
    tooltip: {},
    legend: {
      data: ['本基金', '同类基准'],
      bottom: 0,
      textStyle: { fontSize: 11 },
    },
    radar: {
      indicator,
      radius: '62%',
      center: ['50%', '48%'],
      splitNumber: 4,
      axisName: { fontSize: 11, color: '#606266' },
    },
    series: [
      {
        type: 'radar',
        data: [
          {
            value: dims.map((d) => d.value),
            name: '本基金',
            areaStyle: { color: 'rgba(210, 59, 59, 0.18)' },
            lineStyle: { color: '#d23b3b' },
            itemStyle: { color: '#d23b3b' },
          },
          {
            value: dims.map((d) => d.peer),
            name: '同类基准',
            lineStyle: { color: '#909399', type: 'dashed' },
            itemStyle: { color: '#909399' },
          },
        ],
      },
    ],
  })
  radarChart.resize()
}

async function renderNavCurve() {
  if (!hasNav.value || !navRef.value) return
  await nextTick()
  if (!navChart) navChart = echarts.init(navRef.value)
  const pts = navHistory.value!.points
  // 优先画累计净值（反映分红后真实增长），缺失时回退单位净值。
  const useAcc = pts.some((p) => p.acc_nav != null)
  const dates = pts.map((p) => p.date)
  const values = pts.map((p) => (useAcc ? p.acc_nav : p.unit_nav))
  const base = values.find((v) => v != null) ?? null
  // 归一化为增长百分比（起点=0%）。
  const growth = values.map((v) => (v != null && base ? ((v / base) - 1) * 100 : null))
  const last = growth[growth.length - 1]
  const up = (last ?? 0) >= 0
  const color = up ? '#d23b3b' : '#16a34a'
  // 同类平均基线：按日期对齐到本基金 x 轴（缺测日 null，connectNulls 桥接）。
  const peerPts = navPeer.value?.points || []
  const peerMap = new Map(peerPts.map((p) => [p.date, p.growth]))
  const hasPeer = peerPts.length > 0
  const peerAligned = hasPeer ? dates.map((d) => peerMap.get(d) ?? null) : []
  // 把同类平均重定基到"本基金起点同一条 0% 基准线"，便于直观看超额：
  // 找到本基金归一化起点(growth 首个非空=0%)的索引，取该处（或其后首个有效）
  // 的同类平均值作为偏移量减去，使两条线在图左侧同点出发。
  const baseIdx = growth.findIndex((v) => v != null)
  let peerOffset: number | null = null
  if (hasPeer && baseIdx >= 0) {
    for (let i = baseIdx; i < peerAligned.length; i++) {
      if (peerAligned[i] != null) {
        peerOffset = peerAligned[i] as number
        break
      }
    }
  }
  const peerSeriesData =
    hasPeer && peerOffset != null
      ? peerAligned.map((v) => (v == null ? null : Number((v - (peerOffset as number)).toFixed(4))))
      : peerAligned
  const series: echarts.LineSeriesOption[] = [
    {
      name: '本基金',
      type: 'line',
      data: growth,
      smooth: true,
      showSymbol: false,
      lineStyle: { color, width: 1.6 },
      areaStyle: {
        color: {
          type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: up ? 'rgba(210,59,59,0.18)' : 'rgba(22,163,74,0.18)' },
            { offset: 1, color: 'rgba(255,255,255,0)' },
          ],
        },
      },
    },
  ]
  if (hasPeer) {
    series.push({
      name: '同类平均',
      type: 'line',
      data: peerSeriesData,
      smooth: true,
      showSymbol: false,
      connectNulls: true,
      lineStyle: { color: '#909399', width: 1.2, type: 'dashed' },
    })
  }
  navChart.setOption(
    {
      grid: { left: 48, right: 16, top: hasPeer ? 28 : 16, bottom: 28 },
      legend: hasPeer
        ? { data: ['本基金', '同类平均'], top: 0, right: 8, itemWidth: 14, textStyle: { fontSize: 10, color: '#606266' } }
        : undefined,
      tooltip: {
        trigger: 'axis',
        valueFormatter: (v: number) => (v == null ? '—' : `${v.toFixed(2)}%`),
      },
      xAxis: {
        type: 'category',
        data: dates,
        boundaryGap: false,
        axisLabel: { fontSize: 10, color: '#909399' },
      },
      yAxis: {
        type: 'value',
        axisLabel: { fontSize: 10, color: '#909399', formatter: '{value}%' },
        splitLine: { lineStyle: { color: '#f0f2f5' } },
      },
      series,
    },
    true,
  )
  navChart.resize()
}

async function renderPie() {
  if (!hasIndustryPie.value || !pieRef.value) return
  await nextTick()
  if (!pieChart) pieChart = echarts.init(pieRef.value)
  const dist = (composite.value?.industry?.distribution || []).slice(0, 8)
  pieChart.setOption({
    tooltip: { trigger: 'item', formatter: '{b}: {c}% ({d}%)' },
    legend: { type: 'scroll', orient: 'horizontal', bottom: 0, textStyle: { fontSize: 10 } },
    series: [
      {
        type: 'pie',
        radius: ['38%', '62%'],
        center: ['50%', '44%'],
        avoidLabelOverlap: true,
        label: { show: false },
        data: dist.map((d) => ({ name: d.industry, value: Number(d.ratio.toFixed(2)) })),
      },
    ],
  })
  pieChart.resize()
}

async function loadNav() {
  if (!props.code) return
  navLoading.value = true
  try {
    const [navRes, peerRes] = await Promise.allSettled([
      getFundNavHistory(props.code, navRange.value),
      getFundNavPeer(props.code, navRange.value),
    ])
    navHistory.value =
      navRes.status === 'fulfilled' ? (navRes.value as unknown as FundNavHistory) : null
    navPeer.value =
      peerRes.status === 'fulfilled' ? (peerRes.value as unknown as FundNavPeer) : null
    await renderNavCurve()
  } catch {
    navHistory.value = null
    navPeer.value = null
  } finally {
    navLoading.value = false
  }
}

function switchNavRange(r: string) {
  if (r === navRange.value) return
  navRange.value = r
  void loadNav()
}

async function loadData() {
  if (!props.code) return
  loading.value = true
  loadError.value = ''
  peer.value = null
  composite.value = null
  timing.value = null
  lookThrough.value = null
  style.value = null
  aiLoaded.value = false
  aiHtml.value = ''
  aiNote.value = ''
  aiSources.value = []
  try {
    const [peerRes, compRes, timingRes] = await Promise.allSettled([
      getFundPeerCompare(props.code) as unknown as Promise<FundPeerCompare>,
      getFundCompositeAnalysis(props.code) as unknown as Promise<FundComposite>,
      getFundTiming(props.code) as unknown as Promise<FundTiming>,
    ])
    if (peerRes.status === 'fulfilled') peer.value = peerRes.value
    if (compRes.status === 'fulfilled') composite.value = compRes.value
    if (timingRes.status === 'fulfilled') timing.value = timingRes.value
    if (peerRes.status === 'rejected' && compRes.status === 'rejected') {
      loadError.value = '加载基金分析数据失败'
    }
    loadedCode = props.code
    await renderRadar()
    await renderPie()
    void loadNav()
    void loadLookThrough()
    void loadStyle()
    // 静默查缓存：若已有 AI 结果则直接展示
    void prefetchAi()
  } catch (e) {
    loadError.value = '加载基金分析数据失败'
  } finally {
    loading.value = false
  }
}

async function loadLookThrough() {
  lookThrough.value = null
  try {
    lookThrough.value = (await getFundLookThrough(props.code)) as unknown as FundLookThrough
  } catch {
    lookThrough.value = null
  }
}

async function loadStyle() {
  style.value = null
  try {
    style.value = (await getFundStyle(props.code)) as unknown as FundStyle
  } catch {
    style.value = null
  }
}

async function prefetchAi() {
  try {
    const res = (await getFundAiAnalysis(props.code)) as unknown as FundAiAnalysis
    if (res.ai_available && res.content) {
      await applyAi(res.content, res.sources, '')
    }
  } catch {
    /* 忽略：缓存查不到不影响主流程 */
  }
}

async function applyAi(content: string, sources: FundAiSource[], note: string) {
  const md = await ensureMd()
  aiHtml.value = md.render(content || '')
  aiSources.value = sources || []
  aiNote.value = note || ''
  aiLoaded.value = !!content
}

async function runAi(refresh: boolean) {
  if (!props.code) return
  aiLoading.value = true
  try {
    const res = (await runFundAiAnalysis(props.code, refresh)) as unknown as FundAiAnalysis
    if (res.ai_available && res.content) {
      await applyAi(res.content, res.sources, '')
      if (!refresh && res.cached) ElMessage.success('已加载缓存的 AI 解读')
    } else {
      aiNote.value = res.note || 'AI 暂不可用，已展示规则化分析。'
      ElMessage.warning(aiNote.value)
    }
  } catch (e) {
    ElMessage.error('AI 解读生成失败')
  } finally {
    aiLoading.value = false
  }
}

function onOpened() {
  // 抽屉动画结束后再 resize，避免容器尺寸为 0
  nextTick(() => {
    radarChart?.resize()
    navChart?.resize()
    pieChart?.resize()
  })
}

watch(
  () => [props.modelValue, props.code] as const,
  ([visible, code]) => {
    if (visible && code && code !== loadedCode) {
      loadData()
    }
  },
)
</script>

<style scoped>
.fdd-body {
  padding: 0 4px 24px;
}
.fdd-error {
  color: #f56c6c;
  padding: 20px 0;
  text-align: center;
}
.fdd-summary {
  background: #f7f9fc;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 14px;
}
.fdd-summary-line {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}
.fdd-style {
  font-size: 12px;
  color: #606266;
}
.fdd-summary-text {
  font-size: 13px;
  color: #303133;
  line-height: 1.6;
}
.fdd-section {
  margin-bottom: 18px;
}
.fdd-section-title {
  font-size: 14px;
  font-weight: 700;
  color: #303133;
  margin-bottom: 10px;
  border-left: 3px solid #409eff;
  padding-left: 8px;
}
.fdd-peer-count {
  font-size: 12px;
  font-weight: 400;
  color: #909399;
}
/* 入场时机卡片 */
.fdd-timing-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
}
.fdd-tier {
  font-size: 13px;
  font-weight: 700;
  border-radius: 12px;
  padding: 2px 12px;
  color: #fff;
}
.fdd-tier.tier-low {
  background: #16a34a;
}
.fdd-tier.tier-dca {
  background: #e6a23c;
}
.fdd-tier.tier-wait {
  background: #909399;
}
.fdd-tier.tier-high {
  background: #d23b3b;
}
.fdd-timing-score {
  font-size: 12px;
  color: #606266;
}
.fdd-timing-score b {
  font-size: 15px;
  color: #303133;
}
.fdd-timing-stale {
  font-size: 12px;
  color: #e6a23c;
}
.fdd-timing-flag {
  font-size: 11px;
  color: #909399;
  background: #f4f4f5;
  border: 1px solid #e9e9eb;
  border-radius: 10px;
  padding: 1px 8px;
}
.fdd-timing-quality {
  font-size: 11px;
  color: #16a34a;
  background: #f0f9eb;
  border: 1px solid #c2e7b0;
  border-radius: 10px;
  padding: 1px 8px;
}
.fdd-timing-bars {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 8px;
}
.fdd-timing-bar-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.fdd-timing-bar-label {
  flex: 0 0 60px;
  font-size: 12px;
  color: #606266;
}
.fdd-timing-track {
  flex: 1 1 auto;
  height: 8px;
  background: #f0f2f5;
  border-radius: 4px;
  overflow: hidden;
}
.fdd-timing-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.3s ease;
}
.fdd-timing-bar-val {
  flex: 0 0 30px;
  text-align: right;
  font-size: 12px;
  font-weight: 600;
  color: #303133;
}
.fdd-timing-note {
  font-size: 11px;
  color: #909399;
  line-height: 1.6;
}
/* T6 底层持仓位置参考卡 */
.fdd-lt-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
}
.fdd-lt-list {
  display: flex;
  flex-direction: column;
  gap: 7px;
  margin-bottom: 8px;
}
.fdd-lt-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.fdd-lt-name {
  flex: 0 0 40%;
  max-width: 40%;
  font-size: 12px;
  color: #303133;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.fdd-lt-name i {
  font-style: normal;
  margin-left: 4px;
  font-size: 11px;
}
.fdd-lt-val {
  flex: 0 0 30px;
  text-align: right;
  font-size: 12px;
  font-weight: 600;
  color: #303133;
}
.fdd-lt-na {
  flex: 1 1 auto;
  text-align: right;
  font-size: 11px;
}
/* 持仓风格暴露卡 */
.fdd-style-fill {
  background: #409eff;
}
.fdd-style-drift {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin: 4px 0 8px;
}
.fdd-style-chg {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 8px;
  background: #f0f2f5;
  color: #606266;
}
.fdd-style-chg.up {
  color: #d23b3b;
  background: #fef0f0;
}
.fdd-style-chg.down {
  color: #16a34a;
  background: #f0f9eb;
}
.fdd-radar {
  width: 100%;
  height: 280px;
}
.fdd-value-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 14px;
}
.fdd-value-chip {
  font-size: 12px;
  color: #d23b3b;
  background: #fef0f0;
  border: 1px solid #fbc4c4;
  border-radius: 12px;
  padding: 2px 10px;
}
.fdd-kpi-bar {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  margin-bottom: 14px;
}
.fdd-kpi {
  background: #f7f8fa;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 8px 6px;
  text-align: center;
}
.fdd-kpi-label {
  font-size: 11px;
  color: #909399;
  margin-bottom: 3px;
}
.fdd-kpi-value {
  font-size: 15px;
  font-weight: 700;
}
.fdd-nav-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.fdd-nav-ranges {
  display: flex;
  gap: 2px;
}
.fdd-nav-range {
  font-size: 11px;
  font-weight: 400;
  color: #909399;
  padding: 2px 8px;
  border-radius: 10px;
  cursor: pointer;
}
.fdd-nav-range.active {
  color: #fff;
  background: #d23b3b;
}
.fdd-navchart {
  width: 100%;
  height: 220px;
}
.fdd-piechart {
  width: 100%;
  height: 220px;
  margin-top: 10px;
}
.fdd-holdings-h {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  margin: 12px 0 6px;
}
.fdd-holdings,
.fdd-profile {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.fdd-holdings th,
.fdd-holdings td {
  padding: 5px 6px;
  border-bottom: 1px solid #f0f2f5;
  text-align: left;
}
.fdd-holdings th {
  color: #909399;
  font-weight: 500;
}
.fdd-holdings .r {
  text-align: right;
}
.fdd-profile th {
  width: 84px;
  color: #909399;
  font-weight: 500;
  text-align: left;
  vertical-align: top;
  padding: 5px 8px 5px 0;
}
.fdd-profile td {
  color: #303133;
  padding: 5px 0;
  line-height: 1.5;
}
.fdd-dim-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}
.fdd-dim-chip {
  font-size: 12px;
  color: #606266;
  background: #f0f2f5;
  border-radius: 12px;
  padding: 2px 10px;
}
.fdd-dim-chip b {
  color: #d23b3b;
}
.fdd-card {
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 10px;
}
.fdd-card-h {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 8px;
  color: #303133;
}
.fdd-list {
  margin: 0;
  padding-left: 18px;
}
.fdd-list li {
  font-size: 13px;
  color: #303133;
  line-height: 1.8;
}
.fdd-kv {
  font-size: 13px;
  color: #303133;
  line-height: 1.7;
}
.fdd-muted {
  color: #909399;
}
.fdd-ind-bars {
  margin-top: 8px;
}
.fdd-ind-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}
.fdd-ind-name {
  width: 84px;
  font-size: 12px;
  color: #606266;
  flex-shrink: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.fdd-ind-track {
  flex: 1;
  height: 10px;
  background: #f0f2f5;
  border-radius: 5px;
  overflow: hidden;
}
.fdd-ind-fill {
  height: 100%;
  background: linear-gradient(90deg, #409eff, #66b1ff);
  border-radius: 5px;
}
.fdd-ind-val {
  width: 48px;
  text-align: right;
  font-size: 12px;
  color: #303133;
}
.fdd-ai-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-left: 3px solid #67c23a;
}
.fdd-ai-note {
  font-size: 12px;
  color: #e6a23c;
  margin-bottom: 8px;
}
.fdd-ai-content {
  font-size: 13px;
  line-height: 1.75;
  color: #303133;
}
.fdd-ai-content :deep(h1),
.fdd-ai-content :deep(h2),
.fdd-ai-content :deep(h3) {
  font-size: 14px;
  margin: 12px 0 6px;
}
.fdd-ai-content :deep(a) {
  color: #409eff;
}
.fdd-sources {
  margin-top: 10px;
  border-top: 1px dashed #ebeef5;
  padding-top: 8px;
}
.fdd-sources-h {
  font-size: 12px;
  color: #909399;
  margin-bottom: 4px;
}
.fdd-source-link {
  display: block;
  font-size: 12px;
  color: #409eff;
  margin-bottom: 3px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.fdd-empty {
  font-size: 13px;
  color: #909399;
  padding: 12px 0;
  text-align: center;
}
.fdd-disclaimer {
  margin-top: 16px;
  font-size: 11px;
  color: #b88230;
  background: #fdf6ec;
  border: 1px solid #faecd8;
  border-radius: 6px;
  padding: 8px 10px;
  line-height: 1.6;
}

/* ─── 移动端适配 ─── */
@media (max-width: 767.98px) {
  .fdd-body {
    padding: 0 2px 20px;
  }
  .fdd-nav-title {
    flex-wrap: wrap;
    gap: 6px;
  }
  .fdd-nav-ranges {
    flex-wrap: wrap;
  }
  .fdd-kpi-bar {
    grid-template-columns: repeat(2, 1fr);
  }
  .fdd-holdings {
    display: block;
    overflow-x: auto;
    white-space: nowrap;
  }
}
</style>
