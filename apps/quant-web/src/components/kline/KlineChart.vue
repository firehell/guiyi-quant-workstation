<script setup lang="ts">
/**
 * K 线图表组件（Lightweight Charts）：主图 + MACD/ATR 副图联动、
 * marker/overlay、viewport 可见区间上报与 focusTime 对外暴露。
 */
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  TickMarkType,
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type IPriceLine,
  type IRange,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type LineData,
  type LogicalRange,
  type MouseEventParams,
  type SeriesMarker,
  type Time,
  type WhitespaceData,
} from 'lightweight-charts'
import type { HuoTianDaYouPoint } from '@/utils/indicators'
import type {
  BarData,
  ChartOverlay,
  HoverKlineContext,
  IndicatorPanelType,
  KlineMarker,
  LiveMarketBarsQuality,
  MainIndicatorDefinition,
  MainIndicatorId,
  MainIndicatorSeries,
  MainIndicatorValue,
  MarketBarsQuality,
  MarketMacdIndicatorResponse,
} from '@/types/market'
import { calculateATR, calculateHuoTianDaYou, calculateMACD } from '@/utils/indicators'
import { macdOverrideToResult } from '@/utils/macdOverride'
import { MAIN_INDICATOR_DEFINITIONS } from '@/utils/mainIndicators'
import { resolveChartTheme } from '@/styles/chartTheme'
import {
  barTimeMsForBar,
  canonicalBarTimeKey,
  chartLookupKeyForBar,
  chartLookupKeyForTimeString,
  chartTimeKey,
  lookupKeyFromChartTime,
  normalizePeriod,
  toChartTimeForPeriod,
  type ChartTimeValue,
} from '@/utils/barTime'

const LINKED_PRICE_SCALE_MIN_WIDTH = 76
const MAIN_CHART_FALLBACK_HEIGHT = 430
const SUB_CHART_FALLBACK_HEIGHT = 150
const DAILY_WEEKLY_PERIODS = new Set(['1d', '1w'])
const INDICATOR_SCALE_PADDING = 0.12
const INDICATOR_RESCALE_DEBOUNCE_MS = 80
const HTDY_INDICATOR_ID: MainIndicatorId = 'htdy'
const HTDY_UNSTABLE_TAIL_BARS = 25
const HTDY_LINE_KEYS = ['htdy:zk1', 'htdy:zd1', 'htdy:zd2'] as const
const HTDY_LINE_OPTIONS: Record<(typeof HTDY_LINE_KEYS)[number], { label: string; color: string; lineWidth: 1 | 2; lineStyle?: LineStyle }> = {
  'htdy:zk1': { label: 'ZK1', color: '#e2e8f0', lineWidth: 2, lineStyle: LineStyle.Dotted },
  'htdy:zd1': { label: 'ZD1', color: '#fb7185', lineWidth: 2 },
  'htdy:zd2': { label: 'ZD2', color: '#2dd4bf', lineWidth: 2 },
}
type MainIndicatorLineKey = MainIndicatorId | (typeof HTDY_LINE_KEYS)[number]

interface HtdyOverlayShape {
  width: number
  height: number
  bandPath: string
  candles: Array<{
    key: string
    x: number
    yHigh: number
    yLow: number
    yOpen: number
    yClose: number
    width: number
    color: string
    unstable: boolean
  }>
  markers: Array<{
    key: string
    x: number
    y: number
    label: string
    color: string
    unstable: boolean
  }>
}

const props = withDefaults(
  defineProps<{
    bars: BarData[]
    markers?: KlineMarker[]
    activeMarkerId?: string | null
    overlays?: ChartOverlay[]
    loading?: boolean
    error?: string | null
    indicatorPanels?: IndicatorPanelType[]
    mainIndicators?: MainIndicatorId[]
    mainIndicatorSeries?: MainIndicatorSeries[]
    macdOverride?: MarketMacdIndicatorResponse | null
    period?: string
    periodOptions?: { label: string; value: string; disabled?: boolean }[]
    showPeriodToolbar?: boolean
    fitContent?: boolean
    quality?: MarketBarsQuality | LiveMarketBarsQuality | null
  }>(),
  {
    indicatorPanels: () => ['macd', 'atr'],
    mainIndicators: () => [],
    mainIndicatorSeries: () => [],
    periodOptions: () => [],
    showPeriodToolbar: false,
    fitContent: true,
    quality: null,
  },
)

const emit = defineEmits<{
  hover: [context: HoverKlineContext | null]
  'marker-click': [marker: KlineMarker]
  'update:period': [value: string]
  'visible-range-change': [payload: { fromMs: number; toMs: number }]
}>()

const klineShell = ref<HTMLElement>()
const mainWrap = ref<HTMLElement>()
const mainContainer = ref<HTMLElement>()
const macdContainer = ref<HTMLElement>()
const atrContainer = ref<HTMLElement>()
const activePanel = ref<IndicatorPanelType>('macd')
const hoverContext = ref<HoverKlineContext | null>(null)
const linkedCrosshair = ref<{ x: number; top: number; height: number } | null>(null)
const htdyOverlay = ref<HtdyOverlayShape | null>(null)

const indicatorTabs = computed(() => {
  const labels: Record<IndicatorPanelType, string> = {
    macd: 'MACD',
    atr: 'ATR',
    volume_ratio: '量比',
    signal_score: '信号分',
  }
  return props.indicatorPanels.map((value) => ({ label: labels[value] || value, value }))
})

const showIndicatorTabs = computed(() => indicatorTabs.value.length > 1)

function selectPeriod(value: string, disabled?: boolean) {
  if (disabled || !value || value === props.period) return
  emit('update:period', value)
}

function mainIndicatorReadouts(context: HoverKlineContext | null) {
  return context?.mainIndicators || []
}

let mainChart: IChartApi | null = null
let macdChart: IChartApi | null = null
let atrChart: IChartApi | null = null
let candleSeries: ISeriesApi<'Candlestick'> | null = null
let volumeSeries: ISeriesApi<'Histogram'> | null = null
let markerLayer: ISeriesMarkersPluginApi<Time> | null = null
let mainIndicatorLineSeries = new Map<MainIndicatorLineKey, ISeriesApi<'Line'>>()
let macdDifSeries: ISeriesApi<'Line'> | null = null
let macdDeaSeries: ISeriesApi<'Line'> | null = null
let macdHistogramSeries: ISeriesApi<'Histogram'> | null = null
let atrSeries: ISeriesApi<'Line'> | null = null
let resizeObserver: ResizeObserver | null = null
let syncingRange = false
let syncingCrosshair = false
let suppressVisibleRangeEmit = false
let priceLines: IPriceLine[] = []
let renderBarsCache: BarData[] = []
let htdyPointsCache: HuoTianDaYouPoint[] = []
let indicatorRescaleTimer: ReturnType<typeof setTimeout> | null = null
let htdyOverlayFrame: number | null = null
let chartTheme = resolveChartTheme()

const barByTime = new Map<string, BarData>()
const markersByTime = new Map<string, KlineMarker[]>()
const mainIndicatorByTime = new Map<string, MainIndicatorValue[]>()
const macdByTime = new Map<string, { dif?: number; dea?: number; histogram?: number }>()
const atrByTime = new Map<string, number>()

interface HoverLookupOptions {
  allowNearest?: boolean
}

const hasData = computed(() => props.bars.length > 0)

const crossFileConflictCount = computed(() =>
  props.quality && 'cross_file_conflicts' in props.quality ? props.quality.cross_file_conflicts ?? 0 : 0,
)
const hasCrossFileConflicts = computed(() => crossFileConflictCount.value > 0)

watch(
  () => props.indicatorPanels,
  (panels) => {
    if (!panels.includes(activePanel.value)) {
      activePanel.value = panels[0] || 'macd'
    }
  },
  { immediate: true },
)

onMounted(async () => {
  await nextTick()
  createCharts()
  renderSeries()
  observeResize()
})

onUnmounted(() => {
  if (indicatorRescaleTimer) clearTimeout(indicatorRescaleTimer)
  if (htdyOverlayFrame !== null) cancelAnimationFrame(htdyOverlayFrame)
  resizeObserver?.disconnect()
  removePriceLines()
  mainChart?.remove()
  macdChart?.remove()
  atrChart?.remove()
})

