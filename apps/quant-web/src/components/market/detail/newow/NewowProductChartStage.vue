<script setup lang="ts">
import ChartReferenceToolbar from '../ChartReferenceToolbar.vue'
import NewowMainRiseProcessLabels from './NewowMainRiseProcessLabels.vue'
import {readNewowChartDisplayTheme} from '@/utils/newowChartDisplayTheme'
import {layoutMainRiseProcessLabels} from '@/utils/newowProcessHintDisplay'
import NewowBreakoutOverlay from './NewowBreakoutOverlay.vue'
import {breakoutBand,type BreakoutPoint,type NewowBreakoutEvent} from '@/utils/newowBreakoutEvents'
import NewowDisplayOverlay from './NewowDisplayOverlay.vue'
import {displayIndexVisible,type DisplayPoint,type NewowDisplayEvent} from '@/utils/newowDisplayEvents'
import { cautionDisplayTitle, cautionStateLabel, type CautionState } from '@/utils/newowCautionDisplay.ts'
import ReferenceCalloutLabels from '@/components/kline/ReferenceCalloutLabels.vue'
import { DETAIL_CHART_SESSION, detailChartTime, detailChartVolumeBars, detailChartViewport, detailChartIndex, detailChartLength, type DetailChartSession } from '@/utils/detailChartSession'
import { createPriceSeriesWriter } from '@/utils/priceSeriesWriter'
import { newowProcessHintDisplay } from '@/utils/newowProcessHintDisplay'
import NewowChartSettings, { type NewowChartLayers } from './NewowChartSettings.vue'
import { NewowPriceAnnotationPrimitive, type NewowPriceAnnotation } from './newowPriceAnnotationPrimitive.ts'
import { newowFourStepMarks } from '@/utils/newowFourStepMarks'
import { newowExtrema, newowNineTurn } from '@/utils/newowChartAnnotations'
import { readChartAnnotationPreferences, readVisualOverlayPreferences, saveVisualOverlayPreferences, visualDonchian, retainBuildStop, retainedStopPrice, type RetainedBuildStop } from '@/utils/newowVisualOverlays'
import { newowReferencePrice, newowSimpleDualLabel, NEWOW_CHART_PRICE_FORMAT } from '@/utils/newowPagePresentation'
import { CHART_PROFILES, DISPLAY_CATALOG, mountChartHost, type ChartHost, type ChartLayer, type LayerStatus } from '@guiyi/quant-chart'
import { newowAuxiliaryLayerStatus, newowPaneId, type NewowAdditionalPane, type NewowAuxiliaryPaneComponent } from '@/utils/newowAdditionalPanes'
import { volumePresentation, validVolume, VOLUME_SCALE_OPTIONS, type DisplayVolumeBar } from '@guiyi/quant-chart/volume'
import { newowOscillationBreakout } from '@/utils/newowBreakoutDisplay'
import { newowChartReadout } from '@/utils/newowChartReadout'
import { newowActionReturnDisplay, newowActionStatus } from '@/utils/newowActionReturnDisplay'
import type { KlineReferenceCallout } from '@/types/referenceCallout'
import type { BarData } from '@/types/market'
import { projectNewowAuxiliaryReadiness } from '@/utils/newowDetailPresentation'
import { computed, shallowRef, inject, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  ColorType,
  CrosshairMode,
  createChart,
  createSeriesMarkers,
  type WhitespaceData,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type ISeriesPrimitive,
  type LineData,
  type CandlestickData,
  type HistogramData,
  type LogicalRange,
  type MouseEventParams,
  type SeriesMarker,
  type Time,
} from 'lightweight-charts'

import { NewowProductBandPrimitive } from '@/components/market/detail/newow/newowProductBandPrimitive'
import { NewowPublicPatternPrimitive } from '@/components/market/detail/newow/newowPublicPatternPrimitive'
import { buildNewowPatternGeometry, type PatternChoice } from '@/utils/newowPatternDisplay'
import { NewowTrendChannelPrimitive } from '@/components/market/detail/newow/newowTrendChannelPrimitive'
import { NewowZhaoyaoMirrorPrimitive, buildNewowZhaoyaoMirrorData } from '@/components/market/detail/newow/newowZhaoyaoMirrorPrimitive'
import { NewowUpDownEnergyPrimitive, buildNewowUpDownEnergyData } from '@/components/market/detail/newow/newowUpDownEnergyPrimitive'
import { NewowMainForceControlPrimitive, buildNewowMainForceData } from '@/components/market/detail/newow/newowMainForceControlPrimitive'
import { NewowTrendReversalPrimitive, buildNewowTrendReversalData, buildNewowTrendReversalMarks } from '@/components/market/detail/newow/newowTrendReversalPrimitive'
import { newowAuxiliaryPaneLayout } from '@/components/market/detail/newow/newowAuxiliaryPaneLayout'
import { resolveChartTheme } from '@/styles/chartTheme'
import type { NewowProductSectionResponse, NewowProductStrategy } from '@/types/newowProduct'
import { formatChartAxisTimeInShanghai, formatChartTimeInShanghai } from '@/utils/barTime'
import { readNewowUiPreferences, rememberNewowUiPreferences } from '@/utils/newowUiPreferences'
import { newowComparisonCompatible } from '@/utils/newowComparison'
import { mergeNewowDualReferences, layoutNewowDualCallouts, newowDualDominance, newowDualVisibleStatistics, type DualPoint } from '@/utils/newowDualChartDisplay'
import { NewowDualBackgroundPrimitive } from '@/components/market/detail/newow/newowDualBackgroundPrimitive'
import { initialNewowChartLogicalRange } from '@/utils/chartViewport'
import { NIUWA_CALLOUT_BOX, layoutNiuwaReferenceCallouts, type PositionedCallout } from '@/utils/referenceCalloutLayout'
import {
  buildNewowProductChartModel,
  buildNewowActionCallouts,
  alignNewowAuxiliaryChartModel,
  resolveNewowAuxiliaryRenderState,
  chartMarkerTime,
  createNewowProductChartDisposer,
  NEWOW_PRODUCT_CHART_ADAPTER_KEY,
  newowChartSnapshotKey,
  preserveNewowViewport,
  productChartMarker,
  type NewowProductChartModel,
  type NewowProductResizeObserver,
} from '@/components/market/detail/newow/newowProductChartPrimitives'

const props = withDefaults(defineProps<{
  response: NewowProductSectionResponse<'chart'> | null
  priceBars?: readonly BarData[]
  priceFrequency?: string
  displayOnly?: boolean
  patternSelection?:PatternChoice|null
  patternWindowKey?:string|null
  strategy: NewowProductStrategy
  targetPrice?: string | null
  absorbPrice?: string | null
  referenceTrades?: readonly import('@/types/newowProduct').NewowReferenceTrade[]
  referenceTradesComplete?: boolean
  referenceStatsLoading?: boolean
  referenceStatsError?: string | null
  referencePriceStatus?: string
  comparisonResponse?: NewowProductSectionResponse<'chart'> | null
  comparisonReferenceTrades?: readonly import('@/types/newowProduct').NewowReferenceTrade[]
  auxiliaryResponse?: NewowProductSectionResponse<'auxiliary'> | null
  auxiliaryLifecycle?: import('@/types/newowProduct').NewowResourceLifecycle
  auxiliaryError?: string | null
  extraAuxiliaryPanes?: readonly NewowAdditionalPane[]
  selectedSignalId: string | null
  focusRequestId?: number
  loading?: boolean
  strategySwitching?: boolean
  showTools?: boolean
  hasMoreBefore?: boolean
}>(), { showTools: true, loading: false, hasMoreBefore: false, focusRequestId: 0 })

const emit = defineEmits<{
  loadEarlier: []
  'load-reference-stats': []
  'select-signal': [signalId: string]
  'focus-resolved': [signalId: string, focusRequestId: number]
  'select-comparison-signal': [strategy: 'trend' | 'oscillation', signalId: string]
  'select-hint': [hintId: string]
  'select-breakout':[event:NewowBreakoutEvent]; 'select-display':[event:NewowDisplayEvent]
  'analyze-channel': []
  'explain-main': []
  'explain-auxiliary': []
}>()

function actionDisplay(callout: KlineReferenceCallout, strategy = props.strategy) {
  return newowActionReturnDisplay(callout, strategy, allReferenceTrades.value)
}

function actionTitle(callout: KlineReferenceCallout, strategy = props.strategy) {
  const status = newowActionStatus(callout, strategy, allReferenceTrades.value)
  return status ? `${callout.title} · ${status}` : callout.title
}
function actionWidth(callout: KlineReferenceCallout, strategy = props.strategy): number {
  return Math.max(ACTION_LABEL_BOX.width, Math.min(180, Math.max(actionTitle(callout, strategy).length, actionDisplay(callout, strategy).text.length) * 7 + 14))
}
const pageTheme=ref(readNewowChartDisplayTheme())
let themeObserver:MutationObserver|null=null
const breakoutPoints=ref<BreakoutPoint[]>([]),showBreakoutShapes=ref(true),showBreakoutWicks=ref(true)
const displayPoints=ref<DisplayPoint[]>([])
watch(()=>[props.strategy,props.response?.meta.identity.product,props.response?.meta.identity.frequency,props.response?.meta.identity.formula_versions.join('|')],()=>{breakoutPoints.value=[]},{flush:'sync'})
const cautionOverlays = ref<Array<{x:number;y:number;key:string;tentative:boolean;state:CautionState;title:string;stemX:number;stemEnd:number}>>([])
const selectedCautionKey = ref<string | null>(null)
const selectedCaution = computed(() => cautionOverlays.value.find(item=>item.key===selectedCautionKey.value) ?? null)
watch(cautionOverlays, items => { if (!items.some(item=>item.key===selectedCautionKey.value)) selectedCautionKey.value=null }, {deep:true})

const visualOverlays = ref(readVisualOverlayPreferences())
const annotations = ref(readChartAnnotationPreferences())
const pure = computed(() => annotations.value.pure)
const settingsOpen = ref(false)
watch(annotations, value => saveVisualOverlayPreferences(value))

