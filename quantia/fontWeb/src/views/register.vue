<script setup lang="ts">
/**
 * Phase 8 自助注册页。
 *
 * 流程：
 *   1. 输入邮箱 → 点击「发送验证码」→ 后端发送 6 位数字验证码到邮箱（5 分钟有效）。
 *      - 后端 60 秒内只允许重发一次（按钮倒计时）。
 *      - 后端开发模式 (QUANTIA_REGISTER_DEV_MODE=true) 会在响应中回显 dev_code。
 *   2. 填写验证码 + 密码 + 确认密码 + 昵称 → 提交注册。
 *      - 注册成功自动登录（若鉴权启用），跳转首页。
 */
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { authApi } from '@/api/auth'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const authStore = useAuthStore()

const email = ref('')
const code = ref('')
const password = ref('')
const passwordConfirm = ref('')
const nickname = ref('')

const sendingCode = ref(false)
const submitting = ref(false)
const cooldown = ref(0)
let timer: number | null = null

const canSendCode = computed(
  () => !sendingCode.value && cooldown.value === 0 && /\S+@\S+\.\S+/.test(email.value)
)

onMounted(async () => {
  await authStore.bootstrap()
  if (authStore.username) {
    router.replace('/')
  }
})

onBeforeUnmount(() => {
  if (timer !== null) {
    window.clearInterval(timer)
    timer = null
  }
})

function startCooldown(seconds: number) {
  cooldown.value = seconds
  if (timer !== null) window.clearInterval(timer)
  timer = window.setInterval(() => {
    cooldown.value -= 1
    if (cooldown.value <= 0) {
      cooldown.value = 0
      if (timer !== null) {
        window.clearInterval(timer)
        timer = null
      }
    }
  }, 1000)
}

async function onSendCode() {
  if (!canSendCode.value) {
    ElMessage.warning('请填写有效邮箱')
    return
  }
  sendingCode.value = true
  try {
    const resp = await authApi.sendRegisterCode(email.value.trim().toLowerCase())
    if (resp?.ok && resp.data) {
      const ttl = resp.data.expires_in || 300
      ElMessage.success(
        resp.data.smtp_sent
          ? `验证码已发送至邮箱，${Math.floor(ttl / 60)} 分钟内有效`
          : '验证码已生成（开发模式）'
      )
      if (resp.data.dev_code) {
        // 开发模式回显验证码，方便本地调试
        code.value = resp.data.dev_code
        ElMessage.info(`开发模式验证码：${resp.data.dev_code}`)
      }
      startCooldown(60)
    } else {
      ElMessage.error(resp?.error || '发送失败')
    }
  } catch {
    // 拦截器已提示
  } finally {
    sendingCode.value = false
  }
}

async function onSubmit() {
  if (!email.value || !code.value || !password.value || !nickname.value) {
    ElMessage.warning('请填写所有必填字段')
    return
  }
  if (password.value !== passwordConfirm.value) {
    ElMessage.error('两次输入的密码不一致')
    return
  }
  if (password.value.length < 6) {
    ElMessage.error('密码至少 6 位')
    return
  }
  submitting.value = true
  try {
    const resp = await authApi.register({
      email: email.value.trim().toLowerCase(),
      code: code.value.trim(),
      password: password.value,
      password_confirm: passwordConfirm.value,
      nickname: nickname.value.trim()
    })
    if (resp?.ok && resp.data) {
      ElMessage.success('注册成功')
      // 注册成功后端已自动登录（cookie 已下发）。刷新 store 后跳首页。
      authStore.$patch({
        enabled: !!resp.data.enabled,
        username: resp.data.username,
        role: (resp.data.role as 'admin' | 'operator' | 'viewer' | null) ?? null,
        email: resp.data.email ?? null,
        nickname: resp.data.nickname ?? null
      })
      router.replace('/')
    } else {
      ElMessage.error(resp?.error || '注册失败')
    }
  } catch {
    // 拦截器已提示
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="register-wrap">
    <div class="register-card">
      <h2 class="title">玄枢 Quantia 注册</h2>
      <el-form @submit.prevent="onSubmit" label-width="80px">
        <el-form-item label="邮箱">
          <el-input
            v-model="email"
            type="email"
            placeholder="example@domain.com"
            autocomplete="email"
          />
        </el-form-item>
        <el-form-item label="验证码">
          <div style="display: flex; gap: 8px; width: 100%;">
            <el-input
              v-model="code"
              maxlength="6"
              placeholder="6 位数字"
              style="flex: 1;"
            />
            <el-button
              :loading="sendingCode"
              :disabled="!canSendCode"
              @click="onSendCode"
            >
              {{ cooldown > 0 ? `${cooldown}s 后重发` : '发送验证码' }}
            </el-button>
          </div>
        </el-form-item>
        <el-form-item label="昵称">
          <el-input v-model="nickname" maxlength="32" placeholder="登录后展示" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="password"
            type="password"
            autocomplete="new-password"
            show-password
            placeholder="至少 6 位"
          />
        </el-form-item>
        <el-form-item label="确认密码">
          <el-input
            v-model="passwordConfirm"
            type="password"
            autocomplete="new-password"
            show-password
            @keyup.enter="onSubmit"
          />
        </el-form-item>
        <el-form-item>
          <el-button
            type="primary"
            :loading="submitting"
            @click="onSubmit"
            style="width: 100%"
          >注册并登录</el-button>
        </el-form-item>
        <div class="login-row">
          已有账号？
          <router-link to="/login">直接登录</router-link>
        </div>
      </el-form>
    </div>
  </div>
</template>

<style scoped>
.register-wrap {
  min-height: 100dvh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f5f7fa;
}
.register-card {
  width: 420px;
  padding: 32px 28px;
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08);
}
@media (max-width: 575.98px) {
  .register-card {
    width: calc(100vw - 32px);
    max-width: 420px;
    padding: 24px 20px;
  }
}
.title {
  text-align: center;
  margin: 0 0 16px;
  font-size: 18px;
  color: #303133;
}
.login-row {
  text-align: center;
  font-size: 13px;
  color: #909399;
  a {
    margin-left: 4px;
    color: #409eff;
    text-decoration: none;
  }
}
</style>
