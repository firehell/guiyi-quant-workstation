import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFileSync } from 'node:fs'
import { compileScript, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import { createRenderer, h, nextTick } from 'vue'

const vueUrl = import.meta.resolve('vue')
const apiUrl = `data:text/javascript;base64,${Buffer.from(`
export const pending=[];
const meta=(product)=>({run_id:product.repeat(64),product,scenario:'baseline',status:'COMPLETED'});
export function getNewSubingProfiles(){return Promise.resolve({strategy_code:'new_subing_v1',profiles:[]})}
export function getNewSubingRuns(){return Promise.resolve({runs:[meta('AL'),meta('RB')]})}
export function getNewSubingRun(id){return Promise.resolve({metadata:meta(id.startsWith('A')?'AL':'RB'),summary:{status:'COMPLETED'},diagnostics:{}})}
export function getNewSubingPage(id,kind,cursor){
  if(cursor)return new Promise(resolve=>pending.push({id,kind,cursor,resolve}));
  return Promise.resolve({items:[{reason:id.startsWith('A')?'AL-FIRST':'RB-FIRST'}],next_cursor:'more-'+id,run_id:id,sha256:id});
}
`).toString('base64')}`
const utilUrl = `data:text/javascript;base64,${Buffer.from(`export const selectionToken=(id,n)=>n+':'+id;export const decisionMatches=()=>true;export const equityPoints=()=>'';export const metricText=()=>'';export const runStateText=()=>'';`).toString('base64')}`
const shellUrl = `data:text/javascript;base64,${Buffer.from('export default {}').toString('base64')}`
const api = await import(apiUrl)

async function component() {
  const source = readFileSync(new URL('../src/pages/research/NewSubingPage.vue', import.meta.url), 'utf8')
  const compiled = compileScript(parse(source).descriptor, { id: 'new-subing-race', inlineTemplate: false })
  const code = ts.transpileModule(compiled.content, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
    .replace(/from ['"]vue['"]/g, `from '${vueUrl}'`)
    .replace(/from ['"]@\/components\/common\/PageShell.vue['"]/g, `from '${shellUrl}'`)
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
  api.pending[1].resolve({items:[{reason:'RB-NEXT'}],next_cursor:null,run_id:'R'.repeat(64),sha256:'new'})
  await settle()
  assert.equal(state.pages.decisions.items[0].reason, 'RB-NEXT')
  app.unmount()
})