function syncDisplayPreferences() {
  if (document.visibilityState === 'hidden') return
  const display = readChartAnnotationPreferences()
  if (display.pure !== annotations.value.pure || display.extrema !== annotations.value.extrema
      || display.nineTurn !== annotations.value.nineTurn) annotations.value = display
  const overlays = readVisualOverlayPreferences()
  if (overlays.window !== visualOverlays.value.window || overlays.donchian !== visualOverlays.value.donchian
      || overlays.stop !== visualOverlays.value.stop) visualOverlays.value = overlays
}
watch(visualOverlays, value => { saveVisualOverlayPreferences(value); renderVisualOverlays() })
const cursorRows = ref<string[]>([])
const cursorTop = ref(0)
const extraPaneHeaders = ref<Array<{ component: NewowAuxiliaryPaneComponent; title: string; top: number; status: LayerStatus; formulaVersion: string | null }>>([])
const activeAuxiliary = shallowRef<ReturnType<ChartLayer['inspect']> | null>(null)
const extraStatusMessages: Partial<Record<LayerStatus, string>> = {
  loading: '加载中', warming: '预热中', invalid_source: '来源不匹配', compute_error: '计算结果不可用', missing_input: '缺少输入',
}
const extraPaneHeight = computed(() => pure.value ? 0 : (props.extraAuxiliaryPanes ?? []).reduce((sum, pane) => sum + (pane.height ?? 120), 0))
function onCrosshair(event: MouseEventParams<Time>): void {
  cursorRows.value = event.point == null ? [] : newowChartReadout(model.value, null, event.time ?? null)
  const chartTop = container.value?.offsetTop ?? 0
  const paneOffset = chart?.panes?.().slice(0, event.paneIndex ?? 0).reduce((height, pane) => height + pane.getHeight(), 0) ?? 0
  const cardHeight = cursorRows.value.length * 18 + 20
  cursorTop.value = chartTop + Math.max(0, Math.min((event.point?.y ?? 0) + paneOffset - 100, (container.value?.clientHeight ?? 0) - cardHeight))
}
const volumeBars = shallowRef<readonly DisplayVolumeBar[]>([])
const stageRoot = ref<HTMLElement | null>(null)
const fullscreen = ref(false)
const fullscreenError = ref<string | null>(null)
const auxiliaryTop = ref(0)
const actionOverlayTop = ref(0)
const actionOverlayHeight = ref(0)
const actionOverlayLeft = ref(0)
const actionOverlayWidth = ref(0)
const cycleCountOverlays = ref<Array<{ x: number; top: number; height: number; color: string; barEnd: string }>>([])
const processOverlays = ref<Array<{ id: string; kind: string; anchorPrice: string | null; barEnd:string; x: number; y: number; text: string; color: string; below: boolean; cycle?: boolean }>>([])
const attackOverlays = ref<Array<{ id: string; kind: string; x: number; y: number; height: number; width: number }>>([])
const positionedActions = ref<PositionedCallout[]>([])
const positionedComparison = ref<Array<PositionedCallout & { origin: 'trend' | 'oscillation' }>>([])
const comparisonSwitches = ref<Array<{ x: number; from: 'trend' | 'oscillation'; to: 'trend' | 'oscillation' }>>([])
const comparisonDominant = ref<'trend' | 'oscillation' | null>(null)
const trendTrack = ref(true)
const oscillationTrack = ref(true)
const comparisonBackground = ref(true)
const ACTION_LABEL_BOX = NIUWA_CALLOUT_BOX
const container = ref<HTMLElement | null>(null)
const detailSession = inject<DetailChartSession | null>(DETAIL_CHART_SESSION, null)
const auxiliaryToolbar = ref<HTMLElement | null>(null)
const followLatest = ref(true)
const detailLabels = ref(true)
const showActions = ref(true)
const showStructure = ref(true)
const showHints = ref(true)
const model = computed(() => props.response === null ? null : buildNewowProductChartModel(props.response))
const settingsIdentity = computed(() => {
  const value = model.value
  return value ? identityKey(value) : props.strategy
})
const layers = computed<NewowChartLayers>(() => ({
  structure: showStructure.value, actions: showActions.value, hints: showHints.value,
  breakouts: showBreakoutShapes.value, wicks: showBreakoutWicks.value, detail: detailLabels.value,
  trendTrack: trendTrack.value, oscillationTrack: oscillationTrack.value,
  comparisonBackground: comparisonBackground.value,
}))
function updateLayers(value: NewowChartLayers) {
  showStructure.value = value.structure
  showActions.value = value.actions
  showHints.value = value.hints
  showBreakoutShapes.value = value.breakouts
  showBreakoutWicks.value = value.wicks
  detailLabels.value = value.detail
  trendTrack.value = value.trendTrack
  oscillationTrack.value = value.oscillationTrack
  comparisonBackground.value = value.comparisonBackground
  rememberViewport()
}
function analyzeChannel() {
  settingsOpen.value = false
  // Let the drawer release focus and scroll before opening the comparison dialog.
  void nextTick(() => emit('analyze-channel'))
}
const comparisonActive = computed(() => newowComparisonCompatible(props.response, props.comparisonResponse ?? null))
const partnerModel = computed(() => comparisonActive.value && props.comparisonResponse ? buildNewowProductChartModel(props.comparisonResponse) : null)
const trackModels = computed(() => [model.value, partnerModel.value].filter((value): value is NewowProductChartModel => value !== null))
const fourStepMarks = computed(() => {
  const primary = model.value
  const partner = partnerModel.value
  if (!comparisonActive.value || primary?.identity.frequency !== '1d' || !partner) return null
  return newowFourStepMarks(primary.bars, [primary, partner].map(track => ({
    source: track.identity.strategy === 'oscillation' ? 'oscillation' : 'trend',
    actions: track.actions,
  })))
})
function dualStepTitle(title: string, id: string): string {
  const badge = fourStepMarks.value?.get(id)?.badge
  return badge ? `${badge} ${title}` : title
}
function dualStepDescription(id: string): string {
  const mark = fourStepMarks.value?.get(id)
  return mark ? `${mark.badge} ${mark.label} · ` : ''
}

const allReferenceTrades = computed(() => mergeNewowDualReferences([...(props.referenceTrades ?? []), ...(comparisonActive.value ? props.comparisonReferenceTrades ?? [] : [])]))
const comparisonStats = computed(() => newowDualVisibleStatistics(positionedComparison.value, allReferenceTrades.value))
const auxiliaryModel = computed(() => alignNewowAuxiliaryChartModel(props.response, props.auxiliaryResponse ?? null))
const auxiliaryReadiness = computed(() => projectNewowAuxiliaryReadiness(props.auxiliaryResponse?.value, props.response?.value?.bars.at(-1)))
const auxiliaryPresentation = computed(() => resolveNewowAuxiliaryRenderState(props.auxiliaryLifecycle ?? 'not_requested', auxiliaryModel.value !== null, props.auxiliaryError ?? null, auxiliaryReadiness.value?.message ?? null))
const mainLineColors: Record<string, string> = { b: '#F59E0B', a: '#2563EB', upper: '#16A34A', lower: '#DC2626', ma35: '#F59E0B', ma45: '#2563EB', ma10_display_v1: 'rgba(255,105,180,.7)' }
const legend = computed(() => [...new Map(model.value?.mainLines.filter(line => line.key !== 'ma10_display_v1').map(line => [line.key, line]) ?? []).values()])
const mainLegendLabel = computed(() => ({ trend: '趋势带', oscillation: '震荡区间', main_rise: '主升浪' })[props.strategy])
const adapter = inject(NEWOW_PRODUCT_CHART_ADAPTER_KEY, {
  createChart,
  createSeriesMarkers: (series) => createSeriesMarkers(series),
  createResizeObserver: (callback) => new ResizeObserver(callback),
})

let host: ChartHost | null = null
let chart: IChartApi | null = null
let candles: ISeriesApi<'Candlestick'> | null = null
let volume: ISeriesApi<'Histogram'> | null = null
const band = new NewowProductBandPrimitive()
const dualBackground = new NewowDualBackgroundPrimitive()
const trendChannel = new NewowTrendChannelPrimitive()
const publicPattern = new NewowPublicPatternPrimitive()
const priceAnnotations = new NewowPriceAnnotationPrimitive()
const marks = computed<NewowPriceAnnotation[]>(() => {
  const value = model.value
  if (!value || props.displayOnly || props.strategySwitching || props.loading) return []
  const bars = value.bars.map(bar => ({ ...bar, owner: JSON.stringify(
    [bar.physicalContract, bar.segmentId, bar.calculationSegmentId],
  ) }))
  const toMark = (mark: { index: number; side: 'high' | 'low' }) => {
    const bar = value.bars[mark.index]!
    return { ...mark, price: bar[mark.side],
      time: chartMarkerTime(bar.barEnd, value.identity.frequency, bar.tradingDay) }
  }
  const extrema = annotations.value.extrema ? newowExtrema(bars).map(mark => {
    const bar = value.bars[mark.index]!
    return { ...toMark(mark), kind: 'extremum' as const,
      text: newowReferencePrice(bar.displayPrices?.[mark.side] ?? String(bar[mark.side])) }
  }) : []
  const nine = annotations.value.nineTurn && !pure.value ? newowNineTurn(bars).map(mark => ({
    ...toMark(mark), kind: 'nine' as const, count: mark.count, text: String(mark.count),
  })) : []
  return [...extrema, ...nine].sort((a, b) => a.index - b.index)
})
function syncPricePrimitive(id: string, indicator: string, primitive: ISeriesPrimitive<Time>, show: boolean) {
  if (!host || !candles) return
  if (!show) host.removeLayer(id)
  else if (!host.hasLayer(id)) host.layer(id, indicator, 'main').primitive(candles, primitive)
}
function renderPriceAnnotations() {
  syncPricePrimitive('annotations', 'newow_annotations', priceAnnotations, marks.value.length > 0)
  priceAnnotations.setData(marks.value, pageTheme.value === 'dark')
}
watch([marks, pageTheme], renderPriceAnnotations, { flush: 'post' })
function renderPattern(){
 publicPattern.setData(null)
 const choice=props.patternSelection
 if(pure.value||!choice||!model.value||props.loading||props.strategySwitching||choice.windowKey!==props.patternWindowKey)return
 // Every source bar must still be exactly present in the accepted owner window.
 const accepted=new Map(model.value.bars.map(b=>[b.barEnd,b]))
 if(!choice.bars.every(b=>{const current=accepted.get(b.barEnd);return current&&current.sourceIdentity===b.sourceIdentity&&current.physicalContract===b.physicalContract&&current.segmentId===b.segmentId&&current.calculationSegmentId===b.calculationSegmentId}))return
 try{publicPattern.setData(buildNewowPatternGeometry(choice,model.value.identity.frequency))}catch{publicPattern.setData(null)}
}
watch(()=>[props.patternSelection,props.patternWindowKey,props.loading,props.strategySwitching],renderPattern)
const zhaoyaoMirror = new NewowZhaoyaoMirrorPrimitive()
const upDownEnergy = new NewowUpDownEnergyPrimitive()
const mainForceControl = new NewowMainForceControlPrimitive()
const trendReversal = new NewowTrendReversalPrimitive()
let auxiliaryAnchor: ISeriesApi<'Line'> | null = null
let auxiliaryZeroLine: { applyOptions(options: { color: string }): void } | null = null
type AuxiliaryLines = Map<string, ISeriesApi<'Line'> | ISeriesApi<'Histogram'>>
const auxiliaryLines: AuxiliaryLines = new Map()
let actionMarkers: ISeriesMarkersPluginApi<Time> | null = null
let observer: NewowProductResizeObserver | null = null
let renderedBars: NewowProductChartModel['bars'] = []
let renderedIdentity: NewowProductChartModel['identity'] | null = null
let retainedVisibleRange: LogicalRange | null = null
let rendering = false
let nearLeftBoundary = false
let paginationArmed = false
let paginationArmFrame: number | null = null
let actionProjectionFrame: number | null = null
let paneHeaderFrame: number | null = null
let actionProjectionScheduled = false
let programmaticRange: { from: number; to: number } | null = null
let resolvedSignalKey: string | null = null
let resolvedFocusRequestKey: string | null = null
let retainedStop: RetainedBuildStop | null = null
function renderVisualOverlays(): void {
  if (!chart || !candles || !host) return
  host.removeLayer('donchian')
  host.removeLayer('stop')
  const value = model.value
  if (pure.value || !value || props.displayOnly || props.loading || props.strategySwitching || props.response?.status.status !== 'ready' || value.identity.strategy !== props.strategy) { retainedStop = null; return }
  const owner = (b: NewowProductChartModel['bars'][number]) => `${b.physicalContract}:${b.segmentId}:${b.calculationSegmentId}`
  if (visualOverlays.value.donchian) {
    const points = visualDonchian(value.bars.map(b => ({ time: b.barEnd, high: b.high, low: b.low, owner: owner(b) })), visualOverlays.value.window)
    const options = { priceFormat: NEWOW_CHART_PRICE_FORMAT, lineWidth: 1 as const, lineStyle: 2 as const, priceLineVisible: false, lastValueVisible: false }
    const lines = host.layer('donchian', 'newow_donchian', 'main').band(
      { ...options, color: 'rgba(52,199,89,0.7)' }, { ...options, color: 'rgba(255,59,48,0.7)' },
    )
    for (const side of ['upper', 'lower'] as const) {
      lines[side].setData(points.map((p, i) => ({ time: chartMarkerTime(p.time, value.identity.frequency, value.bars[i]!.tradingDay), ...(p[side] === null ? {} : { value: p[side]! }) })))
    }
  }
  const anchorModel = comparisonActive.value ? trackModels.value.find(m => m.identity.strategy === 'oscillation') : value
  if (!anchorModel) { retainedStop = null; return }
  const range = chart.timeScale().getVisibleLogicalRange()
  // Logical indexes belong to the primary candle axis; partner windows can begin earlier.
  const bars = value.bars.filter((bar,i) => { const logical = chart ? detailChartIndex(chart, chartMarkerTime(bar.barEnd, value.identity.frequency, bar.tradingDay), i) : i; return !range || (logical >= Math.ceil(range.from) && logical <= Math.floor(range.to)) })
  retainedStop = retainBuildStop(retainedStop, `${identityKey(value)}:${comparisonActive.value ? 'dual' : 'single'}`, anchorModel.actions.map(a => { const b = anchorModel.bars.find(b => b.barEnd === a.barEnd && b.physicalContract === a.physicalContract && b.segmentId === a.segmentId); return { time:a.barEnd, owner:b ? owner(b) : '', price:a.referencePrice, action:a.kind } }),bars.map(b => ({time:b.barEnd,owner:owner(b)})))
  const price = retainedStopPrice(retainedStop, 0.07)
  if (price !== null) host.layer('stop', 'newow_stop', 'main').priceLevel(candles, {price,color:'#3B82F6',lineStyle:2,lineWidth:1,title:'止损价（−7%）',axisLabelVisible:true})
}
const mainLines = new Map<string, ISeriesApi<'Line'>>()

