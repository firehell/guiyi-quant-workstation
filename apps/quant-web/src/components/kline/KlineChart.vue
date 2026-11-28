<script setup lang="ts">
import { createWorkstationPaneRenderer } from '../market/detail/newow/workstationPaneRenderer'
import type { ArchivePane, WorkstationStyles } from '@/utils/workstationChartPanes'
import { SubingVolumeTierPrimitive } from './subingVolumeTierPrimitive'
import { CHART_PROFILES, DISPLAY_CATALOG, mountChartHost, type ChartHost, type ChartLayer, type ChartProfileId } from '@guiyi/quant-chart'
import { volumePresentation, validVolume, VOLUME_DISPLAY_VERSION, VOLUME_SCALE_OPTIONS, type DisplayVolumeBar } from '@guiyi/quant-chart/volume'
import { readNewowChartDisplayTheme } from '@/utils/newowChartDisplayTheme'

import { formatDisplayNumber } from '@/utils/marketDisplay'
import { DynamicRangePrimitive } from '@/components/kline/dynamicRangePrimitive'
import { DYNAMIC_RANGE_VERSION, matchesRangeBar, pointKey, type DynamicRangeDisplay, type VerifiedRangePoint } from '@/utils/dynamicRange'
import { NewowPublicPatternPrimitive } from '@/components/market/detail/newow/newowPublicPatternPrimitive'
import type { PatternGeometry } from '@/utils/newowPatternDisplay'
import { inject, nextTick, onMounted, onUnmounted, ref, shallowRef, watch } from 'vue'
import { DETAIL_CHART_SESSION, detailChartViewport, placeDetailChartViewport, detailChartVolumeBars, detailChartTime, detailChartPaneLayout, detailChartIndex, detailChartLength, detailChartTimeAt, type DetailChartSession } from '@/utils/detailChartSession'
import {
  ColorType,
  PriceScaleMode,
  createChart,
  type IChartApi,
  type ISeriesMarkersPluginApi,
  type ISeriesApi,
  type LogicalRange,
  type MouseEventParams,
  type TickMarkType,
  type Time,
  type UTCTimestamp,
  type LineSeriesOptions,
  type DeepPartial,
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
import { marketStudyLayerStatus, type ChartStudyId, type EmaIndicatorId, type MarketChartStudyDisplay, type MarketChartStudyIssue, type MarketChartStudyPoint, type MarketChartStudyPreview } from '@/utils/marketChartStudies'
import { HTDY_WEB_OBSERVATION_METADATA } from '@/utils/mainIndicators'
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
  workstationPanes?: ArchivePane[]
  workstationStyles?: WorkstationStyles
  logPrice?: boolean
  dynamicRange?: DynamicRangeDisplay | null
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
  studyCompleted?: MarketChartStudyDisplay | null
  studyPreview?: MarketChartStudyPreview | null
  studyTailIssue?: MarketChartStudyIssue | null
  talibMacd?: boolean
  allowGenericMacd?: boolean
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
  'toggle-talib-macd': []
}>()

