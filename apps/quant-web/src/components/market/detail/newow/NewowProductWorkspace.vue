<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { useNewowProduct } from '@/composables/useNewowProduct'
import type { MarketDetailIdentity } from '@/types/marketDetail'
import type { NewowAuxiliaryComponent, NewowProductStrategy, NewowResourceLifecycle, NewowProductSectionResponse, NewowReferenceTrade } from '@/types/newowProduct'
import { resolveNewowReferenceLocate } from '@/utils/newowProductViewModel'
import { projectNewowDetail, newowDisplayLabel, shortNewowTime, referencePercentDisplay } from '@/utils/newowDetailPresentation'
import { buildNewowProductChartModel, buildNewowAuxiliaryDisclosure, newowChartSnapshotKey } from './newowProductChartPrimitives'
import { formatChartTimeInShanghai } from '@/utils/barTime'
import NewowProductChartStage from './NewowProductChartStage.vue'
import NewowExplanationPanel from './NewowExplanationPanel.vue'
import NewowReferencePanel from './NewowReferencePanel.vue'
import NewowDetailDialog from './NewowDetailDialog.vue'
const props = defineProps<{ identity: MarketDetailIdentity }>()
const emit = defineEmits<{ 'focus-resolved': [barEnd: string]; 'snapshot-mode': [asOf: string | null]; 'refresh-current': [] }>()
const identity = computed(() => props.identity)
const identityKey = computed(() => [props.identity.view, props.identity.symbol, props.identity.strategy, props.identity.frequency].join(':'))
const selectedStrategy = computed(() => props.identity.strategy as NewowProductStrategy)
const loader = useNewowProduct({ identity })
const selectedSignalId = ref<string | null>(null)
const selectedHintId = ref<string | null>(null)
const selectedAuxiliary = ref<NewowAuxiliaryComponent>('macd')
const detailsOpen = ref(false)
const dialogKind = ref<'explanation' | 'action' | 'hint' | 'indicator' | 'comparator' | 'cup_handle' | null>(null)
const locateMessage = ref<string | null>(null)
const referenceAnchor = ref<HTMLElement | null>(null)
let observer: IntersectionObserver | null = null
const chartResponse = computed(() => (
  loader.sections.chart.data.value?.section === 'chart'
    ? loader.sections.chart.data.value as NewowProductSectionResponse<'chart'>
    : null
))
const chartModel = computed(() => chartResponse.value === null ? null : buildNewowProductChartModel(chartResponse.value))
const selectedHint = computed(() => chartModel.value?.hints.find(hint => hint.id === selectedHintId.value) ?? null)
const selectedAction = computed(() => chartModel.value?.actions.find((action) => action.id === selectedSignalId.value) ?? null)
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
// A display-only retention of the accepted selected pane while the same loader serves the cup dialog.
const retainedPane = shallowRef<{ response: NewowProductSectionResponse<'auxiliary'> | null; lifecycle: NewowResourceLifecycle; error: string | null; proof: string | null; component: NewowAuxiliaryComponent } | null>(null)
const retainedPaneCompatible = computed(() => dialogKind.value === 'cup_handle' && retainedPane.value !== null
  && retainedPane.value.proof !== null && retainedPane.value.proof === newowChartSnapshotKey(chartResponse.value)
  && retainedPane.value.component === selectedAuxiliary.value)
const currentAuxiliaryResponse = computed(() => {
  const response = retainedPaneCompatible.value ? retainedPane.value!.response : auxiliaryResponse.value
  return response?.value?.component === selectedAuxiliary.value && newowChartSnapshotKey(response) !== null
    && newowChartSnapshotKey(response) === newowChartSnapshotKey(chartResponse.value) ? response : null
})
const currentAuxiliaryLifecycle = computed(() => loader.sections.auxiliary.state.value === 'input_conflict' ? 'input_conflict'
  : retainedPaneCompatible.value ? retainedPane.value!.lifecycle
  : dialogKind.value === 'cup_handle' ? 'not_requested' : loader.sections.auxiliary.state.value)
