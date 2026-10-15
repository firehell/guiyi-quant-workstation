import { compileCurveComponent } from './helpers/compileCurveComponent.ts'
import assert from 'node:assert/strict'
import test from 'node:test'
import { newowSimpleDualLabel, newowReferencePrice, newowReferencePercent } from '../src/utils/newowPagePresentation.ts'
import {createRenderer,defineComponent,h,nextTick,ref} from 'vue'
async function component() {
 return (await import(await compileCurveComponent(new URL('../src/components/market/detail/newow/NewowPagePerformancePanel.vue',import.meta.url)))).default
}

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



test('page records show latest three, expand and collapse, reset mode/window without changing prices',async()=>{
 const Panel=await component(),root=element('root')
 const trades=Array.from({length:5},(_,i)=>({segment_id:'s',buyDate:`2026-09-0${i+1}`,sellDate:`2026-09-1${i+1}`,buyPrice:'3100.123456',sellPrice:'3200',pct:'3.22',forceClose:false}))
 const model={trades,dates:['2026-09-01','2026-09-30'],segment_ids:['s','s'],equity:['0','3.22'],trading_days:['2026-09-01','2026-09-30'],summary:{cumReturn:'16.10',accuracy:'100',maxDrawdown:'0',tradeCount:5}}
 const value=ref({strategy:'trend',ordinary:model,ideal:{...model,trades:trades.slice(0,4)},ordinary_interrupted_count:0,ideal_open_count:0})
 const app=createRenderer(nodeOperations()).createApp(defineComponent({setup:()=>()=>h(Panel,{value:value.value,since:'2025-09-30',through:'2026-09-30'})}));app.mount(root);await nextTick()
 const cards=()=>findNodes(root,n=>n.type==='article')
 assert.equal(cards().length,3);assert.match(nodeText(cards()[0]),/09-05.*3100.12.*3200.00/)
 assert.equal(findNodes(cards()[0],n=>n.type==='time')[0]?.props.datetime,'2026-09-05')
 const more=()=>findNode(root,n=>n.type==='button'&&nodeText(n).includes('加载更多'))!
 ;(more().props.onClick as Function)();await nextTick();assert.equal(cards().length,5)
 const collapse=findNode(root,n=>n.type==='button'&&nodeText(n)==='收起')!
 ;(collapse.props.onClick as Function)();await nextTick();assert.equal(cards().length,3)
 ;(more().props.onClick as Function)();await nextTick()
 const ideal=findNode(root,n=>n.type==='button'&&nodeText(n)==='理论值')!
 ;(ideal.props.onClick as Function)();await nextTick();assert.equal(cards().length,3)
 ;(more().props.onClick as Function)();await nextTick();assert.equal(cards().length,4)
 value.value={...value.value};await nextTick();assert.equal(cards().length,3)
 assert.equal(trades[0].buyPrice,'3100.123456');assert.equal(model.summary.cumReturn,'16.10')
 app.unmount()
})

test('multi-owner page header shows aggregate annualization and follows mode and loaded window', async () => {
 const Panel=await component(),root=element('root')
 const model={period:'day',trades:[],dates:['2024-01-01','2024-12-31','2025-01-01','2026-01-01'],segment_ids:['a','a','b','b'],equity:['0','10','10','32'],trading_days:['2024-01-01','2024-12-31','2025-01-01','2026-01-01'],summary:{cumReturn:'32',accuracy:0,maxDrawdown:'0',tradeCount:0}}
 const value=ref({strategy:'trend',ordinary:model,ideal:{...model,equity:['0','10','10','100']},ordinary_interrupted_count:0,ideal_open_count:0})
 const app=createRenderer(nodeOperations()).createApp(defineComponent({setup:()=>()=>h(Panel,{value:value.value})}));app.mount(root);await nextTick()
 const heading=()=>findNode(root,n=>n.props.class==='newow-reference__annualized')!
 assert.match(nodeText(heading()),/页面参考年化 14\.87%.*2个合约段汇总/)
 assert.match(nodeText(root),/各合约段年化/)
 const toggle=findNode(root,n=>n.type==='button'&&nodeText(n)==='理论值')!
 ;(toggle.props.onClick as Function)();await nextTick()
 assert.match(nodeText(heading()),/41\.35%/)
 value.value={...value.value,ideal:{...model,dates:['2025-01-01','2026-01-01'],trading_days:['2025-01-01','2026-01-01'],segment_ids:['b','b'],equity:['0','21']}};await nextTick()
 assert.match(nodeText(heading()),/21\.00%/)
 assert.doesNotMatch(nodeText(heading()),/合约段汇总/)
 assert.deepEqual(model.equity,['0','10','10','32'])
 app.unmount()
})

test('simple dual labels retain the reference price and Decimal display preserves precision',()=>{
 assert.equal(newowSimpleDualLabel('trend',false,'3100.123456'),'建仓 3100.12')
 assert.equal(newowSimpleDualLabel('oscillation',true,'3200'),'清仓 3200.00')
 assert.equal(newowReferencePrice('9007199254740993.125'),'9007199254740993.13')
 assert.equal(newowReferencePrice(null),'—')
 assert.equal(newowReferencePercent('1.4'),'+1.40%')
 assert.equal(newowReferencePercent('0'),'0.00%')
})
