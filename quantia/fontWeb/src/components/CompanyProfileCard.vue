<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { getStockProfile, getStockBusiness, type StockProfileData, type StockBusinessData, type MainOpItem } from '@/api/stock'

const props = defineProps<{ code: string; name?: string }>()
const emit = defineEmits<{ (e: 'loaded', hasData: boolean): void }>()

const data = ref<StockProfileData | null>(null)
const business = ref<StockBusinessData | null>(null)
const reason = ref('')
const loading = ref(false)

// 展开/收起长概念、板块标签
const conceptExpanded = ref(false)
const styleExpanded = ref(false)
const scopeExpanded = ref(false)
const reviewExpanded = ref(false)
const TAG_LIMIT = 8
const LONGTEXT_THRESHOLD = 120

const conceptTags = computed(() => data.value?.concept || [])
const styleTags = computed(() => data.value?.style || [])
const conceptShown = computed(() =>
  conceptExpanded.value ? conceptTags.value : conceptTags.value.slice(0, TAG_LIMIT))
const styleShown = computed(() =>
  styleExpanded.value ? styleTags.value : styleTags.value.slice(0, TAG_LIMIT))

/** 元 → 亿元 / 万元，自动选单位，保留 2 位。 */
const fmtMoney = (v: number | null | undefined): string => {
  if (v == null || !isFinite(v as number)) return '-'
  const n = Number(v)
  const abs = Math.abs(n)
  if (abs >= 1e8) return (n / 1e8).toFixed(2) + ' 亿'
  if (abs >= 1e4) return (n / 1e4).toFixed(2) + ' 万'
  return n.toFixed(0)
}
const fmtPct = (v: number | null | undefined): string => {
  if (v == null || !isFinite(v as number)) return '-'
  return Number(v).toFixed(2) + '%'
}
const fmtNum = (v: number | null | undefined, digits = 2): string => {
  if (v == null || !isFinite(v as number)) return '-'
  return Number(v).toFixed(digits)
}
const fmtDate = (v: string | null | undefined): string => {
  if (!v) return '-'
  // 后端返回 ISO 或时间戳字符串，截取日期部分
  const s = String(v)
  return s.length >= 10 ? s.slice(0, 10) : s
}

// 涨跌色（A 股习惯：涨红跌绿）：增长率≥0 用红，<0 用绿。
const growthColor = (v: number | null | undefined): string => {
  if (v == null || !isFinite(v as number)) return '#303133'
  return Number(v) >= 0 ? '#f56c6c' : '#67c23a'
}

// 比例（0~1）→ 百分比字符串
const fmtRatio = (v: number | null | undefined): string => {
  if (v == null || !isFinite(v as number)) return '-'
  return (Number(v) * 100).toFixed(2) + '%'
}
// 主营收入占比 → 进度条宽度（clamp 到 0~100%）
const barWidth = (v: number | null | undefined): string => {
  if (v == null || !isFinite(v as number)) return '0%'
  const pct = Math.max(0, Math.min(100, Number(v) * 100))
  return pct.toFixed(1) + '%'
}

// 主营构成按维度（行业/产品/地区/其他）分组，组内保持后端排序（rank 升序）
const mainopGroups = computed(() => {
  const list = business.value?.mainop || []
  if (!list.length) return [] as { type: string; items: MainOpItem[]; reportDate: string | null }[]
  const order = ['行业', '产品', '地区', '其他']
  const map = new Map<string, MainOpItem[]>()
  for (const it of list) {
    const key = it.type || '其他'
    if (!map.has(key)) map.set(key, [])
    map.get(key)!.push(it)
  }
  const idx = (t: string) => { const i = order.indexOf(t); return i < 0 ? order.length : i }
  return Array.from(map.entries())
    .sort((a, b) => idx(a[0]) - idx(b[0]))
    .map(([type, items]) => ({ type, items, reportDate: items[0]?.report_date ?? null }))
})

const scopeLong = computed(() => (business.value?.business_scope?.length || 0) > LONGTEXT_THRESHOLD)
const reviewLong = computed(() => (business.value?.business_review?.length || 0) > LONGTEXT_THRESHOLD)


const metrics = computed(() => {
  const d = data.value
  if (!d) return []
  return [
    { label: '营收总额', value: fmtMoney(d.total_operate_income), highlight: true },
    { label: '归属净利润', value: fmtMoney(d.parent_netprofit) },
    { label: '总市值', value: fmtMoney(d.total_market_cap) },
    { label: '流通市值', value: fmtMoney(d.free_cap) },
    { label: '市盈率(TTM)', value: fmtNum(d.pe9) },
    { label: '市净率(MRQ)', value: fmtNum(d.pbnewmrq) },
    { label: 'ROE', value: fmtPct(d.roe_weight) },
    { label: '毛利率', value: fmtPct(d.sale_gpr) },
    { label: '净利率', value: fmtPct(d.sale_npr) },
    {
      label: '净利润增长',
      value: fmtPct(d.netprofit_yoy_ratio),
      color: growthColor(d.netprofit_yoy_ratio),
    },
    { label: '股息率', value: fmtPct(d.zxgxl) },
    { label: '上市日期', value: fmtDate(d.listing_date) },
  ]
})

