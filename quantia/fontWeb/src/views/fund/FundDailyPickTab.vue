<template>
  <div class="pick-tab" v-loading="loading">
    <!-- 说明条 -->
    <div class="pick-intro">
      <div class="pick-intro-head">
        <div class="pick-intro-main">
          每类基金综合质量 Top10 精选<span v-if="data?.date" class="pick-date">· 运行日 {{ data.date }}</span>
          <span v-if="data?.score_as_of" class="pick-asof">· 质量截面 {{ data.score_as_of }}</span>
        </div>
        <button
          v-if="buckets.length"
          class="pick-push-btn"
          type="button"
          @click="openPushPreview"
        >🔔 钉钉推送预览</button>
      </div>
      <div class="pick-intro-note">
        “每日精选”= 同类中质量较优，并给出当前入场/定投节奏提示，<b>非“立即买入”建议</b>。择时为弱标签，不参与排序。
      </div>
    </div>

    <!-- 数据健康三防线（蓝图 §9，全部基于真实库计数） -->
    <div v-if="data?.data_health" class="pick-health">
      <div class="dh-card" :class="timelinessCls">
        <div class="dh-title">🕒 净值披露及时性 <span class="dh-tag">防线1</span></div>
        <div class="dh-value" :style="{ color: timelinessColor }">{{ timelinessValue }}</div>
        <div class="dh-desc">{{ timelinessDesc }}</div>
      </div>
      <div class="dh-card" :class="holdingsCls">
        <div class="dh-title">🏭 持仓行业可用性 <span class="dh-tag">防线2</span></div>
        <div class="dh-value" :style="{ color: holdingsColor }">{{ holdingsValue }}</div>
        <div class="dh-desc">{{ holdingsDesc }}</div>
      </div>
      <div class="dh-card" :class="coverageCls">
        <div class="dh-title">✅ 质量评分覆盖 <span class="dh-tag dh-tag--fresh">主排序</span></div>
        <div class="dh-value" :style="{ color: coverageColor }">{{ coverageValue }}</div>
        <div class="dh-desc">{{ coverageDesc }}</div>
      </div>
    </div>

    <div v-if="!buckets.length && !loading" class="pick-empty">
      暂无精选榜数据（待 analysis 精选作业落库）。
    </div>

    <template v-else>
      <!-- 桶标题条（对齐原型 bucket-head） -->
      <div v-if="activeBucket" class="pick-bucket-head">
        <span class="pbh-name">{{ activeBucket.fund_type }}</span>
        <span class="pbh-sub">每类综合精选 Top10</span>
        <span class="pbh-mode">{{
          activeBucket.timing_applicable
            ? '口径 V1：质量主排序 + 择时标签'
            : '收益型：只展示收益/规模稳定性（不做点位择时）'
        }}</span>
      </div>

      <div v-if="activeBucket" class="pick-list">
        <!-- 表头（桌面） -->
        <div v-if="!isMobile" class="pick-head">
          <span class="ph-rank">#</span>
          <span class="ph-name">基金</span>
          <span class="ph-nav" v-if="activeBucket.timing_applicable">净值</span>
          <span class="ph-quality">质量分</span>
          <span class="ph-timing" v-if="activeBucket.has_timing">入场档位</span>
          <template v-if="activeBucket.timing_applicable">
            <span class="ph-metric">近1年</span>
            <span class="ph-metric">目前回撤</span>
            <span class="ph-style">风格</span>
          </template>
          <span v-else class="ph-metric">七日年化</span>
        </div>

        <div
          v-for="p in activeBucket.picks"
          :key="p.code"
          class="pick-row"
          :class="{ 'pick-row--top': (p.rank_in_type || 99) <= 3 }"
          @click="emit('open', { code: p.code, name: p.name || p.code })"
        >
          <span class="pr-rank">{{ medal(p.rank_in_type) }}</span>
          <div class="pr-name-wrap">
            <span class="pr-name">{{ p.name || p.code }}</span>
            <span class="pr-code">{{ p.code }}</span>
            <span v-if="reasonOf(p, activeBucket)" class="pr-reason">{{ reasonOf(p, activeBucket) }}</span>
          </div>
          <div v-if="activeBucket.timing_applicable" class="pr-nav">
            <b>{{ fmtNav(p.unit_nav) }}</b>
            <span v-if="p.acc_nav != null" class="pr-nav-acc">累计 {{ fmtNav(p.acc_nav) }}</span>
            <span v-else class="pr-nav-acc pr-nav-acc--na">缺累计</span>
          </div>
          <div class="pr-quality">
            <div class="pr-bar-track">
              <div class="pr-bar" :style="scoreBarStyle(p.quality_score)"></div>
            </div>
            <span class="pr-score">{{ fmtNum(p.quality_score, 1) }}</span>
          </div>
          <div class="pr-timing" v-if="activeBucket.has_timing">
            <span
              v-if="p.timing_tier"
              class="tier-badge"
              :class="tierClass(p.timing_tier)"
            >{{ p.timing_tier
              }}<span v-if="p.timing_score != null" class="tier-score">{{ tierScore(p.timing_score) }}</span></span>
            <span v-else class="tier-badge tier-na">暂无</span>
            <span
              v-if="lagTagText(p.data_lag_days)"
              class="pr-lagtag"
              :class="{ 'pr-lagtag--warn': lagWarn(p.data_lag_days) }"
              :title="p.nav_as_of ? `净值披露日 ${p.nav_as_of}` : ''"
            >{{ lagTagText(p.data_lag_days) }}</span>
          </div>
          <template v-if="activeBucket.timing_applicable">
            <div class="pr-metric pr-metric--r1y" :style="returnStyle(p.rate_1y)">
              {{ fmtPct(p.rate_1y) }}
            </div>
            <div
              class="pr-metric pr-metric--dd"
              :style="drawdownStyle(p.current_drawdown)"
              :title="p.max_drawdown != null ? `历史最大回撤 ${fmtDrawdown(p.max_drawdown)}` : ''"
            >
              {{ fmtDrawdown(p.current_drawdown) }}
            </div>
            <div
              v-if="p.main_industry"
              class="pr-style"
              :title="`持仓加权主行业（前十大重仓股）`"
            >{{ p.main_industry }}</div>
            <div v-else class="pr-style pr-style--na" title="非权益/无持仓数据，行业如实留白">—</div>
          </template>
          <div v-else class="pr-metric pr-metric--y7">
            {{ fmtY7(p.seven_day_annual) }}
          </div>
        </div>

        <div v-if="!activeBucket.timing_applicable" class="pick-money-note">
          货币型以七日年化/规模为主，不做点位择时，故无入场档位。
        </div>
        <div v-else-if="!activeBucket.has_timing" class="pick-money-note">
          该类暂无净值历史（未回填），入场提示暂缺；质量分与收益仍可参考。
        </div>
      </div>
      <div v-else class="pick-empty">
        当前基金类型暂无精选榜数据。
      </div>
    </template>

    <div class="pick-disclaimer" v-if="data?.disclaimer">⚠️ {{ data.disclaimer }}</div>

    <!-- 钉钉推送预览（复刻 notify_fund_pick_job.build_fund_pick_markdown 口径：每桶 Top3） -->
    <div v-if="pushVisible" class="dt-mask" @click.self="closePushPreview">
      <div class="dt-modal">
        <div class="dt-top">💬 钉钉群 · 每日基金精选推送预览</div>
        <div class="dt-body">
          <div class="dt-bubble" v-html="pushHtml"></div>
        </div>
        <div class="dt-foot">
          <span class="dt-note">仅为文案预览，实际推送由 P6 清晨作业按配置触发（未启用则不发送）。</span>
          <button type="button" @click="closePushPreview">关闭</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import {
  getFundDailyPick,
  type FundDailyPick,
  type FundDailyPickBucket,
  type FundDailyPickItem,
} from '@/api/fund'
import { useResponsive } from '@/composables/useResponsive'

