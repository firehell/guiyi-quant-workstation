<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  HistogramSeries,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type LineData,
  type MouseEventParams,
  type SeriesMarker,
  type TickMarkType,
  type Time,
  type WhitespaceData,
} from 'lightweight-charts'

import type { BarData } from '@/types/market'
import type { NewowTrendDetailResponse } from '@/types/newow'
import { resolveChartTheme } from '@/styles/chartTheme'
import { formatChartAxisTimeInShanghai, formatChartTimeInShanghai } from '@/utils/barTime'
import { initialChartLogicalRange } from '@/utils/chartViewport'
import {
  buildNewowTrendChartProjection,
  createNewowTrendChartDisposer,
  NewowTrendChartPrimitive,
  resolveNewowTrendCrosshairFacts,
  type NewowTrendChartMarker,
  type NewowTrendChartProjection,
  type NewowTrendHoverFacts,
} from '@/components/market/detail/newowTrendChartPrimitives'

const props = withDefaults(defineProps<{
  data: NewowTrendDetailResponse | null
  genericBars: readonly BarData[]
  loading?: boolean
}>(), { loading: false })

const container = ref<HTMLElement | null>(null)
const hoverFacts = ref<NewowTrendHoverFacts | null>(null)
const projection = computed(() => buildNewowTrendChartProjection({
  data: props.data,
  genericBars: props.genericBars,
}))
const primitive = new NewowTrendChartPrimitive()

let chart: IChartApi | null = null
let candles: ISeriesApi<'Candlestick'> | null = null
let volume: ISeriesApi<'Histogram'> | null = null
let bLine: ISeriesApi<'Line'> | null = null
let cLine: ISeriesApi<'Line'> | null = null
let markers: ISeriesMarkersPluginApi<Time> | null = null
let observer: ResizeObserver | null = null
let disposeResources: (() => void) | null = null

onMounted(async () => {
  await nextTick()
  if (container.value === null) return
  const theme = resolveChartTheme()
  chart = createChart(container.value, {
    width: container.value.clientWidth,
    height: container.value.clientHeight,
    layout: { background: { type: ColorType.Solid, color: theme.background }, textColor: theme.text },
    grid: { vertLines: { color: theme.grid }, horzLines: { color: theme.grid } },
    rightPriceScale: { borderColor: theme.axis },
    localization: { timeFormatter: formatChartTimeInShanghai },
    crosshair: {
      vertLine: { labelBackgroundColor: '#1F2937', labelVisible: true },
      horzLine: { labelBackgroundColor: '#1F2937', labelVisible: true },
    },
    timeScale: {
      borderColor: theme.axis,
      timeVisible: false,
      tickMarkFormatter: (time: Time, tickMarkType: TickMarkType) => (
        formatChartAxisTimeInShanghai(time, tickMarkType)
      ),
    },
  })
  chart.panes()[0]!.setStretchFactor(6)
  chart.addPane().setStretchFactor(2)
  candles = chart.addSeries(CandlestickSeries, {
    upColor: theme.up,
    downColor: theme.down,
    borderUpColor: theme.up,
    borderDownColor: theme.down,
    wickUpColor: theme.up,
    wickDownColor: theme.down,
  }, 0)
  candles.attachPrimitive(primitive)
  bLine = chart.addSeries(LineSeries, {
    color: '#F59E0B', lineWidth: 2, lastValueVisible: false, priceLineVisible: false,
  }, 0)
  cLine = chart.addSeries(LineSeries, {
    color: '#2563EB', lineWidth: 2, lastValueVisible: false, priceLineVisible: false,
  }, 0)
  volume = chart.addSeries(HistogramSeries, { priceFormat: { type: 'volume' } }, 1)
  chart.priceScale('right', 1).applyOptions({ scaleMargins: { top: 0.12, bottom: 0.05 } })
  markers = createSeriesMarkers(candles)
  chart.subscribeCrosshairMove(onCrosshairMove)
  observer = new ResizeObserver(resize)
  observer.observe(container.value)
  disposeResources = createNewowTrendChartDisposer({
    unsubscribeCrosshair: () => chart?.unsubscribeCrosshairMove(onCrosshairMove),
    disconnectResizeObserver: () => observer?.disconnect(),
    removeChart: () => chart?.remove(),
  })
  renderProjection(projection.value, true)
})

