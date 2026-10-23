<script setup lang="ts">
import { ref, watch } from 'vue'
import type { HtdyHistoricalResponse } from '@/types/htdyReference'
import type { ReferenceTradeView } from '@/types/referenceTrading'
import { formatBeijingInstant, formatMarketDecimal } from '@/utils/marketDisplay'
const props = defineProps<{ stale?: boolean; result: HtdyHistoricalResponse | null; loading: boolean; error: string | null; focusError: string | null }>()
defineEmits<{ more: []; retry: []; window: [window: { since: string; through: string }]; focus: [trade: ReferenceTradeView] }>()
const since = ref(''), through = ref('')
const statusLabels: Record<string, string> = { OPEN: '未平', CLOSED: '已平', ROLLOVER_INTERRUPTED: '换月中断', DATA_INTERRUPTED: '数据中断', DATA_CONFLICT: '数据冲突' }
watch(() => props.result, result => { if (result) { since.value = result.since; through.value = result.through } }, { immediate: true })
</script>
<template>
  <section class="htdy-history" aria-label="火天大有历史重算参考记录">
    <p>历史重算 · 零费用、零滑点 · 不代表实际观察或账户成交</p>
    <form @submit.prevent="$emit('window', { since, through })"><label>开始 <input v-model="since" type="date" required></label> <label>截至 <input v-model="through" type="date" required></label> <button type="submit" :disabled="loading">读取窗口</button> <button type="button" :disabled="loading" @click="$emit('retry')">重新读取</button></form>
    <p v-if="stale" role="status">已有更新的完成K线，当前历史参考已过期；重新读取后更新。</p>
    <p v-if="loading" role="status">读取历史参考中…</p>
    <p v-if="error" role="status">{{ error }} <button type="button" @click="$emit('retry')">重试</button></p>
    <p v-if="focusError" role="status">{{ focusError }}</p>
    <template v-if="result">
      <p>计算至 {{ formatBeijingInstant(result.computed_through) }} · 已平 {{ result.summary.closed }} · 未平 {{ result.summary.open }}</p>
      <div class="htdy-history__table"><table><thead><tr><th>方向 / 状态</th><th>合约</th><th>开仓参考</th><th>平仓参考</th><th>持有周期</th><th>参考收益</th></tr></thead>
      <tbody><tr v-for="trade in result.trades" :key="trade.reference_trade_id" @click="$emit('focus', trade)">
        <td><button type="button" @click.stop="$emit('focus', trade)">{{ trade.side === 'LONG' ? '多' : '空' }} · {{ statusLabels[trade.status] ?? trade.status }}</button></td>
        <td>{{ trade.physical_contract }}</td><td>{{ formatMarketDecimal(trade.entry_reference_price) }}<small>{{ formatBeijingInstant(trade.entry_bar_end) }}</small></td>
        <td>{{ formatMarketDecimal(trade.exit_reference_price) }}<small>{{ formatBeijingInstant(trade.exit_bar_end) }}</small></td>
        <td>{{ trade.holding_bars }}</td><td>{{ trade.reference_return === null ? '—' : `${trade.reference_return}%` }}</td>
      </tr></tbody></table></div>
      <p v-if="!result.trades.length">所选窗口暂无历史参考交易。</p>
      <button v-if="result.next_cursor" :disabled="loading" type="button" @click="$emit('more')">加载更多记录</button>
    </template>
  </section>
</template>
<style scoped>
.htdy-history { padding: 12px; border: 1px solid var(--gy-border); border-radius: 8px; font-size: 13px; }
.htdy-history form { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.htdy-history__table { overflow-x: auto; } table { width: 100%; border-collapse: collapse; } th,td { text-align: left; padding: 8px; border-bottom: 1px solid var(--gy-border); } small { display: block; color: var(--gy-text-muted); } button { cursor: pointer; }
</style>