onMounted(async () => {
  await nextTick()
  if (container.value === null) return
  pageTheme.value=readNewowChartDisplayTheme()
  if(typeof MutationObserver!=='undefined'&&typeof document!=='undefined'){
    themeObserver=new MutationObserver(()=>{pageTheme.value=readNewowChartDisplayTheme();dualBackground.setDark(pageTheme.value==='dark');renderVolume(model.value)})
    for(const target of [document.documentElement,document.body])if(target)themeObserver.observe(target,{attributes:true,attributeFilter:['data-theme']})
  }
  const theme = resolveChartTheme(container.value)
  host = mountChartHost(container.value, {
    width: container.value.clientWidth,
    height: container.value.clientHeight,
    layout: { background: { type: ColorType.Solid, color: theme.background }, textColor: theme.text, panes: { enableResize: false, separatorColor: '#EBEDF0' } },
    grid: { vertLines: { color: theme.grid }, horzLines: { color: theme.grid } },
    rightPriceScale: { borderColor: theme.axis, scaleMargins: { top: 0.05, bottom: 0.14 } },
    crosshair: { mode: CrosshairMode.Normal },
    localization: { timeFormatter: formatChartTimeInShanghai },
    timeScale: { borderColor: theme.axis, timeVisible: true, tickMarkFormatter: formatChartAxisTimeInShanghai },
  }, detailSession?.acquire ?? adapter.createChart)
  chart = host.chart
  candles = host.layer('price', 'price', 'main').candles({
    priceFormat: NEWOW_CHART_PRICE_FORMAT,
    upColor: theme.candleUp, downColor: theme.candleDown,
    borderUpColor: theme.candleUp, borderDownColor: theme.candleDown,
    wickUpColor: theme.candleUp, wickDownColor: theme.candleDown,
  })
  chart.panes()[0]!.setStretchFactor(5)
  dualBackground.setDark(pageTheme.value==='dark')
  host.layer('pattern', 'newow_pattern', 'main').primitive(candles, publicPattern)
  // Public detail v3.4.49: volume shares the price pane on its own hidden scale.
  const profile = comparisonActive.value ? 'newow_dual' : `newow_${props.strategy}` as const
  const volumePolicy = CHART_PROFILES[profile].volume
  volume = host.layer('volume', `${volumePolicy}_volume`, 'volume').histogram({ priceScaleId: 'volume', priceFormat: { type: 'volume' }, priceLineVisible: false, lastValueVisible: false })
  volume.priceScale().applyOptions(VOLUME_SCALE_OPTIONS)
  syncAuxiliaryPane()
  if (typeof document !== 'undefined') {
    document.addEventListener('fullscreenchange', onFullscreenChange)
    document.addEventListener('visibilitychange', syncDisplayPreferences)
  }
  if (typeof window !== 'undefined') {
    window.addEventListener('pageshow', syncDisplayPreferences)
    window.addEventListener('storage', syncDisplayPreferences)
  }
  actionMarkers = host.layer('actions', 'newow_actions', 'main').markers(candles, adapter.createSeriesMarkers)
  chart.subscribeCrosshairMove?.(onCrosshair)
  chart.timeScale().subscribeVisibleLogicalRangeChange(onRangeChange)
  observer = adapter.createResizeObserver(resize)
  observer.observe(container.value)
  if (stageRoot.value) observer.observe(stageRoot.value)
  if (auxiliaryToolbar.value) observer.observe(auxiliaryToolbar.value)
  renderModel(model.value)
  renderPriceAnnotations()
  resize()
})

onUnmounted(createNewowProductChartDisposer({
  unsubscribeRange: () => chart?.timeScale().unsubscribeVisibleLogicalRangeChange(onRangeChange),
  disconnectResizeObserver: () => observer?.disconnect(),
  removeChart: () => {
    themeObserver?.disconnect();themeObserver=null
    chart?.unsubscribeCrosshairMove?.(onCrosshair)
    rememberViewport()
    if (paginationArmFrame !== null) cancelAnimationFrame(paginationArmFrame)
    if (actionProjectionFrame !== null) cancelAnimationFrame(actionProjectionFrame)
    if (paneHeaderFrame !== null) cancelAnimationFrame(paneHeaderFrame)
    if (typeof document !== 'undefined') {
      document.removeEventListener('fullscreenchange', onFullscreenChange)
      document.removeEventListener('visibilitychange', syncDisplayPreferences)
    }
    if (typeof window !== 'undefined') {
      window.removeEventListener('pageshow', syncDisplayPreferences)
      window.removeEventListener('storage', syncDisplayPreferences)
    }
    host?.dispose()
    host = null
    chart = null; candles = null; volume = null; auxiliaryAnchor = null; auxiliaryZeroLine = null
    mainLines.clear(); auxiliaryLines.clear()
  },
}))

watch([model, () => props.strategySwitching, () => props.priceBars, () => props.displayOnly], ([value]) => { renderModel(value) })
watch([() => props.targetPrice, () => props.absorbPrice, () => props.loading, () => props.strategy], renderReferencePrices, { flush: 'post' })
watch(showStructure, () => renderModel(model.value))
watch(pure, () => {
  cursorRows.value = []
  syncAuxiliaryPane()
  renderModel(model.value)
  resize()
}, { flush: 'post' })
watch(showBreakoutShapes, () => { renderReferencePrices(); renderVolume(model.value) })
watch([showActions, () => props.loading], () => { renderMarkers(model.value); scheduleActionProjection() })
watch([model, allReferenceTrades], () => { cursorRows.value = []; scheduleActionProjection() }, { flush: 'post' })
watch([detailLabels, showHints], scheduleActionProjection, { flush: 'post' })
watch([() => props.loading, () => props.strategySwitching, () => props.strategy, () => props.response?.status.status, () => props.displayOnly], renderVisualOverlays)
watch([partnerModel, trendTrack, oscillationTrack, comparisonBackground], () => renderModel(model.value))
watch([auxiliaryModel, auxiliaryPresentation, () => props.extraAuxiliaryPanes], () => { cursorRows.value = []; resize() }, { flush: 'post' })
watch([() => props.selectedSignalId, () => props.focusRequestId], () => {
  renderMarkers(model.value)
  resolveSelectedSignal()
  scheduleActionProjection()
}, { flush: 'post' })
function identityKey(value: NewowProductChartModel): string {
  return `${value.identity.product}:${value.identity.strategy}:${value.identity.frequency}`
}

function axisKey(bars: NewowProductChartModel['bars']): string { return JSON.stringify(bars.map(bar => [bar.barEnd, bar.physicalContract, bar.calculationSegmentId])) }
function rememberViewport(): void {
  if (!renderedIdentity || !chart) return
  rememberNewowUiPreferences(`newow:${renderedIdentity.product}:${renderedIdentity.strategy}:${renderedIdentity.frequency}`, { chart: {
    axis: axisKey(renderedBars), range: retainedVisibleRange ?? chart.timeScale().getVisibleLogicalRange(), detail: detailLabels.value,
    actions: showActions.value, structure: showStructure.value, hints: showHints.value,
    breakouts: showBreakoutShapes.value, wicks: showBreakoutWicks.value, trendTrack: trendTrack.value,
    oscillationTrack: oscillationTrack.value, comparisonBackground: comparisonBackground.value,
  } })
}
function renderReferencePrices(): void {
  if (!candles || !host) return
  host.removeLayer('price-references')
  host.removeLayer('breakout-reference')
  if (pure.value || !model.value) return
  for (const [value, color, title] of [
    [props.targetPrice, '#ff4d9d', '目标价'],
    [props.absorbPrice, '#ff3b30', '吸筹价'],
  ] as const) {
    if (value == null || !/^\d+(\.\d+)?$/.test(value)) continue
    const price = Number(value)
    if (!Number.isFinite(price) || price <= 0) continue
    host.layer('price-references', 'newow_price_reference', 'main').priceLevel(candles, { price, color, title, lineWidth: 1, lineStyle: 1,
      axisLabelVisible: true, axisLabelColor: color, axisLabelTextColor: '#ffffff' })
  }
  const breakout = showBreakoutShapes.value && !props.displayOnly && !props.loading && !props.strategySwitching && props.strategy === model.value.identity.strategy
    && props.response?.status.status === 'ready' ? newowOscillationBreakout(model.value) : null
  if (breakout) host.layer('breakout-reference', 'newow_breakouts', 'main').priceLevel(candles, {
    price: breakout.price, color: '#FF9800', title: `突破 ${breakout.displayScore}/7`,
    lineWidth: 1, lineStyle: 2, axisLabelVisible: true, axisLabelColor: '#FF9800', axisLabelTextColor: '#ffffff',
  })
}

const candleWriter = createPriceSeriesWriter<CandlestickData<Time>>()
const volumeWriter = createPriceSeriesWriter<HistogramData<Time> | WhitespaceData<Time>>()
const anchorWriter = createPriceSeriesWriter<{ time: Time }>()

function renderVolume(value:NewowProductChartModel|null):void {
  if(!volume||!value||props.strategySwitching||props.displayOnly)return
  const input = detailChartVolumeBars(chart!, value.bars.map(bar => ({ ...bar, time: bar.barEnd })))
  volumeBars.value = input
  const { colors } = volumePresentation('newow', input, { theme: pageTheme.value, enabled: !pure.value && showBreakoutShapes.value })
  volumeWriter.write(volume,input.map((bar,index)=>({time:detailChartTime({ time: bar.time, trading_day: bar.tradingDay ?? bar.trading_day }, value.identity.frequency),...(validVolume(bar)?{value:bar.volume,color:colors[index]}:{})})),`${value.identity.product}:${value.identity.frequency}`)
}
function reportRenderedEnd(end?: string, contract?: string, frequency?: string) {
  if (!stageRoot.value) return
  stageRoot.value.dataset.klineEnd = end ?? ''
  stageRoot.value.dataset.klineContract = contract ?? ''
  stageRoot.value.dataset.klineFrequency = frequency ?? ''
}

