<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'

import MarketDetailFactStrip from '@/components/market/detail/MarketDetailFactStrip.vue'
import MarketDetailInsightDeck from '@/components/market/detail/MarketDetailInsightDeck.vue'
import MarketDetailSectionTabs from '@/components/market/detail/MarketDetailSectionTabs.vue'
import HtdyChartStage from './HtdyChartStage.vue'
import { getAlertEvents, getAlertRuntimeStatus, getProductAlerts } from '@/api/alerts'
import { usePersistentAlertMarkers } from '@/composables/usePersistentAlertMarkers'
import { useRangeDetectorOverlayWarmup } from '@/composables/useRangeDetectorOverlayWarmup'
import type { MarketSeriesMutation } from '@/composables/useMarketSeries'
import type { BarData, OptionalEmaIndicatorId } from '@/types/market'
import type { DetailViewModel, MarketDetailHeaderModel, MarketDetailIdentity } from '@/types/marketDetail'
import type { FlexibleDetailPreferences } from '@/utils/marketDetailPreferences'
import { visibleMainIndicatorsForOverlay } from '@/utils/mainIndicators'
import { buildKlineDerivedData } from '@/utils/klineViewModel'
import { buildHtdyDetailViewModel } from '@/utils/htdyDetailViewModel'
import { ALERT_RULE_CODES, findAlertRuleByCode, isHtdyAlertEvent } from '@/utils/alertRules'

const props = defineProps<{
  identity: MarketDetailIdentity; header: MarketDetailHeaderModel; bars: BarData[]; mutation: MarketSeriesMutation
  loading: boolean; error: string | null; preferences: FlexibleDetailPreferences; hasMoreBefore: boolean
  loadEarlier: () => Promise<void>; identityWarning?: string | null
}>()
const emit = defineEmits<{ updatePreferences: [preferences: FlexibleDetailPreferences]; 'history-availability': [available: boolean]; 'focus-resolved': [focusBarEnd: string] }>()
const optionalEmaIndicators = ref<OptionalEmaIndicatorId[]>([...props.preferences.optionalEmaIndicators])
const showRangeDetector = ref(props.preferences.showRangeDetector)
const activeTab = ref<string | null>(null)
const tabs = ref<InstanceType<typeof MarketDetailSectionTabs> | null>(null)
const sourceIdentity = computed(() => [props.identity.seriesKind, props.identity.symbol, props.identity.contract ?? '', props.identity.frequency].join(':'))
const rangeWarmup = useRangeDetectorOverlayWarmup({ bars: computed(() => props.bars), hasMoreBefore: computed(() => props.hasMoreBefore), enabled: showRangeDetector, identityKey: sourceIdentity, loadMoreBefore: props.loadEarlier })
const rangeState = computed(() => !showRangeDetector.value ? 'disabled' : rangeWarmup.loading.value ? 'loading' : rangeWarmup.unavailableReason.value === null && rangeWarmup.anchorTime.value ? 'ready' : 'insufficient')
const loader = usePersistentAlertMarkers({ fetchEvents: getAlertEvents }, { resolveRuleCodes: () => [ALERT_RULE_CODES.HTDY] })
const runtime = ref<'healthy' | 'degraded' | 'unavailable'>('unavailable')
const ruleScope = ref('HTDY Rule / Scope 暂不可用')
const rawState = computed(() => {
  try {
    return { observation: buildKlineDerivedData(props.bars, ['htdy']).htdy?.markers.at(-1)?.label as '买观察' | '卖观察' | undefined, unavailable: false }
  } catch { return { observation: undefined, unavailable: true } }
})
const model = computed<DetailViewModel>(() => buildHtdyDetailViewModel({ identity: props.identity, header: props.header, rawObservation: rawState.value.observation ?? null, rawUnavailable: rawState.value.unavailable, events: loader.events.value.filter(isHtdyAlertEvent), alertUnavailable: loader.unavailable.value, runtime: runtime.value, ruleScope: ruleScope.value }))
const indicators = computed(() => visibleMainIndicatorsForOverlay('htdy', optionalEmaIndicators.value, showRangeDetector.value))

