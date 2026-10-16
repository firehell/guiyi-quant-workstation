import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFileSync } from 'node:fs'
import { compileScript, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import { createRenderer, h, nextTick } from 'vue'

const vueUrl = import.meta.resolve('vue')
const apiUrl = `data:text/javascript;base64,${Buffer.from(`
export const pending=[]; export const reads=[];
const meta=(product,cash='100000')=>({run_id:(product+cash).repeat(64).slice(0,64),product,scenario:'baseline',status:'COMPLETED',strategy_code:'new_subing_v2',initial_cash:cash});
export function getNewSubingEquityCurve(id){return Promise.resolve({run_id:id,sha256:id,items:[],total:0,sampled:false,status:'COMPLETED',since:'2026-01-01',through:'2026-10-01',sampling_version:'exact_extrema_boundaries_v1'})}
export function getNewSubingProfiles(){return Promise.resolve({strategy_code:'new_subing_v1',profiles:[]})}
export function getNewSubingRuns(){return Promise.resolve({runs:[meta('AL'),meta('RB'),meta('AL','1000000')]})}
export function getNewSubingRun(id){return Promise.resolve({sha256:id,metadata:meta(id.startsWith('R')?'RB':'AL',id.includes('1000000')?'1000000':'100000'),summary:{status:'COMPLETED'},diagnostics:{}})}
export function getNewSubingPage(id,kind,cursor,options){
  reads.push({id,kind,cursor,signal:options?.signal});
  if(cursor)return new Promise(resolve=>pending.push({id,kind,cursor,resolve}));
  return Promise.resolve({items:[{reason:id.startsWith('A')?'AL-FIRST':'RB-FIRST'}],next_cursor:'more-'+id,run_id:id,sha256:id});
}
`).toString('base64')}`

const utilUrl = new URL('../src/utils/newSubingResearch.ts',import.meta.url).href
const shellUrl = `data:text/javascript;base64,${Buffer.from('export default {}').toString('base64')}`
const api = await import(apiUrl)

async function component() {
  const source = readFileSync(new URL('../src/pages/research/NewSubingPage.vue', import.meta.url), 'utf8')
  const compiled = compileScript(parse(source).descriptor, { id: 'new-subing-race', inlineTemplate: false })
  const code = ts.transpileModule(compiled.content, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
    .replace(/from ['"]vue['"]/g, `from '${vueUrl}'`)
    .replace(/from ['"]@\/components\/[^'"]+\.vue['"]/g, `from '${shellUrl}'`)
    .replace(/from ['"]@\/utils\/returnCurveLayout['"]/g, `from '${new URL('../src/utils/returnCurveLayout.ts',import.meta.url).href}'`)
    .replace(/from ['"]@\/api\/newSubingResearch['"]/g, `from '${apiUrl}'`)
    .replace(/from ['"]@\/utils\/newSubingResearch['"]/g, `from '${utilUrl}'`)
  return (await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)).default
}

function renderer() {
  return createRenderer({
    patchProp() {}, insert() {}, remove() {},
    createElement: () => ({}), createText: () => ({}), createComment: () => ({}),
    setText() {}, setElementText() {}, parentNode: () => null, nextSibling: () => null,
    querySelector: () => null, setScopeId() {}, insertStaticContent: () => [{}, {}] as const,
  })
}
async function settle() { await Promise.resolve(); await Promise.resolve(); await nextTick(); await Promise.resolve(); await nextTick() }

test('switching run during deferred pagination unlocks new run and discards old page', async () => {
  const Page = await component()
  Page.render = () => h('div')
  const app = renderer().createApp(Page)
  app.mount({})
  await settle()
  const state = (app as unknown as { _instance: { setupState: Record<string, any> } })._instance.setupState
  assert.equal(state.detail.metadata.product, 'AL')
  void state.nextPage()
  assert.equal(api.pending.length, 1)
  assert.equal(state.pageLoading, true)
  state.selectedProduct = 'RB'
  await state.selectRun()
  await settle()
  assert.equal(state.detail.metadata.product, 'RB')
  assert.equal(state.pageLoading, false)
  void state.nextPage()
  assert.equal(api.pending.length, 2)
  api.pending[0].resolve({items:[{reason:'AL-LATE'}],next_cursor:null,run_id:'A'.repeat(64),sha256:'old'})
  await settle()
  assert.equal(state.pages.decisions.items[0].reason, 'RB-FIRST')
  api.pending[1].resolve({items:[{reason:'RB-NEXT'}],next_cursor:null,run_id:api.pending[1].id,sha256:api.pending[1].id})
  await settle()
  assert.deepEqual(state.pages.decisions.items.map(row=>row.reason), ['RB-FIRST','RB-NEXT'])
  app.unmount()
})

test('capital switch discards late pagination and unlocks selected account', async () => {
  const Page = await component()
  Page.render = () => h('div')
  const app = renderer().createApp(Page)
  app.mount({})
  await settle()
  const state = (app as unknown as { _instance: { setupState: Record<string, any> } })._instance.setupState
  void state.nextPage()
  const old = api.pending.at(-1)
  state.selectedCapital = '1000000'
  await state.selectRun()
  await settle()
  assert.equal(state.detail.metadata.initial_cash, '1000000')
  assert.equal(state.pageLoading, false)
  old.resolve({items:[{reason:'OLD-CASH'}],next_cursor:null,run_id:old.id,sha256:'old'})
  await settle()
  assert.notEqual(state.pages.decisions.items[0].reason, 'OLD-CASH')
  app.unmount()
})

test('decision action selector offers core trace actions without BUILD', () => {
  const source = readFileSync(new URL('../src/pages/research/NewSubingPage.vue', import.meta.url), 'utf8')
  const descriptor = parse(source).descriptor
  const walk = (node: any): any[] => [node, ...(node.children ?? []).flatMap(walk)]
  const nodes = walk(descriptor.template!.ast)
  const selector = nodes.find(node => node.tag === 'select' && node.props?.some((prop: any) => prop.name === 'model' && prop.exp?.content === 'actionFilter'))
  assert.ok(selector, 'actionFilter select is present')
  const option = selector.children.find((node:any)=>node.tag === 'option')
  const loop = option.props.find((prop:any)=>prop.name === 'for').exp.content
  const options = JSON.parse(loop.match(/\[[^\]]+\]/)![0].replaceAll("'", '"'))
  assert.deepEqual(options, ['ALL', 'SETUP', 'ADD_SETUP', 'SETUP_INVALIDATED', 'OPEN', 'ADD', 'REDUCE', 'REDUCE_SKIPPED', 'CLEAR', 'CANCEL', 'REJECT', 'INTERRUPTED'])
  assert.ok(!options.includes('BUILD'))
})

test('metric cards wrap exact fallback values rather than clipping them', () => {
  const source = readFileSync(new URL('../src/pages/research/NewSubingPage.vue', import.meta.url), 'utf8')
  assert.match(source, /\.metrics strong\{[^}]*overflow-wrap:anywhere/)
})

 test('research loads only selected table and aborts obsolete pagination', async () => {
  api.reads.length = 0
  const Page = await component(); Page.render = () => h('div')
  const app = renderer().createApp(Page); app.mount({}); await settle()
  const state = (app as any)._instance.setupState
  assert.deepEqual(api.reads.map(row => row.kind), ['decisions'])
  void state.nextPage()
  const signal = api.reads.at(-1).signal
  state.selectedProduct = 'RB'; await state.selectRun()
  assert.equal(signal.aborted, true)
  state.pageKind = 'trades'; await settle()
  assert.ok(api.reads.some(row => row.kind === 'trades'))
  app.unmount()
})
