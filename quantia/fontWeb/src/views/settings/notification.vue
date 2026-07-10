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

      <el-table v-if="!isMobile" :data="rows" stripe border size="small">
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

      <!-- 移动端卡片视图 -->
      <div v-if="isMobile" class="nc-card-list">
        <el-empty v-if="rows.length === 0" description="暂无配置" :image-size="60" />
        <div v-for="row in rows" :key="row.id" class="nc-card">
          <div class="nc-card-head">
            <span class="nc-card-title">#{{ row.id }} {{ row.event_type }}</span>
            <el-tag :type="row.enabled ? 'success' : 'info'" size="small">
              {{ row.enabled ? '启用' : '关闭' }}
            </el-tag>
          </div>
          <div class="nc-card-body">
            <div class="nc-field"><span class="nc-lbl">模拟盘 ID</span><span>{{ row.paper_id ?? '全局' }}</span></div>
            <div class="nc-field"><span class="nc-lbl">渠道</span><span>{{ row.channel }}</span></div>
            <div class="nc-field"><span class="nc-lbl">版本</span><span>{{ row.config_version }}</span></div>
            <div class="nc-field">
              <span class="nc-lbl">webhook</span>
              <el-tag :type="row.webhook_is_configured ? 'success' : 'danger'" size="small">{{ row.webhook_is_configured ? '已注入' : '未注入' }}</el-tag>
            </div>
            <div class="nc-field nc-field-full"><span class="nc-lbl">webhook_env</span><span class="nc-val-mono">{{ row.webhook_env }}</span></div>
          </div>
          <div class="nc-card-ops">
            <span class="nc-op" @click="openEdit(row)">编辑</span>
            <span class="nc-op-sep">|</span>
            <span class="nc-op" @click="onTestSend(row)">测试发送</span>
            <span class="nc-op-sep">|</span>
            <span class="nc-op nc-op-danger" @click="onDelete(row)">删除</span>
          </div>
        </div>
      </div>
    </el-card>

    <el-dialog v-model="dialogVisible" :title="form.id ? '编辑通知配置' : '新增通知配置'" :fullscreen="isMobile" :width="isMobile ? '100%' : 'min(640px, 92vw)'">
      <el-form :model="form" :label-width="isMobile ? '100px' : '120px'">
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
            <el-option label="每日基金精选榜 (fund_daily_pick)" value="fund_daily_pick" />
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
import { useResponsive } from '@/composables/useResponsive'

const { isMobile } = useResponsive()
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

/* ─── 移动端卡片视图 ─── */
.nc-card-list { display: flex; flex-direction: column; gap: 10px; }
.nc-card { background: #fff; border: 1px solid #ebeef5; border-radius: 6px; padding: 10px 12px; }
.nc-card-head { display: flex; justify-content: space-between; align-items: center; padding-bottom: 8px; border-bottom: 1px dashed #ebeef5; }
.nc-card-title { font-weight: 600; color: #303133; font-size: 14px; }
.nc-card-body { display: grid; grid-template-columns: 1fr 1fr; gap: 6px 12px; font-size: 13px; padding: 8px 0; }
.nc-field { display: flex; justify-content: space-between; align-items: center; }
.nc-field-full { grid-column: 1 / -1; }
.nc-val-mono { font-family: monospace; font-size: 12px; word-break: break-all; }
.nc-lbl { color: #909399; }
.nc-card-ops { display: flex; justify-content: flex-end; align-items: center; gap: 8px; padding-top: 8px; border-top: 1px dashed #ebeef5; }
.nc-op { color: #409eff; cursor: pointer; font-size: 13px; }
.nc-op-danger { color: #f56c6c; }
.nc-op-sep { color: #dcdfe6; }

@media (max-width: 767.98px) {
  .settings-page { padding: 10px }
  .card-header { flex-wrap: wrap; gap: 8px; }
}
</style>
