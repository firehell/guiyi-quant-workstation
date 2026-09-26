<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { newowReferenceCurve } from '@/utils/newowReferenceCurve'
import { referenceTimeDisplay, referencePercentDisplay, referenceInterruptionLabel } from '@/utils/newowDetailPresentation'
import { formatMarketDecimal } from '@/utils/marketDisplay'
import { acceptedNewowReferencePreset, newowReferenceWindow, type NewowReferencePreset } from '@/utils/newowReferenceWindows'

import type {
  NewowProductSectionResponse,
  NewowReferenceTrade,
  NewowResourceLifecycle,
} from '@/types/newowProduct'
import {
  buildNewowReferencePanelViewModel,
  resolveNewowPanelRenderState,
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
  }>()

const performanceSince = ref('')
const performanceThrough = ref('')
const invalidWindow = computed(() => !!performanceSince.value && !!performanceThrough.value && performanceSince.value > performanceThrough.value)
const presentation = computed(() => resolveNewowPanelRenderState(props.lifecycle, props.response, props.error))
const model = computed(() => (
  presentation.value.showValue && props.response?.value
    ? buildNewowReferencePanelViewModel(props.response, props.chartResponse, props.crossSectionCompatible)
    : null
))
const curve = computed(() => props.response?.value ? newowReferenceCurve(props.response.value) : null)
const selectedTradeId = ref<string | null>(null)
const recordElements = new Map<string, HTMLElement>()
const curvePoints = computed(() => {
  const points = curve.value?.points ?? []
  const low = Math.min(0, ...points.map(p => p.value))
  const high = Math.max(0, ...points.map(p => p.value))
  const y = (value: number) => 160 - (value - low) / (high - low || 1) * 130
  const start = Date.parse(model.value?.performanceWindow.since ?? '')
  const end = Date.parse(points.at(-1)?.trade.exit_trading_day ?? '')
  const duration = end - start
  const x = (day: string) => 48 + (duration > 0 ? (Date.parse(day) - start) / duration : 1) * 684
  const sameYear = new Date(start).getUTCFullYear() === new Date(end).getUTCFullYear()
  const tickCount = duration > 0 ? Math.min(7, Math.floor(duration / 86_400_000) + 1) : 1
  const ticks = Number.isFinite(start) && Number.isFinite(end) ? Array.from({ length: tickCount }, (_, index) => {
    const ratio = tickCount === 1 ? 1 : index / (tickCount - 1)
    const day = new Date(start + duration * ratio).toISOString().slice(0, 10)
    return { x: 48 + ratio * 684, label: sameYear ? day.slice(5) : day, anchor: index === 0 && tickCount > 1 ? 'start' : index === tickCount - 1 ? 'end' : 'middle' }
  }) : []
  return { points: points.map(p => ({ ...p, x: x(p.trade.exit_trading_day!), y: y(p.value) })), ticks, zero: y(0), low, high }
})
async function selectCurveTrade(trade: NewowReferenceTrade): Promise<void> {
  selectedTradeId.value = trade.reference_trade_id
  if (!recordElements.has(trade.reference_trade_id) && props.response?.value?.next_before) {
    emit('load-more')
    await nextTick()
    return
  }
  await nextTick()
  recordElements.get(trade.reference_trade_id)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
}
watch(() => props.response?.value?.items, async () => {
  if (!selectedTradeId.value) return
  await nextTick()
  const record = recordElements.get(selectedTradeId.value)
  if (record) record.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  else if (props.response?.value?.next_before) emit('load-more')
})
watch(() => props.selectedSignalId, id => {
  const trade = props.response?.value?.items.find(t => t.entry_signal_id === id || t.exit_signal_id === id)
  if (trade) selectedTradeId.value = trade.reference_trade_id
})
watch(() => props.response?.value, value => {
  if (!value?.items.some(t => t.reference_trade_id === selectedTradeId.value)) selectedTradeId.value = null
})
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
</script>

