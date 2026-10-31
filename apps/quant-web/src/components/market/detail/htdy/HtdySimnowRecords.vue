<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { monitorClient, type MonitorDetail, type MonitorQuery, type MonitorRecord } from '@/api/simnowMonitor'
import type { BarData } from '@/types/market'
import { projectHtdySimnowRecords, type HtdySimnowDisplayRecord } from '@/utils/htdySimnowMarkers'
import { monitorMoney, monitorReason, monitorTime } from '@/utils/simnowPresentation'

const props = defineProps<{ product: string; bars: BarData[]; active: boolean }>()
const emit = defineEmits<{
  records: [records: HtdySimnowDisplayRecord[]]
  state: [state: { status: 'loading' | 'ready' | 'partial' | 'unavailable'; snapshot: string | null }]
  focus: [identity: { barEnd: string; physicalContract: string }]
}>()
const MAX_RECORDS = 500
const rows = ref<MonitorRecord[]>([]), loading = ref(false), moreLoading = ref(false)
const error = ref<string | null>(null), nextCursor = ref<string | null>(null), snapshot = ref<string | null>(null)
const coverage = ref<'complete' | 'partial' | 'unavailable'>('unavailable')
const selected = ref<MonitorDetail | null>(null), selectedId = ref<string | null>(null), detailLoading = ref(false), detailError = ref<string | null>(null)
let controller: AbortController | null = null, detailController: AbortController | null = null, generation = 0, detailGeneration = 0
const kindNames = { signal: '信号', risk: '风控', order: '订单', fill: '成交' } as const
const factNames: Record<string, string> = { bar_end: '信号K线', observed_at: '观察时间', reason: '处理原因', margin: '保证金', projected_margin: '预计保证金', margin_limit: '保证金上限', side: '委托方向', offset: '开平', quantity: '数量', price: '价格', fee: '费用', accepted_at: '受理时间', reconciled: '已核对', filled_at: '成交时间', recorded_at: '入账时间', native_precision_seconds: '时间精度（秒）', trading_day: '交易日', origin: '来源', input_hash: '输入摘要' }
function day(value: string) { return new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(value)) }
const range = computed(() => {
  const dates = props.bars.map(bar => bar.time).filter(value => Number.isFinite(Date.parse(value))).sort((a, b) => Date.parse(a) - Date.parse(b))
  if (!dates.length) return null
  const end = day(dates.at(-1)!), earliest = day(dates[0]!)
  const floor = new Date(`${end}T00:00:00+08:00`); floor.setUTCDate(floor.getUTCDate() - 92)
  return { startDay: earliest > day(floor.toISOString()) ? earliest : day(floor.toISOString()), endDay: end }
})
const identity = computed(() => JSON.stringify([props.product.toUpperCase(), range.value]))
const query = computed<MonitorQuery | null>(() => range.value ? { kind: 'all', product: props.product.toUpperCase(), status: '', ...range.value } : null)
const projected = computed(() => projectHtdySimnowRecords(rows.value, props.bars, props.product))
const capped = computed(() => rows.value.length >= MAX_RECORDS && Boolean(nextCursor.value))
watch([projected, coverage, error], ([value]) => emit('records', error.value || coverage.value === 'unavailable' ? [] : value), { immediate: true })

