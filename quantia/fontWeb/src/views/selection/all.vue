<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  getSelectionScoreIndustries,
  getSelectionScoreList,
  getSelectionScoreTop,
} from '@/api/selectionScore'

type AnyObj = Record<string, any>
const router = useRouter()

const loading = ref(false)
const loadingTop = ref(false)
const loadingIndustries = ref(false)

const filters = ref({
  date: '',
  industry: '',
  rating: '',
  min_quality: undefined as number | undefined,
  template: 'balanced',
  sort: 'total_score',
})

const pagination = ref({
  page: 1,
  page_size: 30,
  total: 0,
})

const listData = ref<AnyObj[]>([])
const topData = ref<AnyObj[]>([])
const industryData = ref<AnyObj[]>([])

const listMeta = ref<AnyObj>({})
const topMeta = ref<AnyObj>({})
const industriesMeta = ref<AnyObj>({})

const warningText = ref('')

const ratingOptions = ['S', 'A', 'B', 'C', 'D']
const templateOptions = [
  { label: '均衡', value: 'balanced' },
  { label: '价值', value: 'value' },
  { label: '成长', value: 'growth' },
  { label: '技术', value: 'technical' },
  { label: 'M1选股池', value: 'm1_selection_pool' },
]
const sortOptions = [
  { label: '展示分', value: 'total_score' },
  { label: '视图分(显式)', value: 'total_score_view' },
  { label: '质量分Q', value: 'quality_score' },
  { label: '行业排名', value: 'industry_rank' },
]

const industryOptions = computed(() => industryData.value.map((x) => String(x.industry || '')).filter(Boolean))

const pageDate = computed(() => listMeta.value.date_effective || industriesMeta.value.date_effective || topMeta.value.date_effective || '--')
const contractVersion = computed(() => listMeta.value.api_contract_version || industriesMeta.value.api_contract_version || topMeta.value.api_contract_version || '--')

const kpis = computed(() => {
  const totalStocks = Number(pagination.value.total || 0)
  const sCount = listData.value.filter((x) => String(x.rating || '') === 'S').length
  const industryCount = Number(industriesMeta.value.count || industryData.value.length || 0)
  const avgScore = listData.value.length
    ? listData.value.reduce((s, x) => s + Number(x.display_score ?? 0), 0) / listData.value.length
    : 0
  return [
    { label: '股票总数', value: totalStocks.toLocaleString('zh-CN') },
    { label: 'S级数量(当前页)', value: String(sCount) },
    { label: '行业数量', value: String(industryCount) },
    { label: '当前页均分', value: avgScore ? avgScore.toFixed(2) : '--' },
  ]
})

function toNum(v: any, digits = 2): string {
  const n = Number(v)
  if (!Number.isFinite(n)) return '--'
  return n.toFixed(digits)
}

async function loadList() {
  loading.value = true
  try {
    const res: AnyObj = await getSelectionScoreList({
      date: filters.value.date || undefined,
      industry: filters.value.industry || undefined,
      rating: filters.value.rating || undefined,
      min_quality: filters.value.min_quality,
      template: filters.value.template,
      sort: filters.value.sort,
      page: pagination.value.page,
      page_size: pagination.value.page_size,
    })
    listMeta.value = res || {}
    listData.value = Array.isArray(res?.items) ? res.items : []
    pagination.value.total = Number(res?.total || 0)
    warningText.value = String(res?.warning || '')
  } catch (e: any) {
    listData.value = []
    pagination.value.total = 0
    ElMessage.error(e?.response?.data?.error || '加载评分榜失败')
  } finally {
    loading.value = false
  }
}

async function loadTop() {
  loadingTop.value = true
  try {
    const res: AnyObj = await getSelectionScoreTop({
      date: filters.value.date || undefined,
      n: 10,
    })
    topMeta.value = res || {}
    topData.value = Array.isArray(res?.items) ? res.items : []
  } catch {
    topData.value = []
  } finally {
    loadingTop.value = false
  }
}

async function loadIndustries() {
  loadingIndustries.value = true
  try {
    const res: AnyObj = await getSelectionScoreIndustries({
      date: filters.value.date || undefined,
      min_quality: filters.value.min_quality,
      template: filters.value.template,
    })
    industriesMeta.value = res || {}
    industryData.value = Array.isArray(res?.items) ? res.items : []
  } catch {
    industryData.value = []
  } finally {
    loadingIndustries.value = false
  }
}