function renderModel(value: NewowProductChartModel | null): void {
  processOverlays.value = []
  cycleCountOverlays.value = []
  if (chart === null || candles === null) return
  renderReferencePrices()
  renderVisualOverlays()
  renderPattern()
  if (value === null) {
    rememberViewport()
    paginationArmed = false
    if (renderedIdentity !== null && renderedBars.length > 0) {
      const visibleRange = chart.timeScale().getVisibleLogicalRange()
      if (visibleRange !== null) retainedVisibleRange = visibleRange
    }
    // Keep only the price facts while switching strategy, never its old indicators or signals.
    if (!props.strategySwitching) {
      const preview = props.priceBars ?? []

      const points = preview.map(bar => ({ time: (props.priceFrequency ?? '').endsWith('m')
        ? Math.floor(Date.parse(bar.time) / 1000) as import('lightweight-charts').UTCTimestamp
        : chartMarkerTime(bar.time, '1d', bar.trading_day ?? bar.time.slice(0, 10)), open: bar.open, high: bar.high, low: bar.low, close: bar.close }))
      candleWriter.write(candles, points, 'preview')
      const last = preview.at(-1)
      reportRenderedEnd(last?.time, last?.physicalContract, props.priceFrequency)

      if (auxiliaryAnchor) anchorWriter.write(auxiliaryAnchor, [], 'cleared')
    }
    const previewVolume = props.strategySwitching ? volumeBars.value : detailChartVolumeBars(chart, props.priceBars ?? [])
    volumeBars.value = previewVolume.map(bar => ({ ...bar, confirmed: false }))
    const { colors: previewColors } = volumePresentation('newow', volumeBars.value, { theme: pageTheme.value, enabled: false })
    if (volume) volumeWriter.write(volume, volumeBars.value.map((bar, index) => ({
      time: detailChartTime({ time: bar.time, trading_day: bar.tradingDay ?? bar.trading_day }, props.priceFrequency ?? '1d'),
      ...(validVolume(bar) ? { value: bar.volume, color: previewColors[index] } : {}),
    })), 'preview')
    host?.removeLayer('strategy-band')
    host?.removeLayer('comparison-background')
    host?.removeLayer('strategy-channel')
    band.setData([])
    dualBackground.setData([])
    trendChannel.setData([])
    renderAuxiliary()
    for (const id of mainLines.keys()) host?.removeLayer(`main:${id}`)
    mainLines.clear()
    renderMarkers(null)
    positionedActions.value = []; positionedComparison.value = []; comparisonSwitches.value = []; comparisonDominant.value = null
    resolvedSignalKey = null
    resolvedFocusRequestKey = null
    return
  }
  const changedIdentity = renderedIdentity !== null && (renderedIdentity.product !== value.identity.product || renderedIdentity.strategy !== value.identity.strategy || renderedIdentity.frequency !== value.identity.frequency)
  if (changedIdentity) rememberViewport()
  const initialPreferences = renderedIdentity === null || changedIdentity ? readNewowUiPreferences(`newow:${value.identity.product}:${value.identity.strategy}:${value.identity.frequency}`).chart : undefined
  if (renderedIdentity === null || changedIdentity) {
    detailLabels.value = initialPreferences?.detail ?? true
    showActions.value = initialPreferences?.actions ?? true
    showStructure.value = initialPreferences?.structure ?? true
    showHints.value = initialPreferences?.hints ?? true
    showBreakoutShapes.value = initialPreferences?.breakouts ?? true
    showBreakoutWicks.value = initialPreferences?.wicks ?? true
    trendTrack.value = initialPreferences?.trendTrack ?? true
    oscillationTrack.value = initialPreferences?.oscillationTrack ?? true
    comparisonBackground.value = initialPreferences?.comparisonBackground ?? true
  }
  const previousModel = renderedIdentity === null ? null : { identity: renderedIdentity, bars: renderedBars }
  const identityChanged = renderedIdentity !== null && (
    value.identity.product !== renderedIdentity.product
    || value.identity.strategy !== renderedIdentity.strategy
    || value.identity.frequency !== renderedIdentity.frequency
  )
  const previousRange = retainedVisibleRange ?? chart.timeScale().getVisibleLogicalRange()
  const previousFirst = renderedBars[0]?.barEnd
  const previousOffset = previousFirst === undefined ? -1 : value.bars.findIndex((bar) => bar.barEnd === previousFirst)
  const prepended = Math.max(0, previousOffset)
  const retainsPreviousAxis = previousModel !== null && (
    preserveNewowViewport(previousModel, value)
    || (!identityChanged
      && previousOffset >= 0
      && previousModel.bars.every((bar, index) => bar.barEnd === value.bars[previousOffset + index]?.barEnd))
  )
  const resetViewport = previousModel !== null && !retainsPreviousAxis
  rendering = true
  const priceIdentity = `${value.identity.product}:${value.identity.frequency}`
  candleWriter.write(candles, value.bars.map((bar) => ({
    time: chartMarkerTime(bar.barEnd, value.identity.frequency, bar.tradingDay),
    open: bar.open, high: bar.high, low: bar.low, close: bar.close,
  })), priceIdentity)
  const last = value.bars.at(-1)
  reportRenderedEnd(last?.barEnd, last?.physicalContract, value.identity.frequency)
  renderVolume(value)
  if (auxiliaryAnchor) anchorWriter.write(auxiliaryAnchor, value.bars.map(bar => ({ time: chartMarkerTime(bar.barEnd, value.identity.frequency, bar.tradingDay) })), priceIdentity)
  const trendModel = trackModels.value.find(item => item.identity.strategy === 'trend')
  const showStructureLayers = !pure.value && showStructure.value
  const bandAreas = showStructureLayers && !comparisonActive.value ? value.bandAreas : []
  syncPricePrimitive('strategy-band', 'newow_trend', band, bandAreas.length > 0)
  band.setData(bandAreas)
  const backgroundTimes = showStructureLayers && comparisonActive.value && comparisonBackground.value
    ? (trendModel?.bandAreas.filter(area => area.color === 'rgba(54, 90, 245, 0.35)').map(area => area.time) ?? []) : []
  syncPricePrimitive('comparison-background', 'newow_dual_background', dualBackground, backgroundTimes.length > 0)
  dualBackground.setData(backgroundTimes)
  const channelModel = comparisonActive.value ? trackModels.value.find(item => item.identity.strategy === 'oscillation') : value
  const channelPoints = showStructureLayers ? channelModel?.channelPoints ?? [] : []
  syncPricePrimitive('strategy-channel', 'newow_oscillation', trendChannel, channelPoints.length > 0)
  trendChannel.setData(channelPoints.map((point) => ({
    time: chartMarkerTime(point.barEnd, value.identity.frequency, point.tradingDay),
    upper: point.upper,
    lower: point.lower,
  })))
  renderAuxiliary()
  syncMainLines(comparisonActive.value ? { ...value, mainLines: trackModels.value.flatMap(item => item.mainLines) } : value)
  renderMarkers(value)
  const sharedViewport = detailChartViewport(chart)
  if (sharedViewport) {
    followLatest.value = false
    setRange(sharedViewport)
  } else if (renderedIdentity !== null && initialPreferences?.range && initialPreferences.axis === axisKey(value.bars)) {
    followLatest.value = false
    setRange(initialPreferences.range)
  } else if (resetViewport || previousModel === null || renderedBars.length === 0) {
    followLatest.value = true
    resolvedSignalKey = null
    resolvedFocusRequestKey = null
    const range = initialNewowChartLogicalRange(value.bars.length, container.value?.clientWidth ?? 1000)
    if (range === null) chart.timeScale().fitContent()
    else setRange(range)
  } else if (prepended > 0 && previousRange !== null) {
    setRange({ from: previousRange.from + prepended, to: previousRange.to + prepended })
  } else if (previousRange !== null) {
    setRange(previousRange)
  }
  renderedBars = value.bars
  renderedIdentity = { ...value.identity }
  retainedVisibleRange = null
  rendering = false
  projectActionLabels(value)
  renderVisualOverlays()
  resolveSelectedSignal()
}

function syncMainLines(value: NewowProductChartModel): void {
  if (host === null) return
  const active = new Set((!pure.value && showStructure.value ? value.mainLines : []).map((line) => line.id))
  for (const id of mainLines.keys()) {
    if (active.has(id)) continue
    host.removeLayer(`main:${id}`)
    mainLines.delete(id)
  }

  for (const line of !pure.value && showStructure.value ? value.mainLines : []) {
    let series = mainLines.get(line.id)
    if (series === undefined) {
      const displayId = ['a', 'b'].includes(line.key) ? 'newow_trend'
        : ['upper', 'lower'].includes(line.key) ? 'newow_oscillation' : 'newow_main_rise'
      series = host.layer(`main:${line.id}`, displayId, 'main').line({
        priceFormat: NEWOW_CHART_PRICE_FORMAT,
        color: mainLineColors[line.key] ?? '#64748B',
        lineWidth: ['a', 'b', 'ma35', 'ma45', 'ma10_display_v1'].includes(line.key) ? 1 : 2,
        lineVisible: line.key !== 'upper' && line.key !== 'lower',
        lineStyle: line.key === 'a' || line.key === 'b' || line.key === 'ma35' || line.key === 'ma45' || line.key === 'ma10_display_v1' ? 2 : 0,
        lastValueVisible: false,
        priceLineVisible: false,
      })
      mainLines.set(line.id, series)
    }
    series.setData(line.points.map((point): LineData<Time> => ({
      time: chartMarkerTime(point.barEnd, value.identity.frequency, point.tradingDay), value: point.value,
    })))
  }
}

function renderMarkers(value: NewowProductChartModel | null): void {
  if (host === null || actionMarkers === null) return
  const hidden = pure.value || comparisonActive.value || !showActions.value
  const preview = props.displayOnly || props.strategySwitching || (value !== null && value.identity.strategy !== props.strategy)
  const response = value === null || preview ? null : props.response
  const latest = response ? value?.bars.at(-1) : null
  const featureStatus = response?.status?.status
  const layer = host.layer('actions', 'newow_actions', 'main')
  layer.updateDiagnostics({
    status: hidden ? 'hidden' : latest && featureStatus === 'ready' ? 'ready'
      : featureStatus === 'warming' ? 'warming' : props.loading || props.strategySwitching ? 'loading' : 'missing_input',
    formulaVersion: latest ? response?.meta.identity.formula_versions.join(' / ') || null : null,
    sourceIdentity: latest ? response?.meta.data_revision_identity ?? response?.meta.input_content_sha256 ?? null : null,
    frequency: latest ? value?.identity.frequency ?? null : null,
    dataCutoff: latest?.barEnd ?? null,
  })
  if (hidden || preview || value === null) { actionMarkers.setMarkers([]); return }
  const actions: SeriesMarker<Time>[] = [...value.actions]
    .sort((left, right) => Date.parse(left.barEnd) - Date.parse(right.barEnd) || (left.sequence ?? -1) - (right.sequence ?? -1))
    .map((item) => ({ ...productChartMarker(
      item,
      props.selectedSignalId,
      chartMarkerTime(item.barEnd, value.identity.frequency, item.tradingDay),
    ), text: '' }))
  actionMarkers.setMarkers(actions)
}

