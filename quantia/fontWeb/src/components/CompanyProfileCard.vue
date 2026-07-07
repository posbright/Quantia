<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { getStockProfile, type StockProfileData } from '@/api/stock'

const props = defineProps<{ code: string; name?: string }>()

const data = ref<StockProfileData | null>(null)
const reason = ref('')
const loading = ref(false)

// 展开/收起长概念、板块标签
const conceptExpanded = ref(false)
const styleExpanded = ref(false)
const TAG_LIMIT = 8

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

// 涨跌色：正绿负红（A 股习惯：涨红跌绿 → 增长率正用红，负用绿）
const growthColor = (v: number | null | undefined): string => {
  if (v == null || !isFinite(v as number)) return '#303133'
  return Number(v) >= 0 ? '#f56c6c' : '#67c23a'
}

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
  reason.value = ''
  conceptExpanded.value = false
  styleExpanded.value = false
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
}
</style>
