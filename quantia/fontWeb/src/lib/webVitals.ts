/**
 * web-vitals 性能上报（PR-12）。
 *
 * 浏览器侧采集 LCP / CLS / INP / FCP / TTFB，sendBeacon 异步发送到
 * `/quantia/api/metric/web_vitals`（如果后端未实现该路由会静默 404，不影响业务）。
 *
 * 开发模式 / 标记了 `data-disable-vitals` 时只 console.debug，不发请求。
 */
import { onCLS, onINP, onLCP, onFCP, onTTFB, type Metric } from 'web-vitals'

const ENDPOINT = '/quantia/api/metric/web_vitals'

function shouldReport(): boolean {
  if (typeof window === 'undefined') return false
  if (import.meta.env.DEV) return false
  if (document.documentElement?.hasAttribute('data-disable-vitals')) return false
  return true
}

function send(metric: Metric) {
  const payload = {
    name: metric.name,
    value: Math.round(metric.value * 1000) / 1000,
    rating: metric.rating,
    delta: metric.delta,
    id: metric.id,
    nav: metric.navigationType,
    path: window.location.pathname,
    ts: Date.now(),
  }
  if (!shouldReport()) {
    // 开发时只打 debug，方便本地观察
    // eslint-disable-next-line no-console
    console.debug('[web-vitals]', metric.name, metric.value, metric.rating)
    return
  }
  try {
    const body = JSON.stringify(payload)
    if (navigator.sendBeacon) {
      navigator.sendBeacon(ENDPOINT, new Blob([body], { type: 'application/json' }))
    } else {
      fetch(ENDPOINT, {
        method: 'POST',
        body,
        headers: { 'Content-Type': 'application/json' },
        keepalive: true,
      }).catch(() => { /* swallow */ })
    }
  } catch {
    /* best-effort */
  }
}

export function startWebVitals() {
  try {
    onLCP(send)
    onCLS(send)
    onINP(send)
    onFCP(send)
    onTTFB(send)
  } catch {
    /* web-vitals 加载失败也不应阻塞业务 */
  }
}
