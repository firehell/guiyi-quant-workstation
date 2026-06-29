<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  HistogramSeries,
  LineSeries,
  LineStyle,
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type LineData,
  type LogicalRange,
  type MouseEventParams,
  type SeriesMarker,
  type Time,
  type WhitespaceData,
} from 'lightweight-charts'
import type { BarData, ChartOverlay, HoverKlineContext, IndicatorPanelType, KlineMarker } from '@/types/market'
import { calculateATR, calculateEMA, calculateMACD } from '@/utils/indicators'

const LINKED_PRICE_SCALE_MIN_WIDTH = 76

const props = defineProps<{
  bars: BarData[]
  markers?: KlineMarker[]
  activeMarkerId?: string | null
  overlays?: ChartOverlay[]
  loading?: boolean
  error?: string | null
}>()

const emit = defineEmits<{
  hover: [context: HoverKlineContext | null]
}>()

const mainContainer = ref<HTMLElement>()
const macdContainer = ref<HTMLElement>()
const atrContainer = ref<HTMLElement>()
const activePanel = ref<IndicatorPanelType>('macd')
const hoverContext = ref<HoverKlineContext | null>(null)

let mainChart: IChartApi | null = null
let macdChart: IChartApi | null = null
let atrChart: IChartApi | null = null
let candleSeries: ISeriesApi<'Candlestick'> | null = null
let volumeSeries: ISeriesApi<'Histogram'> | null = null
let emaSeries: ISeriesApi<'Line'> | null = null
let markerLayer: ISeriesMarkersPluginApi<Time> | null = null
let macdDifSeries: ISeriesApi<'Line'> | null = null
let macdDeaSeries: ISeriesApi<'Line'> | null = null
let macdHistogramSeries: ISeriesApi<'Histogram'> | null = null
let atrSeries: ISeriesApi<'Line'> | null = null
let resizeObserver: ResizeObserver | null = null
let syncingRange = false
let syncingCrosshair = false
let priceLines: IPriceLine[] = []

const barByTime = new Map<string, BarData>()
const markerByTime = new Map<string, KlineMarker>()
const emaByTime = new Map<string, number>()
const macdByTime = new Map<string, { dif?: number; dea?: number; histogram?: number }>()
const atrByTime = new Map<string, number>()

const hasData = computed(() => props.bars.length > 0)
const indicatorTabs: Array<{ label: string; value: IndicatorPanelType }> = [
  { label: 'MACD', value: 'macd' },
  { label: 'ATR', value: 'atr' },
]

onMounted(async () => {
  await nextTick()
  createCharts()
  renderSeries()
  observeResize()
})

onUnmounted(() => {
  resizeObserver?.disconnect()
  removePriceLines()
  mainChart?.remove()
  macdChart?.remove()
  atrChart?.remove()
})

watch(
  () => [props.bars, props.markers, props.activeMarkerId, props.overlays],
  () => renderSeries(),
  { deep: true },
)

watch(activePanel, async () => {
  await nextTick()
  resizeCharts()
  syncAllRanges(mainChart?.timeScale().getVisibleLogicalRange() || null, mainChart)
  if (hoverContext.value) syncCrosshairForTime(toChartTime(hoverContext.value.time))
})

function createCharts() {
  if (!mainContainer.value || !macdContainer.value || !atrContainer.value) return

  mainChart = createChart(mainContainer.value, {
    width: mainContainer.value.clientWidth,
    height: 430,
    layout: {
      background: { type: ColorType.Solid, color: '#101318' },
      textColor: '#b8c0cc',
    },
    grid: {
      vertLines: { color: '#252a32' },
      horzLines: { color: '#252a32' },
    },
    rightPriceScale: {
      borderColor: '#3a404b',
      minimumWidth: LINKED_PRICE_SCALE_MIN_WIDTH,
      scaleMargins: { top: 0.08, bottom: 0.22 },
    },
    timeScale: { borderColor: '#3a404b', timeVisible: true, secondsVisible: false },
    crosshair: { mode: 1 },
  })

  candleSeries = mainChart.addSeries(CandlestickSeries, {
    upColor: '#ef4444',
    downColor: '#22c55e',
    borderUpColor: '#ef4444',
    borderDownColor: '#22c55e',
    wickUpColor: '#ef4444',
    wickDownColor: '#22c55e',
  })
  markerLayer = createSeriesMarkers(candleSeries, [])
  emaSeries = mainChart.addSeries(LineSeries, {
    color: '#f59e0b',
    lineWidth: 2,
    priceLineVisible: false,
    lastValueVisible: false,
  })
  volumeSeries = mainChart.addSeries(HistogramSeries, {
    priceFormat: { type: 'volume' },
    priceScaleId: '',
    priceLineVisible: false,
    lastValueVisible: false,
  })
  mainChart.priceScale('').applyOptions({ scaleMargins: { top: 0.78, bottom: 0 } })

  macdChart = createSubChart(macdContainer.value, 150)
  macdHistogramSeries = macdChart.addSeries(HistogramSeries, {
    priceLineVisible: false,
    lastValueVisible: false,
  })
  macdDifSeries = macdChart.addSeries(LineSeries, {
    color: '#38bdf8',
    lineWidth: 1,
    priceLineVisible: false,
    lastValueVisible: false,
  })
  macdDeaSeries = macdChart.addSeries(LineSeries, {
    color: '#f59e0b',
    lineWidth: 1,
    priceLineVisible: false,
    lastValueVisible: false,
  })

  atrChart = createSubChart(atrContainer.value, 150)
  atrSeries = atrChart.addSeries(LineSeries, {
    color: '#a78bfa',
    lineWidth: 1,
    priceLineVisible: false,
    lastValueVisible: false,
  })
  setupLinkedChartController()
}

