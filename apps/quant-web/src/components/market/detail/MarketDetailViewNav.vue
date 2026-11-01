<script setup lang="ts">
import ChartReferenceToolbar from './ChartReferenceToolbar.vue'
import { computed, ref, watch } from 'vue'

import { type MarketProductDirectoryItem, MARKET_FREQUENCIES, type MarketFrequency, type SeriesKind } from '@/types/market'
import {
  type MarketDetailIdentity,
  type MarketDetailView,
  type MarketDetailViewRestore,
  type NewowStrategy,
} from '@/types/marketDetail'
import { switchFuturesModel } from '@/utils/newowFutures'
import { resolveViewSwitchIdentity } from '@/utils/marketDetailRoute'

const props = withDefaults(defineProps<{
  products?: readonly MarketProductDirectoryItem[]
  identity: MarketDetailIdentity
  restore: MarketDetailViewRestore
  seriesKinds?: readonly SeriesKind[]
  frequencies?: readonly MarketFrequency[]
  newowFrequencies: readonly MarketFrequency[]
  targetPrice?: string | null
  absorbPrice?: string | null
  referencePriceStatus?: string
  newowFrequencyInWorkspace?: boolean
}>(), {
  seriesKinds: () => ['actual_dominant', 'contract'],
  frequencies: () => MARKET_FREQUENCIES,
  products: () => [],
  newowFrequencyInWorkspace: false,
})

const emit = defineEmits<{
  select: [identity: MarketDetailIdentity]
  'contract-cleared': [identity: MarketDetailIdentity]
  'ai-analysis': []
}>()

type AnalysisChoice = NewowStrategy | 'dual' | Extract<MarketDetailView, 'htdy' | 'subing' | 'free'>

const views: readonly { value: AnalysisChoice; label: string }[] = [
  { value: 'oscillation', label: '震荡策略' },
  { value: 'trend', label: '趋势策略' },
  { value: 'dual', label: '双策略' },
  { value: 'htdy', label: '火天大有' },
  { value: 'subing', label: '苏冰预警' },
  { value: 'free', label: '自由看盘' },
]
const isFutures = computed(() => props.identity.strategyModel === 'futures_bidir_v1')
const futuresTests = [{value:'osc-test',label:'测试'}, {value:'osc-test2',label:'测试2'}, {value:'osc-test3',label:'测试3'}, {value:'osc-test4',label:'测试4'}] as const
function chooseTest(choice: MarketDetailIdentity['newowTest'] | 'main_rise') {
  const base = props.identity.view === 'newow' ? props.identity : resolveViewSwitchIdentity('newow', props.identity.symbol, props.identity, props.restore)
  emit('select', { ...base, view: 'newow', strategy: choice === 'main_rise' ? 'main_rise' : 'oscillation', newowMode: undefined,
    newowTest: choice === 'main_rise' ? undefined : choice, homeContext: undefined, focusBarEnd: undefined })
}
const activeChoice = computed<AnalysisChoice>(() => props.identity.view === 'newow'
  ? props.identity.newowMode === 'dual' ? 'dual' : props.identity.strategy ?? 'trend'
  : props.identity.view === 'trend' ? 'trend' : props.identity.view)
const showFrequencyControls = computed(() => (props.identity.view === 'newow' && !props.newowFrequencyInWorkspace) || ['subing', 'htdy', 'free'].includes(props.identity.view))
const availableFrequencies = computed(() => props.identity.view === 'newow' ? props.newowFrequencies : ['subing', 'htdy'].includes(props.identity.view) ? ['5m', '15m', '30m', '60m', '1d', '1w'] as MarketFrequency[] : props.frequencies)
const symbol = ref(props.identity.symbol)
const contract = ref(props.identity.contract ?? '')

watch(() => props.identity, (identity) => {
  symbol.value = identity.symbol
  contract.value = identity.contract ?? ''
}, { deep: true })

function chooseView(view: AnalysisChoice) {
  if (view === 'trend' || view === 'oscillation' || view === 'main_rise' || view === 'dual') {
    const restored = resolveViewSwitchIdentity('newow', props.identity.symbol, props.identity, props.restore)
    emit('select', {
      ...restored, strategy: view === 'dual' ? 'trend' : view,
      newowTest: undefined, newowMode: view === 'dual' ? 'dual' : undefined,
      homeContext: undefined, focusBarEnd: undefined,
    })
    return
  }
  const identity = resolveViewSwitchIdentity(view, props.identity.symbol, props.identity, props.restore)
  emit('select', identity)
}

