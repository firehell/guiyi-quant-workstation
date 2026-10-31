<script setup lang="ts">
import type { PatternGeometry } from '@/utils/newowPatternDisplay'
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import type { KlineQualityBreak, KlineReferenceCallout, KlineReferenceIndicator, KlineReferenceSelection } from '@/types/referenceCallout'
import KlineChart from '@/components/kline/KlineChart.vue'
import MarketDetailIcon from '@/components/market/detail/MarketDetailIcon.vue'
import type { BarData, KlineMarker, MainIndicatorId, SeriesKind } from '@/types/market'
import type { MarketSeriesMutation } from '@/composables/useMarketSeries'

const props = withDefaults(defineProps<{
  patternGeometry?: PatternGeometry | null
  bars: BarData[]
  mutation: MarketSeriesMutation
  loading: boolean
  error: string | null
  period: string
  seriesKind: SeriesKind
  visibleMainIndicators: MainIndicatorId[]
  rangeDetectorSourceIdentity: string
  rangeDetectorAnchorTime: string | null
  identityKey: string
  focusBarEnd?: string | null
  showNavigationButtons?: boolean
  showDerivedMarkers?: boolean
  markers?: KlineMarker[]
  markerSelectionEnabled?: boolean
  referenceCallouts?: KlineReferenceCallout[]
  referenceIndicators?: KlineReferenceIndicator[]
  referenceSelection?: KlineReferenceSelection[]
  qualityBreaks?: KlineQualityBreak[]
  hasMoreBefore?: boolean
  loadingBefore?: boolean
  historyError?: string | null
  focusRequestId?: number
}>(), { markers: () => [], markerSelectionEnabled: true, showDerivedMarkers: true, showNavigationButtons: true })

const emit = defineEmits<{
  loadEarlier: []
  'visible-from-change': [time: string | null]
  'range-detector-result': [result: { count: number; calculationMs: number }]
  'focus-resolved': [focusBarEnd: string]
  'marker-select': [marker: KlineMarker]
}>()
const chart = ref<InstanceType<typeof KlineChart> | null>(null)
const followLatest = ref(true)
const fullscreen = ref(false)
let resolvedFocusKey: string | null = null

function resolveFocus(): boolean {
  if (!props.focusBarEnd) return false
  const focusKey = `${props.identityKey}:${props.focusBarEnd}:${props.focusRequestId ?? 0}`
  if (resolvedFocusKey === focusKey) return true
  if (!chart.value?.revealTime(props.focusBarEnd)) return false
  resolvedFocusKey = focusKey
  followLatest.value = false
  emit('focus-resolved', props.focusBarEnd)
  return true
}

watch(() => props.identityKey, () => {
  resolvedFocusKey = null
  followLatest.value = true
})

watch(() => [props.identityKey, props.focusBarEnd, props.focusRequestId], async () => {
  await nextTick()
  resolveFocus()
}, { immediate: true })

onMounted(async () => {
  await nextTick()
  requestAnimationFrame(() => resolveFocus())
})

watch(() => props.mutation, async (mutation) => {
  await nextTick()
  if (!chart.value) return
  if (mutation.kind === 'replace') chart.value.replaceBars(props.bars, !followLatest.value)
  else if (mutation.kind === 'prepend') chart.value.prependBars(mutation.bars)
  else {
    for (const bar of mutation.bars) chart.value.updateBar(bar)
    if (followLatest.value) chart.value.scrollToLatest()
  }
  resolveFocus()
}, { deep: true })

function syncFullscreen() { fullscreen.value = Boolean(document.fullscreenElement) }
document.addEventListener('fullscreenchange', syncFullscreen)
onBeforeUnmount(() => document.removeEventListener('fullscreenchange', syncFullscreen))
</script>

<template>
  <section class="market-kline-stage" :class="{ 'market-kline-stage--fullscreen': fullscreen }">
    <div class="market-kline-stage__controls">
      <button v-if="showNavigationButtons && !followLatest" type="button" @click="chart?.scrollToLatest()"><MarketDetailIcon name="refresh" :size="16" />回到最新</button>
    </div>
    <div v-if="hasMoreBefore !== undefined && (loadingBefore || historyError || hasMoreBefore === false)" class="market-kline-stage__history" role="status">
      <button v-if="hasMoreBefore && historyError" type="button" :disabled="loading || loadingBefore" @click="emit('loadEarlier')">
        {{ loadingBefore ? '加载中…' : '重试' }}
      </button>
      <span v-if="loadingBefore">加载中…</span>
      <span v-if="hasMoreBefore === false && !loading && bars.length">已到最早可用数据</span>
      <span v-if="historyError">{{ historyError }}</span>
    </div>
    <KlineChart
      :show-derived-markers="showDerivedMarkers"
      ref="chart"
      :bars="bars"
    :pattern-geometry="patternGeometry"
      :loading="loading"
      :error="error"
      :period="period"
      :series-kind="seriesKind"
      :visible-main-indicators="visibleMainIndicators"
      :range-detector-source-identity="rangeDetectorSourceIdentity"
      :range-detector-anchor-time="rangeDetectorAnchorTime"
      :alert-markers="markers"
      :marker-selection-enabled="markerSelectionEnabled"
      :reference-callouts="referenceCallouts"
      :reference-indicators="referenceIndicators"
      :reference-selection="referenceSelection"
      :quality-breaks="qualityBreaks"
      @need-more-before="!loadingBefore && !historyError && hasMoreBefore !== false && emit('loadEarlier')"
      @follow-latest-change="followLatest = $event"
      @visible-from-change="emit('visible-from-change', $event)"
      @range-detector-result="emit('range-detector-result', $event)"
      @marker-select="emit('marker-select', $event)"
    />
  </section>
</template>

<style scoped>
.market-kline-stage { position: relative; min-width: 0; }
.market-kline-stage__history { display: flex; align-items: center; gap: 8px; min-height: 32px; font-size: 12px; color: var(--gy-text-secondary); }
.market-kline-stage__history button { cursor: pointer; padding: 4px 10px; border: 1px solid var(--gy-border); border-radius: 4px; background: var(--gy-bg-panel); color: inherit; }
.market-kline-stage__controls { position: absolute; z-index: 4; top: 10px; right: 10px; display: flex; gap: 8px; }
.market-kline-stage__controls button { min-height: 44px; min-width: 44px; padding: 0 10px; border: 1px solid var(--gy-border); border-radius: var(--gy-radius-sm); color: var(--gy-text-primary); background: var(--gy-bg-panel); cursor: pointer; }
.market-kline-stage--fullscreen { display: grid; height: 100vh; padding: 16px; background: var(--gy-bg-app); }
.market-kline-stage--fullscreen :deep(.kline-shell) { height: 100%; }
</style>
