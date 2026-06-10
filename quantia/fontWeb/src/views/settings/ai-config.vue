<template>
  <div class="settings-page">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>AI 研判配置</span>
          <div>
            <el-button type="primary" size="small" @click="openCreate">新增配置</el-button>
            <el-button size="small" @click="loadList">刷新</el-button>
          </div>
        </div>
      </template>

      <el-alert type="warning" show-icon :closable="false" style="margin-bottom: 12px">
        <strong>安全提示：</strong> API Key 不会保存在数据库或前端响应中，仅通过
        <code>api_key_ref</code> 引用环境变量名。请在服务器 <code>.env</code> 中设置对应变量
        （默认 <code>QUANTIA_AI_API_KEY</code>）。Gate 默认关闭，开启前请在回测/模拟盘中验证。
      </el-alert>

      <el-table v-if="!isMobile" :data="rows" stripe border size="small">
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="name" label="名称" />
        <el-table-column prop="source_type" label="来源" width="90" />
        <el-table-column prop="provider" label="Provider" width="140" />
        <el-table-column prop="model_name" label="Model" />
        <el-table-column label="启用" width="80">
          <template #default="{ row }">
            <el-tag :type="row.enabled ? 'success' : 'info'" size="small">
              {{ row.enabled ? '启用' : '关闭' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="作为 Gate" width="90">
          <template #default="{ row }">
            <el-tag :type="row.enabled_as_gate ? 'warning' : 'info'" size="small">
              {{ row.enabled_as_gate ? '是' : '否' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="API Key" width="100">
          <template #default="{ row }">
            <el-tag :type="row.api_key_is_configured ? 'success' : 'danger'" size="small">
              {{ row.api_key_is_configured ? '已注入' : '未注入' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="config_version" label="版本" width="70" />
        <el-table-column label="操作" width="170">
          <template #default="{ row }">
            <el-button size="small" @click="openEdit(row)">编辑</el-button>
            <el-button size="small" type="danger" @click="onDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 移动端卡片视图 -->
      <div v-if="isMobile" class="ac-card-list">
        <el-empty v-if="rows.length === 0" description="暂无配置" :image-size="60" />
        <div v-for="row in rows" :key="row.id" class="ac-card">
          <div class="ac-card-head">
            <span class="ac-card-title">#{{ row.id }} {{ row.name }}</span>
            <el-tag :type="row.enabled ? 'success' : 'info'" size="small">
              {{ row.enabled ? '启用' : '关闭' }}
            </el-tag>
          </div>
          <div class="ac-card-body">
            <div class="ac-field"><span class="ac-lbl">来源</span><span>{{ row.source_type }}</span></div>
            <div class="ac-field"><span class="ac-lbl">版本</span><span>{{ row.config_version }}</span></div>
            <div class="ac-field"><span class="ac-lbl">Provider</span><span>{{ row.provider }}</span></div>
            <div class="ac-field"><span class="ac-lbl">Model</span><span>{{ row.model_name }}</span></div>
            <div class="ac-field">
              <span class="ac-lbl">作为 Gate</span>
              <el-tag :type="row.enabled_as_gate ? 'warning' : 'info'" size="small">{{ row.enabled_as_gate ? '是' : '否' }}</el-tag>
            </div>
            <div class="ac-field">
              <span class="ac-lbl">API Key</span>
              <el-tag :type="row.api_key_is_configured ? 'success' : 'danger'" size="small">{{ row.api_key_is_configured ? '已注入' : '未注入' }}</el-tag>
            </div>
          </div>
          <div class="ac-card-ops">
            <span class="ac-op" @click="openEdit(row)">编辑</span>
            <span class="ac-op-sep">|</span>
            <span class="ac-op ac-op-danger" @click="onDelete(row)">删除</span>
          </div>
        </div>
      </div>
    </el-card>

    <el-dialog v-model="dialogVisible" :title="form.id ? '编辑 AI 配置' : '新增 AI 配置'" :fullscreen="isMobile" :width="isMobile ? '100%' : 'min(780px, 92vw)'">
      <el-form :model="form" :label-width="isMobile ? '110px' : '140px'">
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="例如：默认模拟盘 Pre-Buy" />
        </el-form-item>
        <el-form-item label="来源类型">
          <el-select v-model="form.source_type">
            <el-option label="模拟交易 (paper)" value="paper" />
            <el-option label="回测 (backtest)" value="backtest" />
            <el-option label="实盘 (live)" value="live" />
            <el-option label="全部 (all)" value="all" />
          </el-select>
        </el-form-item>
        <el-form-item label="来源 ID">
          <el-input v-model.number="form.source_id" placeholder="留空表示该来源类型下所有" clearable />
        </el-form-item>
        <el-form-item label="启用 AI 研判">
          <el-switch v-model="form.enabled" />
        </el-form-item>
        <el-form-item label="作为交易 Gate">
          <el-switch v-model="form.enabled_as_gate" />
          <span class="hint">开启后买入需 score ≥ 阈值；卖出需 score ≤ 阈值</span>
        </el-form-item>
        <el-form-item label="失败时拒绝交易">
          <el-switch v-model="form.fail_closed" />
          <span class="hint">默认关（失败放行）；开启后 AI 失败将拒绝下单</span>
        </el-form-item>

        <el-divider content-position="left">模型 / 接入</el-divider>
        <el-form-item label="Provider">
          <el-select v-model="form.provider" filterable allow-create
                     :placeholder="providerLoading ? '加载中...' : '选择 provider（可手填）'"
                     @change="onProviderChange">
            <el-option v-for="p in providerOptions" :key="p.value"
                       :label="p.label" :value="p.value" />
          </el-select>
          <span class="hint">从 <code>QUANTIA_AI_PROVIDER_*_API_BASE</code> 等环境变量自动发现；新增不需改前端。</span>
        </el-form-item>
        <el-form-item label="Model">
          <el-select v-model="form.model_name" filterable allow-create
                     placeholder="例如 gpt-4o-mini / deepseek-chat（可手填）">
            <el-option v-for="m in modelOptions" :key="m" :label="m" :value="m" />
          </el-select>
          <span v-if="selectedProfile && !selectedProfile.has_key" class="hint" style="color:#e6a23c">
            该 provider 在服务器端未检测到 API Key（QUANTIA_AI_PROVIDER_*_API_KEY 未设置）
          </span>
        </el-form-item>
        <el-form-item label="Base URL">
          <el-input v-model="form.base_url" :placeholder="selectedProfile?.api_base || '例如 https://api.deepseek.com'" />
        </el-form-item>
        <el-form-item label="api_key_ref">
          <el-input v-model="form.api_key_ref" placeholder="环境变量名，例如 QUANTIA_AI_API_KEY" />
        </el-form-item>

        <el-divider content-position="left">Prompt</el-divider>
        <el-form-item label="System Prompt">
          <el-input v-model="form.system_prompt" type="textarea" :rows="4" />
        </el-form-item>
        <el-form-item label="User Prompt 模板">
          <el-input v-model="form.user_prompt_template" type="textarea" :rows="6"
                    placeholder="可使用 {{ code }}, {{ indicators }}, {{ kline_window }} 等占位符" />
        </el-form-item>

        <el-divider content-position="left">参数</el-divider>
        <el-form-item label="Temperature">
          <el-input-number v-model="form.temperature" :min="0" :max="2" :step="0.1" />
        </el-form-item>
        <el-form-item label="Max Tokens">
          <el-input-number v-model="form.max_tokens" :min="1" :max="32000" :step="64" />
        </el-form-item>
        <el-form-item label="超时（秒）">
          <el-input-number v-model="form.timeout_seconds" :min="1" :max="300" :step="1" />
        </el-form-item>
        <el-form-item label="重试次数">
          <el-input-number v-model="form.retry_count" :min="0" :max="5" :step="1" />
        </el-form-item>
        <el-form-item label="Buy 阈值">
          <el-input-number v-model="form.buy_threshold" :min="0" :max="100" :step="1" />
        </el-form-item>
        <el-form-item label="Sell 阈值">
          <el-input-number v-model="form.sell_threshold" :min="0" :max="100" :step="1" />
          <span class="hint">score ≤ 阈值视为通过卖出/减仓</span>
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
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  listAIConfigs, saveAIConfig, deleteAIConfig, AIDecisionConfig,
} from '@/api/settings'
import { aiGetConfig, type AiProviderProfile } from '@/api/ai'
import { useResponsive } from '@/composables/useResponsive'

const { isMobile } = useResponsive()
const rows = ref<AIDecisionConfig[]>([])
const dialogVisible = ref(false)
const saving = ref(false)
// ---- 动态 provider / model 下拉（从 /api/ai/config 拉取 QUANTIA_AI_PROVIDER_*） ----
const profiles = ref<AiProviderProfile[]>([])
const providerLoading = ref(false)

const providerOptions = computed(() => {
  const opts = profiles.value.map(p => ({
    value: p.name,
    label: p.label || _titleCase(p.name),
  }))
  // 保留 openai_compatible 作为通用兑底选项
  if (!opts.find(o => o.value === 'openai_compatible')) {
    opts.unshift({ value: 'openai_compatible', label: 'OpenAI Compatible (通用)' })
  }
  return opts
})

const selectedProfile = computed<AiProviderProfile | undefined>(() =>
  profiles.value.find(p => p.name === form.value.provider))

const modelOptions = computed<string[]>(() => {
  const p = selectedProfile.value
  if (!p) return []
  const list = [...(p.models || [])]
  if (p.default_model && !list.includes(p.default_model)) list.unshift(p.default_model)
  return list
})

function _titleCase(s: string): string {
  return (s || '').split('_').map(w => w ? w[0].toUpperCase() + w.slice(1) : w).join(' ')
}

async function loadProviders() {
  providerLoading.value = true
  try {
    const r = await aiGetConfig()
    if (r.code === 0 && r.data) profiles.value = r.data.profiles || []
  } catch (e: any) {
    console.warn('加载 AI provider 列表失败:', e?.message || e)
  } finally {
    providerLoading.value = false
  }
}

function onProviderChange(v: string) {
  const p = profiles.value.find(x => x.name === v)
  if (!p) return
  // 补默认 base_url / model（仅在用户没填时）
  if (!form.value.base_url && p.api_base) form.value.base_url = p.api_base
  if (!form.value.model_name && p.default_model) form.value.model_name = p.default_model
}

const emptyForm = (): AIDecisionConfig => ({
  name: '', enabled: false, source_type: 'paper',
  provider: 'openai_compatible', api_key_ref: 'QUANTIA_AI_API_KEY',
  temperature: 0.2, max_tokens: 2048, timeout_seconds: 20, retry_count: 1,
  buy_threshold: 70, sell_threshold: 40, enabled_as_gate: false, fail_closed: false,
})
const form = ref<AIDecisionConfig>(emptyForm())

const loadList = async () => {
  const res = await listAIConfigs()
  rows.value = res?.data || []
}

const openCreate = () => {
  form.value = emptyForm()
  dialogVisible.value = true
}

const openEdit = (row: AIDecisionConfig) => {
  form.value = { ...row }
  dialogVisible.value = true
}

const onSave = async () => {
  saving.value = true
  try {
    const res = await saveAIConfig(form.value)
    if (!res.ok) { ElMessage.error(res.error || '保存失败'); return }
    ElMessage.success('保存成功，配置版本：' + res.data.config_version)
    dialogVisible.value = false
    await loadList()
  } finally {
    saving.value = false
  }
}

const onDelete = async (row: AIDecisionConfig) => {
  if (!row.id) return
  await ElMessageBox.confirm(`确定删除配置 #${row.id} (${row.name})？`, '提示', { type: 'warning' })
  await deleteAIConfig(row.id)
  ElMessage.success('已删除')
  await loadList()
}

onMounted(async () => {
  await Promise.all([loadList(), loadProviders()])
})
</script>

<style scoped>
.settings-page { padding: 16px }
.card-header { display: flex; justify-content: space-between; align-items: center }
.hint { color: #909399; font-size: 12px; margin-left: 8px }

/* ─── 移动端卡片视图 ─── */
.ac-card-list { display: flex; flex-direction: column; gap: 10px; }
.ac-card { background: #fff; border: 1px solid #ebeef5; border-radius: 6px; padding: 10px 12px; }
.ac-card-head { display: flex; justify-content: space-between; align-items: center; padding-bottom: 8px; border-bottom: 1px dashed #ebeef5; }
.ac-card-title { font-weight: 600; color: #303133; font-size: 14px; }
.ac-card-body { display: grid; grid-template-columns: 1fr 1fr; gap: 6px 12px; font-size: 13px; padding: 8px 0; }
.ac-field { display: flex; justify-content: space-between; align-items: center; }
.ac-lbl { color: #909399; }
.ac-card-ops { display: flex; justify-content: flex-end; align-items: center; gap: 8px; padding-top: 8px; border-top: 1px dashed #ebeef5; }
.ac-op { color: #409eff; cursor: pointer; font-size: 13px; }
.ac-op-danger { color: #f56c6c; }
.ac-op-sep { color: #dcdfe6; }

@media (max-width: 767.98px) {
  .settings-page { padding: 10px }
  .card-header { flex-wrap: wrap; gap: 8px; }
}
</style>
