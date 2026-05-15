<template>
  <el-select
    v-model="selected"
    size="small"
    :placeholder="loading ? '加载中...' : '选择 Agent'"
    style="width: 180px;"
    @change="emitChange"
  >
    <el-option
      v-for="a in agents"
      :key="a.name"
      :label="a.display_name || a.name"
      :value="a.name"
    >
      <span>{{ a.display_name || a.name }}</span>
      <span v-if="a.is_builtin" class="picker-tag">内置</span>
    </el-option>
  </el-select>
</template>

<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { aiListAgents, type AiAgentMeta } from '../api/ai'

const STORAGE_KEY = 'quantia-ai-agent-picker'

const props = defineProps<{
  modelValue?: string
  // 默认 agent（外部如 AiChatDrawer 按 mode 推算）
  defaultAgent?: string
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', v: string): void
  (e: 'change', v: string): void
}>()

const agents = ref<AiAgentMeta[]>([])
const loading = ref(false)
const selected = ref('')

function _loadFromStorage(): string {
  try { return localStorage.getItem(STORAGE_KEY) || '' } catch { return '' }
}

function _saveToStorage() {
  try { localStorage.setItem(STORAGE_KEY, selected.value) } catch { /* ignore */ }
}

async function loadAgents() {
  loading.value = true
  try {
    const resp: any = await aiListAgents(false)
    if (resp && resp.code === 0 && resp.data) {
      agents.value = resp.data.agents || []
      const stored = _loadFromStorage()
      const initial = props.modelValue || stored || props.defaultAgent || (agents.value[0]?.name || '')
      selected.value = agents.value.find(a => a.name === initial) ? initial : (agents.value[0]?.name || '')
      emitChange()
    }
  } catch {
    /* best-effort */
  } finally {
    loading.value = false
  }
}

function emitChange() {
  _saveToStorage()
  emit('update:modelValue', selected.value)
  emit('change', selected.value)
}

watch(() => props.modelValue, (v) => {
  if (v && v !== selected.value) selected.value = v
})

onMounted(loadAgents)

defineExpose({ reload: loadAgents })
</script>

<style scoped>
.picker-tag {
  margin-left: 6px;
  font-size: 11px;
  color: #909399;
  background: #f5f7fa;
  padding: 0 4px;
  border-radius: 2px;
}
</style>
