<script setup lang="ts">
import { computed, nextTick, ref, watch, onBeforeUnmount } from 'vue'
import { getNewowFusion, type FusionComparison } from '@/api/newowFusion'
import { closedReferenceCurve, sumReferenceReturns, referenceCurveDrawdown } from '@/utils/newowReferenceCurve'
import { newowReferenceWindow, type NewowReferencePreset } from '@/utils/newowReferenceWindows'
import { referencePercentDisplay, referenceTimeDisplay } from '@/utils/newowDetailPresentation'
import type { NewowProductSectionResponse } from '@/types/newowProduct'
import { formatMarketDecimal, formatBeijingInstant } from '@/utils/marketDisplay'
const props = defineProps<{ response: NewowProductSectionResponse<'reference'> }>()
const result = ref<FusionComparison | null>(null)
const loading = ref(false)
const error = ref('')
let controller: AbortController | null = null
let generation = 0
watch(() => [props.response.meta.identity.product, props.response.meta.identity.strategy, props.response.meta.identity.frequency, props.response.meta.as_of, props.response.meta.snapshot_token, props.response.value?.reference_input_sha256, props.response.value?.performance_since, props.response.value?.performance_through], () => {
  generation++; controller?.abort(); result.value = null; loading.value = false; error.value = ''
  void load()
}, { immediate: true })
onBeforeUnmount(() => { generation++; controller?.abort() })
async function load() {
  result.value = null
  const value = props.response.value
  if (!value || props.response.meta.identity.strategy !== 'trend') return
  const token = ++generation
  controller?.abort(); controller = new AbortController()
  loading.value = true; error.value = ''
  const identity = props.response.meta.identity
  try {
    const next = await getNewowFusion({ identity: { product: identity.product, strategy: 'trend', frequency: identity.frequency, seriesKind: 'actual_dominant' }, section: 'reference', asOf: props.response.meta.as_of, snapshotToken: props.response.meta.snapshot_token ?? undefined, performanceSince: value.performance_since, performanceThrough: value.performance_through }, { signal: controller.signal })
    if (token === generation) {
      if (next.reference_input_sha256 !== value.reference_input_sha256 || next.reference_cutoff !== value.reference_cutoff) {
        error.value = '融合输入已变化，请刷新当前图表后重试。'
        return
      }
      result.value = next
    }
  } catch { if (token === generation) error.value = '融合参考读取失败，请重试。' }
  finally { if (token === generation) loading.value = false }
}
function tone(value: string | null) { return value === null ? '' : Number(value) >= 0 ? 'gain' : 'loss' }
const names = { trend: '趋势', oscillation: '震荡', fusion: '融合' }
const states = { OPEN: '未清仓', CLOSED: '已完成', ROLLOVER_INTERRUPTED: '换月中断', DATA_INTERRUPTED: '数据中断' }
const display = (value: string | null) => value === null ? '—' : formatMarketDecimal(value)
const preset = ref<Exclude<NewowReferencePreset, 'ideal'>>('all')
watch(() => result.value, () => { preset.value = 'all' })
const anchor = computed(() => result.value ? new Date(Date.parse(result.value.reference_cutoff) + 8 * 3600000).toISOString().slice(0, 10) : '')
const window = computed(() => result.value ? newowReferenceWindow(anchor.value, preset.value, result.value.performance_since) : null)
const fullCurve = computed(() => {
  const data = result.value, group = data?.groups.find(g => g.model === 'fusion')
  return data && group ? closedReferenceCurve(data.items, group.closed_count, group.sum_return_percentage_points, 'entry_in_window_v1', data.records_truncated) : { points: [], message: '正在读取融合参考…' }
})
const closed = computed(() => fullCurve.value.points.map(p => p.trade).filter(t => {
  const day = new Date(Date.parse(t.entry_bar_end) + 8 * 3600000).toISOString().slice(0, 10)
  return window.value && day >= window.value.performanceSince && day <= window.value.performanceThrough
}))
const total = computed(() => preset.value === 'all' ? result.value?.groups.find(g => g.model === 'fusion')?.sum_return_percentage_points ?? null : closed.value.length ? sumReferenceReturns(closed.value.map(t => t.reference_return_pct!)) : null)
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
const isInitialRecord = (row: { entry_bar_end: string; statistics_membership: string }) => row.statistics_membership === 'initial_before_window' || new Date(Date.parse(row.entry_bar_end) + 8 * 3600000).toISOString().slice(0, 10) < recordSince.value
const selected = ref<string | null>(null)
watch(() => result.value, () => { selected.value = null })
const records = computed(() => {
  if (!result.value) return []
  const since = recordSince.value
  return result.value.items.filter(t => t.reference_trade_id === selected.value || t.status === 'OPEN' || new Date(Date.parse(t.exit_bar_end ?? t.entry_bar_end) + 8 * 3600000).toISOString().slice(0, 10) >= since)
})
async function locate(id: string) { selected.value = id; await nextTick(); document.getElementById(`fusion-trade-${id}`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }) }
const time = (instant: string) => referenceTimeDisplay(instant, props.response.meta.identity.frequency, [result.value?.reference_cutoff ?? instant])
const presets = [['three_months', '近3月'], ['one_year', '近1年'], ['three_years', '近3年'], ['ytd', '今年'], ['all', '全部']] as const
</script>
<template>
  <section class="fusion-panel newow-reference" aria-label="双策略融合参考模型" :aria-busy="loading">
    <header class="newow-reference__returns-heading"><strong>策略收益率走势</strong><span class="newow-reference__annualized">年化{{ annualized }}</span><button class="fusion-refresh" :disabled="loading" @click="load">{{ loading ? '计算中…' : '重新计算' }}</button></header>
    <p class="fusion-caption">双策略融合 · 单仓 long/flat · 零费用、零滑点页面参考，不代表可执行收益。</p>
    <p v-if="response.value?.history_coverage === 'PARTIAL'" role="status">数据覆盖不完整，仅统计已验证片段，中断不计入已完成收益。</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="loading" role="status">正在读取融合参考…</p>
    <template v-if="result">
      <div class="newow-reference__window"><div class="newow-reference__presets" aria-label="融合参考统计快捷窗口"><button v-for="item in presets" :key="item[0]" :aria-pressed="preset === item[0]" :disabled="loading || fullCurve.message !== null" @click="preset = item[0]">{{ item[1] }}</button></div></div>
      <section class="newow-reference__curve" aria-label="融合已完成参考交易累计收益曲线">
        <p v-if="curve.message" role="status">{{ curve.message }}{{ result.records_truncated ? '记录已截断，完整统计仍见三组对比。' : '' }}</p>
        <div v-else class="newow-reference__plot"><div class="newow-reference__plot-area">
          <svg viewBox="0 0 712 140" preserveAspectRatio="none" role="group" aria-label="融合参考收益按清仓顺序累计">
            <defs><linearGradient id="fusion-reference-area" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#ff403a" stop-opacity="0.16"/><stop offset="100%" stop-color="#ff403a" stop-opacity="0.01"/></linearGradient></defs>
            <line v-for="level in plot.levels" :key="level.y" x1="0" x2="712" :y1="level.y" :y2="level.y" stroke="#f2f3f5"/>
            <polygon :points="`0,${plot.zero} ` + plot.points.map(p => `${p.x},${p.y}`).join(' ') + ` 712,${plot.points.at(-1)?.y ?? plot.zero} 712,${plot.zero}`" fill="url(#fusion-reference-area)"/>
            <line x1="0" x2="712" :y1="plot.zero" :y2="plot.zero" stroke="#d0d5dd" stroke-dasharray="4 4"/>
            <polyline :points="`0,${plot.zero} ` + plot.points.map(p => `${p.x},${p.y}`).join(' ') + ` 712,${plot.points.at(-1)?.y ?? plot.zero}`" fill="none" stroke="#ff403a" stroke-width="1.8"/>
            <circle v-for="p in plot.points" :key="p.trade.reference_trade_id" :cx="p.x" :cy="p.y" r="2" fill="#ff403a" tabindex="0" role="button" :aria-label="`${time(p.trade.exit_bar_end!)}，累计${display(p.cumulative)}百分点`" @click="locate(p.trade.reference_trade_id)" @keydown.enter.prevent="locate(p.trade.reference_trade_id)" @keydown.space.prevent="locate(p.trade.reference_trade_id)"><title>{{ time(p.trade.exit_bar_end!) }} · {{ p.trade.physical_contract }} · 累计{{ display(p.cumulative) }}百分点</title></circle>
          </svg>
          <span v-for="level in plot.levels" :key="level.y" class="newow-reference__value-tick" :style="{top:`${level.y / 140 * 100}%`}">{{ level.label }}</span>
          <span v-for="tick in plot.ticks" :key="tick.x" class="newow-reference__date-tick" :data-anchor="tick.x === 0 ? 'start' : tick.x === 712 ? 'end' : 'middle'" :style="{left:`${tick.x / 712 * 100}%`}">{{ tick.day }}</span>
        </div></div>
        <section class="newow-reference__summary"><dl class="newow-reference__metrics"><div><dt>累计收益</dt><dd :data-direction="referencePercentDisplay(total).direction">{{ referencePercentDisplay(total).text }}</dd></div><div><dt>胜率</dt><dd>{{ winRate }}</dd></div><div><dt>最大回撤</dt><dd class="newow-reference__drawdown">{{ drawdown === null ? '—' : `${drawdown}%` }}</dd></div><div><dt>交易次数</dt><dd>{{ preset === 'all' ? result.groups.find(g => g.model === 'fusion')?.closed_count : closed.length }}</dd></div></dl></section>
      </section>
      <header class="newow-reference__records-heading"><h3>回测操盘提醒</h3><span>近一年 · 历史参考推演，仅供参考，不作为实时买卖提示</span></header>
      <p v-if="result.records_truncated" role="status">仅返回最近200条融合记录，近一年记录可能不完整。</p>
      <div class="newow-reference__cards">
        <article v-for="row in records" :id="`fusion-trade-${row.reference_trade_id}`" :key="row.reference_trade_id" class="newow-reference__card" :class="{'fusion-selected':selected === row.reference_trade_id}">
          <header class="newow-reference__record-top"><div class="newow-reference__record-meta"><strong class="newow-reference__period" :class="{'is-open':row.status === 'OPEN','is-interrupted':row.status.endsWith('INTERRUPTED')}">{{ row.status === 'CLOSED' ? response.meta.identity.frequency === '1w' ? '周K' : '日K' : states[row.status] }}</strong><span>{{ time(row.entry_bar_end) }} → {{ row.exit_bar_end ? time(row.exit_bar_end) : '尚未清仓' }}</span><span>{{ row.physical_contract }}</span><span v-if="selected === row.reference_trade_id && row.status !== 'OPEN' && time(row.exit_bar_end ?? row.entry_bar_end).slice(0,10) < newowReferenceWindow(anchor, 'one_year').performanceSince">曲线定位 · 近一年外</span><span v-if="isInitialRecord(row)">期初已有</span></div><strong class="newow-reference__record-return" :data-direction="referencePercentDisplay(row.status === 'CLOSED' ? row.reference_return_pct : row.mark_change_pct).direction">{{ row.status === 'CLOSED' ? '盈亏' : row.status === 'OPEN' ? '未清仓浮动' : '中断浮动' }} {{ referencePercentDisplay(row.status === 'CLOSED' ? row.reference_return_pct : row.mark_change_pct).text }}</strong></header>
          <div class="newow-reference__record-line"><span><strong class="newow-reference__entry">建仓</strong> 买入 {{ display(row.entry_reference_price) }} <small>{{ names[row.entry_source] }}来源</small></span><time>{{ time(row.entry_bar_end) }}</time></div>
          <div v-if="row.status === 'CLOSED'" class="newow-reference__record-line"><span><strong class="newow-reference__exit">清仓</strong> 卖出 {{ display(row.exit_reference_price) }} <b class="newow-reference__inline-return" :data-direction="referencePercentDisplay(row.reference_return_pct).direction">{{ referencePercentDisplay(row.reference_return_pct).text }}</b><small>{{ row.exit_source ? names[row.exit_source] : '—' }}来源</small></span><time>{{ row.exit_bar_end ? time(row.exit_bar_end) : '—' }}</time></div>
          <p v-else class="newow-reference__interruption">{{ row.status === 'OPEN' ? '截至所示已完成Bar，未清仓浮动不计入已完成收益。' : '物理合约或数据区段中断，中断浮动不计入已完成收益。' }}</p>
        </article>
      </div>
      <p v-if="!records.length">近一年暂无融合参考记录。</p>
      <details><summary>三组独立统计与融合配对规则</summary><p>{{ result.performance_since }} — {{ result.performance_through }} · 截至 {{ formatBeijingInstant(result.reference_cutoff) }}<small>{{ result.reference_model_version }}</small></p><div class="fusion-panel__scroll"><table><thead><tr><th>模型</th><th>已完成</th><th>累计收益百分点</th><th>未清仓</th><th>中断</th></tr></thead><tbody><tr v-for="g in result.groups" :key="g.model"><th>{{ names[g.model] }}</th><td>{{ g.closed_count }}</td><td :class="tone(g.sum_return_percentage_points)">{{ display(g.sum_return_percentage_points) }}</td><td>{{ g.open_count }}</td><td>{{ g.interrupted_count }}</td></tr></tbody></table></div><p>累计简单相加窗口内建仓且已完成的参考收益。同根先清仓再建仓，同方向优先震荡价；允许跨策略配对，持有期间不重复建仓，不跨合约配对。期初已有、未清仓浮动和中断不计入累计。</p></details>
    </template>
  </section>
</template>
<style scoped src="./newowReferencePanel.css"></style>
<style scoped>
.fusion-panel { margin:16px 0; }.fusion-caption,.fusion-panel details p { color:#8891a5; font-size:12px; }.fusion-refresh { margin-left:auto; }.fusion-panel__scroll { overflow:auto; } table { width:100%; border-collapse:collapse; font-size:13px; white-space:nowrap; } th,td { text-align:left; padding:10px; border-bottom:1px solid #eef0f4; }.gain { color:#ff4248; }.loss { color:#22b957; } summary { cursor:pointer; font-size:13px; margin:10px 0; }.fusion-selected { outline:2px solid #ff9500; }
</style>
