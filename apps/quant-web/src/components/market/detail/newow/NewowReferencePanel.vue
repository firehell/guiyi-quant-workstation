<script setup lang="ts">
import { holdingCurvePlot } from '@/utils/newowHoldingCurve'
import { computed, nextTick, ref, watch } from 'vue'
import { closestReferenceCurvePoint, referenceCurveAnchors, referenceCurveDrawdown, newowReferenceCurve, newowReferenceDrawdown, newowReferenceAnnualized, newowTheoreticalDisplay } from '@/utils/newowReferenceCurve'
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
  resolveNewowPanelRenderState,
} from '@/utils/newowProductViewModel'

const props = defineProps<{
  updatingStrategy?: boolean
  recordsResponse?: NewowProductSectionResponse<'reference'> | null
  recordsLoading?: boolean
  recordsError?: string | null
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
const records = computed(() => props.recordsResponse === undefined ? props.response : props.recordsResponse)
const recordsModel = computed(() => {
  const response = records.value
  if (!response?.value) return null
  const focused = (props.response?.value?.curve_trades ?? props.response?.value?.items ?? []).find(trade => trade.reference_trade_id === selectedTradeId.value)
  const items = focused && !response.value.items.some(trade => trade.reference_trade_id === focused.reference_trade_id)
    ? [focused, ...response.value.items] : response.value.items
  return buildNewowReferencePanelViewModel({ ...response, value: { ...response.value, items } }, props.chartResponse, props.crossSectionCompatible)
})
const displayValue = computed(() => props.response?.value ? acceptedPreset.value === 'ideal' ? newowTheoreticalDisplay(props.response.value) : props.response.value : null)
const displaySummary = computed(() => displayValue.value && props.response ? buildNewowReferencePanelViewModel({ ...props.response, value: displayValue.value }, props.chartResponse, props.crossSectionCompatible).summary : null)
const curve = computed(() => displayValue.value ? newowReferenceCurve(displayValue.value) : { points: [], message: '理论值所需的完整持仓区段暂不可用。' })
const maximumDrawdown = computed(() => {
  if (!displayValue.value) return null
  if (acceptedPreset.value !== 'ideal' && !holdingPlot.value.message) return referenceCurveDrawdown({ message: null, points: holdingPlot.value.points.map(p => ({ cumulative: p.marked_return_percentage_points! })) }, displayValue.value.history_coverage === 'FULL')
  return newowReferenceDrawdown(displayValue.value)
})
const annualized = computed(() => {
  if (acceptedPreset.value !== 'ideal' && !holdingPlot.value.message && displayValue.value?.history_coverage === 'FULL') {
    const points = holdingPlot.value.points
    const days = (Date.parse(points.at(-1)!.bar_end) - Date.parse(points[0]!.bar_end)) / 86400000
    const ratio = (100 + Number(points.at(-1)!.marked_return_percentage_points)) / (100 + Number(points[0]!.marked_return_percentage_points))
    const result = days > 0 && ratio > 0 ? (ratio ** (365 / days) - 1) * 100 : NaN
    return Number.isFinite(result) ? result : null
  }
  return displayValue.value && model.value ? newowReferenceAnnualized(displayValue.value) : null
})
const selectedTradeId = ref<string | null>(null)
const recordElements = new Map<string, HTMLElement>()
const curvePoints = computed(() => {
  const points = curve.value?.points ?? []
  const minimum = Math.min(0, ...points.map(p => p.value))
  const maximum = Math.max(0, ...points.map(p => p.value))
  // Public-page axis headroom follows each actual extremum, never inventing a loss below zero.
  const low = minimum < 0 ? minimum * 1.1 : 0
  const high = maximum > 0 ? maximum * 1.1 : low === 0 ? 1 : 0
  const y = (value: number) => 140 - (value - low) / (high - low) * 140
  const start = Date.parse(displayValue.value?.coverage_intervals[0]?.since ?? model.value?.performanceWindow.since ?? '')
  const through = model.value?.performanceWindow.through ?? ''
  const availableThrough = model.value?.actualAvailableThrough ?? ''
  const end = Date.parse(through < availableThrough ? through : availableThrough)
  const duration = end - start
  const x = (day: string) => (duration > 0 ? (Date.parse(day) - start) / duration : 1) * 712
  const tickCount = duration > 0 ? Math.min(7, Math.floor(duration / 86_400_000) + 1) : 1
  const ticks = Number.isFinite(start) && Number.isFinite(end) ? Array.from({ length: tickCount }, (_, index) => {
    const ratio = tickCount === 1 ? 1 : index / (tickCount - 1)
    const day = new Date(start + duration * ratio).toISOString().slice(0, 10)
    return { x: ratio * 712, day, label: day.slice(5), anchor: index === 0 && tickCount > 1 ? 'start' : index === tickCount - 1 ? 'end' : 'middle' }
  }) : []
  const levels = Array.from({ length: 5 }, (_, index) => {
    const value = high - (high - low) * index / 4
    return { y: y(value), label: `${Math.abs(value) < 0.05 ? '0.0' : value.toFixed(1)}%` }
  })
  return { levels, points: points.map(p => ({ ...p, x: x(p.trade.exit_trading_day!), y: y(p.value) })), ticks, zero: y(0), low, high }
})
async function selectCurveTrade(trade: NewowReferenceTrade): Promise<void> {
  selectedTradeId.value = trade.reference_trade_id
  await nextTick()
  recordElements.get(trade.reference_trade_id)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
}
watch(() => records.value?.value?.items, async () => {
  if (!selectedTradeId.value) return
  await nextTick()
  const record = recordElements.get(selectedTradeId.value)
  if (record) record.scrollIntoView({ block: 'nearest', behavior: 'smooth' })

})
watch(() => props.selectedSignalId, id => {
  const trade = records.value?.value?.items.find(t => t.entry_signal_id === id || t.exit_signal_id === id)
  if (trade) selectedTradeId.value = trade.reference_trade_id
})
watch(() => props.response?.value?.reference_input_sha256, () => { selectedTradeId.value = null })
// The initial request is the server-resolved full history; preserve its authoritative floor across range switches.
const availableSince = ref<string | null>(null)
const pendingPreset = ref<{ kind: NewowReferencePreset | 'complete'; since: string; through: string } | null>(null)
const acceptedPreset = ref<NewowReferencePreset | 'complete' | null>(null)
const acceptedAnchor = computed(() => model.value?.actualAvailableThrough ?? null)

// Current FLAT is a chart fact, never a synthetic trade or a guess from a history page.
const waiting = computed(() => {
  const chart = props.chartResponse
  const reference = records.value
  if ((props.recordsResponse === undefined && (props.lifecycle !== 'ready' || !props.crossSectionCompatible))
    || reference?.status.status !== 'ready' || props.chartLifecycle !== 'ready' || props.currentChartWindow !== true
    || reference.meta.snapshot_token !== chart?.meta.snapshot_token || chart?.status.status !== 'ready' || reference?.status.status !== 'ready'
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
  const sameWindow = performanceSince.value === value.performance_since && performanceThrough.value === value.performance_through
  if (availableSince.value === null) availableSince.value = value.performance_since
  performanceSince.value = value.performance_since
  performanceThrough.value = value.performance_through
  const pending = pendingPreset.value
  acceptedPreset.value = pending ? acceptedNewowReferencePreset(pending, { performanceSince: value.performance_since, performanceThrough: value.performance_through }) : sameWindow ? acceptedPreset.value : null
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
    const target = newowReferenceWindow(acceptedAnchor.value, preset, availableSince.value ?? undefined)
    pendingPreset.value = { kind: preset, since: target.performanceSince, through: target.performanceThrough }
    emit('reload', target)
  } catch { pendingPreset.value = null }
}


function locateCurvePoint(event: MouseEvent) {
  const bounds = (event.currentTarget as SVGElement).getBoundingClientRect()
  if (bounds.width <= 0 || bounds.height <= 0) return
  const point = closestReferenceCurvePoint(curvePoints.value.points, (event.clientX - bounds.left) / bounds.width * 712, (event.clientY - bounds.top) / bounds.height * 140)
  if (point) selectCurveTrade(point.trade)
}

const curveMode = ref<'holding' | 'closed'>('holding')
const analysisOpen = ref(false)
const holdingIndex = ref<number | null>(null)
const holdingPlot = computed(() => holdingCurvePlot(props.response?.value?.holding_curve, props.response?.value?.performance_since ?? '', props.response?.value?.performance_through ?? ''))
const holdingReadout = computed(() => holdingIndex.value === null ? null : holdingPlot.value.points[holdingIndex.value] ?? null)
const holdingTicks = computed(() => {
  const points = holdingPlot.value.points
  if (!points.length) return []
  return Array.from({ length: Math.min(7, points.length) }, (_, i) => {
    const p = points[Math.round(i * (points.length - 1) / (Math.min(7, points.length) - 1 || 1))]!
    return { x: p.x, day: p.trading_day, label: p.trading_day.slice(5), anchor: i === 0 ? 'start' : i === Math.min(7, points.length) - 1 ? 'end' : 'middle' }
  })
})
watch(holdingPlot, () => { holdingIndex.value = null })
function inspectHolding(event: MouseEvent) {
  const bounds = (event.currentTarget as SVGElement).getBoundingClientRect()
  if (bounds.width <= 0) return
  const x = (event.clientX - bounds.left) / bounds.width * 712
  let index = 0, distance = Infinity
  holdingPlot.value.points.forEach((p,i) => { if (Math.abs(p.x-x) < distance) { distance = Math.abs(p.x-x); index = i } })
  holdingIndex.value = index
}
</script>

<template>
  <section class="newow-reference" :aria-busy="loadingPage" aria-labelledby="newow-reference-title">
    <header class="newow-reference__returns-heading"><strong id="newow-reference-title">策略收益率走势</strong><span class="newow-reference__annualized" title="页面参考年化：按所选统计区间的实际天数，将 1 + 累计参考收益 / 100 折算一年；零费用、零滑点，不代表账户收益。">年化{{ annualized === null ? ' —' : `${annualized.toFixed(1)}%` }}</span><button type="button" class="newow-reference__analysis-link" @click="analysisOpen = true">收益分析 ›</button></header>
      <form class="newow-reference__window" @submit.prevent="reload">
        <div class="newow-reference__presets" aria-label="参考统计快捷窗口">
          <button v-for="preset in ([['three_months', '近3月'], ['one_year', '近1年'], ['three_years', '近3年'], ['ytd', '今年']] as const)" :key="preset[0]" type="button" :disabled="loadingPage || !acceptedAnchor" :aria-pressed="acceptedPreset === preset[0]" :data-pending="pendingPreset?.kind === preset[0]" @click="usePreset(preset[0])">{{ pendingPreset?.kind === preset[0] ? '读取中…' : preset[1] }}</button>
          <button type="button" class="newow-reference__ideal" :disabled="loadingPage || !acceptedAnchor || !availableSince || !response?.value?.theoretical" :aria-pressed="acceptedPreset === 'ideal'" title="全历史回看最优卖出价；不代表可执行收益" @click="usePreset('ideal')">理论值</button>
          <button type="button" :disabled="loadingPage || !acceptedAnchor || !availableSince" :aria-pressed="acceptedPreset === 'all' || (acceptedPreset === null && performanceSince === availableSince)" @click="usePreset('all')">全部</button>
        </div>
      </form>
    <p v-if="acceptedPreset === 'ideal'" class="newow-reference__state" role="status">理论值 · 趋势／主升浪回看持仓期间最高收盘价，震荡回看最高价；零费用、零滑点；仅计已完成交易，不代表可执行收益。下方操盘记录仍显示原始建仓／清仓参考价。</p>
    <p v-if="invalidWindow" class="newow-reference__state" role="alert">统计起点不能晚于统计终点。</p>

    <p v-if="presentation.message" class="newow-reference__state" role="status">
      {{ presentation.message }}
      <span v-if="presentation.staleAt">上次已验证读取时间 {{ presentation.staleAt }}</span>
    </p>

    <button v-if="lifecycle === 'not_requested' || error || lifecycle === 'unavailable'" type="button" @click="emit('retry')">{{ lifecycle === 'not_requested' ? '读取参考交易' : '重试参考交易' }}</button>
    <div v-if="!model && (updatingStrategy || lifecycle === 'loading' || chartLifecycle === 'loading')" class="newow-reference__loading-curve" aria-hidden="true" />
    <template v-if="model">

      <section v-if="curveMode === 'holding' && acceptedPreset !== 'ideal' && !holdingPlot.message" class="newow-reference__curve" aria-label="逐 Bar 持有过程">
          <div class="newow-reference__plot"><div class="newow-reference__plot-area">
            <svg viewBox="0 0 712 140" preserveAspectRatio="none" role="group" aria-label="逐 Bar 浮动参考曲线，点击查看读数" @mousemove="inspectHolding" @mouseleave="holdingIndex = null" @click="inspectHolding">
              <defs><linearGradient id="newow-holding-area" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#ff403a" stop-opacity="0.14" /><stop offset="100%" stop-color="#ff403a" stop-opacity="0.01" /></linearGradient></defs>
              <polygon v-for="(segment,i) in holdingPlot.segments" :key="`area-${i}`" :points="`${segment.trim().split(' ')[0]?.split(',')[0]},${holdingPlot.zero} ${segment} ${segment.trim().split(' ').at(-1)?.split(',')[0]},${holdingPlot.zero}`" fill="url(#newow-holding-area)" />
              <line v-if="holdingReadout" :x1="holdingReadout.x" :x2="holdingReadout.x" y1="0" y2="140" stroke="#bbb" stroke-dasharray="3 3" />
              <line v-for="level in holdingPlot.levels" :key="level.y" x1="0" x2="712" :y1="level.y" :y2="level.y" stroke="#f2f3f5" />
              <line x1="0" x2="712" :y1="holdingPlot.zero" :y2="holdingPlot.zero" stroke="#d0d5dd" stroke-dasharray="4 4" />
              <polyline v-for="(segment,i) in holdingPlot.segments" :key="i" :points="segment" fill="none" stroke="#ff403a" stroke-width="1.8" />
              <circle v-if="holdingReadout" :cx="holdingReadout.x" :cy="holdingReadout.y" r="3" fill="#ff9500" />
            </svg>
            <span v-for="level in holdingPlot.levels" :key="level.y" class="newow-reference__value-tick" :style="{ top: `${level.y / 140 * 100}%` }">{{ level.label }}</span>
          <span v-for="tick in holdingTicks" :key="tick.x" class="newow-reference__date-tick" :data-anchor="tick.anchor" :title="tick.day" :style="{ left: `${tick.x / 712 * 100}%` }">{{ tick.label }}</span></div></div>
          <div v-if="holdingReadout" class="newow-reference__tooltip" aria-live="polite">{{ formatBeijingInstant(holdingReadout.bar_end) }} · {{ referencePercentDisplay(holdingReadout.marked_return_percentage_points).text }}</div>
      </section>
<section class="newow-reference__curve newow-reference__completed" aria-label="已完成参考交易累计收益曲线">
        <p v-if="(curveMode === 'closed' || acceptedPreset === 'ideal' || !!holdingPlot.message) && curve?.message" role="status">{{ curve.message }}</p>
        <template v-if="!curve.message && (curveMode === 'closed' || acceptedPreset === 'ideal' || !!holdingPlot.message)">
          <div class="newow-reference__plot">
            <div class="newow-reference__plot-area">
              <svg @click="locateCurvePoint" viewBox="0 0 712 140" preserveAspectRatio="none" role="group" aria-label="按清仓顺序累计的参考收益，每个点可定位交易记录">
                <defs><linearGradient id="newow-reference-area" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#ff403a" stop-opacity="0.16" /><stop offset="100%" stop-color="#ff403a" stop-opacity="0.01" /></linearGradient></defs>
                <line v-for="level in curvePoints.levels" :key="level.y" x1="0" x2="712" :y1="level.y" :y2="level.y" stroke="#f2f3f5" />
                <polygon :points="`0,${curvePoints.zero} ` + curvePoints.points.map(p => `${p.x},${p.y}`).join(' ') + ` 712,${curvePoints.points.at(-1)?.y ?? curvePoints.zero} 712,${curvePoints.zero}`" fill="url(#newow-reference-area)" />
                <line x1="0" x2="712" :y1="curvePoints.zero" :y2="curvePoints.zero" stroke="#d0d5dd" stroke-dasharray="4 4" />
                <polyline :points="`0,${curvePoints.zero} ` + curvePoints.points.map(p => `${p.x},${p.y}`).join(' ') + ` 712,${curvePoints.points.at(-1)?.y ?? curvePoints.zero}`" fill="none" stroke="#ff403a" stroke-width="1.8" />
                <circle v-for="point in referenceCurveAnchors(curvePoints.points)" :key="point.trade.reference_trade_id" :cx="point.x" :cy="point.y" :r="selectedTradeId === point.trade.reference_trade_id ? 4 : 2" class="newow-reference__trade-point" :fill="point.value >= 0 ? '#ff403a' : '#22b95d'" stroke="white" role="button" tabindex="0" :aria-label="`${point.trade.exit_trading_day}，累计 ${formatMarketDecimal(point.cumulative)} 百分点，定位参考交易`" @click.stop="selectCurveTrade(point.trade)" @keydown.enter.prevent="selectCurveTrade(point.trade)" @keydown.space.prevent="selectCurveTrade(point.trade)"><title>{{ point.trade.exit_trading_day }} · {{ point.trade.physical_contract }} · 单笔 {{ referencePercentDisplay(point.trade.reference_return_pct).text }} · 累计 {{ formatMarketDecimal(point.cumulative) }} 百分点</title></circle>
              </svg>
            <span v-for="level in curvePoints.levels" :key="level.y" class="newow-reference__value-tick" :style="{ top: `${level.y / 140 * 100}%` }">{{ level.label }}</span>
            <span v-for="tick in curvePoints.ticks" :key="tick.x" class="newow-reference__date-tick" :title="tick.day" :data-anchor="tick.anchor" :style="{ left: `${tick.x / 712 * 100}%` }">{{ tick.label }}</span>
            </div>
          </div>
        </template>
      <section class="newow-reference__summary" data-testid="newow-reference-summary" aria-label="参考交易统计摘要">
        <div v-if="response?.value?.history_coverage === 'PARTIAL'" role="status">
          <p>历史覆盖不完整；仅统计有效区段内已完成的参考交易，跨中断记录不计入收益。</p>
          <ul><li v-for="interval in response.value.coverage_intervals" :key="`${interval.segment_id}:${interval.since}:${interval.status}`">{{ interval.since }} → {{ interval.through }} · {{ interval.physical_contract }} · {{ interval.status === 'VALID' ? '有效计算区段' : interval.status === 'PRICE_UNAVAILABLE' ? '来源价格不可用' : '重新预热中' }}</li></ul>
        </div>
        <dl class="newow-reference__metrics">
          <div><dt>累计收益</dt><dd title="已完成页面参考交易收益简单累加；零费用、零滑点，不代表账户收益。" :data-direction="referencePercentDisplay(displayValue?.summary.sum_return_percentage_points).direction">{{ referencePercentDisplay(displayValue?.summary.sum_return_percentage_points).text }}</dd></div>
          <div><dt>胜率</dt><dd>{{ displaySummary?.winRateText ?? '—' }}</dd></div>
          <div><dt>最大回撤</dt><dd class="newow-reference__drawdown" :title="response?.value?.holding_curve && acceptedPreset !== 'ideal' ? '页面参考回撤，以100为起点，包含持有浮动；不是账户回撤。' : '已完成交易累计回撤，以100为起点，不含持仓浮动。'">{{ maximumDrawdown === null ? '—' : `${maximumDrawdown}%` }}</dd></div>
          <div><dt>交易次数</dt><dd>{{ model.summary.closedCount }}</dd></div>
        </dl>
        <p v-if="response?.status.reason_code" class="newow-reference__availability" role="status">{{ model.statusExplanation }}</p>

        <p v-if="model.summary.closedCount === 0">暂无已完成参考交易；统计指标不是 0%。</p>
        <button v-if="model.completeWindowAction" type="button" :disabled="loadingPage" @click="useCompleteWindow">使用最近完整统计区间</button>
      </section>
      </section>

    </template>
    <div v-if="analysisOpen" class="newow-reference__analysis-backdrop" @click.self="analysisOpen = false">
      <section class="newow-reference__analysis-dialog" role="dialog" aria-modal="true" aria-label="收益分析" tabindex="-1" @keydown.esc="analysisOpen = false">
        <header><strong>收益分析</strong><button type="button" aria-label="关闭收益分析" @click="analysisOpen = false">×</button></header>
        <p>{{ performanceSince }} 至 {{ performanceThrough }} · {{ response?.meta.identity.product.toUpperCase() }} · {{ response?.meta.identity.frequency }}</p>
        <dl><div><dt>累计收益</dt><dd>{{ referencePercentDisplay(displayValue?.summary.sum_return_percentage_points).text }}</dd></div><div><dt>胜率</dt><dd>{{ displaySummary?.winRateText ?? '—' }}</dd></div><div><dt>最大回撤</dt><dd>{{ maximumDrawdown === null ? '—' : `${maximumDrawdown}%` }}</dd></div><div><dt>交易次数</dt><dd>{{ model?.summary.closedCount ?? '—' }}</dd></div></dl>
        <p>收益按已完成页面参考交易简单累加，零手续费、零滑点。持有曲线包含当根收盘价浮动；换月和数据中断处断线。</p>
        <p>{{ acceptedPreset === 'ideal' || holdingPlot.message ? '当前曲线仅含已完成累计，未包含持仓浮动。' : '最大回撤按持有曲线、以100为起点计算权益比例回撤。' }}期货参考统计保留入场属于窗口的口径；未清仓不计入交易次数。</p>
        <p>历史页面参考，不代表因果回测或账户收益；历史表现不代表未来收益。</p>
        <button type="button" @click="analysisOpen = false">知道了</button>
      </section>
    </div>
    <template v-if="recordsModel">
      <header class="newow-reference__records-heading"><h3>回测操盘提醒</h3><span>近一年 · 历史参考推演，仅供参考，不作为实时买卖提示</span></header>
      <article v-if="waiting" class="newow-reference__card newow-reference__waiting" data-testid="newow-reference-waiting">
        <header><strong>空仓等待中</strong><span>策略空仓 · {{ waiting.physical_contract }}</span></header>
        <p :title="waiting.bar_end">状态时间 {{ referenceTimeDisplay(waiting.bar_end, chartResponse!.meta.identity.frequency, [chartResponse!.meta.as_of]) }} · 截至所示已完成 Bar，仅作页面参考。</p>
      </article>

      <div class="newow-reference__cards">
        <article v-for="row in recordsModel.rows" :key="row.id" :ref="element => { if (element) recordElements.set(row.id, element as HTMLElement); else recordElements.delete(row.id) }" :id="`reference-trade-${row.id}`" class="newow-reference__card" :data-reference-category="row.category" :data-reference-initial="row.initial">
          <header class="newow-reference__record-top">
            <div class="newow-reference__record-meta"><strong class="newow-reference__period" :class="{ 'is-open': row.category === 'open', 'is-interrupted': row.category === 'interrupted' }">{{ row.category === 'open' ? '持仓参考中' : row.category === 'interrupted' ? (row.trade.status === 'DATA_INTERRUPTED' ? '数据中断' : '换月中断') : row.trade.frequency === '1w' ? '周K' : row.trade.frequency === '1d' ? '日K' : `${row.trade.frequency.replace('m', '')}分` }}</strong><span>{{ rowTime(row.trade, row.trade.entry_bar_end) }} → {{ row.category === 'open' ? '至估值日' : rowTime(row.trade, row.trade.exit_bar_end ?? row.trade.interrupted_at) }}</span><span>{{ row.trade.physical_contract }}</span><span v-if="row.initial">期初已有</span></div>
            <strong class="newow-reference__record-return" :data-direction="referencePercentDisplay(row.category === 'closed' ? row.trade.reference_return_pct : row.trade.mark_change_pct).direction">{{ row.category === 'closed' ? '盈亏' : row.category === 'open' ? '参考浮动' : '中断浮动' }} {{ referencePercentDisplay(row.category === 'closed' ? row.trade.reference_return_pct : row.trade.mark_change_pct).text }}</strong>
          </header>
          <div class="newow-reference__record-line"><span><b class="newow-reference__entry">建仓</b> <span>买入</span> <strong>{{ formatMarketDecimal(row.trade.entry_reference_price) }}</strong></span><time :datetime="row.trade.entry_bar_end">{{ rowTime(row.trade, row.trade.entry_bar_end) }}</time></div>
          <div v-if="row.category === 'closed'" class="newow-reference__record-line"><span><b class="newow-reference__exit">清仓</b> <span>卖出</span> <strong>{{ formatMarketDecimal(row.trade.exit_reference_price) }}</strong> <strong class="newow-reference__inline-return" :data-direction="referencePercentDisplay(row.trade.reference_return_pct).direction">{{ referencePercentDisplay(row.trade.reference_return_pct).text }}</strong></span><time :datetime="row.trade.exit_bar_end ?? undefined">{{ rowTime(row.trade, row.trade.exit_bar_end) }}</time></div>
          <div v-else class="newow-reference__record-line"><span><b class="newow-reference__valuation">参考估值</b> <strong>{{ formatMarketDecimal(row.trade.mark_reference_price) }}</strong></span><time :datetime="row.trade.mark_bar_end ?? undefined">{{ rowTime(row.trade, row.trade.mark_bar_end) }}</time></div>
          <p v-if="row.category === 'interrupted'" class="newow-reference__interruption">{{ referenceInterruptionLabel(row.trade.interruption_reason) }} · 中断浮动不计入已完成收益</p>
          <p v-else-if="row.category === 'open'" class="newow-reference__interruption">未清仓 · 浮动不计入已完成收益</p>
        </article>
      </div>
      <p v-if="recordsModel.rows.length === 0" class="newow-reference__state">暂无参考交易记录。</p>
      <p v-if="locateMessage" class="newow-reference__state" role="status">{{ locateMessage }}</p>
      <button v-if="recordsModel.nextBefore" type="button" :disabled="recordsLoading" @click="emit('load-more')">加载更多参考历史</button>
    </template>
    <p v-if="recordsLoading" role="status">正在读取近一年操盘记录…</p>
    <p v-if="recordsError" role="status">{{ recordsError }} <button @click="emit('load-more')">重试记录</button></p>
  </section>
</template>

<style scoped src="./newowReferencePanel.css"></style>
