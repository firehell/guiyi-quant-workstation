<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { createChart, CandlestickSeries, LineSeries, ColorType, CrosshairMode, LineStyle, type IChartApi, type UTCTimestamp } from 'lightweight-charts'
import { formatChartAxisTimeInShanghai, formatChartTimeInShanghai } from '@/utils/barTime'
const props=defineProps<{rows:Record<string,any>[];stop:string|null;target:string|null}>()
const host=ref<HTMLElement|null>(null)
let chart:IChartApi|undefined
let candles:any,close:any,upper:any,lower:any,ema:any
let lines:any[]=[]
const stamp=(at:string)=>Math.floor(Date.parse(at)/1000) as UTCTimestamp
function render(){
 if(!chart)return
 const rows=props.rows;const hasOHLC=rows.length>0&&rows.every(r=>['open','high','low'].every(k=>r[k]!=null))
 candles.setData(hasOHLC?rows.map(r=>({time:stamp(r.at),open:Number(r.open),high:Number(r.high),low:Number(r.low),close:Number(r.close)})):[])
 close.setData(hasOHLC?[]:rows.map(r=>({time:stamp(r.at),value:Number(r.close)})))
 for(const [series,key] of [[upper,'upper'],[lower,'lower'],[ema,'ema21']] as const)series.setData(rows.map(r=>r[key]==null?{time:stamp(r.at)}:{time:stamp(r.at),value:Number(r[key])}))
 for(const line of lines) candles.removePriceLine(line);lines=[]
 for(const [value,title,color] of [[props.stop,'初始保护','#ff6b2c'],[props.target,'1R目标','#8b95a5']] as const){if(value!=null&&Number.isFinite(Number(value)))lines.push(candles.createPriceLine({price:Number(value),title,color,lineStyle:LineStyle.Dashed,lineWidth:1,axisLabelVisible:true}))}
 if(rows.length)chart.timeScale().fitContent()
}
onMounted(()=>{if(!host.value)return;chart=createChart(host.value,{autoSize:true,height:390,layout:{background:{type:ColorType.Solid,color:'#ffffff'},textColor:'#667085',fontFamily:'Arial, sans-serif',fontSize:12},grid:{vertLines:{color:'#f1f2f5'},horzLines:{color:'#f1f2f5'}},crosshair:{mode:CrosshairMode.Normal},rightPriceScale:{borderColor:'#ebedf0',scaleMargins:{top:.08,bottom:.08}},timeScale:{borderColor:'#ebedf0',timeVisible:true,tickMarkFormatter:formatChartAxisTimeInShanghai},localization:{timeFormatter:formatChartTimeInShanghai}})
 candles=chart.addSeries(CandlestickSeries,{upColor:'#ff403a',downColor:'#22b95d',borderUpColor:'#ff403a',borderDownColor:'#22b95d',wickUpColor:'#ff403a',wickDownColor:'#22b95d',priceFormat:{type:'price',precision:2,minMove:.01}})
 close=chart.addSeries(LineSeries,{color:'#ff6b2c',lineWidth:2,priceLineVisible:false,lastValueVisible:false})
 upper=chart.addSeries(LineSeries,{color:'#5d86c4',lineStyle:LineStyle.Dashed,lineWidth:1,priceLineVisible:false,lastValueVisible:false})
 lower=chart.addSeries(LineSeries,{color:'#5d86c4',lineStyle:LineStyle.Dashed,lineWidth:1,priceLineVisible:false,lastValueVisible:false})
 ema=chart.addSeries(LineSeries,{color:'#bd8ad0',lineWidth:1,priceLineVisible:false,lastValueVisible:false})
 render()})
watch(()=>[props.rows,props.stop,props.target],render)
onBeforeUnmount(()=>{chart?.remove()})
</script>
<template><div ref="host" class="replay-chart" role="img" aria-label="30分钟K线、近期结构和保护位置"/><p v-if="rows.length&&!rows[0].open" class="chart-note">当前历史包仅提供收盘线；未补造开高低价。</p></template>
<style scoped>.replay-chart{height:390px;min-width:0}.chart-note{font-size:12px;color:#667085;padding:0 16px}</style>