function createSubChart(container: HTMLElement, height: number) {
  return createChart(container, {
    width: container.clientWidth,
    height,
    layout: {
      background: { type: ColorType.Solid, color: '#101318' },
      textColor: '#8d97a7',
    },
    grid: {
      vertLines: { color: '#252a32' },
      horzLines: { color: '#252a32' },
    },
    rightPriceScale: { borderColor: '#3a404b', minimumWidth: LINKED_PRICE_SCALE_MIN_WIDTH },
    timeScale: { borderColor: '#3a404b', timeVisible: true, secondsVisible: false },
    crosshair: { mode: 1 },
  })
}

function setupLinkedChartController() {
  mainChart?.timeScale().subscribeVisibleLogicalRangeChange((range) => syncAllRanges(range, mainChart))
  macdChart?.timeScale().subscribeVisibleLogicalRangeChange((range) => syncAllRanges(range, macdChart))
  atrChart?.timeScale().subscribeVisibleLogicalRangeChange((range) => syncAllRanges(range, atrChart))
  mainChart?.subscribeCrosshairMove((param) => syncCrosshair(param, mainChart))
  macdChart?.subscribeCrosshairMove((param) => syncCrosshair(param, macdChart))
  atrChart?.subscribeCrosshairMove((param) => syncCrosshair(param, atrChart))
}

function renderSeries() {
  if (!candleSeries || !volumeSeries || !emaSeries || !macdDifSeries || !macdDeaSeries || !macdHistogramSeries || !atrSeries) return

  rebuildLookupMaps()
  const candleData: CandlestickData<Time>[] = props.bars.map((bar) => ({
    time: toChartTime(bar.time),
    open: bar.open,
    high: bar.high,
    low: bar.low,
    close: bar.close,
  }))
  const volumeData: HistogramData<Time>[] = props.bars.map((bar) => ({
    time: toChartTime(bar.time),
    value: bar.volume,
    color: bar.close >= bar.open ? 'rgba(239, 68, 68, 0.45)' : 'rgba(34, 197, 94, 0.45)',
  }))
  const chartTimes = props.bars.map((bar) => toChartTime(bar.time))
  const emaData = toAlignedLineData(chartTimes, calculateEMA(props.bars, 21))
  const macd = calculateMACD(props.bars)
  const macdDifData = toAlignedLineData(chartTimes, macd.dif)
  const macdDeaData = toAlignedLineData(chartTimes, macd.dea)
  const macdHistogramData = toAlignedHistogramData(chartTimes, macd.histogram)
  const atrData = toAlignedLineData(chartTimes, calculateATR(props.bars, 14))

  candleSeries.setData(candleData)
  markerLayer?.setMarkers(toSeriesMarkers(props.markers || [], props.activeMarkerId || null))
  volumeSeries.setData(volumeData)
  emaSeries.setData(emaData)
  macdDifSeries.setData(macdDifData)
  macdDeaSeries.setData(macdDeaData)
  macdHistogramSeries.setData(macdHistogramData)
  atrSeries.setData(atrData)
  applyPriceLines()
  if (props.bars.length > 0) {
    mainChart?.timeScale().fitContent()
    macdChart?.timeScale().fitContent()
    atrChart?.timeScale().fitContent()
    const activeMarker = (props.markers || []).find((marker) => marker.id === props.activeMarkerId)
    setHoverContextForTime(toChartTime(activeMarker?.time || props.bars.at(-1)!.time))
  } else {
    clearHover()
  }
}

