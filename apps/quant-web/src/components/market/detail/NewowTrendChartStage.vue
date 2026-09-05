<script setup lang="ts">
import { computed, inject, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  HistogramSeries,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type LineData,
  type LogicalRange,
  type MouseEventParams,
  type SeriesMarker,
  type TickMarkType,
  type Time,
} from 'lightweight-charts'

import type { BarData } from '@/types/market'
import type { MarketSeriesMutation } from '@/composables/useMarketSeries'
import type { NewowTrendDetailResponse } from '@/types/newow'
import { resolveChartTheme } from '@/styles/chartTheme'
import { formatChartAxisTimeInShanghai, formatChartTimeInShanghai } from '@/utils/barTime'
import { initialChartLogicalRange } from '@/utils/chartViewport'
import {
  buildNewowTrendChartProjection,
  createNewowTrendChartDisposer,
  NEWOW_TREND_CHART_ADAPTER_KEY,
  NewowTrendChartPrimitive,
  resolveNewowTrendCrosshairFacts,
  type NewowTrendChartMarker,
  type NewowTrendChartProjection,
  type NewowTrendHoverFacts,
  type NewowTrendResizeObserver,
} from '@/components/market/detail/newowTrendChartPrimitives'

const props = withDefaults(defineProps<{
  data: NewowTrendDetailResponse | null
  genericBars: readonly BarData[]
  loading?: boolean
  identityKey?: string
  focusBarEnd?: string | null
  mutation?: MarketSeriesMutation
  hasMoreBefore?: boolean
}>(), { loading: false, identityKey: '', hasMoreBefore: false })

const emit = defineEmits<{
  loadEarlier: []
  'focus-resolved': [barEnd: string]
  'marker-select': [markerId: string]
}>()

const container = ref<HTMLElement | null>(null)
const root = ref<HTMLElement | null>(null)
const followLatest = ref(true)
const fullscreen = ref(false)
let renderedBars: NewowTrendChartProjection['bars'] = []
let resolvedFocusKey: string | null = null
let rendering = false
let nearLeftBoundary = false
let programmaticRange: { from: number; to: number } | null = null
const hoverFacts = ref<NewowTrendHoverFacts | null>(null)
const projection = computed(() => buildNewowTrendChartProjection({
  data: props.data,
  genericBars: props.genericBars,
}))
const primitive = new NewowTrendChartPrimitive()
const chartAdapter = inject(NEWOW_TREND_CHART_ADAPTER_KEY, {
  createChart,
  createSeriesMarkers,
  createResizeObserver: (callback) => new ResizeObserver(callback),
})

let chart: IChartApi | null = null
let candles: ISeriesApi<'Candlestick'> | null = null
let volume: ISeriesApi<'Histogram'> | null = null
const bandLines = new Map<string, {
  readonly b: ISeriesApi<'Line'>
  readonly c: ISeriesApi<'Line'>
}>()
let markers: ISeriesMarkersPluginApi<Time> | null = null
let observer: NewowTrendResizeObserver | null = null
let disposeResources: (() => void) | null = null