onUnmounted(() => {
  disposeResources?.()
  disposeResources = null
  observer = null
  markers = null
  candles = null
  volume = null
  bLine = null
  cLine = null
  chart = null
})

watch(projection, (value) => renderProjection(value, false))

function renderProjection(value: NewowTrendChartProjection, resetViewport: boolean): void {
  if (chart === null || candles === null || volume === null || bLine === null || cLine === null) return
  const theme = resolveChartTheme()
  candles.setData(value.bars.map((bar) => ({
    time: dayTime(bar.tradingDay),
    open: bar.open,
    high: bar.high,
    low: bar.low,
    close: bar.close,
  })))
  volume.setData(value.bars.map((bar) => ({
    time: dayTime(bar.tradingDay),
    value: bar.volume,
    color: bar.close >= bar.open ? theme.volumeUp : theme.volumeDown,
  })))
  bLine.setData(bandLineValues(value, 'b'))
  cLine.setData(bandLineValues(value, 'c'))
  primitive.setData(value, dayTime)
  primitive.setStyle({
    yellowFill: 'rgba(245, 158, 11, 0.16)',
    blueFill: 'rgba(37, 99, 235, 0.14)',
    bullishCup: '#D97706',
    bearishCup: '#2563EB',
    pivot: '#7C3AED',
    rollover: theme.textMuted,
    rolloverText: theme.textMuted,
  })
  markers?.setMarkers(value.markers.map((marker) => chartMarker(marker, theme)))
  hoverFacts.value = null
  if (!resetViewport) return
  const range = initialChartLogicalRange(value.bars.length)
  if (range === null) chart.timeScale().fitContent()
  else chart.timeScale().setVisibleLogicalRange(range)
}

function bandLineValues(
  value: NewowTrendChartProjection,
  key: 'b' | 'c',
): Array<LineData<Time> | WhitespaceData<Time>> {
  const byDay = new Map(value.band[key].map((point) => [point.tradingDay, point]))
  return value.bars.map((bar) => {
    const point = byDay.get(bar.tradingDay)
    return point === undefined
      ? { time: dayTime(bar.tradingDay) }
      : {
        time: dayTime(bar.tradingDay),
        value: point.value,
        color: point.state === 'YELLOW' ? '#F59E0B'
          : point.state === 'BLUE' ? '#2563EB' : '#98A2B3',
      }
  })
}

function chartMarker(
  marker: NewowTrendChartMarker,
  theme: ReturnType<typeof resolveChartTheme>,
): SeriesMarker<Time> {
  const colors = {
    yellow: '#D97706',
    blue: '#2563EB',
    d1: theme.down,
    d2: theme.up,
    d3: '#2563EB',
    cup: '#7C3AED',
  } as const
  return {
    id: marker.id,
    time: dayTime(marker.tradingDay),
    position: marker.position,
    shape: marker.shape,
    color: colors[marker.colorRole],
    text: marker.label,
    size: marker.family === 'trend' ? 1.5 : 1,
  }
}

function onCrosshairMove(param: MouseEventParams<Time>): void {
  hoverFacts.value = param.time === undefined
    ? null
    : resolveNewowTrendCrosshairFacts(projection.value, param.time)
}

function resize(): void {
  if (container.value === null || chart === null) return
  chart.resize(container.value.clientWidth, container.value.clientHeight)
}

function dayTime(day: string): Time {
  const [year, month, date] = day.split('-').map(Number)
  return { year: year!, month: month!, day: date! }
}

function formatValue(value: number | null): string {
  return value === null ? '不可用' : String(value)
}
</script>

