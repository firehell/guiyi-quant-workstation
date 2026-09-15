<script setup lang="ts">
import { computed, inject, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  LineSeries,
  HistogramSeries,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type LineData,
  type LogicalRange,
  type MouseEventParams,
  type SeriesMarker,
  type Time,
} from 'lightweight-charts'

import { NewowProductBandPrimitive } from '@/components/market/detail/newow/newowProductBandPrimitive'
import { NewowTrendChannelPrimitive } from '@/components/market/detail/newow/newowTrendChannelPrimitive'
import { NewowZhaoyaoMirrorPrimitive, buildNewowZhaoyaoMirrorData } from '@/components/market/detail/newow/newowZhaoyaoMirrorPrimitive'
import { resolveChartTheme } from '@/styles/chartTheme'
import type { NewowProductSectionResponse, NewowProductStrategy } from '@/types/newowProduct'
import { formatChartAxisTimeInShanghai, formatChartTimeInShanghai } from '@/utils/barTime'
import { initialChartLogicalRange } from '@/utils/chartViewport'
import { layoutReferenceCallouts, REFERENCE_CALLOUT_BOX, type PositionedCallout } from '@/utils/referenceCalloutLayout'
import {
  buildNewowProductChartModel,
  buildNewowActionCallouts,
  alignNewowAuxiliaryChartModel,
  resolveNewowAuxiliaryRenderState,
  chartMarkerTime,
  createNewowProductChartDisposer,
  NEWOW_PRODUCT_CHART_ADAPTER_KEY,
  preserveNewowViewport,
  productChartMarker,
  type NewowProductChartModel,
  type NewowProductResizeObserver,
} from '@/components/market/detail/newow/newowProductChartPrimitives'

const props = withDefaults(defineProps<{
  response: NewowProductSectionResponse<'chart'> | null
  strategy: NewowProductStrategy
  auxiliaryResponse?: NewowProductSectionResponse<'auxiliary'> | null
  auxiliaryLifecycle?: import('@/types/newowProduct').NewowResourceLifecycle
  auxiliaryError?: string | null
  selectedSignalId: string | null
  loading?: boolean
  hasMoreBefore?: boolean
}>(), { loading: false, hasMoreBefore: false })

const emit = defineEmits<{
  loadEarlier: []
  'select-signal': [signalId: string]
  'focus-resolved': [signalId: string]
  'select-hint': [hintId: string]
  'explain-main': []
  'explain-auxiliary': []
}>()

const stageRoot = ref<HTMLElement | null>(null)
const fullscreen = ref(false)
const fullscreenError = ref<string | null>(null)
const volumeTop = ref(0)
const auxiliaryTop = ref(0)
const actionOverlayTop = ref(0)
const actionOverlayHeight = ref(0)
const actionOverlayLeft = ref(0)
const actionOverlayWidth = ref(0)
const positionedActions = ref<PositionedCallout[]>([])
const activeActionLabel = ref<string | null>(null)
const container = ref<HTMLElement | null>(null)
const followLatest = ref(true)
const model = computed(() => props.response === null ? null : buildNewowProductChartModel(props.response))
const auxiliaryModel = computed(() => alignNewowAuxiliaryChartModel(props.response, props.auxiliaryResponse ?? null))
const auxiliaryPresentation = computed(() => resolveNewowAuxiliaryRenderState(props.auxiliaryLifecycle ?? 'not_requested', auxiliaryModel.value !== null, props.auxiliaryError ?? null))
const mainLineColors: Record<string, string> = { b: '#F59E0B', a: '#2563EB', upper: '#16A34A', lower: '#DC2626', ma35: '#F59E0B', ma45: '#2563EB' }
const legend = computed(() => [...new Map(model.value?.mainLines.map(line => [line.key, line]) ?? []).values()])
const mainLegendLabel = computed(() => ({ trend: '趋势带', oscillation: '震荡区间', main_rise: '主升浪' })[props.strategy])
const adapter = inject(NEWOW_PRODUCT_CHART_ADAPTER_KEY, {
  createChart,
  createSeriesMarkers: (series) => createSeriesMarkers(series),
  createResizeObserver: (callback) => new ResizeObserver(callback),
})

