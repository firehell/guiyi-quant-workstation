<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  HistogramSeries,
  LineSeries,
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type LineData,
  type SeriesMarker,
  type Time,
} from 'lightweight-charts'
import type { BarData, KlineMarker } from '@/types/market'
import { calculateATR, calculateEMA, calculateMACD } from '@/utils/indicators'

const props = defineProps<{
  bars: BarData[]
  markers?: KlineMarker[]
  activeMarkerId?: string | null
  loading?: boolean
  error?: string | null
}>()

const mainContainer = ref<HTMLElement>()
const macdContainer = ref<HTMLElement>()
const atrContainer = ref<HTMLElement>()

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

const hasData = computed(() => props.bars.length > 0)

onMounted(async () => {
  await nextTick()
  createCharts()
  renderSeries()
  observeResize()
})

onUnmounted(() => {
  resizeObserver?.disconnect()
  mainChart?.remove()
  macdChart?.remove()
  atrChart?.remove()
})

watch(
  () => [props.bars, props.markers, props.activeMarkerId],
  () => renderSeries(),
  { deep: true },
)

function createCharts() {
  if (!mainContainer.value || !macdContainer.value || !atrContainer.value) return

  mainChart = createChart(mainContainer.value, {
    width: mainContainer.value.clientWidth,
    height: 430,
    layout: {
      background: { type: ColorType.Solid, color: '#0f172a' },
      textColor: '#cbd5e1',
    },
    grid: {
      vertLines: { color: '#1e293b' },
      horzLines: { color: '#1e293b' },
    },
    rightPriceScale: { borderColor: '#334155', scaleMargins: { top: 0.08, bottom: 0.22 } },
    timeScale: { borderColor: '#334155', timeVisible: true, secondsVisible: false },
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

  atrChart = createSubChart(atrContainer.value, 120)
  atrSeries = atrChart.addSeries(LineSeries, {
    color: '#a78bfa',
    lineWidth: 1,
    priceLineVisible: false,
    lastValueVisible: false,
  })
}

function createSubChart(container: HTMLElement, height: number) {
  return createChart(container, {
    width: container.clientWidth,
    height,
    layout: {
      background: { type: ColorType.Solid, color: '#0f172a' },
      textColor: '#94a3b8',
    },
    grid: {
      vertLines: { color: '#1e293b' },
      horzLines: { color: '#1e293b' },
    },
    rightPriceScale: { borderColor: '#334155' },
    timeScale: { borderColor: '#334155', timeVisible: true, secondsVisible: false },
  })
}

function renderSeries() {
  if (!candleSeries || !volumeSeries || !emaSeries || !macdDifSeries || !macdDeaSeries || !macdHistogramSeries || !atrSeries) return

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
  const emaData: LineData<Time>[] = calculateEMA(props.bars, 21).map((point) => ({
    time: toChartTime(String(point.time)),
    value: point.value,
  }))
  const macd = calculateMACD(props.bars)
  const macdDifData: LineData<Time>[] = macd.dif.map((point) => ({ time: toChartTime(String(point.time)), value: point.value }))
  const macdDeaData: LineData<Time>[] = macd.dea.map((point) => ({ time: toChartTime(String(point.time)), value: point.value }))
  const macdHistogramData: HistogramData<Time>[] = macd.histogram.map((point) => ({
    time: toChartTime(String(point.time)),
    value: point.value,
    color: point.value >= 0 ? 'rgba(239, 68, 68, 0.55)' : 'rgba(34, 197, 94, 0.55)',
  }))
  const atrData: LineData<Time>[] = calculateATR(props.bars, 14).map((point) => ({
    time: toChartTime(String(point.time)),
    value: point.value,
  }))

  candleSeries.setData(candleData)
  markerLayer?.setMarkers(toSeriesMarkers(props.markers || [], props.activeMarkerId || null))
  volumeSeries.setData(volumeData)
  emaSeries.setData(emaData)
  macdDifSeries.setData(macdDifData)
  macdDeaSeries.setData(macdDeaData)
  macdHistogramSeries.setData(macdHistogramData)
  atrSeries.setData(atrData)
  mainChart?.timeScale().fitContent()
  macdChart?.timeScale().fitContent()
  atrChart?.timeScale().fitContent()
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

function focusTime(value: string) {
  if (!mainChart) return
  const target = toChartTime(value) as number
  const day = 24 * 60 * 60
  mainChart.timeScale().setVisibleRange({
    from: (target - day) as Time,
    to: (target + day) as Time,
  })
}

function observeResize() {
  if (!mainContainer.value || !macdContainer.value || !atrContainer.value) return
  resizeObserver = new ResizeObserver(() => {
    if (mainChart && mainContainer.value) mainChart.applyOptions({ width: mainContainer.value.clientWidth })
    if (macdChart && macdContainer.value) macdChart.applyOptions({ width: macdContainer.value.clientWidth })
    if (atrChart && atrContainer.value) atrChart.applyOptions({ width: atrContainer.value.clientWidth })
  })
  resizeObserver.observe(mainContainer.value)
  resizeObserver.observe(macdContainer.value)
  resizeObserver.observe(atrContainer.value)
}

function toChartTime(value: string): Time {
  return Math.floor(new Date(value).getTime() / 1000) as Time
}

defineExpose({ focusTime })
</script>

<template>
  <div class="kline-shell">
    <div v-if="loading" class="chart-state">加载中</div>
    <div v-else-if="error" class="chart-state chart-state--error">{{ error }}</div>
    <div v-else-if="!hasData" class="chart-state">暂无数据</div>
    <div ref="mainContainer" class="chart chart--main" />
    <div class="indicator-label">MACD</div>
    <div ref="macdContainer" class="chart chart--macd" />
    <div class="indicator-label">ATR</div>
    <div ref="atrContainer" class="chart chart--atr" />
  </div>
</template>

<style scoped>
.kline-shell {
  position: relative;
  display: grid;
  grid-template-rows: 430px 24px 150px 24px 120px;
  min-height: 748px;
  background: #0f172a;
  border: 1px solid #1e293b;
  border-radius: 6px;
  overflow: hidden;
}

.chart {
  width: 100%;
  min-width: 0;
}

.indicator-label {
  display: flex;
  align-items: center;
  padding: 0 12px;
  color: #94a3b8;
  background: #111827;
  border-top: 1px solid #1e293b;
  font-size: 12px;
}

.chart-state {
  position: absolute;
  z-index: 2;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #cbd5e1;
  background: rgba(15, 23, 42, 0.72);
}

.chart-state--error {
  color: #fecaca;
}
</style>