<template>
  <section
    class="newow-trend-chart-stage"
    data-testid="newow-trend-chart-stage"
    :data-chart-source="projection.source"
    :data-pane-count="projection.paneCount"
    data-time-scale-sync="shared"
    data-crosshair-sync="shared"
    :data-newow-band-area-count="projection.band.areas.length"
    :data-newow-marker-count="projection.markers.length"
    :data-newow-marker-ids="projection.markers.map((marker) => marker.id).join(',')"
    :data-newow-rollover-count="projection.rolloverSeams.length"
  >
    <div ref="container" class="newow-trend-chart-stage__chart" />
    <div v-if="hoverFacts" class="newow-trend-chart-stage__hover" aria-live="polite">
      <span>{{ hoverFacts.tradingDay }}</span>
      <span>O {{ hoverFacts.bar.open }}</span>
      <span>H {{ hoverFacts.bar.high }}</span>
      <span>L {{ hoverFacts.bar.low }}</span>
      <span>C {{ hoverFacts.bar.close }}</span>
      <span>Vol {{ hoverFacts.bar.volume }}</span>
      <span>OI {{ formatValue(hoverFacts.bar.openInterest) }}</span>
      <span v-if="hoverFacts.physicalContract">合约 {{ hoverFacts.physicalContract }}</span>
      <template v-if="hoverFacts.trend">
        <span>趋势 {{ hoverFacts.trend.state }}</span>
        <span>B {{ formatValue(hoverFacts.trend.b) }}</span>
        <span>C {{ formatValue(hoverFacts.trend.c) }}</span>
      </template>
      <span v-for="(label, index) in hoverFacts.markerLabels" :key="`${index}:${label}`">{{ label }}</span>
      <span v-for="cup in hoverFacts.cupStates" :key="cup.candidateId">
        杯柄 {{ cup.direction }} / {{ cup.state }}
      </span>
      <span v-if="hoverFacts.rolloverLabel">{{ hoverFacts.rolloverLabel }}</span>
    </div>
    <div class="newow-trend-chart-stage__legend" aria-label="Newow 趋势图例">
      <span><i class="newow-trend-chart-stage__swatch newow-trend-chart-stage__swatch--yellow" />黄带</span>
      <span><i class="newow-trend-chart-stage__swatch newow-trend-chart-stage__swatch--blue" />蓝带</span>
      <span>下方子图：成交量</span>
    </div>
    <div v-if="loading && data === null" class="newow-trend-chart-stage__status">正在读取 Newow 趋势数据…</div>
    <div
      v-else-if="projection.unavailableDisclosure"
      class="newow-trend-chart-stage__status newow-trend-chart-stage__status--unavailable"
      data-testid="newow-trend-chart-unavailable"
    >
      {{ projection.unavailableDisclosure }}
    </div>
    <div v-else-if="projection.bars.length === 0" class="newow-trend-chart-stage__status">当前窗口无 Newow completed D1 bars</div>
  </section>
</template>

<style scoped>
.newow-trend-chart-stage {
  position: relative;
  min-width: 0;
  min-height: 680px;
  height: clamp(680px, 74vh, 1040px);
  border: 1px solid var(--gy-border);
  background: var(--gy-bg-panel);
}
.newow-trend-chart-stage__chart { width: 100%; height: 100%; }
.newow-trend-chart-stage__hover {
  position: absolute;
  z-index: 4;
  top: 10px;
  left: 12px;
  display: flex;
  flex-wrap: wrap;
  gap: 4px 12px;
  max-width: calc(100% - 24px);
  color: var(--gy-text-muted);
  font-size: 12px;
  line-height: 1.4;
  pointer-events: none;
}
.newow-trend-chart-stage__legend {
  position: absolute;
  z-index: 3;
  top: 42px;
  right: 72px;
  display: flex;
  gap: 12px;
  padding: 5px 9px;
  border: 1px solid var(--gy-border);
  border-radius: var(--gy-radius-sm);
  color: var(--gy-text-secondary);
  background: color-mix(in srgb, var(--gy-bg-panel) 90%, transparent);
  font-size: var(--gy-font-size-xs);
  pointer-events: none;
}
.newow-trend-chart-stage__legend span { display: inline-flex; gap: 5px; align-items: center; white-space: nowrap; }
.newow-trend-chart-stage__swatch { width: 18px; height: 7px; border-radius: 2px; }
.newow-trend-chart-stage__swatch--yellow { background: rgba(245, 158, 11, .4); }
.newow-trend-chart-stage__swatch--blue { background: rgba(37, 99, 235, .36); }
.newow-trend-chart-stage__status {
  position: absolute;
  z-index: 5;
  inset: auto 12px 12px;
  padding: 8px 10px;
  border: 1px solid var(--gy-border);
  border-radius: var(--gy-radius-sm);
  color: var(--gy-text-muted);
  background: color-mix(in srgb, var(--gy-bg-panel) 94%, transparent);
  font-size: var(--gy-font-size-sm);
  pointer-events: none;
}
.newow-trend-chart-stage__status--unavailable { color: var(--gy-status-warning); }

@media (max-width: 640px) {
  .newow-trend-chart-stage { min-height: 520px; height: 68vh; }
  .newow-trend-chart-stage__legend { top: auto; right: 8px; bottom: 46px; gap: 8px; }
}
</style>
