<script setup lang="ts">
import { computed, ref, shallowRef, watch } from 'vue'
import { diagnosticCode, readReplay, type Replay, type Run, type Trade } from '@/api/backtestCenter'
import { formatBeijingInstant } from '@/utils/marketDisplay'
import BacktestChart from './BacktestChart.vue'
import { diagnosticLabel, displayValue, replayMarkerLabel, statusLabel } from './backtestDisplay'

const props = defineProps<{ run: Run; trade: Trade }>()
const emit = defineEmits<{ close: [] }>()
const replay = shallowRef<Replay>()
const error = ref('')
const trade = computed(() => replay.value?.trade ?? props.trade)
const markedAt = computed(() => trade.value.marked_at ?? trade.value.valuation_at)
const legs = computed(() => (replay.value?.native_fills ?? []).map(fill => ({
  fill, attempt: replay.value?.attempts?.find(attempt => attempt.signal_id === fill.signal_id),
})))
const fillsById = computed(() => new Map(legs.value.map(({ fill }) => [fill.native_trade_id, fill])))
const nativeIds = computed(() => new Set([
  trade.value.native_entry_id, trade.value.native_exit_id, ...(trade.value.native_entry_ids ?? []),
  ...(trade.value.native_exit_ids ?? []), ...fillsById.value.keys(),
]))
const signals = computed(() => new Set([
  trade.value.entry_signal_id, trade.value.exit_signal_id, ...legs.value.map(({ fill }) => fill.signal_id),
]))
const markers = computed(() => (replay.value?.markers ?? []).map(marker => ({
  ...marker,
  quantity: marker.quantity ?? (marker.native_trade_id ? fillsById.value.get(marker.native_trade_id)?.quantity : undefined),
  selected: marker.trade_id === trade.value.trade_id || (marker.native_trade_id
    ? nativeIds.value.has(marker.native_trade_id) : Boolean(marker.signal_id && signals.value.has(marker.signal_id))),
})))
const fillMarkers = computed(() => markers.value.filter(marker => marker.selected && ['ENTRY', 'EXIT', 'VALUATION'].includes(marker.kind)))
const positionEffects: Record<string, string> = { OPEN: '开仓', CLOSE: '平仓', CLOSE_TODAY: '平今' }

watch([() => props.run.run_id, () => props.trade.trade_id], async (_, __, onCleanup) => {
  replay.value = undefined
  error.value = ''
  const { run, trade: selected } = props
  const controller = new AbortController()
  onCleanup(() => controller.abort())
  try {
    const value = await readReplay(run.run_id, selected.trade_id, controller.signal)
    if (controller.signal.aborted) return
    const snapshotRevision = run.snapshot?.data_revision
    const inputHash = run.snapshot?.input_sha256
    if (value.run_id !== run.run_id || value.trade?.trade_id !== selected.trade_id
      || value.trade.contract !== selected.contract || value.contract !== selected.contract
      || value.frequency !== run.config.signal_frequency
      || (value.available && !value.revision) || (snapshotRevision && value.revision !== snapshotRevision)
      || (inputHash && value.input_sha256 !== inputHash)) {
      error.value = '归档图窗的 Run、交易或修订身份不一致。'
      return
    }
    replay.value = value
  } catch (reason) {
    if (!controller.signal.aborted) error.value = diagnosticCode(reason) ?? '图窗读取失败'
  }
}, { immediate: true })
</script>

