<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import KlineChart from '@/components/kline/KlineChart.vue'
import DetailPricePreview from '@/components/market/detail/DetailPricePreview.vue'
import FrozenFields from './FrozenFields.vue'
import FuturesCurvePanel from './FuturesCurvePanel.vue'
import FuturesRecordsTable from './FuturesRecordsTable.vue'
import type { DetailPricePreview as PricePreview } from '@/composables/useDetailPricePreview'
import type { MarketDetailIdentity } from '@/types/marketDetail'
import type { FuturesSnapshot, FuturesPart, FuturesPage } from '@/types/newowFutures'
import { getFuturesSnapshot, getFuturesPart } from '@/api/newowFutures'
import { createFuturesSnapshotResource, futuresChartBars, futuresChartMarkers, futuresChartCallouts, futuresReferenceIndicators } from '@/utils/newowFuturesSnapshot'
import { futuresRecordKey, locateFuturesRecord, type FuturesLocateEndpoint } from '@/utils/newowFuturesLocate'
import type { FrozenRecord } from '@/types/newowFutures'
import { futuresVariant } from '@/utils/newowFutures'
import { futuresStrategyLabel, futuresAsOfLabel, futuresStateLabel, futuresFrequencyLabel, futuresTime, futuresNumber, futuresStatus, futuresReason, knownFuturesReason, futuresTradeColumns, type FuturesColumn } from '@/utils/newowFuturesPresentation'
const props=defineProps<{identity:MarketDetailIdentity;pricePreview:PricePreview}>()
const chart=ref<InstanceType<typeof KlineChart>|null>(null),chartRegion=ref<HTMLElement|null>(null)
const selectedRecordKey=ref<string|null>(null), locateNotice=ref<string|null>(null)
const chartSelection=ref<Array<{time:string;physicalContract:string}>>([])
const packet=shallowRef<FuturesSnapshot|null>(null),loading=ref(false),error=ref<string|null>(null)
const sourceKey=computed(()=>[props.identity.symbol,props.identity.frequency,futuresVariant(props.identity),props.identity.strategyModel].join(':'))
const resource=createFuturesSnapshotResource(getFuturesSnapshot,(value,pending,problem)=>{packet.value=value;loading.value=pending;error.value=problem})
watch(sourceKey,()=>{void resource.load({...props.identity})},{immediate:true,flush:'sync'})
const bars=computed(()=>packet.value ? futuresChartBars(packet.value):[])
const callouts=computed(()=>packet.value ? futuresChartCallouts(packet.value):[])
const markers=computed(()=>packet.value ? futuresChartMarkers(packet.value).filter(marker=>!callouts.value.some(callout=>callout.id===marker.id)):[])
const showTarget=ref(true), showStop=ref(true)
const referenceIndicators=computed(()=>packet.value?futuresReferenceIndicators(packet.value,showTarget.value,showStop.value):[])
const snapshot=computed(()=>packet.value?.reference.snapshot)
const diagnostics=computed(()=>packet.value && !Array.isArray(packet.value.diagnostics) ? packet.value.diagnostics : {})
const fundingText=computed(()=>{
  const count=diagnostics.value.funding_refusals
  if(typeof count!=='number')return packet.value?.metadata.status==='INSUFFICIENT_CAPITAL'?'账户资金不足，未能按风险与保证金约束开出最小一手；独立参考交易不受账户资金限制。':'资金、风险和保证金约束以模型账户执行结果为准。'
  return count>0?`有 ${count} 次因资金或风险预算不足被拒绝，未生成模拟成交；独立参考交易仍单独展示。`:'本次研究没有因资金或最小手数预算不足被拒绝的动作。'
})
const referenceMetrics=computed(()=>[
  {label:'已完成参考交易',value:packet.value?.reference.summary.closed_trades??'—',unit:'笔'},
  {label:'累计参考收益',value:futuresNumber(packet.value?.reference.summary.reference_return_pct),unit:'百分点'},
])
const accountMetrics=computed(()=>[
  {label:'初始资金',value:futuresNumber(packet.value?.summary.initial_cash),unit:'元'},
  {label:'期末权益',value:futuresNumber(packet.value?.summary.final_equity),unit:'元'},
  {label:'账户净收益率',value:futuresNumber(packet.value?.summary.account_return_pct),unit:'%'},
  {label:'最大回撤',value:futuresNumber(packet.value?.summary.max_drawdown_pct),unit:'%'},
  {label:'累计手续费',value:futuresNumber(packet.value?.summary.total_fees),unit:'元'},
  {label:'期末净持仓',value:packet.value?.summary.ending_qty??'—',unit:'手'},
])
const part=ref<FuturesPart>('reference-trades'),page=shallowRef<FuturesPage|null>(null),pageLoading=ref(false),pageError=ref<string|null>(null)
let pageOwner:AbortController|null=null
async function loadPage(offset=0){
  pageOwner?.abort();const owner=pageOwner=new AbortController(),current=packet.value,selected=part.value
  page.value=null;pageError.value=null;pageLoading.value=false
  if(!current)return
  pageLoading.value=true
  try{
    const value=await getFuturesPart(current.run_id,current.sha256,selected,offset,owner.signal)
    if(owner.signal.aborted)return
    if(value.run_id!==current.run_id || value.sha256!==current.sha256 || value.part!==selected || value.offset!==offset || value.items.length>50)throw new Error('RESULT_PAGE_IDENTITY_MISMATCH')
    page.value=value
  }catch{if(!owner.signal.aborted)pageError.value='记录读取失败或结果身份不一致'}
  finally{if(!owner.signal.aborted)pageLoading.value=false}
}
watch(packet,()=>{chartSelection.value=[];selectedRecordKey.value=null;locateNotice.value=null},{flush:'sync'})
async function locateRecord(row:FrozenRecord,endpoint:FuturesLocateEndpoint,source:FuturesPart|'reference-actions'){
  const current=packet.value;if(!current)return
  const result=locateFuturesRecord(current,row,endpoint,source)
  locateNotice.value=result.message;selectedRecordKey.value=futuresRecordKey(row);chartSelection.value=[]
  if(result.kind!=='located')return
  await nextTick();if(packet.value!==current)return
  if(!chart.value?.revealTime(result.barEnd,true)){locateNotice.value='无法定位到对应冻结Bar，未改变图表位置';return}
  chartSelection.value=[{time:result.barEnd,physicalContract:result.physicalContract}]
  chartRegion.value?.scrollIntoView({behavior:'smooth',block:'center'})
}
watch([packet,part],()=>{void loadPage()},{flush:'sync'})
const recordParts:ReadonlyArray<{value:FuturesPart;label:string}>=[{value:'reference-trades',label:'独立参考交易'},{value:'trades',label:'10万模型账户交易'},{value:'fills',label:'模拟成交'},{value:'decisions',label:'决策与拒绝'},{value:'equity',label:'模型账户权益'}]
const columns=computed(()=>futuresTradeColumns(part.value))
const actionColumns:FuturesColumn[]=[{key:'at',label:'信号时间',kind:'time'},{key:'action',label:'动作',kind:'action'},{key:'side',label:'方向',kind:'side'},{key:'reference_price',label:'参考价',kind:'number'},{key:'holding_frequency',label:'持有周期',kind:'frequency'},{key:'reason',label:'原因',kind:'reason'}]
function openHistory(){document.getElementById('futures-records')?.scrollIntoView({behavior:'smooth'})}
defineExpose({openHistory})
onBeforeUnmount(()=>{resource.dispose();pageOwner?.abort()})
</script>
<template>
  <section class="futures-workspace" data-testid="futures-workspace" :aria-busy="loading">
    <p class="futures-workspace__banner">归一自有期货双向研究 · 尚未证明样本外表现 · 自动下单关闭</p>
    <template v-if="packet">
      <header class="futures-workspace__heading"><h2>{{ futuresStrategyLabel(packet.metadata.strategy) }} <span>{{ futuresFrequencyLabel(packet.metadata.frequency) }}</span></h2><p>历史研究 · {{ futuresAsOfLabel(packet.metadata.as_of_kind) }} {{ futuresTime(packet.metadata.as_of) }} · {{ futuresStatus(packet.metadata.status) }}</p></header>
      <section class="futures-workspace__state" aria-label="策略参考状态">
        <div class="futures-workspace__state-title"><strong :data-side="snapshot?.side">{{ futuresStateLabel(snapshot?.side) }}</strong><span>持有周期 {{ snapshot?.holding_frequency ? futuresFrequencyLabel(snapshot.holding_frequency) : '—' }}</span><span>{{ snapshot?.overnight_eligible===true?'已满足跨日条件':snapshot?.overnight_eligible===false?'未满足跨日条件':'跨日条件未知' }}</span></div>
        <dl class="futures-workspace__metrics"><div><dt>参考入场价</dt><dd>{{ futuresNumber(snapshot?.entry_reference_price) }}</dd></div><div><dt>参考保护价</dt><dd>{{ futuresNumber(snapshot?.stop_reference_price) }}</dd></div><div><dt>参考目标价</dt><dd>{{ futuresNumber(snapshot?.target_reference_price) }}</dd></div><div><dt>周期升级</dt><dd>{{ snapshot?.upgrades ?? '—' }}<small>次</small></dd></div></dl>
        <p class="futures-workspace__note">{{ snapshot?.reason ? futuresReason(snapshot.reason) : '参考状态未知' }}。以上为冻结的策略参考状态。</p>
      </section>
      <div v-if="bars.length" class="futures-workspace__record-tabs" role="group" aria-label="参考线显示"><button type="button" :aria-pressed="showTarget" @click="showTarget=!showTarget">目标参考线</button><button type="button" :aria-pressed="showStop" @click="showStop=!showStop">保护参考线</button></div>
      <div v-if="bars.length" ref="chartRegion"><KlineChart ref="chart" :key="`${packet.run_id}:${packet.sha256}`" :bars="bars" :research-markers="markers" :reference-callouts="callouts" :reference-indicators="referenceIndicators" :reference-selection="chartSelection" series-kind="actual_dominant" :period="identity.frequency" :visible-main-indicators="[]" :marker-selection-enabled="false" :range-detector-source-identity="`${packet.run_id}:${packet.sha256}:futures_bidir_v1`"/></div>
      <p v-else role="status">该结果没有可验证的历史图表数据。</p>
      <div class="futures-workspace__summaries">
        <section aria-label="独立参考收益"><h3>独立参考交易</h3><p class="futures-workspace__note">完成信号收盘价 · 零手续费 / 零滑点 · 仅作参考</p><dl class="futures-workspace__metrics"><div v-for="metric in referenceMetrics" :key="metric.label"><dt>{{ metric.label }}</dt><dd>{{ metric.value }}<small>{{ metric.unit }}</small></dd></div></dl><FuturesCurvePanel :packet="packet" kind="reference-equity"/></section>
        <section aria-label="10万模型账户收益"><h3>10万元模型账户</h3><p class="futures-workspace__note">{{ futuresStatus(packet.summary.status) }} · 按模拟成交、成本与资金约束计账</p><dl class="futures-workspace__metrics"><div v-for="metric in accountMetrics" :key="metric.label"><dt>{{ metric.label }}</dt><dd>{{ metric.value }}<small>{{ metric.unit }}</small></dd></div></dl><FuturesCurvePanel :packet="packet" kind="equity"/></section>
      </div>
      <p v-if="locateNotice" role="status" data-testid="futures-locate-notice">{{ locateNotice }}</p>
      <p class="futures-workspace__funding">{{ fundingText }}</p>
      <details><summary>策略参考动作 · 最近50条</summary><FuturesRecordsTable :items="packet.reference.actions.slice(-50)" :columns="actionColumns" :locatable="true" :selected-key="selectedRecordKey" @locate="(row,endpoint)=>locateRecord(row,endpoint,'reference-actions')"/></details>
      <section id="futures-records" aria-label="期货双向研究记录">
        <h3>历史记录</h3><div class="futures-workspace__record-tabs"><button v-for="option in recordParts" :key="option.value" type="button" :aria-pressed="part===option.value" @click="part=option.value">{{ option.label }}</button></div>
        <p v-if="pageLoading" role="status">正在读取记录…</p><p v-else-if="pageError" role="alert">{{ pageError }} <button @click="loadPage()">重试</button></p>
        <template v-else-if="page"><p class="futures-workspace__note">共 {{ page.total }} 条 · 当前 {{ page.offset + (page.items.length ? 1 : 0) }}–{{ page.offset + page.items.length }} 条</p><FuturesRecordsTable :items="page.items" :columns="columns" :locatable="true" :selected-key="selectedRecordKey" @locate="(row,endpoint)=>locateRecord(row,endpoint,part)"/>
          <div class="futures-workspace__pagination"><button type="button" :disabled="page.offset===0" @click="loadPage(Math.max(0,page.offset-50))">上一页</button><button type="button" :disabled="page.next_offset===null" @click="page.next_offset!==null && loadPage(page.next_offset)">下一页</button></div>
        </template>
      </section>
      <details class="futures-workspace__source"><summary>来源详情</summary><FrozenFields :value="{...packet.metadata,result_sha256:packet.sha256,diagnostics:packet.diagnostics}"/><p v-if="snapshot?.reason && !knownFuturesReason(snapshot.reason)">未识别原因代码：{{ snapshot.reason }}</p></details>
    </template>
    <template v-else>
      <p role="status">{{ loading ? '正在读取历史研究结果…' : error==='RESEARCH_NOT_COVERED'?'该品种尚未纳入本轮研究':error?.startsWith('RESULT_')?'研究结果暂不可用，请查看结果说明。':error??'研究结果暂不可用' }}</p>
      <p v-if="!loading">{{ ['jm','rb','al','ta'].includes(identity.symbol) ? '没有可验证的匹配结果，策略状态未知。' : '首轮仅覆盖焦煤、螺纹钢、沪铝和PTA。' }}</p><details v-if="error"><summary>结果说明</summary>{{ error }}</details>
      <DetailPricePreview :identity="identity" :preview="pricePreview"/>
    </template>
  </section>
