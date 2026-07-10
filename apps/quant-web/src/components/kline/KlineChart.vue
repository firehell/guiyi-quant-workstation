<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
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
import type { BarData, ChartOverlay, HoverKlineContext, IndicatorPanelType, KlineMarker } from '@/types/market'
import { calculateATR, calculateEMA, calculateMACD } from '@/utils/indicators'

const LINKED_PRICE_SCALE_MIN_WIDTH = 76
const MAIN_CHART_FALLBACK_HEIGHT = 430
const SUB_CHART_FALLBACK_HEIGHT = 150
const DAILY_WEEKLY_PERIODS = new Set(['1d', '1w'])
const INDICATOR_SCALE_PADDING = 0.12
const INDICATOR_RESCALE_DEBOUNCE_MS = 80

const props = withDefaults(
  defineProps<{
    bars: BarData[]
    markers?: KlineMarker[]
    activeMarkerId?: string | null
    overlays?: ChartOverlay[]
    loading?: boolean
    error?: string | null
    indicatorPanels?: IndicatorPanelType[]
    period?: string
    periodOptions?: { label: string; value: string; disabled?: boolean }[]
    showPeriodToolbar?: boolean
  }>(),
  {
    indicatorPanels: () => ['macd', 'atr'],
    periodOptions: () => [],
    showPeriodToolbar: false,
  },
)

const emit = defineEmits<{
  hover: [context: HoverKlineContext | null]
  'marker-click': [marker: KlineMarker]
  'update:period': [value: string]
}>()

const klineShell = ref<HTMLElement>()
const mainContainer = ref<HTMLElement>()
const macdContainer = ref<HTMLElement>()
const atrContainer = ref<HTMLElement>()
const activePanel = ref<IndicatorPanelType>('macd')
const hoverContext = ref<HoverKlineContext | null>(null)

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

let mainChart: IChartApi | null = null
let macdChart: IChartApi | null = null
let atrChart: IChartApi | null = null
let candleSeries: ISeriesApi<'Candlestick'> | null = null
let volumeSeries: ISeriesApi<'Histogram'> | null = null
let emaSeries: ISeriesApi<'Line'> | null = null
let markerLayer: ISeriesMarkersPluginApi<Time> | null = null
let macdDifSeries: ISeriesApi<'Line'> | null = null
let macdDeaSeries: ISeriesApi<'Line'> | null = null
let macdHistogramSeries: ISeriesApi<'Histogram'> | null = null
let atrSeries: ISeriesApi<'Line'> | null = null
let resizeObserver: ResizeObserver | null = null
let syncingRange = false
let syncingCrosshair = false
let priceLines: IPriceLine[] = []
let renderBarsCache: BarData[] = []
let indicatorRescaleTimer: ReturnType<typeof setTimeout> | null = null

const barByTime = new Map<string, BarData>()
const markersByTime = new Map<string, KlineMarker[]>()
const emaByTime = new Map<string, number>()
const macdByTime = new Map<string, { dif?: number; dea?: number; histogram?: number }>()
const atrByTime = new Map<string, number>()

const hasData = computed(() => props.bars.length > 0)

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
  resizeObserver?.disconnect()
  removePriceLines()
  mainChart?.remove()
  macdChart?.remove()
  atrChart?.remove()
})