watch(
  () => [props.bars, props.markers, props.activeMarkerId, props.overlays, props.mainIndicators, props.mainIndicatorSeries, props.macdOverride, props.fitContent],
  async () => {
    renderSeries({ fitContent: props.fitContent })
    if (props.bars.length > 0 && mainContainer.value && mainContainer.value.clientWidth === 0) {
      await nextTick()
      resizeCharts()
    }
  },
  { deep: true },
)

watch(activePanel, async () => {
  await nextTick()
  resizeCharts()
  syncAllRanges(mainChart?.timeScale().getVisibleLogicalRange() || null, mainChart)
  scheduleIndicatorPriceRescale(mainChart?.timeScale().getVisibleLogicalRange() || null)
  scheduleHtdyOverlayRefresh()
  if (hoverContext.value) syncCrosshairForTime(timeStringToChartTime(hoverContext.value.time))
})

watch(
  () => props.period,
  () => {
    applyTimeDisplayOptions()
  },
)

function isDailyLikePeriod() {
  const period = props.period?.toLowerCase()
  return period ? DAILY_WEEKLY_PERIODS.has(period) : false
}

function pad2(value: number) {
  return String(value).padStart(2, '0')
}

function parseBarDate(value: string) {
  const normalized = String(value).replace(/(?:Z|[+-]\d{2}:\d{2})$/, '')
  const date = new Date(normalized)
  return Number.isFinite(date.getTime()) ? date : null
}

function resolveBarDate(input: string | Time): Date | null {
  if (typeof input === 'object' && input !== null && 'year' in input) {
    return new Date(input.year, input.month - 1, input.day)
  }

  let iso: string | null = null
  if (typeof input === 'string') {
    iso = input
  } else if (typeof input === 'number') {
    iso = barByTime.get(String(input))?.time ?? null
    if (!iso) {
      const date = new Date(input * 1000)
      return Number.isFinite(date.getTime()) ? date : null
    }
  }

  if (!iso) return null
  return parseBarDate(iso)
}

function formatDateParts(date: Date, includeTime: boolean) {
  const dateLabel = `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`
  if (!includeTime) return dateLabel
  return `${dateLabel} ${pad2(date.getHours())}:${pad2(date.getMinutes())}`
}

function formatKlineTimeLabel(input: string | Time): string {
  const date = resolveBarDate(input)
  if (!date) return '-'
  return formatDateParts(date, !isDailyLikePeriod())
}

function formatChartTime(time: Time) {
  return formatKlineTimeLabel(time)
}

function formatChartTickMark(time: Time, tickMarkType: TickMarkType) {
  const date = resolveBarDate(time)
  if (!date) return null

  if (tickMarkType === TickMarkType.Time || tickMarkType === TickMarkType.TimeWithSeconds) {
    if (isDailyLikePeriod()) return `${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`
    return `${pad2(date.getHours())}:${pad2(date.getMinutes())}`
  }

  if (tickMarkType === TickMarkType.Year) return String(date.getFullYear())
  return `${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`
}

function sharedTimeDisplayOptions() {
  return {
    localization: {
      locale: 'zh-CN',
      timeFormatter: formatChartTime,
    },
    timeScale: {
      borderColor: chartTheme.axis,
      timeVisible: true,
      secondsVisible: false,
      tickMarkFormatter: formatChartTickMark,
    },
  }
}

function applyTimeDisplayOptions() {
  const options = sharedTimeDisplayOptions()
  mainChart?.applyOptions(options)
  macdChart?.applyOptions(options)
  atrChart?.applyOptions(options)
}

function linkedCrosshairOptions() {
  return {
    mode: CrosshairMode.Normal,
    vertLine: {
      visible: false,
      labelVisible: false,
    },
    horzLine: {
      visible: true,
      labelVisible: true,
      style: LineStyle.Dashed,
    },
  } as const
}

function mainCrosshairOptions() {
  return {
    mode: CrosshairMode.Normal,
    vertLine: {
      visible: false,
      labelVisible: false,
    },
    horzLine: {
      visible: true,
      labelVisible: true,
      style: LineStyle.Dashed,
    },
  } as const
}

/** 初始化主图与 MACD/ATR 副图，绑定联动控制器与可见区间事件。 */
function createCharts() {
  if (!mainContainer.value || !macdContainer.value || !atrContainer.value) return
  chartTheme = resolveChartTheme(klineShell.value || document.documentElement)

  const mainHeight = mainContainer.value.clientHeight || MAIN_CHART_FALLBACK_HEIGHT
  mainChart = createChart(mainContainer.value, {
    width: mainContainer.value.clientWidth,
    height: mainHeight,
    layout: {
      background: { type: ColorType.Solid, color: chartTheme.background },
      textColor: chartTheme.text,
      attributionLogo: false,
    },
    grid: {
      vertLines: { color: chartTheme.grid },
      horzLines: { color: chartTheme.grid },
    },
    rightPriceScale: {
      borderColor: chartTheme.axis,
      minimumWidth: LINKED_PRICE_SCALE_MIN_WIDTH,
      scaleMargins: { top: 0.08, bottom: 0.22 },
    },
    ...sharedTimeDisplayOptions(),
    crosshair: mainCrosshairOptions(),
  })

  candleSeries = mainChart.addSeries(CandlestickSeries, {
    upColor: chartTheme.up,
    downColor: chartTheme.down,
    borderUpColor: chartTheme.up,
    borderDownColor: chartTheme.down,
    wickUpColor: chartTheme.up,
    wickDownColor: chartTheme.down,
  })
  markerLayer = createSeriesMarkers(candleSeries, [])
  syncMainIndicatorSeries(activeMainIndicatorDefinitions())
  volumeSeries = mainChart.addSeries(HistogramSeries, {
    priceFormat: { type: 'volume' },
    priceScaleId: '',
    priceLineVisible: false,
    lastValueVisible: false,
  })
  mainChart.priceScale('').applyOptions({ scaleMargins: { top: 0.78, bottom: 0 } })

  const macdHeight = macdContainer.value.clientHeight || SUB_CHART_FALLBACK_HEIGHT
  macdChart = createSubChart(macdContainer.value, macdHeight)
  macdHistogramSeries = macdChart.addSeries(HistogramSeries, {
    priceLineVisible: false,
    lastValueVisible: false,
  })
  macdDifSeries = macdChart.addSeries(LineSeries, {
    color: chartTheme.macdDif,
    lineWidth: 1,
    priceLineVisible: false,
    lastValueVisible: false,
  })
  macdDeaSeries = macdChart.addSeries(LineSeries, {
    color: chartTheme.macdDea,
    lineWidth: 1,
    priceLineVisible: false,
    lastValueVisible: false,
  })

  const atrHeight = atrContainer.value.clientHeight || SUB_CHART_FALLBACK_HEIGHT
  atrChart = createSubChart(atrContainer.value, atrHeight)
  atrSeries = atrChart.addSeries(LineSeries, {
    color: chartTheme.atr,
    lineWidth: 1,
    priceLineVisible: false,
    lastValueVisible: false,
  })
  setupLinkedChartController()
}

function createSubChart(container: HTMLElement, height: number) {
  return createChart(container, {
    width: container.clientWidth,
    height,
    layout: {
      background: { type: ColorType.Solid, color: chartTheme.background },
      textColor: chartTheme.textMuted,
      attributionLogo: false,
    },
    grid: {
      vertLines: { color: chartTheme.grid },
      horzLines: { color: chartTheme.grid },
    },
    rightPriceScale: {
      borderColor: chartTheme.axis,
      minimumWidth: LINKED_PRICE_SCALE_MIN_WIDTH,
      autoScale: true,
      scaleMargins: { top: 0.12, bottom: 0.12 },
    },
    ...sharedTimeDisplayOptions(),
    crosshair: linkedCrosshairOptions(),
  })
}

