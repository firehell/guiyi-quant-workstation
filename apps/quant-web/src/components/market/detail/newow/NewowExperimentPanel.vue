<script setup lang="ts">
import NewowVisualOverlayControls from './NewowVisualOverlayControls.vue'
import { readVisualOverlayPreferences, saveVisualOverlayPreferences, visualDonchian, retainBuildStop, retainedStopPrice, type RetainedBuildStop } from '@/utils/newowVisualOverlays'
import {newowReferencePrice,newowReferencePercent} from '@/utils/newowPagePresentation'
import {computed,onBeforeUnmount,onMounted,ref,shallowRef,watch} from 'vue'
import {createChart,CandlestickSeries,LineSeries,createSeriesMarkers,type IChartApi,type UTCTimestamp,type ISeriesMarkersPluginApi,type Time,type IPriceLine} from 'lightweight-charts'
import {getNewowExperiment} from '@/api/newowExperiments'
import {EXPERIMENT_OPTIONS,ExperimentRequestGeneration,experimentRangeParams,experimentVisibleSegments,experimentMarkerLabel,type ExperimentRange,type ExperimentDetail,type ExperimentKind} from '@/utils/newowExperiments'
import {formatMarketPercent} from '@/utils/marketDisplay'
import {pagePerformanceAnnualized} from '@/utils/newowPagePerformance'
import {layoutNiuwaReferenceCallouts,type PositionedCallout} from '@/utils/referenceCalloutLayout'
import {formatChartTimeInShanghai} from '@/utils/barTime'
const emit=defineEmits<{ 'analyze-channel': []; context: [value: {asOf:string;physicalContract:string|null;segmentId:string|null;latestState:import('@/utils/newowExperiments').ExperimentSegment['latest_state']|null}|null] }>()
const props=defineProps<{product:string;frequency:string;kind:ExperimentKind;asOf:string|null}>()
let retainedStop:RetainedBuildStop|null=null
const data=shallowRef<ExperimentDetail|null>(null),loading=ref(false),error=ref<string|null>(null),container=ref<HTMLElement|null>(null)
const visualOverlays=ref(readVisualOverlayPreferences())
watch(visualOverlays,value=>{saveVisualOverlayPreferences(value);render()})
const range=ref<ExperimentRange>('1y')
const selectedSegment=ref<string|null>(null)
const visibleSegments=computed(()=>experimentVisibleSegments(data.value,selectedSegment.value))
const chartBars=computed(()=>{const segment=visibleSegments.value[0];return data.value?.segments.length&&!segment?[]:(data.value?.bars??[]).filter(b=>!segment||b.segment_id===segment.segment_id)})
const chartMarkers=computed(()=>{const segment=visibleSegments.value[0];return data.value?.segments.length&&!segment?[]:(data.value?.markers??[]).filter(m=>!segment||m.segment_id===segment.segment_id)})
watch([data,selectedSegment],()=>{const segment=visibleSegments.value[0];emit('context',data.value?{asOf:data.value.as_of,physicalContract:segment?.physical_contract??null,segmentId:segment?.segment_id??null,latestState:segment?.latest_state??null}:null)})
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
async function load(){const token=generation.begin();data.value=null;selectedSegment.value=null;retainedStop=null;error.value=null;loading.value=true;if(!props.asOf){loading.value=false;return}try{const result=await getNewowExperiment({product:props.product,frequency:props.frequency,kind:props.kind,as_of:props.asOf,...experimentRangeParams(props.asOf,range.value)},token.signal);if(token.current())data.value=result}catch{if(token.current())error.value='实验数据暂不可用，请重试。'}finally{if(token.current())loading.value=false}}
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
 const bars=chartBars.value
 if(visualOverlays.value.donchian){
  const points=visualDonchian(bars.map(b=>({time:b.bar_end,high:Number(b.high),low:Number(b.low),owner:`${b.physical_contract}:${b.segment_id}`})),visualOverlays.value.window)
  for(const [side,color] of [['upper','rgba(52,199,89,0.7)'],['lower','rgba(255,59,48,0.7)']] as const){
   const line=chart.addSeries(LineSeries,{color,lineWidth:1,lineStyle:2,priceLineVisible:false,lastValueVisible:false})
   line.setData(points.map(p=>({time:time(p.time),...(p[side]===null?{}:{value:p[side]!})})))
   visualLines.push(line)
  }
 }
 const range=chart.timeScale().getVisibleLogicalRange()
 const visible=bars.filter((_,i)=>!range||(i>=Math.ceil(range.from)&&i<=Math.floor(range.to)))
 const pct=props.kind==='osc-test4'?0.12:0.07
 retainedStop=retainBuildStop(retainedStop, `${props.product}:${props.frequency}:${props.kind}`, chartMarkers.value.map(m=>({time:m.bar_end,owner:`${m.physical_contract}:${m.segment_id}`,price:m.reference_price,action:m.action})),visible.map(b=>({time:b.bar_end,owner:`${b.physical_contract}:${b.segment_id}`})))
 const price=retainedStopPrice(retainedStop,pct)
 if(visualOverlays.value.stop&&price!==null)stopLine=candles.createPriceLine({price,color:'#3B82F6',lineStyle:2,lineWidth:1,title:`止损价（−${pct*100}%）`,axisLabelVisible:true})
}
const callouts=shallowRef<PositionedCallout[]>([])
function projectCallouts(){
 if(!chart||!candles||!container.value)return
 const scale=chart.timeScale(),width=scale.width?.()??container.value.clientWidth,height=414
 callouts.value=layoutNiuwaReferenceCallouts(chartMarkers.value.flatMap(m=>{
  const x=scale.timeToCoordinate?.(time(m.bar_end)),y=candles?.priceToCoordinate?.(Number(m.reference_price))
  if(x===null||x===undefined||y===null||y===undefined)return []
  const bar=chartBars.value.find(b=>b.bar_end===m.bar_end)
  const high=bar?candles?.priceToCoordinate?.(Number(bar.high)):null,low=bar?candles?.priceToCoordinate?.(Number(bar.low)):null
  return [{callout:{id:m.marker_id,time:m.bar_end,physicalContract:m.physical_contract,price:m.reference_price,title:experimentMarkerLabel(m),detail:'',tone:'neutral' as const,above:m.action==='CLEAR'},x,y,boxWidth:100,boxHeight:28,...(high!=null&&low!=null?{candle:{left:x-8,top:Math.min(high,low)-3,width:16,height:Math.abs(high-low)+6}}:{})}]
 }),width,height)
}
function render(){
 if(!chart||!candles||!upper||!lower||!markers)return
 const bars=chartBars.value
 candles.setData(bars.map(b=>({time:time(b.bar_end),open:Number(b.open),high:Number(b.high),low:Number(b.low),close:Number(b.close)})))
 upper.setData(bars.map(b=>b.channel_high===null?{time:time(b.bar_end)}:{time:time(b.bar_end),value:Number(b.channel_high)}))
 lower.setData(bars.map(b=>b.channel_low===null?{time:time(b.bar_end)}:{time:time(b.bar_end),value:Number(b.channel_low)}))
 markers.setMarkers([])
 chart.timeScale().fitContent();renderVisual();projectCallouts()
}
watch([data,selectedSegment],render)
onMounted(()=>{if(!container.value)return;chart=createChart(container.value,{height:440,width:container.value.clientWidth,localization:{timeFormatter:formatChartTimeInShanghai,priceFormatter:(value:number)=>newowReferencePrice(String(value))},timeScale:{timeVisible:true},grid:{vertLines:{color:'#f1f3f5'},horzLines:{color:'#f1f3f5'}}});candles=chart.addSeries(CandlestickSeries,{upColor:'#ff403a',downColor:'#22b95d',wickUpColor:'#ff403a',wickDownColor:'#22b95d',borderVisible:false});upper=chart.addSeries(LineSeries,{color:'#f7bb23',lineWidth:2,priceLineVisible:false});lower=chart.addSeries(LineSeries,{color:'#3984ff',lineWidth:2,priceLineVisible:false});markers=createSeriesMarkers(candles);chart.timeScale().subscribeVisibleLogicalRangeChange(()=>{renderVisual();projectCallouts()});observer=new ResizeObserver(()=>{if(container.value){chart?.applyOptions({width:container.value.clientWidth});projectCallouts()};if(curveContainer.value)curveChart?.applyOptions({width:curveContainer.value.clientWidth})});observer.observe(container.value);if(curveContainer.value){curveChart=createChart(curveContainer.value,{height:180,width:curveContainer.value.clientWidth,localization:{timeFormatter:formatChartTimeInShanghai}});observer.observe(curveContainer.value)}render();renderCurves()})
onBeforeUnmount(()=>{generation.clear();emit('context',null);observer?.disconnect();chart?.remove();curveChart?.remove()})
const pct=(v:unknown,signed=true)=>typeof v==='string'?formatMarketPercent(v,'percentage_points',signed):'—'
const date=(v:unknown)=>typeof v==='string'?formatChartTimeInShanghai(time(v)):'—'
const annualized=(model:Record<string,unknown>|null)=>pagePerformanceAnnualized(model&&Array.isArray(model.dates)&&Array.isArray(model.equity)?{dates:model.dates as string[],equity:model.equity as string[]}:null)
const annualizedText=(model:Record<string,unknown>|null)=>{const value=annualized(model);return value===null?'--':newowReferencePercent(String(value))}
const summary=(model:Record<string,unknown>|null)=>model?.summary as Record<string,unknown>|undefined
const allRecords=(model:Record<string,unknown>|null)=>Array.isArray(model?.trades)?model.trades as Record<string,unknown>[]:[]
</script>
<template>
<section class="experiment-panel newow-reference" aria-label="震荡实验策略">
<header class="experiment-heading"><strong>{{option.label}}</strong><slot name="frequency" /></header>
<p v-if="loading" role="status">正在读取实验策略…</p><p v-else-if="error" role="alert">{{error}} <button @click="load">重试</button></p><p v-else-if="!asOf" role="status">等待当前周期行情快照…</p><p v-else-if="(visibleSegments[0]?.readiness??data?.readiness)?.status==='DATA_INSUFFICIENT'" role="status">当前合约段数据不足，暂时没有实验结果。</p><p v-else-if="(visibleSegments[0]?.readiness??data?.readiness)?.status==='WARMUP'" role="status">当前合约段正在预热。</p>
<slot name="overview" />
<div class="experiment-chart-controls"><slot name="chart-controls" /><NewowVisualOverlayControls v-model="visualOverlays" @analyze="emit('analyze-channel')" /></div>
<div class="experiment-chart-wrap"><div ref="container" class="experiment-chart" />
<div class="experiment-callouts" aria-label="实验策略参考动作"><svg aria-hidden="true"><polyline v-for="item in callouts" :key="item.callout.id" :points="`${item.x},${item.y} ${item.x},${(item.y+item.lineY)/2} ${item.lineX},${(item.y+item.lineY)/2} ${item.lineX},${item.lineY}`" fill="none" /></svg>
<div v-for="item in callouts" :key="item.callout.id" class="experiment-callout" :class="{'is-compact':item.compact}" :style="{left:`${item.left}px`,top:`${item.top}px`,width:`${item.width}px`,height:`${item.height}px`}" :data-action-id="item.callout.id" :data-reference-price="item.callout.price" :title="`${item.callout.title} ${newowReferencePrice(item.callout.price)} · ${item.callout.time} · ${item.callout.physicalContract}`"><template v-if="!item.compact"><strong>{{item.callout.title}}</strong><span>{{newowReferencePrice(item.callout.price)}}</span></template><template v-else>{{item.callout.above?'▽':'△'}}</template></div></div></div>
<slot name="chart-auxiliary" />
<header class="newow-reference__returns-heading"><strong>策略收益率走势</strong><span class="newow-reference__annualized" title="当前模式及合约段的页面曲线自然日年化">年化 {{annualizedText(visibleSegments[0]?.[mode] ?? null)}}</span></header>
<div class="newow-reference__presets experiment-mode" aria-label="页面统计快捷窗口"><button v-for="r in [{id:'3m',label:'近3月'},{id:'1y',label:'近1年'},{id:'3y',label:'近3年'},{id:'year',label:'今年'}]" :key="r.id" type="button" :aria-pressed="range===r.id" @click="range=r.id as ExperimentRange">{{r.label}}</button><button type="button" class="newow-reference__ideal" :aria-pressed="mode==='theoretical'" @click="mode=mode==='ordinary'?'theoretical':'ordinary'">理论值</button><button type="button" :aria-pressed="range==='all'" @click="range='all'">全部</button></div>
<template v-if="data"><label class="experiment-contract">合约计算段 <select v-model="selectedSegment"><option :value="null">当前计算段 · {{data.segments.at(-1)?.physical_contract}}</option><option v-for="s in data.segments.slice(0,-1)" :key="s.segment_id" :value="s.segment_id">{{s.physical_contract}} · {{date(s.statistics_window?.through)}}</option></select></label></template>
<div ref="curveContainer" class="experiment-curve" />
<template v-if="data"><section v-for="segment in visibleSegments" :key="segment.segment_id" class="experiment-segment"><p class="experiment-segment-status">{{segment.physical_contract}}<span v-if="segment.status==='ROLLOVER_INTERRUPTED'"> · 换月中断</span><span v-else-if="segment.status==='DATA_CONFLICT'"> · 数据中断</span></p>
<template v-for="model in [segment[mode]]" :key="mode"><p v-if="model===null" role="status">该合约段不足11根，参考收益暂不可用。</p>
<section class="newow-reference__summary"><dl class="newow-reference__metrics" data-testid="experiment-summary"><div><dt>累计收益</dt><dd :data-direction="Number(summary(model)?.cum_return_percentage_points)>=0?'up':'down'">{{pct(summary(model)?.cum_return_percentage_points)}}</dd></div><div><dt>胜率</dt><dd>{{pct(summary(model)?.accuracy_pct,false)}}</dd></div><div><dt>年化收益 <span title="按当前曲线首末净值比及上海日历跨度折算365日复合年化；页面参考，不代表可执行收益。">ⓘ</span></dt><dd>{{annualizedText(model)}}</dd></div><div><dt>{{mode==='ordinary'?'最大回撤':'单笔最大亏损'}}</dt><dd class="newow-reference__drawdown">{{pct(summary(model)?.max_drawdown_percentage_points,false)}}</dd></div></dl></section>
<header class="experiment-records-heading"><strong>回测操盘提醒</strong><span>历史页面参考，仅供参考，不作为实时买卖提示</span></header>
<p v-if="!allRecords(model).length">当前口径暂无页面估值交易。</p>
<article v-for="(trade,i) in allRecords(model).slice().reverse().slice(0,recordCount)" :key="`${segment.segment_id}:${trade.entry_bar_end}:${trade.exit_bar_end}:${i}`" class="newow-reference__card" :data-page-force-close="trade.force_close"><header><strong class="experiment-badge">{{trade.force_close?'持仓参考中':frequency}}</strong><strong :data-direction="Number(trade.return_percentage_points)>=0?'up':'down'">{{trade.force_close?'参考浮动':'盈亏'}} {{newowReferencePercent(trade.return_percentage_points as string)}}</strong></header><p class="experiment-record-line"><span><b class="experiment-buy">建仓</b> 买入 <strong>{{newowReferencePrice(trade.entry_reference_price as string)}}</strong></span><time :datetime="trade.entry_bar_end as string">{{date(trade.entry_bar_end)}}</time></p><p class="experiment-record-line"><span><b class="experiment-sell">{{trade.force_close?'参考估值':trade.stop_loss?'止损清仓':trade.confirm_exit?'确认清仓':'清仓'}}</b> {{trade.force_close?'':'卖出'}} <strong>{{newowReferencePrice(trade.exit_reference_price as string)}}</strong></span><time :datetime="trade.exit_bar_end as string">{{date(trade.exit_bar_end)}}</time></p></article>
<p class="experiment-record-count">共 {{allRecords(model).length}} 笔页面参考记录，{{recordCount===3?'仅展示最近3笔':'已展开全部'}}</p><button v-if="recordCount<allRecords(model).length" class="experiment-show-all" type="button" @click="recordCount=allRecords(model).length">查看全部 {{allRecords(model).length}} 笔页面记录</button><button v-else-if="recordCount>3 && allRecords(model).length>3" class="experiment-show-all" type="button" @click="recordCount=3">收起</button>
</template></section>
<slot name="path" />
<details class="experiment-basis"><summary>详情与口径</summary><p>{{option.description}}。跳空止损参考价取止损价与开盘价较低者；测试2目标参考价取锁定目标与开盘价较高者。普通统计保留末根收盘强制平仓；理论统计为基础震荡回看理想模型，与四测试独立，按合约计算。</p><p>页面参考 · 零手续费与滑点。黄线 HHV10、蓝线 LLV10；不代表可执行收益。</p><p v-if="data.window">统计窗口 {{data.window.since}} 至 {{data.window.through}} · 主图最多显示最近2000根</p><p>截至 {{date(data.as_of)}} · {{data.formula_version}}</p><p v-for="segment in visibleSegments" :key="segment.segment_id">{{segment.latest_state?.holding?'持有':'空仓'}} · 建仓参考价 {{newowReferencePrice(segment.latest_state?.entry_reference_price)}} · {{kind==='osc-test4'?'12%':'7%'}}止损 {{newowReferencePrice(segment.latest_state?.stop_reference_price)}}<template v-if="kind==='osc-test2'"> · 锁定目标 {{newowReferencePrice(segment.latest_state?.locked_target)}}</template><template v-if="kind==='osc-test4'"> · 确认参考价 {{newowReferencePrice(segment.latest_state?.confirm_reference)}}</template></p></details>
</template>
</section>
</template>
<style scoped src="./newowReferencePanel.css"></style>
<style scoped>
.experiment-panel{min-width:0;background:#fff;padding:10px;border-radius:8px;gap:8px}.experiment-heading,.experiment-chart-controls{display:flex;gap:12px;flex-wrap:wrap;align-items:center;justify-content:space-between}.experiment-panel p,.experiment-contract,.experiment-basis{font-size:12px;color:#667085}.experiment-chart-wrap{position:relative;min-width:0}.experiment-chart{height:440px;min-width:0}.experiment-curve{height:180px}.experiment-mode{justify-content:center}.experiment-mode button[aria-pressed="true"]{color:#ff6b2c;border-color:#ff6b2c}.experiment-contract{align-self:flex-end}.experiment-segment-status{margin:4px 0}.experiment-callouts{position:absolute;inset:0;pointer-events:none;z-index:4;overflow:hidden}.experiment-callouts svg{position:absolute;inset:0;width:100%;height:100%;stroke:#9B8169;stroke-width:1}.experiment-callout{position:absolute;display:grid;place-content:center;box-sizing:border-box;overflow:hidden;border:1.5px solid #AD5734;border-radius:8px;background:#FFFEFA;color:#665044;font-size:11px;line-height:13px;text-align:center;padding:1px 4px}.experiment-callout strong,.experiment-callout span{white-space:nowrap}.experiment-callout.is-compact{padding:0}.experiment-records-heading{display:flex;justify-content:space-between;align-items:center;gap:12px;font-size:13px;margin:14px 0 8px}.experiment-records-heading span,.experiment-record-line time{font-size:11px;color:#999}.newow-reference__card{margin:8px 0}.newow-reference__card header,.experiment-record-line{display:flex;justify-content:space-between;align-items:center;gap:8px}.experiment-record-line{margin:6px 0}.experiment-buy,[data-direction="up"]{color:#ff403a}.experiment-sell,[data-direction="down"]{color:#34c759}.experiment-badge{background:#ff9500;border-radius:3px;padding:3px 7px;color:white;font-size:11px}.experiment-record-count{text-align:center}.experiment-show-all{display:block;margin:8px auto;padding:7px 22px;border:1px solid #e5e5ea;background:white;border-radius:20px;font-size:12px}.experiment-basis summary{cursor:pointer}@media(max-width:600px){.experiment-mode{gap:5px}.experiment-records-heading span{max-width:50%;text-align:right}.experiment-record-line time{max-width:44%;text-align:right}}
</style>
