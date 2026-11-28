import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { compileScript, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import { createRenderer, defineComponent, h, nextTick, ref } from 'vue'

const products = ['jm','lc','rb','sa','fg','ma','ec','v','pr','ta','ur','sh','sc','cj','oi','i']
const moduleUrl = (source: string) => `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`
async function loadPage() {
  const vue = import.meta.resolve('vue')
  const stub = moduleUrl(`import { defineComponent, h } from '${vue}'; export default defineComponent({setup(){return ()=>h('div')}})`)
  function compile(file: string, replacements: Record<string,string>) {
    const url = new URL(`../src/${file}`, import.meta.url)
    const { descriptor, errors } = parse(readFileSync(url, 'utf8'), { filename: url.pathname })
    assert.deepEqual(errors, [])
    const compiled = compileScript(descriptor, { id: file, inlineTemplate: true })
    const code = ts.transpileModule(compiled.content, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
      .replace(/import ['"]@\/styles\/marketHome.css['"];?/g, '')
      .replace(/from ['"]([^'"]+)['"]/g, (_, name: string) => `from '${name === 'vue' ? vue : replacements[name] ?? name}'`)
    return moduleUrl(code)
  }
  const portfolio = compile('components/subing/SubingPortfolioWorkbench.vue', {
    './SubingReplayChart.vue': stub,
    './SubingTradeComparison.vue': compile('components/subing/SubingTradeComparison.vue', {
      './labels': new URL('../src/components/subing/labels.ts', import.meta.url).href,
    }),
    './labels': new URL('../src/components/subing/labels.ts', import.meta.url).href,
  })
  return (await import(compile('pages/research/SubingDecisionPage.vue', {
    '@/components/subing/SubingPortfolioWorkbench.vue': portfolio,
    '@/components/market/MarketNavigation.vue': stub,
    'vue-router': moduleUrl(`import { reactive } from '${vue}';
      let route;
      export function useRoute(){ route = reactive({query:{}}); return route }
      export function useRouter(){ return { push(to){route.query = to.query; return Promise.resolve()} } }`),
  }))).default
}
async function flush() { await new Promise(resolve => setImmediate(resolve)); await nextTick() }
function textOf(node: TestNode): string { return node.type === '#comment' ? '' : node.text + node.children.map(textOf).join(' ') }
function click(root: TestNode, title: string) {
  const button = findNode(root, node => node.type === 'button' && textOf(node) === title)
  assert.ok(button, `Missing button ${title}`)
  ;(button.props.onClick as () => void)()
}

test('mount and switching use only shared APIs, show all16 and preserve honest not-started values', async () => {
  const calls: string[] = [], original = globalThis.fetch
  globalThis.fetch = async input => {
    const url = String(input); calls.push(url)
    return new Response(JSON.stringify({status:url.endsWith('history')?'NOT_REGISTERED':'NOT_STARTED', products:[],account:{},auto_order:false}))
  }
  const app = createRenderer(nodeOperations()).createApp(await loadPage()), root = element('root')
  try {
    app.mount(root); await flush()
    assert.deepEqual(calls, ['/api/v1/subing-portfolio/status'])
    const list = findNode(root, node => node.props['aria-label'] === '品种列表')!
    assert.equal(list.children.filter(node => node.type === 'button').length, 16)
    for (const code of products) assert.ok(textOf(list).includes(code.toUpperCase()))
    const summary = findNode(root, node => node.props['aria-label'] === '共享账户摘要')!
    assert.ok(textOf(summary).includes('组合尚未启动'))
    assert.ok(!textOf(summary).includes('100,000')); assert.ok(textOf(summary).includes('—'))
    assert.ok(!textOf(root).includes('焦煤独立'))
    click(root, '历史回放'); await flush()
    assert.ok(textOf(root).includes('暂无已登记组合回放'))
    const upload = findNode(root, node => node.type === 'input' && node.props.type === 'file')!
    const header = {kind:'THREE_PRODUCT_RETROSPECTIVE_HISTORICAL_RESEARCH', matched:0, differences:0, trade_rows:0}
    await upload.props.onChange({target:{files:[new File([JSON.stringify(header)], 'trades.jsonl')]}})
    await flush()
    assert.ok(textOf(root).includes('退出分歧 0 组'))
    const fill = {rule:'A', fill_id:'same', contract:'JM2505', fill_at:'2026-01-02T02:01:00Z',
      match:'单侧入场', exit_reasons:null}
    const duplicate = [{...header, trade_rows:2}, fill, fill].map(row => JSON.stringify(row)).join('\n')
    await upload.props.onChange({target:{files:[new File([duplicate], 'duplicate.jsonl')]}})
    await flush()
    assert.ok(textOf(root).includes('读取失败，请选择逐笔说明'))
    assert.ok(!textOf(root).includes('退出分歧 0 组'))
    click(root, '持续模型'); await flush()
    assert.deepEqual(calls, ['/api/v1/subing-portfolio/status', '/api/v1/subing-portfolio/history', '/api/v1/subing-portfolio/status'])
  } finally { app.unmount(); globalThis.fetch = original }
})

test('shared equity, physical positions and historical cursor retain returned facts', async () => {
  const calls: string[] = [], original = globalThis.fetch
  globalThis.fetch = async input => {
    const url = String(input); calls.push(url)
    const history = url.includes('/history')
    return new Response(JSON.stringify({status:history?'HISTORICAL_RESULT':'RUNNING',run_id:history?'history-hash':'portfolio-run',auto_order:false,
      observed_at:'2026-11-19T02:00:00+00:00',day_net:'-23.5',
      account:{equity:'98765',margin:'15000',policy:{daily_loss_budget:'2000'}},
      products:[{product:'jm',enabled:true,accounts:[{contract:'JM2701',status:'OPEN',summary:{open_quantity:1},open_layers:[{side:'SHORT',price:'1000'}],latest_decision:{demand:'HOLD'}}]}],
      ...(history?{index:0,length:2,window:['2026-10-01','2026-11-01']}:{}),
    }))
  }
  const app = createRenderer(nodeOperations()).createApp(await loadPage()), root = element('root')
  try {
    app.mount(root); await flush()
    assert.ok(textOf(root).includes('98,765')); assert.ok(textOf(root).includes('15,000'))
    assert.ok(textOf(root).includes('JM2701')); assert.ok(textOf(root).includes('空头持仓'))
    assert.ok(textOf(root).includes('portfolio-run'))
    click(root,'历史回放'); await flush()
    assert.ok(textOf(root).includes('history-hash')); assert.ok(!textOf(root).includes('portfolio-run'))
    assert.ok(textOf(root).includes('当前回放时刻快照'))
    click(root,'下一步'); await flush()
    assert.equal(calls.at(-1),'/api/v1/subing-portfolio/history?index=1')
    assert.ok(calls.every(url=>url.startsWith('/api/v1/subing-portfolio/')))
  } finally { app.unmount(); globalThis.fetch=original }
})

interface TestNode {
  style?: { display: string }
  type: string
  parent: TestNode | null
  children: TestNode[]
  props: Record<string, unknown>
  text: string
}

function element(type: string): TestNode {
  return { style: { display: '' }, type, parent: null, children: [], props: {}, text: '' }
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

test('SuBing replay draws supplied OHLC or close-only history and releases its levels and chart series', async () => {
  const chartModule = moduleUrl(`
    export const paints = [], levels = new Set(), mounts = [], removed = []
    export const CandlestickSeries = { type: 'Candlestick' }, LineSeries = { type: 'Line' }
    export const ColorType = { Solid: 'solid' }, CrosshairMode = { Normal: 0 }, LineStyle = { Dashed: 2 }
    export function createChart(_container, options) {
      mounts.push(options)
      return {
        addSeries(definition, options) {
          const record = { type: definition.type, color: options.color, data: [] }
          paints.push(record)
          return {
            setData(data) { record.data = data },
            createPriceLine(level) { levels.add(level); return level },
            removePriceLine(level) { levels.delete(level) },
          }
        },
        removeSeries(series) { removed.push(series) },
        remove() { removed.push('chart') },
        timeScale() { return { fitContent() {} } },
      }
    }
  `)
  const api = await import(chartModule)
  const url = new URL('../src/components/subing/SubingReplayChart.vue', import.meta.url)
  const { descriptor, errors } = parse(readFileSync(url, 'utf8'), { filename: url.pathname })
  assert.deepEqual(errors, [])
  const compiled = compileScript(descriptor, { id: 'subing-replay', inlineTemplate: true })
  const imports: Record<string, string> = {
    vue: import.meta.resolve('vue'),
    '@guiyi/quant-chart': import.meta.resolve('@guiyi/quant-chart'),
    'lightweight-charts': chartModule,
    '@/utils/barTime': new URL('../src/utils/barTime.ts', import.meta.url).href,
  }
  const code = ts.transpileModule(compiled.content, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
    .replace(/from ['"]([^'"]+)['"]/g, (_, name: string) => `from '${imports[name] ?? name}'`)
  const Replay = (await import(moduleUrl(code))).default
  const rows = ref<Array<{ at: string; open?: string; high?: string; low?: string; close: string; ema21?: string }>>([
    { at: '2026-11-19T02:30:00Z', open: '100', high: '112', low: '97', close: '110', ema21: '104' },
  ])
  const target = ref<string | null>('120')
  const root = element('root')
  const app = createRenderer(nodeOperations()).createApp(defineComponent({
    setup: () => () => h(Replay, { rows: rows.value, stop: '96', target: target.value }),
  }))
  app.mount(root)
  await flush()
  assert.equal(api.mounts.length, 1)
  assert.equal(api.mounts[0].height, 390)
  assert.equal(api.paints.length, 5)
  assert.deepEqual(api.paints[0].data.map(({ open, high, low, close }) => [open, high, low, close]), [[100, 112, 97, 110]])
  assert.deepEqual(api.paints[4].data.map(({ value }) => value), [104])
  assert.deepEqual([...api.levels].map(({ price }) => price), [96, 120])

  rows.value = [{ at: '2026-11-19T03:00:00Z', close: '113' }]
  target.value = null
  await flush()
  assert.equal(api.paints[0].data.length, 0)
  assert.deepEqual(api.paints[1].data.map(({ value }) => value), [113])
  assert.deepEqual([...api.levels].map(({ price }) => price), [96])
  assert.match(textOf(root), /仅提供收盘线/)
  app.unmount()
  assert.equal(api.levels.size, 0)
  assert.equal(api.removed.length, 6)
  assert.equal(api.removed.at(-1), 'chart')
})
