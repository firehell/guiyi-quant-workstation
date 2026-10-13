import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { resolve } from 'node:path'
import { compileScript, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import { createRenderer, defineComponent, h, nextTick, ref } from 'vue'
import { homeRowHints, homeCardSpace, homeControlLabel, homePagePerformance, homeCompositeDisplay, homeTrendDisplay, homeReferenceDisplay, homeDirectionDisplay, homePeriodDisplay, homePeriodReason, homeDeliveryNotice, type HomePeriodFact, type HomeState } from '../src/utils/newowHomeCards.ts'

const ready = (state: HomeState): HomePeriodFact => ({ status: 'ready', state, physical_contract: 'RB2701', segment_id: 's', calculation_segment_id: 'c', input_sha256: 'hash', formula_versions: ['v1'], as_of: '2026-10-09T00:00:00Z', bar_end: '2026-10-09T00:00:00Z', page_parity: true, executable: false, target: '9007199254740993.125', absorb: '2999.995', display_as_of: '2026-10-11T00:00:00Z', display_projection_version: 'newow_home_display_v1', current_event: null, guard_ma10: null })

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

test('composite covers all stage pairs without changing daily reference selection', () => {
  const states: HomeState[] = ['BUILD', 'HOLD', 'CLEAR', 'FLAT']
  for (const day of states) for (const week of states) {
    const expected = day === 'CLEAR' || week === 'CLEAR' ? 'CLEAR' : week === 'BUILD' || week === 'HOLD' ? week : day === 'BUILD' || day === 'HOLD' ? day : 'FLAT'
    const value = homeCompositeDisplay(ready(day), ready(week))
    assert.equal(value.state, expected, `${day}/${week}`)
    assert.deepEqual(value.reference, homeReferenceDisplay(ready(day)))
  }
  assert.equal(homeCompositeDisplay(ready('HOLD'), { ...ready('HOLD'), display_as_of: '2026-10-11T00:00:00.000001Z' }).state, null)
  assert.equal(homeCompositeDisplay(ready('HOLD'), { ...ready('HOLD'), physical_contract: 'RB2705' }).state, null)
  assert.equal(homeCompositeDisplay(ready('HOLD'), { ...ready('HOLD'), display_projection_version: undefined }).state, null)
  assert.equal(homeTrendDisplay().label, '独立趋势来源未确认')
})

test('current events are exact-bar owned, price guarded and historical recent actions never override', () => {
  const day = { ...ready('HOLD'), reference_current: '99', guard_ma10: '100', current_event: { kind: 'BUILD' as const, bar_end: ready('HOLD').bar_end!, signal_id: 'build' } }
  assert.equal(homeCompositeDisplay(day, ready('FLAT')).state, 'HOLD')
  assert.equal(homeCompositeDisplay({ ...day, reference_current: '100' }, ready('FLAT')).state, 'BUILD')
  assert.equal(homeCompositeDisplay({ ...day, reference_current: '100', current_event: { ...day.current_event, bar_end: '2026-10-08T00:00:00Z' } }, ready('FLAT')).state, null)
  assert.equal(homeCompositeDisplay({ ...day, current_event: null, recent_action: day.current_event }, ready('FLAT')).state, 'HOLD')
  const clear = { ...day, current_event: { ...day.current_event, kind: 'CLEAR' as const }, reference_current: '101' }
  assert.equal(homeCompositeDisplay(clear, ready('HOLD')).state, 'HOLD')
  assert.equal(homeCompositeDisplay({ ...clear, reference_current: '99' }, ready('HOLD')).state, 'CLEAR')
})

test('MA10 guard preserves Decimal scientific notation, plus signs and sub-cent boundaries', () => {
  const day = { ...ready('HOLD'), reference_current: '99', current_event: { kind: 'BUILD' as const, bar_end: ready('HOLD').bar_end!, signal_id: 'build' } }
  for (const guard_ma10 of ['100', '1E+2', '+100.00', ' .1e3 ']) assert.equal(homeCompositeDisplay({ ...day, guard_ma10 }, ready('FLAT')).state, 'HOLD')
  assert.equal(homeCompositeDisplay({ ...day, reference_current: '9007199254740993.124999', guard_ma10: '9007199254740993.125' }, ready('FLAT')).state, 'HOLD')
  assert.equal(homeCompositeDisplay({ ...day, reference_current: '9007199254740993.125', guard_ma10: '9007199254740993.125' }, ready('FLAT')).state, 'BUILD')
})

test('completed D1 and W1 cutoffs can differ under one exact display owner', () => {
  const day = ready('HOLD'), week = { ...ready('FLAT'), as_of: '2026-10-02T07:00:00Z', bar_end: '2026-10-02T07:00:00Z' }
  assert.equal(homeCompositeDisplay(day, week).state, 'HOLD')
  assert.equal(homeCompositeDisplay(day, { ...week, bar_end: '2026-10-03T07:00:00Z' }).state, null)
  assert.equal(homeCompositeDisplay(day, { ...week, display_as_of: undefined }).state, null)
})

test('home supplemental facts keep daily ownership and ordinary page return', () => {
  const day = { ...ready('FLAT'), absorb_space_percent: '-1.1717085641244141457', target_space_percent: '4.1755',
    main_force_control: { status: 'ready', label: '无庄控盘', formula_version: 'newow_main_force_control_page_v1', bar_end: ready('FLAT').bar_end!, physical_contract: 'RB2701', calculation_segment_id: 'c', page_parity: true, executable: false },
    page_performance: { status: 'ready', strategy: 'trend' as const, frequency: '1d' as const, as_of: ready('FLAT').as_of!, version: 'newow_page_performance_v3379_v2', input_sha256: 'hash', source_evidence_sha256: null, cum_return_percent: '20.59', trade_count: 55, page_parity: true, executable: false },
  }
  assert.equal(homeCardSpace(day).value, day.absorb_space_percent)
  assert.equal(homeControlLabel(day), '无庄控盘')
  assert.equal(homeControlLabel({ ...day, main_force_control: { ...day.main_force_control, physical_contract: 'RB2705' } }), '控盘待确认')
  assert.equal(homePagePerformance(day, 'trend')?.cum_return_percent, '20.59')
  assert.equal(homePagePerformance(day, 'oscillation'), null)
  assert.equal(homePagePerformance({ ...day, page_performance: { ...day.page_performance, executable: true } }, 'trend'), null)
  assert.equal(homePagePerformance({ ...day, page_performance: { ...day.page_performance, status: 'warming' } }, 'trend'), null)
  assert.equal(homeCardSpace({ ...day, status: 'warming', state: null }).value, null)
})

const moduleUrl = (code: string) => `data:text/javascript;base64,${Buffer.from(code).toString('base64')}`
const apiUrl = moduleUrl('export const performanceCalls=[];export const authorityCalls=[];export function configureHomeCardAuthority(...args){authorityCalls.push(args)};export function peekNewowHomeCards(){return undefined};export function getNewowHomePerformance(product,strategy,fact,signal){return new Promise((resolve,reject)=>performanceCalls.push({product,strategy,fact,signal,resolve,reject}))};export const calls=[];export function getNewowHomeCards(products,signal){return new Promise((resolve,reject)=>calls.push({products,signal,resolve,reject}))}')
const api = await import(apiUrl)
async function loadList() {
  const iconSource = readFileSync(new URL('../src/components/market/MarketStateIcon.vue', import.meta.url), 'utf8')
  const iconCompiled = compileScript(parse(iconSource).descriptor, { id: 'home-icon-test', inlineTemplate: true })
  const iconCode = ts.transpileModule(iconCompiled.content, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText.replace(/from ['"]vue['"]/g, `from '${import.meta.resolve('vue')}'`).replace(/from ['"]@\/utils\/marketHomeIcons['"]/g, `from '${new URL('../src/utils/marketHomeIcons.ts', import.meta.url).href}'`)
  const iconUrl = moduleUrl(iconCode)
  const priceSource = readFileSync(new URL('../src/components/market/detail/newow/NewowPriceSources.vue', import.meta.url), 'utf8')
  const priceCompiled = compileScript(parse(priceSource).descriptor, { id: 'home-price-test', inlineTemplate: true })
  const priceCode = ts.transpileModule(priceCompiled.content, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText.replace(/from ['"]vue['"]/g, `from '${import.meta.resolve('vue')}'`).replace(/from ['"]@\/([^'"]+)['"]/g, (_m, name) => `from '${new URL('../src/' + name + '.ts', import.meta.url).href}'`)
  const priceUrl = moduleUrl(priceCode)
  const source = readFileSync(new URL('../src/components/market/MarketHomeStrategyCards.vue', import.meta.url), 'utf8')
  const compiled = compileScript(parse(source).descriptor, { id: 'home-list-test', inlineTemplate: true })
  const root = fileURLToPath(new URL('../src/', import.meta.url))
  const code = ts.transpileModule(compiled.content, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
    .replace(/from ['"]\.\/detail\/newow\/NewowPriceSources\.vue['"]/g, `from '${priceUrl}'`)
    .replace(/from ['"]\.\/MarketStateIcon\.vue['"]/g, `from '${iconUrl}'`)
    .replace(/from ['"]vue['"]/g, `from '${import.meta.resolve('vue')}'`)
    .replace(/from ['"]@\/api\/newowHomeCards['"]/g, `from '${apiUrl}'`)
    .replace(/from ['"]@\/([^'"]+)['"]/g, (_m, name) => `from '${pathToFileURL(resolve(root, name + '.ts')).href}'`)
  return (await import(moduleUrl(code))).default
}
function nodeText(node: TestNode): string { return [node.text, ...node.children.map(nodeText)].join(' ').trim() }
const settle = async () => { await new Promise(resolve => setImmediate(resolve)); await nextTick() }

test('rows expand and summary cards navigate with selected strategy while retaining notices', async () => {
  const List = await loadList(), root = element('root'), chart: unknown[] = [], sorts: unknown[] = []
  const sequence = ref(0)
  const rows = [{ symbol: 'rb', product_name: '螺纹钢', close: 3100.125, price_change_1d: .0125, actual_contract: 'RB2701', data_as_of: '2026-10-09', liveQuote: { physicalContract: 'RB2701', barEnd: '2026-10-09T00:00:00Z' } }]
  const app = createRenderer(nodeOperations()).createApp(defineComponent({ setup: () => () => h(List, { rows, products: ['rb'], authority: 'one', refreshSequence: sequence.value, liveStale: true, sort: 'default', sortDirection: 'desc', onChart: (...args: unknown[]) => chart.push(args), onSort: (value: unknown) => sorts.push(value) }) }))
  try {
    app.mount(root)
    assert.equal(api.authorityCalls.at(-1)?.[1], false)
    const call = api.calls.at(-1)
    call.resolve({ schema_version: 'newow_home_cards_v2', requested_at: '2026-10-09T00:00:00Z', items: [{ product: 'rb', strategies: { trend: { '1d': {...ready('HOLD'), row_hints: {status:'ready', bar_end:ready('HOLD').bar_end, physical_contract:'RB2701', calculation_segment_id:'c', page_parity:true, executable:false, items:[{kind:'caution', peak_day:'2026-10-08', event_day:'2026-10-09', formula_version:'mirror'}]}}, '1w': ready('BUILD') }, oscillation: { '1d': ready('FLAT'), '1w': { ...ready('CLEAR'), freshness: 'pending_update' } } } }] })
    await settle()
    assert.match(nodeText(root), /3100.13/)
    assert.equal(nodeText(findNode(root, n => n.props.class === 'row-hint')!), '小心')
    assert.match(nodeText(root), /9007199254740993.13/)
    assert.match(nodeText(root), /趋势来源未确认/)
    assert.doesNotMatch(nodeText(root), /日周向上/)
    const summary = findNode(root, n => n.props['aria-label'] === '螺纹钢展开策略摘要')!
    assert.equal(summary.props['aria-expanded'], false)
    ;(summary.props.onClick as Function)(); await nextTick()
    assert.equal(summary.props['aria-expanded'], true)
    assert.match(nodeText(root), /日周向上/)
    assert.match(nodeText(root), /日周综合/)
    assert.match(nodeText(root), /来源信息不可用/)
    assert.match(nodeText(root), /原站私有价格逐值一致未证明/)
    assert.match(nodeText(root), /断线保留最新完成报价/)
    assert.equal(findNode(root, n => n.type === 'details')?.props.open, undefined)
    assert.deepEqual(chart, [])
    assert.equal(findNode(root, n => n.props.class === 'summary-toggle'), null)
    const card = findNode(root, n => n.props.role === 'link')!
    ;(card.props.onClick as Function)()
    const switcher = findNode(root, n => n.type === 'button' && nodeText(n) === '震荡')!
    ;(switcher.props.onClick as Function)(); await nextTick()
    assert.match(nodeText(root), /3000.00/)
    assert.match(nodeText(root), /日周向下/)
    assert.match(nodeText(root), /等待最新周期更新/)
    ;(findNode(root, n => n.props.role === 'link')!.props.onClick as Function)()
    assert.deepEqual(chart, [['rb', 'trend', '1d'], ['rb', 'oscillation', '1d']])
    sequence.value++; await nextTick()
    api.calls.at(-1).resolve({ schema_version: 'newow_home_cards_v2', requested_at: '2026-10-09T00:00:00Z', items: [{ product: 'rb', strategies: { trend: { '1d': { ...ready('HOLD'), target_space_percent: '4' }, '1w': ready('CLEAR') }, oscillation: { '1d': { ...ready('FLAT'), absorb_space_percent: '-3' }, '1w': ready('HOLD') } } }] })
    await settle()
    assert.match(nodeText(root), /日线吸筹参考价相对确认收盘价 -3/)
    ;(findNode(root, n => n.type === 'button' && nodeText(n) === '趋势')!.props.onClick as Function)(); await nextTick()
    assert.match(nodeText(root), /日线目标参考价相对确认收盘价 \+4/)
    ;(switcher.props.onClick as Function)(); await nextTick()

    assert.match(nodeText(root), /空仓.*建仓.*持有.*清仓/)
    assert.match(nodeText(root), /参考收益待确认/)
    const sort = findNode(root, n => n.type === 'button' && nodeText(n).startsWith('涨跌幅'))!
    ;(sort.props.onClick as Function)(); assert.deepEqual(sorts, ['change'])
    sequence.value++; await nextTick()
    assert.match(nodeText(root), /策略刷新中，保留上次快照/)
    api.calls.at(-1).reject(Error('offline')); await settle()
    assert.match(nodeText(root), /策略刷新失败，保留上次快照/)
    assert.match(nodeText(root), /3000.00/)
    sequence.value++; await nextTick()
    const warming = { status: 'warming', state: null }, unavailable = { status: 'unavailable', state: null }
    api.calls.at(-1).resolve({ schema_version: 'newow_home_cards_v2', requested_at: '2026-10-09T00:00:00Z', items: [{ product: 'rb', strategies: { trend: { '1d': warming, '1w': unavailable }, oscillation: { '1d': warming, '1w': unavailable } } }] })
    await settle()
    assert.match(nodeText(root), /日线预热中/)
    assert.match(nodeText(root), /周线不可用/)
    assert.match(nodeText(root), /日周一致性不可用/)
    assert.doesNotMatch(nodeText(root), /日周向下|策略刷新失败/)
    assert.match(nodeText(root), /综合状态不可用/)
    ;(summary.props.onClick as Function)(); await nextTick()
    assert.equal(summary.props['aria-expanded'], false)
    assert.doesNotMatch(nodeText(root), /日周综合/)
  } finally { app.unmount() }
})

test('sector changes cancel obsolete requests and preserve displayed product order', async () => {
  const List = await loadList(), root = element('root')
  const all = ['rb', 'cu', 'a'].map(symbol => ({ symbol, product_name: symbol, close: 100, price_change_1d: 0 }))
  const rows = ref(all), authority = ref('one')
  const start = api.calls.length
  const app = createRenderer(nodeOperations()).createApp(defineComponent({ setup: () => () => h(List, {
    rows: rows.value, products: rows.value.map(row => row.symbol), authority: authority.value,
    refreshSequence: 0, liveStale: false, sort: 'default', sortDirection: 'desc',
  }) }))
  try {
    app.mount(root)
    const initial = api.calls.slice(start)
    assert.deepEqual(initial.map(call => call.products), [['rb'], ['cu']])
    rows.value = [all[2]!]; await nextTick()
    assert.ok(initial.every(call => call.signal.aborted))
    assert.deepEqual(api.calls.at(-1).products, ['a'])
    const before = api.calls.length
    initial.forEach(call => call.resolve({ schema_version: 'newow_home_cards_v2', requested_at: '2026-10-09T00:00:00Z', items: call.products.map((product: string) => ({ product, strategies: { trend: { '1d': ready('HOLD'), '1w': ready('HOLD') }, oscillation: { '1d': ready('FLAT'), '1w': ready('FLAT') } } })) }))
    await settle()
    assert.equal(api.calls.length, before, 'obsolete queue must not start hidden a product')
    assert.doesNotMatch(nodeText(root), /rb RB/)
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


test('row hints require exact daily ownership and do not create a trend source', () => {
  const day = { ...ready('FLAT'), row_hints: { status: 'ready', bar_end: ready('FLAT').bar_end!, physical_contract: 'RB2701', calculation_segment_id: 'c', page_parity: true, executable: false, items: [{kind: 'caution' as const, peak_day: '2026-10-08', event_day: '2026-10-09', formula_version: 'mirror'}, {kind: 'reduce' as const, event_day: '2026-10-09', j_value: '98.1', reference_price: '3000', formula_version: 'j'}] } }
  assert.deepEqual(homeRowHints(day).map(hint => hint.label), ['小心', '减仓'])
  assert.match(homeRowHints(day)[0].title, /2026-10-08.*2026-10-09/)
  assert.deepEqual(homeRowHints({...day, row_hints: {...day.row_hints, physical_contract: 'RB2601'}}), [])
  assert.deepEqual(homeRowHints({...day, row_hints: {...day.row_hints, executable: true}}), [])
  assert.equal(homeTrendDisplay().tone, 'pending')
})


test('expanded performance is lazy, deduplicated, authority isolated and recovers one rejected product owner', async () => {
  const List = await loadList(), root = element('root'), authority = ref('first')
  const row = { symbol: 'rb', product_name: '螺纹钢', close: 3100, price_change_1d: 0 }
  const packet = (token: string) => ({ schema_version: 'newow_home_cards_v2', requested_at: ready('FLAT').display_as_of, items: [{ product:'rb', strategies: { trend: { '1d': { ...ready('FLAT'), snapshot_token:token }, '1w':ready('FLAT') }, oscillation: { '1d':{ ...ready('HOLD'), snapshot_token:token + '-osc' }, '1w':ready('HOLD') } } }] })
  const initialCount = api.performanceCalls.length
  const app = createRenderer(nodeOperations()).createApp(defineComponent({ setup: () => () => h(List, { rows:[row], products:['rb'], authority:authority.value, refreshSequence:0, liveStale:false, sort:'default', sortDirection:'desc' }) }))
  try {
    app.mount(root); api.calls.at(-1).resolve(packet('one')); await settle()
    assert.equal(api.performanceCalls.length, initialCount)
    const toggle = () => (findNode(root, n => n.props['aria-label'] === '螺纹钢展开策略摘要')!.props.onClick as Function)()
    toggle(); await settle(); assert.equal(api.performanceCalls.length, initialCount + 2)
    assert.match(nodeText(root), /参考收益读取中/)
    toggle(); toggle(); await settle(); assert.equal(api.performanceCalls.length, initialCount + 2)
    const oldTrend = api.performanceCalls[initialCount], oldOsc = api.performanceCalls[initialCount + 1]
    authority.value = 'second'; await settle(); api.calls.at(-1).resolve(packet('one')); await settle()
    assert.equal(api.performanceCalls.length, initialCount + 4)
    const perf = (strategy: string, percent: string) => ({ status:'ready', version:'newow_page_performance_v3379_v2', strategy, frequency:'1d', as_of:ready('FLAT').as_of, input_sha256:'history', cum_return_percent:percent, trade_count:5, page_parity:true, executable:false })
    oldTrend.resolve(perf('trend','999')); oldOsc.reject(Error('old offline')); await settle()
    assert.doesNotMatch(nodeText(root), /999|读取失败/)
    api.performanceCalls[initialCount + 2].reject(Object.assign(Error('conflict'), { code:'NEWOW_SNAPSHOT_GENERATION_CONFLICT' })); await settle()
    assert.match(nodeText(root), /策略刷新中，保留上次快照/)
    api.calls.at(-1).resolve(packet('two')); await settle()
    assert.equal(api.performanceCalls.length, initialCount + 6)
    api.performanceCalls[initialCount + 3].resolve(perf('oscillation','999')); await settle()
    api.performanceCalls[initialCount + 4].resolve(perf('trend','20.59'))
    api.performanceCalls[initialCount + 5].resolve(perf('oscillation','62.14')); await settle()
    assert.match(nodeText(root), /20.59%/)
    const before = api.performanceCalls.length
    ;(findNode(root, n => n.type === 'button' && nodeText(n) === '震荡')!.props.onClick as Function)(); await settle()
    assert.match(nodeText(root), /62.14%/); assert.doesNotMatch(nodeText(root), /999/)
    toggle(); toggle(); await settle(); assert.equal(api.performanceCalls.length, before)
  } finally { app.unmount() }
})


test('period disclosure distinguishes a data conflict from an unconfirmed private source', () => {
  assert.match(homePeriodReason({ status: 'unavailable', state: null, reason_code: 'REFERENCE_CANONICAL_MISMATCH' })!, /身份冲突/)
  assert.equal(homePeriodReason({ status: 'ready', state: 'HOLD' }), null)
  assert.equal(homeTrendDisplay().label, '独立趋势来源未确认')
})
