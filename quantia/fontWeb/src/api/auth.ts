import service from './request'

/**
 * Phase 8 鉴权 API。
 *
 * 后端默认 QUANTIA_AUTH_ENABLED=false，此时:
 * - GET  /api/auth/me      → { enabled: false, username: null }
 * - POST /api/auth/login   → { enabled: false, username: null }（不设 cookie）
 * - POST /api/auth/logout  → 清空 cookie（即使未启用也安全）
 *
 * 启用后:
 * - login 成功颁发 QUANTIA_session（httpOnly）+ csrf_token（非 httpOnly）。
 *   axios 拦截器从 cookie 读取 csrf_token，写操作自动带 X-CSRF-Token 头。
 */
export interface AuthMeResponse {
  enabled: boolean
  username: string | null
  role: string | null
  email?: string | null
  nickname?: string | null
}

export interface AuthLoginResponse {
  enabled: boolean
  username: string | null
  role: string | null
  email?: string | null
  nickname?: string | null
  source?: string
  csrf_token?: string
  ttl_seconds?: number
}

export interface AdminUser {
  id: number
  username: string
  role: 'admin' | 'operator' | 'viewer'
  enabled: boolean
  last_login_at: string | null
  created_at: string | null
  updated_at: string | null
  email?: string | null
  nickname?: string | null
}

export interface SendCodeResponse {
  ok: boolean
  expires_in: number
  smtp_sent: boolean
  dev_code?: string
}

export const authApi = {
  me() {
    return service.get<unknown, { ok: boolean; data: AuthMeResponse }>(
      '/api/auth/me'
    )
  },
  login(identifier: string, password: string) {
    return service.post<
      unknown,
      { ok: boolean; data: AuthLoginResponse; error?: string }
    >('/api/auth/login', { username: identifier, password })
  },
  logout() {
    return service.post<unknown, { ok: boolean }>('/api/auth/logout', {})
  },
  // ── 自助注册（公开端点） ──
  sendRegisterCode(email: string) {
    return service.post<
      unknown,
      { ok: boolean; data?: SendCodeResponse; error?: string }
    >('/api/auth/register/send-code', { email })
  },
  register(payload: {
    email: string
    code: string
    password: string
    password_confirm: string
    nickname: string
  }) {
    return service.post<
      unknown,
      { ok: boolean; data?: AuthLoginResponse; error?: string }
    >('/api/auth/register', payload)
  },
  // ── Should 8 用户管理（admin） ──
  listUsers() {
    return service.get<unknown, { ok: boolean; data: AdminUser[] }>(
      '/api/auth/users/list'
    )
  },
  saveUser(payload: {
    id?: number
    username?: string
    password?: string
    role: AdminUser['role']
    enabled: boolean
  }) {
    return service.post<
      unknown,
      { ok: boolean; data?: AdminUser; error?: string }
    >('/api/auth/users/save', payload)
  },
  deleteUser(id: number) {
    return service.post<
      unknown,
      { ok: boolean; error?: string }
    >('/api/auth/users/delete', { id })
  },
  // ── Should 7 审计聚合（admin/operator） ──
  audit(limit = 200) {
    return service.get<
      unknown,
      {
        ok: boolean
        data: Array<{
          kind: string
          id: number
          ref_a: unknown
          ref_b: unknown
          modified_by: string
          updated_at: string | null
          config_version: number | null
        }>
      }
    >(`/api/auth/audit/list?limit=${limit}`)
  }
}
