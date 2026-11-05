<script setup lang="ts">
import {computed} from 'vue'
import {layoutBreakouts,type BreakoutPoint,type NewowBreakoutEvent} from '@/utils/newowBreakoutEvents'
const props=defineProps<{points:readonly BreakoutPoint[];width:number;height:number;shapes:boolean;wicks:boolean}>()
const emit=defineEmits<{'select-breakout':[event:NewowBreakoutEvent]}>()
let context:CanvasRenderingContext2D|null=null
const measure=(text:string,size:number)=>{
 context??=document.createElement('canvas').getContext('2d')
 if(!context)return text.length*size
 context.font=`${size}px -apple-system, "PingFang SC", sans-serif`
 return context.measureText(text).width
}
const labels=computed(()=>layoutBreakouts(props.points,props.width,props.height,props.shapes,props.wicks,measure))
const visible=computed(()=>props.points.filter(p=>(p.event.kind.startsWith('wick_')?props.wicks:props.shapes)&&Number.isFinite(p.x)&&Number.isFinite(p.y)&&p.x>=0&&p.x<=props.width&&p.y>=0&&p.y<=props.height))
</script>
<template>
 <div class="breakout-overlay" :style="{width:width+'px',height:height+'px'}" aria-label="突破形态，非成交">
  <svg :width="width" :height="height" aria-hidden="true" class="breakout-decoration">
   <g v-for="p in visible" :key="p.event.event_id">
    <template v-if="p.band">
     <rect class="breakout-band" :x="p.band.left" :y="p.band.top" :width="Math.max(2,p.band.right-p.band.left)" :height="p.band.bottom-p.band.top" />
     <line class="breakout-threshold" :x1="p.band.left" :x2="p.band.right" :y1="p.band.thresholdY" :y2="p.band.thresholdY" />
    </template>
    <rect class="breakout-volume" :x="p.x-(p.candleWidth??2)*.4" :y="height*.90" :width="(p.candleWidth??2)*.8" :height="height*.07" />
   </g>
   <line v-for="p in labels.filter(p=>p.event.kind==='pending')" :key="'pending:'+p.event.event_id" class="breakout-connector" :x1="p.x" :x2="p.x" :y1="p.event.side==='up'?p.top+30:p.top" :y2="p.y" />
  </svg>
  <button v-for="p in labels" :key="p.event.event_id" type="button" :class="{pending:p.event.kind==='pending',wick:p.event.kind.startsWith('wick_')}" :style="{left:p.left+'px',top:p.top+'px',width:p.width+'px',color:p.color,background:p.fill??'transparent',borderColor:p.stroke??'transparent'}" :aria-label="p.label+' · '+p.detail+' · '+p.event.bar_end+' · '+p.event.physical_contract" @pointerdown.stop @click.stop="emit('select-breakout',p.event)"><strong>{{p.label}}</strong><span>{{p.detail}}</span></button>
 </div>
</template>
<style scoped>
.breakout-overlay{--breakout-pending-text:#6E6E73;--breakout-pending-stroke:#8E8E93;--breakout-band:rgba(255,107,53,.12);--breakout-volume:rgba(255,107,53,.65);position:absolute;top:0;left:0;overflow:hidden;pointer-events:none;z-index:7}
:global([data-theme='dark'] .breakout-overlay){--breakout-pending-text:#AEAEB2;--breakout-pending-stroke:#AEAEB2;--breakout-band:rgba(255,107,53,.10);--breakout-volume:rgba(255,107,53,.55)}
.breakout-decoration{position:absolute;inset:0;overflow:hidden;pointer-events:none}.breakout-band{fill:var(--breakout-band)}.breakout-threshold{stroke:#FF6B35;stroke-width:1;stroke-dasharray:4 3}.breakout-volume{fill:var(--breakout-volume)}.breakout-connector{stroke:var(--breakout-pending-stroke);stroke-width:1;stroke-dasharray:3 3}
.breakout-overlay button{position:absolute;pointer-events:auto;cursor:pointer;height:30px;min-height:30px;max-height:30px;min-width:0;margin:0;padding:0;appearance:none;box-shadow:none;box-sizing:border-box;border:1px solid transparent;border-radius:5px;white-space:nowrap;font-family:-apple-system,"PingFang SC",sans-serif;font-weight:400;letter-spacing:normal}
.breakout-overlay button strong,.breakout-overlay button span{position:absolute;left:0;width:100%;line-height:1;transform:translateY(-50%);text-align:center;font-weight:400}.breakout-overlay button strong{top:9px;font-size:11px}.breakout-overlay button span{top:21px;font-size:10px;opacity:.85}.breakout-overlay button.wick strong{font-size:10px}.breakout-overlay button.wick span{font-size:9px}.breakout-overlay button:focus-visible{outline:2px solid var(--gy-accent);outline-offset:1px}
</style>
