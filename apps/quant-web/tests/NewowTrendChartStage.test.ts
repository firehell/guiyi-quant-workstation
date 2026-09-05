import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { resolve } from 'node:path'
import test from 'node:test'

import ts from 'typescript'
import { compileScript, parse } from '@vue/compiler-sfc'
import { createRenderer, defineComponent, h, nextTick, ref } from 'vue'
import { LineSeries } from 'lightweight-charts'

import {
  NEWOW_TREND_CHART_ADAPTER_KEY,
  type NewowTrendChartAdapter,
} from '../src/components/market/detail/newowTrendChartPrimitives.ts'
import type { BarData } from '../src/types/market.ts'
import type { NewowTrendDetailResponse } from '../src/types/newow.ts'

const componentUrl = new URL('../src/components/market/detail/NewowTrendChartStage.vue', import.meta.url)
const sourceRoot = fileURLToPath(new URL('../src/', import.meta.url))

test('connects paging, stable reveal, marker selection, follow latest, fullscreen and identity reset', async () => {
  const Stage = await loadComponent()
  let range = { from: 0, to: 1 }
  let rangeListener: ((value: typeof range) => void) | undefined
  let clickListener: ((value: { hoveredInfo: { objectKind: string; objectId: string } }) => void) | undefined
  let scrolls = 0
  let loads = 0
  const selected: string[] = []
  const focused: string[] = []
  const scale = {
    fitContent() {}, setVisibleLogicalRange(value: typeof range) { range = value },
    getVisibleLogicalRange: () => range, timeToCoordinate: () => 1,
    scrollToRealTime() { scrolls += 1 },
    subscribeVisibleLogicalRangeChange(callback: typeof rangeListener) { rangeListener = callback },
    unsubscribeVisibleLogicalRangeChange() { rangeListener = undefined },
  }
  const fakeChart = {
    panes: () => [{ setStretchFactor() {} }], addPane: () => ({ setStretchFactor() {} }),
    addSeries: () => ({ setData() {}, attachPrimitive() {} }), removeSeries() {},
    priceScale: () => ({ applyOptions() {} }), timeScale: () => scale,
    subscribeCrosshairMove() {}, unsubscribeCrosshairMove() {}, resize() {}, remove() {},
    subscribeClick(callback: typeof clickListener) { clickListener = callback },
    unsubscribeClick() { clickListener = undefined },
  }
  const data = ref<NewowTrendDetailResponse | null>(twoSegmentTrendData())
  data.value!.trend_markers = [{ marker_id: 'build-stable', marker_type: 'BUILD',
    bar_end: data.value!.bars[2]!.bar_end, price: 13, label: '建仓',
    formula_version: 'newow_trend_band_page_v2', facts: {} }]
  const identity = ref('rb:actual_dominant:1d')
  const focus = ref<string | null>(null)
  const bars = ref(data.value!.bars.map((bar) => genericBar(bar.trading_day, bar.close)))
  const stage = ref<{ revealTime: (time: string) => boolean } | null>(null)
  const Host = defineComponent({ setup: () => () => h(Stage, {
    ref: stage, data: data.value, genericBars: bars.value, identityKey: identity.value,
    focusBarEnd: focus.value, hasMoreBefore: true, loading: false,
    onLoadEarlier() { loads += 1 }, 'onMarker-select': (id: string) => selected.push(id),
    'onFocus-resolved': (time: string) => focused.push(time),
  }) })
  const app = createRenderer(nodeOperations()).createApp(Host)
  app.provide(NEWOW_TREND_CHART_ADAPTER_KEY, {
    createChart: () => fakeChart as never, createSeriesMarkers: () => ({ setMarkers() {} }) as never,
    createResizeObserver: () => ({ observe() {}, disconnect() {} }),
  })
  const root = element('root')
  app.mount(root)
  await nextTick()
  assert.equal(typeof rangeListener, 'function', 'range paging must be connected')
  rangeListener!(range)
  assert.equal(loads, 0, 'programmatic initial range must not drain the history')
  rangeListener!({ from: 30, to: 31 })
  rangeListener!({ from: -2, to: 1 })
  assert.equal(loads, 1)
  assert.equal(stage.value!.revealTime('2026-01-03T07:00:00Z'), true)
  assert.equal(stage.value!.revealTime('2020-01-03T07:00:00Z'), false)
  clickListener!({ hoveredInfo: { objectKind: 'series-marker', objectId: 'build-stable' } })
  clickListener!({ hoveredInfo: { objectKind: 'series-marker', objectId: 'unknown' } })
  clickListener!({ hoveredInfo: { objectKind: 'primitive', objectId: 'build-stable' } })
  assert.deepEqual(selected, ['build-stable'])
  focus.value = '2026-01-04T07:00:00Z'
  await nextTick()
  assert.deepEqual(focused, [focus.value])
  range = { from: 1, to: 2 }
  data.value = null
  bars.value = [genericBar('2026-01-01', 10), ...bars.value]
  await nextTick()
  assert.deepEqual(range, { from: 2, to: 3 }, 'prepend preserves the same physical viewport')
  let latest = findNode(root, (node) => node.type === 'button' && node.text === '回到最新')
  assert.ok(latest)
  ;(latest.props.onClick as () => void)()
  assert.equal(scrolls, 1)
  await nextTick()
  assert.equal(findNode(root, (node) => node.type === 'button' && node.text === '回到最新'), undefined)
  rangeListener!({ from: 0, to: 1 })
  identity.value = 'ag:actual_dominant:1d'
  focus.value = null
  bars.value = [genericBar('2026-01-06', 20)]
  await nextTick()
  assert.deepEqual(range, { from: 0, to: 0 })
  assert.equal(findNode(root, (node) => node.type === 'button' && node.text === '回到最新'), undefined)
  const chartRoot = findNode(root, (node) => node.props['data-testid'] === 'newow-trend-chart-stage')!
  let requested = 0
  Object.assign(chartRoot, { requestFullscreen: async () => { requested += 1 } })
  const previous = Object.getOwnPropertyDescriptor(globalThis, 'document')
  Object.defineProperty(globalThis, 'document', { configurable: true, value: { fullscreenElement: null } })
  try {
    const fullscreen = findNode(root, (node) => node.props['aria-label'] === '全屏图表')!
    await (fullscreen.props.onClick as () => Promise<void>)()
    assert.equal(requested, 1)
  } finally {
    if (previous) Object.defineProperty(globalThis, 'document', previous)
    else Reflect.deleteProperty(globalThis, 'document')
  }
  app.unmount()
  assert.equal(rangeListener, undefined)
  assert.equal(clickListener, undefined)
})

