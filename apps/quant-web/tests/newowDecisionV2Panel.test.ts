import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import test from 'node:test'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { compileScript, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import { createRenderer, defineComponent, h, nextTick, ref } from 'vue'

const sourceRoot = fileURLToPath(new URL('../src/', import.meta.url))
const mockUrl = `data:text/javascript;base64,${Buffer.from(`export class NewowProductRequestError extends Error { constructor(code,classification) { super(code); this.classification=classification; } } export const calls=[]; export function getNewowProductSection(request, options) { return new Promise((resolve, reject) => calls.push({request, options, resolve, reject})); }`).toString('base64')}`
const mock = await import(mockUrl)
async function componentUrl(name: string): Promise<string> {
  const source = readFileSync(new URL(`../src/components/market/detail/${name}.vue`, import.meta.url), 'utf8')
  const { descriptor } = parse(source)
  const compiled = compileScript(descriptor, { id: 'dual-test', inlineTemplate: true })
  const nested = compiled.content.includes('./NewowStatusCard.vue') ? await componentUrl('newow/NewowStatusCard') : null
  const pathPanel = compiled.content.includes('./NewowDailyWeeklyPath.vue') ? await componentUrl('newow/NewowDailyWeeklyPath') : null
  const code = ts.transpileModule(compiled.content, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
    .replace(/from ['"]\.\/NewowStatusCard\.vue['"]/g, `from '${nested}'`)
    .replace(/from ['"]\.\/NewowDailyWeeklyPath\.vue['"]/g, `from '${pathPanel}'`)
    .replace(/from ['"]vue['"]/g, `from '${import.meta.resolve('vue')}'`)
    .replace(/from ['"]@\/api\/newowProduct['"]/g, `from '${mockUrl}'`)
    .replace(/from ['"]@\/([^'"]+)['"]/g, (_match, specifier: string) => {
      for (const suffix of ['', '.ts']) {
        const path = resolve(sourceRoot, `${specifier}${suffix}`)
        if (existsSync(path)) return `from '${pathToFileURL(path).href}'`
      }
      throw new Error(specifier)
    })
  return `data:text/javascript;base64,${Buffer.from(code).toString('base64')}`
}
async function component(name: string) { return (await import(await componentUrl(name))).default }
const input = (product = 'jm') => ({ meta: { identity: { product, strategy: 'trend', frequency: '1d' }, as_of: '2026-09-26T15:00:00Z', snapshot_token: product + '-snapshot' } })
const output = () => ({ section: 'explanation', value: { decision_v2: { cdv2: {
  formula_version: 'test', as_of: '2026-09-24T07:00:00Z', total: 78, action: '参考持有', resonance: 'R4', mismatch: null, mismatch_age: -1,
  trend_bias: 'bullish', oscillation_bias: 'bullish', reference_exposure_range: '0–50%', missing_roles: ['trend_m60','oscillation_m60'], scores: {}, deductions: {}, cert_extra: 0, extra_sources: {}, volatility_pct: null,
  facts: ['trend_day','oscillation_day','trend_week','oscillation_week','trend_m60','oscillation_m60'].map(role => ({ role, state: 'hold', status: role.endsWith('m60') ? 'unavailable' : 'ready', age: role.endsWith('day') ? 0 : 2, frequency: role.endsWith('week') ? '1w' : '1d', bar_end: '2026-09-24T07:00:00Z', physical_contract: 'JM2701', segment_id:'owner', reason: null })),
}, prices: null } } })

test('daily/weekly card exposes states, ages and two-period R4 scope; refresh and identity discard stale output', async () => {
  const Panel = await component('newow/NewowDecisionV2Panel')
  const response = ref(input())
  const root = element('root')
  const app = createRenderer(nodeOperations()).createApp(defineComponent({ setup: () => () => h(Panel, { response: response.value }) }))
  app.mount(root)
  assert.match(nodeText(root), /正在读取同一快照/)
  assert.equal(mock.calls.length, 1)
  const button = () => findNode(root, n => n.props['aria-label'] === '刷新综合决策')!
  assert.equal(mock.calls[0].request.snapshotToken, undefined)
  mock.calls[0].resolve(output())
  await nextTick(); await nextTick()
  const states = findNode(root, n => n.props['aria-label'] === '日周小时策略状态与信号年龄')!
  assert.match(nodeText(states), /周线趋势.*持有.*2 根周K.*日线趋势.*持有.*0 根日K/)
  assert.equal(findNodes(states, n => n.type === 'article').length, 6)
  response.value = { ...input(), value: { bars: [] } } as any
  await nextTick()
  assert.equal(mock.calls.length, 1, 'same snapshot chart paging must not trigger another composite read')
  const reasons = findNode(root, n => n.props['aria-label'] === '共振与错配依据')!
  assert.match(nodeText(reasons), /参与周期以已完成事实列表为准/)
  assert.match(nodeText(root), /未命中 MM1–MM4/)
  ;(button().props.onClick as Function)()
  await nextTick()
  assert.doesNotMatch(nodeText(root), /78\s*分/)
  mock.calls[1].reject(new mock.NewowProductRequestError('NEWOW_RESOURCE_BUSY','busy'))
  await nextTick(); await nextTick()
  assert.match(nodeText(root), /图表仍在计算/)
  ;(button().props.onClick as Function)()
  response.value = input('rb')
  await nextTick()
  assert.equal(mock.calls[2].options.signal.aborted, true)
  assert.equal(mock.calls[3].request.identity.product, 'rb')
  mock.calls[2].resolve(output())
  await nextTick(); await nextTick()
  assert.doesNotMatch(nodeText(root), /78\s*分/)
  app.unmount()
})

test('composite card keeps scored header, five components, first action and independently folded evidence', async () => {
  const stored = new Map<string,string>()
  Object.defineProperty(globalThis,'localStorage',{configurable:true,value:{getItem:(k:string)=>stored.get(k)??null,setItem:(k:string,v:string)=>stored.set(k,v)}})
  const Panel = await component('newow/NewowDecisionV2Panel')
  const root = element('root'), response = ref(input('cu')), before = mock.calls.length
  const renderer = createRenderer(nodeOperations())
  const app = renderer.createApp(defineComponent({setup:()=>()=>h(Panel,{response:response.value})}))
  app.mount(root)
  const payload=output()
  Object.assign(payload.value.decision_v2.cdv2, { total:65, action:'回补窗口·分批建仓', action_code:'MM4', resonance:'R2', mismatch:'MM4', mismatch_age:0,
    scores:{trend:24,oscillation:22,resonance:10,direction:12,volatility:-3}, certainty_cap:50,resonance_cap:30,reference_exposure_cap:30,reference_exposure_range:'10%–30%',volatility_pct:'2.5',volatility_level:'mid',
    trend_state:{week:'up',day:'up',m60:'unknown'}, oscillation_state:{week:'holding',day:'cleared',m60:'idle'},
    presentation:{version:'guiyi_cdv2_daily_weekly_hourly_presentation_v1',scope:'daily_weekly_hourly',advice:'趋势最新一根上穿 MA10，观察回补。',first_action:{rule_token:'daily_oscillation_cleared',level:'warn',title:'震荡日线已清仓 · 趋势建仓',detail:'等待回补信号。',source_formula_version:'first-action'}} })
  mock.calls[before].resolve(payload); await nextTick(); await nextTick()
  const header=()=>findNode(root,n=>n.props['aria-label']==='展开综合决策'||n.props['aria-label']==='收起综合决策')!
  const body=findNode(root,n=>n.props.class==='decision-v2__body')!
  assert.equal(header().props['aria-expanded'],false)
  assert.equal(body.style.display,'none')
  assert.match(nodeText(header()),/综合决策.*65 分.*中等确定性.*共振 R2.*错配 MM4/)
  ;(header().props.onClick as Function)(); await nextTick()
  assert.equal(header().props['aria-expanded'],true); assert.notEqual(body.style.display,'none')
  assert.equal(stored.get('guiyi_newow_composite_collapsed'),'0')
  const scores=findNode(root,n=>n.props['aria-label']==='综合决策五项评分')!
  assert.equal(findNodes(scores,n=>n.props.class==='decision-v2__score').length,5)
  assert.match(nodeText(scores),/24.*趋势一致.*22.*震荡确认.*10.*共振.*12.*方向拐点.*-3.*波动折损/)
  assert.match(nodeText(root),/震荡日线已清仓.*错配期·趋势转多.*最新一根日K.*10%–30%/)
  const evidence=()=>findNode(root,n=>n.props['aria-label']==='展开综合依据'||n.props['aria-label']==='收起综合依据')!
  const details=findNode(root,n=>n.props.class==='decision-v2__evidence')!
  assert.equal(evidence().props['aria-expanded'],false); assert.equal(details.style.display,'none')
  ;(evidence().props.onClick as Function)(); await nextTick()
  assert.equal(evidence().props['aria-expanded'],true)
  assert.match(nodeText(details),/2.5%.*日周小时共同参与/)
  response.value=input('rb'); await nextTick()
  assert.doesNotMatch(nodeText(root),/65 分|错配 MM4|回补窗口/)
  ;(header().props.onClick as Function)(); await nextTick(); app.unmount()
  const second=element('root'), app2=renderer.createApp(defineComponent({setup:()=>()=>h(Panel,{response:input('al')})}))
  app2.mount(second)
  assert.equal(findNode(second,n=>n.props['aria-label']==='展开综合决策')!.props['aria-expanded'],false)
  app2.unmount(); delete (globalThis as any).localStorage
})

test('status card has independent folding, preference restore, explanatory expansion and oscillation facts', async () => {
  const Card = await component('newow/NewowStatusCard')
  const stored = new Map<string,string>()
  Object.defineProperty(globalThis,'localStorage',{configurable:true,value:{getItem:(k:string)=>stored.get(k)??null,setItem:(k:string,v:string)=>stored.set(k,v)}})
  const payload = output().value.decision_v2
  const decision = ref(payload), strategy=ref('trend')
  const root=element('root')
  const renderer=createRenderer(nodeOperations())
  const app=renderer.createApp(defineComponent({setup:()=>()=>h(Card,{decision:decision.value,strategy:strategy.value,loading:false,error:''})}))
  app.mount(root)
  const header=()=>findNode(root,n=>n.props.class==='newow-status-card__header')!
  assert.equal(header().props['aria-expanded'],true)
  assert.match(nodeText(root),/上涨趋势/)
  ;(header().props.onClick as Function)(); await nextTick()
  assert.equal(header().props['aria-expanded'],false)
  assert.equal(stored.get('guiyi_newow_status_card_collapsed'),'1')
  const explain=()=>findNode(root,n=>n.type==='button'&&typeof n.props.class==='string'&&n.props.class.startsWith('newow-status-card__explanation'))!
  ;(header().props.onClick as Function)(); await nextTick()
  ;(explain().props.onClick as Function)(); await nextTick()
  assert.equal(explain().props['aria-expanded'],true)
  strategy.value='oscillation'; await nextTick()
  assert.equal(explain().props['aria-expanded'],false)
  assert.match(nodeText(root),/多周期感知.*日周小时策略状态/)
  const periodRows=findNodes(root,n=>n.props.class==='newow-status-card__period')
  assert.equal(periodRows.length,3)
  assert.match(nodeText(root),/震荡名称采用周日小时组合/)
  ;(header().props.onClick as Function)(); await nextTick(); app.unmount()
  const second=element('root'), app2=renderer.createApp(defineComponent({setup:()=>()=>h(Card,{decision:null,strategy:'trend',loading:false,error:'读取失败'})}))
  app2.mount(second)
  assert.equal(findNode(second,n=>n.props.class==='newow-status-card__header')!.props['aria-expanded'],false)
  assert.doesNotMatch(nodeText(second),/上涨趋势/)
  app2.unmount(); delete (globalThis as any).localStorage
})

interface TestNode { type: string; props: Record<string, unknown>; parent: TestNode | null; children: TestNode[]; text: string; style: Record<string,unknown> }
function element(type: string): TestNode { return { type, props: {}, parent: null, children: [], text: '', style:{} } }
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

test('daily weekly path reuses decision snapshot and folds independently with explicit source prices', async () => {
  const Panel = await component('newow/NewowDecisionV2Panel')
  const root = element('root')
  const app = createRenderer(nodeOperations()).createApp(defineComponent({ setup: () => () => h(Panel, { response: input() }) }))
  const before = mock.calls.length
  app.mount(root)
  const payload = output() as any
  const price = (raw: string, frequency: string, category: string) => ({ raw,frequency,source_category:category,bar_end:'2026-09-24T07:00:00Z',physical_contract:'JM2701',segment_id:'owner',calculation_segment_id:frequency+'-calc',source_identity:'source' })
  payload.value.decision_v2.daily_weekly_path = {version:'guiyi_daily_weekly_path_v1',page_parity:true,executable:false,periods:[
    {frequency:'1w',state:'hold',status:'ready',cost:{...price('90','1w','canonical_strategy_build'),entry_marker_id:'weekly-entry'},current:price('110','1d','canonical_completed_close'),target:price('160','1w','canonical_channel'),reason:null},
    {frequency:'1d',state:'wait',status:'partial',cost:null,current:price('110','1d','canonical_completed_close'),target:null,reason:'FLAT_NO_OPEN_ENTRY'},
  ]}
  mock.calls[before].resolve(payload)
  await nextTick(); await nextTick()
  const section = findNode(root,n=>n.props['aria-label']==='日周路径示意图')!
  const toggle = findNode(section,n=>n.type==='button')!
  assert.equal(toggle.props['aria-expanded'],false)
  ;(toggle.props.onClick as Function)()
  await nextTick()
  assert.equal(toggle.props['aria-expanded'],true)
  assert.equal(mock.calls.length,before+1)
  assert.match(nodeText(section),/周线 \[持有\].*日线 \[观望\]/)
  assert.match(nodeText(section),/周线成本 90/)
  assert.match(nodeText(section),/BUILD weekly-entry/)
  assert.match(nodeText(section),/空仓，无当前建仓成本/)
  const solid = findNodes(section,n=>n.type==='path' && Number(n.props['stroke-width'])===2.5 && !n.props['stroke-dasharray'])
  const dashed = findNodes(section,n=>n.type==='path' && n.props['stroke-dasharray']==='7 5')
  assert.equal(solid.length,1)
  assert.equal(dashed.length,1)
  app.unmount()
})


test('hourly fact colors follow hourly states independently of daily direction', async () => {
  const Panel=await component('newow/NewowDecisionV2Panel'), root=element('root')
  const base=mock.calls.length
  const app=createRenderer(nodeOperations()).createApp(defineComponent({setup:()=>()=>h(Panel,{response:input()})}))
  app.mount(root)
  const payload=output() as any
  payload.value.decision_v2.cdv2.trend_state={week:'up',day:'up',m60:'down'}
  payload.value.decision_v2.cdv2.oscillation_state={week:'holding',day:'holding',m60:'cleared'}
  for (const f of payload.value.decision_v2.cdv2.facts) if(f.role.endsWith('m60')) {f.status='ready';f.state='wait';f.frequency='60m'}
  mock.calls[base].resolve(payload); await nextTick(); await nextTick()
  const states=findNode(root,n=>n.props['aria-label']==='日周小时策略状态与信号年龄')!
  const rows=findNodes(states,n=>n.type==='article')
  const hour=rows.filter(n=>nodeText(n).includes('60分钟'))
  assert.equal(hour.length,2)
  assert.ok(hour.every(n=>n.props.style.color==='#34c759'))
  assert.ok(rows.filter(n=>nodeText(n).includes('日线')).every(n=>n.props.style.color==='#ff3b30'))
  app.unmount()
})
