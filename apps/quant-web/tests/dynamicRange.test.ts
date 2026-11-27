import assert from 'node:assert/strict'
import test from 'node:test'
import { mergeRangePoints, normalizeRangeResponse, matchesRangeBar, rangeRequestIssue, rangeDiagnosticReason, type DynamicRangePoint } from '../src/utils/dynamicRange.ts'

const bar={time:'2026-07-20T07:00:00Z',physicalContract:'JM2609',open:100,high:102,low:98,close:101,volume:1}
const point: DynamicRangePoint={time:bar.time,contract:'JM2609',open:100,high:102,low:98,close:101,regime:'RANGE',phase:'RANGE_ACTIVE',reason:null,er:.1,chop:65,trend_candidate:false,break_side:null,
  box:{box_id:'box',confirmed_at:'2026-07-19T07:00:00Z',lower:98,upper:102,atr_reference:2,revision:0}}
const response=()=>({version:'subing_dynamic_range_v2',trend_version:'subing_ema21_ols5_atr14_v2',profile:'bounded_confirmed',symbol:'jm',frequency:'30m',contract:'JM2609',source_proof:{lifecycle_hash:'c'.repeat(64),partitions:{'2026-1':'d'.repeat(64)}},source_hash:'a'.repeat(64),prefix_start:'2026-01-01T00:00:00Z',points:[point]})
test('display data is matched to physical candles and normalized without recalculation',()=>{
 const sourceBarSha256 = 'b'.repeat(64)
 const p=normalizeRangeResponse(response(),'jm','30m',[{ ...bar, sourceBarSha256 }])[0]
 assert.deepEqual(p,{ ...point, prefixSourceHash: response().source_hash, barSourceHash: sourceBarSha256 })
 assert.equal(matchesRangeBar(p,{...bar,sourceBarSha256}),true)
 assert.equal(matchesRangeBar(p,bar),false)
 assert.equal(matchesRangeBar(p,{...bar,sourceBarSha256,confirmed:false}),false)
 assert.equal(matchesRangeBar(p,{...bar,physicalContract:'JM2701'}),false)
 assert.equal(matchesRangeBar(p,{...bar,close:100}),false)
})
test('source/endpoint/future-confirmation errors cannot become a plotted range',()=>{
 for(const mutate of [(r:any)=>r.symbol='ma',(r:any)=>r.points=[],(r:any)=>r.prefix_start='2027-01-01',
  (r:any)=>r.points[0].box.confirmed_at='2027-01-01',(r:any)=>r.points[0].high=null,
  (r:any)=>r.points[0].box.upper=90,(r:any)=>r.points[0].close=100]){
 const r=structuredClone(response());mutate(r);assert.throws(()=>normalizeRangeResponse(r,'jm','30m',[bar]))
 }
})
test('prepend keeps existing snapshots and rejects retrospective boundary changes',()=>{
 const old=structuredClone(point)
 const earlier={...point,time:'2026-07-19T07:00:00Z'}
 const merged=mergeRangePoints([old],[earlier])
 assert.equal(merged[1],old)
 assert.deepEqual(merged[1].box,point.box)
 assert.throws(()=>mergeRangePoints([old],[{...point,box:{...point.box!,upper:103,revision:1}}]),/HISTORY_CHANGED/)
 assert.equal(mergeRangePoints([old],[point])[0],old)
})

test('requests and results expose only bounded diagnostic codes for the specific failure', () => {
  assert.equal(rangeRequestIssue('DYNAMIC_RANGE_PREFIX_UNAVAILABLE').status, 'missing_input')
  assert.equal(rangeRequestIssue('DYNAMIC_RANGE_COVERAGE_INVALID').status, 'invalid_source')
  assert.equal(rangeRequestIssue('DYNAMIC_RANGE_BUDGET_EXCEEDED').status, 'compute_error')
  assert.equal(rangeRequestIssue('unexpected error detail').code, 'DYNAMIC_RANGE_UNAVAILABLE')
  assert.equal(rangeDiagnosticReason('FACTOR_INPUT_INVALID'), 'FACTOR_INPUT_INVALID')
  assert.equal(rangeDiagnosticReason('unexpected error detail'), null)
})
