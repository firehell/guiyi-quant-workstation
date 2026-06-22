<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import {
  CandlestickSeries,
  createChart,
  type CandlestickData,
  type IChartApi,
  type ISeriesApi,
  type Time,
} from 'lightweight-charts'

const chartContainer = ref<HTMLElement>()
let chart: IChartApi | null = null
let candleSeries: ISeriesApi<'Candlestick'> | null = null

const sampleData: CandlestickData<Time>[] = [
  { time: '2025-01-01' as Time, open: 3800, high: 3850, low: 3780, close: 3830 },
  { time: '2025-01-02' as Time, open: 3830, high: 3880, low: 3820, close: 3870 },
  { time: '2025-01-03' as Time, open: 3870, high: 3900, low: 3850, close: 3890 },
  { time: '2025-01-06' as Time, open: 3890, high: 3920, low: 3860, close: 3880 },
  { time: '2025-01-07' as Time, open: 3880, high: 3910, low: 3840, close: 3850 },
]

onMounted(() => {
  if (!chartContainer.value) return

  chart = createChart(chartContainer.value, {
    width: chartContainer.value.clientWidth,
    height: 400,
    layout: {
      background: { color: '#ffffff' },
      textColor: '#333',
    },
    grid: {
      vertLines: { color: '#f0f0f0' },
      horzLines: { color: '#f0f0f0' },
    },
    timeScale: { borderColor: '#ddd' },
    rightPriceScale: { borderColor: '#ddd' },
  })

  candleSeries = chart.addSeries(CandlestickSeries, {
    upColor: '#ef4444',
    downColor: '#22c55e',
    borderUpColor: '#ef4444',
    borderDownColor: '#22c55e',
    wickUpColor: '#ef4444',
    wickDownColor: '#22c55e',
  })
  candleSeries.setData(sampleData)

  const resizeObserver = new ResizeObserver(() => {
    if (chart && chartContainer.value) {
      chart.applyOptions({ width: chartContainer.value.clientWidth })
    }
  })
  resizeObserver.observe(chartContainer.value)
})

onUnmounted(() => {
  chart?.remove()
  chart = null
})
</script>

<template>
  <div ref="chartContainer" class="kline-chart" />
</template>

<style scoped>
.kline-chart {
  width: 100%;
  height: 400px;
}
</style>
