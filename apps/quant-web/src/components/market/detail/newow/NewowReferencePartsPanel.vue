<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import PerformancePanel from '../../../performance/PerformancePanel.vue'
import ReturnCurveSvg from '../../../charts/ReturnCurveSvg.vue'
import NewowDetailDialog from './NewowDetailDialog.vue'
import { returnCurveLayout } from '@/utils/returnCurveLayout'
import { newowReferenceWindow, type NewowReferencePreset } from '@/utils/newowReferenceWindows'
import { formatBeijingInstant, formatMarketDecimal } from '@/utils/marketDisplay'
import { referencePercentDisplay } from '@/utils/newowDetailPresentation'
import { newowReferencePoints, newowReferencePrice } from '@/utils/newowPagePresentation'
import type { useNewowReferenceParts } from '@/composables/useNewowReferenceParts'
import type { NewowProductSectionResponse, NewowReferenceMode, NewowReferencePartPoint, NewowReferenceRecord, NewowReferenceTrade } from '@/types/newowProduct'

const props = defineProps<{
  state: ReturnType<typeof useNewowReferenceParts>
  chart: NewowProductSectionResponse<'chart'> | null
  fusion: boolean
  selectedSignalId: string | null
}>()
const emit = defineEmits<{ locate: [trade: NewowReferenceTrade, endpoint: 'entry' | 'exit'] }>()
const fact = ref<'page' | 'holding' | 'closed'>('page')
const ideal = ref(props.state.mode.value.includes('page_ideal'))
const preset = ref<NewowReferencePreset>(ideal.value ? 'ideal' : 'all')
const analysisOpen = ref(false)
const selectedId = ref<string | null>(null)
const selectedPoint = ref<NewowReferencePartPoint | null>(null)
const recordElements = new Map<string, HTMLElement>()
const overview = computed(() => props.state.overview.value?.value?.reference_part === 'overview' ? props.state.overview.value.value : null)
const curve = computed(() => props.state.curve.value?.value?.reference_part === 'curve' ? props.state.curve.value.value.curve : null)
const history = computed(() => props.state.history.value?.value?.reference_part === 'history' ? props.state.history.value.value : null)
const anchor = computed(() => overview.value?.actual_available_through ?? '')
const floor = ref<string | null>(null)
watch(() => props.chart?.meta.snapshot_token, () => { floor.value = null; selectedId.value = null; ideal.value = props.state.mode.value.includes('page_ideal'); preset.value = ideal.value ? 'ideal' : 'all'; fact.value = 'page' })
watch(overview, value => { if (value && floor.value === null) floor.value = value.performance_since })
watch(() => props.state.mode.value, () => { selectedId.value = null; selectedPoint.value = null; analysisOpen.value = false })
watch(curve, () => { selectedId.value = null; selectedPoint.value = null })

function modeFor(nextFact = fact.value, nextIdeal = ideal.value): NewowReferenceMode {
  const name = nextFact === 'page' ? nextIdeal ? 'page_ideal' : 'page_ordinary'
    : nextIdeal ? 'theoretical' : nextFact
  return (props.fusion ? `fusion_${name}` : name) as NewowReferenceMode
}
function setFact(next: typeof fact.value) {
  fact.value = next
  props.state.select(modeFor())
}
function usePreset(next: NewowReferencePreset) {
  if (!anchor.value || !floor.value) return
  const window = newowReferenceWindow(anchor.value, next, floor.value)
  ideal.value = next === 'ideal'
  preset.value = next
  props.state.select(modeFor(), window)
}
function retry() { void props.state.load() }

const pageMode = computed(() => props.state.mode.value.includes('page_'))
const metrics = computed(() => curve.value?.metrics ?? null)
const shownReturn = computed(() => metrics.value?.return_percentage_points ?? null)
const shownWinRate = computed(() => metrics.value?.win_rate_pct ?? null)
const shownDrawdown = computed(() => metrics.value?.drawdown ?? null)
const drawdownLabel = computed(() => {
  if (pageMode.value) return metrics.value?.drawdown_kind === 'peak_difference' ? '页面曲线回撤（百分点）'
    : metrics.value?.drawdown_kind === 'maximum_trade_loss' ? '单笔最大亏损（百分点）'
    : metrics.value?.drawdown_kind === 'mixed_segment' ? '分段页面损失统计（百分点）'
    : '页面回撤口径未确认'
  return '参考权益比例回撤'
})
const drawdownText = computed(() => pageMode.value
  ? drawdownLabel.value === '页面回撤口径未确认' ? '—' : newowReferencePoints(shownDrawdown.value).replace(/^\+/, '')
  : shownDrawdown.value === null ? '—' : `${formatMarketDecimal(shownDrawdown.value)}%`)
