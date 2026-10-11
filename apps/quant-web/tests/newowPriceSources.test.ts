import test from 'node:test'
import assert from 'node:assert/strict'
import { homePriceSources, chartPriceSources, decisionPriceSources } from '../src/utils/newowPriceSources.ts'
const source = {raw:'100',display_value:'100.00',frequency:'1d',bar_end:'2026-10-09T07:00:00Z',as_of:'2026-10-09T07:00:00Z',physical_contract:'RB2701',segment_id:'physical',calculation_segment_id:'calc',formula_version:'newow_chart_legend_hhv_llv10_page_v1',branch:'chart_hhv10',source_category:'canonical_channel',input_sha256:'a'.repeat(64)}
const fact = {input_sha256:'b'.repeat(64),price_input_sha256:source.input_sha256,status:'ready',target:'100',absorb:'90',as_of:source.as_of,bar_end:source.bar_end,physical_contract:source.physical_contract,segment_id:'physical',calculation_segment_id:'calc',price_formula_version:source.formula_version,price_sources:{target:source,absorb:{...source,raw:'90',display_value:'90.00',branch:'chart_llv10'}}}
test('home discloses exact price owners without treating page parity as private evidence',()=>{
 const rows=homePriceSources(fact)
 assert.equal(rows[0].available,true); assert.equal(rows[0].source?.branch,'chart_hhv10')
 assert.equal(rows[1].source?.calculation_segment_id,'calc')
 assert.equal(homePriceSources({...fact,price_sources:undefined})[0].available,false)
 for(const patch of [{frequency:'1w'},{physical_contract:'RB2610'},{calculation_segment_id:'old'},{bar_end:'2026-10-08T07:00:00Z'},{raw:'101'},{formula_version:'other'},{input_sha256:'invalid'},{input_sha256:'b'.repeat(64)}]) assert.equal(homePriceSources({...fact,price_sources:{...fact.price_sources,target:{...source,...patch}}})[0].available,false)
})
test('chart sources follow accepted summary prices and exact chart owner',()=>{
 const reference={...source,surface:'chart_legend',anchor_bar_end:source.bar_end,target:{raw:'100',display:'100.00',status:{status:'ready'}},absorb:{raw:'90',display:'90.00',status:{status:'ready'}}}
 const chart={meta:{as_of:source.as_of,identity:{frequency:'1d'}},value:{price_reference:reference,bars:[{...source,observation_eligible:true}]}}
 const summary={target:{display_value:'100.00'},absorb:{display_value:'90.00'}}
 assert.equal(chartPriceSources(chart,summary)[0].available,true)
 assert.equal(chartPriceSources(chart,{...summary,target:null})[0].available,false)
 assert.equal(chartPriceSources({...chart,meta:{as_of:'2026-10-10T07:00:00Z'}},summary)[0].available,false)
})
test('decision surfaces retain actual selected branches and independent source periods',()=>{
 const prices={as_of:source.as_of,formula_version:'selection',current_price:source,shared:{target:source,absorb:null},status_card:{target:{...source,frequency:'1w',bar_end:'2026-10-02T07:00:00Z',branch:'target_weekly'},absorb:{...source,raw:'90',branch:'status_card_weekly_llv10_override'}}}
 const rows=decisionPriceSources(prices)
 assert.equal(rows.length,6); assert.equal(rows[0].available,true);assert.equal(rows[1].available,false)
 assert.equal(rows[4].source?.branch,'current_price');assert.equal(rows[5].available,false)
 assert.equal(rows[2].source?.frequency,'1w');assert.equal(rows[3].source?.branch,'status_card_weekly_llv10_override')
 assert.equal(decisionPriceSources({...prices,status_card:{...prices.status_card,target:{...source,physical_contract:'RB2610'}}})[2].available,false)
 assert.equal(decisionPriceSources({...prices,shared:{...prices.shared,target:{...source,calculation_segment_id:'old'}}})[0].available,false)
 assert.equal(decisionPriceSources({...prices,shared:{...prices.shared,target:{...source,bar_end:'2026-10-10T07:00:00Z'}}})[0].available,false)
})
