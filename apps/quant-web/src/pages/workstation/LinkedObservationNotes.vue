<script setup lang="ts">
import { ref, shallowRef, watch } from 'vue'
import { targetObservations, type ObservationLinkKind } from '@/api/journalObservations'
const props = defineProps<{kind: ObservationLinkKind; targetId: string; version?: number}>()
const open = ref(false), offset = ref(0), next = ref<number|null>(null), retry = ref(0), status = ref('')
const items = shallowRef<{id:string;trading_day:string;contract:string;note:string}[]>([])
watch(() => [props.kind,props.targetId,props.version], () => {offset.value = 0}, {flush:'sync'})
watch(() => [props.kind,props.targetId,props.version,open.value,offset.value,retry.value], async (_,__,cleanup) => {
  const controller = new AbortController()
  cleanup(() => controller.abort())
  items.value=[]; next.value=null; status.value=''
  if (!open.value) return
  status.value='读取中…'
  try {
    const data = await targetObservations(props.kind,props.targetId,props.version,offset.value,controller.signal)
    if (!controller.signal.aborted) { items.value=data.items; next.value=data.next_offset; status.value=items.value.length?'':'尚未关联行情观察。' }
  } catch {if (!controller.signal.aborted) status.value='读取失败。'}
})
</script>
<template><details @toggle="open=($event.target as HTMLDetailsElement).open"><summary>关联的行情观察</summary>
<p v-if="status">{{ status }} <button v-if="status==='读取失败。'" type="button" @click="retry++">重试</button></p>
<ul v-else><li v-for="n in items" :key="n.id"><RouterLink :to="{name:'trade-journal',params:{caseId:''},query:{observation:n.id,day:n.trading_day}}">{{ n.trading_day }} · {{ n.contract }} · {{ n.note }}</RouterLink></li></ul>
<button v-if="offset" type="button" @click="offset-=30">上一页观察</button>
<button v-if="next!==null" type="button" @click="offset=next">下一页观察</button>
</details></template>
<style scoped>details { margin:8px 0; } summary, button { cursor:pointer; } a { color:var(--gy-link); } li {overflow-wrap:anywhere;}</style>
