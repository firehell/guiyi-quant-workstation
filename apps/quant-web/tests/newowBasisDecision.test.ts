import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync, existsSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import { cdtDecide, deriveBasisDecision } from '../src/utils/newowBasisDecision.ts'
const rawStates = ['holding','cleared','idle'] as const
const states = {holding:'hold',cleared:'sell',idle:'wait'}
const expected = {
 holding:{holding:['UU','建仓','ok',false],cleared:['UD','等待','tip',true],idle:['UN','等待','tip',false]},
 cleared:{holding:['DU','减仓','tip',false],cleared:['DD','空仓','violate',false],idle:['DN','空仓','tip',false]},
 idle:{holding:['N','等待','tip',false],cleared:['N','等待','tip',false],idle:['N','等待','tip',false]},
} as const
const fixture=(family='trend',direction='hold',execution='sell',basis='week')=>{
 const frequencies=basis==='day'?['1d','60m']:['1w','1d'], roles=basis==='day'?['day','m60']:['week','day']
 return {cdv2:{as_of:'2026-10-08T07:00:00Z',trend_state:{week:'down',day:'down'},facts:roles.map((role,i)=>({role:family+'_'+role,frequency:frequencies[i],state:i?execution:direction,status:'ready',bar_end:'2026-10-08T06:00:00Z',physical_contract:'RB2701',segment_id:'same-owner',age:0,source_category:'canonical',reason:null}))},prices:null} as any
}
for(const D of rawStates)for(const X of rawStates){
 test('cdt '+D+'/'+X,()=>{const v=cdtDecide(D,X);assert.deepEqual([v.row,v.action,v.strength,v.conflict],expected[D][X])})
 for(const basis of ['week','day'] as const)for(const family of ['trend','oscillation'])test(basis+' '+family+' '+D+'/'+X,()=>{
  const input=fixture(family,states[D],states[X],basis),v=deriveBasisDecision(input,family,basis)!
  assert.deepEqual([v.row,v.action,v.strength,v.conflict],expected[D][X]);assert.equal(v.directionFact,input.cdv2.facts[0]);assert.equal(v.executionFact,input.cdv2.facts[1])
  assert.equal(v.dirFull,basis==='week'?'周线':'日线');assert.equal(v.execFull,basis==='week'?'日线':'60分');assert.equal(v.basis,basis);assert.ok(v.reason);assert.ok(v.stance.label)
 })
}
test('buy is holding; wait is neutral despite CDV2 normalized down',()=>{
 assert.equal(deriveBasisDecision(fixture('trend','buy','buy'),'trend')?.row,'UU')
 assert.equal(deriveBasisDecision(fixture('trend','wait','sell'),'trend')?.row,'N')
})
test('dual follows its dominant bucket; unsupported strategies return null',()=>{
 const input=fixture();input.cdv2.facts.push(...fixture('oscillation','sell','hold').cdv2.facts)
 assert.equal(deriveBasisDecision(input,'dual','week','oscillation')?.row,'DU')
 for(const d of ['trend',null] as const)assert.equal(deriveBasisDecision(input,'dual','week',d)?.row,'UD')
 for(const s of ['main_rise','scenario','pattern','unsupported'])assert.equal(deriveBasisDecision(input,s),null)
 assert.equal(deriveBasisDecision(null,'trend'),null)
})
test('invalid facts fail closed',()=>{
 const mutations=[
 (v:any)=>v.cdv2.facts.pop(),(v:any)=>v.cdv2.facts.push({...v.cdv2.facts[0]}),
 (v:any)=>v.cdv2.facts[0].status='partial',(v:any)=>v.cdv2.facts[0].state=null,(v:any)=>v.cdv2.facts[0].state='reduce',
 (v:any)=>v.cdv2.facts[0].physical_contract='',(v:any)=>v.cdv2.facts[0].segment_id=null,
 (v:any)=>v.cdv2.facts[1].physical_contract='RB2610',(v:any)=>v.cdv2.facts[1].segment_id='other',
 (v:any)=>v.cdv2.facts[0].frequency='60m',(v:any)=>v.cdv2.facts[0].role='trend_m60',
 (v:any)=>v.cdv2.facts[0].bar_end=null,(v:any)=>v.cdv2.facts[0].bar_end='bad',
 (v:any)=>v.cdv2.facts[0].bar_end='2026-10-08T07:00:01Z',(v:any)=>v.cdv2.as_of='bad']
 for(const mutate of mutations){const input=fixture();mutate(input);assert.equal(deriveBasisDecision(input,'trend'),null)}
})
test('exact as_of valid; no mutation',()=>{
 const input=fixture();input.cdv2.facts[0].bar_end=input.cdv2.as_of;const before=JSON.stringify(input)
 assert.equal(deriveBasisDecision(input,'trend')?.row,'UD');assert.equal(JSON.stringify(input),before)
})
const source=process.env.NEWOW_PUBLIC_SOURCE
test('frozen v3.3.79 oracle for nine combinations',{skip:!source||!existsSync(source)},()=>{
 const html=readFileSync(source!,'utf8')
 const constants=['CDT_REASON','CDT_STANCE'].map(name=>html.match(new RegExp('var '+name+' = \\{[\\s\\S]*?\\n    \\};'))![0]).join('\n')
 const functions=['cdtBucket3','cdtDecide','cdtTriggerText'].map(name=>html.match(new RegExp('function '+name+'\\([^]*?\\n    \\}'))![0]).join('\n')
 const oracle=runInNewContext(constants+'\n'+functions+'\n({decide:cdtDecide,reasons:CDT_REASON,stances:CDT_STANCE,trigger:cdtTriggerText})')
 for(const D of rawStates)for(const X of rawStates){
  const a=cdtDecide(D,X),e=oracle.decide(D,X);assert.deepEqual([a.row,a.action,a.strength,a.conflict],[e.row,e.action,e.strength,e.conflict])
  for(const basis of ['week','day'] as const){
   const d=deriveBasisDecision(fixture('trend',states[D],states[X],basis),'trend',basis)!
   assert.equal(d.reason,oracle.reasons[d.row]);assert.equal(JSON.stringify(d.stance),JSON.stringify(oracle.stances[d.row]))
   assert.equal(d.strengthText,oracle.trigger(d.row,d.dirFull,d.execFull))
  }
 }
})