const paneRenderer = createWorkstationPaneRenderer()
const workstationHeaders = ref<ReturnType<typeof paneRenderer.headers>>([])
const enlargedAuxiliary = ref<ArchivePane['id'] | null>(null)
function toggleAuxiliarySize(component: ArchivePane['id']) {
  enlargedAuxiliary.value = enlargedAuxiliary.value === component ? null : component
  syncPaneLayout()
  requestAnimationFrame(syncMacdLabelTop)
}
function renderWorkstationPanes() {
  if (!host || !props.workstationPanes) return
  const panes = sharedPriceWritten ? props.workstationPanes
    : props.workstationPanes.map(pane => ({ ...pane, chart: null, auxiliary: null, message: '主图行情不可用' }))
  paneRenderer.render(host, panes, sharedPriceWritten ? renderedBars.map(chartTime) : [])
  syncPaneLayout()
  syncMacdLabelTop()
}
watch(() => props.workstationPanes, () => {
  if (!host || !chart) return
  const range = chart.timeScale().getVisibleLogicalRange()
  renderWorkstationPanes()
  renderStudyData(resolveChartTheme(container.value ?? document.documentElement))
  if (range) chart.timeScale().setVisibleLogicalRange(range)
  detailSession?.restoreInspectionCursor()
}, { flush: 'post' })

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
const releaseInspector = detailSession?.attachInspector(() => (host?.diagnostics() ?? []).filter(d => d.indicatorId !== 'auxiliary_axis'))
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
const liveStudyPointCount = ref(0)
const previewStudyPointCount = ref(0)
const talibMacdPointCount = ref(0)
let referenceStudy: ReturnType<typeof referenceIndicatorOverlay> = null
let talibMacdLayers: { dif: ISeriesApi<'Line'>; dea: ISeriesApi<'Line'>; histogram: ISeriesApi<'Histogram'> } | null = null
const studyPreviewSeries = new Map<ChartStudyId, Map<string, ISeriesApi<'Line'>>>()
type NativeStudyPoint = (SingleValueData<Time> & { color?: string }) | WhitespaceData<Time>
const plottedStudyData = new WeakMap<object, NativeStudyPoint[]>()
const publicPatternPrimitive = new NewowPublicPatternPrimitive(point => chartTime({ time: point.barEnd, trading_day: point.tradingDay } as BarData))
watch(() => props.patternGeometry, () => {
  renderPublicPattern()
  detailSession?.restoreInspectionCursor()
})
const rangeDetectorPrimitive = new RangeDetectorPrimitive()
let htdyLines: Record<'zk1' | 'zd1' | 'zd2', ISeriesApi<'Line'>> | null = null
const dynamicRangePrimitive = new DynamicRangePrimitive()
let drawnRangePoints: readonly VerifiedRangePoint[] = []
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
const savedReferenceSeries = new Map<string, ISeriesApi<'Line'> | null>()
let renderedMarkerById = new Map<string, KlineMarker>()
const drawnMarkers = shallowRef<KlineMarker[]>([])
let viewportStabilityFrame: number | null = null
let viewportStabilityTarget: ChartViewportRange | null = null
let viewportStabilityAutomatic = false
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
  if (props.workstationPanes) chart.priceScale('right', 0).applyOptions({ mode: props.logPrice ? PriceScaleMode.Logarithmic : PriceScaleMode.Normal })
  if (!props.workstationPanes) {
    chart.addPane()
    host.addAuxiliary('default')
  }
  syncPaneLayout()
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
  releaseInspector?.()
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
watch([() => props.studyDisplay, () => props.studyCompleted, () => props.studyIssue, () => props.studyTailIssue], () => {
  renderStudyData(resolveChartTheme(container.value ?? document.documentElement))
  detailSession?.restoreInspectionCursor()
})
watch(() => props.studyPreview, () => renderStudyPreview(resolveChartTheme(container.value ?? document.documentElement)))
watch(() => props.talibMacd, () => {
  const theme = resolveChartTheme(container.value ?? document.documentElement)
  if (!props.talibMacd && !props.workstationPanes) renderThsMacd(theme)
  renderStudyData(theme)
  renderStudyPreview(theme)
  if (props.talibMacd) removeThsMacd()
})
watch(() => props.dynamicRange, () => { renderDynamicRange(); detailSession?.restoreInspectionCursor() })
watch(() => props.savedReferenceLines, renderSavedReferenceLines)
watch(() => props.workstationStyles, () => { renderSavedReferenceLines(); renderStudyData(resolveChartTheme(container.value ?? document.documentElement)) })
watch(() => props.logPrice, log => chart?.priceScale('right', 0).applyOptions({ mode: log ? PriceScaleMode.Logarithmic : PriceScaleMode.Normal }))
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
    sourceBarSha256: bar.sourceBarSha256, marketSource: bar.marketSource, calculationSegmentId: bar.calculationSegmentId,
    trading_day: bar.trading_day, confirmed: bar.confirmed, volume: bar.volume,
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
  const volumeFact = {
    ...barProvenance(latestVolume),
    ...(scoringVersion ? { sourceIdentity: null } : {}),
    formulaVersion: scoringVersion, cacheState: null, physicalContract: latestVolume?.physicalContract,
  }
  volumeLayer?.updateDiagnostics({
    ...volumeFact, status: latestVolume ? 'ready' : props.loading ? 'loading' : 'missing_input', lastError: null,
  })
  detailSession?.recordBaseLayer('volume', volumeFact)
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
  placeDetailChartViewport(chart, targetRange)
  beginViewportStabilityCheck(targetRange, detailSession !== null && mappedSessionViewport === null)
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

function beginViewportStabilityCheck(target: ChartViewportRange | null, automatic = false): void {
  if (viewportStabilityFrame !== null) cancelAnimationFrame(viewportStabilityFrame)
  viewportStabilityTarget = target
  viewportStabilityAutomatic = automatic
  viewportStableFrames = 0
  viewportStabilityAttempts = 0
  chartViewportReady.value = false
  if (target) viewportStabilityFrame = requestAnimationFrame(checkViewportStability)
}

