<template>
  <!-- 桌面 / 平板：原 el-select -->
  <el-select
    v-if="!isMobile"
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

  <!-- 手机：触发按钮 + 底部 sheet -->
  <template v-else>
    <el-button
      class="picker-trigger"
      size="small"
      :loading="loading"
      @click="sheetOpen = true"
    >
      <span class="picker-trigger-label">{{ currentLabel || '选择 Agent' }}</span>
      <el-icon class="picker-trigger-arrow"><ArrowDown /></el-icon>
    </el-button>
    <el-drawer
      v-model="sheetOpen"
      direction="btt"
      size="60%"
      :with-header="true"
      title="选择 Agent"
      class="picker-sheet"
      :append-to-body="true"
    >
      <div class="picker-sheet-list">
        <div
          v-for="a in agents"
          :key="a.name"
          class="picker-sheet-item"
          :class="{ active: selected === a.name }"
          @click="onPick(a.name)"
        >
          <span class="picker-sheet-label">{{ a.display_name || a.name }}</span>
          <span v-if="a.is_builtin" class="picker-tag">内置</span>
          <el-icon v-if="selected === a.name" class="picker-check"><Check /></el-icon>
        </div>
        <div v-if="!loading && agents.length === 0" class="picker-empty">暂无 Agent</div>
      </div>
    </el-drawer>
  </template>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { ArrowDown, Check } from '@element-plus/icons-vue'
import { aiListAgents, type AiAgentMeta } from '../api/ai'
import { useResponsive } from '../composables/useResponsive'

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

const { isMobile } = useResponsive()
const agents = ref<AiAgentMeta[]>([])
const loading = ref(false)
const selected = ref('')
const sheetOpen = ref(false)

const currentLabel = computed(() => {
  const found = agents.value.find(a => a.name === selected.value)
  return found ? (found.display_name || found.name) : ''
})

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

function onPick(name: string) {
  selected.value = name
  sheetOpen.value = false
  emitChange()
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
.picker-trigger {
  display: inline-flex;
  align-items: center;
  justify-content: space-between;
  min-width: 140px;
  max-width: 100%;
}
.picker-trigger-label {
  flex: 1 1 auto;
  text-align: left;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.picker-trigger-arrow { margin-left: 6px; font-size: 12px; color: #909399; }
.picker-sheet-list {
  display: flex;
  flex-direction: column;
  gap: 0;
  padding: 4px 0;
  max-height: calc(60vh - 60px);
  overflow-y: auto;
}
.picker-sheet-item {
  display: flex;
  align-items: center;
  padding: 14px 18px;
  font-size: 15px;
  border-bottom: 1px solid #f0f2f5;
  cursor: pointer;
}
.picker-sheet-item:active { background: #f5f7fa; }
.picker-sheet-item.active { color: #409eff; }
.picker-sheet-label { flex: 1 1 auto; }
.picker-check { font-size: 16px; color: #409eff; }
.picker-empty { padding: 24px; text-align: center; color: #909399; }
</style>
