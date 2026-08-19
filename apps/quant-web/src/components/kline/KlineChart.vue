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
import type { BarData, HoverKlineContext, KlineMarker, MainIndicatorId } from '@/types/market'
import { resolveChartTheme } from '@/styles/chartTheme'
import { formatChartAxisTimeInShanghai, formatChartTimeInShanghai } from '@/utils/barTime'
import { normalizeBarSeries } from '@/utils/barSeries'
import { buildKlineDerivedData, resolveKlineHoverContext, type KlineValuePoint } from '@/utils/klineViewModel'
import { mergeKlineMarkers } from '@/utils/alertMarkers'
import {
  calculateMainForceMirror,
  type MainForceMirrorState,
} from '@/utils/mainForceMirror'

const props = withDefaults(defineProps<{
  bars: BarData[]
  loading?: boolean
  error?: string | null
  period?: string
  visibleMainIndicators?: MainIndicatorId[]
  alertMarkers?: KlineMarker[]
}>(), {
  loading: false,
  error: null,
  period: '15m',
  visibleMainIndicators: () => [],
  alertMarkers: () => [],
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
let mainForceHistogram: ISeriesApi<'Histogram'> | null = null
let mainForceCaution: ISeriesApi<'Histogram'> | null = null
let mainForceMarkers: ISeriesMarkersPluginApi<Time> | null = null
let htdyZk1: ISeriesApi<'Line'> | null = null
let htdyZd1: ISeriesApi<'Line'> | null = null
let htdyZd2: ISeriesApi<'Line'> | null = null
let htdyMarkers: ISeriesMarkersPluginApi<Time> | null = null
const emaLines: Partial<Record<EmaIndicatorId, ISeriesApi<'Line'>>> = {}
let observer: ResizeObserver | null = null
let renderedBars: BarData[] = []
let isNearLeftBoundary = false
let paginationArmed = false
let followLatest = true
const hoverContext = ref<HoverKlineContext | null>(null)
const secondaryPanelTop = ref<number | null>(null)
let derivedData = buildKlineDerivedData([], [])

type EmaIndicatorId = 'ema_10' | 'ema_21' | 'ema_60'
type SecondaryPanelId = 'macd' | 'main_force_mirror'
const EMA_INDICATORS: EmaIndicatorId[] = ['ema_10', 'ema_21', 'ema_60']
const selectedSecondaryPanel = ref<SecondaryPanelId>('macd')
const SECONDARY_PANEL_TABS: Array<{ id: SecondaryPanelId; label: string }> = [
  { id: 'macd', label: 'MACD' },
  { id: 'main_force_mirror', label: '主力照妖镜' },
]
const MAIN_FORCE_COLORS: Record<MainForceMirrorState, string> = {
  entry: '#ef4444',
  wash: '#22c55e',
  pull_up: '#3b82f6',
  distribute: '#eab308',
  exit: '#06b6d4',
  lure: '#f97316',
}
const CAUTION_COLOR = '#22c55e'

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
  mainForceHistogram = chart.addSeries(HistogramSeries, { base: 0, lastValueVisible: false, priceLineVisible: false }, 2)
  mainForceCaution = chart.addSeries(HistogramSeries, { base: 0, lastValueVisible: false, priceLineVisible: false }, 2)
  mainForceMarkers = createSeriesMarkers(mainForceCaution)
  chart.priceScale('right', 1).applyOptions({ scaleMargins: { top: 0.15, bottom: 0.05 } })
  chart.priceScale('right', 2).applyOptions({ scaleMargins: { top: 0.15, bottom: 0.1 } })
  chart.timeScale().subscribeVisibleLogicalRangeChange(onVisibleLogicalRangeChange)
  chart.subscribeCrosshairMove(onCrosshairMove)
  observer = new ResizeObserver(() => resize())
  observer.observe(container.value)
  container.value.addEventListener('pointerup', syncSecondaryPanelTop)
  replaceBars(props.bars)
})

