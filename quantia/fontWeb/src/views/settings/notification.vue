<template>
  <div class="settings-page">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>钉钉/通知配置</span>
          <div>
            <el-button type="primary" size="small" @click="openCreate">新增配置</el-button>
            <el-button size="small" @click="loadList">刷新</el-button>
          </div>
        </div>
      </template>

      <el-alert type="info" show-icon :closable="false" style="margin-bottom: 12px">
        敏感字段（webhook URL、secret）不会保存到数据库，仅在 <code>webhook_env</code> /
        <code>secret_env</code> 中保存环境变量名。请在服务器 <code>.env</code> 中注入对应变量后
        点击「测试发送」。
      </el-alert>

      <el-table :data="rows" stripe border size="small">
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="paper_id" label="模拟盘 ID" width="100">
          <template #default="{ row }">{{ row.paper_id ?? '全局' }}</template>
        </el-table-column>
        <el-table-column prop="channel" label="渠道" width="100" />
        <el-table-column prop="event_type" label="事件类型" width="140" />
        <el-table-column label="启用" width="80">
          <template #default="{ row }">
            <el-tag :type="row.enabled ? 'success' : 'info'" size="small">
              {{ row.enabled ? '启用' : '关闭' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="webhook_env" label="webhook_env" />
        <el-table-column label="webhook 已配置" width="120">
          <template #default="{ row }">
            <el-tag :type="row.webhook_is_configured ? 'success' : 'danger'" size="small">
              {{ row.webhook_is_configured ? '已注入' : '未注入' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="config_version" label="版本" width="80" />
        <el-table-column label="操作" width="240">
          <template #default="{ row }">
            <el-button size="small" @click="openEdit(row)">编辑</el-button>
            <el-button size="small" type="primary" @click="onTestSend(row)">测试发送</el-button>
            <el-button size="small" type="danger" @click="onDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" :title="form.id ? '编辑通知配置' : '新增通知配置'" width="min(640px, 92vw)">
      <el-form :model="form" label-width="120px">
        <el-form-item label="模拟盘 ID">
          <el-input v-model.number="form.paper_id" placeholder="留空表示全局生效" clearable />
        </el-form-item>
        <el-form-item label="渠道">
          <el-select v-model="form.channel">
            <el-option label="钉钉 (dingtalk)" value="dingtalk" />
            <el-option label="企业微信 (wecom)" value="wecom" disabled />
          </el-select>
        </el-form-item>
        <el-form-item label="事件类型">
          <el-select v-model="form.event_type">
            <el-option label="模拟交易成交 (paper_trade)" value="paper_trade" />
            <el-option label="运行失败 (run_failed)" value="run_failed" />
            <el-option label="每日汇总 (run_summary)" value="run_summary" />
            <el-option label="风险提醒 (risk_alert)" value="risk_alert" />
          </el-select>
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.enabled" />
        </el-form-item>
        <el-form-item label="webhook 环境变量名">
          <el-input v-model="form.webhook_env" placeholder="例如 QUANTIA_DINGTALK_WEBHOOK" />
        </el-form-item>
        <el-form-item label="secret 环境变量名">
          <el-input v-model="form.secret_env" placeholder="例如 QUANTIA_DINGTALK_SECRET" />
        </el-form-item>
        <el-form-item label="摘要字段">
          <el-input
            v-model="summaryText" type="textarea" :rows="3"
            placeholder='JSON，例如 {"fields":["direction","code","ai_score","value"]}'
          />
        </el-form-item>
        <el-form-item label="详情上限">
          <el-input
            v-model="detailText" type="textarea" :rows="3"
            placeholder='JSON，例如 {"max_rules":5,"show_ai_evidence":true}'
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onSave">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  listNotificationConfigs, saveNotificationConfig, deleteNotificationConfig,
  testSendNotification, NotificationConfig
} from '@/api/settings'

const rows = ref<NotificationConfig[]>([])
const dialogVisible = ref(false)
const saving = ref(false)
const summaryText = ref('')
const detailText = ref('')

const emptyForm = (): NotificationConfig => ({
  channel: 'dingtalk', event_type: 'paper_trade', enabled: true,
  webhook_env: 'QUANTIA_DINGTALK_WEBHOOK', secret_env: 'QUANTIA_DINGTALK_SECRET',
})
const form = ref<NotificationConfig>(emptyForm())

const loadList = async () => {
  const res = await listNotificationConfigs()
  rows.value = res?.data || []
}

const openCreate = () => {
  form.value = emptyForm()
  summaryText.value = ''
  detailText.value = ''
  dialogVisible.value = true
}

const openEdit = (row: NotificationConfig) => {
  form.value = { ...row }
  summaryText.value = row.summary_config ? JSON.stringify(row.summary_config, null, 2) : ''
  detailText.value = row.detail_config ? JSON.stringify(row.detail_config, null, 2) : ''
  dialogVisible.value = true
}

const parseJson = (text: string) => {
  if (!text || !text.trim()) return {}
  try { return JSON.parse(text) } catch { ElMessage.error('JSON 格式错误'); throw new Error('json') }
}

const onSave = async () => {
  saving.value = true
  try {
    const payload: NotificationConfig = {
      ...form.value,
      summary_config: parseJson(summaryText.value),
      detail_config: parseJson(detailText.value),
    }
    const res = await saveNotificationConfig(payload)
    if (!res.ok) { ElMessage.error(res.error || '保存失败'); return }
    ElMessage.success('保存成功，配置版本：' + res.data.config_version)
    dialogVisible.value = false
    await loadList()
  } catch (e: any) {
    if (e?.message !== 'json') ElMessage.error(e?.message || '保存失败')
  } finally {
    saving.value = false
  }
}

const onDelete = async (row: NotificationConfig) => {
  if (!row.id) return
  await ElMessageBox.confirm(`确定删除配置 #${row.id}？`, '提示', { type: 'warning' })
  await deleteNotificationConfig(row.id)
  ElMessage.success('已删除')
  await loadList()
}

const onTestSend = async (row: NotificationConfig) => {
  const res = await testSendNotification({ paper_id: row.paper_id, channel: row.channel })
  if (res.ok) ElMessage.success('测试消息已发送')
  else ElMessage.warning(res.data?.error || '测试发送被跳过')
}

onMounted(loadList)
</script>

<style scoped>
.settings-page { padding: 16px }
.card-header { display: flex; justify-content: space-between; align-items: center }
</style>
