<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { useNewowProduct } from '@/composables/useNewowProduct'
import type { MarketDetailIdentity } from '@/types/marketDetail'
import type { NewowAuxiliaryComponent, NewowProductAction, NewowProductCapabilities, NewowProductSection, NewowProductStrategy, NewowResourceLifecycle, NewowProductSectionResponse, NewowReferenceTrade } from '@/types/newowProduct'
import { resolveNewowReferenceLocate } from '@/utils/newowProductViewModel'
import { describeNewowState, projectNewowDetail, newowDisplayLabel, shortNewowTime, referencePercentDisplay } from '@/utils/newowDetailPresentation'
import { buildNewowProductChartModel, buildNewowAuxiliaryDisclosure, describeNewowProductAction, newowChartSnapshotKey, newowInitialClearLabel } from './newowProductChartPrimitives'
import { formatChartTimeInShanghai } from '@/utils/barTime'
import { newowErrorDisplay } from '@/utils/newowDataDiagnostics'
import { formatMarketDecimal } from '@/utils/marketDisplay'
import NewowProductChartStage from './NewowProductChartStage.vue'
import NewowExplanationPanel from './NewowExplanationPanel.vue'
import NewowReferencePanel from './NewowReferencePanel.vue'
import NewowDetailDialog from './NewowDetailDialog.vue'
import NewowCupFactsPanel from './NewowCupFactsPanel.vue'
import MarketDetailUnavailable from '@/components/market/detail/MarketDetailUnavailable.vue'
const props = defineProps<{ identity: MarketDetailIdentity; capabilities: NewowProductCapabilities }>()
const emit = defineEmits<{ 'focus-resolved': [barEnd: string]; 'snapshot-mode': [asOf: string | null]; 'daily-snapshot-as-of': [asOf: string | null]; 'weekly-quote-context': [context: { asOf: string | null; physicalContract: string | null }]; 'refresh-current': [] }>()
const identity = computed(() => props.identity)
const identityKey = computed(() => [props.identity.view, props.identity.symbol, props.identity.strategy, props.identity.frequency].join(':'))
const selectedStrategy = computed(() => props.identity.strategy as NewowProductStrategy)
const loader = useNewowProduct({ identity })
const selectedSignalId = ref<string | null>(null)
const selectedHintId = ref<string | null>(null)
const selectedAuxiliary = ref<NewowAuxiliaryComponent>('macd')
const dialogKind = ref<'explanation' | 'action' | 'hint' | 'indicator' | 'comparator' | 'cup_handle' | null>(null)
const locateMessage = ref<string | null>(null)
const chartRegion = ref<HTMLElement | null>(null)
const referenceRegion = ref<HTMLElement | null>(null)
const sectionOpen = (section: NewowProductSection) => (props.capabilities.open_sections as readonly string[]).includes(section)
const deferredSectionReason = (section: NewowProductSection) => props.capabilities.deferred_sections.find(item => item.section === section)?.reason_code ?? null
const chartResponse = computed(() => (
  loader.sections.chart.data.value?.section === 'chart'
    ? loader.sections.chart.data.value as NewowProductSectionResponse<'chart'>
    : null
))
const chartModel = computed(() => chartResponse.value === null ? null : buildNewowProductChartModel(chartResponse.value))
const selectedHint = computed(() => chartModel.value?.hints.find(hint => hint.id === selectedHintId.value) ?? null)
const selectedAction = computed(() => chartModel.value?.actions.find((action) => action.id === selectedSignalId.value) ?? null)
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
const auxiliaryDisclosure = computed(() => buildNewowAuxiliaryDisclosure(selectedAuxiliary.value, props.identity.frequency as '1w' | '1d' | '60m', currentAuxiliaryLifecycle.value))
const auxiliaryOptions = [{ id: 'macd', label: 'MACD' }, { id: 'zhaoyao_mirror', label: '照妖镜' }, { id: 'up_down_energy', label: '涨跌动能' }, { id: 'main_force_control', label: '主力控盘' }] as const
const historicalAsOfLabel = computed(() => loader.historicalSnapshot.value ? formatChartTimeInShanghai(loader.historicalSnapshot.value.as_of) : '')
const dialogTitle = computed(() => ({ explanation: '策略解释', action: '历史主动作事实', hint: '历史过程提示', indicator: '指标解读', comparator: '页面比较说明', cup_handle: '杯柄说明' }[dialogKind.value ?? 'explanation']))
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
  if (kind === 'cup_handle' && props.identity.frequency === '1d') await loadAuxiliaryForChart('cup_handle')
}
function closeDialog() {
  const wasCup = dialogKind.value === 'cup_handle'
  dialogKind.value = null
  if (wasCup) void loadAuxiliaryForChart()
  retainedPane.value = null
}
function selectSignal(signalId: string) {
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
async function locateReferenceTrade(trade: NewowReferenceTrade): Promise<void> {
  locateMessage.value = null
  let target = resolveNewowReferenceLocate(trade, chartResponse.value, loader.referenceChartCompatible.value)
  if (target.kind === 'request_display_window') {
    await loader.loadChart(target.displayWindow)
    target = resolveNewowReferenceLocate(trade, chartResponse.value, loader.referenceChartCompatible.value)
  }
  if (target.kind !== 'loaded') {
    locateMessage.value = `无法按精确信号 ${target.signalId} / ${target.barEnd} 定位；没有跳转到邻近日期。`
    return
  }
  selectedSignalId.value = target.signalId
  locateMessage.value = `已按精确信号 ${target.signalId} / ${target.barEnd} 定位。`
  await nextTick()
  chartRegion.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function resolveSignalFocus(signalId: string): void {
  const action = chartModel.value?.actions.find((item) => item.id === signalId)
  if (action !== undefined && props.identity.focusBarEnd === action.barEnd) emit('focus-resolved', action.barEnd)
}
function refreshCurrent(): void { loader.refreshCurrent(); emit('refresh-current') }


watch(identityKey, async () => {
  selectedSignalId.value = null; selectedHintId.value = null; retainedPane.value = null; selectedAuxiliary.value = 'macd'; dialogKind.value = null; locateMessage.value = null
}, { flush: 'sync' })
watch(loader.historicalSnapshot, async () => {
  emit('snapshot-mode', loader.historicalSnapshot.value?.as_of ?? null)
  selectedSignalId.value = null; selectedHintId.value = null; retainedPane.value = null
  dialogKind.value = null; locateMessage.value = null
}, { flush: 'sync' })
watch(loader.dailySnapshot, snapshot => emit('daily-snapshot-as-of', snapshot?.as_of ?? null), { immediate: true, flush: 'sync' })
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
onBeforeUnmount(() => loader.dispose())
</script>

<template>
  <section class="newow-product-workspace" data-detail-workspace="newow" :data-strategy="identity.strategy" :data-frequency="identity.frequency" :data-chart-state="loader.sections.chart.state.value" :data-auxiliary-state="loader.sections.auxiliary.state.value">
    <section class="newow-summary" aria-label="策略概览">
      <div class="newow-summary__main">
        <strong>策略概览</strong>
        <span class="newow-status" :data-state="summary.status.state"><span>{{ ({ BUILD: '▲', HOLD: '✓', CLEAR: '▼', FLAT: '×', UNAVAILABLE: '?' })[summary.status.state] }}</span>{{ summary.status.label }}</span>
        <span class="newow-summary__identity">{{ summaryContract }} · 截至 {{ summaryAsOf }}</span>
        <span class="newow-price newow-price--target" :title="summary.target?.bar_end">目标参考 {{ formatMarketDecimal(summary.target?.display_value) }}<small v-if="summary.target"> · {{ shortNewowTime(summary.target.bar_end) }}</small><small v-else> · {{ !sectionOpen('explanation') ? '未开放' : loader.sections.explanation.state.value === 'loading' ? '读取中' : '不可用 / 证据不足' }}</small></span>
        <span class="newow-price newow-price--absorb" :title="summary.absorb?.bar_end">吸筹参考 {{ formatMarketDecimal(summary.absorb?.display_value) }}<small v-if="summary.absorb"> · {{ shortNewowTime(summary.absorb.bar_end) }}</small><small v-else> · {{ !sectionOpen('explanation') ? '未开放' : loader.sections.explanation.state.value === 'loading' ? '读取中' : '不可用 / 证据不足' }}</small></span>
        <button class="newow-summary__evidence" @click="openDialog('explanation')">查看依据</button>
      </div>
      <div class="newow-summary__facts">
        <span :title="summary.status.barEnd ?? undefined">{{ summary.status.historical ? '历史窗口最近主动作' : '已读取窗口最近主动作' }} <button v-if="summary.latestAction" :title="summary.latestAction.bar_end" @click="selectSignal(summary.latestAction.signal_id)">{{ summaryActionLabel(summary.latestAction) }} · {{ formatMarketDecimal(summary.latestAction.reference_price) }} · {{ shortNewowTime(summary.latestAction.bar_end) }}</button><template v-else>—</template></span>
        <span>当前参考交易 {{ openReferenceText }}</span>
        <span>参考浮动 <span class="newow-return-badge" :data-direction="referencePercentDisplay(summary.openReference?.mark_change_pct).direction">{{ referencePercentDisplay(summary.openReference?.mark_change_pct).text }}</span> · {{ shortNewowTime(summary.openReference?.mark_bar_end) }}</span>
        <span :title="summary.status.barEnd ?? undefined">{{ summary.status.historical ? '历史窗口状态截至' : '已读取状态截至' }} {{ shortNewowTime(summary.status.barEnd) }}</span>
      </div>
    </section>
    <MarketDetailUnavailable v-if="chartResponse === null && loader.sections.chart.state.value !== 'loading' && !loader.dailyLoading.value" title="主图事实不可用" :message="`${newowErrorDisplay(loader.sections.chart.error.value) ?? '当前主图没有可显示的已验证数值'}；参考与解释保持独立状态。`" :technical-detail="loader.sections.chart.error.value" recovery-label="刷新日线" :can-recover="true" :can-return-market="false" @recover="loader.refreshCurrent()" />
    <div v-else ref="chartRegion" class="newow-product-workspace__chart"><NewowProductChartStage :response="chartResponse" :strategy="selectedStrategy" :selected-signal-id="selectedSignalId" :loading="loader.sections.chart.state.value === 'loading'" :has-more-before="chartModel?.nextBefore != null || chartResponse?.value?.next_older_window != null" :auxiliary-response="currentAuxiliaryResponse" :auxiliary-lifecycle="currentAuxiliaryLifecycle" :auxiliary-error="currentAuxiliaryError" @load-earlier="loader.loadNextChartPage" @select-signal="selectSignal" @focus-resolved="resolveSignalFocus" @select-hint="selectHint" @explain-main="openDialog('explanation')" @explain-auxiliary="openDialog('indicator')">
    <template #auxiliary-controls>
    <section class="newow-product-workspace__auxiliary" aria-label="Newow 辅助图层">
      <div class="newow-product-workspace__auxiliary-controls">
        <button v-for="option in auxiliaryOptions" :key="option.id" :aria-pressed="selectedAuxiliary === option.id" @click="toggleAuxiliary(option.id)">{{ option.label }}</button>
        <span v-if="selectedAuxiliary === 'macd'" class="newow-macd-legend"><span>DIF</span> / <span>DEA</span></span>
        <button aria-label="指标解读" @click="openDialog('indicator')">ⓘ</button>
        <button @click="openDialog('cup_handle')">杯柄说明</button>
      </div>
      <p v-if="currentAuxiliaryError" role="status">{{ currentAuxiliaryError }} · 辅助图层不可用 <button @click="loadAuxiliaryForChart()">重试指标</button></p>
    </section>
    </template>
    </NewowProductChartStage></div>
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
        <button @click="refreshCurrent">刷新当前</button>
        <span v-if="loader.historicalError.value" role="status">{{ newowErrorDisplay(loader.historicalError.value) }}</span>
      </template>
    </div>
    <section ref="referenceRegion" class="newow-product-workspace__research" aria-label="Newow 参考与解释" tabindex="-1">
      <button @click="openDialog('comparator')">页面比较说明</button>
      <NewowReferencePanel :key="identityKey" :chart-lifecycle="loader.sections.chart.state.value" :current-chart-window="loader.currentChartWindow.value" :response="referenceResponse" :chart-response="chartResponse" :cross-section-compatible="loader.referenceChartCompatible.value" :lifecycle="loader.sections.reference.state.value" :error="loader.sections.reference.error.value" :selected-signal-id="selectedSignalId" :locate-message="locateMessage" :loading-page="loader.sections.reference.state.value === 'loading'" @reload="loader.loadReference" @retry="loader.loadReference()" @load-more="loader.loadNextReferencePage" @locate="locateReferenceTrade" />
    </section>
    <NewowDetailDialog :open="dialogKind !== null" :wide="dialogKind === 'explanation' || dialogKind === 'comparator' || dialogKind === 'cup_handle'" :title="dialogTitle" :identity-key="identityKey" @close="closeDialog">
      <p>{{ identity.symbol.toUpperCase() }} · {{ newowDisplayLabel(identity.strategy ?? 'UNAVAILABLE') }} · {{ identity.frequency }} · {{ dialogKind === 'action' ? selectedAction?.physicalContract : dialogKind === 'hint' ? selectedHint?.physicalContract : chartResponse?.value?.bars.at(-1)?.physical_contract ?? '—' }}</p>
      <template v-if="dialogKind === 'hint'">
        <p v-if="selectedHint">{{ newowDisplayLabel(selectedHint.kind) }} · {{ formatMarketDecimal(selectedHint.anchorPrice) }} · {{ shortNewowTime(selectedHint.barEnd) }}</p>
        <p>仅为所选历史过程提示，不代表主动作或账户成交。</p>
        <details v-if="selectedHint"><summary>来源与原始事实</summary><p>{{ selectedHint.id }} · {{ selectedHint.barEnd }}</p><p>known_at {{ selectedHint.confirmedAt }} · sequence {{ selectedHint.sequence ?? '—' }}</p><p>owner {{ selectedHint.physicalContract }} · {{ selectedHint.segmentId }}</p><p>来源 {{ selectedHint.sourceIdentity ?? '—' }} · 响应公式 {{ selectedHint.formulaVersions.join(' / ') }}</p><p>anchor_price {{ selectedHint.anchorPrice ?? '—' }}</p></details>
      </template>
      <template v-else-if="dialogKind === 'action'">
        <p v-if="selectedAction">历史主动作 {{ selectedActionDescription?.label }} · {{ formatMarketDecimal(selectedAction.referencePrice) }} · {{ shortNewowTime(selectedAction.barEnd) }}</p>
        <p>{{ selectedActionDescription?.explanation ?? '仅为所选历史主动作事实，不代表账户成交。' }}</p>
        <details><summary>来源与关联 Hint</summary><p>{{ selectedSignalId }} · {{ selectedAction?.barEnd }}</p><p v-for="hint in chartResponse?.value?.hints.filter(hint => chartResponse?.value?.frames.find(frame => frame.bar_end === selectedAction?.barEnd)?.hint_ids.includes(hint.hint_id)) ?? []" :key="hint.hint_id">{{ hint.kind }} · {{ hint.hint_id }} · known_at {{ hint.known_at }} · {{ hint.anchor_price ?? '—' }}</p></details>
      </template>
      <template v-else-if="dialogKind === 'indicator'"><h3>{{ auxiliaryDisclosure.title }}</h3><p>当前读数：{{ currentAuxiliaryResponse?.value?.component ?? '尚未取得' }}</p><p>含义与边界：{{ auxiliaryDisclosure.disclosure }}</p><p v-if="currentAuxiliaryLifecycle !== 'ready'" role="status">{{ featureStateText('auxiliary') }}</p><details><summary>来源与原始事实</summary><p>{{ currentAuxiliaryResponse?.value?.formula_version ?? '暂无经确认的解释' }}</p><p>截至 {{ currentAuxiliaryResponse?.meta.as_of ?? '—' }}</p><p v-if="currentAuxiliaryError">技术原因 {{ newowErrorDisplay(currentAuxiliaryError) }}</p></details><button v-if="currentAuxiliaryError" @click="loadAuxiliaryForChart()">重试指标</button></template>
      <template v-else-if="dialogKind === 'cup_handle'"><p v-if="identity.frequency !== '1d'">杯柄仅适用于 1d。</p><p v-else-if="currentAuxiliaryError" role="status">杯柄事实读取失败：{{ newowErrorDisplay(currentAuxiliaryError) }}</p><template v-else-if="currentAuxiliaryResponse?.value?.component === 'cup_handle'"><template v-for="segment in currentAuxiliaryResponse.value.segments" :key="segment.segment_id"><NewowCupFactsPanel v-if="segment.status.status === 'ready'" :witnesses="Array.isArray(segment.data) ? segment.data : []" :physical-contract="segment.physical_contract" :segment-id="segment.segment_id" /><p v-else role="status">{{ segment.physical_contract }} · {{ segment.status.reason_code ?? '该区段杯柄事实暂不可用' }}</p></template></template><p v-else role="status">正在读取已确认杯柄事实…</p><button v-if="currentAuxiliaryError" @click="loadAuxiliaryForChart('cup_handle')">重试杯柄事实</button></template>
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
.newow-summary { display:grid; gap:8px; padding:8px; border:1px solid #e9edf2; border-radius:12px; background:#fff; box-shadow:0 8px 24px #15223808; }
.newow-product-workspace__snapshot-controls { display:flex; align-items:center; gap:12px; color:#667085; font-size:12px; }
.newow-summary__main,.newow-summary__facts { display:flex; align-items:center; flex-wrap:wrap; gap:12px 20px; }
.newow-summary__identity { color:#667085; font-size:12px; }
.newow-summary__facts { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); font-size:12px; color:#667085; }.newow-summary__facts > span { min-width:0; padding:4px 8px; border-radius:8px; background:#f8fafc; }
.newow-summary button,.newow-product-workspace__auxiliary-controls button,.newow-product-workspace__research > button { border:0; background:#fff; color:inherit; padding:4px 12px; }
.newow-status { display:flex; align-items:center; gap:8px; }
.newow-status span { border-radius:50%; width:24px; height:24px; display:grid; place-items:center; background:#f3f4f6; }
.newow-status[data-state="BUILD"] { color:#ff403a; }.newow-status[data-state="HOLD"] { color:#ff6b2c; }.newow-status[data-state="CLEAR"] { color:#22b95d; }.newow-status[data-state="FLAT"] { color:#365af5; }
.newow-price { padding:3px 8px; border-radius:7px; }.newow-price--target { color:#dd4c15; background:#fff4ee; }.newow-price--absorb { color:#365af5; background:#eef3ff; }
.newow-price small { font-size:11px; }.newow-summary__evidence { margin-left:auto; border:1px solid var(--gy-border) !important; border-radius:var(--gy-radius-md); min-height:36px; }
.newow-product-workspace__auxiliary-controls { display:flex; flex-wrap:nowrap; overflow-x:auto; white-space:nowrap; align-items:center; border-top:1px solid #ebedf0; gap:0; font-size:12px; }
.newow-product-workspace__auxiliary-controls button { min-height:36px; padding:0 10px; }
.newow-product-workspace__auxiliary-controls button[aria-pressed="true"] { color:#ff6b2c; border-bottom:2px solid #ff6b2c; }
.newow-macd-legend { padding:0 6px; color:#667085; }.newow-macd-legend span:first-child { color:#ff6b2c; }.newow-macd-legend span:last-child { color:#365af5; }
.newow-product-workspace__notice { color:#b45309; }
.newow-window-state { display:grid; gap:6px; padding:12px; border:1px solid var(--gy-border); border-radius:7px; }
.newow-window-state h3,.newow-window-state p { margin:0; }
.newow-window-state h3 { font-size:14px; }
pre { white-space:pre-wrap; overflow-wrap:anywhere; }
@media(max-width:640px) { .newow-product-workspace__auxiliary-controls button,.newow-summary__evidence { min-height:44px; }.newow-summary { padding:12px; }.newow-summary__facts { grid-template-columns:1fr 1fr; }.newow-summary__evidence { margin-left:0; } }
</style>
