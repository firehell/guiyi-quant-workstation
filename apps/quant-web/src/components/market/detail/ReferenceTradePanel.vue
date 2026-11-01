<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import ReturnCurveSvg from '@/components/charts/ReturnCurveSvg.vue'
import PerformancePanel from '../../performance/PerformancePanel.vue'
import MarketDetailDrawer from './MarketDetailDrawer.vue'
import { referencePanelSupported } from '@/utils/referencePanelPeriods'
import { useForwardReferencePanel } from '@/composables/useForwardReferencePanel'
import { formatBeijingInstant, formatDecimalText } from '@/utils/marketDisplay'
import { newowReferencePrice } from '@/utils/newowPagePresentation'
import { returnCurveLayout } from '@/utils/returnCurveLayout'
import { newowReferenceWindow, type NewowReferencePreset } from '@/utils/newowReferenceWindows'
import type { ReferenceTradeView } from '@/types/referenceTrading'
const props = defineProps<{ strategy: string; product: string; frequency: string; through?: string; seriesKind?: string }>()
const emit = defineEmits<{ focus: [identity: { barEnd: string; physicalContract: string }] }>()
const reference = useForwardReferencePanel()
const preset = ref<NewowReferencePreset | null>(null)
const pendingPreset = ref<NewowReferencePreset | null>('three_months')
let readGeneration = 0
const showAll = ref(false), analysis = ref(false)
const selected = ref<string | null>(null)
const sinceInput = ref(''), throughInput = ref('')
const supported = computed(() => referencePanelSupported(props.strategy, props.frequency, props.seriesKind))
const through = computed(() => props.through?.slice(0, 10) ?? '')
const window = ref({ since: '', through: '' })
const data = reference.data
const summary = computed(() => data.value?.summary)
const start = computed(() => data.value?.page.stream.recording_start?.slice(0, 10))
const rows = computed(() => showAll.value ? reference.rows.value : reference.rows.value.slice(0, 3))
const plot = computed(() => returnCurveLayout((data.value?.curve ?? []).map(point => ({ ...point, value: Number(point.value), position: Date.parse(point.bar_end) })), {
  headroom: 1.1, areaBaseline: 'zero', valueUnit: 'percentage_points', singlePoint: 'start',
}))
const invalidDates = computed(() => !sinceInput.value || !throughInput.value || sinceInput.value > throughInput.value)
function reset() {
  readGeneration++; reference.dispose(); preset.value = null; pendingPreset.value = 'three_months'; showAll.value = false; selected.value = null; analysis.value = false
  if (!supported.value || !through.value) return
  const chosen = newowReferenceWindow(through.value, 'three_months')
  window.value = { since: chosen.performanceSince, through: chosen.performanceThrough }
  sinceInput.value = window.value.since; throughInput.value = window.value.through
  void read()
}
async function read(force = false) {
  const own = ++readGeneration, requested = { ...window.value }, requestedPreset = pendingPreset.value
  preset.value = null
  await reference.refresh({ strategy: props.strategy, product: props.product, frequency: props.frequency, mode: 'forward_observation' }, requested, force)
  if (own !== readGeneration) return
  const accepted = data.value?.page.window
  if (accepted?.since === requested.since && accepted?.through === requested.through) preset.value = requestedPreset
}
function usePreset(value: NewowReferencePreset) {
  if (!through.value) return
  const chosen = newowReferenceWindow(through.value, value, start.value)
  pendingPreset.value = value; showAll.value = false; selected.value = null
  window.value = { since: chosen.performanceSince, through: chosen.performanceThrough }
  sinceInput.value = window.value.since; throughInput.value = window.value.through
  void read()
}
function customWindow() {
  if (invalidDates.value) return
  pendingPreset.value = null
  window.value = { since: sinceInput.value, through: throughInput.value }; showAll.value = false; selected.value = null
  void read()
}
const text = (value: unknown) => typeof value === 'string' ? value : null
const pct = (value: unknown) => value == null ? '—' : `${formatDecimalText(text(value), { maximumFractionDigits: 2, signed: true })}%`
const direction = (value: unknown) => value == null ? 'neutral' : Number(value) > 0 ? 'up' : Number(value) < 0 ? 'down' : 'neutral'
const shortDate = (value: string | null) => value ? formatBeijingInstant(value).slice(0, 16) : '—'
function label(row: ReferenceTradeView) { return row.status === 'OPEN' ? '持仓参考中' : row.status === 'CLOSED' ? '已完成参考' : row.status === 'OBSERVATION_INTERRUPTED' ? '观察中断' : '参考中断' }
function focus(row: ReferenceTradeView) { if (typeof row.physical_contract === 'string') emit('focus', { barEnd: row.entry_bar_end, physicalContract: row.physical_contract }) }
const cardElements = new Map<string, HTMLElement>()
async function selectPoint(id: string) { selected.value = id; showAll.value = true; await nextTick(); cardElements.get(id)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }) }
function clickCurve(event: MouseEvent) {
  const rect = (event.currentTarget as SVGElement).getBoundingClientRect()
  if (!rect.width || !plot.value.points.length) return
  const x = (event.clientX - rect.left) / rect.width * 712
  const point = plot.value.points.reduce((best, next) => Math.abs(next.x - x) < Math.abs(best.x - x) ? next : best)
  void selectPoint(point.reference_trade_id)
}
watch(() => [props.strategy, props.product, props.frequency, props.seriesKind, through.value], reset, { immediate: true })
onBeforeUnmount(() => { readGeneration++; reference.dispose() })
</script>
<template>
  <section v-if="supported" class="newow-reference forward-reference" aria-label="实时参考收益与记录" :aria-busy="reference.loading.value" data-reference-mode="forward_observation">
    <PerformancePanel class="newow-reference__performance" kind="实时留存参考交易" :show-details="false" :loading="reference.loading.value" :error="reference.error.value">
      <template #header><header class="newow-reference__returns-heading"><h3>实时参考收益走势</h3><button type="button" @click="analysis = true">收益分析 ›</button></header></template>
      <nav class="newow-reference__presets" aria-label="实时参考统计快捷窗口">
        <button v-for="entry in ([['three_months','近3月'],['one_year','近1年'],['three_years','近3年'],['ytd','今年'],['all','全部']] as const)" :key="entry[0]" type="button" :disabled="reference.loading.value || !supported || !through || (entry[0] === 'all' && !start)" :aria-pressed="preset === entry[0]" @click="usePreset(entry[0])">{{ entry[1] }}</button>
      </nav>
      <p v-if="!through" role="status">等待已确认行情的交易日，暂不推算统计窗口。</p>
      <p v-if="reference.error.value"><button type="button" :disabled="reference.loading.value" @click="read(true)">重新读取</button></p>
      <div v-if="data && plot.points.length" class="newow-reference__curve">
        <ReturnCurveSvg :plot="plot" label="已完成实时参考交易累计收益曲线，点击或按回车定位记录" area zero-line @select="index => selectPoint(plot.points[index]!.reference_trade_id)" @click="clickCurve" />
        <p class="forward-reference__note">曲线 {{ data.curve.length }} / {{ data.total_curve_points }} 个已平参考点；统计按完整结果计算。</p>
      </div>
      <p v-else-if="data" class="newow-reference__curve forward-reference__empty" role="status">所选窗口暂无已完成实时参考交易；不以历史重算补齐曲线。</p>
      <p v-if="plot.message" role="status">{{ plot.message }}</p>
      <section v-if="summary" class="newow-reference__summary"><dl class="newow-reference__metrics">
        <div><dt>累计参考收益</dt><dd :data-direction="direction(summary.sum_return_percentage_points)">{{ summary.closed_count ? formatDecimalText(summary.sum_return_percentage_points, { maximumFractionDigits: 2, signed: true }) + ' 百分点' : '—' }}</dd></div>
        <div><dt>参考胜率</dt><dd>{{ summary.win_rate_pct === null ? '—' : formatDecimalText(summary.win_rate_pct, { maximumFractionDigits: 1 }) + '%' }}</dd></div>
        <div><dt>累计百分点回撤</dt><dd class="newow-reference__drawdown">{{ data?.drawdown_percentage_points == null ? '—' : formatDecimalText(data.drawdown_percentage_points, { maximumFractionDigits: 2 }) + ' 百分点' }}</dd></div>
        <div><dt>已完成参考交易</dt><dd>{{ summary.closed_count }}</dd></div>
      </dl></section>
      <header class="newow-reference__records-heading"><h3>实时留存参考记录</h3><span>首次记录 · 零费用／零滑点 · 非账户成交</span></header>
      <div class="newow-reference__cards"><article v-for="row in rows" :key="row.reference_trade_id" :ref="el => { if (el) cardElements.set(row.reference_trade_id, el as HTMLElement); else cardElements.delete(row.reference_trade_id) }" :data-reference-trade-id="row.reference_trade_id" class="newow-reference__card" :class="{ 'forward-reference__selected': selected === row.reference_trade_id }">
        <header class="newow-reference__record-top"><div class="newow-reference__record-meta"><strong class="newow-reference__period" :class="{ 'is-open': row.status === 'OPEN', 'is-interrupted': !['OPEN','CLOSED'].includes(row.status) }">{{ label(row) }}</strong><span>{{ row.side === 'LONG' ? '多' : '空' }} · {{ row.physical_contract }}</span><span v-if="row.entry_trading_day < window.since">窗口初始</span></div><strong class="newow-reference__record-return" :data-direction="direction(row.status === 'CLOSED' ? row.reference_return : row.mark_return)">{{ row.status === 'CLOSED' ? '盈亏 ' + pct(row.reference_return) : row.status === 'OPEN' ? '参考浮动 ' + pct(row.mark_return) : '中断 · 未计收益' }}</strong></header>
        <div class="newow-reference__record-line"><span><b class="newow-reference__entry">建仓</b>参考 {{ newowReferencePrice(row.entry_reference_price) }}</span><time>{{ shortDate(row.entry_bar_end) }}</time></div>
        <div v-if="['OPEN', 'CLOSED'].includes(row.status)" class="newow-reference__record-line"><span><b :class="row.status === 'CLOSED' ? 'newow-reference__exit' : 'newow-reference__valuation'">{{ row.status === 'CLOSED' ? '清仓' : '估值' }}</b>参考 {{ newowReferencePrice(row.status === 'CLOSED' ? row.exit_reference_price : text(row.mark_reference_price)) }}</span><time>{{ shortDate(row.status === 'CLOSED' ? row.exit_bar_end : text(row.mark_bar_end)) }}</time></div>
        <button type="button" class="forward-reference__focus" @click="focus(row)">定位图表</button>
      </article></div>
      <p v-if="data && !rows.length" role="status">所选窗口暂无实时留存参考记录。</p>
      <p v-if="selected && !reference.rows.value.some(row => row.reference_trade_id === selected)" role="status">该收益点对应较早记录，请读取更多后查看。</p>
      <p v-if="data" class="newow-reference__record-count">{{ showAll ? `已显示 ${rows.length} 笔参考记录` : '仅展示最近 3 笔参考记录' }}</p>
      <div v-if="data && reference.rows.value.length > 3 && !showAll" class="newow-reference__view-all"><button type="button" @click="showAll = true">查看全部</button></div>
      <button v-if="showAll && reference.hasMore() && !reference.capped.value" type="button" :disabled="reference.moreLoading.value" @click="reference.loadMore()">{{ reference.moreLoading.value ? '读取中…' : '读取更多参考记录' }}</button>
      <p v-if="reference.moreError.value" role="alert">{{ reference.moreError.value }} <button type="button" @click="read(true)">重新读取</button></p><p v-if="reference.capped.value" role="status">已达展示容量，请缩小日期窗口。</p>
      <details v-if="data" class="forward-reference__note"><summary>记录范围与来源</summary><p>{{ window.since }} → {{ window.through }} · 首次记录起点 {{ formatBeijingInstant(data.page.stream.recording_start) }} · 计算至 {{ formatBeijingInstant(data.page.coverage?.computed_through) }}</p><p>观察连续性：{{ data.page.coverage?.complete_window_proven ? '已证明' : '待核对，不能视为完整运行记录' }}。未平 {{ summary?.open_count }} · 中断 {{ summary?.interrupted_count }} · 窗口初始 {{ summary?.initial_count }}；均不计入已平累计。百分点之和不是账户复利收益，不折算年化。</p></details>
    </PerformancePanel>
    <MarketDetailDrawer :open="analysis" title="实时参考收益分析" @close="analysis = false">
      <dl v-if="summary" class="forward-reference__analysis-metrics"><div><dt>累计参考收益</dt><dd>{{ summary.closed_count ? formatDecimalText(summary.sum_return_percentage_points, { maximumFractionDigits: 2, signed: true }) + ' 百分点' : '—' }}</dd></div><div><dt>参考胜率</dt><dd>{{ pct(summary.win_rate_pct) }}</dd></div><div><dt>累计百分点回撤</dt><dd>{{ data?.drawdown_percentage_points == null ? '—' : formatDecimalText(data.drawdown_percentage_points, { maximumFractionDigits: 2 }) + ' 百分点' }}</dd></div><div><dt>已完成参考交易</dt><dd>{{ summary.closed_count }}</dd></div></dl>
      <p>仅统计首次实时留存参考交易；不包含盘后重算、火天大有重绘、Paper 或真实账户成交。</p><p>按入场交易日窗口统计已完成记录。累计为收益百分比之和；回撤为累计百分点曲线的峰谷差，非账户权益回撤。曲线可能采样，统计使用完整结果。</p><form class="forward-reference__dates" @submit.prevent="customWindow"><label>开始交易日<input v-model="sinceInput" type="date" aria-label="实时参考开始交易日" /></label><label>结束交易日<input v-model="throughInput" type="date" aria-label="实时参考结束交易日" /></label><button type="submit" :disabled="invalidDates || reference.loading.value || !supported">读取参考</button></form><p v-if="invalidDates" role="alert">请选择有效的开始／结束交易日。</p></MarketDetailDrawer>
  </section>
</template>
<style scoped src="./newow/newowReferencePanel.css"></style>
<style scoped>
.forward-reference{min-width:0}.forward-reference :deep(.performance-panel){border:0;padding:0;background:transparent}.forward-reference__empty{min-height:180px;display:grid;place-items:center;color:var(--gy-text-muted);font-size:13px}.forward-reference__note{font-size:11px;color:var(--gy-text-muted);line-height:1.7}.forward-reference__selected{outline:2px solid var(--gy-accent)}.forward-reference__focus{font-size:11px;min-height:28px;margin-top:6px}.forward-reference__dates{display:flex;flex-wrap:wrap;gap:10px;align-items:end}.forward-reference__dates label{display:grid;gap:5px}.forward-reference__dates input{max-width:180px}
</style>

<style scoped>
.forward-reference__analysis-metrics{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.forward-reference__analysis-metrics dt{font-size:12px;color:var(--gy-text-muted)}.forward-reference__analysis-metrics dd{margin:4px 0;font-weight:600}
</style>
