<script setup lang="ts">
import { ref, onMounted, onActivated } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getBacktestConfig, getBacktestHistory, deleteBacktestHistory } from '@/api/stock'
import { useResponsive } from '@/composables/useResponsive'

const route = useRoute()
const router = useRouter()
const { isMobile } = useResponsive()

const strategies = ref<any[]>([])
const loading = ref(false)
const items = ref<any[]>([])
const total = ref(0)
// 来自详情页跳转时携带的股票名（用于空态提示与单股回测回填）
const queryName = ref('')

const filter = ref({
  code: '',
  strategy: '',
  dateRange: [] as string[],
  page: 1,
  page_size: 20,
})

// 从路由 query 回填股票代码（详情页「查看回测」跳转时携带）
const _applyQuery = () => {
  const q = route.query
  if (typeof q.code === 'string' && q.code.trim()) {
    filter.value.code = q.code.trim()
  }
  queryName.value = typeof q.name === 'string' ? q.name : ''
}

onMounted(async () => {
  try {
    const config: any = await getBacktestConfig()
    strategies.value = config?.strategies || []
  } catch { /* ignore */ }
  _applyQuery()
  loadList()
})

onActivated(() => {
  _applyQuery()
  loadList()
})

const loadList = async () => {
  loading.value = true
  try {
    const params: any = {
      page: filter.value.page,
      page_size: filter.value.page_size,
    }
    if (filter.value.code) params.code = filter.value.code.trim()
    if (filter.value.strategy) params.strategy = filter.value.strategy
    if (filter.value.dateRange && filter.value.dateRange.length === 2) {
      params.start = filter.value.dateRange[0]
      params.end = filter.value.dateRange[1]
    }
    const res: any = await getBacktestHistory(params)
    items.value = res?.items || []
    total.value = res?.total || 0
  } catch (e: any) {
    ElMessage.error(e.message || '加载历史失败')
  } finally {
    loading.value = false
  }
}

const handleSearch = () => {
  filter.value.page = 1
  loadList()
}

const handleReset = () => {
  filter.value.code = ''
  filter.value.strategy = ''
  filter.value.dateRange = []
  filter.value.page = 1
  loadList()
}

const handleView = (row: any) => {
  router.push({
    path: '/backtest/single',
    query: {
      code: row.code,
      strategy: row.strategy,
      start_date: row.start_date,
      end_date: row.end_date,
      hold_days: row.hold_days != null ? String(row.hold_days) : '',
    },
  })
}

const handleDelete = async (row: any) => {
  try {
    await ElMessageBox.confirm(`确认删除 ${row.code} 的回测记录？`, '提示', { type: 'warning' })
  } catch {
    return
  }
  try {
    await deleteBacktestHistory(row.id)
    ElMessage.success('已删除')
    if (items.value.length === 1 && filter.value.page > 1) filter.value.page -= 1
    loadList()
  } catch (e: any) {
    ElMessage.error(e.message || '删除失败')
  }
}

const formatRate = (val: any) => {
  if (val === null || val === undefined) return '—'
  const num = Number(val)
  return num >= 0 ? `+${num.toFixed(2)}%` : `${num.toFixed(2)}%`
}
const getRateClass = (val: any) => {
  if (val === null || val === undefined) return ''
  return Number(val) >= 0 ? 'text-up' : 'text-down'
}

// 跳转单股回测，携带当前筛选的股票代码进行回填
const goSingleBacktest = () => {
  const q: any = {}
  if (filter.value.code) q.code = filter.value.code.trim()
  if (queryName.value) q.name = queryName.value
  router.push({ path: '/backtest/single', query: q })
}
</script>