const currentAuxiliaryError = computed(() => loader.sections.auxiliary.state.value === 'input_conflict' ? loader.sections.auxiliary.error.value
  : retainedPaneCompatible.value ? retainedPane.value!.error
  : dialogKind.value === 'cup_handle' ? null : loader.sections.auxiliary.error.value)

const summary = computed(() => projectNewowDetail(chartResponse.value, loader.sections.chart.state.value,
  explanationResponse.value, loader.sections.explanation.state.value, loader.explanationChartCompatible.value,
  referenceResponse.value, loader.sections.reference.state.value, loader.referenceChartCompatible.value))
const auxiliaryDisclosure = computed(() => buildNewowAuxiliaryDisclosure(selectedAuxiliary.value, props.identity.frequency as '1w' | '1d' | '60m', currentAuxiliaryLifecycle.value))
const auxiliaryOptions = [{ id: 'macd', label: 'MACD' }, { id: 'zhaoyao_mirror', label: '照妖镜' }, { id: 'up_down_energy', label: '涨跌动能' }, { id: 'main_force_control', label: '主力控盘' }] as const
const historicalAsOfLabel = computed(() => loader.historicalSnapshot.value ? formatChartTimeInShanghai(loader.historicalSnapshot.value.as_of) : '')
const dialogTitle = computed(() => ({ explanation: '策略解释', action: '历史主动作事实', hint: '历史过程提示', indicator: '指标解读', comparator: '页面比较说明', cup_handle: '杯柄说明' }[dialogKind.value ?? 'explanation']))
async function loadExplanation() { if (loader.sections.explanation.state.value === 'not_requested') await loader.loadExplanation() }
async function toggleDetails() { detailsOpen.value = !detailsOpen.value; if (detailsOpen.value) await loadExplanation() }
async function openDialog(kind: NonNullable<typeof dialogKind.value>) {
  if (kind === 'cup_handle') retainedPane.value = { response: currentAuxiliaryResponse.value, lifecycle: currentAuxiliaryLifecycle.value,
    error: currentAuxiliaryError.value, proof: newowChartSnapshotKey(chartResponse.value), component: selectedAuxiliary.value }
  dialogKind.value = kind
  if (kind === 'explanation') await loadExplanation()
  if (kind === 'comparator' && loader.sections.comparator.state.value === 'not_requested') await loader.loadComparator()
  if (kind === 'cup_handle' && props.identity.frequency === '1d') await loader.loadAuxiliary('cup_handle')
}
function closeDialog() {
  const wasCup = dialogKind.value === 'cup_handle'
  dialogKind.value = null
  if (wasCup) void loader.loadAuxiliary(selectedAuxiliary.value)
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
  await loader.loadAuxiliary(component)
}
function loadReferenceOnce() { if (loader.sections.reference.state.value === 'not_requested') void loader.loadReference() }
function observeReference() {
  observer?.disconnect()
  if (!referenceAnchor.value || typeof IntersectionObserver === 'undefined') return
  observer = new IntersectionObserver(entries => {
    if (entries.some(entry => entry.isIntersecting)) { loadReferenceOnce(); observer?.disconnect() }
  })
  observer.observe(referenceAnchor.value)
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
}

function resolveSignalFocus(signalId: string): void {
  const action = chartModel.value?.actions.find((item) => item.id === signalId)
  if (action !== undefined && props.identity.focusBarEnd === action.barEnd) emit('focus-resolved', action.barEnd)
}
function refreshCurrent(): void { loader.refreshCurrent(); emit('refresh-current') }