let chart: IChartApi | null = null
let candles: ISeriesApi<'Candlestick'> | null = null
let volume: ISeriesApi<'Histogram'> | null = null
const band = new NewowProductBandPrimitive()
const trendChannel = new NewowTrendChannelPrimitive()
const zhaoyaoMirror = new NewowZhaoyaoMirrorPrimitive()
let auxiliaryAnchor: ISeriesApi<'Line'> | null = null
let auxiliaryZeroLine: { applyOptions(options: { color: string }): void } | null = null
const auxiliaryLines = new Map<string, ISeriesApi<'Line'> | ISeriesApi<'Histogram'>>()
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
let actionProjectionScheduled = false
let programmaticRange: { from: number; to: number } | null = null
let resolvedSignalKey: string | null = null
const mainLines = new Map<string, ISeriesApi<'Line'>>()

onMounted(async () => {
  await nextTick()
  if (container.value === null) return
  const theme = resolveChartTheme(container.value)
  chart = adapter.createChart(container.value, {
    width: container.value.clientWidth,
    height: container.value.clientHeight,
    layout: { background: { type: ColorType.Solid, color: theme.background }, textColor: theme.text, panes: { enableResize: false, separatorColor: '#EBEDF0' } },
    grid: { vertLines: { color: theme.grid }, horzLines: { color: theme.grid } },
    rightPriceScale: { borderColor: theme.axis, scaleMargins: { top: 0.24, bottom: 0.1 } },
    localization: { timeFormatter: formatChartTimeInShanghai },
    timeScale: { borderColor: theme.axis, timeVisible: true, tickMarkFormatter: formatChartAxisTimeInShanghai },
  })
  candles = chart.addSeries(CandlestickSeries, {
    upColor: theme.candleUp, downColor: theme.candleDown,
    borderUpColor: theme.candleUp, borderDownColor: theme.candleDown,
    wickUpColor: theme.candleUp, wickDownColor: theme.candleDown,
  })
  chart.panes()[0]!.setStretchFactor(5)
  chart.addPane().setStretchFactor(1.2)
  chart.addPane().setStretchFactor(2)
  candles.attachPrimitive(band)
  candles.attachPrimitive(trendChannel)
  volume = chart.addSeries(HistogramSeries, { priceFormat: { type: 'volume' }, priceLineVisible: false, lastValueVisible: false }, 1)
  // Whitespace keeps the auxiliary pane/timeline present during loading, without inventing zero values.
  auxiliaryAnchor = chart.addSeries(LineSeries, { lineVisible: false, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false }, 2)
  auxiliaryZeroLine = auxiliaryAnchor.createPriceLine({ price: 0, color: '#D0D5DD', lineWidth: 1, lineStyle: 2, axisLabelVisible: false })
  auxiliaryAnchor.attachPrimitive(zhaoyaoMirror)
  if (typeof document !== 'undefined') document.addEventListener('fullscreenchange', onFullscreenChange)
  actionMarkers = adapter.createSeriesMarkers(candles as never)
  chart.subscribeClick(onClick)
  chart.timeScale().subscribeVisibleLogicalRangeChange(onRangeChange)
  observer = adapter.createResizeObserver(resize)
  observer.observe(container.value)
  renderModel(model.value)
  resize()
})

onUnmounted(createNewowProductChartDisposer({
  unsubscribeRange: () => chart?.timeScale().unsubscribeVisibleLogicalRangeChange(onRangeChange),
  unsubscribeClick: () => chart?.unsubscribeClick(onClick),
  disconnectResizeObserver: () => observer?.disconnect(),
  removeChart: () => {
    if (paginationArmFrame !== null) cancelAnimationFrame(paginationArmFrame)
    if (actionProjectionFrame !== null) cancelAnimationFrame(actionProjectionFrame)
    if (typeof document !== 'undefined') document.removeEventListener('fullscreenchange', onFullscreenChange)
    candles?.detachPrimitive(band)
    candles?.detachPrimitive(trendChannel)
    auxiliaryAnchor?.detachPrimitive(zhaoyaoMirror)
    chart?.remove()
    chart = null; candles = null; volume = null; auxiliaryAnchor = null; auxiliaryZeroLine = null
    mainLines.clear(); auxiliaryLines.clear()
  },
}))

