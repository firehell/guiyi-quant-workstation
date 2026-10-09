import assert from 'node:assert/strict'
import { readFileSync, existsSync } from 'node:fs'
import { resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import test from 'node:test'
import { compileScript, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import { createRenderer, defineComponent, h, nextTick } from 'vue'

const mockUrl = `data:text/javascript;base64,${Buffer.from(`
let matrix; export const calls=[]; export function setMatrix(value){matrix=value;calls.length=0;}
export async function getNewowRecordingMatrix(){return matrix;}
const point={kind:'indicator',trading_day:'2026-10-09',formula_versions:[],value:{version:'newow_bar_state_v1',bar_end:'2026-10-08T14:00:00Z',observed_at:'2026-10-08T14:13:07Z',physical_contract:'RB2701',main_state:'FLAT',availability:{status:'ready'}}};
const page=(id,window)=>({items:window.through>='2026-10-09'?[point]:[],snapshot:id,revision_id:'rev',seq:1,next_cursor:'next',window,cutoff:null,status:'READY'});
export async function getNewowRecordingRecords(id,window){calls.push({id,window:{...window}});return {signals:{...page(id,window),items:[]},states:page(id,window)};}
export async function getReferenceStreams(){return [{stream_id:'historical',recording_mode:'historical_replay',readable:true,formula_versions:[],profile_id:'historical'}];}
export async function getReferencePoints(id,kind,window,snapshot){calls.push({id,window:{...window},kind,snapshot});return page(id,window);}
`).toString('base64')}`
const mock = await import(mockUrl)
const sourceRoot = fileURLToPath(new URL('../src/', import.meta.url))
const source = readFileSync(new URL('../src/components/market/detail/newow/NewowRecordingPanel.vue', import.meta.url), 'utf8')
const { descriptor } = parse(source)
const compiled = compileScript(descriptor, { id: 'recording-test', inlineTemplate: true })
const code = ts.transpileModule(compiled.content, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
  .replace(/from ['"]vue['"]/g, `from '${import.meta.resolve('vue')}'`)
  .replace(/from ['"]@\/api\/referenceTrading['"]/g, `from '${mockUrl}'`)
  .replace(/from ['"]@\/([^'"]+)['"]/g, (_match, name: string) => {
    for (const suffix of ['', '.ts']) { const path=resolve(sourceRoot,name+suffix); if(existsSync(path)) return `from '${pathToFileURL(path).href}'` }
    throw new Error(name)
  })
const Panel = (await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)).default
interface TestNode { type: string; props: Record<string, unknown>; parent: TestNode | null; children: TestNode[]; text: string; style: Record<string,unknown> }
function element(type: string): TestNode { return { type, props: {}, parent: null, children: [], text: '', style:{}, addEventListener() {}, removeEventListener() {}, get options() { return this.children.filter(node => node.type === 'option') }, get value() { return this.props.value ?? this.text } } as TestNode }
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


async function settle() { for(let count=0;count<10;count++) await nextTick() }

test('actual night point stays visible through its saved trading day and paging keeps the same window', async t => {
  t.mock.timers.enable({ apis: ['Date'], now: Date.parse('2026-10-08T14:15:00Z') })
  const row={product:'rb',strategy:'trend',frequency:'60m',stream_id:'forward',enabled:true,status:'READY',
    latest_state_source:'observed',latest_observed_trading_day:'2026-10-09',latest_state:null}
  mock.setMatrix({items:[row],expected_count:720,configured_count:720,enabled_count:720,seeded_count:720,observed_count:180})
  const root=element('root'), app=createRenderer(nodeOperations()).createApp(defineComponent({setup:()=>()=>h(Panel,{product:'RB',strategy:'trend',frequency:'60m'})}))
  app.mount(root); await settle()
  assert.equal(mock.calls[0].window.through,'2026-10-09')
  assert.match(nodeText(root),/2026-10-08 22:00 北京时间/)
  const more=findNode(root,n=>n.type==='button' && nodeText(n).trim()==='加载更多状态')!
  ;(more.props.onClick as Function)(); await settle()
  assert.equal(mock.calls.at(-1).window.through,'2026-10-09')
  assert.equal(mock.calls.at(-1).snapshot,'forward')
  const historical=findNode(root,n=>n.type==='button' && nodeText(n).trim()==='历史回放')!
  ;(historical.props.onClick as Function)(); await settle()
  assert.equal(mock.calls.at(-1).id,'historical')
  assert.equal(mock.calls.at(-1).window.through,'2026-10-08')
  app.unmount()
})

test('daily weekly waiting and historical seeds do not infer a future trading day', async t => {
  t.mock.timers.enable({ apis: ['Date'], now: Date.parse('2026-10-08T14:15:00Z') })
  for(const frequency of ['1d','1w','60m']){
    mock.setMatrix({items:[{product:'rb',strategy:'trend',frequency,stream_id:'seeded',enabled:true,status:'READY',latest_state_source:'historical_seed',latest_observed_trading_day:frequency==='60m'?'2026-10-09':null,latest_state:null}]})
    const app=createRenderer(nodeOperations()).createApp(defineComponent({setup:()=>()=>h(Panel,{product:'RB',strategy:'trend',frequency})}))
    app.mount(element('root')); await settle()
    assert.equal(mock.calls[0].window.through,'2026-10-08')
    app.unmount()
  }
})

test('short minute props select their saved forward stream and display observed K state', async t => {
  t.mock.timers.enable({ apis: ['Date'], now: Date.parse('2026-10-08T14:15:00Z') })
  for (const frequency of ['5m', '15m', '30m']) {
    mock.setMatrix({items:[{product:'rb',strategy:'trend',frequency,stream_id:frequency,enabled:true,status:'READY',latest_state_source:'observed',latest_observed_trading_day:'2026-10-09',latest_state:null}],expected_count:1260})
    const root=element('root'), app=createRenderer(nodeOperations()).createApp(defineComponent({setup:()=>()=>h(Panel,{product:'RB',strategy:'trend',frequency})}))
    app.mount(root); await settle()
    assert.equal(mock.calls[0].id,frequency)
    assert.match(nodeText(root),/1260/)
    assert.match(nodeText(root),/2026-10-08 22:00 北京时间/)
    app.unmount()
  }
})