onMounted(async () => {
  await nextTick()
  if (container.value === null) return
  const theme = resolveChartTheme(container.value)
  chart = chartAdapter.createChart(container.value, {
    width: container.value.clientWidth,
    height: container.value.clientHeight,
    layout: { background: { type: ColorType.Solid, color: theme.background }, textColor: theme.text },
    grid: { vertLines: { color: theme.grid }, horzLines: { color: theme.grid } },
    rightPriceScale: { borderColor: theme.axis },
    localization: { timeFormatter: formatChartTimeInShanghai },
    crosshair: {
      vertLine: { labelBackgroundColor: '#1F2937', labelVisible: true },
      horzLine: { labelBackgroundColor: '#1F2937', labelVisible: true },
    },
    timeScale: {
      borderColor: theme.axis,
      timeVisible: false,
      tickMarkFormatter: (time: Time, tickMarkType: TickMarkType) => (
        formatChartAxisTimeInShanghai(time, tickMarkType)
      ),
    },
  })
  chart.panes()[0]!.setStretchFactor(6)
  chart.addPane().setStretchFactor(2)
  candles = chart.addSeries(CandlestickSeries, {
    upColor: theme.up,
    downColor: theme.down,
    borderUpColor: theme.up,
    borderDownColor: theme.down,
    wickUpColor: theme.up,
    wickDownColor: theme.down,
  }, 0)
  candles.attachPrimitive(primitive)
  volume = chart.addSeries(HistogramSeries, { priceFormat: { type: 'volume' } }, 1)
  chart.priceScale('right', 1).applyOptions({ scaleMargins: { top: 0.12, bottom: 0.05 } })
  markers = chartAdapter.createSeriesMarkers(candles)
  chart.subscribeCrosshairMove(onCrosshairMove)
  chart.subscribeClick(onClick)
  chart.timeScale().subscribeVisibleLogicalRangeChange(onRangeChange)
  if (typeof document !== 'undefined') document.addEventListener('fullscreenchange', syncFullscreen)
  observer = chartAdapter.createResizeObserver(resize)
  observer.observe(container.value)
  disposeResources = createNewowTrendChartDisposer({
    unsubscribeCrosshair: () => chart?.unsubscribeCrosshairMove(onCrosshairMove),
    disconnectResizeObserver: () => observer?.disconnect(),
    removeChart: () => chart?.remove(),
  })
  renderProjection(projection.value, true)
})

onUnmounted(() => {
  chart?.unsubscribeClick(onClick)
  chart?.timeScale().unsubscribeVisibleLogicalRangeChange(onRangeChange)
  if (typeof document !== 'undefined') document.removeEventListener('fullscreenchange', syncFullscreen)
  disposeResources?.()
  disposeResources = null
  observer = null
  markers = null
  candles = null
  volume = null
  bandLines.clear()
  chart = null
})

watch(projection, (value) => renderProjection(value, false))
watch(() => props.identityKey, () => {
  resolvedFocusKey = null
  followLatest.value = true
  renderedBars = []
  renderProjection(projection.value, true)
}, { flush: 'sync' })
watch(() => props.focusBarEnd, resolveFocus, { flush: 'post' })

function revealTime(barEnd: string): boolean {
  const index = projection.value.bars.findIndex((bar) => Date.parse(bar.barEnd) === Date.parse(barEnd))
  if (chart === null || index < 0) return false
  followLatest.value = false
  const range = chart.timeScale().getVisibleLogicalRange()
  const width = Math.max(10, range === null ? 100 : range.to - range.from)
  rendering = true
  setRange({ from: index - width / 2, to: index + width / 2 })
  rendering = false
  return true
}

function resolveFocus(): void {
  if (!props.focusBarEnd) return
  const key = `${props.identityKey}:${props.focusBarEnd}`
  if (resolvedFocusKey === key || !revealTime(props.focusBarEnd)) return
  resolvedFocusKey = key
  emit('focus-resolved', props.focusBarEnd)
}

function scrollToLatest(): void {
  followLatest.value = true
  chart?.timeScale().scrollToRealTime()
}

function onRangeChange(range: LogicalRange | null): void {
  if (rendering || range === null) return
  if (range.from === programmaticRange?.from && range.to === programmaticRange.to) return
  followLatest.value = range.to >= projection.value.bars.length - 2
  const nearLeft = range.from < 10
  if (nearLeft && !nearLeftBoundary && props.hasMoreBefore && !props.loading) emit('loadEarlier')
  nearLeftBoundary = nearLeft
}

function onClick(event: MouseEventParams<Time>): void {
  if (event.hoveredInfo?.objectKind !== 'series-marker') return
  const marker = projection.value.markers.find((item) => item.id === event.hoveredInfo?.objectId)
  if (marker) emit('marker-select', marker.id)
}

function setRange(range: { from: number; to: number }): void {
  programmaticRange = range
  nearLeftBoundary = range.from < 10
  chart?.timeScale().setVisibleLogicalRange(range)
}

