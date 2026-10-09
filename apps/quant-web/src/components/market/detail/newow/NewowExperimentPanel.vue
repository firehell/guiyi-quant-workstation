<script setup lang="ts">
import NewowVisualOverlayControls from './NewowVisualOverlayControls.vue'
import { readVisualOverlayPreferences, saveVisualOverlayPreferences, visualDonchian, visibleBuildStop } from '@/utils/newowVisualOverlays'
import {newowReferencePrice,newowReferencePercent} from '@/utils/newowPagePresentation'
import {computed,onBeforeUnmount,onMounted,ref,shallowRef,watch} from 'vue'
import {createChart,CandlestickSeries,LineSeries,createSeriesMarkers,type IChartApi,type UTCTimestamp,type ISeriesMarkersPluginApi,type Time,type IPriceLine} from 'lightweight-charts'
import {getNewowExperiment} from '@/api/newowExperiments'
import {EXPERIMENT_OPTIONS,ExperimentRequestGeneration,experimentRangeParams,type ExperimentRange,type ExperimentDetail,type ExperimentKind} from '@/utils/newowExperiments'
import {formatMarketDecimal,formatMarketPercent} from '@/utils/marketDisplay'
import {formatChartTimeInShanghai} from '@/utils/barTime'
const props=defineProps<{product:string;frequency:string;kind:ExperimentKind;asOf:string|null}>()
const data=shallowRef<ExperimentDetail|null>(null),loading=ref(false),error=ref<string|null>(null),container=ref<HTMLElement|null>(null)
const visualOverlays=ref(readVisualOverlayPreferences())
watch(visualOverlays,value=>{saveVisualOverlayPreferences(value);render()})
const range=ref<ExperimentRange>('1y')
const selectedSegment=ref<string|null>(null)
const visibleSegments=computed(()=>{const all=data.value?.segments??[];return all.filter(x=>x.segment_id===(selectedSegment.value??all.at(-1)?.segment_id))})
watch(data,()=>{selectedSegment.value=null})
const recordCount=ref(3)
watch([data,selectedSegment],()=>{recordCount.value=3})
const mode=ref<'ordinary'|'theoretical'>('ordinary')
watch(mode,()=>{recordCount.value=3})
const curveContainer=ref<HTMLElement|null>(null)
let curveChart:IChartApi|null=null
const curveSeries:ReturnType<IChartApi['addSeries']>[]=[]
function renderCurves(){if(!curveChart)return;for(const series of curveSeries)curveChart.removeSeries(series);curveSeries.length=0;for(const segment of visibleSegments.value){const model=segment[mode.value];if(!model||!Array.isArray(model.dates)||!Array.isArray(model.equity))continue;const series=curveChart.addSeries(LineSeries,{color:mode.value==='ordinary'?'#ff6b2c':'#3984ff',lineWidth:2,priceLineVisible:false});series.setData(model.dates.map((date,i)=>({time:time(String(date)),value:Number((model.equity as unknown[])[i])})));curveSeries.push(series)}curveChart.timeScale().fitContent()}
watch([data,mode,selectedSegment],renderCurves)
const option=computed(()=>EXPERIMENT_OPTIONS.find(x=>x.kind===props.kind)!)
const generation=new ExperimentRequestGeneration()
async function load(){const token=generation.begin();data.value=null;error.value=null;loading.value=true;if(!props.asOf){loading.value=false;return}try{const result=await getNewowExperiment({product:props.product,frequency:props.frequency,kind:props.kind,as_of:props.asOf,...experimentRangeParams(props.asOf,range.value)},token.signal);if(token.current())data.value=result}catch{if(token.current())error.value='实验数据暂不可用，请重试。'}finally{if(token.current())loading.value=false}}
watch(()=>[props.product,props.frequency,props.kind,props.asOf,range.value],load,{immediate:true})
let chart:IChartApi|null=null,observer:ResizeObserver|null=null
let candles:ReturnType<IChartApi['addSeries']>|null=null,upper:ReturnType<IChartApi['addSeries']>|null=null,lower:ReturnType<IChartApi['addSeries']>|null=null
let markers:ISeriesMarkersPluginApi<Time>|null=null
const time=(text:string)=>Math.floor(Date.parse(text)/1000) as UTCTimestamp
let stopLine:IPriceLine|null=null
const visualLines:ReturnType<IChartApi['addSeries']>[]=[]
function renderVisual(){
 if(!chart||!candles)return
 for(const line of visualLines)chart.removeSeries(line)
 visualLines.length=0
 if(stopLine)candles.removePriceLine(stopLine)
 stopLine=null
 const bars=data.value?.bars??[]
 if(visualOverlays.value.donchian){
  const points=visualDonchian(bars.map(b=>({time:b.bar_end,high:Number(b.high),low:Number(b.low),owner:`${b.physical_contract}:${b.segment_id}`})),visualOverlays.value.window)
  for(const [side,color] of [['upper','rgba(52,199,89,0.7)'],['lower','rgba(255,59,48,0.7)']] as const){
   const line=chart.addSeries(LineSeries,{color,lineWidth:1,lineStyle:2,priceLineVisible:false,lastValueVisible:false})
   line.setData(points.map(p=>({time:time(p.time),...(p[side]===null?{}:{value:p[side]!})})))
   visualLines.push(line)
  }
 }
 if(!visualOverlays.value.stop)return
 const range=chart.timeScale().getVisibleLogicalRange()
 const visible=bars.filter((_,i)=>!range||(i>=Math.ceil(range.from)&&i<=Math.floor(range.to)))
 const pct=props.kind==='osc-test4'?0.12:0.07
 const price=visibleBuildStop((data.value?.markers??[]).map(m=>({time:m.bar_end,owner:`${m.physical_contract}:${m.segment_id}`,price:m.reference_price,action:m.action})),visible.map(b=>({time:b.bar_end,owner:`${b.physical_contract}:${b.segment_id}`})),pct)
 if(price!==null)stopLine=candles.createPriceLine({price,color:'#3B82F6',lineStyle:2,lineWidth:1,title:`止损价（−${pct*100}%）`,axisLabelVisible:true})
}
function render(){if(!chart||!candles||!upper||!lower||!markers)return;const bars=data.value?.bars??[];candles.setData(bars.map(b=>({time:time(b.bar_end),open:Number(b.open),high:Number(b.high),low:Number(b.low),close:Number(b.close)})));upper.setData(bars.map(b=>b.channel_high===null?{time:time(b.bar_end)}:{time:time(b.bar_end),value:Number(b.channel_high)}));lower.setData(bars.map(b=>b.channel_low===null?{time:time(b.bar_end)}:{time:time(b.bar_end),value:Number(b.channel_low)}));markers.setMarkers((data.value?.markers??[]).map(m=>({time:time(m.bar_end),position:m.action==='BUILD'?'belowBar':'aboveBar',shape:m.action==='BUILD'?'arrowUp':'arrowDown',color:m.action==='BUILD'?'#ff403a':'#22b95d',text:(m.action==='BUILD'?'建仓':m.stop_loss?'止损':m.confirm_exit?'确认清仓':'清仓')+' '+formatMarketDecimal(m.reference_price)+' · '+m.score+'分'})));chart.timeScale().fitContent();renderVisual()}
watch(data,render)
onMounted(()=>{if(!container.value)return;chart=createChart(container.value,{height:440,width:container.value.clientWidth,localization:{timeFormatter:formatChartTimeInShanghai},timeScale:{timeVisible:true},grid:{vertLines:{color:'#f1f3f5'},horzLines:{color:'#f1f3f5'}}});candles=chart.addSeries(CandlestickSeries,{upColor:'#ff403a',downColor:'#22b95d',wickUpColor:'#ff403a',wickDownColor:'#22b95d',borderVisible:false});upper=chart.addSeries(LineSeries,{color:'#f7bb23',lineWidth:2,priceLineVisible:false});lower=chart.addSeries(LineSeries,{color:'#3984ff',lineWidth:2,priceLineVisible:false});markers=createSeriesMarkers(candles);chart.timeScale().subscribeVisibleLogicalRangeChange(renderVisual);observer=new ResizeObserver(()=>{if(container.value)chart?.applyOptions({width:container.value.clientWidth});if(curveContainer.value)curveChart?.applyOptions({width:curveContainer.value.clientWidth})});observer.observe(container.value);if(curveContainer.value){curveChart=createChart(curveContainer.value,{height:180,width:curveContainer.value.clientWidth,localization:{timeFormatter:formatChartTimeInShanghai}});observer.observe(curveContainer.value)}render();renderCurves()})
onBeforeUnmount(()=>{generation.clear();observer?.disconnect();chart?.remove();curveChart?.remove()})
const pct=(v:unknown,signed=true)=>typeof v==='string'?formatMarketPercent(v,'percentage_points',signed):'—'
const date=(v:unknown)=>typeof v==='string'?formatChartTimeInShanghai(time(v)):'—'
const summary=(model:Record<string,unknown>|null)=>model?.summary as Record<string,unknown>|undefined
const allRecords=(model:Record<string,unknown>|null)=>Array.isArray(model?.trades)?model.trades as Record<string,unknown>[]:[]
</script>
<template><section class="experiment-panel" aria-label="震荡实验策略">
<header><strong>{{option.label}} · 震荡实验</strong><span>{{option.description}}</span><slot name="frequency" /></header>
<p v-if="loading" role="status">正在读取实验策略…</p><p v-else-if="error" role="alert">{{error}} <button @click="load">重试</button></p><p v-else-if="!asOf" role="status">等待当前周期行情快照…</p><p v-else-if="(visibleSegments[0]?.readiness??data?.readiness)?.status==='DATA_INSUFFICIENT'" role="status">当前合约段数据不足，暂时没有实验结果。</p><p v-else-if="(visibleSegments[0]?.readiness??data?.readiness)?.status==='WARMUP'" role="status">当前合约段正在预热。</p>
<NewowVisualOverlayControls v-model="visualOverlays" /><div ref="container" class="experiment-chart" /><p>黄线：HHV10 · 蓝线：LLV10 · 红箭头：建仓 · 绿箭头：清仓 / 止损</p>
<div class="experiment-mode"><button v-for="r in [{id:'3m',label:'近3月'},{id:'1y',label:'近1年'},{id:'3y',label:'近3年'},{id:'year',label:'今年'},{id:'all',label:'全部'}]" :key="r.id" :aria-pressed="range===r.id" @click="range=r.id as ExperimentRange">{{r.label}}</button></div><p v-if="data?.window">统计窗口 {{data.window.since}} 至 {{data.window.through}} · 主图最多显示最近2000根</p><div class="experiment-mode"><button :aria-pressed="mode==='ordinary'" @click="mode='ordinary'">普通收益</button><button :aria-pressed="mode==='theoretical'" @click="mode='theoretical'">理论收益</button><span>{{mode==='ordinary'?'末根收盘强制平仓计入统计':'基础震荡的回看理想模型，与四测试独立'}}</span></div><div ref="curveContainer" class="experiment-curve" />
<template v-if="data"><label>合约计算段 <select v-model="selectedSegment"><option :value="null">当前计算段 · {{data.segments.at(-1)?.physical_contract}}</option><option v-for="s in data.segments.slice(0,-1)" :key="s.segment_id" :value="s.segment_id">{{s.physical_contract}} · {{date(s.statistics_window?.through)}}</option></select></label><p>截至 {{formatChartTimeInShanghai(Math.floor(Date.parse(data.as_of)/1000) as UTCTimestamp)}} · 页面参考，零手续费与滑点</p>
<section v-for="segment in visibleSegments" :key="segment.segment_id" class="experiment-segment"><h4>{{segment.physical_contract}} <small v-if="segment.status==='ROLLOVER_INTERRUPTED'">换月中断</small><small v-else-if="segment.status==='DATA_CONFLICT'">数据中断</small></h4>
<p v-if="segment.latest_state && segment.readiness?.status==='READY'">{{segment.latest_state.holding?'持有':'空仓'}} · 建仓参考价 {{formatMarketDecimal(segment.latest_state.entry_reference_price)}} · {{kind==='osc-test4'?'12%':'7%'}}止损 {{formatMarketDecimal(segment.latest_state.stop_reference_price)}}<template v-if="kind==='osc-test2'"> · 锁定目标 {{formatMarketDecimal(segment.latest_state.locked_target)}}</template><template v-if="kind==='osc-test4'"> · 确认参考价 {{formatMarketDecimal(segment.latest_state.confirm_reference)}}</template></p><p v-if="segment.readiness?.status!=='READY'" role="status">该合约计算段不足11根，实验概览尚在预热。</p><div class="experiment-models"><article v-for="model in [segment[mode]]" :key="mode"><h5>{{mode==='ordinary'?'普通':'理论'}}参考收益</h5><p v-if="model===null" role="status">该合约段不足11根，参考收益暂不可用。</p><p>累计 {{pct(summary(model)?.cum_return_percentage_points)}} · 完成 {{summary(model)?.trade_count??'—'}} 笔</p><p>准确率 {{pct(summary(model)?.accuracy_pct,false)}} · {{mode==='ordinary'?'最大回撤':'单笔最大亏损'}} {{pct(summary(model)?.max_drawdown_percentage_points,false)}}</p><div class="experiment-table"><table><thead><tr><th>建仓时间</th><th>建仓参考价</th><th>清仓时间</th><th>清仓参考价</th><th>收益</th><th>说明</th></tr></thead><tbody><tr v-for="(trade,i) in allRecords(model).slice().reverse().slice(0,recordCount)" :key="i"><td>{{date(trade.entry_bar_end)}}</td><td>{{newowReferencePrice(trade.entry_reference_price as string)}}</td><td>{{date(trade.exit_bar_end)}}</td><td>{{newowReferencePrice(trade.exit_reference_price as string)}}</td><td>{{newowReferencePercent(trade.return_percentage_points as string)}}</td><td>{{trade.stop_loss?'止损':trade.confirm_exit?'确认清仓':trade.force_close?'末根强制平仓':'区间清仓'}}</td></tr></tbody></table></div><button v-if="recordCount<allRecords(model).length" @click="recordCount=allRecords(model).length">查看全部 {{allRecords(model).length}} 笔</button><button v-else-if="recordCount>3 && allRecords(model).length>3" @click="recordCount=3">收起</button></article></div></section>
<details><summary>公式与参考价</summary><p>{{option.description}}。跳空止损参考价取止损价与开盘价较低者；测试2目标参考价取锁定目标与开盘价较高者。普通统计和理论统计按各自模型展示，分合约计算。</p><p>{{data.formula_version}}</p></details></template>
</section></template>
<style scoped>.experiment-panel{min-width:0;background:#fff;padding:10px;border-radius:8px}.experiment-panel header{display:flex;gap:12px;flex-wrap:wrap;align-items:center}.experiment-panel p{font-size:12px;color:#667085}.experiment-chart{height:440px;min-width:0}.experiment-models{display:grid;grid-template-columns:minmax(0,1fr);gap:16px}.experiment-curve{height:180px}.experiment-mode{display:flex;gap:8px;align-items:center;flex-wrap:wrap;font-size:12px}.experiment-mode button{border:1px solid #ddd;background:#fff;border-radius:5px;padding:6px}.experiment-mode button[aria-pressed="true"]{color:#ff6b2c;border-color:#ff6b2c}.experiment-table{overflow:auto}table{width:100%;font-size:12px;border-collapse:collapse}td,th{padding:7px;text-align:left;border-bottom:1px solid #edf0f3;white-space:nowrap}h4,h5{margin:8px 0}small{color:#b45309}@media(max-width:700px){.experiment-models{grid-template-columns:1fr}}</style>
