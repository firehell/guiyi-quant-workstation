import { onBeforeUnmount, shallowRef, watch, type Ref } from 'vue'
import { getHtdySnapshot } from '../api/htdySnapshot.ts'
import type { HtdySnapshot } from '../types/htdySnapshot.ts'
export function useHtdySnapshot(product:Ref<string>, enabled:Ref<boolean>, fetchSnapshot:typeof getHtdySnapshot=getHtdySnapshot) {
 const data=shallowRef<HtdySnapshot|null>(null), rows=shallowRef<HtdySnapshot['trades']>([])
 const loading=shallowRef(false), moreLoading=shallowRef(false), error=shallowRef<string|null>(null)
 let generation=0, controller:AbortController|null=null
 const failure=(e:unknown)=>{
  const code=(e as {response?:{data?:{detail?:{code?:string}}}})?.response?.data?.detail?.code
  return code?.includes('NOT_BUILT') || code?.includes('MISSING') || code?.includes('NOT_FOUND') ? '历史快照尚未构建，请使用显式构建入口生成历史参考。' : '历史快照读取失败；保留已读取的冻结结果，请重新读取。'
 }
 async function read() {
  controller?.abort(); const abort=new AbortController();controller=abort;const own=++generation
  loading.value=true;moreLoading.value=false;error.value=null
  try {const result=await fetchSnapshot(product.value.toLowerCase(),abort.signal);if(own===generation&&!abort.signal.aborted){data.value=result;rows.value=result.trades}}
  catch(e){if(own===generation&&!abort.signal.aborted)error.value=failure(e)}
  finally{if(own===generation)loading.value=false}
 }
 async function more() {
  if(!data.value?.next_cursor || loading.value || moreLoading.value || rows.value.length>=10000)return
  const own=generation, id=data.value.snapshot_id, abort=controller!, cursor=data.value.next_cursor
  moreLoading.value=true;error.value=null
  try {const result=await fetchSnapshot(product.value.toLowerCase(),abort.signal,id,cursor);if(own!==generation||abort.signal.aborted)return
   const seen=new Set(rows.value.map(row=>row.reference_trade_id));rows.value=[...rows.value,...result.trades.filter(row=>!seen.has(row.reference_trade_id))];data.value={...data.value!,next_cursor:result.next_cursor}
  } catch(e){if(own===generation&&!abort.signal.aborted)error.value=failure(e)}
  finally {if(own===generation)moreLoading.value=false}
 }
 watch([product,enabled],()=>{controller?.abort();generation++;loading.value=false;moreLoading.value=false;data.value=null;rows.value=[];error.value=null;if(enabled.value)void read()},{immediate:true,flush:'sync'})
 onBeforeUnmount(()=>{generation++;controller?.abort()})
 return {data,rows,loading,moreLoading,error,read,more}
}
