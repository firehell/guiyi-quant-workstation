<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useReferenceTrading } from '@/composables/useReferenceTrading'
import type { ReferenceMode } from '@/types/referenceTrading'
import { formatBeijingInstant, formatMarketDecimal } from '@/utils/marketDisplay'

const props = withDefaults(defineProps<{
  strategy: string
  product: string
  frequency: string
  through?: string
  initialMode?: ReferenceMode
  historicalAvailable?: boolean
}>(), { initialMode: 'forward_observation', historicalAvailable: true })
const mode = ref<ReferenceMode>(props.initialMode)
const reference = useReferenceTrading()
const throughDate = computed(() => props.through || new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
}).format(new Date()))
const since = computed(() => {
  const day = new Date(`${throughDate.value}T00:00:00Z`)
  if (Number.isNaN(day.valueOf())) return throughDate.value
  day.setUTCDate(day.getUTCDate() - 90)
  return day.toISOString().slice(0, 10)
})
watch(() => [props.strategy, props.product, props.frequency, throughDate.value, mode.value] as const,
  ([strategy, product, frequency, through]) => {
    if (!through) return
    void reference.refresh({ strategy, product, frequency, mode: mode.value }, {
      since: since.value, through,
    })
  }, { immediate: true })
onBeforeUnmount(reference.dispose)
</script>

<template>
  <section class="reference-trade-panel" aria-label="统一参考交易">
    <header>
      <h2>参考交易</h2>
      <nav aria-label="参考记录模式">
        <button v-if="historicalAvailable" type="button" :aria-pressed="mode === 'historical_replay'" @click="mode = 'historical_replay'">历史参考</button>
        <button type="button" :aria-pressed="mode === 'forward_observation'" @click="mode = 'forward_observation'">盘中观察参考</button>
      </nav>
    </header>
    <p class="reference-trade-panel__note">零费用、零滑点的页面参考记录；不代表账户成交。</p>
    <p v-if="reference.loading.value" role="status">读取参考记录中…</p>
    <p v-else-if="reference.error.value" role="status">{{ reference.error.value }}</p>
    <template v-if="reference.stream.value && reference.page.value">
      <p v-if="mode === 'forward_observation'" role="status">
        记录起点 {{ formatBeijingInstant(reference.stream.value.recording_start) }} ·
        计算至 {{ formatBeijingInstant(reference.page.value.coverage?.computed_through) }} ·
        <template v-if="reference.page.value.coverage?.observation_boundary_at">观察中断于 {{ formatBeijingInstant(reference.page.value.coverage.observation_boundary_at) }} ·</template>
        观察连续性 {{ reference.page.value.coverage?.complete_window_proven ? '已证明' : '待核对' }} ·
        Canonical 核对待执行
      </p>
      <p v-if="reference.summary.value">已平 {{ reference.summary.value.closed_count }} · 未平 {{ reference.summary.value.open_count }} · 中断 {{ reference.summary.value.interrupted_count }}</p>
      <section v-if="mode === 'forward_observation' && reference.signals.value.length" aria-label="首次观察记录">
        <h3>首次观察记录</h3>
        <ul>
          <li v-for="(signal, index) in reference.signals.value" :key="index">
            {{ formatBeijingInstant(String(signal.value.observed_at ?? '')) }} ·
            {{ Array.isArray(signal.value.observation_types) && signal.value.observation_types.length ? signal.value.observation_types.join(' / ') : String(signal.value.direction ?? '首次观察') }} ·
            {{ formatBeijingInstant(String(signal.value.bar_end ?? '')) }}
          </li>
        </ul>
      </section>
      <div class="reference-trade-panel__table"><table>
        <thead><tr><th>方向 / 状态</th><th>合约</th><th>开仓参考</th><th>平仓参考</th><th>收益</th></tr></thead>
        <tbody><tr v-for="trade in reference.page.value.items" :key="trade.reference_trade_id">
          <td>{{ trade.side === 'LONG' ? '多' : '空' }} · {{ trade.status }}</td>
          <td>{{ trade.physical_contract }}</td>
          <td>{{ formatMarketDecimal(trade.entry_reference_price) }}<small>{{ formatBeijingInstant(trade.entry_bar_end) }}</small></td>
          <td>{{ formatMarketDecimal(trade.exit_reference_price) }}<small>{{ formatBeijingInstant(trade.exit_bar_end) }}</small></td>
          <td>{{ trade.reference_return === null ? '—' : `${trade.reference_return}%` }}</td>
        </tr></tbody>
      </table></div>
      <p v-if="!reference.page.value.items.length">所选窗口暂无已观察的参考交易。</p>
      <button v-if="reference.page.value.next_cursor" type="button" :disabled="reference.loading.value" @click="reference.loadMore()">加载更多</button>
    </template>
  </section>
</template>

<style scoped>
.reference-trade-panel { border: 1px solid var(--gy-border); border-radius: var(--gy-radius-md); padding: var(--gy-space-3); background: var(--gy-bg-panel); }
header, nav { display: flex; flex-wrap: wrap; align-items: center; gap: var(--gy-space-2); }
header { justify-content: space-between; } h2 { font-size: 1rem; margin: 0; }
button { cursor: pointer; border: 1px solid var(--gy-border); border-radius: var(--gy-radius-sm); background: var(--gy-bg-panel); padding: 0.35rem 0.65rem; }
button[aria-pressed="true"] { font-weight: 700; }
.reference-trade-panel__note { color: var(--gy-text-muted); font-size: 0.85rem; }
.reference-trade-panel__table { overflow-x: auto; } table { width: 100%; border-collapse: collapse; min-width: 580px; }
th, td { padding: 0.5rem; border-bottom: 1px solid var(--gy-border); text-align: left; } small { display: block; color: var(--gy-text-muted); }
</style>