</template>
<style scoped>
.futures-workspace{display:grid;gap:16px}.futures-workspace__banner{padding:10px 14px;background:#fff8e7;border:1px solid #f0d592;border-radius:6px;color:#8a641e;font-size:12px}.futures-workspace__heading{display:flex;align-items:baseline;justify-content:space-between;gap:16px;flex-wrap:wrap}.futures-workspace__heading h2{font-size:18px;margin:0}.futures-workspace__heading h2 span{font-size:12px;font-weight:400;margin-left:8px;color:var(--gy-text-muted)}.futures-workspace__heading p{font-size:12px;color:var(--gy-text-muted)}.futures-workspace__state{padding:12px 16px;border:1px solid var(--gy-border);border-radius:8px}.futures-workspace__state-title{display:flex;align-items:center;gap:20px;font-size:12px;color:var(--gy-text-muted)}.futures-workspace__state-title strong{font-size:22px;color:var(--gy-text-primary)}.futures-workspace__state-title strong[data-side=LONG]{color:#d84e4e}.futures-workspace__state-title strong[data-side=SHORT]{color:#248975}.futures-workspace__metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:12px;margin:16px 0}.futures-workspace__metrics div{min-width:0}.futures-workspace__metrics dt{font-size:12px;color:var(--gy-text-muted)}.futures-workspace__metrics dd{margin:6px 0 0;font-size:19px;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}.futures-workspace__metrics small{font-size:11px;color:var(--gy-text-muted);margin-left:5px}.futures-workspace__summaries{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.futures-workspace__summaries>section{border:1px solid var(--gy-border);border-radius:8px;padding:16px;min-width:0}.futures-workspace h3{font-size:15px;margin:4px 0 12px}.futures-workspace p{margin:6px 0;line-height:1.6}.futures-workspace__note,.futures-workspace__funding{font-size:12px;color:var(--gy-text-muted)}.futures-workspace__funding{padding:8px 12px;background:var(--gy-detail-section-bg);border-radius:6px}.futures-workspace details{overflow-wrap:anywhere;font-size:12px;color:var(--gy-text-muted)}.futures-workspace summary{cursor:pointer}.futures-workspace__record-tabs{display:flex;flex-wrap:wrap;gap:6px}.futures-workspace button{cursor:pointer;padding:7px 12px;border:1px solid var(--gy-border);background:var(--gy-bg-panel);border-radius:5px;color:inherit}.futures-workspace button[aria-pressed=true]{background:#e8edf5}.futures-workspace button:disabled{opacity:.4}.futures-workspace__pagination{display:flex;gap:8px;margin-top:10px}@media(max-width:700px){.futures-workspace__summaries{grid-template-columns:1fr}.futures-workspace__state-title{flex-wrap:wrap;gap:12px}.futures-workspace__metrics{grid-template-columns:repeat(2,minmax(0,1fr))}}
</style>
