<script setup lang="ts">
import { SubingVolumeTierPrimitive } from './subingVolumeTierPrimitive'
import { CHART_PROFILES, DISPLAY_CATALOG, mountChartHost, type ChartHost, type ChartLayer, type ChartProfileId } from '@guiyi/quant-chart'
import { volumePresentation, validVolume, VOLUME_DISPLAY_VERSION, VOLUME_SCALE_OPTIONS, type DisplayVolumeBar } from '@guiyi/quant-chart/volume'
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
import { marketStudyLayerStatus, type EmaIndicatorId, type MarketChartStudyDisplay, type MarketChartStudyIssue, type MarketChartStudyPoint } from '@/utils/marketChartStudies'
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
import { NEWOW_PUBLIC_PATTERNS_METADATA } from '@/utils/newowPublicPatterns'
import { THS_MACD_DISPLAY_VERSION } from '@/utils/thsMacdDisplay'

function lastMatching<T>(items: readonly T[], matches: (item: T) => boolean): T | undefined {
  for (let index = items.length - 1; index >= 0; index--) {
    const item = items[index]!
    if (matches(item)) return item
  }
}

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
  studyIssue?: MarketChartStudyIssue | null
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
  if (sharedPriceWritten && chart && candles && container.value) {
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
let sharedPriceWritten = false
let activeCandle: ISeriesApi<'Candlestick'> | null = null
let volume: ISeriesApi<'Histogram'> | null = null
let volumeLayer: ChartLayer | null = null
let macdHistogram: ISeriesApi<'Histogram'> | null = null
let macdDif: ISeriesApi<'Line'> | null = null
let macdDea: ISeriesApi<'Line'> | null = null
let macdCrossMarkers: ISeriesMarkersPluginApi<Time> | null = null
let htdyMarkers: ISeriesMarkersPluginApi<Time> | null = null
const emaLines: Partial<Record<EmaIndicatorId, ISeriesApi<'Line'>>> = {}
let bollLines: Record<'upper' | 'middle' | 'lower', ISeriesApi<'Line'>> | null = null
const bollPointCount = ref(0)
const publicPatternPrimitive = new NewowPublicPatternPrimitive(point => chartTime({ time: point.barEnd, trading_day: point.tradingDay } as BarData))
watch(() => props.patternGeometry, () => {
  renderPublicPattern()
  detailSession?.restoreInspectionCursor()
})
const rangeDetectorPrimitive = new RangeDetectorPrimitive()
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
  chart.addPane()
  syncPaneLayout()
  host.addAuxiliary('default')
  const price = host.layer('price', 'price', 'main')
  candles = price.candles({
    upColor: theme.candleUp,
    downColor: theme.candleDown,
    borderUpColor: theme.candleUp,
    borderDownColor: theme.candleDown,
    wickUpColor: theme.candleUp,
    wickDownColor: theme.candleDown,
  })
  const profile = props.chartProfile ?? (props.subingVolumeTiers ? 'subing' : props.visibleMainIndicators.includes('htdy') ? 'htdy' : 'free')
  const volumeId = props.subingVolumeTiers && CHART_PROFILES[profile].volume === 'subing' ? 'subing_volume' : 'generic_volume'
  volumeLayer = host.layer('volume', volumeId, 'volume')
  volume = volumeLayer.histogram({
    priceFormat: { type: 'volume' }, priceScaleId: 'volume', priceLineVisible: false, lastValueVisible: false,
  })
  volume.priceScale().applyOptions(VOLUME_SCALE_OPTIONS)
  chart.priceScale('right', 0).applyOptions({ scaleMargins: { top: .05, bottom: .14 } })
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
    const themeObserver = new MutationObserver(renderVolumeBars)
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
  volumeLayer = null
})

watch(() => props.period, () => {
  chart?.applyOptions({ timeScale: { timeVisible: !isDaily() } })
})

