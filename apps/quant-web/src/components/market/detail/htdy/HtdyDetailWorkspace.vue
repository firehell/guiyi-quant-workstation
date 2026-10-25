<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'

import { retainedReferenceFocus } from '@/utils/retainedReferenceFocus'
import ObservedReferenceRecords from '@/components/market/detail/ObservedReferenceRecords.vue'
import { actualEventsToOwnedMarkers } from '@/utils/historicalSignalMerge'
import HtdyChartStage from './HtdyChartStage.vue'
import { getAlertEvents } from '@/api/alerts'
import { usePersistentAlertMarkers } from '@/composables/usePersistentAlertMarkers'
import { rangeDetectorStatusText } from '@/utils/rangeDetectorStatus'
import { useRangeDetectorOverlayWarmup } from '@/composables/useRangeDetectorOverlayWarmup'
import type { MarketSeriesMutation } from '@/composables/useMarketSeries'
import type { BarData } from '@/types/market'
import type { MarketDetailHeaderModel, MarketDetailIdentity } from '@/types/marketDetail'
import type { FlexibleDetailPreferences } from '@/utils/marketDetailPreferences'
import { visibleMainIndicatorsForOverlay } from '@/utils/mainIndicators'
import { ALERT_RULE_CODES } from '@/utils/alertRules'

const props = defineProps<{
  identity: MarketDetailIdentity; header: MarketDetailHeaderModel; bars: BarData[]; mutation: MarketSeriesMutation
  loading: boolean; error: string | null; preferences: FlexibleDetailPreferences; hasMoreBefore: boolean
  loadingBefore?: boolean; historyError?: string | null
  loadEarlier: () => Promise<void>; identityWarning?: string | null
}>()
const emit = defineEmits<{ updatePreferences: [preferences: FlexibleDetailPreferences]; 'history-availability': [available: boolean]; 'focus-resolved': [focusBarEnd: string] }>()
const selectedFocus = ref<string | null>(null)
const focusError = ref<string | null>(null)
let focusGeneration = 0
const realtimeEnabled = computed(() => props.identity.frequency === '60m')
const actualSignals = computed(() => realtimeEnabled.value ? actualEventsToOwnedMarkers(loader.events.value, props.bars, { symbol: props.identity.symbol, strategy: 'htdy', frequency: props.identity.frequency }) : [])
async function focusObservation(identity: { barEnd: string; physicalContract: string }) {
  const own = ++focusGeneration, key = sourceIdentity.value
  const current = () => own === focusGeneration && key === sourceIdentity.value
  focusError.value = null
  try {
    const found = await retainedReferenceFocus(identity, { bars: () => props.bars, hasMore: () => props.hasMoreBefore, loadEarlier: props.loadEarlier, current })
    if (!current()) return
    if (found) { selectedFocus.value = identity.barEnd; workspace.value?.querySelector('.kline-stage')?.scrollIntoView({ block: 'start', behavior: 'smooth' }) }
    else focusError.value = '未找到该物理合约对应的精确历史K线，请核对数据范围'
  } catch { if (current()) focusError.value = '历史行情读取失败，请重试定位。' }
}
const optionalEmaIndicators = computed(() => props.preferences.optionalEmaIndicators)
const showRangeDetector = computed(() => props.preferences.showRangeDetector)
const workspace = ref<HTMLElement | null>(null)
const sourceIdentity = computed(() => [props.identity.seriesKind, props.identity.symbol, props.identity.contract ?? '', props.identity.frequency].join(':'))
const visibleFrom = ref<string | null>(null)
const rangeCount = ref(0)
watch(sourceIdentity, () => { visibleFrom.value = null; rangeCount.value = 0; selectedFocus.value = null; focusError.value = null; focusGeneration++ }, { flush: 'sync' })
const rangeWarmup = useRangeDetectorOverlayWarmup({ visibleFrom, bars: computed(() => props.bars), hasMoreBefore: computed(() => props.hasMoreBefore), enabled: showRangeDetector, identityKey: sourceIdentity, loadMoreBefore: props.loadEarlier })
const loader = usePersistentAlertMarkers({ fetchEvents: getAlertEvents }, { resolveRuleCodes: () => [ALERT_RULE_CODES.HTDY] })
const indicators = computed(() => visibleMainIndicatorsForOverlay('htdy', optionalEmaIndicators.value, showRangeDetector.value))
async function refresh() {
  if (!realtimeEnabled.value) { loader.dispose(); return }
  const identity = { ...props.identity }
  await loader.sync(identity, props.bars, props.mutation.kind)
}
function openHistory() { workspace.value?.querySelector('.performance-panel')?.scrollIntoView({ block: 'start', behavior: 'smooth' }) }
defineExpose({ openHistory })
watch([() => props.identity, () => props.bars, () => props.mutation], () => { void refresh() }, { immediate: true, deep: true, flush: 'sync' })
watch(() => loader.events.value.length, value => emit('history-availability', value > 0), { immediate: true })
onBeforeUnmount(() => { focusGeneration += 1; loader.dispose() })
</script>

