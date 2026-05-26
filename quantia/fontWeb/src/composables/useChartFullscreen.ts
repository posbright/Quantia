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

  function safeResize() {
    try { chartRef.value?.resize() } catch { /* noop */ }
  }

  function onFsChange() {
    const active = !!document.fullscreenElement
    isFullscreen.value = active
    // 浏览器 layout 完成需要 1~2 帧；多次 resize 避免黑边
    setTimeout(safeResize, 60)
    setTimeout(safeResize, 250)
    setTimeout(safeResize, 600)
    if (!active) {
      try { (screen.orientation as any)?.unlock?.() } catch { /* noop */ }
    }
  }

  async function enter() {
    const el = wrapRef.value
    if (!el || typeof (el as any).requestFullscreen !== 'function') {
      // 浏览器不支持 Fullscreen API：用 CSS class 兜底全屏（旋转 90°）
      el?.classList.add('chart-fs-fallback')
      isFullscreen.value = true
      setTimeout(safeResize, 80)
      setTimeout(safeResize, 320)
      return
    }
    try {
      await (el as any).requestFullscreen()
      try { await (screen.orientation as any)?.lock?.('landscape') } catch { /* noop */ }
    } catch (e) {
      console.warn('[chart-fullscreen] enter failed:', e)
    }
  }

  async function exit() {
    const el = wrapRef.value
    if (el?.classList.contains('chart-fs-fallback')) {
      el.classList.remove('chart-fs-fallback')
      isFullscreen.value = false
      setTimeout(safeResize, 60)
      return
    }
    if (document.fullscreenElement) {
      try { await document.exitFullscreen() } catch { /* noop */ }
    }
    try { (screen.orientation as any)?.unlock?.() } catch { /* noop */ }
  }

  function toggle() {
    if (isFullscreen.value || document.fullscreenElement) exit()
    else enter()
  }

  document.addEventListener('fullscreenchange', onFsChange)

  onBeforeUnmount(() => {
    document.removeEventListener('fullscreenchange', onFsChange)
    if (document.fullscreenElement) {
      try { document.exitFullscreen() } catch { /* noop */ }
    }
  })

  return { isFullscreen, enter, exit, toggle }
}
