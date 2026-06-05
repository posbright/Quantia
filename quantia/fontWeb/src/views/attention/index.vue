<template>
  <div class="attention-page">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>我的关注（{{ count }} 只）</span>
          <div class="header-actions">
            <el-button size="small" @click="loadList" :loading="loading">刷新</el-button>
            <el-button size="small" type="primary" @click="goPreference">分析设置</el-button>
          </div>
        </div>
      </template>

      <el-alert
        type="info"
        :closable="false"
        show-icon
        class="tip"
      >
        关注列表不限数量。综合选股评分来自每日多因子打分；最新AI评分 / AI评级来自 AI 分析报告。
        点击股票代码查看个股 K 线技术详情；「AI分析历史」「AI评分历史」列可查看该股历次分析与评分变化。定时分析可选「综合选股评分最高的前 N 只」或「指定股票」，
        分析股票数 / 选股方式 / 失败熔断次数可在
        <el-link type="primary" underline="never" @click="goPreference">报告偏好</el-link>
        中调整。
      </el-alert>

      <el-table :data="items" v-loading="loading" stripe style="width: 100%; margin-top: 12px">
        <el-table-column type="index" label="#" width="56" />
        <el-table-column prop="code" label="代码" width="100">
          <template #default="{ row }">
            <el-link type="primary" underline="never" @click="goStockDetail(row)">{{ row.code }}</el-link>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="名称" min-width="110" />
        <el-table-column label="综合选股评分" width="150" sortable :sort-method="sortBySelScore">
          <template #default="{ row }">
            <template v-if="row.sel_score != null">
              <el-tag :type="selScoreTagType(row.sel_score)" effect="plain">
                {{ Number(row.sel_score).toFixed(1) }}
              </el-tag>
              <span v-if="row.sel_rating" class="sel-rating">{{ row.sel_rating }}</span>
            </template>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="行业排名" width="120">
          <template #default="{ row }">
            <span v-if="row.sel_rank != null" class="rank-text">
              {{ row.sel_rank }}<span class="muted">/{{ row.sel_total ?? '—' }}</span>
            </span>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="最新AI评分" width="120">
          <template #default="{ row }">
            <el-tag v-if="row.report_rating_score != null" :type="scoreTagType(row.report_rating_score)" effect="dark">
              {{ Number(row.report_rating_score).toFixed(0) }}
            </el-tag>
            <el-tag v-else-if="row.report_id != null" type="info" effect="plain" size="small">已生成</el-tag>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="AI评级" width="100">
          <template #default="{ row }">
            <el-tag
              v-if="row.report_rating"
              :type="reportRatingType(row.report_rating)"
              effect="plain"
              size="small"
            >{{ reportRatingLabel(row.report_rating) }}</el-tag>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="report_at" label="AI分析时间" width="170">
          <template #default="{ row }">
            <span v-if="row.report_at">{{ row.report_at }}</span>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="AI分析历史" width="110" align="center">
          <template #default="{ row }">
            <el-button size="small" link type="primary" @click="goAnalysisHistory(row)">查看</el-button>
          </template>
        </el-table-column>
        <el-table-column label="AI评分历史" width="110" align="center">
          <template #default="{ row }">
            <el-button size="small" link type="primary" @click="goScoreHistory(row)">查看</el-button>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="230" fixed="right">
          <template #default="{ row }">
            <el-button size="small" link type="primary" @click="goDetail(row)">评分详情</el-button>
            <el-button size="small" link type="primary" @click="goAnalysis(row)">AI分析</el-button>
            <el-button size="small" link type="danger" @click="handleRemove(row)">取消关注</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无关注股票，可在股票数据 / 选股页面点击关注添加" />
        </template>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onActivated } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getAttentionList, type AttentionListItem } from '@/api/report'
import { toggleAttention } from '@/api/stock'

const router = useRouter()
const loading = ref(false)
const items = ref<AttentionListItem[]>([])
const count = ref(0)

async function loadList() {
  loading.value = true
  try {
    const res = await getAttentionList() as any
    items.value = res.items || []
    count.value = res.count || items.value.length
  } catch (err: any) {
    ElMessage.warning('加载关注列表失败: ' + (err.message || err))
  } finally {
    loading.value = false
  }
}

function scoreTagType(score: number) {
  if (score >= 70) return 'success'
  if (score >= 50) return 'warning'
  return 'danger'
}

function selScoreTagType(score: number) {
  if (score >= 70) return 'success'
  if (score >= 55) return 'warning'
  if (score >= 40) return 'info'
  return 'danger'
}

function sortBySelScore(a: AttentionListItem, b: AttentionListItem) {
  const av = a.sel_score ?? -1
  const bv = b.sel_score ?? -1
  return av - bv
}

function reportRatingLabel(rating?: string) {
  const map: Record<string, string> = {
    buy: '买入',
    hold: '观望',
    avoid: '回避',
  }
  return (rating && map[rating]) || rating || ''
}

function reportRatingType(rating?: string) {
  if (rating === 'buy') return 'success'
  if (rating === 'avoid') return 'danger'
  if (rating === 'hold') return 'warning'
  return 'info'
}

function goDetail(row: AttentionListItem) {
  router.push({ path: `/selection/detail/${row.code}` })
}

function goStockDetail(row: AttentionListItem) {
  router.push({
    path: '/indicator/detail',
    query: { code: row.code, name: row.name || undefined },
  })
}

function goAnalysis(row: AttentionListItem) {
  router.push({ path: '/ai-report/analysis', query: { code: row.code } })
}

function goAnalysisHistory(row: AttentionListItem) {
  router.push({ path: '/ai-report/history', query: { code: row.code } })
}

function goScoreHistory(row: AttentionListItem) {
  router.push({ path: '/ai-report/history', query: { code: row.code, tab: 'score' } })
}

function goPreference() {
  router.push({ path: '/ai-report/preference' })
}

async function handleRemove(row: AttentionListItem) {
  try {
    await ElMessageBox.confirm(`确认取消关注 ${row.code} ${row.name}？`, '提示', {
      type: 'warning',
    })
  } catch {
    return
  }
  try {
    await toggleAttention({ code: row.code, otype: '1' })
    items.value = items.value.filter(it => it.code !== row.code)
    count.value = items.value.length
    ElMessage.success('已取消关注')
  } catch (err: any) {
    ElMessage.error('操作失败: ' + (err.message || err))
  }
}

onMounted(loadList)
onActivated(loadList)
</script>

<style scoped>
.attention-page {
  padding: 20px;
}
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.header-actions {
  display: flex;
  gap: 8px;
}
.tip {
  margin-bottom: 4px;
}
.muted {
  color: #c0c4cc;
}
.sel-rating {
  margin-left: 6px;
  font-weight: 600;
  color: #909399;
}
.rank-text {
  font-variant-numeric: tabular-nums;
}
</style>
