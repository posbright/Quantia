<template>
  <div class="settings-page">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>实盘交易（Phase 7）</span>
          <div>
            <el-button size="small" @click="loadStatus">刷新状态</el-button>
            <el-button type="primary" size="small" :loading="executing" @click="onExecute" :disabled="!status?.enabled">
              触发执行（limit={{ execLimit }}）
            </el-button>
          </div>
        </div>
      </template>

      <el-alert :type="status?.enabled ? 'success' : 'info'" show-icon :closable="false" style="margin-bottom: 12px">
        <template v-if="!status?.enabled">
          <strong>实盘交易开关已关闭</strong>（默认状态）。需在服务器导出
          <code>QUANTIA_LIVE_TRADING_ENABLED=1</code> 与 <code>QUANTIA_LIVE_BROKER=&lt;name&gt;</code>
          后重启 web；当前 broker = <el-tag size="small">{{ status?.broker || 'dry_run' }}</el-tag>。
          关闭状态下点击「触发执行」会返回 503，不会有任何 DB / broker 调用。
        </template>
        <template v-else>
          <strong>实盘交易已启用（当前 broker：</strong>
          <el-tag size="small" :type="status?.broker === 'dry_run' ? 'warning' : 'success'">
            {{ status?.broker }}
          </el-tag>
          <strong>）</strong>。每次「触发执行」会扫描 status='approved' 的
          <router-link to="/settings/im-commands">IM 指令</router-link>
          并通过 broker 下单；二次风控失败 → expired/rejected，broker 异常 → failed，结果通过钉钉通知反馈。
          交易时段：<code>{{ status?.trading_hours || '未限制' }}</code>。
        </template>
      </el-alert>

      <el-form inline size="small" style="margin-bottom: 8px">
        <el-form-item label="单次执行 limit">
          <el-input-number v-model="execLimit" :min="1" :max="100" controls-position="right" />
        </el-form-item>
      </el-form>

      <el-card v-if="lastStats" shadow="never" style="margin-bottom:12px">
        <template #header>
          <strong>上次执行统计</strong>
          <el-tag v-if="lastStats.status === 'disabled'" type="info" size="small" style="margin-left:8px">disabled</el-tag>
          <el-tag v-else type="success" size="small" style="margin-left:8px">ok</el-tag>
          <span v-if="lastStats.broker" style="margin-left:8px;color:#666">broker={{ lastStats.broker }}</span>
        </template>
        <el-row :gutter="12">
          <el-col :span="4"><el-statistic title="processed" :value="lastStats.processed" /></el-col>
          <el-col :span="4"><el-statistic title="executed" :value="lastStats.executed" :value-style="{ color: '#67c23a' }" /></el-col>
          <el-col :span="4"><el-statistic title="rejected" :value="lastStats.rejected" :value-style="{ color: '#f56c6c' }" /></el-col>
          <el-col :span="4"><el-statistic title="expired" :value="lastStats.expired" :value-style="{ color: '#e6a23c' }" /></el-col>
          <el-col :span="4"><el-statistic title="failed" :value="lastStats.failed" :value-style="{ color: '#f56c6c' }" /></el-col>
        </el-row>

        <el-table v-if="lastStats.details?.length" :data="lastStats.details" size="small" border style="margin-top:12px">
          <el-table-column prop="id" label="command_id" width="120" />
          <el-table-column label="状态" width="120">
            <template #default="{ row }">
              <el-tag :type="detailType(row.status)" size="small">{{ row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="order_id" label="order_id" width="220" />
          <el-table-column prop="error" label="错误" min-width="220" show-overflow-tooltip />
        </el-table>
      </el-card>

      <el-descriptions :column="2" border size="small">
        <el-descriptions-item label="主开关 (env)">{{ status?.enabled_env }}</el-descriptions-item>
        <el-descriptions-item label="启用状态">
          <el-tag :type="status?.enabled ? 'success' : 'info'" size="small">
            {{ status?.enabled ? '已启用' : '关闭' }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="broker (env)">{{ status?.broker_env }}</el-descriptions-item>
        <el-descriptions-item label="broker 当前值">{{ status?.broker || '-' }}</el-descriptions-item>
        <el-descriptions-item label="交易时段" :span="2">{{ status?.trading_hours || '未限制（24x7 接受）' }}</el-descriptions-item>
      </el-descriptions>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { LiveStatus, LiveExecuteStats, getLiveStatus, executeLivePending } from '@/api/imLive'

const status = ref<LiveStatus | null>(null)
const execLimit = ref(20)
const executing = ref(false)
const lastStats = ref<LiveExecuteStats | null>(null)

const detailType = (s: string) => {
  if (s === 'executed') return 'success'
  if (s === 'expired') return 'warning'
  return 'danger'
}

const loadStatus = async () => {
  try {
    const r = await getLiveStatus()
    status.value = r.data || null
  } catch (e: any) {
    ElMessage.error(`加载失败: ${e?.message || e}`)
  }
}

const onExecute = async () => {
  executing.value = true
  try {
    const r = await executeLivePending(execLimit.value)
    lastStats.value = r.data
    if (r.data?.status === 'disabled') {
      ElMessage.warning('实盘交易开关未开启，未执行任何指令')
    } else {
      ElMessage.success(`执行完成：${r.data.executed} 成功 / ${r.data.rejected + r.data.expired + r.data.failed} 未通过`)
    }
  } catch (e: any) {
    const data = e?.response?.data
    if (data?.data) lastStats.value = data.data
    ElMessage.error(`触发失败: ${data?.error || e?.message || e}`)
  } finally {
    executing.value = false
  }
}

onMounted(loadStatus)
</script>

<style scoped>
.settings-page { padding: 12px; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
</style>
