<template>
  <div class="settings-page">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>IM 指令记录</span>
          <div>
            <el-select v-model="filterStatus" size="small" clearable placeholder="状态过滤" style="width:160px;margin-right:8px" @change="loadList">
              <el-option v-for="s in STATUSES" :key="s" :label="s" :value="s" />
            </el-select>
            <el-input-number v-model="filterPaperId" size="small" controls-position="right" :min="0" placeholder="paper_id" style="width:120px;margin-right:8px" />
            <el-button size="small" @click="loadList">刷新</el-button>
          </div>
        </div>
      </template>

      <el-alert type="info" show-icon :closable="false" style="margin-bottom: 12px">
        所有钉钉回调（含签名失败外的失败/拒绝/未授权）都会落库，便于审计。请配合
        <router-link to="/settings/im-operator">操作人白名单</router-link> 与
        <router-link to="/settings/live-trading">实盘交易开关</router-link> 一起使用。
      </el-alert>

      <el-table :data="rows" v-if="!isMobile" stripe border size="small">
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="created_at" label="时间" width="170" />
        <el-table-column prop="source_channel" label="渠道" width="80" />
        <el-table-column prop="operator_id" label="操作人" width="160" show-overflow-tooltip />
        <el-table-column prop="command_type" label="指令" width="120" />
        <el-table-column prop="code" label="股票" width="100" />
        <el-table-column prop="direction" label="方向" width="70" />
        <el-table-column label="数量" width="90">
          <template #default="{ row }">{{ row.amount ?? '-' }}</template>
        </el-table-column>
        <el-table-column label="金额" width="110">
          <template #default="{ row }">{{ row.value != null ? '¥' + Number(row.value).toFixed(2) : '-' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="signal_id" label="signal" width="80" />
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button size="small" @click="openDetail(row)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 移动端卡片视图 -->
      <div v-if="isMobile" class="imc-card-list">
        <div v-for="row in rows" :key="row.id" class="imc-card">
          <div class="imc-card-head">
            <span class="imc-id">#{{ row.id }}</span>
            <span class="imc-cmd">{{ row.command_type }}</span>
            <span v-if="row.code" class="imc-code">{{ row.code }}</span>
            <el-tag :type="statusType(row.status)" size="small">{{ row.status }}</el-tag>
          </div>
          <div class="imc-card-body">
            <div class="imc-field">
              <span class="imc-lbl">渠道</span>
              <span>{{ row.source_channel || '—' }}</span>
            </div>
            <div class="imc-field">
              <span class="imc-lbl">方向</span>
              <span>{{ row.direction || '—' }}</span>
            </div>
            <div class="imc-field">
              <span class="imc-lbl">数量</span>
              <span>{{ row.amount ?? '—' }}</span>
            </div>
            <div class="imc-field">
              <span class="imc-lbl">金额</span>
              <span>{{ row.value != null ? '¥' + Number(row.value).toFixed(2) : '—' }}</span>
            </div>
            <div class="imc-field imc-field-full">
              <span class="imc-lbl">操作人</span>
              <span class="imc-operator">{{ row.operator_id || '—' }}</span>
            </div>
            <div class="imc-field imc-field-full">
              <span class="imc-lbl">时间</span>
              <span>{{ row.created_at }}</span>
            </div>
          </div>
          <div class="imc-card-ops">
            <a class="imc-op" @click="openDetail(row)">详情</a>
          </div>
        </div>
        <el-empty v-if="rows.length === 0" description="暂无指令记录" />
      </div>

      <div class="pagination">
        <el-button size="small" :disabled="offset === 0" @click="prevPage">上一页</el-button>
        <span style="margin:0 12px">offset {{ offset }} | limit {{ limit }}</span>
        <el-button size="small" :disabled="rows.length < limit" @click="nextPage">下一页</el-button>
      </div>
    </el-card>

    <el-dialog v-model="dialogVisible" :title="`指令详情 #${current?.id ?? ''}`" :fullscreen="isMobile" :width="isMobile ? '100%' : 'min(780px, 92vw)'">
      <el-descriptions v-if="current" :column="isMobile ? 1 : 2" border size="small">
        <el-descriptions-item label="ID">{{ current.id }}</el-descriptions-item>
        <el-descriptions-item label="状态">
          <el-tag :type="statusType(current.status)" size="small">{{ current.status }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="渠道">{{ current.source_channel }}</el-descriptions-item>
        <el-descriptions-item label="message_id">{{ current.source_message_id || '-' }}</el-descriptions-item>
        <el-descriptions-item label="操作人">{{ current.operator_name }} ({{ current.operator_id }})</el-descriptions-item>
        <el-descriptions-item label="指令类型">{{ current.command_type }}</el-descriptions-item>
        <el-descriptions-item label="paper_id">{{ current.paper_id ?? '-' }}</el-descriptions-item>
        <el-descriptions-item label="signal_id">{{ current.signal_id ?? '-' }}</el-descriptions-item>
        <el-descriptions-item label="股票">{{ current.code || '-' }}</el-descriptions-item>
        <el-descriptions-item label="方向">{{ current.direction || '-' }}</el-descriptions-item>
        <el-descriptions-item label="数量">{{ current.amount ?? '-' }}</el-descriptions-item>
        <el-descriptions-item label="金额">{{ current.value ?? '-' }}</el-descriptions-item>
        <el-descriptions-item label="限价">{{ current.price_limit ?? '-' }}</el-descriptions-item>
        <el-descriptions-item label="过期时间">{{ current.expire_at || '-' }}</el-descriptions-item>
        <el-descriptions-item label="批准时间">{{ current.approved_at || '-' }}</el-descriptions-item>
        <el-descriptions-item label="执行时间">{{ current.executed_at || '-' }}</el-descriptions-item>
      </el-descriptions>

      <el-divider>风控检查</el-divider>
      <pre class="json-block">{{ formatJson(current?.risk_check) }}</pre>

      <el-divider>原始回调 payload</el-divider>
      <pre class="json-block">{{ formatJson(current?.request_payload) }}</pre>

      <el-divider v-if="current?.execution_result">执行结果（Phase 7）</el-divider>
      <pre v-if="current?.execution_result" class="json-block">{{ formatJson(current?.execution_result) }}</pre>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { IMCommand, listIMCommands, getIMCommand } from '@/api/imLive'
import { useResponsive } from '@/composables/useResponsive'

const { isMobile } = useResponsive()
const STATUSES = ['pending', 'approved', 'rejected', 'expired', 'executed', 'failed', 'unauthorized', 'invalid', 'duplicate']

const rows = ref<IMCommand[]>([])
const filterStatus = ref<string>('')
const filterPaperId = ref<number | undefined>(undefined)
const limit = ref(50)
const offset = ref(0)

const dialogVisible = ref(false)
const current = ref<IMCommand | null>(null)

const statusType = (s: string) => {
  if (s === 'executed' || s === 'approved') return 'success'
  if (s === 'rejected' || s === 'failed' || s === 'unauthorized' || s === 'invalid') return 'danger'
  if (s === 'expired' || s === 'duplicate') return 'warning'
  return 'info'
}

const formatJson = (v: any) => {
  if (v == null) return ''
  try { return JSON.stringify(v, null, 2) } catch { return String(v) }
}

const loadList = async () => {
  try {
    const r = await listIMCommands({
      status: filterStatus.value || undefined,
      paper_id: filterPaperId.value,
      limit: limit.value,
      offset: offset.value,
    })
    rows.value = r.data || []
  } catch (e: any) {
    ElMessage.error(`加载失败: ${e?.message || e}`)
  }
}

const prevPage = () => { offset.value = Math.max(0, offset.value - limit.value); loadList() }
const nextPage = () => { offset.value += limit.value; loadList() }

const openDetail = async (row: IMCommand) => {
  try {
    const r = await getIMCommand(row.id)
    current.value = r.data
    dialogVisible.value = true
  } catch (e: any) {
    ElMessage.error(`加载详情失败: ${e?.message || e}`)
  }
}

onMounted(loadList)
</script>

<style scoped>
.settings-page { padding: 12px; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.pagination { margin-top: 12px; text-align: right; }
.json-block {
  background: #f7f7f9; padding: 10px; border-radius: 4px;
  font-size: 12px; max-height: 280px; overflow: auto;
  font-family: Consolas, monospace; white-space: pre-wrap;
}

/* 移动端卡片视图 */
.imc-card-list { display: flex; flex-direction: column; gap: 10px; }
.imc-card {
  background: #fff; border: 1px solid #ebeef5; border-radius: 6px; padding: 10px 12px;
}
.imc-card-head {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  border-bottom: 1px dashed #ebeef5; padding-bottom: 6px; margin-bottom: 8px;
}
.imc-id { color: #909399; font-size: 12px; }
.imc-cmd { font-weight: 600; font-size: 14px; color: #303133; }
.imc-code { color: #409eff; font-size: 13px; }
.imc-card-body {
  display: grid; grid-template-columns: 1fr 1fr; gap: 6px 12px; font-size: 13px;
}
.imc-field { display: flex; justify-content: space-between; align-items: center; gap: 8px; min-width: 0; }
.imc-field-full { grid-column: 1 / -1; }
.imc-lbl { color: #909399; white-space: nowrap; }
.imc-operator { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.imc-card-ops {
  margin-top: 10px; padding-top: 8px; border-top: 1px dashed #ebeef5;
  display: flex; justify-content: flex-end; font-size: 13px;
}
.imc-op { color: #409eff; cursor: pointer; }
.imc-op:hover { text-decoration: underline; }

@media (max-width: 767.98px) {
  .card-header { flex-direction: column; align-items: flex-start; gap: 8px; }
  .card-header > div { display: flex; flex-wrap: wrap; gap: 8px; width: 100%; }
  .card-header :deep(.el-select),
  .card-header :deep(.el-input-number) {
    width: 100% !important;
    margin-right: 0 !important;
  }
}
</style>