function rebuildLookupMaps() {
  barByTime.clear()
  markerByTime.clear()
  emaByTime.clear()
  macdByTime.clear()
  atrByTime.clear()
  props.bars.forEach((bar) => barByTime.set(String(toChartTime(bar.time)), bar))
  ;(props.markers || []).forEach((marker) => markerByTime.set(String(toChartTime(marker.time)), marker))
  calculateEMA(props.bars, 21).forEach((point) => emaByTime.set(String(toChartTime(String(point.time))), point.value))
  const macd = calculateMACD(props.bars)
  macd.dif.forEach((point) => {
    const key = String(toChartTime(String(point.time)))
    macdByTime.set(key, { ...macdByTime.get(key), dif: point.value })
  })
  macd.dea.forEach((point) => {
    const key = String(toChartTime(String(point.time)))
    macdByTime.set(key, { ...macdByTime.get(key), dea: point.value })
  })
  macd.histogram.forEach((point) => {
    const key = String(toChartTime(String(point.time)))
    macdByTime.set(key, { ...macdByTime.get(key), histogram: point.value })
  })
  calculateATR(props.bars, 14).forEach((point) => atrByTime.set(String(toChartTime(String(point.time))), point.value))
}

function toAlignedLineData(chartTimes: Time[], points: Array<{ time: Time | string; value: number }>): Array<LineData<Time> | WhitespaceData<Time>> {
  const values = new Map(points.map((point) => [String(toChartTime(String(point.time))), point.value]))
  return chartTimes.map((time) => {
    const value = values.get(String(time))
    return value === undefined ? { time } : { time, value }
  })
}

function toAlignedHistogramData(
  chartTimes: Time[],
  points: Array<{ time: Time | string; value: number }>,
): Array<HistogramData<Time> | WhitespaceData<Time>> {
  const values = new Map(points.map((point) => [String(toChartTime(String(point.time))), point.value]))
  return chartTimes.map((time) => {
    const value = values.get(String(time))
    if (value === undefined) return { time }
    return {
      time,
      value,
      color: value >= 0 ? 'rgba(239, 68, 68, 0.55)' : 'rgba(34, 197, 94, 0.55)',
    }
  })
}

function syncAllRanges(range: LogicalRange | null, source: IChartApi | null) {
  if (!range || syncingRange) return
  syncingRange = true
  ;[mainChart, macdChart, atrChart].forEach((chart) => {
    if (chart && chart !== source) chart.timeScale().setVisibleLogicalRange(range)
  })
  syncingRange = false
}

function syncCrosshair(param: MouseEventParams<Time>, source: IChartApi | null) {
  if (syncingCrosshair) return
  if (!param.time) {
    clearLinkedCrosshairs(source)
    return
  }
  setHoverContextForTime(param.time)
  syncingCrosshair = true
  const key = String(param.time)
  const bar = barByTime.get(key)
  const macd = macdByTime.get(key)
  const atr = atrByTime.get(key)
  if (source !== mainChart && isChartVisible(mainChart) && bar && candleSeries) mainChart?.setCrosshairPosition(bar.close, param.time, candleSeries)
  if (source !== macdChart && isChartVisible(macdChart) && macdHistogramSeries && macd) {
    macdChart?.setCrosshairPosition(macd.histogram ?? macd.dif ?? 0, param.time, macdHistogramSeries)
  }
  if (source !== atrChart && isChartVisible(atrChart) && atrSeries && atr !== undefined) atrChart?.setCrosshairPosition(atr, param.time, atrSeries)
  syncingCrosshair = false
}

function clearLinkedCrosshairs(source: IChartApi | null) {
  if (syncingCrosshair) return
  syncingCrosshair = true
  if (source !== mainChart && isChartVisible(mainChart)) mainChart?.clearCrosshairPosition()
  if (source !== macdChart && isChartVisible(macdChart)) macdChart?.clearCrosshairPosition()
  if (source !== atrChart && isChartVisible(atrChart)) atrChart?.clearCrosshairPosition()
  syncingCrosshair = false
  clearHover()
}

