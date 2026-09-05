import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { resolve } from 'node:path'
import test from 'node:test'

import ts from 'typescript'
import { compileScript, parse } from '@vue/compiler-sfc'
import { createRenderer, nextTick } from 'vue'

import type { NewowTrendDetailResponse } from '../src/types/newow.ts'

const componentUrl = new URL('../src/components/market/detail/TrendDetailWorkspace.vue', import.meta.url)
const viewModelUrl = new URL('../src/utils/newowViewModel.ts', import.meta.url)
const historyComponentUrl = new URL('../src/components/market/detail/MarketDetailSectionTabs.vue', import.meta.url)
const insightDeckUrl = new URL('../src/components/market/detail/MarketDetailInsightDeck.vue', import.meta.url)
const sourceRoot = fileURLToPath(new URL('../src/', import.meta.url))

function component() {
  const source = readFileSync(componentUrl, 'utf8')
  const parsed = parse(source, { filename: componentUrl.pathname })
  assert.deepEqual(parsed.errors, [], 'TrendDetailWorkspace must be a valid Vue SFC')
  assert.ok(parsed.descriptor.scriptSetup, 'TrendDetailWorkspace must expose a typed setup contract')
  assert.ok(parsed.descriptor.template, 'TrendDetailWorkspace must render a template')
  return { source, template: parsed.descriptor.template.content }
}

test('projects one Newow snapshot into facts, disclosures, chart, and history without another authority', () => {
  const { source, template } = component()

  assert.match(source, /useNewowTrendDetail/)
  assert.match(source, /buildNewowDetailViewModel/)
  assert.match(source, /model\.value\.history/)
  assert.match(source, /loader\.data\.value/)
  assert.match(source, /onBeforeUnmount\(loader\.dispose\)/)
  assert.match(template, /<MarketDetailFactStrip[^>]+:facts="model\.facts"/)
  assert.match(template, /<MarketDetailInsightDeck[^>]+:sections="disclosureSections"/)
  assert.match(template, /<NewowTrendChartStage[^>]+:data="loader\.data\.value"[^>]+:generic-bars="bars"/s)
  assert.match(template, /<MarketDetailSectionTabs[^>]+:history="model\.history"/s)
  assert.doesNotMatch(source, /getAlert|usePersistentAlert|useHtdy|useRangeDetector|ResearchOverlayId/)
  assert.doesNotMatch(template, /MACD|EMA|Range|火天大有|苏冰|预警/)
})

test('keeps the three facts and all authority disclosures visible before the independent chart', () => {
  const { source, template } = component()
  const banner = template.indexOf('model.semanticBanner.text')
  const facts = template.indexOf('<MarketDetailFactStrip')
  const notices = template.indexOf('trend-workspace__notices')
  const disclosures = template.indexOf('<MarketDetailInsightDeck')
  const chart = template.indexOf('<NewowTrendChartStage')

  assert.ok(banner >= 0 && banner < facts)
  assert.ok(facts < notices && notices < disclosures && disclosures < chart)
  assert.match(readFileSync(viewModelUrl, 'utf8'), /建仓、持有、清仓、空仓为趋势引擎状态，不代表实际账户持仓。/)
  assert.match(source, /calculation_identity/)
  assert.match(source, /source_identity/)
  assert.doesNotMatch(source, /formula_descriptions/)
  assert.match(source, /bar_policy/)
  assert.match(source, /rollover_seams/)
  assert.match(source, /warnings/)
  assert.match(source, /仅展示已完成 D1/)
  assert.match(source, /不表示建立期货空单/)
})

test('fails Newow closed while retaining only the generic completed-D1 chart fallback', () => {
  const { source, template } = component()

  assert.match(source, /趋势策略数据不可用/)
  assert.match(source, /基础 completed D1 K 线/)
  assert.match(template, /loader\.error\.value/)
  assert.match(template, /data-newow-state="unavailable"/)
  assert.match(template, /:data="loader\.data\.value"/)
  assert.match(template, /:generic-bars="bars"/)
  assert.doesNotMatch(template, /overlay/i)
})

