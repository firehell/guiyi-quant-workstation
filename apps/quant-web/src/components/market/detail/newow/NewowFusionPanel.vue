<script setup lang="ts">
import NewowPagePerformancePanel from './NewowPagePerformancePanel.vue'
import { holdingCurvePlot, holdingCurveWindow, fusionTheoreticalCurve } from '@/utils/newowHoldingCurve'
import { computed, nextTick, ref, watch, onBeforeUnmount } from 'vue'
import { getNewowFusion, type FusionComparison } from '@/api/newowFusion'
import { NewowProductRequestError } from '@/api/newowProduct'
import { closestReferenceCurvePoint, referenceCurveAnchors, closedReferenceCurve, sumReferenceReturns, referenceCurveDrawdown } from '@/utils/newowReferenceCurve'
import { newowReferenceWindow, type NewowReferencePreset } from '@/utils/newowReferenceWindows'
import { referencePercentDisplay, referenceTimeDisplay } from '@/utils/newowDetailPresentation'
import type { NewowProductSectionResponse } from '@/types/newowProduct'
import { formatMarketDecimal, formatBeijingInstant } from '@/utils/marketDisplay'
const props = withDefaults(defineProps<{ response: NewowProductSectionResponse<'reference'>; readyToLoad?: boolean }>(), { readyToLoad: true })
const emit = defineEmits<{ 'snapshot-conflict': [token: string] }>()
const result = ref<FusionComparison | null>(null)
const pageWindow = ref<{performanceSince: string; performanceThrough: string} | null>(null)
function reloadPage(window: {performanceSince: string; performanceThrough: string}) { pageWindow.value = window; void load() }
const loading = ref(false)
const error = ref('')
let controller: AbortController | null = null
let generation = 0
const initialLoadPending = ref(true)
const waitingForInput = computed(() => initialLoadPending.value && !props.readyToLoad)
const inputKey = computed(() => JSON.stringify([props.response.meta.identity.product, props.response.meta.identity.strategy, props.response.meta.identity.frequency, props.response.meta.as_of, props.response.meta.snapshot_token, props.response.value?.reference_input_sha256, props.response.value?.performance_since, props.response.value?.performance_through]))
watch(inputKey, () => {
  pageWindow.value = null
  generation++; controller?.abort(); result.value = null; loading.value = false; error.value = ''; initialLoadPending.value = true
  void load()
}, { immediate: true })
watch(() => props.readyToLoad, ready => { if (ready && initialLoadPending.value) void load() })
onBeforeUnmount(() => { generation++; controller?.abort() })
async function load() {
  if (!props.readyToLoad) return
  result.value = null
  const value = props.response.value
  if (!value || props.response.meta.identity.strategy !== 'trend') return
  initialLoadPending.value = false
  const token = ++generation
  const requestInputKey = inputKey.value
  const snapshotToken = props.response.meta.snapshot_token
  controller?.abort(); controller = new AbortController()
  loading.value = true; error.value = ''
  const identity = props.response.meta.identity
  try {
    const next = await getNewowFusion({ identity: { product: identity.product, strategy: 'trend', frequency: identity.frequency, seriesKind: 'actual_dominant' }, section: 'reference', asOf: props.response.meta.as_of, snapshotToken: props.response.meta.snapshot_token ?? undefined, performanceSince: pageWindow.value?.performanceSince ?? value.performance_since, performanceThrough: pageWindow.value?.performanceThrough ?? value.performance_through }, { signal: controller.signal })
    if (token === generation && inputKey.value === requestInputKey) {
      if (next.reference_input_sha256 !== value.reference_input_sha256 || next.reference_cutoff !== value.reference_cutoff) {
        error.value = '融合输入已变化，请刷新当前图表后重试。'
        return
      }
      result.value = next
    }
  } catch (cause) {
    if (token === generation && inputKey.value === requestInputKey) {
      error.value = '融合参考读取失败，请重试。'
      if (props.readyToLoad && cause instanceof NewowProductRequestError && cause.code === 'NEWOW_SNAPSHOT_GENERATION_CONFLICT'
        && cause.classification === 'conflict' && snapshotToken) {
        emit('snapshot-conflict', snapshotToken)
      }
    }
  }
  finally { if (token === generation && inputKey.value === requestInputKey) loading.value = false }
}
function tone(value: string | null) { return value === null ? '' : Number(value) >= 0 ? 'gain' : 'loss' }
const names = { trend: '趋势', oscillation: '震荡', fusion: '融合' }
const states = { OPEN: '未清仓', CLOSED: '已完成', ROLLOVER_INTERRUPTED: '换月中断', DATA_INTERRUPTED: '数据中断' }
const display = (value: string | null) => value === null ? '—' : formatMarketDecimal(value)
const preset = ref<NewowReferencePreset>('all')
watch(() => result.value?.reference_revision ?? result.value?.reference_input_sha256, () => { preset.value = 'all' })
const anchor = computed(() => result.value ? new Date(Date.parse(result.value.reference_cutoff) + 8 * 3600000).toISOString().slice(0, 10) : '')
const window = computed(() => result.value ? newowReferenceWindow(anchor.value, preset.value, result.value.performance_since) : null)
const fullCurve = computed(() => {
  const data = result.value
  if (data && preset.value === 'ideal') return fusionTheoreticalCurve(data)
  const group = data?.groups.find(g => g.model === 'fusion')
  return data && group ? closedReferenceCurve(data.curve ?? data.items, group.closed_count, group.sum_return_percentage_points, 'entry_in_window_v1', data.curve === undefined && data.records_truncated) : { points: [], message: '正在读取融合参考…' }
})
const closed = computed(() => fullCurve.value.points.map(p => p.trade).filter(t => {
  const day = t.entry_trading_day ?? new Date(Date.parse(t.entry_bar_end) + 8 * 3600000).toISOString().slice(0, 10)
  return window.value && day >= window.value.performanceSince && day <= window.value.performanceThrough
}))
const total = computed(() => preset.value === 'ideal' ? result.value?.theoretical?.sum_return_percentage_points ?? null : preset.value === 'all' ? result.value?.groups.find(g => g.model === 'fusion')?.sum_return_percentage_points ?? null : closed.value.length ? sumReferenceReturns(closed.value.map(t => t.reference_return_pct!)) : null)
const curve = computed(() => fullCurve.value.message ? fullCurve.value : closedReferenceCurve(closed.value, closed.value.length, total.value))
const drawdown = computed(() => referenceCurveDrawdown(curve.value, props.response.value?.history_coverage === 'FULL'))
const winRate = computed(() => curve.value.message || !closed.value.length ? '—' : `${(100 * closed.value.filter(t => Number(t.reference_return_pct) > 0).length / closed.value.length).toFixed(1)}%`)
const annualized = computed(() => {
  if (props.response.value?.history_coverage !== 'FULL' || curve.value.message || total.value === null || !window.value || Number(total.value) <= -100) return '—'
  const days = (Date.parse(window.value.performanceThrough) - Date.parse(window.value.performanceSince)) / 86400000 + 1
  const value = (Math.pow(1 + Number(total.value) / 100, 365 / days) - 1) * 100
  return Number.isFinite(value) ? `${value.toFixed(1)}%` : '—'
})
const plot = computed(() => {
  const points = curve.value.points
  const low = Math.min(0, ...points.map(p => p.value)) * 1.1
  const high = Math.max(0, ...points.map(p => p.value)) * 1.1 || (low < 0 ? 0 : 1)
  const y = (v: number) => 140 - (v - low) / (high - low) * 140
  const start = Date.parse(window.value?.performanceSince ?? '')
  const end = Date.parse(window.value?.performanceThrough ?? '')
  const duration = end - start
  return { zero: y(0), points: points.map(p => ({ ...p, x: duration > 0 ? (Date.parse(p.trade.exit_bar_end!) + 8 * 3600000 - start) / (duration + 86400000) * 712 : 712, y: y(p.value) })),
    levels: Array.from({ length: 5 }, (_, i) => ({ y: i * 35, label: `${(high - (high - low) * i / 4).toFixed(1)}%` })),
    ticks: Number.isFinite(start) ? Array.from({ length: 7 }, (_, i) => ({ x: i / 6 * 712, day: new Date(start + duration * i / 6).toISOString().slice(5, 10) })) : [] }
})
const recordSince = computed(() => anchor.value ? newowReferenceWindow(anchor.value, 'one_year').performanceSince : '')
const isInitialRecord = (row: { entry_bar_end: string; entry_trading_day?: string; statistics_membership: string }) => row.statistics_membership === 'initial_before_window' || (row.entry_trading_day ?? new Date(Date.parse(row.entry_bar_end) + 8 * 3600000).toISOString().slice(0, 10)) < recordSince.value
const selected = ref<string | null>(null)
watch(() => result.value?.reference_revision ?? result.value?.reference_input_sha256, () => { selected.value = null })
const records = computed(() => {
  if (!result.value) return []
  const since = recordSince.value
  const focused = result.value.curve?.find(t => t.reference_trade_id === selected.value)
  const rows = focused && !result.value.items.some(t => t.reference_trade_id === focused.reference_trade_id)
    ? [focused, ...result.value.items] : result.value.items
  return rows.filter(t => t.reference_trade_id === selected.value || t.status === 'OPEN' || (t.entry_trading_day ?? new Date(Date.parse(t.entry_bar_end) + 8 * 3600000).toISOString().slice(0, 10)) >= since)
})
async function loadMore() {
  const current = result.value, value = props.response.value
  if (!props.readyToLoad || !current?.next_cursor || !value || loading.value) return
  const token = generation
  const requestInputKey = inputKey.value
  const snapshotToken = props.response.meta.snapshot_token
  const identity = props.response.meta.identity
  loading.value = true; error.value = ''
  try {
    const next = await getNewowFusion({ identity: { product: identity.product, strategy: 'trend', frequency: identity.frequency, seriesKind: 'actual_dominant' }, section: 'reference', asOf: props.response.meta.as_of, snapshotToken: props.response.meta.snapshot_token ?? undefined, performanceSince: value.performance_since, performanceThrough: value.performance_through, fusionBefore: current.next_cursor }, { signal: controller?.signal })
    if (token !== generation || inputKey.value !== requestInputKey) return
    if (next.reference_revision !== current.reference_revision) throw new Error('fusion revision conflict')
    const existing = new Set(current.items.map(item => item.reference_trade_id))
    if (next.items.some(item => existing.has(item.reference_trade_id))) throw new Error('duplicate fusion page')
    result.value = { ...current, items: [...current.items, ...next.items], next_cursor: next.next_cursor }
  } catch (cause) {
    if (token === generation && inputKey.value === requestInputKey) {
      if (cause instanceof NewowProductRequestError && cause.classification === 'conflict') result.value = null
      error.value = '记录快照已变化或读取失败，请刷新后重试。'
      if (props.readyToLoad && cause instanceof NewowProductRequestError && cause.code === 'NEWOW_SNAPSHOT_GENERATION_CONFLICT'
        && cause.classification === 'conflict' && snapshotToken) {
        emit('snapshot-conflict', snapshotToken)
      }
    }
  }
  finally { if (token === generation && inputKey.value === requestInputKey) loading.value = false }
}
async function locate(id: string) { selected.value = id; await nextTick(); document.getElementById(`fusion-trade-${id}`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }) }
const time = (instant: string) => referenceTimeDisplay(instant, props.response.meta.identity.frequency, [result.value?.reference_cutoff ?? instant])
const presets = [['three_months', '近3月'], ['one_year', '近1年'], ['three_years', '近3年'], ['ytd', '今年'], ['ideal', '理论值'], ['all', '全部']] as const

