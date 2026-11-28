<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { mountChartHost, type ChartHost } from '@guiyi/quant-chart'
import { createChart, CandlestickSeries, LineSeries, ColorType, CrosshairMode, LineStyle, type ISeriesApi, type SeriesType, type UTCTimestamp } from 'lightweight-charts'
import { formatChartAxisTimeInShanghai, formatChartTimeInShanghai } from '@/utils/barTime'

interface ReplayBar {
  at: string
  open?: string | number | null
  high?: string | number | null
  low?: string | number | null
  close: string | number
  upper?: string | number | null
  lower?: string | number | null
  ema21?: string | number | null
}

const props = defineProps<{ rows: ReplayBar[]; stop: string | null; target: string | null }>()
const container = ref<HTMLElement | null>(null)
let host: ChartHost | null = null
let prices: ISeriesApi<'Candlestick'> | null = null
let close: ISeriesApi<'Line'> | null = null
let upper: ISeriesApi<'Line'> | null = null
let lower: ISeriesApi<'Line'> | null = null
let ema: ISeriesApi<'Line'> | null = null
let releaseLevels: Array<() => void> = []

const stamp = (at: string) => Math.floor(Date.parse(at) / 1000) as UTCTimestamp

function render() {
  if (!host || !prices || !close || !upper || !lower || !ema) return
  const candles = prices
  const rows = props.rows
  const hasOHLC = rows.length > 0 && rows.every(row => row.open != null && row.high != null && row.low != null)
  candles.setData(hasOHLC ? rows.map(row => ({
    time: stamp(row.at), open: Number(row.open), high: Number(row.high), low: Number(row.low), close: Number(row.close),
  })) : [])
  close.setData(hasOHLC ? [] : rows.map(row => ({ time: stamp(row.at), value: Number(row.close) })))
  for (const [series, key] of [[upper, 'upper'], [lower, 'lower'], [ema, 'ema21']] as const) {
    series.setData(rows.map(row => row[key] == null ? { time: stamp(row.at) } : { time: stamp(row.at), value: Number(row[key]) }))
  }
  for (const release of releaseLevels) release()
  releaseLevels = []
  for (const [value, title, color] of [[props.stop, '初始保护', '#ff6b2c'], [props.target, '1R目标', '#8b95a5']] as const) {
    if (value == null || !Number.isFinite(Number(value))) continue
    const level = candles.createPriceLine({ price: Number(value), title, color, lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: true })
    releaseLevels.push(host.own(() => candles.removePriceLine(level)))
  }
  if (rows.length) host.chart.timeScale().fitContent()
}

onMounted(() => {
  if (!container.value) return
  const theme = container.value.ownerDocument?.defaultView?.getComputedStyle(container.value)
  const color = (token: string, fallback: string) => theme?.getPropertyValue(token).trim() || fallback
  const border = color('--gy-border', '#39485b')
  const replay = mountChartHost(container.value, {
    autoSize: true, height: 390,
    layout: { background: { type: ColorType.Solid, color: color('--gy-bg-panel', '#151e29') }, textColor: color('--gy-text-secondary', '#acb9ca'), fontFamily: 'Arial, sans-serif', fontSize: 12 },
    grid: { vertLines: { color: border }, horzLines: { color: border } },
    crosshair: { mode: CrosshairMode.Normal },
    rightPriceScale: { borderColor: border, scaleMargins: { top: .08, bottom: .08 } },
    timeScale: { borderColor: border, timeVisible: true, tickMarkFormatter: formatChartAxisTimeInShanghai },
    localization: { timeFormatter: formatChartTimeInShanghai },
  }, createChart)
  host = replay
  const chart = replay.chart
  // Replay values and protection levels are supplied by the SuBing model account snapshot.
  function ownSeries<S extends SeriesType>(series: ISeriesApi<S>): ISeriesApi<S> {
    replay.own(() => chart.removeSeries(series))
    return series
  }

  prices = ownSeries(chart.addSeries(CandlestickSeries, {
    upColor: '#ff403a', downColor: '#22b95d', borderUpColor: '#ff403a', borderDownColor: '#22b95d',
    wickUpColor: '#ff403a', wickDownColor: '#22b95d', priceFormat: { type: 'price', precision: 2, minMove: .01 },
  }))
  close = ownSeries(chart.addSeries(LineSeries, { color: '#ff6b2c', lineWidth: 2, priceLineVisible: false, lastValueVisible: false }))
  const channel = { color: '#5d86c4', lineStyle: LineStyle.Dashed, lineWidth: 1 as const, priceLineVisible: false, lastValueVisible: false }
  upper = ownSeries(chart.addSeries(LineSeries, channel))
  lower = ownSeries(chart.addSeries(LineSeries, channel))
  ema = ownSeries(chart.addSeries(LineSeries, { color: '#bd8ad0', lineWidth: 1, priceLineVisible: false, lastValueVisible: false }))
  render()
})
watch(() => [props.rows, props.stop, props.target], render)
onBeforeUnmount(() => {
  host?.dispose()
  host = null
  releaseLevels = []
})
</script>
<template><div ref="container" class="replay-chart" role="img" aria-label="30分钟K线、近期结构和保护位置"/><p v-if="rows.length&&!rows[0].open" class="chart-note">当前历史包仅提供收盘线；未补造开高低价。</p></template>
<style scoped>.replay-chart{height:390px;min-width:0}.chart-note{font-size:12px;color:#667085;padding:0 16px}</style>
