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
  type Time,
  type UTCTimestamp,
} from 'lightweight-charts'
import KlineHoverLegend from '@/components/kline/KlineHoverLegend.vue'
import { NStructureBandPrimitive } from '@/components/kline/NStructureBandPrimitive'
import type {
  BarData,
  HoverKlineContext,
  KlineMarker,
  MainIndicatorId,
  NStructureBand,
  SeriesKind,
} from '@/types/market'
import { resolveChartTheme } from '@/styles/chartTheme'
import { formatChartAxisTimeInShanghai, formatChartTimeInShanghai } from '@/utils/barTime'
import { normalizeBarSeries } from '@/utils/barSeries'
import { initialChartLogicalRange } from '@/utils/chartViewport'
import {
  buildKlineDerivedData,
  resolveKlineHoverContext,
  type KlineValuePoint,
} from '@/utils/klineViewModel'
import { mergeKlineMarkers } from '@/utils/alertMarkers'

const props = withDefaults(defineProps<{
  bars: BarData[]
  loading?: boolean
  error?: string | null
  period?: string
  seriesKind: SeriesKind
  visibleMainIndicators?: MainIndicatorId[]
  alertMarkers?: KlineMarker[]
  researchMarkers?: KlineMarker[]
  nStructureBands?: NStructureBand[]
}>(), {
  loading: false,
  error: null,
  period: '15m',
  visibleMainIndicators: () => [],
  alertMarkers: () => [],
  researchMarkers: () => [],
  nStructureBands: () => [],
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
let nStructureBandPrimitive: NStructureBandPrimitive | null = null
const emaLines: Partial<Record<EmaIndicatorId, ISeriesApi<'Line'>>> = {}
let observer: ResizeObserver | null = null
let renderedBars: BarData[] = []
let isNearLeftBoundary = false
let paginationArmed = false
let followLatest = true
const hoverContext = ref<HoverKlineContext | null>(null)
const macdLabelTop = ref<number | null>(null)
const renderedResearchMarkerCount = ref(0)
const renderedNStructureBandCount = ref(0)
const renderedNStructureOverlapGroupCount = ref(0)
const renderedNStructureSuppressedCount = ref(0)
const renderedNStructureOverlapLabel = ref('')
const renderedNStructureOverlapLabelPoint = ref('')
const renderedNStructureOverlapBadges = ref<Array<{
  externalId: string
  label: string
  x: number
  y: number
  direction: 'up' | 'down'
}>>([])
const hoveredNStructureBand = ref<NStructureBand | null>(null)
const hoveredNStructureOverlap = ref<{ groupId: string; count: number; position: number } | null>(null)
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
    timeScale: {
      borderColor: theme.axis,
      timeVisible: !isDaily(),
      tickMarkFormatter: (time: Time) => formatChartAxisTimeInShanghai(time),
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
  nStructureBandPrimitive = new NStructureBandPrimitive(
    { up: theme.up, down: theme.down },
    () => syncNStructureBandDiagnostics(),
  )
  candles.attachPrimitive(nStructureBandPrimitive)
  emaLines.ema_10 = chart.addSeries(LineSeries, { color: theme.ema10, lineWidth: 1, lastValueVisible: false }, 0)
  emaLines.ema_21 = chart.addSeries(LineSeries, { color: theme.ema21, lineWidth: 2, lastValueVisible: false }, 0)
  emaLines.ema_60 = chart.addSeries(LineSeries, { color: theme.ema60, lineWidth: 1, lastValueVisible: false }, 0)
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
  chart.subscribeClick(onChartClick)
  observer = new ResizeObserver(() => resize())
  observer.observe(container.value)
  container.value.addEventListener('pointerup', syncMacdLabelTop)
  replaceBars(props.bars)
})

onUnmounted(() => {
  chart?.timeScale().unsubscribeVisibleLogicalRangeChange(onVisibleLogicalRangeChange)
  chart?.unsubscribeCrosshairMove(onCrosshairMove)
  chart?.unsubscribeClick(onChartClick)
  observer?.disconnect()
  container.value?.removeEventListener('pointerup', syncMacdLabelTop)
  if (candles && nStructureBandPrimitive) candles.detachPrimitive(nStructureBandPrimitive)
  chart?.remove()
})

watch(() => props.period, () => {
  chart?.applyOptions({ timeScale: { timeVisible: !isDaily() } })
})

watch(() => props.visibleMainIndicators, () => {
  renderDerivedSeries()
}, { deep: true })

watch(() => props.alertMarkers, () => {
  renderDerivedSeries()
}, { deep: true })

watch(() => props.researchMarkers, () => {
  renderDerivedSeries()
}, { deep: true })

watch(() => props.nStructureBands, () => {
  renderNStructureBands()
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

function onVisibleLogicalRangeChange(range: LogicalRange | null) {
  if (!range || !renderedBars.length) return
  if (nStructureBandPrimitive?.resetOverlapSelection()) {
    hoveredNStructureBand.value = null
    hoveredNStructureOverlap.value = null
    syncNStructureBandDiagnostics()
  }
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
  const hoveredObjectId = param.hoveredInfo?.objectId ?? param.hoveredObjectId
  if (param.time === undefined) {
    if (nStructureBandPrimitive?.resetOverlapSelection()) syncNStructureBandDiagnostics()
    hoveredNStructureBand.value = null
    hoveredNStructureOverlap.value = null
    hoverContext.value = null
    emit('crosshair-change', null)
    return
  }
  const externalId = typeof hoveredObjectId === 'string' ? hoveredObjectId : undefined
  let nextOverlap = nStructureBandPrimitive?.overlapInfoByExternalId(externalId) ?? null
  if (
    hoveredNStructureOverlap.value
    && hoveredNStructureOverlap.value.groupId !== nextOverlap?.groupId
    && nStructureBandPrimitive?.resetOverlapSelection()
  ) {
    syncNStructureBandDiagnostics()
    nextOverlap = nStructureBandPrimitive.overlapInfoByExternalId(externalId)
  }
  hoveredNStructureBand.value = nStructureBandPrimitive?.bandByExternalId(externalId) ?? null
  hoveredNStructureOverlap.value = nextOverlap
  const bar = renderedBars.find((item) => sameChartTime(chartTime(item), param.time!))
  const nextContext = bar
    ? resolveKlineHoverContext(
      renderedBars,
      derivedData,
      props.visibleMainIndicators,
      bar.time,
      mergedDisplayMarkers(),
    )
    : null
  hoverContext.value = nextContext
  emit('crosshair-change', nextContext)
}

function onChartClick(param: MouseEventParams<Time>) {
  const hoveredObjectId = param.hoveredInfo?.objectId ?? param.hoveredObjectId
  const externalId = typeof hoveredObjectId === 'string' ? hoveredObjectId : undefined
  if (!nStructureBandPrimitive?.cycleOverlapGroupByExternalId(externalId)) return
  hoveredNStructureBand.value = nStructureBandPrimitive.bandByExternalId(externalId)
  hoveredNStructureOverlap.value = nStructureBandPrimitive.overlapInfoByExternalId(externalId)
  syncNStructureBandDiagnostics()
}

function onOverlapBadgeEnter(externalId: string): void {
  hoveredNStructureBand.value = nStructureBandPrimitive?.bandByExternalId(externalId) ?? null
  hoveredNStructureOverlap.value = nStructureBandPrimitive?.overlapInfoByExternalId(externalId) ?? null
}

function onOverlapBadgeClick(externalId: string): void {
  if (!nStructureBandPrimitive?.cycleOverlapGroupByExternalId(externalId)) return
  hoveredNStructureBand.value = nStructureBandPrimitive.bandByExternalId(externalId)
  hoveredNStructureOverlap.value = nStructureBandPrimitive.overlapInfoByExternalId(externalId)
  syncNStructureBandDiagnostics()
}

function onOverlapBadgeLeave(): void {
  if (nStructureBandPrimitive?.resetOverlapSelection()) syncNStructureBandDiagnostics()
  hoveredNStructureBand.value = null
  hoveredNStructureOverlap.value = null
}

function renderAllSeries(): void {
  if (!candles || !volume || !chart) return
  candles.setData(barValues(renderedBars))
  volume.setData(volumeValues(renderedBars))
  renderNStructureBands()
  renderDerivedSeries()
}

function renderNStructureBands(): void {
  nStructureBandPrimitive?.setData(props.nStructureBands, renderedBars[0]?.time ?? '')
  syncNStructureBandDiagnostics()
  if (
    hoveredNStructureBand.value
    && !props.nStructureBands.some((band) => band.band_id === hoveredNStructureBand.value?.band_id)
  ) {
    hoveredNStructureBand.value = null
    hoveredNStructureOverlap.value = null
  }
}

function syncNStructureBandDiagnostics(): void {
  const geometry = nStructureBandPrimitive?.currentGeometry() ?? []
  renderedNStructureBandCount.value = geometry.length
  renderedNStructureOverlapGroupCount.value = new Set(
    geometry.flatMap((item) => item.overlapGroupId ? [item.overlapGroupId] : []),
  ).size
  renderedNStructureSuppressedCount.value = geometry.filter((item) => item.isOverlapSuppressed).length
  const primary = geometry.find((item) => item.overlapCount >= 3 && item.isOverlapPrimary)
  renderedNStructureOverlapBadges.value = geometry.flatMap((item) => (
    item.overlapCount >= 3 && item.isOverlapPrimary && item.overlapGroupId && item.labelVisible
      ? [{
          externalId: `n-structure-band-group:${item.overlapGroupId}`,
          label: item.overlapLabel,
          x: item.labelX,
          y: item.labelY,
          direction: item.band.direction,
        }]
      : []
  ))
  renderedNStructureOverlapLabel.value = primary?.overlapLabel ?? ''
  renderedNStructureOverlapLabelPoint.value = primary
    ? `${primary.labelX},${primary.labelY}`
    : ''
}

function formatNStructureBandTime(value: string): string {
  const timestamp = Date.parse(value)
  if (!Number.isFinite(timestamp)) return value
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(timestamp))
}

function renderDerivedSeries(): void {
  renderedResearchMarkerCount.value = 0
  if (!chart || !macdHistogram || !macdDif || !macdDea) return
  derivedData = buildKlineDerivedData(renderedBars, props.visibleMainIndicators)
  const theme = resolveChartTheme()

  EMA_INDICATORS.forEach((indicator) => {
    emaLines[indicator]?.setData(chartValues(derivedData.ema[indicator]))
  })

  macdDif.setData(chartValues(derivedData.macd.dif))
  macdDea.setData(chartValues(derivedData.macd.dea))
  macdHistogram.setData(chartValues(derivedData.macd.histogram).map((point) => ({
    ...point,
    color: point.value >= 0 ? theme.volumeUp : theme.volumeDown,
  })))

  htdyZk1?.setData(chartValues(derivedData.htdy?.zk1))
  htdyZd1?.setData(chartValues(derivedData.htdy?.zd1))
  htdyZd2?.setData(chartValues(derivedData.htdy?.zd2))
  renderedResearchMarkerCount.value = chartMarkers(props.researchMarkers).length
  const renderedMarkers = chartMarkers(mergedDisplayMarkers())
  htdyMarkers?.setMarkers(renderedMarkers)
}

function mergedDisplayMarkers(): KlineMarker[] {
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
  if (isDaily()) return (bar.trading_day || bar.time.slice(0, 10)) as Time
  return Math.floor(new Date(bar.time).getTime() / 1000) as UTCTimestamp
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
  if (nStructureBandPrimitive?.resetOverlapSelection()) {
    hoveredNStructureBand.value = null
    hoveredNStructureOverlap.value = null
    syncNStructureBandDiagnostics()
  }
  chart.resize(container.value.clientWidth, container.value.clientHeight)
  requestAnimationFrame(syncMacdLabelTop)
}

defineExpose({
  replaceBars,
  prependBars,
  updateBar,
  scrollToLatest,
})
</script>

<template>
  <div
    class="kline-shell"
    data-testid="kline-shell"
    :data-alert-marker-count="alertMarkers.length"
    :data-research-marker-count="researchMarkers.length"
    :data-rendered-research-marker-count="renderedResearchMarkerCount"
    :data-research-marker-ids="researchMarkers.map((marker) => marker.id).join(',')"
    :data-research-marker-times="researchMarkers.map((marker) => marker.time).join(',')"
    :data-n-structure-band-count="nStructureBands.length"
    :data-rendered-n-structure-band-count="renderedNStructureBandCount"
    :data-n-structure-overlap-group-count="renderedNStructureOverlapGroupCount"
    :data-n-structure-suppressed-count="renderedNStructureSuppressedCount"
    :data-n-structure-overlap-label="renderedNStructureOverlapLabel"
    :data-n-structure-overlap-label-point="renderedNStructureOverlapLabelPoint"
    :data-n-structure-band-directions="[...new Set(nStructureBands.map((band) => band.direction))].join(',')"
  >
    <div ref="container" class="chart" />
    <button
      v-for="badge in renderedNStructureOverlapBadges"
      :key="badge.externalId"
      type="button"
      class="n-structure-overlap-badge"
      :class="`n-structure-overlap-badge--${badge.direction}`"
      :style="{ left: `${badge.x}px`, top: `${badge.y}px` }"
      :aria-label="badge.label"
      @pointerenter="onOverlapBadgeEnter(badge.externalId)"
      @pointerleave="onOverlapBadgeLeave"
      @focus="onOverlapBadgeEnter(badge.externalId)"
      @blur="onOverlapBadgeLeave"
      @click.stop="onOverlapBadgeClick(badge.externalId)"
    >
      {{ badge.label }}
    </button>
    <KlineHoverLegend
      :context="hoverContext"
      :show-macd="true"
    />
    <div
      v-if="hoveredNStructureBand"
      class="n-structure-band-tooltip"
      data-testid="n-structure-band-tooltip"
    >
      <strong>{{ hoveredNStructureBand.direction === 'up' ? 'N↑ 上涨' : 'N↓ 下跌' }}</strong>
      <span>{{ hoveredNStructureBand.contract }} · {{ hoveredNStructureBand.lower }}–{{ hoveredNStructureBand.upper }}</span>
      <span>完成 {{ formatNStructureBandTime(hoveredNStructureBand.completed_at) }}</span>
      <span v-if="hoveredNStructureOverlap">
        同方向重叠 {{ hoveredNStructureOverlap.count }} 条 · 当前 {{ hoveredNStructureOverlap.position }}/{{ hoveredNStructureOverlap.count }}
      </span>
      <span v-if="hoveredNStructureBand.invalidated_at">
        N2 起点破坏 {{ formatNStructureBandTime(hoveredNStructureBand.invalidated_at) }}
      </span>
      <span v-else-if="hoveredNStructureBand.first_reentered_at">
        首次回到区间 {{ formatNStructureBandTime(hoveredNStructureBand.first_reentered_at) }}
      </span>
      <span v-else>
        尚未回到区间 · 观察至 {{ formatNStructureBandTime(hoveredNStructureBand.expanded_until) }}
      </span>
      <small>历史确认 · 研究观察</small>
    </div>
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
.n-structure-overlap-badge { position: absolute; z-index: 3; height: 16px; border: 0; border-radius: 2px; padding: 0 2px; background: rgba(255, 255, 255, .82); font: 600 11px/16px -apple-system, BlinkMacSystemFont, sans-serif; cursor: pointer; }
.n-structure-overlap-badge:hover { background: rgba(255, 255, 255, .98); box-shadow: 0 0 0 1px currentColor; }
.n-structure-overlap-badge--up { color: var(--gy-up); }
.n-structure-overlap-badge--down { color: var(--gy-down); }
.secondary-panel-label { position: absolute; z-index: 3; left: 10px; min-height: 26px; padding: 3px 8px; background: color-mix(in srgb, var(--gy-bg-panel) 88%, transparent); color: var(--gy-text-primary); font-size: var(--gy-font-size-xs); font-weight: 600; pointer-events: none; }
.htdy-legend { position: absolute; z-index: 2; top: 52px; right: 72px; display: flex; gap: 12px; align-items: center; padding: 5px 9px; border: 1px solid var(--gy-border); border-radius: var(--gy-radius-sm); background: rgba(255, 255, 255, .9); color: var(--gy-text-secondary); font-size: var(--gy-font-size-xs); pointer-events: none; box-shadow: var(--gy-shadow-sm); }
.htdy-legend span { display: inline-flex; gap: 5px; align-items: center; white-space: nowrap; }
.htdy-legend__line { display: inline-block; width: 18px; border-top: 2px solid; }
.htdy-legend__line--zk1 { border-color: var(--gy-chart-htdy-zk1); }
.htdy-legend__line--zd1 { border-color: var(--gy-chart-htdy-zd1); border-top-style: dashed; }
.htdy-legend__line--zd2 { border-color: var(--gy-chart-htdy-zd2); }
.n-structure-band-tooltip { position: absolute; z-index: 4; top: 88px; right: 72px; display: grid; gap: 3px; min-width: 190px; padding: 8px 10px; border: 1px solid var(--gy-border); border-radius: var(--gy-radius-sm); background: rgba(255, 255, 255, .96); color: var(--gy-text-secondary); font-size: var(--gy-font-size-xs); pointer-events: none; box-shadow: var(--gy-shadow-sm); }
.n-structure-band-tooltip strong { color: var(--gy-text-primary); }
.n-structure-band-tooltip small { color: var(--gy-text-muted); }
.overlay { position: absolute; inset: 0; display: grid; place-items: center; color: var(--gy-text-muted); background: rgba(11, 17, 27, .48); pointer-events: none; }
.overlay.error { color: var(--gy-status-error); }

@media (max-width: 980px) {
  .secondary-panel-label { right: 10px; }
}
</style>
