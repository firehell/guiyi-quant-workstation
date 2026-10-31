<script setup lang="ts">
import {ref,watch,nextTick,onMounted,onBeforeUnmount} from 'vue'
import {drawMainRiseProcessLabels,type PositionedProcessHint} from '@/utils/newowProcessHintDisplay'
const props=defineProps<{points:readonly PositionedProcessHint[];width:number;height:number;dark:boolean}>()
const canvas=ref<HTMLCanvasElement|null>(null)
function draw(){
 const el=canvas.value;if(!el)return
 const dpr=typeof window==='undefined'?1:window.devicePixelRatio||1
 el.width=Math.round(props.width*dpr);el.height=Math.round(props.height*dpr)
 const ctx=el.getContext?.('2d');if(!ctx)return
 ctx.scale(dpr,dpr);drawMainRiseProcessLabels(ctx,props.points,props.dark)
}
watch(()=>[props.points,props.width,props.height,props.dark],()=>void nextTick(draw),{deep:true})
onMounted(()=>{draw();if(typeof window!=='undefined')window.addEventListener('resize',draw)})
onBeforeUnmount(()=>{if(typeof window!=='undefined')window.removeEventListener('resize',draw)})
</script>
<template><canvas ref="canvas" class="newow-main-rise-process-labels" :style="{width:width+'px',height:height+'px'}" aria-hidden="true" /></template>
<style scoped>.newow-main-rise-process-labels{position:absolute;left:0;top:0;pointer-events:none}</style>
