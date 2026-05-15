<script setup lang="ts">
/**
 * Phase 8 登录页。
 *
 * - 后端 QUANTIA_AUTH_ENABLED=false 时，调用 /api/auth/login 会返回
 *   { ok:true, data:{ enabled:false } }，本页直接跳回首页。
 * - 启用后，登录成功颁发 QUANTIA_session + csrf_token cookie。
 */
import { ref, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const username = ref('')
const password = ref('')
const submitting = ref(false)
onMounted(async () => {
  // 已登录或鉴权未启用 → 直接跳转。
  await authStore.bootstrap()
  if (!authStore.enabled || authStore.username) {
    redirectAfterLogin()
  }
})

function redirectAfterLogin() {
  const target = (route.query.redirect as string) || '/'
  // 防御：避免开放重定向 (//evil.com)；只允许 / 开头的相对路径。
  const safe = target.startsWith('/') && !target.startsWith('//') ? target : '/'
  router.replace(safe)
}

async function onSubmit() {
  if (!username.value.trim() || !password.value) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  submitting.value = true
  try {
    const resp = await authStore.login(username.value.trim(), password.value)
    if (resp?.ok) {
      ElMessage.success('登录成功')
      redirectAfterLogin()
    } else {
      ElMessage.error(resp?.error || '登录失败')
    }
  } catch {
    // axios 拦截器已弹错误提示，这里不重复。
  } finally {
    submitting.value = false
    password.value = ''
  }
}
</script>

<template>
  <div class="login-wrap">
    <div class="login-card">
      <h2 class="title">玄枢 Quantia 管理后台</h2>
      <p class="hint" v-if="!authStore.bootstrapped">正在检查会话...</p>
      <p class="hint" v-else-if="!authStore.enabled">
        当前后端鉴权未启用 (QUANTIA_AUTH_ENABLED=false)，请直接进入应用。
      </p>
      <el-form @submit.prevent="onSubmit" v-if="authStore.enabled">
        <el-form-item label="账号">
          <el-input
            v-model="username"
            autocomplete="username"
            placeholder="用户名 / 邮箱 / 昵称"
          />
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="password"
            type="password"
            autocomplete="current-password"
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
          >登录</el-button>
        </el-form-item>
        <div class="register-row">
          还没有账号？
          <router-link to="/register">立即注册</router-link>
        </div>
      </el-form>
    </div>
  </div>
</template>

<style scoped>
.login-wrap {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f5f7fa;
}
.login-card {
  width: 360px;
  padding: 32px 28px;
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08);
}
.title {
  text-align: center;
  margin: 0 0 16px;
  font-size: 18px;
  color: #303133;
}
.hint {
  text-align: center;
  color: #909399;
  font-size: 12px;
  margin: 0 0 16px;
}
.register-row {
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