function publishState(status?: 'loading' | 'ready' | 'partial' | 'unavailable') {
  emit('state', { status: status ?? (coverage.value === 'unavailable' ? 'unavailable' : coverage.value === 'partial' || nextCursor.value ? 'partial' : 'ready'), snapshot: snapshot.value })
}
function clear() {
  generation++; detailGeneration++; controller?.abort(); detailController?.abort()
  rows.value = []; nextCursor.value = null; snapshot.value = null; selected.value = null; selectedId.value = null
  loading.value = false; moreLoading.value = false; detailLoading.value = false; error.value = null; detailError.value = null
  coverage.value = 'unavailable'; emit('records', []); publishState('unavailable')
}
async function read(more = false) {
  if (!props.active || !query.value || more && (moreLoading.value || !nextCursor.value || capped.value)) return
  if (loading.value) return
  const own = ++generation, wanted = identity.value
  controller?.abort(); controller = new AbortController()
  if (more) moreLoading.value = true
  else {
    detailGeneration++; detailController?.abort(); detailController = null
    selected.value = null; selectedId.value = null; detailLoading.value = false; detailError.value = null
    loading.value = true; rows.value = []; snapshot.value = null; nextCursor.value = null
  }
  error.value = null; publishState('loading')
  try {
    const page = await monitorClient.records(query.value, controller.signal, more ? nextCursor.value ?? undefined : undefined)
    if (own !== generation || wanted !== identity.value || !props.active) return
    if (page.coverage !== 'unavailable' && !page.snapshot) throw Error('SNAPSHOT_MISSING')
    if (more && page.snapshot !== snapshot.value) throw Error('SNAPSHOT_CHANGED')
    if (page.items.some(row => row.product.toUpperCase() !== props.product.toUpperCase())) throw Error('PRODUCT_CHANGED')
    const combined = more ? [...rows.value, ...page.items] : page.items
    rows.value = [...new Map(combined.map(row => [row.id, row])).values()].slice(0, MAX_RECORDS)
    snapshot.value = page.snapshot; nextCursor.value = page.next_cursor; coverage.value = page.coverage
    publishState()
  } catch {
    if (own !== generation || wanted !== identity.value || !props.active) return
    error.value = more ? '执行记录快照变化或读取失败，未追加不一致的记录；请重新读取。' : '本地SimNow执行记录暂不可读取。'
    emit('records', []); publishState('unavailable')
  } finally { if (own === generation) { loading.value = false; moreLoading.value = false } }
}
async function detail(row: MonitorRecord) {
  const own = ++detailGeneration, wanted = identity.value
  detailController?.abort(); detailController = new AbortController()
  selectedId.value = row.id; selected.value = null; detailError.value = null; detailLoading.value = true
  try {
    const value = await monitorClient.detail(row.id, detailController.signal)
    if (own !== detailGeneration || wanted !== identity.value || !props.active) return
    if (value.snapshot !== snapshot.value || value.selected.id !== row.id || value.selected.product.toUpperCase() !== props.product.toUpperCase()) throw Error('SNAPSHOT_CHANGED')
    selected.value = value
  } catch { if (own === detailGeneration && wanted === identity.value && props.active) detailError.value = '关联记录不可读取或快照已变化，请重新读取列表。' }
  finally { if (own === detailGeneration) detailLoading.value = false }
}
function factValue(key: string, value: string | null) { return value == null ? '—' : key === 'reason' ? monitorReason[value] ?? value : value }
watch([identity, () => props.active], () => { clear(); if (props.active) void read() }, { immediate: true })
onBeforeUnmount(clear)
</script>