const plot = computed(() => {
  const calendar = fact.value !== 'page'
  const points = (curve.value?.points ?? []).map((point, sampledIndex) => {
    const date = calendar && point.trade?.exit_trading_day ? point.trade.exit_trading_day : point.trading_day
    return { ...point, value: point.value === null ? null : Number(point.value), date,
      position: calendar ? Date.parse(date) : point.position, sampledIndex,
      segment: point.segment_id }
  })
  return returnCurveLayout(points, { headroom: 1.1, areaBaseline: calendar ? 'zero' : 'bottom',
    singlePoint: 'start', valueUnit: 'percentage_points',
    ...(calendar && overview.value ? { start: Date.parse(overview.value.performance_since), end: Date.parse(overview.value.performance_through), dateTicks: 'calendar-window' as const } : {}),
    ...(!calendar && curve.value ? { start: 0, end: Math.max(0, curve.value.total_points - 1) } : {}),
  })
})
function key(row: NewowReferenceRecord) {
  return 'reference_trade_id' in row ? row.reference_trade_id
    : JSON.stringify([row.buyDate, row.buyPrice, row.sellDate, row.sellPrice, row.pct, row.segment_id])
}
function isTrade(row: NewowReferenceRecord): row is NewowReferenceTrade {
  return 'reference_trade_id' in row && typeof row.reference_trade_id === 'string'
}
const records = computed(() => {
  const current = history.value ? props.state.historyRows.value : overview.value?.recent_items ?? []
  const focused = selectedPoint.value?.trade
  return focused && !current.some(row => key(row) === key(focused)) ? [focused, ...current] : current
})
const highlighted = computed(() => selectedId.value ?? (props.selectedSignalId
  ? records.value.filter(isTrade).find(row => row.entry_signal_id === props.selectedSignalId || row.exit_signal_id === props.selectedSignalId)?.reference_trade_id ?? null
  : null))
async function selectPoint(point: NewowReferencePartPoint) {
  selectedPoint.value = point
  if (!point.reference_trade_id) return
  selectedId.value = point.reference_trade_id
  await nextTick()
  recordElements.get(point.reference_trade_id)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
}
function clickCurve(event: MouseEvent) {
  const target = event.currentTarget as SVGElement, rect = target.getBoundingClientRect()
  if (rect.width <= 0) return
  const x = (event.clientX - rect.left) / rect.width * 712
  const point = plot.value.points.reduce<typeof plot.value.points[number] | null>((best, current) => best === null || Math.abs(current.x - x) < Math.abs(best.x - x) ? current : best, null)
  if (point) {
    const source = curve.value?.points[point.sampledIndex]
    if (source) void selectPoint(source)
  }
}
function selectCurveIndex(index: number) {
  const point = plot.value.points[index]
  const source = point ? curve.value?.points[point.sampledIndex] : null
  if (source) void selectPoint(source)
}
function category(row: NewowReferenceRecord) {
  if (!isTrade(row)) return 'page'
  return row.status === 'CLOSED' ? 'closed' : row.status === 'OPEN' ? 'open' : 'interrupted'
}
function interruptionLabel(reason: string | null) {
  return reason === 'OWNER_BOUNDARY' ? '物理合约区段结束' : reason === 'DATA_CONFLICT' ? '数据冲突' : '参考交易中断'
}
const display = (value: string | null | undefined) => value == null ? '—' : formatMarketDecimal(value)
const groupName = (model: unknown) => ({ trend: '趋势', oscillation: '震荡', fusion: '融合' })[String(model) as 'trend' | 'oscillation' | 'fusion'] ?? '未知'
const segmentAnnuals = computed(() => curve.value?.segment_annuals ?? [])
const segmentField = (segment: Readonly<Record<string, unknown>>, key: string) => segment[key] == null ? null : String(segment[key])
const annualLabel = computed(() => curve.value?.annualized_pct == null ? '不可计算' : `${Number(curve.value.annualized_pct).toFixed(2)}%`)
const waiting = computed(() => {
  if (!props.state.chartCompatible.value || !overview.value || overview.value.summary.open_count !== 0) return null
  const bar = props.chart?.value?.bars.at(-1)
  const frame = props.chart?.value?.frames.find(item => item.bar_end === bar?.bar_end)
  return bar?.completed && bar.observation_eligible && frame?.status.status === 'ready'
    && frame.status.evidence_status === 'ACTIVE_CODE_VERIFIED' && frame.main_state === 'FLAT'
    && Date.parse(bar.bar_end) <= Date.parse(props.chart!.meta.as_of) ? bar : null
})
</script>

