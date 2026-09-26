import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import test from 'node:test'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { compileScript, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import { createRenderer, defineComponent, h, nextTick, ref } from 'vue'

const sourceRoot = fileURLToPath(new URL('../src/', import.meta.url))
const mockUrl = `data:text/javascript;base64,${Buffer.from(`export const calls=[]; export function getNewowProductSection(request, options) { return new Promise((resolve, reject) => calls.push({request, options, resolve, reject})); }`).toString('base64')}`
const mock = await import(mockUrl)
async function component(name: string) {
  const source = readFileSync(new URL(`../src/components/market/detail/${name}.vue`, import.meta.url), 'utf8')
  const { descriptor } = parse(source)
  const compiled = compileScript(descriptor, { id: 'dual-test', inlineTemplate: true })
  const code = ts.transpileModule(compiled.content, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
    .replace(/from ['"]vue['"]/g, `from '${import.meta.resolve('vue')}'`)
    .replace(/from ['"]@\/api\/newowProduct['"]/g, `from '${mockUrl}'`)
    .replace(/from ['"]@\/([^'"]+)['"]/g, (_match, specifier: string) => {
      for (const suffix of ['', '.ts']) {
        const path = resolve(sourceRoot, `${specifier}${suffix}`)
        if (existsSync(path)) return `from '${pathToFileURL(path).href}'`
      }
      throw new Error(specifier)
    })
  return (await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)).default
}
const input = (product = 'jm') => ({ meta: { identity: { product, strategy: 'trend', frequency: '1d' }, as_of: '2026-09-26T15:00:00Z', snapshot_token: product + '-snapshot' } })
const output = () => ({ section: 'explanation', value: { decision_v2: { cdv2: {
  formula_version: 'test', as_of: '2026-09-24T07:00:00Z', total: 78, action: '参考持有', resonance: 'R4', mismatch: null, mismatch_age: -1,
  trend_bias: 'bullish', oscillation_bias: 'bullish', reference_exposure_range: '0–50%', missing_roles: ['trend_m60','oscillation_m60'], scores: {}, deductions: {}, cert_extra: 0, extra_sources: {}, volatility_pct: null,
  facts: ['trend_day','oscillation_day','trend_week','oscillation_week','trend_m60','oscillation_m60'].map(role => ({ role, state: 'hold', status: role.endsWith('m60') ? 'unavailable' : 'ready', age: role.endsWith('day') ? 0 : 2, frequency: role.endsWith('week') ? '1w' : '1d', bar_end: '2026-09-24T07:00:00Z', physical_contract: 'JM2701', reason: null })),
}, prices: null } } })

test('daily/weekly card exposes states, ages and two-period R4 scope; refresh and identity discard stale output', async () => {
  const Panel = await component('newow/NewowDecisionV2Panel')
  const response = ref(input())
  const root = element('root')
  const app = createRenderer(nodeOperations()).createApp(defineComponent({ setup: () => () => h(Panel, { response: response.value }) }))
  app.mount(root)
  assert.match(nodeText(root), /60分钟未参与/)
  assert.equal(mock.calls.length, 0)
  const button = () => findNode(root, n => n.type === 'button')!
  ;(button().props.onClick as Function)()
  assert.equal(mock.calls[0].request.snapshotToken, 'jm-snapshot')
  mock.calls[0].resolve(output())
  await nextTick(); await nextTick()
  const states = findNode(root, n => n.props['aria-label'] === '日周策略状态与信号年龄')!
  assert.match(nodeText(states), /日线趋势.*持有.*0 根日K.*周线趋势.*持有.*2 根周K/)
  assert.equal(findNodes(states, n => n.type === 'article').length, 4)
  const reasons = findNode(root, n => n.props['aria-label'] === '共振与错配依据')!
  assert.match(nodeText(reasons), /日周确认，不包含60分钟确认/)
  assert.match(nodeText(reasons), /未命中 MM1–MM4/)
  ;(button().props.onClick as Function)()
  await nextTick()
  assert.doesNotMatch(nodeText(root), /78 分/)
  mock.calls[1].reject(new Error('refresh failed'))
  await nextTick(); await nextTick()
  assert.match(nodeText(root), /综合解释读取失败/)
  ;(button().props.onClick as Function)()
  response.value = input('rb')
  await nextTick()
  assert.equal(mock.calls[2].options.signal.aborted, true)
  mock.calls[2].resolve(output())
  await nextTick(); await nextTick()
  assert.doesNotMatch(nodeText(root), /78 分/)
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
