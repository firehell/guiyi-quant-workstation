import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { compileScript, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import { createRenderer } from 'vue'
import { validateOverview, type MonitorOverview, type MonitorTradingScope } from '../src/api/simulationMonitor.ts'

const products=['JM','LC','RB','SA','FG','MA','EC','V','PR','TA','UR','SH','SC','CJ','OI','I']
const scope=(status:'FLATTEN_PENDING'|'ACTIVE'):MonitorTradingScope=>({status,version:'scope-v1',products,
 pending_positions:status==='FLATTEN_PENDING'?[{product:'AP',contract:'AP701',quantity:2}]:[],
 pending_order_ids:[],pending_reservation_ids:[],native_readback_verified:status==='ACTIVE'})
const overview=(trading_scope?:MonitorTradingScope)=>({version:'simulation_monitor_v1',status:'available',snapshot:'one',generated_at:'2026-11-19T02:00:00Z',
 account:{key:'account',alias:'测试账户',environment:'fixture',strategy:'HTDY',scope_product:null,policy_version:'v1'},
 observer:{status:'running',stage:'ACTIVE',published_at:'2026-11-19T02:00:00Z',connection:'LOGGED_IN'},
 readback_at:'2026-11-19T02:00:00Z',trading_day:'20261119',readback_status:'verified',position_projection_complete:true,
 metrics:{},positions:[{id:'ap',product:'AP',contract:'AP701',side:'LONG',quantity:2,today:2,yesterday:0,frozen_long:0,frozen_short:0,position_profit:'0',status:'matched',as_of:'2026-11-19T02:00:00Z'}],
 curve:[],issues:[],issue_count:0,coverage:'complete',performance_status:'pending',source_times:{},...(trading_scope?{trading_scope}:{}),
} as MonitorOverview)
const moduleUrl=(source:string)=>`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`
const vueUrl=import.meta.resolve('vue')
const monitorUrl=moduleUrl(`import {ref} from '${vueUrl}'; export function useSimulationMonitor(){return {
 data:ref(globalThis.__scopeOverview),loading:ref(false),error:ref(null),selectedId:ref(null),detailLoading:ref(false),detailError:ref(null),detail:ref(null),
 start(){},dispose(){},setVisible(){},setQueryValid(){},setQuery(){},refresh(){},closeDetail(){}
}}`)
const source=readFileSync(new URL('../src/components/market/MarketHomeSimulation.vue',import.meta.url),'utf8')
const compiled=compileScript(parse(source).descriptor,{id:'simulation-scope',inlineTemplate:true})
const code=ts.transpileModule(compiled.content,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText
 .replace(/from ['"]vue['"]/g,`from '${vueUrl}'`)
 .replace(/from ['"]@\/composables\/useSimulationMonitor['"]/g,`from '${monitorUrl}'`)
 .replace(/from ['"]@\/([^'"]+)['"]/g,(_,name:string)=>`from '${new URL('../src/'+name+'.ts',import.meta.url).href}'`)
const Page=(await import(moduleUrl(code))).default
const text=(node:TestNode):string=>node.type==='#comment'?'':node.text+node.children.map(text).join(' ')

test('scope payload is optional and rejects malformed position facts',()=>{
 assert.ok(validateOverview(overview()))
 assert.ok(validateOverview(overview({status:'NOT_APPLIED',version:null})))
 assert.ok(validateOverview(overview(scope('FLATTEN_PENDING'))))
 assert.ok(validateOverview(overview(scope('ACTIVE'))))
 const short=scope('FLATTEN_PENDING');short.pending_positions[0].quantity=-1
 assert.ok(validateOverview(overview(short)))
 const invalid=overview(scope('ACTIVE'));(invalid.trading_scope as any).pending_positions=[{product:'AP',contract:'AP701',quantity:'2'}]
 assert.throws(()=>validateOverview(invalid),/MONITOR_RESPONSE_INVALID/)
})

test('scope notice preserves actual out-of-scope contract and all native holdings',()=>{
 const originalDocument=globalThis.document
 Object.assign(globalThis,{document:{visibilityState:'visible',addEventListener(){},removeEventListener(){}}})
 try{
  for(const current of [{status:'NOT_APPLIED',version:null} as MonitorTradingScope,scope('FLATTEN_PENDING'),scope('ACTIVE')]){
   Object.assign(globalThis,{__scopeOverview:overview(current)})
   const root=element('root'),body=element('body')
   const app=createRenderer({...nodeOperations(),querySelector:()=>body}).createApp(Page,{options:[]})
   try{
    app.mount(root)
    const notice=findNode(root,node=>node.props['aria-label']==='交易范围')!
    assert.ok(notice)
    if(current.status==='NOT_APPLIED'){
     assert.ok(text(notice).includes('交易范围尚未应用'))
     assert.ok(!text(notice).includes('范围收敛已核验'))
    }else{
     assert.ok(text(notice).includes('交易范围16品种'))
     if(current.status==='FLATTEN_PENDING'){
      assert.ok(text(notice).includes('范围外持仓待平仓'))
      assert.ok(text(notice).includes('AP701 2手'))
      assert.ok(text(notice).includes('柜台核验待完成'))
     }else assert.ok(text(notice).includes('范围收敛已核验'))
    }
    const positions=findNode(root,node=>node.type==='table'&&String(node.props.class).includes('simulation-positions'))!
    assert.ok(text(positions).includes('AP701'));assert.ok(text(positions).includes('AP'))
   }finally{app.unmount()}
  }
 }finally{Object.assign(globalThis,{document:originalDocument});Reflect.deleteProperty(globalThis,'__scopeOverview')}
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
