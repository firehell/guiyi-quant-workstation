<script setup lang="ts">
import { SubingVolumeTierPrimitive } from './subingVolumeTierPrimitive'
import { CHART_PROFILES, mountChartHost, type ChartHost, type ChartProfileId } from '@guiyi/quant-chart'
import { volumePresentation, validVolume, VOLUME_SCALE_OPTIONS, type DisplayVolumeBar } from '@guiyi/quant-chart/volume'
import { readNewowChartDisplayTheme } from '@/utils/newowChartDisplayTheme'

import { formatDisplayNumber } from '@/utils/marketDisplay'
import { DynamicRangePrimitive } from '@/components/kline/dynamicRangePrimitive'
import { matchesRangeBar, pointKey, type DynamicRangePoint } from '@/utils/dynamicRange'
import { NewowPublicPatternPrimitive } from '@/components/market/detail/newow/newowPublicPatternPrimitive'
import type { PatternGeometry } from '@/utils/newowPatternDisplay'
import { inject, nextTick, onMounted, onUnmounted, ref, shallowRef, watch } from 'vue'
import { DETAIL_CHART_SESSION, detailChartViewport, detailChartVolumeBars, detailChartTime, detailChartPaneLayout, detailChartIndex, detailChartLength, detailChartTimeAt, type DetailChartSession } from '@/utils/detailChartSession'
import {
  ColorType,
  createChart,
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
import { marketStudyLayerStatus, type EmaIndicatorId, type MarketChartStudyDisplay, type MarketChartStudyPoint } from '@/utils/marketChartStudies'
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
  chartStudySeries,
  resolveKlineHoverContext,
  type KlineValuePoint,
} from '@/utils/klineViewModel'
import { mergeKlineMarkers } from '@/utils/alertMarkers'
import { previewInstant } from '@/utils/candidatePreviewInstant'
import { referencePriceLevelSegments } from '@/utils/referencePriceLevels'
import { RangeDetectorPrimitive } from '@/components/kline/rangeDetectorPrimitive'

import type { SavedReferenceLine } from '@/utils/newowMarketReference'
import { referenceIndicatorOverlay } from '@/utils/referenceIndicatorOverlay'

function latestStudyPoint(
  points: readonly KlineValuePoint[] | undefined,
  facts: Record<string, MarketChartStudyPoint> | undefined,
): KlineValuePoint | undefined {
  if (!points) return
  for (let index = points.length - 1; index >= 0; index -= 1) {
    const point = points[index]
    if (point && (point.value !== null || facts?.[point.time] !== undefined)) return point
  }
}