const emit = defineEmits<{ (e: 'open', v: { code: string; name: string }): void }>()
const props = defineProps<{ fundType: string }>()

const { isMobile } = useResponsive()
const data = ref<FundDailyPick | null>(null)
const loading = ref(false)

const buckets = computed<FundDailyPickBucket[]>(() => data.value?.buckets || [])
const activeBucket = computed<FundDailyPickBucket | null>(
  () => buckets.value.find((b) => b.fund_type === props.fundType) || null,
)

function medal(rank: number | null): string {
  if (rank === 1) return '🥇'
  if (rank === 2) return '🥈'
  if (rank === 3) return '🥉'
  return String(rank ?? '')
}

// 净值披露滞后：QDII 必须展示（蓝图 §7.1bis）；其余档仅在滞后≥5 自然日时提示（§7.2bis）。
function lagWarn(lag: number | null | undefined): boolean {
  return lag !== null && lag !== undefined && lag >= 5
}

// 净值时效 tag（对齐原型 lagTag）：≤2 天 净值T-N；3~5 天 滞后N天；>5 天 ⚠滞后N天
function lagTagText(lag: number | null | undefined): string {
  if (lag === null || lag === undefined) return ''
  if (lag <= 2) return `净值T-${lag}`
  if (lag <= 5) return `滞后${lag}天`
  return `⚠滞后${lag}天`
}