async function loadAll() {
  await Promise.all([loadList(), loadTop(), loadIndustries()])
}

function onSearch() {
  pagination.value.page = 1
  loadAll()
}

function onReset() {
  filters.value = {
    date: '',
    industry: '',
    rating: '',
    min_quality: undefined,
    template: 'balanced',
    sort: 'total_score',
  }
  pagination.value.page = 1
  loadAll()
}

function onPageChange(page: number) {
  pagination.value.page = page
  loadList()
}

function goIndustry(industry: string) {
  router.push({
    path: `/selection/industry/${encodeURIComponent(industry)}`,
    query: {
      date: listMeta.value.date_effective || filters.value.date || undefined,
      template: filters.value.template || undefined,
      sort: filters.value.sort || undefined,
      rating: filters.value.rating || undefined,
      min_quality: filters.value.min_quality,
    },
  })
}

function goDetail(code: string) {
  router.push({
    path: `/selection/detail/${encodeURIComponent(code)}`,
    query: { date: listMeta.value.date_effective || filters.value.date || undefined },
  })
}

onMounted(loadAll)
</script>

<template>
  <div class="selection-score-page">
    <section class="hero-card">
      <div>
        <h1>综合选股评分榜</h1>
        <p>日期 {{ pageDate }} · 契约 {{ contractVersion }} · 模板 {{ listMeta.template_effective || filters.template }}</p>
      </div>
      <el-tag type="success" effect="dark">M4 首页</el-tag>
    </section>

    <section class="filter-card">
      <el-date-picker v-model="filters.date" type="date" value-format="YYYY-MM-DD" placeholder="选择日期(默认最新)" clearable />
      <el-select v-model="filters.template" placeholder="模板" style="width: 140px">
        <el-option v-for="opt in templateOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
      </el-select>
      <el-select v-model="filters.sort" placeholder="排序" style="width: 160px">
        <el-option v-for="opt in sortOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
      </el-select>
      <el-select v-model="filters.industry" placeholder="行业" clearable filterable style="width: 180px">
        <el-option v-for="name in industryOptions" :key="name" :label="name" :value="name" />
      </el-select>
      <el-select v-model="filters.rating" placeholder="评级" clearable style="width: 110px">
        <el-option v-for="r in ratingOptions" :key="r" :label="r" :value="r" />
      </el-select>
      <el-input-number v-model="filters.min_quality" :min="0" :max="100" :step="1" controls-position="right" placeholder="最小Q" style="width: 130px" />
      <el-button type="primary" @click="onSearch">查询</el-button>
      <el-button @click="onReset">重置</el-button>
    </section>

    <section class="kpi-grid">
      <article v-for="item in kpis" :key="item.label" class="kpi-card">
        <div class="kpi-label">{{ item.label }}</div>
        <div class="kpi-value">{{ item.value }}</div>
      </article>
    </section>

    <section class="dual-grid">
      <el-card class="panel" shadow="never" v-loading="loadingTop">
        <template #header>
          <div class="panel-header">全市场 Top10（固定按质量分Q）</div>
        </template>
        <div v-if="!topData.length" class="empty-tip">暂无数据</div>
        <ul v-else class="top-list">
          <li v-for="(item, idx) in topData" :key="item.code || idx" class="top-item">
            <span class="rank">{{ idx + 1 }}</span>
            <el-button class="name-btn" link type="primary" @click="goDetail(String(item.code || ''))">{{ item.name || item.code }}</el-button>
            <span class="meta">Q {{ toNum(item.quality_score) }} · 展示 {{ toNum(item.display_score) }}</span>
          </li>
        </ul>
      </el-card>

      <el-card class="panel" shadow="never" v-loading="loadingIndustries">
        <template #header>
          <div class="panel-header">行业宫格（点击筛选）</div>
        </template>
        <div v-if="!industryData.length" class="empty-tip">暂无行业汇总</div>
        <div v-else class="industry-grid">
          <button
            v-for="item in industryData.slice(0, 12)"
            :key="item.industry"
            class="industry-card"
            type="button"
            @click="goIndustry(item.industry)"
          >
            <div class="industry-title">{{ item.industry }}</div>
            <div class="industry-meta">均分 {{ toNum(item.avg_display_score) }} · {{ item.stock_count }}只</div>
            <div class="industry-meta">龙头 {{ item.leader_name || item.leader_code }}</div>
          </button>
        </div>
      </el-card>
    </section>

    <el-card class="table-panel" shadow="never">
      <template #header>
        <div class="panel-header">评分列表</div>
      </template>

      <el-alert v-if="warningText" :title="warningText" type="warning" :closable="false" show-icon style="margin-bottom: 12px" />

      <el-table :data="listData" stripe border v-loading="loading" height="560">
        <el-table-column type="index" width="64" label="#" />
        <el-table-column prop="code" label="代码" width="92" />
        <el-table-column prop="name" label="名称" min-width="120">
          <template #default="scope">
            <el-button link type="primary" @click="goDetail(String(scope.row.code || ''))">{{ scope.row.name || scope.row.code }}</el-button>
          </template>
        </el-table-column>
        <el-table-column prop="industry" label="行业" min-width="120" />
        <el-table-column label="展示分" width="110">
          <template #default="scope">{{ toNum(scope.row.display_score) }}</template>
        </el-table-column>
        <el-table-column label="质量分Q" width="110">
          <template #default="scope">{{ toNum(scope.row.quality_score) }}</template>
        </el-table-column>
        <el-table-column prop="rating" label="评级" width="80" />
        <el-table-column label="行业名次" width="108">
          <template #default="scope">{{ scope.row.industry_rank || '--' }}</template>
        </el-table-column>
        <el-table-column label="排名变化" width="130">
          <template #default="scope">
            <span>{{ scope.row.rank_change_1d ?? '--' }}</span>
            <el-tag v-if="scope.row.rank_change_comparable === false" size="small" type="info" style="margin-left: 6px">不可比</el-tag>
          </template>
        </el-table-column>
      </el-table>

      <div class="pager-wrap">
        <el-pagination
          background
          layout="prev, pager, next, total"
          :current-page="pagination.page"
          :page-size="pagination.page_size"
          :total="pagination.total"
          @current-change="onPageChange"
        />
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.selection-score-page {
  display: grid;
  gap: 14px;
  padding: 14px;
  background: linear-gradient(165deg, #f7fafc 0%, #eef4ff 55%, #f5fbf7 100%);
}

.hero-card {
  border-radius: 16px;
  background: linear-gradient(130deg, #0f172a, #1d4ed8 45%, #0ea5a4);
  color: #fff;
  padding: 18px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.hero-card h1 {
  margin: 0;
  font-size: 26px;
}

.hero-card p {
  margin: 8px 0 0;
  opacity: 0.92;
}

.filter-card {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  padding: 12px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid #dbe7ff;
}

.kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.kpi-card {
  border-radius: 12px;
  padding: 12px;
  background: #fff;
  border: 1px solid #e3ecff;
}

.kpi-label {
  color: #5b6b86;
  font-size: 12px;
}

.kpi-value {
  margin-top: 6px;
  font-size: 24px;
  font-weight: 700;
  color: #0f1f3d;
}

.dual-grid {
  display: grid;
  grid-template-columns: 1fr 1.4fr;
  gap: 10px;
}

.panel,
.table-panel {
  border-radius: 12px;
  border-color: #dce7ff;
}

.panel-header {
  font-weight: 700;
  color: #223151;
}

.top-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 8px;
}

.top-item {
  display: grid;
  grid-template-columns: 34px 1fr auto;
  gap: 8px;
  align-items: center;
  padding: 8px;
  border-radius: 8px;
  background: #f7fbff;
}

.rank {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: #0f4fbf;
  color: #fff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
}

.name {
  font-weight: 600;
  color: #1a2a4a;
}

.name-btn {
  justify-self: start;
  font-weight: 600;
}

.meta {
  font-size: 12px;
  color: #54709f;
}

.industry-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.industry-card {
  border: 1px solid #d7e6ff;
  background: #f9fcff;
  border-radius: 8px;
  padding: 9px;
  text-align: left;
  cursor: pointer;
}

.industry-card:hover {
  border-color: #8fb3ff;
  background: #eef5ff;
}

.industry-title {
  font-weight: 700;
  color: #1a2f56;
}

.industry-meta {
  margin-top: 4px;
  font-size: 12px;
  color: #5b6c87;
}

.pager-wrap {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}

.empty-tip {
  color: #7b8ba8;
  font-size: 13px;
}

@media (max-width: 1024px) {
  .kpi-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .dual-grid {
    grid-template-columns: 1fr;
  }

  .industry-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .selection-score-page {
    padding: 10px;
  }

  .hero-card h1 {
    font-size: 22px;
  }

  .industry-grid {
    grid-template-columns: 1fr;
  }
}
</style>
