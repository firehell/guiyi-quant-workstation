<script setup lang="ts">
import { computed, ref } from 'vue'
import type { HtdySnapshot } from '@/types/htdySnapshot'
import type { ReferenceTradeView } from '@/types/referenceTrading'
import { formatBeijingInstant, formatDecimalText, formatMarketDecimal } from '@/utils/marketDisplay'
import { returnCurveLayout } from '@/utils/returnCurveLayout'
import ReturnCurveSvg from '@/components/charts/ReturnCurveSvg.vue'
const props=defineProps<{data:HtdySnapshot|null;rows:ReferenceTradeView[];loading:boolean;moreLoading:boolean;error:string|null}>()
const emit=defineEmits<{read:[];more:[];focus:[identity:{barEnd:string;physicalContract:string}]}>()
const all=ref(false)
const visible=computed(()=>all.value?props.rows:props.rows.slice(0,3))
const plot=computed(()=>returnCurveLayout((props.data?.curve??[]).map(p=>({...p,date:p.date??p.bar_end.slice(0,10),segment:p.segment??p.reference_trade_id,position:Date.parse(p.bar_end),value:Number(p.value)})),{headroom:1.1,areaBaseline:'zero',valueUnit:'percentage_points',singlePoint:'start'}))
const pct=(v:unknown)=>typeof v==='string'?`${formatDecimalText(v,{maximumFractionDigits:2,signed:true})}%`:'—'
const labels:Record<string,string>={CLOSED:'已平参考',OPEN:'未平参考',ROLLOVER_INTERRUPTED:'换月中断',DATA_INTERRUPTED:'质量中断'}
function focus(row:ReferenceTradeView){if(typeof row.physical_contract==='string')emit('focus',{barEnd:row.entry_bar_end,physicalContract:row.physical_contract})}
</script>
<template>
 <section class="htdy-history-panel performance-panel" aria-label="历史回放参考交易">
  <header><h3>历史回放参考</h3><button type="button" :disabled="loading" @click="emit('read')">重新读取快照</button></header>
  <p class="note">逐根完成K线回放 · 信号收盘参考价 · 零费用／零滑点 · 非账户收益</p>
  <p v-if="loading" role="status">正在读取历史快照…</p>
  <p v-if="error" role="alert">{{ error }}</p>
  <template v-if="data">
   <p class="note">{{ data.since }} → {{ data.through }} · 计算至 {{ formatBeijingInstant(data.computed_through) }} <span :title="data.snapshot_id">· 冻结快照 {{ data.snapshot_id.slice(0,12) }}</span></p>
   <ReturnCurveSvg v-if="plot.points.length" :plot="plot" label="历史回放参考累计收益百分点曲线" area zero-line />
   <p v-else>此快照暂无已完成参考交易。</p>
   <p v-if="plot.message" role="status">{{ plot.message }}</p>
   <dl><div><dt>累计参考收益</dt><dd>{{ data.summary.sum_return_percentage_points == null ? '—' : formatDecimalText(data.summary.sum_return_percentage_points,{maximumFractionDigits:2,signed:true})+' 百分点' }}</dd></div><div><dt>参考胜率</dt><dd>{{ pct(data.summary.win_rate_pct) }}</dd></div><div><dt>已平参考交易</dt><dd>{{ data.summary.closed }}</dd></div></dl>
   <div class="trades"><article v-for="row in visible" :key="row.reference_trade_id"><header><strong>{{ labels[row.status]??'中断' }} · {{ row.side==='LONG'?'多':'空' }} · {{ row.physical_contract }}</strong><b>{{ pct(row.reference_return) }}</b></header><p>建仓参考 {{ formatMarketDecimal(row.entry_reference_price) }} · {{ formatBeijingInstant(row.entry_bar_end) }}</p><p v-if="row.exit_bar_end">平仓参考 {{ formatMarketDecimal(row.exit_reference_price) }} · {{ formatBeijingInstant(row.exit_bar_end) }}</p><p v-else>{{ row.status==='OPEN'?'保留未平参考，不计已平收益':'中断记录，不计已平收益' }}</p><button type="button" @click="focus(row)">定位图表</button></article></div>
   <button v-if="!all && rows.length>3" type="button" @click="all=true">查看全部已加载记录</button><button v-if="all && data.next_cursor" type="button" :disabled="loading||moreLoading" @click="emit('more')">{{ moreLoading?'读取中…':'读取更多' }}</button>
   <p class="note">未平 {{ data.summary.open }} · 中断 {{ data.summary.interrupted??0 }}；收益仅统计本快照已平参考交易，不与实时参考或 SimNow 拼接。</p>
  </template>
 </section>
</template>
<style scoped>
.htdy-history-panel{padding:16px;min-width:0;border:1px solid var(--gy-border);border-radius:12px}header,dl{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}h3{margin:0;font-size:16px}p{font-size:12px;line-height:1.6}.note{color:var(--gy-text-muted)}dl>div{flex:1;min-width:100px}dt{font-size:12px;color:var(--gy-text-muted)}dd{margin:6px 0}.trades{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:12px}article{padding:12px;border:1px solid var(--gy-border);border-radius:8px}article header{font-size:12px}button{padding:6px 10px;margin:4px 6px 4px 0;border:1px solid var(--gy-border);border-radius:6px;background:var(--gy-bg-panel);color:var(--gy-text-primary);cursor:pointer}
</style>
