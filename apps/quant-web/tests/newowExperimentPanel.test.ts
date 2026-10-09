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
const chartUrl=`data:text/javascript;base64,${Buffer.from(`export const CandlestickSeries={},LineSeries={};export function createSeriesMarkers(){return {setMarkers(){}}};export function createChart(){return {addSeries(){return {setData(){},createPriceLine(){return {}},removePriceLine(){}}},removeSeries(){},timeScale(){return {fitContent(){}}},applyOptions(){},remove(){}}}`).toString('base64')}`
async function component(){const source=readFileSync(new URL('../src/components/market/detail/newow/NewowExperimentPanel.vue',import.meta.url),'utf8');const compiled=compileScript(parse(source).descriptor,{id:'experiment',inlineTemplate:true});const root=fileURLToPath(new URL('../src/',import.meta.url));const code=ts.transpileModule(compiled.content,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText.replace(/from ['"]vue['"]/g,`from '${import.meta.resolve('vue')}'`).replace(/from ['"]lightweight-charts['"]/g,`from '${chartUrl}'`).replace(/from ['"]@\/api\/newowExperiments['"]/g,`from '${mockUrl}'`).replace(/from ['"]@\/([^'"]+)['"]/g,(_m,s)=>`from '${pathToFileURL(resolve(root,s+'.ts')).href}'`);return (await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)).default}
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
