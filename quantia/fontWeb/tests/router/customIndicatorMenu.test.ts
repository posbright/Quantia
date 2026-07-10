import { describe, it, expect } from 'vitest'
import router from '@/router'

describe('custom indicator menu placement', () => {
  it('places indicator editor under parameter configuration menu', () => {
    const routes = router.options.routes
    const configRoute = routes.find((route) => route.path === '/config')
    const legacyRoute = routes.find((route) => route.path === '/custom-indicator')

    expect(configRoute?.children?.some((child) => child.name === 'CustomIndicatorEditor')).toBe(true)
    expect(configRoute?.children?.find((child) => child.name === 'CustomIndicatorEditor')?.path).toBe('custom-indicator')
    expect(legacyRoute?.meta?.hidden).toBe(true)
    expect(legacyRoute?.redirect).toBe('/config/custom-indicator')
  })
})