<template>
  <div class="backtest-history">
    <el-card shadow="never" class="filter-card">
      <template #header><span class="card-title">回测历史</span></template>
      <el-form :model="filter" inline>
        <el-form-item label="股票代码">
          <el-input v-model="filter.code" placeholder="如 000001" style="width: 140px" clearable />
        </el-form-item>
        <el-form-item label="策略">
          <el-select v-model="filter.strategy" placeholder="全部" clearable filterable style="width: 200px">
            <el-option v-for="s in strategies" :key="s.name" :label="s.cn" :value="s.name" />
          </el-select>
        </el-form-item>
        <el-form-item label="创建时间">
          <el-date-picker v-model="filter.dateRange" type="daterange" range-separator="至"
            start-placeholder="开始" end-placeholder="结束"
            format="YYYY-MM-DD" value-format="YYYY-MM-DD" style="width: 240px" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="handleSearch">查询</el-button>
          <el-button @click="handleReset">重置</el-button>
          <el-button type="success" plain @click="goSingleBacktest">去单股回测</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never" class="table-card">
      <el-table v-if="!isMobile" v-loading="loading" :data="items" border size="small" stripe>
        <template #empty>
          <div class="empty-state">
            <p>{{ filter.code ? `股票 ${filter.code}${queryName ? '（' + queryName + '）' : ''} 暂无回测历史` : '暂无回测历史' }}</p>
            <el-button type="primary" @click="goSingleBacktest">前往单股回测</el-button>
          </div>
        </template>
        <el-table-column prop="created_at" label="创建时间" width="160" align="center" />
        <el-table-column prop="code" label="代码" width="80" align="center" />
        <el-table-column prop="name" label="名称" width="100" align="center" />
        <el-table-column prop="strategy_cn" label="策略" width="120" align="center" />
        <el-table-column label="区间" width="200" align="center">
          <template #default="{ row }">{{ row.start_date }} ~ {{ row.end_date }}</template>
        </el-table-column>
        <el-table-column label="出场模式" width="120" align="center">
          <template #default="{ row }">{{ row.exit_mode === 'fixed' ? `固定 ${row.hold_days} 日` : '策略卖点' }}</template>
        </el-table-column>
        <el-table-column prop="trade_count" label="笔数" width="70" align="center" />
        <el-table-column label="胜率" width="90" align="right">
          <template #default="{ row }">{{ row.win_rate == null ? '—' : row.win_rate + '%' }}</template>
        </el-table-column>
        <el-table-column label="累计收益" width="100" align="right">
          <template #default="{ row }"><span :class="getRateClass(row.cum_return)">{{ formatRate(row.cum_return) }}</span></template>
        </el-table-column>
        <el-table-column label="操作" width="130" align="center" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="handleView(row)">查看</el-button>
            <el-button link type="danger" @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 移动端卡片视图 -->
      <div v-if="isMobile" v-loading="loading" class="bh-card-list">
        <div v-for="row in items" :key="row.id" class="bh-card">
          <div class="bh-card-head">
            <span class="bh-card-code">{{ row.code }}</span>
            <span class="bh-card-name">{{ row.name }}</span>
            <span :class="getRateClass(row.cum_return)" class="bh-card-return">{{ formatRate(row.cum_return) }}</span>
          </div>
          <div class="bh-card-body">
            <div class="bh-card-field">
              <span class="bh-lbl">策略</span>
              <span>{{ row.strategy_cn }}</span>
            </div>
            <div class="bh-card-field">
              <span class="bh-lbl">胜率</span>
              <span>{{ row.win_rate == null ? '—' : row.win_rate + '%' }}</span>
            </div>
            <div class="bh-card-field">
              <span class="bh-lbl">出场模式</span>
              <span>{{ row.exit_mode === 'fixed' ? `固定 ${row.hold_days} 日` : '策略卖点' }}</span>
            </div>
            <div class="bh-card-field">
              <span class="bh-lbl">笔数</span>
              <span>{{ row.trade_count ?? '—' }}</span>
            </div>
            <div class="bh-card-field bh-card-field-full">
              <span class="bh-lbl">区间</span>
              <span>{{ row.start_date }} ~ {{ row.end_date }}</span>
            </div>
            <div class="bh-card-field bh-card-field-full">
              <span class="bh-lbl">创建时间</span>
              <span>{{ row.created_at }}</span>
            </div>
          </div>
          <div class="bh-card-ops">
            <a class="bh-op" @click="handleView(row)">查看</a>
            <span class="bh-op-sep">|</span>
            <a class="bh-op bh-op-danger" @click="handleDelete(row)">删除</a>
          </div>
        </div>
        <div v-if="!loading && items.length === 0" class="empty-state">
          <p>{{ filter.code ? `股票 ${filter.code}${queryName ? '（' + queryName + '）' : ''} 暂无回测历史` : '暂无回测历史' }}</p>
          <el-button type="primary" @click="goSingleBacktest">前往单股回测</el-button>
        </div>
      </div>

      <div class="pagination-row">
        <el-pagination
          v-model:current-page="filter.page"
          v-model:page-size="filter.page_size"
          :total="total"
          :page-sizes="[10, 20, 50, 100]"
          layout="total, sizes, prev, pager, next"
          @current-change="loadList"
          @size-change="handleSearch"
        />
      </div>
    </el-card>
  </div>
</template>

<style lang="scss" scoped>
.backtest-history { padding: 0; }
.filter-card, .table-card { margin-bottom: 16px; }
.card-title { font-size: 16px; font-weight: 600; }
.pagination-row { display: flex; justify-content: flex-end; margin-top: 16px; }
.empty-state { padding: 24px 0; text-align: center; color: #909399; }
.empty-state p { margin: 0 0 12px; }
.text-up { color: #f56c6c; }
.text-down { color: #67c23a; }

/* 移动端卡片视图 */
.bh-card-list { display: flex; flex-direction: column; gap: 10px; }
.bh-card {
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-light);
  border-radius: 6px;
  padding: 10px 12px;
}
.bh-card-head {
  display: flex; align-items: center; gap: 8px;
  border-bottom: 1px dashed var(--el-border-color-lighter);
  padding-bottom: 6px; margin-bottom: 8px;
}
.bh-card-code { font-weight: 600; font-size: 15px; color: var(--el-color-primary); }
.bh-card-name { flex: 1; font-size: 14px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bh-card-return { font-weight: 600; font-size: 14px; }
.bh-card-body {
  display: grid; grid-template-columns: 1fr 1fr; gap: 6px 12px; font-size: 13px;
}
.bh-card-field { display: flex; justify-content: space-between; align-items: center; gap: 8px; min-width: 0; }
.bh-card-field-full { grid-column: 1 / -1; }
.bh-lbl { color: var(--el-text-color-secondary); white-space: nowrap; }
.bh-card-ops {
  margin-top: 10px; padding-top: 8px;
  border-top: 1px dashed var(--el-border-color-lighter);
  display: flex; justify-content: flex-end; gap: 8px; font-size: 13px;
}
.bh-op { color: var(--el-color-primary); cursor: pointer; }
.bh-op:hover { text-decoration: underline; }
.bh-op-danger { color: var(--el-color-danger); }
.bh-op-sep { color: var(--el-border-color); }

@include sm-down {
  .filter-card :deep(.el-form--inline .el-form-item) {
    display: flex;
    width: 100%;
    margin-right: 0;
  }
  .filter-card :deep(.el-form--inline .el-form-item__content) {
    flex: 1;
  }
  .filter-card :deep(.el-input),
  .filter-card :deep(.el-select),
  .filter-card :deep(.el-date-editor) {
    width: 100% !important;
  }
  .pagination-row { justify-content: center; }
}
</style>
