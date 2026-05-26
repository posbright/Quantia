import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { authApi } from '@/api/auth'

export type Role = 'admin' | 'operator' | 'viewer'

/**
 * Phase 8 鉴权状态。
 *
 * 角色权限简表（与后端 require_role 一致，仅作 UX 提示用）：
 *   - admin    可改实盘开关、IP 白名单、IM operator 白名单、用户管理。
 *   - operator 可改 notification / ai-config 业务配置。
 *   - viewer   只读所有页面，写按钮 disabled 并提示「需要 operator 角色」。
 */
export const useAuthStore = defineStore('auth', () => {
  const enabled = ref(false)
  const username = ref<string | null>(null)
  const role = ref<Role | null>(null)
  const email = ref<string | null>(null)
  const nickname = ref<string | null>(null)
  const bootstrapped = ref(false)

  async function bootstrap() {
    if (bootstrapped.value) return
    try {
      // 弱网保护：3s 超时，避免路由守卫无限阻塞
      const resp: any = await Promise.race([
        authApi.me(),
        new Promise((_, reject) =>
          setTimeout(() => reject(new Error('auth bootstrap timeout')), 3000)
        ),
      ])
      enabled.value = !!resp?.data?.enabled
      username.value = resp?.data?.username ?? null
      role.value = (resp?.data?.role as Role | null) ?? null
      email.value = resp?.data?.email ?? null
      nickname.value = resp?.data?.nickname ?? null
    } catch {
      enabled.value = false
      username.value = null
      role.value = null
      email.value = null
      nickname.value = null
    } finally {
      bootstrapped.value = true
    }
  }

  async function login(user: string, password: string) {
    const resp = await authApi.login(user, password)
    if (resp?.ok && resp.data) {
      enabled.value = !!resp.data.enabled
      username.value = resp.data.username
      role.value = (resp.data.role as Role | null) ?? null
      email.value = resp.data.email ?? null
      nickname.value = resp.data.nickname ?? null
    }
    return resp
  }

  async function logout() {
    try {
      await authApi.logout()
    } finally {
      username.value = null
      role.value = null
      email.value = null
      nickname.value = null
    }
  }

  function clear() {
    username.value = null
    role.value = null
    email.value = null
    nickname.value = null
  }

  /** 判断当前会话是否拥有列表中任一角色。关闭鉴权时一律 true。 */
  function hasRole(...required: Role[]): boolean {
    if (!enabled.value) return true
    if (!username.value || !role.value) return false
    return required.includes(role.value)
  }

  const isAdmin = computed(() => hasRole('admin'))
  const canWrite = computed(() => hasRole('admin', 'operator'))
  const isViewer = computed(
    () => enabled.value && role.value === 'viewer'
  )

  return {
    enabled,
    username,
    role,
    email,
    nickname,
    bootstrapped,
    isAdmin,
    canWrite,
    isViewer,
    bootstrap,
    login,
    logout,
    clear,
    hasRole,
  }
})
