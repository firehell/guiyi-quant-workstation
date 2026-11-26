<script setup lang="ts">
import DetailChartToolbar from './DetailChartToolbar.vue'
import { computed, ref, watch } from 'vue'

import { type MarketProductDirectoryItem, MARKET_FREQUENCIES, type MarketFrequency, type SeriesKind } from '@/types/market'
import {
  type MarketDetailIdentity,
  type MarketDetailView,
  type MarketDetailViewRestore,
  type NewowStrategy,
} from '@/types/marketDetail'
import { resolveViewSwitchIdentity } from '@/utils/marketDetailRoute'
import { workstationNewowMode } from '@/utils/workstationRoutes'

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
  afterMarket?: boolean
  marketFoundation?: boolean
  showReferencePrices?: boolean
  frequencyInWorkspace?: boolean
}>(), {
  seriesKinds: () => ['actual_dominant', 'contract'],
  frequencies: () => MARKET_FREQUENCIES,
  products: () => [],
  frequencyInWorkspace: false,
  showReferencePrices: true,
})

const emit = defineEmits<{
  select: [identity: MarketDetailIdentity]
  'contract-cleared': [identity: MarketDetailIdentity]
  'ai-analysis': []
}>()

type AnalysisChoice = NewowStrategy | 'dual' | Extract<MarketDetailView, 'htdy' | 'subing' | 'free'>

const views: readonly { value: AnalysisChoice; label: string }[] = [
  { value: 'trend', label: '趋势' },
  { value: 'oscillation', label: '震荡' },
  { value: 'dual', label: '双策略' },
  { value: 'main_rise', label: '主升浪' },
  { value: 'free', label: '自由看盘' },
  { value: 'htdy', label: '火天大有' },
  { value: 'subing', label: '苏冰预警' },
]
const experimentOptions = [{value:'osc-test',label:'测试'}, {value:'osc-test2',label:'测试2'}, {value:'osc-test3',label:'测试3'}, {value:'osc-test4',label:'测试4'}, {value:'osc-test5',label:'测试5'}] as const
function chooseTest(choice: MarketDetailIdentity['newowTest'] | 'main_rise') {
  const base = props.identity.view === 'newow' ? props.identity : resolveViewSwitchIdentity('newow', props.identity.symbol, props.identity, props.restore)
  emit('select', { ...base, view: 'newow', strategy: choice === 'main_rise' ? 'main_rise' : 'oscillation', newowMode: undefined,
    newowSource: undefined, newowTest: choice === 'main_rise' ? undefined : choice, homeContext: undefined, focusBarEnd: undefined })
}
const activeChoice = computed<AnalysisChoice>(() => props.identity.view === 'newow'
  ? props.identity.newowMode === 'dual' ? 'dual' : props.identity.strategy ?? 'trend'
  : props.identity.view === 'trend' ? 'trend' : props.identity.view)
const showFrequencyControls = computed(() => !props.frequencyInWorkspace && ['newow', 'subing', 'htdy', 'free'].includes(props.identity.view))

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
      newowSource: props.marketFoundation ? undefined : props.afterMarket ? 'after-market' : restored.newowSource,
      newowTest: undefined, newowMode: view === 'dual' ? 'dual' : undefined,
      homeContext: undefined, focusBarEnd: undefined,
    })
    return
  }
  const identity = resolveViewSwitchIdentity(view, props.identity.symbol, props.identity, props.restore)
  emit('select', identity)
}

