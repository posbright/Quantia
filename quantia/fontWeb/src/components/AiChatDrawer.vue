<template>
  <el-drawer
    v-model="visible"
    title="AI 策略助手"
    direction="rtl"
    :size="drawerSize"
    :before-close="handleClose"
    class="ai-chat-drawer"
  >
    <div class="ai-drawer-wrap">
      <!-- M8 会话侧边栏（仅 chat 模式可见） -->
      <aside v-if="mode === 'chat'" class="ai-sidebar">
        <div class="sidebar-head">
          <span>会话列表</span>
          <el-button text size="small" @click="newConversation">新会话</el-button>
        </div>
        <div class="sidebar-list">
          <div
            v-for="c in conversations"
            :key="c.conversation_id"
            class="sidebar-item"
            :class="{ active: c.conversation_id === currentConvId }"
            @click="selectConversation(c.conversation_id)"
          >
            <div class="title-row">
              <span class="title-text">{{ c.title || '(未命名)' }}</span>
              <el-button
                text size="small" type="danger" class="del-btn"
                @click.stop="deleteConversation(c.conversation_id)"
              >删除</el-button>
            </div>
            <div class="meta-row">{{ c.message_count }} 条 · {{ formatTs(c.updated_at) }}</div>
          </div>
          <div v-if="!conversations.length" class="sidebar-empty">暂无会话</div>
        </div>
      </aside>

      <div class="ai-drawer">
      <!-- M5: provider/model + agent 选择 -->
      <div class="ai-pickers">
        <AiModelPicker v-model="modelSel" />
        <AiAgentPicker v-model="agentSel" :default-agent="defaultAgentForMode" />
      </div>

      <!-- 模式切换 -->
      <el-radio-group v-model="mode" size="small" style="margin-bottom: 12px;">
        <el-radio-button value="generate">生成新策略</el-radio-button>
        <el-radio-button value="refine" :disabled="!currentCode">修改当前代码</el-radio-button>
        <el-radio-button value="repair" :disabled="!strategyId">修复失败回测</el-radio-button>
        <el-radio-button value="chat">多轮聊天</el-radio-button>
      </el-radio-group>

      <!-- chat 模式：消息流 -->
      <div v-if="mode === 'chat'" class="chat-wrap">
        <div class="chat-history" ref="chatHistoryEl">
          <div v-for="(m, i) in chatMessages" :key="i" class="chat-msg" :class="m.role">
            <div class="chat-role">{{ m.role === 'user' ? '我' : (m.role === 'assistant' ? 'AI' : m.role) }}</div>
            <pre class="chat-content">{{ m.content }}</pre>
          </div>
          <div v-if="!chatMessages.length" class="chat-empty">输入消息开始新对话。</div>
        </div>
        <el-input
          v-model="prompt"
          type="textarea"
          :rows="3"
          placeholder="向 AI 提问，可联系上下文（最多约 4000 tokens 历史）"
          maxlength="2000"
          show-word-limit
        />
      </div>

      <!-- Prompt 输入（非 chat 模式） -->
      <template v-else>
      <div v-if="mode !== 'repair'">
        <div class="section-label">
          {{ mode === 'generate' ? '描述你想要的策略' : '描述要修改的内容' }}
        </div>
        <el-input
          v-model="prompt"
          type="textarea"
          :rows="6"
          :placeholder="placeholder"
          maxlength="2000"
          show-word-limit
        />
      </div>
      <div v-else class="section-label">
        将根据该策略最近一次失败的回测错误信息进行修复。
      </div>
      </template>

      <!-- 操作 -->
      <div class="ai-actions">
        <el-button type="primary" :loading="loading" @click="run" :disabled="!canRun">
          {{ loading ? (mode === 'chat' ? '发送中...' : '生成中...') : (mode === 'chat' ? '发送' : '运行') }}
        </el-button>
        <el-button
          v-if="mode === 'generate'"
          type="success"
          :loading="streaming"
          @click="runStream"
          :disabled="!canRun"
        >
          {{ streaming ? '流式生成中...' : '流式运行' }}
        </el-button>
        <el-button v-if="lastCode && mode !== 'chat'" @click="apply">采用结果</el-button>
        <el-button v-if="lastCode && mode !== 'chat'" text @click="copyResult">复制</el-button>
      </div>

      <!-- 流式输出预览 -->
      <el-card v-if="streaming || (streamingText && !lastCode)" shadow="never" style="margin-top: 12px;">
        <div class="section-label">流式输出（实时）：</div>
        <pre class="stream-preview">{{ streamingText || '等待第一段输出...' }}</pre>
      </el-card>

      <!-- 校验状态（非 chat） -->
      <template v-if="mode !== 'chat'">
      <el-alert
        v-if="validationError"
        :title="`沙箱校验失败：${validationError}`"
        type="warning"
        show-icon
        :closable="false"
        style="margin-top: 12px;"
      />
      <el-alert
        v-else-if="lastCode && validated"
        :title="repairAttempts > 0
          ? `代码已通过沙箱校验（自动修复 ${repairAttempts} 轮后通过）`
          : '代码已通过沙箱校验'"
        type="success"
        show-icon
        :closable="false"
        style="margin-top: 12px;"
      />
      <el-alert
        v-if="!validated && lastCode && repairAttempts > 0"
        :title="`已自动尝试修复 ${repairAttempts} 轮仍未通过校验，请人工检查后采用。`"
        type="info"
        show-icon
        :closable="false"
        style="margin-top: 8px;"
      />
      </template>
      <el-alert
        v-if="errorMsg"
        :title="errorMsg"
        type="error"
        show-icon
        :closable="false"
        style="margin-top: 12px;"
      />

      <!-- 失败信息（repair 模式） -->
      <div v-if="failureInfo && mode === 'repair'" class="failure-block">
        <div class="section-label">
          最近一次失败：
          <el-tag v-if="failureInfo.traceback" size="small" type="danger" effect="plain" style="margin-left:8px;">含完整堆栈</el-tag>
          <el-tag v-if="(failureInfo.history || []).length > 1" size="small" type="warning" effect="plain" style="margin-left:6px;">
            历史失败 {{ (failureInfo.history || []).length }} 次
          </el-tag>
        </div>
        <pre>{{ failureInfo.error_message }}</pre>
        <div class="meta">回测 ID: {{ failureInfo.backtest_id }} · 时间: {{ failureInfo.started_at }}</div>
        <el-collapse v-if="failureInfo.traceback" style="margin-top:6px;">
          <el-collapse-item title="展开完整 Traceback" name="tb">
            <pre class="tb-preview">{{ failureInfo.traceback }}</pre>
          </el-collapse-item>
        </el-collapse>
        <el-collapse v-if="(failureInfo.history || []).length > 1" style="margin-top:6px;">
          <el-collapse-item :title="`查看历史失败（共 ${(failureInfo.history || []).length} 次）`" name="hist">
            <div v-for="h in (failureInfo.history || []).slice(1)" :key="h.id" class="hist-item">
              <div class="meta">回测 ID: {{ h.id }} · {{ h.started_at }}</div>
              <pre>{{ h.error_message }}</pre>
            </div>
          </el-collapse-item>
        </el-collapse>
      </div>

      <!-- 生成代码预览（非 chat） -->
      <div v-if="lastCode && mode !== 'chat'" class="result-block">
        <div class="section-label">生成结果：</div>
        <pre class="code-preview">{{ lastCode }}</pre>
      </div>
      </div>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  aiGenerateStrategy, aiRefineStrategy, aiRepairStrategy, aiGenerateStrategyStream,
  aiChat, aiListConversations, aiGetConversation, aiDeleteConversation,
  type StrategyAiResponse,
  type AiConversationSummary,
} from '../api/ai'
import AiModelPicker from './AiModelPicker.vue'
import AiAgentPicker from './AiAgentPicker.vue'

