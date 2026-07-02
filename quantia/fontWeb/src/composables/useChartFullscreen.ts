import { ref, onBeforeUnmount, type Ref } from 'vue'
import type { ECharts } from 'echarts'

/**
 * 移动端图表全屏 + 横屏锁定 + 触摸缩放配套。
 *
 * 用法：
 *   const wrapRef = ref<HTMLElement|null>(null)
 *   const chart   = shallowRef<ECharts|null>(null)
 *   const fs = useChartFullscreen(wrapRef, chart)
 *   <div ref="wrapRef" class="chart-wrap">
 *     <div ref="chartRef" style="height:320px"></div>
 *     <ChartFullscreenBtn :is-fullscreen="fs.isFullscreen.value" @toggle="fs.toggle"/>
 *   </div>
 *
 * 行为：
 *   - 调 wrapper.requestFullscreen() 让外层占满屏幕
 *   - 调 screen.orientation.lock('landscape') 锁横屏（Android Chrome 支持，iOS 静默忽略）
 *   - 进出全屏自动多次 chart.resize() 适配新尺寸
 *   - 监听 ESC / 浏览器主动退出全屏
 *   - 组件卸载时自动退出
 */
export function useChartFullscreen(
  wrapRef: Ref<HTMLElement | null | undefined>,
  chartRef: Ref<ECharts | null | undefined>,
) {
  const isFullscreen = ref(false)

  function getFullscreenElement(): Element | null {
    return document.fullscreenElement || (document as any).webkitFullscreenElement || null
  }

  async function exitBrowserFullscreen() {
    const exit = document.exitFullscreen || (document as any).webkitExitFullscreen
    if (typeof exit === 'function') {
      await exit.call(document)
    }
  }

  function isPortraitViewport(): boolean {
    const vv = (window as any).visualViewport
    const width = Number(vv?.width || window.innerWidth || 0)
    const height = Number(vv?.height || window.innerHeight || 0)
    return height > width
  }

  function updateFullscreenClasses(active: boolean) {
    const el = wrapRef.value
    document.documentElement.classList.toggle('chart-fs-open', active)
    if (!el) return
    el.classList.toggle('chart-fs-active', active)
    el.classList.toggle('chart-fs-rotate', active && isPortraitViewport())
  }

  function safeResize() {
    try { chartRef.value?.resize() } catch { /* noop */ }
  }

  function scheduleResize() {
    requestAnimationFrame(safeResize)
    setTimeout(safeResize, 60)
    setTimeout(safeResize, 250)
    setTimeout(safeResize, 600)
  }

  function onFsChange() {
    const active = !!getFullscreenElement()
    isFullscreen.value = active
    updateFullscreenClasses(active)
    // 浏览器 layout 完成需要 1~2 帧；多次 resize 避免黑边
    scheduleResize()
    if (!active) {
      try { (screen.orientation as any)?.unlock?.() } catch { /* noop */ }
    }
  }

  function onViewportChange() {
    if (!isFullscreen.value) return
    updateFullscreenClasses(true)
    scheduleResize()
  }

  function enterFallback(el: HTMLElement) {
    el.classList.add('chart-fs-fallback')
    isFullscreen.value = true
    updateFullscreenClasses(true)
    scheduleResize()
  }

  async function enter() {
    const el = wrapRef.value
    if (!el) return
    const request = (el as any).requestFullscreen || (el as any).webkitRequestFullscreen
    if (typeof request !== 'function') {
      // 浏览器不支持 Fullscreen API：用 CSS class 兜底全屏（旋转 90°）
      enterFallback(el)
      return
    }
    try {
      updateFullscreenClasses(true)
      await request.call(el)
      try { await (screen.orientation as any)?.lock?.('landscape') } catch { /* noop */ }
      isFullscreen.value = true
      updateFullscreenClasses(true)
      scheduleResize()
    } catch (e) {
      console.warn('[chart-fullscreen] enter failed:', e)
      enterFallback(el)
    }
  }

  async function exit() {
    const el = wrapRef.value
    if (el?.classList.contains('chart-fs-fallback')) {
      el.classList.remove('chart-fs-fallback')
      el.classList.remove('chart-fs-active', 'chart-fs-rotate')
      document.documentElement.classList.remove('chart-fs-open')
      try { (screen.orientation as any)?.unlock?.() } catch { /* noop */ }
      isFullscreen.value = false
      scheduleResize()
      return
    }
    if (getFullscreenElement()) {
      try { await exitBrowserFullscreen() } catch { /* noop */ }
    }
    try { (screen.orientation as any)?.unlock?.() } catch { /* noop */ }
    updateFullscreenClasses(false)
    isFullscreen.value = false
    scheduleResize()
  }

  function toggle() {
    if (isFullscreen.value || getFullscreenElement()) exit()
    else enter()
  }

  document.addEventListener('fullscreenchange', onFsChange)
  document.addEventListener('webkitfullscreenchange', onFsChange as EventListener)
  window.addEventListener('orientationchange', onViewportChange)
  window.addEventListener('resize', onViewportChange)
  ;(window as any).visualViewport?.addEventListener?.('resize', onViewportChange)

  onBeforeUnmount(() => {
    document.removeEventListener('fullscreenchange', onFsChange)
    document.removeEventListener('webkitfullscreenchange', onFsChange as EventListener)
    window.removeEventListener('orientationchange', onViewportChange)
    window.removeEventListener('resize', onViewportChange)
    ;(window as any).visualViewport?.removeEventListener?.('resize', onViewportChange)
    updateFullscreenClasses(false)
    if (getFullscreenElement()) {
      try { void exitBrowserFullscreen() } catch { /* noop */ }
    }
  })

  return { isFullscreen, enter, exit, toggle }
}