watch(
  () => [props.bars, props.markers, props.activeMarkerId, props.overlays],
  async () => {
    renderSeries()
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
  if (hoverContext.value) syncCrosshairForTime(toChartTime(hoverContext.value.time))
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
      borderColor: '#3a404b',
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

function createCharts() {
  if (!mainContainer.value || !macdContainer.value || !atrContainer.value) return

  const mainHeight = mainContainer.value.clientHeight || MAIN_CHART_FALLBACK_HEIGHT
  mainChart = createChart(mainContainer.value, {
    width: mainContainer.value.clientWidth,
    height: mainHeight,
    layout: {
      background: { type: ColorType.Solid, color: '#101318' },
      textColor: '#b8c0cc',
      attributionLogo: false,
    },
    grid: {
      vertLines: { color: '#252a32' },
      horzLines: { color: '#252a32' },
    },
    rightPriceScale: {
      borderColor: '#3a404b',
      minimumWidth: LINKED_PRICE_SCALE_MIN_WIDTH,
      scaleMargins: { top: 0.08, bottom: 0.22 },
    },
    ...sharedTimeDisplayOptions(),
    crosshair: { mode: 1 },
  })

  candleSeries = mainChart.addSeries(CandlestickSeries, {
    upColor: '#ef4444',
    downColor: '#22c55e',
    borderUpColor: '#ef4444',
    borderDownColor: '#22c55e',
    wickUpColor: '#ef4444',
    wickDownColor: '#22c55e',
  })
  markerLayer = createSeriesMarkers(candleSeries, [])
  emaSeries = mainChart.addSeries(LineSeries, {
    color: '#f59e0b',
    lineWidth: 2,
    priceLineVisible: false,
    lastValueVisible: false,
  })
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
    color: '#38bdf8',
    lineWidth: 1,
    priceLineVisible: false,
    lastValueVisible: false,
  })
  macdDeaSeries = macdChart.addSeries(LineSeries, {
    color: '#f59e0b',
    lineWidth: 1,
    priceLineVisible: false,
    lastValueVisible: false,
  })

  const atrHeight = atrContainer.value.clientHeight || SUB_CHART_FALLBACK_HEIGHT
  atrChart = createSubChart(atrContainer.value, atrHeight)
  atrSeries = atrChart.addSeries(LineSeries, {
    color: '#a78bfa',
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
      background: { type: ColorType.Solid, color: '#101318' },
      textColor: '#8d97a7',
      attributionLogo: false,
    },
    grid: {
      vertLines: { color: '#252a32' },
      horzLines: { color: '#252a32' },
    },
    rightPriceScale: {
      borderColor: '#3a404b',
      minimumWidth: LINKED_PRICE_SCALE_MIN_WIDTH,
      autoScale: true,
      scaleMargins: { top: 0.12, bottom: 0.12 },
    },
    ...sharedTimeDisplayOptions(),
    crosshair: { mode: 1 },
  })
}

function setupLinkedChartController() {
  mainChart?.timeScale().subscribeVisibleLogicalRangeChange((range) => syncAllRanges(range, mainChart))
  macdChart?.timeScale().subscribeVisibleLogicalRangeChange((range) => syncAllRanges(range, macdChart))
  atrChart?.timeScale().subscribeVisibleLogicalRangeChange((range) => syncAllRanges(range, atrChart))
  mainChart?.subscribeCrosshairMove((param) => syncCrosshair(param, mainChart))
  mainChart?.subscribeClick(handleChartClick)
  macdChart?.subscribeCrosshairMove((param) => syncCrosshair(param, macdChart))
  atrChart?.subscribeCrosshairMove((param) => syncCrosshair(param, atrChart))
}

