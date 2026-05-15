import { ref, computed, watch, onMounted } from 'vue'
import { listIndicators, indicatorSeries,
  type IndicatorListItem, type SeriesResult,
  type SignalPoint, type ScorePoint } from '@/api/customIndicator'

export type OverlayMode = 'off' | 'main' | 'sub' | 'both'

const LS_INDICATOR = 'ci_overlay_indicator'
const LS_MODE = 'ci_overlay_mode'

export interface OverlayExtension {
  /** 主图叠加：买卖信号点（scatter on K-line grid 0） */
  mainSignalSeries: any | null
  /** 副图：评分曲线 series + 对应 grid/axis 扩展 */
  subPanel: null | {
    grid: any
    xAxis: any
    yAxis: any
    series: any[]
    legend: string[]
  }
  /** 副图新增了几个 axis index（用于 dataZoom xAxisIndex 联动） */
  extraXAxisCount: number
}

const EMPTY: OverlayExtension = {
  mainSignalSeries: null,
  subPanel: null,
  extraXAxisCount: 0,
}

export interface UseOverlayOptions {
  /** 副图位置参数，相同布局复用主页面 grid 计算 */
  subGridBottom?: string  // 默认 '6%'
  subGridHeight?: string  // 默认 '14%'
}

/**
 * 自定义指标 K 线叠加 composable
 *
 * 用法（页面侧）：
 *   const overlay = useCustomIndicatorOverlay(codeRef, periodRef, datesRef)
 *   // template: <CustomIndicatorOverlayBar :state="overlay" />
 *   // 在构造 echarts option 时:
 *   const ext = overlay.extension.value
 *   if (ext.mainSignalSeries) series.push(ext.mainSignalSeries)
 *   if (ext.subPanel) {
 *     grids.push(ext.subPanel.grid); xAxes.push(ext.subPanel.xAxis)
 *     yAxes.push(ext.subPanel.yAxis); series.push(...ext.subPanel.series)
 *     legendData.push(...ext.subPanel.legend)
 *   }
 *
 * 用户偏好（指标 ID + 显示模式）持久化到 localStorage（per dev plan #5/#7）。
 */