watch(model, (value) => renderModel(value))
watch([auxiliaryModel, auxiliaryPresentation], renderAuxiliary)
watch(() => props.selectedSignalId, () => {
  resolvedSignalKey = null
  renderMarkers(model.value)
  resolveSelectedSignal()
  scheduleActionProjection()
}, { flush: 'post' })
watch(activeActionLabel, scheduleActionProjection)

function identityKey(value: NewowProductChartModel): string {
  return `${value.identity.product}:${value.identity.strategy}:${value.identity.frequency}`
}

function renderModel(value: NewowProductChartModel | null): void {
  if (chart === null || candles === null) return
  if (value === null) {
    paginationArmed = false
    if (renderedIdentity !== null && renderedBars.length > 0) {
      retainedVisibleRange = chart.timeScale().getVisibleLogicalRange()
    }
    candles.setData([])
    volume?.setData([])
    auxiliaryAnchor?.setData([])
    band.setData([])
    trendChannel.setData([])
    renderAuxiliary()
    for (const series of mainLines.values()) chart.removeSeries(series)
    mainLines.clear()
    actionMarkers?.setMarkers([])
    positionedActions.value = []
    activeActionLabel.value = null
    resolvedSignalKey = null
    return
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
  candles.setData(value.bars.map((bar) => ({
    time: chartMarkerTime(bar.barEnd, value.identity.frequency, bar.tradingDay),
    open: bar.open, high: bar.high, low: bar.low, close: bar.close,
  })))
  const theme = resolveChartTheme(container.value ?? document.documentElement)
  volume?.setData(value.bars.map(bar => ({ time: chartMarkerTime(bar.barEnd, value.identity.frequency, bar.tradingDay), value: bar.volume, color: bar.close >= bar.open ? theme.volumeUp : theme.volumeDown })))
  auxiliaryAnchor?.setData(value.bars.map(bar => ({ time: chartMarkerTime(bar.barEnd, value.identity.frequency, bar.tradingDay) })))
  band.setData(value.bandAreas)
  trendChannel.setData(value.channelPoints.map((point) => ({
    time: chartMarkerTime(point.barEnd, value.identity.frequency, point.tradingDay),
    upper: point.upper,
    lower: point.lower,
  })))
  renderAuxiliary()
  syncMainLines(value)
  renderMarkers(value)
  if (resetViewport || previousModel === null || renderedBars.length === 0) {
    followLatest.value = true
    resolvedSignalKey = null
    const range = initialChartLogicalRange(value.bars.length)
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
  resolveSelectedSignal()
}

function syncMainLines(value: NewowProductChartModel): void {
  if (chart === null) return
  const active = new Set(value.mainLines.map((line) => line.id))
  for (const [id, series] of mainLines) {
    if (active.has(id)) continue
    chart.removeSeries(series)
    mainLines.delete(id)
  }

  for (const line of value.mainLines) {
    let series = mainLines.get(line.id)
    if (series === undefined) {
      series = chart.addSeries(LineSeries, { color: mainLineColors[line.key] ?? '#64748B', lineWidth: value.identity.strategy === 'trend' ? 1 : 2, lastValueVisible: false, priceLineVisible: false })
      mainLines.set(line.id, series)
    }
    series.setData(line.points.map((point): LineData<Time> => ({
      time: chartMarkerTime(point.barEnd, value.identity.frequency, point.tradingDay), value: point.value,
    })))
  }
}

function renderMarkers(value: NewowProductChartModel | null): void {
  if (chart === null || actionMarkers === null || value === null) return
  const actions: SeriesMarker<Time>[] = [...value.actions]
    .sort((left, right) => Date.parse(left.barEnd) - Date.parse(right.barEnd) || (left.sequence ?? -1) - (right.sequence ?? -1))
    .map((item) => productChartMarker(
      item,
      props.selectedSignalId,
      chartMarkerTime(item.barEnd, value.identity.frequency, item.tradingDay),
    ))
  actionMarkers.setMarkers(actions)
}

function projectActionLabels(value: NewowProductChartModel | null = model.value): void {
  if (chart === null || candles === null || container.value === null || value === null) {
    positionedActions.value = []
    return
  }
  const scale = chart.timeScale()
  const timeToCoordinate = (scale as unknown as { timeToCoordinate?: (time: Time) => number | null }).timeToCoordinate
  const priceToCoordinate = (candles as unknown as { priceToCoordinate?: (price: number) => number | null }).priceToCoordinate
  if (timeToCoordinate === undefined || priceToCoordinate === undefined) {
    positionedActions.value = []
    return
  }
  const widthFn = (scale as unknown as { width?: () => number }).width
  const panesFn = (chart as unknown as { panes?: () => Array<{ getHeight?: () => number }> }).panes
  const width = widthFn?.call(scale) ?? container.value.clientWidth
  const height = panesFn?.call(chart)[0]?.getHeight?.() ?? container.value.clientHeight
  actionOverlayTop.value = container.value.offsetTop
  actionOverlayHeight.value = height
  actionOverlayLeft.value = container.value.offsetLeft
  actionOverlayWidth.value = width
  const actionById = new Map(value.actions.map(action => [action.id, action]))
  positionedActions.value = layoutReferenceCallouts(buildNewowActionCallouts(value).flatMap(callout => {
    const action = actionById.get(callout.id)
    if (action === undefined) return []
    const x = timeToCoordinate.call(scale, chartMarkerTime(action.barEnd, value.identity.frequency, action.tradingDay))
    const y = priceToCoordinate.call(candles, action.value)
    return x === null || y === null ? [] : [{
      callout, x, y,
      boxWidth: REFERENCE_CALLOUT_BOX.width,
      boxHeight: REFERENCE_CALLOUT_BOX.height,
      expanded: activeActionLabel.value === callout.id || props.selectedSignalId === callout.id,
    }]
  }), width, height)
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
  if (resolvedSignalKey === key) return true
  const barEnd = value.actions[index]!.barEnd
  const barIndex = value.bars.findIndex((bar) => bar.barEnd === barEnd)
  if (barIndex < 0) return false
  const current = chart.timeScale().getVisibleLogicalRange()
  const width = Math.max(10, current === null ? 100 : current.to - current.from)
  followLatest.value = false
  rendering = true
  setRange({ from: barIndex - width / 2, to: barIndex + width / 2 })
  rendering = false
  resolvedSignalKey = key
  emit('focus-resolved', signalId)
  return true
}

function resolveSelectedSignal(): void {
  if (props.selectedSignalId !== null) revealSignal(props.selectedSignalId)
}

function onClick(event: MouseEventParams<Time>): void {
  if (event.hoveredInfo?.objectKind !== 'series-marker' || typeof event.hoveredInfo.objectId !== 'string') return
  const value = model.value
  if (value?.actions.some((action) => action.id === event.hoveredInfo?.objectId)) emit('select-signal', event.hoveredInfo.objectId)
}

function onRangeChange(range: LogicalRange | null): void {
  if (rendering || range === null) return
  if (range.from === programmaticRange?.from && range.to === programmaticRange.to) return
  projectActionLabels()
  if (!paginationArmed) return
  const length = model.value?.bars.length ?? 0
  followLatest.value = range.to >= length - 2
  const nearLeft = range.from < 10
  if (nearLeft && !nearLeftBoundary && props.hasMoreBefore && !props.loading) emit('loadEarlier')
  nearLeftBoundary = nearLeft
}

function setRange(range: { from: number; to: number }): void {
  paginationArmed = false
  programmaticRange = range
  nearLeftBoundary = range.from < 10
  chart?.timeScale().setVisibleLogicalRange(range as LogicalRange)
  armPagination()
}

function armPagination(): void {
  const finish = () => {
    paginationArmFrame = null
    const range = chart?.timeScale().getVisibleLogicalRange()
    nearLeftBoundary = range !== null && range !== undefined && range.from < 10
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

function resize(): void {
  if (chart !== null && container.value !== null) {
    // Repaint synchronously so native pane heights include the shared time axis.
    chart.resize(container.value.clientWidth, container.value.clientHeight, true)
    volumeTop.value = container.value.offsetTop + chart.panes()[0]!.getHeight()
    auxiliaryTop.value = volumeTop.value + chart.panes()[1]!.getHeight()
    projectActionLabels()
  }
}

function renderAuxiliary(): void {
  if (!chart) return
  const active = new Set<string>()
  const value = auxiliaryPresentation.value.showRetainedValue ? auxiliaryModel.value : null
  const theme = resolveChartTheme(container.value ?? document.documentElement)
  const colors: Record<string, string> = { dif: '#FF6B2C', dea: '#365AF5', kongpan: '#FF6B2C', var4: '#FF6B2C', ma10: '#365AF5', var3: '#9333EA', ma120: '#667085', entry: '#FF403A', wash: '#F5B726', distribution: '#22B95D', markup: '#FF6B2C', exit: '#365AF5', inducement: '#9333EA', peaks: '#B45309', caution: '#667085', band_entry: '#FF403A', rebound_entry: '#F5B726', oversold_entry: '#22B95D' }
  const mirror = value?.component === 'zhaoyao_mirror'
  auxiliaryZeroLine?.applyOptions({ color: mirror ? 'rgba(0, 0, 0, 0)' : '#D0D5DD' })
  zhaoyaoMirror.setData(mirror ? buildNewowZhaoyaoMirrorData(value.series) : [])
  for (const item of value?.series ?? []) {
    if (value?.component === 'zhaoyao_mirror') continue
    const id = `${value!.component}:${item.id}`
    active.add(id)
    let series = auxiliaryLines.get(id)
    if (!series) {
      const options = { color: colors[item.key] ?? '#667085', lineWidth: 1 as const, lastValueVisible: false, priceLineVisible: false,
        autoscaleInfoProvider: (base: () => import('lightweight-charts').AutoscaleInfo | null) => {
          const info = base()
          return info?.priceRange == null ? info : { ...info, priceRange: { minValue: Math.min(0, info.priceRange.minValue), maxValue: Math.max(0, info.priceRange.maxValue) } }
        },
      }
      series = item.key === 'histogram' ? chart.addSeries(HistogramSeries, options, 2) : chart.addSeries(LineSeries, options, 2)
      auxiliaryLines.set(id, series)
    }
    series.setData(item.points.map(point => ({ time: point.time, value: point.value, ...(item.key === 'histogram' ? { color: point.value >= 0 ? theme.volumeUp : theme.volumeDown } : {}) })))
  }
  for (const [id, series] of auxiliaryLines) {
    if (active.has(id)) continue
    chart.removeSeries(series); auxiliaryLines.delete(id)
  }
}

function onFullscreenChange(): void {
  fullscreen.value = document.fullscreenElement === stageRoot.value
  resize()
}
async function toggleFullscreen(): Promise<void> {
  fullscreenError.value = null
  try {
    if (document.fullscreenElement === stageRoot.value) await document.exitFullscreen()
    else if (stageRoot.value?.requestFullscreen) await stageRoot.value.requestFullscreen()
    else fullscreenError.value = '当前浏览器不支持图表全屏。'
  } catch { fullscreenError.value = '无法进入图表全屏。' }
}

defineExpose({ revealSignal, scrollToLatest })
</script>

<template>
  <section
    ref="stageRoot"
    class="newow-product-chart-stage"
    :data-auxiliary-component="auxiliaryModel?.component ?? ''"
    :data-auxiliary-state="auxiliaryPresentation.mode"
    :data-band-area-count="model?.bandAreas.length ?? 0"
    :data-channel-point-count="model?.channelPoints.length ?? 0"
    data-testid="newow-product-chart-stage"
    :data-strategy="strategy"
    :data-frequency="model?.identity.frequency ?? ''"
    :data-selected-signal-id="selectedSignalId ?? ''"
    :data-action-ids="model?.actions.map((action) => action.id).join(',') ?? ''"
  >
    <div class="newow-product-chart-stage__toolbar">
    <div class="newow-product-chart-stage__legend" aria-label="Newow 主图图例"><button class="newow-product-chart-stage__main-legend" type="button" @click="emit('explain-main')">{{ mainLegendLabel }}<span v-for="line in legend" :key="line.key" :style="{ color: mainLineColors[line.key] }">{{ line.label }}</span>ⓘ</button><details v-if="model?.hints.length"><summary>过程提示</summary><button v-for="hint in model.hints" :key="hint.id" type="button" :data-hint-id="hint.id" :data-hint-tone="hint.tone" @click="emit('select-hint', hint.id)"><span class="newow-product-chart-stage__hint-kind" :class="`is-${hint.tone}`">{{ hint.kind }}</span> · {{ hint.barEnd }}</button></details></div>
    <div class="newow-product-chart-stage__controls">
      <button v-if="hasMoreBefore" type="button" data-testid="newow-load-earlier" :disabled="loading" @click="emit('loadEarlier')">加载更早</button>
      <button v-if="!followLatest" type="button" @click="scrollToLatest">回到最新</button>
      <button type="button" :aria-label="fullscreen ? '退出图表全屏' : '图表全屏'" @click="toggleFullscreen">{{ fullscreen ? '退出全屏' : '全屏' }}</button>
    </div>
    </div>
    <div
      ref="container"
      class="newow-product-chart-stage__chart"
      @pointermove="scheduleActionProjection"
      @pointerup="scheduleActionProjection"
      @wheel="scheduleActionProjection"
      @dblclick="scheduleActionProjection"
    />
    <div
      v-if="model?.actions.length"
      class="newow-product-chart-stage__action-callouts"
      :style="{ left: `${actionOverlayLeft}px`, top: `${actionOverlayTop}px`, width: `${actionOverlayWidth}px`, height: `${actionOverlayHeight}px` }"
      aria-label="策略参考动作"
    >
      <svg aria-hidden="true"><line v-for="item in positionedActions.filter(point => !point.compact)" :key="item.callout.id" :x1="item.x" :y1="item.y" :x2="item.lineX" :y2="item.lineY" /></svg>
      <button
        v-for="item in positionedActions"
        :key="item.callout.id"
        type="button"
        class="newow-product-chart-stage__action-label"
        :class="[{ 'is-density-node': item.compact, 'is-compact': item.compact && activeActionLabel !== item.callout.id && selectedSignalId !== item.callout.id, 'is-active': activeActionLabel === item.callout.id, 'is-selected': selectedSignalId === item.callout.id }, `is-${item.callout.tone}`]"
        :style="{ left: `${item.left}px`, top: `${item.top}px`, width: `${item.width}px`, height: `${item.height}px` }"
        :data-action-id="item.callout.id"
        :data-reference-price="item.callout.price"
        :data-reference-time="item.callout.time"
        :data-reference-contract="item.callout.physicalContract"
        :data-anchor-y="item.y"
        :aria-label="`${item.callout.title}，${item.callout.detail}，策略参考动作`"
        :title="`${item.callout.title} · ${item.callout.detail}`"
        @mouseenter="activeActionLabel = item.callout.id"
        @mouseleave="activeActionLabel = null"
        @focus="activeActionLabel = item.callout.id"
        @blur="activeActionLabel = null"
        @click="emit('select-signal', item.callout.id)"
      ><template v-if="!item.compact || activeActionLabel === item.callout.id || selectedSignalId === item.callout.id"><strong>{{ item.callout.title }}</strong><span>{{ item.callout.detail }}</span></template><template v-else>{{ item.callout.above ? '▽' : '△' }}</template></button>
    </div>
    <span class="newow-product-chart-stage__volume-label" :style="{ top: `${volumeTop}px` }">成交量</span>
    <div class="newow-product-chart-stage__auxiliary-toolbar" :style="{ top: `${auxiliaryTop}px` }"><slot name="auxiliary-controls"><button @click="emit('explain-auxiliary')">{{ auxiliaryModel?.component === 'macd' ? 'MACD · DIF / DEA' : '辅助指标' }} ⓘ</button></slot></div>
    <p v-if="auxiliaryPresentation.message || fullscreenError" class="newow-product-chart-stage__auxiliary-status" role="status">{{ fullscreenError ?? auxiliaryPresentation.message }}</p>
    <p v-if="loading && response === null" class="newow-product-chart-stage__status" role="status">正在读取 Newow 主图…</p>
    <p v-else-if="response?.value === null" class="newow-product-chart-stage__status" role="status">当前组合主图不可用。</p>
    <p v-else-if="model?.bars.length === 0" class="newow-product-chart-stage__status" role="status">当前窗口没有已完成 Bar。</p>
  </section>
</template>

<style scoped>
.newow-product-chart-stage { --gy-chart-bg:#FFFFFF; --gy-chart-text:#667085; --gy-chart-grid:#F2F4F7; --gy-chart-axis:#EBEDF0; --gy-up:#FF403A; --gy-down:#22B95D; position:relative; min-width:0; height:clamp(580px, 70vh, 920px); display:flex; flex-direction:column; border:1px solid #ebedf0; background:#fff; }
.newow-product-chart-stage:fullscreen { height:100vh; width:100vw; padding:12px; box-sizing:border-box; }
.newow-product-chart-stage__chart { width:100%; flex:1; min-height:500px; }
.newow-product-chart-stage__action-callouts { position:absolute; pointer-events:none; z-index:4; overflow:hidden; }
.newow-product-chart-stage__action-callouts svg { width:100%; height:100%; position:absolute; inset:0; stroke:#9B8169; stroke-width:1; }
.newow-product-chart-stage__action-label { position:absolute; pointer-events:auto; display:grid; align-content:center; gap:3px; box-sizing:border-box; padding:4px; overflow:hidden; border:1px solid #AA927B; border-radius:2px; background:#FFFEFA; color:#665343; font-size:11px; cursor:pointer; box-shadow:0 1px 3px #8C73551A; }
.newow-product-chart-stage__action-label strong { font-size:12px; font-weight:500; }
.newow-product-chart-stage__action-label strong,.newow-product-chart-stage__action-label span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.newow-product-chart-stage__action-label.is-gain span { color:#CB3737; }
.newow-product-chart-stage__action-label.is-loss span { color:#188052; }
.newow-product-chart-stage__action-label.is-density-node { min-width:0; min-height:0; }
.newow-product-chart-stage__action-label.is-compact { padding:0; place-items:center; }
.newow-product-chart-stage__action-label.is-active { z-index:5; outline:2px solid #AA927B; }
.newow-product-chart-stage__action-label.is-selected { outline:2px solid #8B653D; background:#FFF3D9; }
.newow-product-chart-stage__toolbar { display:flex; flex-wrap:wrap; justify-content:space-between; gap:8px; min-height:48px; border-bottom:1px solid #ebedf0; padding:0 8px; }
.newow-product-chart-stage__controls,.newow-product-chart-stage__legend { display:flex; align-items:center; gap:8px; }
button,summary { min-height:44px; padding:0 10px; border:0; color:#667085; background:#fff; cursor:pointer; font-size:12px; }
.newow-product-chart-stage__main-legend { display:flex; align-items:center; gap:6px; }
button:focus-visible,summary:focus-visible { outline:2px solid #365af5; outline-offset:2px; }
summary { display:flex; align-items:center; }
.newow-product-chart-stage__volume-label { position:absolute; left:12px; margin-top:4px; color:#667085; font-size:11px; pointer-events:none; z-index:2; background:#fff; padding-right:4px; }
.newow-product-chart-stage__auxiliary-toolbar { position:absolute; left:1px; right:70px; min-height:32px; background:#fff; z-index:3; }
details { position:relative; } details[open] { z-index:6; } details[open] > button { display:block; white-space:nowrap; }
details[open] { position:absolute; top:0; left:90px; max-height:240px; max-width:calc(100% - 100px); overflow:auto; border:1px solid #ebedf0; background:#fff; box-shadow:0 8px 24px #20242b14; }
.newow-product-chart-stage__hint-kind { display:inline-flex; min-width:28px; justify-content:center; border:1px solid currentColor; border-radius:3px; padding:2px 5px; font-weight:600; }
.newow-product-chart-stage__hint-kind.is-risk { color:#DC2626; }
.newow-product-chart-stage__hint-kind.is-entry { color:#16A34A; }
.newow-product-chart-stage__hint-kind.is-cycle { color:#D97706; }
.newow-product-chart-stage__hint-kind.is-neutral { color:#64748B; }
.newow-product-chart-stage__auxiliary-status { margin:0; padding:6px 12px; color:#b45309; font-size:12px; }
.newow-product-chart-stage__status { position:absolute; z-index:5; top:64px; left:12px; margin:0; color:#b45309; background:#fff; }
@media(max-width:640px) { .newow-product-chart-stage { height:640px; } .newow-product-chart-stage__chart { min-height:500px; } }
</style>
