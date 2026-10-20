<script setup lang="ts">
import { computed, ref, watch, useId, onMounted, onBeforeUnmount } from 'vue'
import type { NewowDecisionV2 } from '@/types/newowDecisionV2'
import { newowReferencePrice } from '@/utils/newowPagePresentation'
import { historicalPathGeometry } from '@/utils/newowDailyWeeklyPath'
const props=defineProps<{decision:NewowDecisionV2|null;loading:boolean;error:string}>()
const expanded=ref(false),host=ref<HTMLElement|null>(null),width=ref(480),id=useId()
const data=computed(()=>props.decision?.daily_weekly_path?.history)
const graph=computed(()=>data.value?.status==='ready'?historicalPathGeometry(data.value,width.value):null)
let observer:ResizeObserver|null=null, resizeTimer:ReturnType<typeof setTimeout>|undefined
function measure() { width.value=Math.max(480,Math.min(1200,(host.value?.clientWidth??504)-24)) }
onMounted(()=>{measure();if(typeof ResizeObserver==='undefined')return;observer=new ResizeObserver(()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(measure,200)});if(host.value)observer.observe(host.value)})
onBeforeUnmount(()=>{observer?.disconnect();clearTimeout(resizeTimer)})
const reasons:Record<string,string>={TRADE_SAMPLES_MISSING:'至少需要两个建仓点和一个真实清仓点',CURRENT_CONTEXT_UNAVAILABLE:'当前合约段或价格未就绪',CALENDAR_MISSING:'同合约交易日序列缺失',SAMPLES_MISSING:'历史区间样本不足两笔',PRICE_OR_START_MISSING:'起点或目标价格缺失'}
const eta=computed(()=>data.value?.eta)
const periods=computed(()=>props.decision?.daily_weekly_path?.periods??[])
const selected=ref<{date:string;price:string;kind:string}|null>(null)
watch(data,()=>{selected.value=null})
const price=newowReferencePrice
const periodName=(frequency:string)=>({'1w':'周线','1d':'日线','60m':'60分'} as Record<string,string>)[frequency]??frequency

</script>
<template>
  <section ref="host" class="period-path" aria-label="历史波段路径：页面参考，不可执行">
    <button class="period-path__toggle" :aria-expanded="expanded" :aria-controls="id" @click="expanded=!expanded"><strong>多周期嵌套波段路径</strong><span>{{expanded?'收起 ⌃':'展开 ⌄'}}</span></button>
    <div v-show="expanded" :id="id" class="period-path__body">
      <p v-if="loading" role="status">读取同一截止的历史路径…</p>
      <p v-else-if="error" role="alert">路径读取失败，请刷新。</p>
      <p v-else-if="!data || !graph" role="status">{{reasons[data?.reason??'']??'历史路径数据不足'}}</p>
      <template v-else>
        <p class="period-path__summary"><span>现价 <b>{{price(data.current)}}</b></span><span v-for="period in periods" :key="period.frequency">{{periodName(period.frequency)}} 成本 <b>{{price(period.cost?.raw??null)}}</b> → 目标 <b>{{price(period.target?.raw??null)}}</b></span></p>
        <div class="period-path__estimate" role="status"><template v-if="eta?.status==='ready'"><p><strong>{{eta.overdue?'已到预测期':'历史周期预估'}}</strong> 预计{{data.holding?'清仓':'建仓'}} <b class="sell">{{price(eta.to_price??(data.holding?data.target:data.cost))}}</b> · {{eta.overdue?'已超出平均周期，随时可能触发':`约 ${eta.remain?.toFixed(1)} ${eta.unit}后（${eta.date}前后）`}}</p><p class="period-path__estimate-detail">历史 {{eta.samples}} 笔 · 平均 {{eta.base?.toFixed(1)}} {{eta.unit}} × 剩余幅度 {{((eta.ratio??0)*100).toFixed(0)}}% · 本段已用 {{eta.elapsed?.toFixed(1)}} {{eta.unit}}。历史统计，仅供参考。</p></template><p v-else>时间估算不可用：{{reasons[eta?.reason??'']??'样本或交易日序列不足'}}</p></div>
        <p class="period-path__chart-caption">建仓价／清仓价 · 日K（{{data.buys.length+data.sells.length}} 个历史点）</p>
        <div class="canvas"><svg :viewBox="`0 0 ${width} 320`" role="img" aria-label="历史买卖双线与参考路径">
          <defs><linearGradient :id="id+'fill'" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2e9e8f" stop-opacity=".2"/><stop offset="1" stop-color="#1f5fa9" stop-opacity=".05"/></linearGradient></defs>
          <rect v-for="(b,i) in graph.background" :key="'bg'+i" :x="b.x" y="32" :width="b.width" height="240" :fill="b.state==='hold'?'#ff950e':'#8e8e93'" opacity=".08"/>
          <g v-for="(tick,i) in graph.yTicks" :key="'y'+i"><line x1="44" :x2="width-40" :y1="tick.y" :y2="tick.y" stroke="#eeeef1"/><text x="38" :y="tick.y+4" text-anchor="end">{{tick.label}}</text></g>
          <polygon :points="graph.envelope" :fill="`url(#${id}fill)`"/>
          <line v-for="(s,i) in graph.segments" :key="'segment'+i" :x1="s.x1" :y1="s.y1" :x2="s.x2" :y2="s.y2" :stroke="s.color" :stroke-width="s.holding?1.8:1.2" :stroke-dasharray="s.holding?undefined:'2 3'" :opacity="s.holding?1:.45"/><text v-for="(l,i) in graph.labels" :key="'label'+i" :x="l.x" :y="l.y" :style="{fill:l.color}" font-weight="600">{{l.text}}</text>
          <g v-for="(p,i) in graph.buy" :key="'buy'+i"><circle :cx="p.x" :cy="p.y" r="3.5" class="buy-point" tabindex="0" role="button" :aria-label="`${p.date} 建仓参考 ${price(p.price)}`" @click="selected={...p,kind:'建仓参考'}" @keydown.enter="selected={...p,kind:'建仓参考'}"/><title>{{p.date}} 建仓 {{price(p.price)}}</title></g>
          <g v-for="(p,i) in graph.sell" :key="'sell'+i"><rect :x="p.x-3" :y="p.y-3" width="6" height="6" class="sell-point" tabindex="0" role="button" :aria-label="`${p.date} 清仓参考 ${price(p.price)}`" @click="selected={...p,kind:'清仓参考'}" @keydown.enter="selected={...p,kind:'清仓参考'}"/><title>{{p.date}} 清仓 {{price(p.price)}}</title></g>
          <g v-if="graph.forecast"><line v-for="(p,i) in [graph.buy.at(-1),graph.sell.at(-1)]" :key="'future'+i" :x1="p?.x" :y1="p?.y" :x2="graph.forecast.x" :y2="graph.forecast.y" :stroke="i?'#2e9e8f':'#1f5fa9'" :stroke-dasharray="data.holding?undefined:'2 3'" opacity=".6"/><text :x="graph.forecast.x" :y="graph.forecast.y-10" text-anchor="end">{{eta?.status==='ready' ? (data.holding?'预计清仓':'预计建仓') : (data.holding?'清仓参考':'建仓参考')}} {{price(graph.forecast.price)}}</text></g>
          <g v-if="graph.current"><line x1="44" :y1="graph.current.y" :x2="width-40" :y2="graph.current.y" stroke="#8e8e93" stroke-dasharray="2 4"/><circle :cx="graph.current.x" :cy="graph.current.y" r="4" fill="#ff950e"/><text x="46" :y="Math.max(18,graph.current.y-8)">现价 {{price(data.current)}}</text></g>
          <text v-for="(t,i) in graph.ticks" :key="'tick'+i" :x="t.x" y="300" text-anchor="middle">{{t.date.slice(5)}}</text>
        </svg></div>
        <p v-if="selected" class="period-path__readout" aria-live="polite">{{selected.date}} · {{selected.kind}} {{price(selected.price)}} <button @click="selected=null" aria-label="清除点位读数">×</button></p>
        <p class="legend"><span class="buy">○ 建仓价（蓝）</span><span class="sell">□ 清仓价（绿）</span><span>┄ 虚线＝预测段</span><span v-if="data.background.length">琥珀＝周持有 · 灰＝周空仓</span></p>
        <p class="period-path__note">两条线各自连接同类点，之间区域为价格空间。目标／吸筹来自 Canonical 通道；历史页面参考，不代表成交或执行预测。</p>
        <p v-if="eta?.date_limited" class="limitation">日期受历史序列限制，不外推未来交易日。</p>

      </template>
    </div>
  </section>