function locateCurvePoint(event: MouseEvent) {
  const bounds = (event.currentTarget as SVGElement).getBoundingClientRect()
  if (bounds.width <= 0 || bounds.height <= 0) return
  const point = closestReferenceCurvePoint(plot.value.points, (event.clientX - bounds.left) / bounds.width * 712, (event.clientY - bounds.top) / bounds.height * 140)
  if (point) locate(point.trade.reference_trade_id)
}

const curveMode = ref<'holding' | 'closed'>('holding')
const holdingIndex = ref<number | null>(null)
const holdingPlot = computed(() => {
  const data = result.value, range = window.value, group = data?.groups.find(g=>g.model === 'fusion')
  const valid = data?.curve !== undefined && group && (group.closed_count === 0 ? data.curve.length === 0 : closedReferenceCurve(data.curve, group.closed_count, group.sum_return_percentage_points).message === null)
  const source = valid && data && range ? holdingCurveWindow(data.holding_curve, data.curve!, range.performanceSince, range.performanceThrough) : null
  return holdingCurvePlot(source, range?.performanceSince ?? '', range?.performanceThrough ?? '')
})
const holdingReadout = computed(() => holdingPlot.value.points[holdingIndex.value ?? holdingPlot.value.points.length - 1] ?? null)
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
  <section class="fusion-panel newow-reference" aria-label="双策略融合参考模型" :aria-busy="loading || waitingForInput">
    <NewowPagePerformancePanel :value="result?.page_performance" :since="result?.performance_since" :through="result?.performance_through" :floor="response.value?.performance_since" :loading="loading || waitingForInput" @reload="reloadPage" />
    <details><summary>原始融合 ReferenceTrade 事实与诊断</summary><p>此处保留策略信号配对事实；页面收益投影在上方独立显示。</p>
    <header class="newow-reference__returns-heading"><strong>策略收益率走势</strong><span class="newow-reference__annualized">年化{{ annualized }}</span><button class="fusion-refresh" :disabled="loading || !readyToLoad" @click="load">{{ waitingForInput ? '读取中…' : loading ? '计算中…' : '重新计算' }}</button></header>
    <p class="fusion-caption">双策略融合 · 单仓 long/flat · 零费用、零滑点页面参考，不代表可执行收益。</p>
    <p v-if="response.value?.history_coverage === 'PARTIAL'" role="status">数据覆盖不完整，仅统计已验证片段，中断不计入已完成收益。</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="waitingForInput" role="status">正在读取另一策略参考输入…</p>
    <p v-if="loading" role="status">正在读取融合参考…</p>
    <template v-if="result">
      <div class="newow-reference__window"><div class="newow-reference__presets" aria-label="融合参考统计快捷窗口"><button v-for="item in presets" :key="item[0]" :aria-pressed="preset === item[0]" :disabled="loading" @click="preset = item[0]">{{ item[1] }}</button></div></div>

      <p v-if="preset === 'ideal'" class="newow-reference__state">融合理论值 · 回看持有阶段最高价（High）；仅计已完成配对，零费用、零滑点，不代表可执行收益。操盘记录仍显示普通参考价。</p>
      <section v-if="curveMode === 'holding' && preset !== 'ideal' && !holdingPlot.message" class="newow-reference__curve" aria-label="逐 Bar 持有过程">
          <p class="newow-reference__state">逐 Bar 页面参考 = 已完成累计 + 当根持有浮动；中断处断线，不计入已完成收益。</p>
          <div class="newow-reference__plot"><div class="newow-reference__plot-area">
            <svg viewBox="0 0 712 140" preserveAspectRatio="none" role="group" aria-label="逐 Bar 浮动参考曲线，点击查看读数" @mousemove="inspectHolding" @click="inspectHolding">
              <line v-for="level in holdingPlot.levels" :key="level.y" x1="0" x2="712" :y1="level.y" :y2="level.y" stroke="#f2f3f5" />
              <line x1="0" x2="712" :y1="holdingPlot.zero" :y2="holdingPlot.zero" stroke="#d0d5dd" stroke-dasharray="4 4" />
              <polyline v-for="(segment,i) in holdingPlot.segments" :key="i" :points="segment" fill="none" stroke="#ff403a" stroke-width="1.8" />
              <circle v-if="holdingReadout" :cx="holdingReadout.x" :cy="holdingReadout.y" r="3" fill="#ff9500" />
            </svg>
            <span v-for="level in holdingPlot.levels" :key="level.y" class="newow-reference__value-tick" :style="{ top: `${level.y / 140 * 100}%` }">{{ level.label }}</span>
          <span class="newow-reference__date-tick" data-anchor="start" style="left:0">{{ holdingPlot.points[0]?.trading_day }}</span><span class="newow-reference__date-tick" data-anchor="end" style="left:100%">{{ holdingPlot.points.at(-1)?.trading_day }}</span></div></div>
          <div class="newow-holding-readout" aria-live="polite"><button type="button" aria-label="上一根持有读数" @click="holdingIndex = Math.max(0, (holdingIndex ?? holdingPlot.points.length - 1) - 1)">‹</button><span v-if="holdingReadout">{{ formatBeijingInstant(holdingReadout.bar_end) }} · {{ holdingReadout.physical_contract }} · 已完成 {{ formatMarketDecimal(holdingReadout.closed_return_percentage_points) }} · 浮动 {{ referencePercentDisplay(holdingReadout.floating_return_pct).text }} · 合计 {{ referencePercentDisplay(holdingReadout.marked_return_percentage_points).text }}</span><button type="button" aria-label="下一根持有读数" @click="holdingIndex = Math.min(holdingPlot.points.length - 1, (holdingIndex ?? holdingPlot.points.length - 1) + 1)">›</button></div>
      </section>
