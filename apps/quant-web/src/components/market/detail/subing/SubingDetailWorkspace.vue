<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

import { matchesReferenceBar } from '@/utils/referenceCalloutLayout'
import type { KlineReferenceSelection } from '@/types/referenceCallout'
import type { SubingReferenceTrade } from '@/types/subingReference'
import { getSubingReference } from '@/api/subingReference'
import { useSubingReference } from '@/composables/useSubingReference'
import { subingCallouts, subingActionLabel } from '@/utils/subingReference'
import SubingReferencePanel from './SubingReferencePanel.vue'
import MarketDetailDrawer from '@/components/market/detail/MarketDetailDrawer.vue'
import MarketDetailFactStrip from '@/components/market/detail/MarketDetailFactStrip.vue'
import MarketDetailInsightDeck from '@/components/market/detail/MarketDetailInsightDeck.vue'
import MarketDetailSectionTabs from '@/components/market/detail/MarketDetailSectionTabs.vue'
import { getAlertEvents, getProductAlerts } from '@/api/alerts'
import { getRuntimeHealth } from '@/api/runtime'
import { usePersistentAlertMarkers } from '@/composables/usePersistentAlertMarkers'
import { useSubingAlertFacts } from '@/composables/useSubingAlertFacts'
import type { MarketSeriesMutation } from '@/composables/useMarketSeries'
import type { BarData, KlineMarker } from '@/types/market'
import type { MarketDetailHeaderModel, MarketDetailIdentity } from '@/types/marketDetail'
import { ALERT_RULE_CODES, alertEventIdentityKey, isSubingThsAlertEvent } from '@/utils/alertRules'
import { buildSubingDetailViewModel } from '@/utils/subingDetailViewModel'
import SubingChartStage from './SubingChartStage.vue'

const props = defineProps<{
  identity: MarketDetailIdentity; header: MarketDetailHeaderModel; bars: BarData[]; mutation: MarketSeriesMutation
  loading: boolean; error: string | null; hasMoreBefore: boolean; loadEarlier: () => Promise<void>; identityWarning?: string | null; focusBarEnd?: string | null
}>()
const emit = defineEmits<{ 'history-availability': [available: boolean]; 'focus-resolved': [focusBarEnd: string] }>()
const tabs = ref<InstanceType<typeof MarketDetailSectionTabs> | null>(null)
const reference = useSubingReference(getSubingReference)
const referenceFocus = ref<string | null>(null)
const referenceFocusRequestId = ref(0)
const referenceSelection = ref<KlineReferenceSelection[]>([])
let focusIntent = 0
const referenceFocusNotice = ref<string | null>(null)
const selectedTrade = ref<SubingReferenceTrade | null>(null)
const colocatedEvents = computed(() => selectedSignal.value ? loader.events.value.filter(event => isSubingThsAlertEvent(event) && Date.parse(event.bar_end) === Date.parse(selectedSignal.value!.bar_end) && event.contract === selectedSignal.value!.physical_contract) : [])
async function focusTrade(trade: SubingReferenceTrade) {
  selectedTrade.value = trade
  const intent = ++focusIntent
  referenceSelection.value = []
  const key = identityKey.value
  const snapshotHash = reference.data.value?.input_snapshot_hash
  const current = () => intent === focusIntent && key === identityKey.value && snapshotHash === reference.data.value?.input_snapshot_hash && selectedTrade.value?.reference_trade_id === trade.reference_trade_id
  const target = trade.exit_bar_end ?? trade.entry_bar_end
  referenceFocus.value = null
  const matches = (bar: BarData) => matchesReferenceBar({ time: target, physicalContract: trade.physical_contract }, bar)
  referenceFocusNotice.value = null
  while (current() && !props.bars.some(matches) && props.hasMoreBefore && Date.parse(target) < Date.parse(props.bars[0]?.time ?? target)) {
    const first = props.bars[0]?.time
    await props.loadEarlier(); await nextTick()
    if (first === props.bars[0]?.time) break
  }
  if (current() && props.bars.some(matches)) {
    referenceFocus.value = target
    referenceFocusRequestId.value += 1
    referenceSelection.value = [trade.entry_bar_end, trade.exit_bar_end].flatMap(time => time ? [{ time, physicalContract: trade.physical_contract }] : [])
  }
  if (current() && !props.bars.some(matches)) referenceFocusNotice.value = '此参考 Bar 不在当前可读图表范围内；记录详情仍可查看。'
}
const selectedSignalId = ref<string | null>(null)
const selectedSignal = computed(() => reference.data.value?.signals.find(item => item.signal_id === selectedSignalId.value) ?? null)
const missingCalloutCount = computed(() => callouts.value.filter(callout => !props.bars.some(bar => matchesReferenceBar(callout, bar))).length)
const callouts = computed(() => subingCallouts(reference.data.value?.signals ?? []))
const selectedEvent = ref<number | null>(null)
const activeTab = ref<string | null>(null)
const loader = usePersistentAlertMarkers({ fetchEvents: getAlertEvents }, { resolveRuleCodes: () => [ALERT_RULE_CODES.SUBING_THS] })
const alertFacts = useSubingAlertFacts({ fetchRuntime: getRuntimeHealth, fetchProductAlerts: getProductAlerts })
const identityKey = computed(() => [props.identity.seriesKind, props.identity.symbol, props.identity.contract ?? '', props.identity.frequency].join(':'))
const model = computed(() => buildSubingDetailViewModel({
  identity: props.identity, header: props.header, events: loader.events.value.filter(isSubingThsAlertEvent), alertUnavailable: loader.unavailable.value,
  rule: alertFacts.rule.value, ruleUnavailable: alertFacts.ruleUnavailable.value, runtime: alertFacts.runtime.value, runtimeUnavailable: alertFacts.runtimeUnavailable.value,
}))
const selectedHistory = computed(() => model.value.history.find((item) => item.id === `subing-event:${selectedEvent.value}`) ?? null)

