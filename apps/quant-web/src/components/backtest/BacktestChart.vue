<script setup lang="ts">
import { onMounted, onScopeDispose, ref, watch } from 'vue'
import { mountChartHost, type ChartHost } from '@guiyi/quant-chart'
import { CandlestickSeries, ColorType, createChart, createSeriesMarkers, LineSeries, type SeriesMarker, type UTCTimestamp } from 'lightweight-charts'
import type { Equity, ReplayBar, ReplayMarker } from '@/api/backtestCenter'
import { formatChartAxisTimeInShanghai, formatChartTimeInShanghai } from '@/utils/barTime'

import { replayMarkerLabel } from './backtestDisplay'

const props = defineProps<{
  series: { kind: 'equity'; rows: Equity[] } | { kind: 'trades'; bars: ReplayBar[]; markers: Array<ReplayMarker & { selected: boolean }> }
}>()
const canvas = ref<HTMLElement | null>(null)
const failed = ref(false)
let host: ChartHost | undefined

function stamp(value: string) {
  return Math.floor(Date.parse(value) / 1000) as UTCTimestamp
}

function render() {
  if (!canvas.value) return
  host?.dispose()
  host = undefined
  failed.value = false
  const series = props.series
  try {
    const chartHost = mountChartHost(canvas.value, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: '#ffffff' }, textColor: '#526374', fontSize: 12 },
      grid: { vertLines: { color: '#eff3f6' }, horzLines: { color: '#eff3f6' } },
      rightPriceScale: { borderColor: '#dfe7ee' },
      timeScale: { borderColor: '#dfe7ee', timeVisible: series.kind === 'trades', tickMarkFormatter: formatChartAxisTimeInShanghai },
      localization: { timeFormatter: formatChartTimeInShanghai },
    }, createChart)
    host = chartHost
    if (series.kind === 'equity') {
      const equity = chartHost.chart.addSeries(LineSeries, { color: '#0c7276', lineWidth: 2, priceLineVisible: false })
      chartHost.own(() => chartHost.chart.removeSeries(equity))
      equity.setData(series.rows.map(row => ({ time: stamp(row.at), value: Number(row.equity) })))
    } else {
      const prices = chartHost.chart.addSeries(CandlestickSeries, {
        upColor: '#c34646', wickUpColor: '#c34646', borderUpColor: '#c34646',
        downColor: '#11786d', wickDownColor: '#11786d', borderDownColor: '#11786d',
      })
      chartHost.own(() => chartHost.chart.removeSeries(prices))
      const rows = series.bars.map(bar => ({
        time: stamp(bar.at), open: Number(bar.open), high: Number(bar.high), low: Number(bar.low), close: Number(bar.close),
      }))
      if (!rows.length || rows.some(row => !Object.values(row).every(Number.isFinite))) throw new Error('REPLAY_BARS_INVALID')
      prices.setData(rows)

      const times = new Set(rows.map(row => row.time))
      const markers = series.markers.map(marker => ({ ...marker, time: stamp(marker.at) }))
        .filter(marker => times.has(marker.time)).sort((left, right) => left.time - right.time)
      const rendered = createSeriesMarkers(prices, markers.map((marker): SeriesMarker<UTCTimestamp> => {
        const entry = ['ENTRY', 'BUILD', 'OPEN'].includes(marker.kind)
        const exit = ['EXIT', 'CLEAR', 'CLOSE'].includes(marker.kind)
        const valuation = marker.kind === 'VALUATION'
        const annotation = {
          id: marker.native_trade_id,
          time: marker.time,
          shape: entry ? 'arrowUp' as const : exit ? 'arrowDown' as const : 'circle' as const,
          color: marker.selected ? valuation ? '#345d96' : entry ? '#0c7276' : exit ? '#992e37' : '#74521e' : '#70808c',
          text: replayMarkerLabel(marker),
        }
        const value = marker.price == null ? NaN : Number(marker.price)
        if (marker.selected && (marker.native_trade_id || valuation) && Number.isFinite(value)) {
          return { ...annotation, position: entry ? 'atPriceBottom' : exit ? 'atPriceTop' : 'atPriceMiddle', price: value }
        }
        return { ...annotation, position: entry ? 'belowBar' : 'aboveBar' }
      }))
      chartHost.own(() => rendered.detach())

      const selected = markers.filter(marker => marker.selected)
      const entry = selected.find(marker => marker.kind === 'ENTRY')
      const valuation = selected.filter(marker => marker.kind === 'VALUATION').at(-1)
      const exit = selected.filter(marker => marker.kind === 'EXIT').at(-1)
      const positionEnd = series.bars.filter(bar => bar.in_position).at(-1)?.at
      const terminal = valuation ?? (positionEnd ? { time: stamp(positionEnd) } : exit)
      const terminalPrice = valuation?.price ?? (exit?.time === terminal?.time ? exit?.price : undefined) ?? entry?.price
      if (entry?.price != null && terminal && entry.time < terminal.time) {
        const interval = chartHost.chart.addSeries(LineSeries, {
          color: '#345d96', lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
        })
        chartHost.own(() => chartHost.chart.removeSeries(interval))
        interval.setData([
          { time: entry.time, value: Number(entry.price) },
          { time: terminal.time, value: Number(terminalPrice) },
        ])
      }
    }
    chartHost.chart.timeScale().fitContent()
  } catch {
    host?.dispose()
    host = undefined
    failed.value = true
  }
}

onMounted(render)
watch(() => props.series, render)
onScopeDispose(() => host?.dispose())
</script>

<template>
  <div ref="canvas" class="backtest-chart" :class="{ 'bt-equity-chart': series.kind === 'equity' }"
       role="img" :aria-label="series.kind === 'equity' ? '本 Run 的资金曲线' : '同 Run 的成交回放'" />
  <p v-if="failed" class="bt-alert" role="alert">无法绘制已归档图窗，请查阅明细。</p>
</template>
