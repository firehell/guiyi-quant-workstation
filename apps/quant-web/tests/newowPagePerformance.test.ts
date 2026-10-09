import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { compileScript, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import { createRenderer, defineComponent, h, nextTick } from 'vue'
import { normalizePagePerformance, pagePerformancePlot } from '../src/utils/newowPagePerformance.ts'
function payload() {
  const mode = (pct:string,forceClose:boolean) => ({period:'day',summary:{cumReturn:pct,accuracy:100,maxDrawdown:'0',tradeCount:1},dates:['2026-01-01','2026-01-02','2026-01-03'],trading_days:['2026-01-01','2026-01-02','2026-01-03'],segment_ids:['owner','owner','owner'],equity:['0','1',pct],trades:[{buyDate:'2026-01-01',buyPrice:'100',sellDate:'2026-01-03',sellPrice:String(100+Number(pct)),pct,forceClose,segment_id:'owner'}]})
  return {version:'newow_page_performance_v3379_v2',source_version:'3.3.79',source_sha256:'3c1d600a1bd59dc8d8edfe46dd0cdfa1b44dbd9e7124a20d509426eb1d66973d',page_parity:true,executable:false,strategy:'trend',input_sha256:'a'.repeat(64),source_evidence_sha256:null,segment_count:1,ordinary_interrupted_count:0,ideal_open_count:0,ordinary:mode('2',true),ideal:mode('9',false)}
}
test('strict page projection rejects source identity and curve/trade contradictions',()=>{
  assert.equal(normalizePagePerformance(undefined,'trend'),null)
  const mutations=[(p:ReturnType<typeof payload>)=>{p.source_sha256='f'.repeat(64)},(p:ReturnType<typeof payload>)=>{p.executable=true},(p:ReturnType<typeof payload>)=>{p.ordinary.equity.pop()},(p:ReturnType<typeof payload>)=>{p.ordinary.summary.tradeCount=2},(p:ReturnType<typeof payload>)=>{p.ordinary.trades[0]!.buyPrice='0'}]
  for (const mutate of mutations){const p=payload();mutate(p);assert.throws(()=>normalizePagePerformance(p,'trend'),/page_performance/)}
  assert.throws(()=>normalizePagePerformance({...payload(),strategy:'fusion'},'trend'),/identity/)
  const parsed=normalizePagePerformance(payload(),'trend')!; assert.equal(parsed.ordinary!.trades[0]!.forceClose,true)
  const split={...parsed.ordinary!,segment_ids:['one','two','two']};assert.equal(pagePerformancePlot(split).length,2)
})
async function panel(){
 const url=new URL('../src/components/market/detail/newow/NewowPagePerformancePanel.vue',import.meta.url)
 const compiled=compileScript(parse(readFileSync(url,'utf8')).descriptor,{id:'page-test',inlineTemplate:true})
 const root=fileURLToPath(new URL('../src/',import.meta.url))
 const code=ts.transpileModule(compiled.content,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText.replace(/from ['"]vue['"]/g,`from '${import.meta.resolve('vue')}'`).replace(/from ['"]@\/([^'"]+)['"]/g,(_match,specifier:string)=>`from '${pathToFileURL(resolve(root,`${specifier}.ts`)).href}'`)
 return (await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)).default
}
test('ordinary/theoretical toggle changes independent curve summary and estimate records together',async()=>{
 const Panel=await panel(),root=element('root')
 const app=createRenderer(nodeOperations()).createApp(defineComponent({setup:()=>()=>h(Panel,{value:normalizePagePerformance(payload(),'trend'),since:'2026-01-01',through:'2026-01-02'})}))
 app.mount(root)
 assert.match(nodeText(root),/末根估值平仓/)
 assert.match(nodeText(findNode(root,n=>n.props['data-testid']==='page-performance-summary')!),/2/)
 const ordinary=findNode(root,n=>n.type==='polyline')!.props.points
 const button=findNode(root,n=>n.type==='button'&&nodeText(n)==='理论值')!
 ;(button.props.onClick as Function)();await nextTick()
 assert.match(nodeText(root),/页面清仓参考/)
 assert.doesNotMatch(nodeText(root),/末根估值平仓/)
 assert.match(nodeText(findNode(root,n=>n.props['data-testid']==='page-performance-summary')!),/9/)
 assert.match(nodeText(findNode(root,n=>n.props['data-testid']==='page-performance-summary')!),/单笔最大亏损/)
 assert.doesNotMatch(nodeText(findNode(root,n=>n.props['data-testid']==='page-performance-summary')!),/页面回撤/)
 assert.notEqual(findNode(root,n=>n.type==='polyline')!.props.points,ordinary)
 app.unmount()
 const absent=element('root'),empty=createRenderer(nodeOperations()).createApp(Panel,{value:null});empty.mount(absent)
 assert.match(nodeText(absent),/投影不可用/);assert.equal(findNode(absent,n=>n.props['data-testid']==='page-performance-summary'),undefined);empty.unmount()
})
interface TestNode { type: string; props: Record<string, unknown>; parent: TestNode | null; children: TestNode[]; text: string }
function element(type: string): TestNode { return { type, props: {}, parent: null, children: [], text: '' } }
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

test('projection rejects cross-owner chronology, forged trades and invalid terminal while allowing prior-window entry',()=>{
  const bad=[(p:ReturnType<typeof payload>)=>{p.ordinary.segment_ids=['a','b','b'];p.ordinary.dates=['2026-01-03','2026-01-01','2026-01-02']},
    (p:ReturnType<typeof payload>)=>{p.ordinary.trades[0]!.segment_id='missing'},
    (p:ReturnType<typeof payload>)=>{p.ordinary.segment_ids=['a','b','a']},
    (p:ReturnType<typeof payload>)=>{p.segment_count=0},
    (p:ReturnType<typeof payload>)=>{p.ordinary.trades[0]!.sellDate='2026-01-02'},
    (p:ReturnType<typeof payload>)=>{p.ordinary.trades[0]!.buyDate='2026-01-01T12:00:00Z'}]
  for(const mutate of bad){const p=payload();mutate(p);assert.throws(()=>normalizePagePerformance(p,'trend'),/page_performance/)}
  const good=payload();good.ordinary.trades[0]!.buyDate='2025-12-30';assert.ok(normalizePagePerformance(good,'trend'))
})

test('full-history page curve accepts 200000 points and preserves owner breaks', () => {
 const parsed = normalizePagePerformance(payload(), 'trend')!
 const size = 200000
 const full = {...parsed.ordinary!, equity: Array.from({length:size}, (_,i) => String(i % 7 - 3)), segment_ids: Array.from({length:size}, (_,i) => i < size / 2 ? 'first' : 'second')}
 const parts = pagePerformancePlot(full)
 assert.equal(parts.length, 2)
 assert.equal(parts.map(part => part.trim().split(' ').length).reduce((a,b) => a+b, 0), size)
 assert.match(parts[0]!, /^0,140 /)
 assert.ok(parts[1]!.includes('712,'))
})
