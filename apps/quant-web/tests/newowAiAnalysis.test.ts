import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { compileScript, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import { createRenderer, defineComponent, h, nextTick, ref } from 'vue'
import { getNewowAiAnalysis, validateAiAnalysis } from '../src/api/newowAiAnalysis.ts'
const asOf='2026-09-24T07:00:00.000001Z'
function output(product='jm') { return {schema_version:'newow_ai_analysis_v1',product,as_of:asOf,formula_version:'newow_ai_summary_ranking_page_v1',futures_adapter_version:'guiyi_newow_ai_segment_valuation_v1',page_source_sha256:'b12da74d89a7ac304d7479999d11f13ab53ced834a8472f937d78a0c1bd03709',page_kernel_parity:true,page_parity:false,executable:false,combos:['1w','1d'].flatMap(frequency=>['oscillation','trend'].map(strategy=>({strategy,frequency,since:frequency==='1w'?'2024-06-01':'2025-09-01',through:'2026-09-24',source_bars:100,input_sha256:'a'.repeat(64),summary:{cumulative_return:'25.50',win_rate:60,max_drawdown:'12.50',trade_count:10,terminal_valuation_count:1,segment_count:1,warming_segment_count:0},reason_code:null,score:'0.5000',confidence:'high',is_best:strategy==='trend'&&frequency==='1w'})))} }
test('transport binds exact cutoff, product and page contract; rejects hourly/invalid metrics',async()=>{
  let called:any
  assert.equal((await getNewowAiAnalysis('jm',asOf,{request:async(path,config)=>{called={path,config};return output()}})).combos.length,4)
  assert.equal(called.path,'/market/newow/ai-analysis');assert.deepEqual(called.config.params,{product:'jm',as_of:asOf})
  assert.equal(validateAiAnalysis(output(),'rb',asOf),false)
  assert.equal(validateAiAnalysis(output(),'jm','2026-09-24T07:00:00.000002Z'),false)
  for(const mutate of [(v:any)=>{v.combos[0].frequency='60m'},(v:any)=>{v.executable=true},(v:any)=>{v.combos[0]=v.combos[1]},(v:any)=>{v.combos[0].score='NaN'},(v:any)=>{v.combos[0].summary.terminal_valuation_count=11},(v:any)=>{v.combos[0].is_best=true},(v:any)=>{v.combos[0].input_sha256=null}]){const v=output();mutate(v);assert.equal(validateAiAnalysis(v,'jm',asOf),false)}
  await assert.rejects(getNewowAiAnalysis('jm',asOf,{request:async()=>output('rb')}),/NEWOW_AI_RESPONSE_INVALID/)
})
const mockUrl=`data:text/javascript;base64,${Buffer.from('export const calls=[];export function getNewowAiAnalysis(product,asOf,options){return new Promise((resolve,reject)=>calls.push({product,asOf,options,resolve,reject}));}').toString('base64')}`
const mock=await import(mockUrl)
const dialogUrl=`data:text/javascript;base64,${Buffer.from(`import {defineComponent,h} from '${import.meta.resolve('vue')}';export default defineComponent({props:['open','title','identityKey','variant'],setup(p,{slots}){return()=>p.open?h('section',{},[h('h2',{},p.title),slots.default?.(),slots.footer?.()]):null}})`).toString('base64')}`
async function component(){const {descriptor}=parse(readFileSync(new URL('../src/components/market/detail/newow/NewowAiAnalysisDialog.vue',import.meta.url),'utf8'));const code=ts.transpileModule(compileScript(descriptor,{id:'ai-test',inlineTemplate:true}).content,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText.replace(/from ['"]vue['"]/g,`from '${import.meta.resolve('vue')}'`).replace(/from ['"]\.\/NewowDetailDialog.vue['"]/g,`from '${dialogUrl}'`).replace(/from ['"]@\/api\/newowAiAnalysis['"]/g,`from '${mockUrl}'`);return(await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)).default}
interface N{type:string;props:Record<string,any>;parent:N|null;children:N[];text:string}
const element=(type:string):N=>({type,props:{},parent:null,children:[],text:''})
const text=(n:N):string=>[n.text,...n.children.map(text)].join(' ')
const find=(n:N,p:(n:N)=>boolean):N|undefined=>p(n)?n:n.children.map(c=>find(c,p)).find(Boolean)
const host={patchProp(n:N,k:string,_p:any,v:any){n.props[k]=v},insert(n:N,p:N,a:N|null=null){if(n.parent)n.parent.children=n.parent.children.filter(x=>x!==n);n.parent=p;const i=a?p.children.indexOf(a):-1;i<0?p.children.push(n):p.children.splice(i,0,n)},remove(n:N){if(n.parent)n.parent.children=n.parent.children.filter(x=>x!==n);n.parent=null},createElement:element,createText(t:string){const n=element('#text');n.text=t;return n},createComment(t:string){const n=element('#comment');n.text=t;return n},setText(n:N,t:string){n.text=t},setElementText(n:N,t:string){n.text=t;n.children=[]},parentNode(n:N){return n.parent},nextSibling(n:N){return n.parent?.children[n.parent.children.indexOf(n)+1]??null},setScopeId(){},querySelector(){return null},insertStaticContent(){return[element('#static'),element('#static')]as const}}
test('dialog request/loading/rerun/adopt/error and stale/close/unmount cancellation',async()=>{
  const Panel=await component(),root=element('root'),open=ref(false),product=ref('jm');let adopted:any;const base=mock.calls.length
  const app=createRenderer(host).createApp(defineComponent({setup:()=>()=>h(Panel,{open:open.value,product:product.value,asOf,identityKey:product.value,onAdopt:(c:any)=>{adopted=c}})}))
  app.mount(root);assert.equal(mock.calls.length,base);open.value=true;await nextTick();assert.equal(mock.calls.length,base+1);assert.match(text(root),/正在回测/)
  mock.calls[base].resolve(output());await nextTick();await nextTick();assert.match(text(root),/AI策略分析推荐.*趋势策略.*周线/)
  find(root,n=>n.type==='button'&&text(n)==='采纳推荐')!.props.onClick();assert.equal(adopted.frequency,'1w');assert.equal(adopted.strategy,'trend')
  find(root,n=>n.type==='button'&&text(n)==='重新回测')!.props.onClick();await nextTick();assert.equal(mock.calls.length,base+2);assert.equal(find(root,n=>n.type==='button'&&text(n)==='采纳推荐')!.props.disabled,true)
  product.value='rb';await nextTick();assert.equal(mock.calls[base+1].options.signal.aborted,true);mock.calls[base+1].resolve(output());await nextTick();await nextTick();assert.match(text(root),/正在回测/)
  mock.calls[base+2].reject(new Error('private_error_detail'));await nextTick();await nextTick();assert.match(text(root),/分析数据暂不可用/);assert.doesNotMatch(text(root),/private_error_detail/)
  find(root,n=>n.type==='button'&&text(n)==='重新回测')!.props.onClick();await nextTick();const last=mock.calls.at(-1);open.value=false;await nextTick();assert.equal(last.options.signal.aborted,true);assert.doesNotMatch(text(root),/推荐/)
  open.value=true;await nextTick();const final=mock.calls.at(-1);app.unmount();assert.equal(final.options.signal.aborted,true)
})
