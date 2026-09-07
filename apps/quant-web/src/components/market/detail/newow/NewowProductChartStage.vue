<script setup lang="ts">
import { computed, inject, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type LineData,
  type LogicalRange,
  type MouseEventParams,
  type SeriesMarker,
  type Time,
} from 'lightweight-charts'

import { resolveChartTheme } from '@/styles/chartTheme'
import type { NewowProductSectionResponse } from '@/types/newowProduct'
import { formatChartAxisTimeInShanghai, formatChartTimeInShanghai } from '@/utils/barTime'
import { initialChartLogicalRange } from '@/utils/chartViewport'
import {
  buildNewowProductChartModel,
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
}>()

const container = ref<HTMLElement | null>(null)
const followLatest = ref(true)
const model = computed(() => props.response === null ? null : buildNewowProductChartModel(props.response))
const adapter = inject(NEWOW_PRODUCT_CHART_ADAPTER_KEY, {
  createChart,
  createSeriesMarkers: (series) => createSeriesMarkers(series),
  createResizeObserver: (callback) => new ResizeObserver(callback),
})

let chart: IChartApi | null = null
let candles: ISeriesApi<'Candlestick'> | null = null
let actionMarkers: ISeriesMarkersPluginApi<Time> | null = null
let observer: NewowProductResizeObserver | null = null
let renderedBars: NewowProductChartModel['bars'] = []
let renderedIdentity = ''
let rendering = false
let nearLeftBoundary = false
let programmaticRange: { from: number; to: number } | null = null
let resolvedSignalKey: string | null = null
const mainLines = new Map<string, ISeriesApi<'Line'>>()
const hintSeries = new Map<string, {
  series: ISeriesApi<'Line'>
  markers: ISeriesMarkersPluginApi<Time>
}>()

onMounted(async () => {
  await nextTick()
  if (container.value === null) return
  const theme = resolveChartTheme(container.value)
  chart = adapter.createChart(container.value, {
    width: container.value.clientWidth,
    height: container.value.clientHeight,
    layout: { background: { type: ColorType.Solid, color: theme.background }, textColor: theme.text },
    grid: { vertLines: { color: theme.grid }, horzLines: { color: theme.grid } },
    rightPriceScale: { borderColor: theme.axis },
    localization: { timeFormatter: formatChartTimeInShanghai },
    timeScale: { borderColor: theme.axis, timeVisible: true, tickMarkFormatter: formatChartAxisTimeInShanghai },
  })
  candles = chart.addSeries(CandlestickSeries, {
    upColor: theme.up, downColor: theme.down,
    borderUpColor: theme.up, borderDownColor: theme.down,
    wickUpColor: theme.up, wickDownColor: theme.down,
  })
  actionMarkers = adapter.createSeriesMarkers(candles as never)
  chart.subscribeClick(onClick)
  chart.timeScale().subscribeVisibleLogicalRangeChange(onRangeChange)
  observer = adapter.createResizeObserver(resize)
  observer.observe(container.value)
  renderModel(model.value)
})

onUnmounted(createNewowProductChartDisposer({
  unsubscribeRange: () => chart?.timeScale().unsubscribeVisibleLogicalRangeChange(onRangeChange),
  unsubscribeClick: () => chart?.unsubscribeClick(onClick),
  disconnectResizeObserver: () => observer?.disconnect(),
  removeChart: () => chart?.remove(),
}))

