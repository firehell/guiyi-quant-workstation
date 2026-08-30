<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  AreaSeries,
  ColorType,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type TickMarkType,
  type Time,
  type UTCTimestamp,
} from 'lightweight-charts'
import { resolveChartTheme } from '@/styles/chartTheme'
import { formatChartAxisTimeInShanghai, formatChartTimeInShanghai } from '@/utils/barTime'
import type { SubingCumulativePoint } from '@/utils/subingStrategyPerformance'

const props = defineProps<{
  points: SubingCumulativePoint[]
}>()

const container = ref<HTMLElement>()
let chart: IChartApi | null = null
let series: ISeriesApi<'Area'> | null = null
let observer: ResizeObserver | null = null

function hexToRgba(hex: string, alpha: number): string {
  const match = /^#([0-9a-f]{6})$/i.exec(hex.trim())
  if (!match) return hex
  const n = Number.parseInt(match[1], 16)
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`
}

function areaColors(lastValue: number | null) {
  const theme = resolveChartTheme()
  const positive = lastValue === null || lastValue >= 0
  const line = positive ? theme.up : theme.down
  return {
    lineColor: line,
    topColor: hexToRgba(line, 0.28),
    bottomColor: hexToRgba(line, 0.03),
  }
}

function chartData() {
  return props.points.map((point) => ({
    time: point.time as UTCTimestamp,
    value: point.value,
  }))
}

function applySeries() {
  if (!series) return
  series.applyOptions(areaColors(props.points.at(-1)?.value ?? null))
  series.setData(chartData())
  chart?.timeScale().fitContent()
}

function resize() {
  if (!container.value || !chart) return
  chart.resize(container.value.clientWidth, container.value.clientHeight)
}

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
    localization: {
      timeFormatter: formatChartTimeInShanghai,
      priceFormatter: (price: number) => `${price >= 0 ? '+' : ''}${price.toFixed(2)}%`,
    },
    timeScale: {
      borderColor: theme.axis,
      timeVisible: true,
      tickMarkFormatter: (time: Time, tickMarkType: TickMarkType) => (
        formatChartAxisTimeInShanghai(time, tickMarkType)
      ),
    },
  })
  series = chart.addSeries(AreaSeries, {
    lineWidth: 2,
    priceLineVisible: false,
    lastValueVisible: true,
    priceFormat: { type: 'custom', formatter: (price: number) => `${price >= 0 ? '+' : ''}${price.toFixed(2)}%`, minMove: 0.01 },
    ...areaColors(props.points.at(-1)?.value ?? null),
  })
  observer = new ResizeObserver(() => resize())
  observer.observe(container.value)
  applySeries()
})

onUnmounted(() => {
  observer?.disconnect()
  chart?.remove()
  chart = null
  series = null
})

watch(() => props.points, () => applySeries(), { deep: true })
</script>

<template>
  <div class="trend-chart" data-testid="subing-performance-trend-chart">
    <div ref="container" class="trend-chart__canvas" />
    <p v-if="points.length === 0" class="trend-chart__empty">当前区间暂无已完成 Episode</p>
  </div>
</template>

<style scoped>
.trend-chart { position: relative; height: 240px; }
.trend-chart__canvas { height: 240px; width: 100%; }
.trend-chart__empty {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  margin: 0;
  color: var(--gy-text-muted);
  font-size: var(--gy-font-size-xs);
  pointer-events: none;
}
</style>
