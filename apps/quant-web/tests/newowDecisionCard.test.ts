import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import { cardChain, cardMergedChain, cardPresentation, cardState, cardChipState, cardActionColor } from '../src/utils/newowDecisionCard.ts'
import { cdtDecide, deriveBasisDecision } from '../src/utils/newowBasisDecision.ts'

const witness=readFileSync(new URL('../e2e/fixtures/newow-composite-detail3449.html',import.meta.url),'utf8')
const reference:any={window:{},localStorage:{getItem:()=>null,setItem:()=>{}}}
runInNewContext(witness.match(/<script>([\s\S]*)<\/script>/)![1]!,reference)
const cutoff='2026-11-05T07:00:00Z'
const make=()=>({as_of:cutoff,total:70,resonance:'R3',mismatch:null,mismatch_age:-1,scores:{trend:30,oscillation:30,resonance:14,direction:4,volatility:-8},trend_state:{week:'down',day:'up',m60:'down'},oscillation_state:{week:'holding',day:'holding',m60:'cleared'},reference_exposure_cap:30,reference_exposure_range:'10%–30%',volatility_pct:'9.00',volatility_level:'high',facts:['trend','oscillation'].flatMap(axis=>['week','day','m60'].map(period=>({role:`${axis}_${period}`,state:period==='m60'?'sell':'hold',status:'ready',age:0,frequency:period==='week'?'1w':period==='day'?'1d':'60m',bar_end:cutoff,physical_contract:'JM2701',segment_id:'owner'})))}) as any
for(const family of ['trend','oscillation'])for(const basis of ['week','day'] as const)for(const D of ['hold','sell','wait'])for(const X of ['hold','sell','wait']) {
 test(`${family}/${basis} ${D}/${X} chain, action and conflict share facts`,()=>{
  const cd=make(), direction=basis==='week'?'week':'day',execution=basis==='week'?'day':'m60'
  cd.facts.find((f:any)=>f.role===`${family}_${direction}`).state=D
  cd.facts.find((f:any)=>f.role===`${family}_${execution}`).state=X
  const chain=cardChain(cd,family,basis),decision=deriveBasisDecision({cdv2:cd,prices:null},family,basis)!
  assert.deepEqual(chain.map(c=>c.period),basis==='week'?['week','day','m60']:['day','m60','week'])
  assert.equal(chain[0]!.fact,decision.directionFact);assert.equal(chain[1]!.fact,decision.executionFact)
  const raw=(s:string)=>s==='hold'?'holding':s==='sell'?'cleared':'idle'
  assert.deepEqual([decision.action,decision.conflict],[cdtDecide(raw(D),raw(X)).action,cdtDecide(raw(D),raw(X)).conflict])
  assert.deepEqual(cdtDecide(raw(D),raw(X)),JSON.parse(JSON.stringify(reference.cdtDecide(raw(D),raw(X)))))
 })
}
test('merge requires three equal known states, missing never becomes flat',()=>{
 const cd=make();cd.facts.forEach((f:any)=>f.state='hold')
 assert.equal(cardMergedChain(cardChain(cd,'oscillation','day')),'周 / 日 / 60分 均在持股（三周期同向）')
 cd.facts[3].status='unavailable';assert.equal(cardState(cd.facts[3]),'状态不可用');assert.equal(cardMergedChain(cardChain(cd,'oscillation','day')),null)
 assert.deepEqual(cardChain(cd,'main_rise','week'),[]);assert.deepEqual(cardChain(cd,'dual','week',null),[])
 assert.equal(cardChain(cd,'dual','week','oscillation')[0]!.fact!.role,'oscillation_week')
 const fact=make().facts[0]
 fact.state='buy';assert.equal(cardChipState('trend',fact),'建仓');assert.equal(cardChipState('oscillation',fact),'持股')
 fact.state='wait';assert.equal(cardChipState('trend',fact),'空仓');assert.equal(cardChipState('oscillation',fact),'清仓')
})

test('all 27 trend direction combinations match the frozen public render helper',()=>{
 for(const week of ['up','down','unknown'])for(const day of ['up','down','unknown'])for(const m60 of ['up','down','unknown']){
  const cd=make();cd.trend_state={week,day,m60}
  assert.deepEqual(cardPresentation(cd).direction,JSON.parse(JSON.stringify(reference.judgeDirJudge({trendState:cd.trend_state}))))
 }
})
test('source copy for resonance, mismatch, tiers, colors and volatility preserves numeric inputs',()=>{
 const cd=make(),before=structuredClone(cd)
 for(const r of ['R0','R1','R2','R3','R4']) {cd.resonance=r;const view=cardPresentation(cd);assert.ok(view.resonance.description);assert.equal(view.resonance.dots.length,5)}
 for(const mm of ['MM1','MM2','MM3','MM4']) {cd.mismatch=mm;cd.mismatch_age=0;const view=cardPresentation(cd);assert.ok(view.mismatch!.action);assert.match(view.mismatch!.ageLabel,/0 根/)}
 for(const [total,label] of [[0,'信号不足'],[40,'低确定性'],[60,'中等确定性'],[80,'高确定性']] as const) {cd.total=total;assert.equal(cardPresentation(cd).tier.label,label)}
 for(const level of ['low','mid','high']) {cd.volatility_level=level;assert.equal(cardPresentation(cd).volatility!.level,level)}
 Object.assign(cd,before);assert.match(cardPresentation(cd).direction.text,/周线下跌中的反弹/)
 assert.deepEqual(cd,before);assert.equal(cardActionColor('等待'),'#8e8e93');assert.equal(cardActionColor('建仓'),'#ff3b30');assert.equal(cardActionColor('空仓'),'#34c759')
})