function findNode(node: TestNode, matches: (node: TestNode) => boolean): TestNode | undefined {
  if (matches(node)) return node
  for (const child of node.children) {
    const result = findNode(child, matches)
    if (result) return result
  }
  return undefined
}

test('mounts one chart and ResizeObserver, reuses them on update, and disposes them once', async () => {
  const Stage = await loadComponent()
  const calls = {
    create: 0, subscribe: 0, observe: 0,
    unsubscribe: 0, disconnect: 0, remove: 0,
  }
  const series = () => ({ setData() {}, attachPrimitive() {} })
  const fakeChart = {
    panes: () => [{ setStretchFactor() {} }],
    addPane: () => ({ setStretchFactor() {} }),
    addSeries: () => series(),
    priceScale: () => ({ applyOptions() {} }),
    timeScale: () => ({
      fitContent() {}, setVisibleLogicalRange() {}, timeToCoordinate: () => 1,
      getVisibleLogicalRange: () => null,
      subscribeVisibleLogicalRangeChange() {}, unsubscribeVisibleLogicalRangeChange() {},
    }),
    subscribeCrosshairMove: () => { calls.subscribe += 1 },
    subscribeClick() {}, unsubscribeClick() {},
    unsubscribeCrosshairMove: () => { calls.unsubscribe += 1 },
    resize() {},
    remove: () => { calls.remove += 1 },
  }
  const adapter: NewowTrendChartAdapter = {
    createChart: () => { calls.create += 1; return fakeChart as never },
    createSeriesMarkers: () => ({ setMarkers() {} }) as never,
    createResizeObserver: () => ({
      observe: () => { calls.observe += 1 },
      disconnect: () => { calls.disconnect += 1 },
    }),
  }
  const bars = ref<readonly BarData[]>([genericBar('2026-01-02', 11)])
  const Host = defineComponent({
    setup: () => () => h(Stage, { data: null, genericBars: bars.value }),
  })
  const renderer = createRenderer(nodeOperations())
  const app = renderer.createApp(Host)
  app.provide(NEWOW_TREND_CHART_ADAPTER_KEY, adapter)
  const root = element('root')

  app.mount(root)
  await nextTick()
  assert.deepEqual(calls, {
    create: 1, subscribe: 1, observe: 1,
    unsubscribe: 0, disconnect: 0, remove: 0,
  })

  bars.value = [genericBar('2026-01-02', 11), genericBar('2026-01-03', 12)]
  await nextTick()
  assert.deepEqual(calls, {
    create: 1, subscribe: 1, observe: 1,
    unsubscribe: 0, disconnect: 0, remove: 0,
  })

  app.unmount()
  assert.deepEqual(calls, {
    create: 1, subscribe: 1, observe: 1,
    unsubscribe: 1, disconnect: 1, remove: 1,
  })
})