function setupLinkedChartController() {
  mainChart?.timeScale().subscribeVisibleLogicalRangeChange((range) => {
    syncAllRanges(range, mainChart)
    emitVisibleRangeChange()
  })
  macdChart?.timeScale().subscribeVisibleLogicalRangeChange((range) => syncAllRanges(range, macdChart))
  atrChart?.timeScale().subscribeVisibleLogicalRangeChange((range) => syncAllRanges(range, atrChart))
  mainChart?.subscribeCrosshairMove((param) => syncCrosshair(param, mainChart))
  mainChart?.subscribeClick(handleChartClick)
  macdChart?.subscribeCrosshairMove((param) => syncCrosshair(param, macdChart))
  atrChart?.subscribeCrosshairMove((param) => syncCrosshair(param, atrChart))
}

function chartTimeToMs(time: Time): number | null {
  const date = resolveBarDate(time)
  return date ? date.getTime() : null
}

/** 向父组件上报可见时间范围，供 viewport 懒加载 K 线。 */
function emitVisibleRangeChange() {
  if (suppressVisibleRangeEmit || syncingRange || !mainChart) return
  const visibleRange = mainChart.timeScale().getVisibleRange()
  if (!visibleRange) return
  const fromMs = chartTimeToMs(visibleRange.from)
  const toMs = chartTimeToMs(visibleRange.to)
  if (fromMs === null || toMs === null) return
  emit('visible-range-change', { fromMs, toMs })
}

/** 根据 props 重绘 K 线、成交量、主图指标、MACD/ATR 与 marker。 */
function renderSeries(options: { fitContent?: boolean } = {}) {
  if (!candleSeries || !volumeSeries || !macdDifSeries || !macdDeaSeries || !macdHistogramSeries || !atrSeries) return

  const renderBars = dedupeRenderBarsByChartTime(normalizedBars())
  const activeDefinitions = activeMainIndicatorDefinitions()
  syncMainIndicatorSeries(activeDefinitions)
  renderBarsCache = renderBars
  rebuildLookupMaps(renderBars, activeDefinitions)
  const candleData = dedupeCandlestickData(
    renderBars.map((bar) => ({
      time: barChartTime(bar),
      open: bar.open,
      high: bar.high,
      low: bar.low,
      close: bar.close,
    })),
  )
  const volumeData = dedupeHistogramData(
    renderBars.map((bar) => ({
      time: barChartTime(bar),
      value: bar.volume,
      color: bar.close >= bar.open ? chartTheme.volumeUp : chartTheme.volumeDown,
    })),
  )
  const chartTimes = candleData.map((item) => item.time)
  const macd = macdOverrideToResult(props.macdOverride) || calculateMACD(renderBars)
  const macdDifData = toAlignedLineData(chartTimes, macd.dif)
  const macdDeaData = toAlignedLineData(chartTimes, macd.dea)
  const macdHistogramData = toAlignedHistogramData(chartTimes, macd.histogram)
  const atrData = toAlignedLineData(chartTimes, calculateATR(renderBars, 14))
  const htdyResult = hasHtdyObservation() ? calculateHuoTianDaYou(renderBars) : { points: [] }
  htdyPointsCache = htdyResult.points

  candleSeries.setData(candleData)
  markerLayer?.setMarkers(toSeriesMarkers(props.markers || [], props.activeMarkerId || null))
  volumeSeries.setData(volumeData)
  activeDefinitions.forEach((definition) => {
    const apiSeries = props.mainIndicatorSeries?.find((item) => item.id === definition.id)
    mainIndicatorLineSeries.get(definition.id)?.setData(toAlignedLineData(chartTimes, indicatorLinePoints(apiSeries)))
  })
  mainIndicatorLineSeries
    .get('htdy:zk1')
    ?.setData(toAlignedLineData(chartTimes, htdyResult.points.map((point) => ({ time: point.time, value: point.zk1 })).filter(hasPointValue)))
  mainIndicatorLineSeries
    .get('htdy:zd1')
    ?.setData(toAlignedLineData(chartTimes, htdyResult.points.map((point) => ({ time: point.time, value: point.zd1 })).filter(hasPointValue)))
  mainIndicatorLineSeries
    .get('htdy:zd2')
    ?.setData(toAlignedLineData(chartTimes, htdyResult.points.map((point) => ({ time: point.time, value: point.zd2 })).filter(hasPointValue)))
  macdDifSeries.setData(macdDifData)
  macdDeaSeries.setData(macdDeaData)
  macdHistogramSeries.setData(macdHistogramData)
  atrSeries.setData(atrData)
  applyPriceLines()
  clearLinkedCrosshairs(null)
  if (renderBars.length > 0) {
    if (options.fitContent !== false) {
      suppressVisibleRangeEmit = true
      mainChart?.timeScale().fitContent()
      macdChart?.timeScale().fitContent()
      atrChart?.timeScale().fitContent()
      requestAnimationFrame(() => {
        suppressVisibleRangeEmit = false
        emitVisibleRangeChange()
      })
    }
    const activeMarker = (props.markers || []).find((marker) => marker.id === props.activeMarkerId)
    const hoverBar = renderBars.at(-1)!
    setHoverContextForTime(activeMarker ? timeStringToChartTime(activeMarker.time) : barChartTime(hoverBar))
    scheduleIndicatorPriceRescale(mainChart?.timeScale().getVisibleLogicalRange() || null)
    scheduleHtdyOverlayRefresh()
  } else {
    renderBarsCache = []
    htdyPointsCache = []
    htdyOverlay.value = null
    clearHover()
  }
}

function normalizedPeriod() {
  return normalizePeriod(props.period)
}

function dedupeRenderBarsByChartTime(bars: BarData[]): BarData[] {
  const period = normalizedPeriod()
  const byKey = new Map<string, BarData>()
  bars.forEach((bar) => {
    byKey.set(chartTimeKey(toChartTimeForPeriod(bar, period)), bar)
  })
  return [...byKey.values()].sort((left, right) => barTimeMsForBar(left, period) - barTimeMsForBar(right, period))
}

function dedupeCandlestickData(data: CandlestickData<Time>[]): CandlestickData<Time>[] {
  const byKey = new Map<string, CandlestickData<Time>>()
  data.forEach((item) => byKey.set(chartTimeKey(item.time as ChartTimeValue), item))
  return [...byKey.values()]
}

function dedupeHistogramData(data: HistogramData<Time>[]): HistogramData<Time>[] {
  const byKey = new Map<string, HistogramData<Time>>()
  data.forEach((item) => byKey.set(chartTimeKey(item.time as ChartTimeValue), item))
  return [...byKey.values()]
}

function normalizedBars() {
  const period = normalizedPeriod()
  const byTime = new Map<string, BarData>()
  props.bars.forEach((bar) => {
    byTime.set(canonicalBarTimeKey(bar, period), bar)
  })
  return [...byTime.values()].sort((first, second) => barTimeMsForBar(first, period) - barTimeMsForBar(second, period))
}

function activeMainIndicatorDefinitions() {
  const selected = new Set(props.mainIndicators || [])
  return MAIN_INDICATOR_DEFINITIONS.filter(
    (definition) => definition.available && definition.renderer === 'line' && selected.has(definition.id),
  )
}

function hasHtdyObservation() {
  return (props.mainIndicators || []).includes(HTDY_INDICATOR_ID)
}

function syncMainIndicatorSeries(activeDefinitions: MainIndicatorDefinition[]) {
  if (!mainChart) return
  const activeIds = new Set<MainIndicatorLineKey>(activeDefinitions.map((definition) => definition.id))
  if (hasHtdyObservation()) HTDY_LINE_KEYS.forEach((key) => activeIds.add(key))
  activeDefinitions.forEach((definition) => {
    const existing = mainIndicatorLineSeries.get(definition.id)
    const options = {
      color: definition.color,
      lineWidth: definition.id === 'ema_21' ? 2 : 1,
      priceLineVisible: false,
      lastValueVisible: false,
      visible: true,
    } as const
    if (existing) {
      existing.applyOptions(options)
      return
    }
    mainIndicatorLineSeries.set(definition.id, mainChart!.addSeries(LineSeries, options))
  })
  if (hasHtdyObservation()) {
    HTDY_LINE_KEYS.forEach((key) => {
      if (mainIndicatorLineSeries.has(key)) return
      const option = HTDY_LINE_OPTIONS[key]
      mainIndicatorLineSeries.set(
        key,
        mainChart!.addSeries(LineSeries, {
          color: option.color,
          lineWidth: option.lineWidth,
          lineStyle: option.lineStyle ?? LineStyle.Solid,
          priceLineVisible: false,
          lastValueVisible: false,
          visible: true,
        }),
      )
    })
  }
  mainIndicatorLineSeries.forEach((series, id) => {
    if (!activeIds.has(id)) {
      series.setData([])
      series.applyOptions({ visible: false })
    }
  })
}

