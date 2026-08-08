<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  CandlestickSeries,
  ColorType,
  createChart,
  HistogramSeries,
  type IChartApi,
  type ISeriesApi,
  type Time,
  type UTCTimestamp,
} from 'lightweight-charts'
import type { BarData } from '@/types/market'
import { resolveChartTheme } from '@/styles/chartTheme'

const props = withDefaults(defineProps<{
  bars: BarData[]
  loading?: boolean
  error?: string | null
  period?: string
}>(), {
  loading: false,
  error: null,
  period: '15m',
})

const container = ref<HTMLElement>()
let chart: IChartApi | null = null
let candles: ISeriesApi<'Candlestick'> | null = null
let volume: ISeriesApi<'Histogram'> | null = null
let observer: ResizeObserver | null = null

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
    timeScale: { borderColor: theme.axis, timeVisible: !isDaily() },
  })
  candles = chart.addSeries(CandlestickSeries, {
    upColor: theme.up,
    downColor: theme.down,
    borderUpColor: theme.up,
    borderDownColor: theme.down,
    wickUpColor: theme.up,
    wickDownColor: theme.down,
  })
  volume = chart.addSeries(HistogramSeries, {
    priceFormat: { type: 'volume' },
    priceScaleId: 'volume',
  })
  chart.priceScale('volume').applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } })
  observer = new ResizeObserver(() => resize())
  observer.observe(container.value)
  render()
})

onUnmounted(() => {
  observer?.disconnect()
  chart?.remove()
})

watch(() => [props.bars, props.period], render, { deep: true })

function render() {
  if (!candles || !volume || !chart) return
  const theme = resolveChartTheme()
  const values = props.bars.map((bar) => ({
    time: chartTime(bar),
    open: bar.open,
    high: bar.high,
    low: bar.low,
    close: bar.close,
  }))
  candles.setData(values)
  volume.setData(props.bars.map((bar) => ({
    time: chartTime(bar),
    value: bar.volume,
    color: bar.close >= bar.open ? theme.volumeUp : theme.volumeDown,
  })))
  chart.applyOptions({ timeScale: { timeVisible: !isDaily() } })
  chart.timeScale().fitContent()
}

function chartTime(bar: BarData): Time {
  if (isDaily()) return (bar.trading_day || bar.time.slice(0, 10)) as Time
  return Math.floor(new Date(bar.time).getTime() / 1000) as UTCTimestamp
}

function isDaily() {
  return props.period === '1d' || props.period === '1w'
}

function resize() {
  if (!container.value || !chart) return
  chart.resize(container.value.clientWidth, container.value.clientHeight)
}
</script>

<template>
  <div class="kline-shell">
    <div ref="container" class="chart" />
    <div v-if="loading" class="overlay">读取 Canonical…</div>
    <div v-else-if="error" class="overlay error">{{ error }}</div>
    <div v-else-if="!bars.length" class="overlay">当前窗口无可读 bars</div>
  </div>
</template>

<style scoped>
.kline-shell { position: relative; min-height: 620px; border: 1px solid var(--gy-border); background: var(--gy-bg-panel); }
.chart { width: 100%; height: 620px; }
.overlay { position: absolute; inset: 0; display: grid; place-items: center; color: var(--gy-text-muted); background: rgba(11, 17, 27, .48); pointer-events: none; }
.overlay.error { color: #fb7185; }
</style>