test('renders each physical segment through separate B and C line series', async () => {
  const Stage = await loadComponent()
  const lineData: Array<Array<{ time: unknown }>> = []
  const fakeChart = {
    panes: () => [{ setStretchFactor() {} }],
    addPane: () => ({ setStretchFactor() {} }),
    addSeries: (definition: unknown) => {
      const data: Array<{ time: unknown }> = []
      if (definition === LineSeries) lineData.push(data)
      return {
        setData(values: Array<{ time: unknown }>) { data.splice(0, data.length, ...values) },
        attachPrimitive() {},
      }
    },
    removeSeries() {},
    priceScale: () => ({ applyOptions() {} }),
    timeScale: () => ({
      fitContent() {}, setVisibleLogicalRange() {}, timeToCoordinate: () => 1,
      getVisibleLogicalRange: () => null,
      subscribeVisibleLogicalRangeChange() {}, unsubscribeVisibleLogicalRangeChange() {},
    }),
    subscribeCrosshairMove() {}, unsubscribeCrosshairMove() {}, resize() {}, remove() {},
    subscribeClick() {}, unsubscribeClick() {},
  }
  const adapter: NewowTrendChartAdapter = {
    createChart: () => fakeChart as never,
    createSeriesMarkers: () => ({ setMarkers() {} }) as never,
    createResizeObserver: () => ({ observe() {}, disconnect() {} }),
  }
  const Host = defineComponent({
    setup: () => () => h(Stage, { data: twoSegmentTrendData(), genericBars: [] }),
  })
  const renderer = createRenderer(nodeOperations())
  const app = renderer.createApp(Host)
  app.provide(NEWOW_TREND_CHART_ADAPTER_KEY, adapter)

  app.mount(element('root'))
  await nextTick()

  assert.deepEqual(lineData.map((data) => data.map((point) => chartDay(point.time))), [
    ['2026-01-02', '2026-01-03'],
    ['2026-01-02', '2026-01-03'],
    ['2026-01-04', '2026-01-05'],
    ['2026-01-04', '2026-01-05'],
  ])
  app.unmount()
})