watch(model, (value) => renderModel(value))
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
    for (const series of mainLines.values()) chart.removeSeries(series)
    mainLines.clear()
    for (const entry of hintSeries.values()) chart.removeSeries(entry.series)
    hintSeries.clear()
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
  const colors: Record<string, string> = { b: '#F59E0B', a: '#2563EB', upper: '#DC2626', lower: '#16A34A', ma35: '#F59E0B', ma45: '#7C3AED' }
  for (const line of value.mainLines) {
    let series = mainLines.get(line.id)
    if (series === undefined) {
      series = chart.addSeries(LineSeries, { color: colors[line.key] ?? '#64748B', lineWidth: 2, lastValueVisible: false, priceLineVisible: false })
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
  const groups = new Map<string, NewowProductChartModel['hints'][number][]>()
  const occurrences = new Map<string, number>()
  for (const hint of value.hints) {
    if (hint.value === null) continue
    const occurrenceKey = `${hint.kind}:${hint.barEnd}`
    const occurrence = occurrences.get(occurrenceKey) ?? 0
    occurrences.set(occurrenceKey, occurrence + 1)
    const seriesKey = `${hint.kind}:${occurrence}`
    const items = groups.get(seriesKey) ?? []
    items.push(hint)
    groups.set(seriesKey, items)
  }
  for (const [seriesKey, entry] of hintSeries) {
    if (groups.has(seriesKey)) continue
    chart.removeSeries(entry.series)
    hintSeries.delete(seriesKey)
  }
  for (const [seriesKey, items] of groups) {
    let entry = hintSeries.get(seriesKey)
    if (entry === undefined) {
      const series = chart.addSeries(LineSeries, {
        color: 'rgba(0, 0, 0, 0)', lineVisible: false, crosshairMarkerVisible: false,
        lastValueVisible: false, priceLineVisible: false,
      })
      entry = { series, markers: adapter.createSeriesMarkers(series as never) }
      hintSeries.set(seriesKey, entry)
    }
    const ordered = [...items].sort((left, right) => Date.parse(left.barEnd) - Date.parse(right.barEnd) || (left.sequence ?? -1) - (right.sequence ?? -1))
    entry.series.setData(ordered.map((hint): LineData<Time> => ({
      time: chartMarkerTime(hint.barEnd, value.identity.frequency, hint.tradingDay), value: hint.value!,
    })))
    entry.markers.setMarkers(ordered.map((hint) => productChartMarker(
      hint,
      props.selectedSignalId,
      chartMarkerTime(hint.barEnd, value.identity.frequency, hint.tradingDay),
    )))
  }
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
  if (chart !== null && container.value !== null) chart.resize(container.value.clientWidth, container.value.clientHeight)
}

function formatKnownAt(value: string): string {
  return formatChartTimeInShanghai(Math.floor(Date.parse(value) / 1000) as Time)
}

defineExpose({ revealSignal, scrollToLatest })
</script>

<template>
  <section
    class="newow-product-chart-stage"
    data-testid="newow-product-chart-stage"
    :data-strategy="model?.identity.strategy ?? ''"
    :data-frequency="model?.identity.frequency ?? ''"
    :data-selected-signal-id="selectedSignalId ?? ''"
    :data-action-ids="model?.actions.map((action) => action.id).join(',') ?? ''"
  >
    <div class="newow-product-chart-stage__controls">
      <button v-if="hasMoreBefore" type="button" data-testid="newow-load-earlier" :disabled="loading" @click="emit('loadEarlier')">加载更早</button>
      <button v-if="!followLatest" type="button" @click="scrollToLatest">回到最新</button>
    </div>
    <div ref="container" class="newow-product-chart-stage__chart" />
    <div class="newow-product-chart-stage__legend" aria-label="Newow 主图图例">
      <span v-for="line in model?.mainLines ?? []" :key="line.id">{{ line.label }}</span>
      <span>建仓 / 清仓</span>
    </div>
    <ul v-if="model?.hints.length" class="newow-product-chart-stage__hints" aria-label="非重绘过程提示">
      <li v-for="hint in model.hints" :key="hint.id">
        {{ hint.kind }} · 来源 {{ hint.sourceIdentity ?? '未提供更细来源' }}
        · 响应公式 {{ hint.formulaVersions.join(' / ') }}
        · owner {{ hint.physicalContract }} · {{ hint.segmentId }}
        · 确认 {{ formatKnownAt(hint.confirmedAt) }}
      </li>
    </ul>
    <p v-if="loading && response === null" class="newow-product-chart-stage__status" role="status">正在读取 Newow 主图…</p>
    <p v-else-if="response?.value === null" class="newow-product-chart-stage__status" role="status">当前组合主图不可用。</p>
    <p v-else-if="model?.bars.length === 0" class="newow-product-chart-stage__status" role="status">当前窗口没有已完成 Bar。</p>
  </section>
</template>

<style scoped>
.newow-product-chart-stage { position: relative; min-width: 0; height: clamp(560px, 68vh, 900px); border: 1px solid var(--gy-border); background: var(--gy-bg-panel); }
.newow-product-chart-stage__chart { width: 100%; height: 100%; }
.newow-product-chart-stage__controls { position: absolute; z-index: 5; top: 10px; right: 10px; display: flex; gap: 8px; }
.newow-product-chart-stage__controls button { min-height: 44px; padding: 0 12px; border: 1px solid var(--gy-border); border-radius: var(--gy-radius-sm); color: var(--gy-text-primary); background: var(--gy-bg-panel); cursor: pointer; }
.newow-product-chart-stage__legend { position: absolute; z-index: 4; top: 12px; left: 12px; display: flex; flex-wrap: wrap; gap: 8px; color: var(--gy-text-secondary); font-size: var(--gy-font-size-xs); pointer-events: none; }
.newow-product-chart-stage__hints { position: absolute; z-index: 4; right: 12px; bottom: 12px; max-width: min(520px, calc(100% - 24px)); margin: 0; padding: 8px 12px 8px 28px; border: 1px solid var(--gy-border); border-radius: var(--gy-radius-sm); color: var(--gy-text-secondary); background: color-mix(in srgb, var(--gy-bg-panel) 94%, transparent); font-size: var(--gy-font-size-xs); }
.newow-product-chart-stage__status { position: absolute; z-index: 5; inset: auto 12px 12px; margin: 0; padding: 8px 10px; border: 1px solid var(--gy-border); border-radius: var(--gy-radius-sm); color: var(--gy-status-warning); background: var(--gy-bg-panel); }
@media (max-width: 640px) { .newow-product-chart-stage { height: 58vh; min-height: 480px; } .newow-product-chart-stage__hints { max-height: 120px; overflow: auto; } }
</style>
