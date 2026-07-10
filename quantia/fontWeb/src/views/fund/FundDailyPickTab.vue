<template>
  <div class="pick-tab" v-loading="loading">
    <!-- 说明条 -->
    <div class="pick-intro">
      <div class="pick-intro-main">
        每类基金综合质量 Top10 精选<span v-if="data?.date" class="pick-date">· 运行日 {{ data.date }}</span>
        <span v-if="data?.score_as_of" class="pick-asof">· 质量截面 {{ data.score_as_of }}</span>
      </div>
      <div class="pick-intro-note">
        “每日精选”= 同类中质量较优，并给出当前入场/定投节奏提示，<b>非“立即买入”建议</b>。择时为弱标签，不参与排序。
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
          <span class="ph-quality">质量分</span>
          <span class="ph-timing" v-if="activeBucket.has_timing">入场提示</span>
          <template v-if="activeBucket.timing_applicable">
            <span class="ph-metric">最大回撤</span>
            <span class="ph-metric">近1年</span>
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
            <span class="pr-code"
              >{{ p.code
              }}<span
                v-if="showLag(p.data_lag_days)"
                class="pr-lag"
                :class="{ 'pr-lag--warn': lagWarn(p.data_lag_days) }"
                :title="p.nav_as_of ? `净值披露日 ${p.nav_as_of}` : ''"
                >净值滞后{{ p.data_lag_days }}天</span
              ></span
            >
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
          </div>
          <template v-if="activeBucket.timing_applicable">
            <div class="pr-metric pr-metric--dd" :style="drawdownStyle(p.max_drawdown)">
              {{ fmtDrawdown(p.max_drawdown) }}
            </div>
            <div class="pr-metric pr-metric--r1y" :style="returnStyle(p.rate_1y)">
              {{ fmtPct(p.rate_1y) }}
            </div>
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
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getFundDailyPick, type FundDailyPick, type FundDailyPickBucket } from '@/api/fund'
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
function showLag(lag: number | null | undefined): boolean {
  if (lag === null || lag === undefined) return false
  return activeBucket.value?.fund_type === 'QDII' || lag >= 5
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
.ph-quality {
  width: 160px;
}
.ph-timing {
  width: 72px;
  text-align: center;
}
.ph-metric {
  width: 88px;
  text-align: right;
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
.pr-lag {
  margin-left: 6px;
  padding: 0 5px;
  border-radius: 3px;
  font-size: 11px;
  line-height: 16px;
  color: #6b7785;
  background: #eef1f5;
  white-space: nowrap;
}
.pr-lag--warn {
  color: #b8860b;
  background: #fdf6e3;
}
.pr-quality {
  width: 160px;
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
  width: 72px;
  text-align: center;
  flex-shrink: 0;
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
  width: 88px;
  text-align: right;
  font-size: 13px;
  color: #606266;
  flex-shrink: 0;
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

/* ── 移动端：横向指标改为卡片内网格 ── */
@media (max-width: 767.98px) {
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
  .pr-quality {
    width: 100%;
    order: 3;
  }
  .pr-timing {
    width: auto;
    order: 2;
    margin-left: auto;
  }
  .pr-metric {
    order: 4;
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
  .pick-bucket-head {
    gap: 6px;
  }
  .pbh-mode {
    margin-left: 0;
    flex-basis: 100%;
  }
}
</style>