export function useCustomIndicatorOverlay(
  codeRef: { value: string | undefined },
  periodRef: { value: string },
  datesRef: { value: string[] },
  opts: UseOverlayOptions = {},
) {
  const indicatorList = ref<IndicatorListItem[]>([])
  const loadingList = ref(false)
  const selectedId = ref<string>(localStorage.getItem(LS_INDICATOR) || '')
  const mode = ref<OverlayMode>(
    (localStorage.getItem(LS_MODE) as OverlayMode) || 'off')

  const seriesData = ref<SeriesResult | null>(null)
  const loadingSeries = ref(false)
  const errorMsg = ref('')

  const subBottom = opts.subGridBottom ?? '6%'
  const subHeight = opts.subGridHeight ?? '14%'

  const loadList = async () => {
    if (indicatorList.value.length > 0) return
    loadingList.value = true
    try {
      indicatorList.value = await listIndicators()
    } catch (e) {
      indicatorList.value = []
    } finally {
      loadingList.value = false
    }
  }

  const reloadSeries = async () => {
    errorMsg.value = ''
    if (mode.value === 'off' || !selectedId.value || !codeRef.value) {
      seriesData.value = null
      return
    }
    if (!datesRef.value || datesRef.value.length === 0) {
      seriesData.value = null
      return
    }
    const period = periodRef.value || 'daily'
    if (period !== 'daily') {
      // 后端目前仅支持 daily（PR-5 后续可扩展）
      errorMsg.value = '自定义指标当前仅支持日 K 叠加'
      seriesData.value = null
      return
    }
    loadingSeries.value = true
    try {
      seriesData.value = await indicatorSeries({
        indicator_id: selectedId.value,
        code: codeRef.value,
        start: datesRef.value[0],
        end: datesRef.value[datesRef.value.length - 1],
        period: 'daily',
      })
    } catch (e: any) {
      seriesData.value = null
      errorMsg.value = e?.message || '加载指标曲线失败'
    } finally {
      loadingSeries.value = false
    }
  }

  // localStorage 同步
  watch(selectedId, (v) => {
    if (v) localStorage.setItem(LS_INDICATOR, v)
    else localStorage.removeItem(LS_INDICATOR)
    reloadSeries()
  })
  watch(mode, (v) => {
    localStorage.setItem(LS_MODE, v)
    reloadSeries()
  })
  watch([codeRef, periodRef, datesRef], () => reloadSeries(), { deep: true })

  /**
   * 计算最终 ECharts 扩展（合并到页面 baseOption）
   */
  const extension = computed<OverlayExtension>(() => {
    if (mode.value === 'off' || !seriesData.value) return EMPTY
    const dates = datesRef.value
    if (!dates || dates.length === 0) return EMPTY
    const dateIndex: Record<string, number> = {}
    dates.forEach((d, i) => { dateIndex[d] = i })

    const showMain = mode.value === 'main' || mode.value === 'both'
    const showSub = mode.value === 'sub' || mode.value === 'both'

    let mainSignalSeries: any = null
    if (showMain && seriesData.value.signal_points?.length) {
      const buyData: any[] = []
      const sellData: any[] = []
      for (const p of seriesData.value.signal_points as SignalPoint[]) {
        const idx = dateIndex[p.date]
        if (idx == null) continue
        const point = { value: [p.date, p.price], name: p.action, reason: p.reason || '' }
        const act = (p.action || '').toLowerCase()
        if (act.startsWith('sell')) sellData.push(point)
        else buyData.push(point)
      }
      const ciName = seriesData.value.name || '自定义指标'
      // 用文字符号"买"/"卖"，仅 2px 偏移
      mainSignalSeries = {
        name: `${ciName}-信号`,
        type: 'scatter',
        xAxisIndex: 0,
        yAxisIndex: 0,
        symbol: 'circle',
        symbolSize: 18,
        data: [
          ...buyData.map((p) => ({
            ...p,
            symbolOffset: [0, -2],
            itemStyle: { color: '#ec0000', borderColor: '#fff', borderWidth: 1 },
            label: { show: true, formatter: '买', color: '#fff', fontWeight: 'bold', fontSize: 11 },
          })),
          ...sellData.map((p) => ({
            ...p,
            symbolOffset: [0, 2],
            itemStyle: { color: '#00da3c', borderColor: '#fff', borderWidth: 1 },
            label: { show: true, formatter: '卖', color: '#fff', fontWeight: 'bold', fontSize: 11 },
          })),
        ],
        z: 30,
        tooltip: {
          trigger: 'item',
          formatter: (p: any) => {
            const head = `<b>${p.data.name}</b><br/>${p.data.value[0]}<br/>价格: ${p.data.value[1]}`
            return p.data.reason ? `${head}<br/>理由: ${p.data.reason}` : head
          },
        },
      }
    }

    let subPanel: OverlayExtension['subPanel'] = null
    if (showSub && seriesData.value.score_series?.length) {
      const arr: (number | null)[] = new Array(dates.length).fill(null)
      for (const s of seriesData.value.score_series as ScorePoint[]) {
        const idx = dateIndex[s.date]
        if (idx != null) arr[idx] = s.score
      }
      const ciName = seriesData.value.name || '自定义指标'

      // 双线趋势：基于评分序列计算快/慢 EMA，金叉/死叉作为衍生买卖信号
      const fastN = 5
      const slowN = 20
      const ema = (period: number): (number | null)[] => {
        const k = 2 / (period + 1)
        const out: (number | null)[] = new Array(arr.length).fill(null)
        let prev: number | null = null
        for (let i = 0; i < arr.length; i++) {
          const v = arr[i]
          if (v == null) { out[i] = prev; continue }
          prev = prev == null ? v : (v * k + prev * (1 - k))
          out[i] = prev
        }
        return out
      }
      const fast = ema(fastN)
      const slow = ema(slowN)

      // 计算金叉 / 死叉点（用于 tooltip 提示，不在副图上画散点 — 用户可通过两线交叉直接读出）
      // 后端 signal_points（策略真实买卖点）作为可选叠加，颜色更深以区分
      const stratBuy: any[] = []
      const stratSell: any[] = []
      for (const p of (seriesData.value.signal_points || []) as SignalPoint[]) {
        const idx = dateIndex[p.date]
        if (idx == null) continue
        const act = (p.action || '').toLowerCase()
        const yVal = arr[idx] ?? (act.startsWith('sell') ? 25 : 75)
        const point = { value: [p.date, yVal], name: p.action, reason: p.reason || '' }
        if (act.startsWith('sell')) stratSell.push(point)
        else stratBuy.push(point)
      }

      const fastName = `${ciName}-快线(EMA${fastN})`
      const slowName = `${ciName}-慢线(EMA${slowN})`
      const subSeries: any[] = [
        {
          name: fastName,
          type: 'line',
          data: fast,
          connectNulls: true,
          smooth: true,
          symbol: 'none',
          z: 6,
          lineStyle: { width: 1.6, color: '#ec0000' },
        },
        {
          name: slowName,
          type: 'line',
          data: slow,
          connectNulls: true,
          smooth: true,
          symbol: 'none',
          z: 5,
          lineStyle: { width: 1.6, color: '#409eff' },
        },
      ]
      if (stratBuy.length) {
        subSeries.push({
          name: '策略-买',
          type: 'scatter',
          data: stratBuy,
          symbol: 'circle', symbolSize: 16, symbolOffset: [0, -2],
          itemStyle: { color: '#ec0000', borderColor: '#fff', borderWidth: 1 },
          label: { show: true, formatter: '买', color: '#fff', fontWeight: 'bold', fontSize: 10 },
          z: 21,
          tooltip: {
            trigger: 'item',
            formatter: (p: any) => {
              const head = `<b>${p.data.name}</b><br/>${p.data.value[0]}`
              return p.data.reason ? `${head}<br/>理由: ${p.data.reason}` : head
            },
          },
        })
      }
      if (stratSell.length) {
        subSeries.push({
          name: '策略-卖',
          type: 'scatter',
          data: stratSell,
          symbol: 'circle', symbolSize: 16, symbolOffset: [0, 2],
          itemStyle: { color: '#00da3c', borderColor: '#fff', borderWidth: 1 },
          label: { show: true, formatter: '卖', color: '#fff', fontWeight: 'bold', fontSize: 10 },
          z: 21,
          tooltip: {
            trigger: 'item',
            formatter: (p: any) => {
              const head = `<b>${p.data.name}</b><br/>${p.data.value[0]}`
              return p.data.reason ? `${head}<br/>理由: ${p.data.reason}` : head
            },
          },
        })
      }

      subPanel = {
        grid: { left: '8%', right: '3%', height: subHeight, bottom: subBottom },
        xAxis: {
          type: 'category', data: dates,
          boundaryGap: false,
          axisLabel: { show: false }, axisTick: { show: false }, axisLine: { show: false },
        },
        yAxis: {
          scale: false, splitNumber: 3,
          axisLabel: { show: true, fontSize: 9, color: '#999' },
          axisLine: { show: false }, axisTick: { show: false },
          splitLine: { lineStyle: { color: '#f5f5f5' } },
          min: 0, max: 100,
        },
        series: subSeries,
        legend: [fastName, slowName],
      }
    }

    return {
      mainSignalSeries,
      subPanel,
      extraXAxisCount: subPanel ? 1 : 0,
    }
  })

  onMounted(loadList)

  return {
    indicatorList,
    loadingList,
    selectedId,
    mode,
    seriesData,
    loadingSeries,
    errorMsg,
    extension,
    loadList,
    reloadSeries,
  }
}
