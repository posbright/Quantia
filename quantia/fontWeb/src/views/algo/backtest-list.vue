<template>
  <div class="bt-history">
    <div class="page-header">
      <div class="header-left">
        <h2>回测列表</h2>
        <el-tag type="info" size="small" class="count-tag">
          共 {{ total }} 条回测
        </el-tag>
      </div>
      <div class="header-right">
        <el-button type="danger" :disabled="selectedRows.length === 0" @click="batchDelete">
          <el-icon><Delete /></el-icon>
          删除 ({{ selectedRows.length }})
        </el-button>
        <el-button type="primary" :disabled="selectedRows.length < 2" @click="goCompare">
          <el-icon><DataAnalysis /></el-icon>
          对比 ({{ selectedRows.length }})
        </el-button>
        <el-select v-model="filterStrategyId" placeholder="筛选策略" clearable style="width: 200px;"
                   @change="onFilterChange">
          <el-option label="全部策略" :value="0" />
          <el-option v-for="s in strategies" :key="s.id" :label="s.name" :value="s.id" />
        </el-select>
      </div>
    </div>

    <ResponsiveDataView :data="list" :loading="loading" row-key="id" switch-at="md" empty-text="暂无回测记录">
      <!-- 桌面端：保留原大宽表 -->
      <el-table :data="list" v-loading="loading" stripe style="width: 100%;"
              :default-sort="{ prop: 'total_return', order: 'descending' }"
              @selection-change="onSelectionChange" @sort-change="onSortChange" ref="tableRef">
      <el-table-column type="selection" width="45" />
      <el-table-column prop="id" label="ID" width="60" sortable="custom" />
      <el-table-column prop="strategy_name" label="策略名称" width="150" show-overflow-tooltip>
        <template #default="{ row }">
          <el-link type="primary" @click="$router.push('/algo/edit/' + row.strategy_id)">
            {{ row.strategy_name }}
          </el-link>
        </template>
      </el-table-column>
      <el-table-column label="回测区间" width="200">
        <template #default="{ row }">{{ row.start_date }} ~ {{ row.end_date }}</template>
      </el-table-column>
      <el-table-column prop="initial_cash" label="初始资金" width="100" align="right">
        <template #default="{ row }">{{ formatCash(row.initial_cash) }}</template>
      </el-table-column>
      <el-table-column prop="total_return" label="策略收益" width="95" align="right" sortable="custom">
        <template #default="{ row }">
          <span :class="retCls(row.total_return)">{{ fmtRet(row.total_return) }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="annual_return" label="年化收益" width="95" align="right" sortable="custom">
        <template #default="{ row }">
          <span :class="retCls(row.annual_return)">{{ fmtRet(row.annual_return) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="基准收益" width="95" align="right" sortable :sort-method="(a:any,b:any)=> (a.benchmark_return||0)-(b.benchmark_return||0)">
        <template #default="{ row }">
          <span :class="retCls(row.benchmark_return)">{{ fmtRet(row.benchmark_return) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="超额收益" width="95" align="right" sortable :sort-method="(a:any,b:any)=> (a.excess_return||0)-(b.excess_return||0)">
        <template #default="{ row }">
          <span :class="retCls(row.excess_return)">{{ fmtRet(row.excess_return) }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="max_drawdown" label="最大回撤" width="90" align="right" sortable="custom">
        <template #default="{ row }">
          <span class="val-green">{{ row.max_drawdown != null ? N(row.max_drawdown).toFixed(2) + '%' : '--' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="超额最大回撤" width="110" align="right" sortable :sort-method="(a:any,b:any)=> (a.excess_max_drawdown||0)-(b.excess_max_drawdown||0)">
        <template #default="{ row }">
          <span class="val-green">{{ N(row.excess_max_drawdown || 0).toFixed(2) }}%</span>
        </template>
      </el-table-column>
      <el-table-column prop="sharpe_ratio" label="夏普" width="70" align="right" sortable="custom">
        <template #default="{ row }">{{ row.sharpe_ratio != null ? N(row.sharpe_ratio).toFixed(2) : '--' }}</template>
      </el-table-column>
      <el-table-column label="超额夏普" width="85" align="right" sortable :sort-method="(a:any,b:any)=> (a.excess_sharpe_ratio||0)-(b.excess_sharpe_ratio||0)">
        <template #default="{ row }">{{ N(row.excess_sharpe_ratio || 0).toFixed(2) }}</template>
      </el-table-column>
      <el-table-column label="索提诺" width="75" align="right" sortable :sort-method="(a:any,b:any)=> (a.sortino_ratio||0)-(b.sortino_ratio||0)">
        <template #default="{ row }">{{ N(row.sortino_ratio || 0).toFixed(2) }}</template>
      </el-table-column>
      <el-table-column prop="win_rate" label="胜率" width="70" align="right" sortable="custom">
        <template #default="{ row }">{{ N(row.win_rate || 0).toFixed(1) }}%</template>
      </el-table-column>
      <el-table-column label="盈亏比" width="75" align="right" sortable :sort-method="(a:any,b:any)=> (a.profit_loss_ratio||0)-(b.profit_loss_ratio||0)">
        <template #default="{ row }">{{ N(row.profit_loss_ratio || 0).toFixed(2) }}</template>
      </el-table-column>
      <el-table-column prop="trade_count" label="交易数" width="70" align="right" sortable="custom" />
      <el-table-column prop="elapsed" label="回测耗时" width="90" align="right" show-overflow-tooltip />
      <el-table-column prop="completed_at" label="完成时间" width="160" sortable="custom" />
      <el-table-column label="操作" width="120" fixed="right">
        <template #default="{ row }">
          <el-button size="small" type="primary" text @click="viewDetail(row.id)">详情</el-button>
          <el-button size="small" type="danger" text @click="deleteSingle(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

      <!-- 移动端：卡片视图，只展示关键指标 + 操作 -->
      <template #mobile-card="{ row }">
        <div class="bt-card">
          <div class="bt-card-header">
            <el-link type="primary" class="bt-card-strategy" @click="$router.push('/algo/edit/' + row.strategy_id)">
              {{ row.strategy_name }}
            </el-link>
            <span class="bt-card-id">#{{ row.id }}</span>
          </div>
          <div class="bt-card-range">{{ row.start_date }} ~ {{ row.end_date }}</div>
          <div class="bt-card-metrics">
            <div class="m-cell">
              <span class="m-label">策略收益</span>
              <span class="m-value" :class="retCls(row.total_return)">{{ fmtRet(row.total_return) }}</span>
            </div>
            <div class="m-cell">
              <span class="m-label">年化</span>
              <span class="m-value" :class="retCls(row.annual_return)">{{ fmtRet(row.annual_return) }}</span>
            </div>
            <div class="m-cell">
              <span class="m-label">超额</span>
              <span class="m-value" :class="retCls(row.excess_return)">{{ fmtRet(row.excess_return) }}</span>
            </div>
            <div class="m-cell">
              <span class="m-label">最大回撤</span>
              <span class="m-value val-green">{{ row.max_drawdown != null ? N(row.max_drawdown).toFixed(2) + '%' : '--' }}</span>
            </div>
            <div class="m-cell">
              <span class="m-label">夏普</span>
              <span class="m-value">{{ row.sharpe_ratio != null ? N(row.sharpe_ratio).toFixed(2) : '--' }}</span>
            </div>
            <div class="m-cell">
              <span class="m-label">胜率</span>
              <span class="m-value">{{ N(row.win_rate || 0).toFixed(1) }}%</span>
            </div>
          </div>
          <div class="bt-card-actions">
            <span class="bt-card-time">{{ row.completed_at }}</span>
            <div>
              <el-button size="small" type="primary" text @click="viewDetail(row.id)">详情</el-button>
              <el-button size="small" type="danger" text @click="deleteSingle(row)">删除</el-button>
            </div>
          </div>
        </div>
      </template>
    </ResponsiveDataView>

    <div class="pagination-wrap" v-if="total > 0">
      <el-pagination
        v-model:current-page="currentPage"
        v-model:page-size="pageSize"
        :page-sizes="[10, 20, 50, 100]"
        :total="total"
        layout="total, sizes, prev, pager, next, jumper"
        @size-change="loadData"
        @current-change="loadData"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onActivated } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { DataAnalysis, Delete } from '@element-plus/icons-vue'
import { getPortfolioBacktestListPage, getStrategyCodeList, deleteBacktests } from '@/api/stock'
import { ElMessage, ElMessageBox } from 'element-plus'
import ResponsiveDataView from '@/components/ResponsiveDataView.vue'

const router = useRouter()
const route = useRoute()
const list = ref<any[]>([])
const strategies = ref<any[]>([])
const loading = ref(false)
const filterStrategyId = ref(0)
const selectedRows = ref<any[]>([])
const tableRef = ref()
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)
const sortBy = ref('total_return')
const sortOrder = ref('desc')

const N = Number
function formatCash(v: number) {
  return v >= 10000 ? (v / 10000).toFixed(0) + '万' : v.toFixed(0)
}
function fmtRet(v: number | undefined) {
  if (v == null) return '--'
  return `${v >= 0 ? '+' : ''}${N(v).toFixed(2)}%`
}
function retCls(v: number | undefined) {
  if (v == null || v === 0) return ''
  return v > 0 ? 'val-red' : 'val-green'
}

function onSelectionChange(rows: any[]) {
  selectedRows.value = rows
}

function onSortChange({ prop, order }: { prop: string; order: string | null }) {
  if (prop && order) {
    sortBy.value = prop
    sortOrder.value = order === 'ascending' ? 'asc' : 'desc'
  } else {
    sortBy.value = 'total_return'
    sortOrder.value = 'desc'
  }
  currentPage.value = 1
  loadData()
}

function onFilterChange() {
  currentPage.value = 1
  loadData()
}

function goCompare() {
  if (selectedRows.value.length < 2) return
  const ids = selectedRows.value.map((r: any) => r.id).join(',')
  router.push({ path: '/algo/backtest-compare', query: { ids } })
}

function viewDetail(id: number) {
  router.push('/algo/backtest-detail/' + id)
}

async function batchDelete() {
  if (selectedRows.value.length === 0) return
  try {
    await ElMessageBox.confirm(
      `确定删除选中的 ${selectedRows.value.length} 条回测记录？此操作不可恢复。`,
      '批量删除',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }
    )
  } catch { return }
  const ids = selectedRows.value.map((r: any) => r.id)
  try {
    const res = await deleteBacktests(ids) as any
    if (res?.code === 0) {
      ElMessage.success(`已删除 ${res.data?.deleted || ids.length} 条记录`)
      selectedRows.value = []
      loadData()
    } else {
      ElMessage.error(res?.msg || '删除失败')
    }
  } catch (e: any) {
    ElMessage.error(e?.message || '删除异常')
  }
}

async function deleteSingle(row: any) {
  try {
    await ElMessageBox.confirm(
      `确定删除回测 #${row.id}（${row.strategy_name}）？`,
      '删除回测',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }
    )
  } catch { return }
  try {
    const res = await deleteBacktests([row.id]) as any
    if (res?.code === 0) {
      ElMessage.success('已删除')
      loadData()
    } else {
      ElMessage.error(res?.msg || '删除失败')
    }
  } catch (e: any) {
    ElMessage.error(e?.message || '删除异常')
  }
}

async function loadData() {
  loading.value = true
  try {
    const params: any = { page: currentPage.value, page_size: pageSize.value, sort_by: sortBy.value, sort_order: sortOrder.value }
    if (filterStrategyId.value) params.strategy_id = filterStrategyId.value
    const res = await getPortfolioBacktestListPage(params) as any
    if (res?.code === 0) {
      list.value = res.data || []
      total.value = res.total || 0
    } else {
      list.value = []
      total.value = 0
    }
  } finally {
    loading.value = false
  }
}

async function loadStrategies() {
  try {
    const res = await getStrategyCodeList() as any
    const d = res?.data || res
    strategies.value = d?.strategies || (Array.isArray(d) ? d : [])
  } catch (_e) { /* ignore */ }
}

onMounted(() => {
  // 从路由 query 初始化策略筛选（从编辑页"回测历史"跳转时携带）
  const qsId = Number(route.query.strategy_id)
  if (qsId) filterStrategyId.value = qsId
  loadData(); loadStrategies()
})

// keep-alive 激活时刷新列表数据（从详情/对比页返回时获取最新数据）
onActivated(() => { loadData() })
</script>

<style scoped>
.bt-history { padding: 20px; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; flex-wrap: wrap; gap: 8px; }
.header-left { display: flex; align-items: center; gap: 12px; }
.header-left h2 { margin: 0; }
.header-right { display: flex; align-items: center; gap: 12px; }
.count-tag { font-variant-numeric: tabular-nums; }
.val-red { color: #f56c6c; font-weight: 600; }
.val-green { color: #67c23a; font-weight: 600; }
.pagination-wrap { margin-top: 16px; display: flex; justify-content: flex-end; }

/* PR-05/06 移动端卡片 */
.bt-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.bt-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.bt-card-strategy { font-size: 15px; font-weight: 600; }
.bt-card-id { color: #909399; font-size: 12px; }
.bt-card-range { color: #606266; font-size: 12px; }
.bt-card-metrics {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 6px 12px;
  margin-top: 4px;
}
.bt-card-metrics .m-cell {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
}
.bt-card-metrics .m-label { color: #909399; font-size: 11px; }
.bt-card-metrics .m-value { font-size: 14px; font-weight: 600; font-variant-numeric: tabular-nums; }
.bt-card-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 6px;
  border-top: 1px dashed var(--el-border-color-lighter, #ebeef5);
  padding-top: 6px;
}
.bt-card-time { color: #909399; font-size: 11px; }

@media (max-width: 575.98px) {
  .bt-history { padding: 12px; }
  .page-header { flex-direction: column; align-items: stretch; }
  .header-right { flex-wrap: wrap; }
  .header-right .el-select { width: 100% !important; }
  .pagination-wrap { justify-content: center; }
}
</style>
