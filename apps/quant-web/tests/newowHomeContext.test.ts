import test from 'node:test'
import assert from 'node:assert/strict'
import { homeContext,parseHomeContext,homeContextChanged } from '../src/utils/newowHomeContext.ts'
import { parseMarketDetailRoute, serializeMarketDetailIdentity } from '../src/utils/marketDetailRoute.ts'
const identity={view:'newow',symbol:'rb',strategy:'trend',frequency:'1d',seriesKind:'actual_dominant'} as const
const context={product:'rb',strategy:'trend',frequency:'1d',as_of:'2026-10-19T07:00:00Z',input_sha256:'a'.repeat(64),physical_contract:'RB2701',segment_id:'s',calculation_segment_id:'c'}
test('home links roundtrip input identity and reject forged or foreign context',()=>{
 const query=serializeMarketDetailIdentity({...identity,homeContext:context})
 const result=parseMarketDetailRoute(query)
 assert.equal(result.kind,'valid');if(result.kind==='valid')assert.deepEqual(result.identity.homeContext,context)
 assert.equal(parseHomeContext({...context,product:'jm'},identity),null)
 assert.equal(parseHomeContext({...context,input_sha256:'bad'},identity),null)
 assert.equal(parseMarketDetailRoute({...query,home_context:'invalid'}).kind,'invalid')
 assert.equal(homeContext('rb','trend','1d',{status:'warming',state:null}),undefined)
})
test('new input, cutoff or physical owner shows update instead of silently reusing home event',()=>{
 const chart:any={meta:{identity:{product:'rb',strategy:'trend',frequency:'1d'},as_of:context.as_of,input_content_sha256:context.input_sha256},value:{bars:[{physical_contract:context.physical_contract,segment_id:'s',calculation_segment_id:'c'}]}}
 assert.equal(homeContextChanged(context,chart),false)
 for(const mutate of [(v:any)=>v.meta.input_content_sha256='b'.repeat(64),(v:any)=>v.meta.as_of='2026-10-20T07:00:00Z',(v:any)=>v.value.bars[0].physical_contract='RB2705']){const v=structuredClone(chart);mutate(v);assert.equal(homeContextChanged(context,v),true)}
})
