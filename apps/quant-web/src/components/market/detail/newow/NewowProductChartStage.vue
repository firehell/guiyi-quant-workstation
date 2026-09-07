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
import { resolveChartTheme } from '@/styles/chartTheme'
import type { NewowProductSectionResponse } from '@/types/newowProduct'
import { formatChartAxisTimeInShanghai, formatChartTimeInShanghai } from '@/utils/barTime'
import { initialChartLogicalRange } from '@/utils/chartViewport'
import {
  buildNewowProductChartModel,
  alignNewowAuxiliaryChartModel,
  resolveNewowAuxiliaryRenderState,
  chartMarkerTime,
  createNewowProductChartDisposer,
  NEWOW_PRODUCT_CHART_ADAPTER_KEY,
  productChartMarker,
  type NewowProductChartModel,
  type NewowProductResizeObserver,
} from '@/components/market/detail/newow/newowProductChartPrimitives'

const props = withDefaults(defineProps<{
  response: NewowProductSectionResponse<'chart'> | null
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
const container = ref<HTMLElement | null>(null)
const followLatest = ref(true)
const model = computed(() => props.response === null ? null : buildNewowProductChartModel(props.response))
const auxiliaryModel = computed(() => alignNewowAuxiliaryChartModel(props.response, props.auxiliaryResponse ?? null))
const auxiliaryPresentation = computed(() => resolveNewowAuxiliaryRenderState(props.auxiliaryLifecycle ?? 'not_requested', auxiliaryModel.value !== null, props.auxiliaryError ?? null))
const mainLineColors: Record<string, string> = { b: '#F59E0B', a: '#2563EB', upper: '#DC2626', lower: '#16A34A', ma35: '#F59E0B', ma45: '#7C3AED' }
const legend = computed(() => [...new Map(model.value?.mainLines.map(line => [line.key, line]) ?? []).values()])
const adapter = inject(NEWOW_PRODUCT_CHART_ADAPTER_KEY, {
  createChart,
  createSeriesMarkers: (series) => createSeriesMarkers(series),
  createResizeObserver: (callback) => new ResizeObserver(callback),
})

let chart: IChartApi | null = null
let candles: ISeriesApi<'Candlestick'> | null = null
let volume: ISeriesApi<'Histogram'> | null = null
const band = new NewowProductBandPrimitive()
let auxiliaryAnchor: ISeriesApi<'Line'> | null = null
const auxiliaryLines = new Map<string, ISeriesApi<'Line'> | ISeriesApi<'Histogram'>>()
let actionMarkers: ISeriesMarkersPluginApi<Time> | null = null
let observer: NewowProductResizeObserver | null = null
let renderedBars: NewowProductChartModel['bars'] = []
let renderedIdentity = ''
let rendering = false
let nearLeftBoundary = false
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
    upColor: theme.up, downColor: theme.down,
    borderUpColor: theme.up, borderDownColor: theme.down,
    wickUpColor: theme.up, wickDownColor: theme.down,
  })
  chart.panes()[0]!.setStretchFactor(5)
  chart.addPane().setStretchFactor(1.2)
  chart.addPane().setStretchFactor(2)
  candles.attachPrimitive(band)
  volume = chart.addSeries(HistogramSeries, { priceFormat: { type: 'volume' }, priceLineVisible: false, lastValueVisible: false }, 1)
  // Whitespace keeps the auxiliary pane/timeline present during loading, without inventing zero values.
  auxiliaryAnchor = chart.addSeries(LineSeries, { lineVisible: false, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false }, 2)
  auxiliaryAnchor.createPriceLine({ price: 0, color: '#D0D5DD', lineWidth: 1, lineStyle: 2, axisLabelVisible: false })
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
    if (typeof document !== 'undefined') document.removeEventListener('fullscreenchange', onFullscreenChange)
    candles?.detachPrimitive(band)
    chart?.remove()
    chart = null; candles = null; volume = null; auxiliaryAnchor = null
    mainLines.clear(); auxiliaryLines.clear()
  },
}))

watch(model, (value) => renderModel(value))
watch([auxiliaryModel, auxiliaryPresentation], renderAuxiliary)
watch(() => props.selectedSignalId, () => {
  resolvedSignalKey = null
  renderMarkers(model.value)
  resolveSelectedSignal()
}, { flush: 'post' })

function identityKey(value: NewowProductChartModel): string {
  return `${value.identity.product}:${value.identity.strategy}:${value.identity.frequency}`
}