function syncCrosshairForTime(time: Time) {
  const key = String(time)
  const bar = barByTime.get(key)
  const macd = macdByTime.get(key)
  const atr = atrByTime.get(key)
  syncingCrosshair = true
  if (isChartVisible(mainChart) && bar && candleSeries) mainChart?.setCrosshairPosition(bar.close, time, candleSeries)
  if (isChartVisible(macdChart) && macdHistogramSeries && macd) macdChart?.setCrosshairPosition(macd.histogram ?? macd.dif ?? 0, time, macdHistogramSeries)
  if (isChartVisible(atrChart) && atrSeries && atr !== undefined) atrChart?.setCrosshairPosition(atr, time, atrSeries)
  syncingCrosshair = false
}

function isChartVisible(chart: IChartApi | null) {
  if (!chart) return false
  if (chart === mainChart) return Boolean(mainContainer.value?.clientWidth)
  if (chart === macdChart) return activePanel.value === 'macd' && Boolean(macdContainer.value?.clientWidth)
  if (chart === atrChart) return activePanel.value === 'atr' && Boolean(atrContainer.value?.clientWidth)
  return false
}

function setHoverContextForTime(time: Time) {
  const key = String(time)
  const bar = barByTime.get(key)
  if (!bar) {
    clearHover()
    return
  }
  const context: HoverKlineContext = {
    time: bar.time,
    bar,
    ema21: emaByTime.get(key) ?? null,
    macd: macdByTime.get(key) || null,
    atr: atrByTime.get(key) ?? null,
    marker: markerByTime.get(key) || null,
  }
  hoverContext.value = context
  emit('hover', context)
}

function clearHover() {
  hoverContext.value = null
  emit('hover', null)
}

function toSeriesMarkers(markers: KlineMarker[], activeMarkerId: string | null): SeriesMarker<Time>[] {
  return markers.map((marker) => ({
    id: marker.id,
    time: toChartTime(marker.time),
    position: marker.position,
    shape: marker.shape,
    color: marker.id === activeMarkerId ? '#fbbf24' : marker.color,
    text: marker.label,
    size: marker.id === activeMarkerId ? 2 : 1,
  }))
}

function applyPriceLines() {
  if (!candleSeries) return
  removePriceLines()
  ;(props.overlays || [])
    .filter((overlay) => overlay.type === 'price_line' && typeof overlay.price === 'number')
    .forEach((overlay) => {
      priceLines.push(
        candleSeries!.createPriceLine({
          price: overlay.price!,
          color: overlay.color,
          lineWidth: 1,
          lineStyle: toLineStyle(overlay.lineStyle),
          axisLabelVisible: true,
          title: overlay.label,
        }),
      )
    })
}

function removePriceLines() {
  if (!candleSeries) {
    priceLines = []
    return
  }
  priceLines.forEach((line) => candleSeries?.removePriceLine(line))
  priceLines = []
}

function toLineStyle(style: ChartOverlay['lineStyle']) {
  if (style === 'solid') return LineStyle.Solid
  if (style === 'dashed') return LineStyle.Dashed
  return LineStyle.Dotted
}

function focusTime(value: string) {
  if (!props.bars.length) return
  const index = nearestBarIndex(value)
  const range = {
    from: Math.max(0, index - 20),
    to: Math.min(props.bars.length - 1, index + 20),
  }
  mainChart?.timeScale().setVisibleLogicalRange(range)
  macdChart?.timeScale().setVisibleLogicalRange(range)
  atrChart?.timeScale().setVisibleLogicalRange(range)
  const time = toChartTime(props.bars[index].time)
  setHoverContextForTime(time)
  syncCrosshairForTime(time)
}

function nearestBarIndex(value: string) {
  const target = exchangeLocalTimeMs(value)
  if (!Number.isFinite(target)) return props.bars.length - 1
  let nearest = 0
  let distance = Math.abs(exchangeLocalTimeMs(props.bars[0].time) - target)
  for (let index = 1; index < props.bars.length; index += 1) {
    const current = exchangeLocalTimeMs(props.bars[index].time)
    if (!Number.isFinite(current)) continue
    const currentDistance = Math.abs(current - target)
    if (currentDistance < distance) {
      nearest = index
      distance = currentDistance
    }
  }
  return nearest
}

function exchangeLocalTimeMs(value: string) {
  return new Date(String(value).replace(/(?:Z|[+-]\d{2}:\d{2})$/, '')).getTime()
}

function observeResize() {
  if (!mainContainer.value || !macdContainer.value || !atrContainer.value) return
  resizeObserver = new ResizeObserver(resizeCharts)
  resizeObserver.observe(mainContainer.value)
  resizeObserver.observe(macdContainer.value)
  resizeObserver.observe(atrContainer.value)
}

