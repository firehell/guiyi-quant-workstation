<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

import { referencePanelSupported } from '@/utils/referencePanelPeriods'
import { retainedReferenceFocus } from '@/utils/retainedReferenceFocus'
import ObservedReferenceRecords from '@/components/market/detail/ObservedReferenceRecords.vue'
import { actualEventsToOwnedMarkers } from '@/utils/historicalSignalMerge'
import { formatBeijingInstant } from '@/utils/marketDisplay'
import MarketDetailDrawer from '@/components/market/detail/MarketDetailDrawer.vue'
import MarketDetailInsightDeck from '@/components/market/detail/MarketDetailInsightDeck.vue'
import MarketDetailSectionTabs from '@/components/market/detail/MarketDetailSectionTabs.vue'
import { getAlertEvents, getProductAlerts } from '@/api/alerts'
import { getRuntimeHealth } from '@/api/runtime'
import { usePersistentAlertMarkers } from '@/composables/usePersistentAlertMarkers'
import { useSubingAlertFacts } from '@/composables/useSubingAlertFacts'
import type { MarketSeriesMutation } from '@/composables/useMarketSeries'
import type { BarData } from '@/types/market'
import type { MarketDetailHeaderModel, MarketDetailIdentity } from '@/types/marketDetail'
import { ALERT_RULE_CODES, isSubingThsAlertEvent } from '@/utils/alertRules'
import { buildSubingDetailViewModel } from '@/utils/subingDetailViewModel'
import SubingChartStage from './SubingChartStage.vue'

const props = defineProps<{
  identity: MarketDetailIdentity; header: MarketDetailHeaderModel; bars: BarData[]; mutation: MarketSeriesMutation
  loading: boolean; error: string | null; hasMoreBefore: boolean; loadingBefore?: boolean; historyError?: string | null; loadEarlier: () => Promise<void>; identityWarning?: string | null; focusBarEnd?: string | null
}>()
const emit = defineEmits<{ 'history-availability': [available: boolean]; 'focus-resolved': [focusBarEnd: string] }>()
let focusGeneration = 0
const referenceFocus = ref<string | null>(null)
const referenceFocusRequestId = ref(0)
const referenceFocusNotice = ref<string | null>(null)
const chartRegion = ref<HTMLElement | null>(null)
const actualSignals = computed(() => actualEventsToOwnedMarkers(visibleEvents.value, props.bars, { symbol: props.identity.symbol, strategy: 'subing', frequency: props.identity.frequency }))
const selectedEvent = ref<number | null>(null)
const alignmentFilter = ref<'all' | 'aligned'>('all')
const visibleEvents = computed(() => loader.events.value.filter(isSubingThsAlertEvent).filter(event => alignmentFilter.value === 'all' || event.subing_alignment?.status === 'PASS'))
const visibleMarkers = computed(() => actualSignals.value.map(item => item.marker))
const selectedEventRecord = computed(() => visibleEvents.value.find(event => event.id === selectedEvent.value) ?? null)
function alignmentLabel(status: string | undefined) { return status === 'PASS' ? '六周期同向' : status === 'FAIL' ? '未全部同向' : status === 'UNKNOWN' ? '无法判断' : '未记录' }

const activeTab = ref<string | null>(null)
const loader = usePersistentAlertMarkers({ fetchEvents: getAlertEvents }, { resolveRuleCodes: () => [ALERT_RULE_CODES.SUBING_THS] })
const alertFacts = useSubingAlertFacts({ fetchRuntime: getRuntimeHealth, fetchProductAlerts: getProductAlerts })
const identityKey = computed(() => [props.identity.seriesKind, props.identity.symbol, props.identity.contract ?? '', props.identity.frequency].join(':'))
const model = computed(() => buildSubingDetailViewModel({
  identity: props.identity, header: props.header, events: visibleEvents.value, alertUnavailable: loader.unavailable.value,
  rule: alertFacts.rule.value, ruleUnavailable: alertFacts.ruleUnavailable.value, runtime: alertFacts.runtime.value, runtimeUnavailable: alertFacts.runtimeUnavailable.value,
}))
const selectedHistory = computed(() => model.value.history.find((item) => item.id === `subing-event:${selectedEvent.value}`) ?? null)

async function refresh() {
  const identity = { ...props.identity }
  await Promise.all([loader.sync(identity, props.bars, props.mutation.kind), alertFacts.refresh({ symbol: identity.symbol, frequency: identity.frequency })])
}
async function openHistory() { await nextTick(); chartRegion.value?.parentElement?.querySelector('.forward-reference')?.scrollIntoView({ block: 'start', behavior: 'smooth' }) }
async function focusObservation(identity: { barEnd: string; physicalContract: string }) {
  const own = ++focusGeneration, key = identityKey.value
  const current = () => own === focusGeneration && key === identityKey.value
  referenceFocusNotice.value = null
  try {
    const found = await retainedReferenceFocus(identity, { bars: () => props.bars, hasMore: () => props.hasMoreBefore, loadEarlier: props.loadEarlier, current })
    if (!current()) return
    if (found) { referenceFocus.value = identity.barEnd; referenceFocusRequestId.value += 1; chartRegion.value?.scrollIntoView({ block: 'start', behavior: 'smooth' }) }
    else referenceFocusNotice.value = '未找到该物理合约对应的精确历史K线，请核对数据范围'
  } catch { if (current()) referenceFocusNotice.value = '历史行情读取失败，请重试定位。' }
}
function loadEarlierChart() { void props.loadEarlier().catch(() => { referenceFocusNotice.value = '历史行情加载失败，可重试。' }) }
defineExpose({ openHistory })
watch([() => props.identity, () => props.bars, () => props.mutation], () => { void refresh() }, { immediate: true, deep: true })
watch(() => model.value.history.length, (value) => emit('history-availability', value > 0), { immediate: true })
watch(identityKey, () => { focusGeneration++; referenceFocus.value = null; referenceFocusNotice.value = null; selectedEvent.value = null }, { flush: 'sync' })
onBeforeUnmount(() => { focusGeneration++; loader.dispose(); alertFacts.dispose() })
</script>

