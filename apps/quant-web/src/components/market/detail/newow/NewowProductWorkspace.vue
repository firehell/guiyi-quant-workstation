<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { readNewowUiPreferences, rememberNewowUiPreferences } from '@/utils/newowUiPreferences'
import { newowUiStateLabel } from '@/utils/newowUiState'
import { useNewowComparison } from '@/composables/useNewowComparison'
import { useNewowProduct } from '@/composables/useNewowProduct'
import type { MarketDetailIdentity } from '@/types/marketDetail'
import type { NewowAuxiliaryComponent, NewowProductAction, NewowProductCapabilities, NewowProductSection, NewowProductStrategy, NewowResourceLifecycle, NewowProductSectionResponse, NewowReferenceTrade } from '@/types/newowProduct'
import { resolveNewowReferenceLocate } from '@/utils/newowProductViewModel'
import { describeNewowState, projectNewowAuxiliaryReadiness, projectNewowDetail, newowDisplayLabel, shortNewowTime, referencePercentDisplay } from '@/utils/newowDetailPresentation'
import { buildNewowProductChartModel, buildNewowAuxiliaryDisclosure, describeNewowProductAction, newowChartSnapshotKey, newowInitialClearLabel } from './newowProductChartPrimitives'
import { formatChartTimeInShanghai } from '@/utils/barTime'
import { newowErrorDisplay } from '@/utils/newowDataDiagnostics'
import { formatMarketDecimal } from '@/utils/marketDisplay'
import NewowProductChartStage from './NewowProductChartStage.vue'
import { NEWOW_ZHAOYAO_MIRROR_LEGEND } from './newowZhaoyaoMirrorPrimitive'
import { NEWOW_UP_DOWN_ENERGY_STYLE } from './newowUpDownEnergyPrimitive'
import { NEWOW_MAIN_FORCE_STYLE } from './newowMainForceControlPrimitive'
import { NEWOW_TREND_REVERSAL_STYLE } from './newowTrendReversalPrimitive'
import NewowExplanationPanel from './NewowExplanationPanel.vue'
import NewowReferencePanel from './NewowReferencePanel.vue'
import ReferenceTradePanel from '@/components/market/detail/ReferenceTradePanel.vue'
import NewowFormulaHelp from './NewowFormulaHelp.vue'
import NewowDetailDialog from './NewowDetailDialog.vue'
import NewowCupFactsPanel from './NewowCupFactsPanel.vue'
import MarketDetailUnavailable from '@/components/market/detail/MarketDetailUnavailable.vue'
const props = defineProps<{ identity: MarketDetailIdentity; capabilities: NewowProductCapabilities }>()
const emit = defineEmits<{ 'focus-resolved': [barEnd: string]; 'snapshot-mode': [asOf: string | null]; 'daily-snapshot-as-of': [asOf: string | null]; 'daily-snapshot-pending': [pending: boolean]; 'weekly-quote-context': [context: { asOf: string | null; physicalContract: string | null }]; 'refresh-current': [] }>()
const identity = computed(() => props.identity)
const identityKey = computed(() => [props.identity.view, props.identity.symbol, props.identity.strategy, props.identity.frequency].join(':'))
const selectedStrategy = computed(() => props.identity.strategy as NewowProductStrategy)
const loader = useNewowProduct({ identity })
const comparisonEnabled = ref(false)
const comparisonSelection = shallowRef<{ strategy: 'trend' | 'oscillation'; signalId: string } | null>(null)
const selectedSignalId = ref<string | null>(null)
const selectedHintId = ref<string | null>(null)
const selectedAuxiliary = ref<NewowAuxiliaryComponent>(readNewowUiPreferences(identityKey.value).auxiliary ?? 'macd')
const dialogKind = ref<'explanation' | 'action' | 'hint' | 'indicator' | 'comparator' | 'cup_handle' | 'formula' | null>(null)
const locateMessage = ref<string | null>(null)
const locateRequest = ref(0)
const chartFocusRequestId = ref(0)
const pendingLocate = ref<{ request: number; signalId: string; barEnd: string; endpoint: 'entry' | 'exit'; tradeId: string; identity: string; snapshot: string } | null>(null)
const locatedTradeId = ref<string | null>(null)
const chartRegion = ref<HTMLElement | null>(null)
const referenceRegion = ref<HTMLElement | null>(null)
const sectionOpen = (section: NewowProductSection) => (props.capabilities.open_sections as readonly string[]).includes(section)
const deferredSectionReason = (section: NewowProductSection) => props.capabilities.deferred_sections.find(item => item.section === section)?.reason_code ?? null
const chartResponse = computed(() => (
  loader.sections.chart.data.value?.section === 'chart'
    ? loader.sections.chart.data.value as NewowProductSectionResponse<'chart'>
    : null
))
const comparison = useNewowComparison(chartResponse, comparisonEnabled)
const chartModel = computed(() => chartResponse.value === null ? null : buildNewowProductChartModel(chartResponse.value))
const selectedHint = computed(() => chartModel.value?.hints.find(hint => hint.id === selectedHintId.value) ?? null)
const selectedAction = computed(() => {
  const selection = comparisonSelection.value
  if (selection) {
    const response = selection.strategy === chartResponse.value?.meta.identity.strategy ? chartResponse.value : comparison.response.value
    return response ? buildNewowProductChartModel(response).actions.find(action => action.id === selection.signalId) ?? null : null
  }
  return chartModel.value?.actions.find(action => action.id === selectedSignalId.value) ?? null
})
const selectedActionDescription = computed(() => selectedAction.value === null ? null : describeNewowProductAction(selectedAction.value))
const summaryActionLabel = (action: NewowProductAction) => newowInitialClearLabel(action.trade_eligibility) ?? newowDisplayLabel(action.kind)
const referenceResponse = computed(() => (
  loader.sections.reference.data.value?.section === 'reference'
    ? loader.sections.reference.data.value as NewowProductSectionResponse<'reference'>
    : null
))
const explanationResponse = computed(() => (
  loader.sections.explanation.data.value?.section === 'explanation'
    ? loader.sections.explanation.data.value as NewowProductSectionResponse<'explanation'>
    : null
))
const comparatorResponse = computed(() => (
  loader.sections.comparator.data.value?.section === 'comparator'
    ? loader.sections.comparator.data.value as NewowProductSectionResponse<'comparator'>
    : null
))
const auxiliaryResponse = computed(() => (
  loader.sections.auxiliary.data.value?.section === 'auxiliary'
    ? loader.sections.auxiliary.data.value as NewowProductSectionResponse<'auxiliary'>
    : null
))
function chartWindowProof(response: NewowProductSectionResponse<'chart'> | null): string | null {
  const snapshot = newowChartSnapshotKey(response)
  return snapshot === null || response?.value === null || response === null
    ? null
    : JSON.stringify([snapshot, response.value.chart_from, response.value.chart_through])
}
function locateSnapshotProof(): string | null { return newowChartSnapshotKey(chartResponse.value) }
// A display-only retention of the accepted selected pane while the same loader serves the cup dialog.
const retainedPane = shallowRef<{ response: NewowProductSectionResponse<'auxiliary'> | null; lifecycle: NewowResourceLifecycle; error: string | null; proof: string | null; component: NewowAuxiliaryComponent } | null>(null)
const retainedPaneCompatible = computed(() => dialogKind.value === 'cup_handle' && retainedPane.value !== null
  && retainedPane.value.proof !== null && retainedPane.value.proof === chartWindowProof(chartResponse.value)
  && retainedPane.value.component === selectedAuxiliary.value)
const requiredAuxiliaryComponent = computed<NewowAuxiliaryComponent>(() => dialogKind.value === 'cup_handle' ? 'cup_handle' : selectedAuxiliary.value)
const currentAuxiliaryResponse = computed(() => {
  const response = dialogKind.value === 'cup_handle' ? auxiliaryResponse.value : retainedPaneCompatible.value ? retainedPane.value!.response : auxiliaryResponse.value
  const lifecycle = dialogKind.value === 'cup_handle' ? loader.sections.auxiliary.state.value : retainedPaneCompatible.value ? retainedPane.value!.lifecycle : loader.sections.auxiliary.state.value
  const acceptedWindow = loader.acceptedAuxiliaryWindow.value
  return (lifecycle === 'ready' || lifecycle === 'warming')
    && acceptedWindow !== null && auxiliaryChartWindow.value !== null
    && acceptedWindow.from === auxiliaryChartWindow.value.from && acceptedWindow.through === auxiliaryChartWindow.value.through
    && response?.value?.component === requiredAuxiliaryComponent.value && newowChartSnapshotKey(response) !== null
    && newowChartSnapshotKey(response) === newowChartSnapshotKey(chartResponse.value) ? response : null
})
const currentAuxiliaryLifecycle = computed(() => loader.sections.auxiliary.state.value === 'input_conflict' ? 'input_conflict'
  : dialogKind.value === 'cup_handle' ? loader.sections.auxiliary.state.value
  : retainedPaneCompatible.value ? retainedPane.value!.lifecycle : loader.sections.auxiliary.state.value)