<template>
  <section class="newow-reference" :aria-busy="loadingPage" aria-labelledby="newow-reference-title">
    <header class="newow-reference__returns-heading"><strong id="newow-reference-title">参考收益走势</strong></header>
      <form class="newow-reference__window" @submit.prevent="reload">
        <div class="newow-reference__presets" aria-label="参考统计快捷窗口">
          <button v-for="preset in ([['three_months', '近3月'], ['one_year', '近1年'], ['ytd', '今年']] as const)" :key="preset[0]" type="button" :disabled="loadingPage || !acceptedAnchor" :aria-pressed="acceptedPreset === preset[0]" :data-pending="pendingPreset?.kind === preset[0]" @click="usePreset(preset[0])">{{ pendingPreset?.kind === preset[0] ? '读取中…' : preset[1] }}</button>
          <button type="button" :disabled="loadingPage || !model?.completeWindowAction" :title="loadingPage ? '正在读取统计窗口' : !model?.completeWindowAction ? '当前统计窗口已完整，或尚无经确认的完整截止' : '使用服务端确认的完整截止'" :aria-pressed="acceptedPreset === 'complete'" :data-pending="pendingPreset?.kind === 'complete'" @click="useCompleteWindow">{{ pendingPreset?.kind === 'complete' ? '读取中…' : '完整窗口' }}</button>
        </div>
        <details class="newow-reference__custom-window"><summary>自定义区间</summary><div>
        <label>统计起点 <input :value="performanceSince" type="date" @input="updateSince" /></label>
        <label>统计终点 <input :value="performanceThrough" type="date" @input="updateThrough" /></label>
        <button type="submit" :disabled="loadingPage || invalidWindow || !performanceSince || !performanceThrough">{{ loadingPage ? '读取中…' : '应用统计窗口' }}</button>
        </div></details>
      </form>
    <p v-if="invalidWindow" class="newow-reference__state" role="alert">统计起点不能晚于统计终点。</p>

    <p v-if="presentation.message" class="newow-reference__state" role="status">
      {{ presentation.message }}
      <span v-if="presentation.staleAt">上次已验证读取时间 {{ presentation.staleAt }}</span>
    </p>

    <button v-if="lifecycle === 'not_requested' || error || lifecycle === 'unavailable'" type="button" @click="emit('retry')">{{ lifecycle === 'not_requested' ? '读取参考交易' : '重试参考交易' }}</button>
    <template v-if="model">
      <section class="newow-reference__curve" aria-label="已完成参考交易累计收益曲线">
        <p v-if="curve?.message" role="status">{{ curve.message }}</p>
        <template v-else>
          <svg viewBox="0 0 780 192" preserveAspectRatio="none" role="group" aria-label="按清仓顺序累计的参考收益，每个点可定位交易记录">
            <defs><linearGradient id="newow-reference-area" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#ff403a" stop-opacity="0.16" /><stop offset="100%" stop-color="#ff403a" stop-opacity="0.01" /></linearGradient></defs>
            <line v-for="level in [25, 70, 115, 160]" :key="level" x1="48" x2="732" :y1="level" :y2="level" stroke="#f2f3f5" />
            <polygon :points="`${48},${curvePoints.zero} ` + curvePoints.points.map(p => `${p.x},${p.y}`).join(' ') + ` ${curvePoints.points.at(-1)?.x ?? 48},${curvePoints.zero}`" fill="url(#newow-reference-area)" />
            <line x1="48" x2="732" :y1="curvePoints.zero" :y2="curvePoints.zero" stroke="#d0d5dd" stroke-dasharray="4 4" />
            <text v-if="curvePoints.low < 0 && curvePoints.high > 0" x="6" :y="curvePoints.zero - 4">0</text>
            <text x="6" y="25">{{ curvePoints.high.toFixed(2) }}</text>
            <text x="6" y="176">{{ curvePoints.low.toFixed(2) }}</text>
            <polyline :points="`${48},${curvePoints.zero} ` + curvePoints.points.map(p => `${p.x},${p.y}`).join(' ')" fill="none" stroke="#ff403a" stroke-width="1.8" />
            <circle v-for="point in curvePoints.points" :key="point.trade.reference_trade_id" :cx="point.x" :cy="point.y" :r="selectedTradeId === point.trade.reference_trade_id ? 4 : 2" :fill="point.value >= 0 ? '#ff403a' : '#22b95d'" stroke="white" role="button" tabindex="0" :aria-label="`${point.trade.exit_trading_day}，累计 ${formatMarketDecimal(point.cumulative)} 百分点，定位参考交易`" @click="selectCurveTrade(point.trade)" @keydown.enter.prevent="selectCurveTrade(point.trade)" @keydown.space.prevent="selectCurveTrade(point.trade)"><title>{{ point.trade.exit_trading_day }} · {{ point.trade.physical_contract }} · 单笔 {{ referencePercentDisplay(point.trade.reference_return_pct).text }} · 累计 {{ formatMarketDecimal(point.cumulative) }} 百分点</title></circle>
            <text v-for="tick in curvePoints.ticks" :key="tick.x" :x="tick.x" y="190" :text-anchor="tick.anchor" class="newow-reference__date-tick">{{ tick.label }}</text>
          </svg>
        </template>
      <section class="newow-reference__summary" data-testid="newow-reference-summary" aria-label="参考交易统计摘要">
        <div v-if="response?.value?.history_coverage === 'PARTIAL'" role="status">
          <p>历史覆盖不完整；仅统计有效区段内已完成的参考交易，跨中断记录不计入收益。</p>
          <ul><li v-for="interval in response.value.coverage_intervals" :key="`${interval.segment_id}:${interval.since}:${interval.status}`">{{ interval.since }} → {{ interval.through }} · {{ interval.physical_contract }} · {{ interval.status === 'VALID' ? '有效计算区段' : interval.status === 'PRICE_UNAVAILABLE' ? '来源价格不可用' : '重新预热中' }}</li></ul>
        </div>
        <dl class="newow-reference__metrics">
          <div><dt>累计参考收益</dt><dd :data-direction="referencePercentDisplay(response?.value?.summary.sum_return_percentage_points).direction">{{ model.summary.sumText }} <small>百分点</small></dd></div>
          <div><dt>胜率</dt><dd>{{ model.summary.winRateText }}</dd></div>
          <div><dt>平均单笔</dt><dd>{{ model.summary.meanText }}</dd></div>
          <div><dt>已完成交易</dt><dd>{{ model.summary.closedCount }}</dd></div>
        </dl>
        <p v-if="response?.status.reason_code" class="newow-reference__availability" role="status">{{ model.statusExplanation }}</p>

        <p v-if="model.summary.closedCount === 0">暂无已完成参考交易；统计指标不是 0%。</p>
        <button v-if="model.completeWindowAction" type="button" :disabled="loadingPage" @click="useCompleteWindow">使用最近完整统计区间</button>
      </section>
      </section>

      <header class="newow-reference__records-heading"><h3>回测操盘提醒</h3><span>历史参考推演，仅供参考，不作为实时买卖提示</span></header>
      <article v-if="waiting" class="newow-reference__card newow-reference__waiting" data-testid="newow-reference-waiting">
        <header><strong>空仓等待中</strong><span>策略空仓 · {{ waiting.physical_contract }}</span></header>
        <p :title="waiting.bar_end">状态时间 {{ referenceTimeDisplay(waiting.bar_end, chartResponse!.meta.identity.frequency, [chartResponse!.meta.as_of]) }} · 截至所示已完成 Bar，仅作页面参考。</p>
      </article>

      <div class="newow-reference__cards">
        <article v-for="row in model.rows" :key="row.id" :ref="element => { if (element) recordElements.set(row.id, element as HTMLElement); else recordElements.delete(row.id) }" :id="`reference-trade-${row.id}`" class="newow-reference__card" :data-reference-category="row.category" :data-reference-initial="row.initial">
          <header class="newow-reference__record-top">
            <div class="newow-reference__record-meta"><strong class="newow-reference__period" :class="{ 'is-open': row.category === 'open', 'is-interrupted': row.category === 'interrupted' }">{{ row.category === 'open' ? '持仓参考中' : row.category === 'interrupted' ? (row.trade.status === 'DATA_INTERRUPTED' ? '数据中断' : '换月中断') : row.trade.frequency === '1w' ? '周K' : row.trade.frequency === '1d' ? '日K' : '60分' }}</strong><span>{{ rowTime(row.trade, row.trade.entry_bar_end) }} → {{ row.category === 'open' ? '至估值日' : rowTime(row.trade, row.trade.exit_bar_end ?? row.trade.interrupted_at) }}</span><span>{{ row.trade.physical_contract }}</span><span v-if="row.initial">期初已有</span></div>
            <strong class="newow-reference__record-return" :data-direction="referencePercentDisplay(row.category === 'closed' ? row.trade.reference_return_pct : row.trade.mark_change_pct).direction">{{ row.category === 'closed' ? '盈亏' : row.category === 'open' ? '参考浮动' : '中断浮动' }} {{ referencePercentDisplay(row.category === 'closed' ? row.trade.reference_return_pct : row.trade.mark_change_pct).text }}</strong>
          </header>
          <div class="newow-reference__record-line"><span><b class="newow-reference__entry">建仓</b> <span>买入</span> <strong>{{ formatMarketDecimal(row.trade.entry_reference_price) }}</strong></span><time :datetime="row.trade.entry_bar_end">{{ rowTime(row.trade, row.trade.entry_bar_end) }}</time></div>
          <div v-if="row.category === 'closed'" class="newow-reference__record-line"><span><b class="newow-reference__exit">清仓</b> <span>卖出</span> <strong>{{ formatMarketDecimal(row.trade.exit_reference_price) }}</strong> <strong class="newow-reference__inline-return" :data-direction="referencePercentDisplay(row.trade.reference_return_pct).direction">{{ referencePercentDisplay(row.trade.reference_return_pct).text }}</strong></span><time :datetime="row.trade.exit_bar_end ?? undefined">{{ rowTime(row.trade, row.trade.exit_bar_end) }}</time></div>
          <div v-else class="newow-reference__record-line"><span><b class="newow-reference__valuation">参考估值</b> <strong>{{ formatMarketDecimal(row.trade.mark_reference_price) }}</strong></span><time :datetime="row.trade.mark_bar_end ?? undefined">{{ rowTime(row.trade, row.trade.mark_bar_end) }}</time></div>
          <p v-if="row.category === 'interrupted'" class="newow-reference__interruption">{{ referenceInterruptionLabel(row.trade.interruption_reason) }} · 中断浮动不计入已完成收益</p>
          <p v-else-if="row.category === 'open'" class="newow-reference__interruption">未清仓 · 浮动不计入已完成收益</p>
        </article>
      </div>
      <p v-if="model.rows.length === 0" class="newow-reference__state">暂无参考交易记录。</p>
      <p v-if="locateMessage" class="newow-reference__state" role="status">{{ locateMessage }}</p>
      <button v-if="model.nextBefore" type="button" :disabled="loadingPage" @click="emit('load-more')">加载更多参考历史</button>
    </template>
  </section>
