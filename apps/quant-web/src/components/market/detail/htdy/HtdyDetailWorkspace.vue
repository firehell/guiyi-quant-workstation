<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

import MarketDetailInsightDeck from '@/components/market/detail/MarketDetailInsightDeck.vue'
import MarketDetailSectionTabs from '@/components/market/detail/MarketDetailSectionTabs.vue'
import HtdyHistoricalPanel from './HtdyHistoricalPanel.vue'
import { getHtdyReference } from '@/api/htdyReference'
import { useHtdyHistoricalReference } from '@/composables/useHtdyHistoricalReference'
import type { ReferenceTradeView } from '@/types/referenceTrading'
import HtdyChartStage from './HtdyChartStage.vue'
import ReferenceTradePanel from '@/components/market/detail/ReferenceTradePanel.vue'
import { getAlertEvents, getAlertRuntimeStatus, getProductAlerts } from '@/api/alerts'
import { useHtdyAlertFacts } from '@/composables/useHtdyAlertFacts'
import { usePersistentAlertMarkers } from '@/composables/usePersistentAlertMarkers'
import { useRangeDetectorOverlayWarmup } from '@/composables/useRangeDetectorOverlayWarmup'
import type { MarketSeriesMutation } from '@/composables/useMarketSeries'
import type { BarData, OptionalEmaIndicatorId } from '@/types/market'
import type { DetailViewModel, MarketDetailHeaderModel, MarketDetailIdentity } from '@/types/marketDetail'
import type { FlexibleDetailPreferences } from '@/utils/marketDetailPreferences'
import { visibleMainIndicatorsForOverlay } from '@/utils/mainIndicators'
import { buildKlineDerivedData } from '@/utils/klineViewModel'
import { buildHtdyDetailViewModel, currentHtdyObservation } from '@/utils/htdyDetailViewModel'
import { ALERT_RULE_CODES, isHtdyAlertEvent } from '@/utils/alertRules'

