import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { compileScript, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import { createRenderer, nextTick } from 'vue'
const source=new URL('../src/components/kline/VolumeExplanation.vue',import.meta.url)
const script=compileScript(parse(readFileSync(source,'utf8'),{filename:source.pathname}).descriptor,{id:'volume',inlineTemplate:true})
const code=ts.transpileModule(script.content,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText
 .replace(/from ['"]vue['"]/g,`from '${import.meta.resolve('vue')}'`)
 .replace(/from ['"]@\/utils\/volumeDisplay['"]/g,`from '${new URL('../src/utils/volumeDisplay.ts',import.meta.url).href}'`)
const Component=(await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)).default
interface Node {type:string;props:Record<string,any>;text:string;children:Node[];parent:Node|null}
const node=(type:string,text=''):Node=>({type,props:{},text,children:[],parent:null})
const text=(n:Node):string=>[n.text,...n.children.map(text)].join(' ')
const find=(n:Node,match:(n:Node)=>boolean):Node|undefined=>match(n)?n:n.children.map(c=>find(c,match)).find(Boolean)
const renderer=createRenderer<Node,Node>({
 patchProp(n,k,_p,v){n.props[k]=v},createElement:node,createText:t=>node('#text',t),createComment:t=>node('#comment',t),
 setText(n,t){n.text=t},setElementText(n,t){n.text=t;n.children=[]},parentNode:n=>n.parent,
 nextSibling(n){return n.parent?.children[n.parent.children.indexOf(n)+1]??null},
 insert(n,p,a){if(n.parent)n.parent.children=n.parent.children.filter(c=>c!==n);n.parent=p;const i=a?p.children.indexOf(a):-1;if(i<0)p.children.push(n);else p.children.splice(i,0,n)},
 remove(n){if(n.parent)n.parent.children=n.parent.children.filter(c=>c!==n)},
})
const bars=Array.from({length:10},(_,i)=>({time:String(i),physicalContract:'JM2701',calculationSegmentId:'c',open:90,close:108,high:110,low:90,volume:100}))
test('shared explanation scores by default without strategy actions and supports selecting a retained bar',async()=>{
 const root=node('root'),app=renderer.createApp(Component,{bars,top:100}),instance=app.mount(root) as any
 find(root,n=>n.type==='button'&&text(n)==='黄色柱说明')!.props.onClick();await nextTick()
 assert.match(text(root),/下沿 90.00/);assert.match(text(root),/上沿 110.00/)
 assert.doesNotMatch(text(root),/建仓|清仓/)
 assert.match(text(root),/非策略信号/)
 instance.showAt('0');await nextTick();assert.match(text(root),/有效数据不足/)
 find(root,n=>n.props['aria-label']==='关闭成交量评分')!.props.onClick();await nextTick()
 assert.equal(find(root,n=>n.props.role==='dialog'),undefined)
 app.unmount()
})
test('preview disables scoring while keeping the same explanation',async()=>{
 const root=node('root'),app=renderer.createApp(Component,{bars,top:100,scoring:false});app.mount(root)
 find(root,n=>n.type==='button'&&text(n)==='黄色柱说明')!.props.onClick();await nextTick()
 assert.match(text(root),/当前柱不参与黄色评分/);assert.doesNotMatch(text(root),/下沿 90.00/)
 app.unmount()
})