async function refresh() {
  const identity = { ...props.identity }
  await Promise.all([loader.sync(identity, props.bars, props.mutation.kind), alertFacts.refresh({ symbol: identity.symbol, frequency: '15m' })])
}
function openHistory() { tabs.value?.openHistory() }
function selectMarker(marker: KlineMarker) { selectedEvent.value = loader.events.value.find((event) => isSubingThsAlertEvent(event) && marker.id === `alert:${alertEventIdentityKey(event)}`)?.id ?? null }
defineExpose({ openHistory })
watch([() => props.identity, () => props.bars, () => props.mutation], () => { void refresh() }, { immediate: true, deep: true })
watch(() => model.value.history.length, (value) => emit('history-availability', value > 0), { immediate: true })
watch(() => reference.data.value?.input_snapshot_hash, () => { focusIntent += 1; referenceSelection.value = []; selectedTrade.value = null; selectedSignalId.value = null; referenceFocus.value = null; referenceFocusNotice.value = null }, { flush: 'sync' })
watch(identityKey, () => { focusIntent += 1; referenceSelection.value = []; selectedTrade.value = null; referenceFocusNotice.value = null; referenceFocus.value = null; selectedSignalId.value = null; void reference.refresh(props.identity.symbol) }, { immediate: true })
onBeforeUnmount(() => { loader.dispose(); alertFacts.dispose(); reference.dispose() })
</script>