function rebuildLookupMaps(renderBars: BarData[], activeDefinitions: MainIndicatorDefinition[]) {
  barByTime.clear()
  markersByTime.clear()
  mainIndicatorByTime.clear()
  macdByTime.clear()
  atrByTime.clear()
  renderBars.forEach((bar) => barByTime.set(chartLookupKeyForBar(bar, props.period), bar))
  ;(props.markers || []).forEach((marker) => {
    const key = chartLookupKeyForTimeString(marker.time, props.period)
    markersByTime.set(key, [...(markersByTime.get(key) || []), marker])
  })
  activeDefinitions.forEach((definition) => {
    const apiSeries = props.mainIndicatorSeries?.find((item) => item.id === definition.id)
    ;(apiSeries?.points || []).forEach((point) => {
      const key = pointLookupKey(point.time)
      const value: MainIndicatorValue = {
        id: definition.id,
        displayName: definition.displayName,
        color: definition.color,
        value: point.ready && point.valid ? point.value : null,
        ready: point.ready,
        valid: point.valid,
        reason: point.reason || null,
      }
      mainIndicatorByTime.set(key, [...(mainIndicatorByTime.get(key) || []), value])
    })
  })
  if (hasHtdyObservation()) {
    const definition = MAIN_INDICATOR_DEFINITIONS.find((item) => item.id === HTDY_INDICATOR_ID)
    calculateHuoTianDaYou(renderBars).points.forEach((point, index, points) => {
      const key = pointLookupKey(point.time)
      const unstable = isHtdyUnstableIndex(index, points.length)
      const values = [
        htdyHoverValue(definition, 'ZK1', point.zk1, unstable),
        htdyHoverValue(definition, 'ZD1', point.zd1, unstable),
        htdyHoverValue(definition, 'ZD2', point.zd2, unstable),
      ]
      mainIndicatorByTime.set(key, [...(mainIndicatorByTime.get(key) || []), ...values])
    })
  }
  const macd = macdOverrideToResult(props.macdOverride) || calculateMACD(renderBars)
  macd.dif.forEach((point) => {
    const key = pointLookupKey(point.time)
    macdByTime.set(key, { ...macdByTime.get(key), dif: point.value })
  })
  macd.dea.forEach((point) => {
    const key = pointLookupKey(point.time)
    macdByTime.set(key, { ...macdByTime.get(key), dea: point.value })
  })
  macd.histogram.forEach((point) => {
    const key = pointLookupKey(point.time)
    macdByTime.set(key, { ...macdByTime.get(key), histogram: point.value })
  })
  calculateATR(renderBars, 14).forEach((point) =>
    atrByTime.set(pointLookupKey(point.time), point.value),
  )
}

function pointLookupKey(time: Time | string): string {
  if (typeof time === 'string') return chartLookupKeyForTimeString(time, props.period)
  return lookupKeyFromChartTime(time)
}

function toAlignedLineData(chartTimes: Time[], points: Array<{ time: Time | string; value: number }>): Array<LineData<Time> | WhitespaceData<Time>> {
  const values = new Map(points.map((point) => [pointLookupKey(point.time), point.value]))
  return chartTimes.map((time) => {
    const value = values.get(lookupKeyFromChartTime(time))
    return value === undefined ? { time } : { time, value }
  })
}

function indicatorLinePoints(series: MainIndicatorSeries | undefined) {
  return (series?.points || [])
    .filter((point) => point.ready && point.valid && typeof point.value === 'number')
    .map((point) => ({ time: point.time, value: point.value as number }))
}

function hasPointValue(point: { time: Time | string; value: number | null }): point is { time: Time | string; value: number } {
  return typeof point.value === 'number' && Number.isFinite(point.value)
}

function isHtdyUnstableIndex(index: number, length: number) {
  return index >= Math.max(0, length - HTDY_UNSTABLE_TAIL_BARS)
}

function htdyHoverValue(
  definition: MainIndicatorDefinition | undefined,
  label: string,
  value: number | null,
  unstable: boolean,
): MainIndicatorValue {
  return {
    id: HTDY_INDICATOR_ID,
    displayName: unstable ? `${label}(unstable)` : label,
    color: definition?.color || '#2dd4bf',
    value,
    ready: value !== null,
    valid: value !== null && !unstable,
    reason: unstable ? '未来引用 / 重绘风险：尾部观察点可能重绘' : null,
  }
}

function toAlignedHistogramData(
  chartTimes: Time[],
  points: Array<{ time: Time | string; value: number }>,
): Array<HistogramData<Time> | WhitespaceData<Time>> {
  const values = new Map(points.map((point) => [pointLookupKey(point.time), point.value]))
  return chartTimes.map((time) => {
    const value = values.get(lookupKeyFromChartTime(time))
    if (value === undefined) return { time }
    return {
      time,
      value,
      color: value >= 0 ? chartTheme.volumeUp : chartTheme.volumeDown,
    }
  })
}

function syncAllRanges(range: LogicalRange | null, source: IChartApi | null) {
  if (!range || syncingRange) return
  syncingRange = true
  ;[mainChart, macdChart, atrChart].forEach((chart) => {
    if (chart && chart !== source) chart.timeScale().setVisibleLogicalRange(range)
  })
  syncingRange = false
  scheduleIndicatorPriceRescale(range)
  scheduleHtdyOverlayRefresh()
}

function visibleBarIndexRange(range: IRange<number>, barCount: number) {
  const from = Math.max(0, Math.ceil(range.from))
  const to = Math.min(barCount - 1, Math.floor(range.to))
  if (from > to) return null
  return { from, to }
}

function paddedPriceRange(min: number, max: number) {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return null
  if (min === max) {
    const pad = Math.max(Math.abs(min) * 0.1, 1)
    return { from: min - pad, to: max + pad }
  }
  const span = max - min
  const pad = span * INDICATOR_SCALE_PADDING
  return { from: min - pad, to: max + pad }
}

function applyIndicatorPriceRange(chart: IChartApi | null, from: number, to: number) {
  if (!chart) return
  const priceScale = chart.priceScale('right')
  priceScale.applyOptions({ autoScale: false })
  priceScale.setVisibleRange({ from, to })
}

function resyncIndicatorPriceScales(range: IRange<number> | null) {
  if (!range || renderBarsCache.length === 0) return
  const indexes = visibleBarIndexRange(range, renderBarsCache.length)
  if (!indexes) return

  let macdMin = Infinity
  let macdMax = -Infinity
  let atrMin = Infinity
  let atrMax = -Infinity

  for (let index = indexes.from; index <= indexes.to; index += 1) {
    const key = chartLookupKeyForBar(renderBarsCache[index], props.period)
    const macd = macdByTime.get(key)
    if (macd) {
      for (const value of [macd.dif, macd.dea, macd.histogram]) {
        if (value === undefined || !Number.isFinite(value)) continue
        macdMin = Math.min(macdMin, value)
        macdMax = Math.max(macdMax, value)
      }
    }
    const atr = atrByTime.get(key)
    if (atr !== undefined && Number.isFinite(atr)) {
      atrMin = Math.min(atrMin, atr)
      atrMax = Math.max(atrMax, atr)
    }
  }

  if (Number.isFinite(macdMin) && Number.isFinite(macdMax)) {
    macdMin = Math.min(macdMin, 0)
    macdMax = Math.max(macdMax, 0)
    const macdRange = paddedPriceRange(macdMin, macdMax)
    if (macdRange && isChartVisible(macdChart)) {
      applyIndicatorPriceRange(macdChart, macdRange.from, macdRange.to)
    }
  }

  if (Number.isFinite(atrMin) && Number.isFinite(atrMax)) {
    const atrRange = paddedPriceRange(atrMin, atrMax)
    if (atrRange && isChartVisible(atrChart)) {
      applyIndicatorPriceRange(atrChart, atrRange.from, atrRange.to)
    }
  }
}

