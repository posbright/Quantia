import { onMounted, onBeforeUnmount, onActivated, onDeactivated, watch, type Ref } from 'vue'
import type { ECharts } from 'echarts'
import { useResponsive } from './useResponsive'

/**
 * M1 echarts 响应式 + 生命周期统一封装。修复 indicator/index.vue 等页面长期存在
 * 的 keep-alive resize 监听重复注册 + 不 dispose 泄漏问题。
 *
 * 使用方式：
 *   const chartRef = ref<HTMLElement|null>(null)
 *   const chart = shallowRef<ECharts|null>(null)
 *   useChartResponsive(chart, {
 *     onResize: () => chart.value?.resize(),
 *     mobileGrid: { top: 30, left: 8, right: 8, bottom: 28 },
 *     desktopGrid: { top: 30, left: 50, right: 30, bottom: 40 },
 *   })
 *
 * 责任范围：
 *   - 统一 window + visualViewport resize 监听（防键盘弹起破坏布局）
 *   - keep-alive 切走时 chart.clear() 让出 GPU
 *   - onUnmounted 强制 dispose + 解绑监听
 *   - 提供按断点切换 grid / dataZoom 配置的助手
 */

export type GridConfig = { top?: number | string; left?: number | string; right?: number | string; bottom?: number | string; containLabel?: boolean }

export interface UseChartResponsiveOptions {
  /** 视口变化时回调；通常调 chart.resize() + 自定义 setOption。 */
  onResize?: () => void
  /** 移动端 grid（xs / sm 时使用）。 */
  mobileGrid?: GridConfig
  /** 桌面 grid（lg+）。 */
  desktopGrid?: GridConfig
  /** keep-alive 切走时是否调 chart.clear() 释放 GPU，默认 true。 */
  clearOnDeactivate?: boolean
  /** 防抖 ms，默认 100。 */
  debounceMs?: number
}

export function useChartResponsive(
  chart: Ref<ECharts | null | undefined>,
  options: UseChartResponsiveOptions = {},
) {
  const {
    onResize,
    mobileGrid,
    desktopGrid,
    clearOnDeactivate = true,
    debounceMs = 100,
  } = options
  const { isMobile, breakpoint } = useResponsive()

  let timer: number | null = null
  const handleResize = () => {
    if (timer !== null) {
      window.clearTimeout(timer)
    }
    timer = window.setTimeout(() => {
      timer = null
      if (!chart.value) return
      try {
        chart.value.resize()
        onResize?.()
      } catch (_e) {
        // chart 已 dispose 的情况下静默
      }
    }, debounceMs)
  }

  const currentGrid = () => (isMobile.value ? mobileGrid : desktopGrid) || undefined

  // 断点切换时刷新 grid（不依赖 setOption 调用方写死断点）
  watch(breakpoint, () => {
    const grid = currentGrid()
    if (grid && chart.value) {
      try {
        chart.value.setOption({ grid }, { lazyUpdate: true } as any)
      } catch (_e) { /* noop */ }
    }
    handleResize()
  })

  onMounted(() => {
    window.addEventListener('resize', handleResize, { passive: true })
    ;(window as any).visualViewport?.addEventListener?.('resize', handleResize, { passive: true })
  })

  onActivated(() => {
    // keep-alive 切回：resize 一次让 chart 重新填满容器
    handleResize()
  })

  onDeactivated(() => {
    if (clearOnDeactivate) {
      try { chart.value?.clear() } catch (_e) { /* noop */ }
    }
  })

  onBeforeUnmount(() => {
    if (timer !== null) window.clearTimeout(timer)
    window.removeEventListener('resize', handleResize)
    ;(window as any).visualViewport?.removeEventListener?.('resize', handleResize)
    try { chart.value?.dispose() } catch (_e) { /* noop */ }
  })

  return {
    isMobile,
    breakpoint,
    currentGrid,
    triggerResize: handleResize,
  }
}