// 净值/累计净值：去除多余尾零（原型显示 2.7 / 累计 3.768）
function fmtNav(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return parseFloat(v.toFixed(4)).toString()
}

// 入选理由（简化版，仅用真实返回字段：质量分/择时/近1年/回撤/净值滞后）
function reasonOf(p: FundDailyPickItem, bucket: FundDailyPickBucket): string {
  if (!bucket.timing_applicable) {
    if (p.seven_day_annual != null) return '七日年化居同类前列'
    return '同类质量分居前'
  }
  const q = p.quality_score
  if (q != null && q >= 88) return '同类质量分前列'
  if (p.current_drawdown != null && p.current_drawdown <= -0.25) return '距高点回撤较深'
  if (p.timing_score != null && p.timing_score >= 75) return '当前处历史相对低位'
  if (p.timing_score != null && p.timing_score >= 50) return '位置中性适合定投'
  if (p.data_lag_days != null && p.data_lag_days > 7) return '净值披露滞后、暂不评位'
  if (p.main_industry) return `主配${p.main_industry}`
  if (q != null && q >= 82) return '同类质量分居前'
  return ''
}

function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return `${v > 0 ? '+' : ''}${v.toFixed(2)}%`
}

function fmtNum(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return v.toFixed(digits)
}

function fmtDrawdown(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return `${(v * 100).toFixed(2)}%`
}

// 七日年化（货币型）：cn_fund_rank.seven_day_annual，已是百分数值
function fmtY7(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return `${v.toFixed(2)}%`
}

// 择时分数（对齐原型「低吸 78」）
function tierScore(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return ''
  return ` ${Math.round(v)}`
}

function scoreColor(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '#909399'
  if (v >= 75) return '#16a34a'
  if (v >= 50) return '#e6a23c'
  return '#d23b3b'
}

function scoreBarStyle(v: number | null | undefined): Record<string, string> {
  const n = v === null || v === undefined || Number.isNaN(v) ? 0 : Math.max(0, Math.min(100, v))
  return { width: `${n}%`, background: scoreColor(v) }
}

function returnStyle(v: number | null | undefined): Record<string, string> {
  if (v === null || v === undefined || Number.isNaN(v) || v === 0) return {}
  return { color: v > 0 ? '#d23b3b' : '#16a34a', fontWeight: '600' }
}

function drawdownStyle(v: number | null | undefined): Record<string, string> {
  if (v === null || v === undefined || Number.isNaN(v)) return {}
  if (v <= -0.3) return { color: '#d23b3b', fontWeight: '600' }
  if (v >= -0.1) return { color: '#16a34a', fontWeight: '600' }
  return {}
}