</template>
<style scoped>
.period-path{margin:8px 0;background:var(--gy-bg-panel);border:1px solid #ff950055;border-radius:8px;color:var(--gy-text-primary);min-width:0}.period-path__toggle{width:100%;display:flex;justify-content:space-between;gap:8px;padding:12px;border:0;background:transparent;color:inherit;cursor:pointer}.period-path__body{padding:0 12px 12px}.canvas{min-width:0}svg{width:100%;height:auto;display:block}svg text{font-size:11px;fill:var(--gy-text-primary)}.legend{display:flex;gap:14px;flex-wrap:wrap}.buy{color:#1f5fa9}.sell{color:#2e9e8f}.buy-line,.sell-line{fill:none;stroke-width:1.8}.buy-line{stroke:#1f5fa9}.sell-line{stroke:#2e9e8f}.buy-point{fill:var(--gy-bg-panel);stroke:#1f5fa9}.sell-point{fill:var(--gy-bg-panel);stroke:#2e9e8f}p,summary{font-size:12px;line-height:1.6}.limitation{color:#996000}
</style>

<style scoped>
.period-path__toggle { color:#b56d00; padding:10px 14px; font-size:13px; }
.period-path__toggle[aria-expanded="true"] { border-bottom:1px solid #ff950033; }
.period-path__body { padding:0 14px 12px; }
.period-path__summary { display:flex; flex-wrap:wrap; gap:4px 10px; margin:8px 0; color:#888; font-size:11px; }
.period-path__summary b { color:#303036; font-weight:600; }
.period-path__estimate { max-width:720px; margin:8px auto 12px; padding:7px 10px; border-radius:7px; background:#edf6f7; font-size:12px; }
.period-path__estimate p { margin:0; }
.period-path__estimate strong { padding:2px 5px; border-radius:3px; background:#ffb52e; font-size:11px; }
.period-path__estimate-detail { color:#888; font-size:11px; }
.period-path__chart-caption,.period-path__note { color:#888; font-size:11px; margin:4px 0; }
.canvas svg { max-height:290px; }
svg text { fill:#888; font-size:10px; }
.buy-point,.sell-point { cursor:pointer; }
.buy-point:focus,.sell-point:focus { outline:2px solid #ff9500; }
.legend { border-top:1px solid #f1f1f4; padding-top:8px; margin:4px 0; color:#888; font-size:11px; gap:8px 14px; }
.period-path__readout { color:#666; margin:0; }
.period-path__readout button { border:0; background:transparent; cursor:pointer; }
</style>