function projectActionLabels(value: NewowProductChartModel | null = model.value): void {
  breakoutPoints.value=[]
  displayPoints.value=[]
  cautionOverlays.value = []
  attackOverlays.value = []
  processOverlays.value = []
  cycleCountOverlays.value = []
  if (pure.value || props.displayOnly || props.strategySwitching || chart === null || candles === null || container.value === null || value === null) {
    positionedActions.value = []; positionedComparison.value = []; comparisonSwitches.value = []; comparisonDominant.value = null
    return
  }
  const scale = chart.timeScale()
  const timeToCoordinate = (scale as unknown as { timeToCoordinate?: (time: Time) => number | null }).timeToCoordinate
  const priceToCoordinate = (candles as unknown as { priceToCoordinate?: (price: number) => number | null }).priceToCoordinate
  if (timeToCoordinate === undefined || priceToCoordinate === undefined) {
    positionedActions.value = []; positionedComparison.value = []; comparisonSwitches.value = []; comparisonDominant.value = null
    return
  }
  const widthFn = (scale as unknown as { width?: () => number }).width
  const panesFn = (chart as unknown as { panes?: () => Array<{ getHeight?: () => number }> }).panes
  const width = widthFn?.call(scale) ?? container.value.clientWidth
  const height = panesFn?.call(chart)[0]?.getHeight?.() ?? container.value.clientHeight
  auxiliaryTop.value = container.value.offsetTop + chart.panes()[0]!.getHeight()
  actionOverlayTop.value = container.value.offsetTop
  actionOverlayHeight.value = height
  actionOverlayLeft.value = container.value.offsetLeft
  actionOverlayWidth.value = width
  cautionOverlays.value = []
  for (const event of props.response?.value?.caution_events ?? []) {
    if (!event.detail_visible) continue
    const bar=value.bars.find(bar=>bar.barEnd===event.bar_end)
    if (!bar) continue
    const x=timeToCoordinate.call(scale,chartMarkerTime(bar.barEnd,value.identity.frequency,bar.tradingDay))
    const y=priceToCoordinate.call(candles,bar.close)
    if (x != null && y != null && Number.isFinite(x) && Number.isFinite(y) && x>=0 && x<=width && y>=0 && y<=height) {
      const capsuleX=Math.max(16,Math.min(width-16,x)), capsuleY=Math.max(0,y-26)
      cautionOverlays.value.push({x:capsuleX,y:capsuleY,key:event.event_id,tentative:event.tentative,state:event.display_state,title:cautionDisplayTitle(event),stemX:16+x-capsuleX,stemEnd:y-capsuleY-16})
    }
  }
  const breakoutRange=scale.getVisibleLogicalRange()
  const breakoutCandleWidth=Math.max(2,width/Math.max(1,breakoutRange?breakoutRange.to-breakoutRange.from:value.bars.length)*.6)
  const breakoutBars=value.bars.map(b=>({bar_end:b.barEnd,physical_contract:b.physicalContract,segment_id:b.segmentId,calculation_segment_id:b.calculationSegmentId}))
  const breakoutEvents=props.strategy==='oscillation'?(props.response?.value?.breakout_events??[]):[]
  breakoutPoints.value=breakoutEvents.flatMap(event=>{
    const bar=value.bars.find(b=>b.barEnd===event.bar_end&&b.physicalContract===event.physical_contract&&b.calculationSegmentId===event.calculation_segment_id)
    if(!bar)return []
    const x=timeToCoordinate.call(scale,chartMarkerTime(bar.barEnd,value.identity.frequency,bar.tradingDay)),y=priceToCoordinate.call(candles,event.side==='up'?bar.high:bar.low)
    const index=detailChartIndex(chart!,chartMarkerTime(bar.barEnd,value.identity.frequency,bar.tradingDay),value.bars.indexOf(bar))
    return x!=null&&y!=null&&displayIndexVisible(index,scale.getVisibleLogicalRange())?[{event,x,y,candleWidth:breakoutCandleWidth,band:breakoutBand(event,breakoutBars,value.bars.indexOf(bar),i=>timeToCoordinate.call(scale,chartMarkerTime(value.bars[i]!.barEnd,value.identity.frequency,value.bars[i]!.tradingDay)),p=>priceToCoordinate.call(candles,p),breakoutCandleWidth)}]:[]
  })
  const displayEvents=[...(props.response?.value?.display_events??[]),...(comparisonActive.value ? props.comparisonResponse?.value?.display_events??[] : [])]
  const seenDisplay=new Set<string>()
  displayPoints.value=displayEvents.flatMap(event=>{
    // Shared J is emitted in both strategy reads; paint only once. Fusion's
    // breakdown always comes from its oscillation response, never trend BUILD.
    if(event.kind==='TREND_REVERSAL'||seenDisplay.has(event.event_id))return []
    seenDisplay.add(event.event_id)
    const bar=value.bars.find(b=>b.barEnd===event.bar_end&&b.physicalContract===event.physical_contract&&b.calculationSegmentId===event.calculation_segment_id)
    if(!bar)return []
    const x=timeToCoordinate.call(scale,chartMarkerTime(bar.barEnd,value.identity.frequency,bar.tradingDay)),y=priceToCoordinate.call(candles,event.kind==='OSC_BREAKDOWN'?bar.low:bar.high)
    const index=detailChartIndex(chart!,chartMarkerTime(bar.barEnd,value.identity.frequency,bar.tradingDay),value.bars.indexOf(bar))
    return x!=null&&y!=null&&displayIndexVisible(index,scale.getVisibleLogicalRange())?[{event,x,y}]:[]
  })
  if (showHints.value && !comparisonActive.value) {
    cycleCountOverlays.value = (value.cycleCounts ?? []).flatMap(({ bar, color }) => {
      const x = timeToCoordinate.call(scale, chartMarkerTime(bar.barEnd, value.identity.frequency, bar.tradingDay))
      const high = priceToCoordinate.call(candles, bar.high)
      const low = priceToCoordinate.call(candles, bar.low)
      if (x == null || high == null || low == null || ![x, high, low].every(Number.isFinite) || x < 0 || x > width) return []
      return [{ x, top: Math.min(high, low), height: Math.abs(low - high), color, barEnd: bar.barEnd }]
    })
    const bars = new Map(value.bars.map(bar => [bar.barEnd, bar]))
    const projected = value.hints.flatMap(hint => {
      const bar = bars.get(hint.barEnd)
      const display = bar ? newowProcessHintDisplay(hint, bar) : null
      if (!bar || !display) return []
      const x = timeToCoordinate.call(scale, chartMarkerTime(bar.barEnd, value.identity.frequency, bar.tradingDay))
      const y = priceToCoordinate.call(candles, display.displayPrice)
      if (x == null || y == null || !Number.isFinite(x) || !Number.isFinite(y)) return []
      const range=scale.getVisibleLogicalRange()
      if(value.identity.strategy==='main_rise'&&range){
        const index=detailChartIndex(chart!,chartMarkerTime(bar.barEnd,value.identity.frequency,bar.tradingDay),value.bars.indexOf(bar))
        if(index<Math.floor(range.from)||index>Math.ceil(range.to)||(display.cycle&&index>=Math.ceil(range.to)))return []
      }else if(x<0||x>width||y<0||y>height)return []
      return [{ ...display, id: hint.id, kind: hint.kind, barEnd:bar.barEnd, anchorPrice: hint.anchorPrice, x, y: y + (display.below ? display.padding : -display.padding) }]
    })
    processOverlays.value=value.identity.strategy==='main_rise'?layoutMainRiseProcessLabels(projected):projected
  }
  if (showHints.value && value.identity.strategy === 'oscillation') {
    const range = scale.getVisibleLogicalRange()
    const count = Math.max(1, range ? range.to - range.from + 1 : value.bars.length)
    const barWidth = Math.max(2, Math.min(6, width / count * .6))
    attackOverlays.value = value.hints.flatMap(hint => {
      if (!['ZLGJ_BUY', 'ZLGJ_SELL', 'OSCILLATION_J'].includes(hint.kind)) return []
      const bar = value.bars.find(b => b.barEnd === hint.barEnd && b.physicalContract === hint.physicalContract)
      if (!bar) return []
      const x = timeToCoordinate.call(scale, chartMarkerTime(bar.barEnd, value.identity.frequency, bar.tradingDay))
      const y = priceToCoordinate.call(candles, hint.kind === 'OSCILLATION_J' ? Number(hint.anchorPrice) : bar.open)
      const closeY = priceToCoordinate.call(candles, bar.close)
      if (x == null || y == null || closeY == null || x < 0 || x > width) return []
      return [{ id: hint.id, kind: hint.kind, x, y: hint.kind === 'OSCILLATION_J' ? y - 12 : Math.min(y, closeY), height: Math.max(1.5, Math.abs(closeY - y)), width: barWidth }]
    })
  }
  positionedComparison.value = []
  comparisonSwitches.value = []; comparisonDominant.value = null
  if (comparisonActive.value) {
    const dominance = newowDualDominance(value, trackModels.value)
    comparisonDominant.value = dominance.dominant
    comparisonSwitches.value = dominance.switches.flatMap(point => {
      const bar = value.bars[point.index]!
      const x = timeToCoordinate.call(scale, chartMarkerTime(bar.barEnd, value.identity.frequency, bar.tradingDay))
      return x !== null && x >= 0 && x <= width ? [{ x, from: point.from, to: point.to }] : []
    })
    const points: DualPoint[] = []
    for (const track of trackModels.value) {
      const origin: 'trend' | 'oscillation' = track.identity.strategy === 'trend' ? 'trend' : 'oscillation'
      if (origin === 'trend' ? !trendTrack.value : !oscillationTrack.value) continue
      points.push(...buildNewowActionCallouts(track).flatMap(callout => {
        const action = track.actions.find(item => item.id === callout.id)
        if (!action || !value.bars.some(bar => bar.barEnd === action.barEnd)) return []
        const x = timeToCoordinate.call(scale, chartMarkerTime(action.barEnd, value.identity.frequency, action.tradingDay))
        const y = priceToCoordinate.call(candles, action.value)
        const bar = value.bars.find(b => b.barEnd === action.barEnd)
        const highY = bar ? priceToCoordinate.call(candles, bar.high) : null
        const lowY = bar ? priceToCoordinate.call(candles, bar.low) : null
        const candle = x !== null && highY !== null && lowY !== null ? { left: x - 8, top: Math.min(highY, lowY) - 3, width: 16, height: Math.abs(lowY - highY) + 6 } : undefined
        if (x === null || y === null) return []
        return [{ callout: { ...callout, title: `${origin === 'trend' ? '趋势' : '震荡'}${callout.title}` }, origin, x, y, candle,
          boxWidth: (detailLabels.value ? Math.max(100, actionWidth(callout, origin)) : Math.max(86, newowSimpleDualLabel(origin, callout.above, callout.price).length * 7 + 12)) + (fourStepMarks.value?.has(callout.id) ? 16 : 0), boxHeight: detailLabels.value ? 28 : 18 }]
      }))
    }
    positionedComparison.value = showActions.value ? layoutNewowDualCallouts(points, width, height) : []
    positionedActions.value = []
    return
  }
  const breakout = newowOscillationBreakout(value)
  const breakoutY = breakout ? priceToCoordinate.call(candles, breakout.price) : null
  const reserved = breakoutY === null ? [] : [{ left: Math.max(0, width - 110), top: breakoutY - 22, width: 110, height: 44 }]
  reserved.push(...cautionOverlays.value.map(p=>({left:p.x-22,top:p.y,width:44,height:20})))
  const actionById = new Map(value.actions.map(action => [action.id, action]))
  positionedActions.value = layoutNiuwaReferenceCallouts(buildNewowActionCallouts(value).flatMap(callout => {
    const action = actionById.get(callout.id)
    if (action === undefined) return []
    const x = timeToCoordinate.call(scale, chartMarkerTime(action.barEnd, value.identity.frequency, action.tradingDay))
    const y = priceToCoordinate.call(candles, action.value)
    const bar = value.bars.find(bar => bar.barEnd === action.barEnd)
    const highY = bar ? priceToCoordinate.call(candles, bar.high) : null
    const lowY = bar ? priceToCoordinate.call(candles, bar.low) : null
    const candle = x !== null && highY !== null && lowY !== null
      ? { left: x - 8, top: Math.min(highY, lowY) - 3, width: 16, height: Math.abs(lowY - highY) + 6 } : undefined
    return x === null || y === null ? [] : [{
      callout, x, y, candle,
      boxWidth: actionWidth(callout),
      boxHeight: ACTION_LABEL_BOX.height,
      expanded: props.selectedSignalId === callout.id,
    }]
  }), width, height, reserved)
}

function scheduleActionProjection(): void {
  if (actionProjectionScheduled) return
  actionProjectionScheduled = true
  const finish = () => {
    actionProjectionScheduled = false
    actionProjectionFrame = null
    projectActionLabels()
  }
  if (typeof requestAnimationFrame === 'undefined') queueMicrotask(finish)
  else actionProjectionFrame = requestAnimationFrame(finish)
}

function revealSignal(signalId: string): boolean {
  const value = model.value
  if (chart === null || value === null) return false
  const index = value.actions.findIndex((action) => action.id === signalId)
  if (index < 0) return false
  const key = `${identityKey(value)}:${signalId}`
  const requestKey = `${key}:${props.focusRequestId}`
  if (resolvedSignalKey === key && resolvedFocusRequestKey === requestKey) return true
  const barEnd = value.actions[index]!.barEnd
  const barIndex = value.bars.findIndex((bar) => bar.barEnd === barEnd)
  if (barIndex < 0) return false
  const current = chart.timeScale().getVisibleLogicalRange()
  const width = Math.max(10, current === null ? 100 : current.to - current.from)
  followLatest.value = false
  rendering = true
  const logicalIndex = detailChartIndex(chart, chartMarkerTime(value.bars[barIndex]!.barEnd, value.identity.frequency, value.bars[barIndex]!.tradingDay), barIndex)
  setRange({ from: logicalIndex - width / 2, to: logicalIndex + width / 2 })
  rendering = false
  resolvedSignalKey = key
  resolvedFocusRequestKey = requestKey
  emit('focus-resolved', signalId, props.focusRequestId)
  return true
}

function resolveSelectedSignal(): void {
  if (props.selectedSignalId !== null) revealSignal(props.selectedSignalId)
}


function firstLogicalIndex(): number {
  const bar = model.value?.bars[0]
  return chart && bar && model.value ? detailChartIndex(chart, chartMarkerTime(bar.barEnd, model.value.identity.frequency, bar.tradingDay), 0) : 0
}

function onRangeChange(range: LogicalRange | null): void {
  if (rendering || range === null) return
  if (range.from === programmaticRange?.from && range.to === programmaticRange.to) return
  projectActionLabels()
  renderVisualOverlays()
  if (!paginationArmed) return
  const length = chart ? detailChartLength(chart, model.value?.bars.length ?? 0) : 0
  followLatest.value = range.to >= length - 2
  const nearLeft = range.from < firstLogicalIndex() + 10
  if (nearLeft && !nearLeftBoundary && props.hasMoreBefore && !props.loading) emit('loadEarlier')
  nearLeftBoundary = nearLeft
}

function setRange(range: { from: number; to: number }): void {
  paginationArmed = false
  programmaticRange = range
  nearLeftBoundary = range.from < firstLogicalIndex() + 10
  chart?.timeScale().setVisibleLogicalRange(range as LogicalRange)
  armPagination()
}

function armPagination(): void {
  const finish = () => {
    paginationArmFrame = null
    const range = chart?.timeScale().getVisibleLogicalRange()
    nearLeftBoundary = range !== null && range !== undefined && range.from < firstLogicalIndex() + 10
    paginationArmed = true
    projectActionLabels()
  }
  if (typeof requestAnimationFrame === 'undefined') queueMicrotask(finish)
  else {
    if (paginationArmFrame !== null) cancelAnimationFrame(paginationArmFrame)
    paginationArmFrame = requestAnimationFrame(finish)
  }
}

function scrollToLatest(): void {
  followLatest.value = true
  paginationArmed = false
  chart?.timeScale().scrollToRealTime()
  armPagination()
}

const auxiliaryPaneKey = 'newow-selected'
const auxiliaryPane = { auxiliary: auxiliaryPaneKey } as const
let attachedAuxiliaryComponent: string | null = null
function syncAuxiliaryPane(): void {
  if (!host) return
  if (pure.value) {
    for (const [component, pane] of extraPanes) {
      host.removeAuxiliary(pane.pane.auxiliary)
      extraPanes.delete(component)
    }
    host.removeAuxiliary(auxiliaryPaneKey)
    auxiliaryLines.clear()
    auxiliaryAnchor = null
    auxiliaryZeroLine = null
    attachedAuxiliaryComponent = null
    activeAuxiliary.value = null
    renderedAuxiliaryKey = null
    return
  }
  if (auxiliaryAnchor) return
  host.addAuxiliary(auxiliaryPaneKey)
  // Whitespace pins the secondary timeline without inventing zero values.
  const axis = host.layer('auxiliary-axis', 'auxiliary_axis', auxiliaryPane)
  auxiliaryAnchor = axis.line({
    lineVisible: false, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false,
  })
  auxiliaryZeroLine = axis.priceLevel(auxiliaryAnchor, {
    price: 0, color: '#D0D5DD', lineWidth: 1, lineStyle: 2, axisLabelVisible: false,
  })
}
type SpecializedAuxiliary = NewowZhaoyaoMirrorPrimitive | NewowUpDownEnergyPrimitive | NewowMainForceControlPrimitive | NewowTrendReversalPrimitive
const reversalMarks = computed(() => {
  const value = model.value
  const response = props.auxiliaryResponse?.value
  return value && auxiliaryModel.value?.component === 'trend_reversal' && response?.component === 'trend_reversal'
    ? buildNewowTrendReversalMarks(value, response.segments) : []
})
const primitives = {
  zhaoyao_mirror: zhaoyaoMirror, up_down_energy: upDownEnergy, main_force_control: mainForceControl, trend_reversal: trendReversal,
}
const mirrorEvents = computed(() => (props.response?.value?.caution_events ?? []).flatMap(event => {
  const main = model.value
  const bar = event.detail_visible ? main?.bars.find(item => item.barEnd === event.bar_end) : undefined
  return main && bar ? [{ time: chartMarkerTime(bar.barEnd, main.identity.frequency, bar.tradingDay), tentative: event.tentative, state: event.display_state }] : []
}))
function updateAuxiliaryPrimitive(
  primitive: SpecializedAuxiliary,
  value: ReturnType<typeof alignNewowAuxiliaryChartModel>,
  response: NewowProductSectionResponse<'auxiliary'> | null | undefined,
  topInset: number,
) {
  const series = value?.series ?? []
  const main = model.value
  if (primitive instanceof NewowZhaoyaoMirrorPrimitive) primitive.setData(buildNewowZhaoyaoMirrorData(series, mirrorEvents.value), topInset)
  else if (primitive instanceof NewowUpDownEnergyPrimitive) primitive.setData(buildNewowUpDownEnergyData(series, main?.bars ?? []), topInset)
  else if (primitive instanceof NewowMainForceControlPrimitive) primitive.setData(response?.value?.component === 'main_force_control' ? buildNewowMainForceData(series, response.value.segments) : [], topInset)
  else primitive.setData(buildNewowTrendReversalData(series), topInset, main && response?.value?.component === 'trend_reversal' ? buildNewowTrendReversalMarks(main, response.value.segments) : [])
}

