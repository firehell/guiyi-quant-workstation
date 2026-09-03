<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'

import KlineChart from '@/components/kline/KlineChart.vue'
import type { BarData, KlineMarker, MainIndicatorId, SeriesKind } from '@/types/market'
import type { MarketSeriesMutation } from '@/composables/useMarketSeries'

const props = withDefaults(defineProps<{
  bars: BarData[]
  mutation: MarketSeriesMutation
  loading: boolean
  error: string | null
  period: string
  seriesKind: SeriesKind
  visibleMainIndicators: MainIndicatorId[]
  rangeDetectorSourceIdentity: string
  rangeDetectorAnchorTime: string | null
  markers?: KlineMarker[]
}>(), { markers: () => [] })

const emit = defineEmits<{ loadEarlier: [] }>()
const chart = ref<InstanceType<typeof KlineChart> | null>(null)
const root = ref<HTMLElement | null>(null)
const followLatest = ref(true)
const fullscreen = ref(false)

watch(() => props.mutation, async (mutation) => {
  await nextTick()
  if (!chart.value) return
  if (mutation.kind === 'replace') chart.value.replaceBars(props.bars, !followLatest.value)
  else if (mutation.kind === 'prepend') chart.value.prependBars(mutation.bars)
  else {
    for (const bar of mutation.bars) chart.value.updateBar(bar)
    if (followLatest.value) chart.value.scrollToLatest()
  }
}, { deep: true })

async function toggleFullscreen() {
  if (!root.value) return
  if (document.fullscreenElement) await document.exitFullscreen()
  else await root.value.requestFullscreen()
}

function syncFullscreen() { fullscreen.value = Boolean(document.fullscreenElement) }
document.addEventListener('fullscreenchange', syncFullscreen)
onBeforeUnmount(() => document.removeEventListener('fullscreenchange', syncFullscreen))
</script>

<template>
  <section ref="root" class="market-kline-stage" :class="{ 'market-kline-stage--fullscreen': fullscreen }">
    <div class="market-kline-stage__controls">
      <button v-if="!followLatest" type="button" @click="chart?.scrollToLatest()">↺ 回到最新</button>
      <button type="button" :aria-label="fullscreen ? '退出全屏' : '全屏图表'" @click="toggleFullscreen">
        {{ fullscreen ? '退出全屏' : '⛶' }}
      </button>
    </div>
    <KlineChart
      ref="chart"
      :bars="bars"
      :loading="loading"
      :error="error"
      :period="period"
      :series-kind="seriesKind"
      :visible-main-indicators="visibleMainIndicators"
      :range-detector-source-identity="rangeDetectorSourceIdentity"
      :range-detector-anchor-time="rangeDetectorAnchorTime"
      :alert-markers="markers"
      @need-more-before="emit('loadEarlier')"
      @follow-latest-change="followLatest = $event"
    />
  </section>
</template>

<style scoped>
.market-kline-stage { position: relative; min-width: 0; }
.market-kline-stage__controls { position: absolute; z-index: 4; top: 10px; right: 10px; display: flex; gap: 8px; }
.market-kline-stage__controls button { min-height: 44px; min-width: 44px; padding: 0 10px; border: 1px solid var(--gy-border); border-radius: var(--gy-radius-sm); color: var(--gy-text-primary); background: var(--gy-bg-panel); cursor: pointer; }
.market-kline-stage--fullscreen { display: grid; height: 100vh; padding: 16px; background: var(--gy-bg-app); }
.market-kline-stage--fullscreen :deep(.kline-shell) { height: 100%; }
</style>