function renderModel(value: NewowProductChartModel | null): void {
  if (chart === null || candles === null) return
  if (value === null) {
    candles.setData([])
    volume?.setData([])
    auxiliaryAnchor?.setData([])
    band.setData([])
    renderAuxiliary()
    for (const series of mainLines.values()) chart.removeSeries(series)
    mainLines.clear()
    actionMarkers?.setMarkers([])
    renderedBars = []
    renderedIdentity = ''
    resolvedSignalKey = null
    return
  }
  const nextIdentity = identityKey(value)
  const resetViewport = nextIdentity !== renderedIdentity
  const previousRange = chart.timeScale().getVisibleLogicalRange()
  const previousFirst = renderedBars[0]?.barEnd
  const prepended = previousFirst === undefined ? 0 : Math.max(0, value.bars.findIndex((bar) => bar.barEnd === previousFirst))
  rendering = true
  candles.setData(value.bars.map((bar) => ({
    time: chartMarkerTime(bar.barEnd, value.identity.frequency, bar.tradingDay),
    open: bar.open, high: bar.high, low: bar.low, close: bar.close,
  })))
  volume?.setData(value.bars.map(bar => ({ time: chartMarkerTime(bar.barEnd, value.identity.frequency, bar.tradingDay), value: bar.volume, color: bar.close >= bar.open ? '#FF403A' : '#22B95D' })))
  auxiliaryAnchor?.setData(value.bars.map(bar => ({ time: chartMarkerTime(bar.barEnd, value.identity.frequency, bar.tradingDay) })))
  band.setData(value.bandAreas)
  renderAuxiliary()
  syncMainLines(value)
  renderMarkers(value)
  if (resetViewport || renderedBars.length === 0) {
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
  renderedIdentity = nextIdentity
  rendering = false
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
      series = chart.addSeries(LineSeries, { color: mainLineColors[line.key] ?? '#64748B', lineWidth: 2, lastValueVisible: false, priceLineVisible: false })
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
  const length = model.value?.bars.length ?? 0
  followLatest.value = range.to >= length - 2
  const nearLeft = range.from < 10
  if (nearLeft && !nearLeftBoundary && props.hasMoreBefore && !props.loading) emit('loadEarlier')
  nearLeftBoundary = nearLeft
}

function setRange(range: { from: number; to: number }): void {
  programmaticRange = range
  nearLeftBoundary = range.from < 10
  chart?.timeScale().setVisibleLogicalRange(range as LogicalRange)
}

function scrollToLatest(): void {
  followLatest.value = true
  chart?.timeScale().scrollToRealTime()
}

function resize(): void {
  if (chart !== null && container.value !== null) {
    // Repaint synchronously so native pane heights include the shared time axis.
    chart.resize(container.value.clientWidth, container.value.clientHeight, true)
    volumeTop.value = container.value.offsetTop + chart.panes()[0]!.getHeight()
    auxiliaryTop.value = volumeTop.value + chart.panes()[1]!.getHeight()
  }
}

function renderAuxiliary(): void {
  if (!chart) return
  const active = new Set<string>()
  const value = auxiliaryPresentation.value.showRetainedValue ? auxiliaryModel.value : null
  const colors: Record<string, string> = { dif: '#FF6B2C', dea: '#365AF5', kongpan: '#FF6B2C', var4: '#FF6B2C', ma10: '#365AF5', var3: '#9333EA', ma120: '#667085', entry: '#FF403A', wash: '#F5B726', distribution: '#22B95D', markup: '#FF6B2C', exit: '#365AF5', inducement: '#9333EA', peaks: '#B45309', caution: '#667085', band_entry: '#FF403A', rebound_entry: '#F5B726', oversold_entry: '#22B95D' }
  for (const item of value?.series ?? []) {
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
    series.setData(item.points.map(point => ({ time: point.time, value: point.value, ...(item.key === 'histogram' ? { color: point.value >= 0 ? '#FF403A' : '#22B95D' } : {}) })))
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
    data-testid="newow-product-chart-stage"
    :data-strategy="model?.identity.strategy ?? ''"
    :data-frequency="model?.identity.frequency ?? ''"
    :data-selected-signal-id="selectedSignalId ?? ''"
    :data-action-ids="model?.actions.map((action) => action.id).join(',') ?? ''"
  >
    <div class="newow-product-chart-stage__toolbar">
    <div class="newow-product-chart-stage__legend" aria-label="Newow 主图图例"><button class="newow-product-chart-stage__main-legend" type="button" @click="emit('explain-main')">{{ model?.identity.strategy === 'trend' ? '趋势带' : model?.identity.strategy === 'oscillation' ? '震荡区间' : '主升浪' }}<span v-for="line in legend" :key="line.key" :style="{ color: mainLineColors[line.key] }">{{ line.label }}</span>ⓘ</button><details v-if="model?.hints.length"><summary>过程提示</summary><button v-for="hint in model.hints" :key="hint.id" type="button" :data-hint-id="hint.id" @click="emit('select-hint', hint.id)">{{ hint.kind }} · {{ hint.barEnd }}</button></details></div>
    <div class="newow-product-chart-stage__controls">
      <button v-if="hasMoreBefore" type="button" data-testid="newow-load-earlier" :disabled="loading" @click="emit('loadEarlier')">加载更早</button>
      <button v-if="!followLatest" type="button" @click="scrollToLatest">回到最新</button>
      <button type="button" :aria-label="fullscreen ? '退出图表全屏' : '图表全屏'" @click="toggleFullscreen">{{ fullscreen ? '退出全屏' : '全屏' }}</button>
    </div>
    </div>
    <div ref="container" class="newow-product-chart-stage__chart" />
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
.newow-product-chart-stage__auxiliary-status { margin:0; padding:6px 12px; color:#b45309; font-size:12px; }
.newow-product-chart-stage__status { position:absolute; z-index:5; top:64px; left:12px; margin:0; color:#b45309; background:#fff; }
@media(max-width:640px) { .newow-product-chart-stage { height:640px; } .newow-product-chart-stage__chart { min-height:500px; } }
</style>