// 低吸(强)>定投>观望>高估勿追(弱)，色语义对齐原型 tierOf()
function tierClass(tier: string | null): string {
  if (tier === '低吸') return 'tier-low'
  if (tier === '定投') return 'tier-dca'
  if (tier === '观望') return 'tier-wait'
  if (tier === '高估勿追' || tier === '高估') return 'tier-high'
  return ''
}

// ── 数据健康三防线（真实库计数） ──
const timelinessValue = computed(() => {
  const t = data.value?.data_health?.timeliness
  if (!t) return '—'
  return `${t.fresh.toLocaleString()} / ${t.total.toLocaleString()}`
})
const timelinessDesc = computed(() => {
  const t = data.value?.data_health?.timeliness
  if (!t || t.pct == null) return '净值 5 日内更新占比（滞后 > 7 日者不产出择时档位）'
  return `仅 ${t.pct}% 基金净值在 5 日内更新；滞后 > 7 日者不产出择时档位`
})
const timelinessColor = computed(() => {
  const pct = data.value?.data_health?.timeliness?.pct
  if (pct == null) return '#909399'
  return pct >= 60 ? '#16a34a' : '#e6a23c'
})
const timelinessCls = computed(() => {
  const pct = data.value?.data_health?.timeliness?.pct
  if (pct == null) return 'dh-card--muted'
  return pct >= 60 ? 'dh-card--ok' : 'dh-card--warn'
})
const coverageValue = computed(() =>
  data.value?.data_health?.quality_coverage?.status === 'full' ? '当日全量' : '部分覆盖',
)
const coverageColor = computed(() =>
  data.value?.data_health?.quality_coverage?.status === 'full' ? '#16a34a' : '#e6a23c',
)
const coverageCls = computed(() =>
  data.value?.data_health?.quality_coverage?.status === 'full' ? 'dh-card--ok' : 'dh-card--warn',
)
const coverageDesc = computed(() => {
  const asof = data.value?.data_health?.quality_coverage?.score_as_of
  return asof
    ? `cn_fund_rank_score ${asof} 已就绪，V1 以质量分主排序`
    : '质量评分截面待就绪'
})

// 防线2：持仓行业覆盖（cn_fund_rank_score.main_industry 真实计数）
const holdingsValue = computed(() => {
  const h = data.value?.data_health?.holdings
  if (!h || !h.available || h.covered == null || h.total == null) return '暂无持仓数据'
  return `${h.covered.toLocaleString()} / ${h.total.toLocaleString()}`
})
const holdingsDesc = computed(() => {
  const h = data.value?.data_health?.holdings
  if (!h || !h.available || h.pct == null) {
    return '仅权益/指数类有前十大重仓；债券/货币/QDII/FOF 无持仓，风格列如实留白'
  }
  return `仅 ${h.pct}% 基金有持仓加权主行业（前十大重仓股）；无持仓者风格列留白，不做硬拦截`
})
const holdingsColor = computed(() => {
  const pct = data.value?.data_health?.holdings?.pct
  if (pct == null) return '#909399'
  return pct >= 30 ? '#e6a23c' : '#909399'
})
const holdingsCls = computed(() => {
  const h = data.value?.data_health?.holdings
  if (!h || !h.available) return 'dh-card--muted'
  return 'dh-card--warn'
})