function openAiAnalysis() {
  if (props.identity.view !== 'newow') chooseView('trend')
  emit('ai-analysis')
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
  return value === '1d' ? '日线' : value === '1w' ? '周线' : value.replace('m', '分钟')
}
</script>

<template>
  <nav class="detail-view-nav" aria-label="分析视角" data-detail-section="view-nav">
    <div class="detail-view-nav__views" role="tablist" aria-label="分析选项">
      <template v-for="view in views.filter(view => ['oscillation', 'trend', 'dual'].includes(view.value))" :key="view.value"><button
        type="button"
        role="tab"
        :aria-selected="activeChoice === view.value"
        :class="{ 'is-active': activeChoice === view.value }"
        @click="chooseView(view.value)"
      >{{ view.label }}</button>
      <span v-if="view.value === 'dual'" id="newow-strategy-test-anchor">
        <details v-if="identity.view !== 'newow'" class="newow-test-menu"><summary aria-label="牛哇T策略">T ▾</summary><div class="nav-test-options"><button v-for="option in futuresTests" :key="option.value" type="button" @click="chooseTest(option.value)">{{ option.label }}</button><button type="button" @click="chooseTest('main_rise')">主升浪</button></div></details>
      </span>
      <button v-if="view.value === 'dual'" type="button" class="detail-view-nav__ai" @click="openAiAnalysis">AI分析</button></template>
      <span v-if="identity.view === 'newow'" id="newow-channel-controls" />
      <button v-if="identity.view === 'newow'" type="button" role="switch" :aria-checked="isFutures" class="detail-view-nav__model" data-testid="futures-model-switch" @click="emit('select',switchFuturesModel(identity,!isFutures))">期货双向 {{ isFutures ? '开' : '关' }}</button>
      <details v-if="isFutures" class="detail-view-nav__tests"><summary aria-label="牛哇T策略">T</summary><div aria-label="T策略选项"><button v-for="option in futuresTests" :key="option.value" type="button" :aria-pressed="identity.newowTest===option.value" @click="chooseTest(option.value)">{{ option.label }}</button><button type="button" :aria-pressed="identity.strategy === 'main_rise'" @click="chooseTest('main_rise')">主升浪</button></div></details>
    </div>

    <div class="detail-view-nav__views detail-view-nav__secondary" role="tablist" aria-label="其他分析选项">
      <button v-for="view in views.filter(view => ['htdy', 'subing', 'free'].includes(view.value))" :key="view.value"
        type="button" role="tab" :aria-selected="activeChoice === view.value"
        :class="{ 'is-active': activeChoice === view.value }" @click="chooseView(view.value)">{{ view.label }}</button>
      <slot name="display-controls" />
    </div>



    <ChartReferenceToolbar v-if="showFrequencyControls" :target-price="targetPrice" :absorb-price="absorbPrice" :status="referencePriceStatus">
      <div class="newow-chart-frequency" role="group" aria-label="周期">
        <button v-for="frequency in availableFrequencies" :key="frequency" type="button"
          :aria-pressed="identity.frequency === frequency" :class="{ 'is-active': identity.frequency === frequency }"
          @click="chooseFrequency(frequency)">{{ periodLabel(frequency) }}</button>
      </div>
    </ChartReferenceToolbar>
  </nav>
</template>

<style scoped>
.detail-view-nav__tests { display:flex; white-space:nowrap; }
.newow-test-menu { position:relative; }
.newow-test-menu summary { display:flex; align-items:center; height:28px; padding:0 12px; border-radius:6px; background:#f2f2f7; color:#999; font-size:13px; font-weight:600; cursor:pointer; list-style:none; }
.newow-test-menu summary::-webkit-details-marker { display:none; }
.nav-test-options { position:absolute; z-index:100; top:100%; min-width:88px; background:var(--gy-bg-panel); box-shadow:0 4px 16px #0002; }
.nav-test-options button { display:block; width:100%; }
.detail-view-nav__tests summary { cursor:pointer; padding:8px; }
.detail-view-nav__model[aria-checked=true] { background:#fff0ce; border-color:#d8ad56; }
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