function scheduleIndicatorPriceRescale(range: IRange<number> | null) {
  if (indicatorRescaleTimer) clearTimeout(indicatorRescaleTimer)
  indicatorRescaleTimer = setTimeout(() => {
    indicatorRescaleTimer = null
    resyncIndicatorPriceScales(range ?? mainChart?.timeScale().getVisibleLogicalRange() ?? null)
  }, INDICATOR_RESCALE_DEBOUNCE_MS)
}

function scheduleHtdyOverlayRefresh() {
  if (typeof requestAnimationFrame === 'undefined') return
  if (htdyOverlayFrame !== null) cancelAnimationFrame(htdyOverlayFrame)
  htdyOverlayFrame = requestAnimationFrame(() => {
    htdyOverlayFrame = null
    updateHtdyOverlay()
  })
}

function updateHtdyOverlay() {
  if (!hasHtdyObservation() || !mainContainer.value || !mainChart || !candleSeries || renderBarsCache.length === 0 || htdyPointsCache.length === 0) {
    htdyOverlay.value = null
    return
  }
  const range = mainChart.timeScale().getVisibleLogicalRange()
  if (!range) {
    htdyOverlay.value = null
    return
  }
  const indexes = visibleBarIndexRange(range, renderBarsCache.length)
  if (!indexes) {
    htdyOverlay.value = null
    return
  }
  const width = mainContainer.value.clientWidth
  const height = mainContainer.value.clientHeight
  const visiblePoints = htdyPointsCache.slice(indexes.from, indexes.to + 1)
  const visibleBars = renderBarsCache.slice(indexes.from, indexes.to + 1)
  const coordinates = visiblePoints.map((point, localIndex) => {
    const globalIndex = indexes.from + localIndex
    const bar = visibleBars[localIndex]
    const x = mainChart!.timeScale().timeToCoordinate(barChartTime(bar))
    return {
      point,
      bar,
      x,
      unstable: isHtdyUnstableIndex(globalIndex, htdyPointsCache.length),
      zk1: coordinateForPrice(point.zk1),
      zd1: coordinateForPrice(point.zd1),
      zd2: coordinateForPrice(point.zd2),
    }
  })
  const bandPoints = coordinates.filter(
    (item): item is typeof item & { x: number; zd1: number; zd2: number } =>
      item.x !== null &&
      item.x !== undefined &&
      Number.isFinite(item.x) &&
      item.zd1 !== null &&
      item.zd1 !== undefined &&
      Number.isFinite(item.zd1) &&
      item.zd2 !== null &&
      item.zd2 !== undefined &&
      Number.isFinite(item.zd2),
  )
  const bandPath =
    bandPoints.length >= 2
      ? [
          `M ${bandPoints[0].x} ${bandPoints[0].zd1}`,
          ...bandPoints.slice(1).map((item) => `L ${item.x} ${item.zd1}`),
          ...bandPoints
            .slice()
            .reverse()
            .map((item) => `L ${item.x} ${item.zd2}`),
          'Z',
        ].join(' ')
      : ''
  const candleWidth = resolveHtdyOverlayCandleWidth(bandPoints.map((item) => item.x))
  const candles = coordinates
    .map((item) => {
      if (item.x === null || item.x === undefined || !Number.isFinite(item.x)) return null
      if (!item.point.yellowCandle && !item.point.whiteCandle) return null
      const yHigh = coordinateForPrice(item.bar.high)
      const yLow = coordinateForPrice(item.bar.low)
      const yOpen = coordinateForPrice(item.bar.open)
      const yClose = coordinateForPrice(item.bar.close)
      if ([yHigh, yLow, yOpen, yClose].some((value) => value === null || value === undefined || !Number.isFinite(value))) return null
      return {
        key: String(item.point.time),
        x: item.x,
        yHigh: yHigh!,
        yLow: yLow!,
        yOpen: yOpen!,
        yClose: yClose!,
        width: candleWidth,
        color: item.point.yellowCandle ? '#facc15' : '#f8fafc',
        unstable: item.unstable,
      }
    })
    .filter((item): item is NonNullable<typeof item> => Boolean(item))
  const markers = coordinates
    .flatMap((item) => {
      if (item.x === null || item.x === undefined || !Number.isFinite(item.x)) return []
      const yLow = coordinateForPrice(item.bar.low)
      const yHigh = coordinateForPrice(item.bar.high)
      const result: HtdyOverlayShape['markers'] = []
      const suffix = item.unstable ? '(unstable)' : ''
      if (item.point.buyObservation && yLow !== null && yLow !== undefined) {
        result.push({ key: `${item.point.time}-buy`, x: item.x, y: yLow + 18, label: `买多观察${suffix}`, color: '#facc15', unstable: item.unstable })
      }
      if (item.point.sellObservation && yHigh !== null && yHigh !== undefined) {
        result.push({ key: `${item.point.time}-sell`, x: item.x, y: yHigh - 10, label: `卖空观察${suffix}`, color: '#f8fafc', unstable: item.unstable })
      }
      if (item.point.xgObservation && yLow !== null && yLow !== undefined) {
        result.push({ key: `${item.point.time}-xg`, x: item.x, y: yLow + 34, label: `XG观察${suffix}`, color: '#ef4444', unstable: item.unstable })
      }
      return result
    })
    .filter((item) => Number.isFinite(item.y))
  htdyOverlay.value = { width, height, bandPath, candles, markers }
}

function coordinateForPrice(price: number | null) {
  if (price === null || price === undefined || !Number.isFinite(price)) return null
  return candleSeries?.priceToCoordinate(price) ?? null
}

function resolveHtdyOverlayCandleWidth(xs: number[]) {
  if (xs.length < 2) return 6
  const distances = xs.slice(1).map((x, index) => Math.abs(x - xs[index])).filter((value) => value > 0)
  const minDistance = distances.length ? Math.min(...distances) : 8
  return Math.max(2, Math.min(10, minDistance * 0.45))
}

function syncCrosshair(param: MouseEventParams<Time>, source: IChartApi | null) {
  if (syncingCrosshair) return
  const isMainSource = source === mainChart
  const cursorPrice =
    isMainSource && candleSeries && param.point && Number.isFinite(param.point.y)
      ? candleSeries.coordinateToPrice(param.point.y)
      : null

  let linkedTime = param.time ?? null
  if (!linkedTime && param.point && source && Number.isFinite(param.point.x)) {
    linkedTime = source.timeScale().coordinateToTime(param.point.x) ?? null
  }

  if (!linkedTime && !param.point) {
    clearLinkedCrosshairs(source)
    clearHover()
    return
  }

  if (linkedTime) {
    setHoverContextForTime(linkedTime, undefined, cursorPrice)
  } else {
    clearHover()
  }

  if (param.point && Number.isFinite(param.point.x)) {
    updateLinkedCrosshairFromPoint(source, param.point, linkedTime)
  } else if (linkedTime) {
    updateLinkedCrosshairForTime(linkedTime)
  }

  syncingCrosshair = false
}

function handleChartClick(param: MouseEventParams<Time>) {
  const marker = markerFromClick(param)
  if (!marker) return
  const time = timeStringToChartTime(marker.time)
  setHoverContextForTime(time, marker.id)
  syncCrosshairForTime(time)
  emit('marker-click', marker)
}

function markerFromClick(param: MouseEventParams<Time>) {
  const hoveredObjectId = markerObjectId(param.hoveredInfo?.objectId ?? param.hoveredObjectId)
  if (param.hoveredInfo?.objectKind === 'series-marker' && hoveredObjectId) {
    const hovered = (props.markers || []).find((marker) => marker.id === hoveredObjectId)
    if (hovered) return hovered
  }
  if (!param.time) return null
  const candidates = markersByTime.get(param.time ? lookupKeyFromChartTime(param.time) : '') || []
  return candidates.find((marker) => marker.id.startsWith('signal-')) || candidates[0] || null
}

