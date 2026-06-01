<template>
  <el-drawer
    v-model="show"
    :title="drawerTitle"
    direction="rtl"
    size="560px"
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
          </div>

          <div class="fdd-card">
            <div class="fdd-card-h">🏢 规模与成立</div>
            <ul class="fdd-list">
              <li v-for="(t, i) in composite.scale.texts" :key="i">{{ t }}</li>
              <li v-if="!composite.scale.texts.length" class="fdd-muted">暂无规模信息</li>
            </ul>
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
import {
  getFundPeerCompare,
  getFundCompositeAnalysis,
  getFundAiAnalysis,
  runFundAiAnalysis,
  type FundPeerCompare,
  type FundComposite,
  type FundAiSource,
  type FundAiAnalysis,
} from '@/api/fund'

const props = defineProps<{
  modelValue: boolean
  code: string
  name?: string
}>()
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void }>()

const show = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const loading = ref(false)
const loadError = ref('')
const peer = ref<FundPeerCompare | null>(null)
const composite = ref<FundComposite | null>(null)

const aiLoading = ref(false)
const aiLoaded = ref(false)
const aiHtml = ref('')
const aiNote = ref('')
const aiSources = ref<FundAiSource[]>([])

const radarRef = ref<HTMLElement | null>(null)
let radarChart: echarts.ECharts | null = null
let mdInstance: { render: (src: string) => string } | null = null
let loadedCode = ''

const drawerTitle = computed(() => {
  const n = props.name || peer.value?.name || composite.value?.name || ''
  return n ? `${n}（${props.code}）` : props.code
})

const hasRadar = computed(() => !!(peer.value && peer.value.dims && peer.value.dims.length))

const topIndustries = computed(() => {
  const dist = composite.value?.industry?.distribution || []
  return dist.slice(0, 5)
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

async function loadData() {
  if (!props.code) return
  loading.value = true
  loadError.value = ''
  peer.value = null
  composite.value = null
  aiLoaded.value = false
  aiHtml.value = ''
  aiNote.value = ''
  aiSources.value = []
  try {
    const [peerRes, compRes] = await Promise.allSettled([
      getFundPeerCompare(props.code) as unknown as Promise<FundPeerCompare>,
      getFundCompositeAnalysis(props.code) as unknown as Promise<FundComposite>,
    ])
    if (peerRes.status === 'fulfilled') peer.value = peerRes.value
    if (compRes.status === 'fulfilled') composite.value = compRes.value
    if (peerRes.status === 'rejected' && compRes.status === 'rejected') {
      loadError.value = '加载基金分析数据失败'
    }
    loadedCode = props.code
    await renderRadar()
    // 静默查缓存：若已有 AI 结果则直接展示
    void prefetchAi()
  } catch (e) {
    loadError.value = '加载基金分析数据失败'
  } finally {
    loading.value = false
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
  nextTick(() => radarChart?.resize())
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
.fdd-radar {
  width: 100%;
  height: 280px;
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
</style>