watch(identityKey, async () => {
  selectedSignalId.value = null; selectedHintId.value = null; retainedPane.value = null; selectedAuxiliary.value = 'macd'; detailsOpen.value = false; dialogKind.value = null; locateMessage.value = null
  await nextTick(); observeReference()
}, { flush: 'sync' })
watch(loader.historicalSnapshot, async () => {
  emit('snapshot-mode', loader.historicalSnapshot.value?.as_of ?? null)
  selectedSignalId.value = null; selectedHintId.value = null; retainedPane.value = null
  detailsOpen.value = false; dialogKind.value = null; locateMessage.value = null
  await nextTick(); observeReference()
}, { flush: 'sync' })
// The single loader's invalidation also revokes display retention, even when the chart proof is unchanged.
watch(loader.sections.auxiliary.state, state => {
  if (state === 'input_conflict' || state === 'not_requested') retainedPane.value = null
}, { flush: 'sync' })
watch(() => newowChartSnapshotKey(chartResponse.value), (proof, previous) => {
  if (proof === previous) return
  retainedPane.value = null
  if (dialogKind.value === 'cup_handle') dialogKind.value = null
}, { flush: 'sync' })
// Load the default auxiliary only after chart acceptance, so its request carries the chart snapshot proof.
watch(() => [chartResponse.value?.meta.snapshot_token, chartResponse.value?.value?.page_identity], () => {
  if (chartResponse.value && loader.sections.auxiliary.state.value === 'not_requested') void loader.loadAuxiliary(selectedAuxiliary.value)
}, { immediate: true })
watch([chartModel, () => props.identity.focusBarEnd], ([model, focusBarEnd]) => {
  if (!focusBarEnd || model === null || selectedSignalId.value !== null) return
  selectedSignalId.value = model.actions.find(action => action.barEnd === focusBarEnd)?.id ?? null
}, { immediate: true })
onMounted(observeReference)
onBeforeUnmount(() => { observer?.disconnect(); loader.dispose() })
</script>

