import { ref, onMounted, onBeforeUnmount } from 'vue'

/**
 * 软键盘可见性 / 高度差检测（基于 visualViewport API）。
 *
 * Android 默认 resize 模式是 `pan`，软键盘弹起时 `window.innerHeight` 不变，
 * 表单底部按钮会被键盘遮挡。只有 `visualViewport.height` 是可靠信号。
 *
 * 同时把 `--kb-shift` 暴露到 `<html>`，样式侧可写：
 *   max-height: calc(100dvh - 120px - var(--kb-shift, 0px));
 *
 * iOS Safari 不发 resize 而走 scroll，因此两个事件都监听。
 */
export function useVirtualKeyboard(threshold = 80) {
  const visible = ref(false)
  const heightShift = ref(0)

  let vv: VisualViewport | null = null

  const onChange = () => {
    if (!vv) return
    const shift = Math.max(0, window.innerHeight - vv.height)
    heightShift.value = shift
    visible.value = shift > threshold
    if (typeof document !== 'undefined') {
      document.documentElement.style.setProperty('--kb-shift', `${Math.round(shift)}px`)
    }
  }

  onMounted(() => {
    if (typeof window === 'undefined' || !window.visualViewport) return
    vv = window.visualViewport
    vv.addEventListener('resize', onChange)
    vv.addEventListener('scroll', onChange)
    onChange()
  })

  onBeforeUnmount(() => {
    if (!vv) return
    vv.removeEventListener('resize', onChange)
    vv.removeEventListener('scroll', onChange)
    vv = null
    if (typeof document !== 'undefined') {
      document.documentElement.style.removeProperty('--kb-shift')
    }
  })

  return { visible, heightShift }
}
