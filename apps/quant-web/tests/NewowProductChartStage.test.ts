import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import test from 'node:test'

import { compileScript, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import { createRenderer, defineComponent, h, nextTick, ref } from 'vue'

import {
  NEWOW_PRODUCT_CHART_ADAPTER_KEY,
  type NewowProductChartAdapter,
} from '../src/components/market/detail/newow/newowProductChartPrimitives.ts'
import type { NewowProductSectionResponse } from '../src/types/newowProduct.ts'

const componentUrl = new URL('../src/components/market/detail/newow/NewowProductChartStage.vue', import.meta.url)
const sourceRoot = fileURLToPath(new URL('../src/', import.meta.url))

test('emits stable signal selection and preserves an established viewport and focus when earlier data arrives', async () => {
  const Stage = await loadComponent()
  let range = { from: 0, to: 1 }
  let rangeListener: ((value: typeof range) => void) | undefined
  let clickListener: ((value: { hoveredInfo: { objectKind: string; objectId: string } }) => void) | undefined
  let loads = 0
  const selected: string[] = []
  const focused: string[] = []
  const scale = {
    fitContent() {},
    setVisibleLogicalRange(value: typeof range) { range = value },
    getVisibleLogicalRange: () => range,
    scrollToRealTime() {},
    subscribeVisibleLogicalRangeChange(callback: typeof rangeListener) { rangeListener = callback },
    unsubscribeVisibleLogicalRangeChange() { rangeListener = undefined },
  }
  const fakeChart = {
    addSeries: () => ({ setData() {} }), removeSeries() {}, timeScale: () => scale,
    subscribeClick(callback: typeof clickListener) { clickListener = callback },
    unsubscribeClick() { clickListener = undefined }, resize() {}, remove() {},
  }
  const response = ref(chartResponse())
  const selectedSignalId = ref<string | null>('build-stable')
  const stage = ref<{ revealSignal: (id: string) => boolean } | null>(null)
  const Host = defineComponent({ setup: () => () => h(Stage, {
    ref: stage, response: response.value, selectedSignalId: selectedSignalId.value,
    hasMoreBefore: true, loading: false,
    onLoadEarlier: () => { loads += 1 },
    'onSelect-signal': (id: string) => selected.push(id),
    'onFocus-resolved': (id: string) => focused.push(id),
  }) })
  const renderer = createRenderer(nodeOperations())
  const app = renderer.createApp(Host)
  app.provide(NEWOW_PRODUCT_CHART_ADAPTER_KEY, adapter(fakeChart))
  const root = element('root')

  app.mount(root)
  await nextTick()
  assert.equal(stage.value!.revealSignal('build-stable'), true)
  assert.deepEqual(focused, ['build-stable'])

  range = { from: 20, to: 21 }
  rangeListener!(range)
  range = { from: -1, to: 1 }
  rangeListener!(range)
  assert.equal(loads, 1)

  clickListener!({ hoveredInfo: { objectKind: 'series-marker', objectId: 'build-stable' } })
  clickListener!({ hoveredInfo: { objectKind: 'series-marker', objectId: 'unknown' } })
  assert.deepEqual(selected, ['build-stable'])

  range = { from: 0.25, to: 1.25 }
  rangeListener!(range)
  response.value = prependBar(response.value)
  await nextTick()
  assert.deepEqual(range, { from: 1.25, to: 2.25 }, 'prepended data must preserve the physical viewport')
  assert.deepEqual(focused, ['build-stable'], 'later data must not reset established focus')

  const chartRoot = findNode(root, (node) => node.props['data-testid'] === 'newow-product-chart-stage')!
  assert.equal(chartRoot.props['data-strategy'], 'oscillation')
  assert.equal(chartRoot.props['data-frequency'], '60m')
  assert.equal(chartRoot.props['data-selected-signal-id'], 'build-stable')
  app.unmount()
  assert.equal(rangeListener, undefined)
  assert.equal(clickListener, undefined)
})

test('renders action IDs, hint source and confirmation facts without owning a product or period selector', async () => {
  const Stage = await loadComponent()
  const source = readFileSync(componentUrl, 'utf8')
  assert.doesNotMatch(source, /defineModel|strategy-options|frequency-options|select-symbol/)
  const markerSets: Array<Array<{ id: string; text: string }>> = []
  const seriesData: unknown[][] = []
  const fakeChart = {
    addSeries: () => ({ setData(value: unknown[]) { seriesData.push(value) } }), removeSeries() {},
    timeScale: () => ({ fitContent() {}, setVisibleLogicalRange() {}, getVisibleLogicalRange: () => null, scrollToRealTime() {}, subscribeVisibleLogicalRangeChange() {}, unsubscribeVisibleLogicalRangeChange() {} }),
    subscribeClick() {}, unsubscribeClick() {}, resize() {}, remove() {},
  }
  const Host = defineComponent({ setup: () => () => h(Stage, { response: chartResponse(), selectedSignalId: null }) })
  const app = createRenderer(nodeOperations()).createApp(Host)
  app.provide(NEWOW_PRODUCT_CHART_ADAPTER_KEY, adapter(fakeChart, markerSets))
  const root = element('root')
  app.mount(root)
  await nextTick()

  assert.deepEqual(markerSets.flatMap((items) => items.map((marker) => marker.id)), ['build-stable', 'hint-stable'])
  assert.equal(seriesData.some((items) => items.some((item) => (
    typeof item === 'object' && item !== null && 'value' in item && item.value === 88
  ))), true, 'the Hint marker series must use anchor_price instead of candle/reference price')
  assert.ok(findNode(root, (node) => node.text.includes('JM2601 · segment-1')))
  assert.ok(findNode(root, (node) => node.text.includes('2026-08-15 16:30')))
  app.unmount()
})

function adapter(fakeChart: object, markerSets: Array<Array<{ id: string; text: string }>> = []): NewowProductChartAdapter {
  return {
    createChart: () => fakeChart as never,
    createSeriesMarkers: () => ({ setMarkers(markers: Array<{ id: string; text: string }>) { markerSets.push(markers) } }) as never,
    createResizeObserver: () => ({ observe() {}, disconnect() {} }),
  }
}

function chartResponse(): MutableChartResponse {
  const bars = [bar('2026-08-15T07:00:00Z', '2026-08-15')]
  return {
    meta: {
      schema_version: 'newow_product_detail_v1',
      identity: { product: 'jm', strategy: 'oscillation', frequency: '60m', series_kind: 'actual_dominant', profile_id: 'newow_product_oscillation_60m_v1', formula_versions: ['newow_hhv_llv_channel_page_v1', 'newow_oscillation_hhv_llv10_page_v1'] },
      as_of: '2026-08-15T09:00:00Z', read_at: '2026-08-15T09:00:01Z', input_content_sha256: 'a'.repeat(64), data_revision_identity: null,
      snapshot_token: 'snapshot-a', reference_model_version: 'newow_marker_reference_zero_cost_v1', futures_adaptation_version: 'newow_futures_segment_interrupt_v1',
    },
    section: 'chart', status: ready(), value: {
      chart_from: '2026-08-15', chart_through: '2026-08-15', page_identity: 'b'.repeat(64), bars,
      frames: [{ bar_end: bars[0]!.bar_end, main_state: 'BUILD', main_values: { upper: '110', lower: '90' }, status: ready(), action_ids: ['build-stable'], hint_ids: ['hint-stable'] }],
      actions: [{ signal_id: 'build-stable', kind: 'BUILD', bar_end: bars[0]!.bar_end, trading_day: bars[0]!.trading_day, reference_price: '90', physical_contract: 'JM2601', segment_id: 'segment-1', related_build_id: null, trade_eligibility: 'ELIGIBLE', sequence: 0 }],
      hints: [{ hint_id: 'hint-stable', kind: 'D4', bar_end: bars[0]!.bar_end, known_at: '2026-08-15T08:30:00Z', anchor_price: '88', physical_contract: 'JM2601', segment_id: 'segment-1', retrospective: false, quantity_effect: 'none', sequence: 1 }],
      diagnostics: [], next_before: 'older-page', repainting: false, formal_signal_eligible: true, allowed_uses: ['product_chart', 'reference_input'],
    },
  } as MutableChartResponse
}

function prependBar(response: MutableChartResponse): MutableChartResponse {
  const earlier = bar('2026-08-15T06:00:00Z', '2026-08-15')
  return {
    ...response,
    value: {
      ...response.value!,
      bars: [earlier, ...response.value!.bars],
      frames: [{ bar_end: earlier.bar_end, main_state: 'FLAT', main_values: { upper: '109', lower: '89' }, status: ready(), action_ids: [], hint_ids: [] }, ...response.value!.frames],
    },
  }
}

function bar(barEnd: string, tradingDay: string) {
  return { bar_end: barEnd, trading_day: tradingDay, open: '100', high: '110', low: '90', close: '101', volume: 10, open_interest: 20, physical_contract: 'JM2601', segment_id: 'segment-1', source_identity: 'canonical:jm:JM2601:60m', observation_eligible: true, completed: true as const }
}

function ready() { return { status: 'ready' as const, evidence_status: 'ACTIVE_CODE_VERIFIED' as const, reason_code: null } }

async function loadComponent() {
  const source = readFileSync(componentUrl, 'utf8')
  const { descriptor, errors } = parse(source, { filename: componentUrl.pathname })
  assert.deepEqual(errors, [])
  const compiled = compileScript(descriptor, { id: 'newow-product-stage', inlineTemplate: true })
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

interface TestNode { type: string; props: Record<string, unknown>; parent: TestNode | null; children: TestNode[]; text: string; clientWidth: number; clientHeight: number }
function element(type: string): TestNode { return { type, props: {}, parent: null, children: [], text: '', clientWidth: 800, clientHeight: 600 } }
function findNode(node: TestNode, match: (candidate: TestNode) => boolean): TestNode | undefined {
  if (match(node)) return node
  for (const child of node.children) { const found = findNode(child, match); if (found) return found }
  return undefined
}
function nodeOperations() {
  return {
    patchProp(node: TestNode, key: string, _previous: unknown, next: unknown) { node.props[key] = next },
    insert(child: TestNode, parent: TestNode, anchor: TestNode | null = null) { child.parent = parent; const index = anchor === null ? -1 : parent.children.indexOf(anchor); if (index < 0) parent.children.push(child); else parent.children.splice(index, 0, child) },
    remove(child: TestNode) { if (child.parent === null) return; child.parent.children = child.parent.children.filter((item) => item !== child); child.parent = null },
    createElement: (type: string) => element(type),
    createText(text: string) { const node = element('#text'); node.text = text; return node }, createComment(text: string) { const node = element('#comment'); node.text = text; return node },
    setText(node: TestNode, text: string) { node.text = text }, setElementText(node: TestNode, text: string) { node.text = text; node.children = [] },
    parentNode(node: TestNode) { return node.parent }, nextSibling(node: TestNode) { if (node.parent === null) return null; const index = node.parent.children.indexOf(node); return node.parent.children[index + 1] ?? null }, querySelector() { return null }, setScopeId() {}, insertStaticContent() { return [element('#static'), element('#static')] as const },
  }
}

type MutableChartResponse = Mutable<NewowProductSectionResponse<'chart'>>
type Mutable<T> = { -readonly [K in keyof T]: T[K] extends readonly (infer U)[] ? Mutable<U>[] : T[K] extends object ? Mutable<T[K]> : T[K] }