<template>
  <section class="newow-product-workspace" data-detail-workspace="newow" :data-strategy="identity.strategy" :data-frequency="identity.frequency" :data-chart-state="loader.sections.chart.state.value" :data-auxiliary-state="loader.sections.auxiliary.state.value">
    <section class="newow-summary" aria-label="策略概览">
      <div class="newow-product-workspace__snapshot-controls" :data-as-of="loader.historicalSnapshot.value?.as_of">
        <template v-if="loader.historicalSnapshot.value">
          <span :title="loader.historicalSnapshot.value.as_of">历史快照截至 {{ historicalAsOfLabel }}（交易日 {{ loader.historicalSnapshot.value.trading_day }}）</span>
          <button @click="loader.returnToCurrent">返回当前</button>
        </template>
        <template v-else>
          <button :disabled="loader.historicalLoading.value" @click="loader.switchToHistorical">查看最近可用历史快照</button>
          <button @click="refreshCurrent">刷新当前</button>
          <span v-if="loader.historicalError.value" role="status">{{ loader.historicalError.value }}</span>
        </template>
      </div>
      <div class="newow-summary__main">
        <strong>策略概览</strong>
        <button class="newow-status" :data-state="summary.status.state" @click="openDialog('explanation')"><span>{{ ({ BUILD: '▲', HOLD: '✓', CLEAR: '▼', FLAT: '×', UNAVAILABLE: '?' })[summary.status.state] }}</span>{{ summary.status.label }}</button>
        <button aria-label="策略信息" @click="openDialog('explanation')">ⓘ</button>
        <span class="newow-price newow-price--target" :title="summary.target?.bar_end">目标参考 {{ summary.target?.display_value ?? '—' }}<small v-if="summary.target"> · {{ shortNewowTime(summary.target.bar_end) }}</small><small v-else> · {{ loader.sections.explanation.state.value === 'not_requested' ? '未读取' : '不可用 / 证据不足' }}</small></span>
        <span class="newow-price newow-price--absorb" :title="summary.absorb?.bar_end">吸筹参考 {{ summary.absorb?.display_value ?? '—' }}<small v-if="summary.absorb"> · {{ shortNewowTime(summary.absorb.bar_end) }}</small><small v-else> · {{ loader.sections.explanation.state.value === 'not_requested' ? '未读取' : '不可用 / 证据不足' }}</small></span>
        <button class="newow-summary__expand" :aria-expanded="detailsOpen" aria-controls="newow-details" @click="toggleDetails">{{ detailsOpen ? '收起详情' : '展开详情' }}</button>
      </div>
      <div class="newow-summary__facts">
        <span :title="summary.status.barEnd ?? undefined">{{ summary.status.historical ? '历史窗口最近主动作' : '已读取窗口最近主动作' }} <button v-if="summary.latestAction" :title="summary.latestAction.bar_end" @click="selectSignal(summary.latestAction.signal_id)">{{ newowDisplayLabel(summary.latestAction.kind) }} · {{ summary.latestAction.reference_price }} · {{ shortNewowTime(summary.latestAction.bar_end) }}</button><template v-else>—</template></span>
        <span>当前参考交易 {{ summary.openReference ? '未清仓' : '—' }} <small v-if="!summary.openReference">{{ loader.sections.reference.state.value === 'not_requested' ? '未读取' : '当前窗口不可用' }}</small></span>
        <span>参考浮动 <span class="newow-return-badge" :data-direction="referencePercentDisplay(summary.openReference?.mark_change_pct).direction">{{ referencePercentDisplay(summary.openReference?.mark_change_pct).text }}</span> · {{ shortNewowTime(summary.openReference?.mark_bar_end) }}</span>
        <span :title="summary.status.barEnd ?? undefined">{{ summary.status.historical ? '历史窗口状态截至' : '已读取状态截至' }} {{ shortNewowTime(summary.status.barEnd) }}</span>
      </div>
      <div v-if="detailsOpen" id="newow-details">
        <NewowExplanationPanel :chart-state="summary.status" :response="explanationResponse" :lifecycle="loader.sections.explanation.state.value" :error="loader.sections.explanation.error.value" :comparator-response="null" comparator-lifecycle="not_requested" :comparator-error="null" mode="explanation" />
        <button v-if="loader.sections.explanation.error.value" @click="loader.loadExplanation">重试解释</button>
      </div>
    </section>
    <p v-if="loader.sections.chart.error.value" class="newow-product-workspace__notice" role="status">{{ loader.sections.chart.error.value }}：主图事实不可用或已过期。 <button @click="loader.loadChart()">重试主图</button></p>
    <NewowProductChartStage :response="chartResponse" :strategy="selectedStrategy" :selected-signal-id="selectedSignalId" :loading="loader.sections.chart.state.value === 'loading'" :has-more-before="chartModel?.nextBefore != null" :auxiliary-response="currentAuxiliaryResponse" :auxiliary-lifecycle="currentAuxiliaryLifecycle" :auxiliary-error="currentAuxiliaryError" @load-earlier="loader.loadNextChartPage" @select-signal="selectSignal" @focus-resolved="resolveSignalFocus" @select-hint="selectHint" @explain-main="openDialog('explanation')" @explain-auxiliary="openDialog('indicator')">
    <template #auxiliary-controls>
    <section class="newow-product-workspace__auxiliary" aria-label="Newow 辅助图层">
      <div class="newow-product-workspace__auxiliary-controls">
        <button v-for="option in auxiliaryOptions" :key="option.id" :aria-pressed="selectedAuxiliary === option.id" @click="toggleAuxiliary(option.id)">{{ option.label }}</button>
        <span v-if="selectedAuxiliary === 'macd'" class="newow-macd-legend"><span>DIF</span> / <span>DEA</span></span>
        <button aria-label="指标解读" @click="openDialog('indicator')">ⓘ</button>
        <button @click="openDialog('cup_handle')">杯柄说明</button>
      </div>
      <p v-if="currentAuxiliaryError" role="status">{{ currentAuxiliaryError }} · 辅助图层不可用 <button @click="loader.loadAuxiliary(selectedAuxiliary)">重试指标</button></p>
    </section>
    </template>
    </NewowProductChartStage>
    <section ref="referenceAnchor" class="newow-product-workspace__research" aria-label="Newow 参考与解释">
      <button @click="openDialog('comparator')">页面比较说明</button>
      <NewowReferencePanel :key="identityKey" :response="referenceResponse" :chart-response="chartResponse" :cross-section-compatible="loader.referenceChartCompatible.value" :lifecycle="loader.sections.reference.state.value" :error="loader.sections.reference.error.value" :selected-signal-id="selectedSignalId" :locate-message="locateMessage" :loading-page="loader.sections.reference.state.value === 'loading'" @reload="loader.loadReference" @retry="loader.loadReference()" @load-more="loader.loadNextReferencePage" @locate="locateReferenceTrade" />
    </section>
    <NewowDetailDialog :open="dialogKind !== null" :title="dialogTitle" :identity-key="identityKey" @close="closeDialog">
      <p>{{ identity.symbol.toUpperCase() }} · {{ newowDisplayLabel(identity.strategy ?? 'UNAVAILABLE') }} · {{ identity.frequency }} · {{ dialogKind === 'action' ? selectedAction?.physicalContract : dialogKind === 'hint' ? selectedHint?.physicalContract : chartResponse?.value?.bars.at(-1)?.physical_contract ?? '—' }}</p>
      <template v-if="dialogKind === 'hint'">
        <p v-if="selectedHint">{{ selectedHint.kind }} · {{ selectedHint.anchorPrice ?? '—' }} · {{ shortNewowTime(selectedHint.barEnd) }}</p>
        <p>仅为所选历史过程提示，不代表主动作或账户成交。</p>
        <details v-if="selectedHint"><summary>来源与原始事实</summary><p>{{ selectedHint.id }} · {{ selectedHint.barEnd }}</p><p>known_at {{ selectedHint.confirmedAt }} · sequence {{ selectedHint.sequence ?? '—' }}</p><p>owner {{ selectedHint.physicalContract }} · {{ selectedHint.segmentId }}</p><p>来源 {{ selectedHint.sourceIdentity ?? '—' }} · 响应公式 {{ selectedHint.formulaVersions.join(' / ') }}</p><p>anchor_price {{ selectedHint.anchorPrice ?? '—' }}</p></details>
      </template>
      <template v-else-if="dialogKind === 'action'">
        <p v-if="selectedAction">历史主动作 {{ newowDisplayLabel(selectedAction.kind) }} · {{ selectedAction.referencePrice }} · {{ shortNewowTime(selectedAction.barEnd) }}</p>
        <p>仅为所选历史主动作事实，不代表账户成交。</p>
        <details><summary>来源与关联 Hint</summary><p>{{ selectedSignalId }} · {{ selectedAction?.barEnd }}</p><p v-for="hint in chartResponse?.value?.hints.filter(hint => chartResponse?.value?.frames.find(frame => frame.bar_end === selectedAction?.barEnd)?.hint_ids.includes(hint.hint_id)) ?? []" :key="hint.hint_id">{{ hint.kind }} · {{ hint.hint_id }} · known_at {{ hint.known_at }} · {{ hint.anchor_price ?? '—' }}</p></details>
      </template>
      <template v-else-if="dialogKind === 'indicator'"><p>{{ auxiliaryDisclosure.title }}</p><p>{{ auxiliaryDisclosure.disclosure }}</p><p>{{ currentAuxiliaryLifecycle }} · {{ currentAuxiliaryError ?? '—' }}</p><details><summary>来源</summary><p>{{ currentAuxiliaryResponse?.value?.formula_version ?? '未读取' }}</p><p>截至 {{ currentAuxiliaryResponse?.meta.as_of ?? '—' }}</p></details></template>
      <template v-else-if="dialogKind === 'cup_handle'"><p>{{ identity.frequency !== '1d' ? '杯柄仅适用于 1d' : loader.sections.auxiliary.state.value }}</p><p v-if="loader.sections.auxiliary.error.value">{{ loader.sections.auxiliary.error.value }}</p><template v-if="auxiliaryResponse?.value?.component === 'cup_handle'"><p v-for="segment in auxiliaryResponse.value.segments" :key="segment.segment_id">{{ segment.physical_contract }} · {{ segment.status.reason_code ?? segment.status.status }}</p><details><summary>服务端杯柄事实</summary><pre>{{ auxiliaryResponse.value.segments }}</pre></details></template></template>
      <NewowExplanationPanel v-else :chart-state="summary.status" :response="explanationResponse" :lifecycle="loader.sections.explanation.state.value" :error="loader.sections.explanation.error.value" :comparator-response="comparatorResponse" :comparator-lifecycle="loader.sections.comparator.state.value" :comparator-error="loader.sections.comparator.error.value" :mode="dialogKind === 'comparator' ? 'comparator' : 'explanation'" />
      <button v-if="dialogKind === 'explanation' && loader.sections.explanation.error.value" @click="loader.loadExplanation">重试解释</button>
      <button v-if="dialogKind === 'comparator' && loader.sections.comparator.error.value" @click="loader.loadComparator">重试比较器</button>
    </NewowDetailDialog>
  </section>
