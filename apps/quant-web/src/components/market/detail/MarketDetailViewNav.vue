<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import { type DominantContractItem, MARKET_FREQUENCIES, type MarketFrequency, type SeriesKind } from '@/types/market'
import {
  type MarketDetailIdentity,
  type MarketDetailView,
  type MarketDetailViewRestore,
  type NewowStrategy,
} from '@/types/marketDetail'
import { resolveViewSwitchIdentity } from '@/utils/marketDetailRoute'

const props = withDefaults(defineProps<{
  products?: readonly DominantContractItem[]
  identity: MarketDetailIdentity
  restore: MarketDetailViewRestore
  seriesKinds?: readonly SeriesKind[]
  frequencies?: readonly MarketFrequency[]
  newowFrequencyInChart?: boolean
  newowFrequencies: readonly MarketFrequency[]
}>(), {
  seriesKinds: () => ['actual_dominant', 'continuous', 'contract'],
  frequencies: () => MARKET_FREQUENCIES,
  products: () => [],
})

const emit = defineEmits<{
  select: [identity: MarketDetailIdentity]
  'contract-cleared': [identity: MarketDetailIdentity]
}>()

type AnalysisChoice = NewowStrategy | Extract<MarketDetailView, 'htdy' | 'subing' | 'free'>

const views: readonly { value: AnalysisChoice; label: string }[] = [
  { value: 'oscillation', label: '震荡策略' },
  { value: 'trend', label: '趋势策略' },
  { value: 'main_rise', label: '主升浪' },
  { value: 'htdy', label: '火天大有' },
  { value: 'subing', label: '苏冰预警' },
  { value: 'free', label: '自由看盘' },
]
const activeChoice = computed<AnalysisChoice>(() => props.identity.view === 'newow'
  ? props.identity.strategy ?? 'trend'
  : props.identity.view === 'trend' ? 'trend' : props.identity.view)
const seriesLabels: Record<SeriesKind, string> = { actual_dominant: '真实主力', continuous: '主连', contract: '指定合约' }
const showSeriesControls = computed(() => props.identity.view === 'htdy' || props.identity.view === 'free')
const showFrequencyControls = computed(() => (props.identity.view === 'newow' && !props.newowFrequencyInChart) || props.identity.view === 'subing' || showSeriesControls.value)
const availableFrequencies = computed(() => props.identity.view === 'newow' ? props.newowFrequencies : props.identity.view === 'subing' ? ['15m', '30m', '60m', '1d'] as MarketFrequency[] : props.frequencies)
const availableSeriesKinds = computed(() => props.seriesKinds.filter((kind) => kind !== 'contract'))
const allowsContract = computed(() => (props.identity.view === 'free' || props.identity.view === 'htdy') && props.seriesKinds.includes('contract'))
const symbol = ref(props.identity.symbol)
const contract = ref(props.identity.contract ?? '')

watch(() => props.identity, (identity) => {
  symbol.value = identity.symbol
  contract.value = identity.contract ?? ''
}, { deep: true })

function chooseView(view: AnalysisChoice) {
  if (view === 'trend' || view === 'oscillation' || view === 'main_rise') {
    const restored = resolveViewSwitchIdentity('newow', props.identity.symbol, props.identity, props.restore)
    const frequency = props.identity.view === 'newow'
      ? props.identity.frequency
      : props.newowFrequencies.includes(restored.frequency) ? restored.frequency : props.newowFrequencies[0] ?? restored.frequency
    emit('select', {
      view: 'newow', symbol: props.identity.symbol, strategy: view,
      seriesKind: 'actual_dominant', frequency,
    })
    return
  }
  emit('select', resolveViewSwitchIdentity(view, props.identity.symbol, props.identity, props.restore))
}

function chooseSeries(seriesKind: SeriesKind) {
  if (seriesKind === 'contract' && !contract.value.trim()) return
  emit('select', {
    ...props.identity,
    seriesKind,
    ...(seriesKind === 'contract' ? { contract: contract.value.trim().toUpperCase() } : { contract: undefined }),
    focusBarEnd: undefined,
  })
}

function chooseFrequency(frequency: MarketFrequency) {
  emit('select', { ...props.identity, frequency, focusBarEnd: undefined })
}

function chooseSymbol(nextValue = symbol.value) {
  const nextSymbol = nextValue.trim().toLowerCase()
  if (!/^[a-z]+$/.test(nextSymbol)) return
  if (nextSymbol !== props.identity.symbol && props.identity.seriesKind === 'contract') {
    contract.value = ''
    emit('contract-cleared', {
      view: props.identity.view,
      symbol: nextSymbol,
      seriesKind: 'actual_dominant',
      frequency: props.identity.frequency,
    })
    return
  }
  emit('select', { ...props.identity, symbol: nextSymbol, focusBarEnd: undefined })
}

