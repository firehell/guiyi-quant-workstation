<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'

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
onBeforeUnmount(() => { loader.dispose(); alertFacts.dispose() })
</script>

<template>
  <section class="subing-workspace" data-detail-workspace="subing">
    <p class="subing-workspace__semantic" role="status">{{ model.semanticBanner.text }}</p>
    <MarketDetailFactStrip :facts="model.facts" />
    <p v-if="identityWarning" class="subing-workspace__hint" role="status">{{ identityWarning }}</p>
    <SubingChartStage :bars="bars" :mutation="mutation" :loading="loading" :error="error" period="15m" :series-kind="identity.seriesKind" :identity-key="identityKey" :focus-bar-end="focusBarEnd ?? identity.focusBarEnd" :markers="loader.markers.value" :visible-main-indicators="['ema_21']" @load-earlier="loadEarlier" @focus-resolved="emit('focus-resolved', $event)" @marker-select="selectMarker" />
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
.subing-workspace__hint { margin: 0; color: var(--gy-text-muted); font-size: var(--gy-font-size-sm); }
</style>
