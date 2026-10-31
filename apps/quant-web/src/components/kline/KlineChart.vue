<script setup lang="ts">
import { NewowPublicPatternPrimitive } from '@/components/market/detail/newow/newowPublicPatternPrimitive'
import type { PatternGeometry } from '@/utils/newowPatternDisplay'
import { inject, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { DETAIL_CHART_SESSION, detailChartViewport, detailChartTime, detailChartPaneLayout, detailChartIndex, detailChartLength, detailChartTimeAt, type DetailChartSession } from '@/utils/detailChartSession'
import {
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  HistogramSeries,
  LineSeries,
  type IChartApi,
  type ISeriesMarkersPluginApi,
  type ISeriesApi,
  type LogicalRange,
  type MouseEventParams,
  type TickMarkType,
  type Time,
  type UTCTimestamp,
  type SingleValueData,
  type WhitespaceData,
} from 'lightweight-charts'
import type { KlineQualityBreak, KlineReferenceCallout, KlineReferenceIndicator, KlineReferenceSelection } from '@/types/referenceCallout'
import ReferenceCalloutLabels from './ReferenceCalloutLabels.vue'
import { layoutNiuwaReferenceCallouts, matchesReferenceBar, NIUWA_CALLOUT_BOX, type PositionedCallout } from '@/utils/referenceCalloutLayout'
import KlineHoverLegend from '@/components/kline/KlineHoverLegend.vue'
import type {
  BarData,
  HoverKlineContext,
  KlineMarker,
  MainIndicatorId,
  SeriesKind,
} from '@/types/market'
import { calculateThsMacdDisplay } from '@/utils/thsMacdDisplay'
import { resolveChartTheme } from '@/styles/chartTheme'
import {
  formatChartAxisTimeInShanghai,
  formatChartTimeInShanghai,
  toKlineDisplayTimeForPeriod,
} from '@/utils/barTime'
import { normalizeBarSeries } from '@/utils/barSeries'
import { visibleRangeDetectorCount } from '@/utils/rangeDetectorStatus'
import { initialChartLogicalRange, initialNewowChartLogicalRange, prependChartLogicalRange } from '@/utils/chartViewport'
import {
  buildKlineDerivedData,
  resolveKlineHoverContext,
  type KlineValuePoint,
} from '@/utils/klineViewModel'
import { mergeKlineMarkers } from '@/utils/alertMarkers'
import { referencePriceLevelSegments } from '@/utils/referencePriceLevels'
import { RangeDetectorPrimitive } from '@/components/kline/rangeDetectorPrimitive'

import { referenceIndicatorOverlay } from '@/utils/referenceIndicatorOverlay'

const props = withDefaults(defineProps<{
  patternGeometry?: PatternGeometry | null
  bars: BarData[]
  loading?: boolean
  error?: string | null
  period?: string
  seriesKind: SeriesKind
  visibleMainIndicators?: MainIndicatorId[]
  rangeDetectorSourceIdentity?: string
  rangeDetectorAnchorTime?: string | null
  showDerivedMarkers?: boolean
  alertMarkers?: KlineMarker[]
  researchMarkers?: KlineMarker[]
  markerSelectionEnabled?: boolean
  referenceCallouts?: KlineReferenceCallout[]
  referenceIndicators?: KlineReferenceIndicator[]
  referenceSelection?: KlineReferenceSelection[]
  qualityBreaks?: KlineQualityBreak[]
}>(), {
  loading: false,
  error: null,
  period: '15m',
  visibleMainIndicators: () => [],
  rangeDetectorSourceIdentity: '',
  rangeDetectorAnchorTime: null,
  showDerivedMarkers: true,
  alertMarkers: () => [],
  researchMarkers: () => [],
  markerSelectionEnabled: true,
  referenceCallouts: () => [],
  referenceSelection: () => [],
  qualityBreaks: () => [],
})

const emit = defineEmits<{
  'need-more-before': []
  'visible-from-change': [time: string | null]
  'range-detector-result': [result: { count: number; calculationMs: number }]
  'follow-latest-change': [followLatest: boolean]
  'crosshair-change': [context: HoverKlineContext | null]
  'marker-select': [marker: KlineMarker]
}>()

const container = ref<HTMLElement>()
const detailSession = inject<DetailChartSession | null>(DETAIL_CHART_SESSION, null)
const positionedCallouts = ref<PositionedCallout[]>([])
const positionedSelection = ref<Array<{ time: string; x: number; height: number }>>([])
const isReferenceSelected = (callout: KlineReferenceCallout) => props.referenceSelection.some(selection => matchesReferenceBar(selection, callout))
let calloutFrame: number | null = null
function scheduleReferenceCallouts() {
  if (calloutFrame !== null || (!props.referenceCallouts.length && !props.referenceSelection.length)) return
  calloutFrame = requestAnimationFrame(projectReferenceCallouts)
}
function projectReferenceCallouts() {
  calloutFrame = null
  if (chart && candles && container.value) {
    const width = chart.timeScale().width()
    const height = chart.panes()[0]?.getHeight() ?? 0
    const points = props.referenceCallouts.flatMap((callout) => {
      const bar = renderedBars.find((item) => matchesReferenceBar(callout, item))
      if (!bar) return []
      const x = chart!.timeScale().timeToCoordinate(chartTime(bar))
      const y = candles!.priceToCoordinate(Number(callout.price))
      const high = candles!.priceToCoordinate(bar.high), low = candles!.priceToCoordinate(bar.low)
      return x === null || y === null ? [] : [{
        callout, x, y,
        candle: high === null || low === null ? undefined : { left: x - 8, top: Math.min(high, low) - 3, width: 16, height: Math.abs(low - high) + 6 },
        boxWidth: Math.max(NIUWA_CALLOUT_BOX.width, Math.min(180, Math.max(callout.title.length, callout.detail.length) * 7 + 14)),
        boxHeight: NIUWA_CALLOUT_BOX.height,
        expanded: isReferenceSelected(callout),
      }]
    })
    positionedCallouts.value = layoutNiuwaReferenceCallouts(points, width, height, [], true)
    positionedSelection.value = props.referenceSelection.flatMap(selection => {
      const bar = renderedBars.find(item => matchesReferenceBar(selection, item))
      if (!bar) return []
      const x = chart!.timeScale().timeToCoordinate(chartTime(bar))
      return x === null || x < 0 || x > width ? [] : [{ time: selection.time, x, height }]
    })
  }

}
watch(() => [props.referenceCallouts, props.referenceSelection], () => {
  if (calloutFrame !== null) cancelAnimationFrame(calloutFrame)
  calloutFrame = null
  positionedCallouts.value = []
  positionedSelection.value = []
  scheduleReferenceCallouts()
}, { deep: true })
let referenceLevelSeries: ISeriesApi<'Line'>[] = []
const referenceTargetSegments = ref(0), referenceStopSegments = ref(0)
let chart: IChartApi | null = null
let candles: ISeriesApi<'Candlestick'> | null = null
let volume: ISeriesApi<'Histogram'> | null = null
let macdHistogram: ISeriesApi<'Histogram'> | null = null
let macdDif: ISeriesApi<'Line'> | null = null
let macdDea: ISeriesApi<'Line'> | null = null
let macdCrossMarkers: ISeriesMarkersPluginApi<Time> | null = null
let htdyZk1: ISeriesApi<'Line'> | null = null
let htdyZd1: ISeriesApi<'Line'> | null = null
let htdyZd2: ISeriesApi<'Line'> | null = null
let htdyMarkers: ISeriesMarkersPluginApi<Time> | null = null
const emaLines: Partial<Record<EmaIndicatorId, ISeriesApi<'Line'>>> = {}
const publicPatternPrimitive = new NewowPublicPatternPrimitive(point => chartTime({ time: point.barEnd, trading_day: point.tradingDay } as BarData))
watch(() => props.patternGeometry, value => publicPatternPrimitive.setData(value ?? null))
const rangeDetectorPrimitive = new RangeDetectorPrimitive()
let observer: ResizeObserver | null = null
let renderedBars: BarData[] = []
const rangeCalculationMs = ref(0)
const rangeCount = ref(0)
const visibleRangeCount = ref(0)
const lastVisibleFrom = ref<string | null>(null)
const macdPointCount = ref(0)
let isNearLeftBoundary = false
let paginationArmed = false
let followLatest = true
const hoverContext = ref<HoverKlineContext | null>(null)
const macdLabelTop = ref<number | null>(null)
const chartViewportReady = ref(false)
let derivedData = buildKlineDerivedData([], [])
// One latest result only; normalized Bar arrays are replaced on every input mutation.
let rangeCache: { bars: BarData[]; key: string; result: NonNullable<typeof derivedData.rangeDetector> } | null = null
let renderedMarkerById = new Map<string, KlineMarker>()
let viewportStabilityFrame: number | null = null
let viewportStabilityTarget: ChartViewportRange | null = null
let viewportStableFrames = 0
let viewportStabilityAttempts = 0

type EmaIndicatorId = 'ema_10' | 'ema_21' | 'ema_60'
type ChartViewportRange = { from: number; to: number }
const EMA_INDICATORS: EmaIndicatorId[] = ['ema_10', 'ema_21', 'ema_60']
const REQUIRED_VIEWPORT_STABLE_FRAMES = 3
const MAX_VIEWPORT_STABILITY_ATTEMPTS = 12
const LOGICAL_RANGE_EPSILON = 0.001

onMounted(async () => {
  await nextTick()
  if (!container.value) return
  const theme = resolveChartTheme(container.value)
  chart = (detailSession?.acquire ?? createChart)(container.value, {
    width: container.value.clientWidth,
    height: container.value.clientHeight,
    layout: {
      background: { type: ColorType.Solid, color: theme.background },
      textColor: theme.text,
    },
    grid: {
      vertLines: { color: theme.grid },
      horzLines: { color: theme.grid },
    },
    rightPriceScale: { borderColor: theme.axis },
    localization: { timeFormatter: formatChartTimeInShanghai },
    crosshair: {
      vertLine: {
        labelBackgroundColor: '#1F2937',
        labelVisible: true,
      },
      horzLine: {
        labelBackgroundColor: '#1F2937',
        labelVisible: true,
      },
    },
    timeScale: {
      borderColor: theme.axis,
      timeVisible: !isDaily(),
      tickMarkFormatter: (time: Time, tickMarkType: TickMarkType) => (
        formatChartAxisTimeInShanghai(time, tickMarkType)
      ),
    },
  })
  chart.panes()[0].setStretchFactor(6)
  chart.addPane().setStretchFactor(2)
  chart.addPane().setStretchFactor(2)
  candles = chart.addSeries(CandlestickSeries, {
    upColor: theme.candleUp,
    downColor: theme.candleDown,
    borderUpColor: theme.candleUp,
    borderDownColor: theme.candleDown,
    wickUpColor: theme.candleUp,
    wickDownColor: theme.candleDown,
  }, 0)
  emaLines.ema_10 = chart.addSeries(LineSeries, { color: theme.ema10, lineWidth: 1, lastValueVisible: false }, 0)
  emaLines.ema_21 = chart.addSeries(LineSeries, { color: theme.ema21, lineWidth: 2, lastValueVisible: false }, 0)
  emaLines.ema_60 = chart.addSeries(LineSeries, { color: theme.ema60, lineWidth: 1, lastValueVisible: false }, 0)
  candles.attachPrimitive(rangeDetectorPrimitive)
  candles.attachPrimitive(publicPatternPrimitive)
  publicPatternPrimitive.setData(props.patternGeometry ?? null)
  htdyZk1 = chart.addSeries(LineSeries, { color: theme.htdyZk1, lineWidth: 2, lineStyle: 0, lastValueVisible: false }, 0)
  htdyZd1 = chart.addSeries(LineSeries, { color: theme.htdyZd1, lineWidth: 2, lineStyle: 2, lastValueVisible: false }, 0)
  htdyZd2 = chart.addSeries(LineSeries, { color: theme.htdyZd2, lineWidth: 2, lineStyle: 0, lastValueVisible: false }, 0)
  htdyMarkers = createSeriesMarkers(candles)
  volume = chart.addSeries(HistogramSeries, {
    priceFormat: { type: 'volume' },
  }, 1)
  macdHistogram = chart.addSeries(HistogramSeries, { base: 0, lastValueVisible: false }, 2)
  macdDif = chart.addSeries(LineSeries, { color: '#00bfcf', lineWidth: 1, lastValueVisible: false }, 2)
  macdDea = chart.addSeries(LineSeries, { color: '#d4b000', lineWidth: 1, lastValueVisible: false }, 2)
  macdCrossMarkers = createSeriesMarkers(macdDif)
  macdDif.createPriceLine({ price: 0, color: '#888888', lineWidth: 1, lineStyle: 0, axisLabelVisible: false, title: '' })
  chart.priceScale('right', 1).applyOptions({ scaleMargins: { top: 0.15, bottom: 0.05 } })
  chart.priceScale('right', 2).applyOptions({ scaleMargins: { top: 0.15, bottom: 0.1 } })
  chart.timeScale().subscribeVisibleLogicalRangeChange(onVisibleLogicalRangeChange)
  chart.subscribeCrosshairMove(onCrosshairMove)
  chart.subscribeClick(onClick)
  observer = new ResizeObserver(() => resize())
  observer.observe(container.value)
  container.value.addEventListener('pointerup', syncMacdLabelTop)
  replaceBars(props.bars, detailChartViewport(chart) !== null)
})

onUnmounted(() => {
  if (calloutFrame !== null) cancelAnimationFrame(calloutFrame)
  if (viewportStabilityFrame !== null) cancelAnimationFrame(viewportStabilityFrame)
  chart?.timeScale().unsubscribeVisibleLogicalRangeChange(onVisibleLogicalRangeChange)
  chart?.unsubscribeCrosshairMove(onCrosshairMove)
  chart?.unsubscribeClick(onClick)
  observer?.disconnect()
  container.value?.removeEventListener('pointerup', syncMacdLabelTop)
  rangeCache = null
  chart?.remove()
})

watch(() => props.period, () => {
  chart?.applyOptions({ timeScale: { timeVisible: !isDaily() } })
})

watch(() => props.visibleMainIndicators, () => {
  renderDerivedSeries()
}, { deep: true })
watch(() => props.referenceIndicators, () => { renderDerivedSeries() }, { deep: true })
watch(() => props.qualityBreaks, () => { renderAllSeries() }, { deep: true })

watch(
  () => [props.rangeDetectorSourceIdentity, props.rangeDetectorAnchorTime],
  () => { renderDerivedSeries() },
)

watch(() => props.alertMarkers, () => {
  renderDerivedSeries()
}, { deep: true })

watch(() => props.researchMarkers, () => {
  renderDerivedSeries()
}, { deep: true })

function barValues(bars: BarData[]) {
  const values: Array<{ time: Time; open: number; high: number; low: number; close: number } | WhitespaceData<Time>> = bars.map((bar) => ({
    time: chartTime(bar),
    open: bar.open,
    high: bar.high,
    low: bar.low,
    close: bar.close,
  }))
  const occupied = new Set(values.map(item => chartTimeKey(item.time)))
  for (const item of props.qualityBreaks) {
    const time = ribbonTime(item.time)
    const key = time === null ? null : chartTimeKey(time)
    if (time !== null && key !== null && !occupied.has(key)) {
      values.push({ time })
      occupied.add(key)
    }
  }
  return props.qualityBreaks.length
    ? values.sort((left, right) => compareChartTimes(left.time, right.time))
    : values
}

function volumeValues(bars: BarData[]) {
  const theme = resolveChartTheme()
  return bars.map((bar) => ({
    time: chartTime(bar),
    value: bar.volume,
    color: bar.close >= bar.open ? theme.volumeUp : theme.volumeDown,
  }))
}

function replaceBars(bars: BarData[], preserveViewport = false): void {
  const visibleRange = preserveViewport && chart ? detailChartViewport(chart) ?? chart.timeScale().getVisibleLogicalRange() : null
  renderedBars = normalizeBarSeries(bars)
  if (!chart) return
  paginationArmed = false
  lastVisibleFrom.value = null
  renderAllSeries()
  chart.applyOptions({ timeScale: { timeVisible: !isDaily() } })
  const targetRange = detailSession ? detailChartViewport(chart) ?? initialNewowChartLogicalRange(renderedBars.length, container.value?.clientWidth ?? 1000)
    : visibleRange ?? initialChartLogicalRange(renderedBars.length)
  if (targetRange) chart.timeScale().setVisibleLogicalRange(targetRange)
  else chart.timeScale().fitContent()
  beginViewportStabilityCheck(targetRange)
  requestAnimationFrame(() => {
    // Initial placement is not a pagination request. Even when the first
    // page fills the viewport, the first user move toward its left edge
    // must be allowed to request history.
    isNearLeftBoundary = false
    paginationArmed = true
    publishVisibleFrom(chart?.timeScale().getVisibleLogicalRange() ?? null)
    syncMacdLabelTop()
  })
}

function beginViewportStabilityCheck(target: ChartViewportRange | null): void {
  if (viewportStabilityFrame !== null) cancelAnimationFrame(viewportStabilityFrame)
  viewportStabilityTarget = target
  viewportStableFrames = 0
  viewportStabilityAttempts = 0
  chartViewportReady.value = false
  if (target) viewportStabilityFrame = requestAnimationFrame(checkViewportStability)
}

function checkViewportStability(): void {
  viewportStabilityFrame = null
  if (!chart || !viewportStabilityTarget) return
  viewportStabilityAttempts += 1
  const actual = chart.timeScale().getVisibleLogicalRange()
  if (sameLogicalRange(actual, viewportStabilityTarget)) viewportStableFrames += 1
  else {
    viewportStableFrames = 0
    chart.timeScale().setVisibleLogicalRange(viewportStabilityTarget)
  }
  if (viewportStableFrames >= REQUIRED_VIEWPORT_STABLE_FRAMES) {
    chartViewportReady.value = true
    viewportStabilityTarget = null
    return
  }
  if (viewportStabilityAttempts < MAX_VIEWPORT_STABILITY_ATTEMPTS) {
    viewportStabilityFrame = requestAnimationFrame(checkViewportStability)
  }
}

function sameLogicalRange(left: LogicalRange | null, right: ChartViewportRange): boolean {
  return left !== null
    && Math.abs(left.from - right.from) <= LOGICAL_RANGE_EPSILON
    && Math.abs(left.to - right.to) <= LOGICAL_RANGE_EPSILON
}

function prependBars(bars: BarData[]): void {
  if (!chart || !bars.length) return
  const previousLength = renderedBars.length
  const visibleRange = chart.timeScale().getVisibleLogicalRange()
  renderedBars = normalizeBarSeries([...bars, ...renderedBars])
  const prependedCount = renderedBars.length - previousLength
  if (!prependedCount) return
  // An initial warm-up page can arrive before the stability RAF finishes.
  // Shift both targets, otherwise the next RAF would restore the old indices.
  if (!detailSession) viewportStabilityTarget = prependChartLogicalRange(viewportStabilityTarget, prependedCount)
  viewportStableFrames = 0
  const wasArmed = paginationArmed
  paginationArmed = false
  renderAllSeries()
  if (detailSession) {
    const mapped = detailChartViewport(chart)
    if (viewportStabilityTarget) viewportStabilityTarget = mapped
    if (mapped) chart.timeScale().setVisibleLogicalRange(mapped)
  } else if (visibleRange) {
    chart.timeScale().setVisibleLogicalRange({
      from: visibleRange.from + prependedCount,
      to: visibleRange.to + prependedCount,
    })
  }
  paginationArmed = wasArmed
  publishVisibleFrom(chart.timeScale().getVisibleLogicalRange())
}

function updateBar(bar: BarData): void {
  const index = renderedBars.findIndex((item) => item.time === bar.time)
  if (index >= 0) renderedBars[index] = bar
  else renderedBars.push(bar)
  renderedBars = normalizeBarSeries(renderedBars)
  // Live updates rebuild only series data; viewport ownership remains with the user/follow state.
  renderAllSeries()
}

function scrollToLatest(): void {
  chart?.timeScale().scrollToRealTime()
  if (!followLatest) {
    followLatest = true
    emit('follow-latest-change', true)
  }
}

function revealTime(iso: string, exact = false): boolean {
  if (!chart || !props.bars.length) return false
  const parsed = Date.parse(iso)
  if (!Number.isFinite(parsed)) return false
  const targetDay = iso.slice(0, 10)
  const index = isDaily() && !exact
    ? renderedBars.findIndex((bar) => (bar.trading_day ?? bar.time.slice(0, 10)) === targetDay)
    : renderedBars.findIndex((bar) => Date.parse(bar.time) === parsed)
  if (index < 0) return false
  const logicalIndex = detailChartIndex(chart, chartTime(renderedBars[index]!), index)
  if (followLatest) {
    followLatest = false
    emit('follow-latest-change', false)
  }
  const targetRange = {
    from: Math.max(0, logicalIndex - 48),
    to: Math.min(detailChartLength(chart, props.bars.length) - 1, logicalIndex + 8),
  }
  chart.timeScale().setVisibleLogicalRange(targetRange)
  beginViewportStabilityCheck(targetRange)
  return true
}

function timeAtLogical(index: number): string | null {
  const native = chart ? detailChartTimeAt(chart, index) : null
  if (native === null) return renderedBars[Math.max(0, Math.min(renderedBars.length - 1, Math.floor(index)))]?.time ?? null
  const local = renderedBars.find(bar => sameChartTime(chartTime(bar), native))
  if (local) return local.time
  return typeof native === 'number' ? new Date(native * 1000).toISOString()
    : typeof native === 'string' ? native : `${native.year}-${String(native.month).padStart(2, '0')}-${String(native.day).padStart(2, '0')}`
}
function publishRangeResult(range = chart?.timeScale().getVisibleLogicalRange() ?? null) {
  const from = range ? timeAtLogical(range.from) : null
  const to = range ? timeAtLogical(Math.ceil(range.to)) : null
  visibleRangeCount.value = visibleRangeDetectorCount(derivedData.rangeDetector?.ranges ?? [], from, to, renderedBars.at(-1)?.time ?? null)
  emit('range-detector-result', { count: visibleRangeCount.value, calculationMs: rangeCalculationMs.value })
}

function publishVisibleFrom(range: LogicalRange | null) {
  if (!range || !renderedBars.length) return
  const time = timeAtLogical(range.from)
  if (time !== lastVisibleFrom.value) { lastVisibleFrom.value = time; emit('visible-from-change', time) }
  publishRangeResult(range)
}

function onVisibleLogicalRangeChange(range: LogicalRange | null) {
  scheduleReferenceCallouts()
  if (!range || !renderedBars.length) return
  const isFollowing = range.to >= (chart ? detailChartLength(chart, renderedBars.length) : renderedBars.length) - 3
  if (isFollowing !== followLatest) {
    followLatest = isFollowing
    emit('follow-latest-change', isFollowing)
  }
  if (!paginationArmed || props.loading) return
  publishVisibleFrom(range)
  const start = chart ? detailChartIndex(chart, chartTime(renderedBars[0]!), 0) : 0
  const nearLeftBoundary = range.from <= start + 20
  if (!nearLeftBoundary) {
    isNearLeftBoundary = false
    return
  }
  if (!isNearLeftBoundary) {
    isNearLeftBoundary = true
    emit('need-more-before')
  }
}

function onCrosshairMove(param: MouseEventParams<Time>) {
  if (param.time === undefined) {
    hoverContext.value = null
    emit('crosshair-change', null)
    return
  }
  const bar = renderedBars.find((item) => sameChartTime(chartTime(item), param.time!))
  const nextContext = bar
    ? resolveKlineHoverContext(
      renderedBars,
      derivedData,
      props.visibleMainIndicators,
      bar.time,
      markersForHoverContext(),
    )
    : null
  hoverContext.value = nextContext
  emit('crosshair-change', nextContext)
}

function onClick(param: MouseEventParams<Time>) {
  if (!props.markerSelectionEnabled) return
  const hovered = param.hoveredInfo
  if (hovered?.objectKind !== 'series-marker' || typeof hovered.objectId !== 'string') return
  const marker = renderedMarkerById.get(hovered.objectId)
  if (marker) emit('marker-select', marker)
}

function renderAllSeries(): void {
  if (!candles || !volume || !chart) return
  candles.setData(barValues(renderedBars))
  volume.setData(volumeValues(renderedBars))
  renderDerivedSeries()
}

function renderDerivedSeries(): void {
  if (!chart || !macdHistogram || !macdDif || !macdDea) return
  const calculationStarted = performance.now()
  const rangeEnabled = props.visibleMainIndicators.includes('range_detector') && Boolean(props.rangeDetectorSourceIdentity) && Boolean(props.rangeDetectorAnchorTime)
  const rangeKey = JSON.stringify([props.rangeDetectorSourceIdentity, props.rangeDetectorAnchorTime, 'range_detector_lux_v1'])
  const cachedRange = rangeEnabled && rangeCache?.bars === renderedBars && rangeCache.key === rangeKey ? rangeCache.result : null
  derivedData = buildKlineDerivedData(renderedBars, props.visibleMainIndicators, {
    rangeDetector: { enabled: rangeEnabled && !cachedRange, sourceIdentity: props.rangeDetectorSourceIdentity, anchorTime: props.rangeDetectorAnchorTime },
  })
  if (cachedRange) derivedData.rangeDetector = cachedRange
  if (rangeEnabled && derivedData.rangeDetector) rangeCache = { bars: renderedBars, key: rangeKey, result: derivedData.rangeDetector }
  else rangeCache = null
  rangeCalculationMs.value = performance.now() - calculationStarted
  rangeCount.value = derivedData.rangeDetector?.ranges.length ?? 0
  publishRangeResult()
  const referenceOverlay = referenceIndicatorOverlay(renderedBars, props.referenceIndicators)
  if (referenceOverlay) {
    derivedData.ema.ema_21 = referenceOverlay.ema21
  }
  referenceLevelSeries.forEach(series => chart!.removeSeries(series))
  referenceLevelSeries = []
  const levels = referencePriceLevelSegments(renderedBars, props.referenceIndicators ?? [])
  referenceTargetSegments.value = levels.filter(level => level.kind === 'target').length
  referenceStopSegments.value = levels.filter(level => level.kind === 'stop').length
  for (const level of levels) {
    const line = chart.addSeries(LineSeries, { color: level.kind === 'target' ? '#b28a36' : '#cc6262', lineWidth: 1, lineStyle: 2, lastValueVisible: false, priceLineVisible: false, pointMarkersVisible: true, pointMarkersRadius: 2 }, 0)
    line.setData(chartValues(level.points))
    referenceLevelSeries.push(line)
  }
  const theme = resolveChartTheme()

  emaLines.ema_10?.applyOptions({ color: theme.ema10 })
  emaLines.ema_21?.applyOptions({ color: theme.ema21 })
  emaLines.ema_60?.applyOptions({ color: theme.ema60 })
  EMA_INDICATORS.forEach((indicator) => {
    const visible = props.visibleMainIndicators.includes(indicator)
    emaLines[indicator]?.setData(chartValues(visible ? derivedData.ema[indicator] : undefined))
  })
  rangeDetectorPrimitive.setStyle({
    rangeIntact: theme.rangeIntact,
    rangeBrokenUp: theme.rangeBrokenUp,
    rangeBrokenDown: theme.rangeBrokenDown,
    rangeFill: theme.rangeFill,
    rangeMid: theme.rangeMid,
  })
  rangeDetectorPrimitive.setData(
    derivedData.rangeDetector?.ranges ?? [],
    renderedBars.at(-1)?.time ?? null,
    ribbonTime,
  )

  const displayMacd = calculateThsMacdDisplay(renderedBars)
  derivedData.macd = displayMacd
  const displayBarByTime = new Map(renderedBars.map(bar => [bar.time, bar]))
  macdCrossMarkers?.setMarkers(displayMacd.crosses.map(point => ({
    time: chartTime(displayBarByTime.get(point.time)!), position: 'atPriceMiddle' as const, price: point.value,
    shape: 'circle' as const, size: 0, text: point.side === 'golden' ? '▲' : '▼',
    color: point.side === 'golden' ? '#ef232a' : '#14b143',
  })))
  macdPointCount.value = derivedData.macd.dif.filter(point => Number.isFinite(point.value)).length
  macdDif.setData(chartValues(derivedData.macd.dif))
  macdDea.setData(chartValues(derivedData.macd.dea))
  macdHistogram.setData(chartValues(derivedData.macd.histogram).map((point) => (
    'value' in point ? { ...point, color: point.value >= 0 ? theme.volumeUp : theme.volumeDown } : point
  )))

  htdyZk1?.setData(chartValues(derivedData.htdy?.zk1))
  htdyZd1?.setData(chartValues(derivedData.htdy?.zd1))
  htdyZd2?.setData(chartValues(derivedData.htdy?.zd2))
  const displayMarkers = mergedDisplayMarkers()
  const renderedMarkers = chartMarkers(displayMarkers)
  renderedMarkerById = new Map(displayMarkers.filter((marker) => renderedMarkers.some((rendered) => rendered.id === marker.id)).map((marker) => [marker.id, marker]))
  htdyMarkers?.setMarkers(renderedMarkers)
}

function mergedDisplayMarkers(): KlineMarker[] {
  return mergeKlineMarkers(
    mergeKlineMarkers(props.showDerivedMarkers ? derivedData.htdy?.markers ?? [] : [], props.alertMarkers),
    props.researchMarkers,
  )
}

function markersForHoverContext(): KlineMarker[] {
  return mergeKlineMarkers(
    mergeKlineMarkers(props.showDerivedMarkers ? derivedData.htdy?.markers ?? [] : [], props.alertMarkers),
    props.researchMarkers,
  )
}

function chartValues(points: KlineValuePoint[] | undefined): Array<SingleValueData<Time> | WhitespaceData<Time>> {
  if (!points?.length) return []
  const barsByTime = new Map(renderedBars.map((bar) => [bar.time, bar]))
  return points.flatMap((point) => {
    const bar = barsByTime.get(point.time)
    return bar ? [Number.isFinite(point.value)
      ? { time: chartTime(bar), value: point.value }
      : { time: chartTime(bar) }] : []
  })
}

function chartMarkers(markers: KlineMarker[]) {
  const barsByTime = new Map(renderedBars.map((bar) => [markerTimeKey(bar.time), bar]))
  const theme = resolveChartTheme()
  const ordinary = markers.flatMap((marker) => {
    const bar = barsByTime.get(markerTimeKey(marker.time))
    return bar ? [{
      id: marker.id,
      time: chartTime(bar),
      position: marker.position,
      shape: marker.shape,
      color: marker.tone === 'up'
        ? theme.up
        : marker.tone === 'down'
          ? theme.down
          : marker.tone === 'htdy' ? theme.htdy : theme.textMuted,
      text: marker.label,
      size: marker.tone === 'htdy' ? 1.5 : 1,
    }] : []
  })
  const quality = props.qualityBreaks.flatMap(item => {
    const time = ribbonTime(item.time)
    return time === null ? [] : [{
      id: item.id, time, position: 'aboveBar' as const, shape: 'square' as const,
      color: theme.textMuted, text: item.label, size: 1,
    }]
  })
  return [...ordinary, ...quality].sort((left, right) => compareChartTimes(left.time, right.time))
}

function markerTimeKey(value: string): string {
  const timestamp = Date.parse(value)
  return Number.isFinite(timestamp) ? `instant:${timestamp}` : `raw:${value}`
}

function chartTime(bar: BarData): Time {
  return detailSession ? detailChartTime(bar, props.period) : toKlineDisplayTimeForPeriod(bar, props.period) as Time
}

function ribbonTime(iso: string): Time | null {
  if (isDaily()) {
    const day = iso.slice(0, 10)
    return /^\d{4}-\d{2}-\d{2}$/.test(day) ? day as Time : null
  }
  const time = detailSession ? detailChartTime({ time: iso }, props.period) : toKlineDisplayTimeForPeriod({ time: iso }, props.period)
  return time === 0 ? null : time as UTCTimestamp
}

function sameChartTime(left: Time, right: Time): boolean {
  return chartTimeKey(left) === chartTimeKey(right)
}

function compareChartTimes(left: Time, right: Time): number {
  if (typeof left === 'number' && typeof right === 'number') return left - right
  return chartTimeKey(left).localeCompare(chartTimeKey(right))
}

function chartTimeKey(time: Time): string {
  if (typeof time === 'number') return `timestamp:${time}`
  if (typeof time === 'string') return `date:${time}`
  return `date:${time.year}-${String(time.month).padStart(2, '0')}-${String(time.day).padStart(2, '0')}`
}

function isDaily() {
  return props.period === '1d' || props.period === '1w'
}

function syncMacdLabelTop() {
  scheduleReferenceCallouts()
  const panes = chart?.panes()
  if (!panes || panes.length < 3) return
  macdLabelTop.value = panes[0].getHeight() + panes[1].getHeight()
}

function resize() {
  if (!container.value || !chart) return
  if (detailSession) {
    const layout = detailChartPaneLayout(container.value.clientHeight, 32)
    const panes = chart.panes()
    panes[0]?.setStretchFactor(layout.mainHeight)
    panes[1]?.setStretchFactor(layout.volumeHeight)
    panes[2]?.setStretchFactor(layout.auxiliaryHeight)
  }
  chart.resize(container.value.clientWidth, container.value.clientHeight)
  if (viewportStabilityTarget) {
    viewportStableFrames = 0
    chart.timeScale().setVisibleLogicalRange(viewportStabilityTarget)
  }
  requestAnimationFrame(syncMacdLabelTop)
}

defineExpose({
  replaceBars,
  prependBars,
  updateBar,
  scrollToLatest,
  revealTime,
})
</script>

<template>
  <div
    class="kline-shell"
    data-testid="kline-shell"
    :data-alert-marker-count="alertMarkers.length"
    :data-macd-point-count="macdPointCount"
    :data-reference-target-segments="referenceTargetSegments"
    :data-reference-stop-segments="referenceStopSegments"
    :data-research-marker-count="researchMarkers.length"
    :data-rendered-marker-count="mergedDisplayMarkers().length"
    :data-rendered-marker-times="mergedDisplayMarkers().map(marker => marker.time).join(',')"
    :data-rendered-marker-ids="mergedDisplayMarkers().map(marker => marker.id).join(',')"
    :data-rendered-research-marker-count="researchMarkers.length"
    :data-research-marker-ids="researchMarkers.map((marker) => marker.id).join(',')"
    :data-research-marker-times="researchMarkers.map((marker) => marker.time).join(',')"
    :data-range-detector-range-count="rangeCount"
    :data-range-detector-visible-range-count="visibleRangeCount"
    :data-range-detector-calculation-ms="rangeCalculationMs"
    :data-visible-from="lastVisibleFrom"
    :data-chart-viewport-ready="chartViewportReady"
  >
    <div ref="container" class="chart" @pointermove="scheduleReferenceCallouts" @pointerup="scheduleReferenceCallouts" @wheel="scheduleReferenceCallouts" />
    <div v-for="selection in positionedSelection" :key="selection.time" class="reference-candle-selection" aria-hidden="true" :style="{ left: `${selection.x - 6}px`, height: `${selection.height}px` }" />
    <div v-if="referenceCallouts.length" class="reference-callouts" aria-label="历史重算参考信号">
      <ReferenceCalloutLabels :items="positionedCallouts.map(item => ({ position: item, title: item.callout.title, detail: item.callout.detail, direction: item.callout.tone === 'gain' ? 'up' : item.callout.tone === 'loss' ? 'down' : 'neutral', selected: isReferenceSelected(item.callout), labelClass: 'reference-callout', ariaLabel: `${item.callout.title}，参考价 ${item.callout.detail}，历史重算` }))" />
    </div>
    <KlineHoverLegend
      :context="hoverContext"
      :period="period"
      :show-macd="true"
    />
    <div
      class="secondary-panel-label"
      data-testid="secondary-panel-label"
      :style="{ top: macdLabelTop === null ? '80%' : `${macdLabelTop + 5}px` }"
    >
      MACD · MA21 金死叉
    </div>
    <div
      v-if="visibleMainIndicators.includes('htdy')"
      class="htdy-legend"
      data-testid="htdy-chart-legend"
      aria-label="火天大有图例"
    >
      <span><i class="htdy-legend__line htdy-legend__line--zk1" />ZK1 上轨</span>
      <span><i class="htdy-legend__line htdy-legend__line--zd1" />ZD1 下轨</span>
      <span><i class="htdy-legend__line htdy-legend__line--zd2" />ZD2 趋势</span>
    </div>
    <div v-if="loading" class="overlay">读取 Canonical…</div>
    <div v-else-if="error" class="overlay error">{{ error }}</div>
    <div v-else-if="!bars.length" class="overlay">当前窗口无可读 bars</div>
  </div>
</template>

<style scoped>
.kline-shell { position: relative; min-height: 680px; height: clamp(680px, 74vh, 1040px); border: 1px solid var(--gy-border); background: var(--gy-bg-panel); }
.reference-candle-selection { position: absolute; top: 0; width: 12px; background: #aa927b2b; border-inline: 1px solid #8b653d; pointer-events: none; z-index: 2; }
.reference-callouts { position: absolute; inset: 0; pointer-events: none; z-index: 3; overflow: hidden; }
.chart { width: 100%; height: 100%; }
.secondary-panel-label { position: absolute; z-index: 3; left: 10px; min-height: 26px; padding: 3px 8px; background: color-mix(in srgb, var(--gy-bg-panel) 88%, transparent); color: var(--gy-text-primary); font-size: var(--gy-font-size-xs); font-weight: 600; pointer-events: none; }
.htdy-legend { position: absolute; z-index: 2; top: 52px; right: 72px; display: flex; gap: 12px; align-items: center; padding: 5px 9px; border: 1px solid var(--gy-border); border-radius: var(--gy-radius-sm); background: rgba(255, 255, 255, .9); color: var(--gy-text-secondary); font-size: var(--gy-font-size-xs); pointer-events: none; box-shadow: var(--gy-shadow-sm); }
.htdy-legend span { display: inline-flex; gap: 5px; align-items: center; white-space: nowrap; }
.htdy-legend__line { display: inline-block; width: 18px; border-top: 2px solid; }
.htdy-legend__line--zk1 { border-color: var(--gy-chart-htdy-zk1); }
.htdy-legend__line--zd1 { border-color: var(--gy-chart-htdy-zd1); border-top-style: dashed; }
.htdy-legend__line--zd2 { border-color: var(--gy-chart-htdy-zd2); }
.overlay { position: absolute; inset: 0; display: grid; place-items: center; color: var(--gy-text-muted); background: rgba(11, 17, 27, .48); pointer-events: none; }
.overlay.error { color: var(--gy-status-error); }

@media (max-width: 980px) {
  .secondary-panel-label { right: 10px; }
}
</style>