async function refresh() {
  await loader.sync(props.identity, props.bars, props.mutation.kind)
  try {
    const status = await getAlertRuntimeStatus()
    runtime.value = status === 'ok' || status === 'healthy' ? 'healthy' : status === 'disabled' ? 'unavailable' : 'degraded'
  } catch { runtime.value = 'unavailable' }
  try {
    const response = await getProductAlerts(props.identity.symbol)
    const rule = findAlertRuleByCode(response.rules, ALERT_RULE_CODES.HTDY)
    ruleScope.value = rule
      ? `${rule.display_name} (${ALERT_RULE_CODES.HTDY}) · ${props.identity.symbol.toUpperCase()} ${props.identity.frequency} · ${rule.enabled_frequencies.includes(props.identity.frequency) ? '当前 Scope 已启用' : '当前 Scope 未启用'} · 仅只读展示`
      : 'HTDY Rule / Scope 暂不可用'
  } catch { ruleScope.value = 'HTDY Rule / Scope 暂不可用' }
}
function updatePreferences() { emit('updatePreferences', { seriesKind: props.identity.seriesKind === 'continuous' ? 'continuous' : 'actual_dominant', frequency: props.identity.frequency, optionalEmaIndicators: [...optionalEmaIndicators.value], showRangeDetector: showRangeDetector.value }) }
function toggleEma(value: OptionalEmaIndicatorId) { optionalEmaIndicators.value = optionalEmaIndicators.value.includes(value) ? optionalEmaIndicators.value.filter((item) => item !== value) : [...optionalEmaIndicators.value, value] }
function openHistory() { tabs.value?.openHistory() }
defineExpose({ openHistory })
watch([() => props.identity, () => props.bars, () => props.mutation], () => { void refresh() }, { immediate: true, deep: true })
watch([optionalEmaIndicators, showRangeDetector], () => { updatePreferences(); if (!showRangeDetector.value) rangeWarmup.reset() }, { deep: true })
watch(() => model.value.history.length, (value) => emit('history-availability', value > 0), { immediate: true })
onBeforeUnmount(loader.dispose)
</script>

<template>
  <section class="htdy-workspace" data-detail-workspace="htdy">
    <div class="htdy-workspace__indicators"><details open><summary>指标设置</summary><label v-for="item in [['ema_10', 'EMA10'], ['ema_21', 'EMA21'], ['ema_60', 'EMA60']] as const" :key="item[0]"><input type="checkbox" :checked="optionalEmaIndicators.includes(item[0])" @change="toggleEma(item[0])">{{ item[1] }}</label><label><input v-model="showRangeDetector" type="checkbox">箱体识别（Range）</label></details></div>
    <p class="htdy-workspace__semantic" role="status">{{ model.semanticBanner.text }}</p>
    <MarketDetailFactStrip :facts="model.facts" />
    <p v-if="identityWarning" class="htdy-workspace__hint" role="status">{{ identityWarning }}</p>
    <HtdyChartStage :bars="bars" :mutation="mutation" :loading="loading" :error="error" :period="identity.frequency" :series-kind="identity.seriesKind" :visible-main-indicators="indicators" :range-detector-source-identity="sourceIdentity" :range-detector-anchor-time="rangeState === 'ready' ? rangeWarmup.anchorTime.value : null" :identity-key="sourceIdentity" :focus-bar-end="identity.focusBarEnd" :markers="loader.markers.value" @load-earlier="loadEarlier" @focus-resolved="emit('focus-resolved', $event)" />
    <MarketDetailSectionTabs ref="tabs" :tabs="[{ id: 'explanation', label: '信号说明' }, { id: 'alerts', label: '预警与运行' }, { id: 'data', label: '数据与历史' }]" :active-id="activeTab" :history="model.history" @select="activeTab = $event"><template #default><MarketDetailInsightDeck :identity-key="sourceIdentity" :sections="model.disclosureSections" :default-open="true" /></template></MarketDetailSectionTabs>
  </section>
</template>

<style scoped>
.htdy-workspace { display: grid; gap: var(--gy-space-4); }
.htdy-workspace__indicators, .htdy-workspace__semantic { padding: var(--gy-space-3); border: 1px solid var(--gy-border); border-radius: var(--gy-radius-md); background: var(--gy-bg-panel); }
.htdy-workspace details { display: flex; gap: 12px; flex-wrap: wrap; }.htdy-workspace summary { cursor: pointer; }.htdy-workspace label { margin-right: 8px; }
.htdy-workspace__semantic { margin: 0; color: var(--gy-status-warning); background: color-mix(in srgb, var(--gy-status-warning) 10%, transparent); }.htdy-workspace__hint { margin: 0; color: var(--gy-text-muted); font-size: var(--gy-font-size-sm); }
</style>
