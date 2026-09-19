<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { referenceTimeDisplay, referencePercentDisplay, referenceInterruptionLabel } from '@/utils/newowDetailPresentation'
import { formatBeijingInstant, formatMarketDecimal } from '@/utils/marketDisplay'
import { acceptedNewowReferencePreset, newowReferenceWindow, type NewowReferencePreset } from '@/utils/newowReferenceWindows'

import type {
  NewowProductSectionResponse,
  NewowReferenceTrade,
  NewowResourceLifecycle,
} from '@/types/newowProduct'
import {
  buildNewowReferencePanelViewModel,
  filterNewowReferenceRows,
  resolveNewowPanelRenderState,
  type NewowReferenceCategory,
} from '@/utils/newowProductViewModel'

const props = defineProps<{
  response: NewowProductSectionResponse<'reference'> | null
  chartResponse: NewowProductSectionResponse<'chart'> | null
  crossSectionCompatible: boolean
  chartLifecycle?: NewowResourceLifecycle
  currentChartWindow?: boolean
  lifecycle: NewowResourceLifecycle
  error: string | null
  selectedSignalId: string | null
  locateMessage: string | null
  loadingPage: boolean
}>()
const emit = defineEmits<{
  reload: [window: { performanceSince: string; performanceThrough: string }]
  retry: []
  'load-more': []
  locate: [trade: NewowReferenceTrade, endpoint: 'entry' | 'exit']
}>()

const filter = ref<'all' | NewowReferenceCategory | 'initial'>('all')
const expanded = ref<readonly string[]>([])
const performanceSince = ref('')
const performanceThrough = ref('')
const invalidWindow = computed(() => !!performanceSince.value && !!performanceThrough.value && performanceSince.value > performanceThrough.value)
const presentation = computed(() => resolveNewowPanelRenderState(props.lifecycle, props.response, props.error))
const model = computed(() => (
  presentation.value.showValue && props.response?.value
    ? buildNewowReferencePanelViewModel(props.response, props.chartResponse, props.crossSectionCompatible)
    : null
))
const visibleModel = computed(() => model.value === null ? null : filterNewowReferenceRows(model.value, filter.value))
const pendingPreset = ref<{ kind: NewowReferencePreset | 'complete'; since: string; through: string } | null>(null)
const acceptedPreset = ref<NewowReferencePreset | 'complete' | null>(null)
const acceptedAnchor = computed(() => model.value?.actualAvailableThrough ?? null)

// Current FLAT is a chart fact, never a synthetic trade or a guess from a history page.
const waiting = computed(() => {
  const chart = props.chartResponse
  const reference = props.response
  if (props.lifecycle !== 'ready' || props.chartLifecycle !== 'ready' || props.currentChartWindow !== true
    || !props.crossSectionCompatible || chart?.status.status !== 'ready' || reference?.status.status !== 'ready'
    || !chart.value || !reference.value || chart.meta.as_of !== reference.meta.as_of
    || JSON.stringify(chart.meta.identity) !== JSON.stringify(reference.meta.identity)) return null
  const bar = chart.value.bars.at(-1)
  const frame = chart.value.frames.find(item => item.bar_end === bar?.bar_end)
  if (!bar?.completed || !bar.observation_eligible || frame?.status.status !== 'ready'
    || frame.status.evidence_status !== 'ACTIVE_CODE_VERIFIED' || frame.main_state !== 'FLAT'
    || Date.parse(bar.bar_end) > Date.parse(chart.meta.as_of)
    || reference.value.items.some(item => item.status === 'OPEN' && item.physical_contract === bar.physical_contract && item.segment_id === bar.segment_id && item.calculation_segment_id === bar.calculation_segment_id)) return null
  return bar
})
function rowTime(trade: NewowReferenceTrade, time: string | null): string {
  return referenceTimeDisplay(time, trade.frequency, [trade.entry_bar_end, trade.exit_bar_end,
    trade.mark_bar_end, trade.interrupted_at, props.response?.meta.as_of])
}

watch(() => props.response?.value, (value) => {
  if (value === null || value === undefined) {
    performanceSince.value = ''
    performanceThrough.value = ''
    return
  }
  performanceSince.value = value.performance_since
  performanceThrough.value = value.performance_through
  const pending = pendingPreset.value
  acceptedPreset.value = acceptedNewowReferencePreset(pending, { performanceSince: value.performance_since, performanceThrough: value.performance_through })
  pendingPreset.value = null
}, { immediate: true })

