import axios, { AxiosInstance, InternalAxiosRequestConfig, AxiosResponse } from 'axios'
import { ElMessage } from 'element-plus'

/**
 * 从 document.cookie 读取指定名称的 cookie 值。
 * 用于把后端在 /api/auth/login 颁发的 csrf_token 回显到 X-CSRF-Token 头。
 */
function readCookie(name: string): string | null {
  if (typeof document === 'undefined' || !document.cookie) return null
  const target = name + '='
  const parts = document.cookie.split(';')
  for (const raw of parts) {
    const cookie = raw.trim()
    if (cookie.startsWith(target)) {
      return decodeURIComponent(cookie.substring(target.length))
    }
  }
  return null
}

const WRITE_METHODS = new Set(['post', 'put', 'delete', 'patch'])

// 创建 axios 实例
const service: AxiosInstance = axios.create({
  baseURL: '/quantia',
  // 部分验证 / 回测页面的同步分析接口可能耗时较长（K 线兜底、组合回测等），
  // 全局超时放宽到 5 分钟，避免长区间数据请求被 axios 中断。
  timeout: 300000,
  headers: {
    'Content-Type': 'application/json;charset=UTF-8'
  },
  // Phase 8: 携带 cookie，否则 secure_cookie 会话不会随请求发送。
  withCredentials: true
})

// 请求拦截器
service.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    // Phase 8: 写操作自动带 CSRF token；后端在 QUANTIA_AUTH_ENABLED=false
    // 时不会校验，发送也不会有副作用。
    const method = (config.method || 'get').toLowerCase()
    if (WRITE_METHODS.has(method)) {
      const token = readCookie('csrf_token')
      if (token) {
        config.headers = config.headers || {}
        ;(config.headers as Record<string, string>)['X-CSRF-Token'] = token
      }
    }
    return config
  },
  (error) => {
    console.error('请求错误:', error)
    return Promise.reject(error)
  }
)

// 响应拦截器
service.interceptors.response.use(
  (response: AxiosResponse) => {
    return response.data
  },
  (error) => {
    console.error('响应错误:', error)
    const status = error?.response?.status
    const serverMsg = error?.response?.data?.error
    // Phase 8: 401 → 跳转登录页；403 → 显示权限不足；429 → 显示限速。
    if (status === 401) {
      ElMessage.warning(serverMsg || '会话已过期，请重新登录')
      if (typeof window !== 'undefined' &&
          !window.location.pathname.startsWith('/login')) {
        const redirect = encodeURIComponent(
          window.location.pathname + window.location.search
        )
        window.location.href = `/login?redirect=${redirect}`
      }
    } else if (status === 403) {
      ElMessage.error(serverMsg || '没有权限执行该操作')
    } else if (status === 429) {
      ElMessage.warning(serverMsg || '操作过于频繁，请稍后再试')
    } else {
      ElMessage.error(serverMsg || error.message || '网络错误')
    }
    return Promise.reject(error)
  }
)

export default service
