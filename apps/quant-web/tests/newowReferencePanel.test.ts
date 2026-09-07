import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import test from 'node:test'
import { fileURLToPath, pathToFileURL } from 'node:url'

import { compileScript, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import { createRenderer, defineComponent, h, nextTick, ref } from 'vue'

import type {
  NewowProductSectionResponse,
  NewowReferenceTrade,
} from '../src/types/newowProduct.ts'
import * as viewModels from '../src/utils/newowProductViewModel.ts'

const buildReference = (viewModels as unknown as {
  buildNewowReferencePanelViewModel: (
    response: NewowProductSectionResponse<'reference'>,
    chart: NewowProductSectionResponse<'chart'> | null,
    crossSectionCompatible?: boolean,
  ) => ReferenceModel
}).buildNewowReferencePanelViewModel
const filterReference = (viewModels as unknown as {
  filterNewowReferenceRows: (model: ReferenceModel, filter: string) => ReferenceModel
}).filterNewowReferenceRows
const resolveLocate = (viewModels as unknown as {
  resolveNewowReferenceLocate: (
    trade: NewowReferenceTrade,
    chart: NewowProductSectionResponse<'chart'> | null,
    crossSectionCompatible?: boolean,
  ) => { kind: string; signalId: string; barEnd: string; displayWindow?: { from: string; through: string } }
}).resolveNewowReferenceLocate
const componentUrl = new URL('../src/components/market/detail/newow/NewowReferencePanel.vue', import.meta.url)
const sourceRoot = fileURLToPath(new URL('../src/', import.meta.url))

interface ReferenceModel {
  readonly summary: {
    readonly closedCount: number
    readonly winRateText: string
    readonly meanText: string
    readonly sumText: string
    readonly sumUnit: string
  }
  readonly performanceWindow: { readonly since: string; readonly through: string; readonly cutoff: string }
  readonly rows: readonly Array<{
    readonly id: string
    readonly category: string
    readonly initial: boolean
    readonly lifecycle: string
    readonly returnText: string
    readonly valuationText: string
    readonly hints: readonly Array<{ readonly id: string; readonly availability: string; readonly text: string }>
  }>
}

test('zero CLOSED stays unavailable while negative interruption and initial-position records remain separate', () => {
  const response = referenceResponse()
  const model = buildReference(response, chartResponse(), true)

  assert.deepEqual(model.summary, {
    closedCount: 0,
    winRateText: '—',
    meanText: '—',
    sumText: '—',
    sumUnit: '百分点（简单相加）',
  })
  assert.deepEqual(model.performanceWindow, {
    since: '2026-01-01', through: '2026-08-15', cutoff: '2026-08-15T07:00:00Z',
  })
  assert.equal(model.rows.find((row) => row.id === 'interrupted')?.category, 'interrupted')
  assert.equal(model.rows.find((row) => row.id === 'interrupted')?.returnText, '-12.5000%（中断浮动）')
  assert.equal(model.rows.find((row) => row.id === 'interrupted')?.valuationText, '2026-04-30T07:00:00Z · 87.500')
  assert.equal(model.rows.find((row) => row.id === 'initial')?.category, 'closed')
  assert.equal(model.rows.find((row) => row.id === 'initial')?.initial, true)
  assert.equal(model.rows.find((row) => row.id === 'initial')?.lifecycle, 'CLOSED')
  assert.equal(model.rows.find((row) => row.id === 'initial')?.returnText, '3.1250%（期初已有，不计入窗口统计）')
  assert.equal(model.rows.find((row) => row.id === 'initial-interrupted')?.category, 'interrupted')
  assert.equal(model.rows.find((row) => row.id === 'initial-interrupted')?.initial, true)
  assert.equal(model.rows.find((row) => row.id === 'initial-interrupted')?.lifecycle, 'ROLLOVER_INTERRUPTED')
  assert.equal(model.rows.find((row) => row.id === 'initial-interrupted')?.returnText, '-20.0000%（中断浮动；期初已有，不计入窗口统计）')
})

test('table filtering keeps the exact server summary and performance window', () => {
  const model = buildReference(referenceResponse(), chartResponse(), true)
  const filtered = filterReference(model, 'interrupted')

  assert.equal(filtered.summary, model.summary)
  assert.equal(filtered.performanceWindow, model.performanceWindow)
  assert.deepEqual(filtered.rows.map((row) => row.id), ['interrupted', 'initial-interrupted'])
  assert.deepEqual(filterReference(model, 'initial').rows.map((row) => row.id), ['initial', 'initial-interrupted'])
})

test('historical Hints expose only exact IDs already loaded and never infer same-Bar ordering', () => {
  const model = buildReference(referenceResponse(), chartResponse(), true)
  const hints = model.rows.find((row) => row.id === 'open')!.hints

  assert.deepEqual(hints.map(({ fact: _fact, ...hint }) => hint), [
    { id: 'hint-loaded', availability: 'loaded', text: 'D4 · 2026-08-14T07:00:00Z · 关联 Hint（不推断与主动作的同 Bar 顺序）' },
    { id: 'hint-missing', availability: 'unavailable', text: '未在已加载图表事实中找到，不能按邻近日期或当前上下文推断。' },
  ])
  assert.equal(hints[0]!.fact?.known_at, '2026-08-14T07:00:00Z')
  assert.equal(hints[0]!.fact?.anchor_price, '99.000')
  assert.equal(hints[1]!.fact, null)
})

test('history locate requires exact signal ID plus bar_end and requests display data without a performance window', () => {
  const response = referenceResponse()
  const open = response.value!.items.find((trade) => trade.reference_trade_id === 'open')!
  const initial = response.value!.items.find((trade) => trade.reference_trade_id === 'initial')!

  assert.deepEqual(resolveLocate(open, chartResponse(), true), {
    kind: 'loaded', signalId: 'entry-open', barEnd: '2026-08-14T07:00:00Z',
  })
  assert.deepEqual(resolveLocate(initial, chartResponse(), true), {
    kind: 'request_display_window', signalId: 'entry-initial', barEnd: '2025-12-20T07:00:00Z',
    displayWindow: { from: '2025-12-20', through: '2025-12-20' },
  })
  assert.equal('performanceSince' in resolveLocate(initial, chartResponse(), true), false)

  const chartWithWrongId = chartResponse()
  chartWithWrongId.value!.bars = [{ ...chartWithWrongId.value!.bars[0]!, bar_end: initial.entry_bar_end, trading_day: initial.entry_trading_day }]
  assert.deepEqual(resolveLocate(initial, chartWithWrongId, true), {
    kind: 'unavailable', signalId: 'entry-initial', barEnd: '2025-12-20T07:00:00Z',
  })
})

test('cross-section Hint and locate stay unavailable without a shared snapshot proof', () => {
  const response = referenceResponse()
  const chart = chartResponse()
  const open = response.value!.items.find((trade) => trade.reference_trade_id === 'open')!
  const model = buildReference(response, chart, false)

  assert.equal(model.rows.find((row) => row.id === 'open')!.hints[0]!.availability, 'unavailable')
  assert.match(model.rows.find((row) => row.id === 'open')!.hints[0]!.text, /共同快照/)
  assert.deepEqual(resolveLocate(open, chart, false), {
    kind: 'unavailable', signalId: 'entry-open', barEnd: '2026-08-14T07:00:00Z',
  })
})

test('simple sum keeps percentage points separate and never appends a percent unit', () => {
  const response = referenceResponse()
  response.value!.summary.closed_count = 1
  response.value!.summary.win_count = 1
  response.value!.summary.win_rate_pct = '100.00'
  response.value!.summary.mean_return_pct = '12.5000'
  response.value!.summary.sum_return_percentage_points = '12.5000'
  const model = buildReference(response, chartResponse(), true)

  assert.equal(model.summary.sumText, '12.5000')
  assert.equal(model.summary.sumUnit, '百分点（简单相加）')
  assert.equal(model.summary.sumText.includes('%'), false)
})

test('reference panel keeps the server summary while native controls filter, expand and emit exact locate facts', async () => {
  const Panel = await loadComponent()
  const located: Array<{ reference_trade_id: string; entry_signal_id: string; entry_bar_end: string }> = []
  const Host = defineComponent({ setup: () => () => h(Panel, {
    response: referenceResponse(), chartResponse: chartResponse(), crossSectionCompatible: true, lifecycle: 'ready', error: null,
    selectedSignalId: null, locateMessage: null, loadingPage: false,
    onLocate: (trade: NewowReferenceTrade) => located.push(trade),
  }) })
  const root = element('root')
  const app = createRenderer(nodeOperations()).createApp(Host)
  app.mount(root)
  await nextTick()

  const summary = findNode(root, (node) => node.props['data-testid'] === 'newow-reference-summary')!
  assert.match(nodeText(summary), /胜率\s*—/)
  assert.match(nodeText(summary), /简单相加/)
  const fullText = nodeText(root)
  for (const phrase of ['long/flat', '趋势 B', '震荡 Low/High', '主升浪 MA45', 'API reference_price', '零手续费', '零滑点', '不计资金占用与真实成交限制', '不推断手数', '不推断空单', '不推断账户净值', '不推断真实收益', '非因果回测', '非模拟账户', '非真实成交']) {
    assert.match(fullText, new RegExp(phrase))
  }
  assert.match(fullText, /同 Bar Close 仅属于独立 comparator/)
  assert.doesNotMatch(fullText, /Reference[^。]*采用同 Bar Close/)
  const expand = findNode(root, (node) => node.props['aria-label'] === '展开参考记录 open')!
  assert.equal(expand.type, 'button')
  assert.equal(expand.props['aria-expanded'], false)
  ;(expand.props.onClick as () => void)()
  await nextTick()
  assert.match(nodeText(root), /D4 · 2026-08-14T07:00:00Z · 关联 Hint（不推断与主动作的同 Bar 顺序）/)
  assert.match(nodeText(root), /不能按邻近日期或当前上下文推断/)

  const locate = findNode(root, (node) => node.props['aria-label'] === '定位参考记录 open 的建仓信号')!
  assert.equal(locate.type, 'button')
  ;(locate.props.onClick as () => void)()
  assert.deepEqual(located.map(({ reference_trade_id, entry_signal_id, entry_bar_end }) => ({ reference_trade_id, entry_signal_id, entry_bar_end })), [
    { reference_trade_id: 'open', entry_signal_id: 'entry-open', entry_bar_end: '2026-08-14T07:00:00Z' },
  ])

  const filter = findNode(root, (node) => node.props['aria-label'] === '筛选参考历史')!
  ;(filter.props.onChange as (event: { target: { value: string } }) => void)({ target: { value: 'interrupted' } })
  await nextTick()
  assert.doesNotMatch(nodeText(root), /entry-open/)
  assert.ok(findNode(root, node => node.type === 'article' && node.props['data-reference-category'] === 'interrupted'))
  assert.equal(findNode(root, node => node.type === 'table'), undefined)
  assert.match(nodeText(summary), /胜率\s*—/, 'filter must not change the server-owned summary')
  app.unmount()
})

test('reference date drafts clear when a new identity has no retained response', async () => {
  const Panel = await loadComponent()
  const response = ref<NewowProductSectionResponse<'reference'> | null>(referenceResponse())
  const Host = defineComponent({ setup: () => () => h(Panel, {
    response: response.value, chartResponse: null, crossSectionCompatible: false, lifecycle: response.value === null ? 'unavailable' : 'ready',
    error: response.value === null ? 'NEWOW_API_UNAVAILABLE' : null, selectedSignalId: null, locateMessage: null, loadingPage: false,
  }) })
  const root = element('root')
  const app = createRenderer(nodeOperations()).createApp(Host)
  app.mount(root)
  await nextTick()
  assert.deepEqual(findNodes(root, (node) => node.type === 'input').map((node) => node.props.value), ['2026-01-01', '2026-08-15'])

  response.value = null
  await nextTick()
  assert.deepEqual(findNodes(root, (node) => node.type === 'input').map((node) => node.props.value), ['', ''])
  assert.doesNotMatch(nodeText(root), /stale/)
  app.unmount()
})

function referenceResponse(): Mutable<NewowProductSectionResponse<'reference'>> {
  return {
    meta: meta(), section: 'reference', status: ready(), value: {
      performance_since: '2026-01-01', performance_through: '2026-08-15', actual_available_through: '2026-08-15',
      reference_cutoff: '2026-08-15T07:00:00Z', reference_input_sha256: 'c'.repeat(64),
      summary: {
        membership_policy: 'entry_in_window_v1', closed_count: 0, win_count: 0, loss_count: 0, flat_count: 0,
        win_rate_pct: null, mean_return_pct: null, sum_return_percentage_points: null,
        open_count: 1, interrupted_count: 1, initial_count: 2,
      },
      items: [
        trade('open', {
          entry_signal_id: 'entry-open', entry_bar_end: '2026-08-14T07:00:00Z', entry_trading_day: '2026-08-14',
          status: 'OPEN', statistics_membership: 'entry_in_window_v1',
          hint_ids: ['hint-loaded', 'hint-missing'], mark_bar_end: '2026-08-15T07:00:00Z', mark_reference_price: '98.500', mark_change_pct: '-1.5000',
        }),
        trade('interrupted', {
          entry_signal_id: 'entry-interrupted', entry_bar_end: '2026-04-01T07:00:00Z', entry_trading_day: '2026-04-01',
          status: 'ROLLOVER_INTERRUPTED', statistics_membership: 'entry_in_window_v1',
          mark_bar_end: '2026-04-30T07:00:00Z', mark_reference_price: '87.500', mark_change_pct: '-12.5000',
          interrupted_at: '2026-05-01T00:00:00Z', interruption_reason: 'OWNER_BOUNDARY',
        }),
        trade('initial', {
          entry_signal_id: 'entry-initial', entry_bar_end: '2025-12-20T07:00:00Z', entry_trading_day: '2025-12-20',
          exit_signal_id: 'exit-initial', exit_bar_end: '2026-01-03T07:00:00Z', exit_trading_day: '2026-01-03', exit_reference_price: '103.125',
          status: 'CLOSED', reference_return_pct: '3.1250', statistics_membership: 'initial_before_window',
        }),
        trade('initial-interrupted', {
          entry_signal_id: 'entry-initial-interrupted', entry_bar_end: '2025-11-20T07:00:00Z', entry_trading_day: '2025-11-20',
          status: 'ROLLOVER_INTERRUPTED', statistics_membership: 'initial_before_window',
          mark_bar_end: '2025-12-20T07:00:00Z', mark_reference_price: '80.000', mark_change_pct: '-20.0000',
          interrupted_at: '2025-12-21T00:00:00Z', interruption_reason: 'OWNER_BOUNDARY',
        }),
      ],
      next_before: 'opaque-history', executable: false, auto_order: false,
      allowed_uses: ['page_parity_reference', 'research_display'],
    },
  }
}

function chartResponse(): Mutable<NewowProductSectionResponse<'chart'>> {
  return {
    meta: meta(), section: 'chart', status: ready(), value: {
      chart_from: '2026-08-14', chart_through: '2026-08-15', page_identity: 'b'.repeat(64),
      bars: [bar('2026-08-14T07:00:00Z', '2026-08-14'), bar('2026-08-15T07:00:00Z', '2026-08-15')],
      frames: [],
      actions: [{
        signal_id: 'entry-open', kind: 'BUILD', bar_end: '2026-08-14T07:00:00Z', trading_day: '2026-08-14', reference_price: '100.000',
        physical_contract: 'JM2601', segment_id: 'segment-1', related_build_id: null, trade_eligibility: 'ELIGIBLE', sequence: 0,
      }],
      hints: [{
        hint_id: 'hint-loaded', kind: 'D4', bar_end: '2026-08-14T07:00:00Z', known_at: '2026-08-14T07:00:00Z', anchor_price: '99.000',
        physical_contract: 'JM2601', segment_id: 'segment-1', retrospective: false, quantity_effect: 'none', sequence: null,
      }],
      diagnostics: [], next_before: null, repainting: false, formal_signal_eligible: true,
      allowed_uses: ['product_chart', 'reference_input'],
    },
  }
}

function trade(id: string, overrides: Partial<Mutable<NewowReferenceTrade>>): Mutable<NewowReferenceTrade> {
  return {
    reference_trade_id: id, product: 'jm', strategy_code: 'trend', frequency: '1d', physical_contract: 'JM2601', segment_id: 'segment-1',
    formula_versions: ['newow_trend_band_page_v2'], reference_model_version: 'newow_marker_reference_zero_cost_v1', futures_adaptation_version: 'newow_futures_segment_interrupt_v1',
    entry_signal_id: `entry-${id}`, entry_sequence: 0, entry_bar_end: '2026-08-01T07:00:00Z', entry_trading_day: '2026-08-01', entry_reference_price: '100.000',
    exit_signal_id: null, exit_bar_end: null, exit_trading_day: null, exit_reference_price: null,
    status: 'OPEN', holding_bars: 1, reference_return_pct: null,
    mark_bar_end: null, mark_reference_price: null, mark_change_pct: null, interrupted_at: null, interruption_reason: null,
    statistics_membership: null, hint_ids: [], ...overrides,
  }
}

function bar(barEnd: string, tradingDay: string) {
  return { bar_end: barEnd, trading_day: tradingDay, open: '100', high: '101', low: '99', close: '100', volume: 10, open_interest: 20, physical_contract: 'JM2601', segment_id: 'segment-1', source_identity: 'canonical:jm:JM2601:1d', observation_eligible: true, completed: true as const }
}

function meta() {
  return {
    schema_version: 'newow_product_detail_v1' as const,
    identity: { product: 'jm', strategy: 'trend' as const, frequency: '1d' as const, series_kind: 'actual_dominant' as const, profile_id: 'profile-1', formula_versions: ['newow_trend_band_page_v2'] },
    as_of: '2026-08-15T07:00:00Z', read_at: '2026-08-15T07:00:01Z', input_content_sha256: 'a'.repeat(64), data_revision_identity: null, snapshot_token: 'snapshot-1',
    reference_model_version: 'newow_marker_reference_zero_cost_v1' as const, futures_adaptation_version: 'newow_futures_segment_interrupt_v1' as const,
  }
}

function ready() { return { status: 'ready' as const, evidence_status: 'ACTIVE_CODE_VERIFIED' as const, reason_code: null } }
type Mutable<T> = { -readonly [K in keyof T]: T[K] extends readonly (infer U)[] ? Mutable<U>[] : T[K] extends object ? Mutable<T[K]> : T[K] }

async function loadComponent() {
  const source = readFileSync(componentUrl, 'utf8')
  const { descriptor, errors } = parse(source, { filename: componentUrl.pathname })
  assert.deepEqual(errors, [])
  const compiled = compileScript(descriptor, { id: 'newow-reference-panel', inlineTemplate: true })
  const transpiled = ts.transpileModule(compiled.content, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
    .replace(/from ['"]vue['"]/g, `from '${import.meta.resolve('vue')}'`)
    .replace(/from ['"]@\/([^'"]+)['"]/g, (_match, specifier: string) => {
      for (const suffix of ['', '.ts', '.vue']) {
        const path = resolve(sourceRoot, `${specifier}${suffix}`)
        if (existsSync(path)) return `from '${pathToFileURL(path).href}'`
      }
      throw new Error(`cannot resolve source import: ${specifier}`)
    })
  return (await import(`data:text/javascript;base64,${Buffer.from(transpiled).toString('base64')}`)).default
}

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
    insert(child: TestNode, parent: TestNode, anchor: TestNode | null = null) { child.parent = parent; const index = anchor === null ? -1 : parent.children.indexOf(anchor); if (index < 0) parent.children.push(child); else parent.children.splice(index, 0, child) },
    remove(child: TestNode) { if (child.parent === null) return; child.parent.children = child.parent.children.filter((item) => item !== child); child.parent = null },
    createElement: (type: string) => element(type), createText(text: string) { const node = element('#text'); node.text = text; return node }, createComment(text: string) { const node = element('#comment'); node.text = text; return node },
    setText(node: TestNode, text: string) { node.text = text }, setElementText(node: TestNode, text: string) { node.text = text; node.children = [] },
    parentNode(node: TestNode) { return node.parent }, nextSibling(node: TestNode) { if (node.parent === null) return null; const index = node.parent.children.indexOf(node); return node.parent.children[index + 1] ?? null }, querySelector() { return null }, setScopeId() {}, insertStaticContent() { return [element('#static'), element('#static')] as const },
  }
}