async function toggleFullscreen(): Promise<void> {
  if (root.value === null || typeof document === 'undefined') return
  if (document.fullscreenElement === root.value) await document.exitFullscreen()
  else await root.value.requestFullscreen()
}

function syncFullscreen(): void {
  fullscreen.value = document.fullscreenElement === root.value
  resize()
}

defineExpose({ revealTime, scrollToLatest })

function renderProjection(value: NewowTrendChartProjection, resetViewport: boolean): void {
  if (
    container.value === null
    || chart === null
    || candles === null
    || volume === null
  ) return
  const previousRange = chart.timeScale().getVisibleLogicalRange()
  const previousFirst = renderedBars[0]?.barEnd
  const prepended = previousFirst === undefined ? 0
    : Math.max(0, value.bars.findIndex((bar) => Date.parse(bar.barEnd) === Date.parse(previousFirst)))
  rendering = true
  const theme = resolveChartTheme(container.value)
  candles.setData(value.bars.map((bar) => ({
    time: dayTime(bar.tradingDay),
    open: bar.open,
    high: bar.high,
    low: bar.low,
    close: bar.close,
  })))
  volume.setData(value.bars.map((bar) => ({
    time: dayTime(bar.tradingDay),
    value: bar.volume,
    color: bar.close >= bar.open ? theme.volumeUp : theme.volumeDown,
  })))
  syncBandLines(value)
  primitive.setData(value, dayTime)
  primitive.setStyle({
    yellowFill: 'rgba(245, 158, 11, 0.16)',
    blueFill: 'rgba(37, 99, 235, 0.14)',
    bullishCup: '#D97706',
    bearishCup: '#2563EB',
    pivot: '#7C3AED',
    rollover: theme.textMuted,
    rolloverText: theme.textMuted,
  })
  markers?.setMarkers(value.markers.map((marker) => chartMarker(marker, theme)))
  hoverFacts.value = null
  if (resetViewport || renderedBars.length === 0) {
    const range = initialChartLogicalRange(value.bars.length)
    if (range === null) chart.timeScale().fitContent()
    else setRange(range)
  } else if (prepended > 0 && previousRange !== null) {
    setRange({ from: previousRange.from + prepended, to: previousRange.to + prepended })
  } else if (followLatest.value && props.mutation?.kind === 'live') {
    chart.timeScale().scrollToRealTime()
  } else if (previousRange !== null) {
    setRange(previousRange)
  }
  renderedBars = value.bars
  rendering = false
  resolveFocus()
}

function syncBandLines(value: NewowTrendChartProjection): void {
  if (chart === null) return
  const segmentIds = new Set([
    ...value.band.b.map((point) => point.segmentId),
    ...value.band.c.map((point) => point.segmentId),
  ])
  for (const [segmentId, series] of bandLines) {
    if (segmentIds.has(segmentId)) continue
    chart.removeSeries(series.b)
    chart.removeSeries(series.c)
    bandLines.delete(segmentId)
  }
  for (const segmentId of segmentIds) {
    let series = bandLines.get(segmentId)
    if (series === undefined) {
      series = {
        b: chart.addSeries(LineSeries, {
          color: '#F59E0B', lineWidth: 2, lastValueVisible: false, priceLineVisible: false,
        }, 0),
        c: chart.addSeries(LineSeries, {
          color: '#2563EB', lineWidth: 2, lastValueVisible: false, priceLineVisible: false,
        }, 0),
      }
      bandLines.set(segmentId, series)
    }
    series.b.setData(bandLineValues(value, 'b', segmentId))
    series.c.setData(bandLineValues(value, 'c', segmentId))
  }
}

function bandLineValues(
  value: NewowTrendChartProjection,
  key: 'b' | 'c',
  segmentId: string,
): Array<LineData<Time>> {
  return value.band[key]
    .filter((point) => point.segmentId === segmentId)
    .map((point) => ({
      time: dayTime(point.tradingDay),
      value: point.value,
      color: point.state === 'YELLOW' ? '#F59E0B'
        : point.state === 'BLUE' ? '#2563EB' : '#98A2B3',
    }))
}