const currentAuxiliaryError = computed(() => loader.sections.auxiliary.state.value === 'input_conflict' ? loader.sections.auxiliary.error.value
  : dialogKind.value === 'cup_handle' ? loader.sections.auxiliary.error.value
  : retainedPaneCompatible.value ? retainedPane.value!.error : loader.sections.auxiliary.error.value)
const auxiliaryChartWindow = computed(() => chartResponse.value?.value === null || chartResponse.value === null
  ? null
  : { from: chartResponse.value.value.chart_from, through: chartResponse.value.value.chart_through })

const summary = computed(() => projectNewowDetail(chartResponse.value, loader.sections.chart.state.value,
  explanationResponse.value, loader.sections.explanation.state.value, loader.explanationChartCompatible.value,
  referenceResponse.value, loader.sections.reference.state.value, loader.referenceChartCompatible.value,
  loader.currentChartWindow.value, loader.historicalChartWindow.value))
const auxiliaryReadiness = computed(() => projectNewowAuxiliaryReadiness(currentAuxiliaryResponse.value?.value, chartResponse.value?.value?.bars.at(-1)))
const auxiliaryDisclosure = computed(() => buildNewowAuxiliaryDisclosure(selectedAuxiliary.value, props.identity.frequency as '1w' | '1d' | '60m', auxiliaryReadiness.value?.currentStatus ?? currentAuxiliaryLifecycle.value))
const auxiliaryOptions = [{ id: 'macd', label: 'MACD' }, { id: 'zhaoyao_mirror', label: '照妖镜' }, { id: 'up_down_energy', label: '涨跌动能' }, { id: 'main_force_control', label: '主力控盘' }, { id: 'trend_reversal', label: '趋势转折' }] as const
const zhaoyaoMirrorLegend = NEWOW_ZHAOYAO_MIRROR_LEGEND
const upDownEnergyLegend = [
  { label: '上涨', color: NEWOW_UP_DOWN_ENERGY_STYLE.up, marker: 'square' },
  { label: '下跌', color: NEWOW_UP_DOWN_ENERGY_STYLE.down, marker: 'square' },
  { label: '波段进场', color: NEWOW_UP_DOWN_ENERGY_STYLE.band, marker: 'triangle' },
  { label: '反弹', color: NEWOW_UP_DOWN_ENERGY_STYLE.rebound, marker: 'triangle' },
  { label: '超跌', color: NEWOW_UP_DOWN_ENERGY_STYLE.oversold, marker: 'triangle' },
] as const
const mainForceLegend = [
  { label: '开始', color: NEWOW_MAIN_FORCE_STYLE.start, marker: 'triangle' },
  { label: '庄控', color: NEWOW_MAIN_FORCE_STYLE.controlled, marker: 'square' },
  { label: '高控', color: NEWOW_MAIN_FORCE_STYLE.high, marker: 'square' },
  { label: '出货', color: NEWOW_MAIN_FORCE_STYLE.distribution, marker: 'square' },
  { label: '无庄', color: NEWOW_MAIN_FORCE_STYLE.none, marker: 'square' },
  { label: '叠加', color: NEWOW_MAIN_FORCE_STYLE.high, marker: 'stack' },
] as const
const trendReversalLegend = [
  { label: '偏离', color: NEWOW_TREND_REVERSAL_STYLE.negative },
  { label: '反弹', color: NEWOW_TREND_REVERSAL_STYLE.rebound },
  { label: '调整', color: NEWOW_TREND_REVERSAL_STYLE.adjust },
] as const
const trendReversalLatest = computed(() => {
  if (currentAuxiliaryResponse.value?.value?.component !== 'trend_reversal') return null
  for (const segment of [...currentAuxiliaryResponse.value.value.segments].reverse()) {
    if (segment.data !== null && !Array.isArray(segment.data) && 'bias' in segment.data) {
      const bias = segment.data.bias.at(-1)
      if (bias !== undefined) return `${bias >= 0 ? '+' : ''}${bias.toFixed(2)}%`
    }
  }
  return null
})
const trendReversalWarmup = computed(() => {
  if (currentAuxiliaryResponse.value?.value?.component !== 'trend_reversal') return null
  for (const segment of [...currentAuxiliaryResponse.value.value.segments].reverse()) {
    if (segment.data !== null && !Array.isArray(segment.data) && 'enough' in segment.data) {
      return segment.data.enough ? null : segment.data.bar_count
    }
  }
  return null
})
const historicalAsOfLabel = computed(() => loader.historicalSnapshot.value ? formatChartTimeInShanghai(loader.historicalSnapshot.value.as_of) : '')
const niuwaIndicatorTitles: Partial<Record<NewowAuxiliaryComponent, string>> = {
  zhaoyao_mirror: '主力动态', up_down_energy: '涨跌动能', main_force_control: '主力控盘', trend_reversal: '趋势转折',
}
const isNiuwaIndicatorDialog = computed(() => dialogKind.value === 'indicator' && selectedAuxiliary.value in niuwaIndicatorTitles)
const dialogTitle = computed(() => isNiuwaIndicatorDialog.value ? `${niuwaIndicatorTitles[selectedAuxiliary.value]} · 指标解读` : ({ explanation: '策略解释', action: '历史主动作事实', hint: '历史过程提示', indicator: '指标解读', comparator: '页面比较说明', cup_handle: '杯柄说明', formula: '公式速查' }[dialogKind.value ?? 'explanation']))
const summaryContract = computed(() => chartResponse.value?.value?.bars.at(-1)?.physical_contract ?? '物理合约不可用')
const summaryAsOf = computed(() => shortNewowTime(chartResponse.value?.meta.as_of))
const openReferenceText = computed(() => summary.value.openReference ? '未清仓页面参考交易' : loader.sections.reference.state.value === 'ready' ? '当前无未清仓页面参考交易' : loader.sections.reference.state.value === 'not_requested' ? '参考交易尚未读取' : '参考交易当前不可用')
const featureStateText = (section: NewowProductSection) => !sectionOpen(section) ? '当前发布阶段未开放' : loader.sections[section].state.value === 'loading' ? '正在读取' : '证据不足或当前不可用'
async function loadExplanation() { if (sectionOpen('explanation') && loader.sections.explanation.state.value === 'not_requested') await loader.loadExplanation() }
async function loadAuxiliaryForChart(component: NewowAuxiliaryComponent = selectedAuxiliary.value) {
  if (!sectionOpen('auxiliary') || auxiliaryChartWindow.value === null || !chartResponse.value?.meta.snapshot_token) return
  await loader.loadAuxiliary(component, auxiliaryChartWindow.value)
}
async function openDialog(kind: NonNullable<typeof dialogKind.value>) {
  if (kind === 'cup_handle') retainedPane.value = { response: currentAuxiliaryResponse.value, lifecycle: currentAuxiliaryLifecycle.value,
    error: currentAuxiliaryError.value, proof: chartWindowProof(chartResponse.value), component: selectedAuxiliary.value }
  dialogKind.value = kind
  if (kind === 'explanation') await loadExplanation()
  if (kind === 'comparator' && sectionOpen('comparator') && loader.sections.comparator.state.value === 'not_requested') await loader.loadComparator()
  if (kind === 'cup_handle' && props.identity.frequency === '1d' && props.identity.strategy === 'trend') await loadAuxiliaryForChart('cup_handle')
}
function closeDialog() {
  const wasCup = dialogKind.value === 'cup_handle'
  dialogKind.value = null
  if (wasCup) void loadAuxiliaryForChart()
  retainedPane.value = null
}
function selectComparisonSignal(strategy: 'trend' | 'oscillation', signalId: string) {
  const response = strategy === chartResponse.value?.meta.identity.strategy ? chartResponse.value : comparison.response.value
  if (!response?.value?.actions.some(action => action.signal_id === signalId)) return
  comparisonSelection.value = { strategy, signalId }
  void openDialog('action')
}
watch([comparison.response, chartResponse, comparisonEnabled], () => { comparisonSelection.value = null })
function selectSignal(signalId: string) {
  comparisonSelection.value = null
  if (!chartModel.value?.actions.some(action => action.id === signalId)) return
  selectedSignalId.value = signalId
  void openDialog('action')
}
function selectHint(hintId: string) {
  if (!chartModel.value?.hints.some(hint => hint.id === hintId)) return
  selectedHintId.value = hintId
  void openDialog('hint')
}
async function toggleAuxiliary(component: NewowAuxiliaryComponent) {
  if (selectedAuxiliary.value === component) return
  selectedAuxiliary.value = component
  await loadAuxiliaryForChart(component)
}
function loadReferenceOnce() { if (sectionOpen('reference') && loader.sections.reference.state.value === 'not_requested') void loader.loadReference() }
function loadFirstScreenResearch(): void {
  if (sectionOpen('explanation') && loader.sections.explanation.state.value === 'not_requested') void loader.loadExplanation()
  loadReferenceOnce()
}
async function openHistory(): Promise<void> {
  loadReferenceOnce()
  await nextTick()
  referenceRegion.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  referenceRegion.value?.focus({ preventScroll: true })
}
async function locateReferenceTrade(trade: NewowReferenceTrade, endpoint: 'entry' | 'exit' = 'entry'): Promise<void> {
  const request = ++locateRequest.value
  pendingLocate.value = null
  const snapshot = locateSnapshotProof()
  if (snapshot === null) {
    locateMessage.value = '当前图表缺少完整快照证明，未定位参考信号。'
    return
  }
  const context = { identity: identityKey.value, snapshot }
  locateMessage.value = `正在定位${endpoint === 'entry' ? '建仓' : '清仓'}…`
  let target = resolveNewowReferenceLocate(trade, chartResponse.value, loader.referenceChartCompatible.value, endpoint)
  if (target.kind === 'request_display_window') {
    await loader.loadChart(target.displayWindow)
    if (request !== locateRequest.value || context.identity !== identityKey.value || context.snapshot !== locateSnapshotProof()) {
      if (request === locateRequest.value) locateMessage.value = '图表身份或快照已刷新，未使用旧定位结果。'
      return
    }
    target = resolveNewowReferenceLocate(trade, chartResponse.value, loader.referenceChartCompatible.value, endpoint)
  }
  if (target.kind !== 'loaded') {
    locateMessage.value = `无法按精确信号 ${target.signalId ?? '—'} / ${target.barEnd ?? '—'} 定位；没有跳转到邻近日期。`
    return
  }
  pendingLocate.value = { request, signalId: target.signalId, barEnd: target.barEnd, endpoint, tradeId: trade.reference_trade_id, ...context }
  chartFocusRequestId.value = request
  selectedSignalId.value = target.signalId
  await nextTick()
  if (request !== locateRequest.value || context.identity !== identityKey.value || context.snapshot !== locateSnapshotProof()) {
    if (request === locateRequest.value) { pendingLocate.value = null; locateMessage.value = '图表身份或快照已刷新，未使用旧定位结果。' }
    return
  }
  chartRegion.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function resolveSignalFocus(signalId: string, request: number): void {
  const pending = pendingLocate.value
  const snapshot = locateSnapshotProof()
  if (pending !== null && pending.request === request && pending.signalId === signalId && pending.identity === identityKey.value && pending.snapshot === snapshot) {
    locateMessage.value = `已定位 ${pending.endpoint === 'entry' ? '建仓' : '清仓'}信号 ${signalId} / ${pending.barEnd}。`
    locatedTradeId.value = pending.tradeId
    pendingLocate.value = null
  }
  const action = chartModel.value?.actions.find((item) => item.id === signalId)
  if (action !== undefined && props.identity.focusBarEnd === action.barEnd) emit('focus-resolved', action.barEnd)
}
async function returnToReferenceTrade(): Promise<void> {
  if (locatedTradeId.value === null) return
  await nextTick()
  const record = document.getElementById(`reference-trade-${locatedTradeId.value}`)
  if (record === null) {
    locateMessage.value = '原记录不在当前筛选或已加载页，未修改筛选、统计窗口或分页。'
    referenceRegion.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    referenceRegion.value?.focus({ preventScroll: true })
    return
  }
  record.scrollIntoView({ behavior: 'smooth', block: 'center' })
  record.focus({ preventScroll: true })
}
function refreshCurrent(): void { loader.refreshCurrent(); emit('refresh-current') }


watch(selectedAuxiliary, value => rememberNewowUiPreferences(identityKey.value, { auxiliary: value }))
watch(identityKey, async (_key, previous) => {
  if (previous) rememberNewowUiPreferences(previous, { auxiliary: selectedAuxiliary.value, scrollTop: scrollOwner()?.scrollTop ?? 0 })
  restoredScroll = false
  comparisonSelection.value = null; ++locateRequest.value; chartFocusRequestId.value = 0; pendingLocate.value = null; locatedTradeId.value = null; selectedSignalId.value = null; selectedHintId.value = null; retainedPane.value = null; selectedAuxiliary.value = readNewowUiPreferences(identityKey.value).auxiliary ?? 'macd'; dialogKind.value = null; locateMessage.value = null
}, { flush: 'sync' })
watch(loader.historicalSnapshot, async () => {
  emit('snapshot-mode', loader.historicalSnapshot.value?.as_of ?? null)
  comparisonSelection.value = null; ++locateRequest.value; chartFocusRequestId.value = 0; pendingLocate.value = null; locatedTradeId.value = null; selectedSignalId.value = null; selectedHintId.value = null; retainedPane.value = null
  dialogKind.value = null; locateMessage.value = null
}, { flush: 'sync' })
watch(loader.dailySnapshot, snapshot => {
  emit('daily-snapshot-pending', snapshot?.freshness === 'pending_update')
  emit('daily-snapshot-as-of', snapshot?.as_of ?? null)
}, { immediate: true, flush: 'sync' })
watch(loader.weeklySnapshot, snapshot => emit('weekly-quote-context', {
  asOf: snapshot?.current_context.status === 'known' ? snapshot.requested_at : null,
  physicalContract: snapshot?.current_context.status === 'known' ? snapshot.current_context.physical_contract : null,
}), { immediate: true, flush: 'sync' })
// The single loader's invalidation also revokes display retention, even when the chart proof is unchanged.
watch(loader.sections.auxiliary.state, state => {
  if (state === 'input_conflict' || state === 'not_requested') retainedPane.value = null
}, { flush: 'sync' })
watch(() => chartWindowProof(chartResponse.value), (proof, previous) => {
  if (proof === previous) return
  retainedPane.value = null
  if (dialogKind.value === 'cup_handle') dialogKind.value = null
  if (proof !== null) loadFirstScreenResearch()
}, { immediate: true, flush: 'sync' })
// Load the default auxiliary only after chart acceptance, so its request carries the chart snapshot proof.
watch(() => auxiliaryChartWindow.value === null ? null : [
  chartResponse.value?.meta.snapshot_token,
  auxiliaryChartWindow.value.from,
  auxiliaryChartWindow.value.through,
].join('|'), () => {
  if (chartResponse.value) void loadAuxiliaryForChart()
}, { immediate: true, flush: 'sync' })
watch([chartModel, () => props.identity.focusBarEnd], ([model, focusBarEnd]) => {
  if (!focusBarEnd || model === null || selectedSignalId.value !== null) return
  selectedSignalId.value = model.actions.find(action => action.barEnd === focusBarEnd)?.id ?? null
}, { immediate: true })
defineExpose({ openHistory })
function scrollOwner(): HTMLElement | null {
  let element = chartRegion.value?.parentElement ?? null
  while (element) {
    if (/(auto|scroll)/.test(getComputedStyle(element).overflowY)) return element
    element = element.parentElement
  }
  return document.scrollingElement as HTMLElement | null
}
let restoredScroll = false
watch(chartResponse, async value => {
  if (!value?.value || restoredScroll) return
  restoredScroll = true
  const key = identityKey.value
  const top = readNewowUiPreferences(key).scrollTop
  await nextTick()
  if (key === identityKey.value && top !== undefined) scrollOwner()?.scrollTo({ top })
}, { flush: 'post' })
onBeforeUnmount(() => {
  rememberNewowUiPreferences(identityKey.value, { auxiliary: selectedAuxiliary.value, scrollTop: scrollOwner()?.scrollTop ?? 0 })
  comparison.dispose(); loader.dispose()
})
</script>

<template>
  <section class="newow-product-workspace" data-detail-workspace="newow" :data-strategy="identity.strategy" :data-frequency="identity.frequency" :data-chart-state="loader.sections.chart.state.value" :data-auxiliary-state="loader.sections.auxiliary.state.value">
    <section class="newow-summary" aria-label="策略概览">
      <div class="newow-summary__main">
        <strong>策略概览 <small class="newow-summary__scope">页面参考</small></strong>
        <span class="newow-status" :data-state="summary.status.state"><span>{{ ({ BUILD: '▲', HOLD: '✓', CLEAR: '▼', FLAT: '×', UNAVAILABLE: '?' })[summary.status.state] }}</span>{{ summary.status.label }}</span>
        <span class="newow-summary__identity">{{ summaryContract }} · 截至 {{ summaryAsOf }}</span>
        <button class="newow-summary__evidence" @click="openDialog('explanation')">查看依据</button>
      </div>
      <div class="newow-summary__facts">
        <span :title="summary.status.barEnd ?? undefined">{{ summary.status.historical ? '历史窗口最近主动作' : '已读取窗口最近主动作' }} <button v-if="summary.latestAction" :title="summary.latestAction.bar_end" @click="selectSignal(summary.latestAction.signal_id)">{{ summaryActionLabel(summary.latestAction) }} · {{ formatMarketDecimal(summary.latestAction.reference_price) }} · {{ shortNewowTime(summary.latestAction.bar_end) }}</button><template v-else>—</template></span>
        <span>当前参考交易 {{ openReferenceText }}</span>
        <span>参考浮动 <span class="newow-return-badge" :data-direction="referencePercentDisplay(summary.openReference?.mark_change_pct).direction">{{ referencePercentDisplay(summary.openReference?.mark_change_pct).text }}</span> · {{ shortNewowTime(summary.openReference?.mark_bar_end) }}</span>
        <span :title="summary.status.barEnd ?? undefined">{{ summary.status.historical ? '历史窗口状态截至' : '已读取状态截至' }} {{ shortNewowTime(summary.status.barEnd) }}</span>
      </div>
    </section>


    <MarketDetailUnavailable v-if="chartResponse === null && loader.sections.chart.state.value !== 'loading' && !loader.dailyLoading.value" class="newow-product-workspace__unavailable-chart" title="主图事实不可用" :message="`${newowErrorDisplay(loader.sections.chart.error.value) ?? '当前主图没有可显示的已验证数值'}；参考与解释保持独立状态。`" :technical-detail="loader.sections.chart.error.value" recovery-label="刷新日线" :can-recover="true" :can-return-market="false" @recover="loader.refreshCurrent()" />
    <div v-else ref="chartRegion" class="newow-product-workspace__chart"><NewowProductChartStage :response="chartResponse" :reference-trades="loader.referenceChartCompatible.value ? referenceResponse?.value?.items ?? [] : []" :target-price="summary.target?.display_value ?? null" :absorb-price="summary.absorb?.display_value ?? null" :reference-price-status="!sectionOpen('explanation') ? '未开放' : loader.sections.explanation.state.value === 'loading' ? '读取中' : '不可用 / 证据不足'" :comparison-response="comparisonEnabled ? comparison.response.value : null" :strategy="selectedStrategy" :selected-signal-id="selectedSignalId" :focus-request-id="chartFocusRequestId" :loading="loader.sections.chart.state.value === 'loading'" :has-more-before="chartModel?.nextBefore != null || chartResponse?.value?.next_older_window != null" :auxiliary-response="currentAuxiliaryResponse" :auxiliary-lifecycle="currentAuxiliaryLifecycle" :auxiliary-error="currentAuxiliaryError" @load-earlier="loader.loadNextChartPage" @select-signal="selectSignal" @select-comparison-signal="selectComparisonSignal" @focus-resolved="resolveSignalFocus" @select-hint="selectHint" @explain-main="openDialog('explanation')" @explain-auxiliary="openDialog('indicator')">
    <template #reference-controls><slot name="chart-frequency" /></template>
    <template #main-controls><div class="newow-product-workspace__comparison-controls"><button type="button" :disabled="selectedStrategy === 'main_rise'" :title="selectedStrategy === 'main_rise' ? '双轨对照由趋势与震荡组成，请切换到其中一个策略' : '读取相同时间与物理合约的另一策略，不合并收益'" :aria-pressed="comparisonEnabled && selectedStrategy !== 'main_rise'" @click="comparisonEnabled = !comparisonEnabled">双策略对照</button><span v-if="comparisonEnabled && selectedStrategy !== 'main_rise'" role="status">{{ newowUiStateLabel(comparison.state.value) }} · 趋势上轨 / 震荡下轨 · 参考统计仍属于 {{ newowDisplayLabel(selectedStrategy) }}</span><span v-if="comparison.error.value" role="status">{{ comparison.error.value }} <button @click="comparison.reload">重试对照</button></span></div></template>
    <template #auxiliary-controls>
    <section class="newow-product-workspace__auxiliary" aria-label="Newow 辅助图层">
      <div class="newow-product-workspace__auxiliary-controls">
        <div class="newow-product-workspace__auxiliary-tabs">
          <button v-for="option in auxiliaryOptions" :key="option.id" :aria-pressed="selectedAuxiliary === option.id" @click="toggleAuxiliary(option.id)">{{ option.label }}</button>
          <span v-if="selectedAuxiliary === 'macd'" class="newow-macd-legend"><span>DIF</span> / <span>DEA</span></span>
          <button v-if="identity.strategy === 'trend' && identity.frequency === '1d'" @click="openDialog('cup_handle')">杯柄说明</button><button @click="openDialog('formula')">公式速查</button>
        </div>
      </div>
      <div class="newow-product-workspace__auxiliary-legend-row">
      <div v-if="selectedAuxiliary === 'zhaoyao_mirror'" class="newow-mirror-legend" role="group" aria-label="主力动态颜色说明">
        <span class="newow-mirror-legend__title">主力动态</span>
        <span v-for="item in zhaoyaoMirrorLegend" :key="item.label" class="newow-mirror-legend__item"><i aria-hidden="true" :style="{ backgroundColor: item.color }" />{{ item.label }}</span>
      </div>
      <div v-if="selectedAuxiliary === 'up_down_energy'" class="newow-mirror-legend" role="group" aria-label="涨跌动能颜色说明">
        <span class="newow-mirror-legend__title">涨跌动能</span>
        <span v-for="item in upDownEnergyLegend" :key="item.label" class="newow-mirror-legend__item" :style="{ color: item.color }"><i v-if="item.marker === 'square'" aria-hidden="true" :style="{ backgroundColor: item.color }" /><b v-else aria-hidden="true">▲</b>{{ item.label }}</span>
      </div>
      <div v-if="selectedAuxiliary === 'main_force_control'" class="newow-mirror-legend" role="group" aria-label="主力控盘颜色说明">
        <span class="newow-mirror-legend__title">主力控盘</span>
        <span v-for="item in mainForceLegend" :key="item.label" class="newow-mirror-legend__item" :style="{ color: item.color }"><i v-if="item.marker !== 'triangle'" aria-hidden="true" :class="{ 'newow-mirror-legend__stack': item.marker === 'stack' }" :style="item.marker === 'stack' ? {} : { backgroundColor: item.color }" /><b v-else aria-hidden="true">▲</b>{{ item.label }}</span>
      </div>
      <div v-if="selectedAuxiliary === 'trend_reversal'" class="newow-trend-reversal-legend" role="group" aria-label="趋势转折颜色说明">
        <div><strong>趋势转折</strong><span>20 根 Bar 威廉位置 · 120 根 Bar 均线乖离</span></div>
        <div><span>最新偏离 {{ trendReversalLatest ?? '—' }}</span><span class="newow-trend-reversal-legend__keys"><span v-for="item in trendReversalLegend" :key="item.label" class="newow-mirror-legend__item"><i aria-hidden="true" :class="{ 'newow-trend-reversal-legend__bias': item.label === '偏离' }" :style="item.label === '偏离' ? {} : { backgroundColor: item.color }" />{{ item.label }}</span></span></div>
        <p v-if="trendReversalWarmup !== null" role="status">当前合约计算段仅 {{ trendReversalWarmup }} 根 Bar，未满 120 根；图形为预热参考。</p>
      </div>
      <span v-if="selectedAuxiliary === 'macd'" class="newow-mirror-legend__title">MACD</span>
        <button class="newow-product-workspace__indicator-help" type="button" @click="openDialog('indicator')">指标解读</button>
      </div>
      <p v-if="currentAuxiliaryError" role="status">{{ newowErrorDisplay(currentAuxiliaryError) }} · 辅助图层不可用 <button @click="loadAuxiliaryForChart()">重试指标</button></p>
    </section>
    </template>
    </NewowProductChartStage><button v-if="locatedTradeId !== null" type="button" class="newow-product-workspace__return" @click="returnToReferenceTrade">返回原记录</button></div>
    <div class="newow-product-workspace__snapshot-controls" :data-as-of="loader.historicalSnapshot.value?.as_of ?? loader.dailySnapshot.value?.as_of ?? loader.weeklySnapshot.value?.as_of">
      <template v-if="loader.historicalSnapshot.value">
        <span :title="loader.historicalSnapshot.value.as_of">历史快照截至 {{ historicalAsOfLabel }}（交易日 {{ loader.historicalSnapshot.value.trading_day }}）</span>
        <button @click="loader.returnToCurrent">返回当前</button>
      </template>
      <template v-else>
        <span v-if="loader.dailySnapshot.value" :title="loader.dailySnapshot.value.as_of">日线截至 {{ loader.dailySnapshot.value.available_trading_day }} 收盘</span>
        <span v-if="loader.dailySnapshot.value?.freshness === 'pending_update'" role="status">{{ loader.dailySnapshot.value.expected_trading_day }} 日线待更新</span>
        <span v-if="loader.weeklySnapshot.value" :title="loader.weeklySnapshot.value.as_of">周线截至 {{ loader.weeklySnapshot.value.available_period_end }}，当前主力 {{ loader.weeklySnapshot.value.current_context.physical_contract ?? '不可判定' }}</span>
        <span v-if="loader.weeklySnapshot.value?.freshness === 'pending_update'" role="status">{{ loader.weeklySnapshot.value.expected_period_end }} 周线待发布</span>
        <span v-if="loader.dailyLoading.value" role="status">正在确认最近完整{{ identity.frequency === '1w' ? '周线' : '日线' }}…</span>
        <span v-if="loader.dailyError.value" role="status">{{ newowErrorDisplay(loader.dailyError.value) }}</span>
        <button :disabled="loader.historicalLoading.value" @click="loader.switchToHistorical">查看最近可用历史快照</button>
        <button :disabled="loader.dailyLoading.value || loader.sections.chart.state.value === 'loading'" @click="refreshCurrent">{{ loader.dailyLoading.value || loader.sections.chart.state.value === 'loading' ? '读取中…' : '刷新当前' }}</button>
        <span v-if="loader.historicalError.value" role="status">{{ newowErrorDisplay(loader.historicalError.value) }}</span>
      </template>
    </div>
    <div class="newow-product-workspace__read-state" aria-live="polite"><span>主图 · {{ loader.dailyLoading.value ? '正在确认完整周期' : newowUiStateLabel(loader.sections.chart.state.value) }}</span><span>副图 · {{ newowUiStateLabel(currentAuxiliaryLifecycle) }}</span><span>参考 · {{ newowUiStateLabel(loader.sections.reference.state.value) }}</span></div>
    <section ref="referenceRegion" class="newow-product-workspace__research" aria-label="Newow 参考与解释" tabindex="-1">
      <button @click="openDialog('formula')">公式速查</button>
      <button @click="openDialog('comparator')">页面比较说明</button>
      <p v-if="locateMessage" class="newow-product-workspace__reference-message" data-testid="newow-reference-locate-status" role="status">{{ locateMessage }}</p>
      <NewowReferencePanel :key="identityKey" :chart-lifecycle="loader.sections.chart.state.value" :current-chart-window="loader.currentChartWindow.value" :response="referenceResponse" :chart-response="chartResponse" :cross-section-compatible="loader.referenceChartCompatible.value" :lifecycle="loader.sections.reference.state.value" :error="loader.sections.reference.error.value" :selected-signal-id="selectedSignalId" :locate-message="null" :loading-page="loader.sections.reference.state.value === 'loading'" @reload="loader.loadReference" @retry="loader.loadReference()" @load-more="loader.loadNextReferencePage" @locate="locateReferenceTrade" />
      <ReferenceTradePanel :strategy="`newow-${selectedStrategy.replace('_', '-')}`" :product="identity.symbol.toLowerCase()" :frequency="identity.frequency" :through="chartResponse?.value?.bars.at(-1)?.trading_day" />
    </section>
    <NewowDetailDialog :open="dialogKind !== null" :wide="dialogKind === 'explanation' || dialogKind === 'comparator' || dialogKind === 'cup_handle' || dialogKind === 'formula'" :variant="isNiuwaIndicatorDialog ? 'niuwa-indicator' : undefined" :title="dialogTitle" :identity-key="identityKey" @close="closeDialog">
      <p v-if="!isNiuwaIndicatorDialog">{{ identity.symbol.toUpperCase() }} · {{ newowDisplayLabel(comparisonSelection?.strategy ?? identity.strategy ?? 'UNAVAILABLE') }} · {{ identity.frequency }} · {{ dialogKind === 'action' ? selectedAction?.physicalContract : dialogKind === 'hint' ? selectedHint?.physicalContract : chartResponse?.value?.bars.at(-1)?.physical_contract ?? '—' }}</p>
      <NewowFormulaHelp v-if="dialogKind === 'formula'" :topic="selectedStrategy" :formula-versions="chartResponse?.meta.identity.formula_versions" :as-of="chartResponse?.meta.as_of" />
      <template v-else-if="dialogKind === 'hint'">
        <p v-if="selectedHint">{{ newowDisplayLabel(selectedHint.kind) }} · {{ formatMarketDecimal(selectedHint.anchorPrice) }} · {{ shortNewowTime(selectedHint.barEnd) }}</p>
        <p>仅为所选历史过程提示，不代表主动作或账户成交。</p>
        <details v-if="selectedHint"><summary>来源与原始事实</summary><p>{{ selectedHint.id }} · {{ selectedHint.barEnd }}</p><p>known_at {{ selectedHint.confirmedAt }} · sequence {{ selectedHint.sequence ?? '—' }}</p><p>owner {{ selectedHint.physicalContract }} · {{ selectedHint.segmentId }}</p><p>来源 {{ selectedHint.sourceIdentity ?? '—' }} · 响应公式 {{ selectedHint.formulaVersions.join(' / ') }}</p><p>anchor_price {{ selectedHint.anchorPrice ?? '—' }}</p></details>
      </template>
      <template v-else-if="dialogKind === 'action'">
        <p v-if="selectedAction">历史主动作 {{ selectedActionDescription?.label }} · {{ formatMarketDecimal(selectedAction.referencePrice) }} · {{ shortNewowTime(selectedAction.barEnd) }}</p>
        <p>{{ selectedActionDescription?.explanation ?? '仅为所选历史主动作事实，不代表账户成交。' }}</p>
        <details><summary>来源与关联 Hint</summary><p>{{ comparisonSelection?.signalId ?? selectedSignalId }} · {{ selectedAction?.barEnd }}</p><p v-for="hint in (comparisonSelection && comparisonSelection.strategy !== selectedStrategy ? comparison.response.value : chartResponse)?.value?.hints.filter(hint => (comparisonSelection && comparisonSelection.strategy !== selectedStrategy ? comparison.response.value : chartResponse)?.value?.frames.find(frame => frame.bar_end === selectedAction?.barEnd)?.hint_ids.includes(hint.hint_id)) ?? []" :key="hint.hint_id">{{ hint.kind }} · {{ hint.hint_id }} · known_at {{ hint.known_at }} · {{ hint.anchor_price ?? '—' }}</p></details>
      </template>
      <template v-else-if="dialogKind === 'indicator'"><details class="newow-help-formulas"><summary>公式、阈值与边界速查</summary><NewowFormulaHelp :topic="selectedAuxiliary === 'cup_handle' ? selectedStrategy : selectedAuxiliary" :formula-versions="currentAuxiliaryResponse?.value ? [currentAuxiliaryResponse.value.formula_version] : []" :as-of="currentAuxiliaryResponse?.meta.as_of" /></details><h3 v-if="!isNiuwaIndicatorDialog">{{ auxiliaryDisclosure.title }}</h3>
        <template v-if="selectedAuxiliary === 'zhaoyao_mirror'">
          <div class="newow-niuwa-explanation newow-niuwa-explanation--mirror">
            <div class="newow-niuwa-explanation__card newow-niuwa-explanation__card--mirror"><strong>看图口诀：</strong><p><b class="newow-niuwa-explanation__red">零轴之上</b>看<b class="newow-niuwa-explanation__red">红</b><b class="newow-niuwa-explanation__green">绿</b>（进/洗），</p><p><b class="newow-niuwa-explanation__blue">零轴之下</b>看<b class="newow-niuwa-explanation__yellow">黄</b><b class="newow-niuwa-explanation__blue">蓝</b>（拉/出），</p><p><b class="newow-niuwa-explanation__blue">虚线</b>出现要警惕（退/诱）</p></div>
            <div class="newow-niuwa-explanation__rows">
              <div class="newow-niuwa-explanation__row"><i class="newow-niuwa-explanation__dot" style="--dot:#ff403a"></i><p><strong>进场（红）</strong>：零轴上方红色宽柱，主力吸筹开始</p></div>
              <div class="newow-niuwa-explanation__row"><i class="newow-niuwa-explanation__dot" style="--dot:#30b458"></i><p><strong>洗盘（绿）</strong>：零轴上方绿色窄柱，清洗浮筹假摔</p></div>
              <div class="newow-niuwa-explanation__row"><i class="newow-niuwa-explanation__dot" style="--dot:#ffcc00"></i><p><strong>拉高（黄）</strong>：零轴下方黄色宽柱，快速拉升脱离成本</p></div>
              <div class="newow-niuwa-explanation__row"><i class="newow-niuwa-explanation__dot" style="--dot:#007aff"></i><p><strong>出货（蓝）</strong>：零轴下方蓝色窄柱，高位派发筹码松动</p></div>
              <div class="newow-niuwa-explanation__row"><i class="newow-niuwa-explanation__dot" style="--dot:#0860b7"></i><p><strong>退场（深蓝虚线）</strong>：控盘走弱，主力离场</p></div>
              <div class="newow-niuwa-explanation__row"><i class="newow-niuwa-explanation__dot" style="--dot:#ff8800"></i><p><strong>诱多（橙色虚线）</strong>：假突破吸引跟风后砸盘</p></div>
            </div>
            <p class="newow-niuwa-explanation__note">仅供历史回看；该指标会重绘，不进入正式信号。</p>
          </div>
        </template>
        <template v-else-if="selectedAuxiliary === 'up_down_energy'">
          <div class="newow-niuwa-explanation newow-niuwa-explanation--energy">
            <div class="newow-niuwa-explanation__card newow-niuwa-explanation__card--energy">
              <p><b class="newow-niuwa-explanation__red">上涨动能（红）</b>　压力系数　<b class="newow-niuwa-explanation__green">下跌动能（绿）</b>　支撑系数</p>
              <p class="newow-niuwa-explanation__blue">上楼梯走平 → 遇压力卖出｜下楼梯走平 → 遇支撑买入</p>
              <small>动能高度表示当前区间位置，不预测下一根的涨跌幅度</small>
            </div>
            <div class="newow-niuwa-explanation__energy-rows">
              <div><strong>红色曲线（压力系数）</strong><p>价格上涨中的区间位置参考，越接近 100 压力越大，见波段高点。<br>95 横线 = 压力警戒线。曲线越宽压力越强。</p></div>
              <div><strong>绿色曲线（支撑系数）</strong><p>价格下跌中的区间位置参考，越接近 0 支撑越大，见波段低点。<br>5 横线 = 支撑警戒线。曲线越宽支撑越强。</p></div>
            </div>
            <div class="newow-niuwa-explanation__signal-rows">
              <div><i class="newow-niuwa-explanation__dot" style="--dot:#ff403a"></i><strong class="newow-niuwa-explanation__red">波段进场（红三角▲）</strong><p>上升区间中的调整低点提示<br>是否继续上行需要后续事实验证。</p></div>
              <div><i class="newow-niuwa-explanation__dot" style="--dot:#ff9500"></i><strong class="newow-niuwa-explanation__orange">反弹进场（橙三角▲）</strong><p>下跌趋势中的反弹买入时机，见好就收<br>该标记仅表达公式满足条件，不触发账户操作。</p></div>
              <div><i class="newow-niuwa-explanation__dot" style="--dot:#d935ee"></i><strong class="newow-niuwa-explanation__purple">超跌进场（紫三角▲）</strong><p>疯狂下跌后的超跌警示信号 = 大底区域<br>不代表安全、获利概率或反弹强度。</p></div>
            </div>
            <div class="newow-niuwa-explanation__practical"><i class="newow-niuwa-explanation__dot" style="--dot:#0878f9"></i><strong class="newow-niuwa-explanation__blue">实战口诀</strong><p>红带变绿 = 区间位置改变，查看主策略状态<br>绿带变红 = 区间位置改变，查看主策略状态<br>阈值满足仅产生过程提示，不替代主策略动作</p></div>
            <p class="newow-niuwa-explanation__note">以上为牛哇页面解读口径，不代表可执行交易或收益预测。</p>
          </div>
        </template>
        <template v-else-if="selectedAuxiliary === 'main_force_control'">
          <div class="newow-niuwa-explanation newow-niuwa-explanation--control">
            <div class="newow-niuwa-explanation__cycle"><small>一个完整的控盘周期</small><p><b class="newow-niuwa-explanation__purple">▲开始</b><span>→</span><b class="newow-niuwa-explanation__red">■庄控</b><span>→</span><b class="newow-niuwa-explanation__magenta">■高控</b><span>→</span><b class="newow-niuwa-explanation__lime">■出货</b><span>→</span><b class="newow-niuwa-explanation__gold">■无庄</b></p></div>
            <div class="newow-niuwa-explanation__verse"><strong>📌 看图口诀</strong><p><b class="newow-niuwa-explanation__purple">紫三角▲出现</b> → 控盘启动，<em>可以关注</em><br><b class="newow-niuwa-explanation__red">红柱连续上升</b> → 有庄建仓，<em>趋势持有参考</em><br><b class="newow-niuwa-explanation__magenta">洋红柱出现</b> → 高度控盘，<em>强势持有</em><br><b class="newow-niuwa-explanation__lime">绿柱开始出现</b> → 主力出货，<em class="newow-niuwa-explanation__red">考虑减仓</em><br><b class="newow-niuwa-explanation__gold">金黄柱子</b> → 无庄控盘，<em class="newow-niuwa-explanation__muted">观望为主</em></p></div>
            <div class="newow-niuwa-explanation__core"><strong>⚡ 核心要点</strong><p>• 紫三角▲是最关键的信号——代表主力从“不关注”变成“开始控盘”<br>• 一般<span class="newow-niuwa-explanation__lime">绿色下跌浪</span>来临前，主力都会先拉高再出货<br>• <span class="newow-niuwa-explanation__lime">绿柱（出货）</span>只表示公式状态变化，与正式减仓决策相互独立</p></div>
            <div class="newow-niuwa-explanation__control-rows">
              <div><i class="newow-niuwa-explanation__dot" style="--dot:#9933ff"></i><p><strong>▲开始控盘</strong> — 主力刚入场，关注信号</p></div>
              <div><i class="newow-niuwa-explanation__dot" style="--dot:#ff0000"></i><p><strong>■有庄控盘</strong> — 主力在加仓，趋势向上</p></div>
              <div><i class="newow-niuwa-explanation__dot" style="--dot:#ff00ff"></i><p><strong>■高度控盘</strong> — 强势阶段，价格在均线上方</p></div>
              <div><i class="newow-niuwa-explanation__dot" style="--dot:#00e638"></i><p><strong>■主力出货</strong> — 高位派发筹码，注意风险</p></div>
              <div><i class="newow-niuwa-explanation__dot" style="--dot:#ffcc66"></i><p><strong>■无庄控盘</strong> — 零轴下方，暂无主力关注</p></div>
              <div><i class="newow-niuwa-explanation__dot newow-niuwa-explanation__dot--stack"></i><p><strong>■叠加柱</strong> — 边拉高边出货，洋红+绿双色</p></div>
            </div>
            <p class="newow-niuwa-explanation__note">页面解读不代表真实持仓、成交或可执行交易建议。</p>
          </div>
        </template>
        <template v-else-if="selectedAuxiliary === 'trend_reversal'">
          <div class="newow-trend-reversal-explanation">
            <p class="newow-trend-reversal-explanation__intro">基于当前周期的 20 根 Bar 区间位置与 120 根 Bar 均线乖离，展示历史走势转折参考。</p>
            <p v-if="trendReversalWarmup !== null" role="status">当前合约计算段只有 {{ trendReversalWarmup }} 根 Bar，未满 120 根；均线使用已有 Bar 的均值，当前图形仍在预热。</p>
            <div class="newow-trend-reversal-explanation__list">
              <div class="newow-trend-reversal-explanation__item newow-trend-reversal-explanation__item--adjust"><span class="newow-trend-reversal-explanation__dot" aria-hidden="true"></span><div><strong>蓝色柱 = 调整标记</strong><p>收盘价贴近近 20 根 Bar 最高价时显示冷蓝加粗柱。该标记只描述当前区间位置，不预测后续走势。</p></div></div>
              <div class="newow-trend-reversal-explanation__item newow-trend-reversal-explanation__item--rebound"><span class="newow-trend-reversal-explanation__dot" aria-hidden="true"></span><div><strong>橙色柱 = 反弹标记</strong><p>收盘价贴近近 20 根 Bar 最低价时显示暖橙加粗柱。该标记只描述当前区间位置，不预测后续走势。</p></div></div>
              <div class="newow-trend-reversal-explanation__item newow-trend-reversal-explanation__item--bias"><span class="newow-trend-reversal-explanation__dot" aria-hidden="true"></span><div><strong>零轴与偏离柱</strong><p>普通细柱为收盘价相对近 120 根 Bar 均线的乖离：<b class="newow-trend-reversal-explanation__red">红柱 = 站上均线</b>，<b class="newow-trend-reversal-explanation__green">绿柱 = 跌破均线</b>。零轴表示偏离为零。</p></div></div>
              <div class="newow-trend-reversal-explanation__item newow-trend-reversal-explanation__item--adjust"><span class="newow-trend-reversal-explanation__dot" aria-hidden="true"></span><div><strong>连续调整标记</strong><p>相邻 Bar 持续满足调整阈值，表示区间上沿附近的持续状态。</p></div></div>
              <div class="newow-trend-reversal-explanation__item newow-trend-reversal-explanation__item--rebound"><span class="newow-trend-reversal-explanation__dot" aria-hidden="true"></span><div><strong>连续反弹标记</strong><p>相邻 Bar 持续满足反弹阈值，表示区间下沿附近的持续状态。</p></div></div>
            </div>
            <div class="newow-trend-reversal-tips"><strong>读图提示</strong><p>标记只表示当前 Bar 满足公式阈值；标记消失表示下一根 Bar 已不满足阈值。</p></div>
            <div class="newow-trend-reversal-explanation__list newow-trend-reversal-explanation__list--followup">
              <div class="newow-trend-reversal-explanation__item newow-trend-reversal-explanation__item--main"><span class="newow-trend-reversal-explanation__dot" aria-hidden="true"></span><div><strong>配合主图</strong><p>黄蓝带状态来自主图，与本面板的反弹和调整标记相互独立。</p></div></div>
            </div>
            <p class="newow-trend-reversal-explanation__disclaimer">页面参考指标，不代表策略动作、成交或收益预测。</p>
          </div>
        </template>
        <template v-else><p>当前读数：{{ currentAuxiliaryResponse?.value?.component ?? '尚未取得' }}</p><p>含义与边界：{{ auxiliaryDisclosure.disclosure }}</p></template>
        <p v-if="auxiliaryReadiness" role="status">{{ auxiliaryReadiness.message }}</p><p v-else-if="currentAuxiliaryLifecycle !== 'ready'" role="status">{{ featureStateText('auxiliary') }}</p><details v-if="!isNiuwaIndicatorDialog"><summary>来源与原始事实</summary><p>{{ currentAuxiliaryResponse?.value?.formula_version ?? '暂无经确认的解释' }}</p><p>截至 {{ currentAuxiliaryResponse?.meta.as_of ?? '—' }}</p><p v-if="currentAuxiliaryError">技术原因 {{ newowErrorDisplay(currentAuxiliaryError) }}</p></details><button v-if="currentAuxiliaryError" @click="loadAuxiliaryForChart()">重试指标</button></template>
      <template v-else-if="dialogKind === 'cup_handle'"><p v-if="identity.frequency !== '1d' || identity.strategy !== 'trend'">杯柄仅适用于趋势日线。</p><p v-else-if="currentAuxiliaryError" role="status">杯柄事实读取失败：{{ newowErrorDisplay(currentAuxiliaryError) }}</p><template v-else-if="currentAuxiliaryResponse?.value?.component === 'cup_handle'"><p v-if="auxiliaryReadiness" role="status">{{ auxiliaryReadiness.message }}</p><template v-for="segment in currentAuxiliaryResponse.value.segments" :key="segment.segment_id"><NewowCupFactsPanel v-if="segment.status.status === 'ready'" :witnesses="Array.isArray(segment.data) ? segment.data : []" :physical-contract="segment.physical_contract" :segment-id="segment.segment_id" /><p v-else role="status">{{ segment.physical_contract }} · {{ segment.status.reason_code ?? '该区段杯柄事实暂不可用' }}</p></template></template><p v-else role="status">正在读取已确认杯柄事实…</p><button v-if="currentAuxiliaryError" @click="loadAuxiliaryForChart('cup_handle')">重试杯柄事实</button></template>
      <template v-else-if="dialogKind === 'explanation' && !sectionOpen('explanation')">
        <section class="newow-window-state" data-testid="newow-window-state" :aria-label="summary.status.historical ? '所示历史窗口状态' : '所示图表状态'">
          <h3>{{ summary.status.historical ? '所示历史窗口状态' : '所示图表状态' }}</h3>
          <p :title="summary.status.barEnd ?? undefined">截至 {{ shortNewowTime(summary.status.barEnd) }}</p>
          <p>{{ describeNewowState(summary.status.state, summary.status.historical) }}</p>
        </section>
        <p>当前发布阶段尚未开放跨周期综合解释。</p>
        <details><summary>来源与版本</summary><p>{{ deferredSectionReason('explanation') ?? 'NEWOW_SECTION_NOT_OPEN' }} · release_stage={{ capabilities.release_stage }}</p></details>
      </template>
      <template v-else-if="dialogKind === 'comparator' && !sectionOpen('comparator')"><p>当前发布阶段尚未开放页面比较说明。</p></template>
      <NewowExplanationPanel v-else :chart-state="summary.status" :response="explanationResponse" :lifecycle="loader.sections.explanation.state.value" :error="loader.sections.explanation.error.value" :comparator-response="comparatorResponse" :comparator-lifecycle="loader.sections.comparator.state.value" :comparator-error="loader.sections.comparator.error.value" :mode="dialogKind === 'comparator' ? 'comparator' : 'explanation'" />
      <button v-if="dialogKind === 'explanation' && loader.sections.explanation.error.value" @click="loader.loadExplanation">重试解释</button>
      <button v-if="dialogKind === 'comparator' && loader.sections.comparator.error.value" @click="loader.loadComparator">重试比较器</button>
    </NewowDetailDialog>
  </section>
</template>
<style scoped>
.newow-product-workspace { display:grid; min-width:0; gap:3px; }
.newow-product-workspace__comparison-controls { display:flex; flex-wrap:wrap; align-items:center; gap:8px; padding:4px 8px; font-size:11px; color:#667085; }
.newow-product-workspace__comparison-controls button { border:1px solid #ebedf0; border-radius:7px; background:#fff; color:#667085; min-height:32px; padding:0 12px; cursor:pointer; }
.newow-product-workspace__comparison-controls button[aria-pressed="true"] { color:#c2410c; border-color:#ff6b2c; background:#fff4ee; }
.newow-product-workspace__read-state { display:flex; flex-wrap:wrap; gap:4px 16px; color:#667085; font-size:11px; min-height:20px; align-items:center; padding:0 8px; }
.newow-product-workspace__unavailable-chart { min-height:clamp(580px,70vh,920px); box-sizing:border-box; }
.newow-summary { display:grid; gap:8px; padding:8px 12px; border:1px solid #e9edf2; border-radius:12px; background:#fff; box-shadow:0 8px 24px #15223808; }
.newow-product-workspace__snapshot-controls { display:flex; flex-wrap:wrap; align-items:center; gap:12px; color:#667085; font-size:12px; }
.newow-summary__main,.newow-summary__facts { display:flex; align-items:center; flex-wrap:wrap; gap:12px 20px; }
.newow-summary__scope { font-size:10px; font-weight:400; color:#667085; margin-left:6px; }
.newow-summary__main > strong { font-size:14px; }
.newow-status { font-size:16px; font-weight:650; }
.newow-summary__identity { color:#667085; font-size:12px; }
.newow-summary__facts { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); font-size:12px; color:#667085; }.newow-summary__facts > span { min-width:0; padding:4px 8px; line-height:1.5; border-radius:8px; background:#f8fafc; }
.newow-summary button,.newow-product-workspace__auxiliary-controls button,.newow-product-workspace__research > button { border:0; background:#fff; color:inherit; padding:4px 12px; }
.newow-status { display:flex; align-items:center; gap:8px; }
.newow-status span { border-radius:50%; width:24px; height:24px; display:grid; place-items:center; background:#f3f4f6; }
.newow-status[data-state="BUILD"] { color:#ff403a; }.newow-status[data-state="HOLD"] { color:#ff6b2c; }.newow-status[data-state="CLEAR"] { color:#22b95d; }.newow-status[data-state="FLAT"] { color:#365af5; }
.newow-price small { font-size:11px; }.newow-summary__evidence { margin-left:auto; border:1px solid var(--gy-border) !important; border-radius:var(--gy-radius-md); min-height:36px; }
.newow-product-workspace__auxiliary-controls { display:flex; align-items:center; min-width:0; border-top:1px solid #ebedf0; font-size:12px; }
.newow-product-workspace__auxiliary-tabs { display:flex; flex:1 1 auto; min-width:0; align-items:center; overflow-x:auto; white-space:nowrap; }
.newow-product-workspace__auxiliary-controls button { flex:none; min-height:36px; padding:0 10px; }
.newow-product-workspace__auxiliary-controls button[aria-pressed="true"] { color:#ff6b2c; border-bottom:2px solid #ff6b2c; }
.newow-product-workspace__indicator-help { flex:none; min-height:25px; margin:0 8px 0 12px; padding:2px 10px; border:1px solid #1677ff; border-radius:16px; background:#fff; color:#1677ff; font-size:12px; line-height:18px; cursor:pointer; }
.newow-product-workspace__auxiliary-legend-row { display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:12px; min-height:36px; padding:4px 10px 16px; font-size:12px; }
.newow-product-workspace__auxiliary-legend-row > .newow-product-workspace__indicator-help { margin-left:auto; flex-shrink:0; }
.newow-product-workspace__indicator-help:hover { background:#f2f7ff; }
.newow-product-workspace__indicator-help:focus-visible { outline:2px solid #1677ff; outline-offset:2px; }
.newow-macd-legend { padding:0 6px; color:#667085; }.newow-macd-legend span:first-child { color:#ff6b2c; }.newow-macd-legend span:last-child { color:#365af5; }
.newow-mirror-legend { display:flex; align-items:center; gap:10px; width:100%; box-sizing:border-box; min-height:22px; overflow-x:auto; padding:0 10px; color:#667085; font-size:11px; line-height:16px; white-space:nowrap; background:#fff; }
.newow-mirror-legend__title { color:#667085; }
.newow-mirror-legend__item { display:inline-flex; align-items:center; gap:4px; }
.newow-mirror-legend__item i { display:inline-block; flex:0 0 8px; width:8px; height:8px; border-radius:2px; }
.newow-mirror-legend__item b { font-size:10px; line-height:1; }
.newow-mirror-legend__item .newow-mirror-legend__stack { background:linear-gradient(#00ff00 50%,#ff00ff 50%); }
.newow-niuwa-explanation { color:#55595d; font-size:12.5px; line-height:1.48; }
.newow-niuwa-explanation p { margin:0; }
.newow-niuwa-explanation__dot { display:block; flex:0 0 10px; width:10px; height:10px; margin-top:4px; border-radius:50%; background:var(--dot); }
.newow-niuwa-explanation__dot--stack { background:linear-gradient(#00ee36 50%,#ff00ff 50%); }
.newow-niuwa-explanation__red { color:#ff403a; }.newow-niuwa-explanation__green { color:#2dbb60; }.newow-niuwa-explanation__blue { color:#0878f9; }.newow-niuwa-explanation__yellow { color:#ffcc00; }.newow-niuwa-explanation__orange { color:#ff9500; }.newow-niuwa-explanation__purple { color:#9933ff; }.newow-niuwa-explanation__magenta { color:#ff00ff; }.newow-niuwa-explanation__lime { color:#00e638; }.newow-niuwa-explanation__gold { color:#ffcc66; }.newow-niuwa-explanation__muted { color:#8d9096; }
.newow-niuwa-explanation__card { border-radius:14px; background:linear-gradient(120deg,#f3f7fe,#d7e2f4); }
.newow-niuwa-explanation__card--mirror { margin:4px 0 16px; padding:20px 14px; text-align:center; font-size:14px; font-weight:700; line-height:1.7; }
.newow-niuwa-explanation__card--mirror > strong { display:block; margin-bottom:8px; font-size:15px; }
.newow-niuwa-explanation__card--mirror p + p { margin-top:4px; }
.newow-niuwa-explanation__rows { display:grid; gap:12px; }
.newow-niuwa-explanation__row { display:flex; align-items:start; gap:9px; }
.newow-niuwa-explanation__row strong { font-size:13px; }
.newow-niuwa-explanation__card--energy { margin:4px 0 16px; padding:18px 16px; text-align:center; font-weight:700; line-height:1.65; }
.newow-niuwa-explanation__card--energy p:first-child { font-size:13.5px; }
.newow-niuwa-explanation__card--energy p:nth-child(2) { margin:9px 0; font-size:13px; }
.newow-niuwa-explanation__card--energy small { color:#898d94; font-size:11px; }
.newow-niuwa-explanation__energy-rows { display:grid; gap:14px; }
.newow-niuwa-explanation__energy-rows > div { display:grid; grid-template-columns:102px minmax(0,1fr); gap:7px; align-items:start; }
.newow-niuwa-explanation__energy-rows strong { padding-top:2px; font-size:13px; line-height:1.35; }
.newow-niuwa-explanation__signal-rows { display:grid; gap:14px; margin-top:16px; }
.newow-niuwa-explanation__signal-rows > div { display:grid; grid-template-columns:10px 105px minmax(0,1fr); gap:8px; align-items:start; }
.newow-niuwa-explanation__signal-rows strong { font-size:13px; line-height:1.35; }
.newow-niuwa-explanation__practical { display:grid; grid-template-columns:10px 1fr; gap:0 8px; margin-top:15px; }
.newow-niuwa-explanation__practical strong { color:#0878f9; font-size:13px; }
.newow-niuwa-explanation__practical p { grid-column:2; }
.newow-niuwa-explanation__cycle { margin:4px 0 12px; padding:16px 10px; border-radius:12px; background:#1c1d2e; text-align:center; }
.newow-niuwa-explanation__cycle small { color:#9899a2; font-size:11px; }
.newow-niuwa-explanation__cycle p { display:flex; align-items:center; justify-content:center; gap:4px; margin-top:10px; white-space:nowrap; font-size:13px; }
.newow-niuwa-explanation__cycle span { color:#777985; }
.newow-niuwa-explanation__verse { margin-bottom:14px; padding:16px 12px; border-left:4px solid #ffcc00; border-radius:11px; background:linear-gradient(110deg,#243c60,#2b1f49); color:#fff; text-align:center; font-weight:700; }
.newow-niuwa-explanation__verse > strong { color:#ffcc00; font-size:13px; }
.newow-niuwa-explanation__verse p { margin-top:10px; font-size:12.5px; line-height:1.8; }
.newow-niuwa-explanation__verse em { color:#ff9500; font-style:normal; }.newow-niuwa-explanation__verse em.newow-niuwa-explanation__red { color:#ff403a; }.newow-niuwa-explanation__verse em.newow-niuwa-explanation__muted { color:#999ba2; }
.newow-niuwa-explanation__core { margin-bottom:20px; padding:16px 14px; border:1px solid #ffd591; border-radius:10px; background:#fff9ef; }
.newow-niuwa-explanation__core > strong { color:#c77d00; font-size:13px; }
.newow-niuwa-explanation__core p { margin-top:9px; line-height:1.75; }
.newow-niuwa-explanation__control-rows { display:grid; gap:18px; padding:0 10px; }
.newow-niuwa-explanation__control-rows > div { display:flex; gap:9px; align-items:start; }
.newow-niuwa-explanation__control-rows strong { font-size:13px; }
.newow-niuwa-explanation__note { margin-top:16px !important; color:#898c92; font-size:10.5px; text-align:center; }
.newow-trend-reversal-legend { display:grid; gap:4px; padding:4px 10px; font-size:11px; color:#8a909b; background:#fff; }.newow-trend-reversal-legend > div { display:flex; align-items:center; gap:12px; min-height:16px; }.newow-trend-reversal-legend strong { color:#383d48; }.newow-trend-reversal-legend__keys { display:inline-flex; gap:12px; margin-left:auto; }.newow-trend-reversal-legend i { display:inline-block; width:8px; height:8px; border-radius:1px; }.newow-trend-reversal-legend__bias { background:linear-gradient(#ff403a 50%,#30b458 50%); }
.newow-trend-reversal-explanation { font-size:12px; line-height:1.35; color:#56595d; }
.newow-trend-reversal-explanation__intro { margin:0 0 14px; color:#888b91; text-align:center; font-size:12.5px; font-weight:600; line-height:1.35; }
.newow-trend-reversal-explanation__list { display:grid; gap:10px; }
.newow-trend-reversal-explanation__item { display:grid; grid-template-columns:10px minmax(0,1fr); gap:10px; align-items:start; }
.newow-trend-reversal-explanation__dot { width:10px; height:10px; margin-top:4px; border-radius:50%; background:currentColor; }
.newow-trend-reversal-explanation__item strong { display:block; font-size:13.5px; font-weight:750; line-height:1.35; }
.newow-trend-reversal-explanation__item p { margin:2px 0 0; }
.newow-trend-reversal-explanation__item--adjust { color:#55bdee; }.newow-trend-reversal-explanation__item--adjust strong { color:#0878f9; }.newow-trend-reversal-explanation__item--adjust p { color:#56595d; }
.newow-trend-reversal-explanation__item--rebound { color:#ff9500; }.newow-trend-reversal-explanation__item--rebound p { color:#56595d; }
.newow-trend-reversal-explanation__item--bias { color:#606367; }.newow-trend-reversal-explanation__item--bias .newow-trend-reversal-explanation__dot { background:linear-gradient(#ff403a 50%,#30b458 50%); }.newow-trend-reversal-explanation__item--bias p { color:#56595d; }
.newow-trend-reversal-explanation__item--main { color:#606367; }.newow-trend-reversal-explanation__item--main .newow-trend-reversal-explanation__dot { background:linear-gradient(#ffcc00 50%,#0878f9 50%); }.newow-trend-reversal-explanation__item--main p { color:#56595d; }
.newow-trend-reversal-explanation__red { color:#ff403a; }.newow-trend-reversal-explanation__green { color:#30b458; }.newow-trend-reversal-explanation__blue { color:#0878f9; }.newow-trend-reversal-explanation__muted { color:#898c92; }
.newow-trend-reversal-tips { margin:16px 0 18px; padding:16px; border-radius:14px; background:linear-gradient(120deg,#f2f6fd,#d7e2f4); line-height:1.4; }
.newow-trend-reversal-tips > strong { display:block; margin-bottom:8px; color:#858990; font-size:12px; }
.newow-trend-reversal-tips p { margin:5px 0 0; color:#363a41; font-size:13px; font-weight:700; line-height:1.45; }
.newow-trend-reversal-explanation__list--followup { gap:12px; }
.newow-trend-reversal-explanation__disclaimer { margin:18px 0 0; color:#898c92; text-align:center; font-size:12px; }
.newow-product-workspace__notice { color:#b45309; }
.newow-product-workspace__reference-message { margin:0; padding:8px; color:#b45309; border:1px solid var(--gy-border); border-radius:7px; background:#fff; }
.newow-window-state { display:grid; gap:6px; padding:12px; border:1px solid var(--gy-border); border-radius:7px; }
.newow-window-state h3,.newow-window-state p { margin:0; }
.newow-window-state h3 { font-size:14px; }
pre { white-space:pre-wrap; overflow-wrap:anywhere; }
@media(max-width:640px) { .newow-product-workspace__auxiliary-controls button,.newow-summary__evidence { min-height:44px; }.newow-summary { padding:12px; }.newow-summary__facts { grid-template-columns:1fr 1fr; }.newow-summary__evidence { margin-left:0; } }
</style>
