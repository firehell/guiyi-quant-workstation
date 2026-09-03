<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
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
} from 'lightweight-charts'
import KlineHoverLegend from '@/components/kline/KlineHoverLegend.vue'
import type {
  BarData,
  HoverKlineContext,
  KlineMarker,
  MainIndicatorId,
  SeriesKind,
} from '@/types/market'
import { resolveChartTheme } from '@/styles/chartTheme'
import {
  formatChartAxisTimeInShanghai,
  formatChartTimeInShanghai,
  toKlineDisplayTimeForPeriod,
} from '@/utils/barTime'
import { normalizeBarSeries } from '@/utils/barSeries'
import { initialChartLogicalRange } from '@/utils/chartViewport'
import {
  buildKlineDerivedData,
  resolveKlineHoverContext,
  type KlineValuePoint,
} from '@/utils/klineViewModel'
import { mergeKlineMarkers } from '@/utils/alertMarkers'
import { RangeDetectorPrimitive } from '@/components/kline/rangeDetectorPrimitive'

const props = withDefaults(defineProps<{
  bars: BarData[]
  loading?: boolean
  error?: string | null
  period?: string
  seriesKind: SeriesKind
  visibleMainIndicators?: MainIndicatorId[]
  rangeDetectorSourceIdentity?: string
  rangeDetectorAnchorTime?: string | null
  alertMarkers?: KlineMarker[]
  researchMarkers?: KlineMarker[]
}>(), {
  loading: false,
  error: null,
  period: '15m',
  visibleMainIndicators: () => [],
  rangeDetectorSourceIdentity: '',
  rangeDetectorAnchorTime: null,
  alertMarkers: () => [],
  researchMarkers: () => [],
})

const emit = defineEmits<{
  'need-more-before': []
  'follow-latest-change': [followLatest: boolean]
  'crosshair-change': [context: HoverKlineContext | null]
}>()

const container = ref<HTMLElement>()
let chart: IChartApi | null = null
let candles: ISeriesApi<'Candlestick'> | null = null
let volume: ISeriesApi<'Histogram'> | null = null
let macdHistogram: ISeriesApi<'Histogram'> | null = null
let macdDif: ISeriesApi<'Line'> | null = null
let macdDea: ISeriesApi<'Line'> | null = null
let htdyZk1: ISeriesApi<'Line'> | null = null
let htdyZd1: ISeriesApi<'Line'> | null = null
let htdyZd2: ISeriesApi<'Line'> | null = null
let htdyMarkers: ISeriesMarkersPluginApi<Time> | null = null
const emaLines: Partial<Record<EmaIndicatorId, ISeriesApi<'Line'>>> = {}
const rangeDetectorPrimitive = new RangeDetectorPrimitive()
let observer: ResizeObserver | null = null
let renderedBars: BarData[] = []
let isNearLeftBoundary = false
let paginationArmed = false
let followLatest = true
const hoverContext = ref<HoverKlineContext | null>(null)
const macdLabelTop = ref<number | null>(null)
let derivedData = buildKlineDerivedData([], [])

type EmaIndicatorId = 'ema_10' | 'ema_21' | 'ema_60'
const EMA_INDICATORS: EmaIndicatorId[] = ['ema_10', 'ema_21', 'ema_60']