function chartMarker(
  marker: NewowTrendChartMarker,
  theme: ReturnType<typeof resolveChartTheme>,
): SeriesMarker<Time> {
  const colors = {
    yellow: '#D97706',
    blue: '#2563EB',
    d1: theme.down,
    d2: theme.up,
    d3: '#2563EB',
    cup: '#7C3AED',
  } as const
  return {
    id: marker.id,
    time: dayTime(marker.tradingDay),
    position: marker.position,
    shape: marker.shape,
    color: colors[marker.colorRole],
    text: marker.label,
    size: marker.family === 'trend' ? 1.5 : 1,
  }
}

function onCrosshairMove(param: MouseEventParams<Time>): void {
  hoverFacts.value = param.time === undefined
    ? null
    : resolveNewowTrendCrosshairFacts(projection.value, param.time)
}

function resize(): void {
  if (container.value === null || chart === null) return
  chart.resize(container.value.clientWidth, container.value.clientHeight)
}

function dayTime(day: string): Time {
  const [year, month, date] = day.split('-').map(Number)
  return { year: year!, month: month!, day: date! }
}

function formatValue(value: number | null): string {
  return value === null ? '不可用' : String(value)
}
</script>

<template>
  <section
    ref="root"
    class="newow-trend-chart-stage"
    :class="{ 'newow-trend-chart-stage--fullscreen': fullscreen }"
    data-testid="newow-trend-chart-stage"
    :data-chart-source="projection.source"
    :data-pane-count="projection.paneCount"
    data-time-scale-sync="shared"
    data-crosshair-sync="shared"
    :data-newow-band-area-count="projection.band.areas.length"
    :data-newow-marker-count="projection.markers.length"
    :data-newow-marker-ids="projection.markers.map((marker) => marker.id).join(',')"
    :data-newow-rollover-count="projection.rolloverSeams.length"
  >
    <div class="newow-trend-chart-stage__controls">
      <button v-if="hasMoreBefore" type="button" :disabled="loading" @click="emit('loadEarlier')">加载更早</button>
      <button v-if="!followLatest" type="button" @click="scrollToLatest">回到最新</button>
      <button type="button" :aria-label="fullscreen ? '退出全屏' : '全屏图表'" @click="toggleFullscreen">{{ fullscreen ? '退出全屏' : '全屏图表' }}</button>
    </div>
    <div ref="container" class="newow-trend-chart-stage__chart" />
    <div v-if="hoverFacts" class="newow-trend-chart-stage__hover" aria-live="polite">
      <span>{{ hoverFacts.tradingDay }}</span>
      <span>O {{ hoverFacts.bar.open }}</span>
      <span>H {{ hoverFacts.bar.high }}</span>
      <span>L {{ hoverFacts.bar.low }}</span>
      <span>C {{ hoverFacts.bar.close }}</span>
      <span>Vol {{ hoverFacts.bar.volume }}</span>
      <span>OI {{ formatValue(hoverFacts.bar.openInterest) }}</span>
      <span v-if="hoverFacts.physicalContract">合约 {{ hoverFacts.physicalContract }}</span>
      <template v-if="hoverFacts.trend">
        <span>趋势 {{ hoverFacts.trend.state }}</span>
        <span>B {{ formatValue(hoverFacts.trend.b) }}</span>
        <span>C {{ formatValue(hoverFacts.trend.c) }}</span>
      </template>
      <span v-for="(label, index) in hoverFacts.markerLabels" :key="`${index}:${label}`">{{ label }}</span>
      <span v-for="cup in hoverFacts.cupStates" :key="cup.candidateId">
        杯柄 {{ cup.direction }} / {{ cup.state }}
      </span>
      <span v-if="hoverFacts.rolloverLabel">{{ hoverFacts.rolloverLabel }}</span>
    </div>
    <div class="newow-trend-chart-stage__legend" aria-label="Newow 趋势图例">
      <span><i class="newow-trend-chart-stage__swatch newow-trend-chart-stage__swatch--yellow" />黄带</span>
      <span><i class="newow-trend-chart-stage__swatch newow-trend-chart-stage__swatch--blue" />蓝带</span>
      <span>下方子图：成交量</span>
    </div>
    <div v-if="loading && data === null" class="newow-trend-chart-stage__status">正在读取 Newow 趋势数据…</div>
    <div
      v-else-if="projection.unavailableDisclosure"
      class="newow-trend-chart-stage__status newow-trend-chart-stage__status--unavailable"
      data-testid="newow-trend-chart-unavailable"
    >
      {{ projection.unavailableDisclosure }}
    </div>
    <div v-else-if="projection.bars.length === 0" class="newow-trend-chart-stage__status">当前窗口无 Newow completed D1 bars</div>
  </section>