type FailureHistoryItem = {
  id: number
  started_at: string
  error_message: string
}

type FailureInfo = {
  error_message: string
  started_at: string
  backtest_id: number
  traceback?: string
  error?: string
  history?: FailureHistoryItem[]
}

export type AiApplyMeta = {
  source: 'ai'
  ai_prompt: string
  ai_agent: string  // 'strategy_coder' / 'strategy_repairer'
  ai_model?: string
}

const props = defineProps<{
  modelValue: boolean
  currentCode?: string
  strategyId?: number | string
  defaultMode?: 'generate' | 'refine' | 'repair' | 'chat'
  initialPrompt?: string
  // PR：repair 模式预演回测参数；后端在 DB 无失败记录时自动跑预演
  strategyName?: string
  backtestStartDate?: string
  backtestEndDate?: string
  backtestInitialCash?: number
  backtestBenchmark?: string
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'apply', code: string, meta: AiApplyMeta): void
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (v: boolean) => emit('update:modelValue', v),
})

// M0: 移动端抽屉占满整屏；桌面端保持 55% 不变
const isNarrow = ref(false)
let _mql: MediaQueryList | null = null
const _onMqlChange = (e: MediaQueryListEvent) => { isNarrow.value = e.matches }
onMounted(() => {
  if (typeof window !== 'undefined' && window.matchMedia) {
    _mql = window.matchMedia('(max-width: 768px)')
    isNarrow.value = _mql.matches
    _mql.addEventListener?.('change', _onMqlChange)
  }
})
onBeforeUnmount(() => { _mql?.removeEventListener?.('change', _onMqlChange) })
const drawerSize = computed(() => (isNarrow.value ? '100%' : '55%'))

