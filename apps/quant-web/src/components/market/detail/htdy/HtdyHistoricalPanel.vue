<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import PerformancePanel from '@/components/performance/PerformancePanel.vue'
import MarketDetailDrawer from '@/components/market/detail/MarketDetailDrawer.vue'
import type { HtdyHistoricalResponse } from '@/types/htdyReference'
import type { ReferenceTradeView } from '@/types/referenceTrading'
import { formatBeijingInstant, formatMarketDecimal, formatMarketPercent } from '@/utils/marketDisplay'
import { referenceTone, referenceDecimalDisplay } from '@/utils/subingReference'
const props = defineProps<{ stale?: boolean; result: HtdyHistoricalResponse | null; loading: boolean; error: string | null; focusError: string | null }>()
const emit = defineEmits<{ more: []; retry: []; window: [window: { since: string; through: string }]; focus: [trade: ReferenceTradeView] }>()
const since = ref(''), through = ref(''), selected = ref<ReferenceTradeView | null>(null)
const invalidRange = computed(() => Boolean(since.value && through.value && since.value > through.value))
const statusLabels: Record<string, string> = { OPEN: '未平参考', CLOSED: '已平参考', ROLLOVER_INTERRUPTED: '换月中断', DATA_INTERRUPTED: '数据中断', DATA_CONFLICT: '数据冲突' }
const text = (value: unknown) => typeof value === 'string' ? value : null
const percent = (value: unknown) => formatMarketPercent(text(value), 'percentage_points', true)
const tradeReturn = (trade: ReferenceTradeView) => trade.reference_return ?? text(trade.mark_return)
watch(() => props.result, result => { if (result) { since.value = result.since; through.value = result.through }; selected.value = null }, { immediate: true })
function readWindow() { if (!invalidRange.value) { if (since.value && through.value) emit('window', { since: since.value, through: through.value }); else emit('retry') } }
</script>
<template>
  <PerformancePanel class="htdy-history reference-history" title="策略收益与参考记录" kind="已完成参考交易" :since="result?.since" :through="result?.through" :loading="loading" :error="error" description="按入场交易日窗口统计；零手续费、零滑点，非账户收益。">
    <header><div><h3>历史重算参考</h3><p>历史重算·乐观参考｜零费用/零滑点</p></div><span>{{ result?.frequency ?? '当前周期' }} · 双向反手 · 非可执行</span></header>
    <form @submit.prevent="readWindow"><label>开始交易日<input v-model="since" type="date" aria-label="参考开始交易日"></label><label>结束交易日<input v-model="through" type="date" aria-label="参考结束交易日"></label><button type="submit" :disabled="loading || invalidRange">{{ loading ? '读取中…' : '读取参考' }}</button></form>
    <p v-if="invalidRange" class="reference-history__validation" role="alert">开始交易日不能晚于结束交易日。</p>
    <p v-if="stale" role="status">已有更新的完成K线，当前历史参考已过期；请重新读取。</p>
    <p v-if="error"><button type="button" :disabled="loading" @click="emit('retry')">重试</button></p>
    <p v-if="focusError" role="status">{{ focusError }}</p>
    <template v-if="result">
      <div class="reference-history__summary"><span>已平 <b>{{ result.summary.closed }}</b></span><span>胜 / 负 / 平 <b>{{ result.summary.wins ?? '—' }} / {{ result.summary.losses ?? '—' }} / {{ result.summary.flat ?? '—' }}</b></span><span>胜率 <b>{{ formatMarketPercent(result.summary.win_rate_pct, 'percentage_points') }}</b></span><span>平均参考收益 <b :class="referenceTone(result.summary.mean_return_pct ?? null)">{{ percent(result.summary.mean_return_pct) }}</b></span><span>累计参考收益（百分点） <b :class="referenceTone(result.summary.sum_return_percentage_points ?? null)">{{ referenceDecimalDisplay(result.summary.sum_return_percentage_points ?? null) }} 百分点</b></span></div>
      <p class="reference-history__note">统计按所选交易日固定，不随图表缩放或翻页变化。未平 {{ result.summary.open }} · 中断 {{ result.summary.interrupted ?? '—' }}；未平和中断不计入已平收益。百分比之和不是账户复利收益。</p>
      <div class="reference-history__table"><table><thead><tr><th>方向 / 状态</th><th>物理合约</th><th>建仓参考</th><th>清仓参考</th><th>持有 Bar</th><th>参考收益 / 浮动</th><th>操作</th></tr></thead><tbody>
        <tr v-for="trade in result.trades" :key="trade.reference_trade_id"><td>{{ trade.side === 'LONG' ? '多' : '空' }} · {{ statusLabels[trade.status] ?? trade.status }}</td><td>{{ trade.physical_contract }}</td><td>{{ formatMarketDecimal(trade.entry_reference_price) }}<small>{{ formatBeijingInstant(trade.entry_bar_end) }}</small></td><td>{{ formatMarketDecimal(trade.exit_reference_price) }}<small>{{ trade.exit_bar_end ? formatBeijingInstant(trade.exit_bar_end) : trade.status === 'OPEN' ? '尚无反向信号' : '已中断，未配对平仓' }}</small></td><td>{{ trade.holding_bars }}</td><td :class="referenceTone(tradeReturn(trade))">{{ percent(tradeReturn(trade)) }}{{ trade.status === 'OPEN' && tradeReturn(trade) !== null ? ' · 参考浮动' : '' }}</td><td class="reference-history__actions"><button type="button" @click="emit('focus', trade)">定位图表</button><button type="button" @click="selected = trade">查看详情</button></td></tr>
      </tbody></table></div>
      <p v-if="!result.trades.length">已完成计算，所选窗口暂无历史参考记录。</p>
      <button v-if="result.next_cursor" type="button" :disabled="loading" @click="emit('more')">{{ loading ? '读取中…' : '加载更多参考记录' }}</button>
      <p class="reference-history__note">历史来源截止 {{ formatBeijingInstant(result.computed_through) }} · {{ result.since }} — {{ result.through }}</p>
    </template>
    <MarketDetailDrawer :open="selected !== null" title="火天大有历史参考详情" @close="selected = null"><template v-if="selected"><p>{{ selected.physical_contract }} · {{ selected.side === 'LONG' ? '多' : '空' }} · {{ statusLabels[selected.status] ?? selected.status }}</p><p>建仓参考 {{ formatMarketDecimal(selected.entry_reference_price) }} · {{ formatBeijingInstant(selected.entry_bar_end) }}</p><p>清仓参考 {{ formatMarketDecimal(selected.exit_reference_price) }} · {{ selected.exit_bar_end ? formatBeijingInstant(selected.exit_bar_end) : '尚未配对平仓' }}</p><p>持有 {{ selected.holding_bars }} 根 Bar · 参考收益 / 浮动 {{ percent(tradeReturn(selected)) }}</p><p>历史重算｜零费用/零滑点，非账户成交。</p><p>{{ selected.reference_trade_id }}</p></template></MarketDetailDrawer>
  </PerformancePanel>
</template>
<style scoped src="@/styles/referenceHistory.css"></style>
