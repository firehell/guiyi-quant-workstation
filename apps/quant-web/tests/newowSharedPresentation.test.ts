import assert from 'node:assert/strict'
import test from 'node:test'
import { sharedChartForOwner, sharedDecisionForOwner } from '../src/utils/newowSharedPresentation.ts'
import { buildStatusCard } from '../src/utils/newowStatusCardPresentation.ts'
import type { NewowProductSectionResponse } from '../src/types/newowProduct'
import type { NewowDecisionV2 } from '../src/types/newowDecisionV2'
const owner = { asOf: '2026-10-09T07:00:00Z', physicalContract: 'RB2701', segmentId: 'owner' }
const chart = { meta: { as_of: owner.asOf }, value: { bars: [
  {bar_end:'a',physical_contract:'RB2701',segment_id:'owner'},
  {bar_end:'b',physical_contract:'RB2609',segment_id:'old'},
], frames:[{bar_end:'a'},{bar_end:'b'}] } } as unknown as NewowProductSectionResponse<'chart'>
const decision = { cdv2: { as_of:owner.asOf, trend_bias:'bullish', facts:['trend_day','trend_week','oscillation_day'].map(role => ({role,state:'hold',status:'ready',physical_contract:owner.physicalContract,segment_id:owner.segmentId})) },prices:null } as unknown as NewowDecisionV2

test('experiment shared chart is bound to the selected cutoff, contract and segment',()=>{
 const selected=sharedChartForOwner(chart,owner)!
 assert.deepEqual(selected.value!.bars.map(b=>b.bar_end),['a'])
 assert.deepEqual(selected.value!.frames.map(f=>f.bar_end),['a'])
 assert.equal(chart.value!.bars.length,2)
 for(const wrong of [null,{...owner,asOf:'other'},{...owner,segmentId:'old'},{...owner,physicalContract:null}]) assert.equal(sharedChartForOwner(chart,wrong),null)
})
test('shared explanation rejects stale and cross-contract facts without inventing missing prices',()=>{
 assert.equal(sharedDecisionForOwner(decision,owner,'oscillation'),true)
 assert.equal(sharedDecisionForOwner(decision,{...owner,asOf:'other'},'oscillation'),false)
 assert.equal(sharedDecisionForOwner(decision,{...owner,physicalContract:'RB2609'},'oscillation'),false)
 const missing=structuredClone(decision);missing.cdv2.facts[2]!.status='unavailable'
 assert.equal(sharedDecisionForOwner(missing,owner,'oscillation'),false)
 const wrongPrice={...decision,prices:{current_price:{physical_contract:'RB2609',segment_id:'old'}}} as unknown as NewowDecisionV2
 assert.equal(sharedDecisionForOwner(wrongPrice,owner,'trend'),false)
})
test('main rise can explicitly display trend background without adding main rise cross-period strategy',()=>{
 assert.equal(buildStatusCard(decision,'main_rise').risk,'unknown')
 const background=buildStatusCard(decision,'main_rise',undefined,true)
 assert.equal(background.day.state,'hold')
 assert.equal(background.week.state,'hold')
 assert.equal(background.version,'guiyi_newow_status_card_mainrise_background_v1')
 assert.equal(background.progress,null)
 const missing=structuredClone(decision);missing.cdv2.facts[1]!.status='unavailable'
 assert.equal(buildStatusCard(missing,'main_rise',undefined,true).risk,'unknown')
})

test('experiment calculation segment maps through chart facts to exactly one physical owner',()=>{
 const mapped=structuredClone(chart)
 Object.assign(mapped.value!.bars[0]!,{calculation_segment_id:'quality'})
 assert.equal(sharedChartForOwner(mapped,{...owner,segmentId:'quality'})?.value?.bars[0]?.segment_id,'owner')
 Object.assign(mapped.value!.bars[1]!,{physical_contract:owner.physicalContract,calculation_segment_id:'quality'})
 assert.equal(sharedChartForOwner(mapped,{...owner,segmentId:'quality'}),null)
})

test('same frequency shared prices cannot cross a quality calculation segment',()=>{
 const value={...decision,prices:{current_price:{physical_contract:owner.physicalContract,segment_id:owner.segmentId,frequency:'1d',calculation_segment_id:'current-quality'}}} as unknown as NewowDecisionV2
 assert.equal(sharedDecisionForOwner(value,{...owner,frequency:'1d',calculationSegmentId:'old-quality'},'oscillation'),false)
 assert.equal(sharedDecisionForOwner(value,{...owner,frequency:'1d',calculationSegmentId:'current-quality'},'oscillation'),true)
})

test('shared cutoff comparison preserves exact instant across equivalent ISO time zones',()=>{
 assert.ok(sharedChartForOwner(chart,{...owner,asOf:'2026-10-09T07:00:00+00:00'}))
 assert.ok(sharedDecisionForOwner(decision,{...owner,asOf:'2026-10-09T15:00:00+08:00'},'trend'))
 assert.equal(sharedDecisionForOwner(decision,{...owner,asOf:'2026-10-09T07:00:00.000001Z'},'trend'),false)
})