</template>

<style scoped>
.newow-reference { min-width:0; display: grid; gap: var(--gy-space-3); }
.newow-reference__header, .newow-reference__summary, .newow-reference__state, .newow-reference__tools { padding: var(--gy-space-3); border: 1px solid var(--gy-border); border-radius: var(--gy-radius-md); background: var(--gy-bg-panel); }
.newow-reference__header { display: flex; flex-wrap:wrap; justify-content: space-between; gap: var(--gy-space-3); }
.newow-reference h3, .newow-reference p, .newow-reference dl { margin: 0; }
.newow-reference__header p, .newow-reference__tools span, small { color: var(--gy-text-muted); }
.newow-reference__window, .newow-reference__tools, .newow-reference__presets { display: flex; flex-wrap: wrap; align-items: end; gap: var(--gy-space-2); }
.newow-reference__presets button { min-height:32px; border-radius:8px; font-size:12px; }.newow-reference__presets button[aria-pressed="true"] { background:#fff1e8; border-color:#ff6b2c; color:#c2410c; }
.newow-reference__window label { display: grid; gap: 4px; }
.newow-reference button, .newow-reference input, .newow-reference select { min-height: 44px; padding: 0 var(--gy-space-2); border: 1px solid var(--gy-border); border-radius: var(--gy-radius-sm); color: var(--gy-text-primary); background: var(--gy-bg-panel); }
.newow-reference__summary dl { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: var(--gy-space-2); }
.newow-reference__summary dl div { padding: var(--gy-space-2); background: var(--gy-bg-elevated); }
.newow-reference__summary dt { color: var(--gy-text-muted); font-size: var(--gy-font-size-xs); }
.newow-reference__summary dd { margin: 4px 0 0; font-variant-numeric: tabular-nums; }
.newow-reference__records-heading { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:4px 0; }
.newow-reference__records-heading h3 { font-size:14px; font-weight:700; }
.newow-reference__records-heading span { font-size:12px; color:#999; }
.newow-reference__cards { display:grid; gap:8px; }
.newow-reference__card { padding:10px 14px; border:1px solid #ebedf0; border-radius:10px; background:#fff; min-width:0; cursor:default; }
.newow-reference__record-top { display:flex; align-items:center; justify-content:space-between; gap:10px; margin-bottom:4px; }
.newow-reference__record-meta { display:flex; align-items:center; flex-wrap:wrap; gap:8px; font-size:12px; line-height:20px; color:#999; }
.newow-reference__period { padding:3px 7px; line-height:18px; border-radius:4px; background:#ff9500; color:#fff; font-size:12px; white-space:nowrap; }
.newow-reference__period.is-open,.newow-reference__waiting header strong { background:#007aff; color:#fff; }
.newow-reference__period.is-interrupted { background:#98a2b3; }
.newow-reference__record-return { font-size:15px; font-weight:700; line-height:22px; white-space:nowrap; }
.newow-reference__record-line { display:flex; justify-content:space-between; align-items:baseline; gap:12px; margin-top:4px; font-size:15px; font-weight:600; line-height:22px; color:#292929; font-variant-numeric:tabular-nums; }
.newow-reference__record-line > span { display:flex; flex-wrap:wrap; align-items:baseline; gap:6px; }
.newow-reference__record-line strong,.newow-reference__record-line b { font-weight:700; }
.newow-reference__record-line time { color:#999; font-size:12px; font-weight:400; white-space:nowrap; }
.newow-reference__entry,[data-direction="up"].newow-reference__record-return,[data-direction="up"].newow-reference__inline-return { color:#ff403a; }
.newow-reference__exit,[data-direction="down"].newow-reference__record-return,[data-direction="down"].newow-reference__inline-return { color:#2ac758; }
.newow-reference__valuation { color:#8992a4; }
.newow-reference__record-return[data-direction="neutral"],.newow-reference__inline-return[data-direction="neutral"] { color:#999; }
.newow-reference__interruption { margin-top:6px !important; font-size:11px; line-height:16px; color:#999; }
.newow-reference__waiting header { display:flex; gap:12px; align-items:center; margin-bottom:8px; }
.newow-reference__waiting header strong { padding:3px 7px; font-size:12px; line-height:18px; border-radius:4px; }
@media(max-width:600px) { .newow-reference__records-heading { align-items:flex-start; flex-direction:column; }.newow-reference__record-top { align-items:flex-start; }.newow-reference__record-meta { gap:6px; font-size:12px; }.newow-reference__record-return { font-size:14px; }.newow-reference__record-line { font-size:14px; }.newow-reference__record-line time { font-size:12px; }.newow-reference__card { padding:10px 12px; } }
.newow-reference__state { color: var(--gy-status-warning); }
@media (max-width: 720px) { .newow-reference__header { flex-direction: column; } }
.newow-reference__curve { padding:16px; border:1px solid #ebedf0; border-radius:8px; background:#fff; }
.newow-reference__curve header { display:flex; flex-wrap:wrap; align-items:center; gap:12px; }
.newow-reference__curve header span { color:#98a2b3; font-size:12px; }
.newow-reference__curve header b { margin-left:auto; color:#ff6b2c; font-size:20px; font-variant-numeric:tabular-nums; }
.newow-reference__curve svg { display:block; width:100%; min-height:170px; margin:12px 0; overflow:visible; }
.newow-reference__curve svg text { fill:#98a2b3; font-size:10px; }
.newow-reference__curve circle { cursor:pointer; }.newow-reference__curve circle:focus { stroke:#365af5; stroke-width:3; outline:none; }
.newow-reference__summary dd { font-size:20px; }.newow-reference__summary dl div { background:#f8f9fb; border-radius:4px; }

/* A single compact returns surface: toolbar, plot, metrics and source facts. */
.newow-reference { gap:10px; }
.newow-reference__header { border:0; border-radius:0; padding:12px 0 0; display:grid; grid-template-columns:minmax(0,1fr); gap:10px; }
.newow-reference__header > div { display:flex; align-items:baseline; flex-wrap:wrap; gap:8px 14px; }
.newow-reference__header h3 { font-size:16px; }
.newow-reference__header p,.newow-reference__header details { font-size:11px; color:#98a2b3; }
.newow-reference__header details[open] { flex-basis:100%; }
.newow-reference__window { margin:14px 0 10px; justify-content:center; align-items:center; gap:10px; }
.newow-reference__presets { align-items:center; gap:8px; }
.newow-reference__presets button { min-height:30px; padding:0 18px; border-radius:18px; font-size:13px; }
.newow-reference__presets button[aria-pressed="true"] { background:#222; border-color:#222; color:white; }
.newow-reference__custom-window { color:#98a2b3; font-size:12px; }
.newow-reference__custom-window > summary { cursor:pointer; padding:6px 8px; }
.newow-reference__custom-window > div { display:flex; flex-wrap:wrap; gap:8px; padding:8px 0; }
.newow-reference__custom-window input,.newow-reference__custom-window button { min-height:32px; font-size:12px; }
.newow-reference__curve { border:0; padding:8px 0; border-radius:0; }
.newow-reference__curve header { gap:10px; font-size:14px; }
.newow-reference__curve svg { height:220px; min-height:0; margin:10px 0 4px; }
.newow-reference__summary { padding:0; border:0; background:transparent; }
.newow-reference__summary .newow-reference__metrics { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:0; padding:6.5px 0; margin:8px 0 14px; border:1px solid #ebedf0; border-radius:10px; background:#fff; }
.newow-reference__summary .newow-reference__metrics > div { position:relative; display:flex; flex-direction:column; align-items:center; gap:2px; padding:0 8px; border-radius:0; background:transparent; border:0; }
.newow-reference__summary .newow-reference__metrics > div:not(:last-child)::after { content:''; position:absolute; right:0; top:50%; transform:translateY(-50%); height:24px; width:1px; background:#ebedf0; }
.newow-reference__metrics > div:last-child { border-right:0 !important; }
.newow-reference__metrics dd { order:-1; font-size:18px; line-height:22px; font-weight:700; color:#242424; margin:0; }
.newow-reference__metrics dd[data-direction="up"] { color:#ff403a; }
.newow-reference__metrics dd[data-direction="down"] { color:#2ac758; }
.newow-reference__metrics dd small { font-size:10px; font-weight:400; }
.newow-reference__metrics dt { font-size:11px; line-height:16px; color:#999; }
.newow-reference__availability { color:#98a2b3; font-size:11px; line-height:20px; }
.newow-reference__tools { padding:6px 0; border:0; border-top:1px solid #f2f4f7; border-radius:0; font-size:12px; align-items:center; }
.newow-reference__tools select { min-height:28px; font-size:12px; margin-left:6px; }
.newow-reference :deep(.fusion-panel) { margin:0; padding:10px 12px; font-size:12px; }
.newow-reference :deep(.fusion-panel header) { align-items:center; }
.newow-reference :deep(.fusion-panel header p) { margin:3px 0 0; font-size:11px; }
.newow-reference :deep(.fusion-panel button) { min-height:28px; padding:4px 10px; font-size:12px; }
@media(max-width:600px) { .newow-reference__curve svg { height:170px; }.newow-reference__metrics dd { font-size:16px; }.newow-reference__metrics dt { font-size:11px; }.newow-reference__presets button { padding:0 12px; } }
.newow-reference__returns-heading { display:flex; align-items:baseline; gap:10px; padding-top:10px; font-size:14px; }.newow-reference__returns-heading span { color:#98a2b3; font-size:11px; }
</style>