const primitiveConstructors = {
  zhaoyao_mirror: NewowZhaoyaoMirrorPrimitive, up_down_energy: NewowUpDownEnergyPrimitive,
  main_force_control: NewowMainForceControlPrimitive, trend_reversal: NewowTrendReversalPrimitive,
}
const extraPanes = new Map<NewowAuxiliaryPaneComponent, {
  pane: { auxiliary: string }; layer: ChartLayer; anchor: ISeriesApi<'Line'>; primitive: SpecializedAuxiliary | null;
  lines: AuxiliaryLines; snapshot: string | null;
}>()
function renderExtraAuxiliaries() {
  if (!host) return
  const panes = pure.value ? [] : props.extraAuxiliaryPanes ?? []
  const active = new Set(panes.map(pane => pane.component))
  for (const [component, existing] of extraPanes) {
    if (active.has(component)) continue
    host.removeAuxiliary(existing.pane.auxiliary)
    extraPanes.delete(component)
  }
  const main = model.value
  for (const item of panes) {
    const id = newowPaneId(item.component)
    let current = extraPanes.get(item.component)
    if (!current) {
      const pane = host.addAuxiliary(id)
      const axis = host.layer(`${id}:axis`, 'auxiliary_axis', pane)
      const layer = host.layer(id, id, pane)
      const anchor = axis.line({ lineVisible: false, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false })
      const primitive = item.component === 'macd' ? null : layer.primitive(anchor, new primitiveConstructors[item.component]())
      if (item.component === 'macd') axis.priceLevel(anchor, { price: 0, color: '#D0D5DD', lineWidth: 1, lineStyle: 2, axisLabelVisible: false })
      current = { pane, layer, anchor, primitive, lines: new Map(), snapshot: null }
      extraPanes.set(item.component, current)
    }
    const aligned = alignNewowAuxiliaryChartModel(props.response, item.response)
    const value = aligned?.component === item.component ? aligned : null
    const height = item.height ?? 120
    const key = JSON.stringify([newowChartSnapshotKey(props.response), main?.bars[0]?.barEnd, main?.bars.at(-1)?.barEnd, value, mirrorEvents.value, height, pageTheme.value])
    if (current.snapshot !== key) {
      current.anchor.setData(main?.bars.map(bar => ({ time: chartMarkerTime(bar.barEnd, main.identity.frequency, bar.tradingDay) })) ?? [])
      if (current.primitive) updateAuxiliaryPrimitive(current.primitive, value, value ? item.response : null, 20)
      else renderMacdLines(current.layer, current.lines, value, 20 / height)
      current.snapshot = key
    }
    const readiness = projectNewowAuxiliaryReadiness(item.response?.value, props.response?.value?.bars.at(-1))
    const hasPoints = value?.series.some(series => series.points.length > 0) ?? false
    current.layer.updateDiagnostics({
      status: newowAuxiliaryLayerStatus(item.lifecycle, Boolean(item.response?.value), value !== null, readiness?.currentStatus ?? null, hasPoints, item.error),
      sourceIdentity: item.response?.meta.data_revision_identity ?? item.response?.meta.input_content_sha256 ?? null,
      formulaVersion: item.response?.value?.formula_version ?? null,
      frequency: main?.identity.frequency ?? null, dataCutoff: item.response?.meta.as_of ?? null, lastError: item.error,
    })
  }
  if (!pure.value && auxiliaryAnchor) host.orderAuxiliaries([auxiliaryPaneKey, ...panes.map(item => newowPaneId(item.component))])
}

function positionPaneHeaders(): void {
  if (!chart || !host || !container.value) return
  const nativePanes = chart.panes()
  const nativeTop = container.value.offsetTop
  const containerTop = container.value.getBoundingClientRect?.().top ?? null
  const offset = (index: number) => {
    const row = nativePanes[index]?.getHTMLElement?.()
    return nativeTop + (row && containerTop !== null ? row.getBoundingClientRect().top - containerTop
      : nativePanes.slice(0, index).reduce((sum, pane) => sum + pane.getHeight(), 0))
  }
  auxiliaryTop.value = offset(1)
  extraPaneHeaders.value = [...extraPanes]
    .sort(([, left], [, right]) => host!.paneIndex(left.pane) - host!.paneIndex(right.pane))
    .map(([component, pane]) => {
      const diagnostic = pane.layer.inspect()
      return {
        component, title: DISPLAY_CATALOG[newowPaneId(component)]!.label,
        top: offset(host!.paneIndex(pane.pane)), status: diagnostic.status, formulaVersion: diagnostic.formulaVersion,
      }
    })
}

function resize(): void {
  if (!chart || !host || !container.value) return
  const layout = newowAuxiliaryPaneLayout(container.value.clientHeight, auxiliaryToolbar.value?.offsetHeight ?? 0)
  renderExtraAuxiliaries()
  chart.panes()[0]!.setStretchFactor(Math.max(200, layout.mainHeight - extraPaneHeight.value))
  chart.panes()[1]?.setStretchFactor(layout.auxiliaryHeight)
  for (const [component, pane] of extraPanes) {
    const height = props.extraAuxiliaryPanes?.find(item => item.component === component)?.height ?? 120
    chart.panes()[host.paneIndex(pane.pane)]?.setStretchFactor(height)
  }
  chart.resize(container.value.clientWidth, container.value.clientHeight, true)
  positionPaneHeaders()
  // Swapping panes updates the native DOM on the chart's next frame.
  if (extraPanes.size && paneHeaderFrame === null) {
    paneHeaderFrame = requestAnimationFrame(() => { paneHeaderFrame = null; positionPaneHeaders() })
  }
  renderAuxiliary()
  projectActionLabels()
}

let renderedAuxiliaryKey: string | null = null
function renderAuxiliary(): void {
  if (!host || !auxiliaryAnchor || pure.value) return
  const value = auxiliaryPresentation.value.showRetainedValue ? auxiliaryModel.value : null
  // A strategy switch does not revoke the last accepted market indicator.
  // The new generation must prove compatibility before it can replace this layer.
  if (value === null && (props.strategySwitching || props.auxiliaryLifecycle === 'loading')) return
  const component = value?.component ?? null
  if (component !== attachedAuxiliaryComponent) {
    host.removeLayer('auxiliary-selected')
    auxiliaryLines.clear()
    attachedAuxiliaryComponent = component
    renderedAuxiliaryKey = null
  }
  const primitive = component && component in primitives ? primitives[component as keyof typeof primitives] : null
  const displayId = primitive ? `newow.${component}` : component === 'macd' ? 'macd' : null
  const layer = displayId ? host.layer('auxiliary-selected', displayId, auxiliaryPane) : null
  if (primitive && layer && renderedAuxiliaryKey === null) layer.primitive(auxiliaryAnchor, primitive)
  const response = props.auxiliaryResponse
  const readiness = auxiliaryReadiness.value
  layer?.updateDiagnostics({
    sourceIdentity: response?.meta.data_revision_identity ?? response?.meta.input_content_sha256 ?? null,
    formulaVersion: response?.value?.formula_version ?? null,
    frequency: response?.meta.identity.frequency ?? props.priceFrequency ?? null,
    status: newowAuxiliaryLayerStatus(props.auxiliaryLifecycle ?? 'not_requested', Boolean(response?.value), value !== null,
      readiness?.currentStatus ?? null, value?.series.some(series => series.points.length > 0) ?? false, props.auxiliaryError ?? null),
    dataCutoff: response?.meta.as_of ?? null,
    lastError: props.auxiliaryError ?? null,
  })
  activeAuxiliary.value = layer?.inspect() ?? null
  auxiliaryZeroLine?.applyOptions({ color: primitive ? 'rgba(0, 0, 0, 0)' : '#D0D5DD' })
  const { topInset, auxiliaryHeight } = newowAuxiliaryPaneLayout(container.value?.clientHeight ?? 700, auxiliaryToolbar.value?.offsetHeight ?? 0)
  const nextKey = JSON.stringify([value, topInset, auxiliaryHeight, mirrorEvents.value, primitive ? model.value?.bars : null])
  if (nextKey === renderedAuxiliaryKey) return
  renderedAuxiliaryKey = nextKey
  if (primitive) updateAuxiliaryPrimitive(primitive, value, response, topInset)
  if (layer && component === 'macd') renderMacdLines(layer, auxiliaryLines, value, topInset / auxiliaryHeight)
}

function renderMacdLines(
  layer: ChartLayer,
  lines: AuxiliaryLines,
  value: ReturnType<typeof alignNewowAuxiliaryChartModel>,
  topMargin: number,
): void {
  const theme = resolveChartTheme(container.value ?? document.documentElement)
  const active = new Set<string>()
  for (const item of value?.series ?? []) {
    const id = item.id
    active.add(id)
    let series = lines.get(id)
    const histogram = item.key === 'histogram'
    if (!series) {
      const options = { color: item.key === 'dif' ? '#FF6B2C' : '#365AF5', lineWidth: 1 as const, lastValueVisible: false, priceLineVisible: false,
        autoscaleInfoProvider: (base: () => import('lightweight-charts').AutoscaleInfo | null) => {
          const info = base()
          return info?.priceRange == null ? info : { ...info, priceRange: { minValue: Math.min(0, info.priceRange.minValue), maxValue: Math.max(0, info.priceRange.maxValue) } }
        },
      }
      series = histogram ? layer.histogram(options) : layer.line(options)
      lines.set(id, series)
    }
    series.priceScale().applyOptions({ scaleMargins: { top: topMargin, bottom: 0.06 } })
    series.setData(item.points.map(point => ({ time: point.time, value: point.value,
      ...(histogram ? { color: point.value >= 0 ? theme.volumeUp : theme.volumeDown } : {}),
    })))
  }
  for (const [id, series] of lines) {
    if (active.has(id)) continue
    layer.remove(series)
    lines.delete(id)
  }
}

function onFullscreenChange(): void {
  fullscreen.value = document.fullscreenElement === stageRoot.value
  resize()
}


function inspectLayers() { return host?.diagnostics() ?? [] }

defineExpose({ revealSignal, scrollToLatest, inspectLayers })
</script>

