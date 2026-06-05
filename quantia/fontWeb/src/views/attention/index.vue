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
        关注列表不限数量。每日定时分析的股票数、连续失败熔断次数可在
        <el-link type="primary" underline="never" @click="goPreference">报告偏好</el-link>
        中调整。
      </el-alert>

      <el-table :data="items" v-loading="loading" stripe style="width: 100%; margin-top: 12px">
        <el-table-column type="index" label="#" width="56" />
        <el-table-column prop="code" label="代码" width="100" />
        <el-table-column prop="name" label="名称" min-width="120" />
        <el-table-column label="最新AI评分" width="130">
          <template #default="{ row }">
            <el-tag v-if="row.score != null" :type="scoreTagType(row.score)" effect="dark">
              {{ Number(row.score).toFixed(1) }}
            </el-tag>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="AI建议" width="110">
          <template #default="{ row }">
            <span v-if="row.action">{{ actionLabel(row.action) }}</span>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="scored_at" label="评分时间" width="170">
          <template #default="{ row }">
            <span v-if="row.scored_at">{{ row.scored_at }}</span>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="260" fixed="right">
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

function actionLabel(action: string) {
  const map: Record<string, string> = {
    reject: '拒绝交易',
    hold: '建议观望',
    pass: '允许交易',
  }
  return map[action] || action
}

function goDetail(row: AttentionListItem) {
  router.push({ path: `/selection/detail/${row.code}` })
}

function goAnalysis(row: AttentionListItem) {
  router.push({ path: '/ai-report/analysis', query: { code: row.code } })
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
</style>