// A failed request has not accepted the requested window. Keeping a selected
// pill in that case would mislabel the older response that remains on screen.
watch(() => [props.lifecycle, props.error] as const, ([lifecycle, error]) => {
  if (pendingPreset.value !== null && (lifecycle === 'unavailable' || lifecycle === 'input_conflict'
    || lifecycle === 'cancelled' || (lifecycle === 'stale' && error !== null))) {
    pendingPreset.value = null
    acceptedPreset.value = null
  }
})

function toggle(id: string): void {
  expanded.value = expanded.value.includes(id)
    ? expanded.value.filter((item) => item !== id)
    : [...expanded.value, id]
}

function reload(): void {
  if (!performanceSince.value || !performanceThrough.value || invalidWindow.value || props.loadingPage) return
  emit('reload', { performanceSince: performanceSince.value, performanceThrough: performanceThrough.value })
}

function useCompleteWindow(): void {
  const target = model.value?.completeWindowAction
  if (!target || props.loadingPage) return
  pendingPreset.value = { kind: 'complete', ...target }
  emit('reload', { performanceSince: target.since, performanceThrough: target.through })
}
function usePreset(preset: NewowReferencePreset): void {
  if (!acceptedAnchor.value || props.loadingPage) return
  try {
    const target = newowReferenceWindow(acceptedAnchor.value, preset)
    pendingPreset.value = { kind: preset, since: target.performanceSince, through: target.performanceThrough }
    emit('reload', target)
  } catch { pendingPreset.value = null }
}

function updateSince(event: Event): void { performanceSince.value = (event.target as HTMLInputElement).value; pendingPreset.value = null; acceptedPreset.value = null }
function updateThrough(event: Event): void { performanceThrough.value = (event.target as HTMLInputElement).value; pendingPreset.value = null; acceptedPreset.value = null }
function updateFilter(event: Event): void { filter.value = (event.target as HTMLSelectElement).value as typeof filter.value }
</script>