<template>
  <section
    ref="stageRoot"
    :aria-busy="loading"
    class="newow-product-chart-stage"
    :data-auxiliary-component="auxiliaryModel?.component ?? ''"
    :data-auxiliary-state="auxiliaryPresentation.mode"
    :data-chart-package="activeAuxiliary?.packageVersion"
    :data-auxiliary-indicator="activeAuxiliary?.indicatorId"
    :data-auxiliary-renderer="activeAuxiliary?.renderer"
    :data-auxiliary-formula="activeAuxiliary?.formulaVersion"
    :data-auxiliary-cutoff="activeAuxiliary?.dataCutoff"
    :data-volume-policy="volume ? 'newow' : undefined"
    :data-volume-bar-count="volumeBars.filter(validVolume).length"
    :data-band-area-count="model?.bandAreas.length ?? 0"
    :data-channel-point-count="model?.channelPoints.length ?? 0"
    data-testid="newow-product-chart-stage"
    :data-strategy="strategy"
    :data-comparison-active="comparisonActive"
    :data-theme="pageTheme"
    :data-pure-mode="pure"
    :data-extrema-count="marks.filter(mark => mark.kind === 'extremum').length"
    :data-nine-turn-count="marks.filter(mark => mark.kind === 'nine').length"
    :data-reversal-confirmation-count="pure ? 0 : reversalMarks.length"
    :data-frequency="model?.identity.frequency ?? ''"
    :data-selected-signal-id="selectedSignalId ?? ''"
    :data-action-ids="model?.actions.map((action) => action.id).join(',') ?? ''"
  >
    <ChartReferenceToolbar :target-price="targetPrice" :absorb-price="absorbPrice" :status="referencePriceStatus">
        <slot name="frequency-controls" />
        <slot name="reference-controls" />
        <button type="button" class="newow-settings-trigger" aria-haspopup="dialog" :aria-expanded="settingsOpen" @click="settingsOpen = true">图表设置</button>
        <details v-if="showTools" class="newow-product-chart-stage__tools">
          <summary>图表工具</summary>
          <div class="newow-product-chart-stage__tools-body">
            <slot name="main-controls" />
            <div v-if="!comparisonActive" class="newow-product-chart-stage__legend" aria-label="Newow 主图图例">
              <button class="newow-product-chart-stage__main-legend" type="button" @click="emit('explain-main')">{{ mainLegendLabel }}<span v-for="line in legend" :key="line.key" :style="{ color: mainLineColors[line.key] }">{{ line.label }}</span>ⓘ</button>
              <details v-if="!pure && showHints && model?.hints.length"><summary>过程提示</summary><button v-for="hint in model.hints" :key="hint.id" type="button" :data-hint-id="hint.id" :data-hint-tone="hint.tone" @click="emit('select-hint', hint.id)"><span class="newow-product-chart-stage__hint-kind" :class="`is-${hint.tone}`">{{ hint.kind }}</span> · {{ hint.barEnd }}</button></details>
            </div>
            <div class="newow-product-chart-stage__controls">
              <button v-if="!followLatest" type="button" @click="scrollToLatest">回到最新</button>
            </div>
            <p v-if="!comparisonActive && referenceTradesComplete === false" class="newow-product-chart-stage__reference-record-status" role="status">单笔参考收益仅显示已核对记录；未显示收益不代表没有交易。下方参考记录可按需加载。</p>
          </div>
        </details>
    </ChartReferenceToolbar>
    <p v-if="!comparisonActive && referenceStatsError" class="newow-product-chart-stage__reference-record-status" role="status">清仓参考收益读取未完成：{{ referenceStatsError }} <button type="button" :disabled="referenceStatsLoading" @click="emit('load-reference-stats')">重试</button></p>
    <div v-if="comparisonActive" class="newow-product-chart-stage__dual-summary" aria-label="双策略本视图摘要" :title="referenceTradesComplete === false ? '历史记录按需分页，未证明覆盖全部图表信号；仅显示已核对单笔。' : `统计仅含已绘制清仓标签对应的 ${comparisonStats.samples} 笔已完成参考交易，不含融合配对收益`">主导：{{ comparisonDominant === 'trend' ? '趋势' : comparisonDominant === 'oscillation' ? '震荡' : '—' }} · 上=趋势 下=震荡 · 本视图 {{ comparisonStats.count }} 个信号 · <template v-if="referenceTradesComplete !== false">平均盈亏 {{ comparisonStats.average }} · 胜率 {{ comparisonStats.winRate }} · 最大 {{ comparisonStats.maximum }}</template><template v-else>参考收益需完整记录，当前不显示统计 <button type="button" :disabled="referenceStatsLoading" @click="emit('load-reference-stats')">{{ referenceStatsLoading ? '正在核对完整记录…' : '读取完整参考统计' }}</button><span v-if="referenceStatsError" role="alert">{{ referenceStatsError }}</span></template> · 背景深色=趋势蓝带</div>
    <NewowChartSettings :open="settingsOpen" :identity-key="settingsIdentity"
      v-model:annotations="annotations" v-model:overlays="visualOverlays" :layers="layers"
      :dual="comparisonActive" :oscillation="strategy === 'oscillation' || comparisonActive"
      @update:layers="updateLayers" @close="settingsOpen = false" @analyze="analyzeChannel" />
    <details v-if="response?.value?.price_unavailable_days.length" class="newow-product-chart-stage__quality-gaps" data-testid="newow-chart-price-gaps">
      <summary>日线来源价格不可用 {{ response.value.price_unavailable_days.length }} 日；指标已分段重算</summary>
      <ul><li v-for="gap in response.value.price_unavailable_days" :key="`${gap.segment_id}:${gap.trading_day}`">{{ gap.trading_day }} · {{ gap.physical_contract }} · 无可用开高低价；未生成 K 线或交易信号</li></ul>
    </details>
    <div
      ref="container"
      :style="{ '--extra-pane-height': `${extraPaneHeight}px` }"
      class="newow-product-chart-stage__chart"
      @pointermove="scheduleActionProjection"
      @pointerup="scheduleActionProjection"
      @wheel="scheduleActionProjection"
      @dblclick="scheduleActionProjection"
    />
    <NewowBreakoutOverlay :points="breakoutPoints" :width="actionOverlayWidth" :height="actionOverlayHeight" :shapes="showBreakoutShapes" :wicks="showBreakoutWicks" :style="{left:actionOverlayLeft+'px',top:actionOverlayTop+'px'}" @select-breakout="emit('select-breakout',$event)" />
    <NewowDisplayOverlay :points="displayPoints" :width="actionOverlayWidth" :height="actionOverlayHeight" :style="{left:actionOverlayLeft+'px',top:actionOverlayTop+'px'}" @select-display="emit('select-display',$event)" />
    <div class="newow-caution-overlay" :class="{dark:pageTheme==='dark'}" :style="{ left: `${actionOverlayLeft}px`, top: `${actionOverlayTop}px`, width: `${actionOverlayWidth}px`, height: `${actionOverlayHeight}px` }" aria-label="小心：历史回看提示，会重绘，非交易信号">
      <button v-for="item in cautionOverlays" :key="item.key" type="button" data-testid="newow-caution-trigger" :class="{ tentative: item.tentative, invalidated: item.state === 'invalidated' }" :style="{left:`${item.x}px`,top:`${item.y}px`}" :title="item.title" :aria-label="item.title" :aria-expanded="selectedCautionKey === item.key" @pointerdown.stop @click.stop="selectedCautionKey = selectedCautionKey === item.key ? null : item.key" @keydown.esc.stop="selectedCautionKey = null"><svg class="caution-capsule" aria-hidden="true" width="32" height="16" viewBox="0 0 32 16"><rect x="0" y="0" width="32" height="16" rx="8" /><line v-if="item.state === 'invalidated'" class="caution-withdrawal" x1="3" y1="13" x2="29" y2="3" /></svg><svg class="caution-leader" aria-hidden="true" width="32" height="10" viewBox="0 0 32 10"><line :x1="item.stemX" y1="0" :x2="item.stemX" :y2="item.stemEnd" :stroke-dasharray="item.tentative || item.state === 'invalidated' ? '1 3' : '3 3'" /></svg><span>小心</span></button>
    </div>
    <aside v-if="selectedCaution" class="newow-caution-explanation" data-testid="newow-caution-explanation" role="region" aria-label="小心说明" @pointerdown.stop @keydown.esc.stop="selectedCautionKey = null">
      <header><strong>{{ cautionStateLabel(selectedCaution.state) }}</strong><button type="button" aria-label="关闭小心说明" @click="selectedCautionKey = null">关闭</button></header>
      <p>{{ selectedCaution.title }}</p>
    </aside>
    <div v-if="showHints && (processOverlays.length || cycleCountOverlays.length)" class="newow-process-overlay" :style="{ left: `${actionOverlayLeft}px`, top: `${actionOverlayTop}px`, width: `${actionOverlayWidth}px`, height: `${actionOverlayHeight}px` }" aria-label="主图过程提示，非成交">
      <i v-for="item in cycleCountOverlays" :key="item.barEnd" class="newow-cycle-count" :data-cycle-count-bar="item.barEnd" :style="{ left: `${item.x}px`, top: `${item.top}px`, height: `${item.height}px`, background: item.color }" />
      <NewowMainRiseProcessLabels v-if="strategy==='main_rise'" :points="processOverlays" :width="actionOverlayWidth" :height="actionOverlayHeight" :dark="pageTheme==='dark'" />
      <span v-for="item in processOverlays" :key="item.id" :data-process-hint-id="item.id" :data-hint-kind="item.kind" :data-anchor-price="item.anchorPrice" :class="{ below: item.below, cycle: item.cycle, 'canvas-only':strategy==='main_rise' }" :style="{ left: `${item.x}px`, top: `${item.y}px`, color: item.color }">{{ item.text }}</span>
    </div>
    <div v-if="showHints && attackOverlays.length" class="newow-attack-overlay" :style="{ left: `${actionOverlayLeft}px`, top: `${actionOverlayTop}px`, width: `${actionOverlayWidth}px`, height: `${actionOverlayHeight}px` }" aria-label="震荡辅助攻击线提示">
      <span v-for="item in attackOverlays" :key="item.id" :data-hint-kind="item.kind" :style="{ left: `${item.x}px`, top: `${item.y}px`, width: item.kind === 'OSCILLATION_J' ? '12px' : `${item.width}px`, height: item.kind === 'OSCILLATION_J' ? '14px' : `${item.height}px` }" :class="item.kind">{{ item.kind === 'OSCILLATION_J' ? 'J' : '' }}</span>
    </div>
    <div
      v-if="!pure && !comparisonActive && showActions && detailLabels && model?.actions.length"
      class="newow-product-chart-stage__action-callouts"
      :style="{ left: `${actionOverlayLeft}px`, top: `${actionOverlayTop}px`, width: `${actionOverlayWidth}px`, height: `${actionOverlayHeight}px` }"
      aria-label="策略参考动作"
    >
      <ReferenceCalloutLabels :items="positionedActions.map(item => ({ position: item, title: actionTitle(item.callout), detail: actionDisplay(item.callout).text, direction: actionDisplay(item.callout).direction, selected: selectedSignalId === item.callout.id, labelClass: 'newow-product-chart-stage__action-label', ariaLabel: `${actionTitle(item.callout)}，${actionDisplay(item.callout).text}，策略参考动作`, tooltip: `${actionTitle(item.callout)} · ${actionDisplay(item.callout).text} · ${item.callout.time} · ${item.callout.physicalContract} · ${item.callout.id}` }))" />
    </div>
    <div v-if="!pure && comparisonActive" class="newow-product-chart-stage__action-callouts newow-product-chart-stage__dual-tracks" :style="{ left: `${actionOverlayLeft}px`, top: `${actionOverlayTop}px`, width: `${actionOverlayWidth}px`, height: `${actionOverlayHeight}px` }" aria-label="趋势与震荡双策略叠加">
      <svg aria-hidden="true"><line v-for="(item,index) in comparisonSwitches" :key="`switch:${index}`" :x1="item.x" y1="20" :x2="item.x" :y2="actionOverlayHeight" stroke-dasharray="4 3" class="dual-switch-line" /><polyline v-for="item in positionedComparison" :key="`${item.origin}:${item.callout.id}`" :points="`${item.x},${item.y} ${item.x},${(item.y + item.lineY) / 2} ${item.lineX},${(item.y + item.lineY) / 2} ${item.lineX},${item.lineY}`" fill="none" /><circle v-for="item in positionedComparison" :key="`anchor:${item.origin}:${item.callout.id}`" :cx="item.x" :cy="item.y" r="2.5" :fill="item.callout.above ? '#34c759' : '#ff3b30'" stroke="none" /></svg>
      <div v-for="(item,index) in comparisonSwitches" :key="index" class="newow-product-chart-stage__dual-switch" :style="{ left: `${item.x}px` }" :title="`${item.from === 'trend' ? '趋势' : '震荡'}切换至${item.to === 'trend' ? '趋势' : '震荡'}，仅主图展示主导策略`"><b :class="item.from">{{ item.from === 'trend' ? '趋' : '震' }}</b><span>⇄</span><b :class="item.to">{{ item.to === 'trend' ? '趋' : '震' }}</b></div>
      <ReferenceCalloutLabels :draw-lines="false" :items="positionedComparison.map(item => ({ position: item, title: dualStepTitle(detailLabels ? actionTitle(item.callout, item.origin) : newowSimpleDualLabel(item.origin, item.callout.above, item.callout.price), item.callout.id), detail: detailLabels ? actionDisplay(item.callout, item.origin).text : undefined, unpaired: item.callout.title.includes('无入场'), direction: actionDisplay(item.callout, item.origin).direction, origin: item.origin, labelClass: 'newow-product-chart-stage__action-label', ariaLabel: `${dualStepDescription(item.callout.id)}${item.origin === 'trend' ? '趋势策略' : '震荡策略'}，${actionTitle(item.callout, item.origin)}，${actionDisplay(item.callout, item.origin).text}，${item.callout.time}，${item.callout.physicalContract}`, tooltip: `${dualStepDescription(item.callout.id)}${item.origin === 'trend' ? '趋势策略' : '震荡策略'} · ${actionTitle(item.callout, item.origin)} · ${actionDisplay(item.callout, item.origin).text} · ${item.callout.time} · ${item.callout.physicalContract} · ${item.callout.id}` }))" />
    </div>
    <aside v-if="!pure && cursorRows.length" class="newow-product-chart-stage__cursor-card" :style="{ top: `${cursorTop}px` }" aria-label="同一时间主副图读数"><div v-for="(row, index) in cursorRows" :key="index">{{ row }}</div></aside>
    <div v-show="!pure" ref="auxiliaryToolbar" class="newow-product-chart-stage__auxiliary-toolbar" :style="{ top: `${auxiliaryTop}px` }"><slot name="auxiliary-controls" :diagnostic="activeAuxiliary" :inspect-layers="inspectLayers"><button @click="emit('explain-auxiliary')">{{ auxiliaryModel?.component === 'macd' ? 'MACD · DIF / DEA' : '辅助指标' }} ⓘ</button></slot></div>
    <div v-for="pane in extraPaneHeaders" v-show="!pure" :key="pane.component" class="newow-product-chart-stage__extra-header" :style="{ top: `${pane.top}px` }" :data-auxiliary-pane="pane.component" :data-auxiliary-status="pane.status" :data-auxiliary-formula="pane.formulaVersion">
      {{ pane.title }}<span v-if="pane.status !== 'ready'"> · {{ extraStatusMessages[pane.status] ?? pane.status }}</span>
      <span v-if="pane.component === 'zhaoyao_mirror'"> · 回看重绘</span>
    </div>
    <p v-if="fullscreenError || (!pure && auxiliaryPresentation.message && auxiliaryPresentation.message !== '当前可计算')" class="newow-product-chart-stage__auxiliary-status" role="status">{{ fullscreenError ?? auxiliaryPresentation.message }}</p>
    <p v-if="loading && response === null" class="newow-product-chart-stage__status" role="status">{{ strategySwitching ? '正在切换策略，更新指标与信号…' : '正在读取 Newow 主图…' }}</p>
    <p v-else-if="response?.value === null" class="newow-product-chart-stage__status" role="status">当前组合主图不可用。</p>
    <p v-else-if="model?.bars.length === 0" class="newow-product-chart-stage__status" role="status">当前窗口没有已完成 Bar。</p>
  </section>
