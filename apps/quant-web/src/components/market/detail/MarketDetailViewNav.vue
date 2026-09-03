<script setup lang="ts">
import { computed } from 'vue'

import { MARKET_FREQUENCIES, type MarketFrequency, type SeriesKind } from '@/types/market'
import type { MarketDetailIdentity, MarketDetailView, MarketDetailViewRestore } from '@/types/marketDetail'
import { resolveViewSwitchIdentity } from '@/utils/marketDetailRoute'

const props = withDefaults(defineProps<{
  identity: MarketDetailIdentity
  restore: MarketDetailViewRestore
  seriesKinds?: readonly SeriesKind[]
  frequencies?: readonly MarketFrequency[]
  contract?: string
}>(), {
  seriesKinds: () => ['actual_dominant', 'continuous', 'contract'],
  frequencies: () => MARKET_FREQUENCIES,
  contract: undefined,
})

const emit = defineEmits<{
  select: [identity: MarketDetailIdentity]
}>()

const views: readonly { value: MarketDetailView; label: string }[] = [
  { value: 'trend', label: '趋势策略' },
  { value: 'htdy', label: '火天大有' },
  { value: 'subing', label: '新苏冰' },
  { value: 'free', label: '自由看盘' },
]
const seriesLabels: Record<SeriesKind, string> = { actual_dominant: '真实主力', continuous: '主连', contract: '指定合约' }
const showSeriesControls = computed(() => props.identity.view === 'htdy' || props.identity.view === 'free')
const showFrequencyControls = computed(() => showSeriesControls.value)
const availableSeriesKinds = computed(() => props.seriesKinds.filter((kind) => kind !== 'contract' || Boolean(props.contract || props.identity.contract)))

function chooseView(view: MarketDetailView) {
  emit('select', resolveViewSwitchIdentity(view, props.identity.symbol, props.identity, props.restore))
}

function chooseSeries(seriesKind: SeriesKind) {
  emit('select', {
    ...props.identity,
    seriesKind,
    ...(seriesKind === 'contract' ? { contract: props.contract || props.identity.contract } : { contract: undefined }),
    focusBarEnd: undefined,
  })
}

function chooseFrequency(frequency: MarketFrequency) {
  emit('select', { ...props.identity, frequency, focusBarEnd: undefined })
}

function periodLabel(value: MarketFrequency) {
  return value === '1d' ? '日K' : value === '1w' ? '周K' : value
}
</script>

<template>
  <nav class="detail-view-nav" aria-label="分析视角" data-detail-section="view-nav">
    <div class="detail-view-nav__views" role="tablist" aria-label="分析视角">
      <button
        v-for="view in views"
        :key="view.value"
        type="button"
        role="tab"
        :aria-selected="identity.view === view.value"
        :class="{ 'is-active': identity.view === view.value }"
        @click="chooseView(view.value)"
      >{{ view.label }}</button>
    </div>

    <div class="detail-view-nav__controls">
      <span v-if="identity.view === 'trend'" class="detail-view-nav__fixed">固定日K</span>
      <span v-else-if="identity.view === 'subing'" class="detail-view-nav__fixed">固定15m</span>
      <div v-if="showSeriesControls" class="detail-view-nav__group" role="group" aria-label="序列">
        <button
          v-for="kind in availableSeriesKinds"
          :key="kind"
          type="button"
          :aria-pressed="identity.seriesKind === kind"
          :class="{ 'is-active': identity.seriesKind === kind }"
          @click="chooseSeries(kind)"
        >{{ seriesLabels[kind] }}</button>
      </div>
      <div v-if="showFrequencyControls" class="detail-view-nav__group" role="group" aria-label="周期">
        <button
          v-for="frequency in frequencies"
          :key="frequency"
          type="button"
          :aria-pressed="identity.frequency === frequency"
          :class="{ 'is-active': identity.frequency === frequency }"
          @click="chooseFrequency(frequency)"
        >{{ periodLabel(frequency) }}</button>
      </div>
    </div>
  </nav>
</template>

<style scoped>
.detail-view-nav { display: grid; gap: var(--gy-space-3); padding: var(--gy-space-4) 0; border-bottom: 1px solid var(--gy-border-subtle); }
.detail-view-nav__views,
.detail-view-nav__group { display: flex; align-items: center; gap: var(--gy-space-1); overflow-x: auto; }
.detail-view-nav button,
.detail-view-nav__fixed { min-height: 44px; padding: 0 var(--gy-space-3); border: 1px solid transparent; border-radius: var(--gy-radius-pill); color: var(--gy-text-secondary); background: transparent; font: inherit; white-space: nowrap; }
.detail-view-nav button { cursor: pointer; }
.detail-view-nav button:hover { background: var(--gy-bg-hover); }
.detail-view-nav button:focus-visible { outline: 2px solid var(--gy-border-focus); outline-offset: 2px; }
.detail-view-nav button.is-active { border-color: var(--gy-detail-accent); color: var(--gy-text-primary); background: var(--gy-detail-accent-soft); font-weight: 700; }
.detail-view-nav__controls { display: flex; align-items: center; gap: var(--gy-space-2); min-width: 0; }
.detail-view-nav__group { min-width: 0; }
.detail-view-nav__group button { min-height: 36px; padding: 0 var(--gy-space-2); border-color: var(--gy-border); border-radius: var(--gy-radius-md); font-size: var(--gy-font-size-sm); }
.detail-view-nav__group button.is-active { border-color: var(--gy-accent); color: var(--gy-text-on-accent); background: var(--gy-accent); }
.detail-view-nav__fixed { display: inline-flex; align-items: center; min-height: 32px; border-color: var(--gy-border); background: var(--gy-detail-section-bg); font-size: var(--gy-font-size-sm); }

@media (max-width: 640px) {
  .detail-view-nav__controls { align-items: flex-start; flex-direction: column; }
  .detail-view-nav__group { width: 100%; }
  .detail-view-nav__group button { min-height: 44px; }
}
</style>
