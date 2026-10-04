import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import test from 'node:test'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { compileScript, compileTemplate, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import { createRenderer, defineComponent, h, nextTick, ref } from 'vue'
import { NewowProductRequestError } from '../src/api/newowProduct.ts'

const sourceRoot = fileURLToPath(new URL('../src/', import.meta.url))
const mockUrl = `data:text/javascript;base64,${Buffer.from(`export const calls=[]; export function getNewowFusion(request, options) { return new Promise((resolve, reject) => calls.push({request, options, resolve, reject})); }`).toString('base64')}`
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
async function workspaceFusionHost(Panel: unknown, setup: () => unknown) {
  const source = readFileSync(new URL('../src/components/market/detail/newow/NewowProductWorkspace.vue', import.meta.url), 'utf8')
  const { descriptor } = parse(source)
  const actualPanelTemplate = descriptor.template!.content.match(/<NewowFusionPanel\b[^>]*\/>/)![0]
  const compiled = compileTemplate({ source: actualPanelTemplate, filename: 'WorkspaceFusionHost.vue', id: 'workspace-fusion-test' })
  assert.deepEqual(compiled.errors, [])
  const code = compiled.code.replace(/from ["']vue["']/g, `from '${import.meta.resolve('vue')}'`)
  const { render } = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)
  return defineComponent({ components: { NewowFusionPanel: Panel }, setup: () => ({ ...(setup() as object), recoverFusionSnapshotConflict: () => {} }), render })
}
const input = (product = 'jm') => ({ meta: { identity: { product, strategy: 'trend', frequency: '1d' }, as_of: '2026-09-26T15:00:00Z', snapshot_token: product + '-snapshot' }, value: { performance_since: '2023-01-01', performance_through: '2026-09-24', reference_input_sha256: product, reference_cutoff: '2026-09-24T07:00:00Z', history_coverage: 'FULL' } })
const output = (version: string, product = 'rb') => ({ reference_model_version: version, reference_input_sha256: product, performance_since: '2023-01-01', performance_through: '2026-09-24', reference_cutoff: '2026-09-24T07:00:00Z', records_truncated: false, groups: ['trend','oscillation','fusion'].map(model => ({ model, closed_count: 0, sum_return_percentage_points: null, open_count: 0, interrupted_count: 0 })), items: [] })

test('fusion generation conflict requests one parent recovery while busy and stale errors do not', async () => {
  const Panel = await component('newow/NewowFusionPanel'), root = element('root'), base = mock.calls.length
  const response = ref(input('pl'))
  const conflicts: string[] = []
  const app = createRenderer(nodeOperations()).createApp(defineComponent({ setup: () => () => h(Panel, {
    response: response.value, onSnapshotConflict: (token: string) => conflicts.push(token),
  }) }))
  app.mount(root)
  mock.calls[base].reject(new NewowProductRequestError('NEWOW_SNAPSHOT_GENERATION_CONFLICT', 'conflict'))
  await nextTick(); await nextTick()
  assert.deepEqual(conflicts, ['pl-snapshot'])
  assert.equal(mock.calls.length, base + 1, 'panel must not retry with its stale token')
  response.value = input('rb'); await nextTick()
  mock.calls[base + 1].reject(new NewowProductRequestError('NEWOW_SOURCE_BUSY', 'busy'))
  await nextTick(); await nextTick()
  assert.deepEqual(conflicts, ['pl-snapshot'], '429 must not rebuild')
  response.value = input('cu'); await nextTick()
  response.value = input('ag'); await nextTick()
  mock.calls[base + 2].reject(new NewowProductRequestError('NEWOW_SNAPSHOT_GENERATION_CONFLICT', 'conflict'))
  await nextTick(); await nextTick()
  assert.deepEqual(conflicts, ['pl-snapshot'], 'superseded request cannot recover old identity')
  app.unmount()
})

test('fusion entry loads automatically and drops late results after identity change/unmount', async () => {
  const Panel = await component('newow/NewowFusionPanel')
  const base = mock.calls.length
  const response = ref(input())
  const root = element('root')
  const app = createRenderer(nodeOperations()).createApp(defineComponent({ setup: () => () => h(Panel, { response: response.value }) }))
  app.mount(root)
  assert.equal(mock.calls.length, base + 1)
  assert.equal(mock.calls[base].request.identity.strategy, 'trend')
  assert.equal(mock.calls[base].request.snapshotToken, 'jm-snapshot')
  response.value = input('rb')
  await nextTick()
  assert.equal(mock.calls[base].options.signal.aborted, true)
  assert.equal(mock.calls.length, base + 2)
  mock.calls[base].resolve(output('old-result'))
  await nextTick(); await nextTick()
  assert.doesNotMatch(nodeText(root), /old-result/)
  mock.calls[base + 1].resolve(output('current-result'))
  await nextTick(); await nextTick()
  assert.match(nodeText(root), /current-result/)
  assert.match(nodeText(root), /趋势.*震荡.*融合/)
  assert.ok(findNode(root, n => n.type === 'details' && n.props.open === undefined))
  response.value = input('cu')
  await nextTick()
  assert.doesNotMatch(nodeText(root), /current-result/)
  mock.calls[base + 2].resolve(output('changed-input', 'wrong'))
  await nextTick(); await nextTick()
  assert.match(nodeText(root), /融合输入已变化/)
  assert.doesNotMatch(nodeText(root), /changed-input/)
  response.value = input('al')
  await nextTick()
  app.unmount()
  assert.equal(mock.calls[base + 3].options.signal.aborted, true)
  mock.calls[base + 3].resolve(output('unmounted'))
})

test('dual tab replaces main rise and emits a presentation identity preserving period', async () => {
  const Nav = await component('MarketDetailViewNav')
  const root = element('root')
  let selected: unknown
  let aiRequests = 0
  const identity = { view: 'newow', symbol: 'jm', strategy: 'oscillation', seriesKind: 'actual_dominant', frequency: '1w' }
  const app = createRenderer(nodeOperations()).createApp(defineComponent({ setup: () => () => h(Nav, { identity, restore: { newow: { strategy: 'trend', frequency: '1d' } }, newowFrequencies: ['1d','1w'], onSelect: (v: unknown) => { selected = v }, onAiAnalysis: () => { aiRequests++ } }) }))
  app.mount(root)
  const dual = findNode(root, n => n.type === 'button' && nodeText(n).trim() === '双策略')!
  assert.ok(dual)
  assert.doesNotMatch(nodeText(root), /主升浪/)
  const labels = findNodes(root, n => n.type === 'button').map(n => nodeText(n).trim())
  assert.deepEqual(labels.slice(0, 5), ['震荡策略', '趋势策略', '双策略', '✨AI分析', '火天大有'])
  ;(findNode(root, n => n.type === 'button' && nodeText(n).trim() === '✨AI分析')!.props.onClick as Function)()
  assert.equal(aiRequests, 1)
  assert.equal(selected, undefined)
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

test('fusion curve uses closed members, range does not replace recent records, truncated source fails closed', async () => {
  const Panel = await component('newow/NewowFusionPanel')
  const root = element('root')
  const base = mock.calls.length
  const app = createRenderer(nodeOperations()).createApp(defineComponent({ setup: () => () => h(Panel, { response: input() }) }))
  app.mount(root)
  const trade = (id: string, entry: string, exit: string | null, status = 'CLOSED', value: string | null = '2.5') => ({ reference_trade_id: id, entry_source: 'trend', exit_source: exit ? 'oscillation' : null, entry_bar_end: `${entry}T07:00:00Z`, exit_bar_end: exit ? `${exit}T07:00:00Z` : null, physical_contract: 'JM2701', entry_reference_price: '100', exit_reference_price: exit ? '102.5' : null, status, reference_return_pct: value, mark_change_pct: status === 'OPEN' ? '-4.5' : null, statistics_membership: 'entry_in_window_v1' })
  const data = { ...output('fixture', 'jm'), groups: [{ model: 'fusion', closed_count: 3, sum_return_percentage_points: '7.5', open_count: 1, interrupted_count: 1 }], items: [trade('open','2026-09-11',null,'OPEN',null), trade('recent','2026-09-08','2026-09-09'), trade('roll','2026-08-06','2026-08-18','ROLLOVER_INTERRUPTED',null), trade('within-year','2026-03-13','2026-04-03'),trade('old','2023-01-01','2023-01-10')] }
  mock.calls[base].resolve(data)
  await nextTick(); await nextTick()
  assert.match(nodeText(root), /策略收益率走势.*回测操盘提醒/)
  assert.equal(findNodes(root, n => n.type === 'circle').length, 3)
  assert.ok(findNode(root,n => n.props.id === 'fusion-trade-open'))
  assert.ok(findNode(root,n => n.props.id === 'fusion-trade-roll'))
  assert.ok(findNode(root,n => n.props.id === 'fusion-trade-within-year'))
  assert.equal(findNode(root,n => n.props.id === 'fusion-trade-old'), undefined)
  assert.match(nodeText(root), /趋势来源.*震荡来源/)
  const threeMonths = findNode(root,n => n.type === 'button' && nodeText(n).trim() === '近3月')!
  ;(threeMonths.props.onClick as Function)()
  await nextTick()
  assert.equal(findNodes(root,n => n.type === 'circle').length,1)
  assert.ok(findNode(root,n => n.props.id === 'fusion-trade-within-year'))
  assert.ok(findNode(root,n => n.props.id === 'fusion-trade-open'))
  assert.ok(findNode(root,n => n.props.id === 'fusion-trade-roll'))
  assert.match(nodeText(root), /\+2.5%/)
  const reload = findNode(root,n => n.type === 'button' && nodeText(n).trim() === '重新计算')!
  ;(reload.props.onClick as Function)()
  await nextTick()
  mock.calls[base + 1].resolve({ ...data, records_truncated:true })
  await nextTick(); await nextTick()
  assert.equal(findNodes(root,n => n.type === 'circle').length,0)
  assert.match(nodeText(root), /记录已截断/)
  app.unmount()
})

test('fusion theory is independent and the ordinary record price remains visible', async () => {
  const Panel = await component('newow/NewowFusionPanel'), root = element('root'), base = mock.calls.length
  const app = createRenderer(nodeOperations()).createApp(defineComponent({ setup: () => () => h(Panel, { response: input('rb') }) }))
  app.mount(root)
  const trade = {reference_trade_id:'theory-trade',status:'CLOSED',statistics_membership:'entry_in_window_v1',entry_source:'trend',exit_source:'oscillation',physical_contract:'RB2610',entry_reference_price:'100',exit_reference_price:'105',reference_return_pct:'5',mark_change_pct:null,entry_trading_day:'2026-09-01',exit_trading_day:'2026-09-02',entry_bar_end:'2026-09-01T07:00:00Z',exit_bar_end:'2026-09-02T07:00:00Z'}
  mock.calls[base].resolve({...output('theory-test'),curve:[trade],items:[trade],groups:[{model:'fusion',closed_count:1,sum_return_percentage_points:'5',open_count:0,interrupted_count:0}],theoretical:{model_version:'newow_dual_fusion_hindsight_peak_high_v1',hindsight:true,executable:false,returns:[{reference_trade_id:'theory-trade',return_pct:'20',ideal_exit_price:'120'}],sum_return_percentage_points:'20'}})
  await nextTick();await nextTick()
  const theory = findNode(root,n=>n.type==='button'&&nodeText(n).trim()==='理论值')!
  assert.ok(theory)
  ;(theory.props.onClick as Function)()
  await nextTick()
  assert.match(nodeText(root), /持有阶段最高价/)
  assert.match(nodeText(root), /\+20%/)
  const record = findNode(root,n=>n.props.id==='fusion-trade-theory-trade')!
  assert.match(nodeText(record), /105/)
  assert.doesNotMatch(nodeText(record), /120/)
  app.unmount()
})

test('missing fusion theory allows returning to ordinary mode; holding readouts keep closed summary separate', async () => {
  const Panel = await component('newow/NewowFusionPanel'), root = element('root'), base = mock.calls.length
  const app = createRenderer(nodeOperations()).createApp(defineComponent({setup:()=>()=>h(Panel,{response:input('rb')})}))
  app.mount(root)
  const trade = {reference_trade_id:'readout',status:'CLOSED',statistics_membership:'entry_in_window_v1',entry_source:'trend',exit_source:'oscillation',physical_contract:'RB2610',entry_reference_price:'100',exit_reference_price:'105',reference_return_pct:'5',mark_change_pct:null,entry_trading_day:'2026-09-01',exit_trading_day:'2026-09-02',entry_bar_end:'2026-09-01T07:00:00Z',exit_bar_end:'2026-09-02T07:00:00Z'}
  mock.calls[base].resolve({...output('holding-test'),curve:[trade],items:[trade],groups:[{model:'fusion',closed_count:1,sum_return_percentage_points:'5',open_count:0,interrupted_count:0}],theoretical:null,holding_curve:{model_version:'newow_reference_marked_curve_v1',page_parity:true,executable:false,points:[{bar_end:'2026-09-01T07:00:00Z',trading_day:'2026-09-01',physical_contract:'RB2610',segment_id:'a',calculation_segment_id:'a',entry_trading_day:'2026-09-01',closed_return_percentage_points:'0',floating_return_pct:'20',marked_return_percentage_points:'20',reference_trade_id:'readout',status:'HOLDING'}]}})
  await nextTick();await nextTick()
  const holding = findNode(root,n=>n.props['aria-label']==='逐 Bar 持有过程')!
  assert.match(nodeText(holding), /浮动 \+20%/)
  assert.match(nodeText(root), /累计收益 \+5%/)
  ;(findNode(root,n=>n.type==='button'&&nodeText(n).trim()==='理论值')!.props.onClick as Function)()
  await nextTick()
  assert.match(nodeText(root), /理论值所需的完整持有区段暂不可用/)
  const ordinary = findNode(root,n=>n.type==='button'&&nodeText(n).trim()==='全部')!
  assert.equal(ordinary.props.disabled,false)
  ;(ordinary.props.onClick as Function)()
  await nextTick()
  assert.match(nodeText(root), /浮动 \+20%/)
  app.unmount()
})


test('fusion admission waits initially but preserves appended records across same-identity comparison reloads', async () => {
  const Panel = await component('newow/NewowFusionPanel'), root = element('root'), base = mock.calls.length
  const response = ref(input('j')), readyToLoad = ref(false)
  const Host = await workspaceFusionHost(Panel, () => ({ dualMode: true, referenceResponse: response, identityKey: 'j:1d', comparison: { referenceSettled: readyToLoad } }))
  const app = createRenderer(nodeOperations()).createApp(Host)
  app.mount(root)
  assert.equal(mock.calls.length, base)
  assert.match(nodeText(root), /正在读取另一策略参考输入/)
  assert.equal(findNode(root, n => n.type === 'button' && n.props.class === 'fusion-refresh')?.props.disabled, true)
  readyToLoad.value = true; await nextTick()
  assert.equal(mock.calls.length, base + 1)
  const trade = id => ({ reference_trade_id: id, entry_source: 'trend', exit_source: null, physical_contract: 'J2701',
    entry_bar_end: '2026-09-01T07:00:00Z', entry_reference_price: '100', exit_bar_end: null, exit_reference_price: null,
    status: 'OPEN', statistics_membership: 'entry_in_window_v1', reference_return_pct: null, mark_change_pct: null })
  const first = { ...output('admission', 'j'), reference_revision: 'same-revision', items: [trade('first')], next_cursor: 'older' }
  mock.calls[base].resolve(first); await nextTick(); await nextTick()
  readyToLoad.value = false; await nextTick()
  const more = findNode(root, n => n.type === 'button' && nodeText(n).trim() === '加载更多近一年记录')!
  assert.equal(more.props.disabled, true)
  ;(more.props.onClick as Function)()
  ;(findNode(root, n => n.type === 'button' && n.props.class === 'fusion-refresh')!.props.onClick as Function)()
  await nextTick()
  assert.equal(mock.calls.length, base + 1, 'pending comparison cannot initiate pagination or recomputation')
  assert.ok(findNode(root, n => n.props.id === 'fusion-trade-first'))
  readyToLoad.value = true; await nextTick()
  ;(more.props.onClick as Function)()
  await nextTick()
  assert.equal(mock.calls[base + 1].request.fusionBefore, 'older')
  readyToLoad.value = false; await nextTick()
  assert.equal(mock.calls[base + 1].options.signal.aborted, false)
  mock.calls[base + 1].resolve({ ...first, items: [trade('appended')], next_cursor: null })
  await nextTick(); await nextTick()
  assert.ok(findNode(root, n => n.props.id === 'fusion-trade-first'))
  assert.ok(findNode(root, n => n.props.id === 'fusion-trade-appended'))
  response.value = { ...response.value, meta: { ...response.value.meta } }
  readyToLoad.value = true; await nextTick(); await nextTick()
  assert.equal(mock.calls.length, base + 2, 'same primary snapshot must not reload or discard appended rows')
  assert.ok(findNode(root, n => n.props.id === 'fusion-trade-appended'))
  app.unmount()
})

test('new fusion identity clears and aborts old input, waits for admission, and does not retry rejected input', async () => {
  const Panel = await component('newow/NewowFusionPanel'), root = element('root'), base = mock.calls.length
  const response = ref(input('j')), readyToLoad = ref(true)
  const app = createRenderer(nodeOperations()).createApp(defineComponent({ setup: () => () => h(Panel, { response: response.value, readyToLoad: readyToLoad.value }) }))
  app.mount(root)
  readyToLoad.value = false
  response.value = input('hc')
  await nextTick()
  assert.equal(mock.calls[base].options.signal.aborted, true)
  assert.equal(mock.calls.length, base + 1)
  mock.calls[base].resolve(output('stale-j', 'j')); await nextTick(); await nextTick()
  assert.doesNotMatch(nodeText(root), /stale-j/)
  readyToLoad.value = true; await nextTick()
  assert.equal(mock.calls.length, base + 2)
  assert.equal(mock.calls[base + 1].request.identity.product, 'hc')
  mock.calls[base + 1].resolve(output('wrong-source', 'j')); await nextTick(); await nextTick()
  assert.match(nodeText(root), /融合输入已变化/)
  readyToLoad.value = false; await nextTick()
  readyToLoad.value = true; await nextTick()
  assert.equal(mock.calls.length, base + 2, 'readiness recovery is not an automatic retry')
  app.unmount()
})


test('minute fusion curve location labels only records outside the past year', async () => {
  const Panel = await component('newow/NewowFusionPanel'), root = element('root'), base = mock.calls.length
  const response = { ...input('ag'), meta: { ...input('ag').meta, identity: { product: 'ag', strategy: 'trend', frequency: '5m' } } }
  const app = createRenderer(nodeOperations()).createApp(defineComponent({ setup: () => () => h(Panel, { response }) }))
  const originalDocument = Object.getOwnPropertyDescriptor(globalThis, 'document')
  Object.defineProperty(globalThis, 'document', { configurable: true, value: { getElementById: () => null } })
  try {
    app.mount(root)
    const trade = (id: string, entry: string, exit: string, exitDay?: string) => ({ reference_trade_id: id, status: 'CLOSED', statistics_membership: 'entry_in_window_v1', entry_source: 'trend', exit_source: 'oscillation', physical_contract: 'AG2612', entry_reference_price: '100', exit_reference_price: '105', reference_return_pct: '5', mark_change_pct: null, entry_bar_end: entry, exit_bar_end: exit, ...(exitDay ? { exit_trading_day: exitDay } : {}) })
    const rows = [
      trade('recent', '2026-09-24T06:50:00Z', '2026-09-24T06:55:00Z', '2026-09-24'),
      trade('old', '2025-09-22T06:50:00Z', '2025-09-23T06:55:00Z', '2025-09-23'),
      trade('beijing-boundary', '2025-09-23T16:50:00Z', '2025-09-23T17:00:00Z'),
    ]
    mock.calls[base].resolve({ ...output('minute-location', 'ag'), curve: rows, items: rows, groups: [{ model: 'fusion', closed_count: 3, sum_return_percentage_points: '15', open_count: 0, interrupted_count: 0 }] })
    await nextTick(); await nextTick()
    for (const [id, date, outside] of [['recent', '09-24 14:55', false], ['old', '2025-09-23', true], ['beijing-boundary', '2025-09-24', false]] as const) {
      const point = findNode(root, n => n.type === 'circle' && String(n.props['aria-label']).includes(date))!
      assert.ok(point, `curve point ${id} must be selectable`)
      await (point.props.onClick as Function)({ stopPropagation() {} })
      await nextTick()
      const record = findNode(root, n => n.props.id === `fusion-trade-${id}`)!
      assert.ok(record, `located record ${id} must be visible`)
      assert.equal(nodeText(record).includes('曲线定位 · 近一年外'), outside, id)
    }
  } finally {
    app.unmount()
    if (originalDocument) Object.defineProperty(globalThis, 'document', originalDocument)
    else Reflect.deleteProperty(globalThis, 'document')
  }
})