function canStabilizeViewport(chart: IChartApi): boolean {
  if (!viewportStabilityTarget) return false
  if (viewportStabilityAutomatic && detailChartViewport(chart) !== null) {
    viewportStabilityTarget = null
    chartViewportReady.value = true
    return false
  }
  return true
}

function checkViewportStability(): void {
  viewportStabilityFrame = null
  if (!chart || !canStabilizeViewport(chart) || !viewportStabilityTarget) return
  viewportStabilityAttempts += 1
  const actual = chart.timeScale().getVisibleLogicalRange()
  if (sameLogicalRange(actual, viewportStabilityTarget)) viewportStableFrames += 1
  else {
    viewportStableFrames = 0
    placeDetailChartViewport(chart, viewportStabilityTarget)
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
  const firstBar = renderedBars.at(0)
  const anchor = firstBar ? chartTime(firstBar) : null
  const previousIndex = detailSession && anchor !== null ? detailChartIndex(chart, anchor, 0) : 0
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
    const offset = anchor === null ? prependedCount : detailChartIndex(chart, anchor, prependedCount) - previousIndex
    const owned = detailChartViewport(chart)
    const shift = (range: ChartViewportRange | null) => range && { from: range.from + offset, to: range.to + offset }
    if (viewportStabilityTarget && canStabilizeViewport(chart)) {
      viewportStabilityTarget = owned ?? shift(viewportStabilityTarget)
    }
    const mapped = owned ?? shift(visibleRange)
    if (mapped) placeDetailChartViewport(chart, mapped)
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
  if (nextContext && props.talibMacd) {
    const values = studyFact('macd', nextContext.time)?.values
    nextContext.macd = { dif: values?.dif ?? null, dea: values?.dea ?? null, histogram: values?.histogram ?? null }
  }
  if (nextContext && props.dynamicRange) {
    const point=drawnRangePoints.find(p => matchesRangeBar(p, nextContext.bar))
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
    let series = savedReferenceSeries.get(line.id)
    const written = host.renderLayer(`saved-reference:${line.id}`, 'saved_reference', 'main', 'line', layer => {
      series ??= layer.line({
        color: line.color, title: line.label, lineWidth: 1, lastValueVisible: false, priceLineVisible: false,
      })
      const style = props.workstationStyles?.[line.id.split(':')[0] as keyof WorkstationStyles]
      series.applyOptions({ color: line.color, lineWidth: 1, ...style })
      series.setData(chartValues(line.points, barsByTime))
      const cutoff = lastMatching(line.points, point => barsByTime.has(point.time) && Number.isFinite(point.value))?.time ?? null
      layer.updateDiagnostics({
        status: cutoff ? 'ready' : 'missing_input', frequency: props.period,
        sourceIdentity: cutoff ? line.sourceRevision : null, formulaVersion: cutoff ? line.formulaVersion : null, dataCutoff: cutoff,
      })
    })
    savedReferenceSeries.set(line.id, written ? series ?? null : null)
  }
}

function renderAllSeries(): void {
  if (!host || !candles || !volume || !chart) return
  const price = host.layer('price', 'price', 'main')
  const wasWritten = sharedPriceWritten
  const retained = !renderedBars.length ? detailSession?.readBaseLayer('candles') : undefined
  try {
    candles.setData(barValues(renderedBars))
    sharedPriceWritten = true
    const confirmed = lastMatching(renderedBars, bar => bar.confirmed !== false)
    const priceFact = retained ?? { ...barProvenance(confirmed), formulaVersion: null, cacheState: null, physicalContract: confirmed?.physicalContract }
    price.updateDiagnostics({
      ...priceFact, status: priceFact.dataCutoff ? 'ready' : props.loading ? 'loading' : 'missing_input', lastError: null,
    })
    detailSession?.recordBaseLayer('candles', priceFact)
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
  const retainedPrice = sharedPriceWritten ? retained : undefined
  if (container.value) {
    container.value.dataset.klineEnd = last?.time ?? retainedPrice?.dataCutoff ?? ''
    container.value.dataset.klineCount = String(sharedPriceWritten ? renderedBars.length || detailSession?.length() || 0 : 0)
    container.value.dataset.klineClose = last ? String(last.close) : ''
    container.value.dataset.klineContract = last?.physicalContract ?? retainedPrice?.physicalContract ?? ''
    container.value.dataset.klineFrequency = props.period
  }
  renderVolumeBars()
  renderWorkstationPanes()
  renderSavedReferenceLines()
  renderDerivedSeries()
}

function renderDynamicRange(): void {
  if (!host || !candles) return
  const display = props.dynamicRange
  if (!display || !sharedPriceWritten) {
    if (host.inspectLayer('dynamic-range')) host.removeLayer('dynamic-range')
    publishDynamicRangePoints([])
    return
  }
  const anchor = candles
  const bars = new Map(renderedBars.map(b => [pointKey(b.physicalContract ?? '',b.time),b]))
  const points = display.points.flatMap(point => {
    const bar = bars.get(pointKey(point.contract, point.time))
    return bar && matchesRangeBar(point, bar) ? [point.time === bar.time ? point : { ...point, time: bar.time }] : []
  })
  const written = host.renderLayer('dynamic-range', 'dynamic_range', 'main', 'primitive', layer => {
    if (!layer.hasResource(dynamicRangePrimitive)) layer.primitive(anchor, dynamicRangePrimitive, () => publishDynamicRangePoints([]))
    dynamicRangePrimitive.setData(points, ribbonTime)
    const last = points.at(-1)
    layer.updateDiagnostics({
      status: display.issue?.status ?? (display.loading ? 'loading' : !last ? 'missing_input'
        : last.reason === 'WARMUP' ? 'warming' : last.regime === 'UNKNOWN' ? 'invalid_source' : 'ready'),
      frequency: props.period, formulaVersion: last ? DYNAMIC_RANGE_VERSION : null,
      sourceIdentity: last?.prefixSourceHash ?? null, dataCutoff: last?.time ?? null,
      lastError: display.issue?.code ?? last?.reason ?? null,
    })
  })
  publishDynamicRangePoints(written ? points : [])
}

function publishDynamicRangePoints(points: readonly VerifiedRangePoint[]) {
  drawnRangePoints = points
  const current = hoverContext.value
  if (!current) return
  const enabled = Boolean(props.dynamicRange)
  const point = enabled ? points.find(item => matchesRangeBar(item, current.bar)) ?? null : null
  if (point === current.dynamicRange && enabled === current.dynamicRangeEnabled) return
  const next = { ...current, dynamicRange: point, dynamicRangeEnabled: enabled }
  hoverContext.value = next
  emit('crosshair-change', next)
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
    hideThsMacd: !!props.workstationPanes || props.talibMacd,
    rangeDetector: { enabled: rangeEnabled && !cachedRange, sourceIdentity: props.rangeDetectorSourceIdentity, anchorTime: props.rangeDetectorAnchorTime },
  })
  if (cachedRange) derivedData.rangeDetector = cachedRange
  if (rangeEnabled && derivedData.rangeDetector) rangeCache = { bars: renderedBars, key: rangeKey, result: derivedData.rangeDetector }
  else rangeCache = null
  rangeCalculationMs.value = performance.now() - calculationStarted
  rangeCount.value = derivedData.rangeDetector?.ranges.length ?? 0
  publishRangeResult()
  host.removeLayer('trade-reference')
  const levels = sharedPriceWritten ? referencePriceLevelSegments(renderedBars, props.referenceIndicators ?? []) : []
  referenceTargetSegments.value = levels.filter(level => level.kind === 'target').length
  referenceStopSegments.value = levels.filter(level => level.kind === 'stop').length
  for (const level of levels) {
    const line = host.layer('trade-reference', 'trade_reference', 'main').line({ color: level.kind === 'target' ? '#b28a36' : '#cc6262', lineWidth: 1, lineStyle: 2, lastValueVisible: false, priceLineVisible: false, pointMarkersVisible: true, pointMarkersRadius: 2 })
    line.setData(chartValues(level.points))
  }
  const theme = resolveChartTheme(container.value ?? document.documentElement)

  referenceStudy = referenceIndicatorOverlay(renderedBars, props.referenceIndicators)
  renderStudyData(theme)
  renderStudyPreview(theme)
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

function studyPoints(id: ChartStudyId, output: string) {
  return chartStudySeries(renderedBars, props.studyDisplay?.points[id], output, props.studyCompleted?.points[id])
}

function studyFact(id: ChartStudyId, time: string) {
  return props.studyCompleted?.points[id]?.[time] ?? props.studyDisplay?.points[id]?.[time]
}

function studyDiagnostics(id: ChartStudyId, latest: KlineValuePoint | undefined) {
  const time = latest?.time ?? null
  const usingLive = !!time && props.studyCompleted?.points[id]?.[time] !== undefined
  const display = usingLive ? props.studyCompleted : props.studyDisplay
  const fact = time ? studyFact(id, time) : undefined
  const proof = time ? display?.segmentsByTime[time] : undefined
  return {
    frequency: props.period, status: fact ? marketStudyLayerStatus(fact) : props.studyIssue?.status ?? marketStudyLayerStatus(),
    formulaVersion: display?.features[id]?.formulaVersion ?? null,
    sourceIdentity: display?.features[id] ? display.sourceRevision : null,
    dataCutoff: time,
    sourceStage: proof ? usingLive ? 'completed_live' as const : 'canonical' as const : null,
    calculationAnchor: proof?.calculationAnchor ?? null,
    lastError: props.studyIssue?.reason ?? fact?.diagnostic ?? props.studyTailIssue?.reason ?? null,
  }
}

function sameStudyPoint(left: NativeStudyPoint, right: NativeStudyPoint) {
  if (!sameChartTime(left.time, right.time)) return false
  if ('value' in left && 'value' in right) return left.value === right.value && left.color === right.color
  return !('value' in left) && !('value' in right)
}

/** Keep the native series and use the chart API's tail update where its prefix still matches. */
function writeStudyPoints(series: ISeriesApi<'Line'> | ISeriesApi<'Histogram'>, data: NativeStudyPoint[]) {
  const previous = plottedStudyData.get(series)
  if (previous?.length && previous.length <= data.length
    && previous.slice(0, -1).every((point, index) => sameStudyPoint(point, data[index]!))
    && sameChartTime(previous.at(-1)!.time, data[previous.length - 1]!.time)) {
    const last = previous.length - 1
    const offset = sameStudyPoint(previous[last]!, data[last]!) ? last + 1 : last
    for (let index = offset; index < data.length; index++) series.update(data[index]!)
  } else {
    series.setData(data)
  }
  plottedStudyData.set(series, data)
}

function renderStudyData(theme: ReturnType<typeof resolveChartTheme>) {
  if (!host) return
  const nativeBars = new Map(renderedBars.map(bar => [bar.time, bar]))
  const emaColors = { ema_10: theme.ema10, ema_21: theme.ema21, ema_60: theme.ema60 }
  let liveCount = 0
  for (const indicator of EMA_INDICATORS) {
    if (!props.visibleMainIndicators.includes(indicator)) {
      host.removeLayer(indicator)
      delete emaLines[indicator]
      continue
    }
    const referenceSeries = indicator === 'ema_21' ? referenceStudy?.ema21 : undefined
    const points = referenceSeries ?? studyPoints(indicator, 'value')
    derivedData.ema[indicator] = points
    derivedData.emaFacts[indicator] = referenceSeries ? undefined : {
      ...props.studyDisplay?.points[indicator], ...props.studyCompleted?.points[indicator],
    }
    const facts = derivedData.emaFacts[indicator]
    const last = latestStudyPoint(points, facts)
    const written = host.renderLayer(indicator, indicator, 'main', 'line', layer => {
      const series = emaLines[indicator] ??= layer.line({ color: emaColors[indicator], lineWidth: indicator === 'ema_21' ? 2 : 1, lastValueVisible: false })
      series.applyOptions({ color: emaColors[indicator], lineWidth: indicator === 'ema_21' ? 2 : 1, ...props.workstationStyles?.[indicator] })
      writeStudyPoints(series, chartValues(points, nativeBars))
      layer.updateDiagnostics(referenceSeries ? { frequency: props.period,
        dataCutoff: last?.time ?? null, status: last?.value != null ? 'ready' : 'missing_input', lastError: null,
      } : studyDiagnostics(indicator, last))
    })
    if (!written) delete emaLines[indicator]
    else if (!referenceSeries) liveCount += readyCompletedCount(indicator)
  }
  if (renderBoll(theme, nativeBars)) liveCount += readyCompletedCount('boll')
  if (renderTalibMacd(theme, nativeBars)) liveCount += readyCompletedCount('macd')
  if (props.workstationPanes) syncMacdLabelTop()
  liveStudyPointCount.value = liveCount
}

function readyCompletedCount(id: ChartStudyId) {
  return Object.values(props.studyCompleted?.points[id] ?? {}).filter(point => point.status === 'READY').length
}

function renderBoll(theme: ReturnType<typeof resolveChartTheme>, nativeBars: ReadonlyMap<string, BarData>): boolean {
  if (!host) return false
  if (!props.visibleMainIndicators.includes('boll')) {
    host.removeLayer('boll')
    bollLines = null
    bollPointCount.value = 0
    return false
  }
  const written = host.renderLayer('boll', 'boll', 'main', 'band', layer => {
    const boundary = { color: theme.ema60, lineWidth: 1, lineStyle: 2, lastValueVisible: false, priceLineVisible: false, ...props.workstationStyles?.boll_edge } as const
    const center = { ...boundary, color: theme.ema10, lineWidth: 1, lineStyle: 0, ...props.workstationStyles?.boll_mid } as const
    bollLines ??= { ...layer.band(boundary, boundary), middle: layer.line(center) }
    bollLines.upper.applyOptions(boundary)
    bollLines.middle.applyOptions(center)
    bollLines.lower.applyOptions(boundary)
    const middle = studyPoints('boll', 'middle')
    writeStudyPoints(bollLines.upper, chartValues(studyPoints('boll', 'upper'), nativeBars))
    writeStudyPoints(bollLines.middle, chartValues(middle, nativeBars))
    writeStudyPoints(bollLines.lower, chartValues(studyPoints('boll', 'lower'), nativeBars))
    bollPointCount.value = middle.filter(point => point.value !== null).length
    layer.updateDiagnostics(studyDiagnostics('boll', middle.at(-1)))
  })
  if (!written) {
    bollLines = null
    bollPointCount.value = 0
  }
  return written
}

const AUXILIARY_PANE = { auxiliary: 'default' } as const

function renderTalibMacd(theme: ReturnType<typeof resolveChartTheme>, nativeBars: ReadonlyMap<string, BarData>): boolean {
  if (!host) return false
  if (!props.talibMacd) {
    host.removeLayer('talib-macd')
    talibMacdLayers = null
    talibMacdPointCount.value = 0
    return false
  }
  const pane = props.workstationPanes ? { auxiliary: 'macd' } : AUXILIARY_PANE
  if (props.workstationPanes && !host.hasLayer('workstation-axis:macd')) return false
  const written = host.renderLayer('talib-macd', 'macd', pane, 'histogram', layer => {
    if (!talibMacdLayers) {
      talibMacdLayers = {
        histogram: layer.histogram({ base: 0, lastValueVisible: false }),
        dif: layer.line({ color: '#00bfcf', lineWidth: 1, lastValueVisible: false }),
        dea: layer.line({ color: '#d4b000', lineWidth: 1, lastValueVisible: false }),
      }
      layer.priceLevel(talibMacdLayers.dif, { price: 0, color: '#888888', lineWidth: 1, lineStyle: 0, axisLabelVisible: false, title: '' })
      chart?.priceScale('right', host!.paneIndex(pane)).applyOptions({ scaleMargins: { top: 0.15, bottom: 0.1 } })
      syncPaneLayout()
    }
    talibMacdLayers.dif.applyOptions({ color: '#00bfcf', lineWidth: 1, ...props.workstationStyles?.macd_dif })
    talibMacdLayers.dea.applyOptions({ color: '#d4b000', lineWidth: 1, ...props.workstationStyles?.macd_dea })
    const histogram = studyPoints('macd', 'histogram')
    writeStudyPoints(talibMacdLayers.histogram, chartValues(histogram, nativeBars).map(point => 'value' in point
      ? { ...point, color: point.value >= 0 ? theme.volumeUp : theme.volumeDown } : point))
    writeStudyPoints(talibMacdLayers.dif, chartValues(studyPoints('macd', 'dif'), nativeBars))
    writeStudyPoints(talibMacdLayers.dea, chartValues(studyPoints('macd', 'dea'), nativeBars))
    talibMacdPointCount.value = histogram.filter(point => point.value !== null).length
    layer.updateDiagnostics(studyDiagnostics('macd', histogram.at(-1)))
  })
  if (!written) {
    talibMacdLayers = null
    talibMacdPointCount.value = 0
  }
  return written
}

function renderStudyPreview(theme: ReturnType<typeof resolveChartTheme>) {
  if (!host) return
  const preview = props.studyPreview
  const latestBar = renderedBars.at(-1)
  let count = 0
  const colors = {
    ema_10: { value: theme.ema10 }, ema_21: { value: theme.ema21 }, ema_60: { value: theme.ema60 },
    boll: { upper: theme.ema60, middle: theme.ema10, lower: theme.ema60 },
    macd: { dif: '#00bfcf', dea: '#d4b000', histogram: theme.volumeUp },
  }
  for (const id of Object.keys(colors) as ChartStudyId[]) {
    const layerId = `${id}-active-preview`
    const selected = id === 'macd' ? props.talibMacd : props.visibleMainIndicators.includes(id)
    const point = preview?.data.points[id]?.[preview.bar.time]
    if (!selected || !preview || !point
      || (id === 'ema_21' && referenceStudy)
      || (latestBar && compareChartTimes(chartTime(preview.bar), chartTime(latestBar)) <= 0)) {
      host.removeLayer(layerId)
      studyPreviewSeries.delete(id)
      continue
    }
    const written = host.renderLayer(layerId, id, id === 'macd' ? AUXILIARY_PANE : 'main', 'line', layer => {
      const proof = preview.data.segmentsByTime[preview.bar.time]
      const preceding = latestBar && studyFact(id, latestBar.time)
      const precedingProof = latestBar && (props.studyCompleted?.segmentsByTime[latestBar.time] ?? props.studyDisplay?.segmentsByTime[latestBar.time])
      const bridges = latestBar && preceding?.values && proof && precedingProof
        && proof.segmentId === precedingProof.segmentId && proof.physicalContract === precedingProof.physicalContract
      const outputs = studyPreviewSeries.get(id) ?? new Map<string, ISeriesApi<'Line'>>()
      studyPreviewSeries.set(id, outputs)
      for (const [output, color] of Object.entries(colors[id])) {
        const options: DeepPartial<LineSeriesOptions> = {
          color, lineWidth: 1, lineStyle: 2, lastValueVisible: false, priceLineVisible: false,
          pointMarkersVisible: true, pointMarkersRadius: 2, crosshairMarkerVisible: false,
        }
        let line = outputs.get(output)
        if (!line && point.values?.[output] !== undefined) {
          line = layer.line(options)
          outputs.set(output, line)
        }
        if (!line) continue
        line.applyOptions(options)
        const value = point.values?.[output]
        const previousValue = bridges ? preceding.values?.[output] : undefined
        line.setData(value === undefined ? [] : [
          ...(previousValue === undefined || !latestBar ? [] : [{ time: chartTime(latestBar), value: previousValue }]),
          { time: chartTime(preview.bar), value },
        ])
      }
      layer.updateDiagnostics({
        sourceStage: 'active_preview', calculationAnchor: proof?.calculationAnchor ?? null,
        frequency: props.period,
        formulaVersion: preview.data.features[id]?.formulaVersion ?? null,
        sourceIdentity: preview.generation, dataCutoff: preview.bar.time,
        status: marketStudyLayerStatus(point), lastError: point.diagnostic,
      })
    })
    if (!written) studyPreviewSeries.delete(id)
    else if (point.status === 'READY') count++
  }
  previewStudyPointCount.value = count
}

function removeThsMacd() {
  host?.removeLayer('macd-crosses')
  host?.removeLayer('macd')
  macdHistogram = null
  macdDif = null
  macdDea = null
  macdCrossMarkers = null
  macdPointCount.value = 0
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
  if (props.talibMacd || props.workstationPanes) removeThsMacd()
  else renderThsMacd(theme)
  if (props.visibleMainIndicators.includes('htdy')) {
    const written = host.renderLayer('htdy', 'htdy', 'main', 'line', layer => {
      htdyLines ??= {
        zk1: layer.line({ color: theme.htdyZk1, lineWidth: 2, lineStyle: 0, lastValueVisible: false }),
        zd1: layer.line({ color: theme.htdyZd1, lineWidth: 2, lineStyle: 2, lastValueVisible: false }),
        zd2: layer.line({ color: theme.htdyZd2, lineWidth: 2, lineStyle: 0, lastValueVisible: false }),
      }
      const barsByTime = new Map(renderedBars.map(bar => [bar.time, bar]))
      let cutoff: string | null = null
      for (const key of ['zk1', 'zd1', 'zd2'] as const) {
        const points = derivedData.htdy?.[key] ?? []
        htdyLines[key].setData(chartValues(points, barsByTime))
        const last = lastMatching(points, point => Number.isFinite(point.value) && barsByTime.has(point.time))
        if (last && (cutoff === null || Date.parse(last.time) > Date.parse(cutoff))) cutoff = last.time
      }
      layer.updateDiagnostics({
        frequency: props.period, formulaVersion: HTDY_WEB_OBSERVATION_METADATA.indicator_version, sourceIdentity: null, dataCutoff: cutoff,
        status: cutoff ? 'ready' : props.loading ? 'loading' : 'missing_input',
      })
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
  const theme = resolveChartTheme(container.value ?? document.documentElement)
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
  if (host && props.workstationPanes) workstationHeaders.value = paneRenderer.headers(host, props.workstationPanes)
  const panes = chart?.panes()
  if (!panes || panes.length < 2) return
  macdLabelTop.value = panes[0].getHeight()
}

function syncPaneLayout() {
  if (!container.value || !chart) return
  if (props.workstationPanes && host) {
    const panes = chart.panes()
    if (!props.workstationPanes.some(p => p.id === enlargedAuxiliary.value)) enlargedAuxiliary.value = null
    const height = props.workstationPanes.reduce((total, pane) => total + pane.height, 0)
    const available = container.value.clientHeight - 30
    panes[0]?.setStretchFactor(enlargedAuxiliary.value ? 88 : Math.max(220, available - height))
    for (const pane of props.workstationPanes) {
      const size = enlargedAuxiliary.value ? (pane.id === enlargedAuxiliary.value ? Math.max(200, available - 88 - 48 * (props.workstationPanes.length - 1)) : 48) : pane.height
      if (host.hasLayer('workstation-axis:' + pane.id)) panes[host.paneIndex({ auxiliary: pane.id })]?.setStretchFactor(size)
    }
    return
  }
  const layout = detailSession ? detailChartPaneLayout(container.value.clientHeight, 32) : null
  const panes = chart.panes()
  panes[0]?.setStretchFactor(layout?.mainHeight ?? 6)
  panes[1]?.setStretchFactor(layout?.auxiliaryHeight ?? 2)
}

function resize() {
  if (!container.value || !chart) return
  if (detailSession) syncPaneLayout()
  chart.resize(container.value.clientWidth, container.value.clientHeight)
  if (viewportStabilityTarget && canStabilizeViewport(chart)) {
    viewportStableFrames = 0
    placeDetailChartViewport(chart, viewportStabilityTarget)
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
    :style="workstationPanes ? { height: `calc(clamp(360px, 55vh, 660px) + ${workstationPanes.reduce((n, p) => n + p.height, 0)}px)`, minHeight: 0 } : undefined"
    :data-boll-point-count="bollPointCount"
    :data-live-study-point-count="liveStudyPointCount"
    :data-preview-study-point-count="previewStudyPointCount"
    :data-talib-macd-point-count="talibMacdPointCount"
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
      :show-macd="!workstationPanes || talibMacd"
    />
    <div v-for="pane in workstationHeaders" :key="pane.id" class="secondary-panel-label" :style="{ top: (pane.top + 3) + 'px' }" :data-workstation-pane="pane.id">
      <button class="pane-size" type="button" :aria-label="(enlargedAuxiliary === pane.component ? '还原' : '放大') + pane.label" :aria-pressed="enlargedAuxiliary === pane.component" @click="toggleAuxiliarySize(pane.component)">{{ enlargedAuxiliary === pane.component ? '还原' : '放大' }}</button>
      {{ pane.label }}<span v-if="pane.retrospective"> · 历史回看，会重绘</span><span v-if="pane.note"> · {{ pane.note }}</span>
      <span v-if="hoverContext && pane.component !== 'macd'" :data-newow-hover="pane.component">
        · {{ hoverContext.bar.trading_day }} · {{ hoverContext.bar.physicalContract }} · {{ paneRenderer.readout(pane.component, hoverContext.bar) }}
      </span>
    </div>
    <component v-if="!workstationPanes"
      :is="allowGenericMacd ? 'button' : 'div'"
      class="secondary-panel-label"
      :class="{ 'secondary-panel-label--select': allowGenericMacd }"
      data-testid="secondary-panel-label"
      :type="allowGenericMacd ? 'button' : undefined"
      :aria-pressed="allowGenericMacd ? talibMacd : undefined"
      :aria-label="allowGenericMacd ? 'TA-Lib MACD' : undefined"
      :title="allowGenericMacd ? (talibMacd ? '切回同花顺 MACD' : '切换至 TA-Lib MACD') : undefined"
      :style="{ top: macdLabelTop === null ? '80%' : `${macdLabelTop + 5}px` }"
      @click="allowGenericMacd && emit('toggle-talib-macd')"
    >
      {{ talibMacd ? 'TA-Lib MACD' : 'MACD · MA21 金死叉' }}
    </component>
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
.pane-size { pointer-events: auto; cursor: pointer; margin-right: 4px; color: inherit; background: transparent; border: 1px solid var(--gy-border); border-radius: 3px; font: inherit; }
.secondary-panel-label.secondary-panel-label--select { border: 0; cursor: pointer; pointer-events: auto; text-align: left; font-family: inherit; }
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