function markerObjectId(value: unknown) {
  if (typeof value === 'string') return value
  if (typeof value === 'number') return String(value)
  return null
}

function clearLinkedCrosshairs(source: IChartApi | null) {
  if (syncingCrosshair) return
  syncingCrosshair = true
  linkedCrosshair.value = null
  if (source !== mainChart && isChartVisible(mainChart)) mainChart?.clearCrosshairPosition()
  if (source !== macdChart && isChartVisible(macdChart)) macdChart?.clearCrosshairPosition()
  if (source !== atrChart && isChartVisible(atrChart)) atrChart?.clearCrosshairPosition()
  syncingCrosshair = false
}

function syncCrosshairForTime(time: Time) {
  const key = lookupKeyFromChartTime(time)
  const bar = barByTime.get(key)
  const macd = macdByTime.get(key)
  const atr = atrByTime.get(key)
  updateLinkedCrosshairForTime(time)
  syncingCrosshair = true
  if (isChartVisible(mainChart) && bar && candleSeries) mainChart?.setCrosshairPosition(bar.close, time, candleSeries)
  if (isChartVisible(macdChart) && macdHistogramSeries && macd) macdChart?.setCrosshairPosition(macd.histogram ?? macd.dif ?? 0, time, macdHistogramSeries)
  if (isChartVisible(atrChart) && atrSeries && atr !== undefined) atrChart?.setCrosshairPosition(atr, time, atrSeries)
  syncingCrosshair = false
}

function updateLinkedCrosshairFromPoint(
  source: IChartApi | null,
  point: MouseEventParams<Time>['point'] | undefined,
  time: Time | null,
) {
  if (!point || !Number.isFinite(point.x)) {
    if (time) updateLinkedCrosshairForTime(time)
    return
  }
  const sourceContainer = chartContainerFor(source) || mainContainer.value
  updateLinkedCrosshair(sourceContainer, point.x)
}

function resolveNearestBarTime(time: Time): Time | null {
  const key = lookupKeyFromChartTime(time)
  if (barByTime.has(key)) return time
  const renderBars = renderBarsCache
  if (!renderBars.length) return null
  const targetMs = chartTimeToMs(time)
  if (targetMs === null) return null
  let nearest = 0
  let distance = Math.abs(barTimeMsForBar(renderBars[0], props.period) - targetMs)
  for (let index = 1; index < renderBars.length; index += 1) {
    const currentDistance = Math.abs(barTimeMsForBar(renderBars[index], props.period) - targetMs)
    if (currentDistance < distance) {
      nearest = index
      distance = currentDistance
    }
  }
  return barChartTime(renderBars[nearest])
}

function updateLinkedCrosshairForTime(time: Time) {
  const coordinate = mainChart?.timeScale().timeToCoordinate(time)
  if (coordinate === null || coordinate === undefined || !Number.isFinite(coordinate)) {
    linkedCrosshair.value = null
    return
  }
  updateLinkedCrosshair(mainContainer.value, coordinate)
}

function updateLinkedCrosshair(sourceContainer: HTMLElement | undefined, localX: number) {
  if (!klineShell.value || !sourceContainer || !Number.isFinite(localX)) {
    linkedCrosshair.value = null
    return
  }
  const shellRect = klineShell.value.getBoundingClientRect()
  const sourceRect = sourceContainer.getBoundingClientRect()
  const targetContainer = activePanel.value === 'atr' ? atrContainer.value : macdContainer.value
  const bottomRect = (targetContainer || mainContainer.value)?.getBoundingClientRect()
  const topRect = (mainWrap.value || mainContainer.value || sourceContainer).getBoundingClientRect()
  if (!bottomRect || !topRect) {
    linkedCrosshair.value = null
    return
  }
  const x = sourceRect.left - shellRect.left + localX
  linkedCrosshair.value = {
    x: Math.max(0, Math.min(shellRect.width, x)),
    top: Math.max(0, topRect.top - shellRect.top),
    height: Math.max(0, bottomRect.bottom - topRect.top),
  }
}

function chartContainerFor(chart: IChartApi | null) {
  if (chart === mainChart) return mainContainer.value
  if (chart === macdChart) return macdContainer.value
  if (chart === atrChart) return atrContainer.value
  return null
}

function isChartVisible(chart: IChartApi | null) {
  if (!chart) return false
  if (chart === mainChart) return Boolean(mainContainer.value?.clientWidth)
  if (chart === macdChart) return activePanel.value === 'macd' && Boolean(macdContainer.value?.clientWidth)
  if (chart === atrChart) return activePanel.value === 'atr' && Boolean(atrContainer.value?.clientWidth)
  return false
}

function setHoverContextForTime(time: Time, preferredMarkerId?: string, cursorPrice?: number | null, options: HoverLookupOptions = {}) {
  const hoverTime = options.allowNearest ? resolveNearestBarTime(time) ?? time : time
  const key = lookupKeyFromChartTime(hoverTime)
  const bar = barByTime.get(key)
  if (!bar) {
    clearHover()
    return false
  }
  const markers = markersByTime.get(key) || []
  const marker =
    (preferredMarkerId ? markers.find((item) => item.id === preferredMarkerId) : null) ||
    markers.find((item) => item.id.startsWith('signal-')) ||
    markers[0] ||
    null
  const context: HoverKlineContext = {
    time: bar.time,
    bar,
    mainIndicators: mainIndicatorByTime.get(key) || [],
    ema21: mainIndicatorByTime.get(key)?.find((item) => item.id === 'ema_21')?.value ?? null,
    macd: macdByTime.get(key) || null,
    atr: atrByTime.get(key) ?? null,
    marker,
    cursorPrice: cursorPrice ?? null,
  }
  hoverContext.value = context
  emit('hover', context)
  return true
}

function clearHover() {
  hoverContext.value = null
  emit('hover', null)
}

function handleChartShellLeave() {
  clearLinkedCrosshairs(null)
  clearHover()
}

function toSeriesMarkers(markers: KlineMarker[], activeMarkerId: string | null): SeriesMarker<Time>[] {
  return markers.map((marker) => ({
    id: marker.id,
    time: timeStringToChartTime(marker.time),
    position: marker.position,
    shape: marker.shape,
    color: marker.id === activeMarkerId ? chartTheme.ema : marker.color,
    text: marker.label,
    size: marker.id === activeMarkerId ? 2 : 1,
  }))
}

function applyPriceLines() {
  if (!candleSeries) return
  removePriceLines()
  ;(props.overlays || [])
    .filter((overlay) => overlay.type === 'price_line' && typeof overlay.price === 'number')
    .forEach((overlay) => {
      priceLines.push(
        candleSeries!.createPriceLine({
          price: overlay.price!,
          color: overlay.color,
          lineWidth: 1,
          lineStyle: toLineStyle(overlay.lineStyle),
          axisLabelVisible: true,
          title: overlay.label,
        }),
      )
    })
}

function removePriceLines() {
  if (!candleSeries) {
    priceLines = []
    return
  }
  priceLines.forEach((line) => candleSeries?.removePriceLine(line))
  priceLines = []
}

function toLineStyle(style: ChartOverlay['lineStyle']) {
  if (style === 'solid') return LineStyle.Solid
  if (style === 'dashed') return LineStyle.Dashed
  return LineStyle.Dotted
}

/** 对外暴露：将视口滚动到指定时间附近并同步十字线/hover。 */
function focusTime(value: string) {
  const renderBars = normalizedBars()
  if (!renderBars.length) return
  const index = nearestBarIndex(value, renderBars)
  const range = {
    from: Math.max(0, index - 20),
    to: Math.min(renderBars.length - 1, index + 20),
  }
  mainChart?.timeScale().setVisibleLogicalRange(range)
  macdChart?.timeScale().setVisibleLogicalRange(range)
  atrChart?.timeScale().setVisibleLogicalRange(range)
  scheduleIndicatorPriceRescale(range)
  scheduleHtdyOverlayRefresh()
  const time = barChartTime(renderBars[index])
  setHoverContextForTime(time)
  syncCrosshairForTime(time)
}

