<template>
  <div class="ai-model-picker">
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
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { aiGetConfig, type AiProviderProfile } from '../api/ai'

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
</style>
