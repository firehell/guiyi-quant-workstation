<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

import { matchesReferenceBar } from '@/utils/referenceCalloutLayout'
import type { KlineQualityBreak, KlineReferenceSelection } from '@/types/referenceCallout'
import type { SubingReferenceTrade } from '@/types/subingReference'
import { getSubingReference } from '@/api/subingReference'
import { useSubingReference } from '@/composables/useSubingReference'
import { subingCallouts } from '@/utils/subingReference'
import { formatBeijingInstant, formatMarketDecimal } from '@/utils/marketDisplay'
import SubingReferencePanel from './SubingReferencePanel.vue'
import ReferenceTradePanel from '@/components/market/detail/ReferenceTradePanel.vue'
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
const chartRegion = ref<HTMLElement | null>(null)
const chartBars = computed<BarData[]>(() => props.identity.frequency === '1d' && reference.data.value?.quality_chart_bars
  ? reference.data.value.quality_chart_bars.map(bar => ({
      time: bar.bar_end, trading_day: bar.trading_day, physicalContract: bar.physical_contract,
      calculationSegmentId: bar.calculation_segment_id,
      open: Number(bar.open), high: Number(bar.high), low: Number(bar.low), close: Number(bar.close), volume: Number(bar.volume),
      ...(bar.turnover === null ? {} : { turnover: Number(bar.turnover) }),
      ...(bar.open_interest === null ? {} : { openInterest: Number(bar.open_interest) }),
    }))
  : props.bars)
const chartMutation = computed<MarketSeriesMutation>(() => props.identity.frequency === '1d' ? { kind: 'replace' } : props.mutation)
const qualityBreaks = computed<KlineQualityBreak[]>(() => (reference.data.value?.quality_interruptions ?? []).map(item => ({
  id: `subing-d1-quality:${item.physical_contract}:${item.bar_end}:${item.classification_version}`,
  time: item.bar_end,
  label: item.classification === 'PRICE_UNAVAILABLE' ? '缺价' : '非正收盘',
  detail: `${item.physical_contract} · ${item.trading_day} · ${item.classification}`,
})))
async function focusTrade(trade: SubingReferenceTrade) {
  const intent = ++focusIntent
  referenceSelection.value = []
  const key = identityKey.value
  const snapshotHash = reference.data.value?.input_snapshot_hash
  const current = () => intent === focusIntent && key === identityKey.value && snapshotHash === reference.data.value?.input_snapshot_hash
  const target = trade.exit_bar_end ?? trade.entry_bar_end
  referenceFocus.value = null
  const matches = (bar: BarData) => matchesReferenceBar({ time: target, physicalContract: trade.physical_contract }, bar)
  referenceFocusNotice.value = null
  while (current() && !chartBars.value.some(matches) && props.identity.frequency !== '1d' && props.hasMoreBefore && Date.parse(target) < Date.parse(chartBars.value[0]?.time ?? target)) {
    const first = chartBars.value[0]?.time
    await props.loadEarlier(); await nextTick()
    if (first === chartBars.value[0]?.time) break
  }
  if (current() && chartBars.value.some(matches)) {
    referenceFocus.value = target
    referenceFocusRequestId.value += 1
    referenceSelection.value = [trade.entry_bar_end, trade.exit_bar_end].flatMap(time => time ? [{ time, physicalContract: trade.physical_contract }] : [])
    await nextTick()
    chartRegion.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
  if (current() && !chartBars.value.some(matches)) referenceFocusNotice.value = '此参考 Bar 不在当前可读图表范围内；记录详情仍可查看。'
}
const missingCalloutCount = computed(() => callouts.value.filter(callout => !chartBars.value.some(bar => matchesReferenceBar(callout, bar))).length)
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
  if (identity.frequency === '15m') await Promise.all([loader.sync(identity, props.bars, props.mutation.kind), alertFacts.refresh({ symbol: identity.symbol, frequency: '15m' })])
  else await loader.sync(identity, [], 'replace')
}
function openHistory() { tabs.value?.openHistory() }
function loadEarlierChart() { if (props.identity.frequency !== '1d') void props.loadEarlier() }
defineExpose({ openHistory })
watch([() => props.identity, () => props.bars, () => props.mutation], () => { void refresh() }, { immediate: true, deep: true })
watch(() => model.value.history.length, (value) => emit('history-availability', value > 0), { immediate: true })
watch(() => reference.data.value?.input_snapshot_hash, () => { focusIntent += 1; referenceSelection.value = []; selectedTrade.value = null; referenceFocus.value = null; referenceFocusNotice.value = null }, { flush: 'sync' })
watch(identityKey, () => { focusIntent += 1; referenceSelection.value = []; selectedTrade.value = null; selectedEvent.value = null; referenceFocusNotice.value = null; referenceFocus.value = null; void reference.refresh(props.identity.symbol, { frequency: props.identity.frequency as '15m' | '30m' | '60m' | '1d' }) }, { immediate: true })
onBeforeUnmount(() => { loader.dispose(); alertFacts.dispose(); reference.dispose() })
</script>

