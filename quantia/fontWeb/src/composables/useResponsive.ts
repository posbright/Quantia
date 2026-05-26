import { computed, ref, onMounted, onBeforeUnmount } from 'vue'

/**
 * M1 响应式基础设施。统一的断点真相源，所有移动适配组件 / mixin 都基于这里。
 *
 * 断点对齐 Element Plus 与 Bootstrap 5：
 *   xs   < 576        手机竖屏
 *   sm   ≥ 576        手机横屏 / 小平板竖屏
 *   md   ≥ 768        平板竖屏
 *   lg   ≥ 992        桌面（项目原 1100 断点统一收敛到此处）
 *   xl   ≥ 1200       大桌面
 *   xxl  ≥ 1600       超宽屏
 *
 * 紧急回滚：
 *   - localStorage.setItem('quantia.forceDesktop', '1') → 永远返回桌面（lg）
 *   - <html data-force-desktop> → 同上（后端注入 QUANTIA_FORCE_DESKTOP=1）
 */

export type Breakpoint = 'xs' | 'sm' | 'md' | 'lg' | 'xl' | 'xxl'

const BREAKPOINTS: Record<Exclude<Breakpoint, 'xs'>, number> = {
  sm: 576,
  md: 768,
  lg: 992,
  xl: 1200,
  xxl: 1600,
}

function resolveBp(w: number): Breakpoint {
  if (w >= BREAKPOINTS.xxl) return 'xxl'
  if (w >= BREAKPOINTS.xl) return 'xl'
  if (w >= BREAKPOINTS.lg) return 'lg'
  if (w >= BREAKPOINTS.md) return 'md'
  if (w >= BREAKPOINTS.sm) return 'sm'
  return 'xs'
}

function isForcedDesktop(): boolean {
  if (typeof window === 'undefined') return false
  try {
    if (window.localStorage?.getItem('quantia.forceDesktop') === '1') return true
  } catch (_e) {
    // 隐私模式 / Safari ITP localStorage 可能抛错，忽略
  }
  const html = document.documentElement
  if (html?.dataset?.forceDesktop === '1' || html?.hasAttribute('data-force-desktop')) return true
  return false
}

const _width = ref<number>(typeof window === 'undefined' ? 1280 : window.innerWidth)
const _height = ref<number>(typeof window === 'undefined' ? 800 : window.innerHeight)
const _dpr = ref<number>(typeof window === 'undefined' ? 1 : Math.min(window.devicePixelRatio || 1, 3))
let _listenerAttached = false
let _refCount = 0

function _onResize() {
  _width.value = window.innerWidth
  _height.value = window.innerHeight
}

function _attach() {
  if (_listenerAttached || typeof window === 'undefined') return
  window.addEventListener('resize', _onResize, { passive: true })
  // visualViewport 在软键盘弹起 / 缩放时变化，比 window 更准
  ;(window as any).visualViewport?.addEventListener?.('resize', _onResize, { passive: true })
  _listenerAttached = true
}

function _detach() {
  if (!_listenerAttached || typeof window === 'undefined') return
  window.removeEventListener('resize', _onResize)
  ;(window as any).visualViewport?.removeEventListener?.('resize', _onResize)
  _listenerAttached = false
}

/**
 * 主入口：返回 reactive 的当前断点 + 常用布尔。
 * 多个组件同时使用时复用同一个全局 resize 监听器（引用计数）。
 */
export function useResponsive() {
  const forced = isForcedDesktop()
  const bp = computed<Breakpoint>(() => (forced ? 'lg' : resolveBp(_width.value)))

  const isMobile = computed(() => !forced && (bp.value === 'xs' || bp.value === 'sm'))
  const isTablet = computed(() => !forced && bp.value === 'md')
  const isDesktop = computed(() => forced || bp.value === 'lg' || bp.value === 'xl' || bp.value === 'xxl')

  // 工具语义：以 768 为界，小于则当作"小屏"
  const isSmallScreen = computed(() => !forced && _width.value < BREAKPOINTS.md)
  const isLargeScreen = computed(() => forced || _width.value >= BREAKPOINTS.lg)

  // 折叠 / 横屏（手机横屏 < 480 高）
  const isLandscape = computed(() => _width.value > _height.value)
  const isPortrait = computed(() => _height.value >= _width.value)

  onMounted(() => {
    _refCount += 1
    _attach()
    _onResize()
  })
  onBeforeUnmount(() => {
    _refCount -= 1
    if (_refCount <= 0) {
      _refCount = 0
      _detach()
    }
  })

  return {
    width: _width,
    height: _height,
    dpr: _dpr,
    breakpoint: bp,
    isMobile,
    isTablet,
    isDesktop,
    isSmallScreen,
    isLargeScreen,
    isLandscape,
    isPortrait,
    forcedDesktop: forced,
  }
}

/**
 * 不需要 reactive 上下文（如 router guard / store action）时用这个。
 * 直接读 window.innerWidth + 强制桌面短路。
 */
export function getCurrentBreakpoint(): Breakpoint {
  if (typeof window === 'undefined') return 'lg'
  if (isForcedDesktop()) return 'lg'
  return resolveBp(window.innerWidth)
}

export const BREAKPOINT_VALUES = BREAKPOINTS
