<template>
  <div class="agent-manager">
    <div class="header">
      <h2>AI Agent 管理</h2>
      <div class="actions">
        <el-button type="primary" :icon="Plus" @click="openCreate">新建 Agent</el-button>
        <el-button :icon="Refresh" @click="reload">刷新</el-button>
      </div>
    </div>

    <el-table v-if="!isMobile" :data="agents" v-loading="loading" border stripe size="small"
              empty-text="暂无 agent">
      <el-table-column prop="name" label="名称" width="180">
        <template #default="{ row }">
          <span>{{ row.name }}</span>
          <el-tag v-if="row.is_builtin" size="small" type="info" style="margin-left:6px">内置</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="display_name" label="显示名" width="180" />
      <el-table-column prop="description" label="描述" min-width="200" show-overflow-tooltip />
      <el-table-column prop="default_provider" label="provider" width="100" />
      <el-table-column prop="default_model" label="model" width="160" />
      <el-table-column label="工具" width="220">
        <template #default="{ row }">
          <el-tag v-for="t in (row.allowed_tools || [])" :key="t" size="small"
                  style="margin-right:4px">{{ t }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="enabled" label="启用" width="70">
        <template #default="{ row }">
          <el-tag :type="row.enabled ? 'success' : 'danger'" size="small">
            {{ row.enabled ? '是' : '否' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="180" fixed="right">
        <template #default="{ row }">
          <el-button size="small" link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-popconfirm v-if="!row.is_builtin"
                         :title="`确认删除 ${row.name}?`"
                         @confirm="onDelete(row)">
            <template #reference>
              <el-button size="small" link type="danger">删除</el-button>
            </template>
          </el-popconfirm>
          <el-tooltip v-else content="内置 agent 不可删除" placement="top">
            <el-button size="small" link disabled>删除</el-button>
          </el-tooltip>
        </template>
      </el-table-column>
    </el-table>

    <!-- 移动端卡片视图 -->
    <div v-if="isMobile" v-loading="loading" class="am-card-list">
      <el-empty v-if="!loading && agents.length === 0" description="暂无 agent" :image-size="60" />
      <div v-for="row in agents" :key="row.name" class="am-card">
        <div class="am-card-head">
          <span class="am-card-title">
            {{ row.name }}
            <el-tag v-if="row.is_builtin" size="small" type="info">内置</el-tag>
          </span>
          <el-tag :type="row.enabled ? 'success' : 'danger'" size="small">{{ row.enabled ? '启用' : '禁用' }}</el-tag>
        </div>
        <div class="am-card-body">
          <div class="am-field"><span class="am-lbl">显示名</span><span>{{ row.display_name || '--' }}</span></div>
          <div class="am-field"><span class="am-lbl">provider</span><span>{{ row.default_provider || '--' }}</span></div>
          <div class="am-field"><span class="am-lbl">model</span><span>{{ row.default_model || '--' }}</span></div>
          <div class="am-field am-field-full" v-if="row.description"><span class="am-lbl">描述</span><span>{{ row.description }}</span></div>
          <div class="am-field am-field-full" v-if="(row.allowed_tools || []).length">
            <span class="am-lbl">工具</span>
            <span class="am-tools">
              <el-tag v-for="t in (row.allowed_tools || [])" :key="t" size="small">{{ t }}</el-tag>
            </span>
          </div>
        </div>
        <div class="am-card-ops">
          <span class="am-op" @click="openEdit(row)">编辑</span>
          <template v-if="!row.is_builtin">
            <span class="am-op-sep">|</span>
            <el-popconfirm :title="`确认删除 ${row.name}?`" @confirm="onDelete(row)">
              <template #reference>
                <span class="am-op am-op-danger">删除</span>
              </template>
            </el-popconfirm>
          </template>
        </div>
      </div>
    </div>

    <el-dialog v-model="dialogVisible" :title="dialogTitle" :fullscreen="isMobile" :width="isMobile ? '100%' : 'min(640px, 92vw)'"
               :close-on-click-modal="false">
      <el-form :model="form" :label-width="isMobile ? '96px' : '120px'" ref="formRef" :rules="rules">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" :disabled="isEdit"
                    placeholder="字母/数字/下划线，例如 market_summarizer" maxlength="64" />
        </el-form-item>
        <el-form-item label="显示名">
          <el-input v-model="form.display_name" maxlength="128" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="System Prompt" prop="system_prompt">
          <el-input v-model="form.system_prompt" type="textarea" :rows="8"
                    :disabled="form.is_builtin"
                    placeholder="agent 的系统提示词" />
          <div v-if="form.is_builtin" class="hint">内置 agent 的 prompt 不可在此编辑</div>
        </el-form-item>
        <el-form-item label="默认 provider">
          <el-input v-model="form.default_provider" placeholder="可留空，使用全局默认" />
        </el-form-item>
        <el-form-item label="默认 model">
          <el-input v-model="form.default_model" placeholder="可留空，使用全局默认" />
        </el-form-item>
        <el-form-item label="允许的工具">
          <el-select v-model="form.allowed_tools" multiple filterable allow-create
                     style="width:100%" placeholder="不选则禁用工具调用"
                     :disabled="form.is_builtin">
            <el-option v-for="t in TOOL_CHOICES" :key="t" :label="t" :value="t" />
          </el-select>
        </el-form-item>
        <el-form-item label="temperature">
          <el-input-number v-model="form.temperature" :min="0" :max="2" :step="0.1" />
        </el-form-item>
        <el-form-item label="max_tokens">
          <el-input-number v-model="form.max_tokens" :min="1" :max="65536" :step="256" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.enabled" :disabled="form.is_builtin" />
          <span v-if="form.is_builtin" class="hint" style="margin-left:8px">内置 agent 不可禁用</span>
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
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import {
  aiListManagedAgents,
  aiGetAgentDetail,
  aiSaveAgent,
  aiDeleteAgent,
  type AiAgentRecord,
} from '@/api/ai'
import { useResponsive } from '@/composables/useResponsive'

const { isMobile } = useResponsive()
const TOOL_CHOICES = ['sql_query', 'kline_fetch', 'code_validate', 'backtest_run', 'web_search']

const agents = ref<AiAgentRecord[]>([])
const loading = ref(false)

const dialogVisible = ref(false)
const dialogTitle = ref('新建 Agent')
const saving = ref(false)
const isEdit = ref(false)
const formRef = ref<any>(null)

const form = reactive<AiAgentRecord>({
  name: '',
  display_name: '',
  description: '',
  system_prompt: '',
  default_provider: '',
  default_model: '',
  allowed_tools: [],
  temperature: 0.3,
  max_tokens: 4096,
  enabled: true,
  is_builtin: false,
})

const rules = {
  name: [{ required: true, message: '请输入 name', trigger: 'blur' }],
  system_prompt: [{ required: true, message: '请输入 system_prompt', trigger: 'blur' }],
}

function reload() {
  loading.value = true
  aiListManagedAgents(false)
    .then((res: any) => {
      agents.value = res?.data?.agents || []
    })
    .catch((e) => ElMessage.error(`读取失败: ${e?.message || e}`))
    .finally(() => (loading.value = false))
}

function resetForm() {
  form.name = ''
  form.display_name = ''
  form.description = ''
  form.system_prompt = ''
  form.default_provider = ''
  form.default_model = ''
  form.allowed_tools = []
  form.temperature = 0.3
  form.max_tokens = 4096
  form.enabled = true
  form.is_builtin = false
}

function openCreate() {
  resetForm()
  isEdit.value = false
  dialogTitle.value = '新建 Agent'
  dialogVisible.value = true
}

async function openEdit(row: AiAgentRecord) {
  resetForm()
  isEdit.value = true
  dialogTitle.value = `编辑 Agent: ${row.name}`
  try {
    const res: any = await aiGetAgentDetail(row.name)
    const d = res?.data || {}
    Object.assign(form, {
      name: d.name,
      display_name: d.display_name || '',
      description: d.description || '',
      system_prompt: d.system_prompt || '',
      default_provider: d.default_provider || '',
      default_model: d.default_model || '',
      allowed_tools: d.allowed_tools || [],
      temperature: typeof d.temperature === 'number' ? d.temperature : 0.3,
      max_tokens: typeof d.max_tokens === 'number' ? d.max_tokens : 4096,
      enabled: d.enabled !== false,
      is_builtin: !!d.is_builtin,
    })
    dialogVisible.value = true
  } catch (e: any) {
    ElMessage.error(`读取详情失败: ${e?.message || e}`)
  }
}

async function onSave() {
  if (formRef.value) {
    try {
      await formRef.value.validate()
    } catch {
      return
    }
  }
  saving.value = true
  const payload: Partial<AiAgentRecord> = {
    name: form.name,
    display_name: form.display_name,
    description: form.description,
    system_prompt: form.system_prompt,
    default_provider: form.default_provider || undefined,
    default_model: form.default_model || undefined,
    allowed_tools: form.allowed_tools && form.allowed_tools.length ? form.allowed_tools : null,
    temperature: form.temperature,
    max_tokens: form.max_tokens,
    enabled: form.enabled,
  }
  try {
    const res: any = await aiSaveAgent(payload)
    if (res?.code === 0) {
      ElMessage.success('保存成功')
      dialogVisible.value = false
      reload()
    } else {
      ElMessage.error(res?.msg || '保存失败')
    }
  } catch (e: any) {
    ElMessage.error(`保存失败: ${e?.message || e}`)
  } finally {
    saving.value = false
  }
}

async function onDelete(row: AiAgentRecord) {
  try {
    const res: any = await aiDeleteAgent(row.name)
    if (res?.code === 0) {
      ElMessage.success('已删除')
      reload()
    } else {
      ElMessage.error(res?.msg || '删除失败')
    }
  } catch (e: any) {
    ElMessage.error(`删除失败: ${e?.message || e}`)
  }
}

onMounted(reload)
</script>

<style scoped>
.agent-manager {
  padding: 16px;
}
.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.actions {
  display: flex;
  gap: 8px;
}
.hint {
  color: #909399;
  font-size: 12px;
  margin-top: 4px;
}

/* ─── 移动端卡片视图 ─── */
.am-card-list { display: flex; flex-direction: column; gap: 10px; }
.am-card { background: #fff; border: 1px solid #ebeef5; border-radius: 6px; padding: 10px 12px; }
.am-card-head { display: flex; justify-content: space-between; align-items: center; padding-bottom: 8px; border-bottom: 1px dashed #ebeef5; }
.am-card-title { font-weight: 600; color: #303133; font-size: 14px; display: flex; align-items: center; gap: 6px; }
.am-card-body { display: grid; grid-template-columns: 1fr 1fr; gap: 6px 12px; font-size: 13px; padding: 8px 0; }
.am-field { display: flex; justify-content: space-between; gap: 6px; }
.am-field-full { grid-column: 1 / -1; }
.am-tools { display: flex; flex-wrap: wrap; gap: 4px; justify-content: flex-end; }
.am-lbl { color: #909399; white-space: nowrap; }
.am-card-ops { display: flex; justify-content: flex-end; align-items: center; gap: 8px; padding-top: 8px; border-top: 1px dashed #ebeef5; }
.am-op { color: #409eff; cursor: pointer; font-size: 13px; }
.am-op-danger { color: #f56c6c; }
.am-op-sep { color: #dcdfe6; }

/* 移动端适配（PR-10） */
@media (max-width: 768px) {
  .agent-manager { padding: 10px 8px; }
  .header { flex-direction: column; align-items: stretch; gap: 8px; }
  .actions { flex-wrap: wrap; }
}
</style>