onUnmounted(() => {
  chart?.timeScale().unsubscribeVisibleLogicalRangeChange(onVisibleLogicalRangeChange)
  chart?.unsubscribeCrosshairMove(onCrosshairMove)
  observer?.disconnect()
  container.value?.removeEventListener('pointerup', syncSecondaryPanelTop)
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

watch(selectedSecondaryPanel, () => {
  renderDerivedSeries()
})

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
  else chart.timeScale().fitContent()
  requestAnimationFrame(() => {
    const range = chart?.timeScale().getVisibleLogicalRange()
    isNearLeftBoundary = !!range && range.from <= 20
    paginationArmed = true
    syncSecondaryPanelTop()
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
    ? resolveKlineHoverContext(renderedBars, derivedData, props.visibleMainIndicators, bar.time)
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
  if (!chart || !macdHistogram || !macdDif || !macdDea || !mainForceHistogram || !mainForceCaution) return
  derivedData = buildKlineDerivedData(renderedBars, props.visibleMainIndicators)
  const theme = resolveChartTheme()

  EMA_INDICATORS.forEach((indicator) => {
    emaLines[indicator]?.setData(chartValues(derivedData.ema[indicator]))
  })

  if (selectedSecondaryPanel.value === 'macd') {
    macdDif.setData(chartValues(derivedData.macd.dif))
    macdDea.setData(chartValues(derivedData.macd.dea))
    macdHistogram.setData(chartValues(derivedData.macd.histogram).map((point) => ({
      ...point,
      color: point.value >= 0 ? theme.volumeUp : theme.volumeDown,
    })))
    mainForceHistogram.setData([])
    mainForceCaution.setData([])
    mainForceMarkers?.setMarkers([])
  } else {
    macdDif.setData([])
    macdDea.setData([])
    macdHistogram.setData([])
    renderMainForceMirror()
  }

  htdyZk1?.setData(chartValues(derivedData.htdy?.zk1))
  htdyZd1?.setData(chartValues(derivedData.htdy?.zd1))
  htdyZd2?.setData(chartValues(derivedData.htdy?.zd2))
  htdyMarkers?.setMarkers(chartMarkers(mergeKlineMarkers(
    derivedData.htdy?.markers ?? [],
    props.alertMarkers,
  )))
}

function renderMainForceMirror() {
  if (!mainForceHistogram || !mainForceCaution) return
  const observation = calculateMainForceMirror(renderedBars)
  mainForceHistogram.setData(observation.points.flatMap((point, index) => {
    if (point.value === null || point.state === null || !renderedBars[index]) return []
    return [{
      time: chartTime(renderedBars[index]),
      value: point.value,
      color: MAIN_FORCE_COLORS[point.state],
    }]
  }))
  mainForceCaution.setData(observation.points.flatMap((point, index) => {
    if (point.cautionLevel === null || !renderedBars[index]) return []
    return [{
      time: chartTime(renderedBars[index]),
      value: point.cautionLevel,
      color: CAUTION_COLOR,
    }]
  }))
  mainForceMarkers?.setMarkers(observation.points.flatMap((point, index) => {
    if (!point.caution || !renderedBars[index]) return []
    return [{
      time: chartTime(renderedBars[index]),
      position: 'aboveBar' as const,
      shape: 'arrowUp' as const,
      color: CAUTION_COLOR,
      text: '小心',
      size: 1.5,
    }]
  }))
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

function syncSecondaryPanelTop() {
  const panes = chart?.panes()
  if (!panes || panes.length < 3) return
  secondaryPanelTop.value = panes[0].getHeight() + panes[1].getHeight()
}

function resize() {
  if (!container.value || !chart) return
  chart.resize(container.value.clientWidth, container.value.clientHeight)
  requestAnimationFrame(syncSecondaryPanelTop)
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
    :data-secondary-panel="selectedSecondaryPanel"
  >
    <div ref="container" class="chart" />
    <KlineHoverLegend
      :context="hoverContext"
      :show-macd="selectedSecondaryPanel === 'macd'"
    />
    <div
      class="secondary-panel-header"
      data-testid="secondary-panel-tabs"
      role="tablist"
      aria-label="副图指标"
      :style="{ top: secondaryPanelTop === null ? '80%' : `${secondaryPanelTop + 5}px` }"
    >
      <button
        v-for="item in SECONDARY_PANEL_TABS"
        :key="item.id"
        type="button"
        class="secondary-panel-tab"
        :class="{ 'secondary-panel-tab--active': selectedSecondaryPanel === item.id }"
        role="tab"
        :aria-selected="selectedSecondaryPanel === item.id"
        @click="selectedSecondaryPanel = item.id"
      >{{ item.label }}</button>
      <div v-if="selectedSecondaryPanel === 'main_force_mirror'" class="main-force-legend" aria-label="主力照妖镜图例">
        <span><i class="mirror-dot mirror-dot--entry" />进场</span>
        <span><i class="mirror-dot mirror-dot--wash" />洗盘</span>
        <span><i class="mirror-dot mirror-dot--pull" />拉高</span>
        <span><i class="mirror-dot mirror-dot--distribute" />出货</span>
        <span><i class="mirror-dot mirror-dot--exit" />退场</span>
        <span><i class="mirror-dot mirror-dot--lure" />诱多</span>
        <span class="main-force-legend__note">小心＝HHV5/BARSLAST10 结构警戒，非实测资金流</span>
      </div>
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
.secondary-panel-header { position: absolute; z-index: 3; left: 10px; display: flex; align-items: center; gap: 6px; max-width: calc(100% - 84px); min-height: 26px; pointer-events: auto; }
.secondary-panel-tab { appearance: none; border: 0; border-bottom: 2px solid transparent; padding: 3px 8px; background: color-mix(in srgb, var(--gy-bg-panel) 88%, transparent); color: var(--gy-text-muted); font: inherit; font-size: var(--gy-font-size-xs); cursor: pointer; }
.secondary-panel-tab:hover { color: var(--gy-text-primary); }
.secondary-panel-tab--active { border-bottom-color: var(--gy-accent); color: var(--gy-text-primary); font-weight: 600; }
.main-force-legend { display: flex; align-items: center; gap: 7px; min-width: 0; color: var(--gy-text-muted); font-size: var(--gy-font-size-xs); }
.main-force-legend span { display: inline-flex; align-items: center; gap: 3px; white-space: nowrap; }
.main-force-legend__note { overflow: hidden; max-width: 340px; text-overflow: ellipsis; }
.mirror-dot { width: 7px; height: 7px; border-radius: 50%; }
.mirror-dot--entry { background: #ef4444; }
.mirror-dot--wash { background: #22c55e; }
.mirror-dot--pull { background: #3b82f6; }
.mirror-dot--distribute { background: #eab308; }
.mirror-dot--exit { background: #06b6d4; }
.mirror-dot--lure { background: #f97316; }
.htdy-legend { position: absolute; z-index: 2; top: 52px; right: 72px; display: flex; gap: 12px; align-items: center; padding: 5px 9px; border: 1px solid var(--gy-border); border-radius: var(--gy-radius-sm); background: rgba(255, 255, 255, .9); color: var(--gy-text-secondary); font-size: var(--gy-font-size-xs); pointer-events: none; box-shadow: var(--gy-shadow-sm); }
.htdy-legend span { display: inline-flex; gap: 5px; align-items: center; white-space: nowrap; }
.htdy-legend__line { display: inline-block; width: 18px; border-top: 2px solid; }
.htdy-legend__line--zk1 { border-color: var(--gy-chart-htdy-zk1); }
.htdy-legend__line--zd1 { border-color: var(--gy-chart-htdy-zd1); border-top-style: dashed; }
.htdy-legend__line--zd2 { border-color: var(--gy-chart-htdy-zd2); }
.overlay { position: absolute; inset: 0; display: grid; place-items: center; color: var(--gy-text-muted); background: rgba(11, 17, 27, .48); pointer-events: none; }
.overlay.error { color: var(--gy-status-error); }

@media (max-width: 980px) {
  .main-force-legend span:not(.main-force-legend__note) { display: none; }
  .main-force-legend__note { max-width: 240px; }
}
</style>