// ── 钉钉推送预览（复刻 build_fund_pick_markdown 口径：每桶 Top3 + emoji 档位） ──
const pushVisible = ref(false)
const TIER_EMOJI: Record<string, string> = {
  低吸: '🟢',
  定投: '🟠',
  观望: '⚪',
  高估勿追: '🔴',
  高估: '🔴',
}
function fundDetailUrl(code: string, name?: string): string {
  // 镜像 notify_fund_pick_job._fund_detail_url：{base}/#/fund/rank?code=XXX&name=YYY。
  // 预览场景用当前站点 origin（点击即在本应用打开基金抽屉）。
  const base = window.location.origin
  let u = `${base}/fund/rank?code=${encodeURIComponent(code)}`
  if (name) u += `&name=${encodeURIComponent(name)}`
  return u
}
function pickListUrl(): string {
  return `${window.location.origin}/fund/rank?pick=1`
}
function pushMeta(p: FundDailyPickItem, timingApplicable: boolean): string {
  const parts: string[] = []
  if (p.quality_score != null) parts.push(`质量${Math.round(p.quality_score)}`)
  if (timingApplicable) {
    if (p.timing_tier) {
      const emoji = TIER_EMOJI[p.timing_tier] || ''
      parts.push(p.timing_score != null ? `${emoji}${p.timing_tier}${Math.round(p.timing_score)}` : `${emoji}${p.timing_tier}`)
    } else {
      parts.push('择时暂无')
    }
    if (p.data_lag_days != null && p.data_lag_days >= 5) parts.push(`净值滞后${p.data_lag_days}天`)
  } else if (p.seven_day_annual != null) {
    parts.push(`七日年化${p.seven_day_annual.toFixed(2)}%`)
  } else if (p.rate_1y != null) {
    parts.push(`近1年${p.rate_1y.toFixed(2)}%`)
  }
  return parts.length ? ' · ' + parts.join(' · ') : ''
}
const pushHtml = computed(() => {
  const d = data.value
  if (!d) return ''
  const rows: string[] = [`<b>📈 每日基金精选榜 ${d.date || ''}</b>`, '']
  for (const b of d.buckets) {
    const top3 = b.picks.slice(0, 3)
    if (!top3.length) continue
    rows.push(`<b>${b.fund_type}</b> · Top${top3.length}`)
    for (const p of top3) {
      const label = escapeHtml(`${p.code} ${p.name || p.code}`)
      const url = escapeHtml(fundDetailUrl(p.code, p.name || p.code))
      const meta = escapeHtml(pushMeta(p, b.timing_applicable))
      rows.push(`· <a class="dt-fund-link" href="${url}" target="_blank" rel="noopener">${label}</a>${meta}`)
    }
    rows.push('')
  }
  rows.push(`<a class="dt-fund-link" href="${escapeHtml(pickListUrl())}" target="_blank" rel="noopener">📋 查看完整每类 Top10 榜单</a>`)
  rows.push('———')
  if (d.disclaimer) rows.push(`<span class="dt-quote">${escapeHtml(d.disclaimer)}</span>`)
  return rows.join('<br>')
})
function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}
function openPushPreview() {
  pushVisible.value = true
}
function closePushPreview() {
  pushVisible.value = false
}

async function load() {
  loading.value = true
  try {
    const res = (await getFundDailyPick()) as unknown as FundDailyPick
    data.value = res
  } catch {
    ElMessage.error('加载每日精选榜失败')
    data.value = null
  } finally {
    loading.value = false
  }
}

onMounted(load)
defineExpose({ reload: load })
</script>