const load = async () => {
  if (!props.code) return
  loading.value = true
  data.value = null
  business.value = null
  reason.value = ''
  conceptExpanded.value = false
  styleExpanded.value = false
  scopeExpanded.value = false
  reviewExpanded.value = false
  try {
    const res = await getStockProfile(props.code) as any
    if (res?.data) {
      data.value = res.data
    } else {
      reason.value = res?.reason || '暂无公司概况数据'
    }
  } catch (e) {
    reason.value = '加载失败'
  } finally {
    loading.value = false
    emit('loaded', !!data.value)
  }
  // 经营范围/主营构成/经营评述为独立慢 job 缓存，可能为空，单独加载不阻塞基本面
  try {
    const bres = await getStockBusiness(props.code) as any
    business.value = bres?.data || null
  } catch (e) {
    business.value = null
  }
}

watch(() => props.code, () => load())
onMounted(() => load())
</script>

<template>
  <div class="company-profile" v-loading="loading">
    <div class="cp-header">
      <span class="cp-title">公司概况</span>
      <span v-if="data" class="cp-tags">
        <el-tag v-if="data.industry" size="small" type="primary" effect="plain">{{ data.industry }}</el-tag>
        <el-tag v-if="data.area" size="small" type="info" effect="plain">{{ data.area }}</el-tag>
      </span>
    </div>

    <template v-if="data">
      <div class="cp-metrics">
        <div v-for="m in metrics" :key="m.label" class="cp-metric" :class="{ hl: m.highlight }">
          <div class="cp-metric-label">{{ m.label }}</div>
          <div class="cp-metric-value" :style="m.color ? { color: m.color } : undefined">{{ m.value }}</div>
        </div>
      </div>

      <div v-if="conceptTags.length" class="cp-tag-block">
        <div class="cp-tag-label">
          概念题材
          <span class="cp-tag-count">（{{ conceptTags.length }}）</span>
        </div>
        <div class="cp-tag-list">
          <el-tag v-for="t in conceptShown" :key="t" size="small" effect="light" type="warning" class="cp-tag">{{ t }}</el-tag>
          <el-button
            v-if="conceptTags.length > TAG_LIMIT"
            link type="primary" size="small"
            @click="conceptExpanded = !conceptExpanded"
          >{{ conceptExpanded ? '收起' : `+${conceptTags.length - TAG_LIMIT} 展开` }}</el-button>
        </div>
      </div>

      <div v-if="styleTags.length" class="cp-tag-block">
        <div class="cp-tag-label">
          所属板块
          <span class="cp-tag-count">（{{ styleTags.length }}）</span>
        </div>
        <div class="cp-tag-list">
          <el-tag v-for="t in styleShown" :key="t" size="small" effect="plain" class="cp-tag">{{ t }}</el-tag>
          <el-button
            v-if="styleTags.length > TAG_LIMIT"
            link type="primary" size="small"
            @click="styleExpanded = !styleExpanded"
          >{{ styleExpanded ? '收起' : `+${styleTags.length - TAG_LIMIT} 展开` }}</el-button>
        </div>
      </div>

      <!-- 主营构成明细（最新报告期，按行业/产品/地区分组） -->
      <div v-if="mainopGroups.length" class="cp-section">
        <div class="cp-section-title">
          主营构成
          <span v-if="business?.report_date" class="cp-section-sub">（{{ fmtDate(business.report_date) }}）</span>
        </div>
        <div v-for="g in mainopGroups" :key="g.type" class="cp-mainop-group">
          <div class="cp-mainop-type">
            按{{ g.type }}
            <span v-if="g.reportDate && g.reportDate !== business?.report_date" class="cp-mainop-period">
              （{{ fmtDate(g.reportDate) }}）
            </span>
          </div>
          <div v-for="it in g.items" :key="g.type + '-' + it.item" class="cp-mainop-item">
            <div class="cp-mainop-row">
              <span class="cp-mainop-name" :title="it.item">{{ it.item }}</span>
              <span class="cp-mainop-val">{{ fmtMoney(it.income) }}</span>
            </div>
            <div class="cp-mainop-bar-wrap">
              <div class="cp-mainop-bar" :style="{ width: barWidth(it.income_ratio) }"></div>
            </div>
            <div class="cp-mainop-meta">
              <span>占比 {{ fmtRatio(it.income_ratio) }}</span>
              <span v-if="it.gross_profit_ratio != null">毛利率 {{ fmtRatio(it.gross_profit_ratio) }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 经营范围 -->
      <div v-if="business?.business_scope" class="cp-section">
        <div class="cp-section-title">经营范围</div>
        <div class="cp-longtext" :class="{ collapsed: scopeLong && !scopeExpanded }">{{ business.business_scope }}</div>
        <el-button
          v-if="scopeLong"
          link type="primary" size="small"
          @click="scopeExpanded = !scopeExpanded"
        >{{ scopeExpanded ? '收起' : '展开全文' }}</el-button>
      </div>

      <!-- 经营评述 -->
      <div v-if="business?.business_review" class="cp-section">
        <div class="cp-section-title">经营评述</div>
        <div class="cp-longtext" :class="{ collapsed: reviewLong && !reviewExpanded }">{{ business.business_review }}</div>
        <el-button
          v-if="reviewLong"
          link type="primary" size="small"
          @click="reviewExpanded = !reviewExpanded"
        >{{ reviewExpanded ? '收起' : '展开全文' }}</el-button>
      </div>
    </template>

    <el-empty v-else-if="!loading" :description="reason || '暂无公司概况数据'" :image-size="60" />
  </div>
</template>

<style lang="scss" scoped>
.company-profile {
  .cp-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 8px;
    margin-bottom: 14px;
    .cp-title {
      font-size: 15px;
      font-weight: 600;
    }
    .cp-tags {
      display: flex;
      align-items: center;
      gap: 6px;
      flex-wrap: wrap;
    }
  }

  .cp-metrics {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
    gap: 12px 16px;
    margin-bottom: 16px;

    @include sm-down {
      grid-template-columns: repeat(2, 1fr);
      gap: 10px 12px;
    }

    .cp-metric {
      display: flex;
      flex-direction: column;
      gap: 3px;
      padding: 8px 10px;
      background: #fafafa;
      border-radius: 6px;

      &.hl {
        background: #ecf5ff;
      }
      .cp-metric-label {
        font-size: 12px;
        color: #909399;
      }
      .cp-metric-value {
        font-size: 15px;
        font-weight: 600;
        color: #303133;
      }
      &.hl .cp-metric-value {
        color: #409eff;
      }
    }
  }

  .cp-tag-block {
    margin-top: 12px;
    .cp-tag-label {
      font-size: 13px;
      font-weight: 600;
      color: #606266;
      margin-bottom: 8px;
      .cp-tag-count {
        font-weight: normal;
        color: #909399;
      }
    }
    .cp-tag-list {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      align-items: center;
      .cp-tag {
        max-width: 100%;
      }
    }
  }

  .cp-section {
    margin-top: 16px;
    padding-top: 14px;
    border-top: 1px solid #f0f0f0;

    .cp-section-title {
      font-size: 13px;
      font-weight: 600;
      color: #606266;
      margin-bottom: 10px;
      .cp-section-sub {
        font-weight: normal;
        color: #909399;
      }
    }
  }

  .cp-mainop-group {
    margin-bottom: 12px;

    .cp-mainop-type {
      font-size: 12px;
      color: #909399;
      margin-bottom: 6px;

      .cp-mainop-period {
        color: #c0c4cc;
        font-size: 11px;
      }
    }

    .cp-mainop-item {
      margin-bottom: 8px;

      .cp-mainop-row {
        display: flex;
        justify-content: space-between;
        align-items: baseline;
        gap: 8px;
        margin-bottom: 3px;

        .cp-mainop-name {
          font-size: 13px;
          color: #303133;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .cp-mainop-val {
          font-size: 13px;
          font-weight: 600;
          color: #303133;
          flex-shrink: 0;
        }
      }

      .cp-mainop-bar-wrap {
        height: 6px;
        background: #f0f2f5;
        border-radius: 3px;
        overflow: hidden;

        .cp-mainop-bar {
          height: 100%;
          background: linear-gradient(90deg, #409eff, #79bbff);
          border-radius: 3px;
          transition: width 0.3s;
        }
      }

      .cp-mainop-meta {
        display: flex;
        gap: 14px;
        margin-top: 3px;
        font-size: 12px;
        color: #909399;
      }
    }
  }

  .cp-longtext {
    font-size: 13px;
    line-height: 1.7;
    color: #606266;
    white-space: pre-wrap;
    word-break: break-word;

    &.collapsed {
      display: -webkit-box;
      -webkit-line-clamp: 3;
      line-clamp: 3;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }
  }
}
</style>