<template>
  <section class="subing-workspace" data-detail-workspace="subing">
    <p v-if="identityWarning" class="subing-workspace__hint" role="status">{{ identityWarning }}</p>
    <div ref="chartRegion" class="subing-workspace__chart"><div id="detail-chart-reference-toolbar" /><SubingChartStage :allow-historical-markers="false" :bars="bars" :mutation="mutation" :loading="loading" :error="error" :has-more-before="hasMoreBefore" :loading-before="loadingBefore" :history-error="historyError" :period="identity.frequency" :series-kind="identity.seriesKind" :identity-key="identityKey" :focus-bar-end="referenceFocus ?? focusBarEnd ?? identity.focusBarEnd" :reference-callouts="[]" :reference-indicators="[]" :quality-breaks="[]" :focus-request-id="referenceFocusRequestId" :reference-selection="[]" :markers="visibleMarkers" :visible-main-indicators="['ema_21']" @load-earlier="loadEarlierChart" @focus-resolved="emit('focus-resolved', $event)" /></div>
    <p v-if="referencePanelSupported('subing-reference', identity.frequency, identity.seriesKind)" class="subing-workspace__reference-source">实时留存参考交易｜首次记录，不以盘后重算补齐；零费用／零滑点，非账户成交</p>
    <ObservedReferenceRecords strategy="subing-reference" :product="identity.symbol.toUpperCase()" :frequency="identity.frequency" :series-kind="identity.seriesKind" :through="bars.at(-1)?.trading_day" :events="visibleEvents" :unavailable="loader.unavailable.value" @focus="focusObservation" />
    <p v-if="referenceFocusNotice" role="status">{{ referenceFocusNotice }}</p>
    <MarketDetailSectionTabs :tabs="[]" :active-id="activeTab" :history="model.history" history-selectable @select="activeTab = $event" @history-select="selectedEvent = Number($event.id.replace('subing-event:', ''))">
      <template #default><MarketDetailInsightDeck :identity-key="identityKey" :sections="model.disclosureSections" :default-open="true" /></template>
    </MarketDetailSectionTabs>
    <MarketDetailDrawer :open="selectedHistory !== null" title="苏冰预警详情" @close="selectedEvent = null">
      <p v-if="selectedHistory">{{ selectedHistory.label }} · {{ formatBeijingInstant(selectedHistory.barEnd) }} · {{ selectedHistory.contract }}</p>
    <template v-if="selectedEventRecord"><p>{{ alignmentLabel(selectedEventRecord.subing_alignment?.status) }}</p><template v-if="selectedEventRecord.subing_alignment"><p>快照 {{ formatBeijingInstant(selectedEventRecord.subing_alignment.as_of) }} · {{ selectedEventRecord.subing_alignment.policy_version }}</p><div class="subing-workspace__snapshot"><table><thead><tr><th>周期</th><th>合约 / 已完成 Bar</th><th>收盘价</th><th>EMA21</th><th>方向</th></tr></thead><tbody><tr v-for="period in selectedEventRecord.subing_alignment.periods" :key="period.frequency"><td>{{ period.frequency }}</td><td>{{ period.contract }} · {{ formatBeijingInstant(period.bar_end) }}</td><td>{{ period.close ?? '—' }}</td><td>{{ period.ema21 ?? '—' }}</td><td>{{ period.direction === 'LONG' ? '均线上方' : period.direction === 'SHORT' ? '均线下方' : period.direction === 'FLAT' ? '等于均线' : '无法判断' }}{{ period.reason ? ` · ${period.reason}` : '' }}</td></tr></tbody></table></div></template></template></MarketDetailDrawer>
  </section>
</template>

<style scoped>
.subing-workspace__references { display: grid; gap: var(--gy-space-3); min-width: 0; }
.subing-workspace__filter { flex-wrap: wrap; display: flex; gap: var(--gy-space-2); }
.subing-workspace__filter button { padding: 8px 12px; border: 1px solid var(--gy-border); border-radius: var(--gy-radius-md); color: var(--gy-text-primary); background: var(--gy-bg-panel); cursor: pointer; }
.subing-workspace__filter button[aria-pressed="true"] { border-color: var(--gy-accent); background: var(--gy-detail-accent-soft); }
.subing-workspace__snapshot { overflow-x: auto; }
.subing-workspace__snapshot table { width: 100%; border-collapse: collapse; font-size: var(--gy-font-size-sm); }
.subing-workspace__snapshot th, .subing-workspace__snapshot td { padding: 8px; text-align: left; border-bottom: 1px solid var(--gy-border); }
.subing-workspace { display: grid; gap: var(--gy-space-4); }
.subing-workspace__semantic { margin: 0; padding: var(--gy-space-3); border: 1px solid var(--gy-border); border-radius: var(--gy-radius-md); color: var(--gy-text-primary); background: var(--gy-bg-panel); }
.subing-workspace__reference-source { margin: 0; padding: 8px 12px; border-left: 2px solid var(--gy-accent); background: var(--gy-accent-soft); color: var(--gy-text-secondary); font-size: 12px; } .subing-workspace__reference-source span { margin-left: 12px; color: var(--gy-text-muted); }
.subing-workspace__hint { margin: 0; color: var(--gy-text-muted); font-size: var(--gy-font-size-sm); }
</style>
