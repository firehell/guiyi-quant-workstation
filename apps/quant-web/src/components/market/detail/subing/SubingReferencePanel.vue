<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { SubingReferenceResponse, SubingReferenceTrade } from '@/types/subingReference'
import { referenceTone, referenceDecimalDisplay } from '@/utils/subingReference'
import { formatBeijingInstant, formatMarketDecimal } from '@/utils/marketDisplay'
const props = defineProps<{ data: SubingReferenceResponse | null; loading: boolean; error: string | null }>()
const emit = defineEmits<{ refresh: [dates: { since?: string; through?: string }]; 'load-more': []; focus: [trade: SubingReferenceTrade]; details: [trade: SubingReferenceTrade] }>()
const since = ref(''); const through = ref('')
const invalidRange = computed(() => !!since.value && !!through.value && since.value > through.value)
watch(() => props.data, (data) => { if (data) { since.value = data.performance_since; through.value = data.performance_through } })
function refresh() { if (!invalidRange.value) emit('refresh', { ...(since.value ? { since: since.value } : {}), ...(through.value ? { through: through.value } : {}) }) }
const statusLabel = (trade: SubingReferenceTrade) => trade.status === 'CLOSED' ? '已平参考' : trade.status === 'OPEN' ? '未平参考' : trade.status === 'DATA_INTERRUPTED' ? '数据中断' : '换月中断'
const readinessLabel = (status: SubingReferenceResponse['research_status']) => ({ WARMING: '预热中（不足 34 根有效日线）', INDICATOR_READY_CROSS_UNEVALUABLE: '指标已就绪，交叉尚不可判定（34 根）', CROSS_EVALUATED: '交叉可判定（至少 35 根）', warming: '预热中', ready: '已就绪' })[status]
</script>
<template>
  <section class="subing-reference" aria-label="历史参考交易">
    <header><div><h2>乐观参考交易</h2><p>{{ data?.storage_mode === 'persisted' ? '历史参考·已保存' : '历史重算·乐观参考' }}｜零费用/零滑点</p></div><span>{{ data?.frequency ?? '当前周期' }} · 双向反手 · 非可执行</span></header>
    <form @submit.prevent="refresh"><label>开始交易日<input v-model="since" type="date" aria-label="参考开始交易日" /></label><label>结束交易日<input v-model="through" type="date" aria-label="参考结束交易日" /></label><button type="submit" :disabled="loading || invalidRange">{{ loading ? '读取中…' : '读取参考' }}</button></form>
    <p v-if="invalidRange" class="subing-reference__validation" role="alert">开始交易日不能晚于结束交易日。</p>
    <p v-if="error" role="status">{{ error }}</p>
    <template v-if="data">
      <div class="subing-reference__summary"><span>已平 <b>{{ data.summary.closed_count }}</b></span><span>胜 / 负 / 平 <b>{{ data.summary.win_count }} / {{ data.summary.loss_count }} / {{ data.summary.flat_count }}</b></span><span>胜率 <b>{{ data.summary.win_rate_pct === null ? '—' : `${referenceDecimalDisplay(data.summary.win_rate_pct, false)}%` }}</b></span><span>平均参考收益 <b :class="referenceTone(data.summary.mean_return_pct)">{{ data.summary.mean_return_pct === null ? '—' : `${referenceDecimalDisplay(data.summary.mean_return_pct)}%` }}</b></span><span>收益百分比之和 <b :class="referenceTone(data.summary.sum_return_percentage_points)">{{ referenceDecimalDisplay(data.summary.sum_return_percentage_points) }} 百分点</b></span></div>
      <p class="subing-reference__note">统计按所选交易日固定，不随图表缩放或翻页变化。未平 {{ data.summary.open_count }} · 换月中断 {{ data.summary.rollover_interrupted_count ?? data.summary.interrupted_count }} · 数据中断 {{ data.summary.data_interrupted_count ?? 0 }} · 窗口初始 {{ data.summary.initial_count }}；未平和中断不计入已平收益。百分比之和不是账户复利收益。</p>
      <p v-if="data.frequency === '1d'" role="status">日线质量状态：{{ readinessLabel(data.research_status) }}；质量中断 {{ data.quality_interruptions?.length ?? 0 }} 项。</p>
      <p v-if="data.signals.length" class="subing-reference__note">最近历史信号内核：{{ data.signals.at(-1)?.physical_contract }} · {{ formatBeijingInstant(data.signals.at(-1)?.bar_end) }} · DIF {{ data.signals.at(-1)?.dif ?? '—' }} / DEA {{ data.signals.at(-1)?.dea ?? '—' }} / MACD×2 {{ data.signals.at(-1)?.macd ?? '—' }} / EMA21 {{ data.signals.at(-1)?.ema21 ?? '—' }}。仅说明该物理合约完整前缀上的历史信号。</p>
      <div class="subing-reference__table"><table><thead><tr><th>方向 / 状态</th><th>物理合约</th><th>开仓参考</th><th>平仓参考</th><th>持有 Bar</th><th>参考收益 / 浮动</th><th>操作</th></tr></thead><tbody><tr v-for="trade in data.items" :key="trade.reference_trade_id"><td>{{ trade.side === 'LONG' ? '多' : '空' }} · {{ statusLabel(trade) }}{{ trade.initial ? ' · 窗口初始' : '' }}</td><td>{{ trade.physical_contract }}</td><td>{{ formatMarketDecimal(trade.entry_reference_price) }}<small>{{ formatBeijingInstant(trade.entry_bar_end) }}</small></td><td>{{ formatMarketDecimal(trade.exit_reference_price) }}<small>{{ (trade.exit_bar_end ? formatBeijingInstant(trade.exit_bar_end) : null) ?? (trade.status === 'DATA_INTERRUPTED' ? `数据中断（${trade.interruption_reason}），未配对平仓` : trade.status === 'ROLLOVER_INTERRUPTED' ? '换月中断，未配对平仓' : '尚无反向信号') }}</small></td><td>{{ trade.holding_bars }}</td><td :class="referenceTone(trade.reference_return_pct ?? trade.mark_change_pct)">{{ trade.reference_return_pct !== null ? `${referenceDecimalDisplay(trade.reference_return_pct)}%` : trade.mark_change_pct !== null ? `${referenceDecimalDisplay(trade.mark_change_pct)}% · 参考浮动` : '—' }}</td><td class="subing-reference__actions"><button type="button" @click="emit('focus', trade)">定位图表</button><button type="button" @click="emit('details', trade)">查看详情</button></td></tr></tbody></table></div>
      <p v-if="data.research_status === 'warming' || data.research_status === 'WARMING' || data.research_status === 'INDICATOR_READY_CROSS_UNEVALUABLE'" role="status">物理合约当前计算分段尚未形成可判定交叉；当前零交易不能解释为无信号或零胜率。</p>
      <p v-else-if="!data.items.length">已完成计算，所选窗口暂无历史参考记录。</p>
      <button v-if="data.next_before" type="button" :disabled="loading" @click="emit('load-more')">{{ loading ? '读取中…' : '加载更多参考记录' }}</button>
      <p class="subing-reference__note">历史来源截止 {{ formatBeijingInstant(data.reference_cutoff) }} · {{ data.performance_since }} — {{ data.performance_through }}</p>
    </template>
  </section>