function renderSeries() {
  if (!candleSeries || !volumeSeries || !emaSeries || !macdDifSeries || !macdDeaSeries || !macdHistogramSeries || !atrSeries) return

  const renderBars = normalizedBars()
  renderBarsCache = renderBars
  rebuildLookupMaps(renderBars)
  const candleData: CandlestickData<Time>[] = renderBars.map((bar) => ({
    time: toChartTime(bar.time),
    open: bar.open,
    high: bar.high,
    low: bar.low,
    close: bar.close,
  }))
  const volumeData: HistogramData<Time>[] = renderBars.map((bar) => ({
    time: toChartTime(bar.time),
    value: bar.volume,
    color: bar.close >= bar.open ? 'rgba(239, 68, 68, 0.45)' : 'rgba(34, 197, 94, 0.45)',
  }))
  const chartTimes = renderBars.map((bar) => toChartTime(bar.time))
  const emaData = toAlignedLineData(chartTimes, calculateEMA(renderBars, 21))
  const macd = calculateMACD(renderBars)
  const macdDifData = toAlignedLineData(chartTimes, macd.dif)
  const macdDeaData = toAlignedLineData(chartTimes, macd.dea)
  const macdHistogramData = toAlignedHistogramData(chartTimes, macd.histogram)
  const atrData = toAlignedLineData(chartTimes, calculateATR(renderBars, 14))

  candleSeries.setData(candleData)
  markerLayer?.setMarkers(toSeriesMarkers(props.markers || [], props.activeMarkerId || null))
  volumeSeries.setData(volumeData)
  emaSeries.setData(emaData)
  macdDifSeries.setData(macdDifData)
  macdDeaSeries.setData(macdDeaData)
  macdHistogramSeries.setData(macdHistogramData)
  atrSeries.setData(atrData)
  applyPriceLines()
  if (renderBars.length > 0) {
    mainChart?.timeScale().fitContent()
    macdChart?.timeScale().fitContent()
    atrChart?.timeScale().fitContent()
    const activeMarker = (props.markers || []).find((marker) => marker.id === props.activeMarkerId)
    setHoverContextForTime(toChartTime(activeMarker?.time || renderBars.at(-1)!.time))
    scheduleIndicatorPriceRescale(mainChart?.timeScale().getVisibleLogicalRange() || null)
  } else {
    renderBarsCache = []
    clearHover()
  }
}

function normalizedBars() {
  const byTime = new Map<string, BarData>()
  props.bars.forEach((bar) => {
    byTime.set(String(toChartTime(bar.time)), bar)
  })
  return [...byTime.values()].sort((first, second) => Number(toChartTime(first.time)) - Number(toChartTime(second.time)))
}

function rebuildLookupMaps(renderBars: BarData[]) {
  barByTime.clear()
  markersByTime.clear()
  emaByTime.clear()
  macdByTime.clear()
  atrByTime.clear()
  renderBars.forEach((bar) => barByTime.set(String(toChartTime(bar.time)), bar))
  ;(props.markers || []).forEach((marker) => {
    const key = String(toChartTime(marker.time))
    markersByTime.set(key, [...(markersByTime.get(key) || []), marker])
  })
  calculateEMA(renderBars, 21).forEach((point) => emaByTime.set(String(toChartTime(String(point.time))), point.value))
  const macd = calculateMACD(renderBars)
  macd.dif.forEach((point) => {
    const key = String(toChartTime(String(point.time)))
    macdByTime.set(key, { ...macdByTime.get(key), dif: point.value })
  })
  macd.dea.forEach((point) => {
    const key = String(toChartTime(String(point.time)))
    macdByTime.set(key, { ...macdByTime.get(key), dea: point.value })
  })
  macd.histogram.forEach((point) => {
    const key = String(toChartTime(String(point.time)))
    macdByTime.set(key, { ...macdByTime.get(key), histogram: point.value })
  })
  calculateATR(renderBars, 14).forEach((point) => atrByTime.set(String(toChartTime(String(point.time))), point.value))
}

function toAlignedLineData(chartTimes: Time[], points: Array<{ time: Time | string; value: number }>): Array<LineData<Time> | WhitespaceData<Time>> {
  const values = new Map(points.map((point) => [String(toChartTime(String(point.time))), point.value]))
  return chartTimes.map((time) => {
    const value = values.get(String(time))
    return value === undefined ? { time } : { time, value }
  })
}

