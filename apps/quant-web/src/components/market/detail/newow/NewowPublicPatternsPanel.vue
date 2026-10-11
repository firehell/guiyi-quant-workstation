<script setup lang="ts">
import { computed, inject, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { NewowProductChartModel } from './newowProductChartPrimitives'
import { NEWOW_PATTERN_NAMES, NEWOW_PATTERN_WORKER_FACTORY, PatternScanSession, splitNewowPatternOwners, type PatternChoice, type PatternWorker } from '@/utils/newowPatternDisplay'
import { NEWOW_PUBLIC_PATTERNS_METADATA, type NewowPublicPattern } from '@/utils/newowPublicPatterns'
const props=defineProps<{model:NewowProductChartModel|null;windowKey:string|null}>()
const emit=defineEmits<{select:[choice:PatternChoice];preview:[choice:PatternChoice];clear:[]}>()
const groups=computed(()=>splitNewowPatternOwners(props.model?.bars??[]))
const selectedOwner=ref(''),patterns=ref<NewowPublicPattern[]>([]),busy=ref(false),error=ref<string|null>(null)
const factory=inject<()=>PatternWorker>(NEWOW_PATTERN_WORKER_FACTORY,()=>new Worker(new URL('../../../../workers/newowPublicPatterns.worker.ts',import.meta.url),{type:'module'}) as unknown as PatternWorker)
let mounted=false
const session=new PatternScanSession(factory,result=>{
 busy.value=false;error.value=result.error?'形态计算失败，请重试':null;patterns.value=result.results[0]?.patterns??[]
 const first=patterns.value[0];if(first){const value=choice(first);if(value)emit('preview',value)}
})
const owner=computed(()=>groups.value.find(group=>group.key===selectedOwner.value))
function choice(pattern:NewowPublicPattern):PatternChoice|null{return owner.value&&props.windowKey?{key:JSON.stringify([props.windowKey,owner.value.key,pattern.type]),windowKey:props.windowKey,ownerKey:owner.value.key,bars:owner.value.bars,pattern}:null}
function scan(){session.cancel();patterns.value=[];error.value=null;emit('clear');if(!mounted||!owner.value||!props.windowKey){busy.value=false;return}busy.value=true
 try{session.run({key:props.windowKey,period:props.model?.identity.frequency==='1w'?'week':'day',groups:[owner.value]})}catch{busy.value=false;error.value='形态计算不可用，请重试'}
}
watch(()=>[props.model,props.windowKey] as const,()=>{selectedOwner.value=groups.value.at(-1)?.key??'';scan()},{immediate:true})
watch(selectedOwner,scan)
onMounted(()=>{mounted=true;scan()})
onBeforeUnmount(()=>{mounted=false;session.cancel()})
function select(pattern:NewowPublicPattern){const value=choice(pattern);if(value)emit('select',value)}
</script>
<template>
 <section class="public-patterns" aria-label="七类公开回看形态" :data-formula-version="NEWOW_PUBLIC_PATTERNS_METADATA.version">
  <p>杯柄、浅碟、双底、平台、递升、盘整、窄幅。按评分排序，默认叠加最佳候选。</p>
  <p class="public-patterns__note">回看形态会随新增 K 线变化，仅用于图形参考，不触发建仓清仓。</p>
  <label>合约区段 <select v-model="selectedOwner"><option v-for="group in groups" :key="group.key" :value="group.key">{{ group.bars[0]?.physicalContract }} · {{ group.bars[0]?.tradingDay }}～{{ group.bars.at(-1)?.tradingDay }} · {{ group.bars.length }} 根</option></select></label>
  <p>使用此区段全部已加载 K 线；向前加载更多后重新识别，不跨合约拼接。</p>
  <p v-if="busy" role="status">正在识别七类形态…</p>
  <p v-else-if="error" role="status">{{ error }} <button @click="scan">重试</button></p>
  <p v-else-if="!patterns.length" role="status">当前区段未检测到符合原式的形态。</p>
  <table v-else><thead><tr><th>形态</th><th>评分</th><th>操作</th></tr></thead><tbody><tr v-for="pattern in patterns" :key="pattern.type"><td>{{ NEWOW_PATTERN_NAMES[pattern.type] }}</td><td :class="pattern.score>=80?'high':pattern.score>=60?'medium':'low'">{{ pattern.score }} 分</td><td><button @click="select(pattern)">绘制</button></td></tr></tbody></table>
  <button @click="emit('clear')">清除叠加</button>
 </section>
</template>
<style scoped>
.public-patterns p{font-size:12px;color:#667085;line-height:1.6}.public-patterns__note{background:#f5f7fa;padding:8px;border-radius:6px}label{display:flex;gap:8px;align-items:center;font-size:13px}select{max-width:100%;min-width:0;padding:8px;border:1px solid #ddd;border-radius:6px}table{width:100%;border-collapse:collapse;margin:12px 0}th,td{padding:10px 6px;border-bottom:1px solid #ebedf0;text-align:left;font-size:13px}button{padding:6px 12px;border:0;border-radius:6px;background:#007aff;color:white;cursor:pointer}.high{color:#34c759;font-weight:700}.medium{color:#ff9500}.low{color:#007aff}
</style>