</template>
<style scoped>
.subing-reference { border: 1px solid #ddd6cc; padding: 18px; background: #fff; color: #463e35; min-width: 0; }
header { display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; align-items: center; } h2 { margin: 0; font-size: 17px; } p { font-size: 12px; line-height: 1.7; } header span { font-size: 12px; color: #8b7b6a; }
form { display: flex; gap: 12px; align-items: end; flex-wrap: wrap; margin: 12px 0; } label { display: grid; gap: 5px; font-size: 12px; } input, button { min-height: 40px; border: 1px solid #cfc3b6; background: #fffefa; border-radius: 3px; color: #615345; padding: 7px 10px; } button { cursor: pointer; } button:disabled { opacity: .6; }
.subing-reference__summary { display: flex; gap: 18px; flex-wrap: wrap; padding: 15px 0; border-top: 1px solid #ede8e1; font-size: 12px; } b { margin-left: 4px; font-size: 15px; font-weight: 500; }
.subing-reference__note { color: #8b8174; }.subing-reference__validation { margin: -6px 0 10px; color: #a63232; }.subing-reference__table { overflow-x: auto; } table { width: 100%; border-collapse: collapse; font-size: 12px; white-space: nowrap; } th, td { padding: 12px 8px; border-bottom: 1px solid #eee9e2; text-align: left; } th { font-weight: 500; color: #8b8174; } small { display: block; margin-top: 5px; color: #918677; } .subing-reference__actions { display: flex; gap: 6px; }.subing-reference__actions button { min-height: 34px; padding: 5px 8px; }.gain { color: #cb3737; } .loss { color: #188052; }
@media (max-width: 600px) { .subing-reference { padding: 12px; } form { gap: 8px; } input { width: 140px; } .subing-reference__summary { gap: 12px; } }
</style>