const mode = ref<'generate' | 'refine' | 'repair' | 'chat'>(props.defaultMode || 'generate')

// M5: provider/model/agent 选择（持久化由各 picker 自负责）
const modelSel = ref<{ provider?: string; model?: string }>({})
const agentSel = ref<string>('')
const defaultAgentForMode = computed(() =>
  mode.value === 'repair' ? 'strategy_repairer' : 'strategy_coder')

function _overrides() {
  const o: Record<string, any> = {}
  if (modelSel.value.provider) o.provider = modelSel.value.provider
  if (modelSel.value.model) o.model = modelSel.value.model
  return o
}

// 抽屉打开时若指定了 defaultMode，则按指定模式重置（避免用户上次切换的 mode 残留）
watch(() => props.modelValue, (v) => {
  if (v) {
    if (props.defaultMode) {
      mode.value = props.defaultMode
    }
    if (props.initialPrompt) {
      prompt.value = props.initialPrompt
    }
    // 抽屉打开时清空旧错误（保留 lastCode 便于再次"采用"）
    errorMsg.value = ''
  }
})
const prompt = ref('')
const loading = ref(false)
const streaming = ref(false)
const streamingText = ref('')
const lastCode = ref('')
const validated = ref(false)
const validationError = ref('')
const errorMsg = ref('')
const failureInfo = ref<FailureInfo | null>(null)
const lastModel = ref('')
const repairAttempts = ref(0)

const placeholder = computed(() => {
  if (mode.value === 'generate') {
    return '例：写一个布林带下轨抄底策略，跌破下轨时买入，回到中轨卖出，持仓不超过 10 只'
  }
  return '例：把持仓数量从 5 只改成 10 只，并加上 5% 止损'
})

const canRun = computed(() => {
  if (loading.value) return false
  if (mode.value === 'chat') return prompt.value.trim().length > 0
  if (mode.value === 'repair') return !!props.strategyId
  return prompt.value.trim().length > 0
})

function _resetState() {
  errorMsg.value = ''
  validationError.value = ''
  validated.value = false
  failureInfo.value = null
  repairAttempts.value = 0
}

// 从 axios 错误中优先提取后端返回的 msg/error，避免 HTTP 4xx/5xx 时只显示
// 通用的 "Request failed with status code XXX"，丢失上游限流等关键原因。
function _extractErrMsg(e: any): string {
  const data = e?.response?.data
  if (data) {
    if (typeof data === 'string' && data.trim()) return data
    if (typeof data === 'object') {
      const m = data.msg || data.error || data.message
      if (m) return String(m)
    }
  }
  return e?.message || String(e)
}