function resizeCharts() {
  if (mainChart && mainContainer.value) mainChart.applyOptions({ width: mainContainer.value.clientWidth })
  if (macdChart && macdContainer.value) macdChart.applyOptions({ width: macdContainer.value.clientWidth })
  if (atrChart && atrContainer.value) atrChart.applyOptions({ width: atrContainer.value.clientWidth })
}

function toChartTime(value: string): Time {
  return Math.floor(new Date(value).getTime() / 1000) as Time
}

function formatNumber(value: number | null | undefined, digits = 2) {
  if (value === null || value === undefined) return '-'
  return value.toLocaleString('zh-CN', { maximumFractionDigits: digits, minimumFractionDigits: digits })
}

defineExpose({ focusTime })
</script>

<template>
  <div class="kline-shell">
    <div class="hover-strip">
      <template v-if="hoverContext">
        <strong>{{ hoverContext.time.replace('T', ' ').slice(0, 16) }}</strong>
        <span>开 {{ formatNumber(hoverContext.bar.open) }}</span>
        <span>高 {{ formatNumber(hoverContext.bar.high) }}</span>
        <span>低 {{ formatNumber(hoverContext.bar.low) }}</span>
        <span>收 {{ formatNumber(hoverContext.bar.close) }}</span>
        <span>量 {{ hoverContext.bar.volume.toLocaleString('zh-CN') }}</span>
        <span>EMA21 {{ formatNumber(hoverContext.ema21) }}</span>
        <span v-if="hoverContext.marker" class="hover-strip__marker">{{ hoverContext.marker.tooltip || hoverContext.marker.label }}</span>
      </template>
      <template v-else>移动十字线查看同一根 K 的主图与副图指标</template>
    </div>
    <div v-if="loading" class="chart-state">加载中</div>
    <div v-else-if="error" class="chart-state chart-state--error">{{ error }}</div>
    <div v-else-if="!hasData" class="chart-state">暂无数据</div>
    <div ref="mainContainer" class="chart chart--main" />
    <div class="indicator-tabs">
      <button
        v-for="tab in indicatorTabs"
        :key="tab.value"
        class="indicator-tab"
        :class="{ 'indicator-tab--active': activePanel === tab.value }"
        @click="activePanel = tab.value"
      >
        {{ tab.label }}
      </button>
      <span v-if="hoverContext && activePanel === 'macd'" class="indicator-readout">
        DIF {{ formatNumber(hoverContext.macd?.dif, 4) }} / DEA {{ formatNumber(hoverContext.macd?.dea, 4) }} / HIST {{ formatNumber(hoverContext.macd?.histogram, 4) }}
      </span>
      <span v-else-if="hoverContext && activePanel === 'atr'" class="indicator-readout">ATR {{ formatNumber(hoverContext.atr, 4) }}</span>
    </div>
    <div v-show="activePanel === 'macd'" ref="macdContainer" class="chart chart--indicator" />
    <div v-show="activePanel === 'atr'" ref="atrContainer" class="chart chart--indicator" />
  </div>
</template>

<style scoped>
.kline-shell {
  position: relative;
  display: grid;
  grid-template-rows: 34px 430px 34px 150px;
  min-height: 648px;
  background: #101318;
  border: 1px solid #262c36;
  border-radius: 6px;
  overflow: hidden;
}

.hover-strip {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  padding: 0 12px;
  color: #98a3b3;
  background: #171b22;
  border-bottom: 1px solid #262c36;
  font-size: 12px;
  white-space: nowrap;
  overflow: hidden;
}

.hover-strip strong {
  color: #e5e7eb;
  font-weight: 600;
}

.hover-strip__marker {
  color: #fbbf24;
}

.chart {
  width: 100%;
  min-width: 0;
}

.indicator-tabs {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 10px;
  color: #94a3b8;
  background: #171b22;
  border-top: 1px solid #262c36;
  border-bottom: 1px solid #262c36;
  font-size: 12px;
}

.indicator-tab {
  height: 24px;
  padding: 0 12px;
  color: #9aa4b2;
  background: #222832;
  border: 1px solid #303744;
  border-radius: 5px;
  cursor: pointer;
}

.indicator-tab--active {
  color: #ffffff;
  background: #ef6b3a;
  border-color: #ef6b3a;
}

.indicator-readout {
  margin-left: 8px;
  color: #cbd5e1;
}

.chart-state {
  position: absolute;
  z-index: 2;
  inset: 34px 0 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #cbd5e1;
  background: rgba(16, 19, 24, 0.72);
}

.chart-state--error {
  color: #fecaca;
}
</style>