const props = defineProps<{
  identity: MarketDetailIdentity; header: MarketDetailHeaderModel; bars: BarData[]; mutation: MarketSeriesMutation
  loading: boolean; error: string | null; preferences: FlexibleDetailPreferences; hasMoreBefore: boolean
  loadingBefore?: boolean; historyError?: string | null
  loadEarlier: () => Promise<void>; identityWarning?: string | null
}>()
const emit = defineEmits<{ updatePreferences: [preferences: FlexibleDetailPreferences]; 'history-availability': [available: boolean]; 'focus-resolved': [focusBarEnd: string] }>()
const recordingMode = ref<'historical_replay' | 'forward_observation'>('historical_replay')
const historical = useHtdyHistoricalReference(getHtdyReference)
const historySupported = computed(() => props.identity.seriesKind === 'actual_dominant' && ['15m', '30m', '60m', '1d'].includes(props.identity.frequency))
const selectedFocus = ref<string | null>(null)
const focusError = ref<string | null>(null)
let focusGeneration = 0
watch(() => [props.identity.symbol, props.identity.frequency, props.identity.seriesKind], () => {
  focusGeneration += 1; selectedFocus.value = null; focusError.value = null
  historical.reset(props.identity.symbol, props.identity.frequency)
  if (historySupported.value) void historical.read()
}, { immediate: true })
watch(() => props.bars.at(-1)?.time ?? null, value => { historical.latestBar.value = value }, { immediate: true })
const historyMarkers = computed(() => (historical.result.value?.signals ?? []).filter(signal => props.bars.some(bar => Date.parse(bar.time) === Date.parse(signal.bar_end) && bar.physicalContract === signal.physical_contract)).flatMap(signal => signal.observation_types.map(direction => ({
  id: `htdy-history:${signal.physical_contract}:${signal.bar_end}:${direction}`, time: signal.bar_end,
  label: direction === 'buy' ? '买入参考' : '卖出参考', tone: 'htdy' as const,
  position: direction === 'buy' ? 'belowBar' as const : 'aboveBar' as const,
  shape: direction === 'buy' ? 'arrowUp' as const : 'arrowDown' as const,
}))))
async function focusTrade(trade: ReferenceTradeView) {
  const generation = ++focusGeneration
  focusError.value = null
  while (generation === focusGeneration) {
    const found = props.bars.find(bar => Date.parse(bar.time) === Date.parse(trade.entry_bar_end))
    if (found) {
      if (found.physicalContract !== trade.physical_contract) focusError.value = '目标合约与图表来源不一致'
      else selectedFocus.value = trade.entry_bar_end
      return
    }
    if (!props.hasMoreBefore || (props.bars[0] && Date.parse(props.bars[0].time) < Date.parse(trade.entry_bar_end))) break
    const previous = props.bars[0]?.time
    try { await props.loadEarlier(); await nextTick() } catch { break }
    if (props.bars[0]?.time === previous) break
  }
  if (generation === focusGeneration) focusError.value = '未找到该合约对应的精确历史K线，请核对数据范围'
}
const optionalEmaIndicators = ref<OptionalEmaIndicatorId[]>([...props.preferences.optionalEmaIndicators])
const showRangeDetector = ref(props.preferences.showRangeDetector)
const activeTab = ref<string | null>('explanation')
const tabs = ref<InstanceType<typeof MarketDetailSectionTabs> | null>(null)
const sourceIdentity = computed(() => [props.identity.seriesKind, props.identity.symbol, props.identity.contract ?? '', props.identity.frequency].join(':'))
const rangeWarmup = useRangeDetectorOverlayWarmup({ bars: computed(() => props.bars), hasMoreBefore: computed(() => props.hasMoreBefore), enabled: showRangeDetector, identityKey: sourceIdentity, loadMoreBefore: props.loadEarlier })
const rangeState = computed(() => !showRangeDetector.value ? 'disabled' : rangeWarmup.loading.value ? 'loading' : rangeWarmup.unavailableReason.value === null && rangeWarmup.anchorTime.value ? 'ready' : 'insufficient')
const loader = usePersistentAlertMarkers({ fetchEvents: getAlertEvents }, { resolveRuleCodes: () => [ALERT_RULE_CODES.HTDY] })
const alertFacts = useHtdyAlertFacts({ fetchRuntime: getAlertRuntimeStatus, fetchProductAlerts: getProductAlerts })
const rawState = computed(() => {
  try {
    const derived = buildKlineDerivedData(props.bars, ['htdy']).htdy
    return { observation: derived ? currentHtdyObservation(props.bars, derived.markers) : null, unavailable: false }
  } catch { return { observation: undefined, unavailable: true } }
})
const model = computed<DetailViewModel>(() => buildHtdyDetailViewModel({ identity: props.identity, header: props.header, rawObservation: rawState.value.observation ?? null, rawUnavailable: rawState.value.unavailable, events: loader.events.value.filter(isHtdyAlertEvent), alertUnavailable: loader.unavailable.value, runtime: alertFacts.runtime.value, ruleScope: alertFacts.ruleScope.value }))
const indicators = computed(() => visibleMainIndicatorsForOverlay('htdy', optionalEmaIndicators.value, showRangeDetector.value))
const sectionsForTab = computed(() => {
  if (activeTab.value === 'explanation') return model.value.disclosureSections.filter((section) => section.id === 'htdy-explanation')
  if (activeTab.value === 'alerts') return model.value.disclosureSections.filter((section) => section.id === 'htdy-alerts')
  return model.value.disclosureSections.filter((section) => section.id !== 'htdy-explanation' && section.id !== 'htdy-alerts')
})

async function refresh() {
  const identity = { ...props.identity }
  await Promise.all([
    loader.sync(identity, props.bars, props.mutation.kind),
    alertFacts.refresh({ symbol: identity.symbol, frequency: identity.frequency }),
  ])
}
function updatePreferences() { emit('updatePreferences', { seriesKind: 'actual_dominant', frequency: props.identity.frequency, optionalEmaIndicators: [...optionalEmaIndicators.value], showRangeDetector: showRangeDetector.value }) }
function toggleEma(value: OptionalEmaIndicatorId) { optionalEmaIndicators.value = optionalEmaIndicators.value.includes(value) ? optionalEmaIndicators.value.filter((item) => item !== value) : [...optionalEmaIndicators.value, value] }
function openHistory() { document.querySelector('.htdy-history')?.scrollIntoView({ block: 'start', behavior: 'smooth' }); if (recordingMode.value === 'forward_observation') tabs.value?.openHistory() }
defineExpose({ openHistory })
watch([() => props.identity, () => props.bars, () => props.mutation], () => { void refresh() }, { immediate: true, deep: true })
watch([optionalEmaIndicators, showRangeDetector], () => { updatePreferences(); if (!showRangeDetector.value) rangeWarmup.reset() }, { deep: true })
watch(recordingMode, () => { focusGeneration += 1; selectedFocus.value = null; focusError.value = null })
watch(() => model.value.history.length + (historical.result.value?.trades.length ?? 0), (value) => emit('history-availability', value > 0), { immediate: true })
onBeforeUnmount(() => { focusGeneration += 1; historical.dispose(); loader.dispose(); alertFacts.dispose() })
</script>