onMounted(async () => {
  await nextTick()
  if (!container.value) return
  const theme = resolveChartTheme()
  chart = createChart(container.value, {
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
    upColor: theme.up,
    downColor: theme.down,
    borderUpColor: theme.up,
    borderDownColor: theme.down,
    wickUpColor: theme.up,
    wickDownColor: theme.down,
  }, 0)
  emaLines.ema_10 = chart.addSeries(LineSeries, { color: theme.ema10, lineWidth: 1, lastValueVisible: false }, 0)
  emaLines.ema_21 = chart.addSeries(LineSeries, { color: theme.ema21, lineWidth: 2, lastValueVisible: false }, 0)
  emaLines.ema_60 = chart.addSeries(LineSeries, { color: theme.ema60, lineWidth: 1, lastValueVisible: false }, 0)
  candles.attachPrimitive(rangeDetectorPrimitive)
  htdyZk1 = chart.addSeries(LineSeries, { color: theme.htdyZk1, lineWidth: 2, lineStyle: 0, lastValueVisible: false }, 0)
  htdyZd1 = chart.addSeries(LineSeries, { color: theme.htdyZd1, lineWidth: 2, lineStyle: 2, lastValueVisible: false }, 0)
  htdyZd2 = chart.addSeries(LineSeries, { color: theme.htdyZd2, lineWidth: 2, lineStyle: 0, lastValueVisible: false }, 0)
  htdyMarkers = createSeriesMarkers(candles)
  volume = chart.addSeries(HistogramSeries, {
    priceFormat: { type: 'volume' },
  }, 1)
  macdHistogram = chart.addSeries(HistogramSeries, { base: 0, lastValueVisible: false }, 2)
  macdDif = chart.addSeries(LineSeries, { color: theme.macdDif, lineWidth: 1, lastValueVisible: false }, 2)
  macdDea = chart.addSeries(LineSeries, { color: theme.macdDea, lineWidth: 1, lastValueVisible: false }, 2)
  chart.priceScale('right', 1).applyOptions({ scaleMargins: { top: 0.15, bottom: 0.05 } })
  chart.priceScale('right', 2).applyOptions({ scaleMargins: { top: 0.15, bottom: 0.1 } })
  chart.timeScale().subscribeVisibleLogicalRangeChange(onVisibleLogicalRangeChange)
  chart.subscribeCrosshairMove(onCrosshairMove)
  observer = new ResizeObserver(() => resize())
  observer.observe(container.value)
  container.value.addEventListener('pointerup', syncMacdLabelTop)
  replaceBars(props.bars)
})

onUnmounted(() => {
  chart?.timeScale().unsubscribeVisibleLogicalRangeChange(onVisibleLogicalRangeChange)
  chart?.unsubscribeCrosshairMove(onCrosshairMove)
  observer?.disconnect()
  container.value?.removeEventListener('pointerup', syncMacdLabelTop)
  chart?.remove()
})

watch(() => props.period, () => {
  chart?.applyOptions({ timeScale: { timeVisible: !isDaily() } })
})

watch(() => props.visibleMainIndicators, () => {
  renderDerivedSeries()
}, { deep: true })

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
  return bars.map((bar) => ({
    time: chartTime(bar),
    open: bar.open,
    high: bar.high,
    low: bar.low,
    close: bar.close,
  }))
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
  const visibleRange = preserveViewport ? chart?.timeScale().getVisibleLogicalRange() : null
  renderedBars = normalizeBarSeries(bars)
  if (!chart) return
  paginationArmed = false
  renderAllSeries()
  chart.applyOptions({ timeScale: { timeVisible: !isDaily() } })
  if (visibleRange) chart.timeScale().setVisibleLogicalRange(visibleRange)
  else {
    const initialRange = initialChartLogicalRange(renderedBars.length)
    if (initialRange) chart.timeScale().setVisibleLogicalRange(initialRange)
    else chart.timeScale().fitContent()
  }
  requestAnimationFrame(() => {
    const range = chart?.timeScale().getVisibleLogicalRange()
    isNearLeftBoundary = !!range && range.from <= 20
    paginationArmed = true
    syncMacdLabelTop()
  })
}

