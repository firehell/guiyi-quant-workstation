<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

import ObservedReferenceRecords from '@/components/market/detail/ObservedReferenceRecords.vue'
import { historicalActionCallouts } from '@/utils/historicalActionCallouts'
import { getHistoricalSignalRange } from '@/api/historicalSignals'
import { useHistoricalSignalRanges } from '@/composables/useHistoricalSignalRanges'
import { actualEventsToOwnedMarkers } from '@/utils/historicalSignalMerge'
import HtdyHistoricalPanel from './HtdyHistoricalPanel.vue'
import { getHtdyReference } from '@/api/htdyReference'
import { useHtdyHistoricalReference } from '@/composables/useHtdyHistoricalReference'
import type { ReferenceTradeView } from '@/types/referenceTrading'
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
const recordingMode = ref<'historical_replay' | 'forward_observation'>('historical_replay')
const historical = useHtdyHistoricalReference(getHtdyReference)
const historySupported = computed(() => props.identity.seriesKind === 'actual_dominant' && ['15m', '30m', '60m', '1d'].includes(props.identity.frequency))
const selectedFocus = ref<string | null>(null)
const focusError = ref<string | null>(null)
let focusGeneration = 0
watch(() => [props.identity.symbol, props.identity.frequency, props.identity.seriesKind], () => {
  focusGeneration += 1; selectedFocus.value = null; focusError.value = null
  if (props.identity.frequency !== '60m') recordingMode.value = 'historical_replay'
  historical.reset(props.identity.symbol, props.identity.frequency)
  if (historySupported.value) void historical.read()
}, { immediate: true })
watch(() => props.bars.at(-1)?.time ?? null, value => { historical.latestBar.value = value }, { immediate: true })
const chartSignals = useHistoricalSignalRanges(getHistoricalSignalRange)
const realtimeEnabled = computed(() => props.identity.frequency === '60m')
const actualSignals = computed(() => realtimeEnabled.value ? actualEventsToOwnedMarkers(loader.events.value, props.bars, { symbol: props.identity.symbol, strategy: 'htdy', frequency: props.identity.frequency }) : [])
const callouts = computed(() => recordingMode.value === 'historical_replay' ? historicalActionCallouts(chartSignals.actions.value, props.bars) : [])
function focusObservation(identity: { barEnd: string; physicalContract: string }) {
  const found = props.bars.find(bar => Date.parse(bar.time) === Date.parse(identity.barEnd) && bar.physicalContract === identity.physicalContract)
  if (found) selectedFocus.value = identity.barEnd
  else focusError.value = '实际信号的精确时间与物理合约不在当前已加载范围'
}
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
const optionalEmaIndicators = computed(() => props.preferences.optionalEmaIndicators)
const showRangeDetector = computed(() => props.preferences.showRangeDetector)
const workspace = ref<HTMLElement | null>(null)
const sourceIdentity = computed(() => [props.identity.seriesKind, props.identity.symbol, props.identity.contract ?? '', props.identity.frequency].join(':'))
const visibleFrom = ref<string | null>(null)
const rangeCount = ref(0)
watch(sourceIdentity, () => { visibleFrom.value = null; rangeCount.value = 0 }, { flush: 'sync' })
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
watch([sourceIdentity, () => props.bars, () => props.mutation], (_value, previous) => { if (historySupported.value) void chartSignals.sync({ symbol: props.identity.symbol, strategy: 'htdy', frequency: props.identity.frequency }, props.bars, props.mutation.kind === 'replace' && props.mutation !== previous?.[2]) }, { immediate: true, deep: true })
watch(recordingMode, () => { focusGeneration += 1; selectedFocus.value = null; focusError.value = null })
watch(() => loader.events.value.length + (historical.result.value?.trades.length ?? 0), (value) => emit('history-availability', value > 0), { immediate: true })
onBeforeUnmount(() => { focusGeneration += 1; historical.dispose(); chartSignals.dispose(); loader.dispose() })
</script>

<template>
  <section ref="workspace" class="htdy-workspace" data-detail-workspace="htdy" :data-range-detector-status="rangeWarmup.status.value" :data-range-detector-anchor="rangeWarmup.anchorTime.value" :data-range-detector-visible-from="visibleFrom">
    <p v-if="identityWarning" class="htdy-workspace__hint" role="status">{{ identityWarning }}</p>
    <p v-if="showRangeDetector" class="htdy-workspace__hint" role="status">{{ rangeDetectorStatusText(rangeWarmup.status.value, rangeCount) }} 历史图形参考；加载更早数据可能修订箱体。</p>
    <HtdyChartStage :bars="bars" :mutation="mutation" :loading="loading" :error="error" :period="identity.frequency" :series-kind="identity.seriesKind" :visible-main-indicators="indicators" :range-detector-source-identity="sourceIdentity" :range-detector-anchor-time="rangeWarmup.anchorTime.value" :identity-key="sourceIdentity" :focus-bar-end="selectedFocus ?? identity.focusBarEnd" :has-more-before="hasMoreBefore" :loading-before="loadingBefore" :history-error="historyError" :historical-mode="recordingMode === 'historical_replay'" :reference-callouts="callouts" :markers="recordingMode === 'historical_replay' ? [] : actualSignals.map(item => item.marker)" @load-earlier="loadEarlier" @focus-resolved="emit('focus-resolved', $event)" @visible-from-change="visibleFrom = $event" @range-detector-result="rangeCount = $event.count" />
    <p v-if="!realtimeEnabled" class="htdy-workspace__source" role="status">实时信号统一记录于60分钟；当前周期保留历史研究图表。</p>
    <p class="htdy-workspace__source">正式历史图使用盘后 Canonical 重算 · 首次事件保留在实时审计｜参考交易零费用/零滑点，非账户成交</p>
    <nav class="htdy-workspace__filter" aria-label="火天大有记录模式"><button type="button" :aria-pressed="recordingMode === 'historical_replay'" @click="recordingMode = 'historical_replay'">盘后历史</button><button v-if="realtimeEnabled" type="button" :aria-pressed="recordingMode === 'forward_observation'" @click="recordingMode = 'forward_observation'">实时首次事件审计</button></nav>
    <p v-if="recordingMode === 'historical_replay' && !historySupported" role="status">此周期或序列暂不支持历史重算参考。</p>
    <p v-if="chartSignals.loading.value" class="htdy-workspace__hint" role="status">正在读取当前图表范围的历史信号…</p>
    <p v-if="chartSignals.error.value" class="htdy-workspace__hint" role="status">{{ chartSignals.error.value }} <button type="button" @click="chartSignals.sync({ symbol: identity.symbol, strategy: 'htdy', frequency: identity.frequency }, bars)">重试历史信号</button></p>
    <ObservedReferenceRecords v-if="realtimeEnabled && recordingMode === 'forward_observation'" strategy="htdy" :product="identity.symbol.toUpperCase()" :frequency="identity.frequency" :events="loader.events.value" :unavailable="loader.unavailable.value" @focus="focusObservation" />
    <HtdyHistoricalPanel v-if="recordingMode === 'historical_replay' && historySupported" :stale="historical.stale.value" :result="historical.result.value" :loading="historical.loading.value" :error="historical.error.value" :focus-error="focusError" @more="historical.read(true)" @retry="historical.read()" @window="historical.read(false, $event)" @focus="focusTrade" />

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
