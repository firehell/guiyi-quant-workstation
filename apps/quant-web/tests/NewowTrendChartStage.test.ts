import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { resolve } from 'node:path'
import test from 'node:test'

import ts from 'typescript'
import { compileScript, parse } from '@vue/compiler-sfc'
import { createRenderer, defineComponent, h, nextTick, ref } from 'vue'

import {
  NEWOW_TREND_CHART_ADAPTER_KEY,
  type NewowTrendChartAdapter,
} from '../src/components/market/detail/newowTrendChartPrimitives.ts'
import type { BarData } from '../src/types/market.ts'

const componentUrl = new URL('../src/components/market/detail/NewowTrendChartStage.vue', import.meta.url)
const sourceRoot = fileURLToPath(new URL('../src/', import.meta.url))

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
    }),
    subscribeCrosshairMove: () => { calls.subscribe += 1 },
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
