import assert from 'node:assert/strict'
import test from 'node:test'
import { createRenderer, defineComponent, h, nextTick, ref } from 'vue'
import { useHtdySnapshot } from '../src/composables/useHtdySnapshot.ts'
const tick=async()=>{await new Promise(resolve=>setImmediate(resolve));await nextTick()}
function harness(){
 const product=ref('jm'),enabled=ref(true),calls:any[]=[];let hook!:ReturnType<typeof useHtdySnapshot>
 const renderer=createRenderer<any,any>({patchProp(){},insert(){},remove(){},createElement:()=>({}),createText:()=>({}),createComment:()=>({}),setText(){},setElementText(){},parentNode:()=>null,nextSibling:()=>null})
 const app=renderer.createApp(defineComponent({setup(){hook=useHtdySnapshot(product,enabled,((...args:any[])=>new Promise((resolve,reject)=>calls.push({args,resolve,reject}))) as any);return()=>h('div')}}));app.mount({})
 return {product,enabled,calls,hook,app}
}
test('snapshot source switches abort and cannot accept late responses',async()=>{
 const h=harness();try{h.product.value='rb';await tick();assert.equal(h.calls[0].args[1].aborted,true);h.calls[0].resolve({snapshot_id:'old',trades:[]});await tick();assert.equal(h.hook.data.value,null);h.calls[1].resolve({snapshot_id:'new',trades:[]});await tick();assert.equal(h.hook.data.value?.snapshot_id,'new')}finally{h.app.unmount()}
})
test('pagination pins immutable snapshot and a failed reread retains frozen results',async()=>{
 const h=harness();try{h.calls[0].resolve({snapshot_id:'frozen',trades:[{reference_trade_id:'a'}],next_cursor:'frozen:1'});await tick();const pending=h.hook.more();assert.deepEqual(h.calls[1].args.slice(2),['frozen','frozen:1']);h.calls[1].resolve({snapshot_id:'frozen',trades:[{reference_trade_id:'b'}],next_cursor:null});await pending;assert.equal(h.hook.rows.value.length,2);const refresh=h.hook.read();h.calls[2].reject(Error('offline'));await refresh;assert.equal(h.hook.data.value?.snapshot_id,'frozen');assert.equal(h.hook.rows.value.length,2);assert.match(h.hook.error.value!,/读取失败/)}finally{h.app.unmount()}
})