<template>
  <section class="newow-reference" aria-labelledby="newow-reference-title">
    <header class="newow-reference__header">
      <div>
        <h3 id="newow-reference-title">参考交易</h3>
        <p>页面参考 · 零手续费 / 零滑点 · 非账户成交</p>
        <details><summary>参考口径说明</summary><p>只表达 long/flat；使用趋势 B、震荡 Low/High、主升浪 MA45 的 API reference_price；不计资金占用与真实成交限制，不推断手数、不推断空单、不推断账户净值、不推断真实收益。Reference 非因果回测、非模拟账户、非真实成交，不使用同 Bar Close；同 Bar Close 仅属于独立 comparator。</p></details>
      </div>
      <form class="newow-reference__window" @submit.prevent="reload">
        <div class="newow-reference__presets" aria-label="参考统计快捷窗口">
          <button v-for="preset in ([['three_months', '近3月'], ['one_year', '近1年'], ['ytd', '今年']] as const)" :key="preset[0]" type="button" :disabled="loadingPage || !acceptedAnchor" :aria-pressed="acceptedPreset === preset[0]" :data-pending="pendingPreset?.kind === preset[0]" @click="usePreset(preset[0])">{{ pendingPreset?.kind === preset[0] ? '读取中…' : preset[1] }}</button>
          <button type="button" :disabled="loadingPage || !model?.completeWindowAction" :aria-pressed="acceptedPreset === 'complete'" :data-pending="pendingPreset?.kind === 'complete'" @click="useCompleteWindow">{{ pendingPreset?.kind === 'complete' ? '读取中…' : '完整窗口' }}</button>
        </div>
        <label>统计起点 <input :value="performanceSince" type="date" @input="updateSince" /></label>
        <label>统计终点 <input :value="performanceThrough" type="date" @input="updateThrough" /></label>
        <button type="submit" :disabled="loadingPage || invalidWindow">{{ loadingPage ? '读取中…' : '应用统计窗口' }}</button>
      </form>
    </header>
    <p v-if="invalidWindow" class="newow-reference__state" role="alert">统计起点不能晚于统计终点。</p>

    <p v-if="presentation.message" class="newow-reference__state" role="status">
      {{ presentation.message }}
      <span v-if="presentation.staleAt">stale 读取时间 {{ presentation.staleAt }}</span>
    </p>

    <button v-if="lifecycle === 'not_requested' || error || lifecycle === 'unavailable'" type="button" @click="emit('retry')">{{ lifecycle === 'not_requested' ? '读取参考交易' : '重试参考交易' }}</button>
    <template v-if="model">
      <section class="newow-reference__summary" data-testid="newow-reference-summary" aria-label="参考交易统计摘要">
        <p class="newow-reference__availability" role="status">{{ model.statusExplanation }}</p>
        <div v-if="response?.value?.history_coverage === 'PARTIAL'" role="status">
          <p>历史覆盖不完整；仅统计有效区段内已完成的参考交易，跨中断记录不计入收益。</p>
          <ul><li v-for="interval in response.value.coverage_intervals" :key="`${interval.segment_id}:${interval.since}:${interval.status}`">{{ interval.since }} → {{ interval.through }} · {{ interval.physical_contract }} · {{ interval.status === 'VALID' ? '有效计算区段' : interval.status === 'PRICE_UNAVAILABLE' ? '来源价格不可用' : '重新预热中' }}</li></ul>
        </div>
        <dl>
          <div><dt>已完成</dt><dd>{{ model.summary.closedCount }}</dd></div>
          <div><dt>胜率</dt><dd>{{ model.summary.winRateText }}</dd></div>
          <div><dt>平均单笔</dt><dd>{{ model.summary.meanText }}</dd></div>
          <div><dt>收益合计</dt><dd>{{ model.summary.sumText }} <small>{{ model.summary.sumUnit }}</small></dd></div>
          <div><dt>未清仓</dt><dd>{{ model.counts.open }}</dd></div>
          <div><dt>换月中断</dt><dd>{{ model.counts.rolloverInterrupted }}</dd></div>
          <div><dt>数据中断</dt><dd>{{ model.counts.dataInterrupted }}</dd></div>
          <div><dt>期初已有</dt><dd>{{ model.counts.initial }}</dd></div>
        </dl>
        <p v-if="model.summary.closedCount === 0">暂无已完成参考交易；统计指标不是 0%。</p>
        <button v-if="model.completeWindowAction" type="button" :disabled="loadingPage" @click="useCompleteWindow">使用最近完整统计区间</button>
        <details><summary>统计时间与来源</summary><p>用户选择统计区间 {{ model.performanceWindow.since }} → {{ model.performanceWindow.through }}</p><p>实际完整可用截止 {{ model.actualAvailableThrough }} · 参考计算截止 {{ formatBeijingInstant(model.performanceWindow.cutoff) }}</p><p v-if="response?.status.reason_code">技术原因码 {{ response.status.reason_code }}</p></details>
      </section>

      <article v-if="waiting" class="newow-reference__card newow-reference__waiting" data-testid="newow-reference-waiting">
        <header><strong>空仓等待中</strong><span>策略空仓 · {{ waiting.physical_contract }}</span></header>
        <p :title="waiting.bar_end">状态时间 {{ referenceTimeDisplay(waiting.bar_end, chartResponse!.meta.identity.frequency, [chartResponse!.meta.as_of]) }} · 截至所示已完成 Bar，仅作页面参考。</p>
        <details><summary>状态来源</summary><p>{{ waiting.bar_end }} · {{ waiting.segment_id }}</p><p>{{ chartResponse!.meta.identity.profile_id }} · {{ chartResponse!.meta.identity.formula_versions.join(' / ') }} · as-of {{ chartResponse!.meta.as_of }}</p></details>
      </article>

      <div class="newow-reference__tools">
        <label>
          记录筛选
          <select :value="filter" aria-label="筛选参考历史" @change="updateFilter">
            <option value="all">全部</option>
            <option value="closed">已清仓</option>
            <option value="open">未清仓</option>
            <option value="interrupted">中断记录</option>
            <option value="initial">期初已有</option>
          </select>
        </label>
        <span>筛选仅改变记录，不改变服务端统计或 Performance window。</span>
      </div>

      <div class="newow-reference__cards">
        <article v-for="row in visibleModel?.rows ?? []" :key="row.id" :id="`reference-trade-${row.id}`" class="newow-reference__card" :data-reference-category="row.category" :data-reference-initial="row.initial" :data-selected="selectedSignalId === row.trade.entry_signal_id" tabindex="-1">
          <header :title="`${row.trade.entry_bar_end} → ${row.trade.exit_bar_end ?? row.trade.mark_bar_end ?? row.trade.interrupted_at}`"><strong>{{ row.category === 'open' ? '未清仓' : row.category === 'closed' ? '已清仓' : row.trade.status === 'DATA_INTERRUPTED' ? '数据中断' : '换月中断' }}</strong><span>{{ row.trade.physical_contract }} · {{ rowTime(row.trade, row.trade.entry_bar_end) }} → {{ row.trade.exit_bar_end ? rowTime(row.trade, row.trade.exit_bar_end) : row.category === 'open' ? '至估值日' : rowTime(row.trade, row.trade.interrupted_at) }}</span><span v-if="row.initial">期初已有</span></header>
          <div class="newow-reference__card-body">
            <dl class="newow-reference__facts">
              <div><dt>参考建仓</dt><dd>▲ {{ formatMarketDecimal(row.trade.entry_reference_price) }} · {{ rowTime(row.trade, row.trade.entry_bar_end) }}</dd></div>
              <div v-if="row.category === 'closed'"><dt>参考清仓</dt><dd>▼ {{ formatMarketDecimal(row.trade.exit_reference_price) }} · {{ rowTime(row.trade, row.trade.exit_bar_end) }}</dd></div>
              <div v-if="row.category !== 'closed' && row.trade.mark_bar_end !== null && row.trade.mark_reference_price !== null"><dt>参考估值</dt><dd>{{ formatMarketDecimal(row.trade.mark_reference_price) }} · {{ rowTime(row.trade, row.trade.mark_bar_end) }}</dd></div>
              <div v-if="row.category === 'interrupted'"><dt>中断说明</dt><dd>{{ row.trade.status === 'DATA_INTERRUPTED' ? '数据中断' : '换月中断' }} · {{ referenceInterruptionLabel(row.trade.interruption_reason) }}</dd></div>
            </dl>
            <p class="newow-reference__return">{{ row.category === 'open' ? '参考浮动' : row.category === 'closed' ? '已清仓收益' : '中断浮动' }} <span class="newow-return-badge" :data-direction="referencePercentDisplay(row.category === 'closed' ? row.trade.reference_return_pct : row.trade.mark_change_pct).direction">{{ referencePercentDisplay(row.category === 'closed' ? row.trade.reference_return_pct : row.trade.mark_change_pct).text }}</span></p>
            <button type="button" :aria-label="`定位参考记录 ${row.id} 的建仓信号`" @click="emit('locate', row.trade, 'entry')">定位建仓</button>
            <button v-if="row.trade.exit_signal_id !== null && row.trade.exit_bar_end !== null && row.trade.exit_trading_day !== null" type="button" :aria-label="`定位参考记录 ${row.id} 的清仓信号`" @click="emit('locate', row.trade, 'exit')">定位清仓</button>
            <button type="button" :aria-label="`展开参考记录 ${row.id}`" :aria-expanded="expanded.includes(row.id)" @click="toggle(row.id)">查看详情</button>
          </div>
          <div v-if="expanded.includes(row.id)" class="newow-reference__details">
            <p>{{ row.returnText }} · 估值 {{ row.valuationText }} · 中断原始原因 {{ row.trade.interruption_reason ?? '—' }}</p><p>{{ row.statusText }} · 建仓 {{ row.trade.entry_bar_end }} · 清仓 {{ row.trade.exit_bar_end ?? '—' }}</p><p>{{ row.trade.strategy_code }} / {{ row.trade.frequency }} · {{ row.trade.holding_bars }} Bars</p><p>{{ row.id }} · {{ row.trade.segment_id }}</p>
            <p>建仓 ID {{ row.trade.entry_signal_id }} · 清仓 ID {{ row.trade.exit_signal_id ?? '—' }}</p>
            <p>公式 {{ row.trade.formula_versions.join(' / ') }} · {{ row.trade.reference_model_version }} · {{ row.trade.futures_adaptation_version }}</p>
            <p v-if="row.hints.length === 0">该记录没有服务端 Hint ID。</p>
            <ul v-else><li v-for="hint in row.hints" :key="hint.id" :data-hint-availability="hint.availability"><code>{{ hint.id }}</code> · {{ hint.text }}<template v-if="hint.fact"> · known_at {{ hint.fact.known_at }} · anchor {{ hint.fact.anchor_price ?? '—' }} · {{ hint.fact.physical_contract }} / {{ hint.fact.segment_id }}</template></li></ul>
          </div>
        </article>
      </div>
      <p v-if="visibleModel?.rows.length === 0" class="newow-reference__state">当前筛选没有记录。</p>
      <p v-if="locateMessage" class="newow-reference__state" role="status">{{ locateMessage }}</p>
      <button v-if="model.nextBefore" type="button" :disabled="loadingPage" @click="emit('load-more')">加载更多参考历史</button>
    </template>
  </section>