defineExpose({ selectSymbol: chooseSymbol })

function periodLabel(value: MarketFrequency) {
  if (props.identity.view === 'newow') return value
  if (props.identity.view === 'subing') return value === '1d' ? '日线' : value.replace('m', '分')
  return value === '1d' ? '日K' : value === '1w' ? '周K' : value
}
</script>

<template>
  <nav class="detail-view-nav" aria-label="分析视角" data-detail-section="view-nav">
    <div class="detail-view-nav__views" role="tablist" aria-label="分析选项">
      <button
        v-for="view in views"
        :key="view.value"
        type="button"
        role="tab"
        :aria-selected="activeChoice === view.value"
        :class="{ 'is-active': activeChoice === view.value }"
        @click="chooseView(view.value)"
      >{{ view.label }}</button>
    </div>

    <div v-if="showSeriesControls || showFrequencyControls" class="detail-view-nav__controls">
      <div v-if="showSeriesControls" class="detail-view-nav__group" role="group" aria-label="序列">
        <button
          v-for="kind in availableSeriesKinds"
          :key="kind"
          type="button"
          :aria-pressed="identity.seriesKind === kind"
          :class="{ 'is-active': identity.seriesKind === kind }"
          @click="chooseSeries(kind)"
        >{{ seriesLabels[kind] }}</button>
        <template v-if="allowsContract">
          <input v-model="contract" aria-label="指定合约" placeholder="例如 JM2601" @change="chooseSeries('contract')">
          <button
            type="button"
            :aria-pressed="identity.seriesKind === 'contract'"
            :class="{ 'is-active': identity.seriesKind === 'contract' }"
            @click="chooseSeries('contract')"
          >{{ seriesLabels.contract }}</button>
        </template>
      </div>
      <div v-if="showFrequencyControls" class="detail-view-nav__group" role="group" aria-label="周期">
        <button
          v-for="frequency in availableFrequencies"
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
.detail-view-nav { display: grid; gap: var(--gy-space-2); padding: var(--gy-space-2) 0; border-bottom: 1px solid var(--gy-border-subtle); }
.detail-view-nav__views,
.detail-view-nav__group { display: flex; align-items: center; gap: var(--gy-space-1); overflow-x: auto; }
.detail-view-nav button,
.detail-view-nav__fixed { min-height: 36px; padding: 0 var(--gy-space-3); border: 1px solid transparent; border-radius: var(--gy-radius-pill); color: var(--gy-text-secondary); background: transparent; font: inherit; white-space: nowrap; }
.detail-view-nav button { cursor: pointer; }
.detail-view-nav button:hover { background: var(--gy-bg-hover); }
.detail-view-nav button:focus-visible { outline: 2px solid var(--gy-border-focus); outline-offset: 2px; }
.detail-view-nav button.is-active { border-color: var(--gy-detail-accent); color: var(--gy-text-primary); background: var(--gy-detail-accent-soft); font-weight: 700; }
.detail-view-nav__controls { display: flex; align-items: center; gap: var(--gy-space-2); min-width: 0; }
.detail-view-nav__group { min-width: 0; }
.detail-view-nav__group button { min-height: 36px; padding: 0 var(--gy-space-2); border-color: var(--gy-border); border-radius: var(--gy-radius-md); font-size: var(--gy-font-size-sm); }
.detail-view-nav__symbol,
.detail-view-nav__group input { min-width: 0; min-height: 36px; max-width: 128px; padding: 0 var(--gy-space-2); border: 1px solid var(--gy-border); border-radius: var(--gy-radius-md); color: var(--gy-text-primary); background: var(--gy-bg-panel); font: inherit; }
.detail-view-nav__group button.is-active { border-color: var(--gy-accent); color: var(--gy-text-on-accent); background: var(--gy-accent); }
.detail-view-nav__fixed { display: inline-flex; align-items: center; min-height: 32px; border-color: var(--gy-border); background: var(--gy-detail-section-bg); font-size: var(--gy-font-size-sm); }
@media (max-width: 640px) {
  .detail-view-nav { margin-inline: calc(-1 * var(--gy-space-3)); }
  .detail-view-nav__views,
  .detail-view-nav__controls { padding-inline: var(--gy-space-3); }
  .detail-view-nav__views { width: auto; scroll-padding-inline: var(--gy-space-3); }
  .detail-view-nav__views button { min-height: 44px; }
  .detail-view-nav__controls { align-items: flex-start; flex-direction: column; }
  .detail-view-nav__group { width: 100%; }
  .detail-view-nav__group button { min-height: 44px; }
}
</style>