<template>
  <section class="htdy-workspace" data-detail-workspace="htdy">
    <p v-if="identityWarning" class="htdy-workspace__hint" role="status">{{ identityWarning }}</p>
    <HtdyChartStage :bars="bars" :mutation="mutation" :loading="loading" :error="error" :period="identity.frequency" :series-kind="identity.seriesKind" :visible-main-indicators="indicators" :range-detector-source-identity="sourceIdentity" :range-detector-anchor-time="rangeState === 'ready' ? rangeWarmup.anchorTime.value : null" :identity-key="sourceIdentity" :focus-bar-end="selectedFocus ?? identity.focusBarEnd" :has-more-before="hasMoreBefore" :loading-before="loadingBefore" :history-error="historyError" :historical-mode="recordingMode === 'historical_replay'" :markers="recordingMode === 'historical_replay' ? historyMarkers : loader.markers.value" @load-earlier="loadEarlier" @focus-resolved="emit('focus-resolved', $event)" />
    <p class="htdy-workspace__source">历史重算·乐观参考｜零费用/零滑点　历史信号与实际预警分开展示</p>
    <nav class="htdy-workspace__filter" aria-label="火天大有记录模式"><button type="button" :aria-pressed="recordingMode === 'historical_replay'" @click="recordingMode = 'historical_replay'">历史重算参考</button><button type="button" :aria-pressed="recordingMode === 'forward_observation'" @click="recordingMode = 'forward_observation'">实际记录</button></nav>
    <p v-if="recordingMode === 'historical_replay' && !historySupported" role="status">此周期或序列暂不支持历史重算参考。</p>
    <HtdyHistoricalPanel v-else-if="recordingMode === 'historical_replay'" :stale="historical.stale.value" :result="historical.result.value" :loading="historical.loading.value" :error="historical.error.value" :focus-error="focusError" @more="historical.read(true)" @retry="historical.read()" @window="historical.read(false, $event)" @focus="focusTrade" />
    <ReferenceTradePanel v-else strategy="htdy" :product="identity.symbol.toUpperCase()" :frequency="identity.frequency" :through="bars.at(-1)?.trading_day" :historical-available="false" />
    <div class="htdy-workspace__indicators"><details><summary>指标设置</summary><label v-for="item in [['ema_10', 'EMA10'], ['ema_21', 'EMA21'], ['ema_60', 'EMA60']] as const" :key="item[0]"><input type="checkbox" :checked="optionalEmaIndicators.includes(item[0])" @change="toggleEma(item[0])">{{ item[1] }}</label><label><input v-model="showRangeDetector" type="checkbox">箱体识别（Range）</label></details></div>
    <MarketDetailSectionTabs ref="tabs" :tabs="[{ id: 'explanation', label: '信号说明' }, { id: 'alerts', label: '预警与运行' }, { id: 'data', label: '数据与历史' }]" :active-id="activeTab" :history="model.history" @select="activeTab = $event"><template #default><MarketDetailInsightDeck :identity-key="sourceIdentity" :sections="sectionsForTab" :default-open="true" /></template></MarketDetailSectionTabs>
  </section>
</template>

<style scoped>
.htdy-workspace__filter { display: flex; flex-wrap: wrap; gap: var(--gy-space-2); }
.htdy-workspace__filter button { padding: 8px 12px; min-height: 40px; border: 1px solid var(--gy-border); border-radius: var(--gy-radius-md); background: var(--gy-bg-panel); color: var(--gy-text-primary); cursor: pointer; }
.htdy-workspace__filter button[aria-pressed="true"] { border-color: var(--gy-accent); background: var(--gy-detail-accent-soft); }
.htdy-workspace__source { margin: 0; padding: 8px 12px; border-left: 2px solid var(--gy-accent); background: var(--gy-accent-soft); color: var(--gy-text-secondary); font-size: 12px; }
.htdy-workspace { display: grid; gap: var(--gy-space-4); }
.htdy-workspace__indicators, .htdy-workspace__semantic { padding: var(--gy-space-3); border: 1px solid var(--gy-border); border-radius: var(--gy-radius-md); background: var(--gy-bg-panel); }
.htdy-workspace details { display: flex; gap: 12px; flex-wrap: wrap; }.htdy-workspace summary { cursor: pointer; }.htdy-workspace label { margin-right: 8px; }
.htdy-workspace__semantic { margin: 0; color: var(--gy-status-warning); background: color-mix(in srgb, var(--gy-status-warning) 10%, transparent); }.htdy-workspace__hint { margin: 0; color: var(--gy-text-muted); font-size: var(--gy-font-size-sm); }
</style>