</template>

<style scoped>
.newow-reference { display: grid; gap: var(--gy-space-3); }
.newow-reference__header, .newow-reference__summary, .newow-reference__state, .newow-reference__tools { padding: var(--gy-space-3); border: 1px solid var(--gy-border); border-radius: var(--gy-radius-md); background: var(--gy-bg-panel); }
.newow-reference__header { display: flex; justify-content: space-between; gap: var(--gy-space-3); }
.newow-reference h3, .newow-reference p, .newow-reference dl { margin: 0; }
.newow-reference__header p, .newow-reference__tools span, small { color: var(--gy-text-muted); }
.newow-reference__window, .newow-reference__tools, .newow-reference__presets { display: flex; flex-wrap: wrap; align-items: end; gap: var(--gy-space-2); }
.newow-reference__presets button { min-height:32px; border-radius:999px; font-size:12px; }.newow-reference__presets button[aria-pressed="true"] { background:#fff1e8; border-color:#ff6b2c; color:#c2410c; }
.newow-reference__window label { display: grid; gap: 4px; }
.newow-reference button, .newow-reference input, .newow-reference select { min-height: 44px; padding: 0 var(--gy-space-2); border: 1px solid var(--gy-border); border-radius: var(--gy-radius-sm); color: var(--gy-text-primary); background: var(--gy-bg-panel); }
.newow-reference__summary dl { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: var(--gy-space-2); }
.newow-reference__summary dl div { padding: var(--gy-space-2); background: var(--gy-bg-elevated); }
.newow-reference__summary dt { color: var(--gy-text-muted); font-size: var(--gy-font-size-xs); }
.newow-reference__summary dd { margin: 4px 0 0; font-variant-numeric: tabular-nums; }
.newow-reference__cards { display:grid; gap:8px; }
.newow-reference__card { padding:12px 16px; border:1px solid var(--gy-border); border-radius:7px; background:var(--gy-bg-panel); min-width:0; }
.newow-reference__card[data-reference-category="open"] { background:#fff8f2; border-left:4px solid #ff6b2c; }
.newow-reference__waiting { background:#f1f7ff; border-left:4px solid #397bd1; }
.newow-reference__card[data-selected="true"] { outline:2px solid var(--gy-border-focus); }
.newow-reference__card header,.newow-reference__card-body { display:flex; gap:12px; align-items:center; flex-wrap:wrap; }
.newow-reference__card header { margin-bottom:6px; }
.newow-reference__card header strong { font-size:12px; padding:4px 10px; border-radius:7px; background:var(--gy-bg-elevated); }
.newow-reference__card-body > p:first-child { flex:1; }
.newow-reference__facts { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:var(--gy-space-2); flex:1; min-width:min(100%, 360px); }
.newow-reference__facts div { min-width:0; padding:var(--gy-space-2); border-radius:var(--gy-radius-sm); background:var(--gy-bg-elevated); }
.newow-reference__facts dt { color:var(--gy-text-muted); font-size:var(--gy-font-size-xs); }.newow-reference__facts dd { margin:4px 0 0; overflow-wrap:anywhere; font-variant-numeric:tabular-nums; }
.newow-reference__return { font-variant-numeric:tabular-nums; }
.newow-reference__details { margin-top:12px; color:var(--gy-text-secondary); overflow-wrap:anywhere; }
.newow-reference__state { color: var(--gy-status-warning); }
@media (max-width: 720px) { .newow-reference__header { flex-direction: column; } .newow-reference__card-body > p:first-child { flex-basis:100%; } }
</style>
