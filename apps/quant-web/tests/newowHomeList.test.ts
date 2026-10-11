import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { resolve } from 'node:path'
import { compileScript, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import { createRenderer, defineComponent, h, nextTick, ref } from 'vue'
import { homeReferenceDisplay, homeDirectionDisplay, homePeriodDisplay, homeDeliveryNotice, type HomePeriodFact, type HomeState } from '../src/utils/newowHomeCards.ts'

const ready = (state: HomeState): HomePeriodFact => ({ status: 'ready', state, physical_contract: 'RB2701', segment_id: 's', calculation_segment_id: 'c', input_sha256: 'hash', formula_versions: ['v1'], as_of: '2026-10-09T00:00:00Z', bar_end: '2026-10-09T00:00:00Z', page_parity: true, executable: false, target: '9007199254740993.125', absorb: '2999.995' })

test('daily target/absorb follows only the ready state and uses Decimal rounding', () => {
  for (const state of ['BUILD', 'HOLD'] as const) assert.deepEqual(homeReferenceDisplay(ready(state)), { label: '目标', text: '9007199254740993.13' })
  for (const state of ['CLEAR', 'FLAT'] as const) assert.deepEqual(homeReferenceDisplay(ready(state)), { label: '吸筹', text: '3000.00' })
  assert.equal(homeReferenceDisplay({ ...ready('HOLD'), target: null }).text, '--')
  assert.equal(homeReferenceDisplay({ ...ready('HOLD'), status: 'unavailable', state: null }).text, '--')
})

test('direction is an identity-bound day/week state summary and unavailable does not become bearish', () => {
  assert.deepEqual(homeDirectionDisplay(ready('BUILD'), ready('HOLD')), { label: '日周向上', tone: 'up' })
  assert.deepEqual(homeDirectionDisplay(ready('FLAT'), ready('CLEAR')), { label: '日周向下', tone: 'down' })
  assert.equal(homeDirectionDisplay(ready('HOLD'), ready('FLAT')).label, '日周分歧')
  assert.equal(homeDirectionDisplay(ready('HOLD'), { status: 'warming', state: null }).label, '待确认')
  assert.equal(homeDirectionDisplay(ready('HOLD'), { ...ready('HOLD'), input_sha256: undefined }).label, '待确认')
  assert.equal(homePeriodDisplay({ status: 'unavailable', state: null }).tone, 'pending')
  assert.equal(homeDeliveryNotice({ card: null, failed: true, loading: false, stale: false }), '策略读取失败，可刷新重试')
})

const moduleUrl = (code: string) => `data:text/javascript;base64,${Buffer.from(code).toString('base64')}`
const apiUrl = moduleUrl('export const calls=[];export function getNewowHomeCards(products,signal){return new Promise((resolve,reject)=>calls.push({products,signal,resolve,reject}))}')
const api = await import(apiUrl)
async function loadList() {
  const iconSource = readFileSync(new URL('../src/components/market/MarketStateIcon.vue', import.meta.url), 'utf8')
  const iconCompiled = compileScript(parse(iconSource).descriptor, { id: 'home-icon-test', inlineTemplate: true })
  const iconCode = ts.transpileModule(iconCompiled.content, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText.replace(/from ['"]vue['"]/g, `from '${import.meta.resolve('vue')}'`).replace(/from ['"]@\/utils\/marketHomeIcons['"]/g, `from '${new URL('../src/utils/marketHomeIcons.ts', import.meta.url).href}'`)
  const iconUrl = moduleUrl(iconCode)
  const source = readFileSync(new URL('../src/components/market/MarketHomeStrategyCards.vue', import.meta.url), 'utf8')
  const compiled = compileScript(parse(source).descriptor, { id: 'home-list-test', inlineTemplate: true })
  const root = fileURLToPath(new URL('../src/', import.meta.url))
  const code = ts.transpileModule(compiled.content, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
    .replace(/from ['"]\.\/MarketStateIcon\.vue['"]/g, `from '${iconUrl}'`)
    .replace(/from ['"]vue['"]/g, `from '${import.meta.resolve('vue')}'`)
    .replace(/from ['"]@\/api\/newowHomeCards['"]/g, `from '${apiUrl}'`)
    .replace(/from ['"]@\/([^'"]+)['"]/g, (_m, name) => `from '${pathToFileURL(resolve(root, name + '.ts')).href}'`)
  return (await import(moduleUrl(code))).default
}
function nodeText(node: TestNode): string { return [node.text, ...node.children.map(nodeText)].join(' ').trim() }
const settle = async () => { await new Promise(resolve => setImmediate(resolve)); await nextTick() }

test('real list switches strategy, routes day/week icons and retains failure/pending notices', async () => {
  const List = await loadList(), root = element('root'), chart: unknown[] = [], sorts: unknown[] = []
  const sequence = ref(0)
  const rows = [{ symbol: 'rb', product_name: '螺纹钢', close: 3100.125, price_change_1d: .0125, actual_contract: 'RB2701', data_as_of: '2026-10-09', liveQuote: { physicalContract: 'RB2701', barEnd: '2026-10-09T00:00:00Z' } }]
  const app = createRenderer(nodeOperations()).createApp(defineComponent({ setup: () => () => h(List, { rows, authority: 'one', refreshSequence: sequence.value, liveStale: true, sort: 'default', sortDirection: 'desc', onChart: (...args: unknown[]) => chart.push(args), onSort: (value: unknown) => sorts.push(value) }) }))
  try {
    app.mount(root)
    const call = api.calls.at(-1)
    call.resolve({ schema_version: 'newow_home_cards_v1', requested_at: '2026-10-09T00:00:00Z', items: [{ product: 'rb', strategies: { trend: { '1d': ready('HOLD'), '1w': ready('BUILD') }, oscillation: { '1d': ready('FLAT'), '1w': { ...ready('CLEAR'), freshness: 'pending_update' } } } }] })
    await settle()
    assert.match(nodeText(root), /3100.13/)
    assert.match(nodeText(root), /9007199254740993.13/)
    assert.match(nodeText(root), /日周向上/)
    assert.match(nodeText(root), /断线保留最新完成报价/)
    assert.equal(findNode(root, n => n.type === 'details')?.props.open, undefined)
    const day = findNode(root, n => n.type === 'button' && String(n.props['aria-label']).includes('趋势日线'))!
    ;(day.props.onClick as Function)()
    const switcher = findNode(root, n => n.type === 'button' && nodeText(n) === '震荡')!
    ;(switcher.props.onClick as Function)(); await nextTick()
    assert.match(nodeText(root), /3000.00/)
    assert.match(nodeText(root), /日周向下/)
    assert.match(nodeText(root), /等待最新周期更新/)
    const week = findNode(root, n => n.type === 'button' && String(n.props['aria-label']).includes('震荡周线'))!
    ;(week.props.onClick as Function)()
    assert.deepEqual(chart, [['rb', 'trend', '1d'], ['rb', 'oscillation', '1w']])
    const sort = findNode(root, n => n.type === 'button' && nodeText(n).startsWith('涨跌幅'))!
    ;(sort.props.onClick as Function)(); assert.deepEqual(sorts, ['change'])
    sequence.value++; await nextTick()
    assert.match(nodeText(root), /策略刷新中，保留上次快照/)
    api.calls.at(-1).reject(Error('offline')); await settle()
    assert.match(nodeText(root), /策略刷新失败，保留上次快照/)
    assert.match(nodeText(root), /3000.00/)
    sequence.value++; await nextTick()
    const warming = { status: 'warming', state: null }, unavailable = { status: 'unavailable', state: null }
    api.calls.at(-1).resolve({ schema_version: 'newow_home_cards_v1', requested_at: '2026-10-09T00:00:00Z', items: [{ product: 'rb', strategies: { trend: { '1d': warming, '1w': unavailable }, oscillation: { '1d': warming, '1w': unavailable } } }] })
    await settle()
    assert.match(nodeText(root), /日线预热中/)
    assert.match(nodeText(root), /周线不可用/)
    assert.match(nodeText(root), /待确认/)
    assert.doesNotMatch(nodeText(root), /日周向下|策略刷新失败/)
  } finally { app.unmount() }
})

interface TestNode {
  type: string
  parent: TestNode | null
  children: TestNode[]
  props: Record<string, unknown>
  text: string
}

function element(type: string): TestNode {
  return { type, parent: null, children: [], props: {}, text: '' }
}

function findNode(node: TestNode, predicate: (candidate: TestNode) => boolean): TestNode | null {
  if (predicate(node)) return node
  for (const child of node.children) {
    const match = findNode(child, predicate)
    if (match) return match
  }
  return null
}

function nodeOperations() {
  return {
    patchProp(node: TestNode, key: string, _previous: unknown, next: unknown) { node.props[key] = next },
    insert(child: TestNode, parent: TestNode, anchor: TestNode | null = null) {
      child.parent = parent
      const index = anchor === null ? -1 : parent.children.indexOf(anchor)
      if (index < 0) parent.children.push(child)
      else parent.children.splice(index, 0, child)
    },
    remove(child: TestNode) {
      if (child.parent === null) return
      child.parent.children = child.parent.children.filter((item) => item !== child)
      child.parent = null
    },
    createElement: (type: string) => element(type),
    createText(text: string) { const node = element('#text'); node.text = text; return node },
    createComment(text: string) { const node = element('#comment'); node.text = text; return node },
    setText(node: TestNode, text: string) { node.text = text },
    setElementText(node: TestNode, text: string) { node.text = text; node.children = [] },
    parentNode: (node: TestNode) => node.parent,
    nextSibling(node: TestNode) {
      if (node.parent === null) return null
      const index = node.parent.children.indexOf(node)
      return node.parent.children[index + 1] ?? null
    },
    querySelector: () => null,
    setScopeId() {},
    insertStaticContent: () => [element('#static'), element('#static')] as const,
  }
}