function nearestBarIndex(value: string, renderBars: BarData[]) {
  const target = exchangeLocalTimeMs(value)
  if (!Number.isFinite(target)) return renderBars.length - 1
  let nearest = 0
  let distance = Math.abs(exchangeLocalTimeMs(renderBars[0].time) - target)
  for (let index = 1; index < renderBars.length; index += 1) {
    const current = exchangeLocalTimeMs(renderBars[index].time)
    if (!Number.isFinite(current)) continue
    const currentDistance = Math.abs(current - target)
    if (currentDistance < distance) {
      nearest = index
      distance = currentDistance
    }
  }
  return nearest
}

function exchangeLocalTimeMs(value: string) {
  return new Date(String(value).replace(/(?:Z|[+-]\d{2}:\d{2})$/, '')).getTime()
}

function observeResize() {
  if (!klineShell.value || !mainContainer.value || !macdContainer.value || !atrContainer.value) return
  resizeObserver = new ResizeObserver(resizeCharts)
  resizeObserver.observe(klineShell.value)
  resizeObserver.observe(mainContainer.value)
  resizeObserver.observe(macdContainer.value)
  resizeObserver.observe(atrContainer.value)
}

function applyChartSize(chart: IChartApi | null, container: HTMLElement | undefined) {
  if (!chart || !container) return
  const width = container.clientWidth
  const height = container.clientHeight
  if (width > 0 && height > 0) {
    chart.applyOptions({ width, height })
  }
}

function resizeCharts() {
  applyChartSize(mainChart, mainContainer.value)
  if (activePanel.value === 'macd') {
    applyChartSize(macdChart, macdContainer.value)
  } else {
    applyChartSize(atrChart, atrContainer.value)
  }
  scheduleHtdyOverlayRefresh()
}

function barChartTime(bar: Pick<BarData, 'time' | 'trading_day'>): Time {
  return toChartTimeForPeriod(bar, normalizedPeriod()) as Time
}

function timeStringToChartTime(value: string): Time {
  return toChartTimeForPeriod({ time: value }, normalizedPeriod()) as Time
}

function formatNumber(value: number | null | undefined, digits = 2) {
  if (value === null || value === undefined) return '-'
  return value.toLocaleString('zh-CN', { maximumFractionDigits: digits, minimumFractionDigits: digits })
}

defineExpose({ focusTime })
</script>

<template>
  <div ref="klineShell" class="kline-shell" @mouseleave="handleChartShellLeave">
    <div v-if="showPeriodToolbar" class="period-toolbar">
      <button
        v-for="item in periodOptions"
        :key="item.value"
        class="period-tab"
        :class="{
          'period-tab--active': item.value === period,
          'period-tab--disabled': item.disabled,
        }"
        :disabled="item.disabled"
        @click="selectPeriod(item.value, item.disabled)"
      >
        {{ item.label }}
      </button>
    </div>
    <div v-if="hasCrossFileConflicts" class="conflict-banner">
      <span class="conflict-banner__icon">⚠</span>
      <span class="conflict-banner__text">
        检测到 {{ crossFileConflictCount }} 个跨文件数据冲突（同一交易日存在不同 OHLCV 值的重复 K 线）
      </span>
    </div>
    <div v-if="hasHtdyObservation()" class="htdy-risk-banner">
      火天大有（原始观察）：未来引用 / 重绘风险 · 公式语义尚未完全对齐 · 仅供人工观察 · 不进入严格研究、回测、信号、提醒或交易
    </div>
    <div class="hover-strip">
      <template v-if="hoverContext">
        <strong class="hover-strip__time">{{ formatKlineTimeLabel(hoverContext.time) }}</strong>
        <span class="hover-strip__field"><span class="hover-strip__label">开</span>{{ formatNumber(hoverContext.bar.open) }}</span>
        <span class="hover-strip__field"><span class="hover-strip__label">高</span>{{ formatNumber(hoverContext.bar.high) }}</span>
        <span class="hover-strip__field"><span class="hover-strip__label">低</span>{{ formatNumber(hoverContext.bar.low) }}</span>
        <span class="hover-strip__field"><span class="hover-strip__label">收</span>{{ formatNumber(hoverContext.bar.close) }}</span>
        <span class="hover-strip__field"><span class="hover-strip__label">量</span>{{ hoverContext.bar.volume.toLocaleString('zh-CN') }}</span>
        <span v-if="hoverContext.bar.openInterest !== undefined" class="hover-strip__field">
          <span class="hover-strip__label">持仓</span>{{ hoverContext.bar.openInterest.toLocaleString('zh-CN') }}
        </span>
        <span v-for="item in mainIndicatorReadouts(hoverContext)" :key="item.id" class="hover-strip__field">
          <span class="hover-strip__label">{{ item.displayName }}</span>{{ formatNumber(item.value) }}
        </span>
        <span v-if="hoverContext.cursorPrice !== null && hoverContext.cursorPrice !== undefined" class="hover-strip__field">
          <span class="hover-strip__label">价格</span>{{ formatNumber(hoverContext.cursorPrice) }}
        </span>
        <span v-if="hoverContext.marker" class="hover-strip__marker">{{ hoverContext.marker.tooltip || hoverContext.marker.label }}</span>
      </template>
      <template v-else>移动十字线查看价格与指标；副图按最近 K 线联动</template>
    </div>
    <div
      v-if="linkedCrosshair"
      class="linked-crosshair"
      :style="{
        left: `${linkedCrosshair.x}px`,
        top: `${linkedCrosshair.top}px`,
        height: `${linkedCrosshair.height}px`,
      }"
      aria-hidden="true"
    />
    <div ref="mainWrap" class="chart-main-wrap">
      <div v-if="loading" class="chart-state">加载中</div>
      <div v-else-if="error" class="chart-state chart-state--error">{{ error }}</div>
      <div v-else-if="!hasData" class="chart-state">暂无数据</div>
      <div ref="mainContainer" class="chart chart--main" />
      <svg
        v-if="htdyOverlay"
        class="htdy-overlay"
        :viewBox="`0 0 ${htdyOverlay.width} ${htdyOverlay.height}`"
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        <path v-if="htdyOverlay.bandPath" :d="htdyOverlay.bandPath" class="htdy-overlay__band" />
        <g
          v-for="item in htdyOverlay.candles"
          :key="item.key"
          class="htdy-overlay__candle"
          :class="{ 'htdy-overlay--unstable': item.unstable }"
        >
          <line :x1="item.x" :x2="item.x" :y1="item.yHigh" :y2="item.yLow" :stroke="item.color" />
          <rect
            :x="item.x - item.width / 2"
            :y="Math.min(item.yOpen, item.yClose)"
            :width="item.width"
            :height="Math.max(2, Math.abs(item.yClose - item.yOpen))"
            :fill="item.color"
          />
        </g>
        <text
          v-for="item in htdyOverlay.markers"
          :key="item.key"
          class="htdy-overlay__marker"
          :class="{ 'htdy-overlay--unstable': item.unstable }"
          :x="item.x"
          :y="item.y"
          :fill="item.color"
        >
          {{ item.label }}
        </text>
      </svg>
    </div>
    <div v-if="showIndicatorTabs" class="indicator-tabs">
      <button
        v-for="tab in indicatorTabs"
        :key="tab.value"
        class="indicator-tab"
        :class="{ 'indicator-tab--active': activePanel === tab.value }"
        @click="activePanel = tab.value"
      >
        {{ tab.label }}
      </button>
      <span v-if="hoverContext && activePanel === 'macd'" class="indicator-readout">
        DIF {{ formatNumber(hoverContext.macd?.dif, 4) }} / DEA {{ formatNumber(hoverContext.macd?.dea, 4) }} / HIST {{ formatNumber(hoverContext.macd?.histogram, 4) }}
      </span>
      <span v-else-if="hoverContext && activePanel === 'atr'" class="indicator-readout">ATR {{ formatNumber(hoverContext.atr, 4) }}</span>
    </div>
    <div v-else class="indicator-tabs indicator-tabs--single">
      <span class="indicator-readout">
        MACD DIF {{ formatNumber(hoverContext?.macd?.dif, 4) }} / DEA {{ formatNumber(hoverContext?.macd?.dea, 4) }} / HIST {{ formatNumber(hoverContext?.macd?.histogram, 4) }}
      </span>
    </div>
    <div v-show="!showIndicatorTabs || activePanel === 'macd'" ref="macdContainer" class="chart chart--indicator" />
    <div v-show="showIndicatorTabs && activePanel === 'atr'" ref="atrContainer" class="chart chart--indicator" />
  </div>
