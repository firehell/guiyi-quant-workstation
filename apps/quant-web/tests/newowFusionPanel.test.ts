import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import test from 'node:test'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { compileScript, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import { createRenderer, defineComponent, h, nextTick, ref } from 'vue'

const sourceRoot = fileURLToPath(new URL('../src/', import.meta.url))
const mockUrl = `data:text/javascript;base64,${Buffer.from(`export const calls=[]; export function getNewowFusion(request, options) { return new Promise(resolve => calls.push({request, options, resolve})); }`).toString('base64')}`
const mock = await import(mockUrl)
async function component(name: string) {
  const source = readFileSync(new URL(`../src/components/market/detail/${name}.vue`, import.meta.url), 'utf8')
  const { descriptor } = parse(source)
  const compiled = compileScript(descriptor, { id: 'dual-test', inlineTemplate: true })
  const code = ts.transpileModule(compiled.content, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
    .replace(/from ['"]vue['"]/g, `from '${import.meta.resolve('vue')}'`)
    .replace(/from ['"]@\/api\/newowFusion['"]/g, `from '${mockUrl}'`)
    .replace(/from ['"]@\/([^'"]+)['"]/g, (_match, specifier: string) => {
      for (const suffix of ['', '.ts']) {
        const path = resolve(sourceRoot, `${specifier}${suffix}`)
        if (existsSync(path)) return `from '${pathToFileURL(path).href}'`
      }
      throw new Error(specifier)
    })
  return (await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)).default
}
const input = (product = 'jm') => ({ meta: { identity: { product, strategy: 'trend', frequency: '1d' }, as_of: '2026-09-26T15:00:00Z', snapshot_token: product + '-snapshot' }, value: { performance_since: '2023-01-01', performance_through: '2026-09-24', reference_input_sha256: product, reference_cutoff: '2026-09-24T07:00:00Z', history_coverage: 'FULL' } })
const output = (version: string, product = 'rb') => ({ reference_model_version: version, reference_input_sha256: product, performance_since: '2023-01-01', performance_through: '2026-09-24', reference_cutoff: '2026-09-24T07:00:00Z', records_truncated: false, groups: ['trend','oscillation','fusion'].map(model => ({ model, closed_count: 0, sum_return_percentage_points: null, open_count: 0, interrupted_count: 0 })), items: [] })

test('fusion entry loads automatically and drops late results after identity change/unmount', async () => {
  const Panel = await component('newow/NewowFusionPanel')
  const response = ref(input())
  const root = element('root')
  const app = createRenderer(nodeOperations()).createApp(defineComponent({ setup: () => () => h(Panel, { response: response.value }) }))
  app.mount(root)
  assert.equal(mock.calls.length, 1)
  assert.equal(mock.calls[0].request.identity.strategy, 'trend')
  assert.equal(mock.calls[0].request.snapshotToken, 'jm-snapshot')
  response.value = input('rb')
  await nextTick()
  assert.equal(mock.calls[0].options.signal.aborted, true)
  assert.equal(mock.calls.length, 2)
  mock.calls[0].resolve(output('old-result'))
  await nextTick(); await nextTick()
  assert.doesNotMatch(nodeText(root), /old-result/)
  mock.calls[1].resolve(output('current-result'))
  await nextTick(); await nextTick()
  assert.match(nodeText(root), /current-result/)
  assert.match(nodeText(root), /趋势.*震荡.*融合/)
  assert.ok(findNode(root, n => n.type === 'details' && n.props.open !== undefined))
  response.value = input('cu')
  await nextTick()
  assert.doesNotMatch(nodeText(root), /current-result/)
  mock.calls[2].resolve(output('changed-input', 'wrong'))
  await nextTick(); await nextTick()
  assert.match(nodeText(root), /融合输入已变化/)
  assert.doesNotMatch(nodeText(root), /changed-input/)
  response.value = input('al')
  await nextTick()
  app.unmount()
  assert.equal(mock.calls[3].options.signal.aborted, true)
  mock.calls[3].resolve(output('unmounted'))
})

test('dual tab replaces main rise and emits a presentation identity preserving period', async () => {
  const Nav = await component('MarketDetailViewNav')
  const root = element('root')
  let selected: unknown
  const identity = { view: 'newow', symbol: 'jm', strategy: 'oscillation', seriesKind: 'actual_dominant', frequency: '1w' }
  const app = createRenderer(nodeOperations()).createApp(defineComponent({ setup: () => () => h(Nav, { identity, restore: { newow: { strategy: 'trend', frequency: '1d' } }, newowFrequencies: ['1d','1w'], onSelect: (v: unknown) => { selected = v } }) }))
  app.mount(root)
  const dual = findNode(root, n => n.type === 'button' && nodeText(n).trim() === '双策略')!
  assert.ok(dual)
  assert.doesNotMatch(nodeText(root), /主升浪/)
  ;(dual.props.onClick as Function)()
  assert.deepEqual(selected, { ...identity, strategy: 'trend', newowMode: 'dual' })
  app.unmount()
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
