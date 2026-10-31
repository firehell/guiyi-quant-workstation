<script setup lang="ts">
import {ref,watch,onMounted,nextTick,onBeforeUnmount} from 'vue'
import {readNewowChartDisplayTheme} from '@/utils/newowChartDisplayTheme'
import {BREAKDOWN_FONT,layoutDisplayLabels,drawDisplayLabels,displayEventTitle,type DisplayPoint,type DisplayLabel,type NewowDisplayEvent} from '@/utils/newowDisplayEvents'
const props=defineProps<{points:readonly DisplayPoint[];width:number;height:number}>()
const emit=defineEmits<{'select-display':[event:NewowDisplayEvent]}>()
const canvas=ref<HTMLCanvasElement|null>(null),labels=ref<DisplayLabel[]>([])
let observer:MutationObserver|null=null
function draw(){
 const el=canvas.value;if(!el)return
 const dpr=typeof window==='undefined'?1:window.devicePixelRatio||1;el.width=Math.round(props.width*dpr);el.height=Math.round(props.height*dpr)
 const ctx=el.getContext?.('2d');if(!ctx)return
 ctx.scale(dpr,dpr);ctx.font=BREAKDOWN_FONT
 labels.value=layoutDisplayLabels(props.points,text=>ctx.measureText(text).width)
 drawDisplayLabels(ctx,labels.value,readNewowChartDisplayTheme()==='dark')
}
watch(()=>[props.points,props.width,props.height],()=>void nextTick(draw),{deep:true})
onMounted(()=>{draw();if(typeof MutationObserver!=='undefined'){observer=new MutationObserver(draw);observer.observe(document.documentElement,{attributes:true,attributeFilter:['data-theme','class']});observer.observe(document.body,{attributes:true,attributeFilter:['data-theme','class']})}if(typeof window!=='undefined')window.addEventListener('resize',draw)})
onBeforeUnmount(()=>{observer?.disconnect();if(typeof window!=='undefined')window.removeEventListener('resize',draw)})
</script>
<template><div class="newow-display-overlay" :style="{width:width+'px',height:height+'px'}" aria-label="独立展示提示，非成交"><canvas ref="canvas" :style="{width:width+'px',height:height+'px'}" aria-hidden="true"/><button v-for="p in labels" :key="p.event.event_id" type="button" :title="displayEventTitle(p.event)" :aria-label="displayEventTitle(p.event)" :style="{left:(p.x-p.width/2)+'px',top:(p.event.kind!=='OSC_BREAKDOWN'?p.y-12:p.y)+'px',width:p.width+'px',height:(p.event.kind!=='OSC_BREAKDOWN'?12:16)+'px'}" @pointerdown.stop @click.stop="emit('select-display',p.event)"/></div></template>
<style scoped>
.newow-display-overlay{position:absolute;pointer-events:none;overflow:hidden;z-index:6;top:0;left:0}.newow-display-overlay canvas{position:absolute;top:0;left:0}.newow-display-overlay button{position:absolute;background:transparent;border:0;padding:0;pointer-events:auto;cursor:pointer}.newow-display-overlay button:focus-visible{outline:2px solid var(--gy-accent);outline-offset:2px}
</style>