function chooseNewowReference() {
  const base = resolveViewSwitchIdentity('newow', props.identity.symbol, props.identity, props.restore)
  const mode = workstationNewowMode()
  emit('select', { ...base, newowSource: 'after-market', newowTest: undefined,
    strategy: mode === 'oscillation' ? 'oscillation' : 'trend',
    newowMode: mode === 'dual' ? 'dual' : undefined, homeContext: undefined, focusBarEnd: undefined })
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


</script>

<template>
  <nav class="detail-view-nav" aria-label="分析视角" data-detail-section="view-nav">
    <div class="detail-view-nav__row">
      <div class="detail-view-nav__views" role="tablist" aria-label="分析选项">
        <button v-for="view in views.filter(view => ['free', 'htdy', 'subing'].includes(view.value))" :key="view.value"
          type="button" role="tab" :aria-selected="activeChoice === view.value"
          :class="{ 'is-active': activeChoice === view.value }" @click="chooseView(view.value)">{{ view.label }}</button>
        <button type="button" role="tab" :aria-selected="identity.view === 'newow'"
          :class="{ 'is-active': identity.view === 'newow' }" @click="chooseNewowReference">牛哇参考</button>
      </div>
      <div class="detail-view-nav__display"><slot name="display-controls" /></div>
    </div>
    <div v-if="identity.view === 'newow'" class="detail-view-nav__views" aria-label="牛哇策略" :role="afterMarket ? 'group' : 'tablist'">
      <template v-for="view in views.filter(view => ['oscillation', 'trend', 'dual'].includes(view.value) || (marketFoundation && view.value === 'main_rise'))" :key="view.value"><button
        type="button"
        :role="afterMarket ? undefined : 'tab'"
        :aria-pressed="afterMarket ? activeChoice === view.value : undefined"
        :aria-selected="afterMarket ? undefined : activeChoice === view.value"
        :class="{ 'is-active': activeChoice === view.value }"
        @click="chooseView(view.value)"
      >{{ afterMarket || view.value === 'dual' ? view.label : view.label + '策略' }}</button>
      <span v-if="view.value === 'dual'" id="newow-strategy-test-anchor">
        <details v-if="!afterMarket && identity.view !== 'newow'" class="newow-test-menu"><summary aria-label="牛哇T策略">T ▾</summary><div class="nav-test-options"><button v-for="option in experimentOptions" :key="option.value" type="button" @click="chooseTest(option.value)">{{ option.label }}</button><button type="button" @click="chooseTest('main_rise')">主升浪</button></div></details>
      </span>
      <button v-if="!afterMarket && view.value === 'dual'" type="button" class="detail-view-nav__ai" @click="openAiAnalysis">AI分析</button></template>
    </div>

    <DetailChartToolbar v-if="showFrequencyControls" :identity="identity"
      :frequencies="identity.view === 'newow' ? newowFrequencies : frequencies" :show-reference-prices="showReferencePrices"
      :target-price="targetPrice" :absorb-price="absorbPrice" :status="referencePriceStatus" @select="chooseFrequency" />
  </nav>
</template>

<style scoped>
.newow-test-menu { position:relative; }
.newow-test-menu summary { display:flex; align-items:center; height:28px; padding:0 12px; border-radius:6px; background:#f2f2f7; color:#999; font-size:13px; font-weight:600; cursor:pointer; list-style:none; }
.newow-test-menu summary::-webkit-details-marker { display:none; }
.nav-test-options { position:absolute; z-index:100; top:100%; min-width:88px; background:var(--gy-bg-panel); box-shadow:0 4px 16px #0002; }
.nav-test-options button { display:block; width:100%; }
.detail-view-nav { display: grid; gap: var(--gy-space-2); padding: var(--gy-space-2) 0; border-bottom: 1px solid var(--gy-border-subtle); }
.detail-view-nav__row, .detail-view-nav__display { display: flex; align-items: center; gap: var(--gy-space-2); min-width: 0; }
.detail-view-nav__display { margin-inline-start: auto; flex-wrap: wrap; }
.detail-view-nav__views,
.detail-view-nav__group { display: flex; align-items: center; gap: var(--gy-space-1); min-width: 0; overflow-x: auto; }
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
  .detail-view-nav__row { flex-wrap: wrap; }
  .detail-view-nav__display { margin-inline: var(--gy-space-3); }
  .detail-view-nav__views { width: auto; scroll-padding-inline: var(--gy-space-3); }
  .detail-view-nav__views button { min-height: 44px; }
  .detail-view-nav__controls { align-items: flex-start; flex-direction: column; }
  .detail-view-nav__group { width: 100%; }
  .detail-view-nav__group button { min-height: 44px; }
}
</style>