const props = withDefaults(defineProps<{
  chartProfile?: ChartProfileId
  dynamicRangePoints?: DynamicRangePoint[]
  dynamicRangeEnabled?: boolean
  patternGeometry?: PatternGeometry | null
  bars: BarData[]
  activeBar?: BarData | null
  volumeScoring?: boolean
  subingVolumeTiers?: boolean
  loading?: boolean
  error?: string | null
  period?: string
  seriesKind: SeriesKind
  visibleMainIndicators?: MainIndicatorId[]
  studyDisplay?: MarketChartStudyDisplay | null
  rangeDetectorSourceIdentity?: string
  rangeDetectorAnchorTime?: string | null
  showDerivedMarkers?: boolean
  alertMarkers?: KlineMarker[]
  researchMarkers?: KlineMarker[]
  savedReferenceLines?: SavedReferenceLine[]
  markerSelectionEnabled?: boolean
  referenceCallouts?: KlineReferenceCallout[]
  referenceIndicators?: KlineReferenceIndicator[]
  referenceSelection?: KlineReferenceSelection[]
  qualityBreaks?: KlineQualityBreak[]
}>(), {
  volumeScoring: true,
  subingVolumeTiers: false,
  dynamicRangePoints: () => [],
  dynamicRangeEnabled: false,
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

const volumeTierPrimitive = new SubingVolumeTierPrimitive()
const volumeTierMarkCount = ref(0)
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
const referenceTargetSegments = ref(0), referenceStopSegments = ref(0)
let host: ChartHost | null = null
let chart: IChartApi | null = null
let candles: ISeriesApi<'Candlestick'> | null = null
let activeCandle: ISeriesApi<'Candlestick'> | null = null
let volume: ISeriesApi<'Histogram'> | null = null
let macdHistogram: ISeriesApi<'Histogram'> | null = null
let macdDif: ISeriesApi<'Line'> | null = null
let macdDea: ISeriesApi<'Line'> | null = null
let macdCrossMarkers: ISeriesMarkersPluginApi<Time> | null = null
let htdyMarkers: ISeriesMarkersPluginApi<Time> | null = null
const emaLines: Partial<Record<EmaIndicatorId, ISeriesApi<'Line'>>> = {}
let bollLines: Record<'upper' | 'middle' | 'lower', ISeriesApi<'Line'>> | null = null
const bollPointCount = ref(0)
const publicPatternPrimitive = new NewowPublicPatternPrimitive(point => chartTime({ time: point.barEnd, trading_day: point.tradingDay } as BarData))
watch(() => props.patternGeometry, value => {
  publicPatternPrimitive.setData(value ?? null)
  detailSession?.restoreInspectionCursor()
})
const rangeDetectorPrimitive = new RangeDetectorPrimitive()
let rangeAttached = false
let htdyLines: Record<'zk1' | 'zd1' | 'zd2', ISeriesApi<'Line'>> | null = null
const dynamicRangePrimitive = new DynamicRangePrimitive()
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
const savedReferenceSeries = new Map<string, ISeriesApi<'Line'>>()
let renderedMarkerById = new Map<string, KlineMarker>()
const drawnMarkers = shallowRef<KlineMarker[]>([])
let viewportStabilityFrame: number | null = null
let viewportStabilityTarget: ChartViewportRange | null = null
let viewportStableFrames = 0
let viewportStabilityAttempts = 0

type ChartViewportRange = { from: number; to: number }
const EMA_INDICATORS: EmaIndicatorId[] = ['ema_10', 'ema_21', 'ema_60']
const MARKER_FACT_LAYERS = ['alerts', 'research_actions', 'reconciliation_execution_markers'] as const
const REQUIRED_VIEWPORT_STABLE_FRAMES = 3
const MAX_VIEWPORT_STABILITY_ATTEMPTS = 12
const LOGICAL_RANGE_EPSILON = 0.001

onMounted(async () => {
  await nextTick()
  if (!container.value) return
  const theme = resolveChartTheme(container.value)
  host = mountChartHost(container.value, {
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
    localization: { timeFormatter: formatChartTimeInShanghai, priceFormatter: (value: number) => formatDisplayNumber(value) },
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
  }, detailSession?.acquire ?? createChart)
  chart = host.chart
  const paneLayout = detailSession ? detailChartPaneLayout(container.value.clientHeight, 32) : null
  chart.panes()[0].setStretchFactor(paneLayout?.mainHeight ?? 6)
  chart.addPane().setStretchFactor(paneLayout?.auxiliaryHeight ?? 2)
  const auxiliary = host.addAuxiliary('default')
  const price = host.layer('price', 'price', 'main')
  candles = price.candles({
    upColor: theme.candleUp,
    downColor: theme.candleDown,
    borderUpColor: theme.candleUp,
    borderDownColor: theme.candleDown,
    wickUpColor: theme.candleUp,
    wickDownColor: theme.candleDown,
  })
  host.layer('pattern', 'newow_pattern', 'main').primitive(candles, publicPatternPrimitive)
  publicPatternPrimitive.setData(props.patternGeometry ?? null)
  htdyMarkers = host.layer('markers', 'display_markers', 'main').markers(candles)
  const profile = props.chartProfile ?? (props.subingVolumeTiers ? 'subing' : props.visibleMainIndicators.includes('htdy') ? 'htdy' : 'free')
  const volumeId = props.subingVolumeTiers && CHART_PROFILES[profile].volume === 'subing' ? 'subing_volume' : 'generic_volume'
  const volumeLayer = host.layer('volume', volumeId, 'volume')
  volume = volumeLayer.histogram({
    priceFormat: { type: 'volume' }, priceScaleId: 'volume', priceLineVisible: false, lastValueVisible: false,
  })
  volume.priceScale().applyOptions(VOLUME_SCALE_OPTIONS)
  if (props.subingVolumeTiers) volumeLayer.primitive(volume, volumeTierPrimitive)
  chart.priceScale('right', 0).applyOptions({ scaleMargins: { top: .05, bottom: .14 } })
  const macd = host.layer('macd', 'ths_macd', auxiliary)
  macdHistogram = macd.histogram({ base: 0, lastValueVisible: false })
  macdDif = macd.line({ color: '#00bfcf', lineWidth: 1, lastValueVisible: false })
  macdDea = macd.line({ color: '#d4b000', lineWidth: 1, lastValueVisible: false })
  macdCrossMarkers = macd.markers(macdDif)
  macd.priceLevel(macdDif, { price: 0, color: '#888888', lineWidth: 1, lineStyle: 0, axisLabelVisible: false, title: '' })
  chart.priceScale('right', 1).applyOptions({ scaleMargins: { top: 0.15, bottom: 0.1 } })
  chart.timeScale().subscribeVisibleLogicalRangeChange(onVisibleLogicalRangeChange)
  chart.subscribeCrosshairMove(onCrosshairMove)
  chart.subscribeClick(onClick)
  const native = chart
  host.own(() => native.timeScale().unsubscribeVisibleLogicalRangeChange(onVisibleLogicalRangeChange))
  host.own(() => native.unsubscribeCrosshairMove(onCrosshairMove))
  host.own(() => native.unsubscribeClick(onClick))
  const observer = new ResizeObserver(() => resize())
  observer.observe(container.value)
  host.own(() => observer.disconnect())
  const chartContainer = container.value
  chartContainer.addEventListener('pointerup', syncMacdLabelTop)
  host.own(() => chartContainer.removeEventListener('pointerup', syncMacdLabelTop))
  replaceBars(props.bars, detailChartViewport(chart) !== null)
  if (typeof MutationObserver !== 'undefined') {
    const themeObserver = new MutationObserver(() => { if (volume) volume.setData(volumeValues(renderedBars)) })
    for (const root of [document.documentElement, document.body]) if (root) themeObserver.observe(root, { attributes: true, attributeFilter: ['data-theme'] })
    volumeLayer.own(() => themeObserver.disconnect())
  }
})

onUnmounted(() => {
  if (calloutFrame !== null) cancelAnimationFrame(calloutFrame)
  if (viewportStabilityFrame !== null) cancelAnimationFrame(viewportStabilityFrame)
  rangeCache = null
  host?.dispose()
  host = null
  chart = null
})

watch(() => props.period, () => {
  chart?.applyOptions({ timeScale: { timeVisible: !isDaily() } })
})

watch(() => props.visibleMainIndicators, () => {
  renderDerivedSeries()
  detailSession?.restoreInspectionCursor()
}, { deep: true })
watch(() => props.studyDisplay, () => {
  renderDerivedSeries()
  detailSession?.restoreInspectionCursor()
})
watch(() => [props.dynamicRangePoints, props.dynamicRangeEnabled], () => { renderDynamicRange(); detailSession?.restoreInspectionCursor() })
watch(() => props.savedReferenceLines, renderSavedReferenceLines)
watch(() => props.referenceIndicators, () => { renderDerivedSeries() }, { deep: true })
watch(() => props.qualityBreaks, () => { renderAllSeries() }, { deep: true })
watch(() => [props.subingVolumeTiers, props.volumeScoring, props.loading, props.error, props.period], () => { renderAllSeries() })

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
  const values: Array<{ time: Time; open: number; high: number; low: number; close: number; physicalContract?: string } | WhitespaceData<Time>> = bars.map((bar) => ({
    time: chartTime(bar),
    open: bar.open,
    high: bar.high,
    low: bar.low,
    close: bar.close,
    physicalContract: bar.confirmed === false ? undefined : bar.physicalContract?.toUpperCase(),
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

function volumeTime(bar: DisplayVolumeBar) {
  return chartTime({ ...bar, trading_day: bar.trading_day ?? bar.tradingDay } as BarData)
}
function volumeValues(bars: BarData[]) {
  const input = chart ? detailChartVolumeBars(chart, bars) : bars
  const theme = readNewowChartDisplayTheme()
  const { colors, tiers } = volumePresentation(props.subingVolumeTiers ? 'subing' : 'generic', input, {
    theme, enabled: props.volumeScoring, allowTiers: !props.loading && !props.error, breaks: props.qualityBreaks,
  })
  const marks = tiers.map(point => ({ time: volumeTime(point.bar), volume: point.bar.volume!, tier: point.tier }))
  volumeTierMarkCount.value = marks.length
  volumeTierPrimitive.setData(marks, theme)
  return input.map((bar, index) => ({ time: volumeTime(bar), ...(validVolume(bar) ? { value: bar.volume, color: colors[index] } : {}) }))
}

function replaceBars(bars: BarData[], preserveViewport = false): void {
  const previousSessionViewport = chart ? detailChartViewport(chart) : null
  const visibleRange = preserveViewport && chart ? detailChartViewport(chart) ?? chart.timeScale().getVisibleLogicalRange() : null
  renderedBars = normalizeBarSeries(bars)
  if (!chart) return
  paginationArmed = false
  lastVisibleFrom.value = null
  renderAllSeries()
  chart.applyOptions({ timeScale: { timeVisible: !isDaily() } })
  const mappedSessionViewport = previousSessionViewport !== null ? detailChartViewport(chart) : null
  const targetRange = detailSession ? mappedSessionViewport ?? initialNewowChartLogicalRange(renderedBars.length, container.value?.clientWidth ?? 1000)
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

function updateLiveBars(bars: BarData[]): void {
  renderedBars = normalizeBarSeries(bars)
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
  if (nextContext && props.dynamicRangeEnabled) {
    const point=props.dynamicRangePoints.find(p => matchesRangeBar(p, nextContext.bar))
    nextContext.dynamicRange=point ?? null
    nextContext.dynamicRangeEnabled=true
  }
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

function renderActiveCandle(): void {
  if (!chart) return
  const active = props.activeBar
  const completed = renderedBars.at(-1)
  if (!active || (completed && compareChartTimes(chartTime(active), chartTime(completed)) <= 0)) {
    activeCandle?.setData([])
    return
  }
  if (!activeCandle) {
    const color = '#b47820'
    activeCandle = host?.layer('price-preview', 'price_preview', 'main').candles({
      upColor: 'transparent', downColor: 'transparent',
      borderUpColor: color, borderDownColor: color, wickUpColor: color, wickDownColor: color,
      priceLineVisible: false, lastValueVisible: false,
    }) ?? null
  }
  activeCandle?.setData([{
    time: chartTime(active), open: active.open, high: active.high, low: active.low, close: active.close,
  }])
}

watch(() => props.activeBar, renderActiveCandle)

function renderSavedReferenceLines(): void {
  if (!host) return
  const lines = props.savedReferenceLines ?? []
  const active = new Set(lines.map(line => line.id))
  for (const id of savedReferenceSeries.keys()) {
    if (active.has(id)) continue
    host.removeLayer(`saved-reference:${id}`)
    savedReferenceSeries.delete(id)
  }
  if (!lines.length) return
  const barsByTime = new Map(renderedBars.map(bar => [bar.time, bar]))
  for (const line of lines) {
    const layer = host.layer(`saved-reference:${line.id}`, 'saved_reference', 'main')
    let series = savedReferenceSeries.get(line.id)
    if (!series) {
      series = layer.line({
        color: line.color, title: line.label, lineWidth: 1, lastValueVisible: false, priceLineVisible: false,
      })
      savedReferenceSeries.set(line.id, series)
    }
    series.setData(chartValues(line.points, barsByTime))
    let cutoff: string | null = null
    for (const point of line.points) {
      if (barsByTime.has(point.time) && Number.isFinite(point.value)) cutoff = point.time
    }
    layer.updateDiagnostics({
      status: cutoff ? 'ready' : 'missing_input', frequency: props.period,
      sourceIdentity: cutoff ? line.sourceRevision : null, formulaVersion: cutoff ? line.formulaVersion : null, dataCutoff: cutoff,
    })
  }
}

function renderAllSeries(): void {
  if (!candles || !volume || !chart) return
  candles.setData(barValues(renderedBars))
  renderActiveCandle()
  const last = renderedBars.at(-1)
  if (container.value) {
    container.value.dataset.klineEnd = last?.time ?? ''
    container.value.dataset.klineCount = String(renderedBars.length)
    container.value.dataset.klineClose = last ? String(last.close) : ''
    container.value.dataset.klineContract = last?.physicalContract ?? ''
    container.value.dataset.klineFrequency = props.period
  }
  volume.setData(volumeValues(renderedBars))
  renderSavedReferenceLines()
  renderDerivedSeries()
}

let dynamicRangeAttached = false
function renderDynamicRange(): void {
  if (!host || !candles) return
  if (!props.dynamicRangeEnabled) {
    host.removeLayer('dynamic-range')
    dynamicRangeAttached = false
    return
  }
  if (!dynamicRangeAttached) {
    host.layer('dynamic-range', 'dynamic_range', 'main').primitive(candles, dynamicRangePrimitive)
    dynamicRangeAttached = true
  }
  const bars = new Map(renderedBars.map(b => [pointKey(b.physicalContract ?? '',b.time),b]))
  dynamicRangePrimitive.setData(props.dynamicRangeEnabled ? props.dynamicRangePoints.filter(p => {
    const b=bars.get(pointKey(p.contract,p.time)); return b && matchesRangeBar(p,b)
  }).map(p => ({...p,time:bars.get(pointKey(p.contract,p.time))!.time})) : [], ribbonTime)
}

const indicatorRenderFailed = ref(false)

function renderDerivedSeries(): void {
  try {
    writeDerivedSeries()
    indicatorRenderFailed.value = false
  } catch {
    // Price and volume have already been committed to their own series.
    indicatorRenderFailed.value = true
  }
}

function writeDerivedSeries(): void {
  if (!host || !candles || !macdHistogram || !macdDif || !macdDea) return
  renderDynamicRange()
  const calculationStarted = performance.now()
  const rangeEnabled = props.visibleMainIndicators.includes('range_detector') && Boolean(props.rangeDetectorSourceIdentity) && Boolean(props.rangeDetectorAnchorTime)
  const rangeKey = JSON.stringify([props.rangeDetectorSourceIdentity, props.rangeDetectorAnchorTime, 'range_detector_lux_v1'])
  const cachedRange = rangeEnabled && rangeCache?.bars === renderedBars && rangeCache.key === rangeKey ? rangeCache.result : null
  derivedData = buildKlineDerivedData(renderedBars, props.visibleMainIndicators, {
    emaPoints: props.studyDisplay?.points,
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
  host.removeLayer('trade-reference')
  const levels = referencePriceLevelSegments(renderedBars, props.referenceIndicators ?? [])
  referenceTargetSegments.value = levels.filter(level => level.kind === 'target').length
  referenceStopSegments.value = levels.filter(level => level.kind === 'stop').length
  for (const level of levels) {
    const line = host.layer('trade-reference', 'trade_reference', 'main').line({ color: level.kind === 'target' ? '#b28a36' : '#cc6262', lineWidth: 1, lineStyle: 2, lastValueVisible: false, priceLineVisible: false, pointMarkersVisible: true, pointMarkersRadius: 2 })
    line.setData(chartValues(level.points))
  }
  const theme = resolveChartTheme()

  const emaColors = { ema_10: theme.ema10, ema_21: theme.ema21, ema_60: theme.ema60 }
  for (const indicator of EMA_INDICATORS) {
    if (!props.visibleMainIndicators.includes(indicator)) {
      host.removeLayer(indicator)
      delete emaLines[indicator]
      continue
    }
    const layer = host.layer(indicator, indicator, 'main')
    const series = emaLines[indicator] ??= layer.line({ color: emaColors[indicator], lineWidth: indicator === 'ema_21' ? 2 : 1, lastValueVisible: false })
    series.applyOptions({ color: emaColors[indicator] })
    const points = chartValues(derivedData.ema[indicator])
    series.setData(points)
    const last = latestStudyPoint(derivedData.ema[indicator], derivedData.emaFacts[indicator])
    const fact = last ? derivedData.emaFacts[indicator]?.[last.time] : undefined
    const identity = referenceOverlay && indicator === 'ema_21' ? undefined : props.studyDisplay?.features[indicator]
    layer.updateDiagnostics({ frequency: props.period,
      status: last?.value != null ? 'ready' : marketStudyLayerStatus(fact),
      formulaVersion: identity?.formulaVersion ?? null, sourceIdentity: identity ? props.studyDisplay?.sourceRevision : null,
      dataCutoff: last?.time ?? null, lastError: last?.value != null ? null : fact?.diagnostic ?? null })
  }
  if (props.visibleMainIndicators.includes('boll')) {
    const layer = host.layer('boll', 'boll', 'main')
    const boundary = { color: theme.ema60, lineWidth: 1, lineStyle: 2, lastValueVisible: false, priceLineVisible: false } as const
    const center = { ...boundary, color: theme.ema10, lineStyle: 0 } as const
    bollLines ??= { ...layer.band(boundary, boundary), middle: layer.line(center) }
    const facts = props.studyDisplay?.points.boll
    const middle = chartStudySeries(renderedBars, facts, 'middle')
    const last = latestStudyPoint(middle, facts)
    const fact = last && facts?.[last.time]
    bollLines.upper.applyOptions(boundary)
    bollLines.middle.applyOptions(center)
    bollLines.lower.applyOptions(boundary)
    bollLines.upper.setData(chartValues(chartStudySeries(renderedBars, facts, 'upper')))
    bollLines.middle.setData(chartValues(middle))
    bollLines.lower.setData(chartValues(chartStudySeries(renderedBars, facts, 'lower')))
    bollPointCount.value = middle.filter(point => point.value !== null).length
    layer.updateDiagnostics({
      frequency: props.period, formulaVersion: props.studyDisplay?.features.boll?.formulaVersion ?? null,
      sourceIdentity: facts ? props.studyDisplay?.sourceRevision : null, dataCutoff: last?.time ?? null,
      status: last?.value != null ? 'ready' : marketStudyLayerStatus(fact),
      lastError: fact?.diagnostic ?? null,
    })
  } else if (bollLines) {
    host.removeLayer('boll')
    bollLines = null
    bollPointCount.value = 0
  }
  if (rangeEnabled && !rangeAttached) {
    host.layer('range-detector', 'range_detector', 'main').primitive(candles, rangeDetectorPrimitive)
    rangeAttached = true
  } else if (!rangeEnabled && rangeAttached) {
    host.removeLayer('range-detector')
    rangeAttached = false
  }
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

  const displayBarByTime = new Map(renderedBars.map(bar => [bar.time, bar]))
  macdCrossMarkers?.setMarkers(derivedData.macd.crosses.map(point => ({
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

  if (props.visibleMainIndicators.includes('htdy')) {
    const layer = host.layer('htdy', 'htdy', 'main')
    htdyLines ??= {
      zk1: layer.line({ color: theme.htdyZk1, lineWidth: 2, lineStyle: 0, lastValueVisible: false }),
      zd1: layer.line({ color: theme.htdyZd1, lineWidth: 2, lineStyle: 2, lastValueVisible: false }),
      zd2: layer.line({ color: theme.htdyZd2, lineWidth: 2, lineStyle: 0, lastValueVisible: false }),
    }
    for (const key of ['zk1', 'zd1', 'zd2'] as const) htdyLines[key].setData(chartValues(derivedData.htdy?.[key]))
    layer.updateDiagnostics({ frequency: props.period, formulaVersion: 'original-v0',
      status: derivedData.htdy ? 'ready' : 'missing_input', dataCutoff: renderedBars.at(-1)?.time ?? null })
  } else {
    host.removeLayer('htdy')
    htdyLines = null
  }
  const displayMarkers = mergedDisplayMarkers()
  const { native, drawn } = chartMarkers(displayMarkers)
  htdyMarkers?.setMarkers(native)
  drawnMarkers.value = drawn
  renderedMarkerById = new Map(drawn.map(marker => [marker.id, marker]))
  // Keep one marker renderer so same-Bar stacking and hit testing stay consistent.
  host.layer('markers', 'display_markers', 'main').updateDiagnostics({
    status: native.length ? 'ready' : 'missing_input', frequency: props.period,
    formulaVersion: 'main_marker_layout_v1', dataCutoff: drawn.at(-1)?.time ?? null,
  })
  for (const id of MARKER_FACT_LAYERS) {
    const layerId = `marker-facts:${id}`
    if (!displayMarkers.some(marker => marker.fact?.layer === id)) {
      host.removeLayer(layerId)
      continue
    }
    let latest: KlineMarker | undefined
    for (const marker of drawn) {
      if (marker.fact?.layer === id) latest = marker
    }
    host.layer(layerId, id, 'main').updateDiagnostics({
      status: latest ? 'ready' : 'missing_input', frequency: props.period,
      sourceIdentity: latest?.fact?.sourceIdentity ?? null,
      formulaVersion: latest?.fact?.formulaVersion ?? null, dataCutoff: latest?.time ?? null,
    })
  }
}

function mergedDisplayMarkers(): KlineMarker[] {
  return mergeKlineMarkers(
    mergeKlineMarkers(props.showDerivedMarkers ? derivedData.htdy?.markers ?? [] : [], props.alertMarkers),
    props.researchMarkers,
  )
}

function markersForHoverContext(): KlineMarker[] {
  return drawnMarkers.value
}

function chartValues(points: KlineValuePoint[] | undefined, visibleBars?: ReadonlyMap<string, BarData>): Array<SingleValueData<Time> | WhitespaceData<Time>> {
  if (!points?.length) return []
  const barsByTime = visibleBars ?? new Map(renderedBars.map((bar) => [bar.time, bar]))
  return points.flatMap((point) => {
    const bar = barsByTime.get(point.time)
    return bar ? [point.value !== null && Number.isFinite(point.value)
      ? { time: chartTime(bar), value: point.value }
      : { time: chartTime(bar) }] : []
  })
}

function chartMarkers(markers: KlineMarker[]) {
  const barsByTime = new Map(renderedBars.map((bar) => [markerTimeKey(bar.time), bar]))
  const theme = resolveChartTheme()
  const drawn: KlineMarker[] = []
  const ordinary = markers.flatMap((marker) => {
    const bar = barsByTime.get(markerTimeKey(marker.time))
    if (!bar) return []
    const fact = marker.fact
    if (fact && (bar.confirmed === false
      || bar.physicalContract?.toUpperCase() !== fact.physicalContract.toUpperCase()
      || (fact.frequency !== null && fact.frequency !== props.period))) return []
    drawn.push(marker)
    return [{
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
    }]
  })
  const quality = props.qualityBreaks.flatMap(item => {
    const time = ribbonTime(item.time)
    return time === null ? [] : [{
      id: item.id, time, position: 'aboveBar' as const, shape: 'square' as const,
      color: theme.textMuted, text: item.label, size: 1,
    }]
  })
  return { native: [...ordinary, ...quality].sort((left, right) => compareChartTimes(left.time, right.time)), drawn }
}

function markerTimeKey(value: string): string {
  const timestamp = previewInstant(value)
  return timestamp === null ? `raw:${value}` : `instant:${timestamp}`
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
  if (!panes || panes.length < 2) return
  macdLabelTop.value = panes[0].getHeight()
}

function resize() {
  if (!container.value || !chart) return
  if (detailSession) {
    const layout = detailChartPaneLayout(container.value.clientHeight, 32)
    const panes = chart.panes()
    panes[0]?.setStretchFactor(layout.mainHeight)
    panes[1]?.setStretchFactor(layout.auxiliaryHeight)
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
  updateLiveBars,
  scrollToLatest,
  revealTime,
  inspectLayers: () => [...(host?.diagnostics() ?? []), ...(detailSession?.inspectExecutionLayers() ?? [])],
})
</script>

<template>
  <div
    class="kline-shell"
    data-testid="kline-shell"
    :data-subing-volume-tier-mark-count="volumeTierMarkCount"
    :data-subing-volume-tiers="subingVolumeTiers"
    :data-alert-marker-count="alertMarkers.length"
    :data-macd-point-count="macdPointCount"
    :data-boll-point-count="bollPointCount"
    :data-reference-target-segments="referenceTargetSegments"
    :data-reference-stop-segments="referenceStopSegments"
    :data-research-marker-count="researchMarkers.length"
    :data-rendered-marker-count="drawnMarkers.length"
    :data-rendered-marker-times="drawnMarkers.map(marker => marker.time).join(',')"
    :data-rendered-marker-ids="drawnMarkers.map(marker => marker.id).join(',')"
    :data-rendered-research-marker-count="drawnMarkers.filter(marker => marker.fact?.layer === 'research_actions').length"
    :data-research-marker-ids="researchMarkers.map((marker) => marker.id).join(',')"
    :data-research-marker-times="researchMarkers.map((marker) => marker.time).join(',')"
    :data-range-detector-range-count="rangeCount"
    :data-range-detector-visible-range-count="visibleRangeCount"
    :data-range-detector-calculation-ms="rangeCalculationMs"
    :data-visible-from="lastVisibleFrom"
    :data-chart-viewport-ready="chartViewportReady"
  >
    <p v-if="indicatorRenderFailed" role="status">指标图层更新失败，当前仍可查看 K 线。</p>
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