</template>

<style scoped>
.newow-trend-chart-stage__controls { display: flex; justify-content: flex-end; gap: 8px; }
.newow-trend-chart-stage__controls button { min-height: 44px; padding: 0 12px; border: 1px solid var(--gy-border); border-radius: var(--gy-radius-sm); color: var(--gy-text-primary); background: var(--gy-bg-panel); cursor: pointer; }
.newow-trend-chart-stage--fullscreen { height: 100vh; padding: 16px; background: var(--gy-bg-app); }
.newow-trend-chart-stage--fullscreen .newow-trend-chart-stage__chart { height: calc(100vh - 110px); }
.newow-trend-chart-stage {
  position: relative;
  min-width: 0;
  min-height: 680px;
  height: clamp(680px, 74vh, 1040px);
  border: 1px solid var(--gy-border);
  background: var(--gy-bg-panel);
}
.newow-trend-chart-stage__chart { width: 100%; height: 100%; }
.newow-trend-chart-stage__hover {
  position: absolute;
  z-index: 4;
  top: 10px;
  left: 12px;
  display: flex;
  flex-wrap: wrap;
  gap: 4px 12px;
  max-width: calc(100% - 24px);
  color: var(--gy-text-muted);
  font-size: 12px;
  line-height: 1.4;
  pointer-events: none;
}
.newow-trend-chart-stage__legend {
  position: absolute;
  z-index: 3;
  top: 42px;
  right: 72px;
  display: flex;
  gap: 12px;
  padding: 5px 9px;
  border: 1px solid var(--gy-border);
  border-radius: var(--gy-radius-sm);
  color: var(--gy-text-secondary);
  background: color-mix(in srgb, var(--gy-bg-panel) 90%, transparent);
  font-size: var(--gy-font-size-xs);
  pointer-events: none;
}
.newow-trend-chart-stage__legend span { display: inline-flex; gap: 5px; align-items: center; white-space: nowrap; }
.newow-trend-chart-stage__swatch { width: 18px; height: 7px; border-radius: 2px; }
.newow-trend-chart-stage__swatch--yellow { background: rgba(245, 158, 11, .4); }
.newow-trend-chart-stage__swatch--blue { background: rgba(37, 99, 235, .36); }
.newow-trend-chart-stage__status {
  position: absolute;
  z-index: 5;
  inset: auto 12px 12px;
  padding: 8px 10px;
  border: 1px solid var(--gy-border);
  border-radius: var(--gy-radius-sm);
  color: var(--gy-text-muted);
  background: color-mix(in srgb, var(--gy-bg-panel) 94%, transparent);
  font-size: var(--gy-font-size-sm);
  pointer-events: none;
}
.newow-trend-chart-stage__status--unavailable { color: var(--gy-status-warning); }

@media (max-width: 640px) {
  .newow-trend-chart-stage { min-height: 520px; height: 68vh; }
  .newow-trend-chart-stage__legend { top: auto; right: 8px; bottom: 46px; gap: 8px; }
}
</style>
