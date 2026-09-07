import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { compileScript, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import { createRenderer, nextTick } from 'vue'

const pageUrl = new URL('../src/pages/market/index.vue', import.meta.url)

test('ordinary Market Home product clicks use fixed Newow Trend D1 identity', async () => {
  const pushes: unknown[] = []
  Object.assign(globalThis, { __marketHomeRoutePushes: pushes })
  const Page = await loadPage()
  const root = element('root')
  const app = createRenderer(nodeOperations()).createApp(Page)

  try {
    app.mount(root)
    await nextTick()
    const trigger = findNode(root, (node) => node.type === 'button' && node.text === 'OPEN_AG')
    assert.ok(trigger, 'Market Home table must expose its real product-open handler')
    ;(trigger.props.onClick as () => void)()

    assert.deepEqual(pushes, [{
      name: 'market-chart',
      query: {
        view: 'newow', symbol: 'ag', strategy: 'trend', series_kind: 'actual_dominant',
        contract: undefined, frequency: '1d', focus_bar_end: undefined,
      },
    }])
  } finally {
    app.unmount()
    Reflect.deleteProperty(globalThis, '__marketHomeRoutePushes')
  }
})

async function loadPage() {
  const source = readFileSync(pageUrl, 'utf8')
  const { descriptor, errors } = parse(source, { filename: pageUrl.pathname })
  assert.deepEqual(errors, [])
  const compiled = compileScript(descriptor, { id: 'market-home-route-test', inlineTemplate: true })
  const vueUrl = import.meta.resolve('vue')
  const plainComponent = moduleUrl(`
    import { defineComponent, h } from '${vueUrl}'
    export default defineComponent({ setup() { return () => h('div') } })
  `)
  const productComponent = moduleUrl(`
    import { defineComponent, h } from '${vueUrl}'
    export default defineComponent({
      emits: ['open'],
      setup(_props, { emit }) { return () => h('button', { onClick: () => emit('open', { symbol: 'ag' }) }, 'OPEN_AG') },
    })
  `)
  const routerModule = moduleUrl(`
    export function useRouter() {
      return { push(value) { globalThis.__marketHomeRoutePushes.push(value) } }
    }
  `)
  const naiveModule = moduleUrl(`
    import { defineComponent, h } from '${vueUrl}'
    export const NButton = defineComponent({ setup(_props, { slots }) { return () => h('button', slots.default?.()) } })
  `)
  const apiModule = moduleUrl('export async function getMarketHomeOverview() {}\nexport async function getCurrentAlertEvents() {}\nexport async function getRuntimeHealth() {}')
  const homeModule = moduleUrl(`
    import { ref } from '${vueUrl}'
    function resource(data = null) {
      return { data: ref(data), stale: ref(false), loading: ref(false), unavailable: ref(false), error: ref(null), refresh: async () => {} }
    }
    export function useMarketHome() {
      return { overview: resource(), runtime: resource(), events: resource(), refreshAll: async () => {}, start() {}, dispose() {} }
    }
  `)
  const viewModelModule = moduleUrl(`
    export function buildMarketHomeViewModel() {
      return { rows: [], overview: { availability: 'unavailable' }, runtime: { status: 'unavailable' }, events: { availability: 'unavailable' } }
    }
  `)
  const preferencesModule = moduleUrl(`
    export function loadMarketHomePreferences() {
      return { sector: '', sort: 'default', compactDensity: false, detailFrequency: '15m', focusRailCollapsed: false }
    }
    export function saveMarketHomePreferences() {}
  `)
  const workspaceModule = moduleUrl('export function filterAndSortMarketHomeRows(rows) { return rows }')
  const routesUrl = new URL('../src/utils/marketHomeRoutes.ts', import.meta.url).href
  const transpiled = ts.transpileModule(compiled.content, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
  }).outputText
    .replace(/from ['"]vue['"]/g, `from '${vueUrl}'`)
    .replace(/from ['"]vue-router['"]/g, `from '${routerModule}'`)
    .replace(/from ['"]naive-ui['"]/g, `from '${naiveModule}'`)
    .replace(/from ['"]@\/components\/market\/([^'"]+\.vue)['"]/g, (_match, file: string) => (
      `from '${file === 'MarketHomeTable.vue' || file === 'MarketHomeMobileList.vue' ? productComponent : plainComponent}'`
    ))
    .replace(/from ['"]@\/api\/(?:market|alerts|runtime)['"]/g, `from '${apiModule}'`)
    .replace(/from ['"]@\/composables\/useMarketHome['"]/g, `from '${homeModule}'`)
    .replace(/from ['"]@\/utils\/marketHomeViewModel['"]/g, `from '${viewModelModule}'`)
    .replace(/from ['"]@\/utils\/marketHomePreferences['"]/g, `from '${preferencesModule}'`)
    .replace(/from ['"]@\/utils\/marketHomeRoutes['"]/g, `from '${routesUrl}'`)
    .replace(/from ['"]@\/utils\/marketHomeWorkspace['"]/g, `from '${workspaceModule}'`)
  return (await import(moduleUrl(transpiled))).default
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