async function run() {
  if (mode.value === 'chat') {
    await runChat()
    return
  }
  _resetState()
  loading.value = true
  try {
    let resp: StrategyAiResponse
    const ov = _overrides()
    if (mode.value === 'generate') {
      resp = await aiGenerateStrategy({ prompt: prompt.value, ...ov }) as any
    } else if (mode.value === 'refine') {
      resp = await aiRefineStrategy({
        prompt: prompt.value,
        code: props.currentCode || '',
        ...ov,
      }) as any
    } else {
      resp = await aiRepairStrategy({
        strategy_id: props.strategyId!,
        code: props.currentCode || undefined,
        // 把编辑页当前的回测配置一起带过去，后端兜底预演时复用同样的窗口
        strategy_name: props.strategyName || undefined,
        start_date: props.backtestStartDate || undefined,
        end_date: props.backtestEndDate || undefined,
        initial_cash: props.backtestInitialCash || undefined,
        benchmark: props.backtestBenchmark || undefined,
        auto_backtest: true,
        ...ov,
      }) as any
    }

    if (resp.code === 0 || resp.code === -2) {
      lastCode.value = resp.data?.code || ''
      validated.value = !!resp.data?.validated
      validationError.value = resp.data?.validation_error || ''
      failureInfo.value = resp.data?.failure || null
      lastModel.value = resp.data?.model || ''
      repairAttempts.value = resp.data?.repair_attempts || 0
      if (resp.code === -2) {
        // 仍展示代码，但提示需要修复
        ElMessage.warning('AI 生成的代码未通过沙箱校验，请人工检查或重试')
      } else if (repairAttempts.value > 0) {
        ElMessage.success(`生成成功（自动修复 ${repairAttempts.value} 轮）`)
      } else {
        ElMessage.success('生成成功')
      }
    } else if (resp.code === 429) {
      errorMsg.value = resp.msg || '触发限流，请稍后再试'
    } else {
      errorMsg.value = resp.msg || 'AI 调用失败'
    }
  } catch (e: any) {
    errorMsg.value = _extractErrMsg(e)
  } finally {
    loading.value = false
  }
}

async function runStream() {
  if (mode.value !== 'generate') return
  _resetState()
  streamingText.value = ''
  streaming.value = true
  try {
    const ov = _overrides()
    await aiGenerateStrategyStream(
      { prompt: prompt.value, ...ov },
      (ev) => {
        if (ev.type === 'chunk') {
          streamingText.value += ev.text
        } else if (ev.type === 'repair') {
          repairAttempts.value = ev.attempt
          ElMessage.info(`沙箱校验未通过，正在第 ${ev.attempt} 轮修复...`)
        } else if (ev.type === 'done') {
          lastCode.value = ev.code || ''
          validated.value = !!ev.validated
          validationError.value = ev.validation_error || ''
          lastModel.value = ev.model || ''
          repairAttempts.value = ev.repair_attempts || repairAttempts.value
          if (!validated.value) {
            ElMessage.warning('AI 生成的代码未通过沙箱校验，请人工检查或重试')
          } else if (repairAttempts.value > 0) {
            ElMessage.success(`流式生成成功（自动修复 ${repairAttempts.value} 轮）`)
          } else {
            ElMessage.success('流式生成成功')
          }
        } else if (ev.type === 'error') {
          errorMsg.value = ev.msg || `AI 调用失败 (code=${ev.code})`
        }
      },
    )
  } catch (e: any) {
    errorMsg.value = _extractErrMsg(e)
  } finally {
    streaming.value = false
  }
}

function apply() {
  if (!lastCode.value) return
  const agent = agentSel.value || defaultAgentForMode.value
  emit('apply', lastCode.value, {
    source: 'ai',
    ai_prompt: prompt.value || (mode.value === 'repair' ? '[repair from last failure]' : ''),
    ai_agent: agent,
    ai_model: lastModel.value || undefined,
  })
  ElMessage.success('已应用到编辑器')
  visible.value = false
}

async function copyResult() {
  if (!lastCode.value) return
  try {
    await navigator.clipboard.writeText(lastCode.value)
    ElMessage.success('已复制')
  } catch {
    ElMessage.warning('复制失败，请手动选择')
  }
}