</template>
<style scoped>
.newow-product-workspace { display:grid; min-width:0; gap:12px; }
.newow-summary { padding:16px 0; border-bottom:1px solid #ebedf0; }
.newow-product-workspace__snapshot-controls { display:flex; align-items:center; gap:12px; padding-bottom:10px; color:#667085; font-size:12px; }
.newow-summary__main,.newow-summary__facts { display:flex; align-items:center; flex-wrap:wrap; gap:12px 20px; }
.newow-summary__facts { font-size:12px; color:#667085; }
.newow-summary button,.newow-product-workspace__auxiliary-controls button,.newow-product-workspace__research > button { border:0; background:#fff; color:inherit; padding:4px 12px; }
.newow-status { display:flex; align-items:center; gap:8px; }
.newow-status span { border-radius:50%; width:24px; height:24px; display:grid; place-items:center; background:#f3f4f6; }
.newow-status[data-state="BUILD"] { color:#ff403a; }.newow-status[data-state="HOLD"] { color:#ff6b2c; }.newow-status[data-state="CLEAR"] { color:#22b95d; }.newow-status[data-state="FLAT"] { color:#365af5; }
.newow-price { padding:8px 12px; border-radius:7px; }.newow-price--target { color:#dd4c15; background:#fff4ee; }.newow-price--absorb { color:#365af5; background:#eef3ff; }
.newow-price small { font-size:11px; }.newow-summary__expand { margin-left:auto; }
.newow-product-workspace__auxiliary-controls { display:flex; flex-wrap:nowrap; overflow-x:auto; white-space:nowrap; align-items:center; border-top:1px solid #ebedf0; gap:0; font-size:12px; }
.newow-product-workspace__auxiliary-controls button { min-height:36px; padding:0 10px; }
.newow-product-workspace__auxiliary-controls button[aria-pressed="true"] { color:#ff6b2c; border-bottom:2px solid #ff6b2c; }
.newow-macd-legend { padding:0 6px; color:#667085; }.newow-macd-legend span:first-child { color:#ff6b2c; }.newow-macd-legend span:last-child { color:#365af5; }
.newow-product-workspace__notice { color:#b45309; }
pre { white-space:pre-wrap; overflow-wrap:anywhere; }
@media(max-width:640px) { .newow-product-workspace__auxiliary-controls button { min-height:44px; } }
</style>