<template>
  <section class="newow-reference" aria-label="策略收益与参考记录" :aria-busy="state.loading.value">
    <nav class="performance-modes" aria-label="收益事实类型">
      <button v-for="entry in ([['page','页面参考收益'],['holding','含浮动参考'],['closed','已完成参考交易']] as const)" :key="entry[0]" type="button" :aria-pressed="fact === entry[0]" @click="setFact(entry[0])">{{ entry[1] }}</button>
    </nav>
    <PerformancePanel :kind="fact === 'page' ? '页面参考收益' : fact === 'holding' ? '含浮动参考' : '已完成参考交易'" :since="overview?.performance_since" :through="overview?.performance_through" :cutoff="overview?.reference_cutoff" :version="curve?.model_version ?? chart?.meta.reference_model_version" description="页面历史参考 · 零费用与滑点 · 不代表账户或可执行收益">
      <header class="newow-reference__returns-heading"><strong>参考统计</strong><span class="newow-reference__annualized" title="按完整参考曲线的首末值和自然日跨度折算；跨合约段年化不相加。">{{ pageMode ? '页面参考年化' : '参考年化' }} {{ annualLabel }}{{ pageMode && segmentAnnuals.length > 1 ? ` · ${segmentAnnuals.length}个合约段汇总` : '' }}</span><button type="button" @click="analysisOpen = true">收益分析 ›</button></header>
      <div class="newow-reference__presets" aria-label="参考统计快捷窗口">
        <button v-for="entry in ([['three_months','近3月'],['one_year','近1年'],['three_years','近3年'],['ytd','今年'],['ideal','理论值'],['all','全部']] as const)" :key="entry[0]" type="button" :disabled="state.loading.value || !anchor" :aria-pressed="preset === entry[0]" @click="usePreset(entry[0])">{{ entry[1] }}</button>
      </div>
      <p v-if="ideal" role="status">理论值使用回看最优参考价；不代表可执行收益。下方记录仍按所选模式展示。</p>
      <p v-if="state.error.value" role="alert">{{ state.error.value }} <button type="button" @click="retry">重试</button></p>
      <p v-else-if="state.loading.value && !curve" role="status">正在读取参考曲线…</p>
      <p v-if="overview?.history_coverage === 'PARTIAL'" role="status">历史覆盖不完整；仅统计有效区段，中断不计入已完成收益。</p>
      <details v-if="pageMode" class="page-performance__disclosure"><summary>详情与口径</summary><p>页面乐观收益 · 零手续费、零滑点；{{ ideal ? '理论值采用回看最优参考价' : '普通值包含末根估值平仓' }}，不代表模拟账户或可执行收益。</p><p>页面参考年化由完整曲线首末值和自然日跨度计算；跨合约段汇总不相加各段年化，不补齐换月成交。</p></details>
      <section class="newow-reference__curve" :class="{ 'page-performance': fact === 'page' }" :aria-label="fact === 'page' ? '页面估值收益曲线' : fact === 'holding' ? '逐 Bar 持有过程' : '已完成参考交易累计收益曲线'">
        <p v-if="fact === 'page'">累计参考收益 {{ newowReferencePoints(shownReturn) }} · 页面估值参考</p>
        <ReturnCurveSvg v-if="curve && !plot.message" :plot="plot" :label="fact === 'page' ? '页面收益曲线，区段中断处断线' : '参考收益曲线，点击查看读数或定位交易记录'" area :zero-line="fact !== 'page'" @click="clickCurve" @select="selectCurveIndex" />
        <p v-else role="status">{{ plot.message ?? '当前模式暂无可绘制的参考曲线。' }}</p>
        <p v-if="curve?.sampled" role="status">曲线显示 {{ curve.points.length }} / {{ curve.total_points }} 个保留采样点；下方统计由完整结果计算。</p>
        <p v-if="selectedPoint" aria-live="polite">{{ selectedPoint.trading_day }} · {{ display(selectedPoint.value) }} 百分点<span v-if="selectedPoint.physical_contract"> · {{ selectedPoint.physical_contract }}</span></p>
      </section>
      <details v-if="pageMode && segmentAnnuals.length > 1" class="page-performance__segment-annuals"><summary>各合约段年化 · 不跨段计算</summary><p v-for="(segment, index) in segmentAnnuals" :key="segmentField(segment, 'segment_id') ?? index" :title="segmentField(segment, 'segment_id') ?? undefined">合约段 {{ index + 1 }} · {{ segmentField(segment, 'since')?.slice(5, 10) }} → {{ segmentField(segment, 'through')?.slice(5, 10) }} · 年化 {{ segmentField(segment, 'annualized_pct') == null ? '--' : `${Number(segmentField(segment, 'annualized_pct')).toFixed(2)}%` }}</p></details>
      <section v-if="metrics" class="newow-reference__summary" data-testid="newow-reference-summary" aria-label="参考交易统计摘要"><dl class="newow-reference__metrics">
        <div><dt>{{ pageMode ? '页面累计参考收益' : fact === 'holding' ? '含浮动参考收益（百分点）' : '已完成参考收益（百分点）' }}</dt><dd :data-direction="referencePercentDisplay(shownReturn).direction">{{ pageMode ? newowReferencePoints(shownReturn) : referencePercentDisplay(shownReturn).text }}</dd></div>
        <div><dt>{{ pageMode ? '页面参考胜率（含期末估值）' : '已完成交易胜率' }}</dt><dd>{{ shownWinRate == null ? '—' : `${display(shownWinRate)}%` }}</dd></div>
        <div><dt>{{ drawdownLabel }}</dt><dd>{{ drawdownText }}</dd></div>
        <div><dt>{{ pageMode ? '页面参考次数（含期末估值）' : '已完成交易数' }}</dt><dd>{{ metrics.closed_count }}</dd></div>
      </dl><p v-if="metrics.closed_count === 0">{{ pageMode ? '暂无页面参考交易或期末估值' : '暂无已完成参考交易' }}；统计指标不是 0%。</p></section>
      <p v-else-if="curve" role="status">完整统计暂不可用，不能从采样曲线推算收益或回撤。</p>
      <header class="newow-reference__records-heading"><h3>历史参考记录</h3><span>历史参考推演，仅供参考，不作为实时买卖提示</span></header>
      <article v-if="waiting" class="newow-reference__card newow-reference__waiting" data-testid="newow-reference-waiting"><header><strong>空仓等待中</strong><span>策略空仓 · {{ waiting.physical_contract }}</span></header><p>状态时间 {{ formatBeijingInstant(waiting.bar_end) }} · 截至所示已完成 Bar，仅作页面参考。</p></article>
      <p v-if="state.historyError.value" role="alert">{{ state.historyError.value }} <button type="button" @click="history ? state.loadMore() : state.loadHistory()">重试</button></p>
      <p v-else-if="state.historyLoading.value && !history" role="status">正在读取历史参考记录…</p>
      <article v-for="row in records" :id="isTrade(row) ? `reference-trade-${row.reference_trade_id}` : undefined" :key="key(row)" :ref="element => { if (element && isTrade(row)) recordElements.set(row.reference_trade_id, element as HTMLElement) }" tabindex="-1" class="newow-reference__card" :class="{ 'fusion-selected': highlighted === key(row) }" :data-reference-category="category(row)" :data-reference-initial="isTrade(row) && row.statistics_membership === 'initial_before_window' ? 'true' : undefined">
        <template v-if="'reference_trade_id' in row">
          <header class="newow-reference__record-top"><strong>{{ row.status === 'CLOSED' ? '已完成' : row.status === 'OPEN' ? '未清仓' : '中断' }}</strong><span>{{ row.physical_contract }} · {{ formatBeijingInstant(row.entry_bar_end) }} → {{ row.exit_bar_end ? formatBeijingInstant(row.exit_bar_end) : '尚未清仓' }}</span><b class="newow-reference__record-return" :data-direction="referencePercentDisplay(row.status === 'CLOSED' ? row.reference_return_pct : row.mark_change_pct).direction">{{ referencePercentDisplay(row.status === 'CLOSED' ? row.reference_return_pct : row.mark_change_pct).text }}</b></header>
          <p>建仓参考 {{ newowReferencePrice(row.entry_reference_price) }} · {{ row.status === 'CLOSED' ? '清仓参考' : '标记参考' }} {{ newowReferencePrice(row.status === 'CLOSED' ? row.exit_reference_price : row.mark_reference_price) }}</p>
          <p v-if="row.statistics_membership === 'initial_before_window'">期初已有参考交易，不计入本窗口新建仓统计。</p>
          <p v-if="row.status !== 'CLOSED' && row.status !== 'OPEN'">{{ interruptionLabel(row.interruption_reason) }}；中断浮动不计入已完成收益。</p>
          <button v-if="!fusion" type="button" @click="emit('locate', row as NewowReferenceTrade, 'entry')">定位建仓</button>
          <button v-if="!fusion && row.exit_bar_end" type="button" @click="emit('locate', row as NewowReferenceTrade, 'exit')">定位清仓</button>
        </template>
        <template v-else><header class="newow-reference__record-top"><strong>{{ row.forceClose ? '持仓参考中' : '页面参考交易' }}</strong><span>{{ formatBeijingInstant(row.buyDate) }} → {{ row.forceClose ? '至估值日' : formatBeijingInstant(row.sellDate) }}</span><b>{{ referencePercentDisplay(row.pct).text }}</b></header><p>建仓参考 {{ newowReferencePrice(row.buyPrice) }} · {{ row.forceClose ? '参考估值' : '清仓参考' }} {{ newowReferencePrice(row.sellPrice) }} · {{ row.segment_id }}</p><p v-if="row.buyBarIsLive">末根新建仓的页面估值投影；不代表真实成交。</p></template>
      </article>
      <p v-if="!records.length && !state.historyLoading.value && !state.historyError.value">当前窗口暂无参考记录。</p>
      <p v-if="overview && records.length">{{ history ? `已加载 ${state.historyRows.value.length} 条` : `最近 ${overview.recent_items.length} 条预览` }}{{ history?.next_before && !state.historyCapped.value ? ' · 可继续加载' : '' }} · 总数未提供</p>
      <p v-if="state.historyCapped.value" role="status">已达显示上限，最多显示 300 条；当前不能据此认定完整历史或完整统计。</p>
      <button v-if="overview && !history" type="button" :disabled="state.historyLoading.value" @click="state.loadHistory()">查看完整历史记录</button>
      <button v-if="history?.next_before && !state.historyCapped.value" type="button" :disabled="state.historyLoading.value" @click="state.loadMore()">加载更多历史参考记录</button>
      <details v-if="fusion && overview?.fusion_groups"><summary>三组独立统计与融合配对规则</summary><table><thead><tr><th>模型</th><th>已完成</th><th>累计收益百分点</th><th>未清仓</th><th>中断</th></tr></thead><tbody><tr v-for="group in overview.fusion_groups" :key="String(group.model)"><th>{{ groupName(group.model) }}</th><td>{{ group.closed_count }}</td><td>{{ display(group.sum_return_percentage_points as string | null) }}</td><td>{{ group.open_count }}</td><td>{{ group.interrupted_count }}</td></tr></tbody></table><p>融合配对按固定策略合同计算；期初已有、未清仓浮动和中断不计入已完成累计。</p></details>
      <p v-if="pageMode" class="newow-reference__state">页面参考收益仅用于展示，不等于因果回测或模型账户收益。</p>
    </PerformancePanel>
    <NewowDetailDialog v-if="analysisOpen" :open="analysisOpen" title="收益分析" :identity-key="`${chart?.meta.snapshot_token}:${state.mode.value}`" @close="analysisOpen = false"><p>{{ overview?.performance_since }} 至 {{ overview?.performance_through }} · {{ chart?.meta.identity.product.toUpperCase() }} · {{ chart?.meta.identity.frequency }}</p><p>收益、胜率、回撤与年化来自完整参考投影。曲线可能采样，不能用采样点重算统计。</p><p>零费用、零滑点的页面参考，不代表账户收益或可执行收益。</p></NewowDetailDialog>
  </section>
</template>
<style scoped src="./newowReferencePanel.css"></style>
<style scoped>.newow-reference__curve{min-height:170px}.newow-reference__card{margin:10px 0}.newow-reference__record-top{display:flex;gap:12px;flex-wrap:wrap}.newow-reference__record-top b{margin-left:auto}.fusion-selected{outline:2px solid #ff9500}table{width:100%;border-collapse:collapse}td,th{padding:8px;border-bottom:1px solid #ddd;text-align:left}</style>
