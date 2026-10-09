import assert from 'node:assert/strict'
import test from 'node:test'
import {readFileSync} from 'node:fs'
import {fileURLToPath,pathToFileURL} from 'node:url'
import {resolve} from 'node:path'
import {compileScript,parse} from '@vue/compiler-sfc'
import ts from 'typescript'
import {createRenderer,defineComponent,h,nextTick,ref} from 'vue'
const mockUrl=`data:text/javascript;base64,${Buffer.from(`export const calls=[];export function getNewowExperiment(request,signal){return new Promise((resolve,reject)=>calls.push({request,signal,resolve,reject}))}`).toString('base64')}`
const mock=await import(mockUrl)
const chartUrl=`data:text/javascript;base64,${Buffer.from(`export const prices=new Set(),series=[];export const CandlestickSeries={type:'Candlestick'},LineSeries={type:'Line'};export function createSeriesMarkers(){return {setMarkers(){}}};export function createChart(){return {addSeries(definition,options){const record={definition,options,data:[]};series.push(record);return {setData(data){record.data=data},createPriceLine(options){const line={...options};prices.add(line);return line},removePriceLine(line){prices.delete(line)}}},removeSeries(){},timeScale(){return {fitContent(){},getVisibleLogicalRange(){return null},subscribeVisibleLogicalRangeChange(){}}},applyOptions(){},remove(){prices.clear()}}}`).toString('base64')}`
const chartMock=await import(chartUrl)
async function compiledModule(url:URL):Promise<string>{
 const source=readFileSync(url,'utf8'),compiled=compileScript(parse(source,{filename:url.pathname}).descriptor,{id:'experiment',inlineTemplate:true})
 const root=fileURLToPath(new URL('../src/',import.meta.url))
 let code=ts.transpileModule(compiled.content,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText.replace(/from ['"]vue['"]/g,`from '${import.meta.resolve('vue')}'`).replace(/from ['"]lightweight-charts['"]/g,`from '${chartUrl}'`).replace(/from ['"]@\/api\/newowExperiments['"]/g,`from '${mockUrl}'`).replace(/from ['"]@\/([^'"]+)['"]/g,(_m,s)=>`from '${pathToFileURL(resolve(root,s+'.ts')).href}'`)
 for(const match of [...code.matchAll(/from ['"]([^'"]+\.vue)['"]/g)])code=code.replace(match[0],`from '${await compiledModule(new URL(match[1]!,url))}'`)
 return `data:text/javascript;base64,${Buffer.from(code).toString('base64')}`
}
async function component(){return (await import(await compiledModule(new URL('../src/components/market/detail/newow/NewowExperimentPanel.vue',import.meta.url)))).default}
interface TestNode { type: string; props: Record<string, unknown>; parent: TestNode | null; children: TestNode[]; text: string }
function element(type: string): TestNode { return { type, props: {}, parent: null, children: [], text: '', addEventListener(){}, get options(){return this.children.filter(x=>x.type==='option')}, multiple:false } as TestNode }
function findNode(node: TestNode, match: (candidate: TestNode) => boolean): TestNode | undefined {
  if (match(node)) return node
  for (const child of node.children) { const found = findNode(child, match); if (found) return found }
  return undefined
}
function findNodes(node: TestNode, match: (candidate: TestNode) => boolean): TestNode[] {
  return [match(node) ? node : null, ...node.children.flatMap((child) => findNodes(child, match))].filter((item): item is TestNode => item !== null)
}
function nodeText(node: TestNode): string { return [node.text, ...node.children.map(nodeText)].join(' ') }
function nodeOperations() {
  return {
    patchProp(node: TestNode, key: string, _previous: unknown, next: unknown) { node.props[key] = next },
    insert(child: TestNode, parent: TestNode, anchor: TestNode | null = null) { if (child.parent) child.parent.children = child.parent.children.filter(node => node !== child); child.parent = parent; const index = anchor === null ? -1 : parent.children.indexOf(anchor); if (index < 0) parent.children.push(child); else parent.children.splice(index, 0, child) },
    remove(child: TestNode) { if (child.parent === null) return; child.parent.children = child.parent.children.filter((item) => item !== child); child.parent = null },
    createElement: (type: string) => element(type), createText(text: string) { const node = element('#text'); node.text = text; return node }, createComment(text: string) { const node = element('#comment'); node.text = text; return node },
    setText(node: TestNode, text: string) { node.text = text }, setElementText(node: TestNode, text: string) { node.text = text; node.children = [] },
    parentNode(node: TestNode) { return node.parent }, nextSibling(node: TestNode) { if (node.parent === null) return null; const index = node.parent.children.indexOf(node); return node.parent.children[index + 1] ?? null }, querySelector() { return null }, setScopeId() {}, insertStaticContent() { return [element('#static'), element('#static')] as const },
  }
}


const flush=async()=>{await nextTick();await nextTick();await nextTick()}
test('mounted panel clears old facts on kind switch and ignores late requests after switch/unmount',async()=>{globalThis.ResizeObserver=class{observe(){}disconnect(){}} as any;const Panel=await component();const root=element('root'),kind=ref('osc-test'),base=mock.calls.length;const app=createRenderer(nodeOperations()).createApp(defineComponent({setup:()=>()=>h(Panel,{product:'rb',frequency:'1d',kind:kind.value,asOf:'2026-10-08T07:00:00Z'})}));app.mount(root);await flush();assert.match(nodeText(root),/正在读取实验策略/);kind.value='osc-test4';await flush();assert.equal(mock.calls[base].signal.aborted,true);mock.calls[base].resolve({segments:[],bars:[],markers:[],readiness:{status:'READY'},formula_version:'stale',as_of:'2026-10-08T07:00:00Z'});await flush();assert.doesNotMatch(nodeText(root),/stale/);mock.calls[base+1].resolve({segments:[],bars:[],markers:[],readiness:{status:'DATA_INSUFFICIENT'},formula_version:'fresh',as_of:'2026-10-08T07:00:00Z'});await flush();assert.match(nodeText(root),/数据不足/);assert.match(nodeText(root),/fresh/);kind.value='osc-test2';await flush();assert.doesNotMatch(nodeText(root),/fresh/);app.unmount();assert.equal(mock.calls[base+2].signal.aborted,true)})

test('experiment graph keeps HHV10 facts and renders independent saved overlays with test4 12% anchor',async()=>{
 globalThis.ResizeObserver=class{observe(){}disconnect(){}} as any
 const Panel=await component(),root=element('root'),kind=ref('osc-test4'),base=mock.calls.length
 const app=createRenderer(nodeOperations()).createApp(defineComponent({setup:()=>()=>h(Panel,{product:'rb',frequency:'1d',kind:kind.value,asOf:'2026-10-08T07:00:00Z'})}))
 app.mount(root);await flush()
 const bars=Array.from({length:20},(_,i)=>({bar_end:`2026-09-${String(i+1).padStart(2,'0')}T07:00:00Z`,trading_day:'2026-09-01',physical_contract:'RB2701',segment_id:'a',open:'100',high:String(110+i),low:'90',close:'105',channel_high:'888',channel_low:'777'}))
 mock.calls[base].resolve({bars,markers:[{bar_end:bars[1]!.bar_end,physical_contract:'RB2701',segment_id:'a',action:'BUILD',reference_price:'100',score:1}],segments:[],readiness:{status:'READY'},formula_version:'test',as_of:'2026-10-08T07:00:00Z'});await flush()
 assert.equal(chartMock.prices.size,0)
 const stop=findNode(root,n=>n.type==='button'&&nodeText(n).trim()==='止损参考线')!
 ;(stop.props.onClick as ()=>void)();await flush()
 assert.deepEqual([...chartMock.prices].map((x:any)=>[x.price,x.color,x.title]),[[88,'#3B82F6','止损价（−12%）']])
 const channel=findNode(root,n=>n.type==='button'&&nodeText(n).trim()==='唐奇安通道')!
 ;(channel.props.onClick as ()=>void)();await flush()
 assert.ok(chartMock.series.some((s:any)=>s.options?.color==='rgba(52,199,89,0.7)'&&s.data.at(-1)?.value===129))
 assert.ok(chartMock.series.some((s:any)=>s.options?.color==='#f7bb23'&&s.data.at(-1)?.value===888),'business channel stays supplied HHV10')
 kind.value='osc-test';await flush();assert.equal(chartMock.prices.size,0,'request invalidation removes old anchor')
 app.unmount()
})