<template>
  <section class="htdy-simnow-records" aria-label="HTDY SimNow只读执行记录">
    <header><h3>SimNow记录</h3><button type="button" :disabled="loading" @click="read()">重新读取</button></header>
    <p class="note">本地信号、风控、订单及成交分别保留。当前记录未保存策略公式版本与周期，不能据此覆盖历史回放或首次观察。品种／策略收益归因未证明，收益统计不可用。</p>
    <p v-if="range" class="note">查询记录时间 {{ range.startDay }} → {{ range.endDay }} · 已加载 {{ rows.length }} 条；一次最多显示 {{ MAX_RECORDS }} 条。</p>
    <p v-if="loading" role="status">正在读取本地执行记录…</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-else-if="!loading && coverage === 'unavailable'" role="status">尚无可验证的本地执行来源，不能据此判断是否发生交易。</p>
    <p v-else-if="!loading && !rows.length" role="status">当前已查询范围内暂无执行记录。</p>
    <p v-if="!error && (coverage === 'partial' || nextCursor)" class="note">执行记录尚未完整读取；列表空白不代表无信号或无成交。</p>
    <ol>
      <li v-for="row in projected" :key="row.id">
        <div class="row-heading"><strong>{{ kindNames[row.kind] }} · {{ row.label }}</strong><span>{{ row.status }}</span><time>{{ monitorTime(row.kind === 'fill' ? row.facts.filled_at : row.at) }}</time></div>
        <p>{{ row.product }} {{ row.contract || '合约未关联' }}<template v-if="row.facts.price"> · {{ row.kind === 'fill' ? '成交价' : '委托价' }} {{ monitorMoney(row.facts.price) }}</template><template v-if="row.facts.quantity"> · 数量 {{ row.facts.quantity }}</template><template v-if="row.facts.fee"> · 费用 {{ monitorMoney(row.facts.fee) }}</template></p>
        <p v-if="row.facts.reason" class="note">{{ factValue('reason', row.facts.reason) }}</p>
        <p class="note">未验证策略关联<template v-if="row.plotNotice"> · {{ row.plotNotice }}</template></p>
        <button type="button" @click="detail(row)">查看执行链</button>
        <button v-if="row.focus" type="button" @click="emit('focus', row.focus)">定位图表</button>
      </li>
    </ol>
    <button v-if="nextCursor && !capped && !error" type="button" :disabled="loading || moreLoading" @click="read(true)">{{ moreLoading ? '读取中…' : '读取更多执行记录' }}</button>
    <p v-if="capped" class="note">已达到本页显示上限；不能作为完整账户记录。</p>
    <section v-if="selectedId" class="chain" aria-label="SimNow关联执行链">
      <header><h4>执行链</h4><button type="button" @click="selectedId = null; selected = null">收起</button></header>
      <p v-if="detailLoading" role="status">正在核对关联身份…</p><p v-if="detailError" role="alert">{{ detailError }}</p>
      <article v-for="row in selected?.chain ?? []" :key="row.id"><strong>{{ kindNames[row.kind] }} · {{ row.label }} · {{ row.status }}</strong><p>{{ row.product }} {{ row.contract }} · {{ monitorTime(row.at) }}</p><dl><template v-for="(value, key) in row.facts" :key="key"><dt>{{ factNames[key] ?? key }}</dt><dd>{{ factValue(String(key), value) }}</dd></template><dt>记录身份</dt><dd>{{ row.id }}</dd><dt>信号身份</dt><dd>{{ row.signal_id ?? '未关联' }}</dd><dt>订单身份</dt><dd>{{ row.order_id ?? '未关联' }}</dd></dl></article>
    </section>
  </section>
</template>

<style scoped>
.htdy-simnow-records{padding:14px;min-width:0}.htdy-simnow-records header,.row-heading{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.htdy-simnow-records header{justify-content:space-between}.htdy-simnow-records h3,.htdy-simnow-records h4{margin:0}.note,time,.row-heading>span{font-size:12px;color:var(--gy-text-muted);line-height:1.7}.htdy-simnow-records button{border:1px solid var(--gy-border);background:var(--gy-bg-panel);border-radius:6px;padding:6px 10px;min-height:32px;cursor:pointer;font:inherit;margin:4px 6px 4px 0}.htdy-simnow-records ol{list-style:none;margin:0;padding:0}.htdy-simnow-records li,.chain article{padding:12px 0;border-bottom:1px solid var(--gy-border)}.row-heading time{margin-left:auto}.htdy-simnow-records p{line-height:1.7;margin:5px 0}.chain{margin-top:14px;padding:12px;background:var(--gy-bg-panel);border:1px solid var(--gy-border);border-radius:8px}.chain dl{display:grid;grid-template-columns:minmax(90px,1fr) minmax(0,3fr);gap:6px;font-size:12px}.chain dd{margin:0;overflow-wrap:anywhere}.chain dt{color:var(--gy-text-muted)}@media(max-width:600px){.htdy-simnow-records{padding:10px}.row-heading time{width:100%;margin-left:0}.htdy-simnow-records button{min-height:40px}}
</style>