</template>

<style scoped>
.kline-shell {
  position: relative;
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 520px;
  background: var(--gy-chart-bg);
  border: 1px solid var(--gy-border);
  border-radius: var(--gy-radius-lg);
  overflow: hidden;
}

.conflict-banner {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  background: rgba(245, 158, 11, 0.12);
  border-bottom: 1px solid rgba(245, 158, 11, 0.3);
  font-size: 13px;
  color: var(--gy-text-secondary, #b08020);
}

.conflict-banner__icon {
  font-size: 16px;
}

.conflict-banner__text {
  line-height: 1.4;
}

.htdy-risk-banner {
  flex: 0 0 auto;
  padding: 6px 12px;
  color: #fbbf24;
  background: rgba(245, 158, 11, 0.1);
  border-bottom: 1px solid rgba(245, 158, 11, 0.28);
  font-size: 12px;
  line-height: 1.4;
}

.linked-crosshair {
  position: absolute;
  z-index: 3;
  width: 0;
  pointer-events: none;
  border-left: 1px dashed var(--gy-chart-crosshair, rgba(148, 163, 184, 0.7));
  opacity: 0.92;
}

.period-toolbar {
  flex: 0 0 32px;
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 0 10px;
  background: var(--gy-bg-panel-strong);
  border-bottom: 1px solid var(--gy-border);
}

.period-tab {
  height: 24px;
  min-width: 36px;
  padding: 0 10px;
  color: var(--gy-text-muted);
  background: transparent;
  border: none;
  border-radius: var(--gy-radius-sm);
  cursor: pointer;
  font-size: 12px;
}

.period-tab:hover:not(:disabled) {
  color: var(--gy-text-primary);
  background: var(--gy-bg-hover);
}

.period-tab--active {
  color: #ffffff;
  background: var(--gy-accent);
}

.period-tab--disabled,
.period-tab:disabled {
  color: var(--gy-text-disabled);
  cursor: not-allowed;
}

.main-indicator-toolbar {
  position: relative;
  flex: 0 0 32px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 12px;
  color: var(--gy-text-muted);
  background: var(--gy-bg-panel);
  border-bottom: 1px solid var(--gy-border);
  font-size: 12px;
}

.main-indicator-picker {
  position: relative;
}

.main-indicator-trigger {
  height: 24px;
  padding: 0 10px;
  color: var(--gy-text-primary);
  background: var(--gy-bg-panel-strong);
  border: 1px solid var(--gy-border-strong);
  border-radius: var(--gy-radius-sm);
  cursor: pointer;
}

.main-indicator-trigger:hover {
  background: var(--gy-bg-hover);
}

.main-indicator-menu {
  position: absolute;
  z-index: 10;
  top: 28px;
  left: 0;
  width: 184px;
  padding: 6px;
  background: var(--gy-bg-panel-strong);
  border: 1px solid var(--gy-border-strong);
  border-radius: var(--gy-radius-md);
  box-shadow: var(--gy-shadow-lg);
}

.main-indicator-option {
  display: grid;
  grid-template-columns: 12px 1fr auto;
  align-items: center;
  gap: 8px;
  width: 100%;
  height: 28px;
  padding: 0 8px;
  color: var(--gy-text-muted);
  background: transparent;
  border: none;
  border-radius: var(--gy-radius-sm);
  cursor: pointer;
  text-align: left;
}

.main-indicator-option:hover,
.main-indicator-option--active {
  color: var(--gy-text-primary);
  background: var(--gy-bg-hover);
}

.main-indicator-option--active::after {
  content: '✓';
  color: var(--gy-accent);
}

.main-indicator-option small {
  color: #fbbf24;
}

.main-indicator-swatch {
  width: 10px;
  height: 10px;
  border-radius: 999px;
}

.main-indicator-actions {
  display: flex;
  justify-content: space-between;
  gap: 6px;
  padding-top: 6px;
  margin-top: 6px;
  border-top: 1px solid var(--gy-border);
}

.main-indicator-actions button {
  flex: 1;
  height: 24px;
  color: var(--gy-text-muted);
  background: transparent;
  border: 1px solid var(--gy-border);
  border-radius: var(--gy-radius-sm);
  cursor: pointer;
}

.main-indicator-actions button:hover {
  color: var(--gy-text-primary);
  background: var(--gy-bg-hover);
}

.main-indicator-risk {
  color: #fbbf24;
}

.hover-strip {
  flex: 0 0 34px;
  display: flex;
  align-items: center;
  gap: 0;
  min-width: 0;
  padding: 0 12px;
  color: var(--gy-text-muted);
  background: var(--gy-bg-panel-strong);
  border-bottom: 1px solid var(--gy-border);
  font-size: 12px;
  white-space: nowrap;
  overflow: hidden;
}

.hover-strip__time {
  margin-right: 12px;
  color: var(--gy-text-primary);
  font-weight: 600;
}

.hover-strip__field {
  color: var(--gy-text-primary);
}

.hover-strip__field + .hover-strip__field::before,
.hover-strip__marker::before {
  content: '·';
  margin: 0 8px;
  color: var(--gy-text-disabled);
}

.hover-strip__label {
  margin-right: 4px;
  color: var(--gy-text-muted);
}

.hover-strip__marker {
  color: var(--gy-chart-ema);
}

.chart-main-wrap {
  position: relative;
  flex: 1 1 auto;
  min-height: 240px;
  min-width: 0;
}

.chart {
  width: 100%;
  min-width: 0;
}

.chart--main {
  height: 100%;
  min-height: 0;
}

.htdy-overlay {
  position: absolute;
  inset: 0;
  z-index: 1;
  width: 100%;
  height: 100%;
  overflow: visible;
  pointer-events: none;
}

.htdy-overlay__band {
  fill: var(--gy-chart-htdy-band, rgba(45, 212, 191, 0.22));
  stroke: var(--gy-chart-htdy-band-stroke, rgba(45, 212, 191, 0.55));
  stroke-width: 1;
}

.htdy-overlay__candle line {
  stroke-width: 1.4;
}

.htdy-overlay__marker {
  font-size: 11px;
  font-weight: 600;
  paint-order: stroke;
  stroke: rgba(11, 17, 27, 0.9);
  stroke-width: 3px;
}

.htdy-overlay--unstable {
  opacity: 0.48;
}

.chart--indicator {
  flex: 0 0 24%;
  min-height: 120px;
  max-height: 30%;
}

.indicator-tabs {
  flex: 0 0 34px;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 10px;
  color: var(--gy-text-muted);
  background: var(--gy-bg-panel-strong);
  border-top: 1px solid var(--gy-border);
  border-bottom: 1px solid var(--gy-border);
  font-size: 12px;
}

.indicator-tab {
  height: 24px;
  padding: 0 12px;
  color: var(--gy-text-muted);
  background: var(--gy-bg-panel);
  border: 1px solid var(--gy-border-strong);
  border-radius: var(--gy-radius-sm);
  cursor: pointer;
}

.indicator-tab--active {
  color: #ffffff;
  background: var(--gy-accent);
  border-color: var(--gy-accent);
}

.indicator-readout {
  margin-left: 8px;
  color: var(--gy-text-secondary);
}

.indicator-tabs--single {
  justify-content: flex-start;
}

.chart-state {
  position: absolute;
  z-index: 2;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--gy-text-secondary);
  background: rgba(11, 17, 27, 0.78);
}

.chart-state--error {
  color: #fecaca;
}
</style>