<template>
  <section class="subing-workspace" data-detail-workspace="subing">
    <p v-if="identityWarning" class="subing-workspace__hint" role="status">{{ identityWarning }}</p>
    <div ref="chartRegion" class="subing-workspace__chart"><SubingChartStage :bars="chartBars" :mutation="chartMutation" :loading="identity.frequency === '1d' ? reference.loading.value : loading" :error="identity.frequency === '1d' ? reference.error.value : error" :period="identity.frequency" :series-kind="identity.seriesKind" :identity-key="identityKey" :focus-bar-end="referenceFocus ?? focusBarEnd ?? identity.focusBarEnd" :reference-callouts="callouts" :reference-indicators="reference.data.value?.indicators ?? []" :quality-breaks="qualityBreaks" :focus-request-id="referenceFocusRequestId" :reference-selection="referenceSelection" :markers="identity.frequency === '15m' ? loader.markers.value : []" :visible-main-indicators="['ema_21']" @load-earlier="loadEarlierChart" @focus-resolved="emit('focus-resolved', $event)" /></div>
    <p v-if="missingCalloutCount" class="subing-workspace__hint" role="status">{{ missingCalloutCount }} 个历史参考信号尚未匹配当前已载 Bar 与物理合约；可在参考记录中点击定位，数据不足时不绘制。</p>
    <p class="subing-workspace__reference-source">{{ reference.data.value?.storage_mode === 'persisted' ? '历史参考·已保存' : '历史重算·乐观参考' }}｜零费用/零滑点 <span>白底标注 · 实际预警为 S↑ / S↓</span></p>
    <p v-if="identity.frequency !== '15m'" class="subing-workspace__hint" role="status">历史研究，本周期未启用预警；正式 S↑ / S↓ 仅在 15分周期。</p>
    <SubingReferencePanel :data="reference.data.value" :loading="reference.loading.value" :error="reference.error.value" @refresh="reference.refresh(identity.symbol, { ...$event, frequency: identity.frequency as '15m' | '30m' | '60m' | '1d' })" @load-more="reference.loadMore" @focus="focusTrade" @details="selectedTrade = $event" />
    <ReferenceTradePanel strategy="subing-reference" :product="identity.symbol" :frequency="identity.frequency" :through="bars.at(-1)?.trading_day" />
    <p v-if="referenceFocusNotice" role="status">{{ referenceFocusNotice }}</p>
    <MarketDetailDrawer :open="selectedTrade !== null" title="历史参考记录详情" @close="selectedTrade = null"><template v-if="selectedTrade"><p>{{ selectedTrade.side === 'LONG' ? '多头参考' : '空头参考' }} · {{ selectedTrade.status === 'CLOSED' ? '已平参考' : selectedTrade.status === 'OPEN' ? '未平参考' : selectedTrade.status === 'DATA_INTERRUPTED' ? '数据中断' : '换月中断' }} · {{ selectedTrade.physical_contract }}</p><p>开仓参考 {{ formatMarketDecimal(selectedTrade.entry_reference_price) }} · {{ formatBeijingInstant(selectedTrade.entry_bar_end) }}</p><p>平仓参考 {{ formatMarketDecimal(selectedTrade.exit_reference_price) }} · {{ selectedTrade.exit_bar_end ? formatBeijingInstant(selectedTrade.exit_bar_end) : selectedTrade.status === 'DATA_INTERRUPTED' ? `数据中断（${selectedTrade.interruption_reason}），未配对平仓` : selectedTrade.status === 'ROLLOVER_INTERRUPTED' ? '换月中断，未配对平仓' : '尚无配对平仓' }}</p><p>持有 {{ selectedTrade.holding_bars }} 根 Bar · {{ selectedTrade.initial ? '窗口初始记录' : '窗口内新开参考' }}</p><p>{{ reference.data.value?.storage_mode === 'persisted' ? '历史参考·已保存' : '历史重算·乐观参考' }}｜零费用/零滑点</p><p>{{ selectedTrade.reference_trade_id }}</p></template></MarketDetailDrawer>
    <p v-if="identity.frequency === '15m'" class="subing-workspace__hint">实际预警记录 · 以下仅为已持久化 AlertEvent，与历史重算信号独立；同一 Bar 可以同时存在。</p>
    <MarketDetailSectionTabs v-if="identity.frequency === '15m'" ref="tabs" :tabs="[]" :active-id="activeTab" :history="model.history" history-selectable @select="activeTab = $event" @history-select="selectedEvent = Number($event.id.replace('subing-event:', ''))">
      <template #default><MarketDetailInsightDeck :identity-key="identityKey" :sections="model.disclosureSections" :default-open="true" /></template>
    </MarketDetailSectionTabs>
    <MarketDetailDrawer :open="selectedHistory !== null" title="苏冰预警详情" @close="selectedEvent = null">
      <p v-if="selectedHistory">{{ selectedHistory.label }} · {{ formatBeijingInstant(selectedHistory.barEnd) }} · {{ selectedHistory.contract }}</p>
    </MarketDetailDrawer>
  </section>
</template>

<style scoped>
.subing-workspace { display: grid; gap: var(--gy-space-4); }
.subing-workspace__semantic { margin: 0; padding: var(--gy-space-3); border: 1px solid var(--gy-border); border-radius: var(--gy-radius-md); color: var(--gy-text-primary); background: var(--gy-bg-panel); }
.subing-workspace__reference-source { margin: 0; padding: 8px 12px; border-left: 2px solid #aa927b; background: #fffefa; color: #665343; font-size: 12px; } .subing-workspace__reference-source span { margin-left: 12px; color: #8c8174; }
.subing-workspace__hint { margin: 0; color: var(--gy-text-muted); font-size: var(--gy-font-size-sm); }
</style>