function toAlignedHistogramData(
  chartTimes: Time[],
  points: Array<{ time: Time | string; value: number }>,
): Array<HistogramData<Time> | WhitespaceData<Time>> {
  const values = new Map(points.map((point) => [String(toChartTime(String(point.time))), point.value]))
  return chartTimes.map((time) => {
    const value = values.get(String(time))
    if (value === undefined) return { time }
    return {
      time,
      value,
      color: value >= 0 ? 'rgba(239, 68, 68, 0.55)' : 'rgba(34, 197, 94, 0.55)',
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
    const key = String(toChartTime(renderBarsCache[index].time))
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

function syncCrosshair(param: MouseEventParams<Time>, source: IChartApi | null) {
  if (syncingCrosshair) return
  if (!param.time) {
    clearLinkedCrosshairs(source)
    return
  }
  setHoverContextForTime(param.time)
  syncingCrosshair = true
  const key = String(param.time)
  const bar = barByTime.get(key)
  const macd = macdByTime.get(key)
  const atr = atrByTime.get(key)
  if (source !== mainChart && isChartVisible(mainChart) && bar && candleSeries) mainChart?.setCrosshairPosition(bar.close, param.time, candleSeries)
  if (source !== macdChart && isChartVisible(macdChart) && macdHistogramSeries && macd) {
    macdChart?.setCrosshairPosition(macd.histogram ?? macd.dif ?? 0, param.time, macdHistogramSeries)
  }
  if (source !== atrChart && isChartVisible(atrChart) && atrSeries && atr !== undefined) atrChart?.setCrosshairPosition(atr, param.time, atrSeries)
  syncingCrosshair = false
}

function handleChartClick(param: MouseEventParams<Time>) {
  const marker = markerFromClick(param)
  if (!marker) return
  const time = toChartTime(marker.time)
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
  const candidates = markersByTime.get(String(param.time)) || []
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
  if (source !== mainChart && isChartVisible(mainChart)) mainChart?.clearCrosshairPosition()
  if (source !== macdChart && isChartVisible(macdChart)) macdChart?.clearCrosshairPosition()
  if (source !== atrChart && isChartVisible(atrChart)) atrChart?.clearCrosshairPosition()
  syncingCrosshair = false
}

function syncCrosshairForTime(time: Time) {
  const key = String(time)
  const bar = barByTime.get(key)
  const macd = macdByTime.get(key)
  const atr = atrByTime.get(key)
  syncingCrosshair = true
  if (isChartVisible(mainChart) && bar && candleSeries) mainChart?.setCrosshairPosition(bar.close, time, candleSeries)
  if (isChartVisible(macdChart) && macdHistogramSeries && macd) macdChart?.setCrosshairPosition(macd.histogram ?? macd.dif ?? 0, time, macdHistogramSeries)
  if (isChartVisible(atrChart) && atrSeries && atr !== undefined) atrChart?.setCrosshairPosition(atr, time, atrSeries)
  syncingCrosshair = false
}

function isChartVisible(chart: IChartApi | null) {
  if (!chart) return false
  if (chart === mainChart) return Boolean(mainContainer.value?.clientWidth)
  if (chart === macdChart) return activePanel.value === 'macd' && Boolean(macdContainer.value?.clientWidth)
  if (chart === atrChart) return activePanel.value === 'atr' && Boolean(atrContainer.value?.clientWidth)
  return false
}

function setHoverContextForTime(time: Time, preferredMarkerId?: string) {
  const key = String(time)
  const bar = barByTime.get(key)
  if (!bar) {
    clearHover()
    return
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
    ema21: emaByTime.get(key) ?? null,
    macd: macdByTime.get(key) || null,
    atr: atrByTime.get(key) ?? null,
    marker,
  }
  hoverContext.value = context
  emit('hover', context)
}

function clearHover() {
  hoverContext.value = null
  emit('hover', null)
}

function toSeriesMarkers(markers: KlineMarker[], activeMarkerId: string | null): SeriesMarker<Time>[] {
  return markers.map((marker) => ({
    id: marker.id,
    time: toChartTime(marker.time),
    position: marker.position,
    shape: marker.shape,
    color: marker.id === activeMarkerId ? '#fbbf24' : marker.color,
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
  const time = toChartTime(renderBars[index].time)
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
}

function toChartTime(value: string): Time {
  return Math.floor(new Date(value).getTime() / 1000) as Time
}

function formatNumber(value: number | null | undefined, digits = 2) {
  if (value === null || value === undefined) return '-'
  return value.toLocaleString('zh-CN', { maximumFractionDigits: digits, minimumFractionDigits: digits })
}

defineExpose({ focusTime })
</script>

<template>
  <div ref="klineShell" class="kline-shell">
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
    <div class="hover-strip">
      <template v-if="hoverContext">
        <strong class="hover-strip__time">{{ formatKlineTimeLabel(hoverContext.time) }}</strong>
        <span class="hover-strip__field"><span class="hover-strip__label">开</span>{{ formatNumber(hoverContext.bar.open) }}</span>
        <span class="hover-strip__field"><span class="hover-strip__label">高</span>{{ formatNumber(hoverContext.bar.high) }}</span>
        <span class="hover-strip__field"><span class="hover-strip__label">低</span>{{ formatNumber(hoverContext.bar.low) }}</span>
        <span class="hover-strip__field"><span class="hover-strip__label">收</span>{{ formatNumber(hoverContext.bar.close) }}</span>
        <span class="hover-strip__field"><span class="hover-strip__label">量</span>{{ hoverContext.bar.volume.toLocaleString('zh-CN') }}</span>
        <span class="hover-strip__field"><span class="hover-strip__label">EMA21</span>{{ formatNumber(hoverContext.ema21) }}</span>
        <span v-if="hoverContext.marker" class="hover-strip__marker">{{ hoverContext.marker.tooltip || hoverContext.marker.label }}</span>
      </template>
      <template v-else>移动十字线查看同一根 K 的主图与副图指标</template>
    </div>
    <div class="chart-main-wrap">
      <div v-if="loading" class="chart-state">加载中</div>
      <div v-else-if="error" class="chart-state chart-state--error">{{ error }}</div>
      <div v-else-if="!hasData" class="chart-state">暂无数据</div>
      <div ref="mainContainer" class="chart chart--main" />
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
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 520px;
  background: #101318;
  border: 1px solid #262c36;
  border-radius: 6px;
  overflow: hidden;
}

.period-toolbar {
  flex: 0 0 32px;
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 0 10px;
  background: #171b22;
  border-bottom: 1px solid #262c36;
}

.period-tab {
  height: 24px;
  min-width: 36px;
  padding: 0 10px;
  color: #9aa4b2;
  background: transparent;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
}

.period-tab:hover:not(:disabled) {
  color: #e5e7eb;
  background: #222832;
}

.period-tab--active {
  color: #ffffff;
  background: #ef6b3a;
}

.period-tab--disabled,
.period-tab:disabled {
  color: #5f6775;
  cursor: not-allowed;
}

.hover-strip {
  flex: 0 0 34px;
  display: flex;
  align-items: center;
  gap: 0;
  min-width: 0;
  padding: 0 12px;
  color: #98a3b3;
  background: #171b22;
  border-bottom: 1px solid #262c36;
  font-size: 12px;
  white-space: nowrap;
  overflow: hidden;
}

.hover-strip__time {
  margin-right: 12px;
  color: #e5e7eb;
  font-weight: 600;
}

.hover-strip__field {
  color: #e5e7eb;
}

.hover-strip__field + .hover-strip__field::before,
.hover-strip__marker::before {
  content: '·';
  margin: 0 8px;
  color: #5f6775;
}

.hover-strip__label {
  margin-right: 4px;
  color: #8f9aaa;
}

.hover-strip__marker {
  color: #fbbf24;
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
  color: #94a3b8;
  background: #171b22;
  border-top: 1px solid #262c36;
  border-bottom: 1px solid #262c36;
  font-size: 12px;
}

.indicator-tab {
  height: 24px;
  padding: 0 12px;
  color: #9aa4b2;
  background: #222832;
  border: 1px solid #303744;
  border-radius: 5px;
  cursor: pointer;
}

.indicator-tab--active {
  color: #ffffff;
  background: #ef6b3a;
  border-color: #ef6b3a;
}

.indicator-readout {
  margin-left: 8px;
  color: #cbd5e1;
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
  color: #cbd5e1;
  background: rgba(16, 19, 24, 0.72);
}

.chart-state--error {
  color: #fecaca;
}
</style>
