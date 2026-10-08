<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { getNewowRecordingMatrix, getNewowRecordingRecords, getReferencePoints, getReferenceStreams } from '@/api/referenceTrading'
import type { NewowRecordingMatrix, NewowRecordingStrategy, NewowRecordingFrequency, ReferenceMode, ReferencePage, ReferencePoint, ReferenceStreamInfo } from '@/types/referenceTrading'
import { newowRecordingWindow, newowRecordingIdentity, recordingPointLabel, recordingStateLabel, recordingItemStatus, recordingReconciliationLabel } from '@/utils/newowRecording'
import { formatBeijingInstant } from '@/utils/marketDisplay'
const props = defineProps<{ product: string; strategy: string; frequency: string }>()
const strategies = [{ value: 'trend', label: '趋势' }, { value: 'oscillation', label: '震荡' }, { value: 'main_rise', label: '主升浪' }, { value: 'dual_fusion', label: '双策略' }]
const frequencies = [{ value: '1w', label: '周线' }, { value: '1d', label: '日线' }, { value: '60m', label: '60 分钟' }]
const mode = ref<ReferenceMode>('forward_observation')
const product = ref(props.product.toLowerCase())
const strategy = ref<NewowRecordingStrategy>(strategies.some(item => item.value === props.strategy) ? props.strategy as NewowRecordingStrategy : 'trend')
const frequency = ref<NewowRecordingFrequency>(frequencies.some(item => item.value === props.frequency) ? props.frequency as NewowRecordingFrequency : '60m')
const matrix = ref<NewowRecordingMatrix | null>(null)
const streams = ref<ReferenceStreamInfo[]>([])
const selectedStream = ref('')
const actions = ref<ReferencePage<ReferencePoint> | null>(null)
const states = ref<ReferencePage<ReferencePoint> | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const window = ref(newowRecordingWindow())
const products = computed(() => [...new Set([product.value, ...(matrix.value?.items.map(item => item.product.toLowerCase()) ?? [])])].sort())
const rows = computed(() => matrix.value?.items.filter(item => item.product.toLowerCase() === product.value) ?? [])
const selected = computed(() => rows.value.find(item => item.strategy === strategy.value && item.frequency === frequency.value) ?? null)
const statePoints = computed(() => states.value?.items.filter(point => point.value.version === 'newow_bar_state_v1') ?? [])
let generation = 0
let controller: AbortController | null = null
function reset() {
  generation += 1; controller?.abort(); controller = new AbortController()
  actions.value = null; states.value = null; error.value = null
  return { token: generation, signal: controller.signal }
}
async function read(id: string, token: number, signal: AbortSignal) {
  const result = await getNewowRecordingRecords(id, window.value, { signal })
  if (token === generation) { actions.value = result.signals; states.value = result.states }
}
async function refresh() {
  const { token, signal } = reset()
  loading.value = true; streams.value = []; selectedStream.value = ''; window.value = newowRecordingWindow()
  try {
    const overview = await getNewowRecordingMatrix({ signal })
    if (token !== generation) return
    matrix.value = overview
    if (mode.value === 'forward_observation') {
      window.value = newowRecordingWindow(new Date(), selected.value?.latest_state_source === 'observed' ? selected.value.latest_observed_trading_day : null)
      if (selected.value?.stream_id) await read(selected.value.stream_id, token, signal)
    } else {
      const matches = await getReferenceStreams(newowRecordingIdentity(product.value, strategy.value, frequency.value, 'historical_replay'), { signal })
      if (token !== generation) return
      streams.value = matches.filter(item => item.recording_mode === 'historical_replay')
      if (streams.value.length === 1) {
        selectedStream.value = streams.value[0]!.stream_id
        if (streams.value[0]!.readable) await read(selectedStream.value, token, signal)
      }
    }
  } catch { if (token === generation) error.value = '已保存的记录暂不可读取，请刷新后重试。' }
  finally { if (token === generation) loading.value = false }
}
async function chooseHistorical() {
  const id = selectedStream.value
  const { token, signal } = reset()
  if (!id) return
  loading.value = true
  try { await read(id, token, signal) }
  catch { if (token === generation) error.value = '该历史记录暂不可读取，请刷新后重试。' }
  finally { if (token === generation) loading.value = false }
}
async function more(kind: 'signals' | 'indicators') {
  const previous = kind === 'signals' ? actions.value : states.value
  const id = mode.value === 'historical_replay' ? selectedStream.value : selected.value?.stream_id
  if (!previous?.next_cursor || !id || loading.value || !controller) return
  const token = generation; loading.value = true
  try {
    const next = await getReferencePoints(id, kind, window.value, previous.snapshot, { cursor: previous.next_cursor, signal: controller.signal, limit: 50 })
    if (token !== generation) return
    if (next.snapshot !== previous.snapshot || next.revision_id !== previous.revision_id || next.seq !== previous.seq) throw new Error('SNAPSHOT_CONFLICT')
    const combined = { ...next, items: [...previous.items, ...next.items] }
    if (kind === 'signals') actions.value = combined
    else states.value = combined
  } catch { if (token === generation) error.value = '记录快照已变化或读取失败，请刷新后重新读取。' }
  finally { if (token === generation) loading.value = false }
}
watch(() => [props.product, props.strategy, props.frequency], () => {
  product.value = props.product.toLowerCase()
  if (strategies.some(item => item.value === props.strategy)) strategy.value = props.strategy as NewowRecordingStrategy
  if (frequencies.some(item => item.value === props.frequency)) frequency.value = props.frequency as NewowRecordingFrequency
})
watch([product, strategy, frequency, mode], refresh, { immediate: true })
onBeforeUnmount(() => { generation += 1; controller?.abort() })
</script>
<template>
  <section class="newow-recording" aria-label="牛哇信号与状态记录">
    <header><h2>信号与状态记录</h2><button type="button" :disabled="loading" @click="refresh">刷新记录</button></header>
    <p>记录已完成 K 线的策略状态和信号；不代表账户成交，此处不发送通知。</p>
    <p v-if="matrix">60 品种 · 四策略 · 三周期：应有 {{ matrix.expected_count }} 组，已配置 {{ matrix.configured_count }}，已启用 {{ matrix.enabled_count }}，已完成历史预热 {{ matrix.seeded_count }}，已有实际观察记录 {{ matrix.observed_count }}。</p>
    <nav aria-label="记录模式"><button type="button" :aria-pressed="mode === 'forward_observation'" @click="mode = 'forward_observation'">持续观察</button><button type="button" :aria-pressed="mode === 'historical_replay'" @click="mode = 'historical_replay'">历史回放</button></nav>
    <div class="filters">
      <label>品种 <select v-model="product"><option v-for="item in products" :key="item" :value="item">{{ item.toUpperCase() }}</option></select></label>
      <label>策略 <select v-model="strategy"><option v-for="item in strategies" :key="item.value" :value="item.value">{{ item.label }}</option></select></label>
      <label>周期 <select v-model="frequency"><option v-for="item in frequencies" :key="item.value" :value="item.value">{{ item.label }}</option></select></label>
    </div>
    <p v-if="loading" role="status">正在读取已保存记录…</p><p v-if="error" role="status">{{ error }}</p>
    <template v-if="mode === 'forward_observation'">
      <p>持续观察只显示激活后实际捕获的记录；日线与周线等待对应周期完成。</p>
      <div class="table"><table><thead><tr><th>策略 / 周期</th><th>记录状态</th><th>历史预热至</th><th>实际观察至</th><th>最新已保存状态</th></tr></thead><tbody>
        <tr v-for="row in rows" :key="`${row.strategy}:${row.frequency}`" :class="{ selected: row === selected }"><td><button type="button" @click="strategy = row.strategy; frequency = row.frequency">{{ strategies.find(item => item.value === row.strategy)?.label }} / {{ frequencies.find(item => item.value === row.frequency)?.label }}</button></td><td>{{ recordingItemStatus(row) }}</td><td>{{ formatBeijingInstant(row.historical_computed_through) }}</td><td>{{ formatBeijingInstant(row.observed_through) }}</td><td>{{ row.latest_state_source === 'historical_seed' ? '历史预热 · ' : '' }}{{ recordingStateLabel(row.latest_state) }}</td></tr>
      </tbody></table></div>
      <p v-if="selected">记录起点 {{ formatBeijingInstant(selected.recording_start) }} · 待处理捕获 {{ selected.pending_capture_count ?? '待核对' }} · 合约 {{ selected.latest_state?.physical_contract ?? '尚无观察记录' }} · 行情核对 {{ recordingReconciliationLabel(selected.latest_reconciliation_status) }}</p>
      <p v-if="selected?.latest_state?.availability && typeof selected.latest_state.availability === 'object' && selected.latest_state.availability.reason_code">不可用原因：{{ selected.latest_state.availability.reason_code }}</p>
    </template>
    <template v-else><p>历史回放使用已保存历史快照，不代表当时实时捕获的观察事实。</p><label v-if="streams.length">历史版本 <select v-model="selectedStream" @change="chooseHistorical"><option value="">请选择一个历史版本</option><option v-for="stream in streams" :key="stream.stream_id" :value="stream.stream_id">{{ stream.formula_versions.join(' / ') }} · {{ stream.profile_id }} · {{ stream.stream_id }}</option></select></label><p v-else-if="!loading">所选组合尚无可读取的历史记录。</p></template>
    <p>窗口（交易日）：{{ window.since }} 至 {{ window.through }}。K 线时间以北京时间显示。</p>
    <div v-if="actions" class="table"><h3>动作与提示</h3><table><thead><tr><th>K 线结束</th><th>动作 / 提示</th><th>实际观察时间</th></tr></thead><tbody><tr v-for="(point, index) in actions.items" :key="index"><td>{{ formatBeijingInstant(String(point.value.bar_end ?? '')) }}</td><td>{{ recordingPointLabel(point) }}</td><td>{{ mode === 'forward_observation' ? formatBeijingInstant(String(point.value.observed_at ?? '')) : '历史回放' }}</td></tr></tbody></table><p v-if="!actions.items.length">窗口暂无已记录动作；不等于没有逐 K 线状态。</p><button v-if="actions.next_cursor" type="button" :disabled="loading" @click="more('signals')">加载更多动作与提示</button></div>
    <div v-if="states" class="table"><h3>逐 K 线状态</h3><table><thead><tr><th>K 线结束</th><th>策略状态</th><th>物理合约</th><th>实际观察时间</th></tr></thead><tbody><tr v-for="(point, index) in statePoints" :key="index"><td>{{ formatBeijingInstant(String(point.value.bar_end ?? '')) }}</td><td>{{ recordingPointLabel(point) }}</td><td>{{ point.value.physical_contract ?? '未记录' }}</td><td>{{ mode === 'forward_observation' ? formatBeijingInstant(String(point.value.observed_at ?? '')) : '历史回放' }}</td></tr></tbody></table><p v-if="!statePoints.length">该页暂无新版逐 K 线状态记录。</p><button v-if="states.next_cursor" type="button" :disabled="loading" @click="more('indicators')">加载更多状态</button></div>
  </section>
</template>
<style scoped>
.newow-recording { padding: var(--gy-space-3); background: var(--gy-bg-panel); border: 1px solid var(--gy-border); border-radius: var(--gy-radius-md); }
header, nav, .filters { display: flex; gap: var(--gy-space-2); flex-wrap: wrap; align-items: center; } header { justify-content: space-between; } h2, h3 { font-size: 1rem; } p { color: var(--gy-text-muted); font-size: .85rem; }
button, select { color: inherit; background: var(--gy-bg-panel); border: 1px solid var(--gy-border); border-radius: var(--gy-radius-sm); padding: .35rem .55rem; } button { cursor: pointer; } button[aria-pressed="true"] { font-weight: 700; } .filters, .table { margin-top: var(--gy-space-3); } .table { overflow-x: auto; } table { width: 100%; border-collapse: collapse; min-width: 540px; } th, td { padding: .45rem; text-align: left; border-bottom: 1px solid var(--gy-border); } .selected { font-weight: 700; }
</style>