function handleClose(done: () => void) {
  done()
}

// ─── M8 多轮聊天 ────────────────────────────────────────────────
type ChatMsg = { role: string; content: string; ts?: number }
const chatMessages = ref<ChatMsg[]>([])
const chatHistoryEl = ref<HTMLElement | null>(null)
const conversations = ref<AiConversationSummary[]>([])
// audit-fix-P1-3: conversation_id 持久化到 localStorage（spec §11.3 末尾）
const _LS_KEY = 'ai_chat_conversation_id'
const currentConvId = ref<string>(
  (typeof localStorage !== 'undefined' && localStorage.getItem(_LS_KEY)) || ''
)
watch(currentConvId, (v) => {
  try {
    if (v) localStorage.setItem(_LS_KEY, v)
    else localStorage.removeItem(_LS_KEY)
  } catch { /* SSR / 隐私模式 */ }
})

async function loadConversationsList() {
  try {
    const r = await aiListConversations({ scene: 'chat', mine: true, limit: 50 })
    if (r.code === 0 && r.data) conversations.value = r.data
  } catch { /* 静默 */ }
}

function newConversation() {
  currentConvId.value = ''
  chatMessages.value = []
  prompt.value = ''
}

async function selectConversation(cid: string) {
  if (cid === currentConvId.value) return
  try {
    const r = await aiGetConversation(cid)
    if (r.code === 0 && r.data) {
      currentConvId.value = cid
      chatMessages.value = (r.data.messages || []).filter(m => m.role !== 'system')
      await scrollChatToBottom()
    } else {
      // audit-fix-2-P0-B: 失败时抛出，让自动恢复路径能清掉 localStorage 中的过期 id
      ElMessage.error(r.msg || '加载会话失败')
      throw new Error(r.msg || 'load_conversation_failed')
    }
  } catch (e: any) {
    ElMessage.error(e?.message || '加载会话失败')
    throw e
  }
}

async function deleteConversation(cid: string) {
  try {
    await ElMessageBox.confirm('确认删除该会话？', '提示', { type: 'warning' })
  } catch { return }
  try {
    const r = await aiDeleteConversation(cid)
    if (r.code === 0) {
      ElMessage.success('已删除')
      if (cid === currentConvId.value) newConversation()
      await loadConversationsList()
    } else {
      ElMessage.error(r.msg || '删除失败')
    }
  } catch (e: any) {
    ElMessage.error(e?.message || '删除失败')
  }
}

