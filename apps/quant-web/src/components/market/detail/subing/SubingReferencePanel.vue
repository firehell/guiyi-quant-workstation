<script setup lang="ts">
import { ref, watch } from 'vue'
import type { SubingReferenceResponse, SubingReferenceTrade } from '@/types/subingReference'
import { formatChartTimeInShanghai } from '@/utils/barTime'
import { referenceTone, referenceDecimalDisplay } from '@/utils/subingReference'
const props = defineProps<{ data: SubingReferenceResponse | null; loading: boolean; error: string | null }>()
const emit = defineEmits<{ refresh: [dates: { since?: string; through?: string }]; 'load-more': []; focus: [trade: SubingReferenceTrade] }>()
const since = ref(''); const through = ref('')
watch(() => props.data, (data) => { if (data) { since.value = data.performance_since; through.value = data.performance_through } })
function refresh() { emit('refresh', { ...(since.value ? { since: since.value } : {}), ...(through.value ? { through: through.value } : {}) }) }
const statusLabel = (trade: SubingReferenceTrade) => trade.status === 'CLOSED' ? '已平参考' : trade.status === 'OPEN' ? '未平参考' : '换月中断'
</script>
<template>
  <section class="subing-reference" aria-label="历史参考交易">
    <header><div><h2>乐观参考交易</h2><p>历史重算·乐观参考｜零费用/零滑点</p></div><span>固定 15m · 双向反手 · 非可执行</span></header>
    <form @submit.prevent="refresh"><label>开始交易日<input v-model="since" type="date" aria-label="参考开始交易日" /></label><label>结束交易日<input v-model="through" type="date" aria-label="参考结束交易日" /></label><button type="submit" :disabled="loading || (!!since && !!through && since > through)">{{ loading ? '读取中…' : '读取参考' }}</button></form>
    <p v-if="error" role="status">{{ error }}</p>
    <template v-if="data">
      <div class="subing-reference__summary"><span>已平 <b>{{ data.summary.closed_count }}</b></span><span>胜 / 负 / 平 <b>{{ data.summary.win_count }} / {{ data.summary.loss_count }} / {{ data.summary.flat_count }}</b></span><span>胜率 <b>{{ data.summary.win_rate_pct === null ? '—' : `${referenceDecimalDisplay(data.summary.win_rate_pct, false)}%` }}</b></span><span>平均参考收益 <b :class="referenceTone(data.summary.mean_return_pct)">{{ data.summary.mean_return_pct === null ? '—' : `${referenceDecimalDisplay(data.summary.mean_return_pct)}%` }}</b></span><span>收益百分比之和 <b :class="referenceTone(data.summary.sum_return_percentage_points)">{{ referenceDecimalDisplay(data.summary.sum_return_percentage_points) }} 百分点</b></span></div>
      <p class="subing-reference__note">统计按所选交易日固定，不随图表缩放或翻页变化。未平 {{ data.summary.open_count }} · 换月中断 {{ data.summary.interrupted_count }} · 窗口初始 {{ data.summary.initial_count }}；未平和中断不计入已平收益。百分比之和不是账户复利收益。</p>
      <div class="subing-reference__table"><table><thead><tr><th>方向 / 状态</th><th>物理合约</th><th>开仓参考</th><th>平仓参考</th><th>持有 Bar</th><th>参考收益 / 浮动</th></tr></thead><tbody><tr v-for="trade in data.items" :key="trade.reference_trade_id"><td><button type="button" @click="emit('focus', trade)">{{ trade.side === 'LONG' ? '多' : '空' }} · {{ statusLabel(trade) }}{{ trade.initial ? ' · 窗口初始' : '' }}</button></td><td>{{ trade.physical_contract }}</td><td>{{ trade.entry_reference_price }}<small>{{ formatChartTimeInShanghai(trade.entry_bar_end) }}</small></td><td>{{ trade.exit_reference_price ?? '—' }}<small>{{ (trade.exit_bar_end ? formatChartTimeInShanghai(trade.exit_bar_end) : null) ?? (trade.status === 'ROLLOVER_INTERRUPTED' ? '换月中断，未配对平仓' : '尚无反向信号') }}</small></td><td>{{ trade.holding_bars }}</td><td :class="referenceTone(trade.reference_return_pct ?? trade.mark_change_pct)">{{ trade.reference_return_pct !== null ? `${referenceDecimalDisplay(trade.reference_return_pct)}%` : trade.mark_change_pct !== null ? `${referenceDecimalDisplay(trade.mark_change_pct)}% · 参考浮动` : '—' }}</td></tr></tbody></table></div>
      <p v-if="!data.items.length">所选窗口暂无历史参考记录。</p>
      <button v-if="data.next_before" type="button" :disabled="loading" @click="emit('load-more')">{{ loading ? '读取中…' : '加载更多参考记录' }}</button>
      <p class="subing-reference__note">历史来源截止 {{ formatChartTimeInShanghai(data.reference_cutoff) }}（北京时间） · {{ data.performance_since }} — {{ data.performance_through }}</p>
      <details><summary>参考来源与版本</summary><p>{{ data.performance_since }} — {{ data.performance_through }} · 截止 {{ data.reference_cutoff }}</p><p>{{ data.formula_version }} · {{ data.reference_model_version }}</p><p>快照 {{ data.input_snapshot_hash }}</p><p>as_of {{ data.as_of }} · historical_replay · executable=false · auto_order=false</p></details>
    </template>
  </section>
</template>
<style scoped>
.subing-reference { border: 1px solid #ddd6cc; padding: 18px; background: #fff; color: #463e35; min-width: 0; }
header { display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; align-items: center; } h2 { margin: 0; font-size: 17px; } p { font-size: 12px; line-height: 1.7; } header span { font-size: 12px; color: #8b7b6a; }
form { display: flex; gap: 12px; align-items: end; flex-wrap: wrap; margin: 12px 0; } label { display: grid; gap: 5px; font-size: 12px; } input, button { min-height: 40px; border: 1px solid #cfc3b6; background: #fffefa; border-radius: 3px; color: #615345; padding: 7px 10px; } button { cursor: pointer; } button:disabled { opacity: .6; }
.subing-reference__summary { display: flex; gap: 18px; flex-wrap: wrap; padding: 15px 0; border-top: 1px solid #ede8e1; font-size: 12px; } b { margin-left: 4px; font-size: 15px; font-weight: 500; }
.subing-reference__note { color: #8b8174; }.subing-reference__table { overflow-x: auto; } table { width: 100%; border-collapse: collapse; font-size: 12px; white-space: nowrap; } th, td { padding: 12px 8px; border-bottom: 1px solid #eee9e2; text-align: left; } th { font-weight: 500; color: #8b8174; } small { display: block; margin-top: 5px; color: #918677; } .gain { color: #cb3737; } .loss { color: #188052; } details { margin-top: 16px; font-size: 12px; overflow-wrap: anywhere; } summary { cursor: pointer; }
@media (max-width: 600px) { .subing-reference { padding: 12px; } form { gap: 8px; } input { width: 140px; } .subing-reference__summary { gap: 12px; } }
</style>
