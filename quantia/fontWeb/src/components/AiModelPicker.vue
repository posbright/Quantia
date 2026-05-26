<template>
  <!-- 桌面 / 平板：原双 el-select -->
  <div v-if="!isMobile" class="ai-model-picker">
    <el-select
      v-model="selectedProvider"
      size="small"
      :placeholder="loading ? '加载中...' : '选择 provider'"
      style="width: 130px;"
      @change="onProviderChange"
    >
      <el-option
        v-for="p in profiles"
        :key="p.name"
        :label="p.name + (p.has_key ? '' : ' (无密钥)')"
        :value="p.name"
      />
    </el-select>
    <el-select
      v-model="selectedModel"
      size="small"
      placeholder="选择模型"
      style="width: 200px; margin-left: 8px;"
      filterable
      allow-create
      default-first-option
      @change="emitChange"
    >
      <el-option
        v-for="m in availableModels"
        :key="m"
        :label="m"
        :value="m"
      />
    </el-select>
  </div>

  <!-- 手机：一个触发按钮 + 底部 sheet（provider / model 同屏）-->
  <template v-else>
    <el-button
      class="picker-trigger"
      size="small"
      :loading="loading"
      @click="sheetOpen = true"
    >
      <span class="picker-trigger-label">
        {{ selectedProvider || 'provider' }} / {{ selectedModel || '模型' }}
      </span>
      <el-icon class="picker-trigger-arrow"><ArrowDown /></el-icon>
    </el-button>
    <el-drawer
      v-model="sheetOpen"
      direction="btt"
      size="70%"
      :with-header="true"
      title="选择模型"
      class="picker-sheet"
      :append-to-body="true"
    >
      <div class="picker-sheet-body">
        <div class="picker-section-title">Provider</div>
        <div class="picker-sheet-list">
          <div
            v-for="p in profiles"
            :key="p.name"
            class="picker-sheet-item"
            :class="{ active: selectedProvider === p.name }"
            @click="onPickProvider(p.name)"
          >
            <span class="picker-sheet-label">{{ p.name }}</span>
            <span v-if="!p.has_key" class="picker-tag">无密钥</span>
            <el-icon v-if="selectedProvider === p.name" class="picker-check"><Check /></el-icon>
          </div>
        </div>
        <div class="picker-section-title">模型</div>
        <div class="picker-sheet-list">
          <div
            v-for="m in availableModels"
            :key="m"
            class="picker-sheet-item"
            :class="{ active: selectedModel === m }"
            @click="onPickModel(m)"
          >
            <span class="picker-sheet-label">{{ m }}</span>
            <el-icon v-if="selectedModel === m" class="picker-check"><Check /></el-icon>
          </div>
          <div v-if="availableModels.length === 0" class="picker-empty">该 provider 无可用模型</div>
        </div>
      </div>
    </el-drawer>
  </template>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { ArrowDown, Check } from '@element-plus/icons-vue'
import { aiGetConfig, type AiProviderProfile } from '../api/ai'
import { useResponsive } from '../composables/useResponsive'

const STORAGE_KEY = 'quantia-ai-model-picker'

const props = defineProps<{
  modelValue?: { provider?: string; model?: string }
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', v: { provider: string; model: string }): void
  (e: 'change', v: { provider: string; model: string }): void
}>()

const profiles = ref<AiProviderProfile[]>([])
const loading = ref(false)
const selectedProvider = ref('')
const selectedModel = ref('')
const defaultProvider = ref('')
const defaultModel = ref('')
const sheetOpen = ref(false)
const { isMobile } = useResponsive()

const availableModels = computed<string[]>(() => {
  const prof = profiles.value.find(p => p.name === selectedProvider.value)
  if (!prof) return []
  const list = (prof.models && prof.models.length > 0) ? [...prof.models] : []
  if (prof.default_model && !list.includes(prof.default_model)) {
    list.unshift(prof.default_model)
  }
  return list
})

function _loadFromStorage(): { provider?: string; model?: string } {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return {}
    return JSON.parse(raw)
  } catch {
    return {}
  }
}

function _saveToStorage() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      provider: selectedProvider.value,
      model: selectedModel.value,
    }))
  } catch { /* ignore */ }
}

async function loadConfig() {
  loading.value = true
  try {
    const resp: any = await aiGetConfig()
    if (resp && resp.code === 0 && resp.data) {
      profiles.value = resp.data.profiles || []
      defaultProvider.value = resp.data.default || ''
      defaultModel.value = resp.data.default_model || ''
      const stored = _loadFromStorage()
      const initialProvider = (props.modelValue?.provider) || stored.provider || defaultProvider.value
      selectedProvider.value = profiles.value.find(p => p.name === initialProvider)
        ? initialProvider
        : (profiles.value[0]?.name || '')
      const prof = profiles.value.find(p => p.name === selectedProvider.value)
      selectedModel.value =
        (props.modelValue?.model) ||
        stored.model ||
        prof?.default_model ||
        defaultModel.value ||
        (prof?.models && prof.models[0]) ||
        ''
      emitChange()
    }
  } catch {
    /* swallow — picker is best-effort */
  } finally {
    loading.value = false
  }
}

function onProviderChange() {
  // 切换 provider 时如果当前 model 不在新 provider 的列表里，重置为新 provider 默认 model
  const prof = profiles.value.find(p => p.name === selectedProvider.value)
  if (prof) {
    const models = prof.models || []
    if (!models.includes(selectedModel.value)) {
      selectedModel.value = prof.default_model || models[0] || selectedModel.value
    }
  }
  emitChange()
}

function emitChange() {
  _saveToStorage()
  const payload = { provider: selectedProvider.value, model: selectedModel.value }
  emit('update:modelValue', payload)
  emit('change', payload)
}

function onPickProvider(name: string) {
  selectedProvider.value = name
  const prof = profiles.value.find(p => p.name === name)
  const models = prof?.models || []
  if (!models.includes(selectedModel.value)) {
    selectedModel.value = prof?.default_model || models[0] || ''
  }
  emitChange()
}

function onPickModel(name: string) {
  selectedModel.value = name
  sheetOpen.value = false
  emitChange()
}

watch(() => props.modelValue, (v) => {
  if (!v || (typeof v === 'object' && Object.keys(v).length === 0)) return
  if (v.provider && v.provider !== selectedProvider.value) selectedProvider.value = v.provider
  if (v.model && v.model !== selectedModel.value) selectedModel.value = v.model
})

onMounted(loadConfig)

defineExpose({ reload: loadConfig })
</script>

<style scoped>
.ai-model-picker { display: inline-flex; align-items: center; }
.picker-trigger {
  display: inline-flex;
  align-items: center;
  justify-content: space-between;
  min-width: 180px;
  max-width: 100%;
}
.picker-trigger-label {
  flex: 1 1 auto;
  text-align: left;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
}
.picker-trigger-arrow { margin-left: 6px; font-size: 12px; color: #909399; }
.picker-sheet-body { padding: 8px 0 24px; }
.picker-section-title {
  padding: 12px 18px 6px;
  font-size: 12px;
  color: #909399;
  font-weight: 600;
}
.picker-sheet-list { display: flex; flex-direction: column; max-height: 38vh; overflow-y: auto; }
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
.picker-sheet-label { flex: 1 1 auto; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.picker-tag {
  margin-left: 6px;
  font-size: 11px;
  color: #909399;
  background: #f5f7fa;
  padding: 0 4px;
  border-radius: 2px;
}
.picker-check { font-size: 16px; color: #409eff; }
.picker-empty { padding: 24px; text-align: center; color: #909399; }
</style>