</template>

<style scoped>
.newow-settings-trigger { min-height: 30px; padding: 0 9px; white-space: nowrap; border: 1px solid var(--gy-newow-overlay-border); border-radius: 6px; background: var(--gy-newow-overlay-control-bg); color: var(--gy-newow-overlay-control-text); cursor: pointer; }
.newow-caution-overlay{position:absolute;pointer-events:none;z-index:8}.newow-caution-overlay button{position:absolute;transform:translateX(-50%);box-sizing:border-box;white-space:nowrap;pointer-events:auto;cursor:pointer}

.newow-product-chart-stage__tools > summary { min-height:22px; padding:0 6px; line-height:22px; cursor:pointer; white-space:nowrap; }
.newow-product-chart-stage__tools-body { position:absolute; right:0; top:100%; width:min(560px,calc(100vw - 48px)); padding:8px; border:1px solid var(--gy-border); border-radius:6px; background:var(--gy-bg-panel); box-shadow:0 4px 14px #0002; font-weight:400; }

.newow-product-chart-stage { --gy-chart-bg:var(--gy-bg-panel); --gy-chart-text:var(--gy-text-muted); --gy-chart-grid:#F2F4F7; --gy-chart-axis:#EBEDF0; --gy-up:#FF403A; --gy-down:#22B95D; position:relative; min-width:0; height:auto; min-height:clamp(580px, 70vh, 920px); display:flex; flex-direction:column; border:1px solid #ebedf0; background:var(--gy-bg-panel); }
.newow-product-chart-stage:fullscreen { height:100vh; width:100vw; padding:12px; box-sizing:border-box; }
.newow-product-chart-stage:fullscreen .newow-product-chart-stage__chart { height:0; flex:1 1 auto; min-height:0; }
.newow-product-chart-stage__chart { width:100%; flex:1 0 auto; height:calc(clamp(400px,48vh,650px) + 350px + var(--extra-pane-height, 0px)); min-height:690px; }
.newow-product-chart-stage__action-callouts { position:absolute; pointer-events:none; z-index:9; overflow:hidden; }
.newow-product-chart-stage__action-callouts svg { width:100%; height:100%; position:absolute; inset:0; stroke:#9B8169; stroke-width:1; }
.newow-product-chart-stage__dual-summary { display:flex; align-items:center; flex-wrap:wrap; gap:4px 12px; margin:0; padding:3px 12px 7px; background:#fafafa; color:var(--gy-text-muted); font-size:11px; font-weight:600; line-height:1.5; }
.newow-product-chart-stage__reference-record-status { margin:0; padding:2px 12px; color:var(--gy-text-muted); font-size:10px; }
.newow-product-chart-stage__dual-layer-menu { position:absolute; top:100%; right:0; min-width:128px; padding:4px; border:1px solid #ebedf0; border-radius:4px; background:var(--gy-bg-panel); box-shadow:0 6px 18px #20242b14; }
.newow-product-chart-stage__dual-layer-menu button { display:block; width:100%; text-align:left; white-space:nowrap; }
.newow-product-chart-stage__dual-layer-menu button[aria-pressed="true"] { color:#ff6b35; }
.newow-product-chart-stage__dual-switch { position:absolute; top:1px; transform:translateX(-50%); display:flex; height:16px; border-radius:4px; overflow:hidden; color:white; font-size:10px; line-height:16px; }
.newow-product-chart-stage__dual-switch b { padding:0 3px; }.newow-product-chart-stage__dual-switch .trend { background:#0a84ff; }.newow-product-chart-stage__dual-switch .oscillation { background:#ff9500; }.newow-product-chart-stage__dual-switch span { padding:0 2px; background:#666; }
.newow-product-chart-stage__dual-tracks .dual-switch-line { stroke:var(--gy-text-muted); }
.newow-product-chart-stage__toolbar { display:flex; flex-wrap:wrap; justify-content:space-between; gap:8px; min-height:48px; flex-shrink:0; border-bottom:1px solid #ebedf0; padding:0 8px; }
.newow-product-chart-stage__controls,.newow-product-chart-stage__legend { display:flex; flex-wrap:wrap; align-items:center; gap:8px; min-width:0; }
button,summary { min-height:44px; padding:0 10px; border:0; color:var(--gy-text-muted); background:var(--gy-bg-panel); cursor:pointer; font-size:12px; flex-shrink:0; white-space:nowrap; }
.newow-product-chart-stage__main-legend { display:flex; align-items:center; gap:6px; }
button:focus-visible,summary:focus-visible { outline:2px solid #365af5; outline-offset:2px; }
summary { display:flex; align-items:center; }
.newow-product-chart-stage__cursor-card { position:absolute; right:76px; z-index:6; max-width:calc(100% - 100px); padding:8px 10px; border:1px solid #ebedf0; border-radius:8px; background:#ffffffed; color:var(--gy-text-muted); font-size:11px; line-height:18px; pointer-events:none; box-shadow:0 2px 8px #0000000a; }
.newow-product-chart-stage__auxiliary-toolbar { position:absolute; left:1px; right:70px; min-height:32px; background:var(--gy-bg-panel); z-index:3; }
details { position:relative; } details[open] { z-index:6; } details[open] > button { display:block; white-space:nowrap; }
.newow-product-chart-stage__legend details[open] { position:absolute; top:0; left:90px; max-height:240px; max-width:calc(100% - 100px); overflow:auto; border:1px solid #ebedf0; background:var(--gy-bg-panel); box-shadow:0 8px 24px #20242b14; }
.newow-product-chart-stage__hint-kind { display:inline-flex; min-width:28px; justify-content:center; border:1px solid currentColor; border-radius:3px; padding:2px 5px; font-weight:600; }
.newow-product-chart-stage__hint-kind.is-risk { color:#DC2626; }
.newow-product-chart-stage__hint-kind.is-entry { color:#16A34A; }
.newow-product-chart-stage__hint-kind.is-cycle { color:#D97706; }
.newow-product-chart-stage__hint-kind.is-neutral { color:#64748B; }
.newow-product-chart-stage__extra-header { position: absolute; left: 8px; z-index: 3; height: 20px; color: var(--gy-text-muted); background: var(--gy-bg-panel); font-size: 11px; pointer-events: none; }
.newow-product-chart-stage__auxiliary-status { margin:0; padding:6px 12px; color:#b45309; font-size:12px; }
.newow-product-chart-stage__status { position:absolute; z-index:5; top:64px; left:12px; margin:0; color:#b45309; background:var(--gy-bg-panel); }
@media(max-width:640px) { .newow-product-chart-stage { height:auto; } .newow-product-chart-stage__chart { height:calc(700px + var(--extra-pane-height, 0px)); min-height:700px; } }
</style>

<style scoped>
.newow-process-overlay { position:absolute; pointer-events:none; overflow:hidden; z-index:3; }
.newow-cycle-count { position:absolute; width:1.5px; transform:translateX(-50%); opacity:.6; }
.newow-process-overlay span { position:absolute; transform:translate(-50%,-100%); white-space:nowrap; font:15px Arial,sans-serif; line-height:18px; }
.newow-process-overlay span.below { transform:translateX(-50%); }
.newow-process-overlay span.cycle { font-size:18px; line-height:21px; font-weight:700; }
.newow-process-overlay span.canvas-only{width:1px;height:1px;overflow:hidden;clip-path:inset(50%)}
.newow-attack-overlay { position:absolute; pointer-events:none; overflow:hidden; z-index:3; }
.newow-attack-overlay span { position:absolute; transform:translateX(-50%); box-sizing:border-box; }
.newow-attack-overlay .ZLGJ_BUY { background:#f00; border:1px solid white; }
.newow-attack-overlay .ZLGJ_SELL { background:#0f0; border:1px solid white; }
.newow-attack-overlay .OSCILLATION_J { color:#34c759; text-align:center; font:600 10px -apple-system,sans-serif; }
</style>

<style scoped>
.newow-caution-overlay button{width:32px;min-width:32px;max-width:none;height:16px;min-height:16px;max-height:16px;padding:0;border:0;border-radius:8px;background:transparent;color:#003300;overflow:visible;font:700 10px/16px -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif;text-align:center}
.newow-caution-overlay button>span{position:relative;top:.5px;z-index:1}
.newow-caution-overlay .caution-capsule{position:absolute;left:0;top:0;overflow:visible;pointer-events:none}
.newow-caution-overlay .caution-capsule rect{fill:#00FF00;stroke:none}
.newow-caution-overlay .caution-leader{position:absolute;left:0;top:16px;overflow:visible;pointer-events:none}
.newow-caution-overlay .caution-leader line{stroke:#00FF00;stroke-width:1}
.newow-caution-overlay button.tentative{color:#00A03E}
.newow-caution-overlay .tentative .caution-capsule rect{fill:rgba(0,230,118,.08);stroke:#00A03E;stroke-width:1.5;stroke-dasharray:3 2}
.newow-caution-overlay.dark button.tentative{color:#00E676}
.newow-caution-overlay.dark .tentative .caution-capsule rect{stroke:#00E676}
.newow-caution-overlay button.invalidated{color:#C7D4E8}
.newow-caution-overlay .invalidated .caution-capsule rect{fill:rgba(159,176,200,.10);stroke:#9FB0C8;stroke-width:1.5;stroke-dasharray:2 3}
.newow-caution-overlay .invalidated .caution-leader line{stroke:#8E8E93}
.newow-caution-overlay .caution-withdrawal{stroke:rgba(159,176,200,.55);stroke-width:1}

.newow-caution-overlay button:focus-visible { outline:2px solid #365af5; outline-offset:2px; }
.newow-caution-explanation { position:absolute; top:56px; right:8px; z-index:15; max-width:min(340px,calc(100% - 16px)); box-sizing:border-box; padding:10px 12px; border:1px solid #d0d5dd; border-radius:8px; background:var(--gy-bg-panel,#fff); color:var(--gy-text-primary,#1d2939); box-shadow:0 4px 16px #0002; font-size:12px; line-height:1.6; }
.newow-caution-explanation header { display:flex; justify-content:space-between; align-items:center; gap:16px; }
.newow-caution-explanation header button { cursor:pointer; color:inherit; background:transparent; border:1px solid #d0d5dd; border-radius:4px; }
.newow-caution-explanation p { margin:8px 0 0; overflow-wrap:anywhere; }
</style>