<template>
  <section class="subing-workspace" data-detail-workspace="subing">
    <p class="subing-workspace__semantic" role="status">{{ model.semanticBanner.text }}</p>
    <MarketDetailFactStrip :facts="model.facts" />
    <p v-if="identityWarning" class="subing-workspace__hint" role="status">{{ identityWarning }}</p>
    <p v-if="missingCalloutCount" class="subing-workspace__hint" role="status">{{ missingCalloutCount }} 个历史参考信号尚未匹配当前已载 Bar 与物理合约；可在参考记录中点击定位，数据不足时不绘制。</p>
    <p class="subing-workspace__reference-source">历史重算·乐观参考｜零费用/零滑点 <span>白底标注 · 实际预警为 S↑ / S↓</span></p>
    <SubingChartStage :bars="bars" :mutation="mutation" :loading="loading" :error="error" period="15m" :series-kind="identity.seriesKind" :identity-key="identityKey" :focus-bar-end="referenceFocus ?? focusBarEnd ?? identity.focusBarEnd" :reference-callouts="callouts" :focus-request-id="referenceFocusRequestId" :reference-selection="referenceSelection" @reference-select="selectedSignalId = $event" :markers="loader.markers.value" :visible-main-indicators="['ema_21']" @load-earlier="loadEarlier" @focus-resolved="emit('focus-resolved', $event)" @marker-select="selectMarker" />
    <SubingReferencePanel :data="reference.data.value" :loading="reference.loading.value" :error="reference.error.value" @refresh="reference.refresh(identity.symbol, $event)" @load-more="reference.loadMore" @focus="focusTrade" />
    <p v-if="referenceFocusNotice" role="status">{{ referenceFocusNotice }}</p>
    <MarketDetailDrawer :open="selectedTrade !== null" title="历史参考记录详情" @close="selectedTrade = null"><template v-if="selectedTrade"><p>{{ selectedTrade.side === 'LONG' ? '多头参考' : '空头参考' }} · {{ selectedTrade.status }} · {{ selectedTrade.physical_contract }}</p><p>开仓参考 {{ selectedTrade.entry_reference_price }} · {{ selectedTrade.entry_bar_end }}</p><p>平仓参考 {{ selectedTrade.exit_reference_price ?? '—' }} · {{ selectedTrade.exit_bar_end ?? '尚无配对平仓' }}</p><p>持有 {{ selectedTrade.holding_bars }} 根 Bar · {{ selectedTrade.initial ? '窗口初始记录' : '窗口内新开参考' }}</p><p>历史重算·乐观参考｜零费用/零滑点</p><p>{{ selectedTrade.reference_trade_id }}</p></template></MarketDetailDrawer>
    <p class="subing-workspace__hint">实际预警记录 · 以下仅为已持久化 AlertEvent，与历史重算信号独立；同一 Bar 可以同时存在。</p>
    <MarketDetailDrawer :open="selectedSignal !== null" title="历史重算参考信号" @close="selectedSignalId = null">
      <template v-if="selectedSignal"><p>{{ subingActionLabel(selectedSignal.action) }} · 参考价 {{ selectedSignal.reference_price }}</p><p>{{ selectedSignal.bar_end }} · {{ selectedSignal.physical_contract }}</p><p v-if="selectedSignal.closed_return_pct !== null">本笔平仓参考收益 {{ selectedSignal.closed_return_pct }}%</p><p>历史重算·乐观参考｜零费用/零滑点 · 非实际预警 Event</p><p>信号 {{ selectedSignal.signal_id }}</p><p v-if="colocatedEvents.length">同 Bar 实际预警：<button v-for="event in colocatedEvents" :key="event.id" type="button" @click="selectedEvent = event.id; selectedSignalId = null">查看 AlertEvent #{{ event.id }}</button></p><p v-else>当前已读取窗口未发现同 Bar 实际预警记录。</p></template>
    </MarketDetailDrawer>
    <MarketDetailSectionTabs ref="tabs" :tabs="[]" :active-id="activeTab" :history="model.history" history-selectable @select="activeTab = $event" @history-select="selectedEvent = Number($event.id.replace('subing-event:', ''))">
      <template #default><MarketDetailInsightDeck :identity-key="identityKey" :sections="model.disclosureSections" :default-open="true" /></template>
    </MarketDetailSectionTabs>
    <MarketDetailDrawer :open="selectedHistory !== null" title="苏冰预警详情" @close="selectedEvent = null">
      <p v-if="selectedHistory">{{ selectedHistory.label }} · {{ selectedHistory.barEnd }} · {{ selectedHistory.contract }}</p>
    </MarketDetailDrawer>
  </section>
</template>

<style scoped>
.subing-workspace { display: grid; gap: var(--gy-space-4); }
.subing-workspace__semantic { margin: 0; padding: var(--gy-space-3); border: 1px solid var(--gy-border); border-radius: var(--gy-radius-md); color: var(--gy-text-primary); background: var(--gy-bg-panel); }
.subing-workspace__reference-source { margin: 0; padding: 8px 12px; border-left: 2px solid #aa927b; background: #fffefa; color: #665343; font-size: 12px; } .subing-workspace__reference-source span { margin-left: 12px; color: #8c8174; }
.subing-workspace__hint { margin: 0; color: var(--gy-text-muted); font-size: var(--gy-font-size-sm); }
</style>