<style scoped>
.pick-tab {
  min-height: 200px;
}
.pick-intro {
  margin-bottom: 12px;
}
.pick-intro-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.pick-push-btn {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  background: linear-gradient(135deg, #1f6feb, #388bfd);
  color: #fff;
  border: none;
  border-radius: 20px;
  padding: 7px 15px;
  font-size: 13px;
  font-weight: 600;
  box-shadow: 0 2px 8px rgba(31, 111, 235, 0.3);
  transition: transform 0.15s;
}
.pick-push-btn:hover {
  transform: translateY(-1px);
}
.pick-intro-main {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
}
.pick-date,
.pick-asof {
  font-size: 12px;
  font-weight: 400;
  color: #909399;
  margin-left: 4px;
}
.pick-intro-note {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}

/* 数据健康三防线卡 */
.pick-health {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
  margin-bottom: 14px;
}
.dh-card {
  background: #fff;
  border-radius: 10px;
  padding: 12px 14px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
  border-left: 4px solid #c0c4cc;
}
.dh-card--ok {
  border-left-color: #16a34a;
}
.dh-card--warn {
  border-left-color: #e6a23c;
}
.dh-card--muted {
  border-left-color: #c0c4cc;
}
.dh-title {
  font-size: 12.5px;
  color: #606266;
  display: flex;
  align-items: center;
  gap: 6px;
}
.dh-tag {
  font-size: 11px;
  padding: 0 6px;
  border-radius: 8px;
  background: #eef1f5;
  color: #909399;
}
.dh-tag--fresh {
  background: #e7f7ee;
  color: #16a34a;
}
.dh-value {
  font-size: 20px;
  font-weight: 700;
  margin-top: 4px;
}
.dh-desc {
  font-size: 11.5px;
  color: #909399;
  margin-top: 2px;
}
.pick-empty {
  padding: 40px 0;
  text-align: center;
  color: #909399;
}
.pick-bucket-head {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 8px;
  padding: 2px 2px 8px;
  border-bottom: 1px solid #ebeef5;
  margin-bottom: 2px;
}
.pbh-name {
  font-size: 15px;
  font-weight: 700;
  color: #303133;
}
.pbh-sub {
  font-size: 12px;
  color: #909399;
}
.pbh-mode {
  margin-left: auto;
  font-size: 12px;
  color: #909399;
  background: #f4f6f9;
  border-radius: 10px;
  padding: 2px 10px;
}
.pick-head {
  display: flex;
  align-items: center;
  padding: 6px 10px;
  font-size: 12px;
  color: #909399;
  border-bottom: 1px solid #ebeef5;
}
.ph-rank {
  width: 40px;
  text-align: center;
}
.ph-name {
  flex: 1;
  min-width: 0;
}
.ph-nav {
  width: 82px;
}
.ph-quality {
  width: 130px;
}
.ph-timing {
  width: 132px;
  text-align: left;
}
.ph-metric {
  width: 78px;
  text-align: right;
}
.ph-style {
  width: 72px;
  text-align: left;
  padding-left: 10px;
}
.pick-row {
  display: flex;
  align-items: center;
  padding: 10px;
  border-bottom: 1px solid #f5f6f8;
  cursor: pointer;
  transition: background 0.15s;
}
.pick-row:hover {
  background: #f5f9ff;
}
.pick-row--top {
  background: #fffdf5;
}
.pick-row--top:hover {
  background: #fef8e8;
}
.pr-rank {
  width: 40px;
  text-align: center;
  font-size: 15px;
  font-weight: 600;
  color: #606266;
  flex-shrink: 0;
}
.pr-name-wrap {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.pr-name {
  font-size: 14px;
  color: #303133;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.pr-code {
  font-size: 12px;
  color: #909399;
}
.pr-reason {
  font-size: 11px;
  color: #409eff;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.pr-nav {
  width: 82px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
  font-size: 13.5px;
  color: #303133;
}
.pr-nav-acc {
  font-size: 11px;
  color: #909399;
}
.pr-nav-acc--na {
  color: #e6a23c;
}
.pr-quality {
  width: 130px;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.pr-bar-track {
  flex: 1;
  height: 8px;
  border-radius: 4px;
  background: #eef0f3;
  overflow: hidden;
}
.pr-bar {
  height: 100%;
  border-radius: 4px;
}
.pr-score {
  width: 34px;
  text-align: right;
  font-size: 13px;
  font-weight: 600;
  color: #303133;
}
.pr-timing {
  width: 132px;
  text-align: left;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
}
.pr-lagtag {
  padding: 0 5px;
  border-radius: 3px;
  font-size: 11px;
  line-height: 16px;
  color: #16a34a;
  background: #e7f7ee;
  white-space: nowrap;
}
.pr-lagtag--warn {
  color: #b8860b;
  background: #fdf6e3;
}
.tier-badge {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 12px;
  font-weight: 600;
}
.tier-score {
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}
.tier-low {
  background: #e7f7ee;
  color: #16a34a;
  border: 1px solid #b7e4c7;
}
.tier-dca {
  background: #fdf3e2;
  color: #e6a23c;
  border: 1px solid #f5d9a8;
}
.tier-wait {
  background: #eef1f5;
  color: #606266;
  border: 1px solid #dfe4ea;
}
.tier-high {
  background: #fdeaea;
  color: #d23b3b;
  border: 1px solid #f3c2c2;
}
.tier-na {
  background: #f4f4f5;
  color: #a8abb2;
  border: 1px dashed #d3d4d6;
}
.pr-metric {
  width: 78px;
  text-align: right;
  font-size: 13px;
  color: #606266;
  flex-shrink: 0;
}
.pr-style {
  width: 72px;
  flex-shrink: 0;
  padding-left: 10px;
  font-size: 12.5px;
  color: #606266;
}
.pr-style--na {
  color: #c0c4cc;
}
.pick-money-note {
  padding: 10px;
  font-size: 12px;
  color: #909399;
}
.pick-disclaimer {
  margin-top: 12px;
  font-size: 12px;
  color: #c0524b;
  background: #fef6f6;
  border-radius: 6px;
  padding: 8px 10px;
}

/* 钉钉推送预览弹窗 */
.dt-mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2200;
  padding: 16px;
}
.dt-modal {
  width: 420px;
  max-width: 100%;
  background: #f2f3f5;
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.2);
}
.dt-top {
  background: #0089ff;
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  padding: 10px 14px;
}
.dt-body {
  padding: 16px;
  max-height: 60vh;
  overflow-y: auto;
}
.dt-bubble {
  background: #fff;
  border-radius: 8px;
  padding: 12px 14px;
  font-size: 13px;
  line-height: 1.7;
  color: #303133;
  word-break: break-word;
}
.dt-bubble :deep(.dt-quote) {
  color: #909399;
  font-size: 12px;
}
.dt-bubble :deep(.dt-fund-link) {
  color: #2979ff;
  text-decoration: none;
}
.dt-bubble :deep(.dt-fund-link:hover) {
  text-decoration: underline;
}
.dt-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 14px;
  background: #fff;
  border-top: 1px solid #ebeef5;
}
.dt-note {
  font-size: 11px;
  color: #909399;
}
.dt-foot button {
  flex-shrink: 0;
  border: none;
  background: #409eff;
  color: #fff;
  border-radius: 6px;
  padding: 6px 16px;
  font-size: 13px;
  cursor: pointer;
}