watch(() => props.visibleMainIndicators, () => {
  renderDerivedSeries()
  detailSession?.restoreInspectionCursor()
}, { deep: true })
watch([() => props.studyDisplay, () => props.studyIssue], () => {
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
function renderPublicPattern(): void {
  const anchor = candles
  const pattern = props.patternGeometry
  if (!host || !anchor) return
  if (!pattern || !sharedPriceWritten) {
    host.removeLayer('pattern')
    return
  }
  host.renderLayer('pattern', 'newow_pattern', 'main', 'primitive', layer => {
    if (!layer.hasResource(publicPatternPrimitive)) layer.primitive(anchor, publicPatternPrimitive)
    publicPatternPrimitive.setData(pattern)
    // The geometry carries drawing coordinates but no hash of its scanner input.
    let cutoff: string | null = null
    for (const point of [...pattern.anchors, ...pattern.lines.flatMap(line => line.points)]) {
      if (cutoff === null || Date.parse(point.barEnd) > Date.parse(cutoff)) cutoff = point.barEnd
    }
    layer.updateDiagnostics({
      status: cutoff ? 'ready' : 'missing_input', formulaVersion: NEWOW_PUBLIC_PATTERNS_METADATA.version,
      frequency: pattern.frequency, dataCutoff: cutoff, sourceIdentity: null,
    })
  })
}

function barProvenance(bar: Pick<BarData, 'time' | 'sourceBarSha256'> | undefined) {
  return { frequency: props.period, sourceIdentity: bar?.sourceBarSha256 ?? null, dataCutoff: bar?.time ?? null }
}

function renderVolumeBars(): void {
  if (!volume) return
  const input = chart ? detailChartVolumeBars(chart, renderedBars) : renderedBars
  const theme = readNewowChartDisplayTheme()
  const { colors, tiers, lastTierEvaluation } = volumePresentation(props.subingVolumeTiers ? 'subing' : 'generic', input, {
    theme, enabled: props.volumeScoring, allowTiers: !props.loading && !props.error, breaks: props.qualityBreaks,
  })
  const marks = tiers.map(point => ({ time: volumeTime(point.bar), volume: point.bar.volume!, tier: point.tier }))
  try {
    volume.setData(input.map((bar, index) => ({ time: volumeTime(bar), ...(validVolume(bar) ? { value: bar.volume, color: colors[index] } : {}) })))
  } catch {
    volumeLayer?.updateDiagnostics({
      status: 'renderer_failure', frequency: props.period, sourceIdentity: null, dataCutoff: null,
      formulaVersion: null, lastError: 'CHART_RENDERER_UPDATE_FAILED',
    })
    host?.removeLayer('volume-tiers')
    volumeTierMarkCount.value = 0
    return
  }
  const latestVolume = lastMatching<DisplayVolumeBar>(input, validVolume)
  const scoringVersion = !props.subingVolumeTiers && props.volumeScoring ? VOLUME_DISPLAY_VERSION : null
  volumeLayer?.updateDiagnostics({
    ...barProvenance(latestVolume),
    ...(scoringVersion ? { sourceIdentity: null } : {}),
    status: latestVolume ? 'ready' : props.loading ? 'loading' : 'missing_input',
    formulaVersion: scoringVersion, lastError: null,
  })
  const anchor = volume
  const tierSource = DISPLAY_CATALOG.subing_volume?.source
  const written = Boolean(props.subingVolumeTiers && host?.renderLayer('volume-tiers', 'subing_volume', 'volume', 'primitive', layer => {
    if (!layer.hasResource(volumeTierPrimitive)) layer.primitive(anchor, volumeTierPrimitive, () => {
      volumeTierMarkCount.value = 0
    })
    volumeTierPrimitive.setData(marks, theme)
    layer.updateDiagnostics({
      sourceIdentity: null, frequency: props.period, dataCutoff: lastTierEvaluation?.time ?? null,
      status: !props.volumeScoring ? 'hidden' : props.loading ? 'loading' : props.error ? 'missing_input'
        : lastTierEvaluation ? 'ready' : 'missing_input',
      renderer: 'primitive',
      formulaVersion: tierSource?.type === 'display_transform' ? tierSource.version : null,
    })
  }))
  if (!props.subingVolumeTiers) host?.removeLayer('volume-tiers')
  volumeTierMarkCount.value = written ? marks.length : 0
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
  if (!sharedPriceWritten || param.time === undefined) {
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
  if (!host) return
  const active = props.activeBar
  const tail = renderedBars.at(-1)
  const leading = active && (!tail || compareChartTimes(chartTime(active), chartTime(tail)) > 0) ? active : null
  const pending = leading ?? (sharedPriceWritten ? lastMatching(renderedBars, bar => bar.confirmed === false) : undefined)
  if (!activeCandle && !leading && !pending) {
    host.removeLayer('price-preview')
    return
  }
  const written = host.renderLayer('price-preview', 'price_preview', 'main', 'candles', layer => {
    if (leading && !activeCandle) {
      const color = '#b47820'
      activeCandle = layer.candles({
        upColor: 'transparent', downColor: 'transparent',
        borderUpColor: color, borderDownColor: color, wickUpColor: color, wickDownColor: color,
        priceLineVisible: false, lastValueVisible: false,
      })
    }
    activeCandle?.setData(leading ? [{
      time: chartTime(leading), open: leading.open, high: leading.high, low: leading.low, close: leading.close,
    }] : [])
    layer.updateDiagnostics({ ...barProvenance(pending), status: pending ? 'ready' : 'hidden' })
  })
  if (!written) activeCandle = null
}

watch(() => props.activeBar, renderActiveCandle)

function renderSavedReferenceLines(): void {
  if (!host) return
  const lines = sharedPriceWritten ? props.savedReferenceLines ?? [] : []
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
  if (!host || !candles || !volume || !chart) return
  const price = host.layer('price', 'price', 'main')
  const wasWritten = sharedPriceWritten
  try {
    candles.setData(barValues(renderedBars))
    sharedPriceWritten = true
    const confirmed = lastMatching(renderedBars, bar => bar.confirmed !== false)
    price.updateDiagnostics({
      ...barProvenance(confirmed), status: confirmed ? 'ready' : props.loading ? 'loading' : 'missing_input', lastError: null,
    })
  } catch {
    sharedPriceWritten = false
    positionedCallouts.value = []
    positionedSelection.value = []
    if (hoverContext.value) {
      hoverContext.value = null
      emit('crosshair-change', null)
    }
    price.updateDiagnostics({
      ...barProvenance(undefined), status: 'renderer_failure', lastError: 'CHART_RENDERER_UPDATE_FAILED',
    })
  }
  if (sharedPriceWritten !== wasWritten) renderPublicPattern()
  renderActiveCandle()
  const last = sharedPriceWritten ? renderedBars.at(-1) : undefined
  if (container.value) {
    container.value.dataset.klineEnd = last?.time ?? ''
    container.value.dataset.klineCount = String(sharedPriceWritten ? renderedBars.length : 0)
    container.value.dataset.klineClose = last ? String(last.close) : ''
    container.value.dataset.klineContract = last?.physicalContract ?? ''
    container.value.dataset.klineFrequency = props.period
  }
  renderVolumeBars()
  renderSavedReferenceLines()
  renderDerivedSeries()
}

function renderDynamicRange(): void {
  if (!host || !candles) return
  if (!props.dynamicRangeEnabled || !sharedPriceWritten) {
    host.removeLayer('dynamic-range')
    return
  }
  const anchor = candles
  const bars = new Map(renderedBars.map(b => [pointKey(b.physicalContract ?? '',b.time),b]))
  const points = props.dynamicRangePoints.filter(p => {
    const b=bars.get(pointKey(p.contract,p.time)); return b && matchesRangeBar(p,b)
  }).map(p => ({...p,time:bars.get(pointKey(p.contract,p.time))!.time}))
  host.renderLayer('dynamic-range', 'dynamic_range', 'main', 'primitive', layer => {
    if (!layer.hasResource(dynamicRangePrimitive)) layer.primitive(anchor, dynamicRangePrimitive)
    dynamicRangePrimitive.setData(points, ribbonTime)
    layer.updateDiagnostics({ status: points.length ? 'ready' : 'missing_input', frequency: props.period,
      dataCutoff: points.at(-1)?.time ?? null })
  })
}

const indicatorRenderFailed = ref(false)

function renderDerivedSeries(): void {
  try {
    writeDerivedSeries()
    indicatorRenderFailed.value = false
  } catch {
    // A derived layer must not prevent the remaining base series from updating.
    indicatorRenderFailed.value = true
  }
}

function writeDerivedSeries(): void {
  if (!host || !candles) return
  renderDynamicRange()
  const calculationStarted = performance.now()
  const rangeSelected = props.visibleMainIndicators.includes('range_detector')
  const rangeEnabled = sharedPriceWritten && rangeSelected && Boolean(props.rangeDetectorSourceIdentity) && Boolean(props.rangeDetectorAnchorTime)
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
  const levels = sharedPriceWritten ? referencePriceLevelSegments(renderedBars, props.referenceIndicators ?? []) : []
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
    const usesReference = Boolean(referenceOverlay && indicator === 'ema_21')
    if (props.studyIssue && !usesReference) {
      host.removeLayer(indicator)
      delete emaLines[indicator]
      host.layer(indicator, indicator, 'main').updateDiagnostics({
        status: props.studyIssue.status, frequency: props.period, lastError: props.studyIssue.reason,
      })
      continue
    }
    const last = latestStudyPoint(derivedData.ema[indicator], derivedData.emaFacts[indicator])
    const fact = last ? derivedData.emaFacts[indicator]?.[last.time] : undefined
    const identity = usesReference ? undefined : props.studyDisplay?.features[indicator]
    const written = host.renderLayer(indicator, indicator, 'main', 'line', layer => {
      const series = emaLines[indicator] ??= layer.line({ color: emaColors[indicator], lineWidth: indicator === 'ema_21' ? 2 : 1, lastValueVisible: false })
      series.applyOptions({ color: emaColors[indicator] })
      series.setData(chartValues(derivedData.ema[indicator]))
      layer.updateDiagnostics({ frequency: props.period,
        status: last?.value != null ? 'ready' : marketStudyLayerStatus(fact),
        formulaVersion: identity?.formulaVersion ?? null, sourceIdentity: identity ? props.studyDisplay?.sourceRevision : null,
        dataCutoff: last?.time ?? null, lastError: last?.value != null ? null : fact?.diagnostic ?? null })
    })
    if (!written) delete emaLines[indicator]
  }
  renderBoll(theme)
  const anchor = candles
  if (rangeSelected) host.renderLayer('range-detector', 'range_detector', 'main', 'primitive', layer => {
    if (!layer.hasResource(rangeDetectorPrimitive)) layer.primitive(anchor, rangeDetectorPrimitive)
    rangeDetectorPrimitive.setStyle({
      rangeIntact: theme.rangeIntact,
      rangeBrokenUp: theme.rangeBrokenUp,
      rangeBrokenDown: theme.rangeBrokenDown,
      rangeFill: theme.rangeFill,
      rangeMid: theme.rangeMid,
    })
    rangeDetectorPrimitive.setData(derivedData.rangeDetector?.ranges ?? [], renderedBars.at(-1)?.time ?? null, ribbonTime)
    const point = derivedData.rangeDetector?.points.at(-1)
    layer.updateDiagnostics({
      status: !point ? (props.loading ? 'loading' : 'missing_input') : !point.valid ? 'invalid_source' : point.ready ? 'ready' : 'warming',
      frequency: props.period,
      sourceIdentity: point?.snapshot?.sourceIdentity ?? null,
      formulaVersion: 'range_detector_lux_v1',
      dataCutoff: point?.time ?? null,
      cacheState: point ? (cachedRange ? 'hit' : 'miss') : null,
      lastError: point?.reason ?? null,
    })
  })
  else {
    host.removeLayer('range-detector')
  }

  writeMarkersAndMacd(theme)
}

function renderBoll(theme: ReturnType<typeof resolveChartTheme>): void {
  if (!host) return
  const selected = props.visibleMainIndicators.includes('boll')
  if (!selected || props.studyIssue) {
    host.removeLayer('boll')
    bollLines = null
    bollPointCount.value = 0
    if (selected && props.studyIssue) host.layer('boll', 'boll', 'main').updateDiagnostics({
      status: props.studyIssue.status, frequency: props.period, lastError: props.studyIssue.reason,
    })
    return
  }
  const written = host.renderLayer('boll', 'boll', 'main', 'band', layer => {
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
  })
  if (!written) {
    bollLines = null
    bollPointCount.value = 0
  }
}

function renderThsMacd(theme: ReturnType<typeof resolveChartTheme>): void {
  const currentHost = host
  if (!currentHost) return
  const pane = { auxiliary: 'default' } as const
  const barsByTime = new Map(renderedBars.map(bar => [bar.time, bar]))
  const dif = chartValues(derivedData.macd.dif, barsByTime)
  const dea = chartValues(derivedData.macd.dea, barsByTime)
  const histogram = chartValues(derivedData.macd.histogram, barsByTime)
  const latestValue = lastMatching(derivedData.macd.histogram, point => Number.isFinite(point.value))
  const latestBar = latestValue && barsByTime.get(latestValue.time)
  const written = currentHost.renderLayer('macd', 'ths_macd', pane, 'histogram', layer => {
    if (!macdDif) {
      macdHistogram = layer.histogram({ base: 0, lastValueVisible: false })
      macdDif = layer.line({ color: '#00bfcf', lineWidth: 1, lastValueVisible: false })
      macdDea = layer.line({ color: '#d4b000', lineWidth: 1, lastValueVisible: false })
      layer.priceLevel(macdDif, { price: 0, color: '#888888', lineWidth: 1, lineStyle: 0, axisLabelVisible: false, title: '' })
      chart?.priceScale('right', 1).applyOptions({ scaleMargins: { top: 0.15, bottom: 0.1 } })
      syncPaneLayout()
    }
    try {
      macdDif?.setData(dif)
      macdDea?.setData(dea)
      macdHistogram?.setData(histogram.map(point => 'value' in point
        ? { ...point, color: point.value >= 0 ? theme.volumeUp : theme.volumeDown } : point))
    } catch (error) {
      // The cross marks own a plugin on DIF, so detach before the series is removed.
      currentHost.removeLayer('macd-crosses')
      throw error
    }
    layer.updateDiagnostics({
      frequency: props.period, sourceIdentity: null, dataCutoff: latestBar?.time ?? null,
      status: latestBar ? 'ready' : props.loading ? 'loading' : 'missing_input',
      formulaVersion: THS_MACD_DISPLAY_VERSION, renderer: 'histogram',
    })
  })
  const anchor = macdDif
  if (!written || !anchor) {
    currentHost.removeLayer('macd-crosses')
    macdHistogram = null
    macdDif = null
    macdDea = null
    macdCrossMarkers = null
    macdPointCount.value = 0
    return
  }
  macdPointCount.value = dif.filter(point => 'value' in point).length

  const latest = renderedBars.at(-1)
  const { available, required } = derivedData.macd.crossWarmup
  const marks = derivedData.macd.crosses.flatMap(point => {
    const bar = barsByTime.get(point.time)
    if (!bar || !Number.isFinite(point.value)) return []
    return [{ time: chartTime(bar), position: 'atPriceMiddle' as const, price: point.value, shape: 'circle' as const,
      size: 0, text: point.side === 'golden' ? '▲' : '▼', color: point.side === 'golden' ? '#ef232a' : '#14b143' }]
  })
  const crosses = currentHost.renderLayer('macd-crosses', 'ths_macd', pane, 'marker', layer => {
    if (macdCrossMarkers && !layer.hasResource(macdCrossMarkers)) {
      layer.remove(macdCrossMarkers)
      macdCrossMarkers = null
    }
    macdCrossMarkers ??= layer.markers(anchor)
    macdCrossMarkers.setMarkers(marks)
    layer.updateDiagnostics({
      frequency: props.period, sourceIdentity: null, dataCutoff: available > 0 ? latest?.time ?? null : null,
      status: available === required ? 'ready' : available > 0 ? 'warming' : props.loading ? 'loading' : 'missing_input',
      renderer: 'marker', formulaVersion: THS_MACD_DISPLAY_VERSION,
      warmup: { available, required },
    })
  })
  if (!crosses) macdCrossMarkers = null
}

function writeMarkersAndMacd(theme: ReturnType<typeof resolveChartTheme>): void {
  if (!host) return
  renderThsMacd(theme)
  if (props.visibleMainIndicators.includes('htdy')) {
    const written = host.renderLayer('htdy', 'htdy', 'main', 'line', layer => {
      htdyLines ??= {
        zk1: layer.line({ color: theme.htdyZk1, lineWidth: 2, lineStyle: 0, lastValueVisible: false }),
        zd1: layer.line({ color: theme.htdyZd1, lineWidth: 2, lineStyle: 2, lastValueVisible: false }),
        zd2: layer.line({ color: theme.htdyZd2, lineWidth: 2, lineStyle: 0, lastValueVisible: false }),
      }
      for (const key of ['zk1', 'zd1', 'zd2'] as const) htdyLines[key].setData(chartValues(derivedData.htdy?.[key]))
      layer.updateDiagnostics({ frequency: props.period, formulaVersion: 'original-v0',
        status: derivedData.htdy ? 'ready' : 'missing_input', dataCutoff: renderedBars.at(-1)?.time ?? null })
    })
    if (!written) htdyLines = null
  } else {
    host.removeLayer('htdy')
    htdyLines = null
  }
  const displayMarkers = mergedDisplayMarkers()
  const { native, drawn } = chartMarkers(displayMarkers)
  const markerAnchor = sharedPriceWritten ? candles : null
  if (!markerAnchor) host.removeLayer('markers')
  // Keep one marker renderer so same-Bar stacking and hit testing stay consistent.
  const written = Boolean(markerAnchor && host.renderLayer('markers', 'display_markers', 'main', 'marker', layer => {
    if (htdyMarkers && !layer.hasResource(htdyMarkers)) {
      layer.remove(htdyMarkers)
      htdyMarkers = null
    }
    htdyMarkers ??= layer.markers(markerAnchor, undefined, clearMarkerPaintReadback)
    htdyMarkers.setMarkers(native)
    layer.updateDiagnostics({
      status: native.length ? 'ready' : 'missing_input', frequency: props.period,
      formulaVersion: 'main_marker_layout_v1', dataCutoff: drawn.at(-1)?.time ?? null,
    })
  }))
  if (!written) htdyMarkers = null
  const visible = written ? drawn : []
  drawnMarkers.value = visible
  renderedMarkerById = new Map(visible.map(marker => [marker.id, marker]))
  for (const id of MARKER_FACT_LAYERS) {
    const layerId = `marker-facts:${id}`
    if (!displayMarkers.some(marker => marker.fact?.layer === id)) {
      host.removeLayer(layerId)
      continue
    }
    let latest: KlineMarker | undefined
    for (const marker of visible) {
      if (marker.fact?.layer === id) latest = marker
    }
    host.layer(layerId, id, 'main').updateDiagnostics({
      status: latest ? 'ready' : 'missing_input', frequency: props.period,
      sourceIdentity: latest?.fact?.sourceIdentity ?? null,
      formulaVersion: latest?.fact?.formulaVersion ?? null, dataCutoff: latest?.time ?? null,
      lastError: null,
    })
  }
}

function clearMarkerPaintReadback(): void {
  if (!host) return
  drawnMarkers.value = []
  renderedMarkerById.clear()
  if (hoverContext.value) {
    hoverContext.value = null
    emit('crosshair-change', null)
  }
  for (const id of MARKER_FACT_LAYERS) {
    const layerId = `marker-facts:${id}`
    if (host.inspectLayer(layerId)?.status !== 'ready') continue
    host.layer(layerId, id, 'main').updateDiagnostics({
      status: 'renderer_failure', lastError: 'CHART_RENDERER_PAINT_FAILED',
      frequency: null, sourceIdentity: null, formulaVersion: null, dataCutoff: null,
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

function syncPaneLayout() {
  if (!container.value || !chart) return
  const layout = detailSession ? detailChartPaneLayout(container.value.clientHeight, 32) : null
  const panes = chart.panes()
  panes[0]?.setStretchFactor(layout?.mainHeight ?? 6)
  panes[1]?.setStretchFactor(layout?.auxiliaryHeight ?? 2)
}

function resize() {
  if (!container.value || !chart) return
  if (detailSession) syncPaneLayout()
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