async function loadComponent() {
  const source = readFileSync(componentUrl, 'utf8')
  const { descriptor, errors } = parse(source, { filename: componentUrl.pathname })
  assert.deepEqual(errors, [])
  const compiled = compileScript(descriptor, { id: 'newow-trend-stage', inlineTemplate: true })
  const transpiled = ts.transpileModule(compiled.content, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
  }).outputText
    .replace(/from ['"]vue['"]/g, `from '${import.meta.resolve('vue')}'`)
    .replace(/from ['"]lightweight-charts['"]/g, `from '${import.meta.resolve('lightweight-charts')}'`)
    .replace(/from ['"]@\/([^'"]+)['"]/g, (_match, specifier: string) => {
      const path = resolveSourceImport(specifier)
      return `from '${pathToFileURL(path).href}'`
    })
  return (await import(`data:text/javascript;base64,${Buffer.from(transpiled).toString('base64')}`)).default
}

function resolveSourceImport(specifier: string): string {
  for (const suffix of ['', '.ts', '.vue']) {
    const path = resolve(sourceRoot, `${specifier}${suffix}`)
    if (existsSync(path)) return path
  }
  throw new Error(`cannot resolve source import: ${specifier}`)
}

interface TestNode {
  type: string
  parent: TestNode | null
  children: TestNode[]
  props: Record<string, unknown>
  text: string
  clientWidth: number
  clientHeight: number
}

function element(type: string): TestNode {
  return { type, parent: null, children: [], props: {}, text: '', clientWidth: 800, clientHeight: 600 }
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

function genericBar(day: string, close: number): BarData {
  return {
    time: `${day}T15:00:00+08:00`, trading_day: day,
    open: close - 1, high: close + 1, low: close - 2, close,
    volume: 100,
  }
}

function chartDay(time: unknown): string {
  const value = time as { year: number; month: number; day: number }
  return `${value.year}-${String(value.month).padStart(2, '0')}-${String(value.day).padStart(2, '0')}`
}

function twoSegmentTrendData(): NewowTrendDetailResponse {
  const bars: NewowTrendDetailResponse['bars'] = [
    apiBar('2026-01-02', 11, 'RB2605', 'segment-1'),
    apiBar('2026-01-03', 12, 'RB2605', 'segment-1'),
    apiBar('2026-01-04', 13, 'RB2610', 'segment-2'),
    apiBar('2026-01-05', 14, 'RB2610', 'segment-2'),
  ]
  return {
    meta: {
      strategy_code: 'newow_trend_v1', profile_id: 'newow_trend_d1_page_v2', frequency: '1d',
      series_kind: 'actual_dominant', calculation_identity: 'calculation',
      data_revision_identity: null, request_identity: 'request',
    },
    instrument: { product: 'rb', display_name: '螺纹钢', last_visible_physical_contract: 'RB2610' },
    bars,
    bar_policy: 'completed_only',
    trend_band: bars.map((bar, index) => ({
      bar_end: bar.bar_end,
      b_value: 10.5 + index,
      c_value: 9.8 + index,
      state: index < 2 ? 'BLUE' : 'YELLOW',
      state_before: index === 0 ? null : index < 2 ? 'BLUE' : 'YELLOW',
      transition: null,
    })),
    trend_markers: [], escape_markers: [], cup_markers: [], cup_handles: [],
    rollover_seams: [{
      trading_day: '2026-01-04', previous_contract: 'RB2605', next_contract: 'RB2610',
      previous_bar_end: bars[1]!.bar_end, next_bar_end: bars[2]!.bar_end,
      previous_segment_id: 'segment-1', next_segment_id: 'segment-2',
    }],
    legend: { BUILD: 'trend build', CLEAR: 'trend clear', D1: 'escape D1', D2: 'escape D2', D3: 'escape D3' },
    formula_descriptions: {
      trend_band: 'newow_trend_band_page_v2',
      escape: 'newow_escape_d123_page_v2',
      cup_handle: 'newow_cup_handle_v1',
    },
    warnings: [],
  }
}

function apiBar(
  day: string,
  close: number,
  physicalContract: string,
  segmentId: string,
): NewowTrendDetailResponse['bars'][number] {
  return {
    bar_end: `${day}T07:00:00Z`, trading_day: day,
    open: close - 1, high: close + 1, low: close - 2, close,
    volume: close + 20, open_interest: close + 120,
    physical_contract: physicalContract, segment_id: segmentId, source_identity: 'calculation',
  }
}