<template>
  <section class="bt-replay" aria-labelledby="trade-replay-heading">
    <div class="bt-panel-header">
      <h3 id="trade-replay-heading">逐笔回放 · {{ trade.contract }} · {{ trade.direction }}</h3>
      <button type="button" class="bt-button" @click="emit('close')">关闭回放</button>
    </div>
    <p v-if="error" class="bt-alert" role="alert">{{ diagnosticLabel(error) }}</p>
    <p v-else-if="!replay" class="bt-note" role="status">正在读取同 Run 图窗</p>
    <template v-else>
      <p v-if="replay.revision" class="bt-note">{{ replay.contract }} · {{ replay.frequency }} · 数据修订 <code>{{ replay.revision }}</code></p>
      <p v-if="replay.input_sha256" class="bt-note bt-id">输入 SHA-256 <code>{{ replay.input_sha256 }}</code></p>
      <template v-if="replay.available && replay.bars?.length">
        <BacktestChart :series="{ kind: 'trades', bars: replay.bars, markers }" />
        <ul v-if="fillMarkers.length" class="bt-replay-key" aria-label="图上成交与估值标记">
          <li v-for="marker in fillMarkers" :key="marker.native_trade_id ?? [marker.kind, marker.event_at ?? marker.at].join('/')">
            <strong>{{ replayMarkerLabel(marker) }}</strong>
            <time :datetime="marker.event_at ?? marker.at">{{ marker.event_at ?? marker.at }}</time>
          </li>
        </ul>
      </template>
      <p v-else role="status" class="bt-note">{{ replay.reason ? diagnosticLabel(replay.reason) : '原修订的归档图窗不可重建' }}</p>
    </template>
    <dl class="bt-facts">
      <dt>交易身份</dt><dd>{{ trade.trade_id }}</dd>
      <dt>状态</dt><dd>{{ statusLabel(trade.status) }}</dd>
      <dt>交易手数</dt><dd>{{ trade.quantity }} 手</dd>
      <dt>建模进场</dt><dd>{{ formatBeijingInstant(trade.entry_at) }} · {{ trade.entry_price ?? '—' }}</dd>
      <dt>建模出场</dt><dd>{{ formatBeijingInstant(trade.exit_at) }} · {{ trade.exit_price ?? '—' }}</dd>
      <template v-if="markedAt || trade.mark_price != null">
        <dt>估值合约</dt><dd>{{ trade.contract }}</dd>
        <dt>估值时点</dt><dd>{{ formatBeijingInstant(markedAt) }}</dd>
        <dt>结算估值价</dt><dd>{{ trade.mark_price ?? '—' }}</dd>
      </template>
      <dt>费用</dt><dd>{{ trade.fees ?? '—' }}</dd>
      <template v-if="trade.net_pnl != null || trade.status === 'CLOSED'">
        <dt>已实现净盈亏</dt><dd>{{ trade.net_pnl ?? '—' }}</dd>
      </template>
      <template v-if="trade.unrealized_pnl != null || trade.status === 'OPEN' || trade.status === 'ROLLOVER_INTERRUPTED'">
        <dt>未实现盈亏</dt><dd>{{ trade.unrealized_pnl ?? '缺结算估值' }}</dd>
      </template>
    </dl>
    <div v-if="legs.length" class="bt-table-scroll">
      <table class="bt-table" aria-label="成交时钟与对账">
        <thead><tr><th>原生成交</th><th>原生委托身份</th><th>合约</th><th>手数</th><th>信号收线</th><th>信号可用</th><th>原生委托</th><th>建模成交</th><th>原生成交回调</th><th>价格 / 费用</th></tr></thead>
        <tbody><tr v-for="{ fill, attempt } in legs" :key="fill.native_trade_id">
          <td>{{ fill.native_trade_id }} · {{ positionEffects[fill.position_effect ?? ''] ?? displayValue(fill.position_effect) }}</td>
          <td>{{ displayValue(fill.native_order_id) }}</td><td>{{ fill.contract ?? trade.contract }}</td>
          <td>{{ fill.quantity == null ? '—' : `${fill.quantity} 手` }}</td>
          <td>{{ displayValue(attempt?.signal_bar_end) }}</td><td>{{ displayValue(attempt?.signal_available_at) }}</td>
          <td>{{ displayValue(fill.native_order_at) }}</td><td>{{ displayValue(fill.modeled_fill_at) }}</td>
          <td>{{ displayValue(fill.native_fill_at) }}</td><td>{{ displayValue(fill.price) }} / {{ displayValue(fill.fee) }}</td>
        </tr></tbody>
      </table>
    </div>
    <details class="bt-evidence">
      <summary>原生成交、信号与配对证据</summary>
      <pre>{{ JSON.stringify({ trade, native_fills: replay?.native_fills, attempts: replay?.attempts }, null, 2) }}</pre>
    </details>
  </section>
</template>