<template>
  <section ref="workspace" class="htdy-workspace" data-detail-workspace="htdy" :data-range-detector-status="rangeWarmup.status.value" :data-range-detector-anchor="rangeWarmup.anchorTime.value" :data-range-detector-visible-from="visibleFrom">
    <p v-if="identityWarning" class="htdy-workspace__hint" role="status">{{ identityWarning }}</p>
    <p v-if="showRangeDetector" class="htdy-workspace__hint" role="status">{{ rangeDetectorStatusText(rangeWarmup.status.value, rangeCount) }} 历史图形参考；加载更早数据可能修订箱体。</p>
    <HtdyChartStage :bars="bars" :mutation="mutation" :loading="loading" :error="error" :period="identity.frequency" :series-kind="identity.seriesKind" :visible-main-indicators="indicators" :range-detector-source-identity="sourceIdentity" :range-detector-anchor-time="rangeWarmup.anchorTime.value" :identity-key="sourceIdentity" :focus-bar-end="selectedFocus ?? identity.focusBarEnd" :has-more-before="hasMoreBefore" :loading-before="loadingBefore" :history-error="historyError" :historical-mode="false" :reference-callouts="[]" :markers="actualSignals.map(item => item.marker)" @load-earlier="loadEarlier" @focus-resolved="emit('focus-resolved', $event)" @visible-from-change="visibleFrom = $event" @range-detector-result="rangeCount = $event.count" />
    <p v-if="realtimeEnabled" class="htdy-workspace__source">60分钟实时买／卖信号｜首次观察留存，非账户成交；参考交易仅展示已建立的独立记录</p>
    <p v-else class="htdy-workspace__source" role="status">实时信号统一记录于60分钟；当前周期保留历史研究图表。</p>
    <ObservedReferenceRecords v-if="realtimeEnabled" strategy="htdy" :product="identity.symbol.toUpperCase()" :frequency="identity.frequency" :series-kind="identity.seriesKind" :through="bars.at(-1)?.trading_day" :events="loader.events.value" :unavailable="loader.unavailable.value" @focus="focusObservation" />
    <p v-if="focusError" role="status">{{ focusError }}</p>

  </section>
</template>

<style scoped>
.htdy-workspace__filter { display: flex; flex-wrap: wrap; gap: var(--gy-space-2); }
.htdy-workspace__filter button { padding: 8px 12px; min-height: 40px; border: 1px solid var(--gy-border); border-radius: var(--gy-radius-md); background: var(--gy-bg-panel); color: var(--gy-text-primary); cursor: pointer; }
.htdy-workspace__filter button[aria-pressed="true"] { border-color: var(--gy-accent); background: var(--gy-detail-accent-soft); }
.htdy-workspace__source { margin: 0; padding: 8px 12px; border-left: 2px solid var(--gy-accent); background: var(--gy-accent-soft); color: var(--gy-text-secondary); font-size: 12px; }
.htdy-workspace { display: grid; gap: var(--gy-space-4); }
.htdy-workspace__hint { margin: 0; color: var(--gy-text-muted); font-size: var(--gy-font-size-sm); }
</style>