function scrollChatToBottom() {
  return nextTick(() => {
    const el = chatHistoryEl.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

function formatTs(ts: number): string {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

async function runChat() {
  const text = prompt.value.trim()
  if (!text) return
  errorMsg.value = ''
  loading.value = true
  chatMessages.value.push({ role: 'user', content: text })
  prompt.value = ''
  await scrollChatToBottom()
  try {
    const ov = _overrides()
    const resp = await aiChat({
      prompt: text,
      scene: 'chat',
      agent: agentSel.value || undefined,
      conversation_id: currentConvId.value || undefined,
      ...ov,
    })
    if (resp.code === 0 && resp.data) {
      chatMessages.value.push({ role: 'assistant', content: resp.data.content || '' })
      if (resp.data.conversation_id) {
        const isNew = !currentConvId.value
        currentConvId.value = resp.data.conversation_id
        if (isNew) await loadConversationsList()
      }
      await scrollChatToBottom()
    } else if (resp.code === 429) {
      errorMsg.value = resp.msg || '触发限流，请稍后再试'
    } else {
      errorMsg.value = resp.msg || 'AI 调用失败'
    }
  } catch (e: any) {
    errorMsg.value = _extractErrMsg(e)
  } finally {
    loading.value = false
  }
}

watch(() => mode.value, (v) => {
  if (v === 'chat' && !conversations.value.length) loadConversationsList()
})

watch(() => props.modelValue, (v) => {
  if (v && mode.value === 'chat') {
    loadConversationsList()
    // audit-fix-P1-3: 抽屉重开时若 localStorage 有上次会话 id，自动加载历史
    if (currentConvId.value && !chatMessages.value.length) {
      selectConversation(currentConvId.value).catch(() => {
        // 可能 ownership 校验失败或被删除 → 清掉本地引用
        currentConvId.value = ''
      })
    }
  }
})
</script>

<style scoped>
.ai-drawer-wrap { display: flex; height: 100%; }
.ai-drawer { padding: 0 16px; flex: 1; min-width: 0; overflow-y: auto; }
.ai-sidebar {
  width: 220px; flex-shrink: 0; border-right: 1px solid #ebeef5;
  display: flex; flex-direction: column; background: #fafbfc;
}
.sidebar-head {
  display: flex; justify-content: space-between; align-items: center;
  padding: 8px 12px; border-bottom: 1px solid #ebeef5; font-size: 13px; font-weight: 600;
}
.sidebar-list { flex: 1; overflow-y: auto; }
.sidebar-item {
  padding: 8px 12px; border-bottom: 1px solid #f0f2f5; cursor: pointer;
}
.sidebar-item:hover { background: #ecf5ff; }
.sidebar-item.active { background: #d9ecff; }
.sidebar-item .title-row { display: flex; justify-content: space-between; align-items: center; }
.sidebar-item .title-text {
  font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 130px;
}
.sidebar-item .meta-row { font-size: 11px; color: #909399; margin-top: 2px; }
.sidebar-item .del-btn { padding: 0; }
.sidebar-empty { padding: 16px; color: #909399; font-size: 12px; text-align: center; }
.chat-wrap { display: flex; flex-direction: column; gap: 8px; }
.chat-history {
  border: 1px solid #ebeef5; border-radius: 4px; background: #fafbfc;
  padding: 8px; min-height: 320px; max-height: 420px; overflow-y: auto;
}
.chat-msg { margin-bottom: 10px; }
.chat-msg.user .chat-content { background: #ecf5ff; }
.chat-msg.assistant .chat-content { background: #fff; border: 1px solid #ebeef5; }
.chat-role { font-size: 11px; color: #909399; margin-bottom: 2px; }
.chat-content {
  margin: 0; padding: 8px 10px; border-radius: 4px; white-space: pre-wrap;
  word-break: break-word; font-family: inherit; font-size: 13px; line-height: 1.5;
}
.chat-empty { color: #909399; font-size: 12px; text-align: center; padding: 32px 0; }
.ai-pickers { display: flex; gap: 8px; align-items: center; margin-bottom: 12px; flex-wrap: wrap; }
.section-label { font-size: 13px; color: #606266; margin: 12px 0 6px; font-weight: 500; }
.ai-actions { margin-top: 12px; display: flex; gap: 8px; }
.failure-block, .result-block { margin-top: 16px; }
.failure-block pre, .code-preview, .tb-preview {
  background: #f5f7fa; border: 1px solid #ebeef5; border-radius: 4px;
  padding: 8px 10px; font-family: 'Consolas', 'Monaco', monospace;
  font-size: 12px; line-height: 1.5; max-height: 360px; overflow: auto;
  white-space: pre-wrap; word-break: break-word;
}
.failure-block .meta { font-size: 11px; color: #909399; margin-top: 4px; }
.failure-block .hist-item { margin-bottom: 8px; padding-bottom: 6px; border-bottom: 1px dashed #ebeef5; }
.failure-block .hist-item:last-child { border-bottom: none; }
.stream-preview {
  background: #f5f7fa; border: 1px solid #ebeef5; border-radius: 4px;
  padding: 8px 10px; font-family: 'Consolas', 'Monaco', monospace;
  font-size: 12px; line-height: 1.5; max-height: 360px; overflow: auto;
  white-space: pre-wrap; word-break: break-word; margin: 0;
}

/* M0: 窄屏（手机 / 折叠屏闭合态）下隐藏 220px 会话侧边栏，主体撑满 */
@media (max-width: 768px) {
  .ai-drawer-wrap .ai-sidebar { display: none; }
  .ai-drawer-wrap .ai-drawer { padding: 0 12px; }
}
</style>
