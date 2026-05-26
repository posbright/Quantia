<template>
  <div class="algo-list">
    <!-- 面包屑导航 -->
    <div class="breadcrumb" v-if="currentFolderId > 0">
      <el-button text size="small" @click="exitFolder">
        <el-icon><ArrowLeft /></el-icon> 返回根目录
      </el-button>
      <span class="folder-path">/ {{ currentFolderName }}</span>
    </div>

    <!-- 顶部工具栏 -->
    <div class="toolbar">
      <el-dropdown @command="onCreateStrategy" trigger="click">
        <el-button type="primary">+ 新建策略</el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="stock">股票策略</el-dropdown-item>
            <el-dropdown-item command="multi_factor">多因子策略</el-dropdown-item>
            <el-dropdown-item command="portfolio">组合策略</el-dropdown-item>
            <el-dropdown-item command="blank">空白模版</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
      <el-button @click="onCreateFolder"><el-icon><FolderAdd /></el-icon> 新建文件夹</el-button>
      <el-button :disabled="selectedRows.length === 0" @click="onRenameSelected">重命名</el-button>
      <el-dropdown :disabled="selectedStrategyIds.length === 0" @command="onMoveToFolder" trigger="click">
        <el-button :disabled="selectedStrategyIds.length === 0">移动到</el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item :command="0">根目录</el-dropdown-item>
            <el-dropdown-item v-for="f in allFolders" :key="f.id" :command="f.id">{{ f.name }}</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
      <el-popconfirm title="确定删除选中的项目？" @confirm="onBatchDelete" :disabled="selectedRows.length === 0">
        <template #reference>
          <el-button :disabled="selectedRows.length === 0" type="danger" plain>
            <el-icon><Delete /></el-icon> 删除
          </el-button>
        </template>
      </el-popconfirm>
      <el-button @click="seedTemplateStrategies" :loading="importing" style="margin-left: auto;">导入示例策略</el-button>
    </div>

    <!-- 表格 -->
    <el-table ref="tableRef" :data="tableData" v-loading="loading" @selection-change="onSelectionChange"
              @row-click="onTableRowClick" @row-dblclick="onTableRowDblClick"
              stripe row-key="rowKey" style="width: 100%;">
      <el-table-column type="selection" width="40" />
      <el-table-column label="" min-width="280">
        <template #default="{ row }">
          <div class="name-cell">
            <el-icon :size="18" v-if="row.type === 'folder'" color="#e6a23c"><Folder /></el-icon>
            <el-icon :size="18" v-else color="#409eff"><Document /></el-icon>
            <!-- 行内编辑名称 -->
            <el-input v-if="editingRowId === row.rowKey" v-model="editingName" size="small"
                      style="width: 220px;" @blur="finishRename(row)" @keyup.enter="finishRename(row)"
                      ref="renameInput" />
            <span v-else class="name-text">{{ row.name }}</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="分类" width="100" align="center">
        <template #default="{ row }">
          <el-tag v-if="row.type === 'strategy'" size="small" type="info" effect="plain">
            {{ categoryLabel(row.category) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="最后修改时间" width="180" align="center">
        <template #default="{ row }">{{ row.updated_at || row.created_at || '' }}</template>
      </el-table-column>
      <el-table-column label="历史编译运行" width="120" align="center">
        <template #default="{ row }">
          <span v-if="row.type === 'strategy'">{{ row.compile_count || 0 }}</span>
        </template>
      </el-table-column>
      <el-table-column label="历史回测" width="100" align="center">
        <template #default="{ row }">
          <span v-if="row.type === 'strategy'">{{ row.backtest_count || 0 }}</span>
        </template>
      </el-table-column>
    </el-table>

    <el-empty v-if="!loading && tableData.length === 0"
              description="还没有策略，点击「新建策略」或导入示例策略">
      <div style="display: flex; gap: 12px;">
        <el-button type="primary" @click="onCreateStrategy('stock')">新建股票策略</el-button>
        <el-button @click="seedTemplateStrategies" :loading="importing">导入示例策略</el-button>
      </div>
    </el-empty>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Folder, FolderAdd, Document, Delete, ArrowLeft } from '@element-plus/icons-vue'
import {
  getStrategyCodeList, saveStrategyCode,
  createFolder, renameStrategy, renameFolder, moveStrategy,
  batchDeleteStrategy, getStrategyTemplates, syncStrategyTemplates, deleteFolder,
} from '@/api/stock'

const router = useRouter()
const allStrategies = ref<any[]>([])
const allFolders = ref<any[]>([])
const loading = ref(false)
const selectedRows = ref<any[]>([])
const currentFolderId = ref(0)
const currentFolderName = ref('')
const editingRowId = ref<string | null>(null)
const editingName = ref('')
const importing = ref(false)
const tableRef = ref<any>(null)

const CATEGORY_MAP: Record<string, string> = {
  stock: 'Code', multi_factor: 'Factor', portfolio: 'Portfolio', blank: 'Code'
}
const CATEGORY_TEMPLATES: Record<string, string> = {
  stock: `# 股票策略\ndef initialize(context):\n    context.security = '000001'\n\ndef handle_data(context, data):\n    security = context.security\n    price = data[security].close\n    ma5 = history(security, 5, 'close')\n    if len(ma5) < 5:\n        return\n    ma_val = ma5.mean()\n    if price > ma_val * 1.01 and security not in context.portfolio.positions:\n        order_value(security, context.portfolio.available_cash * 0.9)\n    elif price < ma_val * 0.99 and security in context.portfolio.positions:\n        order_target(security, 0)\n`,
  multi_factor: `# 多因子策略\ndef initialize(context):\n    context.stocks = ['600519', '000858', '601318', '600036', '300750']\n    context.rebalance_days = 0\n\ndef handle_data(context, data):\n    context.rebalance_days += 1\n    if context.rebalance_days % 20 != 1:\n        return\n    target = context.portfolio.total_value / len(context.stocks)\n    for code in context.stocks:\n        order_target_value(code, target)\n`,
  portfolio: `# 组合策略\ndef initialize(context):\n    context.stocks = ['000001', '600519', '601318']\n\ndef handle_data(context, data):\n    momentum = {}\n    for code in context.stocks:\n        h = history(code, 20, 'close')\n        if len(h) >= 20 and h.iloc[0] > 0:\n            momentum[code] = h.iloc[-1] / h.iloc[0] - 1\n    if not momentum:\n        return\n    best = max(momentum, key=momentum.get)\n    for code in list(context.portfolio.positions.keys()):\n        if code != best:\n            order_target(code, 0)\n    if best not in context.portfolio.positions:\n        order_value(best, context.portfolio.available_cash * 0.9)\n`,
  blank: `def initialize(context):\n    pass\n\ndef handle_data(context, data):\n    pass\n`,
}

const selectedStrategyIds = computed(() => selectedRows.value.filter(r => r.type === 'strategy').map(r => r.id))
const selectedFolderIds = computed(() => selectedRows.value.filter(r => r.type === 'folder').map(r => r.id))

// 当前文件夹下的策略（根据 folder_id 过滤）
const tableData = computed(() => {
  const result: any[] = []
  if (currentFolderId.value === 0) {
    // 根目录：显示文件夹 + 根目录下的策略
    for (const f of allFolders.value) {
      result.push({ ...f, rowKey: `folder-${f.id}` })
    }
    for (const s of allStrategies.value.filter(s => !s.folder_id || s.folder_id === 0)) {
      result.push({ ...s, rowKey: `strategy-${s.id}` })
    }
  } else {
    // 文件夹内：只显示属于该文件夹的策略
    for (const s of allStrategies.value.filter(s => s.folder_id === currentFolderId.value)) {
      result.push({ ...s, rowKey: `strategy-${s.id}` })
    }
  }
  return result
})

function categoryLabel(cat: string) { return CATEGORY_MAP[cat] || 'Code' }
function onSelectionChange(rows: any[]) { selectedRows.value = rows }

// 单击/双击 区分：使用延迟模式
let clickTimer: ReturnType<typeof setTimeout> | null = null

function onTableRowClick(row: any, column: any, _event: Event) {
  if (column?.type === 'selection') return
  if (editingRowId.value) return
  // 延迟200ms执行单击，给双击留时间
  if (clickTimer) clearTimeout(clickTimer)
  clickTimer = setTimeout(() => {
    clickTimer = null
    doRowClick(row)
  }, 200)
}

function onTableRowDblClick(row: any, column: any, _event: Event) {
  if (column?.type === 'selection') return
  // 取消延迟的单击
  if (clickTimer) { clearTimeout(clickTimer); clickTimer = null }
  doRowDblClick(row)
}

function doRowClick(row: any) {
  if (editingRowId.value) return
  if (row.type === 'folder') {
    currentFolderId.value = row.id
    currentFolderName.value = row.name
    console.log('[list] Enter folder:', row.id, row.name)
    return
  }
  router.push('/algo/edit/' + row.id)
}

async function doRowDblClick(row: any) {
  editingRowId.value = row.rowKey
  editingName.value = row.name
  await nextTick()
}

function exitFolder() {
  currentFolderId.value = 0
  currentFolderName.value = ''
}

async function finishRename(row: any) {
  const newName = editingName.value.trim()
  editingRowId.value = null
  if (!newName || newName === row.name) return
  try {
    if (row.type === 'folder') {
      await renameFolder(row.id, newName)
    } else {
      await renameStrategy(row.id, newName)
    }
    ElMessage.success('已重命名')
    loadData()
  } catch (e) {
    ElMessage.error('重命名失败')
  }
}

async function loadData() {
  loading.value = true
  try {
    const res = await getStrategyCodeList() as any
    const d = res?.data || res
    if (d?.strategies) {
      allStrategies.value = d.strategies
      allFolders.value = d.folders || []
    } else if (Array.isArray(d)) {
      allStrategies.value = d
      allFolders.value = []
    }
    console.log('[list] loadData:', allStrategies.value.length, 'strategies,',
      allFolders.value.length, 'folders, currentFolder=', currentFolderId.value,
      'root strategies:', allStrategies.value.filter(s => !s.folder_id || s.folder_id === 0).length)
  } finally {
    loading.value = false
  }
}

async function onCreateStrategy(category: string) {
  const n = allStrategies.value.length
  const name = '\u4e00\u4e2a\u7b80\u5355\u7684\u7b56\u7565-' + (n + 1)
  try {
    const res = await saveStrategyCode({
      name, code: CATEGORY_TEMPLATES[category] || CATEGORY_TEMPLATES.blank,
      category, folder_id: currentFolderId.value,
    }) as any
    if ((res?.code ?? res?.data?.code) === 0) {
      ElMessage.success('\u7b56\u7565\u5df2\u521b\u5efa')
      await loadData()
    } else { ElMessage.error(res?.msg || '\u521b\u5efa\u5931\u8d25') }
  } catch (e) { ElMessage.error('\u521b\u5efa\u5931\u8d25') }
}

async function seedTemplateStrategies() {
  if (importing.value) return
  importing.value = true
  try {
    const syncRes = await syncStrategyTemplates() as any
    if ((syncRes?.code ?? syncRes?.data?.code) === 0) {
      const msg = syncRes?.msg || syncRes?.data?.msg || '模板已同步'
      ElMessage.success(msg)
      await loadData()
      return
    }

    await loadData()
    const res = await getStrategyTemplates() as any
    const list = Array.isArray(res?.data) ? res.data : (Array.isArray(res) ? res : [])
    if (!list.length) { ElMessage.warning('\u65e0\u53ef\u7528\u6a21\u677f'); return }
    const existingNames = new Set(allStrategies.value.map((s: any) => s.name))
    let c = 0
    for (const t of list) {
      if (existingNames.has(t.name)) continue
      const r = await saveStrategyCode({ name: t.name, code: t.code, category: t.category || 'stock' }) as any
      if ((r?.code ?? r?.data?.code) === 0) {
        c++
        existingNames.add(t.name)
      }
    }
    if (c === 0) { ElMessage.info('\u6240\u6709\u6a21\u677f\u5df2\u5bfc\u5165'); return }
    ElMessage.success('\u5df2\u5bfc\u5165 ' + c + ' \u4e2a\u793a\u4f8b\u7b56\u7565')
    await loadData()
  } catch (e) { ElMessage.error('\u5bfc\u5165\u5931\u8d25') } finally { importing.value = false }
}

async function onCreateFolder() {
  const { value: name } = await ElMessageBox.prompt('\u8bf7\u8f93\u5165\u6587\u4ef6\u5939\u540d\u79f0', '\u65b0\u5efa\u6587\u4ef6\u5939', {
    confirmButtonText: '\u521b\u5efa', inputValue: '\u65b0\u6587\u4ef6\u5939', inputPattern: /\S+/,
  }).catch(() => ({ value: '' }))
  if (!name) return
  try { await createFolder(name); ElMessage.success('\u6587\u4ef6\u5939\u5df2\u521b\u5efa'); loadData() }
  catch (e) { ElMessage.error('\u521b\u5efa\u5931\u8d25') }
}

async function onRenameSelected() {
  if (selectedRows.value.length !== 1) { ElMessage.warning('\u8bf7\u9009\u62e9\u4e00\u4e2a\u9879\u76ee'); return }
  const item = selectedRows.value[0]
  const { value: name } = await ElMessageBox.prompt('\u65b0\u540d\u79f0', '\u91cd\u547d\u540d', {
    confirmButtonText: '\u786e\u5b9a', inputValue: item.name, inputPattern: /\S+/,
  }).catch(() => ({ value: '' }))
  if (!name) return
  try {
    if (item.type === 'folder') await renameFolder(item.id, name)
    else await renameStrategy(item.id, name)
    ElMessage.success('\u5df2\u91cd\u547d\u540d'); loadData()
  } catch (e) { ElMessage.error('\u91cd\u547d\u540d\u5931\u8d25') }
}

async function onMoveToFolder(folderId: number) {
  if (selectedStrategyIds.value.length === 0) return
  try {
    const res = await moveStrategy(selectedStrategyIds.value, folderId) as any
    const code = res?.code ?? res?.data?.code
    if (code !== 0) {
      ElMessage.error(res?.msg || res?.data?.msg || '移动失败')
      return
    }
    ElMessage.success('已移动')
    selectedRows.value = []
    if (tableRef.value) tableRef.value.clearSelection()
    await loadData()
  } catch (e) {
    console.error('moveStrategy error:', e)
    ElMessage.error('移动失败')
  }
}

async function onBatchDelete() {
  try {
    if (selectedStrategyIds.value.length > 0) await batchDeleteStrategy(selectedStrategyIds.value)
    for (const fid of selectedFolderIds.value) await deleteFolder(fid)
    ElMessage.success('\u5df2\u5220\u9664')
    loadData()
  } catch (e) { ElMessage.error('\u5220\u9664\u5931\u8d25') }
}

onMounted(loadData)
</script>

<style scoped>
.algo-list { padding: 20px; }
.breadcrumb { margin-bottom: 8px; display: flex; align-items: center; gap: 8px; }
.folder-path { font-size: 14px; color: #606266; font-weight: 500; }
.toolbar { display: flex; gap: 8px; margin-bottom: 16px; padding: 12px 0; border-bottom: 1px solid #ebeef5; }
.name-cell { display: flex; align-items: center; gap: 8px; cursor: pointer; width: 100%; min-height: 32px; }
.name-cell:hover .name-text { color: #409eff; }
.name-text { color: #303133; font-size: 14px; transition: color 0.15s; }

/* 移动端适配（PR-10） */
@media (max-width: 768px) {
  .algo-list { padding: 10px 8px; }
  .toolbar { flex-wrap: wrap; gap: 6px; padding: 8px 0; }
  .toolbar .el-button,
  .toolbar .el-dropdown { font-size: 12px; }
  .toolbar > * { flex-shrink: 0; }
  :deep(.el-table) { font-size: 12px; }
  :deep(.el-table .cell) { padding: 0 6px; }
}
</style>