/* ── 移动端：横向指标改为卡片内网格 ── */
@media (max-width: 767.98px) {
  .pick-intro-head {
    flex-wrap: wrap;
  }
  .pick-health {
    grid-template-columns: 1fr;
  }
  .pick-head {
    display: none;
  }
  .pick-row {
    flex-wrap: wrap;
    row-gap: 8px;
    padding: 12px 10px;
  }
  .pr-rank {
    width: 32px;
    font-size: 14px;
  }
  .pr-name-wrap {
    flex: 1 1 auto;
  }
  .pr-nav {
    width: auto;
    order: 2;
    flex-direction: row;
    align-items: baseline;
    gap: 6px;
    margin-left: auto;
  }
  .pr-quality {
    width: 100%;
    order: 4;
  }
  .pr-timing {
    width: 100%;
    order: 3;
  }
  .pr-metric {
    order: 5;
    width: 50%;
    text-align: left;
  }
  .pr-metric::before {
    color: #909399;
    font-size: 11px;
    margin-right: 4px;
  }
  .pr-metric--dd::before {
    content: '回撤 ';
  }
  .pr-metric--r1y::before {
    content: '近1年 ';
  }
  .pr-metric--y7::before {
    content: '七日年化 ';
  }
  .pr-style {
    display: none;
  }
  .pick-bucket-head {
    gap: 6px;
  }
  .pbh-mode {
    margin-left: 0;
    flex-basis: 100%;
  }
}
</style>