function prependBars(bars: BarData[]): void {
  if (!chart || !bars.length) return
  const previousLength = renderedBars.length
  const visibleRange = chart.timeScale().getVisibleLogicalRange()
  renderedBars = normalizeBarSeries([...bars, ...renderedBars])
  const prependedCount = renderedBars.length - previousLength
  if (!prependedCount) return
  renderAllSeries()
  if (visibleRange) {
    chart.timeScale().setVisibleLogicalRange({
      from: visibleRange.from + prependedCount,
      to: visibleRange.to + prependedCount,
    })
  }
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

function revealTime(iso: string): boolean {
  if (!chart || isDaily() || !props.bars.length) return false
  const parsed = Date.parse(iso)
  if (!Number.isFinite(parsed)) return false
  const index = renderedBars.findIndex((bar) => Date.parse(bar.time) === parsed)
  if (index < 0) return false
  if (followLatest) {
    followLatest = false
    emit('follow-latest-change', false)
  }
  chart.timeScale().setVisibleLogicalRange({
    from: Math.max(0, index - 48),
    to: Math.min(props.bars.length - 1, index + 8),
  })
  return true
}

function onVisibleLogicalRangeChange(range: LogicalRange | null) {
  if (!range || !renderedBars.length) return
  const isFollowing = range.to >= renderedBars.length - 3
  if (isFollowing !== followLatest) {
    followLatest = isFollowing
    emit('follow-latest-change', isFollowing)
  }
  if (!paginationArmed || props.loading) return
  const nearLeftBoundary = range.from <= 20
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

function renderAllSeries(): void {
  if (!candles || !volume || !chart) return
  candles.setData(barValues(renderedBars))
  volume.setData(volumeValues(renderedBars))
  renderDerivedSeries()
}

function renderDerivedSeries(): void {
  if (!chart || !macdHistogram || !macdDif || !macdDea) return
  derivedData = buildKlineDerivedData(renderedBars, props.visibleMainIndicators, {
    rangeDetector: {
      enabled: props.visibleMainIndicators.includes('range_detector')
        && Boolean(props.rangeDetectorSourceIdentity)
        && Boolean(props.rangeDetectorAnchorTime),
      sourceIdentity: props.rangeDetectorSourceIdentity,
      anchorTime: props.rangeDetectorAnchorTime,
    },
  })
  const theme = resolveChartTheme()

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

  macdDif.setData(chartValues(derivedData.macd.dif))
  macdDea.setData(chartValues(derivedData.macd.dea))
  macdHistogram.setData(chartValues(derivedData.macd.histogram).map((point) => ({
    ...point,
    color: point.value >= 0 ? theme.volumeUp : theme.volumeDown,
  })))

  htdyZk1?.setData(chartValues(derivedData.htdy?.zk1))
  htdyZd1?.setData(chartValues(derivedData.htdy?.zd1))
  htdyZd2?.setData(chartValues(derivedData.htdy?.zd2))
  const renderedMarkers = chartMarkers(mergedDisplayMarkers())
  htdyMarkers?.setMarkers(renderedMarkers)
}

function mergedDisplayMarkers(): KlineMarker[] {
  return mergeKlineMarkers(
    mergeKlineMarkers(derivedData.htdy?.markers ?? [], props.alertMarkers),
    props.researchMarkers,
  )
}

function markersForHoverContext(): KlineMarker[] {
  return mergeKlineMarkers(
    mergeKlineMarkers(derivedData.htdy?.markers ?? [], props.alertMarkers),
    props.researchMarkers,
  )
}

function chartValues(points: KlineValuePoint[] | undefined): Array<{ time: Time; value: number }> {
  if (!points?.length) return []
  const barsByTime = new Map(renderedBars.map((bar) => [bar.time, bar]))
  return points.flatMap((point) => {
    const bar = barsByTime.get(point.time)
    return bar ? [{ time: chartTime(bar), value: point.value }] : []
  })
}

function chartMarkers(markers: KlineMarker[]) {
  const barsByTime = new Map(renderedBars.map((bar) => [markerTimeKey(bar.time), bar]))
  const theme = resolveChartTheme()
  return markers.flatMap((marker) => {
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
}

function markerTimeKey(value: string): string {
  const timestamp = Date.parse(value)
  return Number.isFinite(timestamp) ? `instant:${timestamp}` : `raw:${value}`
}

function chartTime(bar: BarData): Time {
  return toKlineDisplayTimeForPeriod(bar, props.period) as Time
}

function ribbonTime(iso: string): Time | null {
  if (isDaily()) {
    const day = iso.slice(0, 10)
    return /^\d{4}-\d{2}-\d{2}$/.test(day) ? day as Time : null
  }
  const time = toKlineDisplayTimeForPeriod({ time: iso }, props.period)
  return time === 0 ? null : time as UTCTimestamp
}

function sameChartTime(left: Time, right: Time): boolean {
  return chartTimeKey(left) === chartTimeKey(right)
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
  const panes = chart?.panes()
  if (!panes || panes.length < 3) return
  macdLabelTop.value = panes[0].getHeight() + panes[1].getHeight()
}

function resize() {
  if (!container.value || !chart) return
  chart.resize(container.value.clientWidth, container.value.clientHeight)
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
    :data-research-marker-count="researchMarkers.length"
    :data-rendered-marker-count="mergedDisplayMarkers().length"
    :data-rendered-research-marker-count="researchMarkers.length"
    :data-research-marker-ids="researchMarkers.map((marker) => marker.id).join(',')"
    :data-research-marker-times="researchMarkers.map((marker) => marker.time).join(',')"
    :data-range-detector-range-count="derivedData.rangeDetector?.ranges.length ?? 0"
  >
    <div ref="container" class="chart" />
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
      MACD
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