test('distinguishes the one-shot Newow loading state from an unavailable result', () => {
  const { source, template } = component()

  assert.match(template, /loader\.loading\.value\s*\?\s*'loading'/)
  assert.match(source, /const notices = computed\(\(\) => buildNotices\([\s\S]+?loader\.loading\.value/)
  assert.match(source, /正在读取 Newow 趋势数据；读取完成前仅显示基础 completed D1 K 线。/)
  assert.match(template, /v-if="loader\.error\.value"/)
})

test('exposes history availability and the existing history opener without alert semantics', () => {
  const { source } = component()
  const historySource = readFileSync(historyComponentUrl, 'utf8')

  assert.match(source, /'history-availability':\s*\[available:\s*boolean\]/)
  assert.match(source, /watch\(\(\) => model\.value\.history\.length/)
  assert.match(source, /tabs\.value\?\.openHistory\(\)/)
  assert.match(source, /defineExpose\(\{ openHistory \}\)/)
  assert.doesNotMatch(source, /notificationAttemptedAt|AlertEvent|open-alert|manageAlert/)
  assert.match(historySource, /item\.markerType/)
  assert.match(historySource, /item\.formulaVersion/)
})

test('renders projected Trend, D, Cup, source, rollover, and warning evidence before the chart', async () => {
  const Workspace = await loadWorkspace(snapshot())
  const renderer = createRenderer(nodeOperations())
  const root = element('root')
  const app = renderer.createApp(Workspace, {
    identity: { view: 'trend', symbol: 'rb', seriesKind: 'actual_dominant', frequency: '1d' },
    header: {
      symbol: 'rb', productName: '螺纹钢', exchange: 'SHFE', sector: '黑色',
      seriesKind: 'actual_dominant', displayContract: 'RB2610', asOf: '2026-01-07T07:00:00Z',
      open: 10, high: 12, low: 9, close: 11, change: 1, pct: 10,
      volume: 100, turnover: null, openInterest: 200, phase: 'CLOSED',
      displaySource: 'Canonical', freshness: 'fresh', extendedSections: [],
    },
    bars: [],
  })

  app.mount(root)
  await nextTick()
  const visible = textContent(root)
  const chartOffset = visible.indexOf('CHART_STAGE')
  const evidence = [
    '当前策略状态:持有', '最近转换:CLEAR', '转换时间:2026-01-06T07:00:00Z',
    '当前 Bar D Markers:NEWOW_ESCAPE_D2 / NEWOW_ESCAPE_D3',
    '最近历史 D Marker:NEWOW_ESCAPE_D2', '最近历史 D Bar:2026-01-07T07:00:00Z',
    '杯柄 Candidate:cup-exact', '杯柄当前状态:BREAKOUT · 突破',
    'L 左杯沿:{"pivot_at":"2025-11-01T07:00:00Z","confirmed_at":"2025-11-02T07:00:00Z","price":12}',
    'B 杯底:{"pivot_at":"2025-12-01T07:00:00Z","confirmed_at":"2025-12-02T07:00:00Z","price":8}',
    'R 右杯沿:{"pivot_at":"2026-01-01T07:00:00Z","confirmed_at":"2026-01-02T07:00:00Z","price":11.8}',
    'H 柄起点:2026-01-01T07:00:00Z',
    'H 柄极值:{"pivot_at":"2026-01-03T07:00:00Z","confirmed_at":"2026-01-04T07:00:00Z","price":10.8}',
    'P 枢轴:{"pivot_frozen_at":"2026-01-05T07:00:00Z","price":11.9}',
    'confirmed_at:2026-01-05T07:00:00Z', 'first_seen_at:2026-01-03T07:00:00Z',
    'state_changed_at:2026-01-07T07:00:00Z', 'score:80',
    'score_breakdown:{"pretrend":20,"cup_geometry":20,"u_shape_purity":15,"handle_quality":15,"volume_structure":10}',
    'volume_facts:{"right_leg_median":100,"handle_median":70,"handle_baseline_median":90,"handle_right_ratio":0.7,"handle_baseline_ratio":0.78}',
    '当前合约:RB2610', '当前 Segment:segment-2',
    '最近换月:{"trading_day":"2026-01-07","previous_contract":"RB2605","next_contract":"RB2610","previous_bar_end":"2026-01-06T07:00:00Z","next_bar_end":"2026-01-07T07:00:00Z","previous_segment_id":"segment-1","next_segment_id":"segment-2"}',
    'warnings:[]', '最新 Bar 来源身份:source-rb-segment-2', '计算身份:calculation-identity',
  ]
  assert.ok(chartOffset > 0, 'chart stub must be mounted')
  for (const value of evidence) {
    const offset = visible.indexOf(value)
    assert.ok(offset >= 0, `missing visible evidence: ${value}`)
    assert.ok(offset < chartOffset, `evidence must render before chart: ${value}`)
  }
  assert.match(visible, /仅展示已完成 D1；未完成 Bar 不进入 Newow 事实。/)
  assert.match(visible, /当前窗口包含 1 处主力换月；分界仅表示物理合约切换，不表示交易机会。/)
  assert.match(visible, /建仓、持有、清仓、空仓为趋势引擎状态，不代表实际账户持仓。/)
  assert.match(visible, /蓝色仅表示 Newow 的空仓或风险阶段，不表示建立期货空单。/)
  assert.doesNotMatch(visible, /预警|通知|AlertEvent/)
  app.unmount()
})

test('renders exact warm-up warning identities and their fail-closed presentation', async () => {
  const warned = snapshot()
  warned.warnings = [
    'NEWOW_TREND_WARMUP_INSUFFICIENT',
    'NEWOW_D123_WARMUP_INSUFFICIENT',
    'NEWOW_CUP_WARMUP_INSUFFICIENT',
  ]
  const Workspace = await loadWorkspace(warned)
  const renderer = createRenderer(nodeOperations())
  const root = element('root')
  const app = renderer.createApp(Workspace, {
    identity: { view: 'trend', symbol: 'rb', seriesKind: 'actual_dominant', frequency: '1d' },
    header: {
      symbol: 'rb', productName: '螺纹钢', exchange: 'SHFE', sector: '黑色',
      seriesKind: 'actual_dominant', displayContract: 'RB2610', asOf: '2026-01-07T07:00:00Z',
      open: 10, high: 12, low: 9, close: 11, change: 1, pct: 10,
      volume: 100, turnover: null, openInterest: 200, phase: 'CLOSED',
      displaySource: 'Canonical', freshness: 'fresh', extendedSections: [],
    },
    bars: [],
  })

  app.mount(root)
  await nextTick()
  const visible = textContent(root)
  assert.match(visible, /warnings:\["NEWOW_TREND_WARMUP_INSUFFICIENT","NEWOW_D123_WARMUP_INSUFFICIENT","NEWOW_CUP_WARMUP_INSUFFICIENT"\]/)
  assert.match(visible, /趋势带 warm-up 不足，当前趋势不可用/)
  assert.match(visible, /D1\/D2\/D3 warm-up 不足，当前风险不可用/)
  assert.match(visible, /杯柄 warm-up 不足，当前形态不可用/)
  assert.match(visible, /周线背景:不可用/)
  assert.match(visible, /日线趋势:不可用/)
  assert.match(visible, /当前风险:不可用/)
  app.unmount()
})

test('opens every Trend disclosure by default on desktop through the shared deck behavior', async () => {
  const InsightDeck = await loadInsightDeck()
  const previousWindow = Object.getOwnPropertyDescriptor(globalThis, 'window')
  Object.defineProperty(globalThis, 'window', {
    configurable: true,
    value: {
      matchMedia: () => ({
        matches: false,
        addEventListener() {},
        removeEventListener() {},
      }),
    },
  })
  const renderer = createRenderer(nodeOperations())
  const root = element('root')
  const app = renderer.createApp(InsightDeck, {
    identityKey: 'trend:rb:actual_dominant:1d:request-identity',
    sections: [
      disclosure('trend', 'trend-row'),
      disclosure('risk', 'risk-row'),
      disclosure('data', 'data-row'),
    ],
    defaultOpen: true,
    defaultOpenAll: true,
  })
  try {
    app.mount(root)
    await nextTick()
    assert.match(textContent(root), /trend-row.*risk-row.*data-row/)
  } finally {
    app.unmount()
    if (previousWindow) Object.defineProperty(globalThis, 'window', previousWindow)
    else Reflect.deleteProperty(globalThis, 'window')
  }
})

async function loadWorkspace(data: NewowTrendDetailResponse) {
  const source = readFileSync(componentUrl, 'utf8')
  const { descriptor, errors } = parse(source, { filename: componentUrl.pathname })
  assert.deepEqual(errors, [])
  const compiled = compileScript(descriptor, { id: 'trend-detail-workspace-test', inlineTemplate: true })
  const stubs = componentStubs()
  const loaderStub = moduleUrl(`
    import { ref } from '${import.meta.resolve('vue')}'
    export function useNewowTrendDetail() {
      return { data: ref(${JSON.stringify(data)}), loading: ref(false), error: ref(null), dispose() {} }
    }
  `)
  const transpiled = ts.transpileModule(compiled.content, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
  }).outputText
    .replace(/from ['"]vue['"]/g, `from '${import.meta.resolve('vue')}'`)
    .replace(/from ['"]@\/components\/market\/detail\/([^'"]+\.vue)['"]/g, (_match, file: string) => {
      const url = stubs[file]
      assert.ok(url, `missing component stub: ${file}`)
      return `from '${url}'`
    })
    .replace(/from ['"]@\/composables\/useNewowTrendDetail['"]/g, `from '${loaderStub}'`)
    .replace(/from ['"]@\/([^'"]+)['"]/g, (_match, specifier: string) => (
      `from '${pathToFileURL(resolveSourceImport(specifier)).href}'`
    ))
  return (await import(moduleUrl(transpiled))).default
}

async function loadInsightDeck() {
  const source = readFileSync(insightDeckUrl, 'utf8')
  const { descriptor, errors } = parse(source, { filename: insightDeckUrl.pathname })
  assert.deepEqual(errors, [])
  const compiled = compileScript(descriptor, { id: 'market-detail-insight-deck-test', inlineTemplate: true })
  const disclosureStub = moduleUrl(`
    import { defineComponent, h } from '${import.meta.resolve('vue')}'
    export default defineComponent({
      props: { section: Object, open: Boolean },
      setup(props) { return () => h('section', props.open ? props.section.rows.map(row => h('p', row.value)) : []) },
    })
  `)
  const transpiled = ts.transpileModule(compiled.content, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
  }).outputText
    .replace(/from ['"]vue['"]/g, `from '${import.meta.resolve('vue')}'`)
    .replace(/from ['"]\.\/MarketDetailDisclosure\.vue['"]/g, `from '${disclosureStub}'`)
  return (await import(moduleUrl(transpiled))).default
}

function componentStubs(): Record<string, string> {
  const vueUrl = import.meta.resolve('vue')
  return {
    'MarketDetailFactStrip.vue': moduleUrl(`
      import { defineComponent, h } from '${vueUrl}'
      export default defineComponent({ props: ['facts'], setup(props) { return () => h('div', { 'data-stub': 'facts' }, props.facts.map(f => h('p', f.label + ':' + f.value))) } })
    `),
    'MarketDetailInsightDeck.vue': moduleUrl(`
      import { defineComponent, h } from '${vueUrl}'
      export default defineComponent({ props: { sections: Array, defaultOpenAll: Boolean }, setup(props) { return () => h('div', { 'data-stub': 'insights' }, props.defaultOpenAll ? props.sections.flatMap(s => s.rows.map(r => h('p', r.label + ':' + r.value))) : []) } })
    `),
    'MarketDetailSectionTabs.vue': moduleUrl(`
      import { defineComponent, h } from '${vueUrl}'
      export default defineComponent({ props: ['history'], setup() { return { openHistory() {} } }, render() { return h('div', { 'data-stub': 'history' }) } })
    `),
    'NewowTrendChartStage.vue': moduleUrl(`
      import { defineComponent, h } from '${vueUrl}'
      export default defineComponent({ setup() { return () => h('div', { 'data-stub': 'chart' }, 'CHART_STAGE') } })
    `),
  }
}

function resolveSourceImport(specifier: string): string {
  for (const suffix of ['', '.ts']) {
    const path = resolve(sourceRoot, `${specifier}${suffix}`)
    if (existsSync(path)) return path
  }
  throw new Error(`cannot resolve source import: ${specifier}`)
}

function moduleUrl(source: string): string {
  return `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`
}

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

function textContent(node: TestNode): string {
  return node.text + node.children.map(textContent).join('')
}

function disclosure(id: string, value: string) {
  return {
    id, title: id, summary: id, updatedAt: null, tone: 'default' as const,
    rows: [{ label: value, value, source: 'newow' as const }],
  }
}

function snapshot(): MutableSnapshot {
  const bars: NewowTrendDetailResponse['bars'] = [
    bar('2026-01-05T07:00:00Z', '2026-01-05', 'RB2605', 'segment-1'),
    bar('2026-01-06T07:00:00Z', '2026-01-06', 'RB2605', 'segment-1'),
    bar('2026-01-07T07:00:00Z', '2026-01-07', 'RB2610', 'segment-2'),
  ]
  return {
    meta: {
      strategy_code: 'newow_trend_v1', profile_id: 'newow_trend_d1_page_v2', frequency: '1d',
      series_kind: 'actual_dominant', calculation_identity: 'calculation-identity',
      data_revision_identity: 'data-revision', request_identity: 'request-identity',
    },
    instrument: { product: 'rb', display_name: '螺纹钢', last_visible_physical_contract: 'RB2610' },
    bars, bar_policy: 'completed_only',
    trend_band: [
      { bar_end: bars[0]!.bar_end, b_value: 10, c_value: 9, state: 'YELLOW', state_before: 'BLUE', transition: 'BUILD' },
      { bar_end: bars[1]!.bar_end, b_value: 10, c_value: 9, state: 'BLUE', state_before: 'YELLOW', transition: 'CLEAR' },
      { bar_end: bars[2]!.bar_end, b_value: 10, c_value: 9, state: 'YELLOW', state_before: 'YELLOW', transition: null },
    ],
    trend_markers: [],
    escape_markers: [
      marker('older-d1', 'NEWOW_ESCAPE_D1', bars[1]!.bar_end),
      marker('current-d3', 'NEWOW_ESCAPE_D3', bars[2]!.bar_end),
      marker('current-d2', 'NEWOW_ESCAPE_D2', bars[2]!.bar_end),
    ],
    cup_markers: [], cup_handles: [cup()],
    rollover_seams: [{
      trading_day: '2026-01-07', previous_contract: 'RB2605', next_contract: 'RB2610',
      previous_bar_end: bars[1]!.bar_end, next_bar_end: bars[2]!.bar_end,
      previous_segment_id: 'segment-1', next_segment_id: 'segment-2',
    }],
    legend: { BUILD: 'trend build', CLEAR: 'trend clear', D1: 'escape D1', D2: 'escape D2', D3: 'escape D3' },
    formula_descriptions: {
      trend_band: 'newow_trend_band_page_v2', escape: 'newow_escape_d123_page_v2', cup_handle: 'newow_cup_handle_v1',
    },
    warnings: [],
  }
}

type MutableSnapshot = {
  -readonly [K in keyof NewowTrendDetailResponse]: NewowTrendDetailResponse[K] extends readonly (infer T)[]
    ? T[]
    : NewowTrendDetailResponse[K]
}

function bar(barEnd: string, tradingDay: string, physicalContract: string, segmentId: string) {
  return {
    bar_end: barEnd, trading_day: tradingDay, open: 10, high: 12, low: 9, close: 11,
    volume: 100, open_interest: 200, physical_contract: physicalContract,
    segment_id: segmentId, source_identity: `source-rb-${segmentId}`,
  }
}

function marker(id: string, markerType: 'NEWOW_ESCAPE_D1' | 'NEWOW_ESCAPE_D2' | 'NEWOW_ESCAPE_D3', barEnd: string) {
  return {
    marker_id: id, marker_type: markerType, bar_end: barEnd, price: 11,
    label: markerType, color_token: 'newow-test', priority: 100,
    related_marker_ids: [], trigger_facts: {}, formula_version: 'newow_escape_d123_page_v2' as const,
  }
}

function cup(): NewowTrendDetailResponse['cup_handles'][number] {
  return {
    candidate_id: 'cup-exact', direction: 'BULLISH', state: 'BREAKOUT',
    left_rim: { pivot_at: '2025-11-01T07:00:00Z', confirmed_at: '2025-11-02T07:00:00Z', price: 12 },
    bottom: { pivot_at: '2025-12-01T07:00:00Z', confirmed_at: '2025-12-02T07:00:00Z', price: 8 },
    right_rim: { pivot_at: '2026-01-01T07:00:00Z', confirmed_at: '2026-01-02T07:00:00Z', price: 11.8 },
    handle_start_at: '2026-01-01T07:00:00Z',
    handle_extreme: { pivot_at: '2026-01-03T07:00:00Z', confirmed_at: '2026-01-04T07:00:00Z', price: 10.8 },
    pivot_price: 11.9, pivot_frozen_at: '2026-01-05T07:00:00Z',
    confirmed_at: '2026-01-05T07:00:00Z', first_seen_at: '2026-01-03T07:00:00Z',
    state_changed_at: '2026-01-07T07:00:00Z', score: 80,
    score_breakdown: { pretrend: 20, cup_geometry: 20, u_shape_purity: 15, handle_quality: 15, volume_structure: 10 },
    hard_failures: [], diagnostics: [],
    volume_facts: { right_leg_median: 100, handle_median: 70, handle_baseline_median: 90, handle_right_ratio: 0.7, handle_baseline_ratio: 0.78 },
    formula_version: 'newow_cup_handle_v1',
  }
}
