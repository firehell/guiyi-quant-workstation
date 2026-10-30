import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { compileScript, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import { createRenderer, defineComponent, h, nextTick, ref } from 'vue'

const moduleUrl = (code: string) => `data:text/javascript;base64,${Buffer.from(code).toString('base64')}`
const apiUrl = moduleUrl(`export const calls=[]; export const monitorClient={records(query,signal,cursor){return new Promise((resolve,reject)=>calls.push({query,signal,cursor,resolve,reject}))},detail(id,signal){return new Promise((resolve,reject)=>calls.push({id,signal,resolve,reject}))}}`)
const api = await import(apiUrl)
const source = readFileSync(new URL('../src/components/market/detail/htdy/HtdySimnowRecords.vue', import.meta.url), 'utf8')
const compiled = compileScript(parse(source).descriptor, { id: 'simnow-record-test', inlineTemplate: true })
const code = ts.transpileModule(compiled.content, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
  .replace(/from ['"]vue['"]/g, `from '${import.meta.resolve('vue')}'`)
  .replace(/from ['"]@\/api\/simnowMonitor['"]/g, `from '${apiUrl}'`)
  .replace(/from ['"]@\/([^'"]+)['"]/g, (_m, name) => `from '${new URL('../src/' + name + '.ts', import.meta.url).href}'`)
const Component = (await import(moduleUrl(code))).default
interface Node { type: string; text: string; props: Record<string, unknown>; children: Node[]; parent: Node | null }
const node = (type: string, text = ''): Node => ({ type, text, props: {}, children: [], parent: null })
const operations = {
  patchProp(n: Node, k: string, _p: unknown, v: unknown) { n.props[k] = v },
  insert(n: Node, p: Node, anchor: Node | null = null) { n.parent = p; const i = anchor ? p.children.indexOf(anchor) : -1; if (i < 0) p.children.push(n); else p.children.splice(i, 0, n) },
  remove(n: Node) { if (n.parent) n.parent.children = n.parent.children.filter(x => x !== n); n.parent = null },
  createElement: (type: string) => node(type), createText: (text: string) => node('text', text), createComment: (text: string) => node('comment', text),
  setText(n: Node, text: string) { n.text = text }, setElementText(n: Node, text: string) { n.text = text; n.children = [] },
  parentNode: (n: Node) => n.parent, nextSibling(n: Node) { return n.parent?.children[n.parent.children.indexOf(n) + 1] ?? null },
  querySelector: () => null, setScopeId() {}, insertStaticContent: () => [node('static'), node('static')] as const,
}
const text = (n: Node): string => [n.text, ...n.children.map(text)].join(' ')
const find = (n: Node, predicate: (value: Node) => boolean): Node | undefined => predicate(n) ? n : n.children.flatMap(child => find(child, predicate) ?? []).at(0)
const bars = [{ time: '2026-10-30T07:00:00Z', physicalContract: 'JM2701', open: 1400, high: 1410, low: 1390, close: 1405, volume: 10 }]
const record = (product: string, id: string) => ({ id, kind: 'order', at: bars[0]!.time, product, contract: `${product}2701`, status: 'WORKING', label: '已受理', signal_id: 's', order_id: id, facts: {} })
const packet = (product: string, id: string, snapshot = 'one', cursor: string | null = null) => ({ version: 'simnow_monitor_v1', snapshot, items: [record(product, id)], next_cursor: cursor, available_count: cursor ? 51 : 1, coverage: 'complete' })
const settle = async () => { await new Promise(resolve => setImmediate(resolve)); await nextTick() }

test('changing product aborts in-flight reads and never accepts the old product response', async () => {
  const root = node('root'), product = ref('JM'), active = ref(true), emissions: unknown[][] = []
  const app = createRenderer(operations).createApp(defineComponent({ setup: () => () => h(Component, { product: product.value, active: active.value, bars, onRecords: (value: unknown[]) => emissions.push(value) }) }))
  try {
    app.mount(root); const first = api.calls.at(-1)
    product.value = 'RB'; await nextTick(); assert.equal(first.signal.aborted, true)
    const second = api.calls.at(-1)
    first.resolve(packet('JM', 'old')); await settle(); assert.doesNotMatch(text(root), /old/)
    second.resolve(packet('RB', 'new')); await settle(); assert.match(text(root), /RB2701/)
    active.value = false; await nextTick(); assert.deepEqual(emissions.at(-1), [])
  } finally { app.unmount() }
})

test('pagination rejects a changed snapshot and does not append execution rows', async () => {
  const root = node('root'), emissions: unknown[][] = []
  const app = createRenderer(operations).createApp(defineComponent({ setup: () => () => h(Component, { product: 'JM', active: true, bars, onRecords: (value: unknown[]) => emissions.push(value) }) }))
  try {
    app.mount(root); api.calls.at(-1).resolve(packet('JM', 'first', 'one', 'cursor')); await settle()
    const more = find(root, n => n.type === 'button' && text(n).includes('读取更多执行记录'))!
    ;(more.props.onClick as Function)(); api.calls.at(-1).resolve(packet('JM', 'second', 'changed')); await settle()
    assert.match(text(root), /未追加不一致的记录/)
    assert.doesNotMatch(text(root), /second/)
    assert.deepEqual(emissions.at(-1), [])
  } finally { app.unmount() }
})

test('rereading clears an accepted execution chain and aborts late detail responses', async () => {
  for (const acceptBeforeRefresh of [true, false]) {
    const root = node('root')
    const app = createRenderer(operations).createApp(defineComponent({ setup: () => () => h(Component, { product: 'JM', active: true, bars }) }))
    try {
      app.mount(root); api.calls.at(-1).resolve(packet('JM', 'first')); await settle()
      ;(find(root, n => n.type === 'button' && text(n).trim() === '查看执行链')!.props.onClick as Function)()
      const pendingDetail = api.calls.at(-1)
      const detail = { version: 'simnow_monitor_v1', snapshot: 'one', selected: record('JM', 'first'), chain: [{ ...record('JM', 'first'), label: 'OLD_CHAIN_FACT' }] }
      if (acceptBeforeRefresh) { pendingDetail.resolve(detail); await settle(); assert.match(text(root), /OLD_CHAIN_FACT/) }
      ;(find(root, n => n.type === 'button' && text(n).trim() === '重新读取')!.props.onClick as Function)()
      await nextTick()
      assert.equal(pendingDetail.signal.aborted, true)
      assert.equal(find(root, n => n.props['aria-label'] === 'SimNow关联执行链'), undefined)
      api.calls.at(-1).resolve(packet('JM', 'new-list', 'two')); await settle()
      if (!acceptBeforeRefresh) { pendingDetail.resolve(detail); await settle() }
      assert.doesNotMatch(text(root), /OLD_CHAIN_FACT/)
      assert.equal(find(root, n => n.props['aria-label'] === 'SimNow关联执行链'), undefined)
    } finally { app.unmount() }
  }
})
