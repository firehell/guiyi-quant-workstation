<script setup lang="ts">
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import ReturnCurveSvg from '@/components/charts/ReturnCurveSvg.vue'
import { getFuturesCurve } from '@/api/newowFutures'
import type { FuturesSnapshot, FuturesCurve, FuturesCurveKind } from '@/types/newowFutures'
import { futuresCurvePoints, validateFuturesCurve, futuresReason } from '@/utils/newowFuturesPresentation'
import { returnCurveLayout } from '@/utils/returnCurveLayout'
const props=defineProps<{ packet:FuturesSnapshot; kind:FuturesCurveKind }>()
const curve=shallowRef<FuturesCurve|null>(null),loading=ref(false),error=ref<string|null>(null)
let owner:AbortController|null=null
const title=computed(()=>props.kind==='equity'?'模型账户权益曲线':'独立参考收益曲线')
watch(()=>[props.packet.run_id,props.packet.sha256,props.kind].join(':'),async()=>{
  owner?.abort();const current=owner=new AbortController(),packet=props.packet,kind=props.kind
  curve.value=null;error.value=null;loading.value=true
  try{
    const value=validateFuturesCurve(await getFuturesCurve(packet.run_id,packet.sha256,kind,current.signal),packet.run_id,packet.sha256,kind,packet.metadata.as_of)
    if(!current.signal.aborted)curve.value=value
  }catch{if(!current.signal.aborted)error.value='曲线暂不可用，未使用记录预览拼接曲线。'}
  finally{if(!current.signal.aborted)loading.value=false}
},{immediate:true,flush:'sync'})
const plot=computed(()=>returnCurveLayout(curve.value?.status==='COMPLETED'?futuresCurvePoints(curve.value):[],{headroom:1.05,areaBaseline:'bottom',valueUnit:props.kind==='equity'?'currency':'percentage_points'}))
onBeforeUnmount(()=>owner?.abort())
</script>
<template>
  <section class="futures-curve" :aria-label="title" :aria-busy="loading">
    <h4>{{ title }}</h4>
    <p v-if="loading" role="status">正在读取完整记录区间的曲线…</p>
    <p v-else-if="error" role="status">{{ error }}</p>
    <template v-else-if="curve">
      <p v-if="curve.status!=='COMPLETED'" role="status">{{ futuresReason(curve.status) }}</p>
      <template v-else-if="curve.points.length"><ReturnCurveSvg :plot="plot" :label="title" :area="true"/>
        <p class="futures-curve__coverage">完整记录区间共 {{ curve.total_points }} 个估值点{{ curve.sampled ? `，按全区间抽样显示 ${curve.points.length} 点` : '' }}。</p>
      </template>
      <p v-else role="status">该冻结结果没有可用的{{ kind==='equity'?'模型账户权益':'独立参考收益' }}曲线。</p>
    </template>
  </section>
</template>
<style scoped>.futures-curve{min-width:0;margin-top:16px}.futures-curve h4{font-size:13px;font-weight:600;margin:0 0 8px}.futures-curve p{font-size:12px;line-height:1.5;color:var(--gy-text-muted)}.futures-curve__coverage{margin-bottom:0}</style>