<section v-if="curveMode === 'closed' || preset === 'ideal' || !result.holding_curve" class="newow-reference__curve" aria-label="融合已完成参考交易累计收益曲线">
        <p v-if="curve.message" role="status">{{ curve.message }}{{ result.records_truncated ? '记录已截断，完整统计仍见三组对比。' : '' }}</p>
        <div v-else class="newow-reference__plot"><div class="newow-reference__plot-area">
          <svg @click="locateCurvePoint" viewBox="0 0 712 140" preserveAspectRatio="none" role="group" aria-label="融合参考收益按清仓顺序累计">
            <defs><linearGradient id="fusion-reference-area" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#ff403a" stop-opacity="0.16"/><stop offset="100%" stop-color="#ff403a" stop-opacity="0.01"/></linearGradient></defs>
            <line v-for="level in plot.levels" :key="level.y" x1="0" x2="712" :y1="level.y" :y2="level.y" stroke="#f2f3f5"/>
            <polygon :points="`0,${plot.zero} ` + plot.points.map(p => `${p.x},${p.y}`).join(' ') + ` 712,${plot.points.at(-1)?.y ?? plot.zero} 712,${plot.zero}`" fill="url(#fusion-reference-area)"/>
            <line x1="0" x2="712" :y1="plot.zero" :y2="plot.zero" stroke="#d0d5dd" stroke-dasharray="4 4"/>
            <polyline :points="`0,${plot.zero} ` + plot.points.map(p => `${p.x},${p.y}`).join(' ') + ` 712,${plot.points.at(-1)?.y ?? plot.zero}`" fill="none" stroke="#ff403a" stroke-width="1.8"/>
            <circle v-for="p in referenceCurveAnchors(plot.points)" :key="p.trade.reference_trade_id" :cx="p.x" :cy="p.y" r="2" fill="#ff403a" tabindex="0" role="button" :aria-label="`${time(p.trade.exit_bar_end!)}，累计${display(p.cumulative)}百分点`" @click.stop="locate(p.trade.reference_trade_id)" @keydown.enter.prevent="locate(p.trade.reference_trade_id)" @keydown.space.prevent="locate(p.trade.reference_trade_id)"><title>{{ time(p.trade.exit_bar_end!) }} · {{ p.trade.physical_contract }} · 累计{{ display(p.cumulative) }}百分点</title></circle>
          </svg>
          <span v-for="level in plot.levels" :key="level.y" class="newow-reference__value-tick" :style="{top:`${level.y / 140 * 100}%`}">{{ level.label }}</span>
          <span v-for="tick in plot.ticks" :key="tick.x" class="newow-reference__date-tick" :data-anchor="tick.x === 0 ? 'start' : tick.x === 712 ? 'end' : 'middle'" :style="{left:`${tick.x / 712 * 100}%`}">{{ tick.day }}</span>
        </div></div>
      </section>
        <section class="newow-reference__summary"><dl class="newow-reference__metrics"><div><dt>累计收益</dt><dd :data-direction="referencePercentDisplay(total).direction">{{ referencePercentDisplay(total).text }}</dd></div><div><dt>胜率</dt><dd>{{ winRate }}</dd></div><div><dt>{{ preset === 'ideal' ? '理论曲线回撤' : '最大回撤' }}</dt><dd class="newow-reference__drawdown">{{ drawdown === null ? '—' : `${drawdown}%` }}</dd></div><div><dt>交易次数</dt><dd>{{ preset === 'all' ? result.groups.find(g => g.model === 'fusion')?.closed_count : closed.length }}</dd></div></dl></section>
      <header class="newow-reference__records-heading"><h3>回测操盘提醒</h3><span>近一年 · 历史参考推演，仅供参考，不作为实时买卖提示</span></header>
      <p v-if="result.records_truncated" role="status">仅返回最近200条融合记录，近一年记录可能不完整。</p>
      <div class="newow-reference__cards">
        <article v-for="row in records" :id="`fusion-trade-${row.reference_trade_id}`" :key="row.reference_trade_id" class="newow-reference__card" :class="{'fusion-selected':selected === row.reference_trade_id}">
          <header class="newow-reference__record-top"><div class="newow-reference__record-meta"><strong class="newow-reference__period" :class="{'is-open':row.status === 'OPEN','is-interrupted':row.status.endsWith('INTERRUPTED')}">{{ row.status === 'CLOSED' ? response.meta.identity.frequency === '1w' ? '周K' : response.meta.identity.frequency === '1d' ? '日K' : `${response.meta.identity.frequency.replace('m', '')}分钟` : states[row.status] }}</strong><span>{{ time(row.entry_bar_end) }} → {{ row.exit_bar_end ? time(row.exit_bar_end) : '尚未清仓' }}</span><span>{{ row.physical_contract }}</span><span v-if="selected === row.reference_trade_id && row.status !== 'OPEN' && (row.exit_trading_day ?? new Date(Date.parse(row.exit_bar_end ?? row.entry_bar_end) + 8 * 3600000).toISOString().slice(0, 10)) < recordSince">曲线定位 · 近一年外</span><span v-if="isInitialRecord(row)">期初已有</span></div><strong class="newow-reference__record-return" :data-direction="referencePercentDisplay(row.status === 'CLOSED' ? row.reference_return_pct : row.mark_change_pct).direction">{{ row.status === 'CLOSED' ? '盈亏' : row.status === 'OPEN' ? '未清仓浮动' : '中断浮动' }} {{ referencePercentDisplay(row.status === 'CLOSED' ? row.reference_return_pct : row.mark_change_pct).text }}</strong></header>
          <div class="newow-reference__record-line"><span><strong class="newow-reference__entry">建仓</strong> 买入 {{ display(row.entry_reference_price) }} <small>{{ names[row.entry_source] }}来源</small></span><time>{{ time(row.entry_bar_end) }}</time></div>
          <div v-if="row.status === 'CLOSED'" class="newow-reference__record-line"><span><strong class="newow-reference__exit">清仓</strong> 卖出 {{ display(row.exit_reference_price) }} <b class="newow-reference__inline-return" :data-direction="referencePercentDisplay(row.reference_return_pct).direction">{{ referencePercentDisplay(row.reference_return_pct).text }}</b><small>{{ row.exit_source ? names[row.exit_source] : '—' }}来源</small></span><time>{{ row.exit_bar_end ? time(row.exit_bar_end) : '—' }}</time></div>
          <p v-else class="newow-reference__interruption">{{ row.status === 'OPEN' ? '截至所示已完成Bar，未清仓浮动不计入已完成收益。' : '物理合约或数据区段中断，中断浮动不计入已完成收益。' }}</p>
        </article>
      </div>
      <button v-if="result.next_cursor" :disabled="loading || !readyToLoad" @click="loadMore">加载更多近一年记录</button>
      <p v-if="!records.length">近一年暂无融合参考记录。</p>
      <details><summary>三组独立统计与融合配对规则</summary><p>{{ result.performance_since }} — {{ result.performance_through }} · 截至 {{ formatBeijingInstant(result.reference_cutoff) }}<small>{{ result.reference_model_version }}</small></p><div class="fusion-panel__scroll"><table><thead><tr><th>模型</th><th>已完成</th><th>累计收益百分点</th><th>未清仓</th><th>中断</th></tr></thead><tbody><tr v-for="g in result.groups" :key="g.model"><th>{{ names[g.model] }}</th><td>{{ g.closed_count }}</td><td :class="tone(g.sum_return_percentage_points)">{{ display(g.sum_return_percentage_points) }}</td><td>{{ g.open_count }}</td><td>{{ g.interrupted_count }}</td></tr></tbody></table></div><p>累计简单相加窗口内建仓且已完成的参考收益。同根先清仓再建仓，同方向优先震荡价；允许跨策略配对，持有期间不重复建仓，不跨合约配对。期初已有、未清仓浮动和中断不计入累计。</p></details>
    </template>
    </details>
  </section>
</template>
<style scoped src="./newowReferencePanel.css"></style>
<style scoped>
.fusion-panel { margin:16px 0; }.fusion-caption,.fusion-panel details p { color:#8891a5; font-size:12px; }.fusion-refresh { margin-left:auto; }.fusion-panel__scroll { overflow:auto; } table { width:100%; border-collapse:collapse; font-size:13px; white-space:nowrap; } th,td { text-align:left; padding:10px; border-bottom:1px solid #eef0f4; }.gain { color:#ff4248; }.loss { color:#22b957; } summary { cursor:pointer; font-size:13px; margin:10px 0; }.fusion-selected { outline:2px solid #ff9500; }
</style>
