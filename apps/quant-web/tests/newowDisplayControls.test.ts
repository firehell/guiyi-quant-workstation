import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {fileURLToPath,pathToFileURL} from 'node:url'
import {resolve} from 'node:path'
import {parse,compileScript} from '@vue/compiler-sfc'
import ts from 'typescript'
import {createRenderer,defineComponent,h,nextTick,ref} from 'vue'
async function component(path:string){
 const url=new URL(path,import.meta.url),root=fileURLToPath(new URL('../src/',import.meta.url))
 const code=ts.transpileModule(compileScript(parse(readFileSync(url,'utf8'),{filename:url.pathname}).descriptor,{id:'display-controls',inlineTemplate:true}).content,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText
 .replace(/from ['"]vue['"]/g,`from '${import.meta.resolve('vue')}'`).replace(/from ['"]@\/([^'"]+)['"]/g,(_m,s)=>`from '${pathToFileURL(resolve(root,s+'.ts')).href}'`)
 return (await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'))).default
}
const node=(type:string,text='')=>({type,text,props:{} as any,style:{display:''},children:[] as any[],parent:null as any})
const find=(n:any,p:(n:any)=>boolean):any=>p(n)?n:n.children.map((c:any)=>find(c,p)).find(Boolean)
const text=(n:any):string=>n.text+n.children.map(text).join('')
function renderer(){return createRenderer<any,any>({
 createElement:node,createText:(t)=>node('#text',t),createComment:(t)=>node('#comment',t),
 setText:(n,t)=>{n.text=t},setElementText:(n,t)=>{n.text=t;n.children=[]},patchProp:(n,k,_o,v)=>{n.props[k]=v},
 insert:(n,p,a)=>{n.parent=p;const i=a?p.children.indexOf(a):-1;if(i<0)p.children.push(n);else p.children.splice(i,0,n)},
 remove:(n)=>{if(n.parent)n.parent.children=n.parent.children.filter((c:any)=>c!==n)},parentNode:n=>n.parent,nextSibling:()=>null,
})}
test('11-cycle help lives in expanded main-rise status card, emits existing dialog event and revokes without facts',async()=>{
 const Card=await component('../src/components/market/detail/newow/NewowStatusCard.vue'),ready=ref(true),main=ref(true);let opened=0
 const root=node('root'),app=renderer().createApp(defineComponent({setup:()=>()=>h(Card,{decision:null,strategy:'main_rise',mainRiseBackground:main.value,magic11Ready:ready.value,loading:false,error:'',onMagic11:()=>opened++})}))
 app.mount(root);await nextTick()
 const help=()=>find(root,(n)=>n.type==='button'&&text(n)==='11周期 · 解读')
 assert.ok(help());help().props.onClick();assert.equal(opened,1)
 const header=find(root,n=>n.props.class==='newow-status-card__header');header.props.onClick();await nextTick()
 const body=find(root,n=>n.props.class==='newow-status-card__body');assert.equal(body.style.display,'none')
 header.props.onClick();await nextTick();assert.notEqual(body.style.display,'none')
 ready.value=false;await nextTick();assert.equal(help(),undefined)
 ready.value=true;main.value=false;await nextTick();assert.equal(help(),undefined)
 app.unmount()
})
