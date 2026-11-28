<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { CandlestickSeries, ColorType, createChart, HistogramSeries, type IChartApi } from 'lightweight-charts'
import { getMarketBarsPage } from '@/api/market'
import { historicalDisplayBar } from '@/utils/marketBarDisplay'
import { createDetailChartSession, detailChartTime } from '@/utils/detailChartSession'
import { captureObservationPane } from '@/utils/observationCapture'
import type { BarData, MarketFrequency } from '@/types/market'
import type { MarketDetailIdentity } from '@/types/marketDetail'

const props = defineProps<{ identity: MarketDetailIdentity; period: MarketFrequency; active: boolean }>()
defineEmits<{ expand: []; activate: [] }>()
const el = ref<HTMLDivElement>(),
  status = ref('读取历史行情…'),
  bars = shallowRef<BarData[]>([])
const owner = createDetailChartSession({ createChart })
let chart: IChartApi | undefined,
  serial = 0,
  pending: AbortController | null = null
async function load() {
  if (!el.value) return
  const generation = ++serial
  pending?.abort()
  pending = new AbortController()
  status.value = '读取历史行情…'
  bars.value = []
  chart?.remove()
  owner.setIdentity(
    JSON.stringify([props.identity.symbol, props.identity.seriesKind, props.identity.contract, props.period]),
  )
  owner.resetWindow()
  chart = owner.acquire(el.value, {
    autoSize: true,
    layout: { background: { type: ColorType.Solid, color: '#101720' }, textColor: '#aebed0' },
    grid: { vertLines: { color: '#1f2b39' }, horzLines: { color: '#25313e' } },
    timeScale: { timeVisible: props.period.endsWith('m'), secondsVisible: false },
  })
  const candles = chart.addSeries(CandlestickSeries, {
    upColor: '#e57980',
    downColor: '#54b5a1',
    wickUpColor: '#e57980',
    wickDownColor: '#54b5a1',
    borderVisible: false,
  })
  const volume = chart.addSeries(HistogramSeries, {
    priceScaleId: 'volume',
    priceFormat: { type: 'volume' },
    priceLineVisible: false,
    lastValueVisible: false,
  })
  volume.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } })
  candles.priceScale().applyOptions({ scaleMargins: { top: 0.07, bottom: 0.25 } })
  try {
    const identity = props.identity
    const page = await getMarketBarsPage(
      {
        symbol: identity.symbol,
        series_kind: identity.seriesKind,
        contract: identity.contract,
        frequency: props.period,
        limit: 160,
      },
      pending.signal,
    )
    if (generation !== serial) return
    const data = page.bars.map((b) => historicalDisplayBar(page, b))
    if (!data.length) {
      status.value = '此合约与周期暂无历史 Bar'
      return
    }
    const rows = data.map((b) => ({ ...b, time: detailChartTime(b, props.period) }))
    candles.setData(rows)
    volume.setData(
      rows.map((b) => ({ time: b.time, value: b.volume, color: b.close >= b.open ? '#97565f' : '#448277' })),
    )
    chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, rows.length - 65), to: rows.length + 1 })
    bars.value = data
    status.value = ''
  } catch {
    if (generation === serial) status.value = '历史行情或合约映射不可用'
  }
}
onMounted(load)
watch(() => [props.identity.symbol, props.identity.seriesKind, props.identity.contract, props.period], load)
onBeforeUnmount(() => {
  ++serial
  pending?.abort()
  owner.dispose()
})
defineExpose({
  tradingDay: () => bars.value.at(-1)?.trading_day,
  capture: () =>
    captureObservationPane(
      owner,
      { ...props.identity, view: 'free', strategy: undefined, newowMode: undefined, frequency: props.period },
      bars.value,
      [],
      { display: ['price', 'volume'] },
    ),
})
</script>
<template>
  <section class="period" @pointerdown="$emit('activate')">
    <header>
      <button type="button" :aria-pressed="active" @click="$emit('activate')">
        {{ period }} · {{ identity.symbol.toUpperCase() }}{{ active ? ' · 当前' : '' }}</button
      ><button type="button" @click="$emit('expand')">展开</button>
    </header>
    <p v-if="status" role="status">{{ status }}</p>
    <div ref="el" class="canvas" @dblclick="$emit('expand')"></div>
  </section>
</template>
<style scoped>
.period {
  position: relative;
  min-width: 0;
  background: #101720;
  border: 1px solid #2a3542;
}
.period header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 8px;
  font-size: 12px;
}
.period p {
  position: absolute;
  top: 25%;
  left: 10%;
  z-index: 1;
  color: #b7c2ce;
}
.canvas {
  height: clamp(175px, 22vh, 310px);
}
button {
  color: inherit;
  background: transparent;
  border: 1px solid #384b60;
  border-radius: 3px;
}
</style>